# RC-01 runnable fixture

This directory turns the RC-01 comprehension pilot into a local executable
task. It has not been run by a provider and contains no provider result.

Only `starter/` is the receiver workspace. `acceptance.py` stays on the host
side and must never be copied or mounted into that workspace.

The starter contains the public API and data type, with every implementation
entry point left as a stub. The acceptance checks exercise behavior offline;
there is no checked-in reference solution.

`python -m evals.takeover.run_runnable_openai` is inert and reports
`{"status": "not_run"}`. A provider run requires the full explicit gate
`--run --model MODEL --output NEW_FILE`; the output path must not exist.
The receiver returns strict JSON with one `pagination_py` field. Each condition
is written into its own temporary copy of `starter/`, and the host invokes the
hidden checks in a child process with a timeout and common provider credentials
removed from that process's environment. The hidden checker and task catalog
are never copied into the receiver workspace or included in its model input.

The child process is crash and interpreter-state isolation, not a security
sandbox. Generated Python retains the filesystem and network permissions of
that process. Use this runner only for controlled evaluation candidates in an
appropriately restricted host environment.
