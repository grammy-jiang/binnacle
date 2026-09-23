"""Process-local cumulative blocking-wall accounting.

This module owns the deterministic policy state used by the Phase-2 guard.
Steps 2.4 through 2.6 implement sequential, overlapping, and bounded-state
accounting. Step 2.7 integrates the tracker with positive job_status waits.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "BlockingDecision",
    "BlockingLease",
    "BlockingRelease",
    "BlockingWallTracker",
    "TurnState",
]


@dataclass(frozen=True, slots=True)
class BlockingDecision:
    """The wait decision made when a caller acquires a lease."""

    policy: str
    requested_wait_s: int
    bounded_wait_s: int
    effective_wait_s: int
    budget_s: int | None
    spent_before_s: float | None
    remaining_before_s: float | None
    active_before: int
    blocking_budget_exhausted: bool


@dataclass(frozen=True, slots=True)
class BlockingRelease:
    """Accounting state observed when a lease is released."""

    spent_after_s: float | None
    remaining_after_s: float | None
    active_after: int
    window_closed: bool
    window_wall_s: float | None


@dataclass(slots=True)
class TurnState:
    """Process-local accounting for one client/base-turn key."""

    budget_s: int
    spent_s: float
    active_count: int
    active_window_started: float | None
    active_window_deadline: float | None
    last_seen: float


class BlockingLease:
    """One idempotently releasable blocking-wall decision."""

    def __init__(
        self,
        decision: BlockingDecision,
        release_callback: Callable[[], BlockingRelease],
    ) -> None:
        self.decision = decision
        self._release_callback = release_callback
        self._release_lock = threading.Lock()
        self._release_result: BlockingRelease | None = None

    def release(self) -> BlockingRelease:
        """Release once; repeated calls return the original result."""

        with self._release_lock:
            if self._release_result is None:
                self._release_result = self._release_callback()
            return self._release_result


class BlockingWallTracker:
    """Track cumulative blocking wall time for per-turn waits."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        capacity: int = 4096,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._clock = clock
        self._capacity = capacity
        self._lock = threading.Lock()
        self._states: dict[tuple[str | None, str], TurnState] = {}

    def acquire(
        self,
        *,
        client: str | None,
        turn: str | None,
        requested_wait_s: int,
        bounded_wait_s: int,
        budget_s: int | None,
    ) -> BlockingLease:
        """Return the policy decision and a lease for one positive wait."""

        if budget_s is None:
            return self._untracked_lease(
                policy="no_policy",
                requested_wait_s=requested_wait_s,
                bounded_wait_s=bounded_wait_s,
            )
        if turn is None:
            return self._untracked_lease(
                policy="no_turn",
                requested_wait_s=requested_wait_s,
                bounded_wait_s=bounded_wait_s,
            )

        key = (client, turn)
        with self._lock:
            now = self._clock()
            state = self._states.get(key)
            if state is None:
                if len(self._states) >= self._capacity:
                    evicted = self._evict_lru_inactive()
                    if not evicted:
                        return self._untracked_lease(
                            policy="capacity_untracked",
                            requested_wait_s=requested_wait_s,
                            bounded_wait_s=bounded_wait_s,
                        )
                state = TurnState(
                    budget_s=budget_s,
                    spent_s=0.0,
                    active_count=0,
                    active_window_started=None,
                    active_window_deadline=None,
                    last_seen=now,
                )
                self._states[key] = state

            state.last_seen = now
            active_before = state.active_count
            if active_before:
                if (
                    state.active_window_started is None
                    or state.active_window_deadline is None
                ):
                    raise RuntimeError("active blocking window is incomplete")
                active_elapsed = max(
                    0.0,
                    min(now, state.active_window_deadline)
                    - state.active_window_started,
                )
                spent_before = state.spent_s + active_elapsed
                remaining_before = max(0.0, state.active_window_deadline - now)
            else:
                spent_before = state.spent_s
                remaining_before = max(0.0, state.budget_s - spent_before)

            if remaining_before < 1.0:
                decision = BlockingDecision(
                    policy="exhausted",
                    requested_wait_s=requested_wait_s,
                    bounded_wait_s=bounded_wait_s,
                    effective_wait_s=0,
                    budget_s=state.budget_s,
                    spent_before_s=spent_before,
                    remaining_before_s=remaining_before,
                    active_before=active_before,
                    blocking_budget_exhausted=True,
                )
                return BlockingLease(decision, self._noop_release(decision))

            effective_wait = max(
                0,
                min(bounded_wait_s, math.floor(remaining_before)),
            )
            decision = BlockingDecision(
                policy="tracked",
                requested_wait_s=requested_wait_s,
                bounded_wait_s=bounded_wait_s,
                effective_wait_s=effective_wait,
                budget_s=state.budget_s,
                spent_before_s=spent_before,
                remaining_before_s=remaining_before,
                active_before=active_before,
                blocking_budget_exhausted=False,
            )
            if effective_wait <= 0:
                return BlockingLease(decision, self._noop_release(decision))

            if not active_before:
                state.active_window_started = now
                state.active_window_deadline = now + remaining_before
            state.active_count += 1

        return BlockingLease(decision, lambda: self._release_active(key))

    def _evict_lru_inactive(self) -> bool:
        candidate_key: tuple[str | None, str] | None = None
        candidate_last_seen = 0.0
        for key, state in self._states.items():
            if state.active_count:
                continue
            if candidate_key is None or state.last_seen < candidate_last_seen:
                candidate_key = key
                candidate_last_seen = state.last_seen

        if candidate_key is None:
            return False

        del self._states[candidate_key]
        return True

    def _release_active(self, key: tuple[str | None, str]) -> BlockingRelease:
        with self._lock:
            now = self._clock()
            state = self._states[key]
            if state.active_count < 1:
                raise RuntimeError("active lease state is inconsistent")
            if (
                state.active_window_started is None
                or state.active_window_deadline is None
            ):
                raise RuntimeError("active blocking window is incomplete")

            state.active_count -= 1
            state.last_seen = now
            if state.active_count:
                active_elapsed = max(
                    0.0,
                    min(now, state.active_window_deadline)
                    - state.active_window_started,
                )
                spent_after = min(
                    float(state.budget_s),
                    state.spent_s + active_elapsed,
                )
                remaining_after = max(0.0, state.active_window_deadline - now)
                return BlockingRelease(
                    spent_after_s=spent_after,
                    remaining_after_s=remaining_after,
                    active_after=state.active_count,
                    window_closed=False,
                    window_wall_s=None,
                )

            window_wall = max(
                0.0,
                min(now, state.active_window_deadline) - state.active_window_started,
            )
            state.spent_s = min(
                float(state.budget_s),
                state.spent_s + window_wall,
            )
            state.active_window_started = None
            state.active_window_deadline = None
            remaining_after = max(0.0, state.budget_s - state.spent_s)

            return BlockingRelease(
                spent_after_s=state.spent_s,
                remaining_after_s=remaining_after,
                active_after=0,
                window_closed=True,
                window_wall_s=window_wall,
            )

    @staticmethod
    def _noop_release(
        decision: BlockingDecision,
    ) -> Callable[[], BlockingRelease]:
        def release() -> BlockingRelease:
            return BlockingRelease(
                spent_after_s=decision.spent_before_s,
                remaining_after_s=decision.remaining_before_s,
                active_after=decision.active_before,
                window_closed=False,
                window_wall_s=None,
            )

        return release

    @classmethod
    def _untracked_lease(
        cls,
        *,
        policy: str,
        requested_wait_s: int,
        bounded_wait_s: int,
    ) -> BlockingLease:
        decision = BlockingDecision(
            policy=policy,
            requested_wait_s=requested_wait_s,
            bounded_wait_s=bounded_wait_s,
            effective_wait_s=bounded_wait_s,
            budget_s=None,
            spent_before_s=None,
            remaining_before_s=None,
            active_before=0,
            blocking_budget_exhausted=False,
        )
        return BlockingLease(decision, cls._noop_release(decision))
