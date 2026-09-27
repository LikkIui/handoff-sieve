"""Policy interfaces and processing context."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from relayguard.models import HandoffEnvelope
from relayguard.report import AuditReport
from relayguard.tokens import TokenCounter


@dataclass(slots=True)
class PolicyContext:
    """Shared state available to every policy in one pipeline run."""

    token_counter: TokenCounter
    report: AuditReport
    _track_source_fingerprints: bool = field(default=False, repr=False)
    _source_fingerprint_key: bytes = field(
        default_factory=lambda: secrets.token_bytes(32),
        repr=False,
    )

    def _set_source_fingerprint_tracking(self, enabled: bool) -> None:
        self._track_source_fingerprints = enabled

    def _source_fingerprint(self, serialized: str) -> str | None:
        if not self._track_source_fingerprints:
            return None
        return hmac.new(
            self._source_fingerprint_key,
            serialized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class Policy(ABC):
    """Base class for handoff policies."""

    name = "policy"
    version = "1"

    @abstractmethod
    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        """Return a processed copy of ``envelope``."""
