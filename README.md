# RelayGuard

**A policy and audit layer for agent-to-agent handoffs.**

RelayGuard sits between two AI agents and controls what the receiving agent is
allowed to see. It can redact common secrets, remove exact duplicates, protect
critical constraints, enforce a token budget, validate structured packets, and
record every change without storing the sensitive source text.

```text
Researcher                     Writer
    |                             ^
    |  raw handoff                |
    v                             |
  RelayGuard ---------------------+
  preserve -> redact -> deduplicate -> budget -> audit
```

RelayGuard is not an agent framework. It does not create agents, choose the
next agent, or orchestrate a workflow.

## Why

Agent handoffs often forward an entire conversation even when the next agent
only needs a few conclusions and constraints. That can increase cost, leak
sensitive text, and bury important instructions in irrelevant history.

RelayGuard makes that boundary explicit and testable.

## Status

This repository is an alpha MVP. The Python core, safe YAML configuration,
offline summarizer interface, audit reports, and an optional OpenAI Agents SDK
adapter are implemented. Token counts use an explicitly labelled UTF-8
estimate by default.

## Install locally

```bash
python -m pip install -e .
```

For development:

```bash
python -m pip install -e . pytest
python -m pytest
```

The test suite and examples do not require an API key.

For model-aware text tokenization, install the optional counter:

```bash
python -m pip install -e ".[tiktoken]"
```

```python
from relayguard import HandoffPipeline, TiktokenCounter

pipeline = HandoffPipeline(token_counter=TiktokenCounter("gpt-4o-mini"))
```

Message-wrapper overhead remains an estimate because providers serialize
metadata differently, even when the underlying text encoding is exact.

## Five-minute example

```python
from relayguard import HandoffPipeline, Message
from relayguard.policies import (
    BudgetPolicy,
    ExactDedupPolicy,
    PreservePolicy,
    RedactPolicy,
)

pipeline = HandoffPipeline(
    [
        PreservePolicy(),
        RedactPolicy(detectors=["api_key", "email"]),
        ExactDedupPolicy(),
        BudgetPolicy(500, strategy="drop_oldest"),
    ]
)

result = pipeline.process(
    sender="researcher",
    receiver="writer",
    messages=[
        Message(
            content="The final answer must cite sources.",
            tags={"constraint"},
        ),
        "Contact alice@example.com with key sk-example123456.",
        "Repeated research note.",
        "Repeated research note.",
    ],
)

print(result.report.to_text())
print([message.content for message in result.messages])
```

The input objects are copied before processing, and audit events do not contain
the redacted value.

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
configured and none match, RelayGuard rejects the handoff by default. Set
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

Policy order matters. RelayGuard rejects known built-in order inversions. Use
preserve, redact, schema, deduplicate, select or summarize, and finally budget.
If protected content alone exceeds the budget, RelayGuard raises
`BudgetExceededError` rather than deleting it.

`protected` and adapter reconstruction data are private processing state. They
cannot be supplied through a public `Message` or mapping input. Unknown fields
on messages, artifacts, and envelopes are rejected instead of silently
creating an unprocessed output channel.

## Audit and denied handoffs

Every audit report has a schema version, unique `handoff_id`, and a `passed` or
`denied` status. Policy failures attach the denied report to the raised
`RelayGuardError`:

```python
from relayguard import RelayGuardError

try:
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=["handoff content"],
    )
except RelayGuardError as error:
    if error.report is not None:
        print(error.report.model_dump_json())
    raise
```

Reports contain counts and reason codes rather than removed or redacted source
values. Schema validation reports how many fields normalization changed or
removed.

## Summarization

Summarization is provider-neutral and opt-in:

```python
from relayguard.policies import MockSummarizer, SummarizePolicy

policy = SummarizePolicy(
    MockSummarizer("Offline test summary"),
    max_tokens=100,
)
```

`MockSummarizer` exists for tests and demonstrations. Applications can
implement the small `Summarizer` protocol with their model provider. Reports
track summarizer input and output separately so a summary call is not presented
as free token savings.

YAML does not instantiate a summarizer because doing so would require silently
loading credentials or executable provider code. Construct that policy in
Python instead.

The current pipeline and `Summarizer` protocol are synchronous. RelayGuard
rejects an async summarizer with a denied audit report instead of leaving an
unawaited coroutine or blocking an event loop implicitly.

## OpenAI Agents SDK

Install the optional dependency:

```bash
python -m pip install -e ".[openai]"
```

Then use RelayGuard as a handoff input filter:

```python
from agents import handoff
from relayguard.adapters import OpenAIHandoffFilter

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
`new_items` intact for session history. Its latest audit reports are stored per
execution context and are available through `handoff_filter.last_reports`.

Input filters are intended for client-managed conversation history. Follow the
OpenAI Agents SDK's restrictions for server-managed conversations.
The current compatibility window is OpenAI Agents SDK 0.22.x; each later minor
version must pass the adapter integration tests before the upper bound moves.

## Examples

```bash
python examples/quickstart/run.py
python examples/failure_zoo/secret_leakage/demo.py
python examples/failure_zoo/context_flooding/demo.py
python examples/failure_zoo/constraint_loss/demo.py
```

The Failure Zoo examples are executable assertions, not benchmark claims.

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

See [SECURITY.md](SECURITY.md) before using RelayGuard with sensitive data.

Detailed references:

- [Configuration](docs/configuration.md)
- [Custom policies](docs/custom-policies.md)
- [OpenAI adapter support matrix](docs/openai-adapter.md)
- [Threat model](docs/threat-model.md)

## Roadmap

- LangGraph and AutoGen adapters
- additional provider-specific token counters
- repeatable handoff-quality evaluations
- A2A-compatible policy metadata or proxy
- stable third-party policy plugin API

## License

MIT
