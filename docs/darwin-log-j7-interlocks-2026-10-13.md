# Issue #30 — J7-compatible log maintenance interlocks

Date: 2026-10-13. Scope: a **library-only** prerequisite for future
production writer-coordinated log finalization. No service stop, log deletion,
CLI, scheduler, sudoers edit, or production lock operation has occurred.

## Source-of-truth lock order

The exact independently reviewed Mac J7 deploy gate uses:

1. The deployment mutex at
   ~/.local/state/binnacle/mac-deploy-gate.lock
2. The Jobs service installation/upgrade mutex at
   ~/.local/state/binnacle/j7/jobs-service.lock

Both are file-based advisory flock locks. A future log finalizer must acquire
the deploy gate mutex BEFORE the Jobs service mutex and hold both until its
writer lifecycle has been safely restored. Acquiring a different lock name
would not exclude an in-progress deployment. Locks alone do not prevent
new RPC requests; this stage deliberately provides NO service authorization.

The real Mac's state root is owned by the user but mode 0755; the j7 child
is mode 0700 and its jobs-service.lock is mode 0600. That is a valid
existing deployment. The interlock implementation therefore requires the
state root be user-owned and not group/world **writable**, while enforcing
private 0700-type permissions on j7 and exact 0600 private locks.
It neither relaxes existing lock permissions nor changes the actual Mac
state directory.

## Implementation

The J7Interlocks scoped context manager in the new library:

- uses fixed canonical filenames and directory-descriptor-relative
  opens; only its two lock files may be created with private mode;
- requires owned, not-writable-by-others state root, private j7 directory,
  regular 0600 single-link lock inodes and NOFOLLOW semantics;
- acquires exclusive nonblocking flock in J7 lock order and refuses a
  busy owner without waiting or killing it;
- retains the exact open descriptors until context exit; verify rechecks
  root, subdirectory and both lock path identities/inodes/modes;
- closes acquired descriptors on any failed partial acquisition, without
  unconditionally unlinking or overwriting existing J7 lock files;
- does not use flock(LOCK_UN) to avoid releasing another process's shared
  open-file-description lock after fork.

Tests use only temporary user-owned directories. Native Mac and Linux tests
cover independent-process contention, foreign mode/ownership, symlink,
hardlink, directory/inode replacement, concurrent J7-style lock
acquisition, failure rollback, mode-0755 production-layout compatibility,
nested owner refusal, and release/reacquisition.

## What the interlocks DO NOT prove

An exclusive J7 lock does not prove the manager is idle or a writer has
closed an old archive inode. Before any production finalizer may use this
code, a separate controller must:

- acquire these exact locks without running inside the service that it
  will stop, and coordinate with any watchdog capable of restarting it;
- obtain a real, fenced MCP+Jobs admission/drain barrier and recheck
  authenticated owner PID/generation and durable Jobs state;
- arm a crash-durable recovery supervisor, verify every inherited/foreign
  writable log FD is closed, and maintain the hold through raw source
  deletion and directory fsync;
- observe 100 GiB reserve, log permissions, source SHA-256, canonical
  compressed verification and safe restart/readiness after finalization.

Neither this module nor PR #34 fixture recovery should be construed as a
production WriterHold. Issue #30 remains OPEN. Live production logs and
services must not be modified by this stage.
