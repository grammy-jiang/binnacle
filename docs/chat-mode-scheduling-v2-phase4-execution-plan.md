# Chat mode scheduling v2 — Phase 4 live confirmatory execution plan

Status: **PLANNED; BLOCKED UNTIL PHASE 3 COMPLETES**

This is the authoritative execution document for Phase 4 only. It assumes no
conversation memory. Phase 4 does not trust a conversational statement that
Phase 3 is done; Step 4.0 independently re-audits the Phase-3 artifacts, source
line, CI, candidate shortlist, scenario catalog, and external benchmark setup.

Phase 4 purpose: run the controlled live A/B/C confirmatory experiment plus
targeted H, select the final wall budget, and issue the formal GO/NO-GO for
staged deployment.

## Dependency summary

| Dependency | Must be true before Phase 4 implementation/live work |
| --- | --- |
| Phase 3 | Complete with at least one live C candidate |
| Replay evidence | Corpus/candidate hashes agree with final Phase-3 report |
| Scenarios | R1–R12 catalog valid, including parameterized R12 |
| Provenance | Submitted-failure classifier implemented and tested |
| Source base | Completed Phase-3 branch is the direct predecessor; lower Phase0->1->2->3 stack freshness verified |
| Benchmark environment | Isolated A/B/surviving-C/H topology is feasible; no fallback to primary connector |

Phase 4 produces the selected live budget, full A/B/C/H evidence, hard-gate
matrix, formal `GO_PHASE5` or `NO_GO_*` verdict, and the exact source/instruction
identities required by staging.

## Required references

Read before Step 4.0:

- `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md` — short cross-phase index/dependency DAG;
- `docs/chat-mode-scheduling-v2-design.md`;
- `docs/chat-mode-scheduling-v2-ab-plan.md`;
- `benchmarks/chat-mode-scheduling-v2/METRICS.md`;
- the previous phase's canonical progress and final report identified by Step 4.0.

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

#### Persistent worker scratch/state root

Any worker artifact needed for cold-start recovery, fan-in, or evidence integrity
must live under the phase-local persistent state root, not `/tmp`:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phaseN/
```

Resolve `N` to the phase number and use directory mode `0700`; files that may
contain Project/runtime details use `0600`. Disposable scenario fixtures may still
use `/tmp` when their loss is explicitly acceptable and their canonical evidence
is already frozen elsewhere. Long-running endpoint logs, readiness/provisioning
fragments, diagnostics, review fragments, orchestrator state, and recovery
metadata are persistent.

A reboot or chat restart must not force recomputation merely because `/tmp` was
cleared. If a persistent fragment is missing, use the task recovery contract to
determine whether it can be safely recomputed; never assume the external action
did not happen.

#### Single-writer orchestrator ownership and handoff

Exactly **one orchestrator owner** may mutate Phase-4 scheduler/progress/
integration state at a time. Unlimited worker sessions do not imply multiple task
managers.

Persist ownership outside Git at:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/orchestrator-owner.json
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
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/assignments/
  <task_id>--<attempt_id>.json
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/completions/
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

Task-graph materialization is part of **Step 4.0**, not a later implementation
step. After the formal dependency preflight has enough information to establish
the Phase-4 workspace and enabled conditions, but **before Step 4.0 is marked
complete or any Phase-4.1+ worker is launched**, the orchestrator must:

1. render `phase4-task-graph.json` revision `r01` from this runbook and the
   audited predecessor/handoff identities;
2. run all graph validations listed above;
3. record graph path/revision/SHA in canonical progress;
4. initialize `~/.local/state/binnacle/chat-scheduling-v2/phase4/orchestrator-state.json`
   with the static ready/blocked state implied by the graph;
5. freeze a checkpoint of that initial local state and record its SHA/time;
6. only then mark 4.0 `complete` and allow the ready-queue scheduler to launch
   Phase-4.1+ work.

If the dependency audit is BLOCKED before a valid source/workspace can be chosen,
do not invent a task graph from uncertain inputs. If the graph validator fails,
Step 4.0 is BLOCKED even when every upstream dependency itself passed.

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

Step 4.0 is the only orchestration stage that runs **before** the formal
Phase-4 task graph exists. It therefore uses a tiny bootstrap scheduler state,
not the normal phase graph/runtime state:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/bootstrap-state.json
```

Use directory mode `0700` and atomic replacement. Bootstrap task ids are the
fixed `preflight-*` ids below plus any deterministic read-only child shards
created from them. The bootstrap state records ready/claimed/running/complete/
blocked preflight tasks, attempts and read-only resource identities. It never
contains implementation/live/deployment tasks.

Step 4.0 is a fan-in gate, but its **read-only investigations are independent
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
summary/hash into the dependency-audit evidence. Only then may Step 4.0 choose/
create the canonical Phase-4 workspace, write formal progress/audit, materialize
`phase4-task-graph.json` r01, and initialize the normal
`orchestrator-state.json`. Archive (do not overwrite) the bootstrap state; later
Phase-4.1+ scheduling never uses it.

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
benchmarks/chat-mode-scheduling-v2/phase4-dependency-audit-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase4-dependency-audit-YYYY-MM-DD-rNN.md
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

### Step-4.0 cold-start/preflight workspace

Use:

```text
completed Phase-3 direct-predecessor checkout:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3
  expected branch: feature/chat-mode-scheduling-v2-phase3

public integration refs used only for lower-stack freshness checks:
  origin/proof-of-concept
  origin/master

production observation checkout:
  /home/grammy-jiang/Projects/binnacle
  expected branch: master
```

Phase 4.0 requires Phase-3 progress/handoff evidence from the Phase-3 checkout
and verifies the Phase-3 branch itself is the direct source for Phase 4;
public POC/master are freshness references, not Phase-4 parents.
If the Phase-3 checkout/handoff and lower-stack ancestry disagree, investigate
before creating the Phase-4 branch. Missing Phase-3 worktree may be reattached to
its exact branch; do not reconstruct Phase-3 evidence by copying files into
another branch.

## Step 4.0 — Dependency Audit / Entry Gate

Step 4.0 has **two ordered stages**:

1. **Read-only preflight.** From an existing safe worktree, fetch/read upstream
   branches, previous-phase progress/reports/CI, and external prerequisites. Do
   not modify the previous phase merely to record a failed preflight. If the
   evidence is already insufficient/contradictory, report the blocker and stop;
   no Phase-4 workspace is created from an unqualified base.
2. **Phase workspace bootstrap + formal audit.** Once the phase-specific preflight
   conditions below are sufficient to choose the exact canonical source base,
   create/recover the Phase-4 canonical branch/worktree defined in this
   document. Only inside that workspace create/recover:

   ```text
   benchmarks/chat-mode-scheduling-v2/phase4-progress.json
   benchmarks/chat-mode-scheduling-v2/phase4-progress.md
   ```

   If absent, initialize every phase step to `not_started`, set Step 4.0 to
   `running`, phase status to `in_progress`, and `next_step` to `4.0`. If they
   already exist, reconcile them with Git history before changing anything; never
   overwrite a prior blocked/running checkpoint merely because the chat is new.

The formal dependency-audit artifact and its revision/hash are recorded under
the progress JSON `dependency_audit` object. On audit PASS, **do not yet mark
4.0 complete**: first materialize/validate task-graph revision r01 and initialize
the persistent orchestrator state as required by the task-graph contract above.
Only after those checks pass, mark 4.0 `complete` and set `next_step=4.1`.
On a blocker discovered **after** workspace bootstrap,
leave `last_completed_step` unchanged, set phase status `blocked`, keep
`next_step=4.0`, and commit/push the blocker evidence when Git remains
available.

**No live endpoint, Project mutation, connector setup, calibration, or trial may
start before this audit passes.**

Phase 4 depends on a fully closed **Phase-3 branch as its direct predecessor**.
`master`/`proof-of-concept` are checked only to detect lower-stack staleness; they
are never Phase-4 parents.

### Required Phase-3 state

The canonical Phase-3 files are:

```text
benchmarks/chat-mode-scheduling-v2/phase3-progress.json
benchmarks/chat-mode-scheduling-v2/phase3-progress.md
```

Read `phase3-progress.json.handoff.final_report_json` / `final_report_md`; those
exact paths identify the canonical revision. Do not choose the newest-looking
`phase3-policy-replay-*` file by filename/date.

Verify:

1. `phase3-progress.json` is `complete` with no unresolved worker/task/canonical-trial slot.
2. The Phase-3 final policy-replay report exists and its hashes match the replay
   corpus plus each candidate report.
3. The final Phase-3 verdict contains at least one live cumulative candidate;
   `NO_LIVE_CANDIDATE` blocks Phase 4.
4. Every candidate in the live shortlist passed all Phase-3 reject gates; the
   preferred candidate is the smallest passing budget.
5. R4/R6/R10/R12 manifests exist and manifest validation is green.
6. The timeout-provenance classifier is implemented/tested and the Phase-1 frozen
   timeout examples classify without changing canonical inclusion.
7. Phase-3 tests/pre-commit/CI are green and its final checkpoint is the current
   `feature/chat-mode-scheduling-v2-phase3` tip. Specifically verify the handoff
   `validated_evidence_commit` equals `validated_ci_head_sha`, the recorded CI run
   concluded `success`, and a fresh query for the **current Phase-3 closeout
   HEAD** also shows green CI. Both commits must lie on the expected Phase-3
   lineage.
8. Replay corpus/candidate artifacts are deterministic and no submitted Phase-1
   slot was silently dropped.

### Required source-line state

Verify the direct stacked ancestry:

```text
Phase0 -> Phase1 -> Phase2 -> Phase3
```

and verify the Phase-3 tip/handoff is green. Compare `origin/master` and
`origin/proof-of-concept` against the public-base fingerprint recorded by Phase 3.
If new public-base work appeared after Phase 3's last stack audit, do not rebase
Phase 4 directly to public. Restack from the earliest affected lower phase, then
rebase Phase 3 on refreshed Phase 2, and rerun Phase-3 validation/handoff as
required before Phase 4 starts.

Also re-check that the completed test-efficiency runner/coverage policy inherited
through Phase 2/3 is still authoritative.

### External/environment prerequisites

Connector/Project account tooling is an explicit dependency. At planning review
time, `chatgpt-project list` succeeded while `chatgpt-refresh --list` returned
HTTP 401 `token_expired`. Treat that observation only as evidence that auth state
can differ between helpers; **re-test current auth/capability at Step 4.0** rather
than assuming either success or failure. Never copy/store authentication tokens in
benchmark artifacts.

Record current availability/status of:

- Chrome/session credentials used by the benchmark harness;
- the benchmark source Project `rp-test-sandbox` and its current instructions;
- ability to create/use the isolated A/B/surviving-C/H connector/Project topology, noting
  any one-time UI/account action that still requires the owner;
- ports 8110–8115 availability;
- production observation baseline.

Missing external registration capability may leave Phase 4 `BLOCKED_EXTERNAL`,
but it must not cause the agent to fall back to the primary production connector.

### Phase-4 workspace bootstrap inside Step 4.0

After read-only preflight proves Phase 3 complete, identifies a live candidate
shortlist, and verifies the stacked Phase0->1->2->3 lineage is fresh, create the
exact Phase-4 integration workspace **inside 4.0**, directly from the current
Phase-3 HEAD. Create progress files there, run the inherited optimized source-level
smoke, and commit the formal dependency audit.

If Phase-3 handoff/lineage is inconsistent or the inherited smoke fails, 4.0 is
BLOCKED; no live endpoint/Project setup starts.

### Audit result

Every dependency must be explicitly PASS/BLOCKED in the audit artifact. At
minimum include:

```text
phase3_progress
phase3_replay_report
live_candidate_shortlist
scenario_catalog
provenance_classifier
phase3_ci
stacked_lineage_phase0_phase1_phase2_phase3
public_base_freshness_master_and_poc
test_runner_inheritance
benchmark_project_snapshot
isolated_endpoint_prerequisites
production_isolation
```

### Exit criteria

```text
dependency audit PASS committed
Phase-3 shortlist/hash frozen
Phase-3 direct-predecessor source HEAD frozen for Step 4.1
external setup blockers = none
next allowed step: 4.1
```

## Phase-4 canonical integration workspace

```text
branch:   feature/chat-mode-scheduling-v2-phase4
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4
```

Step 4.0 creates/reuses exactly this workspace after read-only preflight. Existing dirty/diverged state is
investigated as interrupted/concurrent work; do not silently create an alternate
branch/worktree or reset it.

## Phase-4 step dependency DAG

| Work | Direct predecessor(s) | Required predecessor evidence before start |
| --- | --- | --- |
| **4.0** dependency audit | Phase 3 | Phase-3 handoff/report/hashes/CI + external preflight all PASS |
| **4.1** validate/freeze source checkpoint | 4.0 | audited shortlist + Phase-3 predecessor HEAD + test runner frozen |
| **4.2A/B/C/D** implementation frontier | 4.1 | one frozen `phase4_source_head`; all task-specific workers start from that exact HEAD |
| **4.3A** integrate runtime/harness path + local endpoint smoke | 4.2A + 4.2B | endpoint launcher + harness/evidence integrated; all started local endpoints smoke-green |
| **4.3B** integrate analyzer path | 4.2C | confirmatory analyzer/report code integrated; may complete independently of 4.3A/4.2D |
| **4.4A** core live provisioning/smoke | 4.3A + 4.2D readiness for A/B/preferred-C | core local endpoints green; A/B/preferred-C Project/connector routing verified |
| **4.4B:\<lane\>** supplemental provisioning/smoke | 4.3A + that lane's 4.2D readiness | each H/non-preferred-C lane becomes verified independently; no all-supplemental fan-in |
| **4.5** core pre-run M1/M2/M3 | 4.4A | A/B/preferred-C routing/instruction hashes verified; does not wait for confirmatory report generator |
| **4.6A** optional early timing precompute on preferred-C | 4.5 | opportunistic only when qualification host would otherwise be idle; never blocks or delays calibration critical path |
| **4.6B0** core calibration admission baseline | 4.5 | establishes a safe aggregate live-session lower bound on core lanes; does not wait for supplemental lanes |
| **4.6B:\<lane\>** per-lane calibration concurrency refinement | 4.6B0 + that lane's verified manifest | lane starts with conservative cap=1; refinement may raise cap without blocking first canonical trial |
| **4B:C** C-candidate calibration ready queue | per C task: 4.6B0 + that C lane manifest | first trial may run at per-endpoint cap=1; later trials use higher cap only after 4.6B:\<lane\> refinement |
| **4H** historical H comparator ready queue | per H task: 4.6B0 + H lane manifest | H starts at cap=1 and may use later refinement; never a C-selection predecessor |
| **4.7** select C budget | every required **C-candidate** calibration task + 4.3B | all surviving C calibration slots complete + confirmatory/report analyzer integrated; freeze C-relevant admission history |
| **4.6A:selected** authoritative selected-C timing qualification/reuse | 4.7 + selected-C lane manifest | reuse optional 4.6A only if present/applicable; otherwise fully qualify A/B/selected-C |
| **4.8** freeze confirmatory schedule | 4.7 + 4.6A:selected PASS | selected budget + selected-C `max_safe_parallel_blocks` frozen; H may still be running |
| **4.9.1–4.9.6** macro partitions | 4.8 only | frozen schedule; all six partitions are independently ready and may execute concurrently within the qualified live envelope |
| **4.10** post-run micros | **all six 4.9 partitions complete** | every scheduled main canonical slot frozen exactly once; no unfinished partition |
| **4C** evidence-review frontier | 4.10 | post-run micro evidence frozen + canonical trials immutable; fan-out partitions may start together |
| **4.11** hard-gate matrix | all canonical 4C focus artifacts | all focus aggregations + canonical metrics reconcile |
| **4.12** GO/NO-GO | 4.11 | hard-gate matrix internally consistent |
| **4H-R** historical H comparator report | all required 4H tasks | H R5/R6/R7/R12 diagnostic/control evidence aggregated; not part of C hard-gate verdict |
| **4.13** final checkpoint | 4.12 (Amendment P4-A1: not 4H-R) | C verdict fixed; H comparator complete or recorded as pending with its own follow-up; no open evidence-integrity blocker |

### Phase-4 dynamic/optional task-graph rules

Encode the live fan-out/templates so a recovered orchestrator cannot turn them
back into global barriers:

```text
4.4B:<lane>:
  dynamic_template = supplemental_lane
  expansion_source = Phase-3 live C shortlist + H, excluding preferred-C
  predecessor_rule = all_of(4.3A local-smoke:<lane>, 4.2D readiness:<lane>)
  required_for_phase = true for every surviving C and H lane

4.6A:
  task_kind = timing_precompute
  required_for_phase = false
  scheduling_class = opportunistic
  downstream_required_fan_in = none

4.6B:<lane>:
  dynamic_template = calibration_lane_refinement
  expansion_source = every started C/H lane manifest
  predecessor_rule = all_of(4.6B0, lane_manifest:<lane>)
  required_for_phase = false
  scheduling_class = opportunistic

4B:C:<candidate>:<scenario>:<repeat>:
  dynamic_template = c_calibration_trial
  expansion_source = surviving C candidates × {R5,R6,R7,R12} × repeats
  predecessor_rule = all_of(4.6B0, lane_manifest:<candidate>)
  required_for_phase = true
  live_mode = calibration

4H:<scenario>:<repeat>:
  dynamic_template = historical_h_trial
  expansion_source = H × {R5,R6,R7,R12} × repeats
  predecessor_rule = all_of(4.6B0, lane_manifest:H)
  required_for_phase = true for Phase-4 final closeout, false for 4.7/4.12 GO fan-ins
  live_mode = calibration

4.7:
  fan_in = all_of(all enabled 4B:C trial tasks, 4.3B)
  excludes = 4H tasks

4.6A:selected:
  predecessor_rule = all_of(4.7, selected-C lane manifest)
  reuse_source = optional 4.6A result only when identity/criteria hashes match
  required_for_phase = true
  live_mode = qualification

4H-R:
  fan_in = all_of(all enabled 4H tasks)
  required_for_phase = true
  excluded_from = 4.11/4.12 C gate verdict

4.13:
  fan_in = all_of(4.12)          # Amendment P4-A1: 4H-R is no longer a predecessor
  follow_up = 4H-R               # completes later; its report is appended to the handoff
```

Admission revisions are **artifacts/state**, not task predecessors that force old
trials to wait for the newest revision. A calibration task captures the newest
qualified immutable revision available at claim time and remains valid under that
revision. Later refinement creates a newer revision only for not-yet-claimed
work.

The `live-host-mode` is modeled as an exclusive resource identity on every live
qualification/calibration/confirmatory task. The stable graph therefore allows
unlimited non-live workers while mechanically preventing incompatible live modes
from overlapping.

### Phase-4 worker branch/worktree topology

Step 4.1 creates these exact implementation workers from `phase4_source_head`; all four launch immediately because their file ownership is disjoint:

```text
4.2A branch: feature/chat-mode-scheduling-v2-phase4-endpoints
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-endpoints
4.2B branch: feature/chat-mode-scheduling-v2-phase4-harness
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-harness
4.2C branch: feature/chat-mode-scheduling-v2-phase4-analysis
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-analysis
4.2D branch: feature/chat-mode-scheduling-v2-phase4-readiness
     worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-readiness
```

Targeted live calibration does **not** create code branches. Each canonical
calibration trial is an independent ephemeral worker task using frozen source and
read-only orchestration state. The orchestrator may have many such trial workers
running simultaneously, subject only to the live-resource admission envelope
qualified by the current 4.6B admission revision. Canonical trial evidence is frozen/imported by the
orchestrator; calibration workers never edit source/config/progress files.

After 4.10, create review workers from the same immutable post-run integration
HEAD:

```text
feature/chat-mode-scheduling-v2-phase4-review-correctness
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-correctness
feature/chat-mode-scheduling-v2-phase4-review-performance
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-performance
feature/chat-mode-scheduling-v2-phase4-review-reliability
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-reliability
feature/chat-mode-scheduling-v2-phase4-review-efficiency
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4-review-efficiency
```

Each canonical focus-lead worker commits only its two review artifacts. Step 4.11 orchestrator cherry-picks the four focus commits in the documented focus order before generating the canonical gate matrix. Read-only subreview workers described below may be more numerous and do not write canonical artifacts.

Implementation task mapping is by task id, not session slot:

```text
4.2A -> endpoint launcher + historical H adapter
4.2B -> multi-arm harness/evidence plumbing
4.2C -> schedule/gate analyzer
4.2D -> Project/connector readiness lead
```

All four implementation workers launch as soon as 4.1 freezes
`phase4_source_head`. The orchestrator is separate and does not consume one of
these workers. If one finishes early, any downstream work that depends only on
that worker **and other already-complete predecessors** becomes eligible
immediately; do not wait for an arbitrary batch boundary. The code fan-ins are 4.3A for A+B and 4.3B for C. Live-resource fan-ins are 4.4A for core lanes and 4.4B for supplemental calibration lanes.

Within 4.2D, after one common authenticated-control-plane preflight succeeds,
fan out one readiness worker per required benchmark lane (`A`, `B`, `H`, and each
surviving `C120/C300/C600`). Each worker holds disjoint
`project-mutate:<project>` and `connector-mutate:<profile>` locks and writes a
non-canonical readiness fragment under:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/readiness/<endpoint-id>.json
```

The 4.2D lead aggregates all fragments into the canonical
`phase4-readiness.{json,md}` on its worker branch. If the authenticated control
plane cannot safely support concurrent mutations, its observed rate/serialization
requirement becomes a resource lock for this subfrontier only; it does not limit
other workers.

**4.2D must not claim that Projects already route to final A/B/surviving-C/H connectors.**
At this point endpoints are still being implemented. Its job is to create/verify
the required benchmark Projects where supported, snapshot `rp-test-sandbox`, inspect
connector-registration capability, and record any owner UI action still needed.
Actual connector attachment/routing/schema verification occurs in 4.4A/4.4B after the relevant 4.3A local endpoint is green. Disjoint lane resources are mutated in parallel; only an
observed shared control-plane lock serializes the affected sub-operations.

Canonical 4C focus-review outputs are disjoint and fixed:

```text
correctness lead: benchmarks/chat-mode-scheduling-v2/phase4-review-correctness-safety.{json,md}
performance lead: benchmarks/chat-mode-scheduling-v2/phase4-review-performance-bootstrap.{json,md}
reliability lead: benchmarks/chat-mode-scheduling-v2/phase4-review-reliability-provenance.{json,md}
scheduling/efficiency lead: benchmarks/chat-mode-scheduling-v2/phase4-review-scheduling-efficiency.{json,md}
```

Only the orchestrator writes 4.11's canonical hard-gate matrix.

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

## Canonical Phase-4 handoff contract

Step 4.13 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase4-live-confirmatory-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase4-live-confirmatory-YYYY-MM-DD-rNN.md
```

`phase4-progress.json` `handoff` contains:

```text
final_report_json
final_report_md
final_report_json_sha256
final_report_md_sha256
verdict
selected_budget_s
phase4_source_head
baseline_instruction_sha256
v2_instruction_sha256
canonical_schedule_path
canonical_schedule_sha256
canonical_trial_count_A/B/C/H
historical_comparator_path + sha256
all_hard_gates_pass
phase5_ready = true | false
validated_evidence_commit
validated_ci_run_id
validated_ci_head_sha
validated_ci_conclusion
```

The first final report is `r01`. If a completed phase is later formally reopened,
write a new revision instead of overwriting the old one; update the progress
`handoff` to point at the new canonical revision and preserve the prior verdict
as historical evidence.

Phase 5.0 recomputes the report/hash/gate identities before staging.

## Phase-4 implementation and focused-test command contract

### Implementation-frontier 4A file ownership

```text
4.2A endpoint launcher owns:
  scripts/chat_scheduling_endpoints.py
  scripts/chat_scheduling_historical_guard.py
  tests/scripts/test_chat_scheduling_endpoints.py
  tests/scripts/test_chat_scheduling_historical_guard.py
  benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology-base.json

4.2B harness owns:
  scripts/chat_scheduling_harness.py
  scripts/chat_scheduling_runtime.py          # endpoint selection + isolated evidence capture
  scripts/chat_scheduling_evidence.py         # endpoint-log source normalization only
  tests/scripts/test_chat_scheduling_harness.py
  tests/scripts/test_chat_scheduling_analyzer_identity.py

4.2C confirmatory analyzer owns:
  scripts/chat_scheduling_confirmatory.py
  tests/scripts/test_chat_scheduling_confirmatory.py

4.2D readiness owns no production/server source and never edits the topology
base owned by 4.2A. It writes only:
  benchmarks/chat-mode-scheduling-v2/phase4-readiness.json
  benchmarks/chat-mode-scheduling-v2/phase4-readiness.md
```

4.2B must not alter the scenario/oracle definitions frozen by Phase 3 except for
a proven compatibility bug; such a bug blocks the worker and is investigated by
the orchestrator rather than silently changing benchmark semantics.

### Phase-4 baseline snapshot artifact

Step 4.1 writes:

```text
benchmarks/chat-mode-scheduling-v2/phase4-baseline.json
benchmarks/chat-mode-scheduling-v2/phase4-baseline.md
```

The repository JSON contains the current `rp-test-sandbox` Project id/name,
baseline instruction SHA-256, capture timestamp, `phase4_source_head`,
model/thinking configuration evidence, browser/profile identity needed for the
benchmark, and the canonical v2 instruction SHA-256.

Store the exact baseline instruction text outside Git at:

```text
~/.local/state/binnacle/chat-scheduling-v2/phase4/baseline-instructions.txt
```

with mode `0600`; record its SHA-256 and path in `phase4-baseline.json`. Arm A
loads this private snapshot and verifies its hash before Project setup/restore.
Do not commit future Project-specific instruction text.

Phase-4 harness arm A reads **this** snapshot. It must not continue using
`baseline-2026-09-23.json` as the live A definition. That old file remains
historical evidence only. If the baseline Project instructions change after this
snapshot and before the first submitted trial, rerun Step 4.1 / refresh the
Phase-4 dependency state before live execution. Once the first canonical trial
is submitted, changing the baseline invalidates the confirmatory experiment.

### Historical H adapter contract

H remains benchmark-only and lives entirely under `scripts/`.
`scripts/chat_scheduling_historical_guard.py` provides a thread-safe tracker
compatible with the `job_status` lease/decision interface and a benchmark server
entry point used only by endpoint H:

```text
per (client, base_turn):
  first original-positive request -> effective=min(bounded_wait, 10)
  every later original-positive request -> effective=0
```

Use policy strings:

```text
historical_one_shot
historical_one_shot_exhausted
```

The first decision exposes budget 10 and is not marked exhausted at acquisition;
later zero-wait decisions set `blocking_budget_exhausted=true`. The adapter never
enters `src/binnacle` production configuration or adds a production CLI mode.
Tests cover sequential turns, independent turns, concurrency on one turn,
idempotent release, early job exit, and later nonblocking behavior.

H server launch is owned by `chat_scheduling_endpoints.py`; endpoint H must not
start through ordinary `binnacle serve` without installing this adapter.

### Isolated endpoint registries and trial-evidence source contract

Phase 4 uses **two** registries with different purposes.

#### Static topology + per-lane immutable manifests — committed

Step 4.2A writes one immutable static base:

```text
benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology-base.json
```

It contains only deterministic non-secret identities for all reserved lanes:
endpoint id, logical arm, budget, host/port, tunnel profile, connector logical
name and planned Project name. It contains **no mutable Project id/attachment
state**, so it never needs rewriting as lanes become ready.

Each lane gets its own canonical manifest only after its Project/connector/profile
attachment and smoke are verified:

```text
benchmarks/chat-mode-scheduling-v2/phase4-lanes/A.json
benchmarks/chat-mode-scheduling-v2/phase4-lanes/B.json
benchmarks/chat-mode-scheduling-v2/phase4-lanes/C120.json
benchmarks/chat-mode-scheduling-v2/phase4-lanes/C300.json
benchmarks/chat-mode-scheduling-v2/phase4-lanes/C600.json
benchmarks/chat-mode-scheduling-v2/phase4-lanes/H.json
```

A manifest contains at least:

```text
schema_version
phase4_source_head
base_topology_sha256
endpoint_id
logical_arm
budget_s
project_name
project_id
connector_logical_name
tunnel_profile
attachment_status = verified
smoke_evidence_sha256
instruction_sha256
verified_at
```

The orchestrator is the only writer of canonical lane manifests. Provisioning
workers write private/non-canonical fragments; as soon as one lane passes, the
orchestrator validates the fragment against base/readiness/runtime hashes and
freezes that lane's manifest. **No other lane needs to be ready.**

This per-lane contract is what enables incremental live work. A canonical trial
is admissible when its own lane manifest exists and the relevant live-capacity
qualification is PASS. It never waits for an unrelated lane manifest.

For convenience/reporting, after every required lane is eventually verified the
orchestrator may generate:

```text
benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology.json
```

as a deterministic aggregate of the immutable base + lane manifests. This
aggregate is **not** a prerequisite for earlier canonical calibration trials and
is not their topology identity.

No PID, token value, cookie, API key, auth header, or secret environment content
belongs in the base, lane manifests or aggregate topology.

#### Per-trial topology identity

Before submission, every canonical trial records/hashes:

```text
base_topology_sha256
lane_manifest_path
lane_manifest_sha256
runtime_registry_sha256
admission_envelope_revision
```

The harness refuses submission if the lane manifest is absent/not verified, its
`phase4_source_head`/base SHA disagrees, or runtime endpoint identity disagrees.
Later creation of another lane manifest or the aggregate topology does **not**
invalidate an already submitted trial.

#### Runtime endpoint registry — private, not committed

`chat_scheduling_endpoints.py` atomically writes mode-`0600` runtime state to:

```text
~/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints.json
```

For each **started** lane it contains at least:

```text
endpoint_id
phase4_source_head
config_path
token_path                   # path only; never token contents
jobs_dir
socket_path
server_log_path
manager_log_path
tunnel_profile
tunnel_log_path
tunnel_health_url_path
server_pid
manager_pid
tunnel_pid
process_start_identity       # pid/start-time or equivalent stale-PID guard
```

Phase-4 progress stores this private registry's SHA-256 but not its contents.
4.2B/harness refuses an endpoint absent from the private registry, a runtime
registry whose `phase4_source_head` differs from frozen `phase4_source_head`, or a
runtime endpoint whose port/profile/budget identity disagrees with the committed base topology or its immutable lane manifest. Live submission requires that lane manifest to exist with `attachment_status=verified`.

A cold-start recovery never trusts PID existence alone: `status` verifies process
start identity, command line/worktree, port, config path and endpoint id before
reusing a runtime process. Stale/mismatched PIDs are reported and not signalled.

#### Per-trial endpoint log slices

The existing Phase-1 `capture_journal()` reads primary
`binnacle-mcp.service`/`binnacle-jobs.service`; it is **not valid canonical MCP
evidence for isolated Phase-4 trials**.

For every live trial, before submission the harness:

1. reads and hashes both static + private registries;
2. resolves exactly one physical endpoint;
3. records inode/file identity plus byte offsets for that endpoint's
   `server.log`, `manager.log`, and `tunnel.log`;
4. records the planned trial id/arm/scenario before Enter/submission evidence.

After the trial/settling window it copies only newly appended bytes into the
trial state directory:

```text
endpoint-server.log
endpoint-manager.log
endpoint-tunnel.log
endpoint-evidence.json
```

`endpoint-evidence.json` contains:

```text
endpoint_id
logical_arm
base_topology_sha256
lane_manifest_sha256
runtime_registry_sha256
server_log_identity/start_offset/end_offset/sha256
manager_log_identity/start_offset/end_offset/sha256
tunnel_log_identity/start_offset/end_offset/sha256
```

Concurrent trials on the **same physical endpoint** are allowed only through the
existing trial-correlation contract in `chat_scheduling_evidence.py`:

```text
trial seeds = run_id + nonce + fixture root + fixture job ids
        ↓ search RawCall args_raw / parsed args
matching base turn(s)
        ↓ retain only RawCalls whose call.turn is one of those matching turns
trial-local tool trace
        ↓ associate only job_ids produced/referenced by those trial-local calls
trial-local job trace
```

For Phase-4 canonical live trials, correlation must resolve to **exactly one base
turn** after server suffix normalization. Zero matching turns or more than one
distinct matching base turn is `evidence_integrity_error=true` unless a frozen,
tested product behavior explicitly proves why multiple base turns belong to one
submitted user turn. Do not choose a turn by timestamp proximity.

`endpoint-evidence.json` also records:

```text
trial_run_id
trial_nonce_sha256
matched_base_turn
matched_call_ids[]
matched_job_ids[]
raw_foreign_turns_present
normalized_foreign_calls = 0
```

Overlapping raw server/manager slices are expected when concurrent trials share an
endpoint; overlap alone is not contamination. The normalized `TrialTrace` is
canonical only after seed/base-turn/call/job filtering removes all foreign calls.
Tunnel logs are endpoint-level health/routing evidence and are never used to
attribute tool timing or job state to a specific trial.

The frozen endpoint slices plus browser/timing/conversation evidence are the
canonical MCP/tunnel evidence for that trial. Primary systemd journal may be
captured separately **only** as production-isolation evidence under:

```text
production-control-journal.log
```

It is never substituted for missing endpoint evidence.

If a log rotates/truncates, inode/file identity changes unexpectedly, an offset
moves backwards, or requested bytes cannot be recovered, the submitted trial
still owns its canonical slot and records:

```text
evidence_integrity_error = true
```

Metrics that require the missing evidence are null/unscorable. Do not rerun to
replace that submitted slot and do not borrow another endpoint/primary journal.
If the exact original bytes can be recovered from the same endpoint's immutable
retained log/archive, attach them with hashes and document the recovery; otherwise
Phase-4 final analysis must produce `NO_GO_EVIDENCE_INTEGRITY` rather than silently
shrinking the sample.

4.2B extends `chat_scheduling_evidence.py` to accept only an explicit endpoint-log
source for Phase-4 isolated trials. Tests must prove:

- a C300 nonce never appears in A/B/C120/C600/H normalized evidence;
- two or more deliberately interleaved trials on the **same endpoint** with
  overlapping raw log slices normalize into disjoint base turns/call ids/job ids;
- a zero-match or ambiguous-multiple-base-turn trial is marked evidence-integrity
  failure before metrics are accepted;
- primary-journal noise is ignored;
- byte-offset capture handles pre-existing log content;
- static/private registry hash mismatch fails **before submission**;
- stale PID/process identity cannot be reused;
- log truncation after submission produces `evidence_integrity_error=true` and
  never triggers a replacement canonical trial.

### Endpoint launcher CLI

Endpoint lifecycle is intentionally two-stage:

```bash
# Step 4.3A: local manager/server only; no external tunnel dependency
uv run python scripts/chat_scheduling_endpoints.py start-local \
  --root /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints \
  --endpoint A --endpoint B --endpoint C300 --endpoint H

# Step 4.4A/4.4B only, after the relevant profiles/control-plane attachment are ready
uv run python scripts/chat_scheduling_endpoints.py start-tunnels \
  --root /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints \
  --endpoint A --endpoint B --endpoint C300 --endpoint H

uv run python scripts/chat_scheduling_endpoints.py status \
  --root /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints

uv run python scripts/chat_scheduling_endpoints.py stop \
  --root /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints
```

`start-tunnels` fails if the endpoint is not locally healthy or its required
profile/env file is absent. It never creates profiles; 4.2D plus 4.4A/4.4B control-plane
readiness owns that responsibility.

The actual C endpoint list is generated from the Phase-3 live shortlist. `start`
fails on an endpoint id not in `A/B/C120/C300/C600/H` or on a reserved port
already owned by an unrelated process.

### Confirmatory analyzer CLI

Schedule generation:

```bash
uv run python scripts/chat_scheduling_confirmatory.py schedule \
  --seed <recorded-seed> \
  --selected-budget <120|300|600> \
  --max-parallel-blocks <K-from-4.6A:selected> \
  --output benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-schedule.json
```

Gate aggregation after review artifacts exist:

```bash
uv run python scripts/chat_scheduling_confirmatory.py gates \
  --schedule benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-schedule.json \
  --runs-root ~/.local/state/binnacle/chat-scheduling-v2/runs \
  --correctness benchmarks/chat-mode-scheduling-v2/phase4-review-correctness-safety.json \
  --performance benchmarks/chat-mode-scheduling-v2/phase4-review-performance-bootstrap.json \
  --reliability benchmarks/chat-mode-scheduling-v2/phase4-review-reliability-provenance.json \
  --efficiency benchmarks/chat-mode-scheduling-v2/phase4-review-scheduling-efficiency.json \
  --output benchmarks/chat-mode-scheduling-v2/phase4-hard-gate-matrix.json
```

### Focused test matrix

```text
4.2A:
  uv run pytest -q tests/scripts/test_chat_scheduling_endpoints.py \
    tests/scripts/test_chat_scheduling_historical_guard.py

4.2B:
  uv run pytest -q tests/scripts/test_chat_scheduling_harness.py \
    tests/scripts/test_chat_scheduling_analyzer_identity.py \
    tests/scripts/test_chat_scheduling_manifest.py

4.2C:
  uv run pytest -q tests/scripts/test_chat_scheduling_confirmatory.py \
    tests/scripts/test_chat_scheduling_analyzer.py

4.3A runtime/harness integration:
  uv run pytest -q tests/scripts/test_chat_scheduling_endpoints.py \
    tests/scripts/test_chat_scheduling_historical_guard.py \
    tests/scripts/test_chat_scheduling_harness.py \
    tests/scripts/test_chat_scheduling_evidence.py \
    tests/scripts/test_chat_scheduling_analyzer_identity.py \
    tests/scripts/test_chat_scheduling_manifest.py

4.3B analyzer integration:
  uv run pytest -q tests/scripts/test_chat_scheduling_confirmatory.py \
    tests/scripts/test_chat_scheduling_analyzer.py
```

## 19. Phase-4 objective

Measure real ChatGPT behavior under contemporaneous, controlled conditions and
answer:

> Does the full proposal C improve wall time and same-prompt completion while
> satisfying every correctness, safety, reliability, scheduling, guard, and
> efficiency gate required for staged deployment?

Main arms:

```text
A  baseline Project instructions + guard disabled
B  v2 Project instructions       + guard disabled
C  v2 Project instructions       + selected candidate guard
H  v2 Project instructions       + historical one-shot 10 s comparator
```

`A/B/C/H` are **logical analysis arms**. Physical C endpoint ids are
`C120/C300/C600`; during final confirmatory analysis, whichever candidate is
selected maps to logical arm `C`. Do not confuse logical arm names with physical
endpoint ids in trial records.

H is targeted only. It is never a production candidate, is **not** an input to
C budget selection, and is **not** a predecessor for starting the full A/B/C
confirmatory suite. H must be complete only before the Phase-4 final checkpoint so
the final report contains the historical-control evidence.

## 20. Phase-4 benchmark-isolation topology

### 20.1 Why the existing production connector is insufficient

The Phase-2 guard is keyed by client prefix, not ChatGPT Project name. Enabling a
budget for `openai-mcp` on the primary server could affect every Project using
that connector. Therefore live C/H experiments must not be done by editing the
primary production config.

### 20.1a Frozen Phase-4 source equality rule

A/B/C/H must run the same release-candidate server source commit. Do not compare
a production-master A server against a different design-branch C server. That
would confound scheduling policy with code drift.

Step 4.0/4.1 split is fixed:

1. **4.0 read-only preflight** records the current green Phase-3 HEAD and verifies
   the complete Phase0->Phase1->Phase2->Phase3 lineage/handoff.
2. **4.0 workspace bootstrap** creates the Phase-4 branch directly from that
   Phase-3 HEAD and runs a bounded inherited smoke sufficient to establish
   viability. The
   formal dependency audit records this candidate source commit.
3. **4.1 validation** runs the focused default-policy equivalence plus inherited
   optimized test/coverage gate. Only after they pass is the current commit frozen
   as `phase4_source_head`.
4. **4.2+** launches every required A/B/surviving-C/H endpoint from exactly that
   `phase4_source_head`.

A/B have the cumulative guard code present but disabled by an empty budget map.
That is the baseline server behavior for the confirmatory run. Step 4.1 records
a focused default-policy equivalence check against the Phase-3 inherited
server behavior before live measurement.

A Project instructions are recaptured from the actual baseline Project state at
Phase-4 start, before any benchmark mutation. B/C/H use the canonical v2 rule
file hash.

### 20.2 Required isolated topology

Use up to six isolated benchmark lanes, all built from the **same frozen Phase-4
code commit** and differing only in explicit arm policy/config:

```text
A endpoint:    port 8110, guard disabled
B endpoint:    port 8111, guard disabled
C120 endpoint: port 8112, cumulative budget 120 s
C300 endpoint: port 8113, cumulative budget 300 s
C600 endpoint: port 8114, cumulative budget 600 s
H endpoint:    port 8115, benchmark-only historical one-shot adapter
```

A/B/H are always required. Only cumulative candidates that survived Phase 3 need
to be started/registered, but their reserved port/name never changes. For
example, if C120 was rejected, port 8112 remains unused; C300 does not move into
8112. This keeps evidence identities stable.

Each started endpoint has its own:

```text
BINNACLE_CONFIG_FILE
jobs.dir
jobs.socket_path
token file
journal/log target
server process/unit name
tunnel profile / connector registration
```

Never share a job spool across A/B/surviving-C/H endpoint instances.

The benchmark launcher created in Step 4.2A uses this exact filesystem root:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/endpoints/<endpoint-id>/
```

For each started endpoint it writes:

```text
config.toml
token
jobs/
jobs.sock
server.log
manager.log
pids.json
```

Use `[jobs] owner = "manager"` with the arm-specific socket and jobs directory
so the live benchmark keeps the same durable-manager ownership architecture as
the managed deployment while remaining isolated from the primary manager. Start
the arm-specific manager with `BINNACLE_CONFIG_FILE=<arm config> uv run
binnacle-jobs`, then start the server with the same config using `uv run binnacle
serve --host 127.0.0.1 --port <arm port>`. The launcher owns and terminates only
those recorded PIDs. It never invokes `binnacle setup` and never edits user
systemd units.

Ports 8110–8115 are reserved by this plan. Step 4.2A must fail if any is already
in use; do not silently choose another port because connector evidence would no
longer match the frozen topology.

Fixed logical names:

```text
server units/process identities:
  binnacle-sched-a
  binnacle-sched-b
  binnacle-sched-c120
  binnacle-sched-c300
  binnacle-sched-c600
  binnacle-sched-h

tunnel profile -> connector:
  binnacle-sched-a    -> Raspberry Pi MCP Scheduling A
  binnacle-sched-b    -> Raspberry Pi MCP Scheduling B
  binnacle-sched-c120 -> Raspberry Pi MCP Scheduling C120
  binnacle-sched-c300 -> Raspberry Pi MCP Scheduling C300
  binnacle-sched-c600 -> Raspberry Pi MCP Scheduling C600
  binnacle-sched-h    -> Raspberry Pi MCP Scheduling H

ChatGPT Projects:
  rp-sched-A
  rp-sched-B
  rp-sched-C120
  rp-sched-C300
  rp-sched-C600
  rp-sched-H
```

These benchmark Projects did not exist at planning time. Step 4.2D creates A/B/H
and each C Project whose candidate survived Phase 3. Baseline instruction text is
captured at Phase-4 start from the existing benchmark source Project:

```text
rp-test-sandbox
g-p-6aaea9da2bc881918d6f9eb5177cf904
```

`rp-sched-A` receives that exact captured text. B/C120/C300/C600/H receive the canonical v2
instruction file. Once Phase-4 trials begin, no benchmark Project instruction is
mutated until the run is closed.
Instructions remain fixed for the whole live run; do not switch a shared
Project's instructions between trials.

### 20.2a Benchmark tunnel runtime contract

For each started endpoint id, use the fixed tunnel profile shown above. Its local
files follow the existing tunnel-client naming convention:

```text
profile config: ~/.config/tunnel-client/<profile>.yaml
env file:       ~/.config/tunnel-client/<profile>-tunnel.env
health URL:     ~/.local/state/tunnel-client/health/<profile>.url
```

Profile configs/env files are private deployment state (`0600`) and are not
committed. Step 4.2D uses the authenticated control plane to create/verify only
the profiles required by A/B/H and surviving C candidates, without touching
profile `binnacle`.

`chat_scheduling_endpoints.py` starts each benchmark tunnel as a child process
only after the corresponding local MCP endpoint is healthy. It uses the current
audited tunnel-client executable (planning-time path
`/home/grammy-jiang/.local/bin/tunnel-client`) and loads the profile env file into
the child environment without echoing secrets:

```text
<tunnel-client> run --profile-dir /home/grammy-jiang/.config/tunnel-client \
  --profile <fixed-profile>
```

Tunnel stdout/stderr goes to the endpoint root `tunnel.log`; PID, profile,
health-url path and log path are added to the runtime endpoint registry. Stop order
is tunnel -> MCP server -> job manager, except durable benchmark jobs are first
allowed to complete or explicitly stopped by normal benchmark cleanup.

Before a Project is attached in Step 4.4A/4.4B, require both the profile health URL and
its `/api/status` main-channel MCP probe to be healthy using the same bounded
readiness semantics as the primary `binnacle-tunnel.service`. A tunnel profile
that cannot probe its intended local endpoint blocks only that benchmark lane; it
must never be repointed to port 8000 as a fallback.

Trial evidence records tunnel-log start/end offsets along with server/manager log
offsets and copies the slice as `endpoint-tunnel.log`. Cross-endpoint tests inject
distinct nonce lines into A/C300 tunnel logs and prove normalization never mixes
them.

### 20.3 External setup boundary

Creating brand-new ChatGPT connector registrations or Projects may require one
one-time account/UI action if the existing terminal helpers cannot create them.
That is a legitimate external prerequisite, not an invitation to redesign the
experiment.

The desired topology and names above are fixed. The agent should automate every
part supported by existing tunnel/project helpers, then ask the owner only for
the minimal unsupported registration/attachment action.

### 20.4 Historical H implementation

H must not add a production runtime mode. Implement the one-shot comparator as a
**benchmark-only server adapter** under `scripts/` that installs a compatible
tracker/policy object into the benchmark H process before serving MCP. Production
`src/binnacle` defaults remain cumulative/no-policy only.

## 21. Phase-4 trial counts

Confirmatory main arms:

```text
R1-R6, R8-R11: 5 repeats per A/B/C arm
R7:              3 repeats per A/B/C arm
R12:             1 controlled safety run per relevant C budget/H arm
```

R12 is excluded from aggregate performance medians.

Targeted H:

```text
R5/R6/R7: 3 repeats
R12:      1 controlled safety run
```

### 21.1 Submission-count planning

The main confirmatory sample contains:

```text
A: 53 macro slots (50 from R1-R6/R8-R11 + 3 R7)
B: 53 macro slots
C: 53 macro slots + 1 selected-budget R12 safety slot
```

So the main A/B/C body is 159 performance slots plus one C R12 safety slot.

Targeted calibration is 10 slots per surviving C candidate:

```text
R5 3 + R6 3 + R7 3 + R12 1 = 10
```

H10 is another 10 targeted slots. If all three cumulative candidates survive
Phase 3, worst-case unique live submissions before reuse are therefore 30
candidate-calibration + 10 H. The selected candidate's calibration slots count
toward C as described below, so do not rerun those canonical submissions.

### Reuse rule for candidate calibration

If a live candidate-calibration trial uses the final frozen Phase-4 commit,
Project, endpoint, prompt, model/thinking state, scenario manifest and inclusion
rule, the selected candidate's valid canonical calibration slots may count toward
its confirmatory C slots. Do not rerun them solely because the candidate was
selected later.

## 22. Phase-4 fixed acceptance gates

C is eligible for Phase 5 only if all **required deployment gates** below pass.
The original A/B plan labels some lines as targets; this runbook classifies them
for go/no-go without changing their numeric values:

```text
REQUIRED: hard gates (5.1), all same-prompt/UX targets (5.2), all performance
          targets (5.3), all scheduling targets (5.4), all guard targets (5.5),
          token <= A+5%, and no duplicate completed-read regression.
DIAGNOSTIC TARGET: >=10% reduction in long-job redundant status-call/result
                   burden. A miss is reported but does not by itself create NO-GO.
```

A future agent must not silently promote/demote another gate category. Any desired
change to this classification requires an owner-approved amendment to the A/B plan
before analyzing the frozen confirmatory sample.

### Hard gates

```text
correctness: 100% deterministic scenario oracles
safety: zero writes outside disposable benchmark roots
tool contract: no annotation lies / no required new production tool
production isolation: primary connector/config/schema untouched
premature handoff: 0% when dependency work fits budget
```

### Same-prompt / UX

For bounded tasks fitting the selected budget:

```text
same-prompt completion >=95%
median manual continuation = 0
p90 manual continuation = 0
>=80% reduction in required continuations vs A on continuation-prone subset
interruption rate <= A + 2 percentage points
```

### Performance

```text
overall median wall >=20% faster than A
R1/R2/R11 read-heavy median >=30% faster than A
R3/R4 mixed-long median >=20% faster than A
no category >10% slower at median unless higher completion explicitly buys it
paired C/A bootstrap 95% CI upper bound <1.00
```

The `>10% slower category` exception is **not agent-discretionary**. If any
category median is more than 10% slower than A:

1. compute that same category's same-prompt completion rate for A and C;
2. the exception is even eligible only when `C completion rate > A completion
   rate`; equality or worse completion is automatic `NO_GO_PERFORMANCE`;
3. write a `CATEGORY_REGRESSION_EXCEPTION_REQUEST` artifact containing both
   rates, medians, sample counts, and canonical trial ids;
4. pause Step 4.11 and request explicit owner approval;
5. without that approval, the category regression remains a failed required gate.

The agent may never decide for itself that the completion gain is "worth" the
regression.

### Scheduling

```text
avoidable blocking wall p90 <=2 s
eligible overlap ratio >=80%
M2/M3 sliding refill remains demonstrated
```

### Guard

```text
union blocking wall <= budget + 1.0 s
overlap charged once
exhausted calls become nonblocking
p95 guard overhead <1 ms; p99 <2 ms
>=60% repeated-wait burden reduction under replay (definition b, Amendment A1)
```

### Efficiency

```text
REQUIRED: tool-result tokens <= A +5% overall
REQUIRED: no increase in duplicate completed reads
DIAGNOSTIC TARGET: >=10% reduction in long-job status-call/result burden
```

The diagnostic target is still calculated/reported in every final report and in
Phase 5/6 reference evidence; missing it is `TARGET_MISSED`, not an automatic
Phase-4 NO-GO when every required gate passes.

No later phase may waive these gates silently.

## 23. Phase-4 live-run parallelism policy

### Phase-4 live-host mode contract

Worker/resource independence is not enough for live timing work: every chat/MCP
trial ultimately shares the Pi/tunnel/browser/network environment. The
orchestrator therefore owns one **live-host mode** resource in addition to normal
per-Project/endpoint locks:

```text
idle
qualification
calibration
confirmatory
```

Mode semantics:

- `qualification` — used by 4.6A, 4.6A:selected, 4.6B0, per-lane 4.6B and any
  admission refinement. Exactly one controlled qualification experiment owns the
  host load at a time. No unrelated calibration, H, confirmatory block, or smoke
  chat may run concurrently. This prevents one qualification from contaminating
  another.
- `calibration` — shared mode for canonical C/H targeted trials. Multiple live
  sessions are admitted according to the current immutable admission revision and
  per-endpoint limits. External control-plane/read-only/off-host analysis workers
  remain unconstrained.
- `confirmatory` — reserved for canonical A/B/C performance matched blocks. The
  orchestrator may run up to the selected-C `K` matched blocks concurrently, but
  **no H/calibration/qualification/smoke live chat** overlaps this mode.
- `idle` — no benchmark live workload; provisioning/control-plane work can still
  proceed.

Changing mode is an orchestrator operation recorded with monotonic start/end
timestamps in Phase-4 runtime state. Before entering `qualification` or
`confirmatory`, wait for previously submitted calibration/smoke live tasks to
finish/settle; do not cancel a canonical submitted trial to get the lock. Tasks
that only manipulate Git, parse frozen evidence, provision external resources, or
perform read-only control-plane queries do not acquire this live-host mode and may
continue concurrently.

The purpose is **measurement isolation**, not a ChatGPT session limit. Within
`calibration`/`confirmatory`, concurrency remains as high as the measured
admission envelope permits.

Live-host critical-path priority is:

```text
1. required 4.6B0 first-admission baseline (unblocks canonical C work)
2. ready canonical C-candidate calibration work needed by 4.7
3. required selected-C 4.6A:selected qualification after 4.7
4. per-lane/aggregate admission refinements that can materially accelerate
   remaining canonical C work
5. optional early 4.6A preferred-C precompute
6. H comparator live work when no higher-priority C/confirmatory task is ready
```

Do not interrupt an already submitted canonical live trial to enforce priority;
apply priority at the next safe host-mode transition. A refinement/precompute is
useful only when it is likely to shorten the remaining critical path; otherwise
continue canonical cap-1/current-envelope work.

### Targeted budget calibration

Every canonical calibration slot (`candidate × scenario × repeat`, including H)
is an independent task once 4.6B0 has established a safe aggregate lower bound and that lane's 4.6B:\<lane\> qualification passes. The orchestrator continuously dispatches as many slots as the **current immutable admission revision** allows, respecting that revision's aggregate cap and per-endpoint limit. It may run multiple chats against the same candidate Project/endpoint only when that lane qualification permits it; each trial has unique nonce/turn evidence and
per-trial endpoint log slices. Admission is governed only by the measured live-resource envelope.

H live tasks run in `calibration` mode and therefore share the targeted-admission
envelope with C candidate trials. They never overlap `qualification` or
`confirmatory` mode. If an H trial is already submitted when confirmatory work
becomes ready, let that H trial finish/settle, switch the live-host mode, then
start the matched blocks. H resumes whenever the host returns to calibration mode.
H offline/model-side analysis can continue concurrently when it does not create
material benchmark-host load.

This keeps H off the C dependency path without biasing C-vs-A/B timing.

### Full confirmatory A/B/C

Performance timing uses **matched blocks**: one A, one B and one selected-C trial
for the same scenario/repeat class. Step 4.6A discovers how many matched blocks can
run concurrently without materially contaminating timing. Let that number be
`max_safe_parallel_blocks = K`. One running block uses three live chat sessions,
so K blocks use `3*K` sessions; K is measured, not hard-coded.

The orchestrator continuously refills up to K concurrent matched blocks. When a
block finishes, the next ready block starts immediately even while other blocks
remain active. If no concurrent matched block level passes qualification, set
`K=0` and use serial randomized arm order. This early K is provisional until
`4.6A:selected` proves it applies to the C endpoint actually selected by 4.7.

Every concurrent block records host load and per-server dispatch timing. A block
is `host_load_flagged=true` when a checkpoint 1-minute load average exceeds
`0.75 * nproc` or an available `vcgencmd get_throttled` is not `0x0`. Submitted
outcomes remain canonical and are **not replaced**. Diagnostic reruns never
replace flagged canonical slots.

## 24. Phase-4 steps

### Step 4.1 — validate and freeze the Phase-4 source checkpoint

Target: 10–15 minutes.

Predecessor: Step 4.0 PASS. The canonical Phase-4 branch/worktree and source merge
already exist; do not recreate them.

Tasks:

1. Re-read 4.0's Phase-3 predecessor HEAD, stacked lineage and test-runner
   evidence. If either upstream branch moved in a way relevant to this experiment,
   investigate and rerun 4.0 rather than silently updating the source.
2. Run the focused default-policy equivalence check against the recorded
   Phase-3 inherited behavior: empty budget map, existing tool input contract, and
   relevant baseline lifecycle tests.
3. Run the inherited optimized test/coverage gate required by 4.0.
4. Freeze the current commit as `phase4_source_head`; every A/B/C/H logical arm
   and all physical C120/C300/C600 endpoints use exactly this commit.
5. Write/verify the exact `phase4-baseline.{json,md}` artifact above and freeze
   model/UI settings, Chrome profile, baseline/v2 instruction hashes, and Phase-3
   candidate shortlist in progress.

Exit: `phase4_source_head` is immutable for the live experiment and Step 4.2 may
begin.

### Parallel implementation frontier 4A — launch every independent preparation task

#### Step 4.2A — isolated endpoint launcher worker

Target: 15–20 minutes.

Implement benchmark-only scripts/config templates that launch A/B/H plus every surviving C120/C300/C600 endpoint
with separate ports, job dirs, sockets, tokens and logs. No primary systemd/config
files are changed.

#### Step 4.2B — harness multi-arm support worker

Target: 15–20 minutes.

Extend harness metadata/CLI from A/B to A/B/C/H without embedding production
configuration mutations. The live trial CLI becomes:

```bash
uv run python scripts/chat_scheduling_harness.py trial R7 \
  --arm C --budget-s 300 --endpoint C300
```

`--arm` choices are exactly `A/B/C/H`. `--budget-s` is forbidden for A/B,
required for C, and fixed to 10 for H. `--endpoint` must be `A` for arm A, `B` for arm B, `H` for arm H, or `C<budget>` for arm C (for example C300 with budget 300). A mismatched C budget/endpoint is a validation error. Tests may inject fake endpoint mappings only through explicit fixtures. R12 resolves its runtime from
`--budget-s`. A trial record must include:

```text
arm
budget_s
endpoint_id
connector/project id
model/thinking snapshot
source HEAD
manifest hash
instruction hash
submission status
provenance classification
```

#### Step 4.2C — confirmatory analyzer/report generator worker

Target: 15–20 minutes.

Implement aggregate A/B/C/H tables, category medians, paired C/A bootstrap,
reliability deltas, hard-gate matrix and submitted-slot integrity checks. Do not
consume live data yet.

#### Step 4.2D — Project/connector external-readiness lead

Target: 15–20 minutes plus any external registration action.

This lane does **not** attach final connectors yet because 4.2A endpoint code is
still being implemented in parallel. It must:

- snapshot `rp-test-sandbox` instructions and Project id;
- create or verify `rp-sched-A`, `rp-sched-B`, `rp-sched-H`, and each surviving-candidate Project `rp-sched-C120/C300/C600` when the available
  helper/API supports creation;
- verify exact Project names/ids and record them;
- determine whether connector creation/attachment is automatable with current
  authenticated tooling;
- if one-time UI/account action is required, record the exact minimal owner action
  and mark that external prerequisite unresolved until it is completed;
- verify the primary production connector is untouched.

Actual connector attachment, endpoint routing, tool-schema verification, and
instruction-hash verification are **Steps 4.4A/4.4B**, after the relevant 4.3A local endpoint passes.

### Step 4.3A — integrate runtime/harness path and fan out local endpoint smoke

Target: short integration critical section plus parallel local smoke.

Predecessors: **4.2A + 4.2B only**. Do not wait for analyzer 4.2C or external
readiness 4.2D.

Acquire the canonical-integration lock and integrate in deterministic order:

```text
4.2A endpoint launcher / historical H adapter
4.2B harness / runtime / endpoint-evidence plumbing
```

Run their integrated focused tests, release the lock, and freeze the resulting
commit as `phase4_runtime_path_head`.

Immediately launch **one read-only smoke worker per started endpoint**. Each worker
uses the endpoint registry/runtime contract, owns only endpoint-local scratch
output, and verifies distinct job spool/log/socket/policy behavior. Endpoint
smokes are independent and must not be serialized by endpoint id:

```text
A/B: no_policy
C120/C300/C600 that survived: tracked with exactly 120/300/600 respectively
H: first wait <=10, later wait 0
```

The orchestrator aggregates smoke fragments into a local-smoke PASS artifact.
4.4A requires only core endpoints smoke-green; 4.4B separately requires supplemental endpoints smoke-green. 4.3B and 4.2D may continue
concurrently while these smokes run.

### Step 4.3B — integrate analyzer path

Predecessor: **4.2C only**. When the analyzer/report worker is ready, acquire the
canonical-integration lock, integrate its commit onto the current Phase-4 branch,
run confirmatory/analyzer focused tests, record `phase4_analyzer_path_head`, then
release the lock.

This integration does not invalidate already-running endpoint smoke workers from
`phase4_runtime_path_head`: their input commit/hash remains frozen. Core micros and live-capacity qualification do **not** need the confirmatory report generator; 4.7 is the first hard fan-in that requires 4.3B. 4.4A/4.4B provisioning also does not wait for it.

If 4.3A and 4.3B become integration-ready at the same moment, queue only their
short canonical Git critical sections by task id. Their workers/tests and all
endpoint smoke/readiness work remain parallel.

### Step 4.4A — core live Project/connector provisioning and smoke

Core timing lanes are exactly:

```text
A
B
preferred-C   # Phase-3 preferred live candidate: C120, C300, or C600
```

As soon as 4.3A local smoke plus 4.2D readiness fragments for these three lanes
are available, launch one provisioning worker
per lane. Do **not** wait for H or non-preferred surviving C candidates.

Each core provisioning worker holds only its own
`project-mutate:<project-id>` + `connector-mutate:<profile>` locks, executes the
mechanism audited by 4.2D, reads back Project/connector/profile/tool-schema state,
and runs the tiny disposable smoke chat. As each core lane passes, freeze its immutable `phase4-lanes/<id>.json` manifest. Step 4.5 becomes ready when the A, B and preferred-C manifests all exist, even while supplemental lanes continue provisioning.

### Step 4.4B — supplemental calibration-lane provisioning and smoke

Supplemental lanes are:

```text
H
all surviving C candidates other than preferred-C
```

Every supplemental lane is independent. Launch its provisioning worker as soon as
its 4.2D readiness fragment and 4.3A local smoke are available. A slow/blocked
supplemental lane does not block 4.4A/4.5.

Each worker writes only its per-lane verified fragment. As soon as a supplemental lane passes, the orchestrator freezes that lane's immutable `phase4-lanes/<id>.json` manifest and releases its per-lane 4.6B qualification path. No all-supplemental-lane fan-in is required. The aggregate topology may be generated later after all required lanes exist.

If a shared external control plane requires serialization, lock only that control
plane operation; unrelated lane smoke/readback/analysis remains parallel. An
unresolved owner UI action blocks only its affected lane until a downstream
fan-in actually requires that lane.

### Step 4.5 — pre-run micro scheduler sanity

Run M1/M2/M3 before the main session on A, B, and the Phase-3 preferred live C
candidate endpoint. H does not need a full pre-run micro set because it is only a
targeted historical comparator. This is a mechanical gate, not a visual judgment.
PASS requires all of:

```text
M1/M2/M3 deterministic correctness oracles = PASS
duplicate non-repeat logical calls = 0
M2 `read_only_peak_inflight >= 2` and `eligible_read_only_overlap_ratio > 0`
M3 relation `later_read_starts_before_slow_status_ends = true`
no connector-routing mismatch
no tool/schema error attributable to benchmark setup
```

Wall-time improvement is not a micro hard gate; these are scheduler-mechanism
sanities. If any required condition fails, stop before 4.6A/4.6B and investigate the
endpoint/Project/model/product state. Do not continue macro trials while calling
the micro failure "noise".

### Step 4.6A — optional early matched-block timing precompute on preferred-C

Predecessor: **4.5 only**. This task is an **optional latency-hiding precompute**, not a required predecessor of 4.7 or 4.8. Supplemental H/non-preferred-C lanes are irrelevant.

Schedule it only when `live-host-mode=qualification` is available **and no
admission-critical 4.6B0/per-lane qualification or ready canonical calibration
work would be delayed**. Good opportunities include waiting for supplemental
Project/connector provisioning or other external control-plane blockers. If the
live host is useful to the C-selection critical path, keep 4.6A disabled/deferred.

When it runs, every live qualification experiment acquires
`live-host-mode=qualification`; it never overlaps 4.6B load experiments or
canonical calibration.

Using A/B/preferred-C, discover an **early/provisional** `max_safe_parallel_blocks = K` with serial
reference, exponential search, then integer refinement. One block contains the
same `scenario/repeat/nonce-class` on A/B/C, so K blocks use `3*K` live chats.

At **every tested K**, run two separate qualification experiments:

```text
Q-read(K)  = K matched blocks using the read-heavy qualification case
Q-wait(K)  = K matched blocks using the wait-heavy qualification case
```

Do not run `Q-read(K)` and `Q-wait(K)` simultaneously: that would impose `2*K`
blocks while labeling the observation as K. K passes only if **both independent
experiments** pass all criteria. Record each class separately and the combined
`K_pass = read_pass && wait_pass`. Within one Q-run, continuously refill completed
blocks; qualification probes are disposable/non-canonical.

A tested K passes only if all of these hold:

- no endpoint/tunnel/cross-spool/cross-Project error;
- Pi 1-minute load <= `0.75 * nproc` and no reported throttling;
- per-arm `dispatch_ms` p95 <= `max(serial_p95 + 20 ms, serial_p95 * 2)`;
- non-blocking local implementation overhead p95 <=
  `max(serial_p95 + 20 ms, serial_p95 * 1.25)`;
- maximum qualification `dispatch_ms` <=100 ms;
- no correctness/reachability loss only at that concurrency.

After finding a pass/fail bracket at K=1,2,4,8,..., integer-refine to the highest
passing useful K. If K=1 fails, set `max_safe_parallel_blocks=0` and later use
serial randomized confirmatory arms. Record every tested K and reason.

### Step 4.6B0 — establish core calibration admission baseline

Predecessor: **4.5 only**. The **non-live orchestration/preparation** may proceed concurrently with 4.6A, but each 4.6B0 live load experiment acquires `live-host-mode=qualification` and therefore does not overlap a 4.6A live experiment.

Using the already verified A/B/preferred-C core lanes, first establish the **smallest useful passing aggregate level** with one controlled read-heavy and one wait-heavy qualification. As soon as that baseline passes, write the first immutable admission revision and release calibration work at conservative per-endpoint cap=1. Do not delay first canonical trials merely to search the maximum aggregate capacity.

After the first passing revision exists, independent aggregate-refinement tasks may continue exponential-search + integer-refinement in later `qualification` mode windows to raise the total cap.

Store admission state as a revisioned artifact:

```text
benchmarks/chat-mode-scheduling-v2/phase4-live-admission-rNN.json
```

Each revision records the tested topology/lane-manifest hashes, aggregate passing
level, per-endpoint limits known so far, tested levels and criteria. Revisions are
immutable; progress points to the newest qualified revision.

### Step 4.6B:\<lane\> — refine each calibration lane's concurrency independently

For every surviving C candidate and H, instantiate this refinement task as soon as
both conditions hold:

```text
4.6B0 first admission revision exists
that lane's immutable 4.4A/4.4B manifest exists
```

The lane is **already admissible at cap=1** at this point. Therefore its first
canonical calibration task may start immediately in `calibration` mode; this
refinement is not a predecessor for cap-1 work.

When `live-host-mode=qualification` becomes available, concentration-test the lane
with separate read-heavy and wait-heavy experiments using exponential search +
integer refinement. Each higher passing per-endpoint cap produces a new immutable
admission revision and immediately increases refill capacity for remaining tasks.
A failed higher level leaves the previous cap valid. An endpoint never tested
above 1 remains capped at 1.

Whenever a new lane becomes available, the orchestrator may launch an independent
aggregate-capacity refinement task distributing load across all currently
verified lanes. A higher passing aggregate level produces a new immutable
`phase4-live-admission-rNN.json` revision and immediately allows more concurrent
calibration work. A failed higher refinement leaves the previous passing revision
valid. Earlier trials remain valid because each records the admission revision it
used.

Before Step 4.7 fan-in, freeze one final admission summary containing the full
per-endpoint map and the highest qualified aggregate level reached across all
required calibration lanes.

### C-candidate calibration ready queue 4B:C

For every C budget that survived Phase 3, expand its canonical calibration matrix:

```text
R5 repeats 1..3
R6 repeats 1..3
R7 repeats 1..3
R12 safety repeat 1
```

Each C lane becomes eligible for cap-1 canonical work as soon as 4.6B0 has produced the first admission revision and that lane manifest exists. Higher concurrency is used only after its 4.6B:\<lane\> refinement raises the cap.
The orchestrator enters `live-host-mode=calibration`, uses the current immutable admission revision, never exceeds its aggregate/per-endpoint limits, and continuously refills as trials finish. It does
not wait for another C candidate to provision/finish.

For one C candidate, the bounded denominator is the nine R5/R6/R7 trials. Thus
`same-prompt >=95%` means **9/9 pass**, the <=10% outside-R12 exhaustion rule means
**0/9 unexpected exhaustion**, and R12 is the expected-exhaustion safety case.

### Historical comparator ready queue 4H

H10 has the same targeted task count:

```text
R5 repeats 1..3
R6 repeats 1..3
R7 repeats 1..3
R12 safety repeat 1
```

H tasks become ready at conservative cap=1 when 4.6B0 exists and the H lane manifest is verified; later H concurrency follows H's refinement revision. They
use the current live admission revision and the Phase-4 live-host mode contract above: H runs only in `calibration` mode and yields whenever `qualification` or `confirmatory` mode owns the host. H failure/completion never changes the C candidate shortlist or
blocks Step 4.7/4.8.

### Step 4.7 — select the full-confirmatory C budget

Orchestrator-owned fan-in after every required **C-candidate** calibration task is frozen. Freeze the admission revisions used by those C trials before selecting the budget; H admission/trials may continue independently.

Choose the **smallest live candidate** that simultaneously satisfies the targeted
budget-selection rules:

```text
bounded-suite same-prompt >=95%
premature handoff = 0
budget-exhaustion handoff <=10% outside R12
>=60% repeated-wait burden reduction under the frozen replay metric (definition b, Amendment A1)
0 submitted interruption among the nine bounded R5/R6/R7 calibration trials
```

If no candidate passes, Phase 4 stops NO-GO. Do not invent a fourth budget
without a new owner-approved experiment.

Record `selected_c_endpoint` as exactly `C120`, `C300`, or `C600` matching the
selected budget. All subsequent confirmatory C slots use only that endpoint and
Project; never rewrite another C endpoint's budget to impersonate the selected
one.

### Step 4.6A:selected — validate/requalify timing for the selected C endpoint

Predecessors: Step 4.7 has selected the final C budget/endpoint and that endpoint's
immutable lane manifest exists.

Compare the selected endpoint with the endpoint/hash used by the early 4.6A
qualification:

```text
selected_c_endpoint
selected_lane_manifest_sha256
phase4_source_head
A/B lane manifest hashes
qualification criteria/version
```

If an early 4.6A result **exists**, all identities match, and
`selected_c_endpoint == preferred-C`, promote it without rerunning and record
`timing_qualification_reused=true`.

If no early 4.6A result exists, the selected C differs, or any relevant
lane/source/criteria hash changed, wait until `live-host-mode=qualification` is
available, acquire that mode, and run the full read-heavy + wait-heavy
exponential-search/integer-refinement qualification using **A/B/selected-C**. No calibration/H/confirmatory live chat
may overlap this requalification. The task becomes ready immediately after 4.7
and does not depend on H comparator completion; if calibration/H work is already
submitted, let that submitted work finish/settle before switching host mode.

Write the final selected-C timing result/hash into progress. Only this result's K
is supplied to Step 4.8; the early preferred-C K is diagnostic when not reused.

### Step 4.8 — generate deterministic confirmatory schedule

Generate all remaining A/B/C slots with fixed seed recorded in progress. If
serial mode is required, randomize arm order inside each scenario/repeat block.
If parallel mode is qualified, create matched A/B/C blocks and rotate logical-arm-to-physical-session assignment deterministically across
blocks using the same recorded seed.

Write and freeze the schedule at exactly:

```text
benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-schedule.json
```

The JSON includes schedule schema version, seed, selected budget,
`max_safe_parallel_blocks`, selected C endpoint, ordered blocks/slots,
scenario/repeat/arm, and any calibration slot reused as a confirmatory slot.
`max_safe_parallel_blocks=0` means serial randomized arm execution; a positive K
means up to K matched A/B/C blocks may be concurrently active. Record its SHA-256
in progress before the
first 4.9 submission. **Freeze the schedule before running it.** After the first
submission, changing this file invalidates the confirmatory run rather than being
a normal edit.

### Step 4.9 — run confirmatory macro suite

This is the long critical lane.

Rules:

- execute exactly the frozen schedule;
- first submitted outcome owns each slot;
- keep host/tunnel health evidence around each block;
- save/analyze each trial immediately so evidence loss is detected early;
- do not rerun a submitted timeout;
- selected-budget calibration trials may count only when the **Reuse rule for candidate calibration** defined in this Phase-4 document is satisfied.

Other sessions may **read/analyze** completed block state in parallel but they
must not edit canonical progress, import/freeze trial files into Git, change live
endpoint config, or change Project instructions. They write diagnostic scratch
output only under `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/diagnostics/<worker-id>/`.
After each 4.9 group, the orchestrator alone validates slot integrity, imports any
canonical evidence artifacts, updates progress, and commits/pushes the checkpoint.

Treat Step 4.9 as six **independent tracking partitions**, not a serial chain:

```text
4.9.1  R1/R2        read-heavy
4.9.2  R3/R4        overlap + long overlap
4.9.3  R5/R6        true dependency barriers
4.9.4  R7           repeated long barriers
4.9.5  R8/R9        development + recovery journeys
4.9.6  R10/R11      quiet job + multi-round planning
```

All six partitions become ready immediately after 4.8. The orchestrator enters
`live-host-mode=confirmatory`, draws matched blocks from across the partitions and
keeps up to the selected-C `max_safe_parallel_blocks` active. There is no `4.9.1 -> 4.9.2` dependency.
When every slot belonging to one partition finishes, freeze that partition's
trial directories and write/commit its checkpoint even if other partitions are
still running. A later transaction resumes only unfinished slots from the frozen
schedule; it never restarts a submitted slot. CI failure on a checkpoint does not
replace canonical outcomes; fix source/analysis infrastructure separately.

### Step 4.10 — post-run M1/M2/M3 sanity

Repeat M1/M2/M3 on A, B, and `selected_c_endpoint` to detect a session-wide client/product change
between beginning and end.

### Evidence-review frontier 4C — unlimited read-only fan-out with four canonical focus leads

After all canonical slots are frozen, launch four canonical **focus leads**:

```text
correctness/safety lead
performance/bootstrap lead
reliability/provenance lead
scheduling/guard/efficiency lead
```

Each lead may immediately fan out read-only subreview workers over independent
partitions (for example scenario groups R1/R2, R3/R4, R5/R6, R7, R8/R9, R10/R11;
or independent metric families inside its focus). Subworkers write only hashed
scratch fragments under:

```text
/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/review/<focus>/<partition>.json
```

There is no plan-imposed number of subreview workers. The focus lead validates
all expected partitions and deterministically aggregates them into its one
canonical `{json,md}` review artifact. No lead/subworker writes the final verdict.

### 24.1 Confirmatory sample arithmetic

For C's 53 bounded macro slots, the >=95% same-prompt gate requires at least
**51/53** complete (`50/53 = 94.34%` and fails). Correctness remains 100%, so a
deterministic-oracle failure is a hard failure even if 51/53 same-prompt would
otherwise be reachable. Interruption-rate comparison uses all submitted slots,
not only completed trials.

### Step 4.11 — aggregate hard-gate matrix

Orchestrator consumes the four canonical focus reviews and produces the formal C-vs-A/B
result. A disagreement between review artifacts and canonical trial metrics is a
blocker until reconciled.

### Step 4.12 — Phase-4 go/no-go

Possible outcomes:

```text
GO_PHASE5
NO_GO_RELIABILITY
NO_GO_CORRECTNESS
NO_GO_SAFETY
NO_GO_PERFORMANCE
NO_GO_SCHEDULING
NO_GO_EVIDENCE_INTEGRITY
```

There is no ambiguous "mostly pass" deployment state. Any hard gate failure is
NO-GO.

### Amendment P4-A1: H comparator off the critical path (2026-09-25)

Owner decision 2026-09-25 17:50, together with two execution changes that do
not alter this plan's content: sequential orchestrator-owned steps may be run
in one chat, and benchmark trial sends may be 45-60 s apart (never two at
once; the orchestrator's other sends keep >= 2 minutes).

- H stays a required diagnostic comparator; its trials keep running in
  `calibration` mode whenever no C/qualification/confirmatory work needs the
  live host (the critical-path priority list above is unchanged).
- 4.13 no longer waits for 4H-R. A Phase-4 handoff with H `pending` is valid;
  the 4H-R report is appended to the handoff when it is frozen.
- An H evidence-integrity failure is still disclosed and resolved before the
  Phase-4 record is called complete; it does not block the GO/NO-GO verdict,
  which never used H.

### Amendment P4-A2: routing-miss rule (2026-09-25)

Owner decision 2026-09-25 23:50 ("Exclude and rerun"). Evidence: ChatGPT has
no per-Project connector pinning. A trial reaches its lane through the lane
app's composer system hint, which makes ChatGPT prefer that app but does not
force it. After the D4 fix, 1 of 44 trials (`q-read-1-a`, lane A, 2026-09-25
23:45) sent all its calls to the production connector although its recorded
send body carried lane A's hint.

- **Definition.** A trial is a `ROUTING_MISS` when none of its fixture calls
  appear in its own lane's endpoint server log and at least one appears in
  another server's log (the production `binnacle-mcp` journal or another
  lane's server log), matched by the trial's unique fixture root. The routing
  choice happens at the first tool call, before any outcome exists, so this
  classification cannot favor an arm.
- **Handling.** A `ROUTING_MISS` did not receive its arm's treatment. It is
  recorded with its evidence (state dir, where the calls went, the send body
  with its hint), excluded from every arm metric and gate, and its slot is
  submitted again; the first correctly routed submission owns the slot. At
  most three submissions per slot; a slot that misses three times is
  unscorable under the existing evidence-integrity rules.
- **Reporting.** Every report states the routing-miss count and rate per arm.
  A rate above 10% in any arm makes the Phase-4 verdict
  `NO_GO_EVIDENCE_INTEGRITY`.
- **Isolation.** Calls that a miss sent to the production server are recorded
  as non-mutating isolation incidents (read-only fixture reads, fixture jobs
  under `/tmp`). The hard gate "primary connector/config/schema untouched" is
  not affected, because nothing is changed.
- **Scope.** This amends "first submitted outcome owns each slot" only for
  `ROUTING_MISS`. Every other failure keeps that rule.

### Step 4H-R — aggregate historical H comparator

Predecessor: every canonical H R5/R6/R7/R12 task is frozen. This step may run in
parallel with A/B/C evidence review and 4.11/4.12 once H is complete.

Write:

```text
benchmarks/chat-mode-scheduling-v2/phase4-historical-comparator.json
benchmarks/chat-mode-scheduling-v2/phase4-historical-comparator.md
```

Report H correctness, same-prompt/continuation behavior, interruption/provenance,
budget-exhaustion R12 behavior and comparison against selected C on the targeted
scenarios. H is diagnostic: these values do not alter the required C gate matrix
or the 4.12 verdict. Evidence-integrity failure in H must still be disclosed and
resolved/reported before Phase 4 can be called complete.

### Step 4.13 — Phase-4 final validation/checkpoint

Amendment P4-A1 (owner, 2026-09-25 17:50): 4.13 does not wait for 4H-R. If
the 4H-R artifact/hashes are frozen, verify them; otherwise record H as
`pending` in the handoff with the H tasks still open, and 4H-R completes as a
follow-up whose report is appended to the handoff when it is frozen. Then write
the dated Phase-4 JSON/Markdown report, update progress, run optimized full tests,
pre-commit, CI, production isolation, and endpoint cleanup validation. Do not
delete evidence required by Phase 5/6.

Phase 5 may start only after explicit owner approval of `GO_PHASE5`.

---
