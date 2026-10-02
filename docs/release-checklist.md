# GitHub alpha release checklist

Current release: `0.3.0a3`, tag `v0.3.0a3`. PyPI publication remains paused
at the maintainer's request; GitHub package verification and publication do
not depend on completing PyPI account setup.

## Release identity

- Keep distribution `handoff-sieve`, import `handoff_sieve`, and repository
  `LikkIui/handoff-sieve` consistent.
- Update the single version source in `src/handoff_sieve/_version.py`; built
  metadata, public `__version__`, and installed-artifact checks must agree.
- Move completed changes to a dated changelog entry and update installation
  links, migration notes, adapter guides, and supported versions.
- Preserve existing release tags and assets. Never reuse a version for
  different package bytes.

## Automated gates

- `python -m pytest`
- `ruff check .` and `ruff format --check .`
- `mypy src evals`
- `python -m benchmarks.run --check`
- `python -m evals.takeover.validate --validate`
- `python -m build` and `python -m twine check --strict dist/*`
- Install the wheel and source distribution in fresh virtual environments;
  run `scripts/verify_installed.py` outside the source checkout.
- Run the receiver views, missing-state correction, budget feedback, SDK
  takeover, and three-agent relay demos using the installed wheel, without a
  key or model request.
- Unpack the sdist and run its included tests and benchmark to verify that it
  is self-contained.
- Pass existing Python 3.10-3.13, OpenAI Agents SDK 0.22.x, LangGraph
  `>=1.0,<2`, and package CI checks.

The `wheel` CI job also checks quickstart, the three takeover routes, LangGraph,
and Failure Zoo outside the source checkout.

## Publication

- Build from the exact reviewed commit into a new empty directory. Do not
  reuse old packages from `outputs/`, `work/`, or `dist/`.
- Check package contents and public claims; keep local token estimates and
  provider usage separate, and include no local credentials or environment files.
- Record SHA-256 hashes for the wheel and source distribution in `SHA256SUMS`.
- Create the matching GitHub tag and prerelease with those exact files.
- Download release attachments without authentication, compare hashes, and
  verify installation from the published wheel.
- State demonstrated behavior and material limits in release notes. The saved
  one-task SDK gateway-usage anomaly is unresolved; do not claim billing savings
  from that checkpoint.

## When PyPI resumes

Follow [PyPI publishing](pypi-publishing.md). Verify the version is not already
uploaded, configure the Trusted Publisher, and reuse the verified GitHub
package bytes. Run the publisher workflow only after the maintainer resumes
PyPI publication. Verify remote file hashes and a fresh PyPI installation.
