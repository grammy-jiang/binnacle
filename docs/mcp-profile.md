# ChatGPT MCP Compatibility Profile

- **Status:** Draft — empirical bootstrap profile
- **Contract:** `MCP-PROFILE`
- **Applies to:** Binnacle V1
- **Target host:** ChatGPT on the web
- **Initial owner plan:** ChatGPT Pro
- **Last source review:** 2026-08-08
- **Validation state:** No live Binnacle-to-ChatGPT observation has been recorded yet

## 1. Purpose

This document defines how Binnacle determines the MCP behaviour that it may rely on when connected to ChatGPT.

OpenAI does not currently publish one authoritative dated MCP protocol revision for the production ChatGPT client. Binnacle therefore does not infer support from documentation alone. It starts with a minimal, broadly compatible MCP surface, records the actual protocol and client behaviour presented by ChatGPT, and promotes only features that pass an end-to-end probe.

The governing rule is:

> The MCP specification defines what is possible. The actual ChatGPT connection defines what Binnacle V1 may depend on.

This profile is evidence, not an implementation wish list. An unobserved feature remains unvalidated even when an MCP specification or SDK supports it.

## 2. Relationship to the Feature Design

The V17 feature design establishes the direct boundary:

```text
Owner → ChatGPT → MCP → Binnacle → one Raspberry Pi
```

Binnacle is deterministic. ChatGPT is the sole reasoning, planning, diagnostic, and multi-device coordination agent. Binnacle has one normal remote interface: MCP.

This profile supplies the evidence required by the V17 `MCP-PROFILE` contract. It does not define Binnacle's tool catalogue; that is the responsibility of [`mcp-interface.md`](mcp-interface.md).

## 3. Officially Documented Facts

The following statements are supported by current OpenAI documentation as of the source-review date:

1. ChatGPT connects to remote MCP servers. A private or on-premises server can be connected in developer mode through Secure MCP Tunnel.
2. OpenAI's current MCP server guidance uses Streamable HTTP, normally on a stable `/mcp` endpoint.
3. Tools are the primary mechanism for live data and controlled actions.
4. Tool definitions should provide stable names, descriptions, JSON Schema inputs, accurate annotations, and useful model-readable results.
5. Tool results may contain `structuredContent`, `content`, and client-specific `_meta`.
6. `_meta` is hidden from the model but is not secure storage and is not an authorisation mechanism.
7. Tool annotations may influence ChatGPT's confirmation and safety behaviour, but do not replace server-side authentication, authorisation, validation, or policy.
8. Developer-mode availability and permissions depend on account and workspace policy.
9. Current OpenAI documentation states that ChatGPT Pro custom MCP connections are limited to read/fetch permissions, while full write/modify MCP support is available to Business and Enterprise/Edu. The actual account must still be probed because entitlement and rollout behaviour can change.
10. OpenAI instructs developers to connect the actual server and record tool selection, arguments, results, errors, and confirmation behaviour.

OpenAI's public documentation does not currently state one exact MCP protocol revision implemented by the production ChatGPT client. Any exact revision in this document must therefore come from observed traffic or client declarations.

## 4. Initial Compatibility Strategy

### 4.1 Server-side protocol support

The bootstrap implementation should use an official MCP SDK that can support the current MCP revision and the earlier initialization-based revisions required by real clients.

Binnacle should not deliberately depend on modern-only behaviour before ChatGPT proves it. It should also avoid implementing an old wire protocol manually when the official SDK can negotiate or serve compatible protocol profiles.

### 4.2 Binnacle dependency profile

The initial Binnacle interface depends only on this conservative subset:

- remote or tunneled MCP connectivity;
- Streamable HTTP or a tunnel-supported transport;
- server initialization or equivalent modern discovery;
- tool discovery;
- tool invocation;
- JSON Schema inputs;
- model-readable text results;
- structured JSON results where accepted;
- protocol and tool execution errors;
- server-side authentication, authorisation, and local policy.

The initial interface does not depend on:

- MCP Tasks;
- elicitation or MRTR;
- Resources;
- Prompts;
- dynamic tool-list notifications;
- server-initiated model generation;
- MCP Sampling;
- Roots;
- custom UI or MCP Apps.

A feature may be implemented as a probe without becoming a Binnacle dependency.

## 5. Compatibility Status Vocabulary

Every tested feature receives exactly one status:

| Status | Meaning |
| --- | --- |
| `observed-supported` | The actual ChatGPT connection declared or exercised the feature successfully and the result matched the test oracle. |
| `observed-limited` | The feature worked only under recorded limits, permissions, or degraded semantics. |
| `declared-unexercised` | ChatGPT declared support, but no complete end-to-end test has passed. |
| `not-declared` | The feature was absent from the observed client declaration or discovery behaviour. |
| `test-failed` | A valid probe was attempted and failed; the failure evidence is retained. |
| `host-policy-blocked` | Account, workspace, plan, or host policy prevented the test independently of MCP wire compatibility. |
| `server-not-implemented` | Binnacle did not implement the required probe. |
| `not-tested` | No reliable conclusion exists. |
| `unsupported-by-design` | Binnacle V1 intentionally does not use the feature. |

Absence of an invocation is not proof of non-support. A feature is `observed-supported` only after a deterministic probe or an unambiguous protocol declaration plus the required behavioural test.

## 6. Initial Observation Record

The first live test must populate this table. Unknown values remain explicit.

| Field | Initial value |
| --- | --- |
| ChatGPT product | ChatGPT web |
| Account plan | Pro |
| Workspace type | Personal, to be confirmed |
| Developer mode | To be confirmed |
| Connection method | Secure MCP Tunnel preferred for the private Raspberry Pi |
| Binnacle endpoint transport | To be observed |
| Requested or negotiated MCP revision | Unknown |
| Protocol era | Unknown: initialization-based or stateless |
| Client implementation metadata | Unknown |
| Client capabilities | Unknown |
| Authentication context | Unknown |
| Tool discovery behaviour | Unknown |
| Tool-list refresh behaviour | Unknown |
| Structured result handling | Unknown |
| Tool annotation behaviour | Unknown |
| Read operation entitlement | Unknown |
| Write/modify entitlement | Official documentation suggests blocked on Pro; live probe required |
| Cancellation behaviour | Unknown |
| Tasks support | Unknown |
| Elicitation or MRTR support | Unknown |
| Resources support | Unknown |
| Prompts support | Unknown |
| Result-size limits | Unknown |
| Request timeout | Unknown |
| Reconnection behaviour | Unknown |

## 7. Protocol-Version Detection

Binnacle must record protocol facts without exposing credentials or sensitive transport material.

### 7.1 Initialization-based client

When ChatGPT uses an initialization-based MCP revision, record:

- requested `protocolVersion`;
- client implementation name and version;
- declared client capabilities;
- server-selected protocol version;
- session behaviour where present;
- subsequent protocol-version headers;
- initialized server capabilities.

### 7.2 Stateless client

When ChatGPT uses a stateless MCP revision, record:

- protocol version carried on each request;
- request-declared client capabilities;
- whether `server/discover` is called;
- request method and tool-name headers where applicable;
- cache and list behaviour;
- any declared extensions.

### 7.3 Sanitisation

The compatibility record must not retain:

- access tokens;
- cookies;
- bearer credentials;
- private keys;
- full authentication headers;
- secrets in tool arguments;
- raw personal data not required for the test.

Transport identity may be recorded only as a non-reusable identifier or digest sufficient for correlation.

## 8. Bootstrap Probe Surface

The first server should expose only harmless or tightly bounded probe tools.

| Tool | Purpose | Side effect |
| --- | --- | --- |
| `binnacle_probe` | Return the Binnacle build, device summary, observed protocol facts, and a correlation ID | None |
| `system_inspect` | Prove useful read-only access to the Raspberry Pi | None |
| `probe_result_formats` | Test nested structured output, arrays, nullable values, warnings, and model-readable text | None |
| `probe_error` | Test protocol-safe execution errors and known Binnacle outcome classes | None beyond bounded delay where selected |
| `compatibility_report` | Return the sanitised local observation record | None |
| `probe_workspace_write` | Test write entitlement inside one disposable Binnacle-owned directory | Controlled write; disabled until read-only tests pass |
| `probe_workspace_cleanup` | Remove only artefacts created by the write probe | Controlled deletion; disabled until write succeeds |

The write probe must be confined to a disposable directory such as:

```text
/var/lib/binnacle/probe-workspace/
```

It must not access the Binnacle repository, system configuration, services, credentials, arbitrary paths, or hardware.

## 9. Progressive Test Plan

### Stage 1 — Connection and discovery

Pass conditions:

- ChatGPT creates the connection;
- authentication or tunnel association succeeds;
- Binnacle receives a valid protocol request;
- tool discovery succeeds;
- `binnacle_probe` is callable;
- the server records the actual protocol facts.

### Stage 2 — Fundamental tool contract

Test:

- required and optional arguments;
- unknown arguments;
- invalid types;
- empty inputs;
- output schema handling;
- `structuredContent`;
- model-readable `content`;
- accurate annotations;
- unknown tool behaviour;
- tool execution errors;
- reconnection and rediscovery.

### Stage 3 — Read-only device use

Test:

- current device identity and profile;
- system inspection;
- bounded directory listing;
- bounded file reading;
- Git status;
- service status;
- bounded log reading.

Successful Stage 3 establishes the initial read-only B1 workflow.

### Stage 4 — Controlled write entitlement

Attempt only after Stage 3 passes.

Test:

- creation of one disposable file;
- replacement under an explicit version or digest precondition;
- read-back verification;
- deletion of that file;
- rejection outside the probe workspace;
- ChatGPT confirmation or host-policy behaviour.

A failure must distinguish:

- MCP protocol incompatibility;
- ChatGPT plan or workspace policy;
- tool metadata or annotation rejection;
- Binnacle local policy;
- server execution failure.

### Stage 5 — Binnacle-owned long-running operation

Binnacle must first test its own explicit operation handle:

```text
start → operation_id → status → cancel → result
```

This test must not depend on MCP Tasks. It verifies:

- operation identity retention;
- status retrieval after the initiating call;
- cooperative cancellation;
- terminal and uncertain states;
- reconnection.

### Stage 6 — Optional MCP features

Probe individually:

- Resources;
- Prompts;
- elicitation;
- MRTR;
- MCP Tasks;
- progress notifications;
- list-changed notifications;
- result caching or modern discovery extensions.

An optional feature failure must not invalidate the working tool core.

## 10. Initial Capability Matrix

| Capability | Binnacle V1 dependency | Initial status | Promotion requirement |
| --- | ---: | --- | --- |
| Remote or tunneled connectivity | Yes | `not-tested` | Successful connection from the actual ChatGPT account |
| Streamable HTTP | Preferred | `not-tested` | Observed or tunnel-confirmed support |
| Tool discovery | Yes | `not-tested` | Stable tool list received by ChatGPT |
| Tool invocation | Yes | `not-tested` | Representative valid and invalid calls pass |
| Input JSON Schema | Yes | `not-tested` | Required, optional, and invalid input tests pass |
| Text result content | Yes | `not-tested` | ChatGPT receives and uses the result |
| Structured result content | Preferred | `not-tested` | Schema-conforming result is preserved and usable |
| Output schema | Preferred | `not-tested` | ChatGPT accepts and correctly handles it |
| Tool annotations | Preferred | `not-tested` | Metadata is accepted and observed behaviour recorded |
| Authentication | Yes for supported use | `not-tested` | Actual request identity and rejection paths validated |
| Read/fetch operations | Yes | `not-tested` | Stage 3 passes |
| Write/modify operations | Required for full V1 | `not-tested` | Stage 4 passes; otherwise full S1 and H1 remain blocked |
| Resources | No initial dependency | `not-tested` | Concrete interface need plus successful probe |
| Prompts | No | `unsupported-by-design` | New feature-design justification |
| Elicitation or MRTR | No initial dependency | `not-tested` | Declared support and full retry/decline tests |
| MCP Tasks | No initial dependency | `not-tested` | Declared extension plus type-preserving lifecycle tests |
| Progress notifications | No initial dependency | `not-tested` | Useful and reliable end-to-end observation |
| Dynamic tool-list notification | No security dependency | `not-tested` | Reliable refresh test; invocation validation remains authoritative |
| Sampling | No | `unsupported-by-design` | New product-boundary review |
| Roots | No | `unsupported-by-design` | New interface and security review |
| Custom UI or MCP Apps | No | `unsupported-by-design` | Separate product decision |

## 11. Compatibility Report Schema

The sanitised report should contain:

```json
{
  "schema_version": "1.0",
  "test_run_id": "opaque-id",
  "observed_at": "RFC3339 timestamp",
  "chatgpt_surface": "web",
  "account_plan": "pro",
  "connection_method": "secure-mcp-tunnel",
  "server_build": "version-or-commit",
  "protocol": {
    "version": "observed-value",
    "era": "initialization-based-or-stateless",
    "client_info": {
      "name": "observed-value",
      "version": "observed-value"
    },
    "capabilities": {},
    "extensions": {}
  },
  "features": {
    "tools": "observed-supported",
    "structured_content": "not-tested",
    "write_modify": "host-policy-blocked",
    "tasks": "not-declared"
  },
  "limits": {},
  "failures": [],
  "notes": []
}
```

The exact storage format is an implementation decision. The fields and semantics are part of the compatibility evidence contract.

## 12. Promotion and Regression Rules

A feature may become a Binnacle dependency only when:

1. the actual target ChatGPT connection has exercised it;
2. the behaviour matches a written test oracle;
3. failure, cancellation, and reconnection cases are covered;
4. account and workspace requirements are recorded;
5. the feature is added to `mcp-interface.md`;
6. regression tests are assigned.

The profile must be rerun when any of these changes:

- ChatGPT product or account plan;
- workspace policy;
- connection method;
- MCP SDK;
- Binnacle authentication;
- protocol revision;
- advertised client capability;
- tool schema or annotation;
- optional extension;
- documented host entitlement.

## 13. Sources

Primary sources reviewed on 2026-08-08:

- [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [OpenAI: MCP server concepts](https://developers.openai.com/plugins/concepts/mcp-server)
- [OpenAI: Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: Authentication for plugins](https://developers.openai.com/plugins/build/auth)
- [OpenAI Help: Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt)
- [MCP specification](https://modelcontextprotocol.io/specification)
- [MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP 2026-07-28 release overview](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

These sources do not replace the live profile. When documentation and observed behaviour differ, the discrepancy must be recorded and Binnacle may depend only on the behaviour that passes the actual-host test.
