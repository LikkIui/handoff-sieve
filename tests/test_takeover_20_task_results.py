from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.takeover.run_runnable_suite import build_aggregate

RESULTS = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "takeover"
    / "results"
    / "2026-10-01-gpt-5.6-sol-20-task"
)

TASKS = (
    "rc01_composite_cursor",
    "rc02_retry_after",
    "rc03_customer_csv",
    "rc04_config_precedence",
    "rc05_json_merge_patch",
    "rc06_http_cache_key",
    "rc07_refresh_rotation",
    "pe01_streaming_csv",
    "pe02_cli_color",
    "pe03_timezone_migration",
    "pe04_package_template",
    "pe05_batch_checkpoint",
    "pe06_cleanup_dry_run",
    "pe07_file_manifest",
    "rr01_cursor_review",
    "rr02_falsy_config_review",
    "rr03_retry_after_review",
    "rr04_csv_splitter_review",
    "rr05_package_data_review",
    "rr06_checkpoint_review",
)


def _rows(task_id: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (RESULTS / f"{task_id}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def test_twenty_task_aggregate_is_derived_from_exact_records() -> None:
    published = json.loads((RESULTS / "aggregate.json").read_text(encoding="utf-8"))
    rebuilt = build_aggregate(RESULTS, TASKS)

    assert len(list(RESULTS.glob("*.jsonl"))) == 20
    assert published["tasks"] == rebuilt["tasks"]
    assert published["aggregate"] == rebuilt["aggregate"]
    assert published["aggregate"] == {
        "full_history": {
            "successes": 18,
            "tasks": 20,
            "handoff_tokens": 15025,
            "provider_input_tokens": 17182,
            "provider_output_tokens": 21139,
            "provider_total_tokens": 38321,
            "model_calls": 20,
        },
        "naive_summary": {
            "successes": 17,
            "tasks": 20,
            "handoff_tokens": 7402,
            "provider_input_tokens": 30391,
            "provider_output_tokens": 25205,
            "provider_total_tokens": 55596,
            "model_calls": 40,
        },
        "handoff_sieve": {
            "successes": 18,
            "tasks": 20,
            "handoff_tokens": 8177,
            "provider_input_tokens": 12679,
            "provider_output_tokens": 16078,
            "provider_total_tokens": 28757,
            "model_calls": 20,
        },
    }
    assert published["handoff_sieve_reduction_vs_full_history_percent"] == {
        "handoff_tokens": 45.6,
        "provider_total_tokens": 25.0,
    }


def test_provider_errors_stay_in_the_denominator() -> None:
    failures = []
    for task_id in TASKS:
        failures.extend(
            (task_id, row["condition"], row["error"])
            for row in _rows(task_id)
            if row.get("kind") == "observation"
            and row.get("status") == "provider_error"
        )

    assert failures == [
        ("rc07_refresh_rotation", "full_history", "provider_error:model_timeout"),
        (
            "pe03_timezone_migration",
            "naive_summary",
            "provider_error:model_timeout",
        ),
        ("pe07_file_manifest", "handoff_sieve", "provider_error:model_timeout"),
    ]


def test_validator_corrections_preserve_original_grading() -> None:
    corrected = []
    for task_id in TASKS:
        corrected.extend(
            (task_id, row)
            for row in _rows(task_id)
            if row.get("grading_revision") == "taskpack-validator-2026-10-01"
        )

    assert len(corrected) == 9
    assert {task_id for task_id, _ in corrected} == {
        "pe04_package_template",
        "rr02_falsy_config_review",
        "rr04_csv_splitter_review",
    }
    for _, row in corrected:
        assert row["downstream_success"] is True
        assert row["original_grading"]["downstream_success"] is False
        assert row["regraded_at"]
        assert all(check["passed"] for check in row["checks"])
