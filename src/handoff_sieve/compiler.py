"""Strict deterministic receiver-specific handoff compilation.

This low-level compiler expects already classified messages and calls no model.
Use :func:`handoff_sieve.compile_history` to classify common agent-history
shapes with transparent local rules before applying the same compiler.
"""

from __future__ import annotations

import json
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from handoff_sieve.exceptions import BudgetExceededError, ContractError
from handoff_sieve.models import Artifact, HandoffEnvelope, Message
from handoff_sieve.pipeline import HandoffPipeline
from handoff_sieve.policies.base import Policy, PolicyContext
from handoff_sieve.report import AuditReport
from handoff_sieve.tokens import TokenCounter

SectionName = Literal[
    "constraints",
    "decisions",
    "evidence",
    "completed_work",
    "failed_attempts",
    "pending_work",
    "artifacts",
    "tool_results",
]

SECTION_NAMES: tuple[SectionName, ...] = (
    "constraints",
    "decisions",
    "evidence",
    "completed_work",
    "failed_attempts",
    "pending_work",
    "artifacts",
    "tool_results",
)
MESSAGE_SECTION_NAMES: tuple[SectionName, ...] = tuple(
    section for section in SECTION_NAMES if section != "artifacts"
)

_MESSAGE_SECTION_SET = frozenset(MESSAGE_SECTION_NAMES)
_SECTION_INTERNAL_KEY = "handoff_sieve.receiver_section"


class ContractDiagnostics(BaseModel):
    """Inspect missing receiver state without copying source content.

    Indices refer to the envelope passed to history normalization, or to the
    original envelope in the strict compiler. ``None`` means that an origin
    mapping is unavailable, rather than that there were no unclassified items.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Literal["sender_state", "pipeline_output"]
    missing_sections: tuple[SectionName, ...]
    section_counts: dict[SectionName, int]
    unclassified_message_indices: tuple[int, ...] | None = None
    recovery_hints: dict[SectionName, str]

    def to_text(self) -> str:
        available = (
            ", ".join(
                f"{section}={count}"
                for section, count in self.section_counts.items()
                if count
            )
            or "none"
        )
        lines = [f"Available sections ({self.stage}): {available}."]
        if self.unclassified_message_indices is not None:
            indices = ", ".join(map(str, self.unclassified_message_indices)) or "none"
            lines.append(f"Unclassified input message indices (0-based): {indices}.")
        lines.extend(
            f"{section}: {hint}" for section, hint in self.recovery_hints.items()
        )
        return "\n".join(lines)


_SECTION_HEADINGS: dict[SectionName, str] = {
    "constraints": "Constraint:",
    "decisions": "Decision:",
    "evidence": "Evidence:",
    "completed_work": "Completed:",
    "failed_attempts": "Failed attempt:",
    "pending_work": "TODO:",
    "tool_results": "Tool result:",
    "artifacts": "",
}


def _missing_state_diagnostics(
    missing: list[SectionName],
    section_counts: dict[SectionName, int],
    *,
    stage: Literal["sender_state", "pipeline_output"],
    unclassified_indices: tuple[int, ...] | None = None,
) -> ContractDiagnostics:
    hints: dict[SectionName, str] = {}
    for section in missing:
        if stage == "pipeline_output":
            hints[section] = (
                "Inspect the processing policy that removed this required section; "
                "it was present before the pipeline ran."
            )
        elif section == "artifacts":
            hints[section] = "Add actual files or outputs to HandoffEnvelope.artifacts."
        else:
            hints[section] = (
                f"Supply actual {section} state as Message(kind='{section}', ...). "
                f"For compile_history, '{_SECTION_HEADINGS[section]}' also labels it. "
                "Label only relevant state; do not reclassify unrelated notes."
            )
    return ContractDiagnostics(
        stage=stage,
        missing_sections=tuple(missing),
        section_counts=section_counts,
        unclassified_message_indices=unclassified_indices,
        recovery_hints=hints,
    )


class ReceiverContract(BaseModel):
    """The explicit context requirements for one receiving agent.

    ``required`` sections must exist in full and fit the hard budget.
    ``preferred`` sections are considered in declaration order and included
    item by item while they fit. Section names must be one of ``SectionName``.
    ``compile_history`` can normalize common headings, structured keys, and
    tool outputs; this strict compiler itself performs exact matching only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str
    required: tuple[SectionName, ...] = Field(default_factory=tuple)
    preferred: tuple[SectionName, ...] = Field(default_factory=tuple)
    max_tokens: int = Field(gt=0)

    @field_validator("goal")
    @classmethod
    def _goal_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("goal must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _sections_must_be_unambiguous(self) -> ReceiverContract:
        repeated_required = _duplicates(self.required)
        repeated_preferred = _duplicates(self.preferred)
        overlap = sorted(set(self.required).intersection(self.preferred))
        if repeated_required:
            raise ValueError(
                "required contains duplicate sections: " + ", ".join(repeated_required)
            )
        if repeated_preferred:
            raise ValueError(
                "preferred contains duplicate sections: "
                + ", ".join(repeated_preferred)
            )
        if overlap:
            raise ValueError(
                "sections cannot be both required and preferred: " + ", ".join(overlap)
            )
        return self


class HandoffPacket(BaseModel):
    """A receiver-specific, structured task takeover packet."""

    model_config = ConfigDict(extra="forbid")

    sender: str
    receiver: str
    goal: str
    constraints: list[Message] = Field(default_factory=list)
    decisions: list[Message] = Field(default_factory=list)
    evidence: list[Message] = Field(default_factory=list)
    completed_work: list[Message] = Field(default_factory=list)
    failed_attempts: list[Message] = Field(default_factory=list)
    pending_work: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    tool_results: list[Message] = Field(default_factory=list)

    @property
    def item_count(self) -> int:
        """Return the number of source items represented by the packet."""

        message_count = sum(
            len(getattr(self, section)) for section in MESSAGE_SECTION_NAMES
        )
        return message_count + len(self.artifacts)

    def to_envelope(self) -> HandoffEnvelope:
        """Flatten packet sections for an existing framework adapter."""

        messages: list[Message] = []
        for section in MESSAGE_SECTION_NAMES:
            messages.extend(
                Message.model_validate(message.model_dump(mode="python"))
                for message in getattr(self, section)
            )
        return HandoffEnvelope(
            sender=self.sender,
            receiver=self.receiver,
            messages=messages,
            artifacts=[artifact.model_copy(deep=True) for artifact in self.artifacts],
            metadata={"goal": self.goal},
        )

    def to_receiver_text(self) -> str:
        """Return the canonical JSON receiver view used for token counting.

        The representation is deterministic and contains the complete public
        packet, including its goal and artifacts. Framework adapters can send
        this text directly without inventing a second rendering whose size or
        contents drift from the compiled packet.
        """

        public_packet = self.model_dump(mode="json")
        for section in MESSAGE_SECTION_NAMES:
            for message in public_packet[section]:
                message["tags"] = sorted(message["tags"])
        return json.dumps(
            public_packet,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class HandoffCompilation(BaseModel):
    """The compiled packet plus measurements from the original pipeline."""

    model_config = ConfigDict(extra="forbid")

    packet: HandoffPacket
    report: AuditReport
    source_tokens: int = Field(ge=0)
    packet_tokens: int = Field(ge=0)
    omitted_count: int = Field(ge=0)

    @property
    def estimated_tokens_saved(self) -> int:
        """Estimated context removed between sender state and final packet."""

        return max(0, self.source_tokens - self.packet_tokens)

    @property
    def estimated_savings_percent(self) -> float:
        """Estimated context reduction, safe for an empty source."""

        if self.source_tokens == 0:
            return 0.0
        return round(self.estimated_tokens_saved / self.source_tokens * 100, 1)


class _ReceiverContractPolicy(Policy):
    """Enforce the final packet contract before the pipeline emits its report."""

    name = "receiver_contract"

    def __init__(self, contract: ReceiverContract) -> None:
        self.contract = contract

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        processed = _packet_from_pipeline_result(envelope)
        missing = [
            section
            for section in self.contract.required
            if not _packet_section_has_items(processed, section)
        ]
        if missing:
            raise ContractError(
                "Pipeline removed required receiver section(s): " + ", ".join(missing),
                diagnostics=_missing_state_diagnostics(
                    missing,
                    {
                        section: len(getattr(processed, section))
                        for section in SECTION_NAMES
                    },
                    stage="pipeline_output",
                ),
            )

        packet, kept_positions = _fit_processed_packet(
            processed,
            self.contract,
            context.token_counter,
            report=context.report,
        )
        seen_positions: dict[SectionName, int] = {
            section: 0 for section in SECTION_NAMES
        }
        kept_messages: list[Message] = []
        for message in envelope.messages:
            section = message.internal.get(_SECTION_INTERNAL_KEY)
            if section not in _MESSAGE_SECTION_SET:
                continue
            typed_section = cast(SectionName, section)
            position = seen_positions[typed_section]
            seen_positions[typed_section] += 1
            if position in kept_positions[typed_section]:
                kept_messages.append(message)

        output = envelope.model_copy(deep=True)
        output.messages = kept_messages
        output.artifacts = [
            artifact
            for position, artifact in enumerate(output.artifacts)
            if position in kept_positions["artifacts"]
        ]
        omitted_messages = len(envelope.messages) - len(output.messages)
        omitted_artifacts = len(envelope.artifacts) - len(output.artifacts)
        context.report.removed_messages += omitted_messages
        context.report.add_event(
            self.name,
            "compiled",
            count=omitted_messages + omitted_artifacts,
            details={
                "max_tokens": self.contract.max_tokens,
                "packet_tokens": _count_packet(packet, context.token_counter),
            },
        )
        return output


def compile_handoff(
    envelope: HandoffEnvelope,
    contract: ReceiverContract,
    *,
    pipeline: HandoffPipeline | None = None,
    request_id: str | None = None,
) -> HandoffCompilation:
    """Compile sender state into the smallest packet allowed by ``contract``.

    Required sections are copied first and fail closed when absent or over
    budget. Preferred sections are then considered in contract order; an item
    is omitted when adding it would exceed ``max_tokens``. All matching is
    exact and deterministic. Selected messages are protected while the normal
    pipeline runs, so selection, summarization, and budgeting cannot silently
    remove contract content; redaction and validation can still transform it.
    """

    active_pipeline = pipeline or HandoffPipeline()
    counter = active_pipeline.token_counter
    source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
    source_tokens = counter.count_envelope(source)

    by_section = _classify_messages(source.messages)
    missing = [
        section
        for section in contract.required
        if not _section_has_items(section, by_section, source.artifacts)
    ]
    if missing:
        classified_ids = {
            id(message) for messages in by_section.values() for message in messages
        }
        raise ContractError(
            "Required receiver section(s) missing from sender state: "
            + ", ".join(missing)
            + ". Add an exact section name to Message.kind/tags, or provide "
            "HandoffEnvelope.artifacts for the artifacts section.",
            diagnostics=_missing_state_diagnostics(
                missing,
                {
                    section: (
                        len(source.artifacts)
                        if section == "artifacts"
                        else len(by_section[section])
                    )
                    for section in SECTION_NAMES
                },
                stage="sender_state",
                unclassified_indices=tuple(
                    index
                    for index, message in enumerate(source.messages)
                    if id(message) not in classified_ids
                ),
            ),
        )

    selected_messages: list[Message] = []
    selected_artifacts: list[Artifact] = []
    selected_ids: set[int] = set()

    for section in contract.required:
        _append_section(
            section,
            by_section=by_section,
            artifacts=source.artifacts,
            selected_messages=selected_messages,
            selected_artifacts=selected_artifacts,
            selected_ids=selected_ids,
        )

    required_packet = _packet_from_selected(
        source,
        contract,
        selected_messages,
        selected_artifacts,
    )
    required_tokens = _count_packet(required_packet, counter)
    if required_tokens > contract.max_tokens:
        raise BudgetExceededError(
            "Required receiver context needs "
            f"{required_tokens} estimated tokens, exceeding the contract "
            f"budget of {contract.max_tokens}. No required content was removed."
        )

    for section in contract.preferred:
        if section == "artifacts":
            candidates: list[Message | Artifact] = list(source.artifacts)
        else:
            candidates = list(by_section[section])
        for item in candidates:
            candidate_messages = list(selected_messages)
            candidate_artifacts = list(selected_artifacts)
            if isinstance(item, Message):
                if id(item) in selected_ids:
                    continue
                candidate_messages.append(item)
            else:
                candidate_artifacts.append(item)
            candidate_packet = _packet_from_selected(
                source,
                contract,
                candidate_messages,
                candidate_artifacts,
            )
            if _count_packet(candidate_packet, counter) > contract.max_tokens:
                continue
            selected_messages = candidate_messages
            selected_artifacts = candidate_artifacts
            if isinstance(item, Message):
                selected_ids.add(id(item))

    protected_messages: list[Message] = []
    for item_number, message in enumerate(selected_messages):
        message_section = _message_section(message, item_number=item_number)
        if message_section is None:
            continue
        protected = Message.model_validate(message.model_dump(mode="python"))
        protected._mark_protected()
        protected._replace_internal({_SECTION_INTERNAL_KEY: message_section})
        protected_messages.append(protected)

    selected_envelope = HandoffEnvelope(
        sender=source.sender,
        receiver=source.receiver,
        messages=protected_messages,
        artifacts=[artifact.model_copy(deep=True) for artifact in selected_artifacts],
        # Only receiver-visible metadata enters the cleanup pipeline. Source
        # metadata that was not requested by the contract is deliberately
        # left out of the minimal receiver view.
        metadata={"goal": contract.goal},
    )
    pipeline_result = active_pipeline._process_trusted_envelope(
        selected_envelope,
        request_id=request_id,
        final_policies=(_ReceiverContractPolicy(contract),),
    )
    processed_packet = _packet_from_pipeline_result(pipeline_result.envelope)
    packet = processed_packet
    packet_tokens = _count_packet(packet, counter)

    source_item_count = len(source.messages) + len(source.artifacts)
    return HandoffCompilation(
        packet=packet,
        report=pipeline_result.report,
        source_tokens=source_tokens,
        packet_tokens=packet_tokens,
        omitted_count=max(0, source_item_count - packet.item_count),
    )


def _duplicates(sections: tuple[SectionName, ...]) -> list[str]:
    seen: set[SectionName] = set()
    duplicates: set[str] = set()
    for section in sections:
        if section in seen:
            duplicates.add(section)
        seen.add(section)
    return sorted(duplicates)


def _message_section(message: Message, *, item_number: int) -> SectionName | None:
    matches: set[SectionName] = {
        section for section in MESSAGE_SECTION_NAMES if section in message.tags
    }
    if message.kind == "artifacts":
        raise ContractError(
            f"Message {item_number} uses the 'artifacts' section. Put files "
            "and outputs in HandoffEnvelope.artifacts instead."
        )
    for section in MESSAGE_SECTION_NAMES:
        if message.kind == section:
            matches.add(section)
    if len(matches) > 1:
        raise ContractError(
            f"Message {item_number} maps to multiple receiver sections: "
            + ", ".join(sorted(matches))
            + ". Use exactly one section kind or tag."
        )
    if not matches:
        return None
    return next(iter(matches))


def _classify_messages(messages: list[Message]) -> dict[SectionName, list[Message]]:
    by_section: dict[SectionName, list[Message]] = {
        section: [] for section in SECTION_NAMES
    }
    for item_number, message in enumerate(messages):
        section = _message_section(message, item_number=item_number)
        if section is not None:
            by_section[section].append(message)
    return by_section


def _section_has_items(
    section: SectionName,
    by_section: dict[SectionName, list[Message]],
    artifacts: list[Artifact],
) -> bool:
    if section == "artifacts":
        return bool(artifacts)
    return bool(by_section[section])


def _append_section(
    section: SectionName,
    *,
    by_section: dict[SectionName, list[Message]],
    artifacts: list[Artifact],
    selected_messages: list[Message],
    selected_artifacts: list[Artifact],
    selected_ids: set[int],
) -> None:
    if section == "artifacts":
        selected_artifacts.extend(artifacts)
        return
    for message in by_section[section]:
        if id(message) in selected_ids:
            continue
        selected_messages.append(message)
        selected_ids.add(id(message))


def _packet_from_selected(
    source: HandoffEnvelope,
    contract: ReceiverContract,
    messages: list[Message],
    artifacts: list[Artifact],
) -> HandoffPacket:
    by_section = _classify_messages(messages)
    return HandoffPacket(
        sender=source.sender,
        receiver=source.receiver,
        goal=contract.goal,
        constraints=_public_messages(by_section["constraints"]),
        decisions=_public_messages(by_section["decisions"]),
        evidence=_public_messages(by_section["evidence"]),
        completed_work=_public_messages(by_section["completed_work"]),
        failed_attempts=_public_messages(by_section["failed_attempts"]),
        pending_work=_public_messages(by_section["pending_work"]),
        artifacts=[artifact.model_copy(deep=True) for artifact in artifacts],
        tool_results=_public_messages(by_section["tool_results"]),
    )


def _packet_from_pipeline_result(
    envelope: HandoffEnvelope,
) -> HandoffPacket:
    goal = envelope.metadata.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ContractError("Pipeline removed or invalidated the receiver goal.")
    by_section: dict[SectionName, list[Message]] = {
        section: [] for section in SECTION_NAMES
    }
    for message in envelope.messages:
        section = message.internal.get(_SECTION_INTERNAL_KEY)
        if section in _MESSAGE_SECTION_SET:
            by_section[cast(SectionName, section)].append(message)
    return HandoffPacket(
        sender=envelope.sender,
        receiver=envelope.receiver,
        goal=goal,
        constraints=_public_messages(by_section["constraints"]),
        decisions=_public_messages(by_section["decisions"]),
        evidence=_public_messages(by_section["evidence"]),
        completed_work=_public_messages(by_section["completed_work"]),
        failed_attempts=_public_messages(by_section["failed_attempts"]),
        pending_work=_public_messages(by_section["pending_work"]),
        artifacts=[artifact.model_copy(deep=True) for artifact in envelope.artifacts],
        tool_results=_public_messages(by_section["tool_results"]),
    )


def _public_messages(messages: list[Message]) -> list[Message]:
    return [
        Message.model_validate(message.model_dump(mode="python"))
        for message in messages
    ]


def _packet_section_has_items(
    packet: HandoffPacket,
    section: SectionName,
) -> bool:
    return bool(getattr(packet, section))


def _fit_processed_packet(
    processed: HandoffPacket,
    contract: ReceiverContract,
    counter: TokenCounter,
    *,
    report: AuditReport,
) -> tuple[HandoffPacket, dict[SectionName, set[int]]]:
    packet = HandoffPacket(
        sender=processed.sender,
        receiver=processed.receiver,
        goal=processed.goal,
    )
    kept_positions: dict[SectionName, set[int]] = {
        section: set() for section in SECTION_NAMES
    }
    for section in contract.required:
        items = getattr(processed, section)
        setattr(
            packet,
            section,
            [item.model_copy(deep=True) for item in items],
        )
        kept_positions[section].update(range(len(items)))

    required_tokens = _count_packet(packet, counter)
    if required_tokens > contract.max_tokens:
        raise BudgetExceededError(
            "Processed required receiver context needs "
            f"{required_tokens} estimated tokens, exceeding the contract budget "
            f"of {contract.max_tokens}. No required content was removed.",
            report=report,
        )

    for section in contract.preferred:
        for position, item in enumerate(getattr(processed, section)):
            candidate = packet.model_copy(deep=True)
            getattr(candidate, section).append(item.model_copy(deep=True))
            if _count_packet(candidate, counter) <= contract.max_tokens:
                packet = candidate
                kept_positions[section].add(position)
    return packet, kept_positions


def _count_packet(packet: HandoffPacket, counter: TokenCounter) -> int:
    return counter.count_text(packet.to_receiver_text())
