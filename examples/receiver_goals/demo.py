"""Real-model takeover from one mixed sender state, for two different receivers.

Run after installing handoff-sieve[openai]. No fixture model or offline receiver
is used. Calls and selector preparation costs are recorded for every condition.
Only synthetic task state is sent; credentials are never saved in the output.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI

from handoff_sieve import (
    ApproxTokenCounter,
    Artifact,
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_history,
    compile_model_handoff,
)
from handoff_sieve.adapters import OpenAIHandoffSelector

CONDITIONS = ("full_history", "rule_handoff", "receiver_aware_summary", "model_handoff")
COUNTER = ApproxTokenCounter()
REVIEW_INSTRUCTIONS = (
    "Review the CURRENT original session.py artifact; do not fix it. "
    "Under the latest accepted policy in the supplied state, does the CURRENT "
    "implementation correctly reject negative ages, reject an age exactly at "
    "the expiry limit, and reject already used tokens? Return only JSON with "
    "three boolean fields: rejects_negative_age, rejects_expiry_boundary, "
    "rejects_used_token. If information is missing, do not guess."
)
CODER_INSTRUCTIONS = (
    "Implement can_renew(*, age: int, used: bool) -> bool from the latest "
    "accepted policy in the supplied state. Fix the current implementation. "
    "Do not reuse superseded policy. Return only JSON with one field source, "
    "containing a complete Python module. Only one function and an optional "
    "module docstring are allowed: no imports, decorators, calls, attributes, "
    "top-level execution, external information, or sample tests. If accepted "
    "behavior is missing, do not invent thresholds."
)


def sender_state() -> HandoffEnvelope:
    noise = [
        Message(
            kind="evidence",
            content=(
                f"Hosting investigation {index}: compare launch channels, banner "
                "colors, newsletter copy and analytics vendors. These observations "
                "are unrelated to session expiry, source behavior and review."
            ),
        )
        for index in range(70)
    ]
    return HandoffEnvelope(
        sender="researcher",
        receiver="coder",
        messages=[
            Message(
                kind="constraints",
                content=(
                    "Preserve can_renew(*, age: int, used: bool) -> bool. "
                    "Both parameters remain keyword-only; callers pass integer ages."
                ),
            ),
            *noise,
            Message(
                role="assistant",
                content=(
                    "Earlier we considered allowing renewal through age 30.\n"
                    "That proposal is superseded; it must not be implemented.\n"
                    "We accepted a shorter expiry: renewal is allowed only when "
                    "0 <= age < 17 and the token has not already been used.\n"
                    "Using an inclusive upper bound failed: a token aged exactly "
                    "17 was incorrectly renewed. Do not repeat that approach.\n"
                    "The current session.py module exists, but fixing its boundary "
                    "checks and retaining the keyword-only API is still pending.\n"
                    "The launch announcement has already been drafted and is unrelated."
                ),
            ),
            Message(
                role="assistant",
                kind="tool_results",
                content=(
                    "Current session.py verification:\n"
                    "age=-1, used=False: observed True; expected False; FAILED.\n"
                    "age=17, used=False: observed True; expected False; FAILED.\n"
                    "age=4, used=True: observed False; expected False; PASSED."
                ),
            ),
        ],
        artifacts=[
            Artifact(
                name="session.py",
                content=(
                    "def can_renew(*, age: int, used: bool) -> bool:\n"
                    "    return not used and age <= 17\n"
                ),
            )
        ],
    )


def receiver_contract(receiver: str) -> ReceiverContract:
    needs = (
        (
            "Latest accepted renewal policy, including both age boundaries and reuse",
            "Failed boundary approach and remaining implementation work",
            "Current source module and its public API",
        )
        if receiver == "coder"
        else (
            "Latest accepted renewal policy against which to review",
            "Current original implementation being reviewed",
            "Actual failure and passing observations from the current test run",
        )
    )
    return ReceiverContract(
        goal=(
            "Fix session.py renewal behavior"
            if receiver == "coder"
            else "Review session.py boundary and reuse correctness"
        ),
        required=("constraints", "artifacts"),
        preferred=(
            "decisions",
            "failed_attempts",
            "pending_work",
            "evidence",
            "tool_results",
        ),
        needs=needs,
        max_tokens=1300,
    )


def _coder_validation_script(source: str) -> str:
    # Only a small pure function can enter this isolated child process.
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "can_renew":
        raise ValueError("Unexpected module API")
    if functions[0].decorator_list:
        raise ValueError("Decorators are not permitted")
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            raise ValueError("Top-level execution is not permitted")
    forbidden = (
        ast.Call,
        ast.Attribute,
        ast.Import,
        ast.ImportFrom,
        ast.ClassDef,
        ast.Lambda,
        ast.Global,
        ast.Nonlocal,
        ast.With,
        ast.AsyncFunctionDef,
    )
    if any(isinstance(node, forbidden) for node in ast.walk(tree)):
        raise ValueError("Source is not a pure takeover function")
    return (
        "import inspect, json\n"
        "namespace = {'__builtins__': {'int': int, 'bool': bool}}\n"
        f"exec(compile({source!r}, 'candidate.py', 'exec'), namespace)\n"
        "fn = namespace['can_renew']\n"
        "signature = inspect.signature(fn)\n"
        "api = tuple(signature.parameters) == ('age', 'used') and "
        "all(p.kind is inspect.Parameter.KEYWORD_ONLY "
        "for p in signature.parameters.values())\n"
        "cases = [(-1,False,False),(0,False,True),(16,False,True),"
        "(17,False,False),(100,False,False),(4,True,False)]\n"
        "checks = [api] + [fn(age=age,used=used) is expected "
        "for age,used,expected in cases]\n"
        "print(json.dumps({'passed':all(checks),'checks':checks}))\n"
    )


def grade(receiver: str, output: str, directory: Path) -> dict:
    try:
        value = json.loads(output)
        if receiver == "reviewer":
            expected = {
                "rejects_negative_age": False,
                "rejects_expiry_boundary": False,
                "rejects_used_token": True,
            }
            passed = (
                isinstance(value, dict)
                and value == expected
                and all(type(item) is bool for item in value.values())
            )
            return {"passed": passed, "actual": value, "checks": 3}
        if not isinstance(value, dict) or set(value) != {"source"}:
            raise ValueError("Unexpected output structure")
        script = _coder_validation_script(value["source"])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "session.py").write_text(value["source"], encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=directory,
        )
        if result.returncode:
            return {"passed": False, "error": "candidate_execution_failed"}
        return json.loads(result.stdout)
    except (ValueError, TypeError, KeyError, SyntaxError, subprocess.TimeoutExpired):
        return {"passed": False, "error": "invalid_receiver_output"}


class RecordingResponses:
    def __init__(self, client: AsyncOpenAI, directory: Path):
        self.client = client
        self.directory = directory
        self.records: list[dict] = []

    async def create(self, **kwargs):
        number = len(self.records) + 1
        row = {"call": number, "request": kwargs, "started": time.time()}
        self.records.append(row)
        started = time.perf_counter()
        try:
            response = await self.client.responses.create(**kwargs)
            row.update(status="completed", response=response.model_dump(mode="json"))
            return response
        except Exception as error:
            row.update(
                status="error",
                error_type=type(error).__name__,
                status_code=getattr(error, "status_code", None),
            )
            raise
        finally:
            row["seconds"] = round(time.perf_counter() - started, 3)
            (self.directory / f"call-{number:02d}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "event": "model_call",
                        "call": number,
                        "status": row["status"],
                        "seconds": row["seconds"],
                    }
                ),
                flush=True,
            )


async def run(args) -> dict:
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("API credential: ")
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    async with AsyncOpenAI(
        api_key=key, base_url=args.base_url, timeout=180, max_retries=0
    ) as client:
        key = None
        responses = RecordingResponses(client, args.output)
        selector_client = type("SelectorClient", (), {"responses": responses})()
        selector = OpenAIHandoffSelector(selector_client, model=args.model)
        source = sender_state()
        original = source.model_dump(mode="json")
        for receiver in ("coder", "reviewer"):
            state = source.model_copy(deep=True, update={"receiver": receiver})
            contract = receiver_contract(receiver)
            full = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
            for condition in CONDITIONS:
                start_call = len(responses.records)
                row = {
                    "receiver": receiver,
                    "condition": condition,
                    "contract": contract.model_dump(mode="json"),
                }
                try:
                    if condition == "full_history":
                        context = full
                    elif condition == "rule_handoff":
                        result = compile_history(
                            state, contract.model_copy(update={"needs": ()})
                        )
                        context = result.packet.to_receiver_text()
                    elif condition == "receiver_aware_summary":
                        summary = await responses.create(
                            model=args.model,
                            store=False,
                            max_output_tokens=2048,
                            instructions=(
                                "Prepare a receiver-specific task handoff, "
                                "not a final answer. Preserve latest accepted "
                                "constraints, decisions, failed attempts, pending "
                                "work, original artifacts and necessary test "
                                "evidence. Omit superseded and irrelevant state. "
                                "Cover the supplied receiver needs. Do not solve "
                                "the task or repair original code. Stay below "
                                "the supplied max_tokens. Return only the "
                                "handoff text."
                            ),
                            input=json.dumps(
                                {
                                    "contract": contract.model_dump(mode="json"),
                                    "sender_state": original,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        context = summary.output_text
                        if COUNTER.count_text(context) > contract.max_tokens:
                            raise ValueError(
                                "Summary exceeded the common context budget"
                            )
                    else:
                        result = await compile_model_handoff(
                            state, contract, selector=selector
                        )
                        context = result.packet.to_receiver_text()
                        row["compilation"] = result.model_dump(mode="json")
                    row.update(
                        handoff_tokens=COUNTER.count_text(context),
                        context=context,
                        context_sha256=hashlib.sha256(context.encode()).hexdigest(),
                    )
                    response = await responses.create(
                        model=args.model,
                        store=False,
                        max_output_tokens=2048,
                        instructions=CODER_INSTRUCTIONS
                        if receiver == "coder"
                        else REVIEW_INSTRUCTIONS,
                        input=json.dumps(
                            {"goal": contract.goal, "handoff": context},
                            ensure_ascii=False,
                        ),
                    )
                    row["output"] = response.output_text
                    row["acceptance"] = grade(
                        receiver,
                        response.output_text,
                        args.output / f"{receiver}-{condition}",
                    )
                except Exception as error:
                    row["acceptance"] = {
                        "passed": False,
                        "error_type": type(error).__name__,
                    }
                    # Error messages may contain provider data; keep only their type.
                calls = responses.records[start_call:]
                usages = [
                    x["response"].get("usage")
                    for x in calls
                    if x.get("response", {}).get("usage")
                ]
                row.update(
                    model_calls=len(calls),
                    available_usage_count=len(usages),
                    available_provider_tokens=sum(x["total_tokens"] for x in usages),
                )
                records.append(row)
                (args.output / "results.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    json.dumps(
                        {
                            "event": "takeover",
                            "receiver": receiver,
                            "condition": condition,
                            "passed": row["acceptance"]["passed"],
                            "tokens": row.get("handoff_tokens"),
                        }
                    ),
                    flush=True,
                )
        assert source.model_dump(mode="json") == original
        model_rows = [row for row in records if row["condition"] == "model_handoff"]
        selected_sets = [
            set(
                row.get("compilation", {})
                .get("selection", {})
                .get("selected_source_ids", [])
            )
            for row in model_rows
        ]
        views_differ = len(selected_sets) == 2 and selected_sets[0] != selected_sets[1]
        report = {
            "model": args.model,
            "synthetic": True,
            "trials": 1,
            "automatic_retries": 0,
            "source_unchanged": True,
            "receiver_views_differ": views_differ,
            "records": records,
            "actual_calls": len(responses.records),
            "limitations": (
                "Small synthetic mechanism demo, not a real-user success estimate; "
                "compatible gateway model alias is not verified upstream."
            ),
        }
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    model_rows = [
        row for row in report["records"] if row["condition"] == "model_handoff"
    ]
    return (
        0
        if len(model_rows) == 2
        and all(row["acceptance"]["passed"] for row in model_rows)
        and report["receiver_views_differ"]
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
