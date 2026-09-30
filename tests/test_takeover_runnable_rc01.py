from __future__ import annotations

import shutil
from pathlib import Path

from evals.takeover.runnable.rc01_composite_cursor.acceptance import run_acceptance

FIXTURE_ROOT = (
    Path(__file__).parents[1]
    / "evals"
    / "takeover"
    / "runnable"
    / "rc01_composite_cursor"
)
STARTER = FIXTURE_ROOT / "starter"
EXPECTED_CHECK_IDS = {
    "cursor_round_trip",
    "malformed_cursor",
    "page_size_1",
    "page_size_7",
    "page_size_13",
    "terminal_page",
    "input_immutability",
}

REFERENCE_IMPLEMENTATION = '''\
"""Reference behavior written only into a temporary test workspace."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivityRow:
    created_at: datetime
    id: str
    payload: Any = None


def encode_cursor(row: ActivityRow) -> str:
    raw = json.dumps(
        [row.created_at.isoformat(), row.id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("malformed cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not isinstance(value[0], str)
            or not isinstance(value[1], str)
            or not value[1]
        ):
            raise ValueError
        created_at = datetime.fromisoformat(value[0])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, value[1]
    except Exception as exc:
        raise ValueError("malformed cursor") from exc


def page_after(
    rows: Sequence[ActivityRow],
    cursor: str | None,
    limit: int,
) -> tuple[list[ActivityRow], str | None]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    boundary = decode_cursor(cursor) if cursor is not None else None
    ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
    eligible = [
        row
        for row in ordered
        if boundary is None or (row.created_at, row.id) > boundary
    ]
    page = eligible[:limit]
    has_more = len(eligible) > len(page)
    next_cursor = encode_cursor(page[-1]) if page and has_more else None
    return page, next_cursor
'''


def test_starter_stub_fails_hidden_acceptance() -> None:
    report = run_acceptance(STARTER)

    assert not report.overall
    assert {check.id for check in report.checks} == EXPECTED_CHECK_IDS
    assert any(not check.passed for check in report.checks)


def test_reference_behavior_passes_only_from_a_temporary_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "receiver-workspace"
    shutil.copytree(STARTER, workspace)
    (workspace / "task_app" / "pagination.py").write_text(
        REFERENCE_IMPLEMENTATION,
        encoding="utf-8",
    )

    report = run_acceptance(workspace)

    assert report.overall, report
    assert {check.id for check in report.checks} == EXPECTED_CHECK_IDS
    assert all(check.passed for check in report.checks)
    assert not (workspace / "acceptance.py").exists()
    assert not (workspace / "README.md").exists()


def test_receiver_starter_does_not_contain_host_acceptance_or_solution() -> None:
    starter_files = {
        path.relative_to(STARTER).as_posix()
        for path in STARTER.rglob("*.py")
        if "__pycache__" not in path.parts
    }

    assert starter_files == {
        "task_app/__init__.py",
        "task_app/pagination.py",
    }
    pagination_source = (STARTER / "task_app" / "pagination.py").read_text(
        encoding="utf-8"
    )
    assert pagination_source.count("raise NotImplementedError") == 3
