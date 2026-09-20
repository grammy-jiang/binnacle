"""Watchdog policy configuration and reset schedules."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ActionKind = Literal["demote", "restore", "reset", "usb_reset", "reload"]


@dataclass(frozen=True, slots=True)
class Policy:
    failures_before_action: int = 3
    successes_before_restore: int = 3
    demoted_metric: int = 900
    reset_after_failover: bool = True
    min_reset_interval_s: float = 300.0
    usb_reset_enabled: bool = True
    #: (attempts, seconds between attempts) stages; attempts 0 = unlimited.
    usb_reset_schedule: tuple[tuple[int, float], ...] = (
        (3, 60.0),
        (3, 180.0),
        (3, 300.0),
        (0, 600.0),
    )
    #: USB vendor:product ids the watchdog may re-enumerate. Nothing else.
    usb_reset_ids: tuple[str, ...] = ("0bda:8812",)
    #: Reset methods, cycled by attempt: "authorized" toggles the sysfs
    #: attribute (device re-init in place, same node); "port_reset" issues
    #: USBDEVFS_RESET on /dev/bus/usb/BBB/DDD (a bus-level port reset, the
    #: closer cousin of a physical replug). Attempt 1 uses the first, 2 the
    #: second, and so on, so a method that does not revive the adapter is
    #: not repeated ten times in a row.
    usb_reset_methods: tuple[str, ...] = ("authorized", "port_reset")
    #: Repair a wedged standby route (re-activate its profile) on the same
    #: threshold and rate limit as the active one.
    standby_repair: bool = True
    #: Move a device to a strictly higher autoconnect-priority profile whose
    #: network is in range (see the module docstring).
    prefer_enabled: bool = True
    #: How often a device that is not on its best profile gets a fresh scan
    #: (a scan on a connected device costs a brief off-channel gap).
    prefer_check_interval_s: float = 300.0
    #: (attempts, seconds) stages between preference moves of one device;
    #: 0 attempts = unlimited. A move that fails or flaps is not repeated
    #: every cycle: 10 min x3, then hourly.
    prefer_schedule: tuple[tuple[int, float], ...] = ((3, 600.0), (0, 3600.0))
    #: Time on the best profile after which the attempt counter clears.
    prefer_hold_s: float = 3600.0
    #: A preference move that leaves the device unhealthy this long is
    #: undone: the profile that worked is re-activated.
    prefer_timeout_s: float = 300.0
    #: Repair a device that has no route: re-activate the best profile in
    #: range; USB-reset an unavailable adapter or one a re-activation did
    #: not bring back.
    down_repair: bool = True
    #: Cycles a device may sit in "connecting" before that counts as down
    #: (DHCP and 802.1X take longer than a cycle).
    connecting_cycles_before_action: int = 6
    #: Bring a USB adapter back to the best link speed it has shown.
    usb_speed_repair: bool = True
    #: (attempts, seconds) stages between link-level resets: 10 min x3,
    #: 1 h x3, then every 6 h.
    usb_speed_schedule: tuple[tuple[int, float], ...] = (
        (3, 600.0),
        (3, 3600.0),
        (0, 21600.0),
    )
    #: After this many resets without reaching the best speed, the lower
    #: speed is accepted as the level until the device shows more again.
    usb_speed_give_up: int = 6
    #: Time at the best speed after which the attempt counter clears.
    usb_speed_hold_s: float = 3600.0
    #: Public resolver asked when the system one fails, to classify the
    #: failure (resolver vs link). Diagnostic; None disables it.
    dns_fallback: str | None = "1.1.1.1"
    #: A cycle longer than this means the loop is hung: exit, let systemd
    #: restart the unit. A slow-but-honest cycle can take minutes (probe
    #: timeouts, a scan, a 60 s `nmcli connection up`), so this is long;
    #: `cycle_slow` lines flag anything over the interval.
    cycle_timeout_s: float = 600.0
    #: Unbind/bind the driver of a wedged or unavailable non-USB radio via
    #: sysfs, on `usb_reset_schedule`. Off until proven on the host.
    driver_reload_enabled: bool = False
    #: Service rungs: restart the tunnel when polling keeps failing on a
    #: healthy uplink; restart the server when its port stops answering
    #: while its unit is active. A stopped unit is the user's choice.
    service_repair: bool = True
    service_failures_before_action: int = 3
    service_restart_interval_s: float = 900.0
    tunnel_restart_after_s: float = 300.0
    #: The tunnel's own health HTTP server (its URL is in this file, and
    #: changes on every restart). Not answering for
    #: `service_failures_before_action` cycles means the process is frozen
    #: -- the log's silence is no signal: healthy and idle it can be quiet
    #: for half an hour (measured 2026-09-14: gaps up to 1931 s), and a
    #: first draft that restarted on 300 s of silence fired on a healthy
    #: tunnel.
    tunnel_health_url_file: Path | None = None
    #: Silence in the tunnel log longer than this is *reported* (an issue),
    #: never acted on.
    tunnel_stale_after_s: float = 1800.0
    tunnel_log: Path | None = None
    mcp_units: tuple[str, ...] = ("binnacle-mcp.service",)
    tunnel_unit: str = "binnacle-tunnel.service"
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    #: How often to look for a profile stuck at the demoted metric with no
    #: demotion on record (a lost state file); reported, not changed.
    reconcile_interval_s: float = 600.0
    #: A full `snapshot` of every device, service and issue lands in the
    #: journal this often even when nothing changes, so any window of the
    #: log has a baseline; declined decisions are re-stated at the same
    #: cadence.
    snapshot_interval_s: float = 600.0
    #: A file whose presence pauses every action (observation and logging
    #: go on): `binnacle-watchdog pause`. Its content is the expiry epoch.
    pause_file: Path | None = None
    #: System services under the uplink. NetworkManager inactive, failed or
    #: unresponsive for `service_failures_before_action` cycles, or
    #: wpa_supplicant inactive while a radio is unavailable, gets a
    #: `sudo -n systemctl restart` (rate-limited like the user units).
    system_service_repair: bool = True
    nm_unit: str = "NetworkManager.service"
    supplicant_unit: str = "wpa_supplicant.service"
    #: Kernel module parameters worth recording in the inventory line, by
    #: name (read from /sys/module/<module>/parameters/); host-specific,
    #: so the repo default is empty.
    inventory_params: tuple[str, ...] = ()
    #: Observe, decide and log everything, apply nothing (the rehearsal
    #: mode for a new build: `binnacle-watchdog run --cycles 3 --dry-run`).
    dry_run: bool = False
    #: The fast path (2026-09-14, the user: "under one minute"). A thread
    #: TCP-connects to the upstream through the active route every
    #: `fast_interval_s`; after `fast_failures_before_action` failures in
    #: a row, and a standby whose TCP path works, it demotes the active
    #: route at once and re-associates it -- the full cycle's failover
    #: (three 30 s cycles) stays as the backstop. 0 disables the thread.
    fast_interval_s: float = 5.0
    fast_failures_before_action: int = 4
    fast_timeout_s: float = 2.0
    #: After a failover restart the tunnel: its in-flight poll hangs on
    #: the dead path for up to a minute, a restart is back polling in
    #: about a second (measured 0.6 s on 2026-09-14).
    restart_tunnel_on_failover: bool = True
    #: Fifth review (2026-09-14 night). A re-association is rate-limited
    #: *within* an episode (one demotion, one failure streak): the first
    #: one of a new episode is always allowed once `reset_floor_s` has
    #: passed since the last, so a second wedge minutes after the first
    #: gets the gentle repair before the USB schedule (it went straight
    #: to a USB reset three times on 2026-09-14, "still unhealthy after
    #: re-association" with none made in that episode).
    reset_floor_s: float = 60.0
    #: Flap damping: a route that wedges again within `flap_window_s` of
    #: an earlier wedge needs twice as many healthy cycles to be restored
    #: (3, 6, 12, 24 ... capped at `restore_hold_max_cycles`), and the
    #: fast path must have seen it pass for `restore_fast_quiet_s`. On
    #: 2026-09-14 15:51-15:57 wlan1 was restored twice within 42 s of
    #: wedging again while wlan2 was healthy the whole time.
    flap_window_s: float = 3600.0
    restore_hold_max_cycles: int = 40
    restore_fast_quiet_s: float = 90.0
    #: Tunnel socket affinity. The tunnel's long-lived connection to
    #: OpenAI is bound to the address of the route that was active when
    #: it started and stays there across route changes (measured
    #: 2026-09-14 16:12: on wlan2's address 15 min after wlan1 took the
    #: default route back; 21:45: on wlan0's). Its device must be the
    #: active route: off it and without a TCP path, the tunnel is
    #: restarted at once; off it but usable for `tunnel_affinity_cycles`
    #: cycles, at a quiet moment (no command forwarded for
    #: `tunnel_quiet_s`).
    tunnel_affinity: bool = True
    tunnel_affinity_cycles: int = 3
    tunnel_quiet_s: float = 30.0
    #: Floor between failover restarts of the tunnel (a second failover
    #: 30 s after the first must still move the socket).
    failover_restart_floor_s: float = 15.0
    #: After a restart, wait this long for the tunnel's new health server
    #: (its URL file is rewritten on start) to answer; `ready_ms` lands on
    #: the service_restart line, a miss logs `tunnel_not_ready`.
    tunnel_ready_timeout_s: float = 10.0
    #: Issue changes per device inside one snapshot interval before the
    #: journal switches to an `uplink_issue_flapping` summary (wlan0's
    #: lossy 5 GHz link wrote 56 issue lines in three hours).
    flap_log_limit: int = 3


def usb_reset_method(policy: "Policy", attempt: int) -> str:
    """Method for USB reset number `attempt` (1-based): the policy's methods
    in rotation, so consecutive attempts try different things."""
    methods = policy.usb_reset_methods or ("authorized",)
    return methods[(attempt - 1) % len(methods)]


def usb_backoff(schedule: tuple[tuple[int, float], ...], attempt: int) -> float:
    """Seconds to wait before USB reset number `attempt` (1-based)."""
    done = 0
    for count, interval in schedule:
        if count <= 0 or attempt <= done + count:
            return interval
        done += count
    return schedule[-1][1] if schedule else 600.0


DEFAULT_POLICY = Policy()
