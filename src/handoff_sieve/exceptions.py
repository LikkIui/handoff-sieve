"""HandoffSieve exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from handoff_sieve.compiler import BudgetReport, ContractDiagnostics
    from handoff_sieve.normalization import NormalizationReport
    from handoff_sieve.report import AuditReport


class HandoffSieveError(Exception):
    """Base exception for HandoffSieve failures."""

    def __init__(
        self,
        message: str,
        *,
        report: AuditReport | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report


class BudgetExceededError(HandoffSieveError):
    """Raised when protected content cannot fit within a hard budget."""

    def __init__(
        self,
        message: str,
        *,
        report: AuditReport | None = None,
        budget: BudgetReport | None = None,
    ) -> None:
        super().__init__(message, report=report)
        self.budget = budget

    def __str__(self) -> str:
        message = super().__str__()
        if self.budget is not None:
            return message + "\n" + self.budget.to_text()
        return message


class ConfigurationError(HandoffSieveError):
    """Raised when a policy configuration is invalid."""


class ContractError(HandoffSieveError):
    """Raised when sender state cannot satisfy a receiver contract."""

    def __init__(
        self,
        message: str,
        *,
        report: AuditReport | None = None,
        diagnostics: ContractDiagnostics | None = None,
    ) -> None:
        super().__init__(message, report=report)
        self.diagnostics = diagnostics
        self.normalization: NormalizationReport | None = None

    def __str__(self) -> str:
        message = super().__str__()
        if self.diagnostics is not None:
            return message + "\n" + self.diagnostics.to_text()
        return message


class UnmatchedRouteError(HandoffSieveError):
    """Raised when a configured rule set has no matching handoff route."""


class AmbiguousRouteError(HandoffSieveError):
    """Raised when multiple policy routes match without an explicit strategy."""


class ReservedFieldError(HandoffSieveError):
    """Raised when untrusted input attempts to set internal processing state."""


class RedactionError(HandoffSieveError):
    """Raised when redaction cannot complete within configured safety limits."""


class PolicyExecutionError(HandoffSieveError):
    """Raised when a policy rejects input with a non-HandoffSieve exception."""


class AuditExportError(HandoffSieveError):
    """Raised when a successful handoff cannot emit its required audit report."""


class HandoffIntegrityError(HandoffSieveError):
    """Raised when an adapter's control-item relationships are invalid."""


class UnsupportedAdapterModeError(HandoffSieveError):
    """Raised when an adapter cannot observe a complete safe handoff."""
