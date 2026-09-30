"""Objective acceptance checks for the generated refresh action module."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("takeover_session_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(workspace: Path) -> dict[str, Any]:
    """Run fixed API and behavior checks against the generated module."""

    module = _load_module(workspace / "solution" / "session_policy.py")
    decide: Callable[..., str] = module.decide_refresh_action
    failures: list[str] = []

    signature = inspect.signature(decide)
    expected_names = ["hash_matches", "token_revoked", "token_expired"]
    parameters = list(signature.parameters.values())
    if [parameter.name for parameter in parameters] != expected_names or any(
        parameter.kind is not inspect.Parameter.KEYWORD_ONLY for parameter in parameters
    ):
        failures.append("public keyword-only API")

    cases = [
        (
            "invalid hash takes precedence",
            dict(hash_matches=False, token_revoked=True, token_expired=True),
            "reject_invalid",
        ),
        (
            "revoked token revokes family",
            dict(hash_matches=True, token_revoked=True, token_expired=False),
            "revoke_family",
        ),
        (
            "expired active token is rejected",
            dict(hash_matches=True, token_revoked=False, token_expired=True),
            "reject_expired",
        ),
        (
            "valid active token rotates",
            dict(hash_matches=True, token_revoked=False, token_expired=False),
            "rotate",
        ),
    ]
    for label, arguments, expected in cases:
        if decide(**arguments) != expected:
            failures.append(label)

    total = 1 + len(cases)
    return {
        "status": "passed" if not failures else "failed",
        "passed": total - len(failures),
        "total": total,
        "failures": failures,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: acceptance.py WORKSPACE")
    result = evaluate(Path(sys.argv[1]).resolve())
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
