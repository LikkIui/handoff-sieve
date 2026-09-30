"""Failure: sensitive text hides outside the ordinary message body."""

from handoff_sieve import HandoffEnvelope, HandoffPipeline, Message
from handoff_sieve.models import Artifact
from handoff_sieve.policies import RedactPolicy


def main() -> None:
    secret = "surface-owner@example.test"
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
    assert result.report.status == "passed"
    print("Result: all 17 receiver-visible secret surfaces were redacted")


if __name__ == "__main__":
    main()
