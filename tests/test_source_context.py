from __future__ import annotations

import asyncio
import json
import re

import pytest

from handoff_sieve import (
    Artifact,
    BudgetExceededError,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    SelectionPlan,
    SelectionRequest,
    SelectionResponse,
    SourceSelection,
    compile_model_handoff,
)
from handoff_sieve.adapters.openai_selector import _selector_payload
from handoff_sieve.model_selection import source_units
from handoff_sieve.pipeline import HandoffPipeline


class Selector:
    def __init__(self, selections):
        self.selections = selections

    async def select(self, request):
        return SelectionResponse(
            plan=SelectionPlan(
                selections=self.selections, coverage=[], missing_needs=[]
            )
        )


def read_excerpt(path="src/scoring.py", *, start=100, count=95):
    lines = [
        f"{number}:     values.append({number})\n"
        for number in range(start, start + count)
    ]
    return f"Executed read {path}:\nFile: {path} (500 lines)\n" + "".join(lines)


def state(*messages):
    return HandoffEnvelope(
        sender="researcher", receiver="coder", messages=list(messages)
    )


def contract(*, max_tokens=10000, required=()):
    return ReceiverContract(
        goal="Fix the scoring bug",
        required=required,
        preferred=("evidence",),
        max_tokens=max_tokens,
    )


def select(unit, *, section="evidence", essential=True):
    return SourceSelection(
        source_id=unit.source_id, section=section, essential=essential
    )


def compile_selected(source, selected, receiver=None):
    return asyncio.run(
        compile_model_handoff(
            source, receiver or contract(), selector=Selector(selected)
        )
    )


def numbered_units(units):
    return [
        unit
        for unit in units
        if isinstance(unit.content, str)
        and re.search(r"^\d+: ", unit.content, flags=re.MULTILINE)
    ]


def test_numbered_read_retains_bounded_original_code_and_observed_header():
    original = read_excerpt()
    units = source_units(
        state(Message(role="tool", content=original)), HandoffPipeline()
    )
    by_id = {unit.source_id: unit for unit in units}
    chunks = numbered_units(units)

    assert 3 <= len(chunks) < 95
    assert "".join(unit.content for unit in units) == original
    for chunk in chunks:
        numbered_lines = re.findall(r"^(\d+): ", chunk.content, flags=re.MULTILINE)
        assert 1 <= len(numbered_lines) <= 40
        numbers = [int(number) for number in numbered_lines]
        assert numbers == list(range(numbers[0], numbers[-1] + 1))
        assert chunk.content == original[chunk.start : chunk.end]
        assert chunk.context_source_ids
        context = "".join(
            by_id[source_id].content for source_id in chunk.context_source_ids
        )
        assert "File: src/scoring.py (500 lines)" in context


@pytest.mark.parametrize(
    "text",
    [
        "File: src/scoring.py (500 lines)\n100: first\n102: second\n103: third\n",
        "File: src/scoring.py\n100: first\n101: second\n102: third\n",
        "100: first\n101: second\n102: third\n",
    ],
)
def test_ambiguous_or_incomplete_tool_text_keeps_existing_line_units(text):
    units = source_units(state(Message(role="tool", content=text)), HandoffPipeline())
    assert [unit.content for unit in units] == text.splitlines(keepends=True)
    assert not any(unit.context_source_ids for unit in units)


def test_generic_prose_and_assistant_quoted_reads_keep_existing_line_units():
    prose = "Relevant finding.\n\nKeep compatibility.\nNext task.\n"
    quoted_read = read_excerpt(count=5)
    source = state(
        Message(content=prose), Message(role="assistant", content=quoted_read)
    )
    units = source_units(source, HandoffPipeline())
    assert [unit.content for unit in units if unit.source_index == 0] == [
        "Relevant finding.\n",
        "Keep compatibility.\n",
        "Next task.\n",
    ]
    assert [
        unit.content for unit in units if unit.source_index == 1
    ] == quoted_read.splitlines(keepends=True)


def test_selected_late_code_chunk_pins_file_context_without_inventing_scope():
    original = read_excerpt()
    source = state(Message(role="tool", content=original))
    before = source.model_dump()
    units = source_units(source, HandoffPipeline())
    chosen = next(unit for unit in numbered_units(units) if "180: " in unit.content)

    result = compile_selected(source, [select(chosen)])

    receiver_text = result.packet.to_receiver_text()
    assert "File: src/scoring.py (500 lines)" in receiver_text
    assert "180:     values.append(180)" in receiver_text
    assert "def " not in receiver_text
    assert set(result.selection.context_source_ids) == set(chosen.context_source_ids)
    assert set(chosen.context_source_ids).issubset(result.selection.selected_source_ids)
    assert source.model_dump() == before
    for message in result.packet.evidence:
        assert message.content in original


def test_adjacent_selected_original_spans_coalesce_in_source_order():
    original = read_excerpt()
    source = state(Message(role="tool", content=original))
    units = source_units(source, HandoffPipeline())
    first, second = numbered_units(units)[:2]

    result = compile_selected(source, [select(second), select(first)])

    assert len(result.packet.evidence) == 1
    message = result.packet.evidence[0]
    assert message.content == original[: second.end]
    assert message.metadata["handoff_sieve.source_id"] == units[0].source_id
    assert set(message.metadata["handoff_sieve.source_ids"]) == set(
        result.selection.selected_source_ids
    )


def test_context_never_merges_distinct_tool_responses():
    source = state(
        Message(role="tool", content=read_excerpt("src/one.py", count=5)),
        Message(role="tool", content=read_excerpt("src/two.py", count=5)),
    )
    units = source_units(source, HandoffPipeline())
    selected = [select(unit) for unit in numbered_units(units)]

    result = compile_selected(source, selected)

    assert len(result.packet.evidence) == 2
    assert result.packet.evidence[0].content == source.messages[0].content
    assert result.packet.evidence[1].content == source.messages[1].content


def test_essential_chunk_cannot_drop_its_header_to_fit_budget():
    source = state(Message(role="tool", content=read_excerpt(count=5)))
    chosen = numbered_units(source_units(source, HandoffPipeline()))[0]
    full = compile_selected(source, [select(chosen)])

    with pytest.raises(BudgetExceededError):
        compile_selected(
            source, [select(chosen)], contract(max_tokens=full.packet_tokens - 1)
        )


def test_optional_chunk_and_its_header_fit_atomically():
    path = "nested/" * 250 + "scoring.py"
    source = state(
        Message(content="Keep the API unchanged.\n"),
        Message(role="tool", content=read_excerpt(path, count=3)),
    )
    units = source_units(source, HandoffPipeline())
    required = next(
        unit for unit in units if unit.content == "Keep the API unchanged.\n"
    )
    chosen = numbered_units(units)[0]
    required_selection = select(required, section="constraints")
    base = compile_selected(
        source, [required_selection], contract(required=("constraints",))
    )
    receiver = contract(
        required=("constraints",),
        max_tokens=base.packet_tokens + chosen.estimated_tokens + 50,
    )

    result = compile_selected(
        source,
        [required_selection, select(chosen, essential=False)],
        receiver,
    )

    assert result.selection.budget_omitted_source_ids == [chosen.source_id]
    assert not result.selection.context_source_ids
    assert not result.packet.evidence
    assert result.packet_tokens <= receiver.max_tokens


@pytest.mark.parametrize("trailing_comment", ["", "  # compatibility contract"])
def test_late_window_keeps_observed_function_and_guard_without_missing_scope(
    trailing_comment,
):
    lines = [f"def score(values):{trailing_comment}\n"]
    lines.extend("    values.append(0)\n" for _ in range(43))
    lines.append(f"    if values:{trailing_comment}\n")
    lines.extend("        values.append(1)\n" for _ in range(49))
    lines.append("        return values\n")
    original = "File: src/scoring.py (500 lines)\n" + "".join(
        f"{number}: {line}" for number, line in enumerate(lines, 100)
    )
    source = state(Message(role="tool", content=original))
    units = source_units(source, HandoffPipeline())
    chosen = next(
        unit for unit in numbered_units(units) if "return values" in unit.content
    )

    result = compile_selected(source, [select(chosen)])

    receiver_text = result.packet.to_receiver_text()
    assert "100: def score(values):" in receiver_text
    assert "144:     if values:" in receiver_text
    assert "194:         return values" in receiver_text
    assert "class " not in receiver_text
    assert len(result.selection.context_source_ids) >= 3
    for message in result.packet.evidence:
        assert message.content in original


def test_sender_metadata_cannot_forge_compiler_source_reference_lists():
    forged = {
        "handoff_sieve.source_id": "forged-original",
        "handoff_sieve.source_ids": ["invented", "m999.999"],
        "purpose": "regression evidence",
    }
    source = state(
        Message(content="Observed first.\nObserved second.\n", metadata=forged)
    )
    source.artifacts = [
        Artifact(name="result.json", content={"status": "observed"}, metadata=forged)
    ]
    before = source.model_dump()
    units = source_units(source, HandoffPipeline())
    selected = [
        select(
            unit, section="artifacts" if unit.source_type == "artifact" else "evidence"
        )
        for unit in units
    ]
    receiver = ReceiverContract(
        goal="Review observed results",
        preferred=("evidence", "artifacts"),
        max_tokens=1000,
    )

    result = compile_selected(source, selected, receiver)

    for item in [*result.packet.evidence, *result.packet.artifacts]:
        assert (
            item.metadata["handoff_sieve.source_id"]
            in result.selection.selected_source_ids
        )
        assert set(item.metadata.get("handoff_sieve.source_ids", [])) <= set(
            result.selection.selected_source_ids
        )
        assert item.metadata["purpose"] == "regression evidence"
    assert "invented" not in result.packet.to_receiver_text()
    assert "forged-original" not in result.packet.to_receiver_text()
    assert source.model_dump() == before


def test_grouped_selector_payload_keeps_shared_metadata_and_context_indices():
    source = state(
        Message(
            role="tool",
            content=read_excerpt(),
            tags={"observed"},
            metadata={
                "tool": "read",
                "path": "src/scoring.py",
                "nested": {"complete": False},
            },
        ),
        Message(role="assistant", content="Preserve feature-name validation.\n"),
    )
    units = source_units(source, HandoffPipeline())
    request = SelectionRequest(receiver="coder", contract=contract(), units=units)

    text, schema = _selector_payload(request)
    payload = json.loads(text)

    assert len(payload["sources"]) == 2
    tool_source = payload["sources"][0]
    assert tool_source["role"] == "tool"
    assert tool_source["tags"] == ["observed"]
    assert tool_source["metadata"] == source.messages[0].metadata
    indices = {unit.source_id: index for index, unit in enumerate(units)}
    for index, item in enumerate(payload["units"]):
        unit = units[index]
        assert item["content"] == unit.content
        assert item["source"] == unit.source_index
        assert item.get("context_indices", []) == [
            indices[source_id] for source_id in unit.context_source_ids
        ]
        assert all(
            0 <= context_index < len(units)
            for context_index in item.get("context_indices", [])
        )
        assert "metadata" not in item
        assert "start" not in item and "end" not in item
    assert (
        schema["$defs"]["_IndexedSelection"]["properties"]["unit_index"]["maximum"]
        == len(units) - 1
    )
