# Issue #30 — writer-coordinated macOS raw-log finalization

Date: 2026-10-13. Follow-up to
[non-destructive log rotation](darwin-non-destructive-log-rotation-2026-10-13.md)
and [the verified pending snapshot tool](darwin-log-archive-staging-2026-10-13.md).

## Current deliverable — testable core, production finalization disabled

`darwin_log_archive_finalize.py` supplies an **injectable finalization data
plane**. This is deliberately not an enabled service, scheduled job, command
line entry point, launchctl/privilege helper, or a license to prune live files.

**There is no authoritative production WriterHold implementation. No Binnacle
producer currently supports the required lifetime handshake. Accordingly no
production log is eligible for deletion with this release.** A caller creating
its own `WriterHold` object is not proof the real launchd writer has stopped.
The type contract is for testing and future controlled integration, not an
independent security boundary.

### Exact finalization transaction

1. Accept only an allowlisted `*.log.N` raw archive in the user-owned
   0700 log directory; require an owner-held 0600 regular single-link source
   within configured byte limits; refuse unknown service-to-writer mappings.
2. Enter the **authoritative producer-supplied WriterHold** and retain it
   until source removal and directory fsync. The hold must prevent *all* writes
   to the archive's existing inode, and all reopens of the old path or inode,
   for its entire duration. A single `lsof`, `ps`, SIG{HUP,TERM} without
   a handshake, or launchctl job-label string is not sufficient.
3. Recheck writer generation and source dev/inode/link/mode/size/timestamps.
   Enforce at least 100 GiB free capacity plus source bytes.
4. Hash the *raw source*, compress through exclusive 0600 sibling temporary,
   independently decompress and SHA-256 verify the snapshot, rehash the held
   source and verify its metadata again.
5. Publish `.log.N.bz2` with no-overwrite atomic `linkat` and directory
   fsync. Only while the same producer hold remains active and all identity
   checks still match may it unlink the raw source and fsync the directory.
   Failure before that leaves the raw inode, which is always authoritative.
6. If publication completed but removal was interrupted, a future held
   transaction may verify the exact same canonical archive, SHA and size,
   then finish pruning. A differing canonical archive refuses unconditionally.
7. Statistics read one copy during the dual-file interval: raw `.log.N`
   takes precedence while present (including any late writes); verified
   `.log.N.bz2` takes over once raw is gone. Existing `.bz2.pending`
   snapshots stay excluded. No hidden file is ever silently consumed twice.

### Mandatory coordination implementation before production use

The future producer control needs (a) a cryptographically or OS-authenticated
generation-scoped identity, not a user-provided string; (b) a maintenance
request acknowledged by the actual daemon/launchd file-descriptor owner;
(c) proof every original stdout/stderr writer FD, including inherited children,
is closed; (d) a continuing lock that prevents reopen/restart until release;
(e) safe rollback/unlock and liveness on timeout, crash and session teardown;
(f) coordination across watchdog/launchd KeepAlive and concurrent upgrade;
(g) no active or unknown development jobs when a service interruption is
necessary; (h) disk-reserve tests and one-by-one host restart acceptance.

Until those invariants exist and are validated against an **isolated
launchd test fixture**, finalization remains a dormant library capability.
In particular, installing this code does not authorize reconfiguration,
rotation, compression, deletion or service restart on the Mac.

### Synthetic regression and fault evidence

- Original and no-follow path, hardlink, ownership and mode refusal.
- Writer running or unknown, hold revoked between publication and unlink,
  uncooperative append during compression, symlink/inode replacement.
- Corrupt/conflicting archive, unsafe canonical permissions, write failure,
  source length drift and insufficient disk reserve.
- Interrupted publish/unlink recovery, pending snapshot not ingested, exactly
  one logstats generation throughout publication.
- A real *test-owned* subprocess holds the old file descriptor after rename;
  the producer fixture refuses finalization while it is active. There are no
  production LaunchDaemon, root, sudo, reboot or system log side effects.

## Acceptance status

- Core + statistics reader + fixture tests: implemented and tested locally.
- Production writer-coordinated hold: **NOT IMPLEMENTED**.
- Automatic cleanup/scheduling/live pruning: **NOT ENABLED**.
- Issue #30 cannot be marked completely resolved on the basis of the
  injectable protocol and tests alone.
