from __future__ import annotations

import shutil
from pathlib import Path

from evals.takeover.runnable.pe01_streaming_csv.acceptance import run_acceptance

FIXTURE_ROOT = (
    Path(__file__).parents[1] / "evals" / "takeover" / "runnable" / "pe01_streaming_csv"
)
STARTER = FIXTURE_ROOT / "starter"
EXPECTED_CHECK_IDS = {
    "csv_normal",
    "csv_empty",
    "csv_unicode_quoting",
    "lazy_single_pass",
    "json_default_snapshot",
    "json_explicit_snapshot",
    "unsupported_format",
    "input_immutability",
}

CSV_RESPONSE_IMPLEMENTATION = '''\
"""Test-only reference streaming serializer."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator, Mapping

CSV_COLUMNS = ("id", "name", "total")
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


def stream_csv(rows: Iterable[Mapping[str, object]]) -> Iterator[bytes]:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_COLUMNS,
        extrasaction="ignore",
        lineterminator="\\r\\n",
    )
    writer.writeheader()
    yield buffer.getvalue().encode("utf-8")
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow(row)
        yield buffer.getvalue().encode("utf-8")
'''

API_IMPLEMENTATION = '''\
"""Test-only reference endpoint behavior."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .csv_response import CSV_CONTENT_TYPE, stream_csv

JSON_CONTENT_TYPE = "application/json; charset=utf-8"


class ReportService(Protocol):
    def iter_rows(self) -> Iterable[Mapping[str, object]]: ...


@dataclass(frozen=True, slots=True)
class ReportResponse:
    content_type: str
    body: Iterable[bytes]
    streaming: bool

    def read(self) -> bytes:
        return b"".join(self.body)


def _json_response(rows: Iterable[Mapping[str, object]]) -> ReportResponse:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ReportResponse(JSON_CONTENT_TYPE, (payload,), False)


def get_reports(
    service: ReportService,
    *,
    format: str | None = None,
) -> ReportResponse:
    selected_format = "json" if format is None else format
    rows = service.iter_rows()
    if selected_format == "json":
        return _json_response(rows)
    if selected_format == "csv":
        return ReportResponse(CSV_CONTENT_TYPE, stream_csv(rows), True)
    raise ValueError("unsupported report format")
'''

EAGER_CSV_IMPLEMENTATION = CSV_RESPONSE_IMPLEMENTATION.replace(
    '    buffer = io.StringIO(newline="")\n',
    '    rows = list(rows)\n    buffer = io.StringIO(newline="")\n',
)


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
    reports = workspace / "task_app" / "reports"
    (reports / "csv_response.py").write_text(
        CSV_RESPONSE_IMPLEMENTATION,
        encoding="utf-8",
    )
    (reports / "api.py").write_text(API_IMPLEMENTATION, encoding="utf-8")

    report = run_acceptance(workspace)

    assert report.overall, report
    assert {check.id for check in report.checks} == EXPECTED_CHECK_IDS
    assert all(check.passed for check in report.checks)
    assert not (workspace / "acceptance.py").exists()
    assert not (workspace / "README.md").exists()


def test_hidden_acceptance_rejects_an_eager_csv_body(tmp_path: Path) -> None:
    workspace = tmp_path / "receiver-workspace"
    shutil.copytree(STARTER, workspace)
    reports = workspace / "task_app" / "reports"
    (reports / "csv_response.py").write_text(
        EAGER_CSV_IMPLEMENTATION,
        encoding="utf-8",
    )
    (reports / "api.py").write_text(API_IMPLEMENTATION, encoding="utf-8")

    report = run_acceptance(workspace)

    results = {check.id: check.passed for check in report.checks}
    assert not report.overall
    assert results["lazy_single_pass"] is False


def test_receiver_starter_does_not_contain_host_acceptance_or_solution() -> None:
    starter_files = {
        path.relative_to(STARTER).as_posix()
        for path in STARTER.rglob("*")
        if path.is_file() and path.suffix == ".py"
    }

    assert starter_files == {
        "task_app/__init__.py",
        "task_app/reports/__init__.py",
        "task_app/reports/api.py",
        "task_app/reports/csv_response.py",
    }
    api_source = (STARTER / "task_app" / "reports" / "api.py").read_text(
        encoding="utf-8"
    )
    csv_source = (STARTER / "task_app" / "reports" / "csv_response.py").read_text(
        encoding="utf-8"
    )
    assert api_source.count("raise NotImplementedError") == 1
    assert csv_source.count("raise NotImplementedError") == 1
