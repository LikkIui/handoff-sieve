"""Compile noisy research into a reviewer-ready handoff packet."""

from handoff_sieve import (
    Artifact,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_handoff,
)


def item(section: str, content: str) -> Message:
    """Create one explicitly classified handoff item."""

    return Message(kind=section, content=content)


def main() -> None:
    search_noise = (
        "Raw search result about unrelated databases and hosting vendors. " * 170
    )
    transcript_noise = (
        "Interview transcript covering roadmap ideas outside this review. " * 110
    )

    sender_state = HandoffEnvelope(
        sender="researcher",
        receiver="reviewer",
        messages=[
            Message(kind="raw_search", content=search_noise),
            Message(kind="interview_notes", content=transcript_noise),
            item(
                "constraints",
                "Approve only if existing pagination cursors remain valid.",
            ),
            item(
                "decisions",
                "Recommend the indexed created_at plus id cursor design.",
            ),
            item(
                "evidence",
                "The new query returned the same ordered rows across 50 fixtures.",
            ),
            item(
                "failed_attempts",
                "A created_at-only cursor skipped rows sharing the same timestamp.",
            ),
            item(
                "pending_work",
                "Verify backward cursor compatibility and decide whether to approve.",
            ),
            item(
                "tool_results",
                "Pagination comparison: 50 of 50 fixtures matched the baseline.",
            ),
        ],
        artifacts=[
            Artifact(
                name="pagination-review-notes",
                content={
                    "query": "ORDER BY created_at, id",
                    "risk": "Legacy cursors encode created_at only.",
                },
                media_type="application/json",
            )
        ],
    )
    contract = ReceiverContract(
        goal="Review the proposed pagination cursor change for merge readiness.",
        required=("constraints", "evidence", "pending_work", "artifacts"),
        preferred=("decisions", "failed_attempts", "tool_results"),
        max_tokens=650,
    )

    result = compile_handoff(sender_state, contract)
    packet = result.packet

    assert result.source_tokens > result.packet_tokens
    assert result.packet_tokens <= contract.max_tokens
    assert result.omitted_count == 2
    assert packet.constraints and packet.evidence and packet.pending_work
    assert packet.artifacts

    print("Researcher -> Reviewer")
    print(f"Before: {result.source_tokens:,} estimated tokens")
    print(f"After HandoffSieve: {result.packet_tokens:,} estimated tokens")
    print(f"Context reduction: {result.estimated_savings_percent:.1f}%")
    print("\nHandoffPacket")
    print(f"  Goal: {packet.goal}")
    print(f"  Constraint: {packet.constraints[0].content}")
    print(f"  Evidence: {packet.evidence[0].content}")
    print(f"  Failed attempt: {packet.failed_attempts[0].content}")
    print(f"  Pending work: {packet.pending_work[0].content}")
    print(f"  Artifact: {packet.artifacts[0].name}")
    print(
        "\nResult: the reviewer gets the evidence and open decision, "
        "not the raw research."
    )


if __name__ == "__main__":
    main()
