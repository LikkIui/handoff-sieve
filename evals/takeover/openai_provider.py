"""Minimal OpenAI Agents SDK receiver adapter for the takeover pilot.

The optional ``openai`` and ``agents`` packages are imported only when a real
call is made. Importing this module therefore remains safe in the base install.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderDependencyError(ImportError):
    """Raised when the optional OpenAI evaluation dependencies are unavailable."""


class ProviderUsageUnavailableError(RuntimeError):
    """Raised when a completed response lacks provider-reported token usage."""


class ProviderProtocolError(RuntimeError):
    """Raised when the SDK result violates the single-call adapter contract."""


ProviderErrorCategory = Literal[
    "dependency_missing",
    "usage_missing",
    "protocol_error",
    "case_timeout",
    "model_timeout",
    "provider_timeout",
    "rate_limit",
    "provider_http",
    "provider_connection",
    "model_refusal",
    "invalid_output",
    "max_turns",
    "provider_error",
]

_RECEIVER_INSTRUCTIONS = (
    "Use only the supplied takeover input. Follow its receiver instruction and "
    "output contract. Return only the requested JSON object without Markdown fences."
)
_SUMMARY_INSTRUCTIONS = (
    "Follow only the supplied summarization prompt. Return the plain-text summary "
    "only, without commentary or Markdown fences."
)


class OpenAIProviderResult(BaseModel):
    """One completed, provider-measured receiver call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_model: str
    raw_output: str
    response_id: str
    request_id: str | None
    provider_input_tokens: int = Field(ge=0)
    provider_output_tokens: int = Field(ge=0)
    provider_total_tokens: int = Field(ge=0)
    model_calls: int = Field(ge=1)
    event_count: int = Field(ge=1)

    @field_validator("requested_model")
    @classmethod
    def _requested_model_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requested_model cannot be blank")
        return cleaned

    @field_validator("response_id")
    @classmethod
    def _response_id_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("response_id cannot be blank")
        return cleaned

    @field_validator("request_id")
    @classmethod
    def _optional_request_id_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("provider IDs must be non-blank or None")
        return cleaned


class ProviderErrorInfo(BaseModel):
    """Sanitized provider failure metadata safe to persist in eval records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ProviderErrorCategory
    status_code: int | None = Field(default=None, ge=100, le=599)
    request_id: str | None = None
    retryable: bool = False

    @field_validator("request_id")
    @classmethod
    def _request_id_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@dataclass(frozen=True)
class _SDKBindings:
    Agent: Any
    MaxTurnsExceeded: type[BaseException]
    ModelBehaviorError: type[BaseException]
    ModelRefusalError: type[BaseException]
    ModelRetrySettings: Any
    ModelSettings: Any
    ModelTimeoutError: type[BaseException]
    OpenAIProvider: Any
    RunConfig: Any
    Runner: Any
    APIConnectionError: type[BaseException]
    APIError: type[BaseException]
    APIStatusError: type[BaseException]
    APITimeoutError: type[BaseException]
    RateLimitError: type[BaseException]


def _load_sdk() -> _SDKBindings:
    try:
        from agents import (
            Agent,
            MaxTurnsExceeded,
            ModelBehaviorError,
            ModelRefusalError,
            ModelRetrySettings,
            ModelSettings,
            ModelTimeoutError,
            OpenAIProvider,
            RunConfig,
            Runner,
        )
        from openai import (
            APIConnectionError,
            APIError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
        )
    except ImportError:
        raise ProviderDependencyError(
            "OpenAI takeover evaluation requires: pip install 'handoff-sieve[openai]'"
        ) from None

    return _SDKBindings(
        Agent=Agent,
        MaxTurnsExceeded=MaxTurnsExceeded,
        ModelBehaviorError=ModelBehaviorError,
        ModelRefusalError=ModelRefusalError,
        ModelRetrySettings=ModelRetrySettings,
        ModelSettings=ModelSettings,
        ModelTimeoutError=ModelTimeoutError,
        OpenAIProvider=OpenAIProvider,
        RunConfig=RunConfig,
        Runner=Runner,
        APIConnectionError=APIConnectionError,
        APIError=APIError,
        APIStatusError=APIStatusError,
        APITimeoutError=APITimeoutError,
        RateLimitError=RateLimitError,
    )


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_seconds(value: float | int, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def _provider_token(raw_usage: object, field: str) -> int:
    if not isinstance(raw_usage, dict):
        raise ProviderUsageUnavailableError(
            "provider response did not include raw token usage"
        )
    value = raw_usage.get(field)
    if type(value) is not int or value < 0:
        raise ProviderUsageUnavailableError(f"provider response did not report {field}")
    return value


def _optional_provider_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


async def call_receiver(
    model_id: str,
    input_text: str,
    max_output_tokens: int = 512,
    model_timeout: float = 60,
    case_timeout: float = 70,
) -> OpenAIProviderResult:
    """Call one isolated receiver through the OpenAI Responses API.

    Output remains text so the takeover eval's strict host-side grader owns JSON
    parsing and validation.
    """

    return await _call_text(
        model_id,
        input_text,
        max_output_tokens=max_output_tokens,
        model_timeout=model_timeout,
        case_timeout=case_timeout,
        agent_name="takeover-receiver",
        instructions=_RECEIVER_INSTRUCTIONS,
    )


async def call_summary(
    model_id: str,
    prompt_text: str,
    max_output_tokens: int,
    model_timeout: float = 60,
    case_timeout: float = 70,
) -> OpenAIProviderResult:
    """Generate one measured, plain-text naive-summary baseline."""

    return await _call_text(
        model_id,
        prompt_text,
        max_output_tokens=max_output_tokens,
        model_timeout=model_timeout,
        case_timeout=case_timeout,
        agent_name="takeover-summary",
        instructions=_SUMMARY_INSTRUCTIONS,
    )


async def _call_text(
    model_id: str,
    input_text: str,
    *,
    max_output_tokens: int,
    model_timeout: float,
    case_timeout: float,
    agent_name: str,
    instructions: str,
) -> OpenAIProviderResult:
    """Run one no-tool, no-handoff, non-streaming Responses API call."""

    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("model_id must be a non-blank string")
    if not isinstance(input_text, str) or not input_text.strip():
        raise ValueError("input_text must be a non-blank string")
    output_limit = _positive_int(max_output_tokens, "max_output_tokens")
    model_timeout_seconds = _positive_seconds(model_timeout, "model_timeout")
    case_timeout_seconds = _positive_seconds(case_timeout, "case_timeout")

    sdk = _load_sdk()
    settings = sdk.ModelSettings(
        tool_choice="none",
        parallel_tool_calls=False,
        truncation="disabled",
        max_tokens=output_limit,
        store=False,
        preserve_raw_usage=True,
        timeout=model_timeout_seconds,
        retry=sdk.ModelRetrySettings(max_retries=0),
    )
    provider = sdk.OpenAIProvider(
        use_responses=True,
        use_responses_websocket=False,
    )
    run_config = sdk.RunConfig(
        model=model_id.strip(),
        model_provider=provider,
        model_settings=settings,
        tracing_disabled=True,
        trace_include_sensitive_data=False,
    )
    receiver = sdk.Agent(
        name=agent_name,
        instructions=instructions,
        tools=[],
        handoffs=[],
        output_type=str,
    )

    result = await asyncio.wait_for(
        sdk.Runner.run(
            receiver,
            input_text,
            run_config=run_config,
            max_turns=1,
        ),
        timeout=case_timeout_seconds,
    )

    responses = result.raw_responses
    if not isinstance(responses, list) or len(responses) != 1:
        raise ProviderProtocolError(
            "single-turn receiver must produce exactly one model response"
        )
    response = responses[0]
    if not isinstance(result.final_output, str):
        raise ProviderProtocolError("receiver output was not text")

    input_tokens = _provider_token(response.raw_usage, "input_tokens")
    output_tokens = _provider_token(response.raw_usage, "output_tokens")
    total_tokens = _provider_token(response.raw_usage, "total_tokens")
    model_calls = len(responses)
    response_id = _optional_provider_id(response.response_id)
    if response_id is None:
        raise ProviderProtocolError(
            "OpenAI Responses result did not include a response ID"
        )

    return OpenAIProviderResult(
        requested_model=model_id,
        raw_output=result.final_output,
        response_id=response_id,
        request_id=_optional_provider_id(response.request_id),
        provider_input_tokens=input_tokens,
        provider_output_tokens=output_tokens,
        provider_total_tokens=total_tokens,
        model_calls=model_calls,
        event_count=model_calls,
    )


def classify_provider_error(error: BaseException) -> ProviderErrorInfo:
    """Return a data-minimal error category without preserving its message."""

    if isinstance(error, ProviderDependencyError):
        return ProviderErrorInfo(category="dependency_missing")
    if isinstance(error, ProviderUsageUnavailableError):
        return ProviderErrorInfo(category="usage_missing")
    if isinstance(error, ProviderProtocolError):
        return ProviderErrorInfo(category="protocol_error")
    if isinstance(error, asyncio.TimeoutError):
        return ProviderErrorInfo(category="case_timeout", retryable=True)

    try:
        sdk = _load_sdk()
    except ProviderDependencyError:
        return ProviderErrorInfo(category="provider_error")

    request_id = _optional_provider_id(getattr(error, "request_id", None))
    if isinstance(error, sdk.ModelTimeoutError):
        return ProviderErrorInfo(category="model_timeout", retryable=True)
    if isinstance(error, sdk.APITimeoutError):
        return ProviderErrorInfo(
            category="provider_timeout",
            request_id=request_id,
            retryable=True,
        )
    if isinstance(error, sdk.RateLimitError):
        return ProviderErrorInfo(
            category="rate_limit",
            status_code=_optional_status_code(error),
            request_id=request_id,
            retryable=True,
        )
    if isinstance(error, sdk.APIStatusError):
        status_code = _optional_status_code(error)
        return ProviderErrorInfo(
            category="provider_http",
            status_code=status_code,
            request_id=request_id,
            retryable=status_code is not None and status_code >= 500,
        )
    if isinstance(error, sdk.APIConnectionError):
        return ProviderErrorInfo(
            category="provider_connection",
            request_id=request_id,
            retryable=True,
        )
    if isinstance(error, sdk.ModelRefusalError):
        return ProviderErrorInfo(category="model_refusal", request_id=request_id)
    if isinstance(error, sdk.ModelBehaviorError):
        return ProviderErrorInfo(category="invalid_output", request_id=request_id)
    if isinstance(error, sdk.MaxTurnsExceeded):
        return ProviderErrorInfo(category="max_turns", request_id=request_id)
    if isinstance(error, sdk.APIError):
        return ProviderErrorInfo(category="provider_error", request_id=request_id)
    return ProviderErrorInfo(category="provider_error", request_id=request_id)


def _optional_status_code(error: BaseException) -> int | None:
    value = getattr(error, "status_code", None)
    if type(value) is int and 100 <= value <= 599:
        return value
    return None
