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
| Design history | Phase-2 + final test-efficiency history preserved on latest design line |
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

## Step 3.0 — Dependency Audit / Entry Gate

**This is the mandatory first step of Phase 3. Do not create replay workers or
implement replay code before it passes.**

Phase 3 depends on two completed workstreams: scheduling Phase 2 and the separate
test-suite performance optimization program.

### Required upstream state

Audit all of the following from repository evidence, not conversation memory:

1. **Phase 2 completion**
   - `phase2-progress.json` says `status=complete`, `last_completed_step=2.12`,
     `next_step=null`;
   - its `post_completion_review` / 2.12a entry is `complete`;
   - the dated Phase-2 final report says Phase 2 complete, Phase 3 not started,
     production undeployed;
   - the Phase-2 guard implementation commit is an ancestor of the final design
     line used for Phase 3.
2. **Phase 2 quality evidence**
   - final Phase-2/2.12a CI is green;
   - full tests/pre-commit evidence in the final report is internally consistent;
   - repository default blocking budget remains empty.
3. **Test-efficiency program completion**
   - `docs/test-suite-performance-optimization-progress-2026-09-24.md` (or its
     documented successor) shows final Step 3.7 PASS, unless the owner explicitly
     accepted an earlier final checkpoint;
   - its final commit is present on `origin/design/chat-mode-scheduling-v2`;
   - its final CI is green;
   - record the final authoritative fast/full/coverage commands that Phases 3–6
     must inherit rather than reimplement.
4. **Planning handoff**
   - this Phase-3 plan commit is available;
   - Phase 3 starts from the **latest final green design HEAD**, then brings this
     planning document forward as specified in the plan;
   - no test-efficiency commit is dropped/reset.
5. **Production observation baseline**
   - capture production branch/HEAD/status, service ActiveState/SubState, config
     and unit hashes, and budget-key presence;
   - preserve unrelated work exactly.

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
final upstream design HEAD identified
authoritative optimized test commands recorded
production baseline recorded
next allowed step: 3.1
```

## Canonical Phase-3 handoff contract

Step 3.10 must write these exact dated final artifacts:

```text
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD.json
benchmarks/chat-mode-scheduling-v2/phase3-policy-replay-YYYY-MM-DD.md
```

`phase3-progress.json` must contain a `handoff` object with:

```text
final_report_json
final_report_md
final_report_sha256
phase3_source_head
replay_corpus_path + sha256
live_candidates[]
preferred_live_candidate
scenario_catalog_sha256
provenance_classifier_commit
phase4_ready = true | false
```

Phase 4.0 recomputes these hashes and rejects disagreement; it does not trust the
`handoff` object by itself.

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
