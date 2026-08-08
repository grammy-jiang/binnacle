# Binnacle ChatGPT Host Confirmation Profile

- **Status:** Draft HOST-profile contract
- **Contract version:** `1.1.0`
- **Feature-design basis:** [`design.md`](design.md), V17
- **Policy:** `spec/policy/host-confirmation-classes.yaml`

## 1. Scope

This contract classifies the owner-facing confirmation behaviour that the actual ChatGPT product/account/workspace must demonstrate before a Binnacle Tool is promoted for that HOST profile.

It does **not** create a new Binnacle authority source. V17 remains authoritative:

- Binnacle authorizes through authenticated controller identity, local policy, operation contract, explicit input, and current verified state;
- Binnacle cannot cryptographically attest that the owner clicked a ChatGPT control;
- a model message, Tool annotation, conversation claim, or confirmation prose cannot expand local authority;
- a high-impact Tool remains unsupported for a HOST profile when the required interaction cannot be demonstrated.

## 2. Confirmation Classes

| Class | HOST-profile requirement | Server-enforced requirements |
| --- | --- | --- |
| `HC0` | No per-invocation confirmation required | Authentication, schema, policy, state, information, resource, and audit checks |
| `HC1` | Exact per-invocation confirmation of a prepared bounded effect | HC0 plus exact preparation, expiry, idempotency, and no-substitution checks |
| `HC2` | HC1 plus privileged/destructive/external/credential/recovery implications | HC1 plus stronger confinement, destination, credential, recovery, and audit controls |
| `HC3` | HC2 plus physical or safety-relevant facts and independent interlocks | HC2 plus validated hardware profile, interlocks, safe-state, and emergency boundary |

A Tool contract has one class in the reviewed manifest. The host cannot lower it. The server cannot infer a stronger owner decision from ordinary model text.

## 3. HC0

HC0 is appropriate only for bounded observations, synthetic no-effect probes, and sanitized normal-result evidence whose disclosure is already permitted by local policy.

`compatibility_report` is HC0 because its versioned output is sanitized and classified `normal-result`. A report containing restricted or owner-only payload would require a different Tool contract and confirmation/information treatment.

## 4. HC1 Prepared Invocation

Before an HC1 execute Tool is callable, ChatGPT first calls the corresponding no-effect preparation Tool. The preparation result identifies:

- device and Tool contract;
- exact normalized arguments and targets;
- maximum effect;
- data destination where relevant;
- recovery/cancellation implications;
- `prepared_operation_id` and one execution nonce;
- expiry and current-state digest.

The actual host confirmation must present the exact prepared view. The execute request must match it byte-for-byte under the normalization contract.

Preparation is not owner authority. It prevents argument substitution and stale execution while local policy remains authoritative.

## 5. HC2 and HC3

HC2 applies to operations that may:

- require elevated privilege;
- delete or replace non-disposable state;
- affect an external system or disclose a restricted result;
- invoke non-exportable credentials;
- change Binnacle code/configuration/service state;
- materially affect recovery or audit availability.

HC3 applies to non-safety-critical hardware effects only when the profile still requires owner-visible physical facts, verified interlocks, or an emergency safe state. Safety-critical remote actuation remains outside V1.

## 6. Required Host Presentation

For HC1–HC3, the actual host must show before execution:

- Binnacle device identity;
- Tool name and contract version;
- exact normalized target and material arguments;
- maximum local, external, data, privilege, and physical effects;
- information class and destination/recipient;
- preparation expiry;
- rollback, cancellation, uncertainty, and recovery implications;
- whether the request is one operation or a deliberately grouped finite set.

Approval of one prepared invocation cannot be reused for a different Tool, device, path, content digest, destination, privilege, or operation identity.

## 7. Non-Bypassability Test

The HOST profile passes only when tests demonstrate that the same effect cannot be invoked through:

- a direct Tool call that skips the required host interaction;
- stale cached metadata;
- changed arguments after confirmation;
- batch/group substitution;
- an MCP Task, MRTR retry, reconnect, or another conversation route;
- repeated “approve” prompts that obscure distinct effects.

This is empirical profile evidence, not a cryptographic server proof. A compromised host remains a residual risk; Binnacle's local controls continue to limit maximum effect.

## 8. Grouping and Fatigue

A host may group only a finite set whose complete normalized members, aggregate maximum effect, destinations, and recovery implications are shown together. Open-ended “approve future commands” confirmation is not a V1 host-confirmation contract.

The evaluation records decline, dismissal, timeout, duplicate prompts, repeated near-identical operations, and whether distinct effects remain distinguishable.

## 9. Retry and Lost Responses

A lost response does not require a new effect or silently reuse a UI decision. The retry uses the same idempotency identity and exact prepared input:

- same key/input returns the retained operation;
- same key/different input is rejected;
- an expired preparation cannot create a new effect;
- an uncertain result requires status/reconciliation, not automatic execution retry.

## 10. Initial Classification

| Tool | Class | Rationale |
| --- | --- | --- |
| `binnacle_probe` | HC0 | bounded normal-result observation |
| `system_inspect` | HC0 | bounded normal-result observation |
| `probe_result_formats` | HC0 | synthetic no-effect probe |
| `probe_error` | HC0 | synthetic no-effect/error probe |
| `compatibility_report` | HC0 | sanitized normal-result evidence |
| `probe_workspace_prepare` | HC0 | no-effect state binding |
| `probe_workspace_write` | HC1 | one disposable bounded write |
| `probe_workspace_cleanup` | HC1 | one exact disposable deletion |

Future operational filesystem, command, service, network, credential, self-management, and hardware Tools receive explicit classes during promotion.

## 11. Invariants

1. Host confirmation never substitutes for local policy or authentication.
2. Preparation identifiers are server-minted state bindings, not owner authority.
3. HC1–HC3 contracts remain unsupported until the actual HOST profile passes the required interaction tests.
4. Confirmation is bound to one exact prepared invocation or finite explicit group.
5. Retry reconciliation cannot create a second effect.
6. Restricted-result disclosure is not HC0 unless the contract is changed to a sanitized normal-result projection.
