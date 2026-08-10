# Binnacle Audit and Evidence Contract

- **Status:** Draft security contract
- **Contract version:** `1.1.0`
- **Event schema:** `schemas/audit/audit-event.schema.json`
- **Policy:** `spec/audit/audit-policy.yaml`
- **Feature-design basis:** [`design.md`](design.md), V17

## 1. Purpose

Audit records are append-only security evidence, not ordinary application logs and not the same object as model-visible Tool evidence.

The contract supports reconstruction of request, authentication, policy, operation, effect, retry, cancellation, recovery, result, metadata, and audit-integrity events without storing credentials or unbounded payloads.

## 2. Event Type

Version `1.1` uses `payload.kind` as the single authoritative event-type discriminator. The redundant top-level `event_type` field is removed so an event cannot claim one type while carrying another payload family.

Each payload branch is closed and schema-valid for its declared kind.

## 3. Canonical Bytes and Hash Chain

Event hashes use:

- UTF-8;
- RFC 8785 JSON Canonicalization Scheme (JCS);
- I-JSON-compatible values;
- no NaN, infinity, negative zero ambiguity, duplicate object names, or invalid Unicode;
- SHA-256 over the canonical event with `event_hash` omitted;
- `previous_event_hash` binding the preceding event in the same stream/epoch.

The exact algorithm identifier is `rfc8785-jcs+sha256-v1`.

Segments and audit epochs record first/last sequence, event count, byte count, previous segment/epoch digest, and final digest.

## 4. Checkpoints and Non-Equivocation

A local hash chain detects corruption, deletion, insertion, reordering, truncation, and many partial-tampering cases while the trusted anchor remains intact. It does not remain independently trustworthy after full-host compromise if the attacker can rewrite both events and local keys.

Stronger history claims require a checkpoint outside the compromised boundary. An accepted external checkpoint contract must provide:

- audit epoch and sequence range;
- checkpoint digest;
- previous accepted checkpoint digest;
- issuer identity and signature/receipt;
- issuance time and monotonic ordering evidence;
- non-equivocation detection for two different digests claiming the same stream/range;
- missing-checkpoint and fork handling.

Binnacle must reject or flag conflicting checkpoints. A valid signature on two different histories is not accepted as two valid histories.

## 5. Required Correlation

Events correlate, where applicable:

- controller identity digest;
- request and operation identity;
- idempotency-key digest and prepared-operation identity;
- Tool/contract, manifest, schema, policy, profile, and build digests;
- effect target and actual destination digests;
- result/evidence digests;
- cancellation, cleanup, reconciliation, and recovery identities.

Raw credentials, raw idempotency keys, bearer tokens, cookies, private keys, and protected authority material are never recorded.

## 6. Safe Facts and Size Bounds

`safe_facts` contains typed, redacted facts only. Each string is bounded; arrays have bounded item counts; the complete canonical event has a policy byte ceiling.

Untrusted prompt, repository, command, package, or peripheral content is not copied into audit. If explicitly required by a separate information contract, Binnacle records a bounded digest/reference and marks the source untrusted and non-authoritative.

Redaction occurs before persistence and before hash calculation. Hashing a secret and then persisting the secret elsewhere in the event is not compliant.

## 7. Tool Evidence

The canonical MCP evidence schema records:

- source and provenance;
- information class;
- freshness;
- optional result digest;
- operation/audit references;
- bounded typed facts.

Tool evidence is a projection for the permitted result surface. The append-only audit event remains the authoritative local security record.

## 8. Retention, Access, and Export

Retention classes are policy-defined. Export:

- requires authenticated controller/local-owner policy;
- preserves canonical bytes and segment/checkpoint evidence;
- applies information-class and redaction rules;
- records the export event and digest;
- never turns restricted audit payload into ordinary model context.

Support bundles are separately bounded projections, not raw audit-directory copies.

## 9. Audit Storage Failure

When required audit durability or integrity is unavailable:

- new consequential operations fail restricted;
- read-only recovery/status may continue within reserved capacity;
- an emergency journal records the failure if that journal remains trustworthy;
- Binnacle does not silently fall back to unaudited execution;
- restoration requires verification of the surviving chain and explicit recovery evidence.

## 10. Tests

Required tests cover:

- bit changes, insertion, deletion, reorder, truncation, duplicate sequence, and fork;
- restart, segment rotation, and audit-epoch transition;
- RFC 8785 canonicalization edge cases;
- payload-kind/schema mismatch;
- bounded safe-fact strings and maximum event bytes;
- secret and authority-material redaction before persistence;
- local checkpoint mismatch, off-device receipt mismatch, equivocation, and missing continuity;
- export, retention, disk-full, fsync, read-only storage, and emergency-journal exhaustion;
- fail-restricted behavior under audit failure.

## 11. Invariants

1. `payload.kind` is the only event-type discriminator.
2. Canonicalization is RFC 8785 JCS, not an implementation-dependent “sorted JSON”.
3. Redaction happens before persistence and hashing.
4. Safe facts and total event bytes are bounded.
5. Local hash chains do not overclaim trust after full-host compromise.
6. External checkpoint acceptance includes continuity and non-equivocation checks.
7. Required audit failure blocks new consequential work.
