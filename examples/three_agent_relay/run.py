"""Run a real three-agent SDK relay with deterministic offline models."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from agents import Agent, RunConfig, Runner, function_tool, handoff
from agents.models.interface import Model, ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from handoff_sieve import ReceiverContract
from handoff_sieve.adapters import OpenAIReceiverContractFilter

ACCEPTANCE = Path(__file__).resolve().parents[1] / "researcher_to_coder/acceptance.py"
API = {
    "function": "decide_refresh_action",
    "keyword_args": ["hash_matches", "token_revoked", "token_expired"],
}
DECISION = {
    "ordered_rules": [
        ["not hash_matches", "reject_invalid"],
        ["token_revoked", "revoke_family"],
        ["token_expired", "reject_expired"],
    ],
    "otherwise": "rotate",
}
FAILED_ATTEMPT = "Checking expiry before reuse hid reuse of an expired revoked token."
RESEARCH_NOTE = (
    f"Decision: {json.dumps(DECISION)}\n"
    f"Failed attempt: {FAILED_ATTEMPT}\n"
    "TODO: Implement solution/session_policy.py using the stable public API."
)

# A separate process checks the generated file, independently of coder claims.
REVIEW_PROBE = """
import importlib.util
import inspect
import itertools
import json
import sys

spec = importlib.util.spec_from_file_location('session_policy', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
function = module.decide_refresh_action
parameters = inspect.signature(function).parameters
checks = [{'id': 'stable_keyword_only_api', 'passed': (
    list(parameters) == ['hash_matches', 'token_revoked', 'token_expired']
    and all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
)}]
for hash_matches, token_revoked, token_expired in itertools.product(
    (False, True), repeat=3
):
    expected = ('reject_invalid' if not hash_matches else
                'revoke_family' if token_revoked else
                'reject_expired' if token_expired else 'rotate')
    actual = function(hash_matches=hash_matches, token_revoked=token_revoked,
                      token_expired=token_expired)
    case_id = f'case_{int(hash_matches)}{int(token_revoked)}{int(token_expired)}'
    checks.append({'id': case_id, 'passed': actual == expected})
print(json.dumps({'checks': checks,
                  'passed': sum(check['passed'] for check in checks),
                  'total': len(checks)}))
"""


def output_message(text: str, identifier: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=identifier,
        content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
        role="assistant",
        status="completed",
        type="message",
    )


def local_response(output: list[Any], identifier: str) -> ModelResponse:
    return ModelResponse(output=output, usage=Usage(), response_id=identifier)


def receive_packet(model_input: list[Any]) -> dict[str, Any]:
    assert len(model_input) == 1, "Each new receiver must get one packet item."
    return json.loads(model_input[0]["content"])


def build_source(packet: dict[str, Any]) -> str:
    """Generate the function from the API and ordered rules in the first packet."""
    api = next(
        json.loads(item["content"])
        for item in packet["constraints"]
        if item["content"].startswith("{")
    )
    decision = json.loads(packet["decisions"][0]["content"])
    source = f"def {api['function']}(*, {', '.join(api['keyword_args'])}):\n"
    for condition, action in decision["ordered_rules"]:
        source += f"    if {condition}:\n        return {action!r}\n"
    return source + f"    return {decision['otherwise']!r}\n"


def review_source(source: str) -> dict[str, Any]:
    """Check packet-carried code in a fresh workspace, independently of tool claims."""
    with tempfile.TemporaryDirectory(prefix="handoff-sieve-review-") as directory:
        solution = Path(directory) / "session_policy.py"
        solution.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-I", "-c", REVIEW_PROBE, str(solution)],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    return json.loads(completed.stdout)


class OfflineModel(Model):
    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("This example runs without streaming.")
        yield  # pragma: no cover


class OfflineResearcher(OfflineModel):
    async def get_response(self, *, handoffs, **kwargs) -> ModelResponse:
        return local_response(
            [
                output_message(RESEARCH_NOTE, "research-note"),
                ResponseFunctionToolCall(
                    arguments="{}",
                    call_id="transfer-coder",
                    name=handoffs[0].tool_name,
                    type="function_call",
                ),
            ],
            "local-researcher",
        )


class OfflineCoder(OfflineModel):
    def __init__(self) -> None:
        self.turn = 0
        self.first_input: list[Any] = []
        self.acceptance: dict[str, int] = {}

    async def get_response(self, *, input, tools, handoffs, **kwargs) -> ModelResponse:
        self.turn += 1
        if self.turn == 1:
            self.first_input = deepcopy(input)
            packet = receive_packet(input)
            source = build_source(packet)
            output = [
                ResponseFunctionToolCall(
                    arguments=json.dumps({"source": source}),
                    call_id="write-check-code",
                    name=tools[0].name,
                    type="function_call",
                )
            ]
        else:
            tool_output = next(
                json.loads(item["output"])
                for item in input
                if item.get("type") == "function_call_output"
                and item.get("call_id") == "write-check-code"
            )
            self.acceptance = {
                key: tool_output["acceptance"][key] for key in ("passed", "total")
            }
            assert self.acceptance == {"passed": 5, "total": 5}
            output = [
                output_message(
                    "Completed: Wrote solution/session_policy.py; "
                    "the five existing behavior checks passed.\n"
                    "TODO: Independently review the generated source and "
                    "all refresh-action priorities.",
                    "coder-completed-note",
                ),
                ResponseFunctionToolCall(
                    arguments="{}",
                    call_id="transfer-reviewer",
                    name=handoffs[0].tool_name,
                    type="function_call",
                ),
            ]
        return local_response(output, f"local-coder-{self.turn}")


class OfflineReviewer(OfflineModel):
    def __init__(self) -> None:
        self.first_input: list[Any] = []

    async def get_response(self, *, input, **kwargs) -> ModelResponse:
        self.first_input = deepcopy(input)
        packet = receive_packet(input)
        assert packet["constraints"] and packet["completed_work"]
        assert json.loads(packet["decisions"][0]["content"]) == DECISION
        assert packet["failed_attempts"][0]["content"] == FAILED_ATTEMPT
        tool_result = next(
            item["content"]["tool_result"]
            for item in packet["tool_results"]
            if item["content"]["tool_result"]["name"]
            == "write_and_check_session_policy"
        )
        generated = json.loads(tool_result["output"])
        assert generated["source"] == json.loads(tool_result["arguments"])["source"]
        acceptance = review_source(generated["source"])
        verdict = (
            "approve"
            if acceptance["passed"] == acceptance["total"]
            else "request_changes"
        )
        return local_response(
            [output_message(json.dumps({"verdict": verdict, **acceptance}), "review")],
            "local-reviewer",
        )


async def run_workflow() -> dict[str, Any]:
    compilations = []
    coder_model = OfflineCoder()
    reviewer_model = OfflineReviewer()
    with tempfile.TemporaryDirectory(prefix="handoff-sieve-code-") as directory:
        workspace = Path(directory)

        @function_tool
        def write_and_check_session_policy(source: str) -> str:
            """Write the generated module and run the five existing behavior checks."""
            solution = workspace / "solution/session_policy.py"
            solution.parent.mkdir(exist_ok=True)
            solution.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-I", str(ACCEPTANCE), str(workspace)],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return json.dumps(
                {
                    "path": "solution/session_policy.py",
                    "source": solution.read_text(encoding="utf-8"),
                    "acceptance": json.loads(completed.stdout),
                }
            )

        reviewer = Agent(name="reviewer", model=reviewer_model)
        reviewer_filter = OpenAIReceiverContractFilter(
            ReceiverContract(
                goal="Review the generated module, including the rejected check order.",
                required=(
                    "constraints",
                    "decisions",
                    "failed_attempts",
                    "completed_work",
                    "pending_work",
                    "tool_results",
                ),
                max_tokens=1600,
            ),
            sender="coder",
            receiver="reviewer",
            on_compile=compilations.append,
        )
        coder = Agent(
            name="coder",
            model=coder_model,
            tools=[write_and_check_session_policy],
            handoffs=[handoff(reviewer, input_filter=reviewer_filter)],
        )
        coder_filter = OpenAIReceiverContractFilter(
            ReceiverContract(
                goal="Implement the refresh-action function from the accepted rules.",
                required=(
                    "constraints",
                    "decisions",
                    "failed_attempts",
                    "pending_work",
                ),
                max_tokens=900,
            ),
            sender="researcher",
            receiver="coder",
            on_compile=compilations.append,
        )
        researcher = Agent(
            name="researcher",
            model=OfflineResearcher(),
            handoffs=[handoff(coder, input_filter=coder_filter)],
        )
        result = await asyncio.wait_for(
            Runner.run(
                researcher,
                [
                    {
                        "role": "user",
                        "content": "Unrelated launch and hosting notes. " * 200,
                    },
                    {
                        "role": "user",
                        "content": "Constraint: Preserve the public keyword-only API.",
                    },
                    {"role": "user", "content": f"Constraint: {json.dumps(API)}"},
                ],
                max_turns=4,
                run_config=RunConfig(tracing_disabled=True),
            ),
            timeout=30,
        )
    assert result.last_agent is reviewer and len(compilations) == 2
    handoffs_record = []
    for compilation, model_input in zip(
        compilations, (coder_model.first_input, reviewer_model.first_input), strict=True
    ):
        assert model_input == [
            {"role": "user", "content": compilation.packet.to_receiver_text()}
        ]
        assert "hosting notes" not in compilation.packet.to_receiver_text()
        handoffs_record.append(
            {
                "sender": compilation.packet.sender,
                "receiver": compilation.packet.receiver,
                "source_estimated_tokens": compilation.source_tokens,
                "packet_estimated_tokens": compilation.packet_tokens,
                "receiver_input_items": len(model_input),
                "constraints_preserved": bool(compilation.packet.constraints),
                "decisions_preserved": bool(compilation.packet.decisions),
                "failed_attempt_preserved": bool(compilation.packet.failed_attempts),
                "completed_work_items": len(compilation.packet.completed_work),
                "completed_tool_results": len(compilation.packet.tool_results),
            }
        )
    return {
        "mode": "offline_fixture",
        "provider_calls": 0,
        "handoffs": handoffs_record,
        "coder_acceptance": coder_model.acceptance,
        "review": json.loads(result.final_output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Print the verification record."
    )
    args = parser.parse_args()
    record = asyncio.run(run_workflow())
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print("SDK relay: Researcher -> Coder -> Reviewer")
        for item in record["handoffs"]:
            print(
                f"{item['sender']} -> {item['receiver']}: "
                f"{item['source_estimated_tokens']} -> "
                f"{item['packet_estimated_tokens']} "
                "estimated tokens; receiver input items: 1"
            )
        print("Both packets preserve constraints, decisions, and the failed approach.")
        print("Second packet adds completed work and checked source as a tool result.")
        print("Coder acceptance: 5/5")
        review = record["review"]
        print(
            f"Reviewer acceptance: {review['passed']}/{review['total']}; "
            f"{review['verdict']}"
        )
        print("Provider calls: 0")
        print("Offline fixture models verify relay integration, not LLM success rates.")
    if record["review"]["verdict"] != "approve":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
