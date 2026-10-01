"""Compile live OpenAI Agents SDK handoff history for a receiver contract."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from handoff_sieve.adapters.openai_agents import (
    OpenAIHandoffFilter,
    OpenAIHandoffPacketFilter,
)
from handoff_sieve.compiler import ReceiverContract
from handoff_sieve.exceptions import HandoffIntegrityError, UnsupportedAdapterModeError
from handoff_sieve.models import Artifact, HandoffEnvelope, Message
from handoff_sieve.normalization import (
    HistoryCompilation,
    HistoryNormalizer,
    compile_history,
)
from handoff_sieve.pipeline import HandoffPipeline


def _snapshot_items(data: Any) -> list[Any]:
    try:
        from agents.handoffs import HandoffInputData
        from agents.items import HandoffCallItem, HandoffOutputItem
    except ImportError as exc:
        raise ImportError(
            "OpenAI Agents SDK support requires `pip install handoff-sieve[openai]`"
        ) from exc
    if not isinstance(data, HandoffInputData):
        raise UnsupportedAdapterModeError(
            "Contract compilation requires a complete client-managed HandoffInputData."
        )
    history: list[Any] = (
        [data.input_history]
        if isinstance(data.input_history, str)
        else list(data.input_history)
    )
    model_items = data.input_items if data.input_items is not None else data.new_items
    history.extend(
        item.to_input_item()
        for item in (*data.pre_handoff_items, *model_items)
        if not isinstance(item, (HandoffCallItem, HandoffOutputItem))
    )
    return history


def _text_messages(item: dict[str, Any]) -> list[Message]:
    content = item.get("content", "")
    role = str(item.get("role", "user"))
    if isinstance(content, str):
        return [Message(role=role, content=content)]
    if not isinstance(content, list):
        raise UnsupportedAdapterModeError("OpenAI message content must be text blocks.")
    texts: list[str] = []
    for block in content:
        if (
            not isinstance(block, dict)
            or block.get("type") not in {"input_text", "output_text"}
            or not isinstance(block.get("text"), str)
        ):
            raise UnsupportedAdapterModeError(
                "Contract compilation currently supports text and function tools; "
                "images, audio, and other content need an application state mapper."
            )
        texts.append(block["text"])
    return [Message(role=role, content="\n".join(texts))] if texts else []


def _messages_from_snapshot(data: Any) -> list[Message]:
    messages: list[Message] = []
    pending: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()
    for raw in _snapshot_items(data):
        item = OpenAIHandoffFilter._to_plain_item(raw)
        if isinstance(item, str):
            messages.append(Message(content=item))
            continue
        if not isinstance(item, dict):
            raise UnsupportedAdapterModeError("OpenAI history items must be mappings.")
        kind = item.get("type", "message")
        if kind == "message":
            messages.extend(_text_messages(item))
        elif kind == "reasoning":
            continue
        elif kind in {"function_call", "function_call_output"}:
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id:
                raise HandoffIntegrityError("A function tool item has no call_id.")
            if kind == "function_call":
                if call_id in pending or call_id in completed:
                    raise HandoffIntegrityError("A function tool call_id is reused.")
                pending[call_id] = item
                continue
            call = pending.pop(call_id, None)
            if call is None:
                raise HandoffIntegrityError(
                    "A function tool output has no preceding unfinished call."
                )
            completed.add(call_id)
            messages.append(
                Message(
                    role="tool",
                    kind="tool_results",
                    content={
                        "tool_result": {
                            "call_id": call_id,
                            "name": call.get("name", ""),
                            "arguments": deepcopy(call.get("arguments", "")),
                            "output": deepcopy(item.get("output", "")),
                        }
                    },
                )
            )
        else:
            raise UnsupportedAdapterModeError(
                f"OpenAI history item type {kind!r} needs an application state mapper."
            )
    if pending:
        raise HandoffIntegrityError(
            "OpenAI history contains unfinished function tools."
        )
    return messages


def compile_openai_handoff(
    data: Any,
    contract: ReceiverContract,
    *,
    sender: str,
    receiver: str,
    artifacts: Sequence[Artifact] = (),
    normalizer: HistoryNormalizer | None = None,
    pipeline: HandoffPipeline | None = None,
) -> HistoryCompilation:
    """Compile the latest SDK snapshot, including completed function results.

    Routing events and reasoning items do not become receiver task state.
    Original SDK items and local run_context are never mutated or serialized.
    """

    return compile_history(
        HandoffEnvelope(
            sender=sender,
            receiver=receiver,
            messages=_messages_from_snapshot(data),
            artifacts=[artifact.model_copy(deep=True) for artifact in artifacts],
        ),
        contract,
        normalizer=normalizer,
        pipeline=pipeline,
    )


class OpenAIReceiverContractFilter:
    """Build a fresh receiver packet at each SDK handoff, without a model call."""

    def __init__(
        self,
        contract: ReceiverContract,
        *,
        sender: str,
        receiver: str,
        artifacts: Sequence[Artifact] = (),
        normalizer: HistoryNormalizer | None = None,
        pipeline: HandoffPipeline | None = None,
        on_compile: Callable[[HistoryCompilation], None] | None = None,
    ) -> None:
        self.contract = contract
        self.sender = sender
        self.receiver = receiver
        self.artifacts = tuple(artifact.model_copy(deep=True) for artifact in artifacts)
        self.normalizer = normalizer
        self.pipeline = pipeline
        self.on_compile = on_compile

    def __call__(self, data: Any) -> Any:
        compilation = compile_openai_handoff(
            data,
            self.contract,
            sender=self.sender,
            receiver=self.receiver,
            artifacts=self.artifacts,
            normalizer=self.normalizer,
            pipeline=self.pipeline,
        )
        packet_filter = OpenAIHandoffPacketFilter(compilation.packet)
        if self.on_compile is not None:
            self.on_compile(compilation)
        return packet_filter(data)
