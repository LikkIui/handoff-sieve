# Model-assisted original-source handoff: 2026-10-10

**43 saved real task requests, 164,867 available reported provider tokens.**
These are synthetic executable diagnostics through the user-authorized
compatible gateway, requested model `gpt-5.6-sol`. The upstream model identity
and invoice cost are not independently verified. One additional connectivity
probe preceded these tasks (4,405 reported tokens); it is outside the task
records below. No client automatic retries or offline model substitutions.

This is a development sequence, not a stable success-rate benchmark. It shows
what improved, what failed, and how the new extraction path compares with a
stronger receiver-aware model summary. It does **not** establish superiority
over other projects or over that summary.

## Same sender state, two receivers

The coder fixes a small module and is checked for its keyword-only API and
six behaviors. The reviewer inspects the unchanged original module, with three
strict boolean checks. Each condition receives the same public task instruction;
summary preparation and selection receive the same goal, needs and packet budget.
The selector and summary do not receive host grading answers.

Revised goal-selection run, one trial per receiver and condition:

| Condition | Success | Mean estimated handoff tokens | Total reported provider tokens, both receivers | Requests |
|---|---:|---:|---:|---:|
| Full history | 2/2 | 4,981 | 9,373 | 2 |
| Existing rules | 0/2 | 1,262 | 2,740 | 2 |
| Receiver-aware model summary | 2/2 | 370 | 11,079 | 4 |
| Model-selected original spans | 2/2 | 415 | 13,588 | 4 |

The new path sends about 91.7% less estimated receiver context than full
history. Preparation means **more total tokens** than full history or the
strong summary in this example. A low token count from the failed rules path
is not a product win. Exact unrounded values, request bodies, SDK-parsed
responses and checks are in [`receiver-goals/`](receiver-goals/).

The revised views contain different original source-ID sets. They share the
accepted policy and current code. The reviewer additionally retains the passing
reuse observation, which is not in the coder's view. There is still substantial
overlap and extra context; this is not a proof of mathematically minimal state.

The preceding 12-call draft in [`initial-goals/`](initial-goals/) succeeded at
both takeovers but selected the same source-ID sets for both receivers. Its
original view-difference check compared goal-bearing packet text and produced a
false positive. We replaced that check with source-ID set comparison. The raw
calls/results remain published; the flawed draft aggregate is omitted in favor
of the corrected checks in [`summary.json`](summary.json). Both original rule
outcomes are retained: coder failed, reviewer passed. The revised reviewer
rule failure illustrates single-trial variability, not a stable failure rate.

## Existing executable pilots without category labels

The original three public pilot tasks are reused. This disclosed variant
removes message kinds and tags while preserving content, artifacts and public
starter files. Full history, the stronger summary, and model selection share
the same task prefix and existing independent, time-bounded host acceptance.

| Task | Full history | Receiver-aware summary | Model selection, first attempt | Estimated handoff: full / summary / model |
|---|---|---|---|---|
| Composite cursor implementation | Pass | Pass | Pass | 1,450 / 709 / 633 |
| Streaming CSV implementation | Pass | Pass | Pass | 1,536 / 745 / 713 |
| Active cursor patch review | Pass | Pass | **Blocked: duplicate source selection** | 1,570 / 799 / no packet |

The failed review selector assigned `m9.0` to both evidence and pending work.
Local validation rejected the plan before any receiver call. The selector
instruction now explicitly requires one selection per source ID; a selection
may support multiple needs without duplicating the source. The independent
[`review-followup/`](review-followup/) made two additional requests and passed
the same review acceptance with a 992-token packet. It consumed 8,966 reported
tokens. This follow-up **does not replace the first failure**.

Pilot first-attempt totals include 14 requests and 69,288 reported tokens;
[`pilots/`](pilots/) retains all nine condition outcomes. The review's failed
selector consumed 3,138 tokens despite producing no deliverable packet.
Source references, valid schema and budget are locally checked; semantic
coverage and relevance remain model judgments.
All eight successfully compiled packets across the development phases were
also checked against the recorded selector catalogs: every retained item's
content matches its referenced original source content exactly.

## Real SDK handoff

[`sdk/`](sdk/) records three actual HTTP requests: researcher routing,
selection, and coder takeover. The final HTTP request contains exactly one
canonical `HandoffPacket` and no `previous_response_id` or conversation
continuation. The original synthetic sender state stays unchanged. The coder's
generated module passes its API and all six behavior checks. Total reported
provider usage is 9,414 tokens.

## Reproduce

From current `main` with `.[openai]` installed:

```bash
python examples/receiver_goals/demo.py --model YOUR_MODEL --output outputs/receiver-goals
python examples/receiver_goals/sdk_handoff.py --model YOUR_MODEL --output outputs/receiver-sdk
python -m examples.receiver_goals.pilots --model YOUR_MODEL --output outputs/receiver-pilots
```

Provide `OPENAI_API_KEY` / optional `OPENAI_BASE_URL`, or use the hidden
credential prompt. Use a new output directory for each run. Model outputs and
usage can vary. The initial, revised and pilot phases precede the final unique
source-ID instruction; the separately labeled follow-up tests that correction.
They are not independent repeated trials of one frozen release.

## Reading the records

- `call-*.json`: preparation/receiver arguments and complete SDK-parsed response
  data; SDK run records actual HTTP JSON bodies. Authentication headers and
  credentials are excluded. Opaque provider response fields remain unchanged.
- `results.json` / `report.json`: exact context, output, acceptance and usage.
  Provider token totals include preparation, reasoning usage when reported,
  and all saved calls. Local handoff tokens use the built-in UTF-8 estimate.
- `summary.json`: counts for every phase and corrected source-set comparisons.

The value of the new API is goal-sensitive selection from ordinary history,
locally reconstructed original content and explicit validation at the existing
handoff boundary. Cost reduction and consistently better task success still
need evidence. The immediate next work is selection stability and preparation
cost, not additional adapters or security protocols.
