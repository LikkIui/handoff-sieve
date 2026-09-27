from __future__ import annotations

import json
from pathlib import Path

import pytest

from relayguard import (
    AuditExportError,
    CallbackReporter,
    HandoffPipeline,
    JsonlReporter,
)
from relayguard.exceptions import BudgetExceededError, ReservedFieldError
from relayguard.models import HandoffEnvelope
from relayguard.policies import BudgetPolicy, Policy, SummarizePolicy, Summary
from relayguard.policies.base import PolicyContext


def test_callback_receives_completed_isolated_report_without_content() -> None:
    reports = []
    pipeline = HandoffPipeline(reporters=[CallbackReporter(reports.append)])

    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["secret payload that must not enter the audit report"],
        request_id="request-123",
    )

    assert len(reports) == 1
    exported = reports[0]
    assert exported is not result.report
    assert exported.handoff_id == result.report.handoff_id
    assert exported.request_id == "request-123"
    assert exported.status == "passed"
    assert exported.completed_at is not None
    assert exported.completed_at >= exported.started_at
    assert exported.duration_ms is not None
    assert exported.duration_ms >= 0
    assert len(exported.config_fingerprint) == 64
    assert "secret payload" not in exported.model_dump_json()

    exported.warnings.append("callback mutation")
    assert result.report.warnings == []


def test_denied_handoff_is_exported_with_same_correlation_id() -> None:
    reports = []
    pipeline = HandoffPipeline(
        [BudgetPolicy(1, strategy="error")],
        reporters=[CallbackReporter(reports.append)],
    )

    with pytest.raises(BudgetExceededError) as captured:
        pipeline.process(
            sender="a",
            receiver="b",
            messages=["too large"],
            request_id="request-denied",
        )

    assert captured.value.report is not None
    assert len(reports) == 1
    exported = reports[0]
    assert exported.handoff_id == captured.value.report.handoff_id
    assert exported.request_id == "request-denied"
    assert exported.status == "denied"
    assert exported.failure_code == "budget_exceeded"
    assert exported.completed_at is not None


def test_normalization_denial_is_finalized_and_exported() -> None:
    reports = []
    pipeline = HandoffPipeline(reporters=[CallbackReporter(reports.append)])

    with pytest.raises(ReservedFieldError):
        pipeline.process(
            sender="a",
            receiver="b",
            messages=[{"content": "spoofed", "protected": True}],
        )

    assert len(reports) == 1
    assert reports[0].status == "denied"
    assert reports[0].failure_code == "reserved_field"
    assert reports[0].failed_policy == "normalization"
    assert reports[0].completed_at is not None


def test_jsonl_reporter_appends_versioned_success_and_failure_records(
    tmp_path: Path,
) -> None:
    output = tmp_path / "audit.jsonl"
    reporter = JsonlReporter(output)
    HandoffPipeline(reporters=[reporter]).process(
        sender="a",
        receiver="b",
        messages=["private message body"],
    )
    with pytest.raises(BudgetExceededError):
        HandoffPipeline(
            [BudgetPolicy(1, strategy="error")],
            reporters=[reporter],
        ).process(sender="a", receiver="b", messages=["too large"])

    records = [json.loads(line) for line in output.read_text("utf-8").splitlines()]
    assert [record["status"] for record in records] == ["passed", "denied"]
    assert all(record["schema_version"] == "1" for record in records)
    assert all(record["completed_at"] for record in records)
    assert "private message body" not in output.read_text("utf-8")


class FailingReporter:
    def emit(self, report) -> None:
        raise RuntimeError("storage unavailable")


def test_reporter_failure_denies_an_otherwise_successful_handoff() -> None:
    pipeline = HandoffPipeline(reporters=[FailingReporter()])

    with pytest.raises(AuditExportError) as captured:
        pipeline.process(sender="a", receiver="b", messages=["hello"])

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "audit_export"
    assert captured.value.report.failed_policy == "audit"
    assert captured.value.report.completed_at is not None


def test_reporter_failure_does_not_mask_original_denial() -> None:
    fallback_reports = []
    pipeline = HandoffPipeline(
        [BudgetPolicy(1, strategy="error")],
        reporters=[FailingReporter(), CallbackReporter(fallback_reports.append)],
    )

    with pytest.raises(BudgetExceededError) as captured:
        pipeline.process(sender="a", receiver="b", messages=["too large"])

    assert captured.value.report is not None
    assert captured.value.report.failure_code == "budget_exceeded"
    assert any("FailingReporter" in item for item in captured.value.report.warnings)
    assert len(fallback_reports) == 1
    assert fallback_reports[0].failure_code == "budget_exceeded"
    assert any("FailingReporter" in item for item in fallback_reports[0].warnings)


class UsageSummarizer:
    def summarize(self, messages, *, max_tokens, token_counter) -> Summary:
        return Summary(text="brief", input_tokens=900, output_tokens=100)


def test_summarizer_estimates_and_provider_usage_are_separate() -> None:
    result = HandoffPipeline(
        [SummarizePolicy(UsageSummarizer(), max_tokens=20)]
    ).process(sender="a", receiver="b", messages=["source material"])

    assert result.report.summarizer_input_tokens > 0
    assert result.report.summarizer_output_tokens > 0
    assert result.report.summarizer_input_tokens != 900
    assert result.report.summarizer_provider_input_tokens == 900
    assert result.report.summarizer_provider_output_tokens == 100


class VersionedPolicy(Policy):
    name = "versioned"
    version = "7"

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        context.report.add_event(self.name, "checked")
        return envelope


def test_policy_version_and_configuration_fingerprint_are_auditable() -> None:
    first = HandoffPipeline([VersionedPolicy(), BudgetPolicy(100)])
    same = HandoffPipeline([VersionedPolicy(), BudgetPolicy(100)])
    changed = HandoffPipeline([VersionedPolicy(), BudgetPolicy(200)])

    result = first.process(sender="a", receiver="b", messages=[])

    assert result.report.events[0].policy_version == "7"
    assert first.config_fingerprint == same.config_fingerprint
    assert first.config_fingerprint != changed.config_fingerprint
