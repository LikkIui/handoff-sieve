"""Handoff policy pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

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
    ) -> None:
        self.policies = list(policies or [])
        self.rules = list(rules or [])
        self.token_counter = token_counter or ApproxTokenCounter()

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
        )

    def process_envelope(self, envelope: HandoffEnvelope) -> HandoffResult:
        """Process an existing envelope without mutating the caller's object."""

        current = envelope.model_copy(deep=True)
        report = AuditReport(
            sender=current.sender,
            receiver=current.receiver,
            token_counter=self.token_counter.name,
            original_tokens=self.token_counter.count_envelope(current),
        )
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

        for policy in active_policies:
            current = policy.apply(current, context)

        report.transmitted_tokens = self.token_counter.count_envelope(current)
        return HandoffResult(envelope=current, report=report)

    def process(
        self,
        *,
        sender: str,
        receiver: str,
        messages: Iterable[Message | str | dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """Normalize common message inputs and run the policy pipeline."""

        normalized = [self._normalize_message(item) for item in messages]
        envelope = HandoffEnvelope(
            sender=sender,
            receiver=receiver,
            messages=normalized,
            metadata=metadata or {},
        )
        return self.process_envelope(envelope)

    @staticmethod
    def _normalize_message(item: Message | str | dict[str, Any]) -> Message:
        if isinstance(item, Message):
            return item.model_copy(deep=True)
        if isinstance(item, str):
            return Message(content=item)
        if "content" in item:
            return Message.model_validate(item)
        return Message(content=item, kind="structured")
