from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from handoff_sieve import (
    Artifact,
    CallbackReporter,
    HandoffEnvelope,
    HandoffIntegrityError,
    HandoffPipeline,
    Message,
    ReceiverContract,
    UnsupportedAdapterModeError,
    compile_handoff,
)
from handoff_sieve.adapters import OpenAIHandoffFilter, OpenAIHandoffPacketFilter
from handoff_sieve.policies import BudgetPolicy, ExactDedupPolicy, RedactPolicy


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


def test_openai_packet_filter_exposes_only_canonical_packet_to_receiver() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.handoffs import HandoffInputData
    from agents.items import InputItem

    compilation = compile_handoff(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[
                Message(content="Use signed sessions", kind="decisions"),
                Message(content={"tests": ["unit", "integration"]}, kind="evidence"),
                Message(content="irrelevant sender history"),
            ],
            artifacts=[Artifact(name="auth.py", content="def authenticate(): ...")],
        ),
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "artifacts"],
            preferred=["evidence"],
            max_tokens=2_000,
        ),
    )
    agent = Agent(name="researcher")

    def item(text: str) -> InputItem:
        return InputItem(
            agent=agent,
            raw_item={"role": "user", "content": text},
        )

    run_context = object()
    new_items = (item("handoff event retained only for session history"),)
    data = HandoffInputData(
        input_history=({"role": "user", "content": "large runtime history"},),
        pre_handoff_items=(item("pre-handoff scratch work"),),
        new_items=new_items,
        run_context=run_context,
    )
    packet_filter = OpenAIHandoffPacketFilter(compilation.packet)
    receiver_text = compilation.packet.to_receiver_text()
    compilation.packet.goal = "mutated after filter construction"

    filtered = packet_filter(data)

    assert filtered.input_history == (
        {
            "role": "user",
            "content": receiver_text,
        },
    )
    assert json.loads(filtered.input_history[0]["content"])["goal"] == (
        "Implement authentication"
    )
    assert packet_filter.receiver_text == receiver_text
    assert filtered.pre_handoff_items == ()
    assert filtered.input_items == ()
    assert filtered.new_items is new_items
    assert filtered.run_context is run_context
    assert "large runtime history" not in repr(filtered.input_history)
    assert "pre-handoff scratch work" not in repr(filtered.input_history)

    with pytest.raises(
        UnsupportedAdapterModeError,
        match="OpenAIHandoffPacketFilter requires a complete HandoffInputData",
    ):
        packet_filter(object())


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


def test_two_openai_agents_receive_compiled_packet_as_complete_view() -> None:
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
                        call_id="packet_handoff_call",
                        name=handoffs[0].tool_name,
                        type="function_call",
                    )
                ],
                usage=Usage(),
                response_id="packet-researcher-response",
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
                        id="packet-coder-message",
                        content=[
                            ResponseOutputText(
                                annotations=[],
                                text="packet handoff complete",
                                type="output_text",
                            )
                        ],
                        role="assistant",
                        status="completed",
                        type="message",
                    )
                ],
                usage=Usage(),
                response_id="packet-coder-response",
            )

        async def stream_response(self, *args, **kwargs):
            if False:
                yield None

    compilation = compile_handoff(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[
                Message(content="Use signed sessions", kind="decisions"),
                Message(content="Implement auth middleware", kind="pending_work"),
                Message(content="competitor research that coder does not need"),
            ],
            artifacts=[Artifact(name="auth.py", content="def authenticate(): ...")],
        ),
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "pending_work", "artifacts"],
            max_tokens=2_000,
        ),
    )
    final_model = FinalModel()
    coder = Agent(name="coder", model=final_model)
    researcher = Agent(
        name="researcher",
        model=HandoffModel(),
        handoffs=[
            handoff(
                coder,
                input_filter=OpenAIHandoffPacketFilter(compilation.packet),
            )
        ],
    )

    result = Runner.run_sync(
        researcher,
        "runtime conversation that the coder must not receive",
        run_config=RunConfig(tracing_disabled=True),
    )

    assert result.final_output == "packet handoff complete"
    assert result.last_agent is coder
    assert final_model.inputs == [
        [
            {
                "role": "user",
                "content": compilation.packet.to_receiver_text(),
            }
        ]
    ]
    receiver_input = repr(final_model.inputs)
    assert "Use signed sessions" in receiver_input
    assert "Implement auth middleware" in receiver_input
    assert "auth.py" in receiver_input
    assert "competitor research" not in receiver_input
    assert "runtime conversation" not in receiver_input
