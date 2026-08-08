# Binnacle MCP Tool Manifest and Metadata Integrity

- **Status:** Draft — mandatory metadata security contract
- **Related contracts:** `MCP-INTERFACE`, `MCP-PROFILE`
- **Target wire contract:** [`mcp-2026-wire-contract.md`](mcp-2026-wire-contract.md)
- **Feature-design basis:** [`design.md`](design.md), V17
- **Canonical bootstrap manifest:** [`../spec/mcp/bootstrap-tool-manifest.yaml`](../spec/mcp/bootstrap-tool-manifest.yaml)
- **Last review:** 2026-08-08

## 1. Purpose

This document freezes how Binnacle creates, reviews, verifies, exposes, and changes model-visible MCP Tool metadata.

Tool names, descriptions, schemas, annotations, titles, execution hints, and catalogue membership influence model selection and owner confirmation. They are therefore security-relevant model-facing data. They are not authority, and clients must still treat them as untrusted unless the server and build are trusted.

The governing rules are:

> Binnacle emits Tool definitions only from a reviewed canonical manifest tied to the running build and operation-contract versions.

> A metadata digest identifies the reviewed definition; it does not prove trust by itself. Trust comes from the validated build and supply-chain profile.

> Runtime state may remove a Tool from the visible catalogue, but it may not rewrite that Tool's reviewed meaning.

## 2. Canonical Manifest

### 2.1 Source of truth

The canonical Tool manifest contains, directly or by integrity-bound reference:

- manifest schema and semantic version;
- catalogue phase;
- server and build identity requirements;
- Tool name and title;
- operation-contract identity and version;
- model-visible description;
- when-to-use and when-not-to-use review fields;
- contrastive distinctions from neighboring Tools;
- input and output schema identities and digests;
- annotations and execution hints;
- information and risk classes;
- result-shape summary;
- limits and expected errors;
- visibility phases;
- lifecycle state;
- provenance and review decision.

The running server must not compose a Tool description from repository content, package metadata, command output, device labels, external responses, or other untrusted runtime text.

### 2.2 Canonicalization

Before hashing, the build process resolves all referenced schema objects and creates one canonical representation using:

- UTF-8;
- Unicode normalization form NFC for reviewed human-readable strings;
- LF line endings;
- lexicographically sorted object keys;
- Tool entries sorted by exact case-sensitive name;
- arrays kept in contract-defined semantic order;
- no comments;
- no YAML anchors, aliases, merge keys, implicit timestamps, or implementation-dependent scalar tags;
- JSON-compatible scalar values only;
- deterministic JSON serialization with no insignificant whitespace.

The canonical representation is hashed with SHA-256.

The manifest records:

```text
manifest_id
manifest_version
canonicalization_version
manifest_sha256
build_id
build_artifact_sha256
```

The manifest digest must be reproduced independently in CI and at package creation.

### 2.3 Signing and provenance

A signature produced at runtime by the same Binnacle process would not establish independent trust. Therefore:

- the manifest digest is mandatory for bootstrap development;
- the digest is bound into build provenance and the release artefact;
- supported releases require the external signature or attestation selected by the supply-chain contract;
- Binnacle verifies the expected digest and, when promoted, the release provenance before exposing Tools;
- a missing or invalid release signature cannot be replaced by a locally generated signature.

Supply-chain key, SBOM, signing, and rollback details are defined separately. This contract defines the metadata object that those controls bind.

## 3. Startup and Runtime Verification

### 3.1 Startup

Before accepting remote Tool discovery or invocation, Binnacle must:

1. load the reviewed manifest from the protected control plane;
2. resolve the exact input and output schemas;
3. canonicalize the complete manifest;
4. verify its digest against the build-bound expected digest;
5. verify every Tool contract and schema version exists in the build;
6. verify names, descriptions, annotations, lifecycle, and phase rules;
7. reject duplicate or confusing Tool identities;
8. enter normal or restricted operation according to the result.

A manifest mismatch, missing contract, unresolvable schema, duplicate name, invalid annotation, or unexpected Tool implementation blocks the remote Tool catalogue. It must not fall back to dynamically generated metadata.

Local recovery may expose only a separately defined non-MCP break-glass path. A compromised or inconsistent manifest is not diagnosed through an unpinned remote Tool description.

### 3.2 Runtime catalogue derivation

The visible catalogue is the deterministic subset of the verified manifest allowed by:

- catalogue phase;
- deployed build;
- device profile;
- capability lifecycle;
- authenticated controller class;
- current local policy and trust state;
- implemented MCP revision.

Runtime filtering may remove a Tool entry. It must not change:

- name;
- title;
- description;
- input or output schema;
- annotations;
- execution hints;
- contract version;
- risk or information class.

If a runtime condition requires different semantics, it is a different Tool contract or an invocation-time rejection, not a metadata rewrite.

### 3.3 Discovery verification

For every `tools/list` response, Binnacle must:

- derive entries from the verified manifest;
- use deterministic ordering;
- validate each serialized Tool definition against the target MCP revision;
- calculate a canonical visible-catalogue digest;
- record manifest and visible-catalogue digests in local audit;
- expose non-secret version and digest evidence through `binnacle_probe` and `compatibility_report`;
- use `cacheScope: "private"` whenever catalogue membership varies by authenticated context;
- use the applicable TTL and revision contract.

A namespaced, client-hidden `_meta` digest may be emitted only when the selected host profile preserves it reliably. It is supplementary. The Tool catalogue must remain correct when the client ignores `_meta`.

## 4. Metadata Trust Boundary

Tool metadata is model-facing input. Binnacle must assume that:

- the model may over-trust a description;
- a client may ignore annotations;
- another MCP server may expose colliding or misleading names;
- stale cached metadata may be presented;
- external content may attempt to imitate Tool instructions.

Consequently:

- metadata never creates authorization;
- annotations never replace policy, confinement, or confirmation;
- Tool invocation is validated against the server-side contract, not the model's understanding;
- external text cannot modify the manifest;
- server instructions and Tool descriptions cannot order Binnacle to invoke another Tool;
- the actual server name and Tool origin must remain visible in compatibility evidence;
- a model-visible display name is not a unique server identity.

## 5. Naming, Collision, and Shadowing Rules

### 5.1 Exact identity

Tool names are case-sensitive stable semantic identifiers. Personal V1 uses lowercase ASCII letters, digits, and underscores.

Names must:

- be unique in the Binnacle manifest;
- not differ only by case;
- not use Unicode, invisible characters, confusables, whitespace, dots, or hyphens in Personal V1;
- not start with another Tool name followed only by an ambiguous suffix such as `_new`, `_safe`, `_real`, or a visually confusing numeral unless the lifecycle contract explicitly defines it;
- not impersonate ChatGPT, MCP protocol methods, the operating system, another server, or an owner message;
- preserve the `binnacle_` prefix for Binnacle-specific compatibility and control-plane probes.

Operational domain Tools may use reviewed domain prefixes such as `filesystem_`, `operation_`, `service_`, and `git_`.

### 5.2 Aggregated hosts

Binnacle cannot guarantee how a host disambiguates identical names from different servers. The compatibility profile must test multi-server display and selection.

If the actual host obscures server origin or permits unsafe shadowing, affected Tool contracts remain unsupported in that host profile. Binnacle must not rename Tools dynamically in response to other connected servers.

## 6. Description Contract

Every visible Tool description must answer, concisely and explicitly:

1. **Use when:** the intended owner or model situation.
2. **Do not use when:** the most likely unsafe or incorrect alternatives.
3. **Distinction:** how this Tool differs from neighboring Tools.
4. **Returns:** the main result shape and whether an operation handle is created.
5. **Limits:** material path, time, size, side-effect, network, or profile bounds.
6. **Errors:** principal correctable rejection and uncertainty outcomes.

Descriptions must:

- use factual, non-promotional language;
- never claim policy permission or owner approval;
- never promise success based only on invocation;
- state destructive, external, or synthetic-probe status accurately;
- avoid secrets, device-specific protected paths, and mutable runtime text;
- remain within the catalogue context budget.

The canonical manifest stores the exact emitted description plus structured review fields. The emitted description—not hidden review prose—is the model-facing contract.

## 7. Bootstrap Catalogue Phases

### 7.1 Phase `compatibility-core`

Visible Tools:

- `binnacle_probe`;
- `system_inspect`;
- `probe_result_formats`;
- `probe_error`;
- `compatibility_report`.

Purpose: establish connectivity, protocol behavior, structured results, errors, and sanitized observation.

No write Tool is visible.

### 7.2 Phase `compatibility-write-probe`

Adds:

- `probe_workspace_write`;
- `probe_workspace_cleanup`.

This phase is enabled only after the read-only core passes and the actual host profile permits controlled modification. The write root remains dedicated and disposable.

### 7.3 Phase `v1-readonly`

Adds promoted read-only operational Tools. Synthetic format and error probes are hidden from the normal catalogue unless the owner places the device in a locally configured compatibility-test mode.

`binnacle_probe` and `compatibility_report` remain available for version and compatibility evidence.

### 7.4 Phase `v1-operational`

Adds promoted bounded write, command, service, and Git Tools according to the device profile and security gates.

Compatibility write probes are hidden. Their old names are not reused for operational behavior.

### 7.5 Bootstrap retirement

A bootstrap Tool may be:

- retained as a compatibility diagnostic;
- hidden outside a test mode;
- retired from a later manifest.

Retirement must not reuse its name for a different behavior. The manifest records the retirement version and replacement, if any.

A host whose cached catalogue still shows a retired Tool receives a deterministic `unsupported_operation` or `contract_retired` result; the server must not route the old name to a replacement with different semantics.

## 8. Version and Digest Discovery

`binnacle_probe` and `compatibility_report` return:

- Binnacle build version and digest;
- Tool manifest ID, version, and SHA-256;
- visible catalogue phase;
- visible catalogue digest;
- operation-contract registry version;
- schema-registry version;
- MCP revision and host-profile evidence version;
- lifecycle status of the bootstrap catalogue.

These values are non-authoritative model-visible evidence. They allow ChatGPT and tests to detect change; they do not establish build trust without the external release-verification chain.

Every Tool result records its Tool contract version. A status or retained-operation result also records the contract version under which the operation was admitted.

## 9. Change Classification and Approval

### 9.1 Semantic metadata

Changes to any of these are semantic and require review:

- Tool name or title;
- description or its when-to-use/not-to-use meaning;
- input or output schema;
- annotations or execution hints;
- contract, risk, information, or lifecycle classification;
- catalogue phase membership;
- result-shape summary;
- limits or error claims;
- distinctions from neighboring Tools.

Formatting that does not change canonical output is not a manifest change.

### 9.2 Change process

A semantic change requires:

1. an explicit manifest diff;
2. owner/maintainer review of model-selection and safety effects;
3. contract-version or Tool-name change where behavior changes;
4. a new manifest version and digest;
5. metadata selection and mutation tests;
6. actual-host catalogue refresh evidence;
7. affected security and compatibility regression;
8. build provenance bound to the new digest.

A behavior, effect, risk, idempotency, error, or schema breaking change must not remain behind the old Tool semantic identity. It requires a new Tool name or an explicitly supported versioned Tool contract proven safe by the host profile.

### 9.3 Deployment and stale clients

Binnacle cannot assume that ChatGPT refreshes Tool metadata immediately.

Therefore:

- catalogue TTL remains zero until refresh behavior is measured;
- a changed build is not promoted until the actual host refreshes and the new visible digest is observed;
- stale invocation of an unchanged compatible Tool continues under server-side current policy;
- stale invocation of a retired or behaviorally changed Tool name is rejected;
- a cached annotation or description never changes local execution semantics;
- Binnacle does not claim that it can force a host-side reapproval UI.

## 10. Context-Cost Policy

The bootstrap catalogue uses these initial budgets:

| Item | Bootstrap budget |
| --- | ---: |
| Tool description | 1,200 UTF-8 bytes maximum |
| Tool title | 96 UTF-8 bytes maximum |
| One resolved input schema | 8 KiB maximum |
| One resolved output schema | 16 KiB maximum |
| Complete visible Tool catalogue | 96 KiB serialized maximum |
| Model-facing description text | 3,000 estimated tokens maximum for the complete bootstrap catalogue |

The actual ChatGPT profile must measure catalogue bytes, estimated/observed context cost, selection accuracy, and latency. A later budget change requires evidence and cannot truncate required safety distinctions silently.

When the catalogue would exceed its budget, Binnacle must:

- hide unpromoted or phase-inapplicable Tools;
- simplify schemas without weakening validation;
- split a genuinely distinct capability into a later phase;
- fail the profile or deployment if required metadata cannot fit truthfully.

It must not omit when-not-to-use, destructive, external, limit, or error information merely to fit the budget.

## 11. Validation Fixtures

Machine-readable cases are defined in:

```text
tests/fixtures/mcp/tool-metadata-security.yaml
```

Required cases include:

- digest reproduction;
- manifest/build mismatch;
- runtime description mutation;
- schema or annotation mutation;
- Tool addition not present in the manifest;
- Tool removal and stale cached invocation;
- metadata rug-pull between identical requests;
- duplicate and confusable names;
- cross-server shadowing in the actual host;
- contrastive Tool selection;
- descriptions missing use, non-use, limit, result, or error information;
- context-budget overflow;
- phase transition and bootstrap retirement;
- external signing/provenance absence for a supported release.

## 12. Source Basis

MCP requires clients to treat Tool annotations as untrusted unless the server is trusted, and recommends stable, unique names and accurate schemas and descriptions. This contract adds Binnacle-specific build, manifest, lifecycle, and host-refresh controls around that model-facing surface.

The manifest digest is not an authorization token and is not placed in Tool arguments. It is evidence bound to the build and supply-chain verification process.