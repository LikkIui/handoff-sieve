from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from relayguard import BudgetExceededError, HandoffPipeline, Message, RelayGuardError
from relayguard.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    PreservePolicy,
    RedactPolicy,
    SchemaPolicy,
    SelectPolicy,
    MockSummarizer,
    SummarizePolicy,
    Summary,
)


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


def test_exact_dedup_keeps_order() -> None:
    result = HandoffPipeline([ExactDedupPolicy()]).process(
        sender="a",
        receiver="b",
        messages=["first", "second", "first"],
    )

    assert [message.content for message in result.messages] == ["first", "second"]
    assert result.report.duplicates_removed == 1


def test_exact_dedup_never_removes_protected_occurrences() -> None:
    protected = Message(content="repeat", protected=True)
    result = HandoffPipeline([ExactDedupPolicy()]).process(
        sender="a",
        receiver="b",
        messages=[protected, protected],
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
        [PreservePolicy(), BudgetPolicy(25, strategy="drop_oldest")]
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


def test_budget_raises_instead_of_dropping_protected_content() -> None:
    pipeline = HandoffPipeline(
        [PreservePolicy(), BudgetPolicy(5, strategy="drop_oldest")]
    )

    with pytest.raises(BudgetExceededError, match="Nothing protected was removed"):
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[Message(content="critical " * 20, tags={"constraint"})],
        )


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


def test_schema_policy_rejects_missing_fields() -> None:
    pipeline = HandoffPipeline(
        [SchemaPolicy(required_fields=["conclusions", "citations"])]
    )

    with pytest.raises(ValidationError):
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[Message(content={"conclusions": []}, kind="structured")],
        )


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


class OversizedSummarizer:
    def summarize(self, messages, *, max_tokens, token_counter) -> Summary:
        return Summary(text="too large " * 100)


def test_summarize_rejects_backend_that_breaks_limit() -> None:
    pipeline = HandoffPipeline(
        [SummarizePolicy(OversizedSummarizer(), max_tokens=5)]
    )

    with pytest.raises(RelayGuardError, match="exceeding its limit"):
        pipeline.process(sender="a", receiver="b", messages=["input"])

