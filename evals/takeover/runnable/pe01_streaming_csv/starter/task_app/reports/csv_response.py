"""Streaming CSV serialization to be completed by the receiving agent."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

CSV_COLUMNS = ("id", "name", "total")
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


def stream_csv(rows: Iterable[Mapping[str, object]]) -> Iterator[bytes]:
    """Yield a UTF-8 CSV header and rows without materializing ``rows``."""

    raise NotImplementedError
