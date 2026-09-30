"""Smoke-test an installed HandoffSieve distribution outside the source tree."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

import handoff_sieve
from handoff_sieve import (
    HandoffEnvelope,
    HandoffPipeline,
    Message,
    ReceiverContract,
    compile_handoff,
    compile_history,
)
from handoff_sieve.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    PreservePolicy,
    RedactPolicy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--forbid-source-root", type=Path, required=True)
    parser.add_argument("--openai", action="store_true")
    parser.add_argument("--langgraph", action="store_true")
    return parser.parse_args()


def verify_core(
    *, distribution: str, expected_version: str, forbid_source_root: Path
) -> None:
    installed_version = metadata.version(distribution)
    assert installed_version == expected_version
    assert handoff_sieve.__version__ == expected_version

    package_path = Path(handoff_sieve.__file__).resolve()
    source_root = forbid_source_root.resolve()
    assert not package_path.is_relative_to(source_root), (
        f"smoke test imported source checkout instead of artifact: {package_path}"
    )

    pipeline = HandoffPipeline(
        [
            PreservePolicy(),
            RedactPolicy(detectors=["email"]),
            ExactDedupPolicy(),
            BudgetPolicy(80, strategy="drop_oldest"),
        ]
    )
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=[
            Message(content="Keep citations.", tags={"constraint"}),
            "Email alice@example.com",
            "Email alice@example.com",
        ],
    )

    assert result.report.status == "passed"
    assert result.report.redactions == 2
    assert result.report.duplicates_removed == 1
    assert "alice@example.com" not in repr(result.messages)
    assert "[REDACTED:email]" in repr(result.messages)

    compilation = compile_handoff(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[Message(content="Use signed sessions", kind="decisions")],
        ),
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions"],
            max_tokens=500,
        ),
    )
    assert compilation.packet.decisions[0].content == "Use signed sessions"
    assert compilation.packet_tokens <= 500

    history_compilation = compile_history(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[
                Message(content="Decision: Use signed sessions"),
                Message(content="TODO: Implement the middleware"),
                Message(content="Unrelated launch discussion"),
            ],
        ),
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "pending_work"],
            max_tokens=500,
        ),
    )
    assert history_compilation.packet.decisions[0].content == "Use signed sessions"
    assert history_compilation.packet.pending_work[0].content == (
        "Implement the middleware"
    )
    assert history_compilation.normalization.unclassified_messages == 1


def verify_openai_adapter() -> None:
    from agents import Agent
    from agents.handoffs import HandoffInputData
    from agents.items import InputItem

    from handoff_sieve.adapters import OpenAIHandoffFilter, OpenAIHandoffPacketFilter

    agent = Agent(name="artifact-smoke-agent")
    input_item = InputItem(
        agent=agent,
        raw_item={"role": "user", "content": "Email alice@example.com"},
    )
    data = HandoffInputData(
        input_history=(),
        pre_handoff_items=(),
        new_items=(input_item,),
        run_context=object(),
    )
    adapter = OpenAIHandoffFilter(
        HandoffPipeline([RedactPolicy(detectors=["email"])]),
        sender="researcher",
        receiver="writer",
    )

    filtered = adapter(data)

    assert filtered.new_items == data.new_items
    assert filtered.run_context is data.run_context
    assert filtered.input_items[0].raw_item["content"] == "Email [REDACTED:email]"
    assert adapter.last_reports[0].status == "passed"

    compilation = compile_handoff(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[Message(content="Use signed sessions", kind="decisions")],
        ),
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions"],
            max_tokens=500,
        ),
    )
    packet_filtered = OpenAIHandoffPacketFilter(compilation.packet)(data)
    assert packet_filtered.input_history[0]["content"] == (
        compilation.packet.to_receiver_text()
    )
    assert packet_filtered.pre_handoff_items == ()
    assert packet_filtered.input_items == ()


def verify_langgraph_adapter() -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.graph.message import REMOVE_ALL_MESSAGES

    from handoff_sieve.adapters import LangGraphHandoff, compile_langgraph_state

    compilation = compile_langgraph_state(
        {
            "messages": [
                HumanMessage(content="Decision: Use signed sessions."),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "check_tests",
                            "args": {},
                        }
                    ],
                ),
                ToolMessage(content="passed", tool_call_id="call_1"),
                HumanMessage(content="TODO: Implement the middleware."),
            ]
        },
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "pending_work", "tool_results"],
            max_tokens=500,
        ),
        sender="researcher",
        receiver="coder",
    )
    update = LangGraphHandoff(compilation.packet).state_update()
    assert update["messages"][0].id == REMOVE_ALL_MESSAGES
    assert update["messages"][1].content == compilation.packet.to_receiver_text()
    assert update["handoff_packet"]["receiver"] == "coder"


def main() -> None:
    args = parse_args()
    verify_core(
        distribution=args.distribution,
        expected_version=args.expected_version,
        forbid_source_root=args.forbid_source_root,
    )
    if args.openai:
        verify_openai_adapter()
    if args.langgraph:
        verify_langgraph_adapter()
    print(f"installed artifact verified: {args.distribution} {args.expected_version}")


if __name__ == "__main__":
    main()
