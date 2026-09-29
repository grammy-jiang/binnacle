# Lane A — long-turn reliability evidence

Status: **Round 1 Lane A complete (A0–A3).**

This report studies whether a ChatGPT foreground turn itself survives long enough to observe a durable local job reaching a terminal state and then continues meaningful tool work. Durable local job survival alone is not counted as same-turn success.

## Executive summary

- The frozen population contains **734** ChatGPT-attributable background/wait-expired jobs. Primary outcomes are 463 same-turn completed-and-resumed, 18 completed with no follow-up, and 253 whose originating turn stopped observing while the job was still running.
- Same-turn success is directly observed through **33.34 minutes**. The evidence does not establish a hard foreground timeout and does not justify a 20-, 30-, 40-, or 50-minute lifecycle cutoff.
- Recovery is real: **49** jobs were explicitly reattached by a later turn. Separately, **225** jobs reached raw terminal state without any attributable ChatGPT terminal observation in the frozen window.
- For >=5-minute jobs, success versus interruption is 24 versus 205. Seven turns contain both outcomes, so turn-wide duration, model/tool-step burden, accumulated result-token estimates, and shared infrastructure conditions cannot by themselves explain per-job observation loss.
- Current telemetry does not identify one dominant root cause. The durable API implication is stronger: job identity, terminal state, bounded incremental output, cancellation, and retrieve/resume must survive foreground-turn loss.

## 1. Frozen population and window

All timestamps below are host-local Australia/Sydney time (UTC+10 for this window).

- Population start: **2026-09-27T09:22:32+10:00**.
- Population end: **2026-09-29T10:26:27+10:00**.
- Start rationale: docs/usage-analysis-2026-09-27.md records 2026-09-27 09:22:32 as the production deployment time of commit 6c5f261, which changed the job_status/run_command wait descriptions to state that waits return as soon as the job or command exits. A0 found no evidence requiring a narrower clean-build boundary, so the planned deployment boundary is retained.
- End rationale: the end was frozen at the start of the A0 raw-journal reproduction, before any later Lane A analysis can change the observed window.

The A1 candidate population is frozen as ChatGPT-attributable run_command work that became a durable/background job in this half-open window, [start, end). Attribution requires the production journal tool_call to carry a non-empty ChatGPT turn=UUID/call field; candidate jobs must be linked to that call/job ID and must have been handed off as background work (for example, a wait-expired run_command result with background_job=true, or an explicitly backgrounded run). Synchronous commands that return terminally in the initial run_command result are not long-running population members.

A0 does **not** classify or correlate the full population. Those are A1 and A2 respectively.

## 2. Frozen classification definitions

The first three labels describe the originating ChatGPT turn. later_turn_reattached is a recovery annotation that can coexist with an originating-turn outcome. job_terminal_without_chat_observation is a job-level visibility outcome. unknown/unclassifiable is used when the journal cannot support a stronger label.

### same_turn_completed_and_resumed

The originating ChatGPT turn observes the target job in a terminal state, identified by the same job_id, and then makes at least one subsequent real MCP tool_call carrying the same turn UUID.

“Resumed” therefore means **at least one later real tool call after the terminal observation**. The terminal job_status call/result itself is not sufficient. Assistant prose, internal journal events, and the terminal result alone do not count as resumed work.

### same_turn_completed_no_followup

The originating turn observes the target job in a terminal state, identified by the same job_id, but there is no subsequent real MCP tool_call with the same turn UUID inside the frozen evidence window.

This is an observational label. It does not by itself prove why the foreground turn ended or whether the UI/platform would have allowed more work.

### same_turn_stopped_while_running

The target job is observed as still running in the originating turn, and that turn never records a later terminal observation for the same job_id before its last attributable tool activity in the frozen window.

Later completion of the local job does not upgrade this to same-turn success. A later turn may independently receive the later_turn_reattached annotation.

### later_turn_reattached

After the originating turn has ceased observing the target job, a **different** ChatGPT turn UUID makes a job-specific MCP call naming the same job_id (normally job_status or stop_job) and thereby retrieves or acts on the durable job state.

This is a recovery annotation, not evidence that the originating turn survived.

### job_terminal_without_chat_observation

Raw durable-job evidence records the target job reaching a terminal state, but no attributable ChatGPT tool result in any observed turn records the target job_id in a terminal state before the population end.

This distinguishes durable process completion from ChatGPT observation of completion.

### unknown/unclassifiable

Available evidence cannot safely establish the originating turn/job linkage, the relevant terminal/running observation, or the follow-up/reattachment relationship. Ambiguous cases remain here rather than being inferred from timing proximity.

## 3. A0 positive-case reproduction

The previously reported long positive case was independently reproduced from the raw binnacle-mcp.service / binnacle-jobs.service user journals.

| Field | Reproduced value |
| --- | --- |
| Turn UUID | 397d96d9-f3c2-49ec-8f09-233125a00740 |
| Job ID | b94de33877ec |
| Job start | 2026-09-29T00:42:30.827 |
| Job exit | 2026-09-29T01:15:04.578 |
| Journal runtime | 1953.751 s = 32.5625 min |
| Exit | code 0, normal exit |
| Target job_status calls in same turn | 33 |
| Requested wait on those calls | 50 s on all 33 |
| Terminal observation | 2026-09-29T01:15:04.717, call 6503116c6c2f, state=exited, exit_code=0 |
| First later real tool call, same turn | 2026-09-29T01:15:18.154, call b9719bcf47f6, run_command |
| Subsequent read evidence | read_file begins at 2026-09-29T01:15:25.714 in the same turn |
| A0 classification | same_turn_completed_and_resumed |

The terminal job_status requested 50 seconds but returned after 17.514 seconds when the job exited, consistent with the deployed wait description. The first subsequent real tool call began about 13.4 seconds after the terminal tool result. This case therefore demonstrates a same ChatGPT turn remaining active across a 32.56-minute local job, observing terminal state, and continuing tool work. It does not establish a general foreground-turn lifetime guarantee.

## 4. Reproducibility

A0 inspected the existing repository analysis/parsing code before applying bounded shell filters to the raw journal:

- scripts/usage_breakdown.py was reviewed for the journal attribution conventions, especially the exact turn= field.
- scripts/chat_scheduling_journal.py was reviewed for the current single-line journal event/field model.
- A0 itself wrote no new parser or product code; the reproducibility script was added later in A2.

The core raw-evidence queries were bounded to the target case. They can be reproduced locally with:

    journalctl --user -u binnacle-mcp.service -u binnacle-jobs.service \
      --since '2026-09-29 00:42:00' --until '2026-09-29 01:16:00' \
      --no-pager -o cat \
      | grep -E 'b94de33877ec|turn=397d96d9-f3c2-49ec-8f09-233125a00740'

For the decisive terminal/follow-up window:

    journalctl --user -u binnacle-mcp.service -u binnacle-jobs.service \
      --since '2026-09-29 01:13:00' --until '2026-09-29 01:17:00' \
      --no-pager -o cat \
      | grep -E 'b94de33877ec|turn=397d96d9-f3c2-49ec-8f09-233125a00740' \
      | grep -E 'event=(job_exit|tool_call|tool_result|job_status_timing)'

Raw command/stdin payloads may contain unrelated user/project details. The committed report therefore records only IDs, timestamps, tool families, state fields, and aggregate counts needed to reproduce the reliability classification.

For the committed A1/A2 reproducer, use the coordinator-verified project interpreter exactly:

    /home/grammy-jiang/Projects/binnacle/.venv/bin/python docs/long-running-chatgpt/lane-a-scripts/lane_a_analysis.py

Plain `python3` is not a supported invocation in this worktree because it does not have the `binnacle` package installed and fails with `ModuleNotFoundError: binnacle`. The exact interpreter above reproduced all A1 tables and the A2 aggregates during A3 self-review.

## 5. Evidence limitations frozen at A0

- Journal evidence can prove that a particular turn UUID made tool calls before/after a terminal observation; it cannot by itself explain why a turn with no follow-up stopped.
- Durable job_exit proves local process termination, not that ChatGPT observed it.
- Absence of a later tool call is not proof of a platform timeout, context exhaustion, user interruption, or network failure.
- later_turn_reattached requires explicit same-job_id evidence from a different turn; temporal proximity is insufficient.
- A0 establishes definitions and one positive reproduction only. It intentionally makes no population-wide duration, output-volume, tunnel, service-restart, or failure-driver claims.

## 6. A1 — population classification

A1 classified every candidate in the A0-frozen half-open window `[2026-09-27T09:22:32+10:00, 2026-09-29T10:26:27+10:00)`. The production journal contained **734 unique candidate jobs** whose attributable ChatGPT `run_command` result had `background_job=true` and a concrete `job_id`.

The classification pass used the existing `scripts/chat_scheduling_journal.py` parser over this exact journal query:

    journalctl --user -u binnacle-mcp.service -u binnacle-jobs.service \
      --since '2026-09-27 09:22:32' --until '2026-09-29 10:26:27' \
      --no-pager -o cat

The committed A1 reproducer is:

    /home/grammy-jiang/Projects/binnacle/.venv/bin/python docs/long-running-chatgpt/lane-a-scripts/lane_a_analysis.py

It prints the A1 outcome counts, runtime-threshold table, >=5-minute success table, and stopped-case recovery matrix without printing raw command/stdin payloads.

The pass linked each candidate's originating `run_command` call/turn to its `job_start` / `job_exit` record and all job-specific `job_status` / `stop_job` calls. It then applied the A0 definitions literally. A `later_turn_reattached` annotation requires a different turn's job-specific call to begin after the originating turn's last job-specific observation. No raw command text is committed; the report retains IDs, tool families, timing/state fields, and safe summaries only.

Two of the 734 candidates match the repository's existing nonce/test-traffic filters. A0 froze the population without a test exclusion, so A1 retains them. Both are below five minutes and therefore do not affect any long-runtime threshold below.

### 6.1 Outcome counts

The first three outcomes are mutually exclusive primary originating-turn outcomes and sum to 734. The recovery and visibility labels intentionally overlap those primary outcomes.

| Outcome | Count | Interpretation |
| --- | ---: | --- |
| `same_turn_completed_and_resumed` | 463 | Originating turn observed terminal state, then made another real tool call |
| `same_turn_completed_no_followup` | 18 | Originating turn observed terminal state, with no later real tool call in that turn |
| `same_turn_stopped_while_running` | 253 | Originating turn's last target-job observation remained non-terminal |
| `later_turn_reattached` | 49 | Different turn later named the same job after originating target-job observation ceased |
| `job_terminal_without_chat_observation` | 225 | Raw terminal state exists, but no attributable ChatGPT turn observed it |
| `unknown/unclassifiable` | 0 | No candidate lacked the linkage/state evidence required by the frozen definitions |

All 18 `same_turn_completed_no_followup` jobs were shorter than five minutes; the longest ran about 75.0 seconds. A1 does not infer why those turns had no follow-up.

### 6.2 Runtime thresholds

Thresholds use raw `job_start` to `job_exit` runtime. The class columns are the mutually exclusive originating-turn outcomes.

| Runtime | All candidates | Completed + resumed | Completed, no follow-up | Stopped while running |
| --- | ---: | ---: | ---: | ---: |
| >=5 min | 229 | 24 | 0 | 205 |
| >=10 min | 134 | 10 | 0 | 124 |
| >=20 min | 42 | 3 | 0 | 39 |
| >=30 min | 8 | 2 | 0 | 6 |
| >=40 min | 2 | 0 | 0 | 2 |
| >=50 min | 1 | 0 | 0 | 1 |

The A0 frozen window extends later than the evidence snapshot summarized in the master plan. It contains one additional long positive case: job `11023a552209`, turn `3ff65620-37c9-4d1d-a4cf-8a2e3216c82a`, started at 2026-09-29T09:27:28+10:00, ran 33.34 minutes, was terminally observed by the same turn, and was followed by another `run_command`. That explains why the A1 same-turn-success thresholds are 24 / 10 / 3 / 2 at >=5 / >=10 / >=20 / >=30 minutes rather than the earlier 23 / 9 / 2 / 1 snapshot. This is a population-window difference, not a reinterpretation of the earlier cases.

### 6.3 Same-turn successful jobs at >=5 minutes

For this table, "waits" counts target-job `job_status` calls through and including the terminal observation; post-terminal calls are not included. Spawn-to-terminal observation is measured from raw `job_start` to the terminal tool result received by the originating turn. The first post-terminal call is the first later real MCP call in that same turn.

| Job | Turn | Runtime min | Spawn→terminal obs min | Waits | Wait distribution | First post-terminal call |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `4fa55093b1b7` | `8778c798-f56b-4725-b78e-78c651b762aa` | 5.23 | 5.23 | 8 | 2s×1, 8s×3, 10s×2, 12s×2 | `run_command 7b2c3645bf71` |
| `1b27897ff165` | `9454399d-dffc-4146-a23f-74f61e445c7b` | 5.87 | 8.51 | 3 | 15s×3 | `run_command 844929138bb1` |
| `ac39804ea045` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 9.36 | 10.00 | 2 | 0s×1, 50s×1 | `job_status 9cdeac2dab40` |
| `ee0cdb21149e` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 8.90 | 9.96 | 2 | 0s×1, 50s×1 | `job_status fb83391dfad4` |
| `95bc627ec930` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 8.89 | 9.93 | 2 | 0s×1, 50s×1 | `job_status 1517e724e887` |
| `34c1fd96ee96` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 14.50 | 14.66 | 3 | 0s×2, 50s×1 | `job_status c41166c67bbe` |
| `eebdc6c12cb5` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 10.66 | 13.52 | 2 | 0s×1, 50s×1 | `job_status 40422b144f31` |
| `15b8385cd1d7` | `e56e9dad-a427-4941-84bf-74ec87c045de` | 12.06 | 12.14 | 2 | 0s×1, 50s×1 | `job_status 095869a3dc1f` |
| `02415661c7e6` | `48f994a2-4b73-4895-92a9-9fbad59d6be7` | 5.25 | 7.37 | 5 | 2s×1, 5s×1, 10s×3 | `run_command f3e5510da172` |
| `b1675a8f6aee` | `48f994a2-4b73-4895-92a9-9fbad59d6be7` | 5.63 | 6.97 | 6 | 5s×1, 10s×1, 20s×4 | `job_status ebd4765086fd` |
| `a382a5ec7b7c` | `53208944-ce21-4ce2-9a17-21220f8fb17a` | 12.28 | 12.40 | 10 | 30s×2, 40s×3, 45s×5 | `read_file 6a3f63f5ec97` |
| `d8c52a9a0e6e` | `53208944-ce21-4ce2-9a17-21220f8fb17a` | 7.23 | 7.24 | 5 | 30s×2, 40s×3 | `job_status 188b0cfc55ff` |
| `002805e25185` | `0125be7a-2e90-4c3f-ad4b-bf2760688373` | 6.47 | 8.73 | 5 | 30s×1, 40s×2, 45s×2 | `read_file 2eb61246cc3e` |
| `f88b741e4e4d` | `0125be7a-2e90-4c3f-ad4b-bf2760688373` | 6.80 | 6.80 | 4 | 30s×1, 40s×2, 45s×1 | `run_command e519c6767e05` |
| `a158004ca36b` | `0125be7a-2e90-4c3f-ad4b-bf2760688373` | 5.17 | 5.48 | 4 | 35s×1, 45s×3 | `job_status 156463201188` |
| `511ee74905ee` | `0125be7a-2e90-4c3f-ad4b-bf2760688373` | 6.33 | 6.37 | 5 | 35s×1, 45s×4 | `run_command 50cf142669dc` |
| `aa8d2e4bde5e` | `d8b97335-8f1e-457d-adef-352dd5fd17d2` | 5.46 | 5.47 | 3 | 40s×1, 45s×2 | `job_status 4c9493604334` |
| `78d4d8be1284` | `d8b97335-8f1e-457d-adef-352dd5fd17d2` | 5.56 | 5.57 | 3 | 45s×3 | `job_status 68ea89e5c842` |
| `3305e5b86613` | `54ac2005-f047-435d-8abb-579d8577c756` | 11.09 | 11.10 | 15 | 30s×2, 35s×6, 40s×2, 45s×3, 50s×2 | `run_command 4a7ec05c3a84` |
| `1b3cecf4ff45` | `fb9d21bd-d85b-4c55-949b-4a547ba9582c` | 12.27 | 12.27 | 12 | 50s×12 | `run_command a6fc288f3cf7` |
| `bc517950bbbd` | `fefd1d68-9bc7-40dc-9c45-8c933ccd9a21` | 28.89 | 28.90 | 30 | 0s×2, 50s×28 | `read_file 4ea84ead50fd` |
| `30b84824f439` | `fefd1d68-9bc7-40dc-9c45-8c933ccd9a21` | 10.73 | 10.74 | 11 | 50s×11 | `run_command 6eb490bee1d0` |
| `b94de33877ec` | `397d96d9-f3c2-49ec-8f09-233125a00740` | 32.56 | 32.56 | 33 | 50s×33 | `run_command b9719bcf47f6` |
| `11023a552209` | `3ff65620-37c9-4d1d-a4cf-8a2e3216c82a` | 33.34 | 33.34 | 33 | 50s×33 | `run_command 409051c0d202` |

The table records tool families rather than command bodies. Some first post-terminal calls are `job_status` calls because a turn was managing more than one durable job; A1 applies the frozen definition and does not evaluate whether those follow-up calls were efficient.

### 6.4 Originating turn stopped while the job was running

All 253 `same_turn_stopped_while_running` cases were checked for later same-`job_id` observations and raw completion within the frozen window.

| Later turn reattached? | Raw job terminal by frozen end? | Count |
| --- | --- | ---: |
| Yes | Yes | 37 |
| Yes | No | 0 |
| No | Yes | 215 |
| No | No | 1 |

Among the 37 reattached stopped cases, a later turn itself observed terminal state in 27; in 10, the later turn observed only non-terminal state even though the raw job later completed. Overall, 252 of the 253 stopped cases have a raw terminal event inside the frozen window. The remaining job, `569b5ffe86f1`, started at 2026-09-29T10:25:35+10:00, less than a minute before the frozen end; A1 records only that no terminal event or later reattachment exists **inside the frozen window**.

Representative interrupted/recovery cases are traceable without exposing command bodies:

| Job | Originating turn | Runtime | Later turn | Later terminal observation? | Raw completion? |
| --- | --- | ---: | --- | --- | --- |
| `0349280d801e` | `8be4f8bd-4080-4e33-8367-5659931a47aa` | 219.33 min | `4f0ee1dd-781b-4c81-bfe5-986e359019c4` | Yes | Yes |
| `a03a43c6101a` | `7c62f330-f061-48ce-9ebd-cc28dd5b7c7d` | 49.21 min | `7510760f-cd67-4271-8e9a-4722187fe88c` | Yes | Yes |
| `10cc7acfb901` | `779b5822-2160-4419-a62e-ce60b8830bad` | 34.35 min | none | No | Yes |
| `57bdb27e86e7` | `3d543453-547a-428b-8b90-cec332b83891` | 31.04 min | `e268600f-72ad-4bcf-b4a4-e10256f05d94` | Yes | Yes |
| `569b5ffe86f1` | `0e2af7ac-78ab-48f3-9274-9903872c11ee` | censored at frozen end | none | No | Not observed by frozen end |

These are classification facts only. A1 does not infer why the originating turns stopped, nor does it compare network, output volume, context pressure, service events, or other candidate failure drivers; that work remains A2.

## 7. A2 — candidate failure-driver correlation

A2 compares the long-running cohort only: the 229 candidates with raw runtime >=5 minutes. This avoids letting hundreds of one-second/short handoffs dominate a long-turn reliability comparison. In this cohort, 24 jobs are `same_turn_completed_and_resumed`, 205 are `same_turn_stopped_while_running`, and none are `same_turn_completed_no_followup`.

The committed reproducer is:

    /home/grammy-jiang/Projects/binnacle/.venv/bin/python docs/long-running-chatgpt/lane-a-scripts/lane_a_analysis.py

It re-reads the frozen production journals, prints the A1 outcome/threshold/success/recovery tables, and prints the A2 aggregate comparison without emitting raw command or stdin text. Visible model/tool steps use the repository's existing usage-analysis convention: a new step begins when the next tool call starts at least 2 seconds after the previous call.

### 7.1 Success versus interruption

These are job-level comparisons. Turn-wide metrics repeat when one turn owns multiple candidate jobs, so they are descriptive rather than independent statistical samples.

| Candidate factor | Completed + resumed | Stopped while running | Evidence reading |
| --- | ---: | ---: | --- |
| Jobs / unique turns | 24 / 12 | 205 / 33 | direct counts |
| Median job runtime | 8.9 min | 11.1 min | correlated only; distributions overlap |
| Median total visible turn duration | 35.6 min | 3.0 min | correlated only and partly definitional |
| Median tool calls in turn | 88 | 36 | not supported as a monotonic failure driver |
| Median visible model/tool steps | 77 | 23 | not supported as a monotonic failure driver |
| Median total estimated result tokens in turn | 180,684.5 | 26,288 | not supported as a monotonic context-pressure explanation |
| Median maximum estimated tokens for one result | 8,057.5 | 4,780 | not supported as a monotonic context-pressure explanation |
| Median target-job `job_status` calls | 5 | 0 | correlated only; observation behavior is entangled with the outcome definition |
| Non-zero raw job exit | 0/24 | 4/205 | correlated only; 201 interrupted jobs still exited zero |
| Concurrent same-turn candidate job | 17/24 | 180/205 | correlated only |
| Tunnel restart during originating observation | 1/24 | 0/205 | too sparse to estimate an effect |
| MCP reload/restart during originating observation | 0/24 | 1/205 | too sparse to estimate an effect |
| 08:21 network-failover window overlap | 0/24 | 0/205 | not measurable for this long cohort; no exposure |

The runtime distributions overlap substantially: same-turn success exists through 33.34 minutes, while stopped cases begin at five minutes and extend to 219.33 minutes. The frozen data therefore do **not** support a hard foreground wall-clock timeout. Absence of a >=40-minute success is an evidence limit, not a timeout boundary.

The much longer turns, larger step counts, and larger accumulated result-token totals on the successful side run opposite to a simple monotonic hypothesis that "longer/more context necessarily makes the turn stop." This is not evidence that more context improves reliability. It shows only that those turn-wide quantities are insufficient explanations in this population.

### 7.2 Target `job_status` output and job-output snapshots

Only 44 of the 205 stopped cases made any target-job `job_status` call after the spawning handoff, versus 24/24 successful cases. Across the actual target-job status snapshots:

| Snapshot metric | Completed + resumed | Stopped while running |
| --- | ---: | ---: |
| Jobs with target `job_status` | 24 | 44 |
| Target `job_status` calls | 208 | 116 |
| Median structured result bytes | 7,273.5 | 7,258.0 |
| Maximum structured result bytes | 475,307 | 588,877 |
| Maximum estimated tokens in one status result | 118,825 | 147,227 |
| Truncated status results | 0 | 0 |
| `quiet=true` share | 22.6% | 19.8% |
| Median `last_output_age_s` | 10.50 s | 10.45 s |

Within the frozen >=5-minute cohort, returned `job_status` size and truncation are **not supported** as differentiators: median returned sizes are nearly identical and none of the 324 target-job status results is marked truncated. Large outliers exist in both classes, so the historical output-volume hazard remains real, but this population does not show truncation separating success from interruption.

The available `quiet` and `last_output_age_s` snapshots likewise do not support a quiet-job explanation: their aggregate values are close across classes. Actual continuous output cadence is **not measurable with current telemetry**; the journal exposes snapshots when status is requested, not a time series of output production.

### 7.3 Mixed turns and concurrency

The 229 long-running jobs belong to 38 unique turns. Seven turns contain both a >=5-minute successful job and a >=5-minute stopped-while-running job. Those mixed turns account for 18/24 successful jobs and 63/205 interrupted jobs.

This is direct evidence that a turn-wide property cannot be a sufficient per-job explanation by itself: jobs in the same turn share the same overall turn duration, accumulated turn context/results, and broad tunnel/MCP environment yet can receive different classifications. Concurrency is more common among stopped jobs (180/205) than successful jobs (17/24), so it is **correlated only** with interruption. The journal does not record model intent or an explicit "I am abandoning observation of job X" event, so A2 cannot distinguish deliberate prioritization among concurrent jobs from an involuntary foreground interruption.

### 7.4 Network, tunnel, and MCP overlap

There are five `binnacle-tunnel.service` stop/restart events in the frozen window. One long successful case, job `1b3cecf4ff45`, overlaps a tunnel restart during its originating observation interval and still reaches terminal observation plus follow-up. No stopped >=5-minute case overlaps a tunnel restart. This directly shows that a tunnel restart is **not invariably fatal**, but the exposure count is too small to estimate its reliability effect.

The watchdog's known active-uplink disruption is reproducible in the 2026-09-29 08:20–08:25 journal window: active `wlan1` loses gateway/DNS/TCP reachability beginning at 08:21:19, the tunnel is restarted at 08:23:22, and the watchdog is operating via `wlan2` by 08:23:42. None of the >=5-minute cases' originating observation intervals overlaps the defined 08:21:19–08:24:45 failover window. Network failover is therefore **not measurable as a driver in this long cohort**, even though the raw infrastructure event itself is directly evidenced.

The MCP journal contains ten development auto-reload events plus one systemd service restart in the frozen window. Only one stopped long case, job `4aebecba5d39`, overlaps one of these reload/restart events; no successful long case does. One exposed case is insufficient to support a causal or general correlation claim.

Reproduce the infrastructure event windows with:

    journalctl --user -u binnacle-tunnel.service \
      --since '2026-09-27 09:22:32' --until '2026-09-29 10:26:27' \
      --no-pager -o short-iso | grep 'Stopping binnacle-tunnel.service'

    journalctl --user -u binnacle-watchdog.service -u binnacle-tunnel.service \
      --since '2026-09-29 08:20:00' --until '2026-09-29 08:25:30' \
      --no-pager -o short-iso \
      | grep -E 'uplink_probe_error|event=cycle|Stopping binnacle-tunnel|Started binnacle-tunnel'

    journalctl --user -u binnacle-mcp.service \
      --since '2026-09-27 09:22:32' --until '2026-09-29 10:26:27' \
      --no-pager -o short-iso \
      | grep -E 'Stopping binnacle-mcp.service|WatchFiles detected changes'

### 7.5 Local exit status

Four of 205 stopped long jobs exit non-zero; zero of 24 successful long jobs do. That is a weak class association, but local failure is plainly **not necessary** for interruption: 201 stopped jobs have raw exit code zero. Because many stopped turns cease observing before the later local exit occurs, the final exit code also cannot generally be the event that caused the earlier observation to stop.

### 7.6 Evidence classification

| Candidate explanation | A2 classification | Why |
| --- | --- | --- |
| Hard wall-clock foreground timeout | **not supported** | Successes reach 33.34 min; stopped and successful runtimes overlap; no direct expiry event exists |
| More model/tool steps cause interruption | **not supported** | Successful cases have higher median steps, and mixed turns contain both outcomes |
| Higher accumulated result/context volume causes interruption | **not supported** as a monotonic explanation | Successful cases have much higher median accumulated result tokens; actual model context occupancy is not logged |
| More/larger `job_status` output causes interruption | **not supported** in this cohort | Similar median status sizes, zero truncation in both classes, large outliers in both |
| Quiet output causes interruption | **not supported** by available snapshots | Quiet share and last-output-age snapshots are close |
| Fewer target-job observations associate with interruption | **correlated only** | Median status calls are 0 vs 5, but terminal observation is part of the success definition |
| Concurrent same-turn jobs associate with interruption | **correlated only** | 180/205 vs 17/24; seven mixed turns demonstrate differing outcomes under shared turn conditions |
| Non-zero local exit associates with interruption | **correlated only, weak** | 4/205 vs 0/24; 201 interrupted jobs still exit zero |
| Tunnel restart causes interruption | **not supported as deterministic; effect not measurable** | One successful long case overlaps a restart; no interrupted long case does |
| MCP reload/restart causes interruption | **not measurable** | Only one interrupted long case is exposed |
| 08:21 active-uplink failover causes long-case interruption | **not measurable** | No >=5-minute originating observation interval overlaps it |
| Foreground expiry vs voluntary model handoff | **not measurable with current telemetry** | No explicit turn-end reason or model handoff event is logged |

### 7.7 Missing telemetry that limits diagnosis

The current journals cannot directly distinguish several competing explanations. Materially useful missing evidence is:

- an explicit foreground-turn end/cancel reason from the ChatGPT host, with timestamp and turn UUID;
- model-step identifiers and actual context-window occupancy/token accounting per step, rather than inferred steps and summed tool-result estimates;
- a tunnel request/session disconnect reason tied to the affected turn/call, rather than only service/uplink events;
- a stable MCP server-instance/generation identifier on each tool call/result so a reload boundary can be joined directly without timestamp inference;
- job-output sequence/cursor events or periodic byte-production telemetry, so continuous output cadence can be measured instead of inferred from `quiet` / `last_output_age_s` polling snapshots;
- an explicit model-side observation/handoff signal for a durable job, so deliberate abandonment of one concurrent job can be separated from involuntary foreground loss.

A2 stops at correlation and diagnosability. The evidence-bounded risk ranking and contract implications are stated separately in A3 below.

## 8. A3 — recommendations and Round-2 inputs

A3 converts only the frozen A0–A2 evidence into reliability guidance. It does not assign causes where the telemetry cannot distinguish them.

### 8.1 Evidence-supported reliability risks

The ordering below ranks operational risks demonstrated by Lane A evidence, not speculative root causes.

1. **Foreground observation is not durable.** This is the primary demonstrated risk. Of 734 handed-off jobs, 253 jobs' originating turns stopped observing while the target job was still running. In the >=5-minute cohort, 205/229 jobs have that outcome. A durable local process therefore cannot rely on the originating ChatGPT turn remaining alive through completion.
2. **Local completion can become invisible to ChatGPT unless state is retrievable later.** There are 225 jobs with raw terminal state but no attributable ChatGPT terminal observation in the frozen window. Conversely, 49 jobs were explicitly reattached by a later turn, including 37 whose originating turn stopped while running. Durable identity and retrieval are therefore exercised recovery paths, not hypothetical features.
3. **Concurrent job observation is an operational ambiguity.** Concurrency is correlated with interruption (180/205 stopped long jobs versus 17/24 successful long jobs), and seven turns contain both outcomes. This does not prove concurrency causes interruption, but it demonstrates that a turn may continue useful work while ceasing observation of a particular job. Per-job identity/state must therefore remain unambiguous when multiple jobs coexist.
4. **Large status payloads remain a context-efficiency exposure, not an A2-proven interruption cause.** Long-case `job_status` snapshots reached 588,877 structured bytes and 147,227 estimated tokens, although no target status result in the A2 cohort was marked truncated and median sizes were nearly identical across outcomes. The risk is direct payload/context consumption; Lane A does not claim it caused the observed interruptions.

Tunnel restart, MCP reload/restart, active-uplink failover, non-zero local exit, quiet output, and a fixed foreground lifetime are **not ranked as demonstrated reliability causes**. Their A2 evidence is sparse, weakly correlated, or explicitly non-diagnostic.

### 8.2 Wall-clock policy

Current evidence does **not** justify a hard wall-clock threshold policy for foreground ChatGPT turns.

- Same-turn completion-and-resume is directly observed at 32.56 and 33.34 minutes.
- Interrupted and successful runtimes overlap below those durations.
- There are no >=40-minute same-turn successes in the frozen population, but absence of evidence above that point is not evidence of a 40-minute expiry.
- No journal event records a platform foreground timeout reason.

Accordingly, Round 2 should not encode a 20-, 30-, 40-, or 50-minute foreground lifetime into the job lifecycle contract. Individual wait calls may remain bounded for responsiveness, but **job durability, terminal state, output retrieval, and cancellation must not depend on one foreground turn continuing to wait**.

### 8.3 Smallest telemetry additions

The minimum telemetry needed to separate the major unresolved explanations is:

| Diagnostic question | Smallest useful addition |
| --- | --- |
| Did the ChatGPT foreground turn expire, get cancelled, or end normally? | Host-side `turn_end` event with turn UUID, timestamp, and reason code |
| Did the tunnel/session fail independently? | Connection/session generation ID on MCP calls/results plus disconnect/reconnect reason |
| Did model context pressure contribute? | Model-step ID plus actual input/context token occupancy and limit at each step |
| Did an MCP reload sever continuity? | Stable MCP server-generation ID on every tool call/result |
| Was the job quiet or producing output between polls? | Monotonic job output sequence/byte counters with timestamps |
| Did the model deliberately stop observing one concurrent job? | Explicit per-job observe/handoff/abandon event tied to turn UUID and job ID |

These additions are intentionally diagnostic rather than prescriptive. They would let a future analysis distinguish foreground expiry, transport failure, context pressure, server reload, quiet execution, and voluntary handoff without inferring cause from timing proximity.

### 8.4 Findings that should constrain the Round-2 lifecycle contract

Lane A supplies the following constraints to E0/E1 synthesis:

- **Stable durable identity:** `job_id` must identify work independently of the originating ChatGPT turn or MCP session.
- **Retrieve/resume across turns:** a later turn must be able to retrieve current and terminal state by `job_id`; 49 observed reattachments show this is a real recovery path.
- **Durable terminal state/result:** completion must remain available after the originating turn stops observing; 225 terminal-without-chat-observation cases demonstrate the visibility gap.
- **Incremental, bounded output retrieval:** output should be retrievable by a monotonic cursor/sequence with bounded responses so reattachment does not require replaying an ever-growing transcript. Lane A's large status snapshots support the bounded-output requirement even though output size did not distinguish success from interruption.
- **Per-job state under concurrency:** status/output cursors must be scoped to one job, because mixed turns can successfully observe one long job while ceasing observation of another.
- **Cancellation independent of foreground continuity:** cancellation must address durable job identity, not depend on the spawning turn still existing.
- **Foreground waiting is an optimization, not a contract:** clients may wait/poll when useful, but no API guarantee should require one ChatGPT turn to remain alive for the full job runtime.
- **Do not bake in a wall-clock expiry inferred from this sample:** the contract should represent durable lifecycle state, not a guessed foreground timeout.
- **Keep causality/diagnostics separate from lifecycle state:** host turn-end reason, connection generation, model context usage, and server generation are valuable telemetry, but should not be conflated with public job states unless Round 2 has independent evidence for doing so.

These constraints are compatible with the master plan's candidate concepts of durable status, terminal result, cancel, retrieve/resume, and incremental output/cursors. Lane A does not decide whether a new abstraction replaces or extends `run_command`, `job_status`, and `stop_job`; that is a Round-2 compatibility/design decision.

### 8.5 Lane A conclusion

The strongest conclusion is architectural rather than causal: **durable local execution works independently of foreground ChatGPT continuity, while foreground observation is demonstrably intermittent.** The evidence therefore supports designing recovery and retrieval as first-class behavior instead of trying to guarantee that one turn waits indefinitely.

Lane A does not identify one dominant root cause for stopped observation. Duration, turn step count, accumulated result-token estimates, target `job_status` size/truncation, quietness, tunnel restarts, MCP reloads, and local exit status either fail to separate the classes or lack enough exposed cases. The next decision point is the Round-1 synthesis gate, where Lane A's constraints should be combined with the independent output-contract, Responses API, and MCP-capability evidence from the other lanes.
