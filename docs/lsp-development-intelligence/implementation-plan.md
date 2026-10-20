# Development Intelligence / LSP — V2 implementation and validation plan

**Date:** 2026-10-20; reviewed 2026-10-21. **State:** P0.5 initial independent **REWORK**, followed by independent **GO for P1 private test fixtures only**. No production LSP source or public tool changes.
**Current review baseline:** `origin/master` `40aafcd` (original V2 baseline `ce943ced`). **Previous plan:** [2026-09-30 archived V1 plan](implementation-plan-v1-2026-09-30.md).
**Inputs:** [architecture review](current-architecture-review-2026-10-20.md), [functional/technical design V2](functional-technical-design-v2.md), [LSP capability mapbook V2](capability-mapbook-v2.md).

## 1. Execution principles (mandatory)

1. **Design -> evidence -> private implementation -> measured agent value -> public decision.** Do not promote a provider or MCP tool simply because LSP works in a tiny example.
2. Keep existing ChatGPT six-tool/default eight-tool contracts *unchanged* until an explicit public-tool approval. `search_text` stays exact. No hidden LSP decoration of Files/Search tools.
3. Local-first workflow, isolated Git worktree, small reviewable commit per work package. A separate chat session is **not** required for each package; a clear validation boundary and handoff are. Reassess dependencies before advancing.
4. One Binnacle server controls only its own host's providers. Protect active worktrees and existing running services. No reboots/redeployments in design or microbenchmark phases.
5. All code, tests, fixtures and documents are English. Provider/shell/build tool execution needs explicit permission and trust policy; no auto-installs.
6. Evidence must state whether it is docs-only, unit-fixture, synthetic real-provider, medium fixture, real-repository, integration or live deployment. Never silently convert between those categories.
7. Apply current architecture/coverage/import-inventory/size/security and cross-platform gates. Review and update the previous design only where source evidence requires it.
8. A public product can be abandoned after a failed gate without treating the private core infrastructure as a failure.

## 2. Phase dependency map

- **P0 Design reconciliation (NO CODE)** -> independent architecture and capability review.
- **Evaluation track E0–E7 (staged)** -> privacy-safe historical trace mining, frozen-gold corpora, controlled tool and agent A/B; see [evaluation plan](historical-trajectory-evaluation-plan.md).
- **P1 Deterministic test infrastructure** -> fake LSP/analyzer and reproducible benchmark/evidence harness.
- **P2 Private protocol/runtime** -> process owner, strict JSON-RPC, session/lifespan, document sync, no MCP surface changes.
- **P3 Audited provider profiles** -> Pyright first and breadth compatibility, OS/resource/side-effect evidence.
- **P4 Private agent-intent experiment** -> semantic API, corpora, A/B measured workflow and GO/STOP.
- **P5 Conditional public `inspect_symbol`** -> only if P4 passes and independent API review approves.
- **P6 Independent diagnostics experiment** -> analyzer/CLI evidence and conditional `check_code` decision (can start safe foundations after P2, need not wait for P5).
- **P7 Conditional provider/language expansion and release** -> per-provider safety/benefit gate and staged host rollout.

Go/no-go for P5, P6 public release and P7 are **independent**. Failures do not force an unsafe bundled release.

## 3. Work package register

Each item must have one scoped code/evidence change, acceptance proof and a commit or documented no-code decision. Dependencies refer to V2 IDs, not old V1 labels.

| ID | Work package and deliverable | Depends | Acceptance / exit evidence |
| --- | --- | --- | --- |
| P0.1 | Rebaseline current remote master, schema and native composition | — | Current commit, file paths and contract inventory recorded (**draft complete**) |
| P0.2 | Provider capability mapbook; service-vs-shell PATH distinction, upstream claims | P0.1 | All candidate languages, trust, evidence tags and gaps recorded (**draft complete**) |
| P0.3 | V2 responsibilities, protocol/process/security and failures | P0.1 | Technical draft with trust/access/exception model (**draft complete**) |
| P0.4 | Re-map V1 tasks and gates to current architecture, preserve V1 history | P0.1–P0.3 | This V2 plan and versioned V1 archive (**draft complete**) |
| P0.5 | Independent design review: focused FastMCP child ADR, agent capability portfolio, privacy-safe evaluation track, architecture/lifespan ownership, testability, READ and visibility policy | P0.1–P0.4 | 2026-10-21 first REWORK, seven decisions amended, independent follow-up **GO (P1 private fixtures only)**; [decision](p0-5-architecture-resolution-2026-10-21.md) / [sign-off](p0-5-followup-review-2026-10-21.md) |
| P0.6 | Non-intrusive host readiness inventory: deployed service PATH, OS process primitives, versions | P0.5 | Service-context evidence and exact executable fingerprint (**pending; no provider start on production**) |
| P1.1 | Minimal fake LSP stdio handshake, response framing | P0 GO for follow-on implementation | Isolated fixture originally implemented provisionally 2026-10-20; 2026-10-21 P0.5 GO makes subsequent private P1 tasks eligible, but not automatic |
| P1.2 | Fake capability/definition/references/symbol/hover payloads | P1.1 | Typed fixture cases including null/multiple/LocationLink |
| P1.3 | Fake notifications and server requests | P1.1 | Safe configuration response and edit/command refusal tests |
| P1.4 | Transport adversarial fixtures: split/coalesced/bad/oversized frames, late ID | P1.1 | Bounded parser negative coverage |
| P1.5 | Process failure fixture: hang, crash, orphan descendants, cancel, non-exit | P1.1 | Deterministic cleanup/timeout witnesses on Linux and Darwin |
| P1.6 | Fake analyzer: JSON diagnostics, cache/workspace sentinel writes, child spawn | P0 GO | Harness detects intentional side effects and false-clean results |
| P1.7 | Raw LSP benchmark harness + run identity and reproducible fixture manifest | P1.2/P1.4 | Gold assertions required for valid timing; results carry provenance |
| P1.8 | Provider process-tree sampling, cold/settle/warm and artifact comparator | P1.5/P1.7 | Child RSS/CPU counted; incompatible runs rejected |
| P1.9 | Independent fixture/harness reliability review | P1.1–P1.8 | Repeated deterministic passes and fault coverage checkpoint |
| P2.0 | Add strict, default-off feature/provider configuration and root-level near-miss rejection | P0.5 GO | Invalid disabled configs, misspelled TOML/env and unsafe profile fallback refused; legacy settings preserved |
| P2.1 | Decide narrow in-house JSON-RPC or vetted client dependency using P1 fixtures | P1.9 | ADR with dependency/security/maintenance tradeoffs |
| P2.2 | Strict framing/JSON-RPC request+notification dispatcher | P2.1 | Negative framing, unexpected response and cancellation tests |
| P2.3 | Server-to-client requests, capability negotiation, position encoding | P2.2 | Advertised vs unsupported, Unicode/UTF-16 and edit refusal tests |
| P2.4 | Cross-platform provider process owner and cleanup semantics | P1.5/P2.1 | Linux/Darwin spawn/kill/process-tree test with no leaked child |
| P2.5 | Authorized workspace resolver, disk snapshots and didOpen/didChange/didClose | P2.3 | Allowed-root, git-worktree, symlink/TOCTOU, stale-file tests |
| P2.6 | Manager registry: single-flight, concurrent requests, cooldown, bounded residency | P2.2/P2.4/P2.5 | Concurrent/no leak/timeout/eviction tests |
| P2.7 | Default-off FastMCP lifespan injection and guarded startup module manifest | P2.0/P2.6 | No import-time spawn, partial-start/cancellation/repeated-lifespan cleanup, direct-call denial and shutdown; existing 6/8 surfaces unchanged |
| P2.8 | OS and package/coverage/architecture regression gate | P2.7 | Production imports, module-size, coverage, Linux/Darwin and contract checks |
| P3.1 | Exact audited provider profile schema, discovery/source restrictions and trust classification | P2.8/P0.6 | Reject untrusted project-local command, unknown config, disabled provider |
| P3.2 | Pyright LSP profile and independent Pyright CLI analyzer profile | P3.1 | Capability negotiation + file/reference gold tests; CLI JSON completion |
| P3.3 | Filesystem/network/child-process side-effect audit for Pyright profile | P3.2 | Honest per-OS READ-eligible or trust-only classification, reproducible evidence |
| P3.4 | Provider breadth adapter/initialize probes: TS/JS, clangd, rust-analyzer, Marksman, Bash, make-ls, YAML/JSON | P2.8/P3.1 | Per-provider mapbook rows updated; unsafe servers benchmark-only |
| P3.5 | Medium and real-workspace capability/latency/memory matrix | P3.2/P3.4 | Versioned corpora and p50/p95/p99 with correctness, tree RSS, overhead |
| P3.6 | Provider selection, resource policy and capability-mapbook synthesis | P3.3/P3.5 | Audited provider allowlist; measured max instances/TTL/deadlines; GO/REWORK |
| P4.1 | Normalized semantic results, provenance and status model | P3.6 | Correct null/ambiguous/partial/stale/truncation serialization |
| P4.2 | Position anchor alternatives and definition/reference aggregation | P4.1 | Gold tests for repeated same-line tokens, Unicode, cross-file ambiguity |
| P4.3 | Optional hover/type/docs, untrusted URI and snippet filtering | P4.2 | Unsupported capabilities gracefully partial; no off-root content |
| P4.4 | Corpus: Python first, TS/JS and selected other languages | P4.3 | Human-reviewed gold locations and negative control cases |
| P4.5 | Private FastMCP test application, not production registration | P4.3/P2.8 | Existing clients/tools untouched, normal middleware/admission exercised |
| P4.6 | Raw vs Binnacle layer timing + model workflow A/B harness | P4.4/P4.5 | Same model/effort/tasks; unbiased correctness and token accounting |
| P4.7 | Execute repeated A/B and failure analysis | P4.6 | Quantified benefit/failures relative to baseline; not latency-only |
| P4.8 | Independent product GO/STOP decision | P4.7 | Explicit publish-or-stop evidence and recommended anchor schema |
| P5.1 | Conditional public schema usability/agent argument selection study | P4 GO | Agent picks tool and anchor reliably; bounded response design |
| P5.2 | Token/surface/visibility and host capability review | P5.1 | Document measured marginal standing cost and intentional budget effect |
| P5.3 | Explicit public SHIP/NO-SHIP approval | P5.2 | Independent sign-off including READ proof for every enabled profile |
| P5.4 | **Only on SHIP:** optional registration, six/eight-tool profile changes where approved | P5.3 SHIP | Deliberate contract/golden/token/order/visibility updates and rollback |
| P5.5 | **Only on SHIP:** isolated integration + Linux/macOS host release gates | P5.4 | CI, service-context validation, no regression, staged rollout |
| P6.1 | Mine actual lint/type-check `run_command` usage, task and token costs | P2/P0 GO | Deterministic usage corpus, no private source disclosure |
| P6.2 | Audited analyzer runner, normalized diagnostic results and coverage status | P1.6/P2.4 | Structured exit, side effect, timeout and no-false-clean tests |
| P6.3 | Pyright CLI/Ruff CLI comparison; LSP push vs pull completion audit | P6.2/P3.2 | Truthful analyzed scope and provider-specific safety evidence |
| P6.4 | Private `semantic.check_code` and A/B against shell commands | P6.3 | Correctness, clicks/calls/tokens/time, failure comparison |
| P6.5 | Independent `check_code` GO/STOP, optional public schema/contract rollout | P6.4 | Separate SHIP decision; no coupling to `inspect_symbol` |
| P7.Xa | Per-provider safety/trust and source-identity audit | Measured demand | ELIGIBLE / EXPLICIT-TRUST-ONLY / BENCHMARK-ONLY |
| P7.Xb | Conditional profile implementation and focused test | P7.Xa ELIGIBLE | One provider only, no combined rollout |
| P7.Xc | Real OS safety and correctness evidence | P7.Xb | Side effects, output boundaries, process cleanup, trustworthy results |
| P7.Xd | Resource, agent-usage and deployment acceptance | P7.Xc | Stable residency/cost, contract invariance, guarded release |

P7.X expands for TypeScript/JavaScript, clangd, Marksman, Bash, Makefile, YAML/JSON and Go **only as actual demand/evidence justifies**. rust-analyzer remains explicit-trust or benchmark-only unless a separate exceptional audit proves suitable confinement. Pyright Type Server Protocol and Ruff native LSP are future design investigations, not automatic P7 implementation.

## 4. Stage gates and release rules

### P0: design GO gate (passed for P1 private fixtures only)

- Review V2 against current `application.py` composition and startup module import manifest, not old source paths.
- Confirm separate process ownership and two trust boundaries: requested path authority **and** provider's own OS-level workspace/code execution reach.
- Approve provider profile and mapbook evidence semantics, including `advertised != tested != READ safe`. Host configuration is authority; client-name visibility is not permission. Require enforceable confinement before public READ and honest `cleanup_unverified` on escaped descendants.
- Accept or revise the proposed work package dependency order and provide explicit independent review record. The initial 2026-10-21 independent verdict was REWORK; seven [resolutions](p0-5-architecture-resolution-2026-10-21.md) received [independent design GO](p0-5-followup-review-2026-10-21.md) for P1 private fixtures. Strict config is P2.0 and must precede P2.7.

### P1/P2: private foundational GO

- Fake server can trigger all protocol faults deterministically; cancellation never leaves unresolved futures.
- No provider starts on import/startup/disabled; provider exit/reload eventually closes the whole owned process tree.
- Existing six ChatGPT/eight default tool order, descriptions, schemas, annotations, golden output and instruction hashes stay invariant.
- Code observes current module size, core/other branch coverage, architecture/OS import policies and generated startup inventory.

### P3: provider GO

- Exact binary origin/version, profile/settings and installed-service PATH known.
- Provider-specific capability negotiation and correct results on real corpus; no unsupported methods silently invoked.
- Security proof is independent: no unapproved project-code execution, workspace edits/cache spills, network or unmanaged children for an approved READ profile.
- Resource and correctness datasets cover warm resident, cold settling, idle and long-session cases; measured budgets replace guesses.

### P4: agent value GO / STOP

Pre-register a versioned, **numerical** correctness non-regression threshold, wrong-definition tolerance, sample/task sizing, workflow improvement threshold, confidence/variance method and RAM/CPU ceilings **before any A/B run**. Publish both success and failure cases. At minimum experimental correctness may **not deteriorate** versus baseline; require repeatable useful reduction in model steps, tool calls, tokens or task latency, without unacceptable provider memory/CPU or wrong-definition rates. Raw sub-millisecond RPC without end-to-end gain is NO-GO.

### P5/P6/P7: public release decision

Separate product sign-off and an intentional schema/token budget change. Stage deployment host by host only after OS-specific tests and service-readiness checks. Preserve a default-off/disable rollback path; rollback must remove provider workers and restore old profile visibility. Do not treat a green unit-test run as permission to restart production.

## 5. Verification matrix (planned, not yet executed)

| Layer | Scope and compulsory negative cases |
| --- | --- |
| Unit fake protocol | framing, partial messages, bad JSON/IDs, cancellation, server requests, supported/unsupported methods, dynamic registration |
| Unit domain | path/URI authorization, symlink/TOCTOU, Unicode offsets, same-line symbol ambiguity, result clipping and provenance |
| Process integration | parallel startups, dead/hung providers, orphan descendants, signal escalation, graceful/sharp reload on Linux and macOS |
| Real-provider micro | version-pinned Pyright, TS/JS, Rust, C/C++, Markdown, Shell, Makefile, YAML/JSON; correctness before latency |
| Medium/real workload | repeated warm calls, cold/settling, Binnacle overhead, RSS/CPU growth, project indexing and stale sync |
| Read-only security | workspace/external sentinels, extra process/network/cache behavior, denied client edit/execute commands |
| MCP contract | tool hashes/order/count, visibility, instructions, token cap, golden outputs, native Darwin and default client |
| Agent A/B | identical tasks/model/effort, gold anchors, argument failures, calls/steps/tokens/time, misleading/empty results |
| Release | CI Python 3.10–3.14, module size, coverage, lint/import gates, real host smoke, staged rollback |

Existing commands include `uv run python scripts/check_architecture.py`, `uv run lint-imports --no-logo`, `uv run python scripts/gen_startup_server_modules.py --check` (confirmed in the generator CLI source), `uv run tox -e coverage-policy` and the managed contract suite. Reconfirm command availability against the target implementation commit before execution.

## 6. Relationship to the V1 roadmap

| Historical V1 stage | V2 equivalent and material change |
| --- | --- |
| V1 P0 fake server + standalone benchmark | V2 P1, now following explicit current-source architecture/design P0 |
| V1 P1 protocol and manager | V2 P2 with FastMCP native composition, startup inventory and Linux/macOS process ownership |
| V1 P2 provider profiles | V2 P3, inventory extended and provider-trust criteria stronger |
| V1 P3 private `inspect_symbol` | V2 P4, with external URI policy, end-to-end model workflow A/B and current contracts |
| V1 P4 public `inspect_symbol` | V2 P5, only after separate GO decision |
| V1 P5 diagnostics | V2 P6, independent from public semantic release |
| V1 P6/P7 provider expansion and future research | V2 P7 per-provider conditional gates, non-LSP Type Server reserved for later design |

Do **not** mechanically port or execute the 2026-09-30 detailed session tasks. Treat them as task decomposition references. The files remain accessible via the design [index](README.md). Re-baseline dependencies/paths and split any cross-domain task discovered during implementation.

## 7. Handoff record and readiness definition

Each implementation/validation task records:

| Field | Requirement |
| --- | --- |
| Work item / baseline | V2 ID, commit of source baseline, current branch/worktree |
| Change scope | Exact files, primary behavior, untouched public contract assertion |
| Provider evidence | Binary hash/version, host/service PATH, trust profile, corpus and side-effect outcome |
| Test evidence | Commands, OS/Python, passing/failing counts and known skipped checks |
| Measured results | Correctness, request-level latency, end-to-end workflow and process resource use |
| Decisions | GO/REWORK/STOP with rationale, safety exceptions, independent reviewer |
| Delivery | Commit, clean worktree, next eligible task(s), deploy status and rollback plan |

The independent P0.5 first review returned **REWORK** on 2026-10-21; its seven design amendments received independent follow-up **GO for P1 private fixtures only**. The P0.6 service-context inventory and remaining private P1 work are now eligible, not executed here. The earlier P1.1 fake server was provisional, not an implementation waiver. P2 and public gates remain independent.

## 8. Risks, blockers and mitigation owners

| Risk | Required mitigation before production |
| --- | --- |
| Wrong symbol due to stale root/document/position | Authorized disk snapshot, encoding, repeated-token tests and stale revalidation |
| Project-configured language server runs commands or writes caches | Exact audited profiles, OS proof, explicit trust class and fail-closed READ |
| Missing provider on macOS while available on Pi | Service PATH probe and per-host opt-in; no implicit package install |
| Eager module import starts a provider | Import-inert modules + generated startup inventory regression |
| Spawned descendants survive MCP restart | Native process-group integration tests and bounded hard cleanup |
| Provider claims capability without correct results | Mapbook's advertised vs verified distinction and gold fixtures |
| New tool increases model overhead without value | Pre-registered agent A/B and explicit STOP gate |
| CLI diagnostics not complete when process quiet | Bounded invocation+exit, truthful requested/analyzed scope |
| Main worktree dirty/active sessions | Isolated branch, no direct master edits, guarded release separately |
