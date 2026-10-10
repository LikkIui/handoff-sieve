# First sequential-tool run on ten public development tasks

Ten distinct original SWE-bench Verified issues, one trial, three handoff
conditions: full research history, strong receiver-aware summary, and
model-selected original HandoffSieve spans. These are real public repository
tasks, separate from the project's synthetic fixtures and integration attempts.

The researcher had three read-only source operations. Each independent coder
had eight source operations, followed by finish. Tools can list, search, read
and edit existing files; they cannot execute local tests. All three conditions
use the same issue, frozen source/research state, model and coder tool budget.
Source snapshots remained unchanged. Candidate generation is not success.

The executed version is recorded in `provenance.json`. Subsequent selector
changes do not retroactively change these results. Two model-selection plans
failed local validation; those failures remain in the denominator. Separate
corrective selection and takeover retests have their own directories.

The initial coder record's `steps_exhausted` field incorrectly reported false
after the budget-forced finish. Use `executed_tool_steps >= 8` to identify a
continuation that reached the limit; no raw records have been rewritten.

The upstream Linux workflow grades reference-fix and unchanged-source controls
before the generated patches. Its reports will be retained under `upstream/`.
Task success is determined by upstream FAIL_TO_PASS and PASS_TO_PASS tests,
not by a model's finish note. Empty patches and selection failures remain
failures; infrastructure errors are reported separately.

Token counts for handoff sizes are built-in estimates. Provider request usage
is reported separately; selector/summary preparation and shared research costs
are retained. This limited ten-task development diagnostic is not a formal
held-out comparison, a leaderboard submission, or evidence of general superiority.
No held-out tasks or hidden fixes/tests were supplied to the agents.
