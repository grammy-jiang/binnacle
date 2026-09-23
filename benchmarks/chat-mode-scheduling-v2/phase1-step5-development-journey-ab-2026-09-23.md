# Chat mode scheduling v2 — Phase 1 Step 1.5 development journey A/B

Status: **COMPLETE; POSITIVE PERFORMANCE SIGNAL**
Date: 2026-09-23 (Australia/Sydney)

## Scope

R8 is a disposable development journey:

```text
inspect README/app/test
-> modify app.py
-> run focused test
-> inspect final app.py
-> reply DONE
```

Three A/B pairs were run with the first-submitted-slot inclusion rule.
All repository mutation remained inside the disposable Git fixture.

## Canonical results

| Arm | Correct | Same-prompt | Interruptions | Median wall | Median tool calls | Median MCP-result tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 3/3 | 3/3 | 0/3 | 42.896 s | 5 | 736 |
| B | 3/3 | 3/3 | 0/3 | 36.934 s | 5 | 727 |

B median wall time was **13.9% lower** than A.

Paired wall times:

```text
pair 1: A 67.692 s -> B 36.934 s   B/A 0.546
pair 2: A 42.896 s -> B 29.852 s   B/A 0.696
pair 3: A 35.095 s -> B 39.770 s   B/A 1.133
```

B was faster in 2/3 pairs. Median paired B/A ratio was **0.696**, equivalent
to a 30.4% paired-median improvement. With only three pairs, this is a
positive pilot signal rather than a statistical performance conclusion.

## Specification correction: physical batching

The first analyzer pass incorrectly marked four trials as failures. In every
case, the actual task was completed correctly: `app.py` contained the required
`AFTER-<nonce>` value, the focused test passed, the final source was read, and
the assistant replied `DONE`.

The issue was that the original R8 DAG required edit and focused test to be
two separate physical `run_command` calls. Several models instead executed:

```text
<edit app.py> && python test_app.py
```

in a single command. That behavior is explicitly allowed by the v2 Project
instruction, which recommends batching related shell work when dependency
order is preserved.

R8 now treats focused-test success as a correctness oracle:

> at least one `run_command` containing `test_app.py` must exit with code 0.

The dedicated physical `focused_test` DAG node was removed; `verify_app`
depends on the logical edit step, while the successful-test oracle proves the
test actually ran. Both separate-call and combined-call implementations are
accepted.

All six existing frozen conversations were replayed after this correction.
No R8 chat was rerun to improve the result.

## Correctness and safety

All six canonical trials satisfy:

```text
correctness_passed      true
same_prompt_completion  true
interrupted             false
premature_handoff       false
duplicate_calls         0
mutation_scope_ok       true
production_unchanged    true
```

The final Git fixture evidence confirms only `app.py` changed and every final
`app.py` contains the expected `AFTER-<nonce>` result.

## Host observations

Across 12 before/after host observations:

- Raspberry Pi throttling: none;
- CPU temperature: 44.6–51.8 C;
- load-1: approximately 0.47–1.25.

## Interpretation

Step 1.5 is the strongest instruction-only result so far for a realistic
development journey: B preserved 100% correctness and same-prompt completion
while showing lower median wall time and slightly lower MCP-result token cost.

The arm-level median improvement (13.9%) is below the final suite-wide 20%
performance target, while the paired-median signal is stronger at 30.4%.
Those numbers should not be generalized beyond this three-pair pilot.

## Step 1.5 result

**COMPLETE. POSITIVE SIGNAL.**

Step 1.6 was not started.
