# Binnacle MCP Interface Design

- **Status:** Draft — bootstrap interface before live ChatGPT validation
- **Contract:** `MCP-INTERFACE`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Compatibility evidence:** [`mcp-profile.md`](mcp-profile.md)
- **Applies to:** Binnacle V1
- **Last review:** 2026-08-08

## 1. Purpose

This document defines the MCP-facing interface between ChatGPT and one Binnacle instance.

It is an interface specification for an MCP server. It is not:

- a website design;
- a traditional human dashboard;
- a Companion application;
- a local reasoning-agent interface;
- an implementation-module design.

The interface must let ChatGPT inspect and operate one Raspberry Pi through deterministic, policy-controlled operations while preserving Binnacle's local authority, lifecycle, information, safety, and evidence boundaries.

## 2. Design Principles

### 2.1 Tools first

Tools are the primary Binnacle primitive because ChatGPT selects operations and Binnacle executes or observes them.

Resources are introduced only for a concrete context or retained-content need. Prompts are not used in V1 unless a later feature decision identifies a user-selected template that belongs to the server.

### 2.2 Minimal common protocol dependency

The bootstrap interface depends only on the fundamental behaviour validated by `mcp-profile.md`.

It must not require MCP Tasks, elicitation, Resources, Prompts, list-changed notifications, or modern-only discovery to complete the initial connection and read-only workflow.

### 2.3 Binnacle operation identity is authoritative

MCP request IDs, transport connections, conversations, and optional MCP Task IDs do not replace the Binnacle operation identity.

Every retained or consequential operation uses a server-minted `operation_id`. Subsequent status, cancellation, result, and evidence calls use that explicit handle.

### 2.4 Local policy remains authoritative

Tool discovery is advisory. Every call is independently authenticated and evaluated against:

- the current controller identity;
- device trust and profile;
- local policy;
- operation contract;
- explicit inputs;
- current verified state;
- resource and concurrency limits.

A visible or cached tool never grants authority.

### 2.5 Focused tools

Tools represent one recognisable operation. Avoid one generic tool with many unrelated modes.

A general-purpose primitive may exist where software engineering requires it, but it must have a narrowly defined contract and stronger policy than outcome-oriented tools.

### 2.6 Results are truthful local facts

A successful MCP transport response is not necessarily a successful Binnacle operation.

The result must distinguish:

- request acceptance;
- local authorisation;
- operation state;
- verified success;
- known failure;
- cancellation request;
- verified cancellation;
- uncertain effect or outcome.

## 3. Initial Protocol Surface

### 3.1 Transport

The preferred remote endpoint is Streamable HTTP at a stable path such as:

```text
/mcp
```

For a private Raspberry Pi, the initial ChatGPT connection should use Secure MCP Tunnel or another explicitly validated private connectivity mechanism.

The implementation may support multiple MCP protocol revisions through one endpoint. The exact ChatGPT profile is recorded in `mcp-profile.md`.

### 3.2 Server identity

The server advertises a stable name and semantic version.

Recommended identity:

```text
name: binnacle
version: <release-version>
```

Declared server metadata is descriptive and is not the enrolled Raspberry Pi identity.

### 3.3 Server instructions

Server-wide instructions should be short and operational. The most important guidance should fit within the first 512 characters.

Initial instruction intent:

> Binnacle operates one Raspberry Pi. Inspect current state before changes. Treat returned operation state as local fact. Transport success is not operation success. Use the operation ID for status and cancellation. Binnacle does not plan or interpret objectives.

Tool descriptions remain authoritative for tool-specific behaviour.

### 3.4 Primitive support

| Primitive or feature | Bootstrap position |
| --- | --- |
| Tools | Required |
| Resources | Deferred until a concrete retained-content need passes compatibility testing |
| Prompts | Not used |
| Sampling | Prohibited |
| Roots | Not used |
| Elicitation or MRTR | Optional probe only |
| MCP Tasks | Optional adapter only |
| Progress notifications | Optional probe only |
| List-changed notification | Optional and never an authorisation dependency |
| Custom UI | Not used |

## 4. Naming and Versioning

### 4.1 Tool names

Initial tool names use lowercase ASCII letters and underscores:

```text
binnacle_probe
system_inspect
probe_result_formats
probe_error
compatibility_report
probe_workspace_write
probe_workspace_cleanup
```

V1 operational tools should follow the same pattern:

```text
device_inspect
device_profile_get
filesystem_list
filesystem_read
filesystem_search
filesystem_write
filesystem_patch
command_run
operation_get
operation_cancel
service_inspect
service_restart
git_status
git_diff
```

Names are stable semantic identifiers. A behavioural breaking change requires a new tool name or a versioned contract that the compatibility profile proves ChatGPT handles safely.

### 4.2 Contract versions

Every tool definition includes a contract version in its structured result and server-side operation record.

A contract version changes when any of these change materially:

- input semantics;
- effects;
- risk class;
- policy prerequisites;
- result schema;
- error semantics;
- idempotency;
- cancellation;
- retention;
- recovery;
- information classification.

Changing only prose without changing semantics does not create a new contract version, but must still pass metadata regression tests.

## 5. Common Tool Metadata

Every tool definition should provide:

- `name`;
- `title`;
- precise `description`;
- closed `inputSchema`;
- `outputSchema` where supported;
- accurate annotations.

Input schemas should normally use:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

### 5.1 Annotations

Annotations must describe actual behaviour:

| Annotation | Rule |
| --- | --- |
| `readOnlyHint` | `true` only when no state can change |
| `destructiveHint` | `true` when the operation can cause irreversible or difficult-to-reverse effects |
| `idempotentHint` | `true` only when repeating the same contract and identity is safe |
| `openWorldHint` | `true` when the operation can affect or communicate with external systems |

Annotations inform host behaviour. Binnacle never treats them as authorisation.

### 5.2 Authentication metadata

Authentication must be transport- or authorisation-context based. Secrets and tokens must not be ordinary tool arguments.

Per-tool authentication or scope metadata may be added only after the actual ChatGPT authentication profile is validated.

## 6. Common Result Model

Each successful tool call should return:

- concise model-readable `content`;
- machine-readable `structuredContent`;
- an `outputSchema` when the observed ChatGPT profile accepts it reliably.

For compatibility, the text result should summarize the structured result without silently introducing facts that are absent from it.

### 6.1 Base fields

Tool-specific structured results should contain these common fields where applicable:

```json
{
  "schema_version": "1.0",
  "contract": {
    "name": "system_inspect",
    "version": "1.0"
  },
  "request_id": "opaque-request-correlation",
  "operation_id": null,
  "status": "succeeded",
  "summary": "Current system facts were collected.",
  "data": {},
  "warnings": [],
  "evidence": [],
  "error": null
}
```

### 6.2 Status values

The interface uses:

```text
rejected
authorised
running
paused
cancelling
cancelled
succeeded
failed
uncertain
```

A synchronous read-only tool may return `succeeded` directly without creating a retained `operation_id`.

A call that creates or advances retained work returns the authoritative `operation_id`.

### 6.3 Information boundaries

Tool results are classified by the V17 `INFO-BOUNDARY` contract:

- `never-disclosable`;
- `restricted-result`;
- `normal-result`.

Credentials, access tokens, raw authentication material, private keys, and Binnacle control-plane secrets are never returned through `content`, `structuredContent`, `_meta`, errors, logs, or resources.

`_meta` may carry client-specific non-secret information, but is never treated as secure storage or authority merely because it is hidden from the model.

## 7. Error Model

### 7.1 Protocol errors

Use JSON-RPC or MCP protocol errors for:

- malformed MCP messages;
- unsupported protocol method;
- unknown tool;
- request shape that does not satisfy the MCP call schema;
- internal protocol failure before a Binnacle operation can be identified.

### 7.2 Tool execution errors

Use a tool result with `isError: true` for actionable operation-level failures, including:

- invalid tool argument value;
- unsupported device profile;
- authentication or authorisation failure exposed through the selected profile;
- local policy rejection;
- stale or conflicting state;
- missing target;
- resource or concurrency rejection;
- execution failure;
- cancellation result;
- uncertain effect or outcome.

The structured error object should use:

```json
{
  "code": "policy_rejected",
  "message": "The requested path is outside the configured workspace.",
  "retryable": false,
  "operation_id": null,
  "details": {
    "policy_rule": "workspace-root"
  }
}
```

Error details must be actionable without leaking secrets or protected policy internals.

### 7.3 Initial error codes

| Code | Meaning |
| --- | --- |
| `invalid_argument` | A provided value is invalid under the tool contract |
| `unsupported_operation` | The operation or contract is not implemented |
| `unsupported_profile` | The Raspberry Pi profile does not support the operation |
| `authentication_required` | No acceptable controller authentication was present |
| `authentication_failed` | Presented authentication was invalid |
| `policy_rejected` | Local policy denied the explicit request |
| `stale_state` | A required observation or precondition is no longer current |
| `conflict` | Another operation or external change conflicts with the request |
| `resource_limit` | Resource, concurrency, or reservation limits block admission |
| `execution_failed` | Execution failed with known remaining effects |
| `cancellation_requested` | A cancellation request was accepted but not yet verified |
| `cancelled` | The contract's cancellation outcome was verified |
| `uncertain_outcome` | The effect or final state cannot be established safely |
| `result_expired` | The retained result is no longer available |
| `operation_not_found` | The operation identity is unknown or unavailable to the controller |

## 8. Bootstrap Compatibility Tools

These tools are implemented before the operational V1 catalogue.

### 8.1 `binnacle_probe`

Purpose: Verify connectivity, discovery, server identity, protocol observation, and basic structured results.

Input schema:

```json
{
  "type": "object",
  "additionalProperties": false
}
```

Output data:

```json
{
  "server": {
    "name": "binnacle",
    "version": "0.0.0"
  },
  "device": {
    "hostname": "string",
    "architecture": "string",
    "os": "string"
  },
  "protocol_observation": {
    "version": "string-or-null",
    "era": "initialization-based-or-stateless-or-unknown"
  },
  "correlation_id": "opaque-id",
  "server_time": "RFC3339"
}
```

Annotations:

```json
{
  "readOnlyHint": true,
  "destructiveHint": false,
  "idempotentHint": true,
  "openWorldHint": false
}
```

The protocol observation is sanitised and must not include credentials or raw authentication headers.

### 8.2 `system_inspect`

Purpose: Return useful read-only Raspberry Pi facts.

Input schema: Empty object.

Output data includes:

- enrolled device identity reference;
- hostname;
- Raspberry Pi model where deterministically available;
- OS and kernel;
- architecture;
- uptime;
- CPU summary;
- memory summary;
- filesystem summary;
- Binnacle service state.

Annotations: read-only, idempotent, closed-world.

### 8.3 `probe_result_formats`

Purpose: Test ChatGPT handling of structured and text results.

Input schema:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "include_warning": {
      "type": "boolean",
      "default": true
    }
  }
}
```

Output data includes:

- scalar values;
- arrays;
- nested objects;
- booleans;
- a nullable field;
- a warning list;
- stable identifiers.

No external or local state changes.

### 8.4 `probe_error`

Purpose: Test deterministic error handling.

Input schema:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "case": {
      "type": "string",
      "enum": [
        "invalid_argument",
        "policy_rejected",
        "execution_failed",
        "uncertain_outcome",
        "bounded_delay"
      ]
    },
    "delay_seconds": {
      "type": "integer",
      "minimum": 0,
      "maximum": 10
    }
  },
  "required": ["case"]
}
```

`bounded_delay` may delay only within the declared maximum and creates no device side effect.

### 8.5 `compatibility_report`

Purpose: Return the sanitised empirical profile defined by `mcp-profile.md`.

Input schema:

```json
{
  "type": "object",
  "additionalProperties": false
}
```

The report is read-only and contains no reusable authentication material.

### 8.6 `probe_workspace_write`

Purpose: Test ChatGPT write/modify entitlement and Binnacle local write policy.

This tool is disabled until read-only compatibility tests pass.

Input schema:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name": {
      "type": "string",
      "pattern": "^[A-Za-z0-9._-]{1,64}$"
    },
    "content": {
      "type": "string",
      "maxLength": 4096
    },
    "expected_sha256": {
      "type": ["string", "null"],
      "pattern": "^[a-f0-9]{64}$"
    }
  },
  "required": ["name", "content"]
}
```

Policy:

- root fixed to the probe workspace;
- no path separators in `name`;
- no symlink traversal;
- maximum file count and bytes;
- atomic replacement;
- digest returned after write;
- no repository, system, service, credential, hardware, or external access.

### 8.7 `probe_workspace_cleanup`

Purpose: Delete only one artefact previously created by the write probe.

The tool requires the exact name and expected digest. It rejects unknown, changed, linked, or out-of-root targets.

## 9. V1 Operational Tool Groups

The exact schemas are frozen only after the compatibility probe. These groups define the intended interface boundary.

### 9.1 Device inspection

Initial tools:

- `device_inspect`;
- `device_profile_get`.

They return current device facts and accepted profile facts without editing trust or policy.

### 9.2 Filesystem

Initial tools:

- `filesystem_list`;
- `filesystem_read`;
- `filesystem_search`;
- `filesystem_write`;
- `filesystem_patch`.

Requirements:

- explicit profile-defined roots;
- no implicit current directory;
- normalized paths;
- symlink and mount handling;
- file-size and result-size limits;
- expected digest or version for replacement where needed;
- atomic write where the contract promises it;
- exact changed-path evidence;
- no protected control-plane access.

### 9.3 Command execution

Initial tool:

- `command_run`.

The contract must declare:

- executable or shell semantics;
- argument representation;
- working directory;
- environment allowlist;
- stdin policy;
- timeout;
- output limits;
- process-tree containment;
- network and credential policy;
- resource limits;
- operation retention;
- cancellation;
- cleanup;
- uncertainty.

Arbitrary command execution must not inherit Binnacle's own privilege or control-plane access.

### 9.4 Operations

Initial tools:

- `operation_get`;
- `operation_cancel`.

`operation_get` returns the durable state, effects, evidence, warnings, and retention information.

`operation_cancel` requests the contract-defined cancellation path. Its return value distinguishes request acceptance from verified cancellation.

An `operation_list` tool is deferred until a concrete need and privacy policy are defined.

### 9.5 Services

Initial tools:

- `service_inspect`;
- `service_restart`.

The initial supported target is the Binnacle service under `SELF-MANAGE`. Broader service management is added only through validated contracts and policy.

### 9.6 Git and verification

Initial tools:

- `git_status`;
- `git_diff`.

Formatting, lint, test, and build commands may initially use `command_run` under a repository profile. Dedicated tools may replace common commands after usage evidence justifies them.

## 10. Prepared-Operation Pattern

Prepared operations are optional and are not proof of owner confirmation.

Where a consequential contract uses preparation:

```text
prepare → prepared_operation_id → execute_prepared
```

The prepared record binds:

- exact normalized input;
- device and profile;
- operation contract version;
- current deterministic preconditions;
- expiry;
- maximum effects;
- recovery and cancellation semantics.

Execution revalidates the record and current state before the first consequential boundary.

Preparation creates no authority and cannot bypass local policy. ChatGPT host confirmation remains outside Binnacle's verifiable facts.

The bootstrap interface does not require preparation. It may be introduced for command execution, service restart, self-update, or hardware actuation after the actual Host profile is known.

## 11. Long-Running Operations

### 11.1 Binnacle-native interface

The initial interface uses Binnacle's own operation handle:

```text
tool call → operation_id
operation_get(operation_id)
operation_cancel(operation_id)
```

This interface works whether or not ChatGPT supports MCP Tasks.

### 11.2 Optional MCP Tasks adapter

If the actual profile proves MCP Tasks support:

- the MCP Task represents one tool request;
- the Binnacle `operation_id` remains authoritative;
- task cancellation is projected as a cancellation request;
- an MCP Task terminal state must not overstate Binnacle's state;
- a completed tool result may still report a Binnacle `failed` or `uncertain` operation;
- reconnect and retention follow Binnacle's operation contract.

Tasks remain forbidden for tools whose contracts cannot be mapped honestly.

## 12. Resources and Large Results

Resources are deferred initially.

A Resource may be added for:

- retained operation evidence;
- large logs;
- large diffs;
- generated artefacts;
- stable device-profile content.

A tool may instead return a stable resource link after the actual ChatGPT profile proves that resource retrieval works.

Large content must not be silently truncated. The result must report:

- original size;
- returned size;
- truncation or pagination;
- digest;
- continuation or resource handle;
- expiry.

The server must not use a Resource to bypass information policy or Tool-result limits.

## 13. Discovery and Catalogue Changes

The bootstrap catalogue should be stable.

When the available tools change:

- Binnacle may advertise list-change support only if the observed ChatGPT profile handles it reliably;
- ChatGPT may require explicit refresh or reconnection;
- stale discovery never authorises a call;
- removed or disabled tools are rejected at invocation;
- metadata changes trigger compatibility regression tests.

Current policy or device state may be returned through inspection tools rather than continuously changing the catalogue.

## 14. Authentication and Controller Identity

The authentication design is finalized only after the actual ChatGPT profile is observed.

Requirements that do not change:

- declared client metadata is not authenticated controller identity;
- bearer credentials never appear in tool arguments;
- Binnacle verifies authentication on each request as required by the selected protocol and transport;
- authentication does not imply operation authorisation;
- controller replacement or trust reset invalidates old authority under `TRUST-CTRL`;
- transport loss does not silently transfer operation ownership.

For OAuth-based profiles, scopes should map to bounded operation groups and Binnacle must validate issuer, audience, expiration, and scope on each request.

## 15. Compatibility Probe and Freeze Criteria

The bootstrap interface may be promoted into the supported V1 interface only after:

1. the actual ChatGPT connection is recorded in `mcp-profile.md`;
2. connection and discovery pass;
3. every bootstrap tool passes valid and invalid inputs;
4. structured and text results are observed;
5. authentication and policy rejection are tested;
6. read-only B1 operations pass;
7. write entitlement is tested;
8. operation status and cancellation pass;
9. optional features are classified;
10. result-size, timeout, and reconnection limits are recorded.

If ChatGPT Pro permits only read/fetch, the profile may support a read-only B1 preview, but S1 repository modification and H1 service restart cannot be labelled supported.

## 16. Required Test Cases

### 16.1 Discovery

- stable tool names and descriptions;
- valid schemas;
- deterministic order where supported;
- refresh after metadata change;
- cached tool invocation after local disable.

### 16.2 Inputs

- missing required field;
- unknown field;
- wrong type;
- boundary length;
- Unicode;
- path traversal;
- symlink target;
- stale digest;
- unsupported operation version.

### 16.3 Results

- text-only fallback;
- structured result;
- nullable field;
- empty array;
- warning;
- truncation;
- retained result;
- result expiry;
- never-disclosable data absence.

### 16.4 Lifecycle

- synchronous success;
- asynchronous start;
- status after initiating call ends;
- cancellation before effect;
- cancellation during work;
- inability to cancel;
- reconnect;
- restart;
- duplicate call;
- uncertain prior outcome.

### 16.5 Policy and security

- unauthenticated request;
- wrong controller;
- out-of-root file;
- protected control-plane target;
- unauthorized network target;
- resource exhaustion;
- command child-process escape;
- credential leakage attempt;
- untrusted output suggesting another operation.

## 17. Source Basis

Primary sources reviewed on 2026-08-08:

- [Binnacle V17 feature design](design.md)
- [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [OpenAI: MCP server concepts](https://developers.openai.com/plugins/concepts/mcp-server)
- [OpenAI: Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: Authentication for plugins](https://developers.openai.com/plugins/build/auth)
- [OpenAI Help: Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt)
- [MCP specification](https://modelcontextprotocol.io/specification)
- [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

The interface uses only the subset validated by `mcp-profile.md`. A later MCP revision or optional feature does not become a dependency merely because the server SDK supports it.
