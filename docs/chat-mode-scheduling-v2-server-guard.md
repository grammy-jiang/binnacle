# Chat mode scheduling v2 — server blocking-wall guard specification

Status: design specification; no production change.

Parent design: `docs/chat-mode-scheduling-v2-design.md`.
Evidence: `docs/chat-mode-scheduling-final-2026-09-23.md`.

This document specifies only the server-side catastrophe ceiling. It is not a
workflow scheduler and does not know whether independent work remains.

Execution SOP: `docs/chat-mode-scheduling-v2-phase2-execution-plan.md`.

## 1. Layer B — cumulative blocking-wall guard

The server guard is not a scheduler. It exists only to prevent the historical
failure mode where one ChatGPT turn accumulated hundreds or thousands of
seconds of repeated positive `job_status` requests.

### 1.1 Configuration

Proposed deployment setting:

```toml
[jobs.blocking_wall_budget_s_by_client]
"openai-mcp" = 300
```

Repository default remains empty, preserving all existing clients unless a
deployment opts in. The first implementation should validate configured total
budgets in the range 1..3600 seconds; this is separate from the existing
50-second per-call input bound.

The value is a **per-agent-turn union-of-blocking-wall-time budget**, not a
per-call cap and not a total turn lifetime.

The existing `job_status` schema limit of 50 seconds per call remains
unchanged.

### 1.2 Why 300 seconds is the first candidate

In the measured workload, for jobs still running at the first status check:

```text
residual p50  32.5 s
residual p75  74.1 s
residual p90 174.6 s

coverage by residual runtime:
  50 s -> about 65%
 120 s -> about 86%
 180 s -> about 89%
 300 s -> about 94%
```

Historical positive-wait requests per turn were much larger:

```text
p50  210 s
p75  500 s
p90 1000 s
max 2150 s
```

So 300 seconds is a useful experimental point: large enough to preserve most
legitimate dependency completion, but small enough to eliminate the
multi-hundred-to-multi-thousand-second pathological tail.

It is **not** a documented ChatGPT timeout and is not accepted as the production
value until A/B validation.

### 1.3 Union-of-active-waits accounting

Overlapping read-only waits must charge wall time once, not sum requested
durations.

Per `(client, base_turn)` keep process-local state:

```text
spent_s
active_count
active_window_started
active_window_deadline
last_seen
```

When the first positive wait in a new active window begins:

```text
remaining = budget - spent
active_window_started = now
active_window_deadline = now + remaining
effective_wait = min(requested_wait, 50, floor(remaining))
active_count = 1
```

When another positive wait overlaps that active window:

```text
remaining = active_window_deadline - now
effective_wait = min(requested_wait, 50, floor(remaining))
if effective_wait > 0:
    active_count += 1
```

Only an effective positive wait acquires a lease. A request reduced to zero by
the exhausted budget does not change `active_count`.

When a positive wait finishes:

```text
active_count -= 1
if active_count == 0:
    spent += min(now, active_window_deadline) - active_window_started
    close active window
```

Consequences:

- five overlapping 20-second waits cost about 20 seconds, not 100;
- a job that exits after 3 seconds consumes about 3 seconds, not its requested
  50 seconds;
- productive time between separate blocking windows is not charged;
- once less than one second remains, later positive waits become effectively
  non-blocking.

A monotonic clock is required. Accounting operations are protected by a
short-lived lock, but the lock is never held while waiting for a job. A
positive wait receives a lease from the tracker and releases it in a
`finally` path so cancellation, validation failure, or tool errors cannot
strand `active_count`.

### 1.4 Turn correlation

The OpenAI tunnel `X-Request-Id` is observed as:

```text
<base-turn>/<call>
```

The logging middleware already records it as `turn=`. The implementation should
publish the base-turn component through a `current_turn` ContextVar, as the
earlier polling prototype demonstrated.

If turn correlation is unavailable:

- keep the ordinary per-call 50-second schema bound;
- do not pretend a per-turn wall budget was enforced;
- log `blocking_policy=no_turn`;
- never create hidden cross-session state based on guesses.

### 1.5 Process lifetime

The guard is process-local and LRU-bounded.

A server reload may forget spent turn budget. That is acceptable for the first
version because:

- durable job state is not affected;
- the per-call 50-second bound still applies;
- turn-budget loss makes the safety guard less strict, never corrupts work;
- persisting ephemeral ChatGPT turn accounting would add complexity without
  evidence that it is needed.

The tracker is LRU-bounded to **4096 total turn records** in the first
implementation. Inactive records are eligible for LRU eviction; an active wait
window is never evicted. If all 4096 records are active, a new turn falls back
to the ordinary per-call 50-second bound and logs
`blocking_policy=capacity_untracked`; silently evicting an active lease would make wall
accounting incorrect.

If production evidence shows reloads frequently occur inside long active turns,
persistence can be reconsidered separately.

## 2. Layer C — telemetry

Every `job_status` call should expose enough telemetry to reconstruct the guard
decision. Most fields are log-only, but the model must be able to tell when the
server has exhausted the turn budget; otherwise it may loop on instant status
checks without knowing why the requested wait stopped blocking.

Proposed log fields:

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

For a positive wait request, structured tool output should additionally expose:

```text
wait_requested_s
wait_effective_s
blocking_budget_s
blocking_remaining_s
blocking_budget_exhausted
blocking_policy
```

When `blocking_budget_exhausted=true` and the job is still running, the
one-line summary must say that the turn's blocking budget is exhausted and that
further positive waits will be non-blocking. This is a policy fact, not an
error, and gives the model the signal required for the checkpoint fallback in
the Project instruction.

At the end of an active window, emit `event=blocking_window_closed` carrying:

```text
call
turn
client
blocking_budget_s
blocking_window_wall_s
blocking_spent_after_s
blocking_remaining_after_s
```

`binnacle stats` / logstats should aggregate at least:

- positive `job_status` calls;
- non-blocking status calls;
- actual blocking-wall union per turn;
- budget-exhausted calls;
- requested vs effective wait;
- turns that consumed 25%, 50%, 75%, 100% of budget;
- p50/p90/p95/max blocking wall per turn.

Read-only concurrency is derived from existing `tool_call` / `tool_result`
timestamps; no production state is needed.

## 3. Test requirements for the server guard

Unit tests:

- default no-policy behavior;
- prefix client matching;
- base-turn extraction;
- one positive wait finishing early charges actual time;
- sequential waits consume cumulative budget;
- overlapping waits charge union wall time;
- overlapping waits share one deadline;
- remaining budget below one second produces effective zero;
- budget exhaustion is visible in structured output and the one-line summary;
- new turn receives a new budget;
- nonmatching client is unchanged;
- missing turn uses `blocking_policy=no_turn`;
- LRU eviction is bounded, never evicts active leases, and has an explicit
  capacity-untracked fallback;
- monotonic clock is used;
- exceptions/failures release an active wait lease.

Integration tests:

- real running job + repeated waits;
- job exits during a positive wait;
- two concurrent status waits;
- five concurrent waits plus refill;
- MCP reload does not affect durable job state;
- telemetry fields match actual behavior.

Concurrency tests must avoid relying on wall-clock sleeps longer than necessary;
inject/fake the policy clock for deterministic unit coverage.
