# Binnacle MCP server performance review and improvement round — 2026-09-19

## Executive summary

This document is the round-level summary of the 2026-09-19 Binnacle MCP server
performance review. The issue-specific reports remain the source of truth for each
measurement; this report explains how the findings fit together, what was changed,
what the measured effect is, and how future reviews should be performed.

The review started from retained production journal evidence rather than speculative
optimization. It found two broad cost classes:

1. **Avoidable overhead/correctness risk in existing MCP tools** — very large
   `search_text` results, oversized `job_status()` listings, a job-store cap race,
   non-atomic metadata replacement, a Python 3.14 path/glob compatibility defect,
   and one unexplained `job_status` latency outlier.
2. **Repository-discovery inefficiency** — when the model does not know where an
   implementation lives, it often performs a broad search followed by multiple
   narrowing searches and reads. The first broad result itself can consume many
   thousands of model tokens.

The first class was fixed directly in production. The second class produced the
indexed-retrieval research program and the current explicit `@context` development
pilot.

Major outcomes:

- broad `search_text` structured responses are bounded to **65,536 UTF-8 bytes**;
- no-id `job_status()` returns all running jobs plus the newest 20 non-running jobs,
  with compact 160-character head/tail command previews;
- the job store now respects the configured base cap under concurrent starts and
  metadata replacement is atomic;
- Python 3.14 path/glob compatibility is fixed;
- the one historical 163.9-second `job_status` anomaly is now instrumented so a
  recurrence can be decomposed into dispatch/wait/tool stages without speculative
  semantic changes;
- explicit conceptual repository discovery is available as
  `search_text(pattern="@context ...")`, backed by persistent SQLite/FTS5 semantic
  nodes and typed relations;
- the final manually curated agent A/B preserved quality (**8/8 success and recall
  1.0 in both arms**) while reducing aggregate tool-result tokens **24.4%**, logical
  model input **41.5%**, calls **12.8%**, turns **12.3%**, API time **16.6%**, and
  reported Claude cost **25.1%**;
- replaying 18 real historical broad orientation searches reduced their first-hop
  payload from **179,018 to 31,821 tokens**, an **82.2%** reduction;
- `binnacle stats` now automatically displays indexed-context performance when such
  events exist, while preserving the old output for windows with no indexed calls;
- a 2026-09-19 capacity check shows the Pi has substantial headroom for several
  simultaneous ChatGPT development projects; local heavy build/test phases, not
  remote LLM thinking, are the likely contention point.

The indexed mode is intentionally **not automatic routing** yet. Normal `search_text`
remains exact regex/literal search. The development machine enables indexed retrieval
only when a caller explicitly uses the `@context` followed by a space prefix.

---

## 1. Scope and evidence

The review used:

- retained `binnacle-mcp` journal records back to 2026-08-26;
- per-call structured-result byte/token telemetry available from mid-September;
- replay of historical tool calls against surviving worktrees;
- direct Raspberry Pi 5 microbenchmarks;
- multi-Python test matrices (3.10–3.14);
- real production MCP checkpoints after each deployed maintenance change;
- a separate indexed-retrieval POC with corrected synthetic stress sets;
- isolated Claude-agent A/B sessions;
- a final manually curated, source-verified 8-task A/B;
- live `@context` calls through the actual ChatGPT Raspberry Pi MCP connector;
- a live 2026-09-19 system-capacity snapshot with six Claude project sessions
  already resident.

The central rule was: **do not optimize from intuition when production evidence can
measure the problem first.**

---

## 2. Baseline tool cost before this round

The retained workload is dominated by a small number of tools, but response-size
cost is not proportional to call count. In the recent historical window:

- `run_command` had the most calls;
- `read_file` and `job_status` were also frequent;
- `search_text` represented only about 8% of calls, but broad searches contributed a
  disproportionately large share of result tokens;
- blind no-id `job_status()` calls were rare after earlier description changes, but
  when they occurred they could return tens of thousands of tokens.

This distinction drove the round: optimize the **long-tail payload and repeated
orientation behavior**, not merely the most frequently invoked function.

---

## 3. `search_text` structured-result budget

### Problem

682 successful sized `search_text` results from the measured window showed a large
long tail:

- p50 ~1,611 estimated tokens;
- p90 ~8,875;
- p95 ~15,473;
- p99 ~38,733;
- largest historical structured result: **655,605 bytes / ~162k chars/4-estimated
  tokens** (replay measured roughly 170k `o200k_base` tokens).

The largest cases were broad explicit-context searches. Perfect overlap
De-duplication would not have been enough; a total payload budget was necessary.

### Change

`search_text.result_max_bytes` defaults to **65,536 UTF-8 bytes**. The budget is
server configuration, not an MCP parameter, so it adds no standing input-schema
cost.

When the budget binds:

- preserve match order;
- keep the full match count;
- return the largest complete prefix that fits;
- remove context before losing the first match identity when necessary;
- set `truncated=true` and return a narrowing note;
- log `event=search_budget_hit` correlated by call ID.

### Effect

Five replayed historical large searches all stayed below 65,536 bytes. Representative
exact token counts were roughly **15k–16.6k** after bounding, instead of ~27k–170k.
A normal small search remained byte-for-byte identical.

The broad result is predominantly an orientation step: about 90% of historical
results above 64 KiB were followed quickly by another search/read. This finding
became the motivation for the later indexed-retrieval work.

Detailed report:
`docs/usage-analysis-2026-09-19-search-text-result-budget.md`.

---

## 4. Compact `job_status()` listing

### Problem

No-id `job_status()` returned about 51 rows, including complete command strings. In
nine measured sized listings:

- median result size ~77 KiB;
- maximum ~188 KiB;
- combined estimate ~192k tokens;
- long command bodies represented most of the payload.

Observed follow-up selections did need both running and recently completed jobs, but
none needed a non-running job more than 15 starts deep.

### Change

The no-id list now returns:

- **all running jobs**;
- newest **20 non-running** jobs;
- newest-first relative ordering;
- `job_id/state/exit_code/runtime/started_at/workdir`;
- a **160-character head+tail command preview** rather than complete source.

Single-job `job_status(job_id=...)` still returns the full command.

### Effect

A live 51-job store became a 21-row response of about **7.2 KiB / 1,813 estimated
result tokens** in the production checkpoint. Historical no-id lists had reached
roughly 46k estimated tokens.

Detailed report:
`docs/usage-analysis-2026-09-19-job-status-listing.md`.

---

## 5. `job_status` latency anomaly observability

### Problem

One historical blocking status call requested a 50-second wait but took **163.891 s**.
The internal `waited_s` was only 50.429 s, leaving ~113 s of unexplained overhead.

Across 921 status results with `waited_s`, normal overhead was tiny:

- median ~12.9 ms;
- p90 ~23 ms;
- p99 ~66.7 ms;
- only one call exceeded 500 ms overhead.

This was therefore a single extreme outlier, not evidence that normal `job_status`
was slow.

### Change

Do not change wait semantics without evidence. Instead:

- elapsed timing uses monotonic clocks;
- middleware/tool timing identifies dispatch vs in-tool wait;
- `job_status_timing` telemetry makes a future recurrence decomposable.

FastMCP/AnyIO thread-pool queue delay remains a plausible mechanism, but the retained
history cannot prove that was the cause of the one old event.

Detailed report:
`docs/usage-analysis-2026-09-19-job-status-latency.md`.

---

## 6. Python 3.14 glob compatibility

The all-version suite exposed a pre-existing mismatch between the custom glob matcher
and Python 3.14 `PurePath.full_match`: `fnmatch.translate` changed its terminal regex
form from `\Z` to `\z`.

The helper now accepts both forms. Exhaustive comparison covered **34,592** cases with
zero mismatch. The fix was validated through both `list_files` and `search_text` on
live MCP paths.

Detailed report:
`docs/usage-analysis-2026-09-19-python314-glob-compatibility.md`.

---

## 7. Job-store cap and concurrency correctness

### Problem A — steady-state +1

`start_job()` previously pruned before creating the new job, so a configured
`keep_newest=50` naturally settled at 51 directories.

### Problem B — concurrent starts

Two starts could prune the same slot and then both create a new job, producing 52.
A real journal interleaving demonstrated this race.

### Problem C — non-atomic metadata replacement

`meta.json.write_text()` truncated the live metadata file before writing the new
record. Concurrent readers could observe invalid JSON and incorrectly report a real
job as absent. A stress probe reproduced hundreds of invalid/missing reads.

### Changes

- `_prune(reserve=1)` reserves the slot a new job is about to consume;
- a process-local `RLock` serializes prune → create → `Popen` → durable metadata;
- running jobs below the base recency window remain protected exceptions;
- metadata replacement uses same-directory temp file + atomic `os.replace()`;
- prune telemetry records `reserve` and `effective_keep`.

### Effect

A 20-round × 8-concurrent-start stress probe kept the store exactly at the base cap.
Atomic metadata stress went from hundreds of invalid/missing observations to **zero**.
The live store corrected itself from 51 to 50 on the first new launch; a three-client
real concurrent MCP checkpoint also remained at exactly 50.

Detailed report:
`docs/usage-analysis-2026-09-19-job-retention-cap.md`.

---

## 8. Indexed repository retrieval: why it was investigated

Bounding a broad search protects one response, but it does not eliminate the
orientation loop:

```text
broad search
  -> narrower search
  -> another search
  -> read file
  -> read another file
```

Historical analysis defined a conservative conceptual-orientation cohort: first
repository/directory-level search in a turn, location unknown, not a known-symbol
regex/file search, excluding temporary paths. These were only about **5.3% of
ChatGPT tool-using turns**, so indexed retrieval was never expected to reduce *all*
MCP calls by 20–30%. Its value is concentrated in the expensive discovery cases.

The original concern was also standing MCP schema cost: adding a seventh tool makes
every model invocation carry another tool definition. Research therefore tested
whether the capability could live on the existing `search_text` surface instead.

---

## 9. Indexed retrieval architecture

The final POC/pilot uses:

- persistent SQLite per Git worktree;
- contentless FTS5/BM25 over semantic nodes;
- Python functions/classes/modules, docs sections, and runtime-like config keys;
- definitions/references/identifiers;
- typed relations such as `call`, `doc_ref`, and `config_consumer`;
- relation provenance explaining why a candidate entered the package;
- incremental file replacement/re-resolution;
- a bounded model-facing package (default internal 8.5 KiB, generally below ~2.5k
  exact model tokens in the measured benchmark);
- a small LRU of open index connections.

Public MCP behavior stays on the existing tool:

```text
search_text(pattern="known_symbol")
    -> exact regex/literal search

search_text(pattern="@context where is this behavior implemented?", path=<git root>)
    -> indexed discovery package
```

No seventh tool and no new input/output field were required. A compact description
rewrite can explain `@context` with approximately flat or slightly smaller standing
schema cost.

---

## 10. Indexed quality and efficiency evidence

### Corrected benchmark discipline

Early synthetic dependency cases were audited and found to contain file-level rather
than symbol-level gold. Later audit also found documentation-neighbor and config-key
query ambiguity. Those benchmark defects were corrected before making product
claims. Synthetic sets are retained for stress testing, not treated as the final
quality judge.

### Primary evidence — manually curated 8-task A/B

Eight repository tasks were manually checked against source before the A/B. Both arms
used the same model, same read-only MCP tools, no Bash/grep bypass, alternating arm
order, and fresh sessions.

Quality:

- exact-search arm: **8/8 success, recall 1.0**;
- exact + `@context` arm: **8/8 success, recall 1.0**.

Efficiency:

| metric | exact-only | exact + `@context` | delta |
| --- | ---: | ---: | ---: |
| MCP calls | 47 | 41 | **-12.8%** |
| MCP result tokens | 55,970 | 42,329 | **-24.4%** |
| logical model input | 416,935 | 243,766 | **-41.5%** |
| turns | 65 | 57 | **-12.3%** |
| API duration | 161.5 s | 134.7 s | **-16.6%** |
| reported Claude cost | $0.660 | $0.494 | **-25.1%** |

### Historical first-hop replay

Across 18 replayable real orientation searches:

- current bounded broad search payload: **179,018 tokens** total;
- indexed context package: **31,821 tokens** total;
- first-hop reduction: **147,197 tokens = 82.2%**;
- average saving per indexed orientation use: **~8,178 tokens**.

This does not mean all Binnacle traffic becomes 82% cheaper. Conceptual repository
orientation is a small subset of turns. The expected real effect for suitable tasks
is closer to **10–15% fewer tool calls and 20–30% fewer tool-result tokens**, with
much larger savings on the broadest searches.

---

## 11. Development-machine live pilot

The feature is enabled only on this development machine:

```toml
[indexed_context]
enabled = true
reconcile_on_query = true
max_open_indexes = 2
```

Repository defaults remain disabled.

Normal exact search is unchanged; `fixed_strings=true` also guarantees a literal
string beginning with `@context` followed by a space remains searchable. During the pilot indexed mode
requires the Git worktree root and rejects incompatible exact-search controls rather
than silently changing their meaning.

### Live checkpoints

A real ChatGPT MCP indexed call against `research-pipeline` returned 10 bounded
context items at about **1,700 actual tool-result tokens**. The first cold open built
the persistent index in roughly **5.45 s**. The second identical call reused the DB:

- cold_open=false;
- reconcile ~46 ms;
- indexed query ~27 ms;
- total indexed operation ~77 ms.

A returned candidate was subsequently opened with `read_file`, and the statistics
pipeline correctly reported evidence-open conversion.

---

## 12. Observability and automatic review

This round intentionally treats observability as part of the feature, not an
afterthought.

Existing generic records continue to provide:

- `tool_call` and `tool_result`;
- call/turn/session correlation;
- duration;
- result bytes and estimated tokens;
- errors/outcomes;
- job lifecycle.

Indexed mode adds:

- `search_dispatch mode=exact|indexed`;
- `index_context` with pilot/schema/parser version, root/query hashes, Git head,
  generation, cold/open/reconcile/query timing, index scale, package size/item count,
  and hashed evidence paths;
- `index_context_error` with failure phase/class;
- no query text or source excerpts in the dedicated telemetry.

The evidence hashes allow later `read_file` or file-scoped exact searches to be
matched back to an indexed candidate without logging source content.

### Existing `binnacle stats` is the normal review entry point

There is no new long-term stats service or top-level command. The existing command:

```bash
binnacle stats --since "7 days ago"
```

automatically appends an `indexed context pilot` section when indexed data exists.
It reports:

- success/error/cold-open counts;
- pilot version;
- evidence-open conversion;
- result/package size distributions;
- total/reconcile/query latency;
- follow-up repository-tool calls/searches/reads;
- follow-up result tokens;
- **investigation tokens = indexed first-hop result + later repository-tool result
  tokens in the same turn**.

Windows with no indexed events retain the previous stats output.

For detailed per-call JSON:

```bash
scripts/analyze_indexed_pilot.py --since '7 days ago' --json
```

The script and `binnacle stats` share the same `binnacle.logstats` analysis code, so
there is no second independent statistics implementation to drift.

---

## 13. Multi-project capacity check on the Raspberry Pi

This review also checked whether the development Pi can support several concurrent
ChatGPT coding projects.

### Hardware/current-system snapshot

The live machine at the time of measurement:

- CPU: **4 × Cortex-A76 @ up to 2.4 GHz**;
- RAM: **15 GiB** visible;
- memory used: ~4.9 GiB;
- memory available: ~10 GiB;
- root/NVMe: ~917 GiB, only ~11% used;
- temperature: **53.8 °C**;
- Raspberry Pi throttling flags: **0x0** (no current/historical throttle/undervoltage
  flag reported by `vcgencmd get_throttled`);
- load average: **1.56 / 0.97 / 0.56**, below the four-core capacity;
- a 5-second CPU sample showed ~23% total system CPU use;
- memory PSI and IO PSI: 0 over the recent 10/60/300-second windows;
- CPU PSI was low (~1–2% recent `some` pressure), with zero `full` pressure;
- no OOM, kernel memory-pressure, thermal, or undervoltage events were found in the
  recent kernel journal;
- zram held ~2.1 GiB of compressed pages, while the 16 GiB disk swapfile had **0 bytes
  used** and `vmstat` showed no active swap-in/swap-out pressure.

### The machine is already running more than the proposed workload

At measurement time there were **six** persistent Claude remote-control project
sessions (`binnacle`, `voice-input`, `msgloom`, `clause-sift`, `research-pipeline`,
and `home`) plus six corresponding Claude worker processes.

All 12 Claude processes together used roughly **2.36 GiB RSS**, or approximately
**0.39 GiB per project session** on average. During a 5-second sample their combined
CPU use was only ~8.4% on psutil's one-core=100% process scale — very small compared
with four available cores while models were mostly waiting/thinking remotely.

The Binnacle MCP service itself was roughly **158 MiB RSS** across its uvicorn/reload
processes.

### Capacity conclusion

For **2–3 total ChatGPT development projects**, this Pi has substantial margin.
Even adding another 2–3 persistent project sessions on top of the six already
resident would add only roughly another ~0.8–1.2 GiB at the observed idle/session
footprint, still far below the current ~10 GiB available-memory headroom.

The likely bottleneck is **not LLM thinking**. The language model executes remotely;
local controllers spend much of that time idle. Contention happens when multiple
projects simultaneously enter local CPU/IO-heavy phases such as:

- full `pytest`/`tox` matrices;
- `pytest-xdist` with many workers;
- Rust/C/C++ builds using all cores;
- large Git/indexing operations;
- local ASR/inference or media processing;
- multiple cold indexed-retrieval rebuilds at the same time.

On a four-core Pi, two or three projects can all run such jobs concurrently, but the
jobs will compete for the same four cores and complete more slowly. This is a
throughput/latency issue, not currently a stability/memory-capacity concern.

The retained Binnacle workload has already observed up to **10 concurrent running
background jobs** without showing a general MCP server failure, although job count is
not equivalent to CPU saturation because many jobs spend time sleeping/waiting.

### Practical recommendation

No concurrency limit is needed merely for 2–3 ChatGPT projects. Continue normally.
If heavy local tasks begin overlapping often, the first control should be to limit
per-project test/build parallelism (for example xdist/build worker count), not to
limit the number of connected ChatGPT sessions.

---

## 14. Resource-telemetry gap

The current Binnacle journal is strong for **tool-level** observability but does not
currently provide historical host-resource time series.

It records tool calls/results, durations, payload sizes, jobs, indexed timings, and
errors, but it does **not** periodically record:

- host CPU busy percentage/load;
- process/service RSS;
- available memory;
- zram/disk-swap use;
- CPU/memory/IO PSI;
- Pi temperature/throttle flags;
- per-project Claude controller/worker RSS.

Therefore this review could inspect **current** capacity and kernel history, but it
cannot reconstruct a minute-by-minute CPU/RAM graph for yesterday's multi-project
workload from the Binnacle journal alone.

### Recommended follow-up

If multi-project workload monitoring becomes useful, add a **low-frequency resource
snapshot**, not per-tool resource logging. A 30–60 second interval is enough for
capacity trends without adding meaningful overhead or journal volume.

A useful record would contain, for example:

```text
event=system_resource
  cpu_busy_pct=...
  load1=... load5=... load15=...
  mem_available_mb=...
  zram_used_mb=... disk_swap_used_mb=...
  psi_cpu10=... psi_mem10=... psi_io10=...
  temp_c=... throttled=...
  binnacle_rss_mb=...
  claude_sessions=... claude_rss_mb=...
  running_jobs=...
```

`binnacle stats` could then add a host-capacity section with p50/p90/max and periods
of CPU/memory pressure. This should be a separate small follow-up rather than mixed
into individual tool-call latency, because host utilization is shared across all
projects and services.

No resource sampler is required for the current 2–3-project plan; the present live
measurements already show ample margin. Its value would be **historical diagnosis and
capacity trend review**, not immediate stability.

---

## 15. Validation quality after the round

The indexed/pilot integration was validated beyond targeted tests:

- full project suite: **592 passed** on the primary Python environment;
- coverage: about **87.3%**, above the existing 86.9% gate;
- Python 3.10, 3.11, 3.12, 3.13, and 3.14 tox environments all passed;
- `indexed_context.py` targeted coverage is ~99%;
- incremental indexed update was compared against a clean rebuild for nodes,
  definitions, references, identifiers, edges, and ranking;
- real cold/warm indexed calls were run through the production MCP connector;
- `binnacle stats` and detailed JSON analysis were verified against real journal
  records;
- exact `search_text` behavior and its grep-equivalence description contract remain
  intact.

---

## 16. Current operational state

The development machine currently has:

```toml
[indexed_context]
enabled = true
reconcile_on_query = true
max_open_indexes = 2
```

Normal exact search is unchanged. The persistent index is cache state and can be
rebuilt. Rollback is simply disabling indexed context and restarting the service;
exact search never depends on the index.

The intended next review is after roughly **1 week**, with a stronger decision after
**1–2 weeks** of normal real-world use.

Use:

```bash
binnacle stats --since "7 days ago"
```

and, when per-call details are needed:

```bash
scripts/analyze_indexed_pilot.py --since "7 days ago" --json
```

Key real-use questions for that review:

1. indexed success/error rate;
2. warm latency and reconciliation overhead;
3. package/result token distribution;
4. follow-up exact-search/read count and token cost;
5. evidence-open conversion;
6. total investigation result tokens;
7. any recurring wrong-anchor/fallback pattern;
8. whether host-resource telemetry is worth adding for multi-project capacity trend
   analysis.

---

## 17. Detailed evidence documents

The round-level conclusions above are backed by these focused reports:

- `docs/usage-analysis-2026-09-19-search-text-result-budget.md`
- `docs/usage-analysis-2026-09-19-job-status-listing.md`
- `docs/usage-analysis-2026-09-19-job-status-latency.md`
- `docs/usage-analysis-2026-09-19-python314-glob-compatibility.md`
- `docs/usage-analysis-2026-09-19-job-retention-cap.md`
- `docs/indexed-context-pilot.md`
- indexed-retrieval research history and Rust migration blueprint in the separate
  `binnacle-indexed-retrieval-poc` repository.

This summary should be updated at the end of the real-use pilot with the actual
7-day/14-day statistics rather than creating a second competing round summary.

## 18. Webmin-backed host resource history (follow-up decision)

The host already runs Webmin 2.660. A follow-up inspection found that its
`system-status` module already provides the long-term host-resource history needed
for multi-project capacity reviews, so Binnacle should **not** duplicate collection.

Current Webmin collection on this Pi:

- module: `system-status`;
- WebminCron interval: **300 seconds** (`collect_interval=5`);
- history path: `/var/webmin/modules/system-status/history/`;
- retained continuous data observed from **2026-08-29 through 2026-09-19**;
- ~7,233 samples / ~302-second median spacing at inspection time;
- total history footprint only ~**1.7 MiB** after ~21 days.

The history contains simple timestamp/value files for `load`, `load5`, `load15`,
`cpuuser`, `cpukernel`, `cpuidle`, `cpuio`, `memused`, `swapused`, `procs`,
`diskused`, network block I/O counters and NVMe drive temperature.

Authentic Theme also has a one-second real-time graph history, but its configured
retention is only 1,800 seconds and collection is tied to the live WebSocket stats
server. That dataset is therefore **not** used for long-term review. The independent
`system-status` WebminCron history is the authoritative source.

### CLI policy

Host resources are deliberately **not** included in normal `binnacle stats` output.
They are opt-in:

```bash
binnacle stats --since "24 hours ago" --system-resources
binnacle stats --since "7 days ago" --system-resources
```

Without `--system-resources`, `binnacle stats` does not read Webmin at all and its
existing output remains unchanged. With the flag, the same `--since/--until` window
is applied to Webmin history and a final `system resources (Webmin system-status)`
section is appended.

The reader accepts only a fixed metric whitelist. Because Webmin's parent directories
are root-only on this host, it first tries ordinary read access and falls back to
`sudo -n cat` of the fixed history file. No arbitrary Webmin path is accepted and no
Webmin configuration/state is modified.

The resource section reports p50/p90/p95/max/min for CPU busy, CPU IO wait, load,
memory used, swap used, process count and NVMe temperature; fractions of samples
above meaningful CPU/load thresholds; and the timestamps of the top CPU/load/memory/
temperature peaks.

### First historical view

Over the most recent 24-hour window at implementation time:

- CPU busy p50 **6%**, p90 **31–32%**, p95 **38–39%**;
- CPU >=50% in only ~**4%** of five-minute samples;
- CPU >=90% in ~**0.7%** of samples;
- load1 p50 **0.4**, p95 **2.1**, max **4.0** on a four-core machine;
- memory used p50 **7.7 GiB**, p95 **8.2 GiB**, max **10.7 GiB**;
- NVMe temperature p50 **41°C**, p95 **45°C**, max **58°C**.

The seven-day window is more bursty (CPU p95 ~73%, load1 p95 ~4.0) and contains a
few extreme short-lived local-work/IO periods. One peak at 2026-09-16 08:06 reached
load1 ~91.7 with IO wait ~80% and NVMe temperature 71°C. The Binnacle journal has no
corresponding run_command record for that exact window, so its cause is intentionally
left unattributed rather than assigned to an AI project without evidence.

These historical results reinforce the earlier capacity conclusion: normal workload
has substantial headroom, while occasional local build/test/IO bursts can saturate
the Pi briefly. The opt-in Webmin view makes those bursts reviewable without adding a
new sampler or daemon to Binnacle.
