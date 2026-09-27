"""Safe audit report exporters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Protocol

from relayguard.report import AuditReport


class AuditReporter(Protocol):
    """Receive completed audit reports without access to handoff content."""

    def emit(self, report: AuditReport) -> None:
        """Persist or forward one completed report."""


class CallbackReporter:
    """Send an isolated report copy to an application callback."""

    def __init__(self, callback: Callable[[AuditReport], None]) -> None:
        self.callback = callback

    def emit(self, report: AuditReport) -> None:
        self.callback(report.model_copy(deep=True))


class JsonlReporter:
    """Append one versioned audit report per line to a UTF-8 JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def emit(self, report: AuditReport) -> None:
        if not self.path.parent.is_dir():
            raise FileNotFoundError(
                f"Audit report directory does not exist: {self.path.parent}"
            )
        record = report.model_dump_json() + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(record)
