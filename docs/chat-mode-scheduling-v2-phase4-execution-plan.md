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
| Source base | Latest proof-of-concept HEAD/CI identified for common live source |
| Benchmark environment | Isolated A/B/C/H topology is feasible; no fallback to primary connector |

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

## Step 4.0 — Dependency Audit / Entry Gate

**No live endpoint, Project mutation, connector setup, calibration, or trial may
start before this audit passes.**

Phase 4 depends on a fully closed Phase 3 and on the latest proof-of-concept line
being suitable as the common live server source base.

### Required Phase-3 state

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
7. Phase-3 tests/pre-commit/CI are green and its final checkpoint is integrated
   into the scheduling design line.
8. Replay corpus/candidate artifacts are deterministic and no submitted Phase-1
   slot was silently dropped.

### Required source-line state

Verify the latest `origin/proof-of-concept` and `origin/master` relationship and
CI. Record the proof-of-concept HEAD that Step 4.1 will use as the common server
base. Do not yet integrate/mutate it during the audit.

Also re-check that the completed test-efficiency runner/coverage policy inherited
by Phase 3 is still the authoritative test workflow.

### External/environment prerequisites

Record current availability/status of:

- Chrome/session credentials used by the benchmark harness;
- the benchmark source Project `rp-test-sandbox` and its current instructions;
- ability to create/use the isolated A/B/C/H connector/Project topology, noting
  any one-time UI/account action that still requires the owner;
- ports 8110–8113 availability;
- production observation baseline.

Missing external registration capability may leave Phase 4 `BLOCKED_EXTERNAL`,
but it must not cause the agent to fall back to the primary production connector.

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
proof_of_concept_head_and_ci
test_runner_inheritance
benchmark_project_snapshot
isolated_endpoint_prerequisites
production_isolation
```

### Exit criteria

```text
dependency audit PASS committed
Phase-3 shortlist/hash frozen
proof-of-concept source base frozen for Step 4.1
external setup blockers = none
next allowed step: 4.1
```

## Canonical Phase-4 handoff contract

Step 4.13 must write:

```text
benchmarks/chat-mode-scheduling-v2/phase4-live-confirmatory-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase4-live-confirmatory-YYYY-MM-DD.md
```

`phase4-progress.json` `handoff` contains:

```text
final_report_json
final_report_md
final_report_sha256
verdict
selected_budget_s
phase4_source_head
baseline_instruction_sha256
v2_instruction_sha256
canonical_schedule_sha256
canonical_trial_count_A/B/C/H
all_hard_gates_pass
phase5_ready = true | false
```

Phase 5.0 recomputes the report/hash/gate identities before staging.

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

At Step 4.1:

1. fetch the latest green `origin/proof-of-concept`;
2. create the Phase-4 integration branch **from that proof-of-concept HEAD**;
3. merge/cherry-pick the completed Phase-3 scheduling changes onto it;
4. run the inherited optimized test/coverage gate;
5. freeze the resulting commit as `phase4_source_head`;
6. launch A/B/C/H endpoints from exactly that commit.

A/B have the cumulative guard code present but disabled by an empty budget map.
That is the baseline server behavior for the confirmatory run. Step 4.1 records
a focused default-policy equivalence check against the latest proof-of-concept
behavior before live measurement.

A Project instructions are recaptured from the actual baseline Project state at
Phase-4 start, before any benchmark mutation. B/C/H use the canonical v2 rule
file hash.

### 20.2 Required isolated topology

Use four isolated benchmark lanes, all built from the **same frozen Phase-4 code
commit** and differing only in explicit arm policy/config:

```text
A endpoint: port 8110, guard disabled
B endpoint: port 8111, guard disabled
C endpoint: port 8112, candidate budget configured
H endpoint: port 8113, benchmark-only historical one-shot adapter
```

Each endpoint has its own:

```text
BINNACLE_CONFIG_FILE
jobs.dir
jobs.socket_path
token file
journal/log target
server process/unit name
tunnel profile / connector registration
```

Never share a job spool across A/B/C/H.

The benchmark launcher created in Step 4.2A uses this exact filesystem root:

```text
/tmp/binnacle-chat-scheduling-v2/phase4/endpoints/<arm>/
```

For each arm it writes:

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

Ports 8110–8113 are reserved by this plan. Step 4.2A must fail if any is already
in use; do not silently choose another port because connector evidence would no
longer match the frozen topology.

Fixed logical names:

```text
server units:
  binnacle-sched-a.service
  binnacle-sched-b.service
  binnacle-sched-c.service
  binnacle-sched-h.service

tunnel profiles/connectors:
  Raspberry Pi MCP Scheduling A
  Raspberry Pi MCP Scheduling B
  Raspberry Pi MCP Scheduling C
  Raspberry Pi MCP Scheduling H

ChatGPT Projects:
  rp-sched-A
  rp-sched-B
  rp-sched-C
  rp-sched-H
```

These four benchmark Projects did not exist at planning time and are created in
Step 4.2D. Baseline instruction text is captured at Phase-4 start from the
existing benchmark source Project:

```text
rp-test-sandbox
g-p-6aaea9da2bc881918d6f9eb5177cf904
```

`rp-sched-A` receives that exact captured text. B/C/H receive the canonical v2
instruction file. Once Phase-4 trials begin, no benchmark Project instruction is
mutated until the run is closed.
Instructions remain fixed for the whole live run; do not switch a shared
Project's instructions between trials.

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

C is eligible for Phase 5 only if all hard gates and main performance gates pass.

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

### Scheduling

```text
avoidable blocking wall p90 <=2 s
eligible overlap ratio >=80%
M2/M3 sliding refill remains demonstrated
```

### Guard

```text
union blocking wall <= budget + rounding tolerance
overlap charged once
exhausted calls become nonblocking
p95 guard overhead <1 ms; p99 <2 ms
>=70% repeated-wait burden reduction under replay
```

### Efficiency

```text
tool-result tokens <= A +5% overall
target >=10% reduction in long-job status-call/result burden
no increase in duplicate completed reads
```

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
block. A block contaminated by an unrelated host load event is flagged before
analysis according to a predeclared rule; do not discard an arm merely because
its result is poor.

## 24. Phase-4 steps

### Step 4.1 — create Phase-4 integration checkpoint

Target: 10–15 minutes.

Preconditions:

```text
Phase 3 COMPLETE
Phase-3 checkpoint integrated into design branch
all test-efficiency work final/green
production observation baseline captured
```

Create Phase-4 branch/worktree/progress files and freeze source HEAD, model/UI
settings, Chrome profile, Project instruction hashes, and candidate shortlist.

### Wave 4A — preparation, up to four sessions

#### Step 4.2A — isolated endpoint launcher — Slot D

Target: 15–20 minutes.

Implement benchmark-only scripts/config templates that launch A/B/C/H endpoints
with separate ports, job dirs, sockets, tokens and logs. No primary systemd/config
files are changed.

#### Step 4.2B — harness multi-arm support — Slot C

Target: 15–20 minutes.

Extend harness metadata/CLI from A/B to A/B/C/H without embedding production
configuration mutations. The live trial CLI becomes:

```bash
uv run python scripts/chat_scheduling_harness.py trial R7 \
  --arm C --budget-s 300 --endpoint C
```

`--arm` choices are exactly `A/B/C/H`. `--budget-s` is forbidden for A/B,
required for C, and fixed to 10 for H. `--endpoint` must match the arm unless a
test explicitly injects a fake endpoint. R12 resolves its runtime from
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

#### Step 4.2D — independent endpoint/project setup audit — Slot A/independent

Target: 15–20 minutes plus any external registration action.

Verify four Projects use the intended connectors and instructions, all tool
schemas match, and primary production connector remains unchanged.

### Step 4.3 — integrate Wave 4A and smoke endpoints

Target: 15–20 minutes.

Serial integration. Use local MCP smoke calls on every endpoint. Verify distinct
job spools and distinct budget behavior:

```text
A/B: no_policy
C: tracked with configured candidate
H: first wait <=10, later wait 0
```

### Step 4.4 — live Project/connector smoke

Target: 15–20 minutes.

One tiny disposable chat per Project verifies:

- intended connector is callable;
- correct endpoint receives the call;
- instruction hash is fixed;
- no primary production call was accidentally routed;
- test chat can be backed up/deleted;
- instructions remain unchanged afterward.

### Step 4.5 — pre-run micro scheduler sanity

Run M1/M2/M3 before the main session. Abort live macro measurement if basic
scheduler behavior is clearly broken or connector routing is inconsistent.

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
- no qualification tool call exceeds 100 ms of unexplained dispatch queueing;
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
no unacceptable timeout/stream reliability increase
```

If no candidate passes, Phase 4 stops NO-GO. Do not invent a fourth budget
without a new owner-approved experiment.

### Step 4.8 — generate deterministic confirmatory schedule

Generate all remaining A/B/C slots with fixed seed recorded in progress. If
serial mode is required, randomize arm order inside each scenario/repeat block.
If parallel mode is qualified, create matched A/B/C blocks and rotate logical-arm-to-physical-session assignment deterministically across
blocks using the same recorded seed.

Freeze the schedule before running it.

### Step 4.9 — run confirmatory macro suite

This is the long critical lane.

Rules:

- execute exactly the frozen schedule;
- first submitted outcome owns each slot;
- keep host/tunnel health evidence around each block;
- save/analyze each trial immediately so evidence loss is detected early;
- do not rerun a submitted timeout;
- selected-budget calibration trials may count when Section-21 reuse conditions
  are satisfied.

Other sessions may score/freeze completed blocks in parallel but must not change
live endpoint config/Project instructions.

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
progress, push the checkpoint commit if source/evidence files changed, and verify
no scheduled slot is missing or duplicated. The next transaction resumes at the
next substep; it never restarts a complete group.

### Step 4.10 — post-run M1/M2/M3 sanity

Repeat scheduler microbenchmarks to detect a session-wide client/product change
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
