# R1 Job Awareness — final investigation results and R2 handoff

**Status: R1 local investigations completed; overall feasibility INCONCLUSIVE.**
Investigation date: 10 October 2026 (Australia/Sydney).
Report compiled after all four local workers finished, using immutable R1 evidence and a read-only integrity recheck. This is the **R1 results report**, not the R2 plan or a production implementation report.

## 1. Purpose and baseline

The original user-visible failure was that ChatGPT could launch a long-running Binnacle Job, receive its Job ID, and end its own turn rather than continuing the user's authorized workflow and collecting the result. A durable server-side process surviving the MCP request is not proof of ChatGPT workflow continuity. Ordinary status polling should avoid busy loops, but the model must not forget outstanding jobs or require an avoidable user Status message while the active turn can still do useful work.

The candidate R1 architecture: a small job-awareness hint in a subsequent unrelated MCP response to the **same authorized ChatGPT conversation**, preferentially showing completed/unread jobs over running jobs, without embedding log data. A successful, defensible receipt would suppress subsequent reminders while preserving durable output and replay by Job ID.

An MCP response piggyback **cannot wake an already ended ChatGPT turn**. That is a separate scheduling/orchestration concern.

R1 frozen identifiers:

| Item | Pinned value |
| --- | --- |
| R1 Run ID | JA-20261010-174301-ead99b0c |
| Product/source commit | d61761356ee0fce8ea6d73b0c3043b4881c5645e (includes merged PR #18/#19) |
| R1 documentation commit | 62a677b83f5b3a34dddc7fd23595f00ffe89159a |
| R1 fixture SHA-256 | e1c35bda430a2e8e3794d51032cf827afec7bfa451887731918b7fd529970d41 |
| Original evidence directory | /home/grammy-jiang/Projects/binnacle-job-awareness-results/JA-20261010-174301-ead99b0c |
| User-authorized W2/W4 reassignment | revisions/codex-reassignment-v2/_revision/assignment-v2.json |
| Supervisor prior evidence summary | revisions/codex-reassignment-v2/supervisor/INTERIM-STATUS-20261010.md |

Original R1 S0 inputs and Job fixtures remained immutable. Claude Code authentication had expired; the user explicitly requested switching W2/W4 to Codex. The v2 assignment preserved the original input hashes and recorded two approved model/executor changes only.

The validation command for R1 revision is: python3 revisions/codex-reassignment-v2/_revision/validate_v2.py --worker Wn. W1, W2, W3, W4 all passed **structural/evidence consistency** checks. A structural PASS is **not** a proof that every investigated technical assumption is supported.

## 2. Experiment-by-experiment outcomes

| Workstream | Verified executor / effort | Scenario outcome | Feature hypothesis |
| --- | --- | --- | --- |
| W1 native FastMCP carriers, middleware, schema, errors | Codex gpt-6-astra / high | 5 PASS, 3 INCONCLUSIVE, total 8 | H1 UNRESOLVED |
| W2 session identity, trust, adversarial isolation | Codex gpt-6-astra / high | 8 PASS, total 8 | H3 UNRESOLVED for real Chat mode |
| W3 receipt, pagination, replay and failure injection | Codex gpt-6-astra / xhigh | 8 PASS, total 8 | H4 REFUTED for **existing server-fetch-based implicit ACK** |
| W4 performance, bytes, token and legacy compatibility | Codex gpt-6-sol / medium | 4 PASS, 3 INCONCLUSIVE, total 7 | H5 UNRESOLVED |
| W5 real ChatGPT Chat client | NOT RUN | BLOCKED | H2 model visibility and H6 workflow effect UNTESTED |

All four CLI executors recorded their effective model and reasoning effort from native local agent session metadata. R1 used installed FastMCP 4.1.0 and MCP/mcp-types 2.3.0 (not the older design baseline FastMCP 4.0.10); reports bind versions to actual evidence.

### W1 — Native FastMCP result carriers

R1 W1 demonstrated the following **inside synthetic local ASGI/HTTP and native SDK behavior**:

- An allowed metadata hint is serialized into the result's metadata without rewriting the normal content/structured payload.
- A separate text content block can carry a hint without replacing the existing original first text block.
- An extra structured result property can be emitted only when the existing output schema permits it; a closed schema forbids the extension.
- Error/denied-tool responses preserve their error contract and should never leak a private hint.
- Middleware-local state does not automatically survive process restart; per-request ContextVars must not be mistaken for durable ownership.

Limit: **no real ChatGPT Chat model visibility was demonstrated**. The external network/TCP/TLS/secure-tunnel/proxy and full default client matrix were not accepted, so full H1 remains UNRESOLVED.

W1 detailed evidence: W1/results.json, W1/carrier-matrix.csv, W1/findings.md and W1/evidence-index.json under the v2 evidence directory.

### W2 — Session identity and isolation

W2 executed 227 native synthetic FastMCP calls, including 180 interleaved calls across synthetic chat streams; **zero cross-chat unsolicited reminder leaks** occurred under a deliberately fail-closed *synthetic scoped-grant policy*. Negative tests covered malformed, forged and reused chat markers, reconnects, denied clients and guessed Job IDs.

Crucially, the actual inspected production authentication boundary recognizes a shared MCP/tunnel principal, **not an authenticated per-ChatGPT-conversation identity**. Request headers, hashed session strings and the client application name may be correlational signals but are not authorization proofs. Laboratory-supplied A/B/C authenticated grants were test constructs and do not exist in the observed production composition.

**Conclusion:** synthetic isolation implementation can be made safe, but H3 real-world authenticated chat ownership remains UNRESOLVED. Do **not** implement unsupervised per-chat Job reminders based solely on those headers.

W2 detailed evidence: W2/results.json, W2/identity-matrix.csv, W2/identity-provenance.md, W2/findings.md and W2/evidence-index.json.

### W3 — Receipt/replay semantics

W3 completed 75 passing assertions, 297 observed synthetic events and 129 receipt transitions. The experiments distinguished server-side serving from successful client receipt, handled partial pagination and lost replies, preserved output after replay and tested alternative confirmation schemes.

| Candidate acknowledgment | R1 conclusion | Why |
| --- | --- | --- |
| Existing server fetch or public cursor equals ACK | **REFUTED** | Server may return or lose a terminal reply before any client receives/decodes it; cursors are constructible and not consumer-bound |
| Next trusted call carrying a new unpredictable page proof | UNRESOLVED | Requires authenticated consumer identity, unforgeable page/generation/range proof and durable/idempotent persistence absent from current tool contract |
| Explicit receipt with authenticated per-consumer proof | Supported **only in synthetic ledger** | Complete contiguous output must be confirmed; output remains stored, replayable and unaffected by acknowledgment |

**Decision:** no extra ACK tool is not yet proven feasible. Do not silently mark a Job result consumed on successful server-side job_status. Distinguish a successful negative experiment from design approval.

W3 detailed evidence: W3/receipt-verdict.json, W3/receipt-transitions.csv, W3/results.json and W3/findings.md.

### W4 — Preliminary cost and performance

W4 executed 137 in-memory synthetic FastMCP calls (CONTROL, META, TEXT and STRUCT), with 0/1/10/100-job cohorts and repeated paired measurements. Its largest observed signed nearest-rank P95 **hint-rendering-only** increment was approximately 0.032148 milliseconds, with maximum hint 86 UTF-8 bytes under the proposed 512-byte bound.

These are encouraging scope-limited results but **do not measure** the complete installed production middleware path, external HTTP transport/TLS/Tunnel, real ChatGPT model-visible tokenization, or dollar cost. Its token estimates used emitted UTF-8 bytes as a conservative count proxy; this is not verified tokenizer output.

**Conclusion:** H5 remains UNRESOLVED. Do not infer a production performance SLO from the render-only test.

W4 detailed evidence: W4/latency-samples.csv, W4/metrics.json, W4/results.json and W4/findings.md.

### W5 — Genuine ChatGPT Chat experiment

**No genuine ChatGPT Chat test was executed.** The Pi's installed chatgpt launcher was found to resolve to a Codex launcher and does not establish traditional ChatGPT Chat behavior. No separate supported, authorized disposable ChatGPT test-plugin connection was proven. W5 has no results.json; it is BLOCKED rather than a failed successful experiment.

Consequently R1 does not demonstrate:

- Actual model visibility of result metadata/content in Chat mode.
- A voluntary result-fetch call in reaction to a reminder.
- Meaningful continuation of the original user's work in the *same active turn*.
- Real cross-conversation Job isolation with authenticated chat identity.
- True user-visible A/B impact on early handoff, completion and tool cost.

## 3. Gate assessment at R1 closure

| Gate | Outcome | What remains |
| --- | --- | --- |
| G0 input/provenance and isolation | PARTIAL PASS | Frozen R1 data and delegated-agent proof valid; E client surface not established |
| G1 FastMCP native compatibility | INCONCLUSIVE | External transport and complete product client compatibility |
| G2 real Chat model visibility | BLOCKED | Actual Chat mode model-visible nonce and tool trace |
| G3 trusted per-chat authorization | INCONCLUSIVE / NOT APPROVED | Real authenticated Chat conversation identity |
| G4 receipt safety | NO-GO for current implicit ACK | Authenticated explicit or new proof-bearing later call |
| G5 overhead | INCONCLUSIVE | Full transport/middleware and correct token accounting |
| G6 workflow continuation | BLOCKED | Genuine Chat same-prompt paired pilot |
| G7 complete source/runtime regression | INCONCLUSIVE | External client, default tools and post-prototype full-path checks |

Overall research decision: **INCONCLUSIVE — DO NOT IMPLEMENT OR DEPLOY Job Awareness YET**. The R1 experimental lanes have ended, but the feature's key product and security assumptions have not passed.

## 4. Durable evidence integrity

The exact R1/v2 JSON outcome hashes from read-only verification:

| Lane | results.json SHA-256 | evidence-index.json SHA-256 |
| --- | --- | --- |
| W1 | c7261eb622b3ef1014ca3859f0eaf4a3dffd8cfc3b2d0de0936d5fe9e7d1911f | 4a31df18d3bce95dc3fc1061ef3605418a111e64b19a7a6a88c2de848efa6373 |
| W2 | 1145b56afbb1a30b4fbc874675ae2d77aaa0d6eb218e309aac1a3f9f4262de00 | ec4f31f140e2202ca7558d8d118000d07489511cb371c1a136b5508c5a429517 |
| W3 | ec8e901c59b138adc6f0d924a73c1a9b758b48910db45190a117718b8184168d | 9b7b2febdb116a7dff024c55b7a7aca199d33bfef7f8425957754336e6924652 |
| W4 | 6e547db360c39d0158c72fd40d52d993bc907013e2e8a133de9af53497a16b99 | 4e8d9824208f74640162cff046c9a36041a5016a981870de8748f97fe0ef44c9 |

The interim supervisor report SHA-256 is d62221e598505782bb137ff831a5bfaab07ec801ed2be2872ea2049a672d2b24. These references are local Pi evidence files, not claims that raw proprietary input or user credentials were uploaded to GitHub.

Structural validation for frozen R1 S0 and revised W1–W4 returned PASS. This report adds no new R1 worker experiments.

## 5. Exact next stage

Proceed to **R2 targeted feasibility**, not production feature code:

- **R2-A:** verify a separate supported true ChatGPT Chat custom MCP connection and test-only app permissions.
- **R2-B:** discover or design an authenticated per-chat Job ownership boundary and test fail-closed alternatives.
- **R2-C:** evaluate explicit receipt versus later-trusted-call opaque proofs under real failure/restart/page conditions.
- **R2-D:** measure actual local end-to-end HTTP/native MCP compatibility and latency, with bounded hints.
- **R2-E:** real Chat model-visible canary and only then randomized behavior/isolation pairs under B/C safety gates.
- **R2-F:** read-only independent synthesis and new Go/No-Go decision.

R2 should be highly parallel: A/B/C/D and offline E0 share only one immutable R2-0 frozen input bundle. The real Chat endpoint requires independently verified account/plugin authorization. Execution models and efforts remain explicit, not default-selected. A finished R2 feasibility study still does not authorize a feature commit or production deploy.

**Boundary:** The R1 study and report are complete; Job Awareness functionality is not implemented or production validated.
