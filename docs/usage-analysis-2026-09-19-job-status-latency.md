# `job_status` latency anomaly — investigation, 2026-09-19

## Scope

This review addresses one anomalous blocking `job_status` call observed on
2026-09-15. It does not change the wait-not-kill contract or job execution model.
The objective is to determine whether there is a repeatable defect and, where the
historical record is insufficient, make the next occurrence diagnosable.

## The anomaly

Job `7e4c47386fbf` was a background `codex exec` launched at 11:13:46 and
completed successfully at 11:18:59 after about 313 s with no job log output. Three
consecutive blocking status calls targeted the same running job:

| call | requested wait | tool duration | `waited_s` | state |
| --- | ---: | ---: | ---: | --- |
| `ef98beb610b0` | 50 s | 50.021 s | 50.000 s | running |
| `0c85d7729e0f` | 50 s | 50.019 s | 50.000 s | running |
| `ba58bfc0c4ad` | 50 s | **163.891 s** | **50.429 s** | running |

The third call therefore contained about **113.462 s** not represented by the
old `waited_s` measurement. A later status after the job exited took 3.13 ms.

## Population evidence

Across the retained 14-day journal there are **921** `job_status` results carrying
`waited_s`. Define overhead as `tool_result.duration - waited_s`:

- median: ~12.9 ms;
- p90: ~23.0 ms;
- p95: ~36.9 ms;
- p99: ~66.7 ms;
- only 5 calls exceeded 100 ms;
- only **one** exceeded 500 ms: `ba58bfc0c4ad` at 113.462 s.

The next-largest overhead was only 125 ms. This is a single extreme outlier, not a
recurrent latency distribution or a general `job_status` performance problem.

## Local stage measurements

On the current Pi with about 317 processes, read-only microbenchmarks of the
relevant local stages were:

- `job_state`: p50 ~0.086 ms, p99 ~0.155 ms, max ~0.167 ms;
- `read_log` on the sampled job: p50 ~0.020 ms, p99 ~0.025 ms;
- `job_processes` `/proc` scan: p50 ~10.1 ms, p99 ~11.7 ms, max ~12.1 ms.

These figures match the normal historical overhead and give no evidence for a
persistent 100-second disk or `/proc` scan problem.

## Hypotheses checked

### System wall-clock adjustment

The old `_wait_for_exit` measured `waited_s` with `time.time()`, while its actual
timeout deadline and the middleware duration use monotonic clocks. A large wall
clock step could therefore have produced misleading numbers. However, comparing
journald `__REALTIME_TIMESTAMP` with `__MONOTONIC_TIMESTAMP` across 925 entries
from 11:14–11:20 showed a stable realtime-minus-monotonic offset and no ~113 s
clock discontinuity. A clock step is not supported by the retained evidence.

`waited_s` is nevertheless changed to `perf_counter()` because elapsed-duration
metrics should be monotonic by construction.

### FastMCP worker-thread dispatch

FastMCP 4.0.0b5 executes synchronous tools through
`anyio.to_thread.run_sync()`. AnyIO 4.14.2 reports a default worker limiter of 40
tokens. The middleware starts its duration timer before `call_next`; the sync tool
body starts only after worker dispatch. The old `waited_s` timer began inside the
tool body. Worker-queue delay can therefore create exactly the observed shape:
large tool duration with a normal internal wait.

The historical window does **not** prove saturation, however. No overlapping MCP
`tools/call` intervals were found during the anomalous call; the immediately
preceding `tools/list` completed in about 1.1 ms and HTTP traffic was sparse. Other
process-wide AnyIO worker consumers cannot be reconstructed from the existing
logs. Worker dispatch remains a plausible mechanism, not a confirmed root cause.

### Wi-Fi / uplink incident

The anomaly coincided with a substantial WLAN disturbance: elevated probe latency,
deauthentication/reassociation and the start of the failover episode later handled
by the watchdog. This is strong temporal correlation but `job_status`'s relevant
path is local disk, `/proc`, and sleeping on a monotonic deadline. No mechanism in
the current evidence establishes that the network event caused the 113-second
difference, so no causal claim is made.

## Decision

Do **not** redesign job scheduling, reduce the 50-second wait, change FastMCP
threading, or add speculative timeouts for a single unreproduced outlier. Instead:

1. make `waited_s` monotonic (`perf_counter`);
2. propagate the middleware call-start monotonic timestamp through a ContextVar
   (FastMCP/AnyIO already propagates the existing `current_call` this way);
3. emit an internal `job_status_timing` record for every single-job status call.

The event contains:

- `call`, `job_id`, `wait_requested_s`;
- `dispatch_ms`: middleware start to sync tool-body entry;
- `state_ms`: `job_state` / blocking `await_exit` stage;
- `read_log_ms`;
- `process_scan_ms`;
- `impl_ms`: complete `job_status_impl` time;
- final state, process count and log bytes.

It adds no MCP response fields and therefore no model-context/schema cost. Combined
with the existing correlated `tool_result.duration_ms`, a future anomaly can be
partitioned into pre-body dispatch, implementation stages, and residual FastMCP
post-body/serialization time.

## Validation

- focused timing tests pass on Python 3.10, 3.11, 3.12, 3.13 and 3.14 (4/4 per
  interpreter);
- complete jobs + logging suites: 79 passed with an isolated job spool;
- FastMCP in-memory test proves the middleware start timestamp crosses the worker
  thread and `dispatch_ms` is populated and call-correlated;
- final Python 3.13 full project suite: **559 passed**;
- project branch coverage: **88.33%** against the 86.9% gate;
- `job_status.py` branch coverage: **99.21%**.

## Production integration

The implementation was copied to the live server on 2026-09-19 after every
existing target file matched the research snapshot baseline byte-for-byte. A
rollback copy was created at
`/tmp/binnacle-before-job-status-timing-20260919T102607`. WatchFiles performed one
normal reload; the focused production timing tests passed 4/4. No MCP tool
signature or description changed, so no connector schema refresh was required.

Two real ChatGPT `openai-mcp` checkpoints validate the stage accounting:

1. A background `sleep 4` job was checked with `wait_seconds=50` while still
   running. Call `4afb6fe6a43c` waited until exit and logged
   `dispatch_ms=0.61`, `state_ms=2489.96`, `read_log_ms=0.04`,
   `process_scan_ms=0.00`, `impl_ms=2490.02`; the correlated `tool_result` was
   2491.03 ms and returned `waited_s=2.49`.
2. A background `sleep 6` job was checked immediately with `wait_seconds=0` while
   still running. Call `3a6e8a2fbb9c` logged `dispatch_ms=0.53`, `state_ms=0.33`,
   `read_log_ms=0.04`, `process_scan_ms=10.72`, `impl_ms=11.10`; the correlated
   `tool_result` was 12.01 ms and reported one live process.

The residual framework time in both live examples is about a millisecond. The
telemetry can therefore distinguish a future worker-dispatch delay from the
blocking wait, log I/O, `/proc` scan, and post-body framework overhead. This
closes the production gate without asserting an unsupported root cause for the
2026-09-15 outlier.
