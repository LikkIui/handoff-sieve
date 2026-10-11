# One correction round with original-test feedback

The official SWE-bench grader accepted all three conditions on both development
tasks after this correction round. This is a diagnostic result on two previously
used tasks, not a new benchmark sample or evidence of general superiority.

| Condition | Before correction, official acceptance | After correction, official acceptance | New correction requests | New reported provider tokens |
|---|---:|---:|---:|---:|
| Full History | 1/2 | 2/2 | 10 | 269,582 |
| Receiver-aware Summary | 1/2 | 2/2 | 4 | 68,399 |
| HandoffSieve | 2/2 | 2/2 | 3 | 53,668 |

The two tasks are `scikit-learn__scikit-learn-25931` and
`pylint-dev__pylint-6528`, both already among the same ten development task IDs.
The sklearn patches were reused byte-for-byte from
[`context-takeover`](../2026-10-11-context-takeover/); no sklearn model requests
were made in this run. Only the three Pylint agents continued, with the same
maximum of 12 additional source operations each. They used 9, 3, and 2 operations,
respectively, plus a finish request each.

## What the agents received

Each Pylint agent resumed its own saved native Responses history with its own
patch already applied. The added feedback contained only that condition's
results from the unchanged repository test command:

```text
python -m pytest -q tests/test_self.py -k "recursive or regex_paths_csv_validator"
```

The unchanged source passed all five selected tests. Before correction, Full
History and Receiver-aware Summary each passed three and failed two; HandoffSieve
passed five. After correction, all three passed five. The original test source
revision was restored and verified in an isolated container; the candidate
patches did not alter the tests or fixtures. No evaluator test patch, reference
repair, or hidden acceptance result was sent to the agents. See the
[original feedback](../2026-10-11-context-takeover/visible/pylint-dev__pylint-6528.json)
and [post-correction visible checks](visible/pylint-dev__pylint-6528.json).

The visible checks alone do not establish issue resolution. Independent final
acceptance came from the pinned official grader, which accepted all six patches;
both gold controls passed and both unchanged controls failed, with no reported
infrastructure failure. The reports are in
[`upstream/`](upstream/), with the
[grading workflow](https://github.com/LikkIui/handoff-sieve/actions/runs/38115509367).
The original official outcomes remain in
[`context-takeover/upstream/`](../2026-10-11-context-takeover/upstream/).

## Protocol correction and accounting

The preceding [`context-repair`](../2026-10-11-context-repair/) attempt made three
requests rejected with HTTP 400 before a model response. It replayed raw saved
response objects containing nullable wire fields. This separate v2 run reconstructs
those output items through the OpenAI SDK with `exclude_none=True`, matching the
live agent's serialization. It retains the original call IDs and encrypted
reasoning, and appends the real final finish acknowledgement before the new
feedback. The failed attempt and its requests remain preserved.

This run made **17 completed API requests**, with **391,649 provider-reported
tokens**. The three rejected requests have no reported usage; their billing and
token consumption are unknown. There were no automatic API retries. These 17
requests are three continuation episodes on one existing task, not 17 new tasks.

The source takeover made 84 completed requests and reported 856,754 tokens across
two tasks and three conditions. This run reused its histories and contexts. The
related ten-task selection-only stage made ten requests and reported 102,645
tokens; it produced nine valid packets and rejected one task for missing
evidence. Earlier researcher and summary preparation costs are outside the
correction figures above. Those stages must remain separate when comparing total
costs; provider usage is not a bill.

## Interpretation

The results show that observed test feedback can expose and repair regressions
in these saved agents. They do not isolate the effect of source grouping from
other development changes, establish statistical significance, or show that
HandoffSieve outperforms the strong summary. After correction all conditions
tie at 2/2, and the sklearn candidates contribute reused results. The fixed
200-task formal evaluation is not represented by this run. Detailed counts,
patch hashes, and before/after outcomes are in [summary.json](summary.json).
