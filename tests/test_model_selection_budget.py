from __future__ import annotations

import asyncio
import json

import pytest

from handoff_sieve import (
    Artifact,
    BudgetExceededError,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    SelectionPlan,
    SelectionRequest,
    SelectionResponse,
    SourceSelection,
    compile_model_handoff,
)
from handoff_sieve.adapters.openai_selector import _selector_payload
from handoff_sieve.model_selection import _budgeted_request, source_units
from handoff_sieve.pipeline import HandoffPipeline
from handoff_sieve.tokens import ApproxTokenCounter, TiktokenCounter


class Selector:
    def __init__(self, selections):
        self.selections = selections
        self.requests = []

    async def select(self, request):
        self.requests.append(request)
        return SelectionResponse(
            plan=SelectionPlan(
                selections=self.selections,
                coverage=[],
                missing_needs=[],
            )
        )


def selected(source_id, section="evidence"):
    return SourceSelection(source_id=source_id, section=section, essential=True)


def compile_selected(source, receiver, selections, *, pipeline=None):
    selector = Selector(selections)
    result = asyncio.run(
        compile_model_handoff(
            source,
            receiver,
            selector=selector,
            pipeline=pipeline,
        )
    )
    return result, selector.requests[0]


def test_selector_knows_long_goal_leaves_less_than_total_budget_for_source():
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content="Preserve the public API.\n",
                metadata={"path": "模块.py", "observed": True},
            )
        ],
    )
    receiver = ReceiverContract(
        goal="Fix the long issue " + "observed detail " * 150,
        preferred=("evidence",),
        max_tokens=1000,
    )
    result, request = compile_selected(source, receiver, [selected("m0.0")])
    empty = result.packet.model_copy(update={"evidence": []})
    fixed = ApproxTokenCounter().count_text(empty.to_receiver_text())
    assert request.fixed_packet_tokens == fixed
    assert request.source_budget_tokens == receiver.max_tokens - fixed
    assert request.source_budget_tokens < receiver.max_tokens // 2
    unit = request.units[0]
    assert unit.estimated_insertion_tokens >= result.packet_tokens - fixed
    assert unit.estimated_insertion_tokens > unit.estimated_tokens
    for text in (request.to_selector_text(), _selector_payload(request)[0]):
        payload = json.loads(text)
        assert payload["fixed_packet_tokens"] == fixed
        assert payload["source_budget_tokens"] == receiver.max_tokens - fixed
        assert (
            payload["units"][0]["estimated_insertion_tokens"]
            == unit.estimated_insertion_tokens
        )


@pytest.mark.parametrize("counter_name", ["approx", "tiktoken"])
@pytest.mark.parametrize(
    "section", ["evidence", "completed_work", "tool_results", "artifacts"]
)
def test_isolated_estimate_includes_canonical_metadata_and_observed_context(
    counter_name, section
):
    if counter_name == "tiktoken":
        pytest.importorskip("tiktoken")
        counter = TiktokenCounter()
    else:
        counter = ApproxTokenCounter()
    original = (
        "Executed read src/scoring.py:\nFile: src/scoring.py (500 lines)\n"
        + "".join(
            f"{number}: "
            + (
                "def score(values):\n"
                if number == 100
                else "    values.append('observed')\n"
            )
            for number in range(100, 190)
        )
    )
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                role="tool",
                content=original,
                tags={"observed", "constraints"},
                metadata={
                    "path": "src/scoring.py",
                    "detail": {"label": '引用 "quoted"\nnext'},
                    "handoff_sieve.source_ids": ["forged"],
                },
            )
        ],
        artifacts=[
            Artifact(
                name="result.json",
                content={"answer": [1, "原文"]},
                media_type="application/json",
                metadata={"path": "result.json"},
            )
        ],
    )
    receiver = ReceiverContract(
        goal="Review observed implementation " * 40,
        preferred=("evidence", "completed_work", "tool_results", "artifacts"),
        max_tokens=10000,
    )
    pipeline = HandoffPipeline(token_counter=counter)
    catalog = source_units(source, pipeline)
    chosen = (
        catalog[-1]
        if section == "artifacts"
        else next(unit for unit in catalog if "189:" in unit.content)
    )
    result, request = compile_selected(
        source, receiver, [selected(chosen.source_id, section)], pipeline=pipeline
    )
    estimate = next(
        unit.estimated_insertion_tokens
        for unit in request.units
        if unit.source_id == chosen.source_id
    )
    assert estimate >= result.packet_tokens - request.fixed_packet_tokens
    assert "forged" not in result.packet.to_receiver_text()
    if section != "artifacts":
        assert "File: src/scoring.py" in result.packet.to_receiver_text()
        assert "100: def score(values):" in result.packet.to_receiver_text()
        assert result.selection.context_source_ids


def test_estimate_accounts_for_blank_text_retained_when_spans_merge():
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content="First observation.\n"
                + " \t\n" * 2000
                + "Second observation.\n"
            )
        ],
    )
    receiver = ReceiverContract(
        goal="Review", preferred=("evidence",), max_tokens=10000
    )
    result, request = compile_selected(
        source, receiver, [selected("m0.0"), selected("m0.1")]
    )
    costs = [unit.estimated_insertion_tokens for unit in request.units]
    assert request.fixed_packet_tokens + sum(costs) >= result.packet_tokens
    assert costs[1] > request.units[1].estimated_tokens + 2000
    assert result.packet.evidence[0].content == source.messages[0].content


def test_one_insertion_estimate_counts_a_shared_context_ancestor_once():
    original = "File: scoring.py (500 lines)\n" + "".join(
        f"{number}: "
        + ("def score(values):\n" if number == 100 else "    values.append(1)\n")
        for number in range(100, 190)
    )
    source = HandoffEnvelope(
        sender="a", receiver="b", messages=[Message(role="tool", content=original)]
    )
    receiver = ReceiverContract(
        goal="Review", preferred=("evidence",), max_tokens=10000
    )
    pipeline = HandoffPipeline()
    catalog = source_units(source, pipeline)
    request = _budgeted_request(source, catalog, receiver, pipeline)
    flat_request = _budgeted_request(
        source,
        [unit.model_copy(update={"context_source_ids": []}) for unit in catalog],
        receiver,
        pipeline,
    )
    own_costs = {
        unit.source_id: unit.estimated_insertion_tokens for unit in flat_request.units
    }
    # The header is reached directly and via the observed function window.
    assert request.units[-1].context_source_ids == ["m0.0", "m0.1"]
    assert request.units[1].context_source_ids == ["m0.0"]
    assert request.units[-1].estimated_insertion_tokens == sum(
        own_costs[source_id] for source_id in ("m0.0", "m0.1", "m0.3")
    )


def test_artifact_only_contract_keeps_schema_and_packet_categories_unchanged():
    source = HandoffEnvelope(
        sender="a",
        receiver="b",
        messages=[Message(content="Unneeded conversation")],
        artifacts=[Artifact(name="result.json", content={"status": "ready"})],
    )
    receiver = ReceiverContract(
        goal="Inspect", required=("artifacts",), max_tokens=1000
    )
    result, request = compile_selected(source, receiver, [selected("a0", "artifacts")])
    wire, schema = _selector_payload(request)
    assert schema["$defs"]["_IndexedSelection"]["properties"]["section"]["enum"] == [
        "artifacts"
    ]
    assert all(unit.estimated_insertion_tokens is not None for unit in request.units)
    assert json.loads(wire)["contract"]["required"] == ["artifacts"]
    assert len(result.packet.artifacts) == 1
    assert result.packet.evidence == []
    assert result.selection.selected_source_ids == ["a0"]


def test_preparation_does_not_recount_large_goal_for_each_catalog_unit():
    class ObservedCounter(ApproxTokenCounter):
        def __init__(self):
            self.texts = []

        def count_text(self, text):
            self.texts.append(text)
            return super().count_text(text)

    goal = "Unique goal marker " + "long description " * 1000
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="".join(f"Observation {index}.\n" for index in range(300))),
        ],
    )
    receiver = ReceiverContract(goal=goal, preferred=("evidence",), max_tokens=10000)
    counter = ObservedCounter()
    pipeline = HandoffPipeline(token_counter=counter)
    catalog = source_units(source, pipeline)
    request = _budgeted_request(source, catalog, receiver, pipeline)
    assert len(request.units) == 300
    assert sum("Unique goal marker" in text for text in counter.texts) == 1


def test_goal_that_already_exceeds_budget_does_not_spend_a_selector_call():
    source = HandoffEnvelope(
        sender="a", receiver="b", messages=[Message(content="Observed")]
    )
    receiver = ReceiverContract(
        goal="long issue " * 1000, preferred=("evidence",), max_tokens=100
    )
    selector = Selector([selected("m0.0")])
    with pytest.raises(BudgetExceededError, match="empty canonical packet"):
        asyncio.run(compile_model_handoff(source, receiver, selector=selector))
    assert selector.requests == []


def test_ignored_budget_estimates_fail_once_without_dropping_essential_state():
    source = HandoffEnvelope(
        sender="a", receiver="b", messages=[Message(content="Observed detail " * 1000)]
    )
    before = source.model_dump()
    receiver = ReceiverContract(goal="Fix", preferred=("evidence",), max_tokens=300)
    selector = Selector([selected("m0.0")])
    with pytest.raises(BudgetExceededError, match="No essential evidence was removed"):
        asyncio.run(compile_model_handoff(source, receiver, selector=selector))
    assert len(selector.requests) == 1
    assert (
        selector.requests[0].units[0].estimated_insertion_tokens
        > selector.requests[0].source_budget_tokens
    )
    assert source.model_dump() == before


def test_manually_constructed_selector_requests_keep_optional_budget_defaults():
    source = HandoffEnvelope(
        sender="a", receiver="b", messages=[Message(content="Observed")]
    )
    receiver = ReceiverContract(goal="Review", preferred=("evidence",), max_tokens=1000)
    request = SelectionRequest(
        receiver="b", contract=receiver, units=source_units(source, HandoffPipeline())
    )
    assert request.fixed_packet_tokens is None
    assert request.source_budget_tokens is None
    assert request.units[0].estimated_insertion_tokens is None
    for text in (request.to_selector_text(), _selector_payload(request)[0]):
        payload = json.loads(text)
        assert "fixed_packet_tokens" not in payload
        assert "source_budget_tokens" not in payload
        assert "estimated_insertion_tokens" not in payload["units"][0]
