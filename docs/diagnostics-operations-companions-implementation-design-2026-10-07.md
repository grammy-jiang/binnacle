# G5 diagnostics, operations and companions — implementation design draft — 2026-10-07

Status: **parallel investigation/design draft only; not yet approved for implementation**.

Baseline: G4 final candidate `fd05b279e324235d0cf6eeddea86935de60ec1c1`.
This worktree is intentionally isolated from the G4 closeout. No G5 production-source
change is allowed to merge until G4 is deployed, the final G4 SHA is known, and this
design is drift-checked against that deployed baseline.

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
- `ops/watchdog/services.py` imports `tunnel_doctor`; G5 must decide whether this
  is an intentional companion-to-companion public contract or an implementation
  dependency to remove.
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
should either make unauthenticated local liveness explicit or add handler-level auth;
it must not assume MCP endpoint authentication applies automatically.

The path, authentication choice and exact JSON remain subject to independent G5 design
review. This section narrows the problem; it does not authorize implementation before
G4 closes.

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
- watchdog service state;
- Webmin resource-history diagnostics if retained.

The existing `check_uplink` behavior must be moved/owned here without changing its
layer semantics or failure classifications.

### 6.3 Shared diagnostic contracts

`doctor_contracts.py` remains the natural minimal shared result contract
(`Check`, status helpers). Companions may consume this contract.

Do not make `doctor.py` itself a shared API. Compatibility aliases used by companions
must be eliminated or redirected before G5 exits.

### 6.4 Stats / system resource history decision gate

The current `binnacle stats --system-resources` UX must be characterized before an
implementation choice.

Two acceptable design directions remain open for independent review:

- **preserve the flag** behind an ordinary system-resource-history contract with an
  optional concrete contribution selected outside core CLI logic; or
- **move the host-specific report to the watchdog companion**, retaining an explicit
  compatibility/deprecation path if required.

Do not keep `cli.py -> webminstats.py` merely to preserve implementation history, and
do not invent a generic plugin framework only for this flag.

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

- resolve the section 6.4 decision;
- remove `cli.py -> webminstats`;
- preserve or deliberately migrate user-visible behavior with focused CLI tests;
- add static gate forbidding core CLI/stats -> watchdog Webmin internals.

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

- replace watchdog/tunnel imports of core aggregate implementation with stable public
  contracts/helpers;
- classify and remove accidental companion-to-companion implementation imports;
- strengthen Import Linter/AST rules.

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
