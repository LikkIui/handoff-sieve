from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("agents")
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/three_agent_relay/run.py"


def load_example():
    spec = importlib.util.spec_from_file_location("three_agent_relay_example", EXAMPLE)
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    return example


def test_real_sdk_relay_preserves_state_and_checks_generated_code() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        environment.pop(name, None)
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE), "--json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout)
    assert record["provider_calls"] == 0
    assert record["coder_acceptance"] == {"passed": 5, "total": 5}
    assert record["review"]["verdict"] == "approve"
    assert record["review"]["passed"] == record["review"]["total"] == 9
    first, second = record["handoffs"]
    assert (first["sender"], first["receiver"]) == ("researcher", "coder")
    assert (second["sender"], second["receiver"]) == ("coder", "reviewer")
    for item in (first, second):
        assert item["receiver_input_items"] == 1
        assert item["constraints_preserved"]
        assert item["decisions_preserved"]
        assert item["failed_attempt_preserved"]
        assert item["packet_estimated_tokens"] <= 1600
    assert first["source_estimated_tokens"] > first["packet_estimated_tokens"]
    assert first["completed_work_items"] == first["completed_tool_results"] == 0
    assert second["completed_work_items"] == second["completed_tool_results"] == 1


def test_reviewer_rejects_code_even_when_coder_checks_pass(monkeypatch) -> None:
    example = load_example()
    bad_source = (
        "def decide_refresh_action(*, hash_matches, token_revoked, token_expired):\n"
        "    if not hash_matches:\n        return 'reject_invalid'\n"
        "    if token_expired:\n        return 'reject_expired'\n"
        "    if token_revoked:\n        return 'revoke_family'\n"
        "    return 'rotate'\n"
    )
    monkeypatch.setattr(example, "build_source", lambda packet: bad_source)
    record = asyncio.run(example.run_workflow())
    assert record["coder_acceptance"] == {"passed": 5, "total": 5}
    assert record["review"]["verdict"] == "request_changes"
    assert record["review"]["passed"] == 8
    assert record["review"]["total"] == 9
    assert [
        check["id"] for check in record["review"]["checks"] if not check["passed"]
    ] == ["case_111"]
