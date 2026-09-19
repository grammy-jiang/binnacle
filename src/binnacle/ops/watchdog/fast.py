"""Fast-path failover supervision for the watchdog."""

import logging
import os
import sys
import threading
import time
from collections.abc import Callable

from binnacle import uplink
from binnacle.ops.watchdog.actions import apply_action
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.lock import ACT_LOCK
from binnacle.ops.watchdog.model import Action, State
from binnacle.ops.watchdog.schedule import _may_reset
from binnacle.ops.watchdog.services import pause_until
from binnacle.ops.watchdog.tunnel import after_failover
from binnacle.uplink import Route

log = logging.getLogger("binnacle.watchdog")


def _still_safe(
    action: Action, decided_active: str | None, state: State, run: Run
) -> bool:
    """A repair decided under the lock, about to run outside it: still
    safe unless the device has become the active route meanwhile (the fast
    path moved traffic onto it). An in-place repair of the route that was
    active when it was decided, or of a demoted device, always is."""
    if action.dev == decided_active or action.dev in state.demoted:
        return True
    routes_now, known = uplink.read_default_routes(run)
    if not known or not routes_now:
        return True
    return routes_now[0].dev != action.dev


def fast_check(
    state: State,
    policy: Policy,
    run: Run = _run,
    tcp: Callable[[Route], bool] | None = None,
    now: float | None = None,
    host: str = uplink.UPSTREAM_HOST,
) -> list[Action]:
    """One tick of the fast path. Returns the actions it applied.

    Only the active route is probed (one TCP connect to the upstream's
    cached address, `fast_timeout_s`), plus any demoted route so the
    restore can ask for a clean run at this resolution; the standbys are
    asked only when the active one has failed `fast_failures_before_action`
    times running, and only a standby with a working TCP path makes it a
    failover. The demotion and the tunnel move happen under the lock the
    cycle uses; the re-association runs outside it, marked in flight.
    """
    now = time.time() if now is None else now
    state.fast_last = now
    if policy.dry_run or pause_until(policy.pause_file) is not None:
        return []
    routes, known = uplink.read_default_routes(run)
    if not known or len(routes) < 2:
        state.fast_failures = 0
        return []
    active = routes[0]
    address = uplink._last_address.get(host)
    if address is None:
        return []  # the full cycle has not resolved the upstream yet

    def connect(route: Route) -> bool:
        if tcp is not None:
            return tcp(route)
        try:
            ok, _ = uplink.probe_tcp(
                route.src,
                host,
                timeout=policy.fast_timeout_s,
                dev=route.dev,
                address=address,
            )
        except uplink.ProbeUnavailable:
            return True  # no verdict: never a failover
        return ok

    for route in routes[1:]:
        if route.dev not in state.demoted:
            continue
        if connect(route):
            state.fast_demoted_streak[route.dev] = (
                state.fast_demoted_streak.get(route.dev, 0) + 1
            )
            continue
        streak = state.fast_demoted_streak.get(route.dev, 0)
        if streak or route.dev not in state.fast_demoted_last_fail:
            log.warning(
                "event=fast_failure cycle=%s dev=%s role=demoted after_successes=%s",
                state.cycle_n,
                route.dev,
                streak,
            )
        state.fast_demoted_streak[route.dev] = 0
        state.fast_demoted_last_fail[route.dev] = now

    if active.dev in state.demoted:
        state.fast_failures = 0
        return []
    if state.fast_dev != active.dev:
        state.fast_dev = active.dev
        state.fast_failures = 0
    if connect(active):
        if state.fast_failures:
            log.info(
                "event=fast_recovered cycle=%s dev=%s after_failures=%s",
                state.cycle_n,
                active.dev,
                state.fast_failures,
            )
        state.fast_failures = 0
        return []
    state.fast_failures += 1
    log.warning(
        "event=fast_failure cycle=%s dev=%s failures=%s/%s",
        state.cycle_n,
        active.dev,
        state.fast_failures,
        policy.fast_failures_before_action,
    )
    if state.fast_failures < policy.fast_failures_before_action:
        return []
    done: list[Action] = []
    want_reset = False
    with ACT_LOCK:
        if active.dev in state.demoted:
            return []
        target = next(
            (r for r in routes[1:] if r.dev not in state.demoted and connect(r)), None
        )
        if target is None:
            log.warning(
                "event=fast_failover_blocked cycle=%s dev=%s reason=no standby with a TCP path",
                state.cycle_n,
                active.dev,
            )
            return []
        window = state.fast_failures * policy.fast_interval_s
        log.warning(
            "event=fast_failover cycle=%s dev=%s failures=%s window_s=%.0f target=%s metric=%s",
            state.cycle_n,
            active.dev,
            state.fast_failures,
            window,
            target.dev,
            target.metric,
        )
        demote = Action(
            "demote",
            active.dev,
            f"no TCP path for {state.fast_failures} fast probes ({window:.0f} s); "
            f"{target.dev} has a TCP path (metric {target.metric})",
            metric=policy.demoted_metric,
            trigger="fast",
        )
        if apply_action(demote, routes, state, run, policy=policy):
            done.append(demote)
            # Traffic has moved; get the poller onto the new path now,
            # before the 14 s re-association of the old one.
            after_failover(state, policy, run, now, target=target.dev)
            want_reset = policy.reset_after_failover and _may_reset(
                state, active.dev, policy, now, episode_start=now
            )
        state.fast_failures = 0
    if want_reset:
        reset = Action(
            "reset", active.dev, "repair after fast failover", trigger="fast"
        )
        state.repair_in_flight[active.dev] = now
        try:
            if apply_action(reset, routes, state, run, policy=policy):
                done.append(reset)
        finally:
            state.repair_in_flight.pop(active.dev, None)
    return done


def fast_loop(
    state: State,
    policy: Policy,
    run: Run,
    stop: threading.Event,
    host: str = uplink.UPSTREAM_HOST,
) -> None:
    """The fast path's thread body."""
    while not stop.wait(policy.fast_interval_s):
        try:
            fast_check(state, policy, run, host=host)
        except Exception:  # never let the fast path kill the loop
            log.exception("event=fast_check_error cycle=%s", state.cycle_n)


def supervise_fast_path(
    state: State,
    policy: Policy,
    thread: threading.Thread,
    start: Callable[[], threading.Thread],
    exit_fn: Callable[[int], None] = os._exit,
    now: float | None = None,
) -> tuple[threading.Thread, bool]:
    """After each cycle: a dead fast-path thread is started again, a
    stalled heartbeat is logged, a hung one (older than the cycle timeout)
    exits the process for systemd to restart. Returns (thread, hung)."""
    now = time.time() if now is None else now
    age = now - state.fast_last if state.fast_last else 0.0
    stall_after = max(30.0, 3 * (policy.fast_interval_s + policy.fast_timeout_s))
    if not thread.is_alive():
        log.error(
            "event=fast_path_restarted cycle=%s reason=thread died age_s=%.0f",
            state.cycle_n,
            age,
        )
        state.fast_last = now  # the new thread gets its first tick before it is judged
        return start(), False
    if age > policy.cycle_timeout_s:
        log.error(
            "event=fast_path_hung cycle=%s age_s=%.0f; exiting for systemd to restart",
            state.cycle_n,
            age,
        )
        for handler in log.handlers or logging.getLogger().handlers:
            handler.flush()
        sys.stdout.flush()
        exit_fn(3)
        return thread, True
    if age > stall_after:
        log.warning("event=fast_path_stalled cycle=%s age_s=%.0f", state.cycle_n, age)
    return thread, False
