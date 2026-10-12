# Job Awareness hints in production (default off)

Status: implemented on `impl/job-awareness-prod-enable-20261012`
(2026-10-12), based on the reviewed STRUCT branch `e59a846`. The switch is
**off** by default. Owner decision 2026-10-12: wire the E2 session route and
the STRUCT hint into the production MCP server for daily ChatGPT use. The E2
lab study, its server, connector and modules are unchanged.

## What the user sees

1. In a ChatGPT conversation, `run_command` starts a background job
   (`state: "running"`, a `job_id`).
2. The job exits later.
3. The next Binnacle tool call **from the same conversation** (any of the
   six ChatGPT tools) returns its normal result plus one structured field:

   ```json
   "job_awareness_hint": "[Binnacle job reminder] Background job 8b59128fe210, started earlier in this conversation, has finished (exit_code 0). Its final output has not been read here; call job_status with job_id 8b59128fe210 to read it."
   ```

4. The hint is sent once per job. It is not sent when the conversation
   already read the job's terminal state with `job_status` (that `job_id`)
   or stopped the job with `stop_job`.

The field is in `structuredContent`, which ChatGPT shows to the model. Text
blocks are not used: ChatGPT drops an extra text block when
`structuredContent` exists, and `_meta` is not visible to the model (E2
CV-F, OpenAI Apps SDK documentation).

## Design

### Gate (every `tools/call`)

| Check | Rule | Failure |
| --- | --- | --- |
| Switch | `[job_awareness] hints_enabled = true` | No Job Awareness code is imported at all |
| Client | Client name is **exactly** one of `client_names` (default `openai-mcp`, `openai-mcp(ChatGPT)`) | Original result; no binding; no log line |
| Route | Reviewed core parser `session_route.route` through `route_call`: one `X-OpenAI-Session` and one `X-OpenAI-Subject` header, exact grammar, equal to `_meta["openai/session"]` / `_meta["openai/subject"]` of the same call | Original result; `event=ja_route status=NO_SESSION/NO_META/MALFORMED/MISMATCH` |

The route key is `kd = (epoch, d_subj, d_sess)`: HMAC-SHA256 digests under
a 32-byte key that exists only in memory for one process. Raw platform
values are never stored, logged or returned. Codex, Claude and every other
client fail the client check; they also do not send the platform headers.

### Binding, acknowledgement, emission

All state is in memory and owner scoped (`mcp/job_awareness_live_ledger.py`):

- **Bind.** A `run_command` result with `state == "running"` and a valid
  12-hex `job_id` binds that job to the caller's `kd`. Caps: 8 rows per key
  (finished rows are dropped first; 8 pending rows refuse with
  `reason=key_full`), 256 keys (least recently used dropped), 24 h per row.
- **Acknowledge.** A `job_status` result for that `job_id` that shows
  `state == "exited"`, or a `stop_job` call for it, marks the row `ACKED`.
- **Emit.** Under the reviewed per-key fence (`session_fence.FenceSet`,
  5 s), the key's own `PENDING` jobs are read through the backend's
  `job_state` (in a worker thread, 2 s timeout each). At most two `exited`
  jobs are rendered with fixed words (job ids and the exit code or signal
  only; at most 512 UTF-8 bytes). The rows become `EMITTED` only after the
  insert succeeded, just before the result returns. Every lookup names the
  caller's key; there is no global job index, so a job never reaches another
  conversation.

### STRUCT carrier

`insert_struct_hint` follows the reviewed routed render
(`HintAdapter._render`, STRUCT branch) and reuses its parts:

- `walk` / `Meter` with the serverInfo stamp reserved, the 256 KiB wire
  budget and the 1024-byte growth cap;
- `Schema` (the reviewed closed keyword subset) to validate the original and
  the hinted structured content;
- `insert_hint`: one exact JSON mirror is re-serialized in its own format;
  two mirrors, a text that matches both formats (STRUCT-01) or a JSON object
  equal to the structure in another format suppress; plain tool text is
  never rewritten;
- `declares_hint_field`: the field must be exactly
  `{"type": "string", "maxLength": 512}` and optional.

The full `HintAdapter` is not used. Production tools are mounted
(`FastMCPProviderTool`), which the adapter's provenance rule rejects, and
their output schemas are open. Production therefore applies the same field
rule to an open schema (`declares_open_hint_field`).

### Fail-closed rules

The original result object returns, and the jobs stay `PENDING` (a later
call may carry the hint), when any of these hold. Each writes
`event=ja_hint outcome=suppressed reason=<reason>`:

| Reason | Cause |
| --- | --- |
| `busy` | Fence not acquired within 5 s |
| `error_result` / `result_type` | Error result or an unknown result type |
| `no_structure` | No `structuredContent` |
| `schema` | The tool's schema cannot declare the field (unsupported keyword, closed schema, field present) |
| `invalid_original` | The original structure does not validate |
| `insert` | Field already present, more than one mirror, or re-validation failed |
| `unsupported` | Walk limits, non-text content block, ambiguous mirror, hint over 512 bytes |
| `growth` | The result would grow by more than 1024 bytes |
| `stamp` | No serverInfo stamp to reserve |
| `render` | Renderer refused the input |
| `state` | A row stopped being pending before the commit |
| `internal` | Any exception in the hint path |

An unreadable job state (`job_state` raised or timed out) is not a
candidate for this call. A job the store no longer knows is forgotten.

### Modules

| Module | Role | Origin |
| --- | --- | --- |
| `features/commands/job_awareness/session_route.py` | Parser, HMAC epoch keyer | Reviewed E2, unchanged |
| `features/commands/job_awareness/session_fence.py` | Per-key asyncio fence | Reviewed E2, unchanged |
| `mcp/job_awareness_route.py` | `route_call` request-local extraction | Moved unchanged from the lab module, which re-exports it |
| `mcp/job_awareness_hint_struct.py`, `_schema.py`, `_walk.py`, `_identity.py` | STRUCT insertion, schema subset, bounded walk | Reviewed E2, unchanged |
| `mcp/job_awareness_live.py` | Middleware, schema advertisement, carrier, journal lines | New |
| `mcp/job_awareness_live_ledger.py` | In-memory owner-scoped ledger | New |
| `job_awareness_composition.py` | Joins core and MCP; builds the keyer and fence | New; imported only by `application.py` when on |

Lab-only and never reachable from production: `session_lab`,
`session_binding`, `session_serving`, `session_snapshot`,
`session_emission`, `mcp/job_awareness_session` (lab fields),
`mcp/job_awareness_hint` (synthetic adapter), `mcp/job_awareness_hint_routed`,
and the E2 lab server. Import-linter contracts:

- `job-awareness-lab-not-in-production`: server, application and CLI never
  import a lab module (the reviewed route, fence and STRUCT modules left the
  list because production now reaches them when the switch is on);
- `job-awareness-live-no-lab` (new): the production modules never import a
  lab module, the synthetic grants or receipt store, or `tests`;
- `job-awareness-live-only-via-composition` and
  `job-awareness-composition-only-via-application` (new, protected).

`tests/contracts/job_awareness/test_e2_no_path.py` probes a fresh
interpreter: off (default and explicit) loads no Job Awareness module; on
loads only the production set above and no lab module.

## Journal lines

Logger `binnacle.job_awareness`. Values pass a character allowlist and the
raw-value scan; a refused line is written as `fields=refused`.

```text
event=tool_config tool=job_awareness hints_enabled=false            # every start
event=job_awareness_config hints_enabled=true clients=2 carrier=struct   # start, when on
event=ja_bind outcome=bound job=<id> call=<call> tool=run_command ja_key=<16hex>
event=ja_bind outcome=refused reason=key_full job=<id> ...
event=ja_ack job=<id> call=<call> tool=job_status ja_key=<16hex>
event=ja_hint outcome=emitted jobs=<id[,id]> call=<call> tool=<tool> ja_key=<16hex>
event=ja_hint outcome=suppressed reason=<reason> [jobs=...] call=<call> tool=<tool> ja_key=<16hex>
event=ja_route status=<NO_SESSION|NO_META|MALFORMED|MISMATCH|UNKNOWN> call=<call> tool=<tool>
```

`call` joins the line to the `event=tool_call` / `event=tool_result` lines
of the same call. `ja_key` is the first 16 hex characters of `d_sess` under
the current epoch key; it changes on every restart and cannot be linked to
the `oai_session` field of the logging middleware.

## Output-schema impact (measured)

Enabling changes `tools/list` **for the ChatGPT client names only**. Each
of the six ChatGPT tools gains the optional `job_awareness_hint` property;
nothing else changes. Measured on this branch (in-process, streamable HTTP):

| Client | `tools/list` bytes off | on | Delta | Schemas changed |
| --- | --- | --- | --- | --- |
| `openai-mcp` | 10419 | 10749 | +330 | 6 of 6 |
| `openai-mcp(Codex)`, `claude-code`, other | 10419 | 10419 | 0 | none (byte identical) |

A hinted result grows by the field (about 230 bytes for one job, at most
512 + 22 bytes) and, if the tool mirrors its structure as JSON text, the
mirror by the same amount; the growth cap is 1024 bytes.

ChatGPT caches the connector tool list. After enabling (and after
disabling), refresh the connector so its cached output schemas match:
`chatgpt-refresh --browser chrome "Raspberry Pi MCP"` (chatgpt-mcp-dev
skill). ChatGPT does not validate results against the cached schema, so a
hint can reach the model before the refresh; the refresh keeps the declared
contract and the result consistent. Strict clients (Codex, Claude) never
receive the field and never see it declared.

## Enable and disable (kill switch)

Only a configuration change and the normal MCP restart are needed. Never
restart `binnacle-jobs.service` for this; jobs keep running either way.

Enable (after the gated deploy of this branch):

```bash
cp ~/.config/binnacle/config.toml ~/.config/binnacle/config.toml.before-ja-prod-$(date +%Y%m%dT%H%M%S)
cat >> ~/.config/binnacle/config.toml <<'EOF'

[job_awareness]
hints_enabled = true
EOF
# quiet check: no ChatGPT call in flight (last tool_result is the last tool_call)
journalctl --user -u binnacle-mcp -o cat --since -2min | grep -E 'event=tool_(call|result)' | tail -4
systemctl --user restart binnacle-mcp.service
journalctl --user -u binnacle-mcp -o cat --since -1min | grep -E 'tool=job_awareness|event=job_awareness_config'
#   expect: event=tool_config tool=job_awareness hints_enabled=true
#           event=job_awareness_config hints_enabled=true clients=2 carrier=struct
.venv/bin/binnacle doctor
chatgpt-refresh --browser chrome "Raspberry Pi MCP"
```

Disable (kill switch): set `hints_enabled = false` (or delete the
`[job_awareness]` section), run the same quiet check and
`systemctl --user restart binnacle-mcp.service`, then verify
`event=tool_config tool=job_awareness hints_enabled=false` and that no
`event=job_awareness_config` line follows the restart. Refresh the connector
again so ChatGPT drops the declared field. With the switch off, the
application does not import any Job Awareness module, and `tools/list` and
every result are byte identical to a build without the setting.

Environment override for a one-off test: `BINNACLE_JOB_AWARENESS__HINTS_ENABLED=true`.

## Tests

- `tests/unit/core/test_job_awareness_live_units.py`: ledger (owner scope,
  once-only, caps, TTL), renderer, schema advertisement and the exact field
  rule, every carrier suppression reason (including STRUCT-01 and the growth
  cap), journal field validation, route-outcome gate, lab re-export pin.
- `tests/integration/test_job_awareness_live.py` (real `create_application`,
  strict FastMCP client over stateful streamable HTTP, output-schema
  validation on): default-off golden against an absent setting with a
  negative control, ChatGPT-only schema advertisement, once-only hint,
  two-conversation isolation, Codex/Claude/unknown clients, missing or
  mismatched or malformed route, acknowledgement by `job_status` and
  `stop_job`, two jobs per hint, read failure and recovery, restart forgets
  bindings, no raw value in the journal, wire shape.
- `tests/contracts/job_awareness/test_e2_no_path.py`: fresh-interpreter
  module probes for off and on; the import contract lists.

## Not claimed and open risks

- Correlation, not authentication: the session value is a platform-asserted
  conversation key (E2: `SESSION_IS_PER_CONVERSATION`, isolation PASS). A
  holder of the bearer token or tunnel path who replays a live value can
  receive that conversation's hint (E2 T5, out of scope). The hint carries
  only a job id and an exit code of the conversation's own job.
- Memory only: a restart (including a dev-mode auto-reload after a `src/`
  change) forgets every binding, so a job that ends after a restart is
  never hinted. This fails closed.
- The hint is advisory text; whether the model acts on it is not measured
  here (the E2 A/B study measures that separately).
- A busy fence, an unreadable job state or a suppression delays the hint to
  a later call; if the conversation makes no later Binnacle call, no hint is
  seen.
- Cancellation after the commit and before the transport sends the result
  can lose one hint (at most once, never twice).
- Darwin: the composition is host neutral, but only Linux was tested with
  this switch on.
