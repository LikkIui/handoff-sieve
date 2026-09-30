"""A tiny deterministic receiver for the researcher-to-coder example.

This program intentionally uses only Python's standard library. Its two data
inputs are the canonical HandoffPacket JSON file and an empty output workspace.
It is a fixture for an end-to-end boundary check, not a general coding agent.
"""

from __future__ import annotations

import json
import keyword
import sys
from pathlib import Path
from typing import Any


class ReceiverInputError(ValueError):
    """Raised when the packet does not contain a safe runnable task spec."""


def _require_identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.isidentifier()
        or keyword.iskeyword(value)
    ):
        raise ReceiverInputError(f"{field} must be a Python identifier")
    return value


def _task_spec(packet: dict[str, Any]) -> dict[str, Any]:
    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReceiverInputError("packet.artifacts must be a list")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("name") == "refresh-action-spec"
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("content"), dict):
        raise ReceiverInputError("packet needs one refresh-action-spec artifact")
    task_spec = matches[0]["content"]
    if task_spec.get("task_type") != "python_decision_table":
        raise ReceiverInputError("unsupported task_type")
    return task_spec


def _safe_target(workspace: Path, value: Any) -> Path:
    if not isinstance(value, str):
        raise ReceiverInputError("target must be a relative Python path")
    relative = Path(value)
    if relative.is_absolute() or relative.suffix != ".py" or ".." in relative.parts:
        raise ReceiverInputError("target must be a relative Python path")
    workspace_root = workspace.resolve()
    target = (workspace_root / relative).resolve()
    if not target.is_relative_to(workspace_root):
        raise ReceiverInputError("target escapes the receiver workspace")
    return target


def _render_module(task_spec: dict[str, Any]) -> str:
    function_name = _require_identifier(task_spec.get("function"), "function")
    raw_arguments = task_spec.get("keyword_args")
    if not isinstance(raw_arguments, list) or not raw_arguments:
        raise ReceiverInputError("keyword_args must be a non-empty list")
    arguments = [
        _require_identifier(argument, f"keyword_args[{index}]")
        for index, argument in enumerate(raw_arguments)
    ]
    if len(arguments) != len(set(arguments)):
        raise ReceiverInputError("keyword_args must be unique")

    raw_rules = task_spec.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ReceiverInputError("rules must be a non-empty list")

    lines = [
        '"""Generated from the receiver-specific HandoffPacket."""',
        "",
        "from __future__ import annotations",
        "",
        "",
        f"def {function_name}(",
        "    *,",
    ]
    lines.extend(f"    {argument}: bool," for argument in arguments)
    lines.extend(
        [
            ") -> str:",
            '    """Return the action for one refresh-token attempt."""',
        ]
    )

    for index, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            raise ReceiverInputError(f"rules[{index}] must be an object")
        condition = rule.get("when")
        result = rule.get("return")
        if not isinstance(condition, dict) or len(condition) != 1:
            raise ReceiverInputError(f"rules[{index}].when needs one condition")
        argument, expected = next(iter(condition.items()))
        if argument not in arguments or not isinstance(expected, bool):
            raise ReceiverInputError(f"rules[{index}] has an invalid condition")
        if not isinstance(result, str):
            raise ReceiverInputError(f"rules[{index}].return must be a string")
        lines.append(f"    if {argument} is {expected}:")
        lines.append(f"        return {result!r}")

    default = task_spec.get("default")
    if not isinstance(default, str):
        raise ReceiverInputError("default must be a string")
    lines.append(f"    return {default!r}")
    lines.append("")
    return "\n".join(lines)


def generate(packet_path: Path, workspace: Path) -> Path:
    """Generate the requested module using only the serialized packet."""

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise ReceiverInputError("packet must be a JSON object")
    task_spec = _task_spec(packet)
    target = _safe_target(workspace, task_spec.get("target"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_module(task_spec), encoding="utf-8")
    return target


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: offline_receiver.py PACKET_JSON WORKSPACE")
    workspace = Path(sys.argv[2]).resolve()
    target = generate(Path(sys.argv[1]), workspace)
    print(json.dumps({"generated": target.relative_to(workspace).as_posix()}))


if __name__ == "__main__":
    main()
