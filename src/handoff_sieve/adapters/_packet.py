"""Recognize the fixed public receiver packet at framework boundaries."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import ValidationError

from handoff_sieve.compiler import HandoffPacket
from handoff_sieve.exceptions import HandoffIntegrityError
from handoff_sieve.models import Artifact


def packet_from_text(text: object) -> HandoffPacket | None:
    """Decode only a complete packet shape, leaving ordinary JSON as history.

    Both the original rendering and the compact rendering contain every
    top-level packet field. Nested messages use the public model's defaults.
    No private processing fields or unknown packet fields are accepted.
    """

    if not isinstance(text, str) or not text.lstrip().startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or set(payload) != set(HandoffPacket.model_fields):
        return None
    try:
        return HandoffPacket.model_validate(payload)
    except ValidationError as exc:
        raise HandoffIntegrityError(
            "Receiver packet contains invalid public state."
        ) from exc


def check_packet_receiver(packet: HandoffPacket, sender: str) -> None:
    """Ensure the current sender is the agent that received the previous view."""

    if packet.receiver != sender:
        raise HandoffIntegrityError(
            "Previous receiver packet does not belong to the current sender."
        )


def merge_artifacts(
    inherited: Sequence[Artifact], current: Sequence[Artifact]
) -> list[Artifact]:
    """Explicit current artifacts replace inherited artifacts with that name.

    Names identify application outputs at this adapter boundary. We do not
    infer which of two different current artifacts is newer. Exact duplicates
    are removed, and all returned values are independent public copies.
    """

    current_names = {artifact.name for artifact in current}
    candidates = [
        artifact for artifact in inherited if artifact.name not in current_names
    ]
    candidates.extend(current)
    result: list[Artifact] = []
    for artifact in candidates:
        if artifact not in result:
            result.append(Artifact.model_validate(artifact.model_dump(mode="python")))
    return result
