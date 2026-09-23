# Phase 2 blocking-wall guard — final evidence

Date: 2026-09-24 (Australia/Sydney)

Status: **PHASE 2 COMPLETE**
Phase 3: **NOT STARTED**
Production deployment: **NONE**

This report freezes the Phase-2 cumulative blocking-wall guard as a
non-production implementation result. It does not select or enable a production
budget.

## Final answers

- **Default behavior unchanged:** yes for execution semantics. The repository
  default budget map is empty, so unmatched/default clients retain the ordinary
  per-call behavior. Original positive job_status waits intentionally gain six
  additive policy fields; zero-wait and listing payloads retain their prior
  shape.
- **Prefix configuration correct:** yes. Prefixes must be nonblank, budgets are
  constrained to 1..3600 seconds, and the longest matching client prefix wins.
- **Base-turn correlation reliable and conservative:** yes. Only a nonempty
  base/call request ID publishes the base turn; malformed/missing IDs yield no
  guessed turn state. Context resets are covered across success, error,
  sequential, concurrent, and authenticated HTTP paths.
- **Sequential accounting charges actual wall time:** yes. Early exits charge
  measured monotonic wall time, sequential windows accumulate, and productive
  gaps are free.
- **Overlapping waits charge wall-time union:** yes. Two/five-way overlap,
  refill waves, and different jobs under one turn reuse the original deadline
  and charge the active-window union once.
- **Can an exception strand a lease:** no known path. Release occurs in finally;
  exception and cancellation-equivalent coverage leaves tracker state
  consistent.
- **Memory bounded / active records protected:** yes. The default capacity is
  4096 total records; only inactive records are LRU-evictable. All-active
  pressure produces explicit capacity_untracked fail-open behavior.
- **Exhaustion model-visible:** yes. Structured output exposes policy, budget,
  remaining budget and exhaustion; the running-job summary states that later
  positive waits in the turn will be nonblocking.
- **Logs/stats reconstruct policy decisions:** yes. Timing logs expose
  requested/bounded/effective/actual wait plus tracker state, window-close logs
  expose cumulative union wall, and binnacle stats reports policies,
  distributions, utilization buckets, and per-turn p50/p90/p95/max.
- **Durable jobs survive exhaustion and tracker reload:** yes. The guard never
  stops a job; reload resets only ephemeral guard state.
- **Measured overhead:** three independent 100000-iteration Pi runs produced
  median run-level p95 **0.006445 ms** and p99 **0.007259 ms**, passing the
  <1 ms / <2 ms design targets.
- **Ready for Phase 3 offline replay:** yes after the final closeout reruns
  below remain green. Phase 3 itself has not started.

## Schema review

job_status.wait_seconds remains an integer in **0..50**.

Only original positive-wait results gain these intended structured fields:

    wait_requested_s
    wait_effective_s
    blocking_budget_s
    blocking_remaining_s
    blocking_budget_exhausted
    blocking_policy

Zero-wait and recent-job listing payloads retain their prior shape.

## Validation evidence

- Focused Phase-2 matrix: **PASS — 158 passed in 64.12 s**.
- Full repository pytest before evidence write:
  **PASS — 1115 passed, 3 skipped in 122.07 s**.
- Pre-commit before evidence write: **PASS — every hook passed**, including
  Ruff, mypy, Bandit, deptry, module-size, AI-readability, and architecture.
- Architecture: **97 modules checked; 0 forbidden reverse dependencies**.
- Module-size ratchet: **226 modules; 11 warnings; 0 errors**.
- Tracker isolation: integration/concurrency fixtures install per-test tracker
  instances with monkeypatch and clean durable-job fixtures; focused and full
  suites show no cross-test guard-state leak.

### Readability review

The repository's AI-readability check is advisory/warning-only. Phase-2-touched
long functions are:

| Function | Current | Baseline | Advisory level |
| --- | ---: | ---: | --- |
| job_status_impl | 194 lines | 89 lines | severe warning |
| analyze_job_telemetry | 134 lines | 86 lines | strong warning |
| BlockingWallTracker.acquire | 104 lines | new | warning |

The blocking module-size and architecture policies have zero errors. Step 2.12
does not introduce a behavioral refactor solely to silence advisory readability
warnings; this is retained as explicit technical-debt evidence rather than
hidden.

## Production isolation

Initial Step-2.12 isolation check at 2026-09-24T05:36:49+10:00:

- production checkout: master;
- production HEAD: 83862b040f59afc97963041de557bf9037f13e50;
- binnacle-mcp.service: active;
- production blocking_wall_budget_s_by_client: absent;
- unrelated watchdog tracked/untracked work: preserved untouched.

A final isolation check is required again immediately before commit.

## Closeout state

- Post-write full repository pytest:
  **PASS — 1115 passed, 3 skipped in 123.07 s**.
- Post-write whitespace/diff validation: **PASS**.
- Production isolation at 2026-09-24T05:46:55+10:00: **PASS**. Production
  remains master at 83862b040f59afc97963041de557bf9037f13e50, the service is
  active, the budget key is absent, and unrelated watchdog work is unchanged.
- The first post-write pre-commit pass changed only the missing final newline in
  phase2-progress.md; all substantive hooks passed. The clean pre-commit rerun then
  **PASSED every hook**.

    PHASE 2 COMPLETE
    PHASE 3 NOT STARTED
    production unchanged

## Post-completion review closeout — 2.12a

The independent Phase-2 review found one observability-only gap: a positive
`job_status` wait exception released the active lease and emitted the
`blocking_window_closed` union-accounting event, but it skipped the frozen
`job_status_timing` decision record because the exception propagated before the
normal end-of-function logger.

This is now fixed. The exception path emits the same guard decision telemetry
before re-raising, with `state=error` and `na` for read-log/process-scan stages
that were not reached. Guard semantics, durable-job behavior, policy selection,
and normal successful output are unchanged.

Closeout validation:

- focused telemetry/logging matrix: **36 passed in 6.28 s**;
- full repository pytest: **1115 passed, 3 skipped in 123.66 s**;
- module-size: **227 modules checked; 12 warnings; 0 errors**;
- pre-commit before evidence update: **PASS**;
- pre-commit after evidence update: **PASS**.

The regression test was moved into a dedicated small error-path test module so
no file exceeds the repository's 500-line hard gate.

With this closeout patch, the previously reported exception-path telemetry gap
is resolved. Phase 2 remains complete and ready for Phase 3 offline replay, but
Phase 3 has not started and production remains undeployed.
