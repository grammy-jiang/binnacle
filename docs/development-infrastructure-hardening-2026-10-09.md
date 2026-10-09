# Binnacle development infrastructure hardening — 2026-10-09

Base: `045ff9eea07b301cea849b69f99e87704ab1b155`.
Implementation: isolated branch `fix/development-infrastructure-quality-20261009`
under `/home/grammy-jiang/Projects/binnacle-dev-infra-quality`.

## Authority / safety

- Scope: build, test, CI and repository-quality infrastructure; no MCP tools,
  wire contracts, durable-job semantics, systemd service, platform design or
  user-owned dirty files.
- Do not change or relax seven protected master required checks, their names,
  issuer, exact-SHA evidence or atomic deploy/rollback. Default CodeQL must be
  optional initially; do not make a new required job without updating the
  complete governance contract.
- Preserve root `master` user edits and historical notes. Commit only in the
  isolated worktree, run local focused tests and ordinary hooks, freeze one
  candidate and use GitHub's mandatory CI before guarded deployment.

## Phase I — make existing gates truthful

1. Coverage checker derives complete expected canonical Python-source inventory,
   excluding `__init__.py`; fail on any missing/obsolete file in unit/full
   coverage inputs and on malformed/empty inventory. Keep per-module 95/90
   thresholds unchanged. Test deletion/incomplete/extra reports and valid case.
2. Weekly mutation run emits WARN for incomplete, missing, error and timed-out
   results, never OK; do not advance rotation on incomplete data. Add outcome,
   partial-results and rotation regressions. Keep >=80% threshold and the
   low-impact 1-CPU farm.

## Phase II — CI security and new low-cost tool

1. Set `actions/checkout` `persist-credentials: false` in every read-only job.
   Add seven-day cooldown for routine Dependabot updates; security updates
   must not be delayed.
2. Add the reviewed `zizmor` version to locked local lint tools. Run offline,
   fail on medium/high findings, covering CI, Security, Dependabot and
   pre-commit configurations. Check no new credential-bearing contexts;
   audit minimum-severity/CI-report boundary with explicit negative fixtures.
3. Enable GitHub CodeQL default setup for Python and Actions after CI
   integration, with its checks initially advisory/independent, verify repo API
   state and first scan. Do not make CodeQL one of the seven required jobs.

## Phase III — broaden critical script confidence

1. Correct source/report completeness before expanding coverage enforcement:
   test critical deploy/CI/quality scripts and their failure branches with
   synthetic in-memory fixtures. Introduce a minimal `scripts` branch-coverage
   inventory/ratchet with measured baseline and no silent omission (test source
   exclusion separately). Do not invent an unattainable 90% floor on day one.
2. Keep Pyright, Ruff experimental rules and Vulture advisory only until
   incremental findings are classified. No false-green or blanket ignores.

## Phase IV — evidence & cadence

1. Retain independent parallel + ordinary test lanes. Allow opt-in separate
   JUnit XML outputs per lane and bounded durations under CI, upload on failure
   with 7-day retention. Do not double-run the full suite and do not skip
   non-doc test jobs based on path filters.
2. Frozen candidate gates: focused pytest, pre-commit, mypy, Import Linter,
   `zizmor`, current 2-lane full seeded suite once, coverage policy, wheel
   smoke, Python 3.10–3.14 required GitHub CI and surface golden tests;
   guarded deployed smoke, exact-SHA push and README/report receipts.
3. Preserve dirty master with checksum-bound backup/restore if deploying.
    Never force-push or ignore a protection/safety refusal. Retire only our
    clean merged temporary worktree/branch.

## Acceptance evidence

- Negative fixtures demonstrate the prior false-green bugs and the fixes.
- All security audits green or findings explicitly investigated with reasons.
- Full CI seven required checks green on the frozen SHA, unaffected public
  surface, no user file changes.
- After release, production tools/Jobs/Tunnel/Watchdog work and user-owned
  documents are checksum-identical.
