# Rejected native-history replay diagnostic

Three correction requests received HTTP 400 before model output. The stored
diagnostic Responses included nullable output fields; replaying those raw
objects differed from the live agent's SDK serialization with `exclude_none`.

These are protocol failures, not three failed issue repairs. No response usage
was reported, so billing/token consumption is unknown. Requests and errors are
preserved; no candidate was substituted or silently retried in this directory.

The separate `../2026-10-11-context-repair-v2/` run reconstructs output through
the SDK and continues the same native histories with original-test feedback.
Its replay was checked against the exact input of existing successful next
requests before calling the API again.
