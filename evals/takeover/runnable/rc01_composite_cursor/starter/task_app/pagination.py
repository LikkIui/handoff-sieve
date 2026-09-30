"""Activity-feed pagination API to be completed by the receiving agent."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One activity-feed row."""

    created_at: datetime
    id: str
    payload: Any = None


def encode_cursor(row: ActivityRow) -> str:
    """Return an opaque cursor representing ``row``'s pagination key."""

    raise NotImplementedError


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor or raise ``ValueError`` when it is malformed."""

    raise NotImplementedError


def page_after(
    rows: Sequence[ActivityRow],
    cursor: str | None,
    limit: int,
) -> tuple[list[ActivityRow], str | None]:
    """Return the next ascending page and a cursor when more rows remain.

    The returned cursor is ``None`` on the final page. The function must not
    mutate ``rows`` or any row payload. A malformed non-``None`` cursor raises
    ``ValueError``.
    """

    raise NotImplementedError
