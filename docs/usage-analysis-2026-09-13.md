# Usage analysis, 2026-09-13 — window 2026-09-07 onward

Source: `scripts/usage_breakdown.py` over the `binnacle-mcp` journal, calls
attributed to ChatGPT via the tunnel log, nonce-marked test traffic excluded.
Baseline for deltas: `2026-09-06.json` (2026-09-04 to 2026-09-06).

## 1. Tool mix

Total tool calls: 2001 (baseline 820)

| Tool        | Calls | Share | Baseline share |
| ----------- | ----- | ----- | -------------- |
| run_command | 1086  | 54.3% | 13.8%          |
| read_file   | 533   | 26.6% | 60.0%          |
| search_text | 263   | 13.1% | 12.7%          |
| list_files  | 82    | 4.1%  | 2.7%           |
| job_status  | 32    | 1.6%  | 10.9%          |
| stop_job    | 5     | 0.2%  | 0.0%           |

Per day: 09/07/26 161, 09/08/26 6, 09/11/26 69, 09/12/26 1105, 09/13/26 660

## 2. job_status polling

30 calls on 24 jobs; median 1 per job (+0), max 4 (+2).
Listings without a job_id: 2 (-48) (a habit, not a poll; run_command's synchronous result says no job was created).

## 2b. Calls per turn

143 turns, 2478 forwarded calls; calls per turn median 5, p90 39, max 188; gap between calls inside a turn median 14.0 s, p90 45.5 s. One `wfr_` id is one serial agent turn; forwarded calls include every RPC, so the total exceeds the attributed tool calls.

## 3. New-parameter uptake

`job_status.tail_lines` 30, `job_status.wait_seconds` 15, `run_command.tail_lines` 156, `run_command.wait_seconds` 268, `search_text.context_lines` 233, `search_text.line_numbers` 175

`run_command.background=true` 29 (+29)

> Zero uptake with an unchanged metric means the model never noticed the
> parameter: fix the tool description before touching code.

## 4. run_command traits

1086 run_command calls with a visible command.

| Trait          | Calls | Share of run_command | Baseline   |
| -------------- | ----- | -------------------- | ---------- |
| python-heredoc | 489   | 45.0%                | 65 (57.5%) |
| git            | 233   | 21.5%                | 16 (14.2%) |
| grep           | 68    | 6.3%                 | -          |
| hand-tail/head | 52    | 4.8%                 | -          |
| hand-head      | 36    | 3.3%                 | -          |
| ps/pgrep       | 22    | 2.0%                 | -          |
| hand-tail      | 18    | 1.7%                 | -          |
| grep-on-files  | 16    | 1.5%                 | -          |

`hand-tail` is what `run_command.tail_lines` replaces; `hand-head` (first lines) has no
parameter. `grep-on-files` counts a grep that starts a segment, not one after a pipe
(rule fixed 2026-09-13; earlier baselines used a looser rule, compare the grep line).

grep: 17 on files (+17), 74 filtering command output (+74).

## 5. read_file slices

calls 533 (+41); distinct files 205 (+184); max reads of one file 27 (-186); whole-file reads 169 (+164); median slice (lines) 123 (+97); p90 slice 271 (+31); longest same-file run 6 (-54); sequential continuations 2 (-53).

## 6. git subcommands

status 185, diff 144, log 86, commit 61, rev-parse 36, show 34, add 29, branch 7, merge 7, worktree 5, rev-list 4, tag 4, checkout 2, ls-files 1

## 7. Reading of the numbers

**Window and task shape.** 2001 ChatGPT calls, 88% of them on 09-12/13:
agentic coding on the voice-input repo (git 233 run_commands, 61 commits,
205 distinct files read). The two baselines were JSON data work (09-03) and
markdown editing (09-06), so shares are not comparable across windows;
the within-tool signals below are. 09-07 (161 calls) mixes real use with
the day's description-rewrite probes; nine unmarked probe calls (`cc-`,
`eco-`, and the skill's `setsid sleep N & sleep N; wait` stop probe) were
removed by extending the test-traffic markers this round.

**The three 2026-09-03 changes hold, measured against the pre-change
baseline (2026-09-03.json):**

- `job_status`: median polls per job 3 -> 1, max 33 -> 4, tool share
  26.6% -> 1.6%. `wait_seconds` is non-default on 15 of 30 polls, and
  `run_command.wait_seconds` is set deliberately on 268 calls (30 s x149,
  50 s x26, 10 s x49, 1 s x21 for fire-and-return with `background=true`,
  29 uses). Listings without a job_id: 50 -> 2, the 2026-09-06
  "finished synchronously; no background job" result did that.
- Hand `| tail`: 233 -> 18 (-92%); `run_command.tail_lines` non-default on
  156 calls (120/80/100/180 lines, chosen per command). The 18 that remain
  sit inside multi-section diagnostic scripts (`printf '=== x ==='; cmd |
  tail -n 20; printf ...`), one `tail` per section -- batching, which no
  parameter absorbs. The 36 `| head` are first-lines requests; nothing
  replaces them and they are the same batched shape.
- grep on files: 363 -> 16 (old rule) / 17 (occurrences); `search_text`
  1.2% -> 13.1% (263 calls, `context_lines` set on 233, `line_numbers` on
  175). The residual greps read paths outside the allowed roots
  (`/usr/include/linux/input-event-codes.h`) or are conditional logic in
  scripts (`grep -qxF '.tools/' .gitignore || printf ... >> .gitignore`).
  The 74 pipeline greps filter `printf`/`lsusb`/`ps`/`journalctl` output
  and were never addressable.
- `ps`/`pgrep`: 165 -> 22, every one on the user's own daemons (`speechd`,
  `voice-pedal`) -- not run_command jobs, so `job_status.processes` cannot
  replace them.

**The 2026-09-06/07 read_file changes hold (vs 2026-09-06.json):** max
reads of one file 213 -> 27, longest same-file run 60 -> 6, sequential
continuations 55 -> 2, whole-file reads 5 -> 169, median slice 26 -> 123
lines. No paging through large files.

**The 2026-09-07 description rewrite, measured for the first time by turn
(section 2b):** the gap between calls inside a turn fell from ~49 s to
14.0 s median (p90 45.5 s), but turn length did not shrink: median 5 calls,
p90 39, max 188 calls in one 63-minute turn on 09-12. "As few calls as
possible / stop after a step" does not bound an agent-mode turn; the model
already batches heavily (the diagnostic scripts above), so the remaining
length is the task. Per call, the server is not the bottleneck: 0 tool
errors in the window; the 09-12 connector outages (20:31-20:37, and
20:52-21:02 on the wlan0 fallback) appear as gaps in the tunnel log, not as
errors.

**What cannot move, with the counts:**

- File writes through the shell: 344 run_commands carry a recognisable
  write (lower bound; heredoc bodies are clipped at 500 chars): 147 python
  heredoc edits, 85 `cat > file <<EOF`, 44 python `write_text`/`open(w)`,
  61 `git commit`. `edit_file`/`write_file` stay hidden from ChatGPT by the
  2026-09-06 decision. The cost of that decision is now measured: 41 of
  533 read_file calls (2.0% of all calls) are verification re-reads within
  three calls of a shell write of the same file; only 30 of the 344 writes
  are followed by such a read. Small.
- git through the shell: 233 run_commands (status 185, diff 144, log 86,
  show 34, rev-parse 36). Git read tools remain deferred.
- Python heredocs that read/inspect: 287 (hashes, JSON, subprocess
  fan-out). A `run_python` tool would move them, not remove them.

## 8. Candidates, ranked by calls absorbed

No new candidate absorbs enough calls to justify a change this round.
Everything the tools could take has been taken (sections 2-5); what is
left is batching (a preference), pipelines and paths outside the roots
(by design), the user's own daemons (out of scope), and turn length (the
agent mode and the task). The deferred items keep their updated evidence:

1. Shell file writes -- 344 calls (17% of all) plus 41 verification
   re-reads. Deferred 2026-09-06 (edit tools hidden by decision); the
   re-read cost is 2%, so the decision is cheap to keep.
2. git read tools -- 233 calls (12%). Deferred since round one.
3. `run_python` -- 287 read/inspect heredocs. Deferred; would not cut
   calls.

Recommendation: no server change. Keep `2026-09-13.json` as the next
baseline; review again after a different task shape, or when a deferred
decision is reopened.

## 9. Measurement changes this round (folded into the script)

- Test-traffic markers now include `cc-`, `eco-` (word-bounded) and the
  unmarked `setsid sleep N & sleep N; wait` stop-probe shape.
- `grep-on-files` counts a grep that starts a `;`/`&&`/newline segment,
  not one after a pipe (the old rule counted `ps | grep x` as a file
  search: 67 vs the true 16).
- `hand-tail` / `hand-head` split; only `hand-tail` is what `tail_lines`
  replaces.
- `job_status` listings without a job_id and `run_command.background=true`
  are counted; older baselines derive listings from the tool totals.
- Calls per turn and inter-call gaps from the tunnel's `wfr_` turn ids
  (section 2b).

## 10. Token cost of one more tool (measured 2026-09-13, after the review)

The user's objection to every candidate in §8 is the standing cost: a
tool's definition rides in the model context on every turn of every chat
that has the connector, whether or not the turn uses it. Measured with
tiktoken `o200k_base` on the exact `tools/list` ChatGPT receives (six
tools; `name` + `description` + `inputSchema` = "core", compact JSON to
pretty JSON brackets OpenAI's unknown framing); full tables and method in
`docs/tool-cost-2026-09-13.md`.

| Quantity | Value |
| --- | --- |
| Six-tool core per turn | 1335 (compact) to 1928 (pretty) tokens; 3771 with outputSchema, annotations, title, _meta |
| Distinct ChatGPT turns, 08-29 to 09-13 | 375 (lower bound: a turn with no tool call is invisible to us), 26.8 per active day, 13.6 tool calls per turn |
| Core schema sent in the window | 500k to 723k tokens; x14.6 if the definitions are re-sent per model invocation (turns + calls = 5484) |

Marginal cost and the saving an absorbed call would bring (argument
tokens only: result text is not logged, `content_chars` measures the
one-line summary block, and output is the same text whichever tool
carries it):

| Candidate | Per turn | Cost in window | 1:1 absorbable calls | Saved per call | Saved in window | Calls per turn to break even (measured) |
| --- | --- | --- | --- | --- | --- | --- |
| `run_python` (draft) | 148 to 215 | 55k to 81k | 748 heredocs (414 more sit inside larger commands) | 8 (the `python3 - <<'PY'` wrapper) | 6.0k | 18.5 to 26.9 (2.0) |
| `write_file` exposed | 127 to 177 | 48k to 66k | 121 `cat > file` heredocs | 11 | 1.3k | 11.5 to 16.1 (0.32) |
| `edit_file` + `write_file` exposed | 319 to 447 | 120k to 168k | 121 (+ python edits, not measurable: clipped in 94% of calls) | 11 | 1.3k | 29 to 41 (0.32) |
| `git_query` (draft) | 221 to 310 | 83k to 116k | 13 single-git calls (42 pure git; 410 enumerated-subcommand calls, 64% batching two or more invocations) | -2 (the structured keys cost more than the `git` prefix) | -26 | none |

Round trips do not rescue any of them: a git-carrying call holds 2.26
git invocations on average and 293 pipe git into head/tail/grep/sed, so
a one-subcommand tool needs *more* calls; verification re-reads after a
shell write are 26 over the whole history (0.07 per turn), the ceiling on
calls a write tool could remove; `run_python` moves heredocs 1:1.

Reading: on the token axis every candidate costs 10x to 100x what it
saves, and the schema cost is paid on turns that never touch the feature.
A new tool is justified only by something this analysis cannot see --
smaller result payloads or fewer failed attempts -- which would need
result-size logging first. No candidate is recommended; the user decides.
