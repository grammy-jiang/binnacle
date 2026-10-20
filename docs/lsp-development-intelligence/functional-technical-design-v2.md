# Development Intelligence: functional and technical design V2

**Status:** design draft only; no implementation authorization implied. **Date:** 2026-10-20.
**Source:** Binnacle `origin/master` `ce943ced`, [architecture review](current-architecture-review-2026-10-20.md) and [provider mapbook](capability-mapbook-v2.md).

## 1. Product problem and boundary

An AI agent currently uses exact `search_text`, `list_files` and `read_file` to orient itself. It often needs more calls to find a symbol's real definition, cross-file usages, interfaces and type, and can follow the wrong similarly named symbol. Development Intelligence should resolve **a concrete already-located symbol** without replacing exact search or claiming natural-language retrieval.

Candidate agent-visible intents:

1. `inspect_symbol`: resolve a concrete source symbol and return bounded, provenance-backed definition/reference/type evidence.
2. `check_code`: analyze actual file/project scope and return truthful, normalized diagnostics. Separate optional product decision.

Not goals: IDE cursor state, unsaved buffers, GUI/editor integration, semantic replacement for `search_text`, automatic refactors/edits, auto-installation, project builds, public raw LSP methods, central control of multiple Binnacle hosts or guaranteed cross-project resolution.

## 2. Platform and architecture decisions

Binnacle uses one MCP process per host, native FastMCP 4.1.0 / MCP 2.3.0 stack, focused Files/Search/Commands children, OS-independent composition in `application.py` and narrow host adapters.

Proposed modules (exact files not frozen):

| Component | Owns | Explicitly must NOT own |
| --- | --- | --- |
| `features/development_intelligence/domain` | Result types, status/provenance, limits, target identity | FastMCP/ASGI or OS process APIs |
| `.../workspace` | Authorized root, deterministic workspace discovery, disk snapshot/version/position conversion | Broad silent filesystem access or editor buffers |
| `.../profiles` | Audited executable identity, argv/env/allowed methods, trust, settings fingerprint | Install/download or arbitrary project script execution |
| `.../lsp_protocol` | Bounded Content-Length framing, JSON-RPC dispatch, notifications, capability map and server-request responses | MCP result schemas |
| `.../lsp_manager` | Provider registry, single-flight startup, request concurrency, idle eviction, cooldown and cleanup | Durable `run_command` jobs |
| `.../analyzers` | One-shot audited CLI invocation, structured diagnostics parsing, bounded output and completion | Long-running LSP sessions |
| `.../semantic` | Compose definition/declaration/references/hover into normalized agent evidence | Provider-specific wire protocol |
| `platform/contracts` + `platform/{linux,darwin}` as required | Native spawn/kill/process-tree or filesystem-enforcement mechanisms | Product intent or MCP tool contracts |
| `application.create_application` | Dependency injection, FastMCP lifespan, optional future focused child registration | JSON-RPC, provider decision logic |
| `server.create_server` | Production configuration and host composition | Provider subprocess startup at import |
| `mcp` | Existing logging, visibility, order, identity, admission | New hidden semantic routing |

Minimal dependency direction: public MCP adapter -> semantic/analyzer service -> provider manager/protocol -> injected platform process/access contracts. A provider never imports an MCP tool, `server` module or durable command storage.

### Proposed manager ownership

The FastMCP application lifespan owns a **private manager**. Entering lifespan allocates only inert data structures; it does not locate/download/start a provider. The first *explicit private semantic/analyzer request* may invoke the audited configured profile, with one start per (canonical workspace, provider/profile fingerprint, service generation). A ready instance is reused across MCP turns while the process stays alive.

Shutdown stops new requests, bounds active request draining, sends LSP `shutdown` then `exit`, waits briefly, escalates termination to the entire owned process group and closes readers/pipes. A manager-wide closing state is distinct from per-provider readiness. Source reloads/redeploys must leave no orphaned children or outstanding responses.

Native differences are handled below composition. The job owner and its durable spool are deliberately *not* involved. Process-tree accounting and reliable descendant cleanup require Linux and Darwin test evidence, especially for subprocesses that fork/launch new sessions.

## 3. Configuration and trust policy

Default is **disabled**, with zero new public tools, zero provider subprocesses and no observable changes in existing tools. Exact TOML keys remain provisional until reviewed against current `config.py`:

- enable Development Intelligence globally; turn off audited discovery separately;
- configure per-provider enable/disable, command source, explicit trusted override and pinned argv/env;
- define allowed languages and workspace roots, maximum concurrent resident instances, resource ceilings, request deadlines and idle eviction;
- keep safety profile and READ eligibility separate from protocol feature flags;
- disallow unexpected config near-misses instead of silently using unsafe defaults.

Resolution priority: explicit validated trusted configuration -> audited *service PATH* executable -> unavailable. Never search/execute arbitrary repository `.venv`, `node_modules/.bin`, shell aliases, editor settings, `package.json` scripts or commands from provider output. Do not auto-download executable packages, npm typings or workspace toolchains.

There are two distinct security gates:

1. **Host execution safety:** can the provider perform untrusted process, network, workspace-write or cache activities under this exact profile?
2. **Data access authority:** what paths may an agent request, what workspace trees can the provider itself scan, and what returned file URIs can Binnacle reveal?

Applying Binnacle file path checks solely to the incoming `path` does **not** confine a provider's own file-system activity. READ eligibility needs OS-effective isolation or explicitly audited behavior plus fail-closed profile policy. Never assert a sandbox that has not been demonstrated.

Profiles are classified `audited_read_eligible`, `explicit_trust_only`, `benchmark_only`, `not_audited`. New profiles start as `not_audited`; only a passed side-effect audit may promote one. Project configuration is untrusted input. Refuse server-to-client `workspace/applyEdit`; do not send client-to-server `workspace/executeCommand` or automatic edits in a READ flow.

## 4. Workspace identity and authoritative source

A private request identifies an allowed source file path; the workspace root is deterministic:

1. Git worktree root (including linked worktrees whose `.git` is a file) **if** within allowed roots;
2. provider-specific marker root for supported non-Git sources;
3. the narrow file parent when profile explicitly permits.

Never widen beyond Binnacle's permitted roots automatically. Check symlink traversal and TOCTOU before reading, before provider sync and before returning source paths. Provider-generated definition/reference URIs require **separate authorization and normalization**. Paths outside scope are refused or shown only as a redacted count/status, never silently opened.

Disk content is authoritative. On first target use, read/capture authorized content, hash it and send `didOpen`; on subsequent changes send ordered versioned `didChange` (full sync first), `didClose` on eviction. Before a position-sensitive request, reconcile the current disk version. After a response, if the target changed during processing, retry under a bounded policy or return `stale`—never label the answer fresh.

Input positions must be translated using negotiated provider encoding; user-facing line is 1-based while LSP line is 0-based. Account for UTF-8 bytes, UTF-16 code units, non-ASCII and repeated same-line symbols. Do not let a model-supplied column silently select an arbitrary homonym.

## 5. Protocol and process contract

Implement a narrow stdio JSON-RPC LSP 3.18-compatible client without assuming all providers implement 3.18:

- bounded header/body and byte-accurate Content-Length framing; detect malformed, oversized, truncated, duplicated/unknown ID frames;
- exactly one reader/dispatcher per process; serialized stdin writes; independent inflight request futures, unique request IDs and cancellation;
- `initialize` / `initialized`; normalize advertised capabilities, selected positionEncoding and later dynamic registrations, without confusing `READY` with project indexing finished;
- handle push notifications/progress, known safe server-to-client queries with static answers and explicit errors for unknown/unsafe server requests;
- reject `workspace/applyEdit`; no implicit `workspace/executeCommand` or toolchain execution;
- support `Location`, `LocationLink`, null/multiple result shapes and provider-specific partial/error outcomes;
- bound deadlines, output size, reference/result count, exception payload and protocol logs (redacted by default);
- on crash/EOF/hang, fail pending calls exactly once, collect cause, close descendants, enter cooldown, and allow a later *safe* lazy restart.

Proposed provider state: `ABSENT -> STARTING -> READY`; failures go to `COOLDOWN`; configured disallow to `DISABLED`. Eviction returns to `ABSENT`. Project indexing/settling is an observation attached to requests, **not** a parallel durable COLD/WARM lifecycle state. Registration is single-flight per provider/workspace/profile identity.

No fixed timeout, RSS budget or eviction interval is frozen from tiny fixture measurements. Tune values from correctness-qualified p50/p95/p99 and actual host/service resource pressure. A baseline tool call never blocks on a cold provider and never becomes dependent on LSP.

## 6. Candidate private semantic API

A rough internal call (not a public MCP schema yet):

- request: authorized path, 1-based line, `symbol_text` **or** position-based anchor, optional bounded reference scope;
- result: status, exact requested location and synchronized document hash, provider/version/capability proof, definition/declaration/implementation/type locations, hover summary, bounded references, count/truncation and explicit exclusions.

Anchor alternatives: `path+line+symbol_text` is closer to current `search_text` results; `path+line+column` is closer to native LSP and avoids name collisions only when column is correct. Compare **agent argument correctness** on an annotated corpus before freezing schema.

Results must be truthful:

- `ok`: method executed with an authorized, fresh result for claimed scope (not evidence all project references were found);
- `partial`: provider unavailable for a sub-capability, indexing still incomplete, response budget/truncation or data scope limited;
- `ambiguous`: several candidate tokens/definitions and no defensible unique selection;
- `unavailable`: profile absent/disallowed/unsupported method;
- `stale`: file changed between sync and response;
- `timeout` / `provider_error`: explicit failure, no invented empty result;
- `unsafe_profile`: provider fails execution/trust policy.

Diagnostics have an independent scope model: `requested_scope`, `analyzed_scope`, used/skipped providers and reasons, severity/source/code/message/range, count/truncation and `ok/partial/unavailable`. **Zero diagnostics is not global code correctness**. Never label it `clean` without scope.

Returned hover/signature Markdown is untrusted text; strip or safely render links/commands and bound bytes/token counts. Do not expose absolute off-root paths, secrets or raw provider telemetry.

## 7. Analyzer/diagnostics runtime

LSP push diagnostics and explicit one-shot diagnostics are different completion models. A quiet push stream is not proof that a full workspace was checked. For early Python diagnostics, evaluate audited `pyright --outputjson` and `ruff check --output-format json --no-cache` under a bounded, non-fixing, process-tree-owned invocation.

Analyzer manager:

- verifies allowed root and trusted executable;
- runs with explicit argv, not shell; redirect/cache-proof all writes;
- captures bounded JSON, proper exit code and completion evidence;
- distinguishes `unavailable`, analyzer failure, incomplete coverage and findings;
- cleans up process groups/children on deadline or cancellation;
- never executes project-configured plugins or build commands without separately approved trust.

Do not fold `check_code` into `inspect_symbol`; they are independently benchmarked products with distinct security footprints.

## 8. End-to-end request and exception semantics

| Step / failure | Required action | Agent-visible result |
| --- | --- | --- |
| Disabled/not installed | Skip discovery/spawn, leave baseline tools untouched | `unavailable` with provider reason |
| Invalid/off-root input | Reject **before** provider request; no filesystem info leak | sanitized `invalid_scope`/refusal |
| Missing capability | Skip that method only, attempt audited fallback if applicable | `partial` with capability provenance |
| Concurrent cold requests | Registry single-flight, independent response futures | bounded success/failure; no duplicate process |
| Index still settling | Bounded wait only for explicit semantic operation; do not claim complete result | `partial`/`timeout` as appropriate |
| Target changed on disk | ordered re-sync, max one bounded retry where safe | fresh result or `stale` |
| Provider hangs/crashes | fail pending once, attempt cleanup, cooldown | `timeout`/`provider_error` |
| Malformed/oversized RPC | strict parse refusal and process policy, no raw dump | `provider_error` with stable reason |
| Untrusted server request | answer/refuse safely; never execute | optional `partial` or provider refusal |
| External definition/URI | recheck result authorization; redact/drop off-root target | `partial` + exclusion count |
| Analyzer leaves files/network/processes | fail safety gate; profile ineligible for READ | `unsafe_profile` |
| Service reload/cancellation | owner closes every registered instance, all inflight futures complete | no orphan/restart storm |

Existing file/search/command tools never implicitly call this subsystem, so any LSP-specific failure cannot turn a successful baseline tool request into a failure.

## 9. Measurement, telemetry and product acceptance

Separate five quantities:

1. semantic correctness, recall for bounded known corpora, wrong-definition/ambiguity rate;
2. standalone provider response time/cold settling/resource tree;
3. incremental Binnacle lookup/sync/protocol/normalization/serialization overhead;
4. whole agent workflow: calls, steps, retries, tokens, wall time and final task correctness;
5. operational side effects: workspace writes, hidden toolchain execution, child leaks, network access and READ policy.

A/B uses the same real tasks and model settings, controlled ordering and temporary Binnacle app, with identical permissions and token measurement. Baseline arm = current six-tool search/read workflow; experimental arm = same workflow plus private symbol API only. Record confidence/variance and failure cases. A latency win with worse correctness is a **NO-GO**.

Operational telemetry is sparse and redacted. Record profile ID/hash, workspace hash, phase timing, status, reference counts, side-effect verdict and process accounting. Never log full source or protocol frames by default.

## 10. Release and compatibility

Before any production public registration:

- meet architecture checks, import inventory drift, strict per-module sizing, coverage targets and Python matrix;
- run `test_tool_surface.py`, `test_golden_outputs.py`, `test_surface_tokens.py`, `test_visibility.py`, macOS-native parity and live temporary-server tests;
- verify side effects and process ownership on real Linux/Darwin hosts;
- obtain explicit private experiment GO and independent public API GO;
- if public, deliberately update visibility profiles, order, schemas/hashes and standing token budget, with a documented explanation;
- stage an isolated rollout with default-off profile, verified rollback and no production restart during initial docs/fixture phases.

Do not merge a worktree just because isolated unit tests pass; CI/production acceptance are separate gates.

## 11. Decisions not yet frozen

- schema anchor and exact public API naming;
- in-house narrow LSP client vs third-party client after protocol tests;
- exact trusted executable/sandbox policy for Linux and macOS;
- provider max instances, memory/time budgets, idle TTL and network limitations;
- supported Python version/config environment and analyzer completeness;
- broad matrix expansion priority after measured usage;
- whether a seventh or eighth tool justifies token/visibility cost.

The V2 [implementation roadmap](implementation-plan.md) assigns evidence tasks to resolve these rather than guessing answers in design.
