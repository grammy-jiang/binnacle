# Binnacle — Claude Code project guide

`DEVELOPMENT.md` is the canonical repository-development contract. This file
is the thin, always-loaded Claude Code entry point for Binnacle-specific
context. If it conflicts with `DEVELOPMENT.md`, follow `DEVELOPMENT.md` and
repair this file in the same change. Codex uses the matching `AGENTS.md`
entry point; keep the two aligned on shared engineering rules.

## Project shape

Binnacle is a FastMCP server exposed locally on port 8000 and, for ChatGPT,
through the separate `binnacle-tunnel` companion. Tool modules live under
`src/binnacle/tools/`; `server.py` is assembly. Durable background jobs are
owned by the sibling `binnacle-jobs.service` and persisted under
`~/.local/state/binnacle/jobs/`.

The current public tool surface is `read_file`, `list_files`, `search_text`,
`edit_file`, `write_file`, `run_command`, `job_status`, and `stop_job`.
Client-specific exposure is configured separately.

## Repository workflow

- Use `uv run scripts/dev.py doctor` to validate a checkout.
- Use `uv run scripts/dev.py worktrees` before choosing or cleaning a
  worktree.
- For substantial or parallel work, prefer
  `uv run scripts/dev.py worktree-create PATH --branch BRANCH --base master`.
- Never copy `.venv` between worktrees.
- This repository is developed by multiple agents concurrently. Immediately
  before commit, rebase, deploy, branch deletion, or cleanup, re-read
  `git status`, relevant refs, and the worktree inventory.
- Never reset, stash, clean, overwrite, force-delete, or remove another
  session's work. Preserve dirty, locked, unmerged, or unknown worktrees.
- Cleanup uses `worktree-cleanup` dry-run first; use `--apply` only after it
  reports the target safe.

See `DEVELOPMENT.md` for bootstrap and normal development commands.

## Quality

- Start with focused tests appropriate to the change.
- The repository-managed full runner is
  `uv run python scripts/run_test_suite.py`; do not replace it with a direct
  `pytest -n` full-suite invocation because the ordinary-process lane is part
  of the contract.
- Explicit gates are documented in `DEVELOPMENT.md` and `docs/testing.md`.
  Common commands include:
  - `uv run pre-commit run --all-files`
  - `uv run pre-commit run --hook-stage pre-push --all-files`
  - `uv run tox -e coverage-policy -- --seed 12345`
  - `uv run tox` when the complete compatibility matrix is required.
- Ruff, Bandit, uv-lock, mypy and other project-aware Python tools run from
  the locked project environment. Do not create a second remote pre-commit
  version source for them.
- If a test initializes or operates on another Git repository, clear inherited
  repository-local Git variables such as `GIT_DIR` and `GIT_WORK_TREE` first.

## Local reload and services

In development mode, Python changes under `src/` auto-reload uvicorn. Test,
script, and documentation edits do not reload the MCP server.

For ordinary local dependency work, synchronize the locked environment before
expecting a running process to see new dependencies. For **production
deployment**, do not hand-roll that sequence: the gated deploy handles the
`uv sync`, MCP restart, live smoke, and rollback restoration.

`binnacle-jobs.service` is intentionally stable across MCP reloads/restarts.
Restarting the jobs service is a separate operation with its own quiet gate;
never restart it just because MCP code or dependencies changed, and do not
restart it while durable jobs are active.

## Deployment boundary

Deploy only with:

```bash
.venv/bin/python scripts/deploy_smoke.py deploy TARGET
```

The gate verifies CI for the exact target, requires a fast-forward, requires a
clean tracked tree (untracked files are allowed only under `docs/`), waits for
a quiet production window, loads the candidate, and runs the live smoke. In
dev mode, `pyproject.toml` or `uv.lock` changes trigger
`uv sync --locked --group dev` plus an MCP restart. Success atomically updates
`master` and `proof-of-concept`; sync/reload/smoke/push failure rolls the
checkout back and re-verifies it, including restoring the old locked
environment when necessary.

Do not direct-push `master` or `proof-of-concept` as a substitute for this
gate. See `docs/github-governance.md`.

## Runtime verification

- `.venv/bin/binnacle doctor` validates the core server chain.
- `binnacle-tunnel doctor` validates the ChatGPT tunnel companion.
- `binnacle-watchdog doctor` validates host/watchdog state.
- `scripts/deploy_smoke.py --full` performs the full live smoke.

Network probes can expose real intermittent uplink failures. Do not weaken a
deployment gate just to make a deploy pass; diagnose the network or wait for a
healthy quiet window.

## MCP/ChatGPT-specific work

When changing the MCP tool surface or verifying ChatGPT behavior, use the
project skill `.claude/skills/chatgpt-mcp-dev/SKILL.md`. For usage-driven
tool improvement rounds, use `.claude/skills/mcp-usage-review/SKILL.md`.
Those skills add client/testing procedures; they do not override the
repository workflow or deployment boundary above.

## Read deeper only when relevant

- Repository development: `DEVELOPMENT.md`
- Test semantics: `docs/testing.md`
- Quality policy: `docs/quality-gates.md`
- GitHub/Dependabot governance: `docs/github-governance.md`
- Version/provenance: `docs/versioning.md`
- Distribution readiness: `docs/release-readiness.md`
- Durable job ownership: `docs/durable-job-ownership.md`

Historical incident/experiment notes from the former long agent guide are
archived at `docs/archive/claude-agent-guide-history-2026-10-02.md`. They are
evidence, not current instructions; do not use old version/status statements
from that archive as present-day truth.

## Stage 1 OS independence

Consult `docs/os-independent-stage1-architecture.md` and
`DEVELOPMENT.md` for stage-specific source boundaries and quality
gates. FastMCP remains the only MCP framework; Linux platform
adapters own OS operations and the existing durable Job Manager
survives MCP lifetime. Do not bypass real independent reviews,
production CI, quiet-window deployment or stable active jobs.
