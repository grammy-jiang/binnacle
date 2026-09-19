"""One observe-decide-act watchdog cycle."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from binnacle import uplink
from binnacle.ops.watchdog.actions import apply_action
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.fast import _still_safe
from binnacle.ops.watchdog.hardware import (
    host_health,
    usb_adapters_without_netdev,
)
from binnacle.ops.watchdog.lock import ACT_LOCK
from binnacle.ops.watchdog.maintenance import maintain_services
from binnacle.ops.watchdog.model import (
    Action,
    Preference,
    State,
    band_label,
    grade_of,
    grade_rank,
)
from binnacle.ops.watchdog.network import (
    observe_devices,
    preferences,
    stranded_metrics,
    wifi_link_freq,
    wifi_radio_enabled,
)
from binnacle.ops.watchdog.policy import evaluate
from binnacle.ops.watchdog.reporting import record_cycle
from binnacle.ops.watchdog.services import pause_until
from binnacle.ops.watchdog.tunnel import _log_decision, after_failover

log = logging.getLogger("binnacle.watchdog")


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
    services_note, tunnel_note = maintain_services(
        state,
        policy,
        run,
        routes,
        probes,
        devices,
        cycle_n=n,
        now=now_cycle,
        holding=holding,
    )

    record_cycle(
        state,
        policy,
        run,
        started=started,
        cycle_n=n,
        now=now_cycle,
        devices=devices,
        preferences=prefs,
        probes=probes,
        radio=radio,
        paused_until=paused_until,
        health=health,
        active=active,
        routes=routes,
        planned=planned,
        done=done,
        services_note=services_note,
        tunnel_note=tunnel_note,
    )
    state.save(state_file)
    return done
