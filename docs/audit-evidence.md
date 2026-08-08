# Binnacle Audit and Evidence Contract

- **Status:** Draft — mandatory security and support contract
- **Related contracts:** `OP-LIFECYCLE`, `OP-BOUNDARY`, `INFO-BOUNDARY`, `TRUST-CTRL`, `LOCAL-POLICY`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Canonical Tool schemas:** [`mcp-schemas.md`](mcp-schemas.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines Binnacle's append-only audit event stream and its relationship to Tool evidence, operation state, security decisions, recovery, support, and export.

Ordinary application logs are not authoritative audit. A Tool result is not the complete audit history. The authoritative local record is a typed, durably ordered, integrity-linked event stream produced by Binnacle's protected control plane.

The audit contract must support these questions without relying on ChatGPT memory:

- Which authenticated controller made which request?
- Which MCP, Tool, contract, policy, profile, build, and manifest versions applied?
- What was accepted or rejected, and why?
- What effect was intended, started, observed, cancelled, reconciled, or left uncertain?
- Which retry or duplicate mapped to the same operation?
- Which local and external destinations were actually reached?
- What evidence supported the current state?
- Is the retained record complete and integrity-consistent for the claimed interval?

## 2. Integrity Claim and Limit

### 2.1 Mandatory local tamper evidence

Audit events are organized into append-only segments. Every event has:

- a monotonically increasing segment sequence;
- the previous event hash;
- a canonical event hash;
- segment, boot, device, build, and audit-epoch identity.

Segment headers bind the previous sealed segment. Segment trailers bind the final event hash, event count, byte count, time range, and integrity status.

Deletion, insertion, modification, reordering, truncation, or cross-segment substitution is detectable when verification begins from a trusted retained anchor.

### 2.2 Honest limitation

A hash chain stored only on the same fully compromised Raspberry Pi does not prevent an attacker with the highest local privilege from rewriting the events and recomputing hashes.

Therefore Binnacle makes two separate claims:

1. **Local chain integrity:** detects corruption, accidental loss, partial tampering, and changes that do not also replace the trusted anchor or verifier.
2. **Anchored integrity:** detects local history replacement after a checkpoint was exported to an independently controlled sink or signed by a separately protected key/profile.

A supported profile must state which claim it provides. It must not call a local self-hashed log independently tamper-proof.

## 3. Audit Stream and Epochs

### 3.1 Audit epoch

An audit epoch identifies one continuous integrity lineage under one audit configuration and anchor root.

A new epoch is required after:

- first installation;
- loss or reset of audit integrity state;
- owner-authorized audit-key or anchoring change;
- device re-enrolment or equivalent trust reset;
- restore from backup when continuity cannot be proved;
- recovery from suspected highest-boundary compromise.

An epoch transition records the prior epoch disposition and cannot claim continuity when continuity is unverified.

### 3.2 Segment lifecycle

A segment moves through:

```text
open → sealing → sealed
             ↘ failed
```

Only the active segment accepts new events. A sealed segment is immutable to Binnacle. Rotation occurs before configured byte, event, or time limits are exceeded.

The next segment binds the previous segment trailer hash. The first segment binds the audit-epoch anchor.

### 3.3 Durable ordering

Before a consequential state or effect becomes locally committed, the required audit event or durable event intent is persisted according to the operation contract.

The implementation must provide one reconstructable order among:

- authenticated request receipt;
- operation/idempotency creation;
- policy and state decision;
- consequential-boundary intent;
- effect dispatch or local commit;
- effect observation;
- operation state transition;
- result publication;
- cancellation, reconciliation, cleanup, and recovery.

Audit ordering does not replace the authoritative operation state store. The two records cross-reference each other and divergence is a security failure.

## 4. Event Envelope

Every event conforms to `schemas/audit/audit-event.schema.json` and contains:

- schema, event, stream, epoch, segment, and sequence identities;
- wall-clock and monotonic ordering evidence;
- device, boot, build, manifest, profile, and policy identities;
- event type and severity;
- authenticated controller digest or explicit system/local source;
- request, MCP revision, Tool, operation, idempotency, preparation, and correlation identities where applicable;
- information class and provenance;
- typed event payload;
- previous-event and current-event hashes;
- optional checkpoint and export references;
- no reusable secret.

The event schema is closed. Event-specific payloads are closed and identified by a payload `kind` matching the event type family.

## 5. Event Families

### 5.1 Request and authentication

Events include:

- `request.received`;
- `authentication.succeeded`;
- `authentication.failed`;
- `authorization.scope_denied`;
- `protocol.rejected`;
- `request.rate_limited`.

Authentication failures record safe issuer/audience/controller-profile facts or digests but never tokens, assertions, cookies, authorization headers, or private keys.

### 5.2 Discovery and metadata

Events include:

- `catalogue.served`;
- `catalogue.integrity_failed`;
- `manifest.verified`;
- `manifest.rejected`;
- `compatibility.probe_recorded`.

They bind build, manifest, visible-catalogue, schema-registry, and host-profile versions and digests.

### 5.3 Policy and admission

Events include:

- `policy.decision`;
- `operation.reserved`;
- `operation.rejected`;
- `operation.authorised`;
- `resource.reserved`;
- `resource.rejected`.

Policy records identify the rule and version that determined the result. They do not expose protected policy source beyond the configured audit class.

### 5.4 Operation lifecycle

Events include:

- `operation.state_changed`;
- `operation.progress`;
- `operation.retry_reconciled`;
- `operation.idempotency_conflict`;
- `operation.result_published`;
- `operation.retention_changed`.

Every lifecycle event carries `operation_id`, old and new state when applicable, state version, effect knowledge, and evidence references.

### 5.5 Effects and destinations

Events include:

- `effect.intent_recorded`;
- `effect.started`;
- `effect.observed`;
- `effect.failed`;
- `effect.uncertain`;
- `destination.resolved`;
- `destination.connected`;
- `destination.redirected`;
- `credential.used_non_exportably`.

Effect events record normalized target and payload digests, actual destination transitions, counts/bytes, credential audience reference, and uncertainty. They do not record never-disclosable payloads.

### 5.6 Cancellation, cleanup, and recovery

Events include:

- `cancellation.requested`;
- `cancellation.phase_changed`;
- `cancellation.verified`;
- `cleanup.started`;
- `cleanup.verified`;
- `cleanup.failed`;
- `reconciliation.started`;
- `reconciliation.completed`;
- `recovery.required`;
- `recovery.completed`.

A cancellation request and a verified cancelled result remain separate events.

### 5.7 Audit integrity

Events and segment records include:

- `audit.segment_opened`;
- `audit.segment_sealed`;
- `audit.checkpoint_created`;
- `audit.checkpoint_exported`;
- `audit.verification_passed`;
- `audit.verification_failed`;
- `audit.storage_degraded`;
- `audit.retention_applied`.

An audit-integrity failure cannot be hidden inside ordinary logging.

## 6. Event Hashing and Canonicalization

### 6.1 Canonical event

The canonical event for hashing:

- uses UTF-8 JSON;
- follows the canonicalization version in the audit policy;
- excludes only `event_hash` and external signature/receipt fields;
- includes `previous_event_hash`;
- includes the exact typed payload and every security-relevant identity;
- uses deterministic object-key ordering and semantic array order;
- rejects non-JSON numbers, duplicate keys, invalid Unicode, and unknown fields.

The initial hash algorithm is SHA-256.

```text
event_hash = SHA-256(canonical_event_without_event_hash)
```

A later algorithm requires a new audit-policy version and epoch or an explicitly verified migration record.

### 6.2 Segment hash

The segment trailer hash binds:

- epoch and segment identity;
- previous-segment trailer hash;
- first and final event hashes;
- event count;
- canonical byte count;
- first and final sequence and timestamps;
- build and audit-policy version;
- close reason.

### 6.3 Optional authentication

A profile may authenticate checkpoints with:

- a key in a separately protected local security boundary;
- a hardware-backed key;
- an off-device owner-controlled signing service;
- a transparency or append-only external receipt.

The profile records the trust and compromise boundary. A signature made with an ordinary key stored beside writable audit data does not establish independent history integrity.

## 7. Evidence Semantics

### 7.1 Canonical evidence

Tool evidence is a bounded projection of authoritative local facts and audit references. It contains:

- evidence identity and recorded time;
- source event or operation references;
- provenance class;
- observation time and freshness bound;
- information class;
- build, Tool, contract, policy, device, and controller digests;
- effect knowledge and result digest;
- source/destination digests where permitted;
- integrity status and audit anchor reference;
- uncertainty and limitations.

Evidence cannot claim a fact not established by its source events.

### 7.2 Freshness

Every observation states:

- `observed_at`;
- `max_age_ms`;
- whether it was current at the decision boundary;
- source and collection method;
- any later-known conflict.

A later export does not make an old observation fresh.

### 7.3 Host prompt and context

Binnacle records host prompt or context only when the host explicitly supplies it under a declared information contract.

Such material is:

- optional;
- `local-untrusted` or `model-supplied-unknown` provenance;
- non-authoritative for owner intent, approval, policy, or operation meaning;
- length-limited and redacted by contract;
- preferably represented by digest and bounded excerpt rather than complete conversation;
- never required for operation reconstruction.

Binnacle must not silently collect full ChatGPT conversations.

## 8. Secrets, Redaction, and Information Classes

### 8.1 Never logged

Audit must never contain:

- access, refresh, session, or downstream tokens;
- authorization headers, cookies, or gateway assertions;
- private keys, passwords, raw credential values, or credential-helper data;
- raw grant/proof material or protected control-plane references;
- raw idempotency keys when a digest suffices;
- never-disclosable Tool input or output payload;
- unbounded stdout, stderr, file, repository, prompt, or network payload;
- raw environment or descriptor contents.

### 8.2 Safe identifiers and digests

The audit may record:

- controller and credential reference digests;
- normalized target identities;
- file, patch, command, request, response, payload, and result digests;
- bounded counts, sizes, classifications, and selected safe fields;
- redaction rule and version;
- destination and credential audience identifiers.

A digest of a low-entropy secret may still leak information. Never-disclosable values are not hashed into ordinary audit unless a separate keyed or protected verification contract proves safety.

### 8.3 Redaction

Redaction occurs before canonical event hashing and persistence. The event records:

- redaction policy/version;
- fields removed, transformed, or retained by category;
- whether truncation occurred;
- original byte/item counts where safe;
- result classification.

Post-hoc display redaction does not make an unsafe stored event acceptable.

## 9. Retention and Rotation

The device profile defines retention by event class.

Initial minimums:

| Class | Examples | Minimum local retention |
| --- | --- | ---: |
| `AR1-bootstrap` | Compatibility probes and catalogue evidence | 30 days |
| `AR2-normal` | Read-only and bounded local operation history | 90 days |
| `AR3-consequential` | Mutation, command, service, credential, egress, self-management | 365 days |
| `AR4-uncertain-security` | Uncertain effect, integrity failure, compromise, recovery | Until owner-resolved plus 365 days |

Idempotency and operation records may require longer retention; the longest applicable rule governs.

Rotation and compaction must preserve:

- event/segment integrity lineage;
- required event fields;
- unresolved operation and uncertainty references;
- idempotency tombstones;
- security and recovery evidence;
- exported checkpoint references.

Deleting an expired segment records a retention event in a later retained segment and must not break verification of retained history.

## 10. Access and Export

### 10.1 Access

Remote audit access is not implicit in general Tool authorization. It requires a dedicated read-only contract and information policy.

Access is:

- controller-authenticated;
- scoped by device, event class, time, operation, and information class;
- paginated and size-bounded;
- recorded in audit;
- unable to return never-disclosable payload;
- unable to modify or delete events.

Local break-glass access follows owner governance and must preserve original files read-only where practical.

### 10.2 Export bundle

An export bundle contains:

- manifest with device, audit epoch, segment range, policy, schema, and export versions;
- canonical sealed segment data or a contract-defined redacted projection;
- segment and checkpoint hashes;
- external receipts/signatures where available;
- file digests and byte counts;
- verification instructions and expected result;
- exclusions and redactions;
- no reusable secret.

The export itself is audited. Exporting a redacted projection does not replace retention of the authoritative local chain.

### 10.3 Support bundle

A support bundle is narrower than full audit export. It contains only events and evidence needed for the selected incident or operation, with the minimum permitted information. It records the support-bundle policy and digest.

## 11. Storage Failure and Restricted Operation

Audit is part of Binnacle's protected control plane.

When Binnacle cannot durably append or verify the required event:

- no new consequential operation is admitted;
- no new effect crosses a boundary whose intent or result cannot be recorded;
- affected work pauses, stops, fails, or becomes uncertain according to its contract;
- read-only diagnostic and audit-recovery functions remain only when their own required audit can be preserved or a declared emergency ring is available;
- reserved status, cancellation, safe-stop, and recovery capacity is preserved;
- the owner receives a bounded `audit_unavailable` or `audit_integrity_failed` result;
- the server must not silently continue with ordinary text logs only.

An operation already inside an effect may perform its retained protective result even when ordinary audit storage fails. The server records the emergency event in a separately reserved emergency journal or, if even that is impossible, marks the result unobservable/uncertain and requires local recovery.

Storage pressure must not evict unresolved security, operation, idempotency, or uncertainty records to admit new work.

## 12. Verification

Verification can operate on:

- the active segment;
- one sealed segment;
- a contiguous segment range;
- one export bundle;
- the complete retained audit epoch.

It validates:

- schemas and canonicalization;
- sequence continuity;
- previous-event and previous-segment hashes;
- event and segment hashes;
- timestamps and monotonic ordering evidence;
- build/policy/manifest/schema identities;
- checkpoint signature or external receipt where claimed;
- retention and deletion records;
- cross-references to operation and idempotency state;
- unexpected truncation, duplicate event IDs, or forked history.

A failed verification creates a new integrity event only in a still-trusted current journal and moves affected remote operation into restricted state. It does not repair history automatically.

## 13. Schemas and Tests

The canonical files are:

```text
schemas/audit/audit-event.schema.json
spec/audit/audit-policy.yaml
tests/fixtures/audit/audit-integrity.yaml
```

Required tests include:

- valid event and segment chains;
- bit modification, insertion, deletion, reordering, duplication, truncation, and fork;
- restart and segment rotation;
- wrong epoch, device, build, manifest, or policy identity;
- missing required event correlation;
- request, auth, policy, operation, effect, retry, cancellation, recovery, and result events;
- redaction before persistence;
- secret and low-entropy digest leakage;
- prompt/context classification and truncation;
- retention and deletion records;
- export and support bundle verification;
- off-device checkpoint mismatch;
- disk full, read-only storage, fsync failure, and emergency-journal exhaustion;
- fail-restricted and retained protective behavior.

## 14. Source of Truth

The precedence is:

1. audit-event schema;
2. audit-policy specification;
3. this contract;
4. examples in other documents.

A Tool result or application log cannot override an authoritative audit event or operation-state record.