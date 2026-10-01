"""A real SDK tool/handoff loop with offline fixtures or one live coder call.

The researcher is deterministic in both modes so the same runtime note and
tool result reach the handoff. The live mode evaluates one coding task; it is
not a benchmark success-rate claim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ModelRetrySettings,
    ModelSettings,
    OpenAIProvider,
    RunConfig,
    Runner,
    function_tool,
    handoff,
)
from agents.models.interface import Model, ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from handoff_sieve import ReceiverContract
from handoff_sieve.adapters import (
    OpenAIReceiverContractFilter,
    compile_openai_handoff,
)

ACCEPTANCE = Path(__file__).resolve().parents[1] / "researcher_to_coder/acceptance.py"
RUNTIME_NOTE = (
    "Decision: Reject a hash mismatch first; revoke the whole family on reuse; "
    "reject expired tokens; rotate otherwise.\n"
    "Failed attempt: Checking expiry before reuse hid reuse of an expired "
    "revoked token.\n"
    "TODO: Implement solution/session_policy.py using the inspected public API."
)
CODER_INSTRUCTIONS = (
    "Complete the supplied takeover task using its constraints, accepted decision, "
    "failed approach, and inspected API. Return one JSON object with exactly the "
    "key source containing the complete Python module. No Markdown. The module "
    "must contain only a keyword-only decide_refresh_action function and optional "
    "docstrings. Do not import modules or execute code at module scope."
)


@function_tool
def inspect_session_api() -> str:
    """Read the public function signature from the session-service task fixture."""
    return json.dumps(
        {
            "function": "decide_refresh_action",
            "keyword_args": ["hash_matches", "token_revoked", "token_expired"],
            "return_values": [
                "reject_invalid",
                "revoke_family",
                "reject_expired",
                "rotate",
            ],
            "target": "solution/session_policy.py",
        }
    )


def output_message(text: str, identifier: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=identifier,
        content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
        role="assistant",
        status="completed",
        type="message",
    )


class OfflineResearcher(Model):
    def __init__(self) -> None:
        self.turn = 0

    async def get_response(self, *, tools, handoffs, **kwargs) -> ModelResponse:
        self.turn += 1
        if self.turn == 1:
            output = [
                ResponseFunctionToolCall(
                    arguments="{}",
                    call_id="inspect-api",
                    name=tools[0].name,
                    type="function_call",
                )
            ]
        else:
            output = [
                output_message(RUNTIME_NOTE, "latest-research-note"),
                ResponseFunctionToolCall(
                    arguments="{}",
                    call_id="transfer-coder",
                    name=handoffs[0].tool_name,
                    type="function_call",
                ),
            ]
        return ModelResponse(
            output=output, usage=Usage(), response_id=f"local-{self.turn}"
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("This example runs without streaming.")
        yield  # pragma: no cover


class OfflineCoder(Model):
    async def get_response(self, *, input, **kwargs) -> ModelResponse:
        assert len(input) == 1
        packet = json.loads(input[0]["content"])
        assert "hash mismatch first" in packet["decisions"][0]["content"]
        assert "expiry before reuse" in packet["failed_attempts"][0]["content"]
        tool = packet["tool_results"][0]["content"]["tool_result"]
        api = json.loads(tool["output"])
        signature = ", ".join(api["keyword_args"])
        actions = api["return_values"]
        source = (
            f"def {api['function']}(*, {signature}):\n"
            f"    if not hash_matches:\n        return {actions[0]!r}\n"
            f"    if token_revoked:\n        return {actions[1]!r}\n"
            f"    if token_expired:\n        return {actions[2]!r}\n"
            f"    return {actions[3]!r}\n"
        )
        return ModelResponse(
            output=[
                output_message(json.dumps({"source": source}), "local-coder-output")
            ],
            usage=Usage(),
            response_id="local-coder",
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("This example runs without streaming.")
        yield  # pragma: no cover


class RecordingModel(Model):
    def __init__(self, model: Model) -> None:
        self.model = model
        self.inputs: list[Any] = []

    async def get_response(self, **kwargs) -> ModelResponse:
        self.inputs.append(deepcopy(kwargs["input"]))
        return await self.model.get_response(**kwargs)

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("This example runs without streaming.")
        yield  # pragma: no cover

    async def close(self) -> None:
        await self.model.close()


def check_solution(raw_output: str) -> dict[str, Any]:
    """Use the existing independent acceptance and check the rejected approach."""
    import ast

    payload = json.loads(raw_output)
    if not isinstance(payload, dict) or set(payload) != {"source"}:
        raise ValueError("Coder output must contain exactly one source string.")
    source = payload["source"]
    if not isinstance(source, str):
        raise ValueError("Coder source must be text.")
    tree = ast.parse(source)
    allowed = (
        ast.Module,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.If,
        ast.Return,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Expr,
        ast.UnaryOp,
        ast.Not,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Is,
        ast.IsNot,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("The fixture expects a pure decision function.")
    if any(
        isinstance(node, ast.FunctionDef) and node.decorator_list
        for node in ast.walk(tree)
    ):
        raise ValueError("The fixture does not allow decorators.")
    with tempfile.TemporaryDirectory(prefix="handoff-sieve-sdk-") as directory:
        workspace = Path(directory)
        solution = workspace / "solution/session_policy.py"
        solution.parent.mkdir()
        solution.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-I", str(ACCEPTANCE), str(workspace)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode:
            raise ValueError(
                "Generated module failed the existing takeover acceptance."
            )
        acceptance = json.loads(completed.stdout)
        namespace: dict[str, Any] = {}
        exec(
            compile(tree, "session_policy.py", "exec"),
            {"__builtins__": {}, "bool": bool, "str": str},
            namespace,
        )
        assert (
            namespace["decide_refresh_action"](
                hash_matches=True,
                token_revoked=True,
                token_expired=True,
            )
            == "revoke_family"
        ), "The rejected expiry-before-reuse approach returned."
        return {"passed": acceptance["passed"] + 1, "total": acceptance["total"] + 1}


async def run_workflow(
    *, live=False, model_id=None, full_history=False
) -> dict[str, Any]:
    compilations = []
    contract = ReceiverContract(
        goal="Implement refresh-token action selection in the auth module.",
        required=(
            "constraints",
            "decisions",
            "failed_attempts",
            "pending_work",
            "tool_results",
        ),
        max_tokens=900,
    )
    packet_filter = OpenAIReceiverContractFilter(
        contract,
        sender="researcher",
        receiver="coder",
        on_compile=compilations.append,
    )

    def inspect_full_handoff(data):
        compilations.append(
            compile_openai_handoff(
                data,
                contract,
                sender="researcher",
                receiver="coder",
            )
        )
        return data

    provider = (
        OpenAIProvider(use_responses=True, use_responses_websocket=False)
        if live
        else None
    )
    coder_model = RecordingModel(
        provider.get_model(model_id) if provider else OfflineCoder()
    )
    coder = Agent(name="coder", instructions=CODER_INSTRUCTIONS, model=coder_model)
    researcher = Agent(
        name="researcher",
        model=OfflineResearcher(),
        tools=[inspect_session_api],
        handoffs=[
            handoff(
                coder,
                input_filter=inspect_full_handoff if full_history else packet_filter,
            )
        ],
    )
    history = [
        {"role": "user", "content": "Unrelated hosting prices and launch copy. " * 200},
        {
            "role": "user",
            "content": (
                "Constraint: Keep the public decide_refresh_action "
                "keyword-only API stable."
            ),
        },
    ]
    try:
        result = await asyncio.wait_for(
            Runner.run(
                researcher,
                history,
                max_turns=3,
                run_config=RunConfig(
                    tracing_disabled=True,
                    model_settings=ModelSettings(
                        max_tokens=1_200,
                        store=False,
                        preserve_raw_usage=True,
                        timeout=60,
                        retry=ModelRetrySettings(max_retries=0),
                    ),
                ),
            ),
            timeout=75,
        )
    finally:
        await coder_model.close()
    assert result.last_agent is coder
    assert len(compilations) == 1 and len(coder_model.inputs) == 1
    compilation = compilations[0]
    actual_input = coder_model.inputs[0]
    if not full_history:
        assert actual_input == [
            {"role": "user", "content": compilation.packet.to_receiver_text()}
        ]
        assert "hosting prices" not in repr(actual_input)
    acceptance = check_solution(result.final_output)
    return {
        "mode": "live_coder" if live else "offline_fixture",
        "condition": "full_history" if full_history else "handoff_sieve",
        "requested_model": model_id if live else None,
        "source_estimated_tokens": compilation.source_tokens,
        "packet_estimated_tokens": compilation.packet_tokens,
        "receiver_input_items": len(actual_input),
        "latest_decision_preserved": bool(compilation.packet.decisions),
        "failed_attempt_preserved": bool(compilation.packet.failed_attempts),
        "completed_tool_result_preserved": bool(compilation.packet.tool_results),
        "provider_calls": 1 if live else 0,
        "coder_provider_input_tokens": result.raw_responses[-1].usage.input_tokens
        if live
        else None,
        "coder_provider_output_tokens": result.raw_responses[-1].usage.output_tokens
        if live
        else None,
        "acceptance": acceptance,
        "solution_source": json.loads(result.final_output)["source"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make one real coder call.")
    parser.add_argument("--model", help="The exact provider model name for --live.")
    parser.add_argument(
        "--full-history", action="store_true", help="Use the live baseline."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the verification record."
    )
    args = parser.parse_args()
    if args.live and (not args.model or not os.environ.get("OPENAI_API_KEY")):
        parser.error(
            "--live requires --model and OPENAI_API_KEY; OPENAI_BASE_URL is optional."
        )
    if args.full_history and not args.live:
        parser.error(
            "--full-history requires --live; the offline coder expects a packet."
        )
    record = asyncio.run(
        run_workflow(
            live=args.live, model_id=args.model, full_history=args.full_history
        )
    )
    if args.json:
        print(json.dumps(record, indent=2))
        return
    print("SDK workflow: Researcher -> inspect_session_api -> Coder")
    print(
        f"Mapped sender state: {record['source_estimated_tokens']:,} estimated tokens"
    )
    print(f"Receiver packet: {record['packet_estimated_tokens']:,} estimated tokens")
    print("Runtime decision, rejected approach, and completed tool result preserved.")
    print(f"Receiver input items: {record['receiver_input_items']}")
    print(f"Provider calls: {record['provider_calls']}")
    acceptance = record["acceptance"]
    print(f"Takeover acceptance: {acceptance['passed']}/{acceptance['total']}")
    print("Result: SDK handoff and task acceptance verified.")
    if not args.live:
        print("Offline fixture models verify integration, not LLM coding ability.")


if __name__ == "__main__":
    main()
