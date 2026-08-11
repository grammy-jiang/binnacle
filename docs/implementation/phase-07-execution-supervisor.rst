Binnacle Phase 7 Detailed Implementation Plan
=============================================

:Phase: 7 -- Implement durable development-command execution
:Status: merged
:Planning status: provisional -- evidence-independent executor, ticket, process-lifecycle,
                  output, cancellation, workspace-coordination, and restart semantics are
                  concrete; implementation/promotion remains gated by Phase 4/6
                  implementation exits, real host evidence, and candidate-Pi execution-
                  isolation/resource-control evidence
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 4 durable-operation-kernel plan; merged Phase 6 development-
             workspace plan; Phase 4 and Phase 6 implementation exits before operational
             command promotion; real Phase 3/5/6 host/profile evidence where command Tool
             projection, development-session authority, or workspace access depends on it
:Primary objective: Let ChatGPT start, monitor, inspect output from, cancel, and reconcile
                    bounded development commands without making the MCP/application
                    process a shell or process supervisor and without granting command
                    processes Binnacle credentials, protected control-plane state, or
                    privileged-host authority
:Implementation scope: command contracts/schema/manifest promotion barrier; independent
                       unprivileged execution-supervisor service; local single-use execution
                       tickets; versioned framed-JSON Unix-domain-socket IPC; executor-owned
                       minimal durable evidence and output spool separate from the
                       application database; workspace-change coordination; exact
                       start/cancel/launch linearization; process-tree/resource/output
                       lifecycle; restart/reconciliation; tests, deployment seams, and
                       evidence gates only

Purpose
-------

Phase 7 gives Binnacle the process-execution capability required for normal software
engineering: running tests, linters, type checkers, build tools, short-lived development
servers, and other explicitly authorised programs in the registered Binnacle development
workspace.

The phase deliberately preserves three independent truths:

* the network-facing MCP/application process remains the sole controller-facing policy and
  authoritative Binnacle operation-state owner and **never** directly launches arbitrary
  development subprocesses;
* an independent unprivileged execution supervisor owns command acceptance, process-tree
  supervision, output capture, cancellation execution, and independent minimum lifecycle
  evidence sufficient to survive an ordinary MCP/application restart;
* the actual candidate-Pi process-isolation, resource-control, listener-exposure, and
  filesystem-view mechanisms are empirical platform-profile facts. Missing evidence keeps
  ``command_run`` unsupported rather than causing a direct-subprocess or privileged fallback.

This document freezes evidence-independent semantics. It does not claim that a Raspberry Pi
already supports a particular systemd/cgroup/process-isolation mechanism, that ChatGPT
exposes MCP Tasks or any proposed command/status Tool, that non-loopback listener enforcement
is available, or that Phase 6 runtime authority has passed its real exit gate.

``:Status: merged`` denotes the terminal authoritative state of this numbered plan after
planning review and CI acceptance. Before that acceptance the document is proposed.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-04-durable-operation-kernel.rst``;
#. merged ``docs/implementation/phase-06-development-workspace.rst``;
#. this Phase 7 plan;
#. ``docs/security/command-execution.md`` and
   ``spec/policy/command-profiles.yaml``;
#. ``docs/security/capability-composition.md`` and capability-zone policy;
#. ``docs/operation-idempotency.md``, ``spec/operation/idempotency.yaml``, and
   ``spec/operation/lifecycle.yaml``;
#. ``docs/audit-evidence.md`` and audit policy/schemas;
#. MCP manifest/schema/host-confirmation/controller/evaluation contracts;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

When an older detailed execution contract appears to imply a fourth long-lived privileged
service or advanced sandbox prerequisite, the owner-approved Bootstrap topology and Phase 0
reconciliation govern. Security properties remain mandatory; an implementation mechanism is
not promoted until it proves those properties.

2. Roadmap objective and exact exit gate
----------------------------------------

The roadmap requires an independent unprivileged execution supervisor and a versioned UDS
protocol between application and executor. The operational surface must support explicit
executable/argv/cwd/environment/stdin, process-tree supervision, bounded resources/output,
status, incremental output retrieval, cancellation, outstanding-operation listing, and
restart reconciliation.

Real Phase 7 exit is not achieved by this planning PR. It requires real ChatGPT on the real
development Pi to:

#. start Binnacle tests and quality tools through the reviewed command contract;
#. inspect bounded incremental stdout/stderr;
#. cancel a running command and observe truthful terminal state;
#. restart/reconnect the MCP/application process while an acknowledged independently
   supervised command remains resolvable;
#. demonstrate no command-process access to prohibited credentials/control-plane/privileged
   state and no workspace/mount/process-introspection escape;
#. preserve exactly-once start semantics across response loss/retry.

3. Three independent gates
---------------------------

3.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

This numbered plan may merge when review/CI proves the evidence-independent architecture,
state machines, IPC contracts, ordering, security boundaries, tests, and evidence procedure
are coherent and no real host/device behavior is invented.

Plan acceptance grants no command authority.

3.2 Implementation and promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not expose a command-start or command-operation Tool until all of the following are true:

* Phase 4 durable-operation implementation exit is current;
* Phase 6 registered-workspace/session implementation exit and exact shared CHANGE/fence
  seam are current;
* real development-session HOST-profile authority is reviewed/current for the selected
  ChatGPT product/account/workspace;
* exact Phase 7 operation contracts, input/output schemas, manifest entries, information
  classes, annotations, and result limits are reviewed and validated;
* the candidate Pi proves the selected independent supervisor/child execution backend,
  process-tree accounting, resource enforcement, filesystem view, exact registered root/
  mount/no-submount semantics, descriptor/FD closure, output spool durability, UDS peer
  credentials, and the required process-introspection/ptrace boundary;
* command children cannot see Binnacle inbound authentication material, protected app/
  executor control state, app SQLite/audit/recovery, root broker socket, credential agents,
  SSH/GPG private material, arbitrary device nodes, undeclared host mounts, or another
  Binnacle process's memory/descriptors/process-control surface;
* the preferred execution profile uses a distinct unprivileged command identity from the
  supervisor, **or** a same-UID profile independently proves bounded ``/proc`` visibility,
  denied ptrace/process-vm access and denied arbitrary signalling/process inspection outside
  the command execution domain. Merely hiding supervisor paths/sockets is insufficient;
* the selected network-confinement profile proves default network denial and, for the
  development profile, ordinary IPv4/IPv6/DNS application networking while preserving
  explicit non-loopback-listener authority. If that listener distinction cannot be
  enforced on the candidate profile, the affected networked command profile remains
  unsupported rather than relying on argv heuristics;
* exact single-use-ticket replay prevention, application post-commit cancellation
  forwarding, executor launch/cancel linearization, and executor evidence-store durability
  pass crash/fault tests;
* the production main app has no direct-subprocess fallback and no access path that bypasses
  the execution supervisor;
* missing, stale, contradictory, or unverifiable prerequisite makes the relevant command
  capability invisible/disabled.

3.3 Phase exit
~~~~~~~~~~~~~~

Phase exit additionally requires the empirical real-Pi/real-ChatGPT procedure in section
37. Automated tests and a healthy supervisor alone do not establish host support.

4. Explicit non-goals
---------------------

Phase 7 does not implement or promote:

* PTY allocation or interactive terminal reattachment;
* arbitrary shell interpolation hidden behind ``command_run``;
* Docker/Podman orchestration;
* a generic container platform;
* mandatory full seccomp/AppArmor/SELinux/Landlock framework;
* raw credentials or credential-agent access for command children;
* Git push/signing credentials -- Phase 8 owns those dedicated operations;
* root package/service/self-management execution -- Phase 9 owns a separate root broker;
* arbitrary host filesystem/mount/device authority;
* Binnacle control-plane socket access from command children;
* hardware access;
* a second authoritative Binnacle operation database;
* MCP Tasks as a prerequisite;
* automatic rerun of an uncertain execution;
* interpreting command output or repository content as authority;
* direct MCP-process ``subprocess``/``os.exec`` fallback if the supervisor is unavailable.

5. Process-role reconciliation
------------------------------

Bootstrap has three long-lived service roles:

#. unprivileged MCP/application control process;
#. independently supervised unprivileged execution service;
#. narrow privileged root broker introduced in Phase 9.

The existing command security contract describes three **logical command-path boundaries**:
policy process, narrow execution broker, and unprivileged executor. Phase 7 maps them without
creating a second privileged broker:

``Binnacle policy process``
   The existing MCP/application process. It authenticates, normalizes, owns policy,
   authoritative Phase 4 operation state, development-session state, workspace CHANGE/fence
   admission, audit, and Tool projection.

``narrow execution broker``
   The independent Phase 7 **execution-supervisor service**. It is unprivileged. It accepts
   only the versioned local UDS protocol, authenticates the application peer using OS socket
   credentials, independently validates one exact local single-use execution ticket,
   durably consumes/reconciles that ticket, constructs the reviewed execution domain, and
   supervises the resulting process tree. It exposes no general privileged API.

``unprivileged executor``
   The exact command process/tree created by the supervisor inside the selected reviewed
   execution domain. It is a separate process domain from the supervisor and cannot access
   supervisor/app sockets, memory, descriptors, process-control interfaces, or state merely
   because it was spawned locally.

Thus ``narrow_execution_broker_separate=true`` means the broker/supervisor is separate from
the policy process, while ``unprivileged_executor_separate=true`` means the command process
is separate from the supervisor. It does **not** create a fourth long-lived root service.
If contract tooling currently interprets those booleans differently, Phase 7 contract
promotion must reconcile that interpretation before handler exposure.

The Phase 9 privileged broker remains entirely separate and is never a hidden command-
sandbox helper. Candidate isolation that would require generic root calls from every
command is not a valid Phase 7 implementation.

6. Runtime identities and filesystem/process state layout
---------------------------------------------------------

Conceptual deployment uses separate service/runtime state:

::

   /run/binnacle/
       executor/
           supervisor.sock

   /var/lib/binnacle/
       executor/
           state/
               executor-state.sqlite3
           output/
               <execution-id>/
                   stdout.bin
                   stderr.bin

Exact paths are protected owner configuration. The executor tree is **not** part of the
source workspace and command children must not see it in their filesystem view.

The application never opens ``executor-state.sqlite3`` directly. The supervisor never opens
Binnacle's authoritative application SQLite database, audit journal, authentication state,
or policy store. Reconciliation occurs through the UDS protocol.

The preferred Bootstrap profile runs command processes under a **distinct unprivileged OS
identity/process domain** from the supervisor so ordinary same-UID process inspection does
not collapse the broker/executor boundary. A stronger or equally safe mechanism is allowed
when the candidate platform proves it.

A same-UID supervisor/command profile is not accepted merely because filesystem state and the
UDS socket are masked. It is eligible only when the selected execution-domain confinement
independently proves all of the following for the command process/tree:

* bounded ``/proc`` exposure that does not reveal supervisor/application memory,
  descriptors, environment, control sockets, or other process-sensitive state;
* ptrace-style attachment and ``process_vm_readv``/``process_vm_writev`` access to
  supervisor/application processes are denied;
* opening ``/proc/<supervisor-or-app-pid>/mem``, ``fd``, ``fdinfo``, or equivalent
  process-introspection surfaces is denied;
* arbitrary signals/process-control operations against the supervisor/application are
  denied outside the exact reviewed lifecycle boundary;
* the command cannot escape those restrictions by spawning descendants, changing process
  groups/sessions, or using another same-UID process interface.

The exact mechanism -- distinct UID, PID namespace/proc view, non-dumpable protected
processes, LSM/process policy, or a reviewed composition -- is candidate-Pi evidence. The
security property is not optional. If the selected platform cannot prove the same-UID
boundary, use a distinct child identity or keep ``command_run`` unsupported.

7. Separate executor evidence store
-----------------------------------

The application database remains authoritative for Binnacle operation lifecycle. Phase 7
adds a small independent **executor evidence database** owned and written only by the
execution supervisor because exact ticket consumption and process evidence must survive an
ordinary application restart and a lost UDS response.

SQLite is preferred over a custom journal because it is already a mature Bootstrap native
mechanism and correctness outweighs tiny write-throughput gains. The executor database is a
separate file/schema and never participates in a cross-database transaction with the app.
It uses local storage, foreign keys, WAL, ``synchronous=FULL``, bounded busy timeout, and an
explicit versioned migration/setup path; runtime never opportunistically creates or
silently repairs schema.

Representative tables:

``executor_meta``
   Schema version, supervisor instance/generation, boot identity, last verified recovery
   generation, readiness/integrity state.

``execution_records``
   ``execution_id`` PK; exact operation ID; ticket ID/digest; single-use nonce digest;
   command/profile/workspace/root/mount/resource/environment/sandbox-plan digests;
   accepted generation/time; evidence state; durable ``cancel_generation`` and cancellation
   disposition; launch generation/commit state; backend domain identity; PID/start-time/
   cgroup or unit references where available; exit/signal/resource/cancel facts; cleanup
   state; output references/counters/digests/truncation; last evidence generation/reconciled
   time.

``pending_cancel_intents``
   Exact operation ID + ticket ID/digest; highest monotonic cancel generation; expiry/boot
   scope; accepted application peer profile; creation/update evidence generation. This is a
   bounded pre-acceptance cancellation latch only. It carries no command authority and is
   atomically consumed/attached if the matching ticket is later accepted. Contradictory
   ticket digest/operation identity fails closed.

``ticket_tombstones`` or retained terminal execution rows
   Preserve enough non-secret ticket/operation identity for the full duplicate/replay
   window so an old consumed ticket can never spawn again after output or detailed evidence
   expires.

Raw caller idempotency keys, host bearer credentials, SSH/GPG keys, source content, and
unbounded argv/stdin/output do not belong in this database. Exact command argv/input may be
retained by the authoritative application record/payload policy where needed; the executor
retains bounded digests plus only the minimum start data required to execute/reconcile.

The executor DB is evidence, not an alternate operation lifecycle. If executor evidence and
application state disagree, reconciliation reports the contradiction; neither store is
silently rewritten from the other.

8. Executor evidence state machine
----------------------------------

Use a separate executor-only state vocabulary to avoid pretending it is the Phase 4
lifecycle. The exact names may differ, but the state/fact model must preserve this
linearization:

::

   ticket_seen
     -> accepted
     -> launch_preparing
     -> launch_committed
     -> running
     -> exited
     -> cleanup_pending
     -> closed

   accepted | launch_preparing
     -> cancel_requested
     -> exited              # exact proven no-process cancellation
     -> cleanup_pending
     -> closed

   launch_committed | running
     -> cancel_requested
     -> cancelling
     -> exited
     -> cleanup_pending
     -> closed

   accepted | launch_preparing | launch_committed | running | cancelling | cleanup_pending
     -> executor_uncertain

``launch_committed`` is an executor-local fact: the launch path won the executor
launch-versus-cancel gate and is permitted to cross the exact backend process/domain-create
boundary once. It is **not** a second Binnacle effect boundary and it does not permit a
second process on retry.

The exact persisted representation may combine states/facts, but it must distinguish at
least:

* ticket never durably accepted;
* a pre-accept cancellation intent for exact operation+ticket/digest;
* ticket durably accepted/consumed -- **Phase 4 command commit-to-supervisor exists**;
* cancellation generation durably recorded before any process/domain creation;
* executor launch preparation versus gate-owned launch commit;
* process/domain creation attempted;
* exact process/domain identity known;
* process tree currently running;
* exit observed with exact code/signal/reason;
* cancellation requested/signalled;
* cancellation proven to suppress process creation versus cancellation targeting an exact
  created/possibly-created domain;
* descendants fully terminated or not;
* workspace/private-temp/domain cleanup complete or not;
* output complete/truncated/expired;
* evidence uncertain/corrupt/unverifiable.

Once a ticket is durably ``accepted``, replay can return the same ``execution_id`` but can
never allocate another execution. A supervisor crash after acceptance but before actual
``exec`` is recovery of one committed execution, not permission to create a second one.
Durable cancellation discovered before executor launch commit suppresses that launch. A
matching pre-accept cancel intent is attached atomically during acceptance so the launch
worker cannot outrun it. If launch commit won or process creation is ambiguous, recovery
must reconcile/terminate the same exact execution; it never synthesizes a fresh ticket or
assumes process absence from a missing PID alone.

9. Local execution ticket
-------------------------

9.1 Authority model
~~~~~~~~~~~~~~~~~~~

A ticket is **not** a bearer credential. Bootstrap uses a local OS-authenticated ticket over
a restricted UDS rather than adding a new shared signing secret merely to authenticate two
local Binnacle processes.

The supervisor accepts start/cancel/reconcile protocol only from the exact configured main
application peer identity verified by socket permissions and Linux peer credentials. It
independently validates the ticket's closed fields and digests and stores the single-use
nonce digest durably before command launch.

A future signed ticket remains compatible with this seam, but no cryptographic secret is
invented in Phase 7 without a concrete requirement.

9.2 Ticket facts
~~~~~~~~~~~~~~~~

The exact promoted command policy/contract retains current required facts and should add
trusted same-boot deadline evidence where needed:

* ticket ID and exact Binnacle ``operation_id``;
* controller identity digest + epoch snapshot;
* device identity/epoch;
* development session ID/state-version/closure digest;
* command profile/version;
* exact resolved executable identity;
* structured argv digest;
* exact cwd/workspace-relative digest;
* inline stdin digest / server-held input digest / workspace-script digest using explicit
  NULL values when absent;
* workspace ID/profile/root identity and **registered mount identity/no-submount policy**;
* exact Phase 6 workspace mutation-fence owner/version;
* mount/execution-filesystem-view plan digest;
* process-visibility/ptrace-isolation plan digest;
* environment plan digest;
* network/listener-exposure plan digest;
* policy/admission record and policy digest;
* resource/output plan digest;
* sandbox/confinement backend/profile digest;
* aggregate workspace byte/inode ceilings;
* issuance trusted-time/boot identity + short same-boot monotonic deadline where selected;
* ``expires_at``;
* single-use nonce.

Supervisor independently revalidates every field that it can observe. It does not query the
application SQLite database. A mismatch, expired/different-boot ticket, wrong peer,
unsupported profile, changed executable/root/mount/process-isolation plan, duplicate nonce
with different ticket digest, or corrupt executor evidence fails closed.

10. Command request normalization
---------------------------------

``command_run`` is proposed as the start Tool name because it is already the security-
contract vocabulary. It remains a proposal until contract/schema/manifest promotion.

First-use input is closed and typed:

* registered ``workspace_id``;
* exact effective ``development_session_id``;
* caller idempotency key;
* executable selector/profile-resolved executable;
* structured argv array;
* workspace-relative cwd;
* optional bounded inline stdin or reviewed bounded server-held input reference;
* explicit environment additions from an allowlisted key/value schema;
* exact command profile;
* exact resource ceilings no greater than profile maxima;
* explicit network/listener-exposure selection where contract permits it.

No shell string. No implicit ``PATH`` search at child execution time. Application resolves
an allowed executable to an exact absolute executable identity under the reviewed command
profile and binds descriptor/stat/digest facts as applicable. Supervisor reopens/revalidates
the same identity before launch.

Arguments are data and never re-parsed as shell syntax. If a future shell contract is
needed, it receives a separate name/schema/risk review.

Cwd normalization consumes the Phase 6 registered-root/no-submount rules. A cwd under an
unregistered nested mount, symlink, replaced root, protected control-plane path, or
unverifiable mount identity is rejected before command admission.

11. Workspace authority and Phase 6 shared CHANGE seam
------------------------------------------------------

Bootstrap deliberately treats **every general development command as workspace-changing**.
That includes apparently observational tools such as ``pytest``, ``ruff``, ``mypy``, build
systems, Python scripts, environment tooling, and Git CLI because plugins, caches, generated
files, subprocesses, and configuration can write even when the command's human label sounds
read-only.

Therefore every first-admission ``command_run`` acquires:

#. Phase 6 exclusive ``WorkspaceAccessGate.CHANGE``;
#. the same durable ``workspace_mutation_fence`` owned by the command operation;
#. exact workspace/root/mount/profile facts bound into the command ticket.

The CHANGE guard and durable fence remain owned for the **entire independently supervised
descendant lifetime**, through output/process terminal observation and workspace/private-
temp/domain cleanup, until truthful Phase 4 terminal/audit/recovery closure permits release.

``uncertain`` retains the fence. Top-level PID exit alone never releases it. An executor
crash, unknown descendant, unresolved cleanup, unknown mount teardown, or ambiguous command
acceptance keeps the workspace change-closed.

A future command profile may avoid CHANGE only if it is separately reviewed as truly
read-only and the execution backend **enforces** a read-only workspace view. Executable-name
heuristics are not sufficient.

Phase 8 semantic Git operations consume the same coordination seam; no later adapter gets a
parallel writer path.

12. Command filesystem and process view; protected state
--------------------------------------------------------

The command process filesystem/process view is its own explicit command contract. It is not
a Phase 6 ``ContentReadPermit`` and does not inherit arbitrary content or process authority
merely because ChatGPT can read source through workspace Tools.

Required filesystem view:

* exact registered source workspace root/mount identity from Phase 6;
* no implicit nested/unregistered submounts from the source tree;
* only explicitly reviewed read-only system/runtime files needed by the selected command
  profile;
* operation-private temporary storage;
* no ``/etc/binnacle`` protected configuration/policy/authentication;
* no application SQLite, audit journal, audit obligations, recovery/checkpoints;
* no executor evidence DB/output/control socket;
* no Phase 9 privileged-broker socket;
* no SSH/GPG private keys or credential-agent sockets;
* no arbitrary host mounts or device nodes;
* no inherited Binnacle MCP/server sockets.

Required process-introspection view:

* no ptrace/process-vm/memory/descriptors/process-control authority over the supervisor,
  application, Phase 9 broker, or unrelated host processes;
* bounded ``/proc`` exposure appropriate to the exact command execution domain, or an exact
  independently enforced equivalent;
* descendants receive no more process-inspection authority than the top command;
* same-UID execution is unsupported unless these properties are explicitly tested and
  proven on the candidate profile.

If the backend intentionally maps the registered source workspace into an execution-local
sandbox path, the ticket binds the **source** root/mount identity and the exact reviewed
mapping/mount-plan digest. That internal mapping is not an implicit permission to traverse
nested source mounts. The supervisor independently verifies the mapping before acceptance
and the command cannot remount/broaden it.

The current command contract's fail-closed symlink/bind-mount/hard-link/rename ambiguity
remains. Candidate evidence must demonstrate the actual filesystem/process-view mechanism.
If the platform cannot provide the minimum protected-state/process-isolation boundary,
``command_run`` stays unsupported; a working ``cwd`` alone is not containment.

Phase 6 excludes ``.git`` from direct content Tools. Generic Phase 7 command execution does
not automatically declassify protected Git metadata into model-visible output. The promoted
command filesystem/profile must state whether ``.git`` is absent/masked in Phase 7 or
narrowly available to selected no-credential commands. Bootstrap Phase 7 exit does not
require Git metadata access, and the conservative default is to keep ``.git`` hidden from
generic command processes until the Phase 8 Git boundary is reviewed. If existing command-
profile fixtures require ``git`` executable availability, that executable may remain
allowed without granting repository metadata or credentials.

13. Network authority and listener exposure
-------------------------------------------

Global/default command execution is network denied.

The reviewed ``workspace-general-v1`` / inherited ``workspace-check-v1`` development
profile may permit ordinary IPv4, IPv6, and DNS application networking. That permission
still excludes:

* raw packet/network administration;
* protected Unix/control sockets;
* inherited sockets;
* credential agents/raw credentials;
* arbitrary device authority;
* implicit non-loopback listener exposure.

Loopback development listeners may be authorised by profile. Binding ``0.0.0.0``, ``::``,
LAN, or another non-loopback interface requires an explicit typed exposure selection and
local authority. The implementation **must enforce** this at the execution-domain/network
boundary; argv/name inspection is never enforcement.

The exact mechanism is candidate-Pi evidence-dependent. A network namespace, cgroup/BPF or
another reviewed Linux mechanism may implement the property. Advanced generic sandbox
hardening remains deferred, but inability to enforce the **required** listener boundary
keeps the affected network profile unsupported. Phase 7 never weakens the contract because
the simplest launch mechanism cannot enforce it.

14. Environment, descriptors, IPC, and credentials
---------------------------------------------------

Child environment is constructed from a minimal profile allowlist. It does not inherit the
application/supervisor service environment wholesale.

At minimum deny/remove:

* MCP/authentication tokens and headers;
* Binnacle policy/config/state paths not explicitly safe;
* ``SSH_AUTH_SOCK``, ``GPG_AGENT_INFO``/agent sockets and key helper variables;
* generic credential/helper/token variables;
* Python/runtime injection variables unless explicitly required and reviewed;
* container-engine/D-Bus/control-plane socket variables;
* proxy variables when the exact network profile does not permit them.

Every child FD is explicitly mapped or closed. No supervisor listener, application UDS,
inherited network socket, audit/state FD, credential agent, procfd capability, device FD,
or control-plane descriptor reaches the command.

Phase 8 uses dedicated non-exportable SSH/signing authority for exact Git actions. Phase 7
generic commands receive none of it.

15. Execution-domain backend
----------------------------

One ``ExecutionDomainBackend`` port owns command process creation. The preferred Bootstrap
family is systemd/cgroup-v2-backed because systemd already owns service/cgroup lifecycle,
but the exact candidate mechanism is not guessed.

A valid backend must prove:

* execution occurs outside the MCP/application process;
* dedicated unprivileged command identity/domain; a distinct child UID is preferred;
* if supervisor and command share UID, bounded ``/proc`` visibility plus denied
  ptrace/process-vm/arbitrary-signal access to supervisor/application/unrelated processes;
* exact executable/argv/cwd/env/stdin;
* no-new-privileges and no ambient/inheritable capabilities/setuid gain;
* the section 12 filesystem/protected-state/process-introspection boundary;
* the section 13 network/listener profile;
* descendant-wide cgroup/accounting that fork/double-fork/setsid/daemon behavior cannot
  escape;
* resource limits from section 20;
* deterministic process-domain identity usable for reconciliation;
* exact child/process-tree termination evidence;
* supervisor/app restart behavior defined;
* no Phase 9 root-broker dependency for ordinary command start.

Candidate choices may include a preconfigured systemd transient-unit/scope mechanism, a
predelegated cgroup subtree plus controlled spawn, or another reviewed systemd-backed
execution domain. If creating the required domain would need an unrestricted privileged
call at each start, that candidate is not Phase 7 Bootstrap architecture.

The chosen process-visibility/ptrace mechanism is part of the reviewed execution profile and
``sandbox_plan_sha256``. It is independently revalidated before launch. The command security
contract's ``ptrace_outside_sandbox: denied`` property is a mandatory promotion predicate,
not target-only hardening.

``direct_subprocess_fallback=false`` means the main MCP/application process never falls
back to local ``subprocess`` if supervisor/backend is unhealthy. It does not prohibit the
unprivileged supervisor from using a reviewed low-level spawn primitive **inside** the
validated execution domain after exact ticket acceptance.

16. Versioned UDS protocol
--------------------------

Main application and execution supervisor communicate only through a restricted Unix-
domain socket under ``/run/binnacle``.

Protocol properties:

* explicit protocol ID/version;
* length-prefixed/framed JSON;
* UTF-8/I-JSON compatible bounded documents;
* closed message schemas and discriminator;
* request/correlation ID + operation/ticket/execution identity as applicable;
* hard frame/message ceilings;
* timeout and backpressure limits;
* Linux peer-credential verification;
* filesystem/socket ownership/mode;
* no pickle/arbitrary object deserialization;
* no forwarded raw controller credential;
* unknown version/type/field policy fails closed where security relevant;
* start and cancellation control requests are dispatchable concurrently; a long-running
  ``start_execution`` handler/backend-create wait cannot head-of-line block
  ``request_cancel``. A single serial request loop that prevents post-commit cancellation
  from reaching the executor launch gate is not promotable.

Representative messages:

::

   hello / hello_result
   start_execution / start_result
   get_execution / execution_snapshot
   read_output / output_chunk
   request_cancel / cancel_result
   list_executions / execution_list
   reconcile_execution / reconcile_result

Large stdout/stderr/stdin are never unbounded control frames. Bootstrap inline stdin has a
small reviewed ceiling; larger server-held input is either bounded into the same start
frame after exact digest verification or uses a separately reviewed bounded transfer
subprotocol before start acceptance. No input reference lets the supervisor open the
application database or arbitrary protected filesystem path.

Cancellation messages identify the exact operation and original ticket identity/digest
plus a monotonic cancel generation. ``execution_id`` is included when already known to the
application but is not required. If cancellation arrives before the matching execution row
has been accepted, the exact authenticated supervisor stores/updates a bounded
``pending_cancel_intent`` rather than returning a lossy not-found result. Matching first
acceptance atomically attaches the highest valid generation; contradictory operation/ticket
identity or digest fails closed. This allows a cancellation forwarded after application
``call_start`` commitment to race supervisor acceptance/launch even while the original
start response is still in flight.

17. Start linearization across Phase 4 and supervisor
-----------------------------------------------------

This is the core Phase 7 cross-process invariant.

For a new ``command_run`` first admission:

#. authenticate/normalize exact controller/session/workspace/command/profile;
#. resolve caller idempotency binding **before** mutable session/ticket/current-state
   validation;
#. atomically create/find global caller binding + minimal Phase 4 version-1 ``received``
   operation;
#. fsync required ``operation.state_changed(NULL -> received)`` audit;
#. revalidate effective Phase 6 development session, command profile, root/mount,
   executable/input/resource/network facts;
#. evaluate policy;
#. deny -> durable decision + ``received -> rejected`` with no workspace guard/fence/ticket;
#. allow -> acquire exclusive Phase 6 CHANGE; in one post-policy transaction re-prove exact
   predicates, acquire exact self durable workspace mutation fence, persist command metadata
   + one allow decision, commit ``received -> authorised``;
#. build exact local execution ticket bound to the self fence/current state;
#. fsync required allowed-policy/authorised audit;
#. commit ``authorised -> running``;
#. fsync exact ``effect.intent_recorded`` for **commit one execution to independent
   supervisor**;
#. acquire Phase 4 per-operation dispatch handoff;
#. acquire Phase 6 ``DevelopmentSessionAuthorityGate``;
#. acquire Phase 4 process-wide ``ConsequentialBoundaryGate``;
#. under those gates final-revalidate operation/controller/device/session/profile/root/
   mount/fence/executable/ticket/resource/network/listener/cancel/audit/recovery predicates;
#. publish/fsync the Phase 4 audit-obligation marker;
#. recheck exact predicates and let the process-wide gate own ``call_start`` for
   ``ExecutionSupervisorPort.start(ticket)``;
#. at the exact gate-owned ``call_start`` linearization, publish one process-local
   per-operation ``DispatchCommitLatch=COMMITTED`` **before** the UDS start call can block.
   This latch is visible to concurrent cancellation in the same application runtime and is
   never set if cancellation/audit/session failure wins before ``call_start``;
#. once ``DispatchCommitLatch`` is committed, the **pre-start** branch of
   ``DispatchHandoffGate`` no longer serializes post-commit cancellation behind the bounded
   start RPC. A concurrent owner cancellation uses the section-25 post-commit forwarding
   path, which may persist Phase 7 cancel intent and send exact operation+ticket cancellation
   while this start RPC is still in flight;
#. supervisor validates peer+ticket and performs its durable single-use acceptance
   transaction. That transaction atomically attaches any matching pre-accept
   ``pending_cancel_intent`` before launch preparation can begin;
#. supervisor applies ``ExecutorLaunchGate``; concurrently dispatched cancellation can
   suppress launch before ``launch_committed`` or wait for the same gate and terminate the
   exact created/possibly-created domain;
#. bounded start response returns either exact durable accepted execution reference,
   explicit durable no-accept result, or transport/receipt ambiguity;
#. application immediately persists effect reference/effect knowledge with an optimistic
   field-aware update that **never overwrites a newer Phase 7 cancellation generation or
   legal ``cancelling`` lifecycle transition**. If only Phase 7 cancel intent was safe to
   persist before effect classification, this classification consumes that intent and
   projects the legal lifecycle transition;
#. only after immediate effect classification may the ordinary start path release the
   process/session/per-operation start gates;
#. fsync required post-start audit and close the exact obligation when permitted;
#. command remains running/cancelling/uncertain until later supervisor evidence reaches a
   truthful terminal lifecycle outcome;
#. release workspace fence/CHANGE only after section 24 terminal/cleanup closure.

The Phase 4 process-wide ``call_start`` remains the audit-failure-vs-dispatch linearization.
The executor's durable acceptance is the independent exactly-once evidence after that
linearization. ``DispatchCommitLatch`` is a runtime race discriminator, not durable effect
truth: after application crash, restart derives nothing from the lost latch and reconciles
from Phase 4 dispatch/effect state plus exact supervisor evidence. The post-commit cancel
path does not weaken the Phase 4 rule that cancellation winning **before** ``call_start``
must suppress supervisor dispatch; it only prevents an already-committed start RPC from
blocking cancellation until backend creation finishes.

18. Supervisor single-use acceptance and executor-local launch gate
-------------------------------------------------------------------

18.1 Single-use acceptance transaction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On ``start_execution`` the supervisor:

#. verifies protocol version/frame/schema and exact application peer credentials;
#. validates ticket digest, operation/ticket IDs, single-use nonce syntax/digest, expiry/
   boot deadline, profile, executable, cwd/root/mount, process-isolation, environment/
   resource/network/sandbox plan, and all supplied input bytes/digests;
#. looks up ticket/operation in executor evidence **before** mutable launch checks;
#. same exact already-consumed ticket -> return retained ``execution_id``/state; never
   spawn again;
#. same ticket ID/nonce/operation with different digest -> conflict/no start;
#. first use -> one FULL-durability transaction inserts exact ``execution_id``, ticket/
   nonce digests and command/evidence plan and marks ``accepted``; in the same transaction
   it reads/attaches the highest matching unexpired ``pending_cancel_intent`` for exact
   operation+ticket/digest, if any;
#. only after that commit may launch preparation/process creation begin.

This acceptance is single-use even if the UDS response is lost, the application reconnects,
the command later exits, output expires, or the supervisor restarts. Retention/tombstone
outlives every allowed replay window. A matching pre-accept cancellation is also durable
across response loss/restart and cannot be discarded merely because the start frame won the
network race.

Supervisor never invents a second Binnacle operation and never accepts a fresh ticket for
an already-bound operation merely because application state is ``uncertain``.

18.2 ``ExecutorLaunchGate``: atomic launch-versus-cancel ownership
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every accepted execution has one supervisor-local ``ExecutorLaunchGate`` (or exact durable
CAS/lock equivalent) shared by the launch worker, cancellation handler, timeout/resource
pre-start handler, and restart reconciler. The fixed rule is that **no backend process/domain
creation may begin from a stale ``accepted``/``launch_preparing`` snapshot**.

The launch path:

#. acquires the exact execution's launch gate;
#. re-reads the durable execution row, attached/pre-accept and normal
   ``cancel_generation``, ticket/profile, executor readiness/integrity, and any
   terminal/uncertain state;
#. if a durable cancellation already exists and no backend create was committed, atomically
   records ``cancellation_suppressed_spawn=true`` plus the exact no-process evidence and
   performs **zero** backend create/spawn;
#. otherwise atomically records one ``launch_committed`` generation while holding the gate;
#. while still holding the gate, crosses the exact backend ``create``/spawn handoff and
   obtains either an exact durable/reconcilable domain handle, an explicit no-domain receipt,
   or an ambiguous receipt;
#. durably records that handle/receipt/evidence generation before releasing the gate;
#. if cancellation became pending only after launch commit (the cancel handler waits for the
   same gate), it is applied to the exact returned domain immediately after the handler
   acquires the gate; if create receipt is ambiguous, executor state becomes
   ``executor_uncertain`` and cancellation/recovery conservatively targets any independently
   discovered domain for this exact execution.

The cancellation path:

#. authenticates the application peer and validates exact operation+ticket/digest, with
   ``execution_id`` as an additional consistency check when present;
#. if no accepted execution row exists yet, durably create/update the bounded
   ``pending_cancel_intent`` with the highest valid generation and return an explicit
   retained-preaccept-cancel result. It never manufactures an execution or a no-effect
   claim;
#. if the execution exists, acquires the same ``ExecutorLaunchGate``;
#. persists a strictly higher ``cancel_generation`` before signalling or deciding spawn
   suppression;
#. if state is ``accepted``/``launch_preparing`` and no launch commit exists, atomically
   wins cancellation, suppresses backend creation, and closes with exact no-process
   evidence;
#. if ``launch_committed``/``running`` or process creation is possibly committed, it never
   returns a no-process success from absence. It targets the exact domain if known, or
   enters conservative reconciliation/termination if the create receipt is ambiguous;
#. same/lower cancel generations are idempotent retained reads and never duplicate signals
   or launch.

The gate is held only in the unprivileged supervisor and never while the application owns a
SQLite transaction. It may cover the bounded backend-create/receipt handoff because its
purpose is exactly to eliminate the ``accepted -> process created`` cancellation gap. A
backend whose create call can hang without a bounded deadline is not promotable. UDS
request handling must remain concurrent enough that a cancellation control request can
reach this gate while the original start handler is waiting on that bounded backend handoff.

A supervisor crash is recovered from the durable launch/cancel facts. ``cancel_requested``
or an attached matching pre-accept cancellation before ``launch_committed`` can never later
spawn. ``launch_committed`` without a trustworthy create receipt is **not** permission to
start a second domain: recovery uses the exact execution/backend identity and returns
uncertainty unless the backend independently proves the one committed domain/no-domain
outcome.

This is the required executor-side counterpart to Phase 4's application-side
``DispatchHandoffGate`` and ``ConsequentialBoundaryGate``. It closes the later process-spawn
race without inventing another Binnacle operation or another user authority source.

19. Start outcomes and Phase 4 effect knowledge
-----------------------------------------------

``known_effect``
   Exact supervisor response proves the ticket was durably accepted/consumed and returns a
   stable ``execution_id`` + executor evidence generation/reference. The Phase 4 effect is
   **commit one execution to the independent supervisor**; actual child may still be in
   accepted/launch-preparing/launch-committed/running/cancel-requested state. Later launch
   failure or cancellation-before-spawn is a terminal outcome of that already-committed
   supervisor execution, not proof that the Phase 4 effect never occurred.

``known_no_effect``
   Allowed only when exact pre-start/Phase4-gate failure or an explicit supervisor proof
   establishes that the ticket itself was not accepted/consumed and no execution was
   committed to the supervisor. A cancellation that suppresses child spawn **after durable
   supervisor acceptance remains ``known_effect``** for the command operation. A simple
   socket error is not enough.

``uncertain``
   Lost/ambiguous UDS delivery/receipt, supervisor evidence-store unavailability,
   contradictory start response, ambiguous backend create receipt after launch commit, or
   inability to prove accepted-versus-not-accepted after ``call_start``. Workspace fence
   remains owned and no fresh execution is created. Same ticket/operation is reconciled
   through the supervisor. A concurrently forwarded cancellation remains retained by its
   generation; uncertainty never discards it or authorizes another start.

A later reconciliation that finds an uncertain operation's command still running does
**not** move Phase 4 ``uncertain`` back to ``running`` because the reviewed lifecycle has no
such edge. It reports retained executor running evidence while authoritative operation
remains ``uncertain``; when independent evidence eventually proves terminal outcome it may
use the allowed ``uncertain -> succeeded|failed|cancelled`` transition. This is deliberate
conservatism, not a reason to invent another lifecycle edge.

20. Descendant-wide resource controls
-------------------------------------

The selected execution domain enforces profile maxima across the full descendant tree:

* wall-clock deadline;
* CPU accounting/budget;
* memory and swap;
* PIDs/process count;
* open files;
* file-size controls where supported;
* aggregate workspace write/allocated bytes and inode/file count;
* operation-private temp bytes;
* stdout/stderr generated/retained ceilings;
* execution-domain lifetime.

The current policy maxima remain inputs to contract promotion; a command can request only
equal/narrower limits. Fork, double-fork, daemonize, setsid, process-group changes, child/
grandchild creation do not escape the execution domain/accounting.

Exact enforcement backend is real-Pi evidence. Missing or unverifiable descendant-wide
resource enforcement keeps the profile unsupported rather than degrading to parent-PID
limits.

21. Stdout/stderr capture and retention
---------------------------------------

Supervisor owns stdout/stderr pipes and executor-owned spool files independent of one MCP
response and of the application process lifetime.

For each stream retain:

* append offset / total observed bytes;
* retained byte count;
* SHA-256 over retained/final stream according to reviewed policy;
* truncation/limit flag and reason;
* complete/finalized state;
* finalized timestamp;
* retention/expiry metadata;
* exact execution ID/evidence generation.

Output writes are atomic/append-safe and fsynced/finalized at reviewed checkpoints/terminal
closure. Metadata never claims bytes durable that were not written.

``stdout_stderr_bytes_max`` is an execution-resource ceiling, not permission to deadlock a
child by ceasing to drain pipes. The supervisor continues bounded draining while enforcing
the reviewed policy; exceeding a hard generation ceiling terminates/fails the execution or
uses an explicitly reviewed drain-and-discard mode. It never blocks indefinitely with a
full pipe while reporting a healthy running command.

Command output is untrusted data and conservatively ``restricted-result`` for the host
projection unless an exact promoted contract states otherwise. Output can contain source or
remote content but never raw Binnacle/SSH/GPG credentials because the process lacks that
authority. Audit stores digests/summaries, not raw unbounded output.

22. Bounded output retrieval
----------------------------

Proposed ``operation_output`` is owner-scoped/read-only and maps authoritative operation to
its retained executor output reference. Exact naming is reviewed during contract promotion.

Input includes operation ID, stream, byte offset/cursor and requested max bytes within
profile. Result distinguishes:

* bytes available now;
* ``next_offset``;
* current retained end;
* execution still running with no new bytes -- empty data + ``eof=false``;
* terminal stream fully drained -- ``eof=true``;
* output truncated due to execution ceiling;
* output payload expired while security/operation record remains;
* supervisor/evidence unavailable;
* operation uncertain while executor evidence is running/terminal.

An empty chunk is never silently equivalent to EOF. A truncated stream is never presented
as complete. Cursor does not grant authority and cannot read another operation/controller.

Same-owner retained status/output remains inspectable after development-session end under
the exact operation's retained disclosure contract because session end must not strand
acknowledged work. It creates no new process effect. Permanent information/credential
boundaries still apply.

23. Operation status and outstanding listing
--------------------------------------------

Proposed status/list Tools are read-only and backed by application authoritative operation
state plus bounded executor reconciliation evidence.

``operation_get`` or equivalent returns Phase 4 operation snapshot, command metadata,
bounded executor evidence/state/progress, output availability, cancellation state and
reconciliation guidance. It never substitutes executor evidence state for the Phase 4
lifecycle.

``operation_list``/outstanding returns owner-scoped bounded operations relevant to the
controller, with stable pagination/limit. Another controller receives no operation details.
Session end does not erase outstanding operations.

MCP Tasks may later map onto these operation IDs if the actual ChatGPT HOST profile proves
Task support. Task identity never replaces Binnacle ``operation_id``.

24. Terminal command/domain closure and workspace fence release
---------------------------------------------------------------

A normal accepted command closes only after supervisor evidence proves:

* exact execution/process domain identified, **or** exact gate-owned cancellation-before-
  spawn evidence proves no domain/process was created after durable supervisor acceptance;
* top process exit code/signal/reason observed when a process existed;
* all descendants terminated or exact contract-approved survivors accounted;
* output pipes drained/finalized under policy;
* private temp/mount/execution resources removed or explicitly quarantined;
* workspace resource accounting finalized;
* no unresolved executor evidence-store/integrity contradiction;
* required application post-effect/terminal audit/recovery obligations complete.

Then Phase 4 lifecycle mapping is:

* verified exit 0 under success contract -> ``succeeded`` + ``known_effect``;
* verified non-zero/timeout/resource/start-after-accept failure -> ``failed`` +
  ``known_effect``;
* verified owner cancellation, including cancellation that suppresses child spawn **after
  supervisor acceptance**, with complete executor/descendant/cleanup proof -> ``cancelled``
  + ``known_effect``;
* ambiguity after accepted/possible start -> ``uncertain`` unless lifecycle already
  uncertain and awaiting later terminal proof;
* explicit supervisor no-accept before any execution commit -> failed/cancelled
  ``known_no_effect`` only when Phase 4 mapping permits and exact proof exists.

Workspace durable mutation fence and exclusive CHANGE guard release only after truthful
terminal/effect/audit/cleanup closure. If process might still run, descendants are unknown,
workspace cleanup is unresolved, output/process evidence contradicts, executor state is
uncertain, or a forwarded cancellation is not reconciled, fence stays owned.

25. Cancellation model
----------------------

Cancellation uses the **existing command operation identity**, not a new generic command
operation that could race into duplicate work.

Owner-scoped cancel is permitted even if the development session has ended because it
reduces/terminates an already acknowledged execution rather than authorizing new work.
Another controller cannot cancel it absent a separately reviewed recovery/ownership
transfer contract.

There are two nested cancellation/start races and a post-commit forwarding seam:

* **application pre-commit Phase 4 race** -- while ``DispatchCommitLatch`` is still
  ``PRE_COMMIT``, the existing per-operation dispatch handoff decides cancellation versus
  ``ConsequentialBoundaryGate.call_start``. Cancellation winning here means the supervisor
  ticket was never committed;
* **application post-commit forwarding** -- once gate-owned ``call_start`` sets the runtime
  latch ``COMMITTED``, cancellation must not wait for the still-held pre-start handoff while
  ``ExecutionSupervisorPort.start()`` performs bounded supervisor acceptance/launch work.
  It durably records the next Phase 7 cancel generation through an optimistic independent
  metadata transaction and forwards exact operation+ticket/digest cancellation immediately;
* **executor launch race** -- supervisor ``ExecutorLaunchGate`` decides cancellation versus
  backend process/domain creation. Cancellation winning here suppresses child spawn but
  does not erase the already-known Phase 4 effect if the ticket was durably accepted.

Application ordering:

#. authenticate owner and resolve target operation plus original ticket/executor evidence;
#. read the process-local ``DispatchCommitLatch``. If it appears ``PRE_COMMIT``, acquire the
   Phase 4 per-operation dispatch handoff and **recheck** it under that handoff;
#. if still ``PRE_COMMIT``, record durable application cancellation intent/generation and
   the legal lifecycle transition, so final start validation observes it and no supervisor
   ticket is committed;
#. if the recheck or initial read is ``COMMITTED``, do **not** wait for the start path to
   release the dispatch handoff. In a short optimistic SQLite transaction persist a strictly
   higher Phase 7 ``cancel_generation``/request fact without overwriting start/effect fields.
   If Phase 4 effect classification is already durable and lifecycle permits, transition
   ``running -> cancelling``; if start classification is still in flight, retain the Phase 7
   cancel intent and let the classification path project the legal lifecycle once effect
   truth is known;
#. immediately send exact operation ID + original ticket ID/digest + monotonic cancel
   generation over the concurrent UDS control path; include ``execution_id`` when known but
   do not require start response receipt;
#. if supervisor has not yet accepted the execution, it persists/updates the exact bounded
   pre-accept cancel intent; matching acceptance later attaches it atomically;
#. if supervisor already accepted, it resolves exactly one retained execution and applies
   the same/lower/higher generation rules under ``ExecutorLaunchGate``;
#. if cancel wins while executor state is ``accepted``/``launch_preparing`` and no
   ``launch_committed`` fact exists, durably suppress backend creation and prove the
   no-process cancellation closure;
#. if executor launch commit won, cancellation waits for the same gate's bounded create/
   receipt handoff and targets the exact returned domain; ambiguous create receipt causes
   conservative reconciliation/termination, never a false no-process cancellation;
#. for a known running domain, cooperative signal/grace first, then reviewed forced
   termination;
#. all descendants/accounting/private resources/output finalization verified;
#. only then application may commit ``cancelled``;
#. natural successful/failed completion winning the race remains ``succeeded``/``failed``;
#. lost signal/cleanup/supervisor receipt => remain ``cancelling`` or move ``uncertain`` as
   lifecycle/evidence permits, never falsely ``cancelled``.

The start-response classification path is cancellation-aware: it re-reads the latest Phase
7 cancel generation/lifecycle and writes exact effect reference/knowledge without forcing a
stale ``running`` state over ``cancelling``. A concurrently forwarded cancellation can
therefore win before backend create even though the original start RPC is still within the
Phase 4 handoff. No application SQLite transaction is held across either UDS call.

For an authoritative Phase 4 ``uncertain`` start whose supervisor evidence later shows a
possibly running/launch-committed execution, cancellation may be sent as reconciliation
action while the operation remains ``uncertain``; only complete stop/no-spawn + cleanup
proof permits the allowed ``uncertain -> cancelled`` transition.

A supervisor restart that sees durable cancellation before launch commit **must not spawn**.
A restart that sees launch commit with ambiguous create evidence must reconcile the exact
committed execution and must not create a replacement process. A matching pre-accept cancel
intent also survives restart until matching acceptance/expiry/reconciliation. These cases
are mandatory fault tests.

26. Timeout/resource termination
--------------------------------

Supervisor-enforced wall/resource limit is not owner cancellation unless the contract says
so. Verified resource/timeout termination normally maps to ``failed`` + ``known_effect``
with bounded reason code after all descendants/cleanup/output close.

If limit enforcement or cleanup outcome is unverifiable, state is ``uncertain``. A timeout
timestamp or missing PID alone does not prove process-tree termination.

A timeout/resource decision that arrives before backend launch commit consumes the same
``ExecutorLaunchGate`` as cancellation; it may suppress spawn under its own exact terminal
reason. It never races an unsynchronized launch worker.

27. Application restart
-----------------------

Ordinary MCP/application restart must not orphan an accepted command.

The supervisor remains an independent systemd service/process role. Application startup:

#. verifies executor UDS protocol/peer/build/profile compatibility;
#. loads authoritative Phase 4 nonterminal/uncertain command operations and retained fence
   owners;
#. treats any lost process-local ``DispatchCommitLatch`` as **non-authoritative** and never
   reconstructs pre/post-commit truth from it;
#. queries supervisor by exact operation/ticket/execution reference, including retained
   pending/attached cancel generation;
#. validates executor evidence generation, ticket digest, workspace/root/mount/profile and
   command identity;
#. reconciles not-accepted/accepted/launching/running/cancelling/terminal/uncertain evidence
   without creating a new ticket/process and without dropping a durable cancellation;
#. restores operation/status/output projection;
#. retains workspace fence until truthful terminal closure.

An app restart does not require session renewal solely to inspect/reconcile the already
acknowledged command. A still-valid session is required for a **new** command admission.
Session ending during app downtime prevents new starts but does not rewrite a start whose
Phase 4 ``call_start`` already linearized. If the supervisor proves the ticket never
accepted, the ordinary Phase 4 no-effect reconciliation rules apply; otherwise retained
execution/cancellation truth governs.

28. Supervisor restart/crash
----------------------------

Supervisor restart is a different fault from app restart and is not silently treated as
normal success.

On supervisor startup it verifies its own database/schema/integrity, scans retained
nonterminal execution evidence and pending cancel intents, and queries the selected backend
using exact execution-domain identity. PID absence alone is not no-effect because a process
may have run and modified workspace before disappearing.

Before any accepted execution is allowed to continue launch recovery, startup replays the
executor launch/cancel invariant: durable attached/pre-accept cancellation before
``launch_committed`` suppresses spawn; a retained ``launch_committed`` row can only reconcile
the one committed backend domain and can never allocate a replacement. A launch-commit/
create-receipt ambiguity stays executor-uncertain until independent backend evidence
resolves it.

If backend independently proves process/domain running, supervisor can reattach/reconcile
where selected profile permits. If it proves exact terminal exit/cleanup, expose that
truth. If evidence is missing/corrupt/contradictory or the backend cannot establish what
happened, mark executor evidence uncertain and application conservatively moves/retains
Phase 4 uncertainty/fence.

Bootstrap Phase 7 exit requires survival across **MCP application restart**, not necessarily
transparent supervisor crash. Supervisor-crash recovery is nevertheless fault-tested and
must never duplicate execution, ignore a durable cancellation, or falsely release workspace
authority.

29. Start-response loss and retained retry
-----------------------------------------

Lost UDS or MCP response never authorizes a fresh effect.

Application same-key retry first resolves the Phase 4 caller binding. If retained operation
is running/cancelling/terminal/uncertain, return/reconcile it; do not validate a new mutable
session/ticket as first admission and do not allocate another fence.

If application must query supervisor after ambiguous start, it uses exact original ticket/
operation identity. Supervisor returns retained accepted execution if present and includes
retained cancel state. If its healthy durable store proves exact ticket never accepted and
no matching pending acceptance can occur under deadline/generation rules, reconciliation
may establish known-no-effect. If that proof is unavailable, remain uncertain.

Cancellation does not depend on having received ``execution_id`` from the lost start
response: once application ``call_start`` is committed, the post-commit control path can
forward exact operation+ticket/digest cancellation while the start response is still in
flight. Supervisor either attaches it to the existing execution or durably latches it for
the matching first acceptance. A conflicting execution/ticket digest is rejected rather
than guessed.

A fresh caller key after an uncertain command does not bypass the retained workspace fence.

30. Development-session reduction versus command start
-------------------------------------------------------

Phase 6 ``DevelopmentSessionAuthorityGate`` is reused.

The command operation holds session gate across final session/trusted-time predicates,
Phase 4 obligation publication, process-wide ``call_start`` and immediate start-effect
classification. Therefore:

* end/expiry/revocation wins before command ``call_start`` -> zero committed execution;
* command ``call_start`` wins first -> the execution is committed-to-supervisor under the
  valid session; later end/expiry does **not** silently kill or reclassify it;
* post-commit owner cancellation may still be forwarded concurrently while the start RPC is
  in flight, but session reduction itself is not implicitly converted into targeted command
  cancellation after ``call_start``;
* an already-started/committed command continues until natural completion, explicit owner
  cancellation, or resource policy; session end simply blocks new command starts;
* same-key retained reconciliation after session end remains available.

This is deliberately consistent with Phase 6 file-mutation and session-activation start
linearization. Executor launch/cancel handling after supervisor acceptance is independent of
whether the development session later ends: no new owner authority is created by completing
or cancelling the already-committed execution.

31. Executable and script identity
----------------------------------

Profile resolves executable to exact allowed absolute path/identity before policy and binds
it into ticket. Supervisor reopens/revalidates exact executable type/identity and denies
symlink/substitution/setuid/setgid/capability-bearing executable unless profile explicitly
and safely supports it.

If command consumes a workspace script/config whose exact bytes materially define effect,
contract binds the exact workspace-relative path/object/content/mount identity and digest
under the acquired CHANGE/fence. Supervisor executes the validated file in the reviewed
workspace view; a stale/replaced script fails before accepted launch where exact proof can
be made.

Arbitrary code may still read other permitted workspace source at runtime; that is ordinary
command authority, not a promise the entire workspace is immutable. CHANGE prevents
Binnacle-managed concurrent changers for the command lifetime. Accepted out-of-band writer
model must be explicit in the command profile or stronger confinement required.

32. Proposed MCP surface and information classes
------------------------------------------------

Exact names remain proposals until promotion. A minimal set is:

``command_run``
   Consequential start; owner development-session member; structured argv; idempotent via
   caller key; default conservative workspace-changing semantics.

``operation_get``
   Read-only same-owner retained operation/status/reconciliation snapshot.

``operation_output``
   Read-only bounded output chunk/cursor for same-owner retained operation.

``operation_cancel``
   Authority-reducing/idempotent cancellation request against existing operation; no new
   arbitrary command authority. It may target the exact retained operation+ticket before
   the application has received ``execution_id`` and, after application ``call_start``
   commitment, must not be head-of-line blocked by the still-running start RPC.

``operation_list``
   Read-only bounded owner-scoped outstanding/recent operation listing.

The exact operation-status surface may later become shared with other phases; Phase 7 must
not create parallel competing lifecycle semantics. Contract promotion decides canonical
names/versions and whether generic status/output Tools apply beyond commands.

Command output is conservatively ``restricted-result``/untrusted content. Bounded status
metadata may be normal-result where the existing information contract allows. Raw
credentials/never-disclosable state can never become output authority.

33. Contract/schema/manifest promotion
--------------------------------------

Before runtime handler registration:

#. define exact command/status/output/cancel/list operation contracts;
#. reconcile the section 5 mapping of policy process / narrow broker-supervisor / command
   executor process with ``command-profiles.yaml`` and validators if required;
#. add trusted ticket deadline, workspace fence/root-mount, process-introspection/ptrace,
   network exposure, output, executor launch/cancel, post-commit cancel-forwarding and
   execution-evidence fields needed by this plan;
#. define exact input/output JSON schemas and bounded errors/result limits;
#. assign information/confirmation/session-host profile requirements;
#. add exact manifest entries and bump manifest version;
#. update security/evaluation fixtures for single-use replay, UDS loss, app restart,
   cancellation-before-start, post-commit cancellation while start response is in flight,
   pre-accept cancel latching, cancellation-before-spawn, cancellation-during-launch,
   output cursors, listener exposure, process-introspection isolation, protected-state
   access, and workspace coordination;
#. validate all schema pointers, handler bindings, versions, annotations, profile digests,
   and current compatibility profiles;
#. only then compose handlers.

MCP Task adaptation remains optional/evidence-gated. Tool contracts work without Tasks.

34. Expected repository implementation set
------------------------------------------

Representative paths:

::

   src/binnacle/domain/execution.py
   src/binnacle/ports/execution.py
   src/binnacle/application/execution.py
   src/binnacle/application/operation_projection.py
   src/binnacle/adapters/executor_ipc/__init__.py
   src/binnacle/adapters/executor_ipc/client.py
   src/binnacle/executor/__init__.py
   src/binnacle/executor/server.py
   src/binnacle/executor/protocol.py
   src/binnacle/executor/tickets.py
   src/binnacle/executor/state.py
   src/binnacle/executor/output.py
   src/binnacle/executor/backend.py
   src/binnacle/executor/reconcile.py
   migrations/versions/0004_execution_operations.py
   migrations_executor/env.py
   migrations_executor/versions/0001_executor_evidence.py
   deploy/systemd/binnacle-executor.service
   tests/unit/domain/test_execution.py
   tests/unit/application/test_execution.py
   tests/unit/executor/test_tickets.py
   tests/unit/executor/test_launch_cancel.py
   tests/integration/test_executor_ipc.py
   tests/integration/test_executor_restart.py
   tests/integration/test_execution_backend.py
   tests/property/test_execution_lifecycle.py

The separate executor migration environment targets only executor evidence DB. It never
connects to or migrates the application DB. Application migration ``0004`` adds only
command-specific authoritative metadata/cancellation/fence correlation as needed.

35. Application and executor ports
----------------------------------

Representative contracts:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class ExecutionTicket:
       ticket_id: str
       operation_id: str
       ticket_sha256: str
       command_profile_id: str
       workspace_id: str
       workspace_root_identity_sha256: str
       workspace_mount_identity_sha256: str
       workspace_fence_version: int
       executable_identity_sha256: str
       argv_sha256: str
       environment_sha256: str
       resource_plan_sha256: str
       sandbox_plan_sha256: str
       process_isolation_plan_sha256: str
       expires_at: datetime
       single_use_nonce: str
       ...

   @dataclass(frozen=True, slots=True)
   class ExecutionStartReceipt:
       execution_id: str
       evidence_generation: int
       accepted: bool
       accepted_at: datetime | None
       executor_reference: str | None
       receipt_sha256: str

   class ExecutionSupervisorPort(Protocol):
       async def start(self, ticket: ExecutionTicket) -> ExecutionStartReceipt: ...
       async def get(self, operation_id: str) -> ExecutorSnapshot: ...
       async def read_output(
           self, operation_id: str, stream: OutputStream, offset: int, max_bytes: int
       ) -> ExecutorOutputChunk: ...
       async def cancel(
           self,
           operation_id: str,
           ticket_id: str,
           ticket_sha256: str,
           cancel_generation: int,
           execution_id: str | None = None,
       ) -> ExecutorCancelReceipt: ...
       async def list(self, operation_ids: tuple[str, ...]) -> tuple[ExecutorSnapshot, ...]: ...

   class ExecutionDomainBackend(Protocol):
       async def create(self, accepted: AcceptedExecution) -> DomainHandle: ...
       async def inspect(self, handle: DomainHandle) -> DomainSnapshot: ...
       async def signal(self, handle: DomainHandle, request: SignalRequest) -> SignalReceipt: ...
       async def terminate_tree(self, handle: DomainHandle) -> TerminationReceipt: ...
       async def cleanup(self, handle: DomainHandle) -> CleanupReceipt: ...

   class ExecutorEvidenceStore(Protocol):
       async def accept_once(self, ticket: ValidatedTicket) -> AcceptanceResult: ...
       async def record_preaccept_cancel(
           self,
           operation_id: str,
           ticket_id: str,
           ticket_sha256: str,
           cancel_generation: int,
       ) -> PreacceptCancelResult: ...
       async def transition(self, event: ExecutorEvidenceEvent) -> ExecutorSnapshot: ...
       async def record_cancel_generation(
           self, execution_id: str, cancel_generation: int
       ) -> ExecutorSnapshot: ...
       async def lookup_ticket(self, ticket_id: str) -> ExecutorSnapshot | None: ...

Application service consumes Phase 4 operation store/audit/policy + Phase 6
``WorkspaceAccessCoordinator``/``DevelopmentSessionAuthorityGate`` + supervisor port. The
application also owns a process-local ``DispatchCommitLatch`` per in-flight first start and
a durable monotonic Phase 7 cancel-generation field; neither is a substitute for Phase 4
effect truth. The executor never imports application persistence/policy/MCP modules.

36. Error and diagnostic projection
-----------------------------------

Representative closed errors, pending contract promotion:

* ``command_profile_unsupported``;
* ``command_executable_not_allowed``;
* ``command_argument_invalid``;
* ``command_cwd_invalid``;
* ``command_workspace_busy``;
* ``command_workspace_identity_mismatch``;
* ``command_mount_boundary_violation``;
* ``command_session_not_effective``;
* ``command_ticket_expired``;
* ``command_ticket_conflict``;
* ``command_ticket_replayed``;
* ``command_executor_unavailable``;
* ``command_executor_integrity_failed``;
* ``command_start_uncertain``;
* ``command_launch_uncertain``;
* ``command_isolation_unsupported``;
* ``command_process_introspection_unsupported``;
* ``command_network_profile_unsupported``;
* ``command_listener_exposure_required``;
* ``command_resource_limit_exceeded``;
* ``command_output_limit_exceeded``;
* ``command_output_expired``;
* ``command_cancel_pending``;
* ``command_cancel_uncertain``;
* ``command_cleanup_uncertain``.

Errors never reveal another controller's operation, raw ticket/nonce, credential, protected
host path, environment secret, or root-broker detail.

Structured diagnostics may include operation/execution IDs, command profile, safe executable
identity/name, workspace ID, state/evidence/launch/cancel generations, resource/output
counters, cgroup/backend class, reason codes, protocol/build/profile digests and
reconciliation state. Command argv/output/path content is not routine log labels.

37. Test strategy and real evidence
-----------------------------------

37.1 Unit/property
~~~~~~~~~~~~~~~~~~

Prove:

* exact structured command normalization/fingerprint;
* caller-binding-first retry before mutable session/ticket state;
* ticket digest/expiry/boot/nonce validation;
* executor accept-once under concurrent duplicate start frames;
* same ticket returns one execution; changed digest never launches;
* fixed Phase 6 CHANGE/fence ownership from post-policy admission through terminal cleanup;
* exact Phase 4 start gate/order and audit-failure-before-call_start => zero supervisor
  start request;
* session end/expiry before call_start => zero accepted execution; call_start-first may
  continue;
* application cancellation-before-start wins and suppresses ticket acceptance;
* after gate-owned call_start commits, application cancellation does not wait for the
  still-running start RPC/DispatchHandoffGate and can durably forward exact operation+
  ticket/digest cancellation;
* cancellation racing before supervisor acceptance is retained as one pre-accept intent and
  atomically attached by matching acceptance;
* start receipt/effect classification never overwrites a newer cancel generation or legal
  cancelling state;
* executor cancellation immediately after acceptance but before launch commit suppresses
  backend process creation and closes one accepted execution as ``known_effect``;
* launch-commit-first cancellation targets the exact created/possibly-created domain;
* concurrent cancel versus backend create has one winner under ``ExecutorLaunchGate`` and
  never produces an orphan process;
* same/lower cancel-generation replay is idempotent and a higher generation persists before
  signal/spawn-suppression action;
* supervisor restart with pre-accept/attached cancel-before-launch never later spawns;
  launch-commit/create-receipt ambiguity never creates a replacement domain;
* output empty-vs-EOF/truncated/expired cursor semantics;
* top-PID exit cannot release fence while descendant/cleanup unknown;
* app restart reconciliation never allocates new ticket or infers commit state from the
  lost process-local latch;
* executor uncertainty never creates no-effect proof or fresh execution;
* operation lifecycle parity including uncertain terminal-only reconciliation.

37.2 UDS/integration
~~~~~~~~~~~~~~~~~~~~

Test:

* wrong peer UID/GID, socket mode, stale version, malformed/oversize/truncated frame;
* duplicate request/correlation IDs and ticket replay;
* start/control request concurrency: deliberately hold backend create while a post-commit
  cancellation request is processed and reaches ``ExecutorLaunchGate`` rather than being
  head-of-line blocked behind ``start_execution``;
* response loss after executor acceptance then same ticket retry -> same execution ID, one
  process-domain creation;
* cancellation by exact operation+ticket while the start response/execution ID is lost;
* cancellation arriving just before first acceptance -> durable pending cancel -> matching
  acceptance -> zero backend create;
* application SIGKILL after accepted start; supervisor/process/output continue; replacement
  app reconnects and resolves retained cancellation/effect state;
* supervisor unavailable -> no direct-subprocess fallback;
* supervisor DB WAL/FULL/schema/integrity failure -> new starts fail closed;
* supervisor crash after pre-accept cancel, accept before launch, after durable cancel-before-
  launch, after launch commit before create receipt, during launch, while running, during
  output, cancellation, cleanup; never duplicate, never ignore durable cancellation and
  never false fence release;
* UDS output chunk bounds/backpressure;
* application and executor DB files never opened by the other process.

37.3 Linux/process/security
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Candidate backend tests:

* dedicated unprivileged identity/no-new-privileges/no capabilities/setuid gain;
* distinct supervisor/command UID for the preferred profile, or explicit evidence for a
  same-UID profile that all process-introspection tests below fail closed;
* command attempts to ptrace supervisor/application and receives denial;
* command attempts ``process_vm_readv``/``process_vm_writev`` against supervisor/application
  and receives denial;
* command cannot open/read ``/proc/<supervisor-or-app-pid>/mem``, ``fd``, ``fdinfo`` or
  equivalent sensitive process surfaces;
* command cannot send arbitrary signals/control supervisor/application outside the exact
  reviewed execution lifecycle;
* descendants cannot escape the same process-introspection boundary;
* exact workspace root/mount/no-submount binding and replacement/bind-mount attacks;
* command cannot read ``/etc/binnacle``, app SQLite/audit/recovery, executor DB/output/
  socket, root-broker socket, SSH/GPG keys/agents, protected ``.git`` when conservative
  Phase 7 profile masks it;
* inherited FD/socket/environment leakage;
* child/grandchild/double-fork/setsid/daemon/fork-bomb remain in accounting/termination
  domain;
* CPU/memory/swap/PID/open-file/workspace byte+inode/temp/output/wall limits descendant-wide;
* default network denied;
* development IPv4/IPv6/DNS allowed under profile;
* loopback listener allowed when selected, non-loopback denied without typed exposure and
  allowed only with exact exposure authority if candidate backend can prove it;
* raw packet/network-admin/protected Unix/device/credential-agent denial;
* natural exit/cancel/timeout/resource race;
* forced cancellation leaves no unknown descendants before cancelled/fence release.

37.4 Real Pi
~~~~~~~~~~~~

Real candidate Pi evidence records:

* selected supervisor and command process identities/systemd units/domains;
* exact execution-domain backend and cgroup/systemd behavior;
* filesystem/protected-state view enforcement;
* exact ``/proc``/ptrace/process-vm/signal isolation, especially if a shared UID is proposed;
* root mount/no-submount handling;
* process-tree accounting across daemon/fork patterns;
* UDS peer credentials/frame/concurrent-control behavior;
* executor evidence SQLite durability, pre-accept cancel retention and response-loss recovery;
* application post-commit cancel forwarding plus executor launch/cancel gate behavior and
  crash recovery;
* output spool fsync/limits/performance;
* app restart while a command runs;
* supervisor crash behavior;
* resource limits;
* network/listener rules;
* no credentials/control sockets/devices;
* exact Python/systemd/kernel versions needed to interpret evidence.

No candidate feature is marked supported merely because the documentation describes it.

37.5 Real ChatGPT
~~~~~~~~~~~~~~~~~

After promotion, real ChatGPT evidence covers catalogue discovery; session-authorised
``command_run``; structured argv; tests/quality command; incremental output; status;
cancellation including prompt cancellation after gate-owned start commitment while start
receipt is delayed, cancellation after accepted start, same-key retry/lost response;
application restart/reconnect; outstanding listing; bounded result behavior; and host
Task/status behavior only if actually observed.

38. Holistic invariant pass before review
-----------------------------------------

Every Phase 7 review walks these pipelines rather than patching one Tool at a time.

New command start::

   normalize/authenticate/session/workspace/command
     -> caller-binding-first retained lookup/minimal received identity
     -> required received audit
     -> policy
     -> exclusive Phase6 CHANGE
     -> post-policy exact-self durable workspace fence + command metadata/ticket binding
     -> allowed/authorised audit
     -> running + effect.intent_recorded
     -> Phase4 per-operation handoff
     -> DevelopmentSessionAuthorityGate
     -> ConsequentialBoundaryGate
     -> final controller/device/session/profile/root/mount/fence/executable/resource/
        network/cancel/audit/recovery OP-BOUNDARY
     -> durable audit obligation
     -> gate-owned call_start + process-local DispatchCommitLatch=COMMITTED
     -> concurrent post-commit cancel forwarding becomes eligible
     -> supervisor peer/ticket validation + durable accept-once
        (atomically attaches matching pre-accept cancel)
     -> ExecutorLaunchGate: cancel-before-launch OR one bounded launch commit/create receipt
     -> immediate application effect-reference/effect-knowledge classification without
        overwriting newer cancel intent/state
     -> post-start audit/obligation closure
     -> independent process/output lifecycle
     -> truthful terminal + descendant/private-resource/output closure
     -> application terminal audit + workspace fence/CHANGE release
     -> restart/reconciliation
     -> same-key retained retry

Cancellation::

   same-owner retained operation lookup
     -> read DispatchCommitLatch
     -> PRE_COMMIT: Phase4 per-operation cancellation/start handoff + recheck
        -> durable application cancel generation/state -> zero start if cancel wins
     -> COMMITTED: no wait on still-held start handoff
        -> optimistic durable Phase7 cancel generation/intent
        -> exact operation+ticket/digest supervisor cancellation concurrently with start RPC
     -> pre-accept cancel latch OR existing execution lookup
     -> ExecutorLaunchGate durable cancel generation
     -> cancel-before-launch suppresses process creation OR launch-first targets one domain
     -> start classification preserves newer cancel state/generation
     -> cooperative then forced descendant termination when process exists
     -> output/private-domain cleanup proof
     -> cancelled OR natural succeeded/failed OR uncertain
     -> fence release only after truthful closure

Process isolation::

   promoted command profile
     -> distinct child UID preferred OR exact same-UID process-isolation plan
     -> supervisor independently validates sandbox/process plan digest
     -> bounded /proc + ptrace/process-vm/signal boundary established
     -> only then launch commit may cross backend process-create boundary

Output/status::

   authenticate owner -> retained application operation
     -> bounded executor evidence query
     -> information/result policy
     -> exact offset/cursor projection
     -> no state/effect invention from output/process absence

Review explicitly stresses: audit trip/start race; session end/start race; application
pre-commit cancel/start race; post-commit cancel while start RPC/handoff still active;
pre-accept cancel/start frame race; executor cancel/launch race; executor accept/response-
loss; app crash; supervisor crash at pre-accept/accepted/cancelled/launch-committed/create-
receipt states; ticket replay after terminal; workspace root/mount replacement; out-of-band
source write; process daemon escape; same-UID ptrace/proc/process-vm escape; output flood;
resource/cancel cleanup; network listener authority; protected-state/credential access;
executor/application DB ownership; uncertain fence retention; same-key retry after session
end; and every accepted/no-accept/ambiguous outcome.

39. Plan acceptance checklist
-----------------------------

Accept this plan only when:

* main MCP process cannot launch arbitrary subprocess directly;
* supervisor is independent/unprivileged and Phase 9 root broker remains separate;
* existing logical policy/broker/executor boundaries map coherently without hidden fourth
  privileged service;
* ticket is local peer-authenticated, single-use and independently validated;
* executor owns minimal separate durable evidence sufficient for replay/restart, not app DB;
* app remains authoritative Phase 4 lifecycle owner;
* default commands consume Phase 6 CHANGE/fence for complete descendant lifetime;
* root/mount/no-submount and protected-state view are exact/fail-closed;
* distinct command UID is preferred; same-UID requires explicit bounded ``/proc`` plus
  denied ptrace/process-vm/arbitrary-signal access to supervisor/application;
* start uses Phase4 per-op/session/process gates and process-gate ``call_start``;
* gate-owned call_start publishes a runtime post-commit discriminator so cancellation after
  commit cannot be blocked behind the still-running pre-start handoff/start RPC;
* post-commit cancellation has a concurrent supervisor control path and a bounded exact
  pre-accept cancellation latch, so a cancel racing first acceptance is not lost;
* start-effect classification is field-aware and never overwrites a newer cancellation
  generation/legal lifecycle state;
* executor accept-once precedes launch and survives lost response;
* ``ExecutorLaunchGate`` serializes accepted/launching cancellation with backend create;
* durable cancel-before-launch can never later spawn; launch-first cancellation targets the
  one committed domain or remains conservative if create receipt is ambiguous;
* accepted execution can never be respawned from a fresh ticket/retry;
* known-effect/no-effect/uncertain mapping is explicit, including cancellation-before-child-
  spawn after supervisor acceptance remaining ``known_effect``;
* lifecycle handles uncertain-running evidence without inventing ``uncertain -> running``;
* application pre-commit/start, application post-commit cancel forwarding, session/audit,
  and executor launch/cancel races each have one explicit linearization;
* output is independent/bounded/cursor-correct and never process truth;
* all descendants/resources/output/private state close before verified cancellation/fence
  release;
* ordinary app restart preserves acknowledged execution visibility without treating the
  lost process-local dispatch latch as durable truth;
* supervisor crash never implies no-effect, duplicate start, or ignored durable cancellation;
* development networking and non-loopback exposure remain distinct/enforceable profile
  properties;
* credentials/control-plane/root broker/devices remain unavailable;
* contracts/schemas/manifest precede handler exposure;
* MCP Tasks and candidate-Pi mechanisms remain evidence-gated;
* no runtime/host evidence is fabricated.

40. Implementation order
------------------------

When predecessor evidence permits implementation:

#. promote/reconcile command contracts, schemas, manifest and logical broker/executor
   mapping, including process-introspection, post-commit cancel-forwarding, pre-accept cancel
   and executor launch/cancel fields;
#. add application command metadata migration ``0004`` with monotonic Phase 7 cancel
   generation/correlation fields;
#. create separate executor evidence migration/setup and executor state directory,
   including bounded pending-cancel storage;
#. implement versioned framed JSON UDS protocol + peer auth + frame/schema ceilings +
   concurrent start/control dispatch;
#. implement supervisor evidence store and concurrent accept-once/pre-accept-cancel/
   tombstone tests;
#. implement per-execution ``ExecutorLaunchGate`` + durable cancel-generation/launch-state
   recovery before any backend process creation;
#. implement application executor client/reconciliation/cancel-by-operation+ticket port;
#. implement process-local ``DispatchCommitLatch`` and the field-aware post-commit cancel
   forwarding path before backend launch is enabled in tests;
#. implement exact executable/cwd/workspace/root/mount/ticket normalization;
#. integrate Phase 6 CHANGE + durable mutation fence into command post-policy admission;
#. implement Phase 4 received/policy/authorised/running/effect-intent + per-op/session/
   process-gated ``call_start`` path and cancellation-aware start classification;
#. implement candidate ``ExecutionDomainBackend`` behind evidence-gated profile, with
   explicit child-vs-supervisor process-introspection isolation;
#. implement process/domain identity and descendant-wide resource accounting;
#. implement output spool/drain/digest/truncation/retention;
#. implement status/output/outstanding application projection;
#. implement application pre/post-commit cancellation + executor launch/cancel
   linearization + descendant cleanup;
#. implement app restart reconciliation;
#. implement supervisor restart/fault reconciliation including pending-cancel/accepted/
   cancel/launch-commit recovery;
#. add filesystem/credential/FD/process-introspection/network/listener/process/resource
   adversarial tests;
#. validate contract/schema/manifest/profile parity;
#. compose runtime Tools only when all promotion prerequisites are current;
#. collect candidate-Pi evidence;
#. collect real ChatGPT evidence and only then claim Phase 7 exit.

41. Explicit provisional items
------------------------------

Remain evidence-gated after plan acceptance:

* exact candidate execution-domain backend (transient unit, delegated cgroup, or another
  reviewed systemd-backed mechanism);
* exact filesystem-view mechanism sufficient for protected host-state exclusion;
* exact network/listener enforcement mechanism;
* whether supervisor and child may safely share an OS UID; a shared UID is unsupported until
  the selected profile proves bounded ``/proc`` and denied ptrace/process-vm/process-control
  access, otherwise use a distinct child identity;
* exact cgroup v2/systemd capabilities and restart semantics on the candidate Pi;
* exact executor evidence DB/storage throughput and output fsync cadence;
* exact bounded backend-create deadline needed by ``ExecutorLaunchGate``;
* exact concurrent UDS request-handling mechanism and latency budget needed so cancellation
  control is not head-of-line blocked by an in-flight start/backend-create call;
* exact pending-cancel retention ceiling tied to ticket expiry/replay window;
* exact inline stdin/control-frame/result chunk maxima within reviewed upper bounds;
* exact set of allowed executables/profile limits;
* whether generic Phase 7 commands see any ``.git`` metadata before Phase 8;
* actual ChatGPT Tool/Task/status/output behavior;
* actual catalogue refresh and result-size behavior.

Those items may change profile-specific mechanism/limits. They do not change the mandatory
process separation, single-use acceptance, application post-commit cancel forwarding,
executor launch/cancel serialization, durable idempotency, Phase4 gated start, Phase6
workspace coordination, protected-state/process-introspection exclusions, truthful
uncertainty, or no-direct-subprocess invariants without a separately reviewed revision.

42. Deferred work
-----------------

Phase 7 defers PTY/interactive terminal, shell contract, advanced sandbox hardening not
needed for the selected minimum profile, generic container management, arbitrary user
process management, credentialed Git push/signing, root package/service/restart, hardware,
multi-tenant executor scheduling, distributed execution, remote workers, rich MCP Task
integration, and performance tuning beyond measured Bootstrap blockers.

After the real self-hosting loop works, later phases may strengthen isolation or broaden
profiles based on evidence rather than expanding Bootstrap preemptively.
