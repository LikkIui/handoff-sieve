"""Validate takeover task metadata without running a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.takeover.schema import TakeoverManifest, TakeoverTask

DEFAULT_MANIFEST = Path(__file__).with_name("manifest.json")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def validate_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Validate the pilot manifest and every fixture marked ready.

    Planned slots may point at files that do not exist yet. A ready slot must
    resolve inside the manifest directory and contain a matching task.
    """

    manifest = TakeoverManifest.model_validate(_load_json(path))
    validated_tasks = 0
    planned_tasks = 0

    for slot in manifest.tasks:
        task_path = path.parent / PureTaskPath(slot.task_file).as_path()
        if slot.fixture_status == "planned":
            planned_tasks += 1
            if not task_path.exists():
                continue
        elif not task_path.is_file():
            raise ValueError(f"ready task file is missing: {task_path}")

        task = TakeoverTask.model_validate(_load_json(task_path))
        if task.id != slot.id or task.route != slot.route:
            raise ValueError(
                f"task {task_path} does not match manifest slot {slot.id}/{slot.route}"
            )
        validated_tasks += 1

    return {
        "status": "not_run",
        "manifest": str(path),
        "slots": len(manifest.tasks),
        "validated_tasks": validated_tasks,
        "planned_tasks": planned_tasks,
    }


class PureTaskPath:
    """Convert a schema-validated POSIX task path on any host platform."""

    def __init__(self, value: str) -> None:
        self.parts = tuple(value.split("/"))

    def as_path(self) -> Path:
        return Path(*self.parts)


def main() -> None:
    """Command-line entry point; validation is the only supported action."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        required=True,
        help="validate the manifest and ready task files without model calls",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="manifest to validate",
    )
    arguments = parser.parse_args()
    if arguments.validate:
        print(
            json.dumps(
                validate_manifest(arguments.manifest),
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
