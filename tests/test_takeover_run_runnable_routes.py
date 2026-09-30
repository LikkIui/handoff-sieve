from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evals.takeover import run_runnable_openai
from evals.takeover.openai_provider import OpenAIProviderResult, ProviderErrorInfo
from evals.takeover.runnable.taskpack import TASKPACK


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


class _FakeCalls:
    def __init__(self, receiver_output: str) -> None:
        self.receiver_output = receiver_output
        self.summary_inputs: list[str] = []
        self.receiver_inputs: list[str] = []

    async def call_summary(
        self,
        _model: str,
        prompt: str,
        *,
        max_output_tokens: int,
        **_: Any,
    ) -> OpenAIProviderResult:
        assert max_output_tokens > 0
        self.summary_inputs.append(prompt)
        return _result("short task-aware summary", "summary")

    async def call_receiver(
        self,
        _model: str,
        receiver_input: str,
        *,
        max_output_tokens: int,
        **_: Any,
    ) -> OpenAIProviderResult:
        assert max_output_tokens > 0
        self.receiver_inputs.append(receiver_input)
        return _result(self.receiver_output, f"receiver_{len(self.receiver_inputs)}")


def _neutral_classifier(_: BaseException) -> ProviderErrorInfo:
    return ProviderErrorInfo(category="provider_connection", retryable=True)


def _run(
    tmp_path: Path,
    *,
    task_id: str,
    receiver_output: str,
) -> tuple[_FakeCalls, list[dict[str, Any]]]:
    calls = _FakeCalls(receiver_output)
    output = tmp_path / f"{task_id}.jsonl"
    count = asyncio.run(
        run_runnable_openai.run_batch(
            model="test-model",
            output=output,
            sdk_version="fake-sdk",
            task_id=task_id,
            call_summary=calls.call_summary,
            call_receiver=calls.call_receiver,
            classify_error=_neutral_classifier,
        )
    )
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert count == 3
    assert run_runnable_openai.has_completed_footer(output)
    return calls, rows


def _pe01_sources() -> tuple[str, str]:
    spec = run_runnable_openai._SPECS["pe01_streaming_csv"]
    api = (spec.starter / "task_app" / "reports" / "api.py").read_text(encoding="utf-8")
    api = api.replace(
        "from typing import Protocol\n",
        "from typing import Protocol\n\n"
        "from .csv_response import CSV_CONTENT_TYPE, stream_csv\n",
    ).replace(
        "        # Import and connect the existing ``stream_csv`` helper without\n"
        "        # consuming rows here. The response body itself must remain lazy.\n"
        "        raise NotImplementedError\n",
        "        return ReportResponse(CSV_CONTENT_TYPE, stream_csv(rows), True)\n",
    )
    csv_source = """\
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator, Mapping

CSV_COLUMNS = ("id", "name", "total")
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


def stream_csv(rows: Iterable[Mapping[str, object]]) -> Iterator[bytes]:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_COLUMNS,
        extrasaction="ignore",
        lineterminator="\\r\\n",
    )
    writer.writeheader()
    yield buffer.getvalue().encode("utf-8")
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow(row)
        yield buffer.getvalue().encode("utf-8")
"""
    return api, csv_source


def _assert_three_fair_successes(
    task_id: str,
    calls: _FakeCalls,
    rows: list[dict[str, Any]],
    expected_check_ids: tuple[str, ...],
) -> None:
    assert rows[0]["kind"] == "run_started"
    assert rows[0]["task_id"] == task_id
    assert rows[0]["acceptance_check_ids"] == list(expected_check_ids)
    assert rows[-1]["kind"] == "run_completed"
    observations = rows[1:-1]
    assert len(calls.summary_inputs) == 1
    assert len(calls.receiver_inputs) == 3
    assert [row["condition"] for row in observations] == [
        "full_history",
        "naive_summary",
        "handoff_sieve",
    ]
    assert len({row["task_prefix"] for row in observations}) == 1
    assert len({row["receiver_input"] for row in observations}) == 3
    for row in observations:
        assert row["status"] == "completed"
        assert row["downstream_success"] is True
        assert [check["id"] for check in row["checks"]] == list(expected_check_ids)
        assert all(check["passed"] for check in row["checks"])
        assert row["local_handoff_token_estimate"] > 0
        assert "success_validator" not in row["receiver_input"]


def test_cli_passes_selected_route_to_the_shared_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_batch(**kwargs: object) -> int:
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(run_runnable_openai, "_preflight_openai", lambda: "fake-sdk")
    monkeypatch.setattr(run_runnable_openai, "run_batch", fake_batch)
    output = tmp_path / "selected-route.jsonl"

    result = run_runnable_openai.main(
        [
            "--run",
            "--model",
            "test-model",
            "--output",
            str(output),
            "--task-id",
            "pe01_streaming_csv",
        ]
    )

    assert result == 0
    assert captured["task_id"] == "pe01_streaming_csv"
    assert captured["task_path"] is None


def test_pe01_runs_two_generated_files_through_all_three_conditions(
    tmp_path: Path,
) -> None:
    api, csv_source = _pe01_sources()
    raw_output = json.dumps(
        {"api_py": api, "csv_response_py": csv_source},
        ensure_ascii=False,
    )

    calls, rows = _run(
        tmp_path,
        task_id="pe01_streaming_csv",
        receiver_output=raw_output,
    )

    _assert_three_fair_successes(
        "pe01_streaming_csv",
        calls,
        rows,
        run_runnable_openai.PE01_CHECK_IDS,
    )
    assert all(row["candidate_source_bytes"] > 0 for row in rows[1:-1])
    assert all(row["derived_blocking_issue_ids"] is None for row in rows[1:-1])


def test_rr01_grades_review_against_behavior_derived_blockers(tmp_path: Path) -> None:
    raw_output = json.dumps(
        {
            "candidate_id": "cursor_patch_v3",
            "verdict": "request_changes",
            "blocking_issue_ids": ["cursor_tie_skip"],
        }
    )

    calls, rows = _run(
        tmp_path,
        task_id="rr01_cursor_review",
        receiver_output=raw_output,
    )

    _assert_three_fair_successes(
        "rr01_cursor_review",
        calls,
        rows,
        run_runnable_openai.RR01_CHECK_IDS,
    )
    assert all(
        row["derived_blocking_issue_ids"] == ["cursor_tie_skip"] for row in rows[1:-1]
    )
    assert all(row["candidate_source_bytes"] is None for row in rows[1:-1])


def test_expanded_source_task_uses_the_shared_three_condition_runner(
    tmp_path: Path,
) -> None:
    task = TASKPACK["rc02_retry_after"]
    raw_output = json.dumps(
        {file.output_field: file.reference_source for file in task.files}
    )

    calls, rows = _run(
        tmp_path,
        task_id=task.task_id,
        receiver_output=raw_output,
    )

    _assert_three_fair_successes(task.task_id, calls, rows, task.check_ids)
    assert all(row["candidate_source_bytes"] > 0 for row in rows[1:-1])


def test_expanded_review_task_uses_behavior_derived_blockers(
    tmp_path: Path,
) -> None:
    task = TASKPACK["rr02_falsy_config_review"]
    raw_output = json.dumps(
        {
            "candidate_id": task.candidate_id,
            "verdict": "request_changes",
            "blocking_issue_ids": ["FALSY_OVERRIDE"],
        }
    )

    calls, rows = _run(
        tmp_path,
        task_id=task.task_id,
        receiver_output=raw_output,
    )

    _assert_three_fair_successes(task.task_id, calls, rows, task.check_ids)
    assert all(
        row["derived_blocking_issue_ids"] == ["FALSY_OVERRIDE"] for row in rows[1:-1]
    )


@pytest.mark.parametrize(
    "parser,raw",
    [
        (
            run_runnable_openai.parse_pe01_sources,
            '{"api_py":"pass","csv_response_py":"pass","extra":1}',
        ),
        (
            run_runnable_openai.parse_pe01_sources,
            '{"api_py":"first","api_py":"second","csv_response_py":"pass"}',
        ),
        (
            run_runnable_openai.parse_review_submission,
            '{"candidate_id":"x","verdict":"maybe","blocking_issue_ids":[]}',
        ),
        (
            run_runnable_openai.parse_review_submission,
            '{"candidate_id":"x","verdict":"approve","blocking_issue_ids":["x","x"]}',
        ),
    ],
)
def test_route_output_parsers_reject_ambiguous_shapes(
    parser: Any,
    raw: str,
) -> None:
    with pytest.raises(run_runnable_openai.CandidateOutputError):
        parser(raw)
