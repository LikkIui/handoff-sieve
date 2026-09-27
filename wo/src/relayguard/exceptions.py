"""RelayGuard exceptions."""


class RelayGuardError(Exception):
    """Base exception for RelayGuard failures."""


class BudgetExceededError(RelayGuardError):
    """Raised when protected content cannot fit within a hard budget."""


class ConfigurationError(RelayGuardError):
    """Raised when a policy configuration is invalid."""

