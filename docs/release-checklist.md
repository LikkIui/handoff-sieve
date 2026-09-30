# Alpha release checklist

This checklist prepares the first public prerelease without treating a local
build as a published release. Run every automated command from a clean checkout.

## Release identity

- [ ] Approve the formal project name after checking PyPI, GitHub, relevant
  product sites, domains, and applicable trademark registries.
- [ ] Make the project name, PyPI distribution, Python import, repository name,
  README, package metadata, and security links consistent.
- [ ] Confirm that `0.3.0a1` has never been uploaded under the selected PyPI
  distribution name. PyPI files and versions cannot be replaced.
- [ ] Change the single version source in `src/<package>/_version.py`; confirm
  the built metadata and public `__version__` match it.
- [ ] Remove the "Unreleased" marker from the `0.3.0a1` changelog entry and add
  the release date only when the artifacts are ready to publish.
- [ ] Replace the pre-release wording in the supported-versions section of
  `SECURITY.md` with an explicit `0.3.0a1` support row.

## Automated gates

- [ ] `python -m pytest`
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `mypy src`
- [ ] `python -m benchmarks.run --check`
- [ ] `python -m build`
- [ ] `python -m twine check --strict dist/*`
- [ ] Install both the wheel and source distribution in fresh virtual
  environments and run `scripts/verify_installed.py` outside the checkout.
- [ ] Unpack the sdist and run its included tests and benchmark from the
  extracted directory, proving that the source archive is self-contained.
- [ ] Run the quickstart and every Failure Zoo demo with the wheel-installed
  interpreter and no API key.
- [ ] Pass the Python 3.10–3.13, OpenAI Agents SDK 0.22.x, and LangGraph
  `>=1.0,<2` CI matrices.

The `wheel` CI job performs the artifact, quickstart, Failure Zoo, and adapter
smoke checks without importing `src/handoff_sieve` from the checkout.

## Security and documentation gates

- [ ] Review `SECURITY.md`, the threat model, limitations, configuration order,
  adapter support matrix, benchmark fixture, and measured README table.
- [ ] Enable GitHub private vulnerability reporting and verify the security link
  from a signed-out browser.
- [ ] Confirm that examples, fixtures, reports, and built artifacts contain no
  real credentials, personal data, build paths, or local environment files.
- [ ] Confirm that public claims describe pattern redaction and token counting
  as best-effort or estimated where appropriate.
- [ ] Verify the bug, policy-gap, and adapter-request issue templates, including
  their synthetic-data requirements and private security-reporting link.

## Publish gates

- [ ] Create the final artifacts from the exact reviewed commit.
- [ ] Remove or ignore every artifact from an earlier commit; the release
  workflow must build into an empty directory and never reuse `outputs/`,
  `work/`, or an existing `dist/` directory.
- [ ] Record SHA-256 hashes for the wheel and source distribution.
- [ ] Configure a PyPI Trusted Publisher restricted to this repository and the
  release workflow/environment.
- [ ] Publish the GitHub prerelease and PyPI prerelease from the same `v0.3.0a1`
  tag; do not rebuild between destinations.
- [ ] Install `handoff-sieve==0.3.0a1` from PyPI in a new environment and repeat
  the installed-artifact smoke test.
- [ ] Verify release links and provenance, then announce only the capabilities
  demonstrated by the checked-in tests and benchmark.

Publishing, tagging, renaming the remote repository, and reserving the PyPI
name are external actions. They remain separate from local release preparation.
