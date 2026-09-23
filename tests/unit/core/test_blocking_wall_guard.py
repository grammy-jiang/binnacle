"""Deterministic sequential, overlapping, and bounded-state tracker coverage."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def test_two_fully_overlapping_waits_charge_union_once() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    acquired = threading.Barrier(3)
    release_waiters = threading.Event()

    def worker():
        lease = _tracked(tracker, budget_s=10)
        acquired.wait(timeout=2.0)
        if not release_waiters.wait(timeout=2.0):
            raise AssertionError("release signal was not received")
        return lease.decision, lease.release()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        acquired.wait(timeout=2.0)
        clock.advance(4.0)
        release_waiters.set()
        results = [future.result(timeout=2.0) for future in futures]

    decisions = [decision for decision, _ in results]
    releases = [release for _, release in results]
    assert sorted(decision.active_before for decision in decisions) == [0, 1]
    assert all(
        decision.remaining_before_s == pytest.approx(10.0) for decision in decisions
    )
    assert sum(release.window_closed for release in releases) == 1
    closed = next(release for release in releases if release.window_closed)
    assert closed.window_wall_s == pytest.approx(4.0)
    assert closed.spent_after_s == pytest.approx(4.0)
    assert closed.remaining_after_s == pytest.approx(6.0)


def test_five_fully_overlapping_waits_charge_one_window() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    leases = [_tracked(tracker, budget_s=20) for _ in range(5)]

    assert [lease.decision.active_before for lease in leases] == [0, 1, 2, 3, 4]
    assert all(
        lease.decision.remaining_before_s == pytest.approx(20.0) for lease in leases
    )

    clock.advance(3.0)
    releases = [leases[index].release() for index in (2, 4, 1, 3, 0)]

    assert [release.active_after for release in releases] == [4, 3, 2, 1, 0]
    assert [release.window_closed for release in releases] == [
        False,
        False,
        False,
        False,
        True,
    ]
    assert releases[-1].window_wall_s == pytest.approx(3.0)
    assert releases[-1].spent_after_s == pytest.approx(3.0)
    assert releases[-1].remaining_after_s == pytest.approx(17.0)


def test_partial_overlap_keeps_window_open_when_one_wait_exits_early() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=10)
    clock.advance(2.0)
    second = _tracked(tracker, budget_s=10)

    assert second.decision.active_before == 1
    assert second.decision.spent_before_s == pytest.approx(2.0)
    assert second.decision.remaining_before_s == pytest.approx(8.0)
    assert second.decision.effective_wait_s == 8

    clock.advance(2.0)
    first_release = first.release()
    assert first_release.window_closed is False
    assert first_release.window_wall_s is None
    assert first_release.active_after == 1
    assert first_release.spent_after_s == pytest.approx(4.0)
    assert first_release.remaining_after_s == pytest.approx(6.0)

    clock.advance(3.0)
    second_release = second.release()
    assert second_release.window_closed is True
    assert second_release.window_wall_s == pytest.approx(7.0)
    assert second_release.spent_after_s == pytest.approx(7.0)
    assert second_release.remaining_after_s == pytest.approx(3.0)


def test_active_window_deadline_is_shared_and_caps_union_charge() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=5)
    clock.advance(1.5)
    second = _tracked(tracker, budget_s=5)
    assert second.decision.spent_before_s == pytest.approx(1.5)
    assert second.decision.remaining_before_s == pytest.approx(3.5)
    assert second.decision.effective_wait_s == 3

    clock.advance(4.5)
    first_release = first.release()
    assert first_release.active_after == 1
    assert first_release.window_closed is False
    assert first_release.spent_after_s == pytest.approx(5.0)
    assert first_release.remaining_after_s == pytest.approx(0.0)

    exhausted = _tracked(tracker, budget_s=5)
    assert exhausted.decision.policy == "exhausted"
    assert exhausted.decision.active_before == 1
    assert exhausted.decision.effective_wait_s == 0
    assert exhausted.release().active_after == 1

    final_release = second.release()
    assert final_release.window_closed is True
    assert final_release.window_wall_s == pytest.approx(5.0)
    assert final_release.spent_after_s == pytest.approx(5.0)
    assert final_release.remaining_after_s == pytest.approx(0.0)


def test_overlapping_wait_reuses_original_deadline_instead_of_extending_it() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)

    first = _tracked(tracker, budget_s=12)
    clock.advance(7.2)
    second = _tracked(tracker, budget_s=12)

    assert first.decision.remaining_before_s == pytest.approx(12.0)
    assert second.decision.remaining_before_s == pytest.approx(4.8)
    assert second.decision.effective_wait_s == 4

    clock.advance(2.0)
    first.release()
    clock.advance(10.0)
    closed = second.release()

    assert closed.window_wall_s == pytest.approx(12.0)
    assert closed.spent_after_s == pytest.approx(12.0)
    assert closed.remaining_after_s == pytest.approx(0.0)


def test_zero_effective_wait_never_increments_active_count() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    active = _tracked(tracker, budget_s=10)

    zero = _tracked(
        tracker,
        budget_s=10,
        requested_wait_s=1,
        bounded_wait_s=0,
    )

    assert zero.decision.policy == "tracked"
    assert zero.decision.effective_wait_s == 0
    assert zero.decision.active_before == 1
    assert zero.release().active_after == 1

    clock.advance(2.0)
    closed = active.release()
    assert closed.active_after == 0
    assert closed.window_closed is True
    assert closed.window_wall_s == pytest.approx(2.0)


def test_exception_cleanup_releases_active_lease() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    lease = _tracked(tracker, budget_s=10)
    released = []

    with pytest.raises(RuntimeError, match="caller failed"):
        try:
            clock.advance(2.0)
            raise RuntimeError("caller failed")
        finally:
            released.append(lease.release())

    assert released[0].window_closed is True
    assert released[0].spent_after_s == pytest.approx(2.0)
    next_lease = _tracked(tracker, budget_s=10)
    assert next_lease.decision.active_before == 0
    assert next_lease.decision.spent_before_s == pytest.approx(2.0)


def test_cancellation_equivalent_cleanup_releases_active_lease() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    lease = _tracked(tracker, budget_s=10)

    with pytest.raises(asyncio.CancelledError):
        try:
            clock.advance(1.25)
            raise asyncio.CancelledError
        finally:
            released = lease.release()

    assert released.window_closed is True
    assert released.spent_after_s == pytest.approx(1.25)
    next_lease = _tracked(tracker, budget_s=10)
    assert next_lease.decision.active_before == 0
    assert next_lease.decision.spent_before_s == pytest.approx(1.25)


def test_inactive_lru_eviction_retains_recently_used_record() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock, capacity=2)
    old = _tracked(tracker, turn="turn-a", budget_s=10)
    clock.advance(1.0)
    old.release()
    recent = _tracked(tracker, turn="turn-b", budget_s=10)
    clock.advance(1.0)
    recent.release()
    clock.advance(1.0)
    refreshed = _tracked(tracker, turn="turn-a", budget_s=10)
    state = tracker._states[("openai-mcp(ChatGPT)", "turn-a")]
    assert state.last_seen == pytest.approx(clock.now)
    clock.advance(0.5)
    refreshed.release()
    assert state.last_seen == pytest.approx(clock.now)
    clock.advance(0.5)
    _tracked(tracker, turn="turn-c", budget_s=10)
    assert {key[1] for key in tracker._states} == {"turn-a", "turn-c"}


def test_mixed_pressure_never_evicts_active_record() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock, capacity=2)
    active = _tracked(tracker, turn="turn-active", budget_s=20)
    clock.advance(1.0)
    _tracked(tracker, turn="turn-old", budget_s=20).release()
    clock.advance(1.0)
    _tracked(tracker, turn="turn-replacement", budget_s=20)
    assert {key[1] for key in tracker._states} == {"turn-active", "turn-replacement"}
    assert tracker._states[("openai-mcp(ChatGPT)", "turn-active")].active_count == 1
    assert active.decision.policy == "tracked"


def test_all_active_capacity_fallback_preserves_tracked_accounting() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock, capacity=2)
    first = _tracked(tracker, turn="turn-a", budget_s=10)
    _tracked(tracker, turn="turn-b", budget_s=10)
    state = tracker._states[("openai-mcp(ChatGPT)", "turn-a")]
    snapshot = (state.active_count, state.spent_s, state.last_seen)
    clock.advance(2.0)
    fallback = _tracked(tracker, turn="turn-c", budget_s=10)
    assert fallback.decision.policy == "capacity_untracked"
    assert fallback.decision.effective_wait_s == 50
    assert len(tracker._states) == 2
    assert (state.active_count, state.spent_s, state.last_seen) == snapshot
    assert fallback.release().spent_after_s is None
    clock.advance(1.0)
    assert first.release().spent_after_s == pytest.approx(3.0)


def test_new_turn_tracks_after_active_capacity_becomes_inactive() -> None:
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock, capacity=1)
    first = _tracked(tracker, turn="turn-a", budget_s=10)
    fallback = _tracked(tracker, turn="turn-b", budget_s=10)
    assert fallback.decision.policy == "capacity_untracked"
    clock.advance(2.0)
    first.release()
    clock.advance(1.0)
    tracked = _tracked(tracker, turn="turn-b", budget_s=10)
    assert tracked.decision.policy == "tracked"
    assert tracked.decision.spent_before_s == pytest.approx(0.0)
    assert {key[1] for key in tracker._states} == {"turn-b"}
