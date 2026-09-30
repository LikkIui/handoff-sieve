# Three-pilot controlled run — 2026-09-30

This directory records the first real-provider run of the three runnable
takeover pilots. All conditions used the requested model `gpt-5.6-sol`, the
same task prefix and starter files, a 180-second model timeout, and a
190-second outer timeout.

The calls went through a user-authorized OpenAI-compatible gateway at
`compatible-openai-gateway.invalid` using the OpenAI Agents SDK Responses transport. The raw runner
records identify the SDK family as `openai`; this note records the actual
gateway so the results are not mistaken for direct OpenAI API measurements.

| Condition | Success | Handoff tokens, total (mean) | Provider tokens, total (mean) | Model calls |
|---|---:|---:|---:|---:|
| Full History | 3/3 (100%) | 4,588 (1,529) | 8,873 (2,958) | 3 |
| Naive Summary | 2/3 (66.7%) | 1,469 (490) | 12,305 (4,102) | 6 |
| HandoffSieve | 3/3 (100%) | 2,190 (730) | 6,060 (2,020) | 3 |

Across these three tasks, HandoffSieve preserved the Full History success rate
while reducing handoff context by 52.3% and measured provider tokens by 31.7%.
Naive Summary produced the smallest handoff text, but required a preparation
call, used the most provider tokens overall, and failed PE-01.

PE-01's Naive Summary output passed 4/8 checks. It failed `csv_normal`,
`csv_empty`, `csv_unicode_quoting`, and `lazy_single_pass`. Full History and
HandoffSieve passed all 8 checks. RC-01 passed 7/7 under all three conditions;
RR-01 passed 3/3 under all three conditions. No condition retried.

These are three tasks with one trial each. They are a product checkpoint, not
a statistically stable benchmark. The next evaluation step is to add more
runnable takeover tasks before making a broad public claim.

`aggregate.json` contains the machine-readable summary. The three JSONL files
contain the exact receiver inputs, raw outputs, provider usage, and host-side
checks for each task.
