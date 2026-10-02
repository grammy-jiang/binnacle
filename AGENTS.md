# Binnacle local agent guide

This file is the repository entry point for **Codex and other local agents that
honour `AGENTS.md`**. `DEVELOPMENT.md` is the canonical source for repository
development and deployment workflow. If this file and `DEVELOPMENT.md` ever
disagree, follow `DEVELOPMENT.md` and repair this file in the same change.

Claude Code uses `CLAUDE.md`; both agent entry points share the same canonical
development contract.

## Before editing

- Run `uv run scripts/dev.py doctor` to validate the checkout.
- Run `uv run scripts/dev.py worktrees` before deciding where to work or what
  can be cleaned.
- Prefer `uv run scripts/dev.py worktree-create PATH --branch BRANCH --base
  master` for substantial or parallel work. Do not copy `.venv` between
  worktrees.
- This repository is developed by multiple agents concurrently. Re-read
  `git status`, relevant refs, and the worktree inventory immediately before
  commit, rebase, deploy, branch deletion, or cleanup.
- Never reset, stash, clean, overwrite, force-delete, or remove work belonging
  to another worktree/session. Preserve dirty, locked, unmerged, or unknown
  worktrees. Use `worktree-cleanup` dry-run first and `--apply` only after it
  reports the target safe.

## Development and quality gates

- Start with focused tests, then use the repository-managed test layers
  documented in `DEVELOPMENT.md` and `docs/testing.md`.
- Explicit repository gates are:
  - `uv run pre-commit run --all-files`
  - `uv run pre-commit run --hook-stage pre-push --all-files`
  - `uv run tox -e coverage-policy -- --seed 12345`
  - `uv run tox` when the full supported Python matrix is required.
- Do not replace `scripts/run_test_suite.py` with a direct `pytest -n` full
  suite; the ordinary-process lane is part of the test contract.
- Ruff, Bandit, uv-lock and other project-aware Python tools run from the
  locked project environment. Do not add a second pre-commit-managed version
  for them. Python tool/dependency updates belong to the `uv` ecosystem;
  pre-commit Dependabot updates are for hook-native repositories.
- If tests create a separate Git repository, do not let inherited repository
  local variables such as `GIT_DIR` or `GIT_WORK_TREE` point that Git command
  back at Binnacle.

## Deployment boundary

- Development completion is not deployment. Never substitute a direct push to
  `master` or `proof-of-concept` for the deployment gate.
- Deploy only with `.venv/bin/python scripts/deploy_smoke.py deploy TARGET`.
  The gate requires the reviewed CI result and a fast-forward target, waits for
  a quiet production window, performs the live smoke, and atomically updates
  `master` plus `proof-of-concept`.
- The production preflight requires a clean tracked tree. Untracked files are
  allowed only under `docs/`; untracked files elsewhere still block deploy.
- In dev mode, a `pyproject.toml` or `uv.lock` change is synchronized with
  `uv sync --locked --group dev` and the MCP service is restarted so the smoke
  exercises the new environment. Rollback re-synchronizes the old environment.
- The stable `binnacle-jobs.service` is **not** restarted by the deployment
  flow. Restarting it is a separate operation with its own quiet gate; do not
  restart it while durable jobs are active.
- After deployment or host changes, use the relevant doctors/smokes described
  in `DEVELOPMENT.md`, `docs/testing.md`, and `CLAUDE.md`.

## Canonical references

- Repository workflow: `DEVELOPMENT.md`
- Test semantics: `docs/testing.md`
- Quality gates: `docs/quality-gates.md`
- GitHub rulesets and dependency automation: `docs/github-governance.md`
- Version/provenance: `docs/versioning.md`
- Distribution readiness: `docs/release-readiness.md`
- Claude Code / host-specific operational detail: `CLAUDE.md`
