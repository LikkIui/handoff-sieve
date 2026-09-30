"""Re-run host-side acceptance on saved runnable provider outputs.

This never calls a provider. It writes new JSONL files and records the original
grading whenever a corrected validator changes a saved observation.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.takeover import run_runnable_openai


class RegradeError(RuntimeError):
    """Raised when a saved result cannot be regraded without ambiguity."""


def _acceptance(
    spec: run_runnable_openai.RunnableSpec,
    raw_output: str,
    *,
    timeout: float,
) -> tuple[run_runnable_openai.AcceptanceExecution, int | None, int]:
    try:
        if spec.kind == "single_source":
            source = run_runnable_openai.parse_candidate_source(raw_output)
            result = run_runnable_openai.run_candidate_acceptance(
                source,
                timeout=timeout,
            )
            candidate_source_bytes: int | None = len(source.encode("utf-8"))
            submission_bytes = len(source.encode("utf-8"))
        elif spec.kind == "multi_source":
            sources = run_runnable_openai.parse_pe01_sources(raw_output)
            result = run_runnable_openai.run_pe01_acceptance(
                sources,
                timeout=timeout,
            )
            candidate_source_bytes = sum(
                len(source.encode("utf-8")) for source in sources
            )
            submission_bytes = candidate_source_bytes
        elif spec.kind == "review":
            review = run_runnable_openai.parse_review_submission(raw_output)
            result = run_runnable_openai.run_rr01_acceptance(
                review,
                timeout=timeout,
            )
            candidate_source_bytes = None
            submission_bytes = len(raw_output.encode("utf-8"))
        elif spec.kind == "taskpack_source":
            files = run_runnable_openai.parse_taskpack_sources(spec, raw_output)
            result = run_runnable_openai.run_taskpack_acceptance(
                spec,
                files,
                timeout=timeout,
            )
            candidate_source_bytes = sum(
                len(source.encode("utf-8")) for source in files.values()
            )
            submission_bytes = candidate_source_bytes
        else:
            review = run_runnable_openai.parse_review_submission(raw_output)
            result = run_runnable_openai.run_taskpack_acceptance(
                spec,
                review,
                timeout=timeout,
            )
            candidate_source_bytes = None
            submission_bytes = len(raw_output.encode("utf-8"))
    except run_runnable_openai.CandidateOutputError as error:
        raise RegradeError("saved completed output no longer parses") from error
    return result, candidate_source_bytes, submission_bytes


def _grading_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": row.get("status"),
        "downstream_success": row.get("downstream_success"),
        "submission_bytes": row.get("submission_bytes"),
        "candidate_source_bytes": row.get("candidate_source_bytes"),
        "derived_blocking_issue_ids": row.get("derived_blocking_issue_ids"),
        "checks": row.get("checks"),
        "error": row.get("error"),
    }


def regrade_result_file(
    source: Path,
    destination: Path,
    *,
    timeout: float = 30.0,
    regraded_at: str | None = None,
) -> int:
    """Write one regraded copy and return the number of corrected observations."""

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
    except (OSError, json.JSONDecodeError) as error:
        raise RegradeError(f"invalid result file: {source}") from error
    if not run_runnable_openai.has_completed_footer(source):
        raise RegradeError(f"result file is incomplete: {source}")
    task_id = rows[0].get("task_id")
    if not isinstance(task_id, str) or task_id not in run_runnable_openai._SPECS:
        raise RegradeError(f"result has unknown task id: {source}")
    spec = run_runnable_openai._SPECS[task_id]
    timestamp = regraded_at or datetime.now(timezone.utc).isoformat()
    changed = 0
    for row in rows[1:-1]:
        if row.get("kind") != "observation" or row.get("status") != "completed":
            continue
        raw_output = row.get("raw_output")
        if not isinstance(raw_output, str):
            raise RegradeError("completed observation has no raw output")
        before = _grading_snapshot(row)
        acceptance, source_bytes, submission_bytes = _acceptance(
            spec,
            raw_output,
            timeout=timeout,
        )
        row.update(
            {
                "status": (
                    "completed" if acceptance.error is None else "acceptance_error"
                ),
                "downstream_success": acceptance.overall,
                "submission_bytes": submission_bytes,
                "candidate_source_bytes": source_bytes,
                "derived_blocking_issue_ids": (
                    list(acceptance.derived_blocking_issue_ids)
                    if acceptance.derived_blocking_issue_ids is not None
                    else None
                ),
                "checks": list(acceptance.checks),
                "error": acceptance.error,
            }
        )
        after = _grading_snapshot(row)
        if after != before:
            row["original_grading"] = before
            row["regraded_at"] = timestamp
            row["grading_revision"] = "taskpack-validator-2026-10-01"
            changed += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    if changed == 0:
        shutil.copyfile(source, destination)
    else:
        destination.write_text(
            "".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
                for row in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
    return changed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if len({source.name for source in arguments.source}) != len(arguments.source):
        raise RegradeError("source filenames must be unique")
    corrected = 0
    for source in arguments.source:
        corrected += regrade_result_file(
            source,
            arguments.output_dir / source.name,
            timeout=arguments.timeout,
        )
    print(json.dumps({"files": len(arguments.source), "corrected": corrected}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
