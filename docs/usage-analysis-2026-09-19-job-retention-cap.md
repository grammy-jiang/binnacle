# Job-store retention cap and concurrent start correctness — 2026-09-19

## Scope

This maintenance round addresses the mismatch between `jobs.keep_newest = 50` and
the observed on-disk store size of 51–52 jobs. The compact `job_status` listing is
a separate presentation policy and is not changed here. The retention requirement
is:

> Keep the newest `keep_newest` job directories as the **base window**. If a job
> older than that window is still running, protect it as a temporary exception so
> its process is never orphaned from `job_status`, `stop_job`, or its exit recorder.

## Root cause 1: prune-before-create gives a permanent +1

Before this change `start_job()` called `_prune()` first. `_prune()` kept the newest
50 existing directories and only then did `start_job()` create the new directory.
With no protected stale-running job, the steady state was therefore 51, not 50.
A live measurement during this review showed exactly **51 valid dirs = 50 exited +
1 running**.

The compact-listing review had independently observed 51-row listings and one
52-row listing; this analysis explains the base +1 rather than treating it as a
presentation problem.

## Root cause 2: concurrent starts can share the same freed slot

The MCP server dispatches synchronous tools through a worker pool, so multiple
`run_command` calls can enter `start_job()` concurrently. The retained journal has
**6,814 job starts** in the 14-day window. Start bursts reached:

- 3 starts in a rolling 100 ms window;
- 3 starts in a rolling 1 s window;
- 8 starts in a rolling 5 s window.

A concrete production interleaving occurred on 2026-09-17 at 11:23:08: two
`run_command` calls began at about `.970` and `.978`; the journal recorded only one
`jobs_pruned removed=1` at `.981`, then two `job_start` events at `.982` and `.983`.
Both starts therefore consumed the same single free slot, allowing the store to grow
from 51 to 52. This is a demonstrated race, not a theoretical one.

## Protected stale-running jobs are intentional exceptions

Across **6,812** retained prune events, 952 encountered at least one stale running
job outside the base window. The distribution of `skipped_running` was:

- 0: 5,860 events;
- 1: 685;
- 2: 257;
- 3: 10.

The largest observed exception count was three. These jobs must not be deleted: the
process would continue running while its durable status directory vanished, and a
later reaper would be unable to record the exit. This review therefore does **not**
redefine `keep_newest=50` as “50 finished jobs plus all running jobs.” Instead, 50
remains the total base recency window, with only stale-running jobs outside that
window protected.

## Design

`_prune(reserve=0)` now supports reserving slots for jobs a caller is about to add.
It computes:

```text
effective_keep = max(0, keep_newest - reserve)
```

Direct maintenance/test calls keep `reserve=0`. `start_job()` uses `reserve=1`, so
with `keep_newest=50` it first reduces the existing **base** window to 49, then the
new job occupies slot 50. Any stale-running directory encountered below that cutoff
is still spared as an exception.

A process-local `threading.RLock` serializes the entire reservation → job-directory
creation → `Popen` → complete `meta.json` write sequence. This is necessary because
the live server executes concurrent sync MCP calls in worker threads. Keeping the
lock until durable launch metadata is complete also prevents a second starter from
seeing and pruning a newly-created but not-yet-valid directory. The lock is reentrant
so direct `_prune()` callers and `start_job()` can share one implementation.

No cross-process file lock is added. The deployed uvicorn configuration uses one
server process, and the retained evidence demonstrates a thread-level race, not
multiple independently active writers. Adding filesystem locking without evidence
would increase failure modes and complexity.

`jobs.keep_newest` is also validated as **>= 1**. A zero-sized base window is not
operationally coherent because a newly launched job must retain at least its own durable
directory while it can still be addressed by `job_status`, `stop_job`, and the exit
recorder. The production configuration is the default 50, so this validation does not
change the deployed value.

## Observability

`jobs_pruned` retains `removed`, `skipped_running`, and `keep_newest` and now adds:

- `reserve`;
- `effective_keep`.

For normal launch pruning the journal should therefore show `reserve=1` and
`effective_keep=49` at the default cap. Direct `_prune()` reports `reserve=0` and
`effective_keep=50`. This makes intentional protected exceptions distinguishable
from cap overshoot.

## Validation exposed a second job-store atomicity race

While running the full multi-version suite, the pre-existing
`test_concurrent_stops_agree` intermittently failed: one of two simultaneous
`stop_job` callers sometimes received “No job with id” even though both target the
same newly-created running job. Ten isolated repetitions could pass, while a busy
full suite made the race much easier to hit.

The cause is independent of the retention count but belongs to the same durable
store concurrency boundary. `_write_meta()` previously used
`meta.json.write_text(json.dumps(meta))`, which truncates the live file before
writing the replacement. Reapers update that file when a process exits while
status/stop calls read it concurrently. `_read_meta()` deliberately returns `None`
on JSON decode failure, so a reader landing in the truncate/write window
misclassifies a real job as absent.

A dedicated pre-fix stress probe used four concurrent readers while writing 300
large metadata updates. Of 950 reader iterations, `_read_meta()` returned `None`
**764 times** and direct JSON parsing observed **798 invalid intermediate states**.
This makes the flaky concurrent-stop symptom reproducible at the storage primitive.

Metadata writes now use a unique same-directory temporary file followed by atomic
`os.replace()`. The same post-fix stress probe performed 1,038 reader iterations
with **0 missing/invalid reads**, **0 JSON failures**, and **0 leaked temp files**.
A deterministic test also observes that the old complete `meta.json` remains valid
right up to the replace boundary, then the new complete record is present.

This atomic-write correction is included in the retention concurrency round because
the new start serialization would otherwise leave a known job-store concurrency
hole and prevent a trustworthy full-suite concurrency gate. It does not change the
metadata schema or any MCP result.

## Validation

Targeted tests prove:

1. a full store plus one new job remains exactly at the base cap;
2. two barrier-synchronized concurrent starts do not share a reserved slot;
3. a stale running job below the base window remains present while the base window
   itself stays capped;
4. direct `_prune()` retains its reserve-zero behavior and malformed-record cleanup;
5. prune journal fields expose the configured and effective windows;
6. metadata replacement leaves the old complete record visible until atomic replace,
   then exposes the new complete record with no temp-file leak;
7. concurrent metadata readers never observe an invalid/missing record.

The relevant jobs + logging suites passed **83/83** before the atomic-write tests
were added. A separate retention stress probe preloaded a cap-10 store, then ran
**20 rounds × 8 barrier-synchronized concurrent starts**. Every round returned all
eight results without error and ended with exactly **10 directories**.

The final concurrency-focused gate (retention, atomic metadata, concurrent stop, and
prune logging) passed **6/6 on Python 3.10 through 3.14**. The final complete
project matrix, with an isolated job store for every interpreter, is:

- Python 3.10: **577 passed, 1 skipped**, coverage **88.39%**;
- Python 3.11: **577 passed, 1 skipped**, coverage **88.36%**;
- Python 3.12: **577 passed, 1 skipped**, coverage **88.39%**;
- Python 3.13: **578 passed**, coverage **88.36%**;
- Python 3.14: **578 passed**, coverage **88.31%**.

`jobs.py` is about 94% covered in the final matrix. The two earlier 3.13 full-suite
runs that reproduced `test_concurrent_stops_agree` occurred before the atomic
metadata fix. After that fix the same concurrency test passed on all five Python
versions and the entire final matrix completed without failure.

Production integration is recorded after deployment.

## Production integration

The final implementation was copied to the live `binnacle` tree on 2026-09-19
only after every existing target file matched the research snapshot baseline
byte-for-byte. A rollback copy was created at
`/tmp/binnacle-before-job-retention-cap-20260919T115351`. WatchFiles performed a
normal reload and the replacement worker reported a clean startup. The MCP tool
signatures/descriptions did not change, so no connector schema refresh was needed.

The first `run_command` launched by the new production code provided the base-cap
checkpoint. Before deployment the live store had 51 valid job directories. At the
first new launch the journal recorded:

```text
event=jobs_pruned removed=2 skipped_running=0 keep_newest=50 reserve=1 effective_keep=49
```

The command then observed exactly **50 directories / 50 valid states**. Thus the
old steady-state +1 corrected itself on the first ordinary launch; no manual store
cleanup was required.

A true concurrency checkpoint used three independent local FastMCP clients against
the same live HTTP MCP server. Their `run_command` calls entered within about 12 ms
of one another. The server then logged three serialized
`prune(reserve=1) -> job_start` sequences, each with `effective_keep=49`; the store
remained exactly **50 directories / 50 valid states** afterward. This exercises the
actual uvicorn worker-thread path rather than only an in-process unit test.

Atomic metadata replacement was verified through the live MCP path with five rounds
of one background `sleep 30` job followed by **two simultaneous `stop_job` calls**.
All ten stop calls returned `state=exited, signal=15`; none reported a missing job.
No `.meta.*.tmp` files remained in the live spool.

Finally, the focused production retention/concurrency tests passed **6/6** using an
isolated test job store. The real production store remained at **50 directories /
50 valid states** after those checks. This closes the production gate for the
retention and metadata-atomicity fixes.
