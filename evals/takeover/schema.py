"""Schemas for the deliberately small takeover evaluation.

This module validates evaluation inputs only. It does not call a provider,
grade model output, or calculate success rates.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from handoff_sieve import HandoffEnvelope, ReceiverContract

Route = Literal[
    "researcher_to_coder",
    "planner_to_executor",
    "researcher_to_reviewer",
]

ROUTES: tuple[Route, ...] = (
    "researcher_to_coder",
    "planner_to_executor",
    "researcher_to_reviewer",
)

_ROUTE_PARTIES: dict[Route, tuple[str, str]] = {
    "researcher_to_coder": ("researcher", "coder"),
    "planner_to_executor": ("planner", "executor"),
    "researcher_to_reviewer": ("researcher", "reviewer"),
}


class ManifestSlot(BaseModel):
    """One planned or ready task fixture in the pilot manifest."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    route: Route
    task_file: str
    fixture_status: Literal["planned", "ready"] = "planned"

    @field_validator("task_file")
    @classmethod
    def _task_file_must_be_local_json(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "tasks"
            or path.suffix != ".json"
        ):
            raise ValueError("task_file must be a relative tasks/*.json path")
        return value


class TakeoverManifest(BaseModel):
    """Pilot catalog; it intentionally cannot contain evaluation metrics."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    status: Literal["not_run"]
    tasks: tuple[ManifestSlot, ...]

    @model_validator(mode="after")
    def _pilot_must_cover_each_route_once(self) -> TakeoverManifest:
        ids = [task.id for task in self.tasks]
        paths = [task.task_file for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest task ids must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("manifest task files must be unique")
        if len(self.tasks) != len(ROUTES) or {task.route for task in self.tasks} != set(
            ROUTES
        ):
            raise ValueError("pilot manifest must contain one slot for each route")
        return self


class ReceiverOutputContract(BaseModel):
    """Small structured response contract shared by all pilot tasks."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["json"] = "json"
    required_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_fields")
    @classmethod
    def _fields_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("required_fields must be unique")
        if any(not field or "." in field for field in value):
            raise ValueError("required_fields must be non-empty top-level JSON keys")
        return value


class SuccessCheck(BaseModel):
    """One deterministic assertion applied to a receiver's JSON response."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    path: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    operator: Literal["equals", "contains_all"]
    expected: Any

    @model_validator(mode="after")
    def _expected_value_must_match_operator(self) -> SuccessCheck:
        if self.operator == "contains_all" and not isinstance(self.expected, list):
            raise ValueError("contains_all requires a JSON array in expected")
        return self


class SuccessValidator(BaseModel):
    """Task-specific deterministic checks kept out of the receiver prompt."""

    model_config = ConfigDict(extra="forbid")

    checks: tuple[SuccessCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_ids_must_be_unique(self) -> SuccessValidator:
        ids = [check.id for check in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("success check ids must be unique")
        return self


class TakeoverTask(BaseModel):
    """One receiver task and its deterministic, receiver-hidden oracle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    route: Route
    title: str = Field(min_length=1)
    sender_state: HandoffEnvelope
    contract: ReceiverContract
    receiver_instruction: str = Field(min_length=1)
    receiver_output_contract: ReceiverOutputContract
    success_validator: SuccessValidator

    @model_validator(mode="after")
    def _task_parts_must_agree(self) -> TakeoverTask:
        expected_sender, expected_receiver = _ROUTE_PARTIES[self.route]
        if self.sender_state.sender != expected_sender:
            raise ValueError(
                f"{self.route} requires sender={expected_sender!r}, "
                f"got {self.sender_state.sender!r}"
            )
        if self.sender_state.receiver != expected_receiver:
            raise ValueError(
                f"{self.route} requires receiver={expected_receiver!r}, "
                f"got {self.sender_state.receiver!r}"
            )
        if not self.contract.required:
            raise ValueError("contract.required must contain at least one section")

        output_fields = set(self.receiver_output_contract.required_fields)
        checked_fields = {check.path for check in self.success_validator.checks}
        unknown_paths = sorted(
            check.path
            for check in self.success_validator.checks
            if check.path not in output_fields
        )
        if unknown_paths:
            raise ValueError(
                "success checks must target required output fields: "
                + ", ".join(unknown_paths)
            )
        unchecked_fields = sorted(output_fields - checked_fields)
        if unchecked_fields:
            raise ValueError(
                "required output fields must have a success check: "
                + ", ".join(unchecked_fields)
            )
        return self
