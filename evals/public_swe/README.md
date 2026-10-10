# Public SWE-bench takeover development

This track uses original GitHub issues and source commits from the official
SWE-bench Verified dataset. It is separate from the project's 20 synthetic
takeover fixtures. It is a custom mid-task handoff experiment, not an official
SWE-bench leaderboard submission.

## Frozen data

- Dataset revision: `78f471bf655a3137b2e8a75af1501690ec009ec3`.
- 500 distinct original issues; 30 development, 200 held-out test, 270 reserve.
- Split seed and repository/difficulty distributions: [`data/manifest.json`](data/manifest.json).
- Source checksum is verified before import. Sampling never reads patches,
  model outcomes or acceptance results.
- [`data/development.jsonl`](data/development.jsonl) exports only issue text,
  task ID, repository and initial commit. Reference fixes, test patches and
  grading instructions are not exported to the agents.
- These are our custom partitions of the official test dataset, not new
  upstream official splits. The development runner refuses held-out tasks.

```bash
pip install -e '.[openai,public-eval]'
python -m evals.public_swe.dataset
```

The importer uses a small optional Parquet reader. No dataset package or model
runtime is added to the core installation.

## Real API handoff

```bash
python -m evals.public_swe.run \
  --model YOUR_MODEL --base-url YOUR_COMPATIBLE_ENDPOINT \
  --output evals/public_swe/results/NEW_RUN \
  --work work/NEW_SOURCE_CHECKOUTS
```

Supply the credential at the hidden prompt or through `OPENAI_API_KEY`. It is
never stored in call records. Calls use the Responses API with automatic
retries disabled. `--git-proxy` optionally configures public source fetching.

A read-only researcher investigates the original checkout with three source
tool actions, followed by a request to finish its findings. Its actual history
is frozen. Three independent coder checkouts then receive full history, a
strong receiver-aware model summary, or HandoffSieve's model-selected original
spans. Summary and selection have the same contract and 4,000-token estimated
handoff budget. Each coder has at most eight source tool actions.

Portable tools provide listing, literal search, bounded reads and exact source
edits. They do not execute local tests or shell commands. This initial harness
therefore tests a limited source-editing agent, not a full SWE-agent system.
Agents use sequential native Responses function calls and return actual tool
outputs before requesting the next operation. Every executed action consumes
the common tool budget. Bad actions and tool errors remain in the history.
Candidate generation is **not** task success. This follows the
[official function-calling flow](https://developers.openai.com/api/docs/guides/function-calling).

The first two integration runs used JSON action text. Their raw attempts are
retained, including failures and interruptions. They are development
diagnostics and must not be pooled with the sequential-tool run as independent
trials of one frozen implementation. `--source-cache` may reuse a clean source
checkout only after its initial commit is verified; model histories and
candidate edits are never reused by this option.

Requests, parsed Responses, original history, contract, selection plan,
continuation and generated patch are saved. Shared research cost, preparation
cost and continuation calls are kept separately. Token sizes use the built-in
estimate; provider usage is recorded separately and is not an invoice.

`--resume` skips terminal recorded tasks under exactly the same configuration.
It does not overwrite failures or silently repeat a partially interrupted task.
Use a new run directory for a disclosed corrective retest.

## Original-project acceptance

The [`public-swe-development`](../../.github/workflows/public-swe.yml) workflow
uses Linux containers and the official grader pinned at
`02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`. It needs no model credential.

Each task first runs the reference fix and unchanged-source controls. Both
must behave as expected before its candidate results can support a success
claim. It then checks each available generated patch with upstream
FAIL_TO_PASS and PASS_TO_PASS tests. Empty or unavailable patches remain
failures; upstream execution errors remain explicit, not successful results.

`control-request.json` selects the ten fixed development tasks and optionally
points to a committed candidate directory. The workflow retains per-task
reports and upstream execution logs as downloadable artifacts. No reference
fix or grading output is fed back into a model run.

The 200-task, three-trial formal comparison is **planned, not completed**.
Development failures may guide changes; held-out tasks must remain unused until
the implementation and experiment settings are frozen.
