# E4 — Long-running job contract v1 (FROZEN)

Status: **FROZEN 2026-09-29.** Supersedes `e1-contract-draft.md`. Resolves every BLOCKER and CHANGE in
`e2-compat-review.md` (E2) and `e3-adversarial-review.md` (E3); the resolution table is §9.
Round 3 implements exactly this document. A change to it needs a new E4 revision, not a lane decision.

## 1. Principle

A long-running job is owned by Binnacle and identified by `job_id`. **Once a caller has observed a `job_id`**,
any later tool call, from any turn or conversation, can read its lifecycle and all of its output that is
still retained, in bounded chunks, without server-side delivery state. Waiting inside one ChatGPT turn is an
optimization; nothing depends on it. Recovery is bounded by the job store's retention (§5.6).

## 2. What does not change

| Surface | Unchanged |
| --- | --- |
| `run_command` | Inputs, outputs, wait and handoff rules. |
| `job_status` without `cursor` | **Byte-for-byte the current payload** (with the Lane B hard cap, §7.1): same fields, same `log_tail`, same listing mode. No new field appears. |
| `stop_job` | Inputs, outputs, TERM→KILL, idempotence. |
| Lifecycle | `state` ∈ `running` \| `exited` \| `unknown`; `exit_code`, `signal`. No new state. |
| Store | `meta.json` + append-only `out.log`; retention and pruning rules; no rotation. |
| Visibility | `client_tools` unchanged; every client that sees `job_status` gets the new argument. |

## 3. Cursor mode: `job_status(job_id, cursor=...)`

### 3.1 Input

| Argument | Type | Meaning |
| --- | --- | --- |
| `cursor` | string, optional, last parameter | `"start"` = read from byte 0. `"end"` = start at the current end (explicitly skips existing output). Otherwise a value returned earlier as `next_cursor`. |

- `cursor` requires `job_id`; `cursor` without `job_id` is an input error (checked before listing mode).
- In cursor mode `tail_lines` is ignored. `wait_seconds` keeps its meaning (wait until exit or deadline, then read).

### 3.2 Cursor value

`next_cursor` has the form `v1:<job_id>:<offset>`, where `offset` is a decimal byte offset into that job's
`out.log`. Callers treat it as opaque. The server rejects, with a tool error:

- a malformed value, or an unknown version prefix;
- a cursor whose `<job_id>` differs from the `job_id` argument (`cursor belongs to job <x>, not <y>`) — E3-3;
- an offset greater than the current spool size (`cursor beyond end of output`).

A future rotation or replacement of `out.log` must introduce a new version prefix (for example with a generation)
before it ships; a `v1` offset is never applied to replaced content.

### 3.3 Output (cursor mode only)

| Field | Meaning |
| --- | --- |
| `log_delta` | Text for bytes `[delta_start, delta_end)` of `out.log`, decoded per §4. No elision marker. |
| `delta_start`, `delta_end` | Byte range this response covers. A retry that returns the same range is the same delivery (E3-5). |
| `next_cursor` | `v1:<job_id>:<delta_end>`. Pass it as `cursor` next time. |
| `has_more` | `true` when another non-empty `log_delta` is readable **now** from `next_cursor`. `false` means caught up at this read, not that the job is complete. |

`log_tail` is omitted in cursor mode. All lifecycle fields (`state`, `exit_code`, `signal`, `runtime_s`,
`last_output_age_s`, `quiet`, `log_bytes`, `processes`, wait fields, `command`, `workdir`, `log_path`) are
returned as today. **`quiet` says nothing about unread output**; only `has_more` and the cursor do (E2-B3).

## 4. Byte and UTF-8 rules (E3-2, E2-B4)

1. Chunk size `C = max(4, jobs.max_output_chars)` bytes. A read covers at most `C` bytes from the cursor
   offset, so `log_delta` has at most `C` characters. `max_output_chars <= 0` therefore cannot stall a cursor.
2. **Mid-chunk boundary.** If the chunk ends inside a valid multi-byte UTF-8 sequence and the sequence's
   remaining bytes are already in the spool, `delta_end` moves back to the start of that sequence (at most 3
   bytes). Because `C >= 4`, every chunk with readable bytes consumes at least one character.
3. **Pending suffix.** If the unread bytes at the end of the spool are a valid but incomplete UTF-8 prefix
   (1–3 bytes) and the job's `state` is `running`, those bytes are **pending**: not returned, not counted by
   `has_more`. They are returned once completed by later output, or flushed by rule 4.
4. **Terminal flush.** When `state` is not `running`, pending bytes are consumed and decoded with replacement
   (U+FFFD), so a finished job always drains to `has_more=false`.
5. **Invalid bytes** anywhere else are consumed and decoded with replacement; they never block progress.
6. `has_more` is computed after rules 2–4: true iff unread, non-pending bytes remain after `delta_end`.

## 5. Behavior rules

1. **Reseeding (E3-1, E2-B1).** A turn that holds only a `job_id` uses `cursor="start"` for full history, or
   `cursor="end"` to follow from now (an explicit skip). Tail mode never mints a cursor.
2. **Draining.** A caller has all retained output when `state` is not `running` and `has_more` is `false`.
3. **`unknown` (E3-9).** `unknown` means the recorded process is gone without an exit record. The cursor treats it
   as not running (rule 4.4 applies). In the managed owner mode this host runs, an interrupted job is finalized as
   `exited` by owner recovery; the v1 durability guarantee is stated for managed mode. In legacy embedded mode an
   `unknown` job's descendants may still write: a later read then returns the new bytes normally.
4. **Duplicates.** The server keeps no delivery state. Re-reading a cursor returns the same `[delta_start, …)`
   range (plus bytes appended since, up to `C`). Callers de-duplicate by range.
5. **Concurrent jobs.** Each cursor names its job; mixing them is an error (§3.2).
6. **Retention (E3-11).** A cursor does not extend retention. A cursor for a pruned job gets the existing
   `No job with id` error. Recovery is guaranteed only while the job is retained.
7. **Read/prune atomicity (E3-12).** A cursor read opens `out.log` once and reads from that open file. If the job
   is missing at open, the call fails with the `No job with id` error. A cursor read never returns an empty
   success because a file disappeared, and never falls back to the whole-log helper's `OSError → b""` behavior.
8. **Lost start response (E3-4).** If a turn loses the `run_command` result before seeing `job_id`, v1 offers
   only the existing listing (`job_status()` without `job_id`). Create idempotency is out of scope (§8).
9. **Unsupported extensions.** v1 needs only ordinary stateless tool calls. No MCP elicitation, Tasks, SSE, or
   session-held state (Lane D).

## 6. Descriptions

- `job_status` tool, one sentence added: "For complete output across turns, pass `cursor` ("start", or the
  `next_cursor` you got) to read unseen output in bounded chunks until `has_more` is false."
- `cursor` parameter: "\"start\" reads from the beginning, \"end\" from now; otherwise the `next_cursor` from
  your last cursor call for this job."

## 7. Implementation constraints (from E2)

1. **Hard cap first (E2-C1).** Round 3 branches from `feature/longrun-b-job-output` (`a53774e`, containing hard
   cap `136b301`). The hard cap stays a separate commit so it can be kept when the cursor is rolled back.
2. **Surface pins (E2-C2, C3).** Both `job_status` surface hashes change in the same commit as the schema and
   description, with the reason recorded. The legacy `job_status-wait` golden snapshot does **not** change.
   New golden/contract cases cover cursor mode.
3. **Helper signature (E2-C4).** `job_status_impl` keeps its positional order; `cursor` is added as a keyword
   argument at the end.
4. **Cross-field validation (E2-C5).** `cursor` without `job_id` is rejected before listing mode, with a test.
5. **Docs (E2-C6).** `docs/tools/run_command.md` (job_status section) documents cursor mode, field presence,
   errors, and the UTF-8 rules, in the same change.
6. **Telemetry field order (E2-C7).** `server_gen=` is emitted before `args=` / `error=`.
7. **Rollback (E2-C8).** Rolling back the cursor is a schema transition: revert the cursor commits only (keep
   `136b301`), reload, `chatgpt-refresh`, verify in a new chat, clean it up.

## 8. Out of scope for v1

- Bounded tail-mode reads (tail mode still reads the whole spool; its returned size is capped).
- `run_command` create idempotency / request keys (E3-4, R-6).
- Waking on new output; server-side delivery state; SSE; MCP elicitation / Tasks; new lifecycle states.
- Pinning retention for jobs with outstanding cursors (E3-11 stronger fix).

## 9. Resolution of review findings

| Finding | Resolution |
| --- | --- |
| E2-B1 / E3-1 tail-mode `next_after` skips output | Tail mode mints no cursor; reseed by `"start"` or explicit `"end"` (§5.1). |
| E2-B2 missing job vs `state="unknown"` | Missing/pruned → existing `No job with id` error; `unknown` is a normal readable state (§5.3, §5.6). |
| E2-B3 quiet ≠ no unread output | Availability only from cursor/`has_more` (§3.3). |
| E2-B4 cap ≤ 0 stalls progress | `C = max(4, max_output_chars)` (§4.1). |
| E3-2 UTF-8 loop | Pending suffix while running; terminal flush; invalid bytes consumed (§4). |
| E3-3 cursor not job-bound | `v1:<job_id>:<offset>`, mismatch rejected (§3.2). |
| E2-C1 hard cap prerequisite | §7.1. |
| E2-C2 / C3 surface and golden | §7.2; legacy snapshot unchanged because tail mode is unchanged. |
| E2-C4 helper signature | §7.3. |
| E2-C5 cross-field validation | §3.1, §7.4. |
| E2-C6 docs | §7.5. |
| E2-C7 `server_gen` placement | §7.6. |
| E2-C8 rollback | §7.7. |
| E3-4 lost start response | Principle narrowed to "once `job_id` is observed"; gap stated (§1, §5.8, §8). |
| E3-5 duplicate polling | `delta_start` / `delta_end` (§3.3, §5.4). |
| E3-9 `unknown` drain | §5.3. |
| E3-11 pruning | Retention-bounded guarantee, existing error (§5.6); stronger fix out of scope (§8). |
| E3-12 read/prune race | Open once, explicit error, never empty success (§5.7). |
| E3-13 old clients | No new field without `cursor` (§2). |
| E2/E3 NOTEs | Recorded; no contract change needed. |

## 10. Round 3 ownership (I0, frozen)

Integration base for every lane: branch `feature/longrun-b-job-output` at `a53774e`. The coordinator creates the
integration branch `feature/longrun-v1` at that commit and merges each lane into it after the lane's focused
tests pass (no fast-forward to `master`).

| Lane | Branch | Owns (only these files) | Frozen interface | Depends on |
| --- | --- | --- | --- | --- |
| I-A storage + decoding | `feature/longrun-i-a-storage` | `src/binnacle/job_store.py`, `src/binnacle/jobs.py` (read helpers only), `src/binnacle/job_output.py` (new decode helper only), their unit tests | `jobs.read_log_range(job_id: str, start: int, max_bytes: int) -> tuple[bytes, int]` returns `(data, size_at_open)` and raises `jobs.JobGone` if the job or log is missing at open; `job_output.consume_utf8(data: bytes, *, at_eof: bool, final: bool) -> tuple[str, int]` returns `(text, consumed_bytes)` per §4 rules 2–5 (`at_eof`: `data` reaches the end of the spool; `final`: the job is not running) | base |
| I-C telemetry | `feature/longrun-i-c-telemetry` | `src/binnacle/logging_middleware.py` (`server_gen` only), stats/usage parsers under `src/binnacle/logstats*.py` and `scripts/` for the new fields, their tests | `server_gen=<hex>` before `args=` / `error=`; parsers accept `event=job_status_cursor` lines with fields `call job_id delta_start delta_end returned_chars has_more log_bytes` | base |
| I-B tool surface | `feature/longrun-i-b-cursor` | `src/binnacle/tools/job_status.py`, `docs/tools/run_command.md` (job_status section), contract/golden/input-validation/surface tests | §3, §5, §6; emits the `event=job_status_cursor` line from I-C's field list | I-A merged into `feature/longrun-v1` (branches from there) |
| I-D harness | `feature/longrun-i-d-harness` | Round 4 fixtures and live-smoke additions under `scripts/` and `tests/live/` | the §3 surface | I-B merged |

I-A and I-C run in parallel. I-B starts when I-A is merged; I-D when I-B is merged. Each lane step stays under
20 minutes. Nothing is pushed, merged to `master`, or deployed in Round 3; the I-GATE runs the full test suite,
the coverage gate and the pinned contracts on the integrated branch.
