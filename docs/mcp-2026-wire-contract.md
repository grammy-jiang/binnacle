# Binnacle MCP 2026-07-28 Wire Contract

- **Status:** Draft — target-revision wire contract
- **Target revision:** `2026-07-28`
- **Related contracts:** `MCP-PROFILE`, `MCP-INTERFACE`
- **Revision support:** [`mcp-revision-support.md`](mcp-revision-support.md)
- **Feature-design basis:** [`design.md`](design.md), V17
- **Last protocol review:** 2026-08-08

## 1. Purpose

This document freezes Binnacle's wire-level requirements when one request is dispatched under MCP revision `2026-07-28`.

It does not change the legacy profiles defined in `mcp-revision-support.md`. A legacy adapter must render the same Binnacle operation facts using that legacy revision's schemas rather than copying the target-era envelope.

The target-era adapter must validate the wire result before sending it. An internally valid Binnacle result that cannot be represented by the selected MCP schema is a server conformance failure and must not be emitted as malformed success.

## 2. Mandatory Modern Server Surface

### 2.1 `server/discover`

Binnacle must implement `server/discover` for `2026-07-28`.

A client may call another valid request without calling discovery first. Therefore:

- discovery is mandatory server functionality but optional client behaviour;
- Binnacle must not create a discovery-before-use session requirement;
- every request still carries and validates its own protocol and client metadata;
- a cached discovery result never grants controller identity or operation authority.

### 2.2 Discover result

The final discovery response must contain:

- `resultType: "complete"`;
- `supportedVersions` containing the exact set from `mcp-revision-support.md`;
- `capabilities`;
- `serverInfo`;
- `ttlMs`;
- `cacheScope`;
- optional concise `instructions`.

Because Binnacle discovery can vary by authenticated controller, device profile, local policy, and capability lifecycle, the bootstrap profile uses:

```json
{
  "ttlMs": 0,
  "cacheScope": "private"
}
```

A later non-zero TTL requires evidence that the exact discovery representation is stable for that duration and remains private to the authenticated security context.

### 2.3 Capabilities

A Binnacle server that exposes Tools must advertise a `tools` server capability in `server/discover`.

Binnacle must not advertise a primitive, feature, or extension merely because its SDK implements it. The advertised capabilities are the intersection of:

- the target revision;
- the deployed Binnacle build;
- the validated device profile;
- the authentication profile;
- the features Binnacle has promoted and tested.

For the bootstrap profile:

- `tools` is advertised;
- `resources` and `prompts` are omitted unless separately promoted;
- Sampling and Roots are omitted;
- the Tasks extension is omitted;
- optional notifications or extensions are omitted until tested.

## 3. Cacheable Results

### 3.1 Required hints

Every target-era result whose MCP schema is cacheable must contain both:

- `ttlMs` — non-negative cache lifetime in milliseconds;
- `cacheScope` — the protocol-defined cache scope.

This includes, where implemented:

- `server/discover`;
- `tools/list`;
- `resources/list`;
- `resources/read`;
- `prompts/list`;
- other target-era results explicitly defined as cacheable.

Absence of a hint is a conformance failure even when an SDK would inject a default on the wire. Tests must inspect the actual serialized response.

### 3.2 Private versus public

Use `cacheScope: "private"` whenever the representation can vary by:

- authenticated controller;
- scopes;
- device identity or profile;
- local policy;
- trust or restricted state;
- capability lifecycle;
- information-disclosure permission;
- any other authorization or owner-specific fact.

Binnacle's bootstrap discovery and Tool catalogue are authorization-dependent and therefore private.

A public scope is permitted only for a representation proven identical and safe across all controllers and anonymous contexts allowed by the profile. Personal V1 normally has no such remote catalogue.

### 3.3 TTL policy

The bootstrap default is `ttlMs: 0`.

A non-zero TTL requires:

- deterministic ordering;
- a versioned manifest or representation digest;
- a maximum-staleness analysis;
- a policy for profile or lifecycle changes during the TTL;
- regression evidence from the actual ChatGPT host.

Even while a cached catalogue is considered fresh, every Tool invocation is independently authenticated and authorized. Cache freshness never creates authority.

### 3.4 Deterministic ordering

List results must use deterministic ordering under the same authenticated representation and build. Tool ordering must not vary from map iteration, process restart, instance selection, or unrelated request order.

## 4. Result Discrimination

### 4.1 Final result

Every final `2026-07-28` success or represented Tool execution error uses the outer wire discriminator:

```json
{
  "resultType": "complete"
}
```

This applies to final results including:

- `server/discover`;
- `tools/list`;
- `tools/call`;
- status and cancellation Tools;
- any later supported Resource or Prompt request;
- final extension results where the extension contract does not define another discriminator.

SDK application types may hide this wire-only field. Conformance tests must inspect the serialized frame, not only the handler return object.

### 4.2 Input-required result

`resultType: "input_required"` is used only by a request type and client capability that validly support the target-era MRTR input-required contract.

The bootstrap interface does not depend on MRTR. It must never return `input_required` merely to request authentication, owner confirmation, missing required Tool arguments, or a policy exception.

### 4.3 Tasks

The `io.modelcontextprotocol/tasks` extension is not advertised in the bootstrap profile. No target-era `task` result may be emitted.

A future Tasks promotion must define its own extension schemas and cannot reuse the `2025-11-25` experimental Task vocabulary.

## 5. Tool Discovery Contract

### 5.1 `tools/list` envelope

A final target-era `tools/list` response must include:

- `resultType: "complete"`;
- deterministic `tools` array;
- `ttlMs`;
- `cacheScope`;
- pagination fields only when the selected list contract implements them.

The Tool catalogue is advisory. It must not expose a Tool outside the deployed profile, but omission or stale visibility is not an authorization decision.

### 5.2 Tool schema

Each Tool definition must include:

- unique `name`;
- precise `description`;
- valid `inputSchema` object;
- optional `title`;
- `outputSchema` when Binnacle returns structured output under a frozen schema;
- accurate annotations;
- `execution.taskSupport: "forbidden"` for the bootstrap profile where the target schema exposes this field.

JSON Schema defaults to Draft 2020-12 when `$schema` is absent. Binnacle should declare the schema URI explicitly in frozen manifests and fixtures.

Input and output schema root types are objects unless a future protocol and interface contract explicitly permits another form.

## 6. Tool Result Contract

### 6.1 Model-readable content

Binnacle adopts a stricter product rule than the minimum abstract MCP result type:

> Every Binnacle `tools/call` result, including a successful result and a Tool execution error, contains at least one concise model-readable TextContent block in `content`.

This rule ensures the model receives a bounded explanation even when it cannot use `structuredContent` reliably.

The text must:

- describe the same result as the structured data;
- identify failure, cancellation, or uncertainty honestly;
- avoid secrets and protected control-plane material;
- avoid adding facts absent from the canonical local result;
- be actionable for a correctable execution error.

For structured data, Binnacle should include a compact serialization or summary rather than duplicating an arbitrarily large payload.

### 6.2 Structured content

When a Tool declares `outputSchema`:

- the final result must contain `structuredContent`;
- `structuredContent` must validate against that exact schema before serialization;
- the schema and result use the same contract version;
- validation failure is a server conformance failure, not a successful Tool result;
- clients may independently validate the result.

When no output schema is declared, `structuredContent` may be omitted. Binnacle may still use a frozen unstructured content contract.

### 6.3 Tool execution error

A post-authentication, post-protocol Tool execution error must contain:

- `resultType: "complete"`;
- `isError: true`;
- non-empty model-readable `content`;
- structured error data when the Tool declares an output schema that includes the error form, or when a separately frozen error schema is selected;
- no reusable credentials or protected policy internals.

A Tool execution error is distinct from:

- HTTP `401` or `403` transport authorization failure;
- JSON-RPC protocol error;
- a successful status lookup representing an operation whose state is `failed`, `cancelled`, or `uncertain`.

A status lookup that successfully returns retained operation facts remains `isError: false`, regardless of the represented operation state.

## 7. Annotation Semantics

Annotations are untrusted model-facing metadata and never authorize an operation. Binnacle nevertheless publishes accurate explicit values for every Tool.

### 7.1 Protocol meanings

| Annotation | Meaning |
| --- | --- |
| `readOnlyHint` | Whether invoking the Tool can modify its environment |
| `destructiveHint` | For a modifying Tool, whether it may perform destructive rather than purely additive changes |
| `idempotentHint` | Whether repeated calls with the same arguments have no additional effect beyond the first successful effect |
| `openWorldHint` | Whether the Tool can interact with an open world of external entities rather than a closed local domain |

### 7.2 Cautious defaults

If an annotation is omitted, the effective protocol default is treated as:

```json
{
  "readOnlyHint": false,
  "destructiveHint": true,
  "idempotentHint": false,
  "openWorldHint": true
}
```

Binnacle does not rely on implicit defaults in its reviewed Tool manifest. It states all four values explicitly.

### 7.3 Destructive versus modifying

`destructiveHint: false` does not mean read-only. It means a modifying Tool is intended to be additive or otherwise non-destructive.

Examples:

- creating a new file without overwrite may be modifying but non-destructive;
- replacing, deleting, stopping, resetting, or truncating state is destructive;
- a Tool that may overwrite depending on an argument is destructive unless separate Tool contracts or closed schemas make the distinction reliable.

### 7.4 Idempotency

`idempotentHint: true` applies to the same semantic Tool contract and same arguments. It does not by itself provide the durable retry identity required for consequential operation reconciliation.

A Tool may be logically idempotent but still require controller, policy, and state revalidation on every call.

### 7.5 Open-world meaning

For Binnacle, the local Raspberry Pi and explicitly local kernel/filesystem/service state form the default closed domain. Network access, external repositories, package registries, remote APIs, other devices, or external identities are open-world interactions.

Reading untrusted local repository content does not necessarily make the Tool open-world, but its content provenance is still untrusted and governed separately.

## 8. Header and Protocol Error Boundary

Target-era requests must follow `mcp-revision-support.md` for:

- `MCP-Protocol-Version`;
- `Mcp-Method`;
- `Mcp-Name` where required;
- header/body disagreement;
- unsupported revision mapping;
- no protocol-session dependency.

The result contract in this document is applied only after the request passes target-era framing and transport authorization.

## 9. Validation Fixtures

The machine-readable cases are in:

```text
tests/fixtures/mcp/mcp-2026-wire.yaml
```

Required coverage includes:

- valid discovery;
- discovery without prior session;
- required tools capability;
- private zero-TTL bootstrap catalogue;
- missing cache fields;
- public cache leakage for authorization-dependent discovery;
- deterministic list ordering;
- missing final `resultType`;
- invalid result discriminator;
- success with model-readable content and schema-valid structured output;
- execution error with model-readable content;
- missing content;
- structured output violating `outputSchema`;
- status lookup representing failed or uncertain work without `isError`;
- annotation defaults and explicit values;
- destructive versus additive semantics;
- Tasks and MRTR absence in the bootstrap profile.

The oracle validates the serialized MCP wire frame after SDK processing.

## 10. Source Basis

This contract follows the final MCP `2026-07-28` specification and Tier 1 SDK migration guidance reviewed on 2026-08-08, including:

- mandatory server implementation of `server/discover`, while client use remains optional;
- server capability advertisement for Tools;
- required `resultType` wire discrimination;
- required cache hints on cacheable results;
- private cache treatment for authorization-dependent representations;
- output-schema validation;
- cautious Tool annotation defaults and meanings;
- separation of protocol errors and Tool execution errors.

A later SDK convenience or hidden public type cannot weaken the wire contract.