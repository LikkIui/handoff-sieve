from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from handoff_sieve import (
    Artifact,
    BudgetExceededError,
    ContractError,
    HandoffEnvelope,
    Message,
    NeedCoverage,
    ReceiverContract,
    SelectionPlan,
    SelectionResponse,
    SourceSelection,
    compile_handoff,
    compile_model_handoff,
)
from handoff_sieve.adapters import OpenAIHandoffSelector, OpenAIModelHandoffFilter
from handoff_sieve.model_selection import source_units
from handoff_sieve.pipeline import HandoffPipeline


class Selector:
    def __init__(self, plan):
        self.plan = plan
        self.requests = []

    async def select(self, request):
        self.requests.append(request)
        return SelectionResponse(plan=self.plan)


def plan(*items, coverage=(), missing=()):
    return SelectionPlan(
        selections=[
            SourceSelection(source_id=source_id, section=section, essential=essential)
            for source_id, section, essential in items
        ],
        coverage=[
            NeedCoverage(need_index=index, source_ids=list(ids))
            for index, ids in coverage
        ],
        missing_needs=list(missing),
    )


def state():
    return HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content=(
                    "Old hosting discussion.\nKeep the API unchanged.\nUse SQLite.\n"
                )
            )
        ],
        artifacts=[Artifact(name="src/auth.py", content="def login():\n    pass\n")],
    )


def contract(**kwargs):
    return ReceiverContract(
        goal="Implement persistent login",
        required=("constraints",),
        preferred=("decisions", "evidence", "artifacts"),
        max_tokens=1000,
        **kwargs,
    )


def compile_with(selected, *, source=None, receiver=None):
    return asyncio.run(
        compile_model_handoff(
            source or state(),
            receiver or contract(),
            selector=Selector(selected),
        )
    )


def test_unlabeled_history_is_selected_by_source_and_needs_are_pinned():
    source = state()
    before = source.model_dump()
    selected = plan(
        ("m0.1", "constraints", False),
        ("m0.2", "decisions", False),
        ("a0", "artifacts", False),
        coverage=((0, ("m0.2", "a0")),),
    )
    result = compile_with(
        selected,
        source=source,
        receiver=contract(needs=("Storage choice and implementation file",)),
    )
    assert result.packet.constraints[0].content == "Keep the API unchanged.\n"
    assert result.packet.decisions[0].content == "Use SQLite.\n"
    assert result.packet.artifacts[0].content == source.artifacts[0].content
    assert "Old hosting" not in result.packet.to_receiver_text()
    assert result.packet_tokens <= 1000
    assert source.model_dump() == before
    assert result.selection.unselected_source_ids == ["m0.0"]


@pytest.mark.parametrize(
    "selected, match",
    [
        (plan(("invented", "constraints", True)), "unknown source"),
        (plan(("m0.1", "constraints", True), ("m0.1", "constraints", True)), "twice"),
        (plan(("m0.1", "pending_work", True)), "unrequested"),
        (plan(("a0", "constraints", True)), "artifact"),
        (plan(("m0.1", "artifacts", True)), "artifact"),
        (plan(("m0.2", "decisions", True)), "required sections"),
    ],
)
def test_invalid_model_references_are_rejected(selected, match):
    with pytest.raises(ContractError, match=match):
        compile_with(selected)


@pytest.mark.parametrize(
    "coverage, missing",
    [
        ((), ()),
        (((0, ("m0.2",)),), ()),
        (((1, ("m0.1",)),), ()),
        (((0, ()),), ()),
        (((0, ("m0.1",)), (0, ("m0.1",))), ()),
        ((), (0,)),
    ],
)
def test_missing_or_invalid_need_coverage_fails(coverage, missing):
    with pytest.raises(ContractError):
        compile_with(
            plan(("m0.1", "constraints", False), coverage=coverage, missing=missing),
            receiver=contract(needs=("Preserve API",)),
        )


def test_tight_budget_skips_optional_but_never_need_evidence():
    source = state()
    source.messages.append(Message(content="unrelated " * 1500))
    selected = plan(("m0.1", "constraints", False), ("m1.0", "evidence", False))
    result = compile_with(selected, source=source)
    assert result.selection.budget_omitted_source_ids == ["m1.0"]
    with pytest.raises(BudgetExceededError):
        compile_with(
            plan(
                ("m0.1", "constraints", False),
                ("m1.0", "evidence", False),
                coverage=((0, ("m1.0",)),),
            ),
            source=source,
            receiver=contract(needs=("Required evidence",)),
        )


def test_source_catalog_keeps_code_fences_and_structured_results_atomic():
    source = HandoffEnvelope(
        sender="a",
        receiver="b",
        messages=[
            Message(content="Context\n```python\nx = 1\ny = 2\n```\nAfter\n"),
            Message(role="tool", content={"output": {"failures": ["test_api"]}}),
        ],
    )
    units = source_units(source, HandoffPipeline())
    assert len(units) == 4
    assert units[1].content == "```python\nx = 1\ny = 2\n```\n"
    assert units[3].content == source.messages[1].content


def test_deterministic_path_does_not_silently_ignore_natural_language_needs():
    with pytest.raises(ContractError, match="compile_model_handoff"):
        compile_handoff(state(), contract(needs=("Preserve API",)))


def test_selector_input_is_an_isolated_copy():
    source = HandoffEnvelope(
        sender="a",
        receiver="b",
        messages=[
            Message(content={"constraint": {"limit": 17}}),
        ],
    )

    class MutatingSelector:
        async def select(self, request):
            request.units[0].content["constraint"]["limit"] = 99
            return SelectionResponse(plan=plan(("m0.0", "constraints", True)))

    result = asyncio.run(
        compile_model_handoff(source, contract(), selector=MutatingSelector())
    )
    assert result.packet.constraints[0].content == {"constraint": {"limit": 17}}
    assert source.messages[0].content == {"constraint": {"limit": 17}}


def test_openai_selector_uses_schema_and_reports_actual_usage():
    selected = {
        "selections": [
            {
                "unit_index": 1,
                "section": "constraints",
                "essential": True,
                "need_indices": [],
            }
        ],
        "missing_needs": [],
    }

    class Responses:
        async def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                status="completed",
                output_text=json.dumps(selected),
                id="response-1",
                usage=SimpleNamespace(
                    input_tokens=50, output_tokens=20, total_tokens=70
                ),
            )

    responses = Responses()
    backend = OpenAIHandoffSelector(
        SimpleNamespace(responses=responses), model="test-model"
    )
    result = asyncio.run(compile_model_handoff(state(), contract(), selector=backend))
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert result.selector_usage.total_tokens == 70


def test_indexed_selector_coverage_can_only_reference_selected_original_units():
    from handoff_sieve.adapters.openai_selector import (
        _selection_plan,
        _selector_payload,
    )
    from handoff_sieve.model_selection import SelectionRequest

    source = state()
    request = SelectionRequest(
        receiver="coder",
        contract=contract(needs=("API compatibility", "Accepted implementation")),
        units=source_units(source, HandoffPipeline()),
    )
    payload, schema = _selector_payload(request)
    assert json.loads(payload)["units"][1]["unit_index"] == 1
    assert "source_id" not in json.loads(payload)["units"][1]
    props = schema["$defs"]["_IndexedSelection"]["properties"]
    assert props["unit_index"]["maximum"] == len(request.units) - 1
    assert props["need_indices"]["items"]["maximum"] == 1
    selected = _selection_plan(
        json.dumps(
            {
                "selections": [
                    {
                        "unit_index": 1,
                        "section": "constraints",
                        "essential": False,
                        "need_indices": [0, 1],
                    }
                ],
                "missing_needs": [],
            }
        ),
        request,
    )
    result = compile_with(selected, source=source, receiver=request.contract)
    assert result.selection.selected_source_ids == ["m0.1"]
    assert [item.source_ids for item in selected.coverage] == [["m0.1"], ["m0.1"]]
    assert result.packet.constraints[0].content == "Keep the API unchanged.\n"


@pytest.mark.parametrize(
    "indices, needs",
    [([4], [[]]), ([1, 1], [[], []]), ([1], [[1]]), ([1], [[0, 0]])],
)
def test_indexed_selector_rejects_invalid_references_locally(indices, needs):
    from handoff_sieve.adapters.openai_selector import _selection_plan
    from handoff_sieve.model_selection import SelectionRequest

    request = SelectionRequest(
        receiver="coder",
        contract=contract(needs=("Compatibility",)),
        units=source_units(state(), HandoffPipeline()),
    )
    response = {
        "selections": [
            {
                "unit_index": index,
                "section": "constraints",
                "essential": True,
                "need_indices": coverage,
            }
            for index, coverage in zip(indices, needs, strict=True)
        ],
        "missing_needs": [],
    }
    with pytest.raises(ContractError):
        _selection_plan(json.dumps(response), request)


def test_sdk_model_filter_sends_only_packet_and_keeps_original_input():
    pytest.importorskip("agents")
    from agents.handoffs import HandoffInputData

    data = HandoffInputData(
        input_history=(
            {"role": "user", "content": "Keep the API unchanged.\nHosting notes."},
        ),
        pre_handoff_items=(),
        new_items=(),
    )
    observed = []
    filter_ = OpenAIModelHandoffFilter(
        contract(),
        selector=Selector(plan(("m0.0", "constraints", True))),
        sender="researcher",
        receiver="coder",
        on_compile=observed.append,
    )
    output = asyncio.run(filter_(data))
    assert len(output.input_history) == 1
    assert "Hosting notes" not in output.input_history[0]["content"]
    assert "Hosting notes" in data.input_history[0]["content"]
    assert output.input_items == ()
    assert len(observed) == 1


def test_selector_input_omits_coordinates_but_keeps_relevance_metadata():
    source = state()
    source.messages[0].metadata["topic"] = "login"
    selector = Selector(plan(("m0.1", "constraints", True)))
    asyncio.run(compile_model_handoff(source, contract(), selector=selector))
    request = selector.requests[0]
    payload = json.loads(request.to_selector_text())
    assert payload["units"][0]["metadata"] == {"topic": "login"}
    assert "start" not in payload["units"][0]
    assert "source_index" not in payload["units"][0]
    assert request.units[0].start == 0


def test_optional_state_that_cannot_fit_does_not_produce_an_empty_packet():
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="large source " * 1000)],
    )
    with pytest.raises(BudgetExceededError, match="No model-selected"):
        compile_with(
            plan(("m0.0", "evidence", False)),
            source=source,
            receiver=ReceiverContract(
                goal="Inspect", required=(), preferred=("evidence",), max_tokens=200
            ),
        )
