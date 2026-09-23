# Chat mode scheduling v2 — Phase 2 execution plan and SOP

Status: **PLANNED; NOT STARTED; NON-PRODUCTION ONLY**

Date: 2026-09-23 (Australia/Sydney)

Phase-1 evidence/code checkpoint: `cc1b014` (`Complete Phase 1 scheduling go-no-go`).

This document is the primary handoff and execution document for Phase 2. A new
ChatGPT transaction should be able to read this file and recover the background,
decisions, constraints, implementation sequence, test expectations, and working
SOP without relying on prior conversation history.

Related authoritative documents:

- `docs/chat-mode-scheduling-v2-design.md` — parent architecture and phase model;
- `docs/chat-mode-scheduling-v2-server-guard.md` — detailed blocking-wall guard
  specification;
- `docs/chat-mode-scheduling-v2-ab-plan.md` — benchmark variants and acceptance
  gates;
- `benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.md`
  — final Phase-1 aggregate decision;
- `benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.json`
  — machine-readable Phase-1 aggregate evidence.

If this document conflicts with the server-guard specification on guard semantics,
the server-guard specification wins. If it conflicts with the Phase-1 aggregate
report on measured results, the aggregate report wins. This document controls the
Phase-2 execution sequence and SOP.

## 1. Why Phase 2 exists

### 1.1 Original user goal

The user wants ChatGPT to be able to execute long development workflows in one
user prompt. A task may contain multiple long-running commands and multiple MCP
rounds. ChatGPT should continue working until the requested task or explicitly
agreed step is complete. It should not return control merely because a background
job was started, because a tool-call count crossed an arbitrary threshold, or
because one `job_status` call returned while the job was still running.

The desired interaction is:

```text
user starts a bounded development step
-> ChatGPT plans dependencies
-> long commands return durable job_id handles
-> ChatGPT performs independent work while jobs run
-> at a true dependency barrier ChatGPT waits as needed
-> ChatGPT continues after each wait automatically
-> task reaches its defined stop point
-> ChatGPT reports once at the end
```

A background Binnacle job is therefore a Future/Promise-like primitive. Starting
one is not a valid ChatGPT stop point.

### 1.2 What the preceding investigation established

The scheduling investigation established several important product facts:

- one ChatGPT user prompt can span many MCP rounds;
- known independent read-only calls can overlap and refill free in-flight slots;
- result-dependent continuation across an unresolved call is not guaranteed;
- non-read-only operations serialize in the observed connector path;
- `run_command(background=true) -> job_id` is the useful primitive for long work;
- MCP Tasks were not negotiated and are not part of this design;
- the historical latency problem came from repeated blocking `job_status` waits,
  not from one legitimate dependency wait;
- an old one-shot policy that allowed one short positive wait and then forced all
  later waits to zero can create premature user handoffs;
- tool-level durable jobs solve process lifetime, but cannot resurrect a ChatGPT
  turn that the platform itself has already terminated.

The resulting v2 architecture has two separate responsibilities:

1. **model scheduling guidance** — tell ChatGPT how to overlap independent work,
   treat job IDs as futures, and keep working in the same prompt;
2. **server catastrophe ceiling** — prevent one turn from accumulating a
   pathological amount of blocking wall time in repeated positive
   `job_status` waits.

Phase 1 tested responsibility 1. Phase 2 implements responsibility 2.

## 2. Phase-1 result that authorizes Phase 2

Phase 1 is complete: Steps 1.1 through 1.9 are finished.

The canonical macro aggregate used:

```text
R1 R2 R3 R5 R7 R8 R9 R11
24 A trials + 24 B trials
24 paired comparisons
```

Important aggregate observations:

```text
canonical median wall:
  A 49.816 s
  B 45.789 s
  B 8.1% lower

paired median B/A:
  0.917
  8.3% paired-median improvement

B faster:
  14 / 24 pairs

manual continuations:
  A 1
  B 0

premature handoffs:
  A 1
  B 0

same-prompt completion:
  A 87.5%
  B 75.0%

interruptions:
  A 8.3%
  B 25.0%

read-heavy completed median eligible overlap:
  A 40.0%
  B 55.6%

read-heavy median peak read-only in-flight:
  A 2
  B 3

R7 completed median physical tool calls:
  A 8
  B 6
```

The 100,000-resample paired bootstrap 95% interval for the aggregate median B/A
ratio was approximately `[0.756, 1.133]`, so Phase 1 did not prove confirmatory
non-regression.

The formal Phase-1 decision is deliberately two-level:

- **GO to Phase 2 as a design-branch, non-production experiment** because B
  demonstrated useful scheduling mechanism changes and a positive macro point
  estimate;
- **NO-GO for merge/deploy** because the full reliability, performance,
  concurrency-overlap, and statistical acceptance gates were not met.

Phase 2 must not weaken those gates or reinterpret the Phase-1 result as a
production approval.

## 3. Phase-2 objective

Implement a process-local, per-agent-turn **cumulative blocking-wall guard** for
positive `job_status` waits.

The guard answers only:

> How much real wall time has this client turn spent blocked inside positive
> `job_status` waits, and how much blocking time remains in its configured
> budget?

The guard is a safety ceiling, not a workflow scheduler.

It must:

- preserve the existing 50-second per-call `job_status` input bound;
- optionally enforce a total blocking-wall budget per `(client, base_turn)`;
- charge actual union wall time, not requested durations;
- count overlapping positive waits once;
- allow productive non-wait time between blocking windows for free;
- expose exhaustion to the model so it can produce a useful checkpoint instead
  of instant-polling indefinitely;
- remain disabled by default;
- never kill or corrupt durable jobs;
- use a monotonic clock;
- keep process-local memory bounded;
- fail open to the ordinary per-call behavior when turn correlation or tracking
  capacity is unavailable;
- produce telemetry sufficient for Phase 3 replay and later production review.

## 4. Explicit non-goals

Phase 2 must **not**:

- deploy anything to the production Binnacle service;
- modify the production config to enable a budget;
- choose 300 seconds as the production budget;
- implement a DAG scheduler or workflow engine;
- decide whether independent work remains;
- modify ChatGPT's platform timeout behavior;
- attempt to repair pre-MCP browser/submission failures;
- persist ephemeral turn-budget state across server reloads;
- replace durable job ownership;
- change `run_command` job lifetime semantics;
- kill a job when the blocking budget is exhausted;
- silently exclude submitted timeout trials from later A/B evidence;
- loosen the Phase-4 production acceptance gates.

Budget selection is a later experiment. Phase 3 will replay at least
`120 / 300 / 600` second candidates before live C-arm confirmation.

## 5. Safety and compatibility invariants

These are hard constraints throughout all Phase-2 steps.

### 5.1 Default execution semantics are unchanged

Repository defaults must contain no active client budget. With an empty budget
map, existing clients retain the current blocking/job-lifecycle semantics: the
server does not impose a per-turn ceiling and the ordinary per-call 0..50-second
contract remains.

Phase 2 intentionally adds **backward-compatible observability** in Step 2.8:
a specific-job call with an original positive wait gains optional/additive
structured policy fields, even under `no_policy`. Zero-wait and listing payloads
retain their previous shape. Therefore "unchanged" in this document means
execution semantics, not byte-for-byte result JSON after Step 2.8.

### 5.2 Existing per-call contract remains

`job_status.wait_seconds` remains bounded to `0..50` seconds at the MCP schema.
The turn budget can reduce an effective positive wait but cannot increase it.

### 5.3 Durable jobs are independent

Budget exhaustion limits how long the **tool call blocks**. It does not stop the
background process. The job must remain visible to later `job_status` and
`stop_job` calls.

### 5.4 Unknown turn means no hidden guess

If a reliable base turn cannot be extracted, use ordinary per-call behavior and
log `blocking_policy=no_turn`. Do not invent state keyed by session guesses.

### 5.5 Capacity exhaustion fails open

An active turn record must never be evicted. If the tracker is full of active
records, a new turn uses ordinary per-call behavior and records
`blocking_policy=capacity_untracked`.

### 5.6 Locks protect accounting only

No tracker lock may be held while waiting for a job. Acquire/update/release
bookkeeping must be short critical sections.

### 5.7 Evidence remains honest

Setup failures before submission may be retried under the established benchmark
rule. A submitted failure remains canonical. Diagnostic classification must
never be used to replace an inconvenient submitted result.

## 6. Existing code architecture relevant to Phase 2

The current implementation already provides most integration points.

### 6.1 Per-call context

`src/binnacle/callctx.py` currently exposes:

```text
current_call
current_client
current_argument_names
current_call_started
```

Phase 2 will add a `current_turn` ContextVar here.

### 6.2 Request/tool middleware

`src/binnacle/logging_middleware.py` already:

- resolves the MCP client identity;
- observes `X-Request-Id`;
- logs it as `turn=` on tool records;
- sets per-call ContextVars around `call_next()`;
- resets them in `finally` paths.

The observed OpenAI tunnel request-id shape is:

```text
<base-turn>/<call>
```

Phase 2 should publish the reliable base-turn portion through `current_turn`.

### 6.3 `job_status`

`src/binnacle/tools/job_status.py` currently performs:

```text
schema wait_seconds 0..50
-> clamp to WAIT_MAX
-> jobs.await_exit(job_id, wait_seconds)
-> build structured payload
-> build one-line summary
-> emit job_status_timing
```

The Phase-2 policy belongs around the effective wait decision and lease
lifetime. The durable job implementation itself should not learn about ChatGPT
turn budgets.

### 6.4 Configuration

`src/binnacle/config.py::JobsSettings` is the natural location for a mapping such
as:

```toml
[jobs.blocking_wall_budget_s_by_client]
"openai-mcp" = 300
```

The repository default remains empty.

### 6.5 Statistics

The current stats path is already modular:

```text
logstats_models.py
logstats_jobs.py
logstats_render.py
logstats.py
```

Phase 2 should extend this path rather than create a parallel stats command.

## 7. Target guard semantics

### 7.1 State key

State is keyed by:

```text
(client, base_turn)
```

not by job ID and not by MCP session.

### 7.2 Turn state

Initial model:

```text
spent_s
active_count
active_window_started
active_window_deadline
last_seen
```

Private helper fields are allowed, but the public Phase-2 state/API contract is
frozen in Section 9.1.6 and the accounting formulas are frozen in Section
9.1.8. Do not redesign them during implementation.

### 7.3 First positive wait in a new window

The exact first-window rule is:

```text
remaining = budget - spent
active_window_started = now
active_window_deadline = now + remaining
effective_wait = min(requested_wait, 50, floor(remaining))
```

Only an effective positive wait acquires a lease.

### 7.4 Overlapping positive waits

A later wait that overlaps the same active window uses the same deadline:

```text
remaining = active_window_deadline - now
effective_wait = min(requested_wait, 50, floor(remaining))
```

Five overlapping 20-second waits should cost about 20 seconds, not 100.

### 7.5 Closing a window

Each positive wait releases its lease in `finally`.

When `active_count` reaches zero:

```text
spent += min(now, active_window_deadline) - active_window_started
```

Then the active window closes.

A job that exits after 3 seconds therefore charges about 3 seconds even when
50 seconds was requested.

### 7.6 Exhaustion

If less than one second is available, the effective positive wait becomes zero.
The call still reads and returns job state normally. If the job remains running,
structured output and the human/model summary must explicitly state that the
turn's blocking budget is exhausted and later positive waits will be
non-blocking.

## 8. Policy outcomes

The implementation exposes the following exact policy outcomes; their names are
frozen by Section 9.1.7:

```text
no_policy
no_turn
tracked
exhausted
capacity_untracked
```

Expected behavior:

| Policy | Per-turn tracking | Effective behavior |
| --- | --- | --- |
| `no_policy` | no | ordinary per-call 50 s bound |
| `no_turn` | no | ordinary per-call 50 s bound |
| `tracked` | yes | min(per-call bound, remaining budget) |
| `exhausted` | yes | positive wait reduced to zero |
| `capacity_untracked` | no | ordinary per-call 50 s bound |

## 9. Required telemetry contract

Every `job_status` decision must be reconstructible from logs.

The per-call log contract is exactly the field set below, with null/absent-value
encoding defined in Section 9.1.11:

```text
wait_requested_s
wait_bounded_s
wait_effective_s
waited_s
blocking_budget_s
blocking_spent_before_s
blocking_remaining_before_s
blocking_active_before
blocking_policy
blocking_budget_exhausted
turn
client
```

Positive-wait structured output uses exactly these additional policy keys:

```text
wait_requested_s
wait_effective_s
blocking_budget_s
blocking_remaining_s
blocking_budget_exhausted
blocking_policy
```

When the final lease closes an active window, emit a dedicated event with at
least:

```text
turn
client
blocking_window_wall_s
blocking_spent_after_s
blocking_remaining_after_s
```

Later `binnacle stats` must aggregate enough information to answer:

- how many positive/non-blocking `job_status` calls occurred;
- requested versus effective waits;
- actual blocking-wall union per tracked turn;
- how often budget exhaustion occurred;
- how many turns crossed 25%, 50%, 75%, and 100% budget utilization;
- p50/p90/p95/max blocking wall per turn.

## 9.1 Frozen implementation decisions for a cold-start agent

This section removes choices that a new agent would otherwise have to
re-investigate. These decisions are **already made for Phase 2**. Do not reopen
them unless implementation evidence proves one impossible or internally
inconsistent. If that happens, record the contradiction in the Phase-2 progress
files before changing the contract.

### 9.1.1 Canonical repositories, branch, and worktree

Use these exact locations and names:

```text
production checkout:
  /home/grammy-jiang/Projects/binnacle
  expected branch: master

Phase-1/design checkout:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-design
  branch: design/chat-mode-scheduling-v2

Phase-2 implementation branch:
  feature/chat-mode-blocking-wall-guard

Phase-2 implementation worktree:
  /home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard
```

The Phase-1 evidence decision is commit `cc1b014`. The implementation branch
must **not** be created directly from `cc1b014`, because the design branch has
newer planning documentation. Create Phase 2 from the current synchronized tip
of `origin/design/chat-mode-scheduling-v2` that contains this document.

Do not branch Phase 2 from `master` or `proof-of-concept`.

### 9.1.2 Canonical Phase-2 progress files

Step 2.1 must create both files below, and every later numbered step must update
them before that step is committed:

```text
benchmarks/chat-mode-scheduling-v2/phase2-progress.json
benchmarks/chat-mode-scheduling-v2/phase2-progress.md
```

`phase2-progress.json` is the machine-readable source of truth for step status.
Use exact JSON step states `not_started`, `complete`, or `blocked`; use phase
status `in_progress`, `blocked`, or `complete`. The Markdown mirror renders those
as `NOT STARTED`, `COMPLETE`, or `BLOCKED`. Use schema version 1 with at least:

```json
{
  "schema_version": 1,
  "phase": 2,
  "status": "in_progress",
  "branch": "feature/chat-mode-blocking-wall-guard",
  "worktree": "/home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard",
  "source_branch": "design/chat-mode-scheduling-v2",
  "phase1_evidence_commit": "cc1b014",
  "last_completed_step": "2.1",
  "next_step": "2.2",
  "steps": {
    "2.1": {
      "status": "complete",
      "tests": [],
      "notes": []
    }
  }
}
```

Do **not** attempt to store the hash of the commit that contains the progress
file inside that same commit; that would be self-referential. Git history is the
authoritative step-commit mapping. The progress files record step number,
status, tests, findings, and next step.

`phase2-progress.md` is the concise human-readable mirror. It must begin with a
small status table containing all twelve steps and `NOT STARTED / COMPLETE /
BLOCKED` state.

### 9.1.3 Exact new source and test files

Use these exact new files rather than choosing alternate locations:

```text
src/binnacle/blocking_wall_guard.py

tests/unit/core/test_blocking_wall_guard.py
tests/integration/test_job_status_blocking_guard.py
tests/integration/test_job_status_blocking_guard_concurrency.py

scripts/benchmark_blocking_wall_guard.py
```

Existing files to extend are fixed as:

```text
src/binnacle/callctx.py
src/binnacle/config.py
src/binnacle/logging_middleware.py
src/binnacle/tools/job_status.py
src/binnacle/server.py
src/binnacle/logstats_models.py
src/binnacle/logstats_jobs.py
src/binnacle/logstats_render.py

tests/unit/core/test_config_loading.py
tests/unit/core/test_logging_result_fields.py
tests/unit/core/test_logstats_jobs.py
tests/unit/core/test_logstats.py
tests/integration/test_logging.py
tests/integration/test_http_workflows.py
tests/integration/test_jobs_lifecycle.py
tests/integration/test_job_manager_telemetry.py
tests/contracts/test_descriptions.py

docs/tools/run_command.md
docs/logging.md
```

Do not move durable-job code into the new guard module. Do not create another
stats subsystem. `docs/tools/run_command.md` owns the public run/job-status
contract text; `docs/logging.md` owns the production event inventory.

### 9.1.4 Exact configuration API

Add this setting to `JobsSettings`:

```python
blocking_wall_budget_s_by_client: dict[str, int]
```

The default is an empty mapping via `default_factory=dict`.

Validation rules are fixed:

- client-prefix keys must be non-empty and not whitespace-only;
- each budget must be an integer in `1..3600` inclusive;
- configuration outside that range fails settings validation.

Add this method to `JobsSettings`:

```python
def blocking_wall_budget_for_client(self, client: str | None) -> int | None: ...
```

Resolution is exact prefix matching against the configured keys. If several
prefixes match, the longest matching prefix wins. `None` or an unmatched client
returns `None`.

Step 2.2 must also add effective-config observability to the existing `jobs`
`tool_config` line:

```text
blocking_wall_budget_clients=<count>
blocking_wall_budgets=<prefix:seconds,... or ->
```

Sort prefixes for deterministic output. These values are configuration, not
secrets.

For environment-loading coverage, use the existing Pydantic-settings convention
and test the JSON mapping form:

```text
BINNACLE_JOBS__BLOCKING_WALL_BUDGET_S_BY_CLIENT={"openai-mcp":120}
```

### 9.1.5 Exact turn-correlation rule

Add to `src/binnacle/callctx.py`:

```python
current_turn: ContextVar[str | None]
```

Add a pure helper in `logging_middleware.py`:

```python
def _base_turn(request_id: str | None) -> str | None: ...
```

The parsing rule is fixed:

1. input is the full `X-Request-Id` value already logged as `turn=`;
2. split once on the first `/`;
3. return the prefix only when prefix, slash, and suffix are all non-empty;
4. otherwise return `None`;
5. do not synthesize a base turn from session ID, MCP request ID, or any other
   field.

`ToolLoggingMiddleware.on_call_tool()` must continue logging the full request-id
value as `turn=` while publishing only the base portion in `current_turn`.
Set/reset `current_turn` in the same `try/finally` scope as `current_client` and
`current_call`.

### 9.1.6 Exact tracker public API and data model

`src/binnacle/blocking_wall_guard.py` owns the policy state. Use these public
names:

```text
BlockingWallTracker
BlockingDecision
BlockingRelease
BlockingLease
TurnState
```

Use a `threading.Lock`, because synchronous MCP tools may execute concurrently
in worker threads. Do not use an asyncio-only lock.

`BlockingWallTracker` constructor:

```python
def __init__(
    self,
    *,
    clock: Callable[[], float] = time.monotonic,
    capacity: int = 4096,
) -> None: ...
```

The capacity is **4096 total tracked turn records**, not 4096 inactive records
plus active records. On insertion while full, evict the least-recently-used
inactive record. If all records are active, return the untracked capacity
fallback; never evict an active record.

The tracker key is exactly:

```text
(client, base_turn)
```

`TurnState` contains at least:

```text
budget_s
spent_s
active_count
active_window_started
active_window_deadline
last_seen
```

The configured budget is fixed for a tracked record's process lifetime. A
process reload creates a new tracker and therefore a new record from current
configuration.

Expose one acquisition method with this semantic signature:

```python
def acquire(
    self,
    *,
    client: str | None,
    turn: str | None,
    requested_wait_s: int,
    bounded_wait_s: int,
    budget_s: int | None,
) -> BlockingLease: ...
```

`BlockingLease` always exists, including untracked/no-op outcomes. It exposes a
`decision: BlockingDecision` and an idempotent:

```python
def release(self) -> BlockingRelease: ...
```

Calling `release()` twice must not double-charge time.

`BlockingDecision` contains at least:

```text
policy
requested_wait_s
bounded_wait_s
effective_wait_s
budget_s
spent_before_s
remaining_before_s
active_before
blocking_budget_exhausted
```

Untracked policies use `None` for budget/spent/remaining values. `active_before`
is zero for untracked policies.

`BlockingRelease` contains at least:

```text
spent_after_s
remaining_after_s
active_after
window_closed
window_wall_s
```

Untracked releases use `None` for budget-derived values and
`window_closed=false`.

The production `job_status` module imports one process-local singleton:

```python
from binnacle.blocking_wall_guard import BlockingWallTracker

blocking_wall_tracker = BlockingWallTracker()
```

Tests replace `job_status.blocking_wall_tracker` with a fresh tracker. Do not
add persistence for this object.

### 9.1.7 Exact policy names

These strings are frozen for Phase 2 and must be used in output/logs/tests:

```text
no_policy
no_turn
tracked
exhausted
capacity_untracked
```

Do not rename them during implementation without first updating this execution
contract and the server-guard specification in the same step.

Policy selection order for a positive request is:

```text
no matching configured budget -> no_policy
matching budget but no reliable base turn -> no_turn
matching budget + turn but tracker has no capacity -> capacity_untracked
matching budget + turn + remaining < 1 second -> exhausted
otherwise -> tracked
```

For `no_policy`, `no_turn`, and `capacity_untracked`, effective wait equals the
ordinary bounded wait. For `exhausted`, effective wait is zero.
`blocking_budget_exhausted` is true only for `exhausted`; it is false for the
other four policies.

For each positive specific-job call, resolve the budget exactly with:

```python
get_settings().jobs.blocking_wall_budget_for_client(current_client.get())
```

Do not cache a second independent copy of the client-budget map in
`job_status.py`; `get_settings()` is already process-cached and a server reload
picks up changed configuration together with a fresh tracker.

### 9.1.8 Exact accounting semantics

All tracker time is monotonic.

For an inactive tracked turn at acquisition time:

```text
spent_before = state.spent_s
remaining_before = max(0, budget - spent_before)
```

For an already-active window:

```text
active_elapsed = min(now, active_window_deadline) - active_window_started
spent_before = state.spent_s + max(0, active_elapsed)
remaining_before = max(0, active_window_deadline - now)
```

If `remaining_before < 1`, a positive request returns `exhausted` with effective
wait zero and does not increment `active_count`.

Otherwise:

```text
effective_wait = min(bounded_wait, floor(remaining_before))
```

A new active window uses:

```text
active_window_started = now
active_window_deadline = now + remaining_before
```

An overlapping lease shares that same deadline. It does not extend it.

On the final active release:

```text
window_wall = max(0, min(now, deadline) - window_started)
spent_s = min(budget_s, previous_committed_spent_s + window_wall)
```

Productive gaps after a window closes are not charged.

### 9.1.9 Exact `job_status` integration order

For `job_id is None`, preserve listing behavior exactly. Do not invoke the guard
and do not add policy fields to the listing payload.

For a specific job:

```text
1. save the original requested wait before any clamp;
2. compute bounded_wait = max(0, min(requested_wait, WAIT_MAX));
3. call jobs.job_state(job_id) once to validate existence;
4. if it is None, raise the existing ToolError BEFORE acquiring a guard lease;
5. if original requested wait <= 0, preserve the ordinary non-blocking path and
   do not acquire a lease;
6. for a positive request, resolve current client, current base turn, and client
   budget, then acquire one BlockingLease;
7. if effective_wait > 0, call _wait_for_exit(job_id, effective_wait);
8. if effective_wait == 0, call jobs.job_state(job_id) for a fresh non-blocking
   state and set waited_s = 0.0;
9. release the lease in a finally block;
10. after release, continue the existing log-read/process-scan/payload/summary
    path;
11. if the post-wait state unexpectedly becomes None, preserve the existing
    unknown-job ToolError behavior after the lease has safely released.
```

This order is decided. Do not spend Step 2.7 re-evaluating whether invalid jobs
should consume budget: they must not.

### 9.1.10 Exact structured-output rule

The existing listing payload remains unchanged.

For a specific job with **original requested `wait_seconds > 0`**, include these
keys even when there is no configured policy:

```text
wait_requested_s
wait_effective_s
blocking_budget_s
blocking_remaining_s
blocking_budget_exhausted
blocking_policy
```

Types:

```text
wait_requested_s: integer
wait_effective_s: integer
blocking_budget_s: integer | null
blocking_remaining_s: number | null
blocking_budget_exhausted: boolean
blocking_policy: string
```

`blocking_remaining_s` is the best after-call value from `BlockingRelease`.
For untracked policies it is `null`.

For an original zero-wait request, preserve the existing payload shape and do
not add these policy fields. This minimizes noise and backward-compatibility
surface.

For any original positive request, include `waited_s`, including
`waited_s=0.0` when exhaustion reduced the effective wait to zero.

### 9.1.11 Exact logging contract

Extend `event=job_status_timing`; do not create a second per-call policy event.
For every specific-job status call, retain existing timing fields and add:

```text
wait_requested_s
wait_bounded_s
wait_effective_s
waited_s
blocking_budget_s
blocking_spent_before_s
blocking_remaining_before_s
blocking_active_before
blocking_policy
blocking_budget_exhausted
turn
client
```

Use `na` for nullable numeric values in single-line logs. Use `-` for absent
turn/client. `wait_requested_s` means the original caller value;
`wait_bounded_s` is the existing 0..50 bound; `wait_effective_s` is the policy
result.

When a tracked release closes an active window, emit exactly:

```text
event=blocking_window_closed
```

with:

```text
call
turn
client
blocking_budget_s
blocking_window_wall_s
blocking_spent_after_s
blocking_remaining_after_s
```

The guard module returns data; `job_status.py` owns these log writes. Keep the
guard module free of logging dependencies. The window-close event must be
emitted from the same `finally` path that calls `lease.release()`, so an
exception/cancellation cannot silently commit accounting without telemetry.

Add these structured-result keys to
`ToolLoggingMiddleware.RESULT_KEYS` in Step 2.8:

```text
wait_requested_s
wait_effective_s
blocking_budget_s
blocking_remaining_s
blocking_budget_exhausted
blocking_policy
```

When a job is still running and the decision/release state says the turn budget
is exhausted, append this exact sentence to the existing human/model summary:

```text
Turn blocking budget exhausted; further positive waits in this turn will be non-blocking.
```

Do not present exhaustion as an error and do not tell the model that the job was
stopped.

### 9.1.11a Remove the obsolete "wait once" contract text

Phase 1 proved that the old "call `job_status` once" wording conflicts with the
new scheduling model. Step 2.8 must remove that obsolete wording in all three
places below; this is not optional.

1. In `src/binnacle/tools/run_command.py`, replace the current background
   summary template with exactly:

```python
summary = (
    f"Command {reason}; job_id={job_id}. "
    "Use job_status when the result is needed, or stop_job to cancel."
)
```

This removes both `Continue independent work` and `call job_status once`;
workflow belongs to Project instructions, while this result states only the
available job controls.

1. In the `job_status` MCP tool description/docstring in
   `src/binnacle/tools/job_status.py`, replace the old "Call once with
   wait_seconds=50" sentence with exactly:

```text
A positive wait blocks up to the requested duration (max 50 seconds) or any smaller effective turn budget; waiting never kills a still-running job.
```

Keep the measured clause "Only needed when run_command returned a job_id."
Workflow such as whether to continue waiting belongs to the ChatGPT Project
instructions, not the tool description.

1. Update `docs/tools/run_command.md` Section 4 to match that tool contract and
   the additive Phase-2 output fields.

Update `tests/contracts/test_descriptions.py` in the same step: rename
`test_job_status_keeps_the_only_needed_clause_and_wait_once` to
`test_job_status_keeps_the_only_needed_clause_and_wait_contract`, remove the old
wait-once expectation, and assert the new max-50/not-killed contract while
preserving the existing rule that tool descriptions do not own workflow.

The v2 Project rule file already owns the desired workflow:
`.claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt`.
Phase 2 does not need to redesign that file.

### 9.1.12 Exact `binnacle stats` semantics

Extend the existing job telemetry model, analyzer, and renderer. Do not create a
new top-level stats command.

For `job_status_timing` records:

- positive call = `wait_requested_s > 0`;
- non-blocking call = `wait_effective_s <= 0`;
- collect requested and effective wait distributions;
- count `blocking_policy` values;
- count `blocking_budget_exhausted=true`.

For `blocking_window_closed` records, aggregate by `(client, turn)` and retain
the maximum cumulative `blocking_spent_after_s` observed for that turn. A turn
may close multiple windows; report it once using the final cumulative value.

For utilization counts, compare each turn's final cumulative spent with its
budget:

```text
25%: spent / budget >= 0.25
50%: spent / budget >= 0.50
75%: spent / budget >= 0.75
100%: remaining < 1 second OR an exhausted call was observed for that turn
```

Report per-turn blocking wall p50/p90/p95/max from those final cumulative
values. Reuse the existing `_pct()` convention in `logstats_jobs.py`; do not
introduce a second percentile definition for Phase 2. Historical logs without
the new fields/events must continue to parse and render without synthetic
Phase-2 values.

The human renderer adds one section headed exactly:

```text
job_status blocking-wall guard:
```

with lines for:

```text
policies
waits: positive / nonblocking / exhausted
requested wait s: n / p50 / p90 / p95 / max
effective wait s: n / p50 / p90 / p95 / max
blocking wall / tracked turn s: n / p50 / p90 / p95 / max
utilization: >=25% / >=50% / >=75% / effectively-100%
```

Exact spacing may follow the existing `logstats_render.py` style, but these labels
and quantities are not optional.

### 9.1.13 Exact test-file and command matrix

Use these commands at minimum. Additional focused tests are allowed, but an
agent must not spend time rediscovering the baseline suite.

Step 2.1 baseline:

```bash
uv run pytest -q \
  tests/unit/core/test_config_loading.py \
  tests/unit/core/test_logging_result_fields.py \
  tests/unit/core/test_logstats_jobs.py \
  tests/integration/test_logging.py \
  tests/integration/test_http_workflows.py \
  tests/integration/test_jobs_lifecycle.py \
  tests/integration/test_job_manager_telemetry.py
```

Step 2.2:

```bash
uv run pytest -q tests/unit/core/test_config_loading.py
```

Step 2.3:

```bash
uv run pytest -q \
  tests/integration/test_logging.py \
  tests/integration/test_http_workflows.py \
  tests/unit/core/test_logging_result_fields.py
```

Steps 2.4–2.6:

```bash
uv run pytest -q tests/unit/core/test_blocking_wall_guard.py
```

Step 2.7:

```bash
uv run pytest -q \
  tests/unit/core/test_blocking_wall_guard.py \
  tests/integration/test_job_status_blocking_guard.py \
  tests/integration/test_jobs_lifecycle.py
```

Step 2.8:

```bash
uv run pytest -q \
  tests/integration/test_job_status_blocking_guard.py \
  tests/integration/test_logging.py \
  tests/integration/test_jobs_lifecycle.py \
  tests/unit/core/test_logging_result_fields.py \
  tests/contracts/test_descriptions.py
```

Step 2.9:

```bash
uv run pytest -q \
  tests/unit/core/test_logstats_jobs.py \
  tests/unit/core/test_logstats.py
```

Step 2.10:

```bash
uv run pytest -q \
  tests/integration/test_job_status_blocking_guard.py \
  tests/integration/test_jobs_lifecycle.py \
  tests/integration/test_http_workflows.py
```

Step 2.11:

```bash
uv run pytest -q \
  tests/unit/core/test_blocking_wall_guard.py \
  tests/integration/test_job_status_blocking_guard.py \
  tests/integration/test_job_status_blocking_guard_concurrency.py
```

Step 2.12:

```bash
uv run pytest -q
uv run pre-commit run --all-files
git diff --check
```

Before every numbered-step commit, run `uv run pre-commit run --all-files`.
Full pytest is mandatory only at Step 2.12 unless a preceding step uncovers a
cross-cutting regression that warrants it earlier.

### 9.1.14 Exact Step-2.11 benchmark artifact contract

Implement:

```text
scripts/benchmark_blocking_wall_guard.py
```

It measures tracker acquire/release overhead without sleeping and emits JSON.
Use at least 100,000 iterations per run and record p50/p90/p95/p99/max in
milliseconds. Run it three times on the Pi and retain all three runs plus the
median of the three run-level p95/p99 values.

Evidence files use the execution date:

```text
benchmarks/chat-mode-scheduling-v2/phase2-step11-guard-overhead-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase2-step11-guard-overhead-YYYY-MM-DD.md
```

The design target remains p95 <1 ms and p99 <2 ms. Do not encode those tight
thresholds as a normal CI wall-clock assertion. If the three-run evidence misses
the target, investigate/optimize within Step 2.11 and mark Step 2.11 incomplete
until the result is either fixed or explicitly escalated as a blocker.

### 9.1.15 Exact final artifact names

Step 2.12 uses the execution date and writes exactly:

```text
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-YYYY-MM-DD.md
```

Do not invent a different naming scheme.

### 9.1.16 Mandatory per-step persistence

Every numbered step, including the baseline-only Step 2.1, must end by:

1. updating both canonical progress files;
2. running the step's required tests;
3. running `uv run pre-commit run --all-files`;
4. running the production-isolation check from Section 11.9;
5. committing all files for that step with a `Phase 2.N:` subject;
6. pushing `feature/chat-mode-blocking-wall-guard` to `origin`;
7. waiting for the pushed branch's GitHub `ci.yml` run to finish successfully;
8. only then reporting the step complete to the user.

This makes a new transaction recoverable from GitHub even if the previous
ChatGPT turn ended immediately after a step.

The repository CI runs on every push. After pushing a numbered-step commit, use:

```bash
RUN_ID=$(gh run list \
  --workflow ci.yml \
  --branch feature/chat-mode-blocking-wall-guard \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```

If that CI run fails, the numbered step is not complete; diagnose/fix it in the
same step, recommit/push, and wait for green CI. If GitHub itself is unavailable,
use the blocker SOP rather than calling the step complete.

Use these exact commit subjects:

| Step | Commit subject |
| --- | --- |
| 2.1 | `Phase 2.1: freeze blocking guard baseline` |
| 2.2 | `Phase 2.2: add blocking wall budget configuration` |
| 2.3 | `Phase 2.3: publish MCP base-turn context` |
| 2.4 | `Phase 2.4: add sequential blocking wall tracker` |
| 2.5 | `Phase 2.5: account overlapping blocking waits` |
| 2.6 | `Phase 2.6: bound blocking wall tracker state` |
| 2.7 | `Phase 2.7: integrate blocking wall guard with job status` |
| 2.8 | `Phase 2.8: expose blocking wall policy telemetry` |
| 2.9 | `Phase 2.9: aggregate blocking wall guard telemetry` |
| 2.10 | `Phase 2.10: validate blocking guard with real jobs` |
| 2.11 | `Phase 2.11: validate guard concurrency and overhead` |
| 2.12 | `Phase 2.12: complete blocking wall guard phase` |

## 10. Worktree and branch strategy

Phase 2 implementation should not be developed directly in the Phase-1 design
worktree.

At the beginning of Step 2.1, use the exact branch/worktree contract from
Section 9.1.1.

If the Phase-2 branch does not yet exist, execute the equivalent of:

```bash
git -C /home/grammy-jiang/Projects/binnacle-chat-scheduling-design fetch origin
git -C /home/grammy-jiang/Projects/binnacle-chat-scheduling-design status --short --branch
git -C /home/grammy-jiang/Projects/binnacle-chat-scheduling-design worktree add \
  -b feature/chat-mode-blocking-wall-guard \
  /home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard \
  origin/design/chat-mode-scheduling-v2
```

The design worktree must be clean and its local design branch must be
synchronized with `origin/design/chat-mode-scheduling-v2` before creation.

If the branch already exists and the canonical worktree exists, reuse it. If the
branch exists but the canonical worktree does not, attach it with:

```bash
git -C /home/grammy-jiang/Projects/binnacle-chat-scheduling-design worktree add \
  /home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard \
  feature/chat-mode-blocking-wall-guard
```

Do not create alternate Phase-2 branch or worktree names.

### 10.1 Interrupted-worktree recovery rules

Never run `git reset --hard`, `git clean`, delete/recreate the Phase-2 branch, or
discard a dirty canonical worktree merely to make it match this plan.

After `git fetch origin`, recover according to this exact table:

| Observed Phase-2 state | Required action |
| --- | --- |
| branch/worktree absent, progress files absent | normal Step 2.1 creation path |
| canonical worktree dirty | treat as an interrupted current step; read progress files and diff, preserve changes, continue that same step |
| clean local branch only ahead of origin | keep local commits; verify progress/tests and push, never reset them |
| clean local branch only behind origin | `git pull --ff-only` in the canonical Phase-2 worktree, then resume from progress |
| local/origin diverged | mark current step `blocked`; do not reset/rebase/force-push automatically |
| progress says a step complete but worktree has uncommitted changes for that step | treat the step as inconsistent/incomplete; reconcile those changes before moving to the next step |
| progress and Git history disagree on next step | Git history plus committed progress files must be reconciled before implementation; do not guess |

A divergence usually means another agent/session wrote the same branch. It is a
real coordination blocker, not permission to destroy one side.

## 11. Global execution SOP

This SOP applies to every Phase-2 implementation step.

### 11.1 Start-of-transaction recovery

A new ChatGPT transaction must not assume it knows the current Phase-2 state.
Before Step 2.1, the Phase-2 branch/worktree and progress files intentionally do
not exist. In that one case, absence of all three is the explicit checkpoint
`next_step=2.1`; use the design worktree to execute Step 2.1. If the Phase-2
branch exists but progress files are missing, treat Step 2.1 as incomplete and
finish/recover it rather than guessing a later step.

Otherwise it should:

1. use the canonical branch/worktree paths in Section 9.1.1;
2. read this document;
3. read `docs/chat-mode-scheduling-v2-server-guard.md`;
4. read `benchmarks/chat-mode-scheduling-v2/phase2-progress.json` and `.md`;
5. inspect `git status --short --branch` and `git log -12 --oneline --decorate`;
6. use `last_completed_step` / `next_step` from the progress JSON and verify it
   against committed Git history;
7. run the production-isolation checks from Section 11.9;
8. continue from the exact `next_step`; do not re-run completed steps.

Do not restart a completed step merely because the chat is new.

### 11.2 Step execution contract

When the user says, for example, "start 2.4", that means:

> perform everything defined for Step 2.4 and stop only when its exit criteria
> are met, or when a genuine external blocker prevents further progress.

Starting a background job is **not** a stop point. If a step starts a long test
or command, ChatGPT must continue calling `job_status` and performing any other
available work until the step reaches its defined checkpoint.

If the user requests multiple steps in one instruction, for example "do 2.4 and
2.5", do not stop between them unless a real blocker occurs.

### 11.3 Long-running commands

For commands expected to run longer than about 10 seconds (including full
pytest and all-files pre-commit in this repository):

- use `background=true`;
- retain the returned `job_id`;
- use blocking `job_status(wait_seconds=50)` rather than rapid polling;
- if the job is still running and no independent work remains, continue the
  dependency wait in the same ChatGPT turn;
- never report "started" as if it were "finished";
- if the ChatGPT platform itself terminates the turn, durable Binnacle state
  should permit the next transaction to resume from the existing job/checkpoint.

### 11.4 Testing order

Within each step, use this order:

```text
new/changed focused unit tests
-> relevant integration tests
-> affected existing tests
-> the exact step command matrix in Section 9.1.13
-> uv run pre-commit run --all-files
```

Do not run the complete repository suite after every tiny edit. Full pytest is
mandatory at Step 2.12 and optional earlier only when a discovered cross-cutting
regression makes it necessary.

### 11.5 Test design principles

- inject/fake the monotonic clock for tracker unit tests;
- do not use multi-minute sleeps in CI;
- use real short jobs only for integration tests;
- explicitly test cancellation/error `finally` cleanup;
- test concurrent access, not just sequential state changes;
- preserve current no-policy behavior with regression tests;
- avoid timing assertions so tight that normal Pi scheduling jitter makes CI
  flaky;
- record performance evidence separately from strict functional CI gates when
  appropriate.

### 11.6 Commit discipline

Every numbered step ends with one coherent commit and push, including baseline
Step 2.1. Update the canonical Phase-2 progress files in that commit. This is
mandatory so a later transaction can recover without conversation memory.

Use the exact commit-subject table in Section 9.1.16. Do not mix unrelated
cleanup/refactoring into these commits.

### 11.7 Status report after each step

Use a stable summary shape:

```text
Phase 2 progress: N / 12 complete

Completed:
- 2.1 ...
- 2.2 ...

This step:
- implementation result
- tests/evidence
- important findings

Safety:
- production status
- default policy status

Commit:
- hash and subject

Next:
- exact next step
```

### 11.8 Blocker handling

A blocker is not simply a failing test. ChatGPT should investigate and fix normal
implementation/test failures within the current step.

Stop and report only when continuation requires something unavailable to the
current environment, such as:

- explicit user credential/login action that cannot be recovered locally;
- unavailable external service that the step fundamentally requires;
- contradictory requirements requiring a user decision;
- a platform/tool failure that prevents access to the worktree or evidence.

When blocked, record:

```text
last completed step
current branch/HEAD
working-tree state
what was attempted
exact error/evidence
whether any background jobs remain
safe resume instruction
```

If Git and GitHub remain available, update both Phase-2 progress files with
phase/step state `blocked`, keep `last_completed_step` unchanged, keep
`next_step` pointing at the blocked step, and push a checkpoint commit with
subject:

```text
Phase 2.N: checkpoint blocked
```

Do not count that checkpoint as the step's completion commit. When work resumes,
continue the same step and later create its normal completion commit from the
fixed table in Section 9.1.16. If the blocker itself prevents Git persistence,
leave the working tree intact and include its exact status in the user-facing
blocker report.

### 11.9 Production isolation

Before declaring **every numbered step complete**, run these exact safety
checks (read-only against production):

```bash
git -C /home/grammy-jiang/Projects/binnacle status --short --branch
systemctl --user is-active binnacle-mcp.service
grep -n "blocking_wall_budget_s_by_client" \
  /home/grammy-jiang/.config/binnacle/config.toml || true
```

Required result:

- production checkout is on `master` and clean;
- `binnacle-mcp.service` is `active`;
- production config contains no Phase-2 blocking-budget setting.

The production HEAD at planning time was `83862b0`, but another legitimate
workflow may advance `master` later. Do not reset production to that hash. Clean
branch/config/service state is the invariant.

Phase 2 is not a deployment phase.

## 12. Step 2.1 — Phase-2 worktree and baseline freeze

Target duration: **10–15 minutes**.

### Objective

Create/recover a dedicated Phase-2 workspace and freeze the current runtime
baseline before policy code is introduced.

### Entry criteria

- Phase 1 Step 1.9 complete;
- `design/chat-mode-scheduling-v2` contains `cc1b014` and this plan;
- Phase-1 design worktree clean;
- production `master` clean.

### Tasks

1. Create/recover the exact branch/worktree from Section 9.1.1.
2. Create the two canonical progress files from Section 9.1.2 with all 12 JSON
   step states initialized to `not_started` (Markdown: `NOT STARTED`), then mark
   2.1 `complete` only at exit.
3. Record design source HEAD and production `master` HEAD/service state.
4. Freeze the current tool contract by recording the relevant constants/fields
   from `src/binnacle/tools/job_status.py`: input `wait_seconds 0..50`, current
   `OUTPUT_SCHEMA`, and current `job_status_timing` fields.
5. Record current correlation behavior from `logging_middleware.py`: full
   `X-Request-Id` is logged as `turn=`, but no base-turn ContextVar exists yet.
6. Run the exact Step-2.1 baseline command from Section 9.1.13.
7. Run `uv run pre-commit run --all-files`.
8. Run the production-isolation commands from Section 11.9.
9. Update progress JSON/Markdown with test results and baseline facts.
10. Commit with subject `Phase 2.1: freeze blocking guard baseline` and push.

### Expected files

Primarily evidence/documentation. No production runtime behavior should change.

### Exit criteria

- Phase-2 branch/worktree exists and is clean;
- focused baseline is green;
- current public/tool contract is recorded;
- production is unchanged;
- next step is 2.2.

### Do not do in 2.1

- do not add a budget setting;
- do not add `current_turn`;
- do not modify `job_status` behavior.

## 13. Step 2.2 — Configuration contract

Target duration: **10–15 minutes**.

### Objective

Add an opt-in per-client blocking-wall budget configuration without changing
runtime behavior yet.

### Contract

Implement the exact configuration API in Section 9.1.4. The field is:

```python
blocking_wall_budget_s_by_client: dict[str, int] = {}
```

Valid configured budgets: `1..3600` seconds.

### Prefix matching

Client identity already distinguishes legacy and modern OpenAI names such as:

```text
openai-mcp
openai-mcp(ChatGPT)
```

Use prefix matching. If more than one prefix matches, prefer the **longest
matching prefix** so behavior is deterministic and more-specific configuration
can override a broad prefix.

### Tests

Cover at least:

- empty map;
- lower boundary 1;
- upper boundary 3600;
- invalid 0;
- invalid >3600;
- legacy OpenAI name;
- modern ChatGPT name;
- unrelated client;
- multiple matching prefixes / longest-prefix wins;
- TOML loading and the exact environment JSON mapping form from Section 9.1.4.

### Exit criteria

- configuration model and matching helper are tested;
- repository default remains disabled/empty;
- `job_status` behavior is still unchanged;
- focused config suite and pre-commit pass.

## 14. Step 2.3 — Turn correlation ContextVar

Target duration: **10–20 minutes**.

### Objective

Make reliable base-turn identity available to synchronous tool code.

### Tasks

1. Add `current_turn: ContextVar[str | None]` to `callctx.py`.
2. Extract base turn from the observed `X-Request-Id` shape `<base>/<call>`.
3. Set it in `ToolLoggingMiddleware` before `call_next()`.
4. Reset it in `finally` exactly like other call context.
5. Ensure FastMCP's sync-tool thread hop receives the copied ContextVar.
6. Preserve the full existing `turn=` logging field; base-turn context is an
   execution aid, not a reason to discard raw correlation evidence.

### Conservative parsing rule

If the header is absent or cannot be reliably parsed, `current_turn=None`.
Do not infer a turn from MCP session ID or request sequence.

### Tests

- valid `<base>/<call>` extraction;
- absent header;
- malformed/no-slash header;
- two different turns sequentially;
- concurrent requests with distinct turns;
- exception path resets context;
- synchronous tool observes the intended `current_turn`.

### Exit criteria

- context is correct and leak-free;
- no guard policy exists yet;
- logging regressions absent.

## 15. Step 2.4 — Blocking-wall tracker, sequential core

Target duration: **15–20 minutes**.

### Objective

Implement the guard as a standalone deterministic state machine for one turn and
sequential waits.

### Module and API

Use exactly `src/binnacle/blocking_wall_guard.py` and the public names/API in
Section 9.1.6. Do not embed the tracker state machine directly in
`job_status.py`, and do not rename the frozen public Phase-2 classes during this
step.

### Clock

Inject a clock whose production default is `time.monotonic`. Unit tests should
advance a fake clock rather than sleep.

### Required sequential cases

1. No policy -> ordinary requested/per-call bounded wait.
2. New tracked turn -> full configured budget available.
3. 50-second request, job returns after 3 seconds -> charge about 3 seconds.
4. Later sequential wait -> remaining budget reflects prior actual charge.
5. Productive time between windows -> not charged.
6. Remaining budget below one second -> effective wait zero.
7. New base turn -> fresh budget.
8. Nonmatching client -> no policy.
9. Missing turn -> `no_turn`.

### Exit criteria

- deterministic sequential accounting tests pass;
- monotonic clock is explicit;
- no integration into `job_status` yet.

## 16. Step 2.5 — Overlapping-wait union accounting

Target duration: **15–20 minutes**.

### Objective

Make concurrent positive waits consume union wall time rather than summed wait
time.

### Required behavior

The first positive wait opens a window and establishes the shared deadline.
Later overlapping waits use the remaining time to that same deadline.

Only a positive effective wait increments `active_count`.

Each lease releases in `finally`. The last release closes the active window and
charges its union duration.

### Required cases

- two fully overlapping waits;
- five fully overlapping waits;
- partial overlap;
- one wait exits early while another remains active;
- all waits exit before deadline;
- one or more reach deadline;
- release ordering differs from acquire ordering;
- exception during caller work still releases lease;
- cancellation-equivalent cleanup path;
- zero-effective wait never increments active count.

### Concurrency rule

The tracker lock may protect state mutation but must be released before the
actual job wait begins.

### Exit criteria

- concurrency-focused unit tests prove union accounting;
- no active lease can be stranded through normal exception paths;
- no `job_status` integration yet.

## 17. Step 2.6 — LRU bound, eviction, and fallback policies

Target duration: **15–20 minutes**.

### Objective

Bound process-local turn state and make all untracked cases explicit.

### Capacity

Tracker capacity is **4096 total turn records**. The precise eviction rule is
defined in Section 9.1.6. Inactive records use LRU eviction and active records
are never evicted.

If the tracker cannot allocate a record because capacity is entirely active,
return `capacity_untracked` and preserve ordinary per-call behavior.

### Required tests

- inactive LRU eviction order;
- recently used record retained;
- active record never evicted;
- mixed active/inactive pressure;
- all-active capacity fallback;
- fallback does not mutate another turn's accounting;
- last-seen update behavior;
- new turn can be tracked after inactive space becomes available.

### Exit criteria

- memory behavior is bounded and deterministic;
- policy outcome set is tested;
- active accounting cannot be silently corrupted by eviction.

## 18. Step 2.7 — Integrate the guard into `job_status`

Target duration: **15–20 minutes**.

### Objective

Make the tracker control actual positive `job_status` blocking for explicitly
configured clients.

### Wait terminology

Keep these values separate:

```text
requested wait
bounded wait       # current per-call <=50 rule
effective wait     # after turn-budget decision
actual waited time
```

Example:

```text
requested = 50
bounded = 50
turn remaining = 17.8
effective = 17
actual waited = 4.2 because job exited
```

### Integration sequence

Follow the exact ordered algorithm in Section 9.1.9. Unknown-job existence is
validated **before** lease acquisition; invalid job IDs must not consume budget.
Do not revisit that design choice during Step 2.7.

### Backward-compatibility gate

With default empty configuration:

- current `job_status` behavior must remain unchanged;
- old integration/lifecycle tests must continue passing;
- no hidden per-turn tracking should occur.

### Exit criteria

- configured policy affects only matching client+turn calls;
- no-policy/no-turn/fallback paths preserve ordinary behavior;
- durable jobs are never stopped by budget exhaustion;
- focused lifecycle and policy integration tests pass.

## 19. Step 2.8 — Structured output, summaries, and detailed telemetry

Target duration: **15–20 minutes**.

### Objective

Make the policy visible to both the model and operators.

### Structured fields

For positive-wait status calls, add the fields defined in Section 9. Update the
explicit output schema accordingly.

### Exhausted summary

When the job remains running and turn budget is exhausted, the one-line content
must clearly state that:

- the job is still running;
- the turn's blocking budget is exhausted;
- further positive waits in this turn will be non-blocking.

This is informational policy state, not a tool error.

### Logs

Extend `job_status_timing` or add a clearly related policy event so the requested,
bounded, effective, actual, budget, remaining, active-count, policy, client, and
turn values can be reconstructed.

Emit a window-close event when union accounting is committed. Update
`docs/logging.md` in the same step with the exact new/extended event fields.
Update `docs/tools/run_command.md` and the tool/result wording exactly as required
by Section 9.1.11a.

### Tests

- remove/replace every obsolete `call job_status once` / `Call once with
  wait_seconds=50` wording identified in Section 9.1.11a;
- structured schema fields;
- normal tracked wait;
- early job exit;
- exhausted wait;
- no-policy/no-turn output behavior;
- summary wording contains the exhaustion fact;
- logs contain unambiguous key/value fields;
- `ToolLoggingMiddleware.RESULT_KEYS` lifts model-visible policy fields where
  appropriate without leaking sensitive data.

### Exit criteria

- a model can tell why a requested positive wait became non-blocking;
- logs can reconstruct the decision;
- old clients remain compatible.

## 20. Step 2.9 — `binnacle stats` guard aggregation

Target duration: **15–20 minutes**.

### Objective

Make Phase-2 behavior measurable from normal journal evidence.

### Metrics

Aggregate at least:

```text
job_status positive calls
job_status non-blocking calls
requested wait distribution
effective wait distribution
budget-exhausted calls
tracked / no_policy / no_turn / capacity_untracked counts
blocking-wall union per turn
turn budget utilization crossings: 25 / 50 / 75 / 100 percent
blocking-wall per-turn p50 / p90 / p95 / max
```

### Important accounting rule

A turn may contain multiple active windows. Per-turn blocking wall is cumulative
across those windows. Do not report each window as if it were a separate turn.

### Implementation location

Extend exactly:

```text
logstats_models.py
logstats_jobs.py
logstats_render.py
```

Keep parser behavior backward compatible with historical journals that have no
new fields/events.

### Tests

Use synthetic logs covering:

- one turn, one window;
- one turn, multiple windows;
- multiple turns;
- exhausted calls;
- no-turn/capacity-untracked calls;
- historical records with no Phase-2 telemetry;
- percentile and utilization counts;
- human-readable rendering.

### Exit criteria

- `binnacle stats` can reconstruct guard use from logs;
- historical logs still parse/render;
- focused logstats tests pass.

## 21. Step 2.10 — Real-job integration suite

Target duration: **15–20 minutes**.

### Objective

Validate policy behavior against real short background jobs rather than only a
fake clock/state machine.

### Test scenarios

Use the following concrete fixtures as the default integration cases; do not
spend time designing a second set unless one proves flaky on the Pi:

1. **Early exit:** configured budget 3 s; job `sleep 0.2`; request 2 s; expect
   exited state, actual wait well below 2 s, and remaining budget near 3 s minus
   actual wait. Use broad timing tolerance rather than exact milliseconds.
2. **Sequential/exhaustion:** configured budget 3 s; job `sleep 5`; issue
   positive waits against the same turn until cumulative actual union reaches
   the integer-floor exhaustion boundary; the next positive request must have
   effective wait 0 while the job remains alive. Clean up the job explicitly.
3. **Post-exhaustion durability:** after case 2 exhaustion, verify the same job
   is still listed/running, then stop it through normal job cleanup.
4. **Already exited:** use `true` (or an already-recorded completed fixture job)
   and verify a positive request returns promptly and charges effectively zero
   wall time.
5. **Explicit zero wait:** request 0; no policy fields are added and no lease is
   acquired.
6. **No policy:** matching turn but client has no configured budget; behavior is
   ordinary per-call waiting with `no_policy` for a positive request.
7. **No turn:** configured client but `current_turn=None`; behavior is ordinary
   per-call waiting with `no_turn`.
8. **Invalid ID:** call a nonexistent job ID and verify the existing ToolError is
   raised before tracker acquisition and tracker state remains unchanged.
9. **HTTP/context end-to-end:** extend `tests/integration/test_http_workflows.py`
   with one positive-wait status call whose request carries a known
   `X-Request-Id=<base>/<call>` and a test client prefix with a configured budget.
   Assert the tool result is policy-tracked and the journal/caplog shows the
   expected base turn and client. This is the cross-layer proof that middleware
   ContextVars reach the synchronous `job_status` implementation.

Integration tests may shorten `sleep 5` only if total semantics remain the same;
never lengthen these into multi-minute tests.

### Assertions

Verify together:

```text
job state
actual waited duration within broad tolerance
policy fields
budget spent/remaining
summary content
journal telemetry
durable job survival
```

### Exit criteria

- real job lifecycle confirms the unit model;
- no policy path regresses existing lifecycle behavior;
- guard never kills a job.

## 22. Step 2.11 — Concurrency, reload semantics, and guard overhead

Target duration: **15–20 minutes**.

### Objective

Validate the hard concurrency cases and collect performance evidence.

### Concurrent integration cases

Use short `sleep 5` fixture jobs and these patterns:

- two simultaneous positive waits in one turn with budget 3 s and 2 s requested
  by each call; union charge should be roughly one 2 s interval, not 4 s;
- five simultaneous positive waits in one turn with budget 3 s and 1 s requested
  by each call; union charge should be roughly one 1 s interval, not 5 s;
- a second wave starts while the first window is still active and must share the
  original deadline rather than extend it;
- waits for different jobs under the same turn still share one turn budget;
- different turns concurrently maintain independent state/deadlines;
- one turn can exhaust while another retains budget.

Use barriers/events in the test harness to synchronize call start rather than
assuming thread scheduling order. Timing assertions should use broad bounds; the
primary assertions are tracker state, shared deadline, and non-summed union wall.
Clean up all fixture jobs in `finally`.

### Reload semantics

Do not restart production services for this test. Start a normal durable fixture
job, then replace `job_status.blocking_wall_tracker` with a fresh
`BlockingWallTracker()` instance while that job is still running. Verify that the
job remains observable and stoppable. This simulates process-local guard-state
loss without altering durable job storage.

Required outcome:

- durable job remains intact;
- later `job_status` still works;
- lost ephemeral budget state can make the guard less strict but cannot corrupt
  work;
- no attempt is made in Phase 2 to persist the turn tracker.

### Guard overhead evidence

Measure tracker decision/acquire/release overhead on the Pi 5.

Target evidence:

```text
p95 < 1 ms
p99 < 2 ms
```

Do not create an unnecessarily tight CI wall-clock gate that becomes flaky on a
shared Pi. Functional CI should prove algorithmic behavior; a dedicated evidence
run should report measured p50/p90/p95/p99/max. Do not add a normal CI wall-clock threshold for the 1 ms / 2 ms targets. Use
the exact three-run evidence contract in Section 9.1.14.

### Exit criteria

- concurrent union semantics pass;
- reload does not affect durable jobs;
- performance evidence is recorded;
- no unresolved race/leak is known.

## 23. Step 2.12 — Final Phase-2 validation and handoff

Target duration: **15–20 minutes**.

### Objective

Freeze Phase 2 as an implementation result without deploying it.

### Required validation

1. Run focused Phase-2 tests.
2. Run the full repository pytest suite.
3. Run all pre-commit hooks.
4. Verify typing/lint/architecture/readability checks.
5. Check `git diff --check`.
6. Verify production checkout/config/service remain untouched.
7. Verify repository default budget remains disabled.
8. Review MCP schema changes and ensure they are limited to intended
   `job_status` output additions; input `wait_seconds <=50` remains.
9. Review module/function size against repository readability guidance.
10. Confirm no tracker state leaks between tests.
11. Write final Phase-2 evidence/report.
12. Commit and push the Phase-2 branch, then wait for the pushed `ci.yml` run
    to finish green using Section 9.1.16.

### Final evidence should answer

- Is default behavior unchanged?
- Is prefix configuration correct?
- Is base-turn correlation reliable and conservative?
- Does sequential accounting charge actual wall time?
- Do overlapping waits charge wall-time union?
- Can any exception strand an active lease?
- Is memory bounded?
- Are active records protected from eviction?
- Does capacity fallback preserve ordinary behavior?
- Is exhaustion model-visible?
- Can logs/stats reconstruct policy decisions?
- Do durable jobs survive exhaustion and tracker reload?
- What overhead was measured?
- Is the implementation ready for Phase 3 offline replay?

### Expected final artifacts

Use the exact dated artifact names from Section 9.1.15.

### Exit criteria

```text
PHASE 2 COMPLETE
PHASE 3 NOT STARTED
production unchanged
```

## 24. Phase-2 acceptance checklist

Phase 2 is complete only if all items below are true.

### Configuration and compatibility

- [ ] default budget map is empty;
- [ ] configured budgets validate within 1..3600 s;
- [ ] client matching is deterministic;
- [ ] existing `wait_seconds` input bound remains 0..50;
- [ ] no-policy behavior is regression-tested.

### Correlation

- [ ] reliable base turn published via ContextVar;
- [ ] missing/malformed turn does not create guessed state;
- [ ] context resets correctly on success/error/concurrency paths.

### Accounting

- [ ] early exit charges actual time;
- [ ] sequential waits accumulate;
- [ ] productive gaps are free;
- [ ] overlapping waits charge union time once;
- [ ] shared active-window deadline is correct;
- [ ] less than one second remaining yields effective zero;
- [ ] release occurs in `finally`;
- [ ] monotonic clock used.

### Memory and fallback

- [ ] inactive tracker state is bounded;
- [ ] active leases are never evicted;
- [ ] all-active capacity produces explicit untracked fallback;
- [ ] reload loss affects only guard strictness, not durable jobs.

### Tool behavior

- [ ] guard only reduces blocking duration;
- [ ] guard never kills jobs;
- [ ] exhaustion is visible in structured output;
- [ ] exhaustion is explicit in summary text;
- [ ] unknown job/error behavior remains safe.

### Telemetry and stats

- [ ] requested/bounded/effective/actual wait visible in logs;
- [ ] policy/budget/spent/remaining/active state reconstructible;
- [ ] window-close event emitted;
- [ ] per-turn union wall aggregatable;
- [ ] utilization buckets available;
- [ ] p50/p90/p95/max available;
- [ ] historical log parsing remains compatible.

### Validation and safety

- [ ] focused tests green;
- [ ] full pytest green;
- [ ] pre-commit green;
- [ ] concurrency/reload evidence green;
- [ ] overhead evidence recorded;
- [ ] production master/config/service unchanged;
- [ ] no Phase-2 budget deployed;
- [ ] Phase-2 report committed and pushed.

## 25. Conditions for moving to Phase 3

Phase 3 may begin only after Step 2.12 completes.

Phase 3 will not immediately deploy the guard. It will replay historical traces
through candidate budgets, initially:

```text
120 s
300 s
600 s
```

and compare the old 10-second one-shot behavior where useful.

Phase 3 must use actual observed wait durations/job exits, not requested waits
alone. Its purpose is to reject bad candidates before spending live ChatGPT C-arm
trials.

The final production decision remains later, after the full live A/B/C comparison
and all original acceptance gates.

## 26. Timeout provenance requirement before Phase 4

Phase 1 showed that reliability failures are not all the same. Before the Phase-4
live confirmatory run, evidence must distinguish at least:

1. pre-MCP/submission failure;
2. active-turn/browser-stream timeout;
3. MCP work completed but browser settling/timing timed out;
4. genuine Binnacle dependency-wait budget exhaustion.

This classification is diagnostic only. It must never be used to erase a
submitted failure from the canonical user-experience sample.

Phase 2 telemetry should make category 4 unambiguous. Browser/harness provenance
may be improved in Phase 2 if naturally adjacent to evidence collection, but that
must not expand Phase 2 into a browser reliability redesign.

## 27. New-transaction bootstrap procedure

When a future ChatGPT transaction is asked to continue this work, use this
procedure before implementation. If the canonical Phase-2 branch/worktree and
progress files are all absent, that means Phase 2 has not started and the next
step is exactly 2.1. If the branch exists but progress files do not, recover and
finish Step 2.1 first. Otherwise:

```text
1. Use `/home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard` on
   `feature/chat-mode-blocking-wall-guard`; create it only if Step 2.1 has not
   yet done so, using Section 10.
2. Read `docs/chat-mode-scheduling-v2-phase2-execution-plan.md`.
3. Read `docs/chat-mode-scheduling-v2-server-guard.md`.
4. Read the Phase-1 Step 1.9 aggregate report.
5. Read the canonical `phase2-progress.json` and `.md`.
6. Run `git status --short --branch` and `git log -12 --oneline --decorate`.
7. Verify progress JSON against Git history and take its exact `next_step`.
8. Run the production-isolation commands from Section 11.9.
9. Execute only the requested step range, continuously until its defined stop
   point, using the fixed API/test decisions in Section 9.1.
10. Update progress files, test, pre-commit, safety-check, commit, and push before
    reporting a step complete.
```

Do not ask the user to restate decisions already captured here unless repository
state contradicts the document or a genuinely new decision is required.

## 28. Current checkpoint after cold-start review

After the cold-start-agent review of this plan:

```text
Phase 1: 9 / 9 complete
Phase 2: 0 / 12 complete
Phase 2 implementation: NOT STARTED
Phase 2 branch/worktree: NOT YET CREATED
production deployment: NONE
Phase-1 evidence checkpoint: cc1b014
planning branch: design/chat-mode-scheduling-v2
next implementation step: 2.1
```

Writing and committing this planning document does **not** count as starting
Step 2.1.

## 29. Cold-start audit verdict

This execution plan was re-reviewed from the perspective of an agent with **no
conversation memory and no prior task knowledge**. The review deliberately
looked for places where such an agent would have to rediscover architecture,
choose filenames/branches, invent state-machine semantics, decide test scope, or
resolve conflicting documents before it could work.

Those decisions are now frozen in Section 9.1 and the numbered steps. In
particular, a cold-start agent is not expected to investigate or redesign:

- branch/worktree names or creation source;
- Phase-2 progress/checkpoint filenames or status schema;
- source/test/document ownership;
- config field/matching semantics;
- base-turn parsing;
- tracker public API, capacity, lock type, or policy strings;
- union-wall accounting formulas;
- unknown-job/lease ordering;
- structured output/log event fields;
- removal of obsolete `job_status once` wording;
- logstats aggregation semantics;
- focused test commands;
- real-job/concurrency fixture shapes;
- performance evidence artifact names;
- per-step commit subjects, push, and CI completion rules;
- production-isolation commands;
- interrupted-worktree recovery policy.

Normal implementation work still requires reading the target source files,
writing code/tests, and debugging failures. That is execution, not a request to
re-open the design. The only intentionally discretionary choices left are
private helper/local-variable names and similarly local implementation details
that do not alter the frozen contracts.

If an implementation fact genuinely contradicts a frozen contract, the agent
must record that contradiction in `phase2-progress.json` / `.md` and treat it as
a design blocker rather than silently inventing a new rule.
