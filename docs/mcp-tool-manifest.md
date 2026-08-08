# Binnacle MCP Tool Manifest and Metadata Integrity

- **Status:** Draft implementation contract
- **Contract version:** `1.1.0`
- **Source manifest:** `spec/mcp/bootstrap-tool-manifest.yaml`
- **Canonical schemas:** `schemas/mcp/`
- **Feature-design basis:** [`design.md`](design.md), V17

## 1. Purpose

Tool names, descriptions, schemas, annotations, and catalogue membership affect model behaviour but do not authenticate themselves. Binnacle therefore derives runtime Tool metadata from one reviewed manifest and verifies it against the selected build before serving discovery.

## 2. Source and Runtime Manifests

The checked-in source manifest contains:

- manifest identity and version;
- catalogue phase rules;
- Tool names and contract versions;
- contrastive descriptions;
- repository-relative schema references;
- annotations, information class, confirmation class, and implementation binding.

The build creates a runtime manifest by resolving every schema reference and implementation binding. The runtime manifest contains the resolved schema digests and build artifact identity.

### 2.1 Detached digest record

The manifest digest is not stored inside the bytes that it hashes. The release produces a detached record:

```json
{
  "manifest_id": "binnacle-bootstrap-tools",
  "manifest_version": "1.1.0",
  "manifest_sha256": "<sha256 of canonical runtime manifest bytes>",
  "build_id": "<release build>",
  "build_artifact_sha256": "<artifact digest>",
  "schema_registry_sha256": "<resolved registry digest>"
}
```

The canonical runtime manifest excludes this detached record. Release signing and attestation sign the detached digest plus build identity. No self-referential digest or signature field is permitted.

### 2.2 Canonicalization

The build uses UTF-8, LF line endings, normalized Unicode NFC strings, deterministic key ordering, and the repository's canonical YAML-to-JSON conversion profile. The exact canonical bytes and algorithm version are recorded in the detached release evidence.

## 3. Resolvable Schema References

Every source Tool entry uses a repository-relative reference such as:

```text
schemas/mcp/bootstrap-inputs.schema.json#/$defs/binnacle_probe.input.v1_1
```

The build must:

1. resolve the path and JSON Pointer;
2. reject a missing or ambiguous reference;
3. validate the schema as JSON Schema 2020-12;
4. record the resolved file and definition digests in the runtime manifest;
5. bind those digests into the detached manifest record.

Startup fails closed if the runtime manifest, schema registry, implementation binding, or detached digest record does not match the installed build.

## 4. Metadata Rules

A Tool description must state:

- when to use the Tool;
- when not to use it;
- the closest contrasting Tool;
- result shape and information class;
- important limits;
- major rejection or uncertainty outcomes.

Runtime filtering may remove an entire Tool. It may not rewrite:

- name, title, description, or annotations;
- input or output schema;
- contract version;
- maximum effect or information class;
- confirmation class;
- implementation binding.

A semantic change requires a new contract version and a reviewed manifest change. Cached host metadata never changes the server-side execution contract.

## 5. Catalogue Phases

| Phase | Purpose | Visible Tools |
| --- | --- | --- |
| `compatibility-core` | Connect and test read-only fundamentals | `binnacle_probe`, `system_inspect`, `probe_result_formats`, `probe_error`, `compatibility_report` |
| `compatibility-write-probe` | Test exact disposable write/cleanup flow | Core plus `probe_workspace_prepare`, `probe_workspace_write`, `probe_workspace_cleanup` |
| `v1-readonly` | Promoted read-only Binnacle use | Promoted operational read Tools; synthetic probes hidden by default |
| `v1-operational` | Promoted bounded mutation/administration | Only promoted operational Tools |

Synthetic compatibility Tools may be exposed during `v1-readonly` only when:

- `compatibility_test_mode` is explicitly enabled by local policy;
- the source manifest lists the phase in `test_only_phases`;
- discovery remains private with zero TTL;
- the Tool remains under its original contract and cannot gain broader authority.

Filtering can only remove a manifest-authorized entry. Test mode cannot invent a Tool or expand its phases.

## 6. Bootstrap Contracts

The bootstrap manifest contains exactly eight Tool contracts:

```text
binnacle_probe 1.1
system_inspect 1.1
probe_result_formats 1.1
probe_error 1.1
compatibility_report 1.1
probe_workspace_prepare 1.1
probe_workspace_write 1.1
probe_workspace_cleanup 1.1
```

`probe_workspace_cleanup` removes one exact artifact per call. Bulk cleanup or “all owned artifacts” would require a different contract version and owner-visible maximum effect.

`binnacle_probe` `1.1` returns build, manifest, protocol, device, and catalogue identity fields defined in the versioned output schema. Earlier `1.0` result shapes are not silently emitted under the `1.1` contract.

## 7. Naming and Collision Controls

Binnacle rejects:

- duplicate Tool names;
- Unicode-confusable, invisible-character, case-fold, normalization, or punctuation shadowing of another Tool;
- unmanifested runtime Tools;
- a schema/annotation/description change without a contract-version change;
- a runtime handler bound to a different Tool identity.

Security fixtures represent invisible code points with explicit escapes such as `system_\u200Binspect`, never literal invisible characters.

## 8. Discovery and Refresh

Binnacle cannot force ChatGPT to refresh cached metadata. Therefore:

- the runtime always enforces the current manifest and contract;
- stale retired names fail deterministically;
- changed builds are not promoted until the real host demonstrates refreshed discovery;
- a changed catalogue uses private cache scope and a profile-appropriate TTL;
- host selection tests compare contrastive Tools and record the actual chosen name/arguments.

## 9. Bootstrap Retirement

A synthetic Tool may be retired only after:

- its compatibility purpose has completed;
- operational replacements pass their gates;
- the host has demonstrated catalogue refresh;
- stale-name calls fail safely;
- the retirement is recorded in the evaluation profile.

Retirement removes discovery exposure but does not change historical audit or evidence records.

## 10. Invariants

1. The source manifest is reviewed; the runtime manifest is build-resolved.
2. Manifest and schema digests are detached from the bytes they hash.
3. Every schema reference resolves and is integrity-bound before startup.
4. Runtime filtering may remove but never rewrite Tool semantics.
5. Compatibility test mode exposes only manifest-declared test-only phases.
6. One Tool name has one contract version and one implementation binding.
7. Model-visible metadata never grants server authority.
