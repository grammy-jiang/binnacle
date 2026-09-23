# Logging: what the journal records, and how to review the server from it

Status 2026-09-22. Code: `src/binnacle/logging_middleware.py` (request and
tool records), `src/binnacle/jobs.py` (job records), `src/binnacle/server.py`
(startup record, root handler format), `src/binnacle/callctx.py` (the call
id shared by the middleware and the job store). Readers:
`src/binnacle/logstats.py` (`binnacle stats`) and `scripts/usage_breakdown.py`
(the `mcp-usage-review` measurement). Both read every line shape back to
2026-08-29.

## 1. Two line shapes in one journal

| Source | Logger | Handler | Shape in `journalctl -o cat` |
| --- | --- | --- | --- |
| fastmcp `LoggingMiddleware` (our `RequestLoggingMiddleware` subclass) | `fastmcp.middleware.logging` | fastmcp's rich handler | `[MM/DD/YY HH:MM:SS] INFO     event=request_start   logging.py:122` plus indented continuation lines wrapped at about 36 columns, anywhere, including inside tokens; the timestamp is printed once per second |
| fastmcp itself | `fastmcp.server.server` | rich handler | `[..] Error calling tool 'read_file'`, `Invalid arguments for tool ...` |
| binnacle (`binnacle.results`, `binnacle.jobs`, `binnacle.server`) and the MCP SDK (`mcp.*`) | root | `logging.basicConfig` | one line, never wrapped: `INFO: event=...` until 2026-09-13, then `2026-09-13T22:40:11.123 INFO: event=...` (local time, milliseconds) |
| uvicorn | `uvicorn.*` | uvicorn's own | `INFO:     127.0.0.1:52674 - "POST /mcp HTTP/1.1" 200 OK`, `Application startup complete.`, `WatchFiles detected changes in ...` |

The root-handler timestamp was added because `-o cat` output has no
journald timestamp and the rich timestamp only lands on the first record
of each second; the parsers carried the last seen rich timestamp over to
every plain line, so a job or result line could be attributed to the wrong
second.

## 2. Inventory of records (after this change; "since" is the first day in the journal)

| event | Emitted by | Fields | Since |
| --- | --- | --- | --- |
| `request_start` | `RequestLoggingMiddleware` (fastmcp base) | `method source payload(500 chars) payload_type request_id session client [tool]` | 08-29 (`request_id session client tool` from 09-02) |
| `request_success` | same | `method source duration_ms request_id session client [tool]` | 08-29 |
| `request_error` | same, level ERROR | `method source duration_ms error=<text> request_id session client [tool]` | 08-29 |
| `notification_start` / `notification_success` | same | `method source payload ...` | 08-29 |
| `tool_call` | `ToolLoggingMiddleware` | `call tool client session request_id [turn] [oai_session] args_chars args=<json, 500 chars>` | 09-13 |
| `tool_result` | `ToolLoggingMiddleware`; level WARNING when `is_error=True` | `call tool client session request_id [turn] [oai_session] duration_ms is_error` then either result sizes plus lifted scalar facts, or `error_class [error_code] error=<text, 200 chars>` | 09-02; tokenizer fields from 09-21; stable error codes from 09-22 |
| `job_start` | `jobs.start_job` in the selected owner | `job_id pid command(60 chars, repr) workdir call owner owner_instance command_hash command_chars` | 09-02; owner/hash fields from 09-22 |
| `search_budget_hit` | `tools.search_text`; INFO | `call result_bytes result_budget_bytes returned_entries total_matches names_only` | 09-19 |
| `search_exact` | exact `search_text`; INFO, one terminal summary after exact dispatch | `call outcome error_code strategy budget_outcome scope rg_calls auto_context context_requested effective_context` + phase timings + rg/collect/adaptive work counters + final result size/truncation | 09-22 |
| `job_listing` | `tools.job_status`; INFO | `call recorded_jobs returned_jobs running_jobs history_limit command_preview_chars` | 09-19 |
| `job_status_timing` | `tools.job_status`; INFO | `call job_id wait_requested_s wait_bounded_s wait_effective_s waited_s blocking_budget_s blocking_spent_before_s blocking_remaining_before_s blocking_active_before blocking_policy blocking_budget_exhausted turn client dispatch_ms state_ms read_log_ms process_scan_ms impl_ms state processes log_bytes` | 09-19; blocking-wall policy fields from 09-24 |
| `blocking_window_closed` | `tools.job_status`; INFO when a tracked active window commits | `call turn client blocking_budget_s blocking_window_wall_s blocking_spent_after_s blocking_remaining_after_s` | 09-24 |
| `run_command_dispatch` | `tools.run_command`; INFO, one per successful call | `call client job_id owner owner_instance requested_wait_s bounded_wait_s effective_wait_s background_arg auto_background handoff_reason owner_roundtrip_ms command_hash command_chars state` | 09-22 |
| `run_command_dispatch_error` | `tools.run_command`; WARNING when owner dispatch fails | same policy/owner/timing fields plus `error_class` | 09-22 |
| `job_owner_timing` | stable job manager; INFO | `op call job_id owner_instance`, start: `wait_s launch_ms impl_ms state`; stop: `impl_ms state` | 09-22 |
| `job_stop_requested` | ownership layer; INFO | `job_id call origin_call owner_instance command_hash` | 09-22 |
| `job_stop_escalate` | process owner; WARNING | `job_id call signal=SIGKILL grace_s` | 09-22 |
| `job_interrupted` | manager recovery; WARNING | `job_id reason call previous_owner current_owner command_hash` | 09-22 |
| `job_manager_start` | `binnacle-jobs`; INFO | `pid owner boot recovered protocol package_version socket` | 09-22 |
| `job_manager_client_disconnected` | `binnacle-jobs`; INFO | `op call job_id`; client disappeared after work was accepted/completed | 09-22 |
| `job_manager_request_invalid` | `binnacle-jobs`; WARNING | `op call error_class` | 09-22 |
| `job_manager_request_error` | `binnacle-jobs`; ERROR with traceback | `op call error_class` | 09-22 |
| `job_exit` | `jobs.record_exit` in the selected owner | `job_id exit_code signal reason runtime_s log_bytes call owner owner_instance command_hash` | 09-02; correlation/owner fields from 09-22 |
| `job_exit_unrecorded` | `jobs.record_exit`, WARNING | `job_id exit_code signal call owner owner_instance command_hash` | 09-02; correlation fields from 09-22 |
| `jobs_pruned` | `binnacle-jobs.service` via `jobs._prune`, on every prune that removed or skipped something | `removed skipped_running keep_newest reserve effective_keep` | 09-02 (`reserve effective_keep` from 09-19) |
| `config` | `server.log_effective_config`, once per (re)start | `pid version roots jobs_dir keep_newest client_tools rg_bin` | 09-02 (`pid version` from 09-13) |
| `tool_config` | `server.log_effective_config`, once per tool/config group per (re)start | `tool` plus effective scalar limits/caps/timeouts; jobs records configured/effective owner and stop grace | 09-22 |

Lifted result keys (`RESULT_KEYS`, only when the tool's `structured_content`
has them; list-valued `entries`, `jobs`, `processes` are logged as their
length): `job_id state exit_code signal background_job truncated count
total_lines start_line end_line lines_clipped kind output_bytes log_bytes quiet
waited_s wait_requested_s wait_effective_s blocking_budget_s
blocking_remaining_s blocking_budget_exhausted blocking_policy runtime_s
last_output_age_s fits_in_one_call lossy next_start_line mime_guess mode
replacements match first_change_line action previous_bytes bytes`.
Booleans are `true`/`false`, absent values `null`; `is_error` keeps its 09-02
spelling `True`/`False`. Full content, snippets, notes and paths are not lifted.

Argument JSON in `tool_call` is compact, non-string values first and strings
shortest first, so `wait_seconds`, `tail_lines`, `start_line`, `path` stay
visible when a long `command` or `content` runs past the 500-char clip
(`request_start` clips the payload as a whole and loses those keys in 70%
of run_command calls, docs/tool-cost-2026-09-13.md §4). `args_chars` is the
unclipped length.

Not logged, by design: the bearer token (a header; `get_http_headers()`
strips `authorization`), any result text (`tool_result` carries sizes and
scalar facts only), the values of `X-Openai-Session` (hashed) and
`X-Openai-Subject` (dropped).

## 3. What the 2026-09-02 round claimed, checked against code and journal

| Claim | Found |
| --- | --- |
| request ids on middleware lines | Present. For ChatGPT every one is `request_id=0`: it opens a new MCP session per call (1762 sessions today), so only `(session, request_id)` pairs a start with its success. |
| job lifecycle lines | Present (`job_start`, `job_exit`, `jobs_pruned`, `job_exit_unrecorded`). |
| resolved client name | Present (`client=openai-mcp`, `claude-code`, `codex-mcp-client`, `mcp`; one variant `openai-mcp (Codex)` has a space). |
| response summaries | Present but useless: `content_chars` measured the one-line summary (median 126 chars for run_command) because the payload is `structured_content`; and no line was ever written for an error (0 `is_error=True` in 15 days against 29 `request_error`), because errors reach the middleware as exceptions. |
| startup config line | Present; 122 in the last two days, one per `--reload` (the uvicorn watcher reloads on any `.py` save under the repo, `tests/` included). |

## 4. What a review needs, and where it comes from now

| Need | Before | Now |
| --- | --- | --- |
| Correlate one call across lines | `(session, request_id)` on the rich lines only; `job_start` unlinked | `call=` on `tool_call`, `tool_result`, `job_start`; `job_id=` on the run_command result, the job lines and the `job_status`/`stop_job` arguments |
| Correlate with a ChatGPT turn | Timestamp match (±2 s) against the tunnel log's `cmd_request_id` | `turn=wfr_<turn>/<call>` from the request's `X-Request-Id` (the same id the tunnel logs); the part before `/` is one agent turn |
| Per-call latency | `duration_ms` on `request_success`, paired by order or id | `duration_ms` on `tool_result` |
| Size of what the model receives | Not measurable | `content_chars` (text blocks) + `structured_bytes` (compact JSON, UTF-8) + historical `est_tokens` = chars/4; when tokenizer telemetry is enabled for the client, `tokenizer_tokens` is the configured tokenizer count and `tokenizer_encoding` names the encoding |
| Error classification | `request_error` text, ERROR level, class unknown | `is_error=True error_class=ToolError [error_code=<stable reason>] error=message` at WARNING. `CodedToolError` remains a `ToolError` subclass and logs `error_class=ToolError`, preserving historical class counts while adding stable low-cardinality reasons; cancellations/validation/unknown-tool errors retain their native class |
| Truncation and clipping | Nothing | `truncated` (all four file/search tools and run_command's head/tail clip or `tail_lines` drop), `lines_clipped`, `start_line/end_line/total_lines` (read_file window), `count` vs `entries` (search cap), `output_bytes` vs the clip; `tail_lines`, `max_results` visible in `args` |
| Background jobs and outcomes | `job_start`/`job_exit` by `job_id`, exit code only | `run_command_dispatch` records owner/wait/handoff decision; `job_start` and `job_exit` retain call/hash/owner correlation; `job_exit` records runtime, bytes and reason |
| Automatic background policy | None | `run_command_auto_background` records the trigger; `run_command_dispatch` records requested/bounded/effective wait and the final `handoff_reason`, so later analysis does not need to reconstruct old policy configuration |
| Client identity | `client=` on rich lines | `client=` on every plain line too; `oai_session=` (12-hex SHA-256 prefix of `X-Openai-Session`) groups calls of one ChatGPT session |
| Restarts / effective limits | uvicorn's `Application startup complete` | `config pid=... version=...` plus startup-only `tool_config` records for read/list/search/run/jobs/edit behavior-changing limits; reviews can detect config variants in a window instead of assuming today's defaults |

Measured on the live headers (loopback capture, 2026-09-13 22:20): the tunnel
forwards `X-Request-Id: wfr_<turn>/<call>`, `Mcp-Method`, `Mcp-Name`,
`Mcp-Protocol-Version`, `Traceparent`/`Tracestate`, `X-Datadog-Trace-Id`
(one per turn), `X-Datadog-Parent-Id` (one per call), `X-Openai-Session`
(one value across the sampled turn), `X-Openai-Subject`, `X-Openai-Pod-Uid`,
`X-Forwarded-Client-Cert`, `X-Origin-Ingress-Name`. No header carries the
ChatGPT conversation id. Local agents send none of these.

## 5. Shared tool telemetry hardening (2026-09-22)

Simple deterministic tools continue to rely on `tool_call`/`tool_result`; they do not get
a second per-call event merely for symmetry with `run_command`. Phase A adds three shared
capabilities instead:

- existing low-cardinality structured facts are lifted into `tool_result` (for example
  `read_file.fits_in_one_call/lossy/next_start_line`, `list_files.mode`, edit match facts
  and write previous size); content/snippet/path/note text is still not duplicated;
- `tool_config` records the effective behavior-changing caps and timeouts at startup,
  including configured vs effective job owner;
- user-facing coded failures remain `ToolError` but optionally carry `error_code`, allowing
  stable aggregation such as `path_outside_root`, `file_not_found`, `range_past_end`,
  `rg_timeout`, `invalid_glob`, `rg_rejected`, and `response_budget_exceeded` without
  parsing human error text.

`binnacle stats` reports stable error-code counts, `read_file` whole/range and outcome
counts, `list_files` list/glob usage, and the latest effective tool config plus how many
config variants appeared in the requested window. Old journal windows simply leave these
fields empty.

## 6. Durable run-command telemetry (2026-09-22)

The durable owner adds one explicit decision record per `run_command`. This is intentionally
separate from `tool_result`: the latter says what the MCP client received, while
`run_command_dispatch` says **why** the execution path returned synchronously or handed a
job back. `owner_roundtrip_ms` includes the configured foreground wait; it is not labelled
as IPC latency. `job_owner_timing launch_ms` measures the manager's process-launch path.

The stable correlation chain is:

```text
tool_call(call)
  -> run_command_dispatch(call, job_id, command_hash)
  -> job_start(call, job_id, owner_instance, command_hash)
  -> tool_result(call, job_id)
  -> job_status/stop_job(job_id)
  -> job_exit(job_id, original call, owner_instance, command_hash)
```

The full command remains in the tool arguments and durable job record; telemetry uses a
12-hex SHA-256 prefix for aggregation so repeated command families can be measured without
copying full command text into every lifecycle line. Stop escalation, owner recovery and
client disconnects are separate events because they are operationally different failure
boundaries.

`binnacle stats` merges the MCP and jobs journals and reports dispatch/handoff counts,
owner mix, requested/effective waits, owner roundtrip and paired transport-overhead
percentiles, manager launch/stop timings, job runtime percentiles, job-status blocking
wait totals, exit reasons, stop escalation, recoveries and client disconnects.
CPU/RSS/IO sampling is deliberately not part of this telemetry pass.

## 7. Record format, from the live journal (2026-09-13 22:36, `scripts/mcp_client.py`)

```text
2026-09-13T22:36:10.162 INFO: event=tool_call call=682a831a7f11 tool=read_file client=mcp session=93b248d2fabe request_id=2 args_chars=53 args={"end_line":5,"path":"~/Projects/binnacle/README.md"}
2026-09-13T22:36:10.165 INFO: event=tool_result call=682a831a7f11 tool=read_file client=mcp session=93b248d2fabe request_id=2 duration_ms=2.43 is_error=False content_chars=105 structured_bytes=444 est_tokens=137 truncated=false total_lines=7 start_line=1 end_line=5 kind=text bytes=284
2026-09-13T22:36:12.358 INFO: event=tool_call call=d6d5fa0c10f0 tool=run_command client=mcp session=9accc7183c0a request_id=2 args_chars=40 args={"workdir":"/tmp","command":"printf hi"}
2026-09-13T22:36:12.362 INFO: event=job_start job_id=23ba8dcd6ae3 pid=1005608 command='printf hi' workdir=/tmp call=d6d5fa0c10f0
2026-09-13T22:36:12.364 INFO: event=job_exit job_id=23ba8dcd6ae3 exit_code=0 signal=None runtime_s=0.002 log_bytes=2
2026-09-13T22:36:12.364 INFO: event=tool_result call=d6d5fa0c10f0 tool=run_command client=mcp session=9accc7183c0a request_id=2 duration_ms=5.90 is_error=False content_chars=126 structured_bytes=244 est_tokens=92 job_id=23ba8dcd6ae3 state=exited exit_code=0 background_job=false truncated=false output_bytes=2
2026-09-13T22:36:14.349 INFO: event=tool_call call=40700a1bc25e tool=read_file client=mcp session=cd316d7fc612 request_id=2 args_chars=22 args={"path":"/etc/passwd"}
2026-09-13T22:36:14.350 WARNING: event=tool_result call=40700a1bc25e tool=read_file client=mcp session=cd316d7fc612 request_id=2 duration_ms=1.52 is_error=True error_class=ToolError error=Path outside allowed roots (/home/grammy-jiang/Projects, /tmp): /etc/passwd
```text

A request that carries the tunnel's headers (here a direct HTTP call sending
them; a ChatGPT call looks the same with a real `wfr_` id) adds the two
correlation fields after `request_id=`:

```text
2026-09-13T22:36:37.715 INFO: event=tool_call call=3ca0a738d533 tool=read_file client=mcp session=8314e3d09386 request_id=2 turn=wfr_headertest0000/ab12 oai_session=71334a33b178 args_chars=53 args={"end_line":2,"path":"~/Projects/binnacle/README.md"}
```text

Historical embedded-owner example (2026-09-13): a job that outlived its wait
window returned `state=running background_job=true`, and its `job_exit` arrived later
from the in-process reaper. Current managed deployments emit the same lifecycle events
from `binnacle-jobs.service`; `binnacle stats` merges the MCP and jobs journals.

```text
2026-09-13T22:26:54.491 INFO: event=job_start job_id=4b00d564522e pid=980398 command='sleep 3; echo done' workdir=/tmp call=2a94f3464a7d
2026-09-13T22:26:55.490 INFO: event=tool_result call=2a94f3464a7d tool=run_command client=mcp session=eb2e79f66ef5 request_id=10 duration_ms=1003.19 is_error=False content_chars=97 structured_bytes=227 est_tokens=81 job_id=4b00d564522e state=running background_job=true truncated=false output_bytes=0
2026-09-13T22:26:57.495 INFO: event=job_exit job_id=4b00d564522e exit_code=0 signal=None runtime_s=3.003 log_bytes=5
```text

First measurement the new fields allowed: a `job_status` call without a
`job_id` (the recent-jobs listing, 51 jobs) returned `structured_bytes=12327
est_tokens=3087`; ChatGPT made 50 such calls in one week
(docs/usage-analysis-2026-09-06.md).

## 8. Review recipes

```text
# every MCP call with its size and outcome, one line each
journalctl --user -u binnacle-mcp --since -1day -o cat | grep 'event=tool_result'
# one ChatGPT turn end to end
journalctl --user -u binnacle-mcp --since -1day -o cat | grep 'turn=wfr_01a09ab0ab6a7b8483396aba1bde22d1'
# errors by class
journalctl --user -u binnacle-mcp --since -7days -o cat | grep -o 'tool=[a-z_]* .*error_class=[A-Za-z]*' | sed 's/ .* error_class=/ /' | sort | uniq -c
# the largest results
journalctl --user -u binnacle-mcp --since -7days -o cat | grep -o 'tool=[a-z_]* .*est_tokens=[0-9]*' | sed -E 's/ .* est_tokens=/ /' | sort -k2 -n | tail
# a job from spawn to exit
journalctl --user -u binnacle-mcp --since -1day -o cat | grep 'job_id=e0e329ac0185'
```

`binnacle stats --since="-7 days"` adds: result size by tool (est_tokens
n / p50 / p90 / max / total), truncated results by tool, tool errors by
class, job exits by code, run_command results that became jobs, ChatGPT
turns with calls per turn. `scripts/usage_breakdown.py --json` adds
`results` (per tool: calls, est_tokens median/p90/max/total, truncated,
errors; errors_by_class; latency_ms; became_jobs; job_exits) and
`turns_journal`; the existing keys are unchanged and the baselines in
`docs/usage-baselines/` stay comparable.

## 8. Still not in the journal

Per-job CPU seconds, peak RSS, disk IO and thermal/throttling samples are intentionally
not added by the durable-owner telemetry pass. Wall runtime and process snapshots are
available today; resource accounting should be added only when there is a stable per-job
accounting boundary (for example a later cgroup design), rather than by introducing a
high-frequency sampler now.

- Full ChatGPT request/accounting tokens. `tokenizer_tokens` counts only the
  result payload text blocks plus compact structured JSON with the configured
  encoding. It deliberately excludes MCP/JSON-RPC/message framing, tool schemas,
  prior conversation context, and any provider-side accounting.
- The ChatGPT conversation id and the user's prompt: no header carries them.
- Whether ChatGPT gave up on a call (its 60 s cap): only the tunnel log
  (`poll failed`) sees that side; a `tool_call` without a `tool_result`
  means the server never answered (crash or reload mid-call).
- Rejected authentication: uvicorn access lines (`401 Unauthorized`) only.

## 9. Result-tokenizer telemetry

Tokenizer accounting is opt-in and configuration-driven:

```toml
[telemetry.tokenizer]
enabled = true
encoding = "o200k_base"
client_prefixes = ["openai-mcp"]
```

The repository default is disabled. When disabled, Binnacle does not import
`tiktoken` or load an encoding. When enabled, the middleware prepares the
encoding on a daemon thread so a cold/cache-miss tokenizer load cannot delay an
MCP response. Until preparation succeeds, normal tool results continue without
the optional tokenizer fields. Load/count failures are telemetry warnings only.

`client_prefixes` prevents an OpenAI tokenizer count from being presented on a
Claude or other provider's results by default. The fields are explicitly named
`tokenizer_tokens` and `tokenizer_encoding`: they measure the payload under that
encoding, not the provider's complete billed/context token count.

## 10. Logging constants

| Constant | Value | Meaning |
| --- | --- | --- |
| `ARGS_MAX_CHARS` | 500 | clip of `args=` (same as the rich payload clip) |
| `ERROR_MAX_CHARS` | 200 | clip of `error=` |
| `HEADER_MAX_CHARS` | 80 | clip of a lifted header value |
| `CORRELATION_HEADERS` | `{"x-request-id": "turn"}` | headers copied verbatim |
| `HASHED_HEADERS` | `{"x-openai-session": "oai_session"}` | headers logged as a SHA-256 prefix |
| `RESULT_KEYS`, `RESULT_LIST_KEYS` | see §2 | `structured_content` keys lifted into `tool_result` |

## 11. Parser compatibility

`logstats.parse` recognizes both plain shapes (`INFO: event=` and the
timestamped form) as records of their own; rich records parse as before.
`analyze` fills the new `Stats` fields only from lines that carry the new
keys (an old `tool_result` line has no `est_tokens` and counts nowhere),
so a window before 2026-09-13 renders as it did. `usage_breakdown.py`
counts a call once: the `tool_call` record wins over the `request_start`
record with the same `(session, request_id)`, and a window without
`tool_call` records takes the old path unchanged (verified: identical JSON
for 2026-09-12..13 before and after the change). Tests:
`tests/integration/test_logging.py`, `tests/unit/core/test_logstats.py`, `tests/scripts/test_usage_breakdown.py`.

## 12. Exact-search Phase B telemetry (2026-09-22)

Every ordinary exact search that reaches `search_dispatch(mode=exact)` now emits exactly
one terminal `search_exact` record on success or failure. It contains no raw path, pattern,
match text, context, or file list. Correlation uses `call`; `search_dispatch` already carries
the path hash and pattern length.

The event separates result semantics from work:

- `strategy=normal|names_only|adaptive`;
- `budget_outcome=none|entries_trimmed|context_omitted|metadata_error`;
- cumulative coarse timings: `rg_subprocess_ms`, `rg_parse_ms`, `collect_ms`,
  `context_attach_ms`, `adaptive_ms`, `budget_ms`, `impl_ms`;
- raw-work counters: rg stdout characters/event types, collect candidates/glob
  checks/rejects, accepted/retained matches/files, adaptive second-scan counters;
- final bounded-result facts: pre-budget bytes, returned entries/result bytes, truncation.

Auto-context remains one exact execution: `rg_calls=2`, `auto_context=true`, and phase/work
metrics are cumulative. Errors after exact dispatch retain partial work and record the
Phase-A stable `error_code` when available. Indexed `@context` keeps its existing telemetry
and does not emit `search_exact`.

`binnacle stats` reports exact-dispatch/summary coverage for mixed old/new journal windows,
strategy/budget/error counts, phase latency percentiles, work distributions, and
amplification ratios (`rg events / accepted match`, `rg chars / returned entry`).

The rg JSON parser is `orjson` from Phase B. This was explicitly approved as part of the
instrumentation change; the other optimization hypotheses in the Phase B plan remain
unimplemented so observation data stays comparable.

## 13. Indexed-context pilot records (2026-09-19)

The development `search_text('@context ...')` pilot adds dedicated single-line
telemetry without changing `tool_call`/`tool_result`.

| event | Fields |
| --- | --- |
| `search_dispatch` | `call mode path_hash pattern_chars` (`mode` is `exact` or `indexed`) |
| `index_context` | `call root_hash query_hash query_chars head generation cold_open open_ms reconcile_ms freshness_ms changed_files deleted_files hashed_files query_ms surface_ms total_ms files nodes edges db_bytes related_items direct_items package_items package_bytes package_est_tokens evidence_hashes` |
| `index_context_error` | `call root_hash phase error_class error total_ms` |

`query_hash`, `root_hash`, `path_hash`, and `evidence_hashes` are short SHA-256
prefixes used only for grouping/correlation. Query text and result excerpts are not
added to these telemetry records. `evidence_hashes` lets the pilot analyzer match a
later `read_file` or file-scoped exact search to an indexed candidate without logging
the returned source text.

The startup `config` record also carries `indexed_context`, `indexed_reconcile`, and
`indexed_max_open`, so a review can prove which service configuration produced a
measurement window.

Review normally with:

```text
binnacle stats --since "7 days ago"
```

The existing stats command automatically appends an indexed-context section when
these records are present. For detailed JSON/per-call rows, use:

```text
scripts/analyze_indexed_pilot.py --since '7 days ago' --json
```

Both use the same `binnacle.logstats` analysis code. See
`docs/indexed-context-pilot.md` for interpretation and rollout/rollback policy.
