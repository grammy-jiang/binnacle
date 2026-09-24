# Long-command performance and multi-host execution

Status: design / measurement plan. The existing `run_command` auto-background policy
solves foreground waiting; this document addresses how to reduce the commands' actual
wall-clock runtime.

## 1. Separate the two latency problems

1. **Interaction latency** — the agent waits while a long command runs. This is already
   mitigated by deployment-local auto-background policy (`e653aba`).
2. **Execution latency** — pytest, tox, mypy, builds, or release validation actually take
   a long time. This document covers that problem.

The two must not be conflated: backgrounding a command improves responsiveness but does
not make the workload faster.

## 2. Design principle for multiple Raspberry Pis

Distribute **independent logical jobs or shards**, not one arbitrary shell process across
hosts. A worker should receive a reproducible job specification and run it locally.

Good first targets:

- tox environments (one or more environments per host);
- pytest shards balanced by historical test duration;
- independent stage/release checks;
- build/test matrices by Python version or platform;
- independent lint/type/security checks where inputs do not mutate shared state.

Poor first targets:

- a single stateful shell pipeline with tight inter-process communication;
- tests that share a mutable database, device, port, or filesystem without isolation;
- tiny commands whose transfer/setup overhead exceeds their runtime.

## 3. Proposed architecture

### Keep `run_command` local

Do not silently turn the existing `run_command` primitive into remote execution. Its
current contract is valuable: the named command executes against the named workdir on this
host. Transparent rerouting would make filesystem side effects, ports, local services,
and hardware access surprising.

Introduce multi-host execution first as an explicit logical-job/scheduler layer with
known task adapters (pytest, tox, release stages). Each child still uses the ordinary local
job machinery on its worker. Only after production evidence should any `execution=auto`
style interface be considered.

### Controller

The initiating Binnacle node owns one logical parent job. It decides whether to run
locally or fan out and records the aggregate result.

### Workers

Each Raspberry Pi runs its own Binnacle/worker endpoint and advertises capability and
current load (CPU count, available memory, architecture, Python versions, temperature /
throttle state where available). The scheduler does not assume identical Pis.

### Reproducible source snapshot

Every child job must see the same source state. Prefer, in order:

1. exact clean Git commit;
2. commit plus an explicit binary-capable patch for tracked changes and a bundle of
   untracked inputs when the worktree is dirty.

Do not share one live writable worktree over NFS. Workers use independent checkouts.

### Environment/cache key

Worker environments should be reusable and keyed by at least repository, lock/dependency
hash, Python version, architecture, and relevant tool configuration. Do not copy `.venv`
between hosts.

### Scheduler

Start with coarse-grained scheduling. A logical job becomes N child jobs, each with a
stable shard ID. Avoid nested over-parallelism: if four hosts each have four cores, do
not automatically start four xdist workers on every host without measurement.

Workers may be heterogeneous. Equal shard counts are therefore not necessarily balanced.
Maintain a measured speed factor per worker/workload class and assign estimated work by
capacity. A slower Pi should receive proportionally less predicted test duration, while
capability constraints (Python version, architecture, hardware/service requirements) are
hard placement rules rather than weights.

For the first prototype, use an already-authenticated host transport such as SSH rather
than exposing another unaudited network service. The transport is an implementation detail:
the scheduler contract should remain host/job/result oriented so it can later use a
dedicated Binnacle peer protocol if measurements justify one.

### Result aggregation

A parent result should preserve:

- child host + child job ID;
- exit state and duration;
- stdout/stderr/log path;
- JUnit/test result artifacts;
- coverage fragments where applicable;
- cancellation and partial-failure state.

Cancellation propagates from parent to all still-running children.

## 4. Pytest strategy

Use three levels, measured in order:

1. sequential local baseline;
2. local xdist (`-n 2`, then up to the local core count; compare distribution modes);
3. multi-host shards, with each host running a deterministic subset.

For cross-host sharding, historical-duration grouping is preferable to naive file-count
splitting. `pytest-split` is a useful reference/experiment because it stores test
durations and forms balanced groups, including a `least_duration` strategy.

Do **not** make pytest-xdist's rsync-based remote mode the Binnacle foundation. Current
xdist documentation deprecates rsync because it cannot reliably reproduce the remote
development environment. SSH/socket gateways still exist, but Binnacle should own source
and environment reproducibility. A pre-provisioned xdist-over-SSH experiment can remain
an optional comparison later.

## 5. Tox strategy

Tox's `run-parallel` parallelises environments on one host; `-p auto` uses the local CPU
count. For multiple hosts, Binnacle should assign selected tox environments to different
workers and aggregate them. This gives a clean coarse-grained distribution boundary and
avoids pretending tox itself is a cluster scheduler.

## 6. A/B programme

Use the same Git/source snapshot, dependency state, deterministic pytest seed, and test
selection in every comparable run. Record cold-cache and warm-cache runs separately.

### Local phase

- L0: sequential pytest.
- L1: pytest with 2 workers.
- L2: pytest with 4 workers on the Pi 5.
- L3: compare suitable xdist scheduling modes if L1/L2 are stable.
- L4: tox sequential vs local `run-parallel` with bounded parallelism.
- L5: mypy vs daemon/incremental approaches where applicable.

### Multi-host phase

- M1: two hosts, one balanced pytest shard each, one process per host.
- M2: three or more hosts, balanced duration-based shards.
- M3: hybrid: multiple hosts plus a small bounded local worker count per host.
- M4: distribute tox environments across hosts.
- M5: distribute independent release/stage checks.

Do not select a production policy solely from fastest one-off time. Repeat runs and use
variance.

## 7. Initial local A/B result (2026-09-22)

Binnacle's full pytest suite was measured on the Pi 5 at commit `e653aba`, with
`--randomly-seed=424242` held constant. Three adaptive-search test failures already
exist in the sequential baseline and are not counted as parallelism regressions.

| Mode | Wall time | CPU utilisation | user+sys CPU | Max RSS | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| sequential | 117.85 s | 35% | 42.42 s | 417,920 KiB | 3 baseline failures |
| xdist 2, worksteal | 74.05 s | 80% | 59.76 s | 403,168 KiB | baseline + 2 xdist-specific failures |
| xdist 4, worksteal | 65.65 s | 133% | 87.61 s | 400,464 KiB | same 2 xdist-specific failures |
| historical hybrid: xdist 4 + 2 ordinary-process tests | **64.27 s** | 135% | 86.97 s | 399,616 KiB | only the 3 baseline failures; ordinary-process lane 2/2 pass |

The hybrid reduces wall time by about **45.5%** (1.83x speedup) versus sequential.
Moving from two to four workers provides only about another 11% wall-time reduction while
roughly doubling aggregate CPU time relative to sequential. Four workers are therefore a
latency-oriented choice, not an efficiency win.

The two xdist-incompatible tests inspect their own process command line/environment. xdist
changes worker process identity, so those checks must run in an ordinary pytest process.
This is a strong argument for explicit parallel-safe and constrained lanes. It also suggests
that multi-host coarse shards, where each worker runs a normal pytest process, may avoid
some xdist-specific incompatibilities while still overlapping long waits.

The single-host comparison target for the multi-host POC is therefore approximately **64 s
with correct lane placement**, not the 118 s sequential baseline. A multi-host design must
beat the best correct single-host mode after including source/environment setup overhead.

### Phase 1 clean checkpoint (2026-09-24)

The 2026-09-22 measurements above remain historical. Phase 1 of the test-suite performance
plan established a supported two-lane runner and remeasured the Pi 5 on source snapshot
`94441a58aca911ba9069d3228adf33557b2deec1`, before documentation-only checkpoint
changes.

The fixed-seed `12345` checkpoint runs completed in **48.85 s** and **46.55 s** wall time;
a different seed (`54321`) completed in **44.16 s**. Each run selected the same 1,131
managed tests: 1,126 parallel-safe tests passed, 3 live tests skipped, and both `no_xdist`
tests passed in the ordinary-process lane. The formal same-source Phase 1 A/B from Step 1.5
was 113.04 s sequential versus 47.10 s with the two-lane runner. The older Step 1.1
124.73 s sequential baseline remains contextual rather than apples-to-apples because later
Phase 1 steps changed test code and added runner tests.

The supported command is documented in `docs/testing.md`.

### Phase 2/3 local checkpoint and scheduler result (2026-09-24)

These measurements are newer than the 2026-09-22 historical table above; they
do not rewrite it. After the Phase 2 timing work, the fixed-seed fast full suite
completed in **32.01 s** wall time at seed `12345`, with 1,128 passed and 3
skipped across the two required lanes.

The de-duplicated coverage runner then reduced the workers=1 direct coverage
pipeline from 102.03 s to two repeatable workers=4 runs at **54.09 s** and
**53.68 s**, with 1,132 passed and 3 skipped and module-by-module coverage
identical to the sequential single-pass reports. The authoritative
`tox -e coverage-policy` path also remained green.

Step 3.4 compared the bounded local Python-matrix strategies on one unchanged
source snapshot, after warming tox environments:

| Strategy | Command shape | Wall time | Result |
| --- | --- | ---: | --- |
| A | sequential tox, 4 pytest workers/environment | 165.70 s | all five environments green |
| B | 2 tox environments, 2 pytest workers/environment | 152.04 s | all five environments green |
| C | 4 tox environments, 1 pytest process/environment | 178.98 s | all five environments green |
| A repeat | sequential tox, 4 pytest workers/environment | 164.99 s | all five environments green |

Strategy B was the raw fastest, but its advantage over A was below the frozen
10 percent decision threshold. The selected local policy is therefore Strategy
A, which is simpler and repeated within 0.4 percent. This local choice is not a
GitHub Actions policy: CI already parallelizes by Python-version job and lets
the repository runner resolve `min(4, os.cpu_count() or 1)` on each host.

Reproduce the bounded matrix comparison with seed `12345`:

```bash
uv run tox run --notest

nproc
cat /proc/loadavg
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  env BINNACLE_TEST_WORKERS=4 uv run tox run -- --seed 12345

nproc
cat /proc/loadavg
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  env BINNACLE_TEST_WORKERS=2 uv run tox run-parallel -p 2 -- --seed 12345

nproc
cat /proc/loadavg
/usr/bin/time -f "wall=%e user=%U sys=%S cpu=%P maxrss_kb=%M" \
  env BINNACLE_TEST_WORKERS=1 uv run tox run-parallel -p 4 -- --seed 12345
```

Record `nproc` and `/proc/loadavg` immediately before each timed run. If the
one-minute load exceeds 1.5 because of unrelated work, wait up to five minutes
for that foreign load to clear or label the timing as contaminated. Do not
compare runs that use different source snapshots, test selections, dependency
locks, Python versions, or seeds.

## 8. Measurements

For every run capture:

- wall-clock duration (primary latency metric);
- total CPU seconds and average/peak CPU utilisation;
- max RSS / memory pressure;
- disk IO and network transfer/setup time;
- Pi temperature/throttle state when available;
- cache state (cold/warm);
- failures/flakes and result equivalence;
- worker imbalance (fastest vs slowest shard);
- orchestration overhead;
- total compute cost (speedup that doubles aggregate CPU may still be worthwhile, but it
  must be visible).

The comparison baseline is the fastest **correct and stable single-host** mode, not merely
the sequential mode.

## 9. Reliability constraints discovered in production

The original embedded owner could lose final exit metadata when its uvicorn worker
reloaded. The durable local-ownership work replaces that dependency with a stable sibling
`binnacle-jobs.service`; manager-owned jobs survive MCP reload/restart, while manager/host
interruptions are classified as `owner_restart` or `host_reboot`. Distributed execution
remains deferred until this local ownership layer has production evidence.

## 10. Implementation order

1. Finish local A/B measurement and establish the single-host optimum.
2. Define a host capability/job-result protocol without changing `run_command` semantics.
3. Prototype two-Pi coarse-grained pytest sharding with clean Git snapshots and warm
   environments.
4. Add duration-balanced sharding if simple partitions are imbalanced.
5. Generalise the controller only after measurements show a material benefit.

No multi-host scheduler should be merged merely because distribution is possible.
