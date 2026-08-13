Binnacle Phase 9 Detailed Implementation Plan
==============================================

:Phase: 9 -- Implement the minimal privileged broker and self-management path
:Status: provisional
:Planning status: evidence-independent engineering design; runtime promotion remains gated
                  by predecessor implementation exits and real development-Pi evidence
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 4 durable-operation kernel, merged Phase 6 development-workspace
             plan, merged Phase 7 durable execution-supervisor plan, merged Phase 8 Git
             development plan; Phase 4 and Phase 8 implementation exits before privileged
             runtime promotion
:Primary objective: Give ChatGPT only the privileged host capabilities required to keep
                    Binnacle self-development moving, with deterministic restart and
                    recovery that remain truthful when the application itself disappears

1. Purpose and phase boundary
-----------------------------

Phase 9 introduces the first intentional root authority in Bootstrap. Root authority is
confined to a separate privileged broker and a closed semantic vocabulary. The
network-facing MCP/application process remains unprivileged. The Phase 7 execution
supervisor and command children remain unprivileged. Phase 8 Git/credential children do
not inherit root authority.

The minimum privileged vocabulary is:

* bounded inspection of required operating-system package state;
* installation of one exactly prepared development-package transaction;
* bounded inspection of the exact Binnacle development service;
* restart of that exact service when no candidate/runtime rollback semantics are needed;
* restart preflight against durable outstanding work;
* the controlled Binnacle self-restart path with an independently restorable
  last-known-good runtime;
* reboot only if later real Bootstrap evidence proves it necessary.

Phase 9 does not introduce:

* a generic root shell, ``sudo`` forwarding, arbitrary executable or arbitrary argv;
* arbitrary root filesystem read/write/delete;
* arbitrary systemd unit management;
* arbitrary package-manager flags, repositories, removals, full upgrades or autoremove;
* user/group, firewall, network-administration, mount, device, kernel, bootloader or
  firmware management;
* container-engine administration;
* raw reusable credentials visible to ChatGPT or ordinary child processes;
* generic privileged configuration editing;
* production release/update automation.

Plan acceptance, runtime promotion and phase exit remain separate facts. Review/CI may
accept this provisional document without claiming that the selected Raspberry Pi already
supports the required systemd, package-manager, filesystem or recovery mechanisms.

2. Governing invariants
-----------------------

2.1 The application is never root
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MCP/application process uses its normal Binnacle identity. The broker is a distinct
root-owned systemd service. The application remains the sole authoritative writer of the
Phase 4 operation database. The broker never opens that database.

2.2 Phase 7 execution is never an elevation path
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``command_run`` cannot ask for root and cannot connect to the broker. Phase 9 operations
are typed application use cases that create one operation-scoped privileged ticket. The
broker socket, credentials and protected state are denied to Phase 7/8 children.

2.3 Privilege is semantic and target-bound
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A privileged ticket grants one reviewed action against one protected target/profile. It
is not a generic delegation token. The broker independently validates peer identity,
ticket integrity, action, target, maximum effect and current root-side predicates.

2.4 Restart truth survives the process being restarted
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before the application service is stopped, root-protected broker/recovery storage must
contain the exact restart checkpoint and a previously verified last-known-good runtime
that can be selected/restored without cooperation from the candidate application.

2.5 No-effect truth is broker-gated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After Phase 4 commits a privileged dispatch, absence of a broker replay row at one instant
is never proof that no root effect can later occur. A delayed/queued broker handler and
recovery must race through one durable accept-or-seal boundary. ``no_accept_proven`` is a
terminal broker acceptance-state fact, not an observation of an empty database.

2.6 Accepted privileged work outlives ticket/session expiry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Expiry and mutable owner/session predicates decide whether a new ticket may be accepted.
Once the exact ticket is durably accepted, later ticket expiry, application replacement
or development-session end cannot erase the accepted work. Recovery resumes/reconciles
the accepted privileged operation to a truthful terminal/uncertain state.

2.7 Restart owns the workspace change boundary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A point-in-time restart preflight is not exclusion. Every simple or controlled restart of
a service whose runtime is sourced from the registered development workspace acquires the
Phase 6 exclusive ``WorkspaceAccessGate.CHANGE`` guard and durable workspace mutation
fence during post-policy admission. The same operation retains durable fence ownership
through broker acceptance, service disappearance, candidate/LKG selection, recovery,
post-effect audit and truthful terminal closure. Application replacement does not release
or steal it; the replacement starts workspace access recovery-closed and reconciles the
exact retained fence owner before any new content reader or changer may enter.

3. Source-of-truth composition
------------------------------

Phase 9 consumes earlier foundations:

* Phase 4 owns caller-binding-first idempotency, lifecycle, audit, final OP-BOUNDARY,
  audit obligations, effect knowledge and retained retry;
* Phase 6 owns development-session authority, the exclusive workspace ``CHANGE`` guard
  and durable mutation fence consumed by service/self-restart;
* Phase 7 owns durable command/process truth and outstanding-operation inspection;
* Phase 8 owns exact candidate Git revision, signed commit/push semantics and Git process
  authority.

Broker evidence is independent root-side evidence. It does not become a second
owner-visible lifecycle database and does not rewrite Phase 4 state directly.

4. Proposed host-facing semantic surface
----------------------------------------

Names remain proposals until operation contracts, schemas, information classes,
confirmation/authority classifications and manifest entries are reviewed and promoted.
The working Phase 9 set is:

* ``privileged_prepare`` -- one no-effect preparation Tool with a closed action
  discriminator, never arbitrary root vocabulary;
* ``package_inspect``;
* ``package_install``;
* ``binnacle_service_inspect``;
* ``binnacle_service_restart``;
* ``restart_preflight``;
* ``binnacle_restart``;
* ``binnacle_runtime_inspect``;
* ``host_reboot`` only if separately evidenced and promoted.

``binnacle_service_restart`` is intentionally distinct from ``binnacle_restart``. The
former restarts the exact fixed service without changing the candidate/LKG runtime. The
latter is the full self-management checkpoint, candidate-verification and rollback path.
A request cannot downgrade a candidate-changing restart to the simple service operation.

Read-only inspection operations create no consequential Phase 4 effect unless a future
contract explicitly requires one. Package installation, service restart, controlled
self-restart and any future reboot are consequential operations.

The initial contract classification is frozen for implementation review:

.. list-table:: Initial Phase 9 contract classification
   :header-rows: 1

   * - Tool
     - Maximum effect
     - Information class
     - Host class
   * - ``privileged_prepare``
     - no-effect preparation
     - ``normal-result``
     - HC0
   * - ``package_inspect``
     - observation
     - ``normal-result``
     - HC0
   * - ``binnacle_service_inspect``
     - observation
     - ``normal-result``
     - HC0
   * - ``restart_preflight``
     - observation
     - ``normal-result``
     - HC0
   * - ``binnacle_runtime_inspect``
     - observation
     - ``normal-result``
     - HC0
   * - ``package_install``
     - privileged change
     - ``restricted-result``
     - HC2
   * - ``binnacle_service_restart``
     - self-management
     - ``restricted-result``
     - HC2
   * - ``binnacle_restart``
     - self-management
     - ``restricted-result``
     - HC2
   * - ``host_reboot`` (unpromoted)
     - destructive privilege
     - ``restricted-result``
     - HC2

Inspection/preflight results remain ``normal-result`` only by returning bounded sanitized
owner-safe facts: no other-controller identity, raw operation payload, protected path,
credential, configuration value or unrestricted journal output. A future richer result is
``restricted-result`` and must receive a separately reviewed host class.

All HC2 execute Tools require an exact preceding ``privileged_prepare`` result with
``prepared_operation_id``, single-use execution nonce, expiry, normalized action/target,
maximum effect, exact current-state binding, cancellation/recovery disclosure and the
additional HC2 privilege/destructive/credential/audit fields required by
``spec/policy/host-confirmation-classes.yaml``. Preparation grants no authority and runs no
package-manager/systemd/runtime-selector effect. Execution must match and consume the
prepared record exactly, then revalidate current state. Package preparation includes the
complete ``PackageTransactionPlan``; self-restart preparation includes the exact tested
candidate and complete LKG/runtime-slot evidence. Direct execute, cached metadata, batch,
MCP Task, reconnect, another conversation and argument/device substitution cannot bypass
the prepare-confirm-execute route.

5. Protected configuration profiles
------------------------------------

5.1 ``PrivilegedBrokerProfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* broker protocol/profile ID and version;
* exact broker service and root-owned Unix-socket identity;
* expected broker UID/GID and exact allowed application peer UID/GID;
* allowed semantic action set;
* frame/deadline/rate ceilings;
* broker evidence/checkpoint roots and mount/ownership identities;
* exact root-owned broker executable/runtime identity and broker migration head;
* ticket verification key/reference and algorithm profile;
* service hardening digest;
* candidate-Pi capability-evidence digest.

5.2 ``BinnacleServiceProfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* exact development service unit name;
* exact development workspace/source identity;
* exact runtime-selector/recovery root;
* exact immutable-slot root/current-selector identity, layout generation and byte/inode/
  retained-slot ceilings;
* service user/group;
* protected configuration/policy/manifest identities;
* expected executable/entry point;
* exact effective stable unit/drop-in digest and application/executor/Git-credential/
  privileged-broker migration heads;
* exact deployed Phase 7 executor, Git-credential broker and privileged-broker build,
  protocol/profile, unit/config and readiness identities;
* readiness contract and restart deadline;
* allowed service lifecycle actions;
* checkpoint/LKG storage identity;
* local recovery marker path/version.

No model request supplies an arbitrary unit name.

5.3 ``PackageProfile``
~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* exact supported package manager/executable identity;
* exact trusted repository/source profile;
* allowed package-name policy;
* version-pinning requirements;
* whether dependencies may be installed;
* which action classes are forbidden, including package removal by default;
* repository-metadata freshness/identity requirements;
* transaction-plan and artifact verification method;
* package database lock semantics;
* non-interactive environment;
* network/time/output ceilings;
* package evidence parser/version;
* reboot-required observation policy.

Repository addition, full upgrade, dist-upgrade, arbitrary remove/autoremove and raw
package-manager options are outside Bootstrap.

6. Privileged ticket contract
-----------------------------

Each consequential broker call carries an application-issued ticket containing a closed,
canonical structure with at least:

* Phase 4 ``operation_id``;
* controller ID/epoch digest;
* device ID/epoch;
* semantic operation contract/version;
* broker profile/version;
* exact semantic action and target profile/identity;
* canonical request fingerprint;
* maximum-effect digest;
* protected current-state binding digest;
* Phase 4 policy/admission evidence reference/digest;
* application build/config/policy digests;
* issue time and pre-accept expiry;
* single-use random nonce with at least 128 random bits;
* ticket ID and cryptographic integrity proof.

Operation-specific tickets add exact package transaction, service, candidate/LKG or
reboot facts. Ticket expiry blocks first acceptance only. A retained accepted ticket
remains recoverable after expiry.

Exactly one immutable privileged ticket binding exists for each Phase 4 operation. During
post-policy admission and before Phase 4 ``call_start``, the application durably binds the
operation to one ``ticket_id``, ticket digest, nonce, semantic action, target/profile and
broker evidence generation. Every retained retry, replacement application and reconciliation
path reuses that ticket; a second ticket ID/digest/nonce for the same operation is a conflict,
not a replacement attempt. Ticket ID and nonce are also globally unique so one ticket cannot
be rebound to another operation.

7. Root broker process and IPC
------------------------------

The preferred topology is:

::

   unprivileged MCP/application
       -> restricted root-owned AF_UNIX socket
       -> root broker peer/ticket validator
       -> closed semantic privileged adapter
       -> package manager / systemd / recovery storage

The protocol is explicitly versioned, schema-defined framed JSON. It forbids pickle,
arbitrary Python object deserialization, generic path/argv/environment payloads and
unreviewed FD passing.

Transport controls include:

* root-owned socket directory not writable by application/executor children;
* exact socket mode/group or reviewed socket activation;
* Linux peer credentials checked against the exact application identity;
* fixed frame/schema/nesting/string/list ceilings;
* request/operation/ticket correlation;
* bounded read/write/deadline behavior;
* exact protocol-version mismatch failure;
* rejection of Phase 7 command UID, Phase 8 Git child UID and arbitrary local peers.

8. Broker durable evidence and acceptance state
-----------------------------------------------

The broker owns a separate root-protected durable store. SQLite with ``synchronous=FULL``
is preferred when candidate-Pi evidence supports it. Checkpoint/runtime-slot payloads may
use fixed root-owned filesystem storage with explicit file and parent-directory fsync.

The broker store records only privileged replay/recovery evidence, including:

* accepted ticket digest/nonce and operation/action/target;
* broker evidence generation;
* acceptance state;
* privileged subeffect state and exact effect reference;
* bounded result/evidence digests;
* package transaction-plan identity;
* restart/checkpoint/runtime-slot identities;
* candidate/LKG verification/recovery states;
* terminal or uncertain outcome and retention timestamps.

It never stores raw controller, SSH or signing credentials.

8.1 Operation-binding-scoped ``BrokerAcceptanceGate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every exact Phase 4 ``operation_id`` owns one broker acceptance gate (or an equivalent
serialized FULL transaction boundary). The first retained broker binding stores the one
expected ticket ID/digest/nonce/action/target/generation as compared data beneath that gate;
ticket digest is not part of an isolating lock key. The gate is shared by:

* ``accept_once``;
* ``seal_no_accept``;
* retained replay/reconciliation that needs to determine the acceptance winner.

No root package/systemd/recovery effect runs while this acceptance gate is held. Gate
ownership ends after the durable acceptance/seal decision is committed.

8.2 ``accept_once``
~~~~~~~~~~~~~~~~~~~

Under the gate and one FULL transaction:

#. verify peer-independent ticket integrity/action/target/replay identity;
#. create/find the operation's one immutable ticket binding and reject any different
   ticket ID, digest, nonce, semantic action, target or evidence generation;
#. if a matching no-accept tombstone exists, return retained ``no_accept_proven`` and
   create no accepted row;
#. if the accepted row exists, return retained acceptance;
#. otherwise verify pre-accept expiry and root-side admission predicates and atomically
   create the accepted row with state ``accepted_pre_effect``.

Acceptance is the Phase 9 privileged dispatch effect that establishes that root-side work
may now continue. The application maps durable broker acceptance to Phase 4 effect
knowledge without pretending the later package/systemd subeffect has already occurred.

8.3 ``seal_no_accept``
~~~~~~~~~~~~~~~~~~~~~~

Recovery may request a no-accept seal only for the exact already-bound ticket when
Phase 4 recovery proves that the replacement application will not issue a new privileged
``call_start`` for that operation.

Under the same gate and one FULL transaction:

* if acceptance already exists, return ``accepted`` and forbid known-no-effect closure;
* otherwise create/find a terminal ``broker_no_accept_tombstone`` containing operation,
  ticket digest, reason, trusted time/boot facts, evidence generation and a retention
  deadline longer than the maximum delayed-handler/reconnect/retry window.

Every queued, delayed or replayed ``accept_once`` checks this tombstone first and can
never accept after the seal wins. An empty broker store, ticket expiry or lost
application connection outside this gate is not no-effect proof.

A seal for the operation binding also rejects every alternate-ticket attempt for that
operation. It cannot be bypassed by allocating a different ticket ID or digest.

The application-side ``authorised``/``prepared`` state before the durable privileged
dispatch marker is a separate zero-effect boundary: no broker handler may yet have been
sent. Replacement recovery atomically fails the Phase 4 operation as
``restart_before_dispatch``, releases its reservation and workspace fence, and retains a
terminal privileged record whose broker and post-effect audit closures are explicitly
``not_required``. It does not fabricate a broker no-accept seal. Once the durable dispatch
marker exists, this local closure is forbidden and the accept-or-seal rules above apply.

8.4 Post-accept recovery
~~~~~~~~~~~~~~~~~~~~~~~~

Every accepted pre-effect state has a deterministic recovery rule. Ticket/session expiry
does not seal or abandon it. Broker startup/reconciliation examines the accepted row and
operation-specific retained evidence:

* if exact proof shows the root subeffect never started and the contract permits a
  terminal failure/no-subeffect outcome, record that outcome under the accepted ticket;
* if the subeffect was started/accepted, reconcile that exact subeffect;
* if the boundary receipt is ambiguous, retain ``uncertain`` and never start a second
  subeffect;
* if a restart workflow accepted but has not crossed service stop yet, resume from its
  exact durable checkpoint state rather than allocating a replacement attempt.

There is no accepted state that becomes silently unknown because the initiating
application disappeared.

9. Root effect linearization
----------------------------

After durable broker acceptance the broker releases ``BrokerAcceptanceGate`` and executes
one operation-specific state machine. Before the first root subeffect it independently
revalidates ticket-bound root-side current state. It then:

#. durably records exact subeffect intent/state;
#. crosses one semantic root effect boundary;
#. immediately records receipt/knowledge/reference before returning;
#. reconciles operation-specific post-state;
#. returns bounded evidence.

A broker or application crash never causes replay by allocating a new ticket or new
subeffect identity.

10. Read-only package inspection and transaction preparation
------------------------------------------------------------

``package_inspect`` is bounded and has no implicit package-index refresh. It may return:

* installed/not-installed and installed version;
* candidate version when deterministically available from current trusted metadata;
* repository metadata identity/freshness;
* lock/busy state;
* whether exact transaction preparation is currently possible.

``package_inspect`` never silently mutates caches or refreshes repositories. Repository
refresh, if later required, is a separate reviewed operation rather than an inspection
side effect.

10.1 ``PackageTransactionPlan``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Package mutation uses an explicit no-effect prepare/resolve step before the consequential
install. The resolver produces an immutable plan containing at least:

* package-manager/profile/version identity;
* exact repository/source metadata snapshot identity/digest;
* requested package/version/architecture;
* complete ordered or canonicalized action closure for every package affected;
* action class for each member: install/upgrade/configure and any other separately
  reviewed class;
* exact old and target versions for every member;
* package origin/repository identity;
* exact artifact/package checksum or strongest reviewed package-manager artifact identity;
* set/digest of packages whose maintainer scripts may run;
* dependency-closure digest;
* expected disk/resource ceiling;
* transaction-plan version and digest;
* expiry/freshness conditions.

Bootstrap rejects removals, downgrades and unrelated upgrades unless a later reviewed
profile explicitly adds them. Dependency installation is allowed only when the complete
closure is resolved and every member action is allowed by ``PackageProfile``.

If the selected package manager cannot deterministically prepare this closure and later
execute exactly the bound versions/artifacts against the same trusted metadata state,
``package_install`` remains unsupported for that profile.

10.2 Package ticket binding and final comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The package-install ticket binds:

* ``package_transaction_plan_sha256``;
* repository metadata snapshot identity;
* complete package/action/version set digest;
* complete artifact identity digest;
* maintainer-script package set digest;
* exact installed pre-state digest;
* maximum transaction effect.

The application Phase 4 final OP-BOUNDARY and broker root boundary independently
re-resolve or verify the execution transaction against the prepared plan. Any repository
metadata change, solver closure change, unexpected package action or artifact mismatch
causes zero package-manager effect and requires a fresh prepare operation. The broker
never tells the package manager to re-solve an unconstrained request at root-effect time.

11. Package installation effect
-------------------------------

The broker invokes one fixed package-manager adapter with fully constructed argv and a
closed non-interactive environment. Every package/version in the prepared closure is
pinned as required by the selected package-manager profile. No caller-supplied shell or
option string is accepted.

Distro packages may execute package-provided maintainer scripts as root. Phase 9 treats
that as real broad authority and limits it through the trusted repository, exact artifact
closure and prepared transaction. It does not describe package install as a simple file
copy.

The broker records transaction identity/evidence when available, bounded output digest,
pre/post package state and exact unexpected-change evidence.

Terminal classification is conservative:

* the complete exact planned closure is installed and transaction evidence is coherent ->
  known privileged effect;
* exact proof accepted ticket never crossed package-manager start -> accepted operation
  with no package subeffect, not a fabricated unaccepted ticket;
* partial dependency/package change, package DB inconsistency, killed transaction,
  unexpected action or lost receipt -> partial/uncertain, never blind retry.

Post-effect verification checks the whole prepared closure and flags any unexpected
package-manager state change.

The protected package profile also binds the broker/current-LKG operating-system runtime
dependency closure. A prepared transaction that removes, upgrades or otherwise changes a
member of that closure is unsupported by the initial profile; installing an unrelated
development prerequisite may proceed without invalidating the LKG. A future transaction
that changes runtime dependencies requires an offline complete-slot/LKG requalification
contract and cannot be smuggled through normal ``package_install``.

12. Service inspection
----------------------

``binnacle_service_inspect`` targets only ``BinnacleServiceProfile`` and returns bounded
normalized facts such as unit state, main PID/start time, bounded result/failure class,
application readiness, runtime identity and last controlled-restart checkpoint summary.

Systemd ``active`` is not application readiness.

13. Restart preflight
---------------------

``restart_preflight`` is read-only and combines Phase 4 operation truth with Phase 6/7/8
coordination. It reports bounded facts for:

* active/uncertain application operations;
* independently supervised Phase 7 work and survival expectations;
* held workspace change fences;
* Git/credential/privileged effects;
* current runtime identity;
* current LKG runtime slot/checkpoint;
* exact candidate verification-evidence freshness and tested-state match;
* current application/executor/credential-broker/privileged-broker schema heads;
* current deployed peer-service build/protocol/profile set and candidate compatibility;
* predicted service-restart impact;
* blocking or cleanup/cancel reasons.

A source-changing Phase 7/8 operation normally blocks controlled restart/rollback of the
same Binnacle source/runtime unless exact non-overlap is proven. Package mutation and an
unresolved prior restart also block a new restart.

These are advisory point-in-time facts for presentation and policy. They do not authorize
dispatch or close the race with a new Phase 6/7/8 changer. Consequential restart admission
must still acquire exclusive ``WorkspaceAccessGate.CHANGE`` and the free durable workspace
mutation fence, then re-prove the preflight predicates under the normal Phase 6 lock order.

14. Runtime identity
--------------------

A runtime identity binds at least:

* exact Git commit and branch/detached marker;
* dirty-state classification/digest;
* source/workspace/root/mount identity;
* Python executable/version;
* isolated environment/runtime-slot identity;
* lock/dependency manifest digest;
* build/package identity;
* process start time and runtime instance ID;
* configuration, policy and promoted contract/manifest digests;
* service profile/version;
* device ID/epoch;
* readiness generation;
* application, executor, Git-credential-broker and privileged-broker migration heads;
* protected runtime-layout/service-definition generation;
* exact deployed-peer set: Phase 7 executor, Git-credential broker and privileged broker
  build/artifact, protocol/profile, config/unit and readiness generations.

No raw environment variable or credential value is returned.

14.1 Candidate build/test provenance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Controlled self-restart requires one retained ``CandidateVerificationEvidence`` produced
by an isolated, terminal-success Phase 7 verification workflow before preparation. It
binds at least:

* exact Phase 8 repository/worktree identity, branch, commit and source-tree digest;
* candidate runtime-slot/source/environment/lock/config/policy/manifest/service-profile
  identities and all migration heads;
* exact installed peer-service set and every candidate client protocol compatibility range;
* protected peer-owned path/module digest map and proof the candidate changes no separately
  deployed peer/server/protocol artifact;
* exact protected verification-plan/profile version and canonical command-plan digest;
* Phase 7 parent operation plus deterministic member/execution IDs and ticket/evidence
  generations;
* formatter/linter/type/test/build tool and dependency identities;
* every required member's exit/result classification and bounded output/artifact digests;
* trusted completion time, expiry and evidence digest.

The verification profile is protected configuration, not caller-supplied arbitrary argv.
Every required member must have terminal verified success; cancelled, truncated, skipped,
stale or uncertain work is not qualifying evidence. ``privileged_prepare``, the caller
fingerprint, restart checkpoint, privileged ticket, Phase 4 final OP-BOUNDARY and broker
root boundary all bind the same verification-evidence digest. After the restart operation
acquires the Phase 6 ``CHANGE`` guard, it proves current source/tree/environment/config/
policy/manifest/schema state still equals the tested state. Any mismatch or expired/stale
evidence yields zero service-stop effect and requires a new verification run.

A simple restart with no source/environment/config/schema change may reuse the currently
qualified LKG verification evidence. It cannot use that exception to run a different
candidate.

15. ``VerifiedRuntimeSlot`` and last-known-good recovery
-------------------------------------------------------

Git revision rollback alone is insufficient because Bootstrap development normally uses a
mutable source checkout and project environment. Phase 9 therefore defines the LKG as a
previously verified, independently restorable runtime slot, not merely a Git OID plus an
environment digest.

15.1 Runtime-slot contents
~~~~~~~~~~~~~~~~~~~~~~~~~~

A ``VerifiedRuntimeSlot`` binds:

* slot ID/version and immutable/protected slot root identity;
* exact source Git OID and source-tree/artifact identity;
* exact Python interpreter identity;
* isolated environment root/artifact identity;
* exact lockfile/dependency-manifest digest;
* installed distribution/package inventory digest where used for verification;
* immutable/restorable protected configuration, policy, promoted manifest and exact
  effective service-definition material, including their content digests, ownership,
  modes, labels where relevant, selected drop-ins and service-profile identity;
* application, executor, Git-credential-broker and privileged-broker migration heads plus
  protected runtime-layout generation;
* qualifying ``CandidateVerificationEvidence`` identity and evidence digest;
* exact compatible deployed-peer set and peer-issued compatibility receipt digests;
* readiness evidence from the run that qualified the slot;
* creation/promotion evidence generation and retention state.

The LKG slot is stored outside the normal editable development checkout or otherwise
protected so ordinary candidate editing/dependency synchronization cannot mutate it.
Its protected configuration/policy/manifest/service material is stored as exact sealed
slot artifacts or an equivalently immutable content-addressed snapshot, not as digests
without restorable bytes. Those artifacts are never returned through MCP/broker results;
any referenced secret remains root-protected and non-exportable under the selected
profile. Runtime activation selects/restores the complete slot as one verified generation
so LKG source cannot run with candidate environment, configuration, policy, manifest or
unit/drop-in material.

Section 34 freezes the first implementation algorithm: an unprivileged verified build,
root-owned immutable complete slot, same-filesystem atomic selector and stable service-unit
interface. Candidate-Pi evidence must prove that algorithm's durability, disk and startup
behavior before promotion; lack of evidence disables it rather than reverting to the
mutable checkout. An alternative protected worktree/artifact mechanism requires an explicit
plan amendment with equivalent invariants.

15.2 Candidate environment rule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Preparing a candidate may mutate the normal development ``.venv``. That mutable
environment is never treated as the LKG environment merely because its digest was once
recorded.

Controlled restart promotion requires one of two reviewed profiles:

#. **independent-LKG profile** -- a complete protected LKG runtime slot already exists and
   the service/recovery adapter can select it without overwriting unrecognized editable
   workspace state; or
#. **no-runtime-material-change profile** -- until an independent complete LKG slot
   mechanism is proven, controlled restart rejects any candidate whose interpreter/lock/
   environment/configuration/policy/manifest/effective-service identity differs from the
   current verified LKG.

The implementation must never start restored LKG source with an unproven candidate-mutated
shared environment, configuration, policy, manifest or effective service definition.

The initial Bootstrap profile is also **no-schema-change**. A candidate whose expected
application, executor, Git-credential-broker or privileged-broker migration head differs
from the running verified LKG is rejected before service stop. Runtime self-restart never
opportunistically migrates or downgrades any database. Schema/control-plane layout changes
use the explicit offline owner procedure in section 34, which must establish a newly
compatible verified LKG before privileged restart is re-enabled. A later schema-changing
self-management profile requires a separately reviewed database snapshot/migration/rollback
contract and is unsupported by this plan.

It is additionally **no-peer-service-change**. Phase 9 controlled restart replaces only
the application runtime slot; it does not replace or restart the independently supervised
Phase 7 executor, Git-credential broker or root privileged broker. The protected profile
maps their owned source/protocol/unit/config paths and installed artifact digests. A
candidate changing any mapped peer artifact, requiring another peer build/protocol/profile,
or lacking compatibility with the exact deployed set is rejected before service stop.

Before candidate success, each deployed peer supplies a bounded peer-generated
``PeerCompatibilityReceipt`` binding peer build/protocol/profile, app runtime instance,
negotiated protocol, challenge generation and readiness. The broker verifies those receipts
against protected peer identities and exact peer-authenticated UDS/receipt integrity; a
candidate self-assertion or matching migration head is insufficient. LKG eligibility also
binds the same peer set. If a peer changes out of band,
automatic candidate start/rollback is unavailable until the offline multi-service procedure
qualifies a compatible complete LKG.

15.3 LKG promotion
~~~~~~~~~~~~~~~~~~

A candidate becomes the new LKG only after exact runtime identity/readiness and required
audit closure succeed and its complete protected source/environment/configuration/policy/
manifest/service-definition runtime slot is durably materialized/verified. The previous
complete LKG is retained until new-slot promotion is durable.
A candidate cannot destroy the only verified recovery slot before it has qualified.

Promotion is a separate retained broker transition after candidate-ready closure. The
replacement application first commits/reuses the exact terminal audit event, then sends
that audit evidence digest to the broker's closed ``promote_restart_lkg`` request. In one
broker transaction, the verified candidate becomes ``lkg``, the previous LKG becomes a
retained ``prior`` slot, and promotion evidence binds the checkpoint result, verified
selector receipt, audit digest and both before/after slot identities. Only the returned
promotion snapshot may be used to close the application operation, release its reservation
and release the workspace fence. A crash at any boundary reuses the audit event and exact
promotion evidence; a candidate-ready checkpoint without promotion remains outstanding
authority and blocks a new privileged acceptance or broker identity upgrade.

The one bootstrap exception is the explicit offline owner initialization in section 34.4,
which qualifies the already reviewed/current runtime as the first LKG using the same full
build/test/runtime/readiness and durability predicates before any Phase 9 execute Tool is
enabled. It is not a model-visible shortcut and cannot overwrite an existing LKG.

16. Controlled restart checkpoint
---------------------------------

The broker-owned ``RestartCheckpoint`` is fsynced before service stop and binds:

* checkpoint ID/version and Phase 4 operation/ticket identity;
* exact development service;
* candidate source Git OID/branch/dirty expectation;
* candidate interpreter/environment/lock/config/policy/manifest identities;
* exact tested candidate ``CandidateVerificationEvidence`` reference/digest;
* exact application/executor/Git-credential/privileged-broker migration heads and runtime-
  layout generation;
* exact installed peer-service build/protocol/profile set and expected compatibility-
  receipt identities;
* exact candidate runtime slot or candidate-runtime selector inputs;
* exact retained complete LKG ``VerifiedRuntimeSlot`` ID, sealed-artifact identities and
  all protected identity digests;
* pre-restart runtime identity;
* restart/readiness deadline;
* allowed rollback/runtime-selector action;
* broker evidence generation and checkpoint digest.

If a complete LKG slot cannot be proven before stop, controlled restart fails with zero
service stop.

17. Source/runtime selector and rollback authority
--------------------------------------------------

The broker is not a generic Git client. Normal candidate Git preparation is Phase 8.
Recovery uses a narrowly structured ``SelfRecoveryAdapter`` that can select/restore only
the checkpoint's candidate or exact retained complete LKG runtime slot.

Preferred recovery avoids destructive reset of the editable development workspace. A
protected service runtime selector or equivalent exact mechanism points the service at the
candidate/LKG slot while preserving unrelated/unrecognized editable state. If a candidate
implementation instead requires source/environment restoration into a shared location,
that mechanism must prove exact old-state/CAS semantics and refuse intervening state.

Required invariants:

* target is exactly the checkpoint slot;
* no arbitrary path/revision/environment is accepted;
* source, environment, protected configuration, policy, manifest and effective service
  definition are selected/restored as one slot generation and verified before service
  start;
* unrecognized intervening state is never overwritten;
* ambiguous restoration/selection enters restricted recovery;
* candidate-Pi evidence chooses the concrete mechanism before promotion.

18. Controlled restart state machine
------------------------------------

Broker restart states include the semantic progression:

::

   checkpoint_preparing
   checkpoint_ready
   service_stop_requested
   service_stopped
   candidate_selecting
   candidate_start_requested
   candidate_verifying
   candidate_ready
   rollback_required
   lkg_selecting
   rollback_start_requested
   rollback_verifying
   rollback_ready
   restricted_recovery
   failed
   uncertain

Exact machine-readable names may differ, but transitions are one-way/restart-safe and each
privileged subeffect has its own durable intent/receipt/knowledge.

18.1 Before service stop
~~~~~~~~~~~~~~~~~~~~~~~~

Application flow:

#. retained caller-idempotency lookup;
#. required received audit;
#. policy;
#. restart preflight;
#. candidate and protected LKG slot eligibility, exact fresh terminal-success build/test
   evidence, and no-schema-change compatibility;
#. acquire exclusive Phase 6 ``WorkspaceAccessGate.CHANGE``;
#. in the post-policy admission transaction re-prove exact predicates, acquire the free
   durable workspace mutation fence for this operation and the one-restart reservation;
#. create/find the operation's one immutable prepared-operation/ticket binding, including
   exact candidate verification, schema heads, slot and fence generation;
#. authorised audit;
#. running/effect intent;
#. Phase 4 handoff/session/consequential gates;
#. final controller/device/session/service/candidate/LKG/outstanding-work/audit/recovery
   OP-BOUNDARY;
#. durable audit obligation;
#. privileged ticket dispatch.

Broker flow first wins accept-or-seal. If accepted, it durably materializes/verifies the
complete candidate slot and creates ``checkpoint_ready`` including both candidate and
protected LKG slot generations before systemd stop.

The lock order is the existing Phase 6 order: ``WorkspaceAccessGate.CHANGE`` -> durable
workspace fence/restart reservation -> Phase 4 per-operation handoff -> development-
session authority gate -> process-wide consequential gate. The in-memory access guard is
held until the current application stops. Durable fence ownership survives that stop and
remains assigned to the exact Phase 4 restart operation through every broker candidate/
rollback state, retained application reconciliation, audit-obligation closure and truthful
terminal release. ``uncertain`` or ``restricted_recovery`` retains the fence. A replacement
application does not reacquire it as new work: startup remains ``RECOVERY_CLOSED``, loads
the exact owner/checkpoint/broker generation, reconciles it, and only after durable fence
release may reopen ``CONTENT_READ`` or ``CHANGE``.

18.2 Candidate lifecycle
~~~~~~~~~~~~~~~~~~~~~~~~

The broker selects/verifies the exact candidate runtime, requests exact service stop/start
and records each systemd effect receipt. Application disappearance is expected.

The retained Phase 6 fence prevents any new Binnacle-managed Phase 7/8 source/environment
changer from being admitted while the application is absent. A deployment profile with
uncoordinated out-of-band writers cannot promote controlled restart unless an independently
proven runtime-slot mechanism makes those writers unable to mutate either selected slot.

Candidate success requires:

* endpoint/readiness within the deadline;
* exact candidate Git OID;
* branch/dirty expectation;
* source/runtime-slot/environment/lock identities;
* config/policy/manifest digests;
* migration heads/runtime-layout generation;
* exact match to the retained candidate build/test evidence;
* independently verified peer-generated compatibility receipts for the exact deployed
  executor, Git-credential broker and privileged broker builds/protocols;
* device/service identities;
* absence of disqualifying fail-restricted startup state.

Systemd active with wrong identity is candidate failure.

18.3 Candidate success and LKG promotion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Only exact verified ``candidate_ready`` can be reconciled as requested restart success.
The replacement application closes Phase 4 audit/operation obligations from broker
evidence. Protected new-LKG slot promotion occurs only after required verification/audit
closure and never destroys the previous LKG before durable promotion.
The required order is terminal broker result -> durable application audit closure ->
atomic broker LKG promotion -> atomic application/Phase 4/reservation/fence closure.
Rollback/no-subeffect/failed terminal results do not run the LKG-promotion transition.

19. Failed-candidate rollback
-----------------------------

Candidate timeout, crash loop, wrong identity/config/environment or disqualifying
readiness enters ``rollback_required`` without depending on model reasoning or failed
application cooperation.

The broker:

#. reaches a service state safe for recovery;
#. verifies the retained LKG slot is complete and unchanged;
#. atomically selects/restores the exact complete LKG source, environment, protected
   configuration, policy, manifest and effective service definition through
   ``SelfRecoveryAdapter``;
#. records exact recovery receipt;
#. starts the exact service;
#. verifies exact LKG runtime identity/readiness;
#. records ``rollback_ready`` only when proven.

The original requested candidate restart is not reported as success when rollback wins.
Host-visible result says candidate failed and LKG recovery succeeded.

20. Restricted local recovery
-----------------------------

Missing/corrupt LKG source/environment/configuration/policy/manifest/service-definition,
disk-full, systemd failure, ambiguous selector receipt, package damage, filesystem mismatch
or power loss may make rollback unverifiable.
The broker then stops bounded autonomous recovery and enters ``restricted_recovery``.

Root-protected retained evidence includes restart/checkpoint ID, candidate/LKG runtime-slot
identities, last proven service/runtime state, failed/uncertain action, bounded diagnostics,
static-template local operator instructions and evidence digest. Instructions are not
model-generated arbitrary root shell commands.

21. Simple service restart
--------------------------

``binnacle_service_restart`` is only for restarting the fixed service when source,
environment, config and candidate/LKG semantics are unchanged. It still requires
preflight, the same exclusive Phase 6 ``CHANGE`` guard/durable mutation fence when the
service executes from the registered workspace, and exact post-restart runtime
verification. Its fence remains owned through broker and audit closure just as for
controlled restart; the smaller semantic effect does not reopen a workspace race.

``binnacle_restart`` is mandatory whenever source/environment/config candidate identity
changes or rollback semantics may be needed. The final current-state verifier prevents a
caller from selecting the simple path for a candidate-changing restart.

22. Application/broker restart reconciliation
---------------------------------------------

Application startup queries broker acceptance/effect/recovery evidence before new
privileged work. It reconciles exact operation/ticket/checkpoint/evidence generation,
runtime identity, Phase 4 effect knowledge, audit obligations and Phase 6/7/8 cleanup.

Startup reads the Phase 6 durable mutation fence before opening workspace access. A fence
owned by a retained service/self-restart keeps both ``CONTENT_READ`` and ``CHANGE``
recovery-closed while the application reconciles that exact Phase 4 operation and broker
generation. Filesystem appearance, service active state, ticket expiry or an empty broker
query cannot clear or replace fence ownership.

If Phase 4 ``call_start`` occurred but broker acceptance is unknown, application recovery
may request gate-owned ``seal_no_accept`` only under the rule in section 8. If acceptance
won, the application reconciles/resumes the accepted broker operation. Empty broker store
alone never releases the Phase 4 operation/fence.

Broker startup validates every retained accepted pre-effect state and resumes its exact
operation-specific state machine. It never abandons accepted work because the ticket
expired or session ended.

Broker unavailability while privileged work may be incomplete keeps affected Phase 4
operations uncertain/reconciling and blocks overlapping privileged work.

23. Restart preflight versus Phase 7/8 work
-------------------------------------------

A Phase 7 command may survive application restart only when its independent supervision,
workspace/profile and non-overlap predicates remain valid. Source-changing work that can
race candidate/LKG runtime selection prevents the restart operation from acquiring the
free Phase 6 durable mutation fence. Once restart owns that fence, no new Phase 7/8
workspace changer may be admitted until truthful release. Active credentialed Git effects,
package transactions, prior restart/recovery, audit failure or uncertain source mutation
also block.

24. Systemd adapter
-------------------

Use systemd's native service manager through a typed adapter closed over the exact service
profile. It may inspect exact properties, restart/start/stop one registered unit and await
bounded state transitions. No arbitrary ``systemctl`` args/unit names are accepted.

Implementation may use a mature systemd API/DBus binding or fixed ``systemctl`` argv after
candidate-Pi evidence. Shell use is forbidden. The Phase 7 command domain never receives
the system bus as a substitute broker.

25. Optional host reboot
------------------------

Reboot is absent by default. If real evidence later requires it, a separately promoted
contract uses boot-persistent root-protected ticket/checkpoint state, one-shot consumed
identity, boot-ID transition verification, exact post-boot runtime/recovery checks and no
blind second reboot after response loss.

Plan acceptance neither exposes nor claims reboot support.

26. Effect truth
----------------

26.1 Broker acceptance
~~~~~~~~~~~~~~~~~~~~~~

Broker acceptance is the privileged dispatch effect. A sealed ticket has
``no_accept_proven`` and no accepted root work. Accepted tickets are never later
reclassified as unaccepted.

26.2 Package installation
~~~~~~~~~~~~~~~~~~~~~~~~~

Package subeffect starts when the exact prepared transaction is accepted by the package
manager under retained broker state. Complete planned post-state plus coherent transaction
evidence is success. Unexpected/partial package changes are partial/uncertain.

26.3 Service restart
~~~~~~~~~~~~~~~~~~~~

Service subeffect starts when systemd accepts the exact lifecycle transition. Success
requires exact post-restart Binnacle identity/readiness.

26.4 Controlled restart
~~~~~~~~~~~~~~~~~~~~~~~

Checkpoint persistence is preparation. Service stop/start, runtime selection and rollback
are individually retained privileged subeffects. Candidate failure followed by proven LKG
rollback is a completed recovery result with known privileged effects, not known-no-effect.

27. Idempotency, overlap and cancellation
----------------------------------------

Phase 4 caller idempotency remains authoritative. Broker replay prevention is defense in
depth. Same-owner/same-key/same-fingerprint retries reconcile retained application/broker
state before mutable checks. An uncertain retained root effect never receives a fresh
ticket just to retry it.

The application database enforces one privileged-ticket binding per Phase 4 operation.
The broker independently enforces one operation binding plus globally unique ticket ID
and nonce. Concurrent different-ticket attempts for the same operation serialize through
the operation-scoped acceptance gate: exactly the retained binding can accept or seal and
every alternative conflicts with zero new root effect.

Overlap rules include:

* one package mutation at a time;
* no package mutation overlapping service/self-restart;
* one restart/recovery slot at a time;
* no new restart while rollback/recovery unresolved;
* no source-changing Phase 7/8 work overlapping candidate/LKG selection;
* future reboot excludes every unproven consequential operation.

For a service/self-restart backed by the development workspace, these overlap rules are
enforced by the Phase 6 exclusive ``CHANGE`` guard plus durable mutation fence, not only
by a preflight snapshot or a Phase 9 in-memory reservation. Fence release requires broker
terminal/recovery evidence, Phase 4 effect classification and required audit-obligation
closure. ``uncertain`` and ``restricted_recovery`` retain ownership and block new readers
and changers until explicit reconciliation.

Owner cancellation is not a generic mid-root-effect interrupt. Package-manager and
restart effects are allowed to reach their deterministic reconciliation/recovery state
once accepted. A future cancellable privileged operation must define an operation-specific
safe cancellation state machine rather than reuse Phase 7 process cancellation.

28. Audit semantics
-------------------

Application audit remains distinct from broker evidence. Cross-reference using operation
ID, ticket digest, checkpoint/runtime-slot identity and evidence digest.

Required audit includes received request, policy decision, privileged target/transaction
profile digest, effect intent, broker acceptance/seal result, root subeffect references,
package/service/candidate/rollback outcome, restricted recovery and terminal/uncertain
result.

Audit failure before the Phase 4 start gate prevents new root dispatch. Audit failure
after root effect begins cannot erase effect truth; the operation remains fail-restricted
until audit-obligation reconciliation completes.

29. Credential and secret boundary
----------------------------------

The broker never returns root, SSH, signing, controller or repository credentials.
Protected package-repository authentication, if ever required, must be a separately
reviewed non-exportable capability bound to the exact prepared transaction. Bootstrap
prefers trusted OS repositories without new credential authority.

Broker DB rows, journald, exceptions, result envelopes and recovery markers are bounded
and redacted against reusable authority material.

30. Filesystem/path and root-helper process safety
--------------------------------------------------

All broker-writable paths come from protected profiles. Direct broker filesystem work
uses descriptor-relative containment, exact ownership/mount identity, no symlink escape,
restrictive modes, fsync/file+parent durability and CAS/no-overwrite publication where
applicable.

Complete runtime slots use a fixed root-owned layout and generation manifest that binds
source, environment, protected configuration, policy, promoted manifest and effective
service-definition artifacts. Publication fsyncs every artifact and parent before one
atomic/CAS selector transition. Restore/select rejects a missing member, digest/mode/
ownership mismatch, cross-generation mixture, symlink/mount replacement or unrecognized
current selector. Protected slot bytes and secret references are never copied into the
application database, audit journal or model-visible evidence.

Root helper processes use fixed executable identity, constructed argv/environment,
closed stdin where possible, closed inherited FDs, no application/executor credential
sockets, bounded output/time and broker-owned descendant supervision. Shell is forbidden.
Unknown process/effect outcome remains uncertain until independently reconciled.

31. Errors and diagnostics
--------------------------

Exact MCP schemas are promotion work. Domain errors should distinguish bounded classes
including:

* ``privileged_profile_unavailable``;
* ``privileged_ticket_invalid`` / ``privileged_ticket_expired``;
* ``privileged_ticket_replay_conflict``;
* ``privileged_no_accept_proven``;
* ``broker_unavailable`` / ``broker_evidence_unavailable``;
* ``package_transaction_plan_changed``;
* ``package_transaction_busy`` / ``package_partial_or_uncertain``;
* ``service_profile_mismatch``;
* ``restart_preflight_blocked``;
* ``restart_checkpoint_failed``;
* ``lkg_runtime_slot_unavailable``;
* ``candidate_environment_unsupported``;
* ``restart_candidate_failed`` / ``restart_rolled_back``;
* ``restart_rollback_failed`` / ``restart_restricted_recovery``;
* ``runtime_identity_mismatch``;
* ``candidate_verification_missing`` / ``candidate_verification_stale``;
* ``candidate_tested_state_mismatch``;
* ``candidate_schema_change_unsupported``;
* ``candidate_peer_change_unsupported`` / ``peer_build_protocol_mismatch``;
* ``privileged_effect_uncertain``.

No error returns raw privileged stderr, credentials, protected config or arbitrary root
paths.

32. Ports and adapters
----------------------

Representative application-side ports:

.. code-block:: python

   class PrivilegedBrokerPort(Protocol):
       async def inspect_package(self, request: PackageInspectRequest) -> PackageInspectResult: ...
       async def prepare_package(self, request: PackagePrepareRequest) -> PackageTransactionPlan: ...
       async def install_package(self, ticket: PrivilegedTicket) -> BrokerEffectResult: ...
       async def inspect_service(self, request: ServiceInspectRequest) -> ServiceInspectResult: ...
       async def restart_service(self, ticket: PrivilegedTicket) -> BrokerEffectResult: ...
       async def controlled_restart(self, ticket: PrivilegedTicket) -> RestartDispatchResult: ...
       async def seal_no_accept(self, request: NoAcceptSealRequest) -> NoAcceptSealResult: ...
       async def inspect_recovery(self) -> BrokerRecoverySnapshot: ...

   class RestartPreflightPort(Protocol):
       async def inspect(self, request: RestartPreflightRequest) -> RestartPreflightResult: ...

   class RuntimeIdentityPort(Protocol):
       async def current(self) -> RuntimeIdentity: ...

Representative broker-side ports:

.. code-block:: python

   class BrokerEvidenceStore(Protocol):
       def accept_once(self, ticket: VerifiedPrivilegedTicket) -> BrokerAcceptanceResult: ...
       def seal_no_accept(self, request: VerifiedNoAcceptSeal) -> NoAcceptSealResult: ...
       def record_effect_receipt(self, receipt: PrivilegedEffectReceipt) -> None: ...
       def create_restart_checkpoint(self, checkpoint: RestartCheckpoint) -> None: ...
       def advance_restart_state(self, transition: RestartTransition) -> None: ...
       def snapshot(self, operation_id: str) -> BrokerOperationSnapshot: ...

   class PackageManagerAdapter(Protocol):
       def inspect(self, target: PackageTarget) -> PackageState: ...
       def prepare(self, target: PackagePrepareTarget) -> PackageTransactionPlan: ...
       def verify_plan(self, plan: PackageTransactionPlan) -> PackagePlanVerification: ...
       def install(self, plan: PackageTransactionPlan) -> PackageInstallReceipt: ...

   class ServiceManagerAdapter(Protocol):
       def inspect(self, target: ServiceTarget) -> ServiceState: ...
       def restart(self, effect: ServiceRestartEffect) -> ServiceRestartReceipt: ...
       def stop(self, effect: ServiceStopEffect) -> ServiceStopReceipt: ...
       def start(self, effect: ServiceStartEffect) -> ServiceStartReceipt: ...

   class RuntimeSlotStore(Protocol):
       def inspect(self, slot_id: str) -> VerifiedRuntimeSlot: ...
       def materialize_candidate(self, request: RuntimeSlotPrepare) -> RuntimeSlotReceipt: ...
       def activate_complete_slot(self, request: RuntimeSlotActivation) -> RuntimeSlotReceipt: ...
       def promote_lkg(self, request: RuntimeSlotPromotion) -> RuntimeSlotReceipt: ...

   class SelfRecoveryAdapter(Protocol):
       def select_candidate(self, checkpoint: RestartCheckpoint) -> RecoveryReceipt: ...
       def restore_lkg(self, checkpoint: RestartCheckpoint) -> RecoveryReceipt: ...
       def verify_runtime(self, checkpoint: RestartCheckpoint) -> RuntimeVerification: ...

No port accepts arbitrary shell strings, arbitrary systemd units or caller-selected root
paths.

33. Persistence ownership
-------------------------

Application migration ``migrations/versions/0006_privileged_operations.py`` follows the
mandatory Phase 8 ``0005_git_operations.py`` head. It extends Phase 4 only for authoritative
correlation/reservation: one privileged operation subtype, one immutable ticket binding,
broker evidence generation/reference, target/profile/prepared-operation digest, restart
slot/checkpoint and ``CandidateVerificationEvidence`` references, package transaction-plan
digest, schema/runtime-layout heads and observed candidate/rollback outcome. Service/self-
restart rows bind the exact Phase 6 workspace/fence ID, version and operation ownership;
the existing Phase 6 fence row remains authoritative and is never copied or cleared from
broker state. Unique/check constraints enforce one ticket per operation and globally unique
ticket ID/nonce, exact operation subtype shapes, HC2 preparation binding and terminal state
only after broker/audit/fence closure.

The root broker has an isolated Alembic environment:

::

   alembic_privileged.ini
   migrations_privileged/env.py
   migrations_privileged/versions/0001_privileged_evidence.py

Broker ``0001`` creates protocol/schema metadata, operation-ticket bindings, no-accept
tombstones, privileged subeffect states, package-plan evidence, restart/checkpoints,
runtime-slot generations/selectors and restricted-recovery evidence. One unique operation-
binding row owns the immutable ticket ID/digest/nonce/action/target/evidence generation;
ticket ID and nonce are separately unique. Accepted and sealed/no-accept states are mutually
exclusive for the Phase 4 operation binding, not merely for one caller-provided ticket.
Runtime-slot rows bind complete sealed source, environment, configuration, policy,
manifest, service-definition, verification-evidence, migration-head, deployed-peer and
layout artifacts.

The broker never opens or migrates application, executor or Git-credential databases. The
application never opens or migrates the broker database. Runtime requires the exact expected
head and never creates/upgrades either schema opportunistically. Empty/prior/current/head,
FK/check/unique/index/integrity and cross-database-denial tests are mandatory. Migration or
integrity failure keeps new privileged effects unavailable and never silently repairs,
deletes or reconstructs unknown state.

34. systemd and installation assets
-----------------------------------

34.1 Identities and protected paths
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The initial software-broker profile freezes this topology:

* the broker service runs as ``root`` from a separately installed root-owned runtime;
* ``binnacle-privileged-client`` is a dedicated socket-DAC group containing only the
  unprivileged ``binnacle`` application identity;
* executor, command and Git/credential identities are not members and cannot traverse the
  socket directory;
* the broker checks ``SO_PEERCRED`` against the exact application UID and **primary** GID;
  it never mistakes the supplementary socket group for peer identity.

Exact default paths and minimum modes are:

.. list-table:: Initial protected path profile
   :header-rows: 1

   * - Path
     - Owner:group
     - Mode
   * - ``/run/binnacle-privileged``
     - ``root:binnacle-privileged-client``
     - 0750
   * - ``/run/binnacle-privileged/broker.sock``
     - ``root:binnacle-privileged-client``
     - 0660
   * - ``/etc/binnacle-privileged``
     - ``root:root``
     - 0700
   * - ``/etc/binnacle-privileged/broker.toml``
     - ``root:root``
     - 0600
   * - ``/var/lib/binnacle-privileged``
     - ``root:root``
     - 0700
   * - ``/var/lib/binnacle-privileged/evidence.db``
     - ``root:root``
     - 0600
   * - ``/opt/binnacle-privileged``
     - ``root:root``
     - 0755
   * - ``/srv/binnacle-runtime``
     - ``root:binnacle``
     - 0750
   * - ``/srv/binnacle-runtime/slots/<slot-id>``
     - ``root:binnacle``
     - 0550
   * - ``/srv/binnacle-runtime/current``
     - root-owned selector
     - not applicable

Slot members that the service must read use exact root-owned, non-writable modes (normally
0440 for data and 0550 for traversable/executable content) and group ``binnacle``. Secret-
bearing configuration remains model-never-disclosable even though the exact service
identity can read it. The application cannot write, rename or replace the slot or selector.

The broker runtime parent is outside the candidate checkout and candidate ``.venv``. An
explicit owner installation copies/verifies one reviewed broker artifact and dependencies
into ``/opt/binnacle-privileged``; the broker never imports or executes mutable workspace
Python as root. The socket parent is directly beneath root-owned ``/run``, not beneath the
application-owned ``/run/binnacle``. Broker state/checkpoints are not stored under the app-
traversable runtime-slot tree.

34.2 Unit lifecycle and hardening
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``binnacle-privileged.socket`` owns the socket pathname with ``Accept=no`` and the exact
directory/socket modes above. ``binnacle-privileged.service`` is not ``PartOf`` the
application service and is not stopped by ``binnacle-dev`` restart; it must retain restart
and rollback evidence while the application is absent. The application may ``Wants`` and
order ``After`` the broker socket/readiness, without creating a reverse lifecycle cycle.

The service uses a restrictive umask, closed inherited FDs/stdin, private temporary paths,
bounded descendants/output and the strongest filesystem/device/network/capability/systemd-
bus restrictions compatible with the selected package/systemd adapters. Package install
is honestly broad root filesystem/network authority under the exact prepared transaction;
the plan does not claim that ``ProtectSystem=strict`` or a capability set is effective when
it would prevent that semantic operation. Effective unit properties, fragment path and
drop-ins are verified on the Pi. No hardening directive is treated as proven by tracked
unit text alone.

34.3 Runtime-slot publication and selector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The first profile uses one same-filesystem, root-owned immutable slot tree plus an atomic
``current`` relative-symlink/selector under ``/srv/binnacle-runtime``:

#. the unprivileged Phase 7 verification workflow builds/tests and exports only the exact
   reviewed candidate artifacts; root never executes candidate build hooks or source;
#. while the restart owns the Phase 6 fence, the broker creates an unguessable exclusive
   staging directory on the slot filesystem and copies the exact verified source,
   environment, configuration, policy, manifest and service-definition evidence;
#. it verifies every expected digest, migration head, owner/mode and generation manifest,
   reserves configured bytes/inodes and fsyncs files/directories;
#. it publishes the immutable slot by no-overwrite rename and fsyncs the slot parent;
#. before selector change it records durable intent, creates a relative temporary selector
   naming that exact slot, atomically renames it over ``current`` and fsyncs the selector
   parent;
#. it verifies the selected complete generation before asking systemd to start the service
   and records selector/systemd receipts separately.

The stable reviewed ``binnacle-dev.service`` executes source/environment/config through
``/srv/binnacle-runtime/current``. The initial profile requires its effective unit/drop-in
definition and runtime-selector interface to be identical across candidate and LKG slots;
a candidate that changes that interface or migration heads is rejected before stop. Slot
service-definition material is still retained and verified so rollback cannot silently use
an unreviewed installed unit. A future profile that actually replaces unit/drop-in material
needs a separately reviewed crash-safe daemon-reload/rollback state machine.

Selector crash recovery uses the retained intent, old/new slot IDs and actual root-owned
selector target. It never guesses from service presence and never deletes an unknown slot
or selector. Configuration reserves enough bounded storage for current LKG, candidate and
one prior retained slot; referenced LKG/candidate/recovery slots cannot be garbage-collected.
Disk/inode reservation failure occurs before service stop. Cleanup is limited to exact
unreferenced, terminally closed generations with retained deletion receipts.

34.4 Initial LKG bootstrap
~~~~~~~~~~~~~~~~~~~~~~~~~~

The first LKG does not require an earlier successful controlled restart. It is created by
an explicit owner-only offline initialization using the already installed, root-owned
broker executable:

#. stop new application admission and prove/reconcile no outstanding Phase 4/6/7/8/9
   operation or workspace fence;
#. as the unprivileged identities, verify the exact reviewed commit, clean source, frozen
   dependencies, all schema heads and a terminal-success protected build/test plan;
#. stop the application, acquire the offline app/broker/runtime-slot maintenance locks and
   import the exact prebuilt artifacts into a staged complete slot without executing them
   as root;
#. verify/fsync/publish the slot and selector using section 34.3 **without** starting or
   qualifying the application;
#. retain the exact old unit/selector state, install and verify the reviewed stable app
   unit plus broker service/socket assets, run ``systemctl daemon-reload``, then verify
   effective fragment/drop-ins/``ExecStart`` resolve through the selected slot and the
   broker ordering has no lifecycle cycle;
#. start and verify broker socket/service/protocol/store readiness first;
#. start the application exactly once through the reloaded stable selector-backed unit,
   verify complete runtime identity/readiness and exact peer-generated compatibility
   receipts from outside the candidate process, then durably qualify that slot as initial
   LKG;
#. only after qualification enable the Phase 9 execute contracts.

Initialization is idempotent for the same full slot/evidence digest and conflicts on a
different candidate once an LKG exists. Failure before selector/unit publication leaves the
old layout unchanged. Failure after publication but before qualification stops the new app,
restores the exact retained selector/unit state and daemon-reloads it when those receipts
are proven, or leaves the service stopped in restricted local recovery with root-retained
evidence. It never starts both old and new app units or qualifies a run through the old
loaded unit. Setup never labels an unstarted or merely systemd-active slot as LKG.

34.5 Offline migration and upgrade order
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The owner runbook freezes this order:

#. stop new application admission; inspect and drain/reconcile or retain uncertainty for
   application, executor, Git/credential and privileged operations;
#. stop the application, then stop broker socket activation and broker only after every
   accepted privileged state is terminal or explicitly retained for maintenance recovery;
#. acquire each service's runtime migration lock and create the reviewed control-plane
   backup/checkpoint needed by the offline upgrade;
#. migrate the application to exact ``0006`` as ``binnacle`` from the reviewed runtime and
   migrate the broker to exact ``0001`` only through its root-owned installed executable;
#. verify both heads, FK/integrity, owners/modes, runtime-slot generation and the unchanged
   executor/Git-credential heads; never run mutable checkout code as root;
#. for this schema-changing Phase 9 installation, execute section 34.4's single ordered
   stage/publish -> install/verify units -> daemon-reload -> start/verify broker -> start
   app once -> externally verify -> qualify sequence; old-schema slots are ineligible for
   automatic rollback.

Any failure leaves dependent services stopped/restricted with backups and evidence intact;
runtime startup never performs migrations or silently restores a database. Later MCP-driven
controlled restart is no-schema-change. An owner-performed future schema upgrade disables
restart until the offline process establishes a compatible complete LKG.

The same offline rule applies to a new executor, Git-credential broker or privileged-
broker build/protocol/profile: drain and stop affected peers, install/migrate/verify their
exact protected artifacts and units first, then build/select/start the compatible app slot
and qualify a new complete LKG against peer-generated receipts. An old LKG bound to the
previous peer set is not eligible for automatic rollback. MCP ``binnacle_restart`` never
performs this multi-service upgrade.

Retained terminal broker history remains integrity-verifiable across such an offline broker
upgrade and does not itself pin the old build/profile/protocol identity. Exact old identity
is required while unresolved/accepted nonterminal authority exists or while a terminal
``candidate_ready`` checkpoint still lacks durable LKG-promotion evidence.

34.6 Expected repository implementation set
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Representative exact paths are:

.. code-block:: text

   src/binnacle/domain/privileged.py
   src/binnacle/ports/privileged.py
   src/binnacle/application/privileged/
       preparation.py
       service.py
       restart.py
       reconciliation.py
   src/binnacle/adapters/privileged_ipc/
       client.py
       protocol.py
   src/binnacle/adapters/sqlite/privileged.py
   src/binnacle/privileged_broker/
       service.py
       protocol.py
       tickets.py
       acceptance.py
       sqlite.py
       package_manager.py
       systemd.py
       runtime_slots.py
       reconciliation.py
   migrations/versions/0006_privileged_operations.py
   alembic_privileged.ini
   migrations_privileged/env.py
   migrations_privileged/versions/0001_privileged_evidence.py
   spec/operation/privileged-operations.yaml
   spec/policy/privileged-profiles.yaml
   spec/policy/host-confirmation-classes.yaml
   spec/policy/capability-zones.yaml
   spec/mcp/bootstrap-tool-manifest.yaml
   spec/mcp/evaluation-cases.yaml
   spec/mcp/evaluation-profile.yaml
   schemas/mcp/bootstrap-inputs.schema.json
   schemas/mcp/bootstrap-outputs.schema.json
   src/binnacle/_generated/compatibility_core_registry.json
   src/binnacle/_generated/compatibility_core_registry.digest.json
   deploy/systemd/binnacle-dev.service
   deploy/systemd/binnacle-executor.service
   deploy/systemd/binnacle-git-credential.service
   deploy/systemd/binnacle-git-credential.socket
   deploy/systemd/binnacle-privileged.service
   deploy/systemd/binnacle-privileged.socket
   deploy/tmpfiles.d/binnacle-privileged.conf
   scripts/setup_dev_pi.py
   scripts/verify_dev_pi.py
   scripts/verify_privileged_broker.py
   docs/security/privileged-self-management.md
   docs/operations/development-pi.rst
   .github/workflows/python.yml
   pyproject.toml
   uv.lock
   tests/unit/privileged/
   tests/integration/privileged/
   tests/security/privileged/
   tests/property/test_privileged_lifecycle.py

The exact file set may reuse an existing inward port rather than create an empty layer, but
may not omit either migration environment, units/socket/tmpfiles, setup/read-only verifier,
operator runbook, canonical contracts/evaluation, runtime-slot bootstrap/recovery tests or
deployment CI. ``pyproject.toml``/``uv.lock`` change only for a real selected dependency.
The verifier uses an unprivileged static repository path for public checks and the installed
root-owned broker executable for private root-state inspection; root never imports a mutable
checkout merely to verify it.

No hardening, durability or selector directive is claimed effective until verified on the
candidate Pi. The evidence-independent topology/algorithms above remain implementation
requirements even before that evidence exists.

35. Security invariants
-----------------------

The implementation must mechanically preserve:

#. Application is never root.
#. Phase 7/8 children cannot connect to broker.
#. Broker exposes no generic root command/path/unit/package-option surface.
#. Every root effect has Phase 4 operation identity before dispatch and broker replay
   identity before root subeffect.
#. Accept-or-seal gives exactly one terminal acceptance winner.
#. One Phase 4 operation has exactly one immutable privileged ticket binding; alternate
   tickets cannot create another acceptance gate or root effect.
#. Delayed/queued handlers cannot accept after no-accept seal.
#. Accepted work remains recoverable after ticket/session expiry.
#. Broker replay cannot create a second effect.
#. Package install executes only the exact prepared complete transaction closure.
#. Repository metadata/solver/artifact mismatch before package effect yields zero effect.
#. Arbitrary systemd units cannot be selected.
#. Checkpoint and complete LKG runtime slot are durable before service stop.
#. LKG includes source, independently restorable environment and exact restorable
   protected configuration/policy/manifest/service-definition material.
#. Candidate cannot mutate/destroy the only verified LKG slot.
#. Candidate success requires exact runtime identity/readiness, not systemd active.
#. Candidate stop/start is impossible without fresh exact terminal-success Phase 7
   build/test evidence bound through preparation, final boundary, ticket and checkpoint.
#. Bootstrap controlled restart rejects every migration-head/runtime-layout change.
#. Bootstrap controlled restart rejects every separately deployed peer-service artifact/
   protocol change and verifies exact peer-generated post-start compatibility receipts.
#. Rollback is broker-owned and does not depend on failed candidate.
#. Unverifiable rollback enters restricted recovery instead of looping.
#. Shared mutable candidate ``.venv`` is never treated as LKG environment.
#. Empty broker store/application response is not no-effect proof after call-start.
#. Active Phase 7/8 work participates in restart preflight.
#. Every workspace-backed service/self-restart owns the Phase 6 exclusive ``CHANGE`` guard
   and durable mutation fence from post-policy admission through truthful closure.
#. Application replacement never clears, steals or bypasses a retained restart fence.
#. Audit failure before start prevents effect; later audit failure does not erase truth.
#. Reboot remains absent until separately evidenced/promoted.
#. Results/logs/evidence/recovery markers disclose no reusable secret.

36. Holistic concurrency and crash model
----------------------------------------

Walk at least:

* queued broker handler versus gate-owned no-accept sealing after app crash;
* two different ticket IDs/digests concurrently target one Phase 4 operation in both
  arrival orders;
* broker accepts then crashes before first root subeffect;
* ticket expires/session ends after acceptance;
* two package installs;
* package metadata/solver plan changes after prepare but before broker effect;
* malicious repository metadata broadens dependency closure;
* package install races controlled restart;
* two self-restarts with different candidates;
* restart preflight clean then source-changing Phase 7/8 work starts before final boundary;
* source-changing Phase 7/8 admission races restart ``CHANGE``/fence acquisition in both
  winner orders;
* app crash before/after broker acceptance/receipt;
* broker crash after package manager/systemd start but before receipt;
* checkpoint fsync failure;
* service stop then broker crash;
* candidate active with wrong revision/environment/config;
* candidate app is new while executor, Git-credential broker or privileged broker remains
  an older incompatible build/protocol;
* a peer changes after LKG qualification and candidate/rollback tries to reuse stale
  compatibility evidence;
* build/test evidence succeeds, then source/environment/config/schema state changes before
  restart fence acquisition or final boundary;
* mutable development ``.venv`` changed after LKG qualification;
* candidate changes protected config/policy/manifest/unit material after LKG qualification;
* protected LKG environment missing/corrupt before service stop;
* one member of the protected LKG configuration/service generation missing, corrupt or
  replaced before service stop;
* candidate timeout and rollback;
* rollback slot selection succeeds but service-start receipt lost;
* LKG service active with wrong environment identity;
* disk full/power loss during checkpoint/runtime-slot/recovery marker;
* same-key retry after reconnect;
* audit failure before/after root effect;
* malicious arbitrary unit/package/path/argv substitution.

Every case resolves to retained truthful success/failure/recovery/uncertain state; no case
infers root-effect truth from process/service presence alone.

37. Tests and evidence
----------------------

37.1 Unit/property tests
~~~~~~~~~~~~~~~~~~~~~~~

Test ticket canonicalization/replay/expiry, one-ticket-per-operation uniqueness,
alternate-ticket conflicts, accept-or-seal state machine, delayed handler
rejection, package-plan canonicalization, complete dependency closure, service target
binding, runtime-slot/LKG eligibility, restart transitions, runtime identity matching,
verification-evidence freshness/matching, schema-head compatibility, error redaction and
peer-set compatibility, reboot absent-by-default.

Property/state-machine tests inject crashes between every durable broker transition and
prove no double root effect, no accept after seal, no accepted-work abandonment, no
package-plan broadening, no restart/source-changing admission overlap, no mixed-generation
runtime-slot activation and no ambiguous rollback promoted to success.

37.2 Linux integration/fault tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On disposable fixtures prove:

* Unix peer credentials and child-UID denial;
* frame/schema ceilings and broker storage ownership;
* exact package prepare/execute argv/environment;
* repository metadata change after prepare => zero package-manager effect;
* solver dependency broadening => rejection;
* exact fixed-unit systemd lifecycle;
* readiness/runtime identity separate from unit active;
* exact Phase 7 verification success is accepted while failed/cancelled/truncated/stale/
  mismatched evidence causes zero service stop;
* new-client/old-peer protocol mismatch and peer-owned candidate changes cause zero service
  stop; peer-generated receipt loss/mismatch cannot be replaced by candidate assertion;
* checkpoint/runtime-slot fsync durability;
* restart-vs-Phase 7/8 change admission in both linearization orders, with the loser
  blocked before effect and retained fence surviving application replacement;
* app death with broker handler queued: accept versus seal one durable winner;
* app/broker restart plus a forged replacement ticket for the same operation yields the
  retained binding and zero second root effect;
* broker crash after accepted before root boundary: accepted recovery resumes/closes;
* environment-changing candidate uses independently protected LKG env or is rejected;
* config/policy/manifest/service-definition-changing candidate uses a complete protected
  LKG generation and rollback restores/selects that exact generation atomically;
* corrupt/missing LKG env before stop => zero service-stop effect;
* corrupt/missing LKG after effect => restricted recovery, never false rollback success;
* service stop/start while application absent;
* source/runtime-slot path symlink/mount replacement fails closed;
* secret redaction.

37.3 CI gates
~~~~~~~~~~~~~

CI retains the repository Python 3.11/3.12/3.13 test matrix and the quality lane: frozen
``uv`` sync, Ruff/format, strict MyPy including every new setup/verifier/broker script,
Import Linter application/broker isolation, branch coverage, ``pip-audit``, recursive RST,
canonical contracts/schemas/generated registry, manifest/handler parity and pre-commit.

Isolated temporary-root lanes exercise application ``0006`` and broker ``0001`` from empty,
prior/current/head states and prove neither migration environment can open the other's DB.
Static/fake-systemd deployment tests cover fresh and upgrade identities/groups/modes,
socket peer/DAC denial, exact unit/socket/tmpfiles paths, effective-property verifier parsing,
root-owned broker-runtime independence, setup idempotency, offline order and initial-LKG
bootstrap. Temporary filesystem/state-machine tests cover selector publication, fsync/rename
crash windows, quota/ENOSPC, schema mismatch, complete slot generations and retained cleanup.
Package/systemd adapters use deterministic fakes or disposable non-host-mutating fixtures;
CI never installs host packages, restarts the CI service, writes repository state paths or
claims real root/systemd/Pi behavior.

Deployment/order tests prove selector publication alone cannot qualify a slot, daemon-
reload and effective stable-unit verification precede the only application start, broker
readiness precedes that start, and failure restores the exact retained unit/selector or
stops restricted. Peer tests bind installed executor/Git-credential/privileged-broker
artifact and protocol identities, reject peer-owned candidate changes and old-peer/new-
client combinations, and require peer-generated post-start receipts before LKG promotion.

The contract lane compiles every Phase 9 Tool/preparation schema and frozen evaluation case,
checks the HC0/HC2 mapping, exact minimum-attempt risk classes, information/result limits,
idempotency/ticket binding and reboot absence. A documentation-only plan PR need not add
those runtime files, but the Phase 9 implementation exit cannot pass without them.

37.4 Real candidate-Pi evidence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before promotion record:

* exact numeric identities/groups, protected-path modes/mounts, peer credentials, effective
  unit/socket/tmpfiles fragments/drop-ins and broker-runtime independence from candidate;
* exact package manager/version and deterministic prepare/execute plan behavior;
* repository metadata/artifact identity semantics;
* package transaction database/reconciliation evidence;
* systemd version, socket peer credentials and service lifecycle behavior;
* broker hardening actually enforced;
* filesystem durability/mount/ownership behavior for complete broker/runtime slots,
  including protected configuration/policy/manifest/service-definition material;
* fresh-host initial-LKG bootstrap, selector swap/fsync/crash recovery, bounded slot quota
  and upgrade from the prior application/broker schema heads;
* unit install/effective verification/daemon-reload ordering with exactly one selector-
  backed app start and broker readiness first;
* restart/readiness timing distribution;
* exact immutable/restorable complete LKG source/environment/configuration/policy/manifest/
  service-definition mechanism;
* exact build/test evidence production and final tested-state comparison;
* exact executor/Git-credential/privileged-broker installed build/protocol receipts and
  old-peer/new-client rejection;
* service runtime-selector/recovery behavior under stale/intervening state;
* application restart while Phase 7 process survives;
* application stop/crash while broker acceptance/restart continues and replacement startup
  remains Phase 6 recovery-closed on the exact retained fence;
* deliberately broken candidate rollback;
* deliberately unverifiable rollback -> restricted recovery;
* whether any Bootstrap operation truly requires reboot.

Unknown platform facts remain conditional until recorded.

38. Host authority and contract promotion
-----------------------------------------

Owner-approved development-session authority may cover the same-objective self-development
workflow, but privilege requires exact host-confirmation/authority review before Tool
promotion. Local authority is authenticated controller + policy + current development
session + exact Phase 4 operation + privileged ticket/profile. Host metadata/model prose
is not local authority.

Before any handler is exposed:

#. define/review versioned operation contracts;
#. define closed input/output/error schemas;
#. define information/confirmation classes;
#. add exact manifest entries and handler bindings;
#. validate schema/manifest/handler parity and fixtures;
#. validate internal broker IPC contracts separately;
#. reconcile catalogue/host behavior against real evidence when required.

The current manifest is not changed merely by accepting this plan.

The implementation PR must change the canonical contract sources, not create Phase 9
sidecar registries:

* ``spec/mcp/bootstrap-tool-manifest.yaml``;
* ``schemas/mcp/bootstrap-inputs.schema.json``;
* ``schemas/mcp/bootstrap-outputs.schema.json``;
* ``spec/policy/host-confirmation-classes.yaml``;
* ``spec/policy/capability-zones.yaml``;
* ``spec/mcp/evaluation-cases.yaml`` and ``spec/mcp/evaluation-profile.yaml``;
* compiler-owned ``src/binnacle/_generated/compatibility_core_registry.json`` and digest,
  unless a separately reviewed registry rename is performed atomically.

Manifest entries bind the table in section 4, the ``privileged_prepare``/HC2 execute
relationship, exact schemas, annotations, information/result limits, operation contract,
idempotency requirement, development-session/host authority, privileged profile and
handler binding. Schema/manifest/generated-registry/handler parity is a blocking CI gate.

Frozen Phase 9 cases use the existing risk-class names and minimum attempts from
``spec/mcp/evaluation-cases.yaml``:

* inspection/preflight/preparation Tool selection, bounded rendering and recovery-result
  rendering use ``tool_selection_and_result_rendering`` with minimum 10 attempts;
* owner confirmation allow/decline/dismiss/timeout and entitlement-only behavior use
  ``confirmation_and_entitlement`` with minimum 5 attempts;
* **every** package-install, service/self-restart, future reboot, cancellation, same-key
  retry, prepared-nonce reuse, cached/batch confirmation and tested-state-change case uses
  ``write_cancellation_retry_cache_confirmation`` with minimum 20 attempts;
* broker accept/seal, alternate-ticket, workspace-fence race, application/broker restart,
  response loss, candidate/rollback reconnect, wrong-runtime and restricted-recovery cases
  use ``concurrency_race_reconnect_instability`` with minimum 20 attempts.

Cases include exact prepared view and state binding; argument/device/action substitution;
expired/consumed preparation; package-plan/repository/artifact drift; tested-candidate drift;
different-ticket same-operation conflict; restart-versus-Phase 7/8 fence winner orders;
application disappearance/reconnect; systemd-active wrong runtime; candidate failure and
complete LKG rollback; corrupt/mixed slot generation; schema-head mismatch; audit failure;
credential/config redaction; and reboot absence. Evidence binds exact profile/build/config/
policy/manifest/schema digests, Phase 4 operation/audit, Phase 6 fence, Phase 7 verification,
broker operation binding/checkpoint/subeffect, runtime-slot generation and detached
evaluation receipt. Missing real Pi/ChatGPT attempts remain blocked; they never stop
repository-only implementation and CI work.

39. Implementation order
------------------------

#. Freeze/promote Phase 9 semantic contracts/schemas/host-authority classification.
#. Add broker/service/package/runtime-slot protected profile models.
#. Implement ticket issuer/validator and exact peer boundary.
#. Implement broker protocol and separate evidence schema/migrations.
#. Implement operation-scoped ``BrokerAcceptanceGate``, immutable one-ticket binding,
   ``accept_once`` and ``seal_no_accept`` with fault tests before any root adapter.
#. Implement read-only package/service inspection.
#. Implement deterministic ``PackageTransactionPlan`` prepare/verify logic.
#. Implement exact package execute/reconcile behind disabled composition.
#. Integrate restart admission with the Phase 6 exclusive ``CHANGE`` guard and durable
   mutation fence, including replacement-application recovery-closed startup tests.
#. Implement restart preflight/overlap reservations and runtime identity.
#. Implement protected Phase 7 candidate-verification profiles/evidence binding and
   no-schema-change admission.
#. Implement protected peer-owned path/build/protocol identities, peer-generated
   compatibility receipts and no-peer-service-change admission.
#. Implement complete protected ``VerifiedRuntimeSlot`` storage/validation for source,
   environment, configuration, policy, manifest and effective service-definition
   material, plus candidate/LKG eligibility.
#. Implement broker checkpoint/restart state machine without host exposure.
#. Implement fixed systemd adapter and application/broker reconciliation.
#. Implement candidate runtime selection and exact post-start verification.
#. Implement complete LKG source/environment/configuration/policy/manifest/service-
   definition recovery and restricted-recovery path.
#. Compose simple service restart and controlled restart behind all promotion gates.
#. Keep reboot seam unpromoted unless real evidence requires it.
#. Run full property/Linux/fault/security suite and candidate-Pi evidence campaign.
#. Only then expose reviewed host-facing operations supported by current evidence.

40. Holistic pre-review checklist
---------------------------------

The complete pipeline is:

``request/session/current state -> caller-binding-first retained lookup -> received audit
-> policy -> no-effect HC2 preparation + post-policy privileged/restart/package-plan /
workspace-fence reservation -> immutable one-ticket operation binding -> authorised audit
-> running/effect intent -> Phase4 handoff/session/consequential gates -> final controller /
device / preparation / tested-candidate / schema / package-plan / service / candidate /
LKG-runtime-slot / outstanding-work / audit / recovery OP-BOUNDARY -> audit obligation ->
exact retained privileged ticket -> broker peer/ticket validation -> operation-scoped
BrokerAcceptanceGate accept OR terminal no-accept seal -> accepted root-side state machine
-> immediate subeffect evidence -> package/service/candidate/LKG reconciliation ->
application audit/operation reconciliation -> process/reservation/fence cleanup -> retained
retry``.

Verify specifically:

* queued requests cannot defeat no-accept closure;
* an alternate ticket cannot bypass an operation's accepted/sealed binding;
* accepted work never expires into abandonment;
* package plan binds the complete root-running transaction closure;
* LKG source, environment, protected configuration, policy, manifest and service
  definition are independently and atomically restorable/selectable;
* editable workspace/shared ``.venv`` cannot masquerade as rollback safety;
* application/executor/Git/root-broker authority remains disjoint;
* checkpoint/LKG are durable before stop;
* candidate readiness is exact runtime identity;
* candidate restart binds fresh exact isolated build/test success and unchanged tested
  state;
* candidate/LKG bind exact independently deployed peer builds/protocols and cannot promote
  against a stale or self-asserted peer set;
* rollback does not depend on failed application;
* ambiguous rollback becomes restricted recovery;
* Phase 7/8 outstanding work and package effects are in preflight;
* Phase 6 ``CHANGE`` plus durable mutation-fence ownership closes admission races after
  preflight and survives the application process being restarted;
* Phase 4 effect/audit/idempotency truth survives application replacement;
* every uncertain root effect blocks blind repeat;
* no reusable secret leaks;
* reboot remains absent by default.

41. Plan acceptance
-------------------

This planning PR may merge when:

* it changes exactly this numbered Phase 9 document;
* holistic review is complete;
* exact-head Contract Validation and Python CI are green;
* mandatory exact-head Codex substantive review is clean and actionable threads resolved;
* Copilot is attempted at most once per exact head and remains best-effort;
* no unknown Pi/ChatGPT behavior is stated as supported.

Plan acceptance grants no privileged runtime authority.

42. Implementation/promotion gate
---------------------------------

Promotion remains blocked until at least:

* real Phase 4 durable-kernel implementation exit is current;
* real Phase 8 Git implementation exit is current;
* predecessor controller/session/host evidence is current;
* Phase 9 contracts/schemas/manifest/host-authority classification are reviewed;
* broker/service/package/runtime-slot profiles are registered;
* accept-or-seal/replay isolation is proven on candidate Pi;
* deterministic complete package-plan preparation/execution is proven;
* selected systemd/readiness behavior is proven;
* exact isolated candidate build/test provenance and stale-state rejection are proven;
* exact peer build/protocol receipts and old-peer/new-client rejection are proven;
* Phase 6 restart-fence exclusion and replacement-application recovery are proven;
* independently restorable complete LKG source/environment/configuration/policy/manifest/
  service-definition runtime slot is proven, or the safe no-change fallback is enforced
  for every unsupported material class;
* failed candidate rollback and restricted recovery are proven;
* fault/security/redaction gates pass.

If any selected platform mechanism cannot meet these invariants, the affected privileged
operation remains unavailable rather than weakening the plan.

43. Phase exit
--------------

Real Phase 9 exit requires real ChatGPT on the real development Pi to prove with retained
evidence:

#. inspect outstanding work and restart impact;
#. inspect exact runtime identity;
#. request controlled restart of an exact candidate;
#. observe application connection disappearance without loss of broker/restart truth;
#. reconnect to the same endpoint;
#. verify exact candidate Git/environment/config/policy/manifest and readiness;
#. inspect bounded startup diagnostics;
#. prove no reusable credential/root authority disclosure;
#. run a deliberately broken candidate and prove exact complete LKG source/environment/
   configuration/policy/manifest/service-definition rollback to a reachable verified
   runtime, or a verified restricted local-recovery state whose evidence survives outside
   the failed process.

Only then is Phase 9 complete. Missing real Pi/ChatGPT evidence does not block provisional
plan acceptance but blocks this exit and the real Phase 10 acceptance run.
