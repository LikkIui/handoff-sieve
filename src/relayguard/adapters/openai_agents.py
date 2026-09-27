"""OpenAI Agents SDK handoff adapter.

The SDK is an optional dependency. Importing this module is safe without it;
the dependency is only required when the returned filter is called.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from typing import Any

from pydantic import BaseModel

from relayguard.models import HandoffEnvelope, HandoffResult, Message
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
        self._last_reports_var: ContextVar[tuple[AuditReport, ...]] = ContextVar(
            f"relayguard_openai_reports_{id(self)}",
            default=(),
        )

    @property
    def last_reports(self) -> list[AuditReport]:
        """Reports produced in the current execution context."""

        return list(self._last_reports_var.get())

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
    def _to_message(
        cls,
        raw_item: Any,
        *,
        source_index: int,
        segment: str = "message",
    ) -> Message:
        plain = cls._to_plain_item(raw_item)
        if isinstance(plain, str):
            message = Message(
                role="user",
                content=plain,
            )
            message._replace_internal(
                {"source_index": source_index, "segment": segment}
            )
            return message
        if not isinstance(plain, dict):
            message = Message(
                content={"value": plain},
                kind="structured",
                tags={"openai_control"},
            )
            message._mark_protected()
            message._replace_internal(
                {"source_index": source_index, "segment": segment}
            )
            return message

        item_type = str(plain.get("type", "message"))
        role = str(plain.get("role", "assistant"))
        is_control = item_type not in {"message", "input_text", "output_text"}
        message = Message(
            role=role,
            content=plain,
            kind=item_type,
            tags={"openai_control"} if is_control else set(),
        )
        if is_control:
            message._mark_protected()
        message._replace_internal(
            {"source_index": source_index, "segment": segment}
        )
        return message

    @staticmethod
    def _from_message(message: Message) -> Any:
        if isinstance(message.content, dict):
            return message.content
        return {"role": message.role, "content": message.content}

    def _process_messages(self, messages: Sequence[Message]) -> HandoffResult:
        result = self.pipeline._process_trusted_envelope(
            HandoffEnvelope(
                sender=self.sender,
                receiver=self.receiver,
                messages=list(messages),
            )
        )
        self._last_reports_var.set((result.report,))
        return result

    def _process_raw_items(
        self,
        raw_items: Sequence[Any],
        *,
        segment: str = "message",
    ) -> HandoffResult:
        messages = [
            self._to_message(item, source_index=index, segment=segment)
            for index, item in enumerate(raw_items)
        ]
        return self._process_messages(messages)

    @classmethod
    def _history_from_messages(
        cls,
        messages: Sequence[Message],
        *,
        was_string: bool,
    ) -> str | tuple[Any, ...]:
        processed = tuple(cls._from_message(message) for message in messages)
        if was_string and len(messages) == 1:
            only = messages[0]
            if isinstance(only.content, str):
                return only.content
        return processed

    def _process_history(self, history: str | tuple[Any, ...]) -> str | tuple[Any, ...]:
        raw_items: tuple[Any, ...] = (history,) if isinstance(history, str) else history
        result = self._process_raw_items(raw_items, segment="history")
        return self._history_from_messages(
            result.messages,
            was_string=isinstance(history, str),
        )

    def _wrap_run_messages(
        self,
        messages: Sequence[Message],
        items: tuple[Any, ...],
        input_item_type: type,
    ) -> tuple[Any, ...]:
        if not items:
            return ()
        wrapped: list[Any] = []
        for message in messages:
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

    def _process_run_items(self, items: tuple[Any, ...], input_item_type: type) -> tuple[Any, ...]:
        if not items:
            return ()
        raw_items = tuple(item.to_input_item() for item in items)
        result = self._process_raw_items(raw_items, segment="input")
        return self._wrap_run_messages(result.messages, items, input_item_type)

    def __call__(self, data: Any) -> Any:
        try:
            from agents.items import InputItem
        except ImportError as exc:
            raise ImportError(
                "OpenAI Agents SDK support requires `pip install relayguard[openai]`"
            ) from exc

        raw_history: tuple[Any, ...] = (
            (data.input_history,)
            if isinstance(data.input_history, str)
            else data.input_history
        )
        model_source_items = (
            data.input_items if data.input_items is not None else data.new_items
        )

        messages = [
            self._to_message(item, source_index=index, segment="history")
            for index, item in enumerate(raw_history)
        ]
        messages.extend(
            self._to_message(
                item.to_input_item(),
                source_index=index,
                segment="pre_handoff",
            )
            for index, item in enumerate(data.pre_handoff_items)
        )
        messages.extend(
            self._to_message(
                item.to_input_item(),
                source_index=index,
                segment="input",
            )
            for index, item in enumerate(model_source_items)
        )

        result = self._process_messages(messages)
        by_segment: dict[str, list[Message]] = {
            "history": [],
            "pre_handoff": [],
            "input": [],
        }
        for message in result.messages:
            segment = message.internal.get("segment", "input")
            if segment not in by_segment:
                segment = "input"
            by_segment[segment].append(message)

        history = self._history_from_messages(
            by_segment["history"],
            was_string=isinstance(data.input_history, str),
        )
        pre_handoff = self._wrap_run_messages(
            by_segment["pre_handoff"],
            data.pre_handoff_items,
            InputItem,
        )
        model_items = self._wrap_run_messages(
            by_segment["input"],
            model_source_items,
            InputItem,
        )
        changes = {
            "input_history": history,
            "pre_handoff_items": pre_handoff,
            "input_items": model_items,
        }
        clone = getattr(data, "clone", None)
        if callable(clone):
            return clone(**changes)
        return replace(data, **changes)
