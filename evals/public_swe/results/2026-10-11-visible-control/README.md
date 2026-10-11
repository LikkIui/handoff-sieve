# Original-test feedback environment diagnostic

The request runs only existing Pylint tests from the public base checkout on
three preserved development patches and an unchanged-source control. It does
not load the full grading dataset, hidden test patch, or reference solution.

Attempt 1 rejected all containers before testing: the official image's initial
HEAD differed from the public task base commit. `attempt-1/` preserves the
invalid environment report and workflow provenance. This is not a candidate
failure and supplies no valid test feedback to a receiver.

The preparation fix restores and verifies the public base commit inside each
fresh container. Its separate retry request is in
`../2026-10-11-visible-control-retry/visible-request.json`.
