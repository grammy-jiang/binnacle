# Binnacle service-log and lightweight-watchdog parity (2026-10-13)

Status: isolated-worktree implementation, validation and deployment tracked separately.

## Host-specific policy and ownership

| Host | Existing supervision | New companion | Uplink/hardware actions |
| --- | --- | --- | --- |
| Original Raspberry Pi | user systemd + `binnacle-watchdog` | **do not deploy** (avoids dual controllers) | Existing watchdog owns NetworkManager, USB Wi-Fi, failover |
| sextant | user systemd MCP/jobs/tunnel/resource monitor | `binnacle-service-watchdog` | **none**: only wlan0 has an active route, so never reset USB adapters or alter route metrics |
| MacBook Pro | system launchd MCP/jobs/tunnel | `binnacle-service-watchdog` | **none**: no NetworkManager, no USB, no route manipulation, sleep/wake gap resets streaks |

The service watchdog never controls the stable job manager, whose live child
processes must not be lost during a watchdog restart. An operator can create
`~/.local/state/binnacle/service-watchdog.pause` to suspend all recovery
actions without stopping observation; removing it resumes normal decisions.
It never starts a service that was intentionally stopped. Existing launchd/systemd respawn remains
responsible for crashed processes. The new companion only addresses a running
MCP or tunnel process with a nonresponsive *local* endpoint for at least three
cycles, after startup grace and a persisted 15-minute cooldown. Missing service
state or missing tunnel health URL is **unknown**, not unhealthy. Hardware
repairs are absent from this code.

Linux systemd definition: `service_watchdog_deploy.linux_user_unit`.
macOS system LaunchDaemon definition: `service_watchdog_deploy.mac_system_plist`.
Both are side-effect-free renderers. Installation must validate that a host has
the required permissions and only starts this **new label**. Avoid restarting
MCP/jobs/tunnel during activation.

The Mac tunnel profile's verified health URL file is
`~/.config/tunnel-client/binnacle-mac-health.url`. Linux's is
`~/.local/state/tunnel-client/health/binnacle.url`. If the file disappears,
the companion observes the process only and does not make a liveness-based
restart. The Mac `sudo -n launchctl kickstart -k`
recovery requires pre-existing noninteractive administrative authorization; do
not amend sudoers for this companion.

## Log parity

The same FastMCP middleware emits requests and tools on both platforms.
Darwin's stable manager separately emits job events. Changes:

- add Linux-equivalent correlation/outcome fields to Darwin job start/exit events;
- make repeated terminal recording produce one `job_exit` event;
- emit millisecond ISO timestamps from the Darwin manager;
- select a constrained Darwin LaunchDaemon log reader for `binnacle stats`;
- refuse unsafe files and nonallowlisted unit selectors; bound the read budget;
- read newsyslog `.bz2`/`.gz` archives, sort by timestamps, warn and omit
  legacy job lines with no timestamps instead of inventing dates.

On Darwin, enable `[telemetry.tokenizer] enabled = true` in the local TOML
configuration **only after** the deployment and test review, then restart the
MCP process during a safe maintenance window. This is a local configuration
difference, not a missing `tiktoken` dependency.

The existing Mac newsyslog rule remains active. Its `N` setting deliberately
does not signal already-open daemon file descriptors; writes may continue to
the rotated inode until the next controlled service restart. Do not rotate
while expecting that the new active path is necessarily the writer; archived
inodes must be considered in statistics. A stronger reopen/rotation protocol
requires an independent lifecycle review and must not be conflated with
service watchdog recoveries.

## Validation

Use focused unit tests for timing, false positives, refusal/permissions, log
parsing, archive, duplication and bounded memory. Apply no network/USB fault
injection to the production hosts. After isolated tests and a clean committed
branch, check all live Git HEADs and active jobs again before any master merge.
