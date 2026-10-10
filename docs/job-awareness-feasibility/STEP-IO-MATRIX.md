# Exact step-by-step input and output matrix

Status: FINAL-PREFLIGHT SPECIFICATION ONLY — no experiment has run.

This is the operational source of truth for **the input, action, output format and dependent consumer of every step**. The frozen worker-manifest.json supplies the step IDs; [I-O-FORMATS.md](I-O-FORMATS.md) defines every artifact's fields; [schemas/](schemas/) validates JSON; [validate_contracts.py](../../tests/job_awareness_feasibility/validate_contracts.py) performs additional content/hash/invariant checks. Paths are relative to RUN_ROOT unless otherwise stated.

RUN_ROOT is ~/Projects/binnacle-job-awareness-results/RUN_ID. A worker must not read or modify any other worker's output during its own investigation. S0 artifacts are frozen before fan-out. Supervisor is read-only until final reporting.

## Global handoff, required for *every* step

Every S0/W1–W5 step starts with a context envelope from input/WN.input.json or S0's plan:

| Input element | Format / validation | Required behavior |
| --- | --- | --- |
| RUN_ID | string JA-...; matches run-manifest | Reject mismatch, no automatic new run |
| SOURCE_SHA | exact 40-hex Git SHA; source worktree must equal it | Do not use moving master |
| DOCS_SHA | exact 40-hex plan Git commit | All lanes use same approved plan |
| FIXTURE_SHA | SHA-256 of raw immutable fixtures/fixture-manifest.json bytes | Reject changed fixtures or arms |
| MODEL_REQUEST | requested_model, requested_effort from worker-input.json | Select explicitly; never inherit defaults |
| SOURCE AND RESULT BOUNDS | dedicated worktree and own result folder | No production writes or cross-lane edits |
| SCENARIO SET | exact scenario IDs from worker-input.json | Emit exactly one results.json row for each, including BLOCKED/NOT_RUN |
| INPUT EVIDENCE | files/records with fixed hashes, optional blocked app capability | Do not invent evidence for absent inputs |

Each worker starts by writing model-selection.json (schema: schemas/model-selection.schema.json), including requested versus effective model and effort, supported selector proof, and explicit fallback_used=false. This is mandatory even when the rest of the worker is BLOCKED.

For **every** scenario, emit a results.json.scenarios row with id/status/expected/observed/input_refs/evidence_refs/event_ids/proof_layers/duration_ms/blocking_reason. For executed scenarios write one or more entries to events.jsonl and link each event_id. PASS is a statement that the test yielded reliable evidence and met that case's criterion; hypotheses.SUPPORTED or REFUTED is a **separate** conclusion. A negative finding is valuable and is never suppressed.

## S0 — common input freeze and staging preparation (Codex gpt-6-sol, medium)

| Step | Specific input and format | Work | Mandatory output / format | Used by |
| --- | --- | --- | --- | --- |
| S0.0 — source and resource check | Git refs, AGENTS.md, DEVELOPMENT.md, plan commit, CLI versions, process inventory (read-only) | Verify SHA, capacity, primary-tree preservation, exact model selector | S0/preflight.json (s0-preflight schema); S0/provenance.json (JSON), S0/events.jsonl | Every worker and G0 |
| S0.1 — freeze identities | Source SHA, docs SHA, safe random RUN_ID seed | Freeze run identity, safe synthetic workspace, run-scoped nonce/ID map | run-manifest.json (run-manifest schema, status FROZEN or BLOCKED), S0/events.jsonl | All lanes |
| S0.2 — generate fixtures | FIXTURE-CONTRACT.md, deterministic seed, job lifecycle templates | Generate 10+ synthetic fixtures, output hashes, 3 carriers plus CONTROL, prerecorded A/B pairs | fixtures/fixture-manifest.json (fixture schema); fixtures/payloads/* (synthetic bytes); S0/fixture-index.json (JSON SHA-256 index) | W1–W5 |
| S0.3 — isolate test transport | Mock app contract, separate port/namespace, resource safety limits, approved connection state | Safely provision disposable FastMCP private test endpoint and supported Chat mode connection *if available* | S0/resource-ledger.json (JSON), S0/preflight.json.desktop_app_status; S0/connection-evidence.json (JSON or documented BLOCKED) | W5, G0 |
| S0.4 — generate independent worker packets | Exact frozen source/docs/fixture SHA and model assignments in worker-manifest.json | Produce one immutable, role-scoped packet for each W1–W5; add independent input SHA to run manifest | inputs/W1.input.json ... inputs/W5.input.json (worker-input schema), run-manifest.json.worker_inputs[*].sha256 | W1–W5 |
| S0.5 — dispatch readiness and freeze | Hashes of all preceding artifacts, safe host load, GUI ownership, pinned selectors | Verify immutability and resource admission; do not run W1–W5 experiments | S0/preflight.json state PREPARED/PARTIAL/BLOCKED; S0/readiness.md; run-manifest.json final immutable bytes | Supervisor dispatch |

S0 PREPARED does not mean real ChatGPT UI/subject is available. If Chat mode is blocked, mark S0 desktop_app_status BLOCKED and dispatch W1–W4 regardless. Do not continue making S0 changes after it has frozen the packets; a correction is a new RUN_ID.

## W1 — native FastMCP result carriers (Codex gpt-6-astra, high)

W1 common input: inputs/W1.input.json (JSON), frozen fixture manifest (JSON), native FastMCP version and exact Binnacle source; each experiment uses W1's own disposable MCP endpoint. Common output: W1/model-selection.json, W1/results.json, W1/findings.md, W1/evidence-index.json, W1/events.jsonl, W1/carrier-matrix.csv.

| Scenario | Scenario-specific input | Expected test and branch coverage | Mandatory raw output and format |
| --- | --- | --- | --- |
| RAW-BASE | CONTROL envelope fixture, fixed tool schemas and ordinary tool data | Capture no-hint baseline for success/error/denial | W1/wire/RAW-BASE.json (JSON-RPC response capture); carrier-matrix.csv row |
| M-META | META envelope with nonce/hash; FastMCP result metadata API | Native metadata preserved on wire without added model-visible assumption | W1/wire/M-META.json; event layer server_sent or lower; carrier-matrix row |
| M-TEXT | TEXT envelope; same baseline result | Additional text block does not break structured payload or text/error contract | W1/wire/M-TEXT.json; comparative baseline diff; carrier-matrix row |
| M-STRUCT | STRUCT envelope and frozen tool output schema | Additive structured field allowed only by existing schema; otherwise REFUTED or BLOCKED | W1/wire/M-STRUCT.json or W1/unsupported/M-STRUCT.json (JSON diagnostic); carrier-matrix row |
| M-ERROR | Invalid argument, denied tool, ToolError, raised exception | No false success, no leaked hint on deny, exact error parity | W1/wire/M-ERROR.json (array of redacted cases); carrier-matrix row |
| M-SURFACES | Modern server/discover and legacy initialize synthetic requests | No tool-list/schema visibility regressions across supported protocol eras | W1/wire/M-SURFACES.json (requests/responses); carrier-matrix row |
| M-RELOAD | Same synthetic fixture before/after new MCP request/session/server restart | Identify truly durable and ephemeral state; avoid false context persistence claims | W1/wire/M-RELOAD.json (time-ordered state/result pairs) |
| M-COMPAT | Golden job_status/run_command tool payload and exact eight-tool inventory | Legacy clients preserve fields and visibility with no hints by default | W1/wire/M-COMPAT.json (hash/field comparison); carrier-matrix row |

W1 cannot score actual MODEL_VISIBLE. W5 is the sole owner of that observable fact.

## W2 — session provenance and isolation (Claude opus, high)

W2 common input: inputs/W2.input.json, three synthetic chat streams and identity variants, Binnacle logging/identity source, **sanitized** request examples; output W2/model-selection.json, results.json, findings.md, evidence-index.json, events.jsonl, identity-matrix.csv, identity-provenance.md.

| Scenario | Scenario-specific input | Expected test | Mandatory raw output / format |
| --- | --- | --- | --- |
| I-ERAS | Modern and legacy synthetic request envelopes | Distinguish transport session, client name, turn and chat identity | W2/identity/I-ERAS.json (key provenance observations) |
| I-HEADERS | Synthetic X-Request-Id / X-OpenAI-Session permutations | No assumed authenticated identity from a hash or arbitrary header | W2/identity/I-HEADERS.json |
| I-TURN | 90 total interleaved A/B/C synthetic calls | Stable authorized grouping and correct owner association | W2/identity-matrix.csv 90 call rows; W2/identity/I-TURN.json summary |
| I-SPOOF | Forged, removed, reused, malformed and conflicting markers | All untrusted cases fail closed, zero unsolicited cross-chat hints | W2/identity/I-SPOOF.json (counterexample evidence) |
| I-RECONNECT | Reconnect and test server restart snapshots | Record what is stable versus only transport-local | W2/identity/I-RECONNECT.json |
| I-AUTH | Source trace from caller identity to authenticated boundary | Clear TRUSTED / UNVERIFIED / UNAVAILABLE verdict with proof | W2/identity-provenance.md (diagram + evidence refs) |
| I-LEAK | Cross-chat job-ID guess/reuse and wrong owner | Zero cross-chat unsolicited reminders | W2/identity/I-LEAK.json + identity-matrix.csv |
| I-REAL | W5's already specified three-chat observation keys (not W5 runtime results) | Define protocol-visible correlation fields and missing-data rules | W2/identity/I-REAL.json (expected observation schema mapping) |

W2 has no dependency on W5's results. W5 independently tests actual UI behavior; supervisor joins both later.

## W3 — result receipt, Drop and replay (Codex gpt-6-astra, xhigh)

W3 common input: inputs/W3.input.json; synthetic append-only spool with page/cursor reference hashes, pinned current job_status implementation and contract. Output W3/model-selection.json, results.json, findings.md, evidence-index.json, events.jsonl, receipt-transitions.csv and receipt-verdict.json.

| Scenario | Scenario-specific input | Expected test | Mandatory raw output / format |
| --- | --- | --- | --- |
| R-STATE | J-OK/J-FAIL/J-QUIET/J-UNKNOWN state transitions | Distinguish running, terminal success/fail and unknown | W3/receipt/R-STATE.json (state-transition trace) |
| R-UNFETCHED | Completed-but-unread synthetic job + repeated unrelated calls | Reminder eligibility persists until defensible receipt; running stays eligible | W3/receipt/R-UNFETCHED.json |
| R-CURSOR | Multi-page, cross-job, invalid, UTF-8 split and cursor=end fixtures | No false acknowledgement while has_more=true; no missed bytes | W3/receipt/R-CURSOR.json (byte ranges and hashes) |
| R-REPLAY | Previously read/pruned and unpruned job variants | Full retained result remains rereadable by ID after receipt | W3/receipt/R-REPLAY.json |
| R-LOSS | Missing HTTP response, mid-tool failure and retry fixtures | Server-served != client-received; preserve unread state if uncertain | W3/receipt/R-LOSS.json (served/delivered distinctions) |
| R-ACK | Three candidate semantics: server fetch, next-call proof, explicit receipt | Decide exactly which receipt transitions are defensible | W3/receipt/R-ACK.json; receipt-verdict.json (candidate verdicts) |
| R-ISOLATION | Independent cursors/receipts for A/B/C readers | No cross-reader consumption or global receipt collision | W3/receipt/R-ISOLATION.json |
| R-RETENTION | Expired data, concurrent writes, restart, disk error | Conservative fail-closed receipt; no fabricated successful read | W3/receipt/R-RETENTION.json |

Every state transition is also one row in receipt-transitions.csv. A negative result proving that implicit ACK is insufficient can be a successful test but must mark the implicit-ACK hypothesis REFUTED.

## W4 — performance, tokens, capacity (Claude sonnet, medium)

W4 common input: inputs/W4.input.json; frozen CONTROL/META/TEXT/STRUCT carriers and fixture cohorts 0/1/10/100; no dependency on W1 outputs. Output W4/model-selection.json, results.json, findings.md, evidence-index.json, events.jsonl, latency-samples.csv and metrics.json.

| Scenario | Scenario-specific input | Expected test | Mandatory raw output / format |
| --- | --- | --- | --- |
| P-BASE | CONTROL cohort of 0/1/10/100 jobs | Baseline local response latency and bytes | latency-samples.csv baseline rows |
| P-CARRIERS | Frozen META/TEXT/STRUCT variants, same fixture payload | Matched randomized candidate/control trial blocks | latency-samples.csv carrier rows |
| P-SIZE | 0/1/10/100 cohort, long IDs and unicode | Hint bytes ≤512, bounded number of IDs, no stdout/paths | W4/perf/P-SIZE.json + samples |
| P-TOKENS | Rendered carriers and configured tokenizer | Exact count or labeled estimate, distinguish agent usage cost | W4/perf/P-TOKENS.json + metrics.json |
| P-LATENCY | At least 3 randomized baseline/candidate rounds and host load samples | P50/P95/P99 processing delta; P95 initial target ≤5ms when attributable | latency-samples.csv paired raw samples with pair_id; metrics.json signed nearest-rank percentiles |
| P-SCHEMA | Goldens and legacy/error/rejected tool requests | No behavior regressions or unauthorized hint | W4/perf/P-SCHEMA.json |
| P-LOAD | 100 synthetic jobs, pathological IDs and memory sizes | Bounded processing and memory; no full-spool read per normal call | W4/perf/P-LOAD.json + resource samples |

W4 must label noisy measurements INCONCLUSIVE rather than excluding them. All exact samples remain attached.

## W5 — real ChatGPT Chat mode (single Desktop operator)

W5 common input: inputs/W5.input.json; isolated synthetic app capability, fixed model/effort selection, 3 dedicated test chats, pre-registered trial schedule and frozen carrier variations. Output W5/model-selection.json, results.json, findings.md, evidence-index.json, events.jsonl, surface-capability.json, trials.csv and redacted synthetic tool/UI trace.

| Scenario | Scenario-specific input | Expected test | Mandatory raw output / format |
| --- | --- | --- | --- |
| U-CANARY | Launcher, supported Chat UI, harmless echo tool and nonce | Establish actual Chat mode, tool-call transport and pinned subject model | W5/surface-capability.json; W5/ui/U-CANARY.json |
| U-VISIBLE | CONTROL/META/TEXT/STRUCT nonce-bearing tool results | Distinguish server_sending, client_receiving and model_using each carrier | W5/ui/U-VISIBLE.json (per-carrier evidence), events.jsonl |
| U-RUNNING | Synthetic running job, unrelated read; no user status message | Continued independent work with minimal running hint | W5/ui/U-RUNNING.json |
| U-FINISHED | Fixture advance to completed, next unrelated tool result | Model voluntarily fetches correct job result and follows with useful tool call | W5/ui/U-FINISHED.json (causal call sequence) |
| U-ISOLATION | Separate A/B/C synthetic job ownership and interleaved UI calls | No cross-chat unsolicited reminder | W5/ui/U-ISOLATION.json |
| U-RECEIPT | Multiple result pages, lost-delivery synthetic arm, replay by ID | Does not prematurely acknowledge; retains output | W5/ui/U-RECEIPT.json |
| U-PAIR | 12 frozen paired baseline/candidate tasks *per viable carrier* | Per-arm and pair outcome; no hidden sample exclusions | W5/trials.csv (2 rows per pair) + W5/ui/U-PAIR.json |
| U-TURN-END | Synthetic job outlives current ChatGPT turn | Record no unsolicited wakeup without later MCP call | W5/ui/U-TURN-END.json |

If real Chat mode or explicit subject model pin cannot be verified, U-CANARY is BLOCKED and later cases are NOT_RUN; W5 still produces complete schema-valid results.json plus capability diagnostic. **Codex Desktop is not an allowed substitute** for Chat mode evidence.

## M0–M4 — supervisor-only read-only reconciliation

| Step | Input (exact format) | Processing | Output (exact format) |
| --- | --- | --- | --- |
| M0 admission | run-manifest.json, S0/preflight.json, fixture manifest and 5 input packets, hashes and CLI launch receipts | Verify single SHA/fixture/plan/model assignments and independent ownership; dispatch only | supervisor/dispatch-ledger.json (JSON IDs/status), do not edit worker inputs |
| M1 collection | Five WN/results.json and WN/evidence-index.json; case event files | Run structural and hash validation, verify terminal status or genuine blocked code | supervisor/collection-report.json (JSON schema validation and defects) |
| M2 reconciliation | Validated W1–W5 findings, W5 surface capability, cases/proof layers, CSV, raw evidence | Compare contradictions without altering any lane evidence | supervisor/reconciliation.md (Markdown with linked claim/evidence) |
| M3 gate decision | G0–G7 evidence, model/effort verification, subject model consistency, contradictions | Select GO TO IMPLEMENTATION PLAN / CONDITIONAL GO / NO-GO / INCONCLUSIVE | decision.json (manager-decision schema) |
| M4 user summary | decision.json, evidence indexes, worker terminal statuses | Provide one factual Chinese synthesis, not a test or implementation | MANAGER-SUMMARY.md (Markdown), supervisor archive index |

No worker may fill decision.json. The supervisor may produce the last five reporting artifacts but never edit or regenerate a worker test result to change its outcome.

## Failure and no-input rules

- Missing, malformed or hash-mismatched input packet: worker returns BLOCKED, cites INPUT_INVALID, performs no experiment.
- No effective selected model/effort proof: worker returns UNVERIFIED or BLOCKED, records MODEL_UNVERIFIED / MODEL_UNAVAILABLE; it does not silently run a default model.
- No supported real Chat mode surface: W5 returns BLOCKED/NOT_RUN cases; W1–W4 continue.
- Unsupported carrier: preserve attempted bytes and mark unsupported; never bypass output schemas or RPC transport.
- No data from upstream worker: **normal**, not a dependency. All five lanes consume only S0 frozen inputs.
- Worker exits without required output: M1 marks WORKER_OUTPUT_MISSING, does not infer success.
- Parser accepts file syntax but there is no reliable model/tool trace: G2 remains INCONCLUSIVE.
- Absent client receipt confirmation: G4 cannot claim implicit result acknowledgement.
- Any failed security isolation case: G3 FAIL/NO-GO. No silent downgrade of identity strictness.
