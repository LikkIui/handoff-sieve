"""Give a coder and reviewer different views of the exact same sender history."""

from handoff_sieve import (
    Artifact,
    HandoffEnvelope,
    HistoryCompilation,
    Message,
    ReceiverContract,
    compile_history,
)


def build_sender_state() -> HandoffEnvelope:
    return HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                content="Unrelated notes about hosting prices and launch copy. " * 240
            ),
            Message(
                content="Constraint: Existing pagination cursors must remain valid."
            ),
            Message(content="Decision: Use the (created_at, id) pair for new cursors."),
            Message(content="Evidence: All 50 ordering fixtures match the baseline."),
            Message(
                content="Failed attempt: A timestamp-only cursor skipped tied rows."
            ),
            Message(
                content="TODO: Implement the cursor change and check compatibility."
            ),
            Message(role="tool", content="Pagination checks: 50/50 passed."),
        ],
        artifacts=[
            Artifact(
                name="cursor-implementation-notes",
                content={
                    "modify": ["src/pagination.py", "tests/test_pagination.py"],
                    "new_cursor": ["created_at", "id"],
                },
                media_type="application/json",
            )
        ],
    )


def build_views(
    sender_state: HandoffEnvelope,
) -> dict[str, HistoryCompilation]:
    contracts = {
        "coder": ReceiverContract(
            goal="Implement the composite pagination cursor.",
            required=("constraints", "decisions", "pending_work", "artifacts"),
            preferred=("failed_attempts",),
            max_tokens=700,
        ),
        "reviewer": ReceiverContract(
            goal="Review cursor compatibility and the supporting evidence.",
            required=("constraints", "evidence", "failed_attempts", "pending_work"),
            preferred=("tool_results",),
            max_tokens=700,
        ),
    }
    return {
        receiver: compile_history(
            sender_state.model_copy(update={"receiver": receiver}, deep=True), contract
        )
        for receiver, contract in contracts.items()
    }


def main() -> None:
    sender_state = build_sender_state()
    original = sender_state.model_dump_json()
    views = build_views(sender_state)
    coder = views["coder"].packet
    reviewer = views["reviewer"].packet

    assert sender_state.model_dump_json() == original
    assert coder.decisions and coder.artifacts and not coder.evidence
    assert reviewer.evidence and reviewer.tool_results
    assert not reviewer.decisions and not reviewer.artifacts
    assert coder.failed_attempts == reviewer.failed_attempts
    for receiver, result in views.items():
        assert result.packet.receiver == receiver
        assert result.packet.constraints and result.packet.pending_work
        assert result.packet_tokens <= 700
        assert "hosting prices" not in result.packet.to_receiver_text()

    print("One sender history. Two receiver-specific views. Zero model calls.")
    print(f"Full history: {views['coder'].source_tokens:,} estimated tokens")
    for receiver, result in views.items():
        packet = result.packet
        print(
            f"\n{receiver.capitalize()} view: {result.packet_tokens} estimated tokens"
        )
        print(f"  Goal: {packet.goal}")
        print(f"  Constraint: {packet.constraints[0].content}")
        if packet.decisions:
            print(f"  Decision: {packet.decisions[0].content}")
        if packet.evidence:
            print(f"  Evidence: {packet.evidence[0].content}")
        print(f"  Failed attempt: {packet.failed_attempts[0].content}")
        print(f"  Pending work: {packet.pending_work[0].content}")
        for artifact in packet.artifacts:
            print(f"  Artifact: {artifact.name}")
        if packet.tool_results:
            print(f"  Tool result: {packet.tool_results[0].content}")
    print(
        "\nResult: distinct receiver views verified; shared critical state preserved."
    )
    print("This offline demo verifies packet selection, not LLM task success.")


if __name__ == "__main__":
    main()
