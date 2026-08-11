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
  the exact cleanup that performed and durably established removal is classified;
* ``created_at`` / ``updated_at`` / ``removed_at`` nullable as applicable;
* ``file_identity_digest`` nullable protected digest of stable local stat facts after a
  created file is verified.

Do **not** place an unconditional UNIQUE constraint on ``relative_path`` because removed
or safely abandoned history must remain durable while the frozen evaluation reuses the
same synthetic filename across attempts. Migration ``0002`` does, however, enforce
``UNIQUE(relative_path, path_generation)`` across all retained generations and creates an
exact partial unique index equivalent to:

::

   CREATE UNIQUE INDEX uq_probe_artifacts_live_relative_path
       ON probe_artifacts(relative_path)
       WHERE state IN ('reserved', 'created', 'uncertain');

At most one live/uncertain generation can own a path. ``removed`` and proven-no-effect
``abandoned`` rows do not block a later independent write. A new write reservation
atomically chooses ``path_generation = max(retained generation for path) + 1`` (or 1 for
a never-seen path) while holding the short post-policy write transaction.

High-water alone is not a sufficient prepared-state commitment. Before a write preparation
may bind an absent path, every retained prior generation for that normalized path must be
in a terminal/stable historical state (``removed`` or a durably proven-no-effect
``abandoned`` state). ``reserved``, ``created``, ``uncertain``, integrity-invalid, or
otherwise legitimately mutable rows reject preparation rather than being hidden inside a
history digest.

For the stable prior rows, construct a deterministic retained-history commitment in
strict ascending ``path_generation`` order. Each canonical JCS record includes at least:

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
   active_cleanup_operation_id     # required NULL for terminal history
   removed_by_cleanup_operation_id
   created_at
   removed_at

The application treats those history-commitment fields as immutable once the row enters a
terminal historical state. It never silently repairs or rewrites a committed historical
row while an outstanding preparation exists. A reviewed migration or recovery repair that
must change any committed field necessarily invalidates outstanding preparations and
requires a new preparation before another filesystem start.

Preparation binds all three retained-history facts: generation high-water ``N`` (0 for a
never-seen path), exact ``retained_history_count=C``, and
``retained_history_sha256=H`` where ``H`` is SHA-256 of the canonical JCS array above (the
empty array has its deterministic canonical hash). A deletion changes ``C``/``H``; an
insertion changes ``C``/``H`` and usually ``N``; mutation/corruption changes ``H`` even
when the maximum generation remains ``N``. Reads or canonicalization that cannot prove the
complete stable set fail closed.

A row created by the current admitted write is not part of its prepared prior-history
commitment. Final verification recomputes ``N/C/H`` over all rows for the normalized path
**excluding only the exact current operation's self-owned reserved generation ``N+1``**.
No other row may be excluded. This gives the Phase 4 final prepared/current-state digest a
complete retained-history commitment instead of only a generation maximum.

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
``probe_operations``. A successful cleanup that actually unlinked the artifact may record
``removed_by_cleanup_operation_id``, move the artifact to ``removed``, and clear the
active claim only after durable ``known_effect`` classification for the exact cleanup plus
the applicable required post-effect audit/obligation closure. On-disk absence by itself
never authorizes that successful-removal transition.

There is one distinct no-effect absence closure: when the exact claimed artifact is
securely observed absent **before** ``EffectBoundary.start`` (or an explicit adapter
no-effect receipt proves no unlink was attempted after start), the current cleanup may be
terminalized with ``known_no_effect`` and, only after its required terminal/no-effect
audit and recovery closure, section 20 may move the artifact state to ``removed`` and
clear the active claim while leaving ``removed_by_cleanup_operation_id`` NULL. In this
path ``removed`` describes durable current absence, not a claim that this cleanup removed
the file. The retained operation/audit evidence carries the exact no-effect reason. An
``uncertain`` cleanup never releases or supersedes its active claim.

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

Cleanup normalized effect input contains exactly:

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
#. load the complete stable retained history for the path, prove it contains only terminal
   historical rows, and compute exact high-water ``N`` (0 if empty),
   ``retained_history_count=C``, and ``retained_history_sha256=H`` using section 11.2;
#. compute the current-state binding over root identity, target name, target-absent fact,
   ``prepared_path_generation_high_water=N``, ``retained_history_count=C``,
   ``retained_history_sha256=H``, and the deterministic semantic component
   ``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``;
#. generate at least 128 random bits for ``execution_nonce`` and a separate random
   ``prepared_operation_id``;
#. compute the exact prepared normalized-input/request fingerprint;
#. register the nonce through Phase 4
   ``OperationStore.register_prepared_execution_nonce`` with Tool/contract/owner/device,
   expiry, current-state digest, boot identity, and trusted-time monotonic deadline;
#. append/fsync schema-valid bounded preparation/audit evidence using existing payload
   kinds; do not invent ``owner_confirmed`` audit state or a filesystem reservation;
#. return the existing output schema.

For a write preparation, the phase-stable reservation component above represents exactly
one reviewed internal admission transition; it is not an omission of path ownership or
retained-history integrity:

* at preparation, pre-policy execute validation, and post-policy pre-insert admission
  revalidation, the component is valid only while secure lookup proves the target absent,
  the partial live-path index has no live row for that normalized path, every prior row is
  still terminal/stable, and retained history has exact ``N/C/H`` from the preparation;
* after policy allows the exact operation, section 16 may create exactly one ``reserved``
  artifact row owned by that same operation at generation ``N + 1``;
* at final OP-BOUNDARY revalidation, the same semantic component is valid only after
  proving the one live row is that exact operation's still-``reserved`` artifact,
  ``create_operation_id`` equals the exact current ``running`` operation, its generation
  is exactly ``N + 1``, root/path/content/owner/controller facts are unchanged,
  ``probe_operations.prepared_binding_id`` names the consumed prepared binding carrying
  the stored digest, and retained history **excluding only this exact self reservation**
  recomputes to exact high-water ``N``, count ``C``, and digest ``H``;
* a missing/foreign/changed reservation, generation other than ``N + 1``, a different
  prepared-binding relationship, any deleted/inserted/mutated/corrupt prior historical
  row, changed ``N/C/H``, target appearance, or any unrelated current-state change fails
  closed.

The write canonicalizer is deterministic from durable state and the exact operation/
prepared-binding relationship. It lets Phase 4 compare the exact same prepared/current-
state digest across only the expected absent/retained-history ``N/C/H`` -> exact-self
reserved ``N + 1`` transition. It never treats an arbitrary reservation as equivalent to
absence and does not itself authorize an effect.

Algorithm for ``operation=cleanup`` is identical except that it additionally requires a
retained ``probe_artifacts`` record owned by the current controller and exact
``artifact_id``/path/content digest. For a still-created artifact, preparation requires no
unresolved ``active_cleanup_operation_id``; a potentially releasable terminal claim must
first pass section 20 reconciliation, and preparation never steals or clears a claim.
Preparation then permits exactly two truthful filesystem observations for that exact
``created`` generation:

* **present** -- secure lookup proves the exact retained regular-file identity/content
  digest. The current-state binding carries that exact prepared file-identity digest plus
  the deterministic semantic component
  ``cleanup_target_transition=exact_prepared_identity_or_absent_no_start``. At preparation
  and admission this component is valid only while that exact file remains present;
* **observed absent** -- secure lookup through the protected root proves the exact target
  name is absent. The binding includes the exact ``artifact_id``, retained
  ``path_generation``, owner/controller epoch, expected content digest, root identity,
  normalized path, a typed ``created_target_observed_absent`` current-state fact instead
  of an on-disk file identity, and the phase-stable cleanup-claim component described
  below.

For a **present-bound** cleanup, the target-transition token is narrowly phase-aware:

* preparation, pre-policy execute validation, and post-policy admission accept it only
  while secure lookup proves the exact prepared regular-file identity/content still
  exists; disappearance before admission is stale and must be rejected/reprepared;
* at final OP-BOUNDARY, the callback may reproduce the same token either from the exact
  unchanged present identity **or** from secure absence, but the absence alternative is
  permitted only when the retained artifact/generation/owner/content/controller/root/path
  facts are unchanged, the active cleanup claim belongs to the exact current running
  operation, and that operation's immutable ``prepared_binding_id`` equals the consumed
  prepared binding that carried the exact prepared identity digest;
* if the final alternative is secure absence, the callback must return the typed
  ``already_missing_pre_start`` result together with the matching digest so the
  coordinator terminates through the no-start ``known_no_effect`` path before any audit-
  obligation publication or ``EffectBoundary.start``;
* a replacement object, changed/mismatched identity or digest, unverifiable absence,
  foreign/cleared claim, changed retained artifact fact, or mismatched prepared binding is
  never canonicalized and fails closed.

This target transition does not infer who or what removed the file, and it never produces
``known_effect``. It exists only to represent the exact state change from the prepared
file identity to secure absence while this admitted operation is still provably pre-start.
Post-dispatch absence after a lost receipt remains outside this transition and remains
``uncertain`` under sections 19--20.

For **either** still-created cleanup variant, the Phase 5 operation-specific current-state
canonicalizer includes the literal semantic component
``cleanup_claim_transition=unclaimed_then_exact_self`` instead of hashing the raw
``active_cleanup_operation_id`` value as a changing literal. This is a narrowly bounded,
phase-aware representation of the one internal reservation transition that policy
admission is expected to make; it is not an omission of cleanup-claim state:

* at preparation, pre-policy execute validation, and the pre-CAS admission revalidation,
  the component is valid only when the durable ``active_cleanup_operation_id`` is NULL;
* after policy allows the exact operation, the post-policy transaction may perform the
  one atomic CAS ``NULL -> current operation`` already specified in section 16;
* at final OP-BOUNDARY revalidation, the same canonical component is valid only when the
  durable claim equals the exact current ``running`` operation **and** that operation's
  immutable ``probe_operations.prepared_binding_id`` names the same consumed prepared
  binding whose stored current-state digest is being checked;
* a non-NULL claim before admission, a NULL claim at final verification, a claim owned by
  any other operation, or a missing/mismatched prepared-binding relationship is a current-
  state mismatch and fails closed;
* no other current-state fact is normalized across phases except the exact present-bound
  cleanup target transition defined above. Artifact state/generation/owner, root/path,
  content, controller epoch, and every fact outside those two reviewed transitions must
  still compare exactly.

The canonicalizer is deterministic from durable state and the exact operation/prepared-
binding relationship, so fresh-process recovery can reproduce it without an in-memory
whitelist. The self-claim normalization does not itself authorize an effect; it only keeps
Phase 4's exact prepared-current-state digest stable across the one reservation transition
that Phase 5 itself requires after an allow decision.

The observed-absent preparation fact is **not** effect knowledge, remover provenance, or a
state transition. Preparation leaves the artifact durably ``created``, does not set
``removed_at``, does not create/clear a cleanup claim, and does not claim that any cleanup
performed the disappearance. It merely binds the exact current absence so a later
independently authorised operation can revalidate that same state and, before any effect
boundary is crossed, use the truthful no-effect path in sections 17 and 20. Any mismatched
replacement, uncertain durable artifact state, active claim, or unsafe/unverifiable root
rejects preparation fail closed.

For an artifact already durably ``removed``, the current-state binding instead includes
the exact durable already-removed state. These present/created-observed-absent/removed
variants are distinct prepared-state digests and cannot substitute for one another after
preparation except that the exact present-bound target transition may become secure absent
at final pre-start verification under the predicates above.

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
#. commit; only the newly admitted ``received`` operation can continue toward the required
   received-state audit gate and, after that gate succeeds, policy evaluation.

This transaction intentionally does **not** insert ``probe_operations``, mint an
``artifact_id``, create a ``probe_artifacts`` row, or claim the path for a cleanup. Those
are post-policy admission/reservation facts under the merged Phase 4 ordering. Therefore a
policy-denied request, a required received-state audit failure, or a crash after durable
``received`` identity but before policy leaves no target reservation behind.

The transaction is the only first-identity path for Phase 5. A concurrent request cannot
consume one preparation twice or bind two caller keys to two operations.

Same caller key/input returns the retained operation. Same caller key/different input is
``idempotency_conflict``. Same preparation with a different new caller key after
consumption is also rejected without creating an alias/effect. ``uncertain`` never causes
a fresh call with a new key.

16. Local policy, mandatory audit gates, and post-policy reservation
-------------------------------------------------------------------

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

Phase 5 keeps the two mandatory Phase 4 pre-effect audit gates exactly; they are not
optional because the filesystem effect is small:

#. immediately after the minimal version-1 ``received`` operation is durably committed,
   append/fsync schema-valid ``operation.state_changed`` with ``old_state=null``,
   ``new_state=received``, ``state_version=1``, ``effect_knowledge=none``, and a bounded
   Phase-4-compatible reason such as ``operation_received``;
#. **only after that fsync succeeds** evaluate policy;
#. after an allowed policy decision and all operation-specific reservation facts have been
   durably committed together with ``received -> authorised``, append/fsync the required
   schema-valid ``policy.decision`` with ``decision=allowed`` plus
   ``operation.authorised`` evidence;
#. **only after those allowed/authorised audit records report successful fsync** may the
   coordinator transition ``authorised -> running``.

Failure of either required audit gate suppresses filesystem start and follows the merged
Phase 4 audit-failure/fail-restricted recovery semantics. A failed received-state audit
never evaluates policy or creates a probe reservation. A failed allowed/authorised audit
never transitions to ``running`` or reaches ``EffectBoundary.start``; the already-durable
``authorised`` state/reservation remains conservative recovery state and is not silently
replayed or converted into a fabricated terminal outcome merely to free a path.

Policy evaluation therefore occurs only after the required received-state audit fsync.
The post-policy admission behavior is exact:

* on policy deny, one short SQLite transaction persists the one durable deny decision and
  legal ``received -> rejected`` transition; it inserts no ``probe_operations`` row and
  creates/claims no artifact reservation. Before returning, append/fsync the required
  schema-valid ``policy.decision``/``operation.rejected`` and state-change audit evidence;
  required deny-audit failure enters the same Phase 4 fail-restricted recovery path and
  never authorizes an effect;
* on policy allow, one short SQLite write transaction revalidates the expected ``received``
  operation/version and current prepared state, inserts the one durable allow decision,
  inserts the immutable ``probe_operations`` row, and acquires the operation-specific
  reservation before the operation leaves ``received``;
* for a write, that transaction first re-proves the **pre-reservation** prepared state:
  secure target absence, no live-path row, all prior rows still terminal/stable, and exact
  retained ``N/C/H``. It must recompute the stored digest using
  ``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``
  before inserting anything. Only after that exact check may it allocate
  ``path_generation=N+1``, mint ``artifact_id``, and insert the one ``reserved``
  ``probe_artifacts`` row with ``create_operation_id`` equal to this operation under the
  partial live-path unique index and ``UNIQUE(relative_path, path_generation)``. No other
  generation, changed historical commitment, or pre-existing live row may be absorbed by
  the transition;
* for cleanup of a still-created artifact, it revalidates exact
  artifact/path/generation/ownership and the exact prepared filesystem observation. A
  present-bound preparation must still match the protected file identity/digest; a
  ``created_target_observed_absent`` preparation must still prove secure absence for the
  same root/path/generation. A present-bound disappearance **before admission** remains a
  stale preparation and is rejected; the present->absent no-start alternative is only a
  final OP-BOUNDARY state described in section 17. The phase-aware current-state
  canonicalizer must recompute the prepared digest in its pre-claim form while the durable
  active claim is still NULL. Only after that exact digest check does admission atomically
  compare-and-set ``active_cleanup_operation_id`` from NULL to this operation; an existing
  active claim is never stolen or overwritten. That successful CAS is the sole internal
  state transition represented by ``cleanup_claim_transition=unclaimed_then_exact_self``
  and does not authorize normalization of any other changed fact. Admitting the observed-
  absent variant does not mark the artifact removed and does not create effect knowledge --
  it merely gives the exact cleanup operation a claim so the final no-start verifier can
  close it truthfully if absence is still proven;
* for cleanup whose retained artifact is already durably ``removed``, the operation may
  be admitted as an idempotent no-effect establishment of the requested absent state and
  acquires no active cleanup claim or filesystem-start authority;
* only after those writes succeed does the same transaction commit the legal
  ``received -> authorised`` transition/version row;
* after the allow transaction commits, the required allowed ``policy.decision`` and
  ``operation.authorised`` audit evidence must fsync before any ``authorised -> running``
  transition.

The post-reservation/current state is therefore not a blanket exception to Phase 4
current-state binding. At final verification, the write reservation may canonicalize back
to its prepared token only for the exact operation that consumed the exact prepared
binding and only while retained history excluding that exact self reservation recomputes
to the exact prepared ``N/C/H``. Likewise, a cleanup claim may canonicalize back to the
same prepared claim token only for the exact operation that consumed the exact prepared
binding. Raw reservation/claim ownership and those durable relationships are checked
before digest comparison as section 17 defines.

If a prepared filesystem observation changes before admission -- including a file
appearing for an observed-absent cleanup preparation or a present-bound file disappearing,
being replaced, or changing identity -- the prepared current-state digest no longer
matches. The operation must not become authorised from that stale preparation. A new
preparation is required after truthful state observation; this rule never infers an effect
from the changed filesystem state.

If a concurrent operation wins the live-path reservation, acquires the active cleanup
claim, or changes the retained artifact before the allowing transaction commits, this
operation must not become authorised. The transaction records the already-evaluated
admission decision together with a legal ``received -> rejected`` outcome/reason that
truthfully reports reservation/state conflict, without creating a second policy decision
or a partial reservation, then emits the required rejected/audit evidence before return.
A transaction failure that prevents those durable facts from committing leaves the
operation ``received`` and Phase 4 restart recovery handles it fail closed.

An active cleanup claim is released only by the section 20 post-terminal/reconciliation
closure after a durably proven no-effect outcome or a correctly classified successful
removal. Policy admission itself never treats a terminal-looking operation as permission
to steal or clear that claim.

This preserves Phase 4's rule that pre-policy durability contains only minimal operation/
idempotency identity, required received audit precedes policy, post-policy admission/
reservation facts are durable before ``authorised``, and required allowed/authorised audit
precedes ``running`` and any filesystem effect.

17. Final OP-BOUNDARY verifier
------------------------------

The Phase 5 ``OperationBoundaryVerifier`` plugs into the mandatory Phase 4 all-mode final
revalidation path and runs while the per-operation ``DispatchHandoffGate`` and global
``ConsequentialBoundaryGate`` semantics remain authoritative.

For a write, the Phase 5 current-state callback is phase-aware **only** for the exact-self
write reservation component frozen in section 14. Before Phase 4 compares the current
digest with ``operation.prepared_current_state_digest``, the verifier must prove:

* the one live ``probe_artifacts`` row for the path is still ``reserved`` and has
  ``create_operation_id`` equal to the exact current ``running`` operation;
* its generation is exactly prepared high-water ``N + 1``;
* its artifact/path/content/owner/controller/root facts match the admitted operation;
* ``probe_operations.prepared_binding_id`` equals the consumed prepared binding carrying
  the stored digest;
* secure lookup proves the final target name remains absent; and
* the complete retained history for the path **excluding only this exact self
  reservation** is still terminal/stable and recomputes to the exact prepared high-water
  ``N``, ``retained_history_count=C``, and ``retained_history_sha256=H``.

Only then may the callback canonicalize that durable state as
``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``.
A foreign/missing/non-reserved row, changed generation, deleted/inserted/mutated/corrupt
prior generation (even one below the maximum), changed ``N/C/H``, target appearance,
prepared-binding mismatch, or any unrelated state change is a digest mismatch and blocks
start. The reservation is never omitted from the security state; it is represented by the
one reviewed phase-stable transition.

For a still-created cleanup, the Phase 5 current-state callback is phase-aware for exactly
two reviewed components: the cleanup-claim transition for both still-created variants,
and the present-bound cleanup-target transition where applicable. Immediately before
Phase 4 compares the current digest with ``operation.prepared_current_state_digest``, the
verifier must first prove that ``active_cleanup_operation_id`` equals the exact current
``running`` operation and that the immutable ``probe_operations.prepared_binding_id`` for
that operation equals the consumed prepared binding that carries the stored digest. Only
then may the callback canonicalize that exact self-owned claim as
``cleanup_claim_transition=unclaimed_then_exact_self``. A NULL claim at this stage, a
claim owned by any other operation, or a missing/mismatched prepared-binding relationship
is a digest mismatch and blocks start.

For a cleanup prepared against a **present** exact file, the callback then handles the
prepared target component deterministically:

* exact same regular-file identity/content still present -> canonicalize as
  ``cleanup_target_transition=exact_prepared_identity_or_absent_no_start`` and continue
  normal final verification;
* secure target absence -> canonicalize to that same target token **only** when retained
  artifact state/generation/owner/content/controller/root/path are unchanged and the exact
  self claim/prepared-binding checks above already passed; return a typed
  ``already_missing_pre_start`` result with the matching digest and stop before audit-
  obligation publication or ``EffectBoundary.start``;
* any replacement, identity/content mismatch, unsafe or unverifiable lookup, or any other
  changed state -> prepared-state mismatch/fail closed.

For a cleanup prepared with ``created_target_observed_absent``, absence must remain exact;
a later appearing file is never normalized into the present-bound transition and makes the
prepared state stale.

These operation-specific canonical forms preserve Phase 4's exact-digest rule. The write
digest computed while the path is absent with complete prior-history ``N/C/H`` and the
final digest computed with the exact self reservation at ``N + 1`` are identical only for
that reviewed transition and unchanged complete prior history. The cleanup digest computed
before admission while the claim is NULL and the final digest after the exact operation
has acquired its own claim are identical only for that reviewed transition; a present-
bound cleanup additionally permits the one exact secure present->absent pre-start target
transition. No transition hides unrelated state.

Immediately before ``EffectBoundary.start``, revalidate:

* current authenticated controller/profile/epoch and write-probe policy;
* Phase 4 kernel/audit/recovery health and open global consequential permit;
* exact ``running`` operation/state version;
* preparation expiry/trusted-time/current-state binding through the phase-aware rules
  above;
* probe-root identity and permissions;
* exact single-component target path;
* for write, target still absent and the exact self live reservation/generation/binding
  relation plus complete prior-history ``N/C/H`` satisfy the write transition; or for
  cleanup, the artifact still has the exact retained identity/digest/generation/ownership
  and self claim. A present-bound cleanup may instead produce the exact typed secure-
  absence no-start branch above. A cleanup prepared with
  ``created_target_observed_absent`` must still prove absence; no nonexistent file identity
  is fabricated;
* maximum effect remains one bounded local artifact;
* no cancellation/state-version change has occurred.

For a cleanup claim whose retained artifact is still ``created``, the final verifier has
one explicit no-start branch. If the exact prepared/current-state callback has truthfully
matched either (a) continued absence from a ``created_target_observed_absent`` preparation
or (b) the exact secure present->absent target transition from a present-bound preparation,
the verifier returns ``already_missing_pre_start`` rather than calling the adapter. Because
the coordinator knows the effect boundary has not been crossed for this admitted
operation, it may durably classify this operation as ``known_no_effect``. It must not
infer ``known_effect`` from absence, and neither preparation-time observation nor the final
present->absent transition claims who caused the disappearance.

The frozen lifecycle currently permits ``known_no_effect`` terminality for ``failed`` but
not for ``succeeded``. Phase 5 therefore does not mutate the lifecycle contract merely to
make this idempotent case look prettier: the durable operation transitions
``running -> failed`` with ``known_no_effect`` and a bounded internal reason/error such as
``cleanup_already_missing_before_start`` after the required no-effect terminal audit path,
while the MCP cleanup call may still return the existing schema-valid success data
``removed=false, already_missing=true``. The success envelope carries that retained
operation snapshot; the split is deliberate: the Tool request established its requested
absent state, while the admitted consequential operation performed no filesystem effect.
A separate lifecycle-contract PR would be required to introduce a terminal
``succeeded``/``known_no_effect`` combination.

A cleanup admitted against an artifact already durably ``removed`` follows the same
no-filesystem-effect result semantics and never acquires a cleanup claim. It does not
obtain or require a global start permit merely to re-prove absence.

Any other changed/unavailable predicate suppresses the filesystem effect. There is no
"best effort" path repair.

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

``LinuxProbeWorkspace.start_cleanup`` never accepts an arbitrary file. The coordinator
must not call it when the final OP-BOUNDARY verifier has already established the exact
``already_missing_pre_start`` no-effect branch from section 17.

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

There is a defensive race branch inside the adapter: after ``call_start`` has been
linearized but before unlink is attempted, the exact target may be observed absent. The
adapter must then perform **no unlink** and return an explicit no-effect receipt containing
only the exact operation/artifact/path-generation correlation and
``already_missing=true``. If that receipt is durably persisted/classified, the operation
is ``known_no_effect`` and may use the special no-effect absence closure in section 20.
If the receipt is lost, the caller sees only post-dispatch absence and Phase 4 requires
``uncertain``; absence alone cannot reconstruct this no-effect receipt.

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

For cleanup reconciliation and active-claim closure, keep three absence/no-effect cases
strictly separate:

* **pre-start or explicit-receipt no-effect absence:** if the exact cleanup has a durable
  terminal ``known_no_effect`` classification specifically because
  ``already_missing_pre_start`` proved the boundary was never crossed (including the exact
  present-bound secure present->absent transition), or because a durably retained adapter
  no-effect receipt proves no unlink was attempted, first finish the required terminal/no-
  effect audit and close any applicable audit/recovery state. Then one short idempotent
  compare-and-set must revalidate the exact artifact remains in durable ``created`` state,
  the same artifact/path generation/owner is still named, the active claim still equals
  this operation, secure lookup still proves the target absent, the operation's no-effect
  reason/receipt is exact, and audit/recovery health permits closure. Only then set artifact
  state ``removed``, set ``removed_at`` to the closure observation time, clear
  ``active_cleanup_operation_id``, and leave ``removed_by_cleanup_operation_id`` NULL. The
  row's ``removed`` state means durable current absence; it does not assert that this
  cleanup removed the file. Retained operation/audit evidence preserves the no-effect
  provenance. This closure is the only path that may release a created-artifact claim while
  the target is absent without ``known_effect``;
* **successful removal:** exact retained artifact absent after cleanup may record remover
  provenance only when the exact cleanup operation already has durable ``known_effect``
  classification for a recoverable effect reference bound to the same artifact/path
  generation and the applicable required post-effect audit has fsynced, its
  audit-obligation marker has been durably cleared, and any active recovery generation is
  closed. Then one short idempotent transaction may revalidate the exact operation/
  artifact/generation/active claim, set artifact state ``removed``, record
  ``removed_by_cleanup_operation_id=operation_id``, clear
  ``active_cleanup_operation_id``, and converge the lifecycle truthfully;
* **post-dispatch absence without proof:** exact retained artifact absent but the
  unlink/start or no-effect receipt/durable effect classification was lost, effect
  knowledge remains ``uncertain``, or required post-effect audit/obligation/recovery
  closure is incomplete -> absence is only an observation, not proof of either a durable
  successful cleanup or a proven no-effect cleanup. Do not set ``removed``, do not record
  remover provenance, and do not clear the active claim. Keep the operation/path fail
  restricted until an explicit Phase 4 recovery/reconciliation path independently and
  durably establishes truthful effect knowledge; filesystem absence alone can never
  perform that promotion;
* **known no-effect while artifact is still present:** do not auto-repeat. First durably
  finish the operation's terminal/no-effect audit path and close any applicable audit
  obligation. Then one short idempotent SQLite compare-and-set transaction must revalidate
  that the artifact is still the same ``created`` generation/identity, the active claim
  still names this exact operation, effect knowledge is still ``known_no_effect``, and
  audit/recovery health permits new consequential admission. Only then clear
  ``active_cleanup_operation_id`` without changing artifact state;
* the released cleanup operation and its ``probe_operations`` row remain immutable retained
  history. A later independent cleanup therefore uses a new preparation, caller key, and
  operation while targeting the same still-created artifact generation, or a later write
  may allocate a new generation after an exact absent-state closure moved the prior row to
  ``removed``;
* if the operation is ``uncertain``, the start receipt/effect boundary may have been lost,
  required audit/recovery closure is incomplete, or the on-disk artifact identity changed,
  keep the active claim and fail restricted. A later cleanup may not steal or supersede
  it;
* mismatched replacement/identity ambiguity -> ``uncertain`` with the active claim
  retained.

The successful-removal closure, pre-start/explicit-no-effect absence closure, and
still-present no-effect claim-release transaction are recovery/control state, not new
admission decisions. They are safe to retry after crash because they are conditional on
the exact retained operation, exact artifact generation/identity, exact active claim,
exact effect knowledge/no-effect reason or effect reference, filesystem observation, and
healthy audit/recovery state. A crash after operation terminalization but before any
closure therefore leaves a conservative claim that fresh-process reconciliation may clear
idempotently only after re-proving every predicate above.

Reconciliation never creates a second effect and never changes idempotency identity.
Historical ``removed``/``abandoned`` rows and every cleanup attempt remain retained so
path-generation high-water and operation history survive restart and repeated evaluation
attempts. The security-relevant fields of terminal historical artifact rows remain
immutable so the section 11.2 retained-history commitment remains reproducible.

21. Phase 4 audit-obligation and global-gate integration
--------------------------------------------------------

Phase 5 is not allowed to call the filesystem adapter directly from an MCP handler.
Every consequential execute follows the Phase 4 coordinator ordering, including both
mandatory pre-dispatch audit gates:

::

   authenticated execute request
     -> minimal dual prepared/caller identity + received operation
     -> fsynced operation.state_changed(null -> received)
     -> evaluate policy
     -> one durable admission-policy decision
     -> on deny: received -> rejected + required fsynced deny/rejected audit; stop
     -> on allow: post-policy probe operation + artifact/active-cleanup reservation
                  + received -> authorised in one durable transaction
     -> fsynced policy.decision(allowed) + operation.authorised
     -> authorised -> running
     -> fsynced effect.intent_recorded
     -> per-operation DispatchHandoffGate
     -> global ConsequentialBoundaryGate PRE_START permit
     -> final Phase 5 OP-BOUNDARY verifier
        -> write: exact self-reservation N+1 may canonicalize only to its prepared
           absent/complete-history N/C/H transition after all exact-self/binding/history
           checks, with all prior generations excluding self unchanged
        -> cleanup present-bound exact target may either remain exact-present or become
           the typed secure present->absent no-start transition
        -> if exact cleanup target is already missing pre-start:
           no EffectBoundary.start; durable known_no_effect terminal/audit path;
           section 20 no-effect absence closure after audit/recovery closure
        -> otherwise continue
     -> fsynced protected audit-obligation marker
     -> gate-owned call_start
     -> bounded write/cleanup effect
        -> explicit cleanup no-effect receipt if target vanished before unlink, or
        -> actual create/unlink effect receipt, or
        -> truthful failure/uncertainty
     -> immediate durable receipt/reference/effect-knowledge classification
     -> required post-effect/no-effect audit fsync
     -> obligation-marker removal + parent-dir fsync when a marker exists and Phase 4
        permits exact closure
     -> terminal result/reconciliation
     -> if cleanup is durably known-no-effect and the exact artifact is unchanged/present,
        idempotent active-claim release under section 20 predicates
     -> if cleanup is durably known-no-effect with exact proven absent-state provenance,
        idempotent no-effect absence closure under section 20 predicates
     -> if cleanup is durably known-effect and the exact artifact is absent,
        idempotent successful-removal closure under section 20 predicates

Required audit failure at the received-state or allowed/authorised gate suppresses all
later policy/dispatch work as applicable and enters the same Phase 4 fail-restricted audit
recovery path. Required ``effect.intent_recorded`` failure trips the global consequential
gate before any filesystem boundary as Phase 4 specifies. Phase 5 never skips an audit
stage because the effect is local or bounded.

A surviving audit-obligation marker remains explicit-recovery-required across restart;
Phase 5 does not introduce an auto-clear exception for a "simple" file effect. In
particular, a cleanup claim is not released while required audit/recovery state is failed
or incomplete merely to make another cleanup attempt possible.

22. Audit mapping
-----------------

Use only existing schema-valid audit payload kinds.

Preparation may use existing policy/preparation evidence with ``operation_id=null`` and
``prepared_operation_id`` populated where schema permits. It must not claim a filesystem
reservation or owner UI confirmation occurred before policy admission. A write preparation
may include only bounded digest/code facts for its absent/high-water ``N`` state, exact
``retained_history_count=C``/``retained_history_sha256=H``, and the phase-stable write-
reservation transition; it never emits the raw retained-history records and must not claim
the ``N+1`` reservation exists before admission. A cleanup preparation may include only
bounded digest/code facts for its exact prepared identity/target-transition or typed
``created_target_observed_absent`` fact; it must not emit effect/lifecycle evidence, set
effect knowledge, or claim removal merely because a target is or later becomes absent
before start.

Execution keeps the Phase 4 lifecycle/effect mapping and ordering exactly:

* after first durable operation identity, fsync ``operation.state_changed`` for
  ``null -> received`` before policy evaluation;
* after durable allow/``received -> authorised`` and reservation, fsync
  ``policy.decision(decision=allowed)`` plus ``operation.authorised`` before
  ``authorised -> running``;
* deny emits the required schema-valid ``policy.decision``/``operation.rejected`` and
  state-change evidence before return;
* ``effect.intent_recorded`` fsyncs after durable ``running`` and before the handoff/start
  path;
* ``effect.started`` / ``effect.observed`` / ``effect.failed`` /
  ``effect.uncertain`` are used only when truthful;
* recovery/cancellation payloads are used when applicable.

The pre-start ``already_missing`` path never emits ``effect.started`` and never claims
``known_effect``. Its terminal ``running -> failed``/``known_no_effect`` state change and
bounded reason are audited with existing schema-valid lifecycle/no-effect payloads. This
includes the exact present-bound secure present->absent transition; that transition is a
current-state fact, not evidence of a Binnacle effect. The adapter no-effect-receipt path
may record that the boundary was entered but no unlink was attempted only when that exact
receipt was durably obtained; if the receipt is lost, audit records uncertainty instead
of reconstructing no-effect from absence.

Record bounded digests for target path, path generation, retained-history count/digest,
content, maximum effect, artifact identity, Tool manifest, profile/policy, and operation
correlation. Raw retained-history rows, file content, execution nonce, idempotency key,
credentials, and complete host-confirmation screenshots/transcripts are not audit payload.

Host UI confirmation is evaluation evidence, not a server-verifiable authority fact.
Server audit may record the selected reviewed HOST-profile digest/status used for
promotion, but must not fabricate ``owner_confirmed=true``.

Clearing an ``active_cleanup_operation_id`` after a proven-no-effect terminal outcome does
not erase or replace audit evidence. The original cleanup operation, its policy/lifecycle/
effect evidence, and its ``probe_operations`` row remain retained; claim/absence closure
only records the exact durable filesystem state from which a later independently admitted
operation may proceed.

Likewise, an absent filesystem observation after dispatch is not an audit event that can
upgrade ``uncertain`` to ``known_effect`` or ``known_no_effect``. Successful-removal
closure requires already-durable exact-effect knowledge; no-effect absence closure
requires already-durable proof that this cleanup did not cross the effect boundary (or an
exact retained no-effect receipt). Both require the applicable audit/obligation/recovery
closure before the artifact claim is released.

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

For cleanup ``already_missing=true``, preserve the existing success output contract even
though the retained consequential-operation snapshot is ``failed``/``known_no_effect``
under the frozen lifecycle. The operation error/reason states that no filesystem effect
was performed because the exact target was already absent; it is not exposed as a claim
that cleanup failed to establish the requested absent state. This deliberate call-status
versus operation-effect distinction avoids changing either the Tool output schema or the
Phase 4 lifecycle inside Phase 5.

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

* schema/normalization rejection before operation creation;
* policy rejection after minimal ``received`` identity but before any probe reservation;
* required received/authorised audit failure and fail-restricted recovery;
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
* retained ``already_missing`` no-effect cleanup -> same-key retry returns the same
  schema-valid ``already_missing=true`` result and retained operation; it never starts a
  new effect;
* a cleanup that is durably ``known_no_effect`` does not silently reacquire its claim on
  same-key retry; after section 20 releases/closes the active claim, any later independent
  cleanup requires a new preparation/key/operation and normal policy admission;
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
* write preparation binds exact secure absence, retained high-water ``N``, exact
  ``retained_history_count=C``/``retained_history_sha256=H``, and
  ``write_reservation_transition=absent_generation_N_then_exact_self_reserved_generation_N_plus_1``;
  preparation itself creates no reservation and rejects any nonterminal/unstable prior
  history row;
* phase-aware write-reservation canonicalization produces the same current-state digest
  across only the expected absence/complete-history ``N/C/H`` -> exact consuming
  operation's ``reserved`` generation ``N+1`` admission transition; a foreign/missing/non-
  reserved row, wrong generation, changed target, changed ``N/C/H``, or missing/mismatched
  ``prepared_binding_id`` invalidates the binding;
* deleting or mutating a retained **non-maximum** historical generation while preserving
  maximum ``N`` necessarily changes ``C`` or ``H`` and causes final prepared-state
  mismatch/no start; inserting any extra historical row likewise changes ``C/H`` (and may
  also change ``N``) and cannot be hidden by the exact-self reservation exclusion;
* terminal retained-history commitment fields are immutable to normal runtime code;
  preparation fails closed if prior history is nonterminal, integrity-invalid, incomplete,
  or cannot be canonically read;
* cleanup preparation for a durable ``created`` artifact whose exact target is already
  absent succeeds only with the typed ``created_target_observed_absent`` binding over the
  exact artifact/generation/owner/content/root/path and the phase-stable cleanup-claim
  component; preparation does not mutate artifact state/claim or effect knowledge;
* present-bound cleanup preparation binds the exact prepared file identity plus
  ``cleanup_target_transition=exact_prepared_identity_or_absent_no_start``; admission
  requires that exact identity still present, while final verification may canonicalize
  only secure absence with all retained/self-claim/prepared-binding facts unchanged into
  the typed no-start result;
* phase-aware cleanup-claim canonicalization produces the same current-state digest across
  only the expected durable ``NULL -> exact consuming operation`` admission transition;
  a pre-admission non-NULL claim, final NULL/different claim, or missing/mismatched
  ``prepared_binding_id`` relationship invalidates the binding;
* a file appearing after observed-absent preparation, a replacement after present-bound
  preparation, or any artifact/generation/owner change invalidates prepared state rather
  than converting absence/presence into inferred effect knowledge;
* a present-bound exact file disappearing **after admission but before final boundary**
  reaches ``already_missing_pre_start`` with no audit-obligation marker/no boundary call,
  durable ``known_no_effect``, and no inferred remover/effect provenance;
* prepared nonce/caller key dual admission creates one minimal ``received`` operation
  before policy and no probe-path reservation;
* required ``operation.state_changed(null -> received)`` audit fsync occurs before policy;
  injected failure prevents policy/reservation/effect and enters Phase 4 fail-restricted
  recovery;
* policy deny leaves no ``probe_operations``/live artifact reservation and the path remains
  available for a later independent preparation after required deny audit closure;
* policy allow atomically persists operation-specific facts/reservation and
  ``received -> authorised``, then required allowed/authorised audit fsync occurs before
  ``authorised -> running``; injected audit failure cannot reach a filesystem start;
* same caller key/input returns retained operation;
* same caller key/different input rejects;
* consumed preparation plus new caller key cannot create another operation/effect;
* owner mismatch is non-disclosing;
* expired/trusted-time-unavailable preparation cannot admit an effect;
* target-state or path-generation/history-commitment change between prepare/admission/final
  boundary suppresses effect except for the two explicitly reviewed exact-self/no-start
  semantic transitions above;
* partial unique live-path reservation and ``UNIQUE(relative_path, path_generation)`` hold
  under concurrency while ``removed``/``abandoned`` historical rows do not block a new
  generation;
* stale preparation remains invalid after a create+cleanup cycle returns the target to
  absence because the retained path-generation/high-history commitment changed;
* at most one ``active_cleanup_operation_id`` may own a created artifact at a time;
* a terminal cleanup with durably proven ``known_no_effect`` plus unchanged exact artifact
  still present releases its active claim only after required audit/recovery closure,
  retains its operation history, and permits a later independently admitted cleanup;
* exact target absent at final pre-start verification -- including an absence bound during
  preparation and the exact present-bound disappearance transition -- produces no boundary
  call, durable ``known_no_effect``, schema-valid ``already_missing=true`` result, and only
  after terminal/no-effect audit/recovery closure may the exact CAS move the artifact to
  ``removed`` with NULL remover provenance and clear the active claim;
* an explicit adapter no-effect receipt for absence before unlink may use the same closure
  only after that receipt/effect classification is durable;
* cleanup absence with lost/missing start or no-effect receipt, ``uncertain`` effect
  knowledge, or incomplete required post-effect audit/obligation/recovery closure never
  records ``removed``/remover provenance and never clears the active claim; absence alone
  cannot promote the operation to ``known_effect`` or ``known_no_effect``;
* cleanup absence with exact durable ``known_effect`` plus matching recoverable effect
  reference and completed required audit/obligation/recovery closure may perform the
  idempotent successful-removal closure exactly once;
* an uncertain cleanup, audit/recovery-incomplete cleanup, or changed artifact never
  releases its active claim and therefore blocks a later cleanup from stealing authority;
* cleanup never deletes mismatched/unowned content;
* no automatic retry from ``uncertain``;
* maximum file/effect bounds are invariant.

Hypothesis state-machine tests should combine preparation expiry, controller replacement,
idempotency collisions, artifact states/generations, retained-history commitment changes,
active cleanup claims, mandatory audit gates, policy decisions, and crash/reconciliation
transitions.

31. Integration and fault tests
-------------------------------

Use temporary local filesystem roots with the real Phase 4 kernel and a counted filesystem
adapter where fault injection is needed.

Required faults include:

* crash after prepared binding registration;
* concurrent first execute with same nonce/key;
* concurrent same nonce with different caller keys;
* crash after minimal caller/prepared binding + ``received`` commit, before received audit
  or policy -> no ``probe_operations`` row/live artifact reservation;
* required received-state audit fsync failure -> no policy evaluation/reservation/effect and
  Phase 4 audit-failure recovery remains fail closed;
* policy deny -> no reservation and a later independent attempt can use the path only after
  required deny audit closure;
* concurrent policy-allowed writes for the same path -> exactly one live generation wins;
* admitted write exact self ``reserved`` generation ``N+1`` -> final verifier reconstructs
  the prepared absent/complete-history ``N/C/H`` digest through the write reservation
  token; deleting/rebinding/changing that row, changing retained history, or creating the
  target before final verification yields mismatch/no start;
* after preparation/admission, mutate or delete a retained **non-maximum** historical
  generation while keeping maximum generation ``N`` unchanged -> recomputed ``C/H`` differs
  and final OP-BOUNDARY returns prepared-state mismatch with zero filesystem start;
* after preparation/admission, insert or corrupt any prior-history row while preserving
  the self reservation -> recomputed ``C/H`` differs (or integrity/uniqueness validation
  fails) and final OP-BOUNDARY returns mismatch/no start;
* required allowed/authorised audit fsync failure after durable reservation/authorisation ->
  no ``authorised -> running`` and no filesystem start; retained reservation remains
  conservative until Phase 4 recovery resolves it;
* repeated write/cleanup cycles on frozen ``entitlement.txt`` -> retained ``removed``
  histories plus monotonically increasing generations, no uniqueness failure;
* stale prepared write after another complete create/cleanup cycle -> prepared-state
  mismatch despite target being absent again;
* crash after post-policy artifact reservation/authorisation before ``running``;
* crash after ``running``/intent audit before final verifier;
* exact self-owned cleanup claim acquired by admission -> final verifier reconstructs the
  prepared digest through the phase-stable claim component; clearing that claim or
  rebinding it to any other operation before final verification yields mismatch/no start;
* present-bound cleanup target disappears after admission but before final OP-BOUNDARY ->
  exact self claim/binding and unchanged retained facts permit only the typed secure
  present->absent no-start result; no audit-obligation marker or ``EffectBoundary.start``
  occurs and the operation reaches truthful ``known_no_effect`` closure;
* present-bound cleanup target is replaced or changes identity/content before final
  OP-BOUNDARY -> prepared-state mismatch, no no-start normalization, no delete;
* audit-obligation marker failure;
* target appears after prepare but before final boundary;
* staging create/write/fsync failure;
* crash after staging fsync before publish;
* no-replace publish finds target unexpectedly;
* crash after final publish/root-fsync before receipt;
* crash after publish before staging unlink;
* DB failure after created effect;
* required post-effect audit failure/latch failure paths inherited from Phase 4;
* cleanup target already absent **before cleanup preparation** -> preparation binds the
  exact created generation plus ``created_target_observed_absent`` without changing
  effect knowledge/state, admission acquires only the exact cleanup claim after re-proving
  absence, final verification performs no boundary call, and the retained operation reaches
  the same ``known_no_effect``/``already_missing=true`` closure only after required
  audit/recovery completion;
* cleanup target already absent before final filesystem start -> no boundary call, retained
  ``known_no_effect`` terminal operation, success data ``already_missing=true``, and exact
  no-effect absence closure only after required audit/recovery closure;
* cleanup target disappears after ``call_start`` but before unlink and explicit no-effect
  receipt is durably retained -> no unlink, known-no-effect closure is permitted;
* same adapter no-effect race with receipt loss -> ``uncertain`` and active claim retained;
* cleanup target digest/identity mismatch;
* cleanup intent-audit/final-verifier/adapter failure that is durably proven no-effect and
  target remains present -> active claim remains until terminal/no-effect audit closure,
  then releases and a later independent cleanup can be admitted without deleting failed-
  attempt history;
* crash after cleanup terminalization but before any active-claim/absence closure -> fresh-
  process reconciliation performs the exact applicable conditional closure idempotently;
* DB failure while releasing/closing a proven-no-effect cleanup claim -> claim remains
  conservative and later cleanup/path reuse stays blocked until reconciliation succeeds;
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
* a prepared write reconstructs exact high-water ``N``, retained-history count ``C`` and
  digest ``H``, plus the write reservation token; if already admitted, the exact self
  ``reserved`` row at ``N+1`` plus durable prepared-binding relation and complete history
  excluding self must recompute the same ``N/C/H`` and digest, while foreign/missing/
  changed reservation or any changed/deleted/inserted prior generation fails closed
  without in-memory state;
* a retained cleanup preparation with ``created_target_observed_absent`` reconstructs its
  exact no-effect-neutral current-state digest after restart; continued absence may proceed
  through normal admission/final verification, while reappearance or any generation/owner
  change invalidates the preparation without inferring an effect;
* a present-bound admitted cleanup reconstructs the exact prepared target-transition token
  from durable prepared identity/binding facts; exact present state may continue and exact
  secure absence before start may produce only ``already_missing_pre_start``, while a
  replacement/mismatch remains fail closed;
* an admitted still-created cleanup reconstructs the phase-stable claim component solely
  from durable exact ``operation_id``/``probe_operations.prepared_binding_id``/active-claim
  state; no in-memory exception is required, and a missing or foreign claim fails closed;
* dual caller/prepared binding relation remains intact even when no post-policy probe row
  exists for a rejected/interrupted pre-policy operation;
* a ``received`` operation whose required received audit never fsynced does not proceed to
  policy after restart without the exact Phase 4 audit/recovery rules being satisfied;
* an ``authorised`` operation whose required allow/authorised audit never fsynced does not
  proceed to ``running`` or filesystem start after restart;
* reserved/created/removed/abandoned artifact generations reconstruct correctly;
* path-generation high-water and the complete stable retained-history ``C/H`` survive
  restart; removed/proven-abandoned history does not block a later safe generation and is
  never silently rewritten to make an outstanding preparation pass;
* exact published file is reconciled after lost start receipt;
* stale private staging file never becomes a visible second artifact;
* a cleanup claim whose operation is durably terminal ``known_no_effect`` and whose target
  remains present is released only after the exact artifact/generation/identity and audit/
  recovery predicates are re-proven;
* a pre-start/explicit-receipt no-effect cleanup whose exact target is absent moves the
  artifact to ``removed`` and clears the claim only after re-proving exact no-effect
  provenance plus terminal audit/recovery closure; remover provenance remains NULL;
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
#. pre-policy durability is limited to Phase 4 operation/idempotency identity; policy deny,
   received-audit failure, or pre-policy crash creates no probe-path reservation;
#. required fsynced ``operation.state_changed(null -> received)`` precedes policy;
#. every allowed effect has one durable policy decision plus operation-specific reservation
   and ``received -> authorised`` before the required fsynced allowed
   ``policy.decision``/``operation.authorised`` evidence;
#. required allowed/authorised audit fsync precedes ``authorised -> running``; failure at
   either mandatory audit gate suppresses filesystem start and follows Phase 4 fail-closed
   recovery;
#. prepared nonce and caller key converge on one operation and cannot create aliases that
   produce additional effects;
#. write prepared/current-state binding normalizes only the reviewed absent/complete-
   history ``N/C/H`` -> exact consuming operation's self-owned ``reserved`` generation
   ``N+1`` transition. Pre-admission requires actual absence/no-live-row and exact stable
   prior-history ``N/C/H``; final verification requires the exact self row, exact prepared-
   binding relationship, unchanged target, and complete history excluding self with exact
   ``N/C/H``. Deleting, inserting, mutating, or corrupting any prior generation—including
   a non-maximum row that leaves ``N`` unchanged—is never normalized;
#. terminal historical artifact security/provenance fields used by the history commitment
   are immutable to normal runtime code; a nonterminal or unverifiable prior row blocks
   new write preparation rather than being omitted;
#. cleanup preparation may bind a secure current observation that the exact retained
   ``created`` generation is absent, but that observation is never effect knowledge,
   removal provenance, or permission to mutate durable artifact state before independent
   policy admission and final no-start verification;
#. a present-bound cleanup may normalize only the exact secure present->absent transition
   at final pre-start verification, after exact self-claim/prepared-binding and all retained
   artifact/controller/root/path facts are re-proven. The transition can produce only a
   no-start ``known_no_effect`` result; replacement/mismatch and all post-dispatch absence
   remain outside it;
#. cleanup prepared/current-state binding also normalizes only the reviewed admission-owned
   ``NULL -> exact self`` active-claim transition through one deterministic semantic token;
   every phase separately verifies raw claim ownership/prepared-binding relation as
   applicable, and no unrelated state change can be hidden by those canonicalizations;
#. live path uniqueness is state-aware; ``UNIQUE(relative_path, path_generation)`` plus
   retained history and path generations prevent stale preparation resurrection;
#. a created artifact has at most one active cleanup claim; policy admission never steals
   it, proven-no-effect closure preserves the operation history, and uncertain or audit/
   recovery-incomplete cleanup retains the claim fail-closed;
#. pre-start exact absence may be closed only as durable ``known_no_effect`` after exact
   no-effect audit/recovery predicates; it never creates remover provenance or
   ``known_effect``;
#. on-disk absence after cleanup dispatch is never sufficient to record successful removal
   or clear the active claim; exact durable ``known_effect`` plus matching effect reference
   and completed required post-effect audit/obligation/recovery closure are required, unless
   a separately durable exact no-effect receipt proves no unlink was attempted;
#. exact current state is revalidated immediately before the boundary;
#. Phase 4 per-operation cancellation handoff and process-wide consequential gate remain
   the only start path;
#. Phase 4 durable audit-obligation marker exists before any filesystem start;
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
probe filename when classified normal-result by the test profile, path generation,
retained-history count/digest prefix, digest prefixes, byte counts, policy/boundary result
codes, and reconciliation outcome.

Never log raw retained-history rows, content, execution nonce, caller key, credentials, raw
controller assertion, or full host transcript.

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
   ``UNIQUE(relative_path, path_generation)``, path-generation history, terminal-history
   immutability rules, state-aware active cleanup claims, successful-cleanup provenance,
   and ``probe_artifacts`` constraints;
#. implement deterministic retained-history canonicalization for write preparation:
   terminal/stable prior rows only, exact high-water ``N``, count ``C``, SHA-256 ``H`` over
   the full ordered immutable provenance/state record set, and fail-closed integrity reads;
#. implement preparation state binding -- including the exact write absent/complete-history
   ``N/C/H`` plus phase-stable self-reservation transition, the exact
   ``created_target_observed_absent`` cleanup variant, the present-bound
   ``exact_prepared_identity_or_absent_no_start`` target transition, and the phase-stable
   ``unclaimed_then_exact_self`` cleanup-claim component -- and Phase 4 prepared-nonce
   registration;
#. implement minimal dual prepared-nonce + caller-key pre-policy identity admission;
#. integrate mandatory fsynced ``operation.state_changed(null -> received)`` immediately
   after first durable identity and before any policy evaluation;
#. implement exact Bootstrap policy entries for write/cleanup;
#. implement post-policy ``probe_operations`` plus exact-self write/active-cleanup
   reservation, admission decision, pre-reservation write digest revalidation over exact
   ``N/C/H``, exact prepared-state revalidation for present/observed-absent cleanup
   variants, exact NULL-to-self cleanup-claim CAS, and ``received -> authorised``
   transaction;
#. integrate mandatory fsynced allowed ``policy.decision`` + ``operation.authorised``
   evidence before any ``authorised -> running`` transition;
#. implement secure root/staging adapter and filesystem capability verification;
#. implement Phase 5 final boundary verifier including exact prepared-binding/self-write-
   reservation canonical reconstruction with complete history-excluding-self ``N/C/H``,
   exact cleanup self-claim reconstruction, and the present-bound/observed-absent pre-start
   already-missing no-effect branches;
#. implement atomic create/no-overwrite effect and reconciler;
#. implement exact cleanup effect, explicit adapter no-effect receipt, receipt-aware
   successful-removal closure, special no-effect absence closure, state-aware still-present
   active-claim release, and reconciler;
#. integrate both effects through Phase 4 global/per-operation gates, audit obligations,
   lifecycle, audit, and retained result semantics;
#. bind existing MCP handlers without changing manifest/schema contracts;
#. add unit/property/integration/fault/restart/systemd tests, including non-maximum retained-
   history mutation/deletion with unchanged maximum ``N`` -> mismatch/no start;
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
* write prepared/current-state binding survives only the expected exact-self reservation
  transition from absent/complete prior-history ``N/C/H`` to the exact consuming
  operation's ``reserved`` ``N+1`` row; final verification re-proves exact binding relation
  and recomputes complete history excluding self to exact ``N/C/H``;
* any deletion/insertion/mutation/corruption of a prior retained generation—including a
  non-maximum row that leaves maximum ``N`` unchanged—changes the history commitment or
  fails integrity validation and suppresses start; nonterminal history rejects preparation;
* cleanup preparation can truthfully bind an exact retained ``created`` generation plus
  secure observed absence without requiring an on-disk identity and without creating
  effect knowledge, remover provenance, or an artifact-state transition;
* present-bound cleanup binds exact prepared file identity and may accept secure absence
  only at final pre-start verification through the exact typed target transition, with
  unchanged retained/self-claim/prepared-binding facts; replacement/mismatch and
  post-dispatch absence never use that transition;
* still-created cleanup current-state binding remains stable across only the expected
  admission-owned ``NULL -> exact self`` claim transition: preparation/admission require
  NULL, final verification requires the exact self claim plus the exact immutable
  prepared-binding relationship, and all unrelated state remains exact;
* execute requires both prepared nonce and caller key and atomically binds both to one
  minimal pre-policy operation;
* required received-state audit fsync precedes policy and required allowed/authorised audit
  fsync precedes ``running``; audit failure cannot reach filesystem start;
* policy deny/pre-policy crash leaves no probe-path reservation;
* exactly one state-aware durable artifact/active-cleanup reservation is acquired only
  after policy allow and before ``authorised``/filesystem effect;
* removed/proven-abandoned historical rows can coexist with a later live generation and
  stale preparation cannot revive after an intervening path generation;
* a proven-no-effect cleanup whose artifact remains present can release only its exact
  active claim after terminal audit/recovery closure, while its operation history remains
  retained and uncertainty never permits claim supersession;
* exact pre-start absence closes as ``known_no_effect`` without a filesystem boundary,
  including both preparation-bound absence and the exact present-bound disappearance
  transition; it never becomes ``known_effect`` merely from absence, and only after
  terminal/no-effect audit/recovery closure may the exact claim be closed and artifact
  state become ``removed`` with NULL remover provenance;
* cleanup absence after dispatch records successful removal/clears the claim only with
  exact durable ``known_effect``, matching recoverable effect reference, and completed
  required post-effect audit/obligation/recovery closure; lost receipt/uncertainty keeps
  the claim unless an exact durable no-effect receipt independently proves no unlink;
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
#. write prepared/current-state digests remain exact while permitting only the one
   deterministic absent/complete-history ``N/C/H`` -> exact consuming operation's
   ``reserved`` generation ``N+1`` transition via a phase-stable semantic component;
   target presence, foreign/missing reservation, any changed prior-history ``C/H`` or
   generation, or binding mismatch fails closed—even when a non-maximum mutation leaves
   high-water ``N`` unchanged;
#. retained historical artifact generations used by write preparation are terminal/stable,
   canonically ordered and committed by exact count/hash; normal runtime cannot mutate the
   commitment fields after terminalization, and unverifiable/nonterminal history blocks
   preparation;
#. cleanup preparation supports exact created-but-observed-absent current-state binding
   without requiring a nonexistent file identity and without mutating durable artifact or
   effect state;
#. present-bound cleanup prepared/current-state digests permit only the exact secure
   present->absent-before-start target transition at final OP-BOUNDARY after exact retained
   and self-claim/prepared-binding revalidation; replacement/mismatch or post-dispatch
   absence cannot be normalized;
#. cleanup prepared/current-state digests remain exact while permitting only the one
   deterministic post-policy ``NULL -> exact consuming operation`` claim transition via a
   phase-stable semantic component; foreign/missing claims or binding relationships fail
   closed and no other current-state fact is normalized;
#. required ``received`` audit precedes policy and required allowed/authorised audit
   precedes ``running``; failure of either gate cannot reach filesystem start;
#. policy deny/pre-policy crash cannot strand a probe-path reservation;
#. state-aware live-path uniqueness, unique path generations, and retained complete-history
   commitments allow repeated frozen-case attempts without deleting history or reviving
   stale preparations;
#. state-aware cleanup claiming permits a later independent cleanup only after the prior
   claim is durably proven no-effect and safely released/closed, while uncertain claims
   remain fail-closed and all cleanup-attempt history is retained;
#. pre-start already-missing closure is representable without fabricating an effect:
   durable ``known_no_effect``, no boundary call/remover provenance, exact terminal audit/
   recovery closure, then conditional artifact ``removed``/claim closure; preparation-time
   or present->absent-before-start absence is only a bound current-state fact until the
   admitted operation reaches this no-start decision;
#. cleanup removal/claim release after post-dispatch observed absence requires exact durable
   ``known_effect`` plus matching effect reference and completed required post-effect
   audit/obligation/recovery closure, or an exact independently durable no-effect receipt;
   lost receipt/uncertainty cannot infer either effect class from absence;
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
#. automated tests prove exact-self write reservation canonicalization preserves the exact
   prepared digest only across absent/complete-history ``N/C/H`` -> consuming operation's
   reserved ``N+1`` transition, while foreign/missing/changed reservations, target
   appearance, any deleted/inserted/mutated/corrupt prior generation, changed ``N/C/H``, or
   prepared-binding mismatch suppresses final start;
#. automated tests explicitly mutate/delete a non-maximum prior generation while maximum
   ``N`` remains unchanged and prove the recomputed count/hash mismatches with zero
   filesystem start; insertion/corruption and fresh-process reconstruction receive the same
   fail-closed coverage;
#. automated tests prove cleanup preparation can bind exact secure absence for a retained
   ``created`` generation without fabricating identity/effect knowledge, and any state
   change before admission invalidates that preparation fail closed;
#. automated tests prove a present-bound cleanup that disappears only after admission but
   before final start can reach the typed no-start ``known_no_effect`` result only with
   exact retained/self-claim/prepared-binding revalidation; replacement/mismatch and
   post-dispatch absence remain fail closed/uncertain;
#. automated tests prove the prepared cleanup digest survives exactly the expected
   admission-owned NULL-to-self claim CAS, while a foreign/cleared claim or mismatched
   durable prepared-binding relation suppresses final start;
#. automated tests prove both mandatory Phase 4 audit gates suppress policy/dispatch or
   running/start exactly when their required fsync fails;
#. automated tests prove known-no-effect cleanup claims release/close only after durable
   terminal audit/recovery closure, while uncertain/incomplete claims remain non-stealable
   across restart;
#. automated tests prove pre-start exact absence becomes only ``known_no_effect`` and can
   produce the existing ``already_missing=true`` Tool result without calling the effect
   boundary or creating remover provenance;
#. automated tests prove an absent cleanup target cannot be promoted to successful
   ``known_effect`` removal after a lost receipt/unknown effect outcome; exact durable
   ``known_effect`` plus matching effect reference and completed required post-effect
   audit/obligation/recovery closure are required before remover provenance/path reuse,
   unless an exact durable no-effect receipt proves no unlink was attempted;
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