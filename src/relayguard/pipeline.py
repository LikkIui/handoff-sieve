"""Handoff policy pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
from pathlib import Path
from typing import Any, Literal

from relayguard.exceptions import (
    PolicyExecutionError,
    RelayGuardError,
    ReservedFieldError,
    UnmatchedRouteError,
)
from relayguard.models import HandoffEnvelope, HandoffResult, Message
from relayguard.policies.base import Policy, PolicyContext
from relayguard.report import AuditReport
from relayguard.tokens import ApproxTokenCounter, TokenCounter


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """Policies activated for matching sender and receiver names."""

    sender: str
    receiver: str
    policies: tuple[Policy, ...]

    def matches(self, sender: str, receiver: str) -> bool:
        return fnmatchcase(sender, self.sender) and fnmatchcase(receiver, self.receiver)


class HandoffPipeline:
    """Apply ordered policies to an agent handoff."""

    def __init__(
        self,
        policies: Sequence[Policy] | None = None,
        *,
        rules: Sequence[PolicyRule] | None = None,
        token_counter: TokenCounter | None = None,
        on_unmatched: Literal["error", "warn", "pass"] = "error",
    ) -> None:
        if on_unmatched not in {"error", "warn", "pass"}:
            raise ValueError("on_unmatched must be 'error', 'warn', or 'pass'")
        self.policies = list(policies or [])
        self.rules = list(rules or [])
        self.token_counter = token_counter or ApproxTokenCounter()
        self.on_unmatched = on_unmatched

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        token_counter: TokenCounter | None = None,
    ) -> "HandoffPipeline":
        """Load a pipeline from a safe, built-in-only YAML configuration."""

        from relayguard.config import load_config

        loaded = load_config(path)
        return cls(
            loaded.policies,
            rules=loaded.rules,
            token_counter=token_counter,
            on_unmatched=loaded.on_unmatched,
        )

    def process_envelope(self, envelope: HandoffEnvelope) -> HandoffResult:
        """Process a public envelope after discarding private message state."""

        public_envelope = HandoffEnvelope.model_validate(
            envelope.model_dump(mode="python")
        )
        return self._run_envelope(public_envelope)

    def _process_trusted_envelope(self, envelope: HandoffEnvelope) -> HandoffResult:
        """Process an envelope whose private state came from a trusted adapter."""

        return self._run_envelope(envelope)

    def _run_envelope(self, envelope: HandoffEnvelope) -> HandoffResult:
        """Run policies without mutating the caller's object."""

        current = envelope.model_copy(deep=True)
        report = AuditReport(
            sender=current.sender,
            receiver=current.receiver,
            token_counter=self.token_counter.name,
        )
        try:
            report.original_tokens = self.token_counter.count_envelope(current)
        except Exception as error:
            code = self._exception_code(error)
            self._mark_denied(report, policy="token_counter", code=code)
            if isinstance(error, RelayGuardError):
                error.report = report
                raise
            raise PolicyExecutionError(
                f"Token counting denied the handoff ({code}).",
                report=report,
            ) from error
        context = PolicyContext(token_counter=self.token_counter, report=report)

        active_policies = list(self.policies)
        matching_rules = [
            rule
            for rule in self.rules
            if rule.matches(current.sender, current.receiver)
        ]
        for rule in matching_rules:
            active_policies.extend(rule.policies)
        if matching_rules:
            report.add_event("config", "rules_matched", count=len(matching_rules))
        elif self.rules:
            report.add_event(
                "config",
                "route_unmatched",
                details={"behavior": self.on_unmatched},
            )
            message = (
                f"No policy rule matched handoff {current.sender!r} -> "
                f"{current.receiver!r}."
            )
            if self.on_unmatched == "error":
                error = UnmatchedRouteError(message)
                self._mark_denied(
                    report,
                    policy="config",
                    code="unmatched_route",
                )
                error.report = report
                raise error
            if self.on_unmatched == "warn":
                report.warnings.append(message)

        for policy in active_policies:
            try:
                current = policy.apply(current, context)
            except Exception as error:
                code = self._exception_code(error)
                self._mark_denied(report, policy=policy.name, code=code)
                if isinstance(error, RelayGuardError):
                    error.report = report
                    raise
                raise PolicyExecutionError(
                    f"Policy {policy.name!r} denied the handoff ({code}).",
                    report=report,
                ) from error

        try:
            report.transmitted_tokens = self.token_counter.count_envelope(current)
        except Exception as error:
            code = self._exception_code(error)
            self._mark_denied(report, policy="token_counter", code=code)
            if isinstance(error, RelayGuardError):
                error.report = report
                raise
            raise PolicyExecutionError(
                f"Token counting denied the handoff ({code}).",
                report=report,
            ) from error
        return HandoffResult(envelope=current, report=report)

    @staticmethod
    def _exception_code(error: Exception) -> str:
        name = type(error).__name__
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        return snake.removesuffix("_error") or "policy_error"

    @staticmethod
    def _mark_denied(
        report: AuditReport,
        *,
        policy: str,
        code: str,
    ) -> None:
        report.status = "denied"
        report.failure_code = code
        report.failed_policy = policy
        report.transmitted_tokens = 0
        report.add_event(
            policy,
            "denied",
            details={"reason_code": code},
        )

    def process(
        self,
        *,
        sender: str,
        receiver: str,
        messages: Iterable[Message | str | dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """Normalize common message inputs and run the policy pipeline."""

        try:
            normalized = [self._normalize_message(item) for item in messages]
            envelope = HandoffEnvelope(
                sender=sender,
                receiver=receiver,
                messages=normalized,
                metadata=metadata or {},
            )
        except Exception as error:
            report = AuditReport(
                sender=str(sender),
                receiver=str(receiver),
                token_counter=self.token_counter.name,
            )
            code = self._exception_code(error)
            self._mark_denied(report, policy="normalization", code=code)
            if isinstance(error, RelayGuardError):
                error.report = report
                raise
            raise PolicyExecutionError(
                f"Input normalization denied the handoff ({code}).",
                report=report,
            ) from error
        return self.process_envelope(envelope)

    @staticmethod
    def _normalize_message(item: Message | str | dict[str, Any]) -> Message:
        if isinstance(item, Message):
            # Re-validate only the public representation. Private processing
            # state is trusted only when an adapter calls process_envelope().
            return Message.model_validate(item.model_dump(mode="python"))
        if isinstance(item, str):
            return Message(content=item)
        reserved = {"protected", "internal", "_protected", "_internal"}
        attempted = sorted(reserved.intersection(item))
        if attempted:
            raise ReservedFieldError(
                "Message input cannot set internal fields: " + ", ".join(attempted)
            )
        if "content" in item:
            return Message.model_validate(item)
        return Message(content=item, kind="structured")
