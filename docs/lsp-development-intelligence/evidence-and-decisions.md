# Development Intelligence — evidence and decisions

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Why the design exists, what changed since 2026-09-27, and which decisions are already fixed |
| **Source index** | `docs/lsp-development-intelligence-design-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 1. Executive decision

The core idea remains valid on the 2026-09-30 codebase: Binnacle can act as a headless
LSP client and gain useful language-aware intelligence without VS Code, a GUI, or editor
state.

The **integration target has changed materially** since the original 2026-09-27 design.

On 2026-09-28 Binnacle removed the indexed `search_text("@context ...")` pilot after its
pre-declared benchmark failed decisively:

- real ChatGPT queries: recall@3 4/29 = 14%;
- labelled questions: recall@3 13/26 = 50%;
- both below the 70% bar;
- the indexed-first workflow used **more** steps than exact search.

Current `search_text` is exact regex/literal search only. Its surface and outputs were
explicitly preserved when the pilot was removed.

Therefore Development Intelligence must **not** be designed as a replacement backend for
the removed natural-language repository retriever, and it must not silently recreate an
`@context`-like mode inside `search_text`.

The revised product split is:

1. **existing repository discovery stays as-is** — `search_text` + `read_file` remain the
   deterministic orientation/evidence path;
2. **semantic navigation** is a distinct possible agent intent — "what is this symbol,
   where is it defined, and where is it used?" — evaluated privately first;
3. **diagnostics/static analysis** is another distinct possible intent, with one-shot
   analyzer CLIs preferred where they provide clearer completion semantics.

The first implementation stages must not change the six ChatGPT-visible tools:

1. `read_file`
2. `list_files`
3. `search_text`
4. `run_command`
5. `job_status`
6. `stop_job`

A future semantic-navigation tool (working name `inspect_symbol`) and a future diagnostics
tool (`check_code`) are **separate gated candidates**. The evidence may justify neither,
one, or both. No public tool is required merely to build and benchmark the internal LSP
client.

The architectural invariants are:

- Binnacle starts and works normally with zero language servers/analyzers installed;
- installation of Binnacle does not install language servers or analyzers implicitly;
- existing six-tool calls do not fail because Development Intelligence failed;
- current exact `search_text` behavior and output remain independent of Development
  Intelligence;
- Development Intelligence does not restore the removed `@context` dispatch or persistent
  relation index;
- no cold provider is awaited by a normal existing-tool call;
- long-lived providers are reused across MCP calls while the server process is alive;
- repository-controlled executables are never auto-executed through a read-only path;
- a tool carrying `readOnlyHint=true` may use only provider profiles proven not to mutate
  the workspace or execute untrusted project code;
- unsupported, slow, incompatible, or crashed providers degrade cleanly;
- semantic answers retain provider/source provenance and are verified against source when
  ambiguity matters.

The repository has also strengthened its change-control boundary since 2026-09-27:
tool count, complete tool surfaces, golden outputs, and ChatGPT surface-token budget are
now contract-tested. A future seventh tool is therefore a deliberate product/API change,
not merely another registered Python function.

---

## 2. Investigation method and evidence

This document has now been reviewed twice against live code rather than treated as a
self-contained plan.

### 2.1 Current Binnacle implementation — revalidated 2026-09-30

The design branch is rebased onto `master` `f1493ee`.

The only master change after the initial 2026-09-30 revalidation was the resource-history
schema-v2 clarification: `call_id` correlation plus explicit final versus cumulative memory
semantics. It does not change the LSP product boundary; §4.5 in `runtime-architecture.md`
records the reusable accounting lesson.

Current implementation reviewed:

- `src/binnacle/config.py`
- `src/binnacle/server.py`
- `src/binnacle/server_unit.py`
- `src/binnacle/visibility.py`
- `src/binnacle/tools/__init__.py`
- `src/binnacle/tools/search_text.py`
- `src/binnacle/search_text_register.py`
- `src/binnacle/tools/run_command.py`
- `src/binnacle/tools/job_status.py`
- `src/binnacle/job_manager.py`
- `src/binnacle/job_manager_unit.py`
- `src/binnacle/job_cgroup.py`
- `src/binnacle/job_resource_history.py`
- current contract/integration/unit test layout.

The former indexed-context implementation modules no longer exist on master. Their final
state is preserved by tag `archive/indexed-context-pilot-2026-09-28`.

### 2.2 Current project design/evidence

Revalidated against:

- `docs/agent-toolset-design.md`
- `docs/tools/search_text.md`
- `docs/indexed-context-pilot.md` — including the 2026-09-28 closing benchmark/removal;
- `docs/quality-guard-plan-2026-09-27.md`
- `docs/testing.md`
- `docs/usage-analysis-2026-09-27.md`
- `docs/tools/run_command.md`
- `tests/contracts/test_tool_surface.py`
- `tests/contracts/test_golden_outputs.py`
- `tests/contracts/test_surface_tokens.py`
- `scripts/weekly_bench.py`.

These now establish stronger constraints than the first LSP draft assumed:

- ChatGPT's tool count is contract-pinned at six;
- each served tool's name/description/schemas/annotations is hash-pinned;
- current ChatGPT surface budget is 2262 `o200k_base` tokens with a 5% tolerance;
- deterministic tool outputs have golden snapshots;
- weekly quality automation already has a fixed temporary-server latency benchmark and
  isolation policy.

### 2.3 Upstream protocol/provider documentation

Checked against current upstream sources:

- LSP overview and current 3.18 specification:
  <https://microsoft.github.io/language-server-protocol/>
- Pyright settings/configuration:
  <https://github.com/microsoft/pyright/blob/main/docs/settings.md>
  <https://github.com/microsoft/pyright/blob/main/docs/configuration.md>
- TypeScript language server:
  <https://github.com/typescript-language-server/typescript-language-server>
- rust-analyzer:
  <https://rust-analyzer.github.io/book/configuration>
- clangd:
  <https://clangd.llvm.org/design/indexing>
  <https://clangd.llvm.org/config.html>
- Marksman:
  <https://github.com/artempyanykh/marksman>
- bash-language-server:
  <https://github.com/bash-lsp/bash-language-server>
- make-ls:
  <https://github.com/owenrumney/make-ls>
- Ruff:
  <https://docs.astral.sh/ruff/configuration/>
- mypy:
  <https://mypy.readthedocs.io/>

### 2.4 Live provider experiments

The raw-LSP measurements from 2026-09-27 remain useful because the providers and their
semantics are independent of Binnacle's deleted indexed pilot. They are retained in `providers-and-safety.md` §5
as preliminary feasibility data, not current production guarantees.

The managed Binnacle service still relies on its service `PATH`; project-local `.venv/bin`
or `node_modules/.bin` commands must not be auto-executed merely because a repository
contains them.

### 2.5 Runtime/provider recheck — 2026-09-30

The protocol/runtime assumptions used by the PoC have not drifted:

- Binnacle still pins FastMCP `4.0.0b5`;
- the installed `FastMCP` constructor still exposes a lifespan parameter;
- Pyright remains 1.1.413;
- typescript-language-server remains 6.0.0;
- rust-analyzer remains 0.3.3016-standalone;
- clangd remains 19.1.7;
- Marksman remains 2026-02-08;
- bash-language-server remains 5.6.0.

Therefore the earlier raw-provider measurements remain comparable as preliminary evidence.
They still need the planned reproducible benchmark harness before becoming acceptance
thresholds.

---

## 3. Correction ledger

| Earlier idea/assumption | Current finding | Current decision |
| --- | --- | --- |
| `search_text @context` could be the main LSP integration host | The entire indexed-context pilot was removed 2026-09-28 after recall and step-efficiency benchmarks failed | **Do not integrate LSP through `@context` and do not recreate the removed persistent index.** Keep exact search unchanged |
| Semantic navigation should transparently enrich repository orientation | LSP definition/reference methods need a concrete symbol/position; they do not solve a natural-language behavior question from scratch | Treat symbol navigation as a separate explicit agent intent candidate, benchmarked against search/read workflows |
| A seventh tool changes visibility/description only | The repository now pins six-tool count, complete surfaces, golden outputs, and a 2262-token ChatGPT surface budget | Any new tool requires an intentional contract/budget update with measured user benefit |
| `READY` after initialize describes all performance | First requests may still pay indexing/project-model cost, but the intended usage keeps providers resident | Keep the simple process lifecycle; benchmark cold/settling/warm separately and enforce request deadlines |
| LSP diagnostics are the clearest LSP-driven public intent | Pyright uses push diagnostics in the tested version; one-shot CLIs can give clearer completion semantics | Keep diagnostics separate from semantic navigation; `check_code` remains gated |
| Any known analyzer can sit behind read-only `check_code` | Ruff/mypy caches, clangd index caches, and rust-analyzer build behavior can write/execute | Only audited side-effect-safe profiles may back a READ tool |
| Project-local executables are useful zero-config discovery sources | Repositories control `.venv/bin`, `node_modules/.bin`, scripts, and editor config | Never auto-execute project-controlled provider commands; require explicit trusted configuration |
| LSP and analyzers should share one mostly uniform provider abstraction | Lifecycle, completion semantics, trust model, and side effects differ materially | Share normalization/telemetry where useful, but keep separate LSP and one-shot analyzer managers |
| Per-provider resource monitoring had to be invented from scratch | Durable jobs now have cgroup-v2 accounting, peak memory, CPU/IO counters, async cleanup, and long-term resource history | Reuse the **design lessons**, not the job-specific module directly; the MCP service is not delegated like `binnacle-jobs.service` |
| Development reloads make long-lived LSPs constantly unstable | Dev Uvicorn now watches `src/` only, so docs/tests/scripts do not trigger reload | Lifespan-owned LSPs are more practical; source reload still must clean them correctly |

---

## 22. References

### Project-local — current master

- `docs/agent-toolset-design.md`
- `docs/tools/search_text.md`
- `docs/indexed-context-pilot.md` — historical pilot plus 2026-09-28 removal evidence
- `docs/quality-guard-plan-2026-09-27.md`
- `docs/testing.md`
- `docs/usage-analysis-2026-09-27.md`
- `docs/tools/run_command.md`
- `src/binnacle/config.py`
- `src/binnacle/server.py`
- `src/binnacle/server_unit.py`
- `src/binnacle/visibility.py`
- `src/binnacle/tools/search_text.py`
- `src/binnacle/tools/run_command.py`
- `src/binnacle/tools/job_status.py`
- `src/binnacle/job_manager.py`
- `src/binnacle/job_manager_unit.py`
- `src/binnacle/job_cgroup.py`
- `src/binnacle/job_resource_history.py`
- `tests/contracts/test_tool_surface.py`
- `tests/contracts/test_golden_outputs.py`
- `tests/contracts/test_surface_tokens.py`
- `scripts/weekly_bench.py`

Historical indexed-context source itself is no longer on master; use tag
`archive/indexed-context-pilot-2026-09-28` only when historical implementation details are
needed.

### Upstream

- LSP overview / 3.18 specification:
  <https://microsoft.github.io/language-server-protocol/>
- Pyright:
  <https://github.com/microsoft/pyright/tree/main/docs>
- TypeScript language server:
  <https://github.com/typescript-language-server/typescript-language-server>
- rust-analyzer:
  <https://rust-analyzer.github.io/book/>
- clangd:
  <https://clangd.llvm.org/>
- Marksman:
  <https://github.com/artempyanykh/marksman>
- bash-language-server:
  <https://github.com/bash-lsp/bash-language-server>
- make-ls:
  <https://github.com/owenrumney/make-ls>
- Ruff:
  <https://docs.astral.sh/ruff/>
- mypy:
  <https://mypy.readthedocs.io/>
- Microsoft lsprotocol:
  <https://github.com/microsoft/lsprotocol>
