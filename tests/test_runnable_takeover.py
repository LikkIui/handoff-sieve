from __future__ import annotations

import shutil
from pathlib import Path

from evals.takeover.runnable.rc01_composite_cursor.acceptance import (
    run_acceptance,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals" / "takeover" / "runnable" / "rc01_composite_cursor"
STARTER = FIXTURE / "starter"

REFERENCE_IMPLEMENTATION = '''\
"""Test-only reference used to prove that the hidden acceptance is satisfiable."""

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
    payload = json.dumps(
        [row.created_at.isoformat(), row.id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        if not isinstance(cursor, str) or not cursor:
            raise ValueError
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
            or not all(isinstance(item, str) for item in value)
            or not value[1]
        ):
            raise ValueError
        created_at = datetime.fromisoformat(value[0])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, value[1]
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise ValueError("malformed cursor") from None


def page_after(
    rows: Sequence[ActivityRow],
    cursor: str | None,
    limit: int,
) -> tuple[list[ActivityRow], str | None]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be positive")
    boundary = decode_cursor(cursor) if cursor is not None else None
    ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
    if boundary is not None:
        ordered = [
            row for row in ordered if (row.created_at, row.id) > boundary
        ]
    page = ordered[:limit]
    next_cursor = (
        encode_cursor(page[-1]) if page and len(ordered) > len(page) else None
    )
    return page, next_cursor
'''


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "receiver-workspace"
    shutil.copytree(STARTER, workspace)
    return workspace


def test_receiver_workspace_excludes_hidden_acceptance(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    assert (workspace / "task_app" / "pagination.py").is_file()
    assert not (workspace / "acceptance.py").exists()
    assert not any(path.name == "TASK_CATALOG.md" for path in workspace.rglob("*"))


def test_unimplemented_starter_fails_hidden_acceptance(tmp_path: Path) -> None:
    report = run_acceptance(_workspace(tmp_path))

    assert report.overall is False
    assert report.checks
    assert any(not check.passed for check in report.checks)


def test_hidden_acceptance_accepts_a_complete_implementation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "task_app" / "pagination.py").write_text(
        REFERENCE_IMPLEMENTATION,
        encoding="utf-8",
    )

    report = run_acceptance(workspace)

    assert report.overall is True
    assert [check.id for check in report.checks] == [
        "cursor_round_trip",
        "malformed_cursor",
        "page_size_1",
        "page_size_7",
        "page_size_13",
        "terminal_page",
        "input_immutability",
    ]
    assert all(check.detail is None for check in report.checks)
