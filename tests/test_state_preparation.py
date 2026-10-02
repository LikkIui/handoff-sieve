from __future__ import annotations

import pytest

from handoff_sieve import (
    Artifact,
    BudgetExceededError,
    ContractError,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_handoff,
    prepare_sender_state,
)


def _source(
    *messages: Message, artifacts: list[Artifact] | None = None
) -> HandoffEnvelope:
    return HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=list(messages),
        artifacts=artifacts or [],
        metadata={"note": {"value": "original"}},
    )


def test_latest_explicit_decision_wins_without_interpreting_unkeyed_conflicts() -> None:
    source = _source(
        Message(
            content="Use sessions", kind="decisions", metadata={"state_key": "auth"}
        ),
        Message(
            content="Use tokens", tags={"decisions"}, metadata={"state_key": "auth"}
        ),
        Message(content="Use SQLite", kind="decisions"),
        Message(content="Use PostgreSQL", kind="decisions"),
        Message(content="Constraint: Keep the API", metadata={"state_key": "auth"}),
        Message(content="Constraint: Change the API", metadata={"state_key": "auth"}),
    )

    prepared = prepare_sender_state(source)

    assert [message.content for message in prepared.messages] == [
        "Use tokens",
        "Use SQLite",
        "Use PostgreSQL",
        "Constraint: Keep the API",
        "Constraint: Change the API",
    ]


def test_completed_work_closes_pending_work_and_later_pending_work_reopens_it() -> None:
    todo = Message(
        content="Implement auth", kind="pending_work", metadata={"state_key": "auth"}
    )
    completed = Message(
        content="Auth implemented",
        kind="completed_work",
        metadata={"state_key": "auth"},
    )
    closed = prepare_sender_state(_source(todo, completed))
    assert [message.kind for message in closed.messages] == ["completed_work"]

    reopened = prepare_sender_state(
        _source(
            todo, completed, todo.model_copy(update={"content": "Fix auth edge case"})
        )
    )
    assert [message.content for message in reopened.messages] == [
        "Auth implemented",
        "Fix auth edge case",
    ]
    closed_again = prepare_sender_state(_source(todo, completed, todo, completed))
    assert [message.kind for message in closed_again.messages] == ["completed_work"]


def test_task_selection_retains_shared_state_and_scopes_state_keys() -> None:
    source = _source(
        Message(
            content="Shared constraint",
            kind="constraints",
            metadata={"state_key": "api"},
        ),
        Message(
            content="Task A constraint",
            kind="constraints",
            metadata={"task_id": "a", "state_key": "api"},
        ),
        Message(
            content="Task B constraint",
            kind="constraints",
            metadata={"task_id": "b", "state_key": "api"},
        ),
        Message(
            content="Task A TODO",
            kind="pending_work",
            metadata={"task_id": "a", "state_key": "work"},
        ),
        Message(
            content="Task B done",
            kind="completed_work",
            metadata={"task_id": "b", "state_key": "work"},
        ),
        artifacts=[
            Artifact(name="shared", content="public"),
            Artifact(name="task", content="a", metadata={"task_id": "a"}),
            Artifact(name="task", content="b", metadata={"task_id": "b"}),
        ],
    )

    selected = prepare_sender_state(source, task_id="a")

    assert [message.content for message in selected.messages] == [
        "Shared constraint",
        "Task A constraint",
        "Task A TODO",
    ]
    assert [artifact.content for artifact in selected.artifacts] == ["public", "a"]
    assert len(prepare_sender_state(source).messages) == 5
    assert [
        message.content
        for message in prepare_sender_state(source, task_id="A").messages
    ] == ["Shared constraint"]


def test_same_key_in_different_sections_does_not_replace_other_state() -> None:
    source = _source(
        Message(content="Decision", kind="decisions", metadata={"state_key": "api"}),
        Message(
            content="Constraint", kind="constraints", metadata={"state_key": "api"}
        ),
        Message(content="Unkeyed pending", kind="pending_work"),
        Message(content="Unkeyed completed", kind="completed_work"),
    )

    assert len(prepare_sender_state(source).messages) == 4


def test_exact_deduplication_retains_distinct_public_metadata_and_artifacts() -> None:
    message = Message(content={"z": 1, "a": 2}, tags={"evidence", "source"})
    duplicate = Message(content={"a": 2, "z": 1}, tags={"source", "evidence"})
    source = _source(
        message,
        duplicate,
        duplicate.model_copy(update={"role": "assistant"}),
        duplicate.model_copy(update={"metadata": {"source": "other"}}),
        Message(content="ordinary prose"),
        Message(content="ordinary prose"),
        artifacts=[
            Artifact(name="auth.py", content="old"),
            Artifact(name="auth.py", content="old"),
            Artifact(name="auth.py", content="new"),
        ],
    )

    prepared = prepare_sender_state(source)

    assert len(prepared.messages) == 4
    assert [artifact.content for artifact in prepared.artifacts] == ["old", "new"]
    untouched = prepare_sender_state(source, deduplicate=False)
    assert len(untouched.messages) == 6
    assert len(untouched.artifacts) == 3


def test_pre_budget_deduplication_lets_required_state_fit_without_trimming() -> None:
    decision = Message(content="Use composite cursors", kind="decisions")
    source = _source(decision, decision.model_copy(deep=True))
    contract = ReceiverContract(
        goal="Implement", required=("decisions",), max_tokens=10_000
    )
    one = compile_handoff(prepare_sender_state(source), contract)
    tight = contract.model_copy(update={"max_tokens": one.packet_tokens})

    with pytest.raises(BudgetExceededError):
        compile_handoff(source, tight)
    prepared = compile_handoff(prepare_sender_state(source), tight)

    assert prepared.packet.decisions[0].content == "Use composite cursors"
    assert len(prepared.packet.decisions) == 1
    assert prepared.packet_tokens == tight.max_tokens


def test_state_preparation_leaves_source_and_private_fields_unchanged() -> None:
    message = Message(content={"nested": ["original"]}, kind="decisions")
    message._mark_protected()
    message._replace_internal({"private": ["original"]})
    source = _source(
        message, artifacts=[Artifact(name="file", content={"nested": ["original"]})]
    )
    before = source.model_dump()

    prepared = prepare_sender_state(source)

    assert not prepared.messages[0].protected
    assert not prepared.messages[0].internal
    prepared.messages[0].content["nested"].append("changed")
    prepared.artifacts[0].content["nested"].append("changed")
    prepared.metadata["note"]["value"] = "changed"
    assert source.model_dump() == before
    assert source.messages[0].protected
    assert source.messages[0].internal == {"private": ["original"]}


@pytest.mark.parametrize("value", ["", " ", 1, False, [], None])
@pytest.mark.parametrize("field", ["task_id", "state_key"])
def test_invalid_explicit_message_metadata_fails_clearly(
    field: str, value: object
) -> None:
    source = _source(Message(content="Keep", kind="decisions", metadata={field: value}))

    with pytest.raises(ValueError, match=rf"Message 0 metadata\.{field}"):
        prepare_sender_state(source)


@pytest.mark.parametrize("value", ["", " ", 1, False, []])
def test_invalid_task_selection_fails_clearly(value: object) -> None:
    with pytest.raises(ValueError, match="task_id must be a nonblank string"):
        prepare_sender_state(_source(), task_id=value)


def test_invalid_artifact_scope_and_ambiguous_sections_fail_clearly() -> None:
    with pytest.raises(ValueError, match=r"Artifact 0 metadata\.task_id"):
        prepare_sender_state(
            _source(
                artifacts=[
                    Artifact(name="file", content="x", metadata={"task_id": None})
                ]
            )
        )
    with pytest.raises(ContractError, match="multiple receiver sections"):
        prepare_sender_state(
            _source(
                Message(content="ambiguous", kind="decisions", tags={"constraints"})
            )
        )
