# Threat model

RelayGuard protects an agent handoff boundary. The untrusted caller may control
message content, structured keys and values, tags, metadata, artifacts, sender
and receiver identifiers, and route names.

## Security objectives

- Every public field in the canonical envelope is included in redaction and
  token counting.
- Public mapping/model input cannot set private protection or adapter
  reconstruction state.
- A missing or ambiguous route fails closed unless configuration explicitly
  selects another behavior.
- Protected content is never silently removed to satisfy a budget.
- Redaction resource limits fail closed.
- Successful and denied handoffs produce content-free audit facts that can be
  correlated by `handoff_id`.

## Trust assumptions

- Python application code, installed custom policies, and reviewed framework
  adapters are trusted code. RelayGuard is not a Python sandbox.
- `_process_trusted_envelope` accepts internal state created by an adapter;
  untrusted payloads must use `process` or public `process_envelope`.
- Configuration files are controlled by the application operator.
- The selected token counter is honest and deterministic.

## Out of scope and residual risk

- Pattern detectors do not recognize every secret or personal identifier and
  can redact benign text.
- Custom regex can be logically wrong even though size and runtime are bounded.
- A summarizer sees its input and can generate a new matching value. Put input
  redaction before summarization, egress redaction after it, and apply the
  provider's own data controls.
- Redacting tool arguments or outputs can change tool semantics. Protected
  status prevents deletion, not semantic corruption.
- Server-managed, Realtime, and streaming context that never enters the
  canonical envelope cannot be governed by the current adapter.
- Audit reports include sender/receiver identifiers after configured policies;
  applications should use safe aliases or hashes when those identifiers are
  sensitive.

Test with representative adversarial fixtures before production use. Keep
provider authentication, authorization, retention, and network controls in
place.
