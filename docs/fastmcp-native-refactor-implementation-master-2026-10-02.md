# FastMCP-native refactor — implementation master plan — 2026-10-02

Status: **Groups 0, 1, and 2 done; Group 3 ready; Groups 4-6 queued**.

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

Groups 0, 1, and 2 are complete. Group 3 has a reviewed detailed design against
the deployed post-G2 baseline. Detailed designs for Groups 4-6 remain deferred.

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
| G3 | Commands/domain/platform seams | G2 deployed baseline | process/resources lanes later | **ready** |
| G4 | Deployment/platform services | G1 | logs/paths may parallelize | queued |
| G5 | Diagnostics, operations, companions | relevant G3/G4 public seams | selected cleanup may start earlier | queued |
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
Commands domain and G2 construction snapshots. G3 is ready for coordinator
review of the design commit. Implementation starts in a separate task; this
status change does not deploy or implement G3.

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
G3-G6 remain queued. No G3 work has started.

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
