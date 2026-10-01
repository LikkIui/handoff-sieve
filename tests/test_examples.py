from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    ROOT / "examples" / "receiver_views" / "demo.py",
    ROOT / "examples" / "missing_state" / "demo.py",
    ROOT / "examples" / "budget_feedback" / "demo.py",
    ROOT / "examples" / "researcher_to_coder" / "demo.py",
    ROOT / "examples" / "planner_to_executor" / "demo.py",
    ROOT / "examples" / "researcher_to_reviewer" / "demo.py",
    ROOT / "examples" / "quickstart" / "run.py",
    ROOT / "examples" / "failure_zoo" / "secret_leakage" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "context_flooding" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "constraint_loss" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "full_envelope_leakage" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "route_drift" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "ingress_abuse" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "summary_reinjection" / "demo.py",
    ROOT / "examples" / "failure_zoo" / "redaction_dedup_collision" / "demo.py",
]


@pytest.mark.parametrize("script", EXAMPLES, ids=lambda path: path.parent.name)
def test_example_runs_offline(script: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Result:" in completed.stdout or "Transmitted messages:" in completed.stdout
