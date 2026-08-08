# Binnacle Canonical MCP Schemas and Operation State Machine

- **Status:** Draft — canonical V1 data contract
- **Schema dialect:** JSON Schema Draft 2020-12
- **Related contracts:** `MCP-INTERFACE`, `OP-LIFECYCLE`, `OP-BOUNDARY`, `INFO-BOUNDARY`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Wire contract:** [`mcp-2026-wire-contract.md`](mcp-2026-wire-contract.md)
- **Idempotency:** [`operation-idempotency.md`](operation-idempotency.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines the canonical machine-valid schemas for Binnacle Tool structured results, evidence, execution errors, bootstrap inputs and outputs, and durable operation state.

Examples in prose are non-normative. The JSON Schema files and lifecycle transition specification are normative for implementation and tests.

## 2. Canonical Files

| File | Purpose |
| --- | --- |
| `schemas/mcp/binnacle-common.schema.json` | Shared Tool, error, evidence, and operation definitions |
| `schemas/mcp/bootstrap-inputs.schema.json` | Exact input schemas for every bootstrap Tool |
| `schemas/mcp/bootstrap-outputs.schema.json` | Exact success/error unions for every bootstrap Tool output |
| `spec/operation/lifecycle.yaml` | Allowed states, transitions, terminality, timestamps, effects, retry, cancellation, verification, and retention |
| `tests/fixtures/mcp/schema-validation.yaml` | Positive and invalid-input/output schema cases |
| `tests/fixtures/operation/lifecycle.yaml` | State-transition and lifecycle-consistency cases |

Every Tool manifest `input_schema_contract` and `output_schema_contract` resolves to one `$defs` entry in these files. The resolved schema digest is included in the reviewed Tool manifest.

## 3. Three Independent Outcome Layers

Binnacle must not collapse these layers.

### 3.1 Protocol and transport result

This layer answers whether the HTTP, JSON-RPC, authentication, MCP revision, method, and Tool-call envelope were valid.

Examples:

- HTTP `401` — controller authentication failed;
- HTTP `403` — authenticated controller lacks transport permission;
- JSON-RPC error — malformed MCP request or unknown method/Tool;
- successful `tools/call` response — Tool handler returned a result.

The Binnacle structured Tool schemas do not wrap protocol errors.

### 3.2 Current Tool call result

The structured field `call_status` is exactly one of:

- `succeeded` — the current Tool call completed its declared request successfully;
- `execution_error` — the Tool call was well-formed and authenticated but could not complete because of input, policy, state, resource, execution, retention, or other Tool-level conditions.

Mapping to MCP:

| `call_status` | MCP `isError` |
| --- | --- |
| `succeeded` | `false` or omitted where the selected revision permits omission |
| `execution_error` | `true` |

Every Tool result also contains non-empty model-readable `content` outside `structuredContent`, as defined by the target wire contract.

### 3.3 Represented operation status

A successful status or result lookup has:

```text
call_status = succeeded
isError = false
```

regardless of whether the represented operation is:

- `cancelled`;
- `failed`;
- `uncertain`;
- any other valid state.

The lookup succeeded because it returned authoritative operation facts. The represented operation's outcome is carried in `operation.state`, `operation.terminality`, `operation.effect_knowledge`, and verification/error fields.

## 4. Common Structured Result

### 4.1 Success

A successful structured result contains:

- `schema_version`;
- `call_status: "succeeded"`;
- exact `tool` identity and contract version;
- Tool-specific `data`;
- canonical `evidence`;
- optional represented `operation`;
- optional bounded `warnings`.

Objects are closed unless the schema explicitly names an extension boundary.

### 4.2 Execution error

An execution-error result contains:

- `schema_version`;
- `call_status: "execution_error"`;
- exact `tool` identity and contract version;
- canonical `error`;
- canonical `evidence`;
- optional represented `operation` when an operation record exists;
- optional bounded warnings.

It must not masquerade as protocol failure or return a successful call status.

### 4.3 Error structure

The canonical error contains:

- stable `code`;
- model-readable but non-secret `message`;
- `retryable` boolean;
- `retry_action`;
- optional bounded diagnostic facts;
- optional safe target field names;
- no raw credential, protected policy, stack trace, or unbounded command output.

The initial `retry_action` vocabulary is:

- `none`;
- `same_request`;
- `new_request`;
- `query_status`;
- `reconcile`;
- `owner_intervention`;
- `local_recovery`.

## 5. Canonical Evidence

Every Tool structured result contains a minimum evidence summary with:

- evidence identity and timestamp;
- server build version and digest;
- enrolled device identity and profile version;
- controller identity digest;
- Tool and operation-contract version;
- local policy version and decision;
- observation freshness;
- effect knowledge;
- optional operation identity;
- optional audit reference;
- optional source-data and destination digests allowed by the information contract.

Evidence is not an authority grant. It is factual support for ChatGPT and owner assessment.

Sensitive values are represented only by safe identifiers or digests. The schema does not permit reusable credentials or protected control-plane payloads.

## 6. Operation Lifecycle

### 6.1 Complete state vocabulary

The canonical states are:

| State | Meaning |
| --- | --- |
| `received` | Durable operation identity exists; no admission or effect is implied |
| `rejected` | Admission failed before any consequential effect |
| `authorised` | Local admission passed; no consequential boundary has begun |
| `running` | The operation is executing |
| `paused` | Progress stopped at a declared boundary and may resume under the same lifecycle when allowed |
| `cancelling` | Cancellation is being applied |
| `cancelled` | Cancellation result and remaining effects are verified |
| `succeeded` | Local success condition and effects are verified |
| `failed` | Known non-success and remaining effects are verified |
| `uncertain` | Effect or outcome cannot yet be established; new forward effects and automatic repetition are prohibited |

An authenticated schema-valid mutating request may reach `received` before policy admission because the durable idempotency record and operation identity are created pre-effect. Transport/authentication/schema failures create no operation.

### 6.2 Terminality

The schema uses `terminality` rather than one ambiguous boolean:

| Value | States |
| --- | --- |
| `non_terminal` | `received`, `authorised`, `running`, `paused`, `cancelling` |
| `effect_terminal_reconcilable` | `uncertain` |
| `terminal` | `rejected`, `cancelled`, `succeeded`, `failed` |

`uncertain` permits only observation, reconciliation, cleanup, or retained protective behavior. It cannot create or repeat a forward effect. Reconciliation may move it to `succeeded`, `failed`, or `cancelled` without replaying the effect.

### 6.3 Effect knowledge

`effect_knowledge` is exactly one of:

- `none` — no effect boundary was crossed;
- `known_no_effect` — verified that the attempted lifecycle produced no consequential effect;
- `known_effect` — effects and remainder are known;
- `partial` — some effects are known and bounded, but requested completion was not reached;
- `uncertain` — material effect or outcome cannot be established.

State and effect knowledge must be consistent under the lifecycle specification.

### 6.4 State version and ordering

Each operation snapshot includes a monotonically increasing `state_version`. A later snapshot with a lower or equal state version cannot overwrite newer local state.

Timestamps are recorded for:

- creation;
- latest update;
- admission where applicable;
- start where applicable;
- pause/cancellation where applicable;
- terminal or reconciliation event where applicable.

The lifecycle spec defines which timestamps are required or forbidden by state.

### 6.5 Retry, cancellation, verification, and retention

The operation schema includes explicit subobjects for:

- idempotency and retry;
- cancellation request and outcome;
- verification status and evidence references;
- result/status/tombstone retention;
- progress where the contract defines measurable progress;
- error where appropriate.

A cancellation request does not make the state `cancelled`. Verification of the contract's cancellation result is required.

## 7. Allowed State Transitions

The normative transition graph is in `spec/operation/lifecycle.yaml`.

At a high level:

```text
received → rejected | authorised

authorised → running | cancelling | cancelled | failed | uncertain

running → paused | cancelling | succeeded | failed | uncertain

paused → running | cancelling | failed | uncertain

cancelling → cancelled | succeeded | failed | uncertain

uncertain → succeeded | failed | cancelled
```

Terminal states have no outgoing lifecycle transition. A new attempt receives a new operation and idempotency identity.

A direct transition is valid only when its narrower operation contract permits it. For example, an operation may move from `authorised` to `cancelled` only when cancellation before the first effect is verified.

## 8. Bootstrap Input Schemas

### 8.1 Closed objects

Every bootstrap input is a closed object. Unknown arguments are rejected.

A Tool with no arguments uses:

```json
{
  "type": "object",
  "additionalProperties": false
}
```

### 8.2 Correlated constraints

The input schemas encode relationships that prose alone cannot enforce.

Examples:

- `probe_error.delay_ms` is required only when `case` is `bounded_delay` and forbidden otherwise;
- `probe_workspace_write` requires exactly one of `text` and `base64` content;
- write and cleanup execution require the prepared-operation and execution-nonce fields;
- cleanup requires exactly one of a non-empty artifact ID list or `all_owned: true`;
- arrays have unique items and explicit maximum size;
- relative paths reject absolute, empty, NUL-containing, and traversal forms;
- values have explicit string, byte, enum, and numeric limits.

Schema validation occurs before an idempotency or operation record is created.

## 9. Bootstrap Output Schemas

The output registry contains exact success/error unions for:

- `binnacle_probe`;
- `system_inspect`;
- `probe_result_formats`;
- `probe_error`;
- `compatibility_report`;
- `probe_workspace_write`;
- `probe_workspace_cleanup`.

Each union accepts:

- the Tool-specific success envelope; or
- the canonical execution-error envelope.

The write and cleanup success schemas require an operation snapshot because mutating operations use durable idempotency and lifecycle state even when they complete quickly.

## 10. Schema Validation Boundary

### 10.1 Inputs

Input validation is performed on the exact received arguments before normalization and again on the canonical normalized representation where the contract defines a normalized schema.

Invalid schema produces a Tool input/protocol error under the selected MCP revision and creates no Binnacle operation.

### 10.2 Outputs

Before serialization, Binnacle validates `structuredContent` against the Tool's exact declared output schema.

On output-schema failure:

- do not emit malformed success;
- record a server conformance failure;
- return the safest revision-valid server or Tool error permitted by the selected profile without exposing invalid protected content;
- block promotion and trigger alert/recovery according to the profile.

### 10.3 Schema versioning

A schema change is a Tool metadata and contract change. It requires:

- schema-registry version update;
- Tool manifest digest update;
- compatibility regression;
- semantic version or Tool identity change where breaking;
- retained operation results to continue using the schema version under which they were admitted.

## 11. Validation Fixtures

The fixture matrix must validate:

- every positive bootstrap input and output;
- unknown fields;
- missing required fields;
- invalid enum, type, format, range, length, and pattern;
- correlated and mutually exclusive fields;
- result success/error union;
- output data fields and closure;
- status lookup with failed/cancelled/uncertain operation and `isError: false`;
- execution error and `isError: true`;
- every allowed and forbidden lifecycle transition;
- state/timestamp/terminality/effect-knowledge consistency;
- retry, cancellation, verification, and retention consistency;
- schema digest and Tool-manifest binding.

The fixtures are machine-readable and must be executed against the actual JSON Schema validator selected by architecture.

## 12. Compatibility Across MCP Revisions

The canonical Binnacle structured data is revision-independent. The MCP adapter wraps it in the selected revision's valid Tool result shape.

For `2026-07-28`:

- the final wire result includes `resultType: "complete"`;
- success maps to `isError: false` or omission where valid;
- execution error maps to `isError: true`;
- model-readable `content` is non-empty;
- `structuredContent` validates against the declared output schema.

Legacy adapters must not emit target-era-only wire fields, but they preserve the same structured result semantics where that revision supports structured content.

## 13. Source of Truth

The precedence for data shape is:

1. canonical JSON Schema file and `$defs` identity;
2. lifecycle transition specification;
3. Tool manifest binding and digest;
4. this explanatory document;
5. examples elsewhere.

A conflicting example does not change the schema.