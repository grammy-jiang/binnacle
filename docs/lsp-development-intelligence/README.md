# Development Intelligence / LSP — design index

**Status:** P0.5 architecture **GO for P1 private test fixtures only** (2026-10-21 independent follow-up, after initial REWORK). No production LSP implementation, mount, or deployment.
**Current review baseline:** remote `origin/master` at `40aafcd` (2026-10-21); initial V2 design baseline was `ce943ced` (2026-10-14).
**Active isolated worktree:** `~/Projects/binnacle-lsp-isolated-20261021`; branch `feat/lsp-isolated-p0-review-20261021`.
**Previous design:** `design/lsp-development-intelligence-2026-09-27`, last design commit `2b477bd1`.
**Scope:** one Binnacle server on one machine. Do not introduce a cross-machine LSP controller.

## Authoritative V2 documents

Read only what is needed:

| Document | Purpose |
| --- | --- |
| [Current architecture review](current-architecture-review-2026-10-20.md) | Verified source baseline, current integration points, refactor gaps and open verification |
| [Focused sub-server ADR](adr-0001-focused-subserver.md) | Fourth mounted child and root-owned runtime accepted as private-stage design; public release conditional |
| [Functional and technical design V2](functional-technical-design-v2.md) | Responsibilities, protocol/lifecycle, security, results, failure handling and integration |
| [Provider capability mapbook V2](capability-mapbook-v2.md) | Provider/language capabilities, evidence, trust, cost, host inventory and upgrade rules |
| [Development capability portfolio](development-capability-portfolio.md) | Agent-first candidate roadmap beyond LSP: structure, impact, tests, failures, debugging |
| [Historical trajectory evaluation plan](historical-trajectory-evaluation-plan.md) | Reuse old tool/tunnel logs and session observer for opportunity mining, task replay and paired agent A/B |
| [2026-10-21 full-capture readiness](full-capture-readiness-2026-10-21.md) | Rebasing and on-host audit of unredacted full MCP payload, retained job output and task-replay limitations |
| [E0/E1 retrospective opportunity pilot](e0-e1-trace-pilot-2026-10-21.md) | Host-local anonymous extraction, frozen three-host evidence and conservative tool-candidate priorities |
| [E0/E1 independent review trail](e0-e1-independent-review-2026-10-21.md) | Initial REWORK findings, corrected defects and final bounded GO evidence |
| [E2 sample cohort and evidence gaps](e2-historical-sampling-2026-10-21.md) | 49 host-local sampled request groups, 11 controls and reasons real task labels/R2 snapshots remain unverified |
| [E2 technical review](e2-independent-review-2026-10-21.md) | Security and reproducibility review trail, technical GO vs pending independent task/gold acceptance |
| [E2.1 local trace relinking](e2-1-local-trace-recovery-2026-10-21.md) | Three-host 49/49 opaque case restoration, 697 tool events, independent limited GO and residual task/source uncertainty |
| [E2.2 independent task-source precheck](e2-2-independent-task-source-2026-10-21.md) | Mac full and two-Pi narrow source leads; 2 task-ID overlaps, 0 verified original user tasks |
| [E2.2 technical review](e2-2-independent-review-2026-10-21.md) | Fail-closed session coverage, same-repository provenance, read-only checkpoint and limited technical GO |
| [P2.0 default-off implementation](p2-0-default-off-configuration-2026-10-21.md) | Strict opt-in config, startup inventory and disabled/enabled in-memory tool-surface parity |
| [Implementation plan V2](implementation-plan.md) | Gated roadmap, executable work packages, dependencies, acceptance and release decisions |
| [P0.5 resolution](p0-5-architecture-resolution-2026-10-21.md) | Seven design issues, binding decisions and retained runtime gates |
| [P0.6 host inventory](p0-6-host-readiness-2026-10-21.md) | Read-only actual service-PATH/OS/provider locator evidence on MacBook and two Raspberry Pi hosts |
| [P1 native validation](p1-native-validation-2026-10-21.md) | Three-host, two-seed deterministic fake fixture/benchmark tests and baseline contract evidence |
| [P1.9 acceptance and independent reviews](p1-9-acceptance-2026-10-21.md) | Initial REWORK, defect remediation, independent GO, five Python versions and Linux native tests |
| [Initial independent review](p0-5-independent-review-2026-10-21.md) | Initial read-only REWORK findings against pre-amendment code |
| [Independent follow-up GO](p0-5-followup-review-2026-10-21.md) | Independent verification of seven amended contracts, permitting only P1 private fixtures |

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

P0.5 independently passed **for private P1 fixtures only** on 2026-10-21, after documented REWORK and review. The earlier P1.1 tests were developed provisionally and are now eligible as fixture evidence, not runtime/product proof. P0.6 and P1.1–P1.9 are completed as **private, synthetic-only** evidence; P1.9 independent follow-up GO was recorded on 2026-10-21. P2 remains unstarted and requires its own implementation and safety gates. No P2 integration, provider, READ/public registration or deployment approval follows from P0.5.
Use an isolated worktree and a commit per focused implementation item. Preserve users' live services, old design branch, and existing dirty main worktrees. All repository artifacts (including docs and tests) are in English.

## Reading order

Start with the [architecture review](current-architecture-review-2026-10-20.md); then the [capability mapbook](capability-mapbook-v2.md), [technical design](functional-technical-design-v2.md) and [implementation plan](implementation-plan.md). Consult V1 documents only when a V2 item refers to their historical evidence.
