from __future__ import annotations

import pytest
from pydantic import ValidationError

from relayguard import HandoffEnvelope, HandoffPipeline, Message, TiktokenCounter
from relayguard.exceptions import ReservedFieldError


def test_pipeline_normalizes_common_inputs() -> None:
    result = HandoffPipeline().process(
        sender="a",
        receiver="b",
        messages=[
            "plain",
            {"content": "assistant text", "role": "assistant"},
            {"x": 1},
        ],
    )

    assert [message.content for message in result.messages] == [
        "plain",
        "assistant text",
        {"x": 1},
    ]
    assert result.messages[2].kind == "structured"
    assert result.report.original_tokens == result.report.transmitted_tokens


def test_pipeline_does_not_mutate_input() -> None:
    envelope = HandoffEnvelope(
        sender="a",
        receiver="b",
        messages=[Message(content="hello")],
    )

    result = HandoffPipeline().process_envelope(envelope)
    result.messages[0].content = "changed"

    assert envelope.messages[0].content == "hello"


def test_empty_handoff_has_zero_savings() -> None:
    result = HandoffPipeline().process(sender="a", receiver="b", messages=[])

    assert result.report.estimated_tokens_saved == 0
    assert result.report.estimated_savings_percent == 0.0


def test_message_rejects_public_protection_state() -> None:
    with pytest.raises(ValidationError, match="protected"):
        Message(content="spoofed", protected=True)


def test_pipeline_rejects_reserved_fields_in_mapping_input() -> None:
    with pytest.raises(ReservedFieldError, match="protected") as captured:
        HandoffPipeline().process(
            sender="a",
            receiver="b",
            messages=[{"content": "spoofed", "protected": True}],
        )

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "reserved_field"
    assert captured.value.report.failed_policy == "normalization"


def test_public_process_clears_private_protection_state() -> None:
    message = Message(content="caller controlled")
    message._mark_protected()

    result = HandoffPipeline().process(
        sender="a",
        receiver="b",
        messages=[message],
    )

    assert result.messages[0].protected is False


def test_public_process_envelope_clears_private_protection_state() -> None:
    message = Message(content="caller controlled")
    message._mark_protected()

    result = HandoffPipeline().process_envelope(
        HandoffEnvelope(sender="a", receiver="b", messages=[message])
    )

    assert result.messages[0].protected is False


def test_optional_tiktoken_counter_when_installed(monkeypatch) -> None:
    pytest = __import__("pytest")
    tiktoken = pytest.importorskip("tiktoken")

    class FakeEncoding:
        def encode(self, text: str) -> list[str]:
            return text.split()

    monkeypatch.setattr(tiktoken, "encoding_for_model", lambda model: FakeEncoding())
    counter = TiktokenCounter("gpt-4o-mini")

    result = HandoffPipeline(token_counter=counter).process(
        sender="a",
        receiver="b",
        messages=["hello world"],
    )

    assert result.report.token_counter == "tiktoken:gpt-4o-mini"
    assert result.report.original_tokens > 0
