from __future__ import annotations

import json

import pytest

from handoff_sieve import (
    ApproxTokenCounter,
    Artifact,
    BudgetExceededError,
    HandoffEnvelope,
    HandoffPacket,
    Message,
    ReceiverContract,
    compile_handoff,
)
from handoff_sieve.compiler import SECTION_NAMES


def test_compact_packet_omits_item_defaults_and_keeps_all_sections() -> None:
    packet = HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Implement authentication",
        constraints=[Message(content="Keep compatibility", kind="constraints")],
        pending_work=[Message(content="Implement middleware", kind="pending_work")],
        artifacts=[Artifact(name="auth.py", content="pass")],
    )

    payload = json.loads(packet.to_receiver_text())

    assert set(payload) == {"sender", "receiver", "goal", *SECTION_NAMES}
    assert payload["constraints"] == [
        {"content": "Keep compatibility", "kind": "constraints"}
    ]
    assert payload["artifacts"] == [{"name": "auth.py", "content": "pass"}]
    assert payload["evidence"] == []
    assert HandoffPacket.model_validate_json(packet.to_receiver_text()) == packet


def test_compact_packet_preserves_nondefault_fields_and_nested_payloads() -> None:
    packet = HandoffPacket(
        sender="coder",
        receiver="reviewer",
        goal="Review the implementation",
        tool_results=[
            Message(
                role="tool",
                kind="tool_results",
                content={"exit_code": 0, "tags": [], "metadata": {}, "output": None},
                tags={"zeta", "alpha"},
                metadata={"attempt": 0, "accepted": False},
            )
        ],
        artifacts=[
            Artifact(
                name="changes.json",
                content=[{"path": "src/auth.py", "changed": True}],
                media_type="application/json",
                metadata={"revision": "new"},
            )
        ],
    )
    packet.tool_results[0]._mark_protected()
    packet.tool_results[0]._replace_internal({"private_origin": "must not appear"})

    receiver_text = packet.to_receiver_text()
    restored = HandoffPacket.model_validate_json(receiver_text)
    payload = json.loads(receiver_text)

    assert restored.model_dump() == packet.model_dump()
    assert payload["tool_results"][0]["tags"] == ["alpha", "zeta"]
    assert payload["tool_results"][0]["role"] == "tool"
    assert payload["artifacts"][0]["media_type"] == "application/json"
    assert "private_origin" not in receiver_text
    assert "_protected" not in receiver_text
    assert not restored.tool_results[0].protected
    assert not restored.tool_results[0].internal


@pytest.mark.parametrize("content", ["", {}, []])
def test_compact_packet_retains_empty_required_content(
    content: str | dict | list,
) -> None:
    packet = HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Continue",
        decisions=[Message(content=content)],
        artifacts=[Artifact(name="empty", content=content)],
    )

    payload = json.loads(packet.to_receiver_text())

    assert payload["decisions"] == [{"content": content}]
    assert payload["artifacts"] == [{"name": "empty", "content": content}]
    assert HandoffPacket.model_validate_json(packet.to_receiver_text()) == packet


def test_compact_packet_is_deterministic_for_tags_and_object_key_order() -> None:
    first = HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Continue",
        decisions=[Message(content={"z": 1, "a": 2}, tags={"zeta", "alpha"})],
    )
    second = first.model_copy(deep=True)
    second.decisions[0].content = {"a": 2, "z": 1}
    second.decisions[0].tags = {"alpha", "zeta"}

    assert first.to_receiver_text() == second.to_receiver_text()


def test_hard_budget_uses_the_compact_receiver_view() -> None:
    counter = ApproxTokenCounter()
    packet = HandoffPacket(
        sender="researcher",
        receiver="coder",
        goal="Implement authentication",
        decisions=[Message(content="Use signed sessions", kind="decisions")],
        artifacts=[Artifact(name="auth.py", content="pass")],
    )
    budget = counter.count_text(packet.to_receiver_text())
    verbose_size = counter.count_text(
        json.dumps(
            packet.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    source = HandoffEnvelope(
        sender=packet.sender,
        receiver=packet.receiver,
        messages=packet.decisions,
        artifacts=packet.artifacts,
    )
    contract = ReceiverContract(
        goal=packet.goal,
        required=("decisions", "artifacts"),
        max_tokens=budget,
    )

    result = compile_handoff(source, contract)

    assert verbose_size > budget
    assert result.packet.to_receiver_text() == packet.to_receiver_text()
    assert result.packet_tokens == budget
    assert result.budget is not None
    assert result.budget.required_tokens == budget
    assert result.budget.remaining_tokens == 0
    with pytest.raises(BudgetExceededError) as captured:
        compile_handoff(
            source,
            contract.model_copy(update={"max_tokens": budget - 1}),
        )
    assert captured.value.budget is not None
    assert captured.value.budget.required_tokens == budget
    assert captured.value.budget.overflow_tokens == 1
