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

2.7 Restart owns the shared workspace exclusion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Restart preflight is advisory evidence, not concurrency control. Every simple or controlled
Binnacle restart that depends on the development workspace/runtime acquires the exact
Phase 6 exclusive ``WorkspaceAccessGate.CHANGE`` coordination seam and its durable
workspace mutation fence after policy and before privileged dispatch. The durable fence is
retained through broker acceptance, application disappearance, candidate/LKG selection,
rollback/restricted recovery and final audit/operation closure. A replacement application
reconstructs workspace change admission closed from that retained fence before Phase 7/8
workspace-changing work may start. Point-in-time outstanding-work inspection alone never
proves the checkout or runtime remains stable during restart.

3. Source-of-truth composition
------------------------------

Phase 9 consumes earlier foundations:

* Phase 4 owns caller-binding-first idempotency, lifecycle, audit, final OP-BOUNDARY,
  audit obligations, effect knowledge and retained retry;
* Phase 6 owns development-session authority and the shared workspace access/change
  coordination seam; Phase 9 restart must consume the same exclusive ``CHANGE`` guard and
  durable mutation fence rather than creating a restart-only parallel lock;
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
* ticket verification key/reference and algorithm profile;
* service hardening digest;
* candidate-Pi capability-evidence digest.

5.2 ``BinnacleServiceProfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* exact development service unit name;
* exact development workspace/source identity;
* exact runtime-selector/recovery root;
* service user/group;
* protected configuration/policy/manifest identities and the exact protected material
  store/selector used to restore them;
* exact service-unit/drop-in/runtime-selector composition identity and protected
  restorable material reference;
* expected executable/entry point;
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
reboot facts. Restart tickets additionally bind the exact Phase 6 workspace-change fence
identity/generation and candidate/LKG runtime-control-bundle identities. Ticket expiry
blocks first acceptance only. A retained accepted ticket remains recoverable after expiry.

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

8.1 Ticket-scoped ``BrokerAcceptanceGate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every exact ``(operation_id, ticket_id, ticket_sha256)`` owns one broker acceptance gate
(or an equivalent serialized FULL transaction boundary). The gate is shared by:

* ``accept_once``;
* ``seal_no_accept``;
* retained replay/reconciliation that needs to determine the acceptance winner.

No root package/systemd/recovery effect runs while this acceptance gate is held. Gate
ownership ends after the durable acceptance/seal decision is committed.

8.2 ``accept_once``
~~~~~~~~~~~~~~~~~~~

Under the gate and one FULL transaction:

#. verify peer-independent ticket integrity/action/target/replay identity;
#. reject a conflicting ticket digest/semantic fingerprint;
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

A broker crash never causes replay by allocating a new ticket or new subeffect identity.

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
* predicted service-restart impact;
* blocking or cleanup/cancel reasons.

A source-changing Phase 7/8 operation normally blocks controlled restart/rollback of the
same Binnacle source/runtime unless exact non-overlap is proven. Package mutation and an
unresolved prior restart also block a new restart. This read-only result is advisory: the
consequential restart must subsequently acquire the shared Phase 6 ``CHANGE`` guard and
durable workspace mutation fence and then revalidate the relevant preflight/current-state
facts while that exclusion is owned.

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
* readiness generation.

No raw environment variable or credential value is returned.

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
* exact ``RuntimeControlBundle`` ID/version and immutable/protected bundle-root identity;
* independently restorable configuration, policy, promoted contract/manifest and exact
  service-unit/drop-in/runtime-selector material identities, plus their content digests;
* service-profile digest and the exact selector needed to activate this control bundle;
* readiness evidence from the run that qualified the slot;
* creation/promotion evidence generation and retention state.

The LKG slot is stored outside the normal editable development checkout or otherwise
protected so ordinary candidate editing/dependency synchronization cannot mutate it.
The exact materialization mechanism is evidence-gated: a protected worktree/runtime tree,
immutable copy/artifact or equivalent may be selected only after candidate-Pi durability,
disk and startup behavior is verified.

The control material is not digest-only recovery metadata. The protected slot must contain
immutable/restorable bytes or an equivalently protected independently selectable artifact
for the exact configuration, policy, promoted contract/manifest and service definition
needed to start that LKG runtime. If a protected file contains a reusable secret, the slot
stores only the protected secret reference/selector required by the service profile, not a
new plaintext secret copy; restoration must prove the reference still resolves to the
same allowed authority. Source, environment and ``RuntimeControlBundle`` form one runtime
slot and are selected/restored as one exact unit. A profile that cannot independently
restore the complete control bundle must reject a candidate that changes any of those
control identities before service stop.

15.2 Candidate environment and control-material rule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Preparing a candidate may mutate the normal development ``.venv``. That mutable
environment is never treated as the LKG environment merely because its digest was once
recorded.

Controlled restart promotion requires one of two reviewed profiles:

#. **independent-LKG profile** -- a complete protected LKG runtime slot already exists and
   the service/recovery adapter can select it without overwriting unrecognized editable
   workspace state; or
#. **no-environment-or-control-change profile** -- until an independent complete LKG
   slot mechanism is proven, controlled restart rejects any candidate whose interpreter /
   lock / environment / configuration / policy / manifest / service-definition identity
   differs from the current verified LKG.

The implementation must never start restored LKG source with an unproven candidate-mutated
shared environment or candidate control material.

15.3 LKG promotion
~~~~~~~~~~~~~~~~~~

A candidate becomes the new LKG only after exact runtime identity/readiness and required
audit closure succeed and its protected source+environment+``RuntimeControlBundle`` slot
is durably materialized/verified. The previous complete slot is retained until new-slot
promotion is durable. A candidate cannot destroy or mutate the only verified recovery
source, environment or control bundle before it has qualified.

16. Controlled restart checkpoint
---------------------------------

The broker-owned ``RestartCheckpoint`` is fsynced before service stop and binds:

* checkpoint ID/version and Phase 4 operation/ticket identity;
* exact development service;
* candidate source Git OID/branch/dirty expectation;
* candidate interpreter/environment/lock/config/policy/manifest/service-composition
  identities and exact candidate ``RuntimeControlBundle`` reference;
* exact candidate runtime slot or candidate-runtime selector inputs;
* exact retained LKG ``VerifiedRuntimeSlot`` ID, protected source/environment/control
  bundle references and all protected identity digests;
* exact Phase 6 workspace-change fence ID/owner/generation retained for this restart;
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
the checkpoint's candidate or exact retained LKG runtime slot.

Preferred recovery avoids destructive reset of the editable development workspace. A
protected service runtime selector or equivalent exact mechanism points the service at the
candidate/LKG slot while preserving unrelated/unrecognized editable state. The selected
slot includes source, environment and the exact protected ``RuntimeControlBundle``. If a
candidate implementation instead requires restoration into shared source, environment or
control-material locations, that mechanism must prove exact old-state/CAS semantics and
refuse intervening state.

Required invariants:

* target is exactly the checkpoint slot;
* no arbitrary path/revision/environment/config/policy/manifest/service definition is
  accepted;
* source, environment and the complete runtime control bundle are selected/restored and
  verified as one checkpoint-bound runtime before service start;
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
#. advisory restart preflight;
#. acquire exclusive Phase 6 ``WorkspaceAccessGate.CHANGE`` and, only when the workspace
   mutation fence is free, publish the exact durable restart-owned workspace change fence;
#. while that exclusion is owned, revalidate candidate/protected LKG slot eligibility and
   the outstanding Phase 7/8/workspace facts that made preflight acceptable;
#. post-policy one-restart reservation bound to the exact workspace fence;
#. authorised audit;
#. running/effect intent;
#. Phase 4 handoff/session/consequential gates;
#. final controller/device/session/service/candidate/LKG/workspace-fence /
   outstanding-work/audit/recovery OP-BOUNDARY;
#. durable audit obligation;
#. privileged ticket dispatch.

Broker flow first wins accept-or-seal. If accepted, it durably creates/verifies
``checkpoint_ready`` including the protected LKG slot and the exact restart-owned Phase 6
workspace fence before systemd stop. The application may disappear after stop, but the
durable fence remains authoritative; a replacement application reconstructs workspace
change admission closed before exposing Phase 7/8 changers and releases it only after
truthful restart/recovery/audit closure.

18.2 Candidate lifecycle
~~~~~~~~~~~~~~~~~~~~~~~~

The broker selects/verifies the exact candidate runtime, requests exact service stop/start
and records each systemd effect receipt. Application disappearance is expected.

Candidate success requires:

* endpoint/readiness within the deadline;
* exact candidate Git OID;
* branch/dirty expectation;
* source/runtime-slot/environment/lock identities;
* exact selected ``RuntimeControlBundle`` identity and configuration/policy/manifest /
  service-composition digests;
* device/service identities;
* absence of disqualifying fail-restricted startup state.

Systemd active with wrong identity is candidate failure.

18.3 Candidate success and LKG promotion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Only exact verified ``candidate_ready`` can be reconciled as requested restart success.
The replacement application closes Phase 4 audit/operation obligations from broker
evidence. Protected new-LKG slot promotion occurs only after required verification/audit
closure and complete source+environment+control-bundle materialization; it never destroys
the previous complete LKG before durable promotion. The restart-owned workspace fence is
not released merely because the candidate is ready; release waits for operation/audit and
runtime-slot promotion/retention obligations to reach the reviewed terminal closure.

19. Failed-candidate rollback
-----------------------------

Candidate timeout, crash loop, wrong identity/config/environment or disqualifying
readiness enters ``rollback_required`` without depending on model reasoning or failed
application cooperation.

The broker:

#. reaches a service state safe for recovery;
#. verifies the retained LKG slot is complete and unchanged;
#. selects/restores exact LKG source, environment **and protected runtime control
   bundle** through ``SelfRecoveryAdapter`` as one checkpoint-bound recovery target;
#. verifies the selected service definition/configuration/policy/manifest composition
   before service start;
#. records exact recovery receipt;
#. starts the exact service;
#. verifies exact LKG runtime identity/readiness;
#. records ``rollback_ready`` only when proven.

The original requested candidate restart is not reported as success when rollback wins.
Host-visible result says candidate failed and LKG recovery succeeded.

20. Restricted local recovery
-----------------------------

Missing/corrupt LKG source/environment/control material, unresolved protected secret
reference, disk-full, systemd failure, ambiguous selector receipt, package damage,
filesystem mismatch or power loss may make rollback unverifiable.
The broker then stops bounded autonomous recovery and enters ``restricted_recovery``.

Root-protected retained evidence includes restart/checkpoint ID, candidate/LKG runtime-slot
identities, last proven service/runtime state, failed/uncertain action, bounded diagnostics,
static-template local operator instructions and evidence digest. Instructions are not
model-generated arbitrary root shell commands.

21. Simple service restart
--------------------------

``binnacle_service_restart`` is only for restarting the fixed service when source,
environment, config and candidate/LKG semantics are unchanged. It still requires advisory
preflight, acquisition of the same exclusive Phase 6 ``CHANGE`` guard/durable workspace
mutation fence, and exact post-restart runtime verification before truthful fence release.
This prevents a Phase 7/8 source changer from being admitted after preflight but before or
during the service restart.

``binnacle_restart`` is mandatory whenever source/environment/config/policy/manifest /
service-composition candidate identity changes or rollback semantics may be needed. The
final current-state verifier prevents a caller from selecting the simple path for a
candidate-changing restart.

22. Application/broker restart reconciliation
---------------------------------------------

Application startup queries broker acceptance/effect/recovery evidence before new
privileged work. It reconciles exact operation/ticket/checkpoint/evidence generation,
runtime identity, Phase 4 effect knowledge, audit obligations and Phase 6/7/8 cleanup.

If Phase 4 ``call_start`` occurred but broker acceptance is unknown, application recovery
may request gate-owned ``seal_no_accept`` only under the rule in section 8. If acceptance
won, the application reconciles/resumes the accepted broker operation. Empty broker store
alone never releases the Phase 4 operation/fence.

Broker startup validates every retained accepted pre-effect state and resumes its exact
operation-specific state machine. It never abandons accepted work because the ticket
expired or session ended.

Application startup reconstructs the Phase 6 workspace coordinator from any retained
restart-owned durable mutation fence **before** enabling source-changing Phase 7/8 or
Phase 6 mutation admission. Broker terminal/recovery evidence, application audit closure
and the exact fence owner/generation must agree before that fence is released. Missing or
ambiguous broker evidence keeps workspace change admission closed.

Broker unavailability while privileged work may be incomplete keeps affected Phase 4
operations uncertain/reconciling and blocks overlapping privileged work.

23. Restart preflight versus Phase 7/8 work
-------------------------------------------

A Phase 7 command may survive application restart only when its independent supervision,
workspace/profile and non-overlap predicates remain valid. Source-changing work that can
race candidate/LKG runtime selection normally blocks controlled restart. Active
credentialed Git effects, package transactions, prior restart/recovery, audit failure or
uncertain source mutation also block.

Preflight is not the exclusion primitive. Restart admission must acquire the shared Phase
6 exclusive ``CHANGE`` side only after currently active changers have truthfully closed;
while it owns the durable workspace fence, every later Phase 6 mutation and Phase 7/8
workspace-changing start observes that fence and cannot begin. If the application exits,
the retained fence reconstructs the new runtime's workspace coordinator closed until the
same restart reaches truthful terminal/recovery closure.

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
The restart-owned Phase 6 workspace fence is coordination state, not proof of the systemd
subeffect; it remains held until exact terminal/recovery/audit closure and is never released
from service/process presence alone.

27. Idempotency, overlap and cancellation
----------------------------------------

Phase 4 caller idempotency remains authoritative. Broker replay prevention is defense in
depth. Same-owner/same-key/same-fingerprint retries reconcile retained application/broker
state before mutable checks. An uncertain retained root effect never receives a fresh
ticket just to retry it.

Overlap rules include:

* one package mutation at a time;
* no package mutation overlapping service/self-restart;
* one restart/recovery slot at a time;
* no new restart while rollback/recovery unresolved;
* simple/controlled restart owns the shared Phase 6 workspace ``CHANGE`` guard/durable
  mutation fence before dispatch, so no source-changing Phase 6/7/8 work overlaps runtime
  selection, service transition or rollback closure;
* future reboot excludes every unproven consequential operation.

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
applicable. Runtime-slot storage treats source, environment and the protected
``RuntimeControlBundle`` as one checkpoint-bound object set; candidate operations cannot
rewrite the retained LKG control material in place.

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
* ``restart_workspace_fence_unavailable`` / ``restart_workspace_fence_uncertain``;
* ``restart_checkpoint_failed``;
* ``lkg_runtime_slot_unavailable`` / ``lkg_control_bundle_unavailable``;
* ``candidate_environment_unsupported`` / ``candidate_control_material_unsupported``;
* ``restart_candidate_failed`` / ``restart_rolled_back``;
* ``restart_rollback_failed`` / ``restart_restricted_recovery``;
* ``runtime_identity_mismatch``;
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

   class RestartWorkspaceCoordinationPort(Protocol):
       async def acquire_change(self, request: RestartChangeRequest) -> RestartChangeLease: ...
       async def reconcile_change(self, operation_id: str) -> RestartChangeLease: ...
       async def release_after_terminal(self, lease: RestartChangeLease) -> None: ...

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
       def verify_control_bundle(self, slot_id: str) -> RuntimeControlBundleVerification: ...
       def materialize_candidate(self, request: RuntimeSlotPrepare) -> RuntimeSlotReceipt: ...
       def promote_lkg(self, request: RuntimeSlotPromotion) -> RuntimeSlotReceipt: ...

   class SelfRecoveryAdapter(Protocol):
       def select_candidate(self, checkpoint: RestartCheckpoint) -> RecoveryReceipt: ...
       def restore_lkg(self, checkpoint: RestartCheckpoint) -> RecoveryReceipt: ...
       def verify_runtime(self, checkpoint: RestartCheckpoint) -> RuntimeVerification: ...

No port accepts arbitrary shell strings, arbitrary systemd units or caller-selected root
paths.

33. Persistence ownership
-------------------------

Application-side Phase 9 metadata extends Phase 4 only for correlation/reservation:
privileged ticket digest/reference, broker evidence generation/reference, target/profile
digest, restart slot/checkpoint reference, exact restart-owned Phase 6 workspace-fence
reference/generation, package transaction-plan digest and observed candidate/rollback
outcome.

Broker migrations are separate and immutable. Broker tables include accepted tickets,
no-accept tombstones, privileged subeffect state, package-plan evidence and restart/runtime
slot/checkpoint state. Accepted ticket and no-accept tombstone are mutually exclusive for
one exact ticket identity.

Migration/integrity failure keeps new privileged effects unavailable; it never silently
repairs unknown state.

34. systemd and installation assets
-----------------------------------

Phase 9 implementation will add broker service/socket assets only after contracts/profiles
are reviewed. Candidate hardening may include narrow filesystem access, private temporary
storage, restrictive umask, exact ``RuntimeDirectory``/``StateDirectory`` ownership,
appropriate capability reduction and ``NoNewPrivileges`` only where compatible with the
selected root mechanisms.

No hardening directive is claimed effective until verified on the candidate Pi.

35. Security invariants
-----------------------

The implementation must mechanically preserve:

#. Application is never root.
#. Phase 7/8 children cannot connect to broker.
#. Broker exposes no generic root command/path/unit/package-option surface.
#. Every root effect has Phase 4 operation identity before dispatch and broker replay
   identity before root subeffect.
#. Accept-or-seal gives exactly one terminal acceptance winner.
#. Delayed/queued handlers cannot accept after no-accept seal.
#. Accepted work remains recoverable after ticket/session expiry.
#. Broker replay cannot create a second effect.
#. Package install executes only the exact prepared complete transaction closure.
#. Repository metadata/solver/artifact mismatch before package effect yields zero effect.
#. Arbitrary systemd units cannot be selected.
#. Restart acquires the shared Phase 6 exclusive workspace ``CHANGE`` guard and durable
   mutation fence before broker dispatch and retains it through truthful terminal/recovery
   and audit closure.
#. Checkpoint and complete LKG runtime slot are durable before service stop.
#. LKG includes independently restorable source, environment and protected
   configuration/policy/manifest/service-definition control material.
#. Candidate cannot mutate/destroy the only verified LKG source, environment or control
   bundle.
#. Candidate success requires exact runtime identity/readiness, not systemd active.
#. Rollback is broker-owned and does not depend on failed candidate.
#. Unverifiable rollback enters restricted recovery instead of looping.
#. Shared mutable candidate ``.venv`` is never treated as LKG environment.
#. Empty broker store/application response is not no-effect proof after call-start.
#. Active Phase 7/8 work participates in restart preflight, and the shared Phase 6 fence
   closes the race between that preflight and later workspace-changing admission.
#. Audit failure before start prevents effect; later audit failure does not erase truth.
#. Reboot remains absent until separately evidenced/promoted.
#. Results/logs/evidence/recovery markers disclose no reusable secret.

36. Holistic concurrency and crash model
----------------------------------------

Walk at least:

* queued broker handler versus gate-owned no-accept sealing after app crash;
* broker accepts then crashes before first root subeffect;
* ticket expires/session ends after acceptance;
* two package installs;
* package metadata/solver plan changes after prepare but before broker effect;
* malicious repository metadata broadens dependency closure;
* package install races controlled restart;
* two self-restarts with different candidates;
* restart preflight clean versus a source-changing Phase 7/8 admission racing the shared
  ``CHANGE`` acquisition: exactly one side owns the workspace mutation fence;
* application dies after restart fence acquisition and before/after broker acceptance;
* app crash before/after broker acceptance/receipt;
* broker crash after package manager/systemd start but before receipt;
* checkpoint fsync failure;
* service stop then broker crash;
* candidate active with wrong revision/environment/config;
* mutable development ``.venv`` changed after LKG qualification;
* candidate configuration/policy/manifest/service definition changes while the retained
  LKG control bundle remains independently restorable;
* protected LKG environment or control bundle missing/corrupt before service stop;
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

Test ticket canonicalization/replay/expiry, accept-or-seal state machine, delayed handler
rejection, package-plan canonicalization, complete dependency closure, service target
binding, runtime-slot/LKG source+environment+control-bundle eligibility, shared restart
workspace-fence ownership/reconstruction, restart transitions, runtime identity matching,
error redaction and reboot absent-by-default.

Property/state-machine tests inject crashes between every durable broker transition and
prove no double root effect, no accept after seal, no accepted-work abandonment, no
package-plan broadening and no ambiguous rollback promoted to success.

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
* checkpoint/runtime-slot/control-bundle fsync durability;
* restart preflight versus source-changing Phase 7/8 admission: exactly one shared Phase 6
  ``CHANGE`` owner and zero overlap; replacement app reconstructs retained fence closed;
* app death with broker handler queued: accept versus seal one durable winner;
* broker crash after accepted before root boundary: accepted recovery resumes/closes;
* environment/control-material-changing candidate uses an independently protected
  complete LKG runtime slot or is rejected;
* corrupt/missing LKG environment/control bundle before stop => zero service-stop effect;
* corrupt/missing LKG environment/control bundle after effect => restricted recovery,
  never false rollback success;
* service stop/start while application absent;
* source/runtime-slot path symlink/mount replacement fails closed;
* secret redaction.

37.3 Real candidate-Pi evidence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before promotion record:

* exact package manager/version and deterministic prepare/execute plan behavior;
* repository metadata/artifact identity semantics;
* package transaction database/reconciliation evidence;
* systemd version, socket peer credentials and service lifecycle behavior;
* broker hardening actually enforced;
* filesystem durability/mount/ownership behavior for broker/runtime slots;
* restart/readiness timing distribution;
* exact immutable/restorable LKG source+environment+configuration/policy/manifest /
  service-definition control-bundle mechanism;
* shared Phase 6 workspace-fence acquisition/reconstruction across application stop/start;
* service runtime-selector/recovery behavior under stale/intervening state;
* application restart while Phase 7 process survives;
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

39. Implementation order
------------------------

#. Freeze/promote Phase 9 semantic contracts/schemas/host-authority classification.
#. Add broker/service/package/runtime-slot protected profile models.
#. Implement ticket issuer/validator and exact peer boundary.
#. Implement broker protocol and separate evidence schema/migrations.
#. Implement ``BrokerAcceptanceGate``, ``accept_once`` and ``seal_no_accept`` with fault
   tests before any root adapter.
#. Implement read-only package/service inspection.
#. Implement deterministic ``PackageTransactionPlan`` prepare/verify logic.
#. Implement exact package execute/reconcile behind disabled composition.
#. Implement restart preflight plus consumption of the exact Phase 6 shared workspace
   ``CHANGE`` guard/durable mutation fence and restart-time reconstruction before source
   changers are enabled.
#. Implement protected ``VerifiedRuntimeSlot`` storage/validation, complete
   ``RuntimeControlBundle`` materialization/restoration and candidate/LKG eligibility.
#. Implement broker checkpoint/restart state machine without host exposure.
#. Implement fixed systemd adapter and application/broker reconciliation.
#. Implement candidate runtime selection and exact post-start verification.
#. Implement atomic LKG source+environment+runtime-control-bundle recovery and the
   restricted-recovery path.
#. Compose simple service restart and controlled restart behind all promotion gates.
#. Keep reboot seam unpromoted unless real evidence requires it.
#. Run full property/Linux/fault/security suite and candidate-Pi evidence campaign.
#. Only then expose reviewed host-facing operations supported by current evidence.

40. Holistic pre-review checklist
---------------------------------

The complete pipeline is:

``request/session/current state -> caller-binding-first retained lookup -> received audit
-> policy -> advisory restart preflight -> for service/self-restart acquire Phase6
WorkspaceAccessGate.CHANGE + exact durable workspace mutation fence -> revalidate
candidate/LKG/control-bundle/outstanding-work under exclusion -> post-policy privileged /
restart / package-plan reservation -> authorised audit -> running/effect intent -> Phase4
handoff/session/consequential gates -> final controller / device / package-plan / service /
candidate / complete LKG-runtime-slot / workspace-fence / outstanding-work / audit / recovery
OP-BOUNDARY -> audit obligation -> exact privileged ticket -> broker peer/ticket validation
-> BrokerAcceptanceGate accept OR terminal no-accept seal -> accepted root-side state machine
-> immediate subeffect evidence -> package/service/candidate/LKG reconciliation -> application
audit/operation reconciliation -> truthful workspace-fence/process/reservation cleanup ->
retained retry``.

Verify specifically:

* queued requests cannot defeat no-accept closure;
* accepted work never expires into abandonment;
* package plan binds the complete root-running transaction closure;
* restart preflight is closed by the exact shared Phase 6 workspace fence before dispatch,
  and that fence survives application replacement until terminal/recovery closure;
* LKG source, environment and configuration/policy/manifest/service control bundle are
  independently restorable as one runtime slot;
* editable workspace/shared ``.venv`` or candidate control files cannot masquerade as
  rollback safety;
* application/executor/Git/root-broker authority remains disjoint;
* checkpoint/LKG are durable before stop;
* candidate readiness is exact runtime identity;
* rollback does not depend on failed application;
* ambiguous rollback becomes restricted recovery;
* Phase 7/8 outstanding work and package effects are in preflight, while the shared
  workspace fence prevents a new changer from entering after the check;
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
* independently restorable LKG source+environment+configuration/policy/manifest /
  service-definition runtime slot is proven, or the safe no-environment-or-control-change
  fallback is enforced;
* Phase 9 restart consumption/reconstruction of the exact Phase 6 shared workspace-change
  fence is proven across application disappearance and reconnect;
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
#. verify exact candidate Git/environment/config/policy/manifest/service composition and
   readiness;
#. inspect bounded startup diagnostics;
#. prove no reusable credential/root authority disclosure;
#. run a deliberately broken candidate and prove exact LKG source+environment+protected
   configuration/policy/manifest/service composition rollback to a reachable verified
   runtime, or a verified restricted local-recovery state whose
   evidence survives outside the failed process.

Only then is Phase 9 complete. Missing real Pi/ChatGPT evidence does not block provisional
plan acceptance but blocks this exit and the real Phase 10 acceptance run.
