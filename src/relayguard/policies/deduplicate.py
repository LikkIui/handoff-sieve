"""Deterministic exact-message deduplication."""

from __future__ import annotations

import json

from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext
from relayguard.policies.redact import SOURCE_FINGERPRINT_KEY


class ExactDedupPolicy(Policy):
    """Remove messages whose complete public representation is identical."""

    name = "deduplicate"
    version = "2"

    @staticmethod
    def _key(message: Message) -> str:
        source_fingerprint = message.internal.get(SOURCE_FINGERPRINT_KEY)
        if isinstance(source_fingerprint, str):
            return f"source:{source_fingerprint}"
        data = message.model_dump(mode="json")
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _clear_source_fingerprint(message: Message) -> None:
        if SOURCE_FINGERPRINT_KEY not in message.internal:
            return
        internal = dict(message.internal)
        internal.pop(SOURCE_FINGERPRINT_KEY, None)
        message._replace_internal(internal)

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        unique: list[Message] = []
        positions: dict[str, int] = {}
        removed = 0

        for message in output.messages:
            # ``protected`` means no destructive policy may silently remove this
            # occurrence. This is especially important for framework control
            # items and repeated constraints that happen to have equal content.
            if message.protected:
                unique.append(message)
                continue
            key = self._key(message)
            if key not in positions:
                positions[key] = len(unique)
                unique.append(message)
                continue

            removed += 1

        for message in unique:
            self._clear_source_fingerprint(message)
        output.messages = unique
        context.report.removed_messages += removed
        context.report.duplicates_removed += removed
        context.report.add_event(self.name, "duplicates_removed", count=removed)
        return output
