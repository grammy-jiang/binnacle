# Chat mode scheduling v2 — Phase 6 post-deployment review and final integration plan

Status: **PLANNED; BLOCKED UNTIL PHASE 5 COMPLETES**

This is the authoritative execution document for Phase 6 only. Step 6.0
reconstructs the Phase-5 deployment state and cross-checks identities against
Phase 4 before any operational review begins.

Phase 6 purpose: perform the Stage-2 T+24h and T+7d reviews, decide final
operational GO/rollback, and — only after explicit approval — perform primary
integration followed by a final 24-hour primary-cutover confirmation.

## Dependency summary

| Dependency | Must be true before Phase 6 review |
| --- | --- |
| Phase 5 | Complete; not rolled back/blocked |
| Stage 1 | Final Phase-5 Stage-1 observation verdict `PASS_STAGE1` after the recorded 24/48/72h window |
| Stage 2 | `Raspberry Pi 5` is on the approved staging path; immediate smoke passed |
| Experiment identity | Budget/source/instruction/connector identities still match Phase 4/5 |
| Timing | Exact Stage-2 `T0` recorded |
| Rollback | Valid snapshots/actions still available |

Phase 6 produces the T+24h and T+7d operational verdicts and, only after GO plus
explicit approval, the primary integration and final 24-hour primary-cutover
confirmation.

## Required references

Read before Step 6.0:

- `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md` — short cross-phase index/dependency DAG;
- `docs/chat-mode-scheduling-v2-design.md`;
- `docs/chat-mode-scheduling-v2-ab-plan.md`;
- `benchmarks/chat-mode-scheduling-v2/METRICS.md`;
- the previous phase's canonical progress and final report identified by Step 6.0.

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

#### Live-resource admission control

CPU/network/tunnel/browser limits are **measured runtime constraints**, not fixed
chat-count rules. Live benchmark/deployment tasks declare a live-resource class.
The orchestrator admits as many as the current qualification/health evidence
supports and stops increasing concurrency when correctness, routing, dispatch,
load, throttling, or interruption criteria fail. A later section may define a
special stricter admission rule for performance timing; that rule limits only the
contended live resource, not unrelated analysis/code/review workers.

#### Progress fields for parallel scheduling

Canonical progress records enough state for a new orchestrator to reconstruct the
scheduler without conversation memory:

```text
ready_tasks[]
running_tasks[]        # task id, worker branch/session label, input hashes
resource_locks{}       # resource id -> owning task
completed_worker_commits{}
blocked_tasks{}        # blocker and unaffected-ready-work note
```

These are orchestration state, not a license for workers to edit canonical
progress concurrently.

### Dependency-audit preflight fan-out

Step N.0 is a fan-in gate, but its **read-only investigations are independent
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
benchmarks/chat-mode-scheduling-v2/phase6-dependency-audit-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase6-dependency-audit-YYYY-MM-DD-rNN.md
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

### Step-6.0 cold-start/preflight workspace

Use:

```text
Phase-5 coordination/staging checkout:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-staging
  expected branch: release/chat-mode-scheduling-v2-staging

pinned staging runtime checkout:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime
  expected state: detached at approved_runtime_source_head

production observation checkout:
  /home/grammy-jiang/Projects/binnacle
  expected branch: master
```

Read the Phase-5 progress/handoff/report from the coordination checkout and verify
the detached runtime checkout/service identity independently. If the coordination
worktree is absent, reattach its exact branch. If the runtime worktree is absent
while staging services are supposedly active, that is a blocker; do not recreate
it blindly because its absence contradicts the Phase-5 deployment evidence.

## Step 6.0 — Dependency Audit / Entry Gate

Step 6.0 has **two ordered stages**:

1. **Read-only preflight.** From an existing safe worktree, fetch/read upstream
   branches, previous-phase progress/reports/CI, and external prerequisites. Do
   not modify the previous phase merely to record a failed preflight. If the
   evidence is already insufficient/contradictory, report the blocker and stop;
   no Phase-6 workspace is created from an unqualified base.
2. **Phase workspace bootstrap + formal audit.** Once the phase-specific preflight
   conditions below are sufficient to choose the exact canonical source base,
   create/recover the Phase-6 canonical branch/worktree defined in this
   document. Only inside that workspace create/recover:

   ```text
   benchmarks/chat-mode-scheduling-v2/phase6-progress.json
   benchmarks/chat-mode-scheduling-v2/phase6-progress.md
   ```

   If absent, initialize every phase step to `not_started`, set Step 6.0 to
   `running`, phase status to `in_progress`, and `next_step` to `6.0`. If they
   already exist, reconcile them with Git history before changing anything; never
   overwrite a prior blocked/running checkpoint merely because the chat is new.

The formal dependency-audit artifact and its revision/hash are recorded under
the progress JSON `dependency_audit` object. On PASS, mark 6.0 `complete` and
set `next_step=6.1`. On a blocker discovered **after** workspace bootstrap,
leave `last_completed_step` unchanged, set phase status `blocked`, keep
`next_step=6.0`, and commit/push the blocker evidence when Git remains
available.

**No Phase-6 operational window analysis or final integration may begin before
this audit passes.**

Phase 6 depends on Phase 5 having successfully staged the policy through the
first Project and then the normal Raspberry Pi development Project.

### Required Phase-5 state

The canonical Phase-5 files are:

```text
benchmarks/chat-mode-scheduling-v2/phase5-progress.json
benchmarks/chat-mode-scheduling-v2/phase5-progress.md
```

Read the exact final report paths from `phase5-progress.json.handoff`. Do not
select a Phase-5 report by glob/date.

Verify:

1. `phase5-progress.json` is `complete`, not `rolled_back` or `blocked`.
2. Stage 1 (`Binnacle`) deployment timestamp, exact instruction snapshot,
   connector mapping, selected budget, and staging source hash are recorded.
3. Stage-1 immediate smoke passed.
4. The genuine Stage-1 observation gate elapsed for the final Phase-5 duration
   (24, 48, or 72 hours unless a later owner-approved plan revision exists); the
   corresponding cumulative four-review set exists and the final Stage-1 verdict
   is `PASS_STAGE1`.
5. Stage 2 (`Raspberry Pi 5`) switch is recorded with exact `stage2_started_at =
   T0`, instruction snapshot, connector mapping, and rollback state.
6. Stage-2 immediate smoke passed and the Project is actually using the same
   selected budget/source/instructions approved by Phase 4/5.
7. No hard rollback condition occurred between Stage 2 start and Phase-6 entry.
8. Persistent staging server/manager/tunnel are healthy; durable jobs are not
   stranded in an obsolete endpoint. The staging units' `WorkingDirectory`/command
   resolves to `/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime`,
   that worktree is detached at `approved_runtime_source_head`, and it is clean.
9. Phase-5 progress/evidence hashes and CI/test evidence are consistent. Verify
   handoff `validated_evidence_commit == validated_ci_head_sha`, the recorded CI
   conclusion is `success`, and a fresh query shows the current Phase-5 closeout
   HEAD CI is green. Both commits must be on the expected Phase-5 lineage.

### Cross-phase consistency check

Recompute/compare these immutable identities across Phase 4 -> Phase 5 -> Phase 6:

```text
selected_budget_s
approved_runtime_source_head
v2_instruction_sha256
instruction_merge_helper_commit
staging_connector identity
staging config sha256 (except explicitly documented runtime-only fields)
Phase-4 reference report sha256
```

Any unexpected mismatch blocks Phase 6 until explained. Do not silently treat a
changed deployment as the same experiment.

### Phase-6 workspace bootstrap inside Step 6.0

After the read-only preflight proves Phase 5 complete and identifies the exact
staging HEAD/T0/identities, create/recover the Phase-6 canonical review workspace
defined below from that staging HEAD. Create progress files there, freeze the
Phase-4/5 references, and commit the formal dependency audit. Do not perform
primary integration during 6.0.

### Audit result

Required rows include:

```text
phase5_progress
stage1_observation_gate
stage2_started_at
stage2_smoke
selected_budget_identity
source_identity
instruction_identity
staging_connector_health
rollback_state
phase4_reference_integrity
production_observation_baseline
```

### Exit criteria

```text
dependency audit PASS committed
T0 / T+24h / T+7d timestamps frozen
Phase-4/5 reference hashes frozen
staging rollout confirmed healthy at entry
next allowed step: 6.1
```

## Phase-6 canonical review workspace

```text
branch:   release/chat-mode-scheduling-v2-phase6-review
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase6-review
```

Step 6.0 creates/reuses this workspace from the exact Phase-5 staging branch HEAD
recorded by the Phase-5 handoff after read-only preflight. This branch stores only
Phase-6 progress/evidence/review changes until Step 6.7; it is not the primary
integration branch. Dirty/diverged state is investigated, never reset or replaced
with an alternate name.

## Phase-6 step dependency DAG

| Work | Direct predecessor(s) | Required predecessor evidence before start |
| --- | --- | --- |
| **6.0** dependency audit | Phase 5 | Phase-5 handoff/T0/identities/rollback/staging health all PASS |
| **6.1** initialize windows | 6.0 | committed PASS audit + exact T0 |
| **6.2** T+24h freeze | 6.1 + wall clock >=T+24h | exact timestamp-bounded data available |
| **6A** T+24h review frontier | 6.2 | one immutable T+24h evidence snapshot/hash; all independent subreviews ready together |
| **6.3** T+24h gate | all canonical focus artifacts + integrity/activity audits | same evidence hash; all focus fan-ins complete |
| **6.4** wait to T+7d | 6.3=`CONTINUE_TO_7D` or `CONTINUE_TO_7D_LOW_VOLUME` | no rollback/hard failure |
| **6.5** T+7d freeze | wall clock >=T+7d | full and incremental immutable windows frozen |
| **6B** T+7d review frontier | 6.5 | both window hashes frozen; all independent subreviews ready together |
| **6.6** final operational verdict | all canonical T+7d focus artifacts + integrity/activity audits | all focus fan-ins reconcile + no evidence blocker |
| **6.7** primary release-candidate deployment | 6.6=`GO_PRIMARY_INTEGRATION` + explicit owner approval | pre-cutover dependency refresh PASS |
| **6.8** primary smoke + 24h confirmation | 6.7 | cutover commit/config/instructions/consumer inventory frozen |
| **6.9** final evidence/repository closeout + cleanup | 6.8=`PRIMARY_CONFIRMATION_PASS` | no rollback condition, primary state healthy |

Because Phase 6 deliberately spans at least seven days, **Step 6.7 must perform
a fresh pre-cutover dependency investigation** before touching primary:

- fetch latest `origin/proof-of-concept` and `origin/master`;
- compare them with the heads recorded at 6.0 and with the approved scheduling
  release lineage;
- inspect all new intervening commits that touch scheduling-related source,
  config, systemd, tunnel, jobs, tests, or Project integration;
- refresh connector consumer inventory and exact current Project instructions;
- if new work changes assumptions or conflicts with the approved rollout, stop
  and reconcile/test it before integration. Do not reset newer development to the
  week-old audited state.

This pre-cutover refresh is required even when 6.0 was PASS; the elapsed time is
long enough that upstream drift is expected rather than exceptional.

### Phase-6 dynamic review topology

Every frozen Phase-6 evidence window uses the same pattern: **many read-only
subreview workers -> four canonical focus leads -> orchestrator verdict**. The
four focus outputs are a reporting contract, not a session limit.

Canonical focus-lead branches for T+24h:

```text
feature/chat-mode-scheduling-v2-phase6-t24-reliability
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase6-t24-reliability
feature/chat-mode-scheduling-v2-phase6-t24-blocking
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase6-t24-blocking
feature/chat-mode-scheduling-v2-phase6-t24-efficiency
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase6-t24-efficiency
feature/chat-mode-scheduling-v2-phase6-t24-workflow
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase6-t24-workflow
```

T+7d uses the same exact branch/worktree pattern with `t7d-*`. Primary-cutover
confirmation uses `primary24-*`; a 48-hour extension uses fresh `primary48-*`
branches. Never reuse an earlier-window focus branch.

For each window the orchestrator immediately fans out all independent subreview
partitions against the same evidence SHA. Default partition set:

```text
reliability/*:
  mcp-server-errors
  job-manager-errors
  tunnel-connector-health
  interruptions-outages

blocking/*:
  union-wall-budget
  exhaustion-classification
  wait-distribution
  overlap-accounting

efficiency/*:
  tool-result-tokens
  job-status-call-burden
  concurrency-overlap
  duplicate-completed-reads

workflow/*:
  same-turn-proxy
  continuation-incidents
  tagged-validation-correctness
  activity-sufficiency
```

The orchestrator may add more read-only partitions when evidence naturally splits
(for example per scenario class or per day) as long as ownership/output names are
disjoint and the canonical focus lead knows the complete expected partition list.
There is no plan-imposed worker count.

Subreviews write scratch fragments only:

```text
/tmp/binnacle-chat-scheduling-v2/phase6/review/<window>/<focus>/<partition>.json
```

A focus lead becomes ready as soon as all partitions for **that focus** finish; it
does not wait for the other three focus families. It verifies evidence/fragment
hashes and writes one canonical `{json,md}` artifact. The orchestrator writes the
6.3/6.6/6.8 verdict only after the required canonical focus artifacts exist.

Canonical T+24h outputs:

```text
reliability: benchmarks/chat-mode-scheduling-v2/phase6-t24h-reliability.{json,md}
blocking:    benchmarks/chat-mode-scheduling-v2/phase6-t24h-blocking-wall.{json,md}
efficiency:  benchmarks/chat-mode-scheduling-v2/phase6-t24h-efficiency.{json,md}
workflow:    benchmarks/chat-mode-scheduling-v2/phase6-t24h-workflow-ux.{json,md}
```

Canonical T+7d outputs:

```text
reliability: benchmarks/chat-mode-scheduling-v2/phase6-t7d-reliability.{json,md}
blocking:    benchmarks/chat-mode-scheduling-v2/phase6-t7d-blocking-wall.{json,md}
efficiency:  benchmarks/chat-mode-scheduling-v2/phase6-t7d-efficiency.{json,md}
workflow:    benchmarks/chat-mode-scheduling-v2/phase6-t7d-workflow-ux.{json,md}
```

Every canonical focus artifact records the exact evidence-window SHA(s) it
analyzed.

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

## Canonical Phase-6 final-report contract

Step 6.9 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase6-post-deployment-review-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase6-post-deployment-review-YYYY-MM-DD-rNN.md
```

`phase6-progress.json` records the T+24h verdict, T+7d verdict, final operational
verdict, primary-integration approval/commit if performed, primary confirmation verdict/hours, cleanup state, rollback-retention deadline, final Phase 0–6 retrospective
path, and the closeout CI attestation fields `validated_evidence_commit`,
`validated_ci_run_id`, `validated_ci_head_sha`, and
`validated_ci_conclusion`.

The first final report is `r01`. If a completed phase is later formally reopened,
write a new revision instead of overwriting the old one; update the progress
`handoff` to point at the new canonical revision and preserve the prior verdict
as historical evidence.

There is no implicit next phase.

## Phase-6 operational tool reuse contract

Phase 6 reuses `scripts/chat_scheduling_operational.py` from Phase 5. Step 6.0
verifies its file hash/commit is on the Phase-5 handoff lineage and reruns:

```bash
uv run pytest -q tests/scripts/test_chat_scheduling_operational.py
```

Every 6.2/6.5/6.8 evidence freeze invokes the `freeze` subcommand with explicit
`--start` and `--end`; every parallel review invokes `review --focus ...` against
the already frozen JSON. If the tool requires a behavioral fix during Phase 6,
stop, test the fix, record the new tool commit/hash in progress, and ensure all
review lanes for the affected window use the same fixed version. Never let four
workers parse the raw journal with different ad-hoc commands.

## Phase-6 Project-instruction helper reuse contract

Phase 6 reuses `scripts/chat_scheduling_project_instructions.py` from Phase 5.
Step 6.0 verifies its commit/hash is on the Phase-5 handoff lineage and reruns:

```bash
uv run pytest -q tests/scripts/test_chat_scheduling_project_instructions.py
```

Every 6.7 primary Project mutation uses the helper's `merge`/`verify` contract
and exact private pre-cutover snapshots; no Project instruction string is edited
manually.

## 29. Phase-6 objective

Determine whether the staged policy remains healthy under real development use,
first at 24 hours and then at 7 days, before final primary integration.

Reference time `T0` is `stage2_started_at` from Phase 5.

Required review points:

```text
T0 + 24 h
T0 + 7 d
```

## 30. Operational metrics

Report at both windows:

```text
turns / tasks observed
long-job same-turn completion proxy
positive job_status waits
blocking-wall p50 / p90 / p95 / max
budget utilization and exhaustion
read-only concurrency / eligible overlap proxies where available
tool-result tokens and bytes
job_status call burden
stream/request interruption count
connector errors/outages
user continuation prompts from tagged/known development workflows
correctness/safety incidents
```

### 30.1 Long-job same-turn completion proxy

For operational telemetry where the benchmark oracle is unavailable, derive a
proxy from correlated `turn` and `job_id` evidence:

- a job launched in one base turn and observed to reach its required terminal
  status in that same base turn counts as same-turn completion for the proxy;
- a later base turn that resumes status/work for the same job indicates a
  cross-turn continuation;
- this proxy is reported as an operational signal, never mislabeled as the exact
  benchmark same-prompt metric.

### 30.2 User continuation prompts

The MCP journal cannot see arbitrary user prose. Count continuation prompts only
from benchmark evidence or development sessions explicitly tagged/recorded for
this rollout. Do not infer user text from server timing alone.

## 31. Phase-6 hard rollback conditions

### Phase-6 staging rollback SOP

Before primary cutover, a Phase-6 rollback uses the exact Phase-5 Project
snapshots and staged rollback order. Freeze the triggering evidence window first,
restore `Raspberry Pi 5`; restore `Binnacle` too when the fault is shared staging
behavior. Preserve the staging runtime/spool until durable jobs are terminal or
explicitly stopped. Mark Phase 6/5 rollout state `rolled_back`; do not continue to
6.7.

### Private primary-cutover rollback snapshot

Before Step 6.7 mutates primary code/config/Project routing, the fresh pre-cutover
investigation must write exact rollback material outside Git at:

```text
~/.local/state/binnacle/chat-scheduling-v2/phase6/pre-primary-cutover/
  production-git-head.txt
  production-status.txt
  config.snapshot
  server-unit.snapshot
  jobs-unit.snapshot
  tunnel-unit.snapshot
  connector-consumers.json
  project-instructions/<project-id>.txt
  project-connectors/<project-id>.json
```

Use directory mode `0700`, file mode `0600`. Repository progress stores only the
path plus SHA-256 for each snapshot item and non-sensitive Project ids/names. Do
not commit or print credentials/tokens. `connector-consumers.json` records every
known Project attached to the primary connector and whether it is owner-approved
for this rollout. Any unapproved consumer blocks budget enablement.

The snapshot is complete only when every Project that 6.7 will mutate has both an
instruction snapshot and connector mapping, primary config/unit files are hashed,
and the exact pre-cutover deployed Git HEAD is recorded. Missing snapshot material
means 6.7 is `BLOCKED_EXTERNAL`/`BLOCKED_EVIDENCE`; do not mutate primary first
and try to reconstruct rollback state afterward.

### Primary-cutover rollback SOP

After Step 6.7 has changed the primary deployed candidate/config/instructions, a
hard rollback uses the pre-6.7 snapshots captured by the fresh pre-cutover
investigation. Execute in this order:

1. freeze failure evidence and current primary unit/config/instruction/connector
   hashes;
2. restore Project instructions and connector mappings for every primary consumer
   changed by 6.7;
3. restore the pre-6.7 deployment-local config (removing the selected budget);
4. restore/redeploy the exact pre-6.7 primary runtime commit using the repository's
   audited deployment mechanism;
5. restart/verify primary jobs/server/tunnel only as required by that deployment
   mechanism; never stop durable jobs merely to simplify rollback;
6. run the primary read-only smoke plus one status check for any surviving job;
7. verify primary unit/config/runtime/Project hashes against the pre-6.7 snapshot;
8. keep the qualified staging endpoint restartable as the investigation fallback;
9. record `ROLLBACK` and stop final repository synchronization.

If repository history had already reached `proof-of-concept` during 6.7 because
the current release workflow required it, do not rewrite published Git history.
Revert/fix forward according to the repository workflow; `master` is still not
finalized until 6.9.

Rollback staging immediately on any of:

```text
deterministic correctness/safety regression attributable to scheduling v2
primary connector reachability harm caused by rollout
any tracked turn blocking wall > configured budget + 1.0 second
two or more rollout-tagged premature handoffs in any rolling 24-hour window on
  work whose known dependency requirement fits the selected budget; one such
  handoff is an immediate investigation alert
interruption rate > Phase-4 C +2 percentage points with >=20 eligible turns, or
  at least two attributable excess interruptions when sample size is smaller
three or more staging-attributable connector/server failures in any rolling 24 h,
  or one outage >60 seconds
```

A single unexplained observation should be investigated, but hard safety failures
do not wait for the 7-day review.

## 32. Phase-6 steps

### Step 6.1 — initialize review windows

Verify the Phase-6 progress files created/recovered by Step 6.0, then record exact
T0, T+24h and T+7d. Freeze Phase-4/5 reference reports and production baseline
hashes.

Schedule five disposable, explicitly tagged Stage-2 validation turns across the
seven-day window using the same V1–V5 Phase-5 classes. Run **at least V1 and V2
inside the first 24 hours** and the remaining three by T+7d. They test rollout
semantics but are reported separately from ordinary `Raspberry Pi 5` development
turns and do not satisfy the ordinary-usage minimum by themselves.

### Step 6.2 — T+24h data freeze

At or after T+24h, freeze exactly `[T0, T0+24h)` into normalized,
privacy-minimized evidence:

```text
benchmarks/chat-mode-scheduling-v2/phase6-t24h-evidence.json
benchmarks/chat-mode-scheduling-v2/phase6-t24h-evidence.md
```

Record the JSON SHA-256 in progress. Do not extend the window opportunistically
because the review was started late; use timestamps. Every T+24h subreview and focus lead reads this exact artifact/hash.

### T+24h review frontier 6A — dynamic read-only fan-out

Immediately enqueue the full Phase-6 subreview partition set defined in
**Phase-6 dynamic review topology**. All partitions share the frozen T+24h
evidence SHA; focus leads launch independently as soon as their own partitions
complete.

### Step 6.3 — T+24h gate

Orchestrator fan-in. First evaluate hard rollback conditions after the required canonical focus artifacts/integrity checks are complete. If none fired, classify
first-day evidence volume. `CONTINUE_TO_7D` requires at least:

```text
10 eligible Stage-2 turns total
5 ordinary Raspberry Pi 5 development turns (not rollout-validation)
3 turns containing a positive job_status wait
2 tagged rollout-validation turns (V1 and V2) complete
```

If evidence is internally complete but below a usage minimum, use
`CONTINUE_TO_7D_LOW_VOLUME`; low first-day volume is not itself a reason to stop
the intended seven-day observation. If the frozen evidence is missing/corrupt and
therefore cannot assess safety, use `BLOCKED_EVIDENCE`.

Possible outcomes:

```text
CONTINUE_TO_7D
CONTINUE_TO_7D_LOW_VOLUME
ROLLBACK
BLOCKED_EVIDENCE
```

Both CONTINUE outcomes allow Step 6.4. `ROLLBACK` stops the rollout.
`BLOCKED_EVIDENCE` must be resolved before continuing because safety state is
unknown. Progress records which first-day minimums were missing.

### Step 6.4 — wait to T+7d

Intentional wall-clock gate. Progress becomes `waiting_wall_clock` with exact
`resume_not_before`.

### Step 6.5 — T+7d data freeze

Freeze both half-open windows into fixed artifacts:

```text
[T0, T0+7d)
  benchmarks/chat-mode-scheduling-v2/phase6-t7d-evidence-full.json
  benchmarks/chat-mode-scheduling-v2/phase6-t7d-evidence-full.md

[T0+24h, T0+7d)
  benchmarks/chat-mode-scheduling-v2/phase6-t7d-evidence-days2-7.json
  benchmarks/chat-mode-scheduling-v2/phase6-t7d-evidence-days2-7.md
```

Record both JSON SHA-256 values in progress so late degradation is not hidden by
averaging with the first day. Every T+7d subreview/focus lead reads these same hashes.

### T+7d review frontier 6B — dynamic read-only fan-out

Launch the full dynamic subreview partition set again against both frozen T+7d
window hashes. Each subreview/focus lead compares the relevant metrics across:

```text
Phase-4 confirmatory C
Phase-5 Stage-1 final cumulative observation
Phase-5 Stage-1 first 24 h
Phase-6 first 24 h
Phase-6 days 2–7
full 7 d
```

Per-day or per-scenario-class subworkers may be added freely when they reduce wall
time; the canonical focus leads remain the deterministic fan-in boundary.

### Step 6.6 — final operational go/no-go

A `GO_PRIMARY_INTEGRATION` verdict requires the full seven-day staging evidence
to contain at least:

```text
50 eligible Stage-2 turns total
25 ordinary Raspberry Pi 5 development turns not generated solely for rollout validation
10 turns containing at least one positive job_status wait
5 explicitly tagged rollout-validation long-job turns mapped to Phase-4 scenario classes
```

If these minima are not met and no hard rollback condition fired, the only
allowed non-failure outcome is `EXTEND_OBSERVATION_WITH_OWNER_APPROVAL`; do not
turn low usage into a GO. The incremental days-2–7 window is still reported even
when the full-window volume is insufficient.

Possible outcomes:

```text
GO_PRIMARY_INTEGRATION
ROLLBACK
EXTEND_OBSERVATION_WITH_OWNER_APPROVAL
BLOCKED_EVIDENCE
```

`EXTEND_OBSERVATION_WITH_OWNER_APPROVAL` is not an automatic escape from a failed
gate; it is only for insufficient volume/evidence when no hard gate failed.

### Step 6.7 — build and deploy the primary release candidate, only after GO

This step is serial and destructive enough to require explicit owner approval.
It prepares/deploys the primary **release candidate** but does not declare the
repository/project rollout finally complete; Step 6.9 owns that closeout after
the real primary 24-hour confirmation.

Before enabling the budget on the primary connector, freeze a **connector
consumer inventory**: list every known ChatGPT Project that uses the primary
Raspberry Pi MCP connector. Because the server policy sees only the
`openai-mcp` client prefix, not Project identity, primary budget enablement
affects all such Projects. If any consumer has not been included in the owner's
rollout scope, do not enable the primary budget; remain on staging and report the
blocker.

Also re-investigate the authenticated connector/Project control mechanism at
6.7. If the agent cannot verify current consumer attachment or cannot restore the
primary mapping after rollback, primary integration is `BLOCKED_EXTERNAL`; do not
proceed based on the week-old Phase-5 mechanism.

Use this fixed final-integration branch/worktree:

```text
branch:   release/chat-mode-scheduling-v2-primary-integration
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-primary-integration
```

If either already exists, inspect/recover it rather than creating an alternate
name. Divergence or unexplained dirty state is a blocker; do not reset it.

Before any primary mutation, fan out the 6.7 **read-only pre-cutover
investigation** into independent workers:

```text
precutover-git-drift          # latest POC/master + scheduling stack ancestry/conflicts
precutover-consumers          # primary connector consumer inventory/scope
precutover-project-state      # current instructions/connector mappings per Project
precutover-units-config       # primary config/server/jobs/tunnel unit snapshots/hashes
precutover-runtime            # currently deployed commit/process/service identity
precutover-rollback           # completeness/readability of all rollback snapshots
precutover-staging-fallback   # staging endpoint remains healthy/restartable
```

Launch all immediately with read-only resource access. Each writes a private or
non-sensitive hashed fragment under the pre-primary-cutover snapshot root. The
orchestrator performs no primary mutation until **all required pre-cutover
workers pass**. Additional Projects discovered by the consumer-inventory worker
create new Project-state snapshot tasks dynamically and those tasks start
immediately rather than waiting for the first set to finish.

Release-candidate branch/deployment procedure:

1. fetch latest `origin/proof-of-concept` and `origin/master`;
2. verify their relationship/current CI and complete the required 6.7 pre-cutover
   investigation;
3. create/recover the fixed `release/chat-mode-scheduling-v2-primary-integration`
   branch/worktree above from the **latest proof-of-concept**;
4. merge the current approved `release/chat-mode-scheduling-v2-phase6-review`
   HEAD (which contains Phase-5 staging lineage plus Phase-6 evidence through the
   6.6 GO verdict) into the primary-integration branch; do not cherry-pick an
   ad-hoc subset of server/config/tooling commits;
5. reconcile independent changes by inspecting each conflict and rerun affected
   focused tests; never resolve wholesale with `--ours`/`--theirs`;
6. run the repository's optimized full test/coverage matrix, pre-commit, push the
   primary-integration candidate, and wait for its CI green;
7. record this exact candidate commit/hash in Phase-6 progress. Do **not** merge
   `master` yet. Whether the repository release workflow requires merging this
   candidate to `proof-of-concept` before deployment is re-checked in the 6.7
   fresh investigation; if required, merge only to `proof-of-concept`, wait CI,
   and record the resulting proof HEAD. Final `master` synchronization waits for
   6.9;
8. deploy the approved candidate to the primary server using the repository's
   currently documented deployment mechanism, initially with the repository
   default guard disabled; record the exact deployed commit and unit/config hashes;
9. smoke the primary server/connector with the guard disabled;
10. enable the selected client budget in deployment-local config;
11. for every owner-approved primary-connector consumer in rollout scope, use
    the Phase-5 tested instruction-merge helper to inject/update exactly one
    canonical scheduling-v2 block while preserving that Project's existing
    instructions; read back/verify the merged text and record pre/post hashes;
12. re-smoke long-job flow and verify effective config/log telemetry; only then
    begin Step 6.8's 24-hour clock.

Do not combine code deployment, config enablement, and Project-instruction change
into one opaque action. Each has an independent rollback checkpoint. If 6.8
fails, restore the pre-6.7 deployed code/config/instructions/connector mapping;
`master` has not been finalized, so repository rollback remains uncomplicated.

### Step 6.8 — primary cutover immediate smoke and 24-hour confirmation

Treat 6.8 as four explicit substeps:

```text
6.8.1  immediate primary read + short background-job smoke
6.8.2  record primary_cutover_started_at and wait real 24 h
6.8.3  freeze the exact primary-cutover 24 h evidence window
6.8.4  run dynamic review fan-out -> focus leads -> orchestrator PASS/ROLLBACK gate
```

6.8.1 verifies effective config, instruction hash, guard telemetry, durable-job
behavior, connector consumer inventory, and rollback switches. If it fails,
rollback immediately and do not start the 24-hour timer.

6.8.2 sets progress to `waiting_wall_clock`; synthetic time cannot satisfy it.

6.8.3 freezes `[primary_cutover_started_at, +24h)` into:

```text
benchmarks/chat-mode-scheduling-v2/phase6-primary24h-evidence.json
benchmarks/chat-mode-scheduling-v2/phase6-primary24h-evidence.md
```

Record its JSON SHA-256 in progress.

Before 6.8.4 can return `PRIMARY_CONFIRMATION_PASS`, the primary window must contain at
least:

```text
10 eligible primary-connector turns total
5 ordinary development turns not generated solely for cutover validation
3 turns containing a positive job_status wait
2 explicitly tagged cutover-validation long-job turns
```

Run those two tagged cutover-validation turns during the first 24 hours using
known-fit disposable V1/V2 semantics. If the 24-hour window is below a minimum
and no hard rollback condition fired, return `PRIMARY_CONFIRMATION_INSUFFICIENT_ACTIVITY`
and extend the confirmation once to **48 hours total**. Freeze:

```text
[+24h,+48h): benchmarks/chat-mode-scheduling-v2/phase6-primary24h-extension-24-48h-evidence.{json,md}
[0,+48h):    benchmarks/chat-mode-scheduling-v2/phase6-primary48h-evidence.{json,md}
```

Rerun the full dynamic subreview fan-out against the cumulative 48-hour evidence, producing these four canonical focus outputs:

```text
benchmarks/chat-mode-scheduling-v2/phase6-primary48h-reliability.{json,md}
benchmarks/chat-mode-scheduling-v2/phase6-primary48h-blocking-wall.{json,md}
benchmarks/chat-mode-scheduling-v2/phase6-primary48h-efficiency.{json,md}
benchmarks/chat-mode-scheduling-v2/phase6-primary48h-workflow-ux.{json,md}
```

If the cumulative 48-hour window meets the minimum and every gate passes, record
`PRIMARY_CONFIRMATION_PASS` with `primary_confirmation_hours=48`. If still below
minimum at 48 hours, explicit owner decision is required to amend the plan for a
further extension or rollback/stop; it is not an automatic PASS.

6.8.4 launches the same dynamic partition set used for staging windows. Its
canonical 24-hour focus outputs are exactly:

```text
reliability: benchmarks/chat-mode-scheduling-v2/phase6-primary24h-reliability.{json,md}
blocking:    benchmarks/chat-mode-scheduling-v2/phase6-primary24h-blocking-wall.{json,md}
efficiency:  benchmarks/chat-mode-scheduling-v2/phase6-primary24h-efficiency.{json,md}
workflow:    benchmarks/chat-mode-scheduling-v2/phase6-primary24h-workflow-ux.{json,md}
```

All canonical focus artifacts reference the same window hash. At the 24-hour
decision the orchestrator records exactly one of:

```text
PRIMARY_CONFIRMATION_PASS               # also record primary_confirmation_hours=24
PRIMARY_CONFIRMATION_INSUFFICIENT_ACTIVITY
BLOCKED_EVIDENCE
ROLLBACK
```

The insufficient verdict follows the one-time 48-hour extension rule above. Any
condition in **Phase-6 hard rollback conditions** applies. This window checks
regressions introduced specifically by moving from staging to the primary
connector; it does not replace the completed seven-day staging evidence.

### Step 6.9 — cleanup and final project report

After `PRIMARY_CONFIRMATION_PASS`:

1. write the Phase-6 final report/retrospective and perform the two-commit
   evidence-CI/closeout-CI procedure defined above on the Phase-6 review branch;
2. merge that final Phase-6 review closeout HEAD into the existing
   `release/chat-mode-scheduling-v2-primary-integration` branch, ensuring the
   already-deployed candidate code is unchanged except for explicitly documented
   evidence/docs/closeout changes; if runtime code differs, stop and investigate;
3. run the optimized final test/coverage/pre-commit/CI matrix on the updated
   primary-integration branch;
4. merge/synchronize that fully evidenced branch into `proof-of-concept` and then
   `master` only according to the current repository release workflow and explicit
   owner authorization. Record both resulting heads/CI;
5. verify the primary deployed runtime still corresponds to the approved runtime
   source/config/instructions after repository synchronization;
6. retain canonical benchmark/replay/staging evidence and delete throwaway
   benchmark chats;
7. retire temporary A/B/surviving-C/H benchmark endpoints/connectors only after
   confirming no Project still depends on them;
8. stop normal use of the staging endpoint but keep its unit/config/token
   definitions intact and restartable until `primary_cutover_started_at + 7 days`;
   do not delete them during Step 6.9;
9. preserve rollback snapshots until at least that same retention deadline; a
   longer retention period is allowed only when explicitly recorded;
10. mark progress complete and document remaining readability/observability debt
    separately from the scheduling result.
