from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.takeover.grade import grade_response
from evals.takeover.payloads import (
    build_payloads,
    build_receiver_input,
    canonical_sender_state,
    receiver_task_prefix,
)
from evals.takeover.records import TakeoverRecord, TokenUsage
from evals.takeover.schema import TakeoverManifest, TakeoverTask
from evals.takeover.validate import DEFAULT_MANIFEST, validate_manifest
from handoff_sieve import ApproxTokenCounter, HandoffPipeline, compile_handoff


def _valid_task() -> dict[str, object]:
    return {
        "schema_version": "1",
        "id": "rr01_cursor_review",
        "route": "researcher_to_reviewer",
        "title": "Review a composite cursor",
        "sender_state": {
            "sender": "researcher",
            "receiver": "reviewer",
            "messages": [
                {
                    "kind": "constraints",
                    "content": "Existing cursors must remain valid.",
                },
                {
                    "kind": "evidence",
                    "content": "A timestamp-only cursor skips tied rows.",
                },
            ],
            "artifacts": [],
            "metadata": {},
        },
        "contract": {
            "goal": "Decide whether the cursor change is merge-ready.",
            "required": ["constraints", "evidence"],
            "preferred": [],
            "max_tokens": 400,
        },
        "receiver_instruction": "Return the review decision as JSON.",
        "receiver_output_contract": {
            "format": "json",
            "required_fields": ["verdict", "blocking_issue_ids"],
        },
        "success_validator": {
            "checks": [
                {
                    "id": "correct_verdict",
                    "path": "verdict",
                    "operator": "equals",
                    "expected": "request_changes",
                },
                {
                    "id": "finds_tie_bug",
                    "path": "blocking_issue_ids",
                    "operator": "contains_all",
                    "expected": ["timestamp_tie"],
                },
            ]
        },
    }


def test_checked_in_manifest_is_valid_and_explicitly_not_run() -> None:
    result = validate_manifest()

    assert result["status"] == "not_run"
    assert result["manifest"] == str(DEFAULT_MANIFEST)
    assert result["slots"] == 3
    assert result["planned_tasks"] == 0
    assert result["validated_tasks"] == 3


def test_task_schema_accepts_a_deterministically_gradable_task() -> None:
    task = TakeoverTask.model_validate(_valid_task())

    assert task.route == "researcher_to_reviewer"
    assert task.contract.required == ("constraints", "evidence")
    assert len(task.success_validator.checks) == 2


def test_task_schema_rejects_a_grader_path_not_in_output_contract() -> None:
    payload = _valid_task()
    payload["success_validator"] = {
        "checks": [
            {
                "id": "secret_oracle",
                "path": "hidden_answer",
                "operator": "equals",
                "expected": "do not leak this",
            }
        ]
    }

    with pytest.raises(ValidationError, match="required output fields"):
        TakeoverTask.model_validate(payload)


def test_task_schema_rejects_an_ungraded_required_output_field() -> None:
    payload = _valid_task()
    payload["success_validator"] = {
        "checks": [
            {
                "id": "correct_verdict",
                "path": "verdict",
                "operator": "equals",
                "expected": "request_changes",
            }
        ]
    }

    with pytest.raises(ValidationError, match="must have a success check"):
        TakeoverTask.model_validate(payload)


def test_manifest_rejects_results_or_a_claimed_success_rate() -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["status"] = "complete"
    payload["success_rate"] = 1.0

    with pytest.raises(ValidationError):
        TakeoverManifest.model_validate(payload)


def test_ready_slot_requires_a_matching_task_file(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["tasks"][2]["fixture_status"] = "ready"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="ready task file is missing"):
        validate_manifest(manifest_path)


def test_grader_passes_equals_and_contains_all_checks() -> None:
    task = TakeoverTask.model_validate(_valid_task())

    result = grade_response(
        task,
        json.dumps(
            {
                "verdict": "request_changes",
                "blocking_issue_ids": ["another_issue", "timestamp_tie"],
                "explanation": "Extra response fields do not affect the oracle.",
            }
        ),
    )

    assert result.overall is True
    assert [check.passed for check in result.checks] == [True, True]
    assert [check.reason for check in result.checks] == ["passed", "passed"]


def test_grader_reports_value_and_type_mismatches() -> None:
    task = TakeoverTask.model_validate(_valid_task())

    result = grade_response(
        task,
        '{"verdict":"approve","blocking_issue_ids":"timestamp_tie"}',
    )

    assert result.overall is False
    assert [check.reason for check in result.checks] == [
        "value_mismatch",
        "type_mismatch",
    ]


def test_grader_fails_missing_fields_without_skipping_other_checks() -> None:
    task = TakeoverTask.model_validate(_valid_task())

    result = grade_response(task, '{"verdict":"request_changes"}')

    assert result.overall is False
    assert result.checks[0].passed is True
    assert result.checks[1].passed is False
    assert result.checks[1].reason == "missing_field"


@pytest.mark.parametrize(
    ("receiver_json", "reason"),
    [
        ("not JSON", "malformed_json"),
        ('{"verdict":"approve","verdict":"request_changes"}', "malformed_json"),
        ('{"verdict":NaN,"blocking_issue_ids":[]}', "malformed_json"),
        ('["request_changes", ["timestamp_tie"]]', "response_not_object"),
    ],
)
def test_grader_fails_ambiguous_or_non_object_json(
    receiver_json: str,
    reason: str,
) -> None:
    task = TakeoverTask.model_validate(_valid_task())

    result = grade_response(task, receiver_json)

    assert result.overall is False
    assert all(check.passed is False for check in result.checks)
    assert {check.reason for check in result.checks} == {reason}


def test_equals_does_not_treat_boolean_as_number() -> None:
    payload = _valid_task()
    payload["receiver_output_contract"] = {
        "format": "json",
        "required_fields": ["count"],
    }
    payload["success_validator"] = {
        "checks": [
            {
                "id": "exact_count",
                "path": "count",
                "operator": "equals",
                "expected": 1,
            }
        ]
    }
    task = TakeoverTask.model_validate(payload)

    result = grade_response(task, '{"count":true}')

    assert result.overall is False
    assert result.checks[0].reason == "value_mismatch"


def test_payload_builder_uses_exact_canonical_condition_text() -> None:
    task = TakeoverTask.model_validate(_valid_task())
    task.sender_state.messages[0].tags = {"zeta", "alpha"}

    payloads = build_payloads(task)
    full_history = canonical_sender_state(task.sender_state)
    compilation = compile_handoff(
        task.sender_state,
        task.contract,
        pipeline=HandoffPipeline(token_counter=ApproxTokenCounter()),
    )

    assert payloads.full_history.payload_text == full_history
    assert '"tags":["alpha","zeta"]' in full_history
    assert payloads.handoff_sieve.payload_text == (
        compilation.packet.to_receiver_text()
    )


def test_payload_builder_counts_the_exact_text_it_returns() -> None:
    task = TakeoverTask.model_validate(_valid_task())
    counter = ApproxTokenCounter()

    payloads = build_payloads(task, token_counter=counter)

    assert payloads.full_history.local_token_estimate == counter.count_text(
        payloads.full_history.payload_text
    )
    assert payloads.handoff_sieve.local_token_estimate == counter.count_text(
        payloads.handoff_sieve.payload_text
    )
    assert payloads.naive_summary.local_token_estimate == counter.count_text(
        payloads.naive_summary.prompt_text
    )
    assert payloads.full_history.token_counter == "approx_utf8"
    assert payloads.handoff_sieve.token_counter == "approx_utf8"
    assert payloads.naive_summary.token_counter == "approx_utf8"


def test_naive_summary_boundary_is_only_a_fixed_bounded_prompt() -> None:
    task = TakeoverTask.model_validate(_valid_task())

    payloads = build_payloads(task)
    prompt = payloads.naive_summary.prompt_text

    assert payloads.naive_summary.max_output_tokens == task.contract.max_tokens
    assert task.contract.goal in prompt
    assert task.receiver_instruction in prompt
    assert "Required context categories: constraints, evidence" in prompt
    assert "Preferred context categories: none" in prompt
    assert payloads.full_history.payload_text in prompt
    assert "Return plain text only" in prompt
    assert f"Do not exceed {task.contract.max_tokens} tokens" in prompt
    assert "Do not perform the receiver's task or return its final answer" in prompt
    quoted_task = prompt.split("Receiver task (JSON string):\n", 1)[1].split("\n", 1)[0]
    assert json.loads(quoted_task) == receiver_task_prefix(task)
    assert "timestamp_tie" not in prompt
    assert not hasattr(payloads.naive_summary, "summary_text")


def test_receiver_inputs_share_the_exact_prefix_and_only_swap_context() -> None:
    task = TakeoverTask.model_validate(_valid_task())
    payloads = build_payloads(task)
    naive_summary = "Keep cursor compatibility and investigate timestamp ties."
    contexts = {
        "full_history": payloads.full_history.payload_text,
        "handoff_sieve": payloads.handoff_sieve.payload_text,
        "naive_summary": naive_summary,
    }

    receiver_inputs = {
        condition: build_receiver_input(
            task,
            condition=condition,
            context_payload=context,
        )
        for condition, context in contexts.items()
    }
    expected_prefix = receiver_task_prefix(task)

    assert {
        receiver_input.task_prefix.encode("utf-8")
        for receiver_input in receiver_inputs.values()
    } == {expected_prefix.encode("utf-8")}
    for condition, receiver_input in receiver_inputs.items():
        assert receiver_input.input_text == (
            f"{expected_prefix}\n\n<handoff_context>\n"
            f"{contexts[condition]}\n</handoff_context>"
        )
        assert receiver_input.local_token_estimate == ApproxTokenCounter().count_text(
            receiver_input.input_text
        )


def test_receiver_inputs_never_include_the_success_validator() -> None:
    task = TakeoverTask.model_validate(_valid_task())
    payloads = build_payloads(task)
    inputs = (
        build_receiver_input(
            task,
            condition="full_history",
            context_payload=payloads.full_history.payload_text,
        ),
        build_receiver_input(
            task,
            condition="handoff_sieve",
            context_payload=payloads.handoff_sieve.payload_text,
        ),
        build_receiver_input(
            task,
            condition="naive_summary",
            context_payload="Cursor compatibility and tied rows matter.",
        ),
    )

    for receiver_input in inputs:
        assert "success_validator" not in receiver_input.input_text
        assert "request_changes" not in receiver_input.input_text
        assert "timestamp_tie" not in receiver_input.input_text


def _record_base() -> dict[str, object]:
    task = TakeoverTask.model_validate(_valid_task())
    receiver_input = build_receiver_input(
        task,
        condition="full_history",
        context_payload=build_payloads(task).full_history.payload_text,
    )
    return {
        "schema_version": "1",
        "task_id": task.id,
        "condition": "full_history",
        "status": "completed",
        "recorded_at": datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc),
        "provider": "example-provider",
        "requested_model": "example-model-2026-09-01",
        "sdk_version": "1.2.3",
        "response_id": "resp_123",
        "request_id": "req_123",
        "receiver_input": receiver_input.input_text,
        "local_handoff_token_estimate": 123,
        "provider_usage": {
            "input_tokens": 180,
            "output_tokens": 20,
            "total_tokens": 200,
        },
        "naive_summary_preparation_usage": None,
        "retry_count": 0,
        "event_count": 1,
        "raw_output": (
            '{"verdict":"request_changes","blocking_issue_ids":["timestamp_tie"]}'
        ),
        "grade": grade_response(
            task,
            '{"verdict":"request_changes","blocking_issue_ids":["timestamp_tie"]}',
        ).model_dump(mode="json"),
        "error": None,
    }


def test_completed_record_keeps_auditable_evidence() -> None:
    payload = _record_base()

    record = TakeoverRecord.model_validate(payload)

    assert record.status == "completed"
    assert record.grade is not None and record.grade.overall is True
    assert record.provider_usage is not None
    assert record.provider_usage.is_complete


def test_token_usage_is_complete_or_entirely_unknown() -> None:
    assert TokenUsage() == TokenUsage(
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
    )
    assert TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3).is_complete

    with pytest.raises(ValidationError, match="fully measured or entirely unknown"):
        TokenUsage(input_tokens=1, output_tokens=None, total_tokens=1)


@pytest.mark.parametrize(
    "missing_field",
    ["raw_output", "grade", "provider_usage", "response_id"],
)
def test_completed_record_requires_success_evidence(missing_field: str) -> None:
    payload = _record_base()
    payload[missing_field] = None

    with pytest.raises(ValidationError, match="completed record requires"):
        TakeoverRecord.model_validate(payload)


def test_completed_record_allows_an_unavailable_request_id() -> None:
    payload = _record_base()
    payload["request_id"] = None

    record = TakeoverRecord.model_validate(payload)

    assert record.request_id is None


@pytest.mark.parametrize("status", ["completed", "invalid_output"])
def test_provider_response_requires_measured_usage(status: str) -> None:
    payload = _record_base()
    payload["status"] = status
    if status == "invalid_output":
        task = TakeoverTask.model_validate(_valid_task())
        payload["raw_output"] = "not JSON"
        payload["grade"] = grade_response(task, "not JSON").model_dump(mode="json")
    payload["provider_usage"] = TokenUsage().model_dump(mode="json")

    with pytest.raises(ValidationError, match="complete provider_usage"):
        TakeoverRecord.model_validate(payload)


def test_invalid_output_must_keep_failed_grade_and_raw_output() -> None:
    payload = _record_base()
    task = TakeoverTask.model_validate(_valid_task())
    payload.update(
        status="invalid_output",
        request_id=None,
        raw_output="not JSON",
        grade=grade_response(task, "not JSON").model_dump(mode="json"),
    )

    record = TakeoverRecord.model_validate(payload)

    assert record.status == "invalid_output"
    assert record.raw_output == "not JSON"
    assert record.request_id is None
    assert record.grade is not None and record.grade.overall is False


def test_failed_record_rejects_an_overall_success_grade() -> None:
    payload = _record_base()
    payload["status"] = "invalid_output"

    with pytest.raises(ValidationError, match="cannot have overall success"):
        TakeoverRecord.model_validate(payload)


def test_provider_error_keeps_unknown_ids_as_none_without_a_grade() -> None:
    payload = _record_base()
    payload.update(
        status="provider_error",
        response_id=None,
        request_id=None,
        provider_usage=None,
        raw_output=None,
        grade=None,
        error="provider timed out",
    )

    record = TakeoverRecord.model_validate(payload)

    assert record.response_id is None
    assert record.request_id is None
    assert record.provider_usage is None
    assert record.grade is None


def test_naive_summary_completed_record_requires_preparation_usage() -> None:
    payload = _record_base()
    payload["condition"] = "naive_summary"

    with pytest.raises(ValidationError, match="requires preparation usage"):
        TakeoverRecord.model_validate(payload)

    payload["naive_summary_preparation_usage"] = {
        "input_tokens": 500,
        "output_tokens": 80,
        "total_tokens": 580,
    }
    record = TakeoverRecord.model_validate(payload)
    assert record.naive_summary_preparation_usage is not None


def test_non_naive_record_rejects_summary_preparation_usage() -> None:
    payload = _record_base()
    payload["naive_summary_preparation_usage"] = {
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
    }

    with pytest.raises(ValidationError, match="only valid"):
        TakeoverRecord.model_validate(payload)


def test_summary_error_is_truthful_about_missing_receiver_input() -> None:
    payload = _record_base()
    payload.update(
        condition="naive_summary",
        status="summary_error",
        response_id=None,
        request_id=None,
        receiver_input=None,
        local_handoff_token_estimate=None,
        provider_usage=None,
        naive_summary_preparation_usage=None,
        raw_output=None,
        grade=None,
        error="summary provider rejected the request",
    )

    record = TakeoverRecord.model_validate(payload)

    assert record.status == "summary_error"
    assert record.receiver_input is None
    assert record.local_handoff_token_estimate is None


def test_record_requires_utc_and_consistent_event_counts() -> None:
    payload = _record_base()
    payload["recorded_at"] = datetime(
        2026,
        9,
        28,
        20,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        TakeoverRecord.model_validate(payload)

    payload = _record_base()
    payload["retry_count"] = 2
    payload["event_count"] = 1
    with pytest.raises(ValidationError, match="cannot exceed"):
        TakeoverRecord.model_validate(payload)
