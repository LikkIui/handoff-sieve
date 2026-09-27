"""Audit reporting for handoff processing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    """One non-sensitive record of a policy action."""

    policy: str
    action: str
    count: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    """A summary of how a handoff changed."""

    sender: str
    receiver: str
    token_counter: str
    original_tokens: int = 0
    transmitted_tokens: int = 0
    removed_messages: int = 0
    redactions: int = 0
    duplicates_removed: int = 0
    protected_messages: int = 0
    summarizer_input_tokens: int = 0
    summarizer_output_tokens: int = 0
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
        count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an event without storing original message content."""

        self.events.append(
            AuditEvent(
                policy=policy,
                action=action,
                count=count,
                details=details or {},
            )
        )

    def to_text(self) -> str:
        """Render a concise human-readable report."""

        lines = [
            f"{self.sender} -> {self.receiver}",
            f"original tokens (estimated): {self.original_tokens:,}",
            f"transmitted tokens (estimated): {self.transmitted_tokens:,}",
            f"estimated savings: {self.estimated_savings_percent:.1f}%",
            f"redactions: {self.redactions}",
            f"duplicates removed: {self.duplicates_removed}",
            f"protected messages: {self.protected_messages}",
        ]
        if self.summarizer_input_tokens or self.summarizer_output_tokens:
            lines.extend(
                [
                    f"summarizer input tokens: {self.summarizer_input_tokens:,}",
                    f"summarizer output tokens: {self.summarizer_output_tokens:,}",
                    f"net tokens saved (estimated): {self.estimated_net_tokens_saved:,}",
                ]
            )
        if self.warnings:
            lines.append(f"warnings: {len(self.warnings)}")
        return "\n".join(lines)

