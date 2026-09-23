# Chat mode scheduling v2 — Phase 2 progress

| Step | Status |
| --- | --- |
| 2.1 | COMPLETE |
| 2.2 | COMPLETE |
| 2.3 | COMPLETE |
| 2.4 | COMPLETE |
| 2.5 | COMPLETE |
| 2.6 | NOT STARTED |
| 2.7 | NOT STARTED |
| 2.8 | NOT STARTED |
| 2.9 | NOT STARTED |
| 2.10 | NOT STARTED |
| 2.11 | NOT STARTED |
| 2.12 | NOT STARTED |

Phase status: **IN PROGRESS**
Branch: `feature/chat-mode-blocking-wall-guard`
Worktree: `/home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard`
Source branch: `design/chat-mode-scheduling-v2`
Phase-1 evidence commit: `cc1b014`
Last completed step: **2.5**
Next step: **2.6**

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
