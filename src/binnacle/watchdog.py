"""Uplink watchdog: keep the connector reachable when a radio wedges.

The failure this exists for (2026-09-12): the USB adapter held the default
route, stopped passing packets, and kept every local health signal green --
association up, carrier up, DHCP lease valid, driver silent. Nothing in the
system was both able to notice and allowed to act, so the outage ran 48
minutes and ended only because the adapter was physically unplugged.

Policy, in order:

1. Probe every default route each cycle (binnacle.uplink).
2. When the *active* route (lowest metric) fails every layer for
   `failures_before_action` cycles in a row, and another route is healthy,
   demote it: raise its metric so traffic moves to the healthy interface.
   The connector comes back within one cycle; it never waits on a repair.
3. Then try to repair the demoted interface (`nmcli connection up`),
   rate-limited so a persistently broken radio cannot cause a reset storm.
4. If it stays unhealthy, re-enumerate its USB device -- the software form
   of the replug that revived it on 2026-09-12 21:00 when re-association
   had not (802.11 auth, assoc, 4-way handshake and DHCP all succeeded and
   the data path stayed dead). Attempts follow `usb_reset_schedule`: 1 min
   x3, 3 min x3, 5 min x3, then every 10 min without limit, counted from
   the re-association; the counter resets once the device is healthy.
   Only a device whose USB id is in `usb_reset_ids` is ever touched, its
   node is resolved fresh each time (it moves 1-1 -> 2-1 across the mode-1
   re-enumeration), and it only happens while the device is demoted, so the
   connector is already on the other route.
5. Keep probing the demoted interface. After `successes_before_restore`
   healthy cycles, restore its original metric.

Two more things run beside the failover (2026-09-13):

- Standby repair: a wedged *standby* route is re-activated on the same
  threshold and rate limit as the active one. A dead lifeline is the "no
  healthy alternative" case waiting to happen (wlan0 sat on a dead 5 GHz
  link at 18:16 and nothing looked at it), so it is fixed while nothing
  depends on it.
- Profile preference: NetworkManager activates the first profile whose
  network shows up in the first scan and never revisits the choice, so
  after each reset the USB adapter came back on its 2.4 GHz profile
  (autoconnect-priority 0) with the 5 GHz one (priority 20) in range --
  24 hours on the wrong band before anyone noticed. Each cycle the
  watchdog reads the priorities NetworkManager already holds and, when a
  strictly higher-priority profile's network is in range, re-activates
  it: a standby device at once; the active device only through a
  demotion, so traffic is on the other route before the link goes down,
  with the target profile's metric raised too, so the new link earns its
  way back with `successes_before_restore` healthy cycles like any
  repaired device. Attempts back off on `prefer_schedule`, never start
  while a demotion is in flight, and a move that does not come up falls
  back to the profile that worked after `prefer_timeout_s`. Preference
  is expressed only in NetworkManager (`connection.autoconnect-priority`);
  nothing here names a profile or a band.

Reviewed 2026-09-13 (user: keep the network up first, then bring every
radio back to its highest level). Every cycle observes every Wi-Fi device
NetworkManager manages -- not only the ones with a default route -- and
grades it: absent / unavailable / disconnected / connecting / no route /
wedged / degraded / healthy, plus the *level* of a healthy one: the band
(the profile NetworkManager ranks highest), the USB link speed against the
best this device has shown, channel width and rate (reported, not repaired).
The repair ladder, worst first, each rung rate-limited and backed off:

- a wedged active route: failover, re-association, USB reset (above);
- a wedged standby: re-association to the best profile in range;
- a device without a route (disconnected, connecting too long,
  unavailable): re-activate the best profile in range; a USB adapter that
  is unavailable, or that a re-activation did not bring back, gets the
  USB reset schedule -- it carries nothing, so this costs nothing;
- a USB adapter whose link is below the best speed it has shown (a USB 3
  part enumerated at 480 Mbit/s): re-enumerate it -- through a demotion
  when it is the active route -- on `usb_speed_schedule`, and accept the
  lower level after `usb_speed_give_up` attempts until it shows the
  higher one again;
- a device on a lower-priority profile than one in range: the preference
  move (above).

Invariants that put connectivity first: a link-down action on the active
route happens only after a demotion, and a demotion only when another
route is healthy this cycle; a demotion raises the metric of *every*
profile bound to the device, so whatever NetworkManager brings up after
the repair still waits for `successes_before_restore` healthy cycles; one
voluntary action (level or preference) per cycle and none while a
demotion is in flight; the last healthy route is never demoted.

The adapter is never removed and never left out of service permanently --
demotion is reversed as soon as it carries traffic again.

Route changes go through NetworkManager (`connection modify` +
`device reapply`), not `ip route`: NM re-applies its own routes on every
DHCP renew -- measured every ~11 minutes on this host -- and would revert a
direct route edit. `evaluate` is pure, so the policy is tested without a
network.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from binnacle import uplink
from binnacle.uplink import ProbeResult, Route

log = logging.getLogger("binnacle.watchdog")

#: Held around every decide-and-act section: the full cycle's, and the
#: fast path's, so the two never interleave a demotion.
ACT_LOCK = threading.Lock()

Run = Callable[..., "subprocess.CompletedProcess[str]"]
ActionKind = Literal["demote", "restore", "reset", "usb_reset", "reload"]


def _run(*args: str, timeout: float = 30.0) -> "subprocess.CompletedProcess[str]":
    """Run a command; a timeout is reported as exit 124 (like coreutils'
    `timeout`) so a hung NetworkManager degrades the observations instead
    of aborting the cycle.

    For `sudo ...` the timeout is enforced by coreutils `timeout` on sudo's far
    side -- see uplink.sudo_timeout_argv for why subprocess's own timeout
    cannot do it. CompletedProcess.args is reported as the ORIGINAL argv so
    callers and logs see what was asked for, not the wrapping.
    """
    argv = uplink.sudo_timeout_argv(args, timeout)
    wrapped = argv != list(args)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout + 5 if wrapped else timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            list(args), 124, stdout="", stderr=f"timed out after {timeout:.0f} s"
        )
    if wrapped:
        proc.args = list(args)
    return proc


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
    mcp_units: tuple[str, ...] = ("binnacle-mcp.service", "binnacle-mcp-dev.service")
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
    #: go on): `binnacle watchdog pause`. Its content is the expiry epoch.
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
    #: mode for a new build: `binnacle watchdog run --cycles 3 --dry-run`).
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


#: Shared default; Policy is frozen, so one instance is safe to reuse.
DEFAULT_POLICY = Policy()


@dataclass(slots=True)
class Demotion:
    """A route we raised the metric on, and how to put it back."""

    dev: str
    profile: str
    original_metric: int
    since: str
    reason: str
    #: "wedged" (failover) or "preference" (a deliberate profile move).
    kind: str = "wedged"
    #: For a preference move: the profile being activated, and the metric
    #: it had before the move raised it, so restore can put both back.
    target: str = ""
    target_metric: int | None = None
    since_ts: float = 0.0
    #: Every other profile bound to the device and its metric before the
    #: demotion raised them all: whatever NetworkManager activates after a
    #: repair must still earn its way back.
    others: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class State:
    """What must survive a watchdog restart.

    Demotions persist (an un-restored demotion would silently strand the
    adapter); the consecutive-failure counters do not, because a fresh
    process should re-observe a fault before acting on it.
    """

    demoted: dict[str, Demotion] = field(default_factory=dict)
    last_reset: dict[str, float] = field(default_factory=dict)
    last_usb_reset: dict[str, float] = field(default_factory=dict)
    usb_attempts: dict[str, int] = field(default_factory=dict)
    #: Preference moves: last attempt time and count per device (persist,
    #: so a restart does not restart the backoff), and since when the
    #: device has been on its best profile (clears the count after
    #: `prefer_hold_s`).
    last_prefer: dict[str, float] = field(default_factory=dict)
    prefer_attempts: dict[str, int] = field(default_factory=dict)
    preferred_since: dict[str, float] = field(default_factory=dict)
    #: Last fresh scan per device; not persisted (a restart may scan).
    last_scan: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    successes: dict[str, int] = field(default_factory=dict)
    last_cycle: str = ""
    last_summary: dict[str, str] = field(default_factory=dict)
    #: dev -> "profile (band)" as of the last cycle; shown by `doctor`.
    last_profiles: dict[str, str] = field(default_factory=dict)
    #: USB link level: the best speed each adapter has shown, the reset
    #: attempts made to get back to it, when the last one was, and since
    #: when it has been at the best (not persisted; clears the count after
    #: `usb_speed_hold_s`).
    usb_best_speed: dict[str, int] = field(default_factory=dict)
    usb_speed_attempts: dict[str, int] = field(default_factory=dict)
    last_usb_speed_reset: dict[str, float] = field(default_factory=dict)
    usb_best_since: dict[str, float] = field(default_factory=dict)
    #: Consecutive cycles a device has had no route; not persisted.
    down_cycles: dict[str, int] = field(default_factory=dict)
    #: dev -> one-line description of state and level; shown by `doctor`.
    last_devices: dict[str, str] = field(default_factory=dict)
    #: dev -> what is below its highest level right now; `doctor` warns.
    issues: dict[str, str] = field(default_factory=dict)
    #: When the loop last switched NetworkManager's Wi-Fi radio back on.
    last_radio_on: float = 0.0
    #: Devices ever observed (dev -> usb id or "builtin"): a device that
    #: disappears from NetworkManager is reported as absent.
    known_devices: dict[str, str] = field(default_factory=dict)
    #: Driver reloads (non-USB radios), paced like the USB schedule.
    reload_attempts: dict[str, int] = field(default_factory=dict)
    last_reload: dict[str, float] = field(default_factory=dict)
    #: Service restarts: "mcp" / "tunnel" -> last restart time.
    last_service_restart: dict[str, float] = field(default_factory=dict)
    #: Transient: consecutive failing cycles per service, consecutive cycles
    #: with a healthy active route, last reconcile time, extra issues.
    service_failures: dict[str, int] = field(default_factory=dict)
    uplink_ok_cycles: int = 0
    last_reconcile: float = 0.0
    extra_issues: dict[str, str] = field(default_factory=dict)
    #: Cycles since the state file was created (persisted: the journal's
    #: `cycle=` numbers stay unique across restarts).
    cycle_n: int = 0
    #: Grade of every device as of the last cycle and since when (persisted,
    #: so a restart does not fake a transition).
    last_grade: dict[str, str] = field(default_factory=dict)
    grade_since: dict[str, float] = field(default_factory=dict)
    #: Transient: what `evaluate` declined to do this cycle and why, as
    #: (dev, rung, note); the last note logged per (dev, rung) and when.
    decisions: list[tuple[str, str, str]] = field(default_factory=list)
    last_decision: dict[str, tuple[str, float]] = field(default_factory=dict)
    last_snapshot: float = 0.0
    last_inventory: dict[str, str] = field(default_factory=dict)
    last_inventory_at: float = 0.0
    #: Transient: consecutive cycles NetworkManager answered nothing.
    nm_unresponsive_cycles: int = 0
    #: Persisted: last restart per system service ("nm", "supplicant").
    last_system_restart: dict[str, float] = field(default_factory=dict)
    #: Transient: seconds the last cycle took, for the summary line.
    last_duration_ms: float = 0.0
    #: Transient: the role each device had last cycle ("active" /
    #: "standby" / "none"); the failure counter restarts on a change.
    last_role: dict[str, str] = field(default_factory=dict)
    #: Transient: consecutive cycles NetworkManager's unit was not active.
    nm_inactive_cycles: int = 0
    #: Transient: whether the last cycle ran paused (for the transitions).
    was_paused: bool = False
    #: Transient: consecutive degraded cycles per device (hysteresis).
    degraded_streak: dict[str, int] = field(default_factory=dict)
    #: Transient: the fast path's consecutive TCP failures on the active
    #: route, which route they were on, and the last failover restart.
    fast_failures: int = 0
    fast_dev: str = ""
    last_failover_restart: float = 0.0
    #: Persisted: when each device was demoted for a wedge, inside the
    #: flap window (the restore hold-down doubles per entry).
    wedge_times: dict[str, list[float]] = field(default_factory=dict)
    #: Heartbeat of the fast path (epoch of its last tick); in the state
    #: file for `doctor`, never loaded back.
    fast_last: float = 0.0
    #: Transient: repairs running right now outside the lock (dev ->
    #: started), the start of each device's failure streak (an episode),
    #: the fast path's view of demoted routes (last failure, current
    #: success streak), the tunnel's socket device and how many cycles it
    #: has sat off the active route, the last tunnel restart of any kind,
    #: and the issue-line flap damping.
    repair_in_flight: dict[str, float] = field(default_factory=dict)
    failure_since: dict[str, float] = field(default_factory=dict)
    fast_demoted_last_fail: dict[str, float] = field(default_factory=dict)
    fast_demoted_streak: dict[str, int] = field(default_factory=dict)
    tunnel_via: str = ""
    tunnel_off_active_cycles: int = 0
    last_tunnel_restart: float = 0.0
    issue_flips: dict[str, list[float]] = field(default_factory=dict)
    last_flap_log: dict[str, float] = field(default_factory=dict)
    last_logged_issue: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        data = asdict(self)
        data["failures"] = {}
        data["successes"] = {}
        for transient in (
            "last_scan",
            "down_cycles",
            "usb_best_since",
            "service_failures",
            "uplink_ok_cycles",
            "last_reconcile",
            "extra_issues",
            "decisions",
            "last_decision",
            "last_snapshot",
            "last_inventory",
            "last_inventory_at",
            "nm_unresponsive_cycles",
            "last_duration_ms",
            "last_role",
            "nm_inactive_cycles",
            "was_paused",
            "degraded_streak",
            "fast_failures",
            "fast_dev",
            "last_failover_restart",
            "repair_in_flight",
            "failure_since",
            "fast_demoted_last_fail",
            "fast_demoted_streak",
            "tunnel_via",
            "tunnel_off_active_cycles",
            "last_tunnel_restart",
            "issue_flips",
            "last_flap_log",
            "last_logged_issue",
        ):
            data.pop(transient, None)
        return json.dumps(data, indent=2)

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        state = cls()
        for dev, d in (raw.get("demoted") or {}).items():
            try:
                state.demoted[dev] = Demotion(**d)
            except TypeError:
                continue
        state.last_reset = {
            k: float(v) for k, v in (raw.get("last_reset") or {}).items()
        }
        state.last_usb_reset = {
            k: float(v) for k, v in (raw.get("last_usb_reset") or {}).items()
        }
        state.usb_attempts = {
            k: int(v) for k, v in (raw.get("usb_attempts") or {}).items()
        }
        state.last_prefer = {
            k: float(v) for k, v in (raw.get("last_prefer") or {}).items()
        }
        state.prefer_attempts = {
            k: int(v) for k, v in (raw.get("prefer_attempts") or {}).items()
        }
        state.preferred_since = {
            k: float(v) for k, v in (raw.get("preferred_since") or {}).items()
        }
        state.usb_best_speed = {
            k: int(v) for k, v in (raw.get("usb_best_speed") or {}).items()
        }
        state.usb_speed_attempts = {
            k: int(v) for k, v in (raw.get("usb_speed_attempts") or {}).items()
        }
        state.last_usb_speed_reset = {
            k: float(v) for k, v in (raw.get("last_usb_speed_reset") or {}).items()
        }
        state.last_cycle = raw.get("last_cycle", "")
        state.last_summary = raw.get("last_summary") or {}
        state.last_profiles = raw.get("last_profiles") or {}
        state.last_devices = raw.get("last_devices") or {}
        state.issues = raw.get("issues") or {}
        state.last_radio_on = float(raw.get("last_radio_on") or 0.0)
        state.known_devices = {
            str(k): str(v) for k, v in (raw.get("known_devices") or {}).items()
        }
        state.reload_attempts = {
            k: int(v) for k, v in (raw.get("reload_attempts") or {}).items()
        }
        state.last_reload = {
            k: float(v) for k, v in (raw.get("last_reload") or {}).items()
        }
        state.last_service_restart = {
            k: float(v) for k, v in (raw.get("last_service_restart") or {}).items()
        }
        state.cycle_n = int(raw.get("cycle_n") or 0)
        state.last_grade = {
            str(k): str(v) for k, v in (raw.get("last_grade") or {}).items()
        }
        state.grade_since = {
            k: float(v) for k, v in (raw.get("grade_since") or {}).items()
        }
        state.last_system_restart = {
            k: float(v) for k, v in (raw.get("last_system_restart") or {}).items()
        }
        state.wedge_times = {
            str(k): [float(t) for t in v]
            for k, v in (raw.get("wedge_times") or {}).items()
            if isinstance(v, list)
        }
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(path)


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    dev: str
    reason: str
    metric: int | None = None
    #: For "reset": the profile to activate (None = the device's current
    #: one). For a "preference" demote: the profile the move is heading to.
    profile: str | None = None
    #: Why: "wedged" (failover), "standby" (standby repair), "down" (a
    #: device without a route), "preference" (a move to a better profile),
    #: "fallback" (undoing such a move), "usb_speed" (link-level repair).
    tag: str = "wedged"
    #: "cycle" (the 30 s loop) or "fast" (the 5 s thread); on the journal
    #: line, because the cycle's grade is stale when the fast path acts.
    trigger: str = "cycle"


@dataclass(frozen=True, slots=True)
class Preference:
    """What NetworkManager's priorities say about one device right now."""

    dev: str
    #: The profile active on the device.
    current: str
    #: A strictly higher-priority profile for this device, or None when
    #: the current one is already the best.
    target: str | None
    #: Whether the target's network is in the device's scan results.
    visible: bool = False


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """One Wi-Fi device as NetworkManager, sysfs and iw see it this cycle."""

    dev: str
    #: NetworkManager state: connected, connecting, disconnected,
    #: unavailable, unmanaged, deactivating.
    nm_state: str
    profile: str = ""
    usb_id: str | None = None
    #: USB link speed in Mbit/s (5000 SuperSpeed, 480 high speed); None
    #: for a device that is not a USB adapter the watchdog may reset.
    usb_speed: int | None = None
    freq: int | None = None
    width: int | None = None
    rate: float | None = None
    signal: int | None = None

    def describe(self, best_usb: int | None = None) -> str:
        parts = [self.nm_state]
        if self.profile:
            parts.append(self.profile)
        if self.freq:
            parts.append(band_label(self.freq))
            if self.width:
                parts.append(f"{self.width} MHz")
            if self.rate:
                parts.append(f"{self.rate:g} Mbit/s")
            if self.signal is not None:
                parts.append(f"{self.signal} dBm")
        if self.usb_speed is not None:
            usb = f"usb {self.usb_speed}"
            if best_usb and best_usb != self.usb_speed:
                usb += f" (best {best_usb})"
            parts.append(usb)
        return " ".join(parts)


#: Grades, best first. `unknown` is a probe that could not run.
GRADES = (
    "healthy",
    "degraded",
    "dead_end",
    "wedged",
    "no_route",
    "connecting",
    "disconnected",
    "unavailable",
    "absent",
    "unknown",
)


def grade_of(probe: ProbeResult | None, info: DeviceInfo | None, routed: bool) -> str:
    """One word for where a device stands this cycle."""
    if probe is not None and probe.unavailable:
        return "unknown"
    if probe is not None and routed:
        if probe.healthy:
            return "healthy"
        if probe.wedged:
            return "wedged"
        if probe.dead_end:
            return "dead_end"
        return "degraded"
    if info is None:
        return "absent"
    if info.nm_state == "connected":
        return "no_route"
    if info.nm_state in ("connecting", "deactivating"):
        return "connecting"
    if info.nm_state == "unavailable":
        return "unavailable"
    return "disconnected"


def grade_rank(grade: str) -> int:
    return GRADES.index(grade) if grade in GRADES else len(GRADES)


# -- decision (pure) ---------------------------------------------------------


def evaluate(
    routes: list[Route],
    probes: dict[str, ProbeResult],
    state: State,
    policy: Policy = DEFAULT_POLICY,
    now: float | None = None,
    preferences: dict[str, Preference] | None = None,
    devices: dict[str, DeviceInfo] | None = None,
    routes_known: bool = True,
) -> list[Action]:
    """Decide what to do this cycle. No side effects.

    Counters in `state` are updated in place -- they are the memory of the
    running loop, not an output. `preferences` and `devices` are what
    `preferences()` and `observe_devices()` read this cycle; without them
    only the route-based rungs run.
    """
    now = time.time() if now is None else now
    actions: list[Action] = []
    prefs = preferences or {}
    devs = devices or {}
    state.decisions = []
    if not routes and not devs:
        return actions
    routed = {r.dev for r in routes}

    def note(dev: str, rung: str, text: str) -> None:
        """Why a rung looked at `dev` and did nothing; logged on change."""
        state.decisions.append((dev, rung, text))

    def reset_wait(dev: str, episode_start: float | None = None) -> float:
        last = state.last_reset.get(dev)
        if last is None:
            return 0.0
        limit = (
            policy.reset_floor_s
            if episode_start is not None and last < episode_start
            else policy.min_reset_interval_s
        )
        return max(0.0, limit - (now - last))

    def usb_wait(dev: str, episode_start: float | None = None) -> str:
        """Human wording of when the next USB reset may come."""
        if not policy.usb_reset_enabled:
            return "USB reset disabled"
        reset_at, usb_at = _repairs_in_episode(state, dev, episode_start)
        if reset_at is None and usb_at is None:
            return "USB reset after the first re-association"
        last_repair = max(reset_at or 0.0, usb_at or 0.0)
        attempt = state.usb_attempts.get(dev, 0) + 1
        left = usb_backoff(policy.usb_reset_schedule, attempt) - (now - last_repair)
        return f"USB reset attempt {attempt} in {max(0.0, left):.0f} s"

    healthy_devs = {
        dev for dev, p in probes.items() if p.healthy and dev not in state.demoted
    }
    # A failover target needs a TCP path to the upstream, not a perfect
    # probe: on 2026-09-14 00:46 the standby's 5 GHz link had just lost a
    # ping and a DNS reply while its TCP layer worked, "no healthy
    # alternative" blocked the failover, and the wedged active route kept
    # the traffic for four more minutes.
    usable_devs = {
        dev
        for dev, p in probes.items()
        if p.layers.get("tcp") is True and dev not in state.demoted
    }

    # Repairs the loop is running right now (outside the lock, so the fast
    # path can act meanwhile): no rung touches those devices. A marker
    # older than any command's timeout is a leftover.
    for dev, started in list(state.repair_in_flight.items()):
        if now - started > 180.0:
            state.repair_in_flight.pop(dev, None)

    def in_flight(dev: str) -> bool:
        return dev in state.repair_in_flight

    def bump(dev: str) -> int:
        """Count a failing cycle; a streak that starts now is a new episode."""
        state.failures[dev] = state.failures.get(dev, 0) + 1
        if state.failures[dev] == 1:
            state.failure_since[dev] = now
        return state.failures[dev]

    def clear(dev: str) -> None:
        state.failures[dev] = 0
        state.failure_since.pop(dev, None)

    # A device that changes role (active <-> standby, or gains/loses its
    # route) starts its failure count over: the count meant something
    # else in the old role.
    top = uplink.active_route(routes) if routes else None
    for dev in set(routed) | set(devs) | set(state.last_role):
        role = (
            "active"
            if top is not None and dev == top.dev
            else "standby"
            if dev in routed
            else "none"
        )
        if state.last_role.get(dev) != role:
            clear(dev)
            state.last_role[dev] = role

    def usb_eligible(dev: str) -> bool:
        # Without any device observation (tests, a failing nmcli) let
        # usb_reset_device decide; with one, only a listed USB adapter.
        if not devs:
            return True
        info = devs.get(dev)
        return info is not None and info.usb_id in policy.usb_reset_ids

    def reload_eligible(dev: str) -> bool:
        info = devs.get(dev)
        return policy.driver_reload_enabled and info is not None and info.usb_id is None

    # -- the route traffic currently takes
    active = uplink.active_route(routes) if routes else None
    active_probe = probes.get(active.dev) if active is not None else None
    active_healthy = active_probe is not None and active_probe.healthy
    if active is not None and active.dev not in state.demoted:
        probe = active_probe
        if probe is not None and probe.dead_end:
            count = bump(active.dev)
            streak = state.failure_since.get(active.dev)
            what = "wedged" if probe.wedged else "no TCP path"
            if count < policy.failures_before_action:
                note(
                    active.dev,
                    "failover",
                    f"{what} {count}/{policy.failures_before_action} cycles",
                )
            else:
                alternatives = usable_devs - {active.dev}
                if not alternatives:
                    note(
                        active.dev,
                        "failover",
                        f"{what} for {count} cycles; no usable alternative (none with a TCP path)"
                        + (
                            "; the WAN is suspected, radios left alone"
                            if not probe.wedged
                            else f"; in-place reset in {reset_wait(active.dev, streak):.0f} s, "
                            f"{usb_wait(active.dev, streak)}"
                        ),
                    )
                if alternatives:
                    # The kernel will pick the lowest metric among what is
                    # left; name that one (three radios now: 100/300/600).
                    by_metric = {r.dev: r.metric for r in routes}
                    alt = min(
                        alternatives, key=lambda d: (by_metric.get(d, 1 << 30), d)
                    )
                    actions.append(
                        Action(
                            "demote",
                            active.dev,
                            f"{what} for {count} cycles; {alt} "
                            f"{'is healthy' if alt in healthy_devs else 'has a TCP path'}"
                            f" (metric {by_metric.get(alt, '?')})",
                            metric=policy.demoted_metric,
                        )
                    )
                    if policy.reset_after_failover and _may_reset(
                        state, active.dev, policy, now, episode_start=now
                    ):
                        actions.append(
                            Action("reset", active.dev, "repair after failover")
                        )
                elif not probe.wedged:
                    # The gateway answers and nothing beyond it does, on the
                    # only route: that is the WAN or the upstream, not this
                    # host. Resetting radios would only add an outage.
                    pass
                elif in_flight(active.dev):
                    note(
                        active.dev,
                        "failover",
                        f"{what} for {count} cycles; repair in flight",
                    )
                elif _may_reset(state, active.dev, policy, now, streak):
                    # Nothing to fail over to: repair in place is the only move.
                    actions.append(
                        Action(
                            "reset",
                            active.dev,
                            f"wedged for {count} cycles; no usable alternative",
                        )
                    )
                elif usb_eligible(active.dev) and _usb_reset_due(
                    state, active.dev, policy, now, episode_start=streak
                ):
                    # Still wedged after the in-place re-association and with
                    # nowhere to fail over to (2026-09-13: wlan0 dead in its
                    # metal case): escalate to the USB reset on the same
                    # schedule. The device is carrying nothing, so the ~10 s
                    # it takes to come back costs nothing.
                    attempt = state.usb_attempts.get(active.dev, 0) + 1
                    actions.append(
                        Action(
                            "usb_reset",
                            active.dev,
                            f"wedged for {count} cycles, no usable alternative; "
                            f"USB reset attempt {attempt}",
                        )
                    )
                elif reload_eligible(active.dev) and _reload_due(
                    state, active.dev, policy, now, episode_start=streak
                ):
                    attempt = state.reload_attempts.get(active.dev, 0) + 1
                    actions.append(
                        Action(
                            "reload",
                            active.dev,
                            f"wedged for {count} cycles, no usable alternative; "
                            f"driver reload attempt {attempt}",
                        )
                    )
        else:
            clear(active.dev)
            state.usb_attempts.pop(active.dev, None)
            state.reload_attempts.pop(active.dev, None)

    # -- standby routes: keep the lifeline alive while nothing depends on it.
    #    A standby with a gateway but no TCP path is only "broken" when the
    #    active route proves the upstream works; otherwise it is the WAN.
    for route in routes:
        dev = route.dev
        if dev in state.demoted or (active is not None and dev == active.dev):
            continue
        probe = probes.get(dev)
        if probe is None:
            continue
        broken = probe.wedged or (probe.dead_end and active_healthy)
        if not broken:
            clear(dev)
            if probe.healthy:
                state.usb_attempts.pop(dev, None)
                state.reload_attempts.pop(dev, None)
            continue
        count = bump(dev)
        streak = state.failure_since.get(dev)
        what = "wedged" if probe.wedged else "no TCP path"
        if not policy.standby_repair or count < policy.failures_before_action:
            note(
                dev, "standby", f"{what} {count}/{policy.failures_before_action} cycles"
            )
            continue
        if in_flight(dev):
            note(dev, "standby", f"{what} for {count} cycles; repair in flight")
            continue
        if not _may_reset(state, dev, policy, now, streak):
            note(
                dev,
                "standby",
                f"{what} for {count} cycles; re-activation in {reset_wait(dev, streak):.0f} s, "
                f"{usb_wait(dev, streak)}",
            )
        if _may_reset(state, dev, policy, now, streak):
            pref = prefs.get(dev)
            target = pref.target if pref is not None and pref.visible else None
            actions.append(
                Action(
                    "reset",
                    dev,
                    f"standby {what} for {count} cycles"
                    + (f"; moving to {target}" if target else ""),
                    profile=target,
                    tag="standby",
                )
            )
        elif (
            probe.wedged
            and usb_eligible(dev)
            and _usb_reset_due(state, dev, policy, now, episode_start=streak)
        ):
            # Re-association did not revive it; it carries nothing, so the
            # software replug costs nothing.
            attempt = state.usb_attempts.get(dev, 0) + 1
            actions.append(
                Action(
                    "usb_reset",
                    dev,
                    f"standby still wedged after re-activation; USB reset attempt {attempt}",
                )
            )
        elif (
            probe.wedged
            and reload_eligible(dev)
            and _reload_due(state, dev, policy, now, episode_start=streak)
        ):
            attempt = state.reload_attempts.get(dev, 0) + 1
            actions.append(
                Action(
                    "reload",
                    dev,
                    f"standby still wedged after re-activation; driver reload attempt {attempt}",
                )
            )

    # -- devices without a route: the lifeline that is not even there.
    #    They carry nothing, so a repair costs nothing; the thresholds only
    #    keep the loop from stepping on NetworkManager's own reconnect.
    #    "Connected without a route" is different: the device may well be
    #    carrying traffic through a route the loop could not read, so it
    #    needs a readable table, the longer threshold, one device per
    #    cycle, and the gentle repair first (apply_action reapplies the
    #    profile before it re-associates). On 2026-09-13 23:49 a version
    #    without these guards re-activated both radios at once.
    no_route_acted = False
    for dev in sorted(devs):
        info = devs[dev]
        if dev in routed or info.nm_state == "unmanaged":
            state.down_cycles[dev] = 0
            continue
        state.down_cycles[dev] = state.down_cycles.get(dev, 0) + 1
        count = state.down_cycles[dev]
        threshold = (
            policy.connecting_cycles_before_action
            if info.nm_state in ("connecting", "deactivating", "connected")
            else policy.failures_before_action
        )
        what = (
            "connected without a default route"
            if info.nm_state == "connected"
            else info.nm_state
        )
        if not policy.down_repair or count < threshold:
            note(dev, "down", f"{what} {count}/{threshold} cycles")
            continue
        pref = prefs.get(dev)
        target = pref.target if pref is not None and pref.visible else None
        usb_adapter = info.usb_id is not None and info.usb_id in policy.usb_reset_ids
        if in_flight(dev):
            note(dev, "down", f"{what} for {count} cycles; repair in flight")
            continue
        if info.nm_state == "connected":
            # Associated with an address but no default route (a DHCP offer
            # without a router, a route someone deleted): re-applying the
            # profile re-runs the IP configuration; re-association only if
            # that fails. A profile that is not meant to carry a default
            # route is left alone by apply_action.
            if not routes_known:
                note(
                    dev,
                    "down",
                    f"{what} for {count} cycles; the route table could not be read",
                )
                continue
            if no_route_acted:
                note(dev, "down", f"{what} for {count} cycles; one device per cycle")
                continue
            if _may_reset(state, dev, policy, now):
                no_route_acted = True
                actions.append(
                    Action(
                        "reset",
                        dev,
                        f"{what} for {count} cycles",
                        profile=target or info.profile or None,
                        tag="no_route",
                    )
                )
            else:
                note(
                    dev,
                    "down",
                    f"{what} for {count} cycles; re-activation in {reset_wait(dev):.0f} s",
                )
            continue
        if target:
            if _may_reset(state, dev, policy, now):
                actions.append(
                    Action(
                        "reset",
                        dev,
                        f"{info.nm_state} for {count} cycles; {target} is in range",
                        profile=target,
                        tag="down",
                    )
                )
            elif usb_adapter and _usb_reset_due(state, dev, policy, now):
                # The re-activation did not bring it back: the schedule.
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        (
                            f"{info.nm_state} for {count} cycles after re-activation; "
                            f"USB reset attempt {attempt}"
                        ),
                    )
                )
            elif reload_eligible(dev) and _reload_due(state, dev, policy, now):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        (
                            f"{info.nm_state} for {count} cycles after re-activation; "
                            f"driver reload attempt {attempt}"
                        ),
                    )
                )
            else:
                note(
                    dev,
                    "down",
                    f"{info.nm_state} for {count} cycles, {target} in range; "
                    f"re-activation in {reset_wait(dev):.0f} s"
                    + (f", {usb_wait(dev)}" if usb_adapter else ""),
                )
        elif info.nm_state == "unavailable":
            # No radio to speak of (driver, firmware, rfkill): re-enumerate
            # the adapter, or reload the built-in radio's driver if allowed.
            if usb_adapter and _usb_reset_due(state, dev, policy, now, first_ok=True):
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        f"unavailable for {count} cycles; USB reset attempt {attempt}",
                    )
                )
            elif reload_eligible(dev) and _reload_due(
                state, dev, policy, now, first_ok=True
            ):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        f"unavailable for {count} cycles; driver reload attempt {attempt}",
                    )
                )
        else:
            note(dev, "down", f"{info.nm_state} for {count} cycles; nothing in range")

    # -- demoted routes: restore once they carry traffic again -- with a
    #    hold-down that grows with every wedge inside the flap window and
    #    the fast path's word that it has been passing; until then,
    #    re-associate first, then escalate to a USB re-enumeration on the
    #    schedule. Every wait counts from a repair in *this* episode.
    for dev, demotion in list(state.demoted.items()):
        probe = probes.get(dev)
        episode = demotion.since_ts or None
        if probe is not None and probe.healthy:
            state.successes[dev] = state.successes.get(dev, 0) + 1
            count = state.successes[dev]
            recent = len(recent_wedges(state, dev, policy, now))
            needed = restore_needed(recent, policy)
            hold = (
                f" (hold-down {needed}: {recent} wedges in the last "
                f"{policy.flap_window_s / 60:.0f} min)"
                if needed > policy.successes_before_restore
                else ""
            )
            fast_fail = state.fast_demoted_last_fail.get(dev, 0.0)
            fast_ago = now - fast_fail if fast_fail else None
            fast_quiet = (
                policy.fast_interval_s <= 0
                or fast_ago is None
                or fast_ago >= policy.restore_fast_quiet_s
            )
            if count >= needed and fast_quiet:
                actions.append(
                    Action(
                        "restore",
                        dev,
                        f"healthy for {count} cycles{hold}",
                        metric=demotion.original_metric,
                    )
                )
            elif count >= needed:
                note(
                    dev,
                    "restore",
                    f"demoted ({demotion.kind}); healthy {count}/{needed} cycles but "
                    f"the fast path saw it fail {fast_ago:.0f} s ago; restore after "
                    f"{policy.restore_fast_quiet_s:.0f} s clean",
                )
            else:
                note(
                    dev,
                    "restore",
                    f"demoted ({demotion.kind}); healthy {count}/{needed} cycles{hold}",
                )
        else:
            state.successes[dev] = 0
            if probe is not None and not probe.unavailable:
                if demotion.kind == "preference":
                    left = max(0.0, policy.prefer_timeout_s - (now - demotion.since_ts))
                    note(
                        dev,
                        "restore",
                        f"demoted (preference move to {demotion.target}) and "
                        f"{'wedged' if probe.wedged else 'not healthy'}; no USB "
                        f"escalation for a move; back to {demotion.profile} in "
                        f"{max(left, reset_wait(dev, episode)):.0f} s",
                    )
                else:
                    note(
                        dev,
                        "restore",
                        f"demoted ({demotion.kind}) and {'wedged' if probe.wedged else 'not healthy'}; "
                        f"re-association in {reset_wait(dev, episode):.0f} s, "
                        f"{usb_wait(dev, episode)}",
                    )
            # `probe is None` means the device has no route right now -- it
            # is most likely mid-re-enumeration; never stack a reset on that.
            # An unavailable probe is no verdict at all.
            if probe is None or probe.unavailable:
                continue
            if in_flight(dev):
                note(dev, "restore", f"demoted ({demotion.kind}); repair in flight")
                continue
            if demotion.kind == "preference":
                # A self-inflicted change gets no USB escalation: if the
                # better profile has not come up, go back to the one that
                # worked (NetworkManager usually does this by itself).
                if (now - demotion.since_ts) >= policy.prefer_timeout_s and _may_reset(
                    state, dev, policy, now, episode
                ):
                    actions.append(
                        Action(
                            "reset",
                            dev,
                            f"{demotion.target} did not come up within "
                            f"{int(policy.prefer_timeout_s)} s; back to {demotion.profile}",
                            profile=demotion.profile,
                            tag="fallback",
                        )
                    )
                continue
            if not probe.wedged:
                # Associated, gateway answers, still no TCP path: nothing a
                # re-enumeration would fix; re-associate on the rate limit
                # and otherwise wait for it to pass the probes.
                if _may_reset(state, dev, policy, now, episode):
                    actions.append(
                        Action("reset", dev, "demoted and still without a TCP path")
                    )
                continue
            reset_at, _usb_at = _repairs_in_episode(state, dev, episode)
            if reset_at is None and _may_reset(state, dev, policy, now, episode):
                # The gentle repair first, in every episode: the failover's
                # own re-association may have been skipped by the floor.
                actions.append(
                    Action(
                        "reset",
                        dev,
                        "demoted and wedged; re-association before the USB schedule",
                    )
                )
            elif usb_eligible(dev) and _usb_reset_due(
                state, dev, policy, now, episode_start=episode
            ):
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        f"still wedged after this episode's re-association; "
                        f"USB reset attempt {attempt}",
                    )
                )
            elif reload_eligible(dev) and _reload_due(
                state, dev, policy, now, episode_start=episode
            ):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        f"still wedged after this episode's re-association; "
                        f"driver reload attempt {attempt}",
                    )
                )

    # -- voluntary repairs: one per cycle, never over a demotion in flight,
    #    never on a device that is not healthy right now. Level first (a USB
    #    reset also re-picks the profile), then the profile preference.
    acted = False

    # -- USB link level: back to the best speed this adapter has shown
    for dev in sorted(devs):
        info = devs[dev]
        if info.usb_speed is None:
            continue
        best = state.usb_best_speed.get(dev, 0)
        if info.usb_speed >= best:
            if info.usb_speed > best:
                state.usb_best_speed[dev] = info.usb_speed
            since = state.usb_best_since.setdefault(dev, now)
            if (
                dev in state.usb_speed_attempts
                and now - since >= policy.usb_speed_hold_s
            ):
                state.usb_speed_attempts.pop(dev, None)
                state.last_usb_speed_reset.pop(dev, None)
            continue
        state.usb_best_since.pop(dev, None)
        attempts = state.usb_speed_attempts.get(dev, 0)
        if attempts >= policy.usb_speed_give_up:
            # The port, cable or driver will not give more right now: accept
            # this as the level until the device shows the higher one again.
            state.usb_best_speed[dev] = info.usb_speed
            state.usb_speed_attempts.pop(dev, None)
            state.last_usb_speed_reset.pop(dev, None)
            continue
        if (
            not policy.usb_speed_repair
            or acted
            or state.demoted
            or state.repair_in_flight
            or dev not in routed
            or not _usb_speed_due(state, dev, policy, now)
        ):
            why = (
                "repair disabled"
                if not policy.usb_speed_repair
                else "another action this cycle"
                if acted
                else "a demotion is in flight"
                if state.demoted
                else "a repair is in flight"
                if state.repair_in_flight
                else "no route"
                if dev not in routed
                else "waiting for the schedule"
            )
            note(dev, "usb_level", f"link {info.usb_speed} Mbit/s, best {best}; {why}")
            continue
        probe = probes.get(dev)
        if probe is None or not probe.healthy:
            note(
                dev,
                "usb_level",
                f"link {info.usb_speed} Mbit/s, best {best}; device not healthy",
            )
            continue
        if active is not None and dev == active.dev:
            alternatives = healthy_devs - {dev}
            if not alternatives:
                note(
                    dev,
                    "usb_level",
                    f"link {info.usb_speed} Mbit/s, best {best}; no healthy alternative",
                )
                continue  # never take the only working uplink down for this
            actions.append(
                Action(
                    "demote",
                    dev,
                    f"USB link at {info.usb_speed} Mbit/s, best seen {best} "
                    f"(reset attempt {attempts + 1}); {min(alternatives)} is healthy",
                    metric=policy.demoted_metric,
                    tag="usb_speed",
                )
            )
        actions.append(
            Action(
                "usb_reset",
                dev,
                f"USB link at {info.usb_speed} Mbit/s, best seen {best}; "
                f"reset attempt {attempts + 1}",
                tag="usb_speed",
            )
        )
        acted = True

    # -- profile preference
    if policy.prefer_enabled:
        for dev in sorted(prefs):
            pref = prefs[dev]
            if pref.target is None:
                since = state.preferred_since.setdefault(dev, now)
                if dev in state.prefer_attempts and now - since >= policy.prefer_hold_s:
                    state.prefer_attempts.pop(dev, None)
                    state.last_prefer.pop(dev, None)
                continue
            state.preferred_since.pop(dev, None)
            probe = probes.get(dev)
            if (
                acted
                or state.demoted
                or state.repair_in_flight
                or not pref.visible
                or probe is None
                or not probe.healthy
                or not _prefer_due(state, dev, policy, now)
            ):
                why = (
                    "another action this cycle"
                    if acted
                    else "a demotion is in flight"
                    if state.demoted
                    else "a repair is in flight"
                    if state.repair_in_flight
                    else "target not in range"
                    if not pref.visible
                    else "no route"
                    if probe is None
                    else "device not healthy"
                    if not probe.healthy
                    else "waiting for the schedule"
                )
                note(
                    dev,
                    "preference",
                    f"on {pref.current or 'no profile'}, {pref.target} preferred; {why}",
                )
                continue
            attempt = state.prefer_attempts.get(dev, 0) + 1
            if active is not None and dev == active.dev:
                alternatives = healthy_devs - {dev}
                if not alternatives:
                    note(
                        dev,
                        "preference",
                        f"{pref.target} preferred; no healthy alternative",
                    )
                    continue  # never take the only working uplink down for this
                actions.append(
                    Action(
                        "demote",
                        dev,
                        f"moving to preferred profile {pref.target} "
                        f"(attempt {attempt}); {min(alternatives)} is healthy",
                        metric=policy.demoted_metric,
                        profile=pref.target,
                        tag="preference",
                    )
                )
            actions.append(
                Action(
                    "reset",
                    dev,
                    f"activate preferred profile {pref.target} over {pref.current} "
                    f"(attempt {attempt})",
                    profile=pref.target,
                    tag="preference",
                )
            )
            acted = True
            break

    return actions


def _repairs_in_episode(
    state: State, dev: str, episode_start: float | None
) -> tuple[float | None, float | None]:
    """(last re-association, last USB reset) of `dev`, restricted to the
    current episode when one is given."""
    reset_at = state.last_reset.get(dev)
    usb_at = state.last_usb_reset.get(dev)
    if episode_start is not None:
        if reset_at is not None and reset_at < episode_start:
            reset_at = None
        if usb_at is not None and usb_at < episode_start:
            usb_at = None
    return reset_at, usb_at


def _usb_reset_due(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    first_ok: bool = False,
    episode_start: float | None = None,
) -> bool:
    """Has the schedule's wait elapsed since the last repair of `dev` in
    this episode?

    Attempt 1 counts from the tier-2 re-association, so the interface gets
    one minute to come back on its own before the first re-enumeration.
    Without a re-association in this episode there is nothing to escalate
    from: a repair from an earlier episode does not count (on 2026-09-14
    a second wedge minutes after the first went straight to a USB reset,
    logged "still unhealthy after re-association" with none made).
    """
    if not policy.usb_reset_enabled:
        return False
    reset_at, usb_at = _repairs_in_episode(state, dev, episode_start)
    if reset_at is None and usb_at is None:
        return first_ok
    last_repair = max(reset_at or 0.0, usb_at or 0.0)
    attempt = state.usb_attempts.get(dev, 0) + 1
    return (now - last_repair) >= usb_backoff(policy.usb_reset_schedule, attempt)


def _may_reset(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    episode_start: float | None = None,
) -> bool:
    """May `dev` be re-associated now?

    `min_reset_interval_s` paces repeats within one episode; the first
    re-association of a new episode (a demotion, or a failure streak that
    began after the last re-association) needs only `reset_floor_s`.
    """
    last = state.last_reset.get(dev)
    if last is None:
        return True
    if episode_start is not None and last < episode_start:
        return (now - last) >= policy.reset_floor_s
    return (now - last) >= policy.min_reset_interval_s


def recent_wedges(state: State, dev: str, policy: Policy, now: float) -> list[float]:
    """When `dev` was demoted for a wedge inside the flap window."""
    return [
        t for t in state.wedge_times.get(dev, []) if now - t <= policy.flap_window_s
    ]


def restore_needed(recent: int, policy: Policy) -> int:
    """Healthy cycles a demoted route needs before it is restored: the
    base, doubled for every earlier wedge inside the flap window (3, 6,
    12, 24 ...), capped at `restore_hold_max_cycles`."""
    base = policy.successes_before_restore
    if recent <= 1:
        return base
    return min(base * 2 ** (recent - 1), max(base, policy.restore_hold_max_cycles))


def _prefer_due(state: State, dev: str, policy: Policy, now: float) -> bool:
    """Has `prefer_schedule` elapsed since the last preference move?"""
    last = state.last_prefer.get(dev)
    if last is None:
        return True
    # The first move is immediate, so stage 1 of the schedule paces the
    # retries after it: with (3, 600) the gaps are 10 min, 10 min, 10 min.
    moves = max(1, state.prefer_attempts.get(dev, 0))
    return (now - last) >= usb_backoff(policy.prefer_schedule, moves)


def _reload_due(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    first_ok: bool = False,
    episode_start: float | None = None,
) -> bool:
    """Driver reloads pace themselves like USB resets, from the last repair
    in this episode."""
    if not policy.driver_reload_enabled:
        return False
    reset_at = state.last_reset.get(dev)
    reload_at = state.last_reload.get(dev)
    if episode_start is not None:
        if reset_at is not None and reset_at < episode_start:
            reset_at = None
        if reload_at is not None and reload_at < episode_start:
            reload_at = None
    if reset_at is None and reload_at is None:
        return first_ok
    last_repair = max(reset_at or 0.0, reload_at or 0.0)
    attempt = state.reload_attempts.get(dev, 0) + 1
    return (now - last_repair) >= usb_backoff(policy.usb_reset_schedule, attempt)


@dataclass(frozen=True, slots=True)
class ServiceObservation:
    """The two processes between the uplink and ChatGPT, as seen this cycle."""

    #: The MCP unit that is active, or None when none is (stopped on purpose).
    mcp_unit: str | None = None
    #: Does the server's HTTP endpoint answer at all? None when not probed.
    endpoint_ok: bool | None = None
    tunnel_active: bool = False
    #: Trailing `poll failed` lines in the tunnel log and when they began.
    poll_failures: int = 0
    poll_failing_since: float | None = None
    #: Epoch of the tunnel log's last line (reported, not acted on).
    poll_last: float | None = None
    #: Does the tunnel's health server answer? None when unknown.
    tunnel_health_ok: bool | None = None
    #: Epoch of the last command the tunnel forwarded to the server: a
    #: restart for socket affinity waits for a quiet moment.
    forwarded_last: float | None = None


def evaluate_services(
    obs: ServiceObservation, state: State, policy: Policy, now: float
) -> list[tuple[str, str]]:
    """Which units to restart this cycle, as (unit, reason). Pure.

    The server: its unit is active but the port does not answer for
    `service_failures_before_action` cycles. The tunnel: its poller has
    been failing for `tunnel_restart_after_s` while the active route has
    been healthy for as many cycles -- the 2026-09-12 shape where a
    process is alive and useless. Both rate-limited; a stopped unit is
    never started.
    """
    out: list[tuple[str, str]] = []
    if not policy.service_repair:
        return out

    def due(name: str) -> bool:
        last = state.last_service_restart.get(name)
        return last is None or (now - last) >= policy.service_restart_interval_s

    if obs.mcp_unit and obs.endpoint_ok is False:
        state.service_failures["mcp"] = state.service_failures.get("mcp", 0) + 1
        count = state.service_failures["mcp"]
        if count >= policy.service_failures_before_action and due("mcp"):
            out.append(
                (
                    obs.mcp_unit,
                    (
                        f"{policy.mcp_url} not answering for {count} cycles while "
                        f"{obs.mcp_unit} is active"
                    ),
                )
            )
    else:
        state.service_failures["mcp"] = 0

    failing = (
        obs.tunnel_active
        and obs.poll_failures >= policy.service_failures_before_action
        and obs.poll_failing_since is not None
        and (now - obs.poll_failing_since) >= policy.tunnel_restart_after_s
    )
    # A frozen tunnel: its health server stops answering. Counted per
    # cycle like the MCP endpoint; no uplink condition, the health port is
    # local.
    if obs.tunnel_active and obs.tunnel_health_ok is False:
        state.service_failures["tunnel_health"] = (
            state.service_failures.get("tunnel_health", 0) + 1
        )
        count = state.service_failures["tunnel_health"]
        if count >= policy.service_failures_before_action and due("tunnel"):
            out.append(
                (
                    policy.tunnel_unit,
                    (
                        f"tunnel health server not answering for {count} cycles "
                        f"while {policy.tunnel_unit} is active"
                    ),
                )
            )
            return out
    else:
        state.service_failures["tunnel_health"] = 0
    if failing:
        state.service_failures["tunnel"] = state.service_failures.get("tunnel", 0) + 1
        if state.uplink_ok_cycles >= policy.service_failures_before_action and due(
            "tunnel"
        ):
            since_fail = (
                obs.poll_failing_since if obs.poll_failing_since is not None else now
            )
            out.append(
                (
                    policy.tunnel_unit,
                    (
                        f"tunnel poll failing {obs.poll_failures} times running for "
                        f"{int(now - since_fail)} s while the uplink has been healthy for "
                        f"{state.uplink_ok_cycles} cycles"
                    ),
                )
            )
    else:
        state.service_failures["tunnel"] = 0
    return out


@dataclass(frozen=True, slots=True)
class SystemObservation:
    """NetworkManager and wpa_supplicant as seen this cycle."""

    nm_active: bool = True
    #: nmcli answered the device list (False: nothing came back).
    nm_responsive: bool = True
    supplicant_active: bool = True
    #: Some Wi-Fi device is "unavailable" (what a dead supplicant looks like).
    any_unavailable: bool = False


def evaluate_system(
    obs: SystemObservation, state: State, policy: Policy, now: float
) -> list[tuple[str, str]]:
    """Which system units to restart (unit, reason). Pure.

    NetworkManager inactive/failed, or active but answering nothing for
    `service_failures_before_action` cycles, is restarted -- nothing below
    it can act without it. wpa_supplicant inactive while a radio sits in
    "unavailable" is restarted (NetworkManager normally re-spawns it over
    D-Bus; this is the backstop). Both rate-limited.
    """
    out: list[tuple[str, str]] = []
    if not policy.system_service_repair:
        return out

    def due(name: str) -> bool:
        last = state.last_system_restart.get(name)
        return last is None or (now - last) >= policy.service_restart_interval_s

    if not obs.nm_active:
        # Not active includes "activating": an NM restarting on its own
        # gets the same patience as a silent one.
        state.nm_inactive_cycles += 1
        state.nm_unresponsive_cycles = 0
        count = state.nm_inactive_cycles
        if count >= policy.service_failures_before_action and due("nm"):
            out.append(
                (
                    policy.nm_unit,
                    f"NetworkManager not active for {count} cycles",
                )
            )
    elif not obs.nm_responsive:
        state.nm_inactive_cycles = 0
        state.nm_unresponsive_cycles += 1
        count = state.nm_unresponsive_cycles
        if count >= policy.service_failures_before_action and due("nm"):
            out.append(
                (policy.nm_unit, f"NetworkManager answered nothing for {count} cycles")
            )
    else:
        state.nm_unresponsive_cycles = 0
        state.nm_inactive_cycles = 0
    if (
        obs.nm_active
        and not obs.supplicant_active
        and obs.any_unavailable
        and due("supplicant")
    ):
        out.append(
            (
                policy.supplicant_unit,
                "wpa_supplicant is not active while a radio is unavailable",
            )
        )
    return out


def _usb_speed_due(state: State, dev: str, policy: Policy, now: float) -> bool:
    """Has `usb_speed_schedule` elapsed since the last link-level reset?"""
    last = state.last_usb_speed_reset.get(dev)
    if last is None:
        return True
    attempts = max(1, state.usb_speed_attempts.get(dev, 0))
    return (now - last) >= usb_backoff(policy.usb_speed_schedule, attempts)


# -- NetworkManager side effects ---------------------------------------------


def device_profiles(run: Run = _run) -> dict[str, str]:
    """device -> active NetworkManager profile name."""
    proc = run("nmcli", "-t", "-f", "DEVICE,CONNECTION", "device", "status")
    if proc.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        dev, _, conn = line.partition(":")
        if dev and conn and conn != "--":
            out[dev] = conn
    return out


def _split_terse(line: str) -> list[str]:
    """Fields of one `nmcli -t` line; nmcli escapes ':' and '\\' in values."""
    fields: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    fields.append("".join(current))
    return fields


@dataclass(frozen=True, slots=True)
class WifiProfile:
    name: str
    #: Device the profile is active on, or "".
    device: str
    autoconnect: bool
    priority: int


def wifi_profiles(run: Run = _run) -> list[WifiProfile]:
    """Every Wi-Fi profile NetworkManager has, with its autoconnect priority."""
    proc = run(
        "nmcli",
        "-t",
        "-f",
        "NAME,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY",
        "connection",
        "show",
    )
    if proc.returncode != 0:
        return []
    out: list[WifiProfile] = []
    for line in proc.stdout.splitlines():
        fields = _split_terse(line)
        if len(fields) < 5 or fields[1] != "802-11-wireless":
            continue
        name, _, device, auto, prio = fields[:5]
        try:
            priority = int(prio)
        except ValueError:
            priority = 0
        out.append(WifiProfile(name, device, auto == "yes", priority))
    return out


def profile_details(name: str, run: Run = _run) -> tuple[str, str]:
    """(interface-name, SSID) of a Wi-Fi profile; "" where unset."""
    proc = run(
        "nmcli",
        "-t",
        "-g",
        "connection.interface-name,802-11-wireless.ssid",
        "connection",
        "show",
        name,
    )
    if proc.returncode != 0:
        return "", ""
    lines = proc.stdout.splitlines()
    iface = lines[0].strip() if lines else ""
    ssid = lines[1].strip() if len(lines) > 1 else ""
    return iface, ssid


def profile_metric(name: str, run: Run = _run) -> int | None:
    """A profile's ipv4.route-metric (-1 = NetworkManager's default)."""
    proc = run("nmcli", "-g", "ipv4.route-metric", "connection", "show", name)
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def visible_ssids(dev: str, run: Run = _run, rescan: bool = False) -> set[str]:
    """SSIDs in the device's scan results. `rescan` asks for a fresh scan:
    a few seconds, and a brief off-channel gap on a connected device, so
    the loop does it only on `prefer_check_interval_s`."""
    proc = run(
        "nmcli",
        "-t",
        "-f",
        "SSID",
        "device",
        "wifi",
        "list",
        "ifname",
        dev,
        "--rescan",
        "yes" if rescan else "no",
        timeout=60.0,
    )
    seen: set[str] = set()
    if proc.returncode == 0:
        seen = {
            _split_terse(line)[0] for line in proc.stdout.splitlines() if line.strip()
        }
    if rescan:
        # NetworkManager's own rescan on the built-in radio (brcmfmac) did
        # not list the 2.4 GHz network twice in a row on 2026-09-13 while a
        # full scan through nl80211 did, and NM's list carried it right
        # after. So a requested rescan also asks the driver directly (root
        # through `sudo -n`, like the USB reset) and merges the SSIDs.
        proc = run("sudo", "-n", "iw", "dev", dev, "scan", timeout=60.0)
        if proc.returncode == 0:
            for raw in proc.stdout.splitlines():
                line = raw.strip()
                if line.startswith("SSID:"):
                    seen.add(line[5:].strip())
    return seen


def wifi_link_freq(dev: str, run: Run = _run) -> int | None:
    """MHz of the device's current association (`iw dev <dev> link`)."""
    proc = run("iw", "dev", dev, "link")
    if proc.returncode != 0:
        return None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if line.startswith("freq:"):
            try:
                return int(float(line.split(":", 1)[1].strip()))
            except ValueError:
                return None
    return None


def band_label(freq: int | None) -> str:
    if freq is None:
        return "?"
    if freq >= 5925:
        return "6 GHz"
    if freq >= 4900:
        return "5 GHz"
    return "2.4 GHz"


def nm_devices(run: Run = _run) -> dict[str, tuple[str, str]]:
    """Wi-Fi devices NetworkManager manages: dev -> (state, active profile).
    P2P device entries are skipped."""
    proc = run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
    if proc.returncode != 0:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        fields = _split_terse(line)
        if len(fields) < 4 or fields[1] != "wifi":
            continue
        nm_state = fields[2].split(" ", 1)[0]  # "connected (externally)"
        profile = fields[3] if fields[3] != "--" else ""
        out[fields[0]] = (nm_state, profile)
    return out


def usb_speed_of(node: str) -> int | None:
    """Negotiated USB link speed in Mbit/s (sysfs `speed`)."""
    try:
        return int((USB_DEVICES / node / "speed").read_text().strip())
    except (OSError, ValueError):
        return None


def wifi_link_info(
    dev: str, run: Run = _run
) -> tuple[int | None, int | None, float | None, int | None]:
    """(freq MHz, width MHz, tx rate Mbit/s, signal dBm) of the association."""
    freq = width = signal = None
    rate = None
    proc = run("iw", "dev", dev, "link")
    if proc.returncode == 0:
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            try:
                if line.startswith("freq:"):
                    freq = int(float(line.split(":", 1)[1].strip()))
                elif line.startswith("signal:"):
                    signal = int(line.split(":", 1)[1].split()[0])
                elif line.startswith("tx bitrate:"):
                    rate = float(line.split(":", 1)[1].split()[0])
            except (ValueError, IndexError):
                continue
    proc = run("iw", "dev", dev, "info")
    if proc.returncode == 0:
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if "width:" in line:
                try:
                    width = int(line.split("width:", 1)[1].split()[0])
                except (ValueError, IndexError):
                    width = None
    return freq, width, rate, signal


def observe_devices(
    run: Run = _run, usb_ids: Collection[str] = ()
) -> dict[str, DeviceInfo]:
    """Every managed Wi-Fi device with its state and level facts."""
    out: dict[str, DeviceInfo] = {}
    for dev, (nm_state, profile) in nm_devices(run).items():
        node, usb_id = usb_node_of(dev)
        speed = usb_speed_of(node) if node and usb_id in usb_ids else None
        freq = width = signal = None
        rate = None
        if nm_state in ("connected", "connecting"):
            freq, width, rate, signal = wifi_link_info(dev, run)
        out[dev] = DeviceInfo(
            dev, nm_state, profile, usb_id, speed, freq, width, rate, signal
        )
    return out


def driver_of(dev: str) -> tuple[str | None, str | None]:
    """(sysfs device name, driver directory) behind a network interface."""
    try:
        device_dir = (NET_CLASS / dev / "device").resolve()
        driver_dir = (device_dir / "driver").resolve()
    except OSError:
        return None, None
    if not driver_dir.is_dir():
        return device_dir.name, None
    return device_dir.name, str(driver_dir)


SYS_MODULE = Path("/sys/module")


def driver_module_of(dev: str) -> tuple[str | None, list[str]]:
    """(kernel module of the interface's driver, modules that hold it).

    The holders must be unloaded first: on the Pi 5 the built-in radio's
    brcmfmac is held by brcmfmac_cyw.
    """
    _, driver_dir = driver_of(dev)
    if driver_dir is None:
        return None, []
    try:
        module = (Path(driver_dir) / "module").resolve().name
    except OSError:
        return None, []
    holders_dir = SYS_MODULE / module / "holders"
    holders: list[str] = []
    if holders_dir.is_dir():
        holders = sorted(p.name for p in holders_dir.iterdir())
    return module, holders


def driver_reload(dev: str, run: Run = _run) -> tuple[bool, str]:
    """Unload and reload the interface's driver module, as root via
    `sudo -n`: the non-USB cousin of the USB reset. Tested on the Pi 5's
    built-in radio 2026-09-13: a sysfs unbind/bind of the SDIO function
    left the firmware bus down ("bus is down", bind -EIO) and the radio
    gone; `modprobe -r brcmfmac_cyw brcmfmac` then `modprobe brcmfmac`
    brought wlan0 back in about ten seconds. Refuses a USB device -- that
    path has its own, better-tested rung."""
    _, usb_id = usb_node_of(dev)
    if usb_id is not None:
        return False, f"{dev} is a USB device ({usb_id}); use the USB reset"
    module, holders = driver_module_of(dev)
    if module is None:
        return False, f"{dev}: no driver module in sysfs"
    unload = " ".join(holders + [module])
    script = f"modprobe -r {unload} && modprobe {module}"
    proc = run("sudo", "-n", "sh", "-c", script, timeout=120.0)
    if proc.returncode != 0:
        return (
            False,
            f"reload of {module} failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )
    return True, f"reloaded {module}" + (
        f" (after {', '.join(holders)})" if holders else ""
    )


def unit_active(unit: str, run: Run = _run) -> bool:
    proc = run("systemctl", "--user", "is-active", unit)
    return proc.stdout.strip() == "active"


def http_alive(url: str, timeout: float = 5.0) -> bool:
    """Does anything answer HTTP at `url`? Any status counts (401 is the
    server refusing an unauthenticated request, which is alive)."""
    try:
        # The URL is the local server's, from the configuration, never user input.
        urllib.request.urlopen(url, timeout=timeout)  # nosec B310
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return True


def _rfc3339_epoch(stamp: str) -> float | None:
    """Epoch seconds of an RFC 3339 stamp with any fractional precision."""
    if not stamp:
        return None
    head, sep, rest = stamp.partition(".")
    if sep:
        digits = ""
        i = 0
        while i < len(rest) and rest[i].isdigit():
            digits += rest[i]
            i += 1
        stamp = f"{head}.{(digits + '000000')[:6]}{rest[i:]}"
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def observe_services(
    policy: Policy,
    run: Run = _run,
    alive: Callable[[str], bool] = http_alive,
) -> ServiceObservation:
    """Unit states, the server endpoint, and the tunnel's own log."""
    mcp_unit = next((u for u in policy.mcp_units if unit_active(u, run)), None)
    endpoint_ok = alive(policy.mcp_url) if mcp_unit else None
    tunnel_active = unit_active(policy.tunnel_unit, run)
    failures, since, last, forwarded = 0, None, None, None
    if policy.tunnel_log is not None and policy.tunnel_log.exists():
        from binnacle.doctor import scan_tunnel_log

        status = scan_tunnel_log(policy.tunnel_log)
        failures = status.trailing
        since = _rfc3339_epoch(status.first_failure) if failures else None
        last = _rfc3339_epoch(status.last_time)
        forwarded = _rfc3339_epoch(status.last_forwarded)
    health_ok: bool | None = None
    if tunnel_active and policy.tunnel_health_url_file is not None:
        try:
            url = policy.tunnel_health_url_file.read_text(encoding="utf-8").strip()
        except OSError:
            url = ""
        if url.startswith("http"):
            health_ok = alive(url)
    return ServiceObservation(
        mcp_unit,
        endpoint_ok,
        tunnel_active,
        failures,
        since,
        last,
        health_ok,
        forwarded_last=forwarded,
    )


def system_unit_active(unit: str, run: Run = _run) -> bool:
    proc = run("systemctl", "is-active", unit)
    return proc.stdout.strip() == "active"


def nm_answers(run: Run = _run) -> bool:
    """Does nmcli get an answer from NetworkManager at all? (An empty
    device list is an answer; a timeout or a D-Bus error is not.)"""
    proc = run("nmcli", "-t", "-g", "STATE", "general")
    return proc.returncode == 0


def observe_system(
    policy: Policy, devices: dict[str, DeviceInfo], nm_answered: bool, run: Run = _run
) -> SystemObservation:
    return SystemObservation(
        nm_active=system_unit_active(policy.nm_unit, run),
        nm_responsive=nm_answered,
        supplicant_active=system_unit_active(policy.supplicant_unit, run),
        any_unavailable=any(d.nm_state == "unavailable" for d in devices.values()),
    )


def host_health(run: Run = _run) -> dict[str, str]:
    """Power and thermal flags from the firmware (`vcgencmd`), where
    available: under-voltage is the classic cause of USB adapters going
    quiet. Empty on a host without the tool."""
    out: dict[str, str] = {}
    proc = run("vcgencmd", "get_throttled")
    if proc.returncode == 0 and "=" in proc.stdout:
        raw = proc.stdout.strip().split("=", 1)[1]
        out["throttled"] = raw
        try:
            bits = int(raw, 16)
        except ValueError:
            bits = 0
        flags = []
        for bit, name in (
            (0, "under-voltage now"),
            (1, "arm frequency capped now"),
            (2, "throttled now"),
            (3, "soft temperature limit now"),
            (16, "under-voltage occurred"),
            (17, "arm frequency capped occurred"),
            (18, "throttled occurred"),
            (19, "soft temperature limit occurred"),
        ):
            if bits & (1 << bit):
                flags.append(name)
        out["flags"] = ", ".join(flags) or "none"
    proc = run("vcgencmd", "measure_temp")
    if proc.returncode == 0 and "=" in proc.stdout:
        out["temp"] = proc.stdout.strip().split("=", 1)[1]
    return out


def module_params(module: str | None, names: Collection[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not module:
        return out
    for name in names:
        try:
            out[name] = (SYS_MODULE / module / "parameters" / name).read_text().strip()
        except OSError:
            continue
    return out


def inventory_line(
    dev: str,
    info: DeviceInfo,
    profiles: list[WifiProfile],
    run: Run,
    param_names: Collection[str],
) -> str:
    """One line that pins down what a device *is*: bus, id, node, link
    speed, driver, module and its parameters, and every profile bound to
    it with priority and metric. Logged at start and whenever it changes."""
    node, usb_id = usb_node_of(dev)
    _, driver_dir = driver_of(dev)
    driver = Path(driver_dir).name if driver_dir else "?"
    module, _ = driver_module_of(dev)
    params = module_params(module, param_names)
    bound = []
    for p in profiles:
        iface, _ = profile_details(p.name, run)
        if iface == dev or p.device == dev:
            metric = profile_metric(p.name, run)
            bound.append(
                f"{p.name}:prio{p.priority}:metric{metric}:{'auto' if p.autoconnect else 'manual'}"
            )
    kind = f"usb:{usb_id}@{node}:{info.usb_speed or '?'}Mbit" if usb_id else "builtin"
    return (
        f"kind={kind} driver={driver} module={module or '?'}"
        + (
            " params=" + ",".join(f"{k}={v}" for k, v in params.items())
            if params
            else ""
        )
        + f" profiles={';'.join(bound) or '-'}"
    )


def versions(run: Run = _run) -> dict[str, str]:
    """What is running: binnacle, Python, kernel, NetworkManager."""
    out: dict[str, str] = {"python": sys.version.split()[0]}
    try:
        from importlib.metadata import version as pkg_version

        out["binnacle"] = pkg_version("binnacle-mcp")
    except Exception:  # noqa: BLE001 - version is informational
        out["binnacle"] = "?"
    proc = run("uname", "-r")
    out["kernel"] = proc.stdout.strip() if proc.returncode == 0 else "?"
    proc = run("nmcli", "--version")
    out["networkmanager"] = (
        proc.stdout.strip().rsplit(" ", 1)[-1] if proc.returncode == 0 else "?"
    )
    return out


def pause_until(pause_file: Path | None) -> float | None:
    """Expiry epoch of an active pause, or None."""
    if pause_file is None or not pause_file.exists():
        return None
    try:
        until = float(pause_file.read_text().strip() or "0")
    except (OSError, ValueError):
        return None
    if until <= time.time():
        try:
            pause_file.unlink()
        except OSError:
            pass
        return None
    return until


def stranded_metrics(state: State, policy: Policy, run: Run = _run) -> dict[str, str]:
    """Profiles sitting at the demoted metric with no demotion on record
    (a lost or corrupt state file would leave the adapter stranded)."""
    covered: set[str] = set()
    for d in state.demoted.values():
        covered.add(d.profile)
        covered.update(d.others)
        if d.target:
            covered.add(d.target)
    out: dict[str, str] = {}
    for p in wifi_profiles(run):
        if p.name in covered:
            continue
        if profile_metric(p.name, run) == policy.demoted_metric:
            out[f"profile:{p.name}"] = (
                f"ipv4.route-metric is {policy.demoted_metric} with no demotion on "
                "record; the original is unknown -- set it by hand "
                f"(nmcli connection modify '{p.name}' ipv4.route-metric <n>)"
            )
    return out


def usb_adapters_without_netdev(usb_ids: Collection[str]) -> dict[str, str]:
    """USB nodes carrying a known adapter id that expose no network
    interface: the device is on the bus, the driver is not bound."""
    out: dict[str, str] = {}
    try:
        nodes = list(USB_DEVICES.iterdir())
    except OSError:
        return out
    for node in nodes:
        try:
            vendor = (node / "idVendor").read_text().strip()
            product = (node / "idProduct").read_text().strip()
        except OSError:
            continue
        usb_id = f"{vendor}:{product}"
        if usb_id not in usb_ids:
            continue
        has_net = any(
            (child / "net").is_dir() for child in node.iterdir() if child.is_dir()
        )
        if not has_net:
            out[f"usb:{node.name}"] = (
                f"adapter {usb_id} at {node.name} has no network interface "
                "(driver not bound)"
            )
    return out


def wifi_radio_enabled(run: Run = _run) -> bool | None:
    """NetworkManager's Wi-Fi radio switch (`nmcli radio wifi`); None when
    nmcli cannot answer."""
    proc = run("nmcli", "-t", "radio", "wifi")
    if proc.returncode != 0:
        return None
    answer = proc.stdout.strip().lower()
    if answer in ("enabled", "disabled"):
        return answer == "enabled"
    return None


def bound_profiles(dev: str, run: Run = _run) -> list[str]:
    """Autoconnect Wi-Fi profiles whose interface-name is `dev`."""
    names: list[str] = []
    for p in wifi_profiles(run):
        if not p.autoconnect or (p.device and p.device != dev):
            continue
        iface, _ = profile_details(p.name, run)
        if iface == dev:
            names.append(p.name)
    return names


def preferences(
    devs: Iterable[str], run: Run = _run, rescan_for: Collection[str] = ()
) -> dict[str, Preference]:
    """Per device: the active profile and, if NetworkManager holds a
    strictly higher autoconnect-priority profile bound to that device (or
    to no device), whether its network is in range. Profiles active on
    another device are never candidates. One `connection show` plus one
    lookup per higher-priority profile and one scan-list read per device
    that has one -- nothing when every device is on its best profile."""
    profiles = wifi_profiles(run)
    if not profiles:
        return {}
    active = {p.device: p for p in profiles if p.device}
    out: dict[str, Preference] = {}
    for dev in devs:
        current = active.get(dev)
        # No active profile (the device is down): every profile it could
        # use is a candidate, highest priority first.
        floor = current.priority if current is not None else None
        better = sorted(
            (
                p
                for p in profiles
                if p.autoconnect
                and not p.device
                and (floor is None or p.priority > floor)
            ),
            key=lambda p: p.priority,
            reverse=True,
        )
        candidates: list[tuple[WifiProfile, str]] = []
        for p in better:
            iface, ssid = profile_details(p.name, run)
            if iface in ("", dev) and ssid:
                candidates.append((p, ssid))
        current_name = current.name if current is not None else ""
        if not candidates:
            if current is not None:
                out[dev] = Preference(dev, current_name, None, False)
            continue
        seen = visible_ssids(dev, run, rescan=dev in rescan_for)
        in_range = next((p for p, ssid in candidates if ssid in seen), None)
        target = in_range or candidates[0][0]
        out[dev] = Preference(dev, current_name, target.name, in_range is not None)
    return out


def profile_never_default(name: str, run: Run = _run) -> bool:
    """`ipv4.never-default` of a profile: such a profile is not meant to
    carry a default route, so a missing route is not a fault."""
    proc = run("nmcli", "-g", "ipv4.never-default", "connection", "show", name)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "yes"


def _modify_metric(profile: str, metric: int, run: Run) -> bool:
    proc = run(
        "nmcli", "connection", "modify", profile, "ipv4.route-metric", str(metric)
    )
    if proc.returncode != 0:
        log.error(
            "event=metric_set_failed profile=%s metric=%s err=%s",
            profile,
            metric,
            proc.stderr.strip(),
        )
        return False
    return True


def _reapply(dev: str, run: Run) -> bool:
    proc = run("nmcli", "device", "reapply", dev)
    if proc.returncode != 0:
        log.error("event=reapply_failed dev=%s err=%s", dev, proc.stderr.strip())
        return False
    return True


def set_route_metric(profile: str, dev: str, metric: int, run: Run = _run) -> bool:
    """Set a profile's IPv4 route metric and apply it without re-associating."""
    return _modify_metric(profile, metric, run) and _reapply(dev, run)


def reset_device(dev: str, profile: str | None, run: Run = _run) -> bool:
    """Re-associate by re-activating the device's profile.

    `nmcli connection up` is the verb NetworkManager 1.52 has for this
    (there is no `device reconnect`; that call failed on 2026-09-12 20:32
    and left a wedged wlan1 untouched). It is also what the rfk healer uses.
    """
    if not profile:
        log.error("event=reset_skipped dev=%s reason=no_profile", dev)
        return False
    # `ifname` pins the device: a profile with no interface-name would
    # otherwise be free to come up on the other radio.
    proc = run("nmcli", "connection", "up", "id", profile, "ifname", dev, timeout=60.0)
    if proc.returncode != 0:
        log.error("event=reset_failed dev=%s err=%s", dev, proc.stderr.strip())
        return False
    return True


USB_DEVICES = Path("/sys/bus/usb/devices")
NET_CLASS = Path("/sys/class/net")


def usb_node_of(dev: str) -> tuple[str | None, str | None]:
    """(USB device node like '2-1', 'vendor:product') for a network interface.

    Resolved fresh on every call: across the mode-1 re-enumeration the same
    adapter moves from 1-1 to 2-1 and its device number changes.
    """
    try:
        interface_dir = (NET_CLASS / dev / "device").resolve()
    except OSError:
        return None, None
    node_dir = interface_dir.parent  # '<node>:1.0' -> '<node>'
    try:
        vendor = (node_dir / "idVendor").read_text().strip()
        product = (node_dir / "idProduct").read_text().strip()
    except OSError:
        return None, None
    return node_dir.name, f"{vendor}:{product}"


#: USBDEVFS_RESET = _IO('U', 20): a USB port reset through the devfs node.
USBDEVFS_RESET = 0x5514


def usb_devfs_path(node: str) -> Path | None:
    """/dev/bus/usb/BBB/DDD for a sysfs node; the device number changes on
    every re-enumeration, so this is read fresh, never cached."""
    try:
        bus = int((USB_DEVICES / node / "busnum").read_text())
        devnum = int((USB_DEVICES / node / "devnum").read_text())
    except (OSError, ValueError):
        return None
    return Path(f"/dev/bus/usb/{bus:03d}/{devnum:03d}")


def usb_reset_device(
    dev: str,
    policy: Policy = DEFAULT_POLICY,
    run: Run = _run,
    node_of: Callable[[str], tuple[str | None, str | None]] = usb_node_of,
    settle: Callable[[float], None] = time.sleep,
    method: str = "authorized",
    devfs_of: Callable[[str], Path | None] = usb_devfs_path,
) -> tuple[bool, str]:
    """Reset the interface's USB device: the software replug.

    `authorized`: writes 0 then 1 to the node's sysfs attribute -- the
    kernel deconfigures and reconfigures the device in place (same node),
    the driver reloads, NetworkManager reconnects. Proven on a real wedge
    2026-09-12 21:51. `port_reset`: USBDEVFS_RESET on the devfs node -- a
    bus-level port reset that re-enumerates the device, one step closer to
    a physical replug (still no VBUS drop). Both run as root via `sudo -n`,
    which this host grants without a password. Refuses any node whose USB
    id is not in `policy.usb_reset_ids`, and any method not named in
    `policy.usb_reset_methods`.
    """
    node, usb_id = node_of(dev)
    if node is None or usb_id is None:
        return False, f"{dev} has no resolvable USB node"
    if usb_id not in policy.usb_reset_ids:
        return (
            False,
            f"refusing to reset {node}: USB id {usb_id} is not in {policy.usb_reset_ids}",
        )
    if method not in policy.usb_reset_methods:
        return False, f"unknown USB reset method {method!r}"
    if method == "port_reset":
        devfs = devfs_of(node)
        if devfs is None:
            return False, f"{node}: cannot read busnum/devnum for a port reset"
        script = (
            "import fcntl, os; "
            f"fd = os.open({str(devfs)!r}, os.O_WRONLY); "
            f"fcntl.ioctl(fd, {USBDEVFS_RESET}, 0); os.close(fd)"
        )
        proc = run("sudo", "-n", "python3", "-c", script, timeout=30.0)
        if proc.returncode != 0:
            return (
                False,
                f"USBDEVFS_RESET on {devfs} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )
        return True, f"port reset {node} via {devfs} ({usb_id})"
    authorized = USB_DEVICES / node / "authorized"
    for value in ("0", "1"):
        proc = run(
            "sudo", "-n", "sh", "-c", f"echo {value} > {authorized}", timeout=20.0
        )
        if proc.returncode != 0:
            return (
                False,
                f"write {value} to {authorized} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )
        if value == "0":
            settle(2.0)
    return True, f"re-initialised {node} via authorized ({usb_id})"


def apply_action(
    action: Action,
    routes: list[Route],
    state: State,
    run: Run = _run,
    now: float | None = None,
    policy: Policy = DEFAULT_POLICY,
) -> bool:
    """Carry out one action and record it in `state`.

    Every outcome is logged with the cycle number, what the device looked
    like before (`before=`), how long the commands took and the result.
    """
    now = time.time() if now is None else now
    profiles = device_profiles(run)
    n = state.cycle_n
    before = state.last_grade.get(action.dev, "-")
    started = time.perf_counter()

    def took() -> float:
        return (time.perf_counter() - started) * 1000

    if action.kind == "demote":
        profile = profiles.get(action.dev)
        route = next((r for r in routes if r.dev == action.dev), None)
        if profile is None or route is None:
            log.error("event=demote_skipped dev=%s reason=no_profile", action.dev)
            return False
        metric = action.metric or 900
        # Device-level: raise every profile bound to the device (and the
        # target of a preference move) first, so whatever NetworkManager
        # brings up after the repair still waits for the probes. No move
        # without knowing how to undo it.
        names = [n for n in bound_profiles(action.dev, run) if n != profile]
        if (
            action.tag == "preference"
            and action.profile
            and action.profile not in names
        ):
            names.append(action.profile)
        others: dict[str, int] = {}
        for name in names:
            original = profile_metric(name, run)
            if original is None:
                log.error(
                    "event=demote_skipped dev=%s profile=%s reason=metric_unknown",
                    action.dev,
                    name,
                )
                return False
            others[name] = original
        raised: list[str] = []
        for name in others:
            if not _modify_metric(name, metric, run):
                for done in raised:
                    _modify_metric(done, others[done], run)
                return False
            raised.append(name)
        if not set_route_metric(profile, action.dev, metric, run):
            # The modify may have landed before the reapply failed: put the
            # active profile back too, or it sits at 900 with no record.
            _modify_metric(profile, route.metric, run)
            for done in raised:
                _modify_metric(done, others[done], run)
            log.error(
                "event=demote_failed cycle=%s dev=%s profile=%s reverted=%s duration_ms=%.0f",
                n,
                action.dev,
                profile,
                ",".join(raised) or "-",
                took(),
            )
            return False
        kind = action.tag if action.tag in ("preference", "usb_speed") else "wedged"
        target = action.profile if action.tag == "preference" else ""
        state.demoted[action.dev] = Demotion(
            dev=action.dev,
            profile=profile,
            original_metric=route.metric,
            since=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            reason=action.reason,
            kind=kind,
            target=target or "",
            target_metric=others.get(target) if target else None,
            since_ts=now,
            others=others,
        )
        state.failures[action.dev] = 0
        state.failure_since.pop(action.dev, None)
        if kind == "wedged":
            # A new episode: the USB schedule starts over, and the flap
            # damping remembers the wedge.
            state.usb_attempts.pop(action.dev, None)
            times = recent_wedges(state, action.dev, policy, now)
            times.append(now)
            state.wedge_times[action.dev] = times
        log.warning(
            "event=uplink_demoted cycle=%s dev=%s before=%s trigger=%s metric=%s->%s kind=%s "
            "profile=%s others=%s duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            action.trigger,
            route.metric,
            action.metric,
            kind,
            profile,
            ",".join(sorted(others)) or "-",
            took(),
            action.reason,
        )
        return True

    if action.kind == "restore":
        demotion = state.demoted.get(action.dev)
        if demotion is None:
            return False
        to_restore = dict(demotion.others)
        if demotion.target and demotion.target_metric is not None:
            to_restore.setdefault(demotion.target, demotion.target_metric)
        okay = _modify_metric(demotion.profile, demotion.original_metric, run)
        for name, original in to_restore.items():
            okay = _modify_metric(name, original, run) and okay
        if not okay or not _reapply(action.dev, run):
            log.error(
                "event=restore_failed cycle=%s dev=%s profile=%s duration_ms=%.0f",
                n,
                action.dev,
                demotion.profile,
                took(),
            )
            return False
        del state.demoted[action.dev]
        state.successes[action.dev] = 0
        state.usb_attempts.pop(action.dev, None)
        state.fast_demoted_streak.pop(action.dev, None)
        state.fast_demoted_last_fail.pop(action.dev, None)
        log.warning(
            "event=uplink_restored cycle=%s dev=%s before=%s metric=%s kind=%s "
            "profile=%s others=%s demoted_for_s=%.0f duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            demotion.original_metric,
            demotion.kind,
            demotion.profile,
            ",".join(sorted(to_restore)) or "-",
            now - demotion.since_ts if demotion.since_ts else -1.0,
            took(),
            action.reason,
        )
        return True

    if action.kind == "reset":
        state.last_reset[action.dev] = now
        if action.tag == "no_route":
            profile_name = action.profile or profiles.get(action.dev)
            if profile_name and profile_never_default(profile_name, run):
                log.info(
                    "event=reset_skipped cycle=%s dev=%s profile=%s reason=never_default",
                    n,
                    action.dev,
                    profile_name,
                )
                return False
            if _reapply(action.dev, run):
                log.warning(
                    "event=uplink_reapply cycle=%s dev=%s before=%s profile=%s "
                    "duration_ms=%.0f reason=%s",
                    n,
                    action.dev,
                    before,
                    profile_name,
                    took(),
                    action.reason,
                )
                return True
        if action.tag == "preference":
            state.prefer_attempts[action.dev] = (
                state.prefer_attempts.get(action.dev, 0) + 1
            )
            state.last_prefer[action.dev] = now
        profile = action.profile or profiles.get(action.dev)
        okay = reset_device(action.dev, profile, run)
        if action.tag == "fallback" and action.dev in state.demoted:
            # The move is undone; from here a device that stays dead is a
            # wedge and gets the USB schedule like any other.
            state.demoted[action.dev].kind = "wedged"
            state.demoted[
                action.dev
            ].reason = f"{action.reason}; escalates as a wedge from here"
        log.warning(
            "event=uplink_reset cycle=%s dev=%s before=%s trigger=%s ok=%s tag=%s profile=%s "
            "duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            action.trigger,
            okay,
            action.tag,
            profile,
            took(),
            action.reason,
        )
        return okay

    if action.kind == "reload":
        attempt = state.reload_attempts.get(action.dev, 0) + 1
        state.reload_attempts[action.dev] = attempt
        state.last_reload[action.dev] = now
        okay, detail = driver_reload(action.dev, run)
        log.warning(
            "event=uplink_driver_reload cycle=%s dev=%s before=%s attempt=%s ok=%s "
            "duration_ms=%.0f reason=%s detail=%s",
            n,
            action.dev,
            before,
            attempt,
            okay,
            took(),
            action.reason,
            detail,
        )
        return okay

    if action.kind == "usb_reset":
        # Count the attempt whether or not it works: a failing sudo or a
        # vanished node must still advance the schedule, never storm.
        if action.tag == "usb_speed":
            attempt = state.usb_speed_attempts.get(action.dev, 0) + 1
            state.usb_speed_attempts[action.dev] = attempt
            state.last_usb_speed_reset[action.dev] = now
            wait = usb_backoff(policy.usb_speed_schedule, attempt)
        else:
            attempt = state.usb_attempts.get(action.dev, 0) + 1
            state.usb_attempts[action.dev] = attempt
            state.last_usb_reset[action.dev] = now
            wait = usb_backoff(policy.usb_reset_schedule, attempt + 1)
        method = usb_reset_method(policy, attempt)
        okay, detail = usb_reset_device(action.dev, policy, run, method=method)
        log.warning(
            "event=uplink_usb_reset cycle=%s dev=%s before=%s attempt=%s method=%s ok=%s "
            "tag=%s next_in_s=%.0f duration_ms=%.0f reason=%s detail=%s",
            n,
            action.dev,
            before,
            attempt,
            method,
            okay,
            action.tag,
            wait,
            took(),
            action.reason,
            detail,
        )
        return okay

    return False


# -- loop --------------------------------------------------------------------


def describe_issues(
    devices: dict[str, DeviceInfo],
    prefs: dict[str, Preference],
    probes: dict[str, ProbeResult],
    state: State,
) -> dict[str, str]:
    """dev -> what keeps it below its highest level right now."""
    issues: dict[str, str] = {}
    for dev in sorted(set(devices) | set(prefs) | set(probes)):
        parts: list[str] = []
        info = devices.get(dev)
        if info is not None and info.nm_state != "connected":
            parts.append(info.nm_state)
        probe = probes.get(dev)
        if probe is not None and probe.errors.get("probe"):
            parts.append(f"probes unavailable ({probe.errors['probe']})")
        elif probe is not None and not probe.healthy:
            parts.append("wedged" if probe.wedged else f"degraded ({probe.summary()})")
            if probe.notes.get("dns") == "resolver":
                parts.append(
                    "the system resolver is not answering while the fallback "
                    "does: a DNS server problem, not the link"
                )
        if info is not None and info.usb_speed is not None:
            best = state.usb_best_speed.get(dev, 0)
            if info.usb_speed < best:
                parts.append(f"USB link {info.usb_speed} Mbit/s, best seen {best}")
        pref = prefs.get(dev)
        if pref is not None and pref.target:
            where = "in range" if pref.visible else "not in range"
            parts.append(
                f"on {pref.current or 'no profile'}, {pref.target} preferred ({where})"
            )
        if parts:
            issues[dev] = "; ".join(parts)
    for key, text in state.extra_issues.items():
        issues.setdefault(key, text)
    return issues


def cycle(
    state: State,
    policy: Policy,
    state_file: Path,
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
) -> list[Action]:
    """One observe-decide-act pass. Returns the actions taken.

    The journal is the record: every cycle logs its probes and one
    `cycle` summary; grade changes log a `transition`; a rung that looks
    at a device and declines logs a `decision` (on change, and again every
    `snapshot_interval_s`); every action logs what it did and how it went;
    a `snapshot` of everything lands on the same cadence; `inventory`
    lines pin down the hardware and profiles when they change.
    """
    started = time.perf_counter()
    state.cycle_n += 1
    n = state.cycle_n
    now_cycle = time.time()
    paused_until = pause_until(policy.pause_file)
    holding = paused_until is not None or policy.dry_run
    if (paused_until is not None) != state.was_paused:
        log.warning(
            "event=%s cycle=%s until=%s",
            "pause_started" if paused_until is not None else "pause_ended",
            n,
            (
                datetime.fromtimestamp(paused_until, timezone.utc).isoformat(
                    timespec="seconds"
                )
                if paused_until is not None
                else "-"
            ),
        )
        state.was_paused = paused_until is not None

    routes, routes_known = uplink.read_default_routes(run)
    if not routes_known:
        log.error("event=routes_unreadable cycle=%s", n)
    probes = uplink.probe_all(
        routes,
        host=host,
        timeout=timeout,
        run=run,
        fallback_nameserver=policy.dns_fallback,
    )
    devices = observe_devices(run, policy.usb_reset_ids)
    radio = wifi_radio_enabled(run)
    state.extra_issues = {}
    for dev, p in probes.items():
        if p.errors.get("probe"):
            log.error(
                "event=uplink_probe_unavailable cycle=%s dev=%s %s",
                n,
                dev,
                p.errors["probe"],
            )
    active = uplink.active_route(routes)
    active_probe = probes.get(active.dev) if active is not None else None
    if active_probe is not None and active_probe.healthy:
        state.uplink_ok_cycles += 1
    else:
        state.uplink_ok_cycles = 0
    # Devices ever seen; one that vanished from NetworkManager is reported.
    for dev, info in devices.items():
        state.known_devices[dev] = info.usb_id or "builtin"
    for dev, kind in state.known_devices.items():
        if dev not in devices:
            state.extra_issues[dev] = (
                f"absent: not seen by NetworkManager ({kind}); "
                + (
                    "unplugged, or the driver is not bound"
                    if kind != "builtin"
                    else "the driver is gone"
                )
            )
    state.extra_issues.update(usb_adapters_without_netdev(policy.usb_reset_ids))
    if now_cycle - state.last_reconcile >= policy.reconcile_interval_s:
        state.last_reconcile = now_cycle
        state.extra_issues.update(stranded_metrics(state, policy, run))
    health = host_health(run)
    if health.get("flags") and any(" now" in f for f in health["flags"].split(", ")):
        state.extra_issues["host"] = f"power/thermal: {health['flags']}"

    # Every Wi-Fi device is "unavailable" behind a software rfkill; nothing
    # below can repair that, so switch it back on (one attempt per
    # min_reset_interval_s). A hardware switch stays as it is.
    if (
        radio is False
        and policy.down_repair
        and not holding
        and now_cycle - state.last_radio_on >= policy.min_reset_interval_s
    ):
        state.last_radio_on = now_cycle
        proc = run("nmcli", "radio", "wifi", "on")
        log.warning(
            "event=uplink_radio_on cycle=%s ok=%s err=%s",
            n,
            proc.returncode == 0,
            proc.stderr.strip(),
        )

    state.last_cycle = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state.last_summary = {dev: p.summary() for dev, p in probes.items()}

    for dev, p in probes.items():
        level = logging.INFO if p.healthy else logging.WARNING
        log.log(level, "event=uplink_probe cycle=%s dev=%s %s", n, dev, p.detail())
        if not p.healthy:
            for layer, err in p.errors.items():
                log.warning(
                    "event=uplink_probe_error cycle=%s dev=%s layer=%s %s",
                    n,
                    dev,
                    layer,
                    err,
                )

    prefs: dict[str, Preference] = {}
    profiles_all: list[WifiProfile] = []
    if policy.prefer_enabled or policy.down_repair:
        devs = sorted({r.dev for r in routes} | set(devices))
        prefs = preferences(devs, run)
        # A device that is not on its best profile gets a fresh scan on the
        # interval; the cached list may be stale (it was, for 24 h).
        # A fresh scan costs 20-60 s of cycle time; while the active route
        # is not healthy the failover matters more than a band move (a scan
        # delayed the wedge detection by a cycle on 2026-09-14 08:15).
        due = {
            dev
            for dev, pref in prefs.items()
            if pref.target
            and not pref.visible
            and active_probe is not None
            and active_probe.healthy
            and now_cycle - state.last_scan.get(dev, 0.0)
            >= policy.prefer_check_interval_s
        }
        if due:
            for dev in due:
                state.last_scan[dev] = now_cycle
            prefs.update(preferences(sorted(due), run, rescan_for=due))
        for dev, pref in prefs.items():
            band = band_label(wifi_link_freq(dev, run)) if pref.current else "-"
            state.last_profiles[dev] = f"{pref.current or 'none'} ({band})"
            if pref.target:
                # WARNING only when the move is actually pending; a target
                # that stays out of range would otherwise fill the journal.
                log.log(
                    logging.WARNING if pref.visible else logging.INFO,
                    "event=uplink_profile cycle=%s dev=%s profile=%s band=%s preferred=%s in_range=%s",
                    n,
                    dev,
                    pref.current or "none",
                    band,
                    pref.target,
                    pref.visible,
                )

    # -- grades and transitions. A single "degraded" cycle between healthy
    #    ones (one lost ping on a lossy link) is not a transition: it needs
    #    two cycles running before the grade changes.
    routed = {r.dev for r in routes}
    for dev in sorted(set(devices) | set(probes) | set(state.known_devices)):
        grade = grade_of(probes.get(dev), devices.get(dev), dev in routed)
        previous = state.last_grade.get(dev)
        if grade == "degraded" and previous == "healthy":
            state.degraded_streak[dev] = state.degraded_streak.get(dev, 0) + 1
            if state.degraded_streak[dev] < 2:
                continue
        else:
            state.degraded_streak[dev] = 0
        if previous != grade:
            since = state.grade_since.get(dev)
            worse = previous is not None and grade_rank(grade) > grade_rank(previous)
            dinfo = devices.get(dev)
            log.log(
                logging.WARNING if worse else logging.INFO,
                "event=transition cycle=%s dev=%s from=%s to=%s after_s=%s nm=%s "
                "profile=%s role=%s detail=%s",
                n,
                dev,
                previous or "-",
                grade,
                f"{now_cycle - since:.0f}" if since else "-",
                dinfo.nm_state if dinfo else "-",
                (dinfo.profile or "-") if dinfo else "-",
                "active"
                if active and dev == active.dev
                else "standby"
                if dev in routed
                else "none",
                (
                    probes[dev].detail()
                    if dev in probes
                    else devices[dev].describe()
                    if dev in devices
                    else "absent"
                ),
            )
            state.last_grade[dev] = grade
            state.grade_since[dev] = now_cycle

    decided_active = active.dev if active is not None else None
    with ACT_LOCK:
        actions = evaluate(
            routes,
            probes,
            state,
            policy,
            preferences=prefs,
            devices=devices,
            routes_known=routes_known,
        )
        planned = ",".join(f"{a.kind}:{a.dev}" for a in actions) or "-"
        if holding and actions:
            log.warning(
                "event=%s cycle=%s until=%s skipped=%s",
                "dry_run" if policy.dry_run else "paused",
                n,
                (
                    datetime.fromtimestamp(paused_until, timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    if paused_until is not None
                    else "-"
                ),
                planned,
            )
            actions = []
        # Under the lock: the decision, the metric changes (a demotion or a
        # restore takes a few hundred milliseconds) and the tunnel move.
        quick = [a for a in actions if a.kind in ("demote", "restore")]
        slow = [a for a in actions if a.kind not in ("demote", "restore")]
        done: list[Action] = []
        for action in quick:
            if apply_action(action, routes, state, run, policy=policy):
                done.append(action)
                if action.kind == "demote" and action.tag == "wedged":
                    after_failover(state, policy, run, now_cycle)
    # Outside the lock: the repairs (a re-association blocks for up to
    # 60 s, a USB reset for seconds), so the fast path can fail the active
    # route over meanwhile. Each is re-checked first, and marked in flight
    # so the next cycle does not stack another repair on it.
    skipped: list[Action] = []
    for action in slow:
        if not _still_safe(action, decided_active, state, run):
            skipped.append(action)
            log.warning(
                "event=action_skipped cycle=%s kind=%s dev=%s reason=became the active route",
                n,
                action.kind,
                action.dev,
            )
            continue
        state.repair_in_flight[action.dev] = time.time()
        try:
            if apply_action(action, routes, state, run, policy=policy):
                done.append(action)
        finally:
            state.repair_in_flight.pop(action.dev, None)
    failed = [a for a in actions if a not in done and a not in skipped]
    if failed:
        log.error(
            "event=actions_failed cycle=%s failed=%s",
            n,
            ",".join(f"{a.kind}:{a.dev}" for a in failed),
        )

    # -- declined decisions: on change, and again on the snapshot cadence
    for dev, rung, text in state.decisions:
        _log_decision(state, policy, n, now_cycle, dev, rung, text)

    # -- the processes between the uplink and ChatGPT, and the ones under it
    services_note = "-"
    tunnel_note = "-"
    if policy.service_repair:
        obs = observe_services(policy, run)
        tunnel_word = (
            "stopped"
            if not obs.tunnel_active
            else "FROZEN"
            if obs.tunnel_health_ok is False
            else f"failing({obs.poll_failures})"
            if obs.poll_failures
            else "ok"
        )
        services_note = (
            f"mcp={'ok' if obs.endpoint_ok else 'DOWN' if obs.endpoint_ok is False else 'stopped'}"
            f",tunnel={tunnel_word}"
        )
        restarts = evaluate_services(obs, state, policy, now_cycle)
        if holding and restarts:
            log.warning(
                "event=%s cycle=%s skipped_services=%s",
                "dry_run" if policy.dry_run else "paused",
                n,
                ",".join(u for u, _ in restarts),
            )
            restarts = []
        for unit, reason in restarts:
            name = "tunnel" if unit == policy.tunnel_unit else "mcp"
            state.last_service_restart[name] = now_cycle
            if name == "tunnel":
                restart_tunnel(state, policy, run, reason, now_cycle)
                continue
            proc = run("systemctl", "--user", "restart", unit, timeout=120.0)
            log.warning(
                "event=service_restart cycle=%s unit=%s ok=%s reason=%s err=%s",
                n,
                unit,
                proc.returncode == 0,
                reason,
                proc.stderr.strip(),
            )
        tunnel_note = tunnel_affinity_check(
            state, policy, run, routes, probes, obs, n, now_cycle, holding
        )
        if obs.mcp_unit and obs.endpoint_ok is False:
            state.extra_issues["mcp"] = (
                f"{policy.mcp_url} not answering while {obs.mcp_unit} is active"
            )
        if obs.tunnel_active and obs.tunnel_health_ok is False:
            state.extra_issues["tunnel"] = (
                "tunnel health server not answering (process frozen?)"
            )
        elif (
            obs.tunnel_active
            and obs.poll_last is not None
            and now_cycle - obs.poll_last >= policy.tunnel_stale_after_s
        ):
            state.extra_issues["tunnel"] = (
                f"tunnel log silent for {int(now_cycle - obs.poll_last)} s (reported only)"
            )
        if obs.tunnel_active and obs.poll_failures:
            state.extra_issues["tunnel"] = (
                f"tunnel poll failing ({obs.poll_failures} in a row); ChatGPT sees the "
                "connector offline"
                if obs.poll_failures >= policy.service_failures_before_action
                else f"tunnel poll failing ({obs.poll_failures} in a row)"
            )
    if policy.system_service_repair:
        sys_obs = observe_system(policy, devices, nm_answers(run), run)
        if not sys_obs.nm_active:
            state.extra_issues["networkmanager"] = f"{policy.nm_unit} is not active"
        elif not sys_obs.nm_responsive:
            state.extra_issues["networkmanager"] = (
                f"{policy.nm_unit} answered nothing for {state.nm_unresponsive_cycles + 1} cycles"
            )
        if sys_obs.nm_active and not sys_obs.supplicant_active:
            state.extra_issues["supplicant"] = f"{policy.supplicant_unit} is not active"
        restarts = evaluate_system(sys_obs, state, policy, now_cycle)
        if holding and restarts:
            log.warning(
                "event=%s cycle=%s skipped_system=%s",
                "dry_run" if policy.dry_run else "paused",
                n,
                ",".join(u for u, _ in restarts),
            )
            restarts = []
        for unit, reason in restarts:
            name = "nm" if unit == policy.nm_unit else "supplicant"
            state.last_system_restart[name] = now_cycle
            proc = run("sudo", "-n", "systemctl", "restart", unit, timeout=120.0)
            log.warning(
                "event=system_service_restart cycle=%s unit=%s ok=%s reason=%s err=%s",
                n,
                unit,
                proc.returncode == 0,
                reason,
                proc.stderr.strip(),
            )

    for dev, info in devices.items():
        state.last_devices[dev] = info.describe(state.usb_best_speed.get(dev))
    for dev in state.known_devices:
        if dev not in devices:
            state.last_devices[dev] = "absent"
    issues = describe_issues(devices, prefs, probes, state)
    if radio is False:
        issues["wifi"] = "NetworkManager's Wi-Fi radio is switched off"
    if paused_until is not None:
        issues["watchdog"] = (
            "paused until "
            + datetime.fromtimestamp(paused_until, timezone.utc).isoformat(
                timespec="seconds"
            )
            + "; observing, not acting"
        )
    _log_issues(state, policy, issues, n, now_cycle)
    state.issues = issues

    # -- inventory: what each device is, at start and on the snapshot
    #    cadence (it costs a few nmcli calls), logged when it changes
    inventory_tick = bool(devices) and (
        not state.last_inventory
        or now_cycle - state.last_inventory_at >= policy.snapshot_interval_s
    )
    if inventory_tick:
        state.last_inventory_at = now_cycle
        profiles_all = wifi_profiles(run)
        for dev, info in devices.items():
            line = inventory_line(dev, info, profiles_all, run, policy.inventory_params)
            if state.last_inventory.get(dev) != line:
                log.info("event=inventory cycle=%s dev=%s %s", n, dev, line)
                state.last_inventory[dev] = line
    # The host line carries the temperature but only changes of the flags,
    # the resolver or the radio switch re-log it; the temperature alone
    # would re-log it every cycle. The snapshot cadence re-states it.
    host_key = (
        f"throttled={health.get('throttled', '-')} flags={health.get('flags', '-')} "
        f"resolver={','.join(uplink.nameservers()) or '-'} "
        f"radio={'on' if radio else 'off' if radio is False else '?'}"
    )
    if state.last_inventory.get("host") != host_key or inventory_tick:
        log.info(
            "event=inventory_host cycle=%s %s temp=%s",
            n,
            host_key,
            health.get("temp", "-"),
        )
        state.last_inventory["host"] = host_key

    # -- the cycle line: the timeline's backbone
    state.last_duration_ms = (time.perf_counter() - started) * 1000
    grades = ",".join(f"{d}:{g}" for d, g in sorted(state.last_grade.items()))
    if state.last_duration_ms > 30_000:
        log.warning(
            "event=cycle_slow cycle=%s duration_ms=%.0f", n, state.last_duration_ms
        )
    fast_note = (
        f"{state.fast_failures}/{policy.fast_failures_before_action}"
        f"@{max(0.0, time.time() - state.fast_last):.0f}s"
        if state.fast_last
        else "-"
    )
    log.info(
        "event=cycle cycle=%s duration_ms=%.0f active=%s routes=%s grades=%s demoted=%s "
        "issues=%s planned=%s actions=%s services=%s tunnel_via=%s fast=%s "
        "uplink_ok_cycles=%s%s%s",
        n,
        state.last_duration_ms,
        active.dev if active else "-",
        ",".join(f"{r.dev}:{r.metric}@{r.src}>{r.gateway}" for r in routes) or "-",
        grades or "-",
        ",".join(sorted(state.demoted)) or "-",
        len(issues),
        planned,
        ",".join(f"{a.kind}:{a.dev}" for a in done) or "-",
        services_note,
        tunnel_note,
        fast_note,
        state.uplink_ok_cycles,
        " paused=yes" if paused_until is not None else "",
        " dry_run=yes" if policy.dry_run else "",
    )

    # -- snapshot: a baseline in every window of the journal
    if now_cycle - state.last_snapshot >= policy.snapshot_interval_s:
        state.last_snapshot = now_cycle
        for dev in sorted(set(devices) | set(state.known_devices)):
            pref_s = prefs.get(dev)
            log.info(
                "event=snapshot cycle=%s dev=%s grade=%s since_s=%.0f state=%s probe=%s "
                "pref=%s counters=usb%s/prefer%s/level%s/reload%s",
                n,
                dev,
                state.last_grade.get(dev, "-"),
                now_cycle - state.grade_since.get(dev, now_cycle),
                state.last_devices.get(dev, "-"),
                probes[dev].detail() if dev in probes else "-",
                (
                    f"{pref_s.target}:{'in_range' if pref_s.visible else 'out_of_range'}"
                    if pref_s and pref_s.target
                    else "best"
                ),
                state.usb_attempts.get(dev, 0),
                state.prefer_attempts.get(dev, 0),
                state.usb_speed_attempts.get(dev, 0),
                state.reload_attempts.get(dev, 0),
            )
        log.info(
            "event=snapshot_state cycle=%s demoted=%s issues=%s services=%s uplink_ok_cycles=%s",
            n,
            json.dumps({d: asdict(x) for d, x in state.demoted.items()}, default=str)
            if state.demoted
            else "-",
            json.dumps(issues) if issues else "-",
            services_note,
            state.uplink_ok_cycles,
        )
    state.save(state_file)
    return done


def _log_decision(
    state: State, policy: Policy, n: int, now: float, dev: str, rung: str, text: str
) -> None:
    """A declined decision: logged on change, re-stated on the snapshot
    cadence, so "why did nothing happen" is answerable from any window."""
    key = f"{dev}/{rung}"
    last_text, last_at = state.last_decision.get(key, ("", 0.0))
    if text != last_text or now - last_at >= policy.snapshot_interval_s:
        log.info("event=decision cycle=%s dev=%s rung=%s note=%s", n, dev, rung, text)
        state.last_decision[key] = (text, now)


def tunnel_main_pid(unit: str, run: Run = _run) -> int | None:
    """The unit's main process id; 0/None when it has none; -1 when the
    answer could not be read (a fake or a failing systemctl)."""
    proc = run("systemctl", "--user", "show", unit, "-p", "MainPID", "--value")
    text = proc.stdout.strip()
    if proc.returncode != 0 or not text:
        return -1
    try:
        return int(text) or None
    except ValueError:
        return -1


@dataclass(frozen=True, slots=True)
class TunnelSocket:
    """One established connection of the tunnel process."""

    #: The device owning the local address; None when it belongs to none.
    dev: str | None
    local: str
    peer: str


def tunnel_sockets(
    unit: str, routes: list[Route], run: Run = _run, port: int = 443
) -> list[TunnelSocket] | None:
    """The tunnel process's established connections to `port`, each with
    the device that owns its local address (the routes' source addresses
    first, then every configured IPv4 address). None when the unit has no
    main process right now (it is restarting); an empty list when there is
    none to see or the answer could not be read.
    """
    pid = tunnel_main_pid(unit, run)
    if pid is None:
        return None
    if pid < 0:
        return []
    proc = run("ss", "-tnpH", "state", "established")
    if proc.returncode != 0:
        return []
    owner = {r.src: r.dev for r in routes}
    addr = run("ip", "-o", "-4", "addr", "show")
    for line in addr.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            owner.setdefault(parts[3].split("/")[0], parts[1])
    tag = f"pid={pid},"
    out: list[TunnelSocket] = []
    for line in proc.stdout.splitlines():
        if tag not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local, peer = parts[2], parts[3]
        if not peer.endswith(f":{port}"):
            continue
        ip = local.rsplit(":", 1)[0]
        if ip.startswith("127."):
            continue
        out.append(TunnelSocket(owner.get(ip), local, peer))
    return out


def tunnel_via(
    sockets: list[TunnelSocket] | None, active_dev: str | None
) -> str | None:
    """The device the tunnel's connection sits on: the active one when any
    connection is on it, else the first connection's ("?" when its address
    belongs to no device); None without a connection."""
    if not sockets:
        return None
    for s in sockets:
        if active_dev is not None and s.dev == active_dev:
            return s.dev
    return sockets[0].dev or "?"


def restart_tunnel(
    state: State,
    policy: Policy,
    run: Run,
    reason: str,
    now: float,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Restart the tunnel unit and wait for its new instance to be up.

    The tunnel rewrites its health URL file on start; a file newer than
    the restart whose URL answers is the new poller (measured 2026-09-14:
    0.6 s). `ready_ms` lands on the service_restart line; not ready within
    `tunnel_ready_timeout_s` logs `tunnel_not_ready` and the health rung
    takes it from there.
    """
    url_file = policy.tunnel_health_url_file
    started = time.time()
    t0 = time.perf_counter()
    state.last_tunnel_restart = now
    proc = run("systemctl", "--user", "restart", policy.tunnel_unit, timeout=60.0)
    okay = proc.returncode == 0
    ready_ms: float | None = None
    if okay and url_file is not None:
        deadline = time.perf_counter() + policy.tunnel_ready_timeout_s
        while True:
            try:
                fresh = url_file.stat().st_mtime >= started - 1.0
                url = url_file.read_text(encoding="utf-8").strip() if fresh else ""
            except OSError:
                url = ""
            if url.startswith("http") and http_alive(url, timeout=1.0):
                ready_ms = (time.perf_counter() - t0) * 1000
                break
            if time.perf_counter() >= deadline:
                break
            sleep(0.5)
    log.warning(
        "event=service_restart cycle=%s unit=%s ok=%s ready_ms=%s reason=%s err=%s",
        state.cycle_n,
        policy.tunnel_unit,
        okay,
        f"{ready_ms:.0f}" if ready_ms is not None else "-",
        reason,
        proc.stderr.strip(),
    )
    if okay and url_file is not None and ready_ms is None:
        log.error(
            "event=tunnel_not_ready cycle=%s unit=%s waited_s=%.0f reason=no new health "
            "server answered; the health rung restarts it again after %s cycles",
            state.cycle_n,
            policy.tunnel_unit,
            policy.tunnel_ready_timeout_s,
            policy.service_failures_before_action,
        )
    return okay


def after_failover(
    state: State, policy: Policy, run: Run, now: float, target: str | None = None
) -> None:
    """Right after traffic moved: put the tunnel's connection on the new
    active route.

    Its socket is bound to the old route's address and would sit on the
    dead path for the rest of its poll deadline (35 s), then reconnect; a
    restart is back polling in about a second (measured 0.6 s on
    2026-09-14). Skipped when the connection is already on the new active
    route (a second failover right after a restart) or while the unit is
    restarting; a floor of `failover_restart_floor_s` between restarts.
    """
    if not policy.restart_tunnel_on_failover:
        return
    if not unit_active(policy.tunnel_unit, run):
        return
    routes, known = uplink.read_default_routes(run)
    active = target or (routes[0].dev if known and routes else None)
    sockets = tunnel_sockets(policy.tunnel_unit, routes if known else [], run)
    if sockets is None:
        log.info(
            "event=tunnel_kept cycle=%s reason=no tunnel process (restarting already)",
            state.cycle_n,
        )
        return
    via = tunnel_via(sockets, active)
    if active is not None and via == active:
        log.info(
            "event=tunnel_kept cycle=%s via=%s reason=connection already on the new active route",
            state.cycle_n,
            via,
        )
        return
    if (
        state.last_tunnel_restart
        and now - state.last_tunnel_restart < policy.failover_restart_floor_s
    ):
        log.warning(
            "event=service_restart_deferred cycle=%s unit=%s via=%s reason=restarted %.0f s ago",
            state.cycle_n,
            policy.tunnel_unit,
            via or "-",
            now - state.last_tunnel_restart,
        )
        return
    state.last_failover_restart = now
    restart_tunnel(
        state,
        policy,
        run,
        f"failover: the poller's connection is on {via or 'the old route'}, "
        f"traffic moved to {active or 'the next route'}",
        now,
    )


def tunnel_affinity_check(
    state: State,
    policy: Policy,
    run: Run,
    routes: list[Route],
    probes: dict[str, ProbeResult],
    obs: "ServiceObservation",
    n: int,
    now: float,
    holding: bool = False,
) -> str:
    """Keep the tunnel's connection on the active route.

    Returns the device it is on for the cycle line ("-" none seen). Off
    the active route and without a TCP path: restart now (the poller is
    stalling on it; `failover_restart_floor_s` between restarts). Off it
    but usable: after `tunnel_affinity_cycles` cycles with the active
    route healthy, at a quiet moment (no command forwarded for
    `tunnel_quiet_s`), one per minute -- waiting those cycles also means
    a route that wedges again right after its restore never costs a
    restart, because the connection is still where traffic goes back to.
    """
    active = uplink.active_route(routes) if routes else None
    if not policy.tunnel_affinity or not obs.tunnel_active or active is None:
        state.tunnel_off_active_cycles = 0
        state.tunnel_via = "-"
        return "-"
    sockets = tunnel_sockets(policy.tunnel_unit, routes, run)
    via = tunnel_via(sockets, active.dev)
    if via is None:
        state.tunnel_off_active_cycles = 0
        state.tunnel_via = "-"
        return "-"
    state.tunnel_via = via
    if via == active.dev:
        state.tunnel_off_active_cycles = 0
        return via
    state.tunnel_off_active_cycles += 1
    count = state.tunnel_off_active_cycles
    via_probe = probes.get(via)
    usable = via_probe is not None and via_probe.layers.get("tcp") is True
    active_probe = probes.get(active.dev)
    active_ok = active_probe is not None and active_probe.layers.get("tcp") is True
    since_restart = (
        now - state.last_tunnel_restart if state.last_tunnel_restart else None
    )
    forwarded_ago = now - obs.forwarded_last if obs.forwarded_last else None
    quiet = forwarded_ago is None or forwarded_ago >= policy.tunnel_quiet_s
    where = f"connection on {via} ({'usable' if usable else 'no TCP path'}), active {active.dev}"
    if holding:
        _log_decision(
            state, policy, n, now, "tunnel", "affinity", f"{where}; paused or dry-run"
        )
        return via
    if not usable:
        if not active_ok:
            why = f"{active.dev} has no TCP path either"
        elif (
            since_restart is not None
            and since_restart < policy.failover_restart_floor_s
        ):
            why = f"restarted {since_restart:.0f} s ago"
        else:
            state.tunnel_off_active_cycles = 0
            restart_tunnel(
                state,
                policy,
                run,
                f"affinity: the poller's connection is on {via}, which has no TCP path; "
                f"{active.dev} is the active route",
                now,
            )
            return via
        _log_decision(state, policy, n, now, "tunnel", "affinity", f"{where}; {why}")
        return via
    if count < policy.tunnel_affinity_cycles:
        why = f"waiting {count}/{policy.tunnel_affinity_cycles} cycles"
    elif active_probe is None or not active_probe.healthy:
        why = f"{active.dev} is not healthy"
    elif not quiet:
        why = f"a command was forwarded {forwarded_ago:.0f} s ago"
    elif since_restart is not None and since_restart < 60.0:
        why = f"restarted {since_restart:.0f} s ago"
    else:
        state.tunnel_off_active_cycles = 0
        restart_tunnel(
            state,
            policy,
            run,
            f"affinity: the poller's connection sat on {via} for {count} cycles while "
            f"{active.dev} is the active route"
            + (
                f" (quiet for {forwarded_ago:.0f} s)"
                if forwarded_ago is not None
                else " (no command forwarded)"
            ),
            now,
        )
        return via
    _log_decision(state, policy, n, now, "tunnel", "affinity", f"{where}; {why}")
    return via


def _log_issues(
    state: State, policy: Policy, issues: dict[str, str], n: int, now: float
) -> None:
    """`uplink_issue` / `uplink_issue_cleared` on change -- up to
    `flap_log_limit` changes per device inside a snapshot interval; past
    that one `uplink_issue_flapping` summary per interval stands for them
    (wlan0's lossy link wrote 56 issue lines in three hours)."""
    window = policy.snapshot_interval_s
    for dev in sorted(set(issues) | set(state.last_logged_issue)):
        current = issues.get(dev, "")
        if current == state.last_logged_issue.get(dev, ""):
            continue
        flips = [t for t in state.issue_flips.get(dev, []) if now - t < window]
        flips.append(now)
        state.issue_flips[dev] = flips
        if len(flips) <= policy.flap_log_limit:
            if current:
                log.warning(
                    "event=uplink_issue cycle=%s dev=%s issue=%s", n, dev, current
                )
            else:
                log.info("event=uplink_issue_cleared cycle=%s dev=%s", n, dev)
            state.last_logged_issue[dev] = current
            continue
        last_summary = state.last_flap_log.get(dev)
        if last_summary is None or now - last_summary >= window:
            state.last_flap_log[dev] = now
            log.warning(
                "event=uplink_issue_flapping cycle=%s dev=%s changes=%s window_s=%.0f current=%s",
                n,
                dev,
                len(flips),
                window,
                current or "clear",
            )
            state.last_logged_issue[dev] = current
    for dev in list(state.last_logged_issue):
        if not state.last_logged_issue[dev] and dev not in issues:
            state.last_logged_issue.pop(dev, None)


def _still_safe(
    action: Action, decided_active: str | None, state: State, run: Run
) -> bool:
    """A repair decided under the lock, about to run outside it: still
    safe unless the device has become the active route meanwhile (the fast
    path moved traffic onto it). An in-place repair of the route that was
    active when it was decided, or of a demoted device, always is."""
    if action.dev == decided_active or action.dev in state.demoted:
        return True
    routes_now, known = uplink.read_default_routes(run)
    if not known or not routes_now:
        return True
    return routes_now[0].dev != action.dev


def fast_check(
    state: State,
    policy: Policy,
    run: Run = _run,
    tcp: Callable[[Route], bool] | None = None,
    now: float | None = None,
    host: str = uplink.UPSTREAM_HOST,
) -> list[Action]:
    """One tick of the fast path. Returns the actions it applied.

    Only the active route is probed (one TCP connect to the upstream's
    cached address, `fast_timeout_s`), plus any demoted route so the
    restore can ask for a clean run at this resolution; the standbys are
    asked only when the active one has failed `fast_failures_before_action`
    times running, and only a standby with a working TCP path makes it a
    failover. The demotion and the tunnel move happen under the lock the
    cycle uses; the re-association runs outside it, marked in flight.
    """
    now = time.time() if now is None else now
    state.fast_last = now
    if policy.dry_run or pause_until(policy.pause_file) is not None:
        return []
    routes, known = uplink.read_default_routes(run)
    if not known or len(routes) < 2:
        state.fast_failures = 0
        return []
    active = routes[0]
    address = uplink._last_address.get(host)
    if address is None:
        return []  # the full cycle has not resolved the upstream yet

    def connect(route: Route) -> bool:
        if tcp is not None:
            return tcp(route)
        try:
            ok, _ = uplink.probe_tcp(
                route.src,
                host,
                timeout=policy.fast_timeout_s,
                dev=route.dev,
                address=address,
            )
        except uplink.ProbeUnavailable:
            return True  # no verdict: never a failover
        return ok

    for route in routes[1:]:
        if route.dev not in state.demoted:
            continue
        if connect(route):
            state.fast_demoted_streak[route.dev] = (
                state.fast_demoted_streak.get(route.dev, 0) + 1
            )
            continue
        streak = state.fast_demoted_streak.get(route.dev, 0)
        if streak or route.dev not in state.fast_demoted_last_fail:
            log.warning(
                "event=fast_failure cycle=%s dev=%s role=demoted after_successes=%s",
                state.cycle_n,
                route.dev,
                streak,
            )
        state.fast_demoted_streak[route.dev] = 0
        state.fast_demoted_last_fail[route.dev] = now

    if active.dev in state.demoted:
        state.fast_failures = 0
        return []
    if state.fast_dev != active.dev:
        state.fast_dev = active.dev
        state.fast_failures = 0
    if connect(active):
        if state.fast_failures:
            log.info(
                "event=fast_recovered cycle=%s dev=%s after_failures=%s",
                state.cycle_n,
                active.dev,
                state.fast_failures,
            )
        state.fast_failures = 0
        return []
    state.fast_failures += 1
    log.warning(
        "event=fast_failure cycle=%s dev=%s failures=%s/%s",
        state.cycle_n,
        active.dev,
        state.fast_failures,
        policy.fast_failures_before_action,
    )
    if state.fast_failures < policy.fast_failures_before_action:
        return []
    done: list[Action] = []
    want_reset = False
    with ACT_LOCK:
        if active.dev in state.demoted:
            return []
        target = next(
            (r for r in routes[1:] if r.dev not in state.demoted and connect(r)), None
        )
        if target is None:
            log.warning(
                "event=fast_failover_blocked cycle=%s dev=%s reason=no standby with a TCP path",
                state.cycle_n,
                active.dev,
            )
            return []
        window = state.fast_failures * policy.fast_interval_s
        log.warning(
            "event=fast_failover cycle=%s dev=%s failures=%s window_s=%.0f target=%s metric=%s",
            state.cycle_n,
            active.dev,
            state.fast_failures,
            window,
            target.dev,
            target.metric,
        )
        demote = Action(
            "demote",
            active.dev,
            f"no TCP path for {state.fast_failures} fast probes ({window:.0f} s); "
            f"{target.dev} has a TCP path (metric {target.metric})",
            metric=policy.demoted_metric,
            trigger="fast",
        )
        if apply_action(demote, routes, state, run, policy=policy):
            done.append(demote)
            # Traffic has moved; get the poller onto the new path now,
            # before the 14 s re-association of the old one.
            after_failover(state, policy, run, now, target=target.dev)
            want_reset = policy.reset_after_failover and _may_reset(
                state, active.dev, policy, now, episode_start=now
            )
        state.fast_failures = 0
    if want_reset:
        reset = Action(
            "reset", active.dev, "repair after fast failover", trigger="fast"
        )
        state.repair_in_flight[active.dev] = now
        try:
            if apply_action(reset, routes, state, run, policy=policy):
                done.append(reset)
        finally:
            state.repair_in_flight.pop(active.dev, None)
    return done


def fast_loop(
    state: State,
    policy: Policy,
    run: Run,
    stop: threading.Event,
    host: str = uplink.UPSTREAM_HOST,
) -> None:
    """The fast path's thread body."""
    while not stop.wait(policy.fast_interval_s):
        try:
            fast_check(state, policy, run, host=host)
        except Exception:  # never let the fast path kill the loop
            log.exception("event=fast_check_error cycle=%s", state.cycle_n)


def supervise_fast_path(
    state: State,
    policy: Policy,
    thread: threading.Thread,
    start: Callable[[], threading.Thread],
    exit_fn: Callable[[int], None] = os._exit,
    now: float | None = None,
) -> tuple[threading.Thread, bool]:
    """After each cycle: a dead fast-path thread is started again, a
    stalled heartbeat is logged, a hung one (older than the cycle timeout)
    exits the process for systemd to restart. Returns (thread, hung)."""
    now = time.time() if now is None else now
    age = now - state.fast_last if state.fast_last else 0.0
    stall_after = max(30.0, 3 * (policy.fast_interval_s + policy.fast_timeout_s))
    if not thread.is_alive():
        log.error(
            "event=fast_path_restarted cycle=%s reason=thread died age_s=%.0f",
            state.cycle_n,
            age,
        )
        state.fast_last = now  # the new thread gets its first tick before it is judged
        return start(), False
    if age > policy.cycle_timeout_s:
        log.error(
            "event=fast_path_hung cycle=%s age_s=%.0f; exiting for systemd to restart",
            state.cycle_n,
            age,
        )
        for handler in log.handlers or logging.getLogger().handlers:
            handler.flush()
        sys.stdout.flush()
        exit_fn(3)
        return thread, True
    if age > stall_after:
        log.warning("event=fast_path_stalled cycle=%s age_s=%.0f", state.cycle_n, age)
    return thread, False


def run_forever(
    state_file: Path,
    interval_s: float = 30.0,
    policy: Policy = DEFAULT_POLICY,
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    exit_fn: Callable[[int], None] = os._exit,
) -> None:
    """Probe forever. `max_cycles` bounds the loop for tests.

    Each cycle runs in a worker thread with `policy.cycle_timeout_s` as the
    deadline: a hung cycle (a subprocess that never returns, a kernel call
    that blocks) would otherwise leave the watchdog alive and useless --
    the exact shape of the outage it exists for. On a hang the process
    exits and systemd (Restart=always) starts a fresh one; the persisted
    state carries the demotions and counters across.

    The fast path's thread is supervised the same way from here: a dead
    thread is started again, a stalled heartbeat is logged, a hung one
    (older than the cycle timeout) exits the process.
    """
    state = State.load(state_file)
    log.info(
        "event=watchdog_start interval_s=%s host=%s state_file=%s cycle=%s demoted=%s "
        "counters=usb%s/prefer%s/level%s/reload%s versions=%s policy=%s",
        interval_s,
        host,
        state_file,
        state.cycle_n,
        sorted(state.demoted),
        json.dumps(state.usb_attempts),
        json.dumps(state.prefer_attempts),
        json.dumps(state.usb_speed_attempts),
        json.dumps(state.reload_attempts),
        json.dumps(versions(run)),
        json.dumps(asdict(policy), default=str),
    )
    stopping: list[str] = []

    def on_signal(signum: int, _frame: object) -> None:
        stopping.append(signal.Signals(signum).name)

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, on_signal)
            except (ValueError, OSError):  # not the main thread, or embedded
                pass

    stop_fast = threading.Event()
    fast_thread: threading.Thread | None = None

    def start_fast() -> threading.Thread:
        thread = threading.Thread(
            target=fast_loop,
            args=(state, policy, run, stop_fast, host),
            name="watchdog-fast",
            daemon=True,
        )
        thread.start()
        return thread

    if policy.fast_interval_s > 0 and max_cycles is None:
        fast_thread = start_fast()
        log.info(
            "event=fast_path_start interval_s=%s failures_before_action=%s timeout_s=%s",
            policy.fast_interval_s,
            policy.fast_failures_before_action,
            policy.fast_timeout_s,
        )
    count = 0
    while max_cycles is None or count < max_cycles:
        if stopping:
            break

        def one_cycle() -> None:
            try:
                cycle(state, policy, state_file, host=host, timeout=timeout, run=run)
            except Exception:  # keep the loop alive; a probe bug must not blind us
                log.exception("event=watchdog_cycle_error cycle=%s", state.cycle_n)

        worker = threading.Thread(target=one_cycle, name="watchdog-cycle", daemon=True)
        worker.start()
        worker.join(policy.cycle_timeout_s)
        if worker.is_alive():
            log.error(
                "event=watchdog_cycle_hung timeout_s=%s; exiting for systemd to restart",
                policy.cycle_timeout_s,
            )
            for handler in log.handlers or logging.getLogger().handlers:
                handler.flush()
            sys.stdout.flush()
            exit_fn(3)
            return
        if fast_thread is not None:
            fast_thread, hung = supervise_fast_path(
                state, policy, fast_thread, start_fast, exit_fn
            )
            if hung:
                return
        count += 1
        if stopping:
            break
        if max_cycles is None or count < max_cycles:
            sleep(interval_s)
    stop_fast.set()
    if stopping:
        log.warning(
            "event=watchdog_stop signal=%s cycle=%s demoted=%s",
            stopping[0],
            state.cycle_n,
            sorted(state.demoted) or "-",
        )
