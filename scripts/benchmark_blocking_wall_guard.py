"""Measure blocking-wall tracker acquire/release overhead without sleeping."""

from __future__ import annotations

import argparse
import json
import math
import platform
import time

from binnacle.blocking_wall_guard import BlockingWallTracker


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one sample")
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def benchmark(iterations: int) -> dict[str, float | int]:
    if iterations < 100_000:
        raise ValueError("iterations must be at least 100000")

    tracker = BlockingWallTracker()
    samples_ms: list[float] = []
    for _ in range(iterations):
        started_ns = time.perf_counter_ns()
        lease = tracker.acquire(
            client="benchmark-client",
            turn="benchmark-turn",
            requested_wait_s=1,
            bounded_wait_s=1,
            budget_s=3600,
        )
        lease.release()
        samples_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)

    samples_ms.sort()
    return {
        "iterations": iterations,
        "p50_ms": _percentile(samples_ms, 0.50),
        "p90_ms": _percentile(samples_ms, 0.90),
        "p95_ms": _percentile(samples_ms, 0.95),
        "p99_ms": _percentile(samples_ms, 0.99),
        "max_ms": samples_ms[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100_000)
    args = parser.parse_args()

    result = {
        "schema_version": 1,
        "benchmark": "blocking_wall_guard_acquire_release",
        "clock": "time.perf_counter_ns",
        "tracker_clock": "time.monotonic",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "result": benchmark(args.iterations),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
