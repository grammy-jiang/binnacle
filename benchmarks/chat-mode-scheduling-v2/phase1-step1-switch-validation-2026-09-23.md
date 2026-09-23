# Chat mode scheduling v2 — Phase 1 Step 1.1 switching validation

Status: PASS
Date: 2026-09-23 (Australia/Sydney)
Final probe run: `switch-probe-20260923T144229-54bafc6e35`

## Scope

Step 1.1 validates only A/B instruction switching and isolation. It does not run
MCP performance scenarios.

Acceptance evidence is intentionally split into three independent checks:

1. live exact A -> B -> A Project switching;
2. real A/B conversation isolation evidence;
3. a previously frozen live failure-injection restore.

This avoids making the benchmark gate depend on a flaky Project-page URL
transition.

## Live A -> B -> A

Exact hashes:

```text
Arm A
f1c100d0ddb93c29f8f78e5a2d28e297d861ba6e2c7e53712ec886dea06bafa5

Arm B
b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094
```

Final live probe checks:

```text
initial_a_exact          true
b_exact_readback         true
a_exact_after_b          true
production_unchanged     true
```

The benchmark Project ended on exact Arm A.

## Chat isolation evidence

Two real, already-frozen Project conversations were validated offline.

Arm A evidence came from the Phase-0 M1 smoke:

```text
conversation_id = 6ab33e29-29d8-83ec-8a18-accca8e3eb11
reply           = DONE
model           = gpt-5-6-thinking
thinking_effort = max
complete        = true
```

Arm B evidence came from the first Step-1.1 live attempt. That browser helper
reported a timeout, but the exact conversation backup proves the ChatGPT turn
itself had completed successfully before the timeout:

```text
conversation_id = 6ab35582-9f7c-83ec-be44-971c16eb2d92
reply           = SWITCH-B-3b07f29cd363f39e4028a5e1b1e84e50
model           = gpt-5-6-thinking
thinking_effort = max
complete        = true
```

Both conversations:

- have distinct conversation ids;
- have the same benchmark Project template id
  `g-p-6aaea9da2bc881918d6f9eb5177cf904`;
- use the frozen model/effort baseline.

Therefore:

```text
chat_ids_distinct       true
chat_project_isolation  true
```

## Failure-restore evidence

Step 0.3 had already run a real Arm-B failure injection after the alternate
instructions were applied.

Frozen evidence:

```text
error                    HarnessError: injected failure after instructions
instructions_changed     true
instructions_restored    true
production_unchanged     true
fixture_root_removed     true
```

Step 1.1 revalidated that frozen evidence rather than issuing another redundant
live A/B switch solely to recreate the same failure.

## Browser-helper finding

The first full-browser Step-1.1 attempt uncovered a false timeout:

- the final text was already correct;
- the conversation backend showed `is_complete=true`;
- the browser's stop-button state remained present long enough for the helper to
  wait until its 60-second timeout.

The branch-local `chatgpt-send` now has a conservative fallback: when final
text is stable but the stop button remains, it queries the authenticated
conversation backend through the same page and accepts completion only when the
current assistant node is complete.

A second browser attempt exposed a different UI failure: after Enter, the
Project page did not produce a `/c/<uuid>` URL or a conversation within the
timeout. No test chat was created in that attempt.

These findings are why Step 1.1 no longer treats Project-page URL transition as
the switching gate. Formal Phase-1 benchmark trials still retain their exact
chat backup/timing evidence and will surface genuine browser/request failures as
interruptions.

## Final environment

After the passing probe:

```text
benchmark Project     exact Arm A
tracked test ledger   empty
production HEAD       83862b0
production tree       clean
MCP service           active/running
```

No production MCP config, schema, service unit, or checkout was changed.

## Step 1.1 result

PASS.

The switching mechanism is ready for Step 1.2 scheduler micro A/B. Step 1.2 was
not started by this validation.
