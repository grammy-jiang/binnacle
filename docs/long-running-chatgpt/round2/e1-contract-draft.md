# E1 — Long-running job contract, draft v1

Status: **DRAFT for E2 (compatibility) and E3 (adversarial) review.** Not frozen. Author: coordinator.
Inputs: `e0-synthesis.md` decisions D-1 to D-6 and risks R-1 to R-8.

## 1. Principle

A long-running job is owned by Binnacle, identified by `job_id`, and fully recoverable by any later tool call
that names it. A ChatGPT turn may wait for a job, but no guarantee depends on it doing so. The only new public
concept is an **output position**: a byte offset that lets a caller read output it has not seen, in bounded
chunks, from any turn.

## 2. What does not change

| Tool | Unchanged |
| --- | --- |
| `run_command` | Inputs, outputs, wait and handoff rules, `job_id`, `background_job`, `output_bytes`. |
| `job_status` without `after` | Every current field and meaning, including `tail_lines`, `wait_seconds`, the listing mode, and the 24,000-character hard cap on `log_tail` (commit `136b301`). |
| `stop_job` | Inputs, outputs, TERM→KILL behavior, idempotence on terminal jobs. |
| Lifecycle | `state` ∈ `running` \| `exited` \| `unknown`; outcome in `exit_code` / `signal`. No new states. |
| Job store | `meta.json` + append-only `out.log`; retention and pruning rules. |

## 3. The addition: `job_status(after=...)`

Placement: an optional argument on `job_status` (Lane B preferred design). Reason: one call returns both
lifecycle state and new output, which keeps model steps low (A: success turns had a median of 77 visible
steps); a separate tool would add a tool and usually a second call per poll.

### 3.1 Input

| Argument | Type | Default | Meaning |
| --- | --- | --- | --- |
| `after` | integer ≥ 0, or omitted | omitted | Exclusive byte position in the job's merged `out.log`. `0` = from the start. |

`after` requires `job_id`. `after` without `job_id` is an input error. When `after` is given, `tail_lines` is
ignored.

### 3.2 Output (added fields)

| Field | When | Meaning |
| --- | --- | --- |
| `log_delta` | `after` given | Output from byte `after` up to `next_after`, decoded UTF-8 (`errors="replace"`), at most the hard cap (24,000 characters). No elision marker. |
| `next_after` | **always** when `job_id` is given | The position to pass as `after` next time. Without `after`: the end of the spool at read time ("follow from now"). With `after`: the byte after the last byte returned. Always on a UTF-8 character boundary. |
| `has_more` | `after` given | `true` when the spool held more bytes than this call returned, at read time. |

In cursor mode `log_tail` is omitted. `log_bytes`, `state`, `exit_code`, `signal`, `quiet`,
`last_output_age_s`, `processes` and the wait fields keep their current meaning.

### 3.3 Semantics

1. **Exclusive position.** `after=N` returns bytes starting at offset `N`. `next_after` names the first
   unread byte. This matches the Responses `starting_after` idea (C1) with a byte, not an event, as the unit.
2. **Bounded per call.** A call reads at most `cap` bytes from `after` (cap = `jobs.max_output_chars`, 24,000);
   since each character is at least one byte, the returned text is at most `cap` characters. If the chunk ends
   inside a multi-byte character, the read stops before that character (at most 3 bytes back), so
   `next_after` is always a boundary. Progress is guaranteed: a call with `has_more=true` returns at least one
   character.
3. **Bounded I/O.** Cursor mode seeks to `after` and reads at most `cap + 3` bytes. It never reads the whole
   spool (R-2). Tail mode keeps its current read path in v1 (see §6).
4. **Reseeding in a new turn (R-5).** A turn that holds only a `job_id` calls `job_status(job_id)`: it gets the
   usual tail plus `next_after` = current end, and follows from there. A turn that needs everything calls
   `after=0` and repeats while `has_more=true`.
5. **Draining.** The job is fully read when `state` is `exited` and `has_more` is `false`.
6. **Quiet and empty jobs.** `log_delta=""`, `next_after=after`, `has_more=false`; lifecycle fields as usual.
7. **Waiting.** `wait_seconds` keeps its meaning (block until exit or deadline). Cursor mode does not wait for
   new output. "Wake on new output" is out of scope for v1.
8. **Errors.** `after` > current `log_bytes` → tool error `cursor beyond end of output (log_bytes=N)`.
   Unknown or pruned job → the existing unknown-job error. A cursor does not extend retention.
9. **Rotation.** The store has no log rotation. If rotation is ever added, the cursor contract must first gain
   a generation (for example an opaque versioned cursor); a bare offset must never be applied to replaced
   content (R-3).
10. **Idempotence.** Repeating a call with the same `after` returns the same bytes, plus any bytes appended
    since, up to the cap. No delivery state is kept on the server.

## 4. Descriptions (tool contract text)

`job_status` description gains one sentence, kept within the prompt-layer rules (descriptions state the
contract; parameters state parameter facts):

- tool: "Pass `after` (from `next_after`) to read only output you have not seen, in bounded chunks."
- `after` parameter: "Byte position from a previous `next_after`; 0 reads from the start. Omit for the tail."

## 5. Telemetry in v1 (R-1, R-7)

- One line per cursor-mode call: `event=job_status_cursor call=… job_id=… after=… next_after=… returned_bytes=…
  has_more=… log_bytes=…`.
- A server-generation id (set at process start) on every `tool_call` / `tool_result` line, so an MCP reload
  is visible in the record (A §8.3 row 4).
- Attribution keeps the `client=` prefix match (`openai-mcp`), never an exact label (R-7).
- Host-side facts (turn-end reason, context occupancy) are not observable by Binnacle and stay out of scope.

## 6. Out of scope for v1

- Bounded tail-mode reads (F7 stays for calls without `after`; the hard cap already bounds what is returned).
- Duplicate-start protection / create idempotency for `run_command` (R-6): no evidence of harm yet in A;
  revisit with Round 4 data.
- MCP elicitation, MCP Tasks, SSE, new lifecycle states (D-3, D-6).
- Changes to `client_tools`: every client that sees `job_status` gets the new argument.

## 7. Compatibility and rollout

- Additive schema change: one optional input, three optional output fields. Old calls return the same payload
  plus `next_after`.
- ChatGPT caches the tool schema: the full loop applies (reload, `scripts/mcp_client.py`, `chatgpt-refresh`,
  a new test chat, cleanup).
- Rollback: revert the commit; callers that never pass `after` are unaffected.

## 8. Candidate implementation split (for I0; frozen only at E4)

| Lane | Owns | Interface |
| --- | --- | --- |
| I-A storage | `src/binnacle/job_store.py`, `src/binnacle/jobs.py` read helpers + unit tests | `read_log_range(job_id, start, max_bytes) -> (data: bytes, size: int)`; UTF-8 boundary trim helper in `job_output.py` |
| I-B tool surface | `src/binnacle/tools/job_status.py`, `docs/tools/run_command.md` (job_status section), contract/golden/surface tests | uses I-A; adds `after`, `log_delta`, `next_after`, `has_more` |
| I-C telemetry | logging/call-context modules, `binnacle stats` / usage scripts parsing | `event=job_status_cursor`, `server_gen=` field |
| I-D harness | Round 4 fixtures and live-smoke additions | depends on I-B's published schema only |

I-A and I-C can start at once; I-B starts when I-A's helper signature is frozen (this table); I-D starts when
I-B's schema is frozen.

## 9. Questions for the reviewers

- E2: does any current test, script, stats parser or client depend on the exact `job_status` field set, or on
  `log_tail` being present when `job_id` is given?
- E2: is `next_after` in tail mode safe given the tail is head/tail-clipped (the caller may skip unseen middle
  output when it follows from `next_after`)?
- E3: find a sequence of calls, restarts, prunes or races under which a caller loses output, reads output
  twice without knowing, or loops forever.
