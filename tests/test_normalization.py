from __future__ import annotations

import pytest

from handoff_sieve import (
    ApproxTokenCounter,
    Artifact,
    ContractError,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    RuleBasedHistoryNormalizer,
    compile_history,
)


def test_compile_history_builds_packet_from_ordinary_agent_messages() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="A long unrelated conversation about launch copy."),
            Message(content="Constraint: Keep the public API stable."),
            Message(content="决定：Use keyset pagination."),
            Message(content={"completed_work": "Added the cursor schema."}),
            Message(content="TODO: Implement the query path."),
            Message(content="Failed attempt: OFFSET became slow at page 500."),
            Message(
                content="The query plan uses the index.",
                metadata={"handoff_section": "evidence"},
            ),
            Message(role="tool", content={"command": "pytest", "exit_code": 0}),
        ],
        artifacts=[Artifact(name="pagination.py", content="class Cursor: ...")],
    )
    contract = ReceiverContract(
        goal="Implement cursor pagination",
        required=(
            "constraints",
            "decisions",
            "completed_work",
            "pending_work",
            "artifacts",
        ),
        preferred=("failed_attempts", "evidence", "tool_results"),
        max_tokens=2_000,
    )

    result = compile_history(source, contract, request_id="history-1")

    assert result.packet.constraints[0].content == "Keep the public API stable."
    assert result.packet.decisions[0].content == "Use keyset pagination."
    assert result.packet.completed_work[0].content == {
        "completed_work": "Added the cursor schema."
    }
    assert result.packet.pending_work[0].content == "Implement the query path."
    assert result.packet.failed_attempts[0].content == (
        "OFFSET became slow at page 500."
    )
    assert result.packet.evidence[0].content == "The query plan uses the index."
    assert result.packet.tool_results[0].content == {
        "command": "pytest",
        "exit_code": 0,
    }
    assert result.packet.artifacts[0].name == "pagination.py"
    assert result.normalization.total_messages == 8
    assert result.normalization.classified_messages == 7
    assert result.normalization.normalized_messages == 7
    assert result.normalization.unclassified_messages == 1
    assert result.source_tokens == ApproxTokenCounter().count_envelope(source)
    assert result.report.request_id == "history-1"
    assert result.report.events[-1].policy == "history_normalizer"
    assert source.messages[1].kind == "message"
    assert source.messages[1].content.startswith("Constraint:")


def test_explicit_section_wins_over_inferred_text() -> None:
    source = HandoffEnvelope(
        sender="planner",
        receiver="executor",
        messages=[Message(kind="decisions", content="TODO: Keep this as a decision")],
    )

    result = compile_history(
        source,
        ReceiverContract(
            goal="Execute the plan",
            required=("decisions",),
            max_tokens=500,
        ),
    )

    assert result.packet.decisions[0].content == "TODO: Keep this as a decision"
    assert result.packet.pending_work == []
    assert result.normalization.normalized_messages == 0
    assert result.normalization.rule_counts == {"explicit_kind_or_tag": 1}


def test_normalizer_does_not_match_words_in_the_middle_of_prose() -> None:
    normalized = RuleBasedHistoryNormalizer().normalize(
        HandoffEnvelope(
            sender="researcher",
            receiver="reviewer",
            messages=[
                Message(content="We discussed a decision but did not accept one."),
            ],
        )
    )

    assert normalized.envelope.messages[0].kind == "message"
    assert normalized.report.classified_messages == 0
    assert normalized.report.unclassified_messages == 1


def test_conflicting_inference_requires_an_explicit_section() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                role="tool",
                content="Evidence: Query plan uses the index.",
            )
        ],
    )

    with pytest.raises(ContractError, match="conflicting normalization signals"):
        compile_history(
            source,
            ReceiverContract(
                goal="Implement pagination",
                required=("evidence",),
                max_tokens=500,
            ),
        )


def test_missing_required_section_still_fails_closed_after_normalization() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="Unlabelled idea with no accepted status.")],
    )

    with pytest.raises(ContractError, match="decisions"):
        compile_history(
            source,
            ReceiverContract(
                goal="Implement pagination",
                required=("decisions",),
                max_tokens=500,
            ),
        )


def test_multisection_note_preserves_continuations_and_ignores_code_labels() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content=(
                    "Constraint: Keep the public API stable.\n"
                    "Including all keyword argument names.\n"
                    "Decision: Reject invalid hashes first.\n"
                    "```python\nTODO: this is quoted example code\n```\n"
                    "Failed attempt: Checking expiry before reuse hid reuse.\n"
                    "待办：Implement the middleware."
                )
            )
        ],
    )
    before = source.model_dump_json()
    result = compile_history(
        source,
        ReceiverContract(
            goal="Implement authentication",
            required=("constraints", "decisions", "failed_attempts", "pending_work"),
            max_tokens=1_000,
        ),
    )
    assert result.packet.constraints[0].content == (
        "Keep the public API stable.\nIncluding all keyword argument names."
    )
    assert "quoted example code" in result.packet.decisions[0].content
    assert result.packet.pending_work[0].content == "Implement the middleware."
    assert result.packet.failed_attempts[0].content == (
        "Checking expiry before reuse hid reuse."
    )
    assert result.normalization.total_messages == 1
    assert result.normalization.normalized_messages == 1
    assert result.normalization.rule_counts == {"text_prefix_sections": 1}
    assert result.source_tokens == ApproxTokenCounter().count_envelope(source)
    assert source.model_dump_json() == before


@pytest.mark.parametrize(
    "hint",
    [
        {"kind": "evidence"},
        {"tags": {"evidence"}},
    ],
)
def test_multisection_text_keeps_explicit_classification(hint: dict) -> None:
    text = "Decision: quoted choice\nTODO: quoted task"
    result = compile_history(
        HandoffEnvelope(
            sender="researcher",
            receiver="reviewer",
            messages=[Message(content=text, **hint)],
        ),
        ReceiverContract(
            goal="Review evidence", required=("evidence",), max_tokens=500
        ),
    )
    assert result.packet.evidence[0].content == text
    assert not result.packet.decisions and not result.packet.pending_work


def test_multisection_text_does_not_override_conflicting_metadata() -> None:
    with pytest.raises(ContractError, match="conflicting normalization signals"):
        compile_history(
            HandoffEnvelope(
                sender="researcher",
                receiver="reviewer",
                messages=[
                    Message(
                        content="Decision: quoted choice\nTODO: quoted task",
                        metadata={"handoff_section": "evidence"},
                    )
                ],
            ),
            ReceiverContract(goal="Review", required=("evidence",), max_tokens=500),
        )


def test_multisection_split_does_not_discard_unlabelled_preamble() -> None:
    normalized = RuleBasedHistoryNormalizer().normalize(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[Message(content="An unlabelled note.\nDecision: X\nTODO: Y")],
        )
    )
    assert len(normalized.envelope.messages) == 1
    assert normalized.report.unclassified_messages == 1
