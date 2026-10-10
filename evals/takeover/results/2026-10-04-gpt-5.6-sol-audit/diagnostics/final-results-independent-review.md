# Independent result review — completed 2026-10-05

Scope: public `0.3.0a3`, source `3a8d608a47c58c31c093f27d1aac485840c3dba3`. This review reads recorded responses and the original public runner/checkers. It does not change core, graders, inputs, or headline scores. No provider calls were made by the reviewer.

## Main 20-task suite: original scores retained

| Condition | Successful / scheduled | Provider responses completed | Provider timeouts | Successful / completed responses | Approx handoff tokens | Returned provider total tokens |
|---|---:|---:|---:|---:|---:|---:|
| Full History | 17/20 (85%) | 18 | 2 | 17/18 (94.44%) | 15,025 | 34,541 |
| Naive Summary | 16/20 (80%) | 18 | 2 | 16/18 (88.89%) | 9,792 | 63,032 |
| HandoffSieve | 16/20 (80%) | 18 | 2 | 16/18 (88.89%) | 6,773 | 29,644 |

The completed-response fractions are descriptive only; keep timeouts in the scheduled denominator. The 15 tasks with all three completed responses score 14/15, 13/15, and 13/15, respectively. This paired subset is also descriptive, not a replacement score or non-inferiority proof. One trial on 20 curated public tasks is insufficient to claim unchanged general downstream success.

HandoffSieve reduces the original full-envelope estimate by 54.92%. This is not all semantic selection: compact serialization of the same full envelope separately reduces it to 13,213 tokens; the packet is 48.74% smaller than that control. The compact full-envelope control was not run against the provider.

Naive Summary has 20 successful summary-preparation calls in addition to 20 receiver attempts. Its reported 63,032 total includes 31,127 preparation tokens and 31,905 available receiver tokens. No summary-preparation timeout occurred. All three conditions use the same public starter/task prefix; the summaries for the disputed tasks preserve the supplied requirements.

Available receiver input tokens are Full 16,338, Summary 12,015, Sieve 10,547; Summary preparation adds 20,792 input tokens. Each receiver group has missing usage on two different timeout tasks, so these available sums are not like-for-like billing comparisons. Completed receiver request medians were 78.40s, 66.92s, and 84.67s; this single gateway run does not show an end-to-end Sieve latency win.

### Timeout ledger

- Full History: `rc06_http_cache_key`, `rr03_retry_after_review`.
- Naive Summary receiver: `rr01_cursor_review`, `pe03_timezone_migration`.
- HandoffSieve: `rc07_refresh_rotation`, `rr03_retry_after_review`.

All six are `provider_error:model_timeout` at about 180s, without automatic retry or returned usage. They are delivery/provider failures, not executed-code failures.

### PE-02: one real model mistake plus an ambiguous bare flag

Public requirements (`evals/takeover/runnable/taskpack.py:576–585`) specify modes auto/always/never, legacy `--no-color` → never, conflicting or malformed input → ValueError, default auto. Public starter (`taskpack.py:99–106`) only specifies `parse_color_mode(argv: Sequence[str]) -> str`. The shared recorded prefix contains that starter and general goal, but never explicitly states that bare `--color` must have an argument.

The hidden validator (`expanded_acceptance.py:435–470`) checks conflicting explicit `--color auto --color never`, and invalid bare `--color` followed by invalid `--color sometimes`.

- Full History fails the conflicting explicit modes check. Its `set_mode` uses `mode != "auto"` as the indication that a mode was explicitly selected; consequently explicit auto is incorrectly treated as the unset default. This is a genuine implementation mistake under the public conflict rule.
- Naive Summary preserves conflict/malformed requirements; its implementation repeats that same conflict mistake. It also invents bare `--color` → always, giving two failed check groups. This is not evidence that summarization lost the conflict requirement.
- HandoffSieve passes conflicts but fails the validator's first invalid input, bare `--color`. Bare-flag semantics are underspecified in the public input; accepting a bare switch is a plausible CLI convention. However, inspection of the actual source also shows `--color sometimes` → always: it consumes the following parameter only if it is one of the three allowed modes, then ignores unknown arguments. That is a genuine violation of the allowed-mode/malformed-input requirement. The recorded check stops at the bare-flag failure, concealing this second defect. Therefore the whole PE-02 Sieve failure must **not** be excused as fixture ambiguity.

Evidence: `live20/pe02_cli_color.jsonl`, observations 2–4, including exact `receiver_input`, `raw_output`, `naive_summary_raw_output`, and check details. Recommend making required-value syntax explicit before future runs; retain this original failure unchanged.

### PE-07: the evaluated row schema was absent from actual inputs

Public starter (`taskpack.py:133–139`) declares only `build_manifest(root: Path, output: Path) -> list[dict[str, object]]`. Public task requirements (`taskpack.py:637–646`) say regular files, exclude `.git`/`*.tmp`/output, POSIX-sort paths, canonical JSON plus newline, and returned rows equal written rows. They do **not** specify row field names, byte size, or SHA-256. Inspection of all three exact recorded receiver inputs confirms those requirements are absent; Sieve preserves every supplied active requirement.

The catalog (`evals/takeover/TASK_CATALOG.md:218–229`) does describe byte size and lowercase SHA-256, and the host-only reference (`taskpack.py:323–340`) contains `path`, `size`, `sha256`. But the README (`evals/takeover/README.md:40–41`) expressly states provider receivers cannot access that directory or `TASK_CATALOG.md`; `taskpack.py:3–5` states only public starter files are shown, with reference files excluded. They are not part of this provider's context.

The validator (`expanded_acceptance.py:684–735`) indexes `row["size"]` and `row["sha256"]`. Full History happens to infer both fields and passes 4/4. Summary and Sieve produce correct SHA-256/path rows, exclusions, written/returned agreement, and newline formatting, but omit undeclared `size`. Both fail `content_and_hash` and `repeatability` with `KeyError: 'size'`; the repeat check reruns the same `content()` precondition, so these are two failed groups with one schema mismatch, not two distinct behavioral failures. The Summary explicitly notes that supplied state does not define row fields or hash algorithm.

This is an input/oracle contract gap; current evidence cannot establish Sieve information loss. Future runs should publish the exact row schema and hash algorithm as common requirements to every condition. Do not change this run's original scores or silently delete PE-07 from headline results.

Evidence: `live20/pe07_file_manifest.jsonl`, observations 2–4. Existing catalog PE-02 also describes a different `--output`/`--format` migration from the runnable color task, so catalog prose is not a substitute for exact receiver input.

## Synthetic selection stress: a mechanism demonstration

18 attempts, three invented tasks × two trials × three conditions, no automatic retries:

| Condition | Successful / scheduled | Provider completed | Provider errors | Returned total tokens |
|---|---:|---:|---:|---:|
| Full History | 6/6 | 6 | 0 | 4,741 |
| Current HandoffSieve | 0/6 | 6 | 0 | 3,957 |
| Explicit receiver-selection prototype | 5/6 | 5 | 1 | 3,287 |

The prototype timeout is `synthetic_utf8_batch`, trial 1, ~180s, with no usage. All five returned prototype responses pass. All six current-core responses lack the deliberately budget-displaced task policy and fail host behavior checks. This supports explicit receiver-specific item selection **before** FIFO budget packing; it is not a real-user success-rate estimate or evidence that the prototype is already a public product feature. The fixture author supplies selection tags and deliberately places irrelevant preferred material before needed policy. PE-02/PE-07 contract gaps in the main suite do not affect this independently specified mechanism test.

## Real continuous SDK relay

Verified `relay-live-20261005.json`: four real HTTP/model calls, status completed, coder's actual write/check tool 5/5, reviewer's independently executed tool 9/9, final verdict matches host probe, `workflow_success=true`. Both first receiver inputs exactly match their canonical packets and omit launch notes. Available usage: 2,955 input + 319 output = 3,274 total tokens. Source→packet estimates: researcher→coder 2,038→237; coder→reviewer 564→542. The researcher is a deterministic public fixture; coder and reviewer are real model agents. This establishes one actual two-hop workflow, not a comparative downstream-success or billing benchmark. No corrected write or automatic retry was needed.

## Separate amended-protocol follow-up

Completed `clarified-tasks-live-20261005`, eight calls: two summary preparations and six receivers, all with returned usage, no timeout or retry. This targeted follow-up does not replace the original 17/20, 16/20, 16/20 results or generalize to all tasks.

The PE-02 amendment only states that `--color MODE` requires a mode and that values outside auto/always/never raise ValueError; existing default/conflicting-mode requirements still apply. It adds no algorithm or explicit-auto example. The PE-07 amendment only states that rows contain `path`, integer byte-length `size`, and lowercase hexadecimal SHA-256 `sha256`; existing sorting/serialization/exclusion requirements still apply. No hidden fixture instances, expected case answers, or reference code are supplied.

Independent protocol checks confirm both original Full and Sieve context payloads are byte-identical to the corresponding `live20` actual contexts, with matching SHA-256 hashes. Original-prefix and amendment hashes match. All three completed receiver observations for each task have the same amended public prefix, exactly matching `protocol.json`; summary preparation quotes that same prefix, and actual summaries preserve the clarifications.

| Condition | Successful / two scheduled tasks | PE-02 checks | PE-07 checks | Available total tokens |
|---|---:|---:|---:|---:|
| Full History | 1/2 | 3/4 | 4/4 | 4,312 |
| Naive Summary | 2/2 | 4/4 | 4/4 | 6,893 |
| HandoffSieve | 2/2 | 4/4 | 4/4 | 2,609 |

Full History PE-02 still treats current `mode == "auto"` as unset; it accepts the conflicting explicit sequence `--color auto --color never`. The recorded checker reports that exact conflict, so this is a real model implementation mistake, despite the clarified required-value syntax. Both Summary and Sieve now pass the unchanged PE-02 checker. All conditions pass the unchanged PE-07 checker with the published row fields. This is consistent with an original input/oracle gap; single new stochastic outputs do not prove causality or stable superiority.

The private supplemental wrapper initially recorded `task_exit_codes: [3,3]`. This is a metadata naming error: the original public `run_batch` (`run_runnable_openai.py:1343`) returns **observation record count**, not a process exit code. Both matching `run_completed` footers explicitly show `records_written: 3`; all six provider observations have `status=completed`, while Full PE-02 correctly remains a failed behavioral observation. The wrapper's record-count name is corrected separately with an audit note, preserving the original misnamed field. Do not infer run failure or six passed tasks from `[3,3]`.

Evidence: `clarified-tasks-live-20261005/protocol.json`, `calls.jsonl`, `aggregate.json`, and the two task JSONLs. Available usage is 13,814 total tokens, with zero timeout usage gaps.

## Independent request/usage ledger

| Run | Actual attempted provider calls | Responses with available usage | Timeouts with unavailable usage | Available total tokens |
|---|---:|---:|---:|---:|
| Main suite + connectivity probe | 81 | 75 | 6 | 127,268 |
| Synthetic selection stress | 18 | 17 | 1 | 11,985 |
| Continuous SDK relay | 4 | 4 | 0 | 3,274 |
| Separate two-task clarification follow-up | 8 | 8 | 0 | 13,814 |
| **Final total** | **111** | **104** | **7** | **156,341** |

The prior 103-call / 142,527-token total was the intermediate snapshot before the eight-call clarification. Main: 1 probe + 20 summary preparations + 60 receiver attempts. The 51-token connectivity probe is included once. Mock transport and prepare-only outputs are excluded entirely. All recorded available usages satisfy total=input+output. Timeout billing is unknown, so available usage is neither complete actual consumption nor invoice cost. The requested gateway alias is `gpt-5.6-sol`; accepting/echoing an alias does not independently establish upstream model identity.

## Recommendations

1. Prioritize the independently demonstrated compiler/merge quadratic behavior and two compatibility bugs for the small a4 patch; preserve budgets, copy isolation, final transform pass, and arbitrary token-counter semantics.
2. Make receiver-specific item selection before the budget the next visible product feature. Demonstrate coder/reviewer selecting different facts within the same task using explicit tags/keys; retain original sender history application-side.
3. Carry the PE-02 flag value syntax and PE-07 row-schema clarifications into future public task definitions, keeping the already completed eight-call amended follow-up separately labeled and retaining original fixture/results. Do not inflate this into a new benchmark platform.
4. Keep all scheduled failures in future headline tables and separate provider delivery errors, model implementation errors, and input/oracle gaps. No general success-equivalence claim follows from this one trial.

Exact artifacts: `live20/aggregate.json`, `live20/audit.json`, `live20/calls.jsonl`, `selection-stress/aggregate.json`, `selection-stress/receiver-calls.jsonl`, `relay-live-20261005.json`.
