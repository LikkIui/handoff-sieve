"""Pluggable summarization policy."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import Protocol

from relayguard.exceptions import RelayGuardError
from relayguard.models import HandoffEnvelope, Message
from relayguard.policies.base import Policy, PolicyContext
from relayguard.tokens import TokenCounter


@dataclass(frozen=True, slots=True)
class Summary:
    """Summarizer output and its provider-reported or estimated usage."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Summarizer(Protocol):
    """Provider-neutral interface implemented by summary backends."""

    def summarize(
        self,
        messages: Sequence[Message],
        *,
        max_tokens: int,
        token_counter: TokenCounter,
    ) -> Summary: ...


class MockSummarizer:
    """Offline summarizer for tests and examples.

    If ``text`` is omitted, it creates a deterministic extractive preview. It
    deliberately makes no claim about semantic summary quality.
    """

    def __init__(self, text: str | None = None) -> None:
        self.text = text

    def summarize(
        self,
        messages: Sequence[Message],
        *,
        max_tokens: int,
        token_counter: TokenCounter,
    ) -> Summary:
        input_tokens = sum(token_counter.count_message(item) for item in messages)
        if self.text is not None:
            output = self.text
        else:
            serialized = []
            for message in messages:
                if isinstance(message.content, str):
                    serialized.append(message.content)
                else:
                    serialized.append(
                        json.dumps(message.content, ensure_ascii=False, sort_keys=True)
                    )
            output = "[offline extract] " + "\n".join(serialized)

        while output and token_counter.count_text(output) > max_tokens:
            shrink_by = max(1, len(output) // 10)
            output = output[:-shrink_by]
        return Summary(
            text=output,
            input_tokens=input_tokens,
            output_tokens=token_counter.count_text(output),
        )


class SummarizePolicy(Policy):
    """Replace unprotected messages with one summary message."""

    name = "summarize"

    def __init__(self, summarizer: Summarizer, *, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        self.summarizer = summarizer
        self.max_tokens = max_tokens

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        candidates = [message for message in output.messages if not message.protected]
        if not candidates:
            context.report.add_event(self.name, "skipped", count=0)
            return output

        summary = self.summarizer.summarize(
            candidates,
            max_tokens=self.max_tokens,
            token_counter=context.token_counter,
        )
        if isawaitable(summary):
            close = getattr(summary, "close", None)
            if callable(close):
                close()
            raise RelayGuardError(
                "Async summarizers are not supported by the synchronous "
                "HandoffPipeline. Provide a synchronous summarizer backend."
            )
        actual_input_tokens = sum(
            context.token_counter.count_message(message) for message in candidates
        )
        actual_output_tokens = context.token_counter.count_text(summary.text)
        if actual_output_tokens > self.max_tokens:
            raise RelayGuardError(
                f"Summarizer returned {actual_output_tokens} estimated tokens, "
                f"exceeding its limit of {self.max_tokens}."
            )

        context.report.summarizer_input_tokens += (
            summary.input_tokens or actual_input_tokens
        )
        context.report.summarizer_output_tokens += (
            summary.output_tokens or actual_output_tokens
        )
        summary_message = Message(
            role="assistant",
            content=summary.text,
            kind="summary",
            tags={"summary"},
        )
        summary_message._replace_internal(candidates[0].internal)
        ordered: list[Message] = []
        summary_inserted = False
        for message in output.messages:
            if message.protected:
                ordered.append(message)
            elif not summary_inserted:
                ordered.append(summary_message)
                summary_inserted = True
        output.messages = ordered
        removed = max(0, len(candidates) - 1)
        context.report.removed_messages += removed
        context.report.add_event(
            self.name,
            "summarized",
            count=len(candidates),
            details={"max_tokens": self.max_tokens},
        )
        return output
