# Chat mode scheduling v2 benchmark manifests

These JSON files are the executable specification for the Chat-mode scheduling
v2 benchmark. The harness is implemented separately in Step 0.3; this directory
defines **what** each scenario means.

## Catalog

| ID | Phase 1 step | Expected | Max one-turn runtime | Purpose |
| --- | --- | ---: | ---: | --- |
| M1 | 1.2 | 12 s | 60 s | three independent reads |
| M2 | 1.2 | 18 s | 75 s | eight-read sliding-window fan-out |
| M3 | 1.2 | 20 s | 75 s | slow status plus slot refill |
| M4 | mechanism | 25 s | 90 s | dependent continuation barrier |
| M5 | mechanism | 30 s | 90 s | non-read-only serialization |
| M6 | mechanism | 45 s | 100 s | background job as Future handle |
| M7 | mechanism | 3 s | 20 s | direct local FastMCP control |
| R1 | 1.3 | 25 s | 90 s | discovery then six reads |
| R2 | 1.3 | 25 s | 90 s | ten known independent reads |
| R3 | 1.4 | 50 s | 110 s | background validation plus reads |
| R5 | 1.4 | 40 s | 90 s | short true dependency barrier |
| R8 | 1.5 | 65 s | 130 s | inspect/edit/test/verify |
| R9 | 1.6 | 80 s | 150 s | fail/diagnose/fix/retest |
| R11 | 1.7 | 50 s | 130 s | two read/search waves |
| R7 | 1.8 | 165 s | 230 s | two sequential long barriers |

No Phase-1 single Chat turn is allowed to exceed 240 seconds in the manifest
schema. The runner may use a slightly larger external timeout for browser/tool
overhead, but the scenario itself must stay inside this bound.

## Placeholder vocabulary

The Step 0.3 harness resolves only these placeholder forms:

- `{id}` — scenario id;
- `{run_id}` — unique trial id;
- `{nonce}` — unique unpredictable trial marker;
- `{root}` — disposable fixture root;
- `{job:name}` — prelaunched fixture job id;
- `{result:node.field}` — field from a completed DAG node result.

Fixture file contents use the same `{nonce}`, `{id}`, `{run_id}`, and
`{root}` substitutions.

## DAG meaning

A node is runnable when every id in `depends_on` has reached its logical
completion condition.

Node kinds:

- `tool` — an expected MCP tool action;
- `reasoning` — a model-side dependency transformation with no MCP call;
- `control` — harness-side control used only for mechanism checks.

For ordinary nodes, completion means one successful action. A `job_status`
node may set:

```json
{
  "allow_repeats": true,
  "completion_condition": "job_state=exited"
}
```

That means the DAG contains one **logical dependency barrier**, even if ChatGPT
needs more than one physical `job_status` call because each call is capped at
50 seconds. The analyzer must not misclassify those legitimate repeated waits
as duplicate logical work.

## Mutation safety

Every scenario sets `production_mutation_allowed=false`.

Any DAG containing `run_command` or `stop_job` must use a disposable fixture
with explicit `allowed_mutation_globs`. R8/R9 use disposable Git fixtures and stdlib-only focused test scripts so the
benchmark does not measure environment setup. None of the manifests permit
mutation of the production checkout.

The harness must enforce the manifest scope independently; the manifest is not
a security boundary by itself.

## Oracle semantics

`oracle.checks` contains deterministic correctness checks. Some
`event_relation` entries are marked `hard_gate=false`; these record current
product scheduler behavior but do not turn a future ChatGPT scheduler
improvement into a correctness failure.

Performance and user-experience metrics are evaluated by the A/B analyzer, not
by scenario correctness oracles.

Physical shell batching is allowed when it preserves logical dependencies.
For example, R8 accepts either a dedicated test command or a combined
edit-and-test command. Its `command_contains_exit_zero` oracle requires that at
least one `run_command` containing `test_app.py` exits successfully, so the
benchmark checks the required test outcome without forcing one physical call
per logical step.

## Validation

Run:

```bash
.venv/bin/python scripts/chat_scheduling_manifest.py
pytest -q tests/scripts/test_chat_scheduling_manifest.py
```

The validator checks the exact scenario catalog, phase mapping, DAG acyclicity,
tool access classes, mutation scope, repeat semantics, and one-turn runtime
bounds.
