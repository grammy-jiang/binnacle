# Binnacle Command Execution Isolation

- **Status:** Draft security contract
- **Contract version:** `1.2.0`
- **Policy:** `spec/policy/command-profiles.yaml`
- **Feature-design basis:** [`../design.md`](../design.md), V17

## 1. Purpose

`command_run` is a controlled general-purpose primitive for software engineering and diagnosis. It is not a direct subprocess wrapper and never inherits Binnacle's control-plane privilege.

Bootstrap support requires the independent unprivileged executor boundary, explicit workspace and resource controls, process-tree supervision, and exclusion of credentials, protected control-plane IPC, device authority, and network-administration privilege described below. Advanced namespace, seccomp, and mandatory-access-control hardening remains target work and is promoted only when the selected Raspberry Pi/Linux profile proves it; it is not a Bootstrap support prerequisite.

## 2. Process Separation

The implementation has three logical boundaries:

1. **Binnacle policy process** — authenticates, normalizes, authorizes, prepares, and records the operation.
2. **Narrow execution broker** — validates one signed/local execution ticket and creates the sandbox.
3. **Unprivileged executor** — runs the exact executable/argv/input inside the sandbox.

The executor cannot call back into a general privileged broker API. The broker accepts only one single-use ticket for one operation.

## 3. Execution Ticket

The ticket binds:

- ticket and operation identity;
- controller and device identity;
- command-profile identity;
- executable identity and structured argv digest;
- inline stdin digest, server-held stdin-reference digest, and exact workspace-script digest where applicable;
- workspace-root identity;
- mount, environment, policy, resource, and sandbox-plan digests;
- aggregate writable-workspace byte and inode limits;
- expiry, admission-record identity, and single-use nonce.

The broker revalidates every input digest at admission. A changed script, stdin, data reference, mount, environment, policy, or workspace identity invalidates the ticket.

Structured argv execution is the default. Shell interpolation requires a separately named contract and is not implied by `command_run`.

## 4. Filesystem Boundary

The executor receives the minimum filesystem view:

- one canonical workspace root;
- explicitly declared read-only system files required by the profile;
- a private temporary filesystem;
- no Binnacle control-plane, identity, policy, credential, audit, recovery, release, or executable state;
- no host mounts or arbitrary device nodes.

Path resolution fails closed on symlink, bind-mount, mount-namespace, hard-link, rename, or other race ambiguity.

Writable workspace limits include both:

- per-file size;
- aggregate bytes written/allocated and aggregate inode/file count for the full descendant tree.

A per-file limit alone is not a sufficient workspace quota.

## 5. Environment, Descriptors, and IPC

The executor receives an allowlisted environment and no inherited secrets. Binnacle closes or explicitly maps every file descriptor.

The executor has no access to:

- Binnacle or system-management Unix sockets;
- inherited network sockets;
- credential agents or keyrings;
- host D-Bus or container-engine sockets;
- ptrace targets outside its sandbox;
- BPF, kernel keyring, or arbitrary namespace-management authority.

## 6. Network and Devices

Command profiles that do not explicitly opt in to networking default to:

```text
network: denied
devices: denied
raw credentials: denied
credential helpers: denied
```

The authorised `workspace-general-v1` development profile, inherited by `workspace-check-v1`, explicitly permits ordinary IPv4, IPv6, and DNS application networking needed for software engineering. Development servers bind to loopback by default. Binding to `0.0.0.0`, `::`, a LAN address, or another non-loopback interface requires a separate explicit exposure request and authority; application-network permission alone is insufficient.

Ordinary application networking does not grant raw-packet or network-administration capability, protected Unix/control sockets, inherited sockets, reusable credentials, credential helpers or agents, protected Binnacle data, or device access. Dedicated mediated egress remains the path for protected-data and credential-bearing effects whose exact contracts require it. Hardware access remains separately promoted. `command_run` cannot acquire any of those authorities through argv, environment, child processes, local sockets, or inherited descriptors.

## 7. Privilege and Kernel Controls

The Bootstrap profile must prove:

- a dedicated unprivileged execution identity;
- no-new-privileges;
- no ambient or inheritable capabilities;
- no setuid/setgid privilege gain;
- process-tree containment and descendant-wide controls;
- inability to use namespace facilities to gain privilege or protected authority;
- bounded `/proc` visibility and ptrace behavior.

The contract states properties, not a mandatory container engine. systemd/cgroups and the independent execution identity establish the Bootstrap boundary. Namespaces, seccomp, Landlock, AppArmor, SELinux, and equivalent controls are target hardening mechanisms that may be promoted when real-device evidence proves them; their absence does not authorize a direct-subprocess fallback or weaken the permanent authority exclusions.

## 8. Descendant-Wide Resources

Limits apply to the entire descendant tree:

- CPU time and scheduling budget;
- memory and swap;
- process/PID count;
- open files and file size;
- aggregate writable-workspace bytes and inodes;
- private temporary storage;
- stdout/stderr and retained-result bytes;
- wall-clock deadline.

Forking, daemonizing, double-forking, or changing process groups cannot escape accounting or cleanup.

## 9. Cancellation and Cleanup

Cancellation is cooperative first and forced after the declared grace period. Binnacle verifies:

- all descendants stopped or are accounted as unable to stop;
- mounts and namespaces removed;
- temporary resources released or quarantined;
- output finalized consistently;
- remaining effects and workspace changes recorded.

Cleanup failure yields `failed` or `uncertain`; it is never reported as verified cancellation.

## 10. Profile Separation

- `workspace-general-v1` permits bounded workspace commands under full isolation.
- `workspace-check-v1` narrows executable set and resources; it does not redefine network/device fields with ambiguous scalar aliases.
- `self-management` sets `command_run_visible: false` and `command_run_allowed: false`. Binnacle self-management uses dedicated staged Tools and rollback contracts.

## 11. Tests

Required cases include:

- host/control-plane/credential/audit reads;
- symlink, mount, hard-link, and rename races;
- inherited file descriptors and local sockets;
- default-profile IPv4, IPv6, DNS, Unix-socket, proxy, and listener denial;
- development-profile IPv4, IPv6, DNS, and loopback-listener permission;
- non-loopback listener denial without explicit exposure authority;
- raw-packet/network-administration, protected-socket, and credential-agent denial;
- device nodes, capabilities, setuid, namespaces, ptrace, BPF, and keyring;
- child, grandchild, fork-bomb, daemon, output-flood, and storage-exhaustion cases;
- per-file and aggregate workspace quota enforcement;
- inline stdin, data-reference, and script digest substitution;
- cancellation and cleanup failures;
- execution-ticket replay and expiry;
- attempted Binnacle self-management.

## 12. Invariants

1. There is no direct-subprocess fallback.
2. Every command uses one exact single-use ticket.
3. Ticket identity includes every executable input and its digest.
4. Writable workspace growth is bounded in aggregate, not only per file.
5. Networking is fail-closed by default; authorised development profiles explicitly permit ordinary application networking without granting credentials, devices, protected control sockets, raw packets, network administration, or non-loopback listener exposure.
6. Limits and cleanup cover the complete descendant tree.
7. Missing or untestable Bootstrap isolation keeps `command_run` unsupported; unpromoted advanced hardening alone does not block Bootstrap support.
