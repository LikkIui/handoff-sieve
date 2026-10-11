# Coherent source-context takeover retest

Two selected development failures reuse the same frozen sender states and
source commits. All three conditions receive 24 source actions and the same
common prompt. Each context carries its task goal; the prompt does not repeat
the packet goal. Full history and strong summaries are reused, and selected
packets come from the coherent-source selector retest. No new distinct tasks.

| Condition | Official acceptance | Mean estimated handoff tokens | New continuation calls | Reported continuation tokens |
|---|---:|---:|---:|---:|
| Full history | 1/2 | 5,605 | 30 | 376,040 |
| Strong receiver-aware summary | 1/2 | 1,508 | 31 | 259,957 |
| HandoffSieve | 2/2 | 2,166 | 23 | 220,757 |

Both tasks' gold/unchanged controls are valid, and all candidate patches apply.
Every condition solves sklearn; only HandoffSieve solves Pylint in this run.
This small failure-focused retest supports further development, not a general
success-rate or superiority claim. Random generation and multiple configuration
changes prevent attributing the difference solely to source windows.

The 84 new continuation calls report 856,754 tokens. Preparation and shared
research are reused and excluded here, so this is not a total-cost comparison.
Earlier handoff sizes used a different task-goal boundary and cannot be pooled.

`visible/` contains only original repository tests: unchanged source and the
selected packet patch pass; full/summary patches fail. That condition's own
output enters a separate correction run. Hidden acceptance is in `upstream/`
and was not provided to those agents. Before-repair candidates remain intact.
