from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.public_swe import mini_receiver, repository


def action(operation: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "operation": operation,
        "path": "",
        "query": "",
        "old": "",
        "new": "",
        "note": "",
        "start": 0,
        "end": 0,
        **kwargs,
    }


def test_original_test_action_cannot_supply_an_arbitrary_command() -> None:
    assert (
        mini_receiver.parse_receiver_action(json.dumps(action("test")))["operation"]
        == "test"
    )
    parsed = mini_receiver.parse_receiver_action(
        json.dumps(action("test", path="/eval.sh"))
    )
    assert parsed["path"] == "/eval.sh"  # validated by the execution tool
    with pytest.raises(ValueError, match="fields"):
        mini_receiver.parse_receiver_action(
            json.dumps({**action("test"), "command": "bash"})
        )


def test_mini_bridge_preserves_native_reasoning_and_actual_observation(
    tmp_path: Path,
) -> None:
    requests = []
    dumped = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "fixture"},
        {
            "type": "function_call",
            "name": "source_operation",
            "call_id": "call_1",
            "arguments": json.dumps(action("read", path="code.py", start=1, end=4)),
        },
    ]

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        items = [
            SimpleNamespace(**row, model_dump=lambda row=row, **_: row)
            for row in dumped
        ]
        return SimpleNamespace(
            status="completed",
            output=items,
            model_dump=lambda **_: {
                "status": "completed",
                "usage": {"total_tokens": 21},
            },
        )

    model = mini_receiver.MiniReceiverModel(
        SimpleNamespace(responses=SimpleNamespace(create=create)),
        "explicit-model",
        tmp_path / "calls",
    )
    history = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "one packet"},
    ]
    response = model.query(history)
    observation = model.format_observation_messages(
        response, [{"error": "Old text must match exactly once"}]
    )
    model.query([*history, response, *observation])
    assert requests[0]["input"] == [{"role": "user", "content": "one packet"}]
    assert requests[1]["input"][1:3] == dumped
    assert requests[1]["input"][-1]["call_id"] == "call_1"
    assert "Old text must match" in requests[1]["input"][-1]["output"]
    assert model.usage() == {
        "requests": 2,
        "completed_requests": 2,
        "reported_tokens": 42,
        "usage_unavailable_calls": 0,
    }


def test_original_tests_stay_unchanged_and_test_calls_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "tests").mkdir()
    original = tmp_path / "tests/test_original.py"
    original.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(repository, "git", lambda *args: "tests/test_original.py\n")
    monkeypatch.setattr(mini_receiver, "git", lambda *args: "candidate patch")
    patches = []

    def test(patch: bytes) -> dict[str, Any]:
        patches.append(patch)
        return {"status": "tested", "test": {"exit_code": 1, "stdout": "real failure"}}

    env = mini_receiver.MiniReceiverEnvironment(tmp_path, test, tests=1)
    assert "at least one" in env.execute(action("finish"))["error"]
    edit = env.execute(
        action("edit", path="outside/../tests/test_original.py", old="1", new="2")
    )
    assert "unchanged" in edit["error"]
    assert original.read_text(encoding="utf-8") == "value = 1\n"
    invalid = env.execute(action("test", path="/eval.sh"))
    assert "empty unused fields" in invalid["error"]
    assert env.test_requests == 0 and patches == []
    assert "at least one" in env.execute(action("finish"))["error"]
    assert env.execute(action("test"))["test"]["exit_code"] == 1
    assert "exhausted" in env.execute(action("test"))["error"]
    assert patches == [b"candidate patch"]
