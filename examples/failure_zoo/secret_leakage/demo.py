"""Failure: a handoff forwards credentials and personal data verbatim."""

from relayguard import HandoffPipeline
from relayguard.policies import RedactPolicy


def main() -> None:
    secret = "sk-example123456"
    raw = f"Ask alice@example.com to use {secret}."

    result = HandoffPipeline([RedactPolicy()]).process(
        sender="researcher",
        receiver="writer",
        messages=[raw],
    )
    cleaned = str(result.messages[0].content)

    assert secret in raw
    assert secret not in cleaned
    assert "alice@example.com" not in cleaned
    assert result.report.redactions == 2

    print("Before:", raw)
    print("After: ", cleaned)
    print("Result: secret and email were redacted")


if __name__ == "__main__":
    main()
