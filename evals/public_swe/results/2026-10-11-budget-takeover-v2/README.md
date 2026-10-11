# Corrective xarray takeover with a budget-aware packet

The new HandoffSieve receiver solved `pydata__xarray-6721` under the pinned
official SWE-bench grader. Both controls behaved as expected. Full History and
Receiver-aware Summary also passed, using their original patches unchanged.
This is one corrective development case, not three newly matched trials or a
general advantage claim.

| Condition | Official acceptance | Handoff estimate | Preparation + continuation requests | Known provider tokens |
|---|---|---:|---:|---:|
| Full History (original baseline reused) | Passed | 8,843 | 15 | 227,924 |
| Receiver-aware Summary (original baseline reused) | Passed | 3,304 | 16 | 141,729 |
| HandoffSieve (new receiver, preparation reused) | Passed | 3,830 | 14 | 118,481 |

## What changed

The [original twenty-task attempt](../2026-10-11-development-remaining20/README.md)
rejected this handoff because essential content occupied 4,266 estimated tokens
against a 4,000-token contract. Budget-aware selection now sees the fixed
canonical packet cost (2,492), remaining source budget (1,508) and conservative
item insertion estimates. It produced a 3,830-token packet from the same sender
observations and unchanged goal. Essential material is not silently deleted;
final compilation still checks the complete canonical packet.

The [selection-only run](../2026-10-11-budget-selection-v1/README.md) made the
preparation request once: 18,184 reported tokens. This run reused that packet and
performed 13 completed receiver requests (100,297 reported tokens), with 12
source tool actions and a finish response. The receiver had the same maximum of
24 source operations and no local test tool. It did not receive other-condition
patches, reference repairs, test patches or hidden acceptance feedback.

## Cost and interpretation

The table includes summary/selection preparation and receiver continuation;
shared research is reused and excluded from all three rows. Reused costs are
shown for comparison, not charged again as new requests. Selection preparation
is already included in the separate eleven-state selection run and must not be
counted twice in cumulative usage.

On this case the HandoffSieve handoff is 56.69% smaller than Full History and
larger than the strong summary. Known preparation-plus-continuation tokens are
48.02% below Full History and 16.40% below the strong summary. These observations
include a new receiver generation after a selected development failure; they
do not isolate the mechanism, establish stable superiority or predict savings
on other tasks. The requested compatible-provider model alias does not verify
the underlying model identity; usage is not a bill.

The preceding [v1 transport attempt](../2026-10-11-budget-takeover-v1/README.md)
made one request that failed with `APIConnectionError`, before a model response
or tool action. Its token consumption and billing are unknown. It remains
separate and is not silently retried or treated as zero-cost execution.

This retake adds **zero new distinct tasks**. The original twenty-task result
remains Full History 7/20, strong summary 8/20 and HandoffSieve 5/20; this success
does not replace the original budget failure. The 200-task formal set is unused.

## Evidence

The [official workflow](https://github.com/LikkIui/handoff-sieve/actions/runs/38130861366)
accepted all three patches; gold passed and unchanged source failed.
[Upstream reports](upstream/), raw requests, hashes and
[final summary](summary.json) are retained. Frozen candidate reports still say
grading was pending at generation time; the final summary records the separate
official result. `summarize-reproduce.py.txt` audits patch bytes, reused
baselines, request usage and controls from the repository root. It needs no API.
`reproduce.py.txt` is the explicitly paid receiver reproducer.
