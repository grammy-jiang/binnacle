# Usage analysis, 2026-09-27 — window 2026-09-14 onward

Source: `scripts/usage_breakdown.py` over the `binnacle-mcp` journal, calls
attributed to ChatGPT via the tunnel log, nonce-marked test traffic excluded.
Baseline for deltas: `2026-09-13.json` (2026-09-07).

## 1. Tool mix

Total tool calls: 42847 (baseline 2001)

| Tool                            | Calls | Share | Baseline share |
| ------------------------------- | ----- | ----- | -------------- |
| run_command                     | 22494 | 52.5% | 54.3%          |
| read_file                       | 9050  | 21.1% | 26.6%          |
| job_status                      | 6310  | 14.7% | 1.6%           |
| search_text                     | 4225  | 9.9%  | 13.1%          |
| list_files                      | 602   | 1.4%  | 4.1%           |
| stop_job                        | 101   | 0.2%  | 0.2%           |
| async_probe_wait                | 44    | 0.1%  | 0.0%           |
| async_probe_seed                | 7     | 0.0%  | 0.0%           |
| async_probe_echo                | 5     | 0.0%  | 0.0%           |
| async_probe_nondestructive_wait | 4     | 0.0%  | 0.0%           |
| -q                              | 3     | 0.0%  | 0.0%           |
| --help                          | 1     | 0.0%  | 0.0%           |
| async_probe_capabilities        | 1     | 0.0%  | 0.0%           |

Per day: 09/14/26 2321, 09/15/26 1860, 09/16/26 333, 09/17/26 1538, 09/18/26 1761, 09/19/26 3992, 09/20/26 2432, 09/21/26 1163, 09/22/26 5472, 09/23/26 3864, 09/24/26 4666, 09/25/26 8234, 09/26/26 3277, 09/27/26 1934

## 2. job_status polling

6188 calls on 2658 jobs; median 1 per job (+0), max 77 (+73).
Listings without a job_id: 122 (+120) (a habit, not a poll; run_command's synchronous result says no job was created).

## 2b. Calls per turn

496 turns, 16066 forwarded calls; calls per turn median 10 (+5), p90 106 (+67), max 374 (+186); gap between calls inside a turn median 11.3 s (-2.7), p90 55.2 s (+9.7). One `wfr_` id is one serial agent turn; forwarded calls include every RPC, so the total exceeds the attributed tool calls.

## 3. New-parameter uptake

`job_status.tail_lines` 4931, `job_status.wait_seconds` 4772, `run_command.tail_lines` 10295, `run_command.wait_seconds` 21571, `search_text.context_lines` 3675, `search_text.line_numbers` 3836

`run_command.background=true` 1611 (+1582)

> Zero uptake with an unchanged metric means the model never noticed the
> parameter: fix the tool description before touching code.

## 4. run_command traits

22489 run_command calls with a visible command.

| Trait          | Calls | Share of run_command | Baseline    |
| -------------- | ----- | -------------------- | ----------- |
| python-heredoc | 5429  | 24.1%                | 489 (45.0%) |
| git            | 4911  | 21.8%                | 233 (21.5%) |
| grep           | 1280  | 5.7%                 | 68 (6.3%)   |
| hand-tail/head | 1221  | 5.4%                 | 52 (4.8%)   |
| hand-head      | 826   | 3.7%                 | 36 (3.3%)   |
| grep-on-files  | 515   | 2.3%                 | 16 (1.5%)   |
| hand-tail      | 417   | 1.9%                 | 18 (1.7%)   |
| ps/pgrep       | 310   | 1.4%                 | 22 (2.0%)   |

`hand-tail` is what `run_command.tail_lines` replaces; `hand-head` (first lines) has no
parameter. `grep-on-files` counts a grep that starts a segment, not one after a pipe
(rule fixed 2026-09-13; earlier baselines used a looser rule, compare the grep line).

grep: 613 on files (+596), 1139 filtering command output (+1065).

## 5. read_file slices

calls 9050 (+8517); distinct files 3568 (+3363); max reads of one file 427 (+400); whole-file reads 3043 (+2874); median slice (lines) 96 (-27); p90 slice 320 (+49); longest same-file run 20 (+14); sequential continuations 149 (+147).

## 6. git subcommands

status 2929, diff 2200, log 1415, rev-parse 1274, show 959, add 717, commit 593, worktree 309, branch 280, grep 195, merge 175, ls-files 77, rev-list 65, push 62, fetch 47, remote 22, rebase 21, switch 19, config 19, checkout 17, cat-file 16, init 16, restore 15, ls-tree 10, reset 9, stash 8, tag 7, clone 5, describe 4, blame 3

## 7. Reading of the numbers

The totals above use the script's timestamp match against the tunnel log,
which over-attributes when local agents are busy (42,651 calls, of which
3,173 carry `client=openai-mcp(Codex)`). This round's own pass uses the turn
id instead: every call the tunnel forwards carries `turn=<uuid>/<call>`, so
the attribution is exact. By turn id, ChatGPT made 26,403 calls in 683 turns
between 2026-09-14 and 2026-09-27.

**Calls are not the cost; model steps are.** ChatGPT sends several tool
calls in one model step. Counting calls that start less than 2 s after the
previous one as one step: 20,092 steps, 1.31 calls per step; steps per turn
median 18, p90 74, max 190; the gap between steps is about 11 s of model
time. The 2026-09-13 lesson ("report per-call latency and calls per turn as
two numbers") needs a third: steps per turn.

**Multi-file reads are already parallel.** 2,801 `read_file` calls came
directly after a read of a different file (10.6 % of calls, 1,058 runs,
median 3 files). 2,408 of them (86 %) were in the same step as the previous
read. Only 393 started a new step, so a batch-read tool could save at most
about 2 % of the steps. The candidates (`read_file.files`, a separate
`read_files`, and the owner's variant of one `read_files` that replaces
`read_file`) were built off by default and planned for an evaluation; the
owner stopped the evaluation on this finding. They are kept by the tag
`archive/read-files-eval-2026-09-27`, with the plan in
`docs/read-files-plan-2026-09-27.md` on that tag.

**What the steps are.** job_status 17.6 %, Python runs 16.5 %, read_file
10.7 %, git inspection 9.7 %, other shell 6.1 %, search_text 6.0 %, manager
helper scripts 5.8 %, test runs 5.0 %. The most common serial pairs are
job_status -> job_status (1,413), Python -> Python (1,056), read -> read
(524) and test run -> job_status (492). Python, read, search and git steps
are ordinary work: each depends on the previous result, and output
truncation is not the reason (the first output was truncated in 3.3 % of
the serial shell pairs; median output 482 bytes).

**Polling is the waste.** 3,411 of 3,670 `job_status` calls were alone in
their step. Outside the manager-dispatched chats (539 turns), such solo
polls were 21.5 % of the steps, and 47 % of them asked for less than the
50 s maximum; inside the manager chats (144 turns) they were 8.4 % of the
steps, and 91 % used 50 s. Against the realistic minimum per job
(ceil((runtime - initial wait) / 61 s), with 61 s = one 50 s wait plus the
model's think time), about 1,100 solo polls were not needed: 5.5 % of all
steps. Neither description said that a wait ends when the job exits, so a
short wait looked like the responsive choice.

## 8. Candidates, ranked by model steps absorbed

1. **State that a wait ends when the job exits** (shipped, section 9): up to
   about 1,100 steps in two weeks (5.5 %). Mechanism: short waits look
   responsive, but they cost a model step each time the job is still
   running. Cannot fix: intentional quick looks at a job's log, and jobs
   longer than 50 s still need one poll per minute or so.
2. **Batch read** (stopped): at most 393 steps (2 %); the model already reads
   files in parallel.
3. **git read tool** (deferred again by the owner): 395 git -> git step pairs
   (2 %).
4. Python, search and edit steps: no tool change absorbs them.

## 9. Shipped

Recorded when the change is live: see below.
