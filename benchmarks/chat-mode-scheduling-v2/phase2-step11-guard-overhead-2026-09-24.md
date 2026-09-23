# Phase 2 Step 2.11 — blocking-wall guard overhead

Date: 2026-09-24 (Australia/Sydney)

The benchmark measures one BlockingWallTracker.acquire() plus matching
BlockingLease.release() with no sleeping. Each of the three independent Pi
runs executes 100,000 iterations.

| Run | Iterations | p50 ms | p90 ms | p95 ms | p99 ms | max ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 100000 | 0.006203 | 0.006296 | 0.006445 | 0.007259 | 0.054630 |
| 2 | 100000 | 0.006167 | 0.006260 | 0.006407 | 0.007148 | 0.052593 |
| 3 | 100000 | 0.006093 | 0.006240 | 0.006778 | 0.036204 | 0.261536 |

Median of the three run-level p95 values: **0.006445 ms**.
Median of the three run-level p99 values: **0.007259 ms**.

Design targets:

- p95 < 1 ms: **PASS**
- p99 < 2 ms: **PASS**

Command used for each independent run:

    uv run python scripts/benchmark_blocking_wall_guard.py --iterations 100000

The benchmark is evidence only; the 1 ms / 2 ms targets are not encoded as a
normal CI wall-clock gate.
