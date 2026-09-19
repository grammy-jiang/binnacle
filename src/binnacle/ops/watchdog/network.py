"""NetworkManager/Wi-Fi observations and profile helpers."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.hardware import usb_node_of, usb_speed_of
from binnacle.ops.watchdog.model import DeviceInfo, Preference, State


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
