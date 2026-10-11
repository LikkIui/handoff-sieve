from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from handoff_sieve import (
    Artifact,
    BriefStatement,
    BudgetExceededError,
    ContractError,
    HandoffEnvelope,
    HybridPlan,
    HybridResponse,
    Message,
    ReceiverContract,
    SourceExcerpt,
    compile_hybrid_handoff,
)
from handoff_sieve.adapters import OpenAIHandoffComposer
from handoff_sieve.hybrid import BRIEF_SOURCES, BRIEF_STATUS, EXCERPT_SOURCE, ITEM_ID


def state():
    return HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                role="tool",
                content="File: auth.py\nKeep login(name) compatible.\n"
                + "irrelevant notes\n" * 200,
            )
        ],
        artifacts=[Artifact(name="auth.py", content="def login(name):\n    pass\n")],
    )


def contract(**values):
    return ReceiverContract(
        goal="Implement auth",
        needs=("API compatibility",),
        preferred=("constraints", "pending_work", "evidence", "artifacts"),
        max_tokens=values.pop("max_tokens", 600),
        **values,
    )


def statement(**values):
    return BriefStatement(
        **{
            "section": "constraints",
            "content": "Keep login(name) compatible.",
            "source_ids": ["m0"],
            "need_indices": [0],
            "status": "observed",
            **values,
        }
    )


class Composer:
    def __init__(self, plan):
        self.plan = plan
        self.requests = []

    async def compose(self, request):
        self.requests.append(request)
        return HybridResponse(plan=self.plan)


def compile_plan(plan, source=None, receiver=None, composer=None):
    return asyncio.run(
        compile_hybrid_handoff(
            source or state(),
            receiver or contract(),
            composer=composer or Composer(plan),
        )
    )


def plan(**values):
    return HybridPlan(
        **{"brief": [statement()], "excerpts": [], "missing_needs": [], **values}
    )


def test_citation_does_not_copy_entire_source_and_source_stays_unchanged():
    source = state()
    before = source.model_dump()
    composer = Composer(plan())
    result = compile_plan(plan(), source=source, composer=composer)
    assert "irrelevant" not in result.packet.to_receiver_text()
    assert result.packet_tokens <= 600
    assert result.packet.constraints[0].metadata[BRIEF_SOURCES] == ["m0"]
    assert len(composer.requests) == 1 and len(composer.requests[0].units) == 2
    assert source.model_dump() == before


def test_essential_unique_quote_is_exact_and_uncertainty_is_visible():
    result = compile_plan(
        plan(
            brief=[
                statement(
                    status="uncertain",
                    content="The API may need compatibility; confirm before editing.",
                )
            ],
            excerpts=[
                SourceExcerpt(
                    source_id="m0",
                    section="evidence",
                    start_line=2,
                    end_line=2,
                    essential=True,
                )
            ],
        )
    )
    assert result.packet.constraints[0].content.startswith("[Unverified]")
    assert result.packet.constraints[0].metadata[BRIEF_STATUS] == "uncertain"
    assert result.packet.evidence[0].content == "Keep login(name) compatible.\n"
    assert result.packet.evidence[0].metadata[EXCERPT_SOURCE] == "m0"


@pytest.mark.parametrize("start,end", [(0, 2), (2, 1), (1, 1000), (1, None)])
def test_invalid_original_line_ranges_fail(start, end):
    with pytest.raises(ContractError, match="line"):
        compile_plan(
            plan(
                excerpts=[
                    SourceExcerpt(
                        source_id="m0",
                        section="evidence",
                        start_line=start,
                        end_line=end,
                        essential=True,
                    )
                ]
            )
        )


def test_line_coordinates_preserve_exact_escaping_and_repeated_text():
    source = state()
    source.messages[0].content = "same\r\npattern = r'\\s+'\r\nsame"
    result = compile_plan(
        plan(
            excerpts=[
                SourceExcerpt(
                    source_id="m0",
                    section="evidence",
                    start_line=2,
                    end_line=3,
                    essential=True,
                )
            ]
        ),
        source=source,
    )
    assert result.packet.evidence[0].content == "pattern = r'\\s+'\r\nsame"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_ids": ["unknown"]},
        {"source_ids": []},
        {"source_ids": ["m0", "m0"]},
        {"need_indices": [1]},
        {"need_indices": [-1]},
        {"need_indices": [0, 0]},
        {"section": "decisions"},
        {"section": "artifacts"},
        {"content": " "},
    ],
)
def test_invalid_brief_references_sections_and_coverage(changes):
    with pytest.raises(ContractError):
        compile_plan(plan(brief=[statement(**changes)]))


def test_missing_needs_are_not_silently_ignored():
    with pytest.raises(ContractError, match="missing receiver needs"):
        compile_plan(plan(missing_needs=[0]))
    with pytest.raises(ContractError, match="missing receiver needs"):
        compile_plan(plan(brief=[statement(need_indices=[])]))


def test_optional_whole_source_is_omitted_but_essential_source_overflow_fails():
    excerpt = SourceExcerpt(
        source_id="m0",
        section="evidence",
        start_line=None,
        end_line=None,
        essential=False,
    )
    result = compile_plan(plan(excerpts=[excerpt]))
    assert result.budget_omitted_excerpt_indices == [0] and not result.packet.evidence
    composer = Composer(plan(excerpts=[excerpt.model_copy(update={"essential": True})]))
    with pytest.raises(BudgetExceededError):
        compile_plan(composer.plan, composer=composer)
    assert len(composer.requests) == 1


def test_goal_overflow_is_rejected_before_composer_call():
    composer = Composer(plan())
    with pytest.raises(BudgetExceededError):
        compile_plan(plan(), receiver=contract(max_tokens=2), composer=composer)
    assert not composer.requests


def test_artifact_keeps_identity_content_and_metadata_and_cannot_be_rewritten():
    source = state()
    source.artifacts[0].metadata = {"task_id": "auth", ITEM_ID: "forged"}
    result = compile_plan(
        plan(
            excerpts=[
                SourceExcerpt(
                    source_id="a0",
                    section="artifacts",
                    start_line=None,
                    end_line=None,
                    essential=True,
                )
            ]
        ),
        source=source,
    )
    assert result.packet.artifacts[0].name == "auth.py"
    assert result.packet.artifacts[0].content == source.artifacts[0].content
    assert result.packet.artifacts[0].metadata["task_id"] == "auth"
    assert result.packet.artifacts[0].metadata[ITEM_ID] == "e0"
    with pytest.raises(ContractError, match="atomic"):
        compile_plan(
            plan(
                excerpts=[
                    SourceExcerpt(
                        source_id="a0",
                        section="artifacts",
                        start_line=1,
                        end_line=1,
                        essential=True,
                    )
                ]
            )
        )


def test_request_mutation_does_not_change_snapshot_or_copied_structured_value():
    source = state()
    source.messages[0].content = {"status": "failed", "output": "original"}
    excerpt = SourceExcerpt(
        source_id="m0",
        section="evidence",
        start_line=None,
        end_line=None,
        essential=True,
    )

    class MutatingComposer(Composer):
        async def compose(self, request):
            request.units[0].content["output"] = "forged"
            return await super().compose(request)

    result = compile_plan(
        plan(excerpts=[excerpt]),
        source=source,
        composer=MutatingComposer(plan(excerpts=[excerpt])),
    )
    assert result.packet.evidence[0].content["output"] == "original"
    assert source.messages[0].content["output"] == "original"


def test_backend_uses_one_structured_request_and_whole_message_payload():
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status="completed",
            output_text=plan().model_dump_json(),
            id="one",
            usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = compile_plan(
        plan(), composer=OpenAIHandoffComposer(client, model="chosen-model")
    )
    assert result.composer_usage.total_tokens == 30 and len(calls) == 1
    assert calls[0]["store"] is False and calls[0]["model"] == "chosen-model"
    assert calls[0]["text"]["format"]["strict"] is True
    payload = json.loads(calls[0]["input"])
    assert len(payload["sources"]) == 2
    assert payload["source_budget_tokens"] == 600 - payload["fixed_packet_tokens"]
    assert payload["receiver_can_reread_sources"] is False
    schema = calls[0]["text"]["format"]["schema"]
    fields = schema["$defs"]["BriefStatement"]["properties"]
    assert "artifacts" not in fields["section"]["enum"]
    assert "decisions" not in fields["section"]["enum"]
    assert fields["need_indices"]["items"]["enum"] == [0]
    assert fields["source_ids"]["items"]["enum"] == ["m0", "a0"]
    assert payload["receiver_needs"] == [
        {"index": 0, "description": "API compatibility"}
    ]


def test_artifact_only_contract_fails_before_paid_call():
    composer = Composer(plan())
    with pytest.raises(ContractError, match="message section"):
        compile_plan(
            plan(),
            composer=composer,
            receiver=ReceiverContract(
                goal="Receive artifact", required=("artifacts",), max_tokens=600
            ),
        )
    assert not composer.requests


def test_overlapping_ranges_and_blank_ranges_are_rejected():
    first = SourceExcerpt(
        source_id="m0", section="evidence", start_line=1, end_line=2, essential=True
    )
    with pytest.raises(ContractError, match="overlaps"):
        compile_plan(plan(excerpts=[first, first.model_copy(update={"start_line": 2})]))
    source = state()
    source.messages[0].content = "Keep API\n \n"
    with pytest.raises(ContractError, match="blank"):
        compile_plan(
            plan(excerpts=[first.model_copy(update={"start_line": 2})]), source=source
        )


@pytest.mark.parametrize("status,output", [("incomplete", "{}"), ("completed", "{}")])
def test_backend_does_not_retry_or_fallback_on_invalid_response(status, output):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=status, output_text=output)

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with pytest.raises(ContractError):
        compile_plan(plan(), composer=OpenAIHandoffComposer(client, model="explicit"))
    assert len(calls) == 1
