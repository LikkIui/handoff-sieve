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

## 30-second demo

The bundled researcher-to-coder demo is deterministic, runs offline, and uses
the built-in estimated token counter:

```bash
python -m pip install -e .
python examples/researcher_to_coder/demo.py
```

```text
Researcher -> Coder
Before: 5,979 estimated tokens
After HandoffSieve: 438 estimated tokens
Context reduction: 92.7%
Omitted: 3 unrelated items
Normalized: 7 useful messages with local rules (0 model calls)

HandoffPacket
  Goal: Implement refresh-token action selection in the auth module.
  Constraints: Keep the public decide_refresh_action keyword-only API stable.
  Decisions: Reject a hash mismatch first; revoke the whole family on reuse; reject expired tokens; rotate otherwise.
  Evidence: The session service already supplies hash_matches, token_revoked, and token_expired flags.
  Completed work: Reduced the refresh-token behavior to an ordered decision table.
  Failed attempts: Checking expiry before reuse hid reuse of an expired revoked token.
  Pending work: Generate session_policy.py and satisfy the takeover acceptance cases.
  Artifacts: refresh-action-spec
  Tool results: Existing session tests pass; the decision function is still missing.

Receiver boundary: canonical HandoffPacket JSON only
Receiver: deterministic offline generator (no LLM or API call)
Generated: solution/session_policy.py
Takeover acceptance: PASSED (5/5 checks)

Result: packet-only offline takeover completed and verified.
```

The final `PASSED` is an offline boundary check. A deterministic receiver
process reads only the canonical packet JSON, generates a small Python module
in an empty temporary workspace, and an independent acceptance process checks
its public API plus four behaviors. It does not measure LLM coding ability or
claim downstream task success.

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

## Why

Agent handoffs often forward an entire conversation when the receiver needs a
goal, a few decisions, the work already completed, and the next steps. A short
generic summary can also drop the one failed attempt or constraint that matters.

HandoffSieve makes the receiver's needs explicit. Required sections must be
present and fit the budget. Preferred sections are added in order while space
remains. The output is a typed packet that another agent can consume directly.

## Status

The [`0.3.0a1` GitHub prerelease](https://github.com/LikkIui/handoff-sieve/releases/tag/v0.3.0a1)
is available. PyPI publication is pending account configuration. The receiver
contract, structured packet, local history normalizer, policy pipeline,
20-task product checkpoint, and optional OpenAI Agents SDK and LangGraph
adapters are implemented. Token counts use an explicitly labelled UTF-8
estimate by default.

Install the published wheel directly:

```bash
python -m pip install "https://github.com/LikkIui/handoff-sieve/releases/download/v0.3.0a1/handoff_sieve-0.3.0a1-py3-none-any.whl"
```

## Install from source

```bash
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

The test suite and examples do not require an API key.

For model-aware text tokenization, install the optional counter:

```bash
python -m pip install -e ".[tiktoken]"
```

```python
from handoff_sieve import HandoffPipeline, TiktokenCounter

pipeline = HandoffPipeline(token_counter=TiktokenCounter("gpt-4o-mini"))
```

Message-wrapper overhead remains an estimate because providers serialize
metadata differently, even when the underlying text encoding is exact.

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

`compile_history()` recognizes a deliberately small set of inspectable local
signals: headings such as `Decision:`, `TODO:`, and `Failed attempt:`, their
Chinese equivalents, common structured keys, tool messages, and dedicated
metadata hints. It does not call a model or guess from words in the middle of
prose. Unclassified conversation is omitted, and the result includes a
`NormalizationReport` showing how many messages each rule classified.

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
budget. It remains available for existing handoffs. When supplied through
`compile_handoff(pipeline=...)`, non-destructive transforms such as redaction
and validation run on the selected receiver view; contract-selected items are
protected from silent trimming, and the contract applies the final hard budget.

## YAML rules

```yaml
version: 1
on_unmatched: error
on_multiple_match: error

rules:
  - id: researcher-to-writer
    from: researcher
    to: "writer*"

    policies:
      - preserve:
          tags: [constraint, citation, conclusion]

      - redact:
          detect: [api_key, email]

      - deduplicate: exact

      - budget:
          max_tokens: 1200
          strategy: drop_oldest
```

```python
pipeline = HandoffPipeline.from_yaml("handoffs.yaml")
```

Sender and receiver names support `*` wildcard matching. YAML can only create
built-in policies; it never imports an arbitrary Python module. When rules are
configured and none match, HandoffSieve rejects the handoff by default. Set
`on_unmatched` to `warn` or `pass` only when that behavior is intentional.
Rules need stable, unique IDs. If multiple rules match, the default is also to
reject; `first` and `all` make the alternative behavior explicit and auditable.

## Built-in policies

| Policy | Purpose |
|---|---|
| `PreservePolicy` | Protect tagged constraints, citations, and conclusions |
| `RedactPolicy` | Replace configured sensitive patterns recursively |
| `ExactDedupPolicy` | Remove fully identical messages deterministically |
| `SelectPolicy` | Keep selected roles, kinds, or tags |
| `BudgetPolicy` | Enforce a hard estimated-token budget |
| `SchemaPolicy` | Validate structured packets with Pydantic |
| `SummarizePolicy` | Call a user-provided summarizer for unprotected messages |

Policy order matters. HandoffSieve rejects known built-in order inversions. Use
preserve, input redaction, schema, deduplicate, select or summarize, optional
egress redaction, and finally budget. If protected content alone exceeds the
budget, HandoffSieve raises `BudgetExceededError` rather than deleting it.
Custom policies that can change receiver-visible content must run before the
egress redaction pass. No policy may run after the hard budget.

`protected` and adapter reconstruction data are private processing state. They
cannot be supplied through a public `Message` or mapping input. Unknown fields
on messages, artifacts, and envelopes are rejected instead of silently
creating an unprocessed output channel.

When redaction precedes exact deduplication, HandoffSieve uses a per-run keyed
fingerprint to distinguish source messages that converge to the same redacted
text. That temporary value is cleared during deduplication and is never part of
the returned public or private message state.

## Audit and denied handoffs

Every audit report has a schema version, unique `handoff_id`, timestamps,
duration, configuration fingerprint, and a `passed` or `denied` status. A
caller can also supply `request_id` for correlation. Policy failures attach the
completed denied report to the raised `HandoffSieveError`:

```python
from handoff_sieve import HandoffSieveError

try:
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["handoff content"],
    )
except HandoffSieveError as error:
    if error.report is not None:
        print(error.report.model_dump_json())
    raise
```

Reports contain counts and reason codes rather than removed or redacted source
values. Schema validation reports how many fields normalization changed or
removed. `CallbackReporter` and `JsonlReporter` can export both successful and
denied reports without receiving the handoff envelope. See the
[audit report contract](https://github.com/LikkIui/handoff-sieve/blob/main/docs/audit.md)
for fields and failure behavior.

## Summarization

Summarization is provider-neutral and opt-in:

```python
from handoff_sieve import HandoffPipeline
from handoff_sieve.policies import MockSummarizer, RedactPolicy, SummarizePolicy

pipeline = HandoffPipeline(
    [
        RedactPolicy(detectors=["api_key", "email"]),
        SummarizePolicy(
            MockSummarizer("Offline test summary"),
            max_tokens=100,
        ),
        RedactPolicy(detectors=["api_key", "email"], stage="egress"),
    ]
)
```

`MockSummarizer` exists for tests and demonstrations. Applications can
implement the small `Summarizer` protocol with their model provider. Reports
always compute summarizer input and output with HandoffSieve's local token
counter. Optional provider-reported usage is stored in separate fields, so a
missing provider measurement is not presented as free token savings.

Input redaction prevents source secrets from reaching the summarizer. The
explicit `stage="egress"` pass handles a summarizer that generates a new
matching value. Put the hard budget after that pass. `MockSummarizer` hashes
its fixed text into the pipeline configuration fingerprint. For a custom
backend, pass a stable, non-sensitive `config_id` to `SummarizePolicy` when
deployment settings must distinguish audit fingerprints.

YAML does not instantiate a summarizer because doing so would require silently
loading credentials or executable provider code. Construct that policy in
Python instead.

The current pipeline and `Summarizer` protocol are synchronous. HandoffSieve
rejects an async summarizer with a denied audit report instead of leaving an
unawaited coroutine or blocking an event loop implicitly.

## OpenAI Agents SDK

Install the optional dependency:

```bash
python -m pip install -e ".[openai]"
```

Send the compiled receiver view directly to the next agent:

```python
from agents import handoff
from handoff_sieve import compile_history
from handoff_sieve.adapters import OpenAIHandoffPacketFilter

compilation = compile_history(sender_state, contract)
coder_handoff = handoff(
    agent=coder,
    input_filter=OpenAIHandoffPacketFilter(compilation.packet),
)
```

The receiver sees one canonical JSON item containing the goal and every packet
section, including artifacts and tool results. HandoffSieve counts this exact
text when enforcing `ReceiverContract.max_tokens`; the original runtime history
does not enter the receiving model's view.

For existing applications that want to apply the policy pipeline directly to
the SDK snapshot, use the lower-level filter:

```python
from agents import handoff
from handoff_sieve.adapters import OpenAIHandoffFilter

handoff_filter = OpenAIHandoffFilter(
    pipeline,
    sender="triage",
    receiver="refund_agent",
)

refund_handoff = handoff(
    agent=refund_agent,
    input_filter=handoff_filter,
)
```

The adapter treats history, pre-handoff items, and model input items as one
logical handoff, so deduplication and the hard budget apply to their combined
receiver view. It protects SDK control items from trimming and leaves original
`new_items` intact for session history. After all policies run, it verifies
recognized tool call/output IDs, order, pairing, and control-item retention.
Its latest audit reports are stored per execution context and are available
through `handoff_filter.last_reports`, including denied adapter invariants.
Use a pipeline reporter when a report must remain available after
`Runner.run_sync` returns to a different execution context.

Input filters are intended for client-managed conversation history. An output
whose matching call is hidden in server-managed history is denied. Realtime or
streaming inputs must be buffered into a complete supported handoff first.
The current compatibility window is OpenAI Agents SDK 0.22.x; each later minor
version must pass the adapter integration tests before the upper bound moves.

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

## Examples

```bash
python examples/researcher_to_coder/demo.py
python examples/planner_to_executor/demo.py
python examples/researcher_to_reviewer/demo.py
python examples/langgraph_handoff/run.py
python examples/quickstart/run.py
python examples/failure_zoo/secret_leakage/demo.py
python examples/failure_zoo/context_flooding/demo.py
python examples/failure_zoo/constraint_loss/demo.py
python examples/failure_zoo/full_envelope_leakage/demo.py
python examples/failure_zoo/route_drift/demo.py
python examples/failure_zoo/ingress_abuse/demo.py
python examples/failure_zoo/summary_reinjection/demo.py
python examples/failure_zoo/redaction_dedup_collision/demo.py
```

The three takeover examples use the same core API and print measured estimated
tokens from their actual sender state and compiled packet. They run offline and
make no downstream-success benchmark claim. The researcher-to-coder example
also runs the deterministic packet-only boundary check shown above.

The Failure Zoo examples are executable assertions, not benchmark claims.

## Deterministic regression fixture

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
| Pipeline latency | p50 4.400 ms; p95 5.727 ms on the generating machine |
<!-- benchmark-results:end -->

## Limitations

- Pattern redaction is best effort and is not a complete data-loss-prevention
  system.
- Regex compilation, scan volume, and execution time are bounded. Exceeding a
  bound denies the handoff instead of silently skipping redaction.
- The default token counter is an estimate, not a provider invoice.
- Exact deduplication is intentionally not semantic deduplication.
- The offline mock summarizer does not measure semantic quality.
- Compression should be evaluated on the downstream task, not only by message
  length.

See [SECURITY.md](https://github.com/LikkIui/handoff-sieve/blob/main/SECURITY.md) before
using HandoffSieve with sensitive data.

Detailed references:

- [Configuration](https://github.com/LikkIui/handoff-sieve/blob/main/docs/configuration.md)
- [Audit reports and exporters](https://github.com/LikkIui/handoff-sieve/blob/main/docs/audit.md)
- [Custom policies](https://github.com/LikkIui/handoff-sieve/blob/main/docs/custom-policies.md)
- [OpenAI adapter support matrix](https://github.com/LikkIui/handoff-sieve/blob/main/docs/openai-adapter.md)
- [LangGraph adapter](https://github.com/LikkIui/handoff-sieve/blob/main/docs/langgraph-adapter.md)
- [Threat model](https://github.com/LikkIui/handoff-sieve/blob/main/docs/threat-model.md)
- [Alpha migration notes](https://github.com/LikkIui/handoff-sieve/blob/main/docs/migration.md)
- [Name review](https://github.com/LikkIui/handoff-sieve/blob/main/docs/name-review.md)
- [Alpha release checklist](https://github.com/LikkIui/handoff-sieve/blob/main/docs/release-checklist.md)
- [Changelog](https://github.com/LikkIui/handoff-sieve/blob/main/CHANGELOG.md)
- [Contributing and feedback](https://github.com/LikkIui/handoff-sieve/blob/main/CONTRIBUTING.md)

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
