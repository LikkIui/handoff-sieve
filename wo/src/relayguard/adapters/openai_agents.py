"""OpenAI Agents SDK handoff adapter.

The SDK is an optional dependency. Importing this module is safe without it;
the dependency is only required when the returned filter is called.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from typing import Any

from pydantic import BaseModel

from relayguard.models import HandoffResult, Message
from relayguard.pipeline import HandoffPipeline
from relayguard.report import AuditReport


class OpenAIHandoffFilter:
    """Callable adapter for ``handoff(..., input_filter=...)``.

    Non-message SDK control items are marked protected so selection, budgeting,
    and summarization policies cannot silently break tool-call relationships.
    The original ``new_items`` remain untouched for session history; filtered
    replacements are supplied through ``input_items`` for the receiving model.
    """

    def __init__(
        self,
        pipeline: HandoffPipeline,
        *,
        sender: str,
        receiver: str,
    ) -> None:
        self.pipeline = pipeline
        self.sender = sender
        self.receiver = receiver
        self.last_reports: list[AuditReport] = []

    @staticmethod
    def _to_plain_item(item: Any) -> Any:
        if isinstance(item, dict):
            return deepcopy(item)
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json", exclude_none=True)
        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json", exclude_none=True)
        return deepcopy(item)

    @classmethod
    def _to_message(cls, raw_item: Any, *, source_index: int) -> Message:
        plain = cls._to_plain_item(raw_item)
        if isinstance(plain, str):
            return Message(
                role="user",
                content=plain,
                internal={"source_index": source_index},
            )
        if not isinstance(plain, dict):
            return Message(
                content={"value": plain},
                kind="structured",
                protected=True,
                tags={"openai_control"},
                internal={"source_index": source_index},
            )

        item_type = str(plain.get("type", "message"))
        role = str(plain.get("role", "assistant"))
        is_control = item_type not in {"message", "input_text", "output_text"}
        return Message(
            role=role,
            content=plain,
            kind=item_type,
            tags={"openai_control"} if is_control else set(),
            protected=is_control,
            internal={"source_index": source_index},
        )

    @staticmethod
    def _from_message(message: Message) -> Any:
        if isinstance(message.content, dict):
            return message.content
        return {"role": message.role, "content": message.content}

    def _process_raw_items(self, raw_items: Sequence[Any]) -> HandoffResult:
        messages = [
            self._to_message(item, source_index=index)
            for index, item in enumerate(raw_items)
        ]
        result = self.pipeline.process(
            sender=self.sender,
            receiver=self.receiver,
            messages=messages,
        )
        self.last_reports.append(result.report)
        return result

    def _process_history(self, history: str | tuple[Any, ...]) -> str | tuple[Any, ...]:
        raw_items: tuple[Any, ...] = (history,) if isinstance(history, str) else history
        result = self._process_raw_items(raw_items)
        processed = tuple(self._from_message(message) for message in result.messages)
        if isinstance(history, str) and len(result.messages) == 1:
            only = result.messages[0]
            if isinstance(only.content, str):
                return only.content
        return processed

    def _process_run_items(self, items: tuple[Any, ...], input_item_type: type) -> tuple[Any, ...]:
        if not items:
            return ()
        raw_items = tuple(item.to_input_item() for item in items)
        result = self._process_raw_items(raw_items)
        wrapped: list[Any] = []
        for message in result.messages:
            source_index = message.internal.get("source_index", 0)
            if not isinstance(source_index, int) or not 0 <= source_index < len(items):
                source_index = 0
            wrapped.append(
                input_item_type(
                    agent=items[source_index].agent,
                    raw_item=self._from_message(message),
                )
            )
        return tuple(wrapped)

    def __call__(self, data: Any) -> Any:
        try:
            from agents.items import InputItem
        except ImportError as exc:
            raise ImportError(
                "OpenAI Agents SDK support requires `pip install relayguard[openai]`"
            ) from exc

        self.last_reports = []
        history = self._process_history(data.input_history)
        pre_handoff = self._process_run_items(data.pre_handoff_items, InputItem)
        model_items = self._process_run_items(data.new_items, InputItem)
        changes = {
            "input_history": history,
            "pre_handoff_items": pre_handoff,
            "input_items": model_items,
        }
        clone = getattr(data, "clone", None)
        if callable(clone):
            return clone(**changes)
        return replace(data, **changes)
