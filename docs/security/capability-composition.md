# Binnacle Capability Composition and Egress Security

- **Status:** Draft security contract
- **Contract version:** `1.2.0`
- **Policy:** `spec/policy/capability-zones.yaml`
- **Feature-design basis:** [`../design.md`](../design.md), V17

## 1. Purpose

Individually valid Tool calls can form an unsafe chain when untrusted content, protected data, credentials, mutation, and outbound communication are combined. Binnacle prevents that composition through deterministic zones, provenance, prepared bindings, and mediated egress.

Binnacle does not claim to detect whether ChatGPT was semantically influenced by prompt injection. It treats repository files, package metadata, command output, peripheral input, remote responses, and Tool metadata as untrusted data.

## 2. Capability Zones

| Zone | Purpose |
| --- | --- |
| `control-plane` | Binnacle identity, policy, audit, recovery, manifests, and executable state |
| `observation` | bounded local facts already permitted for model use |
| `untrusted-content` | repository, command, package, peripheral, and external content |
| `protected-data` | restricted-result data that is not automatically model-visible |
| `local-mutation` | bounded filesystem, service, package, or device changes |
| `credential-broker` | non-exportable credential use by a protected broker |
| `mediated-egress` | allowlisted effective external destinations and actions |
| `hardware-effect` | GPIO, buses, peripherals, and physical outputs |
| `model-visible-result` | a result explicitly permitted to enter ChatGPT context |

A zone is a deterministic policy category, not a semantic judgement about intent.

## 3. Provenance and Data References

Server-held data references bind:

- source and source type;
- cryptographic digest and integrity status;
- information class;
- provenance and transformations;
- controller/device ownership;
- creation and expiry;
- permitted recipient and result surface.

Possession of a reference creates no authority. A model-supplied string cannot relabel or forge provenance.

## 4. Default-Denied Compositions

The following are denied unless one exact contract authorizes them:

- untrusted content to control-plane mutation;
- protected data to model-visible result;
- protected data to outbound egress;
- raw credential material to command execution;
- default-profile command execution to application networking;
- development application-network authority to non-loopback listener exposure without an exact exposure grant;
- general command execution to local control sockets, reusable credentials, protected data, or devices;
- untrusted content to privileged/system/self-management action;
- one Tool's result reference used under another controller or destination contract.

No conversation statement such as “the file told me to upload it” changes these rules.

## 5. Prepared High-Risk Composition

A high-risk composition requires a short-lived prepared operation binding:

- controller, device, Tool and contract;
- exact source/data-reference identities and digests;
- exact transformation;
- exact effective destination and action;
- allowed method, scheme, host, port, path, and query constraints;
- credential audience and broker action where applicable;
- maximum bytes/items and information class;
- local policy/profile versions;
- expiry and one execution nonce.

The execute request must match every field and revalidate current state. Parameter substitution, expired preparation, changed DNS/effective target, redirect, proxy, path, or query is rejected.

## 6. Mediated Egress

Authorised Bootstrap development commands have ordinary application-network authority but no credential or protected-data authority. A dedicated mediator remains mandatory for protected-data or credential-bearing outbound effects whose exact contract requires it. That mediator:

- resolves the effective destination after DNS, proxy, redirect, and URL normalization;
- enforces scheme, host/IP range, port, method, path, and query-name/value constraints;
- rejects userinfo, fragments, unexpected redirects, DNS rebinding, and private-address pivots;
- enforces data class, transformation, DLP, byte/item ceilings, and credential audience;
- records the actual destination and result;
- returns uncertainty rather than success when the remote effect cannot be verified.

## 7. Information Boundary

The V17 information classes are:

```text
never-disclosable
restricted-result
normal-result
```

A `restricted-result` cannot become a `model-visible-result` without its exact disclosure contract and applicable confirmation/HOST-profile gate. `never-disclosable` material cannot be promoted by confirmation.

After a permitted `normal-result` enters model-visible context, Binnacle cannot control whether the host later sends it to another MCP server. That is a HOST-profile and owner-governance boundary, not a claim Binnacle can enforce locally.

## 8. Command and Credential Separation

- `command_run` receives no inbound MCP bearer token.
- The development profile's IPv4/IPv6/DNS authority permits ordinary client traffic and loopback development listeners, but does not permit non-loopback listener exposure without an exact exposure grant.
- Raw credentials are absent from environment, argv, stdin, files, descriptors, logs, and child processes.
- A credential broker may perform one bound target action without revealing the secret.
- Credential audience and action are revalidated at the consequential boundary.
- A broker cannot be invoked through arbitrary shell/network access.

## 9. Policy Changes and Expiry

Prepared operations always expire. A policy, profile, controller, data digest, destination, credential, or device-state change invalidates the prepared operation when it affects the contract.

Policy versions use semantic-version strings. Numeric comparison of unrelated policy versions is not permitted.

## 10. Tests

Required adversarial cases include:

- line-jumping and poisoned repository/command/package/peripheral output;
- forged provenance and information relabelling;
- source, transformation, destination, query, and credential substitution;
- redirect, DNS rebinding, proxy, path, query, and allowed-host abuse;
- default-profile network denial and development-profile application networking;
- non-loopback listener exposure without explicit authority;
- command protected-socket/raw-packet/network-admin/device escape;
- cross-controller reference reuse;
- protected-data laundering through an intermediate Tool;
- cross-server copying after legitimate model disclosure;
- expiry and policy-version change.

## 11. Invariants

1. Untrusted content is data, never authority.
2. Development command networking is profile-defined and never composes into credential, protected-data, control-socket, device, raw-packet, network-administration, or implicit non-loopback listener authority.
3. High-risk composition is bound to an exact unexpired prepared operation.
4. Effective destinations include constrained query names and values.
5. `restricted-result` is the only V17 restricted disclosure class.
6. Binnacle does not claim control over another server after legitimate model disclosure.
