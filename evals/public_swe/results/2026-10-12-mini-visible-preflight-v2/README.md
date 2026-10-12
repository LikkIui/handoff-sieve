# Separate environment-corrected original-test preflight

The first unchanged-source preflight failed before any new model calls:
Django's Unicode filename case used an ASCII filesystem encoding, and Sphinx's
test_autodoc emitted a meta-node compatibility warning with newer docutils.
Its original result remains unchanged. No tests are deleted or deselected.

This preflight runs the same broad original suites with C.UTF-8 locale and, for
Sphinx only, docutils 0.16, supported by the original base checkout tox.ini.
The dependency override applies equally to unchanged and candidate conditions.
There are no model requests, hidden grader imports or evaluator patches.
