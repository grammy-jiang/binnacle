# Phase 4 P4-A6 confirmatory gate aggregation

This snapshot records the computed-only confirmatory aggregation after Amendment
P4-A6. It is not the Step 4.11 final hard-gate matrix: the four 4C focus reviews
must rerun as attempt a2 against this fixed canonical head before Step 4.11.

## Population integrity

- Population source: six frozen checkpoint `canonical_slots` owner lists plus the
  frozen reused C300 R12 owner from `4B-C300.json`.
- Frozen checkpoint owners: **159**.
- Frozen R12 owners: **1**.
- Submitted main slots: **160/160**.
- Scorable main slots: **160/160**.
- Population issues: **0**.
- Global run-directory discovery: **not used**.

## P4-A6 timing repair

The six timing addenda extend, and do not rewrite, the frozen checkpoints.

- R1-R2: **10** regenerated rows.
- R3-R4: **19** regenerated rows.
- R5-R6: **12** regenerated rows.
- R7: **2** regenerated rows.
- R8-R9: **23** regenerated rows.
- R10-R11: **13** regenerated rows.
- Total: **79** regenerated rows.

Each changed row preserves its prior `metrics.json` and `trace.json` as
`.pre-p4a6` files and records old/new timing, metric, trace, wall-time and
settle-source values in its partition addendum.

## Computed gate observations

These observations use empty review shims deliberately, so only gates computed by
the canonical aggregator are authoritative in this snapshot.

- Correctness: **PASS**, selected C = 100%.
- Premature handoff: **PASS**, selected C = 0.
- Same-prompt completion: **PASS**, selected C = 53/53 bounded slots.
- Overall wall-time ratio C/A: **0.933267**, below the required 20% speedup.
- Read-heavy wall-time ratio C/A: **0.802584**, below the required 30% speedup.
- Mixed-long wall-time ratio C/A: **1.140670**, below the required 20% speedup.
- Paired C/A bootstrap 95% upper bound: **0.996546**, below 1.0.
- Eligible overlap ratio: **0.534783**, below the required 0.80.
- Tool-result token ratio C/A: **0.999393**, within the A + 5% limit.
- Category-regression computation emits an R3/R4 exception request because C is
  slower there while its same-prompt completion is higher than A.
- Continuation-reduction computation remains undefined because A requires zero
  manual continuations in the frozen population; the mechanical gate is false.

The snapshot reports only **9/26** required gates as PASS because externally
reviewed correctness/safety, guard and scheduling judgments are intentionally
absent. Attempt-a2 4C review artifacts are required before the final Step 4.11
matrix can be assembled.
