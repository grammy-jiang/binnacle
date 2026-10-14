# Issue #30 — Crash-durable maintenance transaction journal

Status: **dormant, evidence-only library**, developed on an isolated sextant
Raspberry Pi worktree without touching MacBook Pro, any installed service or
a real raw log. This does not complete Issue #30.

## Goal and authority boundary

Previous merged PRs #32 and #34–#42 provided dormant checksum-verified
archive data handling, J7 interlocks, Watchdog and MCP/Jobs admission
prerequisites and isolated recovery/IPC fixture tests.

A separately controlled production log finalizer must record which
maintenance step was last durably committed. If its process is SIGKILLed
after unloading a launchd log writer, a new process must see that recovery
is required instead of treating an incomplete write as success.

The new module, binnacle.platform.darwin.log_maintenance_transaction,
implements only the durable *evidence journal*. It never invokes
launchctl, Jobs/MCP RPC, newsyslog, kill, compression or log unlink.
A complete journal is NOT authority to delete a raw log:
the production_authorized field is structurally and permanently false.

Receipt SHA-256 fields are opaque until checked separately against
a real authenticated producer, controller and recovery guardian.
The record checksum detects accidental corruption or torn writes;
it does not authenticate a hostile same-UID process.

## Private root and durable publication

One transaction uses an independently pre-created private 0700,
user-owned, absolute and canonical directory named
txn-<32 lowercase hexadecimal nonce>. It is never created or deleted
automatically by this library.

Under an exclusive nonblocking flock of a persistent 0600
transaction.lock, the journal writes one canonical transaction.json.
The record pins a fresh controller generation, owner PID, a digest of
an ephemeral, process-memory-only 256-bit write secret, exact allowlisted
service, producer PID and generation, source dev/inode, phase, revision,
receipt-digest chain and record checksum.

Reads are strictly NOFOLLOW and reject foreign owner, public mode,
multiple links, oversized/short files, pathname inode replacement,
duplicate JSON keys, malformed schemas and inconsistent sequence or
digest evidence. A missing existing journal is not proof that maintenance
finished; it is a distinct, uninitialized state.

Every write exclusively creates a fresh random 0600 sibling temp,
retries partial writes, fsyncs the file, publishes the first record with
a no-overwrite hard link (later steps use atomic rename), and fsyncs the
parent directory. Cleanup unlinks only a temp that still points to the
same inode actually opened by this attempt. A collision or replaced
path never authorizes deleting another file.

A disk-synced atomic rename may have committed even when its success
reply was lost. The controller must reread its revision and only retry
the SAME step with an identical receipt; no skip or divergent replay
is permitted.

## Monotonic maintenance states

| Revision | Phase | Independent external proof, not supplied by journal |
| --- | --- | --- |
| 0 | intent | Exact controller, producer generation and raw source inode |
| 1 | j7_locked | Both J7 interlocks held |
| 2 | watchdog_acked | Same nonce and Watchdog launchd generation |
| 3 | mcp_drained | New MCP/HTTP calls denied, accepted calls finished |
| 4 | jobs_drained | Authenticated Jobs pause ACK; zero running/unknown |
| 5 | guardian_armed | Independent restoration agent ready before bootout |
| 6 | producer_stopped | Exact launchd writer unloaded and KeepAlive fenced |
| 7 | writer_fds_closed | Complete privileged writable-FD census of old inode |
| 8 | canonical_verified | Compressed data and canonical inode verified |
| 9 | raw_pruned | Guarded unlink and directory fsync completed |
| 10 | producer_restored | Fresh launchd generation healthy and reopened |
| 11 | complete | Barriers released and guardian safely disarmed |

Phase order is strict. Each milestone requires a pinned expected revision
and an externally derived receipt digest; this module cannot assert that
a digest is authoritative, and therefore never grants permissions.

The controller's ephemeral write secret is never serialized and is
cleared on context exit. After SIGKILL, another process can acquire
the released kernel lock to INSPECT the state but cannot adopt the
old owner, even if the OS reuses its PID. Unfinished phases indicate
external recovery is required, and phase producer_stopped or later
additionally warns the producer may still be stopped **from the
guardian_armed phase onward**: the actual bootout can succeed and the
controller can crash before the producer_stopped journal receipt has
been written. Treat that uncertainty as requiring independent guardian
recovery, never as permission to assume the producer remained active.
The reader additionally binds the on-disk transaction nonce to the
pre-created directory name, rejecting a valid but foreign journal swap.

## Validation and remaining work

Unit and process tests run entirely in temporary directories on sextant,
with no Mac development interruption. They exercise all 12 phases,
real interprocess flock competition, SIGKILL of a test subprocess,
no takeover after crash, corrupted journal checksums/JSON,
symlink/hardlink/public files, replaced path inodes, UUID collisions,
short/zero writes, fsync/link/rename errors and idempotent replay of
a committed transaction after a lost acknowledgement.

To enable a true production finalizer, a separate independent,
authenticated controller must prove J7 locks, live MCP/Jobs admission
and drain, Watchdog ACK and incarnation, independent crash guardian,
launchd writer generation and complete old-inode FD quiescence.
Only after a controlled native dry-run and independent safety review
could any real log deletion be considered. Production cleanup stays OFF.
