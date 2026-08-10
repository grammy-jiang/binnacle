# Binnacle MCP `2026-07-28` Wire Contract

- **Status:** Draft target-revision contract
- **Contract version:** `1.1.0`
- **Revision:** `2026-07-28`
- **Revision dispatcher:** [`mcp-revision-support.md`](mcp-revision-support.md)

## 1. Scope

This document defines the serialized target-era MCP frames that Binnacle emits and accepts. Application-facing SDK types may hide wire-only fields; conformance therefore validates serialized frames as well as handler values.

## 2. Request Envelope

Every target-era HTTP request is self-contained and includes:

```text
MCP-Protocol-Version: 2026-07-28
Mcp-Method: <JSON-RPC method>
Mcp-Name: <named target when applicable>
```

The JSON-RPC body carries matching method/name values and request `_meta` with protocol version, client information, and client capabilities. Header/body mismatch follows the `-32020` contract in `mcp-revision-support.md`.

There is no `initialize`, `initialized`, or `Mcp-Session-Id` in this revision.

## 3. `server/discover`

Binnacle implements `server/discover`; a client is not required to call it.

A serialized successful discovery result contains:

- `resultType: "complete"`;
- declared server capabilities, including Tools;
- current extension declarations;
- concise server instructions where supported;
- `ttlMs` and `cacheScope`;
- server identity in result metadata at:
  `_meta["io.modelcontextprotocol/serverInfo"]`.

`serverInfo` is not a top-level `DiscoverResult` member in the target profile. The metadata identity is descriptive and does not establish enrolled-device trust.

When discovery varies by controller, authorization, device profile, or policy, Binnacle returns:

```json
{
  "ttlMs": 0,
  "cacheScope": "private"
}
```

A later stable profile may use a positive private TTL only after host-cache behaviour is validated.

## 4. Tools Capability and Catalogue

The discovery capability advertises Tools support. `tools/list`:

- returns deterministic ordering;
- includes `ttlMs` and `cacheScope`;
- exposes only Tool definitions from the verified manifest and current catalogue phase;
- never acts as authorization;
- is revalidated on every invocation.

A target-era Tool definition contains the protocol Tool fields, including name, title where supported, description, input schema, optional output schema, annotations, and protocol-defined metadata.

It must not contain the legacy `execution.taskSupport` object. Target-era Tasks are represented only by the separately negotiated `io.modelcontextprotocol/tasks` extension.

## 5. Tool Annotations

Binnacle applies cautious defaults:

| Annotation | Default | Meaning |
| --- | --- | --- |
| `readOnlyHint` | `false` | `true` only when the Tool cannot intentionally change state |
| `destructiveHint` | `true` for non-read-only Tools unless proved otherwise | Indicates destructive potential, not certainty |
| `idempotentHint` | `false` | `true` only for the declared identity and retry contract |
| `openWorldHint` | `true` when external systems may be contacted | Covers effective external communication, including redirects/proxies |

Annotations guide the host; they do not authenticate the controller or authorize an operation.

## 6. Results

Every final target-era result is serialized with:

```json
{"resultType":"complete"}
```

This discriminator may be consumed by an SDK before application code sees the result.

### 6.1 Tool results

Binnacle adopts a product rule stricter than the minimum abstract MCP shape: every Tool success and every Tool execution error includes at least one concise TextContent entry in `content`.

Where `outputSchema` is declared:

- `structuredContent` must validate against it;
- text and structured forms must not contradict each other;
- credentials, authority material, and non-disclosable content remain excluded;
- the current MCP-call outcome remains separate from any represented operation outcome.

A successful status lookup uses `isError: false` even when the represented operation is `failed`, `cancelled`, or `uncertain`.

### 6.2 Execution errors

A post-authentication Tool execution error:

- uses `isError: true`;
- includes model-readable `content`;
- includes a schema-valid structured execution-error envelope when declared;
- must not be used for pre-dispatch HTTP authentication or protocol-version failures.

## 7. Cacheable Responses

The target profile requires `ttlMs` and `cacheScope` on all protocol operations classified as cacheable by MCP, including Tool and Resource list/read operations.

Binnacle never uses `cacheScope: "public"` for a response that can vary by authentication, authorization, policy, device state, or information class.

A cache entry never grants authority and cannot prevent fresh server-side invocation checks.

## 8. MRTR and Extensions

MRTR uses target-era wire discriminators such as `resultType: "input_required"` only when the request declares the required client capability and the Tool contract permits it.

Tasks:

- are an independent extension;
- are absent unless the request and server negotiate `io.modelcontextprotocol/tasks`;
- never use the removed legacy Tool `execution` member;
- never replace Binnacle `operation_id` or idempotency identity.

Sampling, Roots, and custom UI are outside Binnacle V1.

## 9. Schema and Fixture Rules

Fixtures use one canonical request vocabulary:

- `http_headers` for HTTP headers;
- `body` for the JSON-RPC body;
- `wire_result` for serialized results;
- `tool` for a Tool name in fixture metadata;
- explicit setup facts rather than ambiguous flags such as `prior_request`.

A positive semantic case must first pass request-envelope validation. A negative case must name the expected failure layer so an earlier generic failure cannot false-pass.

## 10. Invariants

1. `serverInfo` is emitted in target result metadata, not as a top-level discovery field.
2. Final target results carry `resultType: "complete"` on the wire.
3. Target Tools do not carry legacy Task execution metadata.
4. Cacheable responses carry explicit private/public scope and TTL.
5. Every Binnacle Tool result includes bounded model-readable `content`.
6. Declared output schemas are validated before serialization.
7. Extension fields appear only after extension negotiation.
