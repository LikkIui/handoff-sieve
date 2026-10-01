# Optional handoff cleanup pipeline

The receiver contract and structured packet are the main HandoffSieve API.
The existing policy pipeline remains available for cleanup of selected
context and for applications that already process whole handoffs.

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
