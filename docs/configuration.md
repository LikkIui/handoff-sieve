# HandoffSieve configuration

HandoffSieve accepts policies directly in Python or from safe YAML. YAML only
constructs built-in policies and never imports a module named by the file.

## Root options

```yaml
version: 1
on_unmatched: error
on_multiple_match: error
```

`on_unmatched` controls a rule set with no matching route:

- `error` denies the handoff and is the default;
- `warn` applies global policies and adds an audit warning;
- `pass` applies global policies without a warning.

`on_multiple_match` controls overlapping rules:

- `error` denies an ambiguous route and is the default;
- `first` applies the first matching rule in declaration order;
- `all` concatenates every matching rule in declaration order.

Every rule should have a stable, unique `id`. Missing IDs become `rule-1`,
`rule-2`, and so on. Audit events record the IDs actually applied.

```yaml
rules:
  - id: researcher-to-writer
    from: researcher
    to: "writer*"
    policies: []
```

Sender and receiver matching is case-sensitive and supports `*` wildcards.
When `all` combines rules, the resulting policy sequence must still pass the
order check.

## Policy order

HandoffSieve validates this order for built-in policies:

1. `preserve`
2. input `redact`
3. `schema`
4. `deduplicate`
5. `select` or `summarize`
6. optional egress `redact`
7. `budget`

Equal-rank operations may repeat. Put custom policies that can change visible
content before egress redaction. After an egress redaction pass, only another
egress redaction or the budget may run; no policy may run after the budget.
HandoffSieve raises `ConfigurationError` instead of allowing a late policy to
bypass either terminal gate.

## Redaction limits

```yaml
- redact:
    stage: input
    detect: [api_key, email, phone]
    custom_patterns:
      ticket: 'CASE-\d+'
    max_pattern_bytes: 1000
    max_scan_bytes: 1000000
    max_scan_strings: 10000
    timeout_ms: 50
```

Detector names use 1–64 ASCII letters, digits, dots, underscores, or hyphens.
At most 32 custom patterns are accepted. Invalid patterns fail during
configuration. A scan limit or regex timeout denies the handoff and attaches a
denied audit report; HandoffSieve never treats an incomplete scan as success.

When a summarizer or custom transformation can generate new sensitive text,
add a second policy with `stage: egress` after that transformation and before
the hard budget. The audit event records the stage explicitly.

## Failure reports

Policy, route, normalization, and token-count failures raise a
`HandoffSieveError` with `error.report`. The report contains a unique
`handoff_id`, `status="denied"`, `failure_code`, and `failed_policy`. It does
not store the removed or redacted source value.
