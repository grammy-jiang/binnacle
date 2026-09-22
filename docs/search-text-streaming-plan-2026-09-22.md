# Exact search streaming / single-pass execution plan

Status: design only. No production implementation in this branch.
Baseline: `f937c75` (Phase B exact-search telemetry live and validated).

## 1. Why this phase exists

Phase B established that `orjson` itself is working normally, but the exact-search pipeline
still materializes far more intermediate state than the final result requires. The next
optimization should therefore change **how rg JSONL is consumed**, not continue tuning
`orjson.loads()` in isolation.

The target is a behavior-equivalent streaming reducer:

```text
rg stdout bytes
    -> incremental JSONL parse (`orjson.loads(bytes)`)
    -> single-pass glob decision / result collection
    -> retain only accepted match facts needed by adaptive ranking
    -> final result shaping
```

The MCP input/output schema, rg search semantics, glob semantics, result ordering for one rg
invocation, context policy, adaptive ranking, result budgets, and indexed `@context` path
must remain unchanged.

## 2. Evidence

### 2.1 Official-style `orjson` loads benchmark on this Pi 5

The current orjson repository's `benchmark_loads.py` feeds **bytes** directly to every
loader. Its fixtures are single complete JSON documents, and its benchmark utilities pin
CPU affinity and disable/freeze GC. Replaying the same four fixtures on this host
(Python 3.13.5, orjson 3.12.0, aarch64) produced:

| Official fixture | stdlib/orjson speed ratio on Pi 5 |
| --- | ---: |
| `github.json` | 1.93x |
| `twitter.json` | 2.04x |
| `citm_catalog.json` | 2.07x |
| `canada.json` | 3.59x |

This is consistent with the lower end of orjson's deserialization benchmark range. The
very large headline multipliers often associated with orjson are primarily serialization
results and/or different x86 hardware/fixtures. There is no evidence that the installed
orjson build is malfunctioning.

### 2.2 Current input form leaves performance on the table

Current Phase B exact search still uses:

```text
subprocess.run(..., capture_output=True, text=True)
    -> full stdout UTF-8 decode to Python str
    -> str.splitlines()
    -> orjson.loads(str) per JSONL record
```

For the ~162.3 MB / 309,733-line historical broad query, parser-only measurements gave
median values around:

- `orjson.loads(bytes)` path: ~4.31 s;
- explicit decode + `orjson.loads(str)`: ~4.96 s;
- stdlib `json.loads(str)`: ~8.90 s.

A four-round `_run_rg` A/B gave median `subprocess + parse` around 8.43 s on the current
text path vs 7.18 s on the binary path (~15% lower). Peak RSS in full-search binary-path
POCs was also ~17% lower than the current text path.

The bytes conversion is worth doing, but it is not the dominant remaining opportunity.

### 2.3 Streaming and per-file glob cache POC

Same historical broad query, same final payload SHA-256
`1c5c67ffc66efd8eeb43a3f3bb8cfed059f4a6197350f5d6db78518b4f2e4194`:

| Prototype | Wall time (representative) | Peak RSS |
| --- | ---: | ---: |
| Phase B materialized pipeline | ~31.6 s | ~1,099,280 KiB |
| binary streaming, no full event list | ~21.6 s | ~91,824 KiB |
| streaming + per-file glob cache | 2.86–2.96 s | ~90–91 MiB |

The streaming+cache prototype processed 309,733 events but invoked the actual glob matcher
only 1,994 times (once per distinct file), instead of ~305,744 event-level glob decisions.
It retained 2,464 accepted match events for adaptive ranking rather than all raw events.

The absolute wall-time ratio is host/load/cache-sensitive and must not be treated as a
production guarantee. The magnitude and memory reduction do establish the architectural
priority.

### 2.4 Same-raw semantic equivalence

To remove rg's cross-invocation ordering variability, one rg byte stream was fed to both
materialized and streaming reducers.

- fast fixture: identical payload SHA; Python processing 46.5 ms -> 8.4 ms (~5.5x);
- medium fixture: identical payload SHA; 1733 ms -> 215 ms (~8.1x).

This is stronger evidence than comparing two independent rg invocations when `max_results`
can expose nondeterministic traversal order.

## 3. Design principles

1. **One rg event is parsed once and consumed once.**
2. **Glob semantics are unchanged**, but the decision is cached per path within one call.
3. **No complete rg event list** in the production streaming path.
4. **No full stdout buffer or Unicode decode** in the streaming path.
5. **Adaptive ranking remains unchanged in V1.** It receives only already-glob-accepted
   match events, in their original stream order, with `glob=None` so it does not repeat the
   filter.
6. **Context semantics remain unchanged in V1.** Keep the accepted line map and use the
   existing `attach_context` implementation after the stream completes.
7. **True total match count is preserved** even after `max_results` is reached; the stream
   must always be fully consumed unless it errors/times out.
8. **Timeout and process reaping are non-negotiable.** A naive blocking generator is not
   acceptable.
9. **Old materialized execution remains an internal rollback/A-B path** through a config
   switch during rollout.

## 4. Proposed architecture

```text
_search_exact_impl
       |
       +-- execution_mode=materialized  (rollback/reference)
       |
       `-- execution_mode=streaming
              |
              v
       RgJsonStream (binary Popen)
              |
              | bytes JSONL
              v
       ExactStreamReducer.consume(event)
              |
              +-- per-file glob cache
              +-- retained normal matches (<= max_results)
              +-- true total match count
              +-- accepted line_map (match/context)
              `-- accepted match events for existing adaptive builder
              |
              v
       ScanResult
              |
              +-- attach_context (existing)
              +-- names_only (existing)
              +-- adaptive builder (existing ranking, glob=None)
              `-- budget shaping (existing)
```

## 5. Component design

### 5.1 `RgJsonStream`

New focused module, e.g. `search_text_stream.py`.

Responsibilities:

- build the exact existing rg command;
- `Popen(stdout=PIPE, stderr=<non-pipe file>, text=False)`;
- yield decoded JSON **objects** one line at a time using `orjson.loads(bytes)`;
- maintain event/output-byte counters;
- enforce the existing per-rg timeout;
- kill and reap rg on timeout or consumer exception;
- validate return code after EOF;
- expose `no_match` for return code 1;
- decode only the bounded stderr tail when constructing an rg error message.

It must not know glob, max_results, adaptive ranking, context shaping, or MCP result schema.

### 5.2 Timeout / stderr safety

`for line in proc.stdout` alone loses `subprocess.run(timeout=...)` semantics. The new
runner must restore them explicitly.

Recommended first implementation:

- stderr goes to a `TemporaryFile`/bounded spooled file, **not `stderr=PIPE`**, so a large
  stderr cannot deadlock while stdout is consumed;
- a lightweight watchdog timer owns the absolute deadline; when it fires it records
  `timed_out=true` and kills rg;
- the stdout iterator then reaches EOF, the owner thread reaps the process, cancels the
  timer, and raises the existing `rg_timeout` coded error;
- if the reducer raises (for example invalid glob), the stream context manager kills/reaps
  rg immediately and re-raises the original reducer error rather than masking it.

Before choosing the watchdog implementation permanently, benchmark its fast-path overhead.
If thread/timer creation violates the fast-search gate, use a selector/nonblocking-fd
runner instead. **Do not ship a timeout-free generator.**

### 5.3 `ExactStreamReducer`

New class in `search_text_collect.py` or a small `search_text_stream_reduce.py` module.

Per-call state:

```text
root / glob / max_results
matches                 first max_results accepted matches, in stream order
line_map                accepted match/context lines for context attachment
total                    all accepted match events
truncated                total > max_results
accepted_match_events    accepted raw match events only, for V1 adaptive builder
glob_cache               file path -> bool, only when glob is present
accepted_files           set/count for telemetry
```

`consume(event)`:

1. ignore event types other than match/context;
2. resolve/calculate glob decision **once per distinct path**;
3. rejected event: increment rejected-event telemetry and discard immediately;
4. accepted event: record line text in `line_map`;
5. accepted match: increment true total, append compact normal match if below cap, and
   append the match event to `accepted_match_events` if adaptive may be required.

The reducer performs no serialization, ranking, budget logic, or logging.

### 5.4 Adaptive V1 integration

Do **not** rewrite adaptive ranking in the first streaming implementation.

Instead of:

```text
build_adaptive_result(all_rg_events, glob=original_glob)
```

call:

```text
build_adaptive_result(accepted_match_events, glob=None)
```

Rationale:

- `_collect_files` only consumes `match` events anyway;
- accepted events already passed exactly the same glob matcher;
- event order is preserved;
- broad POC and medium POC produced identical payload hashes;
- this removes the second glob-filter pass without changing ranking logic;
- it keeps the previously deferred “rewrite adaptive around shared normalized facts” out of
  V1.

A future V2 may replace accepted raw match events with normalized adaptive facts, but only
if telemetry shows the retained accepted-match list is still material.

### 5.5 Context V1 integration

Keep the current `line_map` + `attach_context` behavior. Although a more advanced reducer
could use rolling per-file context buffers, that creates substantially more ordering/state
risk and is not necessary to capture the large observed memory gain.

This means V1 still retains accepted match/context text in `line_map`; it no longer retains
rejected-file context or nested raw event dicts.

## 6. Compatibility / semantic invariants

The streaming path must preserve:

- rg command flags and ignore/hidden behavior;
- fixed-string vs regex behavior;
- Python-side positive-glob semantics (no accidental gitignore whitelist);
- exact stream order for retained matches from a single rg invocation;
- true `count` even when `max_results` truncates entries;
- existing truncation note/summary wording;
- names-only grouping/count behavior;
- line-number context formatting;
- automatic second-rg context policy;
- adaptive ranking/representative selection and notes;
- response-budget behavior;
- all Phase-A error codes/messages;
- indexed `@context` path untouched;
- MCP input/output schemas unchanged.

## 7. Compatibility seam and rollout switch

Add a generic repository setting, e.g.:

```toml
[search_text]
exact_execution = "materialized"  # or "streaming"
```

During development:

- repository default remains `materialized`;
- local development config can opt into `streaming` for shadow/A-B tests;
- startup `tool_config` records the effective mode;
- Phase-B `search_exact` event records `pipeline=materialized|streaming`.

After all gates pass and a short observation window is clean, flip the repository default to
`streaming`. Keep materialized mode for at least one release/rollback window before removal.

The setting is generic product behavior, not ChatGPT-specific preference.

## 8. Telemetry migration

Streaming makes current Phase-B timing categories partly overlapping, so do not silently
reuse field names with changed semantics.

### Keep

- `impl_ms`;
- context/adaptive/budget timings;
- event counts;
- accepted matches/files;
- final result size/strategy/budget outcome.

### New streaming fields

- `pipeline=streaming`;
- `rg_stdout_bytes` (not the old `rg_stdout_chars`);
- `rg_wall_ms`: spawn-to-exit wall time including concurrent streaming ingestion;
- `stream_cpu_ms`: Python current-thread CPU time across parse/reduce loop;
- `glob_cache_hits`;
- `glob_cache_misses` (actual matcher calls);
- `glob_rejected_files`;
- `glob_rejected_events`;
- `adaptive_retained_match_events`;
- optionally `stderr_bytes`/`timed_out` on error summaries.

### Historical fields

Materialized summaries retain `rg_subprocess_ms`, `rg_parse_ms`, `collect_ms`, and
`rg_stdout_chars`. Streaming summaries must not pretend `rg_wall_ms` is equivalent to their
sum: parsing/reduction happens concurrently with rg execution.

`binnacle stats` should render the two pipeline generations separately when mixed in one
window, while common work/result counters can still be compared.

## 9. Testing strategy

### 9.1 Same-raw reducer equivalence (highest-value test)

Capture one deterministic rg byte stream once, then feed the identical lines to:

- existing materialized `list[dict] -> collect -> adaptive` reference path;
- streaming reducer path.

Compare complete structured payload bytes/hash, not merely counts.

Matrix:

- no match;
- fixed string / regex;
- file scope / directory scope;
- no glob / positive glob;
- context 0 / explicit context;
- line_numbers on/off;
- max_results below/above total;
- names_only;
- Unicode source lines;
- adaptive selected;
- adaptive unavailable -> ordinary budget fallback;
- ordinary budget entry trim;
- context-omitted budget outcome.

### 9.2 Property-style reducer tests

Generate small synthetic rg event streams and assert materialized `_collect` and
`ExactStreamReducer` produce identical `matches`, `line_map`, total, and truncation. Include
repeated paths to verify glob cache semantics.

### 9.3 Process lifecycle tests

- rg executable missing -> same `rg_missing`;
- invalid regex -> same `rg_rejected` text/code;
- no match -> return code 1 and empty result;
- timeout -> same `rg_timeout` and process reaped;
- reducer exception -> child killed/reaped, original error preserved;
- stderr larger than pipe capacity -> no deadlock;
- process exits while stream is partially consumed;
- no zombie process after any failure.

### 9.4 Auto-context

First streaming rg with no context, second streaming rg after 1–3 matches. Final payload
must equal the existing materialized path and telemetry must report `rg_calls=2`.

### 9.5 Existing suites

Run exact search, adaptive discovery, indexed context, Phase-B telemetry/stats, Phase-A
error/config telemetry, protocol/contracts, usage-analysis scripts, then full pytest and
full pre-commit.

The three known adaptive-budget tests remain baseline failures unless fixed in a separate
change.

## 10. Performance / memory acceptance gates

Use the same host and fixed workloads; alternate old/new order to reduce thermal/cache
bias.

### Fast path

No regression:

- p50 added latency <1 ms and <=5%;
- p95 no stable >5% regression.

### Medium historical workload

POC from the same raw stream showed ~8.1x Python-processing improvement, and independent
end-to-end runs showed ~4x. Set a conservative release gate of **>=2x end-to-end speedup**
with identical final payload hash.

### Broad historical workload

POC showed ~31.6 s / ~1.10 GiB current vs ~2.9 s / ~90 MiB streaming+cache. Set conservative
release gates:

- **>=2x end-to-end speedup** across repeated alternating runs;
- **>=60% peak-RSS reduction**;
- identical final structured payload hash/count/truncation/note.

The implementation need not reproduce the POC's ~10x ratio to be accepted; the gate is
intentionally robust to concurrent Pi load.

### Instrumentation overhead

No per-event timer, logger, hash, or allocation solely for telemetry. Counters increment in
the reducer. Use `time.thread_time_ns()` once around the full streaming-consume loop for
`stream_cpu_ms` rather than timing every event.

## 11. Implementation stages

1. **S0 — design freeze / baseline:** this document; record current Phase-B fast/medium/
   broad timing, RSS, and payload hashes.
2. **S1 — process stream primitive:** binary Popen, timeout/reap/stderr safety, JSONL event
   iterator; no search integration yet.
3. **S2 — streaming reducer:** normal matches/context/true total + per-file glob cache;
   equivalence against materialized `_collect` on identical event streams.
4. **S3 — exact-path integration behind config:** normal/names-only/context results use
   streaming; materialized remains default/reference.
5. **S4 — adaptive V1:** retain accepted match events and pass them with `glob=None` to the
   existing builder; same-raw payload hash tests.
6. **S5 — auto-context / error lifecycle:** second stream, timeout, invalid regex/glob,
   child cleanup and telemetry.
7. **S6 — telemetry/stats versioning:** pipeline field, bytes/wall/CPU/cache metrics and
   mixed materialized/streaming stats.
8. **S7 — controlled A/B + memory gate:** fast/medium/broad repeated tests; payload hash,
   latency and RSS gates above.
9. **S8 — full quality gates:** full pre-commit and full pytest baseline-equivalence.
10. **S9 — live shadow:** opt local config into streaming; controlled normal/broad/error
    searches; journal/stats/doctor review.
11. **S10 — default flip:** only after live evidence; change repository default to
    streaming, keep materialized rollback for one observation/release window.
12. **S11 — later cleanup:** remove materialized path only after evidence shows rollback no
    longer needed.

## 12. Explicit non-goals for V1

Do not combine the first streaming implementation with:

- changing rg's positive-glob arguments;
- changing ignore/hidden semantics;
- changing context generation or doing a match-only/context-second-pass search;
- changing adaptive ranking or candidate selection;
- replacing accepted match events with a new adaptive normalized-facts algorithm;
- changing budgets/max_results/auto-context thresholds;
- per-search CPU/RSS sampling in production;
- fixing the three existing adaptive-budget test-isolation failures;
- indexed-context changes.

The per-file glob cache **is** part of V1 because the same-path decision is pure and the POC
shows it is the dominant repeated CPU work. Its semantic equivalence receives dedicated
property/same-raw tests.

## 13. Future optimization record

After V1 telemetry/observation, retain these hypotheses without implementing them yet:

1. replace accepted raw match events with normalized adaptive facts and eliminate the small
   second adaptive scan;
2. reduce rg context-event generation before Python filtering (requires search-semantic
   design, not just ingestion refactoring);
3. bounded/rolling context storage for accepted files if no-glob broad searches still show
   material line-map memory;
4. lower-level chunked/nonblocking reader only if watchdog-thread overhead matters;
5. investigate ordering controls only if cross-invocation result order becomes a product
   concern; do not sort results casually because that changes current semantics.

## 14. Recommendation

Proceed with V1 exactly as staged above. The evidence is unusually strong:

- the library-level `orjson` performance is normal for this Pi;
- bytes input is better but only incremental;
- streaming removes the giant intermediate object graph;
- per-file glob caching removes hundreds of thousands of repeated equivalent decisions;
- same-raw tests already demonstrate payload equivalence on fast and medium workloads;
- broad POC preserves the final payload hash while cutting both wall time and memory by a
  large margin.

The safest high-value implementation is therefore **binary streaming, a single-pass reducer, and a per-file glob cache**, with existing
adaptive ranking retained behind an accepted-match
compatibility bridge.

## 15. Implementation validation (feature/search-streaming)

The implementation through S7 preserved the materialized backend as the repository
default while adding the streaming backend behind `search_text.exact_execution`.

### 15.1 Process and reducer correctness

- `RgJsonStream` has dedicated coverage for bytes JSONL, malformed records, missing rg,
  timeout kill/reap, consumer exceptions, large stderr without pipe deadlock, rg rejection,
  early consumer exit, and the case where rg exits before the deadline but the Python
  consumer intentionally drains buffered output slowly.
- The timeout watchdog marks a timeout **only when the child is still alive at the
  deadline**. This preserves the previous subprocess timeout meaning as closely as possible
  without incorrectly timing out post-exit Python processing.
- `ExactStreamReducer` is property-tested against the materialized collector across
  generated match/context/begin/end streams, glob/no-glob, and different max-result caps.
- Normal, names-only, explicit-context, auto-context, truncation, and adaptive searches have
  materialized/streaming equivalence tests. The adaptive bridge passes only already-accepted
  match events with `glob=None` to the existing ranking implementation.

### 15.2 Fast-path A/B

Four alternating rounds, 80 measured calls after warm-up per workload, same commit and
search target:

| Workload | Materialized p50 | Streaming p50 | Result |
| --- | ---: | ---: | --- |
| literal `event=`, `*.py`, context=0 | 16.48–16.99 ms | 12.39–12.59 ms | streaming faster |
| regex `event=|logger`, `*.py`, context=2 | 40.78–41.35 ms | 15.30–15.97 ms | streaming much faster |

No watchdog/timer regression is visible; the `<1 ms / <=5%` no-regression gate is passed
with large margin.

### 15.3 Medium historical workload

Two fresh-process alternating runs, identical structured payload SHA
`ceb3fdc73ef1bdb9d226fa7442694b0a1a9be17b951af333900d096f0cd761e1`:

| Backend | Wall time | Peak RSS |
| --- | ---: | ---: |
| materialized | 1508.9–1516.5 ms | 202,960–203,504 KiB |
| streaming | 385.4–414.6 ms | 83,568–84,064 KiB |

This is ~3.6–3.9x faster with ~59% lower peak RSS, passing the conservative >=2x gate.

### 15.4 Broad historical workload

Two fresh-process alternating runs, identical structured payload SHA
`1c5c67ffc66efd8eeb43a3f3bb8cfed059f4a6197350f5d6db78518b4f2e4194`, identical
`count=2464`, 135 returned entries, and `truncated=true`:

| Backend | Wall time | Peak RSS |
| --- | ---: | ---: |
| materialized | 19,958–20,715 ms | 1,099,456–1,102,112 KiB |
| streaming | 1,486.7–1,561.1 ms | 90,368–91,232 KiB |

The measured speedup is ~12.8–13.9x and peak RSS is ~92% lower. The release gates require
only >=2x and >=60% RSS reduction, so the implementation exceeds both by a wide margin.
These ratios are observations on this host/workload, not a universal performance promise.

### 15.5 Streaming as the prospective default

Running the search-related test surface with
`BINNACLE_SEARCH_TEXT__EXACT_EXECUTION=streaming` now leaves only the same three
pre-existing adaptive-result-budget failures already present on the materialized baseline.
Tests that intentionally monkeypatch materialized internal seams are explicitly pinned to
the materialized backend; streaming has its own error-lifecycle tests.

The next gates are full pre-commit, full pytest baseline-equivalence, then a live shadow
period with local `exact_execution=streaming` before the repository default is flipped.
