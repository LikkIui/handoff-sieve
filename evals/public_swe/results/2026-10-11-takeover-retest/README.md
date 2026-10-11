# Two-task corrective takeover retest

This is a separate development retest of `scikit-learn__scikit-learn-25931`
and `pylint-dev__pylint-6528`, chosen to investigate initial selection/budget
failures. It adds **zero new distinct tasks** and is not a held-out result.
The original ten-task run remains unchanged.

Three independent fresh coder checkouts use the same frozen issue and clean
initial source. Full history and strong-summary contexts are reused from the
initial run; selected packets come from the separate indexed-selector retest.
Every coder receives 24 source actions and the remaining-action notice.
The original researcher and all context-preparation requests are reused, not
newly billed by this run. Raw calls here measure continuation usage only.

Six patches were generated. Only independent upstream test reports determine
whether any resolves its original issue. Controls and candidate reports are
saved under `upstream/`; model finish notes do not establish success.

| Condition | Resolved original issues | Continuation calls | Continuation provider tokens |
|---|---:|---:|---:|
| Full History | 2/2 | 25 | 326,271 |
| Strong receiver-aware summary | 1/2 | 33 | 272,642 |
| HandoffSieve indexed selection | 1/2 | 29 | 243,133 |

All controls passed and all six patches applied. All conditions solved the
scikit-learn task; only full history solved the pylint task. Both compressed
conditions used an internal `_ignore_paths` cache before `open()` initialized
it; the successful patch used `config.ignore_paths`. This is a concrete
dependency/lifecycle failure, not a patch-format or infrastructure failure.
The original researcher had not investigated that cache lifecycle, and all
coders could independently inspect source, so this does not isolate the failure
to handoff selection alone.

This retest made **87 new real continuation requests / 842,046 reported tokens**.
The previously paid research, summary and selection calls are not newly incurred
or included here. Those costs must be included when judging a fresh end-to-end
use; these continuation totals alone do not prove total-cost savings.
See [`summary.json`](summary.json) and the
[actual grading workflow](https://github.com/LikkIui/handoff-sieve/actions/runs/38073674100).

The indexed selector, budget notice and coder limit changed together. This
diagnostic cannot isolate their individual causal effect or establish general
superiority. The two tasks were selected after development failures, so they
must not be pooled as an unbiased stability trial of the earlier implementation.
`run-manifest.json` records the revision and reused contexts;
`reproduce.py.txt` contains the actual executed diagnostic.
