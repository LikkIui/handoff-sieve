"""Critical-content preservation policy."""

from __future__ import annotations

from collections.abc import Iterable

from handoff_sieve.models import HandoffEnvelope, Message
from handoff_sieve.policies.base import Policy, PolicyContext


class PreservePolicy(Policy):
    """Protect messages identified by tags or structured field names."""

    name = "preserve"

    def __init__(
        self,
        *,
        tags: Iterable[str] = ("constraint", "citation", "conclusion"),
        fields: Iterable[str] = ("constraints", "citations", "conclusions"),
    ) -> None:
        self.tags = set(tags)
        self.fields = set(fields)

    def _should_protect(self, message: Message) -> bool:
        if message.tags.intersection(self.tags):
            return True
        if isinstance(message.content, dict):
            if set(message.content).intersection(self.fields):
                return True
        category = message.metadata.get("category")
        return isinstance(category, str) and category in self.tags

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        protected = 0
        for message in output.messages:
            if self._should_protect(message):
                if not message.protected:
                    protected += 1
                message._mark_protected()
        context.report.protected_messages += protected
        context.report.add_event(self.name, "protected", count=protected)
        return output
