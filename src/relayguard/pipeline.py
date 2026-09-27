"""Handoff policy pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, NoReturn

from relayguard.exceptions import (
    AmbiguousRouteError,
    AuditExportError,
    ConfigurationError,
    PolicyExecutionError,
    RelayGuardError,
    ReservedFieldError,
    UnmatchedRouteError,
)
from relayguard.models import HandoffEnvelope, HandoffResult, Message
from relayguard.policies.base import Policy, PolicyContext
from relayguard.report import AuditReport
from relayguard.reporters import AuditReporter
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
        reporters: Sequence[AuditReporter] | None = None,
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
        self.reporters = list(reporters or [])
        self.on_unmatched = on_unmatched
        self.on_multiple_match = on_multiple_match
        self._validate_policy_order(self.policies, location="global policies")
        for index, rule in enumerate(self.rules):
            self._validate_policy_order(
                rule.policies,
                location=f"rule {rule.rule_id or index + 1}",
            )
        self.config_fingerprint = self._configuration_fingerprint()

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        token_counter: TokenCounter | None = None,
        reporters: Sequence[AuditReporter] | None = None,
    ) -> HandoffPipeline:
        """Load a pipeline from a safe, built-in-only YAML configuration."""

        from relayguard.config import load_config

        loaded = load_config(path)
        return cls(
            loaded.policies,
            rules=loaded.rules,
            token_counter=token_counter,
            reporters=reporters,
            on_unmatched=loaded.on_unmatched,
            on_multiple_match=loaded.on_multiple_match,
        )

    def process_envelope(
        self,
        envelope: HandoffEnvelope,
        *,
        request_id: str | None = None,
    ) -> HandoffResult:
        """Process a public envelope after discarding private message state."""

        started = perf_counter()
        report = self._new_report(
            sender=envelope.sender,
            receiver=envelope.receiver,
            request_id=request_id,
        )
        try:
            public_envelope = HandoffEnvelope.model_validate(
                envelope.model_dump(mode="python")
            )
        except Exception as validation_error:
            self._raise_finalized_failure(
                validation_error,
                report=report,
                started=started,
                policy="normalization",
            )
        return self._run_envelope(
            public_envelope,
            request_id=request_id,
            started=started,
            report=report,
        )

    def _process_trusted_envelope(
        self,
        envelope: HandoffEnvelope,
        *,
        request_id: str | None = None,
    ) -> HandoffResult:
        """Process an envelope whose private state came from a trusted adapter."""

        return self._run_envelope(envelope, request_id=request_id)

    def _run_envelope(
        self,
        envelope: HandoffEnvelope,
        *,
        request_id: str | None = None,
        started: float | None = None,
        report: AuditReport | None = None,
    ) -> HandoffResult:
        """Run policies, finalize one report, and export it exactly once."""

        if started is None:
            started = perf_counter()
        if report is None:
            report = self._new_report(
                sender=envelope.sender,
                receiver=envelope.receiver,
                request_id=request_id,
            )
        try:
            current = envelope.model_copy(deep=True)
            result = self._execute_envelope(current, report)
        except Exception as error:
            self._raise_finalized_failure(
                error,
                report=report,
                started=started,
                policy="pipeline",
            )

        report.finish(duration_ms=(perf_counter() - started) * 1_000)
        self._emit_report(report, suppress_errors=False)
        return result

    def _execute_envelope(
        self,
        current: HandoffEnvelope,
        report: AuditReport,
    ) -> HandoffResult:
        """Apply route and policy logic to a private envelope copy."""

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
            event_start = len(report.events)
            policy_version = str(getattr(policy, "version", "1"))
            try:
                current = policy.apply(current, context)
            except Exception as policy_error:
                self._set_event_versions(
                    report,
                    start=event_start,
                    policy_version=policy_version,
                )
                code = self._exception_code(policy_error)
                self._mark_denied(
                    report,
                    policy=policy.name,
                    policy_version=policy_version,
                    code=code,
                )
                if isinstance(policy_error, RelayGuardError):
                    policy_error.report = report
                    raise
                raise PolicyExecutionError(
                    f"Policy {policy.name!r} denied the handoff ({code}).",
                    report=report,
                ) from policy_error
            self._set_event_versions(
                report,
                start=event_start,
                policy_version=policy_version,
            )

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

    def _new_report(
        self,
        *,
        sender: str,
        receiver: str,
        request_id: str | None,
    ) -> AuditReport:
        return AuditReport(
            sender=str(sender),
            receiver=str(receiver),
            token_counter=self.token_counter.name,
            config_fingerprint=self.config_fingerprint,
            request_id=request_id,
        )

    def _prepare_failure(
        self,
        error: Exception,
        report: AuditReport,
    ) -> RelayGuardError:
        if report.status != "denied":
            code = self._exception_code(error)
            self._mark_denied(report, policy="pipeline", code=code)
        if isinstance(error, RelayGuardError):
            error.report = report
            return error
        return PolicyExecutionError(
            f"Pipeline denied the handoff ({report.failure_code}).",
            report=report,
        )

    def _raise_finalized_failure(
        self,
        error: Exception,
        *,
        report: AuditReport,
        started: float,
        policy: str,
    ) -> NoReturn:
        if report.status != "denied":
            self._mark_denied(
                report,
                policy=policy,
                code=self._exception_code(error),
            )
        raised = self._prepare_failure(error, report)
        report.finish(duration_ms=(perf_counter() - started) * 1_000)
        self._emit_report(report, suppress_errors=True)
        if raised is error:
            raise error
        raise raised from error

    def _emit_report(
        self,
        report: AuditReport,
        *,
        suppress_errors: bool,
    ) -> None:
        for reporter in self.reporters:
            try:
                reporter.emit(report.model_copy(deep=True))
            except Exception as export_error:
                reporter_name = type(reporter).__name__
                report.warnings.append(
                    f"Audit reporter {reporter_name!r} failed to emit the report."
                )
                report.add_event(
                    "audit",
                    "reporter_failed",
                    details={"reporter": reporter_name},
                )
                if suppress_errors:
                    continue
                self._mark_denied(
                    report,
                    policy="audit",
                    code="audit_export",
                )
                raise AuditExportError(
                    "Audit export failed; the handoff was denied.",
                    report=report,
                ) from export_error

    @staticmethod
    def _set_event_versions(
        report: AuditReport,
        *,
        start: int,
        policy_version: str,
    ) -> None:
        for event in report.events[start:]:
            event.policy_version = policy_version

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
        policy_version: str = "1",
    ) -> None:
        report.status = "denied"
        report.failure_code = code
        report.failed_policy = policy
        report.transmitted_tokens = 0
        report.add_event(
            policy,
            "denied",
            policy_version=policy_version,
            details={"reason_code": code},
        )

    @classmethod
    def _fingerprint_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, type):
            return f"{value.__module__}.{value.__qualname__}"
        if isinstance(value, dict):
            items = [
                [cls._fingerprint_value(key), cls._fingerprint_value(item)]
                for key, item in value.items()
            ]
            return sorted(
                items,
                key=lambda item: json.dumps(item[0], sort_keys=True, default=str),
            )
        if isinstance(value, (list, tuple)):
            return [cls._fingerprint_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = [cls._fingerprint_value(item) for item in value]
            return sorted(
                items,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        pattern = getattr(value, "pattern", None)
        if isinstance(pattern, str):
            return {
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "pattern": pattern,
            }
        return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}

    @classmethod
    def _policy_fingerprint_value(cls, policy: Policy) -> dict[str, Any]:
        try:
            attributes = {
                name: cls._fingerprint_value(value)
                for name, value in vars(policy).items()
                if not name.startswith("_")
            }
        except TypeError:
            attributes = {}
        return {
            "type": f"{type(policy).__module__}.{type(policy).__qualname__}",
            "name": policy.name,
            "version": str(getattr(policy, "version", "1")),
            "attributes": attributes,
        }

    def _configuration_fingerprint(self) -> str:
        material = {
            "policies": [
                self._policy_fingerprint_value(policy) for policy in self.policies
            ],
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "sender": rule.sender,
                    "receiver": rule.receiver,
                    "policies": [
                        self._policy_fingerprint_value(policy)
                        for policy in rule.policies
                    ],
                }
                for rule in self.rules
            ],
            "token_counter": {
                "type": (
                    f"{type(self.token_counter).__module__}."
                    f"{type(self.token_counter).__qualname__}"
                ),
                "name": self.token_counter.name,
            },
            "on_unmatched": self.on_unmatched,
            "on_multiple_match": self.on_multiple_match,
        }
        serialized = json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def process(
        self,
        *,
        sender: str,
        receiver: str,
        messages: Iterable[Message | str | dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> HandoffResult:
        """Normalize common message inputs and run the policy pipeline."""

        started = perf_counter()
        report = self._new_report(
            sender=sender,
            receiver=receiver,
            request_id=request_id,
        )
        try:
            normalized = [self._normalize_message(item) for item in messages]
            envelope = HandoffEnvelope(
                sender=sender,
                receiver=receiver,
                messages=normalized,
                metadata=metadata or {},
            )
        except Exception as normalization_error:
            self._raise_finalized_failure(
                normalization_error,
                report=report,
                started=started,
                policy="normalization",
            )
        return self._run_envelope(
            envelope,
            request_id=request_id,
            started=started,
            report=report,
        )

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
