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
| Stage 1 | Genuine 24-hour gate passed |
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

## Step 6.0 — Dependency Audit / Entry Gate

**No Phase-6 operational window analysis or final integration may begin before
this audit passes.**

Phase 6 depends on Phase 5 having successfully staged the policy through the
first Project and then the normal Raspberry Pi development Project.

### Required Phase-5 state

Verify:

1. `phase5-progress.json` is `complete`, not `rolled_back` or `blocked`.
2. Stage 1 (`Binnacle`) deployment timestamp, exact instruction snapshot,
   connector mapping, selected budget, and staging source hash are recorded.
3. Stage-1 immediate smoke passed.
4. The genuine Stage-1 24-hour observation gate elapsed; its four parallel review
   artifacts exist and the Stage-1 decision is PASS.
5. Stage 2 (`Raspberry Pi 5`) switch is recorded with exact `stage2_started_at =
   T0`, instruction snapshot, connector mapping, and rollback state.
6. Stage-2 immediate smoke passed and the Project is actually using the same
   selected budget/source/instructions approved by Phase 4/5.
7. No hard rollback condition occurred between Stage 2 start and Phase-6 entry.
8. Persistent staging server/manager/tunnel are healthy; durable jobs are not
   stranded in an obsolete endpoint.
9. Phase-5 progress/evidence hashes and any CI/test evidence are consistent.

### Cross-phase consistency check

Recompute/compare these immutable identities across Phase 4 -> Phase 5 -> Phase 6:

```text
selected_budget_s
approved_server_source_head
v2_instruction_sha256
staging_connector identity
staging config sha256 (except explicitly documented runtime-only fields)
Phase-4 reference report sha256
```

Any unexpected mismatch blocks Phase 6 until explained. Do not silently treat a
changed deployment as the same experiment.

### Audit result

Required rows include:

```text
phase5_progress
stage1_24h_gate
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

## Canonical Phase-6 final-report contract

Step 6.9 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase6-post-deployment-review-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase6-post-deployment-review-YYYY-MM-DD.md
```

`phase6-progress.json` records the T+24h verdict, T+7d verdict, final operational
verdict, primary-integration approval/commit if performed, primary-cutover 24h
verdict, cleanup state, rollback-retention deadline, and final Phase 0–6
retrospective path. There is no implicit next phase.

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

Rollback staging immediately on any of:

```text
deterministic correctness/safety regression attributable to scheduling v2
primary connector reachability harm caused by rollout
any tracked turn blocking wall > configured budget + 1.0 second
systematic premature handoff on work known to fit the budget
interruption rate > Phase-4 C +2 percentage points with >=20 eligible turns, or
  at least two attributable excess interruptions when sample size is smaller
three or more staging-attributable connector/server failures in any rolling 24 h,
  or one outage >60 seconds
```

A single unexplained observation should be investigated, but hard safety failures
do not wait for the 7-day review.

## 32. Phase-6 steps

### Step 6.1 — initialize review windows

At Stage-2 start, create Phase-6 progress and record exact T0, T+24h and T+7d.
Freeze Phase-4/5 reference reports and production baseline hashes.

### Step 6.2 — T+24h data freeze

At or after T+24h, freeze exactly the first 24-hour operational window into
normalized, privacy-minimized evidence. Do not extend the window opportunistically
because the review was started late; use timestamps.

### Wave 6A — T+24h parallel analysis

```text
Slot A  reliability/reachability/interruptions
Slot B  blocking wall/budget/exhaustion
Slot C  calls/tokens/concurrency/efficiency
Slot D  same-turn proxy/continuations/correctness incidents
```

### Step 6.3 — T+24h gate

Serial aggregate. Produce a 24-hour report and choose:

```text
CONTINUE_TO_7D
ROLLBACK
BLOCKED_EVIDENCE
```

Only `CONTINUE_TO_7D` keeps the staged rollout active.

### Step 6.4 — wait to T+7d

Intentional wall-clock gate. Progress becomes `waiting_wall_clock` with exact
`resume_not_before`.

### Step 6.5 — T+7d data freeze

Freeze both:

```text
full T0..T+7d window
incremental T+24h..T+7d window
```

so late degradation is not hidden by averaging with the first day.

### Wave 6B — T+7d parallel analysis

Use the same four lanes as Wave 6A, each comparing:

```text
Phase-4 confirmatory C
Phase-5 first-project 24 h
Phase-6 first 24 h
Phase-6 days 2–7
full 7 d
```

### Step 6.6 — final operational go/no-go

Possible outcomes:

```text
GO_PRIMARY_INTEGRATION
ROLLBACK
EXTEND_OBSERVATION_WITH_OWNER_APPROVAL
BLOCKED_EVIDENCE
```

`EXTEND_OBSERVATION_WITH_OWNER_APPROVAL` is not an automatic escape from a failed
gate; it is only for insufficient volume/evidence when no hard gate failed.

### Step 6.7 — final primary integration, only after GO

This step is serial and destructive enough to require explicit owner approval.

Before enabling the budget on the primary connector, freeze a **connector
consumer inventory**: list every known ChatGPT Project that uses the primary
Raspberry Pi MCP connector. Because the server policy sees only the
`openai-mcp` client prefix, not Project identity, primary budget enablement
affects all such Projects. If any consumer has not been included in the owner's
rollout scope, do not enable the primary budget; remain on staging and report the
blocker.

Branch policy follows the owner's established preference:

1. fetch latest `origin/proof-of-concept` and `origin/master`;
2. verify their relationship and current CI;
3. create a release-integration branch from the **latest proof-of-concept**;
4. integrate the approved scheduling-v2 design/staging commits onto it;
5. reconcile any independent changes made since Phase 4;
6. run the repository's final optimized full test/coverage/CI matrix;
7. merge to `proof-of-concept`;
8. synchronize `master` only under the repository's current release workflow and
   explicit owner instruction;
9. deploy code with repository-default guard still disabled first;
10. smoke primary server/connector;
11. enable the selected client budget in deployment-local config;
12. apply v2 Project instructions;
13. re-smoke long-job flow and verify effective config/log telemetry.

Do not combine code merge, config enablement, and Project-instruction change into
one opaque action. Each has an independent rollback checkpoint.

### Step 6.8 — primary cutover immediate smoke and 24-hour confirmation

After Step 6.7, run immediate read + short background-job smoke through the
**primary** connector and verify effective config, instruction hash, guard
telemetry, durable-job behavior, and rollback switches.

Then hold a final 24-hour primary-cutover observation window. This does not
repeat the full seven-day staging experiment; it checks route/config/integration
regressions introduced specifically by moving from the staging connector to the
primary connector. Use the same four analysis lanes at T+24 h. Any hard rollback
condition from Section 31 applies.

### Step 6.9 — cleanup and final project report

After the primary-cutover 24-hour confirmation is healthy:

- retain canonical benchmark/replay/staging evidence;
- delete throwaway benchmark chats;
- retire temporary A/B/C/H endpoints/connectors only after confirming no Project
  still depends on them;
- retire the staging endpoint only after primary rollback confidence is accepted;
- preserve rollback snapshots for at least 7 additional days after primary
  cutover unless the owner explicitly chooses a longer period;
- mark all progress files complete;
- write one final Phase 0–6 retrospective linking every phase decision;
- document any remaining readability/observability debt separately from the
  scheduling result.
