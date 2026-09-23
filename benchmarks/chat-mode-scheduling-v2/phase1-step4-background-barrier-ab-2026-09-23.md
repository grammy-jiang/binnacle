# Chat mode scheduling v2 — Phase 1 Step 1.4 background/barrier pilot

Status: **MIXED RESULT; UX/PERFORMANCE TARGETS NOT MET**
Date: 2026-09-23 (Australia/Sydney)

## Scope

Step 1.4 covers R3 (30-second background validation plus eight useful reads)
and R5 (25-second true dependency barrier). Each scenario has three A/B pairs.
The canonical sample uses the first submitted trial per planned slot; only
pre-submit failures may retry.

## R3 — background validation plus useful reads

| Arm | Same-prompt | Interruptions | Premature | Median wall | Completed median wall | Completed median overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 2/3 | 0/3 | 1/3 | 54.137 s | 51.373 s | 43.8% |
| B | 2/3 | 1/3 | 0/3 | 61.653 s | 53.910 s | 50.0% |

The completed A/B trials all overlapped useful reads with the background
validation and later obtained its required result. Completed median blocking
wall was essentially unchanged: 14.508 s for A and 14.258 s for B.

One A trial ended normally without any MCP call and replied that the validation
command could not be started. It is retained as a real premature handoff.
One B trial was a submitted timeout at 130.498 seconds before any MCP call.

R3 median paired B/A wall ratio: **1.268**; B was faster in 1/3 pairs.

## R5 — true dependency barrier

The R5 trace exposed an analyzer bug: several real job_status calls used
`tail_lines=100` rather than the manifest's `tail_lines=20`. `tail_lines` is
presentation-only, so it has now been removed from logical DAG identity.
Frozen evidence was replayed; no chats were rerun for this correction.

| Arm | Same-prompt | Interruptions | Median wall | Completed median wall | Completed median blocking |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 2/3 | 1/3 | 51.023 s | 49.004 s | 23.522 s |
| B | 2/3 | 1/3 | 45.411 s | 45.106 s | 22.518 s |

Every completed R5 trial launched the job in the background, waited at the
true dependency barrier, observed `state=exited` / `exit_code=0`, and returned
the exact nonce. The interrupted A and B slots timed out after submission
before any MCP call.

R5 median paired B/A wall ratio: **0.890**; B was faster in 2/3 pairs.

## Combined result

```text
A same-prompt          4/6 = 66.7%
B same-prompt          4/6 = 66.7%
A interruptions        1/6
B interruptions        2/6
A premature handoffs   1/6
B premature handoffs   0/6
A median wall          52.580 s
B median wall          53.910 s
median wall change     B 2.5% slower
median paired B/A      1.079
paired-median change   B 7.9% slower
B faster pairs         3/6
```

This does not satisfy the mixed-long-job >=20% performance target, the >=95%
same-prompt target, or the interruption-rate target. Submitted interruptions
and the A premature handoff remain in the canonical sample.

## Interpretation

When a turn reaches MCP, the intended mechanics work: R3 overlaps background
work with reads, and R5 waits correctly at a true dependency barrier. But
instruction-only B does not improve Step 1.4 as a whole. Pre-MCP request
reliability remains material.

Across 24 captured host observations there was no Pi throttling; CPU
temperature was 50.1–55.1 C and load-1 about 0.26–1.41.

## Step 1.4 result

**COMPLETE. MIXED / TARGETS NOT MET.**

Step 1.5 begins immediately after this report in the same execution round.
