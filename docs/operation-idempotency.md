# Binnacle Durable Idempotency and Retry Reconciliation

- **Status:** Draft — mandatory reliability contract for mutating operations
- **Related contracts:** `OP-PREPARE`, `OP-LIFECYCLE`, `OP-BOUNDARY`, `MCP-INTERFACE`, `TRUST-CTRL`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Host confirmation:** [`mcp-host-confirmation.md`](mcp-host-confirmation.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines how Binnacle prevents duplicate consequential effects when an initiating response is lost, a client retries, a connection is replaced, Binnacle restarts, or several identical requests arrive concurrently.

A server-minted `operation_id` returned only after the request is admitted is not enough: the caller may not receive it. Every mutating or otherwise non-repeatable Tool must therefore carry a stable pre-effect idempotency identity known before the first consequential boundary.

The governing rule is:

> One authenticated controller, Tool contract, idempotency identity, and canonical effect-bearing input fingerprint map to at most one Binnacle operation and at most one admitted effect lifecycle.

## 2. Idempotency Identity Sources

Every contract declares one of these modes:

| Mode | Source | Use |
| --- | --- | --- |
| `none` | No key | Strictly read-only or otherwise safely repeatable operations with no retained effect |
| `caller-key` | Caller supplies `idempotency_key` before admission | Mutating operation without a prepared-operation flow |
| `prepared-nonce` | Binnacle returns `execution_nonce` during no-effect preparation; caller echoes it during execution | Preferred for HC1 consequential operations |
| `derived-member-key` | Deterministically derived from a future envelope/member identity and caller key | Deferred until envelope support is promoted |

A mutating operation that declares `caller-key` or `prepared-nonce` rejects execution when the required identity is absent.

### 2.1 Caller key format

The initial profile requires:

- UTF-8 ASCII subset: letters, digits, hyphen, underscore, colon, and dot;
- 16–128 characters;
- at least 128 bits of unpredictability for generated keys;
- no embedded owner data, path, secret, access token, or semantic instruction;
- opaque treatment by Binnacle.

UUIDv4 or another cryptographically strong 128-bit value is acceptable. A short counter, timestamp alone, repeated natural-language label, or model-generated phrase is not acceptable for a consequential operation.

### 2.2 Prepared execution nonce

A prepared operation returns an opaque `execution_nonce` before effect. It is:

- bound to the preparation and controller;
- single operation or contract-defined idempotent reconciliation only;
- independently non-authoritative;
- not proof of owner confirmation;
- model-visible only where the interface requires the caller to echo it;
- never reused for a changed preparation.

The caller must retain it before sending the execution request.

## 3. Idempotency Scope and Fingerprint

### 3.1 Scope key

The authoritative lookup scope is:

```text
Binnacle device identity
controller identity and epoch
Tool semantic identity
operation-contract version
idempotency identity
```

The stored key may be a keyed digest rather than the raw caller value. Audit and result payloads use only a safe digest or suffix.

A matching string under another controller, device, or Tool contract is not the same idempotency record and must not disclose the existing operation.

### 3.2 Canonical request fingerprint

The fingerprint binds every field capable of changing the effect, including:

- Tool and operation-contract version;
- normalized targets and arguments;
- prepared-operation identity and preparation digest where applicable;
- executable, arguments, working directory, and execution profile;
- file content or patch digest;
- information source references, transformations, recipients, and destinations;
- credential-broker identity and audience;
- hardware targets and effect values;
- caller-selected limits when they affect behavior;
- external idempotency semantics;
- any contract-defined effect-bearing option.

The fingerprint excludes mutable server observations such as current policy version and current state. Those are retained separately as admission and boundary evidence. This allows a retry to locate the existing operation after policy or state changes without creating a new effect.

The normalization algorithm and version are part of the Tool contract. An unrecognized normalization version blocks admission.

### 3.3 Same key, same fingerprint

A retry with the same scope key and same fingerprint returns or advances only the retained operation lifecycle permitted by its contract. It does not create a second operation or repeat an effect.

### 3.4 Same key, different fingerprint

Reuse with a different fingerprint returns `idempotency_conflict` before effect. The response identifies the conflicting Tool/contract and safe fingerprint digests without disclosing another controller's arguments.

A conflict cannot be resolved by choosing the latest request. The caller must inspect the retained operation and use a new key for a genuinely new operation.

## 4. Durable Pre-Effect Record

### 4.1 Atomic creation

After transport authentication and schema validation, and before any local-policy admission or consequential effect, Binnacle atomically creates or finds an idempotency record containing:

- scope-key digest;
- idempotency mode and safe key digest;
- canonical request fingerprint and normalization version;
- server-minted `operation_id`;
- controller and device identity/epoch;
- Tool and contract version;
- prepared-operation identity where applicable;
- record state;
- creation and retention timestamps.

The record must be durable before the server returns authorization, starts an executor, writes a file, changes a service, sends a network request, or performs any other consequential effect.

If Binnacle cannot persist and verify the record, the operation is rejected as `idempotency_unavailable`. It must not continue in memory-only mode.

### 4.2 Record states

| State | Meaning |
| --- | --- |
| `reserved` | Scope key, fingerprint, and operation ID are durably bound; no policy admission or effect is implied |
| `rejected` | The authenticated schema-valid request was rejected before effect; the same key returns the retained rejection |
| `authorised` | Local admission passed; no consequential boundary has begun |
| `running` | One operation lifecycle is executing |
| `paused` | The one lifecycle is stopped at a declared boundary |
| `cancelling` | Cancellation is being applied to the same lifecycle |
| `cancelled` | Cancellation and remaining effects are verified |
| `succeeded` | Success and effects are verified |
| `failed` | Known non-success and remaining effects are verified |
| `uncertain` | Effect or outcome cannot be established; repetition is prohibited |

The idempotency record references the authoritative `OP-LIFECYCLE` record rather than maintaining a competing operation state.

### 4.3 Durable ordering around effects

Before each non-idempotent consequential boundary, Binnacle records a boundary intent and commits the operation state required by the contract. After the effect, it records the observed result or uncertainty.

The implementation must provide one durable ordering for:

- idempotency record creation;
- operation admission;
- boundary intent;
- local effect or external dispatch;
- effect evidence;
- terminal or uncertain state.

A crash between steps must produce a reconstructable state. It must not cause automatic replay merely because a completion marker is absent.

## 5. Retry Behavior

### 5.1 Lost initial response before admission

If the response is lost after the record is reserved but before admission, the same-key retry returns the same `operation_id` and continues or reports the retained admission result according to the contract.

It does not allocate a new operation.

### 5.2 Lost response after effect

If an effect may already have occurred, the same-key retry returns the retained lifecycle or starts deterministic reconciliation. It never dispatches the effect again solely because the client did not receive the first response.

### 5.3 Concurrent duplicate requests

Concurrent requests for the same scope key and fingerprint race on one atomic record creation. Exactly one creates the operation. All others receive the same operation identity and current lifecycle or a bounded in-progress response.

They must not each reserve resources, start executors, or send external requests.

### 5.4 In-progress retry

A same-key retry while the operation is `authorised`, `running`, `paused`, or `cancelling` returns current state and status-retrieval guidance. It does not become another supervisor or cancellation request.

### 5.5 Terminal retry

A same-key retry after `succeeded`, `failed`, or `cancelled` returns the retained terminal result or a result reference. It does not re-execute.

A caller wanting another attempt uses a new idempotency key and, where required, a fresh preparation and host confirmation.

### 5.6 Uncertain retry

A same-key retry after `uncertain` returns the uncertainty and reconciliation requirements. It never automatically creates or repeats an effect.

A new key also cannot repeat the same target effect until the operation contract's reconciliation or owner-intervention condition permits it.

## 6. External Effects

Local idempotency prevents duplicate Binnacle dispatch. It does not by itself guarantee that a remote system applied an effect exactly once.

A dedicated external operation must declare one of:

- remote API supports an idempotency key, transaction ID, conditional update, or exact request deduplication;
- remote effect is safely idempotent under a verified current-state predicate;
- remote system provides a reconciliation query;
- duplicate effect is impossible through another protected design;
- outcome may be uncertain and automatic retry is prohibited.

Where supported, Binnacle derives or binds a downstream idempotency identity to:

- Binnacle `operation_id`;
- caller idempotency identity;
- exact remote target and operation;
- payload digest;
- remote contract version.

The inbound MCP credential is never reused as downstream idempotency or authorization material.

## 7. Ownership, Reconnect, and Controller Change

### 7.1 Reconnect

A new transport connection or ChatGPT conversation under the same authenticated active controller may retry with the same idempotency identity and retrieve the same operation.

Transport connection, MCP session, and interaction context are not part of the operation ownership identity.

### 7.2 Other controller

Another controller cannot inspect or advance the retained operation by presenting the same key. The server returns an authentication-safe result such as not found or unauthorized without revealing whether the key exists.

### 7.3 Controller replacement

Personal V1 does not transfer operation ownership automatically during controller replacement.

Existing operation and idempotency records remain retained constraints and evidence. The successor controller can access them only through a future explicit recovery/transfer contract or local owner administration. It cannot reuse the old controller's key to create a new effect.

## 8. Cancellation

Cancellation uses `operation_id`, not the idempotency key, and is authorized for the operation owner under the cancellation contract.

A cancelled operation keeps its idempotency record. Same-key retry returns `cancelled` and does not start over.

If cancellation occurs before the first effect, a new attempt still uses a new key and fresh confirmation where required. This avoids ambiguous reuse of an identity whose lifecycle already ended.

Cancellation request retries are separately idempotent under the operation and cancellation state; they cannot create another operation.

## 9. Status and Result Retrieval

Status and result Tools use `operation_id` and do not require the caller to resend the idempotency key.

They must:

- authenticate the operation owner;
- avoid disclosing existence to another controller;
- be read-only;
- remain available under reserved control-plane capacity;
- apply per-controller and global rate limits;
- return polling/backoff guidance where useful;
- never advance or repeat the underlying effect;
- preserve the original Tool, contract, key digest, and fingerprint evidence.

Aggressive polling may be rate-limited without cancelling or duplicating the operation.

## 10. Retention and Reuse

### 10.1 Non-terminal records

A non-terminal or uncertain idempotency record must not expire automatically while its operation can still have effects, require cleanup, or block conflicting work.

### 10.2 Initial retention classes

| Class | Example | Full record minimum after terminal state | Key tombstone minimum |
| --- | --- | ---: | ---: |
| `IR1-local-reversible` | Controlled workspace probe or bounded local edit | 7 days | 30 days |
| `IR2-destructive-or-self-management` | Delete, service change, Binnacle update | 30 days | 365 days or device epoch reset, whichever is later |
| `IR3-external-or-uncertain` | Remote write or unresolved external effect | Until reconciled, then 30 days | 365 days or target-contract longer period |

The device profile may set longer periods. It must not set shorter periods without evidence that delayed retries and remote replay are impossible.

### 10.3 Tombstone

After full result cleanup, Binnacle may retain a bounded tombstone containing:

- scope-key digest;
- fingerprint digest;
- operation ID or terminal reference;
- terminal class;
- expiry;
- no result payload or secret.

A matching replay during tombstone retention returns `idempotency_key_expired` or a terminal reference and does not create a new effect.

### 10.4 Storage pressure

Idempotency and operation records are protected control-plane state.

If Binnacle cannot retain the required record or tombstone, it blocks new affected mutating operations before effect. It must not evict a still-relevant key and permit replay.

## 11. Key Exposure and Abuse

The idempotency key is not an authorization secret, but it may reveal workflow correlation and should not be placed in descriptions, logs, metrics labels, or owner-visible prose unnecessarily.

Binnacle records a digest. It never:

- treats key possession as controller authentication;
- lets a key select another controller's operation;
- uses the key as an access token;
- forwards it as a remote credential;
- accepts a key embedded in untrusted content as owner intent;
- changes the request fingerprint to match a reused key.

## 12. Error Codes

Initial errors are:

| Code | Meaning |
| --- | --- |
| `idempotency_key_required` | The contract requires a caller key or prepared execution nonce |
| `idempotency_key_invalid` | Format, length, or profile requirements are not met |
| `idempotency_conflict` | Same scope key was already bound to another fingerprint |
| `idempotency_unavailable` | Required durable state cannot be persisted or verified |
| `idempotency_key_expired` | A retained tombstone prevents reuse after result cleanup |
| `operation_reconciliation_required` | Existing uncertain or external state must be reconciled rather than repeated |

Authentication and authorization failures remain outside this Tool error boundary where required by the transport profile.

## 13. Evidence

Every mutating operation evidence record includes:

- idempotency mode;
- safe key or nonce digest;
- scope-key digest;
- request fingerprint and normalization version;
- operation ID;
- record creation durable order;
- admission, boundary-intent, effect, and result order markers;
- duplicate and conflict counts;
- retry connection and request correlations;
- downstream idempotency identity digest where applicable;
- retention class and expiry;
- terminal or uncertain state;
- no raw idempotency key unless a protected recovery contract explicitly requires it.

## 14. Validation

The profile and test cases are:

```text
spec/operation/idempotency.yaml
tests/fixtures/operation/idempotency.yaml
```

Required tests include:

- first response dropped before admission;
- first response dropped after local effect;
- remote response dropped after dispatch;
- concurrent identical requests;
- same key/different input;
- same key/different Tool or contract;
- same key/other controller;
- restart at every durable ordering boundary;
- retry after success, failure, cancellation, and uncertainty;
- cancellation and status polling;
- tombstone reuse and storage pressure;
- downstream idempotency and non-idempotent remote uncertainty;
- exact effect count of one.

Mock tests validate state-machine logic. Filesystem, service, command, and external-effect profiles require integration and fault-injection tests at the actual durability boundary.