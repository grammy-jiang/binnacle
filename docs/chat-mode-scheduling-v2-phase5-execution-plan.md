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

### Coordinator and parallel workers

The owner can normally run up to four ChatGPT sessions concurrently. One session
is always the **coordinator**. Only the coordinator may edit:

- this phase's canonical progress JSON/Markdown;
- dependency-audit artifacts;
- integration-branch history;
- final phase verdict/report;
- shared ChatGPT Project instructions, connector routing, endpoint configuration,
  staging deployment state, or production state.

Parallel workers use separate worktrees/branches and only the file ownership
assigned by this document. A worker ends with a clean committed branch and
reports its commit hash. The coordinator integrates worker commits serially.

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
benchmarks/chat-mode-scheduling-v2/phaseN-dependency-audit-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phaseN-dependency-audit-YYYY-MM-DD.md
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

## Step 5.0 — Dependency Audit / Entry Gate

**No staging connector switch, persistent staging service, Project-instruction
change, or 24-hour timer may start before this audit passes.**

Phase 5 depends entirely on a successful Phase-4 confirmatory verdict and an
explicit owner decision to proceed.

### Required Phase-4 state

Verify all of the following directly from Phase-4 canonical evidence:

1. `phase4-progress.json` is `complete` and all canonical submitted slots are
   frozen exactly once.
2. The final Phase-4 verdict is exactly `GO_PHASE5`; any `NO_GO_*` blocks Phase 5.
3. The selected cumulative budget is one of the Phase-3 candidates and is
   explicitly recorded in the final Phase-4 report.
4. Every hard gate passed: correctness, safety, tool contract, production
   isolation, and zero premature handoff where dependency work fits budget.
5. Same-prompt/reliability, performance, scheduling, guard, and efficiency gates
   all pass using the frozen sample; the coordinator must not summarize a failed
   gate as "close enough".
6. Pre/post micro scheduler sanity passed or any change is explicitly resolved.
7. Timeout-provenance review reconciles with submitted-slot inclusion.
8. Phase-4 final CI/pre-commit/tests are green.
9. Temporary A/B/C/H endpoint evidence is closed and no benchmark-owned live job
   is left running.

### Required rollout authorization and staging prerequisites

Verify:

- the owner explicitly approved progression after seeing `GO_PHASE5`;
- exact current instructions for `Binnacle` and `Raspberry Pi 5` are snapshotted
  for rollback;
- the persistent staging port/config/token/job/socket paths are free/ready;
- the staging connector can be provisioned without modifying the primary
  connector;
- rollback commands/snapshots are available before any mutation;
- production observation baseline is frozen again at Phase-5 start.

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

## Canonical Phase-5 handoff contract

Step 5.7 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase5-staged-deployment-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase5-staged-deployment-YYYY-MM-DD.md
```

`phase5-progress.json` `handoff` contains:

```text
final_report_json
final_report_md
final_report_sha256
selected_budget_s
approved_source_head
v2_instruction_sha256
staging_connector_identity
staging_config_sha256
stage1_started_at
stage1_24h_verdict
stage2_started_at   # Phase-6 T0
stage2_smoke_pass
rollback_snapshot_paths
phase6_ready = true | false
```

Phase 6.0 recomputes these identities against Phase 4 and current staging state.

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

Phase 5 does **not** reuse the ephemeral `/tmp` Phase-4 endpoint. It promotes the
approved source/config into one persistent, isolated staging stack:

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
8120. Provision these as separate user units or `systemd-run --user` units; do
not overwrite `binnacle-mcp.service`, `binnacle-jobs.service`, or the primary
tunnel profile.

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
-> v2 Project instructions
```

`Raspberry Pi 5` remains unchanged.

After Stage-1 24-hour gate passes:

```text
Raspberry Pi 5
-> guarded staging connector
-> same selected budget
-> v2 instructions
```

The primary production connector/server can remain untouched through the full
staged observation. Final integration to the primary line occurs only after
Phase-6 gates.

## 28. Phase-5 steps

### Step 5.1 — staging release freeze and rollback rehearsal

Target: 15–20 minutes.

Create `release/chat-mode-scheduling-v2-staging` from the exact Phase-4 approved
commit. Freeze:

```text
selected budget
Project instruction hashes
connector ids
staging endpoint source hash
primary production observation baseline
rollback commands/snapshots
```

Rehearse instruction restore and staging-connector budget disable on a test
Project before real stage deployment.

### Step 5.2 — deploy to Binnacle development Project only

Serial deployment action.

- point only the Binnacle development Project at guarded staging connector;
- set exact v2 instructions;
- verify selected budget in staging effective config;
- run one read smoke and one short background-job dependency smoke;
- verify primary normal Project still routes to its old connector.

Record `stage1_started_at`.

### Step 5.3 — immediate 30–60 minute smoke window

Monitor:

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

### Step 5.4 — Stage-1 24-hour observation gate

This is an intentional wall-clock gate. Do not compress it into synthetic time.
Progress status becomes `waiting_wall_clock` with:

```text
resume_not_before = stage1_started_at + 24 h
```

If scheduling/reminder automation is available at execution time, create a 24 h
review reminder. The repository progress timestamp remains authoritative.

### Wave 5A — 24-hour parallel review

After the wall-clock gate:

```text
Slot A  reachability / interruption / error review
Slot B  blocking-wall / exhaustion / wait-distribution review
Slot C  tool-call / tokens / concurrency / efficiency review
Slot D  long-job same-turn proxy / continuation / correctness review
```

Each lane uses the exact 24-hour time window and writes a separate immutable
artifact.

### Step 5.5 — Stage-1 decision

Serial coordinator compares live staging data with Phase-4 C and baseline
expectations.

PASS requires:

- zero attributable correctness/safety incidents;
- zero attributable connector outage lasting >60 seconds;
- every tracked turn's blocking union <= selected budget + 1.0 second;
- non-R12-like operational exhaustion rate <=10% when at least 20 tracked turns
  are observed; with fewer than 20 turns, any unexpected exhaustion is manually
  reviewed rather than averaged away;
- interruption rate is not more than Phase-4 C +2 percentage points when at
  least 20 eligible staged turns exist; with fewer than 20, two or more
  attributable excess interruptions is a fail;
- median tool-result tokens per eligible staged turn <= Phase-4 C *1.10 after
  excluding clearly different workload classes; >1.10 is an investigation gate,
  >1.20 with comparable workload is a fail;
- job_status calls per long-job turn do not regress above Phase-4 C by >20% on
  comparable workloads;
- no repeated owner-observed continuation pattern contradicts the same-prompt
  improvement goal.

Fail -> rollback Binnacle development Project and stop Phase 5.

### Step 5.6 — extend to normal Raspberry Pi development Project

Only after Stage-1 PASS.

Switch the normal Project to the same already-qualified guarded staging connector
and v2 instructions. Preserve an exact snapshot of its prior instructions and
connector route. Run immediate smoke checks and record `stage2_started_at`.

Do not merge into primary `master` merely because this switch succeeds.

### Step 5.7 — Phase-5 handoff to Phase 6

Freeze both staged deployment timestamps, rollback snapshots, connector/project
mapping, selected budget, and Phase-4 reference metrics.

Phase 5 is COMPLETE when Stage 2 is live and healthy through immediate smoke.
Phase 6 owns the 24-hour and 7-day review after Stage 2.

---
