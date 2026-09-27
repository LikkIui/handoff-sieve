"""Safe YAML configuration loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from relayguard.exceptions import ConfigurationError
from relayguard.pipeline import PolicyRule
from relayguard.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    PreservePolicy,
    RedactPolicy,
    SchemaPolicy,
    SelectPolicy,
)
from relayguard.policies.base import Policy


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    policies: tuple[Policy, ...]
    rules: tuple[PolicyRule, ...]


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
        raise ConfigurationError(
            f"{location} must contain exactly one policy name"
        )
    name, raw_config = next(iter(spec.items()))

    if name == "deduplicate":
        if raw_config not in (None, "exact", {}):
            raise ConfigurationError(f"{location}.deduplicate only supports 'exact'")
        return ExactDedupPolicy()

    config = _mapping(raw_config, f"{location}.{name}")
    if name == "redact":
        _check_unknown(config, {"detect", "detectors", "custom_patterns"}, location)
        detectors = config.get("detect", config.get("detectors", ["api_key", "email"]))
        return RedactPolicy(
            detectors=detectors,
            custom_patterns=config.get("custom_patterns"),
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
        _build_policy(item, f"{location}[{index}]")
        for index, item in enumerate(raw)
    )


def load_config(path: str | Path) -> LoadedConfig:
    """Load built-in policies from YAML without importing user code."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not load {config_path}: {exc}") from exc
    root = _mapping(raw, "root")
    _check_unknown(root, {"version", "policies", "rules"}, "root")
    if root.get("version", 1) != 1:
        raise ConfigurationError("Only configuration version 1 is supported")

    global_policies = _build_policies(root.get("policies"), "policies")
    raw_rules = root.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ConfigurationError("rules must be a list")

    rules: list[PolicyRule] = []
    for index, raw_rule in enumerate(raw_rules):
        location = f"rules[{index}]"
        rule = _mapping(raw_rule, location)
        _check_unknown(rule, {"from", "to", "policies"}, location)
        if "policies" not in rule:
            raise ConfigurationError(f"{location} requires policies")
        rules.append(
            PolicyRule(
                sender=str(rule.get("from", "*")),
                receiver=str(rule.get("to", "*")),
                policies=_build_policies(rule["policies"], f"{location}.policies"),
            )
        )

    return LoadedConfig(policies=global_policies, rules=tuple(rules))
