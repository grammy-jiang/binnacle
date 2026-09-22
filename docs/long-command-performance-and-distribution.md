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
| hybrid: xdist 4 + 2 serial-only tests | **64.27 s** | 135% | 86.97 s | 399,616 KiB | only the 3 baseline failures; serial lane 2/2 pass |

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

Background jobs survive a development-worker reload as OS processes, but a job whose old
reaper disappears can later have `state=unknown` because final exit metadata was not
recorded. Increasing background/distributed execution makes durable exit ownership more
important. Fix that reliability gap before treating distributed child jobs as a production
quality gate.

## 10. Implementation order

1. Finish local A/B measurement and establish the single-host optimum.
2. Define a host capability/job-result protocol without changing `run_command` semantics.
3. Prototype two-Pi coarse-grained pytest sharding with clean Git snapshots and warm
   environments.
4. Add duration-balanced sharding if simple partitions are imbalanced.
5. Generalise the controller only after measurements show a material benefit.

No multi-host scheduler should be merged merely because distribution is possible.
