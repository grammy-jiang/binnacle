# Chat mode scheduling v2 — Phase 1 Step 1.3 read-heavy pilot

Status: **GO — positive pilot, final performance target not yet met**
Date: 2026-09-23 (Australia/Sydney)

## Scope

Step 1.3 runs repeated read-heavy macro A/B:

- R1: search discovers six files, then inspect all six;
- R2: ten independent file paths are known at prompt time.

Each scenario has three paired A/B repetitions. Twelve valid trials are used in
the comparison.

Arm A is the frozen live sandbox instruction. Arm B is the proposed scheduling
instruction.

## User-experience and correctness result

All 12 valid trials had:

~~~text
correctness_passed             true
same_prompt_completion         true
interrupted                    false
premature_handoff              false
manual_continuations_required  0
duplicate_calls                0
tool_errors                    0
~~~

Therefore this pilot shows **no correctness or same-prompt UX regression** from
Arm B.

## R1 — discovery then six reads

Wall-time samples:

~~~text
Pair 1: A 42.491 s -> B 33.376 s   B/A 0.785
Pair 2: A 32.939 s -> B 31.244 s   B/A 0.949
Pair 3: A 40.693 s -> B 27.868 s   B/A 0.685
~~~

Summary:

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Median wall time | 40.693 s | 31.244 s |
| Mean wall time | 38.708 s | 30.829 s |
| Median peak read-only in-flight | 3 | 3 |
| Median eligible overlap ratio | 50% | 50% |
| Median tool-result tokens | 1275 | 1261 |
| Median tool calls | 7 | 7 |

Median paired B/A wall ratio = **0.785**, corresponding to a **21.45% paired
median speedup**.

R1 does not show a median concurrency-width difference, so the wall-time gain
cannot be attributed only to peak width. The result is still useful: B finished
the same dependency graph with the same call count and slightly fewer median
tool-result tokens.

## R2 — ten known independent reads

Wall-time samples:

~~~text
Pair 1: A 47.992 s -> B 25.926 s   B/A 0.540
Pair 2: A 36.197 s -> B 27.364 s   B/A 0.756
Pair 3: A 35.205 s -> B 32.416 s   B/A 0.921
~~~

Summary:

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Median wall time | 36.197 s | 27.364 s |
| Mean wall time | 39.798 s | 28.569 s |
| Median peak read-only in-flight | 3 | 4 |
| Median eligible overlap ratio | 50% | 60% |
| Median tool-result tokens | 1310 | 1320 |
| Median tool calls | 10 | 10 |

Median paired B/A wall ratio = **0.756**, corresponding to a **24.40% paired
median speedup**.

R2 also shows the expected scheduling mechanism improvement: median peak
read-only width increased from 3 to 4 and median eligible overlap rose from 50%
to 60%.

## Combined read-heavy view

Across all six paired comparisons:

| Metric | Arm A | Arm B |
| --- | ---: | ---: |
| Median wall time | 38.445 s | 29.556 s |
| Mean wall time | 39.253 s | 29.699 s |
| Median peak read-only in-flight | 3.0 | 3.5 |
| Median eligible overlap ratio | 50% | 55% |
| Median tool-result tokens | 1296.5 | 1305.0 |
| Median tool calls | 8.5 | 8.5 |

The median of the six paired B/A wall ratios is **0.771**, or a **22.93% paired
median speedup**.

The direct combined median wall-time reduction is about **23.1%**.

Median MCP result-token cost changed by only about **+0.7%**, well inside the
design's +5% ceiling. Tool-call count did not increase.

An exploratory paired bootstrap over these six pairs produced a 95% interval
for the median B/A ratio of approximately **[0.613, 0.935]**. This is positive
supporting evidence, but with only six pairs it is **not** treated as the later
confirmatory acceptance interval.

## Final target comparison

The design's later confirmatory target for read-heavy scenarios is:

~~~text
median wall time >= 30% faster than A
~~~

Step 1.3 did **not** reach that final target:

~~~text
R1 paired median speedup = 21.45%
R2 paired median speedup = 24.40%
combined paired median   = 22.93%
~~~

This is not a Step-1.3 stop condition because this phase is explicitly a pilot.
The important pilot questions were whether B creates a useful scheduling signal
without correctness/UX regression. It does.

The result is therefore:

> **GO to the next pilot step, while retaining the >=30% target for later
> confirmatory evaluation.**

## Infrastructure-invalid attempts

Three R2 attempts are excluded from performance and UX metrics because no valid
ChatGPT trial was created:

1. r2-20260923T154139-d85ce7fb3f (B): Enter timing existed, but no
   conversation URL, no R2 MCP calls, and no matching backend conversation was
   found.
2. r2-20260923T155245-4c0910b09f (B): failure before timing/URL/conversation
   creation.
3. r2-20260923T155720-eacac57cc2 (A): failure before timing/URL/conversation
   creation.

These are benchmark-browser infrastructure failures, not ChatGPT task failures.
They are retained for transparency rather than replaced silently.

R2 therefore needed nine harness attempts to obtain six valid trials. This
**33% invalid-attempt rate is a harness reliability concern**, not a product
performance metric.

Step 1.3 added one conservative hardening rule:

> send_project_chat may retry once only when **neither** a conversation URL nor
> timing evidence exists.

Once Enter timing or a conversation URL exists, the harness never
automatically resubmits because doing so could duplicate a real ChatGPT turn.

The rule is unit-tested. Its live failure-rate effect is not yet established
from enough post-change trials, so invalid-attempt accounting remains mandatory
for later steps.

## Additional specification correction

R1 originally required fixed_strings=true in the analyzer's DAG identity for
the discovery search_text call even though the prompt only required an exact
marker and the marker contains no regex metacharacters.

One valid B trial omitted that implementation flag while returning the correct
search results, six exact reads, and correct final answer. The manifest was
therefore relaxed so logical DAG identity depends on semantic path + pattern,
not that unnecessary implementation detail. The frozen trial then replayed
correctly; no chat was rerun or replaced.

## Host condition

Nine of the twelve valid trials were launched through batch runners that
captured pre/post load, temperature and throttling state. Every recorded
vcgencmd get_throttled value was:

~~~text
throttled=0x0
~~~

No thermal/voltage throttling was observed in recorded samples. The three
replacement trials do not have equivalent host snapshots and are retained as
pilot data, not confirmatory data.

## Step 1.3 decision

**PASS / GO.**

Evidence:

- 12/12 valid trials correct;
- 12/12 same-prompt completion;
- zero user continuations;
- zero interruptions;
- zero duplicate tool calls;
- B improved R1 paired median wall time by 21.45%;
- B improved R2 paired median wall time by 24.40%;
- R2 concurrency/overlap metrics moved in the expected direction;
- MCP result-token cost remained effectively flat.

Caveats:

- the later 30% read-heavy acceptance target is not yet met;
- sample size remains pilot-scale;
- browser harness pre-conversation reliability still needs observation after the
  new safe retry rule.

The next planned step is Step 1.4: R3 background-overlap and R5 short true
dependency-barrier pilot. Step 1.4 was not started here.
