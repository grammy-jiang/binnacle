"""Route-based watchdog policy rungs."""

from binnacle.ops.watchdog.context import EvaluationContext
from binnacle.ops.watchdog.model import Action
from binnacle.ops.watchdog.schedule import _may_reset, _reload_due, _usb_reset_due


def evaluate_active(ctx: EvaluationContext) -> None:
    routes = ctx.routes
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    healthy_devs = ctx.healthy_devs
    usable_devs = ctx.usable_devs
    active = ctx.active
    active_probe = ctx.active_probe
    actions = ctx.actions
    note = ctx.note
    reset_wait = ctx.reset_wait
    usb_wait = ctx.usb_wait
    in_flight = ctx.in_flight
    bump = ctx.bump
    clear = ctx.clear
    usb_eligible = ctx.usb_eligible
    reload_eligible = ctx.reload_eligible
    # -- the route traffic currently takes
    if active is not None and active.dev not in state.demoted:
        probe = active_probe
        if probe is not None and probe.dead_end:
            count = bump(active.dev)
            streak = state.failure_since.get(active.dev)
            what = "wedged" if probe.wedged else "no TCP path"
            if count < policy.failures_before_action:
                note(
                    active.dev,
                    "failover",
                    f"{what} {count}/{policy.failures_before_action} cycles",
                )
            else:
                alternatives = usable_devs - {active.dev}
                if not alternatives:
                    note(
                        active.dev,
                        "failover",
                        f"{what} for {count} cycles; no usable alternative (none with a TCP path)"
                        + (
                            "; the WAN is suspected, radios left alone"
                            if not probe.wedged
                            else f"; in-place reset in {reset_wait(active.dev, streak):.0f} s, "
                            f"{usb_wait(active.dev, streak)}"
                        ),
                    )
                if alternatives:
                    # The kernel will pick the lowest metric among what is
                    # left; name that one (three radios now: 100/300/600).
                    by_metric = {r.dev: r.metric for r in routes}
                    alt = min(
                        alternatives, key=lambda d: (by_metric.get(d, 1 << 30), d)
                    )
                    actions.append(
                        Action(
                            "demote",
                            active.dev,
                            f"{what} for {count} cycles; {alt} "
                            f"{'is healthy' if alt in healthy_devs else 'has a TCP path'}"
                            f" (metric {by_metric.get(alt, '?')})",
                            metric=policy.demoted_metric,
                        )
                    )
                    if policy.reset_after_failover and _may_reset(
                        state, active.dev, policy, now, episode_start=now
                    ):
                        actions.append(
                            Action("reset", active.dev, "repair after failover")
                        )
                elif not probe.wedged:
                    # The gateway answers and nothing beyond it does, on the
                    # only route: that is the WAN or the upstream, not this
                    # host. Resetting radios would only add an outage.
                    pass
                elif in_flight(active.dev):
                    note(
                        active.dev,
                        "failover",
                        f"{what} for {count} cycles; repair in flight",
                    )
                elif _may_reset(state, active.dev, policy, now, streak):
                    # Nothing to fail over to: repair in place is the only move.
                    actions.append(
                        Action(
                            "reset",
                            active.dev,
                            f"wedged for {count} cycles; no usable alternative",
                        )
                    )
                elif usb_eligible(active.dev) and _usb_reset_due(
                    state, active.dev, policy, now, episode_start=streak
                ):
                    # Still wedged after the in-place re-association and with
                    # nowhere to fail over to (2026-09-13: wlan0 dead in its
                    # metal case): escalate to the USB reset on the same
                    # schedule. The device is carrying nothing, so the ~10 s
                    # it takes to come back costs nothing.
                    attempt = state.usb_attempts.get(active.dev, 0) + 1
                    actions.append(
                        Action(
                            "usb_reset",
                            active.dev,
                            f"wedged for {count} cycles, no usable alternative; "
                            f"USB reset attempt {attempt}",
                        )
                    )
                elif reload_eligible(active.dev) and _reload_due(
                    state, active.dev, policy, now, episode_start=streak
                ):
                    attempt = state.reload_attempts.get(active.dev, 0) + 1
                    actions.append(
                        Action(
                            "reload",
                            active.dev,
                            f"wedged for {count} cycles, no usable alternative; "
                            f"driver reload attempt {attempt}",
                        )
                    )
        else:
            clear(active.dev)
            state.usb_attempts.pop(active.dev, None)
            state.reload_attempts.pop(active.dev, None)


def evaluate_standby(ctx: EvaluationContext) -> None:
    routes = ctx.routes
    probes = ctx.probes
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    prefs = ctx.prefs
    active = ctx.active
    active_healthy = ctx.active_healthy
    actions = ctx.actions
    note = ctx.note
    reset_wait = ctx.reset_wait
    usb_wait = ctx.usb_wait
    in_flight = ctx.in_flight
    bump = ctx.bump
    clear = ctx.clear
    usb_eligible = ctx.usb_eligible
    reload_eligible = ctx.reload_eligible
    # -- standby routes: keep the lifeline alive while nothing depends on it.
    #    A standby with a gateway but no TCP path is only "broken" when the
    #    active route proves the upstream works; otherwise it is the WAN.
    for route in routes:
        dev = route.dev
        if dev in state.demoted or (active is not None and dev == active.dev):
            continue
        probe = probes.get(dev)
        if probe is None:
            continue
        broken = probe.wedged or (probe.dead_end and active_healthy)
        if not broken:
            clear(dev)
            if probe.healthy:
                state.usb_attempts.pop(dev, None)
                state.reload_attempts.pop(dev, None)
            continue
        count = bump(dev)
        streak = state.failure_since.get(dev)
        what = "wedged" if probe.wedged else "no TCP path"
        if not policy.standby_repair or count < policy.failures_before_action:
            note(
                dev, "standby", f"{what} {count}/{policy.failures_before_action} cycles"
            )
            continue
        if in_flight(dev):
            note(dev, "standby", f"{what} for {count} cycles; repair in flight")
            continue
        if not _may_reset(state, dev, policy, now, streak):
            note(
                dev,
                "standby",
                f"{what} for {count} cycles; re-activation in {reset_wait(dev, streak):.0f} s, "
                f"{usb_wait(dev, streak)}",
            )
        if _may_reset(state, dev, policy, now, streak):
            pref = prefs.get(dev)
            target = pref.target if pref is not None and pref.visible else None
            actions.append(
                Action(
                    "reset",
                    dev,
                    f"standby {what} for {count} cycles"
                    + (f"; moving to {target}" if target else ""),
                    profile=target,
                    tag="standby",
                )
            )
        elif (
            probe.wedged
            and usb_eligible(dev)
            and _usb_reset_due(state, dev, policy, now, episode_start=streak)
        ):
            # Re-association did not revive it; it carries nothing, so the
            # software replug costs nothing.
            attempt = state.usb_attempts.get(dev, 0) + 1
            actions.append(
                Action(
                    "usb_reset",
                    dev,
                    f"standby still wedged after re-activation; USB reset attempt {attempt}",
                )
            )
        elif (
            probe.wedged
            and reload_eligible(dev)
            and _reload_due(state, dev, policy, now, episode_start=streak)
        ):
            attempt = state.reload_attempts.get(dev, 0) + 1
            actions.append(
                Action(
                    "reload",
                    dev,
                    f"standby still wedged after re-activation; driver reload attempt {attempt}",
                )
            )


def evaluate_unrouted(ctx: EvaluationContext) -> None:
    routes_known = ctx.routes_known
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    prefs = ctx.prefs
    devs = ctx.devs
    routed = ctx.routed
    actions = ctx.actions
    note = ctx.note
    reset_wait = ctx.reset_wait
    usb_wait = ctx.usb_wait
    in_flight = ctx.in_flight
    reload_eligible = ctx.reload_eligible
    # -- devices without a route: the lifeline that is not even there.
    #    They carry nothing, so a repair costs nothing; the thresholds only
    #    keep the loop from stepping on NetworkManager's own reconnect.
    #    "Connected without a route" is different: the device may well be
    #    carrying traffic through a route the loop could not read, so it
    #    needs a readable table, the longer threshold, one device per
    #    cycle, and the gentle repair first (apply_action reapplies the
    #    profile before it re-associates). On 2026-09-13 23:49 a version
    #    without these guards re-activated both radios at once.
    no_route_acted = False
    for dev in sorted(devs):
        info = devs[dev]
        if dev in routed or info.nm_state == "unmanaged":
            state.down_cycles[dev] = 0
            continue
        state.down_cycles[dev] = state.down_cycles.get(dev, 0) + 1
        count = state.down_cycles[dev]
        threshold = (
            policy.connecting_cycles_before_action
            if info.nm_state in ("connecting", "deactivating", "connected")
            else policy.failures_before_action
        )
        what = (
            "connected without a default route"
            if info.nm_state == "connected"
            else info.nm_state
        )
        if not policy.down_repair or count < threshold:
            note(dev, "down", f"{what} {count}/{threshold} cycles")
            continue
        pref = prefs.get(dev)
        target = pref.target if pref is not None and pref.visible else None
        usb_adapter = info.usb_id is not None and info.usb_id in policy.usb_reset_ids
        if in_flight(dev):
            note(dev, "down", f"{what} for {count} cycles; repair in flight")
            continue
        if info.nm_state == "connected":
            # Associated with an address but no default route (a DHCP offer
            # without a router, a route someone deleted): re-applying the
            # profile re-runs the IP configuration; re-association only if
            # that fails. A profile that is not meant to carry a default
            # route is left alone by apply_action.
            if not routes_known:
                note(
                    dev,
                    "down",
                    f"{what} for {count} cycles; the route table could not be read",
                )
                continue
            if no_route_acted:
                note(dev, "down", f"{what} for {count} cycles; one device per cycle")
                continue
            if _may_reset(state, dev, policy, now):
                no_route_acted = True
                actions.append(
                    Action(
                        "reset",
                        dev,
                        f"{what} for {count} cycles",
                        profile=target or info.profile or None,
                        tag="no_route",
                    )
                )
            else:
                note(
                    dev,
                    "down",
                    f"{what} for {count} cycles; re-activation in {reset_wait(dev):.0f} s",
                )
            continue
        if target:
            if _may_reset(state, dev, policy, now):
                actions.append(
                    Action(
                        "reset",
                        dev,
                        f"{info.nm_state} for {count} cycles; {target} is in range",
                        profile=target,
                        tag="down",
                    )
                )
            elif usb_adapter and _usb_reset_due(state, dev, policy, now):
                # The re-activation did not bring it back: the schedule.
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        (
                            f"{info.nm_state} for {count} cycles after re-activation; "
                            f"USB reset attempt {attempt}"
                        ),
                    )
                )
            elif reload_eligible(dev) and _reload_due(state, dev, policy, now):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        (
                            f"{info.nm_state} for {count} cycles after re-activation; "
                            f"driver reload attempt {attempt}"
                        ),
                    )
                )
            else:
                note(
                    dev,
                    "down",
                    f"{info.nm_state} for {count} cycles, {target} in range; "
                    f"re-activation in {reset_wait(dev):.0f} s"
                    + (f", {usb_wait(dev)}" if usb_adapter else ""),
                )
        elif info.nm_state == "unavailable":
            # No radio to speak of (driver, firmware, rfkill): re-enumerate
            # the adapter, or reload the built-in radio's driver if allowed.
            if usb_adapter and _usb_reset_due(state, dev, policy, now, first_ok=True):
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        f"unavailable for {count} cycles; USB reset attempt {attempt}",
                    )
                )
            elif reload_eligible(dev) and _reload_due(
                state, dev, policy, now, first_ok=True
            ):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        f"unavailable for {count} cycles; driver reload attempt {attempt}",
                    )
                )
        else:
            note(dev, "down", f"{info.nm_state} for {count} cycles; nothing in range")
