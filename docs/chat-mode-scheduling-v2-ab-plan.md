# Chat mode scheduling v2 — benchmark and A/B plan

Status: Phase 1 complete with conditional GO to Phase 2; no production change.

Parent design: `docs/chat-mode-scheduling-v2-design.md`.
Evidence: `docs/chat-mode-scheduling-final-2026-09-23.md`.

The benchmark DAG metadata described here is test-only. It is not a production
workflow engine.

Executable metric definitions: `benchmarks/chat-mode-scheduling-v2/METRICS.md`.

Phase-1 aggregate decision (2026-09-23): continue to Phase 2 only as a
non-production experiment; do not merge/deploy. The complete evidence and gate
matrix are in
`benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.md`.
The acceptance thresholds below are unchanged.

Execution SOP: `docs/chat-mode-scheduling-v2-phase2-execution-plan.md`.

Phase 3–6 execution SOP: `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md`.

## 1. Benchmark architecture

The benchmark has two layers.

### 1.1 Microbenchmarks

Microbenchmarks prove mechanisms and catch scheduler regressions:

| ID | Scenario | Purpose |
| --- | --- | --- |
| M1 | 3 independent reads | basic model batching |
| M2 | 8 independent reads | sliding-window fan-out |
| M3 | 1 slow status + 5 fast reads | slot refill while slow read-only call runs |
| M4 | unpredictable token -> dependent search beside slow status | dependent-continuation barrier |
| M5 | 3 long `stop_job` calls on SIGTERM-ignoring dummies | non-read-only serialization |
| M6 | background long job + reads + later status | Future/job-id same-prompt flow |
| M7 | 8 local FastMCP waits | server-side concurrency control |

These are mechanism checks, not the main user-experience score.

### 1.2 Macrobenchmarks

Macrobenchmarks model real development work:

| ID | Scenario | Main stress |
| --- | --- | --- |
| R1 | search discovers 6 files, inspect all | common discovery fan-out |
| R2 | inspect 10 known independent files | wide read fan-out |
| R3 | 30 s background validation + 8 independent reads | overlap useful work |
| R4 | 90 s background validation + diagnosis reads | long overlap |
| R5 | 25 s job with no independent work | short true barrier |
| R6 | 90 s job with no independent work | medium true barrier |
| R7 | two sequential 60–90 s dependency jobs | repeated legitimate barriers |
| R8 | inspect -> edit throwaway worktree -> focused tests -> inspect result | development journey |
| R9 | failing focused test -> diagnose -> edit -> retest | recovery journey |
| R10 | long quiet job with sparse/no output | quiet-job behavior |
| R11 | multiple independent read/search waves separated by dependencies | multi-round planning |
| R12 | dependency deliberately longer than the candidate budget | budget-exhaustion fallback |

Mutation scenarios use disposable worktrees/fixtures. No benchmark edits the
production checkout.

### 1.3 Benchmark DAG metadata

Each macro scenario has test-only metadata describing:

```text
nodes
dependencies
read-only vs non-read-only
expected outputs
which nodes are runnable at each dependency state
```

This metadata exists only for analysis. It is **not** a proposed production
workflow engine.

The DAG lets the analyzer measure **avoidable idle time**: time spent in a
positive `job_status` wait while benchmark metadata says another independent
node was already runnable.

## 2. A/B variants

The main comparison is A vs C. B isolates how much value comes from instructions
alone. H is a targeted historical comparator, not a production candidate.

### A — current baseline

- current production server;
- exact active Project instructions snapshotted at benchmark start;
- no per-turn blocking-wall guard.

The repository's legacy reference snapshot is
`.claude/skills/chatgpt-mcp-dev/references/project-instructions-baseline-chat-scheduling-v2.txt`.

Phase 0 must compare that active snapshot with the repository's current
canonical rule file. If they differ, the active snapshot is A and the canonical
legacy file is retained as a historical comparator. The benchmark must never
silently assume that a repository reference file is what the live Project is
actually using.

### B — scheduling-policy only

- current production server;
- proposed v2 Project instructions from
  `.claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt`;
- no server wall-budget guard.

This isolates the benefit of model scheduling guidance.

### C — full proposal

- proposed v2 Project instructions;
- cumulative per-turn blocking-wall guard;
- initial candidate budget = 300 s;
- all other server behavior unchanged.

### H — historical 10-second one-shot guard

Only on targeted long-job scenarios:

- v2 Project instructions;
- first positive wait capped at 10 s;
- all later positive waits in the same turn forced to zero.

This is a regression/control arm to quantify the completion/UX cost of the
earlier polling fix. It is not a merge target.

## 3. Experimental method

For every comparable trial:

- same Git commit and fixture contents;
- same model and thinking effort;
- same ChatGPT Project except instruction variant;
- new chat or otherwise isolated context;
- unique nonce/probe id;
- same task wording apart from the nonce;
- same cache classification;
- same Pi host and service mode;
- no unrelated benchmark jobs running;
- record local system load and throttling state.

Run order is paired and randomized by scenario, for example:

```text
A C B
C A B
B A C
```

rather than running all A trials hours before all C trials.

Pilot:

```text
8 representative macro scenarios
3 repeats per arm
24 trials per arm
```

Confirmatory run:

```text
R1-R6 and R8-R11: 5 repeats per main arm A/B/C
R7:                3 repeats per main arm
R12:               1 controlled safety run per relevant budget/arm
```

R12 is excluded from aggregate performance medians because it is intentionally
a budget-exhaustion probe, not a normal workload. H only runs on R5/R6/R7/R12.

Microbenchmarks run before and after each benchmark session as a scheduler
sanity check.

### Submitted-trial inclusion rule

A scheduled A/B slot is bound to the **first submitted trial**, not the first
successful trial.

- If the harness fails before submission and there is no chat-timing evidence
  that Enter occurred, the same slot may be retried.
- Once timing evidence says the message was submitted, that outcome belongs to
  the slot even if the request later times out, produces no conversation, or
  never reaches MCP.
- A submitted failure must not be replaced by a later successful rerun.
- Extra reruns after all planned slots are already filled are diagnostic only
  and are excluded from the primary A/B sample.

This prevents retry/survivor bias from making an unstable arm look faster or
more reliable than the user would actually experience.

## 4. Metrics

### 4.1 Primary performance metrics

#### End-to-end wall time

From user message submission to final settled assistant reply.

Report per scenario and category:

- median;
- p90;
- paired ratio vs A;
- bootstrap 95% confidence interval for the paired median ratio.

#### Same-prompt completion rate

A trial passes when the task reaches its expected terminal state without a new
user message.

#### Avoidable idle wall time

Union of positive `job_status` wait intervals during which the benchmark DAG
had at least one independent runnable node.

This should approach zero under B/C.

### 4.2 Primary user-experience metrics

#### Manual continuation prompts per task

Count messages such as "continue", "keep working", or "are you still working"
that would be required to finish the benchmark.

The automated benchmark records a required continuation whenever the assistant
ends while the scenario still has runnable work and no external input is
required.

#### Premature handoff rate

Assistant ends before the task is complete even though:

- no user decision is required;
- no unrecoverable error occurred; and
- the server blocking budget was not exhausted.

#### Budget-exhaustion handoff rate

Tracked separately from premature handoff. This is an intentional safety
fallback.

### 4.3 Efficiency metrics

- total MCP tool calls;
- duplicate/redundant tool calls;
- `job_status` calls;
- actual blocking-wall union;
- read-only peak in-flight width;
- eligible read-only overlap ratio;
- background job launches;
- tool-result tokenizer tokens;
- total tool-result bytes;
- model-visible error count.

An eligible read-only call counts as overlapped when its execution interval
overlaps at least one benchmark-declared independent read-only peer. The
eligible overlap ratio is overlapped eligible calls divided by all eligible
calls; calls blocked by a declared dependency are excluded from the
denominator.

### 4.4 Correctness and safety metrics

- expected files/results produced;
- tests/validation outcome matches scenario oracle;
- no mutation outside disposable worktree/fixture;
- no missing write confirmation caused by annotation changes;
- no production connector schema mutation;
- no durable job lost across MCP reload/restart tests.

## 5. Acceptance targets

The full proposal C is eligible for staged deployment only if all hard gates and
the main performance gates pass.

### 5.1 Hard gates

1. **Correctness:** 100% of deterministic scenario oracles pass.
2. **Safety:** zero writes outside benchmark disposable roots.
3. **Tool contract:** no annotation lies and no new production tool is required.
4. **Production isolation:** benchmark never changes the active production
   connector allowlist/schema.
5. **No premature handoff:** 0% on scenarios whose required dependency work
   completes before the configured wall budget is exhausted.

### 5.2 Same-prompt / UX targets

For tasks whose cumulative required positive-wait wall time fits within the
300-second candidate budget:

- same-prompt completion rate **>= 95%**;
- median manual continuation prompts **= 0**;
- p90 manual continuation prompts **= 0**;
- at least **80% reduction** in required continuation prompts vs A on the
  continuation-prone subset;
- request/stream interruption rate no worse than A by more than **2 percentage
  points**.

For R12 (>candidate budget), a budget-exhaustion handoff is expected and must
contain the required checkpoint fields. R12 runtime is parameterized as the
candidate budget plus a safety margin rather than hard-coded to 300 seconds.

### 5.3 Performance targets

Across the confirmatory macro suite:

- overall median end-to-end wall time: **>= 20% faster than A**;
- read-heavy R1/R2/R11 median: **>= 30% faster than A**;
- mixed long-job R3/R4 median: **>= 20% faster than A**;
- no scenario category is more than **10% slower** at the median unless the
  slower result directly buys a higher same-prompt completion rate and is
  separately approved;
- for the confirmatory run, the bootstrap 95% confidence interval for the
  overall paired C/A wall-time ratio must exclude regression (upper bound
  **< 1.00**).

### 5.4 Scheduling targets

On benchmark-declared independent read-only nodes:

- avoidable blocking wall time p90 **<= 2 s**;
- eligible overlap ratio **>= 80%**;
- M2/M3 continue to demonstrate sliding refill rather than a manually imposed
  fixed-size logical batch.

### 5.5 Blocking-guard targets

- actual per-turn positive-wait wall union never exceeds configured budget by
  more than scheduler/timestamp rounding tolerance;
- overlapping waits are charged once;
- budget-exhausted calls become non-blocking;
- guard-decision p95 overhead **< 1 ms**, p99 **< 2 ms** on the Pi 5;
- at least **70% reduction** in the historical repeated-wait upper-bound burden
  under trace replay, while preserving same-prompt completion targets.

### 5.6 Token/call efficiency targets

- tool-result tokens do not increase by more than **5%** overall vs A;
- target **>= 10% reduction** in long-job scenarios through fewer redundant
  status calls;
- no increase in duplicate completed read calls.

## 6. Budget-selection experiment

Do not assume 300 s is optimal.

After B is stable, run C with candidate wall budgets:

```text
120 s
300 s
600 s
```

on R5/R6/R7/R12 plus historical trace replay.

Select the smallest budget that simultaneously satisfies:

- bounded-suite same-prompt completion >= 95%;
- premature handoff = 0;
- budget-exhaustion handoff <= 10% outside the explicit >budget scenario;
- repeated-wait wall burden is materially lower than A.

If 300 s misses completion but 600 s passes without materially increasing
timeout/stream failures, choose 600 s. If 120 s already passes, prefer 120 s.

The budget is therefore an A/B outcome, not a design constant.

## 7. Historical trace replay

Before live model A/B, replay the recorded `job_status` timing traces through
candidate guard algorithms.

Replay must use **actual observed wait durations / job exits**, not requested
wait alone.

For each historical turn report:

- baseline blocking-wall union;
- candidate effective waits;
- whether each job would have completed before budget exhaustion;
- number of waits converted to non-blocking;
- simulated budget-exhaustion point.

Trace replay is a filter, not final evidence: it cannot model how ChatGPT would
schedule different independent work under new instructions.
