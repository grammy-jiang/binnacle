# Evidence protocol, negative cases and decision gates

Status: **frozen proposed acceptance contract, not a record of execution**.

## 1. Evidence hierarchy

Each test may establish a different layer of fact. Never promote evidence from a weaker layer into a stronger one.

| Layer | What can actually be proven | What it does NOT prove |
| --- | --- | --- |
| Server generated | Middleware produced a candidate hint and a result object | The client saw it |
| Server sent | Serialized response/transcript contains hint nonce and tool reply | Transport delivered the reply |
| Client received | Authenticated test caller has the result or a subsequent action demonstrates reception | ChatGPT language model attended to it |
| Model used | Actual ChatGPT Chat-mode tool trace shows a job-specific fetch after hint | Model continued the original work |
| Workflow continued | Same still-active turn made a meaningful later tool call tied to the user's goal | The platform can wake a dead turn |

The synthetic test harness must log enough distinct events to differentiate these layers. A server's log saying 200/ToolResult is not a receipt acknowledgement. App-local display of _meta is not automatically model visibility.

## 2. Frozen scenario and evidence naming

RUN_ID is a unique per-campaign identifier. SOURCE_SHA and FIXTURE_SHA bind all five workers to the identical executable baseline and immutable synthetic input manifest; each worker returns its own worker hash.

Every worker writes under the run-scoped path:

~~~text
~/Projects/binnacle-job-awareness-results/RUN_ID/WN/
~~~

Required:

- results.json (machine-readable, validates against the schema below);
- findings.md (short factual interpretation, limitations, no production recommendation);
- evidence-index.json (paths, SHA-256, source class, redaction and permissions);
- one or more redacted raw evidence logs, captured fixtures, wire envelopes or trace excerpts.

Do not include access tokens, client secrets, raw Authorization or session header values, cookies, unrelated chat content, original command text from real user jobs, private tool outputs, or full unredacted account URLs in shared artifacts.

A recorded session key must be a carefully chosen non-reversible label with RUN_ID scope, not the original header value. A hash of a header is useful for equality evidence but does not convert it into an authenticated identity.

## 3. Minimum results.json shape

Worker authors create the actual JSON. The following is a normative example of its structure, not a completed report:

~~~json
{
  "schema": "binnacle-job-awareness-feasibility-worker-v1",
  "run_id": "RUN_ID",
  "worker": "W1",
  "assignment": "fastmcp-carrier",
  "source_sha": "EXACT_40_HEX",
  "fixture_sha256": "EXACT_64_HEX",
  "executor": {
    "surface": "codex-cli",
    "version": "MEASURED_VERSION",
    "model_requested": "EXPLICIT_MODEL",
    "effort_requested": "EXPLICIT_EFFORT",
    "model_effective": null,
    "effort_effective": null,
    "host": "raspberry-pi",
    "session_ref": "OPAQUE_WORKER_SESSION"
  },
  "started_at": "ISO8601",
  "finished_at": "ISO8601",
  "state": "INCONCLUSIVE",
  "scenarios": [
    {
      "id": "M-META",
      "status": "INCONCLUSIVE",
      "expected": "reminder travels on wire without schema drift",
      "observed": "verbatim factual result with evidence reference",
      "evidence_refs": ["wire-meta.json"],
      "duration_ms": 0,
      "blocking_reason": null
    }
  ],
  "metrics": {},
  "limitations": [],
  "artifact_index": "evidence-index.json"
}
~~~

Allowed worker and case states are **PASS**, **FAIL**, **INCONCLUSIVE**, **BLOCKED** and **NOT_RUN**. PASS requires scenario-local evidence; NOT_RUN is honest if a subset was not executed. The global worker state aggregates only its own assigned scenarios, not other workers or the programme decision.

Each evidence-index.json item records relative path, SHA-256, file size, evidence type, original source/transport, visibility layer, and whether content was redacted. Include host-local timestamp with offset and monotonic elapsed times where meaningful.

## 4. Immutable run preflight and code constraints (G0)

- Same exact baseline SHA across all lanes and latest approved source at start.
- All test fixtures, port namespaces and client identifiers unique per run.
- No accidental run against the production port/connector/spool. Evidence includes an explicit before/after production unit PID and basic health comparison **read-only**, collected by S0 setup/cleanup owner.
- No worker edits or pushes production source, master or existing release branches.
- No shared writable data or shared agent worktree; Desktop has one GUI owner.
- No source/fixture mutation after worker fan-out; a change requires a new run ID and fair A/B rebaseline.

G0 also requires the pinned model and effort per worker to be recorded and verified. If the runtime provider does not expose the effective configuration, record the limitation rather than silently assuming defaults. Any model/effort change during a ChatGPT A/B comparison invalidates that pair.

G0 failure prevents claiming a coherent cross-lane result, although independent negative findings can still be reported.

## 5. G1–G7 acceptance criteria

### G1 — Native FastMCP carrier/wire contract (W1)

At least one carrier must work with **documented/public FastMCP behavior**, maintain original tool schema, status/error semantics and unaffected result fields, and be preserved on the applicable wire. An additional text content block is acceptable only if it is actually allowed by MCP and does not alter the existing structured payload. Structured extensions that require violating an output schema fail. Metadata-only success is merely wire capability until W5 verifies model visibility.

Test normal success, tool error, validation rejection, visibility deny, multiple mounted tools and post-restart operation. Tests check raw wire, not just a Python function return.

### G2 — Verified ChatGPT Chat model visibility (W5)

First prove the GUI really drives ChatGPT **Chat mode** and invokes the isolated test app. For each carrier, place a unique nonce in that carrier only. Require proof distinguishing server sent, client received and model used. If _meta is visible only to the app, classify it MODEL_NOT_VISIBLE (a legitimate negative result).

A fully successful end-to-end sequence requires: model has valid reminder → independently calls result read with correct job ID → continues with at least one meaningful later tool call in the *same turn*, without another user prompt. Require this chain on at least three separately numbered synthetic tasks before treating the carrier as preliminarily viable. Report all 12 paired pilot outcomes, including failures.

### G3 — Identity and isolation (W2 + W5)

**Zero** cross-chat unsolicited reminders in all observed fixtures. Spoofed, missing, reconnected or contradictory metadata must be handled without leaking chat-specific jobs. The identity needed for production must be backed by a verified trust boundary, not an arbitrary unsafeguarded HTTP header. If that prerequisite cannot be proven, session-scoped Job Awareness is NO-GO even if reminders reach the model.

Do not weaken the rule to achieve continuity. A fail-closed no-reminder state is allowed for missing identity, with telemetry recording the reason.

### G4 — Receipt / replay safety (W3 + W5)

A receipt must mean something defensible about consumption or subsequent confirmed client action, not that the server attempted to send bytes. Partial pages do not count as full retrieval; a running job cannot be finalized from a temporary caught-up cursor. Client-visible lost reply, concurrent consumers, unknown state, prune/restart, idempotent re-read and output corruption scenarios must behave conservatively. The same retained result must remain addressable by ID after receipt.

If the preferred no-extra-ack-tool design cannot distinguish a lost terminal tool response from a genuinely delivered one, the result is **NO-GO for implicit receipt**. It may still support a separate CONDITIONAL GO architecture explicitly requiring a receipt signal. Do not invent success.

### G5 — Bounded performance and model cost (W4)

Provisional feasibility budgets to freeze before test: total incremental reminder ≤512 UTF-8 bytes per eligible tool response; P95 incremental local processing ≤5 milliseconds under a reasonably quiet, documented host; bounded CPU/RAM as job count rises 0/1/10/100. Samples need repeated randomized baseline and candidate passes, P50/P95/P99, token count source or estimate label and load measurements.

These are **engineering experiment thresholds, not validated production SLOs**. If host load cannot be controlled enough to attribute deltas, return INCONCLUSIVE with samples, not a fabricated PASS. Do not leak command, workdir or log_tail in compact reminders.

### G6 — Workflow benefit (W5)

Use 12 paired candidate/control tasks per carrier surviving canary. The following are descriptive metrics, not a confirmatory significance claim: model-initiated correct result fetch, same-prompt completion, premature handoff, successful continuation after result, elapsed wall, tool count and token cost. Pre-register pairing and randomized arm order. A candidate must demonstrate at least the three verified end-to-end chains in G2 and must show no obvious correctness or premature-handoff regression. If the paired pilot has heterogeneous or negative outcomes, mark INCONCLUSIVE/FAIL and recommend more tests rather than interpreting a small-sample point estimate as proof.

The next production decision would require a **separate, larger, pre-registered** same-prompt reliability/performance A/B gate. This plan does not declare that stage complete.

### G7 — Binnacle compatibility / operational isolation (W1–W4)

Eight public tools, original call signatures, default wire results, authorization/visibility, durable job lifecycle, cursor semantics, recording and error behavior remain intact. Auth-denied responses receive no private reminder. Synthetic tests do not write to production. A worker error or GUI app failure cannot restart the real Job Manager. Every disposable app/process has a teardown record.

## 6. Mandatory negative scenarios

These should fail the **unsafe behavior** and pass the containment requirement:

- forged/stale X-OpenAI-Session or reused turn key;
- unauthenticated or unsupported ChatGPT surface;
- a test Job created in B or C appearing unsolicited in A;
- _meta-only response that the model cannot consume;
- arbitrary tool exception, MCP protocol error and a denied tool call;
- finished job with has_more=true still fetching pages;
- terminal tool response lost before delivery;
- duplicate cursor read, concurrent cursor readers and repeated full retrieval;
- server restart between result serving and next trusted confirmation;
- log corruption/retention expiry or invalid cursor;
- 100 simultaneous synthetic jobs, enormous job names and uncontrolled hint size;
- a whole ChatGPT turn terminating before another MCP call (not proof of a wakeup capability).

## 7. Model/effort correctness

Use [MODEL-AND-EFFORT.md](MODEL-AND-EFFORT.md) and worker-manifest.json to verify each lane explicitly selected the intended model and effort. Record requested versus effective settings, runtime version, fallback/no-fallback, and any unavailable requested model. A model change produces a newly versioned assignment; an undetected or unreported change is not acceptable test evidence. W5's operator and ChatGPT subject are **different** settings and must be validated separately.

## 8. Cross-lane reconciliation

The supervisor joins results **only by RUN_ID, SOURCE_SHA and FIXTURE_SHA**. For any conflicting claims, publish both pieces of evidence and classify the integrated gate INCONCLUSIVE until the original owning workers explain the mismatch. The supervisor must not rewrite results.json, do an ad hoc live UI experiment or implement a fix.

Example conflicts that must remain explicit:

- W1 METADATA_WIRE_PASS vs W5 META_MODEL_NOT_VISIBLE: the system is not model-visible through that carrier.
- W2 SESSION_KEY_UNTRUSTED vs W5 two chats happened not to leak: G3 is not passed.
- W3 SERVER_FETCHED vs W5 model never got terminal reply: receipt was not confirmed.
- W4 latency unknown on a busy Pi vs W1 locally fast: performance is not established.
- W5 verified Codex Desktop only vs programme requires ChatGPT Chat: G2/G6 remain BLOCKED.

## 9. Final decision and independent limits

**GO TO IMPLEMENTATION PLAN** requires G0–G7 mandatory conditions, an actual ChatGPT Chat surface, independently verifiable evidence, a technically supportable receipt scheme, and no cross-chat leakage.

**CONDITIONAL GO** requires an explicit narrow scope (e.g., only a text carrier works; implicit receipt needs a later tool-call signal) and concrete additional experiment before feature design. It never authorizes production rollout.

**NO-GO** is required for unremedied identity leakage, absence of a model-visible compatible carrier, or receipt rules that would irreversibly lose output or falsely assert consumption. A BLOCKED Desktop surface is **INCONCLUSIVE**, not evidence that ChatGPT lacks the capability.

The report must distinguish proposal, proof of feasibility, implementation readiness, and production readiness. Only the first two are in scope here.
