# Binnacle Job Awareness — R2 targeted feasibility investigation

Status of this document's **originally frozen test specification**: planned on 2026-10-10. The sealed operational R2 run uses the exact original docs SHA cc386613a20f14cd466f19d0fbd3e38ec6ce9927; these later explanatory/report changes do **not** alter worker input packets, fixtures, or the required models/efforts.

The [R1 completed investigation report](https://github.com/grammy-jiang/binnacle/blob/50cca28695dce8b2f11810b92aa792179b0e9eb4/docs/job-awareness-feasibility/R1-INVESTIGATION-RESULTS.md) is now the authoritative previous-round outcome. See the [R1 → R2 evidence handoff](R1-EVIDENCE-HANDOFF.md) and the [completed R2 local investigation results](R2-RESULTS.md) for confirmed local outcomes and blocked real-client gates; do not mistake this static planning baseline for current process status.

## What R2 is, and what it is not

R1 tested feasibility before implementation; it was not a completed Job Awareness feature. R1 four CLI workers ended, their evidence was validated, and genuine ChatGPT Chat testing W5 did not occur. This **new R2 stage** closes specific evidence gaps. It neither repeats the R1 research nor implements the production feature.

### Immutable R1 inputs

| Worker | What R1 proved | Still unknown |
| --- | --- | --- |
| W1 native FastMCP carriers | Metadata and added text work in native ASGI serialization; structured extension is output-schema-dependent | Real external TCP/TLS/ChatGPT consumption; overall H1 UNRESOLVED |
| W2 per-chat ownership | 227 synthetic native calls, 180 interleaved, zero leaks with *lab-only* fail-closed ownership rules | Authenticated stable ChatGPT Chat identity; H3 UNRESOLVED |
| W3 result receipt | 8/8 synthetic tests PASSED; current server-fetch/cursor-only implicit ACK assumption REFUTED | Safe per-client explicit or future-call receipt bound to delivery |
| W4 performance | 137 in-memory calls; max measured render-time incremental P95 about 0.032148 ms and hint 86 bytes | Full MCP transport and middleware overhead, real model token cost; H5 UNRESOLVED |
| W5 live ChatGPT behavior | Not run | Model visibility, workflow continuation, real three-chat isolation; H2/H6 NOT TESTED |

Immutable product source SHA: d61761356ee0fce8ea6d73b0c3043b4881c5645e.
R1 docs SHA: 62a677b83f5b3a34dddc7fd23595f00ffe89159a.
R1 fixture SHA256: e1c35bda430a2e8e3794d51032cf827afec7bfa451887731918b7fd529970d41.
R1 Run ID: JA-20261010-174301-ead99b0c.
Original evidence path: /home/grammy-jiang/Projects/binnacle-job-awareness-results/JA-20261010-174301-ead99b0c.
Consolidated report: revisions/codex-reassignment-v2/supervisor/INTERIM-STATUS-20261010.md.
Original plan: [R1 Job Awareness](../job-awareness-feasibility/README.md).

Never modify original R1 frozen packets, results, or evidence. Every R2 worker reads a read-only snapshot and writes to an exclusive new R2 directory.

## Exactly what we investigate

**R2-A — Independent ChatGPT Chat MCP test connection.** Validate a supported private, synthetic, read-only MCP server and safe connection using official Plugins custom MCP or Secure MCP Tunnel routes. Prove account/workspace/UI support and a real Chat mode tool call if possible; otherwise give exact human-action-needed or blocked verdict. Do not connect a new account/plugin on the user's behalf without required action.

**R2-B — Trusted conversation ownership.** Find out if per-chat identity comes from an authenticated boundary; if not, test narrower explicit capability or authenticated per-user scope, and mark automatic per-chat unsolicited reminders NO-GO unless a sufficient trust boundary is demonstrated. Do not promote clientInfo, X-Request-Id, or X-OpenAI-Session hashes into authorization.

**R2-C — Receipt, pages and durable replay.** Independently test a consumer-authenticated, unpredictable proof or explicit receipt through lost transport replies, result pagination, multiple readers, server restart, unknown/failed jobs and byte-level replay. Do not treat server fetch as delivered content. No real user job outputs.

**R2-D — Full path wire, compatibility and performance.** Extend W1/W4 local data with isolated localhost TCP/HTTP and native FastMCP transport tests, exact legacy/current protocol result/error behavior, bounded reminder cost and measured latency distributions. Distinguish synthetic render time from complete RPC time, and measured tokens from estimates.

**R2-E — Genuine ChatGPT Chat model behavior.** At least one supported read-only test app/tool connected to a new genuine ChatGPT Chat conversation, pinned GPT-6/Medium test subject. Observe model-visible nonce, voluntary job result fetch, meaningful subsequent work in the same prompt, 12 pre-registered paired candidate/control comparisons per viable carrier, and (only after B proves trusted identity) three-chat isolation. Codex Desktop and ChatGPT Work evidence do not count as Chat mode.

**R2-F — Supervisor-only evidence synthesis.** Independently verify R2-A–E terminal reports, compare R1 unchanged source/fixture/provenance and evidence layers, issue G0–G7 PASS/FAIL/INCONCLUSIVE/BLOCKED and a GO_TO_IMPLEMENTATION_PLAN / CONDITIONAL_GO / NO_GO / INCONCLUSIVE verdict. No merging/deployment.

## Parallelism

R2-0 freezes the run source, R1 evidence checksums, fixture references, output schemas, dedicated test namespaces and each worker's immutable input packet. **R2-A/B/C/D can all start simultaneously after R2-0**. R2-E0 (Chat mode trial plan only) can also prepare in parallel. E1 genuine Chat model-visibility canary needs A and a user-authorized connected test App, but does not depend on B/C if it performs no session-specific hints. E2 automatic per-chat reminders/receipt and 3-chat isolation requires trusted B identity and defensible C receipt; if either fails, E2 BLOCKED, not a fake PASS.

No CLI worker may operate the shared Desktop/browser, and there is at most one genuine Chat mode operator. W1–W4 are not rerun. See [DAG and execution](PARALLEL-DAG.md) and [step-by-step I/O](STEP-IO.md).

## Explicit model and effort

User authorized moving unavailable Claude Code tasks to Codex. All new local R2 execution uses Codex, never default model or effort.

| Lane | Executor | Model | Effort |
| --- | --- | --- | --- |
| R2-0 frozen setup | Codex CLI | gpt-6-sol | medium |
| R2-A test-connection feasibility | Codex CLI | gpt-6-sol | medium |
| R2-B identity and trust | Codex CLI | gpt-6-astra | xhigh |
| R2-C receipt protocol | Codex CLI | gpt-6-astra | xhigh |
| R2-D transport/performance | Codex CLI | gpt-6-astra | high |
| R2-E model subject | Real ChatGPT Chat | GPT-6 | Medium |
| R2-E operator | Verified supported UI | Explicit selector where supported | Never infer a default |
| R2-F supervisor | This ChatGPT conversation | Not a worker | Not applicable |

Effective selections must be independently verified via native runtime metadata or actual UI selector and saved as a startup receipt. If unavailable, report BLOCKED/UNVERIFIED, never silently downgrade. See [models and prompts](MODEL-AND-HANDOFF.md).

## Evidence contract, safety and limits

Every lane emits a versioned JSON results report, actual model-selection receipt, redacted JSONL event trace, hashed evidence index, factual Markdown findings and lane-specific raw JSON/CSV described by [Step I/O](STEP-IO.md) and [Evidence gates](EVIDENCE-AND-GATES.md). Per-case status: PASS/FAIL/INCONCLUSIVE/BLOCKED/NOT_RUN. Hypothesis: SUPPORTED/REFUTED/UNRESOLVED. Raw server output is not client receipt; client receipt is not model use; model use is not workflow continuation.

Prototypes are synthetic, isolated, disposable, with no public service changes, no production MCP service restart, no production code changes, no merge/push to master and no real user content. A passive MCP hint cannot wake a ChatGPT turn that has ended; that separate orchestration problem remains explicitly out of scope.

## References verified 2026-10-10

- Official custom MCP plugin test connection: [OpenAI custom MCP connection](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- Official Secure MCP Tunnel guide: [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- OpenAI Agents SDK MCP output rules (a different client, *not* proof of ChatGPT Chat): [Agents SDK MCP integration](https://openai.github.io/openai-agents-python/mcp/)

An official guide does not establish that the particular user/account has permission to add another custom plugin. That is a live R2-A/R2-E condition.

## Current status

At document preparation: R1 W1–W4 finished; W5 not run; no R2 agents launched; one separate existing hourly observer checks for material developments. The R2 documents are not evidence of completed R2 experiments.
