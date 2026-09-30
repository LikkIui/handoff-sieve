"""Deterministically grade one receiver JSON response."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from evals.takeover.schema import SuccessCheck, TakeoverTask

FailureReason = Literal[
    "passed",
    "malformed_json",
    "response_not_object",
    "missing_field",
    "type_mismatch",
    "value_mismatch",
]


class CheckGrade(BaseModel):
    """Outcome of one declared deterministic success check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    path: str
    operator: Literal["equals", "contains_all"]
    passed: bool
    reason: FailureReason
    expected: Any
    actual: Any = None


class GradeResult(BaseModel):
    """Per-check outcomes and their conjunction for one response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    overall: bool
    checks: tuple[CheckGrade, ...]


class _InvalidJSON(ValueError):
    """Raised for JSON constructs that would make grading ambiguous."""


def _reject_nonstandard_constant(value: str) -> None:
    raise _InvalidJSON(f"non-standard JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJSON(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality shortcut."""

    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _json_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(
            _json_equal(actual[key], expected[key]) for key in actual
        )
    return actual == expected


def _failed_checks(
    task: TakeoverTask,
    reason: Literal["malformed_json", "response_not_object"],
) -> GradeResult:
    return GradeResult(
        overall=False,
        checks=tuple(
            CheckGrade(
                id=check.id,
                path=check.path,
                operator=check.operator,
                passed=False,
                reason=reason,
                expected=check.expected,
            )
            for check in task.success_validator.checks
        ),
    )


def _grade_check(check: SuccessCheck, response: dict[str, Any]) -> CheckGrade:
    if check.path not in response:
        return CheckGrade(
            id=check.id,
            path=check.path,
            operator=check.operator,
            passed=False,
            reason="missing_field",
            expected=check.expected,
        )

    actual = response[check.path]
    if check.operator == "equals":
        passed = _json_equal(actual, check.expected)
        reason: FailureReason = "passed" if passed else "value_mismatch"
    else:
        if not isinstance(actual, list):
            return CheckGrade(
                id=check.id,
                path=check.path,
                operator=check.operator,
                passed=False,
                reason="type_mismatch",
                expected=check.expected,
                actual=actual,
            )
        passed = all(
            any(_json_equal(item, expected) for item in actual)
            for expected in check.expected
        )
        reason = "passed" if passed else "value_mismatch"

    return CheckGrade(
        id=check.id,
        path=check.path,
        operator=check.operator,
        passed=passed,
        reason=reason,
        expected=check.expected,
        actual=actual,
    )


def grade_response(task: TakeoverTask, receiver_json: str) -> GradeResult:
    """Grade one strict JSON object against a task's declared checks.

    The function never repairs the response or exposes grader feedback to a
    receiver. Invalid JSON and non-object JSON fail every declared check.
    """

    try:
        response = json.loads(
            receiver_json,
            parse_constant=_reject_nonstandard_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, _InvalidJSON, TypeError):
        return _failed_checks(task, "malformed_json")

    if not isinstance(response, dict):
        return _failed_checks(task, "response_not_object")

    checks = tuple(
        _grade_check(check, response) for check in task.success_validator.checks
    )
    return GradeResult(overall=all(check.passed for check in checks), checks=checks)
