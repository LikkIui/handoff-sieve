"""OpenAI Agents SDK handoff adapter.

The SDK is an optional dependency. Importing this module is safe without it;
the dependency is only required when the returned filter is called.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from typing import Any

from pydantic import BaseModel

from relayguard.exceptions import (
    HandoffIntegrityError,
    RelayGuardError,
    UnsupportedAdapterModeError,
)
from relayguard.models import HandoffEnvelope, HandoffResult, Message
from relayguard.pipeline import HandoffPipeline
from relayguard.policies.base import Policy, PolicyContext
from relayguard.report import AuditReport

_TOOL_INVOCATION_TYPES = frozenset(
    {
        "apply_patch_call",
        "computer_call",
        "custom_tool_call",
        "function_call",
        "local_shell_call",
        "mcp_approval_request",
        "shell_call",
    }
)
_TOOL_OUTPUT_TYPES = {
    "apply_patch_call_output": "apply_patch_call",
    "computer_call_output": "computer_call",
    "custom_tool_call_output": "custom_tool_call",
    "function_call_output": "function_call",
    "local_shell_call_output": "local_shell_call",
    "mcp_approval_response": "mcp_approval_request",
    "shell_call_output": "shell_call",
}


class _OpenAIToolPairPolicy(Policy):
    """Validate exposed SDK control items after all user policies run."""

    name = "openai_tool_pairs"
    version = "1"

    def __init__(self, source_messages: Sequence[Message]) -> None:
        self.source_pairs = self._pair_descriptors(source_messages)
        self.expected_controls = Counter(
            descriptor
            for message in source_messages
            if message.protected
            if (descriptor := self._control_descriptor(message)) is not None
        )

    @staticmethod
    def _item_type(message: Message) -> str | None:
        if not isinstance(message.content, dict):
            return None
        item_type = message.content.get("type")
        return item_type if isinstance(item_type, str) else None

    @classmethod
    def _control_descriptor(
        cls,
        message: Message,
    ) -> tuple[str, int, str] | None:
        segment = message.internal.get("segment")
        source_index = message.internal.get("source_index")
        item_type = cls._item_type(message) or message.kind
        if (
            not isinstance(segment, str)
            or not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or item_type is None
        ):
            return None
        return segment, source_index, item_type

    @classmethod
    def _pair_descriptors(
        cls,
        messages: Sequence[Message],
    ) -> list[tuple[str, str, str | None]]:
        descriptors: list[tuple[str, str, str | None]] = []
        for message in messages:
            if not isinstance(message.content, dict):
                continue
            item_type = cls._item_type(message)
            if item_type in _TOOL_INVOCATION_TYPES:
                key = "id" if item_type == "mcp_approval_request" else "call_id"
                call_id = message.content.get(key)
                descriptors.append(
                    (
                        "invocation",
                        item_type,
                        call_id if isinstance(call_id, str) and call_id else None,
                    )
                )
                continue
            invocation_type = _TOOL_OUTPUT_TYPES.get(item_type or "")
            if invocation_type is None:
                continue
            key = (
                "approval_request_id"
                if item_type == "mcp_approval_response"
                else "call_id"
            )
            call_id = message.content.get(key)
            descriptors.append(
                (
                    "output",
                    invocation_type,
                    call_id if isinstance(call_id, str) and call_id else None,
                )
            )
        return descriptors

    @staticmethod
    def _validate_pairs(
        descriptors: Sequence[tuple[str, str, str | None]],
    ) -> tuple[int, int]:
        invocations: set[tuple[str, str]] = set()
        completed: set[tuple[str, str]] = set()
        for role, invocation_type, call_id in descriptors:
            if call_id is None:
                raise HandoffIntegrityError(
                    "A recognized OpenAI tool control item has no non-empty "
                    "call identifier."
                )
            identity = (invocation_type, call_id)
            if role == "invocation":
                if identity in completed:
                    raise HandoffIntegrityError(
                        "An OpenAI tool call identifier was reused after its "
                        "output was completed."
                    )
                invocations.add(identity)
                continue
            if identity not in invocations:
                raise HandoffIntegrityError(
                    "An OpenAI tool output has no preceding matching tool call "
                    "in the exposed handoff. Include complete client-managed "
                    "history before filtering."
                )
            if identity in completed:
                raise HandoffIntegrityError(
                    "Multiple OpenAI tool outputs complete the same exposed tool call."
                )
            completed.add(identity)
        return len(invocations), len(completed)

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        self._validate_pairs(self.source_pairs)
        actual_controls = Counter(
            descriptor
            for message in envelope.messages
            if message.protected
            if (descriptor := self._control_descriptor(message)) is not None
        )
        if actual_controls != self.expected_controls:
            raise HandoffIntegrityError(
                "A policy changed, removed, duplicated, or unprotected an "
                "OpenAI control item required to reconstruct the handoff."
            )

        output_pairs = self._pair_descriptors(envelope.messages)
        output_invocations, output_outputs = self._validate_pairs(output_pairs)
        if output_pairs != self.source_pairs:
            raise HandoffIntegrityError(
                "A policy changed an OpenAI tool call identifier, type, order, "
                "or output relationship."
            )
        context.report.add_event(
            self.name,
            "validated",
            count=output_outputs,
            details={
                "control_items": sum(actual_controls.values()),
                "tool_invocations": output_invocations,
                "paired_outputs": output_outputs,
            },
        )
        return envelope


class _UnsupportedOpenAIModePolicy(Policy):
    """Create an auditable denial for an unsupported SDK input shape."""

    name = "openai_adapter"
    version = "1"

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        raise UnsupportedAdapterModeError(
            "OpenAIHandoffFilter requires a complete HandoffInputData snapshot "
            "with client-managed history. Buffer realtime or streaming input "
            "before filtering."
        )


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
        message._replace_internal({"source_index": source_index, "segment": segment})
        return message

    @staticmethod
    def _from_message(message: Message) -> Any:
        if isinstance(message.content, dict):
            return message.content
        return {"role": message.role, "content": message.content}

    def _process_messages(
        self,
        messages: Sequence[Message],
        *,
        final_policies: Sequence[Policy] = (),
    ) -> HandoffResult:
        self._last_reports_var.set(())
        try:
            result = self.pipeline._process_trusted_envelope(
                HandoffEnvelope(
                    sender=self.sender,
                    receiver=self.receiver,
                    messages=list(messages),
                ),
                final_policies=(
                    *final_policies,
                    _OpenAIToolPairPolicy(messages),
                ),
            )
        except RelayGuardError as error:
            if error.report is not None:
                self._last_reports_var.set((error.report,))
            raise
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

    def _process_run_items(
        self, items: tuple[Any, ...], input_item_type: type
    ) -> tuple[Any, ...]:
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

        required_fields = (
            "input_history",
            "pre_handoff_items",
            "new_items",
            "input_items",
        )
        supported_shape = all(hasattr(data, field) for field in required_fields)
        if supported_shape:
            supported_shape = (
                isinstance(data.input_history, (str, tuple))
                and isinstance(data.pre_handoff_items, tuple)
                and isinstance(data.new_items, tuple)
                and (data.input_items is None or isinstance(data.input_items, tuple))
            )
        if not supported_shape:
            self._process_messages(
                (),
                final_policies=(_UnsupportedOpenAIModePolicy(),),
            )
            raise AssertionError("Unsupported OpenAI mode policy did not deny input")

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
