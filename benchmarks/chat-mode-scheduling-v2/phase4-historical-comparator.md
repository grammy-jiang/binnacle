# Phase 4 historical H comparator

Generated: 2026-09-26T02:48:21+10:00

Status: **COMPLETE (diagnostic only)**. H does not alter the C hard-gate matrix or
any Step 4.12 verdict.

## Evidence basis

- Phase-4 source: `06bc1649c4bad9449470366da971649bb7620020`.
- H lane: historical one-shot 10 s guard, manifest SHA-256
  `d9bfc26661289baa2db99394fd2872d09965c06fa7bc26ff8cebaa18c4ccbed7`.
- 4H request SHA-256:
  `ef2af7dee0d3152222e64598bcc4fc8234d02f5bcc86e96018a001301bc2cb41`.
- 4H manager result SHA-256:
  `3747ac0a13b0a399b3dde86e278ec4593e602b6c0bb37b794911601e87eab8b5`.
- The manager froze 10 owning H slots. One earlier R5 send timed out before MCP
  submission (`r5-20260926T011203-422b82b48e`) and is excluded from slot metrics.
- Step 4.7 selected no C endpoint (`NO_GO`), so this report compares H with the
  C300 calibration trials as required. C300 result hashes are
  `4ecbbd622113c843e7542b2eb67678fd7bf3daf0c51229dfb10c7acf06adbee5`
  and `51c4a3dadf977f9fab8601ae0e145e283020222929b0584cc4be1cc978dbdfce`.

## Evidence integrity and routing

The 4H manager rows contain `routing=null`, the same serialization gap already
seen for C300. Retained-log recovery found every owning H run id exactly once in
the H server log, zero times in A/B/C300 server logs, and zero times in the
production `binnacle-mcp` journal over the trial window. Therefore H has **0/10
routing misses (0%)** and remains scorable.

| Arm | Routing misses | Submitted trials | Miss rate |
| --- | ---: | ---: | ---: |
| A | 1 | 13 | 7.69% |
| B | 0 | 13 | 0% |
| C | 0 | 24 | 0% |
| H | 0 | 10 | 0% |

No arm exceeds the P4-A2 evidence-integrity threshold of greater than 10%.

## H trial results

| Slot | Wall s | Blocking s | Correct | Same prompt | Budget handoff | Premature | Interrupted | Continuations | Provenance |
| --- | ---: | ---: | --- | --- | --- | --- | --- | ---: | --- |
| 4H:R5:1 | 46.965 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R5:2 | 62.556 | 10.001 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R5:3 | 45.525 | 10.001 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R6:1 | 66.207 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R6:2 | 47.418 | 10.001 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R6:3 | 120.512 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R7:1 | 88.039 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R7:2 | 43.376 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R7:3 | 77.226 | 10.000 | no | no | yes | no | no | 1 | budget exhaustion |
| 4H:R12:1 | 34.147 | 10.001 | no | no | no | yes | no | 1 | unclassified |

Across bounded R5/R6/R7, H is **0/9 correct**, **0/9 same-prompt**, **9/9
budget-exhaustion handoffs**, **0/9 premature handoffs**, and **0/9
interruptions**. Every bounded slot requires one continuation. Provenance is
`budget_exhaustion` for all nine bounded trials.

## R12 budget-exhaustion diagnostic

R12 replied with the requested textual handoff:
`BUDGET_EXHAUSTED job_id=9e04baef17a8 state=running pending=dependency resume=job_status`.
However, the sole `job_status` call requested 50 s and was bounded by H to an
effective 10 s. It returned `state=running`, `blocking_remaining_s=0.0`, but
`blocking_budget_exhausted=false`. The assistant made no second same-turn/job
call to observe the historical guard's exhausted result. The analyzer therefore
records **budget-exhaustion handoff=false**, **premature handoff=true**, and
**correctness=false**. This is consistent with R12 provenance remaining
unclassified.

## Comparison with C300 calibration

Because Step 4.7 selected no C endpoint, C300 calibration is the comparison basis.

| Scenario | H median wall s | C300 median wall s | H same-prompt | C300 same-prompt |
| --- | ---: | ---: | ---: | ---: |
| R5 | 46.965 | 40.268 | 0/3 | 1/3 |
| R6 | 66.207 | 108.399 | 0/3 | 3/3 |
| R7 | 77.226 | 158.269 | 0/3 | 3/3 |

Over all nine bounded trials, H's raw median wall time is 62.556 s versus
108.399 s for C300, a raw H/C300 ratio of 0.57709. That is **not** a successful
completion speedup: all nine H trials hand off after exhausting the historical
10 s blocking budget, while C300 completes 7/9 in the same prompt. H requires
9 total continuations versus 2 for C300.

For R12, H returns after 34.147 s but is classified as premature because the
explicit exhaustion signature is absent. C300 runs 347.819 s and is recognized
as a budget-exhaustion handoff with no premature handoff, although C300 R12 is
also analyzer-incorrect because the required successful exhaustion-marked
`wait_result` is absent.

## Conclusion

The historical H one-shot 10 s policy systematically converts the targeted
wait-heavy scenarios into continuation handoffs rather than same-prompt
completion. It is useful as a historical diagnostic but provides no basis to
revise Step 4.7: H is not a production candidate and does not alter C gates.
Evidence integrity is clean after routing recovery. Phase 4 is still blocked at
Step 4.7, so there is no completed Step 4.13 handoff to append; these comparator
hashes remain available if the phase is later resumed.
