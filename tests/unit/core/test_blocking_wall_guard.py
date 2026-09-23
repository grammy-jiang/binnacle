"""Deterministic sequential coverage for the blocking-wall tracker."""

import time

import pytest

from binnacle.blocking_wall_guard import BlockingWallTracker


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tracked(
    tracker: BlockingWallTracker,
    *,
    turn: str = "turn-a",
    budget_s: int = 120,
    requested_wait_s: int = 50,
    bounded_wait_s: int = 50,
):
    return tracker.acquire(
        client="openai-mcp(ChatGPT)",
        turn=turn,
        requested_wait_s=requested_wait_s,
        bounded_wait_s=bounded_wait_s,
        budget_s=budget_s,
    )


def test_no_policy_preserves_ordinary_bounded_wait() -> None:
    tracker = BlockingWallTracker(clock=FakeClock())

    lease = tracker.acquire(
        client="other-client",
        turn="turn-a",
        requested_wait_s=80,
        bounded_wait_s=50,
        budget_s=None,
    )

    assert lease.decision.policy == "no_policy"
    assert lease.decision.effective_wait_s == 50
    assert lease.decision.budget_s is None
    assert lease.decision.spent_before_s is None
    assert lease.decision.remaining_before_s is None
    assert lease.decision.active_before == 0
    assert lease.decision.blocking_budget_exhausted is False
    assert lease.release().spent_after_s is None


def test_new_tracked_turn_starts_with_full_budget() -> None:
    tracker = BlockingWallTracker(clock=FakeClock())

    lease = _tracked(tracker, budget_s=120)

    assert lease.decision.policy == "tracked"
    assert lease.decision.effective_wait_s == 50
    assert lease.decision.budget_s == 120
    assert lease.decision.spent_before_s == pytest.approx(0.0)
    assert lease.decision.remaining_before_s == pytest.approx(120.0)
    assert lease.decision.active_before == 0
    assert lease.decision.blocking_budget_exhausted is False


def test_early_release_charges_actual_wall_time_not_requested_wait() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    lease = _tracked(tracker, budget_s=120)

    clock.advance(3.0)
    released = lease.release()

    assert released.window_closed is True
    assert released.window_wall_s == pytest.approx(3.0)
    assert released.spent_after_s == pytest.approx(3.0)
    assert released.remaining_after_s == pytest.approx(117.0)
    assert released.active_after == 0


def test_sequential_waits_accumulate_and_productive_gap_is_free() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=20)
    clock.advance(3.0)
    assert first.release().spent_after_s == pytest.approx(3.0)

    clock.advance(60.0)
    second = _tracked(tracker, budget_s=20)
    assert second.decision.spent_before_s == pytest.approx(3.0)
    assert second.decision.remaining_before_s == pytest.approx(17.0)
    assert second.decision.effective_wait_s == 17

    clock.advance(4.0)
    released = second.release()
    assert released.spent_after_s == pytest.approx(7.0)
    assert released.remaining_after_s == pytest.approx(13.0)


def test_remaining_budget_below_one_second_is_exhausted() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=5)
    clock.advance(4.2)
    released = first.release()
    assert released.remaining_after_s == pytest.approx(0.8)

    exhausted = _tracked(tracker, budget_s=5)

    assert exhausted.decision.policy == "exhausted"
    assert exhausted.decision.effective_wait_s == 0
    assert exhausted.decision.spent_before_s == pytest.approx(4.2)
    assert exhausted.decision.remaining_before_s == pytest.approx(0.8)
    assert exhausted.decision.active_before == 0
    assert exhausted.decision.blocking_budget_exhausted is True

    after = exhausted.release()
    assert after.window_closed is False
    assert after.window_wall_s is None
    assert after.spent_after_s == pytest.approx(4.2)
    assert after.remaining_after_s == pytest.approx(0.8)
    assert after.active_after == 0


def test_new_base_turn_gets_a_fresh_budget() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, turn="turn-a", budget_s=10)
    clock.advance(6.0)
    first.release()

    second = _tracked(tracker, turn="turn-b", budget_s=10)

    assert second.decision.spent_before_s == pytest.approx(0.0)
    assert second.decision.remaining_before_s == pytest.approx(10.0)
    assert second.decision.effective_wait_s == 10


def test_nonmatching_client_has_no_policy() -> None:
    tracker = BlockingWallTracker(clock=FakeClock())

    lease = tracker.acquire(
        client="claude-code",
        turn="turn-a",
        requested_wait_s=12,
        bounded_wait_s=12,
        budget_s=None,
    )

    assert lease.decision.policy == "no_policy"
    assert lease.decision.effective_wait_s == 12


def test_missing_turn_uses_no_turn_and_preserves_bounded_wait() -> None:
    tracker = BlockingWallTracker(clock=FakeClock())

    lease = tracker.acquire(
        client="openai-mcp(ChatGPT)",
        turn=None,
        requested_wait_s=50,
        bounded_wait_s=50,
        budget_s=120,
    )

    assert lease.decision.policy == "no_turn"
    assert lease.decision.effective_wait_s == 50
    assert lease.decision.budget_s is None
    assert lease.decision.spent_before_s is None
    assert lease.decision.remaining_before_s is None
    assert lease.release().window_closed is False


def test_release_is_idempotent_and_does_not_double_charge() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    lease = _tracked(tracker, budget_s=20)

    clock.advance(2.5)
    first = lease.release()
    clock.advance(10.0)
    second = lease.release()

    assert second == first
    assert second.spent_after_s == pytest.approx(2.5)

    next_lease = _tracked(tracker, budget_s=20)
    assert next_lease.decision.spent_before_s == pytest.approx(2.5)


def test_record_budget_is_fixed_for_process_lifetime() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=10)
    clock.advance(2.0)
    first.release()

    changed_config = _tracked(tracker, budget_s=30)

    assert changed_config.decision.budget_s == 10
    assert changed_config.decision.remaining_before_s == pytest.approx(8.0)
    assert changed_config.decision.effective_wait_s == 8


def test_default_clock_is_monotonic() -> None:
    tracker = BlockingWallTracker()

    assert tracker._clock is time.monotonic


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity must be at least 1"):
        BlockingWallTracker(capacity=0)
