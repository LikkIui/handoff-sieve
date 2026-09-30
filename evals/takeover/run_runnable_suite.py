"""Run and aggregate the complete runnable takeover suite explicitly."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.takeover import run_runnable_openai

PILOT_TASKS = (
    "rc01_composite_cursor",
    "pe01_streaming_csv",
    "rr01_cursor_review",
)
ALL_TASKS = tuple(run_runnable_openai._SPECS)
EXPANDED_TASKS = tuple(task_id for task_id in ALL_TASKS if task_id not in PILOT_TASKS)

RunTask = Callable[..., Awaitable[int]]


class SuiteConfigurationError(RuntimeError):
    """Raised before an invalid or inconsistent suite can call a provider."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SuiteConfigurationError(f"invalid suite metadata: {path}") from error
    if not isinstance(payload, dict):
        raise SuiteConfigurationError(f"invalid suite metadata: {path}")
    return payload


def _configuration(
    *,
    model: str,
    provider_label: str,
    sdk_version: str,
    tasks: tuple[str, ...],
    model_timeout: float,
    case_timeout: float,
    acceptance_timeout: float,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "status": "running",
        "started_at": _utcnow(),
        "requested_model": model,
        "provider": provider_label,
        "sdk_version": sdk_version,
        "tasks": list(tasks),
        "model_timeout_seconds": model_timeout,
        "case_timeout_seconds": case_timeout,
        "acceptance_timeout_seconds": acceptance_timeout,
    }


def _resume_matches(stored: dict[str, Any], expected: dict[str, Any]) -> bool:
    fields = (
        "schema_version",
        "requested_model",
        "provider",
        "sdk_version",
        "tasks",
        "model_timeout_seconds",
        "case_timeout_seconds",
        "acceptance_timeout_seconds",
    )
    return all(stored.get(field) == expected.get(field) for field in fields)


def _result_rows(path: Path) -> list[dict[str, Any]]:
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise SuiteConfigurationError(f"invalid task result: {path}") from error
    if (
        len(rows) != 5
        or rows[0].get("kind") != "run_started"
        or rows[-1].get("kind") != "run_completed"
    ):
        raise SuiteConfigurationError(f"incomplete task result: {path}")
    return rows


def _usage_amount(
    usage: dict[str, Any],
    preparation: dict[str, Any],
    field: str,
) -> int:
    return int(usage.get(field, 0)) + int(preparation.get(field, 0))


def build_aggregate(
    output_dir: Path,
    tasks: tuple[str, ...],
) -> dict[str, Any]:
    """Derive suite totals from exact per-task JSONL records."""

    conditions = ("full_history", "naive_summary", "handoff_sieve")
    totals = {
        condition: {
            "successes": 0,
            "tasks": 0,
            "handoff_tokens": 0,
            "provider_input_tokens": 0,
            "provider_output_tokens": 0,
            "provider_total_tokens": 0,
            "model_calls": 0,
        }
        for condition in conditions
    }
    task_rows: list[dict[str, Any]] = []
    for task_id in tasks:
        rows = _result_rows(output_dir / f"{task_id}.jsonl")
        observations = {row["condition"]: row for row in rows[1:-1]}
        if set(observations) != set(conditions):
            raise SuiteConfigurationError(
                f"task result has wrong conditions: {task_id}"
            )
        summary: dict[str, Any] = {"task_id": task_id, "conditions": {}}
        for condition in conditions:
            observation = observations[condition]
            usage = observation.get("provider_usage") or {}
            preparation = observation.get("naive_summary_preparation_usage") or {}

            success = observation.get("downstream_success") is True
            handoff = int(observation.get("local_handoff_token_estimate") or 0)
            calls = int(observation.get("event_count") or 0)
            total = totals[condition]
            total["successes"] += int(success)
            total["tasks"] += 1
            total["handoff_tokens"] += handoff
            total["provider_input_tokens"] += _usage_amount(
                usage, preparation, "input_tokens"
            )
            total["provider_output_tokens"] += _usage_amount(
                usage, preparation, "output_tokens"
            )
            total["provider_total_tokens"] += _usage_amount(
                usage, preparation, "total_tokens"
            )
            total["model_calls"] += calls
            summary["conditions"][condition] = {
                "success": success,
                "checks_passed": sum(
                    int(check.get("passed") is True)
                    for check in observation.get("checks", [])
                ),
                "checks_total": len(observation.get("checks", [])),
                "handoff_tokens": handoff,
                "provider_tokens": _usage_amount(usage, preparation, "total_tokens"),
                "model_calls": calls,
                "status": observation.get("status"),
            }
        task_rows.append(summary)
    return {
        "schema_version": "1",
        "tasks": task_rows,
        "aggregate": totals,
    }


async def run_suite(
    *,
    model: str,
    provider_label: str,
    sdk_version: str,
    output_dir: Path,
    tasks: tuple[str, ...],
    model_timeout: float,
    case_timeout: float,
    acceptance_timeout: float,
    resume: bool = False,
    run_task: RunTask = run_runnable_openai.run_batch,
) -> dict[str, Any]:
    """Run selected tasks serially, retaining complete tasks across resumes."""

    if not model.strip() or not provider_label.strip() or not sdk_version.strip():
        raise SuiteConfigurationError(
            "model, provider_label, and sdk_version cannot be blank"
        )
    if acceptance_timeout <= 0 or model_timeout <= 0:
        raise SuiteConfigurationError("timeouts must be positive")
    if case_timeout <= model_timeout:
        raise SuiteConfigurationError("case_timeout must be greater than model_timeout")
    if not tasks or len(tasks) != len(set(tasks)):
        raise SuiteConfigurationError("tasks must be a non-empty unique sequence")
    unknown = sorted(set(tasks) - set(ALL_TASKS))
    if unknown:
        raise SuiteConfigurationError("unknown tasks: " + ", ".join(unknown))
    expected = _configuration(
        model=model,
        provider_label=provider_label,
        sdk_version=sdk_version,
        tasks=tasks,
        model_timeout=model_timeout,
        case_timeout=case_timeout,
        acceptance_timeout=acceptance_timeout,
    )
    metadata_path = output_dir / "suite.json"
    if resume:
        if not output_dir.is_dir() or not metadata_path.is_file():
            raise SuiteConfigurationError("--resume requires an existing suite")
        stored = _read_json(metadata_path)
        if not _resume_matches(stored, expected):
            raise SuiteConfigurationError("resume configuration does not match")
    else:
        try:
            output_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise SuiteConfigurationError(
                "output directory already exists; use --resume"
            ) from error
        _write_json(metadata_path, expected)

    for task_id in tasks:
        output = output_dir / f"{task_id}.jsonl"
        if output.exists():
            if run_runnable_openai.has_completed_footer(output):
                print(
                    json.dumps({"event": "task_skipped", "task_id": task_id}),
                    flush=True,
                )
                continue
            raise SuiteConfigurationError(
                f"incomplete result blocks safe resume: {output.name}"
            )
        print(
            json.dumps({"event": "task_started", "task_id": task_id}),
            flush=True,
        )
        await run_task(
            model=model,
            output=output,
            sdk_version=sdk_version,
            task_id=task_id,
            acceptance_timeout=acceptance_timeout,
            model_timeout=model_timeout,
            case_timeout=case_timeout,
            provider_label=provider_label,
        )
        print(
            json.dumps({"event": "task_completed", "task_id": task_id}),
            flush=True,
        )

    aggregate = build_aggregate(output_dir, tasks)
    aggregate.update(
        {
            "completed_at": _utcnow(),
            "requested_model": model,
            "provider": provider_label,
        }
    )
    _write_json(output_dir / "aggregate.json", aggregate)
    completed = {**expected, "status": "completed", "completed_at": _utcnow()}
    _write_json(metadata_path, completed)
    return aggregate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--provider-label", default="openai")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--task-set",
        choices=("all", "expanded", "pilots"),
        default="all",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        choices=ALL_TASKS,
        help="repeat to override --task-set with an explicit subset",
    )
    parser.add_argument(
        "--model-timeout",
        type=float,
        default=run_runnable_openai.DEFAULT_MODEL_TIMEOUT,
    )
    parser.add_argument(
        "--case-timeout",
        type=float,
        default=run_runnable_openai.DEFAULT_CASE_TIMEOUT,
    )
    parser.add_argument(
        "--acceptance-timeout",
        type=float,
        default=30.0,
    )
    return parser


def _selected_tasks(arguments: argparse.Namespace) -> tuple[str, ...]:
    if arguments.task_id:
        return tuple(arguments.task_id)
    return {
        "all": ALL_TASKS,
        "expanded": EXPANDED_TASKS,
        "pilots": PILOT_TASKS,
    }[arguments.task_set]


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    tasks = _selected_tasks(arguments)
    if not arguments.run:
        print(json.dumps({"status": "not_run", "tasks": list(tasks)}, sort_keys=True))
        return 0
    if arguments.model is None or not arguments.model.strip():
        print("--run requires --model MODEL", file=sys.stderr)
        return 2
    if arguments.output_dir is None:
        print("--run requires --output-dir DIRECTORY", file=sys.stderr)
        return 2
    try:
        sdk_version = run_runnable_openai._preflight_openai()
        asyncio.run(
            run_suite(
                model=arguments.model.strip(),
                provider_label=arguments.provider_label.strip(),
                sdk_version=sdk_version,
                output_dir=arguments.output_dir,
                tasks=tasks,
                model_timeout=arguments.model_timeout,
                case_timeout=arguments.case_timeout,
                acceptance_timeout=arguments.acceptance_timeout,
                resume=arguments.resume,
            )
        )
    except (
        FileExistsError,
        OSError,
        SuiteConfigurationError,
        run_runnable_openai.RunnableConfigurationError,
        run_runnable_openai.RunnableFatalProviderError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
