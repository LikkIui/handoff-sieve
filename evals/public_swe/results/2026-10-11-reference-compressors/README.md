# Pinned original compressor output diagnostic

Two actual TypeScript implementations ran on sixteen byte-identical existing
development sender states. No receiver model or grading was run for these two
outputs. These results measure returned content and size, not takeover quality.

`actual-results.json` retains pinned URLs, source SHA-256, runtime versions,
options, sender/contract hashes and every returned output. `summary.json` counts
the complete goal plus returned JSON using the same built-in estimate. Returned
reference counters are retained separately; no output was clipped afterward.

To reproduce, download the three source files identified by the manifest into
`work/reference-review-20261011`, install TypeScript 5.9.3 in its `runtime`
directory, and construct `inputs.json` from the sixteen original sender and
contract files in `2026-10-11-development-remaining20`. `material_budget` is 4,000
minus the count of `{"goal": original_goal, "handoff": {}}` using compact JSON.
Save `run-originals.cjs.txt` as `work/run-reference-compressors.cjs` and run it
with Node. The runner verifies source hashes before transcribing types to JS.
The original comparison used Node v24.15.0 and TypeScript 5.9.3. Source files are
references, not vendored product dependencies.

See [code review and limits](../../../../docs/design-references-2026-10-11.md).
