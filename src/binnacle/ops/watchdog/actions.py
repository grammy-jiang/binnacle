"""Side-effecting watchdog repair actions."""

import logging
import time
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


def apply_action(
    action: Action,
    routes: list[Route],
    state: State,
    run: Run = _run,
    now: float | None = None,
    policy: Policy = DEFAULT_POLICY,
) -> bool:
    """Carry out one action and record it in `state`.

    Every outcome is logged with the cycle number, what the device looked
    like before (`before=`), how long the commands took and the result.
    """
    now = time.time() if now is None else now
    profiles = device_profiles(run)
    n = state.cycle_n
    before = state.last_grade.get(action.dev, "-")
    started = time.perf_counter()

    def took() -> float:
        return (time.perf_counter() - started) * 1000

    if action.kind == "demote":
        profile = profiles.get(action.dev)
        route = next((r for r in routes if r.dev == action.dev), None)
        if profile is None or route is None:
            log.error("event=demote_skipped dev=%s reason=no_profile", action.dev)
            return False
        metric = action.metric or 900
        # Device-level: raise every profile bound to the device (and the
        # target of a preference move) first, so whatever NetworkManager
        # brings up after the repair still waits for the probes. No move
        # without knowing how to undo it.
        names = [n for n in bound_profiles(action.dev, run) if n != profile]
        if (
            action.tag == "preference"
            and action.profile
            and action.profile not in names
        ):
            names.append(action.profile)
        others: dict[str, int] = {}
        for name in names:
            original = profile_metric(name, run)
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
            if not _modify_metric(name, metric, run):
                for done in raised:
                    _modify_metric(done, others[done], run)
                return False
            raised.append(name)
        if not set_route_metric(profile, action.dev, metric, run):
            # The modify may have landed before the reapply failed: put the
            # active profile back too, or it sits at 900 with no record.
            _modify_metric(profile, route.metric, run)
            for done in raised:
                _modify_metric(done, others[done], run)
            log.error(
                "event=demote_failed cycle=%s dev=%s profile=%s reverted=%s duration_ms=%.0f",
                n,
                action.dev,
                profile,
                ",".join(raised) or "-",
                took(),
            )
            return False
        kind = action.tag if action.tag in ("preference", "usb_speed") else "wedged"
        target = action.profile if action.tag == "preference" else ""
        state.demoted[action.dev] = Demotion(
            dev=action.dev,
            profile=profile,
            original_metric=route.metric,
            since=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            reason=action.reason,
            kind=kind,
            target=target or "",
            target_metric=others.get(target) if target else None,
            since_ts=now,
            others=others,
        )
        state.failures[action.dev] = 0
        state.failure_since.pop(action.dev, None)
        if kind == "wedged":
            # A new episode: the USB schedule starts over, and the flap
            # damping remembers the wedge.
            state.usb_attempts.pop(action.dev, None)
            times = recent_wedges(state, action.dev, policy, now)
            times.append(now)
            state.wedge_times[action.dev] = times
        log.warning(
            "event=uplink_demoted cycle=%s dev=%s before=%s trigger=%s metric=%s->%s kind=%s "
            "profile=%s others=%s duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            action.trigger,
            route.metric,
            action.metric,
            kind,
            profile,
            ",".join(sorted(others)) or "-",
            took(),
            action.reason,
        )
        return True

    if action.kind == "restore":
        demotion = state.demoted.get(action.dev)
        if demotion is None:
            return False
        to_restore = dict(demotion.others)
        if demotion.target and demotion.target_metric is not None:
            to_restore.setdefault(demotion.target, demotion.target_metric)
        okay = _modify_metric(demotion.profile, demotion.original_metric, run)
        for name, original in to_restore.items():
            okay = _modify_metric(name, original, run) and okay
        if not okay or not _reapply(action.dev, run):
            log.error(
                "event=restore_failed cycle=%s dev=%s profile=%s duration_ms=%.0f",
                n,
                action.dev,
                demotion.profile,
                took(),
            )
            return False
        del state.demoted[action.dev]
        state.successes[action.dev] = 0
        state.usb_attempts.pop(action.dev, None)
        state.fast_demoted_streak.pop(action.dev, None)
        state.fast_demoted_last_fail.pop(action.dev, None)
        log.warning(
            "event=uplink_restored cycle=%s dev=%s before=%s metric=%s kind=%s "
            "profile=%s others=%s demoted_for_s=%.0f duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            demotion.original_metric,
            demotion.kind,
            demotion.profile,
            ",".join(sorted(to_restore)) or "-",
            now - demotion.since_ts if demotion.since_ts else -1.0,
            took(),
            action.reason,
        )
        return True

    if action.kind == "reset":
        state.last_reset[action.dev] = now
        if action.tag == "no_route":
            profile_name = action.profile or profiles.get(action.dev)
            if profile_name and profile_never_default(profile_name, run):
                log.info(
                    "event=reset_skipped cycle=%s dev=%s profile=%s reason=never_default",
                    n,
                    action.dev,
                    profile_name,
                )
                return False
            if _reapply(action.dev, run):
                log.warning(
                    "event=uplink_reapply cycle=%s dev=%s before=%s profile=%s "
                    "duration_ms=%.0f reason=%s",
                    n,
                    action.dev,
                    before,
                    profile_name,
                    took(),
                    action.reason,
                )
                return True
        if action.tag == "preference":
            state.prefer_attempts[action.dev] = (
                state.prefer_attempts.get(action.dev, 0) + 1
            )
            state.last_prefer[action.dev] = now
        profile = action.profile or profiles.get(action.dev)
        okay = reset_device(action.dev, profile, run)
        if action.tag == "fallback" and action.dev in state.demoted:
            # The move is undone; from here a device that stays dead is a
            # wedge and gets the USB schedule like any other.
            state.demoted[action.dev].kind = "wedged"
            state.demoted[
                action.dev
            ].reason = f"{action.reason}; escalates as a wedge from here"
        log.warning(
            "event=uplink_reset cycle=%s dev=%s before=%s trigger=%s ok=%s tag=%s profile=%s "
            "duration_ms=%.0f reason=%s",
            n,
            action.dev,
            before,
            action.trigger,
            okay,
            action.tag,
            profile,
            took(),
            action.reason,
        )
        return okay

    if action.kind == "reload":
        attempt = state.reload_attempts.get(action.dev, 0) + 1
        state.reload_attempts[action.dev] = attempt
        state.last_reload[action.dev] = now
        okay, detail = driver_reload(action.dev, run)
        log.warning(
            "event=uplink_driver_reload cycle=%s dev=%s before=%s attempt=%s ok=%s "
            "duration_ms=%.0f reason=%s detail=%s",
            n,
            action.dev,
            before,
            attempt,
            okay,
            took(),
            action.reason,
            detail,
        )
        return okay

    if action.kind == "usb_reset":
        # Count the attempt whether or not it works: a failing sudo or a
        # vanished node must still advance the schedule, never storm.
        if action.tag == "usb_speed":
            attempt = state.usb_speed_attempts.get(action.dev, 0) + 1
            state.usb_speed_attempts[action.dev] = attempt
            state.last_usb_speed_reset[action.dev] = now
            wait = usb_backoff(policy.usb_speed_schedule, attempt)
        else:
            attempt = state.usb_attempts.get(action.dev, 0) + 1
            state.usb_attempts[action.dev] = attempt
            state.last_usb_reset[action.dev] = now
            wait = usb_backoff(policy.usb_reset_schedule, attempt + 1)
        method = usb_reset_method(policy, attempt)
        okay, detail = usb_reset_device(action.dev, policy, run, method=method)
        log.warning(
            "event=uplink_usb_reset cycle=%s dev=%s before=%s attempt=%s method=%s ok=%s "
            "tag=%s next_in_s=%.0f duration_ms=%.0f reason=%s detail=%s",
            n,
            action.dev,
            before,
            attempt,
            method,
            okay,
            action.tag,
            wait,
            took(),
            action.reason,
            detail,
        )
        return okay

    return False
