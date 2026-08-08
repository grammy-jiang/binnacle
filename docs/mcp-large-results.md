# Binnacle Pagination, Large Results, and Retained Result Objects

- **Status:** Draft — mandatory MCP result-boundary contract
- **Related contracts:** `MCP-INTERFACE`, `MCP-PROFILE`, `INFO-BOUNDARY`, `OP-LIFECYCLE`, `OP-BOUNDARY`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Canonical schemas:** [`mcp-schemas.md`](mcp-schemas.md)
- **Evaluation contract:** [`mcp-evaluation.md`](mcp-evaluation.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines how Binnacle returns directory listings, searches, logs, command output, audit projections, compatibility evidence, and other results that may exceed one safe MCP Tool response.

The contract prevents:

- unbounded Tool responses;
- silent truncation;
- duplicate or missing items across pages;
- cursor reuse against a changed query, controller, policy, or result set;
- treating a cursor or result reference as authority;
- leaking protected data through a later page or chunk;
- assuming that Streamable HTTP provides partial Tool-result streaming;
- depending on MCP Resources or protocol-native pagination before the actual ChatGPT profile proves them.

The governing model is:

> Small results are returned inline. Large results are materialized as immutable, server-held result objects and read through bounded Tool pages or chunks.

> MCP Resources, list cursors, progress notifications, and other protocol features are optional adapters. The fundamental Binnacle interface remains usable through ordinary bounded Tools.

## 2. Three Result Delivery Modes

Every operation contract selects one result mode prospectively.

| Mode | Use | Contract |
| --- | --- | --- |
| `inline` | Result fits every applicable server and validated HOST-profile limit | One complete Tool result with explicit counts and no silent omission |
| `item-page` | Ordered collection such as directory entries, search matches, operation lists, or audit projections | Immutable snapshot plus opaque page cursor |
| `byte-chunk` | Large text, binary artifact, log snapshot, diff, command output, or export | Immutable result object plus bounded byte or record chunks |

A live stream or tail is not an implicit fourth mode. It is a separate retained operation with its own time, event, cancellation, and retention contract.

## 3. Effective Limits

### 3.1 Server and HOST limits

The effective response limit is the most restrictive current value among:

- the Binnacle build and device profile;
- the Tool or operation contract;
- the information-disclosure contract;
- current resource and storage budgets;
- the empirically validated ChatGPT HOST profile;
- the selected MCP revision and transport behavior.

Binnacle bootstrap defaults are conservative implementation limits, not claims about ChatGPT's undocumented maximums. `MCP-FEAS` may lower them. A higher observed host limit does not automatically raise the server limit.

### 3.2 Initial bootstrap limits

The initial policy defines:

- model-readable `content`: 8 KiB;
- one `structuredContent`: 64 KiB;
- complete serialized Tool result: 128 KiB;
- default page size: 100 items;
- maximum page size: 500 items;
- default chunk: 64 KiB decoded bytes;
- maximum chunk: 256 KiB decoded bytes;
- one retained result object: 32 MiB;
- one controller's retained result objects: 256 MiB;
- global retained result objects: device-profile defined, initially 1 GiB.

All values are configurable only through accepted local policy and remain subject to lower measured HOST limits.

### 3.3 No silent truncation

A result that does not fit inline must either:

- be returned through a declared page/chunk mode;
- return a retained `result_ref`;
- be rejected before result generation as `result_too_large` or `result_storage_unavailable`.

Every bounded result states:

- whether it is complete;
- returned item and byte counts;
- total counts when known;
- whether omitted counts are known;
- truncation and transformation status;
- continuation availability;
- result or snapshot identity and digest.

Binnacle must not return the first portion as if it were complete.

## 4. Retained Result Object

### 4.1 Identity and lifecycle

A retained result object has one opaque `result_ref` and one lifecycle:

```text
building → complete → expired
        ↘ failed
complete → deleted
```

Only `complete` results are readable through ordinary page or chunk Tools. A `building` result returns `result_not_ready` and status guidance. A failed result never exposes an incomplete object as complete.

A complete result is immutable. New source facts require a new result object.

### 4.2 Required bindings

The authoritative server record binds:

- result identity and schema version;
- producing operation, request, Tool, and contract version;
- authenticated controller identity and epoch;
- enrolled device and profile;
- query/filter/order/format fingerprint;
- source snapshot or collection boundary;
- information and provenance class;
- named recipient and result surface;
- media type and encoding;
- item and decoded-byte counts;
- full result digest;
- optional per-page or per-chunk digests;
- created, completed, accessed, and expiry times;
- retention class and quota charge;
- policy and disclosure versions;
- audit identity.

Possession of `result_ref` creates no authority. Every access authenticates the controller and revalidates result ownership, information policy, expiry, and operation contract.

### 4.3 Storage before reference

Binnacle persists and verifies a result object before returning a usable reference. If persistence, quota accounting, or digest verification fails, it returns an execution error and no readable reference.

It must not return a reference to process memory that disappears on reconnect when the contract promises retained access.

## 5. Item Pagination

### 5.1 Snapshot semantics

A paginated collection is derived from one immutable logical snapshot whenever the source supports it.

The snapshot binds:

- normalized query and filters;
- deterministic sort keys and tie-breaker;
- source version or collection evidence;
- information policy;
- result-set identity;
- creation and expiry;
- total count when available without unreasonable cost.

Changes to the underlying filesystem, audit stream, operation registry, or repository after snapshot creation do not rewrite earlier pages.

If a source cannot provide snapshot consistency, the contract must say `consistency: live_unstable`, provide observed boundaries and duplication/omission warnings, and must not be used where complete traversal is a security or correctness requirement. Personal V1 uses immutable snapshots for promoted pagination contracts.

### 5.2 Cursor

A page cursor is opaque and non-authoritative. It is a random server-held reference or an authenticated token that binds:

- controller and device identity;
- Tool and contract version;
- result-set and snapshot identity;
- normalized query fingerprint;
- ordering and tie-breaker;
- page size and next position;
- information class and recipient;
- expiry and policy version;
- cursor format version.

It contains no raw credential, protected payload, owner data, or unhashed query unless the contract explicitly permits that non-sensitive field.

A copied cursor cannot cross controller, device, result, Tool, contract, query, order, or recipient boundaries.

### 5.3 Stable page behavior

A valid repeated request with the same cursor returns the same page or a semantically identical page under the cursor contract. It does not advance a global mutable pointer.

A traversal must provide:

- deterministic item order;
- no duplicate logical item unless the source snapshot itself contains duplicates and the contract exposes stable unique identities;
- no omitted logical item;
- explicit end-of-results;
- `next_cursor: null` at the end;
- page and cumulative counts;
- snapshot/result digest evidence.

Changing page size, query, filter, sort, projection, or result format requires a new initial request. Those fields cannot be substituted while reusing a cursor.

## 6. Byte and Record Chunks

### 6.1 Chunk contract

A byte-chunk read binds:

- `result_ref`;
- zero-based decoded byte offset;
- requested decoded length within policy;
- media type and encoding;
- full result length and digest;
- returned offset, length, and chunk digest;
- completeness and next offset;
- UTF-8 boundary handling for text;
- binary representation for non-text content.

### 6.2 Text

Text chunks must not split an invalid UTF-8 sequence. The response states whether the returned range was adjusted to a valid boundary.

Line-oriented Tools may use record chunks instead of arbitrary bytes when each record has a stable identity and size bound.

Terminal escape sequences, control characters, and untrusted instructions remain data and follow the output-safety contract.

### 6.3 Binary

Binary content is returned through a declared binary representation, initially base64 in `structuredContent`, with decoded-byte counts and digests. Base64 expansion counts against serialized response limits.

A binary object too large for the retained-object limit is unsupported unless a separately promoted external artifact-delivery contract exists.

### 6.4 Range errors

Negative offsets, overflow, ranges beyond the object, zero or excessive length, incompatible encoding, and changed result identity are rejected. A request at exactly the result length returns an empty final chunk only when the contract explicitly permits it; otherwise it returns `range_invalid`.

## 7. MCP Resources and Protocol Pagination

### 7.1 Resources

MCP Resources may adapt a retained result object only when the actual ChatGPT profile proves:

- declaration and discovery;
- stable URI handling;
- read result size and media behavior;
- information and owner-only exclusion;
- cache and refresh behavior;
- authorization revalidation;
- error and expiry presentation.

A Resource URI is a non-authoritative reference. It does not bypass controller, result, or information policy.

When Resources are unsupported or untested, `result_get`, `result_page`, and `result_chunk` remain the canonical fallback.

### 7.2 Protocol-native list pagination

MCP list methods that support cursors use their protocol-defined cursor shape. Those cursors are distinct from Binnacle result cursors and cannot be interchanged.

Protocol-native pagination is used only for the corresponding MCP list method. It does not solve pagination of arbitrary Tool-specific content.

### 7.3 Streamable HTTP

Streamable HTTP transport does not imply that one Tool result may be sent as an unbounded partial payload while the model consumes it incrementally.

Binnacle returns a revision-valid complete Tool result or a retained result reference. Progress or logging notifications are advisory and cannot carry the authoritative final payload or alter operation state.

Closing a transport stream is not automatic deletion of a retained result or cancellation of the producing operation.

## 8. Large Result Production

### 8.1 Materialization operation

Generating a large result may be:

- part of a synchronous Tool call that persists the complete object within the call budget; or
- a retained Binnacle operation that returns an `operation_id`, then a `result_ref` after completion.

The contract declares CPU, memory, storage, source-read, output, time, and cancellation limits.

### 8.2 Backpressure

Binnacle applies:

- per-controller and global object quotas;
- maximum simultaneous materializations;
- maximum page/chunk request rate;
- maximum aggregate output bandwidth;
- bounded result metadata and index size;
- retention and idle expiry;
- fair scheduling that preserves status, cancellation, audit, and recovery capacity.

A slow or aggressive client cannot force unbounded object creation or keep all objects alive by polling.

### 8.3 Cancellation

Cancelling the producing operation may leave:

- no result object;
- a failed object retained only as evidence;
- a complete object if completion raced and was verified.

It must not expose an arbitrary partial object unless the operation contract explicitly defines a partial-result type and information policy.

## 9. Information and Security Boundary

### 9.1 Information class

Every result object, page, and chunk retains its information class. A later page or Resource adapter cannot downgrade it.

`never-disclosable` content is never materialized into a model-readable result object. Restricted results use only the recipient and surface allowed by their disclosure contract.

### 9.2 Other controllers

An unauthorized or other-controller request must not reveal whether a result reference exists, its size, type, expiry, operation, or owner. The selected transport/profile returns a non-disclosing not-found or unauthorized result.

### 9.3 Cursor and reference logging

Raw cursors and result references are not logged in ordinary logs or metrics labels. Audit records safe digests, result identities, access outcome, ranges/pages, bytes/items, controller, and policy.

References are not secrets or authentication tokens, but unnecessary exposure can reveal workflow correlation.

### 9.4 Cross-server limitation

Once a `normal-result` page or chunk is legitimately visible to ChatGPT, Binnacle cannot prevent the host from copying it to another server. Protected and owner-only payloads remain subject to the validated HOST-profile boundary.

## 10. Retention and Expiry

### 10.1 Retention classes

Initial classes are:

| Class | Use | Minimum retention after completion |
| --- | --- | ---: |
| `RR1-transient` | Synthetic probes and ordinary bounded read results | 1 hour |
| `RR2-operation` | Command output, diffs, logs, search, and operation evidence | 24 hours |
| `RR3-audit-or-support` | Audit/export/support result objects | 7 days or source contract longer |
| `RR4-uncertain` | Result needed to reconcile uncertain work | Until reconciled plus 24 hours |

The source audit, operation, or idempotency record may have a longer retention period than the result payload.

### 10.2 Expiry

After expiry:

- payload and indices are deleted securely under the storage profile;
- a bounded tombstone may retain reference digest, source operation, terminal class, and expiry;
- the owner receives `result_expired` without resurrecting or rebuilding the object automatically;
- a new snapshot or materialization requires a new request and current policy;
- uncertain/security-relevant evidence is not deleted merely to admit new ordinary results.

### 10.3 Quota pressure

Eviction prefers expired and oldest eligible completed objects. It must not delete:

- a building object without applying its cancellation/failure contract;
- a result required for an uncertain operation or active recovery;
- an object whose source contract requires longer retention;
- audit or idempotency security records.

When quota cannot be recovered safely, new large-result production is rejected.

## 11. Errors

Initial execution errors are:

| Code | Meaning |
| --- | --- |
| `result_too_large` | Result cannot fit inline and the contract does not permit retained delivery |
| `result_storage_unavailable` | A retained object cannot be durably created or verified |
| `result_not_ready` | Materialization is still running |
| `result_failed` | Materialization failed and no complete result exists |
| `result_not_found` | No accessible result exists without disclosing another owner |
| `result_expired` | The retained result passed its expiry |
| `cursor_invalid` | Cursor is malformed, forged, wrong scope, or mismatched |
| `cursor_expired` | Cursor or snapshot passed its expiry |
| `snapshot_stale` | Required snapshot/source consistency can no longer be proved |
| `page_size_invalid` | Page size is outside the contract |
| `range_invalid` | Byte/record range is outside the result contract |
| `result_integrity_failed` | Full or chunk digest, index, or storage integrity check failed |
| `result_rate_limited` | Result retrieval exceeded the bounded access rate |

A failed page/chunk Tool call does not change the producing operation's terminal state unless an integrity or retention contract explicitly requires it.

## 12. Evidence and Audit

Large-result evidence records:

- result and snapshot identity/digest;
- producing operation and contract;
- source and query fingerprint;
- information and provenance classes;
- media type, encoding, item and byte counts;
- limits, truncation, and transformation;
- materialization state and resource use;
- retention, quota charge, and expiry;
- page/chunk access digest, range, returned size, and controller;
- cursor validation outcome;
- Resource or Tool adapter used;
- integrity and deletion result;
- HOST-profile limit or limitation where applicable.

Audit never records full protected payload unless a separate audit-content contract permits it.

## 13. Canonical Files and Tests

The canonical files are:

```text
schemas/mcp/result-reference.schema.json
spec/mcp/result-limits.yaml
tests/fixtures/mcp/pagination-large-results.yaml
```

Promotion requires tests for:

- inline boundary and automatic retained-result fallback;
- silent truncation rejection;
- complete page traversal without duplicates or omissions;
- source mutation after snapshot;
- query/order/page-size/cursor substitution;
- other-controller and other-device access;
- cursor forgery, expiry, replay, and concurrent readers;
- result build, completion, failure, restart, expiry, and quota exhaustion;
- text UTF-8 and binary chunking;
- invalid/overflow ranges and digest mismatch;
- Resources supported and unsupported fallback;
- MCP list cursor/result cursor non-interchangeability;
- transport close without deletion/cancellation;
- live-tail versus snapshot distinction;
- restricted and never-disclosable handling;
- HOST limits lower than Binnacle limits;
- audit and retention behavior.

## 14. Source of Truth

The precedence is:

1. result-reference schema;
2. result-limit policy;
3. Tool-specific output and source contract;
4. this document;
5. examples.

No host behavior or large payload observed once becomes a supported limit without the reproducible `MCP-PROFILE` evidence.