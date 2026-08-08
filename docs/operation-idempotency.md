# Binnacle Durable Idempotency and Retry Reconciliation

- **Status:** Draft reliability and security contract
- **Contract version:** `1.1.0`
- **Policy:** `spec/operation/idempotency.yaml`
- **Feature-design basis:** [`design.md`](design.md), V17

## 1. Purpose

A mutating request can cross a consequential boundary even when the initiating MCP response is lost. Retrying as a fresh request could repeat the effect. Binnacle therefore knows a durable idempotency identity before admission and effect.

`operation_id` remains the authoritative local work identity, but the caller must have an idempotency key or prepared execution nonce before the first effect so a lost response can be reconciled.

## 2. Identity Forms

Binnacle supports:

- **caller key** — at least 128 genuinely random bits encoded as lowercase hex or base64url;
- **prepared execution nonce** — server-generated and returned by a no-effect preparation Tool;
- **derived member key** — only for a contract that deterministically derives one member identity from a previously durable parent.

UUIDv4 is not the recommended caller-key format because it contains 122 random bits after fixed version/variant bits. A compliant 128-bit key may be 32 lowercase hex characters generated from 16 random bytes.

Keys are not authorization credentials and are never logged raw.

## 3. Durable Pre-Effect Record

Before policy admission, resource reservation, or effect, Binnacle atomically creates or finds:

- global key digest and key mode;
- controller owner identity and epoch at first creation;
- device identity and epoch;
- Tool name and contract version;
- canonical effect-bearing request fingerprint;
- operation identity and state version;
- creation, last-access, terminal, and retention times;
- conflict/duplicate counters;
- current policy/admission evidence;
- effect-knowledge and reconciliation state.

The fingerprint includes normalized effect-bearing inputs and prepared-operation identity. It excludes mutable current observations and policy results so a retry can find the original record and reconcile it rather than create a new effect.

## 4. Two-Level Lookup and Ownership

The durable index has two separate concerns:

1. **Global duplicate-prevention index** — scoped to device identity/epoch, Tool contract, and key digest. It survives controller rotation long enough to prevent the same key from creating a second effect.
2. **Operation ownership record** — identifies the controller identity/epoch allowed to read or advance the retained operation.

This separation is mandatory.

### 4.1 Same owner

Same key plus same fingerprint returns the retained operation and current lifecycle. No new effect occurs.

Same key plus different fingerprint returns `idempotency_conflict` and creates no operation.

### 4.2 Controller replacement

A successor controller cannot automatically read or advance the prior controller's operation. It also cannot reuse the prior key to create a second operation.

A matching key from another controller returns a non-disclosing `idempotency_owner_mismatch` or equivalent conflict. It reveals no retained operation details and creates no effect.

Deliberate operation recovery or ownership transfer requires a separately defined owner-governed recovery contract. It is never inferred from key possession.

## 5. Ordering

The durable order is:

```text
authenticate request
→ validate idempotency-key syntax
→ atomically create/find global key record
→ bind or verify request fingerprint and owner
→ perform policy/admission checks
→ persist admitted operation/reservations
→ cross consequential boundary
→ record effect knowledge/result
→ return response
```

A crash at any point reconstructs the retained record before another request can create an effect for the same key.

## 6. Retry Outcomes

| Condition | Result |
| --- | --- |
| Same owner, same key, same input | return retained lifecycle/result |
| Same owner, same key, different input | `idempotency_conflict` |
| Different controller, matching key | `idempotency_owner_mismatch`, no details, no effect |
| Key expired but tombstone current | reject `idempotency_key_retired` |
| Existing state `uncertain` | return uncertainty and reconciliation guidance; never auto-retry |
| Existing state terminal | return retained terminal result or result reference |
| Concurrent first requests | exactly one creates the record; all others reconcile |

## 7. Prepared Operations

A prepared execution nonce is bound to:

- prepared operation identity;
- controller and device;
- Tool/contract;
- exact normalized input digest;
- expiry and current-state conditions.

Using the nonce for another input is `prepared_operation_mismatch`. An expired nonce cannot be reused or converted into a fresh caller key.

## 8. Retention and Storage Pressure

Retention covers the maximum interval in which a duplicate request could otherwise repeat an effect, including:

- request and host retry windows;
- operation/result retention;
- reconnect and restart;
- accepted clock uncertainty;
- remote-side reconciliation where applicable.

After full records expire, bounded tombstones retain key digest, Tool contract, controller-owner digest, request fingerprint digest, terminal class, and retirement time.

If Binnacle cannot durably create or retain the pre-effect record, it rejects new mutating work. It does not proceed without idempotency protection.

## 9. Status and Abuse Controls

Status/retry calls are authenticated, owner-scoped, rate-limited, and non-disclosing. Raw keys are never metrics labels or ordinary logs. Repeated conflicts and enumeration attempts are audited and throttled.

## 10. Tests

Required cases include:

- response loss before admission, after admission, and after external effect;
- concurrent duplicate requests;
- same-key/different-input conflict;
- controller replacement and other-controller replay;
- reconnect and process restart;
- uncertain and terminal retries;
- prepared nonce mismatch/expiry;
- tombstone retention and storage pressure;
- cancellation/status polling;
- atomic external-effect counter proving one effect.

## 11. Invariants

1. Every mutating effect has a durable pre-effect identity.
2. Caller keys contain at least 128 genuinely random bits; UUIDv4 alone is insufficient.
3. Global duplicate prevention survives controller replacement.
4. Operation ownership does not transfer automatically.
5. Same key/different input never executes.
6. `uncertain` never permits automatic retry.
7. Loss of idempotency storage fails closed.
