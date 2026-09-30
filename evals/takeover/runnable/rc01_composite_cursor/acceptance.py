"""Hidden host-side acceptance checks for the runnable RC-01 fixture.

This module loads a receiver workspace but is never part of that workspace.
Running these checks locally does not create or imply a provider result.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

CHECK_IDS = (
    "cursor_round_trip",
    "malformed_cursor",
    "page_size_1",
    "page_size_7",
    "page_size_13",
    "terminal_page",
    "input_immutability",
)


@dataclass(frozen=True)
class AcceptanceCheck:
    """One host-side behavioral check."""

    id: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class AcceptanceReport:
    """Conjunction of every RC-01 behavioral check."""

    checks: tuple[AcceptanceCheck, ...]

    @property
    def overall(self) -> bool:
        """Return true only when every check passes."""

        return bool(self.checks) and all(check.passed for check in self.checks)


class _AcceptanceFailure(AssertionError):
    """Internal assertion with a stable host-side failure message."""


def _load_candidate(workspace: Path) -> tuple[ModuleType, str]:
    module_path = workspace.resolve() / "task_app" / "pagination.py"
    if not module_path.is_file():
        raise _AcceptanceFailure(f"candidate module is missing: {module_path}")

    module_name = f"_handoff_sieve_rc01_candidate_{uuid4().hex}"
    module = ModuleType(module_name)
    module.__file__ = str(module_path)
    sys.modules[module_name] = module
    try:
        source = module_path.read_bytes()
        exec(compile(source, str(module_path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module, module_name


def _rows(module: ModuleType) -> list[Any]:
    base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
    rows = [
        module.ActivityRow(
            created_at=base + timedelta(minutes=index // 3),
            # The id permutation prevents an implementation from passing by
            # ordering on id alone while preserving deterministic tie groups.
            id=f"evt-{(index * 17) % 50:03d}",
            payload={"position": index, "label": f"row-{index}"},
        )
        for index in range(50)
    ]
    # The implementation must establish the public ordering without changing
    # the caller-owned sequence.
    return list(reversed(rows[::2])) + list(reversed(rows[1::2]))


def _row_key(row: Any) -> tuple[datetime, str]:
    return row.created_at, row.id


def _snapshot(rows: list[Any]) -> list[tuple[datetime, str, object]]:
    return [(row.created_at, row.id, deepcopy(row.payload)) for row in rows]


def _assert_cursor_round_trip(module: ModuleType) -> None:
    row = module.ActivityRow(
        created_at=datetime(2026, 4, 12, 9, 7, 3, tzinfo=timezone.utc),
        id="evt-unicode-δ",
        payload={"ignored": True},
    )
    cursor = module.encode_cursor(row)
    if not isinstance(cursor, str) or not cursor:
        raise _AcceptanceFailure("encode_cursor must return a non-empty string")
    decoded = module.decode_cursor(cursor)
    if decoded != (row.created_at, row.id):
        raise _AcceptanceFailure("cursor round-trip changed its pagination key")


def _assert_malformed_cursor(module: ModuleType) -> None:
    rows = _rows(module)
    for malformed in ("", "not-a-cursor", "%%%"):
        try:
            module.decode_cursor(malformed)
        except ValueError:
            pass
        else:
            raise _AcceptanceFailure("decode_cursor accepted malformed input")

        try:
            module.page_after(rows, malformed, 7)
        except ValueError:
            pass
        else:
            raise _AcceptanceFailure("page_after accepted a malformed cursor")


def _assert_complete_pagination(module: ModuleType, page_size: int) -> None:
    rows = _rows(module)
    before = _snapshot(rows)
    expected = sorted(rows, key=_row_key)
    received: list[Any] = []
    cursor: str | None = None
    max_pages = len(rows) + 1

    for _ in range(max_pages):
        page, next_cursor = module.page_after(rows, cursor, page_size)
        if not isinstance(page, list):
            raise _AcceptanceFailure("page_after must return each page as a list")
        if not page:
            raise _AcceptanceFailure("page_after returned an empty intermediate page")
        if len(page) > page_size:
            raise _AcceptanceFailure("page_after exceeded the requested page size")

        received.extend(page)
        if len({_row_key(row) for row in received}) != len(received):
            raise _AcceptanceFailure("pagination returned a duplicate row")

        if next_cursor is None:
            break
        if len(page) != page_size:
            raise _AcceptanceFailure("a non-final page was not filled to the limit")
        if not isinstance(next_cursor, str) or not next_cursor:
            raise _AcceptanceFailure("a non-final page returned an invalid cursor")
        if module.decode_cursor(next_cursor) != _row_key(page[-1]):
            raise _AcceptanceFailure("next cursor does not represent the page boundary")
        cursor = next_cursor
    else:
        raise _AcceptanceFailure("pagination did not terminate")

    if _snapshot(received) != _snapshot(expected):
        raise _AcceptanceFailure("pagination omitted, duplicated, or reordered rows")
    if _snapshot(rows) != before:
        raise _AcceptanceFailure("pagination mutated its input rows")


def _assert_terminal_page(module: ModuleType) -> None:
    rows = _rows(module)
    expected = sorted(rows, key=_row_key)
    last_cursor = module.encode_cursor(expected[-1])
    page, next_cursor = module.page_after(rows, last_cursor, 7)
    if page != [] or next_cursor is not None:
        raise _AcceptanceFailure("a cursor at the final row must return ([], None)")

    empty_page, empty_cursor = module.page_after([], None, 7)
    if empty_page != [] or empty_cursor is not None:
        raise _AcceptanceFailure("an empty source must return ([], None)")


def _assert_input_immutability(module: ModuleType) -> None:
    rows = _rows(module)
    before = _snapshot(rows)
    module.page_after(rows, None, 7)
    if _snapshot(rows) != before:
        raise _AcceptanceFailure("pagination mutated its input rows")


def _run_check(check_id: str, check: Callable[[], None]) -> AcceptanceCheck:
    try:
        check()
    except Exception as exc:
        return AcceptanceCheck(
            id=check_id,
            passed=False,
            detail=f"{type(exc).__name__}: {exc}",
        )
    return AcceptanceCheck(id=check_id, passed=True)


def run_acceptance(workspace: str | Path) -> AcceptanceReport:
    """Load one receiver workspace and execute every offline check."""

    try:
        module, module_name = _load_candidate(Path(workspace))
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return AcceptanceReport(
            checks=tuple(
                AcceptanceCheck(id=check_id, passed=False, detail=detail)
                for check_id in CHECK_IDS
            )
        )

    try:
        checks = (
            _run_check("cursor_round_trip", lambda: _assert_cursor_round_trip(module)),
            _run_check("malformed_cursor", lambda: _assert_malformed_cursor(module)),
            _run_check(
                "page_size_1",
                lambda: _assert_complete_pagination(module, 1),
            ),
            _run_check(
                "page_size_7",
                lambda: _assert_complete_pagination(module, 7),
            ),
            _run_check(
                "page_size_13",
                lambda: _assert_complete_pagination(module, 13),
            ),
            _run_check("terminal_page", lambda: _assert_terminal_page(module)),
            _run_check(
                "input_immutability",
                lambda: _assert_input_immutability(module),
            ),
        )
        return AcceptanceReport(checks=checks)
    finally:
        sys.modules.pop(module_name, None)


def _report_payload(report: AcceptanceReport) -> dict[str, object]:
    return {
        "overall": report.overall,
        "checks": [
            {
                "id": check.id,
                "passed": check.passed,
                "detail": check.detail,
            }
            for check in report.checks
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Run the hidden checks for a host-selected workspace and emit JSON.

    The runnable provider driver invokes this CLI in a separate, time-bounded
    process. That boundary contains crashes and global Python state; it is not
    a security sandbox and does not prevent candidate code from using the
    process's filesystem or network permissions.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args(argv)

    # Candidate modules sometimes print while importing. Keep stdout reserved
    # for the single machine-readable report consumed by the host runner.
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        report = run_acceptance(arguments.workspace)
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
