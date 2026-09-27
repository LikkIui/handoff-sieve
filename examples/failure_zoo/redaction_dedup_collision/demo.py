"""Failure: distinct events converge to the same text after redaction."""

from relayguard import HandoffPipeline
from relayguard.policies import ExactDedupPolicy, RedactPolicy


def main() -> None:
    pipeline = HandoffPipeline([RedactPolicy(detectors=["email"]), ExactDedupPolicy()])
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["owner alice@example.com", "owner bob@example.com"],
    )

    assert len(result.messages) == 2
    assert all(
        message.content == "owner [REDACTED:email]" for message in result.messages
    )
    assert result.report.redactions == 2
    assert result.report.duplicates_removed == 0
    print("Result: distinct pre-redaction events remained distinct")


if __name__ == "__main__":
    main()
