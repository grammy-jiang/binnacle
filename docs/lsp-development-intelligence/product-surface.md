# Development Intelligence — product and MCP surface

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Semantic-navigation and diagnostics product candidates, acceptance criteria, non-goals, and open product decisions |
| **Source index** | `docs/lsp-development-intelligence-design-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 12. Semantic navigation and the current tool surface

The removal of indexed `@context` changes this section fundamentally.

### 12.1 `search_text` stays exact-only

Do not integrate LSP into `search_text`.

Current search has a strong, intentionally pinned contract:

- regex/literal semantics;
- auto-context for few exact matches;
- adaptive **representation** only when a broad exact result exceeds the byte budget;
- golden output snapshots;
- surface hash and token-budget pins.

Adding hidden semantic routing would make one tool mean two different things again and
would weaken the exact-surface preservation that accompanied the 2026-09-28 removal.

A string beginning with `@context` followed by a space must continue to be an ordinary regex/literal pattern.

### 12.2 Repository orientation and semantic navigation are different jobs

Current orientation workflow:

~~~text
unknown implementation location
        |
        v
search_text / list_files
        |
        v
read_file
        |
        v
concrete symbol/location found
~~~

Only after the last step does LSP have its strongest input: a real document and symbol
position.

The semantic-navigation experiment therefore starts at that boundary:

~~~text
concrete symbol/location
        |
        v
private semantic.inspect_symbol(...)
        |
        +--> definition / declaration / implementation
        +--> bounded references
        +--> hover/type/signature when useful
        +--> provider/source provenance
~~~

This does not claim to solve natural-language behavior retrieval.

### 12.3 Working public candidate: `inspect_symbol`

If private evidence is positive, the first semantic-navigation MCP candidate should model
one stable agent intent rather than expose raw LSP verbs:

> Inspect this concrete source symbol: explain what it resolves to and return the most
> useful bounded definition/reference/type evidence.

Working name: `inspect_symbol`.

Its final schema is **not frozen**. The design should compare model-friendly anchors such
as:

- `path + line + symbol text`;
- `path + line + column`.

The first form may be easier for ChatGPT because `search_text` already returns file and
line plus matched text; the second is closer to LSP but forces the model to calculate a
column. The benchmark must decide rather than assume.

A candidate result should be bounded and provenance-preserving, for example:

- requested path/line/symbol;
- provider used;
- resolved definition/declaration/implementation locations;
- type/hover summary when provider supplies it;
- bounded references with total/truncation;
- ambiguous/unavailable/partial status.

Do not expose separate `lsp_definition`, `lsp_references`, `lsp_hover`, and
`lsp_workspace_symbols` tools.

### 12.4 Private comparison before MCP exposure

Phase 3 should compare semantic-navigation tasks in two arms:

A. current six-tool workflow — exact search/read reasoning only;

B. the same workflow with private `semantic.inspect_symbol(...)` available to the
benchmark harness or a temporary non-production test profile.

Measure:

- task correctness;
- wrong-definition/ambiguity rate;
- model steps;
- MCP/tool calls;
- tool-result tokens;
- wall/API time;
- raw provider time versus Binnacle overhead.

This test asks whether LSP resolves a **concrete semantic navigation problem** more
efficiently than text search. It does not rerun the failed natural-language retriever under
a different name.

### 12.5 Archived `@context` evidence remains a guardrail

The archived pilot established an important failure mode: a fast, compact retriever can
still lose if candidate quality is poor and it creates extra model steps.

If a future proposal again attempts natural-language repository retrieval, it must be
evaluated against that archived real-query/labelled corpus and predeclared step/recall
bars. Success of `inspect_symbol` on symbol tasks is not evidence that such a retriever
works.

### 12.6 Public semantic-navigation decision gate

Do not expose `inspect_symbol` to ChatGPT until all of these are true:

- provider result correctness is strong on reviewed symbol-navigation tasks;
- the private Binnacle integration adds acceptable resident overhead;
- at least one meaningful workflow metric improves versus search/read only;
- provider absence/failure remains truthful and bounded;
- READ side-effect policy is proven for every enabled profile;
- the new standing surface fits an intentionally revised token budget;
- tool count/surface/golden contract changes are reviewed as deliberate API changes.

If the workflow gain is weak, keep LSP private/internal or stop the feature. A protocol
being fast is not enough reason to add a public tool.

---

## 13. Diagnostics and the provisional check_code tool

### 13.1 check_code is not yet approved

The original draft promoted check_code too early.

The correct decision sequence is:

1. build safe analyzer execution internally;
2. measure real ChatGPT use of run_command for lint/type-check diagnostics;
3. measure whether a normalized read-only call would remove approval clicks, shell
   knowledge, output parsing, tokens, or extra turns;
4. only then add the tool.

### 13.2 If approved, the tool intent is still reasonable

Potential intent:

> Analyze this file or project using the best **audited read-only** providers available
> and return normalized diagnostics with truthful coverage.

A minimal input can still be:

~~~text
check_code(path)
~~~

But the final scope semantics must be explicit in the result.

### 13.3 Provider selection for diagnostics

Initial likely Python strategy:

- Pyright CLI JSON mode for deterministic one-shot type diagnostics;
- Ruff CLI JSON mode with --no-cache and no fix mode;
- optionally Pyright LSP diagnostics only where a bounded completeness rule has been
  demonstrated.

Do not auto-enable mypy, rust-analyzer, or clangd diagnostics merely because their
executables exist.

### 13.4 Result semantics

If a public tool is eventually approved, normalized output should retain:

- requested path;
- scope actually analyzed;
- result status: ok / partial / unavailable;
- providers considered;
- providers used;
- unavailable/skipped provider reason codes;
- counts by severity;
- diagnostics:
  - path
  - start/end line/character when trustworthy
  - severity
  - source/provider
  - diagnostic code/rule
  - message
- truncation information;
- coverage notes.

Never return a status named “clean”.

Zero diagnostics means only that the named providers reported no diagnostics for the
scope they actually analyzed.

### 13.5 Read-only proof is a release gate

Before such a tool is annotated readOnlyHint=true, its enabled provider set must pass
the side-effect test design in the companion document.

One unsafe profile invalidates the annotation for the tool configuration.

---

## 18. Acceptance criteria

The feature is acceptable only when all of these remain true.

### Compatibility

- Existing six ChatGPT tool surfaces remain unchanged through Phases 0–3.
- `tests/contracts/test_tool_surface.py` stays byte-for-byte satisfied without pin updates.
- `tests/contracts/test_golden_outputs.py` stays satisfied for all existing tools.
- `tests/contracts/test_surface_tokens.py` stays within the existing budget before any
  intentionally approved public-tool phase.
- Feature disabled/provider absent leaves existing tool behavior unchanged.
- `search_text` remains exact-only; the removed `@context` dispatch is not reintroduced.

### Safety

- No auto-install/download.
- No auto-execution of project-local provider commands.
- No workspace/applyEdit.
- READ workflows pass filesystem side-effect tests.
- Provider process tree is terminated on shutdown/reload.

### Reliability

- Provider crash/hang/malformed output cannot convert a successful baseline tool call into
  failure.
- Concurrent startup is single-flight.
- Timeouts do not leak pending requests/processes.
- Stale disk changes are synchronized before position-sensitive results are trusted.

### Performance

- MCP startup launches no provider.
- Provider-absent baseline overhead is negligible and cached.
- Existing-tool calls never synchronously wait for a provider process cold start.
- The primary performance gate is **resident steady state**, measured separately from
  cold/project-settling time.
- Standalone provider latency and end-to-end MCP latency are both measured so integration
  overhead is visible rather than attributed to the language server.
- Any enabled enrichment has a hard internal latency budget and measured p50/p95/p99.
- A latency result counts only when the semantic answer passes its correctness assertion.
- Resident process count, RSS, idle CPU, and long-session memory growth are bounded.
- End-to-end benchmarking follows the existing temporary-server/weekly-quality isolation
  model instead of calling the production server.
- Initial provider resource measurements use process-tree accounting; any future cgroup
  implementation is generic or deliberately delegated, not a call into the job-specific
  cgroup namespace.

### Truthfulness

- “No diagnostics” is never reported when no provider analyzed the target.
- Semantic provenance identifies provider/fallback source internally.
- Partial/unavailable states are explicit.
- LSP evidence does not silently replace source verification.

---

## 19. Explicit non-goals

This design does not attempt to:

- reproduce VS Code state;
- know cursor/selection/open tabs;
- consume unsaved buffers;
- launch a GUI or headless VS Code;
- expose raw LSP methods as MCP tools;
- make ChatGPT manage LSP lifecycle;
- auto-install language servers;
- apply code actions;
- perform LSP rename/format edits;
- run project-local provider commands without explicit trust;
- turn rust-analyzer/build-system execution into a READ tool;
- replace run_command for tests/builds;
- guarantee editor-identical diagnostics;
- support every LSP server with one generic profile.

---

## 20. Decisions now versus questions for evidence

### Decided now

- LSP is optional and lazy.
- Existing six-tool behavior is independent of Development Intelligence.
- No IDE integration.
- Disk is authoritative.
- Provider commands are never auto-installed.
- Project-local executables are not auto-executed.
- `readOnlyHint` requires audited side-effect-safe provider profiles.
- Cold/project-settling and resident warm performance are measured separately; they are
  not separate lifecycle states.
- Current `search_text` stays exact-only.
- The removed indexed `@context` path and persistent relation index are **not** restored.
- Semantic navigation is a separate explicit intent candidate (working name
  `inspect_symbol`), not hidden search enrichment.
- `check_code` is a separate diagnostics candidate.
- Neither candidate is an approved public MCP tool.
- LSP and analyzer execution remain separate internally.
- FastMCP lifespan owns provider cleanup in the first implementation.
- The job-specific cgroup module is precedent for accounting/cleanup, not a direct LSP API.
- Pyright remains the first audited production-profile candidate, while
  client compatibility/performance characterization is multi-provider from the start.

### To decide by PoC/measurement

- in-house narrow client versus an LSP client/type dependency;
- exact startup/request budgets;
- acceptable resident-request latency and Binnacle integration-overhead budgets;
- max resident instances/idle timeout;
- whether process-tree resource accounting is sufficient or generic per-provider cgroups
  are worth the systemd/delegation complexity;
- the model-friendliest `inspect_symbol` anchor schema;
- whether `inspect_symbol` produces enough workflow gain to justify standing surface/token
  cost;
- whether Pyright push diagnostics are useful enough to retain beside CLI diagnostics;
- whether `check_code` produces enough workflow gain to justify another public MCP slot;
- which provider profiles should be production-enabled after the first audited profile(s),
  based on actual usage, safety, latency, and resource cost.

---

## 21. Recommended immediate next work

The next development work should **not** add a public LSP tool and should **not** modify
`search_text`.

The next commit series should implement only:

1. deterministic fake LSP/analyzer fixtures;
2. a reusable **standalone multi-provider benchmark harness**;
3. the bounded protocol/process PoC;
4. lifecycle cleanup through FastMCP lifespan;
5. multi-provider compatibility probes plus the first audited profile(s);
6. a private `semantic.inspect_symbol(...)` integration API;
7. end-to-end Binnacle integration benchmarks using the existing temporary-server quality
   infrastructure;
8. workflow A/B between current search/read navigation and private semantic navigation.

Only after those results should the project decide whether to expose `inspect_symbol`,
then separately whether to pursue `check_code`.

This ordering deliberately measures provider speed, Binnacle overhead, semantic correctness,
and model-step efficiency as different quantities before any public contract changes.

---
