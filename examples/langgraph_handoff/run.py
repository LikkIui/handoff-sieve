"""Run a receiver-specific HandoffSieve handoff through a real LangGraph."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages

from handoff_sieve import HandoffPacket, ReceiverContract
from handoff_sieve.adapters import LangGraphHandoff, compile_langgraph_state


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    artifacts: list[dict[str, Any]]
    handoff_packet: dict[str, Any]
    receiver_output: str


contract = ReceiverContract(
    goal="Implement the schema-aware receiver.",
    required=("constraints", "decisions", "pending_work", "tool_results"),
    preferred=("artifacts",),
    max_tokens=900,
)
measurements: dict[str, int | float] = {}


def handoff_to_coder(state: State) -> Any:
    compilation = compile_langgraph_state(
        state,
        contract,
        sender="researcher",
        receiver="coder",
    )
    measurements.update(
        source_tokens=compilation.source_tokens,
        packet_tokens=compilation.packet_tokens,
        savings_percent=compilation.estimated_savings_percent,
    )
    return LangGraphHandoff(compilation.packet).command("coder")


def coder(state: State) -> dict[str, str]:
    assert len(state["messages"]) == 1
    receiver_view = state["messages"][0].content
    assert isinstance(receiver_view, str)
    packet = HandoffPacket.model_validate_json(receiver_view)
    assert packet == HandoffPacket.model_validate(state["handoff_packet"])
    return {
        "receiver_output": (
            f"received {len(packet.pending_work)} pending item and "
            f"{len(packet.tool_results)} paired tool result"
        )
    }


def main() -> None:
    graph_builder = StateGraph(State)
    graph_builder.add_node("handoff", handoff_to_coder)
    graph_builder.add_node("coder", coder)
    graph_builder.add_edge(START, "handoff")
    graph_builder.add_edge("coder", END)
    graph = graph_builder.compile()

    noise = "Unrelated market research and launch notes. " * 200
    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content=noise),
                HumanMessage(content="Constraint: Keep the public JSON API stable."),
                AIMessage(
                    content="Decision: Validate the schema before writing files.",
                    tool_calls=[
                        {
                            "id": "call_schema",
                            "name": "read_schema",
                            "args": {"path": "schema.json"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"required":["name"]}',
                    tool_call_id="call_schema",
                ),
                HumanMessage(content="TODO: Implement receiver.py."),
            ],
            "artifacts": [
                {
                    "name": "schema.json",
                    "content": {"required": ["name"]},
                    "media_type": "application/json",
                }
            ],
        }
    )

    print("LangGraph researcher -> coder")
    print(f"Before: {measurements['source_tokens']:,} estimated tokens")
    print(f"After HandoffSieve: {measurements['packet_tokens']:,} estimated tokens")
    print(f"Context reduction: {measurements['savings_percent']:.1f}%")
    print(f"Receiver messages: {len(result['messages'])}")
    print(f"Receiver: {result['receiver_output']}")
    print("Result: real LangGraph handoff completed with packet-only context.")


if __name__ == "__main__":
    main()
