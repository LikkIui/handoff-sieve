"""Optional, explicit preparation of current sender state before compilation."""

from __future__ import annotations

import json
from typing import cast

from handoff_sieve.compiler import MESSAGE_SECTION_NAMES, SectionName
from handoff_sieve.exceptions import ContractError
from handoff_sieve.models import Artifact, HandoffEnvelope, Message

_MESSAGE_SECTIONS = frozenset(MESSAGE_SECTION_NAMES)


def prepare_sender_state(
    envelope: HandoffEnvelope,
    *,
    task_id: str | None = None,
    deduplicate: bool = True,
) -> HandoffEnvelope:
    """Copy and explicitly organize state before a receiver's budget is applied.

    With ``task_id``, keep matching ``metadata.task_id`` items and unscoped
    shared items. Matching is exact; goals and prose are never interpreted.
    Only messages with an exact section kind/tag and ``metadata.state_key``
    participate in state updates. Within the same task scope and section,
    the last keyed message wins. A later ``completed_work`` message also
    closes earlier ``pending_work`` with that key; later pending work can
    reopen it. Shared and task-specific keys do not overwrite each other.

    Exact public duplicates are removed after state updates when requested.
    Artifacts are scoped and deduplicated, never replaced by filename or key.
    Explicit task IDs and message state keys must be nonblank strings, or
    ``ValueError`` is raised. Ambiguous section labels raise ``ContractError``.
    The source is unchanged and private processing fields are not propagated.
    """

    if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
        raise ValueError("task_id must be a nonblank string or None")
    source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
    selected: list[Message] = []
    keep: list[bool] = []
    latest: dict[tuple[str | None, SectionName, str], int] = {}
    for index, message in enumerate(source.messages):
        scope = _metadata_string(message, "task_id", label=f"Message {index}")
        key = _metadata_string(message, "state_key", label=f"Message {index}")
        if task_id is not None and scope is not None and scope != task_id:
            continue
        section = _explicit_section(message, index=index)
        position = len(selected)
        selected.append(message)
        keep.append(True)
        if key is None or section is None:
            continue
        state = (scope, section, key)
        previous = latest.get(state)
        if previous is not None:
            keep[previous] = False
        latest[state] = position
        if section == "completed_work":
            pending = latest.pop((scope, "pending_work", key), None)
            if pending is not None:
                keep[pending] = False

    messages = [
        message for message, retained in zip(selected, keep, strict=True) if retained
    ]
    artifacts: list[Artifact] = []
    for index, artifact in enumerate(source.artifacts):
        scope = _metadata_string(artifact, "task_id", label=f"Artifact {index}")
        if task_id is None or scope is None or scope == task_id:
            artifacts.append(artifact)
    if deduplicate:
        messages = _deduplicate_messages(messages)
        artifacts = _deduplicate_artifacts(artifacts)
    return source.model_copy(update={"messages": messages, "artifacts": artifacts})


def _metadata_string(
    item: Message | Artifact,
    field: str,
    *,
    label: str,
) -> str | None:
    if field not in item.metadata:
        return None
    value = item.metadata[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} metadata.{field} must be a nonblank string")
    return value


def _explicit_section(message: Message, *, index: int) -> SectionName | None:
    sections = {message.kind, *message.tags}.intersection(_MESSAGE_SECTIONS)
    if len(sections) > 1:
        raise ContractError(
            f"Message {index} maps to multiple receiver sections: "
            + ", ".join(sorted(sections))
            + ". Use exactly one section kind or tag."
        )
    return cast(SectionName, next(iter(sections))) if sections else None


def _public_identity(item: Message | Artifact) -> str:
    payload = item.model_dump(mode="json")
    if isinstance(item, Message):
        payload["tags"] = sorted(payload["tags"])
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _deduplicate_messages(messages: list[Message]) -> list[Message]:
    seen: set[str] = set()
    output: list[Message] = []
    for message in messages:
        identity = _public_identity(message)
        if identity not in seen:
            seen.add(identity)
            output.append(message)
    return output


def _deduplicate_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
    seen: set[str] = set()
    output: list[Artifact] = []
    for artifact in artifacts:
        identity = _public_identity(artifact)
        if identity not in seen:
            seen.add(identity)
            output.append(artifact)
    return output
