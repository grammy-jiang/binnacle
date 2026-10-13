# Issue #30: production-grade writer-coordinated log finalization

Status: staged implementation. This document specifies the remaining
production safety boundary after the native fixture proof in PR #32.

## Required transaction boundary

Only five repository-managed Binnacle LaunchDaemons are eligible:
MCP, Jobs, Tunnel, service-watchdog, resource-monitor. The separately
installed session-observability service remains ineligible until its
full owner, plist and command lifecycle have been reviewed.

No automatic task, scheduler, start-on-boot operation, or transparent
log deletion is in scope. Manual production finalization must be invoked
from a separately authenticated out-of-band shell, never through an
MCP command of the service it may stop. The caller must explicitly name
one raw archive, its producer and accept one bounded service outage.

### P1: Privileged writer generation and admission

- Verify the exact root:wheel installed plist, regular single-link 0644,
  exact label, UserName, stdout/stderr paths, service PID and start time.
- Verify the configured private 0700 log directory and one allowlisted
  private 0600 single-link source inode. No symlinks.
- Exclusively own the fixed J7 deployment/maintenance locks and a separate
  finalizer transaction lock. A concurrent upgrade or transaction refuses.
- Require a fresh quiet-window proof, no active/unknown durable Jobs, no
  incomplete/pending job or connection, and no direct producer RPC actor
  other than the out-of-band controller. Never kill a job to make progress.
- Recheck admission after bootout. Refuse if producer did not unload.
- Prove all source-writable FDs (including inherited children) closed.
  Use a complete privileged lsof scan with exact access modes and an
  independently verified positive-control file. Unknown => refuse.

### P2: Independent crash recovery

- Before bootout, arm a separately owned bounded recovery supervisor.
  Its authority is limited to restoring the *same* root-owned, pinned
  service plist and label. No general command or arbitrary path.
- The recovery journal records owner PID/starttime, producer label and
  original plist digest, writer generation, monotonic lease deadline,
  and a one-time transaction identity; private 0600 single-link.
- If the controller exits abnormally or fails to release the hold before
  deadline, supervisor attempts idempotent bootstrap of the exact same
  label, verifies new PID/generation and logs a durable outcome.
  No forced reboot, broad service reset or deletion.
- Controller always performs normal bootstrap/readiness then disarms
  the supervisor; recovery must also work when the controller is
  SIGKILLed after bootout, or when canonical archive is published and
  raw source still exists.
- If the controller exits before bootout, the guardian must observe the
  same running producer generation, durably disarm without rebootstrapping,
  and leave the original rotated log inode untouched. A new active
  filename must not be fabricated merely to make the test appear healthy.
- If guardian readiness cannot be independently verified before
  bootout, production hold is refused without touching producer.

### P3: Publish/prune only while verified held

- Reuse the already reviewed FD-relative, checksum-verified,
  no-overwrite finalizer data plane. Keep the existing raw archive if
  any guard, generation, source hash, disk reserve or write fails.
- 100 GiB minimum free reserve plus source budget, 40 GiB growth
  warning, two raw retained generations and newsyslog GN only.
- Recheck the protected producer generation, guardian lease, no
  writable FDs and exact source inode immediately before unlink.
  Fail if an ordinary GN rotation or maintenance operation changed
  the archive path while staged; never issue newsyslog -F.
- Recovery of interrupted canonical publication requires independent
  compressed digest/length equivalence before raw can be unlinked.
  Statistics count one generation while raw and canonical coexist.

### P4: Qualification and release

- Synthetic tests: loaded writer, unmapped writer, inherited FD, PID
  reuse, arbitrary bootstrap race, lease expiry, insufficient disk,
  partial publication, corrupt compressed archive, SIGTERM, SIGKILL,
  guardian outage, interrupted restoration, repeated GN rotation.
- Native Mac: isolated root-owned launchd fixtures only. Prove
  recovery after killing *the controller process*, not the writer;
  preserve all five real Binnacle LaunchDaemons and all real logs.
- Linux Python 3.10-3.14 compatibility, MyPy on both platform targets,
  Ruff/Bandit, 90%+ focused branch coverage, full protected CI.
- Production activation only after an independent code review and an
  explicit, separately scheduled manual Mac maintenance window.
  Issue #30 remains OPEN until that contract is complete.

## Non-goals and threat model

This design does not defend against a hostile privileged administrator or
malicious same-UID actor that ignores all cooperative locks and directly
rebootstraps a target. Trust decisions are rooted in actual launchd
service identity, fd inspection and serial controller locks, not
untrusted user-provided WriterHold instances. An isolated test fixture
does not grant authority to prune real logs.
