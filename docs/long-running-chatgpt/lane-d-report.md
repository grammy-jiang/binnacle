# Lane D capability report

## D0 static capability inventory

Inventory date: 2026-09-29 (Australia/Sydney). This checkpoint is static/read-only: no temporary endpoint, live connector, service restart, or production mutation was performed.

### Capability matrix

| Feature | MCP specification / protocol | FastMCP / Python SDK support in installed environment | Observed ChatGPT support | Current Binnacle/tunnel state | D0 disposition |
| --- | --- | --- | --- | --- | --- |
| Modern stateless MCP lifecycle | MCP 2026-07-28 is the current released core revision. It removes the initialize/initialized lifecycle for modern requests; requests carry protocol/client/capability metadata and may use server/discover. | mcp/mcp-types 2.1.1 knows 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25, and 2026-07-28. FastMCP is 4.0.0b5. | **Observed.** A production log entry at 2026-09-29 00:27:52+10:00 identifies clientInfo.name=`openai-mcp (ChatGPT)`, version `1.0.0`, protocol `2026-07-28`, using `server/discover`. | Binnacle serves `mcp.http_app()` behind uvicorn on `127.0.0.1:8000/mcp`; tunnel-client routes the main channel to it as `http-streamable`. | Supported end-to-end for ordinary tool calls. |
| Foreground elicitation via legacy server-to-client request | Pre-2026 eras support `elicitation/create` over the request/session back-channel. In 2026-07-28, server-initiated requests are replaced by MRTR `input_required`. | `Context.elicit(message, response_type, ...)` exists. In FastMCP 4.0.0b5 it raises a clear `ToolError` on modern protocol and inside background tasks; it only sends `session.elicit(...)` on handshake-era foreground requests. | **Not advertised in observed ChatGPT modern capability envelope.** The 00:27:52 ChatGPT `server/discover` request has clientCapabilities containing only `experimental.openai/visibility` and `extensions.io.modelcontextprotocol/ui`; no `elicitation` member is present. | No Binnacle tool currently uses `Context.elicit()`. | Library support is not ChatGPT support. Do not design around direct `Context.elicit()` for ChatGPT; D1 should probe the modern MRTR path only if justified. |
| Multi Round-Trip Requests / `InputRequiredResult` | MCP 2026-07-28 SEP-2322 uses `resultType: "input_required"`, embedded input requests, `requestState`, retry with `inputResponses`. | **Present.** `mcp_types.InputRequiredResult` exists; FastMCP tool/prompt/resource machinery passes it through. `Context.input_responses` and `Context.request_state` expose retry data. FastMCP documents this as the modern guard/return pattern. | **Protocol support observed, client handling not proven.** ChatGPT speaks 2026-07-28, but the observed capability envelope does not advertise elicitation; therefore an elicitation-bearing `InputRequiredResult` must not be assumed to work. | Current Binnacle tools do not return `InputRequiredResult`. | Candidate for D1 bounded POC, with missing capability treated as likely gating evidence rather than worked around. |
| MCP Tasks extension | In 2026-07-28, Tasks moved out of core into `io.modelcontextprotocol/tasks`. The current Tasks extension page is marked Draft and requires per-request extension capability negotiation. It defines `tasks/get`, `tasks/update`, `tasks/cancel`, task status including `input_required`, and `resultType: "task"`. | Core FastMCP has `TaskConfig`, `TaskMeta`, `task=True` intent, and context fields `is_background_task` / `task_id`. However FastMCP explicitly requires a registered `io.modelcontextprotocol/tasks` server extension for task-enabled tools. The installed production environment has neither `fastmcp-tasks` nor `docket`. | **Not advertised.** The observed ChatGPT 2026-07-28 capabilities do not include `extensions.io.modelcontextprotocol/tasks`. | Binnacle registers no Tasks extension and has no task-enabled tools. | Not currently end-to-end available. D1 should treat this as a capability-negotiation gate; no production implementation is justified by D0. |
| Legacy experimental task vocabulary | 2025-11-25 carried experimental task vocabulary; 2026-07-28 moved Tasks to an extension and changed lifecycle. | mcp-types still exposes legacy task types for compatibility, but this is not evidence that the active server supports the 2026 extension. | No ChatGPT evidence for legacy task capability. | tunnel-client's own handshake probes use 2025-06-18 and do not advertise tasks. | Do not conflate exported compatibility types with active Tasks support. |
| Tunnel transport | MCP local transport is Streamable HTTP. The OpenAI tunnel is an outbound-only control-plane poll/response bridge. | N/A. | ChatGPT commands are observed arriving through the tunnel and are logged as `client=openai-mcp` / `openai-mcp (ChatGPT)`. | tunnel-client `0.0.12+881c9a8fed7cccbe6607cd419863bbca506b8215`; local route `transport=http-streamable` to `http://127.0.0.1:8000/mcp`; control plane uses HTTPS `/poll` and `/response` endpoints with a 30 s poll timeout. | Transport inventory complete; no change required for D0. |

### Installed versions and server construction

Production runtime package inventory, read from `/home/grammy-jiang/Projects/binnacle/.venv`:

- `binnacle-mcp 1.0.0`
- `fastmcp 4.0.0b5` / `fastmcp-slim 4.0.0b5`
- `mcp 2.1.1`
- `mcp-types 2.1.1`
- `fastmcp-tasks`: not installed
- `docket`: not installed
- `tunnel-client 0.0.12+881c9a8fed7cccbe6607cd419863bbca506b8215`

The Binnacle source constructs `FastMCP("binnacle", ...)` with static-token auth, instructions, request/tool logging middleware and client-tool visibility, then exposes `app = mcp.http_app()`. It does not register a Tasks extension. The user service runs uvicorn against `binnacle.server:app` on `127.0.0.1:8000`.

The installed `mcp_types.version` registry lists:

- handshake era: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`
- modern/stateless era: `2026-07-28`
- latest known/supported revision: `2026-07-28`

### FastMCP interaction primitives

`Context.elicit()` is available with typed response schemas and shorthand scalar/select forms. Its implementation has two important guards:

1. background task context: raises `ToolError` and directs the tool to return `InputRequiredResult`;
2. modern 2026-07-28 context: raises `ToolError` because the server-to-client back-channel no longer exists, again requiring the MRTR pattern.

The modern input path is therefore declarative: return `InputRequiredResult`, then on retry read `ctx.input_responses` and `ctx.request_state`. FastMCP 4.0.0b5 has the server plumbing to pass this control-flow result through for tools, prompts, and template resources.

FastMCP also exposes task intent through `TaskConfig(mode="forbidden"|"optional"|"required")` and `task=True`, plus `Context.is_background_task` and `Context.task_id`. That is not a self-contained task engine. The installed code explicitly requires the separate `io.modelcontextprotocol/tasks` extension (provided by `fastmcp-tasks`) before any task-enabled tool may serve.

### Client identity and capability evidence

The production journal contains several different MCP clients and they must remain separate:

- **ChatGPT:** at `2026-09-29 00:27:52+10:00`, `server/discover` carried protocol `2026-07-28`, `clientInfo={"name":"openai-mcp (ChatGPT)","version":"1.0.0"}`, and client capabilities with `experimental.openai/visibility.enabled=true` plus `extensions.io.modelcontextprotocol/ui`. No `elicitation` capability and no `io.modelcontextprotocol/tasks` extension were present.
- **tunnel-client probe:** e.g. `2026-09-29 08:41:59+10:00`, `initialize` offered `2025-06-18`, `clientInfo.name="tunnel-client"`, roots/listChanged support, and no elicitation/tasks. This is tunnel health/probe traffic, not ChatGPT.
- **binnacle-doctor:** e.g. `2026-09-29 09:56:26+10:00`, `initialize` offered `2025-06-18`, `clientInfo.name="binnacle-doctor"`, with no elicitation/tasks. This is local doctor traffic, not ChatGPT.
- **generic MCP probe:** modern `server/discover` entries also exist with `clientInfo.name="mcp"`; these are not attributed to ChatGPT.

No ChatGPT `initialize` record was found in the journal window searched from 2026-09-27 onward. That is consistent with the observed ChatGPT use of the 2026-07-28 stateless lifecycle, where `initialize` is retired. The `server/discover` envelope is the relevant ChatGPT capability evidence.

### Tunnel-client transport evidence

The active tunnel profile routes channel `main` to `http://127.0.0.1:8000/mcp`. Startup logs at `2026-09-29 08:41:59+10:00` report:

- `mcp channel route resolved ... transport="http-streamable" ... route_mode="direct"`
- a control-plane `PolledCommandQueue`
- HTTPS poll and response endpoints under `api.openai.com/v1/tunnels/.../poll` and `.../response`
- `poll_timeout_ms=30000`
- `tunnel-client started ... version="0.0.12+881c9a8..."`

This means the local MCP hop is Streamable HTTP while the private outbound tunnel receives work through the OpenAI control-plane polling channel. The tunnel's own local MCP probe is a distinct client and must not be used to infer ChatGPT host capabilities.

### Specification references

- [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Tasks extension draft for 2026-07-28](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks)

The release notes establish the modern stateless lifecycle, MRTR `input_required`, and the move of Tasks to an extension. The Tasks extension specification requires the client to advertise `extensions.io.modelcontextprotocol/tasks` per request before a server may return a task result.

### D0 conclusion

The server library is ahead of the currently observed ChatGPT capability envelope: Binnacle's installed FastMCP/MCP stack can represent modern MRTR input-required flows and has task-intent primitives, but ChatGPT has only been observed advertising the MCP UI extension, not elicitation or Tasks. In addition, Binnacle lacks the separate FastMCP Tasks engine/extension. Therefore D0 does **not** establish end-to-end support for elicitation or Tasks; it establishes the exact capability gaps that D1 should probe with a bounded POC, without changing production.

## D1 isolated live-probe design

Design date: 2026-09-29 (Australia/Sydney). D1 is design only. No tunnel, connector/link, temporary MCP server, systemd unit, or test chat was created in this step, and no production connector or service was refreshed, restarted, stopped, or changed.

### Design decision

Use the already measured `chatgpt-mcp-onboarding` chain as the lifecycle skeleton, but **do not run its all-in-one `onboard-test.sh` wrapper** because that wrapper intentionally starts a second copy of production Binnacle and verifies `run_command`. Lane D needs a smaller surface and must not use the production checkout or production services.

D2/D3, if authorized by their own steps, should reuse the onboarding skill's component scripts in the same order:

1. `chatgpt-web-operations/scripts/manage_tunnels.py` to create a fresh tunnel;
2. a dedicated loopback-only probe server on its own port;
3. `chatgpt-mcp-onboarding/scripts/tunnel-bringup.sh` for a separate tunnel-client profile and transient tunnel unit;
4. `create_connector.py` and `connect_connector.py` for a uniquely named private app/link;
5. `send_prompt.py` with `plugin:plugin_$APP` to target that app;
6. exact chat-URL tracking and exact-ID deletion;
7. `tunnel-teardown.sh --purge --delete-tunnel`, then stop the probe server and remove its `/tmp` root.

This is consistent with OpenAI's Secure MCP Tunnel documentation: a private MCP server can remain on loopback/private networking while `tunnel-client` makes the outbound HTTPS connection and forwards MCP requests locally. See [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

### Fixed experiment namespace

Use one namespace derived from this lane task so every resource is attributable:

```text
NAME=lrc-d-782414a2-probe
ROOT=/tmp/binnacle-longrun-d-782414a2
PORT=18082
SERVER_UNIT=lrc-d-782414a2-probe-server.service
TUNNEL_UNIT=lrc-d-782414a2-probe-tunnel.service
PROFILE=lrc-d-782414a2-probe
CONNECTOR=lrc-d-782414a2-probe
CHAT_TITLE=lrc-d-782414a2 D2 mrtr
```

D2 must fail closed before creation if `ROOT` already exists, either unit name already exists/runs, `PORT` is listening, the connector name is already present, or a tunnel/profile with the namespace already exists. It must not choose the production tunnel as a fallback.

The server process may read the Lane D worktree's locked Python environment through `uv run --project /home/grammy-jiang/Projects/binnacle-longrun-d-mcp-capabilities --frozen`, but its program, token, evidence log, and any runtime state live only below `ROOT`. It must not import or execute code from `/home/grammy-jiang/Projects/binnacle`.

### Minimum temporary server surface

The D2 server is a standalone FastMCP app with static-token auth and exactly two tools. It binds only `127.0.0.1:18082`.

| Tool | Purpose | Arguments | Result / state | Filesystem effect |
| --- | --- | --- | --- | --- |
| `control_echo` | Prove ordinary ChatGPT -> connector -> tunnel -> probe-server routing before interpreting MRTR behavior. | `nonce: str` | Returns `control:<nonce>`. | None. |
| `require_choice` | Exercise MCP 2026-07-28 MRTR without a normal assistant follow-up. | `nonce: str` only; the required choice is deliberately not a tool argument. | First round returns `InputRequiredResult`; retry reads `ctx.input_responses` and `ctx.request_state`, then returns a terminal string. | None. |

The `require_choice` contract is deliberately deterministic:

- On the first call, if `ctx.input_responses` has no `choice`, return one `InputRequiredResult`.
- The result contains one `ElicitRequest` named `choice`, mode `form`, message `Choose the Lane D probe value.`, and an object schema with required string property `value` whose enum is `["alpha", "beta"]`.
- Set `request_state` to a small opaque marker containing only the nonce and a schema/version tag; it contains no credential or filesystem path.
- On re-entry, accept only an `ElicitResult` with `action="accept"` and `content.value` equal to `alpha` or `beta`; return `mrtr:<nonce>:<value>:state-ok`.
- A decline/cancel/malformed response returns a distinct terminal string so it cannot be mistaken for a successful retry.
- The tool performs no write, subprocess, network, shell, repository, or service operation.

MCP 2026-07-28 defines this as a stateless retry: the server returns `resultType: "input_required"` and the client retries the original request with `inputResponses`. See [MCP 2026-07-28 MRTR](https://blog.modelcontextprotocol.io/posts/2026-07-28/).

The probe must log request method, tool name, request ID, protocol version, clientInfo, clientCapabilities, `resultType`, presence/keys of `inputResponses`, and whether `requestState` returned intact. It must never log Authorization or tunnel credentials.

### Scripted bring-up template for D2

The following is the designed command chain, **not executed in D1**. D2 should substitute the tunnel ID and app ID produced by the scripts rather than guessing them.

```bash
LANE=/home/grammy-jiang/Projects/binnacle-longrun-d-mcp-capabilities
ROOT=/tmp/binnacle-longrun-d-782414a2
NAME=lrc-d-782414a2-probe
PORT=18082
W=$HOME/.claude/skills/chatgpt-web-operations/scripts
S=$HOME/.claude/skills/chatgpt-mcp-onboarding/scripts
ORG=org-15FjIoynRqX0UP2k98SLmXNE

# Fail-closed uniqueness checks happen before mkdir/create.
mkdir -m 700 "$ROOT"
python3 -c 'import secrets; print("Bearer " + secrets.token_urlsafe(32))' > "$ROOT/token"
chmod 600 "$ROOT/token"

TID=$(python3 "$W/manage_tunnels.py" create "$NAME" \
  --organization "$ORG" --description "Lane D MRTR probe; delete after test" \
  --id-only)
sleep 30
python3 "$W/manage_tunnels.py" get "$TID"

# probe_server.py is generated only under $ROOT from the D1 contract above.
systemd-run --user --unit "$NAME-server" \
  --working-directory="$ROOT" \
  uv run --project "$LANE" --frozen python -m uvicorn \
  --app-dir "$ROOT" probe_server:app --host 127.0.0.1 --port "$PORT"

# Local auth/health probe must pass before any connector is created.
bash "$S/tunnel-bringup.sh" "$NAME" "$TID" \
  "http://127.0.0.1:$PORT/mcp" "$ROOT/token"

python3 "$W/list_connectors.py" --match "$NAME"
APP=$(python3 "$W/create_connector.py" --name "$NAME" --tunnel "$TID" |
  grep -oE 'asdk_app_[0-9a-f]{32}' | head -1)
python3 "$W/connect_connector.py" "$APP" --name "$NAME" \
  --apps-privacy full_access
python3 "$W/list_connectors.py" --match "$NAME"
```

Do not run `chatgpt-refresh` against `Raspberry Pi MCP`. A fresh private probe app/link performs its own tool discovery; if a refresh is needed after changing the temporary server, refresh only `$NAME`.

### Exact D2 test prompts

Use separate new chats so control success cannot hide MRTR failure. Each URL is persisted immediately and tracked before interpreting the result.

Control prompt:

```text
Use only the custom connector named "lrc-d-782414a2-probe".
Call its control_echo tool exactly once with nonce "lrc-d-control-782414a2".
Do not use any other connector or tool.
Reply exactly: CONTROL <tool-result>
```

MRTR prompt:

```text
Use only the custom connector named "lrc-d-782414a2-probe".
Call its require_choice tool exactly once with nonce "lrc-d-mrtr-782414a2".
The choice is deliberately not a tool argument. If the MCP protocol asks for
structured input during the call, answer that protocol request with value
"beta". Do not replace the protocol interaction with a normal chat question
and do not manually start a second independent tool call.
After the logical operation completes, reply exactly: MRTR <tool-result>
```

The expected success evidence is not merely the final text. All of these must agree:

1. the control chat returns `control:lrc-d-control-782414a2`;
2. the temporary server sees ChatGPT call `require_choice` initially without `inputResponses`;
3. that call returns wire result `input_required` with the `choice` elicitation;
4. ChatGPT reissues the same logical tool operation with `inputResponses.choice` and the echoed `requestState`;
5. the server returns `mrtr:lrc-d-mrtr-782414a2:beta:state-ok`;
6. the tunnel log shows forwarding for the temporary profile;
7. the production Binnacle services were never addressed by the probe.

If ChatGPT instead asks a normal assistant question, drops the result, reports an unsupported result, or never retries with `inputResponses`, classify D2 according to the lane plan; do not simulate the missing protocol behavior in the chat.

### Tasks/deferred-work gate for D3

D0 observed that ChatGPT did **not** advertise `extensions.io.modelcontextprotocol/tasks`. The Tasks extension requires per-request client opt-in, and a server must not return a task result to a request that omitted that extension. See [MCP Tasks extension](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks).

Therefore D1 does **not** put a task tool or Tasks extension into the D2 server. During creation/use of the temporary connector, D2 should preserve the exact ChatGPT `server/discover` and `tools/call` client-capability metadata. D3 is gated as follows:

- If the same temporary ChatGPT client still omits `io.modelcontextprotocol/tasks`, D3 records `not advertised` and performs no Tasks live probe.
- Only if ChatGPT advertises that extension may D3 add a separate task-enabled variant in the same `/tmp` experiment namespace.
- That variant must use an isolated dependency environment and the FastMCP Tasks extension; it must not install `fastmcp-tasks` or Docket into the production Binnacle environment.
- The minimum task tool, if the gate opens, is `deferred_echo(nonce)`: asynchronous, sleeps about 2 seconds, returns `task:<nonce>`, writes no files, and exposes no repository access. D3 then checks creation, `tasks/get`, terminal collection, and safe cancellation in its own step.

This gate prevents an invalid test from manufacturing a `CreateTaskResult` for a client that did not declare the extension.

### Evidence and chat ownership

D2 should keep evidence under `$ROOT/evidence/` until the result is copied into the lane report. Capture:

- probe server stdout/journal for only `$NAME-server`;
- temporary tunnel log for only profile `$NAME`;
- connector/app/link IDs;
- exact ChatGPT `server/discover` capability envelope;
- exact tool-call/result envelopes needed to distinguish first round from retry;
- exact chat URLs and backed-up conversation JSON before deletion.

Each test chat is tracked immediately by exact URL:

```bash
python3 "$W/clean_chats.py" --track <exact-url> \
  --note "Lane D lrc-d-782414a2 D2 probe"
```

Cleanup is by exact ID only; never by guessed title.

### Resource ownership and cleanup

| Resource | Owner/name | Creation path | Required cleanup |
| --- | --- | --- | --- |
| Experiment files | `/tmp/binnacle-longrun-d-782414a2` | D2 only | `rm -rf -- "$ROOT"` after evidence is copied. |
| Probe server | `lrc-d-782414a2-probe-server.service` | transient `systemd-run --user` | `systemctl --user stop "$NAME-server.service"`. |
| OpenAI tunnel | ID returned by `manage_tunnels.py create` | onboarding chain | `tunnel-teardown.sh ... --delete-tunnel`; delete only the ID created by this run. |
| Tunnel profile/unit | `lrc-d-782414a2-probe` | `tunnel-bringup.sh` | `tunnel-teardown.sh "$NAME" "$APP" --purge --delete-tunnel`. |
| ChatGPT app/link | exact `asdk_app_...` / link from create/connect scripts | onboarding chain | teardown deletes links first, then app; never target `Raspberry Pi MCP`. |
| Test chats | exact URLs/UUIDs returned by `send_prompt.py` | D2/D3 only | `clean_chats.py --id <uuid> --delete --backup ... --apply`. |

The cleanup handler must be installed before the first external resource is created. It should tolerate partial setup: if `APP` is empty, still stop/purge the temporary tunnel profile and delete the newly created tunnel; always stop the probe server and remove `ROOT` after evidence preservation.

### Production invariants

Before D2 creation and after cleanup, capture read-only invariants and require equality/health:

- `binnacle-mcp.service`, `binnacle-jobs.service`, and `binnacle-tunnel.service` active/sub states;
- production tunnel-client profile file hash;
- production connector app/link identity from a read-only connector listing;
- no command in the probe lifecycle may call `chatgpt-refresh "Raspberry Pi MCP"`, `binnacle setup`, `binnacle token rotate`, or any restart/stop/start action for a production unit.

The temporary server has no shell tool, repository tool, job manager, or generic file-write tool, so a ChatGPT probe cannot mutate production through its own MCP surface.

### D1 exit assessment

The design is reversible and uses the existing scripted tunnel/connector lifecycle rather than new infrastructure. The temporary MCP endpoint is loopback-only, its writable state is confined to a dedicated `/tmp` root, the production connector/tool list does not change, every temporary resource has an explicit owner and cleanup command, and Tasks are correctly gated on an observed client capability instead of inferred from FastMCP support.

D2 may proceed only under its own step authorization and must implement the two-tool MRTR probe exactly within these boundaries. D1 itself created none of the designed resources.

## D2 input-required / elicitation live test

Execution date: 2026-09-29 (Australia/Sydney). D2 followed the accepted D1 design and did not start any Tasks/deferred-work probe.

### Live resources created

The cleanup handler `/tmp/binnacle-longrun-d-782414a2/cleanup.sh` existed before the setup script created the first external resource. The setup script installed an `ERR/INT/TERM` cleanup trap before tunnel creation and disarmed it only after the full isolated chain was healthy.

The following resources remain intentionally live for D4/D5; D5 owns final teardown:

| Resource | Exact identity |
| --- | --- |
| Experiment root | `/tmp/binnacle-longrun-d-782414a2` |
| Probe server unit | `lrc-d-782414a2-probe-server.service` — active/running |
| Probe tunnel unit/profile | `lrc-d-782414a2-probe-tunnel.service` / `lrc-d-782414a2-probe` — active/running |
| Tunnel | `tunnel_6abb0957b57481919e3c0a030b2e1751` |
| ChatGPT app | `asdk_app_6abb0980ea988191b8e5baf8a6d5967e` |
| ChatGPT link | `link_6abb098e45dc8191b592f010d250d0b9` |
| Control chat | `https://chatgpt.com/c/6abb0a0e-5380-83ec-9936-4c6bb14404d2` — tracked exact ID |
| MRTR chat | `https://chatgpt.com/c/6abb0aa5-c380-83ec-8d87-efb46dcdccba` — tracked exact ID |

The connector discovered exactly `control_echo` and `require_choice`. The local endpoint returned HTTP 401 without its temporary bearer and 200 with it. `tunnel-bringup.sh` reported doctor `RESULT ok`, the dedicated tunnel health endpoint returned `ready`, and its log reported `tunnel-client started`.

This isolation follows OpenAI's documented Secure MCP Tunnel model: the MCP server stays private/loopback while `tunnel-client` opens the outbound HTTPS path and forwards requests locally. See [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

### ChatGPT capability envelope on the temporary connector

The temporary server captured a ChatGPT `server/discover` request before the live tool calls:

```json
{
  "protocol_version": "2026-07-28",
  "client_info": {
    "name": "openai-mcp (ChatGPT)",
    "version": "1.0.0"
  },
  "client_capabilities": {
    "experimental": {
      "openai/visibility": {
        "enabled": true
      }
    },
    "extensions": {
      "io.modelcontextprotocol/ui": {
        "mimeTypes": [
          "text/html;profile=mcp-app"
        ]
      }
    }
  }
}
```

This reproduces D0 on an independent temporary connector: the current ChatGPT client advertises neither an elicitation capability nor `extensions.io.modelcontextprotocol/tasks`.

### Control probe

Before the send, D2 ran the coordinator-required 20-second `flock` guard. The prompt was sent as a new chat using `send_prompt.py --no-wait` with `RP_BROWSER_PROFILE=` and the private app system hint, then read separately with `read_chat.py`.

Prompt nonce: `lrc-d-control-782414a2`.

ChatGPT terminal reply:

```text
CONTROL control:lrc-d-control-782414a2
```

The temporary server recorded one matching `tools/call`, one `tool_control` event with that nonce, and a successful terminal result. This proves the private connector/tunnel/server path works independently of the MRTR feature under test.

### MRTR probe

D2 again ran the 20-second send lock, used a separate new chat, `send_prompt.py --no-wait`, `RP_BROWSER_PROFILE=`, the private app hint, and then `read_chat.py`. It did not send into any lane conversation.

The temporary server received the initial `require_choice` call with:

```text
nonce=lrc-d-mrtr-782414a2
input_response_keys=[]
request_state=null
```

The tool returned the designed structured result. The captured server result contains:

```json
{
  "resultType": "input_required",
  "inputRequests": {
    "choice": {
      "method": "elicitation/create",
      "params": {
        "mode": "form",
        "message": "Choose the Lane D probe value.",
        "requestedSchema": {
          "type": "object",
          "properties": {
            "value": {
              "type": "string",
              "enum": [
                "alpha",
                "beta"
              ]
            }
          },
          "required": [
            "value"
          ],
          "additionalProperties": false
        }
      }
    }
  },
  "requestState": "lane-d-v1:lrc-d-mrtr-782414a2"
}
```

ChatGPT did **not** issue a retry carrying `inputResponses.choice` or the echoed `requestState`. No form or approval requiring human interaction appeared. Instead the ChatGPT turn terminated with:

```text
MRTR McpServerError: MCP input requires an elicitation-capable caller
```

The temporary tunnel log shows the ChatGPT requests were forwarded through `tunnel_6abb0957b57481919e3c0a030b2e1751`.

### Classification

D2 classification: **not advertised / rejected**.

The evidence separates the layers:

- MCP/FastMCP: the server successfully constructed and returned the modern structured `input_required` result.
- ChatGPT transport/tool execution: the ordinary control tool succeeded through the same temporary connector.
- ChatGPT MRTR elicitation: the client did not advertise elicitation capability and explicitly rejected the `input_required` result as requiring an elicitation-capable caller. It did not perform the protocol retry.

Therefore the current ChatGPT deployment cannot be treated as supporting this structured MRTR elicitation path. The test is not classified as a server or tunnel failure because the control succeeded and the server emitted the expected structured result.

### Production and safety observations

After the probe:

- `binnacle-mcp.service`, `binnacle-jobs.service`, and `binnacle-tunnel.service` remained active/running;
- the production tunnel profile SHA-256 remained `c8e2a608779109854e6d3aae921a2cb1fbbe1b6511f1630990899052a6b74ecb`;
- the production connector remained app `asdk_app_6a8af16275ac8191a891cf48118748f5`, link `link_6a8af17294788191b9e35978879baaf3`, with its six-tool surface;
- D2 never refreshed, restarted, stopped, or reconfigured the production connector or protected production services.

A diagnostic grep of the production journal for the D2 nonce is intentionally **not** used as isolation evidence: Lane D itself performs local work through the production Raspberry Pi MCP connector, so a diagnostic command containing the nonce is logged there. The probe-chat routing evidence instead comes from the private app system hint, the dedicated temporary server's matching tool events, and the dedicated temporary tunnel's forwarded-command log.

### Raw evidence retained for later lane steps

Until D5 cleanup, D2 raw evidence remains under:

```text
/tmp/binnacle-longrun-d-782414a2/evidence/
    local-http-status.txt
    tunnel-get.json
    tunnel-bringup.txt
    create-connector.txt
    connect-connector.txt
    connectors-before.txt
    connectors-after.txt
    control-send.json
    control-url.txt
    control-reply.txt
    mrtr-send.json
    mrtr-url.txt
    mrtr-reply.txt
    probe-events.jsonl
    tunnel-forwards.txt
    production-connector-after.txt
    production-isolation.txt
```

Both test chats remain tracked by exact UUID for D4/D5. They were not deleted in D2 because D4 may reuse the successful control primitive; D5 remains responsible for backup/delete and complete resource teardown.

### D2 exit assessment

D2 achieved a conclusive end-to-end result: ordinary connector execution works, while structured `input_required` carrying elicitation is rejected by the current ChatGPT caller because that caller is not elicitation-capable. No human UI interaction was required or automated. D3 was not started.

## D3 MCP Tasks / deferred-work gate

Assessment date: 2026-09-29 (Australia/Sydney). D3 applied the D1 capability gate literally and did not create or execute a Tasks/deferred-work variant.

### Gate evidence

The independent temporary connector's D2 `server/discover` request identifies the caller as `openai-mcp (ChatGPT)` version `1.0.0`, protocol `2026-07-28`. Its complete observed client capability envelope is:

```json
{
  "experimental": {
    "openai/visibility": {
      "enabled": true
    }
  },
  "extensions": {
    "io.modelcontextprotocol/ui": {
      "mimeTypes": [
        "text/html;profile=mcp-app"
      ]
    }
  }
}
```

There is no `extensions.io.modelcontextprotocol/tasks` entry. This matches the earlier D0 production observation and is direct evidence from the isolated D2 connector.

The D2 MRTR evidence is consistent with a capability-gated client: the server returned its structured `input_required` result, but ChatGPT did not retry and instead terminated with `McpServerError: MCP input requires an elicitation-capable caller`. That result is not itself a Tasks test; it is retained only as corroborating evidence that unsupported protocol capabilities are rejected rather than implicitly negotiated.

### Verdict

D3 classification: **not advertised**.

The MCP 2026-07-28 Tasks extension is capability-negotiated. The D1 design therefore required ChatGPT to advertise `io.modelcontextprotocol/tasks` before Lane D could add a task-enabled variant. That prerequisite is absent.

Accordingly D3 performed none of the following:

- no `deferred_echo` or other task tool was added;
- no `fastmcp-tasks` or Docket package was installed;
- no Tasks extension was registered;
- no task-specific server, tunnel, connector, or chat was created;
- no existing connector was refreshed or modified;
- no proprietary task/deferred-work compatibility layer was attempted.

This is the conclusive D3 result requested by the lane plan: current ChatGPT evidence does not make a Tasks live test meaningful, so the lane stops at capability negotiation rather than manufacturing an invalid task response.

### Resource continuity for D4

D3 made no runtime changes. The D2 resources remain intentionally live and unchanged for D4:

```text
root:   /tmp/binnacle-longrun-d-782414a2
server: lrc-d-782414a2-probe-server.service
tunnel: lrc-d-782414a2-probe-tunnel.service
TID:    tunnel_6abb0957b57481919e3c0a030b2e1751
APP:    asdk_app_6abb0980ea988191b8e5baf8a6d5967e
LINK:   link_6abb098e45dc8191b592f010d250d0b9
```

The two D2 test chats remain tracked by exact UUID as recorded above. D3 created no additional chat.

### D3 exit assessment

MCP Tasks/deferred work is **not advertised by the current ChatGPT caller** and therefore was not live-tested. No workaround was built. The existing isolated D2 control primitive remains available for D4 reconnect/new-turn observations.

## D4 reconnect / new-turn observations

Execution date: 2026-09-29 (Australia/Sydney). D4 used only the existing D2 probe resources and the stateless `control_echo` primitive. It did not create another connector, tunnel, server, or tool.

To expose the request-scoped identifiers that FastMCP already makes available, D4 added observation-only logging to the temporary `/tmp` `control_echo` implementation and restarted only `lrc-d-782414a2-probe-server.service`. The tool schema and return value did not change, so the connector was not refreshed. Production services were not restarted.

### What the probe server can observe

On each control call, FastMCP/request metadata exposed:

- FastMCP `session_id`;
- MCP `request_id`;
- transport type (`streamable-http`);
- MCP protocol version;
- per-request `io.modelcontextprotocol/clientInfo`;
- per-request `io.modelcontextprotocol/clientCapabilities`;
- OpenAI-side `sessionId`, `windowId`, and opaque `openai/session`;
- per-call `callId`, `itemId`, and `openai/request_id`;
- per-request extension settings, including UI present and Tasks absent.

The opaque `openai/session` values are not copied into this report. Equality is represented by a short SHA-256 prefix only.

One client-identity nuance is visible in the evidence: connector discovery in D2 identified `openai-mcp (ChatGPT)`, while these actual `tools/call` request metadata records identify `openai-mcp (Codex)`, both version `1.0.0`. Lane D treats those as two observed host-side labels rather than assuming they are interchangeable identities.

### Same ChatGPT conversation, later turn

D4 continued only the existing D2 control chat:

```text
https://chatgpt.com/c/6abb0a0e-5380-83ec-9936-4c6bb14404d2
```

It used the required send lock, `send_prompt.py --no-wait`, and read the settled result separately. The later turn returned:

```text
SAME control:lrc-d-same-chat-782414a2
```

Observed identifiers for that call:

```text
FastMCP session_id: 5c2aecfe-5772-4af9-b8ae-190561938dea
transport: streamable-http
protocol: 2026-07-28
OpenAI sessionId: 01a0ea9f-5298-7475-825f-0317273b4084
OpenAI windowId: 01a0ea9f-5298-7475-825f-0317273b4084:0
openai/session SHA-256 prefix: 0ad268f0f84b
Tasks extension: absent
```

Thus a new turn in the same ChatGPT conversation can call the same private connector and tool successfully.

### New ChatGPT conversation

D4 then created one new test conversation using the required 20-second send lock, `RP_BROWSER_PROFILE=`, `send_prompt.py --no-wait`, and the same private app hint. It was tracked immediately by exact URL:

```text
https://chatgpt.com/c/6abb0de2-be24-83ec-9f22-6e9dae494079
```

The terminal result was:

```text
NEW control:lrc-d-new-chat-782414a2
```

Observed identifiers changed:

```text
FastMCP session_id: c7602036-0a79-4b6d-ac5e-fbdae909a21c
OpenAI sessionId: 01a0eaae-4860-72ab-bbdb-202f76d8f0aa
OpenAI windowId: 01a0eaae-4860-72ab-bbdb-202f76d8f0aa:0
openai/session SHA-256 prefix: 7e2216770a4d
```

Protocol, transport, client capability shape, and absence of the Tasks extension were unchanged. Per-call IDs were also newly minted. Therefore the host metadata does not provide a stable conversation-independent operation identity.

### Temporary tunnel reconnect

D4 restarted **only** `lrc-d-782414a2-probe-tunnel.service`. The production `binnacle-tunnel.service` invocation remained unchanged.

The temporary tunnel restart changed:

```text
probe tunnel systemd invocation:
  c3cbd6042a094330a3b11298bf69e531
  -> 83de9c3dcfdd4d819e7345f39e1097ca

tunnel-client client_instance_id:
  72ed58795b8538434d4b699a87cb63fb
  -> e540c9faa3eecad1bd4b062a8448cbd1
```

The restarted tunnel returned `ready` and initialized its local MCP session successfully. This matches OpenAI's documented tunnel model: `tunnel-client` is the outbound transport path and requests resume after that client reconnects. See [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

D4 then continued the same D2 control conversation. The first post-reconnect call returned:

```text
RECONNECT control:lrc-d-after-reconnect-782414a2
```

The OpenAI conversation-side values remained the same as the earlier same-chat turn:

```text
OpenAI sessionId: 01a0ea9f-5298-7475-825f-0317273b4084
OpenAI windowId: 01a0ea9f-5298-7475-825f-0317273b4084:0
openai/session SHA-256 prefix: 0ad268f0f84b
```

but FastMCP `session_id` changed to:

```text
96733a90-0b19-4b22-8aa6-7692b191daf6
```

and the tunnel forwarded the call under the new `client_instance_id`.

### Session identity is not durable even without another reconnect

A second later turn in the same ChatGPT conversation, with no further server or tunnel restart, returned:

```text
TURN2 control:lrc-d-post-reconnect-turn2-782414a2
```

The OpenAI conversation-side `sessionId`, `windowId`, and opaque-session hash remained unchanged, but FastMCP `session_id` changed again to:

```text
facdba80-97e5-4ec0-9049-c797d05d960a
```

This is decisive for Binnacle architecture: with the current ChatGPT 2026-07-28 stateless request path, FastMCP `session_id` is not a durable cross-turn key. It changed between successive tool calls even while the same ChatGPT conversation and the same reconnected tunnel stayed in place.

### State-placement conclusion

The observations divide identifiers into three classes:

| Identifier class | Observed behavior | Safe role |
| --- | --- | --- |
| FastMCP `session_id`, MCP request ID, call/item/request IDs | Per-call/transient; FastMCP session changed across turns and reconnect | Diagnostics/correlation only; never durable job ownership or resume identity |
| OpenAI `sessionId`, `windowId`, opaque `openai/session` | Stable across the tested turns of one ChatGPT conversation, including tunnel reconnect; different in a new conversation | Useful correlation evidence inside one conversation, but host-owned metadata and not a durable Binnacle contract |
| Explicit Binnacle identity, such as a job ID/cursor/resume token persisted by Binnacle | Not transport-dependent | Required location for long-running operation state, output cursor, cancellation identity, and reconnect/new-conversation resume |

The control tool itself is stateless, so every successful D4 call proves reachability rather than server-side continuation. Any long-running workflow that must survive a new turn, a tunnel reconnect, or a new ChatGPT conversation must persist its authoritative state in Binnacle and return an explicit Binnacle-owned identifier to the client. MCP/ChatGPT session metadata may be logged for correlation but must not be the sole lookup key.

### D4 evidence and live resources

Additional D4 evidence retained under the existing experiment root:

```text
/tmp/binnacle-longrun-d-782414a2/evidence/
    d4-same-send.json
    d4-same-reply.txt
    d4-new-send.json
    d4-new-url.txt
    d4-new-reply.txt
    d4-tunnel-restart.txt
    d4-reconnect-send.json
    d4-reconnect-reply.txt
    d4-turn2-send.json
    d4-turn2-reply.txt
```

The D4 new conversation is tracked by exact UUID. The two D2 chats remain tracked. No chat was deleted in D4.

All D2 resources remain live for D5 with the same tunnel/app/link IDs. The temporary probe server and tunnel units are active/running. The production `binnacle-mcp`, `binnacle-jobs`, and `binnacle-tunnel` services remain active/running, the production tunnel invocation was not restarted, and the production tunnel profile hash remains unchanged.

### D4 exit assessment

The safe control primitive survives a later turn in the same ChatGPT conversation, a fresh ChatGPT conversation, and a temporary tunnel-client reconnect. What does **not** survive as a stable identity is the FastMCP/MCP session itself. Durable long-running state therefore belongs in Binnacle behind explicit Binnacle-owned IDs, not in the MCP session or tunnel connection. D5 cleanup was not started.

## D5 cleanup and final capability matrix

Completion date: 2026-09-29 (Australia/Sydney).

### Evidence preservation

Before deleting any chat or runtime resource, D5 copied the evidence cited by this report into:

```text
docs/long-running-chatgpt/lane-d-evidence/
```

and committed that preservation as `af54de1`.

The preserved evidence is sanitized: raw `openai/session` values are replaced by 12-character SHA-256 prefixes; Authorization/Bearer and credential-like fields are redacted; the temporary bearer token, tunnel-client profile, and environment files were not copied. `lane-d-evidence/manifest.json` records source and preserved SHA-256 hashes and `lane-d-evidence/README.md` documents the sanitization.

The most relevant evidence files are:

- `lane-d-evidence/probe-events.jsonl`: ChatGPT discovery capabilities, D2 control/MRTR events, and sanitized D4 request/session observations;
- `lane-d-evidence/control-reply.txt`: successful ordinary-tool control;
- `lane-d-evidence/mrtr-reply.txt`: ChatGPT's elicitation-capability rejection;
- `lane-d-evidence/d4-same-reply.txt`, `d4-new-reply.txt`, `d4-reconnect-reply.txt`, and `d4-turn2-reply.txt`: reconnect/new-turn control results;
- `lane-d-evidence/d4-tunnel-restart.txt`: temporary tunnel restart identity/readiness evidence;
- `lane-d-evidence/tunnel-forwards.txt`: isolated tunnel forwarding evidence;
- `lane-d-evidence/production-connector-after.txt`: production connector identity/six-tool surface during the probe.

Earlier sections refer to the then-live `/tmp/binnacle-longrun-d-782414a2/evidence` path because they are step checkpoints. That temporary root no longer exists; the committed sanitized directory above is the durable Lane D evidence record.

### Test-chat cleanup

D5 deleted **only** these three probe chats by exact UUID, with conversation backup enabled and `--max 3`:

```text
6abb0a0e-5380-83ec-9936-4c6bb14404d2
6abb0aa5-c380-83ec-8d87-efb46dcdccba
6abb0de2-be24-83ec-9f22-6e9dae494079
```

The cleanup helper backed them up under `~/.local/share/chatgpt-chats/backups/` and deleted all three. Exact `--untrack` checks then reported each ID was already untracked because successful exact-ID deletion removes it from the ledger. D5 never used `--tracked` or `--match`; the lane worker conversations were not selected.

### Probe-resource teardown

D5 used the onboarding teardown against exactly:

```text
TID:  tunnel_6abb0957b57481919e3c0a030b2e1751
APP:  asdk_app_6abb0980ea988191b8e5baf8a6d5967e
LINK: link_6abb098e45dc8191b592f010d250d0b9
```

The teardown deleted the exact link and app, stopped/purged `lrc-d-782414a2-probe-tunnel.service` and its profile/env/health/log files, and deleted the exact tunnel. D5 then stopped the exact probe server, removed `/tmp/binnacle-longrun-d-782414a2`, and cleared the stopped transient server unit record.

Final absence checks:

- probe connector name: 0 links, 0 custom MCP apps;
- tunnel `tunnel_6abb0957b57481919e3c0a030b2e1751`: HTTP 404 from tunnel lookup;
- probe server unit: `LoadState=not-found`, inactive/dead;
- probe tunnel unit: `LoadState=not-found`, inactive/dead;
- probe profile/env/health URL: absent;
- experiment root: absent;
- TCP port 18082: not listening.

### Production verification

The protected production services remain active/running with the coordinator-confirmed baseline PIDs/start times:

| Unit | PID | Active since |
| --- | ---: | --- |
| `binnacle-mcp.service` | 1374081 | 2026-09-28 01:49:17 AEST |
| `binnacle-jobs.service` | 1183 | 2026-09-23 10:15:18 AEST |
| `binnacle-tunnel.service` | 266638 | 2026-09-29 08:41:59 AEST |

The production tunnel profile SHA-256 is still:

```text
c8e2a608779109854e6d3aae921a2cb1fbbe1b6511f1630990899052a6b74ecb
```

The production ChatGPT connector remains:

```text
app:  asdk_app_6a8af16275ac8191a891cf48118748f5
link: link_6a8af17294788191b9e35978879baaf3
name: Raspberry Pi MCP
tools: 6
app status: ENABLED / PRIVATE
link auth: NONE
```

No production connector, service, profile, or tool surface was changed by Lane D.

### Final capability matrix

| Capability | MCP / FastMCP layer | Current ChatGPT evidence | Lane D verdict | Round 2 dependency rule |
| --- | --- | --- | --- | --- |
| Ordinary MCP tool call | Core capability; FastMCP serves it normally | D2 control succeeded through isolated connector/tunnel; D4 controls also succeeded | **Supported** | May rely on ordinary request/response tool calls |
| MCP 2026-07-28 stateless lifecycle | mcp/mcp-types 2.1.1 and FastMCP 4.0.0b5 understand it | `server/discover` observed from `openai-mcp (ChatGPT)` with protocol `2026-07-28` | **Supported/observed** | May use the current stateless request model |
| Legacy direct `Context.elicit()` | Available only on handshake-era foreground sessions; FastMCP rejects it on modern protocol | Current ChatGPT uses 2026-07-28 | **Not applicable to current ChatGPT path** | Do not design around direct server-to-client `Context.elicit()` |
| Modern `input_required` / structured elicitation | FastMCP successfully emitted the designed `InputRequiredResult` | Elicitation was not advertised; ChatGPT returned `McpServerError: MCP input requires an elicitation-capable caller`; no retry/input response occurred | **Not advertised / rejected** | Must remain optional; Round 2 cannot require it |
| MCP Tasks/deferred-work extension | FastMCP has task intent primitives but the installed Binnacle environment lacks the separate Tasks engine; extension is negotiated per request | `io.modelcontextprotocol/tasks` absent in D0 and isolated D2 capabilities | **Not advertised** | Do not depend on MCP Tasks; no compatibility hack justified |
| Later turn in same ChatGPT conversation | Ordinary stateless call | D4 same-chat control succeeded | **Supported for fresh calls** | Reinvoke by explicit Binnacle ID; do not assume MCP session continuity |
| New ChatGPT conversation | Ordinary stateless call | D4 new-chat control succeeded with different host/session metadata | **Supported for fresh calls** | Resume requires an explicit Binnacle-owned ID passed into the new conversation |
| Temporary tunnel reconnect | Tunnel-client reconnects to same private tunnel; local MCP remains separate | Same ChatGPT conversation called control successfully after restarting only probe tunnel | **Supported for fresh calls after reconnect** | Binnacle state must survive independently of tunnel process/session |
| FastMCP `session_id` as durable identity | Exposed by FastMCP request context | Changed across tunnel reconnect and again across later turns without another reconnect | **Not durable** | Diagnostics only; never job/resume/cursor ownership |
| OpenAI `sessionId` / `windowId` / opaque session | Host-provided request metadata, not a Binnacle contract | Stable across tested turns of one conversation/reconnect; changed in new conversation | **Conversation-scoped correlation only** | May log sanitized correlation; never sole durable lookup key |

A client-label nuance remains: the isolated `server/discover` request identified `openai-mcp (ChatGPT)`, while D4 `tools/call` metadata identified `openai-mcp (Codex)`. Both reported version `1.0.0` and the same tested protocol/capability shape. Lane D records the labels as observed and does not infer a stronger identity relationship.

### Round 2 contract guidance

Round 2 may rely on ordinary MCP tool calls and on Binnacle's own durable job/output mechanisms. It should design long-running orchestration around explicit Binnacle-owned identities: job ID, cursor/resume token, cancellation identity, and persisted operation state. Those identifiers must survive independently of MCP request/session objects, ChatGPT conversation metadata, and tunnel-client processes.

Round 2 must **not** require structured MCP elicitation or the MCP Tasks extension in the current deployment. Those capabilities may be revisited only after future client capability evidence explicitly advertises them and a bounded live probe succeeds.

The architectural implication is consistent across D2-D4: the MCP/ChatGPT layer is currently a reliable stateless command surface, not the authoritative store for long-running workflow state.

### Lane D completion

Lane D completed without production-code changes. The isolated connector/tunnel/server and all three probe chats are cleaned up, the evidence needed for synthesis is committed in sanitized form, and production Binnacle remains at its pre-lane service/connector state.
