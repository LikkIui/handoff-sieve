"""Real OpenAI Agents SDK handoff using model-selected original source spans.

Run next to demo.py after installing handoff-sieve[openai]. A researcher routes
to a coder; the async handoff filter calls the selector; the coder receives one
packet and writes a module checked outside the SDK run. No local fixture model
is used. HTTP bodies and responses are recorded without authentication headers.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import time
from pathlib import Path

import httpx
from agents import Agent, ModelSettings, RunConfig, Runner, handoff
from agents.models.openai_provider import OpenAIProvider
from demo import CODER_INSTRUCTIONS, grade, receiver_contract, sender_state
from openai import AsyncOpenAI

from handoff_sieve import HandoffPacket
from handoff_sieve.adapters import (
    OpenAIHandoffComposer,
    OpenAIHandoffSelector,
    OpenAIHybridHandoffFilter,
    OpenAIModelHandoffFilter,
)


async def run(args) -> dict:
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("API credential: ")
    args.output.mkdir(parents=True, exist_ok=False)
    requests: list[dict] = []
    by_request: dict[int, dict] = {}

    async def record_request(request: httpx.Request) -> None:
        row = {
            "call": len(requests) + 1,
            "request": json.loads(await request.aread()),
            "started": time.time(),
        }
        requests.append(row)
        by_request[id(request)] = row

    async def record_response(response: httpx.Response) -> None:
        row = by_request[id(response.request)]
        row["status_code"] = response.status_code
        row["response"] = json.loads(await response.aread())
        row["seconds"] = round(time.time() - row["started"], 3)
        (args.output / f"call-{row['call']:02d}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "event": "sdk_request",
                    "call": row["call"],
                    "status_code": response.status_code,
                }
            ),
            flush=True,
        )

    source = sender_state()
    original = source.model_dump(mode="json")
    compilations = []
    async with (
        httpx.AsyncClient(
            timeout=180,
            event_hooks={"request": [record_request], "response": [record_response]},
        ) as transport,
        AsyncOpenAI(
            api_key=key,
            base_url=args.base_url,
            max_retries=0,
            timeout=180,
            http_client=transport,
        ) as client,
    ):
        key = None
        coder = Agent(name="coder", instructions=CODER_INSTRUCTIONS)
        packet_filter = (
            OpenAIHybridHandoffFilter(
                receiver_contract("coder"),
                composer=OpenAIHandoffComposer(client, model=args.model),
                sender="researcher",
                receiver="coder",
                artifacts=source.artifacts,
                on_compile=compilations.append,
            )
            if args.mode == "hybrid"
            else OpenAIModelHandoffFilter(
                receiver_contract("coder"),
                selector=OpenAIHandoffSelector(client, model=args.model),
                sender="researcher",
                receiver="coder",
                artifacts=source.artifacts,
                on_compile=compilations.append,
            )
        )
        transfer = handoff(
            coder,
            input_filter=packet_filter,
        )
        researcher = Agent(
            name="researcher",
            instructions=(
                "Immediately call the handoff tool to coder. Do not "
                "implement, summarize, rewrite or answer the task."
            ),
            handoffs=[transfer],
        )
        inputs = [
            {"role": item.role, "content": item.content} for item in source.messages
        ]
        inputs.append({"role": "user", "content": "Transfer this task to coder now."})
        result = await Runner.run(
            researcher,
            input=inputs,
            max_turns=3,
            run_config=RunConfig(
                model=args.model,
                model_provider=OpenAIProvider(openai_client=client, use_responses=True),
                model_settings=ModelSettings(max_tokens=2048, store=False),
                tracing_disabled=True,
                trace_include_sensitive_data=False,
            ),
        )
    source_unchanged = source.model_dump(mode="json") == original
    assert source_unchanged
    assert len(compilations) == 1, "The real researcher must hand off exactly once"
    packet = compilations[0].packet
    # Inspect the actual final HTTP body, rather than an SDK-side mock input.
    receiver_request = requests[-1]["request"]
    receiver_inputs = receiver_request["input"]
    assert len(receiver_inputs) == 1, "Receiver history must contain only the packet"
    content = receiver_inputs[0]["content"]
    if isinstance(content, list):
        assert len(content) == 1 and content[0]["type"] == "input_text"
        content = content[0]["text"]
    assert HandoffPacket.model_validate_json(content) == packet
    assert not receiver_request.get("previous_response_id")
    assert not receiver_request.get("conversation")
    acceptance = grade("coder", result.final_output, args.output / "coder")
    report = {
        "synthetic": True,
        "handoff_mode": args.mode,
        "model": args.model,
        "actual_calls": len(requests),
        "source_unchanged": source_unchanged,
        "packet_only_http_boundary": True,
        "last_agent": result.last_agent.name,
        "acceptance": acceptance,
        "compilation": compilations[0].model_dump(mode="json"),
        "available_provider_tokens": sum(
            row["response"].get("usage", {}).get("total_tokens", 0) for row in requests
        ),
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "sdk_takeover",
                "calls": len(requests),
                "passed": acceptance["passed"],
                "packet_only": True,
            }
        ),
        flush=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--mode", choices=("extractive", "hybrid"), default="extractive"
    )
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
