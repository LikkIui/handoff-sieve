"""Import one pinned official snapshot; sample without looking at outcomes."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

DATASET = "SWE-bench/SWE-bench_Verified"
REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
PARQUET = "data/test-00000-of-00001.parquet"
SHA256 = "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"
HARNESS_REVISION = "02e7a74ffd0b707aab73d203fe87bdc7c76afc8e"
SEED = "handoffsieve-public-swe-2026-10-11-v1"
ROOT = Path(__file__).resolve().parent
PUBLIC_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement")


def rank(instance_id: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{instance_id}".encode()).hexdigest()


def sample(rows: list[dict[str, Any]], count: int, seed: str) -> list[str]:
    """One per available repo, then largest-remainder repo/difficulty quotas."""
    if count < 0 or count > len(rows):
        raise ValueError("Sample size exceeds available distinct tasks")
    if len({row["instance_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate original task IDs")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["repo"]].append(row)
    selected: list[str] = []
    for repo in sorted(groups, key=lambda key: rank(key, seed)):
        if len(selected) == count:
            break
        selected.append(
            min(groups[repo], key=lambda row: rank(row["instance_id"], seed))[
                "instance_id"
            ]
        )
    chosen = set(selected)
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["instance_id"] not in chosen:
            strata[(row["repo"], row["difficulty"])].append(row)
    remaining = count - len(selected)
    total = sum(map(len, strata.values()))
    if remaining:
        quotas = {key: remaining * len(value) // total for key, value in strata.items()}
        order = sorted(
            strata,
            key=lambda key: (-(remaining * len(strata[key]) % total), key),
        )
        for key in order[: remaining - sum(quotas.values())]:
            quotas[key] += 1
        for key in sorted(strata):
            ordered = sorted(
                strata[key], key=lambda row: rank(row["instance_id"], seed)
            )
            selected.extend(row["instance_id"] for row in ordered[: quotas[key]])
    return selected


def split_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    if len(rows) != 500:
        raise ValueError("Pinned snapshot must contain exactly 500 tasks")
    test = sample(rows, 200, SEED + ":test")
    remaining = [row for row in rows if row["instance_id"] not in set(test)]
    dev = sample(remaining, 30, SEED + ":dev")
    reserve = sorted(
        {row["instance_id"] for row in rows} - set(test) - set(dev),
        key=lambda task: rank(task, SEED + ":reserve"),
    )
    return {"development": dev, "test": test, "reserve": reserve}


def download_snapshot(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "verified.parquet"
    if not path.exists():
        url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{PARQUET}"
        with urllib.request.urlopen(url, timeout=120) as reply:
            data = reply.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError("Official snapshot checksum differs")
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Cached snapshot checksum differs")
    return path


def load_snapshot(cache: Path) -> list[dict[str, Any]]:
    parquet = importlib.import_module("pyarrow.parquet")
    return cast(
        list[dict[str, Any]], parquet.read_table(download_snapshot(cache)).to_pylist()
    )


def public_task(row: dict[str, Any]) -> dict[str, str]:
    """The only task fields allowed into an agent request."""
    return {field: row[field] for field in PUBLIC_FIELDS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("work/swebench-source"))
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    rows = load_snapshot(args.cache)
    splits = split_rows(rows)
    by_id = {row["instance_id"]: row for row in rows}
    manifest = {
        "dataset": DATASET,
        "revision": REVISION,
        "parquet_sha256": SHA256,
        "harness_revision": HARNESS_REVISION,
        "seed": SEED,
        "method": "test first; one per repo then largest remainder by repo/difficulty",
        "custom_split": True,
        "splits": splits,
        "distribution": {
            name: {
                "repo": dict(sorted(Counter(by_id[i]["repo"] for i in ids).items())),
                "difficulty": dict(
                    sorted(Counter(by_id[i]["difficulty"] for i in ids).items())
                ),
            }
            for name, ids in splits.items()
        },
        "pilot_ids": splits["development"][:10],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "manifest.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError("Refusing to change an existing frozen manifest")
    path.write_text(text, encoding="utf-8")
    # No reference fix, test patch, grading script or outcome is exported here.
    tasks = "".join(
        json.dumps(public_task(by_id[i]), ensure_ascii=False) + "\n"
        for i in splits["development"]
    )
    (args.output / "development.jsonl").write_text(tasks, encoding="utf-8")
    print(
        json.dumps(
            {
                "counts": {k: len(v) for k, v in splits.items()},
                "pilot_ids": manifest["pilot_ids"],
            }
        )
    )


if __name__ == "__main__":
    main()
