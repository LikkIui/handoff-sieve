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

The indexed selector, budget notice and coder limit changed together. This
diagnostic cannot isolate their individual causal effect or establish general
superiority. The two tasks were selected after development failures, so they
must not be pooled as an unbiased stability trial of the earlier implementation.
`run-manifest.json` records the revision and reused contexts;
`reproduce.py.txt` contains the actual executed diagnostic.
