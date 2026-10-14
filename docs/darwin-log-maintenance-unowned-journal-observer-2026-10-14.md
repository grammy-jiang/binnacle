# Issue #30 — Existing-journal recovery observer

Date: 2026-10-14. Status: **dormant, inspection-only, not production
restoration or pruning**.

## Why this is a separate component

The out-of-process maintenance controller introduced in Draft PR #44
needs a durable way to tell a future recovery guardian which step may
have been reached before SIGKILL or restart. PR #44's journal writer
owns its own private exclusive flock and ephemeral write key; a fresh
controller cannot simply recreate that key.

It is not sufficient to open the normal writer context to investigate
an orphan: that context intentionally permits creation of a missing
transaction.lock, which might be confused with evidence that the
previous owner really stopped.

This package adds inspect_unowned_transaction(root) as a **separate**
read-only operational path.

## Observation and refusal contract

The observer accepts only an absolute, canonical, pre-existing
user-owned transaction directory named txn-<32 lowercase hex nonce>.
It refuses root/setuid execution, symlinked/public/foreign directories,
and missing or unsafe transaction.lock. It opens the existing
0600 single-link lock without O_CREAT, validates its FD/path identity,
and attempts a nonblocking exclusive flock.

If the old controller still holds that flock, the observer refuses
immediately, without waiting, killing or forcing a lease break. While
the observation's flock is held, it reads the existing
transaction.json through the same strict JSON, checksum, schema,
record/root nonce, inode/ownership/mode and receipt chain validation
introduced by PR #44.

The observer opens the existing lock file with O_RDWR for portable
Darwin/Linux exclusive flock support but makes **no writes**. It does
not open any lock/record with O_CREAT, rename, unlink, fsync, truncate,
bootstrap a service, or modify the existing journal. It promptly
closes the observation descriptors, without using flock LOCK_UN that
might unlock a fork-inherited file description.

A missing record is a separate UNKNOWN condition, not a successful
cleanup. The result is only a JournalSnapshot that includes conservative
needs_external_recovery and producer_may_be_stopped evidence; it has
production_authorized permanently false.

## Native and cross-platform qualification

The private temporary-directory test suite covers a controller still
holding the flock, a valid completed snapshot, a partially completed
guardian_armed snapshot, actual SIGKILL of an isolated child controller,
corrupt journal and valid foreign nonce, missing lock/record, public
and symlinked/hardlinked lock files, root/UID refusals, root/lock inode
swaps during acquisition, and repeated observation with unchanged
file size, SHA-256, inode and modification timestamp.

No live Mac, Binnacle Jobs Manager, Watchdog, launchd service, RPC
socket or raw archived log is accessed by these tests.

## Remaining production blockers

Successful observation of a crashed transaction is NOT proof of a
safe producer restoration. A separately authenticated guardian must
positively verify actual launchd producer generation, current
watchdog/KeepAlive controls, owner and guardian epochs, and writable
FD closure under the held J7/maintenance locks before applying any
target-specific recovery plan.

The run-time authentication protocol, native Mac service lifecycle and
power-loss acceptance tests remain for a subsequent reviewed work
package. No production scheduler, destructive CLI, privileged FD scan,
actual service interruption, archive publication or log pruning is
enabled by this change. Keep Issue #30 OPEN.
