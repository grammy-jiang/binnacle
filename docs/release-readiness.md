# Release readiness

Binnacle supports explicitly approved manual GitHub releases, but has no automated
GitHub or PyPI publishing pipeline. It does not publish to PyPI.
`project.version` in `pyproject.toml` is package metadata used by installed
artifacts and runtime diagnostics; the current value does not by itself mean
that a corresponding public release exists.

This document defines the separate distribution-readiness and manual
publication boundaries; passing packaging CI is not itself a release.

## Distribution gate

The dedicated GitHub Actions `Packaging / Python 3.13` job runs:

```bash
uv run --no-sync pytest -q tests/integration/test_wheel_artifact.py
```

Despite the historical filename, the test now validates both Python
distribution formats and a clean installation.

The gate:

1. copies only the publishable project inputs into a temporary source tree;
2. builds an sdist with `uv build --no-sources`, the repository's
   hash-constrained build requirements, and `--require-hashes`;
3. builds the wheel **from that sdist**, proving the source distribution can
   reproduce the binary artifact without relying on untracked checkout files;
4. inspects both archives for runtime modules, `py.typed`, console entry
   points, package metadata, and the absence of the test suite;
5. exports the exact locked runtime dependency set without development groups;
6. creates a new virtual environment using the Packaging job's Python
   interpreter;
7. installs the locked runtime dependencies with hash verification, then
   installs the local wheel with dependency resolution disabled;
8. imports `binnacle` and `binnacle.job_manager` from that clean environment and
   verifies the installed `binnacle-mcp` metadata version equals
   `project.version`;
9. runs `--help` for the three command-oriented entry points under an isolated
   HOME/XDG environment.

`binnacle-jobs` is deliberately not executed by this smoke. Its entry point
starts the durable Unix-socket job-manager service immediately rather than
providing a command parser. The distribution gate verifies that the entry point
is installed and imports its module without starting the service.

The clean-install dependency step exports exact versions and hashes from the
repository lock. uv may satisfy those artifacts from its cache or the configured
package index, but it may not substitute a different artifact or version.

## What this does not do

Artifact readiness is not release publication. The repository currently has no
workflow that:

- chooses or increments a release version;
- creates a release tag;
- creates a GitHub Release;
- uploads artifacts to PyPI or another package index;
- manages publishing credentials or trusted-publishing policy.

Those actions remain explicit future design decisions. They should not be added
implicitly to ordinary CI or to the production deployment flow.

Manual GitHub release policy: after explicit user authorization and a single
exact-SHA CI success, first deploy with the existing guarded live smoke.
Create an annotated version tag only on the verified deployed SHA, never move
or reuse a release tag, and publish release notes and verified distribution
artifacts separately. Roll back the deployment without moving the public tag;
ship corrections under a new version. Automated release workflows and PyPI
publication require a separate design and approval.

## Relationship to deployment

The existing production deployment flow and a future package release are
separate concerns.

`scripts/deploy_smoke.py deploy TARGET` deploys an already-tested Git commit to
the Raspberry Pi and atomically advances `master` plus `proof-of-concept`. It
does not create or publish a package release.

The Packaging CI job proves that the same source snapshot is distributable. A
future release workflow may consume that evidence, but it must not bypass the
repository's existing quality, coverage, security, and deployment controls.
