# Original-test feedback diagnostic: v2

Two previously used SWE-bench Verified development tasks, three context
conditions, the actual pinned mini-swe-agent DefaultAgent controller and fresh
source checkouts. All official positive/negative controls are valid. The model
and sender contexts are the same as the earlier source-only run; the controller,
prompt and step semantics differ, so the runs cannot be pooled or their changes
attributed solely to test feedback.

| Condition | Completed takeover / two cases | New receiver trials | New requests | Known new provider tokens |
|---|---:|---:|---:|---:|
| Full History | 0/2 | 0 | 0 | 0 |
| Strong receiver-aware Summary | 0/2 | 0 | 0 | 0 |
| Hybrid HandoffSieve | 0/2 | 2 | 29 | 304,869 |

**No candidate resolves either official task. No superiority or cost saving is
claimed.** Both official patch acceptance and completed takeover are recorded;
partial candidates after controller errors cannot become successful takeovers.

This is a separate correction for the two hybrid
test-argument failures, selected before inspecting official grading. Only hybrid
receivers are fresh; the two full-history and two strong-summary patches are
reused verbatim from v1, not new baseline trials. Django reaches real test
feedback after the interface fix. Sphinx has a provider request failure before
editing, with missing usage; it stays in the denominator. No automatic retry or
replacement of the primary v1 result occurs.


Original-test feedback reaches only its own receiver. The frozen suites are
Django forms_tests (680 tests) and two Sphinx autodoc modules (67 tests). Every
condition shares a 24-model-call, two-test-execution limit. Preparation and
research are reused with zero new calls; their historical usage is labeled,
not counted as new consumption. The default mini unrestricted Bash environment
is not used. The code checks the original controller's fixed SHA-256.

## What this resolves and what it does not

The primary six candidate files parse as Python and enter official tests. In
Full History, Django's original suite changes from failing to passing after
feedback; strong-summary Sphinx does the same. Yet their new issue behavior is
still incorrect. Official Django targets only partly pass, and Sphinx's target
cases do not pass. Strong-summary Django also has two maintenance regressions.
Passing an existing suite therefore cannot establish resolution of a new bug.

The next quality step is an issue-specific reproduction created from the public
issue, run before editing and again after editing, with original regression tests
retained. It should use the receiver's own real outputs, not grading answers.
We will not widen adapters, run the formal 200 tasks, or advertise this as a win.

## Evidence and publication

Public evidence contains candidate patches, hashes, generation counts and
official grading summaries. Complete requests/responses, encrypted reasoning,
trajectories and sender contexts stay local. The compatibility gateway's model
alias identity is unverified. Missing usage is unknown, not zero; reported
provider tokens are not an invoice. See `summary.json`, per-case `metrics.json`
and `upstream/workflow.json`. Previous failures remain unchanged.
