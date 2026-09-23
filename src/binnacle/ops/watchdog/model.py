"""Persistent watchdog state and pure observation models."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from binnacle.ops.watchdog.config import ActionKind
from binnacle.uplink import ProbeResult


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
    #: USB link level in `learned` mode: the best speed the adapter has
    #: shown (lowered when repair gives up; `usb_max_seen` never is), the
    #: reset attempts made to get back to the target, when the last one
    #: was, and since when it has been at the target (not persisted;
    #: clears the count after `usb_speed_hold_s`). The target itself comes
    #: from the policy (policy_usb.py) since 2026-09-23.
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
    #: Physical identity (2026-09-23): dev -> "usb:<vid:pid>@<mac>" or
    #: "builtin@<mac>" as last observed under that name, and the durable
    #: per-device state of adapters not seen right now, keyed by identity,
    #: so it follows the adapter to whatever name it gets next (see
    #: device_identity.py: on 2026-09-15 wlan1/wlan2 swapped for three
    #: boots and the USB 2-only RTL8188EUS inherited the RTL8812AU's
    #: learned 5000 Mbit/s level).
    identities: dict[str, str] = field(default_factory=dict)
    parked: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: USB link policy per device: the fingerprint the repair counters
    #: belong to, the resolved target (None = observe) and mode, the
    #: highest speed ever seen (diagnostic, never a target by itself) and
    #: the speed at which a fixed target's repair was exhausted.
    usb_policy_fp: dict[str, str] = field(default_factory=dict)
    usb_target: dict[str, int | None] = field(default_factory=dict)
    usb_mode: dict[str, str] = field(default_factory=dict)
    usb_max_seen: dict[str, int] = field(default_factory=dict)
    usb_speed_exhausted: dict[str, int] = field(default_factory=dict)
    #: Transient: USB policy changes seen this cycle (dev, old, new,
    #: cleared), logged by the loop as `usb_speed_policy_changed`.
    policy_events: list[tuple[str, str, str, str]] = field(default_factory=list)
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
            "policy_events",
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
        _load_identity(state, raw)
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(path)


def _load_identity(state: "State", raw: dict[str, Any]) -> None:
    """The identity and USB-policy tables (2026-09-23)."""
    state.identities = {
        str(k): str(v) for k, v in (raw.get("identities") or {}).items()
    }
    state.parked = {
        str(k): dict(v)
        for k, v in (raw.get("parked") or {}).items()
        if isinstance(v, dict)
    }
    state.usb_policy_fp = {
        str(k): str(v) for k, v in (raw.get("usb_policy_fp") or {}).items()
    }
    state.usb_target = {
        str(k): (int(v) if v is not None else None)
        for k, v in (raw.get("usb_target") or {}).items()
    }
    state.usb_mode = {str(k): str(v) for k, v in (raw.get("usb_mode") or {}).items()}
    state.usb_max_seen = {
        str(k): int(v) for k, v in (raw.get("usb_max_seen") or {}).items()
    }
    state.usb_speed_exhausted = {
        str(k): int(v) for k, v in (raw.get("usb_speed_exhausted") or {}).items()
    }


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
    #: Permanent MAC address, lower case; "" when it could not be read.
    mac: str = ""
    #: Kernel module parameters named in `inventory_params` (and by the USB
    #: link policies), as read this cycle: (name, value), sorted by name.
    params: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> str | None:
        """Physical identity: `usb:<vid:pid>@<mac>` for a USB adapter,
        `builtin@<mac>` otherwise; None without a MAC, which means no stable
        identity and no history applied to the device."""
        if not self.mac:
            return None
        if self.usb_id:
            return f"usb:{self.usb_id}@{self.mac}"
        return f"builtin@{self.mac}"

    def describe(self, target_usb: int | None = None) -> str:
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
            if target_usb and target_usb != self.usb_speed:
                usb += f" (target {target_usb})"
            parts.append(usb)
        return " ".join(parts)


def band_label(freq: int | None) -> str:
    if freq is None:
        return "?"
    if freq >= 5925:
        return "6 GHz"
    if freq >= 4900:
        return "5 GHz"
    return "2.4 GHz"


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
