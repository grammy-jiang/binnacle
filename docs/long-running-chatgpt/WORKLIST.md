# Long-running ChatGPT orchestration — coordinator worklist

Status: **PREPARED / NOT STARTED**

This file is the coordinator's progress ledger. Update it after every validated step. Do not mark a step complete from a worker's prose alone; verify its exit criteria and artifacts first.

## Preparation

- [x] P0 — master plan written
- [x] P1 — Lane A plan written
- [x] P2 — Lane B plan written
- [x] P3 — Lane C plan written
- [x] P4 — Lane D plan written
- [x] P5 — Claude Code coordinator prompt written
- [ ] P6 — owner explicitly approves execution

## Round 1 — four ChatGPT workers in parallel

Frozen base SHA: `NOT_YET_FROZEN`
Coordinator start: `NOT_STARTED`
Coordinator state dir: `~/.local/state/binnacle/long-running-chatgpt/`

### Lane A — reliability evidence

Chat URL: `NOT_CREATED`
Worktree: `~/Projects/binnacle-longrun-a-evidence`
Branch: `investigation/longrun-a-evidence`

- [ ] A0 — freeze population and definitions
- [ ] A1 — classify population
- [ ] A2 — correlate candidate failure drivers
- [ ] A3 — recommendations and instrumentation gaps
- [ ] A-GATE — `lane-a-report.md` validated and committed

### Lane B — job output safety

Chat URL: `NOT_CREATED`
Worktree: `~/Projects/binnacle-longrun-b-job-output`
Branch: `feature/longrun-b-job-output`

- [ ] B0 — reproduce and define hard-cap invariant
- [ ] B1 — implement hard cap
- [ ] B2 — compatibility/performance validation and focused commit
- [ ] B3 — cursor/delta contract proposal
- [ ] B4 — final report
- [ ] B-GATE — report and hard-cap commit validated; not merged

### Lane C — Responses API reference

Chat URL: `NOT_CREATED`
Worktree: `~/Projects/binnacle-longrun-c-responses`
Branch: `investigation/longrun-c-responses`

- [ ] C0 — current Responses lifecycle
- [ ] C1 — streaming/cursor/reconnect/cancel semantics
- [ ] C2 — map Responses concepts to Binnacle
- [ ] C3 — final recommendations
- [ ] C-GATE — `lane-c-report.md` validated and committed

### Lane D — MCP capabilities

Chat URL: `NOT_CREATED`
Worktree: `~/Projects/binnacle-longrun-d-mcp-capabilities`
Branch: `experiment/longrun-d-mcp-capabilities`

- [ ] D0 — static capability inventory
- [ ] D1 — isolated live-probe design
- [ ] D2 — `input_required` / elicitation live test
- [ ] D3 — MCP Tasks/deferred-work live test
- [ ] D4 — reconnect/new-turn observations
- [ ] D5 — cleanup and final report
- [ ] D-GATE — `lane-d-report.md` validated and experimental resources cleaned

## R1 synthesis gate

- [ ] R1.0 — all four lane gates complete or documented blocked limitation accepted
- [ ] R1.1 — collect exact branch SHAs and reports
- [ ] R1.2 — verify no production drift from D experiments
- [ ] R1.3 — verify temporary worker chats are tracked and preserved until evidence is committed
- [ ] R1.4 — coordinator writes one frozen Round-1 synthesis input set

## Round 2 — contract design

- [ ] E0 — synthesize confirmed facts / rejected assumptions / unresolved risks
- [ ] E1 — draft minimal lifecycle contract
- [ ] E2 — compatibility review
- [ ] E3 — fresh adversarial ChatGPT review
- [ ] E4 — freeze v1 implementation design

## Round 3 — implementation

Implementation lanes are deliberately `TBD` until E4 freezes ownership and interfaces.

- [ ] I0 — freeze implementation lane/file ownership
- [ ] I-A — incremental output/cursor implementation
- [ ] I-B — public lifecycle/API and compatibility implementation
- [ ] I-C — telemetry/recovery/statistics
- [ ] I-D — test/docs/harness work that is independent after interface freeze
- [ ] I-GATE — integration tests, contract tests, coverage/policy gates

## Round 4 — endurance/fault testing

- [ ] T10 — 10-minute normal job
- [ ] T20 — 20-minute normal job
- [ ] T30 — 30-minute normal job
- [ ] T45 — 45-minute normal job
- [ ] T60 — 60+ minute normal job
- [ ] THIGH — high-output job
- [ ] TQUIET — quiet job
- [ ] TFAIL — non-zero exit
- [ ] TCANCEL — cancel during run
- [ ] TTUNNEL — tunnel reconnect/failover path
- [ ] TMCP — MCP service restart while job runs
- [ ] TTURN — foreground ChatGPT turn ends while job runs
- [ ] TREATTACH — later turn reattaches and continues correctly
- [ ] T-GATE — evidence report proves durable state + documented continuation path

## Round 5 — production decision

- [ ] F0 — compare model/tool steps and repeated-output/token burden
- [ ] F1 — fast `run_command` regression check
- [ ] F2 — rollback rehearsal/verification
- [ ] F3 — cleanup temporary worktrees/connectors/chats after evidence backup
- [ ] F4 — GO / NO-GO decision document
- [ ] F5 — merge/deploy only if GO and owner policy permits

## Coordinator event log

Append concise entries here during execution; do not paste huge worker replies.

```text
NOT_STARTED
```
