# Binnacle full test-suite performance optimisation plan

**Date:** 2026-09-24
**Status:** COMPLETED — implementation and final validation finished 2026-09-24; see `docs/test-suite-performance-optimization-progress-2026-09-24.md` for execution evidence.
**Scope:** local and CI execution time of the managed automated Python test suite
**Working repository:** `~/Projects/binnacle-chat-scheduling-design`
**Working branch:** `design/chat-mode-scheduling-v2`
**Required starting commit:** `52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6` (`52ed0bd`)
**Primary host used for the 2026-09-24 investigation:** Raspberry Pi 5, 4 CPU cores, aarch64
**Primary objective:** materially reduce full-suite wall-clock time without weakening test
coverage, test semantics, host safety, Python-version compatibility, or release gates.

---

## 1. Purpose of this document

This document is intentionally self-contained. It is written so that a new AI coding agent
can begin the work with no memory of the previous conversation and without first having to
rediscover why the work exists, what was measured, which risks were found, or what order the
changes should be made in.

The task is **not** "make pytest fast by any means". The task is:

1. preserve the current behavioural confidence of the suite;
2. remove accidental waits and redundant execution;
3. use parallelism only where the tests are actually parallel-safe;
4. keep deliberately real-time tests where real wall-clock behaviour is part of the contract;
5. preserve the per-module branch-coverage policy;
6. preserve the supported Python-version matrix;
7. keep the Raspberry Pi host safe while tests run;
8. make the faster path understandable and maintainable for future developers and agents.

The work is divided into three implementation phases:

- **Phase 1 — Correct parallel execution and immediate low-risk wins**
- **Phase 2 — Test-time / real-time separation and long-tail removal**
- **Phase 3 — Coverage, tox, and CI de-duplication**

Each phase is split into small steps intended to fit within approximately **20–30 minutes**.
Every step has an explicit input, action, validation, and stop point. A future agent should
complete one step, report its result, and stop unless the user explicitly authorises multiple
steps in one transaction.

---

## 2. Repository and test-suite background

Binnacle is a Python MCP server designed to let AI agents work on a Raspberry Pi. The test
suite is intentionally broad because it covers ordinary pure logic as well as Linux process,
filesystem, subprocess, networking-model, watchdog, packaging, MCP protocol, and durable job
lifecycle behaviour.

The managed tests are organised by responsibility:

| Path | Responsibility |
| --- | --- |
| `tests/unit/tools/` | individual MCP tools and small local helpers |
| `tests/unit/core/` | shared pure/core logic, properties, indexed/search logic |
| `tests/integration/` | multi-component workflows, jobs, logging, HTTP, packaging |
| `tests/contracts/` | MCP/client-visible schemas, validation and protocol contracts |
| `tests/system/` | Raspberry Pi/Linux behaviour modelled with fakes/guarded probes |
| `tests/scripts/` | repository maintenance/analysis scripts |
| `tests/live/` | opt-in read-only tests against the deployed Pi |

Important existing documents that an implementation agent should consult only when needed:

- `docs/testing.md` — test-level rules, normal commands, host-safety policy.
- `docs/quality-gates.md` — module-size, architecture, and per-module coverage gates.
- `docs/long-command-performance-and-distribution.md` — earlier performance/distribution
  investigation, including an older 2026-09-22 xdist benchmark.
- `quality-policy.json` — executable module classification and quality thresholds.
- `tox.ini` — supported Python matrix and current coverage commands.
- `pyproject.toml` — pytest, coverage, dependency and tool configuration.
- `.github/workflows/ci.yml` — GitHub Actions test matrix and coverage-policy job.

Do not assume dated test counts in older documents are still current. Always query the
current tree.

---

## 3. Non-negotiable safety and quality rules

### 3.1 Never weaken the host-safety fixture

`tests/conftest.py` contains a global autouse guard that blocks mutating host commands.
This exists because tests previously reactivated real Wi-Fi profiles on the development Pi.

Do not remove, bypass, or globally disable this guard to gain speed.

Tests must continue to avoid real mutation of:

- NetworkManager connections;
- routes and addresses;
- Wi-Fi radios;
- system services;
- kernel modules;
- firewall rules;
- host power state;
- physical USB/network hardware.

If a system test needs such behaviour, inject or monkeypatch the command boundary.

### 3.2 Coverage policy is semantic, not an average-only number

Current policy:

- designated core modules: at least **95% branch coverage from `tests/unit` alone**;
- other production modules: at least **90% branch coverage from the full appropriate suite**.

The repository-wide percentage is useful evidence but cannot replace the per-module policy.
Do not "optimise" coverage by changing the policy thresholds, adding exclusions, introducing
temporary floors, or moving tests between levels merely to make reports pass.

### 3.3 Do not delete meaningful tests to improve wall time

A test may be:

- fixed when it accidentally does unnecessary real work;
- moved to a serial lane when worker-process identity makes xdist invalid;
- converted from real waiting to an injected/test clock when wall time is not the behaviour
  being tested;
- kept as a small real-time contract test when real waiting *is* the behaviour.

A test must not simply be removed because it is slow.

### 3.4 Preserve production timing defaults

The production job background warm-up is currently:

```text
jobs.warmup_s = 1.0 second
```

Phase 2 may make most tests use a smaller test value, but it must **not** silently change the
production default.

Likewise, real production timeout/grace values must not be reduced merely to make tests fast.

### 3.5 Avoid nested unbounded parallelism

The Pi has four cores. Do not combine:

```text
tox -p auto
+
pytest -n auto in every tox environment
```

without measurement. Nested parallelism can oversubscribe CPU, subprocess scanning and the
filesystem and can make the suite slower or less deterministic.

### 3.6 Live tests stay opt-in

`tests/live/` must continue to skip unless `BINNACLE_LIVE=1` is intentionally supplied.
Do not include live deployment interaction in an ordinary speed benchmark.

---

## 4. Fixed working branch and worktree

The project owner has explicitly selected the following branch and commit as the working
baseline for this optimisation:

- **branch:** `design/chat-mode-scheduling-v2`
- **required starting commit:** `52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6`
  (`52ed0bd`)
- **existing worktree:** `~/Projects/binnacle-chat-scheduling-design`

This supersedes the earlier idea of creating a separate
`performance/test-suite-speedup` branch. Do **not** create that branch.

All implementation work for this plan must happen in the existing worktree:

```bash
cd ~/Projects/binnacle-chat-scheduling-design
```

Before Step 1.1, verify the exact branch, commit and cleanliness:

```bash
git status --short --branch
git branch --show-current
git rev-parse HEAD
git show -s --format='%H %h %s' HEAD
```

The expected starting state is:

```text
branch: design/chat-mode-scheduling-v2
HEAD:   52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6
short:  52ed0bd
```

The worktree was verified clean when this document was updated. If a future agent finds:

- a different branch;
- a different starting commit before any optimisation work has been performed; or
- pre-existing uncommitted changes it did not create,

it must stop and report the exact state rather than resetting, stashing, rebasing, merging,
or discarding anything.

Once this optimisation starts, later commits on
`design/chat-mode-scheduling-v2` are expected. Record the starting commit in Step 1.1 and
record each checkpoint commit after that; do not keep requiring HEAD to remain at
`52ed0bd`.

Do not modify the separate dirty `~/Projects/binnacle` master worktree as part of this
programme.

Each phase should end in a clean checkpoint commit after its own gates pass. Do **not**
automatically merge or rebase the branch after a phase; report the state and wait for the
owner to decide.

---

## 5. 2026-09-24 measured baseline and evidence

### 5.1 Measurement conditions

The exploratory benchmark used:

- Raspberry Pi 5;
- 4 CPU cores;
- Linux aarch64;
- Python 3.13.5 in the repository environment;
- pytest 9.1.1;
- pytest-xdist 3.8+ installed;
- deterministic `pytest-randomly` seed `12345`;
- current dirty worktree rooted at master HEAD
  `83862b040f59afc97963041de557bf9037f13e50`;
- approximately 97 `test_*.py` files;
- current full result: **1015 passed, 3 skipped** when run sequentially.

Because the worktree was dirty, these numbers are planning evidence, not the formal
post-implementation baseline. Phase 1 must establish a clean baseline before changing code.

#### 5.1.1 Applicability check against the selected working branch

After the owner selected `design/chat-mode-scheduling-v2 @ 52ed0bd`, the plan's key
technical assumptions were checked directly in that worktree.

At `52ed0bd`:

- `tests/system/test_watchdog_usb.py::test_usb_reset_schedule_escalates_across_attempts`
  exists and still patches `wd.usb_reset_device` rather than the lookup point in
  `binnacle.ops.watchdog.actions`;
- `tests/integration/test_search_text_streaming_equivalence.py` still compares the normal
  materialized and streaming payloads with strict whole-dict equality, while the same module
  separately documents that independent ripgrep invocations may traverse files in different
  order;
- `tests/integration/test_jobs_lifecycle.py` still contains the repeated background-job
  warm-up and real sleep/wait cases targeted by Phase 2;
- `tests/system/test_tunnel_readiness.py` still executes the rendered Bash readiness script
  and uses a two-second test bound to verify real Bash `SECONDS` behaviour;
- `src/binnacle/ops/watchdog/actions.py`,
  `src/binnacle/ops/watchdog/hardware.py`,
  `scripts/check_coverage_policy.py`,
  `tests/unit/core/test_config_loading.py`, and
  `.github/workflows/ci.yml` all exist;
- `tox.ini` still runs coverage in every normal Python environment and still re-runs unit
  tests inside the dedicated `coverage-policy` environment.

Therefore the three-phase design is applicable to the selected branch.

However, the historical timing and test-count numbers below came from a different dirty
master working tree. They must **not** be used as the pass/fail baseline for this branch.
Step 1.1 re-measures `52ed0bd` before implementation.

### 5.2 Current full-suite benchmark

| Mode | Wall time | Outcome |
| --- | ---: | --- |
| sequential, no coverage | **102.55 s** | 1015 passed, 3 skipped |
| xdist 2, worksteal | **55.57 s** | 2 xdist-specific failures |
| xdist 3, worksteal | **45.18 s** | same 2 xdist-specific failures |
| xdist 4, worksteal | **34.09 s** | same 2 xdist-specific failures |
| sequential + coverage | **124.27 s** | 1015 passed, 3 skipped; 96.49% total |
| xdist 4 main lane + temporary 3-test ordinary-process lane + coverage | **45.55 s** | all 1015 pass; coverage still 96.49% |

The current evidence therefore supports four local xdist workers on the Pi 5 for latency.
The final implementation must still re-measure on a clean branch.

### 5.3 Stable xdist-incompatible tests

Two failures reproduced with 2, 3 and 4 workers:

```text
tests/unit/core/test_units.py::
    test_proc_cmdline_reads_this_process

tests/system/test_doctor.py::
    test_process_environ_reads_own_process
```

They inspect the current process. xdist intentionally changes worker process identity:

- the command line can be rewritten to
  `[pytest-xdist running] tests/...`;
- the worker environment is not identical to a normal direct pytest process.

These tests are valid tests, but they must execute in a normal serial pytest process.

### 5.4 Search-text ordering issue exposed under parallel load

This test can intermittently compare identical search results in a different cross-file order:

```text
tests/integration/test_search_text_streaming_equivalence.py::
    test_normal_exact_results_match_between_pipelines[kwargs0]
```

Observed difference:

```text
materialized: b.txt, a.py:2, a.py:4
streaming:    a.py:2, a.py:4, b.txt
```

Counts and entries are identical; ordering differs.

The same test module already acknowledges elsewhere that separate ripgrep invocations may
traverse files in a different order. Therefore the implementation agent must resolve the
public ordering contract instead of simply hiding this test in a serial lane forever.

### 5.5 Accidental 12-second watchdog wait

The slowest measured test was approximately 12.02 seconds:

```text
tests/system/test_watchdog_usb.py::
    test_usb_reset_schedule_escalates_across_attempts
```

The test currently patches:

```python
mock.patch.object(wd, "usb_reset_device", ...)
```

but `wd.apply_action` ultimately calls the symbol imported into:

```text
binnacle.ops.watchdog.actions.usb_reset_device
```

Therefore the mock target is wrong. The real helper executes an `authorized` USB-reset
path whose default settle callback sleeps for 2 seconds. Across the test's reset sequence
this creates roughly 12 seconds of accidental wall time.

An isolated reproduction using the correct target
`wd_actions.usb_reset_device` preserved the full 12-attempt assertions and completed the
logic in approximately 0.23 seconds including interpreter startup.

This is both a performance defect and a test-isolation defect.

### 5.6 Job lifecycle timing cost

`tests/integration/test_jobs_lifecycle.py` was measured separately:

| Configuration | Wall time | Result |
| --- | ---: | --- |
| production warm-up 1.0 s | **39.20 s** | 37 passed |
| test process `BINNACLE_JOBS__WARMUP_S=0.05` | **16.98 s** | 37 passed |

That is a reduction of about **22.2 seconds / 57%** for that module without changing its
asserted behaviours.

The largest individual example:

```text
test_stop_reports_recorded_signal_not_unknown
```

repeats a background-job lifecycle ten times. With the 1-second production warm-up it costs
about 10.5 seconds by itself. The same logic passes with the shorter test warm-up.

### 5.7 Coverage duplication

Current `tox.ini` applies `--cov` to every normal Python test environment:

```text
py310
py311
py312
py313
py314
```

The dedicated `coverage-policy` environment then runs:

1. `tests/unit` with coverage;
2. the entire `tests` tree with coverage.

Measured on Python 3.13:

- full suite + coverage: **124.27 s**;
- unit-only + coverage: **19.16 s**.

So `coverage-policy` currently re-executes unit tests, and all compatibility tox
environments also pay coverage instrumentation.

### 5.8 Second-review execution locks

This section is normative. It was added after re-reading the plan as if the implementing
agent had no prior conversation, no memory, and no knowledge of Binnacle beyond this
document.

If a later step still offers alternatives such as "choose", "prefer", "possible design", or
"if needed", the decisions in this section take precedence unless the repository has
materially changed and the agent can point to the concrete changed file or contract that
invalidates the decision.

#### 5.8.1 Working branch is fixed

The working branch/worktree decision is no longer open.

Use:

```text
branch   design/chat-mode-scheduling-v2
start    52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6
worktree ~/Projects/binnacle-chat-scheduling-design
```

At the start of Step 1.1 run:

```bash
cd ~/Projects/binnacle-chat-scheduling-design
git status --short --branch
git branch --show-current
git rev-parse HEAD
```

Before the first optimisation change, require:

- branch is exactly `design/chat-mode-scheduling-v2`;
- HEAD is exactly `52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6`;
- worktree has no pre-existing uncommitted changes other than this plan document if it has
  not yet been committed.

Do not compare `master` and `proof-of-concept` to choose a base. Do not create
`performance/test-suite-speedup`. The owner has already made the base decision.

After optimisation commits begin, record the new checkpoint commit IDs and continue on this
same branch.

#### 5.8.2 The xdist marker is fixed

Use exactly **no_xdist**.

Register it in pyproject.toml under the pytest configuration with the description:

```text
no_xdist: test must run in a normal pytest process, not an xdist worker
```

Initially mark exactly these two tests:

```text
tests/unit/core/test_units.py::test_proc_cmdline_reads_this_process
tests/system/test_doctor.py::test_process_environ_reads_own_process
```

Do not mark the search-text equivalence test no_xdist. Its issue is an ordering comparison
problem, not a worker-process identity problem.

Do not use xdist_group as a substitute. An xdist group still runs inside an xdist worker,
which is exactly what invalidates these process-self-inspection tests.

#### 5.8.3 Search-text ordering decision is already made

Do not add a production global sort.

The repository already documents two relevant facts:

1. one returned search payload preserves the order produced by that invocation, especially
   when response-budget truncation keeps a prefix;
2. two independent ripgrep invocations may traverse files in a different order.

Therefore the untruncated materialized-versus-streaming differential test must compare:

- path exactly;
- pattern exactly;
- count exactly;
- truncated exactly;
- note exactly;
- complete entry dictionaries after canonical sorting.

A suitable comparison key is:

```python
def entry_key(entry):
    return (
        entry["file"],
        entry.get("line", -1),
        entry.get("text", ""),
        entry.get("count", -1),
    )
```

Sort copies only inside the differential test. Do not change the production result order,
and do not weaken truncation tests that depend on prefix semantics.

#### 5.8.4 The fast-suite runner shape is fixed

Create:

- **scripts/run_test_suite.py**
- **tests/scripts/test_run_test_suite.py**

The runner must start two separate pytest subprocesses through the current Python
interpreter. Do not call pytest.main twice inside one Python process.

Its CLI contract is:

```text
python scripts/run_test_suite.py [--workers N] [--seed N] [shared pytest args...]
```

It is a full-suite runner, not a focused node selector. Focused development runs still use
pytest directly.

Main lane:

```text
python -m pytest tests -q -m "not no_xdist"
```

When workers is greater than one, add:

```text
-n N --dist=worksteal
```

When workers equals one, omit xdist entirely.

Ordinary-process lane:

```text
python -m pytest tests -q -m no_xdist
```

Never add xdist arguments to the ordinary-process lane.

Resolve worker count in this exact order:

1. explicit --workers N;
2. BINNACLE_TEST_WORKERS;
3. min(4, os.cpu_count() or 1).

Reject values below one.

When --seed N is supplied, add --randomly-seed=N to both lanes. For all A/B measurements in
this plan, use seed 12345.

Shared pytest arguments required by tox/CI, especially the existing wheel-artifact ignore,
must be forwarded to both lanes.

Run both lanes even when the first lane has test failures, unless the process is interrupted.
Return non-zero if either lane fails. Print each lane command, exit code, elapsed time, total
time, and resolved worker count.

The runner tests must cover command construction, precedence of CLI/environment/default
worker count, worker=1 behaviour, marker expressions, seed forwarding, shared argument
forwarding, failure propagation, and the fact that the second lane still runs after a normal
first-lane test failure.

#### 5.8.5 Watchdog USB regression guard is mandatory

In the USB schedule test, patch the lookup point used by the action implementation:
**binnacle.ops.watchdog.actions.usb_reset_device**.

Retain the mock object and assert that the fake was called once for each of the 12 applied
USB reset actions. Do not rely only on wall-clock speed to prove the mock is effective.

Do not add a strict sub-second assertion to the committed test. Runtime belongs in benchmark
evidence, not in a correctness assertion.

#### 5.8.6 First Phase 2 timing change is deliberately narrow

Do not introduce a global timing override first.

In **tests/integration/test_jobs_lifecycle.py**, add a module-local autouse fixture that
changes the imported runtime constant:

```python
@pytest.fixture(autouse=True)
def _short_job_warmup(monkeypatch):
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)
```

In the existing default-settings test in **tests/unit/core/test_config_loading.py**, add:

```python
assert settings.jobs.warmup_s == 1.0
```

This separates fast test execution from the production default.

The environment-variable probe used during the investigation was only an A/B experiment.
Do not make BINNACLE_JOBS__WARMUP_S=0.05 a permanent shell, tox, CI, or global conftest
setting.

Only if a later profile proves that several additional integration modules materially pay
the same warm-up should the fixture move to tests/integration/conftest.py, and then it must
remain opt-in rather than suite-wide autouse.

#### 5.8.7 Tunnel readiness is intentionally real-time

The original Step 2.4 description was too generic and associated the slow test with the
wrong production seam.

**tests/system/test_tunnel_readiness.py** renders the tunnel systemd unit, extracts the real
ExecStartPost Bash script, executes it, and validates Bash SECONDS behaviour against a local
HTTP server.

The production template is in **src/binnacle/tunnel_unit.py**. It uses a ten-second bound and
a 0.2-second shell sleep. The tests substitute a shorter bound. The two timeout tests use a
two-second bound because Bash SECONDS advances in whole wall-clock seconds.

These tests are retained real-time integration coverage. Do not fake Python clocks, and do
not replace them with tests of watchdog.tunnel.restart_tunnel.

A one-second Bash bound is not an automatic optimisation: near a wall-clock second boundary
it can expire almost immediately and weaken the contract.

#### 5.8.8 Coverage orchestration sequence is fixed

Create:

- **scripts/run_coverage_policy.py**
- **tests/scripts/test_run_coverage_policy.py**

The coverage runner accepts workers, seed, unit-json path, full-json path, and shared pytest
arguments. It reuses the same worker resolution and no_xdist lane rules as the fast-suite
runner.

The sequence must be exactly:

1. coverage erase;
2. unit, not no_xdist, start new coverage data;
3. unit, no_xdist, append;
4. write unit-only JSON;
5. non-unit, not no_xdist, append;
6. non-unit, no_xdist, append;
7. write full JSON;
8. run the existing coverage-policy checker from tox.

Equivalent concrete commands, shown without the runner's worker options, are:

```text
python -m coverage erase

python -m pytest tests/unit -q -m "not no_xdist"   --cov=binnacle --cov-branch --cov-fail-under=0 --cov-report=

python -m pytest tests/unit -q -m no_xdist   --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=

python -m coverage json -o UNIT_JSON

python -m pytest tests -q --ignore=tests/unit -m "not no_xdist"   --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=

python -m pytest tests -q --ignore=tests/unit -m no_xdist   --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=

python -m coverage json -o FULL_JSON
```

The unit JSON must be written before any integration/system execution. Otherwise non-unit
tests could raise a core module's apparent unit-only coverage and silently weaken the 95%
policy.

In Step 3.2 first prove report equivalence with workers=1. In Step 3.3 enable xdist only on
the two "not no_xdist" calls.

Before replacing the old coverage-policy path, compare old and new JSON reports
module-by-module. Compare the production-file set and at least these summary fields:

- num_statements;
- covered_lines;
- missing_lines;
- num_branches;
- covered_branches;
- missing_branches;
- percent_covered.

"Aggregate coverage is close" is not acceptable.

#### 5.8.9 Normal tox environments do not own coverage

After Phase 3 Step 3.1, the base tox command is:

```ini
commands = python scripts/run_test_suite.py {posargs}
```

Do not include --cov in ordinary Python compatibility environments.

Keep the supported local matrix at Python 3.10, 3.11, 3.12, 3.13 and 3.14.

The existing GitHub layout already exercises 3.10, 3.11, 3.12 and 3.14 as compatibility
jobs and 3.13 in the dedicated coverage job. Do not add duplicate 3.13 CI work solely
because coverage was separated.

#### 5.8.10 Tox scheduling A/B commands are fixed

Warm environments before measuring:

```bash
uv run tox run --notest
```

Compare all three:

Strategy A — sequential tox, four pytest workers per environment:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=4 uv run tox run
```

Strategy B — two tox environments, two pytest workers each:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=2 uv run tox run-parallel -p 2
```

Strategy C — four tox environments, no xdist inside each:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=1 uv run tox run-parallel -p 4
```

Repeat the fastest strategy once. It must be green twice. If two strategies differ by less
than ten percent in wall time, select the simpler/lower-concurrency one.

Do not copy the selected local tox scheduling strategy into GitHub Actions. CI already
parallelizes by Python version.

#### 5.8.11 CI worker policy is host-aware, not Pi-specific

Do not hard-code -n 4 in GitHub Actions YAML.

Let the repository runner calculate min(4, os.cpu_count() or 1) on the GitHub runner unless a
later CI-specific A/B provides evidence for an explicit BINNACLE_TEST_WORKERS value.

Preserve the current wheel-artifact ignore, uv cache/dependency setup, ripgrep installation,
test token/config preparation, and pinned GitHub Actions.

Both repository runners must print the resolved worker count and lane commands so the CI log
shows what actually ran.

#### 5.8.12 Step-completion evidence rule

Every implementation step must leave enough evidence for the next memory-less agent. In
addition to the report format in Section 15, record:

- exact source commit at step start;
- exact files changed;
- exact focused test commands;
- exact full-lane command when one was run;
- pass/fail/skip counts;
- before/after wall time when performance was touched;
- whether production source behaviour changed;
- any deviation from Section 5.8 and the concrete reason.

Do not mark a step PASS if its performance number came from a different source snapshot,
different test selection, or different random seed than its comparison baseline.

---

## Phase 1 — Correct parallel execution and immediate low-risk wins

### Phase 1 objective

Create a correct, deterministic, maintainable fast full-suite path using xdist while fixing
the known accidental watchdog sleep and all currently observed parallel blockers.

Phase 1 must not alter production timing behaviour or coverage policy.

#### Phase 1 acceptance target

At the end of Phase 1:

- all current managed tests pass;
- the two process-self-inspection tests run serially;
- ordinary parallel-safe tests run with a measured worker count;
- search-text equivalence is deterministic according to its documented contract;
- the watchdog schedule test no longer performs real USB-reset settle sleeps;
- host-safety remains intact;
- a clean Pi 5 full run is materially faster than the clean sequential baseline;
- coverage remains unchanged within expected source changes;
- documentation contains the supported fast command.

Do not require a particular exact second count as a hard gate. The exploratory target is
roughly the 30–45 second range for a non-coverage full run before Phase 2, but correctness
comes first.

---

### Step 1.1 — Establish the branch-specific clean baseline

**Time box:** 20–30 minutes
**Type:** measurement only
**Code change:** none, except this plan document may already be present

#### Goal

Establish authoritative performance and correctness baselines on the owner-selected
`design/chat-mode-scheduling-v2` source snapshot before any optimisation implementation
changes are made.

The exploratory numbers in Section 5 were measured from a different dirty master worktree.
They are evidence for the optimisation direction, not the baseline for deciding whether this
branch improved.

#### Branch preflight

Enter the fixed worktree:

```bash
cd ~/Projects/binnacle-chat-scheduling-design
git status --short --branch
git branch --show-current
git rev-parse HEAD
git show -s --format='%H %h %s' HEAD
```

Before implementation begins, expected branch/commit are:

```text
design/chat-mode-scheduling-v2
52ed0bdd61fbae2a61f4028c0a9e04439bf6c1d6
```

The plan document itself may be the only new file if it has not yet been committed. Any
other pre-existing change must be reported before continuing.

Record the exact starting commit in the step report.

#### Environment preflight

Run:

```bash
nproc
python3 --version
uv run python --version
uv run pytest --version
uv run python -c 'import xdist; print(xdist.__version__)'
```

Record CPU count and tool versions. Do not silently compare this branch against measurements
from a different Python environment.

#### Sequential baseline

Run with the fixed benchmark seed:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  uv run pytest tests -q --randomly-seed=12345 --durations=30
```

Record:

- pass/fail/skip counts;
- wall time;
- user/system CPU;
- CPU percentage;
- max RSS;
- top 30 durations.

#### Coverage baseline

Run:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  uv run pytest tests -q --randomly-seed=12345 \
    --cov --cov-fail-under=86.9 --durations=20
```

Record:

- pass/fail/skip counts;
- wall time;
- repository total coverage;
- top 20 durations.

Also run the authoritative current policy before Phase 3 changes it:

```bash
uv run tox -e coverage-policy
```

Record whether the per-module policy is green.

#### Validation

The branch-specific sequential baseline and current coverage policy must be green before
optimisation begins.

If either is red:

1. reproduce the smallest failing test;
2. determine whether the failure is pre-existing on `52ed0bd`;
3. stop and report it;
4. do not begin performance changes on an unexplained red baseline.

Do not require this branch's test count or timing to equal the historical dirty-master
numbers in Section 5.

#### Stop point

Report:

- branch and starting commit;
- environment versions;
- sequential result and timing;
- coverage result and timing;
- current coverage-policy outcome;
- top slow tests.

Do not implement Step 1.2 in the same transaction unless the owner explicitly authorises
multiple steps.

---

### Step 1.2 — Fix the watchdog USB mock target

**Time box:** 20–30 minutes
**Type:** test correctness + immediate performance fix

#### Goal

Ensure `test_usb_reset_schedule_escalates_across_attempts` mocks the function at the actual
lookup point and performs no real 2-second settle sleeps.

#### Files

Primary:

- `tests/system/test_watchdog_usb.py`

Relevant implementation:

- `src/binnacle/ops/watchdog/actions.py`
- `src/binnacle/ops/watchdog/hardware.py`
- `tests/watchdog_support.py`

#### Actions

1. Confirm `apply_action()` dispatches to `_apply_usb_reset()`.
2. Confirm `_apply_usb_reset()` resolves `usb_reset_device` from
   `binnacle.ops.watchdog.actions`.
3. Change the test patch target from the compatibility facade symbol to the symbol used by
   `actions.py`.
4. Do not remove any schedule assertions.
5. Preserve:
   - 12 attempts;
   - exact backoff gap sequence;
   - final attempt counter;
   - method-rotation behaviour if currently asserted elsewhere.

#### Validation

Run:

```bash
/usr/bin/time -f "wall=%e" \
  uv run pytest -q \
  tests/system/test_watchdog_usb.py::test_usb_reset_schedule_escalates_across_attempts
```

Then:

```bash
uv run pytest tests/system/test_watchdog_usb.py -q
```

Expected outcome:

- all tests pass;
- the target test should be sub-second or near-sub-second, not ~12 seconds.

#### Regression guard

Retain the mock object and assert that the patched hardware helper was called exactly once
for each of the 12 applied reset actions. This is mandatory: it proves that the test is
actually using the mocked hardware boundary rather than silently re-entering the real
2-second settle path.

Do not add a strict wall-clock assertion to the committed test; duration is benchmark
evidence, not a correctness contract.

#### Stop point

Commit only this isolated test fix if the focused suite is green. Report old/new duration.

---

### Step 1.3 — Define and mark the true no-xdist tests

**Time box:** 20–30 minutes
**Type:** test-runner policy

#### Goal

Mark tests whose subject is the identity or environment of the current pytest process, so
they run in an ordinary pytest process instead of an xdist worker.

#### Known no-xdist tests

Exactly these two are known from the 2026-09-24 A/B:

```text
tests/unit/core/test_units.py::test_proc_cmdline_reads_this_process
tests/system/test_doctor.py::test_process_environ_reads_own_process
```

The search-text ordering test is not in this category and must remain eligible for xdist
after Step 1.4.

#### Marker definition

Use exactly `no_xdist`. Register it in `pyproject.toml` under
`[tool.pytest.ini_options]`:

```toml
markers = [
    "no_xdist: test must run in a normal pytest process, not an xdist worker",
]
```

Apply `@pytest.mark.no_xdist` to the two tests above.

Do not use `xdist_group` as a substitute. Grouping still executes the test inside an xdist
worker, which changes precisely the process identity or environment these tests inspect.

#### Actions

- Add the marker registration.
- Import or use `pytest` in the affected modules if not already imported.
- Mark the two tests.
- Confirm collection finds exactly two:

```bash
uv run pytest tests --collect-only -q -m no_xdist
```

- Run them in an ordinary pytest process:

```bash
uv run pytest tests -q -m no_xdist --randomly-seed=12345
```

- Run the complementary lane under xdist:

```bash
uv run pytest tests -q -n 4 --dist=worksteal -m "not no_xdist" \
  --randomly-seed=12345
```

At this point the already-known search-text ordering comparison may still fail. Do not mark
it `no_xdist`; Step 1.4 fixes the comparison.

#### Validation

- collection shows the two expected marked tests and no others;
- both marked tests pass without xdist;
- the previous process-command-line and process-environment failures disappear from the
  parallel-safe lane;
- no marker warning appears.

#### Stop point

Report marker count and both lane outcomes. Do not build the final runner until Step 1.4 is
green.

---

### Step 1.4 — Make search-text differential comparison order-correct

**Time box:** 20–30 minutes
**Type:** correctness and determinism

#### Goal

Make the differential test express the ordering contract already present in the repository:
one returned payload preserves the order produced by its own ripgrep scan, but two
independent ripgrep invocations are not required to traverse different files in the same
order.

The second review resolved the earlier design fork. Do not add a production global sort.

#### Evidence already established

- `docs/tools/search_text.md` says response-budget truncation keeps a complete prefix and
  preserves the entry order of that returned result.
- `tests/integration/test_search_text_streaming_equivalence.py` already states in its
  truncated-result test that separate ripgrep invocations may traverse files in a different
  order.
- no public tool description promises globally sorted cross-file results.

A production sort would therefore create a new contract, add work to every search, and could
change which entries survive prefix truncation.

#### Exact test change

Modify
`test_normal_exact_results_match_between_pipelines`:

- keep materialized and streaming invocations separate;
- compare `path`, `pattern`, `count`, `truncated` and `note` exactly;
- assert both payloads are untruncated in this test;
- compare complete entries after sorting copies with a total key suitable for ordinary and
   `names_only` entries:

```python
def entry_key(entry):
    return (
        entry["file"],
        entry.get("line", -1),
        entry.get("text", ""),
        entry.get("count", -1),
    )
```

- compare the entire sorted entry dictionaries, not only the sort keys;
- retain the existing truncation-test semantics;
- do not mark this test `no_xdist`;
- do not change production search code unless the revised test exposes a different,
   reproducible semantic mismatch beyond entry order.

#### Validation

Run:

```bash
for i in 1 2 3 4 5; do
  uv run pytest -q tests/integration/test_search_text_streaming_equivalence.py || exit 1
done

uv run pytest -q -n 4 --dist=worksteal \
  tests/integration/test_search_text_streaming_equivalence.py
```

Then rerun the whole parallel-safe lane:

```bash
uv run pytest tests -q -n 4 --dist=worksteal -m "not no_xdist" \
  --randomly-seed=12345
```

#### Stop point

Proceed only when both the equivalence module and the whole parallel-safe lane are green.

---

### Step 1.5 — Build the two-lane fast full-suite command

**Time box:** 20–30 minutes
**Type:** runner integration

#### Goal

Create one supported full-suite command that always executes the parallel-safe lane and the
`no_xdist` lane. Users and agents must not remember a hand-written pair of commands.

#### Files to create

- `scripts/run_test_suite.py`
- `tests/scripts/test_run_test_suite.py`

Do not add a new third-party dependency or orchestration framework.

#### CLI contract

```text
python scripts/run_test_suite.py [--workers N] [--seed N] [shared pytest args...]
```

This is a full managed-suite runner. Shared trailing pytest arguments exist for
collection-neutral modifiers needed by tox or CI, especially
`--ignore=tests/integration/test_wheel_artifact.py`. Focused file or node execution continues
to use pytest directly.

Use `argparse.parse_known_args()` or an equivalent explicit mechanism so runner options are
parsed while unknown pytest options are forwarded to both lanes.

#### Process model

Launch each lane through a separate subprocess using the current interpreter:

```text
sys.executable -m pytest ...
```

Do not invoke `pytest.main()` twice inside the runner process.

Common selection is:

```text
tests -q
```

Parallel-safe lane:

```text
python -m pytest tests -q -m "not no_xdist"
```

When resolved workers is greater than one, add:

```text
-n N --dist=worksteal
```

When workers equals one, omit both xdist options.

Ordinary-process lane:

```text
python -m pytest tests -q -m no_xdist
```

Never add xdist arguments to the ordinary-process lane.

When `--seed N` is supplied, add `--randomly-seed=N` to both lanes. Append shared pytest
arguments to both lanes.

Run the ordinary-process lane even if the main lane reports normal test failures, unless the
parent process is interrupted. Return non-zero if either lane is non-zero.

Print for each lane:

- lane name;
- resolved command;
- elapsed wall time;
- exit code.

At the end print total wall time and resolved worker count.

#### Worker resolution

Resolve worker count in this exact order:

1. explicit `--workers N`;
2. `BINNACLE_TEST_WORKERS=N`;
3. `min(4, os.cpu_count() or 1)`.

Reject zero, negative and non-integer values with a clear CLI error.

The Pi 5 benchmark command is:

```bash
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
```

#### Runner unit tests

Mock subprocess execution and cover at minimum:

- default worker count is in the range 1 through 4;
- CLI override wins over environment;
- environment wins over default;
- worker=1 omits `-n` and `--dist`;
- worker>1 adds `-n N --dist=worksteal` only to the main lane;
- main lane contains `-m "not no_xdist"`;
- ordinary lane contains `-m no_xdist` and no xdist arguments;
- seed reaches both lanes;
- shared `--ignore=...` reaches both lanes;
- second lane is attempted after a first-lane test failure;
- final exit is non-zero if either lane failed.

Then run the runner for real.

#### Validation

Compare with Step 1.1:

- same total pass and skip set;
- no process-self-inspection failures;
- no search-text ordering failure;
- no test selected by both marker expressions;
- full wall time materially below the sequential baseline.

#### Stop point

Record the exact command, resolved workers, per-lane counts and times, total time and final
exit status.

---

### Step 1.6 — Phase 1 full regression and documentation checkpoint

**Time box:** 20–30 minutes
**Type:** gate

#### Goal

Prove that Phase 1 is correct as a whole, record a stable clean benchmark, and leave the
repository in a checkpoint state that a new agent can use as the baseline for Phase 2.

#### Actions

1. Run the fast full suite at least twice with the same seed.
2. Run one different random seed.
3. Run the relevant watchdog and search-text focused suites.
4. Run:

   ```bash
   uv run pre-commit run --all-files
   ```

   if this fits the environment; if pre-commit is long, run the changed-file hooks first and
   then the repository-required full gate before the phase checkpoint.
5. Update:
   - `docs/testing.md` with the supported fast full-suite command;
   - this plan's execution-status section if used as a live record;
   - `docs/long-command-performance-and-distribution.md` only with a concise cross-reference
     or new clean measurement, not by deleting its historical 2026-09-22 data.

#### Phase 1 exit criteria

- zero unexpected test failures;
- serial lane includes all known process-self-inspection tests;
- parallel lane is stable;
- watchdog 12-second accidental sleep removed;
- search-text ordering contract resolved;
- fast full run is repeatably faster;
- no quality-policy change;
- no production timing change.

#### Stop point

Create a Phase 1 checkpoint commit. Do not merge automatically. Report:

- files changed;
- old/new wall time;
- pass/skip counts;
- any remaining long-tail tests;
- whether Phase 2 is safe to start.

---

## Phase 2 — Separate test timing from production timing

### Phase 2 objective

Remove unnecessary wall-clock waiting from integration/system tests while preserving a small,
explicit set of tests that genuinely verify real timing behaviour.

The governing rule is:

> Test state transitions with controlled time wherever possible; use real elapsed time only
> when elapsed time itself is the contract.

Phase 2 must not convert the suite into fake-only tests. Real process lifecycle, signals,
subprocesses and Linux boundaries should remain where they provide value.

#### Phase 2 target

The exploratory evidence suggests the full suite can realistically move into approximately
the **25–35 second** range on the Pi 5 after combining Phase 1 parallelism with timing
optimisation. This is a planning target, not a hard requirement.

---

### Step 2.1 — Build the real-wait inventory

**Time box:** 20–30 minutes
**Type:** measurement/inventory
**Code change:** preferably none

#### Goal

Create a complete list of tests whose runtime is dominated by deliberate waits.

#### Actions

Run:

```bash
uv run pytest tests -q --durations=50 --randomly-seed=12345
```

Also search tests for:

```text
time.sleep(
asyncio.sleep(
sleep N shell commands
wait_seconds=
STOP_SIGTERM_GRACE_S
WARMUP_S
poll loops
timeout loops
```

Classify each slow test into:

1. **real-time contract** — wall time itself is the behaviour;
2. **process lifecycle with configurable timing** — real process is useful but production
   duration is not;
3. **pure state/policy** — should not wait at all;
4. **external subprocess startup cost** — may be reducible by fixture/process reuse;
5. **unexplained** — profile before changing.

#### Validation

Before leaving this inventory step, confirm that every test in the current top-30 duration
output is either present in the inventory or explicitly classified as below the materiality
threshold. Confirm that every direct sleep/wait match found by the source search has either
an inventory row or a note explaining why it does not consume wall time, such as a long
sentinel process that is terminated immediately.

Do not claim the inventory is complete merely because the top ten tests were classified.

#### Deliverable

Add a table to this document or a small dedicated measurement note containing:

- test node id;
- baseline call duration;
- reason for wait;
- category;
- proposed treatment;
- whether a real-time replacement test must remain.

#### Stop point

Do not optimise more than trivial obvious mistakes in this inventory step.

---

### Step 2.2 — Scope a short job warm-up to lifecycle tests

**Time box:** 20–30 minutes
**Type:** test infrastructure

#### Goal

Remove repeated one-second background warm-up cost from the lifecycle integration module
without changing the production default or globally changing unrelated tests.

#### Current evidence

`tests/integration/test_jobs_lifecycle.py`:

```text
1.0 s warm-up -> 39.20 s
0.05 s test warm-up -> 16.98 s
37/37 tests pass in both cases
```

#### Exact implementation

In `tests/integration/test_jobs_lifecycle.py` add a module-local autouse fixture:

```python
@pytest.fixture(autouse=True)
def _short_job_warmup(monkeypatch):
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)
```

Do not permanently export `BINNACLE_JOBS__WARMUP_S=0.05` from the shell, tox, CI, or global
`tests/conftest.py`. That environment variable was only the A/B probe.

In the existing default-settings test in
`tests/unit/core/test_config_loading.py` add:

```python
assert settings.jobs.warmup_s == 1.0
```

This separately locks the production default.

No current lifecycle test exists to prove that background warm-up is exactly one real
second. The module covers state, signals, wait behaviour, process groups, stdin and durable
job recording. Do not add a production-timing marker merely to preserve the old delay.

If Step 2.5 later proves that several additional integration modules materially pay the same
warm-up, refactor the fixture into `tests/integration/conftest.py` as an **opt-in** fixture and
opt specific modules in explicitly. Do not make it suite-wide autouse without new
measurement.

#### Validation

Run:

```bash
uv run pytest -q tests/unit/core/test_config_loading.py
uv run pytest -q tests/integration/test_jobs_lifecycle.py --durations=20
uv run pytest -q tests/integration/test_logging.py
uv run pytest -q tests/integration/test_job_manager.py
```

Then run:

```bash
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
```

Acceptance:

- lifecycle module remains fully green;
- default-settings test proves `1.0`;
- production source or config files are unchanged by this step;
- lifecycle module is near the measured 17-second class before Step 2.3.

#### Stop point

Report old and new lifecycle duration and explicitly confirm the production-default
assertion.

---

### Step 2.3 — Shorten lifecycle process durations without removing real processes

**Time box:** 20–30 minutes
**Type:** focused integration optimisation

#### Goal

Reduce long shell sleeps used only to keep a process alive long enough for an assertion.

#### Known examples

In `tests/integration/test_jobs_lifecycle.py` there are tests using:

- `sleep 30`;
- `sleep 60`;
- `sleep 2`;
- `sleep 1`;
- a fixed `time.sleep(1.5)`;
- wait windows such as one second or more.

A long `sleep 30` used as a "must still be running" sentinel does not need to finish, so it
may remain if it is killed immediately and adds no wall time. Focus on sleeps that are
actually waited out.

#### Actions

For each waited-out sleep:

1. identify the specific contract;
2. reduce process duration relative to the test warm-up;
3. use event/poll-based readiness instead of fixed sleeps where possible;
4. retain generous assertion tolerances for loaded Pi/CI hosts;
5. avoid millisecond-scale races that create flakes.

Examples:

- a process expected to exit shortly after background return can use hundreds of
  milliseconds rather than multiple seconds;
- "let it finish" should poll for the final state instead of fixed
  `time.sleep(1.5)`;
- status-return-on-exit tests should use a short but real process and verify early return.

#### Validation

Run the lifecycle module repeatedly, including once under xdist as part of the main lane.

#### Stop point

Do not proceed if any lifecycle test becomes flaky over repeated runs.

---

### Step 2.4 — Preserve and classify the tunnel readiness real-time contract

**Time box:** 20–30 minutes
**Type:** system timing confidence gate; normally no code change

#### Why this step exists

The earlier draft associated these slow tests with the wrong production seam. The actual
**tests/system/test_tunnel_readiness.py** does not exercise the Python watchdog tunnel
restart loop. It renders the tunnel systemd unit, extracts the real
ExecStartPost Bash script, executes that script, and validates Bash SECONDS timeout
behaviour against a local HTTP health server.

The production template is **src/binnacle/tunnel_unit.py**. Its ExecStartPost script uses a
10-second bound and a 0.2-second shell sleep. The tests substitute shorter bounds. The two
timeout cases use a 2-second bound and intentionally consume roughly 1–2 seconds of real
wall time because Bash SECONDS advances in whole seconds.

#### Goal

Protect these tests as intentional real-time integration coverage. Do not optimise them into
fake-clock tests that would stop proving the rendered shell script actually works.

#### Actions

- Read the current **tests/system/test_tunnel_readiness.py** and
   **src/binnacle/tunnel_unit.py** far enough to confirm that this contract still exists.
- Run the full module with duration reporting:

```bash
uv run pytest -q tests/system/test_tunnel_readiness.py --durations=10
```

- Repeat the two timeout cases five times:

```bash
for i in 1 2 3 4 5; do
  uv run pytest -q     tests/system/test_tunnel_readiness.py::test_waits_out_the_bound_but_never_fails_when_the_probe_is_not_ok     tests/system/test_tunnel_readiness.py::test_waits_out_the_bound_when_the_url_file_is_stale     || exit 1
done
```

- Keep the 2-second test bound unless measured evidence proves that a smaller **integer**
   bound remains stable and still meaningfully verifies timeout waiting.
- Do not reduce the timeout cases to a 1-second bound merely for speed. Because Bash
   SECONDS is integer-valued, a one-second bound can expire almost immediately near a second
   boundary and weaken the test.
- Do not inject a Python fake clock into this module.
- Do not replace these tests with tests of the Python
   **binnacle.ops.watchdog.tunnel.restart_tunnel** function; that is a different contract.
- Add these two timeout tests to the retained-real-time inventory produced in Step 2.6.

#### Validation

The module must remain green and continue to prove all three behaviours:

- healthy readiness can finish before the bound;
- a bad probe waits out the bound but exits successfully;
- a stale URL file waits out the bound but exits successfully.

The two timeout tests are allowed to remain among the slower tests after Phase 2 because
their real elapsed time is part of the behaviour being validated.

#### Stop point

Normally this step ends with **no code change**. Report the measured cost and explicitly
classify these tests as "intentional real-time contract". Only alter them if the measured
behaviour contradicts the contract above.

---

### Step 2.5 — Review remaining top-20 long-tail tests

**Time box:** 20–30 minutes
**Type:** targeted optimisation

#### Goal

After Steps 2.2–2.4, rerun `--durations=30` and optimise only the next material bottlenecks.

Likely candidates from the 2026-09-24 baseline included:

- `test_status_wait_expires_leaves_job_running`;
- packaging/import smoke tests;
- `test_completed_child_is_not_timed_out_by_slow_consumer`;
- property tests;
- job telemetry escalation tests.

#### Decision rules

Optimise when:

- a wait is artificial;
- expensive setup is repeated unnecessarily;
- a fixture can safely be broader-scoped;
- a process duration is much longer than the behaviour requires.

Do not optimise when:

- the test is already sub-second and the change would add complexity;
- runtime comes from meaningful property-case volume;
- reducing the wait would materially narrow the race window being tested;
- the improvement is below measurement noise.

#### Validation

After the selected long-tail fixes, rerun the affected focused modules and then rerun:

```bash
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
```

Also rerun `--durations=30` and confirm the targeted tests actually moved down the duration
ranking. A code change that looks faster in isolation but does not improve the measured full
suite does not count as a successful performance fix.

#### Stop point

Stop this step after one coherent group of long-tail fixes. Do not turn it into an open-ended
micro-optimisation session.

---

### Step 2.6 — Establish real-timing coverage and anti-flake evidence

**Time box:** 20–30 minutes
**Type:** confidence gate

#### Goal

Prove that Phase 2 did not replace every timing test with mocks.

#### Actions

1. List tests intentionally using real elapsed time.
2. Explain what each one proves that a fake clock does not.
3. Re-run timing-sensitive modules multiple times.
4. Run the full fast suite with at least:
   - fixed seed 12345;
   - one different seed.
5. If practical, run a short loop of the most timing-sensitive tests 5–10 times.

#### Acceptance

- no new flakes;
- production timing defaults unchanged;
- at least one meaningful real wait test remains for each important wait contract that needs
  end-to-end timing validation;
- most ordinary state/lifecycle tests use controlled/test timing.

#### Stop point

Report the retained real-timing tests and the new full-suite wall time.

---

### Step 2.7 — Phase 2 regression checkpoint

**Time box:** 20–30 minutes
**Type:** phase gate

#### Goal

Prove that all Phase 2 timing changes preserve behaviour, coverage and host safety together,
and establish the post-Phase-2 benchmark that Phase 3 orchestration work must preserve.

#### Actions

Run:

```bash
# fast full suite
uv run python scripts/run_test_suite.py --workers 4 --seed 12345

# authoritative coverage policy, still using the current implementation
uv run tox -e coverage-policy

# repository hooks
uv run pre-commit run --all-files
```

Do not yet redesign coverage-policy in this phase.

#### Phase 2 exit criteria

- full suite green;
- coverage policy green;
- production timing defaults unchanged;
- no host mutation;
- repeated timing-sensitive tests stable;
- measured wall time improved from Phase 1 or, at minimum, long-tail CPU/wait evidence shows
  the expected gain;
- no arbitrary sleeps removed without replacement synchronisation where required.

#### Stop point

Create a Phase 2 checkpoint commit and report results. Do not merge automatically.

---

## Phase 3 — Coverage, tox, and CI de-duplication

### Phase 3 objective

Remove redundant test execution across coverage and Python compatibility validation while
preserving the exact semantic gates.

This phase changes orchestration more than test behaviour. Treat it as release-infrastructure
work and validate it carefully.

---

### Step 3.1 — Separate compatibility testing from coverage instrumentation

**Time box:** 20–30 minutes
**Type:** tox configuration

#### Current problem

The base `[testenv]` in `tox.ini` currently invokes pytest with `--cov` for every supported
Python environment. Python 3.10 through 3.14 therefore all pay coverage instrumentation even
though their distinct purpose is interpreter compatibility.

The repository already has a dedicated `coverage-policy` environment.

#### Goal

Make ordinary Python tox environments prove compatibility without coverage while preserving
the same supported five-interpreter matrix.

#### Exact change

Change the base tox command to:

```ini
commands = python scripts/run_test_suite.py {posargs}
```

Do not include `--cov` or `--cov-fail-under` in ordinary `[testenv]`.

Leave unchanged:

- `env_list = py310, py311, py312, py313, py314`;
- `runner = uv-venv-lock-runner`;
- `dependency_groups = test`;
- dependency locking;
- the existing `coverage-policy` environment until Steps 3.2 and 3.3 replace its internals.

The GitHub workflow currently has compatibility jobs for 3.10, 3.11, 3.12 and 3.14 plus a
dedicated 3.13 coverage job. Together those jobs still execute every supported interpreter.
Do not add a duplicate 3.13 compatibility job solely because coverage has been separated.

#### Validation

Run at least:

```bash
uv run tox -e py310
uv run tox -e py313
uv run tox -e py314
```

For each environment confirm:

- `scripts/run_test_suite.py` is the invoked test command;
- both main and `no_xdist` lanes run;
- no coverage summary is produced;
- no `--cov` argument appears in the pytest commands.

Inspect the resolved tox command if needed:

```bash
uv run tox config -e py313
```

#### Stop point

Record per-environment result and time. Do not introduce tox-level parallelism in this step.

---

### Step 3.2 — Make coverage-policy run each test only once

**Time box:** 20–30 minutes
**Type:** coverage orchestration

#### Goal

Produce the same unit-only and full-suite coverage semantics while executing every managed
test exactly once across the four coverage lanes.

#### Semantics that must be preserved

The policy checker requires two logically different reports:

1. a **unit-only** report for core-module 95% branch coverage;
2. a **full-suite** report for all other production-module 90% branch coverage.

The current method runs `tests/unit` once and then runs the whole `tests` tree, which executes
the unit tests a second time.

#### Files to create

- `scripts/run_coverage_policy.py`
- `tests/scripts/test_run_coverage_policy.py`

The script must accept:

```text
--workers N
--seed N
--unit-json PATH
--full-json PATH
[shared pytest args...]
```

Reuse the same worker resolution and `no_xdist` lane rules as
`scripts/run_test_suite.py`. Keep command-building helpers in one place rather than
maintaining two independent definitions of xdist safety.

For Step 3.2, invoke the new runner with `--workers 1`. Parallel coverage is introduced only
after sequential report equivalence is proved.

#### Exact coverage sequence

##### 1. Erase stale coverage data

```bash
python -m coverage erase
```

##### 2. Run unit xdist-safe tests and start coverage

```text
python -m pytest tests/unit -q -m "not no_xdist"
  --cov=binnacle --cov-branch --cov-fail-under=0 --cov-report=
```

##### 3. Run unit no-xdist tests and append

```text
python -m pytest tests/unit -q -m no_xdist
  --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=
```

##### 4. Write the unit-only JSON before non-unit tests

```bash
python -m coverage json -o UNIT_JSON
```

##### 5. Run non-unit xdist-safe tests and append

```text
python -m pytest tests -q --ignore=tests/unit -m "not no_xdist"
  --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=
```

##### 6. Run non-unit no-xdist tests and append

```text
python -m pytest tests -q --ignore=tests/unit -m no_xdist
  --cov=binnacle --cov-branch --cov-append --cov-fail-under=0 --cov-report=
```

##### 7. Write the combined full JSON

```bash
python -m coverage json -o FULL_JSON
```

##### 8. Run the existing policy checker from tox

```bash
python scripts/check_coverage_policy.py   --unit-json UNIT_JSON --full-json FULL_JSON
```

Shared pytest arguments such as
`--ignore=tests/integration/test_wheel_artifact.py` must reach all four pytest calls.

The unit process-command-line `no_xdist` test must be included before the unit JSON is
written. The system process-environment `no_xdist` test must be included before the full JSON
is written.

#### Why the report boundary is mandatory

If unit JSON is written after integration or system tests, those non-unit tests could raise a
core module's apparent unit-only percentage. That would silently weaken the 95% gate while
still producing a green aggregate report.

#### Coverage-runner unit tests

Mock subprocess execution and verify at minimum:

- coverage erase is the first command;
- unit `not no_xdist` precedes unit `no_xdist`;
- unit JSON is emitted before any non-unit test;
- both non-unit pytest calls contain `--ignore=tests/unit`;
- the first pytest call does not append coverage and all later pytest calls do;
- full JSON is emitted after all four pytest calls;
- shared pytest args reach all four pytest calls;
- a failing subprocess stops the coverage pipeline and returns non-zero.

#### Validation against the old policy

Before changing tox's authoritative coverage command:

1. generate an old-method unit/full JSON pair;
2. generate a new-method pair using `--workers 1` and the same source snapshot/seed;
3. compare the set of production files;
4. for every production file compare these JSON `summary` values:

   - `num_statements`;
   - `covered_lines`;
   - `missing_lines`;
   - `num_branches`;
   - `covered_branches`;
   - `missing_branches`;
   - `percent_covered`;

5. run `scripts/check_coverage_policy.py` against both pairs.

Any difference must be explained before proceeding. "Aggregate coverage is close" is not an
acceptable equivalence test.

#### Tox integration

Only after module-by-module equivalence is proved, change `[testenv:coverage-policy]` so it
calls `scripts/run_coverage_policy.py` to produce the two JSON files, then calls the existing
checker.

#### Stop point

Record the old two-pass coverage-policy time, the new de-duplicated workers=1 time, and exact
report-equivalence result.

---

### Step 3.3 — Enable xdist inside coverage-policy

**Time box:** 20–30 minutes
**Type:** coverage plus parallel-runner integration

#### Goal

Enable xdist only for the two `not no_xdist` coverage lanes while retaining ordinary pytest
processes for the two `no_xdist` lanes.

#### Historical proof

The exploratory dirty-worktree experiment achieved:

- 1015 passed and 3 skipped;
- 96.49% total coverage, identical to sequential;
- 45.55 seconds instead of 124.27 seconds.

That experiment temporarily put three tests outside xdist because the search-order
comparison had not yet been fixed. After Phase 1, only the two tests explicitly marked
`no_xdist` belong outside xdist.

#### Exact Pi 5 run

```bash
uv run python scripts/run_coverage_policy.py   --workers 4 --seed 12345   --unit-json /tmp/binnacle-unit-fast.json   --full-json /tmp/binnacle-full-fast.json

uv run python scripts/check_coverage_policy.py   --unit-json /tmp/binnacle-unit-fast.json   --full-json /tmp/binnacle-full-fast.json
```

When workers is greater than one, add `-n N --dist=worksteal` only to:

- unit `-m "not no_xdist"`;
- non-unit `-m "not no_xdist"`.

The two `-m no_xdist` invocations never receive xdist options.

#### Validation

Run the fast coverage pipeline twice. Each execution must begin by erasing stale coverage
data.

Require:

- both executions green;
- no stale or uncombined coverage worker data affects the reports;
- every `no_xdist` test is present in the appropriate report;
- unit/full JSON remain module-by-module equivalent to Step 3.2;
- policy checker passes;
- clean wall time is recorded for both executions.

#### Stop point

Compare the Step 3.2 de-duplicated workers=1 time with workers=4. Proceed only if the
parallel coverage path is correct and repeatable.

---

### Step 3.4 — Benchmark bounded tox-level scheduling strategies

**Time box:** 20–30 minutes
**Type:** A/B measurement

#### Goal

Find the fastest correct local Python-matrix execution while keeping nominal concurrency
near the Pi's four CPU cores.

Do not use `auto` simultaneously at tox and pytest layers.

#### Precondition

Warm the tox environments first so interpreter downloads and environment creation do not
pollute the scheduler comparison:

```bash
uv run tox run --notest
```

Use one unchanged source commit for A, B and C.

#### Strategy A — sequential tox, four pytest workers per environment

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=4 uv run tox run
```

#### Strategy B — two tox environments, two pytest workers each

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=2 uv run tox run-parallel -p 2
```

#### Strategy C — four tox environments, no xdist inside each

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M"   env BINNACLE_TEST_WORKERS=1 uv run tox run-parallel -p 4
```

With workers=1, the suite runner omits xdist, so Strategy C has tox-level concurrency only.

#### Measurements

For each strategy record:

- total wall time;
- user/system CPU;
- CPU percentage;
- max RSS;
- all tox environment outcomes;
- any process or timing flake.

Repeat the fastest strategy once.

#### Decision rule

Select the fastest strategy that is green twice. If the top two strategies differ by less
than 10% wall time, choose the simpler or lower-concurrency one.

Document the selected local matrix command in `docs/testing.md`.

Do not copy the selected local tox scheduling policy into GitHub Actions; CI already
parallelizes by Python-version job.

#### Validation

For every strategy, require all selected tox environments to pass. Verify that the same
interpreter set ran in A, B and C and that no strategy changed pytest selection. The winning
strategy must then pass its repeat run before it is documented as the local default.

#### Stop point

Record A/B/C plus repeat results and the selected local policy.

---

### Step 3.5 — Update GitHub Actions for the new lane and coverage design

**Time box:** 20–30 minutes
**Type:** CI infrastructure

#### Goal

Make CI consume the new repository runners without changing the supported interpreter
coverage, weakening the coverage job, or introducing a Pi-specific worker assumption.

#### Current CI shape

`.github/workflows/ci.yml` already has:

- a quality job;
- compatibility jobs for Python 3.10, 3.11, 3.12 and 3.14;
- a dedicated Python 3.13 coverage-policy job;
- the wheel-artifact test ignored in source-tree tox jobs.

This job topology is already suitable.

#### Actions

1. Keep the CI Python job matrix unchanged unless another repository change has made it
   stale.
2. Compatibility jobs continue to call their existing tox environments. Step 3.1 changes
   those environments to the no-coverage full-suite runner.
3. The Python 3.13 coverage job continues to call `tox -e coverage-policy`. Steps 3.2 and
   3.3 make that environment use the new coverage runner.
4. Do not hard-code `-n 4` in YAML. Let the repository runner resolve
   `min(4, os.cpu_count() or 1)` on the GitHub runner unless future CI-specific A/B evidence
   justifies an explicit `BINNACLE_TEST_WORKERS`.
5. Preserve
   `--ignore=tests/integration/test_wheel_artifact.py` and verify it is forwarded by tox into
   every relevant pytest lane.
6. Keep uv cache/dependency setup, ripgrep installation, token/config preparation and pinned
   action versions unchanged.
7. Both repository runners must print resolved worker count and lane commands so the CI log
   is auditable.

#### Validation before push

Inspect tox configuration:

```bash
uv run tox config -e py313
uv run tox config -e coverage-policy
```

Confirm ordinary compatibility test commands contain no coverage option.

#### Validation after push

Require all jobs green:

- quality;
- Python 3.10 compatibility;
- Python 3.11 compatibility;
- Python 3.12 compatibility;
- Python 3.14 compatibility;
- Python 3.13 coverage-policy.

Inspect logs to confirm:

- both full-suite lanes execute;
- coverage lanes execute in unit-before-non-unit order;
- resolved worker count is visible;
- no unexpected marker warning or deselection appears;
- wheel-artifact ignore is still present where it was before.

If CI exposes a parallel-only failure, reproduce the narrow test locally before changing
worker policy.

#### Stop point

Do not merge on a partially green matrix. Record job names or links and final status in the
Phase 3 checkpoint report.

---

### Step 3.6 — Update testing and quality-gate documentation

**Time box:** 20–30 minutes
**Type:** documentation

#### Goal

Make the repository documentation describe the commands and semantics that now actually run,
so a developer or future agent does not fall back to the old sequential/duplicate-coverage
workflow.

#### Files

At minimum review:

- `docs/testing.md`;
- `docs/quality-gates.md`;
- `docs/long-command-performance-and-distribution.md`;
- this plan.

#### Documentation must explain

1. the normal fast full-suite command;
2. the meaning of the no_xdist marker;
3. why some tests are excluded from xdist workers but not from the suite;
4. how production timing differs from test timing;
5. which tests preserve real timing;
6. the new no-duplicate coverage-policy flow;
7. compatibility tox versus coverage tox responsibilities;
8. local worker policy versus CI worker policy;
9. how to reproduce the benchmark.

Historical benchmark data should remain historical. Do not overwrite old measurements as if
they never existed.

#### Validation

Run the documentation/pre-commit hooks on every documentation file changed in this step.
Search the updated docs for the old direct tox pytest-plus-coverage command, old `serial`
marker wording, and any statement that compatibility tox environments still own coverage.
Any historical occurrence must be explicitly dated as historical rather than presented as
the current command.

#### Stop point

Run documentation-related pre-commit hooks.

---

### Step 3.7 — Final end-to-end release validation

**Time box:** 20–30 minutes for orchestration plus command runtime
**Type:** final gate

#### Goal

Demonstrate that the final branch is release-ready: all fast-path, coverage, Python-matrix,
repository-quality and CI gates pass from one coherent source snapshot, and the measured
speedup is reproducible against the clean baseline.

If commands take longer than the nominal step window, start them as the step's primary work;
do not split a logically atomic release gate merely to satisfy the time-box estimate.

#### Required commands

Run the supported equivalents of:

```bash
# fast current-Python full suite
uv run python scripts/run_test_suite.py --workers 4 --seed 12345

# authoritative per-module branch-coverage policy
uv run tox -e coverage-policy

# all supported Python versions
uv run tox

# repository hooks
uv run pre-commit run --all-files
```

Then verify GitHub Actions after push.

#### Benchmark comparison

Repeat the clean baseline command from Step 1.1 with the same seed and record:

- sequential reference time if still useful;
- final fast full-suite time;
- final coverage-policy time;
- final Python-matrix time;
- pass/skip counts;
- total coverage;
- per-module policy result.

#### Final acceptance criteria

All must be true:

1. no expected test removed;
2. no unexplained skip added;
3. host safety unchanged;
4. all supported Python versions pass;
5. per-module coverage policy passes;
6. GitHub Actions passes;
7. no_xdist tests run and are visible in the ordinary-process lane;
8. production warm-up remains 1.0 s unless an independent product decision changed it;
9. real timing coverage remains explicit;
10. fast local full-suite wall time is materially below the original clean baseline;
11. coverage-policy no longer re-runs the unit suite unnecessarily;
12. compatibility tox environments no longer pay coverage instrumentation;
13. documentation matches the commands actually used.

#### Stop point

Create the final Phase 3 checkpoint commit. Report results to the owner and wait for explicit
merge approval.

---

## 6. Recommended implementation architecture

The desired end state is conceptually:

```text
                    managed test suite
                           |
             +-------------+-------------+
             |                           |
      parallel-safe lane             serial lane
      pytest + xdist                ordinary pytest
      bounded workers              process-self tests
             |                           |
             +-------------+-------------+
                           |
                      same pass set
```

For coverage:

```text
unit parallel-safe
      +
unit no_xdist
      |
      +--> write unit-only JSON
      |
non-unit parallel-safe --cov-append
      +
non-unit no_xdist --cov-append
      |
      +--> write combined full JSON
      |
check_coverage_policy.py
```

For tox:

```text
py310 compatibility -- no coverage
py311 compatibility -- no coverage
py312 compatibility -- no coverage
py313 compatibility -- no coverage
py314 compatibility -- no coverage

coverage-policy (one chosen interpreter, currently CI Python 3.13)
    -> authoritative unit/full coverage policy
```

Do not duplicate coverage in compatibility jobs merely for reassurance; that adds cost
without adding a distinct gate.

---

## 7. Tests and behaviours that require special care

### 7.1 Process identity tests

Never "fix" the two self-process tests by loosening them until they accept xdist's rewritten
worker identity. Their purpose is to validate Binnacle's process inspection against an
ordinary process.

Correct treatment: the no_xdist ordinary-process lane.

### 7.2 Search-text result ordering

Do not add a production sort without proving order is a contract. Sorting every result can
have measurable cost and can change truncation semantics.

Likewise, do not simply convert all equality checks to sets if order is meaningful.

Resolve the contract first.

### 7.3 Job lifecycle races

The job subsystem intentionally tests:

- process exit;
- signal recording;
- background ownership;
- stop/kill escalation;
- process groups;
- descendants;
- stale/missing state;
- wait return behaviour.

Timing changes must preserve race coverage. Prefer:

- shorter but real processes;
- condition polling;
- explicit events;
- injected clocks where appropriate.

Do not turn lifecycle tests into shallow mocks of the functions they are intended to
integrate.

### 7.4 Watchdog hardware fakes

Tests must patch symbols at their **lookup point**, not merely at a compatibility facade that
exports the same object.

When a fake is expected, consider asserting the fake was called. This prevents another silent
return of real sleeps/hardware code.

### 7.5 Coverage data across xdist and multiple pytest invocations

Coverage files can be corrupted semantically by stale data or incorrect append order even
when pytest exits zero.

The coverage runner must explicitly control:

- data-file cleanup;
- xdist worker data combination;
- append order;
- time at which unit JSON is emitted;
- time at which full JSON is emitted.

Never trust only the final aggregate percentage.

---

## 8. Benchmark protocol

Every meaningful A/B comparison should use:

1. the same Git commit/source tree;
2. the same dependency lock;
3. the same Python version;
4. the same test selection;
5. the same random seed;
6. the same host;
7. no concurrent heavy development workload;
8. separate cold/warm-cache notes if cache effects are material.

Recommended command wrapper:

```bash
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" <command>
```

Primary metric:

- wall-clock duration.

Secondary metrics:

- user CPU;
- system CPU;
- CPU utilisation;
- max RSS;
- failure/flake count;
- top slow-test durations.

A faster run that changes the test set is invalid.

A faster run with intermittent failures is invalid.

A faster run that weakens host safety is invalid.

---

## 9. Failure-handling SOP for an AI agent

If a step fails:

1. do not immediately broaden the change;
2. identify whether failure is:
   - pre-existing;
   - deterministic regression;
   - xdist isolation issue;
   - timing flake;
   - stale coverage data;
   - host/environment problem;
3. reproduce the failure with the narrowest test command;
4. compare serial versus xdist where relevant;
5. compare production timing versus test timing where relevant;
6. fix the root cause;
7. rerun the focused test;
8. rerun the phase-level lane;
9. only then continue.

If a failure is unclear after the step's time box, stop and report evidence. Do not "solve" an
unknown failure by skipping the test.

---

## 10. Commit discipline

Prefer small commits aligned with coherent changes, for example:

```text
test: fix watchdog USB reset mock boundary
test: mark process-identity checks no-xdist
test: make search pipeline equivalence order-correct
test: add bounded parallel full-suite runner
test: add explicit fast job timing policy
test: reduce lifecycle real-wait durations
test: make coverage-policy single-pass by test selection
ci: remove duplicate coverage from Python matrix
docs: document fast test and coverage workflow
```

Do not mix unrelated watchdog feature development or MCP product behaviour into these
commits.

Each commit should have its focused tests recorded in the working notes or commit message
where useful.

---

## 11. Expected performance trajectory

The following numbers are directional, based on the 2026-09-24 exploratory dirty-worktree
measurement:

```text
sequential full suite, no coverage
    ~102.6 s

parallel xdist-4 main lane before timing work
    ~34 s plus small no_xdist lane

sequential full + coverage
    ~124.3 s

demonstrated two-lane full + coverage
    ~45.6 s

job lifecycle module
    39.2 s -> 17.0 s with 0.05 s test warm-up

watchdog USB schedule test
    ~12.0 s -> effectively sub-second with correct mock target
```

These results suggest a final local full-suite target around **25–35 seconds** is plausible,
but a clean rebaseline may shift the exact number.

The objective is not to hit a vanity number. The objective is to remove known structural
waste while keeping the same engineering confidence.

---

## 12. What is explicitly out of scope

This three-phase plan does **not** include:

- distributed multi-Pi test execution;
- pytest remote execution;
- mutation-test acceleration;
- reducing supported Python versions;
- lowering coverage targets;
- deleting integration/system coverage in favour of unit tests;
- changing production job timing for performance;
- replacing pytest;
- changing application performance unrelated to test execution.

Multi-host sharding remains a separate topic in
`docs/long-command-performance-and-distribution.md`. It should be reconsidered only after
the best correct single-host test path is established.

---

## 13. Phase dependency map

```text
Phase 1
  clean baseline
      |
  fix accidental wait
      |
  explicit no_xdist lane
      |
  resolve ordering determinism
      |
  supported parallel full runner
      v
Phase 2
  wait inventory
      |
  test timing policy
      |
  lifecycle/tunnel long-tail reduction
      |
  real-timing confidence gate
      v
Phase 3
  compatibility != coverage
      |
  single-pass coverage selection
      |
  xdist coverage
      |
  bounded tox scheduling
      |
  CI update
      |
  final release validation
```

Phase 2 depends on a stable Phase 1 runner because timing changes need repeatable full-suite
validation.

Phase 3 depends on Phase 1's lane model and should ideally follow Phase 2 so coverage and tox
are optimised around the final test execution behaviour rather than an intermediate one.

---

## 14. Step checklist for handoff

A new agent can use this as the compact progress ledger.

### Phase 1

- [x] 1.1 Clean reproducible baseline
- [x] 1.2 Fix watchdog USB mock target
- [x] 1.3 Define/mark true no_xdist tests
- [x] 1.4 Resolve search-text ordering contract
- [x] 1.5 Build two-lane fast full-suite command
- [x] 1.6 Full regression + Phase 1 checkpoint

### Phase 2

- [x] 2.1 Real-wait inventory
- [x] 2.2 Scope a short job warm-up to lifecycle tests
- [x] 2.3 Shorten lifecycle waited-out processes safely
- [x] 2.4 Preserve/classify tunnel readiness real-time contract
- [x] 2.5 Review remaining top-20 long-tail tests
- [x] 2.6 Real-timing coverage + anti-flake evidence
- [x] 2.7 Full regression + Phase 2 checkpoint

### Phase 3

- [x] 3.1 Remove coverage from ordinary compatibility tox environments
- [x] 3.2 Make coverage-policy run each test only once
- [x] 3.3 Enable xdist for coverage-policy while preserving no_xdist lanes
- [x] 3.4 Benchmark bounded tox-level scheduling
- [x] 3.5 Update GitHub Actions
- [x] 3.6 Update testing/quality/performance documentation
- [x] 3.7 Final end-to-end release validation

---

## 15. Required report format after each step

To make multi-chat handoff reliable, every future agent should finish a step with a compact
report containing:

```text
Step:
Status: PASS / BLOCKED / PARTIAL

Changed:
- files or "none"

Validation:
- exact commands
- pass/fail/skip counts

Performance:
- before
- after
- whether comparison is apples-to-apples

Findings:
- important technical facts discovered

Risks / follow-up:
- anything the next step must know

Next:
- exact next step number and title
```

Do not merely say "done". The report is part of the durable engineering record.

---

## 16. Definition of done for the entire programme

This programme is complete only when:

- the full managed suite has a supported, documented fast path;
- parallel-safe tests execute with bounded xdist parallelism;
- genuinely incompatible tests execute serially and are not skipped;
- search-text equivalence is deterministic according to its actual contract;
- accidental real sleeps such as the watchdog USB mock mistake are gone;
- test timing is separated from production timing where appropriate;
- meaningful real timing validation remains;
- the per-module 95%/90% branch coverage policy is unchanged and green;
- unit tests are not redundantly executed merely to build the full coverage report;
- normal Python compatibility environments do not all repeat coverage instrumentation;
- all supported Python versions pass;
- GitHub Actions passes;
- pre-commit passes;
- host-safety protections remain active;
- benchmark evidence shows a material and repeatable wall-time improvement;
- documentation describes the new workflow accurately;
- the owner has reviewed the checkpoint and explicitly approved merge.

Until all of those are true, treat the work as in progress.
