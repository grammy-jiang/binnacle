# G5 diagnostics, operations and companions — implementation design — 2026-10-07

Status: **done; implementation, independent final review, exact-SHA CI, canonical deployment, companion activation, and live verification complete on 2026-10-08**.

Baseline: deployed G4 completion `b07406806ac622df00e583b0079e4b70cad76340`.
Its runtime/source bytes are identical to the reviewed G4 implementation candidate
`c954701ed6691f4749274ea8d7ffc0ce3ec9eb08`; the completion commit changes only the
G4 design/master documentation. This G5 design branch was rebased onto the exact
deployed completion before review. Fresh independent approval is recorded at
<https://chatgpt.com/c/6ac6383c-dd54-83ec-be77-3b688670053c>.
G5.0 baseline: 191 focused tests pass, architecture/import/strict-size gates pass,
and the 141833-byte four-profile wire archive matches the deployed SHA256 below.

## 1. Purpose

G5 makes diagnostics and operational reliability follow the architecture's ownership
direction:

```text
watchdog / tunnel companions
          |
          v
public server / diagnostic contracts
          |
          v
        server

server/core/features/platform ---X---> companion internals
```

G5 is not a package-relocation group. G6 owns broad moves after these boundaries are
proven.

## 2. Current evidence

The G4 candidate was re-read before this draft. Focused G5 baseline:

- doctor/connectivity/watchdog-doctor/Webmin/server-factory tests: **78 passed**;
- architecture checker: **121 modules, 0 forbidden reverse dependencies**;
- Import Linter: **15 contracts kept, 0 broken**.

Those gates are green because the current rules isolate `binnacle.ops.watchdog`, but
they do not yet prohibit the two historical top-level reverse dependencies below.

### 2.1 Confirmed reverse dependencies

1. `doctor.py -> doctor_connectivity.py -> uplink.py`
   - core `binnacle doctor` calls `check_uplink()` when probes are enabled;
   - `check_uplink()` is built directly on watchdog/reliability route and layered
     network probing;
   - `watchdog_doctor.py` imports `check_uplink` back through `doctor.py`.

2. `cli.py::stats -> webminstats.py`
   - the import is lazy and only occurs for `--system-resources`;
   - the dependency still makes the core CLI know a host/watchdog-specific Webmin
     history implementation.

### 2.2 Other ownership coupling to resolve or classify

- `watchdog_doctor.py` imports core doctor rendering plus compatibility helpers from
  `doctor.py`; companion diagnostics should consume stable diagnostic contracts,
  not the aggregate core doctor implementation.
- `tunnel_doctor.py` imports the generic log-tail helper from
  `doctor_connectivity.py`; that helper needs neutral ownership or a companion-local
  home.
- `ops/watchdog/services.py` imports `tunnel_doctor`; this is classified as an
  implementation dependency to remove by extracting the tunnel-log scan into a
  tunnel-owned public helper with no doctor/rendering dependency.
- no Binnacle FastMCP `custom_route()` is currently registered. The server only
  exposes the MCP HTTP application.

### 2.3 Existing characterization already available

Do not add duplicate characterization tests where the current suite already pins the
behavior G5 needs to preserve or deliberately migrate:

- `tests/system/test_doctor_coverage.py` proves core doctor calls the uplink check
  when `probe=True` and omits it for `probe=False`;
- `tests/system/test_doctor_connectivity.py` pins active/standby/wedged/partial
  uplink result classification;
- `tests/system/test_watchdog_doctor.py` pins the watchdog doctor's uplink probe
  delegation and no-probe behavior;
- `tests/system/test_webminstats.py` and `tests/integration/test_cli.py` pin
  `stats --system-resources`, including the same `since/until` window and the
  default no-Webmin path;
- `ops/watchdog/services.py` currently treats any HTTP response from
  `Policy.mcp_url` as proof the MCP process is alive and restarts the active MCP
  unit only after the configured consecutive-failure threshold.

The candidate's CLI help was captured without modifying source under
`~/.local/state/binnacle/g5-prep-fd05-characterization/`. SHA-256 records are
stored beside the captures. The current user-visible facts are:

- core doctor documents the uplink probe as part of its default report and exposes
  `--probe/--no-probe`;
- core stats exposes `--system-resources/--no-system-resources` and explicitly
  describes Webmin system-status history;
- watchdog and tunnel keep separate `doctor` commands.

This existing coverage is the starting characterization. Add a new test only when a
G5 design decision creates a behavior that is not already pinned.

### 2.4 Exact cross-boundary import inventory

A fresh AST inventory on the G4 candidate shows the remaining companion-facing edges
that G5 must either remove or explicitly bless as public contracts.

Core/diagnostic edges that are not acceptable at Gate A:

- `doctor_connectivity.py -> uplink.py`;
- `cli.py -> webminstats.py`;
- `watchdog_doctor.py -> doctor.py` (companion importing the aggregate core doctor);
- `watchdog_cli.py -> doctor.py` and `tunnel_cli.py -> doctor.py` (lazy CLI imports
  used only for `render()` / `render_json()`; both must move to the neutral renderer);
- `tunnel_doctor.py -> doctor_connectivity.py` (only for the shared tail helper);
- `watchdog_cli.py -> cli.py`;
- `tunnel_cli.py -> cli.py`.

Companion-to-companion classification:

- `ops/watchdog/services.py -> tunnel_doctor.py` is prohibited; tunnel-log scanning
  moves behind a tunnel-owned public helper;
- `watchdog_cli.py -> tunnel_unit.TUNNEL_UNIT` is explicitly allowed as the one
  narrow cross-companion service-identity contract. No tunnel rendering/specification
  helper is part of that allowance.

Companion imports of stable public contracts/configuration such as diagnostic result
types, service-log errors and service-unit names may remain only when the target module
is deliberately documented as a public contract. Importing another application's CLI
or doctor aggregate is not such a contract.

This inventory is intentionally stricter than the current Import Linter configuration,
which protects `binnacle.ops.watchdog` but does not yet encode all top-level companion
facades. G5.5 must turn the accepted final direction into mechanical rules.

### 2.5 Deployed-G4 drift check — 2026-10-07

G5.0 was performed after G4 production completion. The design branch was rebased from
the preparation baseline onto exact deployed completion
`b07406806ac622df00e583b0079e4b70cad76340`. A source/script/dependency diff from the
rebased G5 design HEAD back to both deployed completion and reviewed runtime candidate
`c954701ed6691f4749274ea8d7ffc0ce3ec9eb08` is empty for `src/`, `scripts/`,
`pyproject.toml`, and `uv.lock`.

The current import inventory was re-read after the rebase with `from binnacle import X`
expanded to the effective `binnacle.X` edge. It still contains the exact ownership
edges this design targets: `doctor_connectivity -> uplink`, lazy
`cli.stats -> webminstats`, `watchdog_doctor -> doctor`, lazy
`watchdog_cli/tunnel_cli -> doctor` rendering imports,
`tunnel_doctor -> doctor_connectivity`, `watchdog_cli/tunnel_cli -> cli`, and
`ops/watchdog/services -> tunnel_doctor`. No new production dependency invalidates the
planned file ownership.

The deployed G4 public MCP wire baseline remains byte-identical at 141833 bytes with
8/6/6/8 tool visibility and SHA-256
`acbc4e794ee45c1bd9dbd3a51dafa9634f101e06ed18a0b0cea36d2f32fcb61f`. G5 must
preserve that wire surface. G4's completion-only documentation commit does not require
any G5 implementation redesign.

### 2.6 Post-deploy characterization refresh

After rebasing to the deployed G4 completion, the read-only characterization was
refreshed under `~/.local/state/binnacle/g5-design-review-d607100/characterization/`.
Core doctor, watchdog doctor and tunnel doctor representative runs all exited 0; the
core/watchdog no-probe captures and all four CLI help surfaces were hashed. A live
`binnacle stats --since="-1 hour" --until=now --system-resources` capture exited 0,
confirming that the opt-in Webmin path remains usable on the deployed host. The focused
server-composition/wire contract file passed **26 tests**. No source or service mutation
was performed by this characterization.

The G4 completion evidence remains the authoritative live four-profile wire archive;
G5.0 does not regenerate a different public baseline when deployed runtime bytes are
unchanged.

## 3. Goals

G5 must:

- remove core/server reverse dependencies on watchdog reliability implementation;
- organize checks by core/domain/platform/companion ownership;
- keep common diagnostic result/rendering contracts minimal;
- introduce only the operational HTTP state that has a concrete consumer;
- use FastMCP `custom_route()` for root-owned operational HTTP;
- make watchdog and tunnel consume public contracts rather than core implementation
  internals;
- prove the server starts and its MCP surface works with watchdog code unavailable;
- preserve the existing public MCP tool surface exactly.

## 4. Non-goals

G5 does not:

- move the package tree into `features/`, `platform/`, or `companions/`;
- add macOS/launchd support;
- redesign Binnacle structured product telemetry;
- replace durable jobs with FastMCP Tasks;
- create a generic diagnostics plugin framework;
- create a second HTTP framework around FastMCP;
- do broad compatibility-facade deletion that belongs to G6.

## 5. FastMCP-native operational route boundary

Pinned FastMCP 4.0.10 exposes:

```python
FastMCP.custom_route(
    path: str,
    methods: list[str],
    name: str | None = None,
    include_in_schema: bool = True,
)
```

The handler is an async Starlette request handler returning a Starlette response.

Implementation characterization found that `deptry` correctly rejects those direct
Starlette imports while Starlette is only a transitive FastMCP dependency. G5.4 must
promote the **already locked and installed Starlette 1.6.0** to an explicit runtime
requirement (`starlette>=1.6.0`), with its reason in the dependency contract. Keep the
existing lock as the base, resolve offline without upgrade flags, and verify that every
package/version/source/artifact entry is unchanged; only Binnacle's root dependency
and requires-dist metadata may change. Do not suppress DEP003 or import Starlette
indirectly through an undocumented SDK re-export. This is the native FastMCP handler
contract, not a second HTTP server/framework. Rollback of G5.4 reverts this declaration
with the handler and consumer changes; no installed package-version rollback is needed.
Fresh amendment review: APPROVE, no findings,
<https://chatgpt.com/c/6ac63c80-9924-83ec-beb5-abf598192562>.

G5 must keep generic operational routes root-owned. Child custom routes are not the
default because mounted child routes share the root path namespace.

### 5.1 Route design rule

Do **not** add an omnibus admin API. Before choosing a path/schema, characterize the
actual state currently reconstructed by watchdog/tunnel from systemd, local files, or
server internals. Add only values that:

1. are owned by the server;
2. are safe and meaningful for an external companion;
3. avoid exposing secrets or tool payloads;
4. have a stable consumer.

Candidate concepts from the approved architecture are liveness/readiness,
version/revision, server generation, active-call/restart-safe state, command-manager
health, and enabled capabilities. The final G5 design must narrow this list before
implementation.

### 5.2 Minimal operational route draft

Current watchdog repair does not need an administrative API. Its MCP-service decision is
only: the unit is active, but does the local server HTTP process answer at all?

The narrow draft is therefore one root-owned liveness endpoint:

```text
GET /healthz
200 application/json
{"status":"ok"}
```

Implementation constraints for review:

- register it with FastMCP `custom_route()` on the root server, not a child;
- `include_in_schema=False`;
- do not expose token/config/tool payloads, active command text, paths, or host details;
- do not add version/revision/generation fields without a concrete consumer;
- keep the response independent of watchdog, tunnel, systemd and Linux adapters;
- let the watchdog probe this endpoint instead of abusing the MCP endpoint merely to
  observe that some HTTP status was returned;
- preserve the existing consecutive-failure and rate-limit restart policy exactly.

FastMCP 4.0.10 builds the MCP endpoint itself behind `RequireAuthMiddleware`, while
additional custom routes are appended separately at the Starlette routing layer.
Application-level authentication middleware can populate request auth context, but the
custom route is not automatically wrapped by the MCP endpoint's required-auth wrapper.
Because the proposed payload is deliberately non-sensitive liveness state, the design
must not assume MCP endpoint authentication applies automatically.

**Design decision for independent review:** `GET /healthz` is intentionally
unauthenticated. Its purpose is transport/process liveness, not authentication or MCP
readiness, and requiring the bearer token would couple the watchdog's most basic
liveness check to token-file readability and auth state. The response is therefore
fixed to exactly `{"status":"ok"}`, carries no dynamic server/host/config data, and
has no mutation semantics. The watchdog continues to apply its existing failure-count
and restart-rate policy; only the URL changes from `/mcp` to `/healthz`. A test must
prove an unauthenticated request receives exactly this payload while the authenticated
MCP endpoint behavior and public MCP wire surface remain unchanged.

The path, authentication decision and exact JSON are frozen for the G5 design-review
packet; implementation remains unauthorized until G4 closes and the design is
independently approved.

## 6. Proposed responsibility boundaries

### 6.1 Core diagnostics

Core doctor owns:

- config/root/token correctness;
- server/service state through G4 contracts;
- MCP endpoint auth/initialize checks;
- durable-job health through command/job contracts;
- service-log error checks;
- boot/persistence checks through G4 Linux composition.

Core doctor does **not** own route failover, USB/radio recovery, watchdog policy, or
Webmin history.

### 6.2 Reliability companion diagnostics

Watchdog diagnostics own:

- default-route inventory and layered uplink probes;
- network failover/recovery policy state;
- hardware/radio/USB recovery diagnostics;
- watchdog service state.

Webmin resource history is not watchdog policy. It remains an observability/Linux
adapter behind the section 6.4 contract and is not pulled into watchdog diagnostics.

The existing `check_uplink` behavior must be moved/owned here without changing its
layer semantics or failure classifications.

### 6.3 Shared diagnostic contracts

`doctor_contracts.py` remains the natural minimal shared result contract
(`Check`, status helpers). Companions may consume this contract.

Do not make `doctor.py` itself a shared API. Compatibility aliases used by companions
must be eliminated or redirected before G5 exits.

### 6.4 Stats / system resource history decision

Characterization shows that `--system-resources` is opt-in, uses the exact same
`since`/`until` window as journal stats, and has focused tests pinning lazy access,
rendered output, permission fallback and error behavior. Removing or relocating the
flag would create user-visible churn for no architectural benefit.

**Design decision for independent review:** preserve
`binnacle stats --system-resources` exactly, but remove the direct
`cli.py -> webminstats.py` implementation dependency.

G5 introduces one narrow, non-generic observability contract, for example:

```python
class SystemResourceHistory(Protocol):
    def render_window(self, since: str, until: str | None) -> str: ...
```

The CLI consumes only that contract. One explicit observability composition seam binds
the current Webmin implementation when the flag is requested; no registry, entry-point
system, generic diagnostics plugin framework or runtime discovery is introduced.
The Webmin reader remains lazy: constructing or reading the concrete provider is
forbidden when `--system-resources` is false.

Ownership is therefore **observability/platform adapter**, not watchdog policy. G6 may
later relocate the concrete Webmin implementation under the final observability/Linux
package once G5 proves this seam. Existing `tests/system/test_webminstats.py` behavior
is the compatibility baseline; G5 adds focused CLI tests proving the core CLI imports
only the contract/composition seam and that the concrete provider is invoked only for
the opt-in flag.

## 7. Atomic implementation plan

### G5.0 — deployed-G4 drift check and characterization

After G4 deploy:

- rebase/recreate from the exact deployed G4 completion SHA;
- repeat this import inventory;
- capture `binnacle doctor --help`, representative doctor output, stats help and
  `--system-resources` behavior;
- freeze watchdog/tunnel doctor representative output;
- prove current public MCP wire hashes.

No production change.

### G5.1 — diagnostic ownership seam

- make shared diagnostic contracts independent of core aggregate doctor;
- move neutral helpers out of core aggregate modules where needed;
- preserve rendering and exit-status behavior;
- add architecture tests that companions do not import `doctor.py`.

### G5.2 — uplink ownership correction

- move `check_uplink` ownership to the reliability companion;
- remove `doctor_connectivity -> uplink`;
- adjust core doctor help/output intentionally;
- preserve watchdog uplink diagnostics and probe semantics exactly;
- add static gate forbidding core diagnostics -> reliability implementation.

### G5.3 — system-resource ownership correction

- preserve the existing `binnacle stats --system-resources` flag and output;
- add the narrow `SystemResourceHistory` contract and one explicit observability
  composition binding;
- remove direct `cli.py -> webminstats`;
- keep provider construction/read lazy when the flag is false;
- retain current Webmin parsing/rendering/permission behavior behind the adapter;
- add static gate forbidding core CLI/stats from importing the Webmin implementation.

G5.2 and G5.3 may run in parallel after G5.1 contracts settle because they own
different behavior.

### G5.4 — operational HTTP surface

- characterize concrete companion need;
- add minimal root-owned FastMCP custom route(s);
- test auth/schema/error behavior in-process and through authenticated HTTP as
  appropriate;
- prove no MCP tool/resource/prompt surface drift.

This may be implemented in parallel with G5.2/G5.3 after the route schema is approved,
but `server.py` has one integration owner.

### G5.5 — companion dependency cleanup

- replace `watchdog_doctor -> doctor` with imports from minimal diagnostic contracts
  and companion-owned checks;
- replace the lazy `watchdog_cli/tunnel_cli -> doctor` rendering imports with direct
  imports from the neutral `doctor_render` module;
- move the neutral log-tail helper out of `doctor_connectivity` so
  `tunnel_doctor -> doctor_connectivity` disappears;
- remove `watchdog_cli -> cli` and `tunnel_cli -> cli`: companion setup/reload uses
  the G4 Linux provisioner composition seam, service state uses the G4 service inspector,
  and server identity comes from `server_unit`; companions must not import private core
  CLI helpers/constants;
- extract tunnel-log parsing/scanning from `tunnel_doctor` into a tunnel-owned public
  helper with no doctor/rendering dependency, so `ops/watchdog/services` can consume
  that narrow helper without importing another application's doctor aggregate;
- **retain** the watchdog's dependency on the tunnel service identity, but freeze the
  only permitted edge as `watchdog_cli -> tunnel_unit.TUNNEL_UNIT`. The unit name is a
  deliberate public companion contract because watchdog policy must monitor/restart the
  tunnel service. Importing `tunnel_unit` rendering/specification helpers remains
  forbidden;
- strengthen Import Linter/AST rules to make these exact decisions mechanical, including
  an allowlist for only `TUNNEL_UNIT` on the watchdog-to-tunnel edge.

The required end state is not "zero imports from companions into core". Companions are
allowed to consume stable public server/domain contracts. The prohibited direction is
core/features/platform/diagnostics aggregates consuming companion implementation, plus
companions depending on another application's aggregate CLI/doctor implementation.

### G5.5.1 Focused mechanical edge plan

The final static gates are edge-specific rather than package-wide guesses:

- forbid `watchdog_doctor -> binnacle.doctor`;
- forbid `watchdog_cli -> binnacle.doctor`;
- forbid `tunnel_cli -> binnacle.doctor`;
- forbid `tunnel_doctor -> binnacle.doctor_connectivity`;
- forbid `watchdog_cli -> binnacle.cli`;
- forbid `tunnel_cli -> binnacle.cli`;
- forbid `ops/watchdog/services -> binnacle.tunnel_doctor`;
- allow `watchdog_cli -> binnacle.tunnel_unit.TUNNEL_UNIT` only; fail if that import
  widens to any other name from `tunnel_unit`;
- forbid `doctor_connectivity -> binnacle.uplink`;
- forbid `cli -> binnacle.webminstats`;
- require the Webmin implementation to sit behind the system-resource-history contract.

Each rule gets a tiny synthetic/AST regression proving the prohibited former import
shape is caught; do not rely only on scanning the current tree.

### G5.5.2 Exact file/test ownership plan

The implementation is intentionally file-bounded so G5 can be split without
competing edits after the deployed-G4 drift check.

#### Shared diagnostic contracts / rendering

- keep doctor_contracts.py as the dependency-free Check/status record API;
- move doctor.py::render() and render_json() into a neutral rendering module
  (planned doctor_render.py) and leave compatibility imports in doctor.py only
  for the duration of G5;
- move _tail_lines() out of doctor_connectivity.py into a neutral file-I/O helper
  (planned doctor_io.py) consumed by core/tunnel/watchdog diagnostics;
- migrate companion imports directly to doctor_contracts, doctor_render and
  doctor_io; both companion doctor modules and the `doctor` subcommands in
  `watchdog_cli.py` / `tunnel_cli.py` must not import the doctor.py aggregate;
- for the existing `Systemctl` / `systemctl` / `unit_state` compatibility needed by
  companion diagnostic tests, importing the narrow G4-backed primitives from
  `doctor_common.py` is permitted during G5; do not route those names back through
  `doctor.py`. Broad relocation/removal of that compatibility facade remains G6 work.

Characterization to preserve: tests/system/test_doctor.py render/JSON exit-code
behavior plus the current watchdog/tunnel doctor output tests. New static tests must
prove the aggregate-import edges are gone.

#### Reliability/uplink ownership

- move check_uplink() out of doctor_connectivity.py into a watchdog/reliability
  diagnostic module colocated with the existing uplink.py probe model;
- keep low-level uplink.py route/probe semantics intact; G5 changes ownership and
  composition, not probe algorithms;
- watchdog_doctor.run_all() becomes the only owner of the full layered uplink
  diagnostic;
- core doctor.run_all() stops composing the watchdog/reliability uplink check. Any
  resulting core-doctor output/help change is deliberate G5 behavior and must be pinned
  in the design-review packet, not smuggled in as refactor drift.

**CLI compatibility decision for independent review:** keep accepting the existing
`binnacle doctor --probe/--no-probe` switch throughout G5 so scripts do not start
failing argument parsing merely because uplink ownership moves. After G5 the core
doctor has no non-local uplink probe, so this switch becomes a compatibility-only
selector with no effect on the core check set; the help text must say that explicitly
rather than pretending the core doctor still owns network probing. `binnacle-watchdog
doctor` is the authoritative layered uplink diagnostic. A focused CLI regression must
prove both legacy spellings remain accepted, produce the same core-doctor checks, and
do not import or invoke watchdog/uplink implementation. Removing the legacy switch
entirely is deferred to G6 compatibility-facade review and requires its own public-UX
decision.

The compatibility baseline is
tests/system/test_doctor_connectivity.py (active route fail, standby warn, partial
reachability, no-route cases) and
tests/system/test_watchdog_doctor.py (probe delegation and probe=False).
Move/retarget those tests with the implementation rather than duplicating them.

#### System-resource history seam

- add system_resource_contracts.py with only the
  SystemResourceHistory.render_window(since, until) protocol;
- add one explicit observability composition module
  (planned system_resource_history.py) that lazily constructs the Linux/Webmin
  adapter;
- retain webminstats.py as the concrete Linux observability implementation during G5;
- change cli.stats() to import only the contract/composition seam and construct/read
  the provider only inside the system_resources branch.

The current behavioral baseline is tests/system/test_webminstats.py and
tests/integration/test_cli.py::test_stats_only_loads_webmin_history_when_requested.
Add only seam-specific tests: no provider construction when the flag is false, exact
since/until forwarding when true, and an AST/import regression forbidding
cli.py -> webminstats.py.

#### Operational HTTP

- the only G5 server-route edit is in server.py::create_server(): register one root
  FastMCP custom_route('/healthz', ['GET'], include_in_schema=False);
- the handler is independent of auth/systemd/watchdog state and returns exactly
  200 application/json {"status":"ok"};
- change watchdog policy construction in watchdog_cli.py from the current /mcp
  liveness URL to /healthz; do not alter failure thresholds, restart rate limits or
  repair ordering;
- keep ops/watchdog/services.py::http_alive() semantics that any HTTP response proves
  transport/process liveness. The route change makes the normal case a clean 200 rather
  than relying on MCP authentication failure as a liveness signal.

Add focused in-process/HTTP tests for unauthenticated /healthz, exact payload,
include_in_schema=False, unchanged authenticated /mcp behavior, and unchanged MCP
wire snapshots. Retarget the existing HTTP-alive test from /mcp to /healthz.

#### Companion CLI and tunnel-log cleanup

- watchdog_cli.py and tunnel_cli.py replace private binnacle.cli imports with the
  G4 service provisioner/inspector composition plus server_unit.SERVER_UNIT;
- move scan_tunnel_log() and its result record from tunnel_doctor.py into a
  tunnel-owned non-rendering helper (planned tunnel_log.py);
- tunnel_doctor.py and ops/watchdog/services.py both consume that helper;
- watchdog_cli.py -> tunnel_unit.TUNNEL_UNIT remains the sole allowed
  watchdog-to-tunnel identity import.

The corresponding static regression must reject every former aggregate edge and reject
any widening of the tunnel_unit import beyond TUNNEL_UNIT. The current
tests/system/test_tunnel_checks.py::test_scan_tunnel_log_reports_the_last_forwarded_command
moves with the helper and remains the behavioral baseline.

#### Integration ownership

server.py, cli.py, watchdog_cli.py and tunnel_cli.py each have one integration
owner during implementation. Parallel workers may prepare contracts/adapters/tests, but
must not concurrently edit those four files. G5.2/G5.3/G5.4 can still run in parallel
once G5.1 contracts settle by handing their integration patches to those owners.

### G5.6 — convergence

- server construction with watchdog imports blocked;
- core doctor without watchdog installed/importable;
- watchdog and tunnel focused suites;
- public MCP wire parity;
- full suite, coverage, Python matrix, package smoke;
- architecture/Import Linter/module-size/pre-commit/pre-push;
- independent implementation review;
- exact-SHA CI;
- canonical deploy + live smoke/doctors + real ChatGPT read-only call.

### G5.7 — production activation and rollback boundary

The canonical server deploy remains `scripts/deploy_smoke.py deploy <exact-sha>` and
retains its existing pre-push rollback. G5 adds one companion activation step because
`binnacle-watchdog.service` is a long-running Python process and does not auto-reload
when the checkout fast-forwards. Activation order is fixed:

1. deploy the exact reviewed/CI-green G5 candidate through the canonical server gate;
2. verify `/healthz`, MCP wire parity, live pytest and core/tunnel/watchdog doctors while
   the already-running watchdog still uses its pre-G5 `/mcp` liveness policy;
3. run `binnacle-watchdog deploy-check`; only at a quiet verdict restart
   `binnacle-watchdog.service` so it loads the G5 companion bytes and `/healthz` URL;
4. verify the watchdog unit identity, fresh start timestamp, doctor output, one healthy
   observation cycle, and that no unexpected repair/restart action fired;
5. do not restart the durable jobs manager, and do not restart the tunnel merely for
   CLI/doctor/helper ownership changes.

Only a failure **inside step 1, before the canonical gate successfully atomically
pushes the deployment refs**, uses that gate's existing checkout/environment rollback.
Steps 2-4 run after the deployment transaction has committed; their failure cannot
trigger an already-finished gate's rollback. Preserve the evidence and running service
state, then prepare a focused forward fix or revert commit, obtain its required CI,
and deploy through the same canonical gate. Do **not** reset production or directly
move deployment refs. If companion activation has occurred, restore the watchdog
consumer at its quiet gate before removing the server route, as specified below. The current `http_alive()` contract
counts any HTTP response as liveness, so a missing `/healthz` returning an HTTP error
during a forward rollback does not become a false "server dead" signal; nevertheless
rollback correctness must be proven by the restored watchdog doctor/observation cycle,
not by relying on that incidental HTTP status alone.

Each atomic G5 implementation commit must remain independently revertible until the
final candidate. G6 relocation/facade deletion is not part of this rollback boundary.

### G5 checkpoint rollback rules

Each row is one green, independently revertible checkpoint. Keep compatibility aliases
until replacement consumers pass their focused tests; do not delete facades as part of
an unrelated cleanup. Revert dependent checkpoints in reverse order, with the following
explicit boundaries:

| Checkpoint | Retained bridge and rollback |
| --- | --- |
| G5.1 diagnostic helpers | Keep `doctor.render`, `doctor.render_json` and the existing tail-helper aliases while consumers move to neutral helpers. Revert the consumers and helper extraction together; original rendering, exit codes and imports remain recoverable. |
| G5.2 uplink ownership | Move the uplink check, switch watchdog composition, remove core composition, and update core help/tests in one commit. Revert all four together. Both probe flag spellings remain accepted before and after; the low-level probe algorithm is unchanged. |
| G5.3 resource history | Keep the existing Webmin implementation intact behind the new contract. Revert the CLI binding and new seam together to restore the original direct opt-in call; no stored history changes. |
| G5.4 health route | Deploy the root route before activating the watchdog consumer. For rollback after activation, first forward-deploy a revert of only the watchdog URL to `/mcp`, quiet-gate its restart, and verify its loaded policy and healthy observation; only then forward-deploy route removal. Before activation, route and unused consumer-source changes can revert together. |
| G5.5 companion imports | Keep the old aggregate entrypoints and deliberate compatibility re-exports until direct-helper consumers and static gates pass. Revert each consumer migration with its extraction and matching static rule; never leave an import pointing at a removed helper. |

Local reversions use normal revert commits on the implementation branch. Once a
candidate has been deployed, every fix/revert follows exact-SHA CI and canonical
fast-forward deployment; post-deploy failures are not claimed as automatic rollback.
A quiet-gate timeout is a recorded incomplete activation, not permission to restart a
busy watchdog. Bound that wait and continue only when its normal gate succeeds.
The stable jobs manager and tunnel remain running throughout G5 activation/recovery.

No G5 checkpoint changes job/resource lifecycle ownership, durable schema, installed
dependency versions, FastMCP Tasks, or package layout. No data migration or data rollback is required.
G6 package relocation and facade removal wait for completed G5 evidence.

## 8. Parallel-safe work

Safe after G4 closes:

```text
                 G5.1 shared diagnostic contracts
                            |
              +-------------+-------------+
              |             |             |
              v             v             v
        G5.2 uplink    G5.3 resources   G5.4 HTTP
              \             |             /
               +------------+-------------+
                            |
                            v
                     G5.5 cleanup
                            |
                            v
                     G5.6 convergence
```

Before G4 closes, only G5.0 inventory, characterization, design, and test planning are
allowed. Do not edit G4-owned shared production modules in parallel.

## 9. Compatibility surface

Must remain unchanged unless the approved G5 design explicitly records a deliberate
CLI diagnostic migration:

- all public MCP tool names/order/descriptions/schemas/annotations/visibility;
- durable job semantics;
- deployment and stable jobs-manager behavior;
- tunnel/watchdog repair policy;
- watchdog uplink probe layer semantics.

Any core-doctor uplink or `--system-resources` CLI change is an explicit G5 product
decision, not incidental refactor drift.

## 10. Exit criteria

G5 is done only when:

- core server/doctor/features/platform have zero dependency on watchdog internals;
- core CLI/stats has zero dependency on Webmin/watchdog internals;
- operational HTTP is present only to the extent required and has a pinned contract;
- watchdog/tunnel consume public contracts in the correct direction;
- server and public MCP surface work with watchdog unavailable;
- full local and production convergence is green;
- independent review approves the exact final SHA.

## 11. Test execution cadence

User steering on 2026-10-07 changes the execution cadence for the remaining
refactor. Correctness gates remain required, but broad gates are not the normal
edit/test loop.

During implementation:

- run the smallest focused tests for the files/contracts just changed;
- run only directly relevant static architecture/import checks when a boundary changes;
- when a test fails, rerun the exact failing node first;
- after a fix, rerun that node and then only the nearest affected file/subsystem;
- do not respond to one focused failure by rerunning the full suite, coverage,
  complete Python matrix, packaging convergence, or the entire machine farm.

Broad convergence is reserved for the end of the group/final candidate:

- managed full suite including the ordinary-process lane;
- coverage policy;
- supported Python matrix;
- wheel/package smoke;
- all-files quality convergence;
- exact public MCP wire parity.

Run that broad convergence once per final exact candidate SHA. If review or CI
requires a code change after convergence, repair with focused tests and then run
one fresh full convergence on the new final SHA. Do not repeatedly rerun already
green broad gates on an unchanged SHA.

Intermediate commits should use focused tests and changed-file pre-commit where
appropriate. Pre-push/exact-SHA CI are for coherent review/final candidates rather
than every small checkpoint.

## 12. Production completion — 2026-10-08

G5 runtime candidate `dd10ef0c77e87f1c8807c652e2d07188d9add6d3` completed the approved
diagnostics/operations/companion ownership work from deployed G4 completion
`b07406806ac622df00e583b0079e4b70cad76340`. The final source keeps public MCP wire
compatibility while moving diagnostic rendering/file I/O to neutral helpers, giving
the watchdog ownership of uplink diagnostics, placing optional system-resource history
behind its narrow seam, adding the fixed unauthenticated root `GET /healthz` liveness
route, and removing the reviewed companion aggregate dependencies.

The fresh final implementation-review follow-up R3 returned **APPROVE**, both remaining
operational/rollback cells PASS, with zero findings. Exact-SHA CI run `37673788380`
completed **7/7** required jobs successfully on `dd10ef0`: code quality, Python
3.10/3.11/3.12/3.14 tests, Python 3.13 coverage policy, and Python 3.13 packaging.
The already-green final local source convergence was not repeated after the
evidence-wrapper-only correction because the candidate source bytes did not change.

The canonical deployment gate completed successfully and advanced production `master`,
`origin/master`, `origin/proof-of-concept`, and the G5 implementation branch to
`dd10ef0`. The tracked user `pyproject.toml` edit was restored byte-for-byte and the
untracked-file inventory was preserved. The durable jobs service and tunnel service
were not restarted during the canonical transaction.

Post-deployment verification recorded:

- opt-in live pytest: **3 passed**;
- full deploy smoke: **exit 0**;
- core, tunnel, and watchdog doctors: **exit 0**;
- root `GET /healthz`: HTTP **200**, `application/json`, exact body
  `{"status":"ok"}`;
- four-profile public MCP wire: **141833 bytes**, unchanged SHA256
  `acbc4e794ee45c1bd9dbd3a51dafa9634f101e06ed18a0b0cea36d2f32fcb61f`;
- a real ChatGPT/Raspberry-Pi MCP `list_files` call returned the expected
  `deployment_platform.py` path.

The long-running watchdog was then activated once so it loaded the G5 companion bytes.
Its systemd invocation identity and start timestamp changed, its loaded policy changed
only the MCP liveness URL from `/mcp` to `http://127.0.0.1:8000/healthz`, the healthy
in-service uplinks remained healthy, no unexpected repair/failure event occurred during
activation, and both jobs and tunnel service identities remained unchanged. One
pre-existing ignored-adapter condition was explicitly excluded from the activation gate
by operator authorization; that exception is recorded as deployment evidence and does
not change product policy or source.

Completion evidence is retained under:

```text
/home/grammy-jiang/Projects/.binnacle-g5-r3/
```

G5 is complete. G6 production relocation/facade work may now begin from this deployed
runtime baseline, subject to its already-approved preparation constraints and final
Gate A evidence.
