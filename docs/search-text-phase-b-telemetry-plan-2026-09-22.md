# `search_text` Phase B — exact-search telemetry plan

Status: investigation/design only. Production exact-search behavior is unchanged by this
plan. Implementation starts only after this plan is reviewed.

## 1. Objective

Phase B closes the remaining observability gap in ordinary exact `search_text` execution.
Indexed `@context` and adaptive-discovery paths already have specialized telemetry; exact
search currently exposes only whole-tool duration, `search_dispatch`, and occasional
budget/adaptive events. That is insufficient to explain long-tail latency or quantify the
amount of work discarded by Python-side filtering.

The target is **one terminal exact-search summary event per exact call**, carrying coarse
stage timings plus low-cost work counters. It must answer:

- was time spent in ripgrep, JSON parsing, Python collect/glob filtering, adaptive
  representation, or budget shaping;
- how much raw rg output was produced compared with useful accepted matches/files;
- whether auto-context caused a second rg invocation;
- which final representation/strategy was returned;
- how much Python-side work amplification occurred before the bounded MCP result;
- whether a failure happened after partial work and in which stage.

Phase B is telemetry, not a search-algorithm optimization.

## 2. Current exact-search pipeline

For a normal (non-`@context`) call, current `search_text_impl` performs:

```text
validate / resolve path
        |
        v
search_dispatch(mode=exact)
        |
        v
_run_rg(root, pattern, fixed_strings, explicit_context)
        |-- subprocess.run(rg --json ...)
        `-- splitlines + json.loads for every rg JSON line
        |
        v
_collect(events)
        |-- inspect match/context events
        |-- Python-side glob filtering via full_match
        |-- retain at most max_results match entries
        `-- still count/process all matching events
        |
        +--> optional auto-context decision
        |       `-- if 1-3 matches and context omitted: run rg + collect again
        |
        v
_attach_context
        |
        v
assemble ordinary payload
        |
        v
structured_bytes(payload)
        |
        +--> adaptive discovery if enabled and payload > budget
        |       `-- rescan match events, glob-filter again, rank files, fit budget
        |
        `--> ordinary _enforce_result_budget otherwise
                `-- binary-search complete entry prefix
```

The 64 KiB budget limits what the model receives; it does **not** limit rg's internal JSON
output or the Python working set that constructs the result.

## 3. Production evidence

### 3.1 Classified window

`search_dispatch` first appeared at **2026-09-19 20:28 +10:00**. From then through the
final investigation snapshot on **2026-09-22 ~17:54 +10:00**:

- 737 dispatches had corresponding results;
- **727 exact**;
- **10 indexed**.

Exact-search latency:

| Metric | Value |
| --- | ---: |
| p50 | 13.3 ms |
| p95 | 95.5 ms |
| max | 20,412.1 ms |
| >=100 ms | 33 calls |
| >=500 ms | 6 calls |
| >=1 s | 5 calls |

Exact-call shape in the earlier 715-call snapshot used for detailed argument analysis:

- 654/715 (91%) explicitly requested `context_lines > 0`;
- 223/715 used a glob;
- 32 omitted `context_lines`;
- only **5 calls** can be inferred to have triggered auto-context's second rg invocation;
- 11 used adaptive representation;
- 29 hit the ordinary response-budget path;
- 48 returned `truncated=true`.

The final-result strategy distribution in that snapshot was:

| Strategy | Calls |
| --- | ---: |
| normal | 604 |
| no match | 57 |
| budget trimmed | 29 |
| adaptive | 11 |
| max-results truncated | 8 |
| names-only | 6 |

The common fast path therefore dominates. Telemetry must keep normal-call overhead tiny.

### 3.2 Long-tail correlation

All six exact searches over 500 ms used explicit context and a glob. Five exceeded one
second. Four of the five >=1 s calls also emitted `search_budget_hit`; broad contextual
search is the main long-tail shape, not auto-context.

The historical maximum was:

```text
path: python-migration-atlas-cpython-completion
pattern: 13-way alternation
context_lines: 1
glob: *.md
max_results: 400
result: 1,966 accepted matches; response-budget trimmed
whole-tool latency: 20.4 s
```

## 4. Phase profiling findings

Profiling was performed outside production code, using the same current implementation and
historical queries. Wrapper-heavy measurements were used only for call counts; direct
coarse-stage timings were then run without per-event timers.

### 4.1 Historical worst case

For the historical 20.4 s shape, a current equivalent run produced:

| Stage / volume | Measurement |
| --- | ---: |
| rg subprocess | ~0.95 s |
| JSON parse | ~5.04 s |
| `_collect` + Python glob filtering | ~11.21 s |
| context attach | ~17 ms |
| adaptive build | ~4.35 s |
| ordinary budget shaping | ~8.5 ms |
| raw rg JSON | **162.3 MB** |
| JSON lines/events | **309,733** |
| raw match events | 108,291 |
| raw context events | 197,453 |
| files represented by rg match/context events | 1,994 |
| matches accepted after Python glob | ~2,464 |
| accepted files | 10 |

These phase durations overlap conceptually when helper timings are summed, so they are not
a decomposition of one wall clock. They nevertheless establish the dominant work sources:
JSON parse, event collection/glob filtering, and a second event scan during adaptive build.
Context attachment and final budget binary search are negligible by comparison.

A direct raw-rg measurement on the same shape reported:

```text
stdout = 162,306,768 bytes
JSON lines = 309,733
match events = 108,291
context events = 197,453
rg subprocess ~= 2.5 s in that run
json.loads loop ~= 9.7 s in that run
```

Absolute times vary with cache/load, but the work-volume counts are stable enough to guide
telemetry design.

### 4.2 Smaller long-tail comparisons

A historical ~2.9 s shape generated about 22.8 MB / 20,096 JSON events; direct profiling
showed roughly 0.35 s rg, 0.73 s parse, 0.77 s collect, 0.13 s adaptive build.

A historical ~1.7 s shape generated about 6.4 MB / 3,528 events; profiling showed roughly
0.44 s rg, 0.08 s parse, 0.12 s collect, 0.04 s adaptive build.

The trend confirms that **raw rg event volume is a much better explanation of exact-search
latency than final returned match count alone**.

## 5. Important semantic constraint: glob pushdown

A tempting future optimization is to pass the user glob directly to `rg`. On the worst
historical shape, an experimental `rg --glob '*.md'` reduced rg output from roughly
162 MB / 309k events to **2.28 MB / 6,462 events**, and the rg subprocess from roughly
918 ms to 30 ms in that run.

This is **not safe to introduce in Phase B**. The installed ripgrep 14.1.1 help explicitly
states that `-g/--glob` "always overrides any other ignore logic." A controlled Git repo
confirmed the semantic risk:

```text
.gitignore: ignored.md
plain rg: kept.md
rg --glob '*.md': ignored.md + kept.md
```

Therefore current Python-side include filtering is deliberate. The Phase B work-amplification
telemetry should make a future semantics-preserving glob-pushdown experiment measurable,
but Phase B does not change ignore behavior.

## 6. Proposed event: `search_exact`

Emit **one terminal root-log line for every exact search that reaches exact execution**.
Keep the existing `search_dispatch`, `search_budget_hit`, and
`search_adaptive_discovery` events for history/backwards compatibility.

No raw result content, path, pattern, glob, or context text is added.

### 6.1 Identity / inputs

| Field | Meaning |
| --- | --- |
| `call` | existing tool-call correlation id |
| `path_hash` | existing 12-hex resolved-path hash |
| `pattern_hash` | 12-hex SHA-256 prefix for repeated-pattern aggregation |
| `pattern_chars` | input pattern length |
| `glob_used` | boolean; raw glob stays in `tool_call` args |
| `glob_hash` | 12-hex hash when a glob exists, otherwise `-` |
| `fixed_strings` | literal vs regex |
| `names_only` | result mode |
| `max_results` | effective capped value |
| `context_requested` | `auto`, `0`, or requested positive integer |
| `context_effective` | final context span used for the returned pass |
| `auto_context` | whether a second rg invocation was caused by auto-context |

### 6.2 Work counters

Counters must be collected in loops that already exist; no per-event timing calls.

| Field | Meaning |
| --- | --- |
| `rg_invocations` | normally 1; 2 for auto-context |
| `rg_stdout_chars` | cumulative `len(stdout)`; call it chars, not bytes, to avoid an extra 100+ MB encode |
| `rg_json_lines` | cumulative stdout JSON lines |
| `rg_match_events` | raw rg match events |
| `rg_context_events` | raw rg context events |
| `rg_invalid_json` | ignored malformed JSON lines |
| `glob_checks` | match/context events tested by Python include-glob logic |
| `glob_rejected` | events rejected by the include glob |
| `accepted_matches` | final total match lines after glob filtering |
| `accepted_files` | files represented after Python filtering |
| `returned_entries` | final entry count handed toward the MCP result |

`binnacle stats` derives rather than logs additional ratios:

- raw-event amplification per accepted match;
- glob rejection percentage;
- rg-output chars per accepted match;
- context-event / match-event ratio.

### 6.3 Coarse timings

Use `time.perf_counter()` only around stage boundaries:

| Field | Scope |
| --- | --- |
| `rg_ms` | cumulative subprocess time across rg invocations |
| `parse_ms` | cumulative JSON split/parse loop |
| `collect_ms` | cumulative `_collect` passes |
| `context_ms` | `_attach_context` work |
| `prebudget_ms` | ordinary payload byte-size measurement / pre-budget shaping |
| `adaptive_ms` | `build_adaptive_result` when attempted, otherwise 0 |
| `budget_ms` | ordinary `_enforce_result_budget`, otherwise 0 |
| `impl_ms` | entire exact-search implementation interval |

Do **not** time `_matches_glob` per event. `glob_checks/glob_rejected` explains its work
volume without adding hundreds of thousands of clock reads.

### 6.4 Outcome

| Field | Meaning |
| --- | --- |
| `strategy` | stable low-cardinality terminal result strategy |
| `truncated` | final truth from result |
| `pre_budget_bytes` | assembled ordinary payload size before adaptive/budget representation |
| `error_code` | Phase-A coded error when exact execution fails, else `-` |
| `outcome` | `ok` or `error` |

Proposed `strategy` values:

- `normal`;
- `no_match`;
- `names_only`;
- `max_results_truncated`;
- `adaptive`;
- `budget_trimmed`;
- `budget_trimmed_names`;
- `error`.

Do not duplicate final structured bytes/tokens in this event. The correlated `tool_result`
already records `structured_bytes`, estimated/tokenizer tokens, entry count and truncation.
The stats analyzer can join by `call`.

## 7. Error semantics

A terminal exact event should also be emitted for failures **after exact execution begins**:
rg timeout/rejection/missing binary, invalid glob during event collection, or response
budget metadata failure. It should contain whatever counters/timings were known before the
exception and the stable Phase-A `error_code`.

Errors before exact dispatch (empty pattern, path guard/not-found) remain covered by
`tool_result.error_code`; they need no synthetic exact event.

Indexed-mode failures retain indexed telemetry and must not emit `search_exact`.

## 8. Runtime implementation shape

### 8.1 Do not grow `search_text.py`

`src/binnacle/tools/search_text.py` is already exactly 500 lines (the module hard gate), and
`search_text_impl` is already above the AI-readability target. Phase B must improve, not
worsen, that structure.

Introduce a small module such as:

```text
src/binnacle/search_text_exact_telemetry.py
```

containing a dataclass/accumulator with:

- immutable input identity;
- cumulative work counters;
- coarse stage timings;
- terminal outcome/strategy;
- exactly-once log emission.

A small behavior-preserving extraction of existing budget/exact helper code is acceptable
if needed to keep `search_text.py <= 500`, but must be its own checkpoint and pass existing
contract tests before instrumentation is added.

### 8.2 Preserve helper compatibility

Tests currently call `_run_rg` directly for error behavior, while adaptive tests call
`build_adaptive_result` directly. Instrumentation should use optional accumulator arguments
or thin compatibility wrappers rather than forcing unrelated tests/callers onto a new API.

### 8.3 No per-event log records

Never log every rg match/context event. One broad query can contain >300k events. The
accumulator performs integer increments only; one summary line is emitted at the end.

At the observed rate (~727 exact calls over ~69 hours), one additional bounded root-log line
per exact call is only on the order of a few hundred lines / roughly hundreds of KiB per
day, operationally negligible compared with result/journal volume.

## 9. Stats integration

Add a dedicated analyzer module, for example:

```text
src/binnacle/logstats_search_exact.py
```

and an `ExactSearchStats` dataclass in `logstats_models.py`. Keep the already-long main
renderer thin by delegating exact-search formatting/report construction.

`binnacle stats` should report:

### Calls / outcome

- exact calls and exact errors;
- strategy counts/rates;
- auto-context second-rg rate;
- adaptive rate;
- ordinary budget-trim rate;
- max-results truncation rate.

### Timing percentiles

For `impl_ms`, `rg_ms`, `parse_ms`, `collect_ms`, `adaptive_ms`, and `budget_ms`:

- n;
- p50;
- p90;
- p95;
- max.

`context_ms` and `prebudget_ms` can be shown only when their maxima/aggregate contribution
are material; the raw event still records them.

### Work amplification

Report distributions or totals for:

- rg stdout chars;
- rg JSON lines;
- raw match/context events;
- accepted matches/files;
- glob checks/rejections;
- raw events per accepted match;
- glob rejection percentage;
- context/match event ratio.

This is the most important new diagnostic category. It distinguishes "rg itself is slow"
from "rg produced far more data than the final filter needed."

### Join to `tool_result`

Join on `call` so exact-search stats can also compare:

- raw work vs final `structured_bytes`;
- raw work vs tokenizer/result tokens;
- strategy vs result size.

No second token/size calculation belongs in the runtime event.

## 10. Test-isolation prerequisite (B0)

Three existing result-budget tests currently fail on this development host because
`search_text.py` reads deployment-local settings at import time and the host config enables
adaptive discovery. Those tests intend to test **ordinary budget behavior**, but only
monkeypatch `SEARCH_RESULT_MAX_BYTES`; adaptive representation intercepts them.

Evidence: running only those three tests with
`BINNACLE_SEARCH_TEXT__ADAPTIVE_DISCOVERY_ENABLED=false` gives **3/3 passed**.

Before instrumentation:

1. make ordinary budget tests explicitly disable adaptive discovery;
2. keep adaptive tests explicitly enabling/configuring it;
3. do not change production defaults or deployment config;
4. require the full suite baseline to move from "3 known failures" to **zero unexpected
   failures** before Phase B telemetry is considered complete.

This is test isolation, not a product behavior change.

## 11. Test matrix for Phase B

### Exact runtime event

- normal regex search;
- fixed-string search;
- no match;
- file path and directory path;
- glob and no glob;
- `names_only`;
- explicit context 0 / positive context;
- auto-context one match and 2-3 matches (two rg invocations);
- max-results truncation;
- ordinary budget trim;
- adaptive representation;
- adaptive result itself budget-trimmed;
- first contextual entry too large and context omitted;
- timeout / invalid regex / missing rg / invalid glob / budget metadata failure.

Every case checks exactly one terminal `search_exact` event and no raw content/path/pattern
leak.

### Counter correctness

Use synthetic rg JSON events to assert:

- match/context/begin/end counts;
- invalid JSON count;
- glob checks and rejections;
- accepted match/file counts;
- returned entry count;
- cumulative counters across an auto-context second pass.

### Timing correctness

Monkeypatch `perf_counter` or stage functions rather than asserting real milliseconds.
Verify timings are non-negative and stage counters are updated once per actual stage.

### Stats parser/render

Synthetic journal samples cover:

- old windows with no `search_exact` event;
- mixed normal/adaptive/budget/error outcomes;
- work-amplification calculations;
- join to `tool_result` sizes/tokens;
- percentiles and zero-denominator cases.

### Existing contracts

Re-run exact search, adaptive discovery, indexed context, logging, protocol, usage-analysis,
and Phase-A error/config telemetry tests unchanged.

## 12. Performance A/B gate

Pre-Phase-B synthetic baseline on this Pi 5 (same current code):

| Scenario | p50 | p95 |
| --- | ---: | ---: |
| small exact, no context | 11.41 ms | 12.78 ms |
| explicit context + glob | 49.65 ms | 52.25 ms |
| auto-context (two rg passes) | 21.36 ms | 23.60 ms |

After instrumentation, rerun the identical fixture in an isolated worktree and compare
multiple batches, not one run.

Acceptance targets:

- small exact p50 added latency **<1 ms and <5%**; because 5% of 11.4 ms is ~0.57 ms,
  the stricter observed-relative threshold governs when stable;
- p95 should show no material regression beyond normal run variance;
- explicit-context/glob p50 regression <5%;
- broad historical/synthetic searches telemetry overhead <2% after repeated runs;
- no material increase in returned structured bytes/tokens (MCP schema/result unchanged);
- one extra summary journal record per exact call only.

If variance makes the <5% small-search threshold statistically unstable, compare repeated
batch medians and use the absolute <1 ms ceiling as the fallback decision gate.

## 13. Implementation stages

### B0 — fix exact/adaptive test isolation

Test-only change. Explicitly separate ordinary budget tests from deployment-local adaptive
settings. Establish a clean suite baseline.

### B1 — structure seam, behavior unchanged

Create telemetry/support module(s) and, if required by the 500-line hard gate, extract a
small exact/budget helper seam. No new runtime event yet. All existing search contracts must
pass byte-for-byte/field-for-field where applicable.

### B2 — exact accumulator and terminal event

Add coarse timers/counters and one `search_exact` terminal event. Preserve all existing
`search_dispatch`, `search_budget_hit`, and adaptive/indexed event schemas.

### B3 — stats analysis/render

Add dedicated exact-search analyzer/model/reporting, including work amplification and join
to `tool_result` sizes/tokens.

### B4 — A/B overhead and correctness gates

Run the fixed synthetic baseline, broad historical-shape smoke tests, module-size,
AI-readability, all search-related suites, full pre-commit, and full pytest.

### B5 — isolated live deployment observation

Merge only after B4. Let dev auto-reload the MCP server; no jobs-service restart should be
necessary because exact search runs in MCP. Generate controlled normal/glob/context/budget
calls and inspect `search_exact` plus `binnacle stats`. `binnacle doctor` must remain clean.

### B6 — observation window before optimization

Collect real telemetry for several days / at least hundreds of exact calls before changing
search execution. Use the new stats to choose the next optimization rather than optimizing
from the four profiling examples alone.

## 14. Explicit non-goals

Phase B does **not**:

- push `glob` into rg;
- change gitignore/hidden semantics;
- stream rg JSON instead of capturing stdout;
- eliminate the second adaptive event scan;
- change the adaptive representation/ranking algorithm;
- change auto-context thresholds;
- alter result budget or `max_results`;
- add MCP parameters or result fields;
- log raw pattern/path/glob/content;
- add CPU/RSS/IO sampling;
- tune performance based on the telemetry in the same change.

## 15. Follow-up optimization candidates exposed by this investigation

These are **not Phase B implementation items**. They should be prioritized only after the
observation window confirms production frequency/benefit.

1. **Semantics-preserving prefilter/pushdown for globs.** Potential benefit is enormous,
   but naive rg `--glob` is unsafe because it can re-include gitignored files. Any design
   must preserve current ignore semantics and pass explicit ignored-file gates.
2. **Streaming rg JSON parsing.** The worst case captured 162 MB before parsing; streaming
   could reduce peak memory and may permit earlier filtering, but timeout/process/error
   semantics become more complex.
3. **Avoid duplicate event scans.** Exact `_collect` and adaptive `_collect_files` both scan
   the same rg events and apply glob filtering. Reusing file/match facts could reduce broad
   adaptive cost.
4. **Earlier context strategy.** Explicit context dominates usage and contributes raw event
   volume. Any change must preserve current exact context semantics and result ordering.

The new work-amplification telemetry is specifically designed to measure these candidates.

## 16. Definition of done

Phase B is complete only when:

- exact/adaptive test isolation removes the three current baseline failures;
- every exact execution produces exactly one terminal summary event on success/error;
- no indexed call produces that event;
- no raw content/path/pattern/glob is added to the summary;
- stats explain phase latency and work amplification;
- normal-result MCP schema/content is unchanged;
- instrumentation passes the A/B overhead gate;
- module-size/readability gates do not regress;
- full pre-commit passes;
- full pytest has zero unexpected failures;
- live journal/stats validation confirms the schema on the managed dev server;
- production search semantics remain unchanged.
