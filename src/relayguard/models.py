"""Core handoff models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from relayguard.report import AuditReport


class Message(BaseModel):
    """A normalized message passed between agents.

    ``tags`` can be used by policies to identify constraints, citations, or any
    application-specific category. ``protected`` is internal processing state
    and is excluded from serialized output.
    """

    model_config = ConfigDict(extra="forbid")

    role: str = "user"
    content: str | dict[str, Any] | list[Any]
    kind: str = "message"
    tags: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # These values affect destructive policy decisions and framework item
    # reconstruction. They must never be accepted from untrusted payloads or
    # serialized into the receiver view.
    _protected: bool = PrivateAttr(default=False)
    _internal: dict[str, Any] = PrivateAttr(default_factory=dict)

    @property
    def protected(self) -> bool:
        """Whether destructive policies must retain this message."""

        return self._protected

    @property
    def internal(self) -> dict[str, Any]:
        """Trusted adapter state excluded from the public model."""

        return self._internal

    def _mark_protected(self) -> None:
        """Mark a normalized message as protected inside the pipeline."""

        self._protected = True

    def _replace_internal(self, values: dict[str, Any]) -> None:
        """Attach trusted framework reconstruction state."""

        self._internal = dict(values)


class Artifact(BaseModel):
    """A task result kept separate from conversational messages."""

    model_config = ConfigDict(extra="forbid")

    name: str
    content: str | dict[str, Any] | list[Any]
    media_type: str = "text/plain"
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoffEnvelope(BaseModel):
    """The normalized payload for one agent-to-agent handoff."""

    model_config = ConfigDict(extra="forbid")

    sender: str
    receiver: str
    messages: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoffResult(BaseModel):
    """The processed handoff and its audit report."""

    model_config = ConfigDict(extra="forbid")

    envelope: HandoffEnvelope
    report: AuditReport
    status: Literal["passed"] = "passed"

    @property
    def messages(self) -> list[Message]:
        """Return processed messages for convenient framework integration."""

        return self.envelope.messages
