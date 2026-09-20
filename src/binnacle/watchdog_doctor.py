"""Host-specific diagnostics for the watchdog companion.

This module may depend on Binnacle core diagnostics. Core Binnacle modules
must not import this module or any other watchdog companion module.
"""

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from binnacle import units
from binnacle.doctor import (
    Check,
    Systemctl,
    _tail_lines,
    check_uplink,
    fail,
    ok,
    systemctl,
    unit_state,
    warn,
)
from binnacle.watchdog_config import get_watchdog_settings
from binnacle.watchdog_unit import OWNER, WATCHDOG_UNIT, render_watchdog_unit
from binnacle.watchlog import fetch_journal


def check_pause(pause_file: Path) -> list[Check]:
    """A paused watchdog observes but never acts."""
    if not pause_file.exists():
        return []
    try:
        until = float(pause_file.read_text().strip() or "0")
    except (OSError, ValueError):
        return [warn("watchdog", f"pause file {pause_file} unreadable")]
    if until <= time.time():
        return []
    stamp = datetime.fromtimestamp(until, timezone.utc).isoformat(timespec="seconds")
    return [
        warn(
            "watchdog",
            f"paused until {stamp}: it observes but takes no action",
            "`binnacle-watchdog resume` ends the pause",
        )
    ]


def check_privileges(
    run: Callable[..., "subprocess.CompletedProcess[str]"] | None = None,
) -> list[Check]:
    """The watchdog's USB resets and driver reloads run as root through
    `sudo -n`; without passwordless sudo those rungs fail silently."""
    runner = run or (
        lambda *a, **k: subprocess.run(
            a, capture_output=True, text=True, check=False, timeout=15
        )
    )
    try:
        proc = runner("sudo", "-n", "true")
    except (OSError, subprocess.TimeoutExpired) as e:
        return [fail("privileges", f"sudo -n true could not run: {e}")]
    if proc.returncode == 0:
        return [
            ok("privileges", "sudo -n works (USB resets and driver reloads can run)")
        ]
    return [
        fail(
            "privileges",
            "sudo -n is refused: the watchdog cannot reset the USB adapter",
            "grant this user NOPASSWD sudo (or at least for sh, python3 and iw)",
        )
    ]


def check_watchdog(
    unit: str,
    state_file: Path,
    stale_after_s: float = 180.0,
    run: Systemctl = systemctl,
    now: Callable[[], datetime] | None = None,
    fast_interval_s: float = 0.0,
) -> list[Check]:
    """Is the watchdog running, has it moved any route, and is its fast
    path (the 5 s failover thread) still ticking?"""
    out: list[Check] = []
    state = unit_state(unit, run)
    if state == "active":
        out.append(ok("watchdog", f"{unit} active"))
    else:
        out.append(
            warn(
                "watchdog",
                f"{unit} is {state}; a wedged uplink will not fail over",
                f"systemctl --user enable --now {unit}",
            )
        )
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        out.append(
            warn("watchdog", f"no state at {state_file} (no cycle has completed yet)")
        )
        return out
    stamp = raw.get("last_cycle") or ""
    current = (now or (lambda: datetime.now(timezone.utc)))()
    try:
        age = (current - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        age = None
    if age is None:
        out.append(warn("watchdog", f"last cycle timestamp {stamp!r} unreadable"))
    elif age > stale_after_s:
        out.append(
            warn(
                "watchdog",
                f"last cycle {int(age)} s ago (over {int(stale_after_s)} s); "
                "the loop may be stuck",
                f"journalctl --user -u {unit} -n 50",
            )
        )
    else:
        summary = ", ".join(
            f"{d}: {s}" for d, s in (raw.get("last_summary") or {}).items()
        )
        out.append(
            ok("watchdog", f"last cycle {int(age)} s ago; {summary or 'no routes'}")
        )
        profiles = raw.get("last_profiles") or {}
        if profiles:
            shown = ", ".join(f"{d} on {p}" for d, p in profiles.items())
            out.append(ok("watchdog", f"profiles: {shown}"))
        levels = raw.get("last_devices") or {}
        if levels:
            shown = ", ".join(f"{d}: {t}" for d, t in levels.items())
            out.append(ok("watchdog", f"levels: {shown}"))
        fast_last = raw.get("fast_last")
        if (
            fast_interval_s > 0
            and isinstance(fast_last, (int, float))
            and fast_last > 0
        ):
            fast_age = current.timestamp() - float(fast_last)
            limit = max(60.0, 6 * fast_interval_s)
            if fast_age > limit:
                out.append(
                    warn(
                        "watchdog",
                        f"fast path heartbeat {int(fast_age)} s old (over {int(limit)} s); "
                        "the 5 s failover thread may be stuck",
                        f"journalctl --user -u {unit} -n 200 | grep fast_path",
                    )
                )
    for dev, text in (raw.get("issues") or {}).items():
        out.append(
            warn(
                "watchdog",
                f"{dev} is below its highest level: {text}",
                "repaired on the watchdog's schedule; `binnacle-watchdog status` "
                "shows the details",
            )
        )
    demoted = raw.get("demoted") or {}
    attempts = raw.get("usb_attempts") or {}
    for dev, d in demoted.items():
        tries = attempts.get(dev, 0)
        if d.get("kind") == "preference":
            out.append(
                warn(
                    "watchdog",
                    f"{dev} is demoted since {d.get('since', '?')} while it moves "
                    f"to profile {d.get('target', '?')}: {d.get('reason', '')}",
                    f"restored automatically once {dev} passes the probes on the "
                    "new profile",
                )
            )
            continue
        out.append(
            warn(
                "watchdog",
                f"{dev} is demoted since {d.get('since', '?')} "
                f"(metric raised from {d.get('original_metric')}): {d.get('reason', '')}"
                + (f"; {tries} USB re-enumeration(s) so far" if tries else ""),
                f"restored automatically once {dev} passes the probes again",
            )
        )
    return out


def _kv_line(line: str) -> dict[str, str]:
    """`key=value` fields of one ledger line (the cron scripts' log format)."""
    out: dict[str, str] = {}
    for field in line.split():
        key, sep, value = field.partition("=")
        if sep:
            out[key] = value
    return out


def check_driver_stability(
    log_file: Path,
    state_file: Path,
    stale_after_h: float = 36.0,
    now: Callable[[], float] | None = None,
) -> list[Check]:
    """Surface the daily wlan1 USB 3 stability sample, when that job exists.

    The sample itself is taken by ~/.local/bin/rtl8812au-stability.sh (cron,
    daily): driver errors, USB faults, watchdog demotions and the route, all
    since the previous sample. Seven consecutive clean days promote USB 3
    mode into the maintain-rtl8812au baseline automatically. This check only
    reads the ledger, so `doctor` shows the streak without anyone opening
    the mail; it is skipped entirely on a host without the job.
    """
    if not log_file.exists():
        return []
    samples = [
        _kv_line(line)
        for line in _tail_lines(log_file, max_bytes=64 * 1024)
        if " mode=sample " in line
    ]
    if not samples:
        return [warn("driver", f"stability ledger {log_file} has no sample yet")]
    last = samples[-1]
    try:
        age_h = ((now or time.time)() - float(last.get("epoch", "0"))) / 3600
    except ValueError:
        return [warn("driver", "stability ledger: last sample has no readable epoch")]
    state: dict[str, str] = {}
    try:
        state = _kv_line(state_file.read_text(encoding="utf-8").replace("\n", " "))
    except OSError:
        pass
    promoted = state.get("PROMOTED_TS", "0") not in ("", "0")
    streak = last.get("streak", "?")
    baseline = last.get("baseline", "?")
    out: list[Check] = []
    if age_h > stale_after_h:
        out.append(
            warn(
                "driver",
                f"last wlan1 stability sample is {age_h:.0f} h old (over {stale_after_h:.0f} h)",
                "the daily cron job may not be running: crontab -l | grep stability",
            )
        )
    if last.get("clean") == "1":
        tail = (
            f"USB 3 promoted to the skill baseline (mode {baseline})"
            if promoted or baseline == "1"
            else f"streak {streak}/7 toward promotion (baseline still mode {baseline})"
        )
        out.append(
            ok("driver", f"wlan1 stable at last sample ({age_h:.0f} h ago); {tail}")
        )
    else:
        detail = (
            f"usbmode={last.get('usbmode', '?')} usb={last.get('usb', '?')} "
            f"assoc={last.get('assoc', '?')} primary={last.get('primary', '?')} "
            f"rtw_err={last.get('rtw_err', '?')} usb_fault={last.get('usb_fault', '?')} "
            f"demoted={last.get('demoted', '?')}"
        )
        out.append(
            warn(
                "driver",
                f"wlan1 stability sample broken ({age_h:.0f} h ago), streak reset: {detail}",
                f"the job mailed the reasons; ledger {log_file}",
            )
        )
    return out


_QUIET_EVENTS = re.compile(
    r"event=(fast_failure|fast_failover|fast_failover_blocked|uplink_demoted|"
    r"uplink_reset|uplink_usb_reset|uplink_driver_reload|service_restart|"
    r"demote_failed|restore_failed|actions_failed)\b"
)


@dataclass(slots=True)
class QuietReport:
    """The deploy check's verdict: `ok` when the unit may be restarted now."""

    ok: bool
    lines: list[str]


def quiet_moment(
    state_file: Path,
    window_s: float = 60.0,
    stale_after_s: float = 180.0,
    unit: str = WATCHDOG_UNIT,
    journal: Callable[[str, str], list[str]] | None = None,
    now: Callable[[], datetime] | None = None,
) -> QuietReport:
    """May the unit be restarted now? The deploy rule (2026-09-14): no
    demotion in flight, every grade healthy, a recent cycle, and no fast
    failure or repair in the last `window_s` seconds. A restart mid-episode
    resets the transient counters and delays the repair (three minutes on
    2026-09-13); a restart while a route is failing loses the fast path's
    count (the 2026-09-14 08:44 event)."""
    lines: list[str] = []
    waits = 0

    def verdict(good: bool, text: str) -> None:
        nonlocal waits
        waits += 0 if good else 1
        lines.append(f"  [{'ok  ' if good else 'wait'}] {text}")

    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return QuietReport(False, [f"  [wait] state {state_file} unreadable: {e}"])

    demoted = raw.get("demoted") or {}
    verdict(
        not demoted,
        "no demotion in flight"
        if not demoted
        else "demoted: "
        + ", ".join(
            f"{dev} ({d.get('kind', '?')} since {d.get('since', '?')})"
            for dev, d in demoted.items()
        ),
    )
    grades = raw.get("last_grade") or {}
    unhealthy = {dev: g for dev, g in grades.items() if g != "healthy"}
    if not grades:
        verdict(False, "no grades recorded yet")
    elif unhealthy:
        verdict(
            False, "not healthy: " + ", ".join(f"{d}={g}" for d, g in unhealthy.items())
        )
    else:
        verdict(True, "every grade healthy: " + ", ".join(sorted(grades)))
    stamp = raw.get("last_cycle") or ""
    current = (now or (lambda: datetime.now(timezone.utc)))()
    try:
        age: float | None = (current - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        age = None
    if age is None:
        verdict(False, f"last cycle timestamp {stamp!r} unreadable")
    else:
        verdict(
            age <= stale_after_s,
            f"last cycle {int(age)} s ago (limit {int(stale_after_s)} s)",
        )
    fetch = journal or fetch_journal
    try:
        recent = [
            ln for ln in fetch(unit, f"-{int(window_s)}s") if _QUIET_EVENTS.search(ln)
        ]
    except (OSError, subprocess.SubprocessError) as e:
        verdict(False, f"journal unreadable: {e}")
        return QuietReport(False, lines)
    if recent:
        m = re.search(r"event=\S+(?: cycle=\S+)?(?: dev=\S+)?", recent[-1])
        verdict(
            False,
            f"{len(recent)} failure or repair event(s) in the last {int(window_s)} s; "
            f"last: {m.group(0) if m else recent[-1]}",
        )
    else:
        verdict(True, f"no failure or repair in the last {int(window_s)} s")
    return QuietReport(waits == 0, lines)


def run_all(probe: bool = True) -> list[Check]:
    """Run host-specific watchdog and uplink diagnostics."""
    settings = get_watchdog_settings()
    checks: list[Check] = []
    if probe:
        checks += check_uplink(
            host=settings.upstream_host,
            timeout=settings.probe_timeout_s,
            fallback_nameserver=settings.dns_fallback,
        )
    checks += check_watchdog(
        WATCHDOG_UNIT,
        settings.state_file,
        settings.stale_after_s,
        fast_interval_s=settings.fast_interval_s,
    )
    checks += units.check_unit_drift(
        units.UNIT_DIR / WATCHDOG_UNIT,
        OWNER,
        render_watchdog_unit,
        "watchdog",
        "binnacle-watchdog setup",
    )
    checks += units.check_unit_process(
        WATCHDOG_UNIT,
        "watchdog",
        "binnacle-watchdog setup",
        f"binnacle-watchdog deploy-check && systemctl --user restart {WATCHDOG_UNIT}",
    )
    checks += check_pause(settings.state_file.with_suffix(".pause"))
    checks += check_privileges()
    checks += check_driver_stability(
        settings.stability_log,
        settings.stability_state,
        settings.stability_stale_after_h,
    )
    return checks
