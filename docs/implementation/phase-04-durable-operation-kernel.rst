Binnacle Phase 4 Detailed Implementation Plan
=============================================

:Phase: 4 -- Add the durable consequential-operation kernel
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Planning status: provisional -- internal kernel design is concrete; host-facing projection remains evidence-gated
:Depends on: merged Phase 3 Raspberry Pi/ChatGPT validation plan; actual Phase 3 evidence before any host-facing operation projection
:Primary objective: Establish durable operation, idempotency, audit, policy, payload, trusted-time, boundary-revalidation, and reconciliation foundations before any Binnacle capability is permitted to mutate local state
:Implementation scope: internal operation kernel, SQLite/SQLAlchemy/Alembic persistence, append-only integrity-linked audit, minimal PolicyEngine boundary, trusted-time and final consequential-boundary guards, retained payload/evidence storage, local operator diagnostics, deployment-state permissions, tests, and CI only

Purpose
-------

Phase 4 creates the reliability and security kernel that every later consequential
Binnacle capability must use. It does **not** add a write Tool and it does not execute a
real device mutation. It proves that durable intent exists before an effect boundary,
duplicate logical requests reconcile to one retained operation, authority and freshness
are revalidated immediately before every consequential boundary, trusted-time failures
cannot extend preparation deadlines, an effect-dispatch crash cannot be misclassified as
``known_no_effect``, uncertain outcomes cannot be blindly repeated, lifecycle state
survives application restart, and required audit failure blocks new consequential work.

The kernel owns generic operation semantics, not workspace, executor, Git, package,
service, privileged, or hardware effect logic. Production composition in Phase 4 contains
no effect-capable adapter.

``docs/implementation/index.rst`` marks Phase 4 ``provisional`` because host-facing
projection depends on real Phase 3 ChatGPT evidence. This plan freezes the owner-approved
**internal** boundaries while refusing to invent or promote MCP operation/status/cancel/
result Tools, host retry assumptions, confirmation behavior, or host-specific result
limits without that evidence.

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
#. merged ``docs/implementation/phase-01-project-skeleton.rst``;
#. merged ``docs/implementation/phase-02-readonly-mcp-server.rst``;
#. merged ``docs/implementation/phase-03-pi-chatgpt-validation.rst``;
#. this detailed Phase 4 plan;
#. ``docs/operation-idempotency.md``;
#. ``spec/operation/idempotency.yaml``;
#. ``spec/operation/lifecycle.yaml``;
#. operation lifecycle/idempotency fixtures;
#. ``docs/audit-evidence.md``;
#. ``spec/audit/audit-policy.yaml``;
#. ``schemas/audit/audit-event.schema.json`` and audit fixtures;
#. ``docs/mcp-host-confirmation.md`` for preparation/current-state semantics;
#. ``docs/mcp-schemas.md`` and ``schemas/mcp/binnacle-common.schema.json`` for canonical
   operation snapshot vocabulary;
#. ``docs/mcp-large-results.md`` and ``spec/mcp/result-limits.yaml`` where retained
   payload semantics constrain internal storage;
#. ``docs/security/controller-transport.md`` for controller ownership/trust semantics;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

Machine-readable lifecycle, idempotency, audit, and schema contracts constrain the
implementation. They do not expand Phase 4 into later operational capabilities.

2. Provisional and evidence gate
--------------------------------

2.1 Concrete now
~~~~~~~~~~~~~~~~

The following internal architecture is concrete in Phase 4:

* the main Binnacle application is the sole authoritative SQLite writer;
* SQLAlchemy 2.x async APIs, ``aiosqlite``, and Alembic;
* WAL, ``synchronous=FULL``, foreign keys, and bounded busy timeout;
* durable operation and idempotency identity before an effect;
* exact lifecycle states and transitions from ``spec/operation/lifecycle.yaml``;
* two-level global duplicate prevention and controller ownership;
* durable preparation expiry/current-state bindings for the reviewed prepared-nonce
  contract seam;
* trusted wall-time, same-boot monotonic ordering, boot identity, and durable ordering
  sufficient to prevent rollback/reboot from extending preparation deadlines;
* a mandatory final consequential-boundary revalidation step for every operation mode;
* filesystem retained payloads with SQLite authoritative metadata;
* append-only RFC 8785 JCS + SHA-256 audit hash chaining;
* audit-before-effect gating and fail-restricted audit failure behavior;
* a small replaceable ``PolicyEngine`` boundary with fail-closed Bootstrap policy;
* a durable dispatch-attempt state before invoking any future effect boundary;
* restart reconciliation that prefers uncertainty over an unprovable no-effect claim;
* no automatic retry of ``uncertain`` work.

2.2 Evidence-gated and absent here
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Until actual Phase 3 evidence exists and the relevant host-facing contracts are reviewed,
Phase 4 does not freeze or expose:

* MCP ``operation_get``, ``operation_cancel``, result retrieval, or status Tool names;
* MCP Task or Resource adaptation;
* host retry/confirmation semantics;
* host-visible retained-result page/chunk sizes below repository storage ceilings;
* write/modify entitlement;
* controller scopes for future mutation classes;
* operation annotations or manifest entries;
* workspace/executor/Git/privileged/hardware operation contracts.

Internal application APIs may use ``get_operation``, ``request_cancel``, and result-read
semantics. An MCP projection for them is absent in Phase 4.

3. Roadmap exit gate
--------------------

Phase 4 implementation is complete only when tests prove all of the following:

* the configured SQLite DB is explicitly migrated to the expected Alembic head;
* every live SQLite connection verifies the required durability pragmas;
* operation/idempotency state survives a fresh-process restart;
* the global idempotency record and version-1 ``received`` operation are durable before
  any synthetic effect can be dispatched;
* concurrent first use of the same key creates exactly one binding and operation;
* full-record retry, conflict, owner-mismatch, uncertainty, terminal, and tombstone
  outcomes exactly match ``spec/operation/idempotency.yaml``;
* an unconsumed ``prepared_execution_nonce`` durably retains its prepared operation/input,
  expiry, exact current-state binding, registration boot identity, and same-boot monotonic
  deadline evidence before any new operation can be admitted;
* prepared-nonce expiry and prepared input/current-state mismatch remain enforceable after
  a fresh-process restart, returning ``prepared_operation_expired`` or
  ``prepared_operation_mismatch`` before operation creation;
* wall-clock rollback, reboot with untrusted time, or loss of trusted wall time cannot
  extend a prepared nonce lifetime; the kernel fails closed without operation/effect when
  expiry cannot be proven safely;
* a newly admitted prepared operation revalidates preparation expiry and exact current
  state immediately before the consequential boundary, and stale/expired preparation
  suppresses dispatch with a proven no-effect terminal outcome;
* every operation mode performs final OP-BOUNDARY revalidation immediately before
  ``EffectBoundary.start``, including applicable controller/device trust, policy/profile,
  state/version, freshness/target, cancellation/supervision, reservation, privilege/
  credential delegation, interlock, and recovery predicates;
* a final-boundary authority/state failure cannot call the effect adapter or overwrite a
  concurrently changed lifecycle state;
* ``derived_member_key`` is rejected before binding/operation creation in Phase 4 because
  no reviewed parent contract/derivation is registered yet;
* tombstones retain the contract-required non-reversible owner digest and terminal class;
* raw idempotency keys are never persisted, logged, audited, or used as metric labels;
* lifecycle transitions reject every undeclared edge/cross-field combination;
* ``state_version`` starts at 1 and strictly increases exactly once per real transition;
* stale optimistic updates cannot silently overwrite newer state;
* an operation is durably ``running`` before ``EffectBoundary.start`` is invoked;
* required ``effect.intent_recorded`` audit failure before dispatch terminalizes the
  already-running operation as a proven no-effect failure when SQLite is still writable;
* if that terminalization cannot itself be durably committed, no boundary is called and
  restart remains conservative rather than inventing a no-effect proof;
* a crash during dispatch before a receipt can never later be asserted as
  ``known_no_effect``;
* ``uncertain`` is never automatically retried;
* restart reconciliation distinguishes pre-dispatch ``authorised`` work from
  dispatch-attempted ``running`` work;
* effect references returned by a future adapter are durably recoverable, not digest-only;
* required audit records are schema-valid, canonicalized, chained, fsynced, and verified;
* audit payloads use exact existing ``payload.kind`` discriminators;
* audit corruption, truncation, fork, or storage failure blocks new effects;
* bounded recovery/status/verification remains possible where underlying stores remain
  trustworthy;
* retained payload metadata cannot disagree silently with filesystem bytes;
* payload writes are atomic/finalized or explicitly incomplete;
* Bootstrap policy is fail-closed and durably correlated with the operation;
* systemd hardening still permits only the new declared state/result/audit write paths;
* migration cannot run concurrently with the live authoritative DB writer;
* no production adapter performs a real consequential effect;
* no new host-facing MCP Tool/Resource/Task/Prompt is registered;
* exact-head GitHub Actions passes all normal gates.

4. Explicit non-goals
---------------------

Phase 4 does **not** implement:

* any workspace read/write Tool or disposable write probe;
* real write-entitlement or host-confirmation testing;
* command execution or an execution supervisor;
* executor or privileged-broker IPC;
* Git operations;
* package-manager operations;
* service restart or self-management;
* root/privileged operation vocabulary;
* hardware operations;
* production owner-transfer/recovery UI;
* MCP Tasks, Resources, Prompts, MRTR, or new MCP Tools;
* a general long-term policy language/engine;
* a time-synchronization daemon or clock-repair mechanism;
* external audit checkpoint publication or anchoring;
* DB replication/HA, PostgreSQL, network DBs, or distributed locks;
* multiple authoritative application writers;
* production backup orchestration;
* broad automatic destructive retention/purge;
* Phase 5 design.

Test doubles may cross a synthetic effect boundary to prove idempotency and reconciliation.
They are test-only and cannot be reachable from the production MCP catalogue or CLI.

5. Before and after semantics
----------------------------

Before Phase 4, Binnacle has the authenticated read-only Phase 3 architecture but no
authoritative operation DB, durable idempotency record, general lifecycle store, retained
result store, trusted consequential-deadline guard, final boundary-revalidation service,
or append-only local audit journal.

After Phase 4, later operation-specific use cases can call an internal kernel with this
ordering:

::

   authenticated/validated request
      -> canonical effect-bearing fingerprint + safe idempotency digest
      -> atomically create/find global binding and version-1 received operation
      -> schema-valid received audit
      -> evaluate and durably persist policy decision
      -> durable received -> authorised transition
      -> fsynced policy/authorization audit
      -> durable authorised -> running dispatch marker
      -> fsynced effect.intent_recorded audit
      -> final OP-BOUNDARY revalidation for every operation mode
           -> trusted-time/deadline guard where applicable
           -> prepared expiry/current-state guard where applicable
           -> current controller/device trust, policy/profile, lifecycle/cancellation,
              target/freshness/reservation/recovery checks where applicable
      -> effect boundary port (test-only in Phase 4; real adapters later)
      -> persist returned reference/effect knowledge/result metadata
      -> append/fsync effect/lifecycle audit
      -> reconcile/recover truthfully after restart

The kernel is ready to support future effects but grants none by itself.

6. Exact repository changes
---------------------------

The Phase 4 **implementation** is expected to create or modify these paths. This planning
PR itself adds only this document.

6.1 Existing project, deployment, and application files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Modify as required:

::

   pyproject.toml
   uv.lock
   .gitignore
   .github/workflows/python.yml
   src/binnacle/application.py
   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/cli.py
   deploy/systemd/binnacle-dev.service
   scripts/setup_dev_pi.py
   docs/operations/development-pi.rst

Do not alter the five Phase 3 MCP Tool contracts/manifest solely to expose the kernel.

6.2 Domain, application, and port modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/domain/operation.py
   src/binnacle/domain/idempotency.py
   src/binnacle/domain/policy.py
   src/binnacle/domain/audit.py
   src/binnacle/domain/payload.py
   src/binnacle/domain/trusted_time.py
   src/binnacle/ports/operation_store.py
   src/binnacle/ports/policy.py
   src/binnacle/ports/audit.py
   src/binnacle/ports/payload.py
   src/binnacle/ports/effect.py
   src/binnacle/ports/trusted_time.py
   src/binnacle/ports/boundary.py
   src/binnacle/application/operations.py
   src/binnacle/application/reconciliation.py
   src/binnacle/application/kernel_health.py
   src/binnacle/application/boundary.py

If earlier phases still use ``src/binnacle/application.py`` as a module, implementation
may use repository-consistent top-level modules instead of converting it to a package.
There must be one canonical ownership path, not parallel APIs.

6.3 Persistence modules
~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/adapters/sqlite/
     __init__.py
     engine.py
     models.py
     operation_store.py
     migrations.py
     health.py
   alembic.ini
   migrations/
     env.py
     script.py.mako
     versions/
       0001_durable_operation_kernel.py

Alembic owns schema evolution. Runtime code never opportunistically calls
``metadata.create_all()`` outside isolated tests.

6.4 Audit, payload, policy, and trusted-time adapters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/adapters/audit/
     __init__.py
     journal.py
     canonical.py
     verify.py
   src/binnacle/adapters/payload/
     __init__.py
     filesystem.py
     verify.py
   src/binnacle/adapters/policy/
     __init__.py
     bootstrap.py
   src/binnacle/adapters/linux/
     trusted_time.py

The trusted-time adapter consumes fixed Linux/OS time and boot-ordering facts. It does not
set the clock, invoke a general shell, or silently mark time trustworthy when the selected
OS trust signal is unavailable.

6.5 Local verification and tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create/update at least:

::

   scripts/verify_operation_kernel.py
   tests/unit/test_operation_domain.py
   tests/unit/test_idempotency_domain.py
   tests/unit/test_policy_domain.py
   tests/unit/test_audit_domain.py
   tests/unit/test_payload_domain.py
   tests/unit/test_trusted_time.py
   tests/unit/test_boundary_revalidation.py
   tests/unit/test_bootstrap_policy.py
   tests/unit/test_audit_journal.py
   tests/unit/test_payload_store.py
   tests/integration/test_sqlite_operation_store.py
   tests/integration/test_idempotency_concurrency.py
   tests/integration/test_operation_restart_reconciliation.py
   tests/integration/test_audit_failure_gate.py
   tests/integration/test_boundary_revalidation.py
   tests/integration/test_trusted_time_restart.py
   tests/integration/test_payload_integrity.py
   tests/integration/test_alembic_migrations.py
   tests/integration/test_phase4_systemd_state_permissions.py
   tests/property/test_operation_lifecycle_properties.py
   tests/property/test_idempotency_properties.py

Reuse existing lifecycle/idempotency/audit fixtures and status vocabulary.

7. Direct dependencies
----------------------

7.1 Runtime
~~~~~~~~~~~

Add:

* SQLAlchemy 2.x;
* ``aiosqlite``;
* Alembic;
* one maintained RFC 8785 JSON Canonicalization Scheme implementation verified against
  repository audit fixtures and Python 3.11/3.12/3.13.

Do not implement a partial home-grown JCS encoder and do not substitute
``json.dumps(sort_keys=True)``.

No database server/client, Redis, distributed-lock package, second ORM, general policy
engine, or third-party time service SDK is introduced.

7.2 Development and lock discipline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reuse pytest, AnyIO, Hypothesis, coverage, tox, and existing quality tools. Hypothesis is
required for lifecycle/idempotency/state-version/trusted-time invariants.

Exact versions remain in ``uv.lock``. CI keeps frozen sync and explicit interpreter
selection established by prior phases.

8. Runtime state layout and systemd write authority
---------------------------------------------------

Use:

::

   /var/lib/binnacle/
     state/
       binnacle.db
       checkpoints/
     results/
       objects/
       streams/
       tmp/
     audit/
       epochs/
       emergency/
     evaluation/
       ... Phase 3 evidence remains separate ...

``/etc/binnacle`` remains protected configuration/policy; ``/run/binnacle`` remains
runtime/ephemeral control state; source remains under ``/srv/binnacle-dev/repo``.

``scripts/setup_dev_pi.py`` must idempotently create the new ``state``, ``results``, and
``audit`` subtrees with the dedicated ``binnacle`` application identity as owner and
modes no broader than required for that identity. Evaluation evidence ownership from
Phase 3 is not broadened.

Phase 3 uses ``ProtectSystem=strict``. Therefore Phase 4 must explicitly update
``binnacle-dev.service`` so the service can write **only** the new declared paths. Prefer
narrow ``ReadWritePaths=`` entries for:

::

   /var/lib/binnacle/state
   /var/lib/binnacle/results
   /var/lib/binnacle/audit

rather than making all of ``/var/lib`` or all of ``/var/lib/binnacle`` writable. Do not
weaken ``NoNewPrivileges``, capability bounds, protected config permissions, or source
checkout separation merely to make persistence work.

Reusable credentials are not stored under DB/result/audit state.

9. Configuration additions
--------------------------

Add immutable typed settings equivalent to:

.. code-block:: python

   class DatabaseSettings(BaseModel):
       path: Path = Path("/var/lib/binnacle/state/binnacle.db")
       busy_timeout_ms: int = Field(default=5000, ge=100, le=60000)
       wal_autocheckpoint_pages: int = Field(default=1000, ge=100, le=100000)

   class AuditSettings(BaseModel):
       directory: Path = Path("/var/lib/binnacle/audit")
       segment_bytes_max: int = Field(default=16 * 1024 * 1024, ge=1 * 1024 * 1024)
       emergency_bytes_max: int = Field(default=1 * 1024 * 1024, ge=64 * 1024)

   class PayloadSettings(BaseModel):
       directory: Path = Path("/var/lib/binnacle/results")
       object_bytes_max: int = Field(default=32 * 1024 * 1024, ge=1)
       controller_bytes_max: int = Field(default=256 * 1024 * 1024, ge=1)
       append_chunk_bytes_max: int = Field(default=256 * 1024, ge=4096)

Production/system paths are security-critical structural settings. Ordinary environment or
CLI precedence cannot redirect them into source, world-writable, network, or arbitrary
paths. Tests inject temporary roots through explicit composition constructors.

Trusted-time acceptance thresholds or trust sources are not ordinary model-controlled
settings. The selected Linux trust profile is implementation/deployment policy and may
only become less permissive through ordinary runtime configuration.

No hot reload exists for DB/audit/payload roots or trusted-time trust policy.

10. SQLite runtime and migration coordination
---------------------------------------------

``binnacle.adapters.sqlite.engine`` owns engine/session construction.

Expose equivalent APIs:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class DatabaseRuntime:
       engine: AsyncEngine
       session_factory: async_sessionmaker[AsyncSession]
       runtime_lock: object

   async def create_database_runtime(settings: DatabaseSettings) -> DatabaseRuntime: ...
   async def verify_database_runtime(runtime: DatabaseRuntime) -> DatabaseHealth: ...
   async def close_database_runtime(runtime: DatabaseRuntime) -> None: ...

Every SQLite connection applies and reads back:

::

   PRAGMA foreign_keys=ON;
   PRAGMA journal_mode=WAL;
   PRAGMA synchronous=FULL;
   PRAGMA busy_timeout=<bounded milliseconds>;
   PRAGMA wal_autocheckpoint=<configured pages>;

Consequential-kernel availability fails if required values cannot be established.

Use local filesystem storage only. Refuse runtime locations where local durability cannot
be established.

Migration coordination is separate from normal transaction locking. The running
application holds a process/runtime advisory lock under ``/run/binnacle`` for the DB
lifetime. ``binnacle db upgrade`` must acquire the corresponding exclusive migration lock
non-blockingly and refuse migration while a live application writer holds it. The
operator runbook stops ``binnacle-dev.service`` before production/development-Pi upgrade.
This lock prevents concurrent schema migration; it is **not** used as idempotency or
normal DB-transaction correctness authority.

11. Database transaction rules
------------------------------

SQLite and external Linux effects are never described as one ACID transaction.

Rules:

* one ``AsyncSession`` per application use-case transaction;
* no long external I/O while holding a SQLite write transaction;
* create-or-find admission uses a short explicit write transaction;
* SQLite uniqueness/conflict handling, not a Python process mutex, is duplicate-prevention
  authority;
* use ``BEGIN IMMEDIATE`` or an equivalently tested SQLAlchemy/SQLite strategy for the
  narrow first-write critical section where needed;
* commit durable intent before any effect dispatch;
* state changes use expected ``state_version`` optimistic checks;
* retry ``database is locked`` only within a bounded **internal DB transaction** retry
  policy; it never permits repeating an external effect;
* commit/rollback errors after a possible effect become reconciliation work, not effect
  retry;
* DB outage or inability to durably commit pre-effect identity rejects new consequential
  admission.

12. Initial database schema
---------------------------

Migration ``0001_durable_operation_kernel`` creates the minimum authoritative schema.
All foreign keys use explicit names and are exercised with ``PRAGMA foreign_keys=ON`` in
migration tests.

12.1 ``kernel_meta``
~~~~~~~~~~~~~~~~~~~~

Singleton facts:

* ``id`` integer PK constrained to the singleton row;
* ``schema_generation``;
* ``device_id``;
* ``device_epoch`` integer >= 1;
* ``created_at`` / ``updated_at``;
* ``audit_stream_id`` schema-compatible identifier;
* ``audit_epoch`` schema-compatible identifier such as ``epoch-1``;
* ``audit_epoch_generation`` integer >= 1 for local monotonic ordering;
* ``audit_last_sequence`` integer >= 0, where 0 means no event yet in a new store;
* ``audit_last_hash`` nullable SHA-256 until the first event is committed;
* ``trusted_wall_time_high_watermark`` nullable UTC timestamp until trusted time is first
  established;
* ``trusted_time_boot_id_digest`` nullable SHA-256;
* ``trusted_time_monotonic_ns`` nullable non-negative integer for the last trusted sample
  in that boot;
* ``trusted_time_generation`` integer >= 1, incremented on an explicitly accepted new
  boot/trust epoch;
* ``consequential_admission_enabled`` boolean, default false.

The trusted-time fields are ordering/safety evidence, not a clock-repair mechanism.
Within one boot, a monotonic source prevents a wall-clock rollback from extending a
recorded deadline. Across reboot, monotonic values are never compared between boots; the
new wall time must be independently trusted and may not move behind the durable trusted
wall-time high-water mark. If trust or ordering cannot be established, time-dependent
consequential predicates fail closed.

The audit serializer never emits an integer ``audit_epoch`` because the existing audit
event schema requires an identifier. Initial event sequence is 1. Epoch continuity uses
previous accepted epoch/segment digest evidence; the implementation may not use a null
``previous_event_hash`` because the schema requires a digest. If the first-ever genesis
sentinel/convention is not already fixed by the audit fixtures at implementation time, a
small reviewed audit-contract fixture clarification must land before the writer is
accepted rather than inventing a private incompatible convention in runtime code.

On first initialization ``device_epoch=1``. If observed device identity no longer matches
the durable record, startup does not silently adopt a new device epoch; consequential
readiness fails pending explicit future recovery.

12.2 ``controller_owners``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Persist ownership facts, never credentials:

* ``controller_id``;
* ``controller_epoch`` integer >= 1;
* ``controller_profile_id``;
* ``controller_profile_version``;
* ``first_seen_at`` / ``last_seen_at``;
* ``active``.

Primary key: ``(controller_id, controller_epoch)``. Authentication remains owned by the
controller-security layer; this table is an operation ownership reference.

12.3 ``operations``
~~~~~~~~~~~~~~~~~~~

Columns:

* ``operation_id`` PK;
* ``controller_id`` + ``controller_epoch`` composite FK to ``controller_owners``;
* ``device_id`` + ``device_epoch`` snapshot;
* ``operation_contract`` / ``operation_contract_version``;
* ``tool_name`` / ``tool_contract_version`` nullable until a host-facing Tool exists;
* ``request_fingerprint_sha256``;
* ``state``;
* ``state_version`` integer >= 1;
* ``effect_knowledge``;
* ``terminality``;
* ``automatic_retry_allowed`` constrained false for retained V1 operations;
* ``effect_boundary_crossed_at`` nullable;
* ``effect_reference`` nullable bounded protected internal opaque reference;
* ``effect_reference_digest`` nullable SHA-256;
* ``policy_decision_id`` nullable logical current-decision reference;
* ``error_code`` / ``error_summary`` / ``retry_action`` nullable as lifecycle permits;
* ``runtime_build_sha256`` / ``runtime_config_sha256``;
* ``controller_profile_version_snapshot``;
* ``created_at`` / ``updated_at``;
* ``authorised_at`` / ``started_at`` / ``terminal_at`` / ``last_reconciled_at`` nullable.

A stable opaque effect reference is persisted because a digest alone cannot be supplied
to a future ``EffectReconciler`` after restart. The reference is bounded, non-secret,
never treated as authority, and never automatically host-visible. Its digest is used in
audit/correlation. If a future adapter's reference itself contains credential material,
that adapter must instead persist a protected indirect reference; reusable authority
material is forbidden in this table.

Checks enforce canonical lifecycle/effect-knowledge/terminality values and
``automatic_retry_allowed=false``.

12.4 ``operation_transitions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Append-only lifecycle history:

* ``operation_id`` FK;
* ``state_version``;
* ``from_state`` nullable only for version 1;
* ``to_state``;
* ``effect_knowledge``;
* ``terminality``;
* ``reason_code``;
* ``error_code`` nullable;
* ``recorded_at``;
* ``runtime_build_sha256``.

PK ``(operation_id, state_version)``. Version 1 is exactly ``NULL -> received`` and is
inserted in the same transaction that creates the operation. No transition row is
updated after commit.

12.5 ``idempotency_bindings``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Columns:

* ``binding_id`` PK;
* ``device_id``;
* ``device_epoch``;
* ``key_mode``;
* ``key_digest_sha256``;
* ``tool_name`` **NOT NULL**;
* ``contract_version`` **NOT NULL**;
* ``owner_controller_id`` nullable only after full-record compaction;
* ``owner_controller_epoch`` nullable only after full-record compaction;
* ``owner_controller_digest`` non-reversible digest retained for tombstones;
* ``request_fingerprint_sha256`` nullable only for an unconsumed prepared-nonce binding;
* ``prepared_operation_id`` nullable except required for ``prepared_execution_nonce``;
* ``prepared_input_sha256`` nullable except required for ``prepared_execution_nonce``;
* ``prepared_expires_at`` nullable except required for ``prepared_execution_nonce``;
* ``prepared_state_binding_sha256`` nullable except required for
  ``prepared_execution_nonce``;
* ``prepared_registered_boot_id_digest`` nullable except required for an unconsumed
  ``prepared_execution_nonce``;
* ``prepared_monotonic_deadline_ns`` nullable except required for a prepared nonce created
  in the current boot; it is meaningful only when boot IDs match;
* ``target_identity_sha256`` nullable;
* ``maximum_effect_sha256`` nullable;
* ``operation_id`` FK nullable only for a valid tombstone or an unconsumed
  ``prepared_execution_nonce`` full binding;
* ``terminal_class`` nullable for active/full nonterminal records and required for
  tombstones;
* ``created_at`` / ``last_access_at``;
* ``terminal_at`` nullable;
* ``retired_at`` nullable and required for tombstones;
* ``record_kind`` enum ``full``/``tombstone``;
* ``duplicate_count`` / ``conflict_count``.

The exact global unique index is:

::

   (device_id, device_epoch, tool_name, contract_version, key_digest_sha256)

The key columns are non-null so SQLite NULL uniqueness semantics cannot weaken global
duplicate prevention. Internal Phase 4 synthetic tests use a reserved stable internal
``tool_name`` and contract version; they do not create a visible MCP Tool.

An unconsumed prepared execution nonce is a durable ``record_kind=full`` binding with
``key_mode=prepared_execution_nonce`` and ``operation_id=NULL``. It is registered through
an internal store primitive before first execution and retains the prepared operation ID,
exact prepared input digest, expiry timestamp, expected current-state binding digest,
owner/device/Tool/contract scope, nonce digest, registration boot identity, and the
same-boot monotonic deadline needed to prevent wall-clock rollback from extending the
nonce. This is persistence infrastructure only: Phase 4 adds no MCP/CLI preparation
endpoint and no production prepare/execute workflow.

Database checks permit a full row with ``operation_id=NULL`` only for that unconsumed
prepared-nonce shape and require all prepared semantic fields. Other full rows require an
operation ID. Prepared fields are rejected for non-prepared key modes except where a
reviewed later migration explicitly changes the contract. Successful first admission
atomically creates the version-1 operation, stores its request fingerprint, and attaches
its ``operation_id`` to the existing prepared binding.

The full row owns controller ID/epoch; the tombstone contract requires only the
non-reversible owner digest. Full-to-tombstone compaction, when explicitly exercised
after the required retention window, atomically verifies terminal state, writes
``terminal_class`` and ``retired_at``, retains key/tool/contract/fingerprint/owner digest,
clears ``operation_id`` and raw owner ID/epoch as permitted, and leaves the global unique
row in place. Phase 4 implements only explicit operator/test compaction, not broad
automatic purge.

12.6 ``policy_decisions``
~~~~~~~~~~~~~~~~~~~~~~~~~

Store bounded decision facts:

* ``policy_decision_id`` PK;
* ``operation_id`` FK;
* ``policy_id`` / ``policy_version``;
* domain ``decision`` enum ``allow``/``deny``;
* ``controller_id`` / ``controller_epoch``;
* ``operation_contract`` / version;
* ``required_scope_digest`` nullable;
* ``normalized_target_digest`` nullable;
* ``input_facts_sha256``;
* ``reason_codes_json`` bounded canonical JSON;
* ``decided_at``;
* ``runtime_policy_sha256``.

No raw credential or unbounded user content is stored. The audit projection maps domain
``allow`` to audit-schema ``allowed`` and ``deny`` to ``rejected``; it does not emit an
unrecognized payload value.

Avoid a circular mandatory FK graph in migration ``0001``. ``policy_decisions.operation_id``
is the authoritative FK to ``operations``. ``operations.policy_decision_id`` is either a
nullable current-reference with an implementation-tested deferred/logical integrity
check, or it is omitted and the current decision is selected through the operation FK.
The implementation must choose one tested repository-consistent form; it must not create
a migration cycle that SQLite/Alembic cannot safely upgrade/downgrade.

12.7 ``payload_objects``
~~~~~~~~~~~~~~~~~~~~~~~~

SQLite metadata:

* ``payload_id`` PK;
* ``operation_id`` nullable FK;
* ``controller_id`` + ``controller_epoch`` ownership reference;
* ``kind`` enum ``result``/``stdout``/``stderr``/``evidence``/``internal``;
* ``lifecycle`` enum ``building``/``complete``/``failed``/``expired``/``deleted``;
* ``relative_path`` unique;
* ``media_type`` / ``encoding``;
* ``decoded_byte_count``;
* ``sha256`` nullable until complete;
* ``truncated``;
* ``information_class`` / ``retention_class``;
* ``created_at`` / ``completed_at`` / ``expires_at`` / ``last_access_at`` as applicable.

Metadata never claims ``complete`` before finalized bytes are fsynced and digest-verified.

12.8 ``operation_evidence``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bounded correlation metadata:

* ``evidence_id`` PK;
* ``operation_id`` FK;
* ``source`` / ``provenance`` / ``information_class``;
* ``fresh_until`` nullable;
* ``result_sha256`` nullable;
* ``payload_id`` nullable FK;
* ``audit_ref`` nullable;
* ``facts_json`` bounded canonical JSON;
* ``recorded_at``.

This table is an index/projection, not authoritative security audit storage.

12.9 Migration creation order and constraints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Migration ``0001`` creates dependency roots before dependents: ``kernel_meta`` and
``controller_owners`` first; ``operations`` next; then idempotency, policy, payload, and
evidence/history tables in an order that satisfies the chosen FK layout. Migration tests
inspect actual SQLite FK metadata and perform negative inserts. Do not assume ORM
relationship declarations imply SQLite-enforced constraints.

13. Domain lifecycle model
--------------------------

``binnacle.domain.operation`` mirrors exactly:

.. code-block:: python

   class OperationState(StrEnum):
       RECEIVED = "received"
       REJECTED = "rejected"
       AUTHORISED = "authorised"
       RUNNING = "running"
       PAUSED = "paused"
       CANCELLING = "cancelling"
       CANCELLED = "cancelled"
       SUCCEEDED = "succeeded"
       FAILED = "failed"
       UNCERTAIN = "uncertain"

   class EffectKnowledge(StrEnum):
       NONE = "none"
       KNOWN_NO_EFFECT = "known_no_effect"
       KNOWN_EFFECT = "known_effect"
       PARTIAL = "partial"
       UNCERTAIN = "uncertain"

   class Terminality(StrEnum):
       NON_TERMINAL = "non_terminal"
       EFFECT_TERMINAL_RECONCILABLE = "effect_terminal_reconcilable"
       TERMINAL = "terminal"

   @dataclass(frozen=True, slots=True)
   class OperationSnapshot:
       operation_id: str
       state: OperationState
       state_version: int
       effect_knowledge: EffectKnowledge
       terminality: Terminality
       automatic_retry_allowed: Literal[False]
       error: OperationError | None
       ...

Use one table-driven transition validator loaded/generated from the reviewed lifecycle
contract or one hand-maintained exact mapping protected by parity tests. No second
transition map may diverge.

Contract edges are exactly:

::

   received   -> rejected | authorised
   authorised -> running | cancelling | cancelled | failed
   running    -> paused | cancelling | succeeded | failed | uncertain
   paused     -> running | cancelling | failed | uncertain
   cancelling -> cancelled | succeeded | failed | uncertain
   uncertain  -> succeeded | failed | cancelled

Terminal states have no outgoing edge. State/effect-knowledge/error/terminality
cross-field constraints are validated before persistence.

14. Operation identity and request fingerprint
----------------------------------------------

``operation_id`` uses at least 128 random bits and a schema-compatible opaque rendering
such as ``op_<32 lowercase hex>``.

Request fingerprinting uses a closed normalized structure containing exactly the
idempotency contract's effect-bearing fields. JCS canonical bytes (within I-JSON
constraints) are SHA-256 hashed. Fingerprinting excludes current policy decision,
observation freshness, and mutable availability.

Normalization belongs to the operation-specific caller/use case. The generic kernel
accepts typed normalized digests; it never guesses filesystem/Git/command semantics.

The machine-readable ordering phrase ``persist_operation_and_reservations`` is not
interpreted as permission to omit the pre-policy operation identity. The governing
idempotency prose requires operation identity/state version in the durable pre-policy
record. Phase 4 therefore creates the minimal version-1 ``received`` operation atomically
with the global key record; post-policy admission/reservation data is persisted only
after policy.

15. Trusted time and deadline ordering
--------------------------------------

The design requires Binnacle to distinguish wall-clock timestamps, monotonic elapsed time
inside one boot, and durable ordering across restart. Phase 4 therefore introduces a
small ``TrustedTimeSource`` port returning a bounded snapshot:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class TrustedTimeSnapshot:
       wall_time: datetime
       monotonic_ns: int
       boot_id_digest: str
       wall_time_trusted: bool

   class TrustedTimeSource(Protocol):
       async def snapshot(self) -> TrustedTimeSnapshot: ...

The application-layer ``TrustedTimeGuard`` combines that snapshot with durable
``kernel_meta`` high-water evidence.

Rules:

* an untrusted wall clock is never used to prove a future prepared deadline remains valid;
* a current wall time behind the durable trusted high-water mark is rollback and fails
  closed;
* when the boot ID matches registration, the stored monotonic deadline is authoritative
  against wall-clock rollback: reaching/passing it means the preparation is expired even
  if wall time moved backward;
* when boot ID changes, old monotonic values are incomparable; a new wall time must be
  independently trusted and not behind the durable high-water mark before the absolute
  ``prepared_expires_at`` comparison may be used;
* loss of the selected OS trust signal, reboot with an untrusted/incorrect clock, or any
  ordering ambiguity returns internal ``trusted_time_unavailable`` and creates/crosses no
  effect boundary;
* an actually elapsed prepared deadline still returns the existing reviewed
  ``prepared_operation_expired`` code;
* restoring trusted time requires a new accepted snapshot/high-water update; the kernel
  does not set or repair the system clock.

Any other later operation contract that depends on a deadline/freshness predicate must
use the same trusted-time guard rather than reading ``datetime.now()`` directly.

16. Idempotency key handling
----------------------------

``IdempotencyKeyMode`` contains exactly ``caller_key``, ``prepared_execution_nonce``, and
``derived_member_key``.

Caller-key validation accepts only the encodings/randomness rules in
``spec/operation/idempotency.yaml``. Raw key material exists only long enough to validate,
decode, and compute the domain-separated SHA-256 digest. UUIDv4 alone is rejected.

``derived_member_key`` is recognized for contract parity but is **not admitted in Phase
4**. The machine-readable contract permits it only when a parent contract declares a
deterministic member derivation from a previously durable parent. Phase 4 has no reviewed
parent-contract registry/derivation binding, so any request using this mode fails closed
as ``idempotency_invalid`` before a global binding or operation is created. Synthetic
parity tests may assert this rejection; they do not introduce a parent workflow. A later
reviewed phase must explicitly define and verify the parent contract and derivation before
this key mode can become admissible.

For ``prepared_execution_nonce``, Phase 4 defines only an **internal persistence seam**,
not a host workflow. ``OperationStore.register_prepared_execution_nonce(...)`` may be
used by tests and a later reviewed preparation use case to durably reserve the nonce
digest with controller/device/Tool/contract scope, ``prepared_operation_id``, exact
``prepared_input_sha256``, ``prepared_expires_at``,
``prepared_state_binding_sha256``, registration boot identity, and same-boot monotonic
deadline. Registration itself requires a trusted-time snapshot; if that cannot be
established, no prepared binding is created. The raw nonce is never persisted.

The operation-specific future caller is responsible for computing the exact current-state
binding under its reviewed preparation contract. It supplies that digest at first
admission **and** provides a narrow state-verification callback/port that can recompute the
current digest immediately before a consequential boundary. The generic kernel compares
digests; it does not invent filesystem, command, Git, or other current-state semantics.
If the durable prepared binding or final verifier cannot be loaded/executed truthfully,
the prepared operation fails closed without effect.

Preparation expiry, exact prepared operation/input, current-state binding, and trusted
time ordering are checked before first operation admission. For a newly admitted prepared
operation that is still on its first dispatch path, they are checked again as part of the
final OP-BOUNDARY guard immediately before ``EffectBoundary.start``.

Once an effect has been dispatch-attempted, or when a later same-owner/same-fingerprint
retry merely returns retained work, preparation expiry must not be reinterpreted as
permission to create/re-dispatch a fresh operation. Retained-operation reconciliation
remains authoritative.

17. Atomic create-or-find semantics
-----------------------------------

``OperationStore.create_or_find`` owns the first transaction.

Algorithm:

#. begin a short write transaction;
#. reject ``derived_member_key`` as ``idempotency_invalid`` before lookup/creation unless
   a later reviewed implementation supplies and verifies its declared durable parent
   contract and deterministic derivation; Phase 4 supplies none;
#. lookup/attempt the exact global unique binding scope;
#. if no binding exists and the key mode is ``prepared_execution_nonce``, return
   ``prepared_operation_mismatch`` without creating an operation: a prepared nonce must
   have a durable pre-admission registration;
#. if no binding exists for ``caller_key``, create the full binding + ``received``
   operation + version-1 transition atomically;
#. if present and ``record_kind=tombstone`` or ``retired_at`` is set, return
   ``idempotency_key_retired`` without loading/disclosing an operation;
#. for a present full record, verify owner before disclosing preparation or operation
   details; another controller returns non-disclosing ``idempotency_owner_mismatch``;
#. if the full record is an unconsumed prepared-nonce binding with ``operation_id=NULL``,
   obtain a ``TrustedTimeGuard`` decision; inability to prove safe time ordering returns
   ``trusted_time_unavailable`` with no operation created; a proven elapsed deadline
   returns ``prepared_operation_expired`` with no operation created;
#. for that unconsumed prepared binding, compare the supplied prepared operation ID,
   exact input digest, and current-state binding digest against the durable values;
   any mismatch returns ``prepared_operation_mismatch`` with no operation created;
#. after all prepared checks pass, atomically create the version-1 ``received`` operation,
   persist its request fingerprint, attach its ``operation_id`` to the existing prepared
   binding, and continue only that newly admitted operation;
#. for a present full record already attached to an operation, verify fingerprint;
#. same owner + same fingerprint -> return the retained operation, including terminal or
   ``uncertain`` state, with no effect;
#. same owner + different fingerprint -> increment conflict count and return
   ``idempotency_conflict``;
#. different controller -> increment conflict count and return non-disclosing
   ``idempotency_owner_mismatch``;
#. commit;
#. only a newly created/attached full operation proceeds to policy/admission.

The tombstone check occurs before the same-owner/same-fingerprint retained-operation
branch because a valid tombstone may have ``operation_id=NULL`` and the contract requires
``idempotency_key_retired``. No code attempts to load a retired operation from a tombstone.

Prepared expiry/input/current-state/trusted-time checks before first admission use durable
fields that survive process restart. They are not bypassed by reconstructing a fresh
application. After an operation is attached, normal retained-operation idempotency
semantics take precedence for retries, while a *newly admitted operation on its first
dispatch path* still performs final OP-BOUNDARY checks. That final guard is not a second
admission and cannot create another operation.

Concurrent uniqueness races roll back, re-read, and follow the same decision table. They
do not create a second operation.

18. Minimal Bootstrap PolicyEngine
----------------------------------

``PolicyEngine`` receives only normalized bounded facts: authenticated controller
identity/profile/epoch, operation contract/version, already-validated scope names,
normalized target/effect digests, maximum-effect class, development-session flags when
later supplied, and protected policy identity/digest.

Production ``BootstrapPolicyEngine`` is fail-closed:

* unknown operation contract -> deny;
* missing authenticated controller -> deny;
* protected/control-plane target -> deny unless a later reviewed contract supplies
  explicit authority;
* no wildcard allow;
* no embedded policy scripting language;
* no environment/CLI override that broadens security policy.

Because Phase 4 exposes no real consequential contract, production policy does not need
to allow one. Tests inject a fixture policy and synthetic contract to exercise the full
kernel path. There is no hidden production ``allow_all`` switch.

19. Final consequential-boundary revalidation
--------------------------------------------

``docs/design.md`` requires applicable authority/state predicates to be revalidated
**immediately before each consequential boundary**. Phase 4 therefore defines one
mandatory application-layer ``BoundaryRevalidator`` used for every key mode, not only
prepared nonces.

The generic baseline guard re-reads and verifies, as applicable:

* current controller identity/profile/epoch and whether that controller remains trusted;
* current device identity/profile/epoch and device trust;
* current protected policy identity/digest and whether the operation remains allowed;
* current operation state and exact expected ``running`` state version;
* cancellation/supervision state and any pending cancellation transition;
* trusted time and deadline/freshness predicates;
* recovery prerequisite and whether the kernel is still ``available``;
* the durable target/maximum-effect digests that are generic kernel facts.

An operation-specific future consequential caller must additionally provide a narrow
``OperationBoundaryVerifier`` for predicates that the generic kernel cannot interpret,
such as target/path/external endpoint freshness, reservation, delegated privilege/
credential validity, hardware interlock/measurement, or other contract-specific current
state. There is no optional production ``allow_all`` verifier: an effect-capable reviewed
operation contract must declare which predicates apply and supply their verifier before a
real adapter may be composed.

For ``prepared_execution_nonce``, the prepared expiry/current-state verifier is one part
of this same final boundary revalidation. It does not replace the general authority/
lifecycle checks.

The final guard is the last potentially blocking/revalidating work before
``EffectBoundary.start``. After it returns success, the coordinator performs no unrelated
I/O or policy work before the call.

Failure behavior:

* the effect boundary is never called;
* if the operation is still the expected ``running`` state/version and failure proves no
  effect was attempted, transition ``running -> failed`` with ``known_no_effect`` and an
  applicable existing error (for example ``policy_rejected``,
  ``prepared_operation_expired``, ``prepared_operation_mismatch``,
  ``trusted_time_unavailable``) or internal ``boundary_revalidation_failed``;
* if state/version changed concurrently, especially into ``cancelling``, do **not**
  overwrite it with ``failed``; return/reconcile the current retained state and keep the
  boundary suppressed;
* a verifier error/unavailable result is fail-closed, never an implicit success;
* lifecycle/audit evidence uses only existing schema-supported payload kinds.

20. Consequential admission and dispatch sequence
-------------------------------------------------

``OperationCoordinator`` owns the ordering:

#. receive an already-authenticated owner, normalized ``OperationIntent``, and future
   caller idempotency input;
#. validate key syntax/mode and derive safe key digest;
#. reject undeclared ``derived_member_key`` before durable binding/operation creation;
#. atomically create/find global binding + version-1 ``received`` operation;
#. for retained/conflict/owner-mismatch/retired outcomes, return without effect;
#. append/fsync a schema-valid audit event with
   ``payload.kind=operation.state_changed``, ``old_state=null``,
   ``new_state=received``, ``state_version=1``, ``effect_knowledge=none``, and a bounded
   reason code such as ``operation_received``;
#. evaluate policy;
#. durably persist policy decision;
#. on deny, transition ``received -> rejected`` and append/fsync schema-valid
   ``policy.decision``/``operation.rejected`` and state-change audit as required;
#. on allow, transition ``received -> authorised`` and commit;
#. append/fsync schema-valid ``policy.decision`` with ``decision=allowed`` and
   ``operation.authorised`` audit evidence;
#. create the dispatch ``TransitionRequest`` and durably transition
   ``authorised -> running`` with ``effect_knowledge=none`` **before invoking the effect
   adapter**; the resulting running ``state_version`` is the durable dispatch-attempt
   marker;
#. append/fsync a schema-valid ``payload.kind=effect.intent_recorded`` event carrying only
   bounded/digested target/effect facts and that operation correlation;
#. if that required intent append/fsync fails while SQLite remains writable, **do not call
   the effect boundary**: durably transition ``running -> failed`` with
   ``known_no_effect`` and ``audit_unavailable``, disable consequential admission, and
   record emergency/recovery evidence where the existing audit contract permits; if the
   DB terminalization itself cannot be committed, leave no in-memory claim of a durable
   terminal state and let restart use the conservative running/recovery path;
#. run the mandatory final OP-BOUNDARY revalidation from section 19 for **every** operation
   mode, including trusted-time and prepared expiry/current-state checks where applicable;
#. on final-guard failure, suppress the boundary call and follow the no-effect/concurrent-
   state behavior defined in section 19;
#. **only after all applicable final boundary checks pass** call
   ``EffectBoundary.start`` with an ``EffectRequest`` containing the operation ID and
   running state version as stable dispatch identity;
#. durably persist the returned no-crossing/crossed/reference/outcome knowledge and the
   bounded recoverable opaque reference when one exists;
#. transition from ``running`` according to the exact lifecycle contract if the result is
   already terminal/uncertain, or remain running when an independently supervised effect
   is genuinely in progress;
#. append/fsync schema-valid ``effect.started``, ``effect.observed``, ``effect.failed``,
   ``effect.uncertain``, and/or ``operation.state_changed`` records as appropriate;
#. return the retained operation/result metadata.

The exact existing audit schema uses ``payload.kind`` as the event-type discriminator;
Phase 4 does **not** invent an ``event_type`` or unsupported kinds such as a literal
``operation_received`` payload.

A process crash after the durable ``running`` marker but before ``EffectBoundary.start``
is deliberately conservative: durable state says ``running`` even if the adapter was
never reached. Restart cannot prove no effect from the state marker alone, so it resolves
through the running/uncertain reconciliation path rather than falsely returning
``known_no_effect`` unless a separately durable no-effect terminalization was committed
before the crash.

There is no production effect adapter in Phase 4.

21. Effect boundary and reconciliation seams
--------------------------------------------

Define narrow framework-independent ports:

.. code-block:: python

   class PreparedStateVerifier(Protocol):
       async def current_state_digest(self, request: PreparedStateCheck) -> str: ...

   class OperationBoundaryVerifier(Protocol):
       async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult: ...

   class EffectBoundary(Protocol):
       async def start(self, request: EffectRequest) -> EffectStartReceipt: ...

   class EffectReconciler(Protocol):
       async def reconcile(self, reference: EffectReference) -> EffectObservation: ...

``PreparedStateCheck`` contains only protected prepared-operation identity and bounded
operation-specific facts required to recompute the reviewed current-state digest. It does
not accept an arbitrary command/path interface.

``OperationBoundaryCheck`` contains only the already-normalized/digested current predicates
that the operation contract declares. It cannot widen authority or mutate the target.
Phase 4 production has no consequential contract; tests provide deterministic fake
verifiers.

``EffectStartReceipt`` can express only:

* boundary definitely not crossed;
* boundary crossed with stable bounded opaque reference;
* outcome already known;
* outcome uncertain.

``EffectRequest`` carries the operation ID and the durable running state version. A future
adapter must use that stable dispatch identity when its external mechanism supports
idempotent submission/reconciliation. It must never infer a fresh effect identity from a
retry.

A generic exception or lost ``start()`` response after the call begins is **not** proof
that the boundary was not crossed. Unless a typed adapter result can prove no dispatch,
the coordinator leaves/records dispatch-attempted state and restart reconciliation must
produce or preserve ``uncertain``. Only an explicit, trustworthy “definitely not crossed”
receipt may justify ``known_no_effect``.

Phase 4 production composition uses ``UnavailableEffectBoundary``. Tests inject a
separate counting boundary/reconciler. Later executor/broker processes implement their
own adapters/IPC and never open the application SQLite DB directly.

22. State transition persistence
--------------------------------

Every real transition:

#. loads state/version;
#. validates the exact lifecycle edge and cross-field invariants;
#. conditionally updates ``WHERE operation_id=? AND state_version=?``;
#. increments ``state_version`` exactly once;
#. inserts the matching append-only ``operation_transitions`` row in the same transaction;
#. requires exactly one updated current row;
#. returns ``state_conflict`` on stale expected version.

A duplicate observation may return the existing version only when it is semantically the
same observation; it cannot fabricate a transition.

``received`` is version 1. ``authorised -> running`` is a real version increment and is
committed before any effect call. A pre-boundary failure after that marker may use the
contract-allowed ``running -> failed`` edge with ``known_no_effect`` only when the
coordinator still owns the expected running state/version and can prove the effect boundary
was not invoked. ``uncertain`` is effect-terminal-reconcilable and moves only to
``succeeded``/``failed``/``cancelled`` through explicit reconciliation evidence.

23. Restart reconciliation
--------------------------

``OperationReconciler`` runs after DB, audit, payload, and trusted-time verification and
before consequential-kernel availability.

Scan nonterminal/effect-reconcilable operations in bounded pages.

Rules:

* ``received`` -> ``rejected`` with ``restart_before_admission`` after required recovery
  audit is writable; no policy/effect is resumed automatically;
* ``authorised`` -> ``failed`` with ``known_no_effect`` because coordinator invariants
  prohibit calling the effect adapter before the durable transition to ``running``;
* ``running``/``paused``/``cancelling`` with a durable recoverable external reference ->
  ask ``EffectReconciler``;
* a process that failed ``effect.intent_recorded`` and successfully committed
  ``running -> failed`` before exit is already terminal and is not reclassified as
  uncertain;
* ``running`` with missing effect-intent audit and no durable no-effect terminalization is
  recovery-required/uncertain: startup must not infer from absence of the audit event that
  the boundary was definitely never reached;
* ``running`` with no external reference, including crash during ``start()`` before a
  receipt or crash after the running marker before/final-boundary verification, is
  **uncertain**, never ``known_no_effect`` unless separate durable evidence proves the
  boundary was not called;
* ``paused``/``cancelling`` without a reconcilable reference also becomes ``uncertain``
  unless the adapter can prove an allowed terminal observation through another protected
  stable dispatch identity;
* if no reconciler exists or an outcome cannot be proven -> ``uncertain``;
* existing ``uncertain`` remains uncertain until explicit reconciliation proves an
  allowed terminal transition;
* no startup path creates a new idempotency key or dispatches an effect automatically.

Phase 4 production has no external effect reference. Fault/integration tests exercise all
branches with fakes.

24. Cancellation, status, and result application APIs
-----------------------------------------------------

These APIs are internal only:

.. code-block:: python

   class OperationService:
       async def get_operation(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot: ...
       async def request_cancel(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot: ...
       async def get_payload_metadata(self, payload_id: str, owner: OperationOwner) -> PayloadMetadata: ...
       async def read_payload_range(...): ...

Querying failed/uncertain work is a successful state query. Malformed, not-owned, and
not-found requests are application errors.

Cancellation:

* never treats transport disconnect as cancellation;
* validates owner/current state/expected state version;
* follows only lifecycle-declared edges;
* a cancellation or state-version change observed by final boundary revalidation always
  suppresses a new ``start`` call;
* may move ``authorised`` directly to verified ``cancelled`` only when no effect was
  dispatched and the no-effect condition is proven;
* otherwise enters ``cancelling`` only where permitted;
* calls a cancellation-capable future adapter only when one exists;
* never claims ``cancelled`` until cancellation and remaining-effect truth are verified;
* may reconcile to ``succeeded``, ``failed``, or ``uncertain`` as observations require.

No MCP registration/projection is added.

25. Payload storage
-------------------

``PayloadStore`` owns bytes; SQLite owns authoritative ownership/lifecycle metadata.

Required behavior:

* implementation-owned relative paths only; no caller absolute path;
* exclusive temp creation;
* bounded append chunks;
* incremental byte/quota tracking;
* fsync data before finalization;
* SHA-256 of decoded/full bytes;
* atomic temp/part -> final rename;
* fsync containing directory;
* **only then** commit DB lifecycle ``complete`` and digest metadata;
* crash after file finalize/before DB commit -> orphan, never exposed as complete;
* DB complete but missing/wrong bytes -> integrity failure and block affected result;
* no silent truncation marked complete.

``truncated=true`` remains explicit metadata; a later Tool contract decides whether a
truncated object is valid output or an error/reference.

26. Retention and tombstones
----------------------------

Phase 4 establishes internal storage ceilings from existing large-result policy but not
host-facing pagination. Host-visible limits remain evidence-gated.

Full idempotency records are retained through the contract's maximum retry and
reconciliation window. Explicit compaction may then create the contract-exact tombstone
described above. Uncertain/security-recovery evidence is not removed merely because
ordinary result data expires.

Quota pressure rejects new protected payload production when safe eviction is impossible.
No broad automatic destructive cleanup is introduced.

27. Operation evidence metadata
-------------------------------

``OperationEvidence`` stores only bounded source/provenance, information class, freshness,
optional result digest, operation/payload/audit references, and bounded diagnostic facts.
It is not authoritative audit storage and never contains credentials or unbounded effect
payloads.

28. Append-only audit journal and exact schema mapping
-----------------------------------------------------

``AuditJournal`` is independent from structlog/journald and independent from SQLite as the
authoritative event bytes.

It implements:

* UTF-8;
* RFC 8785 JCS;
* I-JSON-compatible values;
* SHA-256 with ``event_hash`` omitted from the preimage;
* required ``previous_event_hash`` chain;
* strictly monotonic sequence;
* segment chain metadata and audit-epoch continuity;
* event byte and safe-fact bounds from ``spec/audit/audit-policy.yaml``.

``payload.kind`` is the **only** authoritative event type. All events validate against
``schemas/audit/audit-event.schema.json`` before append. Phase 4 uses only existing
payload kinds, including as applicable:

* ``operation.state_changed`` for received/running/terminal lifecycle records;
* ``operation.idempotency_conflict`` for duplicate/conflict evidence;
* ``policy.decision``, ``operation.rejected``, ``operation.authorised``;
* ``effect.intent_recorded``, ``effect.started``, ``effect.observed``,
  ``effect.failed``, ``effect.uncertain``;
* ``cancellation.requested`` / ``cancellation.phase_changed`` /
  ``cancellation.verified``;
* ``reconciliation.started`` / ``reconciliation.completed`` / ``recovery.required``;
* existing ``audit.*`` payload kinds for segment/checkpoint/integrity events.

Domain policy ``allow``/``deny`` maps to schema ``allowed``/``rejected``. A reason code
may say ``operation_received`` but the payload kind remains ``operation.state_changed``.
No redundant top-level ``event_type`` is added.

Every required event populates all non-null schema identity fields from the current
verified runtime profile: build digest, runtime Tool-manifest digest, schema-registry
digest, device-profile version, policy version, stream/epoch/segment IDs, boot/device IDs,
and redaction-policy version. Absence of a required runtime identity blocks the required
audit append rather than inventing null/default data.

Redaction happens before canonicalization and persistence. Raw idempotency keys and
authority material are prohibited.

Phase 4 does not claim external-compromise-resistant history; external checkpoint
publication remains deferred.

29. Audit persistence ordering and crash windows
------------------------------------------------

SQLite and audit are two durable systems with explicit recovery; they are not one
transaction.

Pre-effect ordering:

#. DB version-1 ``received`` commits;
#. ``operation.state_changed`` received audit appends/fsyncs;
#. policy decision commits;
#. deny path audits rejection; allow path commits ``authorised``;
#. ``policy.decision``/``operation.authorised`` audit appends/fsyncs;
#. DB ``authorised -> running`` dispatch marker commits;
#. ``effect.intent_recorded`` audit appends/fsyncs;
#. if the intent append/fsync fails and DB is writable, terminalize ``running -> failed``
   with ``known_no_effect``/``audit_unavailable`` before entering the audit-failure gate;
#. perform final OP-BOUNDARY revalidation for every operation mode;
#. only then may the effect adapter be called.

After a synthetic/future external effect, truthful operation persistence has priority;
audit follows immediately and fsyncs. If audit fails after a known effect, do not roll
back history or repeat the effect: mark audit degraded, retain truthful state, and block
new consequential admission.

Crash-window rules:

* DB received but missing received audit -> never continue to effect; recovery records
  the audit gap/recovery and rejects the unadmitted operation once audit is trustworthy;
* authorised DB state without authorization audit -> no effect; fail/recover as
  ``known_no_effect`` only after audit recovery;
* authorization audit but still authorised -> no effect was dispatched because running
  transition is the code-level precondition;
* running state with a known in-process effect-intent append/fsync failure -> no boundary
  was called; if DB is writable, commit ``running -> failed`` ``known_no_effect`` before
  leaving the path and attempt emergency evidence;
* if that DB terminalization fails, do not call the boundary and do not fabricate a
  durable no-effect terminal state; restart treats the unresolved running record
  conservatively;
* running + effect-intent audit but crash before/during final boundary revalidation ->
  uncertain on restart unless separate durable evidence proves no boundary call;
* running + effect-intent audit + passed final boundary guard with lost start receipt ->
  uncertain unless reconciler proves an allowed terminal outcome.

30. Audit failure gate and emergency journal
-------------------------------------------

``KernelHealth`` tracks DB/audit/payload separately. When required audit cannot append,
fsync, or verify:

* durably disable new consequential admission where DB remains writable;
* do not cross a new effect boundary;
* if the failure occurs on ``effect.intent_recorded`` after the durable running marker,
  first persist ``running -> failed`` with ``known_no_effect``/``audit_unavailable`` when
  SQLite is still writable because this process knows ``EffectBoundary.start`` was not
  called;
* allow bounded trustworthy recovery/status reads;
* attempt one bounded emergency audit record only when the pre-created emergency journal
  remains writable/trustworthy;
* emergency exhaustion remains fail-restricted;
* recovery verifies surviving continuity before re-enabling admission.

If SQLite cannot persist that known-no-effect failure, no effect is called but the kernel
must not claim the terminal transition survived; recovery remains conservative.

No silent ordinary-log fallback exists.

31. Audit verification and checkpoints
--------------------------------------

Verifier checks event schema, JCS hash, sequence, previous-event hash, segment metadata,
epoch continuity, truncation/fork/duplicate sequence, and canonical byte ceiling.

Local consistency checkpoints may record DB schema revision, highest operation/transition
summary, audit epoch/sequence/final digest, trusted-time high-water/generation, and runtime
build/config/policy digests. SQLite stores only checkpoint reference/digest metadata;
audit event bytes remain authoritative. This is not an external signed checkpoint or
post-compromise history claim.

32. Minimal local operator CLI and migration safety
--------------------------------------------------

Extend existing CLI with local-only:

::

   binnacle db status
   binnacle db upgrade
   binnacle kernel verify
   binnacle audit verify

``db status`` reads Alembic revision and pragmas.

``db upgrade`` is explicit, never MCP-callable, acquires the exclusive migration/runtime
lock described above, and refuses if the live application writer is active. The
development-Pi runbook requires stop -> upgrade -> verify -> start. It never creates a
second writer beside the running service.

``kernel verify`` checks schema/pragmas, lifecycle/idempotency invariants, trusted-time
ordering state, payload metadata/bytes, and audit continuity without automatic repair.

``audit verify`` checks the append-only chain without dumping event payloads.

Human/agent/JSON output follows existing CLI conventions and never exposes raw payload,
audit, credential, idempotency-key, or raw boot/time-trust material.

33. Startup and migration behavior
----------------------------------

Application startup does not silently migrate.

Sequence:

#. acquire runtime DB lock;
#. inspect Alembic revision;
#. new/uninitialized or behind/ahead DB -> kernel unavailable/migration required;
#. operator stops service and runs explicit ``binnacle db upgrade``;
#. startup reopens and verifies revision/pragmas;
#. verify audit continuity;
#. verify payload roots/metadata;
#. load trusted-time durable high-water/boot evidence and obtain a current trust snapshot;
#. if current time is untrusted or rolled back, mark time-dependent consequential
   predicates unavailable rather than resetting/advancing deadlines;
#. run bounded restart reconciliation;
#. only after all required checks succeed set
   ``consequential_admission_enabled=true`` and mark internal kernel available, while
   time-dependent operations remain fail-closed if trusted time is unavailable.

Migration failure never deletes/recreates DB. Migration ``0001`` rejects incompatible
unmanaged tables rather than silently taking ownership.

Migration tests cover fresh upgrade, FK/check/index presence, unknown revision refusal,
exclusive migration coordination, and safe downgrade/round-trip where downgrade exists.

34. Kernel health and readiness
-------------------------------

Internal availability is ``available``, ``degraded``, or ``unavailable``. Consequential
admission requires ``available``; a time-dependent operation additionally requires a
trusted-time state that can prove its deadline/freshness predicates.

Phase 4 does not change public ``/readyz`` solely to expose this kernel because current
read-only Tools do not depend on it. The existing compatibility server may remain ready
while the internal kernel is unavailable. A later mutating Tool promotion makes kernel
availability part of that capability's readiness.

35. Stable internal error codes
-------------------------------

Include at least:

::

   database_unavailable
   database_revision_mismatch
   database_state_conflict
   idempotency_invalid
   idempotency_conflict
   idempotency_owner_mismatch
   idempotency_key_retired
   idempotency_storage_unavailable
   prepared_operation_mismatch
   prepared_operation_expired
   trusted_time_unavailable
   policy_rejected
   boundary_revalidation_failed
   audit_unavailable
   audit_integrity_failed
   payload_storage_unavailable
   payload_integrity_failed
   payload_quota_exceeded
   operation_not_found
   operation_owner_mismatch
   operation_state_conflict
   operation_transition_invalid
   operation_uncertain
   cancellation_not_supported
   reconciliation_unavailable

These are not automatically MCP error codes. Host-facing mappings require a later
reviewed Tool contract. In Phase 4 ``idempotency_invalid`` is also the internal fail-closed
result for ``derived_member_key`` because no declared parent derivation is implemented.
``trusted_time_unavailable`` truthfully distinguishes inability to prove a deadline from
a deadline that is demonstrably expired.

36. Controller ownership binding
--------------------------------

Phase 4 consumes a validated controller identity from the selected Phase 3 profile; it
does not authenticate requests itself. Durable operation ownership stores opaque
controller ID/profile/version/epoch only, never reusable credential material.

A replacement controller cannot automatically read/advance old operations and cannot use
an old key to create a duplicate. Deliberate ownership transfer remains a separate future
contract.

Final boundary revalidation rechecks that the controller/device trust/profile facts that
matter to the operation are still current immediately before dispatch.

37. Process-boundary ownership
------------------------------

The main MCP/application process is the sole authoritative ``binnacle.db`` writer.
Future executor/privileged-broker processes:

* never open the application SQLite DB directly;
* retain minimum independent execution/broker evidence;
* reconcile through typed IPC/application ports;
* return stable bounded external reference identity to the application.

Phase 4 defines only effect/reconciliation semantics, not future IPC wire schemas.
Audit/payload/trusted-time adapters run in the application process in Phase 4.

38. Logging and diagnostics
---------------------------

Structured diagnostic logs may include DB revision/pragmas, operation ID, state/version,
safe idempotency digest prefix, policy decision ID/reason code, boundary-revalidation
result code, trusted-time health/generation (not raw trust material), reconciliation result,
payload byte counts/digest prefix, audit sequence/status, and kernel availability.

Do not log raw keys/nonces, credentials, full fingerprint inputs, payload/stdout/stderr,
protected policy values, raw external authority material, raw machine/boot identifiers,
or full audit event bodies. Audit and ordinary diagnostics remain separate systems.

39. Property tests
------------------

Hypothesis/state-machine tests cover:

* every allowed and forbidden lifecycle edge;
* state-version monotonicity and duplicate observation behavior;
* valid state/effect-knowledge/terminality/error combinations;
* same-key/same-input reconciliation;
* same-key/different-input conflict;
* cross-controller replay non-disclosure/no effect;
* concurrent first request exactly one binding;
* ``derived_member_key`` without a declared/verified parent contract always fails closed
  as ``idempotency_invalid`` before binding/operation creation;
* prepared nonce first admission requires a durable registration;
* unconsumed prepared nonce expiry returns ``prepared_operation_expired`` with no
  operation/effect;
* prepared operation/input/current-state binding mismatch returns
  ``prepared_operation_mismatch`` with no operation/effect;
* same-boot wall-clock rollback cannot extend a prepared deadline because monotonic
  deadline ordering remains authoritative;
* changed boot ID with untrusted wall time fails prepared admission/boundary revalidation
  as ``trusted_time_unavailable`` with no effect;
* trusted wall time behind the durable high-water mark fails closed;
* a valid prepared binding admits exactly one operation and attaches it atomically;
* a target current-state change after first admission but before final boundary guard
  returns ``prepared_operation_mismatch`` and never calls the counting boundary;
* preparation expiry after first admission but before final boundary guard returns
  ``prepared_operation_expired`` and never calls the counting boundary;
* verifier unavailable/unprovable at the final guard fails closed with no effect;
* controller/device trust, policy/profile, state version, cancellation, reservation,
  target/freshness, or recovery predicate change between authorisation and dispatch
  suppresses ``EffectBoundary.start``;
* a concurrent state/version change is never overwritten by a stale failed transition;
* after successful prepared admission, a same-fingerprint retry returns the retained
  operation even when the preparation expiry time has subsequently passed;
* uncertain never auto-retries;
* cancellation cannot become cancelled without verification;
* full-to-tombstone conversion retaining exact duplicate-prevention fields;
* tombstone replay returns ``idempotency_key_retired`` and never attempts operation load.

Tests consume reviewed YAML/fixtures or parity mappings so contract changes break tests
visibly.

40. Integration and fault tests
-------------------------------

Use temporary SQLite/filesystem roots plus a separate counting effect fixture. Required
fault points include:

* crash before create/find commit;
* crash after received commit/before received audit;
* audit failure before policy;
* policy deny;
* undeclared ``derived_member_key`` is rejected before any durable binding/operation;
* prepared binding persisted, process restarted, then first use while valid;
* prepared binding persisted, process restarted past expiry ->
  ``prepared_operation_expired`` and no operation;
* prepared binding persisted, process restarted with input/current-state mismatch ->
  ``prepared_operation_mismatch`` and no operation;
* same-boot wall clock rolls backward while monotonic time advances -> no lifetime
  extension/no effect;
* reboot/boot-ID change with untrusted wall clock -> ``trusted_time_unavailable``/no effect;
* trusted wall clock below durable high-water mark -> fail closed/no effect;
* prepared first admission succeeds, then target-state digest changes before final
  boundary verification -> ``prepared_operation_mismatch`` and counting boundary=0;
* prepared first admission succeeds, then preparation expires before final boundary
  verification -> ``prepared_operation_expired`` and counting boundary=0;
* controller trust/profile changes after authorisation before start -> boundary=0;
* device trust/profile changes after authorisation before start -> boundary=0;
* policy/profile digest changes after authorisation before start -> boundary=0;
* cancellation/state-version changes after running marker before start -> boundary=0 and
  no stale overwrite;
* generic target/freshness/reservation/recovery verifier fails -> boundary=0;
* crash after authorised commit/before authorization audit;
* crash after authorization audit/before running transition;
* crash after running transition/before effect-intent audit;
* ``effect.intent_recorded`` append/fsync failure with writable DB -> durable
  ``running -> failed`` known-no-effect, admission disabled, counting boundary=0;
* same audit failure plus DB terminalization failure -> boundary=0 and conservative
  restart treatment rather than fabricated terminal durability;
* crash after running/effect-intent audit but before/during final boundary guard;
* crash after running/effect-intent audit and passed guard but before calling ``start``;
* crash/exception during ``EffectBoundary.start`` before receipt;
* lost response after test effect;
* DB failure after known test effect;
* audit failure after known test effect;
* restart with authorised/running/paused/cancelling/uncertain states;
* running with no external reference must become uncertain unless a separately durable
  no-effect terminalization exists;
* concurrent duplicates from same owner;
* matching key from another owner;
* same key/different fingerprint;
* tombstone replay;
* SQLite busy/lock timeout and migration lock contention;
* DB read-only/disk-full simulation where feasible;
* audit bit flip/delete/reorder/truncation/fork;
* emergency-journal exhaustion;
* payload temp crash/finalize-before-DB orphan;
* DB-complete/payload-missing/digest mismatch;
* payload quota pressure;
* systemd unit permits only declared Phase 4 state/result/audit write roots.

The synthetic counter proves at most one effect for one logical idempotency identity.
Tests never mutate real repository/system state.

41. Fresh-process restart tests
------------------------------

Close every runtime object and reconstruct a fresh application. Verify:

* operation identity/state/version remains resolvable;
* idempotency binding reconciles;
* undeclared ``derived_member_key`` remains rejected after fresh composition and cannot
  acquire a binding merely because in-memory registration state was lost/recreated;
* an unconsumed prepared binding retains expiry, boot/monotonic ordering evidence, and
  exact prepared input/current-state digests across restart;
* same-boot restart still enforces monotonic deadline expiry if wall time rolls backward;
* cross-boot restart requires newly trusted wall time not behind the durable high-water
  mark before an absolute deadline can be treated as still valid;
* first use after restart enforces ``prepared_operation_expired`` /
  ``prepared_operation_mismatch`` / ``trusted_time_unavailable`` before creating an
  operation as applicable;
* a still-valid matching prepared binding can attach exactly one received operation after
  restart;
* after that fresh-process admission, final boundary revalidation recomputes preparation
  expiry/current-state and all applicable current authority/state predicates before the
  fake counting boundary;
* terminal result is stable;
* uncertain remains uncertain without evidence;
* authorised pre-dispatch work is never redispatched;
* dispatch-attempted running work is never converted to known-no-effect merely because a
  receipt is missing;
* persisted external reference is available to a fake reconciler after restart;
* audit sequence/epoch chain continues;
* finalized payload remains digest-valid;
* incomplete/orphan payloads are detected.

Do not reuse in-memory repositories/singletons to simulate restart.

42. Audit contract tests
------------------------

Reuse existing audit cases and add Phase 4 event fixtures for exact payload-kind mapping.
Tests cover RFC 8785 edge cases, exact canonical bytes, event schema validity, hash changes,
insertion/deletion/reorder/truncation/fork, segment/epoch continuity, bounded safe facts,
secret/authority redaction, required runtime identity fields, primary storage failure,
emergency behavior, and fail-restricted admission.

A dedicated test injects ``effect.intent_recorded`` append/fsync failure after the durable
running marker and proves that a writable DB records ``running -> failed`` with
``known_no_effect``/``audit_unavailable`` before the coordinator leaves the path, while the
counting effect boundary remains zero. Another test makes that DB terminalization fail and
proves no effect call occurs and no durable terminal claim is fabricated.

A plan/implementation that emits a top-level ``event_type`` or an unknown
``payload.kind`` fails.

43. Payload tests
-----------------

Cover zero-length/max objects, bounded append chunks, finalize idempotency, append after
finalize rejection, quota overflow before growth, atomic rename/fsync failures, orphan
recovery, complete metadata with missing/corrupt bytes, byte-exact UTF-8/binary content,
information-class preservation, and invalid range requests.

44. Policy and boundary tests
-----------------------------

Production policy tests prove unknown contract, missing controller, protected target, and
broad/unrecognized scopes cannot create allow. Environment/CLI cannot enable wildcard
authority. Fixture policy for synthetic effects is separately composed and cannot ship as
a production bypass.

Boundary tests prove an earlier ``allow`` decision is never treated as perpetual
authority. Every applicable predicate is re-read immediately before the effect boundary;
changed/unavailable trust, policy/profile, target/freshness, reservation, privilege/
credential delegation, interlock, cancellation/supervision, or recovery state suppresses
the call. The fake boundary verifier cannot be reached from the production MCP surface.

45. Migration and deployment tests
----------------------------------

On Python 3.11/3.12/3.13 where applicable:

* fresh ``alembic upgrade head``;
* exact tables/indexes/checks/FKs exist;
* invalid FK inserts fail with foreign keys enabled;
* WAL and synchronous FULL are read back;
* app refuses behind/ahead/unknown revision;
* concurrent live-writer vs migration is rejected;
* downgrade round-trip where safe;
* migration failure leaves original DB recoverable;
* trusted-time durable fields survive upgrade/restart and cannot be reset by ordinary
  startup to bypass rollback detection;
* Phase 3 ``ProtectSystem=strict`` remains active;
* only ``/var/lib/binnacle/state``, ``results``, and ``audit`` are writable additions;
* protected controller config and evaluation evidence permissions are not broadened.

46. Security invariants
-----------------------

Phase 4 must preserve:

#. no production consequential effect adapter;
#. no new mutating MCP Tool/Resource/Task/Prompt;
#. durable global idempotency identity before synthetic effect dispatch;
#. undeclared ``derived_member_key`` cannot create a binding/operation/effect; Phase 4
   admits no derived-member mode until a reviewed parent derivation exists;
#. prepared execution nonces retain durable expiry, boot/monotonic ordering evidence, and
   exact current-state binding before first admission;
#. wall-clock rollback/reboot/loss of trusted time cannot extend operation deadlines;
#. a newly admitted prepared operation revalidates expiry/current state as part of the
   final OP-BOUNDARY guard; stale/unprovable state cannot reach ``EffectBoundary.start``;
#. every operation mode revalidates all applicable OP-BOUNDARY authority/state predicates
   immediately before effect dispatch;
#. a concurrent cancellation/state-version change suppresses dispatch and cannot be
   overwritten by stale transition logic;
#. raw idempotency material never persists/discloses;
#. global duplicate prevention survives controller replacement and tombstoning;
#. operation ownership never transfers from key possession;
#. same key/different input never executes;
#. tombstone replay cannot load/revive an old operation;
#. durable ``running`` dispatch marker exists before effect adapter invocation;
#. required intent-audit failure with writable DB terminalizes the running operation as a
   known-no-effect failure before the audit failure gate; no effect call occurs;
#. missing start receipt cannot be treated as proof of no effect;
#. ``uncertain`` never auto-retries;
#. lifecycle/state-version rules are contract-exact;
#. main app process solely owns authoritative SQLite writes;
#. SQLite durability pragmas are verified;
#. migration cannot race the live writer;
#. audit uses existing schema, JCS+SHA-256, and ``payload.kind`` discriminator;
#. audit redaction precedes persistence/hash;
#. required audit failure blocks new effects;
#. payload cannot claim complete before durable bytes/digest;
#. result/audit state contains no reusable credential;
#. DB/audit/payload roots are not ordinary env/CLI-overridable;
#. systemd grants only narrow declared write paths;
#. policy is fail-closed with no general script/wildcard authority;
#. future executor/broker gets no DB access here;
#. host-facing operation projection remains evidence/contract gated.

47. Quality and CI changes
--------------------------

Extend the existing Python workflow; do not create a competing Phase 4 workflow. Keep all
prior gates and add commands equivalent to:

.. code-block:: console

   uv run alembic upgrade head
   uv run python scripts/verify_operation_kernel.py --temporary
   uv run pytest tests/property
   uv run pytest tests/integration/test_sqlite_operation_store.py
   uv run pytest tests/integration/test_idempotency_concurrency.py
   uv run pytest tests/integration/test_operation_restart_reconciliation.py
   uv run pytest tests/integration/test_audit_failure_gate.py
   uv run pytest tests/integration/test_boundary_revalidation.py
   uv run pytest tests/integration/test_trusted_time_restart.py
   uv run pytest tests/integration/test_payload_integrity.py
   uv run pytest tests/integration/test_phase4_systemd_state_permissions.py

Use isolated temporary roots. CI never writes state into repository paths.

Keep ``pip-audit``, strict MyPy, Ruff/format, Import Linter, branch coverage,
contract/schema validation, registry compiler checks, and explicit 3.11/3.12/3.13 lanes.

48. Canonical local validation commands
---------------------------------------

The implementation PR documents and passes at least:

.. code-block:: console

   uv sync --frozen
   uv run python scripts/compile_mcp_registry.py --check
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests
   uv run lint-imports
   uv run pip-audit
   uv run coverage run -m pytest
   uv run coverage report
   uv run tox -e py311,py312,py313,quality
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py
   uv run alembic upgrade head
   uv run python scripts/verify_operation_kernel.py --temporary

On the development Pi, the operator separately performs the reviewed stop -> ``db
upgrade`` -> ``kernel verify`` -> start sequence.

49. Implementation order
------------------------

Implement Phase 4 in this order:

#. add persistence/JCS dependencies, Alembic skeleton, and deployment write-path changes;
#. define domain types and lifecycle/idempotency/audit contract-parity tests, including
   fail-closed undeclared-derived-member handling;
#. implement migration ``0001`` and SQLite runtime/pragmas/migration locking, including
   trusted-time durable high-water/boot-ordering fields;
#. implement ``TrustedTimeSource``/guard and rollback/reboot/loss-of-trust tests;
#. implement atomic create/find with full/tombstone exact semantics and durable
   prepared-nonce pre-admission registration/expiry/current-state validation;
#. implement state-version transition store;
#. implement fail-closed Bootstrap policy + durable decision recording;
#. implement JCS audit writer/verifier + storage-failure gate and exact payload-kind
   mapping, including no-effect terminalization on pre-dispatch intent-audit failure;
#. implement retained payload filesystem adapter + metadata consistency;
#. implement mandatory generic/operation-specific OP-BOUNDARY revalidation;
#. implement ``OperationCoordinator`` through durable running dispatch marker, intent
   audit, final boundary revalidation, and unavailable production effect boundary;
#. implement synthetic counting effect/reconciler/prepared-state/boundary verifiers only
   in tests;
#. implement restart reconciliation and cancellation semantics;
#. add local DB/kernel/audit operator commands;
#. add property, crash-window, trusted-time, boundary, restart, audit, payload, migration,
   and systemd tests;
#. integrate internal kernel health without changing MCP Tool surface;
#. update CI/lock/import rules;
#. run full exact-interpreter validation;
#. stop before any host-facing write/status/cancel/result promotion.

50. Review checklist
--------------------

A reviewer verifies:

* Phase 4 only; no Phase 5 design or Tool promotion;
* host-facing projection remains provisional/evidence-gated;
* persistence stack matches Bootstrap baseline;
* one authoritative SQLite writer and no executor/broker DB access;
* version-1 received creation and lifecycle edges match contracts;
* idempotency unique scope is non-null and contract-exact;
* undeclared ``derived_member_key`` fails closed before binding/operation creation;
* prepared nonce registration durably binds prepared operation/input, expiry, exact
  current-state digest, boot identity, and monotonic deadline ordering;
* same-boot rollback and cross-boot untrusted/rolled-back wall time cannot extend the
  prepared lifetime;
* prepared expiry/mismatch behavior survives fresh-process restart and uses the reviewed
  ``prepared_operation_expired`` / ``prepared_operation_mismatch`` codes when those facts
  are provable;
* loss of trusted time fails closed rather than pretending a nonce remains valid;
* final OP-BOUNDARY revalidation applies to **all** operation modes, not only prepared
  nonces, and rechecks every applicable authority/state/cancellation/recovery predicate;
* a concurrent state/version change is not overwritten by stale dispatch failure logic;
* tombstones contain exactly the required duplicate-prevention facts and return retired;
* raw keys never persist;
* audit authorization and durable running dispatch marker precede effect invocation;
* ``effect.intent_recorded`` audit failure before dispatch terminalizes running work as
  known-no-effect when DB durability remains available and never calls the boundary;
* a lost start receipt becomes uncertain, not known-no-effect;
* same-key conflict/cross-controller cases cannot create effect;
* persisted effect reference permits restart reconciliation;
* audit schema ``payload.kind`` and required fields are exact;
* DB/audit are not falsely one transaction;
* audit failure blocks new effects;
* payload completion is durable/digest truthful;
* Bootstrap policy is minimal/fail-closed;
* migrations are explicit and cannot race live service;
* systemd write authority is narrow under ``ProtectSystem=strict``;
* current five read-only MCP Tools remain unchanged;
* exact-head quality/CI passes.

51. Deterministic acceptance checklist
--------------------------------------

Phase 4 implementation is accepted only when every item is true:

#. persistence/JCS dependencies are locked and support Python 3.11--3.13;
#. Alembic ``0001`` creates exactly the Phase 4 authoritative schema;
#. runtime never silently creates/migrates tables;
#. DB path is local/protected/separate from source/config/evaluation evidence;
#. systemd setup creates and grants only state/results/audit write roots;
#. every DB connection verifies foreign keys, WAL, FULL synchronous, and busy timeout;
#. migration mismatch/unavailable audit keeps consequential kernel unavailable;
#. live writer and ``db upgrade`` cannot run concurrently;
#. ``kernel_meta`` binds stable device epoch, schema-compatible audit epoch continuity,
   and durable trusted-time high-water/boot-ordering evidence;
#. controller ownership rows contain no reusable credential;
#. lifecycle state vocabulary/edges exactly match ``spec/operation/lifecycle.yaml``;
#. version 1 is ``NULL -> received`` and every later transition increments once;
#. invalid/stale transitions are rejected;
#. global idempotency index exactly matches contract scope with non-null key columns;
#. ``derived_member_key`` is rejected as ``idempotency_invalid`` before durable binding/
   operation creation until a reviewed parent contract/derivation exists;
#. raw caller key/prepared nonce never persists/logs/audits;
#. an unconsumed prepared nonce is durably registered with owner/device/Tool/contract,
   prepared operation/input, expiry, exact current-state binding, boot identity, and
   same-boot monotonic deadline before first use;
#. first use of an expired prepared nonce returns ``prepared_operation_expired`` and
   creates no operation/effect;
#. prepared operation/input/current-state mismatch returns
   ``prepared_operation_mismatch`` and creates no operation/effect;
#. same-boot wall-clock rollback cannot extend a prepared lifetime;
#. reboot/loss of trusted wall time or a wall time behind durable high-water fails closed
   without creating/crossing an effect;
#. fresh-process restart preserves and re-enforces prepared expiry/mismatch/time-ordering
   checks;
#. valid prepared first admission atomically attaches exactly one version-1 operation;
#. before that newly admitted prepared operation crosses an effect boundary, expiry and
   exact current-state digest are recomputed/revalidated again;
#. every non-prepared operation also performs the complete applicable OP-BOUNDARY
   revalidation immediately before ``EffectBoundary.start``;
#. changed controller/device trust, policy/profile, state version/cancellation,
   target/freshness/reservation/privilege/interlock/recovery state suppresses the effect
   call when applicable;
#. a concurrent lifecycle change cannot be overwritten by a stale no-effect failure;
#. a later retry of an already admitted/dispatched prepared nonce returns retained work
   rather than creating or redispatching a fresh operation when preparation has expired;
#. concurrent same-key admission creates one binding/operation;
#. same owner + same key + same fingerprint returns retained operation;
#. same key + different fingerprint returns conflict/no second operation;
#. different controller + matching key reveals no old operation and creates no effect;
#. tombstone retains key/tool/contract/owner digest/fingerprint/terminal class/retired time;
#. tombstone replay returns ``idempotency_key_retired`` without loading an operation;
#. production policy denies unknown/unreviewed consequential contracts;
#. policy decision is durable before authorization/effect;
#. received/authorization/effect-intent audit records are schema-valid and durable at the
   defined gates;
#. durable ``running`` transition occurs before every effect-boundary call;
#. pre-dispatch ``effect.intent_recorded`` audit failure with writable DB commits a
   ``running -> failed`` known-no-effect outcome and calls no effect boundary;
#. inability to commit that failure still calls no boundary and is reconciled
   conservatively after restart;
#. crash/lost response during ``start`` cannot become a known-no-effect assertion;
#. production composition has no real effect adapter;
#. synthetic effect proves at most one effect under concurrency/response loss;
#. restart never redispatches automatically;
#. running-without-receipt/reference becomes or remains uncertain unless separate durable
   no-effect evidence exists;
#. persisted opaque external reference can be reconciled after restart;
#. cancellation cannot claim cancelled without verification;
#. audit canonicalization is exact RFC 8785 JCS + SHA-256;
#. audit uses only schema-supported ``payload.kind`` values and all required fields;
#. audit chain detects modification/deletion/reorder/truncation/fork;
#. audit failure disables new consequential admission;
#. emergency journal is bounded/fail-restricted;
#. payload bytes are atomically finalized/fsynced/digest-verified before complete metadata;
#. payload orphan/corruption/quota pressure is detected without silent completeness;
#. operation evidence is bounded and not authoritative audit storage;
#. fresh-process restart reconstructs DB/idempotency/audit/payload/trusted-time truth;
#. local DB/kernel/audit commands expose no secrets/raw payloads and migration is safe;
#. existing Phase 3 authenticated read-only MCP behavior remains regression-tested;
#. no MCP Tool/Resource/Task/Prompt/manifest change exposes Phase 4 APIs;
#. no workspace/command/Git/package/service/privileged/hardware effect capability exists;
#. Ruff/format/strict MyPy/Import Linter/coverage/``pip-audit`` pass;
#. property/fault/migration/integration/systemd tests pass on explicit interpreter lanes;
#. contract/schema/compiler validation passes;
#. GitHub Actions is green for the exact implementation head.

52. Provisional freeze points after Phase 3 evidence
----------------------------------------------------

Before a later phase exposes the kernel through ChatGPT, re-check real Phase 3 evidence
and freeze only host-dependent projection items actually supported by it: status/result
interaction, effective result limits, authenticated scope/profile mapping, confirmation
requirements, optional Tasks/Resources, catalogue refresh, and host retry/reconnect
behavior.

If Phase 3 evidence is absent, expired, or contradictory, internal Phase 4 implementation
may pass its kernel tests but no host-facing consequential projection is promoted.

53. Planning stop rule
----------------------

This plan is complete when a coding agent can implement/test authoritative SQLite state,
exact lifecycle/idempotency semantics, safe tombstones, trusted-time deadline ordering,
mandatory consequential-boundary revalidation, minimal policy, schema-valid append-only
audit, retained payload/evidence storage, durable pre-dispatch state, reconciliation,
local diagnostics, deployment permissions, migrations, and fault/property tests without
deciding later operation-specific authority or host behavior.

Stop here. Do not add the disposable write-probe workflow or any later operational
capability in this document.
