# Chat mode scheduling v2 — Phase 2 progress

| Step | Status |
| --- | --- |
| 2.1 | COMPLETE |
| 2.2 | COMPLETE |
| 2.3 | COMPLETE |
| 2.4 | COMPLETE |
| 2.5 | COMPLETE |
| 2.6 | COMPLETE |
| 2.7 | COMPLETE |
| 2.8 | COMPLETE |
| 2.9 | COMPLETE |
| 2.10 | COMPLETE |
| 2.11 | COMPLETE |
| 2.12 | NOT STARTED |

Phase status: **IN PROGRESS**
Branch: `feature/chat-mode-blocking-wall-guard`
Worktree: `/home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard`
Source branch: `design/chat-mode-scheduling-v2`
Phase-1 evidence commit: `cc1b014`
Last completed step: **2.11**
Next step: **2.12**

## Step 2.1 baseline freeze

Step 2.1 local exit criteria are complete; the completion commit is ready for
push and the mandatory branch CI gate.

### Design source

- Source HEAD: `e9c04728e5ac583a8e5d3b991cb01309de36ef82`.
- The Phase-2 branch/worktree was created from synchronized
  `origin/design/chat-mode-scheduling-v2`.

### Production observation baseline

- Production HEAD: `83862b040f59afc97963041de557bf9037f13e50`.
- Production branch: `master`.
- Service: `ActiveState=active`, `SubState=running`.
- `blocking_wall_budget_s_by_client` is absent from production config.
- Section 11.9 checks use `bash /tmp/phase2-manager/isolation-check.sh`
  because Raspberry Pi MCP file reads are restricted to
  `/home/grammy-jiang/Projects` and `/tmp` and cannot directly read
  `~/.config/binnacle/config.toml`.
- Existing production dirt is unrelated watchdog work and must be preserved:

```text
 M CLAUDE.md
 M docs/watchdog-poc.md
 M src/binnacle/ops/watchdog/config.py
 M src/binnacle/ops/watchdog/cycle.py
 M src/binnacle/ops/watchdog/diagnostics.py
 M src/binnacle/ops/watchdog/inventory.py
 M src/binnacle/ops/watchdog/model.py
 M src/binnacle/ops/watchdog/network.py
 M src/binnacle/ops/watchdog/policy.py
 M src/binnacle/ops/watchdog/policy_recovery.py
 M src/binnacle/ops/watchdog/reporting.py
 M src/binnacle/watchdog.py
 M src/binnacle/watchdog_cli.py
 M src/binnacle/watchdog_config.py
 M tests/system/test_watchdog_devices.py
 M tests/watchdog_support.py
?? docs/watchdog-connectivity-and-best-path-plan-2026-09-23.md
?? src/binnacle/ops/watchdog/device_identity.py
?? src/binnacle/ops/watchdog/policy_usb.py
?? tests/system/test_watchdog_identity.py
?? tests/system/test_watchdog_usb_policy.py
```

### Frozen `job_status` contract

- Input `wait_seconds`: integer `0..50`.
- Current `job_status_timing` fields:
  `call, job_id, wait_requested_s, dispatch_ms, state_ms, read_log_ms, process_scan_ms, impl_ms, state, processes, log_bytes`.
- Baseline note: `job_status_impl` clamps `wait_seconds` before logging,
  so the current `wait_requested_s` field reflects the bounded value.
- Current `OUTPUT_SCHEMA`:

```json
{
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string"
    },
    "state": {
      "type": "string"
    },
    "exit_code": {
      "type": [
        "integer",
        "null"
      ]
    },
    "signal": {
      "type": [
        "integer",
        "null"
      ]
    },
    "runtime_s": {
      "type": "number"
    },
    "last_output_age_s": {
      "type": [
        "number",
        "null"
      ]
    },
    "quiet": {
      "type": "boolean"
    },
    "log_tail": {
      "type": "string"
    },
    "log_bytes": {
      "type": "integer"
    },
    "log_path": {
      "type": "string"
    },
    "command": {
      "type": "string"
    },
    "workdir": {
      "type": "string"
    },
    "waited_s": {
      "type": "number"
    },
    "processes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "pid": {
            "type": "integer"
          },
          "state": {
            "type": "string"
          },
          "etime_s": {
            "type": "number"
          },
          "cpu_s": {
            "type": "number"
          },
          "cmd": {
            "type": "string"
          }
        }
      }
    },
    "jobs": {
      "type": "array",
      "items": {
        "type": "object"
      }
    }
  }
}
```

### Frozen correlation behavior

`ToolLoggingMiddleware` logs the full `X-Request-Id` value as `turn=`.
There is no base-turn `current_turn` ContextVar in `callctx.py` at this
baseline.

### Validation

- Exact Step-2.1 baseline command: **PASS** — 78 tests passed in 45.88 s.
- `uv run pre-commit run --all-files`: **PASS**.
- Final Section 11.9 helper check at `2026-09-23T23:47:53+1000`:
  production remained on `master` at
  `83862b040f59afc97963041de557bf9037f13e50`, the service was
  `active`, and the Phase-2 budget key was absent.
- The unrelated watchdog production changes listed above were preserved
  untouched.
- No Phase-2 runtime behavior changed in Step 2.1.

### Step result

Step 2.1: **COMPLETE**
Next step: **2.2 — Configuration contract**

## Step 2.2 configuration contract

- Added empty-default per-client blocking-wall budgets with 1..3600 validation and non-blank prefixes.
- Longest-prefix lookup added.
- jobs tool_config budget fields added.
- Default remains disabled; job_status behavior unchanged.
- Tests: 19 passed; logging: 1 passed.
Step 2.2: **COMPLETE**
Next step: **2.3**

## Step 2.3 turn correlation ContextVar

- Added current_turn ContextVar with default None.
- Added conservative base/call parsing; absent or malformed request IDs publish no base turn.
- ToolLoggingMiddleware sets and resets base-turn context with the existing call context.
- Full X-Request-Id remains unchanged in the turn= log field.
- Covered sync-thread propagation, sequential isolation, concurrent distinct HTTP turns, and exception cleanup.
- Focused coverage: PASS - 6 passed, 23 deselected in 2.71 s.
- Exact Step-2.3 matrix: PASS - 30 passed in 5.58 s.
- No guard policy or job_status behavior was added.

Step 2.3: **COMPLETE**
Next step: **2.4 - Blocking-wall tracker, sequential core**

## Step 2.4 blocking-wall tracker, sequential core

- Added the standalone BlockingWallTracker with the frozen public classes/API.
- Uses an injected clock with production default time.monotonic and short threading.Lock bookkeeping.
- Sequential waits charge actual elapsed wall time; productive gaps are not charged.
- Remaining budget below one second yields exhausted with effective wait zero.
- No-policy and no-turn preserve the ordinary bounded wait; release is idempotent.
- New base turns get fresh budgets; tracked records keep the budget fixed for their process lifetime.
- Exact Step-2.4 unit command: PASS - 12 passed in 0.23 s.
- No job_status integration, overlapping-wait accounting, or LRU/capacity fallback behavior was added.

Step 2.4: **COMPLETE**
Next step: **2.5 - Overlapping-wait union accounting**

## Step 2.5 overlapping-wait union accounting

- Overlapping positive effective waits share one active window and the original deadline; later waits use live remaining time without extending the window.
- Live spent-before and remaining values include elapsed union wall time while a window is active.
- Non-final releases decrement active_count without committing the window; the final active release commits the capped union duration once.
- Zero-effective waits never increment active_count.
- Deterministic coverage includes two/five fully overlapping waits, partial overlap, early release, deadline exhaustion, reordered release, exception cleanup, cancellation-equivalent cleanup, and a real threaded acquire/release case.
- Exact Step-2.5 unit command: PASS - 20 passed in 0.29s.
- No job-status integration, LRU eviction, or capacity fallback behavior was added.

Step 2.5: **COMPLETE**
Next step: **2.6 - LRU bound, eviction, and fallback policies**

## Step 2.6 LRU bound, eviction, and fallback policies

- Enforced the configured tracker capacity as a total tracked-turn-record bound (4096 by default).
- New records evict the least-recently-used inactive record; active records are never evicted.
- When all capacity is active, new turns return `capacity_untracked`, keep ordinary bounded-wait behavior, and do not mutate another turn's accounting.
- `last_seen` is refreshed on tracked acquire/release activity, so recently used inactive records are retained deterministically.
- A turn that initially falls back can be tracked after an active record becomes inactive and eligible for eviction.
- Exact Step-2.6 unit command: PASS - 24 passed.
- No `job_status` integration was added.

Step 2.6: **COMPLETE**
Next step: **2.7 - Integrate the guard into `job_status`**

## Step 2.7 integrate the guard into `job_status`

- Added the process-local `BlockingWallTracker` singleton to `job_status`.
- Positive specific-job calls now validate job existence before resolving policy or acquiring a lease.
- Matching client+turn calls use the guard's effective wait; `no_policy`, `no_turn`, and `capacity_untracked` preserve the ordinary bounded wait.
- Zero-wait and no-id listing paths do not acquire guard state.
- Exhausted turn budgets make later positive waits non-blocking while leaving durable jobs running.
- Leases release in `finally`, including when the underlying wait raises.
- Exact Step-2.7 matrix: PASS - 69 passed in 38.28 s.
- Structured policy output, exhausted-summary wording, and detailed guard telemetry remain deferred to Step 2.8.

Step 2.7: **COMPLETE**
Next step: **2.8 - Structured output, summaries, and detailed telemetry**

## Step 2.8 structured output, summaries, and detailed telemetry

- Positive specific-job `job_status` results expose `wait_requested_s`,
  `wait_effective_s`, `blocking_budget_s`, `blocking_remaining_s`,
  `blocking_budget_exhausted`, and `blocking_policy`; zero-wait and
  listing payloads keep their prior shape.
- `job_status_timing` records requested/bounded/effective/actual waits and
  budget/spent/remaining/active/policy/exhaustion/turn/client fields.
- Final tracked releases emit `blocking_window_closed` from the same
  `finally` path that releases the lease, including exception cleanup.
- Still-running jobs with exhausted turn budget state explicitly that
  further positive waits in the turn will be non-blocking; durable jobs are
  not stopped.
- `ToolLoggingMiddleware.RESULT_KEYS` lifts the six model-visible policy
  fields; logging and run-command docs reflect the additive contract.
- Removed the obsolete wait-once wording from `run_command` output,
  `job_status` description, and Section 4 of `docs/tools/run_command.md`.
- Exact Step-2.8 matrix: PASS - 77 passed in 40.33 s.
- Repository defaults remain policy-disabled and production was not modified.

Step 2.8: **COMPLETE**
Next step: **2.9 - `binnacle stats` guard aggregation**

## Step 2.9 `binnacle stats` guard aggregation

- Extended the existing job telemetry model/analyzer with Phase-2 guard policy
  counts, positive/non-blocking/exhausted call counts, and requested/effective
  wait distributions.
- `blocking_window_closed` records aggregate by `(client, turn)` using the
  maximum cumulative `blocking_spent_after_s`, so multiple windows in one turn
  contribute one final cumulative blocking-wall value.
- Added tracked-turn p50/p90/p95/max blocking-wall statistics and >=25%,
  >=50%, >=75%, and effectively-100% utilization crossings; effectively-100%
  follows the frozen `remaining < 1 second OR exhausted call observed` rule.
- Added the `job_status blocking-wall guard:` human-readable section with the
  frozen labels and preserved historical journals without Phase-2 fields: they
  parse/render without synthetic guard values.
- Exact Step-2.9 matrix: PASS - 19 passed in 0.28 s.

Step 2.9: **COMPLETE**
Next step: **2.10 - Real-job integration suite**

## Step 2.10 real-job integration suite

- Added real short-background-job coverage for early exit, sequential exhaustion, post-exhaustion durability, already-exited jobs, explicit zero wait, no-policy, no-turn, and invalid job IDs.
- Real tracked waits verify actual wall charge, remaining budget, summary text, telemetry, durable job survival, and explicit cleanup with broad timing tolerances.
- Added an authenticated HTTP positive-wait workflow using X-Request-Id=turn-http-210/call-status and client phase2-http; the tracked result and job_status_timing line prove the base-turn and client ContextVars reach synchronous job_status.
- Guard exhaustion leaves the durable job running and listed until the test explicitly stops it.
- Focused guard suite: PASS - 11 passed in 4.35 s.
- Focused HTTP/context proof: PASS - 1 passed, 6 deselected in 4.46 s.
- Exact Step-2.10 matrix: PASS - 55 passed in 46.60 s.

Step 2.10: **COMPLETE**
Next step: **2.11 - Concurrency, reload semantics, and guard overhead**

## Step 2.11 concurrency, reload semantics, and guard overhead

- Added synchronized real-job concurrency coverage for two simultaneous 2-second waits, five simultaneous 1-second waits, an overlapping second wave, different jobs under one turn, independent concurrent turns, and independent exhaustion state.
- Replaced job_status.blocking_wall_tracker with a fresh BlockingWallTracker while a durable sleep fixture remained running; the job stayed observable and stoppable, confirming that reload loses only ephemeral guard state.
- Focused concurrency/reload suite: PASS - 7 passed in 17.41 s.
- Added scripts/benchmark_blocking_wall_guard.py and the required dated JSON and Markdown performance evidence.
- Three independent 100,000-iteration Pi runs measured median run-level p95 = 0.006445 ms and p99 = 0.007259 ms, passing the <1 ms / <2 ms design targets without adding a normal CI wall-clock gate.
- No production runtime source changes were needed; no race or active-lease leak was observed.
- Exact Step-2.11 matrix: PASS - 42 passed in 20.34 s.

- Initial pushed ci.yml run 35903817678 failed the Python 3.13 coverage-policy job because src/binnacle/jobs.py full coverage was 89.78%, below the required 90.00%.
- Added an idempotent second-stop assertion to the reload-semantics integration test, exercising the already-exited embedded stop path without changing production code, coverage policy, or exclusions.
- Exact CI-equivalent coverage policy after the fix: PASS - 1114 passed, 3 skipped; src/binnacle/jobs.py full coverage 90.67% (target 90.00%); 0 policy errors.
- Follow-up exact Step-2.11 matrix after the coverage fix: PASS - 42 passed in 20.30 s.

- Follow-up ci.yml run 35909011954 for commit 8d20def3093fe9421bbb259f9bb9cca32088a052: PASS.

Step 2.11: **COMPLETE**
Next step: **2.12 - Final Phase-2 validation and handoff**
