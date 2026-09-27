"""Handoff policy pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal

from relayguard.exceptions import (
    AmbiguousRouteError,
    ConfigurationError,
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
    rule_id: str = ""

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
        on_multiple_match: Literal["error", "first", "all"] = "error",
    ) -> None:
        if on_unmatched not in {"error", "warn", "pass"}:
            raise ValueError("on_unmatched must be 'error', 'warn', or 'pass'")
        if on_multiple_match not in {"error", "first", "all"}:
            raise ValueError("on_multiple_match must be 'error', 'first', or 'all'")
        self.policies = list(policies or [])
        self.rules = list(rules or [])
        self.token_counter = token_counter or ApproxTokenCounter()
        self.on_unmatched = on_unmatched
        self.on_multiple_match = on_multiple_match
        self._validate_policy_order(self.policies, location="global policies")
        for index, rule in enumerate(self.rules):
            self._validate_policy_order(
                rule.policies,
                location=f"rule {rule.rule_id or index + 1}",
            )

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        token_counter: TokenCounter | None = None,
    ) -> HandoffPipeline:
        """Load a pipeline from a safe, built-in-only YAML configuration."""

        from relayguard.config import load_config

        loaded = load_config(path)
        return cls(
            loaded.policies,
            rules=loaded.rules,
            token_counter=token_counter,
            on_unmatched=loaded.on_unmatched,
            on_multiple_match=loaded.on_multiple_match,
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
        except Exception as count_error:
            code = self._exception_code(count_error)
            self._mark_denied(report, policy="token_counter", code=code)
            if isinstance(count_error, RelayGuardError):
                count_error.report = report
                raise
            raise PolicyExecutionError(
                f"Token counting denied the handoff ({code}).",
                report=report,
            ) from count_error
        context = PolicyContext(token_counter=self.token_counter, report=report)

        active_policies = list(self.policies)
        all_matching_rules = [
            (index, rule)
            for index, rule in enumerate(self.rules)
            if rule.matches(current.sender, current.receiver)
        ]
        all_rule_ids = [
            rule.rule_id or f"rule-{index + 1}" for index, rule in all_matching_rules
        ]
        if len(all_matching_rules) > 1 and self.on_multiple_match == "error":
            report.add_event(
                "config",
                "route_ambiguous",
                count=len(all_matching_rules),
                details={"rule_ids": all_rule_ids},
            )
            route_error = AmbiguousRouteError(
                "Multiple policy rules matched this handoff; set "
                "on_multiple_match to 'first' or 'all' only when intentional."
            )
            self._mark_denied(
                report,
                policy="config",
                code="ambiguous_route",
            )
            route_error.report = report
            raise route_error
        matching_rules = (
            all_matching_rules[:1]
            if self.on_multiple_match == "first"
            else all_matching_rules
        )
        for _, rule in matching_rules:
            active_policies.extend(rule.policies)
        if matching_rules:
            applied_rule_ids = [
                rule.rule_id or f"rule-{index + 1}" for index, rule in matching_rules
            ]
            report.add_event(
                "config",
                "rules_matched",
                count=len(matching_rules),
                details={
                    "rule_ids": applied_rule_ids,
                    "multiple_match_behavior": self.on_multiple_match,
                },
            )
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
                unmatched_error = UnmatchedRouteError(message)
                self._mark_denied(
                    report,
                    policy="config",
                    code="unmatched_route",
                )
                unmatched_error.report = report
                raise unmatched_error
            if self.on_unmatched == "warn":
                report.warnings.append(message)

        try:
            self._validate_policy_order(
                active_policies,
                location="active handoff policies",
            )
        except ConfigurationError as order_error:
            self._mark_denied(
                report,
                policy="config",
                code="unsafe_policy_order",
            )
            order_error.report = report
            raise

        for policy in active_policies:
            try:
                current = policy.apply(current, context)
            except Exception as policy_error:
                code = self._exception_code(policy_error)
                self._mark_denied(report, policy=policy.name, code=code)
                if isinstance(policy_error, RelayGuardError):
                    policy_error.report = report
                    raise
                raise PolicyExecutionError(
                    f"Policy {policy.name!r} denied the handoff ({code}).",
                    report=report,
                ) from policy_error

        try:
            report.transmitted_tokens = self.token_counter.count_envelope(current)
        except Exception as transmitted_count_error:
            code = self._exception_code(transmitted_count_error)
            self._mark_denied(report, policy="token_counter", code=code)
            if isinstance(transmitted_count_error, RelayGuardError):
                transmitted_count_error.report = report
                raise
            raise PolicyExecutionError(
                f"Token counting denied the handoff ({code}).",
                report=report,
            ) from transmitted_count_error
        return HandoffResult(envelope=current, report=report)

    @staticmethod
    def _exception_code(error: Exception) -> str:
        name = type(error).__name__
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        return snake.removesuffix("_error") or "policy_error"

    @staticmethod
    def _validate_policy_order(
        policies: Sequence[Policy],
        *,
        location: str,
    ) -> None:
        ranks = {
            "preserve": 10,
            "redact": 20,
            "schema": 25,
            "deduplicate": 30,
            "select": 40,
            "summarize": 40,
            "budget": 50,
        }
        previous_rank = -1
        previous_name = ""
        for policy in policies:
            name = policy.name
            rank = ranks.get(name)
            if rank is None:
                continue
            if rank < previous_rank:
                raise ConfigurationError(
                    f"Unsafe policy order in {location}: {name!r} cannot run "
                    f"after {previous_name!r}. Recommended order is preserve, "
                    "redact, schema, deduplicate, select or summarize, budget."
                )
            previous_rank = rank
            previous_name = name

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
        except Exception as normalization_error:
            report = AuditReport(
                sender=str(sender),
                receiver=str(receiver),
                token_counter=self.token_counter.name,
            )
            code = self._exception_code(normalization_error)
            self._mark_denied(report, policy="normalization", code=code)
            if isinstance(normalization_error, RelayGuardError):
                normalization_error.report = report
                raise
            raise PolicyExecutionError(
                f"Input normalization denied the handoff ({code}).",
                report=report,
            ) from normalization_error
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
