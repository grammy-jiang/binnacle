# Chat mode scheduling v2 — Phase 3–6 execution plan and parallel SOP

Status: **PLANNED; PHASES 3–6 NOT STARTED**

Planning date: 2026-09-24 (Australia/Sydney)

Planning branch: `planning/chat-mode-scheduling-v2-phase3-6`

Planning worktree:
`/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-6-plan`

Planning source snapshot: `2e6fb5d` (`test: scope lifecycle job warm-up`).

Important: this source snapshot is **not** the execution source for Phase 3. A
separate ChatGPT transaction is actively optimizing the Binnacle test suite on
`design/chat-mode-scheduling-v2`. Phase 3 must wait for that work to finish and
must start from the later final green design HEAD. Section 12 defines that gate.

This is the cold-start handoff and execution document for the rest of the
Chat-mode scheduling v2 project after Phase 2. It is intentionally detailed so
a future agent with no conversation memory can execute the plan without
re-designing branch topology, replay semantics, benchmark arms, acceptance
gates, parallel-session ownership, staging, rollback, or post-deployment
analysis.

Authoritative related documents:

- `docs/chat-mode-scheduling-v2-design.md` — parent architecture and Phase 0–6
  lifecycle;
- `docs/chat-mode-scheduling-v2-ab-plan.md` — benchmark arms, scenario catalog,
  confirmatory trial counts, and acceptance gates;
- `docs/chat-mode-scheduling-v2-server-guard.md` — cumulative blocking-wall
  guard semantics;
- `docs/chat-mode-scheduling-v2-phase2-execution-plan.md` — completed Phase-2
  implementation/runbook;
- `benchmarks/chat-mode-scheduling-v2/METRICS.md` — executable metric contract;
- `benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.md`
  — Phase-1 aggregate result;
- `benchmarks/chat-mode-scheduling-v2/phase2-blocking-wall-guard-2026-09-24.md`
  — Phase-2 final evidence plus the 2.12a telemetry closeout;
- `docs/test-suite-performance-optimization-plan-2026-09-24.md` and
  `docs/test-suite-performance-optimization-progress-2026-09-24.md` — the
  independent test-efficiency program that must finish before Phase 3 starts.

If this document conflicts with the metric contract on metric arithmetic, the
metric contract wins. If it conflicts with the A/B plan on a frozen production
acceptance threshold, the A/B plan wins. If it conflicts with the Phase-2 guard
specification on server policy semantics, the guard specification wins. This
document controls Phase 3–6 execution order, parallelization, file ownership,
progress persistence, staging topology, and handoff/rollback SOP.

## 1. Correction to the remaining-phase count

The project has **seven numbered phases, 0 through 6**. Phase 0, Phase 1 and
Phase 2 are complete. Therefore four numbered phases remain:

```text
Phase 0  baseline freeze                         COMPLETE
Phase 1  instruction-only A/B                    COMPLETE
Phase 2  cumulative blocking-wall guard          COMPLETE
Phase 3  offline policy replay                   NOT STARTED
Phase 4  live confirmatory A/B/C + targeted H    NOT STARTED
Phase 5  staged deployment                       NOT STARTED
Phase 6  post-deployment review                  NOT STARTED
```

An earlier conversational summary incorrectly said that only Phases 3 and 4
remained. That was wrong; the parent design explicitly includes Phases 5 and 6.
This document restores the full Phase 0–6 lifecycle.

## 2. Project objective carried into Phases 3–6

The user wants ChatGPT to perform a bounded development step continuously inside
one user prompt when no external decision is required. A long background job is
an implementation detail, not a natural assistant stop point.

The desired behavior is:

```text
plan dependencies
-> launch known-long work early
-> use job_id as a Future/Promise handle
-> perform independent work while it runs
-> wait deliberately at true dependency barriers
-> continue repeated legitimate waits while budget remains
-> finish the requested step in the same user prompt
-> report once at the agreed stop point
```

The final product must improve this experience without trading away correctness,
safety, bounded resource use, or platform reliability.

## 3. What Phases 0–2 already established

### 3.1 Phase 1 scheduling signal

Across the Phase-1 canonical macro aggregate:

```text
24 A trials + 24 B trials
24 paired comparisons

A median wall                49.816 s
B median wall                45.789 s
B direct median improvement   8.1%
paired-median improvement     8.3%
B faster pairs               14 / 24

A same-prompt                 87.5%
B same-prompt                 75.0%
A interruption                 8.3%
B interruption                25.0%

A premature handoffs          1
B premature handoffs          0
A manual continuations        1
B manual continuations        0
```

The model-scheduling mechanism improved, so the project continued. Reliability
and confirmatory performance gates did not pass, so no production deployment was
approved.

### 3.2 Phase 2 guard implementation

Phase 2 implemented and validated:

- per-client opt-in blocking-wall budgets;
- `(client, base_turn)` tracking;
- union-of-overlapping-waits accounting;
- actual monotonic wall-time charging;
- bounded 4096-record process-local state;
- active-record eviction protection;
- `no_policy`, `no_turn`, `tracked`, `exhausted`, and
  `capacity_untracked` policy outcomes;
- model-visible budget exhaustion;
- requested/bounded/effective/actual telemetry;
- `blocking_window_closed` cumulative accounting events;
- `binnacle stats` aggregation;
- real-job, concurrency, reload, and performance tests.

The Phase-2 overhead evidence was far below the design ceiling. The independent
2.12a review also closed the positive-wait exception telemetry gap. Phase-2 code
is integrated into `design/chat-mode-scheduling-v2`; repository default remains
an empty budget map.

### 3.3 Why Phase 3 is still necessary

A correct guard implementation does not tell us what budget to deploy. The
candidate values are still experimental:

```text
120 s
300 s
600 s
```

The old historical comparator is:

```text
first positive wait <= 10 s
all later positive waits in the same turn = 0 s
```

Phase 3 rejects obviously bad candidates using replay before live ChatGPT trials.
Phase 4 then measures real model behavior.

## 4. Phase 3–6 high-level outcome

At the end of Phase 6 we want one of two honest outcomes.

### Success path

```text
Phase 3 chooses a live candidate shortlist
-> Phase 4 C satisfies all hard + confirmatory gates
-> Phase 5 staged development deployment is healthy for 24 h
-> Phase 6 24 h and 7 d reviews remain healthy
-> final integration/deployment decision is approved
```

### Stop/rollback path

Any hard correctness/safety failure, serious reliability regression, or staged
operational divergence stops progression. The server guard and Project
instructions have independent rollback switches and neither rollback stops
existing durable background jobs.

## 5. Parallel execution model — maximum four ChatGPT sessions

The owner can normally run at least four ChatGPT sessions concurrently. This
plan treats **four concurrent sessions as the design maximum**. Parallelism is
used only where it does not corrupt evidence or create shared-state races.

### 5.1 Session slots

Use these stable logical roles:

| Slot | Role | Typical ownership |
| --- | --- | --- |
| **A** | integration / coordinator | progress files, branch integration, final reports, gates |
| **B** | replay / data | trace corpus, replay candidates, wait-policy arithmetic |
| **C** | benchmark / harness | manifests, arm support, timeout provenance, analyzers |
| **D** | environment / validation | isolated endpoints, connector/project preflight, independent review |

A slot may be idle during a wave. Do not invent work merely to keep four chats
busy.

### 5.2 What may run in parallel

Good parallel work:

- code in disjoint worker worktrees with fixed file ownership;
- trace-corpus extraction versus replay-engine implementation after the schema is
  frozen;
- independent candidate replay for 120/300/600/H because each writes a distinct
  output artifact;
- missing-scenario manifest work versus timeout-provenance work;
- static analysis, evidence verification, and result review while a long live
  trial is running;
- Phase-5/6 telemetry analyses split by reliability, blocking-wall behavior,
  efficiency, and correctness/user-experience proxy.

### 5.3 What must remain serial

Never parallelize these shared mutations:

- merging/cherry-picking worker branches into the phase integration branch;
- editing the canonical phase progress JSON/Markdown from more than one session;
- changing instructions in one shared ChatGPT Project;
- changing a shared tunnel profile or connector endpoint;
- changing a benchmark server's budget while a trial is active;
- changing production config/systemd/service state;
- final candidate selection;
- Phase-4 final go/no-go;
- Phase-5 deployment/rollback actions;
- final merge into `proof-of-concept`/`master`.

### 5.4 Live timing trials are special

Do **not** assume that four simultaneous ChatGPT sessions can automatically be
used as four simultaneous benchmark arms. Local server/tunnel/CPU contention can
bias end-to-end timing.

Phase 4 therefore contains an explicit concurrency-qualification step:

- targeted budget calibration may run four isolated sessions in parallel because
  its primary purpose is completion/exhaustion classification, not fine-grained
  wall-time comparison;
- full A/B/C confirmatory timing may use simultaneous matched blocks **only if**
  the qualification proves that separate endpoints do not introduce meaningful
  dispatch/server contention;
- otherwise the full performance run remains serial/randomized while the other
  sessions analyze frozen results in parallel.

Evidence quality wins over maximum concurrency.

## 6. Branch and worktree model for parallel workers

No two concurrent agents edit the same worktree.

### 6.1 Canonical integration branches

Phase 3:

```text
branch:   feature/chat-mode-scheduling-v2-phase3
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3
```

Phase 4:

```text
branch:   feature/chat-mode-scheduling-v2-phase4
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4
```

Staging/release line used by Phases 5–6:

```text
branch:   release/chat-mode-scheduling-v2-staging
worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-staging
```

### 6.2 Phase-3 worker branches/worktrees

Create only when the corresponding parallel wave begins:

```text
feature/chat-mode-scheduling-v2-phase3-corpus
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-corpus

feature/chat-mode-scheduling-v2-phase3-replay
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-replay

feature/chat-mode-scheduling-v2-phase3-scenarios
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-scenarios

feature/chat-mode-scheduling-v2-phase3-provenance
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-provenance
```

Each worker starts from the exact Phase-3 integration HEAD frozen in Step 3.2.
Workers do not pull/merge each other. The coordinator integrates them after the
wave finishes.

### 6.3 Phase-4 worker branches/worktrees

```text
feature/chat-mode-scheduling-v2-phase4-harness
feature/chat-mode-scheduling-v2-phase4-environment
feature/chat-mode-scheduling-v2-phase4-analysis
```

Use analogous `~/Projects/binnacle-chat-scheduling-phase4-*` worktrees.
The main Phase-4 integration worktree owns live-run scheduling and canonical
progress.

### 6.4 Worker integration rule

A worker ends with:

```text
focused tests green
pre-commit green for its branch
one coherent commit
push worker branch
report commit hash to coordinator
```

The coordinator:

```text
cherry-pick worker commit(s) in documented order
resolve no conflicts silently: any unexpected conflict means the file-ownership
plan was violated or the source moved; investigate before continuing
run integration tests
update canonical progress
commit integration checkpoint
push integration branch
wait for CI green
```

Do not merge worker branches directly into `design/chat-mode-scheduling-v2`.

## 7. Canonical progress and evidence files

Each phase owns exactly one progress pair:

```text
benchmarks/chat-mode-scheduling-v2/phase3-progress.json
benchmarks/chat-mode-scheduling-v2/phase3-progress.md

benchmarks/chat-mode-scheduling-v2/phase4-progress.json
benchmarks/chat-mode-scheduling-v2/phase4-progress.md

benchmarks/chat-mode-scheduling-v2/phase5-progress.json
benchmarks/chat-mode-scheduling-v2/phase5-progress.md

benchmarks/chat-mode-scheduling-v2/phase6-progress.json
benchmarks/chat-mode-scheduling-v2/phase6-progress.md
```

JSON is the machine-readable source of truth. Step states are:

```text
not_started
running
complete
blocked
```

Phase states are:

```text
not_started
in_progress
waiting_wall_clock
blocked
complete
rolled_back
```

Every progress JSON records:

```text
schema_version
phase
status
source_head
integration_branch
integration_worktree
last_completed_step
next_step
steps
parallel_wave (when active)
worker_commits (when used)
external_prerequisites
production_observation_baseline
```

Only Slot A/coordinator writes canonical progress files.

## 8. Common cold-start SOP for a new transaction

A new transaction must not infer state from conversation memory.

1. Read this document.
2. Read the relevant phase progress JSON/Markdown if they exist.
3. Inspect the canonical integration worktree and `git log -15`.
4. Inspect all worker worktrees belonging to an active parallel wave.
5. Read the latest test-efficiency progress file.
6. Verify production branch/HEAD/status/service/config observationally; do not
   clean unrelated work.
7. If progress and Git disagree, reconcile before implementation.
8. Continue exactly the recorded `next_step` or worker assignment.
9. Do not repeat a complete canonical live trial.
10. Do not start a later phase before the previous phase exit gate is complete.

## 9. Global long-command SOP

For a command expected to exceed about 10 seconds:

```text
run background=true
retain job_id
use blocking job_status(wait_seconds=50)
continue legitimate dependency waits inside the same assistant turn
perform independent work meanwhile when possible
do not report completion while the background job is still unresolved
```

A Binnacle background job being alive is not a ChatGPT stop point.

## 10. Submitted-trial evidence rule — unchanged

All Phase-4 live trials follow the frozen rule:

> the first **submitted** outcome fills the scheduled slot.

Pre-submit infrastructure failures with no timing evidence that Enter occurred
may retry the same slot. Once submission evidence exists, timeout, interruption,
no-MCP work, wrong answer, or success all belong to that slot. No retry can
replace a submitted failure in the primary sample.

Extra reruns are diagnostic only.

## 11. Production isolation rule

Phases 3 and 4 do not modify the primary production connector/config/service.
Phase 5 makes only explicitly staged changes. Phase 6 performs final integration
only after the staged gates pass.

The production checkout may contain unrelated work from other sessions. Preserve
it. Never use `git reset --hard`, `git clean`, force checkout, or delete
unrelated files merely to create a clean status.

Capture an observational production baseline at each phase start:

```text
branch
HEAD
git status --porcelain=v1 --untracked-files=normal
binnacle-mcp.service ActiveState/SubState
config hash
unit hash
whether blocking_wall_budget_s_by_client is present
current Project instructions where relevant
```

Only scheduling-related drift is a blocker.

## 12. Mandatory precondition — finish test-suite efficiency work first

This is a hard gate before Phase 3 Step 3.1 can complete.

At planning time the independent test-efficiency program is still in progress on
`design/chat-mode-scheduling-v2`. Its progress file currently shows Phase 1
complete, Step 2.2 complete, and later steps pending. This plan must not freeze
that intermediate runner as the Phase-3 baseline.

### Required gate

Before Phase 3 starts:

1. `docs/test-suite-performance-optimization-progress-2026-09-24.md` must show
   its final Step 3.7 as PASS, or a newer replacement progress file must state an
   equivalent final completion;
2. the final optimization commit must be on
   `origin/design/chat-mode-scheduling-v2`;
3. its final GitHub CI must be green;
4. its fast full-suite/coverage commands become the test commands inherited by
   Phases 3–6;
5. no Phase-3 agent reimplements or competes with that runner.

If the test-efficiency project stops early by owner decision, record the exact
accepted final checkpoint and use its documented runner. Do not silently assume
the old `uv run pytest -q` workflow remains authoritative.

### Integration with this planning branch

This planning branch was created from design commit `2e6fb5d`, while the other
session may continue advancing design. When the test-efficiency work finishes, do **not** merge this planning branch
history wholesale into the moving design branch. This branch is expected to
contain one planning commit. Start from the final green
`origin/design/chat-mode-scheduling-v2` HEAD, create the Phase-3 integration
branch there, then cherry-pick the planning-document commit. If the cherry-pick
conflicts, resolve only the documentation conflict and preserve every completed
test-efficiency commit. Never reset either history.

---

## Phase 3 — offline policy replay

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

Freeze all canonical Phase-1 submitted trials referenced by Step-1.3 through
Step-1.8 JSON reports. Do not select only successful trials.

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

Step 3.2 freezes schema version 1:

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
3. It creates any systematic early exhaustion on a scenario class whose observed
   required blocking union is clearly below the candidate budget.
4. Historical repeated-wait burden reduction is **<70%** where the replay corpus
   can validly measure the historical repeated-wait upper-bound burden target.
5. Replay arithmetic or source coverage is incomplete enough that the candidate
   cannot be evaluated honestly.

Passing Phase 3 means **eligible for live testing**, not approved for deployment.
The live calibration shortlist is exactly **all candidates that pass every
Section-17 reject gate**. The preferred live candidate is the smallest passing
budget. Do not drop another passing candidate because it looks less attractive;
Phase 4 targeted calibration exists to resolve that uncertainty. If no candidate
passes, Phase 3 ends `NO_LIVE_CANDIDATE` and Phase 4 must not start.

## 18. Phase-3 steps

### Step 3.1 — synchronize the final test-efficiency baseline

Target: 10–20 minutes.

Serial; Slot A only.

Tasks:

1. Verify Section 12 test-efficiency completion gate.
2. Fetch origin and record the final `design/chat-mode-scheduling-v2` HEAD.
3. Bring this planning document onto that final design history without dropping
   either history.
4. Create `feature/chat-mode-scheduling-v2-phase3` and its canonical worktree.
5. Record production observation baseline.
6. Run the newly authoritative fast full-suite smoke defined by the completed
   test-efficiency project.
7. Create `phase3-progress.json/.md` with all Phase-3 steps initialized.

Exit:

```text
final test-efficiency baseline inherited
Phase-3 branch/worktree clean
authoritative test runner recorded
production untouched
```

Do not implement replay yet.

### Step 3.2 — freeze replay schema and source inventory

Target: 15–20 minutes.

Serial; Slot A.

Tasks:

- freeze the schema in Sections 14–16;
- enumerate canonical Phase-1 source reports and state dirs;
- enumerate available operational journal window;
- record source SHA-256 where files are immutable;
- define compact corpus field names;
- write empty/header `phase3-replay-corpus.json` contract fixture;
- create worker branches/worktrees from this exact integration HEAD.

Exit: worker lanes have a stable shared schema and do not need to redesign it.

### Wave 3A — four parallel implementation lanes

All four start from Step-3.2 HEAD.

#### Step 3.3A — corpus extractor — Slot A/B worker

Target: 15–20 minutes.

Own only:

```text
scripts/chat_scheduling_replay_corpus.py
tests/scripts/test_chat_scheduling_replay_corpus.py
phase3 corpus artifacts
```

Tasks:

- read canonical trial reports/state evidence;
- extract actual positive wait intervals and terminal/completion facts;
- normalize operational journal turns;
- redact prose/irrelevant arguments;
- deterministic sort and source hashing;
- fail loudly when a referenced canonical submitted trial is missing rather than
  silently shrinking the sample.

#### Step 3.3B — replay engine — Slot B

Target: 15–20 minutes.

Own only:

```text
scripts/chat_scheduling_replay.py
tests/scripts/test_chat_scheduling_replay.py
```

Implement baseline/C120/C300/C600/H10 semantics from Section 14 with a pure,
deterministic API. Synthetic tests cover serial waits, overlap, partial overlap,
early exhausted budget, observed exit inside/outside candidate interval, and H10.

#### Step 3.3C — missing Phase-4 scenarios — Slot C

Target: 15–20 minutes.

Own:

```text
benchmarks/chat-mode-scheduling-v2/scenarios/R4.json
benchmarks/chat-mode-scheduling-v2/scenarios/R6.json
benchmarks/chat-mode-scheduling-v2/scenarios/R10.json
benchmarks/chat-mode-scheduling-v2/scenarios/R12.json
manifest/schema tests needed for these scenarios
```

Frozen scenario intent:

```text
R4   ~90 s background validation + useful diagnosis reads
R6   ~90 s true dependency barrier, no independent work
R10  long quiet background job, sparse/no output
R12  required dependency deliberately exceeds active candidate budget
```

R12 is budget-parameterized. Do not hard-code a 300-second runtime. Resolve it as
candidate budget plus a documented safety margin. Initial margin: **30 seconds**.
For H10, use 10 + 30 = 40 seconds. For C120/C300/C600, use 150/330/630 seconds.
R12 is never included in aggregate performance medians.

The Phase-1 <=240-second manifest bound must become phase-aware rather than being
silently deleted. Phase-1 scenarios retain their old bound; Phase-4 R12 may use
the resolved larger runtime.

#### Step 3.3D — timeout provenance classifier — Slot D

Target: 15–20 minutes.

Own:

```text
scripts/chat_scheduling_provenance.py
tests/scripts/test_chat_scheduling_provenance.py
minimal harness/evidence changes required to persist classification inputs
```

Every submitted failure must be classifiable as one of:

```text
pre_mcp_submission_failure       # infrastructure before useful MCP work
active_turn_browser_timeout      # submitted; assistant/browser stream timed out
mcp_completed_browser_timeout    # required MCP/DAG completed before browser settling timeout
budget_exhaustion                # explicit guard exhaustion handoff
other_submitted_error            # submitted but none of the above
```

Classification is diagnostic only. It never changes canonical inclusion.

### Step 3.4 — integrate Wave 3A

Target: 15–20 minutes.

Serial; Slot A.

Cherry-pick worker commits in this order:

```text
corpus extractor
replay engine
scenario manifests
timeout provenance
```

Run focused integration tests plus manifest validation. Resolve no unexpected
cross-worker conflict silently.

### Step 3.5 — build and validate the frozen replay corpus

Target: 10–20 minutes.

Serial corpus generation, but Slots C/D may independently audit counts and hashes
in parallel after generation.

Required checks:

- canonical submitted trial count agrees with Phase-1 reports;
- no submitted failure was dropped because it lacks a successful conversation;
- all positive waits use actual observed wait duration;
- overlapping intervals reproduce the existing union metric on sampled traces;
- operational window and any expiration limitation are explicit;
- corpus generation is deterministic byte-for-byte when source evidence is
  unchanged.

### Wave 3B — candidate replay, four sessions in parallel

Each lane reads the same frozen corpus and writes only its own candidate files.
No source code edits during this wave.

#### Step 3.6A — C120 replay

Writes:

```text
phase3-replay-c120.json
phase3-replay-c120.md
```

#### Step 3.6B — C300 replay

Writes `phase3-replay-c300.*`.

#### Step 3.6C — C600 replay

Writes `phase3-replay-c600.*`.

#### Step 3.6D — H10 replay

Writes `phase3-replay-h10.*`.

Each candidate report includes corpus hash, candidate algorithm id, preservation,
exhaustion, union-wall burden, calls clipped/nonblocking, and per-scenario table.

### Step 3.7 — aggregate candidate replay and shortlist

Target: 15–20 minutes.

Serial; Slot A.

Write:

```text
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD.md
```

Apply Section-17 reject gates mechanically. Output:

```text
rejected_candidates
live_candidates
preferred_live_candidate
uncertainties
Phase-4 targeted calibration requirements
```

Do not declare a production budget.

### Step 3.8 — Phase-4 readiness dry run

Target: 15–20 minutes.

Validate without live ChatGPT trials:

- R1–R12 manifests load;
- R12 resolves correctly for every surviving budget plus H10;
- provenance classifier works on frozen Phase-1 timeout examples;
- replay artifacts are independently parseable;
- harness can represent C/H arm metadata even if endpoint switching is not yet
  enabled;
- Project instructions A/B hashes are recorded.

### Step 3.9 — full Phase-3 validation

Target: 10–20 minutes plus test runtime.

Run the authoritative optimized suite inherited from Section 12, full
pre-commit, CI, replay determinism check, and production isolation check.

### Step 3.10 — Phase-3 checkpoint

Write/update final progress and report. Phase 3 is COMPLETE only when:

```text
replay corpus frozen
120/300/600/H10 all evaluated
bad candidates explicitly rejected
live shortlist recorded
R4/R6/R10/R12 manifests ready
timeout provenance ready
all tests + CI green
production unchanged
```

Do not start Phase 4 automatically. Integration into
`design/chat-mode-scheduling-v2` requires the owner's explicit merge instruction,
consistent with the Phase-2 workflow.

---

## Phase 4 — full live confirmatory benchmark

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

## Phase 5 — staged deployment

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

## Phase 6 — post-deployment review and final integration

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

## 33. Parallel wave summary

| Wave | Maximum concurrent sessions | Parallel work |
| --- | ---: | --- |
| Phase 3 Wave A | 4 | corpus / replay engine / missing scenarios / provenance |
| Phase 3 Wave B | 4 | C120 / C300 / C600 / H10 replay |
| Phase 4 Wave A | 4 | endpoint / harness / analyzer / independent setup audit |
| Phase 4 Wave B | 4 | targeted live budget candidates + H |
| Phase 4 live confirmatory | 3 only if qualified | A/B/C matched blocks; otherwise serial |
| Phase 4 Wave C | 4 | correctness / performance / reliability / efficiency reviews |
| Phase 5 Wave A | 4 | first-project 24 h operational review |
| Phase 6 Wave A | 4 | Stage-2 24 h review |
| Phase 6 Wave B | 4 | Stage-2 7 d review |

## 34. Parallel worker handoff format

Every parallel worker reports exactly:

```text
phase / step / lane
source integration HEAD
worker branch
worker commit(s)
owned files changed
tests run + results
artifacts written
known limitations
production touched? (must normally be no)
merge/cherry-pick order constraints
```

The coordinator must not accept a worker result without a commit hash and clean
worker worktree.

## 35. Phase stop points

### Phase 3 stop

```text
Phase 3 COMPLETE
live candidate shortlist frozen
Phase 4 NOT STARTED
```

### Phase 4 stop

```text
Phase 4 COMPLETE
GO_PHASE5 or explicit NO_GO reason frozen
no staged deployment started unless owner explicitly continues
```

### Phase 5 stop

```text
Phase 5 COMPLETE
normal development Project is on qualified staging path
Phase 6 T0 recorded
primary master/connector still not silently changed
```

### Phase 6 stop

```text
Phase 6 COMPLETE
7-day staging verdict frozen
primary integration performed only if explicitly approved
primary-cutover 24-hour confirmation healthy
all rollback/cleanup/evidence state documented
```

## 36. Current checkpoint at plan creation

At the time this Phase 3–6 plan was written:

```text
Phase 0: COMPLETE
Phase 1: COMPLETE
Phase 2: COMPLETE (including 2.12a closeout)
Phase 3: NOT STARTED
Phase 4: NOT STARTED
Phase 5: NOT STARTED
Phase 6: NOT STARTED

planning branch:
  planning/chat-mode-scheduling-v2-phase3-6

planning source snapshot:
  2e6fb5d

test-efficiency program:
  IN PROGRESS on design/chat-mode-scheduling-v2
  Phase-3 execution must wait for its final completion

next scheduling-v2 execution step after that dependency finishes:
  Phase 3 Step 3.1
```

Writing, reviewing, committing, or merging this planning document does **not**
count as starting Phase 3.

## 37. Cold-start execution audit

This plan has been reviewed from the perspective of an agent with **no
conversation memory**. Before declaring the plan ready, the following decisions
are intentionally fixed here so a future agent does not spend a separate round
re-discovering them:

- the test-efficiency completion dependency and how to bring this planning commit
  onto the later final design HEAD;
- Phase-3/4 integration branch/worktree names;
- up to four parallel session roles and worker worktree ownership;
- canonical progress JSON/Markdown names and status vocabulary;
- replay corpus classes and privacy-minimized schema purpose;
- exact C120/C300/C600/H10 replay semantics;
- candidate reject gates and shortlist rule;
- replay CLI shape;
- missing R4/R6/R10/R12 ownership and R12 budget+30-second runtime rule;
- timeout provenance categories;
- Phase-4 A/B/C/H arm definitions;
- the rule that all live arms use the same proof-of-concept-based frozen source
  commit;
- fixed A/B/C/H ports, isolated config/job/socket/token roots, and manager/server
  process architecture;
- benchmark Project names and the existing `rp-test-sandbox` source Project ID;
- the external boundary for creating new connector/Project registrations;
- live trial counts, candidate calibration counts, slot-reuse rule, and 51/53
  confirmatory same-prompt threshold;
- quantitative parallel-live qualification thresholds;
- fixed confirmatory hard/performance/scheduling/guard/efficiency gates;
- Phase-5 persistent staging port/config/socket/job paths;
- exact Stage-1 `Binnacle` and Stage-2 `Raspberry Pi 5` Project IDs;
- independent model-policy and server-guard rollback switches;
- Phase-5 24-hour gate thresholds;
- Phase-6 T+24h/T+7d windows, operational proxy definitions, and hard rollback
  conditions;
- final primary connector consumer-inventory requirement;
- proof-of-concept-first final integration order;
- final 24-hour primary cutover confirmation before cleanup.

Normal implementation still requires reading target source files, writing code,
running tests, and debugging failures. That is execution, not permission to
re-open these frozen experiment decisions. If a real implementation fact makes a
frozen decision impossible, record the contradiction in the active phase
progress files and stop at that design blocker instead of silently inventing a
new experiment.
