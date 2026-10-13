# Cross-host Binnacle hardening — recovery, privacy and Darwin resource monitoring

Date: 2026-10-13. Scope: service-observability companions, **no new MCP tools**.
Source: independent worktree `ops/log-watchdog-hardening-20261013`.

## Host facts and non-disruption invariants

- **Original Raspberry Pi:** preserve the existing `binnacle-watchdog` hardware,
  NetworkManager and multi-radio logic. Do not install a second service watchdog.
- **sextant:** a separate `binnacle-service-watchdog.service` now exists.
  Its recovery flag was enabled at 10:29 AEDT by a concurrent operation.
  There is still only one connected Wi-Fi route; it must **never** touch
  USB, NetworkManager or routing.
- **MacBook Pro:** `com.binnacle.service-watchdog` was switched to active
  recovery at 10:28 AEDT. The stable Job Manager has active jobs and is still
  running an older code revision. Do not restart MCP/Jobs/Tunnel for deployment.

## Recovery last-moment admission

Application-only recovery may occur **only** when all these facts are true:

1. The original watchdog failure streak and startup/wake/cooldown limits apply.
2. A fresh local health probe immediately before action still proves that the
   service is running and its endpoint is unresponsive.
3. The Job Manager's durable activity evidence is safely classified as idle.
   Darwin asks its authenticated local Job Manager for `running_jobs` and
   `unknown_jobs`; both must be exactly zero. The Linux version-1 manager
   ping has no counts, so Linux uses the durable Job Store records as a
   conservative fallback. Any unreadable, malformed or ambiguous record blocks
   recovery. It may occasionally suppress an otherwise useful restart, by design.
4. The existing pause marker and persisted restart-attempt cooldown are respected.
5. Only the existing allowlisted MCP/tunnel service is eligible. The
   stable Job Manager is never forcibly restarted by this companion.

This narrows safety races but cannot provide full atomic admission against a
new concurrent request: the Binnacle host does not expose a shared quiet-window
lock between the MCP dispatcher and the watchdog. Therefore do not use
production fault injection to claim proof of no disruption. Tests use fakes.

## macOS log permissions and rotation

At 10:35 AEDT, four pre-existing launchd log files had their permissions
tightened from 0644 to 0600 **without reopening or restarting a process**.
The original launchd descriptors remained usable.

A further isolated experiment demonstrated that `newsyslog` with `N` and `J`
flags can compress a file while launchd continues writing to its old inode;
data written after compression was visible in neither live path nor archive.
For immediate protection the installed Mac rule was atomically changed from
10 MiB to **1 GiB**, with a separate private backup and successful
`newsyslog -n` dry-run. Seven compressed archives remain configured.
No production log was rotated by that change.

The 1 GiB value buys time, **not a mathematical no-loss guarantee** if a
daemon keeps its stdout/stderr descriptor open long enough to reach 1 GiB.
Never force `newsyslog` rotation of live launchd stdout/stderr. A future
truly lossless design must use writer-coordinated reopen or an agreed quiet
maintenance window: only after confirming that the affected writer's old
descriptor is closed may its log be archived. Do not use copy+truncate as
an allegedly lossless workaround.

The new Darwin resource monitor also checks private log permissions using
`O_NOFOLLOW` and the current user's ownership, never follows a symlink,
and emits a warning when an active .log file exceeds 768 MiB so a
maintenance window can be planned before reaching the installed threshold.

## macOS resource monitor

Darwin has no Linux `/proc/pressure` PSI trigger files. The new lightweight
`com.binnacle.resource-monitor` LaunchDaemon samples every 60 seconds:

- host load averages and logical CPU count;
- home-volume free and total disk bytes;
- `vm_stat` page size and named page counts (not falsely labelled as
  Linux PSI or precisely available memory);
- `memory_pressure -Q` reported system free percentage;
- `sysctl -n hw.memsize` total physical memory.

All native commands are read-only, have bounded timeouts, and are optional.
Missing metrics are omitted; the monitor continues instead of treating them
as zeros. It does not enumerate child processes, manipulate networks or
perform any recoveries. A private `resource-monitor.stderr.log` is created
with mode 0600 **before** the new launchd job is bootstrapped.

## Deployment and remaining acceptance

1. Commit and validate in the independent Mac worktree; test on sextant
   **only in a separate verification worktree**.
2. Follow existing branch protections and CI; no force push or test-bypass.
3. New Mac resource monitor may be bootstrapped separately after plist/permissions
   preflight without touching MCP/Jobs/Tunnel.
4. Updating service-watchdog to its stronger safety policy may restart
   **only the watchdog service**, with exact config backup/hash verification.
   Preserve a concurrent operator's `--restart-enabled` choice; do not
   reconfigure anyone else's settings. On sextant, create a version-frozen
   `git archive` of the merged `src/binnacle` under a private per-commit
   release directory and use `linux_user_unit(..., module_root=<release>/src)`.
   The separate watchdog imports the entire matched source snapshot; never
   copy only `service_watchdog.py` with mismatched companion modules.
5. Do not pull to the original Pi's or sextant's live development checkout;
   Pi uvicorn `--reload` would make that an unplanned MCP restart.
6. When Job Manager and MCP sessions are truly idle in a separate maintenance
   window, verify safe restart semantics, activate the already configured
   macOS tokenizer setting and timestamped Job Manager telemetry, then
   confirm end-to-end logs and `binnacle stats`.
7. Full in-service fault injection, crash recovery acceptance, durable
   lossless rotation and host-version convergence remain separate acceptance
   items until a safe maintenance window is available.
