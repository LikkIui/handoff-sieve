from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("agents")
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/openai_takeover/run.py"


def test_real_sdk_workflow_completes_packet_only_offline_takeover() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        environment.pop(name, None)
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Receiver input items: 1" in completed.stdout
    assert "Provider calls: 0" in completed.stdout
    assert "Takeover acceptance: 6/6" in completed.stdout


def test_takeover_acceptance_catches_the_known_failed_approach() -> None:
    import json

    spec = importlib.util.spec_from_file_location("sdk_takeover_example", EXAMPLE)
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    bad_source = (
        "def decide_refresh_action(*, hash_matches, token_revoked, token_expired):\n"
        "    if not hash_matches:\n        return 'reject_invalid'\n"
        "    if token_expired:\n        return 'reject_expired'\n"
        "    if token_revoked:\n        return 'revoke_family'\n"
        "    return 'rotate'\n"
    )
    with pytest.raises(AssertionError, match="rejected expiry-before-reuse"):
        example.check_solution(json.dumps({"source": bad_source}))


def test_sdk_http_payload_contains_only_the_selected_packet(monkeypatch) -> None:
    """Exercise actual request serialization with a local mocked transport."""
    import asyncio
    import json

    httpx = pytest.importorskip("httpx2")
    from agents import OpenAIProvider
    from openai import AsyncOpenAI

    spec = importlib.util.spec_from_file_location("sdk_wire_example", EXAMPLE)
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    source = json.loads(
        (EXAMPLE.parent / "checkpoint.json").read_text(encoding="utf-8")
    )["records"][0]["solution_source"]
    payloads = []

    async def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp-local-transport",
                "object": "response",
                "created_at": 0,
                "model": "offline-fixture-model",
                "status": "completed",
                "output": [
                    {
                        "id": "msg-local",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"source": source}),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        )

    async def run():
        client = AsyncOpenAI(
            api_key="offline-fixture-key",
            base_url="https://example.test/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        provider = OpenAIProvider(
            openai_client=client, use_responses=True, use_responses_websocket=False
        )
        monkeypatch.setattr(
            example, "OfflineCoder", lambda: provider.get_model("offline-fixture-model")
        )
        try:
            for full in (True, False):
                await example.run_workflow(full_history=full)
        finally:
            await client.close()

    asyncio.run(run())
    full, sieve = payloads
    assert len(full["input"]) == 7
    assert len(sieve["input"]) == 1
    assert full["instructions"] == sieve["instructions"] == example.CODER_INSTRUCTIONS
    assert "hosting prices" in json.dumps(full["input"])
    assert "hosting prices" not in json.dumps(sieve["input"])
    assert not sieve.get("previous_response_id") and not sieve.get("conversation")
    assert not sieve.get("tools")
    packet = json.loads(sieve["input"][0]["content"])
    assert packet["decisions"] and packet["failed_attempts"] and packet["tool_results"]
    sizes = [
        len(json.dumps(payload, separators=(",", ":")).encode()) for payload in payloads
    ]
    assert sizes[1] < sizes[0]
    print(f"Local serialized HTTP bodies: {sizes[0]} -> {sizes[1]} bytes")
