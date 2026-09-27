from __future__ import annotations

import pytest

from relayguard import HandoffPipeline
from relayguard.adapters import OpenAIHandoffFilter
from relayguard.policies import BudgetPolicy, ExactDedupPolicy, RedactPolicy


def test_openai_adapter_processes_raw_history_without_sdk() -> None:
    adapter = OpenAIHandoffFilter(
        HandoffPipeline([RedactPolicy(), ExactDedupPolicy()]),
        sender="triage",
        receiver="specialist",
    )
    history = (
        {"role": "user", "content": "Email alice@example.com"},
        {"role": "user", "content": "Email alice@example.com"},
    )

    processed = adapter._process_history(history)

    assert processed == (
        {"role": "user", "content": "Email [REDACTED:email]"},
    )
    assert adapter.last_reports[0].redactions == 2
    assert adapter.last_reports[0].duplicates_removed == 1


def test_openai_adapter_marks_tool_items_as_protected() -> None:
    message = OpenAIHandoffFilter._to_message(
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "result",
        },
        source_index=0,
    )

    assert message.protected is True
    assert "openai_control" in message.tags


def test_openai_sdk_adapter_enforces_one_budget_across_all_segments() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.handoffs import HandoffInputData
    from agents.items import InputItem

    agent = Agent(name="test-agent")

    def item(text: str) -> InputItem:
        return InputItem(
            agent=agent,
            raw_item={"role": "user", "content": text},
        )

    run_context = object()
    data = HandoffInputData(
        input_history=({"role": "user", "content": "h" * 80},),
        pre_handoff_items=(item("p" * 80),),
        new_items=(item("n" * 80),),
        run_context=run_context,
    )
    adapter = OpenAIHandoffFilter(
        HandoffPipeline([BudgetPolicy(80, strategy="drop_oldest")]),
        sender="triage",
        receiver="specialist",
    )

    filtered = adapter(data)

    assert filtered.input_history == ()
    assert filtered.pre_handoff_items == ()
    assert len(filtered.input_items) == 1
    assert filtered.input_items[0].raw_item["content"] == "n" * 80
    assert filtered.new_items == data.new_items
    assert filtered.run_context is run_context
    assert len(adapter.last_reports) == 1
    assert adapter.last_reports[0].original_tokens > 80
    assert adapter.last_reports[0].transmitted_tokens <= 80
