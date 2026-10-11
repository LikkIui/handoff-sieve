from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.public_swe import visible

BASE = "a" * 40


def request_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "evals/public_swe"
    (root / "data").mkdir(parents=True)
    (root / "results/batch").mkdir(parents=True)
    (root / "data/manifest.json").write_text(
        json.dumps(
            {
                "splits": {"development": [visible.PYLINT_TASK], "test": ["held-out"]},
            }
        ),
        encoding="utf-8",
    )
    (root / "data/development.jsonl").write_text(
        json.dumps(
            {
                "instance_id": visible.PYLINT_TASK,
                "repo": "pylint-dev/pylint",
                "base_commit": BASE,
                "problem_statement": "Fix recursive discovery",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "results/batch/candidate.patch").write_bytes(b"candidate diff\n")
    request = {
        "schema": 1,
        "tasks": [
            {
                "instance_id": visible.PYLINT_TASK,
                "command": list(visible.PYLINT_COMMAND),
                "candidates": [
                    {
                        "condition": "model_handoff",
                        "patch": "evals/public_swe/results/batch/candidate.patch",
                    }
                ],
            }
        ],
    }
    return root / "results/batch/visible-request.json", request


def load_fixture(
    tmp_path: Path, request: dict[str, Any], path: Path
) -> list[visible.TaskRequest]:
    path.write_text(json.dumps(request), encoding="utf-8")
    return visible.load_request(str(path.relative_to(tmp_path)), repository=tmp_path)


def test_visible_request_only_uses_public_development_metadata(tmp_path: Path) -> None:
    path, request = request_fixture(tmp_path)
    task = load_fixture(tmp_path, request, path)[0]
    assert task.base_commit == BASE
    assert task.image == "swebench/sweb.eval.x86_64.pylint-dev_1776_pylint-6528:latest"
    assert task.candidates[0].patch == b"candidate diff\n"
    assert task.command == visible.PYLINT_COMMAND


@pytest.mark.parametrize(
    "change", ["held_out", "command", "hidden_fields", "duplicate"]
)
def test_request_rejects_tuning_or_answer_access(tmp_path: Path, change: str) -> None:
    path, request = request_fixture(tmp_path)
    task = request["tasks"][0]
    if change == "held_out":
        task["instance_id"] = "held-out"
    elif change == "command":
        task["command"] = ["bash", "-c", "cat /eval.sh"]
    elif change == "hidden_fields":
        task["test_patch"] = "hidden evaluator data"
    else:
        request["tasks"].append(task)
    with pytest.raises(ValueError):
        load_fixture(tmp_path, request, path)


@pytest.mark.parametrize(
    "value", ["../outside.patch", "evals/public_swe/results/../../outside.patch"]
)
def test_patch_paths_cannot_escape_results(tmp_path: Path, value: str) -> None:
    path, request = request_fixture(tmp_path)
    request["tasks"][0]["candidates"][0]["patch"] = value
    with pytest.raises(ValueError, match="within public results"):
        load_fixture(tmp_path, request, path)


def task() -> visible.TaskRequest:
    return visible.TaskRequest(
        visible.PYLINT_TASK,
        "pylint-dev/pylint",
        BASE,
        "official:image",
        visible.PYLINT_COMMAND,
        (visible.Candidate("model_handoff", "candidate.patch", b"candidate"),),
    )


class FakeContainer:
    def __init__(self) -> None:
        self.removed = False
        self.patch = b""

    def remove(self, *, force: bool) -> None:
        assert force
        self.removed = True


def client() -> Any:
    containers: list[FakeContainer] = []

    def create(*args: Any, **kwargs: Any) -> FakeContainer:
        assert kwargs["network_disabled"] is True
        assert args[0] in {"official:image", "sha256:image"}
        container = FakeContainer()
        containers.append(container)
        return container

    return SimpleNamespace(
        containers=SimpleNamespace(run=create),
        created=containers,
        images=SimpleNamespace(
            pull=lambda _: SimpleNamespace(
                id="sha256:image",
                attrs={"RepoDigests": ["official@sha256:fixed"]},
            )
        ),
    )


def output(
    text: str = "", *, exit_code: int = 0, timed_out: bool = False
) -> dict[str, Any]:
    return {
        "stdout": text,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_truncated": False,
        "seconds": 0.01,
    }


def fake_execute(
    container: FakeContainer, command: list[str], timeout: int
) -> dict[str, Any]:
    if command == ["git", "rev-parse", "HEAD"]:
        return output(BASE + "\n")
    if command == ["git", "rev-parse", "HEAD:tests/test_self.py"]:
        return output("b" * 40 + "\n")
    if command[0] == "/bin/bash":
        assert "source /opt/miniconda3/etc/profile.d/conda.sh" in command[-1]
        assert "pytest -q tests/test_self.py" in command[-1]
        return (
            output("AttributeError: _ignore_paths\n", exit_code=1)
            if container.patch
            else output("5 passed\n")
        )
    return output()


def set_patch(container: FakeContainer, patch: bytes) -> None:
    container.patch = patch


def test_candidate_failure_is_feedback_with_a_valid_unchanged_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(visible, "_execute", fake_execute)
    monkeypatch.setattr(visible, "_copy_patch", set_patch)
    docker = client()
    report = visible.run_task(task(), docker, timeout=300)
    assert report["baseline_valid"] is True
    assert report["image_digests"] == ["official@sha256:fixed"]
    outcome = report["outcomes"]["model_handoff"]
    assert outcome["status"] == "tested"
    assert outcome["test"]["exit_code"] == 1
    assert "_ignore_paths" in outcome["test"]["stdout"]
    assert outcome["patch_sha256"] == hashlib.sha256(b"candidate").hexdigest()
    assert all(container.removed for container in docker.created)


@pytest.mark.parametrize("problem", ["wrong_base", "modified_tests", "patch_failure"])
def test_unverified_sources_never_run_visible_tests(
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    commands = []

    def execute(
        container: FakeContainer, command: list[str], timeout: int
    ) -> dict[str, Any]:
        commands.append(command)
        if problem == "wrong_base" and command == ["git", "rev-parse", "HEAD"]:
            return output("c" * 40)
        if problem == "modified_tests" and command[:3] == [
            "git",
            "diff",
            "--name-only",
        ]:
            return output("tests/test_self.py\n")
        if problem == "patch_failure" and command[:3] == ["git", "apply", "--check"]:
            return output("Patch does not apply", exit_code=1)
        return fake_execute(container, command, timeout)

    monkeypatch.setattr(visible, "_execute", execute)
    monkeypatch.setattr(visible, "_copy_patch", set_patch)
    docker = client()
    report = visible.run_condition(task(), task().candidates[0], docker, timeout=300)
    assert report["status"] == "environment_error"
    assert not any(command[0] == "/bin/bash" for command in commands)
    assert docker.created[0].removed


def test_environment_timeout_does_not_become_a_passing_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(
        container: FakeContainer, command: list[str], timeout: int
    ) -> dict[str, Any]:
        if command[0] == "/bin/bash":
            return output("Timed out", exit_code=0, timed_out=True)
        return fake_execute(container, command, timeout)

    monkeypatch.setattr(visible, "_execute", execute)
    monkeypatch.setattr(visible, "_copy_patch", set_patch)
    report = visible.run_task(task(), client(), timeout=300)
    assert report["baseline_valid"] is False


def test_stream_output_is_bounded_and_preserves_test_failure_status() -> None:
    api = SimpleNamespace(
        exec_create=lambda *_, **__: {"Id": "exec"},
        exec_start=lambda *_, **__: iter([b"a" * 20_000, b"\nAttributeError\n"]),
        exec_inspect=lambda _: {"ExitCode": 1},
    )
    container = SimpleNamespace(id="container", client=SimpleNamespace(api=api))
    report = visible._execute(container, ["test"], 5)
    assert len(report["stdout"].encode()) == visible.MAX_OUTPUT_BYTES
    assert report["stdout"].endswith("AttributeError\n")
    assert report["stdout_truncated"] is True
    assert report["exit_code"] == 1
