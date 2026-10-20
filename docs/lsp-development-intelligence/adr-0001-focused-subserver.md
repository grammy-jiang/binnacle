# ADR-0001: Focused Development Intelligence FastMCP Sub-server

**Status:** Architecture design accepted for P1 private fixtures only, independent P0.5 follow-up GO (2026-10-21)
**Date:** 2026-10-20; review amendments 2026-10-21
**Active worktree:** `~/Projects/binnacle-lsp-isolated-20261021`
**Branch:** `feat/lsp-isolated-p0-review-20261021`
**Baseline:** `origin/master` `40aafcd`; original V2 docs at `861ab299`

## Context

Binnacle's `application.create_application()` composes three independent focused FastMCP children: Files, Search, Commands. Development Intelligence introduces a distinct agent intent (semantic navigation and diagnostics) and a long-lived/one-shot provider execution backend. It does not belong inside exact Search, filesystem Files, or durable Commands.

FastMCP 4.1.0 supports `root.mount(child, namespace=None)` and participates in mounted child lifespans. The installed `FastMCPProvider.lifespan` delegates to the child's lifespan manager and reuses the root's process-level context infrastructure. Parent middleware runs on mounted tool requests, but per-child state is not automatically identical to the parent's. Do not infer lifecycle behavior from outdated FastMCP 2.x documentation.

## Architecture decision (private-stage GO; public registration conditional)

1. Establish a fourth **focused FastMCP child** named `binnacle-development-intelligence` and created through `create_development_intelligence_server(...)`, following the current native composition pattern.
2. Mount it into the **same** per-host Binnacle root, with no separate HTTP listener, MCP credentials, daemon, or cross-host coordinator.
3. Give the child only MCP adapter responsibilities: tool registration, input normalization, typed results and delegation to injected domain services. Keep JSON-RPC framing, provider capabilities, filesystem scope, lifecycle, telemetry and OS handling out of MCP adapter modules.
4. Use a private `features/development_intelligence` feature domain with semantic/query services, LSP manager and one-shot analyzer runner. Keep provider-specific profiles under an internal provider namespace; do **not** create an MCP sub-server per programming language or per provider.
5. **Single lifecycle owner:** `application.create_application` injects the Development Intelligence manager into the child and owns provider manager enter/close through the root's lifespan. Child user lifespans must not independently launch a second manager. FastMCP's mounted child lifespan participation must be exercised in tests for exception-safe, once-only start/close ordering. Opened File access precedes maintenance startup and inert manager entry; cleanup reverses that order and propagates failures after bounded drain, including partial startup or cancellation.
6. The module and its factory must be inert at import and root creation. Merely mounting a child must not start a language server. Providers launch lazily only on a permitted explicit analysis invocation.
7. Keep the child **unmounted from production** during private research/P1-P4; test it through a temporary FastMCP application when needed. Production mounting is allowed only for an approved, configured public tool in P5/P6.
8. Keep `namespace=None` if approved to preserve clean, intent-centered tool names such as `inspect_symbol` and `check_code`, using root `on_duplicate="error"` and explicit name-collision tests. Do not create raw `lsp_definition` etc. tools. Exact public names remain conditional on A/B results.
9. When a public tool is approved, include it in the appropriate `Settings.client_tools` profile(s) deliberately, then update `PublicToolOrder` and the complete surface/visibility/golden/token contracts. **Important:** unrestricted/default clients currently see all mounted tools, so an allowlist just for ChatGPT cannot safely hide a prematurely mounted public child.
10. Keep READ hints conditional on proven per-provider side-effect **and effective OS confinement** evidence, not on the sub-server's name or whether its tool function only sends a request. Lack of escape-proof cleanup or file/process/network restriction blocks READ and public untrusted-workspace registration.
11. **Authorization is host-owned, not client-name-owned.** With today's shared MCP token, all authenticated callers have the same configured provider/root/mode authority. The existing ChatGPT/default visibility lists are UX/product surface controls, not authorization boundaries. Feature-disabled and profile/root refusal must execute even if a direct `tools/call` bypasses discovery.
12. **Configuration must fail closed.** Reserve `[development_intelligence]`; reject unknown nested keys and top-level near-miss feature sections even under legacy `Settings.extra=ignore`. Validate disabled configs; never fall back to project executables.
13. **Import-safe and privacy-safe.** The frozen server startup inventory imports the disabled feature's modules; optional binaries cannot be import dependencies. Default sanitized telemetry never logs source/protocol/stderr. Existing opt-in full capture is sensitive and remains independent, without automatic enabling by LSP.

## Proposed module boundaries (not code commitments)

```text
src/binnacle/
  application.py                         # dependency injection + conditional mount
  server.py                              # host production assembly only
  features/development_intelligence/
    __init__.py
    intelligence_server.py               # focused FastMCP child factory
    tools/
      inspect_symbol.py                  # only after public product GO
      check_code.py                      # separately gated
    domain/                              # results, requested/actual scope, provenance
    workspace/                           # allowed roots, disk snapshots, sync
    protocol/                            # stdio JSON-RPC LSP client
    providers/                           # audited provider profiles and trust
    runtime/                             # process/session managers, one-shot analyzers
    semantic/                            # private high-level symbol inspection
  platform/contracts/                    # only required native process/access seams
  platform/linux/                        # native process/access implementation if needed
  platform/darwin/                       # native process/access implementation if needed
```

This is a conceptual ownership map. The implementation must split modules according to actual responsibilities, existing import contracts and the 500-line policy; do not generate a nested package hierarchy merely to match this example.

## Why not alternatives?

- **Extend Search:** semantic resolution is not exact regex/literal search and must not revive removed `@context` dispatch or confuse golden outputs.
- **Extend Files:** source-file permissions and symbol relationships are different concerns; hidden provider execution complicates the Files READ contract.
- **Extend Commands:** an LSP provider is reconstructable application infrastructure, not a user-managed durable command job; analyzer CLIs need separately audited execution.
- **Create independent network MCP service:** extra credentials, transport, deployment, IPC, monitoring and failure modes without a demonstrated requirement.
- **Create one MCP child per language server:** tool proliferation, duplicated lifecycle and inconsistent permissions; provider runtime should be internal, selected by capability and audit.

## Required verification before code and rollout

- P0.5: approve child ownership, public mounting gate, naming and lifecycle source of truth; record GO/REWORK.
- P1/P2: fake child with root middleware, injected manager and lifespan tests. Disabled private/default production tree must preserve current 6/8 tool counts and hashes, without provider spawn.
- P2: platform-neutral process manager ownership must not depend on durable Jobs; Linux and Darwin reload/shutdown/descendant tests.
- P3/P4: only audited providers in private benchmark harness; validate correct source locations, authorized results, side effects and complete agent workflow metrics.
- P5/P6: conditional child registration only on independently approved public intent. Cover `tools/list`, `tools/call`, parent auth/visibility/admission, tool ordering, schema/golden hashes, token budget, default-client exposure and rollback.

## Related documents

- [Architecture review](current-architecture-review-2026-10-20.md)
- [Technical design V2](functional-technical-design-v2.md)
- [Implementation plan V2](implementation-plan.md)
- [Capability mapbook V2](capability-mapbook-v2.md)

**P0.5 history:** Initial independent review returned REWORK; seven amendments were resolved in the [P0.5 decision register](p0-5-architecture-resolution-2026-10-21.md), then accepted by the [independent follow-up](p0-5-followup-review-2026-10-21.md) for private P1 fixture research only. No production LSP tool registration, provider execution or runtime deployment is authorized by this ADR alone.
