# Chat mode scheduling v2 — Phase 1 Step 1.2 scheduler micro A/B

Status: **MECHANISM PASS; PERFORMANCE INCONCLUSIVE**
Date: 2026-09-23 (Australia/Sydney)

## Scope

Step 1.2 is a mechanism check, not a statistical performance test. Each arm was
run once for M1/M2/M3 after the harness was hardened against transient ChatGPT
terminal-session authentication failures.

The paired order was:

~~~text
M1: A -> B
M2: B -> A
M3: A -> B
~~~

## Valid trial results

| Scenario | Arm | Wall s | Peak read-only | Overlap | Avoidable idle s | Correct | Same prompt |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| M1 | A | 15.637 | 1 | 0/3 (0.0%) | 0.000 | yes | yes |
| M1 | B | 19.381 | 1 | 0/3 (0.0%) | 0.000 | yes | yes |
| M2 | A | 23.232 | 2 | 2/8 (25.0%) | 0.000 | yes | yes |
| M2 | B | 24.514 | 4 | 4/8 (50.0%) | 0.000 | yes | yes |
| M3 | A | 24.446 | 3 | 5/6 (83.3%) | 0.230 | yes | yes |
| M3 | B | 27.836 | 3 | 4/6 (66.7%) | 0.336 | yes | yes |

Every valid trial had:

~~~text
interrupted                 false
premature_handoff           false
manual_continuations        0
duplicate_calls             0
tool_errors                 0
~~~

Machine-readable summary:
"benchmarks/chat-mode-scheduling-v2/phase1-step2-micro-ab-2026-09-23.json".

## Mechanism interpretation

### M1 — three very fast reads

Both arms were serial in this sample:

~~~text
A: peak 1, overlap 0/3
B: peak 1, overlap 0/3
~~~

M1 is too short/noisy to be a decisive concurrency test. The new instruction
did not force unnecessary calls or correctness regressions.

### M2 — eight known independent reads

B produced a materially wider observed fan-out:

~~~text
A: peak 2, overlap 2/8 = 25%
B: peak 4, overlap 4/8 = 50%
~~~

This is positive mechanism evidence for the instruction's "submit all
currently-known independent reads" rule.

### M3 — slow status plus five fast reads

The final paired M3 control used a **300-second** prelaunched dummy job so the
five-second status call could not be accidentally satisfied during variable
browser/Project startup. The dummy is stopped during fixture cleanup.

Both arms passed the hard sliding-refill relation:

> At least one later read started while the slow job_status(wait=5) remained
> unresolved.

Observed:

~~~text
A: peak 3, overlap 5/6 = 83.3%, blocking 5.001s, avoidable idle 0.230s
B: peak 3, overlap 4/6 = 66.7%, blocking 5.000s, avoidable idle 0.336s
~~~

B therefore **preserves** sliding refill, but this single trial does not show an
M3 concurrency improvement.

## Performance interpretation

The one-shot wall times were:

~~~text
M1: A 15.637s, B 19.381s
M2: A 23.232s, B 24.514s
M3: A 24.446s, B 27.836s
~~~

B was not faster in these single samples. Step 1.2 therefore makes **no
performance claim**. Browser/model/network variance dominates micro wall time,
and the Phase-1 plan intentionally reserves performance conclusions for
repeated macro trials.

The B/A wall-time ratios for these single samples were approximately 1.239,
1.055 and 1.139 respectively. They are recorded for transparency, not treated
as acceptance statistics.

## Invalid/excluded attempts and fixes

Three attempts are explicitly excluded from A/B results:

1. "m1-20260923T145220-2d166c0ea2": the ChatGPT/MCP workload completed, but
   exact chat cleanup hit a transient terminal-session authentication failure.
2. "m3-20260923T150618-dbf6089189": old 30-second control fixture; valid by
   itself but excluded after the fixture definition changed.
3. "m3-20260923T150919-46d496e895": invalid M3 control — the 30-second dummy job
   exited about eight seconds before job_status(wait=5) started.

Hardening completed during Step 1.2:

- Project get-instructions / set-instructions now have bounded outer retries
  around the existing session-level retries;
- exact test-chat deletion has bounded outer retries;
- M3 slow control duration changed from 30s to 300s and is stopped during
  fixture cleanup;
- analyzer blocking intervals now use the same rounded timestamp basis as tool
  intervals, fixing a real millisecond/float boundary failure.

## Step 1.2 decision

**PASS for scheduler mechanism.**

Reasons:

- all six valid A/B trials are correct;
- all six complete in one prompt;
- no interruption, duplicate call, or tool error occurred;
- B preserves M3 sliding refill;
- B increases observed M2 fan-out from peak 2 to peak 4.

**Performance remains inconclusive.** The data is intentionally insufficient
for a speed claim.

The next planned step is Step 1.3, repeated read-heavy macro A/B on R1 and R2.
Step 1.3 was not started here.
