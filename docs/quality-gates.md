# Repository quality gates

Binnacle uses explicit per-module quality gates. Aggregate metrics are useful for
trend reporting, but they cannot make a weak module pass.

## Python module size

The target is at most 500 physical lines per Python module, with a warning from
451 lines onward. The rule applies to production code, repository scripts, and
tests.

The hardening migration is complete: `quality-policy.json` currently contains
no legacy oversized-module entries. The ratchet mechanism remains available
only to make an explicitly reviewed migration safe; a new module above 500
lines fails immediately.

Run:

```bash
python scripts/check_module_size.py
```

Use `--strict` to see the final target with no legacy allowance.

Splits must follow responsibility boundaries. Shortening a file by compressing
formatting, deleting useful documentation, or creating arbitrary line-number
fragments does not satisfy the intent of the rule.

## Watchdog dependency boundary

The Raspberry Pi watchdog is an operational POC kept in this repository only to
keep the development MCP endpoint reachable. It is not a Binnacle product
feature.

The allowed dependency direction is:

```text
watchdog companion -> Binnacle core
Binnacle core -X-> watchdog companion
```

The companion modules are declared in `quality-policy.json`. The architecture
gate parses imports and dynamic literal imports under `src/binnacle` and rejects
a reverse dependency.

Run:

```bash
python scripts/check_architecture.py
```

The long-term portability test is stronger than an import check: deleting the
watchdog companion must not prevent Binnacle core from building, testing, or
serving MCP.

## Per-module branch coverage

Coverage is enforced per production module, not by repository average.

Core logic modules must reach at least 95 percent branch coverage from
`tests/unit` alone. Other production modules must reach at least 90 percent
branch coverage from the full appropriate test suite.

The current classification is in `quality-policy.json`. There are no
temporary ratchet floors: the final 95/90 targets apply directly to every
production module. The checker still supports temporary floors as a migration
mechanism, but introducing one requires an explicit quality-policy change and
does not change the final acceptance target.

Run the authoritative gate with:

```bash
uv run tox -e coverage-policy
```

The tox environment first runs `scripts/run_coverage_policy.py`, then runs the
existing semantic checker. The coverage runner does not execute the unit suite
twice. It erases stale data, runs unit parallel-safe and unit `no_xdist`
tests, writes the unit-only JSON, then appends non-unit parallel-safe and
non-unit `no_xdist` coverage before writing the full JSON. Only the two
parallel-safe lanes may use xdist; the `no_xdist` tests stay in ordinary
pytest processes and remain part of the coverage population.

To reproduce the report generation directly, for example when comparing JSON
reports module by module, run:

```bash
uv run python scripts/run_coverage_policy.py \
  --seed 12345 \
  --unit-json /tmp/binnacle-unit-coverage.json \
  --full-json /tmp/binnacle-full-coverage.json

uv run python scripts/check_coverage_policy.py \
  --unit-json /tmp/binnacle-unit-coverage.json \
  --full-json /tmp/binnacle-full-coverage.json
```

Ordinary Python tox environments are compatibility gates only:
`python scripts/run_test_suite.py {posargs}`. They intentionally do not carry
`--cov` instrumentation. The supported local matrix remains Python 3.10
through 3.14; GitHub Actions uses 3.10, 3.11, 3.12, and 3.14 for compatibility
and the dedicated Python 3.13 `coverage-policy` job for coverage. Worker count
is resolved by the repository runner rather than hard-coded in CI.

`--strict` ignores any migration floor that may be introduced in the future.
With the current policy it is equivalent to the normal check.

## Test kinds

The suite should use the lowest test layer that proves the behavior honestly.
Beyond example-based unit tests, Binnacle uses or plans to use:

- property and invariant tests for paths, parsers, state and policy;
- model/state-machine tests for lifecycle-heavy code such as jobs and watchdog;
- fault-injection tests for timeouts, permission failures, corrupt state,
  disappearing processes, partial writes and failed external commands;
- concurrency/race tests for jobs, index refresh/query and watchdog paths;
- differential/metamorphic tests such as incremental index update versus clean
  rebuild;
- structured fuzz tests for MCP arguments, logs, config and parsers;
- replay tests derived from real production incidents;
- mutation testing for core modules as an on-demand semantic-strength check;
- clean-wheel install and command smoke tests;
- performance/resource regression checks for bounded operations;
- opt-in read-only Raspberry Pi live smoke tests.

Physical or destructive hardware tests remain manual and must never be hidden in
the default automated suite.
