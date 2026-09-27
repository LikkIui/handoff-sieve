"""Deterministic exact-message deduplication."""

from __future__ import annotations

import json

from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext


class ExactDedupPolicy(Policy):
    """Remove messages whose complete public representation is identical."""

    name = "deduplicate"

    @staticmethod
    def _key(message: Message) -> str:
        data = message.model_dump(mode="json")
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)

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

        output.messages = unique
        context.report.removed_messages += removed
        context.report.duplicates_removed += removed
        context.report.add_event(self.name, "duplicates_removed", count=removed)
        return output
