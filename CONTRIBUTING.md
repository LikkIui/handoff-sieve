# Contributing

HandoffSieve is preparing its first public alpha. Useful reports show a small,
reproducible handoff boundary problem and the expected receiver view or audit
result.

## Before opening an issue

- Use synthetic prompts, identifiers, credentials, tool output, and audit data.
  Never submit production prompts, customer data, real tokens, or private logs.
- Report a vulnerability through the private process in
  [SECURITY.md](SECURITY.md), not through a public issue.
- Include the HandoffSieve version or commit, Python version, framework and
  framework version, policy order, and failure code when applicable.
- Reduce policy false positives and false negatives to the smallest synthetic
  input that still reproduces the behavior.

The issue templates separate implementation bugs, policy detection gaps, and
adapter requests so each report has the evidence needed for a decision.

## Local checks

```bash
python -m pip install -e ".[dev,langgraph,openai,tiktoken]"
python -m pytest
ruff check .
ruff format --check .
mypy src evals
python -m benchmarks.run --check
```

Changes to policy output, audit fields, token accounting, examples, or the
benchmark fixture need an assertion that explains the intended contract. Do
not refresh `benchmarks/results.json` merely to hide a failed acceptance gate.

Packaging changes also need:

```bash
python -m pip install -e ".[release]"
python -m build
python -m twine check --strict dist/*
```

The final wheel and source distribution must pass the isolated checks described
in [docs/release-checklist.md](docs/release-checklist.md).
