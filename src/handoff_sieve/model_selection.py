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
SOURCE_IDS_KEY = "handoff_sieve.source_ids"


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
    context_source_ids: list[str] = Field(default_factory=list)
    estimated_insertion_tokens: int | None = Field(default=None, ge=0)


class SelectionRequest(BaseModel):
    """Exactly the task state sent to a model selector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receiver: str
    contract: ReceiverContract
    units: list[SourceUnit]
    fixed_packet_tokens: int | None = Field(default=None, ge=0)
    source_budget_tokens: int | None = Field(default=None, ge=0)

    def to_selector_text(self) -> str:
        """Send task content and hints, omitting host-only source coordinates."""
        catalog = []
        for unit in self.units:
            item = unit.model_dump(mode="json", exclude_none=True)
            for key in ("source_index", "start", "end"):
                item.pop(key, None)
            for key in ("tags", "metadata", "context_source_ids"):
                if not item[key]:
                    item.pop(key)
            catalog.append(item)
        payload: dict[str, Any] = {
            "receiver": self.receiver,
            "contract": self.contract.model_dump(mode="json"),
            "units": catalog,
        }
        for key in ("fixed_packet_tokens", "source_budget_tokens"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return json.dumps(
            payload,
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
    context_source_ids: list[str] = Field(default_factory=list)


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


def _source_windows(text: str) -> list[tuple[int, int, list[int]]] | None:
    """Recognize observed numbered read output, never fetch missing code.

    Keep at most forty source lines per window. The original read header and
    already observed enclosing blocks accompany a selected window. These are
    context references, not a claim to know every runtime dependency.
    """
    header = re.search(r"^File: .+ \(\d+ lines\)\r?\n", text, re.MULTILINE)
    if header is None:
        return None
    offset = header.end()
    lines: list[tuple[int, int, str]] = []
    previous: int | None = None
    for line in text[offset:].splitlines(keepends=True):
        match = re.fullmatch(r"(\d+): ?([^\r\n]*)(?:\r?\n)?", line)
        if match is None:
            return None
        number = int(match[1])
        if previous is not None and number != previous + 1:
            return None
        lines.append((offset, offset + len(line), match[2]))
        offset += len(line)
        previous = number
    if not lines:
        return None
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        end = min(start + 40, len(lines))
        # Prefer a nearby blank-line boundary, retaining the blank line itself.
        if end < len(lines):
            for boundary in range(end, max(start + 20, end - 10), -1):
                if not lines[boundary - 1][2].strip():
                    end = boundary
                    break
        ranges.append((start, end))
        start = end
    owners = {
        line: part + 1
        for part, (start, end) in enumerate(ranges)
        for line in range(start, end)
    }
    ancestors: dict[int, list[int]] = {}
    stack: list[tuple[int, int]] = []
    for number, (_, _, code) in enumerate(lines):
        stripped = code.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(code) - len(stripped)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        ancestors[number] = [owner for _, owner in stack]
        if re.match(
            r"(?:async\s+)?(?:def|class|if|elif|else|for|while|try|except|"
            r"finally|with|match|case)\b.*:\s*(?:#.*)?$",
            stripped,
        ):
            stack.append((indent, owners[number]))
    result: list[tuple[int, int, list[int]]] = [(0, header.end(), [])]
    for part, (start, end) in enumerate(ranges, 1):
        dependencies = {0}
        for number in range(start, end):
            dependencies.update(
                owner for owner in ancestors.get(number, []) if owner < part
            )
        result.append((lines[start][0], lines[end - 1][1], sorted(dependencies)))
    return result


def source_units(
    envelope: HandoffEnvelope, pipeline: HandoffPipeline
) -> list[SourceUnit]:
    """Build original units without interpreting headings or dropping unlabeled text."""
    units: list[SourceUnit] = []
    for index, message in enumerate(envelope.messages):
        content = message.content
        windows = (
            _source_windows(content)
            if message.role == "tool" and isinstance(content, str)
            else None
        )
        spans: list[tuple[int | None, int | None, list[int]]] = (
            [(start, end, context) for start, end, context in windows]
            if windows is not None
            else [(start, end, []) for start, end in _text_spans(content)]
            if isinstance(content, str)
            else [(None, None, [])]
        )
        for part, (start, end, context) in enumerate(spans):
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
                    context_source_ids=[f"m{index}.{parent}" for parent in context],
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

    def metadata(original: dict[str, Any], source_id: str) -> dict[str, Any]:
        # Sender metadata cannot manufacture the compiler's reference list.
        return {
            **{key: value for key, value in original.items() if key != SOURCE_IDS_KEY},
            SOURCE_ID_KEY: source_id,
        }

    # Ranking decides what fits; original order decides how code is presented.
    ordered = sorted(
        selections,
        key=lambda item: (
            units[item.source_id].source_type,
            units[item.source_id].source_index,
            units[item.source_id].start or 0,
        ),
    )
    previous: SourceUnit | None = None
    for selection in ordered:
        unit = units[selection.source_id]
        if unit.source_type == "artifact":
            original = source.artifacts[unit.source_index]
            artifacts.append(
                original.model_copy(
                    deep=True,
                    update={"metadata": metadata(original.metadata, unit.source_id)},
                )
            )
        else:
            original_message = source.messages[unit.source_index]
            if (
                previous is not None
                and previous.source_type == "message"
                and previous.source_index == unit.source_index
                and messages[-1].kind == selection.section
                and isinstance(original_message.content, str)
                and previous.end is not None
                and unit.start is not None
                and not original_message.content[previous.end : unit.start].strip()
            ):
                last = messages[-1]
                assert isinstance(last.content, str)
                last.content += original_message.content[previous.end : unit.end]
                ids = last.metadata.get(SOURCE_IDS_KEY, [last.metadata[SOURCE_ID_KEY]])
                last.metadata[SOURCE_IDS_KEY] = [*ids, unit.source_id]
                previous = unit
                continue
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
                    metadata=metadata(original_message.metadata, unit.source_id),
                )
            )
        previous = unit
    return HandoffEnvelope(
        sender=source.sender,
        receiver=source.receiver,
        messages=messages,
        artifacts=artifacts,
    )


def _with_context(
    selections: Sequence[SourceSelection], units: dict[str, SourceUnit]
) -> list[SourceSelection]:
    """Pin only catalogued original context; keep one category per source."""
    chosen = {item.source_id: item for item in selections}
    expanded: list[SourceSelection] = []
    visiting: set[str] = set()
    seen: set[str] = set()

    def add(item: SourceSelection) -> None:
        if item.source_id in seen:
            return
        if item.source_id in visiting or item.source_id not in units:
            raise ContractError("Invalid source context references")
        visiting.add(item.source_id)
        for source_id in units[item.source_id].context_source_ids:
            add(
                chosen.get(source_id)
                or SourceSelection(
                    source_id=source_id, section=item.section, essential=True
                )
            )
        visiting.remove(item.source_id)
        seen.add(item.source_id)
        expanded.append(item)

    for item in selections:
        add(item)
    return expanded


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


def _budgeted_request(
    source: HandoffEnvelope,
    catalog: list[SourceUnit],
    contract: ReceiverContract,
    pipeline: HandoffPipeline,
) -> SelectionRequest:
    """Expose fixed cost and conservative isolated insertion costs for planning.

    Count the actual goal and packet skeleton once. Item overhead comes from the
    canonical serializer, cached per origin with an empty goal. Content and
    compiler references are counted separately, including possible merged-ref
    metadata and preceding blank text. Context closures count each unit once.
    Shared context and coalescing can lower the sum; arbitrary/BPE counters are
    not additive, so these hints never replace the final whole-packet check.
    """
    counter = pipeline.token_counter
    fixed = counter.count_text(
        HandoffPacket(
            sender=source.sender, receiver=source.receiver, goal=contract.goal
        ).to_receiver_text()
    )
    if fixed > contract.max_tokens:
        raise BudgetExceededError(
            f"Task goal and empty canonical packet need {fixed} estimated tokens; "
            f"budget is {contract.max_tokens}. No selector call was made."
        )
    short_contract = contract.model_copy(update={"goal": ""})
    message_sections: list[SectionName] = [
        section
        for section in (*contract.required, *contract.preferred)
        if section != "artifacts"
    ]
    message_section: SectionName = (
        max(message_sections, key=len) if message_sections else "evidence"
    )
    units = {unit.source_id: unit for unit in catalog}
    overheads: dict[tuple[str, int], int] = {}
    item_costs: dict[str, int] = {}
    previous: dict[tuple[str, int], SourceUnit] = {}
    punctuation = counter.count_text(",")
    for unit in catalog:
        origin = (unit.source_type, unit.source_index)
        is_message = unit.source_type == "message"
        if origin not in overheads:
            section: SectionName = message_section if is_message else "artifacts"
            packet = _packet_for(
                source,
                units,
                [
                    SourceSelection(
                        source_id=unit.source_id, section=section, essential=True
                    )
                ],
                short_contract,
            )
            item = json.loads(packet.to_receiver_text())[section][0]
            # Empty dynamic values retain their JSON field/quote overhead. Count
            # the real values below; the extra quotes give a planning margin.
            item["content"] = ""
            item["metadata"][SOURCE_ID_KEY] = ""
            if is_message:
                item["metadata"][SOURCE_IDS_KEY] = [""]
            overheads[origin] = counter.count_text(
                json.dumps(
                    item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
        content = unit.content
        prior = previous.get(origin)
        if (
            is_message
            and prior is not None
            and prior.end is not None
            and unit.start is not None
            and isinstance(content, str)
        ):
            original = source.messages[unit.source_index].content
            if isinstance(original, str):
                gap = original[prior.end : unit.start]
                if not gap.strip():
                    content = gap + content
        item_costs[unit.source_id] = (
            overheads[origin]
            + counter.count_text(
                json.dumps(
                    content, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
            + (2 if is_message else 1) * counter.count_text(json.dumps(unit.source_id))
            + punctuation
        )
        previous[origin] = unit
    closures: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def closure(source_id: str) -> set[str]:
        if source_id in closures:
            return closures[source_id]
        if source_id in visiting or source_id not in units:
            raise ContractError("Invalid source context references")
        visiting.add(source_id)
        found = {source_id}
        for parent in units[source_id].context_source_ids:
            found.update(closure(parent))
        visiting.remove(source_id)
        closures[source_id] = found
        return found

    return SelectionRequest(
        receiver=source.receiver,
        contract=contract.model_copy(deep=True),
        units=[
            unit.model_copy(
                deep=True,
                update={
                    "estimated_insertion_tokens": sum(
                        item_costs[entry] for entry in closure(unit.source_id)
                    ),
                },
            )
            for unit in catalog
        ],
        fixed_packet_tokens=fixed,
        source_budget_tokens=contract.max_tokens - fixed,
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
        _budgeted_request(source, catalog, contract, active)
    )
    plan = response.plan
    essential_ids = _validate_plan(plan, catalog, contract)
    units = {unit.source_id: unit for unit in catalog}
    selected = _with_context(
        [item for item in plan.selections if item.source_id in essential_ids], units
    )
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
        if item.source_id in {entry.source_id for entry in selected}:
            continue
        expanded = _with_context([*selected, item], units)
        candidate = _packet_for(source, units, expanded, contract)
        if (
            active.token_counter.count_text(candidate.to_receiver_text())
            <= contract.max_tokens
        ):
            selected = expanded
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
    retained_items: list[Message | Artifact] = [
        *compilation.packet.to_envelope().messages,
        *compilation.packet.artifacts,
    ]
    retained = {
        source_id
        for item in retained_items
        for source_id in item.metadata.get(
            SOURCE_IDS_KEY, [item.metadata.get(SOURCE_ID_KEY)]
        )
    }
    if not {item.source_id for item in selected}.issubset(retained):
        raise ContractError("Cleanup removed model-selected source references")
    planned_ids = {item.source_id for item in plan.selections}
    selected_ids = {item.source_id for item in selected}
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
                unit.source_id
                for unit in catalog
                if unit.source_id not in planned_ids | selected_ids
            ],
            coverage=plan.coverage,
            context_source_ids=[
                item.source_id for item in selected if item.source_id not in planned_ids
            ],
        ),
        plan=plan,
        selector_usage=response.usage,
    )
