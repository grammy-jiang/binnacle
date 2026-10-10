# R2 exact step input → processing → output contracts

Status: SPECIFICATION; all R2 result states initially NOT_RUN. Every file path below is relative to a new R2_RUN_ROOT created by R2-0. R1 references are read-only.

## Immutable common worker input packet (JSON)

All A–D and E0 receive one distinct packet at inputs/LANE.input.json using the input format schema in schemas/r2-worker-input.schema.json. Mandatory fields:

| Field | Format | Meaning |
| --- | --- | --- |
| schema | constant r2-worker-input-v1 | Protocol revision for handoff |
| r2_run_id | nonempty R2-prefixed string | New experiment identity, never reuse R1 Run ID |
| lane | A/B/C/D/E0 | Exclusive worker |
| source_sha | 40 lowercase hexadecimal | Product code SHA in R1; do not read moving master |
| r1_docs_sha, r1_fixture_sha256 | 40 and 64 lowercase hexadecimal | Pin original R1 evidence |
| r2_docs_sha | 40 lowercase hexadecimal | Exact committed R2 plan used by all workers |
| r1_evidence | array of ref/path/sha256/semantic_role | Read-only source inputs; missing hash fails closed |
| r2_fixture_sha256 | 64 lowercase hexadecimal | New synthetic fixture manifest hash |
| model | requested_model, requested_effort, required_surface | Hard-pinned per lane, no default |
| scenarios | array of pre-registered case IDs | Exactly one output row per ID |
| worker_workspace, output_dir | absolute paths restricted to authorized R2_RUN_ROOT | No overlapping writers |
| input_artifacts | ref, format, sha256, purpose | Read-only test data, static manifest and model/effort plan |
| required_outputs | ref, format, purpose | Exact output schema, no implicit artifacts |
| constraints | no production writes, no credentials, no unapproved plugin install | Safety gate |
| generated_at | RFC3339 with timezone | Handoff audit |

A worker must verify the exact source/fixture/packet hashes *before* testing and write its own model-selection.json with observed native effective model and effort. A blocked lane still emits a fully shaped result packet without inventing evidence.

## R2-0 shared preparation (Codex Sol/medium)

| Step | Required input, format | Work performed | Required output, format | Downstream |
| --- | --- | --- | --- | --- |
| 0.1 R1 provenance | R1 v2/assignment-v2.json, R1 W1–W4 results.json/index.json and original S0 run-manifest.json; raw bytes + SHA-256 | Read-only validate original result hashes; compare source/docs/fixture versions and completed/broken status | R2-0/r1-evidence-index.json (JSON array of exact paths/hashes), R2-0/preflight.json (JSON) | A–F |
| 0.2 environment | Git source SHA, Codex version/model listing, OS CPU/RAM, extant worker processes | Verify no active duplicate writer and safe baseline, active production units only read-only | R2-0/host-baseline.json (JSON), R2-0/model-capabilities.json (requested/verified pairs) | A–D |
| 0.3 isolated fixtures | R1 synthetic fixture contracts, R2 test plan; never R1 writable state | Generate bounded unique nonces, negative identity variants, artificial result pages, stable A/B trial schedule | fixtures/fixture-manifest.json (JSON), fixtures/fixture-index.json (JSON actual byte hashes), fixtures/payloads/* (synthetic bytes) | A–E |
| 0.4 worker admission | plan's r2-worker-manifest.json, exact R2 docs SHA, frozen fixture SHA, exclusive Git worktrees | Produce one independently verifiable packet and output dir per lane | inputs/A.input.json … inputs/D.input.json and inputs/E0.input.json; run-manifest.json (JSON fixed SHA of every packet) | A–E0 |
| 0.5 freeze and signoff | Prior S0 outputs, no human secrets, safe resource limits | Freeze inputs; prepare audit-ready blocked statuses for impossible UI permissions | R2-0/readiness.md; R2-0/events.jsonl; run-manifest.json final immutable bytes | Supervisor |

R2-0 outputs *prepared* with user action still needed for a plugin is a PARTIAL success: A–D and E0 launch anyway.

## R2-A — isolated real ChatGPT test connection, Codex Sol/medium

Input: inputs/A.input.json, R1 W1 carrier trace & W5 original unexecuted contract, official OpenAI custom-plugin and Secure MCP Tunnel docs, R2 synthetic tool schema and pre-authorized local safe resources.

| Step | Test input | Procedure | Mandatory output |
| --- | --- | --- | --- |
| A1 capabilities | Official documentation URLs and current installed account-neutral CLI/transport APIs | Check available supported connection routes, HTTPS/Tunnel requirements, auth, Plugin/App permissions; never presume Pro workspace entitlement | A/connection-options.json (JSON routes with available/unverified/blocked, exact citation and permission requirements) |
| A2 test app | R2 fixture nonce and read-only echo/status/result tools | Build isolated FastMCP mock on loopback without source changes; test native list_tools/call_tool/denial | A/synthetic-app.json (JSON tool list, schemas, port/owner/cleanup), A/local-canary.json (JSON raw request/response evidence) |
| A3 endpoint | Local test app plus permitted transport tests | Verify health, TLS/network/auth where supported; do **not** expose an endpoint, register a tunnel, or install a ChatGPT plugin without explicitly authorized scope | A/transport-evidence.json (JSON endpoint state and test-level proof); A/account-action-required.json (JSON exact required user action, or null condition) |
| A4 client handoff | Verified app endpoint and permission state, W5 trial script | Specify E1 selector, model, nonce echo, app name, expected tool-call ID evidence | A/chat-handoff.json (JSON supported entrypoint, ready/blocked, nonce contract and E1 prerequisites) |

A returns results.json with scenarios A1–A4, actual model-selection.json and raw transport evidence. A can complete local tests even if genuine ChatGPT Chat installation is blocked.

## R2-B — trusted chat ownership, Codex Astra/xhigh

Input: inputs/B.input.json, R1 W2/results.json, identity-matrix.csv, source-evidence.json, original Binnacle request middleware and tunnel identity files under frozen SOURCE_SHA, R2 synthetic chat streams.

| Step | Test input | Procedure | Mandatory output |
| --- | --- | --- | --- |
| B1 identity chain | Frozen source authentication, X-OpenAI-Session/turn/clientInfo examples *sanitized* | Trace principal → tenant → chat ↔ job; separately identify authenticated versus merely correlated data | B/trust-boundary.md (diagram/decision), B/identity-sources.json (JSON provenance matrix) |
| B2 adversarial test | A/B/C synthetic clients, missing/forged/replayed/reconnected markers | At least 90 interleaved synthetic calls and negative spoof cases; cannot transfer one chat's hints into another | B/identity-cases.csv (CSV source, principal, claimed/verified chat, expected/actual owner, leak, event ID), B/attacks.json (JSON raw case outcomes) |
| B3 candidate alternatives | Two candidate scoped grants or defensible narrower per-user scope | Compare trusted signed registration vs explicit per-chat authorization, missing-proof fallbacks; reject guessable header as proof | B/candidate-comparison.json (JSON rejected/viable architecture, security assumptions and known unsupported parts) |
| B4 definitive gate | B1–B3 raw tests and any real client identity proof (if independently available) | Decide real Chat scoped reminders SUPPORTED / REFUTED / UNRESOLVED; do not infer model behavior from local sandbox | B/identity-verdict.json (JSON trust level, explicit absent prerequisites and E2 allow/deny) |

B does not touch the real ChatGPT GUI, and B's synthetic signed grants cannot be described as an existing ChatGPT identity feature.

## R2-C — receipt protocol, Codex Astra/xhigh

Input: inputs/C.input.json, R1 W3/results.json, receipt-transitions.csv, receipt-verdict.json, cursor API source, synthetic multi-page append-only spool.

| Step | Test input | Procedure | Mandatory output |
| --- | --- | --- | --- |
| C1 formal protocol | Known terminal length/digest and paginated result contract | Define nonce/proof, job incarnation, generation, cursor/range, consumer identity and persistence, separate ACK ledger from retained output | C/receipt-state-machine.md (transitions), C/receipt-candidates.json (JSON explicit vs piggyback vs invalid server-fetch) |
| C2 fault model | Lost response, client never decoded, duplicated/reordered pages, restart, concurrent reader, failed job | Fault-inject independently; no ACK on unproven receipt, partial has_more, unknown job or expired output | C/receipt-events.jsonl (JSONL ordered causality), C/receipt-transitions.csv (CSV sequence/range/proof/ACK), C/negative-cases.json |
| C3 replay & compatibility | Same job ID after receipt, simulated Binnacle unchanged job_status schema | Prove retained output remains addressable and unchanged; compare whether piggyback can be added without violating current tool contracts | C/replay.json (JSON byte/hash comparisons), C/compatibility.json (JSON schema and unknown limitations) |
| C4 decision | Raw C1–C3 evidence with authenticated identity assumption explicitly marked | Rank options by correctness, cost, extra tool need, real Chat support, restart durability | C/receipt-verdict.json (JSON SUPPORTED/REFUTED/UNRESOLVED for each option) |

A PASS of a test falsifying the existing implicit ACK is not a PASS of that feature hypothesis.

## R2-D — external transport, compatibility and cost, Codex Astra/high

Input: inputs/D.input.json, R1 W1/carrier-matrix.csv and raw ASGI traces, W4/latency-samples.csv/metrics.json, exact FastMCP pinned version, frozen result envelopes and synthetic workloads.

| Step | Test input | Procedure | Mandatory output |
| --- | --- | --- | --- |
| D1 wire | Original W1 META/TEXT/STRUCT/CONTROL results, error and deny cases | Bind dedicated localhost loopback TCP when supported, use native MCP HTTP client, verify on-wire payload and schema parity; never bind public network | D/wire-matrix.csv (CSV transport/protocol/carrier/result/error/evidence), D/wire/*.json raw sanitized examples |
| D2 legacy/current | Frozen Binnacle tool schemas and both MCP protocol variants | Verify tools/list, auth rejection, structured outputs, tool failure, metadata and annotations; unsupported client functionality reported | D/compatibility.json (JSON supported/unsupported and exact SDK versions) |
| D3 performance | Paired 0/1/10/100 synthetic job cohorts and 3+ randomized repetitions | Measure full response processing + local transport (P50/P95/P99), both direct time and candidate-control signed deltas | D/latency-samples.csv (CSV per pair/arm/host load/bytes), D/metrics.json (JSON reproducible percentiles); never substitute render-only time |
| D4 token and budget | Real emitted MCP result strings; verified tokenizer if available | Count actual model-visible bytes/tokens when tokenizer reliable, otherwise label estimates; enforce bounded hint ≤512 UTF-8 bytes per response | D/token-cost.json (JSON tokenizer source and estimate labels), D/budget-verdict.json (JSON PASS/FAIL/INCONCLUSIVE) |

D need not wait for A's live plugin connection; D's own local loopback synthetic endpoint is independent.

## R2-E genuine ChatGPT Chat (not Codex Desktop)

| Step | Test input | Procedure | Mandatory output / consumer |
| --- | --- | --- | --- |
| E0 prep | R2 fixtures, official ChatGPT plugin workflow, original R1 W5 prompt/12-pair protocol | Freeze subject GPT-6/Medium, 3 synthetic chats, randomized pair IDs and result-required actions; do not access any UI | E0/trial-manifest.json (JSON), E0/readiness.json (JSON exact plugin prerequisites) |
| E1 visibility canary | A/chat-handoff.json READY, connected approved synthetic MCP app, original R1 no-hint and META/TEXT/STRUCT variations | On genuine ChatGPT Chat, execute nonce call through app; correlate raw app/server response to actual model-visible tool use | E/client-surface.json (JSON Chat vs Work vs Codex), E/visibility-trace.jsonl (JSONL event IDs and proof layers), E/visibility-verdict.json |
| E2 isolated behavior and A/B | E1 PASS plus B per-chat trust GO and C defensible receipt path, paired trial manifest | Test job Running → terminal-unread → actual correct result fetch → meaningful later tool call in **same user turn**, 3-chat isolation and ≥12 pre-registered pairs per viable carrier | E/trials.csv (CSV 2 arms per pair), E/workflow-trace.jsonl, E/isolation.json, E/behavior-verdict.json |
| E3 client boundary | Completed turn, no further MCP invocation | Show no unsolicited wakeup and state boundary; distinguish later user-triggered reconnection | E/turn-end.json (JSON), E/final-findings.md |

If A or real plugin permission blocked, E1/E2 are BLOCKED with exact proof. If B/C unresolved, only harmless E1 visibility may proceed; E2 cannot claim per-chat security or ACK. ChatGPT model self-report is not sufficient evidence; require real MCP call traces.

## R2-F supervisor-only synthesis

| Step | Required input | Processing (read-only) | Output |
| --- | --- | --- | --- |
| F1 collection | R2 run-manifest.json + terminal A/B/C/D/E0/E1/E2 reports, event and index files | Validate SHA/source/model/effort/case completeness; no silent missing workers | supervisor/collection-report.json (JSON schema failures and evidence hashes) |
| F2 contradiction review | A model-visible vs wire, B security vs E live auth, C ACK vs E missing result, D full-cost vs R1 | Record strongest proof and counterexamples; reject false equivalence | supervisor/contradictions.md |
| F3 gate | Evidence for G0–G7, R1 limitations carried forward | Assign PASS/FAIL/INCONCLUSIVE/BLOCKED, distinguish test PASS from hypothesis proof | supervisor/decision.json (JSON exact verdict/evidence) |
| F4 user report | F1–F3 plus outstanding owner/action matrix | Summarize R2 findings and next implementation go/no-go in Chinese | supervisor/FINAL-SUMMARY.md |

Only F writes the overall recommendation. It cannot override worker results or claim full project completion without E and all necessary gate evidence.

## Common output schemas

An output results.json conforms to schemas/r2-worker-result.schema.json. At minimum it contains schema, r2_run_id, worker, source_sha, r1_docs_sha, r2_docs_sha, r1_fixture_sha256, r2_fixture_sha256, input_packet_sha256, started_at, finished_at, executor (surface, version, session reference, requested/effective model+effort with native proof), hypotheses, cases array, artifacts index ref, metrics and limitations.

Each case has case_id, expected, observed, state, input_refs, evidence_refs, event_ids, proof_layers, blocker. Every pre-registered case appears exactly once even if BLOCKED/NOT_RUN.

Every raw event in events.jsonl must identify run, worker, scenario, timestamp, causality layer (generated/sent/client-received/model-used/workflow-continued), payload hash, anonymized chat/job ID and raw artifact. No automatic promotion from server-sent to model-visible proof.

Every evidence-index.json must include relative path, SHA-256, file size, media type, redaction status and proof layer. Worker model selection receipt is written **before** running cases and included in the hash index. Reports use explicit null for unmeasured values, never fabricated zero. Statuses PASS/FAIL/INCONCLUSIVE/BLOCKED/NOT_RUN; hypothesis SUPPORT/REFUTE/UNRESOLVED are separate.
