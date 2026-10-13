# Issue #30: MCP tools/call admission and bounded drain prerequisite

Date: 2026-10-14. **Dormant state machine, not production integration.**

A quiet interval with no tool_call log messages is not a true admission
fence. Another request can arrive after that observation and before
the service is stopped for log rotation. The maintenance controller
must prohibit new MCP tool calls and wait for existing calls to finish
BEFORE safely closing the producer's old stdout/stderr descriptors.

## Implemented pure state machine

The separate tool_admission_drain module contains a reusable, thread-safe,
linearizable in-process counter and a dormant FastMCP middleware adapter.

- Each accepted tools/call receives exactly one opaque ticket, tied to
  an individual application-generation nonce and monotonically assigned
  sequence. In-flight calls are counted under a condition lock.
- A generation-bound one-time pause nonce closes new admission. Already
  accepted calls may finish normally; they are not cancelled or killed.
- A later tools/call raises an explicit, retryable-looking ToolError and
  never invokes its registered handler while this generation is fenced.
- wait_drained requires the exact pause nonce and a bounded finite
  timeout (0 to 120 seconds). A timeout returns a non-drained snapshot
  and **leaves admission closed**. The only safe reopening model for
  this state machine is creating a NEW application process generation.
- Error and BaseException/cancellation paths release the accepted
  ticket in finally. Double release, wrong generation, forged sequence
  and independent transaction nonce are refused.
- DrainSnapshot.shutdown_authorized is structurally false, including
  after the in-process count reaches zero: an in-memory count is NOT
  proof that other HTTP/RPC, Manager jobs, or other processes are idle.

The FastMCP middleware can intercept tools/call on a PRIVATE synthetic
application. It is **not registered by create_application** or any
existing Binnacle production entry point and exposes no management tool
or transport endpoint. Tests run actual synthetic FastMCP read_file
and run_command tool handlers, concurrent calls, late rejection,
cancellation and exceptions.

## Outstanding authority and integration

This is not the complete maintenance barrier:

1. The out-of-band controller must first acquire the exact J7 deploy
   and Jobs Manager service locks. The current J7 interlock module is
   in a separate Draft PR and is never automatically activated.
2. A separately authenticated and process-lifetime-bound mechanism
   must request admission closure and receive a durable generation +
   remaining-count acknowledgement. Remote MCP tool callers must NOT
   be able to arm or release this barrier.
3. The actual Jobs Manager must separately fence new start operations
   inside its existing transaction/launch critical section and verify
   the active/unknown durable job counts are zero. A ping alone is
   insufficient, and the existing provisioner stop marker expires.
4. A live Watchdog must be paused under its same restart mutex, with
   a verified nonce/PID/generation ACK; this is a separate default-off
   component in Draft PR #38.
5. All accepted MCP requests must finish *before* the out-of-band
   owner stops the actual launchd producer. If deadline expires,
   there must be no stop, no log deletion, and an explicit retained
   refusal state.
6. The writer lifecycle and FD-hold/recovery guardian must remain
   ready through canonical compressed verification, inode recheck,
   raw unlink and service bootstrap/readiness. Only then can a new
   application generation reopen admission.

## Testing boundary

No tests interact with the installed Mac launchd MCP, Jobs Manager,
Watchdog, live RPC socket or real archived logs. The admission gate
and synthetic FastMCP tests run on both Linux and Darwin and must
pass the repository's strict code quality and >=90% branch coverage
requirements. This module by itself cannot authorize Issue #30
production enablement; Issue #30 remains OPEN.
