# Versioning and runtime provenance

Binnacle currently separates **distribution version** from **deployment
identity**.

## Distribution version

`pyproject.toml` owns the Python distribution version. It is currently:

```toml
[project]
version = "1.0.1"
```

This is package metadata, not a claim that every deployed commit is a new
formal release. Binnacle is still deployed directly from a reviewed Git
checkout. GitHub releases require an explicit, manual publish operation;
GitHub releases are created manually after an exact-SHA deployment gate.
The PyPI Trusted Publisher workflow runs only after a normal GitHub release
is published, then waits for approval in the protected pypi environment.

The version remains static until there is an intentional package release. Do
not bump it merely because `master` advances.

## Deployment identity

Runtime provenance reports two independent values:

- `package_version`: the installed distribution metadata;
- `revision`: the source checkout Git SHA, shortened to 12 characters.

For a source checkout, tracked modifications append `+dirty`. Untracked files
are ignored because local notes do not change the tracked code that the
services run. A non-Git wheel installation reports `revision=installed`.

The provenance appears in:

- the MCP server `event=config` startup line as `version=... revision=...`;
- the job manager startup line as `package_version=... revision=...`;
- the private job-manager `ping` response;
- `binnacle doctor`, including the live jobs-service response.

When the jobs service is running from a different checkout revision than the
current Binnacle checkout, doctor reports a warning rather than restarting it.
The durable job owner must only be restarted at a quiet moment with no running
jobs.

This lets an operator distinguish two deployments that both have package
version `1.0.0` but run different commits.

## Tags and releases

Existing `archive/...` tags are historical checkpoints. They are **not**
release tags and must not drive Python package version calculation.

Binnacle intentionally does not use `setuptools-scm` or another Git-derived
dynamic package version today. The repository has many archive tags and no
formal release cadence; the deploy SHA already supplies the finer-grained
runtime identity.

For the explicitly approved first manual GitHub release (v1.0.0) and any
subsequent release:

1. choose and commit the new static package version;
2. require the normal code-quality, compatibility, coverage, packaging and
   live-deployment gates;
3. create an annotated `vX.Y.Z` tag only for the reviewed release commit;
4. create a GitHub Release and/or publish a wheel only as an explicit,
   separately reviewed release action;
5. never reuse or move a release tag.

Deployment and release remain separate operations; the release tag can only
point at the already-verified deployed source SHA. The initial GitHub release used 1.0.0; the first PyPI-ready package
uses 1.0.1 with full MIT licensing and public distribution metadata.
