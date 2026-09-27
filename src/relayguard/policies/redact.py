"""Sensitive data redaction policy."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

import regex

from relayguard.exceptions import ConfigurationError, RedactionError
from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext

BUILTIN_PATTERNS: dict[str, str] = {
    "api_key": (
        r"\b(?:sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|"
        r"gh[pousr]_[A-Za-z0-9]{20,})\b"
    ),
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "phone": r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)",
}
SOURCE_FINGERPRINT_KEY = "relayguard.source_fingerprint"


class RedactPolicy(Policy):
    """Redact configured patterns from nested message content and metadata."""

    name = "redact"
    version = "2"

    def __init__(
        self,
        *,
        detectors: Iterable[str] = ("api_key", "email"),
        custom_patterns: Mapping[str, str] | None = None,
        stage: Literal["input", "egress"] = "input",
        max_pattern_bytes: int = 1_000,
        max_scan_bytes: int = 1_000_000,
        max_scan_strings: int = 10_000,
        timeout_ms: int = 50,
    ) -> None:
        if stage not in {"input", "egress"}:
            raise ConfigurationError("stage must be 'input' or 'egress'")
        self.stage = stage
        limits = {
            "max_pattern_bytes": max_pattern_bytes,
            "max_scan_bytes": max_scan_bytes,
            "max_scan_strings": max_scan_strings,
            "timeout_ms": timeout_ms,
        }
        for name, value in limits.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")
        if timeout_ms > 1_000:
            raise ConfigurationError("timeout_ms cannot exceed 1000")

        if custom_patterns is not None and not isinstance(custom_patterns, Mapping):
            raise ConfigurationError("custom_patterns must be a mapping")
        patterns = dict(custom_patterns or {})
        if len(patterns) > 32:
            raise ConfigurationError(
                "custom_patterns cannot contain more than 32 items"
            )
        if isinstance(detectors, (str, bytes)):
            raise ConfigurationError("detectors must be an iterable of names")
        try:
            detector_names = list(detectors)
        except TypeError as error:
            raise ConfigurationError(
                "detectors must be an iterable of names"
            ) from error
        for detector in detector_names:
            if not isinstance(detector, str):
                raise ConfigurationError("detector names must be strings")
            if detector not in BUILTIN_PATTERNS:
                choices = ", ".join(sorted(BUILTIN_PATTERNS))
                raise ConfigurationError(
                    f"Unknown redaction detector {detector!r}; choose from {choices}"
                )
            patterns[detector] = BUILTIN_PATTERNS[detector]
        self.patterns: dict[str, regex.Pattern[str]] = {}
        for name, pattern in patterns.items():
            if not isinstance(name, str) or not regex.fullmatch(
                r"[A-Za-z0-9_.-]{1,64}", name
            ):
                raise ConfigurationError(
                    "Redaction detector names must use 1-64 ASCII letters, "
                    "digits, dots, underscores, or hyphens"
                )
            if not isinstance(pattern, str):
                raise ConfigurationError(f"Redaction pattern {name!r} must be a string")
            if len(pattern.encode("utf-8")) > max_pattern_bytes:
                raise ConfigurationError(
                    f"Redaction pattern {name!r} exceeds max_pattern_bytes"
                )
            try:
                self.patterns[name] = regex.compile(pattern)
            except regex.error as error:
                position = getattr(error, "pos", None)
                suffix = f" at position {position}" if position is not None else ""
                raise ConfigurationError(
                    f"Invalid redaction pattern {name!r}{suffix}"
                ) from error
        self.max_scan_bytes = max_scan_bytes
        self.max_scan_strings = max_scan_strings
        self.timeout_seconds = timeout_ms / 1_000

    @staticmethod
    def _record_source_fingerprint(
        message: Message,
        context: PolicyContext,
    ) -> None:
        internal = dict(message.internal)
        if SOURCE_FINGERPRINT_KEY in internal:
            return
        public = message.model_dump(mode="json")
        public["tags"] = sorted(public["tags"])
        serialized = json.dumps(
            public,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        fingerprint = context._source_fingerprint(serialized)
        if fingerprint is None:
            return
        internal[SOURCE_FINGERPRINT_KEY] = fingerprint
        message._replace_internal(internal)

    def _redact_string(
        self,
        value: str,
        scan_state: list[int],
    ) -> tuple[str, int]:
        scan_state[0] += len(value.encode("utf-8"))
        scan_state[1] += 1
        if scan_state[0] > self.max_scan_bytes:
            raise RedactionError(
                f"Redaction input exceeds max_scan_bytes={self.max_scan_bytes}."
            )
        if scan_state[1] > self.max_scan_strings:
            raise RedactionError(
                f"Redaction input exceeds max_scan_strings={self.max_scan_strings}."
            )
        output = value
        total = 0
        for name, pattern in self.patterns.items():
            try:
                output, count = pattern.subn(
                    f"[REDACTED:{name}]",
                    output,
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as error:
                raise RedactionError(
                    f"Redaction detector {name!r} exceeded its timeout."
                ) from error
            total += count
        return output, total

    def _redact_value(
        self,
        value: Any,
        scan_state: list[int],
    ) -> tuple[Any, int]:
        if isinstance(value, str):
            return self._redact_string(value, scan_state)
        if isinstance(value, list):
            list_items: list[Any] = []
            total = 0
            for item in value:
                cleaned, count = self._redact_value(item, scan_state)
                list_items.append(cleaned)
                total += count
            return list_items, total
        if isinstance(value, dict):
            mapping_items: dict[Any, Any] = {}
            total = 0
            for key, item in value.items():
                if isinstance(key, str):
                    cleaned_key, key_count = self._redact_string(key, scan_state)
                else:
                    cleaned_key, key_count = key, 0
                cleaned, count = self._redact_value(item, scan_state)
                candidate_key = cleaned_key
                suffix = 2
                while candidate_key in mapping_items:
                    candidate_key = f"{cleaned_key}__{suffix}"
                    suffix += 1
                mapping_items[candidate_key] = cleaned
                total += key_count + count
            return mapping_items, total
        return value, 0

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        total = 0
        scan_state = [0, 0]

        output.sender, count = self._redact_string(output.sender, scan_state)
        total += count
        output.receiver, count = self._redact_string(output.receiver, scan_state)
        total += count
        output.metadata, count = self._redact_value(output.metadata, scan_state)
        total += count
        for message in output.messages:
            self._record_source_fingerprint(message, context)
            message.role, count = self._redact_string(message.role, scan_state)
            total += count
            message.kind, count = self._redact_string(message.kind, scan_state)
            total += count
            cleaned_tags: set[str] = set()
            for tag in message.tags:
                cleaned_tag, count = self._redact_string(tag, scan_state)
                cleaned_tags.add(cleaned_tag)
                total += count
            message.tags = cleaned_tags
            message.content, count = self._redact_value(message.content, scan_state)
            total += count
            message.metadata, count = self._redact_value(message.metadata, scan_state)
            total += count
        for artifact in output.artifacts:
            artifact.name, count = self._redact_string(artifact.name, scan_state)
            total += count
            artifact.media_type, count = self._redact_string(
                artifact.media_type, scan_state
            )
            total += count
            artifact.content, count = self._redact_value(artifact.content, scan_state)
            total += count
            artifact.metadata, count = self._redact_value(artifact.metadata, scan_state)
            total += count
        context.report.sender = output.sender
        context.report.receiver = output.receiver
        context.report.redactions += total
        context.report.add_event(
            self.name,
            "redacted",
            count=total,
            details={
                "detectors": sorted(self.patterns),
                "stage": self.stage,
            },
        )
        return output
