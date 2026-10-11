# Coherent-source selection retest

Ten real API selector calls reuse the frozen development sender states from
`2026-10-11-development-native`. These are zero new tasks and do not measure
downstream success. The implementation revision is in `run-manifest.json`.

| Measure | Indexed line catalog | Coherent source windows |
|---|---:|---:|
| Provider input tokens, all 10 calls | 148,511 | 98,066 |
| Provider total tokens, all 10 calls | 154,872 | 102,645 |
| Locally valid packets | 10/10 | 9/10 |

Input tokens fell 33.97% with shared message metadata and contiguous observed
code windows. This is selector preparation cost, not an end-to-end savings claim.
Packets retain more code context: the nine valid packets average 1,763 estimated
tokens. The previous ten averaged 1,118, with different valid denominators.

The pytest task was explicitly rejected because its original short research
did not observe the source behavior required by need 0. No fallback or automatic
retry was used. A previous valid reference plan did not prove that need was
semantically satisfied. Preserve this rejection and improve research evidence
before the remaining development cohort.

Raw requests/responses and compilation reports are included; no model credential
is recorded. `reproduce.py.txt` reproduces the paid calls, not fixed outputs.
