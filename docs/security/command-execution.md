# Binnacle Command Execution Isolation

- **Status:** Draft — mandatory security contract for `command_run`
- **Related contracts:** `MCP-INTERFACE`, `LOCAL-POLICY`, `OP-PREPARE`, `OP-LIFECYCLE`, `OP-BOUNDARY`, `INFO-BOUNDARY`
- **Feature-design basis:** [`../design.md`](../design.md), V17
- **Composition boundary:** [`capability-composition.md`](capability-composition.md)
- **Host confirmation:** [`../mcp-host-confirmation.md`](../mcp-host-confirmation.md)
- **Last review:** 2026-08-08

## 1. Purpose

This document freezes the minimum isolation and acceptance boundary for Binnacle's general-purpose `command_run` capability.

A working-directory check, shell quoting, container label, dedicated Unix user, or timeout alone is not sufficient. A command and every descendant must remain inside a kernel-enforced filesystem, privilege, process, resource, network, device, descriptor, credential, and cleanup boundary.

If a device profile cannot prove the complete required boundary, `command_run` is unsupported on that profile.

## 2. Security Architecture Boundary

### 2.1 Separation of responsibilities

Command execution uses at least three distinct roles:

1. **Binnacle MCP server and policy engine**
   - authenticates the controller;
   - prepares and validates the exact command specification;
   - applies local policy and host-confirmation gates;
   - creates the durable Binnacle operation;
   - never executes the requested program in the server process.

2. **Narrow execution broker or supervisor**
   - accepts only a validated, single-operation execution ticket over a protected local interface;
   - constructs the sandbox and resource boundary;
   - starts, observes, signals, and cleans the isolated executor;
   - exposes no general shell, file, network, device, policy, or credential API;
   - uses only the minimum privilege required to create the selected platform boundary.

3. **Unprivileged executor**
   - runs the requested executable and descendants;
   - has a dedicated non-Binnacle UID/GID or an equivalently isolated identity;
   - cannot call the broker interface or read its authentication material;
   - cannot access the Binnacle server's memory, descriptors, environment, sockets, policy, operations, audit, credentials, executable state, or recovery files.

The broker and executor must be separate operating-system processes. Thread separation in one address space is insufficient.

### 2.2 Local execution ticket

The MCP server issues the broker a protected, single-operation ticket bound to:

- `operation_id`;
- authenticated `controller_id`;
- command-profile identity and version;
- executable and argument digest;
- workspace identity and mount plan digest;
- environment and descriptor plan digest;
- network, device, credential, and syscall policy digests;
- resource limits;
- timeout and cancellation behavior;
- information and output limits;
- local policy and device-profile versions;
- creation time, expiry, and one-time broker admission identity.

The executor cannot mint or modify a ticket. The broker rejects reuse, expiry, digest mismatch, unsupported profile, and a ticket targeting another Binnacle instance.

The ticket is local control-plane material and is never model-visible, passed in the child environment, or written into the workspace.

## 3. `command_run` Input Contract

The default command request uses structured execution fields:

```text
executable
argv[]
workspace_ref
working_directory
explicit_environment{}
stdin_ref or bounded inline stdin
wall_timeout
stdout_limit
stderr_limit
caller_idempotency_key
```

Rules:

- `argv` is an array and is passed without shell interpolation;
- Binnacle does not concatenate arguments into a shell command;
- shell metacharacters have no special meaning;
- the executable is resolved under the command profile, not through an attacker-controlled current directory;
- `PATH` is fixed by the profile or the executable path is exact;
- a script interpreter is an executable and the script is an exact prepared input;
- `sh -c`, `bash -c`, command substitution, pipelines, redirection, and other shell-language execution are outside the default V1 contract;
- a future shell Tool requires a separate name, contract, confirmation class, sandbox review, and tests;
- working directory and all file inputs are relative to a validated workspace reference;
- environment keys and values are closed and size-bounded;
- stdin is size-bounded and classified as data, never authority.

`command_run` is `HC1-per-invocation` until a narrower frozen allowlisted command contract is separately promoted.

## 4. Workspace and Filesystem Boundary

### 4.1 Workspace identity

A workspace is not trusted from a model-supplied path string.

Before preparation and again before sandbox construction, Binnacle must establish:

- owner-configured workspace identity;
- canonical absolute root;
- root file type;
- filesystem, mount, device, and stable object identity as applicable;
- absence of an unapproved symbolic-link or mount indirection;
- permitted read/write subtrees;
- maximum crossing into nested mounts;
- current policy and profile version.

Ambiguity, path disappearance, replacement, mount change, symlink race, bind-mount change, or inability to prove containment blocks execution.

### 4.2 Sandbox filesystem view

The executor receives a constructed filesystem view containing only:

- a minimal runtime and required executable/library set, read-only;
- the approved workspace at its declared read/write mode;
- an operation-private temporary filesystem with size limit;
- minimal synthetic `/etc` data required by the executable, without host secrets;
- a restricted process filesystem when required and proven safe;
- minimal safe pseudo-devices explicitly allowed by the profile.

The executor must not see or reach:

- the host root filesystem;
- `/root`, owner home directories, SSH or cloud credentials;
- Binnacle source, executable, configuration, policy, operation database, audit, recovery, keys, or sockets unless the exact workspace intentionally contains source under a self-development profile and the control-plane installation remains separate;
- host `/run`, system bus, Docker/container runtime sockets, SSH agent, package-manager credential sockets, or desktop/session buses;
- host `/proc` objects outside the isolated process view;
- `/sys`, firmware, boot partitions, block devices, GPIO, I²C, SPI, UART, cameras, input devices, FUSE, or other devices unless a separate non-general-purpose operation contract exposes them;
- arbitrary host mounts or network filesystems not included in the profile.

`chroot` or a changed working directory without mount, descriptor, and privilege isolation does not satisfy this contract.

### 4.3 Path operations inside the executor

The sandbox must prevent escape through:

- absolute paths;
- `..` traversal;
- symbolic links;
- hard links to objects outside the allowed view;
- `/proc/self/fd` and inherited file descriptors;
- `/proc/<pid>/root` or process-memory access;
- mount, bind mount, pivot, namespace, or root changes;
- race-time replacement of validated paths;
- device nodes and special files;
- filesystem magic links;
- case, Unicode, or normalization confusion where the filesystem is affected.

Workspace effect evidence must be collected from the sandbox's actual view, not reconstructed only from requested paths.

## 5. Execution Identity and Privilege

The executor must run with:

- a dedicated unprivileged identity distinct from Binnacle and the owner login;
- no supplementary groups except an explicit sandbox group with no unrelated access;
- no Linux capabilities in the executor's effective, permitted, inheritable, ambient, or bounding sets;
- `no_new_privs` or an equivalent kernel guarantee;
- no setuid or setgid privilege gain;
- no `sudo`, `su`, PolicyKit, systemd management, container runtime, or host session authority;
- a restrictive umask;
- no ability to change UID/GID to a more privileged identity;
- a mandatory-access-control profile or equivalent platform policy when the validated Linux profile relies on one;
- a syscall policy appropriate to the architecture and command profile.

A command that requires host privilege is not run by relaxing `command_run`. It requires a dedicated outcome-oriented operation and narrowly authorized broker action.

## 6. Environment and Descriptor Hygiene

### 6.1 Environment

The executor environment is created from an empty base plus an allowlist.

It must not inherit:

- access or refresh tokens;
- authentication headers;
- private keys or passwords;
- `SSH_AUTH_SOCK`;
- proxy variables unless the profile explicitly permits mediated egress, which general `command_run` does not;
- cloud, Git, package, database, CI, or deployment credentials;
- Binnacle policy or broker secrets;
- systemd, D-Bus, desktop, Wayland/X11, container-runtime, or keyring endpoints;
- owner shell startup variables;
- Python, Node, Ruby, Perl, Java, dynamic-loader, or plugin variables that inject unreviewed code;
- host `HOME`, `XDG_*`, or temporary directories.

The profile defines safe values for `HOME`, `PATH`, locale, timezone, `TMPDIR`, and language/runtime cache directories inside the sandbox.

### 6.2 File descriptors

Before execution, the broker closes every inherited descriptor except explicitly created standard streams and reviewed operation-specific descriptors.

The executor must not inherit:

- MCP or HTTP sockets;
- listening sockets;
- tunnel/gateway connections;
- policy, database, audit, log, credential, or key files;
- directory descriptors outside the sandbox;
- Binnacle operation pipes or event descriptors;
- hardware handles;
- pidfds or process handles for host processes;
- anonymous memory or shared-memory objects containing protected data.

The broker verifies the child descriptor set where the platform permits it. An unknown inherited descriptor blocks profile promotion.

## 7. Network, IPC, and Device Boundary

### 7.1 Network default

General `command_run` has no network authority.

The executor and descendants must be unable to use:

- IPv4 or IPv6 sockets;
- DNS;
- loopback services;
- raw or packet sockets;
- Netlink or route-management interfaces except a profile-proven harmless requirement;
- Bluetooth, CAN, NFC, or other network families;
- a host or tunnel interface;
- a proxy inherited through environment or configuration;
- network namespaces or routing changes.

A dedicated outcome-oriented Tool and egress mediator perform reviewed network actions outside this sandbox.

### 7.2 Local IPC

The executor must not reach host Unix sockets, abstract sockets, named pipes, message queues, shared-memory objects, or service buses.

Operation-private IPC among descendants may be permitted inside the sandbox when it cannot reach host endpoints and remains within resource limits.

### 7.3 Devices

The executor receives no general device access.

A minimal profile may expose only pseudo-devices such as `/dev/null`, `/dev/zero`, and a safe randomness source. It must deny block devices, TTYs, GPIO, bus devices, cameras, GPUs, input devices, sound, FUSE, KVM, TPM, watchdogs, and host-specific hardware.

Hardware work uses dedicated Tools with separate reservations and safety contracts.

## 8. Syscall and Kernel Attack Surface

The validated command profile must use a syscall allowlist or an equivalently strong policy. It must block executor use of operations capable of escaping or materially inspecting the host, including applicable forms of:

- mount, unmount, pivot-root, chroot, and filesystem namespace changes;
- `setns`, unapproved `unshare`, and namespace creation;
- `ptrace`, process-memory access, and cross-process inspection;
- `bpf`, performance-event access, kernel module operations, and kernel keyrings;
- reboot, kexec, swap management, hostname/domain changes, and system time changes;
- device-node creation and privileged I/O;
- capability and securebits changes;
- arbitrary `io_uring`, userfault, fanotify, or other interfaces not proven necessary and safe for the profile;
- creation of network or host IPC sockets;
- movement into another cgroup or escape from the assigned resource group.

The exact allowlist is architecture- and executable-profile-specific and is frozen by implementation security review. A denylist alone is insufficient when unknown syscalls or architecture variants remain available.

## 9. Descendant-Wide Resource Boundary

Every process, thread, child, grandchild, re-parented process, daemon, and helper created by the operation remains in one operation-owned resource and cleanup domain.

The profile enforces descendant-wide limits for:

- CPU quota and total CPU time;
- wall-clock duration;
- memory and swap;
- process and thread count;
- open files and descriptors;
- output bytes;
- file size and temporary storage;
- workspace growth where applicable;
- I/O throughput and total I/O where supported;
- core dumps, which are disabled or retained only through a separate protected diagnostic contract;
- priority and scheduler policy.

Limits must be kernel-enforced where a kernel facility exists. Parent-only monitoring without descendant enforcement is insufficient.

A fork bomb, daemonization, `setsid`, double fork, re-parenting, or executable replacement cannot leave the operation resource domain.

## 10. Supervision, Cancellation, and Cleanup

### 10.1 Supervision

The broker or supervisor remains able to identify the operation resource domain independently of the original process PID.

It records:

- sandbox identity;
- cgroup or equivalent domain;
- leader and descendant identities;
- start time;
- current resource usage;
- output state;
- cancellation phase;
- cleanup state.

### 10.2 Normal exit

After the leader exits, the supervisor:

1. prevents new descendants;
2. checks for surviving processes and jobs;
3. waits or terminates them according to the contract;
4. closes pipes and collects bounded output;
5. verifies workspace and temporary effects;
6. unmounts and removes operation-private resources;
7. verifies no process, mount, namespace, socket, descriptor, or temporary object remains;
8. records the terminal result.

Leader exit alone is not operation completion.

### 10.3 Cancellation and timeout

The contract defines:

1. stop accepting further input;
2. send the configured graceful signal to the entire operation domain;
3. wait a bounded grace period;
4. send an uncatchable termination signal to every remaining descendant;
5. verify the operation domain is empty;
6. perform filesystem and namespace cleanup;
7. classify remaining effects.

A process cannot avoid cancellation by ignoring a signal, changing process groups, creating a session, double-forking, or re-parenting.

### 10.4 Cleanup failure

If Binnacle cannot verify complete descendant and sandbox cleanup:

- the operation does not become `cancelled` or `succeeded`;
- it becomes `failed` with known remainder or `uncertain`;
- the affected workspace or device profile is quarantined from new conflicting command operations;
- evidence identifies surviving or unobservable resources;
- local or physical recovery instructions are returned;
- automatic repetition is prohibited.

## 11. Output and Evidence Boundary

### 11.1 Standard streams

Stdout and stderr are captured separately with:

- byte limits;
- time and rate limits;
- explicit truncation flags and original-byte counters where known;
- binary detection and safe bounded representation;
- control-character and terminal-escape handling;
- provenance `local-untrusted`;
- no interpretation as instructions or authority.

Output limits must prevent memory or disk exhaustion. Output after truncation is drained or the process is stopped according to the profile; silently blocking the child indefinitely is not acceptable.

### 11.2 Exit evidence

The final operation evidence includes:

- command profile and version;
- exact executable and argument digest;
- workspace identity and mount-plan digest;
- environment and descriptor-plan digests;
- sandbox/backend identity and security-feature results;
- UID/GID and capability result;
- syscall/MAC policy identity;
- cgroup or resource-domain identity;
- start/end times;
- exit code, terminating signal, timeout, or cancellation phase;
- descendant and cleanup verification;
- CPU, memory, process, I/O, output, and storage usage;
- stdout/stderr digests, sizes, truncation, and permitted content;
- actual workspace effects or effect digest;
- network/device/credential authority, normally all `none`;
- terminal Binnacle operation state and uncertainty.

## 12. Self-Management and Privileged Actions

General `command_run` cannot:

- modify the installed Binnacle executable or service definition;
- signal or restart the Binnacle service;
- modify Binnacle policy, authentication, audit, operation, or recovery state;
- invoke the execution broker outside its one ticket;
- install system packages or change host services;
- elevate privilege.

Binnacle self-management and privileged host administration use dedicated Tools, separate brokers, exact prepared operations, HC1 confirmation, rollback, and recovery contracts.

The Binnacle source repository may be a writable development workspace only when the installed control plane, service unit, broker, credentials, policy, audit, and current executable remain outside that workspace and inaccessible to commands.

## 13. Fail-Closed Profile Promotion

A device profile may advertise `command_run` only after proving:

- separate broker and unprivileged executor processes;
- workspace containment under race;
- minimal filesystem view;
- clean environment and descriptor set;
- no network or host IPC;
- no device access beyond the exact pseudo-device list;
- no privilege gain;
- syscall and MAC confinement;
- descendant-wide resource control;
- reliable cancellation and cleanup;
- bounded output;
- actionable evidence;
- protected Binnacle control plane;
- actual kernel and architecture compatibility.

If one mandatory mechanism is unavailable, disabled, untestable, or fails after update, `command_run` enters restricted operation. It must not silently fall back to direct subprocess execution.

## 14. Validation Fixtures

The profile and adversarial cases are:

```text
spec/policy/command-profiles.yaml
tests/fixtures/security/command-isolation.yaml
```

Tests must run on every claimed Raspberry Pi OS/kernel/architecture profile. Mock-only tests do not establish containment.

Required cases include:

- workspace symlink, hard-link, mount, descriptor, and rename races;
- host root, process, home, control-plane, audit, and credential reads;
- inherited file descriptors, environment, and sockets;
- Unix, IPv4, IPv6, DNS, proxy, and local-service access;
- device and special-file access;
- setuid, capabilities, namespace, mount, ptrace, BPF, keyring, and syscall escape;
- fork bomb, process-tree escape, daemonization, and cgroup migration;
- CPU, memory, swap, file, descriptor, I/O, output, process, and timeout exhaustion;
- graceful and forced cancellation;
- surviving descendant and cleanup failure;
- stdout/stderr binary, escape, and flood behavior;
- broker-ticket replay, mismatch, and executor access;
- Binnacle self-management attempts;
- fail-closed behavior when a required kernel control is absent.

## 15. Technology Neutrality

This feature/security contract does not select a container engine, sandbox library, service manager, or programming language.

A Linux implementation may use namespaces, cgroups v2, seccomp, Landlock, AppArmor, SELinux, systemd sandboxing, capability controls, pidfds, dedicated users, or other mechanisms. Architecture must demonstrate that the selected combination satisfies every property and test above.

Brand names, container labels, or configuration claims are not evidence without the adversarial test results.