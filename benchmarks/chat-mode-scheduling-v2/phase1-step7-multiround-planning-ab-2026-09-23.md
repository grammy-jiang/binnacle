# Chat mode scheduling v2 — Phase 1 Step 1.7 multi-round planning A/B

Status: **COMPLETE; MECHANISM POSITIVE, RELIABILITY TARGET NOT MET**
Date: 2026-09-23 (Australia/Sydney)

## Scope

R11 exercises two dependency-separated read/search waves:

```text
search wave 1
-> read five files
-> derive a marker from their fragments
-> search wave 2 with that marker
-> read four results
-> return four payload lines
```

Three A/B pairs were run with the first-submitted-slot inclusion rule.

## Canonical results

| Arm | Correct | Same-prompt | Interruptions | Median wall | Completed median wall | Completed peak | Completed overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 3/3 | 3/3 | 0/3 | 39.871 s | 39.871 s | 1 | 0.0% |
| B | 2/3 | 2/3 | 1/3 | 43.889 s | 38.455 s | 3 | 66.7% |

The completed B trials show a clear scheduler-mechanism change: the model
parallelized independent reads within each wave, while all three A trials were
fully serial at the MCP-call interval level.

Paired wall times:

```text
pair 1: A 53.764 -> B 150.322 s  B/A 2.796 (submitted timeout)
pair 2: A 39.871 -> B 43.889 s   B/A 1.101
pair 3: A 36.479 -> B 33.020 s   B/A 0.905
```

Canonical median and paired-median both put B about 10.1% slower because the
submitted timeout remains in the primary sample. B was faster in 1/3 pairs.

Completed-only B is diagnostic only: its two successful trials have a median
wall time of 38.455 s versus A's 39.871 s, while increasing median eligible
read overlap from 0% to 66.7%.

## Reliability

B slot 2 was a genuine submitted timeout at 150.322 seconds and is retained.
It did not complete the multi-round journey in one user prompt.

Therefore B same-prompt completion is 2/3 = 66.7%, below the >=95% target.

## Specification pre-flight

Before Step 1.7, `fixed_strings=true` was removed from the logical identity of
the two search nodes. The prompt requires searching for the derived marker but
does not require a specific search-tool implementation flag. This mirrors the
R1 correction from Step 1.3 and prevents a presentation/implementation detail
from becoming a correctness requirement.

## Token / call cost

Completed median physical tool calls were 11 for both arms.

Completed median MCP-result tokens:

```text
A 1982
B 2006.5
```

So the concurrency gain did not come from fewer calls or lower result volume.

## Host observations

Across 12 before/after observations:

- Pi throttling: none;
- CPU temperature: 46.3–50.7 C;
- load-1: approximately 0.34–0.66.

## Interpretation

Step 1.7 is strong evidence that the v2 instruction changes multi-round
scheduling in the intended direction once a turn reaches MCP: independent
read waves become substantially more concurrent.

However, canonical reliability remains the dominant problem. One submitted
timeout is enough to erase the small completed-only wall-time advantage and
push the primary B result into regression.

## Step 1.7 result

**COMPLETE. MECHANISM POSITIVE; PERFORMANCE/UX TARGETS NOT MET.**

Step 1.8 was not started.
