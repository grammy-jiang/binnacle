# Development Intelligence implementation — P0/P1 foundations

| | |
| --- | --- |
| **Status** | Session-sized execution plan split 2026-09-30 |
| **Current baseline** | `f1493ee` |
| **Purpose** | Deterministic harnesses, raw benchmark foundation, protocol client, lifecycle, and FastMCP ownership |
| **Roadmap index** | `docs/lsp-development-intelligence/implementation-plan.md` |

> Execute exactly one work item per ChatGPT session unless the item itself is split further.

---

## 3. Phase P0 — deterministic harness and standalone benchmarks

Goal: create trustworthy test/measurement infrastructure before production LSP code.

Read for this phase:

- `README.md`
- `providers-and-safety.md`
- `testing-core.md`
- `testing-performance.md`

### P0.1 — fake LSP server skeleton

**Depends:** none.

**Scope:** deterministic stdio fake server with only `initialize`, `initialized`, one
simple request/response, `shutdown`, and `exit`.

**Do not include:** fault modes, server requests, diagnostics, real providers.

**Validate:** focused normal-lifecycle fixture test.

### P0.2 — fake semantic responses

**Depends:** P0.1.

**Scope:** configurable document symbols, workspace symbols, definition, references.

**Validate:** one test per response type plus request recording.

### P0.3 — fake notifications and server requests

**Depends:** P0.1.

**Scope:** push diagnostics plus controlled `workspace/configuration`,
`workspace/applyEdit`, and unknown server request.

**Validate:** fixture records the client response.

### P0.4 — fake framing/data faults

**Depends:** P0.1.

**Scope:** malformed/missing `Content-Length`, invalid JSON, split/coalesced data, oversized
header/body.

**Do not include:** process crash/hang/shutdown behavior.

**Validate:** every framing fault can be triggered independently.

### P0.5 — fake lifecycle/process faults

**Depends:** P0.1.

**Scope:** delayed response, hang, process crash, ignored shutdown, child-process spawn.

**Do not include:** malformed frame implementation.

**Validate:** every lifecycle fault can be triggered independently.

### P0.6 — fake analyzer + side-effect fixture

**Depends:** none.

**Scope:** one fake one-shot analyzer supporting success, structured diagnostics, crash,
sleep, oversized output, workspace sentinel write, and child spawn.

**Validate:** test harness detects the intentional workspace write.

### P0.7 — standalone benchmark harness core

**Depends:** P0.1/P0.2.

**Scope:** raw stdio-LSP benchmark runner for one generic provider configuration, JSON
output, repeated requests, timing, result count, gold assertion hook.

**Do not add:** language-specific fixtures.

**Validate:** fake server only.

### P0.8 — benchmark process/resource sampling

**Depends:** P0.7.

**Scope:** process-tree RSS, child count, idle CPU, cold/settling/warm labels.

**Validate:** synthetic child is counted.

### P0.9 — benchmark artifact identity

**Depends:** P0.7.

**Scope:** provider path/version, Binnacle commit, workload identity, host/Python,
command/options, sample counts, correctness status.

**Validate:** two runs can be classified comparable/not-comparable.

### P0.10 — provider-matrix discovery report

**Depends:** P0.7.

**Scope:** report configured providers as installed/not_installed. No installation.

**Validate:** a missing provider is explicit.

### P0.11 — Phase P0 harness review

**Depends:** P0.1–P0.10.

**Scope:** review only; no new feature code. Compare harness with testing design and create
new work items for any gaps.

**Validate:** fake suite green; benchmark fake run reproducible.

**Done:** GO/REWORK decision before P1.

---

## 4. Phase P1 — private LSP protocol and lifecycle

Goal: implement a bounded internal LSP client with no MCP surface change.

Read:

- `runtime-architecture.md`
- `testing-core.md`
- `testing-safety-contracts.md`

### P1.1 — framing parser

**Depends:** P0.1/P0.4.

**Scope:** parse bounded `Content-Length` stdio frames; valid fragmented/coalesced input.

**Validate:** valid framing tests only plus buffer bound.

**Done:** parser is pure/testable and performs no process management.

### P1.2 — framing error policy

**Depends:** P1.1.

**Scope:** missing/invalid length, malformed JSON, truncated EOF, oversized header/body.

**Validate:** fault fixture cases.

**Done:** malformed provider data cannot create unbounded memory or a hang.

### P1.3 — JSON-RPC request dispatcher

**Depends:** P1.1.

**Scope:** request IDs, pending map, out-of-order responses, notifications.

**Validate:** concurrent fake responses route to correct waiter.

**Done:** transport correlation works without process lifecycle logic.

### P1.4 — timeout and late-response handling

**Depends:** P1.3.

**Scope:** per-request deadline, pending cleanup, safe discard of late/duplicate/unknown IDs.

**Validate:** deterministic delayed-response tests.

**Done:** no timed-out waiter leaks.

### P1.5 — server-to-client request policy

**Depends:** P1.3, P0.3.

**Scope:** safe responses for configuration/progress/dynamic registration policy;
`workspace/applyEdit` rejected; unknown request error.

**Validate:** fake server records policy result.

**Done:** READ client cannot be tricked into edits/commands.

### P1.6 — provider process wrapper

**Depends:** P1.2–P1.5.

**Scope:** spawn one stdio provider, initialize, capture capabilities, initialized,
shutdown/exit.

**Validate:** normal fake-provider lifecycle.

**Done:** one process can be owned/released cleanly.

### P1.7 — crash and forced-shutdown escalation

**Depends:** P1.6, P0.5.

**Scope:** provider exit fails pending requests; ignored shutdown escalates to process-group
TERM/KILL.

**Validate:** parent and spawned child are gone.

**Done:** process cleanup is deterministic.

### P1.8 — position encoding

**Depends:** P1.3.

**Scope:** negotiated/default position conversion with UTF-16 minimum.

**Validate:** ASCII, Chinese, combining marks, emoji/non-BMP round trips.

**Done:** semantic coordinates are trustworthy.

### P1.9 — disk-authoritative document sync

**Depends:** P1.6.

**Scope:** `didOpen`/hash/version, no-change fast path, `didChange` after external disk edit,
`didClose`.

**Validate:** fake server sees exact versions/text.

**Done:** no unsaved-editor state is introduced.

### P1.10 — workspace resolver

**Depends:** none from LSP transport.

**Scope:** allowed-root guard, Git worktree root, provider marker fallback, narrow fallback.

**Validate:** nested worktree/non-Git/outside-root cases.

**Done:** provider roots cannot silently widen.

### P1.11 — manager single-flight registry

**Depends:** P1.6, P1.10.

**Scope:** one instance per workspace/profile; concurrent start requests share one start.

**Validate:** many callers create one fake process.

**Done:** no duplicate provider startup.

### P1.12 — residency limits and eviction

**Depends:** P1.11.

**Scope:** max resident instances, idle/LRU selection, never evict in-flight provider.

**Validate:** fake-clock tests.

**Done:** residency is bounded without provider-specific tuning yet.

### P1.13 — FastMCP lifespan ownership

**Depends:** P1.11/P1.12.

**Scope:** initialize manager through FastMCP lifespan; close all providers on lifespan exit.

**Do not register:** any new MCP tool.

**Validate:** integration test leaves no provider process.

**Done:** runtime ownership matches Binnacle server lifecycle.

### P1.14 — Uvicorn reload/process-tree regression

**Depends:** P1.13.

**Scope:** simulate/reproduce source reload lifecycle and prove old provider tree dies.

**Validate:** repeated teardown/start cycles produce no orphan accumulation.

**Done:** reload safety is explicit.

### P1.15 — six-tool invariance checkpoint

**Depends:** P1.13.

**Scope:** no new code unless needed. Run current surface/golden/token/search preservation
contracts with manager enabled/provider absent.

**Validate:** existing pins remain unchanged.

**Done:** private subsystem has zero current MCP contract drift.

---
