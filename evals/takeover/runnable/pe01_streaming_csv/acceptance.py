"""Hidden host-side acceptance checks for the runnable PE-01 fixture.

This module loads a receiver workspace but is never part of that workspace.
Running these checks locally does not create or imply a provider result.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(frozen=True)
class AcceptanceCheck:
    """One host-side behavioral check."""

    id: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class AcceptanceReport:
    """Conjunction of every PE-01 behavioral check."""

    checks: tuple[AcceptanceCheck, ...]

    @property
    def overall(self) -> bool:
        """Return true only when every check passes."""

        return bool(self.checks) and all(check.passed for check in self.checks)


class _AcceptanceFailure(AssertionError):
    """Internal assertion with a stable host-side failure message."""


class _Service:
    def __init__(self, rows: Iterable[Mapping[str, object]]) -> None:
        self._rows = rows
        self.calls = 0

    def iter_rows(self) -> Iterable[Mapping[str, object]]:
        self.calls += 1
        return self._rows


class _OnePassRows:
    """Iterable that exposes eager, repeated, and sized consumption."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.iterations = 0
        self.consumed = 0

    def __len__(self) -> int:
        raise _AcceptanceFailure("row source must not be sized")

    def __iter__(self) -> Iterator[Mapping[str, object]]:
        self.iterations += 1
        if self.iterations > 1:
            raise _AcceptanceFailure("row source was iterated more than once")
        for row in self._rows:
            self.consumed += 1
            yield row


def _purge_task_modules() -> None:
    for name in tuple(sys.modules):
        if name == "task_app" or name.startswith("task_app."):
            sys.modules.pop(name, None)


def _load_candidate(workspace: Path) -> ModuleType:
    package = workspace.resolve() / "task_app" / "reports" / "__init__.py"
    if not package.is_file():
        raise _AcceptanceFailure(f"candidate package is missing: {package}")
    _purge_task_modules()
    sys.path.insert(0, str(workspace.resolve()))
    previous_bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module("task_app.reports")
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
        sys.path.remove(str(workspace.resolve()))


def _assert_response(
    response: Any,
    *,
    content_type: str,
    streaming: bool,
    body: bytes,
) -> None:
    if response.content_type != content_type:
        raise _AcceptanceFailure("response content type changed")
    if response.streaming is not streaming:
        raise _AcceptanceFailure("response streaming marker is wrong")
    if response.read() != body:
        raise _AcceptanceFailure("response body changed")


def _assert_csv_normal(module: ModuleType) -> None:
    rows = [
        {"total": "3.50", "name": "Alpha", "id": "r1"},
        {"name": "Beta", "id": "r2", "total": "0"},
    ]
    service = _Service(iter(rows))
    response = module.get_reports(service, format="csv")
    if service.calls != 1:
        raise _AcceptanceFailure("iter_rows must be called exactly once")
    _assert_response(
        response,
        content_type="text/csv; charset=utf-8",
        streaming=True,
        body=b"id,name,total\r\nr1,Alpha,3.50\r\nr2,Beta,0\r\n",
    )


def _assert_csv_empty(module: ModuleType) -> None:
    response = module.get_reports(_Service(iter(())), format="csv")
    _assert_response(
        response,
        content_type="text/csv; charset=utf-8",
        streaming=True,
        body=b"id,name,total\r\n",
    )


def _assert_csv_unicode_and_quoting(module: ModuleType) -> None:
    rows = iter([{"id": "δ-1", "name": "Zoë, 王", "total": "12.50"}])
    response = module.get_reports(_Service(rows), format="csv")
    _assert_response(
        response,
        content_type="text/csv; charset=utf-8",
        streaming=True,
        body='id,name,total\r\nδ-1,"Zoë, 王",12.50\r\n'.encode(),
    )


def _assert_lazy_single_pass(module: ModuleType) -> None:
    rows = _OnePassRows(
        [
            {"id": f"r{index}", "name": f"row-{index}", "total": str(index)}
            for index in range(25)
        ]
    )
    service = _Service(rows)
    response = module.get_reports(service, format="csv")
    if service.calls != 1:
        raise _AcceptanceFailure("iter_rows must be called exactly once")
    if rows.consumed != 0:
        raise _AcceptanceFailure("CSV rows were consumed before the body was read")
    chunks = iter(response.body)
    try:
        first_chunk = next(chunks)
    except StopIteration as error:
        raise _AcceptanceFailure("CSV body emitted no header") from error
    if not isinstance(first_chunk, bytes):
        raise _AcceptanceFailure("CSV body chunks must be bytes")
    if rows.consumed == 25:
        raise _AcceptanceFailure("CSV rows were materialized before the first chunk")
    body = first_chunk + b"".join(chunks)
    if rows.iterations != 1 or rows.consumed != 25:
        raise _AcceptanceFailure("CSV body did not consume the row source once")
    if body.count(b"\r\n") != 26:
        raise _AcceptanceFailure("CSV stream did not emit every row")


_JSON_ROWS = [
    {"id": "r1", "name": "Alpha", "total": "3.50"},
    {"id": "r2", "name": "Zoë 王", "total": "0"},
]
_JSON_SNAPSHOT = (
    '[{"id":"r1","name":"Alpha","total":"3.50"},'
    '{"id":"r2","name":"Zoë 王","total":"0"}]'
).encode()


def _assert_json_snapshot(module: ModuleType, selected_format: str | None) -> None:
    service = _Service(iter(deepcopy(_JSON_ROWS)))
    response = module.get_reports(service, format=selected_format)
    if service.calls != 1:
        raise _AcceptanceFailure("iter_rows must be called exactly once")
    _assert_response(
        response,
        content_type="application/json; charset=utf-8",
        streaming=False,
        body=_JSON_SNAPSHOT,
    )


def _assert_json_default(module: ModuleType) -> None:
    _assert_json_snapshot(module, None)


def _assert_json_explicit(module: ModuleType) -> None:
    _assert_json_snapshot(module, "json")


def _assert_unsupported_format(module: ModuleType) -> None:
    try:
        module.get_reports(_Service(iter(())), format="xlsx")
    except ValueError:
        return
    raise _AcceptanceFailure("unsupported format must raise ValueError")


def _assert_input_immutability(module: ModuleType) -> None:
    rows = [{"id": "r1", "name": "mutable", "total": "9", "extra": [1, 2]}]
    before = deepcopy(rows)
    module.get_reports(_Service(iter(rows)), format="csv").read()
    if rows != before:
        raise _AcceptanceFailure("CSV serialization mutated caller-owned rows")


_CHECKS: tuple[tuple[str, Callable[[ModuleType], None]], ...] = (
    ("csv_normal", _assert_csv_normal),
    ("csv_empty", _assert_csv_empty),
    ("csv_unicode_quoting", _assert_csv_unicode_and_quoting),
    ("lazy_single_pass", _assert_lazy_single_pass),
    ("json_default_snapshot", _assert_json_default),
    ("json_explicit_snapshot", _assert_json_explicit),
    ("unsupported_format", _assert_unsupported_format),
    ("input_immutability", _assert_input_immutability),
)
CHECK_IDS = tuple(check_id for check_id, _ in _CHECKS)


def run_acceptance(workspace: Path) -> AcceptanceReport:
    """Run every PE-01 check against ``workspace`` without leaking an oracle."""

    try:
        module = _load_candidate(workspace)
    except (Exception, SystemExit) as error:
        detail = f"candidate_load_failed:{type(error).__name__}"
        return AcceptanceReport(
            checks=tuple(
                AcceptanceCheck(id=check_id, passed=False, detail=detail)
                for check_id, _ in _CHECKS
            )
        )

    checks: list[AcceptanceCheck] = []
    try:
        for check_id, check in _CHECKS:
            try:
                check(module)
            except (Exception, SystemExit) as error:
                checks.append(
                    AcceptanceCheck(
                        id=check_id,
                        passed=False,
                        detail=type(error).__name__,
                    )
                )
            else:
                checks.append(AcceptanceCheck(id=check_id, passed=True))
    finally:
        _purge_task_modules()
    return AcceptanceReport(checks=tuple(checks))


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
    """Emit one strict JSON report for a host-selected receiver workspace.

    A host runner should invoke this entry point in a separate process with a
    timeout. The process boundary contains Python state and candidate crashes;
    it is not a security sandbox and does not remove filesystem or network
    access from candidate code.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args(argv)

    # Candidate imports and checks may print. Reserve stdout for the one JSON
    # report and discard candidate output from both standard streams.
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
