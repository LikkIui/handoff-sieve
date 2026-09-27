"""Failure: a summarizer generates a new secret after input redaction."""

from relayguard import HandoffPipeline
from relayguard.policies import MockSummarizer, RedactPolicy, SummarizePolicy


def main() -> None:
    generated_secret = "summary-owner@example.test"
    pipeline = HandoffPipeline(
        [
            RedactPolicy(detectors=["email"]),
            SummarizePolicy(
                MockSummarizer(f"Generated contact: {generated_secret}"),
                max_tokens=30,
            ),
            RedactPolicy(detectors=["email"], stage="egress"),
        ]
    )
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["The source contains no contact details."],
    )

    receiver_view = result.envelope.model_dump_json()
    assert generated_secret not in receiver_view
    assert "[REDACTED:email]" in receiver_view
    assert result.report.redactions == 1
    assert [
        event.details["stage"]
        for event in result.report.events
        if event.policy == "redact"
    ] == ["input", "egress"]
    print("Result: egress redaction removed the summary-generated secret")


if __name__ == "__main__":
    main()
