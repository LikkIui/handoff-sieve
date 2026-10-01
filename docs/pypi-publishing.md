# Publish the existing GitHub release to PyPI

The public GitHub prerelease is `v0.3.0a1`. PyPI publication is pending account
configuration. The workflow downloads its existing wheel and source archive,
checks their `SHA256SUMS`, verifies installation, and uploads those same bytes.
It does not rebuild a released version or need a stored PyPI API token.

## One-time account setup

Log in to [PyPI account publishing](https://pypi.org/manage/account/publishing/)
and add a **pending GitHub publisher** with these exact fields:

| Field | Value |
|---|---|
| PyPI project name | `handoff-sieve` |
| Owner | `LikkIui` |
| Repository name | `handoff-sieve` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

The workflow name is the filename, without `.github/workflows/`. The owner is
the GitHub owner, not the PyPI username. A pending publisher creates the PyPI
project on the first upload; configuring it alone does not reserve the name.
If the project already exists under your account, add the same fields through
the project's Publishing page instead.

The GitHub `pypi` environment permits deployment from `main`. The workflow also
refuses other branches and grants OIDC permission only to the upload job.

## Verify first, then upload

Open [Publish to PyPI](https://github.com/LikkIui/handoff-sieve/actions/workflows/publish-pypi.yml)
and choose **Run workflow** on `main`:

1. Set `release_tag` to `v0.3.0a1` and leave `publish` off for a dry run.
2. After the account publisher is configured, run again with `publish` on.
3. Confirm all three jobs pass. The final job compares PyPI file hashes with
   the GitHub release and installs `handoff-sieve==0.3.0a1` from PyPI.

The workflow requires successful source CI for the release tag. Dry runs do not
request a PyPI token or upload files. PyPI does not allow replacing an uploaded
version; never rebuild and upload different bytes under the same version.

After a confirmed upload, update README installation instructions and the
GitHub release notes to use `python -m pip install handoff-sieve==0.3.0a1`.

Official references: [create a project with a trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[publish with a trusted publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
