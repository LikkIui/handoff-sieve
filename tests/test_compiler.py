from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from handoff_sieve import (
    ApproxTokenCounter,
    Artifact,
    BudgetExceededError,
    CallbackReporter,
    ContractError,
    HandoffEnvelope,
    HandoffPacket,
    HandoffPipeline,
    Message,
    ReceiverContract,
    compile_handoff,
)
from handoff_sieve.policies import RedactPolicy, SummarizePolicy, Summary


def test_compile_handoff_builds_explicit_receiver_packet() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="Use Python 3.10", kind="constraints"),
            Message(content="Use signed sessions", tags={"decisions"}),
            Message(content="RFC 7519", tags={"evidence"}),
            Message(content="Schema added", tags={"completed_work"}),
            Message(content="Cookies failed", tags={"failed_attempts"}),
            Message(content="Implement middleware", tags={"pending_work"}),
            Message(content={"exit_code": 0}, kind="tool_results"),
            Message(content="irrelevant conversation"),
        ],
        artifacts=[Artifact(name="auth.py", content="pass")],
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["constraints", "decisions", "pending_work"],
        preferred=[
            "evidence",
            "completed_work",
            "failed_attempts",
            "artifacts",
            "tool_results",
        ],
        max_tokens=2_000,
    )

    result = compile_handoff(source, contract, request_id="takeover-1")

    assert result.packet.goal == "Implement authentication"
    assert result.packet.constraints[0].content == "Use Python 3.10"
    assert result.packet.decisions[0].content == "Use signed sessions"
    assert result.packet.evidence[0].content == "RFC 7519"
    assert result.packet.completed_work[0].content == "Schema added"
    assert result.packet.failed_attempts[0].content == "Cookies failed"
    assert result.packet.pending_work[0].content == "Implement middleware"
    assert result.packet.artifacts[0].name == "auth.py"
    assert result.packet.tool_results[0].content == {"exit_code": 0}
    assert result.omitted_count == 1
    assert result.packet_tokens <= contract.max_tokens
    assert result.report.request_id == "takeover-1"
    assert result.report.status == "passed"
    assert result.report.events[-1].policy == "receiver_contract"
    assert result.budget is not None
    assert result.budget.packet_tokens == result.packet_tokens
    assert result.budget.preferred_selected == {
        section: 1 for section in contract.preferred
    }
    assert not any(result.budget.preferred_omitted_for_budget.values())


def test_receiver_text_is_canonical_and_matches_packet_token_count() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content={"decision": "Use signed sessions", "accepted": True},
                kind="decisions",
                tags={"zeta", "alpha"},
            ),
            Message(content=["pytest", "ruff"], kind="tool_results"),
        ],
        artifacts=[
            Artifact(
                name="auth.py",
                content={"path": "src/auth.py", "changed": True},
            )
        ],
    )
    result = compile_handoff(
        source,
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "artifacts"],
            preferred=["tool_results"],
            max_tokens=2_000,
        ),
    )

    receiver_text = result.packet.to_receiver_text()

    expected = json.loads(receiver_text)
    assert receiver_text == json.dumps(
        expected,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = json.loads(receiver_text)
    assert HandoffPacket.model_validate_json(receiver_text).model_dump() == (
        result.packet.model_dump()
    )
    assert payload["decisions"][0]["tags"] == ["alpha", "zeta"]
    assert payload["decisions"][0]["content"] == {
        "accepted": True,
        "decision": "Use signed sessions",
    }
    assert ApproxTokenCounter().count_text(receiver_text) == result.packet_tokens
    assert "_protected" not in receiver_text
    assert "_internal" not in receiver_text
    assert '"constraints":[]' in receiver_text
    assert "budget" not in payload


def test_required_section_missing_fails_clearly() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="Only evidence", tags={"evidence"})],
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["decisions"],
        max_tokens=1_000,
    )

    with pytest.raises(ContractError, match="decisions") as captured:
        compile_handoff(source, contract)

    diagnostics = captured.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.stage == "sender_state"
    assert diagnostics.missing_sections == ("decisions",)
    assert diagnostics.section_counts["evidence"] == 1
    assert diagnostics.section_counts["decisions"] == 0
    assert diagnostics.unclassified_message_indices == ()
    assert "Message(kind='decisions'" in diagnostics.recovery_hints["decisions"]
    assert "Only evidence" not in diagnostics.model_dump_json()
    assert captured.value.normalization is None


def test_artifact_diagnostic_points_to_artifacts_instead_of_message_labels() -> None:
    with pytest.raises(ContractError) as captured:
        compile_handoff(
            HandoffEnvelope(sender="researcher", receiver="coder"),
            ReceiverContract(goal="Implement", required=("artifacts",), max_tokens=500),
        )
    diagnostics = captured.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.missing_sections == ("artifacts",)
    assert "HandoffEnvelope.artifacts" in diagnostics.recovery_hints["artifacts"]
    assert "Message(kind=" not in diagnostics.recovery_hints["artifacts"]


def test_removed_required_artifact_has_pipeline_diagnostic_and_denied_report() -> None:
    from handoff_sieve.policies.base import Policy, PolicyContext

    class DropArtifacts(Policy):
        name = "drop_artifacts_fixture"

        def apply(
            self, envelope: HandoffEnvelope, context: PolicyContext
        ) -> HandoffEnvelope:
            return envelope.model_copy(update={"artifacts": []}, deep=True)

    with pytest.raises(ContractError) as captured:
        compile_handoff(
            HandoffEnvelope(
                sender="researcher",
                receiver="coder",
                artifacts=[
                    Artifact(name="private-file-name", content="private-content")
                ],
            ),
            ReceiverContract(goal="Implement", required=("artifacts",), max_tokens=500),
            pipeline=HandoffPipeline([DropArtifacts()]),
        )
    error = captured.value
    assert error.report is not None and error.report.status == "denied"
    assert error.diagnostics is not None
    assert error.diagnostics.stage == "pipeline_output"
    assert error.diagnostics.section_counts["artifacts"] == 0
    assert "processing policy" in error.diagnostics.recovery_hints["artifacts"]
    assert error.diagnostics.unclassified_message_indices is None
    assert "private-" not in error.diagnostics.model_dump_json()


def test_required_context_is_never_trimmed_to_meet_budget() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="x" * 2_000, tags={"decisions"})],
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["decisions"],
        max_tokens=100,
    )

    with pytest.raises(
        BudgetExceededError, match="No required content was removed"
    ) as captured:
        compile_handoff(source, contract)
    error = captured.value
    assert error.budget is not None and error.report is None
    assert error.budget.stage == "sender_state"
    assert error.budget.packet_tokens is None
    assert error.budget.required_tokens > contract.max_tokens
    assert error.budget.overflow_tokens == error.budget.required_tokens - 100
    assert error.budget.remaining_tokens == 0
    assert "No packet emitted" in str(error)
    assert "x" * 2_000 not in error.budget.model_dump_json()


def test_preferred_sections_follow_priority_and_fit_remaining_budget() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="must keep", tags={"constraints"}),
            Message(content="x" * 2_000, tags={"evidence"}),
            Message(content="small useful failure", tags={"failed_attempts"}),
        ],
    )
    small_only = compile_handoff(
        source,
        ReceiverContract(
            goal="Implement authentication",
            required=["constraints"],
            preferred=["failed_attempts"],
            max_tokens=10_000,
        ),
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["constraints"],
        preferred=["evidence", "failed_attempts"],
        max_tokens=small_only.packet_tokens,
    )

    result = compile_handoff(source, contract)

    assert result.packet.evidence == []
    assert result.packet.failed_attempts[0].content == "small useful failure"
    assert result.packet_tokens <= contract.max_tokens
    assert result.budget is not None
    assert result.budget.preferred_selected == {"evidence": 0, "failed_attempts": 1}
    assert result.budget.preferred_omitted_before_pipeline["evidence"] == 1
    assert result.budget.preferred_omitted_after_pipeline["evidence"] == 0
    assert result.budget.remaining_tokens == 0


def test_later_small_item_is_kept_when_earlier_item_in_same_section_is_too_big() -> (
    None
):
    small_source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="must keep", tags={"constraints"}),
            Message(content="small useful evidence", tags={"evidence"}),
        ],
    )
    small_only = compile_handoff(
        small_source,
        ReceiverContract(
            goal="Implement authentication",
            required=["constraints"],
            preferred=["evidence"],
            max_tokens=10_000,
        ),
    )
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="must keep", tags={"constraints"}),
            Message(content="x" * 2_000, tags={"evidence"}),
            Message(content="small useful evidence", tags={"evidence"}),
        ],
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["constraints"],
        preferred=["evidence"],
        max_tokens=small_only.packet_tokens,
    )

    result = compile_handoff(source, contract)

    assert [message.content for message in result.packet.evidence] == [
        "small useful evidence"
    ]
    assert result.packet_tokens <= contract.max_tokens
    assert result.budget is not None
    assert result.budget.preferred_selected == {"evidence": 1}
    assert result.budget.preferred_omitted_for_budget == {"evidence": 1}


class ExplodingSummarizer:
    def summarize(self, messages, *, max_tokens, token_counter) -> Summary:
        raise AssertionError("contract compilation must not call a summarizer")


def test_contract_compilation_never_calls_summarizer() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="Keep this", tags={"decisions"})],
    )
    pipeline = HandoffPipeline([SummarizePolicy(ExplodingSummarizer(), max_tokens=100)])

    result = compile_handoff(
        source,
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions"],
            max_tokens=1_000,
        ),
        pipeline=pipeline,
    )

    assert result.packet.decisions[0].content == "Keep this"
    assert any(
        event.policy == "summarize" and event.action == "skipped"
        for event in result.report.events
    )


def test_redaction_expansion_denies_inside_pipeline_before_report_emit() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content=" ".join(["a@b.co"] * 30),
                tags={"evidence"},
            )
        ],
    )
    roomy = ReceiverContract(
        goal="Implement authentication",
        required=["evidence"],
        max_tokens=10_000,
    )
    raw = compile_handoff(source, roomy)
    redacted = compile_handoff(
        source,
        roomy,
        pipeline=HandoffPipeline([RedactPolicy(detectors=["email"])]),
    )
    assert redacted.packet_tokens > raw.packet_tokens

    emitted = []
    strict_pipeline = HandoffPipeline(
        [RedactPolicy(detectors=["email"])],
        reporters=[CallbackReporter(emitted.append)],
    )
    strict = roomy.model_copy(update={"max_tokens": raw.packet_tokens})

    with pytest.raises(BudgetExceededError) as captured:
        compile_handoff(source, strict, pipeline=strict_pipeline)

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failed_policy == "receiver_contract"
    assert captured.value.report.failure_code == "budget_exceeded"
    assert len(emitted) == 1
    assert emitted[0].status == "denied"
    assert captured.value.budget is not None
    assert captured.value.budget.stage == "pipeline_output"
    assert captured.value.budget.required_tokens == redacted.packet_tokens
    assert captured.value.budget.overflow_tokens == (
        redacted.packet_tokens - raw.packet_tokens
    )


def test_pipeline_cleans_goal_without_forwarding_unrequested_source_metadata() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[Message(content="Keep this", tags={"decisions"})],
        metadata={"irrelevant": "x" * 10_000},
    )
    pipeline = HandoffPipeline([RedactPolicy(detectors=["email"])])
    contract = ReceiverContract(
        goal="Send the result to coder@example.com",
        required=["decisions"],
        max_tokens=1_000,
    )

    result = compile_handoff(source, contract, pipeline=pipeline)

    assert result.packet.goal == "Send the result to [REDACTED:email]"
    assert "irrelevant" not in result.packet.to_envelope().metadata
    assert result.packet_tokens <= contract.max_tokens


def test_message_must_map_to_at_most_one_section() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content="ambiguous",
                kind="decisions",
                tags={"evidence"},
            )
        ],
    )
    contract = ReceiverContract(
        goal="Implement authentication",
        required=["decisions"],
        max_tokens=1_000,
    )

    with pytest.raises(ContractError, match="multiple receiver sections"):
        compile_handoff(source, contract)


def test_contract_rejects_duplicate_or_overlapping_sections() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions", "decisions"],
            max_tokens=1_000,
        )
    with pytest.raises(ValidationError, match="both required and preferred"):
        ReceiverContract(
            goal="Implement authentication",
            required=["decisions"],
            preferred=["decisions"],
            max_tokens=1_000,
        )


def test_budget_feedback_tracks_preferred_expansion_after_processing() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="Keep the API.", kind="constraints"),
            Message(content=" ".join(["a@b.co"] * 30), kind="evidence"),
            Message(content="A timestamp alone skipped rows.", kind="failed_attempts"),
        ],
    )
    roomy = ReceiverContract(
        goal="Implement pagination",
        required=("constraints",),
        preferred=("evidence", "failed_attempts"),
        max_tokens=10_000,
    )
    original = source.model_dump_json()
    raw = compile_handoff(source, roomy)
    result = compile_handoff(
        source,
        roomy.model_copy(update={"max_tokens": raw.packet_tokens}),
        pipeline=HandoffPipeline([RedactPolicy(detectors=["email"])]),
    )
    assert result.packet.constraints and result.packet.failed_attempts
    assert not result.packet.evidence
    assert result.budget is not None
    assert result.budget.preferred_omitted_before_pipeline == {
        "evidence": 0,
        "failed_attempts": 0,
    }
    assert result.budget.preferred_omitted_after_pipeline == {
        "evidence": 1,
        "failed_attempts": 0,
    }
    assert "a@b.co" not in result.budget.model_dump_json()
    assert source.model_dump_json() == original


def test_absent_or_policy_removed_preferred_state_is_not_a_budget_omission() -> None:
    from handoff_sieve.policies.base import Policy, PolicyContext

    class DropArtifacts(Policy):
        name = "drop_optional_artifacts_fixture"

        def apply(
            self, envelope: HandoffEnvelope, context: PolicyContext
        ) -> HandoffEnvelope:
            return envelope.model_copy(update={"artifacts": []}, deep=True)

    result = compile_handoff(
        HandoffEnvelope(
            sender="researcher",
            receiver="coder",
            messages=[Message(content="Use cursors.", kind="decisions")],
            artifacts=[Artifact(name="reference.txt", content="optional reference")],
        ),
        ReceiverContract(
            goal="Implement pagination",
            required=("decisions",),
            preferred=("artifacts", "evidence"),
            max_tokens=1_000,
        ),
        pipeline=HandoffPipeline([DropArtifacts()]),
    )
    assert not result.packet.artifacts and not result.packet.evidence
    assert result.budget is not None
    assert result.budget.preferred_selected == {"artifacts": 0, "evidence": 0}
    assert result.budget.preferred_omitted_for_budget == {"artifacts": 0, "evidence": 0}


def test_more_budget_restores_preferred_state_without_changing_required_state() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="Preserve old cursors.", kind="constraints"),
            Message(content="query plan " * 200, kind="evidence"),
            Message(content="Timestamps alone skipped rows.", kind="failed_attempts"),
        ],
        artifacts=[Artifact(name="query-plan.txt", content="plan " * 200)],
    )
    base = ReceiverContract(
        goal="Implement pagination",
        required=("constraints",),
        preferred=("failed_attempts",),
        max_tokens=10_000,
    )
    small = compile_handoff(source, base)
    contract = base.model_copy(
        update={
            "preferred": ("failed_attempts", "evidence", "artifacts"),
            "max_tokens": small.packet_tokens,
        }
    )
    tight = compile_handoff(source, contract)
    roomy = compile_handoff(source, contract.model_copy(update={"max_tokens": 10_000}))
    assert tight.packet.constraints == roomy.packet.constraints
    assert tight.packet.failed_attempts == roomy.packet.failed_attempts
    assert not tight.packet.evidence and not tight.packet.artifacts
    assert roomy.packet.evidence and roomy.packet.artifacts
    assert tight.budget is not None and roomy.budget is not None
    assert tight.budget.required_tokens == roomy.budget.required_tokens
    required_only = compile_handoff(source, base.model_copy(update={"preferred": ()}))
    assert tight.budget.required_tokens == required_only.packet_tokens
    assert tight.budget.preferred_omitted_for_budget == {
        "failed_attempts": 0,
        "evidence": 1,
        "artifacts": 1,
    }
    assert not any(roomy.budget.preferred_omitted_for_budget.values())
