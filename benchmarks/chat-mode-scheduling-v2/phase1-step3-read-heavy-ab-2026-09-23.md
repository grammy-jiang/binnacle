# Chat mode scheduling v2 — Phase 1 Step 1.3 read-heavy pilot

Status: **POSITIVE PERFORMANCE SIGNAL; FINAL TARGETS NOT YET MET**
Date: 2026-09-23 (Australia/Sydney)

## Canonical sample rule

The primary sample uses the first **submitted** trial for each planned A/B slot.

- A failure before Enter may retry the same slot.
- Once chat timing shows the message was submitted, that outcome stays in the
  sample even if it times out.
- Later successful reruns do not replace submitted failures.
- Extra reruns after all planned slots are filled are diagnostic only.

This rule prevents retry/survivor bias.

## R1 — search then six independent reads

Three pairs, all correct and same-prompt complete.

| Arm | Median wall | Median peak | Median overlap | Mean overlap |
| --- | ---: | ---: | ---: | ---: |
| A | 40.693 s | 3 | 50.0% | 33.3% |
| B | 31.244 s | 3 | 50.0% | 55.6% |

B median wall time was **23.2% lower**. B was faster in all 3/3 pairs.
Median paired B/A wall ratio was **0.785**.

Median MCP result tokens were 1275 for A and 1261 for B, so token-result cost
was essentially unchanged.

## R2 — ten known independent reads

The first planned B slot was a real submitted timeout:

- Enter was recorded;
- wall time reached 110.339 s;
- no conversation appeared;
- no MCP call reached the fixture.

It remains in the primary sample.

| Arm | Same-prompt | Interruptions | Median wall | Completed median peak | Completed median overlap |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 3/3 | 0/3 | 36.197 s | 3 | 50.0% |
| B | 2/3 | 1/3 | 27.364 s | 3.5 | 55.0% |

Including the timeout, B median wall time was **24.4% lower** because the other
two B trials were fast (27.364 s and 23.605 s). B was faster in 2/3 pairs.
Median paired B/A ratio was **0.903**.

Completed-only R2 is diagnostic only: the two completed B trials have a median
around 25.5 s, about 29.6% below A. The timeout is not removed from the primary
result.

## Combined read-heavy pilot

Across the six planned pairs:

- A same-prompt completion: **6/6 = 100%**
- B same-prompt completion: **5/6 = 83.3%**
- A interruptions: **0/6**
- B interruptions: **1/6**
- B faster pairs: **5/6**
- A median wall: **38.445 s**
- B median wall: **29.556 s**
- median wall improvement: **23.1%**
- median paired B/A ratio: **0.844**
- paired-median improvement: **15.6%**

The design's read-heavy target is >=30% median improvement, so this pilot does
**not** meet that target. The same-prompt target is >=95%; B also does not meet
that target because of one submitted timeout.

## Interpretation

The performance signal is positive, especially for R1 and completed R2 trials,
and is consistent with the scheduler mechanism seen in Step 1.2. However, the
effect is below the 30% read-heavy target and reliability is not yet acceptable
in this small sample.

The timeout happened before any MCP call, so it is not evidence that the B
instruction broke Binnacle scheduling. It is still a real user-visible failure
and is therefore retained.

The appropriate conclusion is:

> Continue to Step 1.4, but carry a reliability warning. Do not claim that the
> v2 instruction has met its performance or UX acceptance gates.

## Validity / environment

All 11 completed canonical conversations used `gpt-5-6-thinking`.

- 10 explicitly recorded `thinking_effort=max`.
- 1 successful R2/B conversation omitted the thinking-effort field throughout;
  no alternate model or effort was observed.

Host evidence showed:

- no Raspberry Pi throttling in captured trials;
- CPU temperature roughly 48–57.3 C;
- load-1 approximately 0.15–3.30.

## Infrastructure observations

Transient ChatGPT terminal/browser failures occurred during the pilot.

The harness now retries chat submission up to three times **only before**
submission evidence exists. Once chat timing proves Enter occurred, it never
auto-retries that trial.

Project instruction operations and exact-UUID chat cleanup already use bounded
retries. Retries never broaden selectors or replace submitted failures.

## Step 1.3 result

**COMPLETE.** Performance signal is positive, but acceptance targets are not
yet met. Step 1.4 was not started here.
