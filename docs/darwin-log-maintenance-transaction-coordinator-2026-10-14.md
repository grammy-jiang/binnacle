# Issue #30 — Out-of-band transaction coordinator, native actuator absent

Status: **default-off reusable control sequence**, proven only on isolated
Linux-owned fixtures. This is not an independently authenticated native Mac
maintenance controller, and it enables no installed service control or raw
log deletion.

## Integration milestone

The coordinator in binnacle.companions.darwin_log_transaction_controller
composes the **already merged** private J7 interlocks, Watchdog pause/ACK,
MCP request fence, Jobs Manager pause/zero-UNKNOWN witness,
durable transaction journal and actual checksum-verifying BZ2 finalizer.

Its only external effects pass through an explicitly supplied
TransactionExecutor protocol, which has **no default implementation,
launchd target, MCP tool, scheduled entrypoint, installer or CLI**.
The executor must eventually be a separate, privileged, independently
authenticated actor. Implementing the Python protocol is not itself an
authorization or cryptographic proof.

The controller requires an exact allowlisted producer generation
and raw source identity, unique nonce/controller generation, bounded
watchdog pause and the inherited finalizer's 100 GiB free-space guard
unless a disposable fixture explicitly overrides the threshold.

The ordered transaction:

1. Begin one private durable journal, then acquire both exact J7 locks.
2. Pause Watchdog and validate a nonce/PID-generation ACK.
3. Fence and drain MCP before obtaining a coherent Jobs start-pause,
   zero-running/zero-UNKNOWN receipt. An ordinary StepReceipt is
   insufficient to claim either quiet window.
4. Arm an **independent READY guardian before any writer stop**.
5. Stop only the pinned writer via the injected executor, confirm its
   stopped receipt, then require complete old-generation writable-FD
   closure evidence before the real finalizer may start.
6. Publish verified canonical BZ2, record canonical_verified **before**
   raw unlink, recheck hold/source/archive inode, unlink+fsync,
   then publish raw_pruned after the irreversible boundary.
7. Restore a new writer generation and **prove a freshly admitting MCP
   incarnation**; the old MCP gate stays permanently fenced and must
   never be unfenced in-place.
8. Disarm guardian after confirmed recovery; release Jobs/Watchdog/J7
   barriers and only then publish durable complete.

Every durable receipt remains *advisory*; the result's
production_authorized flag is structurally false.

## Unknown outcomes and crash rules

An unknown stop result **does not permit an in-process restart**.
The independent guardian retains responsibility because the original
writer could still be alive or could have stopped after its ACK was lost.
An acknowledged stop allows one in-process restore attempt under J7;
a failed/unknown restore ACK is **never retried** by this controller,
because a duplicate bootstrap could create two writers.

Successful writer restoration by itself does not complete the recovery:
a new HTTP/MCP admission generation must also be positively verified.
A failed MCP resume keeps the independent guardian and all relevant
maintenance barriers armed. If the restored-phase journal write later
fails after the new writer and MCP admission are already confirmed,
the in-process controller does not repeat either bootstrap.

A SIGKILL never runs Python finally. Existing Issue #30 full fixture
tests separately qualify an independent test guardian over the
controller's kernel-held journal lease, including the windows after
writer stop, after canonical validation, after raw unlink and after
writer restore. The coordinator does **not** install or implement the
equivalent privileged macOS recovery service.

## Evidence and limits

The new coordinator's Linux fixture integration tests use test-owned
writer subprocesses, private Jobs Manager and Watchdog records, real
J7 file locks, the real durable phase journal and the BZ2 finalizer.
They also inject wrong receipts, busy locks, a still-running Job or
MCP call, lost durable ACKs, unknown stop, restore failure and a
failure to reopen MCP admission. The production module must meet the
repository's Linux/Darwin mypy, architecture, module-size, CI and
90% branch-coverage gates.

**Not implemented here:** a root-owned installed launchd service
actuator, authenticated cross-UID controller-to-service transport,
plist/hash/KeepAlive pinning across bootout, full privileged native
lsof with positive control, independent power-loss/hung-controller
recovery, and macOS launchd fault-injection acceptance. The existing
read-only installed-writer preflight from PR #54 is only an input
prerequisite, never mutation authority.

Until a separate approved production actuator and native review exist,
this coordinator remains deliberately unusable from deployed service
startup. Do not deploy or operate it on real rotated Binnacle logs.
Automatic pruning remains OFF and [Issue #30](https://github.com/grammy-jiang/binnacle/issues/30)
remains OPEN.
