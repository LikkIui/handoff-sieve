from __future__ import annotations

from pathlib import Path

import pytest

from evals.takeover.runnable.rr01_cursor_review.acceptance import (
    CHECK_IDS,
    ReviewSubmission,
    derive_blocking_issue_ids,
    run_acceptance,
)

FIXTURE_ROOT = (
    Path(__file__).parents[1] / "evals" / "takeover" / "runnable" / "rr01_cursor_review"
)
STARTER = FIXTURE_ROOT / "starter"


def test_candidate_probe_derives_only_behavior_observed_blockers() -> None:
    assert derive_blocking_issue_ids(STARTER) == ("cursor_tie_skip",)


def test_behavior_derived_review_passes() -> None:
    report = run_acceptance(
        STARTER,
        ReviewSubmission(
            candidate_id="cursor_patch_v3",
            verdict="request_changes",
            blocking_issue_ids=("cursor_tie_skip",),
        ),
    )

    assert report.overall
    assert report.derived_blocking_issue_ids == ("cursor_tie_skip",)
    assert tuple(check.id for check in report.checks) == CHECK_IDS
    assert all(check.passed for check in report.checks)


@pytest.mark.parametrize(
    "review,failed_check",
    [
        (
            ReviewSubmission(
                "cursor_patch_v2", "request_changes", ("cursor_tie_skip",)
            ),
            "reviews_active_candidate",
        ),
        (
            ReviewSubmission("cursor_patch_v3", "approve", ("cursor_tie_skip",)),
            "verdict_matches_probe",
        ),
        (
            ReviewSubmission("cursor_patch_v3", "request_changes", ()),
            "blocker_set_matches_probe",
        ),
        (
            ReviewSubmission(
                "cursor_patch_v3",
                "request_changes",
                ("cursor_tie_skip", "inclusive_duplicate"),
            ),
            "blocker_set_matches_probe",
        ),
        (
            ReviewSubmission(
                "cursor_patch_v3",
                "request_changes",
                ("cursor_tie_skip", "cursor_tie_skip"),
            ),
            "blocker_set_matches_probe",
        ),
        (
            ReviewSubmission(
                "cursor_patch_v3",
                "request_changes",
                ("cursor_tie_skip", "invented_issue"),
            ),
            "blocker_set_matches_probe",
        ),
    ],
)
def test_incorrect_or_unsupported_review_fails(
    review: ReviewSubmission,
    failed_check: str,
) -> None:
    report = run_acceptance(STARTER, review)

    assert not report.overall
    result = {check.id: check.passed for check in report.checks}
    assert result[failed_check] is False


def test_receiver_starter_contains_candidate_but_not_hidden_oracle() -> None:
    starter_files = {
        path.relative_to(STARTER).as_posix()
        for path in STARTER.rglob("*")
        if path.is_file() and path.suffix == ".py"
    }
    assert starter_files == {"task_app/__init__.py", "task_app/pagination.py"}

    candidate = (STARTER / "task_app" / "pagination.py").read_text(encoding="utf-8")
    assert "cursor_patch_v3" in candidate
    assert "cursor_tie_skip" not in candidate
    assert "request_changes" not in candidate
