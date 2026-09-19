"""Recovery, link-level, and preference watchdog policy rungs."""

from binnacle.ops.watchdog.context import EvaluationContext
from binnacle.ops.watchdog.model import Action
from binnacle.ops.watchdog.schedule import (
    _may_reset,
    _prefer_due,
    _reload_due,
    _repairs_in_episode,
    _usb_reset_due,
    _usb_speed_due,
    recent_wedges,
    restore_needed,
)


def evaluate_demoted(ctx: EvaluationContext) -> None:
    probes = ctx.probes
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    actions = ctx.actions
    note = ctx.note
    reset_wait = ctx.reset_wait
    usb_wait = ctx.usb_wait
    in_flight = ctx.in_flight
    usb_eligible = ctx.usb_eligible
    reload_eligible = ctx.reload_eligible
    # -- demoted routes: restore once they carry traffic again -- with a
    #    hold-down that grows with every wedge inside the flap window and
    #    the fast path's word that it has been passing; until then,
    #    re-associate first, then escalate to a USB re-enumeration on the
    #    schedule. Every wait counts from a repair in *this* episode.
    for dev, demotion in list(state.demoted.items()):
        probe = probes.get(dev)
        episode = demotion.since_ts or None
        if probe is not None and probe.healthy:
            state.successes[dev] = state.successes.get(dev, 0) + 1
            count = state.successes[dev]
            recent = len(recent_wedges(state, dev, policy, now))
            needed = restore_needed(recent, policy)
            hold = (
                f" (hold-down {needed}: {recent} wedges in the last "
                f"{policy.flap_window_s / 60:.0f} min)"
                if needed > policy.successes_before_restore
                else ""
            )
            fast_fail = state.fast_demoted_last_fail.get(dev, 0.0)
            fast_ago = now - fast_fail if fast_fail else None
            fast_quiet = (
                policy.fast_interval_s <= 0
                or fast_ago is None
                or fast_ago >= policy.restore_fast_quiet_s
            )
            if count >= needed and fast_quiet:
                actions.append(
                    Action(
                        "restore",
                        dev,
                        f"healthy for {count} cycles{hold}",
                        metric=demotion.original_metric,
                    )
                )
            elif count >= needed:
                note(
                    dev,
                    "restore",
                    f"demoted ({demotion.kind}); healthy {count}/{needed} cycles but "
                    f"the fast path saw it fail {fast_ago:.0f} s ago; restore after "
                    f"{policy.restore_fast_quiet_s:.0f} s clean",
                )
            else:
                note(
                    dev,
                    "restore",
                    f"demoted ({demotion.kind}); healthy {count}/{needed} cycles{hold}",
                )
        else:
            state.successes[dev] = 0
            if probe is not None and not probe.unavailable:
                if demotion.kind == "preference":
                    left = max(0.0, policy.prefer_timeout_s - (now - demotion.since_ts))
                    note(
                        dev,
                        "restore",
                        f"demoted (preference move to {demotion.target}) and "
                        f"{'wedged' if probe.wedged else 'not healthy'}; no USB "
                        f"escalation for a move; back to {demotion.profile} in "
                        f"{max(left, reset_wait(dev, episode)):.0f} s",
                    )
                else:
                    note(
                        dev,
                        "restore",
                        f"demoted ({demotion.kind}) and {'wedged' if probe.wedged else 'not healthy'}; "
                        f"re-association in {reset_wait(dev, episode):.0f} s, "
                        f"{usb_wait(dev, episode)}",
                    )
            # `probe is None` means the device has no route right now -- it
            # is most likely mid-re-enumeration; never stack a reset on that.
            # An unavailable probe is no verdict at all.
            if probe is None or probe.unavailable:
                continue
            if in_flight(dev):
                note(dev, "restore", f"demoted ({demotion.kind}); repair in flight")
                continue
            if demotion.kind == "preference":
                # A self-inflicted change gets no USB escalation: if the
                # better profile has not come up, go back to the one that
                # worked (NetworkManager usually does this by itself).
                if (now - demotion.since_ts) >= policy.prefer_timeout_s and _may_reset(
                    state, dev, policy, now, episode
                ):
                    actions.append(
                        Action(
                            "reset",
                            dev,
                            f"{demotion.target} did not come up within "
                            f"{int(policy.prefer_timeout_s)} s; back to {demotion.profile}",
                            profile=demotion.profile,
                            tag="fallback",
                        )
                    )
                continue
            if not probe.wedged:
                # Associated, gateway answers, still no TCP path: nothing a
                # re-enumeration would fix; re-associate on the rate limit
                # and otherwise wait for it to pass the probes.
                if _may_reset(state, dev, policy, now, episode):
                    actions.append(
                        Action("reset", dev, "demoted and still without a TCP path")
                    )
                continue
            reset_at, _usb_at = _repairs_in_episode(state, dev, episode)
            if reset_at is None and _may_reset(state, dev, policy, now, episode):
                # The gentle repair first, in every episode: the failover's
                # own re-association may have been skipped by the floor.
                actions.append(
                    Action(
                        "reset",
                        dev,
                        "demoted and wedged; re-association before the USB schedule",
                    )
                )
            elif usb_eligible(dev) and _usb_reset_due(
                state, dev, policy, now, episode_start=episode
            ):
                attempt = state.usb_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "usb_reset",
                        dev,
                        f"still wedged after this episode's re-association; "
                        f"USB reset attempt {attempt}",
                    )
                )
            elif reload_eligible(dev) and _reload_due(
                state, dev, policy, now, episode_start=episode
            ):
                attempt = state.reload_attempts.get(dev, 0) + 1
                actions.append(
                    Action(
                        "reload",
                        dev,
                        f"still wedged after this episode's re-association; "
                        f"driver reload attempt {attempt}",
                    )
                )


def evaluate_usb_level(ctx: EvaluationContext) -> bool:
    probes = ctx.probes
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    devs = ctx.devs
    routed = ctx.routed
    healthy_devs = ctx.healthy_devs
    active = ctx.active
    actions = ctx.actions
    note = ctx.note
    # -- voluntary repairs: one per cycle, never over a demotion in flight,
    #    never on a device that is not healthy right now. Level first (a USB
    #    reset also re-picks the profile), then the profile preference.
    acted = False

    # -- USB link level: back to the best speed this adapter has shown
    for dev in sorted(devs):
        info = devs[dev]
        if info.usb_speed is None:
            continue
        best = state.usb_best_speed.get(dev, 0)
        if info.usb_speed >= best:
            if info.usb_speed > best:
                state.usb_best_speed[dev] = info.usb_speed
            since = state.usb_best_since.setdefault(dev, now)
            if (
                dev in state.usb_speed_attempts
                and now - since >= policy.usb_speed_hold_s
            ):
                state.usb_speed_attempts.pop(dev, None)
                state.last_usb_speed_reset.pop(dev, None)
            continue
        state.usb_best_since.pop(dev, None)
        attempts = state.usb_speed_attempts.get(dev, 0)
        if attempts >= policy.usb_speed_give_up:
            # The port, cable or driver will not give more right now: accept
            # this as the level until the device shows the higher one again.
            state.usb_best_speed[dev] = info.usb_speed
            state.usb_speed_attempts.pop(dev, None)
            state.last_usb_speed_reset.pop(dev, None)
            continue
        if (
            not policy.usb_speed_repair
            or acted
            or state.demoted
            or state.repair_in_flight
            or dev not in routed
            or not _usb_speed_due(state, dev, policy, now)
        ):
            why = (
                "repair disabled"
                if not policy.usb_speed_repair
                else "another action this cycle"
                if acted
                else "a demotion is in flight"
                if state.demoted
                else "a repair is in flight"
                if state.repair_in_flight
                else "no route"
                if dev not in routed
                else "waiting for the schedule"
            )
            note(dev, "usb_level", f"link {info.usb_speed} Mbit/s, best {best}; {why}")
            continue
        probe = probes.get(dev)
        if probe is None or not probe.healthy:
            note(
                dev,
                "usb_level",
                f"link {info.usb_speed} Mbit/s, best {best}; device not healthy",
            )
            continue
        if active is not None and dev == active.dev:
            alternatives = healthy_devs - {dev}
            if not alternatives:
                note(
                    dev,
                    "usb_level",
                    f"link {info.usb_speed} Mbit/s, best {best}; no healthy alternative",
                )
                continue  # never take the only working uplink down for this
            actions.append(
                Action(
                    "demote",
                    dev,
                    f"USB link at {info.usb_speed} Mbit/s, best seen {best} "
                    f"(reset attempt {attempts + 1}); {min(alternatives)} is healthy",
                    metric=policy.demoted_metric,
                    tag="usb_speed",
                )
            )
        actions.append(
            Action(
                "usb_reset",
                dev,
                f"USB link at {info.usb_speed} Mbit/s, best seen {best}; "
                f"reset attempt {attempts + 1}",
                tag="usb_speed",
            )
        )
        acted = True

    return acted


def evaluate_preference(ctx: EvaluationContext, acted: bool) -> None:
    state = ctx.state
    policy = ctx.policy
    now = ctx.now
    prefs = ctx.prefs
    probes = ctx.probes
    healthy_devs = ctx.healthy_devs
    active = ctx.active
    actions = ctx.actions
    note = ctx.note
    # -- profile preference
    if policy.prefer_enabled:
        for dev in sorted(prefs):
            pref = prefs[dev]
            if pref.target is None:
                since = state.preferred_since.setdefault(dev, now)
                if dev in state.prefer_attempts and now - since >= policy.prefer_hold_s:
                    state.prefer_attempts.pop(dev, None)
                    state.last_prefer.pop(dev, None)
                continue
            state.preferred_since.pop(dev, None)
            probe = probes.get(dev)
            if (
                acted
                or state.demoted
                or state.repair_in_flight
                or not pref.visible
                or probe is None
                or not probe.healthy
                or not _prefer_due(state, dev, policy, now)
            ):
                why = (
                    "another action this cycle"
                    if acted
                    else "a demotion is in flight"
                    if state.demoted
                    else "a repair is in flight"
                    if state.repair_in_flight
                    else "target not in range"
                    if not pref.visible
                    else "no route"
                    if probe is None
                    else "device not healthy"
                    if not probe.healthy
                    else "waiting for the schedule"
                )
                note(
                    dev,
                    "preference",
                    f"on {pref.current or 'no profile'}, {pref.target} preferred; {why}",
                )
                continue
            attempt = state.prefer_attempts.get(dev, 0) + 1
            if active is not None and dev == active.dev:
                alternatives = healthy_devs - {dev}
                if not alternatives:
                    note(
                        dev,
                        "preference",
                        f"{pref.target} preferred; no healthy alternative",
                    )
                    continue  # never take the only working uplink down for this
                actions.append(
                    Action(
                        "demote",
                        dev,
                        f"moving to preferred profile {pref.target} "
                        f"(attempt {attempt}); {min(alternatives)} is healthy",
                        metric=policy.demoted_metric,
                        profile=pref.target,
                        tag="preference",
                    )
                )
            actions.append(
                Action(
                    "reset",
                    dev,
                    f"activate preferred profile {pref.target} over {pref.current} "
                    f"(attempt {attempt})",
                    profile=pref.target,
                    tag="preference",
                )
            )
            acted = True
            break
