# What ChatGPT actually calls — usage analysis, 2026-08-29 to 2026-09-03

Source: the `binnacle-mcp` user journal (all `tools/call` payloads, clipped
at 500 chars) and the tunnel client's log. A request is attributed to
ChatGPT when its timestamp matches a tunnel "dispatcher forwarded command"
line within two seconds; everything else is a local agent (Codex, Claude
Code, Copilot CLI) or a test client. Test traffic (`scripts/mcp_client.py`,
nonce-marked end-to-end runs, and the 263 bare `true` calls of 08-31) is
excluded from the run_command breakdown.

## 1. Tool mix

| Tool        | ChatGPT (2,335 calls) | Local agents (1,617 calls) |
| ----------- | --------------------: | -------------------------: |
| run_command | 1,429 (61.2%)         | 792 (49.0%)                |
| job_status  | 603 (25.8%)           | 0                          |
| read_file   | 215 (9.2%)            | 266 (16.5%)                |
| search_text | 34 (1.5%)             | 263 (16.3%)                |
| list_files  | 16 (0.7%)             | 263 (16.3%)                |
| stop_job    | 4 (0.2%)              | 0                          |

ChatGPT reaches for the shell for almost everything; the local agents use
the structured file tools ten times more often. edit_file and write_file
are hidden from ChatGPT; the local agents, which see them, used write 3
times and edit_file never.

## 2. What ChatGPT's 1,424 run_command calls do

A command can fall into several categories (most chain several programs
with `&&` or `;`).

| Intent                                  | Calls | Share | Programs                                               |
| --------------------------------------- | ----: | ----: | ------------------------------------------------------ |
| Run an inline Python script (heredoc)   | 655   | 46%   | `python3 - <<'PY'`                                     |
| Read a file or a slice of one via shell | 500   | 35%   | `sed -n 'a,bp'` 189, `head`/`tail -n` 333, `cat`, `nl` |
| Print section headers into the output   | 363   | 26%   | `printf`, `echo`                                       |
| Search via shell                        | 363   | 26%   | `grep` 435 uses, mostly `-n` and `-A/-B` context       |
| Git, read-only                          | 337   | 24%   | `status` 179, `log` 100, `diff` 116, `show` 32+        |
| Write a file via shell                  | 171   | 12%   | `cat > f <<EOF`, `> /tmp/x.log`                        |
| Poll or kill processes                  | 151   | 11%   | `ps -o ... -p PID`, `pgrep`, `kill`                    |
| Run a project script                    | 67    | 5%    | `python3 tools/*.py`                                   |
| List via shell                          | 50    | 4%    | `ls`, `du`, `find`                                     |
| Git, writing                            | ~30   | 2%    | `add`, `commit`, `fetch`                               |

Details behind the rows:

- **Python heredocs** are almost all data work on the target project
  (`python-migration-atlas`): `json` appears in 605 scripts, `pathlib` in
  385, `glob` in 371, `subprocess` (wrapping git) in 126. Only 11 scripts
  edit a file by `read_text()` / `replace()` / `write_text()`; that is the
  entire "ChatGPT edits via scripts" evidence.
- **Reading via shell** happens even though read_file exists, because the
  read is combined with something read_file cannot do: 32 reads are
  `git show <rev>:<path> | sed -n 'a,bp'` (a file at a git tag), and most
  others are the tail of a log or the output of a pipeline.
- **grep via shell** outnumbers search_text 435 to 34. The grep calls ask
  for `-n` line numbers and `-A/-B` context on every match; search_text
  gives auto-context only when there are at most three matches.
- **head/tail -n** appears 333 times: ChatGPT truncates its own output to
  stay under the response cap instead of asking the tool to.
- **Process polling** is ChatGPT checking the children of a job it
  started (a `git fetch`/`index-pack` inside a background clone) with
  `ps -p PID` and `pgrep`, because job_status reports the job, not its
  process tree.

## 3. job_status polling

596 polls on 119 distinct jobs. Median 3 polls per job, 18 jobs polled ten
or more times, one job polled 33 times in three minutes. Median gap
between polls 6 s; 108 gaps under 5 s. Every poll is a full ChatGPT →
tunnel → server round trip and a model turn.

## 4. Candidate tools and parameters, ranked by calls they would absorb

Items 1 to 3 shipped on 2026-09-03 (specs: `docs/tools/run_command.md`
§3–4, `docs/tools/search_text.md` §3) and passed the browser pass test
the same evening: from the test chat, one `job_status(wait_seconds=50)`
call blocked 36.5 s and returned the finished 40 s job (previously six or
more polls); `processes` listed bash and both `sleep` children of a job;
`run_command(tail_lines=3)` on 100 lines returned the omitted-lines
marker plus the last three; `search_text(context_lines=2,
line_numbers=true)` returned the numbered context block. A 37 s tool call
sits comfortably inside ChatGPT's 60 s client cap. Item 3 turned out to
be mostly a description problem: `context_lines` already existed, and of
ChatGPT's 478 grep segments, 235 filter `ps`/`git` output in a pipeline,
which no file-search tool can absorb; `line_numbers` and the grep-aware
description target the other 243.

1. **`job_status(wait_seconds=…)`** — block up to 50 s until the job
   exits or the time is up (same wait-not-kill contract as run_command).
   Absorbs most of the 596 polls; the model waits once instead of
   looping. Add a `processes` field listing the job's process group
   (`pid`, `etime`, `%cpu`, `cmd`) to absorb the 151 `ps`/`pgrep` calls.
2. **`run_command(tail_lines=…)` or `max_output_chars=…`** — let the
   model ask for the last N lines instead of piping through `tail`;
   333 calls did that by hand.
3. **`search_text(context_lines=…)`** — explicit before/after context on
   every match, with line numbers, as grep gives it. Targets the 363 grep
   calls; today search_text is used 34 times.
4. **`run_python(code, workdir)`** — the 655 heredocs as a first-class
   tool: code arrives as a JSON string, so no heredoc quoting, no shell
   escaping, and the full script is visible in the journal (today 1,174
   of 2,209 payloads are clipped at 500 chars). Same job machinery.
5. **`revision` parameter on read_file (and search_text)** — read a file
   at a git ref; absorbs the `git show rev:path | sed -n` pattern (32).
6. **Structured git reads** (`git_status`, `git_log`, `git_diff`) — 337
   calls, but plain `git` in the shell already works well; lower value
   than the items above unless output size becomes the problem.

Not supported by the data: exposing edit_file to ChatGPT (11 hand edits
in 1,424 calls). The `printf`/`echo` section headers (363) are a symptom
of many commands per call, not a tool gap.

## 5. Git in detail (ChatGPT)

581 git invocations inside 315 run_command calls (22% of ChatGPT's
calls; 170 of those calls run git two to six times). 92% are read-only.
A further 34 calls drive git from Python `subprocess` inside heredocs.

| Subcommand                                   | Calls | Share | Dominant form                                                    |
| -------------------------------------------- | ----: | ----: | ---------------------------------------------------------------- |
| status                                       | 171   | 29%   | `git status --short` (157 of 171)                                |
| diff                                         | 124   | 21%   | `--check` 30, `--cached` 27, `--stat` 23, `--name-only`          |
| log                                          | 103   | 18%   | `git log --oneline -5..-8` (nearly all)                          |
| show                                         | 89    | 15%   | `git show <tag>:<path>` 67 of 89 (a file at a tag, cpython repo) |
| commit                                       | 26    | 4%    | `commit -m`                                                      |
| add                                          | 15    | 3%    | `add -A` 8                                                       |
| ls-tree, tag, grep, rev-list, config, others | 53    | 9%    |                                                                  |

Post-processing: 176 of the 581 invocations (30%) pipe git into `head`,
`grep`, `sed`, `tail`, or `nl` to trim or locate output. The hand-written
ranges on `git show` (`| sed -n '1,240p'`, then `'241,520p'`) are the
same windowing read_file already does.

Reading: a small structured **`git_status` / `git_log` / `git_diff`**
would cover 398 of 581 invocations (69%) with three tools and fixed,
compact output, and `read_file(revision=…)` (item 5 above) would cover
the 67 `git show <rev>:<path>` reads. The write side (commit, add) is
8% and is better left to the shell, where the model already composes the
message and the pathspec.

## 6. grep inside run_command versus search_text (ChatGPT)

455 grep invocations in 368 of ChatGPT's 1,424 run_command calls (26%),
against 35 search_text calls in the whole window: seven to one on file
searches alone.

| grep use | Invocations |
| --- | ---: |
| filtering another command's output in a pipeline (`ps` 96, `git` 56, `nl`, `sed`) | 213 |
| searching files directly | 242 |

Anatomy of the 242 direct file searches:

- `-n` on 204 (84%); `-A` on 79 and `-B` on 75; `-R` over a directory on
  38; `-c` count-only on 15; `-E` on 33; `-i` on 6. No alternation
  patterns, three anchored patterns.
- Context windows are **asymmetric**: 48 of 55 with context use different
  `-A` and `-B`. `-A` runs 18 to 180 lines (median about 40); `-B` runs
  4 to 20 (median about 10). That is "find the definition, then read
  forward", a read anchored at a pattern, not a symmetric search hit.
- Targets, where visible: a single file 88 times (mostly `.py`), a
  directory 75 times, several files 12 times.
- **81% (196) are one step of a multi-command call**, batched with
  `printf` section headers (109), `set -e` (86), `git` (61), `sed` (38),
  `python3` (25), `tail` (24). Only 46 greps were the whole call.

search_text's 35 calls: 23 in python-migration-atlas on 09-02, 8 in
binnacle, 2 in clause-sift, 2 test. Parameters used: `max_results` 31,
`context_lines` 29, `glob` 11, `names_only` 2, `fixed_strings` 2. Half
targeted a single file, half a directory. Typical jobs: list test
functions across a repo (`glob` + `names_only`), outline a markdown file
(`^#{1,3}`), locate a constant in an unfamiliar repo.

Chronology: the first 209 file greps ran with zero search_text calls
(09-01 15:00 to 09-02 09:00). From 09-02 10:00 the two interleaved in the
same project and hours (10:00: 26 grep, 4 search_text; 11:00: 24 and 19),
so the model knows the tool and picks per situation.

Reading of the preference:

1. **Batching wins.** The dominant shape is one shell call that prints
   headers, runs git, greps, and tails, answering several questions in
   one round trip. search_text answers one question per call and cannot
   sit inside that script. This is the main reason, and no parameter on
   search_text changes it.
2. **Anchored forward reads.** `grep -n -A40 -B10 "def x" file.py` is a
   read starting at a pattern. search_text has only a symmetric
   `context_lines` (max 100). A `before_lines`/`after_lines` pair, or an
   `anchor` pattern on read_file, would fit this use directly.
3. **Filtering command output** (213) is not a file search at all and is
   out of scope for search_text.
4. search_text is chosen for repo-wide structural queries (test
   inventories, outlines) and for unfamiliar repositories, where its glob
   and names_only modes beat grep.

The 2026-09-03 description rewrite and `line_numbers` address the
"model did not think of it" share; they do not address items 1 and 2.

## 7. Caveats

- Payloads are clipped at 500 chars in the journal; program counts come
  from the visible prefix. Rejoined wrapped lines lose some spaces
  (`importjson`), which affects token-level counts, not program counts.
- Attribution by timestamp is approximate at the second level; on the
  two busy ChatGPT days (09-01, 09-02) it agrees with the tunnel's own
  totals to within a few percent.
