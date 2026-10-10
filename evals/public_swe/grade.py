"""Linux-only upstream grading; no model credentials are required here."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
from typing import Any

from .dataset import HARNESS_REVISION, ROOT, load_snapshot


def grade(task: dict[str, Any], output: Path, results: Path | None) -> dict[str, Any]:
    harness = importlib.import_module("swebench.harness.run_evaluation")
    utils = importlib.import_module("swebench.harness.utils")
    spec = utils.make_test_spec(task)
    client = harness._docker_client()
    task_id = task["instance_id"]
    run_id = "handoffsieve-" + output.name
    outcomes = {}
    conditions = ["gold_control", "unchanged_control"]
    if results is not None:
        conditions += ["full_history", "receiver_aware_summary", "model_handoff"]
    for condition in conditions:
        if condition == "gold_control":
            patch = task["patch"]
        elif condition == "unchanged_control":
            patch = ""
        else:
            assert results is not None
            path = results / task_id / f"{condition}.patch"
            patch = path.read_text(encoding="utf-8") if path.exists() else ""
            if not patch:
                outcomes[condition] = {
                    "resolved": False,
                    "status": "no_candidate_patch",
                }
                continue
        prediction = {
            "instance_id": task_id,
            "model_name_or_path": condition,
            "model_patch": patch,
        }
        value = harness.run_instance(
            spec,
            prediction,
            client,
            run_id,
            timeout=900,
            skip_patch=condition == "unchanged_control",
        )
        if value is None:
            outcomes[condition] = {
                "resolved": None,
                "status": "upstream_evaluation_error",
            }
        else:
            outcomes[condition] = {"status": "graded", **value[1][task_id]}
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "instance_id": task_id,
                    "harness_revision": HARNESS_REVISION,
                    "outcomes": outcomes,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    controls_valid = (
        outcomes["gold_control"].get("resolved") is True
        and outcomes["unchanged_control"].get("resolved") is False
    )
    report = {
        "instance_id": task_id,
        "harness_revision": HARNESS_REVISION,
        "controls_valid": controls_valid,
        "outcomes": outcomes,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{task_id}.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-id",
        default=os.environ.get("INSTANCE_ID"),
        required=not bool(os.environ.get("INSTANCE_ID")),
    )
    parser.add_argument("--output", type=Path, default=Path("upstream-grading"))
    parser.add_argument("--results", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("work/swebench-source"))
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    if args.instance_id not in manifest["splits"]["development"]:
        raise ValueError(
            "Controls and development grading must not expose held-out tasks"
        )
    matches = [
        row
        for row in load_snapshot(args.cache)
        if row["instance_id"] == args.instance_id
    ]
    if len(matches) != 1:
        raise ValueError("Unknown original task ID")
    report = grade(matches[0], args.output, args.results)
    print(json.dumps(report))
    if not report["controls_valid"]:
        raise SystemExit(
            "Upstream positive/negative controls failed; no valid task success claim"
        )


if __name__ == "__main__":
    main()
