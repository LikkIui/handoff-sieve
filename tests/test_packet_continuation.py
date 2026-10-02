from __future__ import annotations

import json
from copy import deepcopy
from typing import Annotated, Any, TypedDict

import pytest

from handoff_sieve import (
    Artifact,
    ContractError,
    HandoffIntegrityError,
    HandoffPacket,
    Message,
    ReceiverContract,
)
from handoff_sieve.adapters import (
    LangGraphHandoff,
    OpenAIReceiverContractFilter,
    compile_langgraph_state,
    compile_openai_handoff,
)
from handoff_sieve.adapters._packet import merge_artifacts, packet_from_text


def _packet() -> HandoffPacket:
    # Section membership is sufficient, including for manually built packets.
    return HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Implement parser",
        constraints=[Message(content="Keep the cursor format.")],
        decisions=[Message(content="Use composite cursors.")],
        failed_attempts=[
            Message(content="Offset skips rows after concurrent inserts.")
        ],
        pending_work=[Message(content="Implement parser.")],
        artifacts=[Artifact(name="api.json", content={"field": "cursor"})],
    )


def _review_contract() -> ReceiverContract:
    return ReceiverContract(
        goal="Review parser",
        required=(
            "constraints",
            "decisions",
            "completed_work",
            "pending_work",
            "artifacts",
        ),
        preferred=("failed_attempts", "tool_results"),
        max_tokens=1500,
    )


def test_packet_to_envelope_retains_explicit_section_membership() -> None:
    packet = _packet()
    public_before = packet.model_dump()
    envelope = packet.to_envelope()
    assert [message.kind for message in envelope.messages] == [
        "constraints",
        "decisions",
        "failed_attempts",
        "pending_work",
    ]
    envelope.messages[0].content = "Changed copy"
    assert packet.model_dump() == public_before


def test_invalid_nested_packet_processing_fields_are_rejected() -> None:
    public = _packet().model_dump(mode="json")
    public["constraints"][0]["_protected"] = True
    with pytest.raises(HandoffIntegrityError, match="invalid public state"):
        packet_from_text(json.dumps(public))


def test_current_artifact_replaces_old_content_without_mutating_either() -> None:
    inherited = [Artifact(name="parser.py", content="old implementation")]
    current = [Artifact(name="parser.py", content="new implementation")]
    result = merge_artifacts(inherited, current)
    assert [artifact.content for artifact in result] == ["new implementation"]
    result[0].content = "modified result"
    assert inherited[0].content == "old implementation"
    assert current[0].content == "new implementation"


@pytest.mark.parametrize("framework", ["openai", "langgraph"])
def test_continuation_uses_current_application_artifact(framework: str) -> None:
    packet = _packet()
    current = Artifact(name="api.json", content={"field": "new_cursor"})
    contract = ReceiverContract(
        goal="Review API", required=("artifacts",), max_tokens=600
    )
    if framework == "openai":
        pytest.importorskip("agents")
        from agents.handoffs import HandoffInputData

        data = HandoffInputData(
            input_history=({"role": "user", "content": packet.to_receiver_text()},),
            pre_handoff_items=(),
            new_items=(),
        )
        result = compile_openai_handoff(
            data, contract, sender="coder", receiver="reviewer", artifacts=[current]
        )
    else:
        pytest.importorskip("langchain_core.messages")
        graph_message = pytest.importorskip("langgraph.graph.message")
        update = LangGraphHandoff(packet).state_update()
        state = {
            "messages": graph_message.add_messages([], update["messages"]),
            "artifacts": [current.model_dump()],
        }
        result = compile_langgraph_state(
            state, contract, sender="coder", receiver="reviewer"
        )
    assert len(result.packet.artifacts) == 1
    assert result.packet.artifacts[0].content == {"field": "new_cursor"}
    assert packet.artifacts[0].content == {"field": "cursor"}


@pytest.mark.parametrize("legacy", [False, True])
def test_openai_packet_continues_with_new_work_and_artifacts(legacy: bool) -> None:
    agents = pytest.importorskip("agents")
    from agents.handoffs import HandoffInputData
    from agents.items import InputItem

    packet = _packet()
    text = (
        json.dumps(packet.model_dump(mode="json"))
        if legacy
        else packet.to_receiver_text()
    )
    history = ({"role": "user", "content": text},)
    raw = {
        "role": "assistant",
        "content": "Completed: Parser implemented.\nTODO: Review parser.",
    }
    data = HandoffInputData(
        input_history=history,
        pre_handoff_items=(),
        new_items=(InputItem(agent=agents.Agent(name="coder"), raw_item=raw),),
        run_context=object(),
    )
    reports = []
    source_before = repr(data)
    extra = Artifact(name="parser.py", content="def parse(): pass")
    result = OpenAIReceiverContractFilter(
        _review_contract(),
        sender="coder",
        receiver="reviewer",
        artifacts=(packet.artifacts[0], extra),
        on_compile=reports.append,
    )(data)
    compiled = HandoffPacket.model_validate_json(result.input_history[0]["content"])
    assert compiled.sender == "coder"
    assert compiled.receiver == "reviewer"
    assert compiled.goal == "Review parser"
    assert compiled.constraints[0].content == "Keep the cursor format."
    assert compiled.decisions[0].content == "Use composite cursors."
    assert compiled.failed_attempts[0].content == packet.failed_attempts[0].content
    assert compiled.completed_work[0].content == "Parser implemented."
    assert compiled.pending_work[-1].content == "Review parser."
    assert [artifact.name for artifact in compiled.artifacts] == [
        "api.json",
        "parser.py",
    ]
    assert repr(data) == source_before
    assert result.new_items is data.new_items
    assert result.run_context is data.run_context
    assert reports[0].packet_tokens <= _review_contract().max_tokens


def test_openai_ordinary_json_remains_history_and_wrong_receiver_is_rejected() -> None:
    pytest.importorskip("agents")
    from agents.handoffs import HandoffInputData

    def snapshot(text: str) -> HandoffInputData:
        return HandoffInputData(
            input_history=({"role": "user", "content": text},),
            pre_handoff_items=(),
            new_items=(),
        )

    with pytest.raises(ContractError, match="constraints"):
        compile_openai_handoff(
            snapshot('{"constraints":["not an explicit receiver packet"]}'),
            _review_contract(),
            sender="coder",
            receiver="reviewer",
        )
    with pytest.raises(HandoffIntegrityError, match="current sender"):
        compile_openai_handoff(
            snapshot(_packet().to_receiver_text()),
            _review_contract(),
            sender="other-agent",
            receiver="reviewer",
        )


@pytest.mark.parametrize("packet_key", ["handoff_packet", None])
def test_langgraph_packet_continues_from_resolved_message_state(packet_key) -> None:
    messages = pytest.importorskip("langchain_core.messages")
    graph_message = pytest.importorskip("langgraph.graph.message")
    packet = _packet()
    update = LangGraphHandoff(packet, packet_key=packet_key).state_update()
    state = {
        **update,
        "messages": graph_message.add_messages([], update["messages"])
        + [
            messages.AIMessage(
                content="Completed: Parser implemented.\nTODO: Review parser."
            )
        ],
        "artifacts": [packet.artifacts[0].model_dump()],
    }
    source = deepcopy(state)
    result = compile_langgraph_state(
        state, _review_contract(), sender="coder", receiver="reviewer"
    )
    assert result.packet.constraints[0].content == "Keep the cursor format."
    assert result.packet.decisions[0].content == "Use composite cursors."
    assert result.packet.completed_work[0].content == "Parser implemented."
    assert result.packet.pending_work[-1].content == "Review parser."
    assert len(result.packet.artifacts) == 1
    assert state == source


def test_langgraph_marked_packet_requires_valid_matching_public_state() -> None:
    pytest.importorskip("langchain_core.messages")
    graph_message = pytest.importorskip("langgraph.graph.message")
    update = LangGraphHandoff(_packet()).state_update()
    state = {"messages": graph_message.add_messages([], update["messages"])}
    state["messages"][0].content = "Not a receiver packet"
    with pytest.raises(HandoffIntegrityError, match="marker"):
        compile_langgraph_state(
            state, _review_contract(), sender="coder", receiver="reviewer"
        )


@pytest.mark.parametrize("framework", ["openai", "langgraph"])
@pytest.mark.parametrize("orphan", [True, False])
def test_previous_packet_does_not_hide_broken_tool_history(framework, orphan) -> None:
    text = _packet().to_receiver_text()
    contract = ReceiverContract(
        goal="Review", required=("constraints",), max_tokens=500
    )
    if framework == "openai":
        pytest.importorskip("agents")
        from agents.handoffs import HandoffInputData

        broken = (
            {"type": "function_call_output", "call_id": "broken", "output": "orphan"}
            if orphan
            else {
                "type": "function_call",
                "call_id": "broken",
                "name": "check",
                "arguments": "{}",
            }
        )
        data = HandoffInputData(
            input_history=({"role": "user", "content": text}, broken),
            pre_handoff_items=(),
            new_items=(),
        )
        with pytest.raises(HandoffIntegrityError):
            compile_openai_handoff(data, contract, sender="coder", receiver="reviewer")
    else:
        messages = pytest.importorskip("langchain_core.messages")
        pytest.importorskip("langgraph")
        broken = (
            messages.ToolMessage(content="orphan", tool_call_id="broken")
            if orphan
            else messages.AIMessage(
                content="", tool_calls=[{"id": "broken", "name": "check", "args": {}}]
            )
        )
        state = {"messages": [messages.HumanMessage(content=text), broken]}
        with pytest.raises(HandoffIntegrityError):
            compile_langgraph_state(
                state, contract, sender="coder", receiver="reviewer"
            )


def test_real_langgraph_runs_two_handoffs_and_preserves_latest_artifact() -> None:
    messages = pytest.importorskip("langchain_core.messages")
    graph_api = pytest.importorskip("langgraph.graph")

    # Evaluate the local reducer now; postponed class annotations cannot see it.
    State = TypedDict(  # noqa: UP013
        "RelayState",
        {
            "messages": Annotated[list[Any], graph_api.add_messages],
            "artifacts": list[dict[str, Any]],
            "handoff_packet": dict[str, Any],
            "observed": dict[str, Any],
        },
        total=False,
    )

    def researcher(state: State) -> Any:
        compilation = compile_langgraph_state(
            state,
            ReceiverContract(
                goal="Implement parser",
                required=("constraints", "decisions", "pending_work", "artifacts"),
                max_tokens=1000,
            ),
            sender="researcher",
            receiver="coder",
        )
        return LangGraphHandoff(compilation.packet).command("coder")

    def coder(state: State) -> dict[str, Any]:
        assert len(state["messages"]) == 1
        return {
            "messages": [
                messages.AIMessage(
                    content="Completed: Parser implemented.\nTODO: Review parser."
                )
            ],
            "artifacts": [{"name": "parser.py", "content": "new implementation"}],
        }

    def route_review(state: State) -> Any:
        result = compile_langgraph_state(
            state, _review_contract(), sender="coder", receiver="reviewer"
        )
        return LangGraphHandoff(result.packet).command("reviewer")

    def reviewer(state: State) -> dict[str, Any]:
        assert len(state["messages"]) == 1
        return {"observed": json.loads(state["messages"][0].content)}

    graph = graph_api.StateGraph(State)
    for name, node in (
        ("researcher", researcher),
        ("coder", coder),
        ("route_review", route_review),
        ("reviewer", reviewer),
    ):
        graph.add_node(name, node)
    graph.add_edge(graph_api.START, "researcher")
    graph.add_edge("coder", "route_review")
    graph.add_edge("reviewer", graph_api.END)
    result = graph.compile().invoke(
        {
            "messages": [
                messages.HumanMessage(content=text)
                for text in (
                    "Constraint: Keep the cursor format.",
                    "Decision: Use composite cursors.",
                    "TODO: Implement parser.",
                )
            ],
            "artifacts": [{"name": "parser.py", "content": "old implementation"}],
        }
    )
    observed = HandoffPacket.model_validate(result["observed"])
    assert observed.goal == "Review parser"
    assert observed.constraints[0].content == "Keep the cursor format."
    assert observed.decisions[0].content == "Use composite cursors."
    assert observed.completed_work[0].content == "Parser implemented."
    assert observed.artifacts[0].content == "new implementation"
