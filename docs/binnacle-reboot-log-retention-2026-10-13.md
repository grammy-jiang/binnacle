# Binnacle boot-readiness and large-disk log retention

**Date:** 2026-10-13
**Scope:** Existing MacBook Pro, original Raspberry Pi, and sextant.
**Safety:** This is not authorisation to interrupt active work or reboot a host.

## Reboot preflight

Run on each host (after that host has the Binnacle checkout at this commit):

```bash
cd ~/Projects/binnacle
.venv/bin/python scripts/check_binnacle_reboot_readiness.py --json
```

The script is **strictly read-only**. It reports two separate facts:
`boot_ready` means boot-time service definitions, launch agent paths, and
running/enablement status pass a static inspection.
`reboot_now_candidate` additionally requires no active/unknown Binnacle
jobs and no detected Claude, Codex or pytest development processes.
Any inaccessible service, absent job metadata, failed process enumeration,
unexpected OS or ambiguous owner is a blocker, not a success.

The check cannot guarantee that all third-party applications have flushed
their work, that an external USB Wi-Fi adapter will initialize, or that
network availability persists after a real power cycle. Coordinate a quiet
maintenance window and keep remote recovery access before a live reboot.

### Verified host configuration

| Host | Boot configuration | Operational blockers at inspection |
| --- | --- | --- |
| MacBook Pro | Five Binnacle system LaunchDaemons; `RunAtLoad` and `KeepAlive`, valid plist files, executable paths present | Four Job Manager jobs plus other development processes; no reboot |
| Original Raspberry Pi | Enabled user systemd MCP, Jobs, Tunnel, advanced hardware Watchdog and resource monitor; lingering enabled | Multiple Claude/Codex sessions, changed files in separate ongoing work |
| sextant | Enabled user systemd MCP, Jobs, Tunnel, service-health Watchdog and resource monitor; lingering enabled | Claude/Codex and pytest sessions actively running |

On the Mac, `/Library/LaunchDaemons/com.binnacle.mcp.plist` initially lacked
`Umask`. An exact-hash-guarded, backed-up, atomic **disk-only** edit set
`Umask=0077` without reloading or restarting the live service. All other
plist settings remained identical. `plutil -lint` passed. The disk
definition will take effect after its next safe launchd bootstrap or reboot;
the existing MCP process still holds its original file descriptors.

The original Pi's sophisticated USB/network Watchdog must remain the
hardware-recovery owner. Do not install a second lightweight watchdog there.
On sextant, the application-only watchdog uses a private, commit-pinned source
snapshot, independent of its old live development checkout.

## macOS log retention

Linux journald on both Pis is configured for `Storage=persistent`,
`SystemMaxUse=50G`, `SystemKeepFree=100G`, `MaxRetentionSec=0`.
These numbers are for **journald's aggregate storage**, not per-file sizes.

The Mac has a large SSD with approximately 2.4 TiB free at the inspection.
Its native `newsyslog` is per-file. The approved Binnacle policy:

| Setting | Value |
| --- | --- |
| Threshold per uncompressed active `*.log` file | **10 GiB** |
| Early warning per file | **8 GiB** |
| Minimum remaining disk free-space warning | **100 GiB** |
| Archived generations | **7 per file** |
| Permissions | `0600`; log directory private |
| Compression | bzip2 via `J`; keep `GNJ` flags |

Pure source configuration:
`binnacle.companions.darwin_log_privacy.render_newsyslog_rule()`.
Installed path: `/etc/newsyslog.d/com.binnacle.mcp.conf`. A root-owned
config replacement requires a byte-exact preflight, backup and
`newsyslog -n -v` dry-run. Do not force a rotation during deployment.

**Important limitation:** Launchd's `StandardOutPath` and
`StandardErrorPath` are opened by launchd and the daemon keeps writing to
those inodes. `newsyslog` with `N` does not signal the writer; with `J`,
it can compress the old inode while writes continue. This was reproduced
against a fully isolated temporary fixture: post-rotation data was absent
from both the newly active path and compressed archive.

Increasing the threshold reduces the immediate likelihood of a lossy
rotation; it does **not** make rotation lossless or impose a hard aggregate
50 GiB cap. The read-only Darwin resource monitor warns at 8 GiB and when
remaining disk free space falls below 100 GiB. If the warning fires, arrange
a coordinated quiet window. Do not force a live rotation or replace this
with `copytruncate` and claim it is lossless. A proper writer-coordinated
reopen protocol remains a separate design and acceptance item.

## Restart acceptance and current constraints

- All three hosts' core services are currently active and boot-managed.
- Mac Job Manager is still running revision `0a40b064` with active jobs.
  The new logging format and configured tokenizer accounting have not yet
  been activated by a process restart. Do not restart Jobs/MCP while busy.
- The two light service-health Watchdogs are active and the original Pi's
  advanced hardware Watchdog is unchanged. Simulation tests pass, but a
  production crash/failover exercise has not been run.
- GitHub `master` is ahead of both Raspberry Pi live checkouts on purpose.
  Updating either can trigger an active Uvicorn `--reload` or interfere
  with unrelated agent work. Only update a quiet host after its own checks.
- A reboot should be performed **only** after the preflight has no blockers,
  an operator confirms all other work is quiescent and external recovery
  access is available. Record service PIDs, journal/launchd status and
  `binnacle stats` afterwards; a static preflight is not a reboot test.
