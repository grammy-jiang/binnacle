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

### 5.1 Default behavior is unchanged

Repository defaults must contain no active client budget. With an empty budget
map, existing clients must retain the current `job_status` behavior.

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

An implementation may encapsulate additional private fields if tests require
them, but the semantics above must remain recognizable.

### 7.3 First positive wait in a new window

Conceptually:

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

The implementation should expose explicit policy outcomes rather than relying on
implicit null fields. At minimum:

```text
no_policy
no_turn
tracked
exhausted
capacity_untracked
```

Names may be refined during implementation if the final set remains unambiguous
and is documented/tested.

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

Log fields should include at least:

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

Positive-wait structured output should expose at least:

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

## 10. Worktree and branch strategy

Phase 2 implementation should not be developed directly in the Phase-1 design
worktree.

At the beginning of Step 2.1:

1. verify `design/chat-mode-scheduling-v2` contains Phase-1 checkpoint
   `cc1b014` and this execution-plan document;
2. verify that design worktree is clean and synchronized with origin;
3. create a new branch from the current design branch tip, for example:
   `feature/chat-mode-blocking-wall-guard`;
4. create a dedicated worktree, for example:
   `~/Projects/binnacle-chat-blocking-wall-guard`;
5. leave production `~/Projects/binnacle` on `master` untouched.

If the branch/worktree already exists in a later transaction, reuse it rather
than create another one. First inspect its HEAD, status, and relationship to the
Phase-1/design branch.

## 11. Global execution SOP

This SOP applies to every Phase-2 implementation step.

### 11.1 Start-of-transaction recovery

A new ChatGPT transaction must not assume it knows the current Phase-2 state.
It should:

1. locate the Phase-2 worktree and branch;
2. read this document;
3. read `docs/chat-mode-scheduling-v2-server-guard.md`;
4. read the latest Phase-2 checkpoint/report if one exists;
5. inspect `git status --short --branch` and recent commits;
6. determine the last completed numbered step from committed evidence;
7. verify production `master` has not been modified;
8. continue from the next incomplete step.

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

For known-long commands:

- prefer `background=true` where appropriate;
- retain the returned `job_id`;
- use blocking `job_status(wait_seconds=50)` rather than rapid polling;
- if the job is still running and no independent work remains, continue the
  dependency wait in the same ChatGPT turn;
- never report "started" as if it were "finished";
- if the ChatGPT platform itself terminates the turn, durable Binnacle state
  should permit the next transaction to resume from the existing job/checkpoint.

### 11.4 Testing order

Within each step, prefer:

```text
new/changed focused unit tests
-> relevant integration tests
-> affected existing tests
-> pre-commit for touched files or all files as appropriate
```

Do not run the complete repository suite after every tiny edit. Run full pytest
at major integration checkpoints and mandatorily at Step 2.12.

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

Each numbered step should normally end with one coherent commit when it changes
tracked files. A step may intentionally produce no commit if it is purely an
investigation/baseline step, but its result must then be recorded in the Phase-2
checkpoint document before moving on.

Recommended commit pattern:

```text
Phase 2.2: add blocking wall budget configuration
Phase 2.3: publish MCP base-turn context
Phase 2.4: add sequential blocking wall tracker
...
```

Do not mix unrelated cleanup/refactoring into these commits.

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

### 11.9 Production isolation

Before and after major steps, verify as appropriate:

```text
~/Projects/binnacle remains on master
production worktree is clean
binnacle-mcp.service remains in its expected state
production config is unchanged
no experimental Phase-2 budget has been enabled
```

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

1. Create or recover `feature/chat-mode-blocking-wall-guard` and its worktree.
2. Record source branch and HEAD.
3. Record production `master` HEAD and service state.
4. Inspect and record the current `job_status` input/output schema.
5. Inspect current `job_status_timing` fields.
6. Inspect current request/client/turn correlation behavior.
7. Run focused baseline suites covering:
   - `job_status` lifecycle;
   - job-manager telemetry;
   - request/tool logging;
   - HTTP correlation workflows;
   - config loading;
   - logstats job telemetry.
8. Create/update a Phase-2 checkpoint/evidence file with the baseline result.

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

### Proposed contract

Add to `JobsSettings` a mapping conceptually equivalent to:

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
- TOML loading and environment override compatibility where applicable.

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

### Recommended module

```text
src/binnacle/blocking_wall_guard.py
```

Do not embed the tracker state machine directly in `job_status.py`.

### Suggested abstractions

Keep them small and purpose-specific, for example:

```text
BlockingWallTracker
TurnState
BlockingDecision
BlockingLease
```

Exact class names may change if readability improves.

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

Initial inactive-record capacity: **4096**.

Inactive records use LRU eviction. Active records are never evicted.

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

Conceptually:

```text
read current client/turn
-> resolve configured budget
-> bound request by existing WAIT_MAX
-> tracker acquire/decision
-> wait using effective wait
-> release lease in finally
-> read/build normal job result
```

Carefully determine whether unknown-job validation should occur before or after
lease acquisition so invalid IDs cannot consume budget or strand leases. Preserve
existing externally visible error semantics.

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

Emit a window-close event when union accounting is committed.

### Tests

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

Prefer extending:

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

Use small budgets and short jobs to keep runtime bounded:

- job exits inside a positive wait;
- sequential waits consume cumulative budget;
- budget reaches exhaustion while job remains running;
- subsequent positive request becomes effectively non-blocking;
- job later completes and remains observable;
- already-exited job returns promptly;
- explicit zero wait remains non-blocking;
- nonmatching client is unchanged;
- missing-turn context is unchanged;
- invalid job ID does not corrupt tracker state.

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

- two simultaneous positive status waits in one turn;
- five simultaneous waits in one turn;
- partial overlap/refill;
- waits for different jobs under the same turn;
- different turns concurrently;
- one turn exhausting while another retains budget.

Confirm that overlapping waits share the same active-window deadline and charge
union time once.

### Reload semantics

Simulate/recreate tracker state while a durable job exists.

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
run should report measured p50/p90/p95/p99/max. A broad regression sanity limit
may be used if stable.

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
12. Commit and push the Phase-2 branch.

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

Use clear dated names, for example:

```text
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-2026-09-xx.md
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-2026-09-xx.json
```

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
procedure before implementation:

```text
1. Find the Binnacle worktrees and identify the Phase-2 branch/worktree.
2. Read docs/chat-mode-scheduling-v2-phase2-execution-plan.md.
3. Read docs/chat-mode-scheduling-v2-server-guard.md.
4. Read the Phase-1 Step 1.9 aggregate report.
5. Read any committed Phase-2 checkpoint/report.
6. Inspect git status and recent commits.
7. Determine exactly which numbered Phase-2 step is the next incomplete step.
8. Verify production master is clean and no experimental budget is enabled.
9. Execute only the requested step range, continuously until its defined stop point.
10. Report progress using the standard Phase-2 status format.
```

Do not ask the user to restate decisions already captured here unless repository
state contradicts the document or a genuinely new decision is required.

## 28. Current checkpoint at document creation

At the time this plan was written:

```text
Phase 1: 9 / 9 complete
Phase 2: 0 / 12 complete
Phase 2 implementation: NOT STARTED
Phase 2 branch/worktree: NOT YET CREATED
production deployment: NONE
Phase-1 checkpoint: cc1b014
next implementation step: 2.1
```

Writing and committing this planning document does **not** count as starting
Step 2.1.
