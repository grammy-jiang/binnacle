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

### Coordinator and parallel workers

The hard concurrency ceiling for this plan is **four ChatGPT sessions total**,
not four workers plus a coordinator. One of those four sessions is always the
**coordinator (Slot A)**. In a four-lane wave the coordinator may also execute
one explicitly assigned low-conflict lane in a separate worker worktree; the
other three sessions occupy Slots B/C/D. If the coordinator must remain purely
coordinating for a particular wave, only three worker lanes run concurrently and
the fourth lane waits. Never create a fifth session to preserve a four-worker
wave.

Only the coordinator may edit:

- this phase's canonical progress JSON/Markdown;
- dependency-audit artifacts;
- integration-branch history;
- final phase verdict/report;
- shared ChatGPT Project instructions, connector routing, endpoint configuration,
  staging deployment state, or production state.

Parallel workers use separate worktrees/branches and only the file ownership
assigned by this document. A worker ends with a clean committed branch and
reports its commit hash. The coordinator integrates worker commits serially.

### Predecessor uncertainty rule

Before **every numbered step or parallel wave**, verify its direct predecessors
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
the progress JSON `dependency_audit` object. On PASS, mark 4.0 `complete` and
set `next_step=4.1`. On a blocker discovered **after** workspace bootstrap,
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

1. `phase3-progress.json` is `complete` with no unresolved worker/wave/slot.
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
| **4.2A/B/C/D** Wave 4A | 4.1 | one frozen `phase4_source_head`; worker branches from that exact HEAD |
| **4.3** integrate/smoke endpoints | all code-producing 4.2 lanes | worker commits/tests integrated; endpoint code locally runnable |
| **4.4** live Project/connector setup + smoke | 4.3 + 4.2D readiness | local endpoints green; Project/connector prerequisites resolved |
| **4.5** pre-run M1/M2/M3 | 4.4 | all live routing/instruction hashes verified |
| **4.6** parallel qualification | 4.5 | micro sanity PASS + qualification schedule frozen |
| **4B** targeted calibration | 4.6 | isolation healthy; surviving Phase-3 candidate set unchanged |
| **4.7** select C budget | every required 4B lane | canonical calibration slots complete, including expected R12 safety slot |
| **4.8** freeze confirmatory schedule | 4.7 | selected budget fixed + execution mode (serial/parallel) fixed |
| **4.9.1–4.9.6** macro groups | 4.8, then prior group checkpoint | frozen schedule; previous group slot integrity verified |
| **4.10** post-run micros | 4.9.6 | all main canonical slots frozen exactly once |
| **4C** evidence review | 4.10 | post-run micro evidence frozen + canonical trials immutable |
| **4.11** hard-gate matrix | all 4C lanes | four review artifacts + canonical metrics reconcile |
| **4.12** GO/NO-GO | 4.11 | hard-gate matrix internally consistent |
| **4.13** final checkpoint | 4.12 | verdict fixed; no open evidence-integrity blocker |

### Phase-4 worker branch/worktree topology

Step 4.1 creates these exact Wave-4A workers from `phase4_source_head`:

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

Wave-4B live calibration does **not** create code branches; its four sessions use
the frozen integration worktree only for read-only orchestration and write raw
trial state outside Git. Canonical trial evidence is frozen/imported by the
coordinator between blocks. No calibration session edits source/config files.

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

Each review worker commits only its two review artifacts. Step 4.11 coordinator
cherry-picks those four commits in Slot A/B/C/D order before generating the
canonical gate matrix.

Wave-4A assignment is exactly:

```text
Slot A coordinator: 4.2D external/Project readiness only
Slot B:             4.2C analyzer
Slot C:             4.2B harness
Slot D:             4.2A endpoint launcher
```

**4.2D must not claim that Projects already route to final A/B/surviving-C/H connectors.**
At this point endpoints are still being implemented. Its job is to create/verify
the required benchmark Projects where supported, snapshot `rp-test-sandbox`, inspect
connector-registration capability, and record any owner UI action still needed.
Actual connector attachment/routing/schema verification occurs serially in 4.4
after 4.3 endpoints are green.

Wave-4C review outputs are disjoint and fixed:

```text
Slot A: benchmarks/chat-mode-scheduling-v2/phase4-review-correctness-safety.{json,md}
Slot B: benchmarks/chat-mode-scheduling-v2/phase4-review-performance-bootstrap.{json,md}
Slot C: benchmarks/chat-mode-scheduling-v2/phase4-review-reliability-provenance.{json,md}
Slot D: benchmarks/chat-mode-scheduling-v2/phase4-review-scheduling-efficiency.{json,md}
```

Only the coordinator writes 4.11's canonical hard-gate matrix.

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

### Wave-4A file ownership

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
the coordinator rather than silently changing benchmark semantics.

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

#### Static topology registry — committed

Step 4.2A writes the worker-owned immutable base:

```text
benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology-base.json
```

It contains deterministic, non-secret identities for all six reserved lanes and
no Project ids or mutable attachment status. Step 4.2D writes Project/control-
plane findings only to `phase4-readiness.json`.

After 4.3 integrates all Wave-4A commits, the **coordinator** joins the base
mapping with readiness evidence and writes:

```text
benchmarks/chat-mode-scheduling-v2/phase4-endpoint-topology.json
```

Before 4.4 it may contain `project_id=null` / `attachment_status=pending` for an
external action not yet completed. Step 4.4 coordinator updates only those
external identity/status fields after readback verification, then freezes the
file before 4.5. No parallel worker edits the final topology.

The base/final topology schema contains:

```text
schema_version
phase4_source_head
endpoint_id              # A/B/C120/C300/C600/H
logical_arm              # A/B/C/H
budget_s                 # null for A/B, 120/300/600 for C*, 10 for H
host = 127.0.0.1
port                      # 8110..8115 fixed by this plan
tunnel_profile
connector_logical_name
project_name
project_id                # final topology only; null until 4.4 if pending
attachment_status         # final topology: pending|verified|not_started
started_for_this_run      # false for Phase-3-rejected C candidates
```

No PID, token value, cookie, API key, auth header, or secret environment content
belongs in either topology file. Step 4.3 records base/readiness hashes. Step 4.4
freezes `phase4-endpoint-topology.json` and records its SHA-256 in progress. After
the first canonical live submission, changing it invalidates the live experiment
unless the coordinator aborts/restarts the frozen schedule.

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
runtime endpoint whose port/profile/budget identity disagrees with the committed
base/final topology. Live submission additionally requires the frozen final
topology SHA and `attachment_status=verified` for that lane.

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
static_topology_sha256
runtime_registry_sha256
server_log_identity/start_offset/end_offset/sha256
manager_log_identity/start_offset/end_offset/sha256
tunnel_log_identity/start_offset/end_offset/sha256
```

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
- primary-journal noise is ignored;
- byte-offset capture handles pre-existing log content;
- static/private registry hash mismatch fails **before submission**;
- stale PID/process identity cannot be reused;
- log truncation after submission produces `evidence_integrity_error=true` and
  never triggers a replacement canonical trial.

### Endpoint launcher CLI

Endpoint lifecycle is intentionally two-stage:

```bash
# Step 4.3: local manager/server only; no external tunnel dependency
uv run python scripts/chat_scheduling_endpoints.py start-local \
  --root /tmp/binnacle-chat-scheduling-v2/phase4/endpoints \
  --endpoint A --endpoint B --endpoint C300 --endpoint H

# Step 4.4 only, after profiles/control-plane attachment are ready
uv run python scripts/chat_scheduling_endpoints.py start-tunnels \
  --root /tmp/binnacle-chat-scheduling-v2/phase4/endpoints \
  --endpoint A --endpoint B --endpoint C300 --endpoint H

uv run python scripts/chat_scheduling_endpoints.py status \
  --root /tmp/binnacle-chat-scheduling-v2/phase4/endpoints

uv run python scripts/chat_scheduling_endpoints.py stop \
  --root /tmp/binnacle-chat-scheduling-v2/phase4/endpoints
```

`start-tunnels` fails if the endpoint is not locally healthy or its required
profile/env file is absent. It never creates profiles; 4.2D/4.4 control-plane
readiness owns that responsibility.

The actual C endpoint list is generated from the Phase-3 live shortlist. `start`
fails on an endpoint id not in `A/B/C120/C300/C600/H` or on a reserved port
already owned by an unrelated process.

### Confirmatory analyzer CLI

Schedule generation:

```bash
uv run python scripts/chat_scheduling_confirmatory.py schedule \
  --seed <recorded-seed> \
  --mode serial|parallel \
  --selected-budget <120|300|600> \
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

4.3 integrated:
  uv run pytest -q tests/scripts/test_chat_scheduling_endpoints.py \
    tests/scripts/test_chat_scheduling_historical_guard.py \
    tests/scripts/test_chat_scheduling_harness.py \
    tests/scripts/test_chat_scheduling_evidence.py \
    tests/scripts/test_chat_scheduling_analyzer_identity.py \
    tests/scripts/test_chat_scheduling_confirmatory.py \
    tests/scripts/test_chat_scheduling_analyzer.py \
    tests/scripts/test_chat_scheduling_manifest.py
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

H is targeted only. It is never a production candidate.

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
/tmp/binnacle-chat-scheduling-v2/phase4/endpoints/<endpoint-id>/
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

Before a Project is attached in Step 4.4, require both the profile health URL and
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
>=70% repeated-wait burden reduction under replay
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

### Targeted budget calibration

Surviving C budgets from Phase 3 may run in parallel across separate guarded
endpoints/Projects because this stage primarily classifies completion and budget
exhaustion. Up to three C candidates plus H can occupy four sessions.

### Full confirmatory A/B/C

Before allowing simultaneous matched A/B/C blocks, Step 4.6 must qualify local
contention. If qualification fails, use serial randomized arm order.

If qualification passes, a matched block may submit the same
`scenario/repeat/nonce-class` A/B/C trials within a narrow time window on three
isolated endpoints. Record host load and per-server dispatch timing for the whole
block. A block is `host_load_flagged=true` when a checkpoint 1-minute load
average exceeds `0.75 * nproc` or an available `vcgencmd get_throttled` is not
`0x0`. The submitted outcomes remain canonical and are **not replaced**. After
the frozen schedule is complete, an extra matched block may be run as diagnostic
evidence, but it cannot replace the flagged canonical slots.

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

### Wave 4A — preparation, up to four sessions

#### Step 4.2A — isolated endpoint launcher — Slot D

Target: 15–20 minutes.

Implement benchmark-only scripts/config templates that launch A/B/H plus every surviving C120/C300/C600 endpoint
with separate ports, job dirs, sockets, tokens and logs. No primary systemd/config
files are changed.

#### Step 4.2B — harness multi-arm support — Slot C

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

#### Step 4.2C — confirmatory analyzer/report generator — Slot B

Target: 15–20 minutes.

Implement aggregate A/B/C/H tables, category medians, paired C/A bootstrap,
reliability deltas, hard-gate matrix and submitted-slot integrity checks. Do not
consume live data yet.

#### Step 4.2D — Project/connector external-readiness audit — Slot A coordinator

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
instruction-hash verification are **Step 4.4**, after 4.3 local endpoints pass.

### Step 4.3 — integrate Wave 4A and smoke endpoints

Target: 15–20 minutes.

Serial coordinator integration. Cherry-pick Wave-4A commits in worker-step
order **4.2A -> 4.2B -> 4.2C -> 4.2D** (physical Slots D -> C -> B -> A) only
after every worker reports its commit/tests/clean worktree. Verify `phase4-endpoint-topology-base.json` and
`phase4-readiness.json` are each owned by the intended worker, then generate the
initial coordinator-owned `phase4-endpoint-topology.json`. Do not ask either
worker to resolve cross-file Project identity joins.

Use local MCP smoke calls on every started endpoint and verify distinct job
spools, log paths, sockets, and budget behavior:

```text
A/B: no_policy
C120/C300/C600 that survived: tracked with exactly 120/300/600 respectively
H: first wait <=10, later wait 0
```

### Step 4.4 — live Project/connector provisioning and smoke

Target: 15–20 minutes plus any owner UI action already identified by 4.2D.

First execute **exactly the connector/profile attachment mechanism audited by
4.2D** for every started benchmark lane. If 4.2D recorded an unresolved owner UI
action, stop here until that action is completed; do not invent another API or use
the primary connector. Read back Project id/name, attached connector identity,
profile health and tool schema before the smoke chat.

Then one tiny disposable chat per started benchmark Project verifies:

- intended connector is callable;
- correct endpoint receives the call;
- Project/connector ids and tunnel-log paths are written into the endpoint
  registry; after every started Project passes, freeze its SHA in progress;
- instruction hash is fixed;
- no primary production call was accidentally routed;
- test chat can be backed up/deleted;
- instructions remain unchanged afterward.

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
sanities. If any required condition fails, stop before 4.6 and investigate the
endpoint/Project/model/product state. Do not continue macro trials while calling
the micro failure "noise".

### Step 4.6 — qualify simultaneous A/B/C live blocks

Target: 15–20 minutes plus trial time.

Use one read-heavy/control block and one wait-heavy/control block. Compare serial
versus simultaneous server-side evidence.

Parallel matched blocks are allowed only if **all** of these pass:

- no endpoint/tunnel error in the qualification block;
- no cross-spool/cross-project evidence;
- Pi 1-minute load average stays <= `0.75 * nproc` at block checkpoints
  (3.0 on the current 4-core Pi);
- when `vcgencmd get_throttled` is available it reports `0x0`; absence of the
  command is recorded but is not itself a failure;
- per-arm `dispatch_ms` p95 in parallel is <= `max(serial_p95 + 20 ms,
  serial_p95 * 2)`;
- non-blocking local implementation overhead p95 (implementation minus intended
  blocking wait) is <= `max(serial_p95 + 20 ms, serial_p95 * 1.25)`;
- maximum qualification `dispatch_ms` is <=100 ms in both serial and parallel
  qualification runs; any larger dispatch delay fails parallel qualification
  rather than requiring a subjective explanation;
- no arm loses correctness or connector reachability only in parallel mode.

Any failed or unmeasurable criterion selects **serial randomized live trials**.
Record the decision once; do not switch modes mid-confirmatory run without
invalidating/restarting the schedule.

### Wave 4B — targeted live budget calibration

Use only candidates that survived Phase 3.

Up to four sessions may run simultaneously:

```text
Slot A  C120 targeted R5/R6/R7/R12 (if C120 survived)
Slot B  C300 targeted R5/R6/R7/R12 (if C300 survived)
Slot C  C600 targeted R5/R6/R7/R12 (if C600 survived)
Slot D  H10  targeted R5/R6/R7/R12
```

Each slot has an independent endpoint/Project. Canonical inclusion rule applies.
For one candidate, the bounded calibration denominator is the nine R5/R6/R7
trials. Therefore `same-prompt >=95%` means **9/9 must pass** and the <=10%
outside-R12 exhaustion rule means **0/9 unexpected exhaustion**. R12 is the
separate expected-exhaustion safety case.

### Step 4.7 — select the full-confirmatory C budget

Serial.

Choose the **smallest live candidate** that simultaneously satisfies the targeted
budget-selection rules:

```text
bounded-suite same-prompt >=95%
premature handoff = 0
budget-exhaustion handoff <=10% outside R12
>=70% repeated-wait burden reduction under the frozen replay metric
0 submitted interruption among the nine bounded R5/R6/R7 calibration trials
```

If no candidate passes, Phase 4 stops NO-GO. Do not invent a fourth budget
without a new owner-approved experiment.

Record `selected_c_endpoint` as exactly `C120`, `C300`, or `C600` matching the
selected budget. All subsequent confirmatory C slots use only that endpoint and
Project; never rewrite another C endpoint's budget to impersonate the selected
one.

### Step 4.8 — generate deterministic confirmatory schedule

Generate all remaining A/B/C slots with fixed seed recorded in progress. If
serial mode is required, randomize arm order inside each scenario/repeat block.
If parallel mode is qualified, create matched A/B/C blocks and rotate logical-arm-to-physical-session assignment deterministically across
blocks using the same recorded seed.

Write and freeze the schedule at exactly:

```text
benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-schedule.json
```

The JSON includes schedule schema version, seed, execution mode, selected budget,
selected C endpoint, ordered blocks/slots, scenario/repeat/arm, and any calibration
slot reused as a confirmatory slot. Record its SHA-256 in progress before the
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
- selected-budget calibration trials may count only under the **Reuse rule for candidate calibration** defined in this Phase-4 document
  are satisfied.

Other sessions may **read/analyze** completed block state in parallel but they
must not edit canonical progress, import/freeze trial files into Git, change live
endpoint config, or change Project instructions. They write diagnostic scratch
output only under `/tmp/binnacle-chat-scheduling-v2/phase4/diagnostics/<slot>/`.
After each 4.9 group, the coordinator alone validates slot integrity, imports any
canonical evidence artifacts, updates progress, and commits/pushes the checkpoint.

Treat Step 4.9 as six resumable checkpoints so one chat transaction does not own
the entire confirmatory run:

```text
4.9.1  R1/R2        read-heavy
4.9.2  R3/R4        overlap + long overlap
4.9.3  R5/R6        true dependency barriers
4.9.4  R7           repeated long barriers
4.9.5  R8/R9        development + recovery journeys
4.9.6  R10/R11      quiet job + multi-round planning
```

After each substep, freeze all completed trial directories, update canonical
progress, **always commit and push that group checkpoint** (progress itself
changes), and verify no scheduled slot is missing or duplicated. The next
transaction resumes at the next substep; it never restarts a complete group. A
checkpoint commit does not rerun submitted slots merely because its CI later
fails; fix source/analysis infrastructure without replacing canonical trial
outcomes.

### Step 4.10 — post-run M1/M2/M3 sanity

Repeat M1/M2/M3 on A, B, and `selected_c_endpoint` to detect a session-wide client/product change
between beginning and end.

### Wave 4C — parallel evidence review

After all canonical slots are frozen:

```text
Slot A  correctness/safety/mutation audit
Slot B  performance/bootstrap/category analysis
Slot C  reliability/timeout-provenance/same-prompt audit
Slot D  scheduling/guard/token/call-efficiency audit
```

Each writes a separate review artifact. No lane writes the final verdict.

### 24.1 Confirmatory sample arithmetic

For C's 53 bounded macro slots, the >=95% same-prompt gate requires at least
**51/53** complete (`50/53 = 94.34%` and fails). Correctness remains 100%, so a
deterministic-oracle failure is a hard failure even if 51/53 same-prompt would
otherwise be reachable. Interruption-rate comparison uses all submitted slots,
not only completed trials.

### Step 4.11 — aggregate hard-gate matrix

Serial coordinator consumes the four reviews and produces the formal C-vs-A/B
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

### Step 4.13 — Phase-4 final validation/checkpoint

Write dated JSON/Markdown report, update progress, run optimized full tests,
pre-commit, CI, production isolation, and endpoint cleanup validation. Do not
delete evidence required by Phase 5/6.

Phase 5 may start only after explicit owner approval of `GO_PHASE5`.

---
