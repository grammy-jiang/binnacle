# Binnacle MCP Revision Support

- **Status:** Draft implementation contract
- **Contract version:** `1.1.0`
- **Target revision:** `2026-07-28`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Observed-host evidence:** [`mcp-profile.md`](mcp-profile.md)

## 1. Scope

This contract defines the finite MCP revision set that Binnacle accepts and the revision-specific dispatcher behaviour used before any Tool handler or local policy decision runs.

The server-supported revision set and the revision observed from ChatGPT are separate facts. An observed client can select one supported profile; it cannot add a revision or mix rules from two revisions.

## 2. Supported Set

Binnacle accepts exactly:

```json
[
  "2026-07-28",
  "2025-11-25",
  "2025-06-18",
  "2025-03-26"
]
```

Binnacle rejects:

- `2024-11-05` and the deprecated HTTP+SSE transport;
- unspecified drafts and implementation aliases;
- missing versions where no legacy negotiation record exists;
- a request that mixes modern and legacy lifecycle or result shapes.

MCP Tasks are disabled for all revisions until the actual ChatGPT profile passes a version-specific extension test. Binnacle-owned `operation_id`, status, cancellation, and result Tools remain the portable long-running-work contract.

## 3. Target-Era Dispatch: `2026-07-28`

The target revision is stateless at the MCP protocol layer. There is no `initialize` exchange and no `Mcp-Session-Id`.

Every request must contain:

- `MCP-Protocol-Version: 2026-07-28`;
- `Mcp-Method` matching the JSON-RPC body `method`;
- `Mcp-Name` matching the body Tool, Resource, Prompt, or extension name when the method has a named target;
- request `_meta` containing the reserved protocol version, client information, and client capabilities required by the selected SDK profile.

`server/discover` is implemented by the server but is optional for the client to call. A normal request cannot depend on an earlier discovery request.

### 3.1 Header/body mismatch

Header and body routing fields are one integrity boundary. A mismatch is rejected before authentication-dependent Tool dispatch and before any Binnacle operation is admitted.

The Binnacle mapping is:

```text
HTTP status: 400
JSON-RPC error code: -32020
error.data.code: protocol_header_mismatch
```

This mapping applies to a mismatched `Mcp-Method`, `Mcp-Name`, or duplicated protocol-version declaration. No handler, reservation, idempotency record, or consequential effect is created.

### 3.2 Missing or unsupported target version

A missing, malformed, or unsupported target-era version is rejected as:

```text
HTTP status: 400
JSON-RPC error code: -32021
error.data.code: unsupported_protocol_version
```

The response may list the finite supported set but must not expose authentication or policy state.

### 3.3 Result shapes

Every final target-era result is serialized with `resultType: "complete"`. MRTR results use their protocol-defined discriminator and are accepted only when the request declares the required client capability. Tasks use the independently negotiated Tasks extension and are otherwise rejected as unsupported.

## 4. Legacy Dispatch: `2025-11-25`, `2025-06-18`, `2025-03-26`

A legacy client negotiates one revision through `initialize`. Binnacle selects the highest mutually supported listed revision and records it in the protocol session.

After initialization, every Streamable HTTP request must carry:

```text
MCP-Protocol-Version: <negotiated revision>
```

If an SDK recovery path accepts a missing header for `2025-03-26`, that behaviour is compatibility evidence only and is never the positive conformance path.

A header that differs from the negotiated revision is rejected with HTTP `400` before method dispatch. A session identifier cannot be used with the target revision and cannot be transferred between authenticated controllers.

Legacy final results do not receive the target-era `resultType` field. Legacy cancellation notifications affect only the referenced in-flight MCP request; they do not prove cancellation of a retained Binnacle operation.

## 5. Per-Revision Matrix

| Area | `2026-07-28` | Supported legacy revisions |
| --- | --- | --- |
| Lifecycle | Stateless, self-contained request | `initialize` plus initialized session |
| Version source | Per-request version header and reserved `_meta` | Negotiated version plus subsequent version header |
| Routing | `Mcp-Method` and, when applicable, `Mcp-Name` must match body | JSON-RPC body; transport/session validation first |
| Discovery | Server implements `server/discover`; client call optional | Initialization advertises server capabilities |
| Tools | Per-request capabilities; target wire results | Negotiated capabilities; legacy result shapes |
| Cache hints | Target cache contract | Only when the selected legacy revision defines them |
| MRTR | Core retry pattern when declared | Not used |
| Elicitation | Through declared target capability/MRTR | Revision-specific legacy mechanism only after live validation |
| Tasks | Optional extension, disabled by default | Experimental/legacy task vocabulary disabled |
| Cancellation | Transport loss is not Binnacle cancellation; use `operation_cancel` | `notifications/cancelled` is request-scoped; durable operation cancellation uses `operation_cancel` |
| Sessions | Prohibited | Required where the negotiated transport creates one |

## 6. Error Boundary

- HTTP `401`/`403` are reserved for transport authentication/authorization failures.
- JSON-RPC protocol errors cover malformed, unsupported, or revision-invalid MCP messages.
- Tool execution errors occur only after successful transport authentication, revision dispatch, schema validation, and Tool selection.
- A revision error must not be represented as a successful Tool result.

## 7. Conformance Requirements

For each supported revision, fixtures must include:

- a complete positive handshake or self-contained request;
- a positive Tool listing and Tool call;
- correct final-result shape;
- wrong-version, missing-version, and cross-era negatives;
- routing/header mismatches for the target revision;
- session/header misuse for legacy revisions;
- cancellation that reaches the intended cancellation layer;
- disabled Tasks and unsupported extension cases.

A fixture intended to test cancellation, Tasks, or result semantics must first be a valid request for that revision. A generic failure before the intended layer is not a passing oracle.

## 8. Invariants

1. One request is evaluated under exactly one supported revision.
2. Header/body mismatch creates no Tool dispatch or local effect.
3. Modern requests never acquire an implicit protocol session.
4. Legacy post-initialization requests use their negotiated version header.
5. MCP Task or request identity never replaces Binnacle `operation_id` or idempotency identity.
6. Observed ChatGPT behaviour cannot silently expand the supported revision set.
