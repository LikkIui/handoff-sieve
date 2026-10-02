"""LangGraph adapter for receiver-specific handoffs.

LangGraph is an optional dependency. Importing this module is safe without it;
the dependency is loaded only when LangGraph messages or commands are used.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib import import_module
from typing import Any

from handoff_sieve.adapters._packet import (
    check_packet_receiver,
    merge_artifacts,
    packet_from_text,
)
from handoff_sieve.compiler import HandoffPacket, ReceiverContract
from handoff_sieve.exceptions import HandoffIntegrityError
from handoff_sieve.models import Artifact, HandoffEnvelope, Message
from handoff_sieve.normalization import (
    HistoryCompilation,
    HistoryNormalizer,
    compile_history,
)
from handoff_sieve.pipeline import HandoffPipeline


def _optional_module(name: str) -> Any:
    try:
        return import_module(name)
    except ImportError as exc:
        raise ImportError(
            "LangGraph support requires `pip install handoff-sieve[langgraph]`"
        ) from exc


def _content(value: Any) -> str | dict[str, Any] | list[Any]:
    if isinstance(value, (str, dict, list)):
        return deepcopy(value)
    return str(value)


def _coerce_langchain_messages(raw_messages: Sequence[Any]) -> list[Any]:
    messages_module = _optional_module("langchain_core.messages")
    base_message = messages_module.BaseMessage
    convert_to_messages = messages_module.convert_to_messages
    converted: list[Any] = []
    for position, raw in enumerate(raw_messages):
        if isinstance(raw, base_message):
            converted.append(raw)
            continue
        try:
            converted.extend(convert_to_messages([raw]))
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"state messages[{position}] is not a LangChain message"
            ) from exc
    return converted


def _messages_to_state(
    raw_messages: Sequence[Any], *, sender: str | None = None
) -> tuple[list[Message], list[Artifact]]:
    """Convert a complete LangGraph message state into normalizable history.

    An ``AIMessage`` tool call and its matching ``ToolMessage`` are collapsed
    into one semantic ``tool_results`` item. This keeps the call name,
    arguments, identifier, and result together without replaying an old tool
    call in the receiver graph. Orphaned or unfinished calls are rejected.
    """

    if isinstance(raw_messages, (str, bytes)):
        raise TypeError("LangGraph messages must be a sequence of messages")

    messages_module = _optional_module("langchain_core.messages")
    ai_message = messages_module.AIMessage
    tool_message = messages_module.ToolMessage
    remove_message = messages_module.RemoveMessage
    messages = _coerce_langchain_messages(raw_messages)

    history: list[Message] = []
    artifacts: list[Artifact] = []
    pending: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()

    for position, raw in enumerate(messages):
        if isinstance(raw, remove_message):
            raise HandoffIntegrityError(
                "A resolved LangGraph state cannot contain RemoveMessage controls."
            )

        if isinstance(raw, tool_message):
            call_id = raw.tool_call_id
            if not isinstance(call_id, str) or not call_id:
                raise HandoffIntegrityError(
                    f"ToolMessage at position {position} has no tool_call_id."
                )
            if call_id in completed:
                raise HandoffIntegrityError(
                    f"Tool call {call_id!r} has more than one ToolMessage result."
                )
            call = pending.pop(call_id, None)
            if call is None:
                raise HandoffIntegrityError(
                    f"ToolMessage {call_id!r} has no preceding AIMessage tool call."
                )
            completed.add(call_id)
            history.append(
                Message(
                    role="tool",
                    kind="tool_results",
                    content={
                        "tool_result": {
                            "call_id": call_id,
                            "name": call["name"],
                            "arguments": deepcopy(call["arguments"]),
                            "output": _content(raw.content),
                        }
                    },
                    metadata={"tool_call_id": call_id},
                )
            )
            continue

        if pending:
            call_ids = ", ".join(sorted(pending))
            raise HandoffIntegrityError(
                "LangGraph history continues before pending tool calls are "
                f"completed: {call_ids}."
            )

        message_type = getattr(raw, "type", "")
        role = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "function": "tool",
            "chat": getattr(raw, "role", "user"),
        }.get(message_type, message_type or "user")

        packet = packet_from_text(raw.content) if role == "user" else None
        marker = raw.additional_kwargs.get("handoff_sieve")
        if marker is not None:
            if (
                packet is None
                or not isinstance(marker, dict)
                or marker.get("sender") != packet.sender
                or marker.get("receiver") != packet.receiver
            ):
                raise HandoffIntegrityError(
                    "LangGraph receiver packet marker is invalid."
                )
        if packet is not None:
            if sender is not None:
                check_packet_receiver(packet, sender)
            inherited = packet.to_envelope()
            history.extend(inherited.messages)
            artifacts.extend(inherited.artifacts)
            continue

        if raw.content not in ("", []):
            metadata: dict[str, Any] = {}
            name = getattr(raw, "name", None)
            if isinstance(name, str) and name:
                metadata["name"] = name
            history.append(
                Message(
                    role=role,
                    content=_content(raw.content),
                    metadata=metadata,
                )
            )

        if not isinstance(raw, ai_message):
            continue
        for tool_call in raw.tool_calls:
            call_id = tool_call.get("id")
            name = tool_call.get("name")
            if not isinstance(call_id, str) or not call_id:
                raise HandoffIntegrityError(
                    f"AIMessage tool call at position {position} has no id."
                )
            if call_id in pending or call_id in completed:
                raise HandoffIntegrityError(
                    f"LangGraph tool call id {call_id!r} is reused."
                )
            pending[call_id] = {
                "name": name if isinstance(name, str) else "",
                "arguments": deepcopy(tool_call.get("args", {})),
            }

    if pending:
        call_ids = ", ".join(sorted(pending))
        raise HandoffIntegrityError(
            f"LangGraph history ends with unfinished tool calls: {call_ids}."
        )
    return history, artifacts


def langgraph_messages_to_history(raw_messages: Sequence[Any]) -> list[Message]:
    """Map messages and expand previous packets into explicitly typed state.

    Completed tool pairs remain one semantic tool result. Use
    ``langgraph_state_to_envelope`` to also carry packet artifacts forward.
    """

    history, _ = _messages_to_state(raw_messages)
    return history


def langgraph_state_to_envelope(
    state: Mapping[str, Any],
    *,
    sender: str,
    receiver: str,
    messages_key: str = "messages",
    artifacts_key: str | None = "artifacts",
) -> HandoffEnvelope:
    """Map one resolved LangGraph state snapshot to a HandoffSieve envelope."""

    if not isinstance(state, Mapping):
        raise TypeError("state must be a mapping")
    raw_messages = state.get(messages_key, ())
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        raise TypeError(f"state[{messages_key!r}] must be a message sequence")

    messages, artifacts = _messages_to_state(raw_messages, sender=sender)
    current_artifacts: list[Artifact] = []
    if artifacts_key is not None:
        raw_artifacts = state.get(artifacts_key, ())
        if not isinstance(raw_artifacts, Sequence) or isinstance(
            raw_artifacts, (str, bytes)
        ):
            raise TypeError(f"state[{artifacts_key!r}] must be an artifact sequence")
        current_artifacts = [
            Artifact.model_validate(artifact) for artifact in raw_artifacts
        ]

    return HandoffEnvelope(
        sender=sender,
        receiver=receiver,
        messages=messages,
        artifacts=merge_artifacts(artifacts, current_artifacts),
    )


def compile_langgraph_state(
    state: Mapping[str, Any],
    contract: ReceiverContract,
    *,
    sender: str,
    receiver: str,
    messages_key: str = "messages",
    artifacts_key: str | None = "artifacts",
    normalizer: HistoryNormalizer | None = None,
    pipeline: HandoffPipeline | None = None,
    request_id: str | None = None,
) -> HistoryCompilation:
    """Compile a LangGraph state snapshot with the regular HandoffSieve core."""

    envelope = langgraph_state_to_envelope(
        state,
        sender=sender,
        receiver=receiver,
        messages_key=messages_key,
        artifacts_key=artifacts_key,
    )
    return compile_history(
        envelope,
        contract,
        normalizer=normalizer,
        pipeline=pipeline,
        request_id=request_id,
    )


class LangGraphHandoff:
    """Inject a compiled packet into a LangGraph ``MessagesState`` receiver.

    ``state_update`` uses LangGraph's documented remove-all control before the
    new receiver message. The receiving model therefore sees the canonical
    packet instead of the sender's full message history. The optional packet
    state key gives deterministic nodes direct access to the same structure.
    """

    def __init__(
        self,
        packet: HandoffPacket,
        *,
        messages_key: str = "messages",
        packet_key: str | None = "handoff_packet",
    ) -> None:
        if not isinstance(packet, HandoffPacket):
            raise TypeError("packet must be a HandoffPacket")
        if not messages_key:
            raise ValueError("messages_key must not be empty")
        if packet_key == messages_key:
            raise ValueError("packet_key and messages_key must differ")
        self._packet = packet.model_copy(deep=True)
        self.messages_key = messages_key
        self.packet_key = packet_key

    @property
    def packet(self) -> HandoffPacket:
        """Return a defensive copy of the receiver packet."""

        return self._packet.model_copy(deep=True)

    @property
    def receiver_text(self) -> str:
        """Return the exact text injected into the receiver message state."""

        return self._packet.to_receiver_text()

    def state_update(self) -> dict[str, Any]:
        """Build an update for a state key using LangGraph ``add_messages``."""

        messages_module = _optional_module("langchain_core.messages")
        graph_message_module = _optional_module("langgraph.graph.message")
        update: dict[str, Any] = {
            self.messages_key: [
                messages_module.RemoveMessage(
                    id=graph_message_module.REMOVE_ALL_MESSAGES
                ),
                messages_module.HumanMessage(
                    content=self.receiver_text,
                    additional_kwargs={
                        "handoff_sieve": {
                            "sender": self._packet.sender,
                            "receiver": self._packet.receiver,
                        }
                    },
                ),
            ]
        }
        if self.packet_key is not None:
            update[self.packet_key] = self._packet.model_dump(mode="json")
        return update

    def command(self, goto: str, *, graph: str | None = None) -> Any:
        """Build a LangGraph ``Command`` that updates state and routes onward."""

        if not goto:
            raise ValueError("goto must not be empty")
        command_type = _optional_module("langgraph.types").Command
        arguments: dict[str, Any] = {
            "update": self.state_update(),
            "goto": goto,
        }
        if graph is not None:
            arguments["graph"] = graph
        return command_type(**arguments)
