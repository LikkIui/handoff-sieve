# Twenty-task controlled takeover run

This directory is the complete v0.3 evaluation checkpoint: 20 executable
takeover tasks, one trial per task, and the same requested model
`gpt-5.6-sol` for all three conditions.

Calls used the OpenAI Agents SDK Responses transport through the
user-authorized OpenAI-compatible gateway at `compatible-openai-gateway.invalid`. The gateway accepted
the requested model name; these records cannot independently verify the model
actually served behind that name.

| Condition | Success | Handoff tokens, total (mean) | Provider tokens, total (mean) | Model calls |
|---|---:|---:|---:|---:|
| Full History | 18/20 (90%) | 15,025 (751) | 38,321 (1,916) | 20 |
| Naive Summary | 17/20 (85%) | 7,402 (370) | 55,596 (2,780) | 40 |
| HandoffSieve | 18/20 (90%) | 8,177 (409) | 28,757 (1,438) | 20 |

HandoffSieve matched Full History's downstream success while using **45.6%
fewer handoff tokens** and **25.0% fewer measured provider tokens**. Naive
Summary produced the smallest handoff text, but its separate preparation call
doubled model calls, used 45.1% more provider tokens than Full History, and
finished one fewer task successfully.

## Failures

Provider errors remain failures in the denominator, as defined before the run.
There was one model timeout in each condition:

- Full History: `rc07_refresh_rotation`;
- Naive Summary: `pe03_timezone_migration`;
- HandoffSieve: `pe07_file_manifest`.

The completed-output failures were:

- Full History: `pe07_file_manifest` failed two of four behavioral checks;
- Naive Summary: `pe01_streaming_csv` failed four of eight checks, and
  `rr03_retry_after_review` incorrectly requested changes to a valid candidate;
- HandoffSieve: `rr03_retry_after_review` incorrectly requested changes to the
  same valid candidate.

No failed condition was retried or removed. On the 19 conditions in each arm
that returned a model output, Full History and HandoffSieve each passed 18;
Naive Summary passed 17. The primary table still uses all 20 tasks.

## Grading correction

The first aggregate exposed two host-validator defects: the package-data probe
loaded `task_app` under a synthetic module name, and two reviewer prompts named
uppercase issue IDs while the oracle expected lowercase IDs. The validators
were corrected and the saved raw model outputs were regraded without another
provider call.

Nine observations changed across `pe04_package_template`,
`rr02_falsy_config_review`, and `rr04_csv_splitter_review`. Every changed row
contains `original_grading`, `grading_revision`, and `regraded_at`. The original
uncorrected files remain in the two source result directories named in
`aggregate.json`.

## Files and limits

An offline review on 2026-10-02 found that the summary preparation output for
`rr03_retry_after_review` is a final verdict JSON rather than a state summary;
the receiver repeats that incorrect verdict. The original summary prompt
included the receiver's output instructions without a separate data boundary.
Instruction interference is a possible explanation, not a confirmed cause.
Future runs quote those requirements as reference data and explicitly restrict
the preparation step to summarization. This checkpoint predates that change;
its raw outputs, counts, failures, and denominator are unchanged. The comparison
with Naive Summary therefore also reflects the behavior of that original prompt.

This checkpoint also predates compact default-field omission. Re-rendering
its 20 saved packets locally gives 6,773 estimated handoff tokens instead of
8,177 with identical public packet models. This is an offline format measurement;
it does not change this table's original provider usage or task success results.

`aggregate.json` is derived from the 20 JSONL files in this directory. Each
JSONL contains the exact receiver input, raw output, provider usage, model-call
count, and host-side checks. The test suite rebuilds the aggregate from these
records and checks the correction audit fields.

This is a small product benchmark with one trial per task. It supports the
project's core directional claim, but it is not a statistically stable estimate
across providers, models, or repeated stochastic runs.
