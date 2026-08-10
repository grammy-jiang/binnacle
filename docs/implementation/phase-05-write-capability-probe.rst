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
                       evaluation/evidence capture, and narrow deployment permissions only

Purpose
-------

Phase 5 is the first Binnacle phase whose intended live evaluation contains a real local
mutation. It exists to answer a narrow empirical question before normal development
workspace authority is granted: can the selected real ChatGPT product/account/workspace
reliably discover, confirm where required, invoke, retry, reconnect to, and clean up one
bounded disposable write through Binnacle's durable consequential-operation kernel?

The phase does **not** make the Binnacle repository writable. It does not add a general
filesystem API. The only effect-capable production adapter introduced by this phase owns
one dedicated probe root and implements exactly two logical effects:

* create one new regular file, at most 65536 decoded bytes, without overwrite; and
* establish absence of one exact artifact previously created by the probe, deleting that
  artifact when it is still present and still matches its retained identity/digest.

``probe_workspace_prepare`` remains a no-effect HC0 operation. Preparation binds exact
future effect inputs and current state; it is not owner authority and cannot by itself
cross the filesystem effect boundary.

This document is provisional in the sense defined by ``docs/implementation/index.rst``.
It freezes evidence-independent architecture and safety semantics now. It does not claim
that ChatGPT currently exposes the write Tools, presents an HC1 confirmation UI, permits
write entitlement, refreshes catalogue metadata in a particular way, or retries/reconnects
with any specific behavior. Those are real-host observations and remain unresolved until
reviewed evidence exists.

The ``:Status: merged`` value is the terminal document status after this planning PR
passes review/CI and lands. While the PR is open, this document is proposed rather than
authoritative.

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

The existing Tool names, schemas, descriptions, annotations, confirmation classes, and
result envelopes are frozen inputs. Phase 5 must not create alternate write-probe Tool
contracts merely because implementation details are inconvenient.

2. Three separate gates
-----------------------

2.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

This detailed plan may merge when:

* it specifies a deterministic disposable-write implementation without assuming host UI
  behavior;
* it consumes the Phase 4 durable kernel rather than creating a second operation system;
* it preserves the existing three write-probe Tool contracts exactly;
* all host/device-dependent choices are explicit provisional branches with named evidence;
* Contract Validation is green and review findings are resolved.

Plan acceptance grants no runtime authority.

2.2 Implementation/promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not begin or promote the Phase 5 live capability until all of the following are true:

* the Phase 4 implementation exit gate has passed on the exact candidate build;
* real Phase 3 evidence is reviewed/current for the selected ChatGPT product, plan,
  workspace, connection path, controller authentication profile, discovery behavior, and
  the applicable host-confirmation capability/status needed to attempt the HC1 probe;
* the selected controller profile provides a concrete non-wildcard local policy mapping
  for the write-probe capability;
* the candidate build can keep ``compatibility-write-probe`` invisible/disabled when any
  prerequisite is missing or stale;
* the real development Pi validates the probe-root filesystem capabilities required by
  the implementation below.

Missing/expired/contradictory evidence fails closed. It does not get replaced by the
planning assumptions in this document.

2.3 Phase exit gate
~~~~~~~~~~~~~~~~~~~

The roadmap Phase 5 exit remains empirical. Real ChatGPT must create and remove one exact
disposable probe artifact with exactly one logical effect per operation and no escape from
the probe root. The reviewed evidence must additionally cover preparation binding, HC1
behavior where applicable, idempotent retry/lost response, cleanup, and reconnect behavior
required by the frozen evaluation profile.

Phase 5 exit does not promote the Phase 6 Binnacle source workspace automatically. It is
only evidence that the selected host profile can safely proceed to review of the
operational workspace capability.

3. Exact reviewed MCP surface
-----------------------------

Phase 5 implements and exposes **only** the existing ``compatibility-write-probe``
catalogue additions:

``probe_workspace_prepare``
   Contract ``1.1``; HC0; no external/device effect. Prepares exactly one ``write`` or
   ``cleanup`` action and returns ``prepared_operation_id``, ``execution_nonce``, expiry,
   exact operation/path, normalized-input digest, and maximum-effect text.

``probe_workspace_write``
   Contract ``1.1``; HC1; creates one new file below the dedicated probe root. It requires
   an exact unexpired preparation, execution nonce, caller idempotency key, exact relative
   path, ``overwrite=false``, and exactly one of text/base64 content.

``probe_workspace_cleanup``
   Contract ``1.1``; HC1; establishes absence of one exact manifest-owned probe artifact,
   deleting it only when path, artifact identity, preparation, controller ownership, and
   content digest still match.

The five ``compatibility-core`` Tools remain available in the write-probe catalogue as
already declared. No operation-status, cancellation, result, Resource, Task, Prompt, or
other Tool is added by this phase.

4. Explicit non-goals
---------------------

Phase 5 does **not** implement or promote:

* write access to ``/srv/binnacle-dev/repo`` or any registered development workspace;
* arbitrary filesystem read/list/search/write/patch/move/delete;
* directory creation, recursive deletion, globbing, bulk cleanup, or overwrite;
* arbitrary path traversal or symlink following;
* command/process execution;
* Git operations;
* package/service/systemd mutation;
* privileged broker operations;
* credentials, credential agents, or external network effects;
* hardware effects;
* owner-authority inference from model text or preparation output;
* a new host-confirmation protocol;
* MCP Tasks, Resources, Prompts, MRTR/elicitation, or custom UI;
* a new operation lifecycle, second idempotency store, or alternate audit subsystem;
* Phase 6 development-workspace design.

5. Before and after semantics
-----------------------------

Before Phase 5 implementation, the reviewed manifest contains the write-probe contracts
but production composition has no real consequential effect adapter and the write-probe
catalogue is not promoted for a HOST profile.

After Phase 5 implementation but before live evidence passes, the code may contain the
probe adapter behind fail-closed composition and tests, but the selected HOST profile is
still unsupported for HC1 write/cleanup.

After the real Phase 5 exit gate passes, the compatibility profile may record the exact
observed write-entitlement/confirmation/retry/reconnect limitations for that tested
profile. No other workspace receives authority.

6. Expected implementation file set
-----------------------------------

The Phase 5 **implementation** is expected to create or modify the following paths. This
planning PR itself adds only this document.

6.1 Existing application/deployment files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Modify as required:

::

   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/adapters/mcp.py
   src/binnacle/adapters/compatibility.py
   src/binnacle/application/operations.py
   src/binnacle/application/boundary.py
   src/binnacle/cli.py
   deploy/systemd/binnacle-dev.service
   scripts/setup_dev_pi.py
   scripts/verify_dev_pi.py
   scripts/mcp_evaluation.py
   docs/operations/development-pi.rst
   docs/mcp-profile.md              # only after reviewed live evidence

Do not modify Tool names, schema references, confirmation classes, or catalogue phase
membership unless a separate contract-reconciliation PR is first reviewed.

6.2 Probe domain/application/adapter modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/domain/probe_workspace.py
   src/binnacle/ports/probe_workspace.py
   src/binnacle/application/probe_workspace.py
   src/binnacle/adapters/probe_workspace/
     __init__.py
     linux.py
     reconcile.py

Repository-consistent module placement may differ if Phase 4 implementation chose a
non-package application layout, but there must be one canonical ownership path.

6.3 Persistence migration
~~~~~~~~~~~~~~~~~~~~~~~~~

Add one explicit Alembic revision after the Phase 4 kernel revision, for example:

::

   migrations/versions/0002_write_probe_state.py

Runtime code never opportunistically creates these tables.

6.4 Tests
~~~~~~~~~

Add at least:

::

   tests/unit/test_probe_workspace_domain.py
   tests/unit/test_probe_workspace_normalization.py
   tests/unit/test_probe_workspace_policy.py
   tests/unit/test_probe_workspace_paths.py
   tests/unit/test_probe_workspace_prepare.py
   tests/integration/test_probe_workspace_store.py
   tests/integration/test_probe_workspace_write.py
   tests/integration/test_probe_workspace_cleanup.py
   tests/integration/test_probe_workspace_idempotency.py
   tests/integration/test_probe_workspace_reconciliation.py
   tests/integration/test_probe_workspace_audit.py
   tests/integration/test_probe_workspace_systemd_permissions.py
   tests/property/test_probe_workspace_properties.py

Extend the existing evaluation tests rather than introducing a second evaluation-case
language.

7. Dependencies
---------------

Phase 5 should add no new general runtime framework.

Use:

* the existing Phase 4 SQLAlchemy/aiosqlite/Alembic stack;
* Python ``os``, ``stat``, ``hashlib``, ``base64``, ``secrets``, and filesystem ``dir_fd``
  operations;
* AnyIO/asyncio mechanisms already in the project;
* existing Pydantic/JCS/schema/evaluation dependencies.

The Linux probe adapter may use a small, isolated native Linux no-replace publication
helper only if the chosen Python runtime does not expose the required primitive directly.
Do not add a broad filesystem framework. Any native helper must have a deterministic
fallback policy of **fail closed**, not overwrite.

8. Runtime filesystem layout
----------------------------

Add one dedicated disposable root:

::

   /var/lib/binnacle/
     probe-workspace/
       .staging/
       <probe artifact files only>

Requirements:

* root and ``.staging`` are owned by the dedicated ``binnacle`` service identity;
* mode is ``0700`` unless the implemented service identity requires a narrower equivalent;
* the root is on a local filesystem whose required atomic-link/no-replace and directory
  fsync behavior is verified before the write probe becomes available;
* the root is not a symlink, bind to source checkout, network filesystem, credential
  location, audit directory, operation-state directory, or evaluation-evidence directory;
* no other account receives ordinary write authority to the root;
* setup may remove abandoned internal staging files only through the reviewed reconciliation
  rules, never by recursive deletion of unknown content.

Under Phase 4 ``ProtectSystem=strict``, add exactly this durable write path to systemd:

::

   ReadWritePaths=/var/lib/binnacle/probe-workspace

Do not broaden ``/var/lib/binnacle`` generally and do not grant repository/config/audit
write access merely to implement the probe.

9. Protected configuration
--------------------------

Add immutable typed settings equivalent to:

.. code-block:: python

   class ProbeWorkspaceSettings(BaseModel):
       enabled: bool = False
       root: Path = Path("/var/lib/binnacle/probe-workspace")
       max_file_bytes: int = 65536
       preparation_ttl_seconds: int = Field(default=300, ge=30, le=900)

``root`` and ``max_file_bytes`` are structural security settings. Ordinary environment or
model-controlled CLI precedence cannot redirect/enlarge them.

``enabled`` is protected owner/deployment configuration and defaults false. It cannot
make the Tools live unless the runtime promotion checks also prove the Phase 4 kernel,
controller profile, catalogue/profile evidence, and local policy are current.

The exact preparation TTL may be adjusted within the reviewed 30--900 second bound if
real host-confirmation latency evidence justifies it. The selected runtime value is
recorded in evidence; the plan does not claim which value ChatGPT requires.

10. Phase 5 domain types
-----------------------

Define small deterministic types owned by ``binnacle.domain.probe_workspace``:

.. code-block:: python

   class ProbeOperation(StrEnum):
       WRITE = "write"
       CLEANUP = "cleanup"

   class ProbeArtifactState(StrEnum):
       RESERVED = "reserved"
       CREATED = "created"
       REMOVED = "removed"
       ABANDONED = "abandoned"
       UNCERTAIN = "uncertain"

   @dataclass(frozen=True, slots=True)
   class ProbePath:
       relative_path: str
       filename_bytes: bytes

   @dataclass(frozen=True, slots=True)
   class ProbeWriteIntent:
       relative_path: ProbePath
       content_sha256: str
       byte_count: int

   @dataclass(frozen=True, slots=True)
   class ProbeCleanupIntent:
       relative_path: ProbePath
       artifact_id: str
       content_sha256: str

   @dataclass(frozen=True, slots=True)
   class ProbeStateBinding:
       digest_sha256: str
       facts: tuple[object, ...]

   @dataclass(frozen=True, slots=True)
   class ProbeArtifact:
       artifact_id: str
       relative_path: str
       content_sha256: str
       byte_count: int
       state: ProbeArtifactState
       create_operation_id: str
       owner_controller_id: str
       owner_controller_epoch: int

Raw execution nonces/idempotency keys are not stored in these domain objects after the
Phase 4 key-digest boundary.

11. Phase 5 persistence additions
---------------------------------

Migration ``0002`` adds only operation-specific facts that do not belong in the generic
Phase 4 kernel.

11.1 ``probe_operations``
~~~~~~~~~~~~~~~~~~~~~~~~~

Persist one row per Phase 5 mutating operation that has passed policy admission:

* ``operation_id`` PK/FK to ``operations``;
* ``probe_operation`` enum ``write``/``cleanup``;
* ``prepared_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``caller_binding_id`` UNIQUE FK to ``idempotency_bindings``;
* ``artifact_id``;
* ``relative_path``;
* ``expected_content_sha256``;
* ``expected_byte_count`` nullable for cleanup;
* ``prepared_state_binding_sha256``;
* ``created_at``.

The row is inserted only in the post-policy admission transaction described in section
16. It is immutable after admission except for fields explicitly required by migration
compatibility. It proves which operation-specific target/artifact facts were authorised;
it is not a second lifecycle table. A rejected or interrupted pre-policy ``received``
operation therefore has no ``probe_operations`` row and owns no probe-path reservation.
Every admitted cleanup attempt remains independently retained here and in the Phase 4
``operations`` lifecycle even if its active artifact claim is later released after a
proven-no-effect outcome.

11.2 ``probe_artifacts``
~~~~~~~~~~~~~~~~~~~~~~~~

Persist every historical probe-owned filesystem-object generation:

* ``artifact_id`` PK, schema-compatible random identifier;
* ``relative_path`` NOT NULL;
* ``path_generation`` integer >= 1, monotonically increasing for each normalized
  ``relative_path`` across retained historical rows;
* ``owner_controller_id`` / ``owner_controller_epoch``;
* ``content_sha256``;
* ``byte_count`` <= 65536;
* ``state`` enum ``reserved``/``created``/``removed``/``abandoned``/``uncertain``;
* ``create_operation_id`` UNIQUE FK to ``operations``;
* ``active_cleanup_operation_id`` nullable UNIQUE FK to ``operations``; this is only the
  current state-aware cleanup claim while the exact artifact generation remains live;
* ``removed_by_cleanup_operation_id`` nullable UNIQUE FK to ``operations``; immutable once
  the exact cleanup that established ``removed`` is durably classified;
* ``created_at`` / ``updated_at`` / ``removed_at`` nullable as applicable;
* ``file_identity_digest`` nullable protected digest of stable local stat facts after a
  created file is verified.

Do **not** place an unconditional UNIQUE constraint on ``relative_path`` because removed
or safely abandoned history must remain durable while the frozen evaluation reuses the
same synthetic filename across attempts. Instead migration ``0002`` creates an exact
partial unique index equivalent to:

::

   CREATE UNIQUE INDEX uq_probe_artifacts_live_relative_path
       ON probe_artifacts(relative_path)
       WHERE state IN ('reserved', 'created', 'uncertain');

At most one live/uncertain generation can own a path. ``removed`` and proven-no-effect
``abandoned`` rows do not block a later independent write. A new write reservation
atomically chooses ``path_generation = max(retained generation for path) + 1`` (or 1 for
a never-seen path) while holding the short post-policy write transaction. Preparation
binds the current retained generation high-water value, including 0 for a never-seen path,
so a stale preparation cannot become valid again merely because another create/cleanup
cycle returned the target to an absent filesystem state.

A row is created as ``reserved`` only after policy allows the operation. It becomes
``created`` only when reconciliation/receipt proves the exact published file. A proven
pre-effect failure may mark it ``abandoned``. Any conflicting on-disk state becomes
``uncertain`` and remains live/fail-closed for that path; Binnacle never deletes a mismatch
merely to repair the probe.

``active_cleanup_operation_id`` is not cleanup-attempt history. It is a single-owner live
claim that prevents two cleanup effects from racing on one created generation. A cleanup
that reaches a durably proven ``known_no_effect`` terminal outcome while the exact created
artifact remains present may release that claim only through the deterministic closure
rules in section 20. The failed/no-effect operation remains retained in ``operations`` and
``probe_operations``. A successful cleanup may record
``removed_by_cleanup_operation_id``, move the artifact to ``removed``, and clear the
active claim only after durable ``known_effect`` classification for the exact cleanup plus
the applicable required post-effect audit/obligation closure. On-disk absence by itself
never authorizes that transition. An ``uncertain`` cleanup never releases or supersedes
its active claim.

No file content is stored in SQLite.

12. Path normalization and Phase 5 policy narrowing
---------------------------------------------------

The JSON Schema permits a bounded relative path. Phase 5 deliberately uses a stricter
local policy than the broad syntax envelope because nested workspace semantics belong to
Phase 6.

For Phase 5 promotion, ``ProbePath`` accepts exactly one filename component:

* no ``/`` or ``\\``;
* no absolute/drive prefix, ``.``/``..``, NUL, CR/LF, or colon;
* UTF-8 encoding must be <= 255 bytes;
* input must already be NFC-normalized; Phase 5 rejects rather than silently rewrites a
  different Unicode normalization form;
* names beginning ``.binnacle-`` and the exact ``.staging`` internal name are reserved;
* the final filename remains within the schema's 512-character limit.

This is a policy restriction, not a schema rewrite. A schema-valid nested path receives a
bounded policy/execution error in Phase 5 rather than being interpreted as permission to
create directories.

13. Exact normalization and fingerprinting
------------------------------------------

Preparation and execution use one shared normalizer.

Write normalized effect input contains exactly:

::

   tool=probe_workspace_write
   contract_version=1.1
   operation=write
   normalized_relative_path
   decoded_content_sha256
   decoded_byte_count
   overwrite=false
   target_identity_digest
   maximum_effect_digest
   prepared_operation_id
   prepared_input_sha256

Cleanup normalized effect input contains:

::

   tool=probe_workspace_cleanup
   contract_version=1.1
   operation=cleanup
   normalized_relative_path
   artifact_id
   expected_content_sha256
   target_identity_digest
   maximum_effect_digest
   prepared_operation_id
   prepared_input_sha256

Canonical JCS + SHA-256 is used for the request fingerprint through the Phase 4 kernel.
Raw text/base64 bytes are not duplicated into the operation DB or audit journal.

For ``probe_workspace_write``, strict base64 decoding must succeed and decoded bytes must
be <= 65536. The decoded byte count and SHA-256 must exactly match the preparation.
For text input, UTF-8 bytes are hashed/written; the string is not newline-normalized.

14. Preparation service
-----------------------

``ProbeWorkspaceService.prepare`` is no-effect but durable security state.

Algorithm for ``operation=write``:

#. authenticate the controller through the selected Phase 3 profile;
#. validate schema then Phase 5 path policy;
#. verify ``byte_count <= 65536``;
#. open/verify the protected probe-root identity through the adapter;
#. prove the final target name is absent and not represented by a live conflicting
   ``probe_artifacts`` reservation;
#. load the retained path-generation high-water value (0 if no historical row exists) and
   compute the current-state binding over root identity, target name, target-absent fact,
   and that durable generation;
#. generate at least 128 random bits for ``execution_nonce`` and a separate random
   ``prepared_operation_id``;
#. compute the exact prepared normalized-input/request fingerprint;
#. register the nonce through Phase 4
   ``OperationStore.register_prepared_execution_nonce`` with Tool/contract/owner/device,
   expiry, current-state digest, boot identity, and trusted-time monotonic deadline;
#. append/fsync schema-valid bounded preparation/audit evidence using existing payload
   kinds; do not invent ``owner_confirmed`` audit state or a filesystem reservation;
#. return the existing output schema.

Algorithm for ``operation=cleanup`` is identical except that it additionally requires a
retained ``probe_artifacts`` record owned by the current controller and exact
``artifact_id``/path/content digest. For a still-created artifact, preparation requires no
unresolved ``active_cleanup_operation_id``; a potentially releasable terminal claim must
first pass section 20 reconciliation, and preparation never steals or clears a claim. The
current-state binding includes the retained artifact generation, active-claim state, and
secure on-disk identity/digest when the file is present, or the exact durable
already-removed state when the prior cleanup has already succeeded.

Preparation output is not authorization. Raw execution nonce is returned to the caller as
required by the Tool schema but is never logged, audited, used as a metric label, or
retained in the evidence bundle without redaction/digesting.

15. Dual execution identity: prepared nonce plus caller key
-----------------------------------------------------------

The execute schemas require both ``execution_nonce`` and ``idempotency_key``. Phase 5
must bind both to one operation without weakening Phase 4 global duplicate prevention.

Add an internal transactional primitive equivalent to:

.. code-block:: python

   async def create_or_find_prepared_with_caller_key(
       *,
       prepared_nonce: str,
       caller_key: str,
       owner: OperationOwner,
       intent: OperationIntent,
       prepared_state: ProbeStateBinding,
   ) -> CreateOrFindResult: ...

One short **pre-policy** SQLite write transaction performs only durable identity work:

#. digest both raw identities immediately and discard raw values after validation;
#. load the global prepared-nonce binding and caller-key binding scopes;
#. apply the Phase 4 tombstone/owner non-disclosure rules to either existing binding;
#. require the prepared binding to be full, unexpired, exact owner/device/Tool/contract,
   and exact prepared operation/input/fingerprint/current-state match;
#. if the caller binding exists, require same owner/fingerprint and that its operation
   matches the consumed prepared binding; otherwise return the existing idempotency
   conflict/owner-mismatch outcome with no effect;
#. if the prepared binding is already attached to an operation, return that retained
   operation for the same admitted caller-key binding; a different fresh caller key may
   not create a new alias/effect and is rejected as ``idempotency_conflict``;
#. if the prepared binding is unconsumed and caller binding absent, atomically create the
   minimal version-1 ``received`` operation, create the full caller-key binding pointing
   to that operation, and attach the prepared binding to the same operation;
#. commit; only the newly admitted ``received`` operation proceeds to policy evaluation.

This transaction intentionally does **not** insert ``probe_operations``, mint an
``artifact_id``, create a ``probe_artifacts`` row, or claim the path for a cleanup. Those
are post-policy admission/reservation facts under the merged Phase 4 ordering. Therefore a
policy-denied request, or a crash after durable ``received`` identity but before policy,
leaves no target reservation behind.

The transaction is the only first-identity path for Phase 5. A concurrent request cannot
consume one preparation twice or bind two caller keys to two operations.

Same caller key/input returns the retained operation. Same caller key/different input is
``idempotency_conflict``. Same preparation with a different new caller key after
consumption is also rejected without creating an alias/effect. ``uncertain`` never causes
a fresh call with a new key.

16. Local policy and post-policy reservation
--------------------------------------------

Phase 4's production Bootstrap policy denies unknown consequential contracts. Phase 5
adds only two exact consequential intents:

* ``probe_workspace_write@1.1`` -- create one absent regular file under the probe root;
* ``probe_workspace_cleanup@1.1`` -- establish absence of one exact retained probe
  artifact.

The policy input includes authenticated controller/profile/epoch, selected catalogue
phase, normalized target/content/effect digests, artifact ownership, and protected
write-probe enablement.

No wildcard filesystem grant is introduced.

The exact external authentication scope/claim name used by the selected Phase 3 profile
is **provisional**. Implementation maps the reviewed live controller profile to one
internal capability such as ``probe_workspace_mutate`` without treating the external
claim string as a filesystem path or ambient authority. Missing/mismatched scope/profile
fails closed.

Policy evaluation occurs after the minimal pre-policy transaction from section 15. The
post-policy admission behavior is exact:

* on policy deny, one short SQLite transaction persists the one durable deny decision and
  legal ``received -> rejected`` transition; it inserts no ``probe_operations`` row and
  creates/claims no artifact reservation;
* on policy allow, one short SQLite write transaction revalidates the expected ``received``
  operation/version and current prepared state, inserts the one durable allow decision,
  inserts the immutable ``probe_operations`` row, and acquires the operation-specific
  reservation before the operation leaves ``received``;
* for a write, that transaction rechecks that the final path is absent, reads the retained
  path-generation high-water value, allocates ``path_generation = high_water + 1``, mints
  ``artifact_id``, and inserts the ``probe_artifacts`` row in ``reserved`` state under the
  partial live-path unique index;
* for cleanup of a still-created artifact, it revalidates exact
  artifact/path/generation/ownership and atomically compare-and-sets
  ``active_cleanup_operation_id`` from NULL to this operation; an existing active claim is
  never stolen or overwritten by admission;
* for cleanup whose retained artifact is already durably ``removed``, the operation may
  be admitted as an idempotent no-effect establishment of the requested absent state and
  acquires no active cleanup claim or filesystem-start authority;
* only after those writes succeed does the same transaction commit the legal
  ``received -> authorised`` transition/version row.

If a concurrent operation wins the live-path reservation, acquires the active cleanup
claim, or changes the retained artifact before the allowing transaction commits, this
operation must not become authorised. The transaction records the already-evaluated
admission decision together with a legal ``received -> rejected`` outcome/reason that
truthfully reports reservation/state conflict, without creating a second policy decision
or a partial reservation. A transaction failure that prevents those durable facts from
committing leaves the operation ``received`` and Phase 4 restart recovery handles it fail
closed.

An active cleanup claim is released only by the section 20 post-terminal/reconciliation
closure after a durably proven no-effect outcome. Policy admission itself never treats a
terminal-looking operation as permission to steal or clear that claim.

This preserves Phase 4's rule that pre-policy durability contains only minimal operation/
idempotency identity, while post-policy admission/reservation facts are durable before any
filesystem effect.

17. Final OP-BOUNDARY verifier
------------------------------

The Phase 5 ``OperationBoundaryVerifier`` plugs into the mandatory Phase 4 all-mode final
revalidation path and runs while the per-operation ``DispatchHandoffGate`` and global
``ConsequentialBoundaryGate`` semantics remain authoritative.

Immediately before ``EffectBoundary.start``, revalidate:

* current authenticated controller/profile/epoch and write-probe policy;
* Phase 4 kernel/audit/recovery health and open global consequential permit;
* exact ``running`` operation/state version;
* preparation expiry/trusted-time/current-state binding;
* probe-root identity and permissions;
* exact single-component target path;
* write target still absent and its live durable reservation/generation still belongs to
  this operation; or cleanup target/artifact still has the exact retained
  identity/digest/generation/ownership and ``active_cleanup_operation_id`` equals this
  operation;
* maximum effect remains one bounded local artifact;
* no cancellation/state-version change has occurred.

A cleanup admitted against an artifact already durably ``removed`` completes as an
idempotent ``known_no_effect`` success before filesystem start and therefore does not
obtain or require a global start permit merely to re-prove absence.

Any changed/unavailable predicate suppresses the filesystem effect. There is no "best
effort" path repair.

18. Atomic write effect
-----------------------

``LinuxProbeWorkspace.start_write`` is the first real effect adapter admitted by the
Bootstrap sequence. It implements a bounded local publish, not arbitrary filesystem IO.

Preconditions are supplied by the final boundary verifier. The adapter itself still
checks filesystem primitives defensively.

Algorithm:

#. open the configured root and ``.staging`` with directory file descriptors and
   ``O_DIRECTORY``/``O_NOFOLLOW`` where available;
#. create a unique internal staging file derived from operation/artifact identity with
   ``O_CREAT|O_EXCL|O_NOFOLLOW`` and mode ``0600``;
#. write exactly the already-validated decoded bytes;
#. fsync the staging file and verify byte count/digest;
#. atomically publish to the final root filename with a native no-replace operation. The
   preferred Bootstrap implementation is same-filesystem hard-link publication from the
   private staging file to the final name, which fails if the target already exists;
#. fsync the probe-root directory; this is the durable filesystem-effect point;
#. unlink the private staging name and fsync the staging directory;
#. return a stable opaque effect reference based on ``artifact_id`` plus the observed file
   identity digest.

Setup/startup verifies root and staging are on the same local filesystem and that the
chosen no-replace primitive works. If safe no-replace publication or directory fsync is
unavailable, Phase 5 capability stays unavailable. Never fall back to an overwrite-capable
rename.

A crash after final link+root-fsync but before staging cleanup is reconciled as a created
artifact when the final file matches exactly. The stale internal staging name is cleanup
state, not a second user-visible artifact.

19. Exact cleanup effect
------------------------

``LinuxProbeWorkspace.start_cleanup`` never accepts an arbitrary file.

Before unlink it:

#. opens the root by trusted directory fd;
#. loads the retained ``probe_artifacts`` row and requires
   ``active_cleanup_operation_id`` to equal the current operation;
#. securely opens/stats the final filename without following symlinks;
#. requires a regular file, exact protected owner/root context, exact artifact/path,
   byte count, content SHA-256, and retained file-identity facts;
#. unlinks that exact name through the directory fd;
#. fsyncs the root directory;
#. returns the stable artifact/effect reference.

If the exact artifact is already absent and durable artifact state proves it was the
probe-owned target, cleanup may complete with ``already_missing=true``. This is a logical
idempotent cleanup success: the contract's requested effect state (exact artifact absent)
is established without deleting another object. It must never use absence of an
unrecognized path as proof of successful cleanup.

If any file exists at the name with a mismatched type, digest, or identity, do not delete
it. Mark/reconcile the operation/path as uncertain/recovery-required and expose bounded
local recovery guidance.

20. Effect reference, cleanup-claim closure, and restart reconciliation
------------------------------------------------------------------------

Every Phase 5 operation has durable operation-specific facts before effect:

* operation ID/state version;
* prepared/caller binding relationship;
* artifact ID;
* target path digest, retained path generation, and expected content digest;
* ``probe_artifacts`` reservation/ownership or active cleanup claim.

``ProbeWorkspaceReconciler`` can therefore reconstruct a stable effect reference even if
``EffectBoundary.start`` crashed before returning its receipt. Reconstructing an effect
reference does **not** reconstruct effect knowledge: Phase 4's lost-start-receipt rule
still requires ``uncertain`` until durable evidence independently proves the outcome.

For write reconciliation:

* exact final file present with matching artifact/content/reservation -> created, known
  logical effect, converge operation to ``succeeded`` if lifecycle permits;
* final absent and only an un-published staging file exists -> no final create effect;
  clean internal staging safely and converge through a truthful no-effect failure;
* final absent and no publication evidence -> no final create effect under the protected
  single-writer probe-root invariant;
* final present but mismatched/unowned -> ``uncertain``/fail restricted; never overwrite
  or delete it automatically.

For cleanup reconciliation and active-claim closure:

* exact retained artifact absent after cleanup may move to ``removed`` only when the exact
  cleanup operation already has durable ``known_effect`` classification for a recoverable
  effect reference bound to the same artifact/path generation and the applicable required
  post-effect audit has fsynced, its audit-obligation marker has been durably cleared, and
  any active recovery generation is closed. Then one short idempotent transaction may
  revalidate the exact operation/artifact/generation/active claim, set artifact state
  ``removed``, record ``removed_by_cleanup_operation_id=operation_id``, clear
  ``active_cleanup_operation_id``, and converge the lifecycle truthfully;
* exact retained artifact absent but the unlink/start receipt or durable effect
  classification was lost, effect knowledge remains ``uncertain``, or required post-effect
  audit/obligation/recovery closure is incomplete -> absence is only an observation, not
  proof of a durable successful cleanup. Do not set ``removed``, do not record remover
  provenance, and do not clear the active claim. Keep the operation/path fail restricted
  until an explicit Phase 4 recovery/reconciliation path durably establishes truthful
  effect knowledge; filesystem absence alone can never perform that promotion;
* exact retained artifact still present and the operation has a durably proven
  ``known_no_effect`` outcome -> do not auto-repeat. First durably finish the operation's
  terminal/no-effect audit path and close any applicable audit obligation. Then one short
  idempotent SQLite compare-and-set transaction must revalidate that the artifact is still
  the same ``created`` generation/identity, the active claim still names this exact
  operation, effect knowledge is still ``known_no_effect``, and audit/recovery health
  permits new consequential admission. Only then clear ``active_cleanup_operation_id``;
* the released cleanup operation and its ``probe_operations`` row remain immutable retained
  history. A later independent cleanup therefore uses a new preparation, caller key, and
  operation while targeting the same still-created artifact generation;
* if the operation is ``uncertain``, the start receipt/effect boundary may have been lost,
  required audit/recovery closure is incomplete, or the on-disk artifact identity changed,
  keep the active claim and fail restricted. A later cleanup may not steal or supersede
  it;
* mismatched replacement/identity ambiguity -> ``uncertain`` with the active claim
  retained.

The successful-removal closure and the no-effect claim-release transaction are recovery/
control state, not new admission decisions. Both are safe to retry after crash because
they are conditional on the exact retained operation, exact artifact generation/identity,
exact active claim, exact effect knowledge, and healthy audit/recovery state. A crash after
operation terminalization but before either closure therefore leaves a conservative claim
that fresh-process reconciliation may clear idempotently only after re-proving every
predicate above.

Reconciliation never creates a second effect and never changes idempotency identity.
Historical ``removed``/``abandoned`` rows and every cleanup attempt remain retained so
path-generation high-water and operation history survive restart and repeated evaluation
attempts.

21. Phase 4 audit-obligation and global-gate integration
--------------------------------------------------------

Phase 5 is not allowed to call the filesystem adapter directly from an MCP handler.
Every effect goes through the Phase 4 coordinator in this order:

::

   authenticated execute request
     -> minimal dual prepared/caller identity + received operation
     -> evaluate policy
     -> one durable admission-policy decision
     -> post-policy probe operation + artifact/active-cleanup reservation
     -> authorised
     -> running
     -> fsynced effect.intent_recorded
     -> per-operation DispatchHandoffGate
     -> global ConsequentialBoundaryGate PRE_START permit
     -> final Phase 5 OP-BOUNDARY verifier
     -> fsynced protected audit-obligation marker
     -> gate-owned call_start
     -> bounded write/cleanup effect
     -> immediate durable receipt/reference/effect-knowledge classification
     -> required post-effect audit fsync
     -> obligation-marker removal + parent-dir fsync
     -> terminal result/reconciliation
     -> if cleanup is durably known-no-effect and the exact artifact is unchanged,
        idempotent active-claim release under section 20 predicates
     -> if cleanup is durably known-effect and the exact artifact is absent,
        idempotent successful-removal closure under section 20 predicates

Required audit failure trips the global consequential gate exactly as Phase 4 specifies.
A surviving audit-obligation marker remains explicit-recovery-required across restart;
Phase 5 does not introduce an auto-clear exception for a "simple" file effect. In
particular, a cleanup claim is not released while required audit/recovery state is failed
or incomplete merely to make another cleanup attempt possible.

22. Audit mapping
-----------------

Use only existing schema-valid audit payload kinds.

Preparation may use existing policy/preparation evidence with ``operation_id=null`` and
``prepared_operation_id`` populated where schema permits. It must not claim a filesystem
reservation or owner UI confirmation occurred before policy admission.

Execution uses the Phase 4 lifecycle/effect mappings, including:

* ``operation.state_changed``;
* ``policy.decision`` / ``operation.authorised``;
* ``effect.intent_recorded``;
* ``effect.started`` / ``effect.observed`` / ``effect.failed`` /
  ``effect.uncertain`` as truthful;
* recovery/cancellation payloads when applicable.

Record bounded digests for target path, path generation, content, maximum effect, artifact
identity, Tool manifest, profile/policy, and operation correlation. Raw file content,
execution nonce, idempotency key, credentials, and complete host-confirmation screenshots/
transcripts are not audit payload.

Host UI confirmation is evaluation evidence, not a server-verifiable authority fact.
Server audit may record the selected reviewed HOST-profile digest/status used for
promotion, but must not fabricate ``owner_confirmed=true``.

Clearing an ``active_cleanup_operation_id`` after a proven-no-effect terminal outcome does
not erase or replace audit evidence. The original cleanup operation, its policy/lifecycle/
effect evidence, and its ``probe_operations`` row remain retained; the claim release only
records that this exact live artifact may be the subject of a later independently admitted
cleanup.

Likewise, an absent filesystem observation after dispatch is not an audit event that can
upgrade ``uncertain`` to ``known_effect``. Successful-removal closure requires already-
durable exact-effect knowledge plus the required post-effect audit/obligation/recovery
closure; otherwise the uncertainty and active claim remain retained.

23. MCP handler behavior
------------------------

MCP adapters remain thin.

``probe_workspace_prepare``:

* schema validate;
* obtain authenticated controller context;
* call ``ProbeWorkspaceService.prepare``;
* return the exact existing success/error envelope.

``probe_workspace_write`` / ``cleanup``:

* schema validate before decoding/normalization side effects;
* obtain authenticated controller context;
* call the operation-specific application service using Phase 4 coordinator;
* wait only for this bounded local operation to reach a truthful terminal/uncertain result;
* return existing output schema plus the canonical operation snapshot/evidence fields;
* on same-key retry, return retained state/result rather than executing again.

Phase 5 does not require a new MCP operation-status Tool because its local probe effects
are bounded. Reconnect/lost-response tests reconcile by repeating the exact execute Tool
with the same idempotency identity and prepared inputs. An uncertain retained operation
returns uncertainty/reconciliation guidance and never causes a new-key automatic retry.

24. Catalogue activation and host-dependent branch
--------------------------------------------------

Runtime catalogue generation remains filter-only from
``spec/mcp/bootstrap-tool-manifest.yaml``.

The write-probe Tools are visible only when the protected selected catalogue phase is
``compatibility-write-probe`` **and** all local promotion prerequisites pass.

The mechanism by which ChatGPT notices the new catalogue is provisional:

* if reviewed Phase 3 evidence proves reliable list refresh/reconnect behavior, use that
  observed path;
* if the host requires disconnect/reconnect or app/connector refresh, follow the exact
  recorded procedure;
* if the host cannot safely expose/confirm the HC1 Tools for the selected profile, record
  ``host-policy-blocked``/other frozen status and do not weaken the server contract.

Do not add dynamic metadata mutation or a second Tool name to work around a host limit.

25. Error and retry projection
------------------------------

Use the canonical ``binnacleError`` envelope and Phase 4 stable error vocabulary where
applicable.

At minimum distinguish:

* schema/normalization/policy rejection before operation creation;
* ``prepared_operation_mismatch``;
* ``prepared_operation_expired``;
* ``trusted_time_unavailable``;
* ``idempotency_conflict``;
* ``idempotency_owner_mismatch``;
* ``idempotency_key_retired``;
* ``operation_state_conflict``;
* ``audit_unavailable`` / ``audit_integrity_failed``;
* probe-root unavailable/unsafe;
* target exists/no-overwrite conflict;
* artifact mismatch/not-owned;
* active cleanup claim conflict/recovery required;
* ``operation_uncertain``.

Retry guidance must be truthful:

* retained same-key terminal -> same request may retrieve retained result;
* a cleanup that is durably ``known_no_effect`` does not silently reacquire its claim on
  same-key retry; after section 20 releases the active claim, any later independent cleanup
  requires a new preparation/key/operation and normal policy admission;
* uncertain -> ``query_status``/``reconcile`` semantics, never fresh execution key;
* preparation expired before admission -> caller may deliberately create a new preparation
  and new logical operation only after observing that no earlier operation was admitted;
* same key/different input -> no retry under that key.

Do not mark an operation-level external effect retryable merely because HTTP/MCP transport
failed.

26. Evaluation cases exercised by Phase 5
-----------------------------------------

Reuse the frozen evaluation manifest. Phase 5 must exercise, when applicable to the real
HOST profile:

* ``write-entitlement-and-confirmation``;
* ``confirmation-decline``;
* ``idempotency-lost-response``;
* ``uncertain-no-auto-retry``;
* ``reconnect-status-reconciliation`` using exact execute retry/reconciliation rather
  than a new Tool;
* ``concurrent-idempotency-race`` in the server/integration harness and through the real
  host where the host can reliably generate the required attempts without changing the
  oracle.

The frozen profile requires the risk-class attempt counts. A single successful manual
write is not sufficient evidence for an ``observed-supported`` promotion. Repeated
attempts may reuse the frozen synthetic filename after exact cleanup: each new independent
write obtains a new ``artifact_id``/``path_generation`` while the prior ``removed`` row is
retained, so evidence thresholds never require deleting durable history.

``operation-cancellation`` remains unexercised/not-applicable for the immediate bounded
probe unless the frozen case/profile independently requires a promoted cancellable test
operation. Phase 5 does not add a cancellation Tool simply to force that optional case to
pass.

27. Real ChatGPT evaluation procedure
-------------------------------------

After implementation/promotion prerequisites pass, execute the Phase 5 live run in a new
sanitized evidence bundle.

The exact procedure is:

#. record exact Binnacle Git/build/config/manifest/schema/policy/profile digests and Pi
   identity required by the evaluation contract;
#. verify ``compatibility-core`` still passes and authentication has not regressed;
#. activate the reviewed ``compatibility-write-probe`` catalogue through the observed
   Phase 3 host refresh/reconnect procedure;
#. verify the visible Tools exactly match the reviewed manifest;
#. call ``probe_workspace_prepare`` for a synthetic filename such as the frozen case's
   ``entitlement.txt`` and synthetic content digest/length;
#. capture/redact the exact preparation result and host presentation;
#. for required decline attempts, decline and prove no execute call/file effect occurred;
#. for execute attempts, approve through the actual host interaction and verify the exact
   execute request reaches Binnacle unchanged under the normalization contract;
#. prove exactly one artifact appears with exact bytes/digest/ID and no other probe-root
   path changes;
#. exercise lost response/same-key retry and prove one operation/one effect;
#. disconnect/reconnect using the observed host mechanism and prove exact retry returns the
   retained operation/result without a duplicate effect;
#. prepare cleanup using the returned artifact ID/path/digest;
#. exercise required HC1 cleanup confirmation and exact deletion/absence semantics;
#. after cleanup, verify the historical artifact row remains ``removed`` and a later
   independent attempt on the same frozen filename allocates the next path generation
   rather than reusing/deleting history;
#. repeat according to the frozen risk-class attempt counts and record all blocked,
   declined, failed, unstable, and successful outcomes rather than selecting only passes;
#. finalize the evaluation manifest, reviewer decision, evidence archive, detached receipt,
   and compatibility-profile update exactly as Phase 3/evaluation contracts require.

No test writes the Binnacle repository, ``/etc``, service units, credentials, audit files,
or other paths.

28. Evidence sanitization
-------------------------

Phase 5 evidence may retain:

* sanitized Tool list and result frames;
* operation/artifact IDs;
* content/path digests and bounded synthetic path where policy permits;
* state versions/effect knowledge;
* audit references;
* bounded UI observations;
* exact attempt/result status and timing.

It must redact or omit:

* raw execution nonce;
* raw caller idempotency key;
* bearer/cookie/auth headers;
* reusable controller/tunnel credentials;
* private keys;
* unrelated model/user content;
* unbounded screenshots/transcripts;
* raw protected audit journal payloads.

The synthetic probe content itself need not be retained when digest/byte count proves the
oracle.

29. Profile promotion
---------------------

Only after the final manifest is reviewed and its detached receipt is frozen may
``docs/mcp-profile.md`` change write/confirmation/retry/reconnect axes from unknown/
not-tested to their observed statuses.

Promotion is scoped to the exact tested:

* ChatGPT product/surface;
* account plan/workspace policy;
* connection/authentication profile;
* Binnacle build/config/manifest/schema/policy;
* MCP revision/capability profile;
* probe implementation and Pi platform facts.

A later material change triggers expiry/rerun according to the evaluation contract. A
passing Phase 5 profile does not imply another account/workspace supports writes.

30. Unit and property tests
---------------------------

Unit/property coverage includes:

* path policy rejects nested/absolute/dot/backslash/reserved/non-NFC/overlong names;
* text/base64 normalization produces identical digest only for identical decoded bytes;
* prepare/write and prepare/cleanup fingerprints are deterministic and contract-exact;
* prepared nonce/caller key dual admission creates one minimal ``received`` operation
  before policy and no probe-path reservation;
* policy deny leaves no ``probe_operations``/live artifact reservation and the path remains
  available for a later independent preparation;
* policy allow atomically persists operation-specific facts/reservation before
  ``authorised``;
* same caller key/input returns retained operation;
* same caller key/different input rejects;
* consumed preparation plus new caller key cannot create another operation/effect;
* owner mismatch is non-disclosing;
* expired/trusted-time-unavailable preparation cannot admit an effect;
* target-state or path-generation change between prepare/admission/final boundary
  suppresses effect;
* partial unique live-path reservation holds under concurrency while ``removed``/
  ``abandoned`` historical rows do not block a new generation;
* stale preparation remains invalid after a create+cleanup cycle returns the target to
  absence because the retained path-generation high-water changed;
* at most one ``active_cleanup_operation_id`` may own a created artifact at a time;
* a terminal cleanup with durably proven ``known_no_effect`` plus unchanged exact artifact
  releases its active claim only after required audit/recovery closure, retains its
  operation history, and permits a later independently admitted cleanup;
* cleanup absence with lost/missing start receipt, ``uncertain`` effect knowledge, or
  incomplete required post-effect audit/obligation/recovery closure never records
  ``removed``/remover provenance and never clears the active claim; absence alone cannot
  promote the operation to ``known_effect``;
* cleanup absence with exact durable ``known_effect`` plus matching recoverable effect
  reference and completed required audit/obligation/recovery closure may perform the
  idempotent successful-removal closure exactly once;
* an uncertain cleanup, audit/recovery-incomplete cleanup, or changed artifact never
  releases its active claim and therefore blocks a later cleanup from stealing authority;
* cleanup never deletes mismatched/unowned content;
* no automatic retry from ``uncertain``;
* maximum file/effect bounds are invariant.

Hypothesis state-machine tests should combine preparation expiry, controller replacement,
idempotency collisions, artifact states/generations, active cleanup claims, policy
decisions, and crash/reconciliation transitions.

31. Integration and fault tests
-------------------------------

Use temporary local filesystem roots with the real Phase 4 kernel and a counted filesystem
adapter where fault injection is needed.

Required faults include:

* crash after prepared binding registration;
* concurrent first execute with same nonce/key;
* concurrent same nonce with different caller keys;
* crash after minimal caller/prepared binding + ``received`` commit, before policy -> no
  ``probe_operations`` row/live artifact reservation;
* policy deny -> no reservation and a later independent attempt can use the path;
* concurrent policy-allowed writes for the same path -> exactly one live generation wins;
* repeated write/cleanup cycles on frozen ``entitlement.txt`` -> retained ``removed``
  histories plus monotonically increasing generations, no uniqueness failure;
* stale prepared write after another complete create/cleanup cycle -> prepared-state
  mismatch despite target being absent again;
* crash after post-policy artifact reservation/authorisation before ``running``;
* crash after ``running``/intent audit before final verifier;
* audit-obligation marker failure;
* target appears after prepare but before final boundary;
* staging create/write/fsync failure;
* crash after staging fsync before publish;
* no-replace publish finds target unexpectedly;
* crash after final publish/root-fsync before receipt;
* crash after publish before staging unlink;
* DB failure after created effect;
* required post-effect audit failure/latch failure paths inherited from Phase 4;
* cleanup target already absent;
* cleanup target digest/identity mismatch;
* cleanup intent-audit/final-verifier/adapter failure that is durably proven no-effect ->
  active claim remains until terminal/no-effect audit closure, then releases and a later
  independent cleanup can be admitted without deleting failed-attempt history;
* crash after cleanup terminalization but before active-claim release -> fresh-process
  reconciliation performs the same conditional release idempotently;
* DB failure while releasing a proven-no-effect cleanup claim -> claim remains
  conservative and later cleanup stays blocked until reconciliation succeeds;
* lost start receipt or any uncertain cleanup classification -> active claim remains and a
  new cleanup cannot supersede it;
* crash after unlink/root-directory-fsync but before receipt/effect-knowledge persistence ->
  even if the artifact is absent after restart, operation remains ``uncertain`` and the
  active claim is retained until explicit recovery independently establishes exact effect
  knowledge and required audit/obligation closure;
* response loss after write and cleanup;
* process restart then same-key retry;
* controller replacement replay;
* probe-root filesystem capability/permission failure.

Every fault test asserts zero effect or exactly one logical effect as appropriate; no test
may "repair" uncertainty by repeating a fresh effect.

32. Fresh-process restart tests
------------------------------

Close all runtimes and reconstruct a fresh application. Verify:

* prepared nonce/expiry/state binding remains enforceable;
* dual caller/prepared binding relation remains intact even when no post-policy probe row
  exists for a rejected/interrupted pre-policy operation;
* reserved/created/removed/abandoned artifact generations reconstruct correctly;
* path-generation high-water survives restart and removed history does not block a later
  safe generation;
* exact published file is reconciled after lost start receipt;
* stale private staging file never becomes a visible second artifact;
* a cleanup claim whose operation is durably terminal ``known_no_effect`` is released only
  after the exact artifact/generation/identity and audit/recovery predicates are re-proven;
* an absent cleanup target after a lost/missing cleanup receipt remains uncertain with its
  active claim retained; restart observation alone never records removal or enables path
  reuse;
* an uncertain or audit/recovery-incomplete cleanup claim survives restart and continues to
  block superseding cleanup admission;
* mismatched on-disk state remains uncertain/fail-restricted;
* same-key retry returns retained operation/result;
* a surviving Phase 4 audit-obligation marker still blocks new effects;
* write-probe availability remains false until all startup kernel/root/profile checks pass.

33. Real Raspberry Pi validation
--------------------------------

Before live ChatGPT promotion, the exact development Pi must prove:

* ``/var/lib/binnacle/probe-workspace`` is a local protected filesystem root;
* service identity/mode and ``ProtectSystem=strict`` write exceptions are exact;
* staging and final root share a filesystem;
* no-replace publication and directory fsync behave as the implementation expects;
* power/process-kill style restart reconciliation preserves one-effect semantics;
* no write escapes the root or affects source/config/state/audit/evaluation trees.

These are real-device evidence. CI mocks do not promote the Pi profile.

34. Security invariants
-----------------------

Phase 5 must preserve all of the following:

#. write/cleanup authority exists only for the dedicated probe root;
#. no source-workspace or system-management authority is introduced;
#. Tool visibility/annotation/model text/preparation output is not authority;
#. HC1 support remains an empirical HOST-profile fact;
#. pre-policy durability is limited to Phase 4 operation/idempotency identity; policy deny
   or pre-policy crash creates no probe-path reservation;
#. every effect has one durable policy decision plus operation-specific reservation before
   ``authorised`` and before the Phase 4 running/effect gates;
#. prepared nonce and caller key converge on one operation and cannot create aliases that
   produce additional effects;
#. live path uniqueness is state-aware; removed/proven-abandoned history is retained and
   path generations prevent stale preparation resurrection;
#. a created artifact has at most one active cleanup claim; policy admission never steals
   it, proven-no-effect release preserves the failed operation history, and uncertain or
   audit/recovery-incomplete cleanup retains the claim fail-closed;
#. on-disk absence after cleanup dispatch is never sufficient to record ``removed`` or
   clear the active claim; exact durable ``known_effect`` plus matching effect reference
   and completed required post-effect audit/obligation/recovery closure are required;
#. exact current state is revalidated immediately before the boundary;
#. Phase 4 per-operation cancellation handoff and process-wide consequential gate remain
   the only start path;
#. Phase 4 durable audit-obligation marker exists before filesystem start;
#. required audit failure blocks new effects and explicit recovery rules are unchanged;
#. write uses no-overwrite atomic publication;
#. cleanup deletes only the exact retained artifact and never a mismatch;
#. symlinks/directories/reserved/internal names are never accepted as probe artifacts;
#. raw keys/nonces/credentials do not persist in DB/audit/logs/evidence;
#. filesystem content is never interpreted as instruction/authority;
#. the adapter performs no network, command, Git, package, service, privileged, or hardware
   operation;
#. production catalogue is fail-closed when Phase 4/Phase 3/profile/root evidence is
   absent or stale;
#. Phase 6 remains unimplemented/unpromoted.

35. Logging and diagnostics
---------------------------

Structured diagnostics may include safe operation/artifact IDs, state/version, relative
probe filename when classified normal-result by the test profile, path generation, digest
prefixes, byte counts, policy/boundary result codes, and reconciliation outcome.

Never log raw content, execution nonce, caller key, credentials, raw controller assertion,
or full host transcript.

``verify_dev_pi``/local kernel diagnostics may report probe-root availability and
filesystem capability checks without exposing protected data.

36. CI and validation
---------------------

Extend existing normal workflows only when Phase 5 implementation begins. Keep prior
Phase 4 gates.

Canonical implementation validation includes at least:

.. code-block:: console

   uv sync --frozen
   uv run python scripts/compile_mcp_registry.py --check
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests
   uv run lint-imports
   uv run pip-audit
   uv run pytest tests/unit/test_probe_workspace_*.py
   uv run pytest tests/integration/test_probe_workspace_*.py
   uv run pytest tests/property/test_probe_workspace_properties.py
   uv run coverage run -m pytest
   uv run coverage report
   uv run tox -e py311,py312,py313,quality

CI uses temporary roots and synthetic content only. It never writes the repository through
the probe adapter.

37. Implementation order
------------------------

Implement Phase 5 in this order after the implementation/promotion prerequisites are met:

#. revalidate the exact Phase 3 profile and Phase 4 implementation exit evidence;
#. add protected probe-root configuration/systemd/setup verification;
#. add domain normalization/path/maximum-effect types and tests;
#. add migration ``0002`` with ``probe_operations``, state-aware live-path uniqueness,
   path-generation history, state-aware active cleanup claims, successful-cleanup
   provenance, and ``probe_artifacts`` constraints;
#. implement preparation state binding and Phase 4 prepared-nonce registration;
#. implement minimal dual prepared-nonce + caller-key pre-policy identity admission;
#. implement exact Bootstrap policy entries for write/cleanup;
#. implement post-policy ``probe_operations`` plus write/active-cleanup reservation
   transaction and authorised transition;
#. implement secure root/staging adapter and filesystem capability verification;
#. implement Phase 5 final boundary verifier;
#. implement atomic create/no-overwrite effect and reconciler;
#. implement exact cleanup effect, receipt-aware successful-removal closure,
   state-aware active-claim closure, and reconciler;
#. integrate both effects through Phase 4 global/per-operation gates, audit obligations,
   lifecycle, audit, and retained result semantics;
#. bind existing MCP handlers without changing manifest/schema contracts;
#. add unit/property/integration/fault/restart/systemd tests;
#. extend real-Pi verification;
#. run full candidate validation;
#. promote ``compatibility-write-probe`` only through the evidence-selected host
   refresh/reconnect path;
#. execute the frozen real-ChatGPT Phase 5 evaluation attempts;
#. review/freeze manifest/evidence/receipt and only then update ``docs/mcp-profile.md``;
#. stop before Phase 6 workspace authority.

38. Review checklist
--------------------

A reviewer verifies:

* only Phase 5 is designed;
* no Binnacle source-workspace authority appears;
* existing three Tool contracts are consumed exactly;
* Phase 4 implementation + real Phase 3 profile evidence remain promotion prerequisites;
* host-confirmation behavior is never assumed or converted into server authority;
* prepare is no-effect and binds exact input/current state/expiry/path generation;
* execute requires both prepared nonce and caller key and atomically binds both to one
  minimal pre-policy operation;
* policy deny/pre-policy crash leaves no probe-path reservation;
* exactly one state-aware durable artifact/active-cleanup reservation is acquired only
  after policy allow and before ``authorised``/filesystem effect;
* removed/proven-abandoned historical rows can coexist with a later live generation and
  stale preparation cannot revive after an intervening path generation;
* a proven-no-effect cleanup can release only its exact active claim after terminal audit/
  recovery closure, while its operation history remains retained and uncertainty never
  permits claim supersession;
* cleanup absence after dispatch records removal/clears the claim only with exact durable
  ``known_effect``, matching recoverable effect reference, and completed required post-
  effect audit/obligation/recovery closure; lost receipt/uncertainty keeps the claim;
* final boundary revalidation uses the Phase 4 handoff/global-gate path;
* Phase 4 audit-obligation semantics are not bypassed;
* write cannot overwrite and cleanup cannot delete a mismatch;
* restart/lost response cannot create a second effect;
* no raw keys/nonces/credentials enter persistence/audit/evidence;
* catalogue promotion is evidence-selected/fail-closed;
* evaluation uses frozen cases/attempt counts and honest blocked/failed outcomes;
* plan/promotion/phase-exit acceptance are separate;
* exact-head CI/review passes.

39. Deterministic plan-acceptance checklist
-------------------------------------------

This **planning PR** is accepted only when:

#. it changes only ``docs/implementation/phase-05-write-capability-probe.rst``;
#. the plan is explicitly provisional and makes no observed host/device claim;
#. Phase 4 implementation exit and real Phase 3 evidence remain required before live
   Phase 5 implementation/promotion;
#. the exact reviewed Tool/schema/confirmation contracts are preserved;
#. no new MCP Tool/Resource/Task/Prompt is designed;
#. the disposable root is separate from repository/config/state/audit/evaluation paths;
#. dual nonce/key idempotency has one atomic minimal pre-policy one-operation identity
   design;
#. policy deny/pre-policy crash cannot strand a probe-path reservation;
#. state-aware live-path uniqueness and monotonic retained path generations allow repeated
   frozen-case attempts without deleting history or reviving stale preparations;
#. state-aware cleanup claiming permits a later independent cleanup only after the prior
   claim is durably proven no-effect and safely released, while uncertain claims remain
   fail-closed and all cleanup-attempt history is retained;
#. cleanup removal/claim release after observed absence requires exact durable
   ``known_effect`` plus matching effect reference and completed required post-effect
   audit/obligation/recovery closure; lost receipt/uncertainty cannot infer success from
   absence;
#. post-policy operation-specific reservation precedes any authorised filesystem effect;
#. one-artifact write/cleanup algorithms and crash reconciliation are deterministic;
#. Phase 4 operation/audit/global-gate invariants remain authoritative;
#. all real-host catalogue/confirmation/retry choices name the evidence that resolves
   them;
#. Contract Validation is green for the exact plan head;
#. actionable AI-review threads are addressed and resolved.

40. Implementation-promotion checklist
--------------------------------------

The implementation may become live for the selected HOST profile only when:

#. Phase 4 implementation exit is proven for the exact build;
#. Phase 3 auth/discovery/profile evidence is reviewed/current and supplies the applicable
   confirmation/refresh path needed to attempt HC1 evaluation;
#. real-Pi probe-root filesystem/permission capability checks pass;
#. protected local policy maps only the selected authenticated controller profile to the
   write-probe capability;
#. automated tests prove denied/interrupted pre-policy operations cannot reserve paths and
   repeated cleaned-up attempts advance retained path generations safely;
#. automated tests prove known-no-effect cleanup claims release only after durable terminal
   audit/recovery closure, while uncertain/incomplete claims remain non-stealable across
   restart;
#. automated tests prove an absent cleanup target cannot be promoted to ``removed`` after
   a lost receipt/unknown effect outcome; exact durable ``known_effect`` plus matching
   effect reference and completed required post-effect audit/obligation/recovery closure
   are required before remover provenance/claim release/path reuse;
#. all automated Phase 5 tests pass;
#. production composition has no other new effect adapter;
#. ``compatibility-write-probe`` is activated only through the reviewed profile path;
#. no HC1 axis is reported as supported before the live evaluation passes.

41. Real Phase 5 exit checklist
-------------------------------

The roadmap Phase 5 exit is satisfied only by reviewed evidence showing, for the exact
profile:

#. real ChatGPT discovers the exact write-probe catalogue;
#. preparation output binds exact target/content/maximum effect and remains no-effect;
#. required host presentation/confirmation behavior is observed or honestly classified
   blocked/failed according to the frozen oracle;
#. decline produces no execute request and no file effect;
#. approved write produces exactly one artifact inside the probe root and no other local
   effect;
#. response loss/same-key retry produces one operation and one effect total;
#. reconnect/retry reconciles the same operation rather than creating a duplicate;
#. cleanup operates only on the exact artifact and establishes absence exactly once;
#. repeated required attempts may reuse the frozen path only by creating a new retained
   path generation after prior exact cleanup, never by deleting/reusing historical state;
#. no path escape/overwrite/network/credential/repository/system effect occurs;
#. required attempt counts and stability thresholds pass;
#. evaluation manifest validates, reviewer decision is embedded, bundle is sanitized,
   and detached receipt is frozen;
#. ``docs/mcp-profile.md`` records only the observations actually supported by that
   evidence.

A blocked/test-failed/unstable host does not satisfy the exit gate and does not justify
weakening local safety semantics.

42. Provisional freeze points
-----------------------------

The following remain intentionally unresolved until named evidence exists:

* exact ChatGPT plan/workspace write entitlement -> Phase 5 live evaluation;
* exact HC1 owner-presentation/non-bypassability behavior -> Phase 5 live evaluation;
* exact catalogue refresh/reconnect procedure -> reviewed Phase 3 discovery evidence;
* exact external auth scope/claim string -> reviewed selected Phase 3 controller profile;
* preparation TTL tuning within 30--900 seconds -> real host latency/confirmation evidence;
* whether the tested HOST profile can produce all concurrency attempt patterns directly ->
  real evaluation; server-side deterministic harness remains mandatory regardless.

None of these unresolved points changes the local maximum effect or permits broader
workspace authority.

43. Planning stop rule
----------------------

This plan is complete when a coding agent can implement the disposable write probe,
integrate it with the Phase 4 durable kernel, test its crash/idempotency/path/audit safety,
and execute the exact real-host evidence procedure without making an unresolved security
or architecture decision.

Stop here. Do not add Phase 6 development-workspace operations, repository mutation,
command execution, Git, privileged service/package control, hardware, or later-phase
capabilities to this document.