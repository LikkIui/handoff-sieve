"""Run the three-condition takeover pilot only after an explicit CLI opt-in."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, TextIO

from pydantic import ValidationError

from evals.takeover import openai_provider
from evals.takeover.grade import GradeResult, grade_response
from evals.takeover.openai_provider import (
    OpenAIProviderResult,
    ProviderErrorInfo,
)
from evals.takeover.payloads import (
    ConditionName,
    TakeoverPayloads,
    build_payloads,
    build_receiver_input,
)
from evals.takeover.records import TakeoverRecord, TokenUsage
from evals.takeover.schema import TakeoverManifest, TakeoverTask
from handoff_sieve import ApproxTokenCounter

DEFAULT_MANIFEST = Path(__file__).with_name("manifest.json")
_PROVIDER = "openai"
_RECEIVER_MAX_OUTPUT_TOKENS = 512
_FATAL_ERROR_CATEGORIES = frozenset(
    {"dependency_missing", "usage_missing", "protocol_error"}
)
_FATAL_HTTP_STATUS_CODES = frozenset({400, 401, 403, 404, 422})
_INVALID_GRADE_REASONS = frozenset(
    {"malformed_json", "response_not_object", "missing_field", "type_mismatch"}
)
_CONDITIONS: tuple[ConditionName, ...] = (
    "full_history",
    "naive_summary",
    "handoff_sieve",
)

ProviderCall = Callable[..., Awaitable[OpenAIProviderResult]]
ErrorClassifier = Callable[[BaseException], ProviderErrorInfo]


class BatchConfigurationError(RuntimeError):
    """Raised before a valid provider-backed batch can start or continue."""


class BatchFatalProviderError(RuntimeError):
    """Raised for authentication, access, or integration configuration errors."""

    def __init__(self, info: ProviderErrorInfo) -> None:
        self.info = info
        super().__init__("fatal provider configuration error: " + _error_code(info))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BatchConfigurationError(f"missing evaluation file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BatchConfigurationError(f"invalid evaluation JSON: {path}") from exc


def load_ready_tasks(manifest_path: Path = DEFAULT_MANIFEST) -> list[TakeoverTask]:
    """Load the three manifest tasks, refusing incomplete pilot slots."""

    try:
        manifest = TakeoverManifest.model_validate(_load_json(manifest_path))
    except ValidationError as exc:
        raise BatchConfigurationError("invalid takeover manifest") from exc
    if any(slot.fixture_status != "ready" for slot in manifest.tasks):
        raise BatchConfigurationError("all three takeover pilot tasks must be ready")

    tasks: list[TakeoverTask] = []
    for slot in manifest.tasks:
        relative_path = Path(*slot.task_file.split("/"))
        try:
            task = TakeoverTask.model_validate(
                _load_json(manifest_path.parent / relative_path)
            )
        except ValidationError as exc:
            raise BatchConfigurationError(f"invalid takeover task: {slot.id}") from exc
        if task.id != slot.id or task.route != slot.route:
            raise BatchConfigurationError(
                f"task does not match manifest slot: {slot.id}/{slot.route}"
            )
        tasks.append(task)
    return tasks


def _write_line(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    stream.flush()


def _usage(result: OpenAIProviderResult) -> TokenUsage:
    return TokenUsage(
        input_tokens=result.provider_input_tokens,
        output_tokens=result.provider_output_tokens,
        total_tokens=result.provider_total_tokens,
    )


def _error_code(info: ProviderErrorInfo) -> str:
    parts: list[str] = [info.category]
    if info.status_code is not None:
        parts.append(str(info.status_code))
    return ":".join(parts)


def _is_fatal_error(error: BaseException, info: ProviderErrorInfo) -> bool:
    if isinstance(error, (ValueError, TypeError)):
        return True
    if info.category in _FATAL_ERROR_CATEGORIES:
        return True
    return (
        info.category == "provider_http"
        and info.status_code in _FATAL_HTTP_STATUS_CODES
    )


def _classify_or_raise(
    error: BaseException,
    classify_error: ErrorClassifier,
) -> ProviderErrorInfo:
    info = classify_error(error)
    if _is_fatal_error(error, info):
        raise BatchFatalProviderError(info) from error
    return info


def _grade_status(grade: GradeResult) -> Literal["completed", "invalid_output"]:
    if any(check.reason in _INVALID_GRADE_REASONS for check in grade.checks):
        return "invalid_output"
    return "completed"


def _record_payload(record: TakeoverRecord) -> dict[str, Any]:
    return {"kind": "observation", **record.model_dump(mode="json")}


def _condition_order(task_index: int) -> tuple[ConditionName, ...]:
    offset = task_index % len(_CONDITIONS)
    return _CONDITIONS[offset:] + _CONDITIONS[:offset]


def _summary_error_record(
    *,
    task: TakeoverTask,
    model: str,
    sdk_version: str,
    error: str,
    result: OpenAIProviderResult | None = None,
    info: ProviderErrorInfo | None = None,
) -> TakeoverRecord:
    return TakeoverRecord(
        task_id=task.id,
        condition="naive_summary",
        status="summary_error",
        recorded_at=_utcnow(),
        provider=_PROVIDER,
        requested_model=model,
        sdk_version=sdk_version,
        response_id=result.response_id if result is not None else None,
        request_id=(
            result.request_id
            if result is not None
            else info.request_id
            if info is not None
            else None
        ),
        receiver_input=None,
        local_handoff_token_estimate=None,
        provider_usage=None,
        naive_summary_preparation_usage=(
            _usage(result) if result is not None else None
        ),
        retry_count=0,
        event_count=result.event_count if result is not None else 1,
        raw_output=result.raw_output if result is not None else None,
        grade=None,
        error=error,
    )


async def _receiver_record(
    *,
    task: TakeoverTask,
    condition: ConditionName,
    context_payload: str,
    model: str,
    sdk_version: str,
    preparation_result: OpenAIProviderResult | None,
    call_receiver: ProviderCall,
    classify_error: ErrorClassifier,
) -> TakeoverRecord:
    receiver_input = build_receiver_input(
        task,
        condition=condition,
        context_payload=context_payload,
    )
    preparation_usage = (
        _usage(preparation_result) if preparation_result is not None else None
    )
    preparation_events = (
        preparation_result.event_count if preparation_result is not None else 0
    )

    try:
        result = await call_receiver(
            model,
            receiver_input.input_text,
            max_output_tokens=_RECEIVER_MAX_OUTPUT_TOKENS,
        )
    except Exception as error:
        info = _classify_or_raise(error, classify_error)
        return TakeoverRecord(
            task_id=task.id,
            condition=condition,
            status="provider_error",
            recorded_at=_utcnow(),
            provider=_PROVIDER,
            requested_model=model,
            sdk_version=sdk_version,
            response_id=None,
            request_id=info.request_id,
            receiver_input=receiver_input.input_text,
            local_handoff_token_estimate=receiver_input.local_token_estimate,
            provider_usage=None,
            naive_summary_preparation_usage=preparation_usage,
            retry_count=0,
            event_count=preparation_events + 1,
            raw_output=None,
            grade=None,
            error="provider_error:" + _error_code(info),
        )

    grade = grade_response(task, result.raw_output)
    return TakeoverRecord(
        task_id=task.id,
        condition=condition,
        status=_grade_status(grade),
        recorded_at=_utcnow(),
        provider=_PROVIDER,
        requested_model=model,
        sdk_version=sdk_version,
        response_id=result.response_id,
        request_id=result.request_id,
        receiver_input=receiver_input.input_text,
        local_handoff_token_estimate=receiver_input.local_token_estimate,
        provider_usage=_usage(result),
        naive_summary_preparation_usage=preparation_usage,
        retry_count=0,
        event_count=preparation_events + result.event_count,
        raw_output=result.raw_output,
        grade=grade,
        error=None,
    )


async def _prepare_summary(
    *,
    task: TakeoverTask,
    payloads: TakeoverPayloads,
    model: str,
    sdk_version: str,
    call_summary: ProviderCall,
    classify_error: ErrorClassifier,
) -> tuple[str | None, int | None, OpenAIProviderResult | None, TakeoverRecord | None]:
    try:
        result = await call_summary(
            model,
            payloads.naive_summary.prompt_text,
            max_output_tokens=payloads.naive_summary.max_output_tokens,
        )
    except Exception as error:
        info = _classify_or_raise(error, classify_error)
        record = _summary_error_record(
            task=task,
            model=model,
            sdk_version=sdk_version,
            error="summary_error:" + _error_code(info),
            info=info,
        )
        return None, None, None, record

    summary_tokens = ApproxTokenCounter().count_text(result.raw_output)
    if summary_tokens > task.contract.max_tokens:
        record = _summary_error_record(
            task=task,
            model=model,
            sdk_version=sdk_version,
            error="summary_over_budget",
            result=result,
        )
        return None, None, None, record
    return result.raw_output, summary_tokens, result, None


async def run_batch(
    *,
    model: str,
    output: Path,
    sdk_version: str,
    manifest: Path = DEFAULT_MANIFEST,
    call_receiver: ProviderCall | None = None,
    call_summary: ProviderCall | None = None,
    classify_error: ErrorClassifier | None = None,
) -> int:
    """Run all ready pilot tasks and append one flushed JSON object per line."""

    cleaned_model = model.strip()
    if not cleaned_model:
        raise BatchConfigurationError("model cannot be blank")
    if not sdk_version.strip():
        raise BatchConfigurationError("sdk_version cannot be blank")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    tasks = load_ready_tasks(manifest)
    receiver_call = call_receiver or openai_provider.call_receiver
    summary_call = call_summary or openai_provider.call_summary
    error_classifier = classify_error or openai_provider.classify_provider_error
    run_id = str(uuid.uuid4())
    record_count = 0

    with output.open("x", encoding="utf-8", newline="\n") as stream:
        _write_line(
            stream,
            {
                "kind": "run_started",
                "schema_version": "1",
                "run_id": run_id,
                "started_at": _utcnow().isoformat(),
                "provider": _PROVIDER,
                "requested_model": cleaned_model,
                "sdk_version": sdk_version,
                "task_ids": [task.id for task in tasks],
                "conditions": list(_CONDITIONS),
                "condition_orders": {
                    task.id: list(_condition_order(index))
                    for index, task in enumerate(tasks)
                },
            },
        )

        for task_index, task in enumerate(tasks):
            payloads = build_payloads(task)
            (
                summary,
                summary_tokens,
                summary_result,
                summary_error,
            ) = await _prepare_summary(
                task=task,
                payloads=payloads,
                model=cleaned_model,
                sdk_version=sdk_version,
                call_summary=summary_call,
                classify_error=error_classifier,
            )
            for condition in _condition_order(task_index):
                if condition == "naive_summary" and summary_error is not None:
                    record = summary_error
                else:
                    if condition == "full_history":
                        context = payloads.full_history.payload_text
                        preparation = None
                    elif condition == "handoff_sieve":
                        context = payloads.handoff_sieve.payload_text
                        preparation = None
                    else:
                        if summary is None or summary_tokens is None:
                            raise RuntimeError("naive summary state is inconsistent")
                        context = summary
                        preparation = summary_result
                    record = await _receiver_record(
                        task=task,
                        condition=condition,
                        context_payload=context,
                        model=cleaned_model,
                        sdk_version=sdk_version,
                        preparation_result=preparation,
                        call_receiver=receiver_call,
                        classify_error=error_classifier,
                    )
                _write_line(stream, _record_payload(record))
                record_count += 1

        _write_line(
            stream,
            {
                "kind": "run_completed",
                "schema_version": "1",
                "run_id": run_id,
                "completed_at": _utcnow().isoformat(),
                "records_written": record_count,
            },
        )
    return record_count


def _preflight_openai() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise BatchConfigurationError("OPENAI_API_KEY is required for --run")
    try:
        openai_provider._load_sdk()
        return metadata.version("openai-agents")
    except openai_provider.ProviderDependencyError as exc:
        raise BatchConfigurationError(
            "OpenAI evaluation dependency is missing"
        ) from exc
    except metadata.PackageNotFoundError as exc:
        raise BatchConfigurationError(
            "openai-agents package metadata is unavailable"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="allow real provider calls")
    parser.add_argument("--model", help="exact OpenAI model id for both stages")
    parser.add_argument("--output", type=Path, help="new JSONL output path")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Without ``--run``, it never loads or calls a provider."""

    arguments = _parser().parse_args(argv)
    if not arguments.run:
        print(json.dumps({"status": "not_run"}, sort_keys=True))
        return 0
    if arguments.model is None or not arguments.model.strip():
        print("--run requires --model MODEL", file=sys.stderr)
        return 2
    if arguments.output is None:
        print("--run requires --output FILE", file=sys.stderr)
        return 2
    if arguments.output.exists():
        print("output file already exists", file=sys.stderr)
        return 2

    try:
        sdk_version = _preflight_openai()
        asyncio.run(
            run_batch(
                model=arguments.model,
                output=arguments.output,
                sdk_version=sdk_version,
                manifest=arguments.manifest,
            )
        )
    except (BatchConfigurationError, BatchFatalProviderError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
