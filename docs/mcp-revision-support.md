# Binnacle MCP Revision Support

- **Status:** Draft — implementation contract for the bootstrap server
- **Related contracts:** `MCP-PROFILE`, `MCP-INTERFACE`
- **Feature-design basis:** [`design.md`](design.md), V17
- **ChatGPT evidence record:** [`mcp-profile.md`](mcp-profile.md)
- **Last protocol review:** 2026-08-08

## 1. Purpose

This document freezes the MCP protocol revisions that the Binnacle bootstrap server intends to accept and the revision-specific behaviour it must apply.

It deliberately separates two facts:

1. **Server-supported revisions:** the finite set of wire contracts that Binnacle implements and tests.
2. **Observed ChatGPT revision:** the revision and capabilities presented by the actual ChatGPT connection and recorded in `mcp-profile.md`.

Observed ChatGPT behaviour can select a supported profile. It cannot silently add another server-supported revision or alter that revision's wire contract.

## 2. Decision

### 2.1 Target revision

Binnacle's target MCP revision is:

```text
2026-07-28
```

New Binnacle interface work uses the target revision unless a legacy compatibility rule is explicitly required.

### 2.2 Supported legacy revisions

The bootstrap server also supports these initialization-based Streamable HTTP revisions:

```text
2025-11-25
2025-06-18
2025-03-26
```

The supported set is therefore exactly:

```json
[
  "2026-07-28",
  "2025-11-25",
  "2025-06-18",
  "2025-03-26"
]
```

### 2.3 Explicitly unsupported revisions and transports

Binnacle V1 does not support:

- MCP revision `2024-11-05` or earlier;
- the deprecated HTTP+SSE transport used by `2024-11-05`;
- an unspecified draft revision;
- a date-shaped version not listed above;
- implementation-specific version aliases;
- a request that mixes rules from more than one revision.

Supporting an additional revision requires a documented change, positive and negative conformance fixtures, and a compatibility regression against every existing supported revision.

## 3. Why This Set

The supported legacy set begins with `2025-03-26`, the first revision that defines Streamable HTTP at the normal MCP endpoint. This keeps one remote transport family while covering the three final initialization-based revisions that may plausibly be presented by a current client.

The older `2024-11-05` transport requires separate HTTP+SSE endpoints and materially expands the implementation and security surface. It is not needed for the ChatGPT-first bootstrap goal and is excluded.

The server may use an official SDK that serves modern and legacy clients from one application, but SDK capability does not expand the Binnacle support claim. Only the revisions listed here are accepted.

## 4. Revision Detection and Dispatch

### 4.1 General rules

Binnacle must determine the protocol revision from protocol-defined fields, never from:

- `User-Agent`;
- client display name;
- network source address;
- remembered conversation state;
- tool arguments;
- an assumed ChatGPT rollout.

The selected revision is immutable for the request and, for legacy revisions, for the negotiated protocol session.

### 4.2 Modern path: `2026-07-28`

A request uses the modern path only when all applicable modern envelope requirements are present and consistent, including:

- `MCP-Protocol-Version: 2026-07-28` on Streamable HTTP;
- per-request protocol metadata and client capabilities;
- `Mcp-Method` and, where required, `Mcp-Name` matching the JSON-RPC body;
- no dependency on a prior `initialize` exchange or `Mcp-Session-Id`.

`server/discover` must be implemented, but a client is not required to call it before another valid request.

### 4.3 Legacy path: 2025 revisions

A request enters the legacy path through `initialize`.

The `initialize.params.protocolVersion` value is evaluated against the three supported legacy revisions. The negotiated result is bound to the resulting legacy connection or session context. Later requests must not switch revision within that context.

For `2025-06-18` and `2025-11-25`, subsequent Streamable HTTP requests must carry the negotiated `MCP-Protocol-Version` header.

For `2025-03-26`, absence of that later header is accepted because the revision predates the mandatory-header rule. If a header is present, it must agree with the negotiated revision.

### 4.4 Dispatch precedence

The server applies this order:

1. Validate HTTP and JSON-RPC framing that is independent of MCP revision.
2. Determine whether the request is a legacy `initialize` or a modern self-contained request.
3. Select exactly one supported revision.
4. Validate revision-specific headers, metadata, lifecycle, capabilities, method availability, and result schema.
5. Only then dispatch to the Binnacle operation contract.

A request must never be retried internally under another revision after revision-specific validation fails.

## 5. Unsupported and Conflicting Version Behaviour

### 5.1 Unsupported legacy initialization request

When an initialization-based client requests an unsupported version, Binnacle follows legacy negotiation rules and responds with the latest supported legacy revision:

```text
2025-11-25
```

If the client does not support the returned revision, it is expected to disconnect. Binnacle must not silently continue under the client's unsupported requested revision.

If the request cannot be parsed as a valid initialization request, the server returns the applicable protocol error rather than negotiating.

### 5.2 Unsupported modern request

A self-contained request carrying an unsupported protocol version is rejected before tool dispatch.

For `2026-07-28`-style HTTP framing, the response must use the revision's unsupported-protocol-version mapping, including JSON-RPC code `-32022` where a well-formed request ID is available, and an appropriate HTTP failure status.

### 5.3 Missing protocol version

- A modern self-contained request without its required protocol version is rejected.
- A post-initialization `2025-06-18` or `2025-11-25` HTTP request without the required version header is rejected unless the negotiated session context supplies an unambiguous revision and the applicable SDK contract explicitly permits recovery.
- A post-initialization `2025-03-26` request may omit the version header.

The bootstrap conformance profile must record any SDK fallback used. A fallback is not applied to another revision.

### 5.4 Header and body disagreement

A modern request whose standard MCP headers disagree with the JSON-RPC body is rejected before operation dispatch using the `2026-07-28` header-mismatch contract.

A legacy initialization request whose protocol-version header and body disagree is rejected. Binnacle must not reproduce a permissive SDK behaviour that negotiates from only one of the conflicting values.

### 5.5 Session misuse

- A `2026-07-28` request must not require or derive authority from `Mcp-Session-Id`.
- A legacy request requiring a server-issued session ID must include the correct ID after initialization.
- A session ID cannot select a different protocol revision.
- A valid session is not a Binnacle controller identity, operation identity, or authority source.

## 6. Per-Revision Contract Matrix

| Concern | `2025-03-26` | `2025-06-18` | `2025-11-25` | `2026-07-28` |
| --- | --- | --- | --- | --- |
| Protocol era | Initialization-based | Initialization-based | Initialization-based | Stateless, self-contained requests |
| Entry point | `initialize`, then `notifications/initialized` | `initialize`, then `notifications/initialized` | `initialize`, then `notifications/initialized` | Any valid request; `server/discover` available but optional for clients |
| Version source | `initialize.params.protocolVersion` | Initialization plus later `MCP-Protocol-Version` header | Initialization plus later `MCP-Protocol-Version` header | Per-request `MCP-Protocol-Version` and request metadata |
| Protocol session | Optional Streamable HTTP session | Optional Streamable HTTP session | Optional Streamable HTTP session | No protocol session and no `Mcp-Session-Id` dependency |
| Remote transport | Streamable HTTP POST/GET | Streamable HTTP POST/GET | Streamable HTTP POST/GET, including polling/resumption rules | Streamable HTTP per-request response; no legacy resumable request stream |
| JSON-RPC batching | Receiving batches required by this revision | Not supported | Not supported | Not supported |
| Client capabilities | Negotiated during initialization | Negotiated during initialization | Negotiated during initialization | Declared per request |
| Server capabilities | Returned during initialization | Returned during initialization | Returned during initialization | Returned by `server/discover`; server still validates each request independently |
| Tools baseline | `tools/list`, `tools/call`, content results | Adds structured tool output support | JSON Schema 2020-12 default and clarified execution-error semantics | Modern result discriminators, cache hints, standard request headers, per-request capabilities |
| Structured tool output | Not a Binnacle dependency; return revision-valid content | Supported when the tool contract declares it | Supported when the tool contract declares it | Supported with the target-era result envelope and schema validation |
| Authorization generation | 2025-03 OAuth framework | OAuth resource-server and resource-indicator requirements | Updated discovery and incremental-scope behaviour | Target-era authorization hardening; exact security profile is defined separately |
| Formal extension framework | No | No | No | Yes, through per-request/server discovery extension capabilities |
| Tasks | Not available | Not available | Experimental core Tasks exist, but Binnacle does not advertise or use them | `io.modelcontextprotocol/tasks` extension exists, but Binnacle does not advertise or use it until live validation and a separate promotion |
| Elicitation | Not available | Legacy server-initiated elicitation may exist, but is not a bootstrap dependency | Legacy server-initiated elicitation may exist, but is not a bootstrap dependency | MRTR input-required result pattern may be probed but is not a bootstrap dependency |
| Core cancellation | `notifications/cancelled` for an in-flight request | `notifications/cancelled` for an in-flight request | `notifications/cancelled`; experimental task calls use their own task cancellation | Closing the per-request HTTP response stream signals cancellation; stdio uses `notifications/cancelled` |
| Task cancellation | Not applicable | Not applicable | Experimental Tasks require the 2025 task contract | Extension cancellation is cooperative and is not a verified Binnacle `cancelled` state |
| Durable Binnacle work | Explicit Binnacle `operation_id` | Explicit Binnacle `operation_id` | Explicit Binnacle `operation_id` | Explicit Binnacle `operation_id` |
| Final operation truth | Binnacle operation lifecycle | Binnacle operation lifecycle | Binnacle operation lifecycle | Binnacle operation lifecycle |

## 7. Revision-Specific Result Rules

The Binnacle operation result is revision-independent internally. The MCP adapter must render that result using the selected revision's valid wire shape.

Required rules:

- Do not emit a field introduced by a later revision where the selected revision rejects unknown or incompatible result shapes.
- Preserve model-readable `content` for tool execution results in every supported revision.
- Use `structuredContent` only where the selected revision supports it.
- Use `resultType: "complete"` for a final `2026-07-28` result where required by the target schema.
- Never return a `2025-11-25` experimental Task shape on the `2026-07-28` extension path.
- Never return a `2026-07-28` extension Task shape to a legacy client.
- A successful MCP status lookup remains a successful tool call even when the represented Binnacle operation is `failed`, `cancelled`, or `uncertain`.

Canonical result schemas are defined separately from this revision-dispatch contract.

## 8. Tasks Policy

Binnacle's bootstrap and initial V1 interfaces do not depend on MCP Tasks.

The server must not advertise:

- experimental `2025-11-25` Tasks; or
- the `io.modelcontextprotocol/tasks` extension for `2026-07-28`.

Long-running work uses the Binnacle-owned `operation_id`, status, cancellation, and result tools.

A future Tasks adapter requires:

1. observed ChatGPT support for one exact task contract;
2. revision-specific schemas and cancellation semantics;
3. positive and negative conformance fixtures;
4. proof that the adapter does not replace Binnacle operation identity or lifecycle;
5. a documented interface promotion.

## 9. Observed ChatGPT Profile

The server-supported revision set in this document is static until changed through review.

The actual ChatGPT observation record in `mcp-profile.md` must separately record:

- requested or negotiated revision;
- modern or legacy dispatch path;
- declared capabilities;
- methods exercised;
- transport behaviour;
- authentication context;
- host-policy limitations;
- passed and failed probes.

A live observation may narrow the Binnacle dependency profile to one supported revision. It does not delete the server's conformance obligation for another revision that remains listed here.

## 10. Conformance Requirements

The machine-readable case manifest is:

```text
tests/fixtures/mcp/revision-conformance.yaml
```

For every supported revision, implementation tests must cover:

- positive revision selection;
- valid initialization or self-contained entry;
- valid tool discovery and invocation;
- revision-valid result rendering;
- cancellation signal handling;
- unsupported method behaviour;
- missing and conflicting version evidence;
- cross-era shape rejection;
- session misuse;
- optional capability absence;
- Binnacle operation-handle preservation.

The test oracle must validate both the HTTP result and the JSON-RPC or MCP body where applicable.

## 11. Source Basis

This decision is based on the final MCP revisions and official SDK guidance reviewed on 2026-08-08:

- MCP `2025-03-26` changelog, lifecycle, and Streamable HTTP transport;
- MCP `2025-06-18` changelog, lifecycle, and protocol-version-header rule;
- MCP `2025-11-25` changelog, lifecycle, transport, cancellation, and experimental Tasks;
- MCP `2026-07-28` specification and release notes;
- official MCP Python SDK v2 dual-era guidance.

Source documentation can clarify a supported revision. A later source change cannot silently alter this frozen revision set.