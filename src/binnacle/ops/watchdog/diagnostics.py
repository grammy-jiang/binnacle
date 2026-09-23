"""Issue summaries for watchdog state."""

from binnacle.ops.watchdog.model import DeviceInfo, Preference, State
from binnacle.uplink import ProbeResult


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
            target = state.usb_target.get(dev, state.usb_best_speed.get(dev))
            if target is not None and info.usb_speed < target:
                mode = state.usb_mode.get(dev, "learned")
                parts.append(
                    f"USB link {info.usb_speed} Mbit/s, best seen {target}"
                    if mode == "learned"
                    else f"USB link {info.usb_speed} Mbit/s, target {target} ({mode})"
                )
                if dev in state.usb_speed_exhausted:
                    parts.append("repair exhausted")
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
