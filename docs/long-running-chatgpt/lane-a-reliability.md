# Lane A — long-turn reliability evidence

Status: **Round 1 plan; do not execute before coordinator start approval.**

Worktree: `~/Projects/binnacle-longrun-a-evidence`
Branch: `investigation/longrun-a-evidence`
Primary worker: one persistent ChatGPT conversation using the Raspberry Pi MCP connector.
Product-code changes: forbidden.

## Mission

Turn the recent anecdotal evidence about long-running ChatGPT turns into a reproducible failure/success taxonomy. The key distinction is:

> a local job running for a long time is not evidence that ChatGPT waited for it; success requires the same ChatGPT turn to observe completion and then continue meaningful work.

Lane A must determine what correlates with successful same-turn completion, what correlates with abandonment/interruption, and what remains unknowable from available logs.

## Inputs

Read before Step A0:

- `docs/long-running-chatgpt/README.md`
- `docs/usage-analysis-2026-09-27.md`
- `docs/chat-mode-scheduling-v2-retrospective-2026-09-27.md`
- production journals for `binnacle-mcp.service`, `binnacle-tunnel.service`, `binnacle-watchdog.service`, and where useful `binnacle-jobs.service`;
- existing analysis scripts under `scripts/` before writing one-off parsers.

Do not mutate production services or configuration.

## Output artifact

Primary report:

`docs/long-running-chatgpt/lane-a-report.md`

The report must include exact query windows, reproducible commands/scripts used, counts, limitations, and the evidence table requested below.

## Step A0 — Freeze population and definitions

Target: 8–12 minutes.

Tasks:

1. Freeze the analysis start at the 2026-09-27 wait-description deployment unless evidence requires a narrower clean-build boundary.
2. Define these outcomes precisely:
   - `same_turn_completed_and_resumed`;
   - `same_turn_completed_no_followup`;
   - `same_turn_stopped_while_running`;
   - `later_turn_reattached`;
   - `job_terminal_without_chat_observation`;
   - `unknown/unclassifiable`.
3. Define "resumed" as at least one subsequent real tool call in the same turn after observing the target job's terminal state. Do not count only the terminal `job_status` itself.
4. Reproduce the already-known 32.56-minute positive case and record its exact turn/job IDs.
5. Create the report skeleton and record the frozen definitions.

Exit criteria:

- report exists;
- population start/end and classification definitions are explicit;
- the 32.56-minute case is independently reproduced from raw logs.

Do not continue into broad correlation analysis in this step.

## Step A1 — Classify the population

Target: 10–15 minutes.

Tasks:

1. Classify all attributable ChatGPT-started background/wait-expired jobs in the frozen window where enough evidence exists.
2. Produce counts by runtime thresholds: >=5, >=10, >=20, >=30, >=40, >=50 minutes.
3. For same-turn successful cases, record:
   - job runtime;
   - spawn-to-terminal-observation wall time;
   - number and distribution of `job_status` waits;
   - first real tool call after terminal observation.
4. For `same_turn_stopped_while_running`, determine whether a later turn observed the same job and whether it completed.
5. Keep raw command text private/local when it may contain user/project data; the committed report should use IDs, aggregate command family, and safe summaries.

Exit criteria:

- every class has a count;
- runtime-threshold table is produced;
- successful and interrupted examples are traceable to job/turn IDs.

## Step A2 — Correlate candidate failure drivers

Target: 10–15 minutes.

This is correlation, not causation. Compare successful versus interrupted cases against:

- total turn duration;
- number of model/tool steps visible in the journal;
- `job_status` call count;
- total and maximum estimated result tokens where available;
- `job_status` output size and truncation;
- job quiet/output cadence;
- tunnel restart/failover overlap;
- MCP service reload/restart overlap;
- non-zero/failed local jobs versus successful local jobs;
- multiple concurrent local jobs in the same turn where identifiable.

Required conclusions must distinguish:

```text
supported by direct evidence
correlated only
not supported
not measurable with current telemetry
```

Exit criteria:

- at least one comparison table of success versus interruption;
- no claim of a hard platform timeout unless direct evidence supports it;
- explicit list of missing telemetry that would materially improve diagnosis.

## Step A3 — Recommendations and instrumentation gaps

Target: 8–12 minutes.

Tasks:

1. Rank only evidence-supported reliability risks; do not rank speculative causes as facts.
2. State whether current evidence justifies any wall-clock threshold policy. Expected baseline: no assumed hard threshold.
3. Identify the smallest telemetry additions needed to distinguish future foreground-turn expiry, tunnel failure, context pressure, and voluntary model handoff.
4. State which findings should influence the Round-2 API contract.
5. Finish and self-review `lane-a-report.md` for cold-start readability.

Exit criteria:

- report is self-contained;
- all strong claims have reproducible local evidence;
- recommendations feed directly into R1 synthesis.

## Lane A completion reply

Return:

```text
STEP: A3
STATUS: PASS | BLOCKED | FAIL
ARTIFACTS: docs/long-running-chatgpt/lane-a-report.md
COMMIT: <sha or none>
FINDINGS: <top findings>
NEXT: R1 synthesis gate
```

Commit the report on the lane branch when complete. Do not merge it.
