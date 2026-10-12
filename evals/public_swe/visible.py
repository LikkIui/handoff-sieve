"""Run original repository tests in development images, without grading answers.

This batch provides feedback for a later receiver correction. It deliberately
does not import the official grader or load the full dataset snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import re
import shlex
import tarfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
RESULTS = ROOT / "results"
PYLINT_TASK = "pylint-dev__pylint-6528"
PYLINT_IMAGE = "swebench/sweb.eval.x86_64.pylint-dev_1776_pylint-6528"
# Selected from the original base checkout's tests/test_self.py, not evaluator
# test identifiers. Freeze the same command for every comparison condition.
PYLINT_COMMAND = (
    "python",
    "-m",
    "pytest",
    "-q",
    "tests/test_self.py",
    "-k",
    "recursive or regex_paths_csv_validator",
)
MAX_PATCH_BYTES = 2_000_000
MAX_OUTPUT_BYTES = 16_000

# These broad suites are chosen from original repository source, not evaluator
# case names. Every condition receives the same frozen command and source tree.
VISIBLE_PROFILES = {
    PYLINT_TASK: (
        "pylint-dev/pylint",
        PYLINT_IMAGE,
        PYLINT_COMMAND,
        ("tests/test_self.py",),
    ),
    "django__django-13212": (
        "django/django",
        "swebench/sweb.eval.x86_64.django_1776_django-13212",
        (
            "python",
            "tests/runtests.py",
            "forms_tests",
            "--verbosity",
            "1",
            "--parallel",
            "1",
        ),
        ("tests/runtests.py", "tests/forms_tests"),
    ),
    "sphinx-doc__sphinx-7748": (
        "sphinx-doc/sphinx",
        "swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-7748",
        (
            "python",
            "-m",
            "pytest",
            "-q",
            "tests/test_ext_autodoc.py",
            "tests/test_ext_autodoc_configs.py",
        ),
        ("tests/test_ext_autodoc.py", "tests/test_ext_autodoc_configs.py"),
    ),
}


@dataclass(frozen=True)
class Candidate:
    condition: str
    path: str
    patch: bytes


@dataclass(frozen=True)
class TaskRequest:
    instance_id: str
    repo: str
    base_commit: str
    image: str
    command: tuple[str, ...]
    candidates: tuple[Candidate, ...]


def results_path(value: str, *, repository: Path = REPOSITORY) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Request and patch paths must be repository-relative")
    results_root = (repository / "evals/public_swe/results").resolve()
    path = (repository / value).resolve()
    if not results_root.is_relative_to(repository.resolve()) or not path.is_relative_to(
        results_root
    ):
        raise ValueError("Request and patch paths must stay within public results")
    return path


def load_request(value: str, *, repository: Path = REPOSITORY) -> list[TaskRequest]:
    public_root = repository / "evals/public_swe"
    request = json.loads(results_path(value, repository=repository).read_text("utf-8"))
    if (
        not isinstance(request, dict)
        or set(request) != {"schema", "tasks"}
        or request["schema"] != 1
    ):
        raise ValueError("Invalid visible feedback request fields")
    manifest = json.loads((public_root / "data/manifest.json").read_text("utf-8"))
    public_tasks = {
        task["instance_id"]: task
        for task in map(
            json.loads,
            (public_root / "data/development.jsonl").read_text("utf-8").splitlines(),
        )
    }
    tasks = request["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 10:
        raise ValueError("Visible feedback accepts one to ten development tasks")
    result = []
    seen = set()
    for item in tasks:
        required = {"instance_id", "command", "candidates"}
        if not isinstance(item, dict) or set(item) not in (
            required,
            required | {"image"},
        ):
            raise ValueError("Invalid visible task fields")
        task_id = item["instance_id"]
        if task_id in seen or task_id not in manifest["splits"]["development"]:
            raise ValueError("Duplicate or non-development task")
        seen.add(task_id)
        profile = VISIBLE_PROFILES.get(task_id)
        if profile is None or item["command"] != list(profile[2]):
            raise ValueError(
                "Only a frozen original repository test command is supported"
            )
        image = item.get("image", profile[1] + ":latest")
        if image != profile[1] + ":latest" and not re.fullmatch(
            re.escape(profile[1]) + r"@sha256:[0-9a-f]{64}", image
        ):
            raise ValueError("Use the original official image or its recorded digest")
        task = public_tasks[task_id]
        if task["repo"] != profile[0] or not re.fullmatch(
            r"[0-9a-f]{40}", task["base_commit"]
        ):
            raise ValueError("Unexpected public task source metadata")
        values = item["candidates"]
        if not isinstance(values, list) or not 1 <= len(values) <= 3:
            raise ValueError("Supply one to three candidate conditions")
        candidates = []
        names = {"unchanged_source"}
        for candidate in values:
            if not isinstance(candidate, dict) or set(candidate) != {
                "condition",
                "patch",
            }:
                raise ValueError("Invalid candidate fields")
            condition = candidate["condition"]
            if (
                not isinstance(condition, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", condition)
                or condition in names
            ):
                raise ValueError("Invalid or duplicate condition name")
            names.add(condition)
            path = results_path(candidate["patch"], repository=repository)
            if not path.is_file() or path.stat().st_size > MAX_PATCH_BYTES:
                raise ValueError("Missing or oversized candidate patch")
            patch = path.read_bytes()
            patch.decode("utf-8")
            candidates.append(Candidate(condition, candidate["patch"], patch))
        result.append(
            TaskRequest(
                task_id,
                task["repo"],
                task["base_commit"],
                image,
                profile[2],
                tuple(candidates),
            )
        )
    return result


def _execute(container: Any, command: list[str], timeout: int) -> dict[str, Any]:
    """Capture a bounded output tail while the command runs, including failures."""
    api = container.client.api
    exec_id = api.exec_create(container.id, command, workdir="/testbed")["Id"]
    output = bytearray()
    stream: Any = None
    error: Exception | None = None
    truncated = False

    def consume() -> None:
        nonlocal stream, error, truncated
        try:
            stream = api.exec_start(exec_id, stream=True)
            for chunk in stream:
                output.extend(chunk)
                if len(output) > MAX_OUTPUT_BYTES:
                    del output[:-MAX_OUTPUT_BYTES]
                    truncated = True
        except Exception as caught:
            error = caught

    started = time.perf_counter()
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    thread.join(timeout)
    timed_out = thread.is_alive()
    if timed_out:
        container.kill()
        if stream is not None:
            stream.close()
        thread.join(5)
    elif error is not None:
        raise error
    return {
        "exit_code": None if timed_out else api.exec_inspect(exec_id)["ExitCode"],
        "timed_out": timed_out,
        "stdout": bytes(output).decode("utf-8", errors="replace"),
        "stdout_truncated": truncated,
        "seconds": round(time.perf_counter() - started, 3),
    }


def _copy_patch(container: Any, patch: bytes) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("handoff-candidate.patch")
        info.size = len(patch)
        archive.addfile(info, io.BytesIO(patch))
    container.put_archive("/tmp", buffer.getvalue())


def _check(container: Any, command: list[str]) -> str:
    value = _execute(container, command, 30)
    if value["exit_code"] != 0 or value["timed_out"] or value["stdout_truncated"]:
        raise ValueError("Source or patch verification failed: " + value["stdout"])
    return str(value["stdout"]).strip()


def run_condition(
    task: TaskRequest,
    candidate: Candidate,
    client: Any,
    *,
    timeout: int,
    image_id: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "patch_path": candidate.path,
        "patch_sha256": hashlib.sha256(candidate.patch).hexdigest(),
        "expected_base_commit": task.base_commit,
        "base_commit_verified": False,
        "patch_applied": False,
    }
    container = None
    try:
        # No model credential, host mount, grader script or evaluator patch enters
        # this container. Each condition starts from a new original image.
        container = client.containers.run(
            image_id or task.image,
            command=["tail", "-f", "/dev/null"],
            detach=True,
            network_disabled=True,
        )
        report["image_initial_head"] = _check(container, ["git", "rev-parse", "HEAD"])
        # Official images provide the installed environment, but their starting
        # checkout can differ. Restore only the public source revision inside
        # this new, unmounted container; never use evaluator scripts or patches.
        _check(container, ["git", "cat-file", "-e", task.base_commit + "^{commit}"])
        _check(container, ["git", "reset", "--hard", task.base_commit])
        _check(container, ["git", "clean", "-fd"])
        report["prepared_head"] = _check(container, ["git", "rev-parse", "HEAD"])
        if report["prepared_head"] != task.base_commit:
            raise ValueError(
                f"Prepared source revision differs: expected {task.base_commit}, "
                f"actual {report['prepared_head']}"
            )
        if _check(container, ["git", "status", "--porcelain"]):
            raise ValueError("Image source checkout is not clean")
        report["base_commit_verified"] = True
        test_paths = VISIBLE_PROFILES[task.instance_id][3]
        report["visible_test_blobs"] = {
            path: _check(container, ["git", "rev-parse", "HEAD:" + path])
            for path in test_paths
        }
        if task.instance_id == PYLINT_TASK:
            report["visible_test_blob"] = report["visible_test_blobs"][test_paths[0]]
        if candidate.patch:
            _copy_patch(container, candidate.patch)
            _check(
                container, ["git", "apply", "--check", "/tmp/handoff-candidate.patch"]
            )
            _check(container, ["git", "apply", "/tmp/handoff-candidate.patch"])
            report["patch_applied"] = True
        if _check(container, ["git", "diff", "--name-only", "HEAD", "--", "tests"]):
            raise ValueError(
                "Candidate changes original visible tests or their fixtures"
            )
        script = (
            "source /opt/miniconda3/etc/profile.d/conda.sh && "
            "conda activate testbed && export LANG=C.UTF-8 LC_ALL=C.UTF-8 && "
            "cd /testbed && exec " + shlex.join(task.command)
        )
        report.update(
            status="tested",
            test=_execute(container, ["/bin/bash", "-lc", script], timeout),
        )
    except Exception as error:
        report.update(
            status="environment_error",
            error_type=type(error).__name__,
            error_message=str(error)[:MAX_OUTPUT_BYTES],
        )
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception as error:
                report["cleanup_error"] = type(error).__name__
    return report


def run_task(task: TaskRequest, client: Any, *, timeout: int) -> dict[str, Any]:
    image = client.images.pull(task.image)
    source_image = image
    overrides = {}
    if task.instance_id == "sphinx-doc__sphinx-7748":
        # The original tox.ini supports docutils 0.12--0.16. The upstream image
        # currently includes a newer incompatible version. Fix the environment
        # for every condition, without touching source or dropping any test.
        dockerfile = (
            f"FROM {image.id}\n"
            "RUN /opt/miniconda3/envs/testbed/bin/python -m pip install "
            "--disable-pip-version-check --no-deps docutils==0.16\n"
        )
        image, _ = client.images.build(
            fileobj=io.BytesIO(dockerfile.encode("utf-8")), rm=True
        )
        overrides = {"docutils": "0.16"}
    candidates = (Candidate("unchanged_source", "", b""), *task.candidates)
    outcomes = {
        candidate.condition: run_condition(
            task, candidate, client, timeout=timeout, image_id=image.id
        )
        for candidate in candidates
    }
    unchanged = outcomes["unchanged_source"]
    baseline_valid = (
        unchanged["status"] == "tested"
        and unchanged["test"]["exit_code"] == 0
        and not unchanged["test"]["timed_out"]
    )
    return {
        "instance_id": task.instance_id,
        "repo": task.repo,
        "base_commit": task.base_commit,
        "image": task.image,
        "image_id": image.id,
        "image_digests": source_image.attrs.get("RepoDigests", []),
        "original_image_id": source_image.id,
        "runtime_dependency_overrides": overrides,
        "locale": "C.UTF-8",
        "command": list(task.command),
        "baseline_valid": baseline_valid,
        "feedback_scope": "Original repository tests only; not hidden task acceptance",
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", type=Path, default=Path("visible-feedback"))
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 900:
        parser.error("Visible test timeout must be within 1–900 seconds")
    tasks = load_request(args.request)
    docker = importlib.import_module("docker")
    client = docker.from_env(timeout=180)
    args.output.mkdir(parents=True, exist_ok=True)
    valid = True
    try:
        for task in tasks:
            report = run_task(task, client, timeout=args.timeout)
            (args.output / f"{task.instance_id}.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "instance_id": task.instance_id,
                        "baseline_valid": report["baseline_valid"],
                        "statuses": {
                            key: value["status"]
                            for key, value in report["outcomes"].items()
                        },
                    }
                ),
                flush=True,
            )
            valid = valid and report["baseline_valid"]
    finally:
        client.close()
    if not valid:
        raise SystemExit(
            "Original visible-test control failed; inspect environment feedback"
        )


if __name__ == "__main__":
    main()
