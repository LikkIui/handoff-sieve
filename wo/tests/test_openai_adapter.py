from __future__ import annotations

from relayguard import HandoffPipeline
from relayguard.adapters import OpenAIHandoffFilter
from relayguard.policies import ExactDedupPolicy, RedactPolicy


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
