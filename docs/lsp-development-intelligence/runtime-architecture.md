# Development Intelligence — runtime architecture

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Binnacle integration boundaries, internal LSP architecture, lifecycle, workspace model, configuration, resources, and telemetry |
| **Source index** | `docs/lsp-development-intelligence-design-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 4. What current Binnacle architecture implies

### 4.1 The six-tool ChatGPT surface is now strongly pinned

`Settings.client_tools["openai-mcp"]` still exposes exactly:

~~~text
read_file
list_files
search_text
run_command
job_status
stop_job
~~~

Since 2026-09-28 the repository additionally pins:

- the ChatGPT tool count at six and the default-client count at eight;
- each served tool's complete MCP surface hash;
- server instructions hash;
- golden structured outputs;
- the ChatGPT standing surface token budget.

The current token budget is 2262 `o200k_base` tokens plus a 5% tolerance.

Therefore a seventh tool is a deliberate contract change. If one is approved, the same
commit must intentionally update the relevant surface/token/golden tests and document why
the additional standing schema cost is justified.

### 4.2 `readOnlyHint` remains a security/user-control contract

Binnacle deliberately uses `readOnlyHint=true` so ChatGPT can perform read operations
without a write confirmation.

An internal subprocess used by a READ tool cannot quietly:

- create repository caches;
- update lockfiles;
- write indexes under the repository;
- run project build scripts;
- execute arbitrary project-configured commands;
- apply LSP workspace edits.

A provider is not read-only merely because its intended output is "analysis".

### 4.3 The removed indexed-context pilot changes the LSP product boundary

Current `search_text` has no semantic/natural-language dispatch. Every call is exact
regex/literal search, with adaptive result shaping only after a broad exact search exceeds
the response budget.

The removed indexed-context pilot is important evidence rather than reusable architecture:

- speed and result size were acceptable;
- retrieval quality was not;
- behavior questions were especially weak;
- the indexed-first workflow increased model steps.

LSP should therefore **not** be used to resurrect that persistent retriever by default.

The clean boundary is now:

~~~text
repository orientation / evidence
    search_text + read_file
             |
             | once a concrete symbol/location is known
             v
optional semantic navigation
    definition / references / type / symbol relations
~~~

This is a better fit for LSP itself. A language server excels at resolving a concrete
program symbol under language semantics; it is not inherently a natural-language behavior
retriever.

The archived `@context` question sets may still be useful as a negative/control corpus if
a future natural-language retriever is attempted, but success on explicit symbol
navigation must not be misrepresented as solving those behavior questions.

### 4.4 FastMCP lifespan is still the right ownership boundary

The installed FastMCP constructor still supports a lifespan callable.

Development Intelligence should use server lifespan to own and close provider processes.
A module-global process manager with no lifespan integration is insufficient.

The development unit now watches only `src/` for Uvicorn reloads. This reduces accidental
provider churn: documentation, tests, and scripts no longer restart the MCP server. A
source-code reload can still happen at any time and must terminate/recreate provider
processes cleanly.

LSP processes remain reconstructable internal infrastructure. They do **not** need the
durable ownership semantics of `run_command` jobs, which now intentionally survive MCP
reloads and later chats through `binnacle-jobs.service`.

### 4.5 Current job cgroups are a useful precedent, not a drop-in LSP manager

Since this design was written, durable command jobs gained per-job cgroup-v2 accounting:

- CPU counters;
- memory current/peak and memory events;
- IO counters;
- PID current/peak;
- descendant inheritance;
- kernel-event-based empty detection;
- best-effort cleanup;
- compact long-term resource history.

As of `f1493ee`, that history is schema v2: rows carry `call_id`, final gauges are named
explicitly (for example `memory_current_final`), and cumulative `memory.stat` counters are
kept separately. If Development Intelligence later persists provider-resource history, it
should preserve the same semantic discipline: final, peak, and cumulative values must never
share ambiguous names.

This is highly relevant to the LSP performance work, but `job_cgroup.py` is intentionally
job-specific:

- it assumes 12-character job ids and `job-*` names;
- it derives topology from the delegated `binnacle-jobs.service`;
- the job manager unit has `Delegate=cpu memory pids` and
  `DelegateSubgroup=binnacle-manager`;
- `binnacle-mcp.service` currently has no equivalent delegation.

Therefore the first LSP PoC should **not** call `job_cgroup.create` directly.

For initial provider benchmarks, process-tree RSS/CPU plus child counts are sufficient.
If production evidence later requires exact per-provider cgroup accounting, extract or
design a generic process-accounting layer and deliberately add the necessary systemd
delegation (or a separate provider-owner service). Do not move LSP ownership into the
durable jobs service merely to obtain metrics.

### 4.6 Existing quality infrastructure should be extended, not duplicated

`scripts/weekly_bench.py` already:

- creates a deterministic fixture;
- starts a temporary Binnacle server on loopback;
- warms it;
- performs repeated client calls;
- records startup time and RSS;
- runs away from production under the weekly quality isolation policy.

Development Intelligence should reuse this benchmark philosophy. The standalone raw-LSP
benchmark remains separate because it answers a different question, but the end-to-end
MCP benchmark should extend or closely mirror the existing temporary-server harness rather
than inventing a second incompatible performance framework.

---

## 7. Revised architecture

The current six tools are **not** semantic-enrichment entry points in the revised design.
Development Intelligence is initially a private subsystem exercised by tests/benchmarks
and, only if evidence justifies it, by a future explicit MCP intent.

~~~text
                       MCP clients
                           |
                           v
+--------------------------------------------------------------+
|                         Binnacle                             |
|                                                              |
| Existing public tools — unchanged                            |
| read_file  list_files  search_text  run_command              |
| job_status stop_job                                          |
|                                                              |
|                    (no hidden LSP dispatch)                  |
|                                                              |
|       +-----------------------------------------------+      |
|       | Private Development Intelligence subsystem    |      |
|       |                                               |      |
|       | provider profile registry                     |      |
|       | workspace resolver                            |      |
|       | trust / side-effect policy                    |      |
|       |                                               |      |
|       | +----------------+  +----------------------+  |      |
|       | | LSP manager    |  | Analyzer manager     |  |      |
|       | | long-lived     |  | one-shot CLI         |  |      |
|       | | JSON-RPC       |  | bounded execution    |  |      |
|       | +--------+-------+  +----------+-----------+  |      |
|       |          |                     |              |      |
|       |          +----------+----------+              |      |
|       |                     v                         |      |
|       |      normalized semantic/diagnostic model     |      |
|       +-----------------------------------------------+      |
|                    ^                     ^                   |
|                    |                     |                   |
|          private benchmarks      future explicit MCP         |
|                                  intent(s), if approved       |
+--------------------------------------------------------------+
                     |                     |
                     v                     v
              audited LSPs          audited analyzers
~~~

The internal subsystem should expose intent-level Python APIs rather than raw protocol
methods. Conceptually:

~~~text
semantic.inspect_symbol(...)
semantic.document_symbols(...)
semantic.definition(...)
semantic.references(...)
diagnostics.check(...)
~~~

`semantic.inspect_symbol(...)` is the most important product-level experiment: one call
can aggregate the useful bounded facts about a concrete symbol instead of forcing the MCP
surface to mirror LSP methods.

No existing tool should call these APIs in production during the private PoC phases.
That keeps current golden outputs and latency paths genuinely unchanged and makes the
future public-tool decision measurable rather than implicit.

---

## 9. LSP client design

### 9.1 Keep the supported protocol subset intentional

The first client does not need the entire LSP specification.

Required lifecycle/transport support:

- stdio Content-Length framing;
- JSON-RPC request/response IDs;
- server notifications;
- server-to-client requests;
- bounded message/header sizes;
- initialize / initialized;
- shutdown / exit;
- textDocument/didOpen;
- textDocument/didChange;
- textDocument/didClose;
- textDocument/publishDiagnostics.

Initial semantic methods for experiments:

- textDocument/documentSymbol;
- workspace/symbol;
- textDocument/definition;
- textDocument/references.

Do not implement write operations merely because a server advertises them.

### 9.2 Server-to-client request policy

The client needs an explicit method policy.

Examples:

- workspace/configuration — return only Binnacle-controlled provider settings;
- window/workDoneProgress/create — accept/track minimally if required;
- client/registerCapability — support only audited safe dynamic registrations;
- workspace/applyEdit — always reject in read-only generations;
- any command execution request — never execute on behalf of a READ workflow;
- unknown request — standards-compliant error.

Never advertise client capabilities that Binnacle does not correctly implement.

### 9.3 Position encoding

Position-sensitive LSP operations cannot treat Python string indexes as LSP character
offsets.

The client must:

- honor negotiated positionEncoding where supplied;
- implement the legacy/default behavior correctly;
- support UTF-16 conversion at minimum;
- test non-BMP characters explicitly.

This is required before definition/reference results can be trusted.

### 9.4 Message and result bounds

A local language server is still an external process.

Enforce:

- maximum header bytes;
- maximum JSON-RPC body bytes;
- maximum outstanding requests;
- maximum normalized result items/bytes;
- per-request deadlines;
- startup deadline;
- graceful shutdown deadline followed by process-group termination.

Malformed or over-budget provider messages must fail the provider operation, never the
baseline MCP tool.

### 9.5 Dependency decision

Do not choose an LSP Python dependency merely to avoid writing a framing loop.

The PoC should compare:

1. a narrow internal client using the standard library/orjson;
2. Microsoft lsprotocol for generated types plus Binnacle-owned transport;
3. a maintained third-party client library.

Selection criteria:

- Python 3.10 support;
- current LSP coverage;
- bidirectional server-request support;
- async/thread model compatibility with FastMCP;
- dependency weight;
- testability;
- release/maintenance health;
- ability to enforce Binnacle's side-effect and timeout policy.

The current recommendation is **not frozen**. A small in-house protocol subset is
reasonable only if the test matrix proves framing, concurrency, cancellation,
server-requests, position encodings, and shutdown behavior robustly.

---

## 10. LSP lifecycle and residency

Process lifecycle state remains deliberately small:

~~~text
ABSENT
STARTING
READY
COOLDOWN
DISABLED
~~~

`READY` means:

> `initialize` completed and the advertised capability map is available.

Do not add a second semantic-warmness state machine in v1.

Cold/settling/warm are **measurement conditions**, not durable lifecycle states.
The normal usage model keeps a provider resident. If a provider is technically ready but
still finishing project indexing, a semantic request is simply subject to its normal
bounded deadline. Missing that deadline causes a fail-open fallback for an existing tool;
it does not require Binnacle to predict provider internals.

### 10.1 Baseline tool rule

Existing-tool enrichment may use an LSP request only when:

- the provider process is already `READY`;
- the capability is advertised;
- the operation has a small hard deadline;
- failure/timeout can be discarded with no baseline behavior change.

An existing tool must not synchronously launch a cold language server and wait for its
project model merely to enrich a result. It may trigger background startup for later calls.

Once the provider is resident, repeated calls should reuse it directly without PATH
rediscovery, process launch, or workspace reinitialization.

### 10.2 Explicit analysis rule

A future explicit diagnostics/semantic tool may use a larger bounded budget because the
caller explicitly requested analysis.

That still does not justify indefinite waits.

### 10.3 Concurrency

For one `(workspace_root, provider_profile)` instance:

- startup is single-flight;
- request IDs are unique;
- stdout has one reader/dispatcher;
- writes to stdin are serialized;
- concurrent callers can wait for independent responses;
- provider exit resolves/fails all pending requests exactly once.

### 10.4 Residency and idle eviction

Residency is the normal performance path, not an exceptional optimization.

Do not freeze one short global idle timeout before measurements. A lightweight provider
can reasonably stay resident much longer than a provider whose process tree consumes
hundreds of MiB.

The PoC should measure:

- steady-state RSS by provider/workspace;
- RSS growth over long sessions;
- CPU while idle;
- cost of re-warming after eviction;
- simultaneous-provider pressure.

Then choose either one evidence-based global policy or small per-profile defaults.
Eviction remains a resource safety mechanism, not something expected between normal
adjacent chat turns.

### 10.5 Shutdown and Uvicorn reload

FastMCP lifespan owns the manager.

On shutdown/reload:

1. stop accepting new provider requests;
2. send LSP `shutdown` where possible;
3. send `exit`;
4. wait briefly;
5. terminate the provider process group;
6. kill after final grace;
7. join reader threads/tasks;
8. clear instance registry.

This is mandatory before enabling long-lived providers under Uvicorn reload.

---

## 11. Workspace and document model

### 11.1 Disk is authoritative

Binnacle has no unsaved editor-buffer model.

The on-disk file is authoritative.

Before a position-sensitive operation, ensure the provider has current disk contents.

### 11.2 Workspace root

Resolution order should be deterministic:

1. Git worktree root, when inside Git;
2. provider-specific project marker resolution for non-Git trees;
3. requested directory/file parent as the narrow fallback if the provider profile allows it.

Never silently widen outside Binnacle's allowed roots.

### 11.3 Document synchronization

Use on-demand sync:

- didOpen on first use;
- store a content hash/version;
- didChange when disk content changes;
- didClose on document or provider eviction.

Do not open an entire repository just to make LSP “more ready”.

### 11.4 External mutation

Files can change through run_command, another shell/editor, Git, or another automation.

A targeted operation must refresh its target from disk. A provider-wide semantic cache
must therefore be considered advisory unless freshness is established.

---

## 14. Configuration model

Repository defaults must require no Development Intelligence configuration.

Illustrative shape:

~~~toml
[development_intelligence]
enabled = true

[development_intelligence.lsp]
auto_discover_audited = true
max_instances = 2
# idle_timeout_s is intentionally not frozen before residency/RSS benchmarks.

[development_intelligence.analyzers]
auto_discover_audited = true

# Explicit trusted override example:
# [development_intelligence.providers.pyright]
# command = ["/opt/tools/pyright-langserver", "--stdio"]
# trusted = true
~~~

Exact keys are not frozen.

Semantics that are required:

- global disable;
- audited PATH discovery can be disabled;
- explicit trusted command override;
- per-provider disable;
- provider resource limits;
- time budgets stay server-side;
- no provider installation/download;
- no project-local command auto-discovery.

Configuration validation should reject ambiguous or unsafe combinations early.

---

## 15. Process/resource management

Initial resource policy should favor reuse while remaining bounded:

- configurable maximum resident LSP count;
- LRU/idle eviction as a safety valve, with the timeout chosen from provider RSS evidence;
- per-provider RSS/CPU/latency telemetry during PoC;
- one provider instance per workspace/profile;
- provider process group owned by Binnacle;
- reuse the same provider across many MCP calls/chat turns while Binnacle remains alive;
- no persistence requirement across a Binnacle process restart;
- analyzer subprocesses are one-shot and have hard wall-clock deadlines.

The preliminary micro benchmark already shows why one residency rule may be suboptimal:
the TypeScript language-server process tree was roughly 0.5-0.6 GiB on this host while
rust-analyzer in the small isolated fixture was around 20 MiB. These numbers are not
production sizing claims, but they justify measuring resource cost before selecting an
idle timeout.

Do not reuse the durable run_command job-owner model for LSP. Language servers are
reconstructable internal infrastructure, not user jobs whose output must survive a server
reload.

However, process-tree cleanup quality must be tested to the same standard as jobs.

---

## 16. Telemetry

Follow the existing Binnacle principle:

> Add dedicated telemetry only when generic tool records cannot explain a hidden decision,
> fallback, semantic-quality change, or multi-stage latency.

### 16.1 Provider lifecycle

Sparse events may record:

- provider profile key;
- language;
- workspace hash;
- discovery source: configured / PATH / unavailable;
- start/initialize duration;
- process state;
- capability summary;
- exit/failure class;
- cooldown reason;
- RSS sample at controlled points.

No source text.

### 16.2 Semantic operation

For shadow experiments:

- operation class;
- provider ready/warm state;
- operation latency;
- result count/bytes;
- timeout/fallback reason;
- candidate hashes, not source snippets;
- whether it changed ranking/candidates;
- downstream conversion where measurable.

### 16.3 Analyzer execution

One summary per invocation:

- provider;
- version;
- scope;
- duration;
- exit classification;
- diagnostic counts;
- result bytes;
- truncation;
- stable unavailable/failure reason.

### 16.4 No protocol spam

Do not log every JSON-RPC frame.

Frame-level logging may exist behind a developer-only debug switch with payload redaction,
but it is not normal production telemetry.

---
