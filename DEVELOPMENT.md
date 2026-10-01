# Development workflow

This document is the canonical entry point for developing Binnacle. It owns
repository bootstrap, Git-hook installation, normal development commands, and
Git worktree hygiene. Detailed test semantics remain in docs/testing.md and the
quality-gate policy remains in docs/quality-gates.md.

## Bootstrap a checkout

Repository-level requirements are:

- Git;
- uv at the exact version pinned by `uv.lock`;
- ripgrep (rg).

The deployed Binnacle server still requires Linux and systemd. The development
helper itself is intentionally standard-library Python and does not imply that
the current runtime is portable to macOS.

For a fresh clone or a fresh Git worktree, run:

~~~bash
uv run scripts/dev.py bootstrap
~~~

scripts/dev.py carries PEP 723 metadata and has no third-party dependencies, so
uv can run the bootstrap helper before the project's .venv exists.

Bootstrap is idempotent and performs four operations:

1. verify that the installed uv exactly matches the `uv` package in `uv.lock`;
2. run uv sync --locked --group dev;
3. run pre-commit install, which installs every hook type declared by
   default_install_hook_types in .pre-commit-config.yaml;
4. run the repository development doctor.

If bootstrap reports a uv version mismatch, update the standalone uv binary
to the version named in the error (for example, `uv self update VERSION`) and
rerun bootstrap. `[tool.uv].required-version` is deliberately a compatible
0.12.x range so GitHub Dependabot can operate with its bundled uv; the direct `uv==...` dev dependency plus `uv.lock` remain the exact local/CI tool pin.

It does not install operating-system packages, configure systemd services,
change Binnacle host configuration, or deploy the server.

## Development doctor

Run the read-only environment check at any time:

~~~bash
uv run scripts/dev.py doctor
~~~

For agents or other automation:

~~~bash
uv run scripts/dev.py doctor --json
~~~

The doctor verifies:

- the checkout is the Git top level;
- the working-tree state;
- the primary Git checkout is still a normal worktree rather than `bare`;
- the exact uv version;
- uv.lock without changing it or accessing the network;
- ripgrep;
- the project .venv and its .python-version interpreter;
- every Git hook type declared by the pre-commit configuration.

A dirty working tree is a warning, not a failure. Missing tools, lock drift,
the wrong interpreter, missing/non-executable configured hooks, or a primary
checkout that Git reports as `bare` are failures. For the bare-checkout case,
doctor prints the exact `git --git-dir=... config core.bare false` repair
command; run it only after confirming that the path is the repository's intended
primary checkout.

This doctor is different from binnacle doctor. The development doctor validates
the repository environment. binnacle doctor validates the configured/running
server on the host.

## Git worktrees

Binnacle commonly uses several worktrees for parallel AI-agent development.
Treat each worktree as an independent development checkout even though Git
metadata and hooks are shared.

Inspect every registered worktree without changing any of them:

~~~bash
uv run scripts/dev.py worktrees
~~~

Machine-readable form:

~~~bash
uv run scripts/dev.py worktrees --json
~~~

The inventory reports independent flags rather than making cleanup decisions:

- bare: Git is treating a registered checkout as a bare repository, so normal
  worktree commands are unavailable;
- state-unknown: the worktree status could not be read;
- dirty: tracked or untracked files are present;
- upstream-gone: the branch has upstream configuration but the upstream ref no
  longer resolves;
- merged: the worktree HEAD is already an ancestor of master;
- no-venv: that worktree has no project virtual environment;
- lock-drift: its lock file does not pass uv lock --check --offline;
- locked: Git reports the worktree as locked.

The merged flag describes committed HEAD history only. Dirty work is reported
separately and must never be discarded merely because HEAD is merged.

Create and bootstrap a parallel worktree in one command:

~~~bash
uv run scripts/dev.py worktree-create ../binnacle-example \
  --branch feature/example --base master
~~~

Creation is transactional. The helper validates the branch/base and target
path, refuses nested worktrees and branch names that already exist locally or
on `origin`, creates the worktree, then runs the canonical bootstrap against
that checkout. If bootstrap fails while the new branch is still at the original
base and the worktree has no source changes, the helper removes the
half-created worktree and branch. If anything changed after creation, it
preserves the worktree rather than discarding possible work.

Do not copy `.venv` between worktrees. uv creates or synchronizes the correct
environment for each checkout.

Cleanup is guarded and defaults to a dry-run plan:

~~~bash
uv run scripts/dev.py worktree-cleanup ../binnacle-example --delete-branch
~~~

The command refuses the current worktree, bare or locked worktrees,
dirty/unknown working-tree state, any HEAD not already merged into `master`,
and any worktree currently attached to protected local branches such as
`master` or `proof-of-concept`.

Only after the plan is safe should cleanup be applied explicitly:

~~~bash
uv run scripts/dev.py worktree-cleanup ../binnacle-example \
  --delete-branch --apply
~~~

Branch deletion uses ordinary `git branch -d`, never a forced delete. Remote
branches are never deleted by this helper.

## Normal development loop

For a focused change, start with the lowest test layer that proves the
behavior. Examples:

~~~bash
uv run pytest tests/unit/tools/test_read_file.py -q
uv run pytest tests/scripts/test_dev.py -q
~~~

For the managed full suite:

~~~bash
uv run python scripts/run_test_suite.py
~~~

The installed Git hooks provide the normal local gates:

- pre-commit: deterministic static/repository checks;
- pre-push: the fixed-seed fast unit and contract suite.

Run the same gates explicitly when needed:

~~~bash
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
~~~

The authoritative coverage gate is separate from ordinary compatibility tests:

~~~bash
uv run tox -e coverage-policy -- --seed 12345
~~~

Run the complete supported Python compatibility matrix with:

~~~bash
uv run tox
~~~

Do not replace the repository test runner with a direct pytest -n invocation.
The ordinary-process lane is part of the test contract. See docs/testing.md for
test placement, parallelism, live-test rules, mutation testing, weekly checks,
and deployment smoke details.

## Deployment boundary

Development completion and deployment are separate operations.

The production checkout is deployed through:

~~~bash
.venv/bin/python scripts/deploy_smoke.py deploy TARGET
~~~

That flow verifies GitHub CI, waits for a quiet production window,
fast-forwards the production checkout, loads the changed server code, runs the
live smoke, and only then pushes master and proof-of-concept. On a failed live
smoke it rolls the checkout back and pushes nothing. In dev mode, a change to
`pyproject.toml` or `uv.lock` first synchronizes the checkout `.venv` with
`uv sync --locked --group dev`, then explicitly restarts the MCP service so
the smoke exercises the new locked environment. Rollback performs the same
sync against the old commit before reloading it. The stable jobs service is
never restarted by this flow.

The deployment preflight requires a clean tracked tree. Untracked files are
allowed only under `docs/`, because documentation cannot alter the running
package or deployment scripts. Any untracked file elsewhere, including under
`src/` or `scripts/`, still blocks deployment.

Do not use an ordinary direct push to master or proof-of-concept as a
substitute for that flow. The active `master deployment gate` ruleset is
designed to reinforce this contract: it requires the reviewed CI checks and
blocks deletion/non-fast-forward updates without forcing a PR-only deployment.
See `docs/github-governance.md`.

## Sources of truth

Keep volatile operational facts in one place:

| Topic | Canonical source |
| --- | --- |
| Clone/bootstrap/hooks/worktrees/dev loop | DEVELOPMENT.md |
| Product quick start and user configuration | README.md |
| Test layout, semantics and commands | docs/testing.md |
| Pre-commit/pre-push/CI/security gate policy | docs/quality-gates.md |
| GitHub rulesets and dependency automation | docs/github-governance.md |
| Package version and runtime revision provenance | docs/versioning.md |
| Agent-specific operational instructions | CLAUDE.md |
| Distribution/release-readiness boundary | docs/release-readiness.md |

CLAUDE.md should link to these documents instead of copying test counts,
coverage measurements, or other values that routinely change.
