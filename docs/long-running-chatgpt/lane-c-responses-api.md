# Lane C — OpenAI Responses API reference design

Status: **Round 1 plan; do not execute before coordinator start approval.**

Worktree: `~/Projects/binnacle-longrun-c-responses`
Branch: `investigation/longrun-c-responses`
Primary worker: one persistent ChatGPT conversation.
Product-code changes: forbidden.

## Mission

Study the **current** OpenAI Responses API mechanisms for long-running/background work and extract the smallest set of lifecycle ideas that Binnacle should emulate.

The purpose is not to clone the API mechanically. The purpose is to exploit a design that OpenAI itself uses for long-running model operations and that ChatGPT/model behaviour is likely to encounter frequently: stable IDs, explicit terminal states, retrieval after foreground disconnect, incremental events/cursors where available, cancellation, and resumability.

Because OpenAI APIs can change, Lane C must use current official OpenAI sources during execution. Do not rely on remembered API details when current documentation can answer them.

## Inputs

Read first:

- `docs/long-running-chatgpt/README.md`
- current official OpenAI Responses API documentation;
- current official background-mode documentation;
- current official streaming/events/retrieval/cancel documentation relevant to Responses;
- existing Binnacle `run_command`, `job_status`, `stop_job` contracts for comparison.

Prefer official OpenAI documentation over third-party summaries for normative behaviour.

## Output

`docs/long-running-chatgpt/lane-c-report.md`

The report must cite current public sources with retrieval date and distinguish documented behaviour from interpretation.

## Step C0 — Freeze the current Responses lifecycle

Target: 8–12 minutes.

Tasks:

1. Verify the current documented way to start a long/background Response.
2. Record identifiers and lifecycle/status fields.
3. Record terminal states and failure/cancellation semantics.
4. Verify how a client retrieves state/result later without holding the original request open.
5. Verify documented retention/expiry caveats that matter to reattachment.
6. Create the report skeleton with links/citations.

Exit criteria:

- one concise lifecycle diagram;
- all normative claims sourced to current official OpenAI docs;
- no Binnacle design recommendation yet.

## Step C1 — Streaming, cursor, reconnect and idempotency semantics

Target: 10–15 minutes.

Investigate only documented mechanisms relevant to interrupted long work:

- event ordering/sequence identifiers;
- whether/how streaming can resume after disconnect;
- retrieval after stream loss;
- duplicated retrieval/event handling;
- cancellation;
- partial/incomplete/failed results;
- request identifiers or idempotency concepts relevant to duplicate starts;
- any distinction between API object persistence and transport connection persistence.

If a desired concept is not documented, say so instead of inferring it.

Exit criteria:

- transport lifecycle and durable-object lifecycle are explicitly separated;
- cursor/sequence claims are precise and sourced;
- gaps are listed.

## Step C2 — Map Responses concepts to Binnacle

Target: 10–15 minutes.

Create a mapping table like:

```text
Responses concept          Binnacle current / candidate
-------------------------  -----------------------------
response.id                job_id
background=true            background job handoff
queued/in_progress/...     current state / candidate lifecycle
retrieve response          job_status or future retrieve
stream event sequence      candidate output/event cursor
cancel response            stop_job
stored terminal result     durable meta.json + out.log
```

For every row classify:

- `copy_semantics`: concept can be imitated closely;
- `adapt_semantics`: useful idea but local-process differences matter;
- `do_not_copy`: hosted-API detail that would add complexity without value.

Explicitly assess whether adopting familiar field/status names would simplify model behaviour, while avoiding the unsupported claim that an OpenAI model is guaranteed to use an OpenAI-shaped API better.

Exit criteria:

- mapping table complete;
- at least one minimal candidate lifecycle and one over-engineered option rejected.

## Step C3 — Final recommendations

Target: 8–12 minutes.

Finish `lane-c-report.md` with:

1. five or fewer Responses ideas Binnacle should strongly consider;
2. ideas Binnacle should not copy;
3. exact decisions that require Lane D capability evidence;
4. implications for Lane B cursor/delta design;
5. a proposed naming/status vocabulary for Round 2, explicitly provisional.

Self-review the report so a cold-start agent can use it without the original conversation.

## Lane C completion reply

```text
STEP: C3
STATUS: PASS | BLOCKED | FAIL
ARTIFACTS: docs/long-running-chatgpt/lane-c-report.md
COMMIT: <sha or none>
FINDINGS: <top findings>
NEXT: R1 synthesis gate
```

Commit the report on the lane branch. Do not merge it directly.
