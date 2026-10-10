# HandoffSieve 0.3.0a3 audit: 2026-10-04–05

Published to the repository on 2026-10-10. Product source under test:
`3a8d608a47c58c31c093f27d1aac485840c3dba3`; Agents SDK `0.22.3`.
All requests use the user-authorized compatible gateway and requested alias
`gpt-5.6-sol`. The alias does not independently identify its upstream model.
Credentials and authentication headers are not recorded.

## Original 20-task comparison

| Condition | Success / scheduled | Timeouts | Estimated handoff tokens | Available provider total tokens | Requests |
|---|---:|---:|---:|---:|---:|
| Full History | 17/20 | 2 | 15,025 | 34,541 | 20 |
| Naive Summary | 16/20 | 2 | 9,792 | 63,032 | 40 |
| HandoffSieve | 16/20 | 2 | 6,773 | 29,644 | 20 |

One trial per condition with prepared, classified sender state; the same
public task prefix, starter, and host checker. Summary usage includes its
preparation call. No automatic retry or removal of failed cases. Timeout
usage is unknown. Token estimates are separate from reported provider usage.
This does not establish success equivalence, invoice savings, or superiority
over a stronger structured-summary baseline.

`live20/` contains all 20 original JSONL files, the aggregate, request ledger,
probe, and run metadata. Exact receiver input, raw output, and checks remain
as recorded. `diagnostics/verified-public-inputs.json` records the public-source
verification; inputs were generated from the anonymous public v0.3.0a3 archive.

## Other diagnostics, kept separate

- `selection-stress/`: three deliberately constructed FIFO/budget failure
  tasks, two trials each. Full 6/6, current Sieve 0/6, explicit tag-selection
  prototype 5/6 with one timeout. This is a mechanism experiment, not a
  real-user success rate. The prototype is not shipped in core.
- `relay-live-20261005.json`: four real coder/reviewer requests, one actual
  source write, 5/5 coder checks, 9/9 independent reviewer checks, and verified
  first-receiver HTTP packet boundaries. Researcher is an offline fixture.
- `clarified-tasks-live-20261005/`: two tasks with incomplete public
  specifications receive the same minimal clarification in all conditions.
  Original Full/Sieve context bytes and grader are unchanged. Full 1/2,
  Summary 2/2, Sieve 2/2; these results do not overwrite the main comparison.
  Metadata preserves and explains an original mislabeled record-count field.
- `diagnostics/`: frozen performance samples, boundary reproductions, format
  controls, and independent result/priority reviews. Historical notes may
  name work-local diagnostic scripts; those scripts are not new product APIs.

## Request and usage ledger

| Diagnostic | Actual requests | Available usages | Timeouts | Available total tokens |
|---|---:|---:|---:|---:|
| Main comparison + probe | 81 | 75 | 6 | 127,268 |
| Selection stress | 18 | 17 | 1 | 11,985 |
| Live relay | 4 | 4 | 0 | 3,274 |
| Clarification follow-up | 8 | 8 | 0 | 13,814 |
| **Total** | **111** | **104** | **7** | **156,341** |

The total includes the 51-token connectivity probe once. Offline preparation
and mock transport are excluded. No automatic network retry occurred. Missing
usage is not zero billed cost. `inventory.json` stores SHA-256 hashes of the
44 copied evidence files; the records are byte-identical to their local audit
sources. Documentation and the inventory itself are outside that inventory.

See the [optimization review](../../../../docs/optimization-review-2026-10-04.md)
for interpretation and the bounded next-version scope. This is evidence for
the released a3 implementation, not an a4/v0.4 release.
