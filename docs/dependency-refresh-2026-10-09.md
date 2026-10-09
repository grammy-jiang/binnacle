# Dependency refresh for PyPI v1.0.1 — 2026-10-09

## Goal and baseline

User-authorized update of **all currently declared Python runtime, development,
test and security dependencies**, plus the repository's pinned GitHub Actions
and pre-commit integrations. The comparison baseline is the exact deployed
MIT/PyPI candidate at commit fd18e513bf2db2d6aa90a4cd12f1b3751a83b6b8.

Dependencies are upgraded via uv's resolver using \`uv lock --upgrade\`, then
\`uv sync --locked --group dev\`. No production modules or public MCP schema
changes are permitted as a shortcut. The lock remains authoritative for CI
and developer tooling. Public PyPI package dependencies follow the package's
own declared requirements rather than distributing the entire lockfile.

## Source-verified latest versions

Public PyPI JSON checked on 2026-10-09. FastMCP 4.1.0 remains latest
stable; MCP and MCP-types are now 2.3.0, requiring explicit release-source
and wire-contract revalidation.

| Dependency | Baseline | Refreshed |
| --- | --- | --- |
| FastMCP | 4.1.0 | 4.1.0 (already latest) |
| MCP SDK | 2.1.1 | 2.3.0 |
| MCP Types | 2.1.1 | 2.3.0 |
| Pydantic | 2.13.5 | 2.14.0 |
| Starlette | 1.6.0 | 1.7.0 |
| Uvicorn | 0.52.4 | 0.54.0 |
| Orjson | 3.12.0 | 3.13.0 |
| Cyclopts | 4.25.3 | 5.2.0 on Python 3.11+ |
| pytest-randomly | 4.1.* | 5.0.0 |
| Mypy | 2.3.* | 2.4.0 |
| Ruff | 0.16.* | 0.16.10 (latest within reviewed minor) |
| uv | 0.12.21 | 0.12.24 |
| tox | 4.64.7 | 4.64.10 |

Cyclopts 5.2.0 requires Python 3.11, so the resolver retains Cyclopts
4.25.3 for Python 3.10 rather than dropping the supported runtime.
Binnacle's Python requirement now explicitly caps at Python <3.15,
which avoids claiming support for an untested future interpreter and
unneeded pre-release-only dependency branches.

The lock refresh affected 49 same-name package versions. Package entries
and resolution-marker branch counts are not equal to the number of unique
distributions. Latest **compatible** resolution can be lower than the
unqualified latest PyPI release for an older Python interpreter.

## GitHub Actions, pre-commit and build backend

The latest tagged stable revisions were checked via GitHub release/tag APIs.

- \`actions/upload-artifact\`: v7.0.1 → v7.0.2, pinned to immutable
  \`cf430e030ddbb5b0abf93d22962f4752f3646cd9\`.
- \`taiki-e/install-action\`: v2.87.23 → v2.87.26, pinned to immutable
  \`f7e5d7c961414b23f5b25b2da9294395d08513ad\`.
- Checkout, Cache, Download Artifact, setup-uv and PyPA's Trusted Publishing
  action were already at their latest stable reviewed tags, with full SHAs.
- All six pinned pre-commit repository tags are current according to their
  respective release/tag records; no hook or security control was removed.
- Setuptools 84.0.0 remains the latest verified hash-constrained build
  backend; zizmor 1.30.1 is already the latest stable PyPI version.

## Acceptance and release sequence

1. Run targeted MCP wire parity, FastMCP composition, auth, client visibility,
   CLI, durable Job and Python distribution tests. Repair failures without
   weakening the existing protocols or gates.
2. Run Ruff, mypy, deptry, actionlint, zizmor, uv lock consistency and
   repository-specific architecture/module-size/security controls.
3. Freeze exact Git candidate SHA and run full seven-job GitHub CI on that SHA:
   Code quality, Python 3.10/3.11/3.12/3.14, Python 3.13 coverage and
   Python 3.13 packaging.
4. Deploy the reviewed exact SHA using the existing guarded Raspberry Pi
   flow; confirm real read-only MCP client behavior and Live Smoke before
   creating the immutable version tag.
5. Upload only after the PyPI account-side Pending Trusted Publisher is
   installed, and GitHub's protected pypi Environment has approved the job.
   The release action has no stored long-lived upload token.

PyPI publication does **not** require or authorize an opportunistic restart
of the independent durable Job Manager; it follows its own idle-time policy.
No PyPI publication or production release may be claimed unless the actual
remote service confirms success.
