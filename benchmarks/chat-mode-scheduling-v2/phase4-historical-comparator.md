# Phase 4 historical H comparator

Generated: 2026-09-26T08:07:12+10:00

Status: **COMPLETE (P4-A3 reanalysis; diagnostic only)**. H does not alter the C
hard-gate matrix or any Step 4.12 verdict.

## Evidence basis

- Phase-4 source: `06bc1649c4bad9449470366da971649bb7620020`.
- Corrected analyzer head: `76ec24eed464e1162f4b51d9549143bf6175d8bb`.
  The superseded comparator at commit `f600a1dc` used analyzer head
  `6073902ba1e72a946da0ea7d7e901e36f47f96a3`.
- H lane: historical one-shot 10 s guard, manifest SHA-256
  `d9bfc26661289baa2db99394fd2872d09965c06fa7bc26ff8cebaa18c4ccbed7`.
- 4H request SHA-256:
  `ef2af7dee0d3152222e64598bcc4fc8234d02f5bcc86e96018a001301bc2cb41`.
- 4H manager result SHA-256:
  `3747ac0a13b0a399b3dde86e278ec4593e602b6c0bb37b794911601e87eab8b5`.
- The manager froze 10 owning H slots. One earlier R5 send timed out before MCP
  submission (`r5-20260926T011203-422b82b48e`) and remains excluded.
- Step 4.7 revision r02 selected **C300 at 300 s**. The selected-C comparison
  uses the same frozen C300 calibration observations; result hashes remain
  `4ecbbd622113c843e7542b2eb67678fd7bf3daf0c51229dfb10c7acf06adbee5`
  and `51c4a3dadf977f9fab8601ae0e145e283020222929b0584cc4be1cc978dbdfce`.

## P4-A3 reanalysis: what changed

All 10 owning H trials and all 10 frozen C300 calibration trials were re-analyzed
with the corrected wait-node matcher.

- **H outcome classifications are unchanged.** Bounded H remains 0/9 correct,
  0/9 same-prompt, 9/9 budget-exhaustion handoffs, zero premature handoffs,
  zero interruptions and nine continuations. H R12 remains incorrect and
  premature because its required exhaustion-marked tool result is still absent.
- Three H internal oracle diagnostics become more precise: R5 repeats 1 and 3
  and R6 repeat 1 now match a positive repeated wait and report
  `wait_result state='running'` instead of an unmatched `None` state. This
  does not change any H correctness, same-prompt, handoff, provenance or
  continuation classification.
- **Selected C300 changes materially:** bounded same-prompt completion changes
  from 7/9 to **9/9**, premature handoffs from 2/9 to **0/9**, and manual
  continuations from 2 to **0**. C300 R12 correctness changes from false to
  **true** while remaining the expected budget-exhaustion handoff.
- The raw observations, run requests, result hashes, lane identities and routing
  evidence are unchanged; only analyzer interpretation changes.

## Evidence integrity and routing

The 4H manager rows contain `routing=null`. Retained-log recovery already froze
every owning H run id exactly once in the H server log, zero times in A/B/C300
server logs, and zero times in the production `binnacle-mcp` journal. The same
recovery for the C300 calibration freezes 0/10 calibration routing misses.

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
interruptions**. Every bounded slot requires one continuation. Provenance remains
`budget_exhaustion` for all nine bounded trials.

## R12 budget-exhaustion diagnostic

H R12 replied with the requested textual handoff:
`BUDGET_EXHAUSTED job_id=9e04baef17a8 state=running pending=dependency resume=job_status`.
Its sole `job_status` call requested 50 s and was bounded by H to an effective
10 s. It returned `state=running`, `blocking_remaining_s=0.0`, but
`blocking_budget_exhausted=false`. No second same-turn/job call observed the
historical guard's exhausted result. The corrected analyzer therefore still
records **budget-exhaustion handoff=false**, **premature handoff=true**, and
**correctness=false**. R12 provenance remains unclassified.

## Comparison with selected C300

Step 4.7 revision r02 selected C300 at 300 s, so C300 is now the direct
plan-required comparison basis.

| Scenario | H median wall s | C300 median wall s | H same-prompt | C300 same-prompt |
| --- | ---: | ---: | ---: | ---: |
| R5 | 46.965 | 40.268 | 0/3 | 3/3 |
| R6 | 66.207 | 108.399 | 0/3 | 3/3 |
| R7 | 77.226 | 158.269 | 0/3 | 3/3 |

Over all nine bounded trials, H's raw median wall time remains 62.556 s versus
108.399 s for selected C300, a raw H/C300 ratio of 0.57709. That remains **not**
a successful-completion speedup: all nine H trials hand off after exhausting the
historical 10 s blocking budget, while corrected C300 completes **9/9** in the
same prompt. H requires nine total continuations versus **zero** for C300.

For R12, H returns after 34.147 s but remains premature/incorrect because the
explicit exhaustion signature is absent. C300 runs 347.819 s and, under P4-A3,
is **correct**, records the expected budget-exhaustion handoff, and is not
premature.

## Conclusion

P4-A3 leaves the historical H policy's user-visible behavior unchanged: its
10-second one-shot budget systematically converts the targeted bounded waits into
continuation handoffs rather than same-prompt completion. The corrected analyzer
strengthens the selected-C comparison: C300 is 9/9 same-prompt with zero bounded
continuations, and its R12 exhaustion case is valid.

H remains diagnostic and cannot revise the C gate matrix or Step 4.12 verdict.
Evidence integrity remains clean after the frozen routing recovery. Step 4.13 has
not closed Phase 4 and `handoff` is still null, so there is no Phase-4 handoff
to append; the updated comparator hashes are frozen in canonical progress.
