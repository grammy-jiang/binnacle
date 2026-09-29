# Lane B report — `job_status` output safety and incremental-output contract

Status: **B0–B4 complete. Lane B ready for R1 synthesis.**
Implementation commit: `136b301` (`fix: hard-cap job status log output`).
Scope: remove the demonstrated single-call `job_status` context-explosion hazard without changing the public inputs or lifecycle, then propose—but do not implement—a cursor/delta contract for Round 2.

## Executive summary

Before Lane B, `job_status` limited output only by `tail_lines`. It read the complete merged `out.log`, decoded it, split it into lines, and returned the last N lines. One very large line therefore bypassed any practical response-size bound. Production telemetry on 2026-09-27 demonstrated the consequence: individual `job_status` results reached roughly 724 KB of structured payload, `est_tokens=181052`, and about 191k tokenizer-counted tokens.

Commit `136b301` closes that response-size hazard. `job_status` still applies `tail_lines` first, then applies a deterministic hard 24,000-character ceiling to `log_tail`, including the elision marker itself. The full log remains on disk. Tool name, inputs, output schema, lifecycle fields, wait behavior, and ordinary small results are unchanged. Sparse internal telemetry records clipping reason and omitted size.

The change does **not** solve repeated-output efficiency by itself. The provisional Round-2 preference is an optional byte-offset `after` cursor on `job_status`, with a separate `job_output(job_id, after=...)` tool as fallback. Both are provisional pending R1 synthesis.

## B0 — Root cause and safety invariant

### Root cause

The pre-change single-job path was:

```text
jobs.read_log(job_id)       # read the complete out.log
  -> decode UTF-8
  -> _tail(text, tail_lines)
       -> splitlines()
       -> join(last N lines)
  -> log_tail
```

`tail_lines` bounded the **number of lines**, not the number of characters returned. A JSONL record, minified JSON object, compiler diagnostic, model trace, or other output with one giant line could therefore make `log_tail` arbitrarily large even when `tail_lines=1`.

The repository already had the relevant output-shaping vocabulary for `run_command`: head/tail character clipping with an explicit `[… N chars elided …]` marker, driven by `jobs.max_output_chars` (default 24,000). `job_status` simply did not apply a character ceiling.

The B0 synthetic reproduction used one 200,000-character line:

```text
configured budget:          24,000 chars
pre-change _tail(...,100): 200,000 chars
existing run shaper:        24,027 chars
```

The existing run shaper's 24,027-character result exposed one additional requirement: its configured limit is a **source-character** budget and the marker is added on top. Lane B's safety invariant requires a hard **returned-log** budget, so `job_status` could reuse the clipping vocabulary but had to count marker overhead inside the ceiling.

### Frozen invariant

> A single `job_status` call must have a deterministic hard returned-log budget independent of line length, while the full job log remains on disk.

Compatibility constraints frozen with it:

- preserve the existing `job_status` tool name and inputs;
- preserve `tail_lines` as the first selection preference;
- preserve lifecycle, exit/signal, quiet, wait, process, path, command, and workdir fields;
- preserve the complete durable `out.log`;
- do not add cursor parameters in the hard-cap change;
- avoid public clipping metadata unless necessary, because that would change the pinned tool schema.

## B1/B2 — Hard-cap implementation and validation

### Implementation

Commit `136b301` changes four files:

- `src/binnacle/job_output.py`
- `src/binnacle/tools/job_status.py`
- `tests/integration/test_jobs.py`
- `tests/unit/core/test_job_output.py`

The implementation adds `clip_head_tail_hard()`, which preserves the existing head/tail elision vocabulary while counting the marker inside the final character ceiling. `job_status` now:

1. reads and decodes the durable spool as before;
2. applies existing `tail_lines` selection;
3. applies the hard character ceiling to the selected tail;
4. returns the bounded value as the existing `log_tail` field;
5. emits `event=job_status_output_shaping` only when character clipping occurs.

The telemetry contains only scalar shaping facts: reason, `tail_lines`, configured limit, selected/returned/omitted character counts, and `log_bytes`. No log content is copied into the event.

No public input or output-schema field changed. Existing no-clipping results remain byte-for-byte compatible at the `log_tail` level.

### Synthetic before/after

These examples are synthetic; no private historical job output is reproduced.

| Case | Before | After |
| --- | ---: | ---: |
| One 200,000-character line, `tail_lines=100` | `log_tail` = 200,000 chars | `log_tail` = exactly 24,000 chars, head/tail preserved with elision marker |
| One 1,000,000-character line | returned 1,000,000 chars | returned exactly 24,000 chars |
| Small 1,000-character line | returned 1,000 chars | returned the same 1,000 chars |
| ~1 MB multiline log where last 100 lines total 1,099 chars | returned 1,099 chars | returned the same 1,099 chars |

The giant-line integration regression also verifies that the underlying spool still contains the full source output and that `log_bytes` continues to report its full size.

### Test and compatibility evidence

B2 validation covered `job_status`, job lifecycle, logging/telemetry, shared output shaping, configuration, schemas, input validation, descriptions, golden outputs, spool compatibility, protocol metadata, and pinned tool surface.

Evidence:

- Lane B's expanded B2 run: **188 focused tests passed**.
- After the pre-commit formatter adjusted one test's quoting only, the focused re-run: **24 tests passed**.
- Coordinator independent re-test of the committed change: **194 focused tests passed**.
- Repository pre-commit hooks passed on the final commit, including Ruff check/format, mypy, Bandit, secret detection, codespell, dependency checks, module-size ratchet, AI-readability warnings, and architecture boundaries.
- Isolated in-process FastMCP discovery showed `job_status` still exposes exactly `job_id`, `tail_lines`, and `wait_seconds`; no production server reload or deployment was used.
- Golden `job_status` output and pinned tool-surface tests passed.

### Performance evidence

A read-inclusive synthetic microbenchmark compared the old shaping path (full `read_bytes` + decode + `_tail`) with the new path (same read/decode/tail plus hard clip). Five samples were taken per case and the median per-call time reported:

| Synthetic case | Before | After | Change | Returned chars before → after |
| --- | ---: | ---: | ---: | ---: |
| 1 KB single line | 0.010742 ms | 0.010948 ms | +0.000207 ms | 1,000 → 1,000 |
| ~1 MB multiline | 8.411056 ms | 8.001197 ms | -0.409859 ms | 1,099 → 1,099 |
| 1 MB giant line | 2.230339 ms | 2.178061 ms | -0.052278 ms | 1,000,000 → 24,000 |

These are microbenchmarks, not claims of a speedup; the useful conclusion is that no obvious latency regression appeared and the added clipping cost is negligible relative to the existing full-spool read/decode/split path.

### Remaining I/O limitation

The hard-cap fix bounds what is **returned**, not what is **read**. `job_store.read_log()` still uses `Path.read_bytes()`, so `job_status` reads the complete spool before selecting its tail. B1 did not increase the bytes read, but very large logs can still create local I/O/allocation cost even though they can no longer explode the model context.

That is deliberately deferred. A future cursor/delta implementation should use bounded seeks/range reads rather than layering cursor semantics on top of the current full-file read.

## B3 — Cursor/delta contract proposal

**All recommendations in this section are provisional pending the R1 synthesis gate. No cursor/delta API is implemented in Round 1.**

### Design constraints from the current contract

The current durable output source is the per-job merged `out.log`. It is append-only for the life of a job under the current implementation. `job_status(job_id)` reads durable state and returns a bounded `log_tail`; `log_bytes` reports the current spool size. The store keeps a base window of the newest jobs and protects older running jobs, but terminal job directories may later be pruned as whole units. There is no current log rotation or public event stream.

Lane C provides a useful semantic precedent without dictating the local representation: current Responses background streaming gives each event a `sequence_number` and resumes exclusively with `starting_after=<sequence_number>`. Lane C explicitly found no documented exactly-once, gap-free, or globally unique sequence guarantee, and recommends adapting the idea of a monotonic resume position to Binnacle's append-only merged log rather than cloning SSE or the Responses event taxonomy.

The Binnacle objective is therefore narrower: let a later call or later ChatGPT turn say "give me only output after the last position I processed", while preserving the existing status lifecycle and old `job_status` behavior.

### Representation comparison

| Representation | Repeated-token reduction | Cross-turn resume | Retention / rotation | UTF-8 | Terminal retrieval | Compatibility / complexity |
| --- | --- | --- | --- | --- | --- | --- |
| **Byte-offset cursor over merged spool** | Strong: return only bytes after the acknowledged offset, bounded per call. | Strong: one small integer is sufficient with `job_id`; no hidden session state. | Fits current whole-file retention. A pruned job invalidates both job and cursor. Current logs do not rotate; future truncation/rotation must add generation/invalidation semantics before being enabled. | Requires deliberate chunk-boundary handling because byte offsets can split a multibyte code point. Server-issued next offsets must be safe to echo. | Strong: start at byte 0 and advance until caught up; terminal state plus no remaining bytes establishes completion. | Lowest storage complexity because the spool already supplies the monotonic position. |
| **Monotonic sequence/event cursor** | Strong if every output event is persisted and addressable. | Strong if sequence state is durable. | Can survive physical rotation if a separate event index is retained. | Natural if each persisted event owns a decoded payload. | Strong if the event history is retained through terminal state. | High cost here: current stdout/stderr merge is a byte spool with no durable public event boundaries. Requires a sidecar/event store, sequence allocation, restart recovery, and new invariants merely to recreate information not presently stored. |
| **Opaque cursor backed by byte offset** | Same data efficiency as a byte offset. | Strong; caller only echoes the token. | Can encode a future generation/version and reject stale tokens cleanly. | Server can own all boundary rules. | Strong. | More future-proof, but less transparent/debuggable and cannot reuse current `log_bytes` as an obvious "follow from now" position. A versioned opaque cursor is a migration option if rotation is later introduced. |

**Provisional representation choice:** use a byte offset for v1 because it is the natural monotonic position of the existing append-only spool and requires no second durable index. Do not call it an event sequence number: that would imply event semantics Binnacle does not have. If log rotation/truncation becomes a supported behavior, version the cursor or replace it with an opaque generation-aware token before enabling that behavior.

### API-shape comparison

#### Option A — separate `job_output(job_id, after=...)`

Candidate shape:

```text
job_output(job_id, after=0)
  -> {
       job_id,
       output,
       next_after,
       has_more,
       log_bytes
     }
```

Advantages:

- clean separation between lifecycle/status and output transport;
- no conditional meaning for existing `job_status.log_tail`;
- output retrieval can later be optimized to bounded file seeks without changing status logic;
- old clients remain behaviorally untouched because the tool is additive.

Costs:

- adds a seventh ChatGPT-visible tool and corresponding visibility/configuration/schema surface;
- a model commonly needs both job state and new output, so polling becomes two calls instead of one unless it sometimes skips status;
- a new tool increases discovery/tool-selection burden for a problem already encountered while calling `job_status`;
- terminal retrieval needs a separate status call unless the output tool starts duplicating lifecycle fields, which erodes the separation.

#### Option B — extend `job_status` with optional `after`

Candidate shape:

```text
job_status(job_id, tail_lines=100, wait_seconds=0, after=<byte offset>)
  -> existing lifecycle/status fields
     + log_delta
     + next_after
     + has_more
     + log_bytes
```

Compatibility rule:

- **when `after` is omitted, behavior and payload remain the existing `job_status` contract**, including bounded `log_tail`;
- when `after` is supplied, cursor mode returns bounded `log_delta` after that byte position instead of resending `log_tail`;
- existing callers therefore do not need migration, although adding the optional input/output properties changes the published tool schema and requires the normal client/tool-surface refresh when eventually implemented.

Advantages:

- one call answers the two questions a long-running orchestration loop normally has: "what state is the job in?" and "what output is new?";
- minimizes repeated model steps as well as repeated output tokens;
- reuses the existing durable `job_id`, wait behavior, quiet signal, process information, and terminal outcome fields;
- closely adapts Lane C's retrieve-plus-resume-position concept without adding an SSE/event abstraction.

Costs:

- introduces a conditional response mode and additional fields to an established tool;
- `tail_lines` is irrelevant to `log_delta` in cursor mode and must be documented as applying only when `after` is omitted;
- implementation must avoid the current full-spool read path or the token win will not automatically become an I/O win;
- tool schema changes even though old calls remain compatible.

### Provisional preferred design pending R1

**Preferred: Option B, extend `job_status` with an optional byte-offset `after` cursor. This is provisional pending R1 synthesis.**

Proposed semantics for Round-2 evaluation:

1. `after` is an **exclusive byte position** in that job's merged `out.log`. `after=0` requests output from the beginning.
2. Omitting `after` preserves the current B2 behavior exactly: bounded `log_tail`, current `tail_lines`, current state/outcome/process fields.
3. Supplying `after` switches only the output projection to a bounded `log_delta`. It returns `next_after` equal to the first unread byte after the returned chunk and `has_more` indicating that more bytes existed at the read snapshot.
4. Cursor mode should read a bounded region of the spool by seek/range rather than calling the current whole-file `read_bytes()`. The B2 finding that `job_status` still reads/decodes the whole spool is a separate implementation concern to fix when cursor mode is implemented, not in Round 1.
5. The existing hard returned-log budget remains the ceiling for `log_delta`. Chunking should not add a head/tail elision marker: `has_more=true` and `next_after` express continuation without discarding the middle.
6. `next_after` must always be safe to echo. The implementation must not end a chunk inside a valid UTF-8 code point. A bounded byte read with small look-ahead/incremental decoding can preserve the current `errors="replace"` behavior for genuinely invalid bytes while keeping valid multibyte characters intact across chunks.
7. A caller-supplied negative cursor or a cursor beyond current `log_bytes` is an explicit invalid-cursor error, not silently clamped. A missing/pruned job remains the existing unknown-job error. Cursors do not extend retention.
8. Current storage has no rotation. Before any future rotation/truncation is enabled, the contract must gain generation-aware invalidation (for example a versioned opaque cursor); a bare offset must not be silently reused against replaced content.
9. Zero-output and quiet jobs are normal: `log_delta=""`, `next_after=after`, `has_more=false` at that snapshot, while existing `state`, `quiet`, `last_output_age_s`, and optional wait fields still describe lifecycle.
10. Terminal retrieval is deterministic: a caller that needs the complete transcript starts at `after=0` and advances until the job is terminal and `has_more=false`. A caller interested only in future output may intentionally seed `after` from a known current byte position.
11. `log_bytes` is a useful observed spool size, but it is not itself redefined as a cursor. In particular, an earlier `run_command` result may have been head/tail truncated, so using its `output_bytes` as `after` can intentionally skip output the model never saw. Round 2 documentation must distinguish "retrieve complete history" from "follow from now".
12. Cursor mode does not change `wait_seconds` into a streaming wait. The current wait remains "until terminal state or deadline"; waking on new output would be a separate contract requiring evidence.

This shape reduces both repeated output and model-call count while preserving the no-`after` contract for old clients.

### Provisional fallback pending R1

**Fallback: add the separate `job_output(job_id, after=...)` tool using the same byte-offset semantics. This is provisional pending R1 synthesis.**

Choose the fallback if R1 concludes that conditional `job_status` output is too confusing, if independent bounded file-range I/O is substantially easier to reason about as a separate tool, or if Lane D evidence favors a distinct retrieval primitive. The fallback should not introduce sequence/event storage merely to imitate Responses.

### Why a sequence/event cursor is not preferred

A sequence cursor is attractive in an event-native system, and Lane C confirms that `sequence_number + starting_after` is usable for Responses stream recovery. Binnacle is not currently event-native: output is the merged bytes written to `out.log`. Assigning durable sequence numbers would require defining event boundaries, persisting an index/sidecar, recovering sequence allocation across owner restarts, specifying gaps/duplicates, and retaining that metadata consistently with the spool. None of those costs is needed for a monotonic byte position.

The useful Responses lesson is therefore **exclusive resume after a caller-retained monotonic position**, not the literal sequence-number representation.

### Evaluation against the B3 criteria

| Criterion | Preferred: `job_status(after=byte_offset)` | Fallback: `job_output(after=byte_offset)` |
| --- | --- | --- |
| Repeated-token reduction | High: only unseen bounded delta; status metadata is small. | High for output, but separate status calls may add model steps/tokens. |
| Simple model usage | High: poll/retrieve in one familiar call and echo `next_after`. | Moderate: clear separation but model must choose/call two tools when it needs state plus output. |
| Resume in another ChatGPT turn | High: persist only `job_id` + integer `next_after`; no session state. | High: same cursor property. |
| Log rotation / retention | Current whole-job pruning is explicit; future rotation requires cursor generation/invalidation before rollout. | Same. |
| UTF-8 boundaries | Server-issued next offsets must be valid boundaries; invalid source bytes keep replacement semantics. | Same. |
| Terminal output retrieval | Terminal state and `has_more=false` can be observed in one call. | Requires output exhaustion plus a separate status observation unless lifecycle fields are duplicated. |
| Old-client compatibility | Existing no-`after` calls remain behaviorally unchanged; published schema changes additively. | Existing tools remain unchanged; tool list grows and client visibility/config must add the new tool. |
| Zero-output / quiet jobs | Empty delta with unchanged cursor; existing quiet/state fields remain available. | Empty delta is simple, but quiet/state requires `job_status`. |
| Cursor invalidation | Reject negative/out-of-range; missing/pruned job is existing not-found; future rotation needs generation. | Same. |
| Responses API alignment | Adapts exclusive "starting after" resume semantics without claiming event guarantees. | Same cursor semantics, but split retrieval/status differs more from current Binnacle polling flow. |

### R1 cross-lane questions

These remain open for synthesis rather than being decided by Lane B:

- Does Lane D find a host-supported task/elicitation/reconnect primitive that materially changes whether status and output should be one tool or separate tools?
- Should Round 2 optimize cursor mode directly to bounded file seeks, or first introduce a storage helper with byte-range and UTF-8-boundary tests that both API shapes could share?
- Is the additive `job_status` schema change acceptable for all current clients/tool-surface caching, or does compatibility evidence favor the separate-tool fallback despite the extra model call?
- Does Round 2 need cursor generation/versioning immediately even though current Binnacle does not rotate individual logs, or is explicit invalidation on future rotation sufficient for v1?
- Should a later contract add "wait for new output" semantics, or is the existing terminal/deadline wait plus zero-wait delta retrieval enough? Lane B does not assume streaming is required.

### B3 non-decisions

B3 does not implement or freeze a public cursor API, add a tool or parameter, change retention, add SSE, add event sequence storage, change `wait_seconds`, or change the B2 hard-cap contract. Those decisions belong to R1/Round 2.

## Non-goals and deferred work

Lane B deliberately did **not**:

- implement a cursor/delta public API in Round 1;
- add `after`, cursor, sequence, or acknowledgement parameters to any shipped tool;
- add a new `job_output` tool;
- change `run_command`, `stop_job`, job lifecycle states, wait semantics, process ownership, or cancellation;
- change job retention/pruning or introduce per-log rotation;
- add SSE, streaming transport, event sequence storage, or a Responses-shaped event taxonomy;
- promise exactly-once or gap-free output delivery;
- optimize the existing full-spool read path as part of the immediate hard-cap safety fix;
- push, merge, deploy, reload, or restart production services.

Deferred to R1/Round 2 are the public cursor shape, bounded byte-range storage helper, UTF-8 chunk-boundary contract, cursor invalidation/versioning policy, tool-surface migration, and any decision about waiting for new output rather than only terminal state/deadline.

## Cross-lane questions before API freeze

### Lane C — answered

Lane C's completed report answers the Responses-specific design questions needed by Lane B:

- Responses background streaming uses a caller-retained `sequence_number` and resumes **after** it with `starting_after`.
- The reviewed documentation does not establish exactly-once delivery, gap-free sequence numbers, or global sequence uniqueness.
- Lane C recommends adapting a monotonic incremental-output position to Binnacle's append-only log, while retaining `job_id` and the current local lifecycle/outcome semantics.
- Lane C explicitly advises against cloning SSE, hosted retention rules, or the six Responses statuses merely for lexical similarity.

Lane B therefore uses the Responses design as evidence for **exclusive resume after a durable caller-held position**, but chooses a byte offset because Binnacle's persisted output is a byte spool rather than an event store.

### Lane D / R1 — still to resolve

Before the public API is frozen, R1 should answer:

- Does the actual ChatGPT MCP host expose task, elicitation/input-required, reconnect, or other lifecycle primitives that materially favor a separate output-retrieval tool over extending `job_status`?
- Does host/tool caching make an additive optional `job_status.after` parameter materially harder to roll out than adding a new visible `job_output` tool?
- Is there any host behavior that makes a two-tool status/output flow easier or harder for the model than one conditional `job_status` call?

These questions may change the **API shape**, but they do not change the B3 representation finding that a byte-backed monotonic position fits the current spool better than inventing event sequence storage.

### R1 implementation questions

R1/Round 2 must also decide:

- whether cursor mode lands directly with bounded file seeks or behind a reusable byte-range storage helper;
- whether generation/versioning is required in cursor v1 despite the absence of current per-log rotation;
- whether `after` remains a transparent integer or is wrapped in an opaque/versioned token;
- whether "wait for new output" is needed at all, rather than retaining the current terminal/deadline wait plus zero-wait delta reads;
- whether complete-history and "follow from now" workflows need explicit helper fields or documentation beyond `after=0` and the current observed `log_bytes`.

## Lane B conclusion

The immediate safety issue is closed by `136b301`: a single `job_status.log_tail` can no longer grow without bound because of line length, while the durable full log and existing public contract remain intact.

The remaining long-running-work inefficiency is repeated retrieval of already-seen output. Lane B's provisional Round-2 direction is a caller-retained byte position with exclusive "after" semantics, preferably integrated into `job_status` so state and unseen output arrive in one call. The separate `job_output` tool remains the compatibility/clarity fallback. Neither choice is frozen until R1 consumes Lane A reliability evidence, Lane C's Responses mapping, and Lane D's observed host capabilities.
