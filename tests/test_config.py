from __future__ import annotations

from pathlib import Path

import pytest

from handoff_sieve import HandoffPipeline, Message
from handoff_sieve.exceptions import (
    AmbiguousRouteError,
    ConfigurationError,
    UnmatchedRouteError,
)


def write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_yaml_rules_apply_only_to_matching_handoff(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "handoffs.yaml",
        """
version: 1
on_unmatched: pass
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
          max_tokens: 80
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


def test_yaml_rules_fail_closed_when_no_route_matches(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "handoffs.yaml",
        """
version: 1
rules:
  - from: researcher
    to: writer
    policies:
      - redact:
          detect: [email]
""",
    )

    pipeline = HandoffPipeline.from_yaml(config)

    with pytest.raises(UnmatchedRouteError, match="No policy rule matched") as captured:
        pipeline.process(
            sender="reviewer",
            receiver="writer",
            messages=["alice@example.com"],
        )

    assert captured.value.report is not None
    assert captured.value.report.status == "denied"
    assert captured.value.report.failure_code == "unmatched_route"
    assert captured.value.report.failed_policy == "config"
    assert captured.value.report.handoff_id


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


def test_overlapping_rules_fail_closed_by_default(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "overlap.yaml",
        """
version: 1
rules:
  - id: broad
    from: "*"
    to: writer
    policies:
      - redact:
          detect: [email]
  - id: exact
    from: researcher
    to: writer
    policies:
      - deduplicate: exact
""",
    )
    pipeline = HandoffPipeline.from_yaml(config)

    with pytest.raises(AmbiguousRouteError) as captured:
        pipeline.process(
            sender="researcher",
            receiver="writer",
            messages=["alice@example.com"],
        )

    assert captured.value.report is not None
    assert captured.value.report.failure_code == "ambiguous_route"
    assert captured.value.report.events[0].details["rule_ids"] == [
        "broad",
        "exact",
    ]


def test_overlapping_rules_can_apply_all_in_declaration_order(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "overlap.yaml",
        """
version: 1
on_multiple_match: all
rules:
  - id: broad
    from: "*"
    to: writer
    policies:
      - redact:
          detect: [email]
  - id: exact
    from: researcher
    to: writer
    policies:
      - deduplicate: exact
""",
    )
    pipeline = HandoffPipeline.from_yaml(config)

    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["alice@example.com", "alice@example.com"],
    )

    assert [message.content for message in result.messages] == ["[REDACTED:email]"]
    assert result.report.events[0].details == {
        "rule_ids": ["broad", "exact"],
        "multiple_match_behavior": "all",
    }


def test_yaml_rejects_unsafe_policy_order(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "unsafe-order.yaml",
        """
version: 1
policies:
  - budget:
      max_tokens: 100
  - redact:
      detect: [email]
""",
    )

    with pytest.raises(ConfigurationError, match="Unsafe policy order"):
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
