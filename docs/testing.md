# Testing strategy

Binnacle's test suite is organized by **what kind of contract a test proves**,
not by the date a regression was found. The suite is deliberately safe to run
on the development Raspberry Pi: tests must not alter the host's network,
services, kernel modules, routes, or power state.

## Layout

| Directory | Responsibility | Typical examples |
| --- | --- | --- |
| `tests/unit/tools/` | One MCP tool or a small local helper in isolation | file read/write/edit/list/search |
| `tests/unit/core/` | Pure or mostly local core logic shared across tools | text handling, indexed logic, statistics, property tests |
| `tests/integration/` | Multiple Binnacle components cooperating across an internal boundary | authenticated HTTP MCP, config loading, CLI, jobs, logging, indexed context, state-machine flows |
| `tests/contracts/` | Externally visible protocol and schema contracts | MCP annotations, input validation, visibility, descriptions, output schemas |
| `tests/system/` | Raspberry Pi/Linux system behaviour modelled with fakes or guarded probes | doctor, uplink, watchdog, Webmin statistics |
| `tests/scripts/` | Repository maintenance and analysis scripts | usage analysis, indexed-pilot analysis |
| `tests/live/` | Explicit opt-in read-only checks against the deployed Raspberry Pi | active server unit, authenticated localhost MCP smoke |

`tests/conftest.py` is intentionally global. Its autouse safety fixture blocks
host-mutating subprocess commands so an accidental test cannot change the
machine's real network or services.

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

## Normal commands

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

Run the authoritative per-module branch-coverage gate:

```bash
uv run tox -e coverage-policy
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
Python 3.13 runs `coverage-policy`. CI does not hard-code a Pi worker count:
the repository runner resolves its bounded worker count from the CI host.

Before a baseline or merge commit, run:

```bash
uv run tox -e coverage-policy
uv run pre-commit run --all-files
```

`testpaths = ["tests"]` in `pyproject.toml`  is intentional. Developer tools
such as `mutmut` create test-shaped files outside this tree; default pytest
discovery must never collect those copies.

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
target.

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

Do not run the entire mutation tree as a routine hook.

## Test timing policy

Production timing defaults are not test-performance knobs. In particular,
production job background warm-up remains 1.0 second. Selected job-heavy
integration modules explicitly opt in to the non-autouse
`_short_job_warmup` fixture in `tests/integration/conftest.py`, which uses a
0.05-second warm-up only inside those tests.

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
watchdog POC gained stable production boundaries under
`binnacle.ops.watchdog`. The system tests now follow those responsibilities:
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
- Jobs, logging, CLI composition, authentication, and indexed-context service
  behaviour cross component boundaries and therefore remain `integration/`.
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
