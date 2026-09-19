"""Pure timing and backoff helpers for watchdog policy."""

from binnacle.ops.watchdog.config import Policy, usb_backoff
from binnacle.ops.watchdog.model import State


def _repairs_in_episode(
    state: State, dev: str, episode_start: float | None
) -> tuple[float | None, float | None]:
    """(last re-association, last USB reset) of `dev`, restricted to the
    current episode when one is given."""
    reset_at = state.last_reset.get(dev)
    usb_at = state.last_usb_reset.get(dev)
    if episode_start is not None:
        if reset_at is not None and reset_at < episode_start:
            reset_at = None
        if usb_at is not None and usb_at < episode_start:
            usb_at = None
    return reset_at, usb_at


def _usb_reset_due(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    first_ok: bool = False,
    episode_start: float | None = None,
) -> bool:
    """Has the schedule's wait elapsed since the last repair of `dev` in
    this episode?

    Attempt 1 counts from the tier-2 re-association, so the interface gets
    one minute to come back on its own before the first re-enumeration.
    Without a re-association in this episode there is nothing to escalate
    from: a repair from an earlier episode does not count (on 2026-09-14
    a second wedge minutes after the first went straight to a USB reset,
    logged "still unhealthy after re-association" with none made).
    """
    if not policy.usb_reset_enabled:
        return False
    reset_at, usb_at = _repairs_in_episode(state, dev, episode_start)
    if reset_at is None and usb_at is None:
        return first_ok
    last_repair = max(reset_at or 0.0, usb_at or 0.0)
    attempt = state.usb_attempts.get(dev, 0) + 1
    return (now - last_repair) >= usb_backoff(policy.usb_reset_schedule, attempt)


def _may_reset(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    episode_start: float | None = None,
) -> bool:
    """May `dev` be re-associated now?

    `min_reset_interval_s` paces repeats within one episode; the first
    re-association of a new episode (a demotion, or a failure streak that
    began after the last re-association) needs only `reset_floor_s`.
    """
    last = state.last_reset.get(dev)
    if last is None:
        return True
    if episode_start is not None and last < episode_start:
        return (now - last) >= policy.reset_floor_s
    return (now - last) >= policy.min_reset_interval_s


def recent_wedges(state: State, dev: str, policy: Policy, now: float) -> list[float]:
    """When `dev` was demoted for a wedge inside the flap window."""
    return [
        t for t in state.wedge_times.get(dev, []) if now - t <= policy.flap_window_s
    ]


def restore_needed(recent: int, policy: Policy) -> int:
    """Healthy cycles a demoted route needs before it is restored: the
    base, doubled for every earlier wedge inside the flap window (3, 6,
    12, 24 ...), capped at `restore_hold_max_cycles`."""
    base = policy.successes_before_restore
    if recent <= 1:
        return base
    return min(base * 2 ** (recent - 1), max(base, policy.restore_hold_max_cycles))


def _prefer_due(state: State, dev: str, policy: Policy, now: float) -> bool:
    """Has `prefer_schedule` elapsed since the last preference move?"""
    last = state.last_prefer.get(dev)
    if last is None:
        return True
    # The first move is immediate, so stage 1 of the schedule paces the
    # retries after it: with (3, 600) the gaps are 10 min, 10 min, 10 min.
    moves = max(1, state.prefer_attempts.get(dev, 0))
    return (now - last) >= usb_backoff(policy.prefer_schedule, moves)


def _reload_due(
    state: State,
    dev: str,
    policy: Policy,
    now: float,
    first_ok: bool = False,
    episode_start: float | None = None,
) -> bool:
    """Driver reloads pace themselves like USB resets, from the last repair
    in this episode."""
    if not policy.driver_reload_enabled:
        return False
    reset_at = state.last_reset.get(dev)
    reload_at = state.last_reload.get(dev)
    if episode_start is not None:
        if reset_at is not None and reset_at < episode_start:
            reset_at = None
        if reload_at is not None and reload_at < episode_start:
            reload_at = None
    if reset_at is None and reload_at is None:
        return first_ok
    last_repair = max(reset_at or 0.0, reload_at or 0.0)
    attempt = state.reload_attempts.get(dev, 0) + 1
    return (now - last_repair) >= usb_backoff(policy.usb_reset_schedule, attempt)


def _usb_speed_due(state: State, dev: str, policy: Policy, now: float) -> bool:
    """Has `usb_speed_schedule` elapsed since the last link-level reset?"""
    last = state.last_usb_speed_reset.get(dev)
    if last is None:
        return True
    attempts = max(1, state.usb_speed_attempts.get(dev, 0))
    return (now - last) >= usb_backoff(policy.usb_speed_schedule, attempts)
