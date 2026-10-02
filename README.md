# HandoffSieve

**Give each AI agent only the context it needs to take over a task.**

HandoffSieve compiles a large sender state into a small, structured
`HandoffPacket` for one receiver. A `ReceiverContract` names the context that
the next agent needs, prefers, and can fit within its token budget.

```text
Large researcher state
(messages, searches, tool logs, dead ends)
                    |
                    | ReceiverContract for the coder
                    v
              HandoffSieve
                    |
                    v
Receiver-specific HandoffPacket
(goal, decisions, work completed, next steps, artifacts)
```

Reduce handoff tokens, preserve critical state, and avoid unnecessary
information disclosure.

## Try it offline

Requires Python 3.10 or later. Clone the project and run the demo; no API key
or model call is needed:

```bash
git clone https://github.com/LikkIui/handoff-sieve.git
cd handoff-sieve
git checkout v0.3.0a3
python -m pip install -e .
python examples/receiver_views/demo.py
```

**One sender history, two different receiver contracts:**

| Context | Estimated tokens | Receiver-specific content |
|---|---:|---|
| Full sender history | 3,536 | All messages, tool results, artifacts, and unrelated notes |
| Coder packet | 184 | Implementation decision and files to modify |
| Reviewer packet | 165 | Supporting evidence and tool checks |

Both packets preserve the compatibility constraint, failed approach, and
pending work. Unrelated hosting and launch notes disappear. The demo asserts
that the two views differ and that the original sender state stays intact.
Counts come from the actual synthetic fixture with the built-in token estimate.
This verifies packet selection; downstream task success is measured separately
in the checkpoint below.

For a packet-only takeover with five objective behavior checks:

```bash
python examples/researcher_to_coder/demo.py
```

```text
Before: 5,979 estimated tokens
After HandoffSieve: 372 estimated tokens
Receiver boundary: canonical HandoffPacket JSON only
Takeover acceptance: PASSED (5/5 checks)
```

This second demo uses a deterministic offline receiver to generate a small
Python module from the packet, then checks its API and four behaviors. It is
an installation and boundary demonstration, not a claim about LLM coding ability.

For a complete researcher → coder → reviewer relay in the `0.3.0a3` checkout:

```bash
python -m pip install -e ".[openai]"
python examples/three_agent_relay/run.py
```

This runs two real SDK handoffs with local fixture models. The coder writes a
module and passes five behavior checks; the reviewer receives the inherited
decisions plus new work and tool results, then independently checks the API and
all eight input combinations. See the [relay example](examples/three_agent_relay/README.md).

## Twenty-task real-provider checkpoint

The v0.3 checkpoint covers 20 executable takeover tasks with one trial per
task. All conditions used the same requested model, starter files, task prefix,
and host-side acceptance checks.

| Condition | Success | Mean handoff tokens | Mean provider tokens | Model calls |
|---|---:|---:|---:|---:|
| Full History | 18/20 | 751 | 1,916 | 20 |
| Naive Summary | 17/20 | 370 | 2,780 | 40 |
| HandoffSieve | 18/20 | 409 | 1,438 | 20 |

HandoffSieve matched Full History's success rate while using 45.6% fewer
handoff tokens and 25.0% fewer measured provider tokens. Naive Summary used the
smallest handoff text, but its preparation call doubled model calls, consumed
the most provider tokens, and completed one fewer task successfully. Exact
records, provider errors, grading corrections, and limitations are documented
in the
[`20-task result`](evals/takeover/results/2026-10-01-gpt-5.6-sol-20-task/README.md).

This is one trial per task through a user-authorized compatible gateway. It is
a product checkpoint rather than a statistically stable cross-model result.
The result notes also disclose a summary preparation output that answered the
task instead of summarizing its state. This historical run predates the current
summary prompt boundary and compact packet rendering; its recorded values stay
unchanged.

Separately, `0.3.0a3` losslessly re-renders those 20 saved packets from 8,177 to
6,773 estimated handoff tokens, a 17.2% reduction. This is an offline comparison
of the same typed state. It does not measure provider-token or billing savings,
and no provider calls or success checks were rerun for that comparison.

## Why

Agent handoffs often forward an entire conversation when the receiver needs a
goal, a few decisions, the work already completed, and the next steps. A short
generic summary can also drop the one failed attempt or constraint that matters.

HandoffSieve makes the receiver's needs explicit. Required sections must be
present and fit the budget. Preferred sections are added in order while space
remains. The output is a typed packet that another agent can consume directly.

## Install

Install the [`0.3.0a3` GitHub prerelease](https://github.com/LikkIui/handoff-sieve/releases/tag/v0.3.0a3)
directly. PyPI publication remains paused while account setup is completed:

```bash
python -m pip install "https://github.com/LikkIui/handoff-sieve/releases/download/v0.3.0a3/handoff_sieve-0.3.0a3-py3-none-any.whl"
```

The demos above are in the GitHub checkout at `v0.3.0a3`, not in the wheel.
For development, run
`python -m pip install -e ".[dev]"` followed by `python -m pytest` there.
Tests and offline demos do not require credentials.

The checkout and release are `0.3.0a3`, including continuous handoffs, compact
packet rendering, explicit current-state preparation, and the three-agent relay.
`0.3.0a2` introduced the live SDK contract filter, missing-state diagnostics,
and budget feedback. The older `0.3.0a2` and `0.3.0a1` release files remain
unchanged. See the [migration notes](docs/migration.md) for wire-format changes.

Token counts use an explicitly labelled UTF-8 estimate by default. Optional
model-aware text counting is available with the `tiktoken` extra and
`TiktokenCounter`; provider message-wrapper overhead remains an estimate.

## Core API

Put ordinary agent messages in a `HandoffEnvelope`, describe what the receiver
needs, and compile the history into a `HandoffPacket`:

```python
from handoff_sieve import (
    HandoffEnvelope,
    Message,
    ReceiverContract,
    compile_history,
)

sender_state = HandoffEnvelope(
    sender="researcher",
    receiver="coder",
    messages=[
        Message(content="Decision: Use signed sessions."),
        Message(content="Failed attempt: Store tokens in localStorage."),
        Message(content="TODO: Implement the session middleware."),
        Message(content="Unrelated discussion about launch copy."),
    ],
)

contract = ReceiverContract(
    goal="Implement the authentication module",
    required=("decisions", "pending_work"),
    preferred=("failed_attempts", "evidence"),
    max_tokens=4_000,
)

result = compile_history(sender_state, contract)
packet = result.packet

print(result.source_tokens, "->", result.packet_tokens)
print(packet.pending_work)
receiver_input = packet.to_receiver_text()
```

When your application supplies explicit state identities, call
`prepare_sender_state(sender_state, task_id="auth")` before compilation.
It keeps messages and artifacts tagged with `metadata.task_id="auth"` plus
untagged shared state, and removes exact public duplicates before budgeting.
For already classified messages, the latest matching `metadata.state_key`
replaces earlier state in the same task and section; a completed-work entry
closes an earlier pending-work entry with that key. Later pending work can
reopen it. Unlabelled old decisions and TODOs are not guessed away. For example:

```python
from handoff_sieve import prepare_sender_state

prepared = prepare_sender_state(sender_state, task_id="auth")
result = compile_history(prepared, contract)
```

The helper returns an independent copy. Task IDs and state keys must be
nonblank strings. Packet JSON omits item defaults; parse it with
`HandoffPacket.model_validate_json(receiver_input)` to restore the full typed
model instead of assuming every default field is present in the wire text.

`compile_history()` recognizes a deliberately small set of inspectable local
signals: headings such as `Decision:`, `TODO:`, and `Failed attempt:`, their
Chinese equivalents, common structured keys, tool messages, and dedicated
metadata hints. It does not call a model or guess from words in the middle of
prose. Unclassified conversation is omitted, and the result includes a
`NormalizationReport` showing how many messages each rule classified.
An explicitly headed note can contain several sections on separate lines;
continuation lines stay with their heading, and labels inside fenced code do
not start new sections. Report message counts refer to the original input.

When required state is missing, `ContractError.diagnostics` lists missing
sections, available section counts, unclassified input positions, and ways to
supply or label the actual state. `error.normalization` retains the completed
normalization report. Positions start at zero in the original envelope; they
are candidates to inspect, not guesses about which notes the receiver needs.
If a processing policy removed necessary state, the error points to that
policy stage instead. Try the correction flow without a model call:

```bash
python examples/missing_state/demo.py
```

`result.budget` reports the required context size, remaining space, and
preferred items omitted for budget before or after processing. Required
counts include the goal and packet overhead; all counts use the named local
counter. `BudgetExceededError.budget` explains a required-state overflow.
Feedback stays outside the receiver packet. To see a 250-token budget keep
the failed approach and omit evidence, then a 1,000-token budget restore that
evidence while preserving identical required state:

```bash
python examples/budget_feedback/demo.py
```

Applications that already classify state can use the stricter
`compile_handoff()` API with an exact plural `Message.kind` or tag such as
`constraints`, `decisions`, or `pending_work`. Files and structured outputs go
in `HandoffEnvelope.artifacts`. See the complete
[`researcher -> coder` example](examples/researcher_to_coder/demo.py).

`HandoffPacket` always has the same clear shape: Goal, Constraints, Decisions,
Evidence, Completed Work, Failed Attempts, Pending Work, Artifacts, and Tool
Results. Compilation performs no model call and makes no hidden semantic guess.
`to_receiver_text()` returns the same canonical JSON string used for packet
token counting, so an adapter does not introduce a second, larger rendering.

HandoffSieve is not an agent framework. It does not create agents, choose the
next agent, or orchestrate a workflow.

## Optional cleanup policies

The existing pipeline can redact common secrets, remove exact duplicates,
protect critical constraints, validate structured content, and enforce a hard
budget. With `compile_handoff(pipeline=...)`, cleanup runs on the selected
receiver view; contract-selected items cannot be silently trimmed, and the
contract applies the final budget.

See the [policy pipeline guide](docs/policy-pipeline.md) for YAML rules,
built-in policies, audit reports, and opt-in summarization. These are supporting
capabilities; the core compiler itself makes no model call.

## OpenAI Agents SDK

Install the optional dependency:

```bash
python -m pip install -e ".[openai]"
```

Compile the latest runtime history at the actual handoff:

```python
from agents import handoff
from handoff_sieve.adapters import OpenAIReceiverContractFilter

coder_handoff = handoff(
    agent=coder,
    input_filter=OpenAIReceiverContractFilter(
        contract,
        sender="researcher",
        receiver="coder",
    ),
)
```

The filter includes decisions made during the run and completed function-tool
results, then sends one canonical packet item. HandoffSieve counts this exact
text against `ReceiverContract.max_tokens`. Original SDK session items and
local run context stay intact. Missing required sections or an excessive budget
raise an error; they never trigger an implicit full-history fallback.

Run the real SDK tool / handoff loop with offline fixture models:

```bash
python examples/openai_takeover/run.py
```

The demo preserves the latest decision and rejected approach, then generates
a module that passes 6/6 behavior checks. Its [guide and live checkpoint](examples/openai_takeover/README.md)
also show one-task live coder verification. That gateway returned anomalous
token usage, so the SDK checkpoint makes no provider-cost savings claim.

See the [OpenAI adapter guide](docs/openai-adapter.md) for the lower-level
policy filter, precompiled packets, and tool-pair handling. The supported SDK
window is `0.22.x`;
filters work with client-managed conversation history.

## LangGraph

Install the optional dependency:

```bash
python -m pip install -e ".[langgraph]"
```

Compile the graph state with the same contract and route the canonical packet
to the receiver:

```python
from handoff_sieve.adapters import LangGraphHandoff, compile_langgraph_state


def handoff_node(state):
    compilation = compile_langgraph_state(
        state,
        contract,
        sender="researcher",
        receiver="coder",
    )
    return LangGraphHandoff(compilation.packet).command("coder")
```

The adapter replaces the sender's message state with one canonical packet for
the receiver and also exposes the structured packet as `handoff_packet`.
Completed `AIMessage` / `ToolMessage` pairs become one structured tool-result
item; orphaned or unfinished calls are rejected instead of producing a broken
receiver history.

The offline example invokes a real `StateGraph` and verifies that the coder
receives exactly one packet message:

```bash
python examples/langgraph_handoff/run.py
```

See the [LangGraph adapter guide](docs/langgraph-adapter.md) for custom state
keys and parent-graph routing. The compatibility window is LangGraph
`>=1.0,<2`.

## More examples

```bash
python examples/planner_to_executor/demo.py
python examples/researcher_to_reviewer/demo.py
python examples/quickstart/run.py
```

The three takeover routes use the same core API and print measured estimated
tokens from their actual sender state and compiled packet. They run offline.
The [Failure Zoo](examples/failure_zoo) contains executable regression examples
for cleanup and denied handoffs.

<details>
<summary>Maintainer reference: deterministic policy regression fixture</summary>

The versioned synthetic fixture in `benchmarks/` checks the existing policy
pipeline without a model call. It includes eight labelled fake secrets, four benign
lookalikes, five constraints, citations, a conclusion, a tool pair, an
Artifact, long repeated context, one summary-generated secret, and five
denied-path cases. `python -m benchmarks.run --check` reproduces the stable
result and verifies this generated table. Maintainers use `--write` only to
refresh both after an intentional fixture or policy change; a failing run is
never written. This is a regression check, not the v0.3 takeover benchmark or
evidence for the product's downstream-success claim.

<!-- benchmark-results:start -->
| Fixed offline benchmark metric | Result |
|---|---:|
| Source secret/PII recall | 100.0% (8/8) |
| Receiver / audit secret leaks | 0 / 0 |
| Labelled false-positive rate | 0.0% (0/4) |
| Constraint retention | 100.0% (5/5) |
| Citation retention | 100.0% (2/2) |
| Conclusion retention | 100.0% (1/1) |
| Downstream task success | 100.0% (1/1) |
| Tool-pair integrity | 100.0% (1/1) |
| Deterministic runs | 5/5 |
| Audited failure cases | 5/5 |
| Audit completeness | 100.0% |
| Estimated tokens | 903 original → 556 transmitted; 283 summarizer; 64 net saved |
| Pipeline latency | p50 2.703 ms; p95 5.842 ms on the generating machine |
<!-- benchmark-results:end -->

</details>

## Limitations and references

- Local normalization recognizes explicit headings, keys, and metadata. It can
  omit useful unlabelled prose; inspect the packet and normalization report.
- A smaller packet is useful only if the receiver can still complete its task.
  The 20-task result is one checkpoint, not a general success guarantee.
- Default token counts are estimates. Exact deduplication does not detect
  semantically similar messages; pattern redaction is best effort.

References: [Configuration](docs/configuration.md), [audit](docs/audit.md),
[custom policies](docs/custom-policies.md), [migration](docs/migration.md),
[security](SECURITY.md), [changelog](CHANGELOG.md), and
[contributing and feedback](CONTRIBUTING.md).

## Roadmap

- **v0.1 — Make It Real:** installable core, OpenAI Agents SDK adapter, and
  clear end-to-end examples.
- **v0.2 — Killer Feature:** make `ReceiverContract`, `HandoffPacket`, and
  minimal sufficient handoff the center of the API and demos.
- **v0.3 — Prove It:** completed a 20-task comparison of full history, naive
  summary, and HandoffSieve, then added the LangGraph adapter.

See the focused [iteration roadmap](docs/iteration-roadmap.md). Additional
frameworks and protocol work wait for real user demand.

## License

MIT
