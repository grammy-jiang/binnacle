# Binnacle current architecture assessment for Development Intelligence (V2)

**As of:** 2026-10-20. **State:** read-only investigation; not a test pass, deployment verification or LSP implementation.
**Baseline:** `origin/master` = `ce943ced75dc672f3e503b1e07682b6fa2181a5e`; last upstream commit 2026-10-14.
**Historical design baseline:** `f1493eec33656693c4a46c054fc293cbbba71847` (2026-09).
**Methods:** local `git show`, `git diff`, source/contract inspection, executable lookup; no GitHub connector, production service changes, source rebases or LSP launches.

## 1. Source authority and isolation

- Raspberry Pi working `master` was at `278af9c3`, 85 commits behind fetched `origin/master`.
- MacBook Pro working `master` was also at `278af9c3` when inspected.
- Raspberry Pi working `master` contains existing untracked unrelated design docs; do not overwrite, clean, reset or deploy it.
- The 2026-09-27 LSP design lives on `design/lsp-development-intelligence-2026-09-27`, last commit `2b477bd1`, and was absent from upstream branch listings at review.
- A dedicated V2 worktree was created directly at the current remote master. V1 documents were copied into that isolated worktree for reference; existing worktrees remain untouched.
- Historical design branch diverged from current main at `f1493ee`: approximately 4 design-only commits versus 794 subsequent commits on main at review. These are Git ancestry counts, **not** 794 LSP-specific changes.

### Measured refactor impact

Diffing `f1493ee..origin/master` under `src/binnacle` reports 265 affected files, 32,724 insertions and 2,712 deletions. Many are moves/splits rather than new business features. The old LSP assumptions about source locations and module boundaries cannot be trusted without remapping.

## 2. Current composition and injection points

| Current file / domain | Verified role | Implication for LSP V2 |
| --- | --- | --- |
| `src/binnacle/server.py` | Production bootstrap, guarded import preflight, `create_server`, ASGI app | Keep a composition root; no provider startup during module import |
| `src/binnacle/application.py` | OS-independent `create_application`, FastMCP lifespan, Files/Search/Commands mounts, visibility, middleware | Inject optional, private Development Intelligence runtime; no public mount until decision gate |
| `src/binnacle/features/files/` | Files tool adapters, OS-specific opened-grant access, path policy | Reuse authorization policy/contracts, not a writable file-tool capability shortcut |
| `src/binnacle/features/search/` | Exact-content search and result budget | No implicit LSP search enrichment or new `@context` mode |
| `src/binnacle/features/commands/` | Commands tools, durable job orchestration and backend | LSP is not a user durable command job |
| `src/binnacle/platform/composition.py` and `platform/contracts/` | OS selection and platform-neutral interfaces | Bind any native process/FS capability through narrow injected seams |
| `src/binnacle/mcp/` | Client identity, request/tool logging, visibility and admission | Public semantic tools must pass existing middleware/admission/identity chain |
| `src/binnacle/config.py` | Pydantic Settings, client-tool allowlist, allowed roots | Add default-off configuration with strict validation; no hidden tool enrollment |
| `src/binnacle/startup_imports.py` / `startup_server_modules.py` | Fail-closed, generated required import inventory | Keep new Python modules import-safe and refresh generated list + drift tests when implementation begins |

Current `application.create_application()` has an ASGI/FastMCP lifespan (enter File access, start optional maintenance sidecar, yield, stop sidecar, release File access). Integrate an independently owned LSP manager here via explicit dependency injection. The manager must **not** be instantiated with running subprocesses during `server.py` import.

The native FastMCP tree mounts exactly three focused children (Files, Search, Commands). Preserve this domain separation. A future public fourth child must be subject to a separately approved API/surface change, not smuggled into Search.

## 3. Public surface is locked

The checked `tests/contracts/test_tool_surface.py` pins ChatGPT to six tools: `read_file`, `list_files`, `search_text`, `run_command`, `job_status`, `stop_job`. The unfiltered profile has eight, including `edit_file` and `write_file`.

Other guards: `tests/contracts/test_golden_outputs.py`, `test_surface_tokens.py` (2,262 `o200k_base` token budget + 5% tolerance), `test_server_composition.py`, `test_visibility.py`, `test_darwin_interface.py`, and tool order/visibility transforms.

A seventh ChatGPT tool changes more than a `@mcp.tool` decorator. Approval must explicitly update profile configuration, ordering, description/schema hashes, golden outputs, token budget and client compatibility evidence. Keep them unchanged through all private phases.

## 4. Platform and process boundaries

Both Linux (Raspberry Pi) and Darwin (MacBook Pro) must be supported. Current platform contracts enforce that common domains do not import Linux systemd, cgroup or journald implementations. `application.py` already isolates most host-native behavior through composition.

Do **not** reuse the Linux job cgroup owner or Darwin durable Jobs manager for a reconstructable LSP server. Define an independently testable provider-process owner with bounded spawn, standard stdio transport, process-group/descendant cleanup and lifecycle closure. Native differences, including macOS child/session behavior, need real tests. Never claim complete descendant containment merely because a parent PID exited.

Separate service PATH from interactive shell PATH. Executable discovery and trust decisions must use the real installed Binnacle service environment at validation time, not the `command -v` snapshot below.

## 5. Host inventory (2026-10-20; SHELL PATH ONLY)

| Executable | Raspberry Pi / Linux aarch64 | MacBook Pro / Darwin arm64 |
| --- | --- | --- |
| pyright / pyright-langserver | found; pyright 1.1.413 | not on shell PATH |
| typescript-language-server | found; 6.0.0 | not on shell PATH |
| rust-analyzer | found; 0.3.3016-standalone | not on shell PATH |
| clangd | found; Debian 19.1.7 | found; `/usr/bin/clangd` |
| marksman | found; 2026-02-08 | not on shell PATH |
| bash-language-server | found; 5.6.0 | not on shell PATH |
| make-ls | found; symlink to `make-ls-v0.1.20` | not checked on shell PATH |
| yaml-language-server | found | not on shell PATH |
| vscode-json-language-server | found | not on shell PATH |
| ruff, gopls, ty, basedpyright-langserver | not on shell PATH | not on shell PATH |

Raspberry Pi reported ~16 GB RAM with Python 3.13.5; MacBook Pro 128 GB with Python 3.14.8. These results establish only PATH discovery; no launch, capability negotiation, side-effect or performance test occurred. Binnacle Git itself is a predominantly Python repository, with substantial Markdown documentation.

## 6. Constraints changed since V1

| V1 assumption | V2 required action |
| --- | --- |
| FastMCP server provides a lifespan | Inject into current `application.create_application` lifecycle; preserve maintenance File access and shutdown ordering |
| Existing path roots can simply be resolved | Treat LSP input paths, provider-read reach and output URIs as different trust boundaries; use stable allowed-root grants and TOCTOU tests |
| Linux-centric process work | Explicit Linux and Darwin process backends/adapters and root restrictions; do not depend on job manager |
| Import-time provider code can remain inert | Generated startup import inventory now imports required modules; guarantee no provider subprocess during this preflight |
| Six tool surfaces pinned | Still pinned; macOS also has release/visibility and capability contracts |
| Provider matrix from September | Versions/availability refreshed, new Makefile/YAML/JSON candidates; Go and native Ruff server added to research |
| Old LSP task files ready to execute | V2 work items must remap architecture/tests/dependencies; old P0.1 is no longer the unconditional first task |

## 7. Quality and release gates

Repository policy at reviewed baseline: maximum 500 physical lines per Python module, warning at 451; 95% branch coverage target for core modules from units, 90% for other production modules; architecture analyzer and Import Linter; strict startup module inventory; Python 3.10–3.14; and contract/CI checks. Check `docs/quality-gates.md` and `quality-policy.json` in the implementation worktree; do not weaken gates for this feature.

Cross-platform real tests must use safe temporary workspaces. Full CI passing is not proof that providers cannot execute untrusted workspace commands.

## 8. Open verification and release blockers

1. Obtain installed-service PATH and execution identity on each host without restarting production.
2. Verify the final LSP manager seam against the live FastMCP 4.1.0 / MCP 2.3.0 pairing in an isolated test app.
3. Confirm canonical root and symlink behavior for LSP input, include/definition output and project discovery (including Git worktree `.git` files).
4. Independently audit provider external caches, network, command/project-code execution and sandboxing on both OSes; READ annotations are not assumed.
5. Run fake-provider framing/crash/timeout, concurrency, cancellation and process-tree cleanup tests.
6. Run version-pinned LSP initialize/capability probes; produce machine-readable results with run metadata.
7. Execute provider correctness/resource benchmarks against micro, medium and real repositories. Distinguish raw LSP time from end-to-end MCP and model-step time.
8. Conduct an independent design review and record an explicit P0 GO/REWORK decision before production source changes.

## 9. Recommended ownership

- `features/development_intelligence/`: language-neutral domain models, workspace identity, policies, LSP/analyzer managers and internal normalized outcomes.
- `features/development_intelligence/providers/`: explicitly audited provider profiles and adapters; provider configs remain data, not project-local execution hooks.
- `platform/contracts/`: minimal OS-dependent process/access contracts where necessary; Linux and Darwin implementations live under existing platform boundaries.
- `application.py`: manager dependency injection and lifespan ownership only.
- `mcp/`: existing policy middleware, not a place to implement LSP protocol semantics.
- `server.py`: production assembly only, not JSON-RPC transport.

Names are conceptual proposals until architecture review and tests accept them.
