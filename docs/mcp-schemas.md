# Binnacle Canonical MCP Schemas and Operation Lifecycle

- **Status:** Draft implementation contract
- **Contract version:** `1.1.0`
- **Common schema:** `schemas/mcp/binnacle-common.schema.json`
- **Bootstrap inputs:** `schemas/mcp/bootstrap-inputs.schema.json`
- **Bootstrap outputs:** `schemas/mcp/bootstrap-outputs.schema.json`
- **Lifecycle policy:** `spec/operation/lifecycle.yaml`

## 1. Purpose

This document explains the machine-valid schemas used by Binnacle Tools. Examples in prose are non-authoritative when they conflict with a referenced JSON Schema.

## 2. Three Separate Outcomes

Every invocation distinguishes:

1. **HTTP/MCP outcome** — whether the request passed transport and protocol validation.
2. **Current Tool-call outcome** — `succeeded` or `execution_error` for this call.
3. **Represented operation state** — the state of retained local work, if any.

A successful `operation_get` call remains a successful Tool call even when the represented operation is `failed`, `cancelled`, or `uncertain`.

## 3. Canonical Tool Envelopes

### 3.1 Success

Every structured success contains all of these fields:

```json
{
  "schema_version": "1.1",
  "call_status": "succeeded",
  "tool": {
    "name": "binnacle_probe",
    "contract_version": "1.1"
  },
  "request_id": "request-1",
  "data": {},
  "operation": null,
  "evidence": [],
  "warnings": []
}
```

`operation` and `warnings` are required fields. `operation` may be `null`; `warnings` may be an empty array.

### 3.2 Execution error

Every structured execution error contains:

```json
{
  "schema_version": "1.1",
  "call_status": "execution_error",
  "tool": {
    "name": "probe_workspace_write",
    "contract_version": "1.1"
  },
  "request_id": "request-2",
  "error": {
    "code": "policy_rejected",
    "message": "Write probe is disabled by local policy.",
    "retryable": false,
    "retry_action": "none",
    "operation_id": null,
    "details": []
  },
  "operation": null,
  "evidence": [],
  "warnings": []
}
```

Pre-dispatch HTTP `401`/`403` and protocol errors are not Tool execution-error envelopes.

## 4. Evidence

Canonical Tool evidence records:

- stable evidence identity and time;
- source and provenance;
- `normal-result` or `restricted-result` classification;
- freshness limit;
- optional result digest;
- operation and audit references;
- bounded typed facts.

Evidence never stores credentials, authority material, raw idempotency keys, or unbounded command/repository/prompt payloads.

## 5. Operation States

The authoritative states are:

```text
received
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

The JSON Schema binds each state to:

- terminality;
- permitted effect-knowledge values;
- error presence where required;
- cancellation verification for `cancelled`;
- successful verification for `succeeded`;
- `automatic_retry_allowed: false` for `uncertain` and all other V1 retained states.

Automatic retry is not inferred from an operation state. Retry reconciliation uses the explicit idempotency contract.

## 6. Progress

To keep the canonical schema enforceable without non-standard cross-field JSON Schema extensions, progress uses one of two closed shapes:

```json
{"known": false, "millionths": null, "unit": null}
```

or:

```json
{"known": true, "millionths": 500000, "unit": "operation"}
```

`millionths` is an integer from `0` through `1000000`. Tool-specific exact counts belong in the Tool `data` object and must not contradict the lifecycle progress value.

## 7. Bootstrap Tool Contracts

The bootstrap schema registry contains:

- `binnacle_probe` `1.1`;
- `system_inspect` `1.1`;
- `probe_result_formats` `1.1`;
- `probe_error` `1.1`;
- `compatibility_report` `1.1`;
- `probe_workspace_prepare` `1.1`;
- `probe_workspace_write` `1.1`;
- `probe_workspace_cleanup` `1.1`.

The preparation Tool is read-only and creates a short-lived state binding. It returns `prepared_operation_id` and `execution_nonce`. Those values are not owner authority; the execute Tool still requires controller authentication, current local policy, exact input matching, host-profile treatment, and idempotency identity.

## 8. Path Inputs

Bootstrap workspace paths are POSIX-relative only. Schemas reject:

- a leading `/`;
- drive-letter prefixes;
- backslashes;
- `..` path segments;
- NUL, CR, or LF;
- colon-containing alternate path forms.

The executor still canonicalizes the workspace root and fails closed on symlink, mount, or race ambiguity. Schema validation is not the filesystem security boundary.

## 9. Output Validation

Before serialization, Binnacle validates `structuredContent` against the exact output definition referenced by the reviewed Tool manifest.

A validation failure:

- prevents the malformed result from being sent as success;
- emits a bounded internal error and audit event;
- does not disclose the rejected payload;
- does not change the underlying operation state.

Every target-era Tool result also includes bounded model-readable `content` as required by the wire contract.

## 10. Compatibility Status Vocabulary

The canonical status set is:

```text
observed-supported
observed-limited
declared-unexercised
not-declared
test-failed
host-policy-blocked
server-not-implemented
not-tested
unsupported-by-design
unstable
expired
not-applicable
```

`mcp-profile.md`, evaluation manifests, and `compatibility_report` use these exact values.

## 11. Invariants

1. Required envelope fields are never omitted; nullable and empty values are explicit.
2. Tool-call success is independent from represented operation success.
3. `uncertain` work never authorizes automatic retry.
4. Operation state and effect knowledge cannot contradict each other.
5. Progress has one closed, schema-enforceable representation.
6. Every declared Tool output schema has positive and negative fixtures.
7. Preparation identifiers cannot be synthesized by the model and create no authority by themselves.
