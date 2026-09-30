"""Small framework-neutral report endpoint used by the PE-01 fixture."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

JSON_CONTENT_TYPE = "application/json; charset=utf-8"


class ReportService(Protocol):
    """Existing service boundary supplied to the endpoint."""

    def iter_rows(self) -> Iterable[Mapping[str, object]]:
        """Return report rows in service-defined order."""


@dataclass(frozen=True, slots=True)
class ReportResponse:
    """Minimal response value whose body may be streamed."""

    content_type: str
    body: Iterable[bytes]
    streaming: bool

    def read(self) -> bytes:
        """Consume the response body for a transport or a test."""

        return b"".join(self.body)


def _json_response(rows: Iterable[Mapping[str, object]]) -> ReportResponse:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ReportResponse(
        content_type=JSON_CONTENT_TYPE,
        body=(payload,),
        streaming=False,
    )


def get_reports(
    service: ReportService,
    *,
    format: str | None = None,
) -> ReportResponse:
    """Return the existing JSON report or the planned streaming CSV report."""

    selected_format = "json" if format is None else format
    rows = service.iter_rows()
    if selected_format == "json":
        return _json_response(rows)
    if selected_format == "csv":
        # Import and connect the existing ``stream_csv`` helper without
        # consuming rows here. The response body itself must remain lazy.
        raise NotImplementedError
    raise ValueError("unsupported report format")
