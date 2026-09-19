# Usage analysis, 2026-09-04 — window 2026-09-03 onward

Source: `scripts/usage_breakdown.py` over the `binnacle-mcp` journal, calls
attributed to ChatGPT via the tunnel log, nonce-marked test traffic excluded.
Baseline for deltas: `2026-09-03.json` (2026-09-01 to 2026-09-03).

## 1. Tool mix

Total tool calls: 23 (baseline 2243)

| Tool        | Calls | Share | Baseline share |
| ----------- | ----- | ----- | -------------- |
| run_command | 9     | 39.1% | 62.8%          |
| read_file   | 6     | 26.1% | 8.7%           |
| search_text | 5     | 21.7% | 1.2%           |
| stop_job    | 1     | 4.3%  | 0.1%           |
| list_files  | 1     | 4.3%  | 0.4%           |
| job_status  | 1     | 4.3%  | 26.6%          |

Per day: 09/03/26 20, 09/04/26 3

## 2. job_status polling

1 calls on 1 jobs; median 1 per job (-2), max 1 (-32).

## 3. New-parameter uptake

`run_command.tail_lines` 1, `run_command.wait_seconds` 4, `search_text.context_lines` 4, `search_text.line_numbers` 5

> Zero uptake with an unchanged metric means the model never noticed the
> parameter: fix the tool description before touching code.

## 4. run_command traits

9 run_command calls with a visible command.

| Trait          | Calls | Share of run_command | Baseline    |
| -------------- | ----- | -------------------- | ----------- |
| git            | 6     | 66.7%                | 339 (24.1%) |
| python-heredoc | 1     | 11.1%                | 651 (46.2%) |
| grep           | 0     | 0.0%                 | 367 (26.0%) |
| ps/pgrep       | 0     | 0.0%                 | 165 (11.7%) |
| grep-on-files  | 0     | 0.0%                 | 363 (25.8%) |
| hand-tail/head | 0     | 0.0%                 | 233 (16.5%) |

grep: 0 on files (-235), 0 filtering command output (-266).

## 5. git subcommands

status 5, diff 3, log 2, branch 1, add 1, commit 1

## 6. Reading of the numbers

**Too early to judge.** The window holds one real session: 2026-09-03
23:01 to 2026-09-04 00:02, in `clause-sift`, about 20 calls, one task
(rewrite a design brief, check it, commit). Three further calls
(`run_command` `sleep 40 & sleep 40; wait`, one `job_status`, one
`stop_job`) are an unmarked probe from the 2026-09-03 verification and
should be read out; the tail_lines uptake of 1 is also that probe. The
changes shipped at 20:00 on 09-03, so this is the first post-change use.

What the one session shows, with that caveat:

- **search_text was chosen five times, every time with `line_numbers=true`**
  and four times with `context_lines`: a heading outline (`^##`) and
  alternation patterns to locate terms in one markdown file. Baseline
  share was 1.2%; here 22%. No `grep` ran at all.
- **read_file with explicit line ranges** three times (the session read the
  brief in windows after each edit) — the anchored-read need from the
  first round, served by read_file this time.
- **No job polling was needed**: every command finished inside the wait.
  `wait_seconds` on job_status was not exercised by real use yet.
- **Writes still go through the shell**: one Python heredoc edit
  (`read_text`/`replace`/`write_text`) and one whole-file rewrite with
  `cat > docs/design-brief.md <<'EOF'`, followed by `git diff`,
  `pre-commit run`, and a `printf`-sectioned `git status`/`add`/`commit`
  batch. Same shape as round one: batching, and edit/write via run_command
  because edit_file/write_file are hidden from ChatGPT.
- git: 6 of 9 run_commands (status 5, diff 3, log 2, branch, add, commit),
  all in the batched form.

## 7. Candidates, ranked by calls absorbed

No new candidate from 20 calls. The list from round one stands, unchanged
in order and all still deferred by the user:

1. git read tools (`git_status`/`git_log`/`git_diff`) — 69% of 581
   baseline git invocations; this session's 6 git calls fit the pattern.
2. `read_file(revision=…)` — 67 baseline `git show rev:path` reads; none
   in this window.
3. `run_python(code)` — 655 baseline heredocs; 1 here.
4. Exposing edit_file/write_file to ChatGPT — thin in the baseline (11
   hand edits), and this session added one edit and one full rewrite via
   the shell.
5. Asymmetric context (`before_lines`/`after_lines`) on search_text — the
   grep -A/-B pattern; zero grep in this window, so no new pressure.

Recommendation: keep collecting. Re-run this report after at least a week
of real use (several sessions, more than one project) before deciding.
The one signal worth noting now is that the search_text description
rewrite appears to have worked on first contact: five uses, all with the
new parameter, zero grep.
