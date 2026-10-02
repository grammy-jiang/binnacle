# FastMCP-native alignment — G2 implementation design — 2026-10-03

Status: **ready; local design review complete; implementation has not started**.

This is the execution design for Group 2 only. The implementation master is
`docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`. G0 and G1
are done. This document does not authorize implementation, integration, or deployment.

## 1. Baseline and objective

The behavioral baseline is deployed G1 code
`27254767a53a9d8b024b009a5e4c7981b479842f`. The design worktree starts at
`e86ff81db99f989c48275379d203fdc7f1565448`, which changes documentation only
relative to that code checkpoint. The separate G1 review record `096f37a` is
additional evidence, not an implementation input to replay.

The writable design worktree is
`/home/grammy-jiang/Projects/binnacle-g2-native-alignment-design`, on
`design/g2-fastmcp-native-alignment-2026-10-03`. Production and all other
worktrees remain read-only for this task. User-owned production documents stay put.

G2 has two behavior-preserving changes:

1. Delegate component visibility marking, list filtering, and lookup filtering to
   FastMCP. Retain Binnacle's client-name policy, identity resolution, and exact
   existing denied-call error contract.
2. Move Files, Search, and Commands adapter settings from import-time globals to
   ordinary construction arguments, one domain at a time.

Use FastMCP `Depends` only for a real request dependency and lifespan only for a
resource with startup/shutdown ownership. The inspected G2 changes need neither
in production: settings are construction inputs, identity is middleware state,
and existing durable-job resources belong to G3. Native dependency/lifespan
characterization tests make that boundary explicit. Adding a mechanism merely
to demonstrate its API is not a G2 objective.

### 1.1 Governing inputs

Read `AGENTS.md`, `DEVELOPMENT.md`, `docs/testing.md`, and
`docs/quality-gates.md` before implementation. The architectural inputs are:

- `docs/fastmcp-native-architecture-investigation-2026-10-02.md`, especially
  sections 9, 11, and 12;
- `docs/platform-neutral-architecture-design-2026-10-02.md`, especially
  sections 3, 5.2, and 6;
- `docs/fastmcp-native-refactor-high-level-plan-2026-10-02.md`, steps 7 and 8;
- the master plan and the final G1 composition design.

Some architectural inputs remain untracked in production. Read those files
without moving or staging them. The high-level plan explicitly permits minimal
identity/policy glue and directs static dependencies into ordinary factories.

### 1.2 Fixed exclusions

Do not change FastMCP 4.0.10, MCP 2.1.1, MCP-types 2.1.1, dependencies, or
`uv.lock`. Do not add Tasks, extensions, custom Providers, a Provider wrapper,
a router/registry, Feature, ServerBuilder, RuntimeContext, service locator, or
custom lifecycle manager. Do not add a duplicate startup/lifespan guard.

Do not redesign `jobs.py`, `job_owner.py`, the stable manager, job RPC, process
execution, resource accounting, `/proc`, cgroups, systemd/journal, operational
paths, diagnostics, watchdog/tunnel, or macOS support. Those are G3-G5. Do not
move packages, create a CommandService, rename tools, or redesign tool algorithms.

The existing `identity.py` precedence/LRU and `callctx.py` ContextVars stay
unchanged. G2 changes `logging_middleware.py` only to accept tokenizer settings
at construction. Root/child middleware order, lifecycle ownership, authentication,
deployment entrypoints, and instruction text remain unchanged.

## 2. Current code and ownership

### 2.1 Root and focused children

`server.create_server()` builds a fresh authenticated root with
`on_duplicate="error"`, then mounts Files, Search, and Commands without prefixes.
Each child also has local `on_duplicate="error"`. The root LocalProvider is
empty; raw aggregation contains exactly eight tools once each. Cross-provider
duplicates retain FastMCP warning/precedence behavior and remain a test failure
through the raw `Counter` ownership contract, not a runtime validator.

The `PublicToolOrder` Transform restores this exact order:

```text
read_file, list_files, search_text, edit_file, write_file,
run_command, job_status, stop_job
```

It remains ordering-only. Do not combine visibility with it or change its rank
table, identity preservation, unknown-name stability, or duplicate preservation.

Bootstrap remains `mcp = create_server()`, one `log_effective_config()` call,
then `app = mcp.http_app()`. Preserve `binnacle.server:app`, `server.mcp`,
`server.app`, missing/empty-token import failures, and `__main__` behavior.

### 2.2 Current visibility is a client presentation policy

`ClientToolVisibility` stores an insertion-ordered prefix-to-frozenset mapping.
The first matching prefix wins. A matching empty allowlist hides every tool.
Unknown names in an allowlist do not create tools. New tools remain hidden from
restricted clients until explicitly allowed. An absent/unmatched client sees all
tools. Never replace the first-match rule with longest-prefix matching.

`ClientIdentity.resolve()` first reads modern discovery metadata, then legacy
session client information, then remembered session identity. It remembers at
most 256 sessions per root. Modern metadata is only recognized where the current
message shape exposes `message.params.meta`; arbitrary `_meta` on another RPC
must not silently become a new identity source in G2. Discovery still resolves
identity even if the next request carries no metadata.

Current listing middleware filters names after downstream listing. Current call
middleware denies before lookup, argument validation, and tool execution:

```text
Tool 'edit_file' is not available to this client.
```

It raises `fastmcp.exceptions.ToolError`, including for a nonexistent disallowed
name. Retain that class, exact text, timing relative to validation, and logging.
Unrestricted unknown-tool behavior remains FastMCP's current behavior. Client
names are not an authentication principal. Bearer verification remains separate.

### 2.3 Settings and process-state inventory

`get_settings()` is an LRU-cached `Settings` loader. Precedence is explicit
initialization, environment, TOML, then defaults. Environment uses `BINNACLE_`
and nested `__`; config-file selection and removed-setting warnings are stable.
Pydantic settings models are mutable. Passing a caller's model by reference would
allow schema/runtime drift after registration, so factories must copy inputs.

| Location | Current capture | G2 target owner |
| --- | --- | --- |
| `paths.py` | `DEFAULT_ROOT`, `ALLOWED_ROOTS` used by resolution and nearby hints | Explicit copied `RootsSettings` for both helpers; lazy fallback for direct calls |
| `tools/read_file.py` | Four read limits and interpolated `DESCRIPTION` | One read settings snapshot used by description and implementation |
| `tools/list_files.py` | Default/cap, timeout, `RG_BIN` | List settings plus binary captured by registration |
| `tools/edit_file.py` | Snippet context limit | Edit settings captured by registration |
| `tools/write_file.py` | Shared global path policy | Explicit roots only |
| `tools/search_text.py` | Search model, limits, execution mode, contexts, binary | Search model, roots, and binary supplied through existing helper seams |
| `search_text_register.py` | Already accepts implementation/default/cap | Keep that ordinary callable seam and its schema text |
| `tools/run_command.py` | Run policy and wait defaults/cap | Run settings and roots captured by registration |
| `tools/job_status.py` | Quiet/history/preview settings and wait cap | Four scalar construction inputs |
| `tools/stop_job.py` | Existing job owner/store calls | Unchanged |
| `ToolLoggingMiddleware` | Reads tokenizer settings in constructor | Explicit optional tokenizer settings argument, copied at construction |
| `server.py` | Mixed cached settings and bootstrap token path | One domain-settings snapshot per factory; preserve token/bootstrap compatibility |
| `jobs.py`, manager, process modules | Store, owner, socket, output cap, warmup, locks/reapers | Unchanged process/runtime ownership; G3 |
| CLI/setup/service/doctor modules | Host configuration/defaults | Unchanged; G4/G5 |

This is not full multi-tenant server isolation. Two roots can have independent
adapter policy and file/search settings. Commands still share the existing job
backend, output clip ceiling, warmup, owner, socket, and durable store. No G2
factory argument pretends to select a second backend. A differently configured
manager process is not reconfigured by constructing a child server.

## 3. Pinned FastMCP evidence

The design inspected installed FastMCP/FastMCP-slim **4.0.10** and MCP/MCP-types
**2.1.1** on Python **3.13.5**, arm64. Version-specific findings come from the
installed source and local probes, not from an assumption that current web docs
describe the pinned release exactly.

Source locations relative to the installed `fastmcp/` package:

- `server/server.py`: `list_tools`, `get_tool`, `call_tool`, middleware and mounts;
- `server/providers/aggregate.py`, `providers/fastmcp_provider.py`, and
  `providers/local_provider/`: aggregation, delegation, local conflicts;
- `server/transforms/__init__.py` and `transforms/visibility.py`;
- `server/context.py`, `server/dependencies.py`, `dependencies.py`, and
  `server/lifespan.py`.

Official reference links are
[visibility](https://gofastmcp.com/servers/visibility),
[custom Transforms](https://gofastmcp.com/servers/transforms/transforms),
[dependency injection](https://gofastmcp.com/servers/dependency-injection),
[Context](https://gofastmcp.com/servers/context), and
[lifespan](https://gofastmcp.com/servers/lifespan).
They identify the native extension points. The following pinned observations
control implementation when the current documentation differs.

### 3.1 Visibility, request state, and notifications

`Visibility` is a native Transform. It marks copied components; FastMCP's server
then applies session transforms and removes disabled components from listing and
lookup. Use its public `list_tools` and `get_tool` hooks. Do not write its private
metadata markers, call `_mark_component`, or read/write `_visibility_rules` in
production. The design probe reads that private key only as SDK characterization.

`Context.enable_components` / `disable_components` append session rules and emit
list-change notifications. Two identical disable calls produced two stored rules
and two `ToolListChangedNotification` messages on a legacy client. Native denial
was `Unknown tool: 'hidden'`, not Binnacle's existing policy error. Repeatedly
resetting/rebuilding session visibility would add notifications and could erase
other rules. It is not an equivalent replacement for current request policy.

In 4.0.10, `ctx.set_state(key, value, serializable=False)` is request-scoped and
shared through nested mounted-server contexts. The default serializable state
uses the current server's session store. It persisted across two legacy requests
in the probe, but not across two modern HTTP-style request identities. A child's
session store did not read the parent's persistent entry; it did read the
parent's request-scoped entry. Always specify `serializable=False` for the policy
bridge. Current online Context prose must not override this measured distinction.

An empty `names=set()` passed directly to `Visibility` matches no names. Some
session helper paths normalize empty sets to `None`. Use the native Transform
directly and test an empty allowlist; do not infer equivalence between these APIs.
`match_all=True` bypasses selectors, so do not use it with an assumed type filter.

### 3.2 Dependencies and lifespans

A mounted tool's `CurrentContext()` resolves to its child server and the child's
lifespan result. It is not an inherited root dependency bag. Native root/child
lifespans enter root first and exit child first. Existing G1 lifecycle tests remain
authoritative, including startup/teardown failure behavior.

A synthetic synchronous child tool with two `Depends` on one async context-manager
factory received the same object once per invocation. Cleanup ran on success and
tool failure. Injected parameters were absent from the input schema; supplying
one from the wire failed strict validation. These findings justify using native
DI when a later component actually needs a request resource. They do not justify
moving current `callctx` telemetry or immutable configuration into `Depends`.

No Tasks extra is required for `Depends`. Do not add one. No G2-owned resource
needs shutdown. Tokenizer preparation remains ordinary constructor work; job
reapers and the manager must not be tied to MCP client disconnect/lifespan exit.

### 3.3 Completed design characterization

Evidence is retained outside Git at:

```text
/home/grammy-jiang/.local/state/binnacle/
  g2-design-20261002T165110Z-23s_xntn/
```

| Evidence | Result |
| --- | --- |
| `doctor.json`, worktree inventory | Design checkout clean; locked environment available |
| `baseline-gates.json`, `baseline-focused.log` | 158 existing focused tests passed, seed 12345 |
| Architecture / Import Linter / strict size logs | All exit 0 |
| `probe_native.py`, `probe-native.json` | Four-profile exact wire equality; eight raw names once each; identical denied/unknown restricted errors; native state/DI/lifespan observations |
| `probe_visibility_edges.py`, `probe-edges.json` | Empty and overlapping-prefix policies; first call before explicit listing; unknown future tool; repeated lists; concurrent modern/legacy clients; no visibility notifications |
| `probe_http_native.py`, `probe-http.json` | Authenticated native HTTP clients concurrently preserved all four profiles, instructions, schemas, and restricted denial text |
| `probe_http_no_cache.py`, `probe-http-no-cache.json` | The same authenticated four-profile comparison passed with client response caching explicitly disabled |
| `probe_roots_contract.py`, `probe-roots-contract.json` | Existing non-default-root metadata/default behavior characterized; scoped hint prototype excludes a sibling outside the injected roots and preserves an allowed hint |

The scratch baseline/candidate wire JSON files are byte-identical with SHA256
`b215e6ea7dff36ca7785e498ccb8725bce4331394c4b91f6dbc8d075ac56d5c3`.
Their framing differs from G1's retained wire dump, so this is paired design
evidence, not a replacement golden hash. The existing normalized hash pins and
G1 full-wire comparison remain authoritative.

An exploratory HTTP `_meta` override on `tools/list` did not override the legacy
identity in either implementation. That is a characterization of current message
shape, not proof of modern discovery. The separate native HTTP-client probe did
exercise modern discovery and legacy initialization. Do not promote malformed or
unsupported metadata into a new identity channel to make a test pass.

These probes are feasibility evidence, not a finished implementation test suite.
G2.1 must turn the relevant cases into repository tests before switching behavior.

## 4. Target visibility design

### 4.1 Keep one policy source and delegate component mechanics

Keep `ClientToolVisibility` at its existing root middleware position. Its remaining
responsibilities are prefix policy, use of the shared `ClientIdentity`, publishing
the request's allowlist, and the current denied-call error. Remove its manual
list comprehension/filter when the native path activates.

Add `ClientToolVisibilityTransform(Transform)` in the same `visibility.py` module.
It is a small adapter from a request allowlist to native `Visibility`; it is not
a Provider or independent filtering engine. It overrides only `list_tools` and
`get_tool`. Add it to the root after `PublicToolOrder`. Children remain unchanged.

Protocol request flow:

1. Existing identity resolution selects `None` for unrestricted or a frozenset
   for a restricted allowlist. Distinguish `None` from an empty frozenset.
2. Middleware writes that value under one Binnacle-owned request-state key, such
   as `binnacle.client_tool_allowlist`, using `serializable=False`.
3. Root listing aggregates the native children, runs `PublicToolOrder`, then
   applies the new Transform. For a restricted list, delegate first to
   `Visibility(False, components={"tool"}).list_tools(tools)`, then to
   `Visibility(True, names=set(allowed), components={"tool"}).list_tools(...)`.
   For unrestricted listing return the supplied sequence unchanged.
4. Root native `list_tools` performs enabled-component filtering. Binnacle neither
   removes elements itself nor writes native metadata. Resources/prompts are
   untouched. Native serialization keeps private visibility marks off the wire.
5. For `get_tool`, delegate to
   `Visibility(name in allowed, components={"tool"}).get_tool(...)` when
   restricted; otherwise call the supplied `call_next` unchanged. Pass the name
   and keyword-only `version` through. FastMCP owns lookup/filtering/fallback.
6. The existing call-policy check still raises the exact `ToolError` before a
   disallowed call is delegated. This is an error-compatibility bridge. Tests
   must independently prove that native lookup denies a marked tool with this
   check omitted in a synthetic test fixture.

The Transform stores no per-client mutable field, cached component list, provider
index, or session rule. It must not mutate a shared `Visibility` instance between
requests. Use short-lived native rules for the selected request policy.

Publishing must happen for both listing and calls, even if the client never lists
tools first. Discovery still remembers identity. A missing protocol session on
direct Python introspection means unrestricted behavior, preserving raw ownership
tests. Catch only the documented no-current-context/no-session condition at that
boundary. Do not catch arbitrary state-store exceptions or fail open on a real
restricted request whose policy publication failed.

No global `root.enable/disable`, session resets, notification emission, persistent
policy store, new ContextVar, or direct access to SDK private state belongs here.
Do not support arbitrary dynamic nested Binnacle roots as a new G2 feature.

### 4.2 Middleware and identity invariants

Calls retain this sequence:

```text
root DereferenceRefsMiddleware
  -> root RequestLoggingMiddleware
  -> root ToolLoggingMiddleware
  -> root ClientToolVisibility (policy/state/error compatibility)
  -> native root visibility lookup / FastMCPProvider delegation
  -> child DereferenceRefsMiddleware
  -> existing child adapter
```

Keep `add_middleware()` ordering. Do not use the FastMCP constructor's middleware
argument. No Binnacle middleware is added to children. Logging and visibility
continue to share one `ClientIdentity` per root. Identity is never read from
clipped log strings or substituted with the static token's `client_id`.

Listing still runs native child middleware before root aggregation/transforms.
Moving the allowlist selection before native filtering must not change observed
identity semantics. Characterize reconnects, modern discovery with bare followups,
two clients sharing a root, two roots with different policies, and supported
same-connection concurrency. If identity can change during one listing and the
new path differs from current behavior, stop and document that exact case before
activation. Do not silently redefine identity lifetime or expand `identity.py`.

The four pinned profiles remain 8 / 6 / 6 / 8 tools: default, modern ChatGPT,
legacy ChatGPT, unrelated client. Descriptions, annotations, input/output schemas,
instructions, order, and error payloads remain unchanged. No golden rebaseline.

## 5. Target settings and dependency boundaries

### 5.1 Factory contract

Preserve the no-argument `create_server()` and child factory calls. Add optional
keyword-only construction inputs to each child, using existing settings types
and ordinary scalars. Supplied inputs are deep-copied at the factory/registration
boundary; the factory never mutates caller-owned models. The snapshot is private
and treated as immutable. No global change to Pydantic model configuration is
needed.

| Factory | Explicit owned inputs at the final checkpoint |
| --- | --- |
| `create_files_server` | `roots: RootsSettings`, `read_settings: ReadFileSettings`, `list_settings: ListFilesSettings`, `edit_settings: EditFileSettings`, `rg_bin: str` |
| `create_search_server` | `roots: RootsSettings`, `search_settings: SearchTextSettings`, `rg_bin: str` |
| `create_commands_server` | `roots: RootsSettings`, `run_settings: RunCommandSettings`, `quiet_after_s: int`, `listing_history_limit: int`, `listing_command_preview_chars: int` |
| `ToolLoggingMiddleware` | Existing identity plus keyword-only `tokenizer: TokenizerTelemetrySettings` |

Optional inputs default to `None` in the Python API. Resolve only missing inputs
from one cached settings read at construction. Fully supplied domain factories
must not call `get_settings()` for those inputs. Do not use truthiness to replace
valid zero/empty settings. No factory accepts `JobsSettings` as if it could own or
reconfigure the job backend. `job_status` wait cap comes from the same copied
`run_settings.wait_max_s` that builds `run_command`.

At the final root checkpoint, `create_server()` obtains a deep copy of the cached
settings once and supplies the relevant sections/scalars to all three children
and the logging middleware. Do not make an optional whole-`Settings` root API
that suggests ignored process/backend fields would take effect.

Keep `get_settings()` loading, cache behavior, environment/TOML precedence,
removed-key warnings, and CLI defaults unchanged. Keep `TOKEN_FILE` and
`_load_token()` compatibility in this group; token/CLI bootstrap cleanup is not
needed to remove domain captures. No new hot-reload semantics are promised.
Module-level `mcp/app` construction remains intentional bootstrap work.

### 5.2 Files and shared roots

Extend `resolve_path(raw, *, roots: RootsSettings | None = None) -> Path` and
`nearby_hint(parent, *, roots: RootsSettings | None = None) -> str`.
Explicit roots select both the relative base and allowed roots. The hint helper
must use the same allowed roots before enumerating the parent directory. The
fallback reads cached settings at call time for existing direct callers. Remove
`DEFAULT_ROOT` and `ALLOWED_ROOTS` captures after their test consumers migrate.
Do not alter sanitization, expansion, resolution, symlink handling, allowed-root
checks, hints, error codes, or glob code. The two prerequisite glob fixes remain
separate historical commits and their differential property test stays intact.

Each Files registration captures a roots/settings snapshot in its decorated
function closure. Keep public tool parameters byte/JSON-equivalent. Pass settings
as keyword-only arguments to internal implementations/helpers, not new MCP
parameters. Direct implementation calls may retain optional lazy defaults; the
registered server path must always pass explicit captured values.

Pass that same roots snapshot to every `nearby_hint` call in read/list/edit and
Search, including not-found errors. For a nonexistent configured root, its parent
may be globally allowed but outside the injected roots. The hint must then be
empty; it must not enumerate siblings using the global allowlist. Test this case,
in-root hint text parity, missing/empty/large parents, and the absence of global
settings reads on explicit-input error paths. This closes an injection gap; it
does not change the default policy's hint algorithm or text.

Build `read_file` description from the same read snapshot used to enforce its
limits. Do not keep a stale import-time `DESCRIPTION` or limit aliases as the
active implementation. `list_files` schema default/cap and runtime cap use the
same list snapshot. Timeout messages still use that configured timeout.
`edit_file` passes the snippet setting to `_snippet_around`; `write_file` only
needs roots. Static schemas, strings, and clipping markers remain unchanged.

#### 5.2.1 Narrow custom-root compatibility contract

G2 injects the existing path policy; it does not introduce configuration-derived
MCP path defaults or descriptions. The current registration defaults for omitted
`list_files.path`, `search_text.path`, and `run_command.workdir` are literally
`~/Projects`, even when configuration selects another relative-path base.
Descriptions also retain their existing `~/Projects` and `/tmp` wording. G2
preserves this behavior for zero-argument and explicitly configured factories.

Consequently, an explicit relative argument resolves against the captured
`default_root`, and an explicit absolute argument is checked against captured
allowed roots. An omitted argument still resolves the existing literal
`~/Projects`; it does not become the injected root. If that path is excluded by
the captured policy, the existing `path_outside_root` error remains expected.
Constructor injection is not a promise that arbitrary custom roots produce a
self-adapting advertised MCP profile. Root-isolation tests must use explicit
paths when exercising a non-default root.

The fresh-process roots probe confirms this limitation already exists on the
deployed code. Changing root-sensitive defaults/descriptions would be a separate
public compatibility decision. It is deliberately outside this behavior-preserving
G2 design, not an unmentioned implementation task or permission to update hashes.
Tests must pin omitted, explicit relative, and explicit absolute arguments plus
the actual metadata for both standard and non-default roots. No new validation
guard, compatibility-mode flag, or metadata-rendering framework is required.

### 5.3 Search

Thread `SearchTextSettings`, roots, and `rg_bin` through `search_text_impl` and
the existing helper wrappers in `tools/search_text.py`. Resolve default settings
once at the outer direct-call fallback, then explicitly pass them downstream.
Do not repeatedly load settings inside scan/collection/budget loops.
Pass the captured roots to the not-found `nearby_hint` call as well.

The affected helper seams are `_run_rg`, `_collect`, `_attach_context`,
`_scan_exact`, `_enforce_result_budget_rich`, `_enforce_result_budget`,
`_fit_budget_with_metrics`, and `_search_exact_impl`. Pass existing callback
arguments using small closures or `functools.partial` where necessary. Helpers
already accept binary, timeout, line clipping, and budget values. Do not redesign
streaming/materialized search, adaptive ranking, ingestion, metrics, or budgets.

Keep `register_search_text(mcp, impl, output_schema=..., max_results_default=...,
max_results_cap=...)` and its public schema text. Supply a settings-bound ordinary
callable. The callable's MCP-facing argument contract is unchanged. Keep the
existing subprocess/test lookup seams; configuration injection must not mask
patches that verify real telemetry, errors, or streaming equivalence.

### 5.4 Commands adapter settings only

`run_command.register` captures roots and a copied `RunCommandSettings`. Its
schema and implementation share wait default/cap, auto-background patterns,
evidence retention, and evidence directory. Thread those inputs through
`run_command_impl`; keep `DispatchPlan`, job owner calls, telemetry fields,
explicit-argument detection, output shaping, and result schemas unchanged.

`job_status.register` captures `quiet_after_s`, `listing_history_limit`,
`listing_command_preview_chars`, and the shared run wait cap. Thread scalars
through `_command_preview`, `_listing_rows`, `_listing_result`, and
`job_status_impl` only where used. Keep wait timing, cursor semantics, process
inspection, exception logging, and job reads unchanged. `stop_job` is untouched.

`jobs.RUN_MAX_OUTPUT_CHARS`, `WARMUP_S`, `OWNER_MODE`, socket/store paths, locks,
and lifecycle stay process-owned. The manager's wait validation also remains
unchanged. Constructor overrides test adapter behavior against a compatible
embedded/fake backend; they do not support changing a live manager's wait policy.
Normal deployment still supplies matching process configuration to the existing
services. Moving backend policy or making multiple independent managers is G3.

### 5.5 Injection and lifetime acceptance table

| Value/resource | Lifetime | Mechanism in G2 | Explicit non-owner |
| --- | --- | --- | --- |
| Domain limits, roots, binary | Factory/registration | Copied arguments captured by ordinary closures | Request state / Depends |
| Token verifier and token path | Existing root/bootstrap | Existing auth and loader | Visibility policy |
| Client identity cache | Root instance | Existing shared `ClientIdentity` | Auth principal / global cache |
| Selected client allowlist | One protocol request | Native Context request state | Persistent session rules |
| Component visibility flags/filtering | Native component lookup/list | Native `Visibility` and FastMCP | Binnacle list filter |
| Request telemetry | One tool call | Existing ContextVars and logging middleware | New DI/context framework |
| TokenCounter | Root logging middleware | Ordinary constructor with copied settings | Lifespan cleanup |
| Durable jobs, reapers, spool, manager | Existing process/service | Unchanged | Root/child MCP lifespan |
| Hypothetical future request resource | Not added in G2 | Native `Depends` when actually required | Global service locator |
| Hypothetical future startup resource | Not added in G2 | Owning native server/provider lifespan | Custom lifecycle manager |

## 6. Atomic implementation sequence

Every step uses the exclusions in section 1.2 and invariants in sections 2, 4,
and 5. Start from a new authorized implementation worktree containing this reviewed
design. Preserve all design/evidence worktrees. Commit a checkpoint only after
its focused gates pass. Each commit must start and serve a complete server.

The test group names below are defined in section 8. Each step's output is an
input to the named downstream step; no placeholder path may be left broken.

### G2.0 — Record the actual implementation baseline

- **Purpose/current:** G1 is deployed; this is still design-only evidence.
- **Input:** reviewed design commit, current authorized base, locked environment.
- **Output/downstream:** external versions, refs/status/inventory, settings fixture,
  and four-profile raw wire archive used by every later parity check.
- **Files/API:** no production edit. Run dev doctor/worktrees, lock check, B+C+A.
- **Tests:** import/bootstrap and four-profile B/C pins must pass before editing.
- **Stop:** unexpected base drift, dirty work owned by another session, failed
  baseline, dependency change, or absent prerequisite history.
- **Rollback/parallel:** no code change; one owner records baseline.
- **Done:** reviewed baseline and exact evidence path recorded; master G2 becomes
  `implementing` only now. G0/G1 stay done.

### G2.1 — Add characterization contracts before migration

- **Purpose/current:** existing tests pin normal profiles but not all edge/scope
  cases in section 3. Add tests that run against the unmodified current policy.
- **Input:** G2.0 archives and scratch probes; installed 4.0.10 implementation.
- **Output/downstream:** V identity/policy/error tests and N native scope tests,
  reused by the visibility switch and settings isolation tests.
- **Files:** existing visibility/identity contracts as needed; new
  `test_visibility_policy.py`, `test_visibility_http.py`, and
  `test_native_dependency_scopes.py` at the locations in section 7.
- **API:** test-only FastMCP/Client, native Visibility, Context, Depends, lifespan.
- **Tests before/after:** B+C+A before; V+N+B+C+A after. No new golden system.
- **Stop:** a real transport/identity case needs a public change or identity
  redesign. Preserve the failing trace and stop before production activation.
- **Rollback/parallel:** revert tests only; independent read-only SDK review can
  run concurrently, shared fixtures have one owner.
- **Done:** deterministic empty/overlap/first-call/error/notification/HTTP and
  lifecycle tests express measured behavior, not assumed documentation behavior.

### G2.2a — Introduce the native visibility adapter unused

- **Purpose/current:** production still uses the original listing middleware.
- **Input:** G2.1 policy matrix and native scope facts.
- **Output/downstream:** tested `ClientToolVisibilityTransform` available for
  atomic activation in G2.2b; current exported root is unchanged.
- **Files:** `visibility.py`; new `tests/unit/core/test_visibility_native.py` and
  relevant V fixtures. Keep the existing middleware filtering active here.
- **API:** Transform hooks delegating to native Visibility; public request state.
- **Tests:** V+N plus unit tests for unrestricted identity, empty set, duplicate
  multiplicity, metadata, unknown names, get/version passthrough, native denial
  without the compatibility guard, and no shared-object mutation. Run B+C+A.
- **Stop:** raw objects are mutated, resources/prompts affected, private SDK
  writes needed, or a schema/description/ordering/error pin changes.
- **Rollback/parallel:** remove unused adapter/test code; root unchanged. One
  owner for visibility module; settings analysis may proceed separately.
- **Done:** native marking/filtering proven on synthetic roots without switching
  public behavior or adding session rules/notifications.

### G2.2b — Activate request policy and remove manual list filtering

- **Purpose/current:** switch one mechanism with a reversible atomic change.
- **Input:** G2.2a adapter, V/N contracts, original wire archive.
- **Output/downstream:** root uses native component visibility with the same
  client policy/error contract; later settings work keeps these tests mandatory.
- **Files:** `visibility.py`, `server.py`, V/C tests, `surface_support.py` prose
  only if needed to describe the new policy mechanism. Hash pins unchanged.
- **API:** root `add_transform` after PublicToolOrder; `Context.set_state` with
  `serializable=False`; same root middleware position and shared identity.
- **Tests:** V+N+B+C+E+A; exact four-profile full wire JSON; direct denied and
  unknown calls; notifications; concurrent HTTP profiles; raw Counter tests.
- **Stop:** timing/identity/error differences, state leakage, unsupported private
  hooks, or any public drift. Do not delete the error bridge to satisfy native
  error expectations.
- **Rollback/parallel:** revert middleware change and root Transform attachment
  together; unused adapter can remain. No parallel root/visibility edits.
- **Done:** no Binnacle component-list filter remains; native lookup denial and
  compatible call errors both have tests. No session rule growth or notifications.

### G2.3 — Make path policy an explicit compatible helper input

- **Purpose/current:** all domains still call global-root `resolve_path`.
- **Input:** RootsSettings model and existing path/error/property contracts.
- **Output/downstream:** explicit roots keywords on both `resolve_path` and
  `nearby_hint`, with lazy fallbacks; consumed by each domain migration. No changed
  path/glob algorithm or configuration-derived MCP metadata.
- **Files:** `paths.py`; path tests in `test_properties.py` and focused new
  construction tests. Replace only tests that patched removed root constants.
- **API:** ordinary optional keyword argument; no FastMCP dependency on paths.
- **Tests:** P+B+C+A; explicit two-root isolation, outside-root/symlink/error cases,
  hint parity and no-global-read tests, nonexistent custom root with a globally
  allowed parent, existing differential glob tests and both prerequisites.
- **Stop:** any glob delta, new path validation semantics, or platform seam needed.
- **Rollback/parallel:** revert the compatible helper change before consumers
  migrate, or revert dependent domain changes first. Single shared-path owner.
- **Done:** neither resolution nor hints capture roots at import; old no-keyword
  calls still work. No `ALLOWED_ROOTS` hint consumer remains after removal.

### G2.4a — Inject Files read/write configuration

- **Purpose/current:** Files child is mounted; read limits and paths are global.
- **Input:** G2.3 helper and read settings/roots construction contract.
- **Output/downstream:** read/write adapters use captured settings; Files factory
  accepts roots/read settings. List/edit continue their compatible default path.
- **Files:** `files_server.py`, `tools/read_file.py`, `tools/write_file.py`, their
  unit tests, new file-settings construction tests.
- **API:** ordinary keyword inputs and registration closures; native decorators
  and LocalProvider stay unchanged. Build description from captured read settings.
- **Tests:** F+P+B+C+A. Compare default wire; test two factories with different
  roots/limits using explicit paths, caller-model mutation, no-global reads on
  success and hint/error paths, read errors,
  byte-preserving write, and description/limit agreement.
- **Stop:** output/schema pin changes or algorithm/tool-body redesign required.
- **Rollback/parallel:** revert factory/adapter wiring together; paths bridge
  remains. Independent Search preparation allowed after G2.3, not root edits.
- **Done:** read/write registered calls do not consult globals for migrated inputs.

### G2.4b — Finish Files list/edit configuration

- **Purpose/current:** read/write explicit; list/edit still use import captures.
- **Input:** accepted G2.4a plus list/edit settings and binary.
- **Output/downstream:** fully configurable Files child used by root in G2.7.
- **Files:** `files_server.py`, `tools/list_files.py`, `tools/edit_file.py`, focused
  Files unit/construction tests. `read_file`/`write_file` only if wiring requires it.
- **API:** keyword settings, same decorators and closures; `_glob_mode` receives
  binary/timeout, `_snippet_around` receives snippet context.
- **Tests:** F+P+B+C+A; include list default/cap schema parity, runtime cap/timeout,
  binary selection, snippet limit, hidden/gitignore behavior, separate factories.
  Pin the section 5.2.1 omitted-path and metadata compatibility behavior; pass
  captured roots through both list/edit not-found hints.
- **Stop:** any need to change glob semantics, registered parameters, or metadata.
- **Rollback/parallel:** revert this checkpoint, preserving G2.4a; one Files owner.
- **Done:** Files has no import-time settings capture; zero-argument factory still
  serves exactly its four pinned tools.

### G2.5a — Thread Search settings through the existing implementation seams

- **Purpose/current:** Search globals feed scan, clipping, adaptive, and telemetry.
- **Input:** G2.3 and existing explicit low-level helper arguments.
- **Output/downstream:** optional keyword settings/roots/binary at the outer
  implementation; one resolved snapshot reaches every helper. G2.5b binds it.
- **Files:** `tools/search_text.py`; affected search unit/telemetry/equivalence tests.
  Do not rewrite the existing low-level search companion modules.
- **API:** ordinary arguments/partial callables, no Depends/Provider/service class.
- **Tests:** S+P+B+C+A; streaming/materialized equivalence, adaptive and result-byte
  budgets, line/context limits, error codes, telemetry keys/timing, default wire.
- **Stop:** a parameter-only change requires algorithm redesign, package split,
  exceeding 500 lines, changing companion APIs broadly, or weakening tests.
- **Rollback/parallel:** revert parameter threading as one checkpoint; Files can
  proceed independently after shared paths settle. Do not edit root concurrently.
- **Done:** direct default callers work; explicit callers load no hidden Search
  settings; config-derived global constants are no longer implementation inputs.

### G2.5b — Bind Search settings at registration and child construction

- **Purpose/current:** explicit implementation exists; bind one stable server policy.
- **Input:** G2.5a implementation and existing `register_search_text` callable seam.
- **Output/downstream:** isolated Search factory consumed by G2.7.
- **Files:** `search_server.py`, `tools/search_text.py`, Search construction tests;
  registration wrapper should need no behavioral change.
- **API:** factory/registration kwargs and a bound callable passed to native tool
  registration. Same public signature, defaults, descriptions, and output schema.
- **Tests:** S+B+C+A; two factories with distinct caps/binaries/roots; mutating the
  supplied model cannot alter registered runtime limits or published schema.
  Use explicit paths for root isolation, pin unchanged omitted-path metadata and
  behavior, and cover scoped not-found hints without global settings reads.
- **Stop:** captured callback bypasses telemetry/monkeypatch tests or wire changes.
- **Rollback/parallel:** revert binding checkpoint; G2.5a default path works. One
  Search owner; no shared root/config edits.
- **Done:** no Search settings read at import; schema and implementation share the
  copied registration settings; exact default parity passes.

### G2.6a — Inject run-command adapter policy

- **Purpose/current:** run adapter captures policy/default/cap at import.
- **Input:** G2.3, existing RunCommandSettings and unchanged backend APIs.
- **Output/downstream:** Commands factory accepts roots/run settings; run adapter
  uses explicit captured policy; job-status migration follows in G2.6b.
- **Files:** `commands_server.py`, `tools/run_command.py`, relevant command tests
  and new Commands settings tests. Backend/job owner/evidence implementations
  remain untouched.
- **API:** ordinary settings kwargs; existing decorators, ContextVars, DispatchPlan.
- **Tests:** J+P+B+C+A; wait defaults/caps, omitted versus explicit arguments,
  auto-background first-prefix behavior, evidence opt-in, output/error telemetry,
  embedded/fake-manager calls and unchanged manager RPC.
  Pin unchanged omitted-workdir metadata/error behavior under non-default roots;
  prove a rejected omitted workdir cannot launch a command.
- **Stop:** multiple backend isolation, CommandService, manager policy rewrite,
  lifespan cleanup, job resource/platform change, or output/telemetry drift.
- **Rollback/parallel:** revert adapter and child wiring together; no durable-store
  migration exists. Commands work only in test spools/sockets. One Commands owner.
- **Done:** run policy is construction-owned; jobs remain process-owned explicitly.

### G2.6b — Inject job-status presentation and wait settings

- **Purpose/current:** run settings explicit; status still captures four constants.
- **Input:** G2.6a run wait cap plus quiet/history/preview scalar inputs.
- **Output/downstream:** final Commands factory contract, ready for G2.7.
- **Files:** `commands_server.py`, `tools/job_status.py`, focused status/Commands
  construction tests. `stop_job.py`, jobs, cursors, and process modules unchanged.
- **API:** scalar keyword arguments; native decorators; current job backend calls.
- **Tests:** J+B+C+A; no-id listing, quiet state, preview lengths, wait bound,
  cursor replay, exit/error telemetry, raw ownership, all job output schemas.
- **Stop:** schema cap differs from run policy, backend globals are silently
  repurposed as instance state, or status logic changes beyond parameter use.
- **Rollback/parallel:** revert this checkpoint; G2.6a still functional. Same
  Commands owner; no concurrent edits to shared command test fixtures.
- **Done:** adapter defaults/caps agree; no Commands adapter import-time settings
  capture remains. Stable job owner, warmup, output ceiling, and spool remain shared.

### G2.7 — Supply root snapshots and tokenizer settings explicitly

- **Purpose/current:** all children accept explicit policy; root still calls their
  zero-argument compatibility path and logging loads its own settings.
- **Input:** accepted Files, Search, Commands contracts and copied settings models.
- **Output/downstream:** one per-construction root domain snapshot drives schemas,
  runtime limits, client policy, and tokenizer configuration. G2.8 verifies cleanup.
- **Files:** `server.py`, `logging_middleware.py`, factory/config-warning/logging
  tests and construction-isolation tests. No config-loader or CLI changes.
- **API:** normal arguments to children/ToolLoggingMiddleware; keep no-argument
  `create_server()`, `add_middleware`, existing token loader, mcp/app bootstrap.
- **Tests:** D+B+C+V+E+A; two successive roots with test-supplied cached settings,
  same process backend explicitly; no stale domain limits/schema; fresh identity;
  tokenizer copies; token errors and config log count; ASGI/CLI entrypoints.
- **Stop:** root would need arbitrary backend injection, auth/bootstrap redesign,
  request-time settings lookup for registered tools, or middleware reordering.
- **Rollback/parallel:** revert root/logging wiring as a unit; zero-argument child
  factories still function. Integrator only; no parallel root/config edits.
- **Done:** root constructs domain dependencies explicitly without a new framework
  or an API that falsely promises isolated job runtimes.

### G2.8 — Remove obsolete captures and enforce bounded architecture

- **Purpose/current:** migrated settings are explicit; verify no alternate stale path.
- **Input:** all accepted switches and current tests.
- **Output/downstream:** final file/scope audit and static acceptance tests for G2.9.
- **Files:** only leftover config-derived captures in the listed G2 modules and
  their test consumers; new `test_domain_construction.py` static assertions.
- **API:** none new. Keep optional direct-call/factory compatibility fallbacks;
  remove dead configuration constants, not public MCP behavior.
- **Tests:** D+V+B+C+E+A; fresh-process import checks under two configs and explicit
  inputs; no module reload/cache clearing needed for migrated construction tests.
- **Stop:** AST gate needs a generic dependency registry, an Import Linter waiver,
  or forbidden module edits. Do not expand scope to eliminate all globals.
- **Rollback/parallel:** revert cleanup/test tightening only; previous explicit
  path remains usable. One integrator audits final dependency graph.
- **Done:** no import-time `get_settings()` capture in paths or migrated adapters;
  static constants remain legitimate; known process/bootstrap captures documented.

### G2.9 — Convergence, review, and later integration

- **Purpose/current:** local implementation checkpoints exist; group is not done.
- **Input:** final implementation diff, all focused evidence, original wire archive.
- **Output/downstream:** locally reviewed candidate and explicit CI/deployment
  handoff. Later authorized integration supplies final group-exit evidence.
- **Files:** control/design status and evidence; only justified in-scope fixes.
- **Tests/API:** every gate in section 8.6, fresh ChatGPT read-only implementation
  review, exact diff review against implementation base and deployed code.
- **Stop:** any failed gate, unexplained pin/behavior delta, review blocker, or
  need for excluded scope. Never weaken validation/coverage or repair unrelated
  bugs in the G2 lane; a separate prerequisite requires review and replay.
- **Rollback/parallel:** isolated checkpoint reverts in reverse dependency order;
  no Git resets/cleanup of evidence worktrees. Review can be parallel; integration
  and control state have one owner.
- **Done locally:** clean committed branch; G2 `validating`, awaiting independent
  review/CI/deployment. No push/deploy without authorization. Only later actual
  CI, canonical deploy, live suite/smoke, and real ChatGPT call permit `done`.

## 7. Concrete file-change map

The following map is for future implementation. This design task changes only
this document and the master plan.

| Production file | Permitted change |
| --- | --- |
| `src/binnacle/visibility.py` | Request policy state, native Transform delegation, retained exact error bridge; remove manual list filtering |
| `src/binnacle/server.py` | Attach native visibility adapter; pass copied domain/tokenizer settings; preserve bootstrap/auth/order |
| `src/binnacle/logging_middleware.py` | Optional copied tokenizer constructor input only |
| `src/binnacle/paths.py` | Explicit roots on resolution and hints; remove captures; no glob or metadata changes |
| `src/binnacle/files_server.py` | Domain construction kwargs and registrations |
| `src/binnacle/search_server.py` | Search construction kwargs and registration |
| `src/binnacle/commands_server.py` | Adapter policy kwargs, shared run/status wait cap |
| `src/binnacle/tools/read_file.py` | Captured read/roots inputs and matching description |
| `src/binnacle/tools/list_files.py` | Captured list/roots/binary inputs |
| `src/binnacle/tools/edit_file.py` | Captured edit/roots inputs |
| `src/binnacle/tools/write_file.py` | Captured roots input |
| `src/binnacle/tools/search_text.py` | Parameter threading/bound callable, no search algorithm changes |
| `src/binnacle/tools/run_command.py` | Adapter run policy/roots inputs, no lifecycle changes |
| `src/binnacle/tools/job_status.py` | Status presentation scalars and shared wait cap |

`config.py`, `search_text_register.py`, low-level search companions,
`tools/stop_job.py`, `tool_order.py`, `identity.py`, `callctx.py`, and jobs/process
modules should remain production-unchanged. If a signature-only registration
wrapper adjustment appears necessary, inspect the exact need before expanding
this map; its existing callable seam should suffice.

Expected new tests, each below the repository size limit:

- `tests/contracts/test_visibility_policy.py`: policy/error/prefix behavior;
- `tests/unit/core/test_visibility_native.py`: pure native-delegation mechanics;
- `tests/integration/test_visibility_http.py`: modern/legacy HTTP, state, concurrency;
- `tests/integration/test_native_dependency_scopes.py`: test-only DI/lifespan scopes;
- `tests/unit/core/test_domain_construction.py`: bounded AST/import acceptance;
- `tests/integration/test_files_settings.py`;
- `tests/integration/test_search_settings.py`;
- `tests/integration/test_commands_settings.py`.

Extend existing `test_server_factory.py`, `test_server_composition.py`,
`test_mounted_call_context.py`, Files/Search/Commands unit tests, config-warning
and telemetry tests only for changed construction seams. Existing global-limit
monkeypatch tests must pass explicit settings while retaining their input/output
assertions. Do not convert failures into broad mocks that bypass real tool code.
`surface_support.py` may gain comparison helpers if needed, but no new mutable
golden store and no changes to normalization or expected surface hashes.

## 8. Exact test and architecture strategy

Run focused groups with `uv run pytest -q PATHS --randomly-seed=12345`. These are
focused ordinary pytest runs; use the managed runner for the full suite. Keep
new tests deterministic and use temporary token/config/roots/job spools/sockets.
No live command or production service mutation belongs in local tests.

### 8.1 B, C, E — Existing authoritative compatibility tests

**B** consists of:

```text
tests/contracts/test_dependency_pin.py
tests/contracts/test_protocol.py
tests/contracts/test_tool_surface.py
tests/contracts/test_visibility.py
tests/contracts/test_input_validation.py
tests/contracts/test_job_schemas.py
tests/contracts/test_surface_tokens.py
tests/contracts/test_golden_outputs.py
tests/integration/test_auth_asgi.py
tests/integration/test_http_workflows.py
tests/integration/test_logging.py
```

**C** consists of the actual post-G1 modules:

```text
tests/contracts/test_server_composition.py
tests/integration/test_server_factory.py
tests/integration/test_composition_pipeline.py
tests/integration/test_composition_workflows.py
tests/integration/test_mounted_call_context.py
tests/unit/core/test_tool_order.py
tests/unit/core/test_identity.py
```

Do not replace them with new factory-only tests. They pin exported/fresh roots,
child-local inventories, root-local emptiness, raw multiplicity, negative
cross-provider fixtures, all four local duplicate errors, native middleware and
lifespan scope, errors, and worker ContextVar propagation.

**E** adds `tests/integration/test_cli.py`, `test_setup_units.py`,
`test_packaging_smoke.py`, `tests/unit/core/test_units.py`, and
`tests/integration/test_config_warning_logging.py` to factory/auth/HTTP tests.
Check these tracked paths at implementation baseline; renamed equivalents must
be identified rather than silently dropping entrypoint coverage.

At every activation compare complete `model_dump(mode="json", by_alias=True)`
tool lists and exact instructions for default, modern `openai-mcp(ChatGPT)`,
legacy `openai-mcp`, and unrelated `claude-code`. Compare within the same Python
version and settings fixture. Keep existing normalized cross-version hashes.
Record exact raw list order and multiplicity before wire deduplication, with no
request identity, so native visibility cannot hide an ownership defect.

### 8.2 V and N — Characterization and native visibility acceptance

**V** includes existing identity/visibility tests and the three new policy,
native, and HTTP modules. Use `Client(..., cache=False)` when testing repeated
server requests, state changes, or transport behavior; the modern client enables
response caching by default. Retain ordinary-client coverage as well. Cover:

- missing/malformed identity, modern discovery, bare followup, legacy fallback,
  existing LRU behavior, unrelated clients, and reconnect behavior;
- insertion-order overlap, empty allowlist, unknown allowlisted name, new hidden
  tool, direct call before list, repeated list, disallowed malformed arguments,
  and restricted/unrestricted unknown-tool errors;
- two policies/factories and concurrent modern/legacy clients without leakage;
  supported same-connection cases compared against the characterization fixture;
- zero new list-change notifications, no persistent session-rule writes,
  all resource/prompt operations unchanged;
- native get/list filtering with a synthetic error bridge removed; version and
  `call_next` passthrough, unchanged shared components, duplicate preservation;
- authenticated HTTP four-profile lists/instructions/calls, 401 and session errors,
  exact error class/text and one logging call/result pair;
- direct no-session introspection remains unrestricted; state failure during a
  restricted protocol request is surfaced, never treated as unrestricted.

**N** is `test_native_dependency_scopes.py` plus existing composition pipeline
tests: request-state inheritance, default persistent state versus explicit
request state, child lifespan visibility, Depends per-invocation cache/cleanup,
strict rejection of spoofed dependency arguments, and sync worker execution.
These are test-only mechanisms. Do not inject test lifespans/dependencies into
production merely to satisfy these tests.

### 8.3 P, F, S, J — Domain behavior

**P:** `tests/unit/core/test_properties.py` plus explicit-roots cases in new Files
settings tests. Retain all property-test settings and deterministic glob cases.
Cover `nearby_hint` with the same explicit policy on all four caller error paths;
the parent of a nonexistent root must not disclose out-of-policy siblings.

**F:** `tests/unit/tools/test_read_file.py`, `test_list_files.py`, `test_edit_file.py`,
`test_write_file.py`, and file cases in `test_telemetry_error_codes.py`, plus
`test_files_settings.py` and mounted workflows. Verify custom limits against
both published schema/description and actual results, including errors.

**S:** `tests/unit/tools/test_search_text*.py`,
`tests/unit/core/test_search_text*.py`,
`tests/integration/test_search_text*.py`,
`tests/contracts/test_search_text_surface.py`, plus `test_search_settings.py`.
This covers streaming/materialized parity, adaptive discovery, budget clipping,
timing/log metrics, and configuration-dependent defaults. No search algorithm
change is permitted to make injection easier.

**J:** `tests/integration/test_jobs*.py`,
`tests/integration/test_job_manager*.py`,
`tests/integration/test_run_command*.py`,
`tests/unit/core/test_run_command*.py`,
`tests/contracts/test_job_status_cursor_internal.py`, `test_job_schemas.py`, plus
`test_commands_settings.py` and mounted command workflows. Use the existing
embedded/fake-manager fixtures. Retain durable background/status/cursor/stop,
wait/error telemetry, output shaping, and auto-background evidence assertions.

Shell globs in these focused groups are path selections, not instructions to
invent missing tests. Record the resolved test files with each checkpoint.

### 8.4 D — Construction and import acceptance

Use new domain construction tests and `test_server_factory.py` to establish:

1. Zero-argument root/child factories and direct implementation calls still work.
2. Fully supplied child settings avoid global settings reads for owned inputs.
3. Two factories built after module import use their own roots, limits, binary,
   policies, and schema defaults; later caller-model mutation changes neither.
   Schema defaults here mean existing limit defaults. Path/workdir literals and
   descriptions follow the narrower section 5.2.1 compatibility contract.
4. Module import order, `importlib.reload`, or clearing the config cache is not
   required to choose a migrated child's explicit settings.
5. Root factory snapshots the cached configuration at construction and passes
   it to children/logging; import-time exported singleton remains compatible.
6. Commands tests state clearly which policy is instance-owned and which backend
   is shared. No fake claim of per-root durable-job isolation is accepted.
7. Narrow AST assertions reject module-level calls to `get_settings()` in paths
   and the seven migrated adapters. Check actual initialization expressions,
   including aliases/default arguments; do not ban legitimate runtime fallback
   calls or static schema/annotation constants.
8. No production custom lifespan/duplicate validator, new Provider, Depends-based
   settings locator, SDK-private visibility writes, or package relocation appears.

Do not assert exact implementation formatting or create a framework registry to
drive these checks. Keep static gates restricted to this reviewed file set.

### 8.5 A — Existing architecture and size gates

```bash
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
uv run python scripts/check_module_size.py --strict
```

Keep current contracts: root is not a lower-layer dependency; only focused
factories enter adapter modules; children/adapters remain independent; no reverse
watchdog dependency; no top-level cycles. No Import Linter relaxation is expected.
`pyproject.toml` should remain unchanged. Do not split packages or introduce a
generic configuration/dependency container to solve an import violation.

Every production/script/test module stays at most 500 physical lines. Search and
job-status adapters are already close enough to require attention. Remove obsolete
captures as parameters replace them; do not compress code or move arbitrary chunks
to evade the limit. Stop for design review if minimal threading cannot fit.

### 8.6 Full implementation convergence gates

After all focused steps pass, future G2 implementation must run:

```bash
uv lock --check --offline
uv run python scripts/run_test_suite.py --seed 12345
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
uv run tox run
uv run pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
uv run python scripts/check_module_size.py --strict
```

The managed suite includes the ordinary-process lane. The matrix includes Python
3.10, 3.11, 3.12, 3.13/coverage, and 3.14. Coverage is per module, not an aggregate
substitute: 95 percent core unit branch coverage and 90 percent other full-suite
branch coverage under repository policy. No exceptions or reduced tests.

Inspect complete diffs against the implementation baseline and deployed code.
Confirm dependency/lock equality; exact public wire parity; unchanged protected
modules; no unexpected output/golden edits; clean worktree; separate prerequisite
history. Run a fresh ChatGPT read-only review using the final design, diff, SDK
evidence, and all gate logs. Only then record local validation completion.

Later authorized CI must pass the exact candidate's seven required checks:
Code quality; Tests / Python 3.10, 3.11, 3.12, 3.14; Coverage policy / Python 3.13;
Packaging / Python 3.13. Canonical deployment is
`.venv/bin/python scripts/deploy_smoke.py deploy TARGET`, never direct deployment
branch pushes. Require the live read-only suite, normal post-deploy smoke/doctors,
and a real ChatGPT -> Binnacle read-only call before G2 is `done`.

## 9. Dependencies, parallel work, and rollback

| Checkpoint | Required predecessor |
| --- | --- |
| G2.1 characterization | G2.0 baseline |
| G2.2a unused visibility adapter | G2.1 |
| G2.2b visibility activation | G2.2a |
| G2.3 roots and hint seam | G2.2b |
| G2.4a -> G2.4b Files | G2.3 |
| G2.5a -> G2.5b Search | G2.3 |
| G2.6a -> G2.6b Commands | G2.3 |
| G2.7 root construction | G2.4b, G2.5b, and G2.6b |
| G2.8 cleanup/static gates | G2.7 |
| G2.9 convergence/review | G2.8 |

Visibility activation and shared-path changes are sequential checkpoints. After
G2.3, Files/Search/Commands can be developed in separate isolated worktrees if
authorized, with one owner per domain. Shared fixtures, config models, root,
visibility, logging, quality gates, and control docs have one integrator. The
default implementation order is Files, Search, Commands. Do not start G3/G4 lanes
under this design merely because the master plan permits later parallelism.

Rollback follows dependency order. Unused additions can be removed alone. An
activation and its caller changes revert together. Settings implementation keeps
compatible zero-argument paths so each intermediate commit serves a working
server. Never restore old global registration or mount duplicate tools. Never
revert a path signature before callers that rely on it. No data/store/schema
migration occurs. Later deployment rollback belongs to the canonical deploy flow,
which restores checkout/environment as documented; do not reset production by hand.

## 10. Design completion and implementation entry conditions

The design is ready only after its probe evidence, changed-doc gates, and fresh
read-only review are recorded without unresolved architecture findings. This
does not mean G2 implementation has begun or its full gates have run.

Implementation requires coordinator approval of this design, an explicit
implementation instruction, a fresh isolated worktree from the authorized base,
and G2.0 drift/baseline checks. If FastMCP, deployed code, identity behavior, or
the job backend has changed, review the affected design before using it.

No architecture blocker was found in the completed design probes. The native
visibility adapter preserved current surfaces and errors without changing
identity, auth, or lifecycle ownership. The remaining implementation proof is
the deterministic repository tests and each small configuration activation.

### Design validation record

- Baseline focused tests: 158 passed; seed 12345.
- Architecture checker, Import Linter, strict module size: passed.
- Native visibility/state/DI/lifespan and authenticated HTTP probes: passed.
- Production Python/tests/dependencies/lock/deployment files: no edits in this task.
- Changed-document pre-commit: passed for both design/control documents.
- Fresh ChatGPT read-only design review: **APPROVE, no remaining findings**.
  The [review session](https://chatgpt.com/c/6abfe993-76ec-83ec-84a8-c174ed8e38c4)
  used a new chat and the `chatgpt-web-operations` workflow, not a Codex subagent.
  The initial review verified 70 evidence payloads and requested two bounded roots
  corrections plus a dependency-map correction. All three were resolved; the
  closure review verified 9 revision payloads and approved the revised design.
  Prompts, inventories, replies, SDK excerpts, and gate/probe evidence remain in
  the external directory above. The final verdict is `review-verdict-2.json`.
- Final review closure covers explicit roots for nearby hints, the preserved
  custom-root metadata/default limitation, exact dependency ordering, and uncached
  HTTP characterization. No public compatibility rebaseline was approved.
- Local handoff contains only this design and the master control document. The
  resulting commit SHA belongs in the handoff report, not in its own file content.

G2 is ready for coordinator review and a separately authorized implementation
turn. It is not `implementing`, `validating`, or `done`. No code, dependency,
production checkout, remote branch, or service was changed by this design task.
