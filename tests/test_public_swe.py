from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evals.public_swe import repository
from evals.public_swe.dataset import download_snapshot, public_task, split_rows
from evals.public_swe.repository import RepositoryTools, parse_action, parse_actions


def rows() -> list[dict[str, Any]]:
    return [
        {
            "instance_id": f"task-{i}",
            "repo": f"repo/{i % 12}",
            "difficulty": f"difficulty-{i % 4}",
            "patch": "answer",
            "resolved": bool(i % 2),
        }
        for i in range(500)
    ]


def test_splits_are_distinct_and_stable_without_outcomes() -> None:
    data = rows()
    original = split_rows(data)
    for row in data:
        row["resolved"] = not row["resolved"]
        row["patch"] = "different hidden answer"
    assert split_rows(list(reversed(data))) == original
    assert {k: len(v) for k, v in original.items()} == {
        "development": 30,
        "test": 200,
        "reserve": 270,
    }
    assert len(set().union(*(set(value) for value in original.values()))) == 500


def test_duplicate_task_ids_are_not_independent_tasks() -> None:
    data = rows()
    data[1]["instance_id"] = data[0]["instance_id"]
    with pytest.raises(ValueError, match="Duplicate"):
        split_rows(data)


def test_reference_material_is_never_exported_to_agent() -> None:
    data = {
        "instance_id": "a",
        "repo": "x/y",
        "base_commit": "a" * 40,
        "problem_statement": "fix",
        "patch": "hidden fix",
        "test_patch": "hidden checks",
        "eval_script": "hidden grading",
        "hints_text": "post hoc hints",
        "FAIL_TO_PASS": ["hidden test"],
    }
    assert public_task(data) == {
        "instance_id": "a",
        "repo": "x/y",
        "base_commit": "a" * 40,
        "problem_statement": "fix",
    }


def test_corrupt_snapshot_is_rejected_without_network(tmp_path: Path) -> None:
    (tmp_path / "verified.parquet").write_bytes(b"modified data")
    with pytest.raises(ValueError, match="checksum"):
        download_snapshot(tmp_path)


def tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, writable: bool
) -> RepositoryTools:
    monkeypatch.setattr(repository, "git", lambda *_: "mod.py\n")
    (tmp_path / "mod.py").write_text("value = 1\n", encoding="utf-8")
    return RepositoryTools(tmp_path, writable=writable)


@pytest.mark.parametrize(
    "path", ["../answer.json", ".git/config", "../elsewhere/.git/config"]
)
def test_source_paths_do_not_reach_host_or_git_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    tool = tools(tmp_path, monkeypatch, writable=False)
    with pytest.raises(ValueError, match="outside"):
        tool.path(path)


def test_researcher_cannot_edit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = tools(tmp_path, monkeypatch, writable=False)
    with pytest.raises(ValueError, match="read-only"):
        tool.execute({"operation": "edit", "path": "mod.py", "old": "1", "new": "2"})
    assert (tmp_path / "mod.py").read_text() == "value = 1\n"


def test_ambiguous_edits_leave_source_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = tools(tmp_path, monkeypatch, writable=True)
    file = tmp_path / "mod.py"
    file.write_text("value = 1 + 1\n")
    with pytest.raises(ValueError, match="exactly once"):
        tool.execute({"operation": "edit", "path": "mod.py", "old": "1", "new": "2"})
    assert file.read_text() == "value = 1 + 1\n"


def test_reader_rejects_unbounded_tool_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = tools(tmp_path, monkeypatch, writable=False)
    with pytest.raises(ValueError, match="lines"):
        tool.execute({"operation": "read", "path": "mod.py", "start": 1, "end": 100000})


def test_action_schema_does_not_accept_research_edits_or_wrong_types() -> None:
    import json

    action = {
        "operation": "edit",
        "path": "mod.py",
        "query": "",
        "old": "1",
        "new": "2",
        "note": "",
        "start": 0,
        "end": 0,
    }
    with pytest.raises(ValueError, match="operation"):
        parse_action(json.dumps(action), writable=False)
    action["start"] = True
    with pytest.raises(ValueError, match="type"):
        parse_action(json.dumps(action), writable=True)


def test_batched_gateway_actions_are_all_validated() -> None:
    import json

    action = {
        "operation": "read",
        "path": "mod.py",
        "query": "",
        "old": "",
        "new": "",
        "note": "",
        "start": 1,
        "end": 10,
    }
    text = json.dumps(action)
    assert parse_actions(text + text, writable=False) == [action, action]
    with pytest.raises(ValueError):
        parse_actions(text + '{"operation":"edit"}', writable=False)
    with pytest.raises(ValueError):
        parse_actions("```json\n" + text + "\n```", writable=False)


def test_source_fork_uses_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(repository, "git", lambda *args: calls.append(args) or "")
    repository.fork_source(Path("work/task/source"), Path("work/task/coder"))
    assert calls[0][0] == (tmp_path / "work/task").resolve()
    assert calls[0][-2:] == (
        str(tmp_path / "work/task/source"),
        str(tmp_path / "work/task/coder"),
    )


def test_native_agent_returns_real_tool_error_before_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import json
    from types import SimpleNamespace

    from evals.public_swe.run import agent

    tool = tools(tmp_path, monkeypatch, writable=True)
    actions = [
        {"operation": "edit", "path": "mod.py", "old": "absent", "new": "2"},
        {"operation": "finish", "path": "", "old": "", "new": ""},
    ]
    requests = []

    class FakeRecorder:
        async def create(self, **kwargs: Any) -> Any:
            import copy

            requests.append(copy.deepcopy(kwargs))
            values = actions[len(requests) - 1]
            args = {"query": "", "note": "", "start": 0, "end": 0, **values}
            dump = {
                "type": "function_call",
                "call_id": f"call-{len(requests)}",
                "name": "source_operation",
                "arguments": json.dumps(args),
            }
            item = SimpleNamespace(**dump, model_dump=lambda **_: dump)
            return SimpleNamespace(status="completed", output=[item])

        def usage(self) -> dict[str, Any]:
            return {"model_calls": len(requests)}

    result = asyncio.run(
        agent(FakeRecorder(), "unit-fixture", tool, "fix", 2, researcher=False)
    )  # type: ignore[arg-type]
    assert requests[0]["parallel_tool_calls"] is False
    output = requests[1]["input"][-1]
    assert output["type"] == "function_call_output"
    assert output["call_id"] == "call-1"
    assert "Old text must match exactly once" in output["output"]
    assert (tmp_path / "mod.py").read_text() == "value = 1\n"
    assert result["executed_tool_steps"] == 1
