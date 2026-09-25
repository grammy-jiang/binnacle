"""Amendment-A1 repeated-wait burden metrics for Phase-3 replay."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from scripts.chat_scheduling_replay import (
    EPSILON,
    PER_CALL_CAP_S,
    _historical_interval,
    _nonnegative,
    _percent,
    _rounded,
    _union_before,
    _validate_row,
    _wait_sort_key,
    interval_union_seconds,
)


def calculate_repeated_wait_burden(
    row: Mapping[str, Any], *, policy: str, budget_s: float
) -> dict[str, float | None]:
    """Return definition-(b) repeated-wait burden without changing replay rows."""

    _validate_row(row)
    budget = _nonnegative(budget_s, "budget_s")
    if budget <= 0:
        raise ValueError("budget_s must be > 0")
    if policy not in {"cumulative", "historical-one-shot"}:
        raise ValueError(f"unsupported replay policy: {policy}")
    if policy == "historical-one-shot" and abs(budget - 10.0) > EPSILON:
        raise ValueError("historical-one-shot policy is the frozen H10 budget (10 s)")

    waits = sorted(row["waits"], key=_wait_sort_key)
    candidate_intervals: list[tuple[float, float]] = []
    observed_repeated: dict[str, list[tuple[float, float]]] = defaultdict(list)
    candidate_repeated: dict[str, list[tuple[float, float]]] = defaultdict(list)
    positive_waits_by_job: dict[str, int] = defaultdict(int)
    h10_positive_seen = False

    for wait in waits:
        if not isinstance(wait, Mapping):
            raise TypeError("each wait must be an object")
        start, historical_end, requested = _historical_interval(wait)
        observed_duration = max(historical_end - start, 0.0)
        positive_request = requested > EPSILON
        job_id = wait.get("job_id_hash")
        if positive_request and (not isinstance(job_id, str) or not job_id):
            raise ValueError("positive wait is missing job_id_hash")
        repeated = bool(positive_request and positive_waits_by_job[str(job_id)] > 0)
        if positive_request:
            positive_waits_by_job[str(job_id)] += 1

        effective_end = start
        if policy == "cumulative":
            remaining = max(budget - _union_before(candidate_intervals, start), 0.0)
            if positive_request and remaining < 1.0 - EPSILON:
                pass
            elif positive_request and observed_duration > EPSILON:
                duration = min(observed_duration, PER_CALL_CAP_S, remaining)
                effective_end = start + duration
                if duration > EPSILON:
                    candidate_intervals.append((start, effective_end))
        elif positive_request and not h10_positive_seen:
            h10_positive_seen = True
            duration = min(observed_duration, requested, budget, PER_CALL_CAP_S)
            effective_end = start + duration
            if duration > EPSILON:
                candidate_intervals.append((start, effective_end))
        elif positive_request:
            pass

        if repeated:
            if historical_end - start > EPSILON:
                observed_repeated[str(job_id)].append((start, historical_end))
            if effective_end - start > EPSILON:
                candidate_repeated[str(job_id)].append((start, effective_end))

    observed = sum(
        interval_union_seconds(intervals) for intervals in observed_repeated.values()
    )
    candidate = sum(
        interval_union_seconds(intervals) for intervals in candidate_repeated.values()
    )
    return {
        "observed_repeated_wait_burden_s": _rounded(observed),
        "candidate_repeated_wait_burden_s": _rounded(candidate),
        "repeated_wait_burden_reduction_percent": _percent(observed, candidate),
    }
