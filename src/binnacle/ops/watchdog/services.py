"""User/system service observations and pure service repair policy."""

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.model import DeviceInfo, State


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
        from binnacle.tunnel_doctor import scan_tunnel_log

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
