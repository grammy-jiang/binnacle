# `run_command` + `job_status` + `stop_job` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented (`tools/run_command.py`, `tools/job_status.py`, `tools/stop_job.py`, shared `jobs.py`); unit gate (17 tests) and the shell/jobs ChatGPT checkpoint passed 2026-08-30 — see §8 |
| **Parent** | `docs/agent-toolset-design.md` §7.4–7.6 |
| **Method** | Survey of Gemini `run_shell_command`+background tools, Codex `exec_command`/`write_stdin` (source), Copilot `bash` family (fixtures/changelog/leak), Claude Code Bash (docs/self) → decisions → spec |

These three tools share one disk-backed job model, so they are specified
together. The design was fixed in the parent doc (§5.4, §7.4): a call
waits up to `wait_seconds` (≤ 50, under ChatGPT's 60 s ceiling) and
**never kills at the wait boundary** — it hands back a `job_id`; the job
keeps running detached and survives `uvicorn --reload`.

## 1. Survey highlights

| Aspect | Gemini [source] | Codex [source] | Copilot [fixtures/leak] | Claude Code [docs/self] |
| --- | --- | --- | --- | --- |
| Timeout = kill? | **kills** at 300 s inactivity | **yields** a session id at `yield_time_ms` | **backgrounds** at `initial_wait` (sync mode) | **auto-backgrounds** at timeout |
| stdout/stderr | merged, one stream | merged, one stream | merged + `<exited with exit code N>` marker | merged |
| Truncation | 40k chars, 20/80 head/tail, spill file | 1 MiB head/tail buffer + 10k-token model cap, `… N bytes omitted …` | spill to `session-state/temp/*.txt` | 30k inline, spill to session file |
| Background id | OS PID | i32 session_id (soft cap 64, LRU-of-exited eviction) | shellId string | task id |
| Job trio | list / read / (kill via PGID) | fused into `write_stdin` poll | read_bash / stop_bash / list_bash | TaskOutput / TaskStop |
| PTY | opt-in (interactive) | opt-in (`tty` default false) | **removed** (1.0.62, "lightweight process spawning") | — |
| Env hygiene | GEMINI_CLI=1, PAGER=cat, GIT_TERMINAL_PROMPT=0, ASKPASS blanked | identity + sandbox markers, PAGER unset | login-shell env (1.0.81) | CLAUDECODE marker |
| Detach | `detached` process group; `trap 'jobs -p' EXIT` harvests stray children | own process group, parent-death signal | `setsid` for `detach:true` | detached across turns |

Cross-cutting lessons absorbed: **head+tail truncation, never head-only**
(errors live at the end); **spill-to-file** turns "truncated" into
"seekable" (here: the job log is always on disk, and `job_status` tails
it); **timeout ≠ kill**; **merged unlabeled streams** (no model needs
channel attribution); **neuter interactivity** (`PAGER=cat`,
`GIT_TERMINAL_PROMPT=0`) so commands never hang on a prompt; **PTYs cost
more than they pay** for a non-interactive server — v1 uses pipes with
stdin from the `stdin` param, no PTY.

## 2. Decisions

| Decision | From | Rejected |
| --- | --- | --- |
| Every command launches **detached** (`start_new_session=True`, own process group), stdout+stderr merged into one spool file `~/.local/state/binnacle/jobs/<job_id>/out.log`; `meta.json` at launch, `exit` written by the reaping path | Gemini/Codex/Copilot detach discipline; the parent doc's reload-survival contract | in-process `subprocess` held by uvicorn (dies on reload) |
| `run_command` waits up to `wait_seconds` (default 30, clamp 1–50) polling the spool; finishes → full result, still running → `{job_id, state: running, partial_output}` | Codex yield / Copilot initial_wait; ChatGPT 60 s cap | kill-at-timeout (Gemini) |
| `background: true` → return `job_id` after a 1 s warm-up (surfaces immediate errors) | Gemini `is_background` + `delay_ms` | fire-and-forget with no warm-up |
| Merged stream; exit metadata as structured fields (`exit_code`, `signal`, `timed_out`) | universal | separate stdout/stderr |
| Head+tail truncation at 24 000 chars per call, `[… N chars elided …]`; the **full** log always remains on disk and `job_status` tails it | Codex/Gemini/Claude; read_file's own shaping | head-only |
| Env hygiene: inherit, then set `PAGER=cat`, `GIT_PAGER=cat`, `GIT_TERMINAL_PROMPT=0`, `PYTHONUNBUFFERED=1`, `CI=1`, `BINNACLE=1`; no secret redaction (full passthrough, like Codex/Gemini defaults) | Gemini's interactivity-neutering set | PTY; secret filtering (out of scope for a single-user Pi) |
| `workdir` validated by the shared path guard | parent §7.11 | unrestricted cwd |
| No PTY, no `write_stdin` in v1 (jobs are non-interactive); `stdin` is a one-shot param | parent §9 (interactive sessions deferred) | Codex-style interactive sessions |
| `job_status`: one job (with `last_output_age_s` + `quiet` flag) or a compact recent-jobs listing; reads **only disk** | parent §7.5; Gemini's quiet-detection via inactivity; live listing-size review 2026-09-19 | in-memory job table; returning every retained job with its full command |
| `stop_job`: SIGTERM → SIGKILL after 5 s, to the **process group**, plus any descendant that left the group via `setsid()` (found through the `/proc` ppid chain before signaling) | Copilot "whole process tree" (1.0.57); Gemini group kill; measured 2026-09-06: a `setsid` child survived a group kill | single-pid kill (leaks children); killpg alone (leaks setsid children) |
| Liveness is **identity-checked**: `meta.json` records the pid's kernel `starttime` at launch and `job_state` requires it to match, so a reused pid after a reload never reads as running and `stop_job` never signals a stranger; records without it fall back to existence | pid reuse hazard (2026-09-06 probe: a record pointing at an unrelated live pid read as running) | bare `/proc/<pid>` existence |
| `stdin` is spooled to `<job>/stdin` and passed as the child's stdin **file**, never a pipe | a pipe write blocks past 64 KiB when the command never reads it, holding `run_command` until the command ends (defeats `wait_seconds`) | `Popen(stdin=PIPE)` + write |
| Output schemas declare `exit_code`, `signal` (all three tools) and `last_output_age_s` (job_status) as **nullable** (`["integer","null"]`); a running job has no exit code yet and a signal-killed one has none at all | 2026-09-07: fastmcp's strict Client rejected stop_job's result ("None is not of type 'integer'"); ChatGPT does not validate, Claude Code/Codex do; guarded by tests/contracts/test_job_schemas.py through the in-memory client | plain `integer` |
| `meta.json` is validated on read (`command, workdir, pid, started_at`) and replaced atomically via a complete same-directory temp file + `os.replace`; an incomplete external/crash record is treated as absent | 2026-09-06 malformed-record probe; 2026-09-19 concurrent reader/writer probe found in-place writes exposed invalid JSON and made idempotent concurrent stop occasionally report a real job as missing | trusting any parseable JSON; in-place truncate/write |
| Job store is global (not per MCP session) and self-pruning: the base window is the 50 newest job dirs; an older still-running job is protected outside that window. `start_job` reserves one slot and serializes prune+launch+meta so concurrent starts cannot overshoot the base cap. | Codex LRU cap; ChatGPT's per-call sessions (parent §5.3); 2026-09-19 live logs showed steady 51 from prune-before-create and a real two-start race reaching 52 | unbounded dirs; treating running jobs as part of a separate 50-job quota |
| `run_command` annotations `destructiveHint + openWorldHint`; `stop_job` `destructiveHint + idempotentHint`; `job_status` `readOnlyHint` | parent §7.12 | — |

## 3. `run_command`

**Description (ship verbatim; consolidated 2026-09-07 review):**
> Run a shell command with bash -c; several commands can go in one call
> (set -e; a && b). Waits up to wait_seconds; a command still running then
> is not killed: you get a job_id for job_status and stop_job. A command
> that finished created no job. Output merges stdout and stderr.

Division of labor (2026-09-07 review): the description states the tool's
contract only; parameter descriptions own wait_seconds/background/
tail_lines/workdir facts; workflow rules (batch into one call, checks once
at the end, never poll, keep turns short) live in the ChatGPT Project
instructions (`chatgpt-mcp-dev/references/project-instructions.txt`), the
single client in use. "Not killed" stays (timeout ≠ kill, §1); "created no
job" stays (the 50 blind job_status listings, docs/usage-analysis-2026-09-06.md).

**Input**: `command` (required), `workdir` (default `~/Projects`),
`wait_seconds` (int 1–50, default 30), `background` (bool, default false),
`stdin` (string, optional), `tail_lines` (int ≥ 1, optional; added
2026-09-03 — keep only the last N lines of output, prefixed with a
`[… K earlier lines omitted (tail_lines=N) …]` marker and `truncated:
true`; the full log stays on disk. Usage evidence: 333 hand-written
`| tail -n` / `| head -n` in ChatGPT's first week).

**Result** — finished: `{job_id, state: "exited", exit_code, signal?,
output, truncated, output_bytes, duration_s, log_path, workdir,
background_job: false}`; still running / background: `{job_id, state:
"running", output (partial), runtime_s, log_path, workdir,
background_job: true}` + summary naming `job_status`.

`background_job` and the summary tail were added 2026-09-06: a synchronous
finish appends "It finished synchronously; no background job was created,
so no job_status or stop_job is needed." Evidence: models polled
`job_status` with no job_id 50 times in a week to check whether a finished
command had left something running, always in sessions where no job existed
(docs/usage-analysis-2026-09-06.md). The running/background result keeps its
`job_status` / `stop_job` pointer.

## 4. `job_status`

**Description (consolidated 2026-09-07):** > Status of a job from
run_command, or the recent-jobs list when job_id is omitted. Only needed
when run_command returned a job_id. Call once with wait_seconds=50 to block
until the job exits instead of polling; a job still running then is not
killed. Returns state, exit code, output tail, and live processes;
quiet=true means no recent output.

**Input**: `job_id` (optional → list), `tail_lines` (int, default 100),
`wait_seconds` (int 0–50, default 0; added 2026-09-03). With
`wait_seconds > 0` the call blocks, polling disk state with an adaptive
interval (20 ms → 0.5 s), until the job exits or the time is up; a job
still running then is not killed (same wait-not-kill contract as
run_command). Evidence: 596 polls on 119 jobs, median gap 6 s.
**Result** — one job: `{job_id, state, exit_code?, signal?, runtime_s,
last_output_age_s, quiet, log_tail, log_bytes, log_path, command,
workdir, processes, waited_s?}`; a running job silent longer than 30 s is
flagged `quiet: true`. When `job_id` is omitted, the listing is compact:
all running jobs plus the newest 20 non-running jobs, preserving newest-first
order. Listing rows are `{job_id, state, exit_code, runtime_s, started_at,
workdir, command}`; `command` is a one-line 160-source-character head+tail
preview with an explicit omitted-character marker, while a single-job query
continues to return the full command. The limits are server settings
`jobs.listing_history_limit` and `jobs.listing_command_preview_chars`, not MCP
parameters. `processes` (added 2026-09-03) lists the live
members of the job's process group from `/proc` — `{pid, state, etime_s,
cpu_s, cmd}` — so the model need not run `ps -p PID` (151 such calls in
week one); empty once the job has exited. `waited_s` is present only when
a wait was requested, is measured with a monotonic performance counter, and the
summary then ends `Still running after waiting N s.` when the wait expired. Each
single-job call also emits an internal `job_status_timing` journal record with
worker-dispatch, state/wait, log-read, process-scan, and total implementation
milliseconds; no timing field is added to the MCP response.
List: `{jobs: [{job_id, state, exit_code?, runtime_s, started_at, workdir,
command}]}`, using the compact all-running + recent-history policy above.

## 5. `stop_job`

**Description (consolidated 2026-09-07):** > Stop a job (SIGTERM, then
SIGKILL after 5 s) and its whole process group. An already-finished job
returns its final state without error.
**Input**: `job_id` (required). **Result**: `{job_id, state, exit_code?,
signal?}`. Already-exited → returns the final state, no error
(idempotent). Waits for the reaper to record the exit before returning
(via `jobs.await_exit`), so a stopped job reports `state: "exited",
signal: 15`, never a transient `unknown` from reading disk before the exit
was written (2026-09-06). A job whose server died has no reaper to record
it, so stopping it returns `unknown` after the wait — honest, since its
exit code cannot be recovered.

## 6. Shared implementation (`tools/jobs.py`)

`~/.local/state/binnacle/jobs/<job_id>/` holds `out.log` (merged stream)
and `meta.json` (`command, workdir, pid, pgid, started_at, [exit_code],
[signal], [ended_at]`). Every metadata update is assembled in a unique temporary
file in the same job directory and committed with atomic `os.replace`, so concurrent
status/stop/list readers see an old complete record or the new complete record, never
a truncate/write intermediate state. Launch: `subprocess.Popen(["bash", "-c", command],
cwd, env, stdin=PIPE-or-DEVNULL, stdout=log, stderr=STDOUT,
start_new_session=True)`. Exit recording has one owner, whoever waited on
the process: a command that finishes within its wait window is recorded
inline by the run_command request thread (`record_exit`, from the
in-memory `proc.returncode`); a command that outlives the window is handed
to a background reaper thread (`reap_in_background`). So the common
synchronous case spawns no thread and cannot race its own exit.
`stop_job` and `job_status` hold no process handle, so they read what the
recorder wrote and call `await_exit` to wait through the brief window
between a process dying and its reaper writing `meta.json`. A job whose
process is gone but whose `meta.json` still lacks an exit (server killed
mid-run, no reaper left) is reported `state: "unknown"`. `job_status`
derives liveness from `/proc/<pid>` + `meta.json`. The retention base window is
`jobs.keep_newest` (50 by default). Before a launch, `start_job` atomically reserves
one slot by pruning existing non-running dirs to `keep_newest - 1`, then creates
the new job, starts the process, and writes complete launch metadata under the same
process-local store lock. Concurrent MCP calls therefore cannot share one reserved
slot. A job older than the base window is never deleted while it is still running,
so the physical store may temporarily exceed 50 only by those protected stale-running
exceptions. The compact recent-jobs listing cap is independent of disk retention.

## 7. Test checklist (tests/integration/test_jobs.py)

`run_command`: fast command → exited + exit_code 0 + merged output; stderr
merges with stdout; non-zero exit_code; `stdin` piped; workdir honored +
guard rejects outside roots; slow command exceeds a short `wait_seconds` →
running + job_id, then `job_status` shows completion; `background: true`
returns fast with a job_id; output past 24k chars truncated head+tail but
full log on disk; env hygiene (`PAGER` is `cat`); a synchronous finish sets
`background_job: false` and says so in the summary, a still-running or
background one sets `background_job: true` and points to `job_status`.
`job_status`: unknown
job_id errors; malformed `meta.json` → clean not-found, listing skips it; atomic
meta replacement remains valid under concurrent readers and leaves no temp file;
missing `out.log` on a running job → status still works (`log_bytes` 0);
`exit 143` is an exit code, not signal 15; invalid UTF-8 output is
replaced; 200 KiB unread `stdin` returns at `wait_seconds` (spool file, not
a pipe) and stdin is delivered; a `setsid` child dies with the job; a
record whose pid was reused by an unrelated live process reads `unknown`
and `stop_job` does not signal it, a matching `starttime` reads `running`,
a legacy record without one falls back to existence; a reload orphan (no
watcher) is `running` while alive, `unknown` after, and `stop_job` reports
`unknown` without inventing a signal; an unwritable spool is a clean
ToolError; `wait_seconds` above the max is clamped; two concurrent stops
both report `exited`/15. list newest-first; `quiet` flag on a sleeping job; tail
respects `tail_lines`; `wait_seconds` returns soon after the job exits, or
at the deadline with the job still running (and is capped at 50);
`processes` lists bash and its children for a running job and is empty
after exit. `run_command`: `tail_lines` keeps only the last N lines with
an omitted-lines marker, and is a no-op when the output is shorter.
`stop_job`: **corner cases (2026-09-06)** — a command that signals itself
(`kill -TERM $$` / `kill -KILL $$`) is reported exited with `signal`
15/9, `background_job:false`; `background:true` on a fast command still
reports exited, not a false running; stop escalates to SIGKILL and reports
`signal:9` when SIGTERM is ignored (grace `STOP_SIGTERM_GRACE_S`, a module
constant so tests shrink it); stop kills the whole process group so
children die; an external kill via run_command on another job is recorded
and shows through job_status exactly as a stop would (exited, signal 15);
a double stop and a stop of a job that just finished both report the same
true final state. `stop_job`: terminates a running job (group kill
reaches a child); already-exited is idempotent; unknown id errors. Reload
survival is asserted structurally (state on disk, `job_status` reads only
disk).

Property test (2026-09-13, `tests/unit/core/test_properties.py`): `clip_head_tail`
keeps exactly `limit` chars of the original plus the marker for every
text and every limit, preserving the first `limit // 2` and the last
`limit - limit // 2` characters. Found and fixed: with `limit == 0` the
tail slice `text[-0:]` returned the whole text.

## 8. Results — 2026-08-30

Unit gate: 17 tests, all pass (suite total 89) — including the yield→poll
handoff, `background:true` returning fast, head+tail truncation with the
full log on disk, env hygiene (`PAGER=cat`), group-kill reaching a child,
and idempotent stop. A `monkeypatch` on `QUIET_AFTER_S` and a
module-scoped job-store isolation fixture keep the suite hermetic.

Shell/jobs browser checkpoint (one tracked-then-deleted chat; disk +
journal as ground truth). Prompt: "start a 40-second counter, poll until
it finishes, tell me the last lines, and report CPU temperature." This is
the design's whole reason to exist — a task longer than ChatGPT's 60 s
cap:

- `run_command` hit its `wait_seconds` boundary and **yielded a
  job_id**; the counter kept running detached (confirmed on disk:
  `for i in $(seq 1 20)…`, `exit: running`, then `exit_code: 0` written
  by the reaper after the call had already returned).
- ChatGPT **polled `job_status`** three times, reading accurate progress
  (7 → 15 → 20) from the disk-backed log across separate MCP sessions,
  and reported the final tail (lines 15–20), `40.03 seconds`, exit 0.
- The Pi temperature (47.7 °C) came from a second `run_command` calling
  `vcgencmd` — validating the decision to fold Pi health into
  `run_command` rather than ship a `pi_status` tool.
- 5 `run_command` + 3 `job_status` calls, all correct. Total wall time
  ~72 s, entirely above the single-call ceiling — proving the
  wait-not-kill/poll architecture end to end.

No spec corrections. The one open item (write-confirmation dialogs not
appearing, first noted for edit_file) held here too for run_command:
worth confirming whether this connector is set to always-allow.

**Performance fix, 2026-08-31.** A benchmark showed `run_command` on a
fast command cost ~102 ms of pure tool logic while `bash -c true` itself
is ~1 ms — the whole gap was the poll loop's fixed `time.sleep(0.1)`
quantization (a fast command's first `poll()` is None, then it slept a
full 100 ms). Replaced with adaptive backoff (start 2 ms, ×1.5, cap
0.1 s): fast commands now return in ~4 ms direct / ~61 ms round-trip
(down from ~160 ms), matching the other tools; long commands still don't
busy-spin, and the yield-at-deadline behavior is unchanged (jobs gate
17/17). This was an algorithm fix, not a language issue — the earlier
"is Python slow?" question measured the language layer at 0.08–6 ms per
call; the real win was here.
