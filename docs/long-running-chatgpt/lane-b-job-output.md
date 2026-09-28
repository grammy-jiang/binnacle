# Lane B — `job_status` output safety and incremental-output contract

Status: **Round 1 plan; do not execute before coordinator start approval.**

Worktree: `~/Projects/binnacle-longrun-b-job-output`
Branch: `feature/longrun-b-job-output`
Primary worker: one persistent ChatGPT conversation using the Raspberry Pi MCP connector.

## Mission

Remove the already-demonstrated context-explosion hazard in `job_status` without prematurely redesigning the whole long-running API. Then produce a concrete cursor/delta proposal for Round 2.

Round-1 implementation authority is intentionally narrow:

> Lane B may implement and test a hard output-size cap for existing `job_status` results. It may design but must not independently ship the final cursor/delta public API.

## Inputs

Read:

- `docs/long-running-chatgpt/README.md`
- `src/binnacle/tools/job_status.py`
- `src/binnacle/job_output.py`
- `src/binnacle/config.py`
- tests that pin `job_status` schema/output behaviour;
- `docs/tools/run_command.md` and any `job_status` documentation;
- 2026-09-27/28 output telemetry showing the historical giant-result problem.

## Outputs

- implementation commit for the hard cap, if the compatibility review passes;
- `docs/long-running-chatgpt/lane-b-report.md`;
- no final public cursor API implementation in Round 1.

## Step B0 — Reproduce and define the safety invariant

Target: 8–12 minutes.

Tasks:

1. Confirm current `job_status` tail shaping is line-count based and can exceed a character budget when individual lines are huge.
2. Identify the existing generic output-shaping helper used by `run_command` and whether it can be reused safely.
3. Reproduce a bounded synthetic giant-line case locally without needing historical private output.
4. Freeze the invariant:

   > A single `job_status` call must have a deterministic hard returned-log budget independent of line length, while the full job log remains on disk.

5. Identify all public schema/compatibility effects before editing.

Exit criteria:

- failing/regression test design is explicit;
- selected helper/config strategy is justified;
- no source change yet unless needed only to create the failing test.

## Step B1 — Implement the hard cap

Target: 10–15 minutes.

Tasks:

1. Implement the smallest change that applies a hard character budget to `log_tail` after/beside `tail_lines` selection.
2. Reuse existing output-shaping semantics where practical rather than creating a second clipping vocabulary.
3. Preserve:
   - full disk log;
   - current state/exit/process fields;
   - existing `tail_lines` meaning as a preference within the hard ceiling;
   - backward-compatible tool name and inputs.
4. Add telemetry sufficient to identify clipping reason/omitted size if existing shared telemetry does not already provide it.
5. Do not add cursor parameters in this step.

Exit criteria:

- focused unit/contract tests pass;
- giant-line regression is bounded;
- ordinary small `job_status` outputs are unchanged apart from any explicitly documented clipping metadata.

## Step B2 — Compatibility and performance validation

Target: 8–12 minutes.

Tasks:

1. Run focused tests for `job_status`, output shaping, schemas, telemetry, and config.
2. Run `scripts/mcp_client.py` or the repository-prescribed fast loop if tool surface is unchanged.
3. Measure synthetic small/large log latency before/after enough to rule out an obvious regression.
4. Confirm the change does not read or copy more of the spool than necessary; if full-log reading is itself identified as a material problem, record it but do not silently widen scope.
5. Commit the hard-cap change as one focused commit if clean.

Exit criteria:

- focused validation passes;
- commit exists or report explains why implementation was rejected.

## Step B3 — Cursor/delta contract proposal

Target: 10–15 minutes.

Design only. Compare at least these shapes:

1. byte-offset cursor over the merged spool;
2. monotonic sequence/event cursor;
3. separate `job_output(job_id, after=...)` tool;
4. extending `job_status` with an optional cursor.

Evaluate against:

- repeated-token reduction;
- simple model usage;
- resuming in a different ChatGPT turn;
- log rotation/retention;
- UTF-8 boundaries;
- terminal output retrieval;
- old-client compatibility;
- zero-output/quiet jobs;
- cursor invalidation;
- current Responses-API findings from Lane C (do not wait for C; mark cross-lane questions for R1 instead).

Produce a preferred and fallback design, but label both provisional pending R1 synthesis.

## Step B4 — Final report

Target: 8–12 minutes.

`lane-b-report.md` must contain:

- root cause of giant `job_status` results;
- hard-cap implementation summary and commit;
- test/performance evidence;
- before/after examples with synthetic data only;
- cursor/delta alternatives and provisional recommendation;
- explicit non-goals and deferred work;
- questions Lane C/D must answer before final API freeze.

Commit the report separately if useful.

## Lane B completion reply

```text
STEP: B4
STATUS: PASS | BLOCKED | FAIL
ARTIFACTS: docs/long-running-chatgpt/lane-b-report.md
COMMIT: <hard-cap sha and report sha if separate>
FINDINGS: <top findings>
NEXT: R1 synthesis gate; do not merge until coordinator review
```
