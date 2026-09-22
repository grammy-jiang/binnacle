# Tool telemetry review — 2026-09-22

Status: review/design only. No production tool behavior changed by this review.

## 1. Objective

Use the durable `run_command` telemetry work as a quality reference without copying its
shape mechanically to every tool. A tool deserves dedicated telemetry only when generic
`tool_call`/`tool_result` records cannot explain an internal decision, fallback, or
multi-stage latency. Simple deterministic tools should stay on the shared middleware and
expose only low-cardinality scalar outcome fields needed for analysis.

The desired questions are:

- what was requested and by which client/call;
- which execution/decision path was selected and why;
- where latency was spent when a tool has multiple stages;
- how large the returned context was and whether it was clipped/truncated/degraded;
- what stable reason caused a failure;
- whether a later follow-up can be correlated to the original call;
- which effective configuration produced the behavior.

Do not duplicate full content, source text, or long commands in additional events merely
for convenience. Existing `tool_call` arguments and durable records remain the source of
truth; hashes and scalar facts are preferred for aggregation.

## 2. Seven-day production evidence

From the combined MCP/jobs journals immediately before this review:

| Tool | Calls | Errors | Truncated | p50 ms | p95 ms | Max ms | Approx result-token total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `run_command` | 8,222 | 3 | 295 | 122.6 | — | 50,029.7 | 6.21M |
| `job_status` | 2,714 | 12 | 0 | 3,500.9 | 50,038.5 | 50,154.7 | 2.52M |
| `read_file` | 2,517 | 20 | 36 | 1.5 | 9.2 | 49.8 | 3.78M |
| `search_text` | 1,537 | 6 | 87 | 10.1 | 91.1 | 20,412.1 | 5.25M |
| `list_files` | 261 | 5 | 5 | 1.6 | 17.6 | 142.5 | 0.12M |
| `stop_job` | 43 | 0 | 0 | 53.4 | 105.8 | 1,024.9 | negligible |
| `edit_file` | 0 | 0 | 0 | — | — | — | — |
| `write_file` | 0 | 0 | 0 | — | — | — | — |

`edit_file`/`write_file` are deliberately not in the default `openai-mcp` allowlist;
ChatGPT currently edits through `run_command`, so their lack of production evidence is
expected.

Argument logging is already sufficient for the simple read/list/status tools. In this
window `read_file`, `list_files`, `job_status`, and `stop_job` had no argument record over
the 500-character tool-call clip. `search_text` exceeded it in only 10/1,537 calls, while
both `path` and `pattern` remained visible in every search call because compact argument
ordering keeps the useful short fields first. `run_command` is the exception: 4,383/8,222
calls exceeded the clip, which is why its dedicated hash/dispatch telemetry is justified.

## 3. Current strengths

### Shared middleware

Every tool already gets one correlated `tool_call` and one `tool_result` with:

- call/client/session/request/turn identity;
- compact arguments plus unclipped argument length;
- total duration and error class/text;
- result text/structured size and historical chars/4 token estimate;
- tokenizer count where enabled;
- lifted scalar/list outcome fields such as state, count, truncation, bytes, and entries.

For simple tools this is a strong base and should remain the primary telemetry surface.

### `run_command`, `job_status`, `stop_job`

These are now the reference implementation for lifecycle/correlation telemetry:

- `run_command_dispatch` records requested/bounded/effective wait, owner, owner instance,
  background decision/handoff reason, command hash and owner round-trip;
- manager timing separates launch/implementation from MCP-side round-trip, and stats pairs
  them by `job_id` to estimate transport/serialization overhead;
- start/exit/stop/recovery records preserve original call, job ID, owner instance and
  command hash;
- `job_status_timing` exposes blocking waits and phase costs;
- stats reports handoff mix, waiting, runtime, transport overhead, stop escalation and
  manager lifecycle.

No further broad logging pass is required here.

### Indexed/adaptive `search_text`

`search_dispatch`, indexed-context telemetry and adaptive-discovery telemetry are already
strong for those special paths. They record hashes instead of returned content, phase
latencies for indexed retrieval, result/package sizes, candidate/evidence behavior and
follow-up conversion.

## 4. Gaps by tool

### `read_file` — high-volume, low-latency; improve shared result telemetry only

Production behavior:

- 2,047/2,517 calls requested explicit ranges; 470 requested whole files;
- 36 results were truncated (19 whole-file requests, 17 ranged requests);
- only one line-clipping incident in the seven-day window;
- p95 latency is only ~9 ms, so phase timing would add noise without an optimization need.

The structured result already contains useful scalar facts that the shared middleware does
not currently lift: `fits_in_one_call`, `lossy`, `next_start_line`, and `mime_guess`.
These are exactly the facts needed to detect unnecessary slicing, decoding degradation and
continuation behavior. They should be lifted rather than adding a `read_file_*` event.

A further useful signal is a stable truncation reason (`char_budget`, `line_budget`, or
requested range). This can either be an internal telemetry-only field/event or an additive
result scalar, but it should not require logging content.

### `list_files` — adequate; low priority

Production behavior:

- 230 one-level listings and 31 recursive glob calls;
- only five truncated results, all in list mode;
- p95 ~18 ms and max ~142 ms.

Arguments already make list-vs-glob, `include_hidden`, glob and requested cap explicit.
The result logs count/truncation/entries but do not lift `mode`, and the payload does not
retain the total candidate count when truncated. The low-cost improvement is to lift
`mode`; if truncation analysis becomes important, add a telemetry-only/structured
`total_candidates` scalar. Dedicated rg/filter phase timing is not justified by current
latency evidence.

### `search_text` — highest-priority dedicated follow-up

Exact search is the main remaining multi-stage blind spot. Special indexed/adaptive paths
already have rich telemetry, but ordinary exact search only has total tool duration plus
`search_dispatch` and optional budget/adaptive events.

The seven-day long tail includes an exact call taking 20.4 s: 1,966 matches over Markdown,
with context and final response-budget trimming. Current records cannot tell whether time
was spent in ripgrep, JSON parsing/collection, a second auto-context ripgrep, context
attachment, adaptive construction, or budget shaping.

Add one summary event per exact search, not several phase events. It should report at least:

- `call`, `path_hash`, `pattern_chars`;
- number of ripgrep invocations and cumulative `rg_ms`;
- collect/parse/shaping timings where measurable without invasive instrumentation;
- requested/effective context and whether auto-context caused a second search;
- total matches / returned entries / matching files;
- pre-budget bytes and final result bytes;
- final strategy: `normal`, `adaptive`, `budget_trimmed`, `names_only`;
- truncated/budget-hit scalar.

This is the closest analogue to `run_command_dispatch`: it explains an internal decision
and latency breakdown that generic middleware cannot reconstruct.

### `job_status` / `stop_job` — already sufficient

`job_status_timing` plus the new stats aggregation directly measures blocking wait calls,
waits that return still-running, cumulative blocking state time and process-scan costs.
Stop requests are correlated to the original run and record TERM-to-KILL escalation.
No new event family is needed.

### `edit_file` / `write_file` — no production evidence; do not overdesign

These tools are not exposed to ChatGPT in the current client allowlist and have zero calls
in the observed window. Do not add dedicated telemetry now.

If/when clients use them, the shared result logger should lift the already-produced scalar
facts:

- `edit_file`: `match`, `first_change_line` (not the snippet);
- `write_file`: `previous_bytes` alongside existing `action` and `bytes`.

That is enough to quantify exact-vs-whitespace fallback and create-vs-overwrite behavior
before considering any dedicated event.

## 5. Cross-cutting gaps

### 5.1 Effective tool configuration is incompletely logged — high priority

Binnacle deliberately makes behavior configurable, but the startup `config` event does not
record all limits needed to interpret historical results. A later review should be able to
prove what limits were in force without assuming today's defaults from the same Git commit.

Add startup-only effective settings for behavior-changing limits, either as compact
per-tool config records or a deliberately bounded expansion of `config`. At minimum cover:

- `read_file`: max chars, lines, line chars, file bytes;
- `list_files`: default/cap results and rg timeout;
- `search_text`: default/cap results, timeout, line chars, result budget, auto-context and
  adaptive-discovery enablement;
- `run_command/jobs`: default/max wait, warm-up, quiet threshold and stop grace;
- edit snippet context if structured edit tools become active.

Do not log secrets, raw policy regexes, or large config objects. Counts/hashes are enough
where values are sensitive or verbose.

### 5.2 Stable error reason/code — high priority

The middleware currently aggregates errors mostly by exception class. All ordinary tool
validation/runtime failures are `ToolError`, so stats can say `read_file: ToolError = 20`
but cannot directly say why.

Introduce a stable, low-cardinality internal error code while leaving user-visible error
messages unchanged. Examples:

- common path layer: `path_resolve_failed`, `path_outside_root`;
- read: `not_found`, `wrong_type`, `file_too_large`, `range_invalid`,
  `range_past_end`;
- list: `not_found`, `wrong_type`, `rg_missing`, `timeout`, `rg_failed`, `invalid_glob`;
- search: `empty_pattern`, `not_found`, `rg_missing`, `timeout`, `invalid_regex`,
  `invalid_glob`, `indexed_args_invalid`, `response_budget_exceeded`;
- jobs: `job_not_found`, `owner_unavailable`, etc.

A small `ToolError` subclass/helper carrying `telemetry_code` is preferable to parsing
human error text. `ToolLoggingMiddleware` can lift `error_code` when present; existing
messages/tests continue to see a `ToolError` subclass. Roll it out incrementally rather
than converting every error site in one commit.

## 6. Low-cost shared-result improvements

Before adding more special events, extend the shared scalar lift list with fields that are
already generated and low-cardinality:

- `runtime_s`, `last_output_age_s` where useful;
- `fits_in_one_call`, `lossy`, `next_start_line` for `read_file`;
- `mode` for `list_files`;
- `match`, `first_change_line` for `edit_file`;
- `previous_bytes` for `write_file`.

Do **not** lift full path/content/note/snippet/log text into `tool_result`; arguments and
structured-size accounting already cover those without duplication.

## 7. Recommended implementation order

### Phase A — shared telemetry hardening (low risk)

1. Lift the existing low-cardinality result fields above.
2. Log effective per-tool behavioral limits at startup.
3. Add stable error-code plumbing to middleware plus the common path layer and the three
   heavily used read/list/search tools.
4. Extend `binnacle stats` with error-code counts and useful read-result counts
   (`whole/range` can be reconstructed from arguments; truncation/fits/lossy from results).

This phase requires no new per-call event for `read_file` or `list_files`.

### Phase B — exact-search decision/timing telemetry (high value)

1. Add a small timing accumulator around exact search internals.
2. Emit one terminal `search_exact`/`search_exact_timing` summary event per exact call.
3. Preserve current indexed/adaptive event schemas for historical comparison.
4. Add stats percentiles for exact rg time, total exact implementation time, second-rg
   auto-context rate, final result strategy and budget-hit rate.
5. A/B against the existing journal to ensure instrumentation itself has negligible cost.

### Phase C — evidence-driven follow-up only

Do not add edit/write phase telemetry or list/read micro-timing unless actual usage/latency
shows a need. Do not add high-frequency CPU/RSS/IO sampling in this pass.

## 8. Overall assessment

| Area | Current quality | Action |
| --- | --- | --- |
| Shared `tool_call/tool_result` | Strong | extend scalar/error/config facts |
| `run_command` lifecycle | Excellent | maintain only |
| `job_status` / `stop_job` | Excellent | maintain only |
| indexed/adaptive search | Strong/Excellent | maintain schemas |
| exact `search_text` | Fair/Strong | add one decision/timing summary |
| `read_file` | Strong | shared-result fields, no new event |
| `list_files` | Adequate/Strong | lift mode/total if needed, no new timing event |
| `edit_file` / `write_file` | Unknown (no current ChatGPT use) | low-cost scalar lift only |
| effective config provenance | Fair | improve at startup |
| error reason aggregation | Weak | stable error codes are the largest cross-tool gap |

The next implementation should therefore **not** be “make every tool look like
`run_command`”. The correct target is a common high-quality telemetry baseline plus
specialized events only where the tool contains hidden internal decisions that matter to
performance or retrieval quality.
