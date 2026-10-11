"""A concise receiver brief with independently checked original excerpts.

References and excerpts are checked locally; generated statements are model
judgments, not verified entailments. The original extraction API is unchanged.
"""

from __future__ import annotations

import json
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
from handoff_sieve.model_selection import (
    SOURCE_ID_KEY,
    SOURCE_IDS_KEY,
    SelectionRequest,
    SelectionUsage,
    SourceUnit,
)
from handoff_sieve.models import Artifact, HandoffEnvelope, Message
from handoff_sieve.pipeline import HandoffPipeline

BRIEF_SOURCES = "handoff_sieve.brief_sources"
BRIEF_STATUS = "handoff_sieve.brief_status"
EXCERPT_SOURCE = "handoff_sieve.excerpt_source"
EXCERPT_LINES = "handoff_sieve.excerpt_lines"
ITEM_ID = "handoff_sieve.hybrid_item"
_RESERVED = {
    BRIEF_SOURCES,
    BRIEF_STATUS,
    EXCERPT_SOURCE,
    EXCERPT_LINES,
    ITEM_ID,
    SOURCE_ID_KEY,
    SOURCE_IDS_KEY,
}


class BriefStatement(BaseModel):
    """A generated statement; citations do not prove its semantic correctness."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    section: SectionName
    content: str
    source_ids: list[str]
    need_indices: list[int]
    status: Literal["observed", "proposed", "uncertain"]


class SourceExcerpt(BaseModel):
    """Inclusive message line coordinates, or an entire value with null bounds."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_id: str
    section: SectionName
    start_line: int | None
    end_line: int | None
    essential: bool


class HybridPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    brief: list[BriefStatement]
    excerpts: list[SourceExcerpt]
    missing_needs: list[int]


class HybridResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: HybridPlan
    usage: SelectionUsage = Field(default_factory=SelectionUsage)


class HandoffComposer(Protocol):
    async def compose(self, request: SelectionRequest) -> HybridResponse: ...


class HybridHandoffCompilation(HandoffCompilation):
    plan: HybridPlan
    composer_usage: SelectionUsage
    budget_omitted_excerpt_indices: list[int]


def _whole_sources(
    source: HandoffEnvelope, active: HandoffPipeline
) -> list[SourceUnit]:
    """Send each original message once, without a per-line catalog expansion."""
    units = []
    groups: tuple[Sequence[Message | Artifact], ...] = (
        source.messages,
        source.artifacts,
    )
    for items in groups:
        for index, item in enumerate(items):
            text = (
                item.content
                if isinstance(item.content, str)
                else json.dumps(item.content, ensure_ascii=False, separators=(",", ":"))
            )
            if not text.strip():
                continue
            artifact = isinstance(item, Artifact)
            units.append(
                SourceUnit(
                    source_id=f"{'a' if artifact else 'm'}{index}",
                    source_type="artifact" if artifact else "message",
                    source_index=index,
                    role="artifact" if isinstance(item, Artifact) else item.role,
                    name=item.name if isinstance(item, Artifact) else None,
                    hint="artifacts" if isinstance(item, Artifact) else item.kind,
                    tags=sorted(item.tags) if isinstance(item, Message) else [],
                    metadata={
                        k: v for k, v in item.metadata.items() if k not in _RESERVED
                    },
                    content=item.content,
                    estimated_tokens=active.token_counter.count_text(text),
                )
            )
    return units


def _packet(
    source: HandoffEnvelope, contract: ReceiverContract, items: list[Message | Artifact]
) -> HandoffPacket:
    data: dict[str, Any] = {section: [] for section in SECTION_NAMES}
    for item in items:
        data["artifacts" if isinstance(item, Artifact) else item.kind].append(item)
    return HandoffPacket(
        sender=source.sender, receiver=source.receiver, goal=contract.goal, **data
    )


def _brief_items(
    plan: HybridPlan, sources: dict[str, SourceUnit], contract: ReceiverContract
) -> list[Message]:
    permitted = set((*contract.required, *contract.preferred))
    covered: set[int] = set()
    items = []
    for index, statement in enumerate(plan.brief):
        if statement.section == "artifacts" or statement.section not in permitted:
            raise ContractError("Brief statement uses an unrequested message section")
        if not statement.content.strip() or not statement.source_ids:
            raise ContractError("Brief statements require text and original references")
        if len(set(statement.source_ids)) != len(statement.source_ids):
            raise ContractError("Brief statement repeats source references")
        if any(source_id not in sources for source_id in statement.source_ids):
            raise ContractError("Brief statement cites an unknown source")
        if len(set(statement.need_indices)) != len(statement.need_indices) or any(
            need < 0 or need >= len(contract.needs) for need in statement.need_indices
        ):
            raise ContractError("Brief statement has invalid need indices")
        covered.update(statement.need_indices)
        prefix = {
            "observed": "",
            "proposed": "[Proposed] ",
            "uncertain": "[Unverified] ",
        }[statement.status]
        items.append(
            Message(
                role="assistant",
                kind=statement.section,
                content=prefix + statement.content,
                metadata={
                    BRIEF_SOURCES: statement.source_ids,
                    BRIEF_STATUS: statement.status,
                    ITEM_ID: f"b{index}",
                },
            )
        )
    if plan.missing_needs or covered != set(range(len(contract.needs))):
        raise ContractError("Hybrid brief has missing receiver needs")
    if not items:
        raise ContractError("Hybrid composer returned no receiver brief")
    return items


def _excerpt_item(
    excerpt: SourceExcerpt,
    index: int,
    sources: dict[str, SourceUnit],
    source: HandoffEnvelope,
    contract: ReceiverContract,
) -> Message | Artifact:
    if excerpt.source_id not in sources:
        raise ContractError("Excerpt cites an unknown source")
    if excerpt.section not in (*contract.required, *contract.preferred):
        raise ContractError("Excerpt uses an unrequested section")
    unit = sources[excerpt.source_id]
    artifact = unit.source_type == "artifact"
    if artifact != (excerpt.section == "artifacts"):
        raise ContractError("Artifacts cannot be synthesized or reclassified")
    content = unit.content
    if (excerpt.start_line is None) != (excerpt.end_line is None):
        raise ContractError("Excerpt line bounds must both be supplied or null")
    if excerpt.start_line is not None and excerpt.end_line is not None:
        if artifact or not isinstance(content, str):
            raise ContractError("Structured values and artifacts must remain atomic")
        lines = content.splitlines(keepends=True)
        if not 1 <= excerpt.start_line <= excerpt.end_line <= len(lines):
            raise ContractError("Excerpt line range is outside the original source")
        content = "".join(lines[excerpt.start_line - 1 : excerpt.end_line])
        if not content.strip():
            raise ContractError("Excerpt selects only blank source lines")
    metadata: dict[str, Any] = {EXCERPT_SOURCE: excerpt.source_id, ITEM_ID: f"e{index}"}
    if excerpt.start_line is not None:
        metadata[EXCERPT_LINES] = [excerpt.start_line, excerpt.end_line]
    if artifact:
        # Retain artifact identity and caller metadata, stripping forged hybrid markers.
        original = source.artifacts[unit.source_index]
        original_metadata = {
            k: v for k, v in original.metadata.items() if k not in _RESERVED
        }
        return original.model_copy(
            deep=True, update={"metadata": {**original_metadata, **metadata}}
        )
    original_message = source.messages[unit.source_index]
    original_metadata = {
        k: v for k, v in original_message.metadata.items() if k not in _RESERVED
    }
    return Message(
        role=unit.role,
        kind=excerpt.section,
        content=content,
        tags=set(original_message.tags),
        metadata={**original_metadata, **metadata},
    )


async def compile_hybrid_handoff(
    envelope: HandoffEnvelope,
    contract: ReceiverContract,
    *,
    composer: HandoffComposer,
    pipeline: HandoffPipeline | None = None,
    request_id: str | None = None,
) -> HybridHandoffCompilation:
    """Compose once, protect the brief, and fit explicitly optional excerpts.

    Every brief statement stays mandatory. Citing a source does not require
    copying that whole source into the packet. Essential excerpts and required
    sections remain protected; overflow never causes hidden rewriting/retries.
    """
    source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
    if not (contract.required or contract.preferred):
        raise ContractError("Hybrid handoff needs requested packet sections")
    if not any(s != "artifacts" for s in (*contract.required, *contract.preferred)):
        raise ContractError(
            "Hybrid handoff needs a requested message section for its brief"
        )
    active = pipeline or HandoffPipeline()
    fixed = active.token_counter.count_text(
        _packet(source, contract, []).to_receiver_text()
    )
    if fixed > contract.max_tokens:
        raise BudgetExceededError(
            "Goal and empty hybrid packet exceed the contract budget"
        )
    catalog = _whole_sources(source, active)
    if not catalog:
        raise ContractError("Sender state contains no nonblank sources")
    response = await composer.compose(
        SelectionRequest(
            receiver=source.receiver,
            contract=contract.model_copy(deep=True),
            units=[unit.model_copy(deep=True) for unit in catalog],
            fixed_packet_tokens=fixed,
            source_budget_tokens=contract.max_tokens - fixed,
        )
    )
    plan = response.plan
    sources = {unit.source_id: unit for unit in catalog}
    mandatory: list[Message | Artifact] = list(_brief_items(plan, sources, contract))
    optional: list[tuple[int, Message | Artifact]] = []
    seen: dict[str, list[tuple[int, int]]] = {}
    for index, excerpt in enumerate(plan.excerpts):
        item = _excerpt_item(excerpt, index, sources, source, contract)
        unit = sources[excerpt.source_id]
        extent = len(unit.content.splitlines()) if isinstance(unit.content, str) else 1
        bounds = (excerpt.start_line or 1, excerpt.end_line or extent)
        if any(
            bounds[0] <= end and start <= bounds[1]
            for start, end in seen.get(excerpt.source_id, [])
        ):
            raise ContractError("Hybrid plan repeats or overlaps original excerpts")
        seen.setdefault(excerpt.source_id, []).append(bounds)
        if excerpt.essential or excerpt.section in contract.required:
            mandatory.append(item)
        else:
            optional.append((index, item))
    packet = _packet(source, contract, mandatory)
    if any(not getattr(packet, section) for section in contract.required):
        raise ContractError("Hybrid plan omits required packet sections")
    if active.token_counter.count_text(packet.to_receiver_text()) > contract.max_tokens:
        raise BudgetExceededError(
            "Hybrid brief and essential evidence exceed the budget"
        )
    selected = list(mandatory)
    omitted = []
    for index, item in optional:
        candidate = _packet(source, contract, [*selected, item])
        if (
            active.token_counter.count_text(candidate.to_receiver_text())
            <= contract.max_tokens
        ):
            selected.append(item)
        else:
            omitted.append(index)
    packet = _packet(source, contract, selected)
    required = tuple(section for section in SECTION_NAMES if getattr(packet, section))
    result = compile_handoff(
        packet.to_envelope(),
        contract.model_copy(
            update={"required": required, "preferred": (), "needs": ()}
        ),
        pipeline=active,
        request_id=request_id,
    )
    retained: list[Message | Artifact] = [
        *result.packet.to_envelope().messages,
        *result.packet.artifacts,
    ]
    if {item.metadata.get(ITEM_ID) for item in retained} != {
        item.metadata[ITEM_ID] for item in selected
    }:
        raise ContractError("Cleanup removed hybrid brief or evidence references")
    result.report.add_event(
        "hybrid_composer",
        "composed",
        count=len(plan.brief),
        details={
            "model_calls": response.usage.model_calls,
            "semantic_claims_verified": False,
        },
    )
    return HybridHandoffCompilation(
        **{
            **result.model_dump(mode="python"),
            "source_tokens": active.token_counter.count_envelope(source),
            "omitted_count": len(omitted),
        },
        plan=plan,
        composer_usage=response.usage,
        budget_omitted_excerpt_indices=omitted,
    )
