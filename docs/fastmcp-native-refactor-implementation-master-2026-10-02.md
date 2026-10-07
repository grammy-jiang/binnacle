# FastMCP-native refactor — implementation master plan — 2026-10-02

Status: **Groups 0-4 done; Groups 5-6 queued**.

This is the control document for the implementation-design and implementation phases of
the FastMCP-native, platform-neutral Binnacle refactor.

Architecture inputs:

- `docs/platform-neutral-architecture-design-2026-10-02.md`
- `docs/fastmcp-native-architecture-investigation-2026-10-02.md`
- `docs/fastmcp-native-refactor-high-level-plan-2026-10-02.md`

This document is intentionally not a code-level design. It owns:

- implementation groups;
- dependency order;
- allowed parallelism;
- design/implementation status;
- group entry and exit gates;
- final Gate A progress.

Each group gets its own implementation-design document only when its upstream
dependencies are stable enough to design against the current repository.

## 1. Governing rules

### 1.1 FastMCP is the framework

If FastMCP already owns a framework concern, implementation must use the FastMCP-native
mechanism.

Examples:

- composition -> `FastMCP` / `mount()`;
- component source -> `Provider`;
- component presentation -> `Transform`;
- visibility -> native visibility;
- request pipeline -> `Middleware`;
- request dependency -> `Depends`;
- runtime lifetime -> lifespan;
- negotiated protocol capability -> `ServerExtension`;
- ordinary protocol-native background work -> Tasks;
- operational HTTP endpoint -> `custom_route()`;
- protocol tracing -> OpenTelemetry.

A request to introduce a new generic Binnacle MCP framework abstraction is a design
review trigger.

### 1.2 One primary change axis per implementation step

Do not combine unrelated migrations such as:

- dependency upgrade;
- child-server composition;
- package relocation;
- platform extraction;
- diagnostics redesign;
- companion isolation.

Each change should be independently testable and independently revertible.

### 1.3 The server stays functional throughout

After every implementation step:

- the Linux MCP server must still start;
- existing public tool names and contracts remain compatible unless explicitly reviewed;
- current durable-job behavior remains usable;
- deployment remains recoverable;
- a later step must not be required merely to restore functionality.

### 1.4 Add path, prove parity, remove old path

Prefer:

```text
characterize current behavior
        |
        v
introduce new path
        |
        v
prove parity
        |
        v
switch composition
        |
        v
remove obsolete glue
```

over a big-bang rewrite.

### 1.5 Design close to implementation

Groups 0-4 are complete. Groups 5-6 remain separate planned work.

Before designing a later group:

1. finish the upstream implementation group(s);
2. re-read current code;
3. run a drift check against the architecture documents;
4. design against the repository that actually exists.

This prevents detailed downstream designs from fossilizing assumptions invalidated by
earlier refactors.

## 2. Status vocabulary

| Status | Meaning |
| --- | --- |
| queued | high-level scope exists; detailed design intentionally not started |
| designing | detailed implementation design is being written/reviewed |
| ready | detailed design accepted; implementation may start |
| implementing | code/dependency work is active |
| validating | implementation exists; convergence gates are running |
| done | group exit criteria are satisfied and integrated |
| blocked | an upstream dependency or discovered design issue prevents progress |

Status changes belong in this document.

## 3. Implementation groups

| Group | Scope | Depends on | Parallel potential | Status |
| --- | --- | --- | --- | --- |
| G0 | Stable FastMCP 4 baseline | current master | none; foundational | **done** |
| G1 | Composition foundation | G0 | foundational; mostly sequential | **done** |
| G2 | FastMCP-native alignment | G1 | domain settings lanes after shared seams settle | **done** |
| G3 | Commands/domain/platform seams | G2 deployed baseline | serialized integration | **done** |
| G4 | Deployment/platform services | G1 | logs/paths may parallelize | **done** |
| G5 | Diagnostics, operations, companions | relevant G3/G4 public seams | selected cleanup may start earlier | implementing |
| G6 | Package convergence + Gate A | G2-G5 | convergence only | queued |

## 4. Group 0 — Stable FastMCP 4 baseline

Detailed design:

- `docs/fastmcp-stable-baseline-implementation-design-2026-10-02.md`

Purpose:

- move Binnacle from the pre-GA FastMCP 4 beta baseline to one reviewed stable FastMCP
  4 baseline;
- establish that framework upgrade independently of architecture changes.

Group 0 must not introduce:

- `create_server()`;
- mounts;
- Providers/Transforms;
- visibility refactors;
- module moves;
- platform contracts.

Exit condition:

- stable FastMCP pin and targeted lock are integrated;
- public MCP surface remains pinned;
- repository/full compatibility gates are green;
- production deployment smoke is green.

### Initial local attempt — 2026-10-02

Branch `chore/fastmcp-stable-baseline` starts at
`77a04c045b74670172ae024fd108ed395979db7f` in an isolated worktree.
The dependency change is uncommitted. Only FastMCP and FastMCP-slim package
versions changed, from `4.0.0b5` to `4.0.10`. No production Python source or
MCP surface pins changed. All 90 focused compatibility tests pass.

The managed full suite, pre-push, and coverage pipeline fail at
`tests/unit/core/test_properties.py::test_full_match_agrees_with_the_stdlib`.
For path `.` and pattern `***`, Binnacle returns `False` while Python 3.13
returns `True`. The same assertion reproduces with the original
FastMCP `4.0.0b5` environment and unchanged source. This is a pre-existing
glob-matching bug, not a FastMCP compatibility failure.

Keep G0 blocked until the prerequisite bug is resolved separately and all
local gates pass. Do not weaken the property test or include an unrelated
production-source fix in the dependency change. The Group 0 design records
the local gate evidence. CI, deployment, live smoke, and an actual ChatGPT
connector call remain pending. G1 remains queued.

### Continuation status — 2026-10-02

The pre-existing glob blocker was fixed separately in prerequisite commit
`50916ef261d6fe02297e9e61de79db63fa4e27c4`. Its local gates and read-only
review passed. Branch `chore/fastmcp-stable-baseline-resume` starts directly
from that commit; primary production `master` remains at `77a04c0`.

The six reviewed G0 files were copied from the original evidence worktree.
All six files matched byte for byte before these control-status updates;
the four tracked-file diffs also matched exactly. The original G0 worktree
and prerequisite worktree remain unchanged. No production Python source is
changed by G0, and the prerequisite remains a separate earlier commit.

All required G0 local gates passed from this post-fix baseline. The complete
Python matrix passed on an unchanged repeat after the first Python 3.13 run
hit the existing job-telemetry test's startup race. The G0 design records
both runs, the investigation, and all other local gate results. No tests
were changed or skipped to obtain the passing repeat.

Fresh read-only ChatGPT review approved the G0 diff and supplied evidence,
with one non-blocking finding for the existing telemetry startup race.
The G0 design records the review. Independent review, GitHub CI, normal
deployment, live smoke, and a real ChatGPT connector read-only call remain
pending. G0 is not done; G1 remains queued.

### Completion evidence — 2026-10-02

G0 is **done** at `4608423a960bc0cba0e92e20cb8425084b76535c`, after the
separate prerequisite glob fix `50916ef261d6fe02297e9e61de79db63fa4e27c4`.
The coordinating user supplied the following final evidence:

- independent review passed;
- GitHub CI run `36997316142`: all seven required checks passed;
- canonical `deploy_smoke.py` deployment succeeded;
- production `master`, `origin/master`, and `origin/proof-of-concept` reached
  `4608423`;
- FastMCP and FastMCP-slim are `4.0.10`; MCP and MCP-types remain `2.1.1`;
- live read-only pytest: 3 passed; full post-deploy smoke: 20/20 passed;
- tunnel doctor: 9 ok/0 fail; watchdog doctor: 7 ok/0 fail;
- real ChatGPT -> deployed Binnacle read-only `list_files` succeeded.

The production document backup is retained at
`/home/grammy-jiang/.local/state/binnacle/deployment-doc-backups/20261002T105058Z-4608423.8Tiprz`.
The earlier attempt/continuation sections and the G0 design retain their
point-in-time evidence. This completion entry supersedes their pending-gate
status; the G1 design task does not repeat deployment.

## 5. Group 1 — Composition foundation

High-level scope:

- explicit root `create_server()`;
- FastMCP in-process composition tests;
- Files focused child server;
- Search focused child server;
- Commands focused child server;
- remove the obsolete `tools.register_all()` composition role.

Detailed design:

- `docs/fastmcp-composition-foundation-implementation-design-2026-10-02.md`

Design baseline: deployed G0 commit `4608423`, FastMCP `4.0.10`.
G1 implementation has resumed locally on
`refactor/g1-composition-foundation-resume-codex`, based on prerequisite
`39c806d653fe27598c9fa33cb1fc74c74530f7be`. The final design commits
`0fcb33b`, `80d5023`, and `14eded1` are replayed before the accepted implementation
checkpoints. The blocker-only `df98e4c` is not replayed. Original worktrees and
historical evidence remain available; production stays at `4608423`.

The new pre-change baseline passed 102 focused compatibility tests, architecture,
Import Linter, and strict module-size checks. Runtime versions remain FastMCP
and FastMCP-slim `4.0.10`, MCP and MCP-types `2.1.1`.

The accepted implementation predates final design `14eded1`. Checkpoint
`83b718e` completes its native local registration policy: `on_duplicate="error"`
on the root and each child, the documented internal child names, local rejection
tests, and strict synthetic cross-provider collision fixtures. There is no custom
runtime duplicate guard or lifespan. Cross-provider ownership remains a raw test
contract. All replay checkpoints and 210 focused parity/entrypoint tests passed.
Local G1.8 convergence is complete: the managed full suite, coverage policy, full
Python 3.10-3.14 matrix, wheel artifact smoke, pre-commit/pre-push, architecture,
Import Linter, strict module-size checks, and byte-identical four-profile wire parity
all passed. A fresh read-only ChatGPT implementation review returned APPROVE with no
blocking findings. Detailed evidence is in the G1 design's section 14. No remote or
production action has occurred yet.

The pinned default tool order interleaves Search between Files tools.
Three simple mounts cannot preserve that order. The design characterizes
the pinned SDK and specifies a narrow native listing Transform before the
first mount. This does not migrate client visibility, which remains G2.
Exactly three focused child servers remain the target. Files, Search, and Commands
move one at a time, with exact root-local, raw aggregate, and wire-surface contracts
at every checkpoint. Fixed factories and test-only duplicate checks replace the
earlier proposed lifespan guard. Native `on_duplicate="error"` only hardens
registration within each root/child LocalProvider; it does not enforce global
provider uniqueness. Cross-provider warning/precedence behavior remains native.
G1 preserves the current middleware order, including implicit SDK dereferencing.

Key invariant:

- composition changes only; domain implementations remain unchanged.

Expected early parallelism after root construction conventions settle:

```text
               root factory + composition tests
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
          Files        Search      Commands
```

Integration owns the small root mount changes to avoid three branches competing over the
same composition file.

## 6. Group 2 — FastMCP-native alignment

High-level scope:

- characterize and align client visibility with native FastMCP visibility;
- reduce import-time/global settings domain by domain;
- use ordinary construction injection, FastMCP `Depends`, and lifespan according to
  their native scopes;
- avoid custom framework replacements.

Detailed design:

- `docs/fastmcp-native-alignment-implementation-design-2026-10-03.md`

The design uses deployed G1 code `2725476` and documentation baseline `e86ff81`.
The two commits have identical production code, tests, dependency pins, and lockfile.
The approved design `3f300461` passed coordinator review and a fresh ChatGPT
read-only review. Implementation on `refactor/g2-fastmcp-native-alignment` passed
all local gates and final implementation review. Exact-SHA CI, canonical
deployment, live verification, and a real ChatGPT read-only call also passed.
G2 is done. Sections 19 and 20 record checkpoint and deployment evidence.

The design delegates component visibility to native FastMCP Visibility while keeping
client identity/policy and exact denied-call errors. It moves settings domain by domain
through ordinary copied construction inputs. Explicit path policy also covers nearby
file hints; existing path defaults/descriptions remain unchanged even for custom roots.
No production Depends or lifespan is added without an appropriate resource. Durable-job
ownership and platform extraction remain outside G2.

## 7. Group 3 — Commands architecture and platform seams

High-level scope:

- thin Commands FastMCP adapters;
- introduce the command-domain service seam;
- preserve current durable-job semantics;
- extract process semantics;
- extract optional resource accounting.

FastMCP Tasks do not replace Binnacle durable jobs in this group.

Potential later parallelism:

```text
             command-domain seam
                 /       \
                v         v
           process      resources
             lane          lane
```

Detailed design is reviewed against deployed `68e690d`, with the mounted
Commands domain and G2 construction snapshots. G3.0-G3.7 are locally complete
under the approved design. Section 23 records serialized platform activation
and the remaining G3.8 completion boundary; G3 is not yet complete.

Detailed execution specification:
`docs/commands-platform-seams-implementation-design-2026-10-03.md`.
Current design evidence is in section 21; earlier queued statements remain
historical checkpoint records.

## 8. Group 4 — Deployment/platform services

High-level scope:

- service-log source;
- managed-service lifecycle;
- runtime-path conventions;
- Linux implementation behind narrow contracts.

The first implementation remains Linux/systemd/journal compatible.

No launchd/macOS implementation belongs in this group.

Detailed implementation design:

- `docs/deployment-platform-services-implementation-design-2026-10-06.md`.

Design baseline is deployed G3 completion `f21f860`, whose runtime source is
identical to G3 implementation `01523d4`. ChatGPT Chat Mode completed the
current-code, UX, dependency/platform-leakage and contract design work. The
pre-design focused baseline passed 120 service-log/unit/setup/CLI/doctor/
deploy/smoke tests, the architecture checker reported zero forbidden reverse
dependencies, and the strict module-size gate had zero errors. Independent
ChatGPT design review required seven correction rounds; R8 approved the final
design with all prior findings closed. The UX decision is preservation-first:
no new public commands or required flags, no setup/mode/doctor/stats workflow
change, and no MCP surface change except the two explicitly reviewed safety
corrections. G4.1 runtime paths and G4.2 service logs are the only planned
parallel implementation lanes; lifecycle inspection, Linux provisioning and
restart/control migration remain serialized.

G4 implementation and production verification are complete. Section 26 records
the final candidate, independent review, exact-SHA CI, live checks, and preserved
working-tree evidence. The design narrative above remains the historical entry
plan.

## 9. Group 5 — Diagnostics, operations and companions

High-level scope:

- organize core/domain/platform diagnostics by ownership;
- add the minimal public operational HTTP surface using FastMCP custom routes;
- eliminate server/core reverse dependencies on watchdog reliability code;
- tighten tunnel/watchdog companion dependency direction.

Known reverse dependencies to eliminate include:

```text
doctor_connectivity -> uplink
cli                 -> webminstats
```

The server must remain fully functional with watchdog absent.

## 10. Group 6 — Package convergence and Gate A

High-level scope:

- relocate modules only after ownership boundaries are proven;
- remove temporary compatibility facades;
- strengthen Import Linter/AST architecture gates;
- full Linux regression and deployment convergence.

Illustrative final ownership:

- `features/files`;
- `features/search`;
- `features/commands`;
- `platform/linux`;
- `companions/watchdog`;
- `companions/tunnel`.

Directory movement is deliberately late.

## 11. Group dependency graph

```text
G0 FastMCP stable baseline
            |
            v
G1 composition foundation
            |
      +-----+-----+
      |     |     |
      v     v     v
     G2    G3    G4
      \     |     /
       \    |    /
        +---+---+
            |
            v
           G5
            |
            v
           G6
            |
            v
         Gate A
```

The graph is intentionally conservative.

After current-code review, selected G5 cleanup or G4 log/path work may begin before an
entire neighboring group is complete if file ownership and public contracts make that
safe.

Any such relaxation must be recorded here before parallel implementation starts.

### G4/G5/G6 parallel-preparation relaxation — 2026-10-07

The G4 final candidate `fd05b279e324235d0cf6eeddea86935de60ec1c1` has stable
G4 public seams and green local/CI convergence. To reduce calendar time while G4 final
review/deployment closes, the following **preparation-only** work is allowed in isolated
worktrees based on that exact candidate:

- G5 current-code inventory, characterization, detailed design and test planning;
- G6 ownership/relocation manifest and architecture-gate planning;
- Gate A report/harness preparation that does not change product behavior.

This relaxation does **not** authorize G5 production-source edits to G4-owned shared
modules before G4 completion, and it does **not** authorize any G6 package relocation
before G5 ownership boundaries are proven. Every prepared artifact must be drift-checked
against the exact deployed G4 completion SHA before it becomes implementation authority.

## 12. Per-group design template

Every detailed implementation-design document should define:

1. current state and evidence;
2. goal;
3. non-goals;
4. FastMCP-native mechanism involved, if any;
5. proposed responsibility boundary;
6. expected files/modules affected;
7. compatibility surface that must not change;
8. atomic implementation steps;
9. focused tests for each step;
10. group convergence gates;
11. rollback boundary;
12. parallel-safe and parallel-unsafe work;
13. documentation updates;
14. exit criteria.

## 13. Per-step acceptance rule

### Test cadence steering — 2026-10-07

For G5, G6 and Gate A preparation, broad test gates are end-of-group convergence
gates, not routine checkpoint tests. Normal implementation uses the smallest
focused tests and boundary checks relevant to the change. A failure is repaired by
rerunning the exact failing node and nearest affected subsystem, not by restarting
the whole matrix/farm. Full suite, coverage, complete Python matrix, packaging and
all-files convergence run once on a final exact candidate SHA; if that SHA changes
after review/CI, focused repair comes first and one new final convergence follows.

An implementation step is not complete because its code compiles.

It is complete when:

- focused tests are green;
- architecture/import checks relevant to the new boundary are green;
- public MCP contract pins are unchanged unless intentionally reviewed;
- no temporary broken state is required for the next step;
- the change has an obvious rollback.

Group-level full-suite gates supplement, not replace, these step-level checks.

## 14. Public MCP compatibility gate

During the structural refactor, accidental public MCP drift is a failure.

Pinned facts include:

- tool set and ordering per client profile;
- names;
- descriptions;
- input schemas;
- output schemas;
- annotations;
- server instructions;
- visibility;
- representative protocol calls.

If a FastMCP upgrade/refactor changes a hash or schema:

1. do not immediately update the pin;
2. inspect the semantic delta;
3. decide whether it is a framework compatibility bug, harmless normalization, or an
   intentional product change;
4. change the pin only with an explicit reviewed reason.

## 15. Parallel-work rules

Parallel work is encouraged only after shared boundaries are stable.

### Safe pattern

- one branch owns one responsibility;
- shared composition/config files have an integration owner;
- each branch independently passes focused tests;
- merge order is documented when changes are not commutative.

### Unsafe pattern

Several branches simultaneously redesign:

- `server.py`;
- `config.py`;
- `pyproject.toml`;
- the same job lifecycle functions;
- the same systemd/doctor primitives.

Parallelism should reduce calendar dependency, not create merge-driven architecture.

## 16. Documentation policy during implementation

Treat documents by role.

### Living control/design documents

Update when implementation state changes:

- this master plan;
- the current group's implementation design;
- current architecture documentation when a completed implementation changes a statement
  of present state.

### Historical evidence documents

Do not rewrite historical observations merely because the dependency changed later.

Examples include:

- dated usage analyses;
- dated experiment reports;
- production observation reports.

A statement that FastMCP 4.0.0b5 was installed during a September experiment remains
historically correct after G0.

## 17. Gate A progress checklist

Gate A is not reached until all are true.

### FastMCP-native composition

- [x] stable FastMCP 4 baseline;
- [x] explicit root construction;
- [x] Files mounted as focused child;
- [x] Search mounted as focused child;
- [x] Commands mounted as focused child;
- [x] hard-coded global tool registry removed;
- [x] no duplicate Binnacle Feature/Builder/DI/middleware/provider framework.

### Platform isolation

- [ ] process contract;
- [ ] optional resource-accounting contract;
- [ ] service-log contract;
- [ ] managed-service contract;
- [ ] runtime-path contract;
- [ ] product domains do not import Linux implementations.

### Companion isolation

- [ ] core doctor does not depend on watchdog uplink internals;
- [ ] core CLI/stats does not depend on watchdog Webmin internals;
- [ ] operational public surface exists where required;
- [ ] server/core/features/platform do not import watchdog implementation;
- [ ] server remains fully functional without watchdog.

### Convergence

- [x] full test suite;
- [x] supported Python matrix;
- [x] coverage policy;
- [x] packaging smoke;
- [x] architecture/import gates;
- [x] live deployment smoke;
- [x] current Linux deployment healthy.

Only after every item is satisfied should native macOS implementation begin.

## 18. Current next action

G1 is done. Exact-SHA GitHub CI run `37028183978` passed all seven required jobs.
The canonical deployment gate moved production from `4608423` to
`27254767a53a9d8b024b009a5e4c7981b479842f`; local `master`,
`origin/master`, and `origin/proof-of-concept` all reached that SHA. The live
read-only suite passed 3 tests, full post-deploy smoke passed all 20 checks with
0 doctor failures, and a real ChatGPT -> deployed Binnacle `list_files` call
succeeded.

Later documentation-only integration moved the deployment refs to `e86ff81` without
changing that behavioral baseline. G2 implementation through `6e6992f` passed
repeated full local convergence. The reviewed clean candidate `27211d1` then
passed exact-SHA CI, canonical deployment, live verification, and the real
ChatGPT read-only call. G2 is done; section 20 records the exit evidence.
G3 is validating, with local Commands/platform convergence complete.
Sections 23-24 record the integration work and stable-manager admission blocker.
Section 22 records the handoff. G4-G6 remain queued.

## 19. G2 implementation evidence

G2 implementation starts from approved design `3f300461` over deployed
`e86ff81`, in `binnacle-g2-native-alignment-impl` on
`refactor/g2-fastmcp-native-alignment`. G2.0 passed: doctor 9/0/0,
158 B+C tests, architecture, seven Import Linter contracts, strict module size,
and offline lock validation. Runtime versions remain FastMCP/FastMCP-slim
4.0.10 and MCP/MCP-types 2.1.1. The four-profile raw/wire archive and
checkpoint logs are retained outside Git at
`~/.local/state/binnacle/g2-implementation-20261002T221926Z-higemn3y/`.
G0/G1 remain done. The completed G2 deployment is recorded in section 20;
G3 remains queued.

Accepted local checkpoints (seed 12345; each also passed architecture, seven
Import Linter contracts, strict module size, and normal commit hooks):

| Checkpoint | Commit | Focused result |
| --- | --- | --- |
| G2.1 characterization | `772312a` | 171 passed |
| G2.2a unused native adapter | `6cd1ba9` | 185 passed |
| G2.2b visibility activation | `6aebc05` | 255 passed |
| G2.3 explicit roots | `266e6f8` | 408 passed |
| G2.4a Files read/write | `e83d7d2` | 412 passed |
| G2.4b Files list/edit | `add694d` | 417 passed |
| G2.5a Search arguments | `f2723e8` | 535 passed |
| G2.5b Search binding | `51a09cb` | 452 passed |
| G2.6a run-command policy | `0180ea1` | 468 passed |
| G2.6b job-status policy | `eafa1a4` | 469 passed |
| G2.7 root snapshots | `5bdee94` | 274 passed |
| G2.8 construction acceptance | `034d07f` | 305 passed |
| G2.9 edit fallback coverage | `031306f` | 421 passed |
| Review correction: status lookup | `6e6992f` | 620 passed |

All archived activation checkpoints preserve the 100,922-byte four-profile
raw/wire JSON, including instructions, order, schemas, and 8/6/6/8 tool counts.
Its SHA256 is
`308b91ffdc1fef8bafd0139b9e97b3aee11d1d5b53b95231d86c73291ec4e3c4`.
Modern authenticated HTTP characterization distinguishes per-request wire metadata
from the bare middleware listing messages after FastMCP consumes that metadata.
The shared ClientIdentity semantics remain unchanged.

The first implementation review found that the G2.6b callable binding froze
`job_status_impl` at construction, contrary to the approved scalar registration
contract. The correction passes four scalar keywords directly from Commands to
`job_status.register`; its decorated closure looks up `job_status_impl` at each
call. A deterministic post-construction replacement test failed before this fix
and passes afterward. Backend ownership and all tool metadata stay unchanged.
Only internal docstrings were shortened to keep the adapter within 500 lines;
no wait or job algorithm was changed. All local convergence gates were repeated
and passed after `6e6992f`; the original review and evidence are retained.

Remaining global settings are deliberate: token/bootstrap/config logging and
process-owned durable-job policy, spool, socket, warmup, output ceiling, and owner
remain shared. Optional direct-call and child-factory fallbacks still load cached
settings lazily. No production Depends, lifespan, duplicate validator, custom
Provider, package relocation, or dependency change is introduced.

### G2.9 local convergence

After review correction `6e6992f`, the final managed suite passed 1,763
parallel-safe tests with 4 skipped, plus 2 ordinary-process tests, seed 12345.
Offline lock check, full pre-commit and pre-push, Python 3.10-3.14 tox, and explicit clean wheel-install smoke all passed.
The wheel test passed 1 test. Coverage policy checked 100 production modules with
0 below final target and 0 errors. Architecture checked 104 modules; all seven
Import Linter contracts held; strict size checked 306 Python modules with no errors.

The first coverage attempt found `edit_file.py` at 88.69% against its 90% target.
Commit `031306f` added meaningful lazy-fallback, supplied-input precedence, and
snapshot tests. Production code and coverage policy did not change. The repeated
full convergence passed, with edit coverage at 92.26%; initial evidence is retained.

Final in-process and authenticated, uncached HTTP four-profile archives are
byte-identical to G2.0, with the SHA256 above. Repeated HTTP listing, modern/legacy
identity, exact errors, and concurrent profile tests pass without persistent
visibility rules or list-change notifications. The scope proof confirms exactly
14 planned production files, unchanged dependencies/lock/config/identity/job backend,
unchanged G1 ownership and surface contracts, and AST-identical glob fixes.

Local gate logs, exact diff against both `3f300461` and deployed `e86ff81`, runtime
versions, and complete checkpoint history are in the external evidence directory.
The second fresh ChatGPT review passed the implementation, construction, and
public/scope cells. It requested a clean committed candidate because the two
control drafts caused `+dirty` provenance in the otherwise matching wire logs.
Commit `27211d1` recorded only those two control drafts. Its clean-worktree proof
and Git object IDs confirm unchanged production, tests, build inputs, dependencies,
and policies from the fully tested `6e6992f`. Regenerated wire logs identify the
clean candidate and retain exact baseline JSON parity. The
[fresh ChatGPT review](https://chatgpt.com/c/6ac04bdd-a0dc-83ec-a15b-1a6a46005b7d)
then returned **APPROVE**, with no findings, for
`27211d1614ff77adfbb5200a8ea7cd74ca987e7b`.

## 20. G2 deployment completion — 2026-10-03

G2 is done. Reviewed candidate `27211d1614ff77adfbb5200a8ea7cd74ca987e7b`
passed all seven required checks in
[CI run 37083673343](https://github.com/grammy-jiang/binnacle/actions/runs/37083673343).
The canonical `scripts/deploy_smoke.py deploy` gate deployed that exact SHA from
`e86ff81`, reloaded the MCP service, passed smoke, and atomically updated
`master` and `proof-of-concept`. Local production HEAD and both remote deployment
refs were verified at `27211d1`. Subsequent CI runs `37084077221` on `master`
and `37084075593` on `proof-of-concept` also passed all seven checks.

Production verification passed:

- `BINNACLE_LIVE=1 uv run pytest -q tests/live`: 3 passed.
- Full post-deploy smoke: 20/20 checks passed; 12/12 calls logged; no tracebacks
  during smoke.
- Binnacle doctor: 29 ok, 2 warn, 0 fail; tunnel doctor: 9 ok, 0 warn, 0 fail;
  watchdog doctor: 7 ok, 6 warn, 0 fail.
- Runtime: FastMCP/FastMCP-slim 4.0.10; MCP/MCP-types 2.1.1.
- The durable-jobs service retained its PID, invocation ID, and start timestamp.
- All 192 unrelated production untracked files retained their sizes/checksums;
  all 14 older evidence/design worktrees retained their HEADs and file state.

The doctor warnings were inspected. Three recent request-error lines predate the
new code's configuration event at `2026-10-03T00:55:04Z`. The unchanged jobs
service reports an older provenance marker; it was deliberately not restarted.
Wireless/driver warnings are outside G2. No host-policy change was made.

A [real ChatGPT call](https://chatgpt.com/c/6ac0534f-0f54-83ec-8cec-ddfbb761448e)
used the connected Raspberry Pi MCP app to call `list_files` once for
`src/binnacle/visibility.py`. The actual ChatGPT tool-call record and the deployed
server journal share request ID `993286bd-49ed-4e3c-b36d-945998e6b65e`;
server call `38a74680a61c` recorded `client=openai-mcp`, `is_error=False`, and
one result. The returned path was the deployed `visibility.py` file.

The external evidence directory in section 19 retains review transcripts,
clean-candidate proof, CI records, deployment/live/smoke logs, runtime versions,
the real-call trace, and worktree/untracked-file inventories. This completion
record follows the same exact-SHA CI and canonical documentation deployment flow.
G3 remains queued and requires a separate design task.

## 21. G3 design ready — 2026-10-03

G3 is ready, designed against deployed documentation/code baseline
`68e690d3fd53cc8f83463a2505fe6d3829e62ea2`, after completed G2.
The isolated worktree is `binnacle-g3-commands-design`, branch
`design/g3-commands-platform-seams-2026-10-03`. This task leaves production and
older worktrees untouched. It changes only the detailed G3 design and this control
document; it does not implement or deploy G3.

The design specifies two small command use-case modules sharing a stateless
durable-backend port, independent process and optional accounting contracts,
domain-owned resource history, and the existing owner/manager/store lifecycle.
Compatibility facades keep each activation reversible. Process and resource
preparation can parallelize only after the command seam is stable; shared
activation is sequential. No Tasks, package moves, G4/G5 operational extraction,
macOS backend, schema/RPC redesign, or public MCP rebaseline is included.

External evidence:
`/home/grammy-jiang/.local/state/binnacle/g3-design-20261003T013558Z-a2ai0zhz`.
The clean baseline passed doctor 9/9, lock/runtime checks, 314 focused tests,
architecture, seven Import Linter contracts, and strict size with zero errors.
Four-profile raw surface JSON and three-tool hashes were archived. Isolated
temporary-spool/socket probes confirmed manager survival of MCP-worker exit,
shared wait/cursor/stop behavior, PID token checks, and successful execution
without accounting. Existing focused tests cover recovery, stop/prune races,
and deferred resource finalization. These are design observations, not completed
G3 implementation gates.

The design explicitly records that canonical MCP deployment does not restart
the stable job manager. Future G3 completion requires mixed-revision parity and
separately authorized quiet manager activation, including pending accounting
finalizers in the safety check. No service operation occurred during design.

The [fresh read-only ChatGPT review](https://chatgpt.com/c/6ac065bc-7ce8-83ec-9d06-83720da0f36b)
returned APPROVE: all four cells PASS, no remaining findings, and all 139 bundled
payload hashes verified. The first review's accounting-argv ownership, exact
pending-key, and manager-admission findings were corrected and re-reviewed.
Additional isolated probes verified argv-decoration parity and admission closure
with a late-arrival job deferring temporary-manager restart. Changed-doc
pre-commit passed after revisions; final status/evidence text is gated again
before commit. The external directory retains both reviews and probe/gate logs.

Production/remote deployment HEADs remain `68e690d`, with clean tracked state.
Concurrent untracked document additions and updates under
`docs/chatgpt-mcp-development/` were left alone and are recorded separately in
before/after preservation evidence. No source/test/dependency
edits, push, deployment, or production service operation occurred.

G3 is ready, not implementing or done. The coordinator independently reviews
this design commit before starting a separate implementation task. G4-G6 remain
queued.

## 22. G3 serial command seam implementation

G3 is implementing under the user's approved design at `78954f0`. The dedicated
worker owns G3.0-G3.2d only, on `refactor/g3-commands-platform-seams` in
`binnacle-g3-commands-impl`. The required handoff is a clean committed G3.2d
freeze, with external manifests for separate G3.3 and G3.5a preparation lanes.
No push, deploy, platform activation, or G4-G6 work is authorized in this worker.

G3.0 passed 386 focused tests, architecture, seven import contracts, strict size,
doctor, lock/runtime checks, and isolated lifecycle/accounting probes. Public
wire, archived baseline source, spool fixtures, and the checkpoint ledger are
retained at
`~/.local/state/binnacle/g3-implementation-20261003T030542Z-m481gfu3/`.
Section 15 of the detailed G3 design records the current implementation evidence.
Production and remote deployment refs remain `68e690d`; G4-G6 remain queued.

The serial worker has completed G3.0-G3.2d and stops at the clean freeze commit.
Run, status, and stop now use one explicit stateless backend per Commands child.
MCP adapters retain only conversion, policy/path inputs, and late-bound call
lookup. The durable engine and both platform implementations remain unchanged.

Acceptance includes 540 focused tests, full pre-commit/pre-push, the managed full
suite (1,840 parallel-safe plus two ordinary-process tests), coverage policy
(104 modules, zero errors), nine import contracts, strict size, exact wire and
message parity, and both mixed-revision directions. Three final registration
fallback tests close the measured coverage gap and pass in the repeated full
coverage run. No golden, dependency, lock, persisted format, or protected G0-G2
behavior changed.

The detailed design section 15 and external ledger contain checkpoint evidence.
External `process-prepare-G3.3.json` and `resource-prepare-G3.5a.json` bind both
preparation lanes to the exact clean freeze SHA. Their shared files, including
`job_platform.py`, remain integrator-owned. Neither lane was implemented here.
There was no push, deployment, or production service operation. G3 stays
implementing; G3.3/G3.5a dispatch and later serial activation belong to the
coordinator. G4-G6 remain queued.

## 23. G3 platform integration and activation

The user authorized continuation from `ad2a9c4` after independent review of both
prepare lanes with no material findings. The single integrator preserved
`767366f` and `d96d440`, composed their unused providers in `a66d135`, and committed
G3.4a `63e8d97`, G3.4b `0d218d8`, G3.5b `1558afc`, and G3.6 `5a2d42b` serially.
G3.7 adds narrow static boundaries and retained-facade documentation. Its focused
suite passed 743 tests, all 15 import contracts passed, and the exact public wire
archive remains unchanged. The detailed design section 16 contains gate counts,
ordinary failure resolutions, scope evidence, and the external ledger location.

G3 remains validating. G3.8 still requires complete convergence, fresh final
implementation review, exact-SHA CI, canonical deployment, actual stable-manager
revision verification, and live/ChatGPT verification. Production ancestry shows
that the current implementation worker itself runs as manager-owned durable job
`cc667870d56e`. Restarting that manager before this job settles is unsafe. A worker
outside the manager-owned job must perform the approved exclusive admission/drain
barrier and activation after this worker exits. Do not kill the job or claim G3
done while the old manager remains active. G4-G6 remain queued.

## 24. G3 local convergence

Local convergence passed on the clean production source tree reviewed in
`017c19c`. The managed Python 3.13 suite passed 2,043 parallel-safe tests and both
ordinary-process tests. Pre-push passed. Coverage passed all 107 production
modules with no module below target. The Python 3.10-3.14 managed matrix, explicit
wheel artifact test, both archived mixed-revision directions, and exact
four-profile wire comparison passed. The only convergence correction is
`e7f32e4`: a cursor-only reload fixture explicitly requests zero wait to avoid
spending its child-process budget on an unrelated default status wait under
coverage. Its lifecycle/wait/cursor regressions passed unchanged.

The fresh independent source review approved cells 1-3 without findings at
<https://chatgpt.com/c/6ac08d47-b018-83ec-9856-e4393730876a>. Final gate evidence
is submitted for cell 4 and exact-candidate implementation approval before CI
publication. The detailed design section 17 records this checkpoint. CI,
canonical deployment and live results remain separate evidence; the actual
stable-manager restart is blocked until this manager-owned worker settles and
an outside operator establishes the approved admission/drain barrier. G3 is
not done, and G4-G6 remain queued.

## 25. G3 production completion — 2026-10-05

G3 implementation `01523d406732dddf1421eabd93269ad09c25e5ea` passed all seven required checks in
[CI run 37103424140](https://github.com/grammy-jiang/binnacle/actions/runs/37103424140)
and was deployed through the canonical gate. The
[final implementation review](https://chatgpt.com/c/6ac08d47-b018-83ec-9856-e4393730876a)
approved all four cells without findings. Earlier blocker entries above are
historical evidence, not the current activation state.

An operator outside the durable-job service applied section 13.1 after the
user's final GO. The evidence records the quiet inventory, complete admitted-call
drain, closed HTTP admission, second empty job/accounting/RPC check, and clean
service shutdown. No user job was killed by this activation. The manager now
reports PID `3051275`, owner instance `cf8e6dd699c445fa8d772a610ce6785e`,
protocol 1, and loaded code revision `01523d406732`. MCP admission was
restored after that identity was verified. A controlled temporary job proved
new-owner routing, completion, output, and the recorded accounting/history path.

The opt-in live pytest suite, full smoke, server doctor, tunnel doctor, and
watchdog doctor passed their repository exit gates. The external logs preserve
all warnings rather than hiding them. Runtime remains FastMCP/FastMCP-slim
4.0.10 and MCP/MCP-types 2.1.1. Four-profile wire JSON is byte-identical to the
141833-byte baseline, SHA256
`acbc4e794ee45c1bd9dbd3a51dafa9634f101e06ed18a0b0cea36d2f32fcb61f`.
A [real ChatGPT read-only call](https://chatgpt.com/c/6ac42810-eae8-83ec-8ff7-212bb26273ce) returned
`src/binnacle/job_platform.py`. Its actual connector request and successful
production journal result share the same request identifier.

External, timestamped evidence and failure/recovery records are retained at:

```text
/home/grammy-jiang/.local/state/binnacle/g3-closure-20261005T130745Z-o9x1d56k/unattended/runs/20261005T224110Z-lrfpti90
```

The unrelated production `pyproject.toml` edit was checksum-backed up and
temporarily held for the clean activation/deployment boundary. The wrapper
restores its exact original bytes on exit and never includes it in this commit.
Untracked documents are inventoried and left in place. The final external
report verifies restoration and deployment refs. This two-document completion
record follows new exact-SHA CI and the canonical documentation deployment;
it changes no production source, dependency, job protocol, or durable schema.
The manager keeps its verified code revision across the later documentation
commit; that commit has identical runtime source. G4-G6 remain queued.

## 26. G4 production completion — 2026-10-07

Implementation candidate `c954701ed6691f4749274ea8d7ffc0ce3ec9eb08`
completed the G4 extraction from deployed G3 completion `f21f860`.
Service logs, managed-service inspection/control, Linux provisioning, and
runtime-path conventions now use the approved narrow boundaries. Existing
compatibility facades remain where the design requires them. There is no
MCP surface, dependency/lock, durable-job protocol, or on-disk schema change.
G5/G6 implementation is not part of this completion.

The [fresh independent implementation review](https://chatgpt.com/c/6ac6293e-798c-83ec-b4cd-0c9afefd9586)
returned **APPROVE**, all four cells PASS, and no findings. It reviewed the
complete 43-file diff and closed the previous architecture-detector findings.
Its isolated negative probes caught generic-runner command argv and procfs-root
construction. The reviewer did not claim to run the repository test suite.

[CI run 37613814638](https://github.com/grammy-jiang/binnacle/actions/runs/37613814638)
passed all seven required checks on that exact candidate: code quality,
Python 3.10/3.11/3.12/3.14 tests, Python 3.13 coverage policy, and Python 3.13
packaging. These jobs use the managed test lanes and repository gates. The
recovery run also passed 41 focused review-regression tests, changed-file
pre-commit, and the normal pre-push hook. Prior full local convergence on
`fd05b27` is retained as predecessor evidence; `fd05b27..c954701` changes only
three test files. No fresh local full matrix was claimed or repeated during
this closeout. Current-candidate matrix/coverage/packaging evidence is the
exact-SHA CI run above.

An additional read-only operator check extracted both `f21f860` and `c954701`
from Git. All 15 setup/mode/doctor/stats/token scenarios had byte-identical
stdout/stderr and equal exit codes, including help, invalid arguments, setup
dry-run, mode status, local doctor, and a fixed historical stats window.
Mutating token rotation was not run on production. Its reviewed failure
semantics remain covered by the focused regression tests.

The canonical `scripts/deploy_smoke.py deploy c954701...` gate completed on
2026-10-07. It loaded the candidate, passed its live smoke, and atomically
advanced production `master` and `origin/master` plus `origin/proof-of-concept`
to the implementation candidate. The implementation branch also pointed there.
The stable jobs service was not restarted: PID `3051275` and its systemd
invocation identity remained unchanged.

Post-deployment evidence:

- Opt-in live pytest: **3 passed**.
- Full smoke: **20 checks passed**, with no alert or traceback.
- Core doctor: **31 ok, 1 warn, 0 fail**. The warning records the intentionally
  retained manager revision `01523d406732`; it is not a manager restart request.
- Tunnel doctor: **9 ok, 0 warn, 0 fail**.
- Watchdog doctor in full smoke: **7 ok, 6 warn, 0 fail**. The retained warnings
  concern existing wireless preferences/demotion, tunnel log silence, and an
  old driver stability sample. Network probes separately passed. No watchdog
  or network repair was folded into G4.
- Runtime versions: FastMCP/FastMCP-slim **4.0.10**, MCP/MCP-types **2.1.1**.
- Four-profile live MCP JSON: **141833 bytes**, byte-identical to the frozen
  baseline, with **8/6/6/8** tools. SHA256:
  `acbc4e794ee45c1bd9dbd3a51dafa9634f101e06ed18a0b0cea36d2f32fcb61f`.
- A [real ChatGPT read-only call](https://chatgpt.com/c/6ac62f40-8c1c-83ec-8a19-a2fadb0c23c2)
  returned `src/binnacle/deployment_platform.py`. The actual connector call,
  successful result, and production journal share request ID
  `36e55f8d-95fb-49c2-9e38-8027882b8346`.

The external evidence directory contains the exact review materials, checksums,
CI response, deployment log, CLI outputs, live wire archive, and correlated
ChatGPT proof:

```text
/home/grammy-jiang/.local/state/binnacle/g4-unblock-20261007T111035Z-bdvlz9sp
```

The unrelated production `pyproject.toml` edit was backed up, verified,
temporarily held for the clean deployment gate, then restored byte-for-byte
with its original mode. Its SHA256 remains
`c11949785cc1cac2d4994e6e7bc9bba5c9392a1095b873d41ec6612013a40d9d`.
All **440** untracked files retained the same path, bytes, mode, and type.
The completion commit contains only this design document and the master
control document. Its publication requires its own exact-SHA CI and canonical
documentation deployment; the external ledger records those later transaction
results without claiming a new runtime change or restarting the jobs manager.

## G5 implementation entry — 2026-10-07

The deployed G4 completion is `b074068`. G5 design revision 2 passed all four
independent review cells with no findings:
<https://chatgpt.com/c/6ac6383c-dd54-83ec-be77-3b688670053c>.
The isolated implementation branch starts from the deployed baseline plus the
reviewed design. G5.0 has 191 passing focused tests, clean architecture/import/size
gates and identical four-profile wire bytes. Implementation may proceed in green
G5.1-G5.5 checkpoints. G6 runs preparation checks in parallel; package relocation
and facade deletion remain deferred until G5 is deployed and verified.
