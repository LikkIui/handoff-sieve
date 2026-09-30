from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "researcher_to_coder"


def _run(
    script: Path, *arguments: Path, cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(script), *(str(argument) for argument in arguments)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_demo_completes_objective_packet_only_takeover() -> None:
    completed = _run(EXAMPLE / "demo.py")

    assert completed.returncode == 0, completed.stderr
    assert "Receiver boundary: canonical HandoffPacket JSON only" in completed.stdout
    assert "deterministic offline generator (no LLM or API call)" in completed.stdout
    assert "Takeover acceptance: PASSED (5/5 checks)" in completed.stdout
    assert "packet-only offline takeover completed and verified" in completed.stdout


def test_receiver_fails_when_task_artifact_is_not_in_packet(tmp_path: Path) -> None:
    packet_path = tmp_path / "handoff_packet.json"
    packet_path.write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    completed = _run(
        EXAMPLE / "offline_receiver.py",
        packet_path,
        tmp_path,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert "refresh-action-spec" in completed.stderr
    assert not (tmp_path / "solution" / "session_policy.py").exists()


def test_acceptance_rejects_incorrect_receiver_output(tmp_path: Path) -> None:
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "session_policy.py").write_text(
        "def decide_refresh_action(*, hash_matches, token_revoked, token_expired):\n"
        "    return 'rotate'\n",
        encoding="utf-8",
    )

    completed = _run(EXAMPLE / "acceptance.py", tmp_path, cwd=tmp_path)

    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "failed"
    assert result["passed"] < result["total"]
