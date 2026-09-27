# Quality guard plan (2026-09-27)

Status: design, approved in principle by the owner on 2026-09-27 (all six
proposed kinds of test). This plan replaces sections 4 to 6 of
`docs/test-strategy-review-2026-09-27.md`.

## 1. Goal

The owner's rule: this MCP server is important. It must stay **simple,
stable, reliable and efficient**, and no future change may degrade any of the
four. Each quality below gets measurable invariants, the tests that hold
them, when those tests run, and what happens when one fails.

The test program follows the same rule. Every scheduled job is one script.
It runs through `cron-report`, puts one `STATUS: summary` line first, and
stays silent when all is well.

## 2. Simple: the surface and the code stay small

| Invariant | Test | Runs |
| --- | --- | --- |
| Every tool's name, description, input schema, output schema and annotations change only on purpose | a pinned hash per tool and per client profile, the way `tests/contracts/test_run_command_surface.py` pins run_command (new for the other seven tools) | every commit |
| The tool count per client stays fixed (ChatGPT: 6) | a contract test (new) | every commit |
| ChatGPT's surface (descriptions, schemas, server instructions) stays within its token budget | today's measured size plus 5 %, or a documented reason (new) | every commit |
| Modules stay small; layers do not import each other the wrong way | module size ratchet, architecture boundaries (exist) | every commit |
| No new runtime dependency without review | the runtime dependency list is pinned in a test (new); deptry (exists) | every commit |

## 3. Stable: the same inputs give the same outputs, with no flaky tests

| Invariant | Test | Runs |
| --- | --- | --- |
| No behavior regression | unit, property, contract, integration and system suites with the per-module coverage gate (95 % core from unit tests, 90 % other from the full suite) (exist) | every commit |
| Tool results do not drift | golden outputs: each tool on fixed fixtures, with the structured result pinned (timestamps and ids masked) (new) | every commit |
| Old state still works after an upgrade | old configs load (exists); old journals parse (exists); a job spool written by the previous release is readable (new) | every commit |
| Tests do not flake | the full suite 5 times with different `pytest-randomly` seeds while the host is loaded; any failure is a flaky test, fixed or quarantined within a week (new) | weekly |
| Tests really assert | mutation testing (`mutmut`), two core modules per week in rotation, so each core module comes round every seven weeks; kill rate at least 80 % (new schedule) | weekly |
| All supported Pythons work | the CI matrix 3.10 to 3.14 (exists) | every commit |

## 4. Reliable: it keeps working through deploys, faults and time

| Invariant | Test | Runs |
| --- | --- | --- |
| A deploy never leaves the server broken | post-deploy smoke: doctor green; `tools/list` with authentication; one nonce call per tool (read_file, list_files, search_text, a fast run_command, a run_command that becomes a job plus job_status with a wait, stop_job on a sleep job); the journal holds each nonce; no traceback. On failure: fast-forward back to the previous commit, rerun the smoke, and send mail (new) | every deploy |
| The live server works every day | the same smoke plus `binnacle-tunnel doctor` and `binnacle-watchdog doctor` (new; the watchdog doctor already runs at 03:40) | daily |
| Jobs survive restarts; stops are clean | the job lifecycle and stop-path integration tests (exist); a restart with a running job in a disposable test deployment (new) | every commit |
| Faults are recovered | fault-injection drills: freeze the MCP worker, freeze the tunnel, restart the jobs daemon mid-job, fill the job spool on a test mount. Each drill has an expected recovery and a time limit, and results are recorded in `docs/` (scripted, attended) | quarterly, and after changes to jobs, watchdog or tunnel code |
| No slow leak | soak: 12 hours of synthetic calls (one every 10 s, mixed tools) against the live server at night. RSS growth, open file descriptors, p95 latency and errors are compared with the start of the run (new) | monthly |
| Other clients keep working | the conformance probe (T1 to T14) for Claude Code, Codex and Copilot (exists as a tool; the schedule is new) | monthly, and after a surface change |

## 5. Efficient: fast, small and cheap

| Invariant | Test | Runs |
| --- | --- | --- |
| Tools do not get slower | a fixed benchmark on the Pi (same fixtures, same order) plus p50 and p95 per tool from the week's journal, compared with the recorded baseline. WARN above 1.25 times the baseline p95 (new) | weekly |
| Results do not grow | size budgets for the golden fixtures (structured bytes and tokens) (new, part of the golden tests) | every commit |
| Start-up and memory stay low | start-up time and RSS after start, measured by the post-deploy smoke. WARN above 1.25 times the baseline (new) | every deploy, daily |
| The suite stays fast | the test timing policy (exists) | every commit |
| ChatGPT needs no more model steps than before | the usage report's step and polling metrics (`scripts/usage_breakdown.py`), compared with the latest baseline in `docs/usage-baselines/` (exists; the schedule is new) | weekly |

## 6. Schedule

| When | What | Time on the Pi | On failure |
| --- | --- | --- | --- |
| Every commit (pre-commit and CI) | sections 2, 3 and 5 marked "every commit" | CI about 5 to 10 min | the merge is blocked |
| Every deploy | post-deploy smoke, start-up and RSS | about 1 min | automatic rollback, then mail |
| Daily, 06:50 | live smoke and the three doctors | about 2 min | ALERT mail |
| Weekly, Saturday night | flake hunt, two mutation modules, the latency benchmark and journal percentiles, the usage steps and polling report | about 3 h | WARN or ALERT mail; a flaky test is fixed within a week |
| Monthly, first Sunday night | 12-hour soak; client compatibility probe | about 12 h | mail |
| Quarterly, and after related changes | fault-injection drills (attended) | about 1 h | recorded in `docs/`; fixed before the next release |

## 7. Order of work

1. **Every-commit additions:** surface pins for all tools, the tool count, the
   token budget, golden outputs with size budgets, the dependency pin, and
   job-spool compatibility. About 1 day.
2. **Post-deploy smoke with rollback, and the daily live smoke:** one script
   (`scripts/deploy_smoke.py`), used by the deploy procedure and by cron.
   About 1 day.
3. **Weekly jobs:** flake hunt, mutation rotation, latency and resource
   report, usage report. About 1 to 2 days.
4. **Monthly and quarterly:** soak, client probe schedule, drill scripts.
   About 2 days.

Each step ends with its tests green, its schedule installed, and
`docs/testing.md` updated.
