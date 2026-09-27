"""Policy interfaces and processing context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from relayguard.models import HandoffEnvelope
from relayguard.report import AuditReport
from relayguard.tokens import TokenCounter


@dataclass(slots=True)
class PolicyContext:
    """Shared state available to every policy in one pipeline run."""

    token_counter: TokenCounter
    report: AuditReport


class Policy(ABC):
    """Base class for handoff policies."""

    name = "policy"

    @abstractmethod
    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        """Return a processed copy of ``envelope``."""
