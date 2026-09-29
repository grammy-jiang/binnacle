# Long-running ChatGPT orchestration: execution plan

Status: **COMPLETE — deployed to production at `17cc21c` on 2026-09-29; CI and production UX smoke passed.**

Date: 2026-09-29 (Australia/Sydney)
Repository: `/home/grammy-jiang/Projects/binnacle`

## 1. Objective

Make long-running local work reliable even when one ChatGPT foreground turn cannot remain alive for the whole local job.

The target is not "make one ChatGPT turn wait forever". The target is:

> A local job may run for tens of minutes or hours; ChatGPT may wait when that is useful, but interruption of a foreground turn must not lose the job, its progress, or the ability of a later turn to reattach and continue correctly.

The design should deliberately learn from OpenAI Responses API background execution semantics and current MCP multi-round/task mechanisms rather than inventing a novel lifecycle without evidence.

## 2. Evidence already established

These facts are the baseline for the programme. Do not re-litigate them unless new evidence contradicts them.

1. `binnacle-jobs.service` already gives durable local process ownership independent of an individual ChatGPT turn.
2. A local job surviving for a long time does **not** prove that one ChatGPT turn waited for it.
3. The frozen Round-1 classifier found same-turn completions at >=5/10/20/30/40/50 minutes of **24/10/3/2/0/0** across 734 background jobs; the strongest Round-1 example was 33.34 minutes.
4. Round 4 then produced stronger live evidence: T45 completed in the same ChatGPT turn after 45.0 minutes, while T60's foreground turn stopped mid-message after 40.3 minutes and the durable job continued to completion.
5. Therefore there is no useful wall-clock expiry contract for a ChatGPT foreground turn. The production design does not depend on one: later turns or new chats resume durable work by `job_id` and, internally, a job-bound cursor.
6. Some turns stop while their jobs are still running; some such jobs are later observed by another turn. This is a real recovery scenario, not a hypothetical one.
7. Network/tunnel interruption is an independent failure mode. On 2026-09-29 around 08:21–08:23 the active uplink lost gateway/DNS/TCP reachability and the watchdog failed over and restarted `binnacle-tunnel.service`.
8. `job_status` historically returned excessive repeated output. The deployed implementation now hard-caps legacy output at 24,000 characters and adds optional cursor mode for complete bounded deltas. In Round 5, normal long jobs returned about 6.1–26.7× fewer bytes with cursor polling than equivalent repeated legacy tails.

## 2.1 Final production outcome

The programme completed all five rounds and shipped `17cc21c` to `master`, `origin/master`, and `origin/proof-of-concept`. GitHub CI passed code quality, coverage policy, and Python 3.10–3.14. The isolated Round-4 endurance/fault gate passed all 16 scenario rows, including tunnel restart, MCP-server restart, natural/constructed foreground-turn loss, same-chat resume, new-chat resume by `job_id`, and new-chat resume by a carried cursor.

The user-facing policy also changed: once a command yields a durable running `job_id`, ChatGPT normally reports the job ID/current progress and returns control rather than holding the turn open with repeated waits, unless the user explicitly asks it to wait for completion. A production smoke using a harmless two-minute job verified this behavior: the first turn returned after about 22 seconds with job `a98130cba698` still running; a later `Status` turn recovered the same job and reported its successful 120-second completion. The smoke chat was backed up and deleted by exact ID.

`round2/e4-contract-v1.md`, `round4/report.md`, and `round5/decision.md` are the authoritative detailed records for the shipped contract, endurance/fault evidence, and release decision.

## 3. Architectural principle

Use a short-lived control plane over a durable execution plane:

```text
User
  |
  v
ChatGPT foreground turn(s)
  |
  | start / inspect / wait / resume
  v
Binnacle durable job/workflow state
  |
  v
local process (Codex / Claude / tests / arbitrary shell)
```

A later ChatGPT turn must be able to reconstruct enough state to continue without depending on hidden state from the earlier turn.

## 4. Execution model for this programme

The local **Claude Code** process is the coordinator. It must not use normal Claude Code sub-agents for Round 1 lane work.

Round 1 workers are exactly four independent **ChatGPT conversations** created and continued through the local `chatgpt-web-operations` skill:

- Lane A — reliability evidence;
- Lane B — `job_status` immediate safety and delta contract;
- Lane C — OpenAI Responses API reference design;
- Lane D — real ChatGPT MCP capability probes.

One ChatGPT conversation owns one lane for the whole round. The coordinator sends one bounded step at a time to the same conversation.

### 4.1 Why one persistent chat per lane

Each lane has serial reasoning dependencies. Reusing the lane chat preserves its local reasoning/context while still keeping every individual foreground turn short. Parallelism exists **between** the four lane chats, not by asking one chat to execute all lanes.

### 4.2 Timing rule

No planned ChatGPT step may require more than 20 minutes.

Planning target per step: **8–15 minutes**.

Coordinator send command: use `chatgpt-send ... --timeout 600`. The sender itself allows up to another 300 seconds to settle, making the coordinator-side worst-case wait about 15 minutes. That leaves a five-minute safety margin before the 20-minute design boundary.

If a step does not finish inside this envelope, it is an **oversized step**. Do not simply increase the timeout. See section 9.

## 5. Round 1 — four parallel lanes

All four lanes start from one frozen base SHA. Each receives its own worktree to avoid accidental cross-lane writes, even when the lane is primarily investigative.

| Lane | Purpose | Planned steps | Estimated lane wall time | Writes code? | Merge intent |
| --- | --- | ---: | ---: | --- | --- |
| A | Explain successful vs interrupted long turns from real evidence | A0–A3 | 40–55 min | no product code | report only |
| B | Remove known `job_status` output hazard and specify delta/cursor contract | B0–B4 | 50–65 min | hard-cap fix only | hard-cap commit may be merged after review |
| C | Extract reusable long-running semantics from current OpenAI Responses API | C0–C3 | 40–55 min | no | report only |
| D | Verify what the current ChatGPT MCP host actually supports | D0–D5 | 60–80 min | isolated POC only | POC normally discarded |

Because the lanes run concurrently, expected Round-1 elapsed wall time is roughly the slowest lane plus coordinator overhead: **about 70–90 minutes**, not the sum of all four lane estimates. This is an engineering estimate, not a platform guarantee.

Detailed step plans are in:

- `lane-a-reliability.md`
- `lane-b-job-output.md`
- `lane-c-responses-api.md`
- `lane-d-mcp-capabilities.md`

## 6. Round 1 dependency graph

```text
                    +--> Lane A: evidence ------------------+
                    |                                       |
Frozen base --------+--> Lane B: output safety -------------+--> R1 synthesis gate
                    |                                       |
                    +--> Lane C: Responses API -------------+
                    |                                       |
                    +--> Lane D: MCP capabilities ----------+
```

There is no dependency between A, B, C and D after base freeze.

Inside each lane, steps are serial unless that lane document explicitly says otherwise.

## 7. Round 1 worktree/branch plan

The coordinator creates these only after the owner says to start:

```text
~/Projects/binnacle-longrun-a-evidence
  branch: investigation/longrun-a-evidence

~/Projects/binnacle-longrun-b-job-output
  branch: feature/longrun-b-job-output

~/Projects/binnacle-longrun-c-responses
  branch: investigation/longrun-c-responses

~/Projects/binnacle-longrun-d-mcp-capabilities
  branch: experiment/longrun-d-mcp-capabilities
```

Rules:

- the prepared `docs/long-running-chatgpt/` plan set must be committed into the common base before worktrees are created; if still uncommitted at approved kickoff, the coordinator makes a docs-only preparation commit containing exactly this plan directory and no unrelated owner changes;
- freeze `BASE_SHA=$(git rev-parse master)` after that preparation commit and before creating any worktree;
- all four worktrees are created from exactly `BASE_SHA`;
- lane workers must not touch another lane's worktree;
- A/C are documentation/evidence branches only;
- B may implement only the hard output-safety change explicitly authorised by its plan; it must not independently redesign the public long-running API;
- D may build isolated POC code/config, but must not deploy it to production and must not merge it by default;
- production `master`, `proof-of-concept`, `binnacle-mcp.service`, `binnacle-jobs.service`, and the primary ChatGPT connector are not mutated by Round-1 experiments except where a lane plan explicitly describes a reversible, isolated live probe and its cleanup.

## 8. ChatGPT worker protocol

### 8.1 Bootstrap

For each lane, create one new conversation with `chatgpt-send --new --json`. The bootstrap prompt contains only:

1. role and lane name;
2. exact worktree path;
3. exact lane-plan path;
4. instruction to use the Raspberry Pi MCP connector;
5. instruction to read this master plan and the lane plan;
6. instruction to execute **only the first listed step**;
7. the 20-minute/one-step rule;
8. the structured completion format.

The coordinator records the URL immediately with `--url-file` and tracks it with `clean_chats.py`.

### 8.2 Continuation

After validating one step, continue the same worker chat:

```text
chatgpt-send --chat <lane-url> --timeout 600 --json \
  "Continue with Step <ID> only. Re-read the lane checkpoint and obey its exit criteria."
```

Do not create a fresh ChatGPT chat for every step unless the current chat is irrecoverably broken. A replacement chat must be told to recover from lane artifacts, not from memory.

### 8.3 Parallel scheduling

The coordinator must use an event-loop style schedule:

- launch the first step of all four lanes concurrently;
- as soon as one lane finishes and validates, launch that lane's next step without waiting for the other three;
- never serialize A→B→C→D merely for convenience;
- never launch two serial steps of the same lane concurrently;
- later phases may fan out again only where their dependency graph permits it.

### 8.4 Worker completion contract

Every ChatGPT step must end with a compact machine-readable checkpoint in its reply:

```text
STEP: <A0/B1/...>
STATUS: PASS | BLOCKED | FAIL | OVERSIZED
ARTIFACTS: <paths or none>
COMMIT: <sha or none>
FINDINGS: <1-5 short points>
NEXT: <next planned step or stop reason>
```

The authoritative evidence remains the repository/worktree and logs, not the prose reply.

## 9. Oversized-step recovery

A step that cannot finish inside the intended 8–15 minute envelope is not allowed to silently turn into a 30–50 minute foreground ChatGPT run.

Coordinator procedure:

1. `chatgpt-send --timeout 600` returns or stops waiting.
2. If the send did not return a clean final reply, inspect the exact chat with the skill's `read_chat.py`.
3. If the reply is already complete, collect and validate it normally.
4. If it is still generating, continue other lanes; do not block the coordinator globally.
5. Re-check during the remaining five-minute safety margin.
6. If the turn still has not completed by the 20-minute boundary, mark the step `OVERSIZED` and stop advancing that lane.
7. Do **not** solve this by raising the timeout.
8. After the current turn eventually becomes inspectable, split the unfinished logical work into at least two smaller steps, update the lane checkpoint, and resume only with the smaller next step.
9. Never send a second substantive instruction into a chat while its previous assistant turn is still active.

This programme is itself testing the premise that smaller, checkpointed turns are more robust.

## 10. Round 1 synthesis gate (R1)

Do not start final API design until all four lanes are either PASS or have a documented, accepted limitation.

Required inputs:

### From A

- classified successful and interrupted same-turn cases;
- evidence on duration versus failure;
- evidence on output/context volume;
- evidence on network/tunnel overlap;
- clear list of what the logs can and cannot prove.

### From B

- tested hard output cap for `job_status`;
- before/after contract and compatibility evidence;
- cursor/delta proposal, but no assumption that it is the final API.

### From C

- sourced Responses API lifecycle map;
- background start/retrieve/cancel/resume/stream semantics;
- concepts safe to imitate;
- concepts coupled to the hosted Responses API and therefore unsuitable to copy literally.

### From D

- observed ChatGPT MCP protocol/capability matrix;
- live result for `input_required`/elicitation if safely testable;
- live result for MCP Tasks if safely testable;
- reconnect/session behaviour evidence where feasible;
- explicit distinction between "MCP spec supports" and "current ChatGPT host supports".

## 11. Round 2 — contract design

Round 2 is serial at the decision level but may use short specialist reviews in parallel after the first contract draft.

### E0 — Synthesis (10–15 min)

One coordinator-owned synthesis pass consumes only the four frozen Round-1 reports and commits. Produce a decision table of confirmed facts, rejected assumptions, and unresolved risks.

### E1 — Lifecycle contract draft (10–15 min)

Define the smallest public model needed for long-running work. Candidate concepts to evaluate, not pre-approve:

```text
job_id
status: queued | in_progress | completed | failed | cancelled
created_at / started_at / completed_at
cursor / sequence
incremental output/events
terminal result
cancel
resume/retrieve
needs_input / input_required if supported
```

Keep existing tool compatibility in view. A new abstraction must justify itself against `run_command`, `job_status`, and `stop_job`.

### E2 — Compatibility review (10–15 min)

Check the draft against current tools, durable job store, job manager, existing automation, ChatGPT usage patterns, and migration/rollback.

### E3 — Adversarial review (10–15 min)

Use a fresh ChatGPT reviewer chat to attack the contract: interruption, duplicate polling, cursor loss, huge output, tunnel restart, job-manager restart, cancellation races, old clients, and unsupported MCP extensions.

### E4 — Freeze v1 design (10–15 min)

Resolve review findings and freeze the implementation contract. No implementation starts until this gate passes.

Estimated Round-2 wall time: **45–70 minutes**, depending on review findings.

## 12. Round 3 — implementation

Only after E4. Split by file/contract ownership so implementation can fan out again.

Possible lanes, to be frozen by E4 rather than assumed now:

- I-A: incremental output/cursor storage and read path;
- I-B: public tool/API lifecycle and compatibility adapter;
- I-C: telemetry, recovery evidence, stats and diagnostics;
- I-D: tests/docs/harness changes that can proceed after interfaces freeze.

Each implementation step must again be scoped to <=20 minutes for a ChatGPT worker. Independent implementation branches are integrated only after their focused tests pass.

## 13. Round 4 — endurance and fault tests

The critical test is not merely "job survives". Each scenario must record whether ChatGPT can observe completion and continue, or a later turn can correctly reattach.

Test matrix should include at least:

```text
10 min normal job
20 min normal job
30 min normal job
45 min normal job
60+ min normal job
high-output job
quiet job
non-zero exit
cancel during run
tunnel restart while job runs
MCP service restart while job runs
ChatGPT foreground turn ends while job runs
new ChatGPT turn reattaches and continues
```

Do not run every duration serially if fixtures can be safely started together. Long fixture jobs should overlap to keep wall time reasonable, while observations remain attributable by unique job/turn IDs.

The acceptance criterion is not "all one-turn waits succeed". It is:

> No supported interruption loses durable state, and the documented reattachment path reliably reconstructs the next action without requiring hidden context from the interrupted turn.

## 14. Round 5 — production decision

Before merge/deploy:

- compare old and new tool-call count and model-step burden;
- compare repeated output/token volume;
- verify no regression to fast `run_command`;
- confirm rollback path;
- ensure experimental connectors/worktrees/chats are cleaned up;
- document GO / NO-GO with evidence.

## 15. Estimated overall wall time

These are planning estimates for active execution after the owner says start:

| Round | Estimate with planned parallelism |
| --- | ---: |
| Round 1 — four lanes | 70–90 min |
| Round 2 — synthesis/design | 45–70 min |
| Round 3 — implementation | 60–120 min depending on frozen scope |
| Round 4 — endurance/fault tests | 60–100 min with overlapping fixtures |
| Round 5 — final review/deploy decision | 20–40 min |

A realistic full programme is therefore several hours of active work, but **no individual ChatGPT worker step is intentionally longer than 20 minutes**.

## 16. Stop conditions

The coordinator stops rather than improvising when:

- the base repository is unexpectedly dirty in a way it cannot attribute;
- production services would need destructive changes not described by the plan;
- a capability probe would require exposing credentials or weakening auth;
- a lane contradicts a frozen invariant and cannot resolve it from evidence;
- ChatGPT browser/session access is unavailable across all workers;
- more than one lane produces an architectural blocker that invalidates the Round-1 decomposition.

A blocked lane does not stop unrelated lanes. The coordinator records the blocker and lets independent work finish.

## 17. Current execution state

As of this document's creation:

```text
Preparation: complete/in progress
Round 1: NOT STARTED
ChatGPT lane chats: NOT CREATED
Claude Code coordinator: NOT STARTED
Worktrees: NOT CREATED
Product code changes for this programme: NONE
```

The next action requires explicit owner approval to start the coordinator.

### Prepared launch command — DO NOT RUN UNTIL APPROVED

From `/home/grammy-jiang/Projects/binnacle`, the prepared unattended local-coordinator launch is:

```bash
claude --background --dangerously-skip-permissions --effort high \
  --name binnacle-longrun-coordinator \
  "$(cat docs/long-running-chatgpt/coordinator-prompt.md)"
```

This command has **not** been executed as part of planning. When it is intentionally run later, Claude Code becomes the coordinator and creates the four ChatGPT worker chats according to the plan.
