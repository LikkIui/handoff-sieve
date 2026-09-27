"""Core handoff models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from relayguard.report import AuditReport


class Message(BaseModel):
    """A normalized message passed between agents.

    ``tags`` can be used by policies to identify constraints, citations, or any
    application-specific category. ``protected`` is internal processing state
    and is excluded from serialized output.
    """

    model_config = ConfigDict(extra="allow")

    role: str = "user"
    content: str | dict[str, Any] | list[Any]
    kind: str = "message"
    tags: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)
    protected: bool = Field(default=False, exclude=True)
    internal: dict[str, Any] = Field(default_factory=dict, exclude=True)


class Artifact(BaseModel):
    """A task result kept separate from conversational messages."""

    name: str
    content: str | dict[str, Any] | list[Any]
    media_type: str = "text/plain"
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoffEnvelope(BaseModel):
    """The normalized payload for one agent-to-agent handoff."""

    sender: str
    receiver: str
    messages: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoffResult(BaseModel):
    """The processed handoff and its audit report."""

    envelope: HandoffEnvelope
    report: AuditReport
    status: Literal["passed"] = "passed"

    @property
    def messages(self) -> list[Message]:
        """Return processed messages for convenient framework integration."""

        return self.envelope.messages

