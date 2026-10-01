from __future__ import annotations

import json

import pytest

from handoff_sieve import (
    BudgetExceededError,
    ContractError,
    HandoffIntegrityError,
    ReceiverContract,
    UnsupportedAdapterModeError,
)
from handoff_sieve.adapters import (
    OpenAIReceiverContractFilter,
    compile_openai_handoff,
)

pytest.importorskip("agents")
from agents import Agent
from agents.handoffs import HandoffInputData
from agents.items import InputItem


def item(raw: dict) -> InputItem:
    return InputItem(agent=Agent(name="researcher"), raw_item=raw)


def snapshot(history=(), *, prior=(), new=(), model=None) -> HandoffInputData:
    return HandoffInputData(
        input_history=history,
        pre_handoff_items=tuple(item(raw) for raw in prior),
        new_items=tuple(item(raw) for raw in new),
        input_items=None if model is None else tuple(item(raw) for raw in model),
        run_context=object(),
    )


def test_live_snapshot_includes_new_decisions_and_paired_tool_result() -> None:
    data = snapshot(
        (
            {"role": "user", "content": "Unrelated launch copy."},
            {"role": "user", "content": "Constraint: Preserve the API."},
            {
                "type": "function_call",
                "call_id": "check-1",
                "name": "check_tests",
                "arguments": "{}",
            },
        ),
        prior=(
            {"type": "function_call_output", "call_id": "check-1", "output": "passed"},
        ),
        new=(
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Decision: Use signed sessions."},
                    {"type": "output_text", "text": "TODO: Implement middleware."},
                ],
            },
        ),
    )
    source = repr(data)
    reports = []
    filtered = OpenAIReceiverContractFilter(
        ReceiverContract(
            goal="Implement auth",
            required=("constraints", "decisions", "pending_work", "tool_results"),
            max_tokens=700,
        ),
        sender="researcher",
        receiver="coder",
        on_compile=reports.append,
    )(data)
    packet = json.loads(filtered.input_history[0]["content"])
    assert packet["decisions"][0]["content"] == "Use signed sessions."
    assert packet["pending_work"][0]["content"] == "Implement middleware."
    assert packet["tool_results"][0]["content"]["tool_result"] == {
        "call_id": "check-1",
        "name": "check_tests",
        "arguments": "{}",
        "output": "passed",
    }
    assert "launch copy" not in filtered.input_history[0]["content"]
    assert repr(data) == source
    assert filtered.new_items is data.new_items
    assert filtered.run_context is data.run_context
    assert filtered.pre_handoff_items == filtered.input_items == ()
    assert reports[0].packet_tokens <= 700


def test_input_items_override_session_items_and_filter_recompiles_each_call() -> None:
    contract = ReceiverContract(
        goal="Implement", required=("decisions",), max_tokens=500
    )
    reports = []
    adapter = OpenAIReceiverContractFilter(
        contract, sender="researcher", receiver="coder", on_compile=reports.append
    )
    for decision in ("First", "Latest"):
        data = snapshot(
            new=({"role": "assistant", "content": "Decision: session-only item"},),
            model=({"role": "assistant", "content": f"Decision: {decision}"},),
        )
        filtered = adapter(data)
        assert (
            json.loads(filtered.input_history[0]["content"])["decisions"][0]["content"]
            == decision
        )
        assert "session-only" not in filtered.input_history[0]["content"]
    assert len(reports) == 2


@pytest.mark.parametrize(
    "history",
    [
        ({"type": "function_call_output", "call_id": "orphan", "output": "x"},),
        ({"type": "function_call", "call_id": "pending", "name": "check"},),
        (
            {"type": "function_call", "call_id": "same", "name": "check"},
            {"type": "function_call", "call_id": "same", "name": "check"},
        ),
    ],
)
def test_contract_compilation_rejects_incomplete_tool_history(history) -> None:
    with pytest.raises(HandoffIntegrityError):
        compile_openai_handoff(
            snapshot(history),
            ReceiverContract(goal="Review", max_tokens=500),
            sender="researcher",
            receiver="reviewer",
        )


def test_contract_failures_are_not_silently_replaced_by_full_history() -> None:
    data = snapshot("Decision: Use signed sessions.")
    with pytest.raises(ContractError, match="pending_work") as captured:
        compile_openai_handoff(
            data,
            ReceiverContract(
                goal="Implement", required=("pending_work",), max_tokens=500
            ),
            sender="researcher",
            receiver="coder",
        )
    assert captured.value.diagnostics is not None
    assert captured.value.diagnostics.missing_sections == ("pending_work",)
    assert captured.value.normalization is not None
    assert captured.value.normalization.unclassified_message_indices == ()
    with pytest.raises(BudgetExceededError):
        compile_openai_handoff(
            data,
            ReceiverContract(goal="Implement", required=("decisions",), max_tokens=1),
            sender="researcher",
            receiver="coder",
        )


def test_multimodal_and_non_snapshot_inputs_require_explicit_mapper() -> None:
    contract = ReceiverContract(goal="Review", max_tokens=500)
    for data in (
        object(),
        snapshot(
            (
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "https://example.test/a"}
                    ],
                },
            )
        ),
    ):
        with pytest.raises(UnsupportedAdapterModeError):
            compile_openai_handoff(data, contract, sender="a", receiver="b")
