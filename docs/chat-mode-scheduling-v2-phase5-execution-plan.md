# Chat mode scheduling v2 — Phase 5 staged deployment execution plan

Status: **PLANNED; BLOCKED UNTIL PHASE 4 GO_PHASE5 + OWNER APPROVAL**

This is the authoritative execution document for Phase 5 only. It does not
assume Phase 4 passed. Step 5.0 must independently inspect the final Phase-4
hard-gate matrix, selected budget, CI, evidence integrity, cleanup state, and
owner approval before staging begins.

Phase 5 purpose: deploy the approved policy through an isolated persistent
staging connector first to `Binnacle`, observe 24 hours, and only then extend it
to `Raspberry Pi 5`.

## Dependency summary

| Dependency | Must be true before Phase 5 staging |
| --- | --- |
| Phase 4 | Complete with verdict exactly `GO_PHASE5` |
| Acceptance gates | Every hard and required confirmatory gate passed |
| Selected policy | One cumulative budget frozen with source/instruction hashes |
| Owner decision | Explicit approval to begin staged deployment |
| Staging/rollback | Persistent isolated staging topology and rollback snapshots ready |
| Benchmark cleanup | No Phase-4 benchmark-owned live job/config mutation remains unresolved |

Phase 5 produces a qualified persistent staging deployment, a 24-hour Stage-1
review, a Stage-2 `Raspberry Pi 5` start timestamp `T0`, exact rollback state,
and the handoff required for 24-hour/7-day Phase-6 review.

## Required references

Read before Step 5.0:

- `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md` — short cross-phase index/dependency DAG;
- `docs/chat-mode-scheduling-v2-design.md`;
- `docs/chat-mode-scheduling-v2-ab-plan.md`;
- `benchmarks/chat-mode-scheduling-v2/METRICS.md`;
- the previous phase's canonical progress and final report identified by Step 5.0.

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
benchmarks/chat-mode-scheduling-v2/phase5-dependency-audit-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase5-dependency-audit-YYYY-MM-DD-rNN.md
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

### Step-5.0 cold-start/preflight workspace

Use:

```text
completed Phase-4 checkout:
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4
  expected branch: feature/chat-mode-scheduling-v2-phase4

production observation checkout:
  /home/grammy-jiang/Projects/binnacle
  expected branch: master
```

Read Phase-4 progress/handoff/report from the Phase-4 checkout and query its
remote/CI directly. If the worktree is absent, reattach the exact Phase-4 branch
at the canonical path. Do not start by creating the staging branch and then infer
whether Phase 4 passed; the read-only GO/owner/staging preflight happens first.

## Step 5.0 — Dependency Audit / Entry Gate

Step 5.0 has **two ordered stages**:

1. **Read-only preflight.** From an existing safe worktree, fetch/read upstream
   branches, previous-phase progress/reports/CI, and external prerequisites. Do
   not modify the previous phase merely to record a failed preflight. If the
   evidence is already insufficient/contradictory, report the blocker and stop;
   no Phase-5 workspace is created from an unqualified base.
2. **Phase workspace bootstrap + formal audit.** Once the phase-specific preflight
   conditions below are sufficient to choose the exact canonical source base,
   create/recover the Phase-5 canonical branch/worktree defined in this
   document. Only inside that workspace create/recover:

   ```text
   benchmarks/chat-mode-scheduling-v2/phase5-progress.json
   benchmarks/chat-mode-scheduling-v2/phase5-progress.md
   ```

   If absent, initialize every phase step to `not_started`, set Step 5.0 to
   `running`, phase status to `in_progress`, and `next_step` to `5.0`. If they
   already exist, reconcile them with Git history before changing anything; never
   overwrite a prior blocked/running checkpoint merely because the chat is new.

The formal dependency-audit artifact and its revision/hash are recorded under
the progress JSON `dependency_audit` object. On PASS, mark 5.0 `complete` and
set `next_step=5.1`. On a blocker discovered **after** workspace bootstrap,
leave `last_completed_step` unchanged, set phase status `blocked`, keep
`next_step=5.0`, and commit/push the blocker evidence when Git remains
available.

**No staging connector switch, persistent staging service, Project-instruction
change, or 24-hour timer may start before this audit passes.**

Phase 5 depends entirely on a successful Phase-4 confirmatory verdict and an
explicit owner decision to proceed.

### Required Phase-4 state

The canonical Phase-4 files are:

```text
benchmarks/chat-mode-scheduling-v2/phase4-progress.json
benchmarks/chat-mode-scheduling-v2/phase4-progress.md
```

Read the exact final report paths from `phase4-progress.json.handoff`. Do not
select a Phase-4 report by glob/date.

Verify all of the following directly from Phase-4 canonical evidence:

1. `phase4-progress.json` is `complete` and all canonical submitted slots are
   frozen exactly once.
2. The final Phase-4 verdict is exactly `GO_PHASE5`; any `NO_GO_*` blocks Phase 5.
3. The selected cumulative budget is one of the Phase-3 candidates and is
   explicitly recorded in the final Phase-4 report.
4. Every hard gate passed: correctness, safety, tool contract, production
   isolation, and zero premature handoff where dependency work fits budget.
5. Same-prompt/reliability, performance, scheduling, guard, and efficiency gates
   all pass using the frozen sample; the orchestrator must not summarize a failed
   gate as "close enough".
6. Pre/post micro scheduler sanity passed or any change is explicitly resolved.
7. Timeout-provenance review reconciles with submitted-slot inclusion.
8. Phase-4 final CI/pre-commit/tests are green. Verify handoff
   `validated_evidence_commit == validated_ci_head_sha`, recorded CI conclusion
   `success`, and a fresh query showing the current Phase-4 closeout HEAD CI is
   green. Both commits must be on the expected Phase-4 lineage.
9. Temporary A/B/surviving-C/H endpoint evidence is closed and no benchmark-owned live job
   is left running.

### Required rollout authorization and staging prerequisites

Project-to-connector attachment is an external control-plane dependency, separate
from changing Project instructions. The existing `chatgpt-project` helper is
known to manage instructions; do not assume it can change connector attachment.
Before PASS, investigate the currently available authenticated mechanism for both
`Binnacle` and `Raspberry Pi 5`. If attachment/detachment requires owner UI action,
record the exact action and keep Step 5.0 `BLOCKED_EXTERNAL` until the action is
completed and read back/verified. Do not stage by modifying the primary connector
in place as a workaround.

Verify:

- the owner explicitly approved progression after seeing `GO_PHASE5`;
- exact current instructions for `Binnacle` and `Raspberry Pi 5` are snapshotted
  for rollback;
- the persistent staging port/config/token/job/socket paths are free/ready;
- the staging connector can be provisioned without modifying the primary
  connector;
- rollback commands/snapshots are available before any mutation;
- production observation baseline is frozen again at Phase-5 start.

### Phase-5 workspace bootstrap inside Step 5.0

After read-only preflight confirms `GO_PHASE5`, explicit owner approval, selected
policy identities and staging feasibility, identify the exact current Phase-4
**closeout HEAD** whose CI is green. Verify there is no unreviewed runtime-server
drift between recorded `phase4_source_head` and that closeout HEAD (inspect
`src/binnacle`, runtime dependency/config/unit files; benchmark scripts/docs are
allowed). Any runtime drift not covered by Phase-4 gates blocks staging. Then
create/recover the exact Phase-5 staging branch/worktree defined below **from the
Phase-4 closeout HEAD**.
Create progress files there and perform/commit the formal audit. Creating the
branch is not deployment; do not start staging services or mutate Projects during
5.0.

### Audit result

Required rows include:

```text
phase4_progress
phase4_final_report
verdict_GO_PHASE5
selected_budget
all_acceptance_gates
phase4_ci
benchmark_cleanup
owner_approval
project_instruction_snapshots
staging_topology_ready
project_connector_attachment_ready
rollback_ready
production_isolation
```

### Exit criteria

```text
dependency audit PASS committed
selected budget/source/instruction hashes frozen
owner approval recorded
rollback snapshots ready
next allowed step: 5.1
```

## Phase-5 canonical staging workspace

```text
branch:   release/chat-mode-scheduling-v2-staging
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-staging
```

Step 5.0 creates/reuses exactly this branch/worktree from the Phase-4-approved
source commit after read-only preflight. If it exists, reconcile status/progress/origin before use; never
replace unexplained staging work with a newly named branch. The persistent
staging services in this phase execute code from this worktree.

## Phase-5 step dependency DAG

| Work | Direct predecessor(s) | Required predecessor evidence before start |
| --- | --- | --- |
| **5.0** dependency audit | Phase 4 + owner approval | `GO_PHASE5`, all gates PASS, selected identities, rollback/staging prereqs |
| **5.1** release freeze/rehearsal | 5.0 | committed PASS audit + exact rollback snapshots |
| **5.2** deploy `Binnacle` | 5.1 | rollback rehearsal PASS + staging stack healthy before Project switch |
| **5.3** immediate smoke window | 5.2 | Stage-1 deployment timestamp/config/instructions/connector mapping recorded |
| **5.4** start/hold 24h gate | 5.3 | immediate smoke PASS; no hard rollback condition |
| **5A** 24h review frontier | 5.4 + real wall clock elapsed | exact 24h data window frozen; all independent review partitions become ready together |
| **5.5** Stage-1 decision | all four canonical focus artifacts + required integrity/activity audits | same evidence window/hash; all focus fan-ins complete |
| **5.6** switch `Raspberry Pi 5` | 5.5 PASS | Stage-1 PASS + fresh target-Project dependency refresh |
| **5.7** Phase-6 handoff | 5.6 | Stage-2 switch + immediate smoke PASS + exact T0/rollback state recorded |

Before Step 5.6, because at least 24 hours have elapsed since Step 5.0, perform a
**target-Project refresh investigation**: re-read the current `Raspberry Pi 5`
instructions and connector mapping and compare them to the 5.0 snapshot. If they
changed, do not overwrite the newer state automatically. Investigate who/what
changed it, refresh the rollback snapshot, and determine whether the planned
Stage-2 switch is still valid. If the change alters rollout assumptions, mark
Phase 5 blocked and rerun 5.0.

### Phase-5 review worker branch/worktree topology

After the orchestrator freezes `phase5-stage1-24h-evidence.json`, review work is
fan-out is **not limited by the number of canonical focus outputs**. Four canonical focus-lead branches remain because
the final decision needs four stable review artifacts:

```text
feature/chat-mode-scheduling-v2-phase5-review-reliability
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase5-review-reliability
feature/chat-mode-scheduling-v2-phase5-review-blocking
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase5-review-blocking
feature/chat-mode-scheduling-v2-phase5-review-efficiency
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase5-review-efficiency
feature/chat-mode-scheduling-v2-phase5-review-workflow
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase5-review-workflow
```

Before each focus lead aggregates, the orchestrator fans out every independent
read-only subreview partition. Recommended partition set:

```text
reliability/*:
  service-errors
  tunnel-connector
  interruptions
  outage-chronology

blocking/*:
  union-wall
  exhaustion
  wait-distribution
  overlap-accounting

efficiency/*:
  tool-result-tokens
  job-status-calls
  concurrency
  duplicate-reads

workflow/*:
  same-turn-proxy
  continuation-incidents
  tagged-validation-correctness
  activity-sufficiency
```

Each subreview is an independent worker using the same frozen evidence SHA and
writes only a scratch fragment:

```text
/tmp/binnacle-chat-scheduling-v2/phase5/review/<window>/<focus>/<partition>.json
```

There is no fixed number of subreview sessions. Launch every partition at once
when the evidence freezes. As soon as all required partitions for one focus finish,
launch that focus lead immediately even if other focuses still have workers
running. A focus lead verifies fragment hashes and deterministically writes its
canonical artifact. Step 5.5 waits only for the four canonical focus artifacts and
required evidence-integrity checks, not for arbitrary worker batching.

The 24-hour canonical focus outputs are:

```text
reliability: benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-reliability.{json,md}
blocking:    benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-blocking-wall.{json,md}
efficiency:  benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-efficiency.{json,md}
workflow:    benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-workflow-ux.{json,md}
```

All canonical focus artifacts reference the same `stage1_started_at`, window end
timestamp, staging config hash, selected budget and evidence SHA. Mismatch is an
investigation blocker.

For 48-hour and 72-hour extension windows, create fresh focus-lead branches using
the existing `review48-*` / `review72-*` naming convention and launch the same
subreview partition set against the new cumulative evidence. A later window never
reuses an earlier worker branch or scratch fragment.

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

## Canonical Phase-5 handoff contract

Step 5.7 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase5-staged-deployment-YYYY-MM-DD-rNN.json
benchmarks/chat-mode-scheduling-v2/phase5-staged-deployment-YYYY-MM-DD-rNN.md
```

`phase5-progress.json` `handoff` contains:

```text
final_report_json
final_report_md
final_report_json_sha256
final_report_md_sha256
selected_budget_s
approved_runtime_source_head
v2_instruction_sha256
staging_connector_identity
staging_config_sha256
stage1_started_at
stage1_observation_verdict
stage1_observation_hours
stage1_observation_end_at
stage1_observation_evidence_sha256
stage2_started_at   # Phase-6 T0
stage2_smoke_pass
stage2_smoke_sha256
rollback_snapshot_paths
phase6_ready = true | false
validated_evidence_commit
validated_ci_run_id
validated_ci_head_sha
validated_ci_conclusion
```

The first final report is `r01`. If a completed phase is later formally reopened,
write a new revision instead of overwriting the old one; update the progress
`handoff` to point at the new canonical revision and preserve the prior verdict
as historical evidence.

Phase 6.0 recomputes these identities against Phase 4 and current staging state.

## Phase-5/6 operational evidence tooling contract

Phase 5 implements one deterministic privacy-minimizing operational evidence tool
that Phase 6 reuses unchanged:

```text
scripts/chat_scheduling_operational.py
tests/scripts/test_chat_scheduling_operational.py
```

It has two subcommands.

Freeze an exact timestamp window:

```bash
uv run python scripts/chat_scheduling_operational.py freeze \
  --start <offset-aware-ISO8601> \
  --end <offset-aware-ISO8601> \
  --server-unit <mcp-server-unit> \
  --jobs-unit <job-manager-unit> \
  --tunnel-unit <tunnel-unit> \
  --output-json <evidence.json> \
  --output-md <evidence.md>
```

For Phase-5/Stage-2 staging evidence the unit arguments are exactly:

```text
--server-unit binnacle-scheduling-staging.service
--jobs-unit binnacle-scheduling-staging-jobs.service
--tunnel-unit binnacle-scheduling-staging-tunnel.service
```

For primary-cutover evidence in Phase 6 they are exactly:

```text
--server-unit binnacle-mcp.service
--jobs-unit binnacle-jobs.service
--tunnel-unit binnacle-tunnel.service
```

The frozen JSON contains normalized scheduling-v2 telemetry required by Phase
5/6 metrics, source window timestamps, and **separate journal cursor/range/unit
metadata for all three units**, with no arbitrary conversation prose. A missing
required unit/journal source is an evidence error; the tool does not silently
substitute a different unit.

Produce one review focus from a frozen JSON:

```bash
uv run python scripts/chat_scheduling_operational.py review \
  --evidence <evidence.json> \
  --focus reliability|blocking-wall|efficiency|workflow-ux \
  --reference <phase4-live-confirmatory.json> \
  --output-json <review.json> \
  --output-md <review.md>
```

`workflow-ux` reports only server-derived proxies plus explicitly tagged/recorded
continuation evidence; it never fabricates user prompt text from MCP logs.

Step 5.1 must implement/test this tool **before** Stage-1 deployment:

```bash
uv run pytest -q tests/scripts/test_chat_scheduling_operational.py
```

Tests cover half-open window boundaries, server/jobs/tunnel multi-unit capture, duplicate journal lines, turn/job
correlation, exhaustion, interruption/error normalization, tokenizer fields,
missing optional telemetry, and deterministic output ordering/hash stability.
Phase 6 must not fork a second parser for the same journal evidence.

## 25. Phase-5 objective

Expose the Phase-4-selected scheduling policy to real development work in a
reversible, isolated sequence before changing the primary normal Raspberry Pi
Project.

The staged design must respect one architectural fact:

> the server guard knows client identity, not ChatGPT Project identity.

Therefore the first Project-only stage uses the dedicated guarded
endpoint/connector created for Phase 4. It does **not** enable an `openai-mcp`
budget on the primary shared connector.

## 26. Phase-5 rollback switches

### Exact staged rollback SOP

A rollback never kills a durable job merely to change Project routing. Before
changing a Project connector, query the staging job list. If a rollout-owned job
is still running and can safely finish, keep the staging services up and restore
Project routing/instructions first; the old endpoint remains reachable for
operator cleanup/status. If a runaway job itself caused the rollback, use normal
`stop_job` semantics and record that explicit action.

For Stage 1 (`Binnacle`) rollback, execute in this order:

1. freeze failure evidence and timestamp;
2. restore the exact pre-Stage-1 `Binnacle` Project instructions snapshot;
3. restore its exact prior connector mapping;
4. open one tiny read-only verification chat through the restored mapping;
5. verify primary connector/server/config hashes still match the Phase-5 baseline;
6. leave staging server/manager/tunnel running for diagnosis until all
   staging-owned jobs are terminal and failure evidence is frozen;
7. then disable/stop staging tunnel, server, and manager **in that order** unless
   the owner keeps them for investigation; do not delete config/token/job spool;
8. mark Phase 5 `rolled_back` and record restored Project instruction/connector
   hashes plus service states.

For Stage 2 (`Raspberry Pi 5`) rollback, do the same for Stage 2 first. `Binnacle`
may remain on staging only when its Stage-1 verdict was PASS and the failure is
proven specific to the Stage-2 Project. If the failure concerns shared staging
server/guard/tunnel behavior, rollback **both** Projects using their own snapshots.

A rollback is not complete until the affected Project(s) pass the restored
read-only verification and the primary production baseline remains unchanged.

Always preserve two independent rollback controls:

```text
model policy rollback:
  restore previous Project instructions

server guard rollback:
  switch Project back to unguarded connector / remove budget from staging config
```

Neither rollback kills durable jobs. Before any connector switch, wait for a
quiet point with no benchmark/staging-owned active background job requiring that
endpoint.

## 27. Phase-5 staged topology

Phase 5 does **not** reuse the ephemeral `/tmp` Phase-4 endpoint. It separates
**coordination/evidence history** from the **runtime code checkout**.

Coordination/evidence workspace (moves as progress/reports are committed):

```text
branch:   release/chat-mode-scheduling-v2-staging
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-staging
```

Pinned runtime worktree (detached at the approved runtime source commit):

```text
/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime
```

Step 5.1 creates the runtime worktree with `git worktree add --detach` at the
`approved_runtime_source_head` verified from Phase 4. The runtime worktree must
remain detached and unmodified through Phase 5/6 staging observation. Its HEAD and
`git status --porcelain` are checked before every staging-service start/restart.
If either changes, stop and investigate; do not silently reset it while a staged
rollout is active.

Persistent manager/server units execute **only** from this pinned runtime
worktree, so later progress/evidence commits cannot change the code loaded after a
service restart.

Before writing units, Step 5.1 runs in the pinned runtime worktree:

```bash
uv sync --frozen
test -x .venv/bin/binnacle
test -x .venv/bin/binnacle-jobs
```

Record `uv.lock` SHA-256 and the two executable paths in progress. A dependency
sync failure blocks deployment; do not fall back to globally installed Binnacle.

### Exact staging systemd contract

Write these three user-unit files under `~/.config/systemd/user/`. They are
Phase-5-owned resources and must not reuse the primary unit names.

`binnacle-scheduling-staging-jobs.service`:

```ini
[Unit]
Description=Binnacle scheduling-v2 staging job manager

[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime
Environment=BINNACLE_CONFIG_FILE=/home/grammy-jiang/.config/binnacle-scheduling-staging/config.toml
ExecStart=/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime/.venv/bin/binnacle-jobs
TimeoutStartSec=30
Restart=always
RestartSec=1
KillMode=control-group
RuntimeDirectory=binnacle-scheduling-staging
RuntimeDirectoryMode=0700
UMask=0077

[Install]
WantedBy=default.target
```

`binnacle-scheduling-staging.service`:

```ini
[Unit]
Description=Binnacle scheduling-v2 staging MCP server
After=network.target binnacle-scheduling-staging-jobs.service
Wants=binnacle-scheduling-staging-jobs.service

[Service]
Type=simple
WorkingDirectory=/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime
Environment=BINNACLE_CONFIG_FILE=/home/grammy-jiang/.config/binnacle-scheduling-staging/config.toml
Environment=BINNACLE_MANAGED_DEPLOYMENT=1
ExecStart=/home/grammy-jiang/Projects/binnacle-chat-scheduling-staging-runtime/.venv/bin/binnacle serve --host 127.0.0.1 --port 8120
ExecStartPost=/bin/bash -c 'for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/8120) 2>/dev/null && exit 0; sleep 0.1; done; exit 1'
Restart=always
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
```

The staging config is exact except for the selected numeric budget and the
resolved runtime-directory prefix:

```toml
[auth]
token_file = "/home/grammy-jiang/.config/binnacle-scheduling-staging/token"

[serve]
host = "127.0.0.1"
port = 8120

[jobs]
owner = "manager"
dir = "/home/grammy-jiang/.local/state/binnacle-scheduling-staging/jobs"
socket_path = "/run/user/<uid>/binnacle-scheduling-staging/jobs.sock"

[jobs.blocking_wall_budget_s_by_client]
"openai-mcp" = <selected Phase-4 budget: 120, 300, or 600>
```

Resolve `/run/user/<uid>` from the actual `$XDG_RUNTIME_DIR` and write the
absolute path. Do not leave a literal shell variable in TOML. Do not copy the
primary bearer token: generate a distinct random staging token, write only the
raw token expected by the existing auth loader, set mode `0600`, and configure
the staging tunnel profile to use that token. Never print it in logs/evidence.

Step 5.1 loads this TOML through the pinned runtime's `get_settings()` in a
subprocess with `BINNACLE_CONFIG_FILE` set and asserts the parsed auth/serve/jobs
paths, owner, and selected budget **before** starting either unit. Then it starts
the manager/server and verifies the effective `tool_config`/MCP behavior before
Project routing changes.

### Exact staging tunnel contract

Use this profile/resource identity:

```text
profile: binnacle-scheduling-staging
profile config: ~/.config/tunnel-client/binnacle-scheduling-staging.yaml
env file:       ~/.config/tunnel-client/binnacle-scheduling-staging-tunnel.env
health URL:     ~/.local/state/tunnel-client/health/binnacle-scheduling-staging.url
user unit:      binnacle-scheduling-staging-tunnel.service
connector name: Raspberry Pi MCP Scheduling Staging
```

Step 5.0 confirms the authenticated control-plane mechanism can provision/verify
this profile without altering profile `binnacle`. The staging tunnel unit uses the
current primary tunnel executable path discovered during 5.0 (planning-time path
was `/home/grammy-jiang/.local/bin/tunnel-client`) and exactly:

```text
Wants/After=binnacle-scheduling-staging.service
WorkingDirectory=/home/grammy-jiang
EnvironmentFile=<staging env file above>
ExecStart=<audited tunnel-client> run --profile-dir /home/grammy-jiang/.config/tunnel-client --profile binnacle-scheduling-staging
Restart=always
RestartSec=5
UMask=0077
```

Copy the existing bounded readiness semantics from the current
`binnacle-tunnel.service`, substituting the staging health URL and staging server
unit only. Do not hand-design a different readiness policy. Step 5.1 stores the
rendered unit SHA-256 values before enabling them.

Step 5.1 enables/verifies the staging stack in this exact order:

```bash
systemctl --user daemon-reload
systemctl --user enable --now binnacle-scheduling-staging-jobs.service
systemctl --user is-active binnacle-scheduling-staging-jobs.service

systemctl --user enable --now binnacle-scheduling-staging.service
systemctl --user is-active binnacle-scheduling-staging.service
# verify TCP 8120 is listening, then run the authenticated LocalMCP smoke below

systemctl --user enable --now binnacle-scheduling-staging-tunnel.service
systemctl --user is-active binnacle-scheduling-staging-tunnel.service
```

The local MCP readiness check uses the existing benchmark `LocalMCP` helper, not a
made-up HTTP health endpoint. From the pinned runtime worktree:

```bash
.venv/bin/python - <<'PYSMOKE'
from pathlib import Path
from scripts.chat_scheduling_runtime import LocalMCP
client = LocalMCP(
    url="http://127.0.0.1:8120/mcp",
    token_path=Path.home() / ".config/binnacle-scheduling-staging/token",
)
out = client.call("job_status", {})
assert "jobs" in out
PYSMOKE
```

This is an authenticated read-only MCP smoke. Do not add a new server route solely
for staging readiness.

After all three units are active, verify: effective config identifies the staging
jobs dir/socket and selected budget; the read-only MCP smoke above passes; a
disposable short `run_command` is owned by the staging manager/spool and reaches a
terminal state; the staging tunnel main channel reports its MCP probe healthy; and
the primary units/profile hashes are unchanged. Only then perform rollback
rehearsal / Step 5.2 Project switch.

It promotes the approved source/config into one persistent, isolated staging stack:

```text
server port: 8120
config: ~/.config/binnacle-scheduling-staging/config.toml
token:  ~/.config/binnacle-scheduling-staging/token
jobs:   ~/.local/state/binnacle-scheduling-staging/jobs
socket: $XDG_RUNTIME_DIR/binnacle-scheduling-staging/jobs.sock

transient/persistent user units:
  binnacle-scheduling-staging-jobs.service
  binnacle-scheduling-staging.service

tunnel/connector:
  Raspberry Pi MCP Scheduling Staging
```

Use the same selected budget and source commit approved by Phase 4. The staging
manager/server run with their own `BINNACLE_CONFIG_FILE`; they do not share the
primary job spool/socket/token. A dedicated tunnel profile points only at port
8120. Provision these as the exact persistent dedicated user units defined above; do
not use `systemd-run` for the multi-day rollout. Do not overwrite
`binnacle-mcp.service`, `binnacle-jobs.service`, `binnacle-tunnel.service`, or
the primary tunnel profile.

### Project-instruction merge contract

The canonical scheduling text is:

```text
.claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt
```

It is a **scheduling block**, not a complete replacement for an existing Project's
instructions. For every staged/primary Project mutation, preserve its exact
current Project-specific instructions and inject/update exactly one marked block:

```text
=== BEGIN BINNACLE CHAT SCHEDULING V2 ===
<exact canonical scheduling file contents>
=== END BINNACLE CHAT SCHEDULING V2 ===
```

Transformation rules are fixed:

1. snapshot the exact pre-mutation instruction text outside Git and hash it;
2. if neither marker exists, append two newlines plus the complete marked block;
3. if exactly one well-formed begin/end pair exists, replace **only** the text
   inside that pair with the current canonical scheduling text; preserve all text
   before/after the block;
4. if markers are malformed, nested, duplicated, or only one marker exists,
   **BLOCK** and investigate rather than rewriting the Project;
5. after setting instructions, read them back and verify: original non-scheduling
   prefix/suffix unchanged, exactly one block present, block SHA equals canonical
   v2 SHA;
6. rollback always restores the exact pre-mutation snapshot; do not attempt to
   reconstruct it by merely deleting markers.

Implement this transformation in Step 5.1 at these exact paths:

```text
scripts/chat_scheduling_project_instructions.py
tests/scripts/test_chat_scheduling_project_instructions.py
```

CLI contract:

```bash
uv run python scripts/chat_scheduling_project_instructions.py merge \
  --original <private-original-snapshot.txt> \
  --block .claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt \
  --output <private-merged-instructions.txt>

uv run python scripts/chat_scheduling_project_instructions.py verify \
  --original <private-original-snapshot.txt> \
  --block .claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt \
  --actual <private-readback.txt>
```

`merge` refuses malformed/duplicate markers; `verify` proves non-block text is
unchanged and exactly one canonical block exists. All private snapshot/merged/
readback files are `0600` under the Phase-5/6 local-state rollback roots and are
never committed.

Focused tests:

```bash
uv run pytest -q tests/scripts/test_chat_scheduling_project_instructions.py
```

Tests cover empty instructions, existing instructions, existing block update,
malformed markers, duplicate block, Unicode/newlines, and exact rollback snapshot
hashing. Reuse the same helper in Phase 6; do not hand-edit Project instructions.

For an actual Project mutation, after `merge` use the existing authenticated
helper exactly as:

```bash
/usr/bin/python3 .claude/skills/chatgpt-mcp-dev/scripts/chatgpt-project \
  --browser chrome set-instructions --file <private-merged-instructions.txt> \
  '<Project Name>'
```

Then read the current instructions back into a private file with
`chatgpt-project get-instructions '<Project Name>'` and run `verify`. If auth or
readback fails, mutation is not considered complete.

At planning-review time, Project-control authentication was observed to be capable
of expiring (`chatgpt-project get-instructions` returned HTTP 403). Step 5.0 must
re-establish/read back current Project instructions before PASS. A stale
plan-time instruction length is never sufficient for mutation.

Deployment targets are fixed to the existing Projects discovered at planning
time:

```text
Stage 1 Project:
  Binnacle
  g-p-6aae74d658e08191b68720421be6136c

Stage 2 Project:
  Raspberry Pi 5
  g-p-6a9e5ed209e4819195e402d0b4c9dcb1

Primary connector logical name:
  Raspberry Pi MCP

Staging connector logical name:
  Raspberry Pi MCP Scheduling Staging
```

The plan-time instruction lengths (0 chars for `Binnacle`, 784 chars for
`Raspberry Pi 5`) are observations only; Phase 5 must snapshot the exact current
text immediately before mutation and restore that exact snapshot on rollback.
The separate Projects `Binnacle Phase 2 blocking-wall guard` and `Binnacle
test-suite performance optimisation` are not rollout targets.

Stage 1:

```text
Binnacle
-> dedicated guarded staging connector
-> selected Phase-4 budget
-> existing Project instructions + canonical scheduling-v2 block
```

`Raspberry Pi 5` remains unchanged.

After Stage-1 24-hour gate passes:

```text
Raspberry Pi 5
-> guarded staging connector
-> same selected budget
-> existing Project instructions + canonical scheduling-v2 block
```

The primary production connector/server can remain untouched through the full
staged observation. Final integration to the primary line occurs only after
Phase-6 gates.

## 28. Phase-5 steps

### Step 5.1 — staging release freeze and rollback rehearsal

Target: 15–20 minutes.

Using the Phase-5 staging workspace already bootstrapped by 5.0, first implement
and pass both the operational-evidence tooling and Project-instruction merge
helper contracts above, then freeze:

```text
selected budget
Project instruction hashes
connector ids
approved_runtime_source_head
pinned runtime worktree HEAD/status hash
staging endpoint config hash
primary production observation baseline
rollback commands/snapshots
```

Rehearse instruction restore and staging-connector budget disable on the
Phase-4 Project corresponding to `selected_c_endpoint`:

```text
C120 -> rp-sched-C120
C300 -> rp-sched-C300
C600 -> rp-sched-C600
```

Step 5.0 must verify that the selected Project still exists and is no longer
carrying a canonical trial. If it was removed during Phase-4 cleanup, create a
new throwaway Project named `rp-sched-staging-rehearsal`, use it only for the
rollback rehearsal, and record/delete it afterward. Do not rehearse on `Binnacle`
or `Raspberry Pi 5`.

### Step 5.2 — deploy to Binnacle development Project only

Serial deployment action.

- point only the Binnacle development Project at guarded staging connector;
- inject/update the canonical scheduling-v2 block using the merge contract above;
- verify selected budget in staging effective config;
- run one read smoke and one short background-job dependency smoke;
- verify primary normal Project still routes to its old connector.

Record `stage1_started_at`.

### Step 5.3 — immediate 60-minute smoke window

Immediately after the Stage-1 Project switch, the orchestrator launches all
independent smoke tasks concurrently while the 60-minute observation clock runs:

```text
smoke-reachability            # Project -> connector -> staging endpoint
smoke-effective-config        # selected budget/jobs dir/socket/source identity
smoke-durable-job             # short background job + status lifecycle
smoke-primary-isolation       # primary units/config/connector unchanged
smoke-telemetry               # policy/turn/client/window fields present
smoke-rollback-readiness      # snapshots/restore mechanism still valid
```

Each uses disjoint read-only evidence or disposable jobs; only the orchestrator
performs any corrective shared mutation. Failure in one smoke task triggers the
rollback decision path but does not require cancelling unrelated evidence capture.

Observe for a full **60 minutes** after `stage1_started_at`; record a 30-minute
intermediate checkpoint but do not call Step 5.3 complete until 60 minutes have
elapsed. Monitor:

```text
connector reachability
server errors
budget policy fields
unexpected exhaustion
background-job durability
stream/request interruptions
user-visible workflow anomalies
```

Any correctness/safety issue triggers immediate rollback, not a 24-hour wait.
At 60 minutes, freeze the smoke evidence at:

```text
benchmarks/chat-mode-scheduling-v2/phase5-stage1-smoke-60m.json
benchmarks/chat-mode-scheduling-v2/phase5-stage1-smoke-60m.md
```

Step 5.4 starts only after this artifact records PASS.

### Step 5.4 — Stage-1 24-hour observation gate

This is an intentional wall-clock gate. Do not compress it into synthetic time.
Progress status becomes `waiting_wall_clock` with:

```text
resume_not_before = stage1_started_at + 24 h
```

If scheduling/reminder automation is available at execution time, create a 24 h
review reminder. The repository progress timestamp remains authoritative.

During the first 24 hours, run exactly five **rollout-validation** turns through
`Binnacle`, each on disposable fixture roots and tagged in the rollout notes:

```text
V1  R5-like short true barrier
V2  R3-like background job + useful reads
V3  R7-like repeated dependency barriers
V4  R10-like quiet background job
V5  R11-like multi-round read/dependency planning
```

Use the Phase-4 scenario prompts/manifests where directly reusable; otherwise use
the same semantics with shorter operational-safe fixture runtimes only when the
result still maps unambiguously to that Phase-4 class. Record the exact mapping.
These five turns verify known-fit behavior but do **not** count as ordinary
development activity for the real-usage minimum below.

The five validation turns are independent. Schedule them as ready tasks throughout
the first 24-hour window and allow multiple to run concurrently when staging
health/load remains inside the operational admission envelope. Do not serialize
them merely because there are five; unique fixture roots/turn ids keep them
isolated. Their timing is not used for the Phase-4 performance comparison.

### Stage-1 24-hour review frontier — dynamic read-only fan-out

After the wall-clock gate, the orchestrator first freezes the exact window
`[stage1_started_at, stage1_started_at + 24h)` into:

```text
benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-evidence.json
benchmarks/chat-mode-scheduling-v2/phase5-stage1-24h-evidence.md
```

Record its JSON SHA-256 in progress. Every subreview worker and focus lead reads
this frozen artifact (and referenced immutable raw snapshots); nobody runs separate
open-ended `--since 24h` queries. Immediately enqueue the full partition set
defined in **Phase-5 review worker branch/worktree topology** above.

### Step 5.5 — Stage-1 decision

Orchestrator performs the canonical fan-in after all required focus artifacts and integrity/activity checks complete, then compares live staging data with Phase-4 C and baseline expectations.

Before applying rate/efficiency gates, Stage-1 evidence volume must include at
least:

```text
10 staged Project turns total
5 ordinary Binnacle development turns not generated solely for rollout validation
5 turns containing at least one positive job_status wait
5 explicitly tagged rollout-validation long-job turns mapped to Phase-4 scenario classes
```

If the 24-hour window is below any minimum and no hard rollback condition fired,
5.5 returns `INSUFFICIENT_ACTIVITY`, keeps Stage 1 on the qualified staging
connector, and extends observation in fixed 24-hour increments up to **72 hours
total**. It does not switch `Raspberry Pi 5`.

The extension artifacts are fixed:

```text
24 -> 48 h:
  incremental [T+24h,T+48h):
    phase5-stage1-extension-24-48h-evidence.{json,md}
  cumulative [T,T+48h):
    phase5-stage1-through-48h-evidence.{json,md}
  canonical focus reviews:
    phase5-stage1-48h-{reliability,blocking-wall,efficiency,workflow-ux}.{json,md}

48 -> 72 h:
  incremental [T+48h,T+72h):
    phase5-stage1-extension-48-72h-evidence.{json,md}
  cumulative [T,T+72h):
    phase5-stage1-through-72h-evidence.{json,md}
  canonical focus reviews:
    phase5-stage1-72h-{reliability,blocking-wall,efficiency,workflow-ux}.{json,md}
```

All paths are under `benchmarks/chat-mode-scheduling-v2/`. The orchestrator uses
`chat_scheduling_operational.py freeze` for both incremental and cumulative
windows. Each extension launches the full dynamic subreview partition set against the cumulative evidence SHA, then fresh focus-lead branches/worktrees with suffix `phase5-review48-*` or `phase5-review72-*`; never overwrite the original 24-hour review artifacts.

At each decision point apply the same hard gates to the cumulative window and
inspect the incremental window separately for new degradation. If still below the
minimum at 72 hours, explicit owner decision is required to extend further or
stop; it is never an automatic PASS. A further extension, if owner-approved, must
first amend this plan with the new exact end time/artifact names.

PASS requires:

- zero attributable correctness/safety incidents;
- zero attributable connector outage lasting >60 seconds;
- every tracked turn's blocking union <= selected budget + 1.0 second;
- **zero** unexpected exhaustion on the five tagged validation turns whose known
  dependency requirement fits the selected budget. For general staged turns,
  report non-R12-like exhaustion rate and require <=10% once >=20 positive-wait
  turns exist. Below 20, every untagged exhaustion must be individually
  classified from job/turn evidence as known-over-budget or unresolved; any
  unresolved item yields `BLOCKED_EVIDENCE`, not PASS;
- interruption rate is not more than Phase-4 C +2 percentage points when at
  least 20 eligible staged turns exist. Below 20, **zero staging-attributable
  interruption on tagged validation turns** is required and two or more
  staging-attributable interruptions overall is a fail; one untagged attributable
  interruption is recorded as an alert but does not alone establish a rate gate;
- for the five explicitly tagged rollout-validation long-job turns mapped to
  Phase-4 scenario classes, median tool-result tokens <= the corresponding
  Phase-4 C scenario median *1.10. Above 1.10 is a fail; untagged general
  development turns are reported separately and are never reclassified merely to
  make the gate pass;
- for the same five tagged long-job turns, `job_status` calls per turn do not
  exceed the corresponding Phase-4 C scenario median by >20%;
- **zero premature handoff** on tagged validation work known to fit the budget.
  One owner-reported untagged continuation anomaly triggers investigation; two or
  more staging-attributable untagged premature handoffs in the cumulative window
  are a fail.

Step 5.5 verdict is exactly one of:

```text
PASS_STAGE1
INSUFFICIENT_ACTIVITY
ROLLBACK
BLOCKED_EVIDENCE
```

`ROLLBACK` restores the Binnacle development Project and stops Phase 5.
`INSUFFICIENT_ACTIVITY` follows the bounded extension rule above. Step 5.6 requires
`PASS_STAGE1`; no other verdict may advance.

### Step 5.6 — extend to normal Raspberry Pi development Project

Only after Stage-1 PASS.

Switch the normal Project to the same already-qualified guarded staging connector
and the scheduling-v2 block merged into its existing instructions. Preserve an exact snapshot of its prior instructions and
connector route. Record `stage2_started_at` immediately after the switch, run the
immediate smoke checks, and freeze them at:

```text
benchmarks/chat-mode-scheduling-v2/phase5-stage2-smoke.json
benchmarks/chat-mode-scheduling-v2/phase5-stage2-smoke.md
```

5.7 requires this artifact to be PASS.

Do not merge into primary `master` merely because this switch succeeds.

### Step 5.7 — Phase-5 handoff to Phase 6

Freeze both staged deployment timestamps, rollback snapshots, connector/project
mapping, selected budget, and Phase-4 reference metrics.

Phase 5 is COMPLETE when Stage 2 is live and healthy through immediate smoke.
Phase 6 owns the 24-hour and 7-day review after Stage 2.

---
