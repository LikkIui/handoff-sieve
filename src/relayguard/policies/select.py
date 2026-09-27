"""Message selection policy."""

from __future__ import annotations

from collections.abc import Iterable

from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext


class SelectPolicy(Policy):
    """Keep messages matching configured roles, kinds, or tags.

    Different selectors are combined with AND. A selector that is not set does
    not restrict messages. Already protected messages are always retained.
    """

    name = "select"

    def __init__(
        self,
        *,
        roles: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
    ) -> None:
        self.roles = set(roles or [])
        self.kinds = set(kinds or [])
        self.tags = set(tags or [])

    def _matches(self, message: Message) -> bool:
        if self.roles and message.role not in self.roles:
            return False
        if self.kinds and message.kind not in self.kinds:
            return False
        if self.tags and not message.tags.intersection(self.tags):
            return False
        return True

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        before = len(output.messages)
        output.messages = [
            message
            for message in output.messages
            if message.protected or self._matches(message)
        ]
        removed = before - len(output.messages)
        context.report.removed_messages += removed
        context.report.add_event(self.name, "selected", count=removed)
        return output
