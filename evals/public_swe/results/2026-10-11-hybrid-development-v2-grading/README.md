# Hybrid handoff: eight fixed development tasks

The new hybrid compiler combines a concise receiver brief with original evidence
copied by the application. This run used eight previously attempted SWE-bench
Verified development tasks, frozen byte-identical completed research, fresh
receiver episodes and rotated condition order. All eight official positive and
negative controls passed. There were no new research calls or distinct tasks.

| Condition | Official acceptance / all attempts | Requests including preparation | Known provider tokens |
|---|---:|---:|---:|
| Full History | 3/8 | 102 | 1,372,166 |
| Strong receiver-aware Summary | 4/8 | 139 | 1,331,433 |
| Hybrid HandoffSieve | 3/8 | 106 | 1,028,082 |

The primary result **does not beat the strong summary**. Hybrid preparation for
Django 13925 returned an unsupported section, so its receiver did not start.
That failure stays in the eight-attempt denominator. A later schema correction
and successful [single-case receiver](../2026-10-11-hybrid-takeover-v3-grading/README.md)
are separate; they cannot turn this primary result into 4/8.

The same seven tasks received actual context in all three conditions:

| Condition | Mean complete handoff estimated tokens | Requests including preparation | Known provider tokens |
|---|---:|---:|---:|
| Full History | 6,810.71 | 90 | 1,243,486 |
| Strong receiver-aware Summary | 1,688.57 | 123 | 1,184,571 |
| Hybrid HandoffSieve | 2,220.14 | 105 | 1,019,783 |

On these seven, hybrid acceptance is 3/7, summary 3/7 and full history 2/7.
Hybrid context is 67.4% smaller than full history but 31.5% larger than the strong
summary. Known end-to-end provider tokens, including preparation, are 13.9%
lower than the summary and 18.0% lower than full history. These are one-trial,
post-generation matched-context diagnostics, not a replacement success
denominator or evidence of stable superiority. Omitting the failed preparation
from this size comparison prevents its absent receiver from looking cheap.

## What still fails

Astropy 14598, Django 13212, Sphinx 7748 and SymPy 21596 fail in every condition.
The [syntax diagnostic](candidate-syntax-diagnostic.json) finds broken Python in
all three Django 13212 candidates and the full-history xarray candidate. It reads
retained receiver files after generation, never feeds results back to a model,
and does not replace the official grader. Sphinx and SymPy hybrid patches run
the official tests but leave their target behaviors failing. A valid packet
therefore remains insufficient evidence of correct downstream work.

The coder still has only list/search/read/edit operations, up to 24 operations,
and no in-loop test execution. mini-swe-agent was reviewed as a source reference
but was not integrated. The next quality step is the same mature execution and
visible-test feedback for all conditions, not more adapters or a 200-task run.

## Cost and publication scope

The entire run made **355 real requests, 354 completed**, with **3,792,156 known
provider tokens** and one timeout without usage. This includes preparations for
eight additional previously used states beyond the eight receiver tasks.
Primary condition costs include only their eight preparations and receivers;
shared earlier research costs are not claimed as savings. Of sixteen hybrid
preparations, thirteen were valid, two were locally rejected and one timed out.
The timeout belongs to an unused preparation, not a primary receiver episode.

Requests used `gpt-5.6-sol` at the configured compatible gateway; the underlying
model identity is unverified. All 200 formal test tasks remain unused.
Prototype v1, schema-v3 and the single-case correction are not pooled here.

This public bundle contains **candidate patches, hashes, metrics and official
grading summaries only**, following the user's publication choice. Full API
requests/responses, sender states, handoff text and encrypted reasoning remain
local. Sixty-four captured input files and nine frozen implementation files
were checked against local SHA-256 inventories before aggregation. The exact
evaluated composer predates the current contract-bounded response schema.
`summary.json` contains per-attempt metrics; `upstream/workflow.json` links the
independent official grading. Full API replay from this public bundle alone is
not available because sender snapshots were intentionally not published.
