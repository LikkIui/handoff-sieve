"""Inspect budget omissions, then restore useful context by changing the contract."""

from handoff_sieve import (
    BudgetExceededError,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_history,
)


def main() -> None:
    source = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content="Unrelated launch discussion. " * 100),
            Message(
                content="Constraint: Existing pagination cursors must remain valid."
            ),
            Message(content="Decision: Use (created_at, id) for new cursors."),
            Message(content="TODO: Implement cursor parsing and compatibility checks."),
            Message(
                content="Failed attempt: Timestamp-only cursors skipped tied rows."
            ),
            Message(
                content="Evidence: "
                + (
                    "Query-plan fixtures confirm ordered index scans "
                    "and cursor compatibility. "
                )
                * 30
            ),
        ],
    )
    original = source.model_dump_json()
    contract = ReceiverContract(
        goal="Implement composite pagination cursors.",
        required=("constraints", "decisions", "pending_work"),
        preferred=("failed_attempts", "evidence"),
        max_tokens=250,
    )
    tight = compile_history(source, contract)
    assert tight.budget is not None
    assert tight.packet.failed_attempts and not tight.packet.evidence
    assert tight.budget.preferred_omitted_for_budget == {
        "failed_attempts": 0,
        "evidence": 1,
    }
    print("Tight receiver contract:")
    print(tight.budget.to_text())

    roomy = compile_history(source, contract.model_copy(update={"max_tokens": 1_000}))
    assert roomy.budget is not None
    assert roomy.packet.evidence
    for section in contract.required:
        assert getattr(tight.packet, section) == getattr(roomy.packet, section)
    assert tight.packet.failed_attempts == roomy.packet.failed_attempts
    assert tight.budget.required_tokens == roomy.budget.required_tokens
    assert not any(roomy.budget.preferred_omitted_for_budget.values())
    print("\nLarger receiver contract restores supporting evidence:")
    print(roomy.budget.to_text())

    try:
        compile_history(source, contract.model_copy(update={"max_tokens": 100}))
    except BudgetExceededError as error:
        assert error.budget is not None
        assert error.budget.overflow_tokens == tight.budget.required_tokens - 100
        assert error.budget.packet_tokens is None
        print("\nA budget below the required state stops compilation:")
        print(error.budget.to_text())
    else:
        raise AssertionError("Required state must never be trimmed to fit.")

    assert source.model_dump_json() == original
    assert "Unrelated launch" not in roomy.packet.to_receiver_text()
    print(
        "\nResult: budget choices explained; critical state preserved; "
        "zero model calls."
    )


if __name__ == "__main__":
    main()
