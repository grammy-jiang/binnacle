"""Pure watchdog decision orchestration."""

import time

from binnacle.ops.watchdog.config import DEFAULT_POLICY, Policy
from binnacle.ops.watchdog.context import EvaluationContext
from binnacle.ops.watchdog.model import Action, DeviceInfo, Preference, State
from binnacle.ops.watchdog.policy_recovery import (
    evaluate_demoted,
    evaluate_preference,
)
from binnacle.ops.watchdog.policy_routes import (
    evaluate_active,
    evaluate_standby,
    evaluate_unrouted,
)
from binnacle.ops.watchdog.policy_usb import evaluate_usb_level
from binnacle.uplink import ProbeResult, Route


def evaluate(
    routes: list[Route],
    probes: dict[str, ProbeResult],
    state: State,
    policy: Policy = DEFAULT_POLICY,
    now: float | None = None,
    preferences: dict[str, Preference] | None = None,
    devices: dict[str, DeviceInfo] | None = None,
    routes_known: bool = True,
) -> list[Action]:
    """Decide what to do this cycle with no external side effects."""
    current = time.time() if now is None else now
    prefs = preferences or {}
    devs = devices or {}
    state.decisions = []
    state.policy_events = []
    if not routes and not devs:
        return []

    ctx = EvaluationContext(
        routes,
        probes,
        state,
        policy,
        current,
        prefs,
        devs,
        routes_known,
    )
    evaluate_active(ctx)
    evaluate_standby(ctx)
    evaluate_unrouted(ctx)
    evaluate_demoted(ctx)
    acted = evaluate_usb_level(ctx)
    evaluate_preference(ctx, acted)
    return ctx.actions
