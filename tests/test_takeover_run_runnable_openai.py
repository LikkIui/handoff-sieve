from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from evals.takeover import run_runnable_openai
from evals.takeover.openai_provider import OpenAIProviderResult, ProviderErrorInfo
from handoff_sieve import ApproxTokenCounter

EXPECTED_CHECK_IDS = {
    "cursor_round_trip",
    "malformed_cursor",
    "page_size_1",
    "page_size_7",
    "page_size_13",
    "terminal_page",
    "input_immutability",
}

REFERENCE_IMPLEMENTATION = '''\
"""Test-only reference used to prove that runnable execution is satisfiable."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivityRow:
    created_at: datetime
    id: str
    payload: Any = None


def encode_cursor(row: ActivityRow) -> str:
    payload = json.dumps(
        [row.created_at.isoformat(), row.id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("malformed cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not isinstance(value[0], str)
            or not isinstance(value[1], str)
            or not value[1]
        ):
            raise ValueError
        created_at = datetime.fromisoformat(value[0])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, value[1]
    except Exception as exc:
        raise ValueError("malformed cursor") from exc


def page_after(
    rows: Sequence[ActivityRow],
    cursor: str | None,
    limit: int,
) -> tuple[list[ActivityRow], str | None]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be positive")
    boundary = decode_cursor(cursor) if cursor is not None else None
    ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
    eligible = [
        row
        for row in ordered
        if boundary is None or (row.created_at, row.id) > boundary
    ]
    page = eligible[:limit]
    next_cursor = (
        encode_cursor(page[-1]) if page and len(eligible) > len(page) else None
    )
    return page, next_cursor
'''


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
    def __init__(
        self,
        receiver_output: str | Callable[[int, str], str],
        *,
        summary_text: str = "short summary for the receiver",
    ) -> None:
        self.receiver_output = receiver_output
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
        return _result(self.summary_text, "summary")

    async def call_receiver(
        self,
        model_id: str,
        input_text: str,
        *,
        max_output_tokens: int,
        **_: Any,
    ) -> OpenAIProviderResult:
        self.receiver_inputs.append((model_id, input_text, max_output_tokens))
        call_index = len(self.receiver_inputs)
        raw_output = (
            self.receiver_output(call_index, input_text)
            if callable(self.receiver_output)
            else self.receiver_output
        )
        return _result(raw_output, f"receiver_{call_index}")


def _candidate_output(source: str) -> str:
    return json.dumps({"pagination_py": source}, ensure_ascii=False)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _handoff_context(receiver_input: str) -> str:
    opening = "\n\n<handoff_context>\n"
    closing = "\n</handoff_context>"
    _, separator, remainder = receiver_input.partition(opening)
    assert separator == opening
    assert remainder.endswith(closing)
    return remainder[: -len(closing)]


def _neutral_classifier(_: BaseException) -> ProviderErrorInfo:
    return ProviderErrorInfo(category="provider_connection", retryable=True)


def _run_batch(
    tmp_path: Path,
    calls: FakeCalls,
    *,
    output_name: str = "run.jsonl",
    provider_label: str = "openai",
) -> tuple[int, Path, list[dict[str, Any]]]:
    output = tmp_path / output_name
    count = asyncio.run(
        run_runnable_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
            provider_label=provider_label,
        )
    )
    return count, output, _read_jsonl(output)


def test_cli_does_not_touch_provider_without_explicit_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_preflight() -> str:
        raise AssertionError("provider preflight must not run")

    monkeypatch.setattr(
        run_runnable_openai,
        "_preflight_openai",
        forbidden_preflight,
    )
    output = tmp_path / "must-not-exist.jsonl"

    assert run_runnable_openai.main([]) == 0
    assert (
        run_runnable_openai.main(["--model", "test-model", "--output", str(output)])
        == 0
    )
    assert not output.exists()
    assert capsys.readouterr().out.count('"status": "not_run"') == 2


def test_cli_run_gate_passes_only_explicit_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_batch(**kwargs: object) -> int:
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(
        run_runnable_openai,
        "_preflight_openai",
        lambda: "fake-sdk",
    )
    monkeypatch.setattr(run_runnable_openai, "run_batch", fake_batch)
    output = tmp_path / "new.jsonl"

    result = run_runnable_openai.main(
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
        run_runnable_openai.openai_provider,
        "_load_sdk",
        lambda: (_ for _ in ()).throw(AssertionError("SDK must not load")),
    )

    with pytest.raises(
        run_runnable_openai.RunnableConfigurationError,
        match="OPENAI_API_KEY",
    ):
        run_runnable_openai._preflight_openai()


def test_parse_candidate_source_accepts_only_the_exact_single_field_contract() -> None:
    raw = _candidate_output(REFERENCE_IMPLEMENTATION)

    assert run_runnable_openai.parse_candidate_source(raw) == REFERENCE_IMPLEMENTATION


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '"a string"',
        '{"pagination_py": 3}',
        '{"pagination_py": ""}',
        '{"pagination_py": "  \\n"}',
        '{"pagination_py": "pass", "extra": true}',
        '{"pagination_py": "first", "pagination_py": "second"}',
        '```json\n{"pagination_py": "pass"}\n```',
    ],
)
def test_parse_candidate_source_rejects_malformed_or_ambiguous_output(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        run_runnable_openai.parse_candidate_source(raw)


def test_parse_candidate_source_enforces_utf8_byte_limits() -> None:
    oversized_source = "界" * 21_846
    assert len(oversized_source) < run_runnable_openai.MAX_CANDIDATE_SOURCE_BYTES
    assert (
        len(oversized_source.encode("utf-8"))
        > run_runnable_openai.MAX_CANDIDATE_SOURCE_BYTES
    )

    with pytest.raises(ValueError, match="large|size|byte"):
        run_runnable_openai.parse_candidate_source(_candidate_output(oversized_source))

    with pytest.raises(ValueError, match="large|size|byte"):
        run_runnable_openai.parse_candidate_source(" " * 131_073 + "{}")


def test_reference_candidate_runs_all_three_fair_conditions_and_passes(
    tmp_path: Path,
) -> None:
    starter_source = (
        run_runnable_openai.STARTER / "task_app" / "pagination.py"
    ).read_text(encoding="utf-8")
    raw_output = _candidate_output(REFERENCE_IMPLEMENTATION)
    calls = FakeCalls(raw_output)

    count, output, rows = _run_batch(tmp_path, calls)

    assert count == 3
    assert len(rows) == 5
    assert rows[0]["kind"] == "run_started"
    assert rows[0]["task_id"] == "rc01_composite_cursor"
    assert rows[0]["conditions"] == [
        "full_history",
        "naive_summary",
        "handoff_sieve",
    ]
    assert rows[-1]["kind"] == "run_completed"
    assert rows[-1]["records_written"] == 3
    assert rows[0]["run_id"] == rows[-1]["run_id"]
    assert run_runnable_openai.has_completed_footer(output) is True

    observations = rows[1:-1]
    assert [row["kind"] for row in observations] == ["observation"] * 3
    assert [row["condition"] for row in observations] == rows[0]["conditions"]
    assert len(calls.summary_inputs) == 1
    assert len(calls.receiver_inputs) == 3

    task_prefixes = {row["task_prefix"] for row in observations}
    assert len(task_prefixes) == 1
    task_prefix = task_prefixes.pop()
    assert task_prefix.strip()
    assert all(row["receiver_input"].startswith(task_prefix) for row in observations)
    assert len({row["receiver_input"] for row in observations}) == 3
    assert [call[1] for call in calls.receiver_inputs] == [
        row["receiver_input"] for row in observations
    ]
    for check_id in EXPECTED_CHECK_IDS:
        assert all(check_id not in row["receiver_input"] for row in observations)

    for index, row in enumerate(observations, start=1):
        assert row["status"] == "completed"
        assert row["downstream_success"] is True
        assert row["raw_output"] == raw_output
        assert row["response_id"] == f"resp_receiver_{index}"
        assert row["provider_usage"] == {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }
        assert row["local_input_token_estimate"] == ApproxTokenCounter().count_text(
            row["receiver_input"]
        )
        assert row["local_handoff_token_estimate"] == (
            ApproxTokenCounter().count_text(_handoff_context(row["receiver_input"]))
        )
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(check["passed"] for check in row["checks"])

    by_condition = {row["condition"]: row for row in observations}
    assert by_condition["full_history"]["event_count"] == 1
    assert by_condition["naive_summary"]["event_count"] == 2
    assert by_condition["handoff_sieve"]["event_count"] == 1

    assert (run_runnable_openai.STARTER / "task_app" / "pagination.py").read_text(
        encoding="utf-8"
    ) == starter_source


def test_custom_provider_label_is_recorded_on_run_and_observations(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(_candidate_output(REFERENCE_IMPLEMENTATION))

    _, _, rows = _run_batch(
        tmp_path,
        calls,
        provider_label="openai-compatible:test-gateway",
    )

    assert rows[0]["provider"] == "openai-compatible:test-gateway"
    assert all(
        row["provider"] == "openai-compatible:test-gateway" for row in rows[1:-1]
    )


def test_valid_stub_is_completed_but_fails_all_acceptance_checks(
    tmp_path: Path,
) -> None:
    stub_source = (
        run_runnable_openai.STARTER / "task_app" / "pagination.py"
    ).read_text(encoding="utf-8")
    calls = FakeCalls(_candidate_output(stub_source))

    _, _, rows = _run_batch(tmp_path, calls)

    for row in rows[1:-1]:
        assert row["status"] == "completed"
        assert row["downstream_success"] is False
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(not check["passed"] for check in row["checks"])


def test_valid_json_with_invalid_python_is_a_failed_candidate_not_invalid_output(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(_candidate_output("def broken(:\n    pass\n"))

    _, _, rows = _run_batch(tmp_path, calls)

    for row in rows[1:-1]:
        assert row["status"] == "completed"
        assert row["downstream_success"] is False
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(not check["passed"] for check in row["checks"])


def test_acceptance_timeout_is_recorded_as_seven_failed_checks(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(_candidate_output("import time\ntime.sleep(5)\n"))
    output = tmp_path / "acceptance-timeout.jsonl"

    count = asyncio.run(
        run_runnable_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
            acceptance_timeout=0.05,
        )
    )

    rows = _read_jsonl(output)
    assert count == 3
    assert run_runnable_openai.has_completed_footer(output) is True
    for row in rows[1:-1]:
        assert row["status"] == "acceptance_error"
        assert row["downstream_success"] is False
        assert row["error"] == "acceptance_timeout"
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(not check["passed"] for check in row["checks"])
        assert {check["detail"] for check in row["checks"]} == {"acceptance_timeout"}


def test_acceptance_subprocess_cannot_see_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-candidate")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-candidate")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-candidate")
    guarded_source = (
        REFERENCE_IMPLEMENTATION
        + """

import os as _os

if any(
    _os.environ.get(name)
    for name in (
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
    )
):
    raise RuntimeError("provider credential was visible to candidate code")
"""
    )
    calls = FakeCalls(_candidate_output(guarded_source))

    _, _, rows = _run_batch(tmp_path, calls)

    for row in rows[1:-1]:
        assert row["status"] == "completed"
        assert row["downstream_success"] is True
        assert all(check["passed"] for check in row["checks"])


@pytest.mark.parametrize(
    "raw_output",
    [
        '{"pagination_py": "pass", "extra": true}',
        _candidate_output("界" * 21_846),
    ],
    ids=["extra-field", "source-over-byte-limit"],
)
def test_strict_output_failures_are_recorded_without_running_acceptance(
    tmp_path: Path,
    raw_output: str,
) -> None:
    calls = FakeCalls(raw_output)

    count, _, rows = _run_batch(tmp_path, calls)

    assert count == 3
    assert rows[-1]["kind"] == "run_completed"
    assert rows[-1]["records_written"] == 3
    for row in rows[1:-1]:
        assert row["status"] == "invalid_output"
        assert row["downstream_success"] is False
        assert row["raw_output"] == raw_output
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(not check["passed"] for check in row["checks"])
        assert row["provider_usage"] == {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }


def test_nonfatal_provider_errors_are_sanitized_and_batch_completes(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(_candidate_output(REFERENCE_IMPLEMENTATION))

    async def failed_receiver(*_: Any, **__: Any) -> OpenAIProviderResult:
        raise RuntimeError("secret endpoint and credential detail")

    output = tmp_path / "provider-errors.jsonl"
    count = asyncio.run(
        run_runnable_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=calls.call_summary,
            call_receiver=failed_receiver,
            classify_error=_neutral_classifier,
        )
    )

    rows = _read_jsonl(output)
    assert count == 3
    assert rows[-1]["kind"] == "run_completed"
    assert "secret endpoint" not in output.read_text(encoding="utf-8")
    for row in rows[1:-1]:
        assert row["status"] == "provider_error"
        assert row["downstream_success"] is False
        assert row["provider_usage"] is None
        assert row["response_id"] is None
        assert row["raw_output"] is None
        assert {check["id"] for check in row["checks"]} == EXPECTED_CHECK_IDS
        assert all(not check["passed"] for check in row["checks"])
        assert row["error"] == "provider_error:provider_connection"


def test_summary_over_budget_is_charged_only_as_naive_preparation(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(
        _candidate_output(REFERENCE_IMPLEMENTATION),
        summary_text="x" * 10_000,
    )

    count, _, rows = _run_batch(tmp_path, calls)

    observations = {row["condition"]: row for row in rows[1:-1]}
    naive = observations["naive_summary"]
    assert count == 3
    assert len(calls.summary_inputs) == 1
    assert len(calls.receiver_inputs) == 2
    assert naive["status"] == "summary_error"
    assert naive["error"] == "summary_over_budget"
    assert naive["downstream_success"] is False
    assert naive["provider_usage"] is None
    assert naive["response_id"] is None
    assert naive["raw_output"] is None
    assert naive["naive_summary_preparation_usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    assert naive["event_count"] == 1
    assert all(not check["passed"] for check in naive["checks"])
    assert observations["full_history"]["event_count"] == 1
    assert observations["handoff_sieve"]["event_count"] == 1


def test_summary_provider_error_has_no_measured_usage_or_receiver_output(
    tmp_path: Path,
) -> None:
    calls = FakeCalls(_candidate_output(REFERENCE_IMPLEMENTATION))

    async def failed_summary(*_: Any, **__: Any) -> OpenAIProviderResult:
        raise RuntimeError("secret summary endpoint detail")

    output = tmp_path / "summary-provider-error.jsonl"
    count = asyncio.run(
        run_runnable_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            call_summary=failed_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
        )
    )

    rows = _read_jsonl(output)
    observations = {row["condition"]: row for row in rows[1:-1]}
    naive = observations["naive_summary"]
    assert count == 3
    assert len(calls.receiver_inputs) == 2
    assert "secret summary" not in output.read_text(encoding="utf-8")
    assert naive["status"] == "summary_error"
    assert naive["error"] == "summary_error:provider_connection"
    assert naive["downstream_success"] is False
    assert naive["provider_usage"] is None
    assert naive["response_id"] is None
    assert naive["raw_output"] is None
    assert naive["naive_summary_preparation_usage"] is None
    assert naive["event_count"] == 1
    assert all(not check["passed"] for check in naive["checks"])
    assert observations["full_history"]["event_count"] == 1
    assert observations["handoff_sieve"]["event_count"] == 1


def test_batch_refuses_to_overwrite_an_existing_output(tmp_path: Path) -> None:
    calls = FakeCalls(_candidate_output(REFERENCE_IMPLEMENTATION))
    output = tmp_path / "existing.jsonl"
    output.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError):
        asyncio.run(
            run_runnable_openai.run_batch(
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


def test_fatal_provider_failure_leaves_no_completion_footer(
    tmp_path: Path,
) -> None:
    class FatalHTTPError(Exception):
        pass

    calls = FakeCalls(_candidate_output(REFERENCE_IMPLEMENTATION))

    async def fatal_receiver(*_: Any, **__: Any) -> OpenAIProviderResult:
        raise FatalHTTPError("secret provider message")

    def classify(_: BaseException) -> ProviderErrorInfo:
        return ProviderErrorInfo(
            category="provider_http",
            status_code=401,
            request_id="req_fatal",
        )

    output = tmp_path / "partial.jsonl"
    with pytest.raises(run_runnable_openai.RunnableFatalProviderError):
        asyncio.run(
            run_runnable_openai.run_batch(
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
    assert not any(row["kind"] == "run_completed" for row in rows)
    assert run_runnable_openai.has_completed_footer(output) is False
    assert "secret provider message" not in output.read_text(encoding="utf-8")
