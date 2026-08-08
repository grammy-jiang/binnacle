# Binnacle ChatGPT Host Confirmation Gate

- **Status:** Draft — mandatory HOST-profile promotion contract
- **Related contracts:** `MCP-PROFILE`, `MCP-INTERFACE`, `OP-PREPARE`, `LOCAL-POLICY`, `OP-BOUNDARY`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Capability composition:** [`security/capability-composition.md`](security/capability-composition.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document defines when a Binnacle Tool contract requires the actual ChatGPT host to obtain a fresh owner confirmation before invocation and how that behavior becomes a release and profile-promotion gate.

MCP Tool annotations are advisory metadata. They do not prove that the owner saw or confirmed an operation. Binnacle V1 has no separate approval issuer or Companion and does not claim to receive cryptographic proof of a ChatGPT confirmation.

The governing model is:

- ChatGPT owns the owner-facing confirmation interaction;
- the validated HOST profile supplies evidence that confirmation is shown and cannot be bypassed for the classified Tool contract;
- Binnacle binds consequential execution to an exact prepared operation and independently enforces local policy, state, confinement, interlocks, limits, and safe failure;
- a Tool contract remains unsupported when the actual host cannot satisfy its required confirmation class.

## 2. Trust and Enforcement Boundary

### 2.1 What Binnacle verifies

Binnacle verifies:

- authenticated controller identity and HOST-profile ID;
- Tool and operation-contract version;
- prepared-operation identity, expiry, and one-time or idempotency semantics;
- exact normalized input digest;
- target, privilege, data, destination, credential, resource, persistence, and physical bounds;
- current local policy, device profile, and device state;
- every consequential-boundary predicate;
- operation identity, retry, cancellation, and recovery behavior.

### 2.2 What Binnacle does not verify

Binnacle does not independently verify:

- that ChatGPT displayed a confirmation UI;
- that the owner clicked a particular button;
- that the owner read or understood the displayed text;
- that a model assertion about confirmation is true.

A model-supplied boolean such as `confirmed: true`, a conversation message, Tool annotation, request correlation ID, or interaction-context label is not confirmation evidence.

### 2.3 Supported security claim

A per-invocation confirmation requirement is a HOST-profile assurance, not a new server authority product.

If the validated ChatGPT host is compromised or violates its confirmation contract while retaining the authenticated controller credential, Binnacle's remaining protections are its local policy and operation confinement. V1 must not claim independent human-approval resistance against a compromised trusted host.

## 3. Confirmation Classes

Every Tool contract declares exactly one class.

| Class | Meaning | V1 promotion rule |
| --- | --- | --- |
| `HC0-no-confirmation` | Bounded low-risk operation may be invoked by the authenticated controller without a per-invocation owner prompt | Local policy and all other gates still apply |
| `HC1-per-invocation` | Every new consequential effect requires a fresh, exact host confirmation | Supported only after the actual HOST profile passes the confirmation gate for the exact Tool/contract version |
| `HC2-confirmed-envelope` | Several calls may use one owner-confirmed prepared envelope with exact membership, cumulative limits, validity, and destinations | Deferred from bootstrap V1 unless separately promoted and tested; cannot be simulated by repeated HC1 prompts |
| `HC3-unsupported` | Host confirmation is insufficient or the operation is outside V1 risk scope | Tool is absent or deterministically rejected regardless of host behavior |

Status, evidence retrieval, and cancellation that can only reduce or inspect an existing effect may use `HC0` under a separate bounded contract.

## 4. Initial Classification

### 4.1 `HC0-no-confirmation`

Typical candidates, subject to local policy:

- sanitized connection and compatibility probes;
- bounded system inspection;
- read-only device-profile inspection;
- bounded workspace listing and reading of `normal-result` data;
- Git status and diff without remote communication;
- operation status and result retrieval by the owning controller;
- cancellation requests that cannot create a new effect;
- deterministic cleanup already retained as the protective result of an accepted operation.

A read-only annotation alone does not place a Tool in HC0. Protected-data disclosure, external communication, expensive observation, or physical access may require HC1 or remain unsupported.

### 4.2 `HC1-per-invocation`

The initial policy requires HC1 for any Tool contract that can:

- create, overwrite, patch, move, truncate, or delete files outside the disposable compatibility probe;
- execute an arbitrary or general-purpose command;
- install, remove, or update packages;
- start, stop, restart, enable, disable, or reconfigure a service;
- reboot, shut down, or materially alter host availability;
- change users, permissions, privileges, authentication, policy, audit, or network configuration;
- send data or create effects on an external system;
- use a delegated credential;
- create or change a persistent managed workload;
- update, restart, roll back, or otherwise self-manage Binnacle;
- reserve or actuate hardware or a peripheral;
- disclose a `restricted-result` to a model-visible or external recipient;
- cross another contract-declared high-impact boundary.

A tightly allowlisted formatting, lint, test, or build command may later be classified separately only after the command, filesystem, resource, and no-network contract is frozen and tested.

### 4.3 `HC2-confirmed-envelope`

This class is not part of the initial bootstrap support claim.

A future envelope requires:

- deterministic membership rather than semantic purpose;
- exact maximum effects and cumulative budgets;
- validity and revocation behavior;
- destination and information contracts;
- member classes requiring fresh HC1 confirmation;
- host display and exhaustion behavior;
- server-side durable accounting.

### 4.4 `HC3-unsupported`

Personal V1 classifies as HC3:

- safety-critical physical actuation;
- operations without enforceable confinement or safe-state behavior;
- raw-secret disclosure to general-purpose code;
- generic arbitrary data upload;
- remote control when controller identity or host confirmation behavior is unvalidated;
- any operation whose exact target, effects, or recovery implications cannot be represented to the owner;
- any high-impact Tool for which the actual host can invoke without the required confirmation.

## 5. Owner-Visible Confirmation View

For HC1, the actual host must show an owner-visible view derived from one exact Binnacle prepared operation.

The view includes every applicable field:

- Binnacle server and enrolled Raspberry Pi identity;
- Tool name, title, operation contract, and version;
- prepared-operation identity and expiry;
- exact normalized arguments;
- file paths, service, command, package, Git target, hardware resource, or other subject;
- exact executable, arguments, working directory, and environment authority for command execution;
- privilege and identity used for the effect;
- maximum local, persistent, destructive, physical, and resource effects;
- information classes, sources, transformations, recipients, result surfaces, and byte/item limits;
- requested and effective network destination rules, methods, paths, redirects, proxies, and credentials;
- whether the operation is additive, destructive, idempotent, retryable, or externally uncertain;
- expected observable success and non-success results;
- cancellation and safe-stop behavior;
- rollback or recovery implications;
- retained risks and manual intervention conditions;
- whether one confirmation permits exactly one effect or a declared idempotent reconciliation.

ChatGPT may add an explanation, but the explanation cannot replace, hide, contradict, or broaden the server-derived facts.

## 6. Prepare, Confirm, Execute

### 6.1 Preparation

Before HC1 execution, ChatGPT invokes a no-effect preparation contract.

Binnacle returns:

- `prepared_operation_id`;
- canonical normalized input and digest;
- owner-visible confirmation view and digest;
- contract and policy versions;
- current state and freshness evidence;
- maximum effects and destinations;
- confirmation class;
- expiry;
- required caller idempotency key semantics.

Preparation creates no execution authority and is not proof that the owner confirmed.

### 6.2 Host confirmation

The host must:

- present the exact confirmation view or a verified lossless rendering;
- identify Binnacle as the server origin;
- wait for an explicit owner action;
- make decline, dismissal, timeout, and unavailable UI non-authorization;
- prevent the model from supplying or synthesizing the owner response;
- prevent automatic Tool execution before the response;
- bind the response to the exact view digest;
- avoid bundling unrelated operations into one prompt;
- record the outcome for HOST-profile evidence without exposing secrets.

### 6.3 Execution

The execution request supplies:

- `prepared_operation_id`;
- caller idempotency key where required;
- the exact Tool contract's remaining execution fields, if any.

The owner confirmation is not represented by a model-supplied Tool argument.

Binnacle re-normalizes and verifies the retained preparation and current state. Any material change causes rejection or a fresh preparation and confirmation.

### 6.4 Lost response and retry

A retry of the same admitted operation may reconcile under the same confirmation only when:

- the caller uses the same idempotency key;
- the normalized input and prepared-operation binding are identical;
- the operation contract defines reconciliation;
- no new consequential effect is created.

A new operation identity, changed input, expired preparation, or repeated non-idempotent effect requires a new confirmation.

## 7. HOST Profile Promotion Gate

### 7.1 Profile granularity

Confirmation evidence is bound to:

- ChatGPT product and surface;
- plan and workspace type;
- account or policy configuration;
- connection and authentication profile;
- MCP revision;
- Tool name and contract version;
- Tool annotations and manifest digest;
- test date and host release evidence.

Success on another account, workspace, host, Tool, or contract version is not sufficient.

### 7.2 Required observed behavior

An HC1 contract can be marked supported only when tests prove:

1. the owner sees a confirmation before each new consequential invocation;
2. the view contains every mandatory field;
3. decline, dismiss, timeout, and UI failure create no execution request;
4. changed arguments or target produce a new view and confirmation;
5. the model cannot call the Tool through another route that bypasses the confirmation;
6. automatic retry reconciles only an existing idempotency identity and does not create a second effect;
7. Tasks, MRTR, batching, cached catalogue state, reconnection, and another conversation do not bypass the gate;
8. annotation changes cannot remove the requirement without a new profile result;
9. confirmation fatigue controls do not silently convert repeated prompts into autonomous approval;
10. server-side current policy and prepared-operation validation still block invalid work after confirmation.

### 7.3 Failure result

If the host cannot satisfy the gate:

- the affected Tool contract is not promoted for that HOST profile;
- the visible catalogue should omit it where practical;
- direct invocation is deterministically rejected by local policy as `host_confirmation_unavailable` or equivalent;
- a cached or forged Tool call cannot execute it;
- lower-risk HC0 operations may remain supported;
- the product report identifies whether the blocker is host behavior, plan entitlement, workspace policy, or missing evidence.

## 8. Confirmation Fatigue and Aggregation

The host profile must test and bound:

- repeated identical prompts after decline;
- prompt storms caused by retry or model loops;
- splitting one high-impact action into many low-salience confirmations;
- hiding cumulative effect across sequential operations;
- confirming one operation and executing another;
- default-focused or misleading UI controls;
- confirmation text truncation;
- rapid-fire approval requests;
- automatic timeout selection.

Required behavior:

- a decline is terminal for that prepared operation;
- identical duplicate requests are deduplicated or clearly identified;
- the host rate-limits repeated confirmation presentation;
- cumulative effects are shown when a contract permits related operations;
- one HC1 confirmation covers one prepared effect only;
- grouping requires a separately promoted HC2 envelope;
- no prompt is treated as approved by inactivity.

## 9. Local Controls Remain Independent

Host confirmation never bypasses:

- controller authentication;
- local path and target policy;
- command sandboxing;
- capability-composition rules;
- information and egress contracts;
- credential audience restrictions;
- hardware reservations and interlocks;
- resource ceilings;
- consequential-boundary revalidation;
- cancellation and safe-state rules;
- audit and evidence requirements.

An operation can be confirmed and still be rejected by Binnacle.

## 10. Validation Fixtures

The machine-readable confirmation classes and cases are:

```text
spec/policy/host-confirmation-classes.yaml
tests/fixtures/mcp/host-confirmation.yaml
```

The real-host cases must be executed against the actual ChatGPT account and workspace. A mocked UI cannot establish the HOST profile, although it may test Binnacle preparation and execution bindings.

## 11. Evidence and Regression

The compatibility report records:

- confirmation class;
- Tool and contract version;
- manifest digest;
- prepared view digest;
- exact fields shown;
- owner action and whether a Tool call followed;
- Tool arguments observed;
- timing and retries;
- host/account/workspace profile;
- pass/fail oracle and evidence link;
- limitations and product disposition.

The gate reopens after a material change to:

- ChatGPT product or confirmation behavior;
- account plan or workspace policy;
- MCP revision;
- Tool metadata, annotations, schema, or contract;
- authentication path;
- prepared-operation view;
- Binnacle build or manifest;
- any test that previously established non-bypassability.

## 12. Source Basis

MCP annotations are hints for clients and are not enforcement. The protocol recommends human confirmation for sensitive operations but does not guarantee one particular host UI. Binnacle therefore treats confirmation as an empirical ChatGPT HOST-profile requirement while retaining deterministic server-side policy and confinement.