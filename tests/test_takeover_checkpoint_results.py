from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RESULTS = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "takeover"
    / "results"
    / "2026-09-30-gpt-5.6-sol"
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _usage_total(row: dict[str, Any], field: str, metric: str) -> int:
    usage = row.get(field)
    return usage[metric] if isinstance(usage, dict) else 0


def test_real_provider_checkpoint_aggregate_matches_raw_records() -> None:
    aggregate = json.loads((RESULTS / "aggregate.json").read_text(encoding="utf-8"))
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
        for condition in ("full_history", "naive_summary", "handoff_sieve")
    }

    for task in aggregate["tasks"]:
        rows = _read_jsonl(RESULTS / f"{task['task_id']}.jsonl")
        assert rows[0]["kind"] == "run_started"
        assert rows[0]["requested_model"] == aggregate["requested_model"]
        assert rows[0]["model_timeout_seconds"] == 180.0
        assert rows[0]["case_timeout_seconds"] == 190.0
        assert rows[-1]["kind"] == "run_completed"
        assert rows[-1]["records_written"] == 3

        observations = {row["condition"]: row for row in rows[1:-1]}
        assert set(observations) == set(totals)
        for condition, expected in task["conditions"].items():
            row = observations[condition]
            measured_provider_tokens = _usage_total(
                row, "provider_usage", "total_tokens"
            ) + _usage_total(
                row,
                "naive_summary_preparation_usage",
                "total_tokens",
            )
            assert row["downstream_success"] is expected["success"]
            assert (
                sum(check["passed"] for check in row["checks"])
                == expected["checks_passed"]
            )
            assert row["local_handoff_token_estimate"] == expected["handoff_tokens"]
            assert measured_provider_tokens == expected["provider_tokens"]
            assert row["event_count"] == expected["model_calls"]

            current = totals[condition]
            current["successes"] += int(row["downstream_success"])
            current["tasks"] += 1
            current["handoff_tokens"] += row["local_handoff_token_estimate"]
            current["provider_input_tokens"] += _usage_total(
                row, "provider_usage", "input_tokens"
            ) + _usage_total(
                row,
                "naive_summary_preparation_usage",
                "input_tokens",
            )
            current["provider_output_tokens"] += _usage_total(
                row, "provider_usage", "output_tokens"
            ) + _usage_total(
                row,
                "naive_summary_preparation_usage",
                "output_tokens",
            )
            current["provider_total_tokens"] += measured_provider_tokens
            current["model_calls"] += row["event_count"]

    assert totals == aggregate["aggregate"]
