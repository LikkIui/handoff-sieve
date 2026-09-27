"""Failure: untrusted inputs try to create policy bypass channels."""

from collections.abc import Callable

from relayguard import HandoffPipeline, RelayGuardError
from relayguard.policies import BudgetPolicy


def expect_denial(
    operation: Callable[[], object],
    *,
    code: str,
    canary: str,
) -> None:
    try:
        operation()
    except RelayGuardError as error:
        report = error.report
        assert report is not None
        assert report.status == "denied"
        assert report.failure_code == code
        assert report.transmitted_tokens == 0
        assert report.completed_at is not None
        assert canary not in report.model_dump_json()
    else:
        raise AssertionError(f"expected denied report with code {code}")


def main() -> None:
    expect_denial(
        lambda: HandoffPipeline().process(
            sender="researcher",
            receiver="writer",
            messages=[{"content": "spoof-canary", "protected": True}],
        ),
        code="reserved_field",
        canary="spoof-canary",
    )
    expect_denial(
        lambda: HandoffPipeline().process(
            sender="researcher",
            receiver="writer",
            messages=[{"content": "extra-canary", "unexpected": "channel"}],
        ),
        code="validation",
        canary="extra-canary",
    )
    expect_denial(
        lambda: HandoffPipeline([BudgetPolicy(20, strategy="drop_oldest")]).process(
            sender="researcher",
            receiver="writer",
            messages=[],
            metadata={"payload": "metadata-canary " * 100},
        ),
        code="budget_exceeded",
        canary="metadata-canary",
    )
    print("Result: reserved fields, extra fields, and metadata flooding were denied")


if __name__ == "__main__":
    main()
