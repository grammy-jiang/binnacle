# Five independent worker briefs

Status: **dispatch-ready instructions, no trials executed**. Each worker consumes the exact frozen RUN_ID, SOURCE_SHA, FIXTURE_SHA and only its section below.

## Common worker contract

You are one read-only-evidence worker for Binnacle Job Awareness feasibility. You may build disposable test fixtures/prototypes only inside your own isolated workspace. Never edit, commit to, push, merge or deploy production Binnacle source. Do not use user secrets, live job content, credentials, browser data or another lane's workspace. Do not contact the ChatGPT user for incremental supervision. Run your prescribed cases, verify actual responses, and output results.json, findings.md and a file-hash evidence index under your owned results directory. Every case must have actual versus expected, PASS/FAIL/INCONCLUSIVE/BLOCKED, elapsed time, provenance and a reproducible command or supported GUI event trail. End when your bounded work is done. Do not interpret another lane's results or author the combined decision.

Read [EVIDENCE-AND-GATES.md](EVIDENCE-AND-GATES.md) and [PARALLEL-EXECUTION.md](PARALLEL-EXECUTION.md) before beginning. Do not reinterpret an unsupported server/client feature as functioning simply because FastMCP has a type for it.

## W1 — Codex CLI: FastMCP native carrier/wire compatibility

**Model/effort: gpt-6-astra / high (explicit, verify actual runtime).**

**Purpose:** determine which carriers can carry a compact job reminder through a native FastMCP middleware or result path while retaining existing contract behavior. W1 does **not** claim that ChatGPT sees any particular field.

Inputs: frozen FastMCP/MCP versions; source files for application composition, ToolLoggingMiddleware, visibility transforms, ToolResult-based job_status/run_command; S0 benign fixture; saved baseline payloads.

Implementation constraint: test the public FastMCP middleware API first, not an internal monkey-patch, proxy response-body rewriter or own MCP server framework. An unsupported path is recorded as unsupported, not worked around silently.

Independent test matrix:

1. RAW-BASE: capture ordinary tool result byte/JSON fields, text, structured result, error payload and tool schema before adding a reminder.
2. M-META: attach a nonce-bearing reminder through result metadata where publicly supported; inspect raw JSON-RPC and whether middleware receives the right result type.
3. M-TEXT: attach a short, separate human-readable result content block; verify normal result text and structured return remain unchanged.
4. M-STRUCT: try an additive structured result field only if the declared output schema supports it; otherwise record CONTRACT_FAIL. Never widen a production schema to make a probe pass.
5. M-ERROR: tool exception, returned ToolResult error, validation error and downstream middleware error. Reminder logic must never convert an error to apparent success or swallow it.
6. M-SURFACES: modern ChatGPT-like stateless discover/call, legacy initialize/call, per-client visibility restrictions and tools/list. No hint on a denied tool.
7. M-RELOAD: confirm what middleware-private state survives a new request, client session and server restart; do not confuse a Python ContextVar with durable state.
8. M-COMPAT: exact existing result fields/order for the no-reminder arm and original job_status/command visibility. No removal or renaming of eight public Binnacle tools.

Outputs: raw redacted on-wire fixtures for each carrier, FastMCP API references with exact installed versions, comparison matrix of schema/text/exception semantics, candidate ranking **only by technical feasibility**, and hard blockers. Mark metadata MODEL_VISIBILITY=UNTESTED (W5 owns this conclusion).

## W2 — Claude Code CLI: session identity, trust and isolation

**Model/effort: opus / high (explicit, verify actual runtime).**

**Purpose:** find an identity key that is stable enough across ChatGPT tool calls and demonstrably authorized for mapping jobs to a chat. A stable client name is not a chat identifier.

Inputs: S0 immutable synthetic identities, request metadata and three synthetic client streams. Read-only Binnacle request telemetry and identity resolution code; no live private headers or chat logs unless explicitly sanitized in the run packet.

Independent test matrix:

1. I-ERAS: compare legacy MCP session IDs, modern per-request metadata and ChatGPT Chat clientInfo; distinguish protocol connection, turn ID, chat/conversation ID and account authentication.
2. I-HEADERS: inspect observed definitions of X-Request-Id and X-OpenAI-Session without assuming either is authenticated. Distinguish a hash useful for logging from a trusted authorization key.
3. I-TURN: interleave 30 synthetic calls per each of Chat A/B/C; vary call order and FastMCP session regeneration; prove expected grouping.
4. I-SPOOF: attempt forged, missing, reused, contradictory, malformed and cross-client headers, including a second client claiming Chat A's nominal token. Unknown identity must never trigger chat-specific reminders.
5. I-RECONNECT: repeat after new connections and process restart. A volatile session marker can be used only for the lifetime it actually proves.
6. I-AUTH: trace source of any trusted chat ID back to an authenticated boundary or explicitly document that such a boundary is absent. Never treat a user-controlled custom header alone as proof.
7. I-LEAK: ensure lookup of another chat's job by guessed/matching identifier is impossible **at the reminder layer**. Existing explicit by-ID job tools may have different access policy; do not silently claim to change it.
8. I-REAL: define the exact three-chat observation fields required from W5; do not run those GUI trials yourself.

Outputs: identity provenance diagram, attack/negative test results, whether a trusted cross-turn chat key is OBSERVED/UNPROVEN/UNAVAILABLE, recommended fail-closed behavior and raw redacted fixtures. Cross-chat leakage must be zero.

## W3 — Codex CLI: result receipt, replay and safe acknowledgement

**Model/effort: gpt-6-astra / xhigh (explicit, verify actual runtime).**

**Purpose:** prove whether the existing durable job status/result read path can serve as a reliable implicit acknowledgement without adding a separate acknowledgement tool. Do not invent a public Drop tool.

Inputs: actual Binnacle job_status/JobStore/cursor contract, a synthetic append-only spool, nonce-bearing pages, S0 precomputed job transitions. Do not write to real job output.

Independent test matrix:

1. R-STATE: running → exited (success/failure), interrupted/unknown, quiet but running, one active job and multiple completed jobs.
2. R-UNFETCHED: terminal job is eligible for reminders until its output is completely and reliably consumed; running job remains eligible independently of output updates.
3. R-CURSOR: cursor=start, end, next_cursor, multiple pages, has_more=true, terminal has_more=false, invalid/cross-job cursor, UTF-8 split and huge log.
4. R-REPLAY: after nominal full read, the old job ID/cursor can retrieve the same content again; no deletion, truncation or mutation of stdout by acknowledgement.
5. R-LOSS: fail before request, mid-response, after server writes reply but before client receives it, client retry, duplicate calls and parallel readers. A server-side successful fetch is **not evidence of client receipt**.
6. R-ACK: test proposals (a) server saw full fetch; (b) next trusted call carries previous cursor/receipt; (c) explicit receipt if implicit proofs fail. Record which transitions are actually defensible. Do not declare PASS for (a) solely from a 200/tool success.
7. R-ISOLATION: job-specific read receipts are per trusted chat/consumer if the selected design requires it. Concurrent readers' cursors remain independent.
8. R-RETENTION: expired/pruned job, disk read failure, server restart and a terminal write arriving concurrently with result fetch. Missing data does not silently become an acknowledged success.

Outputs: minimal state-transition diagram, exhaustive transition table, test evidence with byte/cursor ranges and one key verdict: can existing tool activity reliably acknowledge *delivery* rather than mere *server-side serving*? If not, return NO-GO for implicit acknowledgement, with a minimal alternative as a recommendation (not a production implementation).

## W4 — Claude Code CLI: performance, tokens and compatibility

**Model/effort: sonnet / medium (explicit, verify actual runtime).**

**Purpose:** measure cost of every technically plausible carrier against unchanged baseline. Use local synthetic traffic only; no live ChatGPT calls.

Inputs: S0 frozen fixture, same saved carrier variants as the common matrix, no dependency on W1 code, 0/1/10/100 active/terminal jobs, short and long ordinary result payloads, modern and legacy protocols.

Independent test matrix:

1. P-BASE: repeat no-reminder tool calls and record host load, warm/cold effects, transport and distribution of latency.
2. P-CARRIERS: benchmark _meta, short text content and structured extension if protocol-compliant; unsupported formats counted as FAIL, not silently removed.
3. P-SIZE: cap hint list, truncate/job-count bound and no stdout/command leakage. Initial target 512 UTF-8 bytes total per added reminder, configured/frozen before test.
4. P-TOKENS: report actual measured tokenizer counts where available, otherwise explicitly labeled conservative estimates, for each carrier and job-count cohort.
5. P-LATENCY: P50/P95/P99 extra latency, CPU/memory and throughput for at least three randomized baseline/candidate rounds; record raw samples, not one unrepresentative aggregate. Provisional target P95 incremental ≤5 ms on a reasonably quiet host; if load is unstable, report INCONCLUSIVE rather than PASS.
6. P-SCHEMA: unmodified tool contracts, output-size bounds, errors, rejected tool calls and old-client behavior; no positive hint on an authorization failure.
7. P-LOAD: 100 jobs and pathological output titles, oversized IDs/Unicode, bounded work and memory, no unbounded full-spool scans on ordinary calls.

Outputs: fixture-by-carrier measurements, raw timestamped samples, cost table, non-regression findings and provisional limits. W4 does not decide whether ChatGPT will act on a reminder.

## W5 — ChatGPT Desktop: live Chat mode observations

**Operator model/effort request: gpt-6-astra / high if actually selectable. ChatGPT Chat subject: GPT-6 / Medium fixed across all A/B trials, only if offered by the verified UI.**

**Purpose:** demonstrate what a real ChatGPT Chat-mode caller actually sees and does after a synthetic reminder. The Desktop operator owns all user-interface interactions and all three test chats; CLI workers must not use the GUI.

Inputs: S0 isolated test MCP App, three synthetic ChatGPT chats (A/B/C), its own nonces, a frozen three-carrier display matrix, balanced control/candidate prompts and observation form. W5 does **not** wait for W1 to select a carrier.

Before starting, complete [DESKTOP-OPERATOR.md](DESKTOP-OPERATOR.md) preflight. An installed binary named ChatGPT may actually launch Codex Desktop; **verify** real Chat mode and its MCP connection. Codex or Work behavior is out-of-scope as substitute evidence. If supported interaction is not possible, return BLOCKED with screenshots/diagnostics that contain no private account details.

Independent test matrix:

1. U-CANARY: prove a harmless nonce returned by the dedicated MCP echo tool reaches real ChatGPT Chat; record actual server-side client name/protocol and the corresponding chat message/tool-call evidence.
2. U-VISIBLE: three carriers tested separately; match nonce between raw result and model-visible result, distinguishing metadata visible only to the app from information supplied to the model.
3. U-RUNNING: start synthetic running job, call an unrelated MCP read tool and verify running reminders are available without blocking useful work.
4. U-FINISHED: advance the synthetic clock/job, call an unrelated tool, inspect whether the chat independently initiates result retrieval, and whether it makes at least one useful *subsequent* tool call.
5. U-ISOLATION: have A, B and C independently create jobs, interleave tool calls and reconnect; compare actual displayed hints and server-side IDs for leakage or cross-attribution. Run negative spoof probes only against own synthetic app.
6. U-RECEIPT: page through output, simulate a failed/lost delivery if supported by the test harness, and inspect whether hints persist until a defensible receipt. Read the same retained result again after any acknowledgement.
7. U-PAIR: first smoke every carrier, then run **12 randomized paired control/candidate trials** for each promising carrier with matched task scripts; record whether the same user prompt completed, any premature handoff, retrieval success, meaningful follow-on call, elapsed time and tool/token usage. The 12 pairs are feasibility evidence, not statistical production validation.
8. U-TURN-END: demonstrate only that no new MCP response reaches a finished ChatGPT turn without another trigger; record this limitation, do not try to bypass the ChatGPT platform lifecycle.

Outputs: UI/runtime surface identification, sanitized screenshots or exported test transcripts where permitted, raw tool-call and server journal correlation, per-trial machine-readable results, actual action sequences, distinction Chat versus Codex versus Work, and bounded limitations. Do not grade yourself from your final prose.

## Independent result interfaces

All five workers emit the same [results schema and evidence policy](EVIDENCE-AND-GATES.md). Each worker may return PASS or FAIL for a particular **scenario** but does not combine cross-lane results or recommend master deployment.

Manager summary is a **separate later step** after terminal reports from all lanes, following [MANAGER-SUMMARY-TEMPLATE.md](MANAGER-SUMMARY-TEMPLATE.md).
