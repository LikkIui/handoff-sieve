"""Audit reporting for handoff processing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    """One non-sensitive record of a policy action."""

    model_config = ConfigDict(extra="forbid")

    policy: str
    policy_version: str = "1"
    action: str
    count: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    """A summary of how a handoff changed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    handoff_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_ms: float | None = None
    status: Literal["passed", "denied"] = "passed"
    failure_code: str | None = None
    failed_policy: str | None = None
    sender: str
    receiver: str
    token_counter: str
    config_fingerprint: str = "unavailable"
    original_tokens: int = 0
    transmitted_tokens: int = 0
    removed_messages: int = 0
    redactions: int = 0
    duplicates_removed: int = 0
    protected_messages: int = 0
    summarizer_input_tokens: int = 0
    summarizer_output_tokens: int = 0
    summarizer_provider_input_tokens: int | None = None
    summarizer_provider_output_tokens: int | None = None
    events: list[AuditEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def estimated_tokens_saved(self) -> int:
        """Estimated gross savings before any optional summarizer cost."""

        return max(0, self.original_tokens - self.transmitted_tokens)

    @property
    def estimated_savings_percent(self) -> float:
        """Estimated percentage reduction, safe for empty handoffs."""

        if self.original_tokens == 0:
            return 0.0
        return round(self.estimated_tokens_saved / self.original_tokens * 100, 1)

    @property
    def estimated_net_tokens_saved(self) -> int:
        """Savings after accounting for an optional summarizer call."""

        summary_cost = self.summarizer_input_tokens + self.summarizer_output_tokens
        return self.original_tokens - self.transmitted_tokens - summary_cost

    def add_event(
        self,
        policy: str,
        action: str,
        *,
        policy_version: str = "1",
        count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an event without storing original message content."""

        self.events.append(
            AuditEvent(
                policy=policy,
                policy_version=policy_version,
                action=action,
                count=count,
                details=details or {},
            )
        )

    def finish(self, *, duration_ms: float) -> None:
        """Mark this report complete exactly once."""

        if self.completed_at is not None:
            return
        self.completed_at = datetime.now(timezone.utc)
        self.duration_ms = max(0.0, duration_ms)

    def to_text(self) -> str:
        """Render a concise human-readable report."""

        lines = [
            f"{self.sender} -> {self.receiver}",
            f"handoff: {self.handoff_id}",
            *([f"request: {self.request_id}"] if self.request_id else []),
            f"status: {self.status}",
            f"duration: {self.duration_ms:.3f} ms"
            if self.duration_ms is not None
            else "duration: incomplete",
            f"original tokens (estimated): {self.original_tokens:,}",
            f"transmitted tokens (estimated): {self.transmitted_tokens:,}",
            f"estimated savings: {self.estimated_savings_percent:.1f}%",
            f"redactions: {self.redactions}",
            f"duplicates removed: {self.duplicates_removed}",
            f"protected messages: {self.protected_messages}",
        ]
        if self.summarizer_input_tokens or self.summarizer_output_tokens:
            net_saved = self.estimated_net_tokens_saved
            lines.extend(
                [
                    "summarizer input tokens (estimated): "
                    f"{self.summarizer_input_tokens:,}",
                    "summarizer output tokens (estimated): "
                    f"{self.summarizer_output_tokens:,}",
                    f"net tokens saved (estimated): {net_saved:,}",
                ]
            )
        if (
            self.summarizer_provider_input_tokens is not None
            or self.summarizer_provider_output_tokens is not None
        ):
            lines.extend(
                [
                    "summarizer provider input tokens: "
                    f"{self.summarizer_provider_input_tokens or 0:,}",
                    "summarizer provider output tokens: "
                    f"{self.summarizer_provider_output_tokens or 0:,}",
                ]
            )
        if self.warnings:
            lines.append(f"warnings: {len(self.warnings)}")
        if self.failure_code:
            lines.append(f"failure: {self.failure_code}")
        return "\n".join(lines)
