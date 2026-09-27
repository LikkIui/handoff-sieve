"""Structured message validation policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, create_model

from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext


class SchemaPolicy(Policy):
    """Validate selected structured messages with a Pydantic model."""

    name = "schema"

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        *,
        required_fields: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
        normalize: bool = True,
    ) -> None:
        fields = list(required_fields or [])
        if schema is None and not fields:
            raise ValueError("schema or required_fields must be provided")
        if schema is not None and fields:
            raise ValueError("provide schema or required_fields, not both")
        self.schema = schema or create_model(
            "InlineHandoffSchema",
            **{field: (Any, ...) for field in fields},
        )
        self.kinds = set(kinds or ["structured"])
        self.normalize = normalize

    def _applies(self, message: Message) -> bool:
        return not self.kinds or message.kind in self.kinds

    @classmethod
    def _diff_counts(cls, before: Any, after: Any) -> tuple[int, int]:
        """Return changed nodes and removed mapping fields without values."""

        if isinstance(before, Mapping) and isinstance(after, Mapping):
            before_keys = set(before)
            after_keys = set(after)
            removed = len(before_keys - after_keys)
            changed = len(before_keys ^ after_keys)
            for key in before_keys & after_keys:
                nested_changed, nested_removed = cls._diff_counts(
                    before[key], after[key]
                )
                changed += nested_changed
                removed += nested_removed
            return changed, removed
        if (
            isinstance(before, Sequence)
            and not isinstance(before, (str, bytes))
            and isinstance(after, Sequence)
            and not isinstance(after, (str, bytes))
        ):
            changed = abs(len(before) - len(after))
            removed = 0
            for before_item, after_item in zip(before, after):
                nested_changed, nested_removed = cls._diff_counts(
                    before_item, after_item
                )
                changed += nested_changed
                removed += nested_removed
            return changed, removed
        return (0, 0) if before == after else (1, 0)

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        validated = 0
        normalized_messages = 0
        changed_fields = 0
        removed_fields = 0
        for message in output.messages:
            if not self._applies(message):
                continue
            model = self.schema.model_validate(message.content)
            if self.normalize:
                normalized = model.model_dump(mode="json")
                changed, removed = self._diff_counts(message.content, normalized)
                if changed:
                    normalized_messages += 1
                    changed_fields += changed
                    removed_fields += removed
                message.content = normalized
            validated += 1
        context.report.add_event(
            self.name,
            "validated",
            count=validated,
            details={
                "normalized_messages": normalized_messages,
                "changed_fields": changed_fields,
                "removed_fields": removed_fields,
            },
        )
        return output
