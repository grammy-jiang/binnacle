# R2 model selection, explicit effort and local-agent handoff

## Core requirement

The original R2 run is pinned to docs SHA cc386613a20f14cd466f19d0fbd3e38ec6ce9927. The [R1 evidence handoff](R1-EVIDENCE-HANDOFF.md) was appended as retrospective explanatory material; no worker may switch to a newer plan SHA without a new sealed run. Current worker statuses are maintained separately in [R2-RESULTS.md](R2-RESULTS.md).

The user authorized local Codex to take over coding/programmatic investigation when Claude Code is not available. Assign only the frozen model and reasoning effort for each lane, and pass those values explicitly to each agent. Do not rely on ~/.codex/config.toml defaults or hidden profile. Runtime proof from the agent's native turn context is mandatory. Launch flags alone do not prove a selector was effective.

| Lane | Difficulty | Explicit Codex model | Effort | Why |
| --- | --- | --- | --- | --- |
| R2-0 run freeze | Routine/deterministic | gpt-6-sol | medium | Hash/provenance, resource admission, fixture generation |
| R2-A connection | Moderate app & tunnel semantics | gpt-6-sol | medium | Supported local connector/transport tests; escalate with explicit new plan only if complex API uncertainty blocks |
| R2-B identity | Critical security | gpt-6-astra | xhigh | Authorization provenance, replay/spoofing, isolation invariants |
| R2-C receipt | Critical distributed semantics | gpt-6-astra | xhigh | Client-delivery proof, pagination, retries, races, durable state |
| R2-D transport & benchmark | Complex integration | gpt-6-astra | high | Native MCP compatibility, latency attribution, statistical checks |
| R2-E0 script preparation | Moderate deterministic | gpt-6-sol | medium | Freeze A/B trial plan, no ChatGPT GUI actions |
| R2-E1/E2 subject | True ChatGPT Chat only | GPT-6 | Medium | Hold the model/effort fixed for matched behavioral trials |
| R2-F synthesis | Supervisor in this chat | Not an executing local model | N/A | Read-only independent audit and decision |

R2-E may use an operator through a supported UI only if the actual operator surface and model/effort can be observed. The installed Pi chatgpt binary resolved to codex-launcher in R1; it does not prove traditional ChatGPT Chat. A Codex Desktop result cannot be recorded as a Chat mode result.

## Concrete launch pattern

Use Codex CLI 0.162.1 or explicitly recheck flags at launch (older run used this CLI). Its exec subcommand did **not** accept -a never. Use the supported configuration overrides:

~~~bash
# Example for lane R2-B; substitute only the explicit frozen values
codex exec \
  -m gpt-6-astra \
  -c 'model_reasoning_effort="xhigh"' \
  -c 'approval_policy="never"' \
  -s workspace-write \
  -C "$WORKER_WORKTREE" \
  --add-dir "$WORKER_RESULT_DIR" \
  --json \
  -o "$WORKER_RESULT_DIR/agent-last-message.txt" \
  - < "$LANE_HANDOFF_FILE"
~~~

For R2-A or R2-0 replace with gpt-6-sol/medium; for R2-C gpt-6-astra/xhigh; for R2-D gpt-6-astra/high. Do not use danger-full-access, bypass approval, ignore safety or silent model fallback. A provider/model refusal becomes an explicit BLOCKED report. Do not create subagents or share a single writable worktree.

The S0/dispatcher must bind the launch command to the exact input packet and record process ID, session ID, requested model/effort, runtime-observed effective model/effort, time, exit status and evidence path. See source run-manifest and per-lane JSON Schema.

## Input packet and receipt handshake

Every agent receives a frozen inputs/LANE.input.json, the R2 worker manifest/step contract, named reference artifacts and its exclusive writable directory. Its **first durable output** is model-selection.json:

| Field | Format | Meaning |
| --- | --- | --- |
| requested_model, requested_effort | strings | Exactly match packet |
| effective_model, effective_effort | strings or null | From authentic Codex turn_context/collaboration_mode or Chat UI |
| verification | VERIFIED, UNVERIFIED or UNAVAILABLE | If not VERIFIED, worker-level positive PASS not allowed |
| proof_ref | evidence-index-relative file path or null | Redacted native session metadata |
| fallback_used | boolean | Must be false |
| session_ref | opaque run-scoped ID | Prevent duplicates and link later results |
| observed_at | RFC3339 time | Provenance |

No private auth files, cookies, raw account identifiers, or original source conversation content are copied into reports.

## Handoff prompts

Ready-to-send templates for [R2-0](prompts/R2-0.md), [A](prompts/A.md), [B](prompts/B.md), [C](prompts/C.md), [D](prompts/D.md), [E0](prompts/E0.md). Each prompt names its exact output files and true authority restrictions. The dispatcher must fill RUN_ROOT, exact SOURCE_SHA, R2_DOCS_SHA and R2_FIXTURE_SHA. Do not send a mutable branch name as the only source identity.

## Isolation, concurrency, completion

- Four CLI workers start concurrently only after R2-0 establishes real SHA values and ports/reservations. A worker's success must not cancel other lanes.
- No worker installs a new ChatGPT plugin or connects a new account automatically; any such step must be completed through the authorized user/plugin UI flow.
- One operator exclusively handles real Chat UI; W2/C/D are not allowed to drive ChatGPT sessions.
- Each worker emits a terminal results.json, even when BLOCKED; do not rely only on process exit code or assistant prose.
- The Supervisor validates packet SHA, native model/effort selector proof, raw evidence and gaps, then reports. It must not implement worker fixes itself or change the production server.
- A plan-only / feasibility-proof phase does not license a source PR, merge or deployment.
