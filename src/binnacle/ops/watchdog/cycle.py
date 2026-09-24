"""One observe-decide-act watchdog cycle."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from binnacle import uplink
from binnacle.ops.watchdog.actions import apply_action
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy, usb_param_names
from binnacle.ops.watchdog.device_identity import absent_issues, track_identities
from binnacle.ops.watchdog.fast import _still_safe
from binnacle.ops.watchdog.hardware import (
    host_health,
    usb_adapters_without_netdev,
)
from binnacle.ops.watchdog.lock import ACT_LOCK
from binnacle.ops.watchdog.maintenance import maintain_services
from binnacle.ops.watchdog.model import (
    Action,
    DeviceInfo,
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


@dataclass(frozen=True)
class _Observed:
    routes: list[uplink.Route]
    routes_known: bool
    probes: dict[str, uplink.ProbeResult]
    devices: dict[str, DeviceInfo]
    radio: bool | None
    health: dict[str, str]
    active: uplink.Route | None
    active_probe: uplink.ProbeResult | None


def _pause_state(
    state: State, policy: Policy, cycle_n: int
) -> tuple[float | None, bool]:
    paused_until = pause_until(policy.pause_file)
    holding = paused_until is not None or policy.dry_run
    if (paused_until is not None) != state.was_paused:
        log.warning(
            "event=%s cycle=%s until=%s",
            "pause_started" if paused_until is not None else "pause_ended",
            cycle_n,
            (
                datetime.fromtimestamp(paused_until, timezone.utc).isoformat(
                    timespec="seconds"
                )
                if paused_until is not None
                else "-"
            ),
        )
        state.was_paused = paused_until is not None
    return paused_until, holding


def _log_probes(probes: dict[str, uplink.ProbeResult], cycle_n: int) -> None:
    for dev, probe in probes.items():
        level = logging.INFO if probe.healthy else logging.WARNING
        log.log(
            level,
            "event=uplink_probe cycle=%s dev=%s %s",
            cycle_n,
            dev,
            probe.detail(),
        )
        if not probe.healthy:
            for layer, err in probe.errors.items():
                log.warning(
                    "event=uplink_probe_error cycle=%s dev=%s layer=%s %s",
                    cycle_n,
                    dev,
                    layer,
                    err,
                )


def _observe(
    state: State,
    policy: Policy,
    cycle_n: int,
    now_cycle: float,
    holding: bool,
    host: str,
    timeout: float,
    run: Run,
) -> _Observed:
    routes, routes_known = uplink.read_default_routes(run)
    if not routes_known:
        log.error("event=routes_unreadable cycle=%s", cycle_n)
    probes = uplink.probe_all(
        routes,
        host=host,
        timeout=timeout,
        run=run,
        fallback_nameserver=policy.dns_fallback,
    )
    devices = observe_devices(run, policy.usb_reset_ids, usb_param_names(policy))
    radio = wifi_radio_enabled(run)
    state.extra_issues = {}

    for dev, probe in probes.items():
        if probe.errors.get("probe"):
            log.error(
                "event=uplink_probe_unavailable cycle=%s dev=%s %s",
                cycle_n,
                dev,
                probe.errors["probe"],
            )

    active = uplink.active_route(routes)
    active_probe = probes.get(active.dev) if active is not None else None
    state.uplink_ok_cycles = (
        state.uplink_ok_cycles + 1
        if active_probe is not None and active_probe.healthy
        else 0
    )

    track_identities(state, devices, cycle_n)
    state.extra_issues.update(absent_issues(state, devices))
    state.extra_issues.update(usb_adapters_without_netdev(policy.usb_reset_ids))
    if now_cycle - state.last_reconcile >= policy.reconcile_interval_s:
        state.last_reconcile = now_cycle
        state.extra_issues.update(stranded_metrics(state, policy, run))

    health = host_health(run)
    if health.get("flags") and any(" now" in f for f in health["flags"].split(", ")):
        state.extra_issues["host"] = f"power/thermal: {health['flags']}"

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
            cycle_n,
            proc.returncode == 0,
            proc.stderr.strip(),
        )

    state.last_cycle = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state.last_summary = {dev: probe.summary() for dev, probe in probes.items()}
    _log_probes(probes, cycle_n)

    return _Observed(
        routes=routes,
        routes_known=routes_known,
        probes=probes,
        devices=devices,
        radio=radio,
        health=health,
        active=active,
        active_probe=active_probe,
    )


def _preferences(
    state: State,
    policy: Policy,
    cycle_n: int,
    now_cycle: float,
    observed: _Observed,
    run: Run,
) -> dict[str, Preference]:
    if not (policy.prefer_enabled or policy.down_repair):
        return {}

    devs = sorted({r.dev for r in observed.routes} | set(observed.devices))
    prefs = preferences(devs, run)
    due = {
        dev
        for dev, pref in prefs.items()
        if pref.target
        and not pref.visible
        and observed.active_probe is not None
        and observed.active_probe.healthy
        and now_cycle - state.last_scan.get(dev, 0.0) >= policy.prefer_check_interval_s
    }
    if due:
        for dev in due:
            state.last_scan[dev] = now_cycle
        prefs.update(preferences(sorted(due), run, rescan_for=due))

    for dev, pref in prefs.items():
        band = band_label(wifi_link_freq(dev, run)) if pref.current else "-"
        state.last_profiles[dev] = f"{pref.current or 'none'} ({band})"
        if pref.target:
            log.log(
                logging.WARNING if pref.visible else logging.INFO,
                "event=uplink_profile cycle=%s dev=%s profile=%s band=%s preferred=%s in_range=%s",
                cycle_n,
                dev,
                pref.current or "none",
                band,
                pref.target,
                pref.visible,
            )
    return prefs


def _record_transitions(
    state: State,
    cycle_n: int,
    now_cycle: float,
    observed: _Observed,
) -> None:
    routed = {r.dev for r in observed.routes}
    devs = sorted(
        set(observed.devices) | set(observed.probes) | set(state.known_devices)
    )
    for dev in devs:
        grade = grade_of(
            observed.probes.get(dev),
            observed.devices.get(dev),
            dev in routed,
        )
        previous = state.last_grade.get(dev)
        if grade == "degraded" and previous == "healthy":
            state.degraded_streak[dev] = state.degraded_streak.get(dev, 0) + 1
            if state.degraded_streak[dev] < 2:
                continue
        else:
            state.degraded_streak[dev] = 0
        if previous == grade:
            continue

        since = state.grade_since.get(dev)
        worse = previous is not None and grade_rank(grade) > grade_rank(previous)
        dinfo = observed.devices.get(dev)
        role = (
            "active"
            if observed.active and dev == observed.active.dev
            else "standby"
            if dev in routed
            else "none"
        )
        detail = (
            observed.probes[dev].detail()
            if dev in observed.probes
            else observed.devices[dev].describe()
            if dev in observed.devices
            else "absent"
        )
        log.log(
            logging.WARNING if worse else logging.INFO,
            "event=transition cycle=%s dev=%s from=%s to=%s after_s=%s nm=%s "
            "profile=%s role=%s detail=%s",
            cycle_n,
            dev,
            previous or "-",
            grade,
            f"{now_cycle - since:.0f}" if since else "-",
            dinfo.nm_state if dinfo else "-",
            (dinfo.profile or "-") if dinfo else "-",
            role,
            detail,
        )
        state.last_grade[dev] = grade
        state.grade_since[dev] = now_cycle


def _execute_actions(
    state: State,
    policy: Policy,
    cycle_n: int,
    now_cycle: float,
    paused_until: float | None,
    holding: bool,
    observed: _Observed,
    prefs: dict[str, Preference],
    run: Run,
) -> tuple[str, list[Action]]:
    decided_active = observed.active.dev if observed.active is not None else None
    with ACT_LOCK:
        actions = evaluate(
            observed.routes,
            observed.probes,
            state,
            policy,
            preferences=prefs,
            devices=observed.devices,
            routes_known=observed.routes_known,
        )
        planned = ",".join(f"{a.kind}:{a.dev}" for a in actions) or "-"
        if holding and actions:
            log.warning(
                "event=%s cycle=%s until=%s skipped=%s",
                "dry_run" if policy.dry_run else "paused",
                cycle_n,
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
        quick = [a for a in actions if a.kind in ("demote", "restore")]
        slow = [a for a in actions if a.kind not in ("demote", "restore")]
        done: list[Action] = []
        for action in quick:
            if apply_action(action, observed.routes, state, run, policy=policy):
                done.append(action)
                if action.kind == "demote" and action.tag == "wedged":
                    after_failover(state, policy, run, now_cycle)

    skipped: list[Action] = []
    for action in slow:
        if not _still_safe(action, decided_active, state, run):
            skipped.append(action)
            log.warning(
                "event=action_skipped cycle=%s kind=%s dev=%s reason=became the active route",
                cycle_n,
                action.kind,
                action.dev,
            )
            continue
        state.repair_in_flight[action.dev] = time.time()
        try:
            if apply_action(action, observed.routes, state, run, policy=policy):
                done.append(action)
        finally:
            state.repair_in_flight.pop(action.dev, None)

    failed = [a for a in actions if a not in done and a not in skipped]
    if failed:
        log.error(
            "event=actions_failed cycle=%s failed=%s",
            cycle_n,
            ",".join(f"{a.kind}:{a.dev}" for a in failed),
        )
    return planned, done


def cycle(
    state: State,
    policy: Policy,
    state_file: Path,
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
) -> list[Action]:
    """One observe-decide-act pass. Returns the actions taken."""
    started = time.perf_counter()
    state.cycle_n += 1
    cycle_n = state.cycle_n
    now_cycle = time.time()
    paused_until, holding = _pause_state(state, policy, cycle_n)
    observed = _observe(
        state,
        policy,
        cycle_n,
        now_cycle,
        holding,
        host,
        timeout,
        run,
    )
    prefs = _preferences(state, policy, cycle_n, now_cycle, observed, run)
    _record_transitions(state, cycle_n, now_cycle, observed)
    planned, done = _execute_actions(
        state,
        policy,
        cycle_n,
        now_cycle,
        paused_until,
        holding,
        observed,
        prefs,
        run,
    )

    for dev, rung, text in state.decisions:
        _log_decision(state, policy, cycle_n, now_cycle, dev, rung, text)
    for dev, old, new, cleared in state.policy_events:
        log.warning(
            "event=usb_speed_policy_changed cycle=%s dev=%s id=%s old=%s new=%s "
            "cleared=%s",
            cycle_n,
            dev,
            state.identities.get(dev, "-"),
            old,
            new,
            cleared,
        )
    state.policy_events = []
    services_note, tunnel_note = maintain_services(
        state,
        policy,
        run,
        observed.routes,
        observed.probes,
        observed.devices,
        cycle_n=cycle_n,
        now=now_cycle,
        holding=holding,
    )
    record_cycle(
        state,
        policy,
        run,
        started=started,
        cycle_n=cycle_n,
        now=now_cycle,
        devices=observed.devices,
        preferences=prefs,
        probes=observed.probes,
        radio=observed.radio,
        paused_until=paused_until,
        health=observed.health,
        active=observed.active,
        routes=observed.routes,
        planned=planned,
        done=done,
        services_note=services_note,
        tunnel_note=tunnel_note,
    )
    state.save(state_file)
    return done
