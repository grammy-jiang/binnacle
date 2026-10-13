# Issue #30: transaction-coherent Jobs Manager maintenance ACK

Status: **default OFF**, fixture and authenticated ping proof only. This
change is stacked on Draft PR #40, the dormant Jobs start fence. No installed
service, Binnacle Jobs process, active user Job or real log has been touched.

## Why this is required

An authenticated Manager ping that returns zero running jobs is not
evidence that a future log-maintenance controller has fenced new starts.
A writer might finish reading the counts before a concurrent Job start
crosses the Manager's launch critical section.

Draft PR #40 introduces a strictly read-only, nonce-and-owner-scoped
request.json check *inside* the durable jobs/.lock transaction, before
any new job can be reserved or spawned. The Manager must report the
fence state and actual counts in a snapshot observed UNDER THAT SAME lock.

## Implemented optional snapshot

The Manager has a second nullable maintenance_probe callback. Both
maintenance_fence and maintenance_probe remain None by default; no startup
code, deployment configuration, remote MCP tool or CLI installs them.

When a future trusted in-process integration explicitly binds:

- maintenance_fence to ManagerStartFence.refusal; and
- maintenance_probe to a closure invoking
  ManagerStartFence.synchronized_ping(manager, reply),

the already-authenticated ping RPC gains an additive
maintenance_admission mapping with state absent/paused/unknown and the
32-character lowercase nonce only when the reader genuinely observed a
valid paused state. It retains the existing owner_instance_id, PID,
revision, running_jobs and unknown_jobs fields.

The synchronized probe acquires manager._transaction (the *same*
durable jobs/.lock flock and process RLock used by job creation), reads
the request, validates the bound owner/PID and recomputes the active/
unknown counts while that lock remains held. Any earlier start must
finish its reservation and spawn before the controller can publish
its pause under the same lock; any later start must see that pause and
be refused. The probe overwrites potentially stale counts previously
read by the unmodified ping path.

This is only a *bounded-time observation*. It is NOT itself approval to
stop a producer. In particular even state=paused plus running_jobs=0
cannot justify removing raw logs if unknown_jobs is nonzero, if RPC
tools/call is still executing, Watchdog is not ACK-paused, or an
independent guardian is not armed.

## Tests and security boundary

Native Mac and Linux synthetic tests verify:

- Default-off ping fields are byte-compatible at the mapping level.
- Valid owner/PID/nonce pause state and counts are visible via existing
  authenticated Manager dispatch, and a following launch is refused.
- A Job started before pause remains counted (and is never killed).
- Deliberately stale initial counts are overwritten by a scan taken
  under the actual jobs/.lock; a second descriptor cannot acquire that
  lock during the scan.
- A ping arriving before the controller's lock-release waits until
  request publication, then returns paused. A forged owner or corrupt
  request never yields a positive nonce.
- Unsupported operations cannot release the pause, and removing a
  fixture request only affects a later observation (not a live process).

The Manager process-lifecycle and installed launchd server are not
changed. The new test file and module satisfy project quality,
size and coverage rules.

## Remaining for production

An independently authenticated out-of-band controller must acquire the
J7 deploy/Jobs locks, atomically publish this pause under the Manager
job transaction lock and validate a live authenticated ping from the
same known owner/PID/generation; it must also fence MCP/HTTP tools
admission, drain in-flight requests, wait for all Jobs and UNKNOWN
states to be zero, pause Watchdog under its action mutex, arm an
independent guardian, then prove the exact launchd writer and every
old-inode writable descriptor quiesced. None of these are granted by
this default-off ping extension.

Issue #30 remains OPEN. Production pruning is still DISABLED.
