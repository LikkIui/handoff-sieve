from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from handoff_sieve import (
    BudgetExceededError,
    HandoffEnvelope,
    HandoffPipeline,
    HandoffSieveError,
    Message,
    PolicyExecutionError,
    RedactionError,
)
from handoff_sieve.exceptions import ConfigurationError
from handoff_sieve.models import Artifact
from handoff_sieve.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    MockSummarizer,
    Policy,
    PreservePolicy,
    RedactPolicy,
    SchemaPolicy,
    SelectPolicy,
    SummarizePolicy,
    Summary,
)
from handoff_sieve.policies.base import PolicyContext


def test_redact_nested_content_without_logging_secret() -> None:
    secret = "sk-abcdefgh1234"
    result = HandoffPipeline([RedactPolicy()]).process(
        sender="a",
        receiver="b",
        messages=[
            Message(
                content={"owner": "alice@example.com", "credentials": [secret]},
                kind="structured",
            )
        ],
    )

    assert result.messages[0].content == {
        "owner": "[REDACTED:email]",
        "credentials": ["[REDACTED:api_key]"],
    }
    assert result.report.redactions == 2
    assert secret not in result.report.model_dump_json()


def test_custom_redaction_pattern() -> None:
    result = HandoffPipeline(
        [RedactPolicy(detectors=[], custom_patterns={"ticket": r"CASE-\d+"})]
    ).process(sender="a", receiver="b", messages=["Track CASE-1234"])

    assert result.messages[0].content == "Track [REDACTED:ticket]"


def test_redaction_rejects_invalid_custom_regex() -> None:
    with pytest.raises(ConfigurationError, match="Invalid redaction pattern"):
        RedactPolicy(detectors=[], custom_patterns={"broken": "("})


def test_redaction_denies_input_above_scan_limit_with_a_report() -> None:
    pipeline = HandoffPipeline([RedactPolicy(detectors=["email"], max_scan_bytes=20)])

    with pytest.raises(RedactionError, match="max_scan_bytes") as captured:
        pipeline.process(
            sender="a",
            receiver="b",
            messages=["x" * 30],
        )

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "redaction"
    assert captured.value.report.failed_policy == "redact"


def test_redaction_times_out_pathological_custom_regex() -> None:
    pipeline = HandoffPipeline(
        [
            RedactPolicy(
                detectors=[],
                custom_patterns={"pathological": r"(a+)+$"},
                timeout_ms=1,
            )
        ]
    )

    with pytest.raises(RedactionError, match="timeout"):
        pipeline.process(
            sender="a",
            receiver="b",
            messages=["a" * 100_000 + "!"],
        )


def test_exact_dedup_keeps_order() -> None:
    result = HandoffPipeline([ExactDedupPolicy()]).process(
        sender="a",
        receiver="b",
        messages=["first", "second", "first"],
    )

    assert [message.content for message in result.messages] == ["first", "second"]
    assert result.report.duplicates_removed == 1


def test_dedup_keeps_distinct_messages_that_redact_to_the_same_text() -> None:
    result = HandoffPipeline(
        [RedactPolicy(detectors=["email"]), ExactDedupPolicy()]
    ).process(
        sender="a",
        receiver="b",
        messages=["owner alice@example.com", "owner bob@example.com"],
    )

    assert [message.content for message in result.messages] == [
        "owner [REDACTED:email]",
        "owner [REDACTED:email]",
    ]
    assert result.report.duplicates_removed == 0


def test_dedup_still_removes_identical_messages_after_redaction() -> None:
    result = HandoffPipeline(
        [RedactPolicy(detectors=["email"]), ExactDedupPolicy()]
    ).process(
        sender="a",
        receiver="b",
        messages=["owner alice@example.com", "owner alice@example.com"],
    )

    assert len(result.messages) == 1
    assert result.report.duplicates_removed == 1
    assert "handoff_sieve.source_fingerprint" not in result.messages[0].internal


def test_redaction_without_dedup_does_not_retain_source_fingerprint() -> None:
    result = HandoffPipeline([RedactPolicy(detectors=["email"])]).process(
        sender="a",
        receiver="b",
        messages=["owner alice@example.com"],
    )

    assert result.messages[0].content == "owner [REDACTED:email]"
    assert "handoff_sieve.source_fingerprint" not in result.messages[0].internal


def test_exact_dedup_never_removes_protected_occurrences() -> None:
    protected = Message(content="repeat")
    protected._mark_protected()
    result = HandoffPipeline([ExactDedupPolicy()])._process_trusted_envelope(
        HandoffEnvelope(
            sender="a",
            receiver="b",
            messages=[protected, protected],
        )
    )

    assert len(result.messages) == 2
    assert result.report.duplicates_removed == 0


def test_preserve_marks_tagged_and_structured_messages() -> None:
    result = HandoffPipeline([PreservePolicy()]).process(
        sender="a",
        receiver="b",
        messages=[
            Message(content="must cite", tags={"constraint"}),
            Message(content={"citations": ["source"]}, kind="structured"),
            Message(content="ordinary"),
        ],
    )

    assert [message.protected for message in result.messages] == [True, True, False]
    assert result.report.protected_messages == 2


def test_select_retains_protected_messages() -> None:
    result = HandoffPipeline(
        [PreservePolicy(), SelectPolicy(roles={"assistant"})]
    ).process(
        sender="a",
        receiver="b",
        messages=[
            Message(role="user", content="required", tags={"constraint"}),
            Message(role="user", content="drop me"),
            Message(role="assistant", content="keep me"),
        ],
    )

    assert [message.content for message in result.messages] == ["required", "keep me"]


def test_budget_drops_oldest_unprotected_messages() -> None:
    result = HandoffPipeline(
        [PreservePolicy(), BudgetPolicy(70, strategy="drop_oldest")]
    ).process(
        sender="a",
        receiver="b",
        messages=[
            "old " * 30,
            Message(content="critical", tags={"constraint"}),
            "new",
        ],
    )

    assert [message.content for message in result.messages] == ["critical", "new"]
    assert result.messages[0].protected is True


def test_redact_covers_the_complete_receiver_visible_envelope() -> None:
    secret = "alice@example.com"
    envelope = HandoffEnvelope(
        sender=secret,
        receiver=secret,
        messages=[
            Message(
                role=secret,
                kind=secret,
                tags={secret},
                content={secret: secret},
                metadata={secret: secret},
            )
        ],
        artifacts=[
            Artifact(
                name=secret,
                media_type=secret,
                content={secret: secret},
                metadata={secret: secret},
            )
        ],
        metadata={secret: secret},
    )

    result = HandoffPipeline([RedactPolicy(detectors=["email"])]).process_envelope(
        envelope
    )

    assert secret not in result.envelope.model_dump_json()
    assert secret not in result.report.model_dump_json()
    assert result.report.redactions == 17


def test_budget_counts_envelope_metadata_even_without_messages() -> None:
    pipeline = HandoffPipeline([BudgetPolicy(40, strategy="drop_oldest")])

    with pytest.raises(BudgetExceededError, match="Nothing protected was removed"):
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[],
            metadata={"unbounded": "x" * 200},
        )


def test_budget_raises_instead_of_dropping_protected_content() -> None:
    pipeline = HandoffPipeline(
        [PreservePolicy(), BudgetPolicy(5, strategy="drop_oldest")]
    )

    with pytest.raises(
        BudgetExceededError, match="Nothing protected was removed"
    ) as captured:
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[Message(content="critical " * 20, tags={"constraint"})],
        )

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "budget_exceeded"
    assert captured.value.report.failed_policy == "budget"


def test_budget_error_strategy_never_trims() -> None:
    pipeline = HandoffPipeline([BudgetPolicy(5, strategy="error")])

    with pytest.raises(BudgetExceededError, match="exceeding"):
        pipeline.process(sender="a", receiver="b", messages=["large " * 20])


class ResearchPacket(BaseModel):
    conclusions: list[str]
    citations: list[str]


def test_schema_policy_validates_and_normalizes() -> None:
    result = HandoffPipeline([SchemaPolicy(ResearchPacket)]).process(
        sender="a",
        receiver="b",
        messages=[
            Message(
                content={"conclusions": ["done"], "citations": ["https://example.com"]},
                kind="structured",
            )
        ],
    )

    assert result.messages[0].content == {
        "conclusions": ["done"],
        "citations": ["https://example.com"],
    }
    event = result.report.events[-1]
    assert event.details == {
        "normalized_messages": 0,
        "changed_fields": 0,
        "removed_fields": 0,
    }


def test_schema_policy_audits_fields_removed_by_normalization() -> None:
    result = HandoffPipeline([SchemaPolicy(ResearchPacket)]).process(
        sender="a",
        receiver="b",
        messages=[
            Message(
                content={
                    "conclusions": ["done"],
                    "citations": ["https://example.com"],
                    "unapproved": "removed",
                },
                kind="structured",
            )
        ],
    )

    assert "unapproved" not in result.messages[0].content
    event = result.report.events[-1]
    assert event.details["normalized_messages"] == 1
    assert event.details["changed_fields"] == 1
    assert event.details["removed_fields"] == 1


def test_schema_policy_rejects_missing_fields() -> None:
    pipeline = HandoffPipeline(
        [SchemaPolicy(required_fields=["conclusions", "citations"])]
    )

    with pytest.raises(PolicyExecutionError) as captured:
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[Message(content={"conclusions": []}, kind="structured")],
        )

    assert isinstance(captured.value.__cause__, ValidationError)
    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "validation"
    assert captured.value.report.failed_policy == "schema"


def test_mock_summarizer_keeps_protected_messages_and_tracks_cost() -> None:
    result = HandoffPipeline(
        [
            PreservePolicy(),
            SummarizePolicy(MockSummarizer("short summary"), max_tokens=20),
        ]
    ).process(
        sender="researcher",
        receiver="writer",
        messages=[
            "long research note " * 20,
            Message(content="Always cite sources", tags={"constraint"}),
        ],
    )

    assert [message.content for message in result.messages] == [
        "short summary",
        "Always cite sources",
    ]
    assert result.report.summarizer_input_tokens > 0
    assert result.report.summarizer_output_tokens > 0


def test_egress_redaction_removes_secret_reintroduced_by_summarizer() -> None:
    secret = "summary-owner@example.com"
    result = HandoffPipeline(
        [
            RedactPolicy(detectors=["email"]),
            SummarizePolicy(
                MockSummarizer(f"Generated contact: {secret}"),
                max_tokens=30,
            ),
            RedactPolicy(detectors=["email"], stage="egress"),
            BudgetPolicy(100, strategy="error"),
        ]
    ).process(sender="a", receiver="b", messages=["safe source"])

    assert secret not in result.envelope.model_dump_json()
    assert result.messages[0].content == "Generated contact: [REDACTED:email]"
    redact_events = [
        event for event in result.report.events if event.policy == "redact"
    ]
    assert [event.details["stage"] for event in redact_events] == ["input", "egress"]
    assert [event.count for event in redact_events] == [0, 1]
    assert result.report.redactions == 1


def test_input_redaction_after_summarization_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="Unsafe policy order"):
        HandoffPipeline(
            [
                SummarizePolicy(MockSummarizer("summary"), max_tokens=20),
                RedactPolicy(detectors=["email"]),
            ]
        )


def test_egress_redaction_after_budget_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="Unsafe policy order"):
        HandoffPipeline(
            [
                BudgetPolicy(100),
                RedactPolicy(detectors=["email"], stage="egress"),
            ]
        )


class LateSecretPolicy(Policy):
    name = "late_secret"

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        output.messages.append(Message(content="late-owner@example.com"))
        return output


def test_custom_policy_must_run_before_egress_redaction() -> None:
    result = HandoffPipeline(
        [
            LateSecretPolicy(),
            RedactPolicy(detectors=["email"], stage="egress"),
            BudgetPolicy(100),
        ]
    ).process(sender="a", receiver="b", messages=["safe"])

    assert "late-owner@example.com" not in result.envelope.model_dump_json()

    with pytest.raises(ConfigurationError, match="after egress redaction"):
        HandoffPipeline(
            [
                RedactPolicy(detectors=["email"], stage="egress"),
                LateSecretPolicy(),
                BudgetPolicy(100),
            ]
        )


def test_no_policy_can_run_after_hard_budget() -> None:
    with pytest.raises(ConfigurationError, match="after the hard budget"):
        HandoffPipeline([BudgetPolicy(100), LateSecretPolicy()])


class OversizedSummarizer:
    def summarize(self, messages, *, max_tokens, token_counter) -> Summary:
        return Summary(text="too large " * 100)


class AsyncSummarizer:
    async def summarize(self, messages, *, max_tokens, token_counter) -> Summary:
        return Summary(text="async summary")


def test_summarize_rejects_backend_that_breaks_limit() -> None:
    pipeline = HandoffPipeline([SummarizePolicy(OversizedSummarizer(), max_tokens=5)])

    with pytest.raises(HandoffSieveError, match="exceeding its limit"):
        pipeline.process(sender="a", receiver="b", messages=["input"])


def test_summarize_rejects_async_backend_with_clear_boundary() -> None:
    pipeline = HandoffPipeline([SummarizePolicy(AsyncSummarizer(), max_tokens=20)])

    with pytest.raises(HandoffSieveError, match="Async summarizers") as captured:
        pipeline.process(sender="a", receiver="b", messages=["input"])

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failed_policy == "summarize"
