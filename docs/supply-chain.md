# Binnacle Supply-Chain, Release, Update, and Rollback Security

- **Status:** Draft release contract
- **Contract version:** `1.1.0`
- **Schema:** `schemas/supply-chain/release-manifest.schema.json`
- **Policy:** `spec/supply-chain/release-policy.yaml`
- **Feature-design basis:** [`design.md`](design.md), V17

## 1. Purpose

A Binnacle release depends on source, the MCP SDK, Python/runtime packages, tunnel or gateway agents, the execution broker, sandbox controls, native libraries, build infrastructure, and installation/update logic. A supported claim requires verifiable evidence for the exact artifacts installed on the Raspberry Pi.

This contract defines mandatory release evidence without inventing concrete package versions before the implementation toolchain is selected.

## 2. Release Envelope and Unsigned Payload

The release artifact uses two layers:

```text
release envelope
├─ payload — canonical release manifest facts
└─ integrity — digest/signature/attestation over the canonical payload
```

The SHA-256 digest and signatures are not fields inside the payload they authenticate.

The canonical payload is serialized with RFC 8785 JCS. `integrity.payload_sha256` is the SHA-256 of those canonical payload bytes. Signatures and attestations bind:

- payload digest;
- release identity and version;
- primary artifact digests;
- builder/provenance identity;
- signing policy/version.

This removes self-reference and gives installers one reproducible verification procedure.

## 3. Approved Sources and Component Lock

Every release payload identifies exact immutable inputs for:

- source repository and commit/tree digest;
- official MCP SDK and transitive dependencies;
- Python/runtime and system/native dependencies;
- tunnel or gateway agent when used;
- Binnacle server, broker, executor, sandbox, migration, and updater components;
- schemas, Tool manifest, policies, and evaluation profile.

A mutable branch, unpinned package range, unverified downloaded script, or unrecorded local patch cannot form a supported release.

When a hosted external service exposes no artifact digest, the payload records:

- exact local agent artifact and digest;
- service identity and documented version/region where available;
- verification evidence and observation date;
- residual risk and operational fallback.

It never fabricates a service digest.

## 4. SBOMs and Deployed Inventory

Three distinct documents are required:

1. **source/build SBOM** — resolved build inputs and build-time tools;
2. **runtime SBOM** — components shipped in the release artifacts;
3. **deployed inventory** — exact packages, native libraries, agents, services, policies, and artifact digests observed on the installed Raspberry Pi.

Each document has an identity, format/version, digest, generation tool/version, and creation time. The deployed inventory is not represented as the runtime SBOM; it records post-install reality and drift.

## 5. Build Provenance and Reproducibility

Provenance identifies:

- source digest;
- resolved inputs and component lock;
- builder identity and isolation;
- build invocation and environment;
- produced artifact digests;
- SBOM digests;
- signing/attestation identity.

Reproducibility levels are honest claims:

| Level | Evidence |
| --- | --- |
| `RB0` | unresolved or incomplete inputs; unsupported |
| `RB1` | all inputs resolved and recorded |
| `RB2` | deterministic output reproduced by the same controlled builder |
| `RB3` | independent rebuild produced matching artifact digest |

A release claims only the highest demonstrated level.

## 6. Security Gates and Exceptions

Release gates cover:

- source and dependency vulnerability scanning;
- exploitability and exposure review;
- secret scanning;
- malware and artifact-integrity scanning;
- licence and EOL policy;
- protocol, schema, metadata, isolation, audit, idempotency, and compatibility regression.

A security exception is a complete, time-bounded governance object. It includes:

- affected release/builds and device profiles;
- affected findings/components;
- exploitability analysis and actual exposure analysis;
- reason and accepted residual risk;
- owner, approver, and remediation owner;
- monitoring controls;
- forced-retirement triggers;
- remediation deadline and exception expiry.

A closed schema must be able to represent every required field. An exception with missing analysis, owner, monitoring, or retirement trigger cannot waive a gate.

## 7. Signing and Verification

Release signing keys are separated from the runtime that emits Tool metadata. Before installation and at startup, the trusted updater/launcher verifies:

- release payload schema and canonical digest;
- signature/attestation chain and policy;
- artifact, Tool-manifest, schema, policy, and migration digests;
- supported release and retirement state;
- device/profile compatibility.

A runtime cannot repair a failed integrity check by rewriting its own evidence.

## 8. Staged Update and Rollback

Binnacle self-update uses dedicated staged capabilities, not `command_run`.

The flow is:

```text
verify release envelope
→ stage artifacts without activation
→ run migrations/checks in an isolated staging context
→ canary health and compatibility checks
→ atomically activate
→ verify service, identity, policy, audit, schema, manifest, and operation recovery
→ retain rollback state until the declared stability window closes
```

A failed stage or health check does not replace the active release. Rollback must preserve or safely migrate:

- operation/idempotency records;
- audit continuity;
- policy/profile state;
- result and recovery records;
- compatibility evidence.

A vulnerable build can be marked restricted or forcibly retired. Retirement cannot silently delete evidence needed for recovery.

## 9. Drift and Startup

The deployed inventory is compared with the release envelope at startup and periodically. Unexpected executable, dependency, policy, schema, manifest, or agent drift causes restricted startup or disables affected capabilities.

An external package manager or owner change is reported as drift; Binnacle does not silently bless it.

## 10. Tests

Required cases include:

- mutable source and dependency substitution;
- payload digest/signature self-reference prevention;
- artifact, manifest, schema, SBOM, or provenance mismatch;
- missing deployed inventory;
- exception evidence omissions and expiry;
- vulnerability freshness and time-bounded exception handling;
- reproducibility overclaim;
- startup drift and retired build;
- update crash before/after activation;
- migration failure, canary failure, rollback, and rollback incompatibility;
- tunnel-agent and hosted-service evidence gaps.

## 11. Invariants

1. The digest/signatures are outside the payload they authenticate.
2. Source, components, artifacts, schemas, policies, and Tool metadata are integrity-bound.
3. Source/build SBOM, runtime SBOM, and deployed inventory are separate required documents.
4. Security exceptions contain all required evidence and expire.
5. Reproducibility claims never exceed demonstrated evidence.
6. Installation and startup verify the exact installed build.
7. Update failure preserves the previous trusted release or enters explicit recovery.
