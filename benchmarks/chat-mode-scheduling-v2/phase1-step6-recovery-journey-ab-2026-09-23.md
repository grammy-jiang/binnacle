# Chat mode scheduling v2 — Phase 1 Step 1.6 recovery journey A/B

Status: **COMPLETE; POSITIVE SIGNAL WITH RELIABILITY WARNING**
Date: 2026-09-23 (Australia/Sydney)

## Scope

R9 exercises a recovery journey:

```text
observe a failing focused test
-> inspect source and test
-> diagnose/fix
-> rerun focused test successfully
-> inspect final source
-> DONE
```

Three A/B pairs were run with the first-submitted-slot inclusion rule.

## Canonical results

| Arm | Correct | Same-prompt | Interruptions | Median wall | Completed median wall |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 3/3 | 3/3 | 0/3 | 62.198 s | 62.198 s |
| B | 2/3 | 2/3 | 1/3 | 57.862 s | 57.832 s |

B arm-level median wall was 7.0% lower, but paired results were mixed:

```text
pair 1: A 62.198 -> B 57.803 s   B/A 0.929
pair 2: A 55.542 -> B 57.862 s   B/A 1.042
pair 3: A 83.511 -> B 170.513 s  B/A 2.042 (submitted timeout)
```

Median paired B/A was 1.042, so the paired-median signal is 4.2% slower for B.
B was faster in only 1/3 pairs.

## Specification correction

The first analyzer pass marked the first five successful chats as failures.
The actual traces showed the required recovery outcome, but the old DAG forced
one exact physical order and exact `python3 test_math_utils.py` command.

Real agents legitimately varied the mechanics: they sometimes tried `pytest`
first, listed files before reading them, or used `python` rather than `python3`.

R9 now checks recovery semantics:

- a command containing `test_math_utils.py` fails;
- a later command containing `test_math_utils.py` succeeds;
- source and test are inspected;
- the final source is inspected;
- mutation stays inside the disposable fixture;
- final reply is `DONE`.

The new `command_failure_precedes_success` oracle enforces failure-before-success
without forcing a specific physical tool-call sequence. All existing frozen
evidence was replayed; no successful chat was rerun to improve the result.

## Reliability

The final B slot was a genuine submitted timeout at 170.513 s before any useful
MCP work reached the fixture. It remains in the canonical sample.

Therefore Step 1.6 does not meet the >=95% same-prompt target for B.

## Host observations

Across 12 before/after observations:

- Pi throttling: none;
- CPU temperature: 46.3–50.7 C;
- load-1: approximately 0.28–1.06.

## Step 1.6 result

**COMPLETE. POSITIVE COMPLETED-TRIAL SIGNAL, BUT RELIABILITY TARGET NOT MET.**

Step 1.7 begins immediately in the same execution round.
