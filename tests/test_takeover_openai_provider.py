from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from evals.takeover import openai_provider


class FakeAPIError(Exception):
    pass


class FakeAPIConnectionError(FakeAPIError):
    pass


class FakeAPITimeoutError(FakeAPIConnectionError):
    pass


class FakeAPIStatusError(FakeAPIError):
    def __init__(self, message: str, *, status_code: int, request_id: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class FakeRateLimitError(FakeAPIStatusError):
    pass


class FakeModelTimeoutError(Exception):
    pass


class FakeModelBehaviorError(Exception):
    pass


class FakeModelRefusalError(Exception):
    pass


class FakeMaxTurnsExceeded(Exception):
    pass


def _fake_sdk(
    result: object,
    *,
    delay: float = 0,
) -> tuple[openai_provider._SDKBindings, dict[str, Any]]:
    captured: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            captured["agent"] = kwargs

    class FakeModelRetrySettings:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            captured["retry"] = kwargs

    class FakeModelSettings:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            captured["settings"] = kwargs

    class FakeOpenAIProvider:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            captured["provider"] = kwargs

    class FakeRunConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            captured["run_config"] = kwargs

    class FakeRunner:
        @classmethod
        async def run(cls, *args: Any, **kwargs: Any) -> object:
            captured["runner_args"] = args
            captured["runner_kwargs"] = kwargs
            if delay:
                await asyncio.sleep(delay)
            return result

    return (
        openai_provider._SDKBindings(
            Agent=FakeAgent,
            MaxTurnsExceeded=FakeMaxTurnsExceeded,
            ModelBehaviorError=FakeModelBehaviorError,
            ModelRefusalError=FakeModelRefusalError,
            ModelRetrySettings=FakeModelRetrySettings,
            ModelSettings=FakeModelSettings,
            ModelTimeoutError=FakeModelTimeoutError,
            OpenAIProvider=FakeOpenAIProvider,
            RunConfig=FakeRunConfig,
            Runner=FakeRunner,
            APIConnectionError=FakeAPIConnectionError,
            APIError=FakeAPIError,
            APIStatusError=FakeAPIStatusError,
            APITimeoutError=FakeAPITimeoutError,
            RateLimitError=FakeRateLimitError,
        ),
        captured,
    )


def _successful_result(*, raw_usage: object) -> SimpleNamespace:
    response = SimpleNamespace(
        response_id="resp_123",
        request_id="req_123",
        raw_usage=raw_usage,
    )
    return SimpleNamespace(
        final_output='{"answer":"done"}',
        raw_responses=[response],
    )


def test_call_receiver_is_one_measured_responses_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, captured = _fake_sdk(
        _successful_result(
            raw_usage={"input_tokens": 120, "output_tokens": 18, "total_tokens": 138}
        )
    )
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    result = asyncio.run(
        openai_provider.call_receiver(
            "provider/model-snapshot",
            "receiver input",
            max_output_tokens=256,
            model_timeout=20,
            case_timeout=25,
        )
    )

    assert result.requested_model == "provider/model-snapshot"
    assert result.raw_output == '{"answer":"done"}'
    assert result.response_id == "resp_123"
    assert result.request_id == "req_123"
    assert result.provider_input_tokens == 120
    assert result.provider_output_tokens == 18
    assert result.provider_total_tokens == 138
    assert result.model_calls == 1
    assert result.event_count == 1

    assert captured["provider"] == {
        "use_responses": True,
        "use_responses_websocket": False,
    }
    assert captured["retry"] == {"max_retries": 0}
    settings = dict(captured["settings"])
    retry = settings.pop("retry")
    assert retry.kwargs == {"max_retries": 0}
    assert settings == {
        "tool_choice": "none",
        "parallel_tool_calls": False,
        "truncation": "disabled",
        "max_tokens": 256,
        "store": False,
        "preserve_raw_usage": True,
        "timeout": 20.0,
    }
    assert captured["run_config"]["model"] == "provider/model-snapshot"
    assert captured["run_config"]["tracing_disabled"] is True
    assert captured["run_config"]["trace_include_sensitive_data"] is False
    assert captured["agent"]["tools"] == []
    assert captured["agent"]["handoffs"] == []
    assert captured["agent"]["output_type"] is str
    assert captured["runner_args"][1] == "receiver input"
    assert captured["runner_kwargs"]["run_config"].kwargs == captured["run_config"]
    assert captured["runner_kwargs"]["max_turns"] == 1
    assert set(captured["runner_kwargs"]) == {"run_config", "max_turns"}

    with pytest.raises(ValidationError):
        result.raw_output = "changed"


def test_call_summary_uses_plain_text_instruction_and_exact_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, captured = _fake_sdk(
        _successful_result(
            raw_usage={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}
        )
    )
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    result = asyncio.run(
        openai_provider.call_summary(
            "provider/model-snapshot",
            "summarize this exact sender state",
            max_output_tokens=128,
        )
    )

    assert result.provider_total_tokens == 100
    assert captured["agent"]["name"] == "takeover-summary"
    assert "plain-text summary" in captured["agent"]["instructions"]
    assert "JSON object" not in captured["agent"]["instructions"]
    assert captured["runner_args"][1] == "summarize this exact sender state"
    assert captured["settings"]["max_tokens"] == 128


def test_call_receiver_fails_when_provider_usage_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, _ = _fake_sdk(
        _successful_result(raw_usage={"input_tokens": 4, "output_tokens": 2})
    )
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    with pytest.raises(
        openai_provider.ProviderUsageUnavailableError,
        match="total_tokens",
    ):
        asyncio.run(openai_provider.call_receiver("model", "input"))


def test_call_receiver_fails_when_response_id_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _successful_result(
        raw_usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    )
    result.raw_responses[0].response_id = None
    sdk, _ = _fake_sdk(result)
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    with pytest.raises(
        openai_provider.ProviderProtocolError,
        match="response ID",
    ):
        asyncio.run(openai_provider.call_receiver("model", "input"))


def test_case_timeout_is_bounded_and_safely_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, _ = _fake_sdk(
        _successful_result(
            raw_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        ),
        delay=0.05,
    )
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    with pytest.raises(asyncio.TimeoutError) as caught:
        asyncio.run(
            openai_provider.call_receiver(
                "model",
                "input",
                case_timeout=0.001,
            )
        )

    classified = openai_provider.classify_provider_error(caught.value)
    assert classified.category == "case_timeout"
    assert classified.retryable is True


def test_http_error_classification_omits_exception_message_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, _ = _fake_sdk(object())
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)
    error = FakeAPIStatusError(
        "secret-key=never-persist-this",
        status_code=503,
        request_id="req_safe",
    )

    classified = openai_provider.classify_provider_error(error)

    assert classified.category == "provider_http"
    assert classified.status_code == 503
    assert classified.request_id == "req_safe"
    assert classified.retryable is True
    serialized = json.dumps(classified.model_dump(mode="json"))
    assert "never-persist-this" not in serialized
    assert "secret-key" not in serialized


def test_specific_timeout_and_rate_limit_categories_precede_parent_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk, _ = _fake_sdk(object())
    monkeypatch.setattr(openai_provider, "_load_sdk", lambda: sdk)

    model_timeout = openai_provider.classify_provider_error(
        FakeModelTimeoutError("sensitive")
    )
    provider_timeout = openai_provider.classify_provider_error(
        FakeAPITimeoutError("sensitive")
    )
    rate_limit = openai_provider.classify_provider_error(
        FakeRateLimitError("sensitive", status_code=429, request_id="req_rate")
    )

    assert model_timeout.category == "model_timeout"
    assert provider_timeout.category == "provider_timeout"
    assert rate_limit.category == "rate_limit"
    assert rate_limit.status_code == 429
    assert rate_limit.request_id == "req_rate"
    assert rate_limit.retryable is True
