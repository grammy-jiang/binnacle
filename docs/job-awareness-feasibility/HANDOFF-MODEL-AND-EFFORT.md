# Model and effort handoff SOP (mandatory)

Status: handoff rules only; no worker has been launched.

The user explicitly requires the manager to instruct **each local agent to select the right model and reasoning effort from this plan**. It is not sufficient to rely on a global ~/.codex/config.toml or ~/.claude/settings.json default. The written plan, worker-input packet, CLI invocation, startup model-selection receipt and terminal results must agree.

## 1. Supervisor → S0 → worker exact handshake

1. Supervisor checks that the plan branch is approved, SOURCE_SHA and DOCS_SHA are fixed, and S0 is the only preparatory writer.
2. S0 runs with explicitly selected Codex CLI gpt-6-sol / medium. S0 issues each Wn.input.json with its exact model_request and, for W5, separate subject_request.
3. The supervisor checks each packet's SHA-256 against run-manifest.json before dispatch. It cannot silently change the model, effort, source SHA, fixture SHA or worker instructions.
4. **Before any actual Wn experiment**, the worker must read Wn.input.json and the frozen MODEL-AND-EFFORT.md, choose the **identical** model/effort explicitly, and record a startup model-selection.json receipt.
5. The worker must verify the provider/runtime's effective selection through structured session metadata, CLI result or supported UI selector evidence. Merely passing command-line flags is insufficient. If effective level cannot be proven, report UNVERIFIED; if unavailable, report UNAVAILABLE. Either prevents a positive worker-level PASS.
6. The worker persists its own evidence for this model selection; later results.json.executor.model must match model-selection.json.executor exactly. W5 has two independently verified selections, the Desktop operator and the ChatGPT Chat **test subject**.
7. The manager refuses any final PASS/GO if the plan, launch request, evidence and results disagree, or an unreported fallback occurred. A change requires an explicit *new assignment/run revision*, not a silent default.

## 2. Fixed assignment table

| Stage/worker | Runtime | Requested model | Effort | Launcher flags or supported UI |
| --- | --- | --- | --- | --- |
| S0 | Codex CLI | gpt-6-sol | medium | -m gpt-6-sol -c model_reasoning_effort="medium" |
| W1 | Codex CLI | gpt-6-astra | high | -m gpt-6-astra -c model_reasoning_effort="high" |
| W2 | Claude Code CLI | opus | high | --model opus --effort high |
| W3 | Codex CLI | gpt-6-astra | xhigh | -m gpt-6-astra -c model_reasoning_effort="xhigh" |
| W4 | Claude Code CLI | sonnet | medium | --model sonnet --effort medium |
| W5 operator | Desktop / Codex Desktop if supported | gpt-6-astra | high | Explicit verified Desktop selector, not CLI defaults |
| W5 test subject | Genuine ChatGPT Chat | GPT-6 | Medium | Explicit Chat model/effort UI selector, fixed across all A/B pairs |

The values above are **requested, not yet proven account entitlements**. At plan review the Pi installed Codex CLI 0.162.1 and Claude Code 2.1.293; both advertise explicit selection flags. The installed /usr/bin/chatgpt launcher resolves to codex-launcher; it has **not** been proven to operate the traditional ChatGPT Chat surface.

## 3. CLI launch templates (do not run until S0 has frozen packets)

The dispatcher's cwd is the worker's own isolated source worktree. Every command receives that worker's frozen input packet as part of the instructions and writes only its assigned results directory. These are **templates**, not successful launches.

~~~bash
# W1: protocol and middleware
codex exec -m gpt-6-astra -c 'model_reasoning_effort="high"' \
  -s workspace-write -a never -C "$W1_WORKTREE" --json - < "$W1_DISPATCH"

# W3: receipt and failure semantics
codex exec -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' \
  -s workspace-write -a never -C "$W3_WORKTREE" --json - < "$W3_DISPATCH"

# W2: authentication provenance and isolation
claude --model opus --effort high --permission-mode dontAsk \
  --no-chrome --disallowedTools WebSearch,WebFetch,Agent \
  --print --output-format json -p "$(cat "$W2_DISPATCH")"

# W4: measurement/benchmarks
claude --model sonnet --effort medium --permission-mode dontAsk \
  --no-chrome --disallowedTools WebSearch,WebFetch,Agent \
  --print --output-format json -p "$(cat "$W4_DISPATCH")"
~~~

For S0 use gpt-6-sol/medium as in MODEL-AND-EFFORT.md. Do **not** use danger-full-access, bypass hooks, hidden fallback, browser credential extraction or production connector access. CLI syntax is verified against the installed version at kickoff, then recorded in startup evidence.

## 4. Model-selection.json output, before case execution

Required output file: RUN_ROOT/Wn/model-selection.json; validate with schemas/model-selection.schema.json.

| Field | Type | Content |
| --- | --- | --- |
| schema, run_id, worker, recorded_at | versioned strings + RFC3339 | Model handoff identity |
| executor | object using common model schema | requested_model/effort, effective_model/effort, verification, match booleans, no fallback |
| subject | null for W1–W4; separate model object for W5 | Actual ChatGPT subject, **not** Desktop operator |
| selection_command | string | Redacted launch flags or supported selector action; never tokens |
| observed_selector_evidence_refs | list of paths | Captured CLI output/UI proof, included in evidence-index |
| notes | list of strings | Unsupported/ambiguous selector details |

Every model object includes:

- requested_model and requested_effort: exact values from immutable Wn.input.json;
- effective_model/effective_effort: nullable observed values; aliases may resolve to canonical IDs if backed by evidence;
- verification: VERIFIED, UNVERIFIED or UNAVAILABLE;
- model_match_verified and effort_match_verified: separate booleans; neither should be guessed true;
- verification_evidence_ref: a path to actual evidence, or null;
- fallback_used: MUST be false for a PASS.

A value of UNVERIFIED/UNAVAILABLE means the worker can still produce a complete BLOCKED/INCONCLUSIVE report. It must **not** fill default model names and claim to have completed the experimental case. W5 cannot run paired Chat-mode trials until the subject model and effort are independently pinned.

## 5. Worker stop-and-report outcomes

| Input/selector condition | Worker action | Required output status |
| --- | --- | --- |
| Request and effective selection match with direct proof | Execute isolated assigned cases | Eligible to report PASS/FAIL |
| Requested model not accepted by provider | Do not fall back | model-selection VERIFICATION=UNAVAILABLE; results state BLOCKED |
| Effort value rejected, ignored or effective not observable | Do not silently retry at default | model-selection VERIFICATION=UNVERIFIED or UNAVAILABLE; results state INCONCLUSIVE/BLOCKED |
| W5 only supports Codex Desktop, not real ChatGPT Chat | Do not reinterpret Codex result as Chat mode | W5 surface-capability CHAT_MODE_NOT_VERIFIED / BLOCKED |
| Operator model valid but ChatGPT subject model not pinned | Do not conduct paired comparisons | W5 U-PAIR NOT_RUN/BLOCKED; no G2/G6 PASS |
| Provider fallback or agent changes model mid-run | Invalidate affected cases; preserve raw evidence | FAIL/INCONCLUSIVE, launch a separately frozen run only if authorized |

Never ask the human user a routine question to resolve a normal local coding/test failure; agents should diagnose independently. But unavailable capabilities must be reported honestly rather than bypassing account permissions or changing baseline silently.
