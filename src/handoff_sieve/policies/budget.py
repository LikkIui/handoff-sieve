"""Hard token-budget policy."""

from __future__ import annotations

from typing import Literal

from handoff_sieve.exceptions import BudgetExceededError
from handoff_sieve.models import HandoffEnvelope
from handoff_sieve.policies.base import Policy, PolicyContext


class BudgetPolicy(Policy):
    """Fit a handoff into a budget without deleting protected messages."""

    name = "budget"

    def __init__(
        self,
        max_tokens: int,
        *,
        strategy: Literal["drop_oldest", "drop_largest", "error"] = "drop_oldest",
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        if strategy not in {"drop_oldest", "drop_largest", "error"}:
            raise ValueError(
                "strategy must be 'drop_oldest', 'drop_largest', or 'error'"
            )
        self.max_tokens = max_tokens
        self.strategy = strategy

    def apply(
        self,
        envelope: HandoffEnvelope,
        context: PolicyContext,
    ) -> HandoffEnvelope:
        output = envelope.model_copy(deep=True)
        current_tokens = context.token_counter.count_envelope(output)
        if current_tokens <= self.max_tokens:
            context.report.add_event(
                self.name,
                "within_budget",
                details={"max_tokens": self.max_tokens},
            )
            return output

        if self.strategy == "error":
            raise BudgetExceededError(
                f"Handoff uses {current_tokens} estimated tokens, exceeding "
                f"the configured budget of {self.max_tokens}."
            )

        candidate_indices = [
            index
            for index, message in enumerate(output.messages)
            if not message.protected
        ]
        if self.strategy == "drop_largest":
            candidate_indices.sort(
                key=lambda index: context.token_counter.count_message(
                    output.messages[index]
                ),
                reverse=True,
            )

        removed_indices: set[int] = set()
        for index in candidate_indices:
            removed_indices.add(index)
            candidate = output.model_copy(deep=True)
            candidate.messages = [
                message
                for item_index, message in enumerate(output.messages)
                if item_index not in removed_indices
            ]
            if context.token_counter.count_envelope(candidate) <= self.max_tokens:
                output = candidate
                break
        else:
            output.messages = [
                message
                for index, message in enumerate(output.messages)
                if index not in removed_indices
            ]

        final_tokens = context.token_counter.count_envelope(output)
        if final_tokens > self.max_tokens:
            raise BudgetExceededError(
                "Protected messages and artifacts require "
                f"{final_tokens} estimated tokens, exceeding the configured "
                f"budget of {self.max_tokens}. Nothing protected was removed."
            )

        removed = len(removed_indices)
        context.report.removed_messages += removed
        context.report.add_event(
            self.name,
            "trimmed",
            count=removed,
            details={
                "max_tokens": self.max_tokens,
                "strategy": self.strategy,
            },
        )
        return output
