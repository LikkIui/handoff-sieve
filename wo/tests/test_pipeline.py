from __future__ import annotations

from relayguard import HandoffEnvelope, HandoffPipeline, Message, TiktokenCounter


def test_pipeline_normalizes_common_inputs() -> None:
    result = HandoffPipeline().process(
        sender="a",
        receiver="b",
        messages=["plain", {"content": "assistant text", "role": "assistant"}, {"x": 1}],
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

