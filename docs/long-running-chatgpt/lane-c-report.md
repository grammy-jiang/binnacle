# Lane C report — OpenAI Responses API reference design

Status: **C0–C3 complete. Lane C ready for R1 synthesis.**
Retrieval date for public sources: **2026-09-29**.
Scope: freeze the documented Responses lifecycle/stream-recovery semantics, map them to the current Binnacle job contract, and provide compatibility-first recommendations for R1 synthesis.

## Source discipline

Normative claims below are sourced only to current official OpenAI documentation/API reference retrieved on 2026-09-29.

- [Background mode](https://developers.openai.com/api/docs/guides/background)
- [Create a model response — Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Get a model response — Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/retrieve)
- [Data controls in the OpenAI platform](https://developers.openai.com/api/docs/guides/your-data)
- [Streaming API responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [OpenAI Ruby API library reference](https://developers.openai.com/api/reference/ruby)
- [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)

Where this report derives a statement by combining documented facts rather than quoting an explicit single sentence, it is labelled **Direct derivation**.

## C0 — Frozen background Responses lifecycle

### Start and identity

**Documented.** A long-running Response is started asynchronously by creating a Response with `background=true`. The returned Response object has a unique `id`; that identifier is the handle used for later retrieval.

Sources:

- Background mode: start background generation with `background=true`.
- Create API reference: `background` controls background execution; `id` is the unique identifier for the Response.

### Lifecycle/status fields

**Documented.** The Response `status` field has exactly these documented values:

```text
queued
in_progress
completed
failed
cancelled
incomplete
```

The Response object also exposes lifecycle/result fields relevant to terminal handling:

- `completed_at`: present only when `status=completed`;
- `error`: an error object returned when the model fails to generate a Response;
- `incomplete_details`: details explaining why a Response is incomplete;
- `output`: generated output items.

Source: Create API reference.

### Terminal states and failure/cancellation semantics

**Documented.** The background-mode guide instructs clients to keep polling while status is `queued` or `in_progress`; once the Response leaves those states it is in a final/terminal state.

**Direct derivation from the documented polling rule plus the six-value status enum.** The terminal status set is therefore:

```text
completed | failed | cancelled | incomplete
```

**Documented.** Failure information is represented by the Response `error` object. An incomplete Response carries `incomplete_details`; for example, OpenAI documents `reason=max_output_tokens` as an incomplete case.

**Documented.** An in-flight background Response can be cancelled with `POST /v1/responses/{response_id}/cancel` (or the SDK `responses.cancel(...)`). The background-mode guide states that cancelling twice is idempotent: later cancellation calls return the final Response object.

Sources:

- Background mode: polling terminal rule and cancellation behavior.
- Create API reference: status enum, `error`, and `incomplete_details`.

### Reattachment/retrieval without the original request

**Documented.** A client does not need to hold the original create request open to observe later state/result. It can retrieve the Response by ID using:

```http
GET /v1/responses/{response_id}
```

The SDK equivalent is `client.responses.retrieve(response_id)`. The background-mode guide explicitly presents polling by repeatedly retrieving `resp.id` until the Response leaves `queued`/`in_progress`.

Sources:

- Get a model response API reference.
- Background mode.

### Retention and expiry caveats

**Documented.** The general Responses API application-state retention period is 30 days by default, or when `store=true`; in those cases response data is stored for at least 30 days, subject to documented retention exceptions.

**Documented, background-specific exception.** Background execution requires temporary server-side storage so asynchronous execution and polling can work. Current data-control documentation says:

- background Response data is stored to disk for roughly 10 minutes to enable polling;
- background Responses follow the standard retention period only when `store=true` is explicitly set;
- if `store` is omitted or `false` for a background request, the Response is deleted after the temporary polling period;
- for Zero Data Retention projects, `store` is treated as `false`.

**Implication for reattachment (direct operational reading, not a Binnacle recommendation).** Retrieval by `response.id` is only useful while the Response object still exists under the applicable retention policy; the identifier is not an indefinite persistence guarantee.

Sources:

- Data controls in the OpenAI platform.
- Background mode.
- Create API reference for `store`.

### Concise lifecycle diagram

```text
POST /v1/responses
  background=true
       |
       v
Response{id, status=queued|in_progress, ...}
       |
       | retain response.id; original HTTP request need not stay open
       |
       +----> GET /v1/responses/{id} ----+
       |                                 |
       |          queued/in_progress ----+---- poll/retrieve again
       |                                 |
       |          completed  ------------+---- terminal; result in Response
       |          failed     ------------+---- terminal; inspect error
       |          incomplete ------------+---- terminal; inspect incomplete_details
       |          cancelled  ------------+---- terminal
       |
       +----> POST /v1/responses/{id}/cancel
                         |
                         +---- cancellation is idempotent; final Response returned
```

Retention boundary around the diagram: durable retrieval depends on the Response retention policy. For background Responses, explicit `store=true` is required for standard retention; otherwise current docs describe only the roughly 10-minute temporary polling window.

## C0 interpretation boundary

C0 records the hosted Responses API lifecycle as documented. It does **not** yet decide which semantics Binnacle should copy, adapt, or reject. Streaming event sequence numbers, reconnect/resume behavior, duplicate handling, request/idempotency details, and transport-vs-object lifecycle are intentionally deferred to C1.

## C1 — Streaming, cursor, reconnect and idempotency semantics

### Transport lifecycle versus Response-object lifecycle

**Documented.** Ordinary Responses streaming uses HTTP server-sent events (SSE) when `stream=true`. The streaming guide identifies common lifecycle events including `response.created`, repeated delta events, `response.completed`, and `error`.

**Documented.** Background streaming separates the stream connection from execution of the Response object. A client creates with both `background=true` and `stream=true`; if the connection drops, the background Response continues running and the client can reconnect to its event stream.

**Documented.** A new stream can only be started from a background Response that was originally created with `stream=true`. For a synchronous Response, the background guide says cancellation is performed by terminating the connection.

**Interpretation.** The SSE connection is therefore a transport view over a separately addressable background Response object. Losing that transport does not by itself cancel the background object. This interpretation is specific to documented background mode; it is not a claim that every Responses transport is durable or reconnectable.

Sources:

- Background mode: background streaming, reconnect example, and limits.
- Streaming API responses: SSE transport and common event types.
- Get a model response API reference: retrieval by Response ID.

### Event sequence numbers and resume cursor

**Documented.** The background guide tells clients to retain a cursor equal to the `sequence_number` received on each streaming event.

**Documented.** To resume after the last processed event, raw HTTP retrieval can request:

```text
GET /v1/responses/{response_id}?stream=true&starting_after={sequence_number}
```

The retrieve API reference defines `starting_after` as the sequence number of the event after which streaming should start.

**Precise contract boundary.** Current official documentation establishes `sequence_number` as the resume cursor and `starting_after` as an exclusive resume position. The documentation reviewed for C1 does **not** state a stronger delivery contract such as:

- sequence numbers are globally unique outside one Response;
- every integer is present with no gaps;
- events are delivered exactly once;
- reconnect can never redeliver an event under all failure races.

Accordingly, C1 does not infer any of those properties.

Sources:

- Background mode: cursor tracking and reconnect examples.
- Get a model response API reference: `starting_after`.

### Retrieval and recovery after stream loss

**Documented.** There are two distinct recovery paths for a retained background Response:

1. retrieve the current Response object by ID with `GET /v1/responses/{id}`; or
2. if it was originally created with streaming enabled, reopen a stream using `stream=true` and `starting_after=<last sequence_number>`.

The first recovers current object state/result; the second resumes incremental events after the caller's cursor. Both remain subject to the C0 retention boundary.

**Documented.** Repeated `GET` retrieval is the polling mechanism OpenAI shows for background work while status remains `queued` or `in_progress`.

Sources:

- Background mode: polling and stream-resume examples.
- Get a model response API reference.

### Duplicate retrieval and duplicate-event handling

**Documented.** Polling intentionally performs repeated retrieval of the same Response ID. For stream recovery, `starting_after` lets the caller resume after the last recorded `sequence_number`, rather than intentionally replaying all earlier events.

**Gap.** The current official Responses documentation reviewed for C1 does not specify an exactly-once event-delivery guarantee, an explicit duplicate-event delivery policy, an ETag/version precondition for retrieval, or a separate event-acknowledgement protocol. C1 therefore treats the cursor as the documented resume mechanism, not as proof of exactly-once processing.

Sources:

- Background mode.
- Get a model response API reference.

### Cancellation

**Documented.** Only Responses created with `background=true` can be cancelled through the Response cancellation endpoint. The background guide says cancelling twice is idempotent: subsequent cancellation calls return the final Response object.

**Documented.** Synchronous-response cancellation is transport-coupled instead: the background guide instructs the client to terminate the connection.

Source: Background mode.

### Failed and incomplete responses; partial output

**Documented.** Official background-streaming examples distinguish completed, failed, and incomplete terminal updates. A failed Response carries an `error` object; an incomplete Response carries `incomplete_details`.

**Documented.** `incomplete` does not imply that useful visible output exists. The reasoning guide documents that `max_output_tokens` can produce an incomplete Response before any visible output token is generated. Conversely, the Structured Outputs guide demonstrates inspecting `response.output` when handling an incomplete Response and warns that generated structured content may be partial/truncated.

**Contract boundary.** C1 therefore records `failed` and `incomplete` as terminal object states with diagnostic fields, but does not assume a guaranteed amount of recoverable partial output for either state.

Sources:

- Background mode: streaming terminal-update example.
- Create a model response API reference: `error`, `incomplete_details`, and `output`.
- Reasoning models guide: incomplete generation can precede visible output.
- Structured model outputs guide: incomplete/truncated output handling.

### Request IDs, retries, and duplicate starts

**Documented.** OpenAI's official Ruby SDK reference exposes the HTTP `x-request-id` on top-level Responses and recommends logging request IDs for troubleshooting. This is request/transport metadata, distinct from the durable Response object's `response.id`.

**Documented.** The same SDK reference says its retry policy may retry replayable requests carrying a non-empty `Idempotency-Key` header under transport-failure conditions.

**Gap / no stronger claim.** The current Responses `POST /v1/responses` create reference and background-mode guide reviewed for C1 do not document a Responses-specific idempotency-key contract, duplicate-create lookup, or a rule that retrying an ambiguous create is guaranteed to return the original `response.id`. Therefore C1 does **not** claim that `x-request-id` deduplicates starts, nor that duplicate starts are prevented by the documented Responses object lifecycle.

Sources:

- OpenAI Ruby API library reference: response metadata/request IDs and retry behavior.
- Create a model response API reference.
- Background mode.

### C1 documented gaps

The following desired semantics were **not established** by the current official Responses documentation reviewed for this step:

- an exactly-once or explicitly at-least-once event-delivery guarantee;
- gap-free or globally unique `sequence_number` semantics beyond its documented use as a resume cursor;
- an event acknowledgement/commit protocol separate from `starting_after`;
- ETag, object-version, or conditional-retrieval semantics for polling;
- a Responses-specific documented guarantee that ambiguous duplicate `POST /v1/responses` starts are deduplicated;
- a guarantee that failed or incomplete Responses contain any minimum amount of partial visible output.

No Binnacle design choice is made from these gaps in C1.

## C2 — Map Responses concepts to Binnacle

C2 compares the C0–C1 Responses semantics with the current Binnacle contract in `docs/tools/run_command.md` and the implementations in `src/binnacle/tools/run_command.py`, `job_status.py`, `stop_job.py`, `jobs.py`, and `job_owner.py`. This is a design mapping only; no product contract is changed here.

### Mapping table

| Responses concept | Binnacle current / candidate | Classification | Rationale |
| --- | --- | --- | --- |
| `response.id` | Existing `job_id` returned by `run_command` and accepted by `job_status` / `stop_job` | `copy_semantics` | Both are stable handles used by later calls after the initiating call returns. Binnacle already persists the handle in the job directory. |
| `background=true` | Existing `background=true`, automatic background policy, or wait-boundary handoff from `run_command` | `adapt_semantics` | The intent matches asynchronous handoff, but Binnacle may first wait up to `wait_seconds` and can finish synchronously; OpenAI background mode is a hosted request mode rather than a local process-owner policy. |
| `queued` / `in_progress` | Current `running`; no public queue state | `adapt_semantics` | `in_progress` is close to `running`, but Binnacle has no documented public queue phase. Adding `queued` without a real queue would invent state. |
| `completed` / `failed` / `cancelled` / `incomplete` | Current terminal `exited` plus `exit_code`, `signal`, and internal `termination_reason`; legacy `unknown` remains possible | `adapt_semantics` | A local process has richer OS termination facts. Exit 0, nonzero exit, signal, explicit stop, owner restart, and host reboot should not be collapsed merely to imitate hosted-model statuses. |
| retrieve Response by ID | Existing `job_status(job_id)` reads durable state from disk across MCP calls/restarts | `copy_semantics` | This is the closest direct analogue: stateless control-plane retrieval over separately owned durable work. |
| repeated polling | Existing `job_status(job_id, wait_seconds=...)` | `copy_semantics` | Repeated read-only retrieval is already supported; Binnacle additionally offers bounded blocking to reduce polling frequency. |
| stream `sequence_number` + `starting_after` | No public output cursor today; `log_bytes` reports size and `log_tail` returns a tail | `adapt_semantics` | A monotonic resume position is useful, but `log_bytes` is not documented as a read cursor and `tail_lines` can repeat output. Any future cursor must be defined for the local append-only log rather than copied as an SSE event sequence. |
| reconnect stream after transport loss | Later MCP call can invoke `job_status`; full `out.log` remains on disk | `adapt_semantics` | Durable reattachment exists, but Binnacle has no public SSE/event-stream transport to reconnect. Retrieval/delta reading is the relevant local analogue. |
| cancel Response | Existing `stop_job(job_id)` | `copy_semantics` | Both target a stable object ID and are idempotent for terminal work. Binnacle's concrete behavior is TERM → KILL over the process tree and must remain explicit. |
| Response `error` / `incomplete_details` | `exit_code`, `signal`, `termination_reason`, summaries; `unknown` for legacy orphan/reused-pid cases | `adapt_semantics` | Diagnostic separation is useful, but hosted generation failure reasons do not map one-for-one to OS process termination. |
| stored terminal Response | Durable `meta.json` plus complete `out.log` in the job store | `copy_semantics` | Binnacle already persists terminal metadata and output independently of the MCP session, which is the lifecycle property that matters for reattachment. |
| hosted retention window / `store=true` | Local self-pruning job store with running-job protection | `do_not_copy` | The hosted 10-minute/30-day storage policy is service-specific. Binnacle should retain its local storage policy unless separate local evidence justifies changing it. |
| SSE event taxonomy (`response.created`, deltas, terminal events) | No equivalent public event stream | `do_not_copy` | Recreating hosted SSE event types would add a second abstraction over an append-only process log without evidence it is needed. A cursor/delta read can be much smaller. |
| HTTP `x-request-id` | Internal Binnacle `call_id` telemetry | `do_not_copy` | Request tracing and durable work identity are different concerns. `job_id` is already the public lifecycle identity; exposing another request ID would not solve reattachment. |
| create-request idempotency / duplicate-start protection | `run_command` starts a new local job per invocation; no public idempotency key | `adapt_semantics` | Duplicate starts are a real orchestration concern, but C1 found no Responses-specific documented create-deduplication contract to copy. If Round 2 needs start idempotency, it requires a Binnacle-specific contract. |

### Current Binnacle lifecycle facts relevant to the mapping

The current public path is already a short-lived control plane over durable execution:

```text
run_command
  |
  +-- finishes within wait --> state=exited + output/result metadata
  |
  +-- still running --------> state=running + job_id
                                  |
                                  +--> job_status(job_id)
                                  |      +--> running
                                  |      +--> exited + exit/signal metadata
                                  |      +--> unknown (legacy/orphan exceptional case)
                                  |
                                  +--> stop_job(job_id)
                                         +--> durable terminal state
```

`job_status` derives state from disk, and managed deployments place process ownership in the stable jobs service rather than the MCP process. `meta.json` and `out.log` are therefore the durable object; an individual MCP call is only a transport/control interaction. This is structurally the same separation C1 identified between a background Response object and one streaming connection, although the transports and payload semantics differ.

### Familiar names versus semantic accuracy

Using familiar field names can reduce translation work for clients and models when the concepts are genuinely equivalent. `job_id`, `status`/`state`, retrieval by ID, and cancellation are already easy to recognize. There is no evidence, however, that an OpenAI model is guaranteed to use an OpenAI-shaped local API more correctly merely because names resemble the Responses API.

A wholesale rename would also create concrete problems:

- changing `job_id` to `response.id` would add no capability and break the established local vocabulary;
- adding `queued` when there is no public queue would misdescribe reality;
- replacing `exited` with `completed` would hide the distinction between exit 0, nonzero exit, signal termination, and interruption unless additional fields restored it;
- calling every explicit or external signal `cancelled` would erase whether `stop_job` actually requested the termination.

The useful principle for Round 2 is therefore semantic familiarity, not lexical imitation: reuse a familiar name only when its invariant matches the local process model.

### Minimal candidate lifecycle

This was the **compatibility-first candidate for Round-2 evaluation** at C2; it was not a product change:

```text
start
  |
  +-- synchronous terminal --> exited
  |                            + exit_code / signal / termination_reason
  |
  +-- durable handoff -------> running
                                |
                                +-- retrieve/wait --> running
                                |
                                +-- natural end ----> exited
                                |
                                +-- stop_job -------> exited
                                |
                                +-- legacy loss ----> unknown
```

Keep the existing lifecycle and stable `job_id`; treat terminal outcome fields as authoritative. The smallest Responses-derived extension worth evaluating later is not a new status taxonomy but an **incremental output position** for retrieving only bytes/events after a caller's last acknowledged position. Its exact contract belongs with Lane B / Round 2, not C2.

This candidate deliberately does **not** add `queued`, SSE, a hosted-style `store` flag, or separate `completed`/`failed`/`cancelled` public states. Those additions are unnecessary to obtain the key reattachment property already present in Binnacle.

### Rejected over-engineered option

Reject, for Round-2 consideration, a literal Responses clone shaped like:

```text
job response object
  status = queued | in_progress | completed | failed | cancelled | incomplete
  store = true|false
  response-style event stream with sequence_number
  starting_after reconnect endpoint
  request_id + idempotency key
  cancel endpoint
  hosted-style retention timers
```

This option duplicates existing `run_command` / `job_status` / `stop_job` responsibilities, introduces states with no current local meaning, adds an SSE/event layer over a durable log, and imports hosted retention/request semantics that C0–C1 showed are coupled to the Responses service. It would increase migration and compatibility cost without being required for durable reattachment.

### C2 boundary

C2 mapped and classified concepts only; it did not freeze a new public API, choose the cursor representation, rename existing fields, or decide Lane D-dependent MCP capabilities. C3 below supplies the lane recommendations while still leaving the public API unfrozen for R1 synthesis.

## C3 — Final recommendations

### Responses ideas Binnacle should strongly consider

These are Lane C recommendations for the R1 synthesis gate, not a frozen Round-2 API.

1. **Preserve stable durable identity across foreground turns.** Keep `job_id` as the public handle for work that outlives `run_command`. Responses validates the general pattern of returning a stable object ID and retrieving it later; Binnacle already implements this with disk-backed state.
2. **Keep execution lifetime independent of transport/control-call lifetime.** A lost ChatGPT/MCP foreground interaction must not own the local process lifetime. Binnacle's stable job owner plus disk-backed `job_status` already provides the local analogue of a background Response surviving a dropped stream.
3. **Add a bounded incremental-output cursor/delta contract.** Responses demonstrates the usability of retaining a monotonic resume position and asking for data after it. Binnacle should adapt that idea to its append-only merged job log so later turns can retrieve only unseen output rather than repeatedly receiving a tail.
4. **Keep retrieval and cancellation idempotent at the durable-job boundary.** Repeated status retrieval must be safe, and `stop_job` should continue returning the already-terminal state rather than turning a retry into an error. This matches the robust retry shape documented for background Responses cancellation without copying its hosted implementation.
5. **Keep terminal outcome separate from lifecycle state.** Preserve local facts such as public `exit_code` / `signal` and durable `termination_reason` instead of forcing process outcomes into Responses `completed` / `failed` / `cancelled` / `incomplete`. A small lifecycle plus explicit outcome metadata is more faithful to local execution.

### Ideas Binnacle should not copy

- **Do not clone the six Responses statuses.** Binnacle has no public queue phase, and local process exit semantics do not map one-for-one to model-generation terminal states.
- **Do not add SSE merely to resemble Responses streaming.** The current need is efficient reattachment and unseen-output retrieval; an event-stream transport is not required to obtain those properties.
- **Do not copy hosted `store=true` or OpenAI retention timers.** Binnacle has a local durable job store with its own pruning and running-job protection; retention should remain a local operational policy.
- **Do not expose request-tracing identity as job identity.** Internal `call_id` and HTTP-style request IDs are observability metadata; `job_id` is the durable work identity.
- **Do not assume Responses-style create idempotency.** C1 found no Responses-specific documented guarantee that an ambiguous repeated create returns the original Response. Any duplicate-start protection would need a separately specified Binnacle contract.

### Decisions that require Lane D capability evidence

Round 2 must not rely on the following until Lane D reports what the current ChatGPT MCP host actually supports:

1. **MCP Tasks/deferred work as a public lifecycle primitive.** If ChatGPT can start, query, cancel, and later collect a real MCP Task across the relevant session/turn boundaries, Round 2 can evaluate whether that should wrap or complement `job_id`. If not, durable Binnacle job identity remains the required mechanism.
2. **Protocol-level `input_required` / elicitation.** A future `needs_input` state or resumable interactive workflow is justified only if Lane D demonstrates end-to-end ChatGPT support. A normal assistant follow-up question is not evidence for protocol elicitation.
3. **What survives MCP session and ChatGPT turn changes.** Lane D must establish whether task/deferred identities or elicitation state survive a new MCP transport/session and later ChatGPT turn. Binnacle must keep any state that the host does not reliably preserve.
4. **Whether MCP-native cancellation/result collection is usable from ChatGPT.** Do not replace `stop_job` or `job_status` with spec-level task operations merely because FastMCP or the MCP specification supports them; current-host evidence is required.

None of these Lane D questions blocks the compatibility-first lifecycle from C2: `job_id`, durable disk state, `job_status`, and `stop_job` remain sufficient for non-interactive reattachment.

### Implications for Lane B cursor/delta design

Lane C does not choose Lane B's byte-offset versus sequence/event representation, but the Responses evidence imposes useful design tests:

- **Cursor is per durable job, not per ChatGPT/MCP session.** A later turn with only `job_id` plus the saved cursor must be able to continue.
- **Define the resume boundary precisely.** Responses documents `starting_after` as exclusive. Binnacle should likewise make it unambiguous whether the cursor names the last consumed position or the first unread position.
- **State retrieval and output progression are separate concerns.** A caller must still learn `running`/terminal state even when no new output exists; quiet jobs cannot require fake events to advance lifecycle.
- **Bound every delta response.** Lane B's hard returned-log cap remains necessary even with a cursor. The result needs a deterministic maximum and a next position so a giant append cannot recreate the context-explosion hazard.
- **Terminal output must remain retrievable incrementally.** Reaching `exited` must not force the caller to request the entire final log; the caller should be able to drain remaining unseen output under the same bounded contract.
- **Do not promise exactly-once delivery unless Binnacle itself can prove it.** C1 found no such Responses guarantee. The local contract should define deterministic cursor behavior and make retries safe rather than relying on an inferred transport guarantee.
- **Specify invalidation and UTF-8 behavior.** A byte-offset design must define character-boundary handling; every design must define what happens if retention/pruning makes an old cursor unusable.
- **Preserve old clients.** The cursor/delta path should be optional or additive so existing `job_status(job_id, tail_lines, wait_seconds)` calls retain their current meaning during migration.

A byte offset over the immutable/append-only `out.log` is therefore a plausible low-complexity candidate, while a synthetic event sequence is justified only if Lane B can show benefits beyond what an offset provides. That choice remains provisional for R1 synthesis.

### Provisional Round-2 naming and status vocabulary

The following vocabulary is proposed for discussion, explicitly **not frozen**:

| Concept | Provisional vocabulary | Reason |
| --- | --- | --- |
| Durable work identity | `job_id` | Existing public contract; already carries the Responses-like stable-ID invariant. |
| Lifecycle field | `state` | Preserve compatibility rather than rename to `status` solely for resemblance. |
| Active state | `running` | Matches the current local process fact. Do not invent `queued` without a real queue. |
| Normal/abnormal terminal state | `exited` | Keep one lifecycle terminal and describe outcome with structured fields. |
| Exceptional legacy state | `unknown` | Preserve only for cases where the process is gone and no terminal record exists; do not treat it as a normal success/failure category. |
| Terminal outcome | `exit_code`, `signal`; consider exposing `termination_reason` | `exit_code` / `signal` are public today; `termination_reason` is durable internal metadata today and should not be presented as already-public. |
| Incremental read position | `cursor` / `next_cursor` | Familiar resume vocabulary; exact representation and exclusivity belong to Lane B/Round 2. |
| Incremental output | `output_delta` (candidate) | Makes unseen output distinct from the existing repeated `log_tail`; exact field/tool placement remains open. |
| Cancellation action | `stop_job(job_id)` | Existing name reflects actual TERM → KILL process semantics and is already idempotent for terminal jobs. |

If Round 2 introduces a higher-level abstraction above the existing tools, it may choose normalized names there, but the compatibility adapter should not silently change the meaning of current fields.

### Cold-start handoff

A reader entering at R1 synthesis can use the following decision frame without this conversation:

- **Confirmed from OpenAI docs:** background Responses have stable IDs, durable retrieval within retention, explicit terminal states, idempotent cancellation, and resumable background streaming using `sequence_number` / `starting_after`.
- **Confirmed from current Binnacle code/spec:** long commands already have stable `job_id`, process ownership outside the MCP call, durable `meta.json` + `out.log`, disk-backed `job_status`, and idempotent terminal `stop_job`.
- **Primary gap:** Binnacle repeatedly returns output tails and has no public incremental-output cursor; this is the Responses concept with the clearest direct value to adapt.
- **Do not infer:** exactly-once event delivery, duplicate-create deduplication, or better model behavior merely from OpenAI-shaped naming.
- **R1 dependencies:** Lane B must supply the concrete cursor/delta alternatives and safety evidence; Lane D must establish which MCP Tasks/elicitation/session-survival features the current ChatGPT host actually supports.

Lane C is complete at this point. The next consumer is the R1 synthesis gate; no product API is frozen by this report.
