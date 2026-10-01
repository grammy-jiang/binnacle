# Quality gate hardening before the portability refactor

Date: 2026-10-01

## Goal

Strengthen Binnacle's deterministic quality controls before the Linux/macOS
architecture refactor without turning ordinary commits into a slow or
network-dependent workflow. The design separates four concerns:

1. fast deterministic static checks at pre-commit;
2. fixed-seed unit and contract semantics at pre-push;
3. complete compatibility, coverage, packaging and history checks in CI; and
4. mutable external intelligence such as vulnerability advisories in scheduled
   security/weekly jobs.

## Implemented changes

- Initially aligned local/pre-commit/CI resolution on uv 0.12.7. A later
  development-infrastructure follow-up on the same date moved the exact
  developer/CI toolchain pin to the direct `uv` dev dependency plus `uv.lock`
  (currently 0.12.21), while `[tool.uv].required-version` became a reviewed
  0.12.x compatibility range so Dependabot's bundled uv can operate.
- Updated the lock only for the known vulnerable `urllib3` and `virtualenv`
  paths; the resulting lock audits clean.
- Enabled pytest strict mode.
- Isolated watchdog system tests from the Pi's real USB bus. The hardware
  observer itself remains covered with a synthetic sysfs tree.
- Removed the only top-level import cycle by extracting low-level logstats
  parsing helpers while keeping historical `binnacle.logstats` helper access.
- Added six blocking Import Linter contracts for composition roots, watchdog
  isolation, tool independence and cycle freedom. The custom AST architecture
  checker remains complementary.
- Expanded stable Ruff rule families and strengthened mypy for production
  modules in the existing single mypy pass.
- Added TOML, portability, executable/shebang, debugger, pyproject, tox and
  GitHub Actions semantic checks plus pre-commit's own configuration meta
  checks.
- Changed the uv lock hook from mutation to `uv lock --check --offline`.
- Kept Gitleaks staged-secret scanning locally and added a manual full-history
  alias used by CI.
- Moved `pip-audit` from the lint/dev path into a separate `security`
  dependency group and daily workflow.
- Added `--suite fast` to the canonical two-lane runner and made it the only
  pre-push hook.
- Fixed CI's pytest-randomly seed at 12345. The weekly flake job retains
  multiple seeds.
- Added a dedicated wheel-packaging job with a hash-constrained setuptools
  build dependency, rather than running the wheel build in every Python job.
- Cached pre-commit environments in the quality job.

## Architecture contracts

`uv run lint-imports --no-logo` currently checks 98 production files and 290
static dependencies. All six contracts are blocking:

1. `tools-only-server`
2. `watchdog-isolated`
3. `server-not-dependency`
4. `tool-modules-independent`
5. `watchdog-acyclic`
6. `top-level-acyclic`

New portability abstractions should strengthen these contracts rather than add
ignored paths to them.

## Measured local baseline

Measurements are from the Pi 5 development host with four pytest workers and
seed 12345. This table is a historical snapshot from the hardening round, not
a source of truth for current test counts, timings, or dependency versions:

| Gate | Result | Wall time |
| --- | --- | ---: |
| pre-commit all files, warm cache | pass | 16.48 s |
| pre-push fast suite | pass | 17.54 s |
| full two-lane suite | 1409 pass + 2 no-xdist pass, 4 skip | 30.15 s |
| coverage policy | 94 production modules, 0 errors | 53.01 s |
| empty-cache hash-constrained wheel test | pass | 3.47 s |
| full Git-history Gitleaks scan | pass | 6.10 s |
| runtime dependency audit | no known vulnerabilities | under 2 s after setup |
| development dependency audit | no known vulnerabilities | under 2 s after setup |

The first actionlint pre-commit environment creation is intentionally excluded
from the warm pre-commit number: pre-commit compiles the Go hook once and then
reuses its cache. GitHub CI caches `~/.cache/pre-commit` by OS, Python version
and pre-commit configuration hash.

## Important boundaries

- Vulnerability audits are not commit determinism: advisory databases can
  change while source does not.
- Mutation, flake, production-usage and latency work remain in the existing
  weekly quality run; they are intentionally too expensive or externally
  variable for commit hooks.
- The current unit/contract population still contains intentional Linux/POSIX
  behaviour. Do not claim macOS compatibility merely because the static gates
  are portable. The forthcoming architecture refactor must establish explicit
  platform-neutral seams before a macOS CI test population is promoted.
- `master` is now protected by the version-controlled `master deployment gate`
  ruleset. It requires the repository CI checks, blocks deletion and
  non-fast-forward updates, and deliberately preserves the CI-first direct
  deployment model. See `docs/github-governance.md` for the current policy.

## Developer workflow

`DEVELOPMENT.md` is the canonical current workflow. Bootstrap a fresh clone or
worktree with:

```bash
uv run scripts/dev.py bootstrap
```

That command synchronizes the locked development environment, installs every
configured Git-hook type, and runs the read-only development doctor. Current
explicit gate commands and their ownership live in `DEVELOPMENT.md`,
`docs/testing.md`, and `docs/quality-gates.md`; do not copy them back into this
historical hardening record.
