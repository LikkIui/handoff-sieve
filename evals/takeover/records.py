"""Auditable data models for one takeover evaluation observation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evals.takeover.grade import GradeResult
from evals.takeover.payloads import ConditionName

RecordStatus = Literal[
    "completed",
    "provider_error",
    "invalid_output",
    "summary_error",
]


class TokenUsage(BaseModel):
    """Provider-reported usage; unavailable values remain ``None``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _usage_must_be_complete_or_entirely_unknown(self) -> TokenUsage:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(value is None for value in values) and not all(
            value is None for value in values
        ):
            raise ValueError("token usage must be fully measured or entirely unknown")
        return self

    @property
    def is_complete(self) -> bool:
        """Whether all three provider counters were measured."""

        return (
            self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens is not None
        )


class TakeoverRecord(BaseModel):
    """One condition result with enough evidence for later aggregation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    condition: ConditionName
    status: RecordStatus
    recorded_at: datetime
    provider: str
    requested_model: str
    sdk_version: str
    response_id: str | None = None
    request_id: str | None = None
    receiver_input: str | None
    local_handoff_token_estimate: int | None = Field(ge=0)
    provider_usage: TokenUsage | None = None
    naive_summary_preparation_usage: TokenUsage | None = None
    retry_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    raw_output: str | None = None
    grade: GradeResult | None = None
    error: str | None = None

    @field_validator("provider", "requested_model", "sdk_version")
    @classmethod
    def _required_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(
                "provider, requested_model, and sdk_version cannot be blank"
            )
        return cleaned

    @field_validator("response_id", "request_id", "error")
    @classmethod
    def _optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional text fields must be non-blank or None")
        return value

    @field_validator("recorded_at")
    @classmethod
    def _recorded_at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("recorded_at must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def _evidence_must_match_status(self) -> TakeoverRecord:
        if self.retry_count > self.event_count:
            raise ValueError("retry_count cannot exceed event_count")

        if self.condition != "naive_summary":
            if self.naive_summary_preparation_usage is not None:
                raise ValueError(
                    "naive_summary_preparation_usage is only valid for "
                    "the naive_summary condition"
                )
        elif self.status != "summary_error":
            if self.naive_summary_preparation_usage is None:
                raise ValueError(
                    "naive_summary requires preparation usage after summary "
                    "generation succeeds"
                )

        if self.status == "summary_error":
            if self.condition != "naive_summary":
                raise ValueError("summary_error is only valid for naive_summary")
            if self.receiver_input is not None:
                raise ValueError("summary_error cannot claim a receiver input")
            if self.local_handoff_token_estimate is not None:
                raise ValueError("summary_error cannot claim handoff tokens")
            if self.grade is not None:
                raise ValueError("summary_error cannot have a grade")
            if self.error is None:
                raise ValueError("summary_error requires error details")
            return self

        if self.receiver_input is None:
            raise ValueError(f"{self.status} requires the exact receiver input")
        if self.local_handoff_token_estimate is None:
            raise ValueError(f"{self.status} requires a local handoff token estimate")

        if self.status == "completed":
            missing: list[str] = []
            if self.raw_output is None:
                missing.append("raw_output")
            if self.grade is None:
                missing.append("grade")
            if self.provider_usage is None:
                missing.append("provider_usage")
            elif not self.provider_usage.is_complete:
                missing.append("complete provider_usage")
            if self.response_id is None:
                missing.append("response_id")
            if missing:
                raise ValueError("completed record requires: " + ", ".join(missing))
            if self.error is not None:
                raise ValueError("completed record cannot contain an error")
            return self

        if self.status == "invalid_output":
            missing = []
            if self.raw_output is None:
                missing.append("raw_output")
            if self.grade is None:
                missing.append("grade")
            if self.provider_usage is None:
                missing.append("provider_usage")
            elif not self.provider_usage.is_complete:
                missing.append("complete provider_usage")
            if self.response_id is None:
                missing.append("response_id")
            if missing:
                raise ValueError(
                    "invalid_output record requires: " + ", ".join(missing)
                )

        if self.status == "provider_error":
            if self.grade is not None:
                raise ValueError("provider_error cannot have a grade")
            if self.error is None:
                raise ValueError("provider_error requires error details")

        if self.status != "completed" and self.grade is not None:
            if self.grade.overall:
                raise ValueError("a failed record cannot have overall success")
        return self
