# Development Intelligence / LSP — design index

**Status:** V2 design draft, 2026-10-20. No production implementation approved or started.
**Source baseline:** remote `origin/master` at `ce943ced75dc672f3e503b1e07682b6fa2181a5e` (last upstream commit dated 2026-10-14).
**Design worktree:** `~/Projects/binnacle-lsp-v2-20261020`; branch `design/lsp-v2-reassessment-20261020`.
**Previous design:** `design/lsp-development-intelligence-2026-09-27`, last design commit `2b477bd1`.
**Scope:** one Binnacle server on one machine. Do not introduce a cross-machine LSP controller.

## Authoritative V2 documents

Read only what is needed:

| Document | Purpose |
| --- | --- |
| [Current architecture review](current-architecture-review-2026-10-20.md) | Verified source baseline, current integration points, refactor gaps and open verification |
| [Functional and technical design V2](functional-technical-design-v2.md) | Responsibilities, protocol/lifecycle, security, results, failure handling and integration |
| [Provider capability mapbook V2](capability-mapbook-v2.md) | Provider/language capabilities, evidence, trust, cost, host inventory and upgrade rules |
| [Implementation plan V2](implementation-plan.md) | Gated roadmap, executable work packages, dependencies, acceptance and release decisions |

The V2 documents above override any contradictory V1 assumption. The files below are historical context, **not current work instructions**:

- `implementation-plan-v1-2026-09-30.md` (archived 91-item conceptual plan; provider expansion templates were separate);
- `implementation-foundations.md`, `implementation-providers.md`, `implementation-product.md`, `implementation-expansion.md` (V1 task definitions);
- `runtime-architecture.md`, `providers-and-safety.md`, `product-surface.md`, `evidence-and-decisions.md`;
- `testing-*.md` and the two 2026-09-27 top-level index files.

Historical evidence is valuable; its `f1493ee` source baseline is not interchangeable with V2. Do not execute a V1 item by ID without a V2 mapping and revalidation.

## Locked product constraints

- Initial phases register **no additional public MCP tool**. Existing ChatGPT six-tool and default eight-tool surfaces are unchanged.
- `search_text` remains exact regex/literal search; do not restore `@context` or silently route search to semantic results.
- Language servers are optional, lazy, reusable while serving, and managed by the application's FastMCP lifespan. Merely importing a module must not start a provider.
- A provider's advertised capability is not evidence of correct, safe, complete results.
- File disk state is authoritative. No editor GUI, unsaved-buffer synchronization or hidden code edits.
- No auto-downloads, unapproved project-local executables, automatic workspace edits, or implicit project-code execution.
- New READ-annotated public capabilities require evidence that enabled provider profiles meet side-effect policies; errors and coverage must remain honest.
- Human/model workflow improvement, not raw RPC speed, determines whether a public tool is justified.
- Platform support must cover Linux and macOS without merging all machines into one managed server.

## Execution policy

P0 (this revision) is **design and evidence only**. P1 may begin only after review accepts the V2 gates.
Use an isolated worktree and a commit per focused implementation item. Preserve users' live services, old design branch, and existing dirty main worktrees. All repository artifacts (including docs and tests) are in English.

## Reading order

Start with the [architecture review](current-architecture-review-2026-10-20.md); then the [capability mapbook](capability-mapbook-v2.md), [technical design](functional-technical-design-v2.md) and [implementation plan](implementation-plan.md). Consult V1 documents only when a V2 item refers to their historical evidence.
