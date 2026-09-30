from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

import pytest

from handoff_sieve import (
    HandoffIntegrityError,
    HandoffPacket,
    Message,
    ReceiverContract,
)
from handoff_sieve.adapters import (
    LangGraphHandoff,
    compile_langgraph_state,
    langgraph_messages_to_history,
)

langchain_messages = pytest.importorskip("langchain_core.messages")
langgraph_graph = pytest.importorskip("langgraph.graph")

AIMessage = langchain_messages.AIMessage
HumanMessage = langchain_messages.HumanMessage
ToolMessage = langchain_messages.ToolMessage
StateGraph = langgraph_graph.StateGraph
add_messages = langgraph_graph.add_messages
START = langgraph_graph.START
END = langgraph_graph.END


def _paired_state() -> dict[str, Any]:
    return {
        "messages": [
            HumanMessage(content="Constraint: Keep the JSON API stable."),
            AIMessage(
                content="Decision: Validate the schema before writing files.",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "read_schema",
                        "args": {"path": "schema.json"},
                    }
                ],
            ),
            ToolMessage(
                content='{"required":["name"]}',
                tool_call_id="call_1",
            ),
            HumanMessage(content="TODO: Implement the receiver."),
        ]
    }


def _packet() -> HandoffPacket:
    return HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Implement the receiver.",
        constraints=[Message(kind="constraints", content="Keep the API stable.")],
        pending_work=[Message(kind="pending_work", content="Write receiver.py.")],
    )


def test_langgraph_messages_collapse_tool_call_and_result() -> None:
    history = langgraph_messages_to_history(_paired_state()["messages"])

    assert [message.role for message in history] == [
        "user",
        "assistant",
        "tool",
        "user",
    ]
    tool_result = history[2]
    assert tool_result.kind == "tool_results"
    assert tool_result.content == {
        "tool_result": {
            "call_id": "call_1",
            "name": "read_schema",
            "arguments": {"path": "schema.json"},
            "output": '{"required":["name"]}',
        }
    }


def test_langgraph_state_compiles_with_regular_contract() -> None:
    compilation = compile_langgraph_state(
        _paired_state(),
        ReceiverContract(
            goal="Implement the receiver.",
            required=("constraints", "decisions", "pending_work", "tool_results"),
            max_tokens=800,
        ),
        sender="researcher",
        receiver="coder",
    )

    assert compilation.packet.goal == "Implement the receiver."
    assert compilation.packet.constraints[0].content == "Keep the JSON API stable."
    assert compilation.packet.decisions[0].content == (
        "Validate the schema before writing files."
    )
    assert compilation.packet.pending_work[0].content == "Implement the receiver."
    assert compilation.packet.tool_results[0].metadata["tool_call_id"] == "call_1"


@pytest.mark.parametrize(
    "messages, match",
    [
        (
            [ToolMessage(content="orphan", tool_call_id="missing")],
            "no preceding AIMessage",
        ),
        (
            [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "pending", "name": "read", "args": {}}],
                )
            ],
            "unfinished tool calls",
        ),
    ],
)
def test_langgraph_message_mapping_rejects_broken_tool_pairs(
    messages: list[Any], match: str
) -> None:
    with pytest.raises(HandoffIntegrityError, match=match):
        langgraph_messages_to_history(messages)


def test_langgraph_handoff_replaces_sender_messages_in_real_graph() -> None:
    class State(TypedDict, total=False):
        messages: Annotated[list[Any], add_messages]
        handoff_packet: dict[str, Any]
        observed: str

    handoff = LangGraphHandoff(_packet())

    def route(_: State) -> Any:
        return handoff.command("receiver")

    def receiver(state: State) -> dict[str, str]:
        assert len(state["messages"]) == 1
        assert isinstance(state["messages"][0], HumanMessage)
        return {"observed": state["messages"][0].content}

    builder = StateGraph(State)
    builder.add_node("route", route)
    builder.add_node("receiver", receiver)
    builder.add_edge(START, "route")
    builder.add_edge("receiver", END)
    graph = builder.compile()

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="large sender history"),
                AIMessage(content="irrelevant details"),
            ]
        }
    )

    assert result["observed"] == handoff.receiver_text
    assert json.loads(result["observed"])["goal"] == "Implement the receiver."
    assert result["handoff_packet"]["receiver"] == "coder"


def test_langgraph_handoff_defensively_copies_packet() -> None:
    packet = _packet()
    handoff = LangGraphHandoff(packet)
    packet.pending_work[0].content = "Changed after construction."

    assert "Changed after construction" not in handoff.receiver_text
    returned = handoff.packet
    returned.goal = "Changed copy."
    assert handoff.packet.goal == "Implement the receiver."


def test_langgraph_handoff_validates_state_keys_and_destination() -> None:
    packet = _packet()
    with pytest.raises(ValueError, match="must differ"):
        LangGraphHandoff(packet, messages_key="state", packet_key="state")

    handoff = LangGraphHandoff(packet)
    with pytest.raises(ValueError, match="goto"):
        handoff.command("")
