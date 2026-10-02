# Group 1 implementation design — Composition foundation — 2026-10-02

Status: **ready; final duplicate-policy review clean; production implementation has not started**.

Parent control document:
`docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`.

This document is the execution specification for G1 only. A future implementation
must preserve a working server after every step. This design task changes documents
only; its isolated probes do not implement G1 in the repository.

## 1. Baseline, authority, and scope

Start from deployed commit `4608423a960bc0cba0e92e20cb8425084b76535c`:

```text
77a04c0 -> 50916ef (separate glob fix) -> 4608423 (G0)
```

G0 is done. The coordinating user supplied final CI, deployment, live-suite,
smoke, doctor, and real ChatGPT `list_files` evidence. The master plan records
that evidence and the retained external production-document backup. Do not
repeat the old deployment task as a prerequisite for this design.

Runtime baseline: FastMCP and FastMCP-slim `4.0.10`; MCP and MCP-types `2.1.1`.
G1 does not change dependencies, lock entries, extras, or supported Python versions.

Read these before implementation:

- `AGENTS.md`, `DEVELOPMENT.md`, `docs/testing.md`, `docs/quality-gates.md`;
- the implementation master and G0 implementation design;
- the architecture investigation, platform-neutral architecture design, and
  high-level migration plan dated 2026-10-02.

The last three inputs remain user-owned untracked files under
`/home/grammy-jiang/Projects/binnacle/docs/`. Read them there without changing,
copying into a commit, or moving them. Their pre-G0 version observations are
historical; this design uses the post-G0 source and pinned SDK.

### 1.1 Target

- A no-argument `create_server() -> FastMCP` in `binnacle.server`.
- Existing `server.mcp`, `server.app`, and deployment entrypoints remain usable.
- One Files child, one Search child, and one Commands child, mounted without
  namespaces or tool renames.
- In-process tests prove root, child, and intermediate-stage behavior.
- `tools.register_all()` is removed only after all mounts preserve parity.
- FastMCP remains the composition, provider, middleware, transform, and lifespan
  framework. Binnacle adds ordinary wiring, not another framework.

### 1.2 Common exclusion set O

Every atomic step below inherits this exclusion set. A listed exception applies
only to the named file and responsibility.

Do not change `config.py`, settings precedence/cache, `identity.py`, `visibility.py`,
`logging_middleware.py`, `callctx.py`, tool implementations or registration
signatures, `search_text_register.py`, search pipeline/schema/telemetry modules,
jobs/manager/process/cgroup/output code, CLI/server-unit behavior, deployment
scripts, watchdog/tunnel, or existing public pins/golden outputs.

Do not introduce G2 native visibility, broad dependency injection, `Depends`,
Tasks/extras, platform contracts, macOS, package relocation, external plugin
discovery, operational routes, a Feature protocol, ServerBuilder, RuntimeContext,
custom Provider router, or lifecycle dispatcher. Do not change middleware order.
Do not add a runtime duplicate validator or custom root/child lifespan for G1.
The native `on_duplicate="error"` constructor option only hardens local-provider
registration. Section 5.3 defines the separate test-only ownership gate.

`pyproject.toml` may change only its Import Linter contracts for the new composition
owners. `uv.lock`, runtime dependency expectations, and quality-policy floors stay
unchanged. No earlier worktree or production checkout may be edited during local
implementation. Integration/deployment requires its separate normal authorization.

## 2. Current source facts

| Area | Post-G0 behavior and G1 consequence |
| --- | --- |
| `server.py` | Import configures logging, resolves `TOKEN_FILE`, constructs authenticated FastMCP, appends three Binnacle middlewares, registers tools, logs effective config, and exports `app = mcp.http_app()`. Keep the bootstrap exports and logging point. |
| `tools/__init__.py` | Imports eight adapter modules and calls their `register()` functions in the pinned order. This is the temporary remaining-tools bridge during migration. |
| All eight `register()` functions | Register nested callable wrappers with existing descriptions, annotations, parameter constraints, defaults, and explicit output schemas. Call these unchanged on a different FastMCP instance. |
| `tools/search_text.py` | Its `register()` delegates to `search_text_register.register_search_text()` with the implementation and configured schema/limits. The Search child calls this existing entrypoint, not the lower helper directly. |
| Identity and visibility | One `ClientIdentity` is shared by root request logging, tool logging, and `ClientToolVisibility`. Modern discovery metadata is remembered for later bare requests; legacy identity comes from initialization. Preserve this instance relationship. |
| `callctx.py` | ContextVars carry call/client/turn/argument/timing data through synchronous worker execution to domain telemetry and jobs. Mounts must preserve that propagation and reset behavior. |
| Configuration | `get_settings()` is cached; multiple domain modules capture settings at import. G1 factories create fresh MCP objects, not isolated domain settings or job services. |
| Deployment | `cli.serve()` and dev-mode `server_unit.py` use `binnacle.server:app`; module execution uses the exported `mcp.run(...)`. No entrypoint changes. |
| Existing tests | `surface_support.served()` exercises `server.mcp` through `Client`; HTTP helpers exercise exported `server.app` with ASGI lifespan and bearer auth. Keep both paths tested. |

The default order is:

```text
read_file, list_files, search_text, edit_file, write_file,
run_command, job_status, stop_job
```

ChatGPT sees the same ordered subsequence with `edit_file` and `write_file` removed.
This is a product compatibility contract, not an incidental dictionary order.

## 3. Pinned FastMCP findings and isolated evidence

### 3.1 Source authority

Inspected installed FastMCP `4.0.10` under
`.venv/lib/python3.13/site-packages/fastmcp/`, including:

- `server/server.py`: constructor, `mount`, `add_provider`, `add_transform`,
  `list_tools`, middleware dispatch, and `local_provider`;
- `server/providers/aggregate.py`: ordered aggregation, lookup, duplicates,
  provider errors, and lifespan;
- `server/providers/fastmcp_provider.py`: list wrapping, delegated calls,
  middleware, and child lifespan;
- `server/providers/local_provider/local_provider.py`: insertion order and
  duplicate behavior;
- `server/providers/base.py` and `server/transforms/__init__.py`: public transform
  list/get semantics;
- `server/mixins/mcp_operations.py`: wire-level version deduplication;
- `server/mixins/lifespan.py`: root and provider startup/teardown order.

The installed `server/middleware/dereference.py` was also inspected to confirm
the implicit schema middleware's list-response behavior.

Current official documentation was also reviewed:
[composition](https://gofastmcp.com/servers/composition),
[testing](https://gofastmcp.com/servers/testing),
[middleware](https://gofastmcp.com/servers/middleware),
[LocalProvider](https://gofastmcp.com/servers/providers/local),
[Transforms](https://gofastmcp.com/servers/transforms/transforms), and
[lifespans](https://gofastmcp.com/servers/lifespan).
These establish the native concepts. The installed version and executable probe
decide version-specific behavior. For example, the current Transform documentation
shows a returned mount reference; installed `4.0.10` returns `None` from `mount()`.
Use `root.mount(child)` for its side effect. Install the ordering transform on
the root through `root.add_transform(...)`.

### 3.2 Provider and middleware findings

1. Every FastMCP starts with its LocalProvider first. A root-local tool added
   after a mount still lists before mounted tools.
2. LocalProvider lists tools in registration order. AggregateProvider gathers
   providers concurrently but flattens results in provider order, preserving
   each provider's contiguous sequence.
3. `mount(child)` adds a native FastMCPProvider. Its wrappers preserve tool
   metadata and delegate execution to the child's `call_tool()`.
4. Root middleware wraps mounted calls. Only the selected child's call
   middleware runs. Listing queries every child, so child list hooks may run
   concurrently; do not assert a global sibling-list completion order.
5. FastMCP automatically adds `DereferenceRefsMiddleware`. Current Binnacle then
   appends RequestLogging, ToolLogging, and ClientToolVisibility. Passing those
   three in the constructor's `middleware=` argument would put them before
   dereferencing in this SDK and would change the current sequence.
6. `FastMCP()` defaults local duplicate handling to `warn`, although standalone
   `LocalProvider()` defaults to `error`. Explicit `on_duplicate="error"` handles
   duplicates within one local provider only.
7. Cross-provider duplicate identities warn and remain in the internal list.
   The wire handler deduplicates by name/version. Lookup chooses the highest
   version; equal or unversioned ties choose the first provider. Mounting is
   not a global duplicate-error check.
8. Native lifespan enters the root user lifespan, then provider/child lifespans;
   teardown reverses that order. G1 must not manually start child lifespans or
   take ownership of the stable jobs process.

### 3.3 Probe and baseline results

Retained design evidence, outside all worktrees:

```text
/home/grammy-jiang/.local/state/binnacle/g1-composition-design-20261002T110708Z-rtmjkac8/
```

`composition_probe.py` and `composition-probe.json` record the pinned-SDK probe.
It uses scratch config/token/data and an embedded job spool under `/tmp`, not
the deployed endpoint or production job manager. Results:

| Probe | Result |
| --- | --- |
| All six permutations of three plain domain mounts | None produces the pinned eight-tool order |
| Four migration stages times four client profiles | All 16 preserve order, existing normalized hashes, instructions, and full wire tool metadata with the proposed Transform |
| Modern/legacy ChatGPT hidden write call | Refused; scratch file not created |
| Repeated listings | Stable in the same session |
| Fully mounted real adapters | All eight representative calls passed |
| Synthetic call middleware | `parent:in, child:in, child:out, parent:out`; sibling call middleware absent |
| Native lifespan | Root, child, sibling enter once; sibling, child, root exit once |
| Child tool added after mounting | Appears and is callable through the parent |
| Duplicate-name characterization | Internal list contains both; wire list contains one; first provider wins; the earlier guard prototype rejects startup |

A second isolated `startup_guard_probe.py` confirmed that the earlier guard
prototype rejects duplicates through both native Client and ASGI lifespan, with
zero child lifespan entries. `startup-guard-probe.json` retains that historical
feasibility result. It does not establish a need for a runtime guard. The current
design excludes that guard and uses the ownership contracts in section 5.3.

The steering revision was checked separately, with evidence retained at:

```text
/home/grammy-jiang/.local/state/binnacle/g1-design-revision-20261002T120218Z-dqt4_t16/
```

`no_guard_composition_probe.py` and `no-guard-composition-probe.json` use native
FastMCP conflict defaults and no custom lifespan on the real-adapter roots or
children. All 16 stage/profile comparisons and all eight representative calls
passed again. Each stage also passed exact root-local inventory and raw aggregate
multiplicity checks. Deliberately adding a second `edit_file` through root/child
or child/child ownership left the eight-tool wire order and existing hashes
unchanged, but produced nine internal tools and failed the ownership contract.
Native startup still succeeded. This proves why wire hashes alone are insufficient
and why the proposed test-only gate catches the concrete G1 collision risk.

The final correction was verified with local strictness enabled and no runtime
guard. Evidence is retained separately at:

```text
/home/grammy-jiang/.local/state/binnacle/g1-final-design-20261002T122256Z-zng1isq8/
```

`local_strict_no_guard_probe.py` and `local-strict-no-guard-probe.json` repeat
all 16 stage/profile comparisons and eight representative calls successfully.
Five local-registration cases (root before mounts, empty-local root after all
mounts, Files, Search, Commands) raise native `ValueError` on duplicate local
registration. With local strictness set on every collision participant, both
root/child and child/child duplicates still allow native startup, preserve the
wire hashes, and fail the raw ownership assertion. The final design uses this
local-versus-cross-provider distinction; it requires no custom lifespan.

The first probe harness tried root `list_tools()` without a session and hit the
existing identity middleware's session requirement. The probe was corrected to
use `list_tools(run_middleware=False)` for internal inspection. Production
identity code was not changed. Client-facing tests always use `Client` or HTTP.

On unchanged `4608423`, the nine G0 compatibility modules passed again:
**90 passed**. The existing architecture checker passed with 100 modules and zero
forbidden reverse dependencies; all six Import Linter contracts passed. These
are design-baseline checks, not claims that future G1 implementation is tested.

## 4. Tool-order decision

Three simple mounts produce this default order:

```text
Files:    read_file, list_files, edit_file, write_file
Search:   search_text
Commands: run_command, job_status, stop_job
```

No permutation can place Search inside the Files block. During partial migration,
remaining root-local tools also list before the mounted Files child. The six-tool
ChatGPT profile alone would miss part of this problem because it hides edit/write.

Use a small native `Transform` subclass, `PublicToolOrder`, in new module
`src/binnacle/tool_order.py`. Its only override is:

```python
async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
    return sorted(tools, key=lambda tool: _RANK.get(tool.name, len(_RANK)))
```

`_RANK` derives from the eight-name public order above. This is presentation data,
not a source of components. It must not import tool modules, register anything,
route calls, inspect client identity, or own domain membership. Unknown names
remain after the pinned names in their original relative order. Missing names
are not manufactured. Duplicate objects are not removed. Tool objects and all
their fields remain unchanged. Inherit native get/resource/prompt behavior.

Install it once on the root before the first mount migration. Keep it after G1:
it remains necessary while exact cross-domain order is a public contract. Removal
requires a separately reviewed order change or equivalent native ordering support.
It is not G2 visibility work; `ClientToolVisibility` keeps all filtering/denial.

Alternatives rejected:

- Rebaseline the order: breaks the explicit public contract.
- Split Files into read and write servers: four mounts can match the final order,
  but split one domain and still leave the partial root-local migration problem.
- Change provider internals or subclass aggregation: couples Binnacle to routing
  internals and duplicates a framework responsibility.
- Copy mounted tools back onto the root: loses native child ownership/middleware
  semantics and leaves duplicate registration.
- Add sorting request middleware: puts component presentation in the wrong
  framework layer and changes the request middleware chain.

Tradeoff: one small, permanent presentation Transform is needed to preserve a
historical interleaved surface while keeping exactly three coherent child servers.

## 5. Construction and lifetime decisions

### 5.1 Root factory and compatibility exports

Keep `create_server()` in `src/binnacle/server.py`, with no arguments. It constructs
a fresh FastMCP and a fresh ClientIdentity shared by the same three new middleware
instances on each call. Reuse the current exact server name, instructions,
StaticTokenVerifier mapping (`client_id="binnacle-tunnel"`), and `_load_token()`.
Set native `on_duplicate="error"` for this root's LocalProvider. This rejects
same-provider registration mistakes only; it is not cross-provider enforcement.

Keep `logging.basicConfig`, `TOKEN_FILE`, `_load_token`, `log_effective_config`, and
the current module bootstrap. In particular, retain:

```python
mcp = create_server()
log_effective_config()
app = mcp.http_app()
```

Keep the existing `if __name__ == "__main__"` transport/host/port behavior. Do not
switch uvicorn to factory mode or replace `binnacle.server:app`.

Append Binnacle middleware with `add_middleware()` exactly as today. The effective
sequence stays:

```text
SDK DereferenceRefsMiddleware
  -> RequestLoggingMiddleware
    -> ToolLoggingMiddleware
      -> ClientToolVisibility
        -> lookup/delegation/tool
```

The factory does not call `log_effective_config()` or build HTTP apps. The module
bootstrap logs once as today. Additional factory calls do not emit duplicate
`event=config` records. Config-warning behavior and startup measurement remain.

After a domain is mounted, a tool call follows this composed sequence:

```text
root DereferenceRefsMiddleware
  -> root RequestLoggingMiddleware
    -> root ToolLoggingMiddleware
      -> root ClientToolVisibility
        -> native FastMCPProvider delegation
          -> child DereferenceRefsMiddleware
            -> child tool
```

Only the selected child handles that call. Listing queries each child's native
middleware before aggregation and the root ordering Transform; root visibility
then filters the ordered sequence. This adds no child Binnacle middleware and
does not change the root middleware order.

Importing `binnacle.server` still constructs the exported default server and needs
a valid token. Missing/empty token behavior stays unchanged. Tests needing another
token patch `server.TOKEN_FILE`/`_load_token` after an isolated initial import, or
use a subprocess with scratch config before import. Do not make auth optional.

Fresh factories isolate MCP registration, middleware identity caches, and native
server state. They do not isolate module-level settings, `SERVER_GEN`, jobs,
tokenizer globals, or domain services. Do not claim multi-configuration roots in
one process. That is later settings/DI work.

### 5.2 Focused factories

Add three small top-level modules without moving existing code:

| New module and factory | Existing registrations, in child order |
| --- | --- |
| `files_server.py::create_files_server()` | `read_file`, `list_files`, `edit_file`, `write_file` |
| `search_server.py::create_search_server()` | `search_text` |
| `commands_server.py::create_commands_server()` | `run_command`, `job_status`, `stop_job` |

Each no-argument function returns a fresh ordinary FastMCP with native
`on_duplicate="error"` for its own LocalProvider. Use internal server names
`binnacle-files`, `binnacle-search`, and `binnacle-commands`. Add no child instructions, auth,
Binnacle middleware, HTTP app, transport, or operational routes. Native default
middleware/lifespan behavior remains. Root auth protects the externally served
HTTP boundary; child in-process tests are not authentication tests.

The root imports factories directly and calls `root.mount(child)` without a
namespace or `tool_names`. Do not store the return value. Do not add tags,
versions, wrapper functions, changed defaults, or alternate domain implementations.

### 5.3 Duplicate ownership contracts; no runtime validator

G1 has a closed, eagerly registered set of eight unversioned built-in tools.
The root calls fixed child factories directly. No configuration, plugin discovery,
request handler, or startup resource changes that composition after construction.
The concrete new collision risk is a migration mistake: retaining a moved root
registration or registering the same name in two children. Both are deterministic
source changes that exact composition contracts can detect before integration.
No additional G1 failure mode was found that requires a runtime validator.

Use test assertions, independent of the production order table, to require:

1. Each child has exactly its named tools in the section 5.2 order; child name
   sets are pairwise disjoint.
2. `await root.local_provider.list_tools()` has exactly the remaining root-local
   sequence for the current checkpoint in section 6.
3. `await root.list_tools(run_middleware=False)` contains exactly eight tools,
   with each expected name appearing once. Compare a `Counter` with the expected
   eight-name `Counter`, not a set or a dictionary indexed by name.
4. Wire order, full metadata, existing hashes, visibility, and representative
   calls still pass separately through native `Client` and authenticated HTTP.

The raw aggregate assertion runs before wire deduplication and without root
request middleware, which needs a session. G1 children have no visibility filter.
Thus ChatGPT's hidden edit/write tools cannot conceal a duplicate from this test.
Do not use private SDK provider/tool dictionaries. The ordering Transform must
retain duplicates so it cannot defeat this contract.

Prove that the test detects both root/child and child/child duplicate fixtures,
including `edit_file`, even when the existing wire hashes remain unchanged.
Do not turn these test assertions into an exported production helper or registry.
Tests detect the G1 composition mistakes; they do not claim to prohibit arbitrary
future runtime calls to FastMCP's mutation APIs.

Use `FastMCP(..., on_duplicate="error")` inside the root and each child factory
as local-provider registration hardening. The SDK raises `ValueError` when the
same component identity is registered twice in that server's LocalProvider.
This catches local mistakes that the default warning/replacement behavior can
hide from a post-registration inventory. Test this native behavior on fresh
factory instances, including the root after its local inventory becomes empty.
Keep these construction assertions separate from clean composition fixtures.

That option is not global provider collision enforcement. Even when it is set
on every server, cross-provider duplicates still use FastMCP's warning, wire
deduplication, and deterministic lookup rules. Do not claim that mounting or
starting such a composition raises an error. The raw test assertions above
detect those collisions at every migration checkpoint; exact surface tests,
architecture review, full CI, and deployment gates remain mandatory.

Add no custom duplicate validator, startup rejection, root/child lifespan callback,
or provider-error policy. Native lifespans retain framework lifecycle ownership.
Valid built-in composition never relies on cross-provider precedence because
the test acceptance gate rejects collisions before integration.

This resolves the platform-neutral design's section 6.3 for G1. Its requirement
to fail startup or tests is met by exact tests. Its following request for startup
validation is superseded for this group by the explicit review steering to keep
composition minimal. The historical architecture input stays unchanged. Later
dynamic providers, versions, or conditional registration would require a separate
design decision; G1 does not prepare a general validation framework for them.

## 6. Compatibility bridges and removal order

| Accepted checkpoint | Remaining root-local registrations | Mounted domains | Registry state |
| --- | --- | --- | --- |
| Factory, tests, order, ownership contracts | All eight, original order | None | Original `register_all` |
| Files activated | Search, Commands | Files | Remove only Files imports/calls from `register_all` |
| Search activated | Commands | Files, Search | Remove only Search import/call |
| Commands activated | None | Files, Search, Commands | Root stops calling `register_all`; unused three-command function retained briefly |
| Registry retired | None | Files, Search, Commands | Remove obsolete function/imports; keep `tools/__init__.py` as a package marker |

The exact root-local sequence at each acceptance point is:

```text
Before mounts:  read_file, list_files, search_text, edit_file, write_file,
               run_command, job_status, stop_job
Files active:  search_text, run_command, job_status, stop_job
Search active: run_command, job_status, stop_job
Commands active and registry retired: empty
```

At each checkpoint, test the actual exported root and a fresh factory root against
that sequence and the raw eight-name multiplicity contract. Then test the same
pinned public sequence, hashes, metadata, and instructions for default, modern
ChatGPT, legacy ChatGPT, and unrelated clients. The Transform restores public order
while ownership moves one domain at a time. Retain each checkpoint's passing test
evidence; a final-only parity check does not prove the intermediate migrations.
Test-only stage fixtures may exercise the ordering bridge across all four layouts.
They supplement tests of the actual current root, not replace them. Do not add
production stage parameters, runtime switches, or a second composition registry.

In the two partial stages, document the temporary function as registering the
remaining local tools; do not add feature flags, domain registries, exclusion
parameters, or register-then-remove logic. The root factory supplies the complete
surface throughout. Switch each domain's registration and mount in one atomic
change, after the child's separate tests pass. Never serve both copies.

The original `tools/__init__.py` imports may cause unrelated adapters to load while
children are first introduced. This is a temporary import side effect, not a
claim that domain settings are isolated. Final registry retirement removes those
eager imports. Existing adapter module import paths remain valid.

The root/export compatibility bridge remains after G1. The ordering Transform
also remains. Domain registration functions remain unchanged. No compatibility
facade may duplicate a public tool or bypass middleware/auth.

## 7. Public behavior acceptance matrix

| Contract | Required proof |
| --- | --- |
| Eight default and six ChatGPT tools | Exact sequence, not only a set; check all four migration checkpoints |
| Schemas/descriptions/annotations | Existing `SURFACE_SHA256`, instruction hash, output schemas, token budget, and golden results unchanged; also compare raw wire tool dumps on the same interpreter |
| Validation | Unknown fields, missing arguments, wrong scalar types, bounds, and ToolError behavior remain; no relaxed schema validation |
| Client visibility | Modern `openai-mcp(ChatGPT)`, legacy `openai-mcp`, default, and unrelated client; discovery then bare follow-up, repeated listing, reconnect, direct denial of both hidden tools |
| Request pipeline | Root middleware once per operation; native child call middleware only on selected child; call identity/ContextVars reach real synchronous adapters and reset on success/error |
| Auth/HTTP | Missing/wrong/doubled bearer rejected; valid auth initializes; session requirements, `/mcp`, tool errors as results, and visibility unchanged |
| Files/Search | Scratch write/read/edit/list/search round trip, escaping-path rejection, search modes/budget/schema/telemetry unchanged |
| Commands | Sync completion, background handoff, status/cursor/tail, stop, manager ownership and reload durability unchanged |
| Exports/entrypoints | `server.mcp`, `server.app`, token helper, config logging, module execution, `binnacle serve`, and unit rendering compatible |
| Composition ownership | Disjoint child inventories, no remaining root-local tools at final checkpoint, native mounts, no hidden duplicate registrations |

Never update pins to make a refactor pass. Inspect semantic differences, determine
their source, and stop for review if preserving behavior needs excluded code changes.

## 8. Atomic implementation sequence

Use one reviewed checkpoint per row/step below. Before edits, run the relevant
existing tests. After edits, run those tests plus the named new tests. Test groups
are defined in section 9. Every step keeps exclusion set O and unchanged public
pins. Production activation here means selecting a path in the development source,
not deploying it. Only the final authorized deployment changes the live server.

### G1.0 — Record the implementation baseline

- **Purpose/current/target:** record the deployed G0 baseline before any G1 code.
  Confirm worktree HEAD, versions, clean tracked state, and supplied architecture
  inputs. Use a new implementation worktree, not this design worktree or production.
- **Files:** no production edits; external evidence and control status only.
- **Out of scope/API:** O; no new framework API.
- **Invariants/tests:** run B and A before starting; capture raw profile surfaces
  alongside existing hashes for diagnostic comparison.
- **Rollback:** discard only this step's own uncommitted evidence if needed;
  preserve all other worktrees. No product rollback required.
- **Parallel-safe:** read-only analysis yes; baseline/config ownership one agent.
- **Done:** stable versions, green baseline, explicit implementation branch/base.

### G1.1 — Extract the root factory without mounts

- **Purpose/current/target:** replace module-global assembly with the factory in
  section 5.1; the same `register_all(root)` still registers all tools.
- **Files:** `server.py`; new `tests/integration/test_server_factory.py`.
- **Out of scope/API:** O; no registry/child changes. Use native
  `FastMCP(on_duplicate="error")`, `StaticTokenVerifier`, `add_middleware`,
  and existing `http_app` export.
- **Invariants:** exact instructions/auth/full middleware order; fresh identity
  per root; no new config-log duplication; same import-time token errors.
- **Tests before/after:** B and E; new factory tests cover two distinct roots,
  registration isolation, exports, middleware identity sharing, and bootstrap.
  Registering the same synthetic local tool twice must raise native `ValueError`;
  this test makes no claim about cross-provider collisions.
- **Rollback:** revert the factory extraction and its new tests; old assembly
  still uses the same registrations. Do not touch services.
- **Parallel-safe:** no; root construction is the shared foundation.
- **Done:** explicit construction and existing exported app both pass parity.

### G1.2 — Add composition characterization and ownership contracts

- **Purpose/current/target:** existing tests focus on the exported singleton;
  add equivalent coverage for fresh factory roots before mounting real domains.
- **Files:** optional backward-compatible `mcp_server` keyword in
  `tests/contracts/surface_support.served()`; new
  `tests/contracts/test_server_composition.py`,
  `tests/integration/test_server_composition.py`, and test-only helpers if needed.
- **Out of scope/API:** O; production source unchanged. Native `Client(FastMCP)`,
  public `local_provider.list_tools()`, `list_tools(run_middleware=False)`,
  middleware, and synthetic child lifespans only. No production validator.
- **Invariants:** existing `served()` callers retain the singleton default.
  Use existing hash constants/normalization, not a second mutable golden set.
  Require the exact current root-local sequence and eight raw names, each once,
  using section 5.3's independent expected-name `Counter`.
- **Tests before/after:** B; add C for roots, two synthetic mounted siblings,
  middleware/error traces, lifespan enter/exit, and disjoint client identities.
  Include root/child and child/child duplicate fixtures with a hidden `edit_file`.
  They must fail the raw ownership contract even when Client wire hashes pass
  and native startup succeeds. Extend exact child inventories as factories appear.
- **Rollback:** remove only additive tests/helper option; G1.1 remains functional.
  Retain the ownership gate while activating mounts.
- **Parallel-safe:** test authors may split contract/pipeline tests after agreeing
  fixture ownership; only one author edits shared helpers.
- **Done:** tests characterize the migration boundary and fail when order,
  metadata, duplicate execution, or identity isolation is deliberately disturbed.
  Both collision fixtures are detected before wire deduplication. The same
  ownership acceptance criteria run at every later staged mount checkpoint.

### G1.3 — Preserve order through a native Transform

- **Purpose/current/target:** all tools remain local; install `PublicToolOrder`
  as a no-op on the current public order, ready for later mixed ownership.
- **Files:** new `tool_order.py`, `server.py`, new
  `tests/unit/core/test_tool_order.py`, composition contract tests.
- **Out of scope/API:** O; no visibility migration. Subclass native `Transform`,
  override only `list_tools`, and call `root.add_transform` once.
- **Invariants:** section 4; no object copies/field edits/filtering/deduplication.
- **Tests before/after:** B+C; unit cases cover mixed known/unknown names, stable
  unknown order, empty/subset sequences, duplicates retained, and input untouched.
  Synthetic mixed local/mounted listings must match the independent contract order.
- **Rollback:** revert this step while all tools are still local. Once mounts are
  active, revert those switches first; never remove the required order bridge alone.
- **Parallel-safe:** no root edits in parallel; isolated Transform tests may split.
- **Done:** original pins remain and the known aggregation mismatch is corrected.

### G1.4a — Introduce Files child without switching the root

- **Purpose/current/target:** add an independently testable Files factory; exported
  root remains wholly on the proven old path plus the order Transform.
- **Files:** new `files_server.py`, composition tests, precise Import Linter
  allowance for this composition module in `pyproject.toml`.
- **Out of scope/API:** O; do not edit four tool modules, paths/text I/O, or root
  registration. Native `FastMCP(on_duplicate="error")` and existing `register()`.
- **Invariants:** four child tools only, same child order and wire metadata as the
  corresponding default root tools. Creating two Files children is independent.
- **Tests before/after:** F and B; after add C child inventory/metadata and real
  scratch file workflow, local duplicate registration rejection, then A.
- **Rollback:** remove unused child/tests/allowance; root never depended on them.
- **Parallel-safe:** child/test work can overlap other unactivated child work after
  G1.3; one integration owner handles `pyproject.toml` and shared tests.
- **Done:** child works standalone in-process; root pins still unchanged.

### G1.4b — Mount Files and remove its root registrations

- **Purpose/current/target:** activate tested Files child and leave Search/Commands
  registered locally through the temporary bridge.
- **Files:** `server.py`, `tools/__init__.py`, composition tests.
- **Out of scope/API:** O; factory/tool bodies unchanged. `root.mount(files)`.
- **Invariants:** exactly one registration per name; order Transform covers mixed
  local/mounted listing; only root has Binnacle middleware/auth.
- **Tests before/after:** B+C+F+E and A; verify root LocalProvider contains exactly
  Search/Commands and Files calls cross the native child boundary once.
- **Rollback:** revert the atomic mount/registry switch together; keep unused Files
  factory if useful. The previous checkpoint is a complete working server.
- **Parallel-safe:** no; shared root/registry integration only.
- **Done:** all profile pins and authenticated Files workflows pass with Files mounted.

### G1.5a — Introduce Search child without switching the root

- **Purpose/current/target:** wrap existing `tools.search_text.register()` in a
  fresh focused FastMCP; active root remains at the Files checkpoint.
- **Files:** new `search_server.py`, composition tests, precise Import Linter
  allowance in `pyproject.toml`.
- **Out of scope/API:** O; especially no changes to `search_text_register.py`,
  search defaults, ingestion, budgeting, schemas, or telemetry. Native FastMCP.
- **Invariants:** exactly one unchanged `search_text` tool; no wrapper replacement
  that breaks the current captured implementation/monkeypatch behavior.
- **Tests before/after:** S and B+C; after add standalone Search metadata/call
  checks and A.
- **Rollback:** remove unused Search factory/tests/allowance; active path unchanged.
- **Parallel-safe:** yes for isolated child work after G1.3; shared gates/helpers
  remain integration-owned.
- **Done:** child schema/result/telemetry parity established before root activation.

### G1.5b — Mount Search and remove its root registration

- **Purpose/current/target:** Files and Search are mounted; only Commands remain
  in the old local registration bridge.
- **Files:** `server.py`, `tools/__init__.py`, composition tests.
- **Out of scope/API:** O; `root.mount(search)` with no namespace.
- **Invariants:** exact interleaved order survives; Search executes the same adapter
  under root identity/logging and has no duplicate local copy.
- **Tests before/after:** B+C+S+E and A, including HTTP file/search round trip and
  root LocalProvider inventory limited to three Commands tools.
- **Rollback:** revert Search mount/registry switch together; Files stays mounted.
- **Parallel-safe:** no; root/registry integration step.
- **Done:** all profiles and search-specific contracts pass through the mount.

### G1.6a — Introduce Commands child without switching the root

- **Purpose/current/target:** group the three existing job-facing MCP adapters;
  do not create a CommandService or change stable job ownership.
- **Files:** new `commands_server.py`, composition tests, precise Import Linter
  allowance in `pyproject.toml`.
- **Out of scope/API:** O; native FastMCP and existing registrations only.
- **Invariants:** same output schemas, sync/background behavior, job identifiers,
  ContextVars, cursor semantics, and manager selection.
- **Tests before/after:** J and B+C; child tests use temporary embedded spools or
  existing manager fixtures, never the production socket. Add A.
- **Rollback:** remove unused Commands factory/tests/allowance; active root unchanged.
- **Parallel-safe:** isolated child work yes; avoid job-fixture/helper edits owned
  by another lane. No command-domain refactor in this lane.
- **Done:** representative sync/background/status/cursor/stop paths pass standalone.

### G1.6b — Mount Commands and stop using the registry

- **Purpose/current/target:** all three children mounted, root LocalProvider empty.
  Remove the root import/call of `register_all`; retain the now-unused registry
  function temporarily so removal follows a proven complete composition.
- **Files:** `server.py`, composition tests; no adapter or job implementation edits.
- **Out of scope/API:** O; `root.mount(commands)` only.
- **Invariants:** root auth/visibility/logging still cover every command; no service
  ownership moved into lifespan; one call/result pair per call.
- **Tests before/after:** B+C+J+E+A, plus managed full suite at this checkpoint.
- **Rollback:** revert Commands mount and restore root registry call together;
  the retained function still registers only Commands. Files/Search remain mounted.
- **Parallel-safe:** no; final root switch and managed gate are coordinated.
- **Done:** all eight tools run through three native mounts; root-local inventory
  empty; full suite green before deletion of old glue.

### G1.7 — Retire obsolete registration glue and tighten boundaries

- **Purpose/current/target:** delete unused `register_all` and its eager imports
  from `tools/__init__.py`; keep the existing package and adapter paths.
- **Files:** `tools/__init__.py`, final Import Linter contracts in `pyproject.toml`,
  composition tests, small current testing/quality documentation notes if needed.
- **Out of scope/API:** O; no new API or package move.
- **Invariants:** no production/test caller left; no fallback registry retained;
  only focused composition modules enter tool adapters from outside that package.
- **Tests before/after:** B+C+E+A; search all tracked callers; subprocess-import
  smoke exercises the final package without relying on cached module globals.
- **Rollback:** restore the unused function/imports if diagnosing an import
  regression. Restoring registration behavior requires the matching mount switch;
  never reconnect the registry while duplicate mounts remain active.
- **Parallel-safe:** no; final boundary and cleanup ownership one integrator.
- **Done:** no `register_all` code/call remains, final architecture gates and public
  parity pass, and no compatibility facade has changed tool imports.

### G1.8 — Converge, review, and later integrate

- **Purpose/current/target:** turn locally passing composition into a reviewed
  implementation candidate; deployment remains a separate gate.
- **Files:** evidence/control documents; only directly justified fixes within G1.
- **Out of scope/API:** O; no new framework concepts.
- **Invariants/tests:** all section 10 local gates, fresh read-only review, exact
  final diff inspection. No pin churn or hidden compatibility exceptions.
- **Rollback:** before deployment use normal reviewed code reverts in isolated
  worktrees; after later authorized deployment use the canonical deploy rollback,
  not manual production reset/cleanup.
- **Parallel-safe:** reviews yes; commits/integration/control status one owner.
- **Done:** local implementation recorded as awaiting CI/deployment, not G1 done.
  Only actual CI, canonical deployment, live smoke, and connector evidence permit
  master-plan status `done`.

## 9. Exact focused test strategy

Use `uv run pytest -q ... --randomly-seed=12345` for each focused set. Keep module
sizes below 500 lines; split tests by contract/pipeline responsibility if needed.
Do not split tests merely to evade the limit or add duplicate golden fixtures.

### B — Baseline/public compatibility

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

The observed 90-test design baseline used the nine G0 modules; B additionally
includes token budgets and golden outputs for implementation acceptance.

### C — New composition tests

Proposed locations:

- `tests/contracts/test_server_composition.py`: exported root versus fresh root;
  every profile's ordered surface, instruction hash, raw same-interpreter wire
  dumps, child inventory, duplicate multiplicity, and validation parity.
- `tests/integration/test_server_factory.py`: exports, fresh identity/state,
  token failures, config-log count, bootstrap and ASGI lifespan compatibility.
- `tests/integration/test_server_composition.py`: native child delegation,
  middleware/lifespan scope, mounted real workflows and ContextVar propagation.
- `tests/unit/core/test_tool_order.py`: pure sequence transformation properties.

Retain existing singleton tests; do not monkeypatch all tests to use only a new
factory. Extend `served()` with a keyword-only optional server only if useful.
Keep expected order independent of the production Transform's rank table, so
changing that table cannot silently change the test oracle.

Use fresh root instances to test two clients/roots without remembered-identity
leakage. Assert the three Binnacle middleware instances share identity within
one root and differ across roots. Synthetic child tracers use native middleware
and append event records; they are test-only. Assert a partial order for concurrent
list hooks and an exact root/selected-child onion for one call.

For each real mounted domain, capture root call/result logging and domain-side
`current_call`/`current_client`/explicit argument names. Include success and
failure, HTTP turn headers, and concurrent requests with distinct turns. Preserve
the current ToolError boundary and restoration of ContextVars. Patch the existing
adapter lookup point when testing delegation; Search captures its implementation
at registration, so patch before creating that child.

Client entry/exit tests verify root/child lifespans run once per active server
lifetime and clean up on failure. Do not claim once per operating-system process
across unrelated Client lifetimes. These are native lifecycle characterization
tests with synthetic callbacks; G1 production factories add no custom lifespan.
Add no test-only child middleware to production factories. Do not rely on private
SDK fields except existing project-owned middleware attributes in an
identity-relationship assertion.

A public `root.local_provider.list_tools()` assertion distinguishes migrated from
remaining tools. `root.list_tools(run_middleware=False)` checks duplicate counts
before wire deduplication. `Client.list_tools()` checks what the client sees.
All three prove different facts and must not be substituted for one another.
Use section 6's exact stage expectations when switching each domain. Exercise the
two negative duplicate fixtures in section 5.3 to prove that the raw contract fails
even when client-visible pins pass. Do not expect native startup to reject them.
Set native local strictness on the synthetic collision servers too, to prove that
`on_duplicate="error"` does not enforce uniqueness across providers. Separately
test duplicate local registration on each real factory: the root and all three
children must raise native `ValueError`, without a custom Binnacle helper.

### F — Files

```text
tests/unit/tools/test_read_file.py
tests/unit/tools/test_list_files.py
tests/unit/tools/test_edit_file.py
tests/unit/tools/test_write_file.py
tests/unit/core/test_properties.py
```

Add C's standalone and mounted Files metadata/call checks. Use `tmp_path`, not
production project files. Existing path/property coverage includes prerequisite
commit `50916ef`; do not alter it in G1.

### S — Search

Run the tracked `tests/unit/tools/test_search_text*.py`,
`tests/unit/core/test_search_text*.py`,
`tests/integration/test_search_text*.py`, and
`tests/contracts/test_search_text_surface.py`, plus C's Search checks.
Use the same interpreter/config for before/after raw schema comparisons.

### J — Commands and durable jobs

Run tracked `tests/unit/tools/test_stop_job_edges.py`,
`tests/unit/core/test_job*.py`, `tests/unit/core/test_run_command*.py`,
`tests/integration/test_job*.py`, `tests/integration/test_run_command*.py`,
and `tests/contracts/test_job*.py`, plus C's Commands checks. Shell globs here
mean the existing matching test files, not newly invented paths.

Reuse `tests/integration/job_test_support.py` and existing fixtures. New tests
must set a scratch spool and embedded owner, or use the isolated manager fixture.
Background jobs must be stopped/reaped in `finally`. Preserve explicit timing
contracts; do not reduce production warm-up or weaken signal-escalation checks.

The G0 evidence records an existing telemetry startup race. If it recurs, report
the exact node, seed, and logs; do not treat a retry as a fix or mix unrelated
test repair into this composition change.

### E — Import, HTTP, and deployment entrypoints

```text
tests/integration/test_server_factory.py
tests/integration/test_auth_asgi.py
tests/integration/test_http_workflows.py
tests/integration/test_cli.py
tests/integration/test_setup_units.py
tests/unit/core/test_units.py
tests/integration/test_packaging_smoke.py
```

Add a subprocess with scratch token/config set before import to prove exported
`mcp`/`app` and error behavior. Test module execution by replacing the runner in
an isolated process/test harness; do not bind the production port. Existing CLI
and unit tests must still assert `binnacle.server:app`, uvloop/httptools, and
current reload behavior. ASGI tests use the app's lifespan context, not a live
production service. Keep HTTP auth tests even though `Client(FastMCP)` is green.

### A — Architecture and static boundary checks

```bash
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
uv run python scripts/check_module_size.py --strict
```

Preserve all existing contracts. Incrementally extend the protected-tools
`allowed_importers` to the precise new `binnacle.files_server`,
`binnacle.search_server`, and `binnacle.commands_server` owners. Keep
`binnacle.server` allowed while it still imports the registry; remove that
allowance at G1.7. Rename the contract description to reflect focused composition.
Do not permit `binnacle.*` generally or add ignore-import exceptions.

Keep tool-module independence, server-not-dependency, top-level acyclicity, and
watchdog contracts. Add an independence contract for the three focused server
modules once they all exist. Each child imports only its own adapter modules;
the root imports factories; `tool_order.py` imports no Binnacle adapters. Tests
prove child inventories and root ownership. Review the actual import graph,
not only allowed-importer strings.

Final static/diff review must also confirm: no root per-tool registration calls;
no `register_all` callers; no private SDK registry access; no Feature/Builder/
RuntimeContext; no new auth/middleware/Tasks/visibility/settings/platform logic;
no runtime duplicate validator or custom lifespan; and no dependency or schema
pin change. Cross-provider uniqueness is a test/architecture acceptance criterion
at every checkpoint, not a runtime policy implemented by Binnacle.
These are bounded review checks, not a new
generic architecture framework or a repository-wide FastMCP import migration.

## 10. Group convergence and integration gates

After focused tests and all mount switches pass, run the canonical gates from
the isolated implementation worktree:

```bash
uv lock --check --offline
uv run python scripts/run_test_suite.py --seed 12345
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
env BINNACLE_TEST_WORKERS=4 uv run tox run
uv run pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
```

The managed suite's ordinary-process lane is mandatory. The supported matrix is
Python 3.10-3.14, with the dedicated coverage-policy environment for 3.13. New
composition modules must satisfy the existing per-module 95/90 classification;
do not add coverage exclusions or temporary floors. Packaging must prove that
new child/Transform modules are included in the clean installed artifact and
that the exported server path still imports.

Review the final diff against `4608423`, including dependencies, instructions,
all public hashes, module ownership, and compatibility exports. Record local
evidence and a fresh read-only ChatGPT review. Then commit locally using current
repository conventions. Do not conflate local completion with deployment.

After separate publication/deployment authorization, follow `DEVELOPMENT.md`
and `docs/github-governance.md`: publish the candidate branch for exact-SHA CI;
require Code quality, Python 3.10/3.11/3.12/3.14 tests, Python 3.13 coverage, and
Python 3.13 packaging. Use only the canonical production gate:

```bash
.venv/bin/python scripts/deploy_smoke.py deploy TARGET
```

The normal gate checks CI/fast-forward/quiet production, smokes the new code,
rolls back on failure, and updates deployment refs only on success. It does not
restart the stable jobs service. After deployment require read-only live pytest,
the normal full smoke/doctors, and a real ChatGPT -> Binnacle read-only call.
No production file cleanup, service restart, or remote mutation is authorized
by this design document alone.

## 11. Risks, stop conditions, and rollback boundaries

- Plain mount ordering is incompatible; keep the Transform while any mixed or
  fully mounted composition is active.
- Root construction must not reorder the SDK's implicit schema middleware.
- A wire list can hide duplicate registrations; test raw multiplicity and fixed
  ownership before each migration checkpoint. Add no runtime validation in G1.
- Child registration can capture callables/config at construction; keep existing
  signatures and patch tests at the correct time rather than rewriting adapters.
- Fresh MCP instances do not remove import-time global settings or durable job
  state. Do not broaden G1 to make them do so.
- A mount may add framework-level validation/delegation passes. Require unchanged
  results, errors, telemetry counts, and existing deployment resource limits.
- Do not add child auth and assume it enforces the root HTTP boundary.
- Do not run real service/network mutations in local tests.

Stop for design review if preserving the pinned surface requires tool-body,
visibility, settings-wide, job-lifecycle, or deployment redesign; if supported
Python behavior differs; or if source drift makes the characterized SDK path
incorrect. Record the smallest failing case without weakening tests or hashes.

Every activation has its paired reverse change in section 8. A preparation
commit is safe to remove only while no active root depends on it. For a later
checkpoint, reverse dependent mount switches first, then remove unused factories.
This is a sequence of working rollback points, not permission to revert arbitrary
dependent commits in an order that breaks imports. No persistent data migration
belongs to G1.

## 12. Parallel work and implementation handoff

Root factory, order, shared ownership tests, root switches, registry removal, shared
Import Linter configuration, and control status have one integration owner.
Files/Search/Commands preparation can use independent branches after G1.3 if
each stays within its factory and domain-specific tests. Integrate activations
in Files -> Search -> Commands order. Parallel branches do not edit `server.py`
or `tools/__init__.py` independently. Keep every branch's focused evidence.

A future Codex implementation prompt should point to this design and require:

1. Recheck deployed/base refs and current instructions; create a new worktree.
2. Execute the atomic steps in order and keep working checkpoints.
3. Use existing FastMCP APIs and unchanged domain registrations.
4. Run each focused set, then all convergence gates; record exact results.
5. Obtain review and commit locally; stop before remote/production actions
   unless the prompt separately authorizes them.

No G2-G6 work is authorized by that G1 scope.

## 13. Design validation and exit state

This design is prepared on a separate branch based on `4608423`. The originally
suggested worktree received a draft from another session during investigation;
that draft was preserved. This run uses
`/home/grammy-jiang/Projects/binnacle-g1-composition-design-codex` on
`design/g1-composition-foundation-2026-10-02-codex`.

Design-time evidence comprises the installed-source inspection, official-doc
review, isolated probe, 90-test baseline, architecture/import checks, and the
changed-document pre-commit gate. No G1 implementation, deployment, service
restart, or remote publication occurs in this task.

The earlier [read-only ChatGPT review](https://chatgpt.com/c/6abf9795-ea90-83ec-8aec-fc18d1120b56)
approved the prior design after middleware and guard-test clarifications. Subsequent
coordinating review required a narrower duplicate policy. This revision retains
the explicit root-to-child middleware sequence and replaces the runtime guard
with tested ownership contracts. The earlier guard probes and review remain
historical evidence, not requirements for implementation.

The [next read-only ChatGPT review](https://chatgpt.com/c/6abf9f46-b350-83ec-83f1-40dabd6024c2)
returned **APPROVE, no findings** for the test-only cross-provider policy. The final
correction folds ownership checks into G1.2, removes the separate duplicate step,
and specifies native local registration hardening without global enforcement.
These reviews are static inspection of supplied design/source/probe evidence,
not independent execution or deployment approval.

The [fresh final ChatGPT review](https://chatgpt.com/c/6abfa3ee-0314-83ec-82fc-48961cecaf1f)
returned **APPROVE — no findings**. It confirmed that the runtime guard is fully
removed, local strictness is not global enforcement, and raw ownership acceptance
remains separate from wire parity at each checkpoint. Prompts, replies, and probe
evidence are retained in the final-correction directory in section 3.3.

Changed-document pre-commit passed for the reviewed correction. Final
status/evidence-only edits use the same document gate before commit.
No production Python, tests, dependencies, lock, or protected architecture inputs
were changed by this design task.

G1 is `ready` in the master plan, not `implementing` or `done`. The next action
is independent review in the coordinating conversation, then preparation of
the G1 local implementation prompt. G1 completion still requires the later
implementation and integration gates in section 10.
