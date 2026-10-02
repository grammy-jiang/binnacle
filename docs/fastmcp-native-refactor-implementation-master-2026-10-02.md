# FastMCP-native refactor — implementation master plan — 2026-10-02

Status: **Group 0 done; Group 1 validating locally; CI and deployment pending**.

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

Group 0 is complete. Group 1 is designed against the deployed stable baseline.
Detailed designs for later groups remain deferred.

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
| G1 | Composition foundation | G0 | foundational; mostly sequential | **validating** |
| G2 | FastMCP-native alignment | G1 | may overlap G3/G4 after shared seams settle | queued |
| G3 | Commands/domain/platform seams | G1; commands mount | process/resources lanes later | queued |
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

Detailed design waits for G1 because mounted child-server ownership changes the natural
place for settings, middleware, visibility and dependency construction.

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

Detailed design waits for the mounted Commands domain from G1.

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
- [ ] explicit root construction;
- [ ] Files mounted as focused child;
- [ ] Search mounted as focused child;
- [ ] Commands mounted as focused child;
- [ ] hard-coded global tool registry removed;
- [ ] no duplicate Binnacle Feature/Builder/DI/middleware/provider framework.

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

- [ ] full test suite;
- [ ] supported Python matrix;
- [ ] coverage policy;
- [ ] packaging smoke;
- [ ] architecture/import gates;
- [ ] live deployment smoke;
- [ ] current Linux deployment healthy.

Only after every item is satisfied should native macOS implementation begin.

## 18. Current next action

G1 local convergence and the fresh read-only implementation review are complete.
The next step is independent coordinating review, branch publication for exact-SHA CI,
and canonical deployment after CI succeeds.

G1 is not `done`; CI, deployment, live smoke, and the real ChatGPT read-only call
remain pending. G2-G6 remain queued.
