# Retrospective and prospective agent-tool evaluation plan

**Status:** P0 research / proposed evaluation method, not an approved public tool or code implementation.
**Date:** 2026-10-20
**Source baseline:** Binnacle `ce943ced`, Development Intelligence candidate portfolio `78b250f3`.
**Scope:** Evaluate incremental **agent task value** from `inspect_symbol`, `search_code_structure`, `analyze_change`, `check_code` and private failure/test-selection services.
**Security:** Read approved local journals, session-observer SQLite and opt-in private full-capture JSONL **on the originating host**. Full original command and source may be inspected locally for evaluation after the 2026-10-21 user authorization; never execute historical commands or commit/export their raw content.

## 1. Key evaluation rule

**Historic logs describe behavior with the old toolset. They do not identify the counterfactual performance of a tool the model never saw.** A before/after calculation that equates fewer calls with saved model steps is unsound. Use historic logs for opportunity discovery and baseline workloads, deterministic correctness fixtures for tool usefulness, then controlled agent A/B to estimate actual adoption and gain.

The unit of product value is a **completed development task with correct verified output**, not an LSP JSON-RPC response or a matching `run_command` keyword.

## 2. Data sources, quality and authority

| Source | Available evidence | Missing or restricted | Role |
| --- | --- | --- | --- |
| Raspberry Pi `binnacle-mcp.service` journal | Older `tool_call` names, parameters (up to 500 chars), timestamps, turn/call; `tool_result` elapsed/size/exit/status; dispatch and job events | Raw result text, user prompt, model context, reliable complete command if clipped | Historic behavior/sequence and outcome metadata |
| Three-host private opt-in `full-capture/*.jsonl` (activated 2026-10-21 at different local times) | Full as-received MCP inputs, as-delivered tool results, tool errors, exact request/call identity; uncapped middleware serialization | Upstream tool result shaping, missing/pruned job spools, original user prompts/model context and complete historic working trees | **Primary post-activation** local command/pattern/source opportunity discovery; see [readiness audit](full-capture-readiness-2026-10-21.md) |
| 2026-09-27 saved usage reports and JSON | Historical tool/category frequencies, step/poll analysis and cost baseline | No per-case gold labels and incomplete total-model token accounting | Sanity check and sampling strata |
| `~/.local/state/tunnel-client/logs/binnacle.log` | Forwarding IDs, timing and some delivery failures | User task requirements/result text; not a universal model-step oracle | Cross-layer latency and request grouping |
| `~/.local/state/binnacle-session-observability/sessions.sqlite3` | Hashed `request_hash`, `base_hash`, linked `calls`, `request_runs`, `tunnel_events`, `local_job_events`, `mcp_internal_events` | Raw command, search pattern, prompt and outputs are deliberately not stored | Privacy-preserving timeline/correlation, post-scrub traffic |
| Historical Git objects and scoped test/coverage artifacts | Reconstruct committed source states, independent test or failure evidence | Uncommitted file states, ephemeral subprocess state and historic external dependencies | Gold reference and executable fixture snapshot when provable |
| Future isolated A/B harness | Same task start state, tool schemas, tool outcomes, *full model* input/output token accounting where API makes it available, model steps, quality | May not reproduce opaque ChatGPT website internals perfectly | Causal comparison, not inferable from old logs |

**Era boundary:** From the 2026-10-09 journal privacy refactor **until each host's 2026-10-21 full-capture activation**, journal `tool_call.args` and request logs redact raw command, stdin, path, search patterns, source and errors. The original `args_chars` length remains, but content cannot be reconstructed. The separate post-activation **private full-capture JSONL does contain full original input strings** and may be locally inspected under current authorization. The collector cannot retroactively restore pre-activation redacted data or upstream clipped `run_command` output. Never export raw pre-privacy or current private captures to Git or reports.

The current session-observability database contains approximately 25.9k calls across October 6–20, but its `calls.turn` is usually one hashed full request ID per call. Derive workflow groups using **unambiguous `calls.request_hash -> tunnel_events.request_hash -> tunnel_events.base_hash`**, not `turn.split('/')` when hashes lack a slash. Fall back to `unknown_group` on collisions/incomplete lifecycle. A request group is not necessarily a single development task.

## 3. Read-only audit results, 2026-10-20

### October observer linkage (snapshot, not a stable future invariant)

- `calls`: 25,935; terminal `ended` populated: 25,935.
- Nonempty request hashes: 25,919 distinct (repetitions are possible).
- All 25,935 calls had an unambiguous exact-hash join to a tunnel base group; 0 hash -> multiple-base collisions observed.
- Recovered base groups: 1,176. Size distribution: 173 groups of 1 call, 241 groups of 2–4, 407 groups of 5–19, 298 groups of 20–99, 57 groups of 100+.
- Sources are per-host/local; do not assume this one SQLite file includes MacBook Pro or Sextant usage.

This proves the *current snapshot can be correlated*, not that every future deployment or every historical era has intact identifiers.

### Older September 26 read-only opportunity sample

From `binnacle-mcp.service` on 2026-09-26, ChatGPT-attributed `tool_call` records after marker filtering:

- 3,269 calls, grouped into 129 turn prefixes, and 2,579 **two-second-gap step proxies**, not actual model reasoning steps.
- `run_command`: 1,884; 860 had `args_chars > 500` (command reconstruction incomplete).
- Visible command categories (nonexclusive and partial): 187 Git read/show/diff-like, 143 test-keyword, 195 grep/rg. Keyword presence does not establish an intent or ground truth.
- Candidate sequential windows (bounded to the next five *steps* and five minutes unless noted):
  - `search_text -> read_file` in the immediate following step: 68;
  - Git read/show/diff -> source read/search: 44;
  - test command -> source read/search: 49;
  - Git read/show/diff -> source inspection -> test within 15 minutes: 16.
- These are **overlapping opportunity windows, NOT savings or distinct development tasks**. At most, eliminating one serial step in each of the 68 specific `search_text -> read_file` windows would account for ~2.6% of the 2,579 step proxies on that one day; the actual achievable share may be zero or negative after new tool selection and overhead.

The October 14 journal sample confirmed raw commands were redacted in every one of 1,982 observed `run_command` calls. It is invalid to count keyword occurrences there as zero demand. The October `turn` header also often hashes an entire request identifier; the session observer's exact hash join is the preferred group source.

### Historical lessons we must not repeat

The 2026-09-27 tool-efficiency review found that a batch `read_file` concept could at most remove about 2% of model steps because most multi-file reads were already parallel. `job_status` polling optimizations have a different owner in Commands; they must not be credited to Development Intelligence. Historical journal attribution based on timestamp alone also over-counted ChatGPT traffic; use actual turn/request evidence and mark unmatched records.

## 4. Trace-to-task reconstruction pipeline

The pipeline must **never execute old Shell commands**. All stages are deterministic, offline and bounded until prospective A/B.

1. **Extract:** Read bounded windows from systemd journal/tunnel, read-only session-observer SQLite (`PRAGMA query_only=ON`) and the approved host-local full-capture JSONL for post-activation periods. Parse full raw tool arguments/results **locally** and track capture era, upstream output shortening, data availability and error events. Do not change production loggers, services or retention; export only aggregate/labelled metadata by default.
2. **Correlate:** Pair `tool_call`/`tool_result` by generation+call, pair Jobs on durable IDs, and requests by exact hashed identifiers. Explicitly label orphaned, duplicate, ambiguous or version-incompatible joins.
3. **Form workflow groups:** Start from authenticated per-request bases; split on large inactivity gaps, workspace/branch changes or independently recognisable task transitions **only when metadata supports it**. Never assume one ChatGPT turn equals one issue.
4. **Detect opportunities:** Search/read navigation chains; repeated syntax-oriented shell searches; local Git diff -> source navigation -> tests; test failure -> source investigation; lint/type-check command -> corrective code navigation. **For post-2026-10-21 private full-capture eras, use locally inspected complete command/pattern/input text for explicit candidate labels;** for scrubbed eras continue metadata-only labels rather than treating absence of raw text as absence of use. Preserve origin/era tags and count mixed-quality cases separately.
5. **Sample:** Stratify by date/era, task type, duration, call count, language/workspace, correctness and error status. Include short and long groups, negative controls and random non-candidates. Deduplicate repeated probes, retries, CI loops and near-duplicate trace windows.
6. **Recover evidence:** A historic Git commit/tree is a valid source snapshot only when the target file contents at decision time can be established. If uncommitted edits or hidden output matter, mark the case `partial_reconstruction`; do not fabricate lost state. If feasible, create a safe synthetic analogous task with a separately labelled provenance class.
7. **Label task and gold:** Annotators reconstruct the actual *question/goal* from accessible project notes/issues and only allow an episode into live replay if the goal is unambiguous. Ground expected answer in independently reviewed source/test facts, not in the new LSP provider's own output. Hold out future commits, test results and intended solution from the agent's starting context.
8. **Freeze corpus:** Store sanitized manifest with source SHA, task prompt, allowed roots, gold assertions, eligibility class, confidence and unresolved missingness. Any raw confidential artifacts remain local with explicit limited retention and are not pushed.

Suggested replayability:

| Grade | Condition | Allowed evaluation |
| --- | --- | --- |
| R0 | Tool sequence only; prompt/source state not recoverable | Demand estimate / opportunity mining only |
| R1 | Partial task semantics, missing mutable source/output | Human-labeled scenario design and synthetic fixtures; not faithful retrospective replay |
| R2 | Verified frozen source snapshot, unambiguous task and independent gold | Matched deterministic tool queries and agent A/B |
| R3 | R2 plus reliable original runtime/test state | Full workflow replay including relevant test/failure artifacts |

Do not filter to R2/R3 silently: report percentage excluded so the replay set does not masquerade as representative of total traffic.

## 5. Controlled tests — separate two kinds of benefit

### Stage A: deterministic capability and query comparison

For each eligible frozen task, run the *same question* against:

- baseline exact search/read plus explicit already-allowed commands, under a measured context/output cap;
- candidate `inspect_symbol`, `search_code_structure`, `analyze_change` or `check_code` invoked privately by a test harness.

Score **truthful correctness first**. For symbol lookups, independently verify file/line, identity, correct references, ambiguity and external-path exclusion. For structure queries, score exact AST matches vs plain regex false positives. For impact, score impacted symbols/contracts and known missed dynamic-dispatch edges. For test recommendations, score precision/recall of high-value/affected tests against reviewed target-specific gold; where possible use per-test coverage contexts recorded from the frozen tree. For diagnostics, verify actual analyzed scope, exit/completion, false-clean behavior, error normalization and side effects.

Raw LSP timings are diagnostic only. Compare standalone provider, Binnacle overhead, JSON bytes/returned context, warm/cold startup and memory; don't treat sub-millisecond raw RPC as a product victory.

### Stage B: prospective agent A/B (required for product decisions)

The same model, effort, tool permission profile and **frozen starting repository** receives the same task in two isolated fresh sessions:

- Control: existing Files, Search, Commands.
- Treatment: same baseline tools plus exactly **one** proposed candidate tool.
- Later ablation: paired capabilities (e.g. impact + test selection) only after independent value is shown.

Use randomized/counterbalanced order and multiple tasks, fresh contexts/worktrees and blinded gold criteria. Repeat variable tasks enough times to measure variance; do not assume deterministic model behavior. No future commits/answers leaked to either arm. Ensure tests themselves cannot call a remote API or change production.

**Client-fidelity gate:** distinguish three evaluation environments. A direct local MCP client validates Binnacle's tool implementation, schemas and timing, not an AI agent. Codex/Claude/other local agents may serve as exploratory integration surrogates, not a substitute for the target ChatGPT **Website Chat Mode** client. Any claim that adding a new tool improves ChatGPT's actual selection/arguments/model-step efficiency requires a matched Chat Mode test with the same tool discovery and permissions. Do not conflate Chat Mode with Work Mode. Keep those live tests low-rate and separate from production traffic; transient HTTP/429 or chat resumption failures are harness/infrastructure outcomes to record, not reasons to overwrite agent-quality metrics.

Record exact **agent invocation steps** in the prospective orchestration where accessible. Historical two-second gaps are a proxy and must not be treated as direct reasoning-step telemetry. Record full model billed tokens where supported, distinguish prompt/completion/cache from returned MCP payload tokens, and record standing tool-schema token cost, warm provider residency, process RSS, wall time, retries and failed tool-selection/argument-generation.

## 6. Metric definitions and conservative business case

### Correctness and usability gates

- Task success = independent acceptance checks pass, no unwanted edits, and requested information is correct and sufficiently scoped.
- Wrong-symbol rate, false-completeness, stale/read-only violations and missed must-run tests are hard quality gates.
- Tool selection reliability = eligible tasks where the agent chooses the right tool / eligible tasks attempted. Tool argument reliability is separately measured.
- `test_recommendations` never suppress mandatory full CI/release quality gates.

### Cost and benefit metrics

For each paired task i:

- `delta_steps_i = baseline_model_steps_i - treatment_model_steps_i`.
- `delta_calls_i = baseline_mcp_calls_i - treatment_mcp_calls_i`; report but do not rank alone.
- `delta_tokens_i = baseline_total_tokens_i - treatment_total_tokens_i`, including standing tool schemas and all model token categories available from the harness.
- `delta_wall_i = baseline_wall_time_i - treatment_wall_time_i`.
- `incremental_provider_cost_i` captures warm memory/CPU residency, cold startup amortization and any analyzer/process cost.
- `success_pair_i` captures whether either arm failed or violated test requirements.

Estimate portfolio benefit over *all observed work*, not cherry-picked eligible cases:

`net_expected_gain_per_task ~= opportunity_rate * agent_adoption_rate * successful_gain_when_used - per-task_schema_and_runtime_overhead - errors_or_extra_steps`

Historical data can help estimate `opportunity_rate`; only a randomized controlled treatment can estimate adoption, successful gains and side effects. It is invalid to plug in historical command share as if it were successful tool adoption.

Use paired bootstrap intervals clustered by **task or request group**, not each call, because actions within a group are correlated. Report median, p90, failure distribution and confidence intervals by language/task category as well as overall. Pre-register minimum correctness and efficiency thresholds before the holdout A/B set is run.

### Claim categories

- `observed_workflow_frequency`: measured historical trace count with confidence/coverage annotations.
- `theoretical_step_opportunity`: an optimistic upper bound based on an explicitly stated replacement assumption.
- `tool_correctness`: validated frozen fixture answer, with completeness.
- `observed_agent_improvement`: randomized paired agent outcome.
- `population_estimate`: opportunity-weighted extrapolation with uncertainty and workload caveats.

Never call a theoretical opportunity count a measured savings percentage.

## 7. Executable evaluation work packages (plan extension, not product code)

| ID | Deliverable | Acceptance |
| --- | --- | --- |
| E0 | Reuse existing parser and readonly session observer schema; freeze field/era documentation | **Post-activation GO (2026-10-21):** three-host schema/era documentation, exact session-observer joins and non-content evidence. Earlier scrubbed windows are not reconstructed; see [frozen pilot](e0-e1-trace-pilot-2026-10-21.md). |
| E1 | Privacy-safe trace/episode metadata extractor (separate offline script) | **Post-activation GO (2026-10-21):** scripts/lsp_e01_trace.py, scripts/lsp_e01_patterns.py and scripts/lsp_e01_observer.py; exclusive UTC cutoff, 45 adversarial synthetic tests per host, three-host anonymized execution and independent follow-up [GO](e0-e1-independent-review-2026-10-21.md). Windows are candidate request-group patterns, not tasks/model steps; see [frozen pilot](e0-e1-trace-pilot-2026-10-21.md). |
| E2 | Historical classifiers and stratified candidate sampler | **TECHNICAL GO (2026-10-21), full E2 manual-label gate OPEN:** deterministic host-local sampling, 49 request groups incl. 11 negative controls, 39 synthetic tests per host, atomic private manifests; **0 verified task goals/gold/source snapshots**, so sensitivity/specificity on real tasks remain unavailable. [Report](e2-historical-sampling-2026-10-21.md) / [review](e2-independent-review-2026-10-21.md). |
| E3 | Immutable task manifest and independent gold annotation | R2/R3 grade for live replay, hash-based snapshot identity and no hindsight leakage |
| E4 | Private capability tests and tool-response evidence | Same inputs, correctness/coverage/safety and resource metrics |
| E5 | Prospective paired agent harness, fresh contexts and metrics | Calls, **true measured** agent steps, model tokens, wall, task success; randomized pairing |
| E6 | Benefit report + explicit GO/REWORK/STOP for each candidate | Per-tool efficacy, eligible fraction, confidence intervals, overhead and regression cases |
| E7 | Optional safety/privacy retention hardening of evaluation artifacts | No changes to live production log privacy or tool surface |

**Suggested pilot** (not a claimed statistical power guarantee): manually validate around 40–60 trace-derived candidate tasks across navigation, impact, test selection, diagnostics/failure analysis and negatives. Build a smaller R2 subset first, then expand to 100+ diverse independent tasks if labels/replay quality are sufficient. Determine final sample size by observed variance/power, not by convenience.

Sequence: E0/E1/E2 can be developed without any new public tool; E3 can be built alongside private LSP P1–P3; E4/E5 depend on private candidate functionality; E6 is the P4/P5/P6 release decision evidence.

## 8. Specific safeguards and exclusions

- Do not execute arbitrary old `run_command` strings. They may modify repositories, install packages, run third-party code, send messages or use secrets.
- Do not snapshot whole private journals in the Git worktree or send raw logs to an external model. The September pre-scrub journal contains potentially sensitive command arguments; October scrub rules must not be weakened for analytics.
- No assumptions that successful historical exit code means the agent's task succeeded. Similarly, `job_status` polling loops are Commands optimization candidates, not Development Intelligence savings.
- A missing or redacted command string is **unknown**, not absence of a syntax/test/Git operation.
- Repository state must be frozen and confined; avoid historical incomplete working trees and a live production service.
- A provider process may execute project-controlled code; side-effect audits and appropriate trust/sandbox classification precede agent experiments.
- Outcome claims must include corpus, model/effort, source/provider versions, host and limitation statements.

## 9. Existing references

- [Usage analysis, September 27](../usage-analysis-2026-09-27.md) and `scripts/usage_steps.py`.
- [Telemetry and logging contract](../logging.md), including 2026-10-09 privacy changes.
- [Tool telemetry review, September 22](../tool-telemetry-review-2026-09-22.md).
- [Development capability portfolio](development-capability-portfolio.md).
- [Implementation plan V2](implementation-plan.md).
- [Capability mapbook V2](capability-mapbook-v2.md).
- Local `~/Projects/binnacle-session-observability` code for read-only DB correlations.

**The evaluation is not ready to claim performance uplift**. The completed work in this document establishes feasible historical instrumentation and a test design, while the prospective agent A/B has not been executed.

## 10. 2026-10-21 authorized local full-capture evaluation amendment

The user explicitly authorized using complete, unredacted private MCP capture history for local Development Intelligence evaluation after the logging workstream finished. Full raw requests, commands and tool responses may therefore be parsed **in place on the originating host** to classify candidate coding work, identify source files and build bounded, independently verified scenarios; they must not be executed or silently exported, copied to repository files, forwarded as raw messages to a model reviewer, or merged with earlier scrubbed events without era labels. The private collector has no string clipping, but upstream `run_command` results can still be clipped at 24,000 characters and durable job spools can be pruned. Raw trace content remains under the explicitly enabled private capture policy; the ordinary journal privacy contract is unchanged. See the [three-host capture readiness audit](full-capture-readiness-2026-10-21.md) for exact quality constraints. Historic capture is suitable for opportunity mining, **not** causal agent A/B claims.
