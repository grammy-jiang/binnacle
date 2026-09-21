"""Side-effecting watchdog repair actions."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import (
    DEFAULT_POLICY,
    Policy,
    usb_backoff,
    usb_reset_method,
)
from binnacle.ops.watchdog.hardware import driver_reload, usb_reset_device
from binnacle.ops.watchdog.model import Action, Demotion, State
from binnacle.ops.watchdog.network import (
    bound_profiles,
    device_profiles,
    profile_metric,
    profile_never_default,
)
from binnacle.ops.watchdog.schedule import recent_wedges
from binnacle.uplink import Route

log = logging.getLogger("binnacle.watchdog")


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


@dataclass
class _ActionContext:
    action: Action
    routes: list[Route]
    state: State
    run: Run
    now: float
    policy: Policy
    profiles: dict[str, str]
    cycle_n: int
    before: str
    started: float

    def took_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000


def _apply_demote(ctx: _ActionContext) -> bool:
    action = ctx.action
    profile = ctx.profiles.get(action.dev)
    route = next((r for r in ctx.routes if r.dev == action.dev), None)
    if profile is None or route is None:
        log.error("event=demote_skipped dev=%s reason=no_profile", action.dev)
        return False
    metric = action.metric or 900
    names = [n for n in bound_profiles(action.dev, ctx.run) if n != profile]
    if action.tag == "preference" and action.profile and action.profile not in names:
        names.append(action.profile)

    others: dict[str, int] = {}
    for name in names:
        original = profile_metric(name, ctx.run)
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
        if not _modify_metric(name, metric, ctx.run):
            for done in raised:
                _modify_metric(done, others[done], ctx.run)
            return False
        raised.append(name)

    if not set_route_metric(profile, action.dev, metric, ctx.run):
        _modify_metric(profile, route.metric, ctx.run)
        for done in raised:
            _modify_metric(done, others[done], ctx.run)
        log.error(
            "event=demote_failed cycle=%s dev=%s profile=%s reverted=%s duration_ms=%.0f",
            ctx.cycle_n,
            action.dev,
            profile,
            ",".join(raised) or "-",
            ctx.took_ms(),
        )
        return False

    kind = action.tag if action.tag in ("preference", "usb_speed") else "wedged"
    target = action.profile if action.tag == "preference" else ""
    ctx.state.demoted[action.dev] = Demotion(
        dev=action.dev,
        profile=profile,
        original_metric=route.metric,
        since=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        reason=action.reason,
        kind=kind,
        target=target or "",
        target_metric=others.get(target) if target else None,
        since_ts=ctx.now,
        others=others,
    )
    ctx.state.failures[action.dev] = 0
    ctx.state.failure_since.pop(action.dev, None)
    if kind == "wedged":
        ctx.state.usb_attempts.pop(action.dev, None)
        times = recent_wedges(ctx.state, action.dev, ctx.policy, ctx.now)
        times.append(ctx.now)
        ctx.state.wedge_times[action.dev] = times
    log.warning(
        "event=uplink_demoted cycle=%s dev=%s before=%s trigger=%s metric=%s->%s kind=%s "
        "profile=%s others=%s duration_ms=%.0f reason=%s",
        ctx.cycle_n,
        action.dev,
        ctx.before,
        action.trigger,
        route.metric,
        action.metric,
        kind,
        profile,
        ",".join(sorted(others)) or "-",
        ctx.took_ms(),
        action.reason,
    )
    return True


def _apply_restore(ctx: _ActionContext) -> bool:
    action = ctx.action
    demotion = ctx.state.demoted.get(action.dev)
    if demotion is None:
        return False
    to_restore = dict(demotion.others)
    if demotion.target and demotion.target_metric is not None:
        to_restore.setdefault(demotion.target, demotion.target_metric)
    okay = _modify_metric(demotion.profile, demotion.original_metric, ctx.run)
    for name, original in to_restore.items():
        okay = _modify_metric(name, original, ctx.run) and okay
    if not okay or not _reapply(action.dev, ctx.run):
        log.error(
            "event=restore_failed cycle=%s dev=%s profile=%s duration_ms=%.0f",
            ctx.cycle_n,
            action.dev,
            demotion.profile,
            ctx.took_ms(),
        )
        return False
    del ctx.state.demoted[action.dev]
    ctx.state.successes[action.dev] = 0
    ctx.state.usb_attempts.pop(action.dev, None)
    ctx.state.fast_demoted_streak.pop(action.dev, None)
    ctx.state.fast_demoted_last_fail.pop(action.dev, None)
    log.warning(
        "event=uplink_restored cycle=%s dev=%s before=%s metric=%s kind=%s "
        "profile=%s others=%s demoted_for_s=%.0f duration_ms=%.0f reason=%s",
        ctx.cycle_n,
        action.dev,
        ctx.before,
        demotion.original_metric,
        demotion.kind,
        demotion.profile,
        ",".join(sorted(to_restore)) or "-",
        ctx.now - demotion.since_ts if demotion.since_ts else -1.0,
        ctx.took_ms(),
        action.reason,
    )
    return True


def _apply_reset(ctx: _ActionContext) -> bool:
    action = ctx.action
    ctx.state.last_reset[action.dev] = ctx.now
    if action.tag == "no_route":
        profile_name = action.profile or ctx.profiles.get(action.dev)
        if profile_name and profile_never_default(profile_name, ctx.run):
            log.info(
                "event=reset_skipped cycle=%s dev=%s profile=%s reason=never_default",
                ctx.cycle_n,
                action.dev,
                profile_name,
            )
            return False
        if _reapply(action.dev, ctx.run):
            log.warning(
                "event=uplink_reapply cycle=%s dev=%s before=%s profile=%s "
                "duration_ms=%.0f reason=%s",
                ctx.cycle_n,
                action.dev,
                ctx.before,
                profile_name,
                ctx.took_ms(),
                action.reason,
            )
            return True
    if action.tag == "preference":
        ctx.state.prefer_attempts[action.dev] = (
            ctx.state.prefer_attempts.get(action.dev, 0) + 1
        )
        ctx.state.last_prefer[action.dev] = ctx.now
    profile = action.profile or ctx.profiles.get(action.dev)
    okay = reset_device(action.dev, profile, ctx.run)
    if action.tag == "fallback" and action.dev in ctx.state.demoted:
        ctx.state.demoted[action.dev].kind = "wedged"
        ctx.state.demoted[
            action.dev
        ].reason = f"{action.reason}; escalates as a wedge from here"
    log.warning(
        "event=uplink_reset cycle=%s dev=%s before=%s trigger=%s ok=%s tag=%s profile=%s "
        "duration_ms=%.0f reason=%s",
        ctx.cycle_n,
        action.dev,
        ctx.before,
        action.trigger,
        okay,
        action.tag,
        profile,
        ctx.took_ms(),
        action.reason,
    )
    return okay


def _apply_reload(ctx: _ActionContext) -> bool:
    action = ctx.action
    attempt = ctx.state.reload_attempts.get(action.dev, 0) + 1
    ctx.state.reload_attempts[action.dev] = attempt
    ctx.state.last_reload[action.dev] = ctx.now
    okay, detail = driver_reload(action.dev, ctx.run)
    log.warning(
        "event=uplink_driver_reload cycle=%s dev=%s before=%s attempt=%s ok=%s "
        "duration_ms=%.0f reason=%s detail=%s",
        ctx.cycle_n,
        action.dev,
        ctx.before,
        attempt,
        okay,
        ctx.took_ms(),
        action.reason,
        detail,
    )
    return okay


def _apply_usb_reset(ctx: _ActionContext) -> bool:
    action = ctx.action
    if action.tag == "usb_speed":
        attempt = ctx.state.usb_speed_attempts.get(action.dev, 0) + 1
        ctx.state.usb_speed_attempts[action.dev] = attempt
        ctx.state.last_usb_speed_reset[action.dev] = ctx.now
        wait = usb_backoff(ctx.policy.usb_speed_schedule, attempt)
    else:
        attempt = ctx.state.usb_attempts.get(action.dev, 0) + 1
        ctx.state.usb_attempts[action.dev] = attempt
        ctx.state.last_usb_reset[action.dev] = ctx.now
        wait = usb_backoff(ctx.policy.usb_reset_schedule, attempt + 1)
    method = usb_reset_method(ctx.policy, attempt)
    okay, detail = usb_reset_device(action.dev, ctx.policy, ctx.run, method=method)
    log.warning(
        "event=uplink_usb_reset cycle=%s dev=%s before=%s attempt=%s method=%s ok=%s "
        "tag=%s next_in_s=%.0f duration_ms=%.0f reason=%s detail=%s",
        ctx.cycle_n,
        action.dev,
        ctx.before,
        attempt,
        method,
        okay,
        action.tag,
        wait,
        ctx.took_ms(),
        action.reason,
        detail,
    )
    return okay


def apply_action(
    action: Action,
    routes: list[Route],
    state: State,
    run: Run = _run,
    now: float | None = None,
    policy: Policy = DEFAULT_POLICY,
) -> bool:
    """Carry out one action and record it in state."""
    resolved_now = time.time() if now is None else now
    ctx = _ActionContext(
        action=action,
        routes=routes,
        state=state,
        run=run,
        now=resolved_now,
        policy=policy,
        profiles=device_profiles(run),
        cycle_n=state.cycle_n,
        before=state.last_grade.get(action.dev, "-"),
        started=time.perf_counter(),
    )
    handlers = {
        "demote": _apply_demote,
        "restore": _apply_restore,
        "reset": _apply_reset,
        "reload": _apply_reload,
        "usb_reset": _apply_usb_reset,
    }
    handler = handlers.get(action.kind)
    return handler(ctx) if handler is not None else False
