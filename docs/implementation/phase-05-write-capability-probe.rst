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

Persist one row per Phase 5 mutating operation:

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

The row is immutable after admission except for fields explicitly required by migration
compatibility. It is the durable relationship proving that the prepared nonce and caller
key were admitted as one logical operation; it is not a second lifecycle table.

11.2 ``probe_artifacts``
~~~~~~~~~~~~~~~~~~~~~~~~

Persist the probe-owned filesystem object:

* ``artifact_id`` PK, schema-compatible random identifier;
* ``relative_path`` UNIQUE NOT NULL;
* ``owner_controller_id`` / ``owner_controller_epoch``;
* ``content_sha256``;
* ``byte_count`` <= 65536;
* ``state`` enum ``reserved``/``created``/``removed``/``abandoned``/``uncertain``;
* ``create_operation_id`` UNIQUE FK to ``operations``;
* ``cleanup_operation_id`` nullable UNIQUE FK to ``operations``;
* ``created_at`` / ``updated_at`` / ``removed_at`` nullable as applicable;
* ``file_identity_digest`` nullable protected digest of stable local stat facts after a
  created file is verified.

The UNIQUE ``relative_path`` reservation means two live writes cannot claim one target.
A row is created as ``reserved`` before the write effect. It becomes ``created`` only
when reconciliation/receipt proves the exact published file. Pre-effect failure may mark
it ``abandoned``. Any conflicting on-disk state becomes ``uncertain`` and fail-closed for
that path; Binnacle never deletes a mismatch merely to repair the probe.

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
#. compute the current-state binding over root identity, target name, target-absent fact,
   and applicable durable reservation generation;
#. generate at least 128 random bits for ``execution_nonce`` and a separate random
   ``prepared_operation_id``;
#. compute the exact prepared normalized-input/request fingerprint;
#. register the nonce through Phase 4
   ``OperationStore.register_prepared_execution_nonce`` with Tool/contract/owner/device,
   expiry, current-state digest, boot identity, and trusted-time monotonic deadline;
#. append/fsync schema-valid bounded reservation/audit evidence using existing payload
   kinds; do not invent ``owner_confirmed`` audit state;
#. return the existing output schema.

Algorithm for ``operation=cleanup`` is identical except that it additionally requires a
retained ``probe_artifacts`` record owned by the current controller and exact
``artifact_id``/path/content digest. The current-state binding includes the retained
artifact generation and secure on-disk identity/digest when the file is present, or the
exact durable already-removed state when the prior cleanup has already succeeded.

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

One short SQLite write transaction performs:

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
   version-1 ``received`` operation, create the full caller-key binding pointing to that
   operation, attach the prepared binding to the same operation, and insert the immutable
   ``probe_operations`` relation;
#. for a write, atomically reserve the unique ``probe_artifacts.relative_path`` and mint
   ``artifact_id`` in that same admission transaction;
#. commit; only the newly admitted operation proceeds to policy/effect.

This transaction is the only first-admission path for Phase 5. A concurrent request cannot
consume one preparation twice or bind two caller keys to two operations.

Same caller key/input returns the retained operation. Same caller key/different input is
``idempotency_conflict``. Same preparation with a different new caller key after
consumption is also rejected without creating an alias/effect. ``uncertain`` never causes
a fresh call with a new key.

16. Local policy
----------------

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
* write target still absent and its durable reservation still belongs to this operation;
  or cleanup target/artifact still has the exact retained identity/digest/ownership;
* maximum effect remains one bounded local artifact;
* no cancellation/state-version change has occurred.

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
#. loads the retained ``probe_artifacts`` row and cleanup operation binding;
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

20. Effect reference and restart reconciliation
-----------------------------------------------

Every Phase 5 operation has durable operation-specific facts before effect:

* operation ID/state version;
* prepared/caller binding relationship;
* artifact ID;
* target path digest and expected content digest;
* ``probe_artifacts`` reservation/ownership.

``ProbeWorkspaceReconciler`` can therefore reconstruct a stable effect reference even if
``EffectBoundary.start`` crashed before returning its receipt.

For write reconciliation:

* exact final file present with matching artifact/content/reservation -> created, known
  logical effect, converge operation to ``succeeded`` if lifecycle permits;
* final absent and only an un-published staging file exists -> no final create effect;
  clean internal staging safely and converge through a truthful no-effect failure;
* final absent and no publication evidence -> no final create effect under the protected
  single-writer probe-root invariant;
* final present but mismatched/unowned -> ``uncertain``/fail restricted; never overwrite
  or delete it automatically.

For cleanup reconciliation:

* exact retained artifact absent after cleanup dispatch -> requested absence is established;
* exact retained artifact still present -> no delete effect is proven; do not auto-repeat;
* mismatched replacement/identity ambiguity -> ``uncertain``.

Reconciliation never creates a second effect and never changes idempotency identity.

21. Phase 4 audit-obligation and global-gate integration
--------------------------------------------------------

Phase 5 is not allowed to call the filesystem adapter directly from an MCP handler.
Every effect goes through the Phase 4 coordinator in this order:

::

   authenticated execute request
     -> dual prepared/caller idempotency admission
     -> one durable admission-policy decision
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

Required audit failure trips the global consequential gate exactly as Phase 4 specifies.
A surviving audit-obligation marker remains explicit-recovery-required across restart;
Phase 5 does not introduce an auto-clear exception for a "simple" file effect.

22. Audit mapping
-----------------

Use only existing schema-valid audit payload kinds.

Preparation may use existing policy/reservation evidence with ``operation_id=null`` and
``prepared_operation_id`` populated where schema permits. It must not claim an owner UI
confirmation occurred.

Execution uses the Phase 4 lifecycle/effect mappings, including:

* ``operation.state_changed``;
* ``policy.decision`` / ``operation.authorised``;
* ``effect.intent_recorded``;
* ``effect.started`` / ``effect.observed`` / ``effect.failed`` /
  ``effect.uncertain`` as truthful;
* recovery/cancellation payloads when applicable.

Record bounded digests for target path, content, maximum effect, artifact identity, Tool
manifest, profile/policy, and operation correlation. Raw file content, execution nonce,
idempotency key, credentials, and complete host-confirmation screenshots/transcripts are
not audit payload.

Host UI confirmation is evaluation evidence, not a server-verifiable authority fact.
Server audit may record the selected reviewed HOST-profile digest/status used for
promotion, but must not fabricate ``owner_confirmed=true``.

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
* ``operation_uncertain``.

Retry guidance must be truthful:

* retained same-key terminal -> same request may retrieve retained result;
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
write is not sufficient evidence for an ``observed-supported`` promotion.

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
* prepared nonce/caller key dual admission creates one operation/binding pair relation;
* same caller key/input returns retained operation;
* same caller key/different input rejects;
* consumed preparation plus new caller key cannot create another operation/effect;
* owner mismatch is non-disclosing;
* expired/trusted-time-unavailable preparation cannot admit an effect;
* target-state change between prepare/admission/final boundary suppresses effect;
* unique artifact path reservation holds under concurrency;
* cleanup never deletes mismatched/unowned content;
* no automatic retry from ``uncertain``;
* maximum file/effect bounds are invariant.

Hypothesis state-machine tests should combine preparation expiry, controller replacement,
idempotency collisions, artifact states, and crash/reconciliation transitions.

31. Integration and fault tests
-------------------------------

Use temporary local filesystem roots with the real Phase 4 kernel and a counted filesystem
adapter where fault injection is needed.

Required faults include:

* crash after prepared binding registration;
* concurrent first execute with same nonce/key;
* concurrent same nonce with different caller keys;
* crash after caller/prepared bindings + artifact reservation commit, before policy;
* policy deny;
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
* crash after unlink before receipt/DB update;
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
* dual caller/prepared binding relation remains intact;
* reserved/created/removed artifact rows reconstruct correctly;
* exact published file is reconciled after lost start receipt;
* stale private staging file never becomes a visible second artifact;
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
#. every effect has Phase 4 durable operation/idempotency state first;
#. prepared nonce and caller key converge on one operation and cannot create aliases that
   produce additional effects;
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
probe filename when classified normal-result by the test profile, digest prefixes,
byte counts, policy/boundary result codes, and reconciliation outcome.

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
#. add migration ``0002`` with ``probe_operations``/``probe_artifacts`` constraints;
#. implement preparation state binding and Phase 4 prepared-nonce registration;
#. implement dual prepared-nonce + caller-key transactional admission;
#. implement exact Bootstrap policy entries for write/cleanup;
#. implement secure root/staging adapter and filesystem capability verification;
#. implement Phase 5 final boundary verifier;
#. implement atomic create/no-overwrite effect and reconciler;
#. implement exact cleanup effect and reconciler;
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
* prepare is no-effect and binds exact input/current state/expiry;
* execute requires both prepared nonce and caller key and atomically binds both to one
  operation;
* exactly one durable artifact reservation precedes write effect;
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
#. dual nonce/key idempotency has one atomic one-operation admission design;
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
