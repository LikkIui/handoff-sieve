"""Run one three-condition runnable pilot after an explicit CLI opt-in.

RC-01 and PE-01 return complete source files; RR-01 returns a strict review.
Each condition uses the same public starter and task prefix, then host-side
acceptance runs in a separate, time-bounded process. Process isolation contains
interpreter state and crashes; it is not a security sandbox.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, TextIO

from pydantic import ValidationError

from evals.takeover import openai_provider
from evals.takeover.openai_provider import OpenAIProviderResult, ProviderErrorInfo
from evals.takeover.payloads import (
    ConditionName,
    build_payloads,
    receiver_task_prefix,
)
from evals.takeover.runnable.pe01_streaming_csv.acceptance import (
    CHECK_IDS as PE01_CHECK_IDS,
)
from evals.takeover.runnable.rc01_composite_cursor.acceptance import (
    CHECK_IDS as RC01_CHECK_IDS,
)
from evals.takeover.runnable.rr01_cursor_review.acceptance import (
    CHECK_IDS as RR01_CHECK_IDS,
)
from evals.takeover.runnable.rr01_cursor_review.acceptance import ReviewSubmission
from evals.takeover.runnable.taskpack import (
    TASKPACK,
    TaskPackSpec,
    build_takeover_task,
)
from evals.takeover.schema import ReceiverOutputContract, TakeoverTask
from handoff_sieve import ApproxTokenCounter

RUNNABLE_ROOT = Path(__file__).with_name("runnable") / "rc01_composite_cursor"
DEFAULT_TASK = Path(__file__).with_name("tasks") / "rc01_composite_cursor.json"
STARTER = RUNNABLE_ROOT / "starter"
ACCEPTANCE_CLI = RUNNABLE_ROOT / "acceptance.py"
CHECK_IDS = RC01_CHECK_IDS

PE01_ROOT = Path(__file__).with_name("runnable") / "pe01_streaming_csv"
RR01_ROOT = Path(__file__).with_name("runnable") / "rr01_cursor_review"
TASKS_ROOT = Path(__file__).with_name("tasks")

MAX_CANDIDATE_SOURCE_BYTES = 65_536
MAX_RAW_OUTPUT_BYTES = 131_072
MAX_MULTI_FILE_RAW_OUTPUT_BYTES = 262_144
DEFAULT_ACCEPTANCE_TIMEOUT = 10.0
DEFAULT_MODEL_TIMEOUT = 180.0
DEFAULT_CASE_TIMEOUT = 190.0

_PROVIDER = "openai"
_RECEIVER_MAX_OUTPUT_TOKENS = 8_192
_CONDITIONS: tuple[ConditionName, ...] = (
    "full_history",
    "naive_summary",
    "handoff_sieve",
)
_FATAL_ERROR_CATEGORIES = frozenset(
    {"dependency_missing", "usage_missing", "protocol_error"}
)
_FATAL_HTTP_STATUS_CODES = frozenset({400, 401, 403, 404, 422})
_CREDENTIAL_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
    }
)

ProviderCall = Callable[..., Awaitable[OpenAIProviderResult]]
ErrorClassifier = Callable[[BaseException], ProviderErrorInfo]
RunnableTaskId = str


@dataclass(frozen=True)
class RunnableSpec:
    """The small task-specific boundary around the shared three-condition run."""

    task_id: RunnableTaskId
    task_path: Path | None
    root: Path | None
    starter: Path | None
    acceptance_cli: Path
    check_ids: tuple[str, ...]
    kind: Literal[
        "single_source",
        "multi_source",
        "review",
        "taskpack_source",
        "taskpack_review",
    ]
    taskpack_spec: TaskPackSpec | None = None


_SPECS: dict[str, RunnableSpec] = {
    "rc01_composite_cursor": RunnableSpec(
        task_id="rc01_composite_cursor",
        task_path=DEFAULT_TASK,
        root=RUNNABLE_ROOT,
        starter=STARTER,
        acceptance_cli=ACCEPTANCE_CLI,
        check_ids=RC01_CHECK_IDS,
        kind="single_source",
    ),
    "pe01_streaming_csv": RunnableSpec(
        task_id="pe01_streaming_csv",
        task_path=TASKS_ROOT / "pe01_streaming_csv.json",
        root=PE01_ROOT,
        starter=PE01_ROOT / "starter",
        acceptance_cli=PE01_ROOT / "acceptance.py",
        check_ids=PE01_CHECK_IDS,
        kind="multi_source",
    ),
    "rr01_cursor_review": RunnableSpec(
        task_id="rr01_cursor_review",
        task_path=TASKS_ROOT / "rr01_cursor_review.json",
        root=RR01_ROOT,
        starter=RR01_ROOT / "starter",
        acceptance_cli=RR01_ROOT / "acceptance.py",
        check_ids=RR01_CHECK_IDS,
        kind="review",
    ),
}

_TASKPACK_ACCEPTANCE = Path(__file__).with_name("runnable") / "expanded_acceptance.py"
for _taskpack_id, _taskpack_spec in TASKPACK.items():
    _SPECS[_taskpack_id] = RunnableSpec(
        task_id=_taskpack_id,
        task_path=None,
        root=None,
        starter=None,
        acceptance_cli=_TASKPACK_ACCEPTANCE,
        check_ids=_taskpack_spec.check_ids,
        kind=(
            "taskpack_review" if _taskpack_spec.kind == "review" else "taskpack_source"
        ),
        taskpack_spec=_taskpack_spec,
    )


class RunnableConfigurationError(RuntimeError):
    """Raised before a valid provider-backed runnable batch can start."""


class RunnableFatalProviderError(RuntimeError):
    """Raised for an authentication, access, or adapter configuration error."""

    def __init__(self, info: ProviderErrorInfo) -> None:
        self.info = info
        super().__init__("fatal provider configuration error: " + _error_code(info))


class CandidateOutputError(ValueError):
    """Raised when receiver output is not the strict runnable response shape."""


# Keep the provider-runner error names consistent with ``run_openai`` for
# callers that treat the two explicit-run CLIs uniformly.
BatchConfigurationError = RunnableConfigurationError
BatchFatalProviderError = RunnableFatalProviderError


@dataclass(frozen=True)
class RunnableReceiverInput:
    """The exact shared task prefix plus one condition's context."""

    condition: ConditionName
    task_prefix: str
    context_payload: str
    input_text: str
    local_handoff_token_estimate: int
    local_input_token_estimate: int
    token_counter: str


@dataclass(frozen=True)
class AcceptanceExecution:
    """Normalized host-side subprocess result."""

    checks: tuple[dict[str, object], ...]
    overall: bool
    error: str | None = None
    derived_blocking_issue_ids: tuple[str, ...] | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _load_task(path: Path, expected_id: str) -> TakeoverTask:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnableConfigurationError(f"missing runnable task: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RunnableConfigurationError(f"invalid runnable task JSON: {path}") from exc
    try:
        task = TakeoverTask.model_validate(payload)
    except ValidationError as exc:
        raise RunnableConfigurationError("invalid runnable task") from exc
    if task.id != expected_id:
        raise RunnableConfigurationError(f"runnable runner requires {expected_id}")
    return task


def _load_rc01_task(path: Path = DEFAULT_TASK) -> TakeoverTask:
    return _load_task(path, "rc01_composite_cursor")


def _read_starter_sources(spec: RunnableSpec) -> dict[str, str]:
    if spec.taskpack_spec is not None:
        return {file.path: file.public_source for file in spec.taskpack_spec.files}
    if spec.starter is None:
        raise RunnableConfigurationError(f"{spec.task_id} has no public starter")
    paths: tuple[str, ...]
    if spec.kind == "single_source" or spec.kind == "review":
        paths = ("task_app/pagination.py",)
    else:
        paths = (
            "task_app/reports/api.py",
            "task_app/reports/csv_response.py",
        )
    sources: dict[str, str] = {}
    try:
        for relative in paths:
            sources[relative] = (spec.starter / relative).read_text(encoding="utf-8")
    except OSError as exc:
        raise RunnableConfigurationError(
            f"{spec.task_id} starter files are unavailable"
        ) from exc
    return sources


def _public_starter_text(sources: dict[str, str]) -> str:
    return "\n\n".join(
        f'<public_starter path="{path}">\n{source}</public_starter>'
        for path, source in sources.items()
    )


def _build_runnable_task_view(
    spec: RunnableSpec,
    task: TakeoverTask,
    sources: dict[str, str],
) -> TakeoverTask:
    """Replace comprehension output with the selected executable boundary."""

    public_starter = _public_starter_text(sources)
    required_fields: tuple[str, ...]
    if spec.kind == "taskpack_source":
        taskpack = spec.taskpack_spec
        if taskpack is None:
            raise RunnableConfigurationError("task-pack source metadata is missing")
        fields = tuple(file.output_field for file in taskpack.files)
        mapping = ", ".join(
            f"{file.output_field} for {file.path}" for file in taskpack.files
        )
        instruction = (
            "Complete every public starter file shown below while preserving its "
            "declared API and the supplied handoff requirements. Return exactly one "
            f"JSON object with only these field mappings: {mapping}. Each value must "
            "be the complete UTF-8 file content, with no Markdown fence, patch, "
            "commentary, or extra field. Each file is limited to 65536 bytes.\n\n"
            f"{public_starter}"
        )
        required_fields = fields
    elif spec.kind == "taskpack_review":
        instruction = (
            "Review only the active public candidate files shown below against the "
            "supplied handoff requirements. Do not modify them. Return exactly one "
            "JSON object with only candidate_id, verdict, and blocking_issue_ids. "
            "verdict must be approve or request_changes; blocking_issue_ids must be "
            "a JSON array without duplicates. Include no Markdown or commentary.\n\n"
            f"{public_starter}"
        )
        required_fields = ("candidate_id", "verdict", "blocking_issue_ids")
    elif spec.kind == "single_source":
        instruction = (
            "Implement the complete public starter file shown below. Preserve its "
            "public API and satisfy the supplied handoff requirements. Return exactly "
            "one JSON object whose only field is pagination_py. Its value must be the "
            "complete Python source for task_app/pagination.py, with no Markdown "
            "fence, patch, commentary, or extra field. The UTF-8 source must be at "
            "most 65536 "
            f"bytes.\n\n{public_starter}"
        )
        required_fields = ("pagination_py",)
    elif spec.kind == "multi_source":
        instruction = (
            "Complete the two public starter files shown below. Preserve their public "
            "API, the existing JSON behavior, and satisfy the supplied handoff "
            "requirements. Return exactly one JSON object with only api_py and "
            "csv_response_py. Each value must be the complete Python source for its "
            "matching starter path, with no Markdown fence, patch, commentary, or "
            "extra field. Each UTF-8 source is limited to 65536 bytes.\n\n"
            f"{public_starter}"
        )
        required_fields = ("api_py", "csv_response_py")
    else:
        instruction = (
            "Review only the active public candidate shown below against the supplied "
            "handoff requirements. Do not modify it. Return exactly one JSON object "
            "with only candidate_id, verdict, and blocking_issue_ids. verdict must be "
            "approve or request_changes; blocking_issue_ids must be a JSON array with "
            "no duplicates. Include no Markdown or commentary.\n\n"
            f"{public_starter}"
        )
        required_fields = (
            "candidate_id",
            "verdict",
            "blocking_issue_ids",
        )
    return task.model_copy(
        update={
            "receiver_instruction": instruction,
            "receiver_output_contract": ReceiverOutputContract(
                required_fields=required_fields
            ),
        }
    )


def _runnable_task_view(task: TakeoverTask, starter_source: str) -> TakeoverTask:
    """Compatibility wrapper for the original RC-01 runnable boundary."""

    return _build_runnable_task_view(
        _SPECS["rc01_composite_cursor"],
        task,
        {"task_app/pagination.py": starter_source},
    )


def build_runnable_receiver_input(
    task: TakeoverTask,
    *,
    condition: ConditionName,
    context_payload: str,
) -> RunnableReceiverInput:
    """Build a receiver input whose only condition-dependent text is context."""

    prefix = receiver_task_prefix(task)
    input_text = f"{prefix}\n\n<handoff_context>\n{context_payload}\n</handoff_context>"
    counter = ApproxTokenCounter()
    return RunnableReceiverInput(
        condition=condition,
        task_prefix=prefix,
        context_payload=context_payload,
        input_text=input_text,
        local_handoff_token_estimate=counter.count_text(context_payload),
        local_input_token_estimate=counter.count_text(input_text),
        token_counter=counter.name,
    )


def _strict_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateOutputError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_candidate_source(raw_output: str) -> str:
    """Parse exactly ``{"pagination_py": <complete source>}`` with size bounds."""

    if not isinstance(raw_output, str):
        raise CandidateOutputError("receiver output must be text")
    try:
        raw_size = len(raw_output.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CandidateOutputError("receiver output is not valid UTF-8 text") from exc
    if raw_size > MAX_RAW_OUTPUT_BYTES:
        raise CandidateOutputError("receiver output exceeds the byte limit")
    try:
        payload = json.loads(raw_output, object_pairs_hook=_strict_object)
    except CandidateOutputError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CandidateOutputError(
            "receiver output must be one valid JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise CandidateOutputError("receiver output must be a JSON object")
    if set(payload) != {"pagination_py"}:
        raise CandidateOutputError(
            "receiver output must contain only the pagination_py field"
        )
    source = payload["pagination_py"]
    if not isinstance(source, str) or not source.strip():
        raise CandidateOutputError("pagination_py must be a non-empty string")
    try:
        source_size = len(source.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CandidateOutputError("pagination_py is not valid UTF-8 text") from exc
    if source_size > MAX_CANDIDATE_SOURCE_BYTES:
        raise CandidateOutputError("pagination_py exceeds the source size in bytes")
    return source


def _parse_strict_payload(raw_output: str, *, max_bytes: int) -> dict[str, object]:
    if not isinstance(raw_output, str):
        raise CandidateOutputError("receiver output must be text")
    try:
        raw_size = len(raw_output.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CandidateOutputError("receiver output is not valid UTF-8 text") from exc
    if raw_size > max_bytes:
        raise CandidateOutputError("receiver output exceeds the byte limit")
    try:
        payload = json.loads(raw_output, object_pairs_hook=_strict_object)
    except CandidateOutputError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CandidateOutputError(
            "receiver output must be one valid JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise CandidateOutputError("receiver output must be a JSON object")
    return payload


def _source_field(payload: dict[str, object], field: str) -> str:
    source = payload[field]
    if not isinstance(source, str) or not source.strip():
        raise CandidateOutputError(f"{field} must be a non-empty string")
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CandidateOutputError(f"{field} is not valid UTF-8 text") from exc
    if size > MAX_CANDIDATE_SOURCE_BYTES:
        raise CandidateOutputError(f"{field} exceeds the source size in bytes")
    return source


def parse_pe01_sources(raw_output: str) -> tuple[str, str]:
    """Parse the two complete PE-01 source files."""

    payload = _parse_strict_payload(
        raw_output,
        max_bytes=MAX_MULTI_FILE_RAW_OUTPUT_BYTES,
    )
    if set(payload) != {"api_py", "csv_response_py"}:
        raise CandidateOutputError(
            "receiver output must contain only api_py and csv_response_py"
        )
    return (
        _source_field(payload, "api_py"),
        _source_field(payload, "csv_response_py"),
    )


def parse_taskpack_sources(
    spec: RunnableSpec,
    raw_output: str,
) -> dict[str, str]:
    """Parse complete file contents for one data-driven source task."""

    taskpack = spec.taskpack_spec
    if taskpack is None or taskpack.kind != "source":
        raise CandidateOutputError("source task metadata is missing")
    payload = _parse_strict_payload(
        raw_output,
        max_bytes=MAX_MULTI_FILE_RAW_OUTPUT_BYTES,
    )
    expected_fields = {file.output_field for file in taskpack.files}
    if set(payload) != expected_fields:
        raise CandidateOutputError(
            "receiver output fields do not match the selected task"
        )
    return {
        file.path: _source_field(payload, file.output_field) for file in taskpack.files
    }


def parse_review_submission(raw_output: str) -> ReviewSubmission:
    """Parse the strict RR-01 review without applying the hidden oracle."""

    payload = _parse_strict_payload(raw_output, max_bytes=65_536)
    if set(payload) != {"candidate_id", "verdict", "blocking_issue_ids"}:
        raise CandidateOutputError("receiver review has an invalid shape")
    candidate_id = payload["candidate_id"]
    verdict = payload["verdict"]
    blockers = payload["blocking_issue_ids"]
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise CandidateOutputError("candidate_id must be a non-empty string")
    if verdict == "approve":
        typed_verdict: Literal["approve", "request_changes"] = "approve"
    elif verdict == "request_changes":
        typed_verdict = "request_changes"
    else:
        raise CandidateOutputError("verdict is invalid")
    if (
        not isinstance(blockers, list)
        or len(blockers) > 4
        or not all(isinstance(issue, str) and issue for issue in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise CandidateOutputError("blocking_issue_ids is invalid")
    return ReviewSubmission(
        candidate_id=candidate_id,
        verdict=typed_verdict,
        blocking_issue_ids=tuple(blockers),
    )


ParsedSubmission = str | tuple[str, str] | dict[str, str] | ReviewSubmission


def _failed_checks(
    detail: str,
    check_ids: tuple[str, ...] = CHECK_IDS,
) -> tuple[dict[str, object], ...]:
    return tuple(
        {"id": check_id, "passed": False, "detail": detail} for check_id in check_ids
    )


def _acceptance_env() -> dict[str, str]:
    """Copy the environment while removing common provider credentials."""

    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _CREDENTIAL_ENV_NAMES
        and key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
    }


def _parse_acceptance_report(
    stdout: str,
    *,
    check_ids: tuple[str, ...] = CHECK_IDS,
    includes_derived_blockers: bool = False,
) -> AcceptanceExecution:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("acceptance process did not return valid JSON") from exc
    expected_fields = {"checks", "overall"}
    if includes_derived_blockers:
        expected_fields.add("derived_blocking_issue_ids")
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError("acceptance report has an invalid top-level shape")
    if type(payload["overall"]) is not bool or not isinstance(payload["checks"], list):
        raise ValueError("acceptance report has invalid field types")

    checks: list[dict[str, object]] = []
    for item in payload["checks"]:
        if not isinstance(item, dict) or set(item) != {"detail", "id", "passed"}:
            raise ValueError("acceptance report contains an invalid check")
        if not isinstance(item["id"], str) or type(item["passed"]) is not bool:
            raise ValueError("acceptance report contains invalid check field types")
        if item["detail"] is not None and not isinstance(item["detail"], str):
            raise ValueError("acceptance report contains an invalid check detail")
        checks.append(
            {
                "id": item["id"],
                "passed": item["passed"],
                "detail": item["detail"],
            }
        )
    if tuple(check["id"] for check in checks) != check_ids:
        raise ValueError("acceptance report did not contain the expected checks")
    computed_overall = all(bool(check["passed"]) for check in checks)
    if payload["overall"] != computed_overall:
        raise ValueError("acceptance report overall does not match its checks")
    derived: tuple[str, ...] | None = None
    if includes_derived_blockers:
        raw_derived = payload["derived_blocking_issue_ids"]
        if (
            not isinstance(raw_derived, list)
            or not all(isinstance(issue, str) for issue in raw_derived)
            or len(raw_derived) != len(set(raw_derived))
        ):
            raise ValueError("acceptance report has invalid derived blockers")
        derived = tuple(raw_derived)
    return AcceptanceExecution(
        checks=tuple(checks),
        overall=computed_overall,
        derived_blocking_issue_ids=derived,
    )


def _execute_acceptance(
    command: list[str],
    *,
    workspace: Path,
    check_ids: tuple[str, ...],
    timeout: float,
    includes_derived_blockers: bool = False,
) -> AcceptanceExecution:
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=_acceptance_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        detail = "acceptance_timeout"
        return AcceptanceExecution(
            _failed_checks(detail, check_ids),
            False,
            detail,
        )
    except OSError:
        detail = "acceptance_process_error"
        return AcceptanceExecution(
            _failed_checks(detail, check_ids),
            False,
            detail,
        )
    if completed.returncode != 0:
        detail = f"acceptance_process_exit:{completed.returncode}"
        return AcceptanceExecution(
            _failed_checks(detail, check_ids),
            False,
            detail,
        )
    try:
        return _parse_acceptance_report(
            completed.stdout,
            check_ids=check_ids,
            includes_derived_blockers=includes_derived_blockers,
        )
    except ValueError:
        detail = "acceptance_protocol_error"
        return AcceptanceExecution(
            _failed_checks(detail, check_ids),
            False,
            detail,
        )


def run_candidate_acceptance(
    source: str,
    *,
    timeout: float = DEFAULT_ACCEPTANCE_TIMEOUT,
) -> AcceptanceExecution:
    """Check one source file in a fresh starter copy and bounded subprocess."""

    if timeout <= 0:
        raise ValueError("acceptance timeout must be positive")
    if not STARTER.is_dir() or not ACCEPTANCE_CLI.is_file():
        raise RunnableConfigurationError("RC-01 runnable fixture is incomplete")

    with tempfile.TemporaryDirectory(prefix="handoff-sieve-rc01-") as temp:
        workspace = Path(temp) / "workspace"
        shutil.copytree(
            STARTER,
            workspace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        candidate = workspace / "task_app" / "pagination.py"
        candidate.write_text(source, encoding="utf-8", newline="\n")
        return _execute_acceptance(
            [
                sys.executable,
                "-I",
                str(ACCEPTANCE_CLI.resolve()),
                "--workspace",
                str(workspace.resolve()),
            ],
            workspace=workspace,
            check_ids=RC01_CHECK_IDS,
            timeout=timeout,
        )


def run_pe01_acceptance(
    sources: tuple[str, str],
    *,
    timeout: float = DEFAULT_ACCEPTANCE_TIMEOUT,
) -> AcceptanceExecution:
    """Check the two PE-01 sources in a fresh starter copy."""

    spec = _SPECS["pe01_streaming_csv"]
    if timeout <= 0:
        raise ValueError("acceptance timeout must be positive")
    if spec.starter is None:
        raise RunnableConfigurationError("PE-01 public starter is missing")
    with tempfile.TemporaryDirectory(prefix="handoff-sieve-pe01-") as temp:
        workspace = Path(temp) / "workspace"
        shutil.copytree(
            spec.starter,
            workspace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        api_source, csv_source = sources
        reports = workspace / "task_app" / "reports"
        (reports / "api.py").write_text(api_source, encoding="utf-8", newline="\n")
        (reports / "csv_response.py").write_text(
            csv_source,
            encoding="utf-8",
            newline="\n",
        )
        return _execute_acceptance(
            [
                sys.executable,
                "-I",
                str(spec.acceptance_cli.resolve()),
                "--workspace",
                str(workspace.resolve()),
            ],
            workspace=workspace,
            check_ids=spec.check_ids,
            timeout=timeout,
        )


def run_rr01_acceptance(
    review: ReviewSubmission,
    *,
    timeout: float = DEFAULT_ACCEPTANCE_TIMEOUT,
) -> AcceptanceExecution:
    """Probe the fixed RR-01 candidate and grade one structured review."""

    spec = _SPECS["rr01_cursor_review"]
    if timeout <= 0:
        raise ValueError("acceptance timeout must be positive")
    if spec.starter is None:
        raise RunnableConfigurationError("RR-01 public starter is missing")
    with tempfile.TemporaryDirectory(prefix="handoff-sieve-rr01-") as temp:
        temp_root = Path(temp)
        workspace = temp_root / "workspace"
        shutil.copytree(
            spec.starter,
            workspace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        review_path = temp_root / "review.json"
        review_path.write_text(
            json.dumps(
                {
                    "candidate_id": review.candidate_id,
                    "verdict": review.verdict,
                    "blocking_issue_ids": list(review.blocking_issue_ids),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )
        return _execute_acceptance(
            [
                sys.executable,
                "-I",
                str(spec.acceptance_cli.resolve()),
                "--workspace",
                str(workspace.resolve()),
                "--review",
                str(review_path.resolve()),
            ],
            workspace=workspace,
            check_ids=spec.check_ids,
            timeout=timeout,
            includes_derived_blockers=True,
        )


def run_taskpack_acceptance(
    spec: RunnableSpec,
    submission: dict[str, str] | ReviewSubmission,
    *,
    timeout: float = DEFAULT_ACCEPTANCE_TIMEOUT,
) -> AcceptanceExecution:
    """Run one expanded task in a fresh workspace and bounded subprocess."""

    taskpack = spec.taskpack_spec
    if taskpack is None:
        raise RunnableConfigurationError("task-pack metadata is missing")
    if timeout <= 0:
        raise ValueError("acceptance timeout must be positive")
    if not spec.acceptance_cli.is_file():
        raise RunnableConfigurationError("task-pack acceptance CLI is missing")

    with tempfile.TemporaryDirectory(prefix=f"handoff-sieve-{spec.task_id}-") as temp:
        temp_root = Path(temp)
        workspace = temp_root / "workspace"
        workspace.mkdir()
        for file in taskpack.files:
            target = workspace / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file.public_source, encoding="utf-8", newline="\n")

        command = [
            sys.executable,
            "-I",
            str(spec.acceptance_cli.resolve()),
            "--task-id",
            spec.task_id,
            "--workspace",
            str(workspace.resolve()),
        ]
        if isinstance(submission, ReviewSubmission):
            review_path = temp_root / "review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "candidate_id": submission.candidate_id,
                        "verdict": submission.verdict,
                        "blocking_issue_ids": list(submission.blocking_issue_ids),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
                newline="\n",
            )
            command.extend(("--review", str(review_path.resolve())))
            includes_derived = True
        else:
            for relative, source in submission.items():
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8", newline="\n")
            includes_derived = False

        return _execute_acceptance(
            command,
            workspace=workspace,
            check_ids=spec.check_ids,
            timeout=timeout,
            includes_derived_blockers=includes_derived,
        )


def _usage(result: OpenAIProviderResult) -> dict[str, int]:
    return {
        "input_tokens": result.provider_input_tokens,
        "output_tokens": result.provider_output_tokens,
        "total_tokens": result.provider_total_tokens,
    }


def _error_code(info: ProviderErrorInfo) -> str:
    parts: list[str] = [info.category]
    if info.status_code is not None:
        parts.append(str(info.status_code))
    return ":".join(parts)


def _classify_or_raise(
    error: BaseException,
    classify_error: ErrorClassifier,
) -> ProviderErrorInfo:
    info = classify_error(error)
    fatal = (
        isinstance(error, (TypeError, ValueError))
        or info.category in _FATAL_ERROR_CATEGORIES
        or (
            info.category == "provider_http"
            and info.status_code in _FATAL_HTTP_STATUS_CODES
        )
    )
    if fatal:
        raise RunnableFatalProviderError(info) from error
    return info


def _record_base(
    *,
    task: TakeoverTask,
    condition: ConditionName,
    model: str,
    sdk_version: str,
    provider_label: str = _PROVIDER,
) -> dict[str, Any]:
    return {
        "kind": "observation",
        "schema_version": "1",
        "task_id": task.id,
        "condition": condition,
        "recorded_at": _utcnow().isoformat(),
        "provider": provider_label,
        "requested_model": model,
        "sdk_version": sdk_version,
        "retry_count": 0,
    }


def _unrun_record(
    *,
    task: TakeoverTask,
    condition: ConditionName,
    model: str,
    sdk_version: str,
    status: str,
    error: str,
    receiver: RunnableReceiverInput | None,
    result: OpenAIProviderResult | None = None,
    preparation_result: OpenAIProviderResult | None = None,
    preparation_request_id: str | None = None,
    unreported_event_count: int = 0,
    check_ids: tuple[str, ...] = CHECK_IDS,
    provider_label: str = _PROVIDER,
) -> dict[str, Any]:
    record = _record_base(
        task=task,
        condition=condition,
        model=model,
        sdk_version=sdk_version,
        provider_label=provider_label,
    )
    record.update(
        {
            "status": status,
            "downstream_success": False,
            "response_id": result.response_id if result is not None else None,
            "request_id": result.request_id if result is not None else None,
            "receiver_input": receiver.input_text if receiver is not None else None,
            "task_prefix": receiver.task_prefix if receiver is not None else None,
            "local_handoff_token_estimate": (
                receiver.local_handoff_token_estimate if receiver is not None else None
            ),
            "local_input_token_estimate": (
                receiver.local_input_token_estimate if receiver is not None else None
            ),
            "token_counter": receiver.token_counter if receiver is not None else None,
            "provider_usage": _usage(result) if result is not None else None,
            "naive_summary_preparation_usage": (
                _usage(preparation_result) if preparation_result is not None else None
            ),
            "naive_summary_preparation_response_id": (
                preparation_result.response_id
                if preparation_result is not None
                else None
            ),
            "naive_summary_preparation_request_id": (
                preparation_result.request_id
                if preparation_result is not None
                else preparation_request_id
            ),
            "naive_summary_raw_output": (
                preparation_result.raw_output
                if preparation_result is not None
                else None
            ),
            "raw_output": result.raw_output if result is not None else None,
            "checks": list(_failed_checks("not_run:" + status, check_ids)),
            "error": error,
            "event_count": (
                (result.event_count if result is not None else 0)
                + (
                    preparation_result.event_count
                    if preparation_result is not None
                    else 0
                )
                + unreported_event_count
            ),
        }
    )
    return record


async def _receiver_record(
    *,
    spec: RunnableSpec,
    task: TakeoverTask,
    receiver: RunnableReceiverInput,
    model: str,
    sdk_version: str,
    preparation_result: OpenAIProviderResult | None,
    call_receiver: ProviderCall,
    classify_error: ErrorClassifier,
    acceptance_timeout: float,
    provider_label: str = _PROVIDER,
) -> dict[str, Any]:
    try:
        result = await call_receiver(
            model,
            receiver.input_text,
            max_output_tokens=_RECEIVER_MAX_OUTPUT_TOKENS,
        )
    except Exception as error:
        info = _classify_or_raise(error, classify_error)
        record = _unrun_record(
            task=task,
            condition=receiver.condition,
            model=model,
            sdk_version=sdk_version,
            status="provider_error",
            error="provider_error:" + _error_code(info),
            receiver=receiver,
            preparation_result=preparation_result,
            unreported_event_count=1,
            check_ids=spec.check_ids,
            provider_label=provider_label,
        )
        record["request_id"] = info.request_id
        return record

    try:
        if spec.kind == "single_source":
            submission: ParsedSubmission = parse_candidate_source(result.raw_output)
        elif spec.kind == "multi_source":
            submission = parse_pe01_sources(result.raw_output)
        elif spec.kind == "taskpack_source":
            submission = parse_taskpack_sources(spec, result.raw_output)
        else:
            submission = parse_review_submission(result.raw_output)
    except CandidateOutputError:
        return _unrun_record(
            task=task,
            condition=receiver.condition,
            model=model,
            sdk_version=sdk_version,
            status="invalid_output",
            error="invalid_candidate_output",
            receiver=receiver,
            result=result,
            preparation_result=preparation_result,
            check_ids=spec.check_ids,
            provider_label=provider_label,
        )

    if spec.kind == "taskpack_source" or spec.kind == "taskpack_review":
        if not isinstance(submission, (dict, ReviewSubmission)):
            raise RuntimeError("task-pack submission type is inconsistent")
        acceptance = run_taskpack_acceptance(
            spec,
            submission,
            timeout=acceptance_timeout,
        )
        if isinstance(submission, dict):
            submission_bytes = sum(
                len(source.encode("utf-8")) for source in submission.values()
            )
            candidate_source_bytes = submission_bytes
        else:
            submission_bytes = len(result.raw_output.encode("utf-8"))
            candidate_source_bytes = None
    elif isinstance(submission, str):
        acceptance = run_candidate_acceptance(
            submission,
            timeout=acceptance_timeout,
        )
        submission_bytes = len(submission.encode("utf-8"))
        candidate_source_bytes = submission_bytes
    elif isinstance(submission, ReviewSubmission):
        acceptance = run_rr01_acceptance(
            submission,
            timeout=acceptance_timeout,
        )
        submission_bytes = len(result.raw_output.encode("utf-8"))
        candidate_source_bytes = None
    else:
        if not isinstance(submission, tuple):
            raise RuntimeError("PE-01 submission type is inconsistent")
        acceptance = run_pe01_acceptance(
            submission,
            timeout=acceptance_timeout,
        )
        submission_bytes = sum(len(source.encode("utf-8")) for source in submission)
        candidate_source_bytes = submission_bytes
    record = _record_base(
        task=task,
        condition=receiver.condition,
        model=model,
        sdk_version=sdk_version,
        provider_label=provider_label,
    )
    record.update(
        {
            "status": "completed" if acceptance.error is None else "acceptance_error",
            "downstream_success": acceptance.overall,
            "response_id": result.response_id,
            "request_id": result.request_id,
            "receiver_input": receiver.input_text,
            "task_prefix": receiver.task_prefix,
            "local_handoff_token_estimate": (receiver.local_handoff_token_estimate),
            "local_input_token_estimate": receiver.local_input_token_estimate,
            "token_counter": receiver.token_counter,
            "provider_usage": _usage(result),
            "naive_summary_preparation_usage": (
                _usage(preparation_result) if preparation_result is not None else None
            ),
            "naive_summary_preparation_response_id": (
                preparation_result.response_id
                if preparation_result is not None
                else None
            ),
            "naive_summary_preparation_request_id": (
                preparation_result.request_id
                if preparation_result is not None
                else None
            ),
            "naive_summary_raw_output": (
                preparation_result.raw_output
                if preparation_result is not None
                else None
            ),
            "raw_output": result.raw_output,
            "submission_bytes": submission_bytes,
            "candidate_source_bytes": candidate_source_bytes,
            "derived_blocking_issue_ids": (
                list(acceptance.derived_blocking_issue_ids)
                if acceptance.derived_blocking_issue_ids is not None
                else None
            ),
            "checks": list(acceptance.checks),
            "error": acceptance.error,
            "event_count": result.event_count
            + (preparation_result.event_count if preparation_result is not None else 0),
        }
    )
    return record


async def run_batch(
    *,
    model: str,
    output: Path,
    sdk_version: str,
    task_id: str = "rc01_composite_cursor",
    task_path: Path | None = None,
    call_receiver: ProviderCall | None = None,
    call_summary: ProviderCall | None = None,
    classify_error: ErrorClassifier | None = None,
    acceptance_timeout: float = DEFAULT_ACCEPTANCE_TIMEOUT,
    model_timeout: float = DEFAULT_MODEL_TIMEOUT,
    case_timeout: float = DEFAULT_CASE_TIMEOUT,
    provider_label: str = _PROVIDER,
) -> int:
    """Run all three conditions for one pilot and write auditable JSONL."""

    cleaned_model = model.strip()
    if not cleaned_model:
        raise RunnableConfigurationError("model cannot be blank")
    cleaned_provider = provider_label.strip()
    if not cleaned_provider:
        raise RunnableConfigurationError("provider_label cannot be blank")
    if not sdk_version.strip():
        raise RunnableConfigurationError("sdk_version cannot be blank")
    if acceptance_timeout <= 0:
        raise RunnableConfigurationError("acceptance_timeout must be positive")
    if model_timeout <= 0:
        raise RunnableConfigurationError("model_timeout must be positive")
    if case_timeout <= model_timeout:
        raise RunnableConfigurationError(
            "case_timeout must be greater than model_timeout"
        )
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    try:
        spec = _SPECS[task_id]
    except KeyError as exc:
        raise RunnableConfigurationError(f"unknown runnable task: {task_id}") from exc
    if not spec.acceptance_cli.is_file() or (
        spec.taskpack_spec is None
        and (spec.starter is None or not spec.starter.is_dir())
    ):
        raise RunnableConfigurationError(
            f"{spec.task_id} runnable fixture is incomplete"
        )

    if task_path is not None:
        task = _load_task(task_path, spec.task_id)
    elif spec.taskpack_spec is not None:
        task = build_takeover_task(spec.taskpack_spec)
    elif spec.task_path is not None:
        task = _load_task(spec.task_path, spec.task_id)
    else:
        raise RunnableConfigurationError(f"{spec.task_id} task definition is missing")
    starter_sources = _read_starter_sources(spec)
    runnable_task = _build_runnable_task_view(spec, task, starter_sources)
    payloads = build_payloads(runnable_task)
    prefix = receiver_task_prefix(runnable_task)

    receiver_call = call_receiver or partial(
        openai_provider.call_receiver,
        model_timeout=model_timeout,
        case_timeout=case_timeout,
    )
    summary_call = call_summary or partial(
        openai_provider.call_summary,
        model_timeout=model_timeout,
        case_timeout=case_timeout,
    )
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
                "provider": cleaned_provider,
                "requested_model": cleaned_model,
                "sdk_version": sdk_version,
                "task_id": task.id,
                "model_timeout_seconds": model_timeout,
                "case_timeout_seconds": case_timeout,
                "conditions": list(_CONDITIONS),
                "task_prefix": prefix,
                "acceptance_check_ids": list(spec.check_ids),
            },
        )

        summary_result: OpenAIProviderResult | None = None
        summary_text: str | None = None
        summary_error: tuple[str, OpenAIProviderResult | None, str | None] | None = None
        try:
            summary_result = await summary_call(
                cleaned_model,
                payloads.naive_summary.prompt_text,
                max_output_tokens=payloads.naive_summary.max_output_tokens,
            )
            if (
                ApproxTokenCounter().count_text(summary_result.raw_output)
                > task.contract.max_tokens
            ):
                summary_error = ("summary_over_budget", summary_result, None)
            else:
                summary_text = summary_result.raw_output
        except Exception as error:
            info = _classify_or_raise(error, error_classifier)
            summary_error = (
                "summary_error:" + _error_code(info),
                None,
                info.request_id,
            )

        contexts = {
            "full_history": payloads.full_history.payload_text,
            "naive_summary": summary_text,
            "handoff_sieve": payloads.handoff_sieve.payload_text,
        }
        for condition in _CONDITIONS:
            context = contexts[condition]
            if condition == "naive_summary" and summary_error is not None:
                error_code, failed_summary, summary_request_id = summary_error
                record = _unrun_record(
                    task=task,
                    condition=condition,
                    model=cleaned_model,
                    sdk_version=sdk_version,
                    status="summary_error",
                    error=error_code,
                    receiver=None,
                    preparation_result=failed_summary,
                    preparation_request_id=summary_request_id,
                    unreported_event_count=(1 if failed_summary is None else 0),
                    check_ids=spec.check_ids,
                    provider_label=cleaned_provider,
                )
            else:
                if not isinstance(context, str):
                    raise RuntimeError("naive summary state is inconsistent")
                receiver = build_runnable_receiver_input(
                    runnable_task,
                    condition=condition,
                    context_payload=context,
                )
                if receiver.task_prefix != prefix:
                    raise RuntimeError(
                        "runnable task prefix changed between conditions"
                    )
                record = await _receiver_record(
                    spec=spec,
                    task=task,
                    receiver=receiver,
                    model=cleaned_model,
                    sdk_version=sdk_version,
                    preparation_result=(
                        summary_result if condition == "naive_summary" else None
                    ),
                    call_receiver=receiver_call,
                    classify_error=error_classifier,
                    acceptance_timeout=acceptance_timeout,
                    provider_label=cleaned_provider,
                )
            _write_line(stream, record)
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


def has_completed_footer(path: Path) -> bool:
    """Return true only when the final JSONL row is a matching completion footer."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) != 5:
            return False
        first = json.loads(lines[0])
        observations = [json.loads(line) for line in lines[1:-1]]
        last = json.loads(lines[-1])
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(first, dict)
        and isinstance(last, dict)
        and first.get("kind") == "run_started"
        and last.get("kind") == "run_completed"
        and all(
            isinstance(observation, dict) and observation.get("kind") == "observation"
            for observation in observations
        )
        and isinstance(first.get("run_id"), str)
        and last.get("run_id") == first.get("run_id")
        and last.get("records_written") == 3
    )


def _preflight_openai() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RunnableConfigurationError("OPENAI_API_KEY is required for --run")
    try:
        openai_provider._load_sdk()
        return metadata.version("openai-agents")
    except openai_provider.ProviderDependencyError as exc:
        raise RunnableConfigurationError(
            "OpenAI evaluation dependency is missing"
        ) from exc
    except metadata.PackageNotFoundError as exc:
        raise RunnableConfigurationError(
            "openai-agents package metadata is unavailable"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="allow real provider calls")
    parser.add_argument("--model", help="exact OpenAI model id for both stages")
    parser.add_argument("--output", type=Path, help="new JSONL output path")
    parser.add_argument(
        "--provider-label",
        default=_PROVIDER,
        help="provider or gateway label written to every result record",
    )
    parser.add_argument(
        "--model-timeout",
        type=float,
        default=DEFAULT_MODEL_TIMEOUT,
        help="per-provider-call timeout in seconds",
    )
    parser.add_argument(
        "--case-timeout",
        type=float,
        default=DEFAULT_CASE_TIMEOUT,
        help="outer timeout in seconds; must exceed --model-timeout",
    )
    parser.add_argument(
        "--task-id",
        choices=tuple(_SPECS),
        default="rc01_composite_cursor",
    )
    parser.add_argument(
        "--task",
        type=Path,
        help="optional task JSON override matching --task-id",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; without ``--run`` it never loads a provider."""

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
                task_id=arguments.task_id,
                task_path=arguments.task,
                model_timeout=arguments.model_timeout,
                case_timeout=arguments.case_timeout,
                provider_label=arguments.provider_label,
            )
        )
    except (
        FileExistsError,
        OSError,
        RunnableConfigurationError,
        RunnableFatalProviderError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
