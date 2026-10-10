"""Model-guided selection of original state, with local packet validation.

The model produces references, never rewritten task facts. Semantic relevance
and need coverage are model judgments; source identity and budget are checked
locally. This is an opt-in API and does not change deterministic compilation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from handoff_sieve.compiler import (
    SECTION_NAMES,
    HandoffCompilation,
    HandoffPacket,
    ReceiverContract,
    SectionName,
    compile_handoff,
)
from handoff_sieve.exceptions import BudgetExceededError, ContractError
from handoff_sieve.models import Artifact, HandoffEnvelope, Message
from handoff_sieve.pipeline import HandoffPipeline

SOURCE_ID_KEY = "handoff_sieve.source_id"


class SourceUnit(BaseModel):
    """An addressable original text span or an atomic structured value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_type: Literal["message", "artifact"]
    source_index: int
    start: int | None = None
    end: int | None = None
    role: str
    name: str | None = None
    hint: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str | dict[str, Any] | list[Any]
    estimated_tokens: int


class SelectionRequest(BaseModel):
    """Exactly the task state sent to a model selector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receiver: str
    contract: ReceiverContract
    units: list[SourceUnit]

    def to_selector_text(self) -> str:
        """Send task content and hints, omitting host-only source coordinates."""
        catalog = []
        for unit in self.units:
            item = unit.model_dump(mode="json", exclude_none=True)
            for key in ("source_index", "start", "end"):
                item.pop(key, None)
            for key in ("tags", "metadata"):
                if not item[key]:
                    item.pop(key)
            catalog.append(item)
        return json.dumps(
            {
                "receiver": self.receiver,
                "contract": self.contract.model_dump(mode="json"),
                "units": catalog,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_id: str
    section: SectionName
    essential: bool


class NeedCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    need_index: int = Field(ge=0)
    source_ids: list[str]


class SelectionPlan(BaseModel):
    """A ranked extraction plan, not a model-generated summary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    selections: list[SourceSelection]
    coverage: list[NeedCoverage]
    missing_needs: list[int]


class SelectionUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str | None = None
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    seconds: float | None = None
    model_calls: int = 1


class SelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: SelectionPlan
    usage: SelectionUsage = Field(default_factory=SelectionUsage)


class HandoffSelector(Protocol):
    async def select(self, request: SelectionRequest) -> SelectionResponse: ...


class SelectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_unit_count: int
    selected_source_ids: list[str]
    budget_omitted_source_ids: list[str]
    unselected_source_ids: list[str]
    coverage: list[NeedCoverage]


class ModelHandoffCompilation(HandoffCompilation):
    """A packet, extraction plan, local validation and selector call usage."""

    selection: SelectionReport
    plan: SelectionPlan
    selector_usage: SelectionUsage


def _text_spans(text: str) -> list[tuple[int, int]]:
    """Keep lines and fenced blocks intact; retain original character offsets."""
    spans: list[tuple[int, int]] = []
    offset = 0
    fence_start: int | None = None
    fence_marker = ""
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        match = re.match(r"(`{3,}|~{3,})", stripped)
        end = offset + len(line)
        if fence_start is not None:
            if (
                match
                and match.group()[0] == fence_marker[0]
                and len(match.group()) >= len(fence_marker)
            ):
                spans.append((fence_start, end))
                fence_start = None
        elif match:
            fence_start = offset
            fence_marker = match.group()
        elif line.strip():
            spans.append((offset, end))
        offset = end
    if fence_start is not None:
        spans.append((fence_start, len(text)))
    return spans


def source_units(
    envelope: HandoffEnvelope, pipeline: HandoffPipeline
) -> list[SourceUnit]:
    """Build original units without interpreting headings or dropping unlabeled text."""
    units: list[SourceUnit] = []
    for index, message in enumerate(envelope.messages):
        content = message.content
        spans: list[tuple[int | None, int | None]] = (
            list(_text_spans(content)) if isinstance(content, str) else [(None, None)]
        )
        for part, (start, end) in enumerate(spans):
            value = content[start:end] if isinstance(content, str) else content
            serialized = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)
            )
            units.append(
                SourceUnit(
                    source_id=f"m{index}.{part}",
                    source_type="message",
                    source_index=index,
                    start=start,
                    end=end,
                    role=message.role,
                    hint=message.kind,
                    tags=sorted(message.tags),
                    metadata=message.metadata,
                    content=value,
                    estimated_tokens=pipeline.token_counter.count_text(serialized),
                )
            )
    for index, artifact in enumerate(envelope.artifacts):
        serialized = (
            artifact.content
            if isinstance(artifact.content, str)
            else json.dumps(artifact.content, ensure_ascii=False)
        )
        units.append(
            SourceUnit(
                source_id=f"a{index}",
                source_type="artifact",
                source_index=index,
                role="artifact",
                name=artifact.name,
                hint="artifacts",
                metadata=artifact.metadata,
                content=artifact.content,
                estimated_tokens=pipeline.token_counter.count_text(serialized),
            )
        )
    return units


def _validate_plan(
    plan: SelectionPlan, units: list[SourceUnit], contract: ReceiverContract
) -> set[str]:
    available = {unit.source_id: unit for unit in units}
    allowed = set((*contract.required, *contract.preferred))
    selected: dict[str, SourceSelection] = {}
    for item in plan.selections:
        if item.source_id not in available:
            raise ContractError(f"Model selected unknown source ID: {item.source_id}")
        if item.source_id in selected:
            raise ContractError(f"Model selected a source twice: {item.source_id}")
        if item.section not in allowed:
            raise ContractError(
                f"Model selected an unrequested section: {item.section}"
            )
        if (item.section == "artifacts") != (
            available[item.source_id].source_type == "artifact"
        ):
            raise ContractError(
                "Model cannot turn message text into an artifact or vice versa"
            )
        selected[item.source_id] = item
    if not selected:
        raise ContractError("Model selected no receiver state")
    present = {item.section for item in selected.values()}
    missing = set(contract.required) - present
    if missing:
        raise ContractError(
            "Model omitted required sections: " + ", ".join(sorted(missing))
        )
    if plan.missing_needs:
        raise ContractError(
            "Sender state cannot satisfy need indices: " + str(plan.missing_needs)
        )
    essential = {
        item.source_id
        for item in plan.selections
        if item.essential or item.section in contract.required
    }
    covered: set[int] = set()
    for coverage in plan.coverage:
        if coverage.need_index >= len(contract.needs) or coverage.need_index in covered:
            raise ContractError("Model returned an invalid or repeated need index")
        if not coverage.source_ids or len(set(coverage.source_ids)) != len(
            coverage.source_ids
        ):
            raise ContractError("Need coverage must cite distinct selected source IDs")
        if not set(coverage.source_ids).issubset(selected):
            raise ContractError(
                "Need coverage cites state absent from the selection plan"
            )
        covered.add(coverage.need_index)
        essential.update(coverage.source_ids)
    if covered != set(range(len(contract.needs))):
        raise ContractError(
            "Model did not supply source coverage for every receiver need"
        )
    return essential


def _selected_envelope(
    source: HandoffEnvelope,
    units: dict[str, SourceUnit],
    selections: Sequence[SourceSelection],
) -> HandoffEnvelope:
    messages: list[Message] = []
    artifacts: list[Artifact] = []
    for selection in selections:
        unit = units[selection.source_id]
        if unit.source_type == "artifact":
            original = source.artifacts[unit.source_index]
            artifacts.append(
                original.model_copy(
                    deep=True,
                    update={
                        "metadata": {**original.metadata, SOURCE_ID_KEY: unit.source_id}
                    },
                )
            )
        else:
            original_message = source.messages[unit.source_index]
            messages.append(
                Message(
                    role=original_message.role,
                    kind=selection.section,
                    content=(
                        original_message.content[unit.start : unit.end]
                        if isinstance(original_message.content, str)
                        else original_message.content
                    ),
                    tags=original_message.tags - set(SECTION_NAMES),
                    metadata={
                        **original_message.metadata,
                        SOURCE_ID_KEY: unit.source_id,
                    },
                )
            )
    return HandoffEnvelope(
        sender=source.sender,
        receiver=source.receiver,
        messages=messages,
        artifacts=artifacts,
    )


def _packet_for(
    source: HandoffEnvelope,
    units: dict[str, SourceUnit],
    selections: Sequence[SourceSelection],
    contract: ReceiverContract,
) -> HandoffPacket:
    envelope = _selected_envelope(source, units, selections)
    sections: dict[str, Any] = {section: [] for section in SECTION_NAMES}
    for message in envelope.messages:
        sections[message.kind].append(message)
    sections["artifacts"] = envelope.artifacts
    return HandoffPacket(
        sender=source.sender, receiver=source.receiver, goal=contract.goal, **sections
    )


async def compile_model_handoff(
    envelope: HandoffEnvelope,
    contract: ReceiverContract,
    *,
    selector: HandoffSelector,
    pipeline: HandoffPipeline | None = None,
    request_id: str | None = None,
) -> ModelHandoffCompilation:
    """Select receiver-relevant original spans, then enforce a real packet budget.

    All selected content in required sections, essential selections, and need
    coverage stays mandatory. Optional selections follow the model's ranking.
    Missing coverage, unknown references and an essential packet over budget
    raise; they never trigger a silent fallback or an additional model call.
    Coverage checks prove references exist, not semantic task sufficiency.
    """
    source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
    active = pipeline or HandoffPipeline()
    catalog = source_units(source, active)
    if not catalog:
        raise ContractError("Sender state contains no nonblank source units")
    response = await selector.select(
        SelectionRequest(
            receiver=source.receiver,
            contract=contract.model_copy(deep=True),
            units=[unit.model_copy(deep=True) for unit in catalog],
        )
    )
    plan = response.plan
    essential_ids = _validate_plan(plan, catalog, contract)
    units = {unit.source_id: unit for unit in catalog}
    selected = [item for item in plan.selections if item.source_id in essential_ids]
    required_packet = _packet_for(source, units, selected, contract)
    required_tokens = active.token_counter.count_text(
        required_packet.to_receiver_text()
    )
    if required_tokens > contract.max_tokens:
        raise BudgetExceededError(
            f"Essential model-selected state needs {required_tokens} estimated tokens; "
            f"budget is {contract.max_tokens}. No essential evidence was removed."
        )
    omitted: list[str] = []
    for item in plan.selections:
        if item.source_id in essential_ids:
            continue
        candidate = _packet_for(source, units, [*selected, item], contract)
        if (
            active.token_counter.count_text(candidate.to_receiver_text())
            <= contract.max_tokens
        ):
            selected.append(item)
        else:
            omitted.append(item.source_id)
    if not selected:
        raise BudgetExceededError(
            "No model-selected source item fits the packet budget"
        )
    # Protect every item already fitted, even when a caller supplies cleanup policies.
    sections = tuple(
        section
        for section in SECTION_NAMES
        if any(item.section == section for item in selected)
    )
    compilation = compile_handoff(
        _selected_envelope(source, units, selected),
        contract.model_copy(
            update={"required": sections, "preferred": (), "needs": ()}
        ),
        pipeline=active,
        request_id=request_id,
    )
    retained = {
        item.metadata.get(SOURCE_ID_KEY)
        for item in compilation.packet.to_envelope().messages
    } | {item.metadata.get(SOURCE_ID_KEY) for item in compilation.packet.artifacts}
    if not {item.source_id for item in selected}.issubset(retained):
        raise ContractError("Cleanup removed model-selected source references")
    planned_ids = {item.source_id for item in plan.selections}
    compilation.report.add_event(
        "model_selector",
        "selected",
        count=len(selected),
        details={
            "source_units": len(catalog),
            "model_calls": response.usage.model_calls,
        },
    )
    return ModelHandoffCompilation(
        **{
            **compilation.model_dump(mode="python"),
            "source_tokens": active.token_counter.count_envelope(source),
            "omitted_count": len(catalog) - len(selected),
        },
        selection=SelectionReport(
            source_unit_count=len(catalog),
            selected_source_ids=[item.source_id for item in selected],
            budget_omitted_source_ids=omitted,
            unselected_source_ids=[
                unit.source_id for unit in catalog if unit.source_id not in planned_ids
            ],
            coverage=plan.coverage,
        ),
        plan=plan,
        selector_usage=response.usage,
    )
