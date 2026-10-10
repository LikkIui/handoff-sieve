# HandoffSieve 0.3.0a3 offline performance audit — 2026-10-04

Scope: read-only source inspection and isolated scripts in `work/`; no provider API call, product source edit, version change, or publication. Source commit: `3a8d608a47c58c31c093f27d1aac485840c3dba3`. No applicable AGENTS.md was found in the project or ancestor workspace paths.

## Method

Windows 11 (10.0.26200), Python 3.13.2, Pydantic 2.13.5, tiktoken 0.14.0 in the existing project virtual environment. Each operation has one untimed warmup followed by three independent measured calls. Fixtures have one required architecture decision plus N unique classified evidence messages, each about 145 content characters and explicit task/state metadata. A generous 1,000,000-token budget ensures all tested evidence is retained; this measures selection overhead rather than gaining speed by dropping useful state. Source construction is outside timings. Whole `compile_handoff` calls include validation, selection, policy pipeline, re-selection, final public packet construction and counting. Normalization, preparation, and artifact merge are separately measured local operations. No framework/model execution is included.

Samples on a workstation vary considerably in the compiler tests; these are reproducible local measurements and complexity evidence, not release SLOs, provider latency, CI performance, or p95 claims. JSON records preserve all samples.

## Findings

### P1 — preferred-section selection is quadratic twice

Locations: `src/handoff_sieve/compiler.py:528`–`552` and `:778`–`785`.

The first selection pass reconstructs every previously selected message into a new packet for every new candidate. The post-pipeline pass deep-copies the entire growing packet for every candidate. Both reserialize and recount the entire JSON packet. This creates roughly quadratic model construction/deep-copy/serialization work even when every candidate obviously fits.

| Evidence items | Full compile, evidence preferred (median) | Full compile, same evidence required (median) | Retained output |
|---:|---:|---:|---:|
| 100 | 162.0 ms | 41.2 ms | 101 items, 6,395 estimated tokens |
| 1,000 | 52,428.6 ms | 451.7 ms | 1,001 items, 63,545 estimated tokens |
| 5,000 | deliberately not run | 2,382.9 ms | 5,001 items, 318,545 estimated tokens |

500 preferred items also took 12,997.7 ms median (8,630.7 / 12,997.7 / 13,139.8 ms). 1,000 preferred samples were 29,773.4 / 53,131.3 / 52,428.6 ms. Required state and all evidence remain present; the 1,000-item output token counts are identical between required/preferred classification of the contract. Contract declarations do not change source item kinds or canonical packet field ordering.

**Practical tight-budget check:** with the same 1,000 evidence candidates but `max_tokens=4000` (matching the README example), full `compile_handoff` took **3,447.3 ms median**, samples **1,190.2 / 3,447.3 / 4,267.9 ms**, after one 1,191.8 ms warmup. The 1,001 source items became **63 retained items: one complete required decision plus 62 preferred evidence items**, **3,992 estimated tokens**, 938 preferred omissions before the pipeline and zero after. Counting made **1,069 calls**, scanned **16,580,569 UTF-8 bytes**, and emitted **15,965-byte** receiver JSON. Each repetition produced identical canonical text, kept the required decision unchanged, respected the hard budget and left source state unchanged; the isolated Approx selector produced the same text. Thus 52.4 seconds is a generous-budget all-retained stress case, not a claim about everyday 4,000-token handoffs. The practical budget limits the growing retained prefix, but the implementation still repeatedly reconstructs that prefix for all remaining candidates. Sample variation remains substantial, so do not present these as a stable service-level latency. Raw records: `work/performance-tight-budget-20261004-results.json`; script: `work/performance_tight_budget_20261004.py`.

Recommendation: keep one local working packet, build/sanitize each candidate once, append/count/rollback instead of repeated full deep copies. For the default UTF-8 counter, canonical fragment byte lengths plus array separators can give exactly the same `ceil(bytes/4)` budget decision in linear time. Recheck independently after transformations. Arbitrary custom counters and tiktoken need exact whole-text fallback unless their counter explicitly exposes a safe compositional capability; BPE token counts must not simply be added. **TiktokenCounter inherits ApproxTokenCounter: `isinstance(counter, ApproxTokenCounter)` is not sufficient to select this fast path.** Use a strict concrete-type check or an explicit supported counter capability. Preserve required-section completeness, contract section order, skip-large/continue-small behavior, reporting, source isolation and final canonical-text hard-budget check.

The 1,000-item full compilation called `count_text` 2,007 times and scanned 255,962,275 UTF-8 bytes, while its final receiver JSON was only 254,179 bytes. The 500-item cProfile run took 32.575 s under profiling: `_packet_from_selected` accumulated 15.821 s, `_fit_processed_packet` 15.333 s, recursive deepcopy 14.456 s, and `_count_packet` only 1.750 s. Repeated public Message construction also caused 255,510 default-factory signature inspections in this Pydantic version. Optimizing the tokenizer alone leaves most observed work intact. Do not add these inclusive cProfile times together.

Using tiktoken instead of Approx, 100/500 preferred items took 822.1 ms / 19,095.1 ms median; this is still entirely local CPU work and does not represent a billed/model API call.

### P2 — artifact continuation merge is quadratic for distinct files

Location: `src/handoff_sieve/adapters/_packet.py:64`–`66`.

`artifact not in result` scans the whole output list using Pydantic model equality for each candidate. Distinct artifact names are a common workload, yet no name index is used.

| Distinct artifacts | Median | Samples |
|---:|---:|---|
| 100 | 11.4 ms | 10.2 / 11.4 / 11.9 ms |
| 1,000 | 980.2 ms | 964.1 / 980.2 / 999.0 ms |
| 5,000 | 24,960.2 ms | 24,941.8 / 24,960.2 / 24,981.0 ms |

Recommendation: use `dict[name, list[Artifact]]` buckets and apply the existing equality test only inside the same-name bucket. Retain inherited/current filename replacement, first-occurrence order, duplicate removal and independent public copies. Avoid replacing current model equality with naive JSON-string hashing: Python/Pydantic can treat numeric values `1` and `1.0` as equal despite different JSON spellings. Same-name many-version workloads remain a worst case; do not infer which conflicting current version should win.

### P2/P3 — normalization and compilation repeatedly copy public state

Locations: `src/handoff_sieve/normalization.py:172`, `:194`/`:204`, `:217`, `:294`, `:325`; `src/handoff_sieve/compiler.py:454`, `:670`–`:717`; `src/handoff_sieve/pipeline.py:164`.

The normalizer sanitizes the whole source, creates independent copied normalized messages, then deep-copies the whole original envelope and immediately replaces its copied message list. `compile_history` adds additional outer sanitization and dumps/revalidates the completed compilation. Sanitization at an untrusted boundary is valuable; some later whole-envelope copies are redundant.

| Items | Normalize median | prepare_sender_state median |
|---:|---:|---:|
| 100 | 25.8 ms | 7.2 ms |
| 1,000 | 194.4 ms | 73.9 ms |
| 5,000 | 1,110.1 ms | 354.3 ms |

These operations are approximately linear and lower priority than the quadratic compiler. A local proof-of-concept removes only the normalizer's final discarded message deep copy. **Independent review found a legal counterexample: a mutable non-JSON object inside `HandoffEnvelope.metadata` (an `Any` field) aliases the original caller when this final envelope copy becomes shallow; the current deep-copy implementation isolates it. Do not apply this shallow-copy candidate as a patch.** A future optimization may copy metadata/artifacts deeply while avoiding the discarded original message copies, with equivalent isolation tests. Do not silently narrow the public API to JSON-only values, or replace public dump/validate boundaries wholesale with shallow copies: private protected/control fields must never propagate from caller-supplied state.

### P2 — simple scale coverage is absent from the existing displayed latency

Locations: `benchmarks/run.py:544`, `benchmarks/results.json:28`; `README.md:398`.

The README's saved p50 2.703 ms / p95 5.842 ms describes a small existing policy-pipeline fixture. It neither covers a large receiver-contract preferred-selection loop nor the full normalization/compile call. That wording is already explicitly pipeline latency, so this is a coverage gap rather than a false claim. Add a small separate repeatable scale diagnostic for 100/1,000 selected items and distinct artifacts, plus output equivalence assertions. Avoid making workstation microtiming a flaky CI threshold or constructing a new benchmark platform.

## Boundaries

`prepare_sender_state` showed linear scaling and preserved all unique evidence in these fixtures. The packet renderer's compact serialization and SDK filter's captured immutable receiver text are sensible existing optimizations. No need for new adapters, protocols, enterprise policy infrastructure, LLM summarization, GPU use or massive benchmark collection to address the measured hot spots.

## Isolated candidate measurements

`work/performance_candidates_20261004.py` does not modify product code. The selector candidate models **only the first pre-pipeline greedy selection pass and only default Approx UTF-8 counting**. It is not a complete replacement compiler and does not imply the same speedup for end-to-end adapter/model calls. The reference uses the actual `_packet_from_selected` and `_count_packet` functions. Sixty deterministic random Unicode/metadata/tag/variable-budget fixtures yielded byte-identical canonical receiver JSON; source content remained unchanged. 100/500/1,000 all-retained fixtures were also compared exactly. Required decisions remained complete.

| Local operation | N | Reference median | Candidate median |
|---|---:|---:|---:|
| First-pass selection | 100 | 95.4 ms | 2.38 ms |
| First-pass selection | 500 | 8,437.2 ms | 43.4 ms |
| First-pass selection | 1,000 | 33,708.2 ms | 98.0 ms |
| Distinct artifact merge | 100 | 11.4 ms | 0.53 ms |
| Distinct artifact merge | 1,000 | 980.2 ms | 7.23 ms |
| Distinct artifact merge | 5,000 | 24,960.2 ms | 39.89 ms |
| Normalize ordinary headings | 100 | 25.8 ms | 18.1 ms |
| Normalize ordinary headings | 1,000 | 194.4 ms | 179.3 ms |
| Normalize ordinary headings | 5,000 | 1,110.1 ms | 891.4 ms |

Artifact equivalence fixtures explicitly include same-name `1` versus `1.0` content, inherited/current same-name override, exact duplicates and conflicting current versions. Independent verification additionally covered `True == 1`, output/input artifact isolation, 32 canonical full-compiler comparisons, and large-skipped/small-later preference ordering. It also demonstrated that an Approx subclass can disagree with UTF-8 counting (521 tokens against a 300 budget), BPE is not additive (`hello` versus separately counted `hel` + `lo`), and a policy that expands preferred state must trigger the second budget selection. **The second pipeline budget pass must remain.** The normalizer candidate compares complete normalized envelope/report equality and message input independence for JSON-compatible fixture shapes, but independent review found the metadata Any aliasing counterexample above; its speed measurement is diagnostic only, not a recommended patch.

All samples: `work/performance-audit-20261004-results.json` and `work/performance-candidates-20261004-results.json`. Attribution: `work/performance-audit-20261004-profile.txt` and `.prof`. Product Git working tree remained clean after these measurements. Candidates remain private work scripts, not validated product implementations.

## Proposed next version scope

An a4 performance/quality increment should first replace preferred-selection repeated construction/deep copies with exact-output greedy selection, then index artifact continuation by name. Normalizer copy changes need further design to preserve metadata/artifact Any isolation; the measured shallow-copy prototype is explicitly not recommended for shipping. Retain all current contract/private-boundary regression checks and add deterministic reference-equivalence cases for default and custom counters, required overflow, transformations that change packet length, Unicode, later-small-after-large preferences, same-name artifacts and caller-state isolation. Keep both pre-policy and post-policy selection and final whole-packet exact count. Keep this a small focused increment; no new framework adapters or platform work is warranted by these findings.
