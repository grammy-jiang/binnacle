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
- the exact uv version;
- uv.lock without changing it or accessing the network;
- ripgrep;
- the project .venv and its .python-version interpreter;
- every Git hook type declared by the pre-commit configuration.

A dirty working tree is a warning, not a failure. Missing tools, lock drift,
the wrong interpreter, or missing/non-executable configured hooks are failures.

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

- dirty: tracked or untracked files are present;
- upstream-gone: the branch has upstream configuration but the upstream ref no
  longer resolves;
- merged: the worktree HEAD is already an ancestor of master;
- no-venv: that worktree has no project virtual environment;
- lock-drift: its lock file does not pass uv lock --check --offline;
- locked: Git reports the worktree as locked.

The merged flag describes committed HEAD history only. Dirty work is reported
separately and must never be discarded merely because HEAD is merged.

Create a normal parallel worktree with Git, then bootstrap it:

~~~bash
git worktree add -b feature/example ../binnacle-example master
cd ../binnacle-example
uv run scripts/dev.py bootstrap
~~~

Do not copy .venv between worktrees. uv will create or synchronize the correct
environment for each checkout.

Worktree deletion remains an explicit manual operation for now. Do not remove a
dirty, unmerged, or locked worktree. A later infrastructure phase may add a
guarded cleanup command, but the current command is deliberately diagnostic
only.

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
smoke it rolls the checkout back and pushes nothing.

Do not use an ordinary direct push to master or proof-of-concept as a
substitute for that flow. Repository-side GitHub rules are intentionally a
separate infrastructure phase because they must first be proven compatible
with this deployment contract.

## Sources of truth

Keep volatile operational facts in one place:

| Topic | Canonical source |
| --- | --- |
| Clone/bootstrap/hooks/worktrees/dev loop | DEVELOPMENT.md |
| Product quick start and user configuration | README.md |
| Test layout, semantics and commands | docs/testing.md |
| Pre-commit/pre-push/CI/security gate policy | docs/quality-gates.md |
| GitHub rulesets and dependency automation | docs/github-governance.md |
| Agent-specific operational instructions | CLAUDE.md |
| GitHub ruleset and Dependabot governance | docs/github-governance.md |

CLAUDE.md should link to these documents instead of copying test counts,
coverage measurements, or other values that routinely change.
