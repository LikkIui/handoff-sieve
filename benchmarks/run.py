"""Run the fixed offline RelayGuard handoff benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from relayguard import (
    HandoffEnvelope,
    HandoffPipeline,
    Message,
    RelayGuardError,
    __version__,
)
from relayguard.models import Artifact, HandoffResult
from relayguard.pipeline import PolicyRule
from relayguard.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    MockSummarizer,
    PreservePolicy,
    RedactPolicy,
    SchemaPolicy,
    SummarizePolicy,
)
from relayguard.tokens import ApproxTokenCounter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURE_PATH = HERE / "fixtures" / "researcher_writer_v1.json"
RESULTS_PATH = HERE / "results.json"
README_PATH = ROOT / "README.md"
TABLE_START = "<!-- benchmark-results:start -->"
TABLE_END = "<!-- benchmark-results:end -->"


class ResearchPacket(BaseModel):
    """Required shape used by the schema-failure benchmark case."""

    conclusions: list[str]
    citations: list[str]


class WriterOutput(BaseModel):
    """Deterministic receiver result used to test handoff sufficiency."""

    status: Literal["passed", "failed"]
    language: str | None
    bullets: list[str]
    citations: list[str]
    conclusion: str | None
    human_approval_required: bool
    artifact_names: list[str]


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Load the public synthetic benchmark fixture."""

    fixture = json.loads(path.read_text(encoding="utf-8"))
    required_collections = (
        "secrets",
        "benign_markers",
        "constraints",
        "citations",
        "conclusions",
        "tool_pairs",
        "artifacts",
        "messages",
    )
    empty = [name for name in required_collections if not fixture.get(name)]
    if empty:
        raise ValueError(
            "benchmark fixture collections cannot be empty: " + ", ".join(empty)
        )
    source_text = _canonical_json(
        {
            name: fixture[name]
            for name in ("sender", "receiver", "messages", "artifacts", "metadata")
        }
    )
    missing_probes = [
        probe
        for probe in [*fixture["secrets"], *fixture["benign_markers"]]
        if probe not in source_text
    ]
    if missing_probes:
        raise ValueError("benchmark probes are absent from the source envelope")
    for secret in fixture.get("summary_secrets", []):
        if secret not in fixture["summary_text"] or secret in source_text:
            raise ValueError("summary secrets must occur only in summary_text")
    return fixture


def build_envelope(fixture: dict[str, Any]) -> HandoffEnvelope:
    """Create a fresh envelope so repeated runs cannot share mutations."""

    return HandoffEnvelope(
        sender=fixture["sender"],
        receiver=fixture["receiver"],
        messages=[Message.model_validate(item) for item in fixture["messages"]],
        artifacts=[Artifact.model_validate(item) for item in fixture["artifacts"]],
        metadata=fixture["metadata"],
    )


def build_pipeline(fixture: dict[str, Any]) -> HandoffPipeline:
    """Build the deterministic policy sequence used by the main scenario."""

    return HandoffPipeline(
        [
            PreservePolicy(
                tags=(
                    "constraint",
                    "citation",
                    "conclusion",
                    "tool_control",
                    "benchmark_keep",
                )
            ),
            RedactPolicy(
                detectors=("api_key", "email", "phone"),
                custom_patterns=fixture["custom_patterns"],
            ),
            ExactDedupPolicy(),
            SummarizePolicy(
                MockSummarizer(fixture["summary_text"]),
                max_tokens=fixture["summary_max_tokens"],
            ),
            RedactPolicy(
                detectors=("api_key", "email", "phone"),
                custom_patterns=fixture["custom_patterns"],
                stage="egress",
            ),
            BudgetPolicy(fixture["budget_tokens"], strategy="drop_oldest"),
        ]
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _envelope_text(result: HandoffResult) -> str:
    return _canonical_json(result.envelope.model_dump(mode="json"))


def _percent(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ValueError("benchmark percentages require a non-zero denominator")
    return round(numerator / denominator * 100, 1)


def _tool_pairs_retained(
    result: HandoffResult,
    expected_pairs: list[dict[str, str]],
) -> int:
    contents = [message.content for message in result.messages]
    retained = 0
    for pair in expected_pairs:
        call_positions = [
            index
            for index, item in enumerate(contents)
            if isinstance(item, dict)
            and item.get("type") == pair["call_type"]
            and item.get("call_id") == pair["call_id"]
        ]
        output_positions = [
            index
            for index, item in enumerate(contents)
            if isinstance(item, dict)
            and item.get("type") == pair["output_type"]
            and item.get("call_id") == pair["call_id"]
        ]
        if (
            len(call_positions) == 1
            and len(output_positions) == 1
            and call_positions[0] < output_positions[0]
        ):
            retained += 1
    return retained


def run_offline_writer(envelope: HandoffEnvelope) -> WriterOutput:
    """Consume only the receiver view and execute a fixed writer contract."""

    constraints = "\n".join(
        str(message.content)
        for message in envelope.messages
        if message.kind == "constraint"
    )
    citations = [
        str(message.content)
        for message in envelope.messages
        if message.kind == "citation"
    ]
    conclusions = [
        str(message.content)
        for message in envelope.messages
        if message.kind == "conclusion"
    ]
    language = "zh-CN" if "language=zh-CN" in constraints else None
    max_three_bullets = "max_bullets=3" in constraints
    citations_required = "citations_required=true" in constraints
    conclusion_required = "conclusion_required=true" in constraints
    approval_required = "human_approval_required=true" in constraints
    conclusion = conclusions[0] if conclusions else None
    bullets = [conclusion] if conclusion is not None else []
    artifact_names = [artifact.name for artifact in envelope.artifacts]
    citation_ids = [citation.split(maxsplit=1)[0] for citation in citations]
    citations_applied = bool(bullets) and all(
        citation_id in bullets[0] for citation_id in citation_ids
    )
    chinese_output = bool(bullets) and any(
        "\u4e00" <= char <= "\u9fff" for char in bullets[0]
    )
    passed = all(
        (
            language == "zh-CN" and chinese_output,
            max_three_bullets and len(bullets) <= 3,
            citations_required and bool(citations) and citations_applied,
            conclusion_required and conclusion is not None,
            approval_required,
            bool(artifact_names),
        )
    )
    return WriterOutput(
        status="passed" if passed else "failed",
        language=language,
        bullets=bullets,
        citations=citations,
        conclusion=conclusion,
        human_approval_required=approval_required,
        artifact_names=artifact_names,
    )


def _audit_checks(
    result: HandoffResult,
    fixture: dict[str, Any],
) -> dict[str, bool]:
    actions = {(event.policy, event.action) for event in result.report.events}
    report_json = result.report.model_dump_json()
    receiver_json = result.envelope.model_dump_json()
    forbidden = [*fixture["secrets"], *fixture.get("summary_secrets", [])]
    recounted_tokens = ApproxTokenCounter().count_envelope(result.envelope)
    redact_stages = [
        event.details.get("stage")
        for event in result.report.events
        if event.policy == "redact"
    ]
    return {
        "schema_version": result.report.schema_version == "1",
        "completed_pass": (
            result.report.status == "passed"
            and result.report.completed_at is not None
            and result.report.duration_ms is not None
        ),
        "config_fingerprint": len(result.report.config_fingerprint) == 64,
        "redaction_count": (
            result.report.redactions == fixture["expected_counts"]["redactions"]
        ),
        "deduplication_count": (
            result.report.duplicates_removed
            == fixture["expected_counts"]["duplicates_removed"]
        ),
        "summary_event": ("summarize", "summarized") in actions,
        "redaction_stages": redact_stages == ["input", "egress"],
        "budget_event": ("budget", "within_budget") in actions,
        "budget_respected": (
            result.report.transmitted_tokens <= fixture["budget_tokens"]
        ),
        "transmitted_tokens_recount": (
            result.report.transmitted_tokens == recounted_tokens
        ),
        "removed_count_consistent": (
            result.report.removed_messages >= result.report.duplicates_removed
        ),
        "local_summary_usage": (
            result.report.summarizer_input_tokens > 0
            and result.report.summarizer_output_tokens > 0
        ),
        "provider_usage_unavailable": (
            result.report.summarizer_provider_input_tokens is None
            and result.report.summarizer_provider_output_tokens is None
        ),
        "event_versions": all(event.policy_version for event in result.report.events),
        "receiver_leak_free": all(secret not in receiver_json for secret in forbidden),
        "audit_leak_free": all(secret not in report_json for secret in forbidden),
    }


def _semantic_signature(result: HandoffResult) -> str:
    report = result.report.model_dump(
        mode="json",
        exclude={"handoff_id", "started_at", "completed_at", "duration_ms"},
    )
    return _canonical_json(
        {
            "envelope": result.envelope.model_dump(mode="json"),
            "report": report,
        }
    )


def _run_failure_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = [
        {
            "name": "unmatched_route",
            "expected_code": "unmatched_route",
            "expected_policy": "config",
            "canary": "route-canary-value",
            "operation": lambda: HandoffPipeline(
                rules=[
                    PolicyRule(
                        sender="researcher",
                        receiver="writer",
                        policies=(RedactPolicy(),),
                        rule_id="researcher-to-writer",
                    )
                ]
            ).process(
                sender="researcher",
                receiver="typo-writer",
                messages=["route-canary-value"],
            ),
        },
        {
            "name": "protected_budget_overflow",
            "expected_code": "budget_exceeded",
            "expected_policy": "budget",
            "canary": "protected-canary-value",
            "operation": lambda: HandoffPipeline(
                [PreservePolicy(), BudgetPolicy(1, strategy="drop_oldest")]
            ).process(
                sender="researcher",
                receiver="writer",
                messages=[
                    "discardable",
                    Message(
                        content="protected-canary-value " * 20,
                        tags={"constraint"},
                    ),
                ],
            ),
        },
        {
            "name": "schema_failure",
            "expected_code": "validation",
            "expected_policy": "schema",
            "canary": "schema-canary-value",
            "operation": lambda: HandoffPipeline(
                [SchemaPolicy(ResearchPacket)]
            ).process(
                sender="researcher",
                receiver="writer",
                messages=[
                    Message(
                        content={"conclusions": ["schema-canary-value"]},
                        kind="structured",
                    )
                ],
            ),
        },
        {
            "name": "spoofed_protection",
            "expected_code": "reserved_field",
            "expected_policy": "normalization",
            "canary": "spoof-canary-value",
            "operation": lambda: HandoffPipeline().process(
                sender="researcher",
                receiver="writer",
                messages=[{"content": "spoof-canary-value", "protected": True}],
            ),
        },
        {
            "name": "extra_field",
            "expected_code": "validation",
            "expected_policy": "normalization",
            "canary": "extra-canary-value",
            "operation": lambda: HandoffPipeline().process(
                sender="researcher",
                receiver="writer",
                messages=[
                    {
                        "content": "extra-canary-value",
                        "unexpected": "egress",
                    }
                ],
            ),
        },
    ]
    results: list[dict[str, Any]] = []
    for case in cases:
        actual_code: str | None = None
        actual_policy: str | None = None
        checks: dict[str, bool] = {"raised_relayguard_error": False}
        try:
            operation: Callable[[], object] = case["operation"]
            operation()
        except RelayGuardError as error:
            checks["raised_relayguard_error"] = True
            if error.report is not None:
                report = error.report
                report_json = report.model_dump_json()
                actual_code = report.failure_code
                actual_policy = report.failed_policy
                denied_events = [
                    event for event in report.events if event.action == "denied"
                ]
                checks.update(
                    {
                        "status_denied": report.status == "denied",
                        "completed": (
                            report.completed_at is not None
                            and report.duration_ms is not None
                        ),
                        "failure_code": actual_code == case["expected_code"],
                        "failed_policy": actual_policy == case["expected_policy"],
                        "zero_transmitted_tokens": report.transmitted_tokens == 0,
                        "config_fingerprint": len(report.config_fingerprint) == 64,
                        "denied_event": (
                            len(denied_events) == 1
                            and denied_events[0].details.get("reason_code")
                            == case["expected_code"]
                        ),
                        "audit_leak_free": case["canary"] not in report_json,
                    }
                )
        passed = all(checks.values())
        results.append(
            {
                "name": case["name"],
                "expected_code": case["expected_code"],
                "actual_code": actual_code,
                "expected_policy": case["expected_policy"],
                "actual_policy": actual_policy,
                "passed": passed,
                "failed_checks": [name for name, ok in checks.items() if not ok],
            }
        )
    return results


def run_benchmark(*, runs: int = 5) -> dict[str, Any]:
    """Execute the fixed benchmark and return machine-readable metrics."""

    if runs < 2:
        raise ValueError("runs must be at least two to test determinism")
    fixture = load_fixture()
    pipeline = build_pipeline(fixture)
    results = [pipeline.process_envelope(build_envelope(fixture)) for _ in range(runs)]
    result = results[0]
    receiver_text = _envelope_text(result)
    report_text = result.report.model_dump_json()
    forbidden_literals = [
        *fixture["secrets"],
        *fixture.get("summary_secrets", []),
    ]

    redaction_result = HandoffPipeline(
        [
            RedactPolicy(
                detectors=("api_key", "email", "phone"),
                custom_patterns=fixture["custom_patterns"],
            )
        ]
    ).process_envelope(build_envelope(fixture))
    redacted_text = _envelope_text(redaction_result)

    secrets_removed = sum(secret not in redacted_text for secret in fixture["secrets"])
    benign_retained = sum(
        marker in redacted_text for marker in fixture["benign_markers"]
    )
    contents_by_kind = {
        kind: [
            message.content
            for message in result.messages
            if message.kind == kind and isinstance(message.content, str)
        ]
        for kind in ("constraint", "citation", "conclusion")
    }
    constraints_retained = sum(
        contents_by_kind["constraint"].count(item) == 1
        for item in fixture["constraints"]
    )
    citations_retained = sum(
        contents_by_kind["citation"].count(item) == 1 for item in fixture["citations"]
    )
    conclusions_retained = sum(
        contents_by_kind["conclusion"].count(item) == 1
        for item in fixture["conclusions"]
    )
    tool_pairs_retained = _tool_pairs_retained(result, fixture["tool_pairs"])
    artifact_names = [artifact.name for artifact in result.envelope.artifacts]
    artifact_retained = all(
        artifact_names.count(artifact["name"]) == 1 for artifact in fixture["artifacts"]
    )
    receiver_secret_leaks = sum(
        secret in receiver_text for secret in forbidden_literals
    )
    audit_secret_leaks = sum(secret in report_text for secret in forbidden_literals)
    writer_output = run_offline_writer(result.envelope)
    writer_expected = fixture["writer_expected"]
    downstream_checks = {
        "writer_passed": writer_output.status == "passed",
        "language": writer_output.language == writer_expected["language"],
        "bounded_bullets": writer_output.bullets == [writer_expected["conclusion"]],
        "citations": writer_output.citations == writer_expected["citations"],
        "conclusion": writer_output.conclusion == writer_expected["conclusion"],
        "human_approval": writer_output.human_approval_required,
        "artifact": (
            artifact_retained
            and writer_expected["artifact_name"] in writer_output.artifact_names
        ),
        "receiver_leak_free": receiver_secret_leaks == 0,
    }
    downstream_success = all(downstream_checks.values())
    signatures = [_semantic_signature(item) for item in results]
    deterministic_runs = sum(signature == signatures[0] for signature in signatures)
    audit_checks = _audit_checks(result, fixture)
    failure_cases = _run_failure_cases()
    failure_cases_passed = sum(item["passed"] for item in failure_cases)
    false_positives = len(fixture["benign_markers"]) - benign_retained
    latencies = sorted(item.report.duration_ms or 0.0 for item in results)
    latency_p95 = latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)]

    metrics = {
        "source_secret_recall_percent": _percent(
            secrets_removed, len(fixture["secrets"])
        ),
        "receiver_secret_leaks": receiver_secret_leaks,
        "audit_secret_leaks": audit_secret_leaks,
        "false_positive_rate_percent": _percent(
            false_positives, len(fixture["benign_markers"])
        ),
        "constraint_retention_percent": _percent(
            constraints_retained, len(fixture["constraints"])
        ),
        "citation_retention_percent": _percent(
            citations_retained, len(fixture["citations"])
        ),
        "conclusion_retention_percent": _percent(
            conclusions_retained, len(fixture["conclusions"])
        ),
        "downstream_task_success_percent": 100.0 if downstream_success else 0.0,
        "tool_pair_integrity_percent": _percent(
            tool_pairs_retained, len(fixture["tool_pairs"])
        ),
        "deterministic_runs_percent": _percent(deterministic_runs, runs),
        "audit_completeness_percent": _percent(
            sum(audit_checks.values()), len(audit_checks)
        ),
        "failure_case_audit_percent": _percent(
            failure_cases_passed, len(failure_cases)
        ),
        "original_tokens": result.report.original_tokens,
        "transmitted_tokens": result.report.transmitted_tokens,
        "summarizer_estimated_tokens": (
            result.report.summarizer_input_tokens
            + result.report.summarizer_output_tokens
        ),
        "estimated_net_tokens_saved": result.report.estimated_net_tokens_saved,
        "pipeline_latency_p50_ms": round(statistics.median(latencies), 3),
        "pipeline_latency_p95_ms": round(latency_p95, 3),
    }
    acceptance_checks = {
        "source_secret_recall": metrics["source_secret_recall_percent"] == 100.0,
        "receiver_leak_free": receiver_secret_leaks == 0,
        "audit_leak_free": audit_secret_leaks == 0,
        "false_positive_rate": metrics["false_positive_rate_percent"] == 0.0,
        "constraint_retention": metrics["constraint_retention_percent"] == 100.0,
        "citation_retention": metrics["citation_retention_percent"] == 100.0,
        "conclusion_retention": metrics["conclusion_retention_percent"] == 100.0,
        "downstream_task": downstream_success,
        "tool_pair_integrity": metrics["tool_pair_integrity_percent"] == 100.0,
        "determinism": deterministic_runs == runs,
        "audit_completeness": metrics["audit_completeness_percent"] == 100.0,
        "failure_audits": failure_cases_passed == len(failure_cases),
        "hard_budget": result.report.transmitted_tokens <= fixture["budget_tokens"],
        "positive_net_token_savings": result.report.estimated_net_tokens_saved > 0,
        "latency_slo": latency_p95 <= 500.0,
    }
    benchmark_result = {
        "schema_version": "1",
        "fixture": fixture["scenario_id"],
        "fixture_sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        "pipeline": {
            "config_fingerprint": pipeline.config_fingerprint,
            "token_counter": pipeline.token_counter.name,
            "relayguard_version": __version__,
        },
        "runs": runs,
        "metrics": metrics,
        "counts": {
            "secrets": len(fixture["secrets"]),
            "secrets_removed": secrets_removed,
            "summary_secrets": len(fixture.get("summary_secrets", [])),
            "receiver_secret_leaks": receiver_secret_leaks,
            "audit_secret_leaks": audit_secret_leaks,
            "benign_markers": len(fixture["benign_markers"]),
            "false_positives": false_positives,
            "constraints": len(fixture["constraints"]),
            "constraints_retained": constraints_retained,
            "citations": len(fixture["citations"]),
            "citations_retained": citations_retained,
            "conclusions": len(fixture["conclusions"]),
            "conclusions_retained": conclusions_retained,
            "tool_pairs": len(fixture["tool_pairs"]),
            "tool_pairs_retained": tool_pairs_retained,
            "deterministic_runs": deterministic_runs,
            "failure_cases": len(failure_cases),
            "failure_cases_passed": failure_cases_passed,
            "audit_checks": len(audit_checks),
            "audit_checks_passed": sum(audit_checks.values()),
        },
        "writer_output": writer_output.model_dump(mode="json"),
        "checks": {
            "audit": audit_checks,
            "downstream": downstream_checks,
        },
        "failure_cases": failure_cases,
        "acceptance": {
            "passed": all(acceptance_checks.values()),
            "checks": acceptance_checks,
            "failed_checks": [
                name for name, passed in acceptance_checks.items() if not passed
            ],
        },
    }
    return benchmark_result


def stable_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Remove the machine-dependent timing value for snapshot comparison."""

    projected = json.loads(json.dumps(result))
    projected["metrics"].pop("pipeline_latency_p50_ms", None)
    projected["metrics"].pop("pipeline_latency_p95_ms", None)
    return projected


def render_readme_table(result: dict[str, Any]) -> str:
    """Render the README block directly from benchmark output."""

    metrics = result["metrics"]
    counts = result["counts"]
    rows = [
        (
            "Source secret/PII recall",
            f"{metrics['source_secret_recall_percent']:.1f}% "
            f"({counts['secrets_removed']}/{counts['secrets']})",
        ),
        (
            "Receiver / audit secret leaks",
            f"{metrics['receiver_secret_leaks']} / {metrics['audit_secret_leaks']}",
        ),
        (
            "Labelled false-positive rate",
            f"{metrics['false_positive_rate_percent']:.1f}% "
            f"({counts['false_positives']}/{counts['benign_markers']})",
        ),
        (
            "Constraint retention",
            f"{metrics['constraint_retention_percent']:.1f}% "
            f"({counts['constraints_retained']}/{counts['constraints']})",
        ),
        (
            "Citation retention",
            f"{metrics['citation_retention_percent']:.1f}% "
            f"({counts['citations_retained']}/{counts['citations']})",
        ),
        (
            "Conclusion retention",
            f"{metrics['conclusion_retention_percent']:.1f}% "
            f"({counts['conclusions_retained']}/{counts['conclusions']})",
        ),
        (
            "Downstream task success",
            f"{metrics['downstream_task_success_percent']:.1f}% (1/1)",
        ),
        (
            "Tool-pair integrity",
            f"{metrics['tool_pair_integrity_percent']:.1f}% "
            f"({counts['tool_pairs_retained']}/{counts['tool_pairs']})",
        ),
        (
            "Deterministic runs",
            f"{counts['deterministic_runs']}/{result['runs']}",
        ),
        (
            "Audited failure cases",
            f"{counts['failure_cases_passed']}/{counts['failure_cases']}",
        ),
        ("Audit completeness", f"{metrics['audit_completeness_percent']:.1f}%"),
        (
            "Estimated tokens",
            f"{metrics['original_tokens']} original → "
            f"{metrics['transmitted_tokens']} transmitted; "
            f"{metrics['summarizer_estimated_tokens']} summarizer; "
            f"{metrics['estimated_net_tokens_saved']} net saved",
        ),
        (
            "Pipeline latency",
            f"p50 {metrics['pipeline_latency_p50_ms']:.3f} ms; "
            f"p95 {metrics['pipeline_latency_p95_ms']:.3f} ms "
            "on the generating machine",
        ),
    ]
    table = [
        TABLE_START,
        "| Fixed offline benchmark metric | Result |",
        "|---|---:|",
        *(f"| {name} | {value} |" for name, value in rows),
        TABLE_END,
    ]
    return "\n".join(table)


def write_outputs(result: dict[str, Any]) -> None:
    """Write the JSON result and replace the generated README table."""

    RESULTS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = README_PATH.read_text(encoding="utf-8")
    if TABLE_START not in readme or TABLE_END not in readme:
        raise RuntimeError("README benchmark markers are missing")
    before, remainder = readme.split(TABLE_START, maxsplit=1)
    _, after = remainder.split(TABLE_END, maxsplit=1)
    rendered = render_readme_table(result)
    README_PATH.write_text(before + rendered + after, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument(
        "--write",
        action="store_true",
        help="update benchmarks/results.json and the generated README table",
    )
    output_mode.add_argument(
        "--check",
        action="store_true",
        help="fail if stable benchmark results or the README table are stale",
    )
    parser.add_argument("--runs", type=int, default=5)
    arguments = parser.parse_args()
    result = run_benchmark(runs=arguments.runs)
    if not result["acceptance"]["passed"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        failed = ", ".join(result["acceptance"]["failed_checks"])
        raise SystemExit(f"benchmark acceptance failed: {failed}")
    if arguments.write:
        write_outputs(result)
    if arguments.check:
        reference = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        if stable_projection(result) != stable_projection(reference):
            raise SystemExit("benchmark reference is stale; run with --write")
        expected_table = render_readme_table(reference)
        readme = README_PATH.read_text(encoding="utf-8")
        if expected_table not in readme:
            raise SystemExit("README benchmark table is stale; run with --write")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
