"""Inventory, issue, cycle-summary, and snapshot reporting."""

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone

from binnacle import uplink
from binnacle.ops.watchdog.command import Run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.diagnostics import describe_issues
from binnacle.ops.watchdog.inventory import inventory_line
from binnacle.ops.watchdog.model import Action, DeviceInfo, Preference, State
from binnacle.ops.watchdog.network import wifi_profiles
from binnacle.ops.watchdog.tunnel import _log_issues
from binnacle.uplink import ProbeResult, Route

log = logging.getLogger("binnacle.watchdog")


def record_cycle(
    state: State,
    policy: Policy,
    run: Run,
    *,
    started: float,
    cycle_n: int,
    now: float,
    devices: dict[str, DeviceInfo],
    preferences: dict[str, Preference],
    probes: dict[str, ProbeResult],
    radio: bool | None,
    paused_until: float | None,
    health: dict[str, str],
    active: Route | None,
    routes: list[Route],
    planned: str,
    done: list[Action],
    services_note: str,
    tunnel_note: str,
) -> None:
    n = cycle_n
    now_cycle = now
    prefs = preferences

    for dev, info in devices.items():
        state.last_devices[dev] = info.describe(
            state.usb_target.get(dev, state.usb_best_speed.get(dev))
        )
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
