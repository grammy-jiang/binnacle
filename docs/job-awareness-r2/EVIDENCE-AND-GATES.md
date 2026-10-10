# R2 evidence requirements, decision gates and rollback

Status: SPECIFICATION; no R2 Worker has yet produced evidence.

## Evidence hierarchy

| Proof class | What it can establish | What it cannot establish |
| --- | --- | --- |
| Local object and mock | Code synthesized a result | MCP serialized or ChatGPT received it |
| Native MCP HTTP wire | Real server/client serialization and transport | ChatGPT Chat model used it |
| ChatGPT client tool trace | Connected Chat-mode client invoked a synthetic tool | Response necessarily received by model |
| Observed model behavior | Model called correct job-specific follow-up tool after nonce hint | Original user goal continued |
| Same-turn continuation | Meaningful later tool action after complete job result, same prompt | A terminated turn was awakened |

Every output must say exactly which boundary it reaches. An MCP result with _meta does not by itself prove that the model read that metadata. A 200 response served does not prove client receipt.

## Strict gates: G0–G7

| Gate | Exact passing criterion | Evidence owner |
| --- | --- | --- |
| G0 baseline / safety | Exact R1 SHA hashes, R2 plan SHA and fixture hash; separate worktrees, validated model/effort, no production mutations or cross-worker writing | R2-0 + F |
| G1 result and transport | At least one public/native FastMCP reminder carrier is wire-compatible on an isolated real transport, error/auth/schema parity intact, no unknown full-path blockers | A + D |
| G2 model-visible reminder | A real ChatGPT Chat client (not Codex Desktop/Work) calls the dedicated synthetic App and shows nonce-based actual model action, not self-report | E1 |
| G3 authenticated chat isolation | Verified authorization chain from authenticated user/client to the claimed per-chat owner; negative spoof/replay tests, zero leaked session-specific hints in both synthetic and authorized live three-chat observations | B + E2 |
| G4 receipt and replay | Defensible consumer-specific receipt (or approved no-ACK limitation) survives lost replies, partial pagination, concurrent consumers/restart, retained output unchanged by ACK; current server-fetch-only implicit ACK cannot be approved | C + E2 |
| G5 performance | Full middleware/loopback transport P50/P95/P99 incremental latency from paired samples, bounded ≤512-byte reminder, no unchecked memory/CPU amplification; exact tokens where possible and clearly labeled estimates otherwise | D |
| G6 end-user workflow effect | Real ChatGPT Chat correctly retrieves result and performs meaningful later tool call within the same active turn; 12 pre-registered pairs per viable carrier reported with all negative cases | E2 |
| G7 regression compatibility | Existing eight public Binnacle tools and visibility, schema, errors, lifecycle, restart behavior unchanged; verified no production service/config writes | A/B/C/D + F |

Provisional latency budget: **≤5 ms P95 incremental local processing** on a documented quiet host. This is an engineering feasibility budget, not a claimed production SLO. If D samples are noisy or incomplete, G5 INCONCLUSIVE; no selecting only favorable samples.

## Mandatory negative cases

- Chat A claiming a chat B header, forged/missing/reused X-OpenAI-Session and malformed turn ID; no hints without verified authorization.
- Two synthetic chats using the **same tunnel-level principal**. If a per-chat claim is still unavailable, no per-chat hints are emitted, regardless of otherwise valid same-client authentication.
- Result served by the server but socket closes before client decodes; cannot mark receipt ACK.
- Result has_more=true, lost page, duplicate cursor, client restart, terminal unknown, expired output and concurrent Job output writes; no false full-consumption ACK.
- Same retained result read again after consumer-specific acknowledgement; output must be byte-identical or retention error explicitly reported.
- Tool error, denied tool, output schema mismatch, legacy/current client negotiation; no status appended to unauthorized results.
- Meta result visible to app but not model; classify accordingly rather than claim G2 success.
- Codex Desktop interface only; cannot count as real ChatGPT Chat.
- ChatGPT turn is already over before next tool call; passive reminder cannot actively resume it.
- Missing/ineffective declared model or effort; no fallback.
- Disallowed plugin install, tunnel exposure or account connection; exact bounded blocker, not a fabricated PASS.

## Result format

All workers A/B/C/D/E0 and E1/E2 emit results.json compliant with schemas/r2-worker-result.schema.json:

- R2_RUN_ID and worker identity, immutable SHA fields, start/end, model requested/effective/verified, source and evidence hashes.
- Exactly one scenario entry per planned ID: expected, observed, PASS/FAIL/INCONCLUSIVE/BLOCKED/NOT_RUN, input references, raw evidence references, event IDs, proof layers, nullable blocking reason.
- Hypothesis verdict separate from scenario success: SUPPORTED, REFUTED, UNRESOLVED.
- Actual metrics with measurement methods, no fabricated tokens/cost.
- Indexed provenance under own exclusive result folder, including redacted tool logs and cryptographic hashes.

The supervisor writes only supervisor/collection-report.json, supervisor/contradictions.md, supervisor/decision.json and supervisor/FINAL-SUMMARY.md. It never changes an input packet or worker evidence to fix a failure. Missing results must be counted NOT_RUN/BLOCKED, not automatically FAIL or PASS.

## Production protection

All R2 probes must use synthetic tools and explicit port namespaces, never production Binnacle command tools, real user job spool, existing tunnels, plugin/account tokens, user chat logs, or real client cookies. Every disposable test endpoint has a named cleanup owner, teardown evidence and failure fallback; do not close unrelated user browser tabs or jobs.

R2 progress cannot authorize any production code commit, PR merge, deploy, release or restart. A passing R2 feasibility gate only enables planning a separate implementation with focused tests, final full suite and rollback.

## Decisions

- **GO_TO_IMPLEMENTATION_PLAN:** every critical gate supported with actual client, identity, receipt, compatibility and performance evidence, no cross-chat leakage.
- **CONDITIONAL_GO:** an explicitly narrowed architecture remains defensible but some assumptions are blocked; follow-up must be named and tested before implementation approval.
- **NO_GO:** a core required assumption fails (e.g. trusted chat ownership absent or server-only ACK selected) and cannot be safely bounded.
- **INCONCLUSIVE:** no supported real Chat mode connection, incomplete transport/measurement or key evidence absent.

These are experiment conclusions, not evidence that the feature has been built. A completed local worker is not the same as a confirmed production-ready design.
