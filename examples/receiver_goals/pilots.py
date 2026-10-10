"""Real-model check on the repository's three executable takeover pilots.

Run from a checkout after installing .[openai]. The public tasks lose category
labels for this explicitly labeled diagnostic; content and public starter files
stay unchanged. Full history, receiver-aware summary, and model selection share
the same task instruction and host acceptance. Grading answers never enter a
model request. This is three synthetic executable tasks, not a user benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from openai import AsyncOpenAI

from evals.takeover import run_runnable_openai as pilots
from evals.takeover.payloads import canonical_sender_state, receiver_task_prefix
from examples.receiver_goals.demo import COUNTER, RecordingResponses
from handoff_sieve import compile_model_handoff
from handoff_sieve.adapters import OpenAIHandoffSelector

TASKS = ("rc01_composite_cursor", "pe01_streaming_csv", "rr01_cursor_review")
CONDITIONS = ("full_history", "receiver_aware_summary", "model_handoff")


async def run_task(client, args, task_id) -> dict:
    directory = args.output / task_id
    directory.mkdir()
    spec = pilots._SPECS[task_id]
    task = pilots._load_task(spec.task_path, task_id)
    task = pilots._build_runnable_task_view(
        spec, task, pilots._read_starter_sources(spec)
    )
    state = task.sender_state.model_copy(deep=True)
    for message in state.messages:
        message.kind = "context"
        message.tags = set()
    original = state.model_dump(mode="json")
    contract = task.contract.model_copy(
        update={
            "needs": (
                "Task-specific accepted behavior and public API constraints",
                "Current accepted decisions and their necessary evidence",
                "Failed approaches to avoid and pending implementation or review work",
                "Relevant artifact identities and current tool observations",
            )
        }
    )
    responses = RecordingResponses(client, directory)
    selector = OpenAIHandoffSelector(
        SimpleNamespace(responses=responses), model=args.model
    )
    rows = []
    for condition in args.conditions:
        start = len(responses.records)
        row = {"task": task_id, "condition": condition}
        try:
            if condition == "full_history":
                context = canonical_sender_state(state)
            elif condition == "receiver_aware_summary":
                preparation = await responses.create(
                    model=args.model,
                    store=False,
                    max_output_tokens=4096,
                    instructions=(
                        "Prepare only a receiver-specific context handoff. Cover "
                        "the supplied goal and needs, accepted constraints, decisions, "
                        "failed approaches, pending work and necessary evidence. "
                        "Preserve original artifacts and identifiers. Do not implement "
                        "or review the task, repair code, invent facts or emit the "
                        "receiver's final answer. Omit superseded and irrelevant "
                        "state. Stay below the supplied max_tokens. Return plain text."
                    ),
                    input=json.dumps(
                        {
                            "contract": contract.model_dump(mode="json"),
                            "sender_state": original,
                        },
                        ensure_ascii=False,
                    ),
                )
                context = preparation.output_text
                if COUNTER.count_text(context) > contract.max_tokens:
                    raise ValueError("Summary exceeded the common handoff budget")
            else:
                compilation = await compile_model_handoff(
                    state, contract, selector=selector
                )
                row["compilation"] = compilation.model_dump(mode="json")
                context = compilation.packet.to_receiver_text()
            prefix = receiver_task_prefix(task)
            response = await responses.create(
                model=args.model,
                store=False,
                max_output_tokens=8192,
                input=f"{prefix}\n\n<handoff_context>\n{context}\n</handoff_context>",
            )
            output = response.output_text
            if spec.kind == "single_source":
                acceptance = pilots.run_candidate_acceptance(
                    pilots.parse_candidate_source(output)
                )
            elif spec.kind == "multi_source":
                acceptance = pilots.run_pe01_acceptance(
                    pilots.parse_pe01_sources(output)
                )
            else:
                acceptance = pilots.run_rr01_acceptance(
                    pilots.parse_review_submission(output)
                )
            row.update(
                context=context,
                output=output,
                handoff_tokens=COUNTER.count_text(context),
                acceptance=asdict(acceptance),
            )
        except Exception as error:
            row["acceptance"] = {"overall": False, "error_type": type(error).__name__}
        calls = responses.records[start:]
        row["model_calls"] = len(calls)
        row["available_provider_tokens"] = sum(
            call.get("response", {}).get("usage", {}).get("total_tokens", 0)
            for call in calls
        )
        rows.append(row)
        (directory / "results.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "event": "pilot",
                    "task": task_id,
                    "condition": condition,
                    "passed": row["acceptance"]["overall"],
                }
            ),
            flush=True,
        )
    assert state.model_dump(mode="json") == original
    report = {
        "task": task_id,
        "variant": "category labels removed; content unchanged",
        "synthetic": True,
        "trials": 1,
        "source_unchanged": True,
        "records": rows,
        "actual_calls": len(responses.records),
    }
    (directory / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


async def run(args) -> dict:
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("API credential: ")
    args.output.mkdir(parents=True, exist_ok=False)
    async with AsyncOpenAI(
        api_key=key, base_url=args.base_url, timeout=180, max_retries=0
    ) as client:
        key = None
        tasks = await asyncio.gather(
            *(run_task(client, args, task_id) for task_id in args.tasks)
        )
    report = {
        "model": args.model,
        "synthetic": True,
        "automatic_retries": 0,
        "tasks": tasks,
        "actual_calls": sum(task["actual_calls"] for task in tasks),
    }
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=TASKS)
    parser.add_argument(
        "--conditions", nargs="+", choices=CONDITIONS, default=CONDITIONS
    )
    args = parser.parse_args()
    report = asyncio.run(run(args))
    rows = [
        row
        for task in report["tasks"]
        for row in task["records"]
        if row["condition"] == "model_handoff"
    ]
    return 0 if all(row["acceptance"]["overall"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
