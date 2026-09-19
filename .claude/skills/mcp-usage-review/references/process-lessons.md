# Lessons from the first round (2026-09-02 to 2026-09-04)

Each item cost time once. Check them before repeating the loop.

## Measuring

- **Attribution first.** `binnacle stats` counts every client. On 08-31 the
  journal held 2,144 tool calls and the tunnel forwarded 25: local agents,
  not ChatGPT. Match request timestamps to the tunnel's "dispatcher
  forwarded command" lines (±2 s) before saying "ChatGPT does X".
- **Per-request client names exist only from 09-02 11:37** (middleware
  change). Older records need the timestamp match.
- **500-char payload clip** in the journal: 1,174 of 2,209 run_command
  payloads were cut. Heredoc bodies are mostly gone; count the visible
  program, not the script contents.
- **Rejoined wrap lines glue tokens** (`importjson`, `gitshow`). Regexes
  for programs must allow a missing space (`git\s*show`).
- **Heredoc bodies leak into program counts** (`from`, `import`, `#`)
  unless stripped first; Python loops leak `x`, `f`, `p`.
- **Test noise looks like usage**: 263 bare `true` calls on 08-31 were a
  timing test; nonce-marked e2e commands are ours. Filter both.
- **ChatGPT sends default values explicitly** (`wait_seconds: 0`,
  `tail_lines: 100`, `line_numbers: false`), so "parameter present" is not
  uptake. The 2026-09-06 draft counted 67 `job_status.wait_seconds` uses;
  the true non-default count was 5. The breakdown script now compares
  values against defaults.
- **Task shape moves the tool mix more than tool changes do.** The
  baseline was JSON data work; the 09-04/05 window was markdown editing.
  Compare within-tool signals (grep count, polls per job, parameter
  values), not shares, across windows of different work.
- **Sample before naming a category.** "grep" split 213 pipeline filters
  (on `ps`/`git` output) versus 242 file searches; only the second half
  is addressable by a search tool.

## Deciding

- **Read the current schema before proposing.** `search_text` already had
  `context_lines`; the real gap was the description and asymmetric
  context, not a missing parameter.
- **Thin evidence is thin.** "ChatGPT edits via scripts" rested on 11 hand
  edits in 1,424 calls. Say the count.
- **Batching is a preference no parameter changes.** 81% of file greps
  were one step in a multi-command shell call. A single-purpose tool
  cannot absorb those; say so instead of promising a drop.

## Implementing

- Keep spec, tests, and code in one change; the spec's test checklist is
  the test file's outline.
- Hooks: `pre-commit run --all-files` ignores untracked files, and the
  `.claude/` scripts fail ruff/bandit/mypy (system `dbus`, duplicate
  `__main__`). Run hooks on repo files by path.
- Do not hot-edit the serving instance during the user's ChatGPT session
  (2026-09-02 incident: 13 reloads in 30 min, connector marked disabled).

## Verifying

- **Discovery is not a test.** `chatgpt-refresh` proves auth and
  `tools/list`; only a chat message proves a `tools/call` round trip.
- **Nonce everything, including probes that only exercise job tools.**
  Without it a cached or earlier reply is indistinguishable from a new
  one, and test traffic pollutes the next measurement. On 2026-09-03 the
  process-list probe (`sleep 40 & sleep 40; wait`) had no nonce, so its
  run_command, job_status, and stop_job counted as real use in the
  09-04 test report. Follow-up calls carry only a `job_id`; the breakdown
  script now drops them when the job's `job_start` command was marked,
  but only if the starting command had the marker.
- **ChatGPT inter-call latency is 5 to 11 s.** A `wait_seconds` probe on
  an 8 s job returned `waited_s: 0.0` because the job had already ended;
  use a 40 s job.
- **A 37 s blocking tool call is fine** within ChatGPT's 60 s cap.
- **Right after a tunnel restart, ChatGPT returns HTTP 424** for a few
  seconds; `chatgpt-refresh` now retries. The tunnel caches the token at
  startup, so a rotation must restart it.
- `chatgpt-send`'s reply reader races the streaming DOM; it tolerates a
  missing node now, but if it fails, the reply is still in the
  conversation via `/backend-api/conversation/<id>`.

## Recording

- Put the round's numbers in `docs/usage-analysis-<date>.md` and the
  machine baseline in `docs/usage-baselines/<date>.json`; the doc's
  narrative regexes and the script's regexes differ, so compare script to
  script.
- Note what the user deferred (git tools, `read_file(revision)`,
  `run_python`, hiding `search_text`) so the next round does not re-argue
  it.

## Third round (2026-09-13)

- **Every probe needs a marker from `TEST_MARKERS`, and the list must know
  every prefix in use.** Hand-typed nonces `cc-001141` and `eco-164922`
  and the skill's own stop probe (`setsid sleep 40 & sleep 40; wait`, no
  nonce at all) counted as real use for a week; nine calls on 09-07. The
  script now bounds the new prefixes (`gcc-14` is not `cc-`) and matches
  the probe shape. When you invent a nonce, add its prefix to the script
  in the same change.
- **Splitting on `|` turns a pipeline filter into a "file search".** The
  `grep-on-files` trait said 67; the honest count was 16. Segment
  boundaries for "what command is this" are `;`, `&&`, newline -- never
  the pipe.
- **A crashed patch script does not stop the shell.** A `re.subn`
  replacement with `\w` raised, nothing was patched, and the driver then
  saved a baseline from the unfixed script. Chain regeneration behind
  `set -e`, and use `str.replace` with exact anchors for source edits.
- **Turn length lives in the tunnel log, not the journal.** `cmd_request_id`
  is `wfr_<turn>/<call>`; one id is one serial agent turn (188 calls in
  63 min). Go trims trailing zeros in its RFC 3339 fractions, so parse the
  timestamp with a tolerant regex, not fixed slicing.
- **"Fewer calls per turn" is not something a description bounds.** The
  09-07 rewrite cut the gap between calls 3.5x but turns got longer with
  the task (agent mode). Report per-call latency and calls per turn as two
  numbers; only the first is the server's.
