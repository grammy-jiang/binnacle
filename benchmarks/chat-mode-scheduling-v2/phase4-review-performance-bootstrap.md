# Phase 4 performance/bootstrap evidence review (4C a2)

This review is limited to the performance/bootstrap focus and records **no Phase-4 verdict**.

## Analyzer reproduction

- Canonical population: 160/160 submitted, 160/160 scorable; slot integrity passed.
- Re-run analytics exactly match phase4-confirmatory-gate-aggregation-p4a6.json.
- Paired C/A bootstrap: 53/53 pairs, median ratio 0.980312, 95% CI [0.935508, 0.996546] from 10000 samples.

## Performance gates

- overall_median_wall_ge_20_percent_faster: **FAIL** — {"c_a_ratio": 0.933267, "maximum_ratio": 0.8, "passed": false}
- read_heavy_median_ge_30_percent_faster: **FAIL** — {"c_a_ratio": 0.802584, "maximum_ratio": 0.7, "passed": false}
- mixed_long_median_ge_20_percent_faster: **FAIL** — {"c_a_ratio": 1.14067, "maximum_ratio": 0.8, "passed": false}
- category_median_regression_within_10_percent: **FAIL** — {"exception_requests": [{"a_median_wall_s": 75.414, "a_same_prompt_completion_rate": 0.8, "artifact_kind": "CATEGORY_REGRESSION_EXCEPTION_REQUEST", "c_a_ratio": 1.14067, "c_median_wall_s": 86.0225, "c_same_prompt_completion_rate": 1.0, "category": "overlap_long", "owner_approval_required": true, "scenarios": ["R3", "R4"]}], "maximum_ratio_without_exception": 1.1, "passed": false}
- paired_c_a_bootstrap_upper_lt_1: **PASS** — {"ci_95_upper": 0.996546, "pair_count": 53, "passed": true, "threshold": 1.0}

## Aggregate performance

- Overall median wall: A 45.225 s; C 42.207 s; C/A 0.933267.
- R1/R2/R11 read-heavy target C/A: 0.802584.
- R3/R4 mixed-long target C/A: 1.140670.

## Routing misses

- Arm A: 1/54 routing misses (1.85%); pre-submit failures 3; above 10%: no.
- Arm B: 0/53 routing misses (0.00%); pre-submit failures 0; above 10%: no.
- Arm C: 0/53 routing misses (0.00%); pre-submit failures 0; above 10%: no.

Per-partition routing-miss counts/rates:

- R1-R2: A 0/10 (0.00%); B 0/10 (0.00%); C 0/10 (0.00%).
- R3-R4: A 0/10 (0.00%); B 0/10 (0.00%); C 0/10 (0.00%).
- R5-R6: A 0/10 (0.00%); B 0/10 (0.00%); C 0/10 (0.00%).
- R7: A 0/3 (0.00%); B 0/3 (0.00%); C 0/3 (0.00%).
- R8-R9: A 1/11 (9.09%); B 0/10 (0.00%); C 0/10 (0.00%).
- R10-R11: A 0/10 (0.00%); B 0/10 (0.00%); C 0/10 (0.00%).

## Partition review

### R1-R2

- Median wall: A 20.960 s; B 18.580 s; C 18.317 s; C/A 0.873927.
- Timing addendum rows: 10; still observed now: 0; host-load-flagged canonical rows: 3.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R1-R2.json SHA-256 f5ba852a217230769512b56311e160f01f00e872b80cda516a866f20e4bf1560.

### R3-R4

- Median wall: A 75.414 s; B 75.858 s; C 86.022 s; C/A 1.140670.
- Timing addendum rows: 19; still observed now: 0; host-load-flagged canonical rows: 4.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R3-R4.json SHA-256 8bbf1fc8d1e3033f126adbf8c61b9b19d7219135da42470074d6aa4f3bbdefdb.

### R5-R6

- Median wall: A 75.575 s; B 72.406 s; C 70.674 s; C/A 0.935163.
- Timing addendum rows: 12; still observed now: 3; host-load-flagged canonical rows: 6.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R5-R6.json SHA-256 188c883ec60473dc258ebf6e0c42714405d1e6e1fb0b43cdf27d68c85e0d7ab0.

### R7

- Median wall: A 161.881 s; B 157.270 s; C 155.160 s; C/A 0.958482.
- Timing addendum rows: 2; still observed now: 1; host-load-flagged canonical rows: 0.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R7.json SHA-256 889eafe4d134c0715694cc1651ad1daf1b663a7bae84974933ae202b8d744d53.

### R8-R9

- Median wall: A 42.471 s; B 43.953 s; C 43.965 s; C/A 1.035177.
- Timing addendum rows: 23; still observed now: 0; host-load-flagged canonical rows: 0.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R8-R9.json SHA-256 c26b7ab715f56cdd8172575096d5fe9143645a68836de4f7526dbfd71e20de27.

### R10-R11

- Median wall: A 75.445 s; B 84.833 s; C 67.541 s; C/A 0.895236.
- Timing addendum rows: 13; still observed now: 0; host-load-flagged canonical rows: 5.
- Scratch fragment: /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/performance-bootstrap/R10-R11.json SHA-256 95dce21a36684ac56714e32eadd9a18a65199d5278175fc80a00d6a9d271e4c3.

## P4-A6 timing recovery

- Recomputed after D9 recovery: 79 canonical rows.
- Current conversation-final-assistant timing: 155/159 performance rows.
- Still on observed time: 4/159 performance rows.
- metrics.json wall time equals current chat-timing.json wall time for all 159 performance rows.

Recomputed trial slots:

- R1-R2 (10): R1-r01-C, R1-r03-A, R1-r03-B, R1-r05-A, R1-r05-B, R1-r05-C, R2-r02-B, R2-r02-C, R2-r03-A, R2-r04-A.
- R3-R4 (19): R3-r02-A, R3-r02-B, R3-r03-B, R3-r03-C, R3-r04-B, R3-r05-A, R4-r01-A, R4-r01-B, R4-r01-C, R4-r02-A, R4-r02-B, R4-r02-C, R4-r03-B, R4-r03-C, R4-r04-A, R4-r04-C, R4-r05-A, R4-r05-B, R4-r05-C.
- R5-R6 (12): R5-r01-B, R5-r04-A, R5-r04-C, R5-r05-A, R6-r01-A, R6-r02-A, R6-r02-B, R6-r03-A, R6-r04-B, R6-r04-C, R6-r05-A, R6-r05-B.
- R7 (2): R7-r01-A, R7-r01-B.
- R8-R9 (23): R8-r01-A, R8-r01-B, R8-r02-B, R8-r02-C, R8-r03-C, R8-r04-A, R8-r04-B, R8-r04-C, R8-r05-A, R8-r05-B, R8-r05-C, R9-r01-A, R9-r01-B, R9-r01-C, R9-r02-A, R9-r02-C, R9-r03-B, R9-r03-C, R9-r04-A, R9-r04-B, R9-r04-C, R9-r05-A, R9-r05-C.
- R10-R11 (13): R10-r01-A, R10-r01-B, R10-r01-C, R10-r02-A, R10-r02-B, R10-r02-C, R10-r04-A, R10-r04-B, R10-r04-C, R11-r01-B, R11-r05-A, R11-r05-B, R11-r05-C.

Trials still on observed time:

- R5-R6 R5-r03-C (r5-20260926T011904-c834d991d6): 40.268 s; settle_time_source absent.
- R5-R6 R6-r01-C (r6-20260926T012431-17c772cd31): 104.552 s; settle_time_source absent.
- R5-R6 R6-r02-C (r6-20260926T012946-4ee162a667): 108.399 s; settle_time_source absent.
- R7 R7-r02-C (r7-20260926T014904-e32fdb3f45): 155.160 s; settle_time_source absent.

## A1 blocker disposition

- D10a_population: **RESOLVED** — Reproduced aggregation uses six frozen checkpoint canonical-slot owners plus frozen R12; slot integrity is 160/160 submitted and 160/160 scorable with no unscheduled owners.
- D10b_failed_after_submission: **RESOLVED** — R7-r02-B remains the canonical submitted owner and the reproduced population is 160/160; failed_after_submission is no longer dropped.
- D10c_recovered_timing_not_regenerated: **RESOLVED** — All 79 P4-A6 addendum rows match regenerated chat-timing/metrics/trace hashes; metrics.wall_s equals chat-timing.wall_s for every canonical slot. Four unchanged reused C rows remain on observed timing and are listed explicitly.

## Category regression exception request

- Artifact kind: CATEGORY_REGRESSION_EXCEPTION_REQUEST; category overlap_long; scenarios R3, R4.
- A median 75.414 s (10 trials), C median 86.022 s (10 trials), C/A 1.140670.
- Same-prompt completion: A 80.0%, C 100.0%; owner approval required and status PENDING_OWNER_APPROVAL.
- A canonical trial ids: R3-r01-A, R3-r02-A, R3-r03-A, R3-r04-A, R3-r05-A, R4-r01-A, R4-r02-A, R4-r03-A, R4-r04-A, R4-r05-A.
- C canonical trial ids: R3-r01-C, R3-r02-C, R3-r03-C, R3-r04-C, R3-r05-C, R4-r01-C, R4-r02-C, R4-r03-C, R4-r04-C, R4-r05-C.

## Scope note

This review does not write or imply the final Phase-4 verdict. The orchestrator owns the 4.11 fan-in and final gate matrix.
