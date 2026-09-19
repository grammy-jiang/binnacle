# Usage analysis, 2026-09-06 — window 2026-09-04 onward

Source: `scripts/usage_breakdown.py` over the `binnacle-mcp` journal, calls
attributed to ChatGPT via the tunnel log, nonce-marked test traffic excluded.
Baseline for deltas: `2026-09-03.json` (2026-09-01 to 2026-09-03).

## 1. Tool mix

Total tool calls: 820 (baseline 2243)

| Tool        | Calls | Share | Baseline share |
| ----------- | ----- | ----- | -------------- |
| read_file   | 492   | 60.0% | 8.7%           |
| run_command | 113   | 13.8% | 62.8%          |
| search_text | 104   | 12.7% | 1.2%           |
| job_status  | 89    | 10.9% | 26.6%          |
| list_files  | 22    | 2.7%  | 0.4%           |
| stop_job    | 0     | 0.0%  | 0.1%           |

Per day: 09/04/26 554, 09/05/26 266

## 2. job_status polling

39 calls on 32 jobs; median 1 per job (-2), max 2 (-31).

## 3. New-parameter uptake

`job_status.tail_lines` 73, `job_status.wait_seconds` 5, `run_command.tail_lines` 7, `run_command.wait_seconds` 15, `search_text.context_lines` 77, `search_text.line_numbers` 88

> Zero uptake with an unchanged metric means the model never noticed the
> parameter: fix the tool description before touching code.

## 4. run_command traits

113 run_command calls with a visible command.

| Trait          | Calls | Share of run_command | Baseline    |
| -------------- | ----- | -------------------- | ----------- |
| python-heredoc | 65    | 57.5%                | 651 (46.2%) |
| git            | 16    | 14.2%                | 339 (24.1%) |
| grep           | 0     | 0.0%                 | 367 (26.0%) |
| hand-tail/head | 0     | 0.0%                 | 233 (16.5%) |
| ps/pgrep       | 0     | 0.0%                 | 165 (11.7%) |
| grep-on-files  | 0     | 0.0%                 | 363 (25.8%) |

grep: 0 on files (-235), 0 filtering command output (-266).

## 5. git subcommands

status 15, diff 11, log 8, commit 6, add 3, show 2, branch 1

## 5b. read_file slices (baseline for the 2026-09-06 change)

calls 492; distinct files 21; max reads of one file 213; whole-file reads
5; median slice 26 lines; p90 slice 240; longest same-file run 60;
sequential continuations 55. Saved as `docs/usage-baselines/2026-09-06.json`
(`read_file` block); later reports print this line with deltas.

## 6. Reading of the numbers

**Window**: 2026-09-04 00:01 to 2026-09-05 15:21, 820 ChatGPT calls in 14
sessions, all in `clause-sift`, all one kind of work: writing and revising
five markdown design documents (design.md 462 lines, architecture.md 878,
workflows.md 952, tech-stack.md 428, design-brief.md 160). None of it is
test traffic. The baseline was a different kind of work (JSON data
pipelines in `python-migration-atlas`), so the **tool-mix shift is mostly
the task**, and only within-tool signals are comparable. Those are clear.

### What the three changes did

- **search_text replaced grep.** grep inside run_command: 0 (baseline 367
  uses in 1,415 calls). search_text: 104 calls, 12.7% of traffic (baseline
  1.2%), 88 with `line_numbers=true`, 77 with `context_lines`, 23 with
  `glob`, every one over the `docs/` directory with alternation patterns
  (`edition|lifecycle|status|...`) or a heading outline (`^##`). The
  description rewrite worked on first contact and held for two days.
- **Hand-written `| tail`/`| head` vanished**: 0 (baseline 233).
  `tail_lines` was used 7 times on run_command and 73 job_status calls set
  a non-default `tail_lines`. `ps`/`pgrep`: 0 (baseline 165).
- **job_status polling collapsed**: 39 calls with a job id on 32 jobs,
  median 1 per job, max 2 (baseline median 3, max 33, 591 polls on 117
  jobs). Part of this is the task (fewer long jobs), but the blocking path
  was used: `wait_seconds` > 0 on 5 job_status calls, and run_command
  itself carried `wait_seconds` 30 or 50 on 15 calls. Nothing was
  stopped; no job needed more than two looks.

A measurement correction found in this round: ChatGPT sends default
values explicitly (`wait_seconds: 0`, `tail_lines: 100`,
`line_numbers: false`). The first draft of this report counted them as
uptake (67 for `job_status.wait_seconds`); the script now counts only
non-default values (5). The lesson is in the skill's reference file.

### New patterns, from the task shape

1. **Tiny-window re-reading.** 492 read_file calls, 487 with an explicit
   line range, on only 21 distinct files; median span 26 lines, p90 240;
   design.md alone was read 213 times, and one session read a single file
   60 times in a row (47 of those continuing exactly where the previous
   range ended). read_file allows 2,000 lines and 24k chars per call, so
   this is model habit (read a slice, edit, re-read to verify), not a tool
   limit. It is 60% of all calls in the window.
2. **Editing through the shell**: of 113 run_command calls, 26 are Python
   heredocs doing `read_text` / `replace` / `write_text`, 18 are
   `cat > file <<'EOF'` whole-file rewrites, 5 more redirect output into a
   file — 49 write operations (43% of run_command) done by hand because
   edit_file and write_file are hidden from ChatGPT. In the baseline this
   was 11 of 1,424; the evidence that decided to hide the edit tools no
   longer holds for document work. The 39 non-edit heredocs are checks
   (line counts, heading lists, moving files).
3. **job_status listings**: 50 calls with no job id, preceded most often
   by read_file (20) or run_command (14) and followed by another
   job_status (20). The model checks "what is running" as a habit, even
   though nothing was; 6% of the window's calls.

## 7. Candidates, ranked by calls absorbed

1. **Expose `edit_file` (and `write_file`) to ChatGPT** — 49 shell writes
   in 113 run_commands here, plus the verify re-reads that follow each
   edit (edit_file returns a context snippet). Config only:
   `client_tools` for `openai-mcp`, then a connector refresh. Cannot fix
   the model's preference for batching, but each hand edit today is a
   heredoc with quoting risk and a clipped journal record. Previously
   deferred on thin evidence; the evidence is no longer thin for document
   work.
2. **Curb the tiny-window re-reads** — 492 calls. Two cheap levers: state
   the file's total line count and the allowed window in read_file's
   result and description ("you can read up to 2,000 lines at once"), and
   return an edit snippet from edit_file so the verify read is
   unnecessary (item 1). Cannot fix a model that prefers small slices, but
   today nothing tells it the slice can be larger.
3. **job_status listings** — 50 calls. Say in run_command's result when a
   command exited that no jobs are running, or drop the "Call job_status
   without a job_id to list recent jobs" hint from success paths. Small
   and speculative; measure again first.
4. Still deferred from round one, unchanged: git read tools (16 git
   calls here, 339 in the baseline), `read_file(revision)` (0 here),
   `run_python` (65 heredocs here, 39 of them non-edit checks),
   asymmetric search context (no grep here to motivate it).

Recommendation: item 1 now, since it is a one-line config change and
reversible; item 2's description change alongside it; hold 3 and 4.

## 9. Decisions and what shipped (2026-09-06)

- **Item 1 (expose edit_file/write_file): declined.** The user's earlier
  decision, made on the static analysis, stands; not re-opened.
- **Item 2 (read_file window): shipped.** The description no longer says
  "start narrow"; it states the 2,000-line / 24k-char window and says to
  omit the range for a file that fits. A partial, untruncated read of such
  a file now returns `fits_in_one_call: true`, a note, and a summary
  sentence. Spec `docs/tools/read_file.md` §4.1/§4.4/§5; four new tests.
  Compare on the `read_file` line of the next report against the 09-06
  baseline: median slice, max reads of one file, whole-file reads, longest
  same-file run.
- **Items 3 and 4: no change**, by the user's decision.
