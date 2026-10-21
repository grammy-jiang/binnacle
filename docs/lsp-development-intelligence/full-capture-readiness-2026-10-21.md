# Full MCP capture readiness for Development Intelligence — 2026-10-21

**Decision:** GO for **local retrospective tool-use/opportunity mining**, CONDITIONAL for source-verified case reconstruction, and **NO-GO for claiming LSP/agent task efficiency from history alone**.
**LSP baseline:** rebased onto fetched `origin/master ab60a33` on 2026-10-21, followed by the retained P1.9 assertion correction (`b0fc5ac`). Independent LSP P1.9 synthetic GO remains unchanged. No P2 implementation or production redeployment.
**Method:** read-only source/config verification, private on-host streaming aggregation of each host's capture JSONL, read-only session-observer SQLite linkage, and an isolated synthetic FastMCP test. Neither private command contents nor private tool results were copied into this repository, the review output or an external model.
**Dynamic observations:** counts below are **point-in-time snapshots around 2026-10-21 00:19–00:23 UTC**; capture continued during measurement, so different rows/scans may have slightly different totals. File names are UTC dates even when the local Sydney date is 2026-10-21.

## 1. Running capture capability is present on all three hosts

| Host | Effective full-capture config | Earliest recorded payload (UTC / Sydney) | Capturing deployment |
| --- | --- | --- | --- |
| MacBook Pro | enabled, fsync=false; owned private JSONL | 2026-10-20 23:32 UTC / Oct 21 10:32 AEDT | checkout at `ab60a33` |
| Raspberry Pi | enabled, fsync=false; owned private JSONL | 2026-10-20 22:21 UTC / Oct 21 09:21 AEDT | checkout at `40aafcd` |
| Sextant | enabled, fsync=false; owned private JSONL | 2026-10-20 22:18 UTC / Oct 21 09:18 AEDT | checkout at `40aafcd` |

Each host's `~/.local/state/binnacle/full-capture/YYYY-MM-DD.jsonl` contains nonempty, parseable JSONL; files are mode `0600`. The deployed `full_capture.py`, `logging_middleware.py`, `config_telemetry.py`, and `command_execution.py` files on all three machines match the exact content hashes in the rebased LSP checkout. The Raspberry Pi deployments are based on an older master commit, but the audited logging code is byte-identical. No service was restarted or modified.

The full-capture `FullCaptureSink` serializes the entire MCP message before writing, without its own string-length limit, while **ordinary journal logging remains sanitized and clipped**. A separate temporary, non-shell FastMCP test verified exact equality across `mcp_request`, `tool_call`, `tool_result`, and `mcp_response` for a **175,046-character synthetic command** and a **200,044-character synthetic result** (eight JSONL records; no external command executed). Existing native capture unit/integration/logging tests: **45 passed, 4 skipped**.

## 2. Real request/result integrity and command completeness

| On-host snapshot | MacBook Pro | Raspberry Pi | Sextant |
| --- | ---: | ---: | ---: |
| Recorded MCP tool calls | 171 | 794 | 123 |
| `run_command` tool calls | 95 | 320 | 90 |
| Request-to-tool-call correlation | 171/171 | 794/794 | 123/123 |
| Full command input equal between original MCP request and tool call | 95/95 | 320/320 | 90/90 |
| Largest captured command in characters | 18,579 | 12,549 | 12,545 |
| Calls paired to `tool_result` or `tool_error` | 170/171 | 793/794 | 122/123 |

All three single unpaired calls at the instant of their respective scans were newer than 90 seconds, not demonstrated historical losses. `tool_error` is an independent terminal event, **not** a missing successful `tool_result`. Five Raspberry Pi `run_command` calls lacked the required command input and ended in errors; they were **invalid requests**, not examples of the capture writer shortening an available command.

For opportunity discovery only, nonexclusive local keyword classification of captured command text found candidate Git inspection, code search, file inspection, test and lint/type-check activity. This is *not* an agent-quality score: active Binnacle development and the logging audit itself influence the distribution. Future evaluation must deduplicate requests, filter by task, use control groups and label results.

## 3. What full capture does and does not preserve

- **Captured intact when available in the original MCP message:** tool names, argument objects (including full `command`, `stdin`, path/pattern), method metadata, the tool's returned content/structured result, error text/tracebacks, timestamps and correlation. The file writer itself does not apply the standard journal's 500-character clip or argument redaction.
- **Not guaranteed full original command stdout/stderr:** `command_execution.run_command` applies the already-existing `jobs.max_output_chars=24,000` head/tail result budget (and optional `tail_lines`). The full-capture file preserves **exactly the result delivered to the MCP client**, including `truncated` and `output_bytes` where available; it cannot recover bytes removed before middleware. Around this audit, `run_command` returned `truncated=true` 10 times on MacBook, 3 times on Raspberry Pi and 0 on Sextant.
- **Job spool cannot be assumed durable forever:** `jobs.keep_newest` defaults to **50**. At one read-only availability check, returned nonempty `log_path` files still existed for **48 of 81** MacBook, **51 of 290** Raspberry Pi and **49 of 87** Sextant recorded command results. Missing files must be graded `output_unavailable` unless another independently verified source exists; retention is a plausible cause, not proven for each item.
- **Not a record of the full AI conversation:** user prompts, private model deliberation, total model input/output/cache tokens, the agent's intended solution and uncommitted complete repository state do not automatically appear in MCP messages. An MCP result is not independent proof that a development task succeeded.
- **Writer failure is possible:** the initial full-capture request record is required/fail-closed, but already-executed outcomes use best-effort persistence; with `fsync=false`, recent buffered disk writes are not crash-durable. Revalidate missing results/joins per evaluation window instead of claiming mathematical losslessness.

These are boundaries in the current **tool result and evidence lifecycle**, not a request to revert the completed full-capture logging implementation.

## 4. Task grouping and historical era boundaries

Read-only on-host `sessions.sqlite3` observer data is available on **all three machines**. Matching full-capture `(server_gen,call)` with `calls(gen,call)`, and observer `request_hash` to `tunnel_events.base_hash`, recovered **one unambiguous tunnel base** for each matched sample: MacBook **124/184**, Raspberry Pi **369/804**, Sextant **122/126**. These counts come from a separate later scan and are **not** the same-sized cohort as §2. Unmatched calls are mostly local/MCP traffic not represented by a tunnel request; they cannot be assigned a ChatGPT task base by timestamp speculation.

Use three separate historical eras:

1. **Before 2026-10-09:** older journals may preserve visible command fragments or full argument material depending on their age; access and labeling remain limited.
2. **2026-10-09 until each host's 2026-10-21 opt-in activation:** regular journals sanitize command, stdin, path, pattern and source text; session-observer SQLite has useful metadata but does not reconstruct stripped content.
3. **From the host's opt-in activation on 2026-10-21:** private full MCP capture allows read-only exact local analysis of original command/source/result *as sent or delivered*, with the upstream tool shaping and prompt/snapshot limits above.

There is **no retroactive creation of missing raw October 9–20 material**. Tool-call groups are not automatically distinct development tasks.

## 5. Evaluation decision and bounded next steps

**GO — E0/E1 local discovery:** implement a read-only on-host extractor which parses the raw private full-capture rows without clipping, pairs by generation+call and session+request ID, joins session-observer tunnel base where exact/unambiguous, classifies code navigation/test/lint commands and marks errors, shortened outputs, missing spool, timestamps and missing task intent. Emit only counts and de-identified metadata to review artifacts by default; do not write raw command text or source into Git.

**CONDITIONAL — historical examples:** recover verifiable source revision and independently reviewed task goals/gold; classify `R0/R1/R2/R3` and exclude unknown or stale state from faithful replay. Capture alone does not justify treating every `read_file` or Git command sequence as an `inspect_symbol` improvement.

**NO-GO — retrospective agent improvement claim:** run a controlled, same-model/effort/task/repo Chat Mode A/B with actual proposed tool and baseline, independently verified correctness, model-step/tokens/latency, resource and permission controls. Historical call totals are opportunity estimates only, not a counterfactual tool comparison.

The existing logging workstream remains separate; no modifications to the production logger or three running services were made for this assessment.
