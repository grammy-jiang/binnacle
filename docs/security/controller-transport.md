# Binnacle Controller and Remote Transport Security

- **Status:** Draft — mandatory bootstrap security contract
- **Related contracts:** `TRUST-CTRL`, `MCP-PROFILE`, `MCP-INTERFACE`, `LOCAL-POLICY`
- **Feature-design basis:** [`../design.md`](../design.md), V17
- **Revision dispatch:** [`../mcp-revision-support.md`](../mcp-revision-support.md)
- **Last security review:** 2026-08-08

## 1. Purpose

This document defines how Binnacle authenticates the ChatGPT MCP controller and secures its remote Streamable HTTP boundary.

A tunnel, TCP connection, TLS connection, MCP session, client display name, source address, or ChatGPT conversation is not an authenticated Binnacle controller identity by itself.

The governing rules are:

> Every accepted remote request is bound to one validated controller security profile and one stable controller identity.

> Transport authentication is evaluated before MCP tool execution. Local Binnacle policy is evaluated after authentication and cannot be bypassed by transport success.

## 2. Scope and Deferred Facts

Binnacle supports two candidate authentication patterns for the bootstrap connection:

1. **OAuth resource-server profile:** Binnacle validates an access token issued specifically for its canonical resource URI.
2. **Trusted gateway assertion profile:** a validated tunnel or gateway authenticates the external client and sends Binnacle a cryptographically protected, narrowly scoped controller assertion over a protected local hop.

The live `MCP-FEAS` result must select and version one profile before supported remote operation is claimed.

The design does not assume that ChatGPT supplies tenant, workspace, authorized-party, token-binding, or proof-of-possession claims. When a selected profile requires a claim that the actual connection does not provide, that profile is infeasible; Binnacle must not invent a value or treat absence as a wildcard.

Anonymous remote MCP access is not supported.

## 3. Canonical Controller Identity

### 3.1 Identity tuple

For each validated authentication profile, Binnacle derives a controller identity from an immutable, versioned tuple:

```text
controller_profile_id
issuer
subject
canonical_audience
client_id_or_authorized_party
owner_tenant_or_workspace_boundary
credential_binding_identifier
```

Fields not supplied by the selected profile are represented as explicitly absent and cannot later acquire meaning without a controller-profile version change.

The stored `controller_id` is a non-reversible digest or opaque local identifier derived from the validated tuple. Raw access tokens and reusable credentials are never stored in an operation, audit event, result, or compatibility report.

### 3.2 One active ChatGPT controller

Personal V1 permits one locally active normal ChatGPT controller identity per Binnacle instance.

A request from another validly authenticated identity is not a continuation of the existing controller. Controller replacement is a separate local trust transition and does not transfer operation ownership automatically.

### 3.3 Profile identity is not client metadata

MCP `clientInfo`, implementation names, versions, and other declared client metadata are descriptive only. They may be recorded for compatibility evidence but cannot participate in controller authentication or scope decisions unless the authenticated security profile independently binds the same value.

## 4. OAuth Resource-Server Profile

When OAuth protects the MCP endpoint, Binnacle acts as an OAuth resource server.

### 4.1 Canonical resource URI

The profile declares exactly one canonical audience/resource URI, for example:

```text
https://binnacle.example.invalid/mcp
```

The configured URI includes the path when the path distinguishes this Binnacle resource. Scheme and host canonicalization rules are fixed by the profile. Redirects, alternate hosts, tunnel aliases, and internal loopback addresses do not become valid token audiences.

### 4.2 Access-token validation

Before processing an MCP request, Binnacle must validate all applicable fields:

| Validation | Requirement |
| --- | --- |
| Signature or token authenticity | Validate with a pinned or securely discovered trusted key set, introspection endpoint, or equivalent profile mechanism |
| Algorithm | Explicit allowlist; reject `none`, algorithm confusion, and unapproved algorithms |
| Key identity | Current trusted key or introspection authority; unknown or retired keys fail |
| Issuer | Exact canonical issuer match, including RFC 9207 issuer validation where the flow supplies it |
| Audience/resource | Must include the canonical Binnacle resource; another API or another Binnacle instance is invalid |
| Subject | Required stable subject for the selected owner/controller profile |
| Authorized client | Validate `client_id`, `azp`, or profile-equivalent binding when supplied or required |
| Tenant/workspace | Exact match when the selected profile defines one; absence cannot satisfy a required tenant boundary |
| Expiration | `exp` must be current under the accepted clock-skew policy |
| Not-before and issued-at | Enforce `nbf`; reject implausible or over-age `iat` under the profile |
| Scopes | Require the operation-class scopes before MCP dispatch |
| Revocation | Apply introspection, short-lived-token policy, local revocation state, or another declared mechanism |
| Credential binding | Validate `cnf`, DPoP, mTLS, gateway assertion binding, or the declared bearer-token replay controls |
| Token identifier | Validate and record a non-reusable digest of `jti` or equivalent where supplied |

Opaque tokens require authoritative introspection or an equivalent validation mechanism. They are not accepted based only on string format or tunnel origin.

### 4.3 Bearer-token fallback

If the actual host supports only bearer tokens without proof-of-possession:

- tokens must be short-lived under a profile-defined maximum lifetime;
- TLS is mandatory on the externally reachable hop;
- tokens must never be logged, returned, forwarded, or placed in tool arguments;
- request and operation replay controls remain mandatory;
- token revocation limitations are recorded honestly;
- the profile must accept the residual replay risk explicitly before promotion.

A tunnel does not convert a bearer token into proof-of-possession.

### 4.4 Scopes

Scopes are transport authorization, not Binnacle local policy.

A minimal scope vocabulary may include:

```text
binnacle:connect
binnacle:observe
binnacle:modify
binnacle:execute
binnacle:self-manage
```

The exact vocabulary is versioned by the selected authentication profile. An operation requires both:

1. sufficient authenticated scope; and
2. a positive local policy and current-state decision.

A broad scope does not grant access to an unlisted path, target, command, device, or risk class.

## 5. Trusted Gateway Assertion Profile

A private tunnel or gateway may terminate the external authentication flow, but network association alone is insufficient.

### 5.1 Required assertion

The gateway must send Binnacle a signed or mutually authenticated assertion containing at least:

- assertion profile and version;
- gateway identity;
- external issuer or authentication source;
- stable subject;
- canonical Binnacle audience;
- authorized client identity when known;
- tenant/workspace boundary when the profile uses one;
- scopes;
- issued-at, expiry, and unique assertion identifier;
- binding to the protected local channel or request;
- key identifier and algorithm.

Binnacle validates the assertion independently. Plain `X-User`, `X-Forwarded-User`, or similar headers are never sufficient.

### 5.2 Local hop

The hop from the tunnel/gateway to Binnacle must use one of:

- a Unix-domain socket with owner and mode restrictions;
- loopback with mutually authenticated TLS;
- loopback with an equivalent cryptographic gateway assertion and no untrusted local listener;
- another profile-reviewed local transport with the same security properties.

The direct network listener must be disabled or separately authenticated. A request that bypasses the gateway must fail before MCP dispatch.

### 5.3 Gateway trust lifecycle

The profile declares:

- trusted gateway identities and keys;
- rotation and overlap rules;
- maximum assertion lifetime;
- replay cache duration;
- compromise and revocation response;
- behaviour when the gateway or identity service is unavailable.

Failure to validate the gateway assertion produces no fallback to source-IP trust.

## 6. Request, Session, and Operation Binding

### 6.1 Every request

Every authenticated request receives a controller security context containing:

- local `controller_id`;
- controller-profile version;
- validated issuer and audience identifiers;
- scope set;
- credential or assertion identifier digest;
- authentication time and expiry;
- tenant/workspace value or explicit absence;
- revocation freshness;
- connection/gateway binding evidence where applicable.

MCP dispatch and tool execution receive this verified context separately from model-supplied arguments.

### 6.2 Legacy MCP sessions

A legacy `Mcp-Session-Id` is transport state only.

When legacy sessions are used:

- the session record is bound to the authenticated `controller_id` and protocol revision;
- every later request re-authenticates or revalidates the security context;
- a session request under a different controller is rejected;
- the session cannot extend token or assertion expiry;
- a session identifier alone creates no identity, authorization, or operation ownership.

### 6.3 Binnacle operations

Before any effect, the durable operation record binds:

- `operation_id`;
- authenticated `controller_id`;
- controller-profile version;
- operation contract and version;
- normalized input digest;
- applicable scope and local-policy decision;
- authentication evidence digest and expiry;
- protocol revision and request correlation.

Every status, result, cancellation, retry, and lifecycle-advancing request must authenticate as the same active controller unless a future explicit transfer contract is added.

Authentication expiry during an operation is handled by the operation contract. It never silently changes the operation owner.

## 7. Downstream Credentials and Token Exchange

The inbound MCP credential is for Binnacle only.

Binnacle must not:

- forward the inbound access token to a package registry, Git host, cloud API, local service, or another MCP server;
- reinterpret a ChatGPT token as an operating-system credential;
- expose the token to a command, child process, environment variable, file, log, or result;
- use an inbound token whose audience is another service.

For downstream access, Binnacle must use:

- a separately configured non-exportable credential;
- a downstream token issued specifically for that resource;
- a standards-based token exchange explicitly approved by the security profile; or
- no credential, when the target is public.

The downstream credential's identity, audience, scope, lifetime, storage, and disclosure contract are independent of the MCP controller token.

## 8. Remote Endpoint and TLS Boundary

### 8.1 External TLS

Every externally reachable MCP and authorization endpoint must use HTTPS with certificate validation appropriate to the profile.

The profile records:

- public endpoint URI;
- TLS termination component;
- certificate trust source;
- minimum TLS version and cipher policy;
- client-certificate requirements, if any;
- hop-by-hop protection after termination;
- certificate/key rotation and failure behaviour.

Plaintext external HTTP is unsupported.

### 8.2 Bind rules

For a private Raspberry Pi deployment:

- Binnacle should bind to a Unix socket or loopback interface behind the validated tunnel;
- binding directly to `0.0.0.0` or a LAN interface requires separate authenticated TLS and an explicit profile decision;
- only the configured MCP path is exposed;
- debug, metrics, health, or administration endpoints are not reachable through the public MCP route unless separately authenticated and reviewed.

### 8.3 Trusted proxies

Binnacle trusts forwarded headers only from configured proxy identities or socket boundaries.

Untrusted requests cannot set or override:

- client address;
- scheme;
- host;
- authenticated subject;
- tenant/workspace;
- client certificate details;
- authorization result.

A forwarded-header chain with an untrusted hop is rejected or reduced to the directly observed peer according to the profile.

### 8.4 Host validation

The HTTP `Host` or `:authority` value must match the configured external or internal endpoint allowlist for the selected path.

Unexpected hosts, absolute-form request targets, and ambiguous proxy rewrites are rejected before MCP parsing where practical.

### 8.5 Origin and CORS

Binnacle validates `Origin` when present.

Default policy:

- deny unexpected browser origins;
- do not send wildcard credentialed CORS responses;
- allow only exact reviewed origins, methods, and headers if browser access is required;
- treat a missing `Origin` from a non-browser MCP client according to the validated host profile, not as automatic failure or trust;
- reject `null` origin unless explicitly tested and required.

### 8.6 CSRF and cookies

Personal V1 does not use ambient cookies for MCP authorization. Bearer or gateway credentials are supplied explicitly on every request.

Because cookie authentication is disabled, a cross-site request cannot gain authority merely from browser cookie attachment. If cookie-based authentication is introduced later, a new profile must define SameSite policy, anti-CSRF tokens, origin checks, and logout/revocation semantics before use.

## 9. Replay and Freshness Controls

The selected security profile defines:

- maximum access-token or assertion lifetime;
- accepted clock skew;
- unique token/assertion identifiers where available;
- replay-cache retention;
- request-id and idempotency-key binding;
- duplicate request behaviour;
- key and revocation freshness;
- maximum authentication-cache lifetime.

A repeated credential may authenticate multiple legitimate requests only within its declared bearer or proof-of-possession model. It does not permit repeating a non-idempotent Binnacle operation.

Consequential operations require their separate durable idempotency and operation identity contract.

## 10. Resource Limits at the Transport Boundary

Before JSON parsing or tool dispatch, the endpoint enforces profile limits for:

- request-line and header bytes;
- header count;
- authorization-header size;
- JSON body bytes;
- nesting depth and parsing budget;
- simultaneous connections;
- simultaneous in-flight requests per controller and globally;
- request rate and burst per controller, gateway, and source boundary;
- authentication failures and challenge rate;
- SSE or response-stream duration;
- idle and total request timeouts.

Limits must reserve enough capacity for authenticated status and cancellation calls. A limit failure must not create a Binnacle operation.

## 11. Authentication and Authorization Error Boundary

### 11.1 HTTP `401 Unauthorized`

Use HTTP `401` before MCP tool dispatch when:

- authorization is missing;
- a token or assertion is invalid, expired, revoked, untrusted, or malformed;
- signature, issuer, audience, subject, authorized client, tenant/workspace, or binding validation fails;
- required authentication freshness cannot be established.

The response includes an appropriate `WWW-Authenticate` challenge and protected-resource metadata reference where the selected OAuth profile requires it. Reusable credential details are never echoed.

### 11.2 HTTP `403 Forbidden`

Use HTTP `403` before tool dispatch when:

- the controller is authenticated but lacks required transport scopes or resource permission;
- the selected authentication profile forbids the requested MCP method or tool class;
- a valid controller is outside the allowed tenant/workspace boundary.

For OAuth insufficient scope, include a `WWW-Authenticate` challenge with `error="insufficient_scope"` and the minimum required scope set where applicable.

### 11.3 Protocol errors

Use HTTP or JSON-RPC protocol errors for malformed MCP framing, unsupported versions, header/body mismatch, unknown methods, and other pre-operation protocol failures under the selected revision.

### 11.4 Tool execution errors

After successful controller authentication and sufficient transport scope, Binnacle local-policy, state, target, resource, and execution failures are returned through the revision-valid tool execution error contract.

Examples include:

- workspace path outside local policy;
- command denied by the device profile;
- stale state;
- resource conflict;
- execution failure;
- uncertain outcome.

These may use `isError` where the selected MCP revision defines it. `isError` must not replace an HTTP `401` or `403` that should have occurred before tool dispatch.

## 12. Audit and Secret Handling

Security records include only non-reusable evidence:

- controller ID;
- authentication-profile version;
- issuer, audience, client, and tenant/workspace identifiers or safe digests;
- scope set;
- credential/assertion ID digest;
- validation and revocation freshness result;
- request, session, and operation correlation;
- HTTP authorization outcome;
- policy outcome after authentication.

Never record:

- access or refresh tokens;
- authorization codes;
- raw gateway assertions;
- private keys;
- cookies;
- full authentication headers;
- downstream secrets.

## 13. Validation and Promotion

The machine-readable security cases are defined in:

```text
tests/fixtures/mcp/controller-transport-security.yaml
```

A remote profile cannot be promoted until it passes:

- direct tunnel-bypass attempts;
- missing, invalid, expired, and revoked credentials;
- wrong issuer, audience, subject, authorized client, tenant/workspace, and scope;
- key rotation and stale-key cases;
- assertion and request replay;
- session/controller mismatch;
- operation access by another controller;
- token passthrough detection;
- untrusted proxy and forwarded-header injection;
- Host and Origin violations;
- CORS and cookie/CSRF assumptions;
- request size, rate, connection, and concurrency limits;
- correct `401`, `403`, protocol-error, and tool-error separation.

The compatibility report records the exact profile, evidence, residual limitations, and host entitlement. Passing through a tunnel without these tests is not sufficient.

## 14. Source Basis

This contract follows the official MCP authorization and security guidance reviewed on 2026-08-08, including:

- OAuth resource-server treatment for HTTP MCP servers;
- canonical resource indicators and audience validation;
- protected-resource metadata and `WWW-Authenticate` challenges;
- HTTP `401`, `403`, and `400` authorization error boundaries;
- explicit prohibition of inbound token passthrough;
- Streamable HTTP Origin validation and local bind guidance.

The actual ChatGPT authentication mechanism remains an empirical dependency of `MCP-FEAS`. Observed host behaviour may select a profile but cannot weaken this contract.