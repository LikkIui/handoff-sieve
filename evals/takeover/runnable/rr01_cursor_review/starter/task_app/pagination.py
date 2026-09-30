"""Active cursor_patch_v3 candidate supplied for review."""

from __future__ import annotations

import base64
import json
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
    """Encode an opaque activity cursor."""

    raw = json.dumps(
        [row.created_at.isoformat(), row.id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor, raising ``ValueError`` when malformed."""

    if not isinstance(cursor, str) or not cursor:
        raise ValueError("malformed cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
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
    except Exception as error:
        raise ValueError("malformed cursor") from error


def page_after(
    rows: Sequence[ActivityRow],
    cursor: str | None,
    limit: int,
) -> tuple[list[ActivityRow], str | None]:
    """Return the candidate's next ascending page."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be positive")
    boundary = decode_cursor(cursor) if cursor is not None else None
    ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
    if boundary is not None:
        ordered = [row for row in ordered if row.created_at > boundary[0]]
    page = ordered[:limit]
    next_cursor = encode_cursor(page[-1]) if page and len(ordered) > len(page) else None
    return page, next_cursor
