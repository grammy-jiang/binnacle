# Compact `job_status` recent-jobs listing — usage analysis, 2026-09-19

## Scope

This review addresses only `job_status()` when `job_id` is omitted. Single-job
status/wait/process/log behavior is out of scope. Per-call structured-size telemetry
is usable from 2026-09-13 onward; older analysis is retained for usage-frequency
context.

## Evidence

After the 2026-09-06 result/description change, blind no-id listings fell sharply
(from 50 in the earlier document-editing window to 2 in the 2026-09-13 review).
They are now low-frequency, but a listing is expensive when it occurs. From
2026-09-13 through this review there were 9 sized no-id listings:

- structured bytes: min 8,681; median 77,313; max **187,758**;
- combined structured bytes: **773,724**;
- combined chars/4 estimate: **192,304 tokens**;
- returned rows were normally 51, with one 52-row result.

The current live store confirms the dominant field. With 51 jobs the full listing
was about 33 KiB; command strings accounted for roughly three quarters of the
payload. In an earlier snapshot of the same analysis they were 20,134 of 26,735
bytes (75.3%). Current command lengths include multi-kilobyte shell/heredoc bodies.
The listing is therefore shipping execution source rather than job identity.

## What ChatGPT actually selected after a listing

Within the nine sized listing turns, 15 later `job_status`/`stop_job` targets were
observed. Five of those jobs were created only *after* the listing and therefore
cannot be evidence for listing usefulness. The remaining **10 real selections**
were all present when the listing ran:

- 5 were running;
- 5 were non-running recent history;
- every selected existing job had at most 15 newer job starts ahead of it.

This rules out a simple "running jobs only" listing: the model sometimes needs a
recent completed job. It also shows that returning ~50 historical rows is not
supported by observed use. A 20-job history leaves a buffer beyond every observed
non-running selection while all running jobs remain unconditional.

Across the retained 14-day journal the maximum tracked concurrent running-job count
was **10**. Thus the observed worst row count under "all running + 20 history" is
about 30, not 50+.

## Candidate representation

For a no-id listing:

1. Start from `jobs.list_jobs()` (newest first).
2. Keep **every `state == running` job**, regardless of age.
3. Keep at most the newest **20 non-running** jobs (`exited` or `unknown`).
4. Preserve their original newest-first relative ordering.
5. Return `job_id`, `state`, `exit_code`, `runtime_s`, `started_at`, **`workdir`**,
   and `command`.
6. `command` becomes a **160-character source-content head+tail preview** with an
   explicit omitted-character marker when truncated; newlines are represented as
   `\n` for compact one-line identification.

`workdir` is added because project identity becomes more important once a long
command is intentionally compacted. The `jobs` output item schema is already a
generic object, so this adds no schema definition or MCP input cost. Single-job
`job_status(job_id=...)` continues to return the complete command and workdir.

On the live job store, this candidate produced about **7.7 KiB / 2,488 exact
`o200k_base` tokens**, versus ~33 KiB for the current full listing. A plain first-160
preview was tested, but head+tail distinguished at least one pair of otherwise
colliding same-workdir commands and is therefore preferred for the same content
budget.

## Decision

Use internal defaults:

- `jobs.listing_history_limit = 20`;
- `jobs.listing_command_preview_chars = 160`.

Do not add MCP input parameters. Do not change the public tool description: it
already says "recent-jobs list", which remains accurate. Add an internal
`event=job_listing` journal record carrying the correlated call id, total recorded
jobs, returned jobs, running jobs, history limit and command-preview size. Existing
`tool_result` telemetry continues to provide the actual structured bytes.

## Adjacent issue deliberately not folded into this change

`start_job()` currently calls `_prune()` *before* creating the new job. With
`KEEP_NEWEST=50`, a normal steady-state store can therefore contain 51 dirs after a
launch; older running jobs skipped by pruning can raise it further (a historical
listing contained 52). This explains the observed count but is not the primary
payload cause and changes job-retention semantics, so it is recorded for a separate
maintenance round instead of being mixed into listing compaction.

## Implementation validation

The change was implemented in an isolated snapshot of the live server after the
`search_text` result-budget deployment, so the previous production fix is part of
this round's baseline. Production files were not changed during development.

Validation results:

- compact-listing tests: **6/6 passed on Python 3.10, 3.11, 3.12, 3.13 and 3.14**;
- complete `tests/integration/test_jobs.py`: **62/62 passed** when pointed at an isolated
  `/tmp` job store;
- final Python 3.13 full project suite: **555 passed**;
- project branch coverage: **88.26%** against the 86.9% gate;
- `src/binnacle/tools/job_status.py` branch coverage: **99.09%**.

Using the real live 51-job store during replay, the pre-change representation was
50,891 compact JSON bytes. The implemented representation returned 21 rows (all
running + 20 non-running) in 7,220 bytes; every running job was present, every row
included `workdir`, and 14 long commands carried explicit head+tail truncation
markers. Earlier candidate tokenization on the live store measured roughly 2.5k
`o200k_base` tokens, versus historical no-id listings as high as ~46k estimated
tokens.

The jobs test suite initially reproduced the existing `test_concurrent_stops_agree`
race while the snapshot and production server shared the default global job spool.
Rerunning that test alone passed. Pointing the snapshot at its own job directory
removed the interference and the complete 62-test jobs suite passed; all final
full-suite evidence therefore uses an isolated job store.

## Production integration

The verified change was copied to the live `binnacle` tree on 2026-09-19 only
after every existing target file matched the research baseline byte-for-byte. A
rollback copy was created at
`/tmp/binnacle-before-compact-job-listing-20260919T101058`. WatchFiles performed
one normal reload and the live compact-listing tests passed 6/6. The runtime
tool signature and description were unchanged, so no connector refresh was
required.

A real ChatGPT `openai-mcp` no-id `job_status` call provided the production
checkpoint: 51 jobs were recorded, 21 were returned (1 running + 20 non-running),
all rows carried `workdir`, and 14 commands were previewed. The journal recorded
`event=job_listing call=a2c3b5e6bfb1 recorded_jobs=51 returned_jobs=21
running_jobs=1 history_limit=20 command_preview_chars=160`; the matching
`tool_result` had `structured_bytes=7219`, `est_tokens=1813`, and duration 8.81 ms.
This closes the production gate.
