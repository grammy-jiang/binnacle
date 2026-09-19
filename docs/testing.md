# Testing strategy

Binnacle's test suite is organized by **what kind of contract a test proves**,
not by the date a regression was found. The suite is deliberately safe to run
on the development Raspberry Pi: tests must not alter the host's network,
services, kernel modules, routes, or power state.

## Layout

| Directory | Responsibility | Typical examples |
| --- | --- | --- |
| `tests/unit/tools/` | One MCP tool or a small local helper in isolation | file read/write/edit/list/search |
| `tests/unit/core/` | Pure or mostly local core logic shared across tools | text handling, visibility, statistics, property tests |
| `tests/integration/` | Multiple Binnacle components cooperating across an internal boundary | HTTP auth, CLI, jobs, logging, indexed context |
| `tests/contracts/` | Externally visible protocol and schema contracts | MCP annotations, descriptions, output schemas |
| `tests/system/` | Raspberry Pi/Linux system behaviour modelled with fakes or guarded probes | doctor, uplink, watchdog, Webmin statistics |
| `tests/scripts/` | Repository maintenance and analysis scripts | usage analysis, indexed-pilot analysis |

`tests/conftest.py` is intentionally global. Its autouse safety fixture blocks
host-mutating subprocess commands so an accidental test cannot change the
machine's real network or services.

## Placement rules

Put a test at the lowest level that proves the behaviour without lying about
its dependencies.

- Use `unit/` when one module can be exercised without a live service or a
  multi-component workflow.
- Use `integration/` when the value comes from components working together,
  even if sockets or external services are replaced with local fakes.
- Use `contracts/` when a failure means an MCP client could observe an
  incompatible API, schema, annotation, or description.
- Use `system/` for behaviour that represents Linux, networking, services, or
  Raspberry Pi host state. These tests still must not mutate the real host.
- Use `scripts/` only for code under `scripts/`; production package behaviour
  belongs in one of the other groups.

A regression test belongs beside the behaviour it protects. Historical context
may be kept in the test docstring when it explains a non-obvious requirement,
but dates are not a directory structure.

## Normal commands

Fast feedback for the managed suite:

```bash
uv run pytest -q
```

Run one level:

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/contracts -q
uv run pytest tests/system -q
```

Run with the branch-coverage gate:

```bash
uv run pytest tests/ -q --cov --cov-fail-under=86.9
```

Run the supported Python matrix:

```bash
uv run tox
```

Before a baseline or merge commit, run:

```bash
uv run pytest tests/ -q --cov --cov-fail-under=86.9
uv run pre-commit run --all-files
```

`testpaths = ["tests"]` in `pyproject.toml`  is intentional. Developer tools
such as `mutmut` create test-shaped files outside this tree; default pytest
discovery must never collect those copies.

## Coverage policy

Coverage is a regression signal, not a target to game. The authoritative gate
is now per module: core logic must reach at least 95% branch coverage from the
unit suite alone; every other production module must reach at least 90% branch
coverage from the full appropriate suite. Repository-average coverage remains a
trend metric only and cannot make a weak module pass.

The executable policy, current ratchet floors, and module classification live
in `quality-policy.json`; `docs/quality-gates.md` documents the full workflow.
New tests should focus on meaningful public behaviour, error handling,
concurrency, state transitions, and regressions seen in real use.

The 2026-09-19 baseline review started at 613 tests and 88.24% branch coverage.
The review then added focused identity and CLI command tests; run the coverage
command above for the current exact count and percentage rather than copying a
potentially stale number into release notes.

The largest remaining coverage gap is indexed-retrieval fallback and error
behaviour. CLI coverage is also deliberately incomplete where a path is only
thin process-launch glue. Improvements should test user-visible behaviour,
failure handling, or a real regression rather than private implementation
details.

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

## Host-safety rule

Tests must be deterministic and must not repair, restart, reconfigure, or
otherwise mutate the machine they run on. If a system-level scenario needs a
command such as `nmcli`, `systemctl`, `ip`, `iw`, or `sudo`, inject or
monkeypatch the command boundary. `tests/conftest.py` is the final safety net,
not a substitute for explicit fakes.

A test that needs intentional physical hardware interaction is a manual
validation procedure and should be documented separately rather than hidden in
the automated pytest suite.

## Large scenario suites

`tests/system/test_watchdog.py` is intentionally retained as one scenario
suite during this baseline cleanup. It has extensive shared fixtures and
encodes a long sequence of network failure and recovery regressions. Splitting
it only by file size would duplicate setup and obscure scenario relationships.

The better trigger for splitting it is a corresponding decomposition of
``binnacle.watchdog` into stable policy, host-observation, action, and lifecycle
boundaries. Until then, section headings inside the module remain the local
navigation mechanism.

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

The review intentionally did **not** split `test_watchdog.py` merely because it
is large. Its size reflects the current size of `binnacle.watchdog`; a future
production-code decomposition should create stable seams first, and the tests
can then follow those seams.

Known follow-up debt:

1. `binnacle.indexed_retrieval` has meaningful fallback/error branches still
   below the rest of the package's coverage.
2. `binnacle.cli` contains process-launch and host-control glue that should be
   covered when a concrete behavioural contract or regression warrants it.
3. Large `doctor` and `watchdog` modules should eventually be decomposed in
   production code; test-file decomposition should follow, not lead, that work.
