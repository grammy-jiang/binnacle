# Binnacle Pagination, Large Results, and Retained Result Objects

- **Status:** Draft MCP result-boundary contract
- **Contract version:** `1.1.0`
- **Schemas:** `schemas/mcp/result-reference.schema.json`
- **Limits:** `spec/mcp/result-limits.yaml`
- **Feature-design basis:** [`design.md`](design.md), V17

## 1. Purpose

A Binnacle Tool result must be complete, bounded, and recoverable without silent truncation. Directory listings, searches, command output, logs, diffs, audit projections, and compatibility evidence may exceed one safe ChatGPT Tool result.

Binnacle V1 uses three delivery modes:

| Mode | Use |
| --- | --- |
| `inline` | Complete result fits the effective Tool-result limit |
| `item-page` | Immutable ordered collection read through bounded pages |
| `byte-chunk` | Immutable text/binary object read through bounded chunks |

A live stream or tail is a separate retained operation, not an implicit fourth mode.

## 2. Canonical Tool Envelopes

Large-result Tools use the same canonical success and execution-error envelopes as every other Binnacle Tool.

The result schema defines full Tool `structuredContent`, including:

- `schema_version`, `call_status`, Tool identity, request identity;
- Tool-specific `data`;
- `operation`, `evidence`, and `warnings`;
- an execution-error union.

The page/chunk schema is not merely an inner `data` object. `result_get`, `result_page`, and `result_chunk` each declare an output schema for the complete Tool envelope.

Every target-era response also includes bounded model-readable `content` outside `structuredContent`.

## 3. Effective Limits

The effective limit is the minimum of:

- Binnacle build/device profile;
- Tool and information contract;
- resource/storage budgets;
- selected MCP revision/transport;
- empirically validated ChatGPT profile.

Initial conservative Binnacle defaults are:

| Limit | Value |
| --- | ---: |
| Model-readable TextContent | 8 KiB |
| Serialized `structuredContent` | 64 KiB |
| Complete serialized Tool result | 96 KiB |
| Inline Tool-specific data target | 32 KiB |
| Default item page | 50 items |
| Maximum item page | 200 items |
| Default decoded chunk | 16 KiB |
| Maximum decoded chunk | 32 KiB |
| Retained result object | 32 MiB |
| Per-controller retained bytes | 256 MiB |

The base64 expansion, field names, digests, evidence, warnings, and JSON framing all count against serialized limits. A 32 KiB decoded binary chunk is an upper bound, not a guarantee; the server reduces it when the envelope would exceed 64 KiB structured content or 96 KiB complete result.

The policy field name is consistently `model_readable_content_bytes_max`.

## 4. No Silent Truncation

An inline result states:

- `delivery_mode: inline`;
- `complete: true`;
- returned item/byte counts;
- `continuation_available: false`;
- `result_ref: null`.

If the result cannot fit, Binnacle either materializes a retained result or returns `result_too_large` / `result_storage_unavailable`. It never returns a prefix marked complete.

## 5. Retained Result Lifecycle

A retained result has:

```text
building → complete → expired
        ↘ failed
complete → deleted
```

Correlations are normative:

| Lifecycle | Read/page/chunk behaviour |
| --- | --- |
| `building` | `result_get` may report status; page/chunk returns `result_not_ready` |
| `complete` | metadata and the declared page/chunk mode are readable |
| `failed` | metadata/error only; no partial payload presented as complete |
| `expired` | tombstone/status only; payload unavailable |
| `deleted` | non-disclosing not-found/tombstone result according to policy |

`item-page` and `byte-chunk` reads require `lifecycle: complete`. `inline` is complete in its initiating Tool result and does not create a retained result reference.

## 6. Retained Result Binding

The server record binds:

- result identity/schema/lifecycle/delivery mode;
- producing operation/request/Tool/contract;
- controller and device identity/epoch;
- normalized query/filter/order/format fingerprint;
- source snapshot and provenance;
- information class, recipient, and result surface;
- media type/encoding;
- item and decoded-byte counts;
- complete-result digest;
- policy/profile versions;
- creation/completion/access/expiry times;
- quota charge and audit identity.

Possession of `result_ref` or cursor creates no authority. Every access reauthenticates and revalidates ownership, policy, information class, lifecycle, and expiry.

The result object and digest are durable before a usable reference is returned.

## 7. Item Pagination

A promoted item-page contract uses one immutable logical snapshot and deterministic total order with a stable tie-breaker.

The cursor binds:

- controller/device;
- Tool/contract;
- result/snapshot identity;
- normalized query/filter/projection/order;
- page size and next position;
- information class/recipient;
- policy version and expiry;
- cursor format version.

Repeated use of the same valid cursor returns the same page. It does not advance a global mutable pointer.

Traversal guarantees no overlap or omission under the snapshot contract. The final page has `next_cursor: null`.

A source that cannot provide snapshot consistency must declare a separate unstable/live contract and cannot be used where complete reconstruction is required.

## 8. Byte Chunks

`result_chunk` binds:

- result reference;
- zero-based decoded-byte offset;
- requested decoded length within the effective limit;
- media type and encoding;
- full decoded length and digest;
- returned offset/length and chunk digest;
- next offset and completion.

Text chunks do not split invalid UTF-8 sequences. Binary chunks use base64 in structured content and count expanded bytes against the envelope budget.

Negative/overflow ranges, incompatible encoding, changed identity, and excessive length are rejected.

## 9. MCP Resources and Protocol Pagination

MCP Resources may adapt retained result objects only after the actual ChatGPT profile proves discovery, URI handling, size/media behaviour, authorization, caching, errors, expiry, and information boundaries.

The canonical fallback remains:

```text
result_get
result_page
result_chunk
```

Protocol-native cursors for MCP list methods are distinct from Binnacle result cursors and cannot be interchanged.

Streamable HTTP does not prove that an unbounded partial Tool payload can be consumed incrementally. Binnacle returns one complete bounded Tool result or one retained reference.

## 10. Information and Cross-Controller Security

Every page/chunk retains its source information class. A later request cannot downgrade it.

An unauthorized controller request does not reveal whether a result exists, its size, type, owner, or expiry. Raw result references and cursors are absent from ordinary logs and metrics; audit uses safe digests and access facts.

Once a permitted `normal-result` enters model-visible context, Binnacle cannot control later host use with another server. `restricted-result` remains excluded unless the exact HOST/information contract permits it.

## 11. Retention and Pressure

Initial classes are:

| Class | Minimum payload retention |
| --- | ---: |
| `RR1-transient` | 1 hour |
| `RR2-operation` | 24 hours |
| `RR3-audit-or-support` | 7 days |
| `RR4-uncertain` | until reconciled plus 24 hours |

Quota eviction never removes payload required for uncertainty/recovery or security records. When safe capacity cannot be recovered, new large-result production is rejected.

## 12. Errors

Initial errors include:

```text
result_too_large
result_storage_unavailable
result_not_ready
result_failed
result_not_found
result_expired
cursor_invalid
cursor_expired
snapshot_stale
page_size_invalid
range_invalid
result_integrity_failed
result_quota_exceeded
```

Every execution error uses the canonical Tool execution-error envelope.

## 13. Tests

Required cases cover:

- exact boundary sizes and envelope overhead;
- inline versus retained lifecycle correlations;
- complete page reconstruction with concurrent source mutation;
- duplicate cursor request, reconnect, expiry, and other-controller use;
- UTF-8 boundaries, binary base64 expansion, range and digest failures;
- restart, cancellation, quota pressure, and storage failure;
- optional Resources fallback and transport close;
- information-class and audit leakage;
- host result-size limits lower than Binnacle defaults.

## 14. Invariants

1. A Tool result is complete inline or recoverable through one retained object.
2. Retrieval output schemas describe the full canonical Tool envelope.
3. Page/chunk reads require a complete retained result lifecycle.
4. Chunk sizes include serialized-envelope and base64 overhead.
5. Cursors are deterministic, bound, non-authoritative, and replayable for the same page.
6. No cross-controller reference reuse or information downgrade is permitted.
7. Numeric defaults are Binnacle limits, not undocumented ChatGPT claims.
