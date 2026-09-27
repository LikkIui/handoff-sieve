from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from relayguard import (
    CallbackReporter,
    HandoffIntegrityError,
    HandoffPipeline,
    UnsupportedAdapterModeError,
)
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

    assert processed == ({"role": "user", "content": "Email [REDACTED:email]"},)
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


def test_openai_adapter_reports_do_not_leak_between_threads() -> None:
    adapter = OpenAIHandoffFilter(
        HandoffPipeline([RedactPolicy(detectors=["email"])]),
        sender="triage",
        receiver="specialist",
    )

    def run(content: str) -> tuple[str, int, str]:
        processed = adapter._process_history(({"role": "user", "content": content},))
        report = adapter.last_reports[0]
        return processed[0]["content"], report.redactions, report.handoff_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        secret = executor.submit(run, "Email alice@example.com")
        ordinary = executor.submit(run, "No secret here")
        secret_result = secret.result()
        ordinary_result = ordinary.result()

    assert secret_result[0] == "Email [REDACTED:email]"
    assert secret_result[1] == 1
    assert ordinary_result[0] == "No secret here"
    assert ordinary_result[1] == 0
    assert secret_result[2] != ordinary_result[2]
    assert adapter.last_reports == []


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


def test_openai_sdk_adapter_preserves_tool_call_output_pair() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.handoffs import HandoffInputData
    from agents.items import ToolCallItem, ToolCallOutputItem

    agent = Agent(name="test-agent")
    tool_call = ToolCallItem(
        agent=agent,
        raw_item={
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
        },
    )
    tool_output = ToolCallOutputItem(
        agent=agent,
        raw_item={
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "result",
        },
        output="result",
    )
    data = HandoffInputData(
        input_history=(),
        pre_handoff_items=(tool_call,),
        new_items=(tool_output,),
        run_context=object(),
    )
    adapter = OpenAIHandoffFilter(
        HandoffPipeline(),
        sender="triage",
        receiver="specialist",
    )

    filtered = adapter(data)

    assert filtered.pre_handoff_items[0].raw_item["type"] == "function_call"
    assert filtered.pre_handoff_items[0].raw_item["call_id"] == "call_1"
    assert filtered.input_items[0].raw_item["type"] == "function_call_output"
    assert filtered.input_items[0].raw_item["call_id"] == "call_1"
    pair_event = next(
        event
        for event in adapter.last_reports[0].events
        if event.policy == "openai_tool_pairs"
    )
    assert pair_event.details["tool_invocations"] == 1
    assert pair_event.details["paired_outputs"] == 1


def test_openai_sdk_adapter_denies_orphan_tool_output_with_report() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.handoffs import HandoffInputData
    from agents.items import ToolCallOutputItem

    reports = []
    agent = Agent(name="test-agent")
    tool_output = ToolCallOutputItem(
        agent=agent,
        raw_item={
            "type": "function_call_output",
            "call_id": "call_orphan",
            "output": "result",
        },
        output="result",
    )
    data = HandoffInputData(
        input_history=(),
        pre_handoff_items=(),
        new_items=(tool_output,),
        run_context=object(),
    )
    adapter = OpenAIHandoffFilter(
        HandoffPipeline(reporters=[CallbackReporter(reports.append)]),
        sender="triage",
        receiver="specialist",
    )

    with pytest.raises(HandoffIntegrityError, match="no preceding matching") as error:
        adapter(data)

    assert error.value.report is not None
    assert error.value.report.status == "denied"
    assert error.value.report.failure_code == "handoff_integrity"
    assert error.value.report.failed_policy == "openai_tool_pairs"
    assert adapter.last_reports[0].handoff_id == error.value.report.handoff_id
    assert reports[0].handoff_id == error.value.report.handoff_id


def test_openai_adapter_rejects_unsupported_input_shape_clearly() -> None:
    pytest.importorskip("agents")
    adapter = OpenAIHandoffFilter(
        HandoffPipeline(),
        sender="triage",
        receiver="specialist",
    )

    with pytest.raises(UnsupportedAdapterModeError, match="complete HandoffInputData"):
        adapter(object())

    assert len(adapter.last_reports) == 1
    assert adapter.last_reports[0].status == "denied"
    assert adapter.last_reports[0].failure_code == "unsupported_adapter_mode"
    assert adapter.last_reports[0].failed_policy == "openai_adapter"


def test_two_openai_agents_complete_offline_filtered_handoff() -> None:
    pytest.importorskip("agents")
    from agents import Agent, RunConfig, Runner, handoff
    from agents.models.interface import Model, ModelResponse
    from agents.usage import Usage
    from openai.types.responses import (
        ResponseFunctionToolCall,
        ResponseOutputMessage,
        ResponseOutputText,
    )

    class HandoffModel(Model):
        async def get_response(
            self,
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            **kwargs,
        ) -> ModelResponse:
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments="{}",
                        call_id="handoff_call_1",
                        name=handoffs[0].tool_name,
                        type="function_call",
                    )
                ],
                usage=Usage(),
                response_id="researcher-response",
            )

        async def stream_response(self, *args, **kwargs):
            if False:
                yield None

    class FinalModel(Model):
        def __init__(self) -> None:
            self.inputs = []

        async def get_response(
            self,
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            **kwargs,
        ) -> ModelResponse:
            self.inputs.append(input)
            return ModelResponse(
                output=[
                    ResponseOutputMessage(
                        id="writer-message",
                        content=[
                            ResponseOutputText(
                                annotations=[],
                                text="handoff complete",
                                type="output_text",
                            )
                        ],
                        role="assistant",
                        status="completed",
                        type="message",
                    )
                ],
                usage=Usage(),
                response_id="writer-response",
            )

        async def stream_response(self, *args, **kwargs):
            if False:
                yield None

    reports = []
    final_model = FinalModel()
    writer = Agent(name="writer", model=final_model)
    handoff_filter = OpenAIHandoffFilter(
        HandoffPipeline(
            [RedactPolicy(detectors=["email"])],
            reporters=[CallbackReporter(reports.append)],
        ),
        sender="researcher",
        receiver="writer",
    )
    researcher = Agent(
        name="researcher",
        model=HandoffModel(),
        handoffs=[handoff(writer, input_filter=handoff_filter)],
    )

    result = Runner.run_sync(
        researcher,
        "Send alice@example.com to the writer",
        run_config=RunConfig(tracing_disabled=True),
    )

    assert result.final_output == "handoff complete"
    assert result.last_agent is writer
    assert len(reports) == 1
    assert reports[0].status == "passed"
    assert reports[0].redactions == 1
    assert "alice@example.com" not in repr(final_model.inputs)
    assert "[REDACTED:email]" in repr(final_model.inputs)
