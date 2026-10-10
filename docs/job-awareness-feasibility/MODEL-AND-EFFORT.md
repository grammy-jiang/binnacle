# Model selection and explicit reasoning effort per worker

Status: **planned assignments, not yet launched**. No lane may inherit the ambient default model or default reasoning effort.

## 1. Why models differ

The objective is correctness and evidence quality with bounded cost, not maximally expensive reasoning everywhere. Protocol/identity/receipt investigations need stronger analytical models. Deterministic fixture scaffolding and statistical benchmark automation need competent but less costly models. Real ChatGPT behavior tests have **two different roles**: the Desktop operator and the ChatGPT model being tested, each with its own model/effort record.

On the Raspberry Pi at planning time (2026-10-10), Codex CLI was 0.162.1 and offered explicit --model/-c config overrides. The local Codex model cache listed gpt-6-astra and gpt-6-sol, each with low/medium/high/xhigh reasoning settings. User config defaulted to gpt-6-astra / high, but relying on that default is prohibited. Claude Code was 2.1.293 and advertised --model with opus/sonnet aliases and --effort low/medium/high/xhigh/max. User settings defaulted to opus, which likewise must be overridden explicitly. The cache/help is an **installation capability indication**, not proof of live account entitlement or that any particular request will be accepted.

## 2. Frozen planned allocation

| Assignment | Execution surface | Requested model | Explicit effort | Reason |
| --- | --- | --- | --- | --- |
| S0 shared fixture/preflight | Codex CLI | gpt-6-sol | medium | Deterministic isolated harness/manifest; limited novel reasoning |
| W1 FastMCP carrier, middleware, wire and exception parity | Codex CLI | gpt-6-astra | high | Subtle protocol/type/compatibility reasoning and contract tests |
| W2 trustworthy chat identity and adversarial session separation | Claude Code CLI | opus | high | Authentication provenance, threat analysis and negative isolation cases |
| W3 receipt, lost replies, cursor/replay/race semantics | Codex CLI | gpt-6-astra | xhigh | Most subtle distributed-systems/acknowledgement reasoning; false PASS is high impact |
| W4 reproducible overhead/tokens/legacy compatibility benchmarks | Claude Code CLI | sonnet | medium | Mostly scripted measurements, instrumentation and statistics with bounded reasoning |
| W5 Desktop experiment operator, if actually a supported Codex Desktop operator | Codex Desktop | gpt-6-astra | high | GUI attribution, cross-chat isolation and model-visible evidence; exact selector support **not yet verified** |
| W5 ChatGPT Chat **test subject** (distinct from the operator) | ChatGPT Chat | GPT-6 | Medium | Fixed, reproducible experimental condition; not a claim about what Desktop currently provides |
| Supervisor | This ChatGPT conversation | existing model, not a CLI worker | N/A | Only reconcile worker evidence and report; does not conduct the experiments |

The Desktop operator can be a tool-driven ChatGPT Desktop/Codex Desktop agent **only if an approved supported interaction mechanism exists**. Do not infer that /usr/bin/chatgpt, currently symlinked to codex-launcher, is a traditional ChatGPT Chat app. If it only provides Codex Desktop, that is not a passing Chat-mode subject. The W5 model/effort entries are binding **requests**, not verified runtime settings.

W5 ChatGPT subject model/effort must be selected and documented in the actual Chat UI before any paired trials. If GPT-6 Medium is not offered, S0/W5 cannot silently inherit default; propose an explicitly identified alternate fixed model/effort, log the substitution in a new pre-registered trial manifest, and mark this planned configuration BLOCKED/NOT_RUN until that change is explicitly approved. Every comparison pair must use the same subject model and reasoning level. Do not mix product surfaces, account tiers or model families and aggregate them as one cohort.

## 3. Explicit CLI invocation requirements

**Codex CLI**: use documented flags with per-worker model and effort, not ~/.codex/config.toml defaults. Illustrative syntax (the dispatcher must fill exact separate workdir and evidence paths):

~~~bash
# S0
codex exec -m gpt-6-sol -c 'model_reasoning_effort="medium"' \
  -s workspace-write -a never -C "$S0_WORKTREE" --json - < "$S0_PROMPT_FILE"

# W1
codex exec -m gpt-6-astra -c 'model_reasoning_effort="high"' \
  -s workspace-write -a never -C "$W1_WORKTREE" --json - < "$W1_PROMPT_FILE"

# W3
codex exec -m gpt-6-astra -c 'model_reasoning_effort="xhigh"' \
  -s workspace-write -a never -C "$W3_WORKTREE" --json - < "$W3_PROMPT_FILE"
~~~

No --dangerously-bypass-approvals-and-sandbox, --oss substitution, hidden fallback, --search or profile elevation. The -a never setting means commands that require approval fail with a recorded error rather than blocking the worker and acquiring unauthorized privileges. Worker scripts may use project-local scratch paths only; external app/session actions are not permitted for CLI lanes.

**Claude Code CLI**: explicitly pin alias and effort, suppress browser integration and nonessential external tools. Illustrative invocations:

~~~bash
# W2 security / provenance
claude --model opus --effort high --permission-mode dontAsk \
  --no-chrome --disallowedTools WebSearch,WebFetch,Agent \
  --print --output-format json -p "$(cat "$W2_PROMPT_FILE")"

# W4 measurements
claude --model sonnet --effort medium --permission-mode dontAsk \
  --no-chrome --disallowedTools WebSearch,WebFetch,Agent \
  --print --output-format json -p "$(cat "$W4_PROMPT_FILE")"
~~~

Each is launched with cwd set to its own trusted worktree and its own results directory. Validate the command form against the actual installed CLI. Do not use --dangerously-skip-permissions or a global writable directory permission. Tool names and approval modes must be checked against version 2.1.293 at actual kickoff.

Neither CLI tool should obtain GUI authority to become a second Desktop operator. Both are programming workers operating without ChatGPT interaction.

## 4. Runtime verification and safe fallback

1. **Preflight:** verify requested model ID/alias, CLI flag support, effort enum, account access and independent session/worktree. Read only non-sensitive settings; never read raw auth files.
2. **First result:** capture runtime-reported effective model and effort from structured CLI output or trusted app UI. If unavailable, record EFFECTIVE_MODEL_UNVERIFIED and treat the lane INCONCLUSIVE until resolved; the CLI flags alone prove a request, not necessarily effective execution.
3. **Pin and freeze:** record requested model, effective model (with evidence), requested effort, effective effort, runtime/CLI version, provider, session ID and any fallback event in results.json and evidence-index.json.
4. **No automatic downgrade:** if the requested model or effort is unavailable, return MODEL_UNAVAILABLE / BLOCKED. The supervisor may authorize one explicit different model+effort in a **new** worker assignment/run revision, with its own provenance; do not silently retry on default/fallback model.
5. **Budget control:** S0 and W4 use medium effort by design; W2/W1/W3 carry more reasoning budget only where correctness requires it. Set an explicit per-worker time and token/cost cap in the S0 manifest, monitor consumption, and return a complete BLOCKED/PARTIAL evidence record rather than switching models invisibly.
6. **A/B validity:** W5 subject model and effort stay fixed from first control through last candidate and across all test chats. Operator model may not change within an active run. On any model or effort drift, stop that comparison, retain observations, and restart with a new pre-registered RUN_ID if justified.
7. **Independent review:** the supervisor performs source/evidence validation only; for a high-risk ambiguity, request a second independent worker review under a separately pinned model+effort, not the same model's unverified assertion as proof.

Model naming is a run parameter, not a reason to rewrite acceptance criteria. The mandatory criteria for security isolation and receipt remain strict even if the selected model cannot complete the lane.

## 5. Cost/effort attribution

W4 must distinguish the inference token cost of the experiment subjects from the **runtime/token overhead of the Binnacle reminder**. Expensive W3 reasoning time is not part of MCP latency; it is worker execution cost. The manager reports cost per lane if actually measured and never replaces an absent cost figure with a fabricated number.

Chosen models and reasoning levels above must appear identically in [worker-manifest.json](worker-manifest.json), each worker brief, each worker's results.json and the supervisor summary. If any differs, G0 input consistency FAILS until reconciled.
