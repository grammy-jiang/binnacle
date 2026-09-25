# Phase 4 Step 4.5 micro scheduler sanity

Verdict: **PASS**.

The canonical evidence set contains nine valid M1/M2/M3 trials across A, B,
and C300. The original B/M3 attempt was infrastructure-invalid because its
prelaunched fixture job had already exited before the wait call; the single
permitted B/M3 rerun is the valid evidence row.

## Mechanical gate

- deterministic_correctness_all_trials: **PASS**
- duplicate_non_repeat_logical_calls_zero: **PASS**
- m2_peak_inflight_at_least_2_all_arms: **PASS**
- m2_overlap_ratio_positive_all_arms: **PASS**
- m3_wait_read_relation_true_all_arms: **PASS**
- connector_routing_matches_all_trials: **PASS**
- benchmark_setup_tool_schema_errors_zero: **PASS**

Aggregate: 9/9 deterministic correctness, zero duplicate logical calls,
M2 minimum peak inflight 3 with minimum overlap ratio 0.375,
and M3 wait/read relation true on all three arms.

## D5 post-send robustness

C300/M1 and B/M2 had already completed their measured MCP work and captured
DONE; cleanup HTTP 429 was downstream of scheduler behavior. D5 makes
completed submissions immune to cleanup failure, retries transient reply
reads with bounded backoff without resubmission, and lets analysis use the
captured send reply when cleanup could not save a transcript.

Focused D5 regression: 34/34 PASS. Full Step-4.5 integration matrix:
114/114 PASS. Production isolation remains at the accepted D2 baseline.

## 4.6B0 preparation

Use R2 for read-heavy qualification because it is the direct ten-file
known-path fan-out with no discovery dependency. Use R5 for wait-heavy
qualification because it is the shortest frozen true dependency barrier.
The serial reference uses five repeats per arm/case, matching the Phase-4
R1-R6 standard repeat count, followed by separate Q-read(1) and Q-wait(1)
matched A/B/C300 blocks.

Run request: 4.6B0-qual

SHA-256:
deb26d1d621be0a53933be1b0cb983d8ab6eaae19da47203f22ac645b6f769b4.

The request is prepared only; live execution remains manager-owned.
