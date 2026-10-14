# Issue #30: full writer-coordinated maintenance transaction rehearsal

Status: **Linux/Raspberry Pi fixture proven; not a macOS production
controller**. No installed service, Mac workspace, real log archive,
active Jobs Manager or system launchd label is touched by this work.

## Objective

Validate the **entire** maintenance transaction, not merely a
collection of disconnected guards:

1. Verify one test-owned, private writer generation and its raw inode.
2. Record intent and acquire existing private J7 deployment/Jobs locks.
3. Request Watchdog maintenance pause and verify its nonce/PID ACK.
4. Fence MCP new calls and wait for existing accepted calls to drain.
5. Publish the private Jobs start barrier, obtain a transaction-coherent
   owner/PID/nonce ping, and demand zero running and UNKNOWN durable jobs.
6. Prepare an independent, READY recovery guardian **before** writer stop.
7. Stop a real, disposable writer subprocess and verify its old FD closed.
8. Publish and independently decompress/checksum a real .bz2 archive
   through the existing finalizer under the held producer-generation fence.
9. Persist the canonical-verified milestone **before raw unlink**.
10. Unlink/fsync only the disposable raw inode, persist the raw-pruned
    milestone, then start and verify a new independent active writer.
11. Release Jobs/Watchdog/J7 barriers and durably record completion.

The stored receipt digest is diagnostic evidence, **not authentication
or production authority**. The new writer uses a different active file
from the previous rotated raw generation.

## Why the data plane needed two milestone callbacks

Previously finalize_archive performed canonical publication, byte
verification and raw unlink in one operation with only a final result.
A controller that crashed after unlink but before recording success
could not tell whether the raw inode still existed.

The optional FinalizeMilestones interface adds a durable boundary
inside the existing authoritative WriterHold:

- canonical_verified is called after the finalizer verified the
  compressed canonical archive but **before** unlink. If it refuses,
  the raw inode remains intact, although an independently verified
  compressed file may coexist.
- After that callback returns, the finalizer **rechecks** the writer
  hold, source inode and canonical inode. It will refuse an uncooperative
  intervening write or renamed file.
- raw_pruned is called **only after** raw unlink and directory fsync.
  A failure or SIGKILL here does not imply rollback. The journal
  conservatively still shows canonical_verified and the independent
  guardian must recover the stopped writer.

The API is opt-in; existing callers retain their original behavior
and production cleanup remains disabled without the future control
plane.

## Real test-only participants

The full transaction rehearsal is deliberately placed under tests/,
not imported into Binnacle startup or an installed entrypoint. It
uses the already-reviewed J7Interlocks, WatchdogMaintenanceFence,
ToolAdmissionDrain, DarwinJobManager fixture maintenance ACK,
MaintenanceTransactionJournal and real finalize_archive implementation.

A separate **test writer subprocess** appends to exactly one mode-0600
file under an owned issue30-fixture-e2e-[32 lowercase hex digits] directory. The test
controller stops it using a private pipe, never by signaling any live
Binnacle job. Its replacement writer opens a new active filename.

An independent **Linux-only fixture guardian process** is READY before
writer stop. It waits for the controller's kernel-held transaction
lock to be released, checks the strict private journal through the
non-adopting observer, and may launch **only** a pinned test worker
when the original is no longer running. It does not delete files,
resume canonical publication, signal installed services, issue
launchctl/systemctl, or inherit the controller's journal write secret.

For a normal transaction, the journal completes and the guardian
records that no restoration was needed. For a controlled exception,
the controller's finally branch restores only the disposable writer;
its incomplete journal remains available for investigation. For an
actual **SIGKILL of the separate fixture controller**, finally is
not executed and the guardian independently restarts the test writer.

## Failure and crash acceptance

Cross-process tests kill the **controller process**, never a real
service, in three distinct windows:

| Crash point | Expected raw/canonical | Recovery expectation |
| --- | --- | --- |
| After writer stopped, before stopped receipt | Raw retained, canonical absent | Guardian restarts fixture worker; journal stays guardian_armed |
| After canonical verified, before raw unlink | Both retained, matching bytes | Guardian restarts fixture worker; journal stays canonical_verified |
| After raw unlink and fsync, before raw_pruned receipt | Raw absent, canonical valid | Guardian restores worker; no fabricated raw_pruned receipt |
| After new writer restored, before complete | Raw absent, canonical valid, active inode already present | Guardian rechecks the recorded active writer PID and restarts only when it has exited; no duplicate living writer |

Normal failure tests also cover missing Watchdog or MCP/Jobs quiet
window, every maintenance phase up to deletion, and errors before
service restoration. Every non-crash exit releases the fixture J7
locks and private pause requests, without converting incomplete
evidence into a successful transaction.

Tests must pass on Linux Python 3.10–3.14; two native-only tests are
registered in the strict platform skip table. The canonical archive
and raw source are always **test-created temporary files**.

## Unresolved production requirements

The fixture is **not** an authenticated macOS out-of-process
controller. It does not acquire real root-owned launchd identities,
stop or bootstrap any of the five Binnacle LaunchDaemons, or prove a
real privileged all-process FD census. The test guardian uses
Linux /proc and a synthetic private worker; it does not implement
production bounded hung-controller restoration, full KeepAlive
coordination, peer-authenticated live MCP/HTTP admission, or power
loss recovery.

Before enabling ANY production raw-log pruning, implement the
independent, authenticated native controller with pinned plist/PID/
generation and complete FD proof, followed by isolated native Mac
fault-injection acceptance and an explicit manual maintenance window.
Issue #30 stays OPEN; no production cleaner or launchd deployment
is introduced in this milestone.
