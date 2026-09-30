# Takeover evaluation scaffold

This directory is the small v0.3 evaluation track. It is separate from the
offline policy regression fixture in `benchmarks/`.

The default commands are offline and do not call a provider:

```bash
python -m evals.takeover.validate --validate
python -m evals.takeover.run_openai
python -m evals.takeover.run_runnable_openai
python -m evals.takeover.run_runnable_suite
```

Without `--run`, all three commands report `status: not_run`. Provider
execution requires the explicit combination `--run --model MODEL --output
NEW_FILE`, an `OPENAI_API_KEY`, and the optional OpenAI dependency. The runners
refuse to overwrite an output file. Unit tests use fake responses to test
plumbing, but fake responses must never enter published evaluation results.

The three checked-in JSON fixtures are a **plumbing and handoff-comprehension
pilot**. Their structured answers can validate prompt construction, condition
fairness, record capture, and grading, but they do not require an agent to edit
code or execute a plan. They therefore cannot support the product claim about
downstream takeover success. That claim requires the isolated runnable tasks
and hidden behavioral validators described in `TASK_CATALOG.md`.

## Pilot shape

`manifest.json` contains one ready fixture in each route:

- researcher to coder;
- planner to executor;
- researcher to reviewer.

Each ready fixture contains
the full `HandoffEnvelope`, its `ReceiverContract`, one receiver instruction, a
small JSON output contract, and deterministic success checks. The runner must
never place `success_validator` or its expected values in the receiver prompt.
Provider receivers run without tools and receive neither this directory nor
`TASK_CATALOG.md`; graders stay on the host side.

The runnable suite now has 20 fixtures across the three routes. The original
three pilots remain the first real-provider checkpoint:

- `runnable/rc01_composite_cursor/` asks a coder to implement a pagination
  module, then checks seven behaviors in a fresh starter copy;
- `runnable/pe01_streaming_csv/` asks an executor to complete streaming CSV
  output while preserving exact JSON snapshots and single-pass iteration;
- `runnable/rr01_cursor_review/` asks a reviewer to assess an active candidate,
  while the host derives the blocker set by executing the candidate probes.

`run_runnable_openai` connects all three pilots to the same condition, summary,
record, and failure path. The same runner now discovers all 20 task ids from a
data-driven task pack. The receiver gets the public starter source in the
common task prefix and has no tools or access to the hidden checks. RC-01
returns one complete source file, PE-01 returns two, and RR-01 returns a strict
review object. Code candidates are written into new temporary starter copies;
RR-01 probes its fixed candidate and derives the blocker set on the host.

The additional 17 fixtures implement RC-02 through RC-07, PE-02 through PE-07,
and RR-02 through RR-06 from `TASK_CATALOG.md`. Their hidden validators execute
the returned implementation or active review candidate, and the test suite
proves every source-task oracle with a host-only reference implementation. This
is local fixture readiness, not a provider result.

Acceptance runs in a separate process with a timeout and common provider
credentials removed. This boundary contains crashes and hangs; it is not a
security sandbox and retains the subprocess's host filesystem and network
permissions.

The first three-pilot provider checkpoint is preserved in
[`results/2026-09-30-gpt-5.6-sol`](results/2026-09-30-gpt-5.6-sol/README.md).
Future invocations remain deliberately explicit and write a new file:

```bash
python -m evals.takeover.run_runnable_openai \
  --run --task-id rc01_composite_cursor \
  --model PINNED_MODEL_ID --output NEW_RC01_RESULT.jsonl \
  --model-timeout 180 --case-timeout 190 \
  --provider-label PROVIDER_OR_GATEWAY

python -m evals.takeover.run_runnable_openai \
  --run --task-id pe01_streaming_csv \
  --model PINNED_MODEL_ID --output NEW_PE01_RESULT.jsonl \
  --model-timeout 180 --case-timeout 190 \
  --provider-label PROVIDER_OR_GATEWAY

python -m evals.takeover.run_runnable_openai \
  --run --task-id rr01_cursor_review \
  --model PINNED_MODEL_ID --output NEW_RR01_RESULT.jsonl \
  --model-timeout 180 --case-timeout 190 \
  --provider-label PROVIDER_OR_GATEWAY
```

The complete 20-task provider checkpoint is saved in
[`results/2026-10-01-gpt-5.6-sol-20-task`](results/2026-10-01-gpt-5.6-sol-20-task/README.md).
It includes every task and failure, along with an auditable correction for two
host-validator defects found during result review. The single-task command's
`--help` output lists the complete runnable set.
The suite runner executes that set serially, preserves every completed task for
safe resume, and derives `aggregate.json` from the per-task JSONL records:

```bash
python -m evals.takeover.run_runnable_suite \
  --run --task-set expanded \
  --model PINNED_MODEL_ID \
  --provider-label PROVIDER_OR_GATEWAY \
  --output-dir NEW_RESULT_DIRECTORY
```

If a run is interrupted, repeat the same command with `--resume`. Configuration
drift or an incomplete task file stops the resume instead of silently mixing
results.

## Three conditions

Every task uses the same receiver model, parameters, instruction, tools, and a
fresh session. Only the handoff payload changes:

1. **Full history:** canonical JSON for the complete sender envelope.
2. **Naive summary:** a goal-aware plain summary generated from that same full
   state by a fixed prompt and model, capped at `ReceiverContract.max_tokens`.
3. **HandoffSieve:** `compile_handoff(...).packet.to_receiver_text()`.

The naive summary is generated during the real run. A hand-written summary is
not a valid baseline. Its preparation token usage must be recorded separately.

## Minimal result rules

- `downstream_success`: `1` only when every declared deterministic check passes;
  malformed output, timeouts, and provider errors are failures and stay in the
  denominator.
- `handoff_tokens`: tokens in the exact payload sent to the receiver.
- `prompt_tokens`: provider-reported receiver input tokens. Naive-summary
  generation input tokens are additionally reported as preparation tokens.
- `retry_count`: receiver calls after the first. Hidden grader feedback may not
  be used to rescue an answer.
- `event_count`: receiver model calls plus tool calls and tool errors.

Published rows must include task id, condition, provider, requested model
identifier (prefer a pinned snapshot), UTC timestamp, response id, provider
usage, exact receiver input, raw receiver output, and every grader check. The
OpenAI Agents SDK does not expose a reliable resolved-model-version field, so
the runner records the requested identifier and never guesses a version.
Aggregates are derived from those rows; conditions never carry a preselected
expected winner.

Without real provider response metadata, the only valid status is `not_run` and
no downstream-success percentage may be shown.
