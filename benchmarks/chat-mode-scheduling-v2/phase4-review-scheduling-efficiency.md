# Phase 4 4C scheduling / guard / efficiency review

Focus review only; this artifact does not issue a Phase-4 GO/NO-GO verdict.

## Attempt-a2 blocker resolution

| A1 blocker | A2 status | Evidence |
| --- | --- | --- |
| `frozen_analyzer_submission_status_incompatibility` | RESOLVED | P4-A6 D10b adds failed_after_submission to _submitted(); the frozen owner R7-r02-B remains retained and the re-run analyzer reports 160/160 submitted and scorable main slots. |
| `assignment_runbook_hash_mismatch` | RESOLVED | a2 packet and current planning worktree both pin runbook SHA-256 4b6ca10e642ec760c9b16bbf8f0af2cdd494211623307ca046e42b85fd91eb43. |

Both a1 analysis-pipeline blockers are resolved. The focus-gate measurements themselves are unchanged after P4-A6.

## Canonical focus gates

| Gate | Class | Status | Evidence |
| --- | --- | --- | --- |
| `avoidable_blocking_wall_p90_le_2s` | REQUIRED | PASS | value=0.0 s |
| `eligible_overlap_ratio_ge_80_percent` | REQUIRED | FAIL | 123/230 = 0.534783 |
| `m2_m3_sliding_refill_demonstrated` | REQUIRED | PASS | 9/9 correctness; M2 min peak=3; M2 min overlap=0.375; M3 relations=3/3 |
| `union_blocking_wall_le_budget_plus_1s` | REQUIRED | PASS | C maximum 299.003 s including R12; ceiling 301.0 s |
| `overlap_charged_once` | REQUIRED | PASS | phase2 blocking-wall guard concurrency evidence; frozen guard source unchanged for Phase 4 |
| `exhausted_calls_nonblocking` | REQUIRED | PASS | R12 final exhausted call requested 1 s, effective 0 s, waited 0.0 s |
| `guard_overhead_p95_lt_1ms` | REQUIRED | PASS | value=0.006445 ms |
| `guard_overhead_p99_lt_2ms` | REQUIRED | PASS | value=0.007259 ms |
| `repeated_wait_burden_reduction_ge_60_percent` | REQUIRED | PASS | value=63.448499% |
| `tool_result_tokens_le_a_plus_5_percent` | REQUIRED | PASS | A=46159, C=46131, C/A=0.999393 |
| `duplicate_completed_reads_no_increase` | REQUIRED | PASS | A=0, C=0 |
| `long_job_status_call_result_burden_reduction_ge_10_percent` | DIAGNOSTIC_TARGET | TARGET_MISSED | calls A=52, C=53, call reduction=-1.923077%; result-token reduction=-4.033051% |

## Partition review

| Partition | C overlap | C tokens | C duplicate calls | Routing misses A/B/C | Recomputed timing | Still observed |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| R1/R2 | 0.6125 | 8295 | 0 | 0/0/0 | 10 | 0 |
| R3/R4 | 0.4625 | 13993 | 0 | 0/0/0 | 19 | 0 |
| R5/R6 | n/a | 4080 | 0 | 0/0/0 | 12 | 3 |
| R7 | n/a | 3373 | 0 | 0/0/0 | 2 | 1 |
| R8/R9 | 0.32 | 7812 | 0 | 1/0/0 | 23 | 0 |
| R10/R11 | 0.644444 | 8578 | 0 | 0/0/0 | 13 | 0 |

## Routing integrity

Aggregate routing misses: A 1/54 (0.018519), B 0/53 (0.000000), C 0/53 (0.000000).
R9-r03-A had one excluded routing miss with eight production calls; its correctly routed attempt 2 owns the slot. The miss is a non-mutating isolation incident.

## Timing recovery and P4-A6 addenda

The six P4-A6 timing addenda bind 79 recovered macro trials to regenerated `metrics.json` and `trace.json` hashes. Four macro trials remain on observed time and are not silently mixed with recovered timing.

- R1/R2 recovered after checkpoint (10): R1-r01-C, R1-r03-A, R1-r03-B, R1-r05-A, R1-r05-B, R1-r05-C, R2-r02-B, R2-r02-C, R2-r03-A, R2-r04-A.
- R3/R4 recovered after checkpoint (19): R3-r02-A, R3-r02-B, R3-r03-B, R3-r03-C, R3-r04-B, R3-r05-A, R4-r01-A, R4-r01-B, R4-r01-C, R4-r02-A, R4-r02-B, R4-r02-C, R4-r03-B, R4-r03-C, R4-r04-A, R4-r04-C, R4-r05-A, R4-r05-B, R4-r05-C.
- R5/R6 recovered after checkpoint (12): R5-r01-B, R5-r04-A, R5-r04-C, R5-r05-A, R6-r01-A, R6-r02-A, R6-r02-B, R6-r03-A, R6-r04-B, R6-r04-C, R6-r05-A, R6-r05-B.
- R7 recovered after checkpoint (2): R7-r01-A, R7-r01-B.
- R8/R9 recovered after checkpoint (23): R8-r01-A, R8-r01-B, R8-r02-B, R8-r02-C, R8-r03-C, R8-r04-A, R8-r04-B, R8-r04-C, R8-r05-A, R8-r05-B, R8-r05-C, R9-r01-A, R9-r01-B, R9-r01-C, R9-r02-A, R9-r02-C, R9-r03-B, R9-r03-C, R9-r04-A, R9-r04-B, R9-r04-C, R9-r05-A, R9-r05-C.
- R10/R11 recovered after checkpoint (13): R10-r01-A, R10-r01-B, R10-r01-C, R10-r02-A, R10-r02-B, R10-r02-C, R10-r04-A, R10-r04-B, R10-r04-C, R11-r01-B, R11-r05-A, R11-r05-B, R11-r05-C.

Still observed-time macro trials: R5-r03-C, R6-r01-C, R6-r02-C, R7-r02-C.
R12-r01-C is a safety-only calibration slot with legacy `chat-timing.json` lacking `settle_time_source`; it is excluded from macro performance timing.

## Long-job call/result burden

For R3/R4/R5/R6/R7/R10, A used 52 `job_status` calls and C used 53; C-vs-A call reduction is -1.923077%. Result-token reduction is -4.033051%. The diagnostic target is missed.

## Deviations and inherited evidence

- D2 is accepted inherited production drift outside the frozen Phase-4 source; observation baseline config hash remains `d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195`.
- P4-A2 routing exclusion is applied exactly.
- D9 timing recovery is applied; all 79 recovered macro trials and all four remaining observed-time macro trials are explicit.
- P4-A6 D10a/D10b/D10c is applied: frozen-owner population scanning, `failed_after_submission` submission classification, and regenerated post-D9 metrics are all reflected in this review.

## Fragment provenance

- R1/R2: checkpoint `bf8bdc772fe586cef3bd893df44144f126d891357d81b9002e921798a4da292b`, timing addendum `042ebd866e134141fad41d37c9fabde017cd4eb084d5ef898664fafb39b1f4a8`, fragment `3621cacdfb35ae99d2d4f770e6e155917b042ed78e94333c735b7eb29dfb3433`.
- R3/R4: checkpoint `6f1ac078cab68ecbbf2435e688e040ca0453992e411eb427624595ed43f17bdd`, timing addendum `a900482a52f997432fd8b75356572c6d452e2349337a171bf60a40e6a130b295`, fragment `0bbc0b1824f3ab56d1fbc72701853c8a4e9bec3427fa0b42819794b26015df69`.
- R5/R6: checkpoint `0938d4b6abc7cd5258591f46c142a28dde963e32dfe30ffc8ead1f4a78fcc589`, timing addendum `82e12eefca1fe11eb07470548ba50f6fa7140b073a8dcb92162e3e737a35effa`, fragment `581e8c1b47523e17aafe9fa729d9815f31410ac5152a76f0ca2b2e28dfef4fd4`.
- R7: checkpoint `344e2b5f372e46dc80dab7df0166a86e58cf5624b358664d2d48bd3b8ffec63a`, timing addendum `b473d7c4c62982d3cff4e283d9f4f08a564cfac97aa0b410169bbdba0e9792ea`, fragment `79d6275706cdb10c857409725f8a248787c06bf629533484d53c6128278038cb`.
- R8/R9: checkpoint `f58ec042664049bb0df964c4a035f96d6378f82f45fe820e7af41718e44453c8`, timing addendum `30cc571c8131534ce1ae0c1404954a17b8e69446f7ec54ade28e717613af939c`, fragment `febca8af55f91ce5a49c0e5ce259a7a17907e0822065b029093a24c1cb79e3ae`.
- R10/R11: checkpoint `d7dbe437d1ca39c090bad760eecee647115a059f782aef39b5fb086414b3de14`, timing addendum `73cf2c7fb65ae852977566d1938aef24330bf16be5bc433fddb2f59a7a5bb672`, fragment `df13a504e2fc5cf494b469fe1522e68c59e586770d36fcc394fbfe59b4305d72`.
