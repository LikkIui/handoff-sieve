from __future__ import annotations

import json
from collections import Counter

import pytest

from evals.takeover import run_runnable_openai
from evals.takeover.runnable.taskpack import (
    TASKPACK,
    TaskPackSpec,
    build_takeover_task,
)

EXPECTED_REVIEW_BLOCKERS = {
    "rr02_falsy_config_review": ("FALSY_OVERRIDE",),
    "rr03_retry_after_review": (),
    "rr04_csv_splitter_review": (
        "CSV_QUOTED_FIELD",
        "CSV_MULTILINE_RECORD",
    ),
    "rr05_package_data_review": (),
    "rr06_checkpoint_review": (),
}


def _runner_spec(task: TaskPackSpec) -> run_runnable_openai.RunnableSpec:
    return run_runnable_openai._SPECS[task.task_id]


def test_runnable_catalog_has_twenty_tasks_with_planned_route_balance() -> None:
    counts = Counter(
        spec.taskpack_spec.route
        if spec.taskpack_spec is not None
        else {
            "rc01_composite_cursor": "researcher_to_coder",
            "pe01_streaming_csv": "planner_to_executor",
            "rr01_cursor_review": "researcher_to_reviewer",
        }[task_id]
        for task_id, spec in run_runnable_openai._SPECS.items()
    )

    assert len(run_runnable_openai._SPECS) == 20
    assert counts == {
        "researcher_to_coder": 7,
        "planner_to_executor": 7,
        "researcher_to_reviewer": 6,
    }


@pytest.mark.parametrize(
    "task",
    [task for task in TASKPACK.values() if task.kind == "source"],
    ids=lambda task: task.task_id,
)
def test_each_source_task_reference_passes_hidden_acceptance(
    task: TaskPackSpec,
) -> None:
    sources = {
        file.path: file.reference_source
        for file in task.files
        if file.reference_source is not None
    }
    assert set(sources) == {file.path for file in task.files}

    result = run_runnable_openai.run_taskpack_acceptance(
        _runner_spec(task),
        sources,
        timeout=30,
    )

    assert result.error is None
    assert result.overall is True
    assert tuple(check["id"] for check in result.checks) == task.check_ids
    assert all(check["passed"] for check in result.checks)


@pytest.mark.parametrize(
    "task_id,blockers",
    EXPECTED_REVIEW_BLOCKERS.items(),
)
def test_each_review_oracle_is_behavior_derived_and_satisfiable(
    task_id: str,
    blockers: tuple[str, ...],
) -> None:
    task = TASKPACK[task_id]
    review = run_runnable_openai.ReviewSubmission(
        candidate_id=task.candidate_id or "",
        verdict="request_changes" if blockers else "approve",
        blocking_issue_ids=blockers,
    )

    result = run_runnable_openai.run_taskpack_acceptance(
        _runner_spec(task),
        review,
        timeout=30,
    )

    assert result.error is None
    assert result.overall is True
    assert result.derived_blocking_issue_ids == blockers
    assert all(check["passed"] for check in result.checks)


@pytest.mark.parametrize("task", TASKPACK.values(), ids=lambda task: task.task_id)
def test_expanded_task_builds_receiver_view_without_hidden_oracle(
    task: TaskPackSpec,
) -> None:
    schema_task = build_takeover_task(task)
    runner_spec = _runner_spec(task)
    sources = run_runnable_openai._read_starter_sources(runner_spec)
    receiver_task = run_runnable_openai._build_runnable_task_view(
        runner_spec,
        schema_task,
        sources,
    )
    prefix = run_runnable_openai.receiver_task_prefix(receiver_task)

    assert schema_task.id == task.task_id
    assert set(sources) == {file.path for file in task.files}
    assert "success_validator" not in prefix
    assert all(file.path in prefix for file in task.files)


def test_taskpack_source_parser_maps_strict_fields_to_paths() -> None:
    task = TASKPACK["pe04_package_template"]
    spec = _runner_spec(task)
    raw = json.dumps({file.output_field: file.reference_source for file in task.files})

    parsed = run_runnable_openai.parse_taskpack_sources(spec, raw)

    assert parsed == {file.path: file.reference_source for file in task.files}
    with pytest.raises(run_runnable_openai.CandidateOutputError):
        run_runnable_openai.parse_taskpack_sources(spec, raw[:-1] + ',"extra":1}')
