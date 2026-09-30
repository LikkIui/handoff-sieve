"""Low-cost normalization for ordinary agent histories.

The strict :func:`handoff_sieve.compile_handoff` API expects messages to be
classified already.  This module provides the ergonomic path: it recognizes a
small set of explicit, inspectable signals and then delegates to the same
contract compiler.  It never calls a model or performs fuzzy semantic
matching.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from handoff_sieve.compiler import (
    MESSAGE_SECTION_NAMES,
    HandoffCompilation,
    ReceiverContract,
    SectionName,
    compile_handoff,
)
from handoff_sieve.exceptions import ContractError
from handoff_sieve.models import HandoffEnvelope, Message
from handoff_sieve.pipeline import HandoffPipeline


class NormalizationReport(BaseModel):
    """Content-free explanation of how a history was classified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_messages: int = Field(ge=0)
    classified_messages: int = Field(ge=0)
    normalized_messages: int = Field(ge=0)
    unclassified_messages: int = Field(ge=0)
    rule_counts: dict[str, int] = Field(default_factory=dict)


class NormalizedHistory(BaseModel):
    """A copied envelope plus its deterministic classification report."""

    model_config = ConfigDict(extra="forbid")

    envelope: HandoffEnvelope
    report: NormalizationReport


class HistoryCompilation(HandoffCompilation):
    """A handoff compilation with the preceding normalization report."""

    normalization: NormalizationReport


class HistoryNormalizer(Protocol):
    """Protocol for applications that want to supply their own classifier."""

    def normalize(self, envelope: HandoffEnvelope) -> NormalizedHistory:
        """Return a classified copy without mutating ``envelope``."""


_SECTION_ALIASES: dict[str, SectionName] = {
    "constraint": "constraints",
    "constraints": "constraints",
    "requirement": "constraints",
    "requirements": "constraints",
    "decision": "decisions",
    "decisions": "decisions",
    "accepted_decision": "decisions",
    "evidence": "evidence",
    "source": "evidence",
    "finding": "evidence",
    "findings": "evidence",
    "completed": "completed_work",
    "completed_work": "completed_work",
    "done": "completed_work",
    "failed_attempt": "failed_attempts",
    "failed_attempts": "failed_attempts",
    "rejected_approach": "failed_attempts",
    "pending": "pending_work",
    "pending_work": "pending_work",
    "todo": "pending_work",
    "next": "pending_work",
    "unresolved": "pending_work",
    "tool_result": "tool_results",
    "tool_results": "tool_results",
    "tool_output": "tool_results",
    "test_result": "tool_results",
}

_TEXT_LABELS: dict[str, SectionName] = {
    "constraint": "constraints",
    "constraints": "constraints",
    "requirement": "constraints",
    "must": "constraints",
    "约束": "constraints",
    "要求": "constraints",
    "必须": "constraints",
    "decision": "decisions",
    "decided": "decisions",
    "accepted decision": "decisions",
    "决定": "decisions",
    "已决定": "decisions",
    "采用": "decisions",
    "evidence": "evidence",
    "source": "evidence",
    "finding": "evidence",
    "证据": "evidence",
    "依据": "evidence",
    "发现": "evidence",
    "completed": "completed_work",
    "completed work": "completed_work",
    "done": "completed_work",
    "implemented": "completed_work",
    "已完成": "completed_work",
    "完成": "completed_work",
    "failed attempt": "failed_attempts",
    "tried and failed": "failed_attempts",
    "rejected approach": "failed_attempts",
    "失败尝试": "failed_attempts",
    "已否决": "failed_attempts",
    "pending": "pending_work",
    "pending work": "pending_work",
    "todo": "pending_work",
    "next": "pending_work",
    "unresolved": "pending_work",
    "待办": "pending_work",
    "下一步": "pending_work",
    "未解决": "pending_work",
    "tool result": "tool_results",
    "command result": "tool_results",
    "test result": "tool_results",
    "工具结果": "tool_results",
    "命令结果": "tool_results",
    "测试结果": "tool_results",
}

_TEXT_PREFIX = re.compile(
    r"^\s*(?:[-*]\s+)?(?P<label>"
    + "|".join(
        re.escape(label) for label in sorted(_TEXT_LABELS, key=len, reverse=True)
    )
    + r")\s*[:：]\s*(?P<body>\S(?:.|\n)*)$",
    flags=re.IGNORECASE,
)

_TOOL_KINDS = frozenset({"tool", "tool_result", "tool_results", "tool_output"})
_METADATA_KEYS = ("handoff_section", "receiver_section")


class RuleBasedHistoryNormalizer:
    """Classify common agent history shapes with transparent fixed rules.

    Signals are intentionally narrow: an existing section kind/tag, a
    dedicated metadata hint, a tool role/kind, one recognized structured key,
    or a heading at the start of text.  Unrecognized conversation remains
    unclassified and therefore does not enter the receiver packet.
    """

    def normalize(self, envelope: HandoffEnvelope) -> NormalizedHistory:
        source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
        normalized_messages: list[Message] = []
        rule_counts: Counter[str] = Counter()
        classified = 0
        normalized = 0

        for item_number, message in enumerate(source.messages):
            section, rule, cleaned_content = self._classify(
                message,
                item_number=item_number,
            )
            copied = Message.model_validate(message.model_dump(mode="python"))
            if section is not None:
                classified += 1
                rule_counts[rule] += 1
                if rule != "explicit_kind_or_tag":
                    normalized += 1
                    copied.kind = section
                    if cleaned_content is not None:
                        copied.content = cleaned_content
            normalized_messages.append(copied)

        output = source.model_copy(deep=True)
        output.messages = normalized_messages
        report = NormalizationReport(
            total_messages=len(source.messages),
            classified_messages=classified,
            normalized_messages=normalized,
            unclassified_messages=len(source.messages) - classified,
            rule_counts=dict(sorted(rule_counts.items())),
        )
        return NormalizedHistory(envelope=output, report=report)

    def _classify(
        self,
        message: Message,
        *,
        item_number: int,
    ) -> tuple[SectionName | None, str, str | None]:
        explicit = _explicit_sections(message)
        if len(explicit) > 1:
            raise ContractError(
                f"Message {item_number} maps to multiple receiver sections: "
                + ", ".join(sorted(explicit))
                + ". Use exactly one section kind or tag."
            )
        if explicit:
            return next(iter(explicit)), "explicit_kind_or_tag", None

        signals: list[tuple[SectionName, str]] = []
        for key in _METADATA_KEYS:
            if key not in message.metadata:
                continue
            section = _section_from_hint(message.metadata[key])
            if section is not None:
                signals.append((section, "metadata_hint"))

        if message.role.casefold() == "tool" or message.kind.casefold() in _TOOL_KINDS:
            signals.append(("tool_results", "tool_role_or_kind"))

        structured = _section_from_structured_content(message.content)
        if structured is not None:
            signals.append((structured, "structured_key"))

        text_section, cleaned_content = _section_from_text(message.content)
        if text_section is not None:
            signals.append((text_section, "text_prefix"))

        sections = {section for section, _ in signals}
        if len(sections) > 1:
            details = ", ".join(f"{rule}={section}" for section, rule in signals)
            raise ContractError(
                f"Message {item_number} has conflicting normalization signals: "
                f"{details}. Add one explicit section kind or tag."
            )
        if not signals:
            return None, "unclassified", None

        section = signals[0][0]
        rule = "+".join(sorted({rule for _, rule in signals}))
        return section, rule, cleaned_content


def compile_history(
    envelope: HandoffEnvelope,
    contract: ReceiverContract,
    *,
    normalizer: HistoryNormalizer | None = None,
    pipeline: HandoffPipeline | None = None,
    request_id: str | None = None,
) -> HistoryCompilation:
    """Normalize ordinary history and compile a minimal receiver packet.

    The default normalizer is deterministic and local.  Applications with
    domain-specific state can pass another ``HistoryNormalizer`` while keeping
    the same contract, budget, packet, and cleanup pipeline.
    """

    source = HandoffEnvelope.model_validate(envelope.model_dump(mode="python"))
    active_pipeline = pipeline or HandoffPipeline()
    normalized = (normalizer or RuleBasedHistoryNormalizer()).normalize(source)
    compilation = compile_handoff(
        normalized.envelope,
        contract,
        pipeline=active_pipeline,
        request_id=request_id,
    )
    compilation.report.add_event(
        "history_normalizer",
        "classified",
        count=normalized.report.normalized_messages,
        details={
            "classified_messages": normalized.report.classified_messages,
            "unclassified_messages": normalized.report.unclassified_messages,
            "rule_counts": normalized.report.rule_counts,
        },
    )
    compilation_data = compilation.model_dump(mode="python")
    compilation_data["source_tokens"] = active_pipeline.token_counter.count_envelope(
        source
    )
    return HistoryCompilation(
        **compilation_data,
        normalization=normalized.report,
    )


def _explicit_sections(message: Message) -> set[SectionName]:
    matches: set[SectionName] = {
        section for section in MESSAGE_SECTION_NAMES if section in message.tags
    }
    for section in MESSAGE_SECTION_NAMES:
        if message.kind == section:
            matches.add(section)
    return matches


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _section_from_hint(value: Any) -> SectionName | None:
    if not isinstance(value, str):
        return None
    normalized = _normalize_key(value)
    if normalized == "artifacts":
        raise ContractError(
            "Message metadata cannot classify content as artifacts. Put files "
            "and outputs in HandoffEnvelope.artifacts instead."
        )
    return _SECTION_ALIASES.get(normalized)


def _section_from_structured_content(
    content: str | dict[str, Any] | list[Any],
) -> SectionName | None:
    if not isinstance(content, dict):
        return None
    matches = {
        section
        for key in content
        if (section := _SECTION_ALIASES.get(_normalize_key(key))) is not None
    }
    if len(matches) == 1:
        return next(iter(matches))
    return None


def _section_from_text(
    content: str | dict[str, Any] | list[Any],
) -> tuple[SectionName | None, str | None]:
    if not isinstance(content, str):
        return None, None
    match = _TEXT_PREFIX.match(content)
    if match is None:
        return None, None
    label = match.group("label").casefold()
    return _TEXT_LABELS[label], match.group("body").strip()
