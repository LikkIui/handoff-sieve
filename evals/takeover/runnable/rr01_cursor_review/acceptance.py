"""Hidden behavioral oracle for the runnable RR-01 review fixture."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from uuid import uuid4

REGISTERED_ISSUE_IDS = (
    "cursor_tie_skip",
    "inclusive_duplicate",
    "malformed_cursor_accepted",
    "input_mutated",
)
CHECK_IDS = (
    "reviews_active_candidate",
    "verdict_matches_probe",
    "blocker_set_matches_probe",
)
MAX_REVIEW_BYTES = 65_536


@dataclass(frozen=True)
class ReviewSubmission:
    """Strict receiver output accepted by the host grader."""

    candidate_id: str
    verdict: Literal["approve", "request_changes"]
    blocking_issue_ids: tuple[str, ...]


@dataclass(frozen=True)
class AcceptanceCheck:
    """One host-side review check."""

    id: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class AcceptanceReport:
    """Behavior-derived RR-01 review report."""

    derived_blocking_issue_ids: tuple[str, ...]
    checks: tuple[AcceptanceCheck, ...]

    @property
    def overall(self) -> bool:
        """Return true only when all review checks pass."""

        return bool(self.checks) and all(check.passed for check in self.checks)


class _ProbeFailure(RuntimeError):
    """The fixed candidate could not be probed deterministically."""


def _load_candidate(workspace: Path) -> tuple[ModuleType, str]:
    candidate_path = workspace.resolve() / "task_app" / "pagination.py"
    if not candidate_path.is_file():
        raise _ProbeFailure(f"candidate module is missing: {candidate_path}")
    module_name = f"_handoff_sieve_rr01_candidate_{uuid4().hex}"
    module = ModuleType(module_name)
    module.__file__ = str(candidate_path)
    sys.modules[module_name] = module
    try:
        source = candidate_path.read_bytes()
        exec(compile(source, str(candidate_path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module, module_name


def _rows(module: ModuleType) -> list[Any]:
    base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
    return [
        module.ActivityRow(base, "evt-009", {"position": 3}),
        module.ActivityRow(base + timedelta(minutes=1), "evt-010", {"position": 4}),
        module.ActivityRow(base, "evt-002", {"position": 1}),
        module.ActivityRow(base, "evt-004", {"position": 2}),
    ]


def _snapshot(rows: list[Any]) -> list[tuple[datetime, str, object]]:
    return [(row.created_at, row.id, deepcopy(row.payload)) for row in rows]


def _paginate(module: ModuleType, rows: list[Any]) -> list[str]:
    received: list[str] = []
    cursor: str | None = None
    for _ in range(len(rows) + 2):
        page, cursor = module.page_after(rows, cursor, 1)
        received.extend(row.id for row in page)
        if cursor is None:
            return received
    raise _ProbeFailure("candidate pagination did not terminate")


def derive_blocking_issue_ids(workspace: Path) -> tuple[str, ...]:
    """Execute the active candidate and derive its registered blocker set."""

    module, module_name = _load_candidate(workspace)
    blockers: set[str] = set()
    try:
        rows = _rows(module)
        before = _snapshot(rows)
        received = _paginate(module, rows)
        expected = [
            row.id for row in sorted(rows, key=lambda row: (row.created_at, row.id))
        ]
        if len(received) != len(set(received)):
            blockers.add("inclusive_duplicate")
        if set(expected) - set(received):
            blockers.add("cursor_tie_skip")
        try:
            module.page_after(rows, "not-a-cursor", 1)
        except ValueError:
            pass
        else:
            blockers.add("malformed_cursor_accepted")
        if _snapshot(rows) != before:
            blockers.add("input_mutated")
    finally:
        sys.modules.pop(module_name, None)
    return tuple(issue for issue in REGISTERED_ISSUE_IDS if issue in blockers)


def run_acceptance(workspace: Path, review: ReviewSubmission) -> AcceptanceReport:
    """Grade one review against blockers derived from candidate behavior."""

    blockers = derive_blocking_issue_ids(workspace)
    expected_verdict = "request_changes" if blockers else "approve"
    submitted_blockers = review.blocking_issue_ids
    registered_and_unique = len(submitted_blockers) == len(
        set(submitted_blockers)
    ) and all(issue in REGISTERED_ISSUE_IDS for issue in submitted_blockers)
    checks = (
        AcceptanceCheck(
            id="reviews_active_candidate",
            passed=review.candidate_id == "cursor_patch_v3",
        ),
        AcceptanceCheck(
            id="verdict_matches_probe",
            passed=review.verdict == expected_verdict,
        ),
        AcceptanceCheck(
            id="blocker_set_matches_probe",
            passed=registered_and_unique and set(submitted_blockers) == set(blockers),
        ),
    )
    return AcceptanceReport(derived_blocking_issue_ids=blockers, checks=checks)


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate review field")
        result[key] = value
    return result


def load_review(path: Path) -> ReviewSubmission:
    """Load the strict reviewer JSON written by the host runner."""

    raw = path.read_bytes()
    if len(raw) > MAX_REVIEW_BYTES:
        raise ValueError("review exceeds byte limit")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("review must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "candidate_id",
        "verdict",
        "blocking_issue_ids",
    }:
        raise ValueError("review has an invalid shape")
    candidate_id = payload["candidate_id"]
    verdict = payload["verdict"]
    blockers = payload["blocking_issue_ids"]
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a non-empty string")
    if verdict not in {"approve", "request_changes"}:
        raise ValueError("verdict is invalid")
    if (
        not isinstance(blockers, list)
        or len(blockers) > len(REGISTERED_ISSUE_IDS)
        or not all(isinstance(issue, str) and issue for issue in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise ValueError("blocking_issue_ids is invalid")
    return ReviewSubmission(
        candidate_id=candidate_id,
        verdict=verdict,
        blocking_issue_ids=tuple(blockers),
    )


def _report_payload(report: AcceptanceReport) -> dict[str, object]:
    return {
        "overall": report.overall,
        "derived_blocking_issue_ids": list(report.derived_blocking_issue_ids),
        "checks": [
            {"id": check.id, "passed": check.passed, "detail": check.detail}
            for check in report.checks
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Emit one strict JSON report for a host-selected candidate and review.

    The caller should apply a subprocess timeout. This process boundary
    contains crashes and Python state; it is not a security sandbox.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        review = load_review(arguments.review)
    except (OSError, ValueError):
        return 2
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        report = run_acceptance(arguments.workspace, review)
    print(
        json.dumps(
            _report_payload(report),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
