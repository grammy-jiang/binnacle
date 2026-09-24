"""Physical device identity: watchdog state follows the adapter, not wlanX.

Interface names are runtime handles. On 2026-09-15 the two USB adapters
swapped wlan1/wlan2 for three boots (and once more mid-boot on 09-16), and
the state file, keyed by name, handed the RTL8812AU's learned 5000 Mbit/s
USB level to the USB 2-only RTL8188EUS: 12 USB resets for a speed it can
never reach. Since 2026-09-23 every durable per-device entry is re-keyed
when a name's identity changes, and parked by identity while the adapter is
absent, so it follows the adapter to whatever name it gets next. The
identity is `usb:<vid:pid>@<permanent mac>` or `builtin@<mac>`
(`DeviceInfo.key`); a device whose MAC could not be read has no identity
and keeps its name-keyed state untouched -- a failed read must never park
anything.
"""

import logging
from dataclasses import asdict
from typing import Any

from binnacle.ops.watchdog.model import Demotion, DeviceInfo, State

log = logging.getLogger("binnacle.watchdog")

#: State that belongs to the adapter and follows it across a rename.
DURABLE_FIELDS: tuple[str, ...] = (
    "demoted",
    "last_reset",
    "last_usb_reset",
    "usb_attempts",
    "last_prefer",
    "prefer_attempts",
    "preferred_since",
    "usb_best_speed",
    "usb_speed_attempts",
    "last_usb_speed_reset",
    "usb_policy_fp",
    "usb_target",
    "usb_mode",
    "usb_max_seen",
    "usb_speed_exhausted",
    "reload_attempts",
    "last_reload",
    "wedge_times",
    "last_grade",
    "grade_since",
    "known_devices",
)

#: State about the name's recent cycles; dropped on a rename, re-observed.
TRANSIENT_FIELDS: tuple[str, ...] = (
    "failures",
    "successes",
    "last_summary",
    "last_profiles",
    "usb_best_since",
    "down_cycles",
    "last_devices",
    "issues",
    "last_role",
    "degraded_streak",
    "failure_since",
    "fast_demoted_last_fail",
    "fast_demoted_streak",
    "issue_flips",
    "last_flap_log",
    "last_logged_issue",
    "last_scan",
    "last_inventory",
)


def _take(state: State, dev: str) -> dict[str, Any]:
    """Remove and return every durable entry of `dev`, JSON-safe."""
    bucket: dict[str, Any] = {}
    for name in DURABLE_FIELDS:
        table: dict[str, Any] = getattr(state, name)
        if dev in table:
            value = table.pop(dev)
            bucket[name] = asdict(value) if isinstance(value, Demotion) else value
    return bucket


def _drop_transient(state: State, dev: str) -> None:
    for name in TRANSIENT_FIELDS:
        getattr(state, name).pop(dev, None)


def _put(state: State, dev: str, bucket: dict[str, Any]) -> None:
    """Install a bucket under `dev`; a demotion is re-addressed to the name."""
    for name, value in bucket.items():
        if name not in DURABLE_FIELDS:
            continue
        if name == "demoted":
            try:
                value = Demotion(**{**value, "dev": dev})
            except TypeError:
                continue
        getattr(state, name)[dev] = value


def _kind(info: DeviceInfo) -> str:
    return info.usb_id or "builtin"


def track_identities(
    state: State, devices: dict[str, DeviceInfo], cycle_n: int
) -> None:
    """Re-key state when an adapter changes name, park the state of adapters
    that are not seen, and migrate a name-keyed (legacy) file once.

    Three passes, because two names can swap in one cycle: first park what
    a renamed name held, then move the state of an adapter that reappeared
    under a new name while its old name is gone, then bind every observed
    name to its identity, unparking what belongs to it.
    """
    keyed = {dev: info.key for dev, info in devices.items() if info.key}
    holders = {key: dev for dev, key in state.identities.items()}
    for dev, key in keyed.items():
        old = state.identities.get(dev)
        if old is None or old == key:
            continue
        state.parked[old] = _take(state, dev)
        _drop_transient(state, dev)
        del state.identities[dev]
        log.warning(
            "event=identity_parked cycle=%s dev=%s id=%s reason=the name now carries %s",
            cycle_n,
            dev,
            old,
            key,
        )
    for dev, key in keyed.items():
        holder = holders.get(key)
        if holder is None or holder == dev or holder in devices:
            continue
        if state.identities.get(holder) != key:
            continue
        state.parked[key] = _take(state, holder)
        _drop_transient(state, holder)
        del state.identities[holder]
        log.warning(
            "event=identity_renamed cycle=%s dev=%s id=%s from_dev=%s",
            cycle_n,
            dev,
            key,
            holder,
        )
    for dev, key in keyed.items():
        if state.identities.get(dev) != key:
            _bind(state, dev, key, devices[dev], cycle_n)
    for dev, info in devices.items():
        state.known_devices[dev] = _kind(info)


def _bind(state: State, dev: str, key: str, info: DeviceInfo, cycle_n: int) -> None:
    """Attach identity `key` to name `dev`: unpark the adapter's own state,
    or discard legacy state that belonged to a different adapter, or adopt
    what the name holds (the one-time migration of a name-keyed file)."""
    legacy = state.known_devices.get(dev)
    if key in state.parked:
        _take(state, dev)
        _drop_transient(state, dev)
        bucket = state.parked.pop(key)
        _put(state, dev, bucket)
        log.warning(
            "event=identity_returned cycle=%s dev=%s id=%s carried=%s",
            cycle_n,
            dev,
            key,
            ",".join(sorted(bucket)) or "-",
        )
    elif legacy is not None and legacy != _kind(info):
        discarded = _take(state, dev)
        _drop_transient(state, dev)
        log.warning(
            "event=identity_mismatch cycle=%s dev=%s id=%s legacy=%s discarded=%s",
            cycle_n,
            dev,
            key,
            legacy,
            ",".join(sorted(discarded)) or "-",
        )
    else:
        log.info(
            "event=identity_seen cycle=%s dev=%s id=%s adopted=%s",
            cycle_n,
            dev,
            key,
            "legacy state" if legacy is not None else "-",
        )
    state.identities[dev] = key


def absent_issues(state: State, devices: dict[str, DeviceInfo]) -> dict[str, str]:
    """Names on record that NetworkManager does not list right now. A name
    whose adapter was seen under another name is not absent: the second
    pass of `track_identities` has already moved its state and record."""
    out: dict[str, str] = {}
    for dev, kind in state.known_devices.items():
        if dev in devices:
            continue
        out[dev] = f"absent: not seen by NetworkManager ({kind}); " + (
            "unplugged, or the driver is not bound"
            if kind != "builtin"
            else "the driver is gone"
        )
    return out
