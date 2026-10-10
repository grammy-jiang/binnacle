# R2: genuine ChatGPT Chat connection and behavior verification

Status: PROPOSED; no independent ChatGPT Chat test app has yet been verified or connected.

## Official supported routes are not account entitlement

OpenAI documents custom MCP Server connections through ChatGPT Plugins and Secure MCP Tunnel. These are possible supported paths, not proof the current ChatGPT account/workspace can install and invoke the new test app.

- [OpenAI custom MCP connection](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [OpenAI plugin quickstart](https://developers.openai.com/plugins/build/app-quickstart)

The Pi chatgpt binary resolved to a Codex launcher in R1; this does not prove genuine ChatGPT Chat. Chat mode, Codex Desktop and ChatGPT Work must be recorded separately.

## A-stage connection capability matrix

| Route | A may verify without ChatGPT account action | Additional gate | Required evidence |
| --- | --- | --- | --- |
| Native isolated FastMCP on loopback | Schema, auth deny, tool list, nonce echo, own port and cleanup | None if local synthetic only | A/local-canary.json |
| Private HTTPS | Transport/TLS/auth once a specific separate endpoint is authorized | Endpoint permission and test-only scope | A/transport-evidence.json |
| Secure MCP Tunnel | Docs and permission requirements, non-secret connectivity diagnostics | Existing authorized tunnel or explicit user-approved new connection | A/connection-options.json |
| ChatGPT Plugin custom MCP server | Read-only tool permissions, onboarding checklist, app manifest | Explicit user/plugin install and connection action where required | A/account-action-required.json |
| Pi Codex Desktop | Product information only | Genuine ChatGPT Chat proof; no automatic equivalence | A/connection-options.json |

A can complete its local feasibility tasks while genuine E1 remains blocked. A local HTTP 200 is not evidence of ChatGPT Chat receiving any tool output.

## Synthetic tool contract

Expose only disposable non-production tools, all scoped to the synthetic run:

- fixture_echo: deterministic nonce in CONTROL, META, TEXT or schema-compliant STRUCT.
- fixture_status: read-only synthetic Job ID and lifecycle state.
- fixture_read: bounded synthetic result pages and cursor; no real files.
- fixture_unrelated_read: harmless fixed text with optional compact reminder.
- Independent local test-controller state transitions; ChatGPT itself gets no arbitrary process execution, filesystem writes or external network fetch tools.

Never reuse production Binnacle commands, live job IDs, private chats or credentials. Record all tool schema, auth-denied cases, results and test state transitions.

## Real ChatGPT E0/E1 preflight

1. Verify product surface: traditional ChatGPT Chat, not Codex Desktop or Work, and record actual UI/runtime version.
2. Verify experimental App is distinctly named, has separate endpoint identity and exposes only synthetic tools. Do not replace the production Binnacle connector.
3. Verify account/workspace permission. Any installation, new account connection, permission warning or user confirmation must be handled through explicitly authorized user action, not programmatic bypass.
4. Pin real ChatGPT subject to GPT-6, Medium effort for the paired pilot. Do not silently use Instant/default if the setting is unavailable.
5. Send a harmless unique nonce through the actual experimental MCP connection and observe corresponding server tool call and model behavior. Server-sent result metadata alone is not proof of model visibility.
6. Test CTRL/META/TEXT/STRUCT separately, with raw wire and client result evidence. E1 does not need per-chat auto-reminder behavior yet.
7. E2 multi-chat auto-reminder tests only after B proves trusted chat ownership and C a defensible receipt. Otherwise E2 BLOCKED, while harmless E1 observations remain useful.

## Paired real ChatGPT behavioral study

After one successful canary, pre-register exactly 12 matched, randomized control/candidate pairs per viable carrier. Model/effort, fixture, prompt, visible app tools and goal are identical except reminder presence.

Record: pair ID, randomized arm order, nonce SHA, chat A/B/C, product surface, subject model/effort proof, sent/received/model-used event IDs, correct job-specific result fetch, complete pages, meaningful subsequent tool call in the *same active turn*, premature handoff, elapsed time, tool count, byte/token counts and measurement source.

The positive causal chain requires genuine ChatGPT Chat to (i) start the synthetic Job, (ii) keep working on independent tasks, (iii) receive the completion hint through a later unrelated tool response, (iv) voluntarily retrieve the correct complete Job result, and (v) make another meaningful user-goal tool call without a new user message. Do not count a model verbal assertion as proof.

A passive MCP tool-result hint cannot wake an already terminated ChatGPT turn. This separate external scheduling problem remains out of scope.

## Isolation and privacy

Only one approved GUI operator may create/manage fresh synthetic test conversations; three chats can be interleaved, but GUI input is exclusive. No worker may read old user chats, scrape cookies, accept app-risk warnings on the user's behalf, install or reconfigure Plugins without required permission, or expose a private MCP test server publicly without explicit scope. All retained logs use run-scoped aliases and sanitized tokens, no secrets or real user content.

If any prerequisite is missing, E1 or E2 ends BLOCKED with a specific missing permission/route and a reproducible canary; the other independent R2 lanes continue.
