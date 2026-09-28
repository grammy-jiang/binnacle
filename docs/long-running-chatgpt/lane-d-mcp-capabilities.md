# Lane D — current ChatGPT MCP capability probe

Status: **Round 1 plan; do not execute before coordinator start approval.**

Worktree: `~/Projects/binnacle-longrun-d-mcp-capabilities`
Branch: `experiment/longrun-d-mcp-capabilities`
Primary worker: one persistent ChatGPT conversation using the Raspberry Pi MCP connector.
Production-code merge intent: none by default.

## Mission

Establish what the **current ChatGPT MCP host actually supports**, not merely what the MCP specification or FastMCP library supports.

The lane must keep three layers separate:

```text
MCP specification capability
FastMCP/server-library capability
OpenAI/ChatGPT client capability observed in this deployment
```

The output is an evidence-backed capability matrix and minimal live proofs where safe.

## Safety boundary

Do not mutate the production Binnacle tool surface merely to make the probe easy.

Preferred order:

1. inspect existing protocol/init evidence;
2. use local library/unit-level probes;
3. design an isolated temporary MCP endpoint/connector if a live ChatGPT test is necessary;
4. create the temporary connector only when the design is reversible and cleanup is explicit;
5. delete/disable experimental connector/configuration after evidence capture.

Never weaken authentication or expose the Pi directly to the Internet.

## Inputs

Read:

- `docs/long-running-chatgpt/README.md`
- current Binnacle/FastMCP versions and server construction;
- production `initialize` request logs where available;
- current MCP specification/release notes for elicitation / `input_required` / Tasks / multi-round behaviour;
- current OpenAI MCP/plugin documentation;
- `CLAUDE.md` ChatGPT connector refresh/test/cleanup procedure;
- existing chat-scheduling isolated endpoint/connector harness before inventing new infrastructure.

## Output

`docs/long-running-chatgpt/lane-d-report.md`

All live test chats/connectors must be named/tracked explicitly and cleaned up at lane end.

## Step D0 — Static capability inventory

Target: 8–12 minutes.

Tasks:

1. Record installed FastMCP and MCP SDK versions and protocol versions they understand.
2. Inspect `Context.elicit` and any task/input-required primitives in the installed library.
3. Extract actual ChatGPT/OpenAI-client `initialize` capability evidence from server logs if present; distinguish it from `binnacle-doctor` or other local clients.
4. Record current tunnel-client version and transport.
5. Build the initial matrix:

```text
feature | MCP spec | FastMCP | ChatGPT observed | evidence | live probe needed?
```

Exit criteria:

- no claim of ChatGPT support based only on server-library support;
- ambiguous client identities are marked ambiguous.

## Step D1 — Design isolated live probe

Target: 8–12 minutes.

Tasks:

1. Reuse existing Binnacle test/staging connector/harness patterns where practical.
2. Define the minimum temporary server surface needed to test:
   - one normal control tool;
   - one structured `input_required`/elicitation path;
   - one task/deferred path if the client advertises or plausibly supports it.
3. Define exact test-chat prompts and expected evidence.
4. Define cleanup before creating anything.
5. Ensure the temporary endpoint cannot write outside a safe `/tmp` or dedicated experiment directory unless the test explicitly requires repository reads.

Exit criteria:

- reversible probe design exists;
- production connector/tool list does not need to be changed;
- every temporary resource has an owner and cleanup command.

## Step D2 — `input_required` / elicitation live test

Target: 10–15 minutes.

Only if D1 passes safety review.

Test the current ChatGPT host end to end:

1. ChatGPT invokes the temporary tool.
2. Tool requires one simple structured input not present in the first call.
3. Observe whether ChatGPT/UI/client returns the required input through the protocol-supported multi-round mechanism.
4. Verify the same logical tool operation resumes and completes.
5. Capture protocol/server logs and the exact chat result.

Classify outcome:

- supported and successful;
- advertised but broken;
- not advertised / rejected;
- test inconclusive.

Do not substitute a normal assistant question to the user for protocol elicitation.

## Step D3 — MCP Tasks/deferred-work live test

Target: 10–15 minutes.

Only if current protocol/client evidence makes this test meaningful.

Test the smallest deferred task:

- starts and returns a task/deferred identity;
- remains queryable independently of the initial response connection;
- reaches terminal state;
- result can be collected later;
- cancellation if supported and safe.

If ChatGPT does not support the relevant MCP extension, record that cleanly and stop; do not create a proprietary compatibility hack in this lane.

## Step D4 — Reconnect / new-turn observations

Target: 10–15 minutes.

Using the safest successful primitive from D2/D3, determine what survives:

- new MCP transport/session;
- a new ChatGPT turn in the same conversation;
- a new ChatGPT conversation, if identity is intentionally passed;
- temporary tunnel reconnect if it can be tested without risking production.

The goal is to identify what state must live in Binnacle rather than in the MCP session.

Do not intentionally disrupt the production tunnel.

## Step D5 — Cleanup and report

Target: 8–12 minutes.

1. Remove all temporary connectors/endpoints/services/files that are not part of the evidence record.
2. Delete tracked test chats according to `CLAUDE.md` owner policy after preserving required evidence.
3. Verify production connector and services are unchanged/healthy.
4. Finish `lane-d-report.md` with the capability matrix and raw evidence references.
5. State clearly which MCP features Round 2 may rely on and which must remain optional.

## Lane D completion reply

```text
STEP: D5
STATUS: PASS | BLOCKED | FAIL
ARTIFACTS: docs/long-running-chatgpt/lane-d-report.md
COMMIT: <sha or none>
FINDINGS: <capability summary>
NEXT: R1 synthesis gate
```

The POC branch is evidence, not production implementation. Do not merge experimental server/connector code unless Round 2 explicitly chooses it and reimplements it under the frozen contract.
