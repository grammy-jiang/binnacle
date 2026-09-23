# Chat mode asynchronous MCP orchestration experiment

**Status:** complete; isolated branch only
**Scope:** ChatGPT **Chat mode** using the real Raspberry Pi MCP connector
**Non-goals:** Work mode, API-only behavior, generic workflow engines, production feature design

Final synthesis: `docs/chat-mode-scheduling-final-2026-09-23.md`.

## 1. Question

Can one user prompt in ordinary ChatGPT Chat mode sustain a multi-round agent
trajectory while one MCP tool call is still unresolved?

The target behavior is stronger than background shell execution and stronger
than ordinary parallel function calling:

```text
long A starts ------------------------------ A ends
     seed B starts/ends
              model receives B
              echo C(B.result) starts/ends
```

The decisive condition is: **C must start before A ends**, and C must contain a
server-generated value returned by B. Because C cannot be constructed before B
returns, this proves the model/host resumed reasoning while A was still
outstanding.

## 2. Distinct capabilities under test

### T0 — MCP Tasks capability negotiation

Inspect the live ChatGPT MCP request for
`io.modelcontextprotocol/tasks` using FastMCP's request context.

Pass:

- per-request extension settings are present, or the client advertises the
  extension through its negotiated capabilities.

Fail:

- neither form is declared.

This answers whether the standards-native MCP task path is currently available
to this ChatGPT client. It does **not** by itself prove async model continuation.

### T1 — ordinary parallel MCP dispatch

Prompt ChatGPT to invoke three independent wait probes in the same step.

Pass:

- at least two probe `start` events occur before either corresponding `end`
  event.

Fail:

- every call begins only after the previous call ends.

This distinguishes concurrent tool dispatch from purely sequential tool calls.

### T2 — true asynchronous orchestration (decisive)

Use three tools and one probe id:

1. `async_probe_wait(..., delay_s=15)` — deliberately long.
2. `async_probe_seed(...)` — immediate, returns a random server-generated
   token that the model cannot predict.
3. `async_probe_echo(..., token=<seed result>)` — immediate.

Prompt requirement: start the long wait; while it is unresolved obtain the seed;
as soon as the seed result is available, pass that exact value to echo; use the
long-wait result before the final answer.

Outcomes:

| Timeline | Interpretation |
| --- | --- |
| wait start → wait end → seed → echo | fully sequential |
| wait + seed overlap, wait end → echo | parallel calls supported, but model does not resume until all calls in the batch finish |
| wait + seed overlap, seed end → **echo start before wait end** | **true async orchestration supported** |

The random token makes the third outcome causally strong: echo cannot be
pre-batched with a guessed argument.

## 3. Probe tools

Temporary read-only tools, exposed only on this experiment branch:

- `async_probe_capabilities`
- `async_probe_wait`
- `async_probe_seed`
- `async_probe_echo`

Every probe writes a structured journal event:

```text
event=async_probe phase=start|end tool=... probe_id=... label=... call=...
```

The normal `tool_call` / `tool_result` records retain the ChatGPT turn id and
OpenAI session correlation. This provides two independent timelines.

## 4. Real Chat mode execution

Use the existing `chatgpt-send` browser harness, not a local MCP client.
It drives a normal chatgpt.com Chat session and therefore tests the actual
ChatGPT host/orchestrator.

For each trial:

1. create a new throwaway Chat chat;
2. immediately track its id with `chatgpt-chats --track`;
3. send a nonce-bearing prompt that forbids shell/run_command substitution;
4. collect MCP + job journal from immediately before the prompt;
5. classify the timeline mechanically;
6. repeat the decisive T2 trial at least three times if the first result could
   be model-strategy-dependent;
7. delete tracked test chats after evidence is saved.

## 5. Controls

### Local server-concurrency control

Before testing ChatGPT, invoke wait probes concurrently with a local MCP client
(or equivalent local async client). They must overlap. Otherwise a sequential
ChatGPT result could be a Binnacle/FastMCP server limitation.

### ChatGPT prompt control

The prompt explicitly says:

- use only the four async probe tools;
- do not use run_command or shell;
- do not replace the requested sequence with a background job;
- the final answer must wait for all required results.

### Duration

15 seconds for the decisive long probe:

- long enough for unambiguous ordering;
- short enough to stay well below the existing one-minute synchronous MCP
  tool-call ceiling.

## 6. Classification rules

No conclusion is based on UI text or model prose. Journal timestamps are the
source of truth.

**True async = PASS** only when all hold:

1. long wait start recorded;
2. seed starts after or contemporaneously with long wait and finishes before it;
3. echo argument exactly equals the returned random seed;
4. echo starts **before** long wait end;
5. all calls share the same ChatGPT turn id (same prefix before `/`).

If calls overlap but criterion 4 fails, report **parallel dispatch only**.

If all calls serialize, report **sequential**.

If the host rejects/does not expose the probes, report **inconclusive client
surface failure**, not sequential.

## 7. Safety and cleanup

- tools are read-only and have no filesystem/process side effects;
- probe ids and seed values are non-sensitive random strings;
- experiment lives in a separate worktree/branch;
- after the experiment, restore the production service to master, refresh the
  connector so probe tools disappear, verify the six normal ChatGPT tools, and
  delete tracked test chats;
- do not merge probe tools into master.

## 8. Evidence to retain

The experiment report should include:

- exact production/client protocol version seen;
- T0 capability result;
- per-trial start/end ordering with millisecond timestamps;
- turn ids for all calls;
- wall-clock elapsed time;
- whether parallel dispatch exists;
- whether true async continuation exists;
- implications for Binnacle's polling/background-handoff design.
