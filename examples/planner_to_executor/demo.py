"""Compile a broad project plan into an executor-ready handoff packet."""

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
    planning_noise = (
        "Backlog discussion about later analytics, billing, and mobile work. " * 160
    )
    meeting_noise = (
        "Planning transcript about milestones, ownership, and release themes. " * 120
    )

    sender_state = HandoffEnvelope(
        sender="planner",
        receiver="executor",
        messages=[
            Message(kind="backlog", content=planning_noise),
            Message(kind="meeting_notes", content=meeting_noise),
            item(
                "constraints",
                "Keep GET /reports backward compatible and stream large exports.",
            ),
            item(
                "decisions",
                "Add CSV export behind the existing format query parameter.",
            ),
            item(
                "completed_work",
                "Confirmed the report service already exposes row iterators.",
            ),
            item(
                "pending_work",
                "Implement the CSV serializer and add empty, Unicode, and "
                "large-file tests.",
            ),
            item(
                "evidence",
                "The current JSON path peaks at 180 MB for the largest fixture.",
            ),
            item(
                "tool_results",
                "pytest tests/test_reports.py: 24 passed before implementation.",
            ),
        ],
        artifacts=[
            Artifact(
                name="csv-execution-plan",
                content={
                    "files": [
                        "src/reports/export.py",
                        "tests/test_reports.py",
                    ],
                    "acceptance": "Streams rows without changing the JSON response.",
                },
                media_type="application/json",
            )
        ],
    )
    contract = ReceiverContract(
        goal="Implement streaming CSV export for the report endpoint.",
        required=("constraints", "decisions", "pending_work", "artifacts"),
        preferred=("completed_work", "evidence", "tool_results"),
        max_tokens=650,
    )

    result = compile_handoff(sender_state, contract)
    packet = result.packet

    assert result.source_tokens > result.packet_tokens
    assert result.packet_tokens <= contract.max_tokens
    assert result.omitted_count == 2
    assert packet.constraints and packet.decisions and packet.pending_work
    assert packet.artifacts

    print("Planner -> Executor")
    print(f"Before: {result.source_tokens:,} estimated tokens")
    print(f"After HandoffSieve: {result.packet_tokens:,} estimated tokens")
    print(f"Context reduction: {result.estimated_savings_percent:.1f}%")
    print("\nHandoffPacket")
    print(f"  Goal: {packet.goal}")
    print(f"  Constraint: {packet.constraints[0].content}")
    print(f"  Decision: {packet.decisions[0].content}")
    print(f"  Pending work: {packet.pending_work[0].content}")
    print(f"  Artifact: {packet.artifacts[0].name}")
    print("\nResult: the executor can start without reading the full plan.")


if __name__ == "__main__":
    main()
