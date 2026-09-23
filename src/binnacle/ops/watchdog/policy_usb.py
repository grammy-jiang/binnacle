"""USB link level: the target an adapter is repaired to, and the rung.

Corrected 2026-09-23. The level used to be "the best speed this adapter has
shown", keyed by interface name: after the 09-15 name swap the USB 2-only
RTL8188EUS was reset 12 times to reach the RTL8812AU's 5000 Mbit/s, and on
09-23 the RTL8812AU, deliberately in `rtw_switch_usb_mode=0`, was demoted
six times to chase the 5000 it had shown in mode 1; 0 of 18 such resets
ever raised a link. Now a per-adapter policy says what the level is:
`fixed` (a number), `param` (a kernel module parameter promises it --
rtw_switch_usb_mode=1 forces SuperSpeed, so 5000; any other value promises
nothing), `observe` (never reset for speed) or `learned` (the old rule, by
identity, relearned when the parameters change). A target is a floor for
repair, never a reason to force a link down.
"""

from dataclasses import dataclass, replace

from binnacle.ops.watchdog.config import Policy, UsbLinkPolicy
from binnacle.ops.watchdog.context import EvaluationContext
from binnacle.ops.watchdog.model import Action, DeviceInfo
from binnacle.ops.watchdog.schedule import _usb_speed_due


@dataclass(frozen=True, slots=True)
class UsbTarget:
    #: learned | fixed | param | observe
    mode: str
    #: Level to repair to; None = observe only.
    target: int | None
    #: What the repair counters belong to; a change clears them.
    fingerprint: str
    #: For journal lines: "best seen", "fixed", "rtw_switch_usb_mode=1".
    source: str


def _rule_for(info: DeviceInfo, policy: Policy) -> UsbLinkPolicy | None:
    for rule in policy.usb_link_policies:
        if rule.usb_id != info.usb_id:
            continue
        if rule.permanent_mac and rule.permanent_mac.lower() != info.mac:
            continue
        return rule
    return None


def resolve_usb_target(info: DeviceInfo, policy: Policy, learned: int) -> UsbTarget:
    """The level `info` is held to under `policy`. `learned` is the level
    the adapter has shown so far; only `learned` mode uses it."""
    rule = _rule_for(info, policy)
    params = dict(info.params)
    if rule is None or rule.mode == "learned":
        suffix = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
        fingerprint = "learned" + (f"|{suffix}" if suffix else "")
        return UsbTarget("learned", learned or None, fingerprint, "best seen")
    if rule.mode == "fixed":
        return UsbTarget(
            "fixed", rule.target_mbps, f"fixed:{rule.target_mbps}", "fixed"
        )
    if rule.mode == "param" and rule.param:
        value = params.get(rule.param)
        target = dict(rule.targets).get(value) if value is not None else None
        return UsbTarget(
            "param",
            target,
            f"param:{rule.param}={value}:{target}",
            f"{rule.param}={value if value is not None else '?'}",
        )
    return UsbTarget("observe", None, "observe", "observe")


def _level_text(
    info: DeviceInfo, target: UsbTarget, prefix: str = "USB link at"
) -> str:
    if target.mode == "learned":
        return f"{prefix} {info.usb_speed} Mbit/s, best seen {target.target}"
    return f"{prefix} {info.usb_speed} Mbit/s, target {target.target} ({target.source})"


def _reconcile(ctx: EvaluationContext, dev: str, info: DeviceInfo) -> UsbTarget:
    """Record what the adapter shows, resolve its target, and clear the
    repair counters when the policy behind them changed (the loop logs it
    as `usb_speed_policy_changed`)."""
    state = ctx.state
    speed = info.usb_speed or 0
    state.usb_max_seen[dev] = max(
        state.usb_max_seen.get(dev, 0), state.usb_best_speed.get(dev, 0), speed
    )  # a legacy file has a learned level but no recorded maximum
    if speed > state.usb_best_speed.get(dev, 0):
        state.usb_best_speed[dev] = speed
    target = resolve_usb_target(info, ctx.policy, state.usb_best_speed.get(dev, 0))
    old = state.usb_policy_fp.get(dev)
    if old is not None and old != target.fingerprint:
        cleared = [
            name
            for name in (
                "usb_speed_attempts",
                "last_usb_speed_reset",
                "usb_speed_exhausted",
            )
            if getattr(state, name).pop(dev, None) is not None
        ]
        state.usb_best_since.pop(dev, None)
        if target.mode == "learned":
            state.usb_best_speed[dev] = speed
            target = replace(target, target=speed or None)
            cleared.append("usb_best_speed")
        state.policy_events.append(
            (dev, old, target.fingerprint, ",".join(cleared) or "-")
        )
    state.usb_policy_fp[dev] = target.fingerprint
    state.usb_target[dev] = target.target
    state.usb_mode[dev] = target.mode
    return target


def _observe_only(
    ctx: EvaluationContext, dev: str, info: DeviceInfo, target: UsbTarget
) -> None:
    top = ctx.state.usb_max_seen.get(dev, 0)
    if info.usb_speed is not None and info.usb_speed < top:
        ctx.note(
            dev,
            "usb_level",
            f"link {info.usb_speed} Mbit/s, max seen {top}; policy {target.source}: "
            "observe, no repair",
        )


def _at_target(
    ctx: EvaluationContext, dev: str, info: DeviceInfo, target: UsbTarget
) -> None:
    state, policy, now = ctx.state, ctx.policy, ctx.now
    since = state.usb_best_since.setdefault(dev, now)
    if dev in state.usb_speed_attempts and now - since >= policy.usb_speed_hold_s:
        state.usb_speed_attempts.pop(dev, None)
        state.last_usb_speed_reset.pop(dev, None)
        state.usb_speed_exhausted.pop(dev, None)
    if target.target is not None and (info.usb_speed or 0) > target.target:
        ctx.note(
            dev,
            "usb_level",
            f"link {info.usb_speed} Mbit/s above target {target.target} "
            f"({target.source}); policy drift, no action",
        )


def _exhausted(
    ctx: EvaluationContext, dev: str, info: DeviceInfo, target: UsbTarget
) -> bool:
    """After `usb_speed_give_up` resets: a learned level is lowered to what
    the adapter shows; a fixed or param target stays and the rung waits for
    the link to change (a re-enumeration by other means restarts the
    schedule)."""
    state, policy = ctx.state, ctx.policy
    speed = info.usb_speed or 0
    at = state.usb_speed_exhausted.get(dev)
    if at is not None and at != speed:
        state.usb_speed_attempts.pop(dev, None)
        state.last_usb_speed_reset.pop(dev, None)
        state.usb_speed_exhausted.pop(dev, None)
        return False
    attempts = state.usb_speed_attempts.get(dev, 0)
    if attempts < policy.usb_speed_give_up:
        return False
    if target.mode == "learned":
        # The port, cable or driver will not give more right now: accept
        # this as the level until the device shows the higher one again.
        state.usb_best_speed[dev] = speed
        state.usb_target[dev] = speed
        state.usb_speed_attempts.pop(dev, None)
        state.last_usb_speed_reset.pop(dev, None)
        return True
    if at is None:
        state.usb_speed_exhausted[dev] = speed
    ctx.note(
        dev,
        "usb_level",
        f"{_level_text(info, target, 'link')}; repair exhausted after {attempts} "
        "resets, waiting for the link to change",
    )
    return True


def _repair_allowed(
    ctx: EvaluationContext, dev: str, info: DeviceInfo, target: UsbTarget, acted: bool
) -> bool:
    """The gates of a voluntary repair, with the reason for waiting noted."""
    state, policy = ctx.state, ctx.policy
    why: str | None
    if not policy.usb_speed_repair:
        why = "repair disabled"
    elif acted:
        why = "another action this cycle"
    elif state.demoted:
        why = "a demotion is in flight"
    elif state.repair_in_flight:
        why = "a repair is in flight"
    elif dev not in ctx.routed:
        why = "no route"
    elif not _usb_speed_due(state, dev, policy, ctx.now):
        why = "waiting for the schedule"
    else:
        probe = ctx.probes.get(dev)
        active = ctx.active is not None and dev == ctx.active.dev
        if probe is None or not probe.healthy:
            why = "device not healthy"
        elif active and not (ctx.healthy_devs - {dev}):
            why = "no healthy alternative"  # never take the only uplink down
        else:
            why = None
    if why is not None:
        ctx.note(dev, "usb_level", f"{_level_text(info, target, 'link')}; {why}")
        return False
    return True


def _plan_repair(
    ctx: EvaluationContext, dev: str, info: DeviceInfo, target: UsbTarget
) -> None:
    """Traffic leaves first (a demotion, when the adapter is the active
    route), then the re-enumeration."""
    attempt = ctx.state.usb_speed_attempts.get(dev, 0) + 1
    text = _level_text(info, target)
    if ctx.active is not None and dev == ctx.active.dev:
        alternatives = ctx.healthy_devs - {dev}
        ctx.actions.append(
            Action(
                "demote",
                dev,
                f"{text} (reset attempt {attempt}); {min(alternatives)} is healthy",
                metric=ctx.policy.demoted_metric,
                tag="usb_speed",
            )
        )
    ctx.actions.append(
        Action("usb_reset", dev, f"{text}; reset attempt {attempt}", tag="usb_speed")
    )


def evaluate_usb_level(ctx: EvaluationContext) -> bool:
    """Voluntary repair of a USB adapter's link level: one per cycle, never
    over a demotion or a repair in flight, never on a device that is not
    healthy, never on the only working uplink, and only towards a level
    its policy promises."""
    acted = False
    for dev in sorted(ctx.devs):
        info = ctx.devs[dev]
        if info.usb_speed is None:
            continue
        target = _reconcile(ctx, dev, info)
        if target.target is None:
            _observe_only(ctx, dev, info, target)
        elif info.usb_speed >= target.target:
            _at_target(ctx, dev, info, target)
        else:
            ctx.state.usb_best_since.pop(dev, None)
            if not _exhausted(ctx, dev, info, target) and _repair_allowed(
                ctx, dev, info, target, acted
            ):
                _plan_repair(ctx, dev, info, target)
                acted = True
    return acted
