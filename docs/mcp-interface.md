# Binnacle MCP Interface Design

- **Status:** Draft — bootstrap interface before live ChatGPT validation
- **Contract version:** `1.2.0`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Compatibility evidence:** [`mcp-profile.md`](mcp-profile.md)
- **Revision contract:** [`mcp-revision-support.md`](mcp-revision-support.md)
- **Schemas:** [`mcp-schemas.md`](mcp-schemas.md)

## 1. Purpose

This document defines the MCP-facing interface between ChatGPT and one Binnacle instance on one Raspberry Pi. It is not a website, owner-control companion, or local reasoning-agent interface.

ChatGPT plans and selects operations. Binnacle authenticates the controller, validates explicit inputs and local policy, executes deterministically, owns local operation state, and returns structured facts.

## 2. Interface Principles

1. **Tools first.** V1 operational work uses focused MCP Tools.
2. **Minimal dependency.** Initial connectivity requires only Tool discovery and Tool invocation.
3. **Stable local identity.** MCP request, conversation, connection, and optional Task identities never replace Binnacle `operation_id` or idempotency identity.
4. **Local policy is authoritative.** Discovery and annotations never grant authority.
5. **Truthful outcomes.** Transport success, Tool-call success, and operation success are separate.
6. **No server reasoning.** Binnacle does not interpret goals or choose strategies.
7. **Compatibility by evidence.** Optional features are dependencies only after the real ChatGPT profile passes their tests.

## 3. Protocol Surface

The preferred endpoint is Streamable HTTP at `/mcp`, normally reached through an explicitly validated private connection or tunnel.

Binnacle implements the finite revision set in `mcp-revision-support.md`. It does not depend on Tasks, elicitation/MRTR, Resources, Prompts, list-change notifications, or custom UI for the bootstrap workflow.

| Primitive | V1 position |
| --- | --- |
| Tools | Required |
| Resources | Optional adapter after host validation |
| Prompts | Not used |
| Sampling | Prohibited |
| Roots | Not used |
| MRTR/elicitation | Probe only until validated |
| Tasks | Optional extension adapter only |
| Custom UI | Not used |

## 4. Tool Identity and Metadata

Tool names are stable lowercase ASCII identifiers. Every Tool definition is derived from the reviewed manifest in `spec/mcp/bootstrap-tool-manifest.yaml` and includes:

- name and title;
- contrastive description;
- exact contract version;
- resolvable input/output schema references;
- accurate annotations;
- information class;
- catalogue phases;
- confirmation classification;
- implementation binding.

The runtime catalogue may filter out Tools but may not rewrite their names, schemas, descriptions, annotations, effects, or information treatment.

## 5. Canonical Results and Errors

Every successful Tool call returns:

- bounded model-readable `content`;
- schema-valid `structuredContent` using the success envelope;
- `isError: false`.

Every post-authentication execution error returns:

- bounded model-readable `content`;
- schema-valid execution-error `structuredContent`;
- `isError: true`.

HTTP authentication and authorization failures use HTTP `401`/`403`. MCP framing/version/method failures use protocol errors. They are not represented as Tool execution errors.

The canonical schemas and lifecycle are defined in `mcp-schemas.md`.

## 6. Bootstrap Catalogue

### 6.1 `binnacle_probe`

Use when ChatGPT needs to verify connectivity, build identity, device identity, selected protocol revision, Tool-manifest identity, and visible catalogue phase.

Do not use for detailed system health or compatibility conclusions.

- Read-only; normal-result; HC0.
- Contract `1.1`.

### 6.2 `system_inspect`

Use for bounded read-only Raspberry Pi and Binnacle-service facts.

Do not use for arbitrary file, process, network, or hardware inspection.

- Read-only; normal-result; HC0.
- Contract `1.1`.

### 6.3 `probe_result_formats`

Use only during compatibility evaluation to test structured/text result handling.

Do not use as an operational data Tool.

- Read-only; normal-result; HC0.
- Contract `1.1`.

### 6.4 `probe_error`

Use only to exercise deterministic validation, policy, failure, timeout, delay, and uncertainty presentation.

It creates no intentional device effect.

- Read-only from a device-state perspective; normal-result; HC0.
- Contract `1.1`.

### 6.5 `compatibility_report`

Returns the sanitized empirical ChatGPT profile. The bootstrap report contains no credentials, raw headers, private owner data, or reusable authority material and is therefore a `normal-result`.

Use it to inspect recorded compatibility evidence, not to infer untested support.

- Read-only; normal-result; HC0.
- Contract `1.1`.

### 6.6 `probe_workspace_prepare`

Creates a short-lived, no-effect state binding for exactly one disposable probe-workspace write or cleanup. It returns:

- `prepared_operation_id`;
- `execution_nonce`;
- normalized input digest;
- exact operation/path;
- maximum effect;
- expiry.

It is not proof of owner approval and cannot execute the operation.

- Read-only/no-effect; normal-result; HC0.
- Contract `1.1`.

### 6.7 `probe_workspace_write`

Creates one new file under the dedicated probe workspace. It cannot overwrite an existing file, escape the root, access credentials, contact a network, or affect Binnacle control-plane state.

It requires:

- exact unexpired preparation identity and nonce;
- 128-bit-or-stronger caller idempotency key;
- exact prepared path and content digest;
- current controller authentication and local write-probe policy;
- the validated HOST-profile confirmation treatment for HC1.

- Mutating; normal-result; HC1 profile gate.
- Contract `1.1`.

### 6.8 `probe_workspace_cleanup`

Removes one exact manifest-owned probe artifact identified by path, artifact identity, and content digest. It is not a bulk cleanup Tool.

It requires the same preparation, idempotency, controller, policy, and HOST-profile conditions as the write Tool.

- Mutating/destructive within the disposable probe root; normal-result; HC1 profile gate.
- Contract `1.1`.

### 6.9 Reviewed Phase 9 contracts (not runtime-promoted)

The canonical manifest also defines `privileged_prepare`, `package_inspect`,
`package_install`, `binnacle_service_inspect`, `binnacle_service_restart`,
`restart_preflight`, `binnacle_restart`, and `binnacle_runtime_inspect`, all at contract
`1.0`. Their closed schemas and HC0/HC2 classifications are implementation-review inputs;
they are not present in either served compatibility catalogue and the `v1-operational`
projection remains disabled.

Consequential Phase 9 execution requires exact preparation, controller/device/session and
current-state binding, Phase 4 lifecycle/audit truth, protected profiles, broker ticket and
acceptance, retained idempotency, and—where applicable—the Phase 6 workspace fence,
tested candidate, complete candidate/LKG slots, checkpoint, and exact runtime verification.
Missing real Raspberry Pi or ChatGPT evidence blocks later runtime promotion only.
`host_reboot` has no Tool contract.

## 7. Preparation and Confirmation Boundary

Preparation is server-enforced state binding. Host confirmation is an empirically validated product behaviour. They are not interchangeable.

Binnacle can enforce:

- that execute inputs match an unexpired prepared operation;
- local policy and current-state checks;
- idempotency and exactly-once reconciliation;
- filesystem, privilege, resource, and information bounds.

Binnacle cannot cryptographically prove that the owner clicked a ChatGPT confirmation control. A Tool classified HC1–HC3 remains unsupported for a ChatGPT profile unless the host evaluation demonstrates the required presentation and non-bypassable interaction. That profile decision does not expand server authority.

## 8. Idempotency and Operation Identity

Every mutating Tool accepts an idempotency key or prepared execution nonce before admission. The server durably binds it to controller, device, Tool contract, and normalized effect-bearing inputs before any effect.

Same-key/same-input retries return the retained operation. Same-key/different-input reuse is rejected. A controller replacement cannot use the old key to create a second effect.

Retained operations use explicit `operation_id` for status, cancellation, result, and evidence. Transport disconnect does not prove cancellation.

## 9. Long-Running Work

The portable V1 model is:

```text
start Tool → operation_id
operation_get(operation_id)
operation_cancel(operation_id)
result reference or terminal evidence
```

MCP Tasks may later adapt this lifecycle after version-specific ChatGPT validation. A Task ID never replaces `operation_id`.

## 10. Large Results

A Tool returns either:

- a complete bounded inline result; or
- a retained result reference read through `result_get`, `result_page`, or `result_chunk`.

There is no silent truncation. The large-result contract is defined in `mcp-large-results.md`.

## 11. Security Boundary

- Tokens and credentials are transport/authorization context, never ordinary Tool arguments.
- General command execution is separated from the bootstrap catalogue and follows `security/command-execution.md`.
- Untrusted content cannot expand authority or obtain direct credential/network composition.
- Tool metadata is model-facing untrusted data and must match the reviewed manifest.
- `_meta` is not secure storage or an authorization channel.
- Every invocation is independently revalidated against current local policy and state.

## 12. Initial Operational Expansion

After the bootstrap profile passes, V1 may promote focused Tools for:

- device and service inspection;
- filesystem list/read/search/write/patch under configured workspaces;
- isolated command execution;
- Git status/diff and bounded repository operations;
- retained operation status/cancellation/result retrieval.

A Tool is promoted only after its schema, manifest metadata, policy, confinement, lifecycle, idempotency, information, audit, and host-profile tests pass.

## 13. Interface Invariants

1. A visible Tool never grants authority.
2. Tool metadata and runtime implementation must match the reviewed manifest.
3. Every result uses the canonical success/error envelope.
4. Every mutating effect has a pre-effect idempotency identity.
5. Preparation binds state but is not human approval.
6. Host confirmation is a profile-promotion fact, not server-verifiable owner authority.
7. Transport loss does not imply cancellation.
8. Large results are complete inline or recoverable through a retained object.
9. Binnacle never reasons about the owner objective.
