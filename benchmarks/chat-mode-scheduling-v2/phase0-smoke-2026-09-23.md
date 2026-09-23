# Chat mode scheduling v2 — Phase 0 end-to-end smoke

Status: PASS
Date: 2026-09-23 (Australia/Sydney)
Scenario: M1 / Arm A
Run id: `m1-20260923T124850-79ad48cbc1`

## Purpose

Step 0.5 validates the complete Phase-0 benchmark path with one short real
ChatGPT Project trial. It is a plumbing/safety smoke, not a performance
acceptance result.

The required path was:

```text
manifest
-> disposable fixture
-> exact Arm-A Project state
-> real ChatGPT Project chat
-> real Raspberry Pi MCP calls
-> frozen journal
-> exact chat backup/delete
-> normalized trace
-> metrics/oracle
-> fixture cleanup
-> production invariant
```

Every stage passed.

## Chat/runtime evidence

The frozen conversation reported:

```text
model_slug      = gpt-5-6-thinking
resolved_model  = gpt-5-6-thinking
thinking_effort = max
is_complete     = true
status          = finished_successfully
```

The chat timing evidence was:

```text
status = complete
wall_s = 17.956
```

`wall_s` is Enter-to-settled-reply time and excludes fixture/setup/cleanup
overhead.

## Real MCP evidence

The trial produced exactly three `read_file` calls from
`client=openai-mcp`, all under one base turn:

```text
turn = b75eec04-b71a-45a5-b1cb-ea68a8ca4e14

read_1 -> f1.txt
read_2 -> f2.txt
read_3 -> f3.txt
```

The normalized intervals were approximately:

```text
read_1  9.997 -> 9.999 s
read_2 10.224 -> 10.237 s
read_3 10.232 -> 10.234 s
```

This smoke therefore observed peak read-only in-flight = 2 and eligible overlap
ratio = 2/3. Those are Arm-A baseline observations only; Step 0.5 has no
performance pass/fail threshold beyond correct end-to-end measurement.

## Metrics

```text
correctness_passed              true
same_prompt_completion          true
manual_continuations_required   0
premature_handoff               false
budget_exhaustion_handoff       false
interrupted                     false
tool_calls                      3
tool_errors                     0
duplicate_calls                 0
redundant_exact_calls           0
job_status_calls                0
blocking_wall_s                 0.0
avoidable_idle_wall_s           0.0
read_only_peak_inflight         2
eligible_read_only_calls        3
overlapped_eligible_calls       2
eligible_overlap_ratio          0.666667
tool_result_tokens              387
tool_result_bytes               975
wall_s                          17.956
```

All deterministic scenario oracles passed.

## Evidence artifacts

The run state directory contains:

```text
chat-timing.json
chat-url.txt
conversation.json
fixture-final.json
journal.log
metrics.json
trace.json
trial.json
```

The analyzer was run twice against the same frozen evidence. Both
`trace.json` and `metrics.json` produced identical SHA-256 hashes on the
second and third replay:

```text
trace.json
7d7c9601338bfad7a9ac955b91c1cdeac8e03681118b66f4592a1bcc83ff0c7c

metrics.json
8b2cc21662c7bc1049189c2ce647e2c313bda256584a8e799981565718ce4ffa
```

Deterministic replay therefore passed.

## Cleanup and isolation

After the trial:

- exact benchmark Project instructions matched Arm A;
- tracked-test-chat ledger was empty;
- the test conversation had been backed up and deleted by exact UUID;
- the disposable fixture root was removed;
- fixture cleanup reported no errors;
- production Git HEAD remained `83862b0`;
- production working tree remained clean;
- `binnacle-mcp.service` remained `active/running`;
- the trial itself recorded `production_unchanged=true`.

## Phase-0 result

Phase 0 is complete.

The benchmark now has:

1. frozen live baseline;
2. machine-readable scenarios and dependency DAGs;
3. safe fixture/Project/chat lifecycle;
4. normalized metrics/analyzer with deterministic replay;
5. one successful real ChatGPT -> Raspberry Pi MCP end-to-end smoke.

Phase 1 may now begin with Step 1.1, the controlled A/B Project-instruction
switching validation. No Phase-1 test was started by this smoke.
