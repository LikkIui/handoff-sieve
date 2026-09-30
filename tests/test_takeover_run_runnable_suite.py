from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TypedDict

import pytest

from evals.takeover import run_runnable_suite


class _SuiteArguments(TypedDict):
    model: str
    provider_label: str
    sdk_version: str
    output_dir: Path
    tasks: tuple[str, ...]
    model_timeout: float
    case_timeout: float
    acceptance_timeout: float


async def _fake_run_task(**kwargs: Any) -> int:
    output: Path = kwargs["output"]
    task_id: str = kwargs["task_id"]
    run_id = f"run-{task_id}"
    rows = [
        {"kind": "run_started", "task_id": task_id, "run_id": run_id},
        {
            "kind": "observation",
            "condition": "full_history",
            "status": "completed",
            "downstream_success": True,
            "local_handoff_token_estimate": 100,
            "provider_usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
            },
            "naive_summary_preparation_usage": None,
            "event_count": 1,
            "checks": [{"id": "behavior", "passed": True}],
        },
        {
            "kind": "observation",
            "condition": "naive_summary",
            "status": "completed",
            "downstream_success": False,
            "local_handoff_token_estimate": 40,
            "provider_usage": {
                "input_tokens": 60,
                "output_tokens": 20,
                "total_tokens": 80,
            },
            "naive_summary_preparation_usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
            },
            "event_count": 2,
            "checks": [{"id": "behavior", "passed": False}],
        },
        {
            "kind": "observation",
            "condition": "handoff_sieve",
            "status": "completed",
            "downstream_success": True,
            "local_handoff_token_estimate": 55,
            "provider_usage": {
                "input_tokens": 70,
                "output_tokens": 25,
                "total_tokens": 95,
            },
            "naive_summary_preparation_usage": None,
            "event_count": 1,
            "checks": [{"id": "behavior", "passed": True}],
        },
        {"kind": "run_completed", "records_written": 3, "run_id": run_id},
    ]
    output.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return 3


def test_default_cli_is_offline_and_lists_all_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run_runnable_suite.main([])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "not_run"
    assert payload["tasks"] == list(run_runnable_suite.ALL_TASKS)
    assert len(payload["tasks"]) == 20


def test_suite_writes_per_task_results_and_exact_aggregate(tmp_path: Path) -> None:
    output_dir = tmp_path / "suite"
    tasks = ("rc02_retry_after", "rr02_falsy_config_review")

    aggregate = asyncio.run(
        run_runnable_suite.run_suite(
            model="test-model",
            provider_label="test-provider",
            sdk_version="test-sdk",
            output_dir=output_dir,
            tasks=tasks,
            model_timeout=180,
            case_timeout=190,
            acceptance_timeout=30,
            run_task=_fake_run_task,
        )
    )

    assert all((output_dir / f"{task_id}.jsonl").is_file() for task_id in tasks)
    assert json.loads((output_dir / "suite.json").read_text())["status"] == "completed"
    assert aggregate["aggregate"] == {
        "full_history": {
            "successes": 2,
            "tasks": 2,
            "handoff_tokens": 200,
            "provider_input_tokens": 240,
            "provider_output_tokens": 60,
            "provider_total_tokens": 300,
            "model_calls": 2,
        },
        "naive_summary": {
            "successes": 0,
            "tasks": 2,
            "handoff_tokens": 80,
            "provider_input_tokens": 320,
            "provider_output_tokens": 60,
            "provider_total_tokens": 380,
            "model_calls": 4,
        },
        "handoff_sieve": {
            "successes": 2,
            "tasks": 2,
            "handoff_tokens": 110,
            "provider_input_tokens": 140,
            "provider_output_tokens": 50,
            "provider_total_tokens": 190,
            "model_calls": 2,
        },
    }


def test_resume_skips_completed_tasks_and_rebuilds_aggregate(tmp_path: Path) -> None:
    output_dir = tmp_path / "suite"
    tasks = ("rc02_retry_after",)
    arguments: _SuiteArguments = {
        "model": "test-model",
        "provider_label": "test-provider",
        "sdk_version": "test-sdk",
        "output_dir": output_dir,
        "tasks": tasks,
        "model_timeout": 180,
        "case_timeout": 190,
        "acceptance_timeout": 30,
    }
    asyncio.run(run_runnable_suite.run_suite(**arguments, run_task=_fake_run_task))

    async def unexpected_run(**_: Any) -> int:
        raise AssertionError("completed task should have been skipped")

    aggregate = asyncio.run(
        run_runnable_suite.run_suite(
            **arguments,
            resume=True,
            run_task=unexpected_run,
        )
    )

    assert aggregate["aggregate"]["handoff_sieve"]["successes"] == 1


def test_resume_rejects_configuration_drift(tmp_path: Path) -> None:
    output_dir = tmp_path / "suite"
    arguments: _SuiteArguments = {
        "model": "test-model",
        "provider_label": "test-provider",
        "sdk_version": "test-sdk",
        "output_dir": output_dir,
        "tasks": ("rc02_retry_after",),
        "model_timeout": 180,
        "case_timeout": 190,
        "acceptance_timeout": 30,
    }
    asyncio.run(run_runnable_suite.run_suite(**arguments, run_task=_fake_run_task))

    with pytest.raises(
        run_runnable_suite.SuiteConfigurationError,
        match="does not match",
    ):
        changed: _SuiteArguments = {**arguments, "model": "different-model"}
        asyncio.run(
            run_runnable_suite.run_suite(
                **changed,
                resume=True,
                run_task=_fake_run_task,
            )
        )
