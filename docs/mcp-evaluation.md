# Binnacle ChatGPT MCP Evaluation and Evidence Contract

- **Status:** Draft — mandatory empirical HOST-profile contract
- **Related contracts:** `MCP-PROFILE`, `MCP-INTERFACE`, `RELEASE-GATE`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Compatibility profile:** [`mcp-profile.md`](mcp-profile.md)
- **Revision support:** [`mcp-revision-support.md`](mcp-revision-support.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines how Binnacle tests the actual ChatGPT MCP client, records evidence, derives a versioned compatibility profile, and decides which MCP features and Binnacle Tool contracts may be promoted.

Documentation, SDK support, another MCP client, another ChatGPT plan, and a single successful Tool call are not sufficient evidence for the target profile.

The governing rules are:

> A feature is supported only when the exact ChatGPT product/account/workspace/connection profile exercises it end to end and the frozen oracle passes.

> An absent observation is not evidence of support or non-support. Every axis is classified explicitly.

> The probe server, schemas, manifest, account, workspace policy, connection path, and evidence bundle are identified immutably enough to reproduce or explain the result.

## 2. Evaluation Objects

### 2.1 Evaluation profile

One evaluation profile identifies:

- profile ID and version;
- ChatGPT product and surface;
- plan and workspace type;
- account/workspace policy digest or recorded configuration facts;
- owner/tester identity reference;
- geographic or regional routing facts when exposed and relevant;
- browser/app and version where relevant;
- connection method and endpoint;
- controller authentication profile;
- Binnacle probe release, artifact, Tool manifest, schemas, and configuration digests;
- intended MCP revision set;
- test matrix and oracle version;
- evidence retention and redaction policy.

A result from another profile is comparative evidence only.

### 2.2 Evaluation run

One run has:

- unique run ID;
- profile ID/version;
- start/end time;
- exact probe deployment identity;
- selected test cases;
- preconditions and known limitations;
- ordered requests and observations;
- pass/fail/blocked outcomes;
- evidence file digests;
- tester notes and adjudication;
- final run integrity digest.

### 2.3 Compatibility profile

A compatibility profile is the reviewed result of one or more runs. It contains only observed or explicitly blocked behavior and has its own version, validity period, evidence references, and rerun triggers.

It distinguishes:

- server-supported MCP features;
- client-declared features;
- features successfully exercised;
- features blocked by account/workspace/host policy;
- features not implemented by the probe;
- failed or unstable features;
- untested features.

## 3. Observation Status Vocabulary

Every capability axis has exactly one status:

| Status | Meaning |
| --- | --- |
| `supported_observed` | The exact profile passed the end-to-end positive and required negative cases |
| `declared_unexercised` | The client or documentation declared support, but the run did not complete the required test |
| `failed` | The feature was attempted and the frozen oracle failed |
| `unstable` | Repeated identical tests produced materially inconsistent results |
| `not_declared` | The client did not advertise the feature where the protocol requires declaration |
| `blocked_by_host_policy` | The host/account/workspace prevented the test before Binnacle feature behavior could be established |
| `not_implemented_by_probe` | Binnacle did not expose the required probe, so no client conclusion is possible |
| `not_applicable` | The frozen profile prospectively excludes the feature with rationale |
| `expired` | Previous evidence is no longer current under a rerun trigger or validity period |

Only `supported_observed` can become a Binnacle dependency. `declared_unexercised` is not support.

## 4. Probe Release

### 4.1 Immutable probe identity

The probe is built through the supply-chain preview contract and records:

- source commit and release ID;
- server artifact digest;
- MCP SDK version/digest;
- Tool manifest and visible catalogue digest;
- schema-registry and operation-contract digests;
- revision dispatch version;
- authentication and tunnel/gateway profile versions;
- probe configuration digest;
- installed device and OS profile;
- SBOM and provenance references.

A code, dependency, manifest, schema, policy, or configuration change creates a different probe identity.

### 4.2 Probe isolation

The compatibility probe uses:

- one dedicated Raspberry Pi or isolated preview deployment;
- a disposable test workspace;
- no owner production data or credentials;
- synthetic or profile-approved test values;
- bounded operations and resource limits;
- audit and evidence retention;
- no hidden feature flags outside the recorded configuration.

### 4.3 Probe phases

The run progresses prospectively:

1. `connectivity`;
2. `read-only-core`;
3. `structured-results-and-errors`;
4. `controlled-write-entitlement`;
5. `long-running-and-cancellation`;
6. `optional-primitives-and-extensions`;
7. `high-impact-confirmation`;
8. `multi-server-and-cross-server`;
9. `regression-and-stability`.

A later phase does not rewrite an earlier failure. The profile may stop at a blocker and still record valid earlier evidence.

## 5. Required Test Axes

### 5.1 Connection and authentication

Test:

- endpoint reachability through the selected private path;
- authentication challenge and credential flow;
- stable controller identity;
- issuer, audience, subject, client, tenant/workspace, scope, and expiry behavior where the profile uses them;
- reconnect and controller replacement;
- tunnel bypass and direct-listener rejection;
- revocation and expiry;
- no credential leakage.

### 5.2 Protocol revision and dispatch

Test:

- actual revision indication or negotiation;
- modern request headers and `server/discover`;
- legacy `initialize` and session behavior where applicable;
- unsupported-version and cross-era rejection;
- result shapes for the selected revision;
- no unadvertised Tasks or optional extension.

### 5.3 Discovery and metadata

Test:

- `tools/list` or target-era discovery behavior;
- refresh and cache behavior;
- private catalogue isolation;
- deterministic order;
- Tool names, descriptions, schemas, annotations, and execution hints;
- server-origin display;
- metadata update and stale-cache behavior;
- collision/shadowing with a test server.

### 5.4 Tool input and output

Test:

- required, optional, default, enum, array, object, nullable, and unknown fields;
- closed-schema rejection;
- structured output preservation;
- model-readable content;
- output-schema validation;
- warnings and bounded errors;
- protocol error versus Tool execution error;
- large result and truncation behavior under the result-limit contract.

### 5.5 Read and write entitlement

Test separately:

- harmless read-only invocation;
- profile-observable local facts;
- controlled disposable write;
- cleanup of only owned probe artifacts;
- direct invocation when a write Tool is hidden or blocked;
- whether the blocker is MCP, account plan, workspace policy, confirmation, or Binnacle policy.

### 5.6 Long-running work

Test:

- response and connection duration;
- Binnacle operation-handle return;
- status polling;
- reconnect and retained result;
- cancellation request and verified local outcome;
- timeout and uncertain result;
- duplicate/retry and idempotency;
- MCP Tasks only when declared and separately implemented.

### 5.7 Host confirmation

For each HC1 Tool contract, test the full confirmation matrix in `mcp-host-confirmation.md`, including decline, timeout, argument change, retry, batching, Tasks/MRTR paths, conversation changes, fatigue, and direct-call bypass.

### 5.8 Optional MCP features

Test independently:

- Resources;
- Prompts;
- MRTR input-required/elicitation;
- Tasks extension;
- progress or logging notifications;
- catalogue-change notifications;
- other extensions.

Failure of an optional feature does not invalidate the fundamental Tool profile unless the interface depends on it.

### 5.9 Cross-server behavior

With a controlled second MCP server, test:

- server-origin visibility;
- Tool-name collision;
- model selection after untrusted content;
- transfer of model-visible normal results;
- exclusion of owner-only and hidden fields;
- confirmation before consequential action on the second server;
- inability of Binnacle to control copied data after authorized model disclosure.

The result defines the HOST-profile limitation; it does not create a Binnacle cross-server enforcement claim.

## 6. Test Oracles

Each case defines:

- setup and prerequisites;
- exact owner prompt or deterministic API action;
- expected server requests and ordering;
- expected Tool selection and arguments;
- expected host confirmation or absence;
- expected Binnacle and MCP result;
- expected audit and compatibility evidence;
- prohibited requests/effects;
- timeout;
- retry/repetition count;
- pass, fail, blocked, and inconclusive criteria.

A human impression such as “looks supported” is not an oracle.

### 6.1 Positive and negative cases

A feature is not `supported_observed` until its required positive and negative cases pass. Examples:

- valid Tool call **and** invalid argument rejection;
- controlled write **and** write outside the probe root rejection;
- cancellation request **and** no false `cancelled` state;
- confirmation acceptance **and** decline/timeout/no-call behavior;
- supported revision **and** unsupported-version rejection.

### 6.2 Repetition

The profile defines repetitions by risk:

| Risk | Minimum repetitions per deterministic case |
| --- | ---: |
| Read-only fundamental behavior | 3 |
| Write, cancellation, retry, cache, confirmation | 5 |
| Concurrency, race, reconnect, instability probes | 10 or contract-specific matrix |

A known nondeterministic host feature records distribution and thresholds instead of hiding variance.

## 7. Evidence Bundle

### 7.1 Bundle contents

One evaluation bundle contains:

- `evaluation-manifest.json` conforming to the canonical schema;
- probe release manifest and sanitized deployed inventory;
- test-profile and case-manifest digests;
- server audit export or bounded event projection;
- sanitized request/response traces sufficient to prove the MCP behavior;
- Tool catalogue and schema snapshots;
- host-visible screenshots, recordings, or structured observations where UI behavior is the subject;
- owner/tester action log;
- result summaries and raw machine-readable case results;
- environment and timing facts;
- known exclusions and limitations;
- bundle file manifest and digests;
- optional external signature/attestation.

### 7.2 Redaction

The bundle must not contain:

- access or refresh tokens;
- authorization headers, cookies, or gateway assertions;
- private keys or passwords;
- owner production data;
- raw controller or credential material;
- never-disclosable Binnacle fields;
- full unrelated conversations;
- unbounded logs or network payloads.

Redaction occurs before bundle finalization. The bundle records redaction policy and categories, not secret values.

### 7.3 Raw evidence and derived conclusions

Raw observations are retained separately from conclusions. A reviewer must be able to trace each profile status to exact evidence and oracle.

A profile conclusion cannot alter the raw case result. Re-adjudication creates a new review record.

## 8. Evaluation Manifest and Integrity

The canonical schema is:

```text
schemas/mcp/evaluation-manifest.schema.json
```

The manifest binds:

- evaluation profile/run identity;
- exact ChatGPT and Binnacle environment;
- test and oracle versions;
- case results;
- evidence files and digests;
- status conclusions;
- reviewer and owner decisions;
- validity and rerun triggers;
- bundle digest and optional signature/attestation.

The bundle may be locally hash-chained and externally signed. A runtime self-signature alone does not establish independent evidence integrity.

## 9. Profile Derivation

### 9.1 Promotion rule

A capability is promoted only when:

- the server implements it under the selected revision;
- the exact host profile declares it when declaration is required;
- all required positive and negative cases pass;
- result stability meets its threshold;
- security, privacy, confirmation, and entitlement conditions pass;
- evidence is complete and current;
- the interface contract explicitly selects it.

### 9.2 Narrowest valid claim

The compatibility claim is limited to the tested dimensions. Example:

```text
ChatGPT web
Pro plan
personal workspace policy digest X
Secure MCP Tunnel profile Y
Binnacle probe release Z
MCP legacy revision 2025-11-25
read-only Tools supported_observed
controlled write blocked_by_host_policy
Tasks not_declared
```

It must not be generalized to all ChatGPT Pro users or all ChatGPT surfaces.

### 9.3 Conflicting runs

When two current runs conflict:

- classify the axis as `unstable` or split the profile by the differing dimension;
- retain both evidence bundles;
- do not select the more convenient result silently;
- block dependency on that feature until the conflict is explained or the interface tolerates both behaviors.

## 10. Validity and Rerun Triggers

A profile expires or requires targeted rerun after a material change to:

- ChatGPT product, plan, surface, account, workspace, or policy;
- host release behavior or owner-visible UI;
- connection/tunnel/gateway/authentication profile;
- MCP revision or client capabilities;
- Binnacle source, build, SDK, manifest, schema, Tool, policy, or configuration;
- device OS, kernel, architecture, or network environment where relevant;
- confirmation behavior;
- result/caching/pagination/timeout limits;
- previously observed entitlement;
- evidence validity period;
- a security incident or regression report.

The compatibility profile defines a maximum age even without a known change. Initial maximum age is 30 days for preview and 90 days for a supported stable profile, subject to shorter host-change triggers.

## 11. Automation Boundary

Binnacle should automate:

- probe deployment verification;
- deterministic Tool calls;
- server-side traces and audit extraction;
- schema and oracle validation;
- evidence hashing and bundle creation;
- comparison with previous runs;
- generation of the draft compatibility profile.

Human or ChatGPT assistance may be required for:

- ChatGPT UI connection and owner confirmation;
- observing model-selected Tool behavior;
- account/workspace policy setup;
- screenshots or recordings;
- adjudicating ambiguous host UI results.

Automation cannot fabricate a host interaction or mark an unexecuted case passed.

## 12. Privacy and Test Data

The evaluation uses synthetic data and a disposable workspace by default. Any real owner data requires a separate explicit information contract and is excluded from normal compatibility evidence.

Screenshots and recordings are treated as restricted evidence when they contain account, workspace, device, or conversation details. Their retention and access are declared in the profile.

## 13. Machine-Readable Files

The canonical files are:

```text
schemas/mcp/evaluation-manifest.schema.json
spec/mcp/evaluation-profile.yaml
tests/fixtures/mcp/evaluation-reproducibility.yaml
```

They define the evidence object, initial matrix, repeat counts, statuses, profile derivation, conflict behavior, redaction, and rerun triggers.

## 14. Relationship to `mcp-profile.md`

`mcp-profile.md` remains the human-readable current profile and source review. It must cite the evaluation profile version and evidence-bundle digest for every promoted feature.

Statements based only on documentation remain source-derived expectations and cannot be labelled `supported_observed`.

## 15. Source of Truth

The precedence is:

1. evaluation-manifest schema and case results;
2. evaluation-profile and test oracle;
3. retained evidence bundle;
4. reviewed compatibility-profile conclusion;
5. `mcp-profile.md` summary;
6. external documentation expectations.

The actual connection is authoritative only as recorded through the frozen experiment and evidence contract.