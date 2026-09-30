"""Run a packet-only, offline researcher-to-coder takeover acceptance.

The receiver is a small deterministic code generator, not an LLM. This proves
that canonical packet data can cross a process boundary and complete a
runnable task without exposing the sender's full state.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from handoff_sieve import (
    Artifact,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_history,
)

HERE = Path(__file__).resolve().parent
RECEIVER = HERE / "offline_receiver.py"
ACCEPTANCE = HERE / "acceptance.py"


def _run_checked(
    command: list[str], *, cwd: Path, label: str
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{label} failed: {details}")
    return completed


def run_packet_only_takeover(receiver_text: str) -> dict[str, Any]:
    """Run the receiver and objective checks in a fresh temporary workspace."""

    with tempfile.TemporaryDirectory(prefix="handoff-sieve-takeover-") as directory:
        workspace = Path(directory)
        packet_path = workspace / "handoff_packet.json"
        packet_path.write_text(receiver_text, encoding="utf-8")

        receiver_run = _run_checked(
            [sys.executable, str(RECEIVER), str(packet_path), str(workspace)],
            cwd=workspace,
            label="offline receiver",
        )
        receiver_result = json.loads(receiver_run.stdout)

        acceptance_run = _run_checked(
            [sys.executable, str(ACCEPTANCE), str(workspace)],
            cwd=workspace,
            label="takeover acceptance",
        )
        acceptance_result = json.loads(acceptance_run.stdout)
        return {
            "generated": receiver_result["generated"],
            "status": acceptance_result["status"],
            "passed": acceptance_result["passed"],
            "total": acceptance_result["total"],
        }


def main() -> None:
    noise = "Unrelated search note about vendor pricing and launch copy. " * 180
    tool_noise = "Crawler heartbeat: page fetched successfully. " * 120
    meeting_noise = "Discussion about naming, screenshots, and social posts. " * 100

    sender_state = HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(content=noise),
            Message(content=tool_noise),
            Message(content=meeting_noise),
            Message(
                content="Constraint: Keep the public decide_refresh_action "
                "keyword-only API stable.",
            ),
            Message(
                content="Decision: Reject a hash mismatch first; revoke the whole "
                "family on reuse; reject expired tokens; rotate otherwise.",
            ),
            Message(
                content="Completed: Reduced the refresh-token behavior to an "
                "ordered decision table.",
            ),
            Message(
                content="Failed attempt: Checking expiry before reuse hid reuse of "
                "an expired revoked token.",
            ),
            Message(
                content="Evidence: The session service already supplies "
                "hash_matches, token_revoked, and token_expired flags.",
            ),
            Message(
                content="TODO: Generate session_policy.py and satisfy the takeover "
                "acceptance cases.",
            ),
            Message(
                role="tool",
                content="Existing session tests pass; the decision function is "
                "still missing.",
            ),
        ],
        artifacts=[
            Artifact(
                name="refresh-action-spec",
                content={
                    "task_type": "python_decision_table",
                    "target": "solution/session_policy.py",
                    "function": "decide_refresh_action",
                    "keyword_args": [
                        "hash_matches",
                        "token_revoked",
                        "token_expired",
                    ],
                    "rules": [
                        {
                            "when": {"hash_matches": False},
                            "return": "reject_invalid",
                        },
                        {
                            "when": {"token_revoked": True},
                            "return": "revoke_family",
                        },
                        {
                            "when": {"token_expired": True},
                            "return": "reject_expired",
                        },
                    ],
                    "default": "rotate",
                },
                media_type="application/json",
            )
        ],
    )
    contract = ReceiverContract(
        goal="Implement refresh-token action selection in the auth module.",
        required=(
            "constraints",
            "decisions",
            "completed_work",
            "pending_work",
            "artifacts",
        ),
        preferred=("failed_attempts", "evidence", "tool_results"),
        max_tokens=900,
    )

    result = compile_history(sender_state, contract)
    packet = result.packet

    assert result.source_tokens > result.packet_tokens
    assert result.packet_tokens <= contract.max_tokens
    assert result.omitted_count == 3
    assert all(
        getattr(packet, section)
        for section in (
            "constraints",
            "decisions",
            "evidence",
            "completed_work",
            "failed_attempts",
            "pending_work",
            "artifacts",
            "tool_results",
        )
    )

    takeover = run_packet_only_takeover(packet.to_receiver_text())

    print("Researcher -> Coder")
    print(f"Before: {result.source_tokens:,} estimated tokens")
    print(f"After HandoffSieve: {result.packet_tokens:,} estimated tokens")
    print(f"Context reduction: {result.estimated_savings_percent:.1f}%")
    print(f"Omitted: {result.omitted_count} unrelated items")
    print(
        "Normalized: "
        f"{result.normalization.normalized_messages} useful messages "
        "with local rules (0 model calls)"
    )
    print("\nHandoffPacket")
    print(f"  Goal: {packet.goal}")
    print(f"  Constraints: {packet.constraints[0].content}")
    print(f"  Decisions: {packet.decisions[0].content}")
    print(f"  Evidence: {packet.evidence[0].content}")
    print(f"  Completed work: {packet.completed_work[0].content}")
    print(f"  Failed attempts: {packet.failed_attempts[0].content}")
    print(f"  Pending work: {packet.pending_work[0].content}")
    print(f"  Artifacts: {packet.artifacts[0].name}")
    print(f"  Tool results: {packet.tool_results[0].content}")
    print("\nReceiver boundary: canonical HandoffPacket JSON only")
    print("Receiver: deterministic offline generator (no LLM or API call)")
    print(f"Generated: {takeover['generated']}")
    print(
        "Takeover acceptance: "
        f"{takeover['status'].upper()} "
        f"({takeover['passed']}/{takeover['total']} checks)"
    )
    print("\nResult: packet-only offline takeover completed and verified.")


if __name__ == "__main__":
    main()
