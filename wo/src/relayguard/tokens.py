"""Token counting interfaces.

The default counter intentionally reports estimates. Applications needing
provider-specific billing accuracy can inject another implementation.
"""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

from relayguard.models import HandoffEnvelope, Message


class TokenCounter(Protocol):
    """Protocol implemented by token counters."""

    @property
    def name(self) -> str: ...

    def count_text(self, text: str) -> int: ...

    def count_message(self, message: Message) -> int: ...

    def count_envelope(self, envelope: HandoffEnvelope) -> int: ...


class ApproxTokenCounter:
    """Deterministic UTF-8 approximation with a small per-message overhead."""

    @property
    def name(self) -> str:
        return "approx_utf8"

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 4))

    def _serialize(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def count_message(self, message: Message) -> int:
        content_tokens = self.count_text(self._serialize(message.content))
        metadata_tokens = self.count_text(self._serialize(message.metadata))
        tag_tokens = self.count_text(" ".join(sorted(message.tags)))
        return content_tokens + metadata_tokens + tag_tokens + 4

    def count_envelope(self, envelope: HandoffEnvelope) -> int:
        message_tokens = sum(self.count_message(item) for item in envelope.messages)
        artifact_tokens = sum(
            self.count_text(self._serialize(item.content)) + 4
            for item in envelope.artifacts
        )
        return message_tokens + artifact_tokens


class TiktokenCounter(ApproxTokenCounter):
    """Optional tiktoken-backed text counter.

    The content encoding is exact for the selected tokenizer, while the
    per-message overhead remains an estimate because providers serialize
    message metadata differently.
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        try:
            import tiktoken
        except ImportError as exc:
            raise ImportError(
                "TiktokenCounter requires `pip install relayguard[tiktoken]`"
            ) from exc
        self.model = model
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    @property
    def name(self) -> str:
        return f"tiktoken:{self.model}"

    def count_text(self, text: str) -> int:
        return len(self.encoding.encode(text)) if text else 0

