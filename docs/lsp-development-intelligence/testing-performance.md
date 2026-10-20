# Development Intelligence testing — semantic quality, performance, and providers

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 testing design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Semantic corpus, raw/integrated performance, telemetry, and real-provider compatibility |
| **Project index** | `docs/lsp-development-intelligence/README.md` |

> Read only the sections required by the current implementation-plan work item.

---

## 15. Semantic-navigation quality corpus

Protocol success is not enough. LSP must improve the concrete symbol-navigation work it is
actually designed to solve.

### 15.1 Primary task categories

Create reviewed gold cases for:

- unique function/class definition;
- duplicate same-name definitions in different modules;
- imported/re-exported alias;
- class method override/implementation;
- typed member resolution;
- function callback/reference;
- declaration versus implementation;
- cross-file reference set;
- Markdown link/heading relation;
- Shell sourced-function relation;
- stale/modified file after provider start;
- unsupported capability;
- genuinely ambiguous resolution.

Each case records the exact expected source location(s).

### 15.2 Primary arms

Compare:

A. current production workflow: `search_text` + `read_file` + model reasoning;

B. the same task with private `semantic.inspect_symbol(...)` available to the benchmark
agent/harness.

Do not add a hidden semantic mode to arm A.

### 15.3 Metrics

Quality:

- task success;
- correct-definition rate;
- reference precision/recall where a complete gold set is practical;
- ambiguity reported correctly;
- stale-result incidents;
- wrong-file/wrong-symbol incidents.

Efficiency:

- model steps;
- MCP/tool calls;
- `search_text` calls;
- `read_file` calls;
- tool-result bytes/tokens;
- wall/API duration;
- semantic-tool selection/argument success when testing a candidate public schema.

Provider behavior:

- availability;
- cold/settling/warm phase;
- semantic request p50/p95/p99;
- timeout/fallback rate;
- result size/truncation.

### 15.4 Archived natural-language retriever corpus is a separate guardrail

The removed indexed-`@context` pilot has real-query and labelled behavior-question corpora
with a documented failed baseline.

Do **not** mix those questions into the primary symbol-navigation score and then claim LSP
fixed repository orientation.

If a future design proposes natural-language semantic retrieval, run that archived corpus
as a separate experiment with predeclared recall/step gates. The symbol-navigation corpus
cannot substitute for it.

### 15.5 Decision discipline

Do not approve a public semantic tool from microbench latency or one impressive definition
lookup.

Require:

- reviewed semantic correctness;
- workflow A/B improvement;
- end-to-end Binnacle overhead within budget;
- read-only safety for enabled profiles;
- acceptable standing surface/token cost.

---

## 16. Performance and resource benchmarks

### 16.1 Suite A — standalone raw-LSP benchmark

Run the provider without Binnacle using the smallest benchmark client that still implements
the required LSP lifecycle correctly.

This isolates language-server behavior from:

- FastMCP;
- Binnacle middleware;
- path/workspace resolution;
- normalization;
- result shaping;
- MCP transport.

For every provider/workload record:

- executable path and exact version;
- command/initialization options;
- workspace fixture/revision;
- process spawn -> initialize response;
- initialize -> project settled/usable milestone where detectable;
- first semantic request;
- resident warm p50/p95/p99;
- result count/bytes;
- correctness assertion result;
- process-tree RSS;
- idle CPU;
- child process count.

Do not rank a provider by latency when the expected semantic result is absent or wrong.

### 16.2 Suite A workload scales

Every target provider should be measured at three scales.

#### Micro fixture

Small deterministic project with exact gold locations. Used for correctness, low-noise
request latency, and CI-friendly regression tests.

#### Medium controlled repository

Enough files/symbols/imports/includes to exercise indexing and cross-file behavior while
remaining reproducible.

#### Real development repository

A real repository already used on this host. The benchmark artifact records the exact Git
commit and may run only in developer/scheduled lanes.

Current local candidates include:

- Binnacle for Python and Markdown;
- `voxtype` or `Handy` for TypeScript/JavaScript and Rust;
- CPython for C/C++;
- Binnacle/research-pipeline-family repositories for Makefiles;
- existing project `scripts/*.sh` trees for Shell.

These are developer benchmark candidates, not CI dependencies.

### 16.3 Suite A provider matrix

The early benchmark matrix is:

| Language/file type | Provider | Current host state | Required semantic gold checks |
| --- | --- | --- | --- |
| Python | Pyright | installed | symbols, definition, references, diagnostics |
| TypeScript | typescript-language-server | installed | symbols, definition, references, diagnostics |
| JavaScript | typescript-language-server | installed | symbols, definition, references, diagnostics |
| Rust | rust-analyzer | installed | workspace symbol, definition, references after project settles |
| C | clangd | installed | symbols, definition, references, diagnostics |
| C++ | clangd | installed | symbols, definition, references, diagnostics |
| Markdown | Marksman | installed | headings, link definition, references, diagnostics |
| Shell | bash-language-server | installed | definition/references and supported symbols/diagnostics |
| Makefile | make-ls | not installed | targets/variables, definition, references, diagnostics |

The benchmark harness reports `not_installed` for a missing optional provider. It must not
download/install one.

### 16.4 Cold, settling, and resident-warm conditions

Measure all three, but weight them differently.

#### Cold

- process does not exist;
- measure spawn/initialize and first project load.

#### Settling

- initialize returned, but provider may still be indexing/reloading the project;
- record transient errors such as `content modified`, empty-but-expected semantic results,
  and progress notifications.

#### Resident warm — primary

- same provider process remains alive;
- project model is settled;
- run at least 30 repetitions per operation for exploratory work and preferably 100 for a
  stable performance artifact;
- report p50/p95/p99, not only averages.

The benchmark must not kill/restart the server between warm iterations.

### 16.5 Preliminary standalone measurements — 2026-09-27

The initial feasibility probe on this host used tiny fixtures and only a handful of warm
iterations, so these are directional baselines rather than quality gates.

| Provider | Warm workspace symbol | Warm definition | Warm references | Approx. RSS | Semantic result |
| --- | ---: | ---: | ---: | ---: | --- |
| Pyright / Python | ~0.4-1.2 ms | ~0.6-1.2 ms | ~0.9-1.4 ms | ~147-153 MiB | valid |
| TypeScript LS / TS | ~2-6 ms | ~3-4 ms | ~6-15 ms | ~540-585 MiB | valid |
| TypeScript LS / JS | ~2-4 ms | ~2-4 ms | ~6-10 ms | ~560-630 MiB | valid |
| rust-analyzer / Rust | ~0.27 ms | ~0.22 ms | ~0.48 ms | ~19-21 MiB small fixture | valid after Cargo settling |
| clangd / C++ | ~0.1-0.4 ms | ~0.1-0.3 ms | ~0.1-0.2 ms | ~110-175 MiB | valid |
| clangd / C | ~0.2-0.6 ms | ~0.1-0.3 ms | ~0.2-0.4 ms | ~120-180 MiB | valid |
| Marksman / Markdown | ~0.6-2.3 ms | ~1-4 ms | ~1-5 ms | ~83-86 MiB | valid with multi-file workspace marker |
| bash-language-server / Shell | ~0.4-1.6 ms | ~0.4-3 ms | ~1.6-3 ms | ~110-190 MiB | valid for definition/references |
| make-ls / Makefile | not measured | not measured | not measured | not measured | provider absent |

A Rust probe sent requests during Cargo workspace reload and initially produced empty or
`content modified` results. After allowing the same process to settle, eight repeated
requests returned the expected symbol/definition/reference set with sub-millisecond
medians. This is why correctness and lifecycle phase must accompany every latency number.

### 16.6 Suite B — end-to-end Binnacle integration benchmark

Once the internal manager exists, benchmark the real Binnacle path using both:

1. FastMCP in-process client — minimizes transport noise and highlights Binnacle code cost;
2. local loopback HTTP — includes the actual HTTP/MCP serialization/middleware path.

For the existing six tools, compare these arms:

A. Development Intelligence disabled;

B. enabled, provider absent;

C. provider manager initialized but no provider started;

D. provider resident for a separate private benchmark call while an existing tool is used.

All four must preserve the existing tool's golden output. Existing tools must not execute a
semantic RPC on their request path.

Then benchmark the **private semantic API** separately through:

E. direct internal `semantic.inspect_symbol(...)`;

F. a temporary FastMCP test assembly exposing the candidate to a non-production profile;

G. local loopback HTTP to that temporary server.

If a public semantic/diagnostic tool is later approved, compare its full end-to-end call
against the equivalent current `search_text`/`read_file` or `run_command` workflow.

### 16.7 Integration latency decomposition

Instrument enough internal phases to explain total time:

~~~text
MCP/private semantic total
  - request/middleware (when using a temporary MCP profile)
  - path + workspace resolution
  - provider registry/instance lookup
  - document freshness/sync
  - queue/dispatch
  - raw LSP request/response
  - semantic aggregation/normalization
  - result shaping/serialization
~~~

The raw LSP latency from Suite A is an independent baseline. The difference between raw
provider cost and the relevant integrated phases exposes Binnacle's overhead.

Do not infer integration cost by subtracting two unrelated wall-clock measurements unless
they were produced by the same benchmark condition.

### 16.8 Provisional integration targets

These are engineering targets to validate, not frozen public promises.

For existing tools where no semantic RPC is used:

- structured result remains byte-for-byte equivalent;
- no PATH scan/process spawn on the hot path;
- median added server-side latency should target <1 ms;
- p95 regression should target the larger of 2 ms or 5% of the baseline.

For a resident private/candidate semantic call:

- Binnacle-only overhead around the raw provider call should target low single-digit
  milliseconds for small results;
- the semantic call must have a hard deadline;
- timeout/failure returns a truthful bounded unavailable/partial semantic result;
- existing six tools are unaffected because they do not call the semantic path;
- the correctness gate is mandatory even if the latency target passes.

Freeze final thresholds only after the benchmark harness itself is stable.

### 16.9 Long-residency/soak benchmark

Because the normal usage model keeps providers alive, run a soak workload that:

- starts each provider once;
- warms it;
- performs mixed semantic requests across many files;
- inserts realistic idle gaps;
- records process-tree RSS/CPU periodically;
- verifies no monotonic memory/process leak;
- verifies no repeated workspace initialization;
- measures post-idle request latency.

Use fake clocks for eviction unit tests, but include at least one real-process soak in the
scheduled/developer benchmark lane.

The current durable-job cgroup implementation is **not** the first measurement mechanism
for LSPs. It belongs to the delegated job-manager service. Initial LSP soak accounting
should use provider process trees. If that proves insufficient, design a generic delegated
provider cgroup deliberately and test that separately.

### 16.10 Resource-cap benchmark

Start providers across multiple workspaces and languages.

Verify:

- max-instance cap;
- idle/LRU eviction;
- memory falls after eviction;
- active requests are not evicted;
- heavy providers do not prevent lightweight providers from operating;
- no process leak after teardown.

One global idle timeout should not be frozen until these measurements exist.

The benchmark should run under the repository's existing weekly-quality isolation rules
(temp checkout/server, quiet-host gate, bounded CPU/resource scope), not against production.

---

## 17. Telemetry tests

Telemetry is itself behavior and should be tested.

Assert:

- lifecycle events contain no source contents;
- workspace stored as hash where intended;
- provider command is not logged with secrets;
- diagnostics messages are not duplicated into generic telemetry;
- failure reason codes are stable/low-cardinality;
- private semantic operation telemetry correlates to its benchmark/MCP call when one exists;
- telemetry exception cannot fail a tool/provider operation.

Add parser/logstats tests before depending on a new event for go/no-go analysis.

---

## 18. Real-provider smoke and compatibility tests

Real providers are supplemental to the deterministic fake server, but the early
compatibility matrix is intentionally broad so the internal client does not become
Pyright-specific.

### 18.1 Pyright — Python

If `pyright-langserver` is available:

- initialize and record advertised capabilities;
- open a known Python project/file;
- document/workspace symbols;
- definition and references with gold locations;
- observe push diagnostics;
- repeated warm requests;
- shutdown;
- verify the chosen read-only profile causes no workspace manifest change.

### 18.2 TypeScript language server — TypeScript and JavaScript

Run distinct TS and JS fixtures because they share a provider but not necessarily identical
project/config behavior.

Validate:

- cross-file import definition;
- references;
- document/workspace symbols;
- diagnostics if delivered;
- child-process/RSS accounting for the TypeScript service;
- warm repeated requests.

### 18.3 rust-analyzer — Rust

Use a small Cargo fixture with no build script/proc macro for the initial benchmark.

Record:

- project-model settling time;
- any `content modified`/empty transient result during reload;
- workspace symbol;
- definition;
- references;
- warm repeated requests only after gold results become valid.

Safety profiling is a separate gate: default rust-analyzer project behavior must not be
treated as a ChatGPT READ provider until command/build-script side effects are controlled.

### 18.4 clangd — C and C++

Run separate C and C++ fixtures with known includes and definitions.

For read-only benchmark mode, disable background index persistence or redirect it away from
the workspace. Validate:

- diagnostics;
- document/workspace symbols;
- definition;
- references;
- compile-command/fallback-mode differences.

### 18.5 Marksman — Markdown

Use a multi-file Markdown workspace with the required workspace marker.

Validate:

- heading document symbols;
- workspace heading search;
- link -> heading definition;
- references/backlinks;
- broken-link diagnostics where supported.

### 18.6 bash-language-server — Shell

Validate:

- sourced-file function definition;
- function references;
- workspace symbols;
- diagnostics/symbol operations actually advertised and useful by the installed version.

Record and control background analysis settings where supported.

### 18.7 Makefile — make-ls

`make-ls` is not installed on this host as of 2026-09-27.

Once explicitly installed in the benchmark environment, validate:

- target and variable document symbols;
- prerequisite/variable go-to-definition;
- references;
- includes;
- diagnostics.

The test harness must not install it automatically.

### 18.8 Analyzer CLI smokes

Pyright CLI:

- run structured output against a synthetic file with one known type error;
- parse one diagnostic;
- verify no workspace write.

Ruff:

- run the audited profile command;
- parse structured output;
- verify no `.ruff_cache`;
- verify no source change.

### 18.9 Optional-provider policy

A missing real provider yields `SKIP`/`not_installed`, not a normal-suite failure.

A provider that **is installed** but returns an incorrect gold semantic result is a failed
compatibility/benchmark case; it must not be reported merely as a fast timing sample.

Only fake-provider tests define protocol-core behavior.

---
