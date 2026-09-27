"""Sensitive data redaction policy."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Pattern

from relayguard.models import HandoffEnvelope
from relayguard.policies.base import Policy, PolicyContext


BUILTIN_PATTERNS: dict[str, str] = {
    "api_key": (
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|"
        r"gh[pousr]_[A-Za-z0-9]{20,})\b"
    ),
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone": r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)",
}


class RedactPolicy(Policy):
    """Redact configured patterns from nested message content and metadata."""

    name = "redact"

    def __init__(
        self,
        *,
        detectors: Iterable[str] = ("api_key", "email"),
        custom_patterns: Mapping[str, str] | None = None,
    ) -> None:
        patterns = dict(custom_patterns or {})
        for detector in detectors:
            if detector not in BUILTIN_PATTERNS:
                choices = ", ".join(sorted(BUILTIN_PATTERNS))
                raise ValueError(
                    f"Unknown redaction detector {detector!r}; choose from {choices}"
                )
            patterns[detector] = BUILTIN_PATTERNS[detector]
        self.patterns: dict[str, Pattern[str]] = {
            name: re.compile(pattern) for name, pattern in patterns.items()
        }

    def _redact_string(self, value: str) -> tuple[str, int]:
        output = value
        total = 0
        for name, pattern in self.patterns.items():
            output, count = pattern.subn(f"[REDACTED:{name}]", output)
            total += count
        return output, total

    def _redact_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            return self._redact_string(value)
        if isinstance(value, list):
            items: list[Any] = []
            total = 0
            for item in value:
                cleaned, count = self._redact_value(item)
                items.append(cleaned)
                total += count
            return items, total
        if isinstance(value, dict):
            items: dict[Any, Any] = {}
            total = 0
            for key, item in value.items():
                if isinstance(key, str):
                    cleaned_key, key_count = self._redact_string(key)
                else:
                    cleaned_key, key_count = key, 0
                cleaned, count = self._redact_value(item)
                candidate_key = cleaned_key
                suffix = 2
                while candidate_key in items:
                    candidate_key = f"{cleaned_key}__{suffix}"
                    suffix += 1
                items[candidate_key] = cleaned
                total += key_count + count
            return items, total
        return value, 0

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        total = 0

        output.sender, count = self._redact_string(output.sender)
        total += count
        output.receiver, count = self._redact_string(output.receiver)
        total += count
        output.metadata, count = self._redact_value(output.metadata)
        total += count
        for message in output.messages:
            message.role, count = self._redact_string(message.role)
            total += count
            message.kind, count = self._redact_string(message.kind)
            total += count
            cleaned_tags: set[str] = set()
            for tag in message.tags:
                cleaned_tag, count = self._redact_string(tag)
                cleaned_tags.add(cleaned_tag)
                total += count
            message.tags = cleaned_tags
            message.content, count = self._redact_value(message.content)
            total += count
            message.metadata, count = self._redact_value(message.metadata)
            total += count
        for artifact in output.artifacts:
            artifact.name, count = self._redact_string(artifact.name)
            total += count
            artifact.media_type, count = self._redact_string(artifact.media_type)
            total += count
            artifact.content, count = self._redact_value(artifact.content)
            total += count
            artifact.metadata, count = self._redact_value(artifact.metadata)
            total += count
        context.report.sender = output.sender
        context.report.receiver = output.receiver
        context.report.redactions += total
        context.report.add_event(
            self.name,
            "redacted",
            count=total,
            details={"detectors": sorted(self.patterns)},
        )
        return output

