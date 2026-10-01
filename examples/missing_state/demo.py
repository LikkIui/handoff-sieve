"""Locate missing receiver state and retry after an explicit caller correction."""

from handoff_sieve import (
    ContractError,
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
            Message(content="Unrelated launch notes."),
            Message(content="Constraint: Existing cursors must remain valid."),
            Message(content="Use (created_at, id) for new cursors."),
            Message(content="Implement the cursor parser and compatibility checks."),
        ],
    )
    original = source.model_dump_json()
    contract = ReceiverContract(
        goal="Implement the composite pagination cursor.",
        required=("constraints", "decisions", "pending_work"),
        max_tokens=700,
    )

    print("First attempt: relevant state exists but two messages have no labels.")
    try:
        compile_history(source, contract)
    except ContractError as error:
        assert error.diagnostics is not None
        assert error.diagnostics.stage == "sender_state"
        assert error.diagnostics.missing_sections == ("decisions", "pending_work")
        assert error.diagnostics.unclassified_message_indices == (0, 2, 3)
        print(error)
    else:
        raise AssertionError("Incomplete state must not produce a receiver packet.")

    # The caller knows what these messages mean; the compiler does not guess.
    corrected = source.model_copy(deep=True)
    corrected.messages[2].kind = "decisions"
    corrected.messages[3].kind = "pending_work"
    result = compile_history(corrected, contract)

    assert source.model_dump_json() == original
    assert result.normalization.unclassified_message_indices == (0,)
    assert result.packet.decisions[0].content == source.messages[2].content
    assert result.packet.pending_work[0].content == source.messages[3].content
    assert "launch notes" not in result.packet.to_receiver_text()
    assert result.packet_tokens <= contract.max_tokens
    print("\nCaller correction: label messages 2 and 3; leave unrelated notes alone.")
    print(f"Compiled receiver packet: {result.packet_tokens} estimated tokens.")
    print(f"Decision: {result.packet.decisions[0].content}")
    print(f"Pending work: {result.packet.pending_work[0].content}")
    print(
        "Result: missing state located; corrected handoff compiled with no model call."
    )


if __name__ == "__main__":
    main()
