# Testing strategy

Binnacle's test suite is organized by **what kind of contract a test proves**,
not by the date a regression was found. The suite is deliberately safe to run
on the development Raspberry Pi: tests must not alter the host's network,
services, kernel modules, routes, or power state.

## Layout

| Directory | Responsibility | Typical examples |
| --- | --- | --- |
| `tests/unit/tools/` | One MCP tool or a small local helper in isolation | file read/write/edit/list/search |
| `tests/unit/core/` | Pure or mostly local core logic shared across tools | text handling, statistics, property tests |
| `tests/integration/` | Multiple Binnacle components cooperating across an internal boundary | authenticated HTTP MCP, config loading, CLI, jobs, logging, state-machine flows |
| `tests/contracts/` | Externally visible protocol and schema contracts | MCP annotations, input validation, visibility, descriptions, output schemas, surface pins, golden outputs |
| `tests/system/` | Raspberry Pi/Linux system behaviour modelled with fakes or guarded probes | doctor, uplink, watchdog, Webmin statistics |
| `tests/scripts/` | Repository maintenance and analysis scripts | usage analysis |
| `tests/live/` | Explicit opt-in read-only checks against the deployed Raspberry Pi | active server unit, authenticated localhost MCP smoke |

`tests/conftest.py` is intentionally global. Its autouse safety fixture blocks
host-mutating subprocess commands so an accidental test cannot change the
machine's real network or services.
`tests/system/conftest.py` additionally replaces watchdog cycle USB-bus
discovery with an empty synthetic observation by default. Hardware helpers are
tested separately against synthetic sysfs trees; system tests must not acquire
results from the development Pi's real USB inventory.

Tests that invoke Git against a fixture or other foreign repository must clear
the repository-local Git environment before spawning that command. Git hooks
export values such as `GIT_DIR` and `GIT_WORK_TREE`; inheriting them can redirect
an otherwise explicit `git -C ...` or `git init PATH` back to Binnacle's real
repository metadata. Build the child environment by removing every name
reported by `git rev-parse --local-env-vars`. The regression coverage is
`test_git_root_clears_repository_local_git_environment`.

## Placement rules

Put a test at the lowest level that proves the behaviour without lying about
its dependencies.

- Use `unit/` when one module can be exercised without a live service or a
  multi-component workflow.
- Use `integration/` when the value comes from components working together,
  including authenticated HTTP workflows, configuration precedence, packaging,
  concurrency, or model/state-machine sequences.
- Use `contracts/` when a failure means an MCP client could observe an
  incompatible API, schema, annotation, or description.
- Use `system/` for behaviour that represents Linux, networking, services, or
  Raspberry Pi host state. These tests still must not mutate the real host.
- Use `scripts/` only for code under `scripts/`; production package behaviour
  belongs in one of the other groups.
- Use `live/` only for read-only checks against the actually deployed host.
  Every live test must skip unless `BINNACLE_LIVE=1` is explicitly set.

The user-scenario and failure-mode inventory is `docs/test-scenarios.md`. Use
that matrix when adding or reviewing a workflow: coverage percentage alone does
not prove that the real user path or failure boundary is represented.

A regression test belongs beside the behaviour it protects. Historical context
may be kept in the test docstring when it explains a non-obvious requirement,
but dates are not a directory structure.

## OS independence / FastMCP Native Architecture acceptance

The accepted Stage 1 plan defines OI-01–OI-12 and FM-01–FM-08.
During implementation run focused dependent tests only; at OS7 run
the normal two-lane complete suite, coverage, compatibility, CI and
package gates. Reuse the immutable OS0 raw MCP baseline rather than
rewriting goldens when an assertion differs.

- `tests/integration/test_os_pure_application.py` verifies three child
  servers and eight tools against a fake Commands backend with Linux
  imports deliberately rejected.
- `tests/contracts/test_os_stage1_wire_parity.py` compares exact wire
  schemas, raw aggregate ownership and four client visibility profiles.
- `tests/integration/test_os_job_rpc_cross_version.py` exercises the
  original Git v1.0.1 manager versus current client, then the reverse.
- `tests/unit/core/test_os_job_identity.py` checks pidfd-owned native
  signals, boot/PID/descendant reuse, target membership and fail-closed
  errors; OS-neutral `job_stop` also runs with a fake lease.
- `tests/unit/core/test_os_independence_paths.py` covers root aliases,
  changes to canonical aliases, escapes and permission errors.
- `tests/scripts/test_os_stage1_inventory.py` proves all current
  production Python modules and scripts have assigned ownership.

See `docs/os-independent-stage1-architecture.md` for deliberate
filesystem TOCTOU and platform capability limitations. The tests
do not authorize an unattended production Job Manager restart.

## Normal commands

### FastMCP composition contracts

`tests/contracts/test_server_composition.py` checks three distinct views:
the root-local inventory, raw aggregate multiplicity before wire deduplication,
and the ordered client-visible surface. Reuse the existing surface hashes;
duplicate tools can pass those hashes while failing the raw ownership contract.
Keep these assertions when changing a mount or focused child factory.

The factory/bootstrap, native pipeline, standalone domain workflows, and mounted
HTTP context tests live in separate integration modules. The integration pipeline
file is `test_composition_pipeline.py`: test basenames must remain unique across
these non-package test directories. `tests/unit/core/test_tool_order.py` checks the
native listing Transform's stable, lossless ordering independently of its rank
table. Production factories use native lifetimes and explicit local
`on_duplicate="error"`; cross-provider conflict behavior remains native and
duplicate ownership checks belong in tests.

### Managed suite

Use the supported two-lane runner for fast full-suite feedback:

```bash
uv run python scripts/run_test_suite.py
```

The runner executes two complementary lanes. Tests matching
`-m "not no_xdist"` may run in xdist workers; tests marked `no_xdist` run in
a separate ordinary pytest process. The marker means exactly "this test must
run in a normal pytest process, not an xdist worker". It does **not** mean that
the test is skipped or removed from the full suite. The current marked tests
inspect their own process command line or environment, so xdist worker identity
would invalidate the contract they are testing. The current marked nodes are:

- `tests/unit/core/test_units.py::test_proc_cmdline_reads_this_process`;
- `tests/system/test_doctor.py::test_process_environ_reads_own_process`.

Worker count resolves in this order: explicit `--workers`,
`BINNACLE_TEST_WORKERS`, then `min(4, os.cpu_count() or 1)`. A resolved
worker count of one disables xdist entirely for the parallel-safe lane. On the
Pi 5, use the fixed benchmark form when a reproducible performance measurement
is needed:

```bash
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
```

The same runner owns the pre-push population. `--suite fast` selects only unit
and contract tests while preserving the same parallel-safe / `no_xdist` split:

```bash
uv run python scripts/run_test_suite.py --suite fast --seed 12345
pre-commit run --hook-stage pre-push --all-files
```

Do not replace this with a direct `pytest -n` command: the ordinary-process lane
is part of the test contract. Repository bootstrap is canonical in
DEVELOPMENT.md; uv run scripts/dev.py bootstrap invokes pre-commit install,
which installs both configured pre-commit and pre-push hook types.

For direct single-process pytest feedback:

```bash
uv run pytest -q
```

Run one level:

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/contracts -q
uv run pytest tests/system -q
uv run pytest tests/scripts -q
```

Run the opt-in read-only deployment smoke only when you intentionally want to
check the current Raspberry Pi deployment:

```bash
BINNACLE_LIVE=1 uv run pytest tests/live -q
```

Run the authoritative per-module branch-coverage gate with the same fixed seed
used by CI:

```bash
uv run tox -e coverage-policy -- --seed 12345
```

Run the supported Python matrix on the four-core development Pi with
sequential tox environments and four pytest workers inside each environment:

```bash
env BINNACLE_TEST_WORKERS=4 uv run tox run
```

Step 3.4 benchmarked bounded tox-level alternatives on this host. The
two-environment/two-worker strategy was less than 10% faster, so the frozen
tie rule selects this simpler sequential-tox policy. Keep this as a local
matrix policy; do not copy the local tox scheduling decision into GitHub
Actions without separate CI-specific evidence.

Compatibility tox environments run `scripts/run_test_suite.py` and do not
collect coverage. The dedicated `coverage-policy` tox environment owns
coverage instrumentation and the semantic 95/90 per-module gate. In GitHub
Actions, Python 3.10, 3.11, 3.12, and 3.14 remain compatibility jobs while
Python 3.13 runs `coverage-policy`. Both paths use pytest-randomly seed `12345`
for reproducibility; the weekly flake hunt, not ordinary CI, explores multiple
seeds. CI does not hard-code a Pi worker count: the repository runner resolves
its bounded worker count from the CI host. A separate Python 3.13 packaging job
builds the sdist, rebuilds the wheel from that sdist, and performs one clean
locked installation/smoke, so the compatibility/coverage lanes continue
to skip `test_wheel_artifact.py` instead of repeating distribution work five
times. CI writes separate JUnit XML reports for each parallel-safe and
`no_xdist` lane, includes bounded slow-test durations, and uploads those
reports only when a test or coverage job fails. Each artifact is retained
for seven days. Passing runs retain no extra artifacts.

Before a baseline or merge commit, run:

```bash
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
```

`testpaths = ["tests"]` in `pyproject.toml`  is intentional. Developer tools
such as `mutmut` create test-shaped files outside this tree; default pytest
discovery must never collect those copies.

## Packaging and dependency security

`tests/integration/test_wheel_artifact.py` copies the publishable project into a
temporary directory, builds a source distribution with `--no-sources`, then
builds the wheel from that sdist using `build-constraints.txt`. The build
backend is pinned to an exact setuptools artifact with reviewed SHA-256 hashes,
and `uv build --require-hashes` refuses an unexpected artifact. The test then
creates a fresh Python environment, installs the exact locked runtime
dependencies with hash verification plus the local wheel, checks installed
metadata/imports, and
smokes only the command entry points whose help path is side-effect free. This
test runs once in the dedicated CI packaging job and remains runnable locally.
`docs/release-readiness.md` owns the complete distribution contract and the
boundary between artifact validation and future publication.

Dependency vulnerability intelligence is intentionally separate from
deterministic code gates. `.github/workflows/security.yml` runs daily and on
manual dispatch. It installs only the `security` dependency group, exports the
locked runtime set and the locked development-tool set separately, and audits
each with `pip-audit --no-deps --disable-pip`. A new advisory can therefore
make the security workflow red without redefining whether an unchanged commit
was syntactically or semantically valid.

The quality CI job still runs staged-secret protection through pre-commit and,
with full Git history fetched, runs the manual `gitleaks-history` hook over the
entire repository history.

## Deploy and live smoke

`tests/scripts/test_deploy_ci.py` checks exact-candidate required CI eligibility,
including partial reruns, trusted check identity, complete pagination, and changes
during observation. `test_deploy_flow.py` exercises that evaluator through the
existing deploy flow with fake GitHub responses and retains quiet-window,
environment-sync, rollback, and atomic-push assertions. These tests never mutate
production services or remote refs.

Production runs from the `~/Projects/binnacle` checkout, so a new `master` there
is a deploy. Deploy only through the gate (quality guard plan, step 2):

```bash
.venv/bin/python scripts/deploy_smoke.py deploy <sha>
```

It requires a clean tracked checkout, a fast-forward target, and successful
CI for that exact commit. Untracked files are allowed only under `docs/`. It
waits for a quiet moment (no tool call for 30 s), then fast-forwards. In dev
mode, Python changes under `src/` use the normal auto-reload. A change to
`pyproject.toml` or `uv.lock` instead synchronizes the checkout with
`uv sync --locked --group dev` and explicitly restarts the MCP service so the
smoke uses the new locked environment. The stable jobs service is never
restarted by this flow. Then it runs the live smoke. On success it atomically
pushes `master` and `proof-of-concept`. On failure it resets `master` to the
previous commit, restores the old locked environment when necessary, reloads or
restarts the MCP service, confirms the rollback with a second smoke, and pushes
nothing.

The live smoke (`scripts/deploy_smoke.py`, checks in `scripts/smoke_checks.py`)
checks the running server as a client would:

- `binnacle doctor` passes, and `tools/list` answers with authentication;
- every tool answers one call with an `e2e-smoke-` nonce, which the usage
  statistics treat as test traffic; the calls touch only a fixture under
  `/tmp` and short jobs, all removed afterwards;
- the journal holds a tool_call and a tool_result line for each call, and no
  traceback;
- the unit's RSS and start-up time (from the main process's start to the
  server's `event=config` line) are within 1.25 times the baseline in
  `~/.local/state/binnacle/smoke/baseline.json`. The first run records the
  baseline; `--rebaseline` records a new one after an intended change.

`--full` adds `binnacle-tunnel doctor` and `binnacle-watchdog doctor
--no-probe`. The first output line is `OK`, `WARN` or `ALERT` for
`cron-report`; `--quiet-ok` prints nothing when all checks pass. The daily
run (install by hand):

```text
50 6 * * * /home/grammy-jiang/.local/bin/cron-report --job binnacle-smoke /home/grammy-jiang/Projects/binnacle/.venv/bin/python /home/grammy-jiang/Projects/binnacle/scripts/deploy_smoke.py --full --quiet-ok
```

`tests/live/` remains the opt-in pytest version of the same idea
(`BINNACLE_LIVE=1`).

## Weekly quality run

`scripts/weekly_quality.py` is step 3 of the quality guard plan
(`docs/quality-guard-plan-2026-09-27.md`): the checks that are too slow for
every commit, once a week, under the owner's isolation rules of 2026-09-28
(other projects run on this host at the same time). What runs, in order:

1. **usage** (`scripts/weekly_usage.py`): the week's production numbers,
   read-only from the journal. p50 and p95 per tool, without the calls that
   carry an `e2e-` nonce, are judged only for read_file, edit_file and
   write_file (30 calls on both sides; WARN above 1.25 times the first
   run's p95 plus 50 ms). list_files and search_text take as long as the
   tree the model chose, and run_command, job_status and stop_job as long as
   the command or the wait, so they are reported only. The model-step and
   job-polling metrics of `scripts/usage_breakdown.py` WARN when solo
   job_status polls take 25 % more of the steps, or excess polls per 1000
   steps rise by 25 %, against the newest `docs/usage-baselines/` file with
   step metrics (else the 2026-09-27 figures), with at least 300 steps.
2. **bench** (`scripts/weekly_bench.py`): a fixed benchmark against a
   temporary server from the weekly clone on a free port of 127.0.0.1, with
   its own configuration, token, fixtures and job spool (embedded owner)
   under `/tmp/binnacle-bench-<run>/`, deleted afterwards. Eleven cases,
   20 rounds after two warm-up rounds; client and server share the scope's
   CPU. WARN when a case's p95 is above 1.25 times the baseline p95 plus
   5 ms. The first run records the baseline; `--rebaseline` records a new
   one after an intended change.
3. **flake**: the full suite once per seed (five by default), each run with
   its own pytest-randomly seed, in the two lanes of
   `scripts/run_test_suite.py`. The parallel lane's four workers share the
   scope's one CPU: that is the load, and it stays inside the scope. Every
   lane keeps its junit XML and its log, and the report names each failing
   test with its seed. CI passed on the commit, so a failure here is a
   flaky test: fix or quarantine it within a week.
4. **mutation**: two core modules a week from `quality-policy.json`, in
   rotation, `mutmut run --max-children 1` in the weekly clone, starting
   from an empty `mutants/`. WARN below 80 % killed. A module stopped by its
   timeout or by production calls is "incomplete", with its partial
   numbers and a WARN (never a green pass). Incomplete, empty or partially
   checked module results do not advance the mutation rotation; the same
   modules remain due on the next quiet-window attempt.

Isolation:

- It never runs in the production checkout. Its own clone
  (`~/.local/state/binnacle/quality-weekly/checkout`, from GitHub) is
  brought to `origin/master` with `uv sync --frozen`, and the run goes on
  in that clone's copy of the script. It never calls the production
  server; it only reads the journal.
- Every job runs in its own user scope: `systemd-run --user --scope -p
  CPUQuota=100% -p CPUWeight=idle -p MemoryMax=2G -p TasksMax=1024 -p
  RuntimeMaxSec=<limit>`, then `nice -n 19 ionice -c3 timeout`. Measured on
  this host (2026-09-28): the user manager delegates only the cpu and pids
  controllers, so the CPU limit, the CPU weight, TasksMax and RuntimeMaxSec
  hold and MemoryMax is ignored. The runner therefore sums the scope's RSS
  every 10 s and stops the scope above 2 GiB. The NVMe queue has no I/O
  scheduler (`none`), so ionice changes nothing there. Before anything
  runs, a probe checks that `cpu.max` reads `100000 100000` and `cpu.idle`
  reads `1` inside a scope; if not, the run is an ALERT and nothing runs.
- `CPUWeight=idle` is what protects production. The scopes sit in the user
  manager's `app.slice` beside `binnacle-mcp`, `binnacle-jobs` and
  `binnacle-tunnel`, and get CPU only when those do not want it. `nice`
  ranks processes only inside one cgroup, so nice 19 alone did not protect
  it. The other projects run outside the user manager (in a login session
  scope); for them the one-CPU cap and the load gate are the bound.
- A job starts only when production had no tool call for 5 minutes, the
  1-minute load is below 2.0 (`--load-max`) and 3 GiB of memory are
  available. It waits up to 20 minutes, else it is skipped. While it runs,
  checked every 10 s, a production tool call, less than 1 GiB available or
  the scope above 2 GiB stops it: the scope is stopped by its exact unit name, and the job
  is never paused, because a paused test run or benchmark gives false
  results. A job stopped by production calls gets one more try at the next
  quiet moment. A job that found no quiet moment, or was stopped twice, is
  a WARN: a week without the check must not look like a clean week.
- Each job has a timeout, the run a budget of 3 hours, and the flake hunt
  at most half of what is left when it starts. The jobs see the settings'
  defaults, as CI does (`BINNACLE_CONFIG_FILE` is an empty file), and never
  the production job manager (`BINNACLE_MANAGED_DEPLOYMENT` is dropped).

Results: each run keeps `report.txt` (the text of the mail), `report.json`,
the junit files and every job's log in
`~/.local/state/binnacle/quality-weekly/runs/<run>/` (the newest eight). The
baselines and the mutation rotation are in the same state directory. The
report ends with the run's timeline and its impact: load and memory while
the jobs ran, and the production calls in the run's window against the
hour before.

First run (attended, 2026-09-28 03:02-03:41, two seeds and one mutation
module, from a cron-like environment with no user-bus variables):

- **Durations:** usage 34 s (a week: 31,594 calls, 24,528 model steps),
  bench 38 s, flake 108 + 6 s and 78 + 10 s per seed (1317 and 2 tests
  passed each time). Every job waited for the gate first: the jobs ran 4.6
  minutes of the 40. The foreign load (a browser, another project's test
  runs) kept the 1-minute load between 2 and 10 all night.
- **Findings:** usage WARN, solo job_status polls 18.6 % of the steps
  against 17.0 %, excess polls 49.3 against 29.5 per 1000 steps (the
  2026-09-27 wait change is under review until 2026-10-11). Flake hunt
  clean in that run. One flaky test was then found by the same suite in a
  1-CPU scope: `test_stop_escalates_to_sigkill_when_sigterm_ignored`
  stopped its job before the job ignored SIGTERM (signal 15 instead of 9);
  with three busy loops in the scope the old test failed 1 of 5 runs and
  the fixed one 0 of 15.
- **Production:** no production call arrived during the run, so no job was
  stopped. Load median 2.36 and maximum 4.35 while jobs ran; MemAvailable
  never below 5.1 GiB; the flake scope's RSS 444 MiB, throttled 134 times
  in its first 45 s.
- **Impact on a server beside the jobs** (a benchmark server with
  production's priority, measured before, during and after a flake lane):
  at the default CPU weight, read_file p50 20.0 / 32.4 / 20.1 ms and
  search_text p50 44 / 94 / 50 ms; with `CPUWeight=idle` 18.5 / 24.0 /
  18.2 ms and 40.6 / 54.2 / 40.2 ms (p95 during the lane: 65 and 133 ms).
  What remains is shared hardware and kernel work. It lasts only until the
  next 10 s check sees a production call and stops the job.
- **Mutation:** the first attempt (04:26-04:41) ran mutmut over all 95
  source files (8.5 minutes of generation), and its stats pass stopped at a
  test that reads `benchmarks/`, which `./mutants` did not hold. Both are
  fixed: `only_mutate` limits generation to the week's modules, and
  `also_copy` lists every path the suite reads (the whole suite passes in a
  copy of that layout). The fixed job then found no quiet moment: four
  gated attempts between 05:02 and 06:30 were skipped (load 3.9 to 9.6),
  so the first measured mutation result is the first Sunday run's. That is
  the gate working as designed.

By hand (from any checkout; it updates and uses its own clone):

```bash
.venv/bin/python scripts/weekly_quality.py [--only usage,bench] [--seeds 2] [--mutation-modules 1] [--ref origin/<branch>]
```

The weekly run, Sunday 00:10, so that the budget ends before the 03:30
backup (install by hand):

```text
10 0 * * 0 /home/grammy-jiang/.local/bin/cron-report --job binnacle-weekly-quality /home/grammy-jiang/.local/state/binnacle/quality-weekly/checkout/.venv/bin/python /home/grammy-jiang/.local/state/binnacle/quality-weekly/checkout/scripts/weekly_quality.py --quiet-ok
```

## Coverage policy

Coverage is a regression signal, not a target to game. The authoritative gate
is per module: core logic must reach at least 95% branch coverage from the unit
suite alone; every other production module must reach at least 90% branch
coverage from the full appropriate suite. Repository-average coverage remains
a trend metric only and cannot make a weak module pass.

`uv run tox -e coverage-policy` uses
`scripts/run_coverage_policy.py` to execute every managed test exactly once
across four lanes: unit parallel-safe, unit `no_xdist`, non-unit
parallel-safe, and non-unit `no_xdist`. The unit-only JSON report is written
after the two unit lanes and before any non-unit test. The full JSON is written
after the two non-unit lanes, then the existing semantic checker applies the
95/90 policy. Only the two parallel-safe lanes use xdist; the `no_xdist`
lanes always run in ordinary pytest processes.

The executable policy and module classification live in `quality-policy.json`;
`docs/quality-gates.md` documents the full workflow. There are currently no
temporary coverage floors: every core module satisfies the 95% unit-branch
target and every other production module satisfies the 90% full-suite branch
target. This hardening also compares the full coverage JSON with the actual
non-`__init__` Python sources, rejecting omitted or deleted module records.
The same full coverage pipeline records `scripts/` branch coverage. It
requires all 46 current top-level script modules to appear, even if unexecuted;
12 release/security/quality scripts have reviewed minimum floors in
`quality-policy.json`, with 90% as the eventual target. The first measured
baseline used `tests/scripts` with seed 12345: 46 scripts were inventoried
and the only three below 90% among the twelve were
`check_architecture.py` (83.15%), `check_coverage_policy.py` (73.79%) and
`github_governance.py` (52.31%). Floors preserve existing behaviour while
further failure-path tests pay down debt; no missing source can pass silently.

The hardening round finished with 190 unit tests and 726 tests in the full
suite. Those counts are a dated baseline, not a permanent target; run the gate
for the current result. New tests should continue to focus on meaningful
behaviour, error handling, fault injection, concurrency, state transitions,
and regressions seen in real use rather than on mechanically increasing a
percentage.

## Property and mutation testing

Property tests live in `tests/unit/core/test_properties.py` and cover invariants
where example-only tests are weak.

Mutation testing is intentionally on demand because it is expensive on the
Raspberry Pi. Run it per module, for example:

```bash
uv run mutmut run '*textio*'
uv run mutmut results
```

Do not run the entire mutation tree as a routine hook. The weekly quality run
("Weekly quality run" above) covers two core modules a week in rotation.

## Pins and snapshots

Step 1 of `docs/quality-guard-plan-2026-09-27.md` (2026-09-28) added guards
that fail on any change to what a client sees, to the runtime dependencies or
to the job-spool format. A change is then a decision: update the pin in the
same commit and give the reason in the commit message. They live in
`tests/contracts/`:

| Guard | Test | What it pins |
| --- | --- | --- |
| Tool surface | `test_tool_surface.py` | per client profile (ChatGPT, client name `openai-mcp`: 6 tools; default: 8) the served tools in order, and per tool a sha256 over the name, description, output schema, annotations and normalized input schema; the sha256 of the server instructions |
| Token budget | `test_surface_tokens.py` | the o200k_base tokens of what ChatGPT is served (the instructions, and per tool the name, description and both schemas): 2140 on 2026-09-28, at most 5 % more |
| Golden outputs | `test_golden_outputs.py`, `snapshots/` | each tool's masked result on fixed fixtures in `tmp_path`, with its size budget (structured bytes and tokens) |
| Dependencies | `test_dependency_pin.py` | the `[project]` dependencies list exactly, each entry with its reason |
| Job spool | `test_job_spool_compat.py`, `fixtures/job_spool/` | a spool in the 2026-09-28 format stays readable: job_status and the listing |

To update a guard on purpose:

- **Surface or instructions:** run `uv run pytest
  tests/contracts/test_tool_surface.py`, copy the new hash from the failure
  into `SURFACE_SHA256` or `INSTRUCTIONS_SHA256`, and give the reason in the
  commit message.
- **Token budget:** a surface up to 5 % over `TOKEN_BUDGET` passes. For more,
  set `TOKEN_BUDGET` to the measured count and add a `BUDGET_CHANGES` line
  with the date and the reason; the test refuses a budget without one.
- **Golden outputs:** rewrite the snapshots with

  ```bash
  BINNACLE_UPDATE_SNAPSHOTS=1 uv run pytest tests/contracts/test_golden_outputs.py
  ```

  then review `git diff tests/contracts/snapshots` (the `size` lines show
  growth) and give the reason in the commit message. A new case needs its
  name in `CASES`; a snapshot file without a case fails the suite.
- **Dependencies:** edit `pyproject.toml` and `RUNTIME_DEPENDENCIES` together;
  the new entry's value is its reason.
- **Job spool:** never edit a dated fixture. A format change adds a new dated
  directory with its own tests and keeps every old one readable.

`golden_support.py` masks what changes from run to run: the tmp directory
becomes `<tmp>`, job ids become `<job-1>`, `<job-2>` in order of appearance,
timestamps, durations and process ids become `"<number>"`, and decimal
seconds in the text become `<s>`. The sizes are measured on the masked
result, so they do not depend on the machine. The pins hold on every
supported Python: the surface hash normalizes the input schema, and the
token count reads it in the form Python 3.11+ serves. They assume the
default tool settings: `BINNACLE_CONFIG_FILE` pointing to a nonexistent file
gives them, and CI's configuration sets only the roots. A local
`config.toml` that changes a tool's limits changes its surface and its
outputs.

## Test timing policy

Production timing defaults are not test-performance knobs. In particular,
production job background warm-up remains 1.0 second. Selected job-heavy
integration modules explicitly opt in to the non-autouse
`_short_job_warmup` fixture in `tests/integration/conftest.py`, which uses a
0.05-second warm-up only inside those tests. The golden-output tests set the
same warm-up in their own fixture (`tests/contracts/test_golden_outputs.py`).

Real elapsed time is retained where wall time is itself part of the contract.
The retained coverage includes:

- all blocking-window concurrency checks in
  `tests/integration/test_job_status_blocking_guard_concurrency.py`;
- real job-status expiry, cap, and early-return checks in
  `tests/integration/test_job_status_blocking_guard.py` and
  `tests/integration/test_jobs_lifecycle.py`;
- subprocess handoff/back-pressure and signal-escalation paths in the jobs
  integration tests and `tests/integration/test_job_telemetry.py`;
- all rendered Bash readiness checks in
  `tests/system/test_tunnel_readiness.py`, especially the two timeout cases;
- real child timeout/reaping and slow-consumer checks in
  `tests/unit/core/test_search_text_stream.py`.

These tests may use shortened, test-specific timing where the production
duration is not the contract, but they still exercise real elapsed time and OS
boundaries. Do not convert them wholesale to fake clocks merely to reduce suite
duration.

## Benchmark reproduction

For comparable timing data, use the same source snapshot, dependency lock,
Python version, test selection, host, and random seed. This performance plan
uses seed `12345`. Before every timed run record `nproc` and
`cat /proc/loadavg`; if unrelated work has pushed the one-minute load above
1.5, wait for that foreign load to clear before treating the timing as clean.

Fast full-suite benchmark:

```bash
nproc
cat /proc/loadavg
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  uv run python scripts/run_test_suite.py --workers 4 --seed 12345
```

Selected local five-interpreter matrix benchmark:

```bash
uv run tox run --notest
nproc
cat /proc/loadavg
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  env BINNACLE_TEST_WORKERS=4 uv run tox run -- --seed 12345
```

The complete 2026-09-24 A/B/C tox scheduling measurements and historical
2026-09-22 results are retained in
`docs/long-command-performance-and-distribution.md`.

## Host-safety rule

Tests must be deterministic and must not repair, restart, reconfigure, or
otherwise mutate the machine they run on. If a system-level scenario needs a
command such as `nmcli`, `systemctl`, `ip`, `iw`, or `sudo`, inject or
monkeypatch the command boundary. `tests/conftest.py` is the final safety net,
not a substitute for explicit fakes.

A test that needs intentional physical hardware interaction is a manual
validation procedure and should be documented separately rather than hidden in
the automated pytest suite.

## Watchdog scenario suites

The original 4,000-line watchdog scenario module was split only after the
watchdog POC gained stable production boundaries, now owned by
`binnacle.companions.watchdog.ops` (the old `binnacle.ops.watchdog` import
was retired in G7). The system tests follow those responsibilities:
policy, USB recovery, NetworkManager preference, device observation, service
repair, fast-path failover, tunnel affinity, concurrency, and audit
regressions.

Shared fakes live in `tests/watchdog_support.py`; individual scenario modules
remain below the repository's 500-line hard limit. This is the preferred
pattern for future large suites: create a real production seam first, then let
the tests follow that seam instead of splitting by arbitrary line ranges.

## Baseline review findings

The managed-history review classified the existing tests rather than treating
the former flat `tests/` directory as a permanent design.

- Tool-local filesystem behaviour belongs under `unit/tools/`.
- Pure shared helpers, invariants, parsing, and identity handling belong under
  `unit/core/`.
- Jobs, logging, CLI composition, and authentication behaviour cross
  component boundaries and therefore remain `integration/` (the
  indexed-context service tests left with the pilot on 2026-09-28).
- MCP schema and description guarantees are explicit `contracts/`.
- Watchdog, uplink, doctor, Webmin history, and journal reconstruction model
  Linux or Raspberry Pi host behaviour and remain `system/`.
- Repository analysis programs and their tests are paired under `scripts/`
  and `tests/scripts/`.

The hardening review subsequently decomposed the oversized production modules
and their corresponding large test suites. `quality-policy.json` now has no
legacy module-size exceptions and no temporary coverage floors. The automated
gates therefore represent the final policy directly rather than a migration
baseline.
