from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from evals.takeover import run_openai
from evals.takeover.openai_provider import OpenAIProviderResult, ProviderErrorInfo
from handoff_sieve import ApproxTokenCounter


def _result(raw_output: str, identifier: str) -> OpenAIProviderResult:
    return OpenAIProviderResult(
        requested_model="test-model",
        raw_output=raw_output,
        response_id=f"resp_{identifier}",
        request_id=f"req_{identifier}",
        provider_input_tokens=100,
        provider_output_tokens=20,
        provider_total_tokens=120,
        model_calls=1,
        event_count=1,
    )


class FakeCalls:
    def __init__(self, summary_text: str | Callable[[int], str] = "short summary"):
        self.summary_text = summary_text
        self.summary_inputs: list[tuple[str, str, int]] = []
        self.receiver_inputs: list[tuple[str, str, int]] = []

    async def call_summary(
        self,
        model_id: str,
        prompt_text: str,
        *,
        max_output_tokens: int,
        **_: Any,
    ) -> OpenAIProviderResult:
        self.summary_inputs.append((model_id, prompt_text, max_output_tokens))
        text = (
            self.summary_text(max_output_tokens)
            if callable(self.summary_text)
            else self.summary_text
        )
        return _result(text, f"summary_{len(self.summary_inputs)}")

    async def call_receiver(
        self,
        model_id: str,
        input_text: str,
        *,
        max_output_tokens: int,
        **_: Any,
    ) -> OpenAIProviderResult:
        self.receiver_inputs.append((model_id, input_text, max_output_tokens))
        return _result("{}", f"receiver_{len(self.receiver_inputs)}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _neutral_classifier(_: BaseException) -> ProviderErrorInfo:
    return ProviderErrorInfo(category="provider_connection", retryable=True)


def test_cli_does_not_touch_provider_without_explicit_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_preflight() -> str:
        raise AssertionError("provider preflight must not run")

    monkeypatch.setattr(run_openai, "_preflight_openai", forbidden_preflight)
    output = tmp_path / "must-not-exist.jsonl"

    assert run_openai.main([]) == 0
    assert run_openai.main(["--model", "test-model", "--output", str(output)]) == 0
    assert not output.exists()
    assert capsys.readouterr().out.count('"status": "not_run"') == 2


def test_cli_run_gate_passes_only_explicit_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_batch(**kwargs: object) -> int:
        captured.update(kwargs)
        return 9

    monkeypatch.setattr(run_openai, "_preflight_openai", lambda: "fake-sdk")
    monkeypatch.setattr(run_openai, "run_batch", fake_batch)
    output = tmp_path / "new.jsonl"

    result = run_openai.main(
        ["--run", "--model", "test-model", "--output", str(output)]
    )

    assert result == 0
    assert captured["model"] == "test-model"
    assert captured["output"] == output
    assert captured["sdk_version"] == "fake-sdk"


def test_missing_api_key_stops_before_loading_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        run_openai.openai_provider,
        "_load_sdk",
        lambda: (_ for _ in ()).throw(AssertionError("SDK must not load")),
    )

    with pytest.raises(run_openai.BatchConfigurationError, match="OPENAI_API_KEY"):
        run_openai._preflight_openai()


def test_batch_writes_fair_inputs_and_only_final_footer_marks_completion(
    tmp_path: Path,
) -> None:
    calls = FakeCalls()
    output = tmp_path / "run.jsonl"

    record_count = asyncio.run(
        run_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
        )
    )

    rows = _read_jsonl(output)
    assert record_count == 9
    assert len(rows) == 11
    assert rows[0]["kind"] == "run_started"
    assert "status" not in rows[0]
    assert rows[-1]["kind"] == "run_completed"
    assert rows[-1]["records_written"] == 9
    assert rows[0]["run_id"] == rows[-1]["run_id"]
    assert [row["kind"] for row in rows[1:-1]] == ["observation"] * 9
    assert rows[0]["condition_orders"] == {
        rows[0]["task_ids"][0]: [
            "full_history",
            "naive_summary",
            "handoff_sieve",
        ],
        rows[0]["task_ids"][1]: [
            "naive_summary",
            "handoff_sieve",
            "full_history",
        ],
        rows[0]["task_ids"][2]: [
            "handoff_sieve",
            "full_history",
            "naive_summary",
        ],
    }

    observations = rows[1:-1]
    assert len(calls.summary_inputs) == 3
    assert len(calls.receiver_inputs) == 9
    assert {row["condition"] for row in observations} == {
        "full_history",
        "naive_summary",
        "handoff_sieve",
    }

    for task_id in rows[0]["task_ids"]:
        task_rows = [row for row in observations if row["task_id"] == task_id]
        assert [row["condition"] for row in task_rows] == rows[0]["condition_orders"][
            task_id
        ]
        prefixes = {
            row["receiver_input"].split("\n\n<handoff_context>\n", 1)[0]
            for row in task_rows
        }
        assert len(prefixes) == 1
        assert all(
            "success_validator" not in row["receiver_input"] for row in task_rows
        )

    for row in observations:
        assert row["retry_count"] == 0
        assert row["raw_output"] == "{}"
        assert row["grade"]["overall"] is False
        assert row["local_handoff_token_estimate"] == (
            ApproxTokenCounter().count_text(row["receiver_input"])
        )
        if row["condition"] == "naive_summary":
            assert row["event_count"] == 2
            assert row["naive_summary_preparation_usage"] == {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            }
        else:
            assert row["event_count"] == 1
            assert row["naive_summary_preparation_usage"] is None


def test_fatal_provider_configuration_leaves_header_without_footer(
    tmp_path: Path,
) -> None:
    class FatalHTTPError(Exception):
        pass

    calls = FakeCalls()

    async def fatal_receiver(*_: Any, **__: Any) -> OpenAIProviderResult:
        raise FatalHTTPError("secret provider message")

    def classify(_: BaseException) -> ProviderErrorInfo:
        return ProviderErrorInfo(
            category="provider_http",
            status_code=401,
            request_id="req_fatal",
        )

    output = tmp_path / "partial.jsonl"
    with pytest.raises(run_openai.BatchFatalProviderError):
        asyncio.run(
            run_openai.run_batch(
                model="test-model",
                output=output,
                sdk_version="fake-sdk",
                call_summary=calls.call_summary,
                call_receiver=fatal_receiver,
                classify_error=classify,
            )
        )

    rows = _read_jsonl(output)
    assert [row["kind"] for row in rows] == ["run_started"]
    assert "secret provider message" not in output.read_text(encoding="utf-8")


def test_nonfatal_provider_errors_are_sanitized_and_batch_completes(
    tmp_path: Path,
) -> None:
    calls = FakeCalls()

    async def failed_receiver(*_: Any, **__: Any) -> OpenAIProviderResult:
        raise RuntimeError("secret endpoint and credential detail")

    output = tmp_path / "provider-errors.jsonl"
    count = asyncio.run(
        run_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=failed_receiver,
            classify_error=_neutral_classifier,
        )
    )

    rows = _read_jsonl(output)
    assert count == 9
    assert rows[-1]["kind"] == "run_completed"
    assert "secret endpoint" not in output.read_text(encoding="utf-8")
    observations = rows[1:-1]
    assert {row["status"] for row in observations} == {"provider_error"}
    assert {row["error"] for row in observations} == {
        "provider_error:provider_connection"
    }


def test_summary_over_budget_is_recorded_without_a_naive_receiver_call(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(lambda limit: "x" * (limit * 8 + 1))
    output = tmp_path / "summary-over-budget.jsonl"

    asyncio.run(
        run_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
        )
    )

    rows = _read_jsonl(output)
    observations = rows[1:-1]
    summary_errors = [
        row for row in observations if row["condition"] == "naive_summary"
    ]
    assert len(summary_errors) == 3
    assert {row["status"] for row in summary_errors} == {"summary_error"}
    assert {row["error"] for row in summary_errors} == {"summary_over_budget"}
    assert all(row["receiver_input"] is None for row in summary_errors)
    assert all(row["local_handoff_token_estimate"] is None for row in summary_errors)
    assert all(row["raw_output"] for row in summary_errors)
    assert all(
        row["naive_summary_preparation_usage"] is not None for row in summary_errors
    )
    assert len(calls.receiver_inputs) == 6
    assert rows[-1]["kind"] == "run_completed"


def test_batch_refuses_to_overwrite_an_existing_output(tmp_path: Path) -> None:
    calls = FakeCalls()
    output = tmp_path / "existing.jsonl"
    output.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError):
        asyncio.run(
            run_openai.run_batch(
                model="test-model",
                output=output,
                sdk_version="fake-sdk",
                call_summary=calls.call_summary,
                call_receiver=calls.call_receiver,
                classify_error=_neutral_classifier,
            )
        )

    assert output.read_text(encoding="utf-8") == "keep me"
    assert calls.summary_inputs == []
    assert calls.receiver_inputs == []
