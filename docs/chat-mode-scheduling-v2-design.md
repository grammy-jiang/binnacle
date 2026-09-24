# Chat mode scheduling v2 — design

Status: Phase 1 complete; conditional GO to Phase 2; no production change.

Evidence source: `docs/chat-mode-scheduling-final-2026-09-23.md`, copied from
the completed `analysis/chat-async-probe` investigation at commit `352d906`.

Execution SOP: `docs/chat-mode-scheduling-v2-phase2-execution-plan.md`.

Phase 3–6 execution SOP: `docs/chat-mode-scheduling-v2-phase3-6-execution-plan.md`.

## Executive decision

The v2 proposal has two production changes and one evidence programme:

- replace the legacy Project workflow rules with dependency-aware scheduling
  that submits all known independent reads, backgrounds long commands early,
  and keeps working in the same prompt;
- replace the old one-shot 10-second polling guard with a cumulative
  per-turn blocking-wall ceiling whose final value is selected by A/B;
- merge/deploy only after the benchmark proves faster wall time, >=95%
  same-prompt completion for bounded tasks, zero premature handoff, and no
  correctness/safety regression.

No new MCP tool is proposed.

## 1. Problem

The current ChatGPT workflow guidance and the first `job_status` polling fix
were written before the Chat-mode scheduler was measured.

The completed investigation changes the design assumptions:

- one user prompt can sustain many MCP rounds;
- independent read-only calls use an approximately five-wide sliding in-flight
  window in the current ChatGPT connector path;
- the width is upstream of local Binnacle/FastMCP;
- already-known independent work can refill free slots while a slow read-only
  call remains unresolved;
- result-dependent continuation across a still-running slow call was not
  observed;
- non-read-only tools serialize, and `idempotentHint=true` does not change that;
- `run_command(background=true) -> job_id` is the useful Future/Promise
  primitive for same-prompt long work;
- MCP Tasks were not negotiated;
- the historical latency problem was repeated blocking `job_status` waits, not
  one legitimate dependency wait.

Two existing workflow rules now conflict with the measured product behavior:

1. "for a job_id, call job_status once with wait_seconds=50" is too coarse; and
2. "past ~10 tool calls, stop ... and wait for continue" directly conflicts
   with the user goal of finishing a long development workflow in one prompt.

The earlier polling prototype also over-corrects. Its "first blocking wait is
capped at 10 s; every later positive wait in the same turn becomes zero" rule
bounds latency, but can force a premature handoff even when the only remaining
work is a legitimate 30–300 second dependency barrier.

This design replaces both ideas with a scheduling policy plus a catastrophe
ceiling.

## 2. Goals

The design has three equally important goals.

### 2.1 Performance

Reduce end-to-end wall time by overlapping work that is already known to be
independent, and by preventing avoidable blocking on background jobs.

### 2.2 Same-prompt completion

Prefer finishing the whole development task inside the original user prompt.
A tool-call count is not a reason to stop. A long dependency barrier is allowed
to wait when there is nothing more useful to do.

### 2.3 User experience

Reduce or eliminate manual continuation prompts such as "keep working" and
"are you still working?", while preserving correctness, write confirmations,
and clear final reporting.

## 3. Non-goals

This design does not:

- add a generic workflow engine;
- add MCP Tasks before ChatGPT negotiates them;
- add a bulk `read_files` tool;
- mislabel mutating tools as read-only;
- make non-read-only calls artificially parallel;
- change durable job ownership;
- change `run_command` background warm-up in the first implementation;
- introduce multi-host execution;
- claim that the currently observed five-wide connector window is a permanent
  API contract.

## 4. Design principles

1. **Model policy and server safety are separate.** Project instructions decide
   what work is useful now. The server only enforces a last-resort blocking
   ceiling.
2. **Exploit independence, not guessed parallelism.** Submit every currently
   known independent read-only call; do not manually batch to a fixed width.
3. **Use job IDs as Futures.** Long non-read-only work should return a durable
   handle quickly and continue in the background.
4. **Wait only at a dependency barrier.** Positive `job_status` waits are
   legitimate when no useful independent work remains.
5. **Bound pathological waiting, not legitimate work.** The server caps
   cumulative blocking wall time for the agent turn rather than allowing only
   one positive wait.
6. **Keep the tool surface simple.** The measured scheduler already handles the
   common read fan-out shape well.
7. **Measure before rollout.** No production policy is selected from one fast
   probe or a counterfactual simulation.
8. **Production control surface is never an experiment target.** Schema or
   annotation experiments require a separate Lab connector or an equivalent
   test using already-existing production tools.

## 5. Proposed architecture

There are two product layers and one measurement layer.

```text
ChatGPT Project instructions
        |
        |  choose runnable independent work
        |  launch long jobs early
        |  decide when a dependency barrier is real
        v
Binnacle MCP tools
        |
        |  durable background job_id
        |  read-only tools
        |  job_status(wait_seconds)
        v
Per-turn blocking-wall guard
        |
        |  catastrophe ceiling only
        |  no workflow knowledge
        v
Durable job owner / filesystem state
```

The benchmark harness sits beside this path and observes it; it is not part of
the production scheduler.

## 6. Layer A — ChatGPT scheduling policy

The production Project instruction should replace the old polling and
"~10 calls then stop" rules. The versioned candidate text is
`.claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt`.

### 6.1 Proposed canonical instruction

```text
Working rules for the Raspberry Pi MCP connector

1. Plan dependencies first. Keep working in the same user prompt until the task
   is complete, external user input is required, an unrecoverable error occurs,
   or the server's blocking-wait budget is exhausted. Never stop only because a
   tool-call count reached a fixed number.

2. When several read-only tool calls are independent and all arguments are
   already known, submit all of them without waiting for other independent
   results. Do not manually split them into fixed-size batches; the client
   controls the actual in-flight width. Do not repeat completed calls.

3. Read a file once, whole, when it fits. After search/list discovers several
   independent files, read those files concurrently. Use server-side context
   and result limits instead of repeated narrow calls when possible.

4. Keep non-read-only calls separate from the read-only lane. Batch related
   shell work inside one run_command when that preserves the dependency order.
   Start known-long commands early with background=true so they return a job_id
   and continue while other work proceeds.

5. Treat job_id as a Future/Promise handle. While productive independent work
   remains, do not block on job_status; use wait_seconds=0 only when a status
   observation is actually needed. At a true dependency barrier, a positive
   wait is allowed. If the job is still running and there is still no
   independent work, continue the dependency wait within the server budget.
   Do not issue repeated wait_seconds=0 checks with no new reason.

6. Run git status, tests, pre-commit and other validation at dependency-appropriate
   points rather than after every edit. Use tail_lines for long output.

7. Report once at the end. If the server wait budget is exhausted before a
   required job finishes, return a concise checkpoint: the job_id, current
   state, completed work, and exact remaining dependency.
```

The text intentionally does not hard-code "five calls" because the observed
width is product behavior, not a durable contract.

### 6.2 What this policy changes

It removes three anti-patterns:

```text
serial independent reads
read -> reason -> read -> reason -> read

blocking too early
background job -> job_status(wait=50) while useful reads still exist

artificial turn cutoff
tool call #10 -> stop -> ask user to say continue
```

and replaces them with:

```text
known independent reads -> submit together
long command -> background job_id -> useful work -> dependency barrier
dependency barrier -> deliberate wait -> continue same prompt
```

## 7. Layer B/C — server guard and telemetry summary

The server change is deliberately narrower than the model policy. It does not
know the task DAG and does not decide whether work is useful. It only bounds
pathological repeated positive `job_status` waiting.

The proposed mechanism is a per-client, per-agent-turn
**union-of-blocking-wall-time** budget. Overlapping waits charge wall time once;
a wait that finishes early charges only actual time; productive gaps between
wait windows are free. The existing 50-second per-call input bound remains.

The first budget candidate is 300 seconds, but 120/300/600 seconds are compared
in A/B and trace replay before a production value is selected.

Budget exhaustion must be visible to the model through structured
`job_status` output and its one-line summary so the Project instruction can
produce an intentional checkpoint instead of instant-polling forever.

Detailed accounting algorithm, concurrency rules, telemetry schema and tests:
`docs/chat-mode-scheduling-v2-server-guard.md`.

## 8. No new tool in v2

The investigation does not justify:

- `read_files([...])`;
- a generic task/workflow tool;
- a second status tool;
- an async callback tool.

The measured real workload had high-confidence discovery-follow-up clusters:

```text
p50 = 3 files
p90 = 5 files
max = 6 files
```

That already fits the current connector scheduler well. The simpler existing
tools preserve composability and keep the schema surface small.

## 9. No run_command warm-up change in v2

Process-launch telemetry showed that the underlying manager launch is already
very fast, while reducing the current one-second background warm-up would save
far less wall time than fixing read scheduling and repeated blocking waits.

Keep the current warm-up for this design so the A/B has one fewer moving part.

## 10. Benchmark and A/B summary

The design is accepted only after controlled comparison.

Main variants:

- **A:** exact active Project instructions snapshotted at benchmark start,
  current server, no turn wall guard;
- **B:** proposed scheduling instructions only;
- **C:** proposed instructions plus cumulative blocking-wall guard;
- **H:** old 10-second one-shot guard, targeted negative/control arm only.

The benchmark contains scheduler microprobes plus real development journeys.
Primary outcomes are end-to-end wall time, same-prompt completion, avoidable
idle wall time, manual continuation prompts, correctness and token/tool-call
cost.

Headline acceptance targets for C include:

- 100% deterministic correctness and no safety regression;
- >=95% same-prompt completion when cumulative required waiting fits the
  selected budget;
- median and p90 manual continuation prompts = 0;
- >=20% overall median wall-time improvement vs A;
- >=30% on read-heavy scenarios;
- >=80% eligible read-only overlap;
- no premature handoff before budget exhaustion;
- no material request/stream-interruption regression.

Full scenario definitions, statistical method, budget selection and gates:
`docs/chat-mode-scheduling-v2-ab-plan.md`.

## 11. Implementation phases

### Phase 0 — baseline freeze

- copy the final investigation evidence into this design branch;
- freeze current Project instructions as A;
- define benchmark manifests and analyzers;
- verify production remains unchanged.

### Phase 1 — instruction-only A/B

Implement no server policy.

Run A vs B to prove that the revised scheduling instructions improve real
read/mixed workloads and reduce continuation prompts.

If B does not improve the macro suite, stop. A server guard cannot fix poor
model scheduling.

Phase-1 outcome (2026-09-23): **conditional GO to Phase 2, no-go for
merge/deploy**. Across 24 canonical macro pairs B showed an 8.1% lower direct
median wall time, an 8.3% paired-median improvement, zero premature handoffs
and stronger read/long-barrier scheduling mechanics. However B same-prompt
completion was only 75%, the interruption rate was 25%, the >=20% overall and
>=30% read-heavy performance targets were not met, and the paired bootstrap
95% interval included regression. Phase 2 may therefore proceed only as a
non-production experiment; all original Phase-4 production gates remain in
force. See
`benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.md`.

### Phase 2 — blocking-wall guard

Implement:

- `current_turn`;
- per-client wall-budget config;
- union-of-active-waits tracker;
- requested/effective/actual telemetry;
- logstats aggregation;
- unit/integration/concurrency tests.

Do not deploy yet.

### Phase 3 — offline policy replay

Replay historical traces for 120/300/600 s candidates and the old 10-second
one-shot comparator.

Reject obviously bad budgets before spending live ChatGPT trials.

### Phase 4 — full live A/B

Run A/B/C and targeted H.

Select the wall budget using the acceptance gates.

### Phase 5 — staged deployment

1. deploy server guard with v2 Project instructions to the Binnacle development
   Project only;
2. observe 24 hours;
3. compare live telemetry against the benchmark;
4. extend to the normal Raspberry Pi development Project only if healthy.

### Phase 6 — post-deployment review

At 24 hours and 7 days report:

- turns/tasks;
- same-prompt completion proxies;
- positive status waits;
- blocking-wall p50/p90/max;
- budget exhaustion;
- read-only concurrency;
- tool-result tokens;
- stream/request interruption count;
- user continuation prompts observed in benchmark or tagged development chats.

Rollback if the production data violates any hard gate or materially diverges
from the confirmatory A/B.

## 12. Rollback design

The server policy is deployment-local and disabled by removing the client
budget entry. Repository default is no guard.

Project instructions are versioned in the repo and can be restored independently
of the server.

Rollback therefore has two independent switches:

```text
model policy -> restore previous Project instructions
server guard -> remove openai-mcp blocking wall budget
```

Neither rollback affects durable jobs.

## 13. Design decisions intentionally deferred

The following require new evidence after v2:

- lowering `run_command` background warm-up below one second;
- exposing a separate explicit "wait for job" tool;
- changing the 50-second per-call status limit;
- persisting turn budgets across server restarts;
- adding bulk-read tools;
- using MCP Tasks when ChatGPT begins negotiating them;
- multi-host task distribution.

## 14. Expected outcome

The v2 design should make ChatGPT feel less like a sequence of synchronous
remote-shell calls and more like an agent that keeps useful work in flight:

```text
before:
  inspect one thing
  wait
  inspect another thing
  start test
  wait 50
  wait 50
  stop after call count
  user: keep working

after:
  discover independent work
  submit independent reads
  start long validation early
  continue useful diagnosis while it runs
  reach a real dependency barrier
  wait deliberately within a measured safety budget
  finish in the same prompt
```

The design is accepted only when the A/B demonstrates both lower wall time and
better same-prompt user experience without correctness or safety regression.
