from __future__ import annotations

from pathlib import Path

import pytest

from relayguard import HandoffPipeline, Message
from relayguard.exceptions import ConfigurationError


def write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_yaml_rules_apply_only_to_matching_handoff(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "handoffs.yaml",
        """
version: 1
rules:
  - from: researcher
    to: "writer*"
    policies:
      - preserve:
          tags: [constraint]
      - redact:
          detect: [email]
      - deduplicate: exact
      - budget:
          max_tokens: 40
          strategy: drop_oldest
""",
    )
    pipeline = HandoffPipeline.from_yaml(config)

    matched = pipeline.process(
        sender="researcher",
        receiver="writer-1",
        messages=[
            "alice@example.com",
            "alice@example.com",
            Message(content="required", tags={"constraint"}),
        ],
    )
    unmatched = pipeline.process(
        sender="reviewer",
        receiver="writer-1",
        messages=["alice@example.com", "alice@example.com"],
    )

    assert [message.content for message in matched.messages] == [
        "[REDACTED:email]",
        "required",
    ]
    assert len(unmatched.messages) == 2
    assert unmatched.messages[0].content == "alice@example.com"


def test_yaml_rejects_unknown_policy(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "bad.yaml",
        """
policies:
  - execute_python:
      module: unsafe
""",
    )

    with pytest.raises(ConfigurationError, match="Unknown policy"):
        HandoffPipeline.from_yaml(config)


def test_yaml_does_not_implicitly_load_summarizer(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "summary.yaml",
        """
policies:
  - budget:
      max_tokens: 100
      overflow: summarize
""",
    )

    with pytest.raises(ConfigurationError, match="construct SummarizePolicy"):
        HandoffPipeline.from_yaml(config)
