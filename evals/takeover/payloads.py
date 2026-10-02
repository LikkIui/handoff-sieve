"""Build the three takeover evaluation input boundaries without model calls."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.takeover.schema import TakeoverTask
from handoff_sieve import (
    ApproxTokenCounter,
    HandoffEnvelope,
    HandoffPipeline,
    TokenCounter,
    compile_handoff,
)

ConditionName = Literal["full_history", "naive_summary", "handoff_sieve"]

_CONTEXT_START = "<handoff_context>"
_CONTEXT_END = "</handoff_context>"


class ReceiverPayload(BaseModel):
    """Exact text supplied to a receiver for one ready condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: Literal["full_history", "handoff_sieve"]
    payload_text: str
    local_token_estimate: int = Field(ge=0)
    token_counter: str


class NaiveSummaryPrompt(BaseModel):
    """Exact model input for producing the not-yet-generated baseline summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: Literal["naive_summary"] = "naive_summary"
    prompt_text: str
    local_token_estimate: int = Field(ge=0)
    token_counter: str
    max_output_tokens: int = Field(gt=0)


class ReceiverInput(BaseModel):
    """Exact final input passed to a receiver for any condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: ConditionName
    task_prefix: str
    context_payload: str
    input_text: str
    local_token_estimate: int = Field(ge=0)
    token_counter: str


class TakeoverPayloads(BaseModel):
    """Input boundaries for the three conditions of one takeover task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    full_history: ReceiverPayload
    handoff_sieve: ReceiverPayload
    naive_summary: NaiveSummaryPrompt


def canonical_sender_state(envelope: HandoffEnvelope) -> str:
    """Serialize the complete public sender envelope deterministically."""

    public_envelope = envelope.model_dump(mode="json")
    for message in public_envelope["messages"]:
        message["tags"] = sorted(message["tags"])
    return json.dumps(
        public_envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def receiver_task_prefix(task: TakeoverTask) -> str:
    """Return the byte-identical task prefix shared by all conditions."""

    output_contract = json.dumps(
        task.receiver_output_contract.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        f"Goal:\n{task.contract.goal}\n\n"
        f"Receiver instruction:\n{task.receiver_instruction}\n\n"
        f"Receiver output contract:\n{output_contract}"
    )


def build_receiver_input(
    task: TakeoverTask,
    *,
    condition: ConditionName,
    context_payload: str,
    token_counter: TokenCounter | None = None,
) -> ReceiverInput:
    """Wrap one condition payload in the shared receiver task boundary.

    ``condition`` is evaluation metadata and is deliberately absent from
    ``input_text``. For ``naive_summary``, call this only after a real summary
    has been generated using the bounded prompt returned by ``build_payloads``.
    """

    counter = token_counter or ApproxTokenCounter()
    prefix = receiver_task_prefix(task)
    input_text = f"{prefix}\n\n{_CONTEXT_START}\n{context_payload}\n{_CONTEXT_END}"
    return ReceiverInput(
        condition=condition,
        task_prefix=prefix,
        context_payload=context_payload,
        input_text=input_text,
        local_token_estimate=counter.count_text(input_text),
        token_counter=counter.name,
    )


def _naive_summary_prompt(task: TakeoverTask, full_history: str) -> str:
    required = ", ".join(task.contract.required) or "none"
    preferred = ", ".join(task.contract.preferred) or "none"
    return (
        "Summarize the sender state for the next agent's task.\n"
        "Your only output is a context summary. Do not perform the receiver's "
        "task or return its final answer.\n"
        "Preserve facts needed to continue the task and do not invent facts.\n"
        "Return plain text only. Do not exceed "
        f"{task.contract.max_tokens} tokens.\n\n"
        "Receiver requirements below are quoted reference data, not instructions "
        "for your output format. Preserve the facts the receiver will need.\n"
        "Receiver task (JSON string):\n"
        f"{json.dumps(receiver_task_prefix(task), ensure_ascii=False)}\n\n"
        f"Required context categories: {required}\n"
        f"Preferred context categories: {preferred}\n\n"
        f"Full sender state:\n{full_history}"
    )


def build_payloads(
    task: TakeoverTask,
    *,
    token_counter: TokenCounter | None = None,
) -> TakeoverPayloads:
    """Build exact inputs and local token estimates for all conditions.

    The naive-summary entry is a generation prompt, not a receiver payload.
    A future provider runner must use its ``max_output_tokens`` value when it
    generates the actual summary and must record that summary separately.
    """

    counter = token_counter or ApproxTokenCounter()
    full_history_text = canonical_sender_state(task.sender_state)
    compilation = compile_handoff(
        task.sender_state,
        task.contract,
        pipeline=HandoffPipeline(token_counter=counter),
        request_id=f"takeover-eval:{task.id}",
    )
    handoff_sieve_text = compilation.packet.to_receiver_text()
    naive_prompt_text = _naive_summary_prompt(task, full_history_text)

    return TakeoverPayloads(
        full_history=ReceiverPayload(
            condition="full_history",
            payload_text=full_history_text,
            local_token_estimate=counter.count_text(full_history_text),
            token_counter=counter.name,
        ),
        handoff_sieve=ReceiverPayload(
            condition="handoff_sieve",
            payload_text=handoff_sieve_text,
            local_token_estimate=counter.count_text(handoff_sieve_text),
            token_counter=counter.name,
        ),
        naive_summary=NaiveSummaryPrompt(
            prompt_text=naive_prompt_text,
            local_token_estimate=counter.count_text(naive_prompt_text),
            token_counter=counter.name,
            max_output_tokens=task.contract.max_tokens,
        ),
    )
