# Phase 4 4C scheduling / guard / efficiency review

Focus review only; this artifact does not issue a Phase-4 GO/NO-GO verdict.

## Canonical focus gates

| Gate | Class | Status | Evidence |
| --- | --- | --- | --- |
| avoidable_blocking_wall_p90_le_2s | REQUIRED | PASS | value=0.0 s |
| eligible_overlap_ratio_ge_80_percent | REQUIRED | FAIL | 123/230 = 0.534783 |
| m2_m3_sliding_refill_demonstrated | REQUIRED | PASS | {'post_run_micro_correctness': '9/9', 'm2_min_read_only_peak_inflight': 3, 'm2_min_overlap_ratio': 0.375, 'm3_relations_true': '3/3'} |
| union_blocking_wall_le_budget_plus_1s | REQUIRED | PASS | C maximum 299.003 s including R12; ceiling 301.0 s |
| overlap_charged_once | REQUIRED | PASS | phase2 blocking-wall guard concurrency evidence; frozen guard source unchanged for Phase 4 |
| exhausted_calls_nonblocking | REQUIRED | PASS | {'scenario': 'R12', 'final_call_wait_requested_s': 1, 'final_call_wait_effective_s': 0, 'final_call_waited_s': 0.0, 'blocking_budget_exhausted': True} |
| guard_overhead_p95_lt_1ms | REQUIRED | PASS | value=0.006445 ms |
| guard_overhead_p99_lt_2ms | REQUIRED | PASS | value=0.007259 ms |
| repeated_wait_burden_reduction_ge_60_percent | REQUIRED | PASS | value=63.448499% |
| tool_result_tokens_le_a_plus_5_percent | REQUIRED | PASS | A=46159, C=46131, C/A=0.999393 |
| duplicate_completed_reads_no_increase | REQUIRED | PASS | A=0, C=0 |
| long_job_status_call_result_burden_reduction_ge_10_percent | DIAGNOSTIC_TARGET | TARGET_MISSED | calls A=52, C=53, reduction=-1.923077%; result-token reduction=-4.033051% |

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

## Timing recovery

Deferred cleanup recovered 79 macro slots after checkpoint freeze. The JSON artifact lists every recovered slot and state directory.
Four macro slots remain on observed time: R5-r03-C, R6-r01-C, R6-r02-C, R7-r02-C. They are not silently mixed with recovered timing.
R12-r01-C is a safety-only calibration slot with legacy chat-timing lacking settle_time_source; it is excluded from macro performance timing.

## Long-job call/result burden

For R3/R4/R5/R6/R7/R10, A used 52 job_status calls and C used 53; C-vs-A reduction is -1.923077%. Result-token reduction is -4.033051%. The diagnostic target is missed.

## Frozen-analyzer blocker

The frozen confirmatory analyzer does not recognize submission_status=failed_after_submission as submitted. Canonical checkpoint owner R7-r02-B (r7-20260926T200743-e7db9a34ac, provenance mcp_completed_browser_timeout) is dropped, so a canonical-only analyzer view reports 159/160 main slots. The prescribed global runs root is additionally contaminated by historical and qualification trials and reports 153/160.
This is not reconciled by changing the checkpoint owner or smoothing metrics. Step 4.11 must reconcile analyzer submission classification with frozen checkpoint semantics.

## Deviations and inherited evidence

- D2 is accepted inherited production drift outside the frozen Phase-4 source; observation baseline config hash remains d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195.
- P4-A2 routing exclusion is applied exactly.
- D9 timing recovery is applied and all remaining observed-time macro slots are explicit.

## Assignment/runbook hash blocker

The assignment packet pins runbook SHA-256 8206b1560a06c12f6fbf98754cd94915f415694903a3f334c295e1a14c1f8697, while the current clean planning worktree is at SHA-256 4b6ca10e642ec760c9b16bbf8f0af2cdd494211623307ca046e42b85fd91eb43 and its plan history now includes commit 52a1b00 (P4-A6). This attempt does not reinterpret scope against a moving runbook.
