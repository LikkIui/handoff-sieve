"""RelayGuard exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from relayguard.report import AuditReport


class RelayGuardError(Exception):
    """Base exception for RelayGuard failures."""

    def __init__(
        self,
        message: str,
        *,
        report: AuditReport | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report


class BudgetExceededError(RelayGuardError):
    """Raised when protected content cannot fit within a hard budget."""


class ConfigurationError(RelayGuardError):
    """Raised when a policy configuration is invalid."""


class UnmatchedRouteError(RelayGuardError):
    """Raised when a configured rule set has no matching handoff route."""


class AmbiguousRouteError(RelayGuardError):
    """Raised when multiple policy routes match without an explicit strategy."""


class ReservedFieldError(RelayGuardError):
    """Raised when untrusted input attempts to set internal processing state."""


class RedactionError(RelayGuardError):
    """Raised when redaction cannot complete within configured safety limits."""


class PolicyExecutionError(RelayGuardError):
    """Raised when a policy rejects input with a non-RelayGuard exception."""


class AuditExportError(RelayGuardError):
    """Raised when a successful handoff cannot emit its required audit report."""


class HandoffIntegrityError(RelayGuardError):
    """Raised when an adapter's control-item relationships are invalid."""


class UnsupportedAdapterModeError(RelayGuardError):
    """Raised when an adapter cannot observe a complete safe handoff."""
