Binnacle Phase 5 Detailed Implementation Plan
=============================================

:Phase: 5 -- Validate real ChatGPT write capability with a disposable probe
:Status: merged
:Planning status: provisional -- evidence-independent implementation design is frozen;
                  implementation/promotion remains gated by Phase 4 implementation exit
                  and real Phase 3 authentication/discovery/confirmation evidence
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 4 durable-operation-kernel plan; Phase 4 implementation exit
             before Phase 5 implementation/promotion; reviewed/current Phase 3 real-host
             evidence before live ``compatibility-write-probe`` exposure
:Primary objective: Prove exactly one bounded create/delete effect in a dedicated
                    disposable probe root through the real ChatGPT host without granting
                    authority over the Binnacle source workspace or other host state
:Implementation scope: the three already-reviewed ``compatibility-write-probe`` Tools,
                       one disposable local filesystem adapter, Phase 4 durable-operation
                       integration, preparation/current-state binding, independently
                       anchored path history, exact idempotency, evaluation/evidence
                       capture, and narrow deployment permissions only

Purpose
-------

Phase 5 is the first Binnacle phase whose intended live evaluation contains a real local
mutation. It answers one narrow empirical question before ordinary development-workspace
authority is granted: can the selected real ChatGPT product/account/workspace discover,
confirm where required, invoke, retry, reconnect to, and clean up one bounded disposable
write through Binnacle's durable consequential-operation kernel?

The phase does **not** make the Binnacle repository writable and does not add a general
filesystem API. The only effect-capable production adapter introduced here owns one
protected disposable probe root and implements exactly two logical effects:

* create one new regular file, at most 65536 decoded bytes, without overwrite; and
* establish absence of one exact live artifact previously created by the probe, deleting
  it only while retained identity/content/ownership/history facts still match.

``probe_workspace_prepare`` remains HC0/no-effect. Preparation binds exact future effect
inputs and exact current state; it is not owner authority and cannot cross the filesystem
effect boundary.

This document freezes evidence-independent implementation semantics only. It does not
claim that ChatGPT currently exposes these Tools, presents HC1 confirmation, grants write
entitlement, refreshes catalogue metadata in a particular way, retries in a particular
way, or reconnects in a particular way. Those remain real-host observations. The
``:Status: merged`` value is the terminal document status after this planning PR lands;
while the PR is open this document is proposed rather than authoritative.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-03-pi-chatgpt-validation.rst``;
#. merged ``docs/implementation/phase-04-durable-operation-kernel.rst``;
#. this detailed Phase 5 plan;
#. ``spec/mcp/bootstrap-tool-manifest.yaml``;
#. ``schemas/mcp/bootstrap-inputs.schema.json``;
#. ``schemas/mcp/bootstrap-outputs.schema.json``;
#. ``schemas/mcp/binnacle-common.schema.json``;
#. ``docs/mcp-interface.md`` and ``docs/mcp-schemas.md``;
#. ``docs/mcp-host-confirmation.md`` and
   ``spec/policy/host-confirmation-classes.yaml``;
#. ``docs/operation-idempotency.md`` and ``spec/operation/idempotency.yaml``;
#. ``spec/operation/lifecycle.yaml`` and operation fixtures;
#. ``docs/audit-evidence.md``, ``spec/audit/audit-policy.yaml``, and audit schemas/fixtures;
#. ``docs/security/controller-transport.md`` and the selected reviewed Phase 3 controller
   profile;
#. ``docs/mcp-evaluation.md``, ``spec/mcp/evaluation-profile.yaml``,
   ``spec/mcp/evaluation-cases.yaml``, and
   ``schemas/mcp/evaluation-manifest.schema.json``;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

Existing Tool names, schemas, descriptions, annotations, confirmation classes, and result
envelopes are frozen inputs. Phase 5 must not create alternate contracts because local
implementation details are inconvenient.

2. Three independent gates
---------------------------

2.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

The plan may merge when it specifies deterministic disposable-write semantics without
assuming host behavior, consumes the Phase 4 durable kernel rather than creating a second
operation system, preserves the reviewed MCP surface, keeps host/device choices explicitly
evidence-gated, passes repository validation, and has no unresolved actionable review
finding. Plan acceptance grants no runtime authority.

2.2 Implementation/promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not begin or promote the live Phase 5 capability until:

* Phase 4 implementation exit passes on the exact candidate build;
* real Phase 3 evidence is reviewed/current for the selected ChatGPT product, plan,
  workspace, connection/authentication profile, discovery behavior, and applicable
  host-confirmation capability;
* the selected controller profile maps to one concrete non-wildcard local write-probe
  capability;
* production composition can keep ``compatibility-write-probe`` invisible/disabled when
  any prerequisite is missing or stale; and
* the exact development Pi proves the probe-root filesystem primitives and systemd
  permissions required below.

Missing, expired, contradictory, or unavailable evidence fails closed. Planning text is
never substituted for an observation.

2.3 Phase exit gate
~~~~~~~~~~~~~~~~~~~

Phase 5 exit is empirical. Real ChatGPT must create and remove one exact disposable probe
artifact with one logical effect per admitted operation and no escape from the probe root.
Reviewed evidence must additionally cover preparation binding, applicable HC1 behavior,
idempotent retry/lost response, cleanup, reconnect behavior, and the frozen attempt-count
oracle. Phase 5 exit is only evidence that the selected profile may proceed to Phase 6
review; it does not itself grant source-workspace authority.

3. Exact reviewed MCP surface
-----------------------------

Phase 5 implements/exposes only the existing ``compatibility-write-probe`` additions:

``probe_workspace_prepare``
   Contract ``1.1``; HC0; no external/device effect. Prepares one ``write`` or ``cleanup``
   and returns the reviewed prepared-operation/nonce/expiry/path/input/effect fields.

``probe_workspace_write``
   Contract ``1.1``; HC1; creates one new file under the disposable probe root. It requires
   an exact unexpired preparation, execution nonce, caller idempotency key, exact relative
   path, ``overwrite=false``, and exactly one text/base64 content representation.

``probe_workspace_cleanup``
   Contract ``1.1``; HC1; establishes absence of one exact manifest-owned live probe
   artifact, deleting only while path/artifact/preparation/controller/content/history
   facts remain exact.

The five ``compatibility-core`` Tools remain as already declared. Phase 5 adds no other
Tool, Resource, Task, Prompt, operation-status surface, cancellation surface, or custom
host protocol.

4. Explicit non-goals and authority boundary
--------------------------------------------

Phase 5 does not implement or promote:

* write access to ``/srv/binnacle-dev/repo`` or any development workspace;
* arbitrary filesystem list/read/search/write/patch/move/delete;
* directory creation, recursive deletion, globbing, bulk cleanup, or overwrite;
* arbitrary path traversal or symlink following;
* command/process execution;
* Git operations;
* package/service/systemd mutation beyond deployment configuration needed to grant the
  already-dedicated service identity access to the probe root;
* privileged broker operations;
* credentials or external network effects;
* hardware effects;
* owner-authority inference from model text or preparation output;
* a new host-confirmation protocol;
* a new operation lifecycle, second idempotency store, or alternate audit subsystem;
* Phase 6 development-workspace design.

5. Runtime filesystem and protected configuration
--------------------------------------------------

The only writable effect root is:

::

   /var/lib/binnacle/
     probe-workspace/
       .staging/
       <probe artifact files only>

Requirements:

* root and ``.staging`` belong to the dedicated unprivileged ``binnacle`` service identity;
* mode is ``0700`` unless an equally narrow implementation-specific mode is required;
* the root is not a symlink, source checkout, bind to source, network filesystem,
  credential location, operation database, audit directory, or evaluation-evidence tree;
* staging/final directories share the same verified local filesystem;
* no-replace publication and directory-fsync semantics are verified before capability
  activation;
* setup/reconciliation never recursively deletes unknown content.

Under Phase 4 ``ProtectSystem=strict``, add only:

::

   ReadWritePaths=/var/lib/binnacle/probe-workspace

Typed protected settings are equivalent to:

.. code-block:: python

   class ProbeWorkspaceSettings(BaseModel):
       enabled: bool = False
       root: Path = Path("/var/lib/binnacle/probe-workspace")
       max_file_bytes: int = Field(default=65536, ge=1, le=65536)
       preparation_ttl_seconds: int = Field(default=300, ge=30, le=900)

``root`` and ``max_file_bytes`` are structural security settings; model-controlled input
cannot redirect/enlarge them. ``enabled`` defaults false and is insufficient by itself to
activate a HOST profile.

6. Expected implementation file set
-----------------------------------

The implementation is expected to modify ordinary Phase 4 composition/configuration,
MCP/application-boundary, deployment/setup/verification, evaluation, and operations docs,
and to add a small probe domain/port/application/Linux-adapter/reconciler set plus one
explicit Alembic revision after the Phase 4 kernel revision. Representative paths remain:

::

   src/binnacle/domain/probe_workspace.py
   src/binnacle/ports/probe_workspace.py
   src/binnacle/application/probe_workspace.py
   src/binnacle/adapters/probe_workspace/__init__.py
   src/binnacle/adapters/probe_workspace/linux.py
   src/binnacle/adapters/probe_workspace/reconcile.py
   migrations/versions/0002_write_probe_state.py

Runtime code never opportunistically creates schema. Phase 5 adds no broad filesystem
framework and no new general runtime framework.

7. Deterministic domain, path, and fingerprinting
-------------------------------------------------

Use small typed domain values for operation kind, path, write intent, cleanup intent,
artifact state, state binding, path ledger, and retained artifact. Raw execution
nonces/idempotency keys stop existing after the Phase 4 digest boundary.

Phase 5 deliberately narrows the schema-valid relative-path envelope to exactly one
filename component:

* no ``/`` or ``\\``;
* no absolute/drive prefix, ``.``/``..``, NUL, CR/LF, or colon;
* UTF-8 encoded name <= 255 bytes and input already NFC-normalized;
* names beginning ``.binnacle-`` and exact ``.staging`` are reserved;
* the final filename remains within the schema limit.

Nested paths are rejected by Phase 5 policy; they are not interpreted as permission to
create directories. One shared normalizer is used by preparation and execution.

Write effect fingerprinting binds Tool/contract/operation, normalized path, decoded
content SHA-256/byte count, ``overwrite=false``, target identity, maximum-effect digest,
prepared operation ID, and prepared input digest. Cleanup fingerprinting additionally
binds exact artifact ID and expected content digest. JCS + SHA-256 is used exactly as in
Phase 4. Raw content is not duplicated into SQLite/audit.

8. Persistence and independent path-history integrity
-----------------------------------------------------

Migration ``0002`` adds only Phase 5-specific facts. Generic lifecycle/idempotency remains
Phase 4-owned.

8.1 ``probe_operations``
~~~~~~~~~~~~~~~~~~~~~~~~

One row exists per mutating Phase 5 operation that passed policy admission:

* ``operation_id`` PK/FK to ``operations``;
* ``probe_operation`` enum ``write``/``cleanup``;
* ``prepared_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``caller_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``artifact_id`` NOT NULL, deferred FK to ``probe_artifacts.artifact_id``;
* ``relative_path``;
* expected content SHA-256 and optional expected byte count;
* ``prepared_state_binding_sha256``;
* ``created_at``.

The row is inserted only in the post-policy admission transaction. A denied/interrupted
pre-policy ``received`` operation has no ``probe_operations`` row and owns no path
reservation. Deferred FK use is allowed only to permit same-transaction creation of a
write's operation/artifact rows; after commit no admitted probe operation may reference a
missing artifact.

8.2 ``probe_artifacts``
~~~~~~~~~~~~~~~~~~~~~~~

Retain every historical probe generation:

* ``artifact_id`` PK;
* ``relative_path`` NOT NULL;
* ``path_generation`` integer >= 1;
* owner controller ID/epoch;
* content SHA-256 and byte count <= 65536;
* state ``reserved``/``created``/``removed``/``abandoned``/``uncertain``;
* ``create_operation_id`` UNIQUE FK to ``operations``;
* ``active_cleanup_operation_id`` nullable UNIQUE FK to ``operations``;
* ``removed_by_cleanup_operation_id`` nullable UNIQUE FK to ``operations``;
* created/updated/removed timestamps as applicable;
* nullable protected ``file_identity_digest`` after exact created-file verification.

Migration ``0002`` enforces ``UNIQUE(relative_path, path_generation)`` and state-aware live
path uniqueness equivalent to:

::

   CREATE UNIQUE INDEX uq_probe_artifacts_live_relative_path
       ON probe_artifacts(relative_path)
       WHERE state IN ('reserved', 'created', 'uncertain');

Terminal historical commitment fields become immutable after final ``removed`` or
durably-proven-no-effect ``abandoned`` terminalization. Runtime code never deletes a
terminal artifact row to make a later request succeed.

8.3 ``probe_path_ledger``
~~~~~~~~~~~~~~~~~~~~~~~~~

Artifact rows are not trusted as their own history-completeness/high-water source.
Migration ``0002`` therefore adds one independently protected row per normalized path:

* ``relative_path`` PK;
* ``generation_high_water`` integer >= 0, monotonic and never decremented;
* ``terminal_history_count`` integer >= 0;
* ``terminal_history_sha256`` NOT NULL;
* ``active_artifact_id`` nullable UNIQUE deferred FK to ``probe_artifacts.artifact_id``;
* ``active_generation`` nullable integer;
* ``active_create_operation_id`` nullable FK to ``operations``;
* ``ledger_version`` integer >= 1, monotonically increasing on every authorised ledger
  transition;
* ``updated_at``.

The ledger is integrity/security state, not a cache. It is never reconstructed or silently
rebased from surviving ``probe_artifacts`` rows after initial creation.

For a truly never-seen path, the only acceptable initial state is:

::

   generation_high_water = 0
   terminal_history_count = 0
   terminal_history_sha256 = SHA256(JCS([]))
   active_artifact_id = NULL
   active_generation = NULL
   active_create_operation_id = NULL

Preparation may create this empty metadata row in one race-safe SQLite transaction only
when both the ledger and every artifact/probe provenance row for the normalized path are
absent. If a ledger is missing while any retained provenance proves the path was seen,
that is integrity failure, not a new path. An existing ledger with missing history is
never reset to empty.

8.4 Canonical terminal history
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Canonical terminal history is strict ascending ``path_generation`` JCS over immutable
security/provenance fields including at least:

::

   relative_path
   path_generation
   artifact_id
   state
   create_operation_id
   owner_controller_id
   owner_controller_epoch
   content_sha256
   byte_count
   file_identity_digest
   active_cleanup_operation_id
   removed_by_cleanup_operation_id
   created_at
   removed_at

For a stable path with no active generation:

* generations 1..``generation_high_water`` exist exactly once;
* every row is stable ``removed`` or durably-proven-no-effect ``abandoned``;
* ``active_cleanup_operation_id`` is NULL in every terminal row;
* ``terminal_history_count == generation_high_water``;
* recomputed canonical count/digest exactly equals ledger count/digest.

For a path with active generation ``N``:

* ledger ``generation_high_water == N``;
* exact ledger ``active_*`` fields identify that generation/artifact/create operation;
* generations 1..``N-1`` exist exactly once and are stable terminal history;
* terminal count is ``N-1`` and its canonical digest exactly matches the ledger;
* generation ``N`` exists exactly once and is the exact active artifact.

Any missing maximum/lower generation, mutation/insertion/duplicate/reorder, orphaned
operation/artifact provenance, nonterminal prior row, ledger mismatch, or canonicalization
failure is an integrity failure. Damage is never absorbed into a new baseline.

8.5 Write reservation and terminalization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A write reservation is one atomic post-policy transition from prepared stable ledger
``L/N/C/H`` to exact-self active state:

::

   ledger_version: L -> L+1
   generation_high_water: N -> N+1
   terminal_history_count: C -> C
   terminal_history_sha256: H -> H
   active_*: NULL -> exact self artifact / generation N+1 / create operation

The same transaction inserts exactly one ``reserved`` artifact generation ``N+1`` and
satisfies deferred references. Generation allocation uses ledger high-water only; it never
uses ``max(surviving rows)+1``.

Only exact ``removed`` and durably-proven-no-effect ``abandoned`` generations may enter
stable terminal history. Before terminalization one transaction must:

#. recompute prior terminal history strictly below the active generation and require exact
   ledger count/digest;
#. require exact ledger high-water/version and active artifact/generation/create operation;
#. require exact operation effect-knowledge/audit/recovery predicates;
#. construct the final immutable terminal representation;
#. append it to canonical history and compute the next count/digest;
#. atomically update artifact terminal state/provenance and ledger terminal commitment,
   clear ledger ``active_*``, increment ``ledger_version``, and preserve monotonic
   high-water.

If prior integrity or required effect/audit/recovery facts cannot be proven, terminalization
fails closed and leaves active/conservative state. Normal runtime/restart never repairs a
ledger from damaged artifact rows. Any deliberate migration/manual integrity repair is a
separately reviewed procedure that invalidates outstanding preparations and records
bounded integrity evidence; it never occurs as ordinary request handling.

9. Preparation service
----------------------

``ProbeWorkspaceService.prepare`` is no-effect but durable security state.

9.1 Write preparation
~~~~~~~~~~~~~~~~~~~~~

For ``operation=write``:

#. authenticate the selected Phase 3 controller/profile;
#. validate schema/path/byte bounds and protected probe-root identity;
#. prove target absent and no live-path artifact row;
#. load the ledger, creating only the deterministic empty anchor for a truly never-seen
   path;
#. require no ledger active generation;
#. load complete terminal history, prove contiguous generations 1..``N``, recompute
   ``C/H``, and require exact ledger ``L/N/C/H``;
#. bind root identity, target-absence, controller facts, ledger identity/version,
   ``N/C/H``, and exact
   ``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``;
#. generate reviewed execution nonce and separate prepared operation ID;
#. compute exact input/effect fingerprint and register through Phase 4 prepared-execution
   nonce storage with owner/device/Tool/contract/expiry/current-state digest/boot/trusted
   time facts;
#. append/fsync only schema-valid bounded preparation evidence;
#. return the existing output schema without claiming policy allow, confirmation,
   reservation, or filesystem effect.

Execute pre-policy validation and post-policy pre-reservation admission recompute this
exact pre-reservation state. Changed ledger/history/target/root/controller/prepared binding
is stale/mismatch and cannot be absorbed.

9.2 Cleanup preparation
~~~~~~~~~~~~~~~~~~~~~~~

A **new** cleanup preparation is valid only for the exact current active artifact retained
as ``created``. An already terminal ``removed``/``abandoned`` generation is not a valid new
cleanup-preparation target. Idempotent repetition of a prior cleanup uses that operation's
same caller key/retained result; it does not manufacture a second authorised cleanup for
an already-terminal generation.

Cleanup preparation must:

#. authenticate controller/profile and validate exact artifact/path/content facts;
#. load the path ledger and require exact active artifact/generation/create-operation
   ownership for this ``created`` artifact;
#. recompute the complete contiguous terminal history strictly below this active generation
   and require exact ledger count/digest, high-water, and version;
#. require ``active_cleanup_operation_id`` NULL;
#. bind exact ledger ``L/N/C/H`` plus active artifact/create ownership, root/controller/path/
   content facts, exact prepared binding, and one target variant below.

Allowed target variants are:

* **present** -- secure lookup proves exact retained regular-file identity/content and the
  binding includes
  ``cleanup_target_transition=exact_prepared_identity_or_absent_no_start``;
* **created target observed absent** -- secure lookup proves exact absence and the binding
  includes typed ``created_target_observed_absent`` without inventing a nonexistent file
  identity or effect knowledge.

For both variants the canonical binding contains
``cleanup_claim_transition=unclaimed_then_exact_self`` instead of a raw claim literal.
Before admission that token is valid only while the raw claim is NULL. Post-policy
admission may perform one exact NULL -> self CAS. Final verification may canonicalize back
to the same token only after proving the raw claim equals the exact running operation and
its immutable ``probe_operations.prepared_binding_id`` equals the consumed prepared
binding.

For a present-bound cleanup, disappearance before admission is stale/rejected. At final
pre-start verification only, secure absence may reproduce the prepared target token when
**all** ledger/history/artifact/controller/root/path/self-claim/prepared-binding facts remain
exact. That path returns typed ``already_missing_pre_start`` and never authorizes a
filesystem effect.

Preparation-time or final secure absence is observation only. It never proves who removed
a file, never produces ``known_effect``, never sets remover provenance, and never mutates
artifact/ledger state by itself.

10. Dual execution identity and minimal pre-policy durability
------------------------------------------------------------

Execute schemas require both ``execution_nonce`` and ``idempotency_key``. One internal
transaction binds them to one Phase 4 operation:

#. digest raw identities and discard raw material;
#. load prepared and caller-key bindings with Phase 4 owner/tombstone rules;
#. require exact unexpired preparation/owner/device/Tool/contract/input/fingerprint/current
   state;
#. if caller binding exists, require same owner/fingerprint and same attached operation;
#. if prepared binding is already attached, only the same admitted caller key may obtain
   retained work; a fresh key conflicts;
#. otherwise atomically create only the minimal version-1 ``received`` operation, caller
   binding, and prepared-binding attachment;
#. commit.

This transaction does **not** insert ``probe_operations``, create an artifact, advance a
ledger, reserve a path, or claim cleanup. Policy deny, received-audit failure, or crash
before policy therefore cannot strand probe authority.

11. Policy, mandatory audit gates, and post-policy admission
------------------------------------------------------------

Phase 5 adds only two local consequential intents:

* ``probe_workspace_write@1.1`` -- one absent-file create under the probe root;
* ``probe_workspace_cleanup@1.1`` -- establish absence of one exact live retained artifact.

External auth claim names remain evidence-selected. They map to one internal capability
such as ``probe_workspace_mutate``; no wildcard filesystem grant exists.

Phase 4 ordering remains exact:

#. after minimal durable ``received``, append/fsync schema-valid
   ``operation.state_changed(null -> received)`` before policy;
#. evaluate and durably retain one policy decision;
#. deny -> ``received -> rejected`` with required deny/rejected audit, no probe row, no
   ledger/reservation/claim transition;
#. allow -> one short transaction revalidates exact prepared state, persists allow,
   inserts immutable ``probe_operations``, acquires the exact operation-specific
   reservation/claim, and commits ``received -> authorised``;
#. append/fsync required ``policy.decision(allowed)`` + ``operation.authorised`` evidence;
#. only then may ``authorised -> running`` occur.

Required audit failure suppresses filesystem start and follows Phase 4 fail-restricted
recovery. An authorised reservation/claim after an allow-audit failure remains conservative
recovery state; it is never freed by fabricating a terminal outcome.

For an allowed write, admission proves exact prepared stable ``L/N/C/H`` plus absence/no
live row, then atomically performs section 8.5 reservation and inserts only exact self
``reserved`` generation ``N+1``. Changed/missing ledger/history or pre-existing live state
rejects with no effect; there is no surviving-row ``max()+1`` fallback.

For an allowed cleanup, admission is possible only for the exact prepared still-``created``
active artifact. It revalidates the complete ledger/history snapshot and exact prepared
filesystem observation, recomputes the pre-claim prepared digest while claim is NULL, then
atomically inserts ``probe_operations``, CASes
``active_cleanup_operation_id: NULL -> current operation``, and commits
``received -> authorised``. It does not change artifact or ledger terminal state.

A new cleanup against an already durably ``removed``/``abandoned`` artifact is rejected
**before post-policy admission/authorisation** as a stale/non-live preparation target. It
never creates an authorised mutating cleanup without a claim and never needs a special
final-boundary exception. Same-key retry of the actual prior cleanup returns retained
result/effect knowledge through Phase 4 idempotency.

12. Final all-mode OP-BOUNDARY verifier
--------------------------------------

Every consequential operation uses Phase 4's per-operation handoff gate, global
consequential gate, and all-mode final current-state verifier before audit-obligation
publication or ``EffectBoundary.start``. Failure/unavailability is fail closed.

12.1 Write final verifier
~~~~~~~~~~~~~~~~~~~~~~~~~

Immediately before any write start, prove:

* exact running operation/state version and exact consumed prepared binding;
* exact self ``reserved`` artifact at generation ``N+1`` with matching path/content/owner/
  controller/root facts;
* target remains securely absent;
* ledger is exact reservation state derived from preparation:
  ``ledger_version=L+1``, high-water ``N+1``, terminal ``C/H`` unchanged, and exact
  ``active_*`` ownership of this artifact/generation/create operation;
* complete retained history excluding only the self reservation is still contiguous
  terminal generations 1..``N`` and recomputes to exact prepared ``C/H``;
* all operation/artifact/ledger referential-integrity checks pass.

Only then may the callback canonicalize exact current state back to the prepared
write-reservation transition token. Any changed/deleted/inserted history, changed ledger,
generation reuse, foreign/missing reservation, binding mismatch, target appearance,
root/controller change, or unverifiable fact produces prepared-state mismatch/no start.

12.2 Cleanup final verifier -- mandatory ledger/history gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Every cleanup path capable of reaching ``EffectBoundary.start`` must pass this verifier
immediately before start.** Admission-time checks are not sufficient.

For the exact active cleanup artifact generation ``N``, the verifier must:

#. re-read the independently durable path ledger;
#. require exact prepared ledger identity/version ``L``, monotonic high-water ``N``, and
   exact ``active_artifact_id``/``active_generation``/``active_create_operation_id``;
#. load every terminal generation 1..``N-1`` and prove exact contiguity/stable terminal
   state/referential integrity;
#. recompute terminal history count/digest and require exact equality to both the durable
   ledger and the ``C/H`` carried by the consumed prepared binding;
#. require exact retained active artifact state ``created``, generation/owner/controller/
   root/path/content/create-operation facts;
#. require raw ``active_cleanup_operation_id`` equals this exact running operation;
#. require immutable ``probe_operations.prepared_binding_id`` equals the exact consumed
   prepared binding;
#. require exact target variant below.

The cleanup-claim NULL -> self transition may be phase-stably canonicalized only **after**
these checks. A deleted/mutated/inserted older terminal row, removed/corrupt ledger,
changed ledger version/high-water/active owner, orphaned provenance, foreign/cleared claim,
changed artifact/controller/root/path/content, or binding mismatch fails closed **before**
audit-obligation publication, ``EffectBoundary.start``, or unlink.

For a present-bound preparation:

* exact same file identity/content may proceed toward the effect boundary;
* secure absence may reproduce the prepared target token only after all ledger/history and
  self-claim/binding checks above pass, returning ``already_missing_pre_start``;
* replacement/mismatch/unverifiable absence fails closed.

For a preparation made while the still-created target was already securely absent,
continued secure absence is required after the same complete ledger/history checks;
reappearance fails closed.

``already_missing_pre_start`` returns before audit-obligation publication and before
``EffectBoundary.start``. The admitted operation is durably classified
``known_no_effect`` and follows frozen lifecycle ``running -> failed`` with bounded reason
such as ``cleanup_already_missing_before_start``. The existing cleanup Tool result may
truthfully return ``removed=false, already_missing=true``. No remover/effect provenance is
invented.

There is deliberately **no final cleanup verifier for an already-terminal artifact**,
because section 9.2 refuses new preparation and section 11 refuses post-policy admission
for that state. This removes the previous authorised-without-claim ambiguity.

13. Phase 4 audit-obligation and effect ordering
------------------------------------------------

After ``authorised -> running``, Phase 5 preserves Phase 4 exactly:

::

   running
     -> fsynced effect.intent_recorded
     -> per-operation DispatchHandoffGate
     -> global ConsequentialBoundaryGate PRE_START permit
     -> final Phase 5 all-mode OP-BOUNDARY verifier
     -> if exact already_missing_pre_start: no start; known_no_effect closure
     -> otherwise durable audit-obligation marker
     -> gate-owned call_start
     -> bounded effect/no-effect receipt/uncertainty
     -> immediate durable receipt/reference/effect-knowledge classification
     -> required post-effect/no-effect audit fsync
     -> exact obligation-marker closure when Phase 4 permits
     -> terminal/reconciliation closure

Failure of required intent audit trips the global gate before effect. A surviving
obligation marker remains explicit-recovery-required across restart. Phase 5 never skips
an audit stage because the effect is small or local.

14. Atomic write effect
-----------------------

``LinuxProbeWorkspace.start_write`` performs bounded publication only after final boundary
success:

#. open protected root and ``.staging`` by directory fds with no-follow defenses;
#. create unique private staging file ``O_CREAT|O_EXCL`` mode ``0600``;
#. write exact prevalidated bytes;
#. fsync staging file and verify byte count/digest;
#. publish to final name using same-filesystem no-replace semantics, preferably hard-link
   publication; never fall back to overwrite-capable rename;
#. fsync probe-root directory -- the durable create-effect point;
#. unlink private staging name and fsync staging directory;
#. return stable opaque artifact/effect reference.

Unavailable safe no-replace or directory-fsync semantics keep capability disabled. Crash
after publish/root-fsync is reconciled from exact retained reservation/file facts.

15. Exact cleanup effect
------------------------

``LinuxProbeWorkspace.start_cleanup`` is callable only after section 12.2 succeeds. It
accepts the exact claimed active ``created`` artifact and performs a second adapter-local
identity/type/content check using protected root directory fds. It then unlinks exact name,
fsyncs the root directory, and returns a stable effect reference.

If target becomes absent after ``call_start`` linearization but before unlink, the adapter
performs no unlink and may return an explicit no-effect receipt correlated to exact
operation/artifact/path generation. Only a durably retained/classified receipt proves no
unlink was attempted. Receipt loss leaves post-dispatch absence ``uncertain``; absence
alone cannot reconstruct either no-effect or known-effect.

Mismatched/symlink/directory/unowned content is never deleted automatically.

16. Reconciliation and ledger-safe closure
------------------------------------------

Reconciliation reconstructs references from durable operation/probe/artifact/ledger facts;
it never reconstructs effect knowledge merely from final filesystem observation.

16.1 Write reconciliation
~~~~~~~~~~~~~~~~~~~~~~~~~

* exact final file present matching exact active ledger/artifact reservation -> durable
  created effect may be classified/converged according to Phase 4;
* unpublished staging only with final absent -> clean private staging safely and converge
  truthful no-effect failure;
* final absent with durable proof no publication occurred -> no create effect;
* mismatched/insufficient state -> ``uncertain``/fail restricted.

A reserved write durably proven ``known_no_effect`` may become ``abandoned`` only through
section 8.5 terminalization after required audit/recovery closure. A successfully created
artifact remains the ledger's active generation while ``created``; it enters terminal
history only after exact cleanup closure.

16.2 Cleanup closure
~~~~~~~~~~~~~~~~~~~~

Keep these cases separate:

* **pre-start/explicit durable no-effect absence:** after terminal ``known_no_effect`` and
  required audit/recovery closure, one transaction first re-proves complete ledger/history
  integrity, exact active artifact/generation/create operation, exact cleanup claim, exact
  no-effect reason/receipt, and secure continued absence. It then terminalizes the artifact
  to ``removed`` through section 8.5, clears cleanup claim and ledger ``active_*``, and
  leaves ``removed_by_cleanup_operation_id`` NULL. ``removed`` means durable current
  absence, not that this cleanup removed it;
* **successful removal:** only exact durable ``known_effect`` plus matching recoverable
  effect reference and completed post-effect audit/obligation/recovery closure may record
  ``removed_by_cleanup_operation_id=current operation`` and terminalize through the same
  ledger-checked transaction;
* **post-dispatch absence without proof:** lost unlink/start receipt, uncertain effect
  knowledge, or incomplete audit/obligation/recovery closure -> no terminalization, no
  history commitment change, no claim/active-owner release;
* **known no-effect while exact artifact remains present:** after terminal audit/recovery
  closure and complete ledger/history integrity verification, clear only the exact cleanup
  claim by CAS; artifact remains ``created`` and ledger remains active;
* **mismatch/identity ambiguity:** retain claim/ledger active ownership and fail restricted.

No closure transaction repairs a damaged ledger/history baseline.

16.3 Restart integrity
~~~~~~~~~~~~~~~~~~~~~~

Fresh-process startup verifies ledger/artifact/probe-operation referential integrity before
write-probe activation. A path whose ledger/rows disagree cannot prepare, admit, or start
another effect. Restart never creates a missing ledger from surviving rows and never
decrements generation high-water.

17. Audit mapping and diagnostics
---------------------------------

Use only existing schema-valid payload kinds. Preparation records bounded digest/code facts
only: root/target state, path-ledger version/high-water/count/digest, active artifact facts,
content/maximum-effect digests, and reviewed transition identifiers. It never emits raw
history rows, raw nonce/key, filesystem content, credentials, owner-confirmation claims, or
fictional effect provenance.

Execution preserves Phase 4 lifecycle/effect audit ordering exactly.
``already_missing_pre_start`` never emits ``effect.started`` and never claims
``known_effect``. Ledger reservation/terminalization uses bounded correlation/digest facts
inside existing schema-compatible audit payloads; Phase 5 adds no new audit subsystem or
unreviewed payload kind.

Diagnostics may expose safe operation/artifact IDs, path generation, ledger version,
history count/digest prefix, effect knowledge, state version, and bounded result codes.
Never log raw history rows/content/keys/nonces/credentials/controller assertions.

18. MCP handler and retry behavior
----------------------------------

MCP adapters remain thin: schema validate, obtain authenticated controller context, call
application service/Phase 4 coordinator, and return the existing envelope plus canonical
retained operation metadata. Same-key retry returns retained state/result rather than
executing again.

Retry rules:

* same key/same input -> retained operation/result;
* same key/different input -> conflict;
* consumed preparation/new caller key -> conflict;
* expired preparation before admission -> deliberate new preparation only after proving no
  earlier operation was admitted;
* ``uncertain`` -> reconciliation/status semantics only, never automatic fresh effect;
* cleanup of an already terminal artifact is not a new preparation/admission path; retry
  the actual prior cleanup with its original logical identity to obtain retained result;
* terminal known-no-effect cleanup does not silently reacquire a released claim; a later
  independent cleanup is possible only if the exact artifact remains live ``created`` and
  receives new preparation/key/policy admission.

19. Catalogue activation and real-host branch
---------------------------------------------

Runtime catalogue remains filter-only from the reviewed manifest. Write-probe Tools are
visible only for selected ``compatibility-write-probe`` phase when local promotion
prerequisites pass.

Catalogue refresh/reconnect, write entitlement, HC1 presentation/non-bypassability, and
host concurrency behavior remain observed HOST-profile facts. Use exactly the reviewed
Phase 3 refresh/reconnect procedure if known; otherwise record blocked/unknown and do not
mutate Tool metadata or weaken local policy.

20. Evaluation procedure and evidence
-------------------------------------

When implementation/promotion prerequisites pass, use a sanitized frozen evaluation
bundle:

#. record exact build/config/manifest/schema/policy/profile digests and required Pi identity
   evidence;
#. verify ``compatibility-core`` and authentication have not regressed;
#. activate/refresh reviewed write-probe catalogue through the observed host procedure;
#. verify visible Tools exactly match manifest;
#. prepare the frozen synthetic path/content and capture sanitized preparation facts;
#. exercise required decline attempts and prove no execute/effect;
#. approved execute must reach exact normalized request and produce exactly one artifact;
#. exercise lost response/same-key retry and prove one operation/one effect;
#. reconnect and prove exact retry returns retained work without duplicate effect;
#. prepare/execute exact cleanup and prove only exact artifact reaches absent state;
#. verify retained history + independent ledger remain coherent and high-water monotonic;
#. repeat exact frozen risk-class attempt counts, retaining blocked/failed/unstable results;
#. validate/freeze manifest, reviewer decision, evidence archive, and detached receipt;
#. only then update ``docs/mcp-profile.md`` with observations actually proven.

No live evaluation writes the Binnacle repository, ``/etc``, credentials, service units,
audit files, or other paths. CI mocks do not establish real Pi/real ChatGPT support.

21. Unit and property tests
---------------------------

Coverage includes at least:

* path normalization, byte/maximum-effect bounds, deterministic text/base64 fingerprints;
* race-safe empty-ledger creation only for truly never-seen paths;
* missing ledger for a seen path fails closed;
* preparation recomputes complete contiguous terminal history and requires exact independent
  ledger count/digest/version/high-water;
* deleting the maximum historical row before preparation cannot lower high-water or permit
  generation reuse;
* deleting/mutating/inserting a lower historical row before preparation cannot become a
  new trusted baseline;
* duplicate/reordered/canonical-corrupt/nonterminal prior history fails closed;
* write reservation allocates strictly ledger ``N -> N+1`` and exact self
  ``L -> L+1`` active ownership;
* final write canonicalization accepts only exact self reservation plus unchanged complete
  prior history;
* new cleanup preparation rejects terminal ``removed``/``abandoned`` artifacts before an
  authorised mutating operation can exist;
* same-key retry of the prior successful/no-effect cleanup returns retained outcome without
  another claim/effect;
* cleanup preparation binds exact ledger ``L/N/C/H`` and active ownership;
* cleanup claim canonicalization accepts only NULL -> exact consuming operation with exact
  prepared binding;
* **after cleanup admission but before final boundary, deleting/mutating an older terminal
  generation changes integrity and yields zero ``EffectBoundary.start`` and zero unlink**;
* **after cleanup admission but before final boundary, removing/corrupting ledger or changing
  ledger version/high-water/active ownership yields zero start and zero unlink**;
* final cleanup verifier recomputes history strictly below active generation and compares
  exact ledger + prepared ``C/H`` before every start-capable path;
* present-bound disappearance before admission is stale; exact disappearance after
  admission can reach only ``already_missing_pre_start`` after full ledger/history checks;
* observed-absent preparation remains effect-neutral; reappearance fails closed;
* replacement/mismatch/foreign or cleared claim fails closed;
* mandatory received audit precedes policy;
* policy deny/pre-policy crash creates no probe reservation/ledger advance;
* allowed/authorised audit precedes ``running``;
* same nonce/key races converge on one operation/effect;
* lost receipts never infer effect/no-effect from final absence;
* known-no-effect and known-effect cleanup closure obey exact audit/recovery/ledger
  predicates;
* uncertain cleanup retains active ownership + claim;
* no mismatch is deleted automatically;
* maximum effect remains one bounded artifact.

Property state machines combine preparation expiry, controller replacement, idempotency
collisions, ledger versions/high-water/history digests, artifact generations/states,
cleanup claims, policy/audit failures, and restart/reconciliation.

22. Required integration and fault tests
----------------------------------------

Required faults include:

* crash after prepared-binding registration;
* concurrent first execute same nonce/key and different caller keys;
* crash after minimal ``received`` before received audit/policy -> no reservation;
* received-audit failure -> no policy/reservation/effect;
* policy deny -> no reservation/ledger advance;
* concurrent allowed writes same path -> exactly one ledger/self reservation wins;
* crash after ledger/artifact reservation before ``running``;
* allowed/authorised audit failure -> no ``running``/filesystem start;
* crash after running/intent audit before final verifier;
* delete maximum terminal artifact before preparation -> ledger mismatch, zero start,
  high-water not decremented;
* delete/mutate lower terminal artifact before preparation -> ledger mismatch, zero start,
  no new baseline;
* delete/mutate/insert history after write preparation -> admission/final mismatch;
* corrupt/remove ledger while artifact/provenance rows exist -> integrity failure;
* restart with ledger/artifact mismatch -> write probe unavailable/fail restricted;
* attempted generation reuse after deleting maximum row -> impossible;
* rebind/delete/change exact self write reservation -> final mismatch;
* target appears after write preparation/before final boundary -> no start;
* staging/fsync/publish/root-fsync/receipt DB failures;
* crash after publish/root-fsync before receipt;
* exact cleanup self claim change -> final mismatch;
* **delete/mutate older terminal history after cleanup admission but before final verifier ->
  zero effect-boundary start and zero unlink**;
* **corrupt/remove/change ledger after cleanup admission but before final verifier -> zero
  effect-boundary start and zero unlink**;
* cleanup present target disappears after admission/before final boundary -> no start,
  truthful ``known_no_effect`` only after full integrity verification;
* cleanup replacement/identity mismatch -> no delete;
* new cleanup preparation against already terminal artifact -> rejected/non-live before
  authorisation; no cleanup claim and no effect-boundary path;
* audit-obligation publication/final audit failures;
* target absent before cleanup preparation while artifact remains ``created`` ->
  observed-absent preparation, exact claim, no-start known-no-effect closure only after
  full ledger/history verification and required audit/recovery closure;
* target absent after ``call_start`` but before unlink with durable explicit no-effect
  receipt -> no unlink and exact no-effect closure;
* same race with receipt loss -> uncertain, claim/ledger active retained;
* crash after unlink/root-fsync before receipt -> uncertain until explicit recovery proves
  effect; absence alone cannot close ledger;
* crash during ledger terminalization -> atomic old or new state only;
* DB failure during cleanup claim/ledger closure -> conservative active state;
* response loss/restart/same-key retry;
* controller replacement replay;
* probe-root capability/permission failure.

Every fault asserts zero effect or exactly one logical effect as appropriate. No test
"repairs" uncertainty by issuing a fresh effect.

23. Fresh-process restart invariants
------------------------------------

A fresh process reconstructs all decisions from durable state. Verify:

* prepared nonce/expiry/current-state binding remains enforceable;
* ledger versions/high-water/terminal count/digest survive restart and are compared against
  complete retained history before preparation/admission/**every final effect boundary**;
* missing/corrupt ledger or missing/mutated history never gets auto-rebuilt;
* admitted write reconstructs exact self ledger/reservation transition without in-memory
  exceptions;
* foreign/missing/changed self reservation or prepared binding fails closed;
* cleanup present/observed-absent transitions and exact self claim reconstruct from durable
  facts only;
* cleanup final verifier re-proves independent ledger/history integrity after restart and
  immediately before any possible unlink;
* a terminal artifact cannot acquire a new cleanup operation through restart/retry;
* interrupted pre-policy operation has no probe reservation;
* interrupted audit gates do not progress toward start outside Phase 4 recovery;
* reserved/created/uncertain active artifact remains ledger-active and blocks a new write;
* terminal removed/abandoned history is immutable and committed by the ledger;
* no-effect/successful cleanup closures update terminal history only after exact predicates;
* uncertain cleanup remains active;
* stale staging never becomes a second visible artifact;
* same-key retry returns retained work;
* surviving audit-obligation marker remains recovery-required;
* capability remains unavailable until kernel/root/profile/integrity checks pass.

24. Real Raspberry Pi validation
--------------------------------

Before live promotion, real-device evidence must prove the exact development Pi's protected
local root, service identity/mode/systemd exception, same-filesystem staging/final root,
no-replace publication, directory fsync, restart behavior, and absence of write escape.
These are evidence requirements, not facts asserted by this plan.

25. Security invariants
-----------------------

Phase 5 preserves all of the following:

#. authority exists only for the dedicated disposable probe root;
#. no source-workspace/system/command/Git/package/service/privileged/hardware authority is
   introduced;
#. Tool visibility/model text/preparation output is not authority;
#. real HOST confirmation support remains empirical;
#. pre-policy durability is Phase 4 minimal identity only;
#. required received audit precedes policy and allowed/authorised audit precedes running;
#. prepared nonce + caller key converge on one operation;
#. path generation high-water is independently anchored and monotonically increasing;
#. preparation never trusts a digest computed only from whatever rows survive;
#. deleting maximum/lower history cannot lower high-water, permit generation reuse, or
   silently establish a new baseline;
#. terminal artifact history/ledger commitment is immutable to ordinary runtime except the
   reviewed atomic terminalization transition;
#. missing/corrupt ledger for a seen path is integrity failure, never an empty-path reset;
#. write canonicalization normalizes only exact prepared ledger -> exact self reservation;
#. cleanup preparation is valid only for the exact active ``created`` artifact; terminal
   artifacts cannot produce a new authorised cleanup-without-claim path;
#. cleanup preparation absence is observation only, never effect knowledge/provenance;
#. cleanup claim normalization accepts only expected NULL -> exact self transition;
#. **every start-capable cleanup final verifier rechecks independent ledger/version/
   high-water/active ownership and complete prior terminal history against prepared C/H**;
#. changed history/ledger after cleanup admission fails before audit-obligation publication,
   start, or unlink;
#. present-bound cleanup may normalize only exact secure present -> absent pre-start no-
   effect transition after complete ledger/history/artifact/self-claim/binding checks;
#. live path/cleanup ownership is single-owner and uncertain claims are non-stealable;
#. on-disk absence after dispatch alone never proves successful/no-effect cleanup;
#. exact current state is revalidated immediately before the Phase 4 effect boundary;
#. Phase 4 gates/audit-obligation marker remain the only start path;
#. write cannot overwrite and cleanup cannot delete mismatch;
#. raw keys/nonces/credentials do not enter DB/audit/log/evidence;
#. filesystem content is never interpreted as authority/instruction;
#. catalogue activation is fail closed when prerequisite evidence/integrity is absent;
#. Phase 6 remains unimplemented/unpromoted.

26. Implementation order
------------------------

After implementation/promotion prerequisites are met:

#. revalidate exact Phase 3 profile and Phase 4 implementation-exit evidence;
#. add protected root/config/systemd/setup verification;
#. add domain normalization/path/max-effect types/tests;
#. add migration ``0002`` with ``probe_operations``, ``probe_artifacts``, state-aware live
   uniqueness, unique generations, deferred references, and independent
   ``probe_path_ledger``;
#. implement deterministic empty-ledger creation plus complete terminal-history
   canonicalization/integrity verification;
#. implement atomic ledger reservation/terminalization transitions and tests before any
   filesystem effect adapter;
#. implement preparation binding for exact write ledger transition and cleanup
   ledger/active-artifact/target/self-claim state;
#. explicitly reject new cleanup preparation/admission for terminal artifacts;
#. implement dual prepared-nonce/caller-key minimal pre-policy identity;
#. integrate mandatory received audit before policy;
#. implement exact write/cleanup policy entries;
#. implement post-policy exact write reservation and cleanup self-claim admission;
#. integrate required allowed/authorised audit before ``running``;
#. implement write final OP-BOUNDARY with independent ledger/history checks;
#. implement cleanup final OP-BOUNDARY that **always** rechecks independent ledger/history
   immediately before every possible effect start;
#. implement secure staging/root adapter and atomic no-overwrite create;
#. implement exact cleanup/no-effect receipt;
#. implement receipt-aware reconciliation and ledger-safe terminal closure;
#. integrate Phase 4 audit obligations, gates, lifecycle, and retained-result semantics;
#. bind existing MCP handlers without changing contracts;
#. add all unit/property/integration/fault/restart/systemd tests, especially corruption
   between cleanup admission and final boundary;
#. extend real-Pi verification;
#. run full candidate validation;
#. activate write-probe only through evidence-selected host path;
#. execute frozen real-ChatGPT evaluation;
#. review/freeze evidence and only then update ``docs/mcp-profile.md``;
#. stop before Phase 6 workspace authority.

27. Deterministic review and plan-acceptance checklist
------------------------------------------------------

This planning PR is accepted only when a reviewer can establish all of the following:

* only this Phase 5 document changes and no host/device observation is fabricated;
* Phase 4 implementation exit + real Phase 3 evidence remain runtime prerequisites;
* existing MCP Tool/schema/confirmation contracts are unchanged;
* disposable root is separated from repository/config/state/audit/evidence paths;
* dual nonce/key design creates one minimal pre-policy operation and no pre-policy path
  reservation;
* mandatory Phase 4 audit gates retain exact ordering;
* ``probe_path_ledger`` is an independent integrity anchor, not a cache derived from
  current rows;
* path generation allocation uses ledger high-water, never surviving-row ``max()+1``;
* never-seen/seen-path distinction is deterministic/race-safe;
* every terminal generation is retained, contiguous, immutable, and committed by exact
  count/digest;
* maximum/lower-row corruption, missing/corrupt anchor, and orphaned provenance fail closed
  even when damage precedes preparation;
* write final canonicalization accepts only exact prepared ledger -> exact consuming self
  reservation and unchanged complete prior history;
* new cleanup preparation/admission applies only to live ``created`` artifact; already
  terminal artifacts cannot create an authorised no-claim operation;
* cleanup final verifier recomputes and compares complete prior terminal history + ledger
  version/high-water/active ownership immediately before every possible unlink;
* history/ledger corruption after cleanup admission therefore yields zero start/unlink;
* cleanup observed absence does not fabricate file identity/effect knowledge;
* present-bound secure absence is accepted only at final pre-start boundary as exact
  no-effect branch after full integrity revalidation;
* post-dispatch absence needs exact durable effect/no-effect evidence before closure;
* uncertain operations remain fail closed across restart;
* one-artifact create/cleanup and crash reconciliation are deterministic;
* real-host choices remain evidence-selected;
* exact-head Contract Validation/Python CI are green where configured;
* all actionable review threads are individually addressed/resolved.

28. Implementation-promotion checklist
--------------------------------------

The capability may become live only when:

* Phase 4 implementation exit passes for exact build;
* selected Phase 3 profile/evidence is reviewed/current;
* real-Pi root/filesystem/systemd checks pass;
* protected local policy grants only the selected controller profile;
* automated tests prove no denied/pre-policy/audit-failed request can reserve/advance path;
* automated tests prove independent ledger integrity before preparation, admission,
  **every final write/cleanup effect boundary**, terminalization, and restart;
* tests cover maximum/lower history corruption before preparation and after admission,
  missing/corrupt ledger, generation-reuse attempts, and restart mismatch with zero start;
* tests prove terminal-artifact new cleanup is rejected before authorisation and prior
  same-key cleanup retries return retained work;
* tests prove exact-self write/cleanup canonical transitions only;
* lost cleanup receipts cannot infer success/no-effect from absence;
* all Phase 5 automated tests and existing quality/contract validation pass;
* production composition adds no other effect adapter;
* HOST catalogue is activated only through reviewed evidence-selected profile;
* no HC1 support axis is promoted before live evaluation passes.

29. Real Phase 5 exit checklist
-------------------------------

Exit requires reviewed evidence showing, for the exact tested profile:

* real ChatGPT discovers exact write-probe catalogue;
* preparation binds target/content/maximum effect and performs no external effect;
* host presentation/confirmation is observed or honestly classified;
* decline produces no execute/effect;
* approved write produces exactly one artifact inside probe root;
* lost response/same-key retry produces one operation/effect;
* reconnect reconciles same operation;
* cleanup establishes exact artifact absence exactly once;
* repeated frozen-path attempts retain history and monotonically advance ledger generation;
* no path escape/overwrite/network/credential/repository/system effect occurs;
* required attempt counts/stability thresholds pass;
* evaluation manifest/reviewer decision/evidence/receipt validate and are sanitized;
* ``docs/mcp-profile.md`` records only observations actually supported.

30. Provisional freeze points
-----------------------------

Remain unresolved until named evidence exists:

* exact ChatGPT write entitlement;
* exact HC1 owner-presentation/non-bypassability behavior;
* exact catalogue refresh/reconnect path;
* exact external auth scope/claim string;
* preparation TTL tuning within reviewed bound;
* whether host can directly generate every concurrency pattern.

None changes local maximum effect or permits broader authority.

31. Planning stop rule
----------------------

This plan is complete when a coding agent can implement the disposable write probe,
integrate it with Phase 4, preserve independent path-history integrity across crash/restart,
revalidate that integrity immediately before **every** consequential filesystem start, test
exact idempotency/audit/current-state/effect semantics, and execute the real-host evidence
procedure without inventing unresolved host/device facts.

Stop here. Do not add Phase 6 development-workspace operations, repository mutation,
command execution, Git, privileged service/package control, hardware, or later-phase
capabilities to this document.
