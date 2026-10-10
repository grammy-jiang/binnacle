# Artifact formats and exact Input → Output contracts

Status: PRE-EXECUTION DOCUMENTATION. This defines **file formats**, independent of whether an experiment passes. Paths are relative to RUN_ROOT = ~/Projects/binnacle-job-awareness-results/RUN_ID.

## 1. File map, authoritative schema and producer

| File or pattern | Exact format | Producer | Consumer | Required role |
| --- | --- | --- | --- | --- |
| run-manifest.json | UTF-8 JSON, schemas/run-manifest.schema.json | S0 | all workers, supervisor | Bound RUN_ID, source/docs/fixture hashes and W1–W5 packet hashes |
| fixtures/fixture-manifest.json | UTF-8 JSON, schemas/fixture-manifest.schema.json | S0 | all workers | Immutable nonces, mock job lifecycles, carrier variants and A/B arm order |
| fixtures/payloads/* | UTF-8 or bytes, size and SHA-256 in fixture index | S0 | all workers | Synthetic input only; no real user data |
| S0/preflight.json | UTF-8 JSON, schemas/s0-preflight.schema.json | S0 | supervisor, workers | Capability/resource and model preflight, outcome |
| S0/provenance.json | UTF-8 JSON object | S0 | supervisor | Exact versions, source/plan commit and inspected transport |
| S0/resource-ledger.json | UTF-8 JSON array | S0 | W5, supervisor | Owner/resource/run-scoped IDs and explicit teardown |
| S0/readiness.md | UTF-8 Markdown | S0 | supervisor | Human-readable readiness explanation and blocked prerequisites |
| inputs/Wn.input.json | UTF-8 JSON, schemas/worker-input.schema.json | S0 | Wn ONLY, supervisor | Frozen standalone input and output manifest, model/effort request |
| Wn/model-selection.json | UTF-8 JSON, schemas/model-selection.schema.json | Wn | supervisor, G0 | Required startup model and effort evidence; operator/subject separate for W5 |
| Wn/results.json | UTF-8 JSON, schemas/worker-result.schema.json | Wn | supervisor | One case outcome per planned scenario; hypothesis verdicts separate |
| Wn/findings.md | UTF-8 Markdown | Wn | supervisor | Factual readout with limits/contradictions, no combined Go/No-Go |
| Wn/evidence-index.json | UTF-8 JSON, schemas/evidence-index.schema.json | Wn | supervisor | Every raw artifact hash, size, evidence layer and redaction status |
| Wn/events.jsonl | UTF-8 JSON Lines, one event per line, schemas/event.schema.json | Wn | supervisor | Causal step trace (server sent ≠ client received) |
| W1/carrier-matrix.csv | UTF-8 CSV, exact columns §4 | W1 | G1/G7 | Carrier and error/contract truth table |
| W1/wire/*.json | UTF-8 JSON recorded request/response pair with sanitized values | W1 | G1 | Real raw wire fields and baseline diffs |
| W2/identity-matrix.csv | UTF-8 CSV, exact columns §4 | W2 | G3 | 90+ mock calls, spoof and leakage outcomes |
| W2/identity-provenance.md | UTF-8 Markdown | W2 | G3 | Trust-boundary proof, not guessed headers |
| W2/identity/*.json | UTF-8 JSON testcase traces | W2 | G3 | Identity/authorization negative evidence |
| W3/receipt-transitions.csv | UTF-8 CSV, exact columns §4 | W3 | G4 | Every simulated state/receipt transition |
| W3/receipt-verdict.json | UTF-8 JSON, contract §5 | W3 | G4 | Explicit/implicit ack variant verdicts |
| W3/receipt/*.json | UTF-8 JSON byte/cursor trace | W3 | G4 | Lost response, re-read and failure proof |
| W4/latency-samples.csv | UTF-8 CSV, exact columns §4 | W4 | G5 | Raw order-preserving benchmark samples |
| W4/metrics.json | UTF-8 JSON, contract §5 | W4 | G5 | Percentiles, size/token/count and noise classification |
| W4/perf/*.json | UTF-8 JSON test snapshots | W4 | G5/G7 | Host load, wire cost, regression cases |
| W5/surface-capability.json | UTF-8 JSON, schemas/desktop-surface.schema.json | W5 | G2/G6 | Product surface and actual model selection proof |
| W5/trials.csv | UTF-8 CSV, exact columns §4 | W5 | G6 | Each A/B arm as an independent observation |
| W5/ui/*.json | UTF-8 JSON with supported UI and MCP event references | W5 | G2–G4/G6 | Real Chat mode actions, redacted; no private screenshots in Git |
| supervisor/dispatch-ledger.json | UTF-8 JSON object | supervisor | manager audit | Worker process/session IDs and immutable input hashes |
| supervisor/collection-report.json | UTF-8 JSON object | supervisor | manager audit | Schema, references, SHA and sample validation results |
| supervisor/reconciliation.md | UTF-8 Markdown | supervisor | G0–G7 | Conflicts and reconciled interpretations |
| decision.json | UTF-8 JSON, schemas/manager-decision.schema.json | supervisor | final user report | G0–G7 with evidence-linked conclusion |
| MANAGER-SUMMARY.md | UTF-8 Markdown | supervisor | user | One concise Chinese management report |

All JSON files use object keys as documented, UTF-8, no comments, and no duplicate keys, NaN or Infinity. All CSV files use comma delimiter, double-quote escaping, UTF-8 headers, actual newlines. All JSONL files contain exactly one JSON object per line with a unique event_id.

Do not record source credentials or real user data. In public documentation report only sanitized excerpt paths; test results may be retained privately in restricted RUN_ROOT.

## 2. S0 outputs and Wn exact input packet

The single **run-manifest.json** is the root of trust for evidence *consistency*, not a substitute for authentication. It freezes:

- run_id: JA-prefixed unique identifier;
- source_sha, docs_sha: exact 40-character commits (source and the present plan);
- fixture_sha256: SHA-256 of the exact, complete fixtures/fixture-manifest.json file bytes, not merely a field inside it;
- frozen_at: timezone-aware RFC3339 time;
- worker_inputs.W1...W5 each with path and SHA-256 of exact input packet bytes;
- s0_preflight_path and desktop_app_status (READY, UNVERIFIED or BLOCKED).

**Worker-input.json** is the authoritative per-lane handoff. It must contain:

- identical run_id/source_sha/docs_sha/fixture_sha256 to the run manifest;
- specific worker ID, scenario IDs, and structured lists of input refs, each with a format and SHA-256 when immutable;
- outputs array listing *all required expected results* (common results/events/index, plus lane-specific matrix or evidence);
- exact model_request.model and model_request.effort, fixed by worker-manifest.json (W5 also includes subject_request.surface/model/effort);
- immutable file/worktree/result paths, time/cost cap and permissions. A worker cannot broaden permissions or add a new test case after the packet is frozen.

For W5, inputs may specify a private app reference without exposing credentials. A non-available app has explicit capability BLOCKED and produces a blocked result packet; it cannot be omitted without an explanation.

### S0 per-step readiness rule

- PREPARED: immutable packets/fixtures ready; W1–W4 can start and W5 app ready if available.
- PARTIAL: packets/fixtures ready but Desktop connection or a noncritical capability blocked. The four CLI lanes may start.
- BLOCKED: core source/fixtures/input packets invalid or unsafe; do not launch.
- No environment model is inferred from defaults. S0 itself must show its explicitly selected model/effort and verified effective configuration.

An S0 worker packet does not contain W1's findings or any prior Wn result; this is what guarantees parallel independence.

## 3. Common W1–W5 terminal output: results.json

Schema: schemas/worker-result.schema.json. **One row per scenario ID is mandatory.** The file contains:

| Field | Type | Meaning |
| --- | --- | --- |
| schema | constant job-awareness-worker-result-v1 | Versioned output API |
| run_id, worker | string, W1–W5 | Identity |
| source_sha, docs_sha, fixture_sha256, input_sha256 | fixed hash strings | Verify frozen inputs and exact worker packet |
| started_at, finished_at | RFC3339 strings | Actual working period |
| executor.surface, version, session_ref | strings | Real executor, never inferred from binary path |
| executor.model.requested_model, requested_effort | strings | Exact plan choices |
| executor.model.effective_model, effective_effort | nullable strings | What runtime actually used; null is not a PASS |
| executor.model.verification | VERIFIED/UNVERIFIED/UNAVAILABLE | Runtime proof quality |
| executor.model.verification_evidence_ref | nullable relative path | Supporting CLI/UI event |
| executor.model.fallback_used | boolean | Unauthorized fallback is a gate failure |
| subject | null or separate surface/model object | Only W5 uses a ChatGPT **subject** distinct from operator |
| state | PASS/FAIL/INCONCLUSIVE/BLOCKED/NOT_RUN | Terminal worker-level evidence quality |
| hypotheses | map H1–H6 to SUPPORTED/REFUTED/UNRESOLVED | Actual feasibility finding, not test status |
| scenarios | array | Exact configured cases (including blocked cases), no extras or duplicates |
| metrics | object | Lane metrics; never fabricated defaults |
| limitations | list of strings | Unverified and unavailable observations |
| artifact_index | constant evidence-index.json | Proof manifest |

Before that results object, the worker emits model-selection.json with requested/effective model and effort, both match-verification booleans, selector evidence references and a redacted explicit launch command. This startup receipt must match the final results.executor.model (and W5 results.subject.model) exactly.

Every scenarios entry contains case id, status, expected statement, observed statement, input_refs, evidence_refs, event_ids, proof_layers, nullable duration_ms and nullable blocking_reason.

**Interpretation:** A test can PASS because it successfully shows that an implicit acknowledgement method is impossible; that scenario's hypothesis then becomes REFUTED. Do not conflate PASS of a test with SUPPORT of the design.

A PASS or FAIL scenario requires actual evidence_refs and linked events; a BLOCKED/NOT_RUN scenario requires a nonempty blocking_reason and observed explanation. If no valid requested model is available, report BLOCKED/UNAVAILABLE rather than silently selecting an unlisted model.

## 4. Exact per-lane CSV columns and types

CSV files are **raw observations**, not independently authored conclusions. Header order is fixed; blank fields are allowed **only** for values legitimately unavailable, and must be justified in findings.md. Numeric fields use decimal dot, booleans are the lowercase literals true/false, never yes/no/1/0. Missing numeric values are empty, never 0.

| File | Exact ordered header columns |
| --- | --- |
| W1/carrier-matrix.csv | case_id,carrier,protocol_era,wire_valid,schema_preserved,error_semantics_preserved,model_visibility,trace_ref |
| W2/identity-matrix.csv | case_id,call_index,claimed_chat,verified_chat,identity_source,trust_level,expected_hint_ids,actual_hint_ids,leak,trace_ref |
| W3/receipt-transitions.csv | case_id,step_index,job_id,consumer_id,from_state,event,to_state,server_served,client_received,has_more,acknowledged,cursor_start,cursor_end,trace_ref |
| W4/latency-samples.csv | sample_id,case_id,pair_id,cohort_jobs,carrier,arm,round_index,wall_ms,processing_ms,returned_bytes,reminder_bytes,token_count,token_method,cpu_pct,ram_bytes,host_load,trace_ref |
| W5/trials.csv | trial_id,pair_id,carrier,arm,arm_order,chat_label,surface,subject_model,subject_effort,model_verified,server_sent,client_received,model_used,correct_fetch,fully_drained,meaningful_followup,same_prompt_completed,premature_handoff,elapsed_ms,tool_calls,reminder_bytes,token_count,trace_ref |

Detailed field conventions:

- arm is CONTROL/CANDIDATE. W5 requires exactly 2 rows per pre-registered pair for each viable carrier; each matching pair uses the same fixed subject model/effort and same frozen fixture.
- cohort_jobs is one of 0, 1, 10 or 100. W4 must include all cohorts for each supported carrier and CONTROL. sample_id/trial_id unique. For paired latency trials, pair_id is identical between candidate and control within (carrier, cohort_jobs, round_index); for the separate standalone P-BASE samples it may be empty.
- carrier is META, TEXT or STRUCT for experiments, CONTROL for no-hint baseline. A carrier marked unsupported is still reported (wire test result and absence of genuine live trials).
- trace_ref is always a safe relative file reference present and hashed in evidence-index.json.
- expected_hint_ids/actual_hint_ids are pipe-separated opaque synthetic IDs, never raw client headers.
- unknown client receipt is an empty client_received, **not** false. False is reserved for positively observed non-delivery.
- model_visibility has one of MODEL_VISIBLE / MODEL_NOT_VISIBLE / NOT_TESTED / INCONCLUSIVE. W1 cannot claim MODEL_VISIBLE.
- token_method is MEASURED / ESTIMATED / UNAVAILABLE; when UNAVAILABLE token_count must be empty.
- a PASS requires raw rows; no invented medians or missing samples silently dropped.

## 5. Additional special result objects

### W3/receipt-verdict.json

UTF-8 JSON object validated by schemas/receipt-verdict.schema.json, with fields: run_id, worker=W3, cases (list of case IDs), variants (array of name SERVER_FETCH / NEXT_TRUSTED_CALL / EXPLICIT_RECEIPT; status SUPPORTED/REFUTED/UNRESOLVED; necessary_assumptions list; counterexample_refs list), recommended_transition (string or null), outstanding_uncertainties list. This object is an evidence-backed design feasibility output, not a production API.

### W4/metrics.json

UTF-8 JSON object validated by schemas/metrics.schema.json, with run_id, worker=W4, cohorts (0/1/10/100), carriers; per-carrier sample_count, p50_ms/p95_ms/p99_ms incremental time nullable numbers, bytes distribution, token_method and token counts, host_load_details, inconclusive_reason nullable. Must be derived from latency-samples.csv, not manually chosen. A candidate/control pair is keyed by (carrier, cohort_jobs, round_index, pair_id). Its **signed** incremental local processing time is candidate.processing_ms minus control.processing_ms; negative is an improvement and is valid. For each carrier/cohort, sort those signed deltas and use the **nearest-rank** percentile at ranks max(1, ceil(p/100 * N)) for P50/P95/P99. The metrics.sample_count is the number of complete pairs, never the number of raw rows. W4 must retain all raw trials and record load/noise limitations. The validator recomputes these values rather than trusting the agent's summary.

### W5/surface-capability.json

Schema: schemas/desktop-surface.schema.json. Explicit surface enum VERIFIED_CHAT_MODE / VERIFIED_CODEX_DESKTOP_ONLY / VERIFIED_WORK_ONLY / CHAT_MODE_NOT_VERIFIED / SURFACE_UNAVAILABLE; launcher, operator model/effort verification, distinct ChatGPT subject model/effort verification, nonce_verified and chat_mcp_tool_invoked. Codex Desktop-only is not a genuine Chat mode PASS.

### W5/ui/{scenario}.json and W1–W4 trace files

These must validate against schemas/trace.schema.json and contain run_id, worker, scenario_id, kind, input_refs, ordered redacted event_ids, time-ordered records and a nullable blocker. Each trace is evidence, not an assertion of a successful step. A negative trace explicitly identifies the failed or missing boundary.

### Events and evidence-index.json

- Wn/events.jsonl: each line strictly validates against schemas/event.schema.json; mandatory unique event_id, scenario_id, proof layer and event time. Link raw evidence by raw_artifact_ref and response_sha256. An event claiming CLIENT_RECEIVED should have separate client-side evidence from SERVER_SENT.
- Wn/evidence-index.json: lists files beneath Wn only, never absolute paths, symlinks, parent-directory escapes, real secrets or external URLs. Each artifact gets actual file SHA-256, byte count, MIME type, proof layer, redacted and privacy_checked flags.
- Wn/results.json references event_ids and evidence_refs that must resolve to those files. Neither results.json nor evidence-index.json is indexed by itself, avoiding cyclic hashes. model-selection.json is an ordinary indexed artifact. Model selection proof links must point to an indexed raw selector trace if verified.

## 6. Supervisor-only outputs (never written by workers)

- supervisor/dispatch-ledger.json (schemas/dispatch-ledger.schema.json): per lane worker_input_sha256, explicitly chosen model/effort, observed process ID or worker session, exact workspace, start and terminal code/time, note whether W5 Chat mode was confirmed.
- supervisor/collection-report.json (schemas/collection-report.schema.json): per file schema/JSONL/CSV/hash checks and missing/unverified evidence list; separate structural PASS from factual verification.
- supervisor/reconciliation.md: one row for each contradictory claim: worker/case, stronger/weaker evidence and unresolved fact.
- decision.json: schemas/manager-decision.schema.json with G0–G7 PASS/FAIL/INCONCLUSIVE/BLOCKED/NOT_RUN, evidence refs, worker status, decision and production_authorized=false.
- MANAGER-SUMMARY.md: concise Chinese synthesis with RUN_ID/SHA, per-worker summaries, actual model and effort, G0–G7 gates, observed benefits/costs and limits.

A manager may perform read-only validation and write these **management results** but must never edit W1–W5 test artifacts.

## 7. Structural checks versus real-world truth

Machine validation checks exact schema, required scenarios, cross-file hashes, numeric ranges, CSV pairing, known input versions, model/effort provenance fields, trace references, and declared stage/proof layer. It cannot certify that a screenshot is a genuine ChatGPT Chat window, that a vendor model selector really honored an effort level, or that a response reached a language model. Those remain **evidence conclusions** requiring W5's independent runtime traces and manager review.

Do not mark GO solely because the Python validator exits 0. Never treat ChatGPT Work, Codex Desktop or API-based simulations as Chat mode observations.
