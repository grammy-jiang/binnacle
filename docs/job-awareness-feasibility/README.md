# Job Awareness feasibility: parallel verification programme

**R1 execution outcome (10 October 2026):** the local W1–W4 experiments have completed and the independent evidence has been verified; actual ChatGPT Chat W5 was not run. Read the [R1 final investigation results](R1-INVESTIGATION-RESULTS.md) for measured findings, negative conclusions, original evidence hashes and the R2 handoff. The remaining plan/checklist text below is the originally frozen R1 *pre-execution* contract; retain it for historical reproducibility. Do not read its PLAN ONLY labels as current worker statuses.

Status: **PLAN ONLY — not started**. Prepared 2026-10-10 (Australia/Sydney).
Source baseline for this document branch: GitHub master at d61761356ee0fce8ea6d73b0c3043b4881c5645e (merged PR #18 and PR #19).
Actual worker kickoff must revalidate and freeze a current exact source SHA; these documents do not claim any Job Awareness implementation or test has run.

## Purpose and narrow scope

The goal is to test, before implementation, whether Binnacle can make ChatGPT aware of its own running and completed durable jobs in later ordinary MCP responses, without breaking FastMCP contracts or leaking jobs between chats. The desired model behavior is to continue independent work, notice completion at a dependency barrier, retrieve the result, and continue the original requested workflow without another user message **while the ChatGPT turn remains active**.

An already terminated ChatGPT turn cannot be revived by an MCP response that will never occur. Wakeup/orchestration is a separate, explicitly out-of-scope capability. Do not claim an automatic resume after a terminated turn.

This work is **feasibility testing, not feature development**. Temporary synthetic FastMCP servers, mock jobs, fixtures and disposable proof-of-concept code are allowed in isolated worker environments solely for measurement. Production code, configuration, connector, job spool, service units, deployed app, credentials and real user job results are out of scope. Do not merge or deploy experiment code.

The discussion distilled six hypotheses:

| Hypothesis | Evidence needed | Owner |
| --- | --- | --- |
| H1: native FastMCP result augmentation is safe | On-wire result and error/contract comparison | W1 Codex CLI |
| H2: ChatGPT actually receives and uses reminders | Real Chat mode trace, not model prose | W5 ChatGPT Desktop |
| H3: chat/job identity is trustworthy and isolated | Source-level and three-chat adversarial tests | W2 Claude Code + W5 |
| H4: successful retrieval can acknowledge a result without deleting it | State machine, pagination and failure replay | W3 Codex CLI |
| H5: incremental reminder overhead is acceptable | Benchmarks, byte/token costs, old-client parity | W4 Claude Code |
| H6: behavior benefits the user's original workflow | Randomized control versus candidate trials | W5 ChatGPT Desktop |

A **Drop** in discussion means a retrievable job/result artifact. No new Binnacle tool or protocol object named Drop is assumed; W3 must verify the actual existing interfaces before defining acknowledgement tests.

## Operating model

The user assigns programmatic, non-ChatGPT-interactive experiments to Claude Code or Codex CLI; real ChatGPT-client experiments belong to the installed ChatGPT Desktop application. These assignments are **five concurrently running evidence lanes**, not five writers to one repository. W1, W2, W3 and W4 use independent CLI processes and exclusive working directories. W5 is the only owner of Desktop GUI input, all temporary ChatGPT test chats, and their evidence.

W5 combines both live visibility/behavior experiments and live multi-chat isolation tests. There is **one Desktop operator**, not one competing Desktop process per test chat. GUI actions are serialized because the physical UI is a shared resource; the ChatGPT chats/jobs themselves can overlap. This is the maximum safe parallelism without an independently verified multi-display / per-profile control surface.

One short S0 preparatory gate freezes common fixtures, source provenance and an isolated, authenticated disposable test MCP app (or returns a specific blocked capability). After S0, all five lanes start without waiting for one another. In particular, W5 exercises a frozen three-carrier matrix independently of W1's findings: it does not wait for W1 to choose a carrier. See [parallel execution](PARALLEL-EXECUTION.md).

Model and effort choices are explicit and lane-specific, never inherited from CLI defaults. S0 uses Codex gpt-6-sol/medium; W1 uses Codex gpt-6-astra/high; W2 uses Claude opus/high; W3 uses Codex gpt-6-astra/xhigh; W4 uses Claude sonnet/medium. W5 pins its ChatGPT Chat test subject to GPT-6/Medium, subject to actual UI availability and explicit verification. See [model and effort](MODEL-AND-EFFORT.md) and the mandatory [handoff receipt protocol](HANDOFF-MODEL-AND-EFFORT.md).

The **ChatGPT manager/supervisor** assigns the workers, checks evidence existence and independent provenance, and gives the user a synthesized report. The manager does **not** implement, edit worker code, execute worker experiments, merge prototype changes or invent missing measurements. Workers own their individual results and return machine-readable evidence. See [worker briefs](WORKER-BRIEFS.md), [desktop SOP](DESKTOP-OPERATOR.md), [evidence gates](EVIDENCE-AND-GATES.md), and [manager report template](MANAGER-SUMMARY-TEMPLATE.md).

## Verified host entry points at planning time

- Claude Code executable: /home/grammy-jiang/.local/bin/claude; version 2.1.293.
- Codex CLI executable: /home/grammy-jiang/.local/bin/codex; version 0.162.1.
- ChatGPT desktop launcher: /usr/bin/chatgpt; resolves to /usr/lib/chatgpt/codex-launcher. /usr/share/applications/chatgpt.desktop has Exec=chatgpt %U.
- Host display at inspection: Wayland (wayland-0; DISPLAY=:1).
- No supported GUI automation/control protocol for this launcher or proof that it is the traditional ChatGPT **Chat mode** was verified at planning time.
- Primary Binnacle worktree was behind origin/master and carried unrelated untracked documents. This document is prepared in a separate branch/worktree; do not reset, checkout or clean the primary worktree.

The installed launcher is **not** itself evidence that it can automate a real ChatGPT Chat conversation. W5 must first confirm the actual ChatGPT surface, an approved supported means of interacting with it, and access to the isolated test MCP app. A Codex Desktop agent conversation is not a substitute for a ChatGPT Chat mode result. If the UI cannot supply that surface, mark live scenarios BLOCKED and continue all four CLI lanes.

## Decisions and non-decisions

The programme has four possible evidence outcomes for each hypothesis: PASS, FAIL, INCONCLUSIVE and BLOCKED. Negative and blocked evidence are real outputs, not reasons to manufacture a successful experiment.

The final synthesis must explicitly distinguish PASS, FAIL, INCONCLUSIVE, BLOCKED and NOT_RUN scenario evidence. Its recommendation can be:

- **GO TO IMPLEMENTATION PLAN:** model-visible compatible carrier and action proven, identity isolated, receipt semantics safe, with acceptable bounded overhead.
- **CONDITIONAL GO:** a narrower result is feasible but important conditions remain. Define additional tests, not an automatic production rollout.
- **NO-GO:** a required assumption is falsified, such as unsupported model-visible delivery, unreliable identity or unsafe implicit acknowledgement.
- **INCONCLUSIVE:** one or more critical experiments remain blocked or lack enough evidence for a supported decision.

The supervisor never equates server-emitted metadata with model visibility, a successful tool invocation with delivery to the client, a clean unit-test suite with real ChatGPT behavior, or Codex/Work behavior with traditional Chat mode.

## Document index

1. [PARALLEL-EXECUTION.md](PARALLEL-EXECUTION.md) — freeze, independent workers, shared-resource discipline, startup/finish barriers.
2. [WORKER-BRIEFS.md](WORKER-BRIEFS.md) — exact W1–W5 assignments, tests, and returned evidence.
3. [DESKTOP-OPERATOR.md](DESKTOP-OPERATOR.md) — live ChatGPT canary, multi-chat isolation, receipt and behavior trials.
4. [EVIDENCE-AND-GATES.md](EVIDENCE-AND-GATES.md) — mandatory evidence structure, thresholds, negative cases and grading.
5. [MODEL-AND-EFFORT.md](MODEL-AND-EFFORT.md) — explicit task-model and reasoning effort assignments and CLI flags.
6. [MANAGER-SUMMARY-TEMPLATE.md](MANAGER-SUMMARY-TEMPLATE.md) — read-only supervisory consolidation.
7. [FIXTURE-CONTRACT.md](FIXTURE-CONTRACT.md) — immutable synthetic input and carrier contracts.
8. [prompts/](prompts/) — standalone S0 and W1–W5 dispatch prompts.
9. [STEP-IO-MATRIX.md](STEP-IO-MATRIX.md) — input/output of every S0, W1–W5 scenario and M0–M4.
10. [I-O-FORMATS.md](I-O-FORMATS.md) — exact JSON/JSONL/CSV/Markdown file contracts.
11. [HANDOFF-MODEL-AND-EFFORT.md](HANDOFF-MODEL-AND-EFFORT.md) — startup model/effort proof and no-default handoff policy.
12. [step-io.json](step-io.json) and [worker-manifest.json](worker-manifest.json) — machine-readable steps, worker assignments and dependency contracts.
13. [schemas/](schemas/) — JSON Schemas for structured input/output.
14. [validate_contracts.py](../../tests/job_awareness_feasibility/validate_contracts.py) and [contract suite](../../tests/job_awareness_feasibility/contract_suite.py) — offline structural verifier with positive/negative tests.
15. [PRELAUNCH-REVIEW.md](PRELAUNCH-REVIEW.md) — final gaps, corrections, evidence and exact launch checklist.

No experiment tests, app installations, connections, browser interactions, production-code edits, deployment or service restart were executed in preparing these documents.
