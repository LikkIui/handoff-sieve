# PE-01 runnable fixture

This directory turns the PE-01 comprehension pilot into a local executable
task. It has not been run by a provider and contains no provider result.

Only `starter/` is the receiver workspace. `acceptance.py` stays on the host
side and must never be copied or mounted into that workspace.

The starter preserves the existing JSON report behavior and leaves the CSV
serializer plus CSV routing branch unfinished. Host-side acceptance checks
normal output, an empty result, Unicode and quoting, lazy single-pass
iteration, JSON snapshots, unsupported formats, and input immutability. There
is no checked-in solution inside the receiver workspace.
