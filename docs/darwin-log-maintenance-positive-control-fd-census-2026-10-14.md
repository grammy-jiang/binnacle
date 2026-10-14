# Issue #30 — Read-only writable-FD census evidence with positive control

Date: 2026-10-14. Status: **advisory-only parser, no production control**.
All work was performed in isolated sextant/Pi worktrees. The installed
MacBook Pro services, active development and real log archives were
never touched.

## Why a positive control is required

A plain lsof query returning no matching file descriptors does not
prove that the scanner had permission to see every process or that
its output was complete. The production Issue #30 contract therefore
requires a positive control **within the same privileged file-scan
invocation**: a caller-created private file whose exact PID, numeric
FD, device and inode are known independently and which is positively
held writable throughout the census.

The fixed command structure for the future independent controller is:

    /usr/sbin/lsof -nP -F pafDin -- <pinned-raw-path> <pinned-canary-path>

Both paths are distinct; the source and canary have independently
pinned device/inode pairs. The parser refuses unexpected process/FD
fields, field order, duplicate FD tuples, unknown access modes,
impossible PID/FD identity, incomplete output and any target or canary
inode mismatch.

The canary must be found under its *own exact PID and numeric FD* with
access w or u. A mere process name, a filename, a read-only handle or
another process's writable handle is insufficient. For target source
records, r is counted as a reader while w and u count as possible
writers. Every record outside the two allowlisted paths refuses.

## Important observed lsof exit semantics

On Linux, passing both source and canary pathnames can produce
returncode **1** with a valid positive writable canary in stdout if
the source pathname has **no currently open FD**. This behavior was
discovered in a real isolated Raspberry Pi test.

The evidence parser therefore handles two exact cases:

- Exit 0 and no stderr: parse and classify all records, requiring the
  writable canary regardless of source matches.
- Exit 1 and no stderr, with a complete and authenticated-looking
  canary record and **zero source records**: return only diagnostic
  source_absent_or_scan_incomplete_advisory_only, not a successful
  production quiescence proof.

Exit 1 containing any source records is inconsistent and refuses.
Any other returncode, stderr, missing canary or malformed/incomplete
output refuses. A successful-looking lsof transcript still cannot
prove privileged access, uninterrupted scope or launchd generation.

## Authority boundary

The new module is a **pure parser and command-argument constructor**.
It does not execute lsof itself, open source paths, write or close
process file descriptors, run launchctl, signal a process or unlink a
raw archive. It cannot claim the canary identity is actually owned by
the caller. The separate production controller must verify a real
positive FD with fstat and prove lsof's executable integrity and
privileged, complete process visibility.

The returned FDCensusEvidence always has:

- manual_review_required = true
- complete_privileged_fd_census = false
- production_authorized = false

These flags cannot be turned true by source-free output, perfect
positive-control rows, fake privileged counters or caller-injected
data. Without independent privileged generation/Fd and recheck guards,
the only safe result is to leave the original raw log unchanged.

## Qualification and limitations

The private temporary-file tests cover malformed/truncated output,
unknown fields, bad process/FD/device/inode, read-only or missing
positive controls, duplicate entries, foreign paths, mismatched
source identity, exit codes and stderr. Real Linux lsof tests prove
detection of (1) known canary only, (2) an open read-only source,
(3) a writable source and (4) a writable source held by a separate
test-owned subprocess.

Linux lsof output is only a portability/reference test. Darwin lsof
format and its privileges must be validated on actual macOS in a
controlled non-destructive fixture. The producer must also be proven
unloaded and unable to restart, existing Jobs/MCP traffic must be
drained and Watchdog/guardian ACKs authenticated before any true log
maintenance operation is permitted.

The collector does not solve those production prerequisites. Issue
Issue #30 remains OPEN and real automatic/raw-log pruning stays OFF.
