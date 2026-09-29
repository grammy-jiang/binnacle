# Round 1 synthesis inputs (R1.4)

Status: **FROZEN 2026-09-29 11:14 — all four Round 1 gates passed.**

Owner: the Claude Code coordinator (session `binnacle-longrun-coordinator`).
Base: `99e89a595bdc37cb31e53687d50611eda3463120` (master, docs-only preparation commit).

This file is the only input set for Round 2 step E0. E0 reads the four lane reports at the exact commits
below and nothing else from Round 1. Worker chat transcripts are execution evidence, not inputs.

## 1. Frozen lane outputs

| Lane | Branch | Head | Report | Gate |
| --- | --- | --- | --- | --- |
| A | `investigation/longrun-a-evidence` | `aa63a07b90d9d1714803fe23d197bf2ecca10ce3` | `docs/long-running-chatgpt/lane-a-report.md` + `lane-a-scripts/lane_a_analysis.py` | A-GATE PASS |
| B | `feature/longrun-b-job-output` | `a53774e8b53bb4df3e84e8f55f46f0ab46e53f64` (hard cap `136b301`) | `docs/long-running-chatgpt/lane-b-report.md` | B-GATE PASS, not merged |
| C | `investigation/longrun-c-responses` | `4554257208b5a0789e6d2db6080869b662a00ea7` | `docs/long-running-chatgpt/lane-c-report.md` | C-GATE PASS |
| D | `experiment/longrun-d-mcp-capabilities` | `d276411b2742c066931eb4f70c25c06fba5d38f0` | `docs/long-running-chatgpt/lane-d-report.md` + `lane-d-evidence/` (sanitized) | D-GATE PASS; POC not for merge |

Read a report without checking out its branch:

```bash
git -C ~/Projects/binnacle show <head>:docs/long-running-chatgpt/lane-<x>-report.md
```

## 2. Coordinator verification performed

Each claim below was re-checked by the coordinator, not taken from the worker's reply.

- A0: job `b94de33877ec` in the raw journal: 33 `job_status` calls, `runtime_s=1953.751`.
- A1: job `11023a552209` in the raw journal: `runtime_s=2000.2` (33.34 min), same turn.
- A2: `lane_a_analysis.py` re-run with `~/Projects/binnacle/.venv/bin/python`: every A1 table identical.
- B0: `_tail()` in `job_status.py` keeps the last N lines, whatever their length.
- B1/B2: diff reviewed; 194 focused tests passed on the working tree and again on commit `136b301`.
- C0: the background-mode guide, fetched live: polling rule and idempotent cancel as quoted.
- D0: the ChatGPT `server/discover` envelope at 2026-09-29 00:27:52 in the journal: protocol
  `2026-07-28`, `openai/visibility`, `io.modelcontextprotocol/ui`; no elicitation, no tasks.
- D2: the probe server's own event log: one `require_choice` call, `input_required` returned,
  no retry; the chat ended with `McpServerError: MCP input requires an elicitation-capable caller`.
- D4: the production units' PIDs and start times equal the 09:55 baseline after the probe-tunnel restart.
- D5: the probe root, port 18082, units and tunnel-client profile are gone; the probe tunnel returns HTTP 404
  at OpenAI; the connector list equals the 09:55 baseline; the 3 probe chats were backed up and deleted by
  exact id; the 4 lane worker chats remain in the Project and tracked; the committed evidence holds no
  token, Authorization value or raw `openai/session` value (hash prefixes only).
- R1.2: `binnacle doctor --no-probe` 28 ok / 1 warn (journal lines = lane workers' rejected out-of-root
  paths, the server behaving as designed); `master` still at the base commit.

## 3. Facts carried into E0 (confirmed by at least one lane with evidence)

1. Local execution is durable; foreground observation is not. 253 of 734 handed-off jobs, and
   205 of 229 jobs of 5 minutes or more, lost their originating turn's observation while running (A).
2. Recovery is used in practice: 49 later-turn reattachments; 225 jobs finished without any
   attributable ChatGPT terminal observation (A).
3. No hard foreground wall-clock limit is supported. Same-turn completion-and-resume is observed to
   33.34 min; none at 40 min or more in the window, which is absence of evidence, not a limit (A).
4. Cause of stopped observation is not measurable with current telemetry; only 44 of 205 stopped long
   jobs were ever polled (A).
5. `job_status` returned-log size is now hard-bounded at 24,000 characters (B, `136b301`);
   the full spool is still read per call (B, deferred).
6. The Responses API pattern that matters is stable id + retrieval independent of the transport +
   an exclusive monotonic resume position (`sequence_number` / `starting_after`); exactly-once
   delivery and create idempotency are not documented (C).
7. The current ChatGPT MCP host speaks protocol `2026-07-28`, advertises neither elicitation nor the
   Tasks extension, and rejects an `input_required` result (D0, D2, D3).
8. Ordinary stateless tool calls survive a later turn, a new conversation and a tunnel reconnect. FastMCP
   `session_id` changes per turn even without a reconnect; OpenAI `sessionId` is stable only within one
   conversation. Durable job, cursor, resume and cancellation state must live behind Binnacle-owned
   identifiers, never MCP or tunnel session identity (D4).
9. Round 2 must not require MCP elicitation or MCP Tasks in the current deployment; both stay optional
   until a future client advertises them and a bounded live probe succeeds (D5).

## 4. Plan inconsistencies recorded for E0

- README section 2 item 3 and the coordinator prompt quote 23/9/2/1 same-turn successes at
  >=5/10/20/30 min and a 32.56-min maximum. The frozen A window (to 2026-09-29 10:26:27) gives
  24/10/3/2 and 33.34 min (job `11023a552209`). E0 uses the Lane A numbers.
- The coordinator prompt says to send with `chatgpt-send --new`. That path could not post on
  2026-09-29 10:03-10:23; the proven worker-rounds path (`send_prompt.py --project ... --no-wait`,
  fresh browser profile, HTTP collection) was used instead (WORKLIST coordinator decision 5).

## 5. Open questions handed to E1 (from the lanes)

- Cursor placement: `job_status(after=<exclusive byte offset>)` (B preferred) or a separate
  `job_output` tool (B fallback).
- Cursor generation/versioning now, or only when log rotation is introduced (B).
- Bounded range reads for cursor mode versus the current full-spool read (B).
- "Wait for new output" semantics, or keep "wait until terminal or deadline" (B).
- Telemetry additions to separate foreground expiry, transport loss, context pressure and handoff (A).
- Client label: discovery says `openai-mcp (ChatGPT)`, D4 `tools/call` metadata says `openai-mcp (Codex)` (D);
  telemetry that attributes calls to ChatGPT should not depend on one label.
