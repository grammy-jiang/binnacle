# Binnacle macOS raw-log archive staging

**Date:** 2026-10-13. **State:** Implemented as an explicit offline tool.
**Scope:** Only the Mac's allowlisted Binnacle `.log.N` archives.
**No service restart or host reboot is required.**

## Problem

The Mac LaunchDaemons hold their `StandardOutPath` and
`StandardErrorPath` file descriptors open. Automatic `GN` rename-only
rotation retains all bytes written to the old inode; `GNJ` compression
previously lost writes after rotation. The present policy keeps two
uncompressed generations, and the resource monitor warns on growth.

Compression can use substantial CPU and disk even without changing the
source. Staging and deletion must not be conflated: the producer may begin
writing the original inode again immediately after a successful snapshot.

## Implemented safe staging command

```bash
cd ~/Projects/binnacle

# Read-only by default. Shows only owner-verified private raw archives.
.venv/bin/python -m binnacle.companions.darwin_log_archive_stage

# Explicit opt-in; source remains at its original path and inode.
.venv/bin/python -m binnacle.companions.darwin_log_archive_stage \
  --stage mcp.stderr.log.0
```

The staging command accepts only a fixed set of Binnacle log filenames,
a canonical numeric `.log.N` suffix and user-owned private single-link
regular files within the user's private log directory. It rejects symlinks,
hardlinks, foreign ownership, publicly readable files and oversized or
ambiguous input. The default limit is 64 GiB per archive and a minimum
100 GiB free-space reserve plus the source length.

It streams the source through bzip2 into a private, unique temporary file.
The tool computes a SHA-256 digest and original size, decompresses the
temporary snapshot to independently verify both, rereads the original and
rechecks the source file's inode, size, ownership and timestamps. Any
observable concurrent change refuses publication and cleans up the
temporary file. Published files are created atomically **without
overwriting existing snapshots** as `<raw-name>.bz2.pending`.

The pending suffix is intentional: `binnacle stats` excludes these
snapshots to avoid double-counting the original and its compressed copy.

**Staging never deletes, truncates, renames or modifies the raw source.**
It does not run launchctl, newsyslog, network operations or the hardware
watchdog. Existing Binnacle service PIDs are unaffected.

## Clear operational constraints

- The snapshot is a non-authoritative, possibly stale copy if its raw
  source receives new writes **after** successful publication. An
  earlier identical checksum only proves the snapshot's own contents
  at the time of creation.
- There is no automatic promotion of `.bz2.pending` to `.bz2`, no
  automatic pruning, and no automatic deletion of `.log.N` sources.
  Staging by itself consumes additional disk and does not reclaim space.
- Final deletion requires a separately verified quiet window and an
  authoritative writer/descriptor ownership handshake. Merely observing
  no open descriptor once is insufficient: launchd could reopen later.
- The deferred finalizer must also preserve the reader's chronological
  correctness and the configured 100 GiB minimum disk-free boundary.
- A snapshot failure never grants permission to restart MCP, Jobs or
  Tunnel, rotate live logs, or change either Raspberry Pi.

The same applies to user-requested host reboots: this tool does not
authorize or attempt a reboot. Offline finalization and live reboot
acceptance remain distinct milestones.

## Validation

Unit tests cover pure read-only discovery, exact filename allowlist,
permission and symlink refusals, inode replacement, concurrent append,
checksum mismatch, partial/failed writes, atomic non-overwrite
publication and post-publication writer growth.

The staging CLI is intentionally not scheduled. No production archive
currently requires immediate compression: existing Mac Binnacle logs are
orders of magnitude below their 50 GiB live-file threshold.
