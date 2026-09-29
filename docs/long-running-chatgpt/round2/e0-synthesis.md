# E0 — Round 1 synthesis

Status: **E0 complete, 2026-09-29.** Input: `../r1-synthesis-inputs.md` (frozen) and the four lane reports at
the commits it names. No other Round 1 material is used.

Lane references: A = reliability evidence (`aa63a07`), B = job output (`a53774e`, hard cap `136b301`),
C = Responses API (`4554257`), D = MCP capabilities (`d276411`).

## 1. Confirmed facts

Each fact is supported by direct evidence in at least one lane, and the coordinator re-checked the marked items
against raw data.

| # | Fact | Evidence | Lane |
| --- | --- | --- | --- |
| F1 | Local jobs are durable. They survive the end of the ChatGPT turn that started them; state and full output persist in the job store (`meta.json`, `out.log`). | 49 later-turn reattachments; 225 jobs finished with no ChatGPT terminal observation; C2 code mapping | A, C |
| F2 | Foreground observation is not durable. 253 of 734 handed-off jobs, and 205 of 229 jobs of 5 minutes or more, lost their originating turn's observation while running. | A1 tables, reproduced by the coordinator | A |
| F3 | Same-turn completion-and-resume is observed up to 33.34 min (job `11023a552209`, coordinator-checked); 24/10/3/2 successes at >=5/10/20/30 min; none at >=40 min. | A1 | A |
| F4 | No hard foreground wall-clock limit is supported by the evidence. | A2, A3 §8.2 | A |
| F5 | The cause of lost observation is not measurable today. Only 44 of 205 stopped long jobs were polled at all; seven turns hold both outcomes; concurrency is correlated only (180/205 vs 17/24). | A2 | A |
| F6 | `job_status` output was unbounded per call (up to ~181k estimated tokens on 2026-09-27). The hard cap in `136b301` bounds `log_tail` to 24,000 characters with unchanged inputs and schema; 194 focused tests pass (coordinator re-run). | B0–B2 | B |
| F7 | `job_status` still reads and decodes the whole spool on every call. | B2 | B |
| F8 | The reusable Responses API pattern is: stable id, retrieval independent of the transport, idempotent cancel, and an exclusive monotonic resume position (`sequence_number` + `starting_after`). Exactly-once delivery and create idempotency are not documented. | C0–C1 (official docs, 2026-09-29; coordinator spot-checked) | C |
| F9 | Binnacle already has the core of that pattern: `job_id`, disk-backed `job_status`, idempotent `stop_job`, durable terminal state. The missing piece is a public incremental-output position. | C2 | C |
| F10 | Current ChatGPT uses MCP `2026-07-28` and advertises only `openai/visibility` and the UI extension: no elicitation, no Tasks. | D0, D2 (coordinator-checked in the journal) | D |
| F11 | ChatGPT rejects an `input_required` result: no retry, `McpServerError: MCP input requires an elicitation-capable caller`. | D2 (coordinator read the probe server's event log) | D |
| F12 | Ordinary stateless tool calls work after a later turn, from a new conversation and after a tunnel reconnect. FastMCP `session_id` changes per turn even without a reconnect; OpenAI `sessionId` is stable only inside one conversation. | D4 | D |

## 2. Rejected assumptions

| Assumption | Why rejected | Lane |
| --- | --- | --- |
| "A local job running for 40–50 min shows ChatGPT can wait that long." | Job durability and turn observation are different facts (F1, F2); no same-turn success at >=40 min. | A |
| "There is a hard foreground timeout near 20 or 30 min." | Successes at 28.9, 32.56 and 33.34 min; no timeout reason in any record. | A |
| "Long waits, large outputs or tunnel faults are the main cause of lost observation." | None separates the classes in A2; tunnel and MCP restart overlap is 1/24 vs 0/205 and 0/24 vs 1/205. | A |
| "Output size caused the interruptions." | Median target `job_status` sizes and truncation are nearly equal across classes; size is a context-cost risk, not a proven cause. | A, B |
| "Use MCP Tasks for deferred work." | Not advertised by ChatGPT (F10). | D |
| "Use MCP elicitation / `input_required` to ask for missing input." | Rejected live by ChatGPT (F11). | D |
| "The MCP session can hold job or cursor state." | `session_id` changes per turn (F12). | D |
| "Clone the Responses API (six statuses, SSE, `store`, retention timers)." | Adds states with no local meaning and a second event layer over an append-only log. | C |
| "A sequence/event cursor is needed." | The spool is a byte stream with no event boundaries; a sequence needs a new index for no stated gain. | B, C |
| "OpenAI-shaped names make the model use the API better." | No evidence; name only where the invariant matches. | C |

## 3. Decisions carried into E1

- **D-1 Durable identity is Binnacle's.** `job_id` stays the only lifecycle handle. No state is keyed on MCP,
  FastMCP, OpenAI or tunnel session identity; those are logged for correlation only (F12).
- **D-2 Foreground waiting is an optimization, not a contract.** No wall-clock lifetime is encoded (F3, F4).
  A later turn must be able to continue from `job_id` alone plus what the tool returns.
- **D-3 Keep the lifecycle vocabulary.** `state` = `running` | `exited` | `unknown`, outcome in `exit_code` /
  `signal`. No `queued`, no Responses status clone (C3).
- **D-4 Add one incremental-output position.** Exclusive byte offset over `out.log`, bounded per call by the
  existing hard cap, safe to echo (UTF-8 boundaries), additive for old callers. Placement (optional argument on
  `job_status` vs a separate tool) is decided in E1 (B3, C3).
- **D-5 Keep the hard cap `136b301`.** It is independent of the cursor and remains the ceiling for any
  returned output. Merge timing is decided at E4 / I-GATE, not now.
- **D-6 No dependency on MCP elicitation or Tasks.** Both stay optional until a client advertises them and a
  bounded live probe succeeds (F10, F11).

## 4. Unresolved risks (owned by later steps)

| Risk | Why it matters | Owner |
| --- | --- | --- |
| R-1 Cause of lost observation is unknown (F5). | The contract must work whatever the cause; diagnosis needs the six telemetry additions of A §8.3. | E1 (telemetry scope), I-C |
| R-2 Full-spool read per call (F7). | Cursor mode must use bounded range reads, or the I/O cost grows with the log. | E1, I-A |
| R-3 Cursor invalidation. | Pruning removes a job; rotation does not exist yet. Needs a defined error, and generation rules before any rotation. | E1, E3 |
| R-4 Tool-surface change. | An additive argument or a new tool changes the published schema; ChatGPT caches it, and `client_tools` controls who sees what. | E2 |
| R-5 Model usage. | A cursor helps only if the model echoes it. A later turn has no memory of an earlier cursor unless the tool can reseed it. | E1, E3, Round 4 (TREATTACH) |
| R-6 Duplicate starts. | A turn cut off after `run_command` may start the job again; no create idempotency exists (C1). | E1 decides in/out of scope |
| R-7 Client label. | Discovery says `openai-mcp (ChatGPT)`, calls say `openai-mcp (Codex)`; attribution must not depend on one label. | I-C |
| R-8 Evidence window. | A's numbers stop at 2026-09-29 10:26:27; they are a baseline, not a guarantee. | Round 4 |

## 5. What E1 must produce

The smallest contract that satisfies D-1 to D-6: cursor placement and field names, exact cursor semantics
(exclusive offset, `next_*`, `has_more`, errors), bounded read path, how a new turn reseeds its position,
telemetry in scope, and an explicit list of what stays unchanged in `run_command`, `job_status` and `stop_job`.
