"""Structured message validation policy."""

from __future__ import annotations

from collections.abc import Iterable
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

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        validated = 0
        for message in output.messages:
            if not self._applies(message):
                continue
            model = self.schema.model_validate(message.content)
            if self.normalize:
                message.content = model.model_dump(mode="json")
            validated += 1
        context.report.add_event(self.name, "validated", count=validated)
        return output
