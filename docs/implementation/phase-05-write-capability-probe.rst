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
                       one disposable local filesystem adapter, preparation/current-state
                       binding, Phase 4 durable-operation integration, exact idempotency,
                       durable path-history integrity, evaluation/evidence capture, and
                       narrow deployment permissions only

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
* establish absence of one exact artifact previously created by the probe, deleting that
  artifact only while retained identity/content/ownership facts still match.

``probe_workspace_prepare`` remains HC0/no-effect. Preparation binds exact future effect
inputs and exact current state; it is not owner authority and cannot cross the filesystem
effect boundary.

This document freezes evidence-independent implementation semantics only. It does not
claim that ChatGPT currently exposes these Tools, presents an HC1 confirmation UI, grants
write entitlement, refreshes catalogue metadata in a particular way, retries in a
particular way, or reconnects in a particular way. Those remain real-host observations.
The ``:Status: merged`` value is the terminal document status after this planning PR lands;
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
evidence-gated, passes Contract Validation, and has no unresolved actionable review
finding. Plan acceptance grants no runtime authority.

2.2 Implementation/promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not begin or promote the live Phase 5 capability until:

* Phase 4 implementation exit passes on the exact candidate build;
* real Phase 3 evidence is reviewed/current for the selected ChatGPT product, plan,
  workspace, connection/authentication profile, discovery behavior, and applicable
  host-confirmation capability;
* the selected controller profile maps to a concrete non-wildcard local write-probe
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
   Contract ``1.1``; HC1; establishes absence of one exact manifest-owned probe artifact,
   deleting only while path/artifact/preparation/controller/content facts remain exact.

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
       max_file_bytes: int = 65536
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

7. Deterministic domain and path normalization
----------------------------------------------

Use small typed domain values for operation kind, path, write intent, cleanup intent,
artifact state, state binding, and retained artifact. Raw execution nonces/idempotency
keys stop existing after the Phase 4 digest boundary.

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

8. Persistence: operation-specific facts
----------------------------------------

Migration ``0002`` adds only Phase 5-specific facts. Generic lifecycle/idempotency remains
Phase 4-owned.

8.1 ``probe_operations``
~~~~~~~~~~~~~~~~~~~~~~~~

One row exists per mutating Phase 5 operation that passed policy admission:

* ``operation_id`` PK/FK to ``operations``;
* ``probe_operation`` enum ``write``/``cleanup``;
* ``prepared_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``caller_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``artifact_id`` NOT NULL, with a deferred integrity FK to ``probe_artifacts.artifact_id``
  for admitted write/cleanup operations that own/target an artifact;
* ``relative_path``;
* expected content SHA-256 and optional expected byte count;
* ``prepared_state_binding_sha256``;
* ``created_at``.

The row is inserted only in the post-policy admission transaction. A denied/interrupted
pre-policy ``received`` operation has no ``probe_operations`` row and owns no path
reservation. Deferred FK use is allowed only to permit same-transaction creation of the
write's ``probe_operations`` and ``probe_artifacts`` rows; after commit no admitted probe
operation may reference a missing artifact.

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

Migration ``0002`` enforces ``UNIQUE(relative_path, path_generation)`` and the state-aware
live-path uniqueness equivalent to:

::

   CREATE UNIQUE INDEX uq_probe_artifacts_live_relative_path
       ON probe_artifacts(relative_path)
       WHERE state IN ('reserved', 'created', 'uncertain');

Terminal historical commitment fields become immutable after final ``removed`` or
durably-proven-no-effect ``abandoned`` terminalization. Runtime code never deletes a
terminal artifact row to make a later request succeed.

8.3 ``probe_path_ledger``: independent path-history anchor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The previous artifact-row set is not itself trusted as the source of path high-water or
history completeness. Migration ``0002`` therefore also adds an independently protected
per-normalized-path ledger:

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

For a never-seen path, the only acceptable initial state is the deterministic empty anchor:

::

   generation_high_water = 0
   terminal_history_count = 0
   terminal_history_sha256 = SHA256(JCS([]))
   active_artifact_id = NULL
   active_generation = NULL
   active_create_operation_id = NULL

The preparation service may create this empty metadata row in one race-safe SQLite
transaction only when both the ledger and every artifact row for the normalized path are
absent. This is durable no-effect security metadata, not a filesystem reservation. If a
ledger is missing while any artifact/probe provenance proves the path was previously seen,
that is integrity failure, not a new path. Conversely, an existing non-empty ledger with
missing history is integrity failure; it is never reset to empty.

Stable/preparable path invariants are exact:

* ``active_artifact_id``, ``active_generation``, and ``active_create_operation_id`` are
  NULL;
* every generation 1..``generation_high_water`` exists exactly once in
  ``probe_artifacts`` and is terminal/stable ``removed`` or proven-no-effect
  ``abandoned``;
* ``terminal_history_count == generation_high_water``;
* canonical ordered terminal history recomputes exactly to
  ``terminal_history_sha256``.

Canonical terminal history is strict ascending ``path_generation`` JCS over at least:

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
   active_cleanup_operation_id     # NULL in terminal history
   removed_by_cleanup_operation_id
   created_at
   removed_at

Any missing generation, deletion of the maximum row, deletion/mutation/insertion of a
lower row, duplicate/reordered generation, orphaned operation/artifact provenance, digest
failure, nonterminal row, or canonicalization failure makes the path non-preparable and
fails closed. The ledger is the independent commitment that prevents already-damaged rows
from becoming a new baseline.

8.4 Ledger reservation transition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A write reservation is one atomic post-policy transition from prepared ledger state
``L/N/C/H`` to exact-self active state:

::

   before admission:
     ledger_version = L
     generation_high_water = N
     terminal_history_count = C = N
     terminal_history_sha256 = H
     active_* = NULL

   after exact-self reservation:
     ledger_version = L + 1
     generation_high_water = N + 1
     terminal_history_count = C
     terminal_history_sha256 = H
     active_artifact_id = exact self artifact
     active_generation = N + 1
     active_create_operation_id = exact current operation

The same short transaction inserts the unique ``reserved`` artifact generation ``N+1``
and deferred referential facts. Allocation therefore comes from the durable ledger, never
``max(current rows)+1``. A lost/deleted maximum artifact row cannot cause generation reuse.

The phase-stable semantic token
``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``
represents this entire exact-self artifact **and ledger** transition. At preparation it is
valid only for exact ``L/N/C/H`` with no active generation; at final OP-BOUNDARY it may be
canonicalized to the same prepared component only for exact ``L+1/N+1/C/H`` owned by the
consuming operation and prepared binding. No other ledger transition is normalized.

8.5 Ledger terminalization transition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A live generation remains the ledger's exact active generation while ``reserved``,
``created``, or ``uncertain``. New write preparation is therefore impossible while a live
or uncertain generation exists.

Only two states may join terminal stable history: exact ``removed`` and a write generation
whose no-effect outcome is durably proven and therefore becomes ``abandoned``. Before
terminalization, one short transaction must:

#. revalidate the prior terminal rows against the existing ledger ``C/H``;
#. revalidate exact active artifact/generation/create operation and the required operation
   effect/audit/recovery predicates;
#. build the exact final immutable representation of generation ``N``;
#. append that generation conceptually to canonical history and compute ``C+1/H'``;
#. update the artifact to its terminal final representation and atomically update the
   ledger to ``terminal_history_count=C+1``, ``terminal_history_sha256=H'``, clear
   ``active_*``, and increment ``ledger_version``;
#. require ``terminal_history_count == generation_high_water`` after commit.

If prior history no longer matches the independent anchor, or any required operation/
audit/filesystem fact is unavailable, terminalization fails closed and leaves the ledger
active/conservative. Recovery never repairs the anchor from damaged rows.

A reviewed migration/manual integrity repair may deliberately change history only through
an explicit recovery procedure that invalidates every outstanding preparation for the
path, records bounded integrity evidence, and establishes a newly reviewed anchor. Normal
runtime/restart reconciliation never performs automatic rebasing.

9. Preparation service
----------------------

``ProbeWorkspaceService.prepare`` is no-effect but durable security state.

For ``operation=write``:

#. authenticate the selected Phase 3 controller/profile;
#. validate schema, Phase 5 path policy, byte count, and protected probe-root identity;
#. prove target absent and no live-path artifact row;
#. load the ledger. If both ledger and all path/provenance rows are absent, race-safely
   create/read the deterministic empty ledger; if evidence shows a previously seen path
   but ledger is absent, fail integrity-closed;
#. require no ledger active generation;
#. load the complete terminal artifact history and prove exact contiguous generations
   1..``N``;
#. recompute ``C/H`` and require exact match to ledger
   ``generation_high_water=N``, ``terminal_history_count=C=N``, and digest ``H``;
#. bind root identity, target-absent fact, ledger identity/version ``L``, exact ``N/C/H``,
   and the phase-stable write-reservation transition token;
#. generate the reviewed random execution nonce and separate prepared operation ID;
#. compute exact prepared input/fingerprint;
#. register through Phase 4 ``register_prepared_execution_nonce`` with owner/device/Tool/
   contract, expiry, current-state digest, boot identity, trusted-time deadline, and exact
   prepared fingerprint;
#. append/fsync only schema-valid bounded preparation evidence; do not claim policy allow,
   owner UI confirmation, artifact reservation, or filesystem effect;
#. return the existing output schema.

Preparation, execute pre-policy validation, and post-policy pre-reservation admission must
all recompute the exact pre-reservation state. A changed ledger version, anchor, row set,
target, root, controller epoch, or prepared binding is stale/mismatch and cannot be
absorbed.

For ``operation=cleanup``, preparation additionally requires the exact retained artifact,
path/generation/controller ownership/content digest. A still-created artifact must have no
unresolved ``active_cleanup_operation_id``. Cleanup preparation permits exactly:

* **present** -- secure lookup proves exact retained regular-file identity/content and the
  binding includes
  ``cleanup_target_transition=exact_prepared_identity_or_absent_no_start``;
* **created target observed absent** -- secure lookup proves exact absence and the binding
  carries typed ``created_target_observed_absent`` plus exact artifact/generation/owner/
  content/root/path facts, without inventing a nonexistent file identity.

For both still-created variants, canonical current state contains
``cleanup_claim_transition=unclaimed_then_exact_self`` instead of a raw changing claim
literal. Before admission that token is valid only while the raw active cleanup claim is
NULL. After exact allow, one CAS may set NULL -> current operation. Final verification may
canonicalize back to the same token only after proving raw claim equals the exact running
operation and its immutable ``probe_operations.prepared_binding_id`` equals the consumed
prepared binding carrying the stored digest.

For a present-bound cleanup, disappearance **before admission** is stale/rejected. At final
pre-start verification only, exact secure absence may reproduce the same prepared target
token when every retained artifact/controller/root/path/self-claim/prepared-binding fact
remains exact. That path returns typed ``already_missing_pre_start`` and never authorizes a
filesystem effect. Replacement/mismatch/unverifiable absence is never normalized.

Preparation-time or final secure absence is observation only. It never proves who removed
a file, never produces ``known_effect``, never sets remover provenance, and never mutates
artifact/ledger state by itself.

10. Dual execution identity and minimal pre-policy durability
------------------------------------------------------------

Execute schemas require both ``execution_nonce`` and ``idempotency_key``. One internal
transaction binds them to one Phase 4 operation without weakening global duplicate
prevention:

#. digest raw identities and discard raw material;
#. load prepared and caller-key bindings with Phase 4 owner/tombstone rules;
#. require exact unexpired preparation/owner/device/Tool/contract/prepared input/fingerprint
   and current-state binding;
#. if caller binding exists, require same owner/fingerprint and same attached operation;
#. if prepared binding is already attached, only the same admitted caller key may obtain
   the retained operation; another fresh key is conflict;
#. otherwise atomically create only the minimal version-1 ``received`` operation, caller
   binding, and prepared-binding attachment;
#. commit.

This pre-policy transaction does **not** insert ``probe_operations``, create an artifact,
advance a path ledger, reserve a path, or claim cleanup. Policy deny, received-audit
failure, or crash before policy therefore cannot strand probe authority.

11. Policy, mandatory audit gates, and post-policy admission
------------------------------------------------------------

Phase 5 adds only two local consequential intents:

* ``probe_workspace_write@1.1`` -- one absent-file create under the probe root;
* ``probe_workspace_cleanup@1.1`` -- establish absence of one exact retained artifact.

External auth claim names remain evidence-selected. They map to one internal capability
such as ``probe_workspace_mutate``; no wildcard filesystem grant exists.

Phase 4 ordering remains exact:

#. after minimal durable ``received``, fsync schema-valid
   ``operation.state_changed(null -> received)`` before policy;
#. evaluate and durably retain one policy decision;
#. deny -> ``received -> rejected`` with required deny/rejected audit, no probe row, no
   ledger/reservation/claim transition;
#. allow -> one short transaction revalidates exact prepared state, persists the allow,
   inserts immutable ``probe_operations``, acquires operation-specific reservation/claim,
   and commits ``received -> authorised``;
#. fsync required ``policy.decision(allowed)`` + ``operation.authorised`` evidence;
#. only then may ``authorised -> running`` occur.

Required audit failure suppresses filesystem start and follows Phase 4 fail-restricted
recovery. An authorised reservation after an allow-audit failure remains conservative
recovery state; it is never freed by fabricating a terminal outcome.

For an allowed write, the admission transaction must prove exact prepared
``L/N/C/H``/absence/no-live-row, then atomically perform the ledger reservation transition
from section 8.4 and insert only the exact self ``reserved`` generation ``N+1``. Deferred
FKs must be satisfied at commit. A changed/missing ledger, changed history, pre-existing
live row, wrong generation, or integrity failure produces rejection/no effect; the
transaction never falls back to surviving-row ``max()+1``.

For an allowed still-created cleanup, the transaction revalidates exact retained artifact
and exact prepared filesystem observation, recomputes the pre-claim prepared digest while
claim is NULL, then atomically CASes
``active_cleanup_operation_id: NULL -> current operation``. It does not change artifact or
ledger terminal state. A present-bound disappearance before admission is stale. The
observed-absent variant merely acquires the exact claim after absence is re-proven.

A cleanup of an already durably ``removed`` artifact may be admitted as idempotent no-
effect establishment and acquires no live cleanup claim/start authority.

12. Final OP-BOUNDARY verifier
------------------------------

Every consequential operation uses Phase 4's per-operation handoff gate, global
consequential gate, and all-mode final current-state verifier before any effect-obligation
marker or ``EffectBoundary.start``.

For write, before the generic kernel compares current digest to the prepared digest, Phase
5 must prove:

* exact running operation/state version and exact consumed prepared binding;
* exact self ``reserved`` artifact at generation ``N+1`` with matching path/content/owner/
  controller/root facts;
* target remains securely absent;
* durable ledger is exactly the reviewed reservation state derived from prepared anchor:
  ``ledger_version=L+1``, ``generation_high_water=N+1``, terminal ``C/H`` unchanged, and
  ``active_artifact_id``/``active_generation``/``active_create_operation_id`` exactly name
  this artifact/generation/operation;
* complete retained history excluding **only** this exact self reservation is still
  contiguous terminal generations 1..N and recomputes to exact prepared ``C/H``;
* no operation/artifact/ledger referential integrity check fails.

Only then may the callback canonicalize the exact current state back to the prepared
``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``
token. The token explicitly covers the expected ``L/N -> L+1/N+1`` ledger transition and
self reservation; it is not a wildcard state exception.

Deletion of the maximum historical row, deletion/mutation/insertion of a lower row,
changed ledger version/high-water/digest/active owner, generation reuse, foreign/missing
reservation, prepared-binding mismatch, target appearance, root/controller change, or any
unverifiable state causes prepared mismatch/no start. A damaged row set can never become a
new baseline merely because preparation or verification recomputes a fresh digest.

For still-created cleanup, final current-state canonicalization is phase-aware only for:

* exact admission-owned cleanup claim ``NULL -> exact self``; and
* for a present-bound preparation, exact prepared identity -> secure absence no-start.

The verifier first proves raw active cleanup claim equals the exact current running
operation and exact prepared binding. For a present-bound target, exact same identity may
continue; secure absence may return ``already_missing_pre_start`` only while all other
retained facts are exact. Replacement/mismatch fails closed. For an observed-absent
preparation, continued secure absence is required; later appearance fails closed.

``already_missing_pre_start`` returns before audit-obligation publication and before
``EffectBoundary.start``. Because this admitted operation is proven not to have crossed the
boundary, it is durably classified ``known_no_effect``. The frozen lifecycle uses
``running -> failed``/``known_no_effect`` with bounded reason such as
``cleanup_already_missing_before_start`` while the existing cleanup Tool result may
truthfully return ``removed=false, already_missing=true``. No remover/effect provenance is
invented.

Any verifier unavailable/error condition fails closed. No "best effort" repair exists.

13. Phase 4 audit-obligation and effect ordering
------------------------------------------------

After ``authorised -> running``, Phase 5 preserves Phase 4 exactly:

::

   running
     -> fsynced effect.intent_recorded
     -> per-operation DispatchHandoffGate
     -> global ConsequentialBoundaryGate PRE_START permit
     -> final Phase 5 OP-BOUNDARY verifier
     -> if exact already_missing_pre_start: no start; known_no_effect closure path
     -> otherwise durable audit-obligation marker
     -> gate-owned call_start
     -> bounded effect/no-effect receipt/uncertainty
     -> immediate durable receipt/reference/effect-knowledge classification
     -> required post-effect/no-effect audit fsync
     -> exact obligation-marker closure when Phase 4 permits
     -> terminal/reconciliation closure

Failure of required intent audit trips the global consequential gate before effect. A
surviving obligation marker remains explicit-recovery-required across restart. Phase 5
never skips an audit stage because the effect is small or local.

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

Unavailable safe no-replace or directory-fsync semantics keep capability disabled.
Crash after publish/root-fsync is reconciled from exact retained reservation/file facts.

15. Exact cleanup effect
------------------------

``LinuxProbeWorkspace.start_cleanup`` accepts only the exact claimed retained artifact.
Before unlink it verifies protected root fd, exact active cleanup operation, exact regular
file identity/type/path/generation/content/owner facts. It then unlinks exact name, fsyncs
root directory, and returns stable effect reference.

If target becomes absent after ``call_start`` linearization but before unlink, the adapter
performs no unlink and may return an explicit no-effect receipt correlated to exact
operation/artifact/path generation. Only a durably retained/classified receipt proves that
no unlink was attempted. Receipt loss leaves post-dispatch absence ``uncertain``; absence
alone cannot reconstruct no-effect or known-effect.

Mismatched/symlink/directory/unowned content is never deleted automatically.

16. Reconciliation and ledger-safe closure
------------------------------------------

Reconciliation reconstructs references from durable operation/probe/artifact/ledger facts;
it never reconstructs effect knowledge merely from filesystem observation.

16.1 Write reconciliation
~~~~~~~~~~~~~~~~~~~~~~~~~

* exact final file present matching exact active ledger/artifact reservation -> durable
  created effect may be classified/converged according to Phase 4;
* unpublished staging only with final absent -> clean internal staging safely and converge
  truthful no-effect failure;
* final absent with proof no publication occurred -> no create effect;
* mismatched final state -> ``uncertain``/fail restricted.

A successfully created artifact remains the ledger's active generation while state is
``created``. It is not part of terminal-history ``C/H`` until exact later cleanup closure
terminalizes it as ``removed``.

A reserved write that is durably proven ``known_no_effect`` before publication may become
``abandoned`` only through section 8.5 ledger terminalization after required audit/recovery
closure. That atomic transition appends the immutable abandoned generation to terminal
history and clears the ledger active generation. If prior ledger/history integrity cannot
be re-proven, leave it conservative; never free the path by rebasing.

16.2 Cleanup claim closure
~~~~~~~~~~~~~~~~~~~~~~~~~~

Keep these cases separate:

* **pre-start or explicit durable no-effect-receipt absence:** after exact terminal
  ``known_no_effect`` plus required audit/recovery closure, one transaction revalidates
  exact artifact/generation/owner/current cleanup claim, exact no-effect reason/receipt,
  secure continued absence, and the existing path ledger's exact active generation. It
  then terminalizes that artifact to ``removed`` through section 8.5, clears
  ``active_cleanup_operation_id``, clears ledger ``active_*``, and leaves
  ``removed_by_cleanup_operation_id`` NULL. ``removed`` means durable current absence,
  not that this cleanup removed it;
* **successful removal:** only exact durable ``known_effect`` plus matching recoverable
  effect reference and completed post-effect audit/obligation/recovery closure may record
  ``removed_by_cleanup_operation_id=current operation`` and terminalize the exact artifact
  to ``removed`` through the same ledger-checked transaction;
* **post-dispatch absence without proof:** lost unlink/start receipt, uncertain effect
  knowledge, or incomplete audit/obligation/recovery closure -> do not set ``removed``, do
  not change ledger terminal commitment, do not clear ledger/artifact active ownership,
  and do not clear cleanup claim;
* **known no-effect while exact artifact remains present:** after terminal audit/recovery
  closure, clear only ``active_cleanup_operation_id`` by exact CAS. Artifact remains
  ``created`` and path ledger remains active on that generation;
* **mismatch/identity ambiguity:** retain claim/ledger active generation and fail restricted.

All closure transactions first recompute/verify the prior ledger terminal ``C/H``. A
missing/deleted/mutated historical row or corrupted/missing ledger therefore blocks
closure instead of silently repairing history.

16.3 Restart integrity
~~~~~~~~~~~~~~~~~~~~~~

Fresh-process startup verifies ledger/artifact/probe-operation referential integrity before
write-probe activation. A path whose ledger and rows disagree is integrity-failed and
cannot prepare/admit/start another effect. Restart never creates a missing ledger from
surviving rows and never decrements generation high-water.

17. Audit mapping and diagnostics
---------------------------------

Use only existing schema-valid payload kinds. Preparation records bounded digest/code
facts only: root/target state, prepared path-ledger version/high-water/count/digest, content/
maximum-effect digests, and reviewed transition identifiers. It never emits raw history
rows, raw nonce/key, filesystem content, credentials, owner-confirmation claims, or a
fictional reservation.

Execution preserves Phase 4 lifecycle/effect audit ordering exactly. Pre-start
``already_missing`` never emits ``effect.started`` and never claims ``known_effect``.
Ledger reservation/terminalization may be represented by bounded correlation/digest facts
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

For cleanup ``already_missing=true``, preserve the existing Tool success data even when
the retained consequential operation is ``failed``/``known_no_effect`` under the frozen
lifecycle; the effect snapshot truthfully states that this admitted operation performed no
filesystem effect.

Retry rules:

* same key/same input -> retained operation/result;
* same key/different input -> conflict;
* consumed preparation/new caller key -> conflict;
* expired preparation before admission -> deliberate new preparation only after proving
  no earlier operation was admitted;
* ``uncertain`` -> reconciliation/status semantics only, never automatic fresh effect;
* terminal known-no-effect cleanup does not silently reacquire a released claim; a later
  independent cleanup needs new preparation/key/policy admission.

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

#. record exact build/config/manifest/schema/policy/profile digests and required Pi
   identity evidence;
#. verify ``compatibility-core`` and authentication have not regressed;
#. activate/refresh the reviewed write-probe catalogue through observed host procedure;
#. verify visible Tools exactly match manifest;
#. prepare the frozen synthetic path/content and capture sanitized preparation facts;
#. exercise required decline attempts and prove no execute/effect;
#. approved execute must reach exact normalized request and produce exactly one artifact;
#. exercise lost response/same-key retry and prove one operation/one effect;
#. reconnect and prove exact retry returns retained work without duplicate effect;
#. prepare/execute exact cleanup and prove only exact artifact reaches absent state;
#. after cleanup, prove terminal artifact history remains retained and path ledger high-
   water remains monotonic; next independent attempt must allocate the next generation;
#. repeat exact frozen risk-class attempt counts, retaining blocked/failed/unstable results;
#. validate/freeze manifest, reviewer decision, evidence archive, and detached receipt;
#. only then update ``docs/mcp-profile.md`` with observations actually proven.

No live evaluation writes the Binnacle repository, ``/etc``, credentials, service units,
audit files, or other paths. CI mocks do not establish real Pi/real ChatGPT support.

21. Unit and property tests
---------------------------

Coverage includes at least:

* path normalization and max-effect bounds;
* deterministic text/base64/input fingerprints;
* empty path-ledger creation is race-safe and allowed only when ledger + all provenance
  rows are absent;
* missing ledger for a previously seen path fails closed;
* preparation recomputes complete contiguous terminal history and requires exact independent
  ledger ``L/N/C/H``;
* deleting the **maximum** historical row before preparation fails integrity and cannot
  reduce high-water or permit generation reuse;
* deleting or mutating a lower historical row before preparation fails history digest/
  count/integrity rather than becoming a new baseline;
* insertion/duplicate/reorder/canonical corruption fails closed;
* nonterminal prior history or active ledger generation rejects new write preparation;
* write reservation allocates strictly from ledger ``N -> N+1`` and atomically binds exact
  self active artifact/create operation/version ``L -> L+1``;
* attempted generation reuse is impossible even if artifact rows are missing/corrupt;
* final write canonicalization accepts only exact prepared ``L/N/C/H`` -> exact self
  ``L+1/N+1/C/H`` transition with prior rows unchanged;
* row/ledger deletion/mutation **after** preparation or admission yields mismatch/no start;
* terminalization checks prior ledger/history and atomically updates terminal digest/count;
* artifact/probe-operation deferred references are satisfied at commit and orphaning is
  rejected;
* cleanup observed-absent preparation is effect-neutral;
* present-bound cleanup disappearance before admission is stale, while exact disappearance
  after admission but before start reaches only ``already_missing_pre_start``;
* cleanup claim canonicalization accepts only NULL -> exact consuming operation with exact
  prepared binding;
* replacement/mismatch/foreign claim fails closed;
* mandatory received audit precedes policy;
* policy deny/pre-policy crash creates no probe reservation/ledger advance;
* allowed/authorised audit precedes ``running``;
* same nonce/key races converge on one operation/effect;
* lost receipts never infer effect from absence;
* known-no-effect claim release/absence closure and known-effect successful removal obey
  exact audit/recovery/ledger predicates;
* uncertain cleanup retains artifact/ledger active ownership and cleanup claim;
* no mismatch is deleted automatically;
* maximum effect remains one bounded artifact.

Property state machines combine preparation expiry, controller replacement, idempotency
collisions, ledger versions/high-water/history digests, artifact generations/states,
cleanup claims, policy/audit failures, and restart/reconciliation.

22. Required integration/fault tests
------------------------------------

Required faults include:

* crash after prepared binding registration;
* concurrent first execute same nonce/key and different caller keys;
* crash after minimal ``received`` before received audit/policy -> no probe reservation;
* received-audit failure -> no policy/reservation/effect;
* policy deny -> no reservation/ledger advance;
* concurrent allowed writes same path -> exactly one ledger/self reservation wins;
* crash after ledger/artifact reservation before ``running``;
* allowed/authorised audit failure -> no ``running``/filesystem start;
* crash after running/intent audit before final verifier;
* **delete maximum terminal artifact before preparation** -> ledger mismatch, zero start,
  high-water not decremented;
* **delete/mutate lower terminal artifact before preparation** -> ledger mismatch, zero
  start, no new baseline;
* delete/mutate/insert history after preparation -> admission/final mismatch, zero start;
* corrupt/remove path ledger while artifact/provenance rows exist -> integrity failure;
* restart with ledger/artifact mismatch -> write probe stays unavailable/fail restricted;
* attempted generation reuse after deleting maximum row -> impossible;
* rebind/delete/change exact self reservation -> final mismatch;
* target appears after preparation/before final boundary -> no start;
* staging/fsync/publish/root-fsync/receipt DB failures;
* crash after publish/root-fsync before receipt;
* exact cleanup self claim change -> final mismatch;
* cleanup present target disappears after admission/before final boundary -> no start,
  truthful ``known_no_effect`` path;
* cleanup replacement/identity mismatch -> no delete;
* audit-obligation publication/final audit failures;
* target absent before cleanup preparation -> observed-absent preparation, exact claim,
  no-start known-no-effect closure only after required audit/recovery;
* target absent after ``call_start`` but before unlink with durable explicit no-effect
  receipt -> no unlink and exact no-effect closure;
* same race with receipt loss -> uncertain, claim/ledger active retained;
* crash after unlink/root-fsync before receipt -> uncertain until explicit recovery proves
  effect; absence alone cannot close ledger;
* crash during ledger terminalization transaction -> atomic old or new state only;
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
  complete retained history before preparation/admission/start;
* missing/corrupt ledger or missing/mutated artifact history never gets auto-rebuilt;
* admitted write reconstructs exact self ledger/reservation transition without in-memory
  exceptions;
* foreign/missing/changed self reservation or prepared binding fails closed;
* cleanup observed-absent/present-bound transitions and exact self claim reconstruct from
  durable facts only;
* interrupted pre-policy operation has no probe reservation;
* interrupted audit gates do not progress toward start outside Phase 4 recovery;
* reserved/created/uncertain active artifact remains ledger-active and blocks a new write;
* terminal removed/abandoned history is immutable and committed by the ledger;
* no-effect and successful cleanup closures update terminal history only after exact
  predicates; uncertain cleanup remains active;
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
#. preparation never trusts a new digest computed only from whatever artifact rows happen
   to survive; complete rows must match the pre-existing ledger exactly;
#. deleting the maximum row cannot lower high-water or enable generation reuse;
#. deleting/mutating/inserting any prior row before or after preparation is detected and
   fails closed;
#. terminal artifact history and ledger commitment fields are immutable to ordinary
   runtime code except the reviewed atomic terminalization transition;
#. missing/corrupt ledger for a seen path is integrity failure, never an empty-path reset;
#. write prepared/current-state canonicalization normalizes only exact
   ``L/N/C/H`` -> consuming self ``L+1/N+1/C/H`` reservation transition;
#. cleanup preparation absence is observation only, never effect knowledge/provenance;
#. present-bound cleanup may normalize only exact secure present->absent pre-start no-effect
   transition after exact retained/self-claim/prepared-binding checks;
#. cleanup claim normalization accepts only expected NULL -> exact self transition;
#. live path/cleanup ownership is single-owner and uncertain claims are non-stealable;
#. on-disk absence after dispatch alone never proves successful/no-effect cleanup;
#. exact current state is revalidated immediately before the Phase 4 boundary;
#. Phase 4 gates/audit-obligation marker remain the only start path;
#. write cannot overwrite and cleanup cannot delete mismatch;
#. raw keys/nonces/credentials do not enter DB/audit/log/evidence;
#. filesystem content is never interpreted as authority/instruction;
#. catalogue activation is fail-closed when prerequisite evidence/integrity is absent;
#. Phase 6 remains unimplemented/unpromoted.

26. Implementation order
------------------------

After implementation/promotion prerequisites are met:

#. revalidate exact Phase 3 profile and Phase 4 implementation-exit evidence;
#. add protected root/config/systemd/setup verification;
#. add domain normalization/path/max-effect types/tests;
#. add migration ``0002`` with ``probe_operations``, ``probe_artifacts``, state-aware live
   uniqueness, unique generations, deferred referential constraints, and independent
   ``probe_path_ledger``;
#. implement deterministic empty-ledger creation and complete terminal-history
   canonicalization/integrity verification;
#. implement atomic ledger reservation/terminalization transitions and tests before any
   filesystem effect adapter;
#. implement preparation binding including ledger ``L/N/C/H`` and exact write reservation
   transition plus cleanup observed-absent/present-bound/self-claim transitions;
#. implement dual prepared-nonce/caller-key minimal pre-policy identity;
#. integrate mandatory received audit before policy;
#. implement exact write/cleanup policy entries;
#. implement post-policy exact ledger/self reservation and cleanup claim admission with
   ``received -> authorised``;
#. integrate required allowed/authorised audit before ``running``;
#. implement final OP-BOUNDARY verifier with independent ledger checks;
#. implement secure staging/root adapter and atomic no-overwrite create;
#. implement exact cleanup/no-effect receipt;
#. implement receipt-aware reconciliation and ledger-safe terminal closure;
#. integrate Phase 4 audit obligations, global/per-operation gates, lifecycle, and retained
   result semantics;
#. bind existing MCP handlers without changing contracts;
#. add all unit/property/integration/fault/restart/systemd tests, especially every
   before-preparation history-corruption case;
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
* never-seen/seen-path distinction is deterministic and race safe;
* every terminal generation is retained, contiguous, immutable, and committed by exact
  count/digest;
* maximum-row deletion, lower-row mutation/deletion/insertion, missing/corrupt anchor, and
  orphaned provenance all fail closed even when damage precedes preparation;
* write final canonicalization accepts only the exact prepared ledger -> exact consuming
  self reservation transition and unchanged complete prior history;
* cleanup observed absence does not fabricate file identity/effect knowledge;
* present-bound cleanup secure absence is accepted only at final pre-start boundary as
  exact no-effect branch;
* cleanup claim canonicalization accepts only exact admission-owned NULL -> self CAS;
* pre-start already-missing closure is representable without effect/remover provenance;
* post-dispatch absence needs exact durable effect/no-effect evidence before claim/ledger
  closure;
* uncertain operations remain fail closed across restart;
* one-artifact create/cleanup and crash reconciliation are deterministic;
* real-host choices remain evidence-selected;
* exact-head Contract Validation is green;
* all actionable review threads are addressed/resolved.

28. Implementation-promotion checklist
--------------------------------------

The capability may become live only when:

* Phase 4 implementation exit passes for exact build;
* selected Phase 3 profile/evidence is reviewed/current;
* real-Pi root/filesystem/systemd checks pass;
* protected local policy grants only the selected controller profile;
* automated tests prove no denied/pre-policy/audit-failed request can reserve/advance a
  path;
* automated tests prove independent ledger integrity before preparation, admission, final
  boundary, terminalization, and restart;
* automated tests explicitly cover deletion of maximum and lower historical rows **before
  preparation**, after preparation, missing/corrupt ledger, generation-reuse attempt, and
  restart mismatch with zero start;
* automated tests prove exact-self write and cleanup canonical transitions only;
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
test exact idempotency/audit/current-state/effect semantics, and execute the real-host
evidence procedure without inventing unresolved host/device facts.

Stop here. Do not add Phase 6 development-workspace operations, repository mutation,
command execution, Git, privileged service/package control, hardware, or later-phase
capabilities to this document.
