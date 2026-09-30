"""Safe YAML configuration loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from handoff_sieve.exceptions import ConfigurationError
from handoff_sieve.pipeline import PolicyRule
from handoff_sieve.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    PreservePolicy,
    RedactPolicy,
    SchemaPolicy,
    SelectPolicy,
)
from handoff_sieve.policies.base import Policy


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    policies: tuple[Policy, ...]
    rules: tuple[PolicyRule, ...]
    on_unmatched: Literal["error", "warn", "pass"]
    on_multiple_match: Literal["error", "first", "all"]


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"{location} must be a mapping")
    return dict(value)


def _check_unknown(config: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise ConfigurationError(f"Unknown keys in {location}: {', '.join(unknown)}")


def _build_policy(spec: Any, location: str) -> Policy:
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ConfigurationError(f"{location} must contain exactly one policy name")
    name, raw_config = next(iter(spec.items()))

    if name == "deduplicate":
        if raw_config not in (None, "exact", {}):
            raise ConfigurationError(f"{location}.deduplicate only supports 'exact'")
        return ExactDedupPolicy()

    config = _mapping(raw_config, f"{location}.{name}")
    if name == "redact":
        _check_unknown(
            config,
            {
                "detect",
                "detectors",
                "custom_patterns",
                "stage",
                "max_pattern_bytes",
                "max_scan_bytes",
                "max_scan_strings",
                "timeout_ms",
            },
            location,
        )
        detectors = config.get("detect", config.get("detectors", ["api_key", "email"]))
        return RedactPolicy(
            detectors=detectors,
            custom_patterns=config.get("custom_patterns"),
            stage=config.get("stage", "input"),
            max_pattern_bytes=config.get("max_pattern_bytes", 1_000),
            max_scan_bytes=config.get("max_scan_bytes", 1_000_000),
            max_scan_strings=config.get("max_scan_strings", 10_000),
            timeout_ms=config.get("timeout_ms", 50),
        )
    if name == "select":
        _check_unknown(config, {"roles", "kinds", "tags"}, location)
        return SelectPolicy(**config)
    if name == "preserve":
        _check_unknown(config, {"tags", "fields"}, location)
        return PreservePolicy(**config)
    if name == "budget":
        _check_unknown(config, {"max_tokens", "strategy", "overflow"}, location)
        if "max_tokens" not in config:
            raise ConfigurationError(f"{location}.budget requires max_tokens")
        strategy = config.get("strategy", config.get("overflow", "drop_oldest"))
        if strategy == "summarize":
            raise ConfigurationError(
                "YAML summarize requires a model backend and is intentionally not "
                "loaded implicitly; construct SummarizePolicy in Python instead"
            )
        return BudgetPolicy(config["max_tokens"], strategy=strategy)
    if name == "schema":
        _check_unknown(config, {"required_fields", "kinds", "normalize"}, location)
        if "required_fields" not in config:
            raise ConfigurationError(f"{location}.schema requires required_fields")
        return SchemaPolicy(**config)

    raise ConfigurationError(f"Unknown policy {name!r} in {location}")


def _build_policies(raw: Any, location: str) -> tuple[Policy, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigurationError(f"{location} must be a list")
    return tuple(
        _build_policy(item, f"{location}[{index}]") for index, item in enumerate(raw)
    )


def load_config(path: str | Path) -> LoadedConfig:
    """Load built-in policies from YAML without importing user code."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not load {config_path}: {exc}") from exc
    root = _mapping(raw, "root")
    _check_unknown(
        root,
        {"version", "policies", "rules", "on_unmatched", "on_multiple_match"},
        "root",
    )
    if root.get("version", 1) != 1:
        raise ConfigurationError("Only configuration version 1 is supported")

    on_unmatched = root.get("on_unmatched", "error")
    if on_unmatched not in {"error", "warn", "pass"}:
        raise ConfigurationError("on_unmatched must be 'error', 'warn', or 'pass'")
    on_multiple_match = root.get("on_multiple_match", "error")
    if on_multiple_match not in {"error", "first", "all"}:
        raise ConfigurationError("on_multiple_match must be 'error', 'first', or 'all'")

    global_policies = _build_policies(root.get("policies"), "policies")
    raw_rules = root.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ConfigurationError("rules must be a list")

    rules: list[PolicyRule] = []
    rule_ids: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        location = f"rules[{index}]"
        rule = _mapping(raw_rule, location)
        _check_unknown(rule, {"id", "from", "to", "policies"}, location)
        if "policies" not in rule:
            raise ConfigurationError(f"{location} requires policies")
        rule_id = rule.get("id", f"rule-{index + 1}")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ConfigurationError(f"{location}.id must be a non-empty string")
        if rule_id in rule_ids:
            raise ConfigurationError(f"Duplicate rule id {rule_id!r}")
        rule_ids.add(rule_id)
        rules.append(
            PolicyRule(
                sender=str(rule.get("from", "*")),
                receiver=str(rule.get("to", "*")),
                policies=_build_policies(rule["policies"], f"{location}.policies"),
                rule_id=rule_id,
            )
        )

    return LoadedConfig(
        policies=global_policies,
        rules=tuple(rules),
        on_unmatched=cast(Literal["error", "warn", "pass"], on_unmatched),
        on_multiple_match=cast(Literal["error", "first", "all"], on_multiple_match),
    )
