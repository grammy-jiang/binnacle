# Issue #30: dormant transaction-scoped Jobs Manager start fence

Status: **not enabled**, not a maintenance controller. Designed and tested
on 2026-10-14 as a prerequisite to production writer-coordinated log
finalization. Existing production Jobs Manager configuration and launchd
service remain unchanged.

## Problem

A successful authenticated ping reporting zero active Jobs cannot alone
prove that another start is unable to enter after the ping and before the
out-of-band controller stops its writer. The Linux and macOS Jobs Manager
may accept new authenticated jobs at any time. A future maintenance
controller needs a durable stop admission barrier aligned to the
Manager's actual job creation critical section.

The current native Darwin Manager already serializes a job-start
transaction under its in-process lock and exclusive durable jobs/.lock
flock. The manager's existing D2 stop marker is checked inside that
transaction but is a short-lived deployment-specific protocol and may
be consumed or expire. It is **not** a general-purpose log-maintenance
lease.

## Implemented default-off scope

The new Darwin Manager has a **nonconfigured** optional
maintenance_fence callable initialized to None. Existing service startup
does not set it, so the deployed Manager and normal production callers
have unchanged behavior.

An explicitly injected, independently trusted ManagerStartFence may
be attached in a fixture or future reviewed integration. Its refusal()
check executes *inside the existing jobs/.lock transaction* and **before
the job history prune, durable reservation or process spawn**. A valid
pause refuses new start requests with a typed maintenance_paused
response. A malformed, expired, foreign, symlinked, hardlinked, unsafe
or undecidable request returns maintenance_state_unknown and refuses
new start operations as well. No existing Job is stopped or signaled.

The reader opens a pinned user-owned 0700 private maintenance directory
with NOFOLLOW, then a single 0600 regular request.json. Its identity
and bounded JSON are checked against the originally opened FD. The
request binds a fresh 32-character lowercase nonce, the exact active
Manager owner instance ID and PID, jobs scope, and a bounded deadline.
Unknown or mismatched state is never treated as absent. The reader
cannot be constructed with a PID from another process incarnation.

The request file is **read-only to the Manager**. There is no new
unauthenticated maintenance RPC, CLI, scheduler or service manifest
configuration. Tests use a separate isolated Jobs directory, a fake
process owner that never spawns a real job, and a private fixture
maintenance root.

## Coordination rule and tested races

Any future controller publishing request.json must hold the **same
jobs/.lock flock as the Manager start transaction**, and publish an
atomically replaced private request while owning that lock. Once a
start has crossed its fence check, a controller cannot obtain the lock
until that transaction has finished reserving and spawning the Job.
Conversely, a controller that publishes first guarantees later
starts are refused. Tests prove the ordering with both threads and
a separate Python process actually competing on the exact flock.

The existing deployed Manager does not have an approved controller to
publish this request or give a durable admission acknowledgement.
The test verifies that the reader refuses missing, corrupt, changed,
foreign and expired maintenance records without mutating Jobs, and
that **default-off mode preserves previous launch behavior**. It
also keeps all preexisting D2 stop marker tests passing.

## Remaining production requirements

1. Independently acquired J7 deployment and Jobs service locks under
   a reviewed lock order. PR #36 provides a dormant library prototype.
2. Separately authenticated owner/generation-bound controller able to
   arm this reader before stopping MCP or Jobs, and to obtain a
   transaction-atomic *admission acknowledged* reply; no user-facing
   remote MCP tool may directly invoke this capability.
3. Controller request publication and ACK must be bounded and durable,
   with cross-process recovery after SIGKILL, power loss and Manager
   incarnation change. The request deadline must not silently reopen
   a retired producer or permit raw-source pruning.
4. Cross-service in-flight MCP/HTTP request drain, active/UNKNOWN
   durable Jobs zero, Watchdog pause and PID incarnation ACK, and
   launchd writer FD-generation proof before any real producer stop.
5. Recovery guardian reboots/restores the exact service, validates
   readiness and explicitly reopens a new application generation.
   A timeout or missing proof must refuse real log deletion.

This PR does not deliver those remaining gates. It must NOT be
installed as permission to archive or delete any production raw log.
Issue #30 remains OPEN.
