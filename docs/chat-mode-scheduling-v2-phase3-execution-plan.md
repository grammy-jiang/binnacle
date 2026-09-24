# Chat mode scheduling v2 — Phase 3 offline replay execution plan

Status: **PLANNED; NOT STARTED**

This is the authoritative execution document for Phase 3 only. A cold-start
agent should read this file, the short Phase 3–6 index, and the referenced
upstream evidence. It should not need the Phase 4/5/6 plans to execute Phase 3.

Phase 3 purpose: replay historical wait evidence against C120/C300/C600/H10,
reject bad budgets before live ChatGPT trials, and prepare the scenario/provenance
infrastructure required by Phase 4.

## Dependency summary

| Dependency | Must be true before Phase 3 implementation |
| --- | --- |
| Phase 2 | Complete including 2.12a; guard/report/CI green |
| Test efficiency | Final accepted checkpoint complete and CI green |
| Stack history | Phase 0 -> Phase 1 -> Phase 2 ancestry intact; Phase 2 includes final test-efficiency maintenance and is fresh vs public base |
| Test runner | Final optimized test/coverage commands identified |
| Production | Observed and preserved; scheduling-v2 still undeployed |

Phase 3 produces the canonical replay corpus, C120/C300/C600/H10 results, live
candidate shortlist, missing R4/R6/R10/R12 manifests, timeout-provenance
classifier, and a Phase-4 readiness handoff.

## Required references

Read before Step 3.0:

- `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md` — short cross-phase index/dependency DAG;
- `docs/chat-mode-scheduling-v2-design.md`;
- `docs/chat-mode-scheduling-v2-ab-plan.md`;
- `benchmarks/chat-mode-scheduling-v2/METRICS.md`;
- the previous phase's canonical progress and final report identified by Step 3.0.

Do not read later-phase execution plans unless you are coordinating cross-phase
planning; they are not execution prerequisites for this phase.

## Execution contract shared by all later phases

This phase document is self-contained for execution, but it does not redefine
upstream evidence. Metric arithmetic remains authoritative in
`benchmarks/chat-mode-scheduling-v2/METRICS.md`; frozen confirmatory thresholds
remain authoritative in `docs/chat-mode-scheduling-v2-ab-plan.md`; server-guard
semantics remain authoritative in `docs/chat-mode-scheduling-v2-server-guard.md`.

### Orchestrator and dynamically parallel workers

There is **no plan-imposed numeric limit** on concurrent ChatGPT worker sessions.
The user's environment is known to support multiple simultaneous chats; four is a
proven minimum capability, **not a ceiling**. The orchestrator/task manager is a
coordination role and does not consume or reserve a worker slot in this design.

The orchestrator maintains a dependency-driven **ready queue**. A task is ready
when all of its declared predecessors are complete and every required immutable
input hash is frozen. At every scheduling event it must:

1. enumerate **all** ready tasks, not only a fixed-size batch;
2. launch every ready task whose write/resource locks do not conflict with an
   already-running task and whose live-resource class is inside the currently
   qualified capacity envelope;
3. when **any** worker completes, validate its declared outputs/commit, release
   its locks, recompute the DAG immediately, and launch newly ready tasks without
   waiting for unrelated workers in the earlier batch;
4. keep independent blocked tasks from preventing unrelated ready work;
5. continue this refill process until the next genuine fan-in/dependency barrier.

Therefore terms such as "wave" or "parallel stage" in this document identify a
**dependency frontier**, not a fixed number of sessions and not a rule that all
workers in that frontier must start/finish together. If eight independent tasks
are ready and the actual environment can support eight safely, launch eight. If
additional tasks become ready while those eight run, launch them immediately when
their resource constraints allow.

The orchestrator exclusively mutates **canonical coordination state**:

- this phase's canonical progress JSON/Markdown;
- dependency-audit artifacts;
- integration-branch history;
- final phase verdict/report;
- any global deployment/cutover decision record.

External resources are not automatically global locks. The orchestrator may
delegate mutation of **disjoint** Projects, connector profiles, endpoints, or
review artifacts to parallel workers by assigning an exclusive resource id to
each worker. For example, `project-mutate:rp-sched-A` and
`project-mutate:rp-sched-C300` may run concurrently, while two workers may never
hold the same Project/connector/endpoint mutation lock. Primary/staging deployment
cutovers remain orchestrator-controlled because they affect shared runtime state.

Workers use separate worktrees/branches or explicitly read-only scratch state and
only the ownership assigned by this document. A code/evidence worker ends with a
clean committed branch and reports its commit hash plus input/output hashes. The
orchestrator integrates commits serially when they target the same integration
branch, but worker execution before that fan-in is maximally parallel.

#### Single-writer orchestrator ownership and handoff

Exactly **one orchestrator owner** may mutate Phase-3 scheduler/progress/
integration state at a time. Unlimited worker sessions do not imply multiple task
managers.

Persist ownership outside Git at:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase3/orchestrator-owner.json
```

Schema:

```text
orchestrator_id        # generated UUID/opaque label for one orchestration tenure
orchestrator_epoch     # monotonically increasing integer
claimed_at
last_checkpoint_at
last_state_sha256
status = active | handing_off | superseded
```

Ownership never expires merely because time passes; a stale clock must not create
two writers. A replacement orchestrator first performs the recovery investigation,
reads the current task/progress/external state, marks the old owner `superseded`,
increments `orchestrator_epoch`, writes a new owner record atomically, and only
then mutates scheduler/progress state. Record the new epoch at the next canonical
checkpoint.

Every assignment/completion packet and task attempt records the epoch under which
it was issued. A worker may finish an old-epoch attempt after orchestrator handoff;
the new orchestrator validates its task/attempt/input/output hashes before
accepting it. The superseded orchestrator, if it resumes, must detect the epoch
mismatch and become read-only; it may not launch tasks, acquire locks, integrate
commits, or update progress.

#### Worker assignment and completion packets

The orchestrator communicates work through persistent local packets so a worker
chat needs no prior conversation memory:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase3/assignments/
  <task_id>--<attempt_id>.json
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase3/completions/
  <task_id>--<attempt_id>.json
```

Assignment packet contains the full task descriptor, orchestrator epoch, exact
worker branch/worktree or scratch root, input hashes, predecessor evidence,
resource locks already reserved by the orchestrator, expected outputs, validation
commands, stop point, and prohibited shared mutations. The worker treats this
packet plus the referenced runbook section as authoritative.

The worker never edits `orchestrator-state.json`, `orchestrator-owner.json`, or
canonical progress. On completion it atomically writes the completion packet with
output/commit/test hashes and reports the same information to the orchestrator.
The orchestrator validates the packet before transitioning the task to complete
and releasing locks.

How a ChatGPT worker session is opened/assigned is outside the repository task
graph; the plan does not assume the orchestrator can programmatically create chat
sessions. The shared assignment/completion protocol makes any available worker
session interchangeable and cold-start safe.

#### Resource-lock model

The scheduler uses **resource identities**, not session-count limits. A worker
declares the smallest relevant set, for example:

```text
git-write:<worker-branch>
artifact-write:<path>
project-mutate:<project-id>
connector-mutate:<connector-or-profile>
endpoint-config:<endpoint-id>
staging-deployment
primary-deployment
canonical-progress
canonical-integration
```

Read-only use of immutable evidence does not conflict. Two workers may run in
parallel when their write/resource identities are disjoint. A shared resource is
serialized only for the period actually required; do not serialize an entire
phase merely because one later action is exclusive.

#### Task-granularity / work-conservation rule

Maximize **useful** parallelism, not worker count for its own sake. Create a
separate worker task when the work has all of these properties:

- its predecessors/input hashes can be frozen independently;
- it owns a disjoint output path or is read-only;
- it has a meaningful validation/check that can succeed/fail independently;
- completing it can unblock downstream work, reduce critical-path latency, or
  materially shorten a large scan/analysis by sharding;
- worker startup/integration overhead is small relative to the work saved.

Good split dimensions are source document/report, endpoint/Project, scenario or
trial block, metric family, time window, independent service/config check, or
independent artifact verification. Do **not** split a short sequential operation
into artificial microtasks that all write the same file, require constant
cross-worker conversation, or must immediately fan back into one tiny edit.

The orchestrator may coalesce trivially small ready tasks that share the same
read-only inputs/output owner when doing so lowers overhead without delaying any
other downstream task. This is an efficiency decision, never a fixed worker cap.
Conversely, a large worker should be split further when an independent shard can
produce a separately verifiable output and reduce the critical path.

#### Live-resource admission control

CPU/network/tunnel/browser limits are **measured runtime constraints**, not fixed
chat-count rules. Live benchmark/deployment tasks declare a live-resource class.
The orchestrator admits as many as the current qualification/health evidence
supports and stops increasing concurrency when correctness, routing, dispatch,
load, throttling, or interruption criteria fail. A later section may define a
special stricter admission rule for performance timing; that rule limits only the
contended live resource, not unrelated analysis/code/review workers.

#### Machine-readable task graph contract

Each phase materializes one canonical **stable task graph** before launching its
first implementation/live worker:

```text
benchmarks/chat-mode-scheduling-v2/phaseN-task-graph.json
```

`N` is the phase number. The Git-tracked graph contains static DAG nodes plus
**dynamic task templates**, not every transient worker instance. It changes only
when the dependency design/template itself changes. Schema:

```text
schema_version
phase
source_head
revision
static_tasks[]:
  task_id
  task_kind
  predecessor_ids[]
  required_input_artifacts[] + sha256
  resource_locks[]
  expected_output_paths[]
  side_effect_class
  external_gates[]
  enabled_condition | null
  required_for_phase = true | false
  scheduling_class = critical | normal | opportunistic

dynamic_templates[]:
  template_id
  expansion_source
  task_id_pattern
  predecessor_rule
  resource_lock_pattern
  output_path_pattern
  side_effect_class
  external_gates[]
  required_for_phase = true | false
  scheduling_class = critical | normal | opportunistic
```

Static task ids come directly from the phase dependency table. Dynamic fan-out
instances (source shards, endpoint readiness tasks, calibration trials, review
partitions, discovered Projects, extension-window reviews) are instantiated from
these templates at runtime with deterministic ids; they are **not appended to the
Git task-graph file for every launch**.

High-frequency scheduler state lives outside Git at:

```text
~/.local/state/binnacle/chat-scheduling-v2/phaseN/orchestrator-state.json
```

Use directory mode `0700` and atomic file replacement. It records instantiated
ready/claimed/running/completed/blocked tasks, attempts, worker branch/scratch
paths and current resource locks. This file may change on every scheduling event
without creating a Git commit or serializing unrelated workers.

Canonical progress stores only the stable graph path/revision/SHA plus compact
checkpoint summaries. At dependency barriers, side-effect boundaries, recovery
checkpoints and phase handoff, persist a compact task-ledger snapshot under
`benchmarks/chat-mode-scheduling-v2/` containing completed task ids and their
input/output hashes. Do not commit every ready/running transition.

Before accepting a new graph revision, the orchestrator validates mechanically:

1. graph is acyclic;
2. every predecessor id exists or is a documented completed prior-phase handoff;
3. every enabled task's required immutable input hash exists;
4. no two concurrently enabled tasks claim the same exclusive output path;
5. every shared/external mutation has an explicit resource lock;
6. every non-artifact prerequisite such as explicit owner approval is declared as
   an `external_gate`, not disguised as a missing task id;
7. no task depends on a later-phase artifact;
8. every fan-in names the exact canonical artifacts/verdicts required for release;
9. dynamic instances have unique deterministic ids and output paths.

Progress stores `task_graph_path`, `task_graph_revision`, and `task_graph_sha256`.
Any **stable graph/template** change after work has started creates a new revision
and records the reason. Runtime instantiation/claim/refill updates only local
orchestrator state and does not revise the Git graph. Existing completed/running
task identities are never silently rewritten. If a stable graph revision changes
predecessors/locks/outputs of an already submitted or side-effectful task, the
phase is blocked for investigation rather than adapting in place.

The Markdown runbook remains authoritative for semantics; the JSON makes the
orchestrator's dependency/parallel execution mechanically auditable and
recoverable by a new AI agent.

Task-graph materialization is part of **Step 3.0**, not a later implementation
step. After the formal dependency preflight has enough information to establish
the Phase-3 workspace and enabled conditions, but **before Step 3.0 is marked
complete or any Phase-3.1+ worker is launched**, the orchestrator must:

1. render `phase3-task-graph.json` revision `r01` from this runbook and the
   audited predecessor/handoff identities;
2. run all graph validations listed above;
3. record graph path/revision/SHA in canonical progress;
4. initialize `~/.local/state/binnacle/chat-scheduling-v2/phase3/orchestrator-state.json`
   with the static ready/blocked state implied by the graph;
5. freeze a checkpoint of that initial local state and record its SHA/time;
6. only then mark 3.0 `complete` and allow the ready-queue scheduler to launch
   Phase-3.1+ work.

If the dependency audit is BLOCKED before a valid source/workspace can be chosen,
do not invent a task graph from uncertain inputs. If the graph validator fails,
Step 3.0 is BLOCKED even when every upstream dependency itself passed.

#### Task identity, claim, and recovery contract

Every parallel task has a deterministic `task_id` derived from phase + logical
work unit, never from a chat/session number. Examples:

```text
p3-source-phase1-step3
p3-audit-phase1-step3
p3-candidate-c300
p4-readiness-c300
p4-calibration-c300-r7-repeat2
p4-confirmatory-r3-repeat4
p5-review24-blocking-exhaustion
p6-t7d-efficiency-job-status-call-burden
```

Before launch, the orchestrator writes a task descriptor into progress/scratch
state containing:

```text
task_id
predecessor_ids[]
input_artifacts[] + sha256
source_head / worker_base_head
required_resource_locks[]
external_gates[]
expected_output_paths[]
worker_branch/worktree or scratch_root
focused_test/validation command when applicable
side_effect_class = none | disposable | shared_external
attempt_id
claim_id
forbidden_actions[]
state = ready | claimed | running | complete | blocked | abandoned | disabled
```

`attempt_id` is unique per launch attempt; `claim_id` uniquely identifies the current ownership claim for that attempt; `task_id` stays stable across retries.

Conditional nodes use `enabled_condition` from the stable task graph. When a
condition becomes definitively false, set that task instance to `disabled`; a
disabled task is terminal for DAG accounting and does **not** block downstream
`one_of`/conditional fan-ins. Never mark a skipped conditional branch `complete`
merely to satisfy the graph.

`required_for_phase=false` is reserved for **opportunistic optimization work** whose
absence cannot change correctness, required evidence, or a deployment verdict. Such
a task may be set `disabled` with a recorded scheduler reason such as
`critical_path_priority`, `no_idle_live_host_window`, or `no_remaining_work_to_accelerate`.
It must never appear in a required `all_of`/`latest_enabled` fan-in. If an
opportunistic result is reused later, the consumer validates its input/criteria
hashes exactly like any other cached result.

`scheduling_class=critical` means the task directly unlocks/advances the current
critical path; `normal` is required but not immediately critical; `opportunistic`
is optional latency-hiding/capacity-refinement work. The ready-queue scheduler
uses this class only for priority when tasks contend for the **same** scarce
resource; it does not reduce concurrency among disjoint tasks.

Conditional fan-ins must name their rule explicitly rather than listing mutually
exclusive predecessors as an unconditional AND. Supported runbook semantics are:

```text
all_of: every enabled predecessor must complete
one_of: exactly one eligible predecessor path must complete with the required verdict
latest_enabled: the latest enabled decision node in an extension chain supplies the verdict
```

The orchestrator evaluates conditions only from frozen canonical verdicts/hashes,
never from worker guesses. Once a side-effectful downstream task is launched, the
condition/verdict that enabled it is immutable unless the phase is rolled back and
re-audited.
The orchestrator allocates the task attempt's unique `claim_id` and atomically claims **all** required resource locks before changing `ready -> claimed`. Workers never partially acquire locks or wait while holding a
subset; this avoids lock-order deadlocks. If the complete lock set is unavailable,
the task remains ready and other tasks continue.

A worker completion packet must return:

```text
task_id + attempt_id
input hashes actually consumed
claim_id
output paths + hashes
commit hash / clean worktree status when Git-backed
tests/validation result
external side effects performed (normally none unless explicitly assigned)
known blocker/limitation
```

On orchestrator/chat recovery, any task left `claimed`/`running` is **investigated
before re-launch**. Check worker branch/worktree, expected outputs, background
processes, submitted-trial evidence, Project/connector/service state and external
side effects as applicable. A new attempt is allowed only after the old attempt is
proved complete, proved not to have executed the side effect, or is explicitly
marked `abandoned` with evidence. For canonical live trials, existing submission
evidence always wins: never create a replacement attempt for a submitted slot.

Read-only deterministic analysis may be recomputed after an abandoned attempt, but
its new attempt must use the same frozen input hashes. Shared-external mutations
are never blindly retried. If an abandoned/superseded worker later returns, its
completion packet is quarantined because its `claim_id` no longer owns the task;
it cannot overwrite or release locks belonging to the newer attempt.

#### Progress/checkpoint fields for parallel scheduling

High-frequency `ready/claimed/running/resource-lock` state lives only in the
persistent local `orchestrator-state.json` described above. Canonical Git progress
must **not** be rewritten for every worker launch/completion; that would turn Git
into the scheduler bottleneck.

At canonical checkpoints (dependency fan-in, side-effect boundary, recovery
checkpoint, evidence freeze, or phase handoff), progress records a compact
scheduler snapshot:

```text
task_graph_path
task_graph_revision
task_graph_sha256
orchestrator_state_path
orchestrator_state_checkpoint_sha256
orchestrator_state_checkpoint_at
ready_count
claimed_count
running_count
blocked_count
running_task_ids_at_checkpoint[]
completed_task_count
completed_worker_commits_since_checkpoint{}
blocked_task_summary{}
```

The checkpoint SHA refers to an immutable copy of the local scheduler state made
at that checkpoint, not to a continuously changing file. A cold-start
orchestrator loads canonical progress/task-graph first, then the current local
state if present, and reconciles it against worker branches/processes/external
side effects using the task-recovery contract. Missing local state does not erase
committed task evidence; reconstruct from the most recent checkpoint plus worker
outputs/branches.

Workers never edit canonical progress concurrently. The orchestrator batches
normal read-only worker completions into the next meaningful checkpoint, while
side-effectful/submitted live tasks still use the explicit pre-action checkpoints
defined in this runbook.

### Dependency-audit preflight fan-out

Step 3.0 is the only orchestration stage that runs **before** the formal
Phase-3 task graph exists. It therefore uses a tiny bootstrap scheduler state,
not the normal phase graph/runtime state:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase3/bootstrap-state.json
```

Use directory mode `0700` and atomic replacement. Bootstrap task ids are the
fixed `preflight-*` ids below plus any deterministic read-only child shards
created from them. The bootstrap state records ready/claimed/running/complete/
blocked preflight tasks, attempts and read-only resource identities. It never
contains implementation/live/deployment tasks.

Step 3.0 is a fan-in gate, but its **read-only investigations are independent
worker tasks** and should be launched concurrently whenever their inputs are
available. The orchestrator should normally fan out at least these categories,
adapted to the phase-specific N.0 requirements:

```text
preflight-git-lineage          # branch ancestry, dirty/diverged worktrees, public-base freshness
preflight-previous-artifacts   # progress/report/handoff paths + SHA verification
preflight-previous-ci          # recorded evidence CI + current closeout HEAD CI
preflight-test-tooling         # authoritative runner/coverage/benchmark tooling identity
preflight-production-state     # read-only master/service/config/unit observation
preflight-external-control     # auth, Projects/connectors/tunnel control plane when relevant
preflight-runtime-state        # relevant staging/endpoint/process identity when relevant
```

There is no fixed worker count: split a category further when that produces
disjoint useful work (for example one artifact-hash worker per report family or
one Project-readback worker per Project). Workers write only scratch findings;
the orchestrator owns the formal dependency-audit JSON/Markdown and performs the
final consistency fan-in. A blocker in one category does not stop unrelated
preflight workers from finishing, so the final blocker report is as complete as
possible in one pass.

After all required preflight tasks finish, the orchestrator freezes a bootstrap
summary/hash into the dependency-audit evidence. Only then may Step 3.0 choose/
create the canonical Phase-3 workspace, write formal progress/audit, materialize
`phase3-task-graph.json` r01, and initialize the normal
`orchestrator-state.json`. Archive (do not overwrite) the bootstrap state; later
Phase-3.1+ scheduling never uses it.

If preflight is BLOCKED, keep `bootstrap-state.json` for recovery and do not create
a speculative formal task graph from uncertain source identities.

### Predecessor uncertainty rule

Before **every numbered step or parallel frontier**, verify its direct predecessors
from this phase's canonical progress JSON and the artifacts named by the step
dependency table below. A cold-start agent must not infer completion from Git
commit names, file existence alone, or a previous chat summary.

If a predecessor's state, artifact, hash, verdict, timestamp, external resource,
or ownership is missing/ambiguous/inconsistent:

1. stop before mutating this step's files or external resources;
2. perform a read-only investigation of the predecessor step/phase evidence;
3. reconcile progress JSON against Git history, CI, and the predecessor's
   canonical artifact;
4. if the uncertainty can be resolved from evidence, record the resolution in
   the current progress notes and continue;
5. if it cannot be resolved, mark the current step/phase `blocked` and identify
   the exact predecessor evidence that is missing or contradictory.

Do not "best guess" a predecessor result. Missing evidence is an investigation
trigger, not permission to silently skip a dependency. If the investigation
changes a frozen upstream identity covered by the phase dependency audit, the
audit is invalidated and Step N.0 must run again.

### Long-command behavior

A background job is not a ChatGPT stop point. For commands expected to take more
than roughly ten seconds, start them in the background, retain the `job_id`, use
blocking `job_status(wait_seconds=50)`, perform independent work while the job is
running, and continue dependency waits until the current numbered step reaches
its defined stop point.

### Progress persistence

The phase progress JSON is the machine-readable source of truth. Step states are
`not_started`, `running`, `complete`, or `blocked`. Phase states are
`not_started`, `in_progress`, `waiting_wall_clock`, `blocked`, `complete`, or
`rolled_back`.

A numbered step is not complete until its required tests/evidence are recorded,
changes are committed/pushed, and the relevant branch CI is green when CI is
part of that step.

### Side-effectful / cross-transaction step start checkpoint

Before any step or substep that will submit canonical live trials, mutate a
ChatGPT Project/connector, start/stop persistent rollout services, change
deployment config/code, or enter a wall-clock wait:

1. re-check the direct predecessor evidence and dependency-audit validity;
2. set the current step/substep to `running` in canonical progress;
3. record exact source HEAD, relevant artifact hashes, external resource ids and
   the intended action/schedule;
4. commit/push this **start checkpoint** and wait for its branch CI when the
   checkpoint changes executable source; documentation/progress-only checkpoints
   require pre-commit and push but need not delay an already time-sensitive live
   action for a full multi-Python CI unless this phase explicitly says otherwise;
5. only then perform the external/live/wall-clock action.

On cold-start recovery, a `running` side-effect step means **investigate the
external state first** (trial submission evidence, Project mapping, service state,
timestamps) before replaying any command. Never assume that a missing completion
commit means the side effect did not happen.

For canonical live benchmark slots, the submitted-trial inclusion rule overrides
Git checkpoint convenience: if evidence shows submission happened, that outcome
owns the slot even when the start checkpoint was the last committed state.

### Production isolation

Do not clean/reset unrelated production work. Observe production state; do not
normalize it. Unless this phase explicitly authorizes a staged or final deployment,
the primary `master` checkout, `binnacle-mcp.service`, primary connector, primary
tunnel profile, and deployment config must not be changed by scheduling-v2 work.

### Dependency-audit persistence and invalidation

Every phase begins with **Step N.0 — Dependency Audit / Entry Gate**. No other
step in that phase may start until the audit is `PASS`.

The audit writes:

```text
benchmarks/chat-mode-scheduling-v2/phase3-dependency-audit-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase3-dependency-audit-YYYY-MM-DD-rNN.md
```

The JSON records at least:

```text
schema_version
phase
audited_at
audited_source_head
previous_phase_progress_path + sha256
previous_phase_report_path + sha256
required_supporting_artifacts + sha256
required_ci_run_id / head_sha / conclusion
external_prerequisites and their status
production_observation_baseline
overall_status = PASS | BLOCKED
blockers[]
```

Revision starts at `r01`. Every rerun increments it (`r02`, `r03`, ...); never
overwrite or edit an older committed audit revision. The phase progress JSON
contains `dependency_audit.path`, `dependency_audit.revision`, and
`dependency_audit.sha256` pointing to the current PASS/BLOCKED revision.

The audit is **invalidated** and must be rerun before further implementation if
any of the following occurs:

- a hashed previous-phase progress/report/supporting artifact changes;
- the current integration history is rewritten or no longer descends from the
  audited source lineage;
- the required upstream CI result is superseded by a new source commit;
- a frozen Project instruction hash, connector/endpoint mapping, selected budget,
  or deployment mapping used by this phase changes;
- the previous phase is reopened or its verdict changes;
- an external prerequisite previously recorded as PASS is later found false.

Parallel worker commits do not invalidate the audit when they descend from the
phase's audited/frozen integration base and only implement work authorized by the
audit. Unexpected upstream drift does.

If the audit becomes invalid, stop launching new workers/live trials/deployment
actions, mark the current phase `blocked`, rerun Step N.0, and only resume after
a new PASS artifact is committed. Never silently inherit an old dependency PASS.

### Step-3.0 cold-start/preflight workspace

Use these exact existing worktrees for the read-only preflight:

```text
direct predecessor checkout:
  /home/grammy-jiang/Projects/binnacle-chat-blocking-wall-guard
  expected branch: feature/chat-mode-blocking-wall-guard

lower-stack worktrees:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase0
    expected branch: feature/chat-mode-scheduling-v2-phase0
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase1
    expected branch: feature/chat-mode-scheduling-v2-phase1

public integration refs for freshness comparison:
  origin/proof-of-concept
  origin/master

planning document checkout until Phase 3 starts:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-6-plan
  expected branch: planning/chat-mode-scheduling-v2-phase3-6

production observation checkout:
  /home/grammy-jiang/Projects/binnacle
  expected branch: master
```

Start with `git fetch origin`, `git worktree list --porcelain`, and verify the
Phase0/Phase1/Phase2/planning/production mappings above. If a lower-phase worktree
is absent but its exact branch exists, reattach that branch at the canonical path;
do not invent a replacement branch. If the planning worktree is absent, recover
`origin/planning/chat-mode-scheduling-v2-phase3-6` at the canonical planning path.
Dirty/diverged state is investigated and preserved.

Do not run Step 3.0 from production `master` merely because it is convenient; the
production checkout is read-only observation evidence.

## Step 3.0 — Dependency Audit / Entry Gate

Step 3.0 has **two ordered stages**:

1. **Read-only preflight.** From an existing safe worktree, fetch/read upstream
   branches, previous-phase progress/reports/CI, and external prerequisites. Do
   not modify the previous phase merely to record a failed preflight. If the
   evidence is already insufficient/contradictory, report the blocker and stop;
   no Phase-3 workspace is created from an unqualified base.
2. **Phase workspace bootstrap + formal audit.** Once the phase-specific preflight
   conditions below are sufficient to choose the exact canonical source base,
   create/recover the Phase-3 canonical branch/worktree defined in this
   document. Only inside that workspace create/recover:

   ```text
   benchmarks/chat-mode-scheduling-v2/phase3-progress.json
   benchmarks/chat-mode-scheduling-v2/phase3-progress.md
   ```

   If absent, initialize every phase step to `not_started`, set Step 3.0 to
   `running`, phase status to `in_progress`, and `next_step` to `3.0`. If they
   already exist, reconcile them with Git history before changing anything; never
   overwrite a prior blocked/running checkpoint merely because the chat is new.

The formal dependency-audit artifact and its revision/hash are recorded under
the progress JSON `dependency_audit` object. On audit PASS, **do not yet mark
3.0 complete**: first materialize/validate task-graph revision r01 and initialize
the persistent orchestrator state as required by the task-graph contract above.
Only after those checks pass, mark 3.0 `complete` and set `next_step=3.1`.
On a blocker discovered **after** workspace bootstrap,
leave `last_completed_step` unchanged, set phase status `blocked`, keep
`next_step=3.0`, and commit/push the blocker evidence when Git remains
available.

**This is the mandatory first step of Phase 3. Do not create replay workers or
implement replay code before it passes.**

Phase 3 depends on two completed workstreams: scheduling Phase 2 and the separate
test-suite performance optimization program.

### Required upstream state

The canonical previous-phase files are exactly:

```text
benchmarks/chat-mode-scheduling-v2/phase2-progress.json
benchmarks/chat-mode-scheduling-v2/phase2-progress.md
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-2026-09-24.json
benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-2026-09-24.md
```

Do not search for a different Phase-2 final report unless these files explicitly
state that Phase 2 was formally reopened and superseded.

Audit all of the following from repository evidence, not conversation memory:

1. **Phase 2 completion**
   - `phase2-progress.json` says `status=complete`, `last_completed_step=2.12`,
     `next_step=null`;
   - its `post_completion_review` / 2.12a entry is `complete`;
   - the dated Phase-2 final report says Phase 2 complete, Phase 3 not started,
     production undeployed;
   - `feature/chat-mode-scheduling-v2-phase0` is an ancestor of
     `feature/chat-mode-scheduling-v2-phase1`;
   - `feature/chat-mode-scheduling-v2-phase1` is an ancestor of
     `feature/chat-mode-blocking-wall-guard`;
   - the Phase-2 guard implementation/2.12a evidence is present on the Phase-2
     branch before its post-Phase-2 test-efficiency maintenance commits.
2. **Phase 2 quality evidence**
   - final Phase-2/2.12a CI is green;
   - full tests/pre-commit evidence in the final report is internally consistent;
   - repository default blocking budget remains empty.
3. **Test-efficiency program completion**
   - `docs/test-suite-performance-optimization-progress-2026-09-24.md` (or its
     documented successor) shows final Step 3.7 PASS, unless the owner explicitly
     accepted an earlier final checkpoint;
   - its completed history is present on the **Phase-2 branch after 2.12a**;
     planning-time evidence includes Step 3.7 PASS and original closeout commit
     `0a80986`, but 3.0 verifies the rebased Phase-2 equivalents/history rather
     than depending on the old commit id;
   - its final CI is green;
   - record the final authoritative fast/full/coverage commands that Phases 3–6
     must inherit rather than reimplement.
   - planning-time known commands after the completed optimisation are:

     ```text
     fast full-suite:
       uv run python scripts/run_test_suite.py --workers 4 --seed 12345
     coverage policy:
       uv run tox -e coverage-policy -- --seed 12345
     local compatibility matrix when required:
       env BINNACLE_TEST_WORKERS=4 uv run tox run -- --seed 12345
     ```

     Step 3.0 re-reads `docs/testing.md` and the optimisation progress file and
     records any later authoritative change instead of blindly hard-coding these
     planning-time commands.
4. **Planning handoff**
   - this Phase-3 plan commit is available;
   - Phase 3 starts from the **current Phase-2 branch HEAD**, never directly from
     `master` or `proof-of-concept`;
   - planning-only commits are replayed on top of Phase 2 after stack freshness is
     proven.
   - no test-efficiency commit is dropped/reset.
5. **Production observation baseline**
   - capture production branch/HEAD/status, service ActiveState/SubState, config
     and unit hashes, and budget-key presence;
   - preserve unrelated work exactly.

### Mandatory lower-stack freshness investigation

Before Phase-3 workspace bootstrap, verify the stacked branches in order:

```text
Phase0 = feature/chat-mode-scheduling-v2-phase0
Phase1 = feature/chat-mode-scheduling-v2-phase1
Phase2 = feature/chat-mode-blocking-wall-guard
```

Required ancestry:

```text
Phase0 is ancestor of Phase1
Phase1 is ancestor of Phase2
```

Then compare the **Phase-2 tree** with the current public integration tree when
`origin/master` and `origin/proof-of-concept` are synchronized. If their trees
differ because new public-base work arrived after the last stack update, Phase 3
must not absorb that work directly. Restack from the earliest affected layer:

1. identify the latest non-scheduling/public-base commits that must move below the
   scheduling stack;
2. rebase Phase 0 onto that refreshed lower base;
3. rebase Phase 1 onto refreshed Phase 0;
4. rebase Phase 2 (including post-2.12a test-efficiency maintenance) onto refreshed
   Phase 1;
5. verify the refreshed Phase-2 tree/content against the intended current public
   integration state;
6. only then rebase planning/Phase 3 onto refreshed Phase 2.

If master and POC themselves diverge, first investigate/reconcile the repository's
normal public integration workflow; do not guess which public branch should be
ignored.

Planning-time verified stack after the 2026-09-24 restack:

```text
Phase0 tip: 2650c08
Phase1 tip: 3074650
Phase2 tip: 5f2be14
Phase2 tree == master/proof-of-concept tree at 77a3f03
```

These ids are historical evidence only; future 3.0 audits use current branch refs.

### Phase-3 workspace bootstrap inside Step 3.0

After the read-only preflight proves Phase0->Phase1->Phase2 ancestry, Phase-2
completion/test-efficiency state, and public-base freshness, bootstrap the exact
Phase-3 integration workspace **from the current Phase-2 HEAD** inside 3.0. Bring
forward only planning-document patches not already patch-equivalent on Phase 2.
Then create progress files and perform/commit the formal audit.

### Audit result

Write the dependency-audit artifacts and a table with one row per dependency:

```text
phase2_progress
phase2_report_and_2_12a
phase2_ci
test_efficiency_progress
test_efficiency_ci
authoritative_test_runner
planning_handoff
git_lineage
production_isolation
```

Every row must be `PASS`. Otherwise Phase 3 remains `not_started`/`blocked` and
no Step 3.1 work begins.

### Exit criteria

```text
dependency audit PASS committed
final direct-predecessor Phase-2 HEAD identified
authoritative optimized test commands recorded
production baseline recorded
next allowed step: 3.1
```

## Phase-3 canonical integration workspace

```text
branch:   feature/chat-mode-scheduling-v2-phase3
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3
```

Step 3.0 creates these exact names after its read-only preflight. If either
already exists, inspect branch HEAD, worktree status, progress files, and origin
relationship first. A dirty worktree is an interrupted Phase-3 step to recover;
divergence is a blocker. Never create an alternate `phase3-2` branch/worktree or
reset unexplained work.

Planning-document transfer procedure used by 3.0:

```bash
git fetch origin
git rev-parse feature/chat-mode-blocking-wall-guard
git rev-parse origin/planning/chat-mode-scheduling-v2-phase3-6
git cherry -v \
  feature/chat-mode-blocking-wall-guard \
  origin/planning/chat-mode-scheduling-v2-phase3-6
```

Create/recover the Phase-3 branch/worktree from the **current Phase-2 HEAD**.
Replay only `+` planning/document patches that are not already patch-equivalent on
Phase 2, preserving their order. Before each replay, inspect the commit's file
scope; runtime/test/production changes on the planning branch are a blocker.

The planning branch itself is kept rebased on Phase 2 while Phase 3 is not yet
started. Once the actual Phase-3 feature branch exists, that branch becomes the
execution lineage; the planning branch remains documentation history only.

## Phase-3 step dependency DAG

| Work | Direct predecessor(s) | Required predecessor evidence before start |
| --- | --- | --- |
| **3.0** dependency audit | Phase 2 + test-efficiency final checkpoint | upstream progress/reports/hashes/CI investigated and PASS |
| **3.1** validate synchronized baseline | 3.0 | committed PASS dependency-audit artifact |
| **3.2** freeze replay schema | 3.1 | Phase-3 integration branch/worktree + inherited test runner recorded |
| **3.3A/B/C/D** implementation frontier | 3.2 | exact shared schema/source HEAD + all four task-specific worker branches created |
| **3.4A** integrate corpus/provenance path | 3.3A + 3.3D | extractor + evidence/provenance commits/tests green; frozen Step-3.2 source inventory remains unchanged |
| **3.4B** integrate replay-engine path | 3.3B | replay-engine commit/tests green; may integrate while 3.5 source workers run |
| **3.4C** integrate Phase-4 scenario path | 3.3C | scenario/oracle commit/tests green; may integrate while 3.5/3.6 work runs |
| **3.5M** source-shard extraction + deterministic corpus merge | 3.4A | every required canonical shard committed; merged corpus hash frozen as provisional-canonical candidate |
| **3.5A** corpus audit fan-out + aggregate audit | each shard may audit as soon as it exists; aggregate audit needs 3.5M | every canonical source audit + aggregate audit PASS against the 3.5M corpus hash |
| **3.6A/B/C** cumulative candidate replay frontier | 3.5M + 3.4B | C120/C300/C600 replay against frozen 3.5M corpus hash; outputs provisional while 3.5A is pending |
| **3H** historical H10 replay | 3.5M + 3.4B | diagnostic historical comparator; never a live-candidate/shortlist predecessor |
| **3.7** promote/aggregate C shortlist | 3.6A/B/C + 3.5A PASS | C120/C300/C600 corpus hashes equal audited corpus; shortlist excludes H10 |
| **3.8** Phase-4 readiness | 3.7 + 3.4C | shortlist/verdict frozen; R4/R6/R10/R12 + provenance contracts integrated |
| **3.9** final validation | 3.8 | readiness PASS; no unresolved blocker |
| **3.10** final replay report/checkpoint | 3.9 + 3H complete | C shortlist/readiness validated + H10 historical replay complete + final tests/CI/isolation green |

### Phase-3 worker branch/worktree topology

Step 3.2 creates these exact worker branches from the same frozen integration
HEAD. Reuse/recover them if they already exist; never create alternate suffixes:

```text
3.3A branch: feature/chat-mode-scheduling-v2-phase3-corpus
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-corpus
3.3B branch: feature/chat-mode-scheduling-v2-phase3-replay
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-replay
3.3C branch: feature/chat-mode-scheduling-v2-phase3-scenarios
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-scenarios
3.3D branch: feature/chat-mode-scheduling-v2-phase3-provenance
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-provenance
```

After Step 3.5M freezes the merged corpus hash **and** Step 3.4B has integrated the replay engine, create/rebase fresh replay-result worker branches from the current Phase-3 integration HEAD. Do not wait for Step 3.5A audits to finish:

```text
feature/chat-mode-scheduling-v2-phase3-c120
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-c120
feature/chat-mode-scheduling-v2-phase3-c300
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-c300
feature/chat-mode-scheduling-v2-phase3-c600
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-c600
feature/chat-mode-scheduling-v2-phase3-h10
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-h10
```

Each C replay worker commits only its C-candidate JSON/Markdown. The H10 worker commits its historical-comparator JSON/Markdown. Step 3.7 needs only C120/C300/C600; H10 is integrated whenever ready and is required only by 3.10 final closeout.

The implementation frontier has four independent tasks because the work itself
contains four disjoint ownership areas. The orchestrator launches **all four at
once** when 3.2 freezes their common input HEAD; it does not occupy one of those
workers:

```text
implementation-corpus      -> 3.3A corpus extractor
implementation-replay      -> 3.3B replay engine
implementation-scenarios   -> 3.3C missing scenarios/oracles
implementation-provenance  -> 3.3D timeout provenance/evidence
```

If one implementation worker is blocked, the other three continue. There is **no single all-worker integration barrier**. The orchestrator integrates each dependency path
as soon as that path's inputs are ready: A+D feed 3.4A, B feeds 3.4B, C feeds
3.4C. These integration commits share the canonical integration branch and are
therefore serialized only for the short cherry-pick/test/commit critical section;
workers spawned from an earlier frozen integration point continue concurrently.

The replay frontier launches one worker for each cumulative **C candidate** plus one independent H10 historical-comparator worker as soon as the Step-3.5M merged corpus hash is frozen and 3.4B is ready:

```text
candidate-c120
candidate-c300
candidate-c600
historical-h10
```

Step 3.7 is the fan-in for the **three C candidate reports only**. The H10 worker
runs on the same audited/provisional corpus pipeline but is diagnostic and may
finish before or after shortlist/readiness work. This mirrors the authoritative
A/B plan where H is not a production candidate.

### Dynamic source-shard extraction and audit fan-out

Step 3.5 is intentionally more parallel than the original plan. Before launching
any shard worker, the orchestrator verifies the Step-3.2
`phase3-source-inventory.json` SHA equals the value recorded in canonical progress.
A mismatch invalidates 3.2 and blocks all shard work; workers never regenerate or
mutate the inventory independently.

The frozen source inventory assigns a stable `source_id` to every canonical
source:

```text
phase1-step3
phase1-step4
phase1-step5
phase1-step6
phase1-step7
phase1-step8
operational-journal   # only when a retained window exists
```

After Step 3.4A integrates the extractor/provenance path, the orchestrator creates **one worker per
source_id** from the same integration HEAD. Branch/worktree names are derived
deterministically:

```text
branch:   feature/chat-mode-scheduling-v2-phase3-source-<source_id>
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-source-<source_id>
output:   benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/<source_id>.json
```

All source workers run concurrently when ready. Each reads only its frozen source
paths and writes only its shard file plus an optional shard Markdown note, then
commits that artifact on its worker branch. A missing optional operational-journal
window produces an explicit `unavailable` shard; a missing canonical Phase-1
source is a blocker.

As each source worker completes, the orchestrator validates its input/output
hashes and briefly acquires `canonical-integration` to cherry-pick **that shard
commit immediately**. This is continuous fan-in: do not wait for all shard workers
before integrating completed shard artifacts. The short Git critical sections are
serialized, while all remaining extraction/audit workers continue running.

The extractor CLI therefore supports deterministic shard/merge operations:

```bash
uv run python scripts/chat_scheduling_replay_corpus.py extract \
  --inventory benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.json \
  --source-id <source_id> \
  --output benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/<source_id>.json

uv run python scripts/chat_scheduling_replay_corpus.py merge \
  --inventory benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.json \
  --shards-dir benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards \
  --output benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.json \
  --report benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.md
```

As each extraction worker finishes, the orchestrator validates its source hash and
immediately launches its corresponding **independent audit worker from that exact
source-worker commit**; it does not wait for every extraction worker first. Audit
branch/worktree names are:

```text
feature/chat-mode-scheduling-v2-phase3-audit-<source_id>
/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-audit-<source_id>
```

Each audit worker re-derives counts/timing invariants from that immutable source
and shard artifact and writes only:

```text
benchmarks/chat-mode-scheduling-v2/phase3-corpus-audits/<source_id>.md
```

After all required shard commits are integrated, the orchestrator merges them
deterministically into the corpus while any already-started shard audits continue
running. Per-source audit commits are cherry-picked as they complete under the
same short canonical-integration lock. Then, once the merged corpus exists, launch
one additional aggregate consistency audit worker:

```text
branch:   feature/chat-mode-scheduling-v2-phase3-audit-aggregate
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-audit-aggregate
output:   benchmarks/chat-mode-scheduling-v2/phase3-corpus-audits/aggregate.md
```

Step 3.5M completes as soon as every required canonical shard is integrated and
the deterministic merge produces a corpus JSON/Markdown with a frozen SHA. That
SHA is immutable for all speculative replay workers.

Step 3.5A continues independently: every per-source audit runs as soon as its
shard exists, and the aggregate audit starts after 3.5M. 3.5A completes only when
every canonical source audit and the aggregate audit pass against the **same
3.5M corpus SHA** and all audit artifacts are present on the canonical branch.

This deliberately overlaps audit latency with candidate replay. The number of
simultaneous workers is the number of ready extraction/audit/replay tasks, not an
arbitrary chat-session limit.

### Speculative replay promotion/invalidation contract

Every replay policy report (C120/C300/C600 **or H10**) started before 3.5A completion must record:

```text
corpus_sha256
audit_status_at_start = pending
provisional = true
```

They are deterministic computations over immutable corpus bytes, so no safety or
external side effect depends on the pending audit. When 3.5A passes:

- if the audited corpus SHA exactly equals the report's `corpus_sha256`, the
  orchestrator promotes that report to canonical by recording
  `audit_status=pass`, `provisional=false`; **do not rerun**;
- if any audit exposes a source/corpus defect that requires a new corpus revision,
  the old provisional reports remain historical diagnostics and only reports whose
  corpus SHA differs from the new audited SHA are rerun;
- if 3.5A is BLOCKED without a corrected corpus, Step 3.7 cannot promote/select a C candidate and Step 3.10 cannot finalize H10, but already-running deterministic replay workers may finish so their diagnostics are preserved.

The provisional optimization saves wall time while preserving the rule that **no
Phase-3 acceptance decision is made from an unaudited corpus**.

### Final CI attestation without self-reference

The final report/progress cannot contain the CI run id of the same commit that
introduces those fields without creating an infinite self-reference loop. Use
this fixed two-commit closeout:

1. **Evidence commit** — write the final report and all substantive evidence, run
   local required gates, commit/push, and wait for that exact commit's CI to
   finish green.
2. **Closeout/handoff commit** — update progress/handoff with
   `validated_evidence_commit`, `validated_ci_run_id`, `validated_ci_head_sha`,
   and `validated_ci_conclusion=success`, pointing to the evidence commit from
   step 1. This closeout commit contains no substantive implementation/result
   changes. Run pre-commit, push it, and wait for its own branch CI to be green.
   Do **not** write that second CI id back into the repository.

The next phase's N.0 verifies both: the recorded evidence-commit CI fields and a
fresh GitHub query showing the current closeout HEAD CI is green. If either is
not green/matching, dependency audit is BLOCKED.

## Canonical Phase-3 handoff contract

Step 3.10 must write these exact dated final artifacts:

```text
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD-rNN.md
```

`phase3-progress.json` must contain a `handoff` object with:

```text
final_report_json
final_report_md
final_report_json_sha256
final_report_md_sha256
phase3_source_head
replay_corpus_path + sha256
candidate_shortlist_path + sha256
historical_h10_path + sha256
live_candidates[]                 # C budgets only
preferred_live_candidate          # C budget only
scenario_catalog_sha256
provenance_classifier_commit
phase4_input_contract_path + sha256
phase4_ready = true | false
validated_evidence_commit
validated_ci_run_id
validated_ci_head_sha
validated_ci_conclusion
```

The first final report is `r01`. If a completed phase is later formally reopened,
write a new revision instead of overwriting the old one; update the progress
`handoff` to point at the new canonical revision and preserve the prior verdict
as historical evidence.

`scenario_catalog_sha256` is the SHA-256 of a canonical JSON object whose keys are
the sorted relative paths `benchmarks/chat-mode-scheduling-v2/scenarios/R*.json`
and whose values are each file's SHA-256. Do not hash directory metadata or file
mtime.

Phase 4.0 recomputes these hashes and rejects disagreement; it does not trust the
`handoff` object by itself.

## Phase-3 implementation and focused-test command contract

These source/test names are frozen. A worker does not search the repository to
invent alternatives.

### New Phase-3 tooling

```text
scripts/chat_scheduling_replay_corpus.py
tests/scripts/test_chat_scheduling_replay_corpus.py

scripts/chat_scheduling_replay.py
tests/scripts/test_chat_scheduling_replay.py

scripts/chat_scheduling_provenance.py
tests/scripts/test_chat_scheduling_provenance.py

scripts/chat_scheduling_phase3_report.py
tests/scripts/test_chat_scheduling_phase3_report.py
```

Step 3.2 writes the immutable source inventory:

```text
benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.json
benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.md
```

The inventory contains exact canonical Phase-1 trial source paths/hashes and the
available operational journal window. The corpus extractor consumes this file;
it does not independently rediscover sources on every run.

Corpus construction uses the parallel `extract` + deterministic `merge` CLI
contract defined in **Dynamic source-shard extraction and audit fan-out** above.
A single-process `build` convenience command may exist for local debugging, but
Phase-3 canonical execution uses shard fan-out so independent source extraction is
not serialized unnecessarily.

Phase-3 report CLI has two fan-in modes.

Step 3.7 C-candidate shortlist:

```bash
uv run python scripts/chat_scheduling_phase3_report.py shortlist \
  --corpus benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.json \
  --candidate benchmarks/chat-mode-scheduling-v2/phase3-replay-c120.json \
  --candidate benchmarks/chat-mode-scheduling-v2/phase3-replay-c300.json \
  --candidate benchmarks/chat-mode-scheduling-v2/phase3-replay-c600.json \
  --output-json benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.json \
  --output-md benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.md
```

Step 3.10 final replay report, after H10 is complete:

```bash
uv run python scripts/chat_scheduling_phase3_report.py final \
  --shortlist benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.json \
  --historical benchmarks/chat-mode-scheduling-v2/phase3-replay-h10.json \
  --output-json benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD-rNN.json \
  --output-md benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD-rNN.md
```

The actual date/revision is resolved by the orchestrator before the final command;
never literally create a file containing `YYYY-MM-DD-rNN`.

### Focused test matrix

```text
3.3A:
  uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py

3.3B:
  uv run pytest -q tests/scripts/test_chat_scheduling_replay.py

3.3C:
  uv run pytest -q tests/scripts/test_chat_scheduling_manifest.py \
    tests/scripts/test_chat_scheduling_oracle.py

3.3D:
  uv run pytest -q tests/scripts/test_chat_scheduling_provenance.py \
    tests/scripts/test_chat_scheduling_analyzer.py

3.4A corpus/provenance integration:
  uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py \
    tests/scripts/test_chat_scheduling_provenance.py \
    tests/scripts/test_chat_scheduling_analyzer.py \
    tests/scripts/test_chat_scheduling_harness.py

3.4B replay-engine integration:
  uv run pytest -q tests/scripts/test_chat_scheduling_replay.py

3.4C scenario/oracle integration:
  uv run pytest -q tests/scripts/test_chat_scheduling_manifest.py \
    tests/scripts/test_chat_scheduling_oracle.py

3.7 shortlist + 3.10 final report modes:
  uv run pytest -q tests/scripts/test_chat_scheduling_phase3_report.py
  # tests must cover both `shortlist` and `final` CLI modes
```

If the completed test-efficiency program changes the wrapper used for full-suite
validation, that affects 3.1/3.9 full gates only; it does not rename these focused
benchmark tests unless Step 3.0 explicitly records such an upstream rename.

## 13. Phase-3 objective

Use frozen historical evidence to answer:

> Which blocking-wall budgets are clearly unsafe or unnecessarily large before
> we spend live ChatGPT trials?

Phase 3 is a **filter**, not final causal evidence. It cannot predict how ChatGPT
would reschedule independent work under a different guard.

Required policy candidates:

```text
C120  cumulative union-wall budget = 120 s
C300  cumulative union-wall budget = 300 s
C600  cumulative union-wall budget = 600 s
H10   first positive wait <=10 s; every later positive wait in same turn = 0 s
```

Observed historical behavior is the baseline comparator.

## 14. Phase-3 replay semantics — frozen

### 14.1 Replay input

Replay physical positive `job_status` intervals from normalized historical
traces. Use actual observed `waited_s` and call start/end timing. Requested wait
is retained for context but is never treated as actual blocking duration.

### 14.2 Candidate cumulative guard

For C120/C300/C600:

- state is per `(client, base_turn)`;
- per-call cap remains 50 seconds;
- overlapping wait intervals charge union wall once;
- each historical wait is clipped by candidate remaining budget;
- after remaining budget falls below one second, subsequent positive requests
  become simulated non-blocking calls;
- the replay never fabricates additional waits that did not occur historically.

### 14.3 Historical H10 comparator

For each historical turn:

```text
first positive wait effective = min(requested, 10 s)
all later positive waits effective = 0 s
```

Replay reports which observed dependency completions would have been lost or
forced to a later user turn under that historical policy.

### 14.4 Completion preservation

For a historical physical status call that returned a required job completion,
mark that completion as preserved only when the candidate effective interval
would still include the observed job-exit point. If the candidate would cut the
call before the observed exit, mark it `completion_at_risk`.

This is deliberately conservative: replay does not assume the model would issue
a smarter later call.

### 14.5 Replay output per turn

Each replayed turn reports:

```text
trial_id / source id
scenario
historical arm
base turn
observed blocking-wall union
candidate blocking-wall union
burden reduction percent
candidate exhaustion timestamp/offset
positive waits observed
waits clipped
waits converted to non-blocking
observed required completions
required completions preserved
completion_at_risk count
final historical terminal/correct/same-prompt state
```

### 14.6 Replay CLI contract

The Phase-3 replay implementation exposes one deterministic CLI:

```bash
uv run python scripts/chat_scheduling_replay.py \
  --corpus benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.json \
  --policy cumulative --budget-s 120 \
  --output benchmarks/chat-mode-scheduling-v2/phase3-replay-c120.json
```

Use `--budget-s 300` / `600` for the other cumulative candidates and
`--policy historical-one-shot --budget-s 10` for H10. The JSON is canonical;
Markdown is rendered from JSON by the same script or a deterministic companion
function. Running the same command twice against the same corpus must produce
identical policy rows except an explicitly separated generation timestamp.

## 15. Phase-3 source corpus

Use two evidence classes.

### 15.1 Canonical benchmark corpus

The mandatory Phase-1 macro source reports are exactly these six files:

```text
benchmarks/chat-mode-scheduling-v2/phase1-step3-read-heavy-ab-2026-09-23.json
benchmarks/chat-mode-scheduling-v2/phase1-step4-background-barrier-ab-2026-09-23.json
benchmarks/chat-mode-scheduling-v2/phase1-step5-development-journey-ab-2026-09-23.json
benchmarks/chat-mode-scheduling-v2/phase1-step6-recovery-journey-ab-2026-09-23.json
benchmarks/chat-mode-scheduling-v2/phase1-step7-multiround-planning-ab-2026-09-23.json
benchmarks/chat-mode-scheduling-v2/phase1-step8-repeated-dependency-barrier-ab-2026-09-23.json
```

Do **not** substitute `phase1-step3-read-heavy-pilot-*` or the Step-1.2 micro
report into the macro replay corpus. Step 1.9's aggregate report is the authority
for the six expected source SHA-256 values. Step 3.2 must recompute every hash and
fail if any differs before corpus extraction.

Freeze all canonical submitted trials referenced by those six reports. Their
combined primary macro sample is expected to contain **24 A + 24 B canonical
slots**; a different count is an investigation blocker, not an invitation to
shrink/expand the sample. Do not select only successful trials.

For every canonical slot, the source inventory records the report path, trial id,
arm/scenario, submitted status, state/evidence directory paths, and whether the
raw evidence required for positive-wait replay exists. Missing raw evidence for a
canonical slot remains explicitly recorded; do not replace that slot with a later
diagnostic rerun.

For completion-preservation analysis, separately identify the subset whose
terminal DAG/correctness evidence shows an observed valid completion. The full
canonical population remains available for reliability context.

### 15.2 Operational historical corpus

Use retained Binnacle journal `job_status_timing`/tool-call evidence available at
Phase-3 start to quantify repeated-wait burden. Freeze only a compact normalized
replay dataset, not arbitrary full private logs, into the repository.

If older raw journal data has expired, do not fabricate it. Record the available
window and use the documented 2026-09-19 distributions only as contextual sanity
evidence, not as synthetic per-turn replay rows. The operational corpus is
valuable but **not mandatory** when retention has legitimately expired. The
canonical Phase-1 benchmark corpus is mandatory and is the fallback population
for the >=70% repeated-wait burden calculation. A candidate is blocked for
insufficient replay evidence only if the canonical corpus itself cannot be
reconstructed.

## 16. Phase-3 replay corpus artifact

Step 3.2 freezes **schema version 1 and an empty/header contract fixture** for the
future corpus. It does not generate canonical replay rows yet. Step 3.5 consumes
the frozen source inventory and produces the canonical artifact:

```text
benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.json
```

It contains no conversation prose. Store only replay fields needed for wait
policy analysis, source hashes, scenario/arm ids, call timing offsets, states,
job ids hashed if necessary, and completion markers.

Also write:

```text
benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.md
```

with counts, source windows, exclusions, hashes, and privacy notes.

## 17. Phase-3 offline candidate gates

A candidate is rejected before Phase 4 if any of these apply:

1. **Known-good completion preservation <95%** across bounded canonical replay
   turns with observed valid dependency completion.
2. **Predicted budget exhaustion >10%** among bounded canonical replay turns
   that actually contain at least one positive status wait; pre-MCP/no-tool
   submitted failures remain reliability evidence but are not assigned a fake
   policy exhaustion outcome.
3. It predicts **any exhaustion** for a bounded canonical replay turn whose
   observed required blocking-wall union is <= `candidate_budget - 1.0 s`. This
   is a deterministic early-exhaustion failure, not a subjective "systematic"
   judgment.
4. Historical repeated-wait burden reduction is **<70%** where the replay corpus
   can validly measure the historical repeated-wait upper-bound burden target.
5. Any canonical replay turn that contains positive waits and is required for a
   policy denominator is missing the actual call timing / `waited_s` / observed
   job-state evidence needed to compute candidate clipping or completion
   preservation. Reliability-only submitted failures with no useful MCP wait are
   retained as reliability context but are not assigned fabricated replay fields.

Passing Phase 3 means **eligible for live testing**, not approved for deployment.
The live calibration shortlist is exactly **all candidates that pass every Phase-3 offline candidate gate**. The preferred live candidate is the smallest passing
budget. Do not drop another passing candidate because it looks less attractive;
Phase 4 targeted calibration exists to resolve that uncertainty. If no candidate
passes, Phase 3 ends `NO_LIVE_CANDIDATE` and Phase 4 must not start.

## 18. Phase-3 steps

### Step 3.1 — validate the synchronized final baseline

Target: 10–20 minutes.

Orchestrator-owned canonical step. Independent already-running workers may continue; this step itself has no worker-session ceiling.

Predecessor: Step 3.0 PASS. The canonical Phase-3 workspace already exists; do
not create another branch/worktree here.

Tasks:

1. Re-read the `audited_source_head`, final test-efficiency checkpoint, and
   authoritative fast/full/coverage commands recorded by 3.0.
2. Confirm the Phase-3 HEAD contains the complete current Phase-2/test-efficiency history
   and this current Phase-3 execution plan; verify no planning/test-efficiency
   commit was dropped during 3.0 bootstrap.
3. Record the exact branch/worktree/HEAD and production observation baseline in
   Phase-3 progress.
4. Run the authoritative optimized fast full-suite smoke recorded by 3.0.
5. If that runner or its documented expected selection/coverage semantics differ
   from the 3.0 audit evidence, stop and investigate; material source drift
   invalidates 3.0.

Exit:

```text
Phase-3 canonical workspace clean
final test-efficiency baseline demonstrably inherited
authoritative test runner smoke green
production untouched
next step: 3.2
```

Do not implement replay yet.

### Step 3.2 — freeze replay schema and source inventory

Target: 15–20 minutes.

Orchestrator-owned canonical step. Launch all newly ready worker tasks immediately after its freeze point.

Tasks:

- freeze the replay semantics, source-corpus, and replay-corpus-artifact contracts defined above;
- enumerate canonical Phase-1 source reports and state dirs;
- enumerate available operational journal window;
- record source SHA-256 where files are immutable;
- define compact corpus field names;
- write empty/header `phase3-replay-corpus.json` contract fixture;
- create worker branches/worktrees from this exact integration HEAD.

Exit: worker lanes have a stable shared schema and do not need to redesign it.

### Parallel implementation frontier 3A — all independent implementation tasks

All four implementation tasks start immediately from the same Step-3.2 HEAD. Four is the task count, not a concurrency limit.

#### Step 3.3A — corpus extractor worker

Target: 15–20 minutes.

Own only:

```text
scripts/chat_scheduling_replay_corpus.py
tests/scripts/test_chat_scheduling_replay_corpus.py
```

This worker implements extraction code/tests only. It does **not** write the
canonical `phase3-replay-corpus.{json,md}`; Step 3.5 orchestrator generation owns
those artifacts.

Tasks:

- read canonical trial reports/state evidence;
- extract actual positive wait intervals and terminal/completion facts;
- normalize operational journal turns;
- redact prose/irrelevant arguments;
- deterministic sort and source hashing;
- fail loudly when a referenced canonical submitted trial is missing rather than
  silently shrinking the sample.

#### Step 3.3B — replay engine worker

Target: 15–20 minutes.

Own only:

```text
scripts/chat_scheduling_replay.py
tests/scripts/test_chat_scheduling_replay.py
```

Implement the frozen baseline/C120/C300/C600/H10 replay semantics defined in **Phase-3 replay semantics — frozen** with a pure,
deterministic API. Synthetic tests cover serial waits, overlap, partial overlap,
early exhausted budget, observed exit inside/outside candidate interval, and H10.

#### Step 3.3C — missing Phase-4 scenarios worker

Target: 15–20 minutes.

Own only:

```text
benchmarks/chat-mode-scheduling-v2/scenarios/R4.json
benchmarks/chat-mode-scheduling-v2/scenarios/R6.json
benchmarks/chat-mode-scheduling-v2/scenarios/R10.json
benchmarks/chat-mode-scheduling-v2/scenarios/R12.json
scripts/chat_scheduling_manifest.py
scripts/chat_scheduling_oracle.py
tests/scripts/test_chat_scheduling_manifest.py
tests/scripts/test_chat_scheduling_oracle.py
```

3.3D owns evidence/provenance changes; 3.3C must not edit
`chat_scheduling_evidence.py` or `chat_scheduling_harness.py`.

The scenario contracts are frozen as follows. Do not redesign them during
implementation.

| ID | Required job | Independent work | Logical completion | Final behavior |
| --- | --- | --- | --- | --- |
| R4 | background 90 s validation that prints a nonce marker | 8 independent diagnosis-file reads after launch | validation job exits 0 after all reads | reply exactly `DONE` |
| R6 | background 90 s nonce job | none | repeated `job_status` logical node completes only at `state=exited` | reply exactly `DONE` |
| R10 | background 90 s job with **no stdout/stderr** | none | repeated status node completes at `state=exited`; at least one earlier status must observe `state=running, quiet=true` | reply exactly `DONE` |
| R12 | background job lasting `budget + 30 s` | none | repeated status node still requires `state=exited`; budget exhaustion therefore leaves the DAG intentionally non-terminal | intentional checkpoint handoff, not `DONE` |

Use `expected_runtime_s=110` and `max_turn_runtime_s=180` for R4/R6/R10. R4's
eight fixture files follow the deterministic `inspect/f01.txt` .. `f08.txt`
shape already used by R3, with R4-specific nonce payloads.

Add one generic deterministic oracle type for R10/R12:

```text
job_status_any_call
params:
  node: <logical job_status node>
  fields: {<structured-result field>: <expected value>, ...}
```

It passes only when at least one successful physical call assigned to that
logical node contains every requested field/value. R10 uses it for
`state=running, quiet=true`. R12 uses it for
`state=running, blocking_budget_exhausted=true`. Keep this oracle generic rather
than hard-coding an R10/R12 name.

R12's final reply is instructed to use this exact field layout, with the actual
job id substituted by the model:

```text
BUDGET_EXHAUSTED job_id=<actual-id> state=running pending=dependency resume=job_status
```

Its deterministic oracle uses `reply_contains_all` for these fixed fragments:

```text
BUDGET_EXHAUSTED
job_id=
state=running
pending=dependency
resume=job_status
```

and `job_status_any_call` for the structured running/exhausted state. Do **not**
add `all_nodes_complete` to R12. The analyzer must report
`terminal=false`, `budget_exhaustion_handoff=true`, and
`same_prompt_completion=false` for the expected successful safety outcome. A
timeout/interruption is not an acceptable R12 handoff.

R12 is budget-parameterized; never hard-code 300 seconds. Its manifest declares
`runtime_budget_margin_s=30` and uses `{budget_plus_margin_s}` in the fixture
command. Phase-4 harness Step 4.2B resolves that placeholder from `--budget-s`.
The resolved job runtimes are exactly 40/150/330/630 seconds for H10/C120/C300/C600.

Make the manifest runtime validator phase-aware: the existing <=240-second bound
continues to apply to every existing Phase-1 scenario and R4/R6/R10; only R12 may
exceed it, with an absolute manifest ceiling of **690 seconds** (600 + 30 job
runtime + 60 seconds benchmark/browser safety allowance). Do not remove the
Phase-1 bound globally.

R12 is excluded from aggregate performance medians.

#### Step 3.3D — timeout provenance classifier worker

Target: 15–20 minutes.

Own only:

```text
scripts/chat_scheduling_provenance.py
tests/scripts/test_chat_scheduling_provenance.py
scripts/chat_scheduling_evidence.py
tests/scripts/test_chat_scheduling_evidence.py
minimal provenance-only harness changes if existing raw evidence lacks a required input
```

Do not edit manifest/oracle files owned by 3.3C. Ensure evidence normalization
retains `blocking_budget_exhausted` and `quiet` structured result fields so the
generic `job_status_any_call` oracle can evaluate R10/R12 after integration.

Every submitted failure must be classifiable as one of:

```text
pre_mcp_submission_failure       # infrastructure before useful MCP work
active_turn_browser_timeout      # submitted; assistant/browser stream timed out
mcp_completed_browser_timeout    # required MCP/DAG completed before browser settling timeout
budget_exhaustion                # explicit guard exhaustion handoff
other_submitted_error            # submitted but none of the above
```

Classification is diagnostic only. It never changes canonical inclusion.

### Step 3.4A — integrate corpus/provenance path

Target: short orchestrator critical section once 3.3A + 3.3D are complete.

Cherry-pick/integrate only:

```text
3.3A corpus extractor
3.3D provenance/evidence support
```

Run their focused integration tests. Freeze the resulting integration HEAD as
`phase3_corpus_path_head`. Immediately release the canonical-integration lock and
launch Step 3.5 source-shard workers. Do **not** wait for 3.3B/3.3C.

### Step 3.4B — integrate replay-engine path

Predecessor: 3.3B only. When the replay-engine worker finishes, acquire the
canonical-integration lock, bring its commit onto the current Phase-3 integration
branch, run replay-engine focused tests, record `phase3_replay_path_head`, then
release the lock. Step 3.6 waits for this checkpoint plus the frozen Step-3.5M corpus; Step 3.5M extraction does not wait for 3.4B.

This integration may occur while source-shard extraction/audit workers created
from `phase3_corpus_path_head` are still running. Their immutable input HEAD/hash
remains valid; do not restart them merely because the canonical branch advanced.

### Step 3.4C — integrate Phase-4 scenario path

Predecessor: 3.3C only. Integrate R4/R6/R10/R12 + manifest/oracle changes when
ready, run focused scenario/oracle tests, and record `phase3_scenario_path_head`.
This checkpoint gates Step 3.8 but **does not gate** source extraction, candidate
replay, or candidate aggregation.

If 3.4B and 3.4C become ready simultaneously, queue their short integration
critical sections in deterministic task-id order; this serialization is only for
the shared Git integration branch, not for their workers/tests before fan-in.

### Step 3.5M — extract shards and freeze the merged replay corpus

Target: 10–20 minutes.

Execute the dynamic source-shard extraction/audit fan-out defined earlier. Source
workers and their corresponding audit workers refill continuously as inputs become
ready. The orchestrator alone performs the deterministic shard merge/final corpus
freeze once all required canonical shards exist; audit workers may still be
running while unrelated source extraction/merge-ready work proceeds.

Required checks:

- `phase3_corpus_path_head` matches the extractor/provenance input lineage used by every shard;
- canonical submitted trial count agrees with Phase-1 reports;
- no submitted failure was dropped because it lacks a successful conversation;
- all positive waits use actual observed wait duration;
- overlapping intervals reproduce the existing union metric on sampled traces;
- operational window and any expiration limitation are explicit;
- corpus generation is deterministic byte-for-byte when source evidence is
  unchanged.

### Step 3.5A — complete per-source and aggregate corpus audits

This audit branch begins **before** 3.5M finishes: each per-source audit starts as
soon as its corresponding shard is frozen. After 3.5M produces the merged corpus,
start the aggregate consistency audit immediately.

Record every audit's source/shard/corpus hashes. Step 3.5A PASS requires all
mandatory Phase-1 source audits plus aggregate audit PASS against exactly the
3.5M corpus SHA. The optional operational-journal audit is required only when its
source inventory entry is available rather than `unavailable`.

A PASS releases Step 3.7 promotion/fan-in; it is **not** a predecessor for
starting Step 3.6 candidate replay.

### Replay frontier 3B — three C candidates + independent H historical comparator

Each replay task reads the same frozen corpus and writes only its own policy result files.
No source code edits during this candidate-replay frontier.

#### Step 3.6A — C120 replay

Writes:

```text
benchmarks/chat-mode-scheduling-v2/phase3-replay-c120.json
benchmarks/chat-mode-scheduling-v2/phase3-replay-c120.md
```

#### Step 3.6B — C300 replay

Writes `phase3-replay-c300.*`.

#### Step 3.6C — C600 replay

Writes `phase3-replay-c600.*`.

#### Step 3H — historical H10 replay

Writes `phase3-replay-h10.*`.

Each policy report includes corpus hash, algorithm id, preservation,
exhaustion, union-wall burden, calls clipped/nonblocking, and per-scenario table.

### Step 3.7 — promote C candidate reports and freeze live shortlist

Target: 15–20 minutes.

Orchestrator-owned fan-in after C120/C300/C600 reports are frozen **and Step 3.5A is PASS**. First apply the speculative replay promotion/invalidation contract to the three C reports; H10 may still be running. No shortlist calculation begins while any required C candidate references a non-audited corpus SHA.

Implement/validate the `shortlist` mode of
`scripts/chat_scheduling_phase3_report.py` using the frozen CLI contract above,
then write:

```text
benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.json
benchmarks/chat-mode-scheduling-v2/phase3-candidate-shortlist.md
```

Apply the **Phase-3 offline candidate gates only to C120/C300/C600**. H10 is not
eligible for `live_candidates` and cannot become `preferred_live_candidate`.
Output:

```text
rejected_candidates
live_candidates
preferred_live_candidate
open_evidence_limitations[]
Phase-4 targeted calibration requirements
```

`open_evidence_limitations` contains only limitations that do **not** invalidate
a Phase-3 offline candidate gate. A limitation that prevents a gate calculation blocks Phase 3
instead of being carried forward as vague uncertainty.

Do not declare a production budget.

### Step 3.8 — Phase-4 input-contract readiness dry run

Target: 15–20 minutes.

This step validates **inputs that Phase 4 will consume**; it must not implement
Phase-4 endpoint/harness support early. Validate without live ChatGPT trials:

- R1–R12 manifests load under the Phase-3 manifest/oracle code;
- R12 parameter rendering produces 40/150/330/630-second job runtimes for
  H10/C120/C300/C600 and expected safety-oracle semantics;
- provenance classifier works on frozen Phase-1 timeout examples;
- replay corpus + C120/C300/C600 reports + `phase3-candidate-shortlist.json` are independently parseable and share the audited corpus SHA; H10 result may still be pending because it is not a live-candidate dependency;
- write a machine-readable Phase-4 input contract at:

  ```text
  benchmarks/chat-mode-scheduling-v2/phase4-input-contract.json
  ```

  containing `live_candidates` (**C budgets only**), `preferred_live_candidate`,
  per-C-candidate budget, scenario catalog SHA, provenance-classifier commit,
  canonical v2 instruction SHA, frozen H10 policy semantics/adapter requirement,
  and required logical arm vocabulary `A/B/C/H`; it does not require the H10 replay
  result itself;
- capture only the **current hash/identity** of the historical A baseline source
  Project needed by Phase 4. The actual fresh baseline instruction snapshot is
  deliberately Phase-4 Step 4.1 work;
- explicitly assert that endpoint routing and C/H harness support are **not yet
  implemented/required** by Phase 3.

Exit: Phase 4 has complete, hashed inputs but no live environment or Phase-4
source mutation has started.

### Step 3.9 — full Phase-3 validation

Target: 10–20 minutes plus test runtime.

Run the authoritative optimized suite recorded by Step 3.0, full pre-commit, CI, C-candidate replay/shortlist determinism checks, and production isolation check. This validation may run while H10 historical replay is still finishing.

### Step 3.10 — final replay report and Phase-3 checkpoint

Predecessors: Step 3.9 PASS + Step 3H historical replay complete/promoted against
the audited corpus SHA.

Run the `chat_scheduling_phase3_report.py final` command to combine the frozen C
shortlist with H10 historical-comparator evidence into the dated canonical
`phase3-policy-replay-YYYY-MM-DD-rNN.{json,md}` report. Verify H10 uses the same
audited corpus SHA; if its provisional corpus differs, rerun only H10 before final
closeout.

The final command is **not allowed to recompute C selection**. It embeds
`candidate_shortlist_path + sha256` and copies `live_candidates` /
`preferred_live_candidate` byte-for-byte/logically identically from the frozen
shortlist artifact. A mismatch blocks closeout. H10 contributes only the
historical-comparator section/fields.

Then write/update final progress/handoff. Phase 3 is COMPLETE only when:

```text
replay corpus frozen
C120/C300/C600 evaluated and live shortlist frozen
H10 historical comparator evaluated
rejected C candidates explicitly recorded
live shortlist contains only eligible C budgets
R4/R6/R10/R12 manifests ready
timeout provenance ready
all tests + CI green
production unchanged
```

Do not start Phase 4 automatically. Phase 4's direct predecessor is the completed
Phase-3 branch; it must be created/rebased from Phase 3 rather than from
`proof-of-concept`/`master`. Public integration of the whole scheduling stack is a
later release action, not a Phase-3 completion requirement.

---
