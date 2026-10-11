# Remaining twenty development attempts

This report retains all twenty preselected non-pilot development tasks. It uses one trial per condition at implementation `9659fb2`, with eight shared research operations and up to twenty-four source operations per coder. Original upstream tests determine acceptance; the coder has no local test execution.

| Condition | Valid official acceptance / all attempts | Actual-context samples | Mean handoff estimate | Preparation requests / known tokens | Continuation requests / known tokens |
|---|---:|---:|---:|---:|---:|
| Full History | 7/20 | 16 | 5987.56 | 0 / 0 | 183 / 2,159,399 (+2 unknown usage) |
| Receiver-aware Summary | 8/20 | 15 | 1443.87 | 16 / 116,245 (+1 unknown usage) | 222 / 1,732,349 (+3 unknown usage) |
| HandoffSieve | 5/20 | 11 | 2563.91 | 16 / 140,254 (+4 unknown usage) | 107 / 788,940 (+2 unknown usage) |

## Failures and denominator

A valid acceptance requires successful official controls and an accepted candidate. Provider outages, shared setup failures or interruptions, context budget rejections, missing evidence, no patch, code failures, and grader problems remain separate below. The full denominator is twenty for every condition; uncompleted model execution is not treated as evidence that its generated code would have failed.

- Full History: success: 7, code_failed_upstream: 7, shared_provider_503: 4, provider_or_transport_error: 1, provider_503: 1.
- Receiver-aware Summary: success: 8, provider_503: 4, code_failed_upstream: 4, shared_provider_503: 4.
- HandoffSieve: budget_rejection: 1, provider_503: 6, code_failed_upstream: 4, shared_provider_503: 4, success: 5.

### Paired tasks without recorded service interruption

This secondary, post-hoc diagnostic excludes only tasks with a raw provider/transport error or interruption in any research or condition request. Budget rejections and code failures remain included; the primary twenty-task denominator above is unchanged. It is not a replacement cohort or evidence of stable superiority.

| Condition | Acceptance on the same service-error-free tasks |
|---|---:|
| Full History | 5/10 |
| Receiver-aware Summary | 6/10 |
| HandoffSieve | 5/10 |

Task IDs: `pydata__xarray-6721`, `django__django-13212`, `django__django-12965`, `django__django-11848`, `django__django-15741`, `django__django-14315`, `django__django-14765`, `django__django-13109`, `matplotlib__matplotlib-20488`, `scikit-learn__scikit-learn-9288`.

Official controls valid: **20/20**. Every task's raw condition status, official result and patch hash appears in [summary.json](summary.json). Invalid controls and grader infrastructure errors are not certified task successes.

## Context and cost boundaries

The raw records contain **641 API requests**, **625 completed request records**, and **5,298,757 known provider-reported tokens**. **16 requests lack reported total usage**; their consumption and billing are unknown. Known usage is not total spend or a bill.

Shared research used 97 requests and 361,570 known tokens, counted once across conditions. For summary and model selection, preparation is the first actual request in that condition folder, including rejected or incomplete attempts. Later native tool requests are continuation cost. Full History makes no preparation model request. The detailed records include phase-specific missing-usage counts and HTTP error statuses.

Handoff means describe only saved contexts or the actual initial receiver request, including requests later rejected by the provider. No context is invented for a preparation failure. Different sample counts must not be interpreted as a matched comparison. The complete three-condition context subset is listed explicitly:

- `django__django-13212`
- `django__django-12965`
- `django__django-11848`
- `django__django-15741`
- `django__django-14315`
- `django__django-14765`
- `django__django-13109`
- `matplotlib__matplotlib-20488`
- `scikit-learn__scikit-learn-9288`
- `scikit-learn__scikit-learn-13496`
- `sphinx-doc__sphinx-8595`

| Condition | Same-subset contexts | Mean handoff estimate |
|---|---:|---:|
| Full History | 11 | 5967.36 |
| Receiver-aware Summary | 11 | 1226.09 |
| HandoffSieve | 11 | 2563.91 |

## Evidence provenance

Terminal report hashes, original and exported patch bytes, parent manifest hashes, grader revision, and merged official reports were checked before writing this report. Grading batches are exports of the same candidates, not new model trials:

- `batch-01`: [workflow 38116293268](https://github.com/LikkIui/handoff-sieve/actions/runs/38116293268) (4 tasks).
- `batch-02`: [workflow 38116895672](https://github.com/LikkIui/handoff-sieve/actions/runs/38116895672) (2 tasks).
- `batch-03`: [workflow 38117432326](https://github.com/LikkIui/handoff-sieve/actions/runs/38117432326) (2 tasks).
- `batch-04`: [workflow 38130205830](https://github.com/LikkIui/handoff-sieve/actions/runs/38130205830) (12 tasks).

The final `run-manifest.json` and all batch `upstream/workflow.json` identities are preserved; this utility does not overwrite them.

## What this result supports

The first ten pilot IDs plus these twenty IDs cover **thirty distinct attempted development tasks**. That is not thirty successes, and their success rates are not combined because pilot configurations and corrective repeats differ. Provider outages and a single development trial do not justify a claim of stable superiority. The frozen 200-task formal evaluation is separate and is not represented here.


To audit and reproduce this summary without model calls, run from the repository root:

```bash
python evals/public_swe/results/2026-10-11-development-remaining20/summarize-reproduce.py.txt
```
