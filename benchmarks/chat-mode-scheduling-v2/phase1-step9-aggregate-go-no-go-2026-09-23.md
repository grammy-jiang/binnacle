# Chat mode scheduling v2 — Phase 1 Step 1.9 aggregate go/no-go

Status: **COMPLETE — CONDITIONAL GO TO PHASE 2; NO-GO FOR MERGE/DEPLOY**
Date: 2026-09-23 (Australia/Sydney)

## Executive decision

Phase 1 provides enough evidence to continue to **Phase 2 as a non-production
experiment**, but it does **not** justify merging or deploying scheduling v2.

The distinction matters. The Phase-1 progression rule says to stop if B does not
improve the macro suite, because a server guard cannot repair poor model
scheduling. B does show real scheduling improvement:

- canonical macro median wall time is **8.1% lower** than A;
- paired-median B/A is **0.917**, an
  **8.3%** paired-median improvement;
- B is faster in **14/24** macro pairs;
- required manual continuation prompts fall from **1 to 0**;
- premature handoffs fall from **1 to 0**;
- completed read-heavy trials increase median eligible overlap from
  **40.0% to 55.6%** and median read-only peak from
  **2 to 3**;
- R7 completed trials reduce median physical tool calls from
  **8 to 6**.

That is sufficient to reject the Phase-1 stop condition "poor model scheduling".
It is **not** sufficient to accept the production proposal.

## Phase-1 sample

The aggregate uses the frozen canonical samples from Steps 1.3–1.8:

```text
R1 R2 R3 R5 R7 R8 R9 R11
24 A trials + 24 B trials
24 paired comparisons
```

M1/M2/M3 from Step 1.2 remain mechanism checks and are not included in the
macro UX score. R4/R6/R10/R12 were not executed/scored in this instruction-only
Phase-1 sequence and therefore are not silently imputed into the aggregate.

## Overall macro result

| Metric | A | B |
| --- | ---: | ---: |
| Canonical trials | 24 | 24 |
| Correct | 22/24 (91.7%) | 18/24 (75.0%) |
| Same-prompt | 21/24 (87.5%) | 18/24 (75.0%) |
| Interruptions | 2/24 (8.3%) | 6/24 (25.0%) |
| Premature handoffs | 1 | 0 |
| Manual continuations required | 1 | 0 |
| Median wall | 49.816 s | 45.789 s |
| Completed-only median wall | 47.992 s | 41.830 s |
| Completed median tool calls | 8 | 7 |
| Completed median MCP-result tokens | 1275 | 1249 |

The direct canonical median improves by **8.1%**, below the
>=20% final target. The median paired ratio improves by
**8.3%**.

A deterministic 100,000-resample paired bootstrap gives a 95% interval for the
median B/A ratio of approximately **[0.756, 1.133]**.
The upper bound exceeds 1.00, so Phase 1 does not establish a statistically
robust non-regression result under the confirmatory criterion.

## Per-scenario result

| Scenario | A median | B median | B wall change | Paired B/A | A same-prompt | B same-prompt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R1 | 40.693 s | 31.244 s | +23.2% | 0.785 | 3/3 | 3/3 |
| R2 | 36.197 s | 27.364 s | +24.4% | 0.903 | 3/3 | 2/3 |
| R3 | 54.137 s | 61.653 s | -13.9% | 1.268 | 2/3 | 2/3 |
| R5 | 51.023 s | 45.411 s | +11.0% | 0.890 | 2/3 | 2/3 |
| R7 | 210.746 s | 159.423 s | +24.4% | 0.756 | 2/3 | 2/3 |
| R8 | 42.896 s | 36.934 s | +13.9% | 0.696 | 3/3 | 3/3 |
| R9 | 62.198 s | 57.862 s | +7.0% | 1.042 | 3/3 | 2/3 |
| R11 | 39.871 s | 43.889 s | -10.1% | 1.101 | 3/3 | 2/3 |

The strongest positive scenarios are R1, R7 and R8. R3 is a clear regression:
its B median is 13.9% slower and same-prompt completion does not improve. R11 is
also about 10.1% slower at the canonical median and loses one trial to timeout.
R9 has a modest arm-level wall improvement but a slightly regressive paired
median because of pair ordering and a submitted timeout.

## Category result

### Read-heavy: R1/R2/R11

- A median: **39.871 s**
- B median: **33.020 s**
- direct improvement: **17.2%**
- paired-median improvement: **9.5%**
- B same-prompt: **7/9**

This is a useful positive scheduling signal, but it misses the >=30% read-heavy
target. On completed read-heavy trials, B increases median eligible overlap from
40.0% to 55.6%; that remains below the >=80% target.

### Executed long-job subset: R3/R5/R7

The raw category median is distorted upward by submitted timeouts, so both raw
and pair-normalized views are retained:

- direct category median: A **67.930 s** vs B **110.700 s** — B is **63.0% slower**;
- paired-median improvement: **11.0%**;
- B faster in **5/9** pairs;
- R7 alone meets the >=20% long-barrier performance target at 24.4% faster.

The mixed long-job story is therefore positive in mechanism but not uniformly
positive in UX/performance.

### Development/recovery: R8/R9

- direct median improvement: **17.1%**;
- paired-median improvement: **1.4%**;
- B same-prompt: **5/6**.

R8 is strongly positive; R9 is mixed because one submitted B timeout dominates
the reliability result.

## Reliability is the hard blocker

Across the 24 macro trials per arm:

- A same-prompt completion: **87.5%**;
- B same-prompt completion: **75.0%**;
- change: **-12.5 percentage points**;
- A interruption rate: **8.3%**;
- B interruption rate: **25.0%**;
- interruption regression: **+16.7 percentage points**.

This fails both the >=95% same-prompt target and the <=2-point interruption
regression allowance. The failures observed in Steps 1.3–1.8 repeatedly include
submitted ChatGPT/browser/turn timeouts; some happen before useful MCP work starts.
A Binnacle blocking-wall guard cannot directly repair that pre-MCP/platform
failure mode.

Therefore reliability must remain a separate hard blocker rather than being
hidden by completed-only performance statistics.

## Scheduling and efficiency

Step 1.2 passed its mechanism gates. Across completed read-heavy macro trials,
median eligible overlap rises from 40.0% to
55.6% and weighted overlap rises from
28.0% to 58.9%.
Median read-only peak rises from 2 to
3. Macro avoidable-idle p90 is 0 seconds
for both arms.

Among same-prompt-complete macro trials, median MCP-result tokens change from
1275 to
1249, while median tool calls change from
8 to 7.
This is directionally efficient rather than a token/call regression, although
completed-only comparisons are diagnostic because the completion counts differ.

## Gate matrix

| Gate | Target | Phase-1 B observation | Result |
| --- | --- | --- | --- |
| Correctness | 100% deterministic | 18/24 canonical | **FAIL** |
| Same-prompt | >=95% | 75.0% | **FAIL** |
| Manual continuation median/p90 | 0 / 0 | 0 / 0 | **PASS** |
| Overall median wall | >=20% faster | 8.1% faster | **FAIL** |
| Read-heavy median | >=30% faster | 17.2% faster | **FAIL** |
| Eligible read overlap | >=80% | 55.6% median | **FAIL** |
| Premature handoff | 0 | 0 | **PASS** |
| Interruption regression | <=+2 pp | +16.7 pp | **FAIL** |
| Paired bootstrap upper bound | <1.00 | 1.133 | **FAIL** |

These are the full-proposal acceptance gates, shown here diagnostically against
B. Phase 2 does not inherit a waiver from any Phase-1 pass.

## Go/no-go

**GO: Phase 2 blocking-wall-guard implementation may proceed on the design
branch as a non-production experiment.**

The reason is narrow: the Phase-1 progression gate is about whether model
scheduling responds usefully to the v2 instructions. It does. B has a positive
macro point estimate, removes the only observed premature continuation handoff,
increases read concurrency, and reduces status/tool-call burden on the repeated
long barrier.

**NO-GO: do not merge or deploy B or the future C variant yet.** Phase 1 misses
most of the full acceptance gates, especially reliability. The final production
decision remains reserved for Phase 4 after C and the selected blocking budget
are measured against A.

Before Phase 4, timeout provenance must be explicit enough to separate at least:

1. pre-MCP/submission failure;
2. active-turn/browser-stream timeout;
3. MCP work completed but browser settling/timing timed out;
4. genuine Binnacle dependency-wait exhaustion.

This classification should improve evidence quality; it must not be used to
remove submitted failures from the canonical UX sample.

## Next checkpoint

Phase 1 is complete. The next planned work is **Phase 2 — cumulative
blocking-wall guard**, followed by Phase 3 offline replay of 120/300/600-second
candidates. Production remains unchanged until the later full live A/B/C gate.
