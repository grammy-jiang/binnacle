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
             development plan; the Phase 4 and Phase 8 implementation exits before
             privileged runtime promotion
:Primary objective: Give ChatGPT only the privileged host capabilities required to keep
                    Binnacle self-development moving, including a deterministic and
                    independently recoverable controlled-restart path

1. Purpose and phase boundary
-----------------------------

Phase 9 is the first Bootstrap phase that intentionally introduces root authority.
That authority exists only in a separate privileged broker and only for a closed,
reviewed vocabulary of structured operations. The network-facing MCP/application process
remains unprivileged. The Phase 7 command executor remains unprivileged. Neither process
receives a root shell, unrestricted ``sudo``, package-manager command line, arbitrary
systemd unit name, arbitrary filesystem mutation, or generic broker forwarding surface.

The roadmap requires only the privileged capabilities that block the first self-hosting
loop:

* inspect required operating-system package state;
* install one specifically requested development OS package under a reviewed package
  profile;
* inspect Binnacle service state;
* restart the exact Binnacle development service;
* perform the controlled Binnacle self-restart path with checkpoint and rollback;
* reboot only if real Bootstrap evidence later proves that reboot is necessary.

Everything else remains outside Phase 9. In particular Phase 9 does not introduce:

* a generic root shell or arbitrary ``exec`` as root;
* arbitrary file read/write/delete as root;
* arbitrary systemd unit management;
* arbitrary package removal, repository addition, kernel/module work, firewall/network
  administration, user/group management, mount administration, device administration,
  bootloader/firmware changes, or container-engine authority;
* reusable root credentials visible to ChatGPT or child processes;
* broad configuration editing through the privileged broker;
* automatic reboot merely because a package manager recommends one;
* production release packaging or general fleet management.

The phase is deliberately split into three readiness questions:

#. **Plan acceptance** asks whether this document is internally coherent and review/CI
   clean without inventing host evidence.
#. **Implementation/promotion readiness** requires the predecessor implementation exits,
   reviewed contracts/schemas/manifest entries, real candidate-Pi systemd/package/broker
   evidence, and production fail-closed composition.
#. **Phase exit** requires the real restart/reconnect/verification workflow and one real
   failed-candidate recovery case.

2. Governing decisions
----------------------

The following already-approved principles are binding.

2.1 The application is not root
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MCP/application process runs under its ordinary unprivileged Binnacle identity. Root
exists only in the broker process. The broker is independently supervised by systemd and
has a filesystem/socket boundary that the Phase 7 command child cannot access.

The application remains the authoritative owner of Binnacle operation lifecycle in the
Phase 4 SQLite database. The broker must not open or mutate the application database.
The broker owns only the minimum independent evidence necessary to prevent replay and to
recover privileged work across application replacement/restart.

2.2 Privilege is operation-specific
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A privileged ticket is not a generic delegation token. It binds one semantic operation,
its exact target, maximum effect, relevant protected current-state facts, controller and
device identity, policy/contract version, expiry and single-use identity.

The root broker validates the ticket independently. Receipt of a message from the
application socket is not sufficient authority.

2.3 Self-management is not ``command_run``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 7 development execution and Phase 9 privileged execution are separate security
domains. A command profile cannot request elevation and the root broker cannot be reached
through the general executor. Phase 9 operations are typed application use cases with
closed broker messages.

2.4 Restart truth must survive the process being restarted
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A controlled restart cannot depend on the replaceable MCP/application process to finish
its own recovery. Before stopping the candidate application, the broker/recovery side
must durably retain enough protected evidence outside that process to know:

* which candidate revision/configuration was requested;
* which last-known-good revision/checkpoint is eligible for rollback;
* the exact fixed service/unit identity;
* the expected runtime/config/policy/build facts;
* restart attempt identity and deadline;
* the exact rollback action allowed if candidate readiness fails;
* what local recovery state/evidence must remain if rollback cannot be verified.

2.5 Real evidence outranks guessed platform support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This plan may name standard Linux/systemd/package-manager mechanisms, but it does not
claim that the selected development Pi already supports a particular systemd property,
package-manager option, reboot requirement, service timeout, filesystem atomicity or
broker hardening feature. Promotion requires exact candidate-Pi verification.

3. Source-of-truth and predecessor composition
----------------------------------------------

Phase 9 consumes rather than reimplements the earlier foundations.

* Phase 4 owns caller-binding-first idempotency, lifecycle, required audit, final
  consequential-boundary checks, audit obligations, effect knowledge and retained retry.
* Phase 6 owns the development-session authority model and the shared workspace
  ``WorkspaceAccessGate``/durable mutation-fence semantics.
* Phase 7 owns independent long-running development-command supervision and outstanding
  operation truth.
* Phase 8 owns the signed feature-branch/push workflow and exact local source revision
  facts used as candidate input to self-management.

A Phase 9 operation may refer to those facts, but it does not silently redefine them.
For example, the broker does not decide whether a Git revision is an authorised
self-development candidate; the application binds that decision into the privileged
operation before the broker accepts it.

4. Proposed host-facing semantic surface
----------------------------------------

No Phase 9 Tool name is final until reviewed operation contracts, input/output schemas,
manifest entries and host-confirmation classification are promoted and validated.
The evidence-independent plan uses the following names only as working proposals:

* ``package_inspect``;
* ``package_install``;
* ``binnacle_service_inspect``;
* ``restart_preflight``;
* ``binnacle_restart``;
* ``binnacle_runtime_inspect``;
* ``host_reboot`` only if later real evidence promotes it.

The plan should prefer one semantic Tool per owner-relevant operation rather than exposing
broker protocol primitives. Broker IPC operations are internal and may be finer-grained.

Read-only inspection Tools are bounded no-effect operations. Package installation,
service restart, controlled self-restart and reboot are consequential Phase 4 operations.

5. Protected configuration profiles
------------------------------------

Phase 9 introduces protected owner-managed profiles rather than accepting arbitrary
privileged targets from the model.

5.1 ``PrivilegedBrokerProfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* broker protocol/profile ID and version;
* exact broker service identity and Unix-socket path;
* expected broker UID/GID and application peer UID/GID;
* allowed privileged operation kinds;
* maximum message/frame sizes and timeouts;
* durable broker-evidence root identity;
* accepted process/service hardening digest;
* ticket verification key/reference or equivalent non-exportable verification material;
* candidate-Pi capability evidence digest.

5.2 ``BinnacleServiceProfile``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* exact development service unit name;
* exact source checkout root and expected registered workspace identity;
* exact service user/group;
* exact protected configuration paths/digests that determine runtime composition;
* readiness endpoint or equivalent bounded readiness probe contract;
* startup/restart timeout;
* allowed systemd operation vocabulary;
* expected service executable/entry point and environment identity source;
* checkpoint/LKG protected storage root;
* local recovery marker path and format version.

No request may supply an arbitrary systemd unit string that bypasses this profile.

5.3 ``PackageProfile``
~~~~~~~~~~~~~~~~~~~~~~

Package authority is narrower than arbitrary package-manager authority. The profile binds:

* supported package manager and exact executable identity;
* trusted configured repository/source identity/digest;
* allowed package names or package-name policy;
* whether exact version is mandatory;
* whether dependency installation is allowed and how the resulting transaction is
  bounded/recorded;
* prohibited package-manager options and environment variables;
* non-interactive mode and prompt behavior;
* package database lock/readiness behavior;
* download/network policy;
* maximum transaction duration/output;
* reboot-required evidence handling;
* package-manager evidence parser/profile version.

Bootstrap should strongly prefer exact package name plus exact candidate version when a
version can be resolved before effect. Repository/source addition, package removal,
``dist-upgrade``/full-upgrade, autoremove and arbitrary option pass-through are not part
of this profile.

6. Privileged ticket contract
-----------------------------

Every consequential broker request carries one application-issued privileged ticket.
The ticket must be opaque to the host-facing model except for bounded correlation facts.
The broker independently verifies a closed structure containing at least:

* ``operation_id``;
* controller ID/epoch digest;
* device ID/epoch;
* privileged operation contract + version;
* exact broker profile/version;
* exact semantic action;
* exact target profile/identity;
* canonical request fingerprint digest;
* maximum-effect digest;
* protected current-state binding digest;
* Phase 4 policy/admission evidence reference/digest;
* application runtime build/config/policy digests;
* issue time, expiry and trusted-time assumptions;
* single-use random nonce with at least 128 random bits;
* ticket ID and ticket digest/signature/MAC according to the reviewed profile.

Operation-specific tickets add exact fields.

A package-install ticket binds package manager, package name, resolved version,
repository/source profile digest and expected pre-install package state.

A service-restart ticket binds exact unit, expected pre-restart runtime/checkpoint state,
restart mode and allowed readiness deadline.

A controlled-self-restart ticket additionally binds candidate/LKG checkpoint identities,
expected candidate source revision, expected config/policy/environment digests, rollback
policy and recovery marker identity.

The broker stores only non-secret ticket/evidence facts needed for replay prevention and
reconciliation. A ticket is authority but not a reusable root credential; it expires and
is single-use for one semantic effect.

7. Broker process and UDS boundary
---------------------------------

The privileged broker runs as a separate root-owned systemd service. The preferred
Bootstrap composition is:

::

   unprivileged MCP/application
       -> restricted root-owned AF_UNIX socket
       -> privileged broker ticket validator
       -> closed typed privileged adapter
       -> package manager / systemd / checkpoint filesystem

The broker protocol is explicitly versioned, schema-defined and framed JSON. It must not
use pickle or arbitrary Python object deserialization.

Required transport controls include:

* socket directory not writable by the application or executor;
* narrow socket group/mode or socket-activation policy;
* Linux peer credentials verified against the exact application identity;
* no trust in forwarded caller metadata from JSON alone;
* fixed maximum frame size and bounded nesting/string/list lengths;
* exact protocol-version negotiation or fail-closed mismatch;
* request ID, operation ID, ticket ID/digest and response correlation;
* read/write/deadline ceilings;
* no file-descriptor passing in Bootstrap unless a later reviewed operation explicitly
  requires it;
* no arbitrary path/argv/environment fields outside closed operation schemas.

The broker rejects requests from the Phase 7 command UID, Git child UID, arbitrary local
users and unknown peer identities even if a valid-looking ticket is presented.

8. Broker durable evidence store
--------------------------------

The broker cannot rely exclusively on the application database because controlled
restart deliberately replaces that process. It therefore owns a small, separate,
root-protected durable evidence store. SQLite with ``synchronous=FULL`` is preferred for
structured broker state if candidate-Pi evidence supports it; small atomic/fsynced files
may be used for checkpoint payloads and recovery markers.

The broker store is not a second authoritative Binnacle operation database. It contains
only enough independent evidence for privileged replay prevention/recovery, including:

* broker schema/profile version;
* accepted ticket digest and single-use nonce;
* operation ID and semantic action;
* target identity;
* acceptance/dispatch/effect state;
* exact privileged effect reference;
* bounded result/evidence digests;
* checkpoint/restart attempt identity;
* candidate/LKG identities;
* restart/rollback/recovery state;
* readiness observations/provenance;
* terminal/uncertain outcome;
* retention timestamps.

A ticket replay with the same exact fingerprint returns retained evidence. Same ticket
with conflicting semantics fails closed. A new ticket cannot create a second effect for
an unresolved retained privileged action whose target/effect identity would overlap.

The broker store never contains raw SSH/GPG private keys, controller credentials or
model-visible secrets.

9. Broker acceptance and effect linearization
---------------------------------------------

The broker follows an accept-once discipline analogous to Phase 7 but specialized for
privileged effects.

For each ticket:

#. verify peer identity, protocol and ticket cryptography;
#. validate ticket syntax/expiry/device/profile/action/target;
#. atomically create/find the broker replay record;
#. resolve same-ticket retained state before mutable current-state checks;
#. revalidate broker-owned current-state predicates required by the ticket;
#. durably record accepted intent and exact maximum effect;
#. cross one operation-specific privileged effect boundary;
#. immediately durably record effect receipt/knowledge/reference before acknowledging the
   result;
#. complete operation-specific reconciliation and return bounded evidence.

The broker must not start an effect and then create its replay record afterwards.

The application still performs the governing Phase 4 OP-BOUNDARY before sending the
broker request. The broker performs an independent narrower root-boundary check so a stale
or compromised application message cannot broaden the ticket.

10. Read-only package inspection
--------------------------------

``package_inspect`` should query only the reviewed package manager/profile and return
bounded normalized facts such as:

* installed/not-installed;
* installed version;
* candidate version when deterministically available;
* package source/repository identity summary;
* package-manager lock/busy state;
* whether package metadata is stale/unknown;
* whether the requested exact install transaction can currently be resolved.

It must not expose arbitrary package-manager output, repository credentials, full source
lists, environment secrets or unbounded maintainer metadata.

Read-only inspection must not refresh package indexes, mutate caches or perform implicit
network writes. If candidate resolution requires an update operation, that is a separate
future semantic effect rather than hidden inside inspection.

11. Package installation
------------------------

``package_install`` exists only to unblock Binnacle development. It is not a general host
package-management API.

11.1 Admission
~~~~~~~~~~~~~~

The application binds:

* exact package profile;
* exact package name;
* exact target version where available/required;
* exact pre-install installed state/version;
* trusted repository/source digest;
* requested reason/objective digest;
* maximum allowed dependency transaction profile;
* timeout/output/resource ceilings.

The final Phase 4 OP-BOUNDARY revalidates controller/device/session/policy/audit/recovery,
package profile, target package/version and current package state. The broker independently
re-checks the package-manager/profile identity and exact precondition before effect.

11.2 Effect execution
~~~~~~~~~~~~~~~~~~~~~

The broker invokes one fixed package-manager adapter with a constructed argv/environment.
No caller-supplied option string or shell is accepted. The adapter uses non-interactive
mode and disables arbitrary hooks/options that can be disabled without violating the
platform package semantics.

A distro package install may execute package-provided maintainer scripts as root. That is
inherent broad effect and must be acknowledged explicitly. Phase 9 therefore requires a
trusted configured distro repository/profile and exact package/version binding; it must
not present package installation as equivalent to a simple file copy.

The broker records package-manager transaction identity/evidence where available,
pre/post package state, exit class and bounded output digest.

11.3 Effect truth and uncertainty
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Process exit alone is not always sufficient to prove package state. After the package
manager returns, the broker independently inspects installed package/version state and any
transaction database evidence supported by the selected platform.

* Exact requested version installed with coherent transaction evidence -> known effect.
* Exact proof no transaction/effect started -> known no effect where the contract permits.
* Partial dependency/package changes, killed package manager, lost effect receipt,
  package-database inconsistency or unverifiable maintainer-script outcome -> partial or
  uncertain, never blind retry.

Phase 4 retains the operation and blocks a new logically overlapping package install
until reconciliation is complete.

12. Service inspection
----------------------

``binnacle_service_inspect`` uses the exact fixed ``BinnacleServiceProfile`` and returns
bounded service facts:

* active/inactive/failed/activating/deactivating or normalized equivalent;
* main PID and start time when available;
* exact unit identity;
* bounded failure/result code;
* readiness state separately from systemd active state;
* runtime identity returned by the application when reachable;
* last controlled-restart attempt/checkpoint summary when authorized.

Systemd ``active`` is not equivalent to Binnacle readiness. Post-restart acceptance always
requires the declared readiness/runtime-identity contract.

13. Restart preflight
---------------------

``restart_preflight`` is read-only. It combines authoritative Phase 4 operation state with
Phase 7 executor state and the requested restart mode.

The response identifies, in bounded form:

* application-owned active/uncertain operations;
* independently supervised Phase 7 operations and whether they are expected to survive
  application restart;
* operations holding Phase 6 workspace fences;
* active Git/credential/privileged operations;
* current application revision/runtime identity;
* current checkpoint/LKG state;
* predicted impact of restarting only the application service;
* reasons restart is blocked, requires cleanup/cancel, or may proceed.

Restart preflight is awareness plus policy, not a global rule that all operations must be
finished. A Phase 7 execution that is explicitly designed to survive application restart
may continue. However, a pending Phase 8 credential child, unresolved Git effect,
privileged package transaction or unresolved audit/recovery state normally blocks
self-restart.

Preflight output never grants authority. The consequential restart operation performs a
fresh final revalidation.

14. Runtime identity contract
-----------------------------

The running application exposes a bounded runtime identity sufficient to verify exactly
what restarted. Include at least:

* Git revision/OID;
* current branch or detached-state marker;
* dirty-state classification and digest where relevant;
* source-workspace/root identity;
* Python executable/version;
* isolated environment/lock identity;
* application build/package identity;
* process start time and runtime instance ID;
* configuration digest;
* policy digest;
* promoted contract/schema/manifest digest;
* service profile/version;
* device ID/epoch;
* readiness generation.

Raw environment variables, credentials and protected configuration content are not
returned.

Runtime identity is evidence, not authority. A restarted process is accepted only when
its identity matches the exact checkpoint expectation and readiness predicates.

15. Checkpoint model for controlled self-restart
------------------------------------------------

The controlled restart path uses a broker-owned ``RestartCheckpoint`` created before the
application is stopped.

15.1 Checkpoint contents
~~~~~~~~~~~~~~~~~~~~~~~~

Bind at least:

* checkpoint ID/version;
* Phase 4 operation ID and privileged ticket digest;
* controller/device/profile digests;
* exact development service unit;
* candidate Git revision;
* candidate branch;
* candidate dirty-state expectation;
* candidate source-root/workspace identity;
* candidate environment/lock identity;
* candidate configuration/policy/manifest digests;
* last-known-good Git revision;
* LKG branch/detached expectation;
* LKG environment/config/policy/manifest digests;
* exact source checkout recovery strategy;
* pre-restart service/runtime identity;
* restart timeout and readiness contract;
* allowed rollback action;
* creation trusted time and expiry;
* checkpoint digest and broker evidence generation.

The candidate and LKG must be independently proven eligible before checkpoint creation.
The broker does not accept arbitrary filesystem paths or arbitrary revisions from a raw
request.

15.2 Last-known-good eligibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

LKG is not merely ``HEAD~1`` and not merely the last Git commit observed. It is a retained
protected checkpoint whose runtime previously reached the required readiness and whose
identity/config/environment evidence is complete enough for deterministic restoration.

A new candidate is never promoted to LKG merely because systemd reports ``active``. The
application must reconnect/be reachable and satisfy the post-restart verification
contract before candidate promotion.

15.3 Checkpoint durability
~~~~~~~~~~~~~~~~~~~~~~~~~~

The checkpoint lives outside the source checkout and outside replaceable application
state under root-protected broker/recovery storage. File and parent-directory durability
must be explicit for filesystem payloads; structured broker state is committed before the
service stop effect begins.

If checkpoint persistence cannot be completed and verified, controlled restart fails
before service stop.

16. Source revision handoff and rollback authority
--------------------------------------------------

The root broker should not become a generic Git client with credential authority. The
normal candidate revision is produced and pushed by Phase 8 before Phase 9 restart.
The development checkout is expected to already contain the exact candidate object and
be in the exact reviewed workspace state required by the restart contract.

Rollback needs authority independent of the failed candidate application. The preferred
Bootstrap model is a narrowly structured recovery adapter that can restore only the exact
retained LKG checkpoint for the registered Binnacle checkout.

The selected mechanism must be reviewed with real repository/worktree evidence. Examples
may include a protected recovery reference/worktree or an exact descriptor-rooted
checkout/ref transition, but the final implementation must not silently choose ``git
reset --hard`` against mutable state.

Required invariants are:

* rollback target is exactly the checkpoint LKG identity;
* no arbitrary revision/path is accepted from the caller;
* current source/worktree state is revalidated before rollback;
* rollback never overwrites unrecognized intervening state;
* any destructive replacement scope is explicitly bound and recorded;
* rollback completion is independently verified before service restart;
* ambiguous source restoration leaves a restricted/stopped recovery state rather than
  guessing.

Phase 9 plan acceptance does not choose the exact Pi-local Git/worktree recovery primitive
without implementation evidence. The recovery adapter seam is frozen; the concrete
mechanism is promotion-gated.

17. Controlled restart state machine
------------------------------------

Represent a restart attempt independently in the broker store with states such as:

::

   checkpoint_preparing
   checkpoint_ready
   stop_requested
   service_stopped
   candidate_start_requested
   candidate_start_observed
   candidate_verifying
   candidate_ready
   rollback_required
   rollback_restoring
   rollback_start_requested
   rollback_verifying
   rollback_ready
   restricted_recovery
   failed
   uncertain

The exact machine-readable contract may use different identifiers, but the semantics must
be one-way and restart-safe.

17.1 Before stop
~~~~~~~~~~~~~~~~

The application performs:

#. caller-binding-first retained lookup;
#. received audit;
#. policy;
#. exact restart preflight;
#. candidate/LKG eligibility checks;
#. post-policy reservation of one active restart slot;
#. authorised audit;
#. running/effect intent;
#. Phase 4 handoff/session/consequential gates;
#. final controller/device/session/service/checkpoint/outstanding-operation/audit/recovery
   OP-BOUNDARY;
#. durable audit obligation;
#. broker ticket dispatch.

The broker then verifies and fsyncs ``checkpoint_ready`` before issuing the stop/restart
systemd effect.

17.2 Stop and candidate start
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The broker controls the exact service lifecycle. It records effect receipts around each
systemd transition and independently observes the unit state. Application disappearance
is expected and must not be interpreted as broker failure.

The broker never waits for a response from the process it just stopped in order to decide
whether to continue recovery.

17.3 Candidate verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After systemd reports the service started, verify both service and application facts:

* exact endpoint/readiness reachable within deadline;
* exact runtime revision equals checkpoint candidate;
* branch/dirty state as expected;
* source-root/workspace identity matches;
* Python/environment identity matches;
* config/policy/manifest digests match;
* device/service profile matches;
* startup diagnostics do not report a fail-restricted state that violates the readiness
  contract.

An ``active`` service with wrong revision/config is a failed candidate, not success.

17.4 Candidate success
~~~~~~~~~~~~~~~~~~~~~~

Only after exact verification may the broker mark ``candidate_ready``. The replacement
application subsequently reconciles the retained Phase 4 operation with broker evidence,
closes required audit obligations and may promote the candidate checkpoint to the new LKG
under the reviewed contract.

Candidate promotion to LKG is itself durable protected control-plane state and must not
happen before verification/audit closure.

18. Failed-candidate rollback
-----------------------------

If the candidate does not reach readiness within the checkpoint deadline, reports the
wrong runtime identity, crashes repeatedly, or otherwise violates the checkpoint
verification contract, the broker enters ``rollback_required`` without waiting for model
reasoning.

Rollback is deterministic within the exact previously authorized checkpoint. It does not
ask the failed application to approve its own recovery.

The broker:

#. ensures the candidate service is stopped or reaches a state safe for restoration;
#. revalidates current source/control-plane state against the checkpoint and retained
   effect receipts;
#. performs only the exact LKG restoration action allowed by the checkpoint;
#. durably records restoration receipt/effect truth;
#. starts the exact service;
#. verifies LKG runtime identity/readiness;
#. records ``rollback_ready`` when proven.

The original Phase 4 restart operation does not become ``succeeded`` merely because
rollback succeeded. Its host-visible result must state that the requested candidate
failed and rollback restored LKG. The operational effect occurred and recovery succeeded;
that is distinct from candidate success.

19. Restricted local-recovery state
-----------------------------------

Rollback can fail or become unverifiable. Examples include corrupted source state,
missing LKG objects/environment, systemd failure, disk-full, package damage, power loss or
ambiguous restoration receipt.

In that case the broker must prefer a known restricted/stopped state over repeated
unbounded restart loops.

``restricted_recovery`` retains outside the failed application:

* restart/checkpoint ID;
* candidate and LKG identities;
* last proven source/service state;
* exact failed/uncertain action;
* bounded diagnostics/evidence references;
* safe local operator commands/instructions derived from reviewed static templates;
* broker/profile version;
* timestamps and evidence digest.

Recovery instructions are not arbitrary generated shell. They are bounded operator-facing
instructions for the fixed Binnacle installation. The broker must not repeatedly retry
rollback after entering restricted recovery unless a separately authorized recovery
operation and exact evidence justify it.

20. Application restart and broker reconciliation
-------------------------------------------------

On each application startup, before new consequential work is admitted, the composition
layer queries broker recovery evidence.

If an incomplete/recent controlled restart exists, the application reconciles:

* exact operation/checkpoint/ticket identity;
* broker restart state/evidence generation;
* actual runtime identity;
* Phase 4 operation/effect knowledge;
* outstanding audit obligations;
* Phase 6/7/8 fence/process/credential cleanup state.

The application cannot rewrite broker history. The broker cannot directly rewrite Phase 4
operation state. Reconciliation uses deterministic mappings and records application-side
transitions/audit from broker evidence.

If the broker is unavailable while a privileged operation may be incomplete, new
privileged/self-management work is fail-closed and the affected Phase 4 operation remains
uncertain/reconciling.

21. Restart preflight versus Phase 7 surviving work
---------------------------------------------------

Application restart does not necessarily terminate Phase 7 development processes. The
preflight contract must classify each outstanding operation by survival semantics.

A command may survive if:

* Phase 7 independently supervises it;
* its workspace/root/profile remains valid across application restart;
* it does not hold a credential/broker/control-plane resource that requires the
  application to remain alive;
* it is not executing against source/config state that the restart/rollback action will
  replace;
* its retained operation/fence state can be reconciled by the replacement application.

A command that may mutate the same source checkout while controlled restart may restore
candidate/LKG source state normally blocks restart unless it has been completed/cancelled
or the exact restart contract proves non-overlap. Bootstrap should choose the conservative
blocking rule for source-changing outstanding commands.

22. Simple service restart versus controlled self-restart
---------------------------------------------------------

The plan distinguishes two semantic effects.

``binnacle_service_restart`` is a fixed-unit service lifecycle action for cases where the
source/config candidate is not changing and rollback semantics are not required. It still
performs restart preflight and post-restart runtime verification.

``binnacle_restart`` is the full self-management checkpoint/candidate/LKG operation and is
used when testing a newly developed Binnacle candidate.

A caller cannot silently downgrade a candidate-changing restart into the simple service
restart path. The final current-state verifier compares source/runtime/config identities
and requires the controlled path when they differ from the running LKG baseline.

23. Systemd adapter
-------------------

Use systemd's native service manager rather than custom daemon supervision.

The adapter is closed over the exact Binnacle service profile. It may implement typed
operations such as:

* inspect exact unit properties needed by the contract;
* restart/start/stop exact registered unit;
* query result/main PID/start timestamps;
* await bounded state transitions.

It does not accept arbitrary ``systemctl`` arguments or unit names from the model.

The concrete implementation may use a mature systemd API/DBus binding or a fixed
``systemctl`` invocation behind the broker. The choice is evidence-dependent. If using a
CLI, argv and environment are fully constructed, stdout/stderr bounded, and shell use is
forbidden.

Do not expose the system bus to Phase 7 command children as a substitute for the broker.

24. Optional host reboot
------------------------

Reboot is not promoted by default. The Tool/contract remains absent unless real Bootstrap
implementation evidence shows a required development change cannot be validated without a
reboot.

If promoted later, reboot requires an even stronger persistent handoff because both
application and broker processes terminate.

A reboot ticket/checkpoint must survive boot under root-protected storage and bind:

* exact operation and reboot reason class;
* pre-reboot runtime/candidate/LKG identities;
* expected boot/device identity and boot transition;
* post-boot verification contract;
* expiry and one-shot consumed state;
* recovery instructions if post-boot verification fails.

The post-boot broker/application must distinguish a new boot from service restart using
trusted boot identity. Reboot response loss never permits an immediate blind second
reboot.

This document freezes the seam but does not claim reboot support or require a host-facing
reboot Tool for plan acceptance.

25. Effect knowledge by operation
---------------------------------

Privileged operations require effect-specific truth.

25.1 Package install
~~~~~~~~~~~~~~~~~~~~

Effect begins when the package manager transaction is accepted/started under the exact
broker replay record. Exact installed package state plus transaction evidence determines
terminal classification. Partial dependency/package change is not known-no-effect.

25.2 Service restart
~~~~~~~~~~~~~~~~~~~~

Effect begins when systemd accepts the exact restart/stop-start transition. Application
connection loss afterwards is expected. Success requires the exact post-restart runtime
identity/readiness, not merely systemd acceptance.

25.3 Controlled self-restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checkpoint creation is preparation, not the service effect. The service effect begins
when broker-owned lifecycle transition is accepted. Candidate failure followed by proven
LKG rollback is a completed recovery outcome with known privileged effects, not
known-no-effect and not candidate success.

25.4 Reboot
~~~~~~~~~~~

If ever promoted, effect begins when the operating system accepts the reboot transition.
Post-boot absence/presence is reconciled using boot identity; a lost request receipt does
not justify repeating reboot.

26. Idempotency and overlap rules
--------------------------------

Phase 4 caller idempotency remains authoritative to the application. The broker adds
privileged ticket single-use/replay protection as defense in depth and restart evidence.

Same-owner same-key same-fingerprint retry returns/reconciles retained Phase 4 work before
new mutable checks. The application reuses the original privileged ticket/evidence
identity as required by the retained operation; it does not manufacture a fresh ticket to
repeat an uncertain effect.

Overlap classes should include at least:

* one package-manager mutation at a time;
* one controlled service/self-restart slot at a time;
* no package mutation overlapping controlled self-restart;
* no new service restart while a restart/rollback attempt is unresolved;
* no source-changing Phase 7/8 work overlapping a controlled source rollback;
* reboot excludes every consequential operation not explicitly proven safe across boot.

Overlapping reservations are acquired after policy, represented phase-stably in final
verification and retained on uncertainty.

27. Audit semantics
-------------------

Required Phase 4 audit remains separate from broker evidence.

The application audit records the owner/controller operation semantics and lifecycle.
The broker evidence records root-bound acceptance/effect/recovery facts. Cross-references
use operation ID/ticket digest/checkpoint ID/evidence digest without copying secrets.

Required application audit events cover at least:

* received request;
* policy allow/deny;
* privileged ticket/profile/target digest;
* effect intent;
* broker acceptance/effect reference;
* package/service/restart outcome;
* candidate verification;
* rollback initiation/outcome;
* restricted-recovery transition;
* terminal/uncertain operation result.

Audit failure before the Phase 4 consequential start gate blocks new effect as usual.
After the broker effect has started, later audit failure cannot rewrite effect truth; the
operation remains effect-aware/fail-restricted until required audit/obligation closure can
be reconciled.

28. Credential and secret boundary
----------------------------------

The privileged broker is not a credential-disclosure service.

It never returns:

* root secrets;
* repository SSH private keys;
* signing private keys;
* controller tokens;
* package repository credentials;
* protected configuration content.

If the package manager needs protected repository authentication in a later profile, that
credential use must be non-exportable and bound to the exact package transaction through a
separate reviewed credential capability. Bootstrap should prefer trusted OS repositories
that do not require introducing this extra authority.

Diagnostics, broker DB rows, journald fields, exception strings and recovery markers must
be scanned/redacted so reusable authority material is not model-visible.

29. Filesystem and path safety
-----------------------------

All broker-writable paths are fixed by protected profiles:

* broker evidence root;
* checkpoint/recovery root;
* exact Binnacle development checkout/recovery target where the selected rollback adapter
  requires access;
* package-manager/systemd paths accessed indirectly through native tools.

No request supplies an arbitrary absolute root path. Direct broker filesystem adapters use
descriptor-relative containment, no symlink following where appropriate, exact ownership
and mount identity, restrictive creation modes, fsync/file+parent durability, and
no-overwrite/CAS publication semantics.

The broker must not follow a source-checkout symlink into arbitrary host state during
rollback/checkpoint work. Candidate-Pi tests include malicious path replacement/mount
insertion between application admission and broker final boundary.

30. Process/resource boundary
-----------------------------

Root child processes are more sensitive than Phase 7 development commands.

For package-manager/systemd helper processes:

* executable identity is fixed by profile;
* argv/environment are fully constructed;
* shell is forbidden;
* stdin is closed or fixed/non-interactive;
* inherited FDs are closed except exact broker-owned pipes;
* no application/executor credential-agent socket is inherited;
* stdout/stderr are bounded and stored as protected evidence, not authority;
* timeout/kill semantics preserve uncertainty if effect state cannot be independently
  reconciled;
* descendants remain broker-owned/supervised until effect receipt/cleanup is established.

Do not reuse the Phase 7 general command UID/process domain for root helpers.

31. Error and result vocabulary
-------------------------------

Exact host-facing schemas are promotion work, but the plan should support bounded classes
such as:

* ``privileged_profile_unavailable``;
* ``privileged_ticket_invalid``;
* ``privileged_ticket_expired``;
* ``privileged_ticket_replay_conflict``;
* ``privileged_target_mismatch``;
* ``broker_unavailable``;
* ``broker_evidence_unavailable``;
* ``package_state_stale``;
* ``package_transaction_busy``;
* ``package_profile_unsupported``;
* ``package_partial_or_uncertain``;
* ``service_profile_mismatch``;
* ``restart_preflight_blocked``;
* ``restart_checkpoint_failed``;
* ``restart_candidate_failed``;
* ``restart_rolled_back``;
* ``restart_rollback_failed``;
* ``restart_restricted_recovery``;
* ``runtime_identity_mismatch``;
* ``privileged_effect_uncertain``.

Errors do not expose raw broker stderr, package credentials, full environment, protected
config or arbitrary filesystem paths.

32. Ports and adapters
----------------------

Phase 9 should introduce small typed seams rather than a privileged framework.
Representative application-side ports may include:

.. code-block:: python

   class PrivilegedBrokerPort(Protocol):
       async def inspect_package(self, request: PackageInspectRequest) -> PackageInspectResult: ...
       async def install_package(self, ticket: PrivilegedTicket) -> BrokerEffectResult: ...
       async def inspect_service(self, request: ServiceInspectRequest) -> ServiceInspectResult: ...
       async def restart_service(self, ticket: PrivilegedTicket) -> BrokerEffectResult: ...
       async def controlled_restart(self, ticket: PrivilegedTicket) -> RestartDispatchResult: ...
       async def inspect_recovery(self) -> BrokerRecoverySnapshot: ...

   class RestartPreflightPort(Protocol):
       async def inspect(self, request: RestartPreflightRequest) -> RestartPreflightResult: ...

   class RuntimeIdentityPort(Protocol):
       async def current(self) -> RuntimeIdentity: ...

Broker-side ports may include:

.. code-block:: python

   class BrokerEvidenceStore(Protocol):
       def accept_once(self, ticket: VerifiedPrivilegedTicket) -> BrokerAcceptance: ...
       def record_effect_receipt(self, receipt: PrivilegedEffectReceipt) -> None: ...
       def create_restart_checkpoint(self, checkpoint: RestartCheckpoint) -> None: ...
       def advance_restart_state(self, transition: RestartTransition) -> None: ...
       def snapshot(self, operation_id: str) -> BrokerOperationSnapshot: ...

   class PackageManagerAdapter(Protocol):
       def inspect(self, target: PackageTarget) -> PackageState: ...
       def install(self, effect: PackageInstallEffect) -> PackageInstallReceipt: ...

   class ServiceManagerAdapter(Protocol):
       def inspect(self, profile: ServiceTarget) -> ServiceState: ...
       def restart(self, effect: ServiceRestartEffect) -> ServiceRestartReceipt: ...
       def stop(self, effect: ServiceStopEffect) -> ServiceStopReceipt: ...
       def start(self, effect: ServiceStartEffect) -> ServiceStartReceipt: ...

   class SelfRecoveryAdapter(Protocol):
       def verify_candidate(self, checkpoint: RestartCheckpoint) -> RuntimeVerification: ...
       def restore_lkg(self, checkpoint: RestartCheckpoint) -> RecoveryReceipt: ...

The exact types remain implementation work, but no port accepts arbitrary shell strings or
unbounded root paths.

33. Persistence and migration ownership
---------------------------------------

Application-side Phase 9 metadata extends the authoritative Phase 4 schema only where
necessary for privileged operation correlation, reservations and restart reconciliation.
Likely protected fields/tables include:

* privileged ticket digest/reference;
* broker evidence generation/reference;
* privileged operation target/profile digest;
* restart slot reservation;
* restart checkpoint reference/digest;
* observed candidate/rollback outcome;
* last supervisor/broker reconciliation time.

The broker evidence schema is a separate root-owned migration set and package/module. It
must not import application ORM models or share writable DB files.

Migrations are immutable once released and verified by CI. Broker startup verifies schema
version before accepting privileged work. Migration or integrity failure keeps the broker
read-only/unavailable for new effects rather than auto-repairing unknown state.

34. systemd/service installation changes
----------------------------------------

Phase 9 implementation will add the real broker service/socket assets only after their
profiles/contracts are reviewed.

Expected assets include an exact root broker service unit and protected runtime/state
directories. The broker unit should use systemd hardening appropriate to its required
root operations without pretending impossible restrictions are active.

Candidate controls to verify include narrow filesystem access, private temporary storage,
closed capabilities where root UID alone is sufficient, ``NoNewPrivileges`` where
compatible with the selected package/systemd mechanism, restrictive umask, explicit
``RuntimeDirectory``/``StateDirectory`` ownership, restart policy, journald identity and
socket permissions.

Do not claim a hardening directive is enforced until the exact candidate-Pi unit is
verified with systemd tooling and adversarial tests.

35. Security invariants
-----------------------

The implementation must mechanically/testably preserve at least these invariants.

#. The MCP/application process is never root.
#. Phase 7/8 child processes cannot connect to the root broker socket.
#. The broker exposes no generic root command, argv or arbitrary path operation.
#. Every consequential root effect has a Phase 4 operation identity before broker effect
   and a broker replay identity before root effect.
#. Broker ticket replay cannot create a second effect.
#. Same ticket with conflicting semantics never executes.
#. Package install is exact-target/profile bounded and acknowledges maintainer-script
   authority rather than disguising it.
#. Arbitrary systemd units cannot be named by a host request.
#. Checkpoint is durable outside the application before service stop.
#. LKG is previously verified runtime state, not a guessed Git ancestor.
#. Candidate success requires exact runtime identity and readiness.
#. Failed candidate never becomes successful merely because systemd is active.
#. Rollback is broker/recovery-owned and does not depend on failed candidate cooperation.
#. Unverifiable rollback enters restricted recovery instead of looping.
#. Empty/missing application response after restart is not proof of no privileged effect.
#. Active Phase 7/8 work is considered by restart preflight and source-changing overlap is
   conservative.
#. Required audit failure before start prevents effect; audit failure after start does not
   erase effect truth.
#. Reboot remains unavailable until separately evidenced/promoted.
#. No reusable secret is returned through result, log, evidence DB or recovery marker.

36. Holistic concurrency and crash model
----------------------------------------

Before review, Phase 9 implementation design must walk at least these interleavings:

* two package installs admitted concurrently;
* package install racing controlled restart;
* two self-restarts with different candidates;
* restart preflight clean, then a new source-changing Phase 7 command starts before final
  boundary;
* service profile/config changes after policy but before broker effect;
* application crashes after Phase 4 call-start but before broker acceptance;
* broker accepts ticket, application crashes before receipt;
* broker crashes after starting package manager/systemd but before receipt persistence;
* service stops and broker crashes before candidate start;
* candidate starts but application response is lost;
* candidate is active with wrong revision;
* candidate readiness times out and rollback begins;
* rollback source restoration succeeds but service start receipt is lost;
* rollback service becomes active with wrong LKG identity;
* disk fills while writing checkpoint/evidence;
* LKG checkpoint disappears/corrupts before stop;
* power loss during candidate or rollback transition;
* same-key retry after application reconnect;
* owner ends the development session after privileged effect has started;
* audit fails before root effect and after root effect;
* broker socket receives a request from Phase 7 child UID;
* malicious request attempts arbitrary unit/package/path/argv substitution.

The expected result for every case must be one of a truthful retained success/failure,
reconciled recovery state or ``uncertain``/restricted recovery. No case may infer success
from service/process absence/presence alone.

37. Tests
---------

37.1 Unit tests
~~~~~~~~~~~~~~~

Cover:

* ticket canonicalization/verification/expiry/single-use conflict;
* profile target binding;
* package target/version resolution model;
* service target fixed-unit rejection;
* restart checkpoint validation;
* LKG eligibility rules;
* restart state-machine transitions;
* runtime identity matching;
* effect/recovery result mapping;
* error redaction;
* reboot capability absent by default.

37.2 Property/state-machine tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use Hypothesis or equivalent for:

* broker accept/replay conflicts;
* overlapping privileged reservation classes;
* restart state machine including crashes between every durable transition;
* candidate/LKG mismatch permutations;
* same-key retry versus broker replay evidence;
* audit-before/after-effect distinctions;
* no transition from ambiguous rollback to success without independent evidence.

37.3 Linux integration tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On disposable test services/package fixtures, prove:

* socket peer-credential enforcement;
* Phase 7 child cannot connect to broker;
* frame/schema ceilings;
* broker DB/file ownership/durability;
* exact package-manager argv/environment construction;
* package lock/busy/error classification;
* exact fixed-unit systemd operation;
* runtime identity/readiness separate from unit active state;
* checkpoint fsync and parent durability;
* service stop/start with application absent;
* broker survives/reconciles application restart;
* source path symlink/mount replacement fails closed;
* output/log secret redaction.

37.4 Fault tests
~~~~~~~~~~~~~~~~

Inject process kill/power-like interruption at every consequential boundary:

* broker replay record before/after effect;
* package manager start/exit/post-inspection;
* checkpoint write/fsync;
* service stop acceptance;
* candidate start acceptance;
* candidate verification;
* rollback source restoration;
* rollback service start;
* restricted-recovery marker publication;
* application reconciliation/audit closure.

37.5 Real candidate-Pi evidence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before promotion, record on the actual 64-bit development Pi:

* selected package manager/version and exact safe invocation behavior;
* package database/transaction evidence available for reconciliation;
* systemd version and exact unit/socket/peer-credential behavior;
* broker service hardening actually enforced;
* filesystem durability/ownership/mount assumptions for broker/checkpoint storage;
* service stop/start/restart timing distribution sufficient to choose a bounded deadline;
* exact readiness/runtime-identity behavior;
* selected LKG restoration mechanism and adversarial stale-state behavior;
* application restart while Phase 7 process survives;
* failed candidate rollback result;
* restricted recovery when rollback is deliberately made unverifiable;
* whether any required Bootstrap operation genuinely requires host reboot.

Until that evidence exists, platform-specific fields remain unsupported/conditional.

38. Host-confirmation and owner authority
----------------------------------------

The owner-approved development session may authorize the normal same-objective
self-development workflow, but Phase 9 introduces privilege and therefore requires exact
review of host-confirmation classification before Tool promotion.

The plan must not assume ChatGPT can express a particular persistent privileged approval
UI. Local authority is authenticated controller + current policy + exact development
session + exact Phase 4 operation + exact privileged ticket/profile. Host metadata/model
prose never substitutes for local authority.

If the actual host cannot safely express the required privileged action semantics, the
corresponding Tool remains unpromoted even though this plan can merge provisionally.

39. Contract/schema/manifest promotion
--------------------------------------

Before any Phase 9 host-facing handler is exposed:

#. define versioned operation contracts;
#. define closed input/output schemas;
#. define information classes and exact error shapes;
#. define confirmation/authority classification;
#. add exact Bootstrap manifest entries;
#. bind handlers and contract versions;
#. validate manifest/schema/handler parity;
#. add positive/negative fixtures;
#. verify catalogue refresh behavior against the real host profile where required.

The current manifest is not modified merely by accepting this plan.

Broker IPC schemas are also versioned and validated, but they are internal contracts and
are not automatically MCP schemas.

40. Implementation order
------------------------

Implement in this order to minimize privileged rework.

#. Freeze/promote Phase 9 semantic operation contracts, schemas and host-authority
   classification where evidence permits.
#. Add protected broker/service/package profile models and validators.
#. Define privileged ticket canonicalization/verification and application issuer seam.
#. Define broker framed-JSON protocol and strict peer validation.
#. Add separate broker evidence package/schema/migrations and replay tests.
#. Implement read-only package/service inspection adapters first.
#. Implement package-install adapter/effect truth behind disabled composition.
#. Implement restart-preflight application service and overlap reservations.
#. Implement runtime identity contract/handler.
#. Implement broker checkpoint/restart state machine without exposing host Tool.
#. Implement exact systemd service adapter and application-restart reconciliation.
#. Implement candidate verification and LKG promotion rules.
#. Implement exact selected LKG recovery adapter and failed-candidate rollback.
#. Implement restricted-recovery marker/operator evidence path.
#. Compose controlled restart behind all promotion gates.
#. Add optional reboot seam only; promote implementation only if real evidence requires.
#. Run full Linux/fault/property/security suite.
#. Run candidate-Pi package/systemd/restart/rollback evidence campaign.
#. Only then expose/promote the host-facing privileged Tools allowed by reviewed evidence.

41. Holistic pre-review checklist
---------------------------------

Before requesting bot review for the planning PR, verify the full pipeline rather than
isolated operations:

``request/session/current state -> caller-binding-first retained lookup -> received audit
-> policy -> post-policy privileged/restart reservation -> authorised audit -> running /
effect intent -> Phase4 handoff/session/consequential gates -> final controller/device /
service/package/candidate/LKG/outstanding-work/audit/recovery OP-BOUNDARY -> audit
obligation -> exact single-use broker ticket -> broker replay record + independent root
boundary -> privileged effect -> immediate broker effect evidence -> package/service /
candidate/LKG reconciliation -> application audit/operation reconciliation -> credential /
process/reservation cleanup -> retained retry``.

Specifically verify:

* application, executor, Git children and root broker authority remain disjoint;
* no generic root shell/path/unit/package option surface exists;
* package maintainer-script breadth is acknowledged and trust-bound;
* restart checkpoint/LKG are durable outside the application before stop;
* candidate readiness is exact runtime identity, not systemd active;
* rollback does not depend on failed candidate application;
* rollback ambiguity produces restricted recovery, not loops/success;
* Phase 7 surviving operations and Phase 8 source/Git effects are included in preflight;
* source-changing overlap cannot race rollback;
* Phase 4 effect/audit/idempotency truth survives application replacement;
* broker replay truth survives response loss;
* every uncertain effect blocks blind repeat;
* no reusable credential appears in result/log/recovery evidence;
* reboot remains absent unless separately evidenced.

42. Plan acceptance
-------------------

This Phase 9 planning PR may merge when:

* it changes exactly this numbered Phase 9 document;
* the holistic invariant pass is complete;
* exact-head Contract Validation and Python CI are green;
* mandatory exact-head Codex substantive review is clean and actionable threads are
  resolved;
* Copilot has been attempted at most once for each exact head and is best-effort only;
* no sentence converts unknown Raspberry Pi/ChatGPT behavior into a support claim.

Plan acceptance creates no privileged runtime authority.

43. Implementation/promotion gate
---------------------------------

Runtime implementation/promotion remains blocked until at least:

* the real Phase 4 durable-kernel implementation exit is current;
* the real Phase 8 Git implementation exit is current;
* the real development-session/controller/host evidence required by predecessor phases is
  current;
* Phase 9 contracts/schemas/manifest/host-authority classification are reviewed;
* exact broker/service/package profiles are registered;
* root broker peer/ticket/replay isolation is verified on the candidate Pi;
* selected package-manager transaction semantics are verified;
* selected systemd service lifecycle/readiness behavior is verified;
* selected checkpoint/LKG restore mechanism is verified;
* failed-candidate rollback and restricted-recovery paths are proven on the candidate Pi;
* full fault/security/secret-redaction gates pass.

If the package manager, systemd profile, filesystem recovery mechanism or host authority
cannot be proven safely, the affected privileged operation remains unavailable. Do not
weaken the boundary to satisfy the roadmap.

44. Phase exit
--------------

The roadmap Phase 9 exit is real evidence, not document acceptance.

With real ChatGPT connected to the real development Pi, prove the following using exact
retained evidence:

#. inspect outstanding work and restart impact;
#. inspect the current Binnacle runtime identity;
#. request the controlled restart for an exact candidate revision;
#. observe the application connection disappear without losing broker/restart truth;
#. reconnect to the same endpoint;
#. verify the exact expected candidate revision/config/policy/environment is running and
   ready;
#. inspect bounded startup diagnostics;
#. independently verify no reusable credential/root authority was disclosed;
#. run a deliberately broken candidate case and prove either deterministic LKG rollback
   to a reachable exact runtime or a verified restricted/local-recovery state whose
   evidence survives outside the failed process.

Only then is Phase 9 complete. Missing real Pi/ChatGPT evidence does not block provisional
plan acceptance, but it does block this exit and Phase 10 real acceptance execution.
