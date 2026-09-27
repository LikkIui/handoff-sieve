from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.run import (
    README_PATH,
    RESULTS_PATH,
    load_fixture,
    render_readme_table,
    run_benchmark,
    stable_projection,
)


def test_fixed_benchmark_meets_all_acceptance_gates() -> None:
    result = run_benchmark()

    assert result["acceptance"]["passed"] is True
    assert result["acceptance"]["failed_checks"] == []
    assert result["metrics"]["source_secret_recall_percent"] == 100.0
    assert result["metrics"]["receiver_secret_leaks"] == 0
    assert result["metrics"]["audit_secret_leaks"] == 0
    assert result["metrics"]["estimated_net_tokens_saved"] > 0
    assert result["writer_output"]["status"] == "passed"
    assert all(case["passed"] for case in result["failure_cases"])


def test_checked_in_benchmark_result_and_readme_are_current() -> None:
    current = run_benchmark()
    reference = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    assert stable_projection(current) == stable_projection(reference)
    assert render_readme_table(reference) in README_PATH.read_text(encoding="utf-8")


def test_fixture_cannot_claim_vacuous_recall(tmp_path: Path) -> None:
    fixture = load_fixture()
    fixture["secrets"] = []
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be empty"):
        load_fixture(path)


def test_determinism_gate_requires_repeated_runs() -> None:
    with pytest.raises(ValueError, match="at least two"):
        run_benchmark(runs=1)
