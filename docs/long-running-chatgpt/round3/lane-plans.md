# Round 3 lane plans (I-A, I-C; I-B and I-D follow)

Contract: `../round2/e4-contract-v1.md` (FROZEN). Ownership: its §10. A lane that finds the contract wrong
stops with STATUS BLOCKED and names the section; it does not change the contract itself.

Common rules for every implementation lane:

- Work only in your own worktree and only on the files §10 gives your lane.
- Run tests with your worktree's own `.venv/bin/python -m pytest ...`. Never use the production checkout
  `~/Projects/binnacle`, never reload or restart a service, never push, never merge.
- Commit on your lane branch with the repository's pre-commit hooks passing.
- One step per turn; each step 8–15 minutes; end with the checkpoint fields
  STEP, STATUS, ARTIFACTS, COMMIT, FINDINGS, NEXT.

## Lane I-A — storage and decoding

Worktree `~/Projects/binnacle-longrun-i-a-storage`, branch `feature/longrun-i-a-storage` (from `a53774e`).

### IA1 — bounded range read

1. Add `jobs.JobGone` (exception) and `jobs.read_log_range(job_id, start, max_bytes) -> tuple[bytes, int]`,
   delegating to a `job_store` helper that opens `out.log` once, takes `size` from the open file (`fstat`),
   seeks to `start`, and reads at most `max_bytes`.
2. Missing job directory, missing `meta.json` or missing `out.log` at open → `JobGone`. Never `b""` for a
   missing file (contract §5.7). `start > size` returns `(b"", size)`; the caller turns it into the
   "beyond end" error.
3. Leave `read_log()` and every existing caller unchanged.
4. Unit tests: middle range, range to EOF, `max_bytes` larger than remainder, `start == size`,
   `start > size`, missing dir/log → `JobGone`, file removed after open still reads (open-once).

Exit: focused tests pass; commit.

### IA2 — UTF-8 consumption helper

1. Add `job_output.consume_utf8(data, *, at_eof, final) -> tuple[str, int]` implementing contract §4 rules
   2–5 for one chunk: back off an incomplete multi-byte sequence at the chunk end when `at_eof` is false;
   keep it pending (not consumed) when `at_eof` is true and `final` is false; flush it with U+FFFD when
   `final` is true; consume invalid bytes elsewhere with replacement.
2. Unit tests: ASCII; valid 2-, 3-, 4-byte characters split at the chunk end (each of the 1–3 possible cut
   points) with `at_eof` false; the same with `at_eof` true and `final` false (pending) and `final` true
   (flushed); invalid bytes mid-chunk; an empty chunk; a 4-byte chunk always consumes at least one character
   when it holds any complete character.
3. A hypothesis property test is welcome: for any byte string split into chunks of size ≥ 4 and drained with
   the helper, the concatenated text equals `data.decode("utf-8", "replace")` once the last chunk is `final`.

Exit: focused tests pass; commit.

### IA3 — validation

Run `tests/unit/core`, the property tests, and the repository pre-commit hooks on the lane's files; check that
branch coverage of the new functions is complete. Fix only what the validation finds. Final commit.
Return the lane completion reply (`NEXT: coordinator merge into feature/longrun-v1`).

## Lane I-C — telemetry

Worktree `~/Projects/binnacle-longrun-i-c-telemetry`, branch `feature/longrun-i-c-telemetry` (from `a53774e`).

### IC1 — server generation id

1. Generate one server-generation id per server process start (short hex) and emit `server_gen=<id>` on every
   `tool_call` and `tool_result` line, **before** `args=` and `error=` (contract §7.6).
2. Tests: the field is present on both line kinds, precedes `args=` / `error=`, is stable within a process, and
   `logstats.plain_fields` returns it as a field without absorbing it into `args` or `error`.

Exit: focused logging/logstats tests pass; commit.

### IC2 — cursor telemetry acceptance

1. Make the stats and usage parsers accept `event=job_status_cursor` lines with fields
   `call job_id delta_start delta_end returned_chars has_more log_bytes` (contract §10): they must not break or
   double-count `job_status_timing`. Where `binnacle stats` reports job_status figures, add a cursor-call count.
2. Tests with synthetic journal lines for both the old shapes and the new event and field.

Exit: focused tests pass, pre-commit hooks pass; commit. Return the lane completion reply
(`NEXT: coordinator merge into feature/longrun-v1`).

## Lane I-B — tool surface (cursor mode)

Worktree `~/Projects/binnacle-longrun-i-b-cursor`, branch `feature/longrun-i-b-cursor`, created from
`feature/longrun-v1` after I-A and I-C are merged into it. Uses `jobs.read_log_range`, `jobs.JobGone` and
`job_output.consume_utf8` as they are; does not change them.

### IB1 — cursor semantics in `job_status_impl`

1. Add `cursor: str | None = None` as the **last keyword** of `job_status_impl` (contract §7.3).
2. Implement §3.2 parsing and errors (`start`, `end`, `v1:<job_id>:<offset>`, malformed, wrong job, beyond
   end), §4 reads (`C = max(4, max_output_chars)`, `read_log_range`, `consume_utf8` with `at_eof` and
   `final = state != "running"`), `has_more` per §4.6, the §3.3 output fields, and omission of `log_tail`
   in cursor mode. Missing job at open → the existing `No job with id` error (§5.7).
3. Emit one `event=job_status_cursor` line with the §10 field list.
4. Integration tests: `start` drain of a multi-chunk log; `end`; wrong-job cursor; beyond end; malformed;
   missing/pruned job; quiet running job with unread output (`has_more` true); pending UTF-8 suffix while
   running, flushed after exit; invalid bytes; `max_output_chars=0` still progresses; `state="unknown"` job
   readable; tail mode payload unchanged.

Exit: focused tests pass; commit.

### IB2 — public surface

1. Add the `cursor` parameter to the `job_status` tool and the §6 description texts; reject `cursor` without
   `job_id` before listing mode (§7.4) with a contract test.
2. Update both pinned `job_status` surface hashes with the reason (§7.2); add golden/contract cases for cursor
   mode; the legacy `job_status-wait` golden snapshot must stay unchanged.
3. Document cursor mode in `docs/tools/run_command.md` (job_status section): inputs, field presence, errors,
   UTF-8 rules (§7.5).

Exit: contract tests pass; commit.

### IB3 — validation

Run the whole test suite with the coverage gate (`tox`'s command or `pytest --cov --cov-fail-under=86.9`),
and the pre-commit hooks. Fix only what validation finds. Final commit and the lane completion reply
(`NEXT: coordinator merge into feature/longrun-v1`).

## Lane I-D — harness (after I-B is merged)

Worktree `~/Projects/binnacle-longrun-i-d-harness`, branch `feature/longrun-i-d-harness`, created from
`feature/longrun-v1` after I-B is merged. Uses the §3 surface as published; changes no `src/` file.

### ID1 — Round 4 fixture program

Add `scripts/longrun_fixture.py`: one deterministic command that Round 4 runs through `run_command`, with
modes `normal` (N minutes, one numbered line every S seconds, exit 0), `high` (bursts of long lines, including
one line longer than the hard cap), `quiet` (silent for the whole run, then one line), `fail` (exit code 3 after
N seconds), `utf8` (multi-byte characters split across writes, including a write that ends mid-character before
a pause), and `cancel` (runs until stopped). Every line carries the fixture nonce and a sequence number so a
reader can prove "no line lost, none duplicated" by comparing sequence numbers. Unit tests for the output shape
of each mode with small N and S.

Exit: tests pass; commit.

### ID2 — live-smoke cursor check

Extend `scripts/smoke_checks.py` (the deploy smoke) with a cursor check: start a short fixture job, drain it
with `job_status(job_id, cursor="start")` until the job is not running and `has_more` is false, and assert that
the concatenated `log_delta` contains every sequence number exactly once. Keep the existing legacy checks
unchanged. Unit tests with a fake client for the new check.

Exit: tests and pre-commit pass; commit; lane completion reply (`NEXT: coordinator merge into
feature/longrun-v1`).
