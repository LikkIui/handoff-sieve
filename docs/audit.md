# HandoffSieve audit reports

Every completed pipeline run produces one versioned `AuditReport`. Successful
runs return it as `result.report`; denied runs attach the same report to the
raised `HandoffSieveError`. A report contains counts and stable identifiers, not
message, artifact, metadata, or redacted field values.

## Correlation and timing

Each report includes:

- `schema_version`, currently `"1"`;
- a generated `handoff_id`;
- an optional caller-supplied `request_id`;
- UTC `started_at` and `completed_at` timestamps;
- monotonic `duration_ms` covering normalization and policy execution;
- `status`, `failure_code`, and `failed_policy`;
- the token-counter name and a SHA-256 `config_fingerprint`.

Pass a safe application correlation ID when processing a handoff:

```python
result = pipeline.process(
    sender="researcher",
    receiver="writer",
    messages=["handoff content"],
    request_id="job-2026-09-27-42",
)
```

`sender`, `receiver`, and `request_id` are audit identifiers. Use opaque aliases
rather than email addresses, customer names, credentials, or message text.
The configuration fingerprint covers policy types, versions, public policy
settings, routes, the token counter, and route behavior without including that
configuration in the report. It is a comparison aid, not a signature.
`MockSummarizer` contributes a SHA-256 hash of its fixed output text. A custom
summarizer is identified by type unless it exposes safe fingerprint material;
applications can pass a stable, non-sensitive `config_id` to
`SummarizePolicy` to distinguish deployments without hashing credentials.

## Estimated and provider-reported usage

`original_tokens`, `transmitted_tokens`, `summarizer_input_tokens`, and
`summarizer_output_tokens` are values computed by the configured HandoffSieve
token counter. HandoffSieve always computes the two summarizer values locally.
They drive `estimated_net_tokens_saved`.

A summarizer may also return provider usage in `Summary.input_tokens` and
`Summary.output_tokens`. Those values are stored separately as
`summarizer_provider_input_tokens` and
`summarizer_provider_output_tokens`. They remain `null` when the provider does
not supply usage, so a missing provider measurement is never presented as
zero-cost work.

## Events and policy versions

Events identify a policy, its version, the action, a count, and safe details.
Built-in policy versions change when their audited behavior changes;
`RedactPolicy` and `ExactDedupPolicy` currently report version `"2"`, while the
remaining built-ins report `"1"`. A custom policy can declare a different
version:

```python
class MyPolicy(Policy):
    name = "my_policy"
    version = "2"
```

The pipeline stamps events created while that policy runs with its declared
version. Event details must contain only counts, reason codes, stable IDs, and
safe configuration metadata.
Redaction events include an `input` or `egress` stage so reports distinguish
source scrubbing from the final pass over summarizer output.

## Callback and JSONL reporters

Reporters receive a deep copy of the completed `AuditReport`. They never
receive the source or processed `HandoffEnvelope`.

```python
from handoff_sieve import CallbackReporter, HandoffPipeline, JsonlReporter


def observe(report):
    print(report.handoff_id, report.status)


pipeline = HandoffPipeline(
    policies,
    reporters=[
        CallbackReporter(observe),
        JsonlReporter("var/audit/handoff_sieve.jsonl"),
    ],
)
```

The JSONL parent directory must already exist. A `JsonlReporter` serializes
each report on one UTF-8 line and protects appends made through the same
reporter instance with a lock.

If a reporter fails after an otherwise successful run, HandoffSieve raises
`AuditExportError` and changes that report to `status="denied"` with
`failure_code="audit_export"`. If policy processing was already denied, a
reporter failure is recorded as a warning and does not replace the original
failure. Reporter callbacks should therefore be small, deterministic, and
idempotent when they forward records to another system.
