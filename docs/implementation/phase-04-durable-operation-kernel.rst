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
* a per-operation application dispatch-handoff gate that serializes final revalidation/
  effect submission with cancellation and other pre-start lifecycle mutation;
* filesystem retained payloads with SQLite authoritative metadata;
* append-only RFC 8785 JCS + SHA-256 audit hash chaining with one frozen first-store
  genesis predecessor digest;
* one process-wide serialized audit append/tail-allocation gate, with the verified journal
  tail as allocator authority and SQLite tail fields only as a recoverable cache;
* audit-before-effect gating and fail-restricted audit failure behavior with a durable
  failure-generation latch that survives restart until explicit verified recovery;
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
* a tombstone lookup verifies the authenticated owner against its retained owner digest
  before revealing retirement: another controller receives non-disclosing
  ``idempotency_owner_mismatch`` while the matching owner receives
  ``idempotency_key_retired`` without loading an operation;
* prepared-nonce full-record compaction clears every preparation-only field while
  retaining the exact tombstone duplicate-prevention facts required by the idempotency
  contract, and database checks reject prepared-only state on a tombstone;
* an expired unconsumed prepared nonce already has its contract request fingerprint
  durably bound, is durably classified ``prepared_operation_expired`` without creating an
  operation, and can later compact to a contract-exact tombstone after the required
  retention window;
* an unconsumed ``prepared_execution_nonce`` durably retains its prepared operation/input,
  request fingerprint, expiry, exact current-state binding, registration boot identity,
  and same-boot monotonic deadline evidence before any new operation can be admitted;
* prepared-nonce expiry and prepared input/current-state/fingerprint mismatch remain
  enforceable after a fresh-process restart, returning ``prepared_operation_expired`` or
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
* final revalidation and the call/receipt handoff to ``EffectBoundary.start`` are
  serialized with cancellation so a ``running -> cancelling`` transition cannot commit
  between the final lifecycle check and a stale new start;
* a final-boundary authority/state failure cannot call the effect adapter or overwrite a
  concurrently changed lifecycle state;
* ``derived_member_key`` is rejected before binding/operation creation in Phase 4 because
  no reviewed parent contract/derivation is registered yet;
* tombstones retain the contract-required non-reversible owner digest and terminal class;
* raw idempotency keys are never persisted, logged, audited, or used as metric labels;
* lifecycle transitions reject every undeclared edge/cross-field combination;
* ``state_version`` starts at 1 and strictly increases exactly once per real transition;
* stale optimistic updates cannot silently overwrite newer state;
* the Phase 4 policy schema has one exact non-circular layout: ``policy_decisions`` owns a
  ``NOT NULL UNIQUE`` FK to ``operations`` and ``operations`` has no reverse policy FK or
  current-decision column;
* every operation that leaves ``received`` has exactly one durable admission decision;
  restart recovery creates an explicit fail-closed recovery deny atomically with rejection
  when a crash left a received operation without one;
* final OP-BOUNDARY policy revalidation does not mutate or replace the admission record;
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
* the first event of a brand-new store uses sequence 1 and the exact Phase 4 genesis
  ``previous_event_hash`` derived from the domain-separated preimage in section 12.1;
  schema-valid placeholder digests are not accepted as store-genesis continuity;
* concurrent audit appenders are serialized from tail read/allocation through write/fsync,
  segment rotation, and in-memory tail publication, so no two events can claim the same
  sequence/predecessor;
* the verified append-only journal tail, not ``kernel_meta.audit_last_*``, is the next-
  event allocator authority; SQLite tail metadata is updated only after journal fsync and
  startup safely repairs a merely-behind cache while treating an ahead/divergent cache as
  integrity failure;
* a required audit failure durably latches a monotonically identified failure generation
  whenever SQLite is writable; fresh-process startup never clears that latch merely
  because surviving journal bytes verify, and consequential admission remains disabled
  until explicit recovery for that exact generation has schema-valid fsynced recovery
  evidence and the durable latch is cleared;
* audit payloads use exact existing ``payload.kind`` discriminators, and pre-operation or
  tombstone idempotency abuse/conflict evidence never fabricates operation state/version
  fields solely to fit ``operation.idempotency_conflict``;
* audit corruption, truncation, fork, or storage failure blocks new effects;
* bounded recovery/status/verification remains possible where underlying stores remain
  trustworthy;
* retained payload metadata cannot disagree silently with filesystem bytes;
* payload writes are atomic/finalized or explicitly incomplete;
* Bootstrap policy is fail-closed and durably correlated with the operation;
* systemd hardening still permits only the new declared state/result/audit write paths,
  recreates the application-owned ephemeral ``/run/binnacle`` lock directory on service
  start/boot, and preserves that protected runtime directory across the ordinary service
  stop used by the offline migration runbook;
* the stopped-service ``binnacle db upgrade`` path can acquire the same protected
  runtime/migration lock without privileged recreation or a fallback lock location;
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
      -> acquire per-operation dispatch-handoff gate shared with cancellation
      -> final OP-BOUNDARY revalidation for every operation mode
           -> trusted-time/deadline guard where applicable
           -> prepared expiry/current-state guard where applicable
           -> current controller/device trust, policy/profile, lifecycle/cancellation,
              target/freshness/reservation/recovery checks where applicable
      -> effect boundary submission/receipt handoff while still holding that gate
         (test-only in Phase 4; real adapters later)
      -> persist returned reference/effect knowledge/result metadata
      -> release dispatch-handoff gate
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

``/run`` is tmpfs/ephemeral and the Phase 3 setup-time creation of ``/run/binnacle`` does
not survive a normal reboot. Phase 4 therefore updates ``binnacle-dev.service`` to use
``RuntimeDirectory=binnacle``, ``RuntimeDirectoryMode=0750``, and
``RuntimeDirectoryPreserve=yes`` (or an exactly equivalent systemd-managed declaration)
so systemd recreates the directory before the service starts and owns it as the configured
non-root service identity/group. ``RuntimeDirectoryPreserve=yes`` is required rather than
``restart`` because the reviewed offline-migration runbook performs an ordinary service
stop: that stop must leave the protected runtime directory in place so the same non-root
operator identity can acquire the migration lock. The directory may still disappear with
``/run`` on reboot; the next service start recreates it before application startup.

The runtime directory contains only ephemeral locks/control state; preservation across a
normal stop does not make it durable evidence and it is never used as correctness
authority after process restart. Do not solve stopped-service migration with a broad
writable ``/run`` exception, a privileged pre-start shell command, or an alternate lock
path.

Phase 3 uses ``ProtectSystem=strict``. Therefore Phase 4 must explicitly update
``binnacle-dev.service`` so the service can write **only** the new declared durable paths.
Prefer narrow ``ReadWritePaths=`` entries for:

::

   /var/lib/binnacle/state
   /var/lib/binnacle/results
   /var/lib/binnacle/audit

rather than making all of ``/var/lib`` or all of ``/var/lib/binnacle`` writable. The
systemd-managed ``/run/binnacle`` directory supplies the separate narrow ephemeral write
location required by the runtime/migration lock. Do not weaken ``NoNewPrivileges``,
capability bounds, protected config permissions, or source checkout separation merely to
make persistence work.

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
non-blockingly and refuse migration while a live application writer holds it. On a
systemd service start, ``RuntimeDirectory=binnacle`` guarantees this parent exists with the
service identity's narrow write permission even after reboot. The same unit also requires
``RuntimeDirectoryPreserve=yes``, so the normal ``systemctl stop binnacle-dev.service`` in
the reviewed offline-upgrade sequence does not remove that parent before the non-root
migration command runs. ``RuntimeDirectoryPreserve=restart`` is insufficient because the
runbook uses an explicit stop, not only a restart.

The stopped-service ``binnacle db upgrade`` command verifies that the protected runtime
directory exists with the expected owner/group/mode and acquires the same lock there. If
the directory is absent or ownership/mode is unsafe, upgrade fails closed with an
operator-facing setup/start instruction; it never creates a privileged runtime directory,
silently falls back to another lock location, or weakens ``/run`` permissions. After a
reboot the first service start recreates ``/run/binnacle`` before application startup; if
that startup reports migration-required, the subsequent stop preserves the directory for
the offline upgrade. The operator runbook stops ``binnacle-dev.service`` before
production/development-Pi upgrade. This lock prevents concurrent schema migration; it is
**not** used as idempotency or normal DB-transaction correctness authority.

11. Database transaction rules
------------------------------

SQLite and external Linux effects are never described as one ACID transaction.

Rules:

* one ``AsyncSession`` per application use-case transaction;
* no long external I/O while holding a SQLite write transaction;
* create-or-find admission uses a short explicit write transaction;
* SQLite uniqueness/conflict handling, not a Python process mutex, is duplicate-prevention
  authority;
* the narrow per-operation ``DispatchHandoffGate`` is application concurrency control for
  lifecycle/cancellation versus the final effect handoff only; it is not idempotency,
  authorization, or cross-process durability authority;
* no SQLite write transaction remains open while final boundary verifiers or
  ``EffectBoundary.start`` perform external I/O;
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
* ``audit_failure_generation`` integer >= 0, default 0;
* ``audit_failure_latched`` boolean, default false;
* ``audit_failure_reason_code`` nullable bounded identifier, required while the latch is
  active;
* ``audit_failure_detected_at`` nullable UTC timestamp, required while the latch is active;
* ``audit_recovered_generation`` integer >= 0, default 0 and never greater than
  ``audit_failure_generation``;
* ``audit_recovery_evidence_sha256`` nullable SHA-256 of the fsynced schema-valid recovery
  event that cleared the latest recovered generation;
* ``trusted_wall_time_high_watermark`` nullable UTC timestamp until trusted time is first
  established;
* ``trusted_time_boot_id_digest`` nullable SHA-256;
* ``trusted_time_monotonic_ns`` nullable non-negative integer for the last trusted sample
  in that boot;
* ``trusted_time_generation`` integer >= 1, incremented on an explicitly accepted new
  boot/trust epoch;
* ``consequential_admission_enabled`` boolean, default false.

The audit-failure fields form a durable fail-restricted latch, not a diagnostic cache.
Database checks require ``audit_failure_latched=true`` to imply
``audit_failure_generation > audit_recovered_generation`` plus non-null reason/time. A
cleared nonzero generation requires ``audit_recovered_generation =
audit_failure_generation`` and non-null ``audit_recovery_evidence_sha256``. A fresh store
has generation/recovered-generation 0, latch false, and no recovery digest. A new required
audit failure after a prior recovery increments ``audit_failure_generation`` before it can
be treated as a new latched outage; while an outage is already latched, additional failures
remain in that generation rather than manufacturing recovery progress.

``audit_last_sequence`` and ``audit_last_hash`` are a derived SQLite cache for diagnostics
and consistency checks, **not** the audit allocation/source-of-truth tail. The verified
append-only journal bytes own the authoritative tail. A cache pair may advance only after
the corresponding journal event bytes and any required segment metadata are durably
fsynced. Startup re-verifies the journal first and reconstructs its tail before trusting
these fields: a cache that is merely behind is refreshed in a short SQLite transaction
after continuity is proven; a cache that is ahead of the verified journal, or has a
different hash for the same sequence, is ``audit_integrity_failed`` and fail-restricted.
No append allocates its next sequence or ``previous_event_hash`` from this cache.

The trusted-time fields are ordering/safety evidence, not a clock-repair mechanism.
Within one boot, a monotonic source prevents a wall-clock rollback from extending a
recorded deadline. Across reboot, monotonic values are never compared between boots; the
new wall time must be independently trusted and may not move behind the durable trusted
wall-time high-water mark. If trust or ordering cannot be established, time-dependent
consequential predicates fail closed.

The audit serializer never emits an integer ``audit_epoch`` because the existing audit
event schema requires an identifier. Initial event sequence is 1. The first event in the
first audit epoch of a brand-new store has no real predecessor but the schema requires a
64-hex ``previous_event_hash``. Phase 4 therefore freezes this exact domain-separated
store-genesis convention:

::

   preimage bytes:  ASCII/UTF-8 "binnacle.audit.genesis.v1" followed by one 0x00 byte
   preimage hex:    62696e6e61636c652e61756469742e67656e657369732e763100
   SHA-256:         a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632

For exactly ``audit_epoch_generation=1`` / sequence 1 with no accepted predecessor, the
writer sets ``previous_event_hash`` to that SHA-256 value and the verifier requires it.
The genesis digest is not an event hash and is never reused merely because of restart,
segment rotation, or a later audit epoch. Every later event uses its real predecessor; a
later epoch transition follows the reviewed accepted epoch/segment continuity evidence.
The existing audit-integrity fixture's all-``f`` predecessor is a schema-valid placeholder,
not the Phase 4 genesis protocol value: schema validation may accept that fixture shape,
but a Phase 4 chain verifier must reject it as first-store genesis. Writer/verifier tests
share this exact vector so independent implementations cannot choose private sentinels.

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
* ``request_fingerprint_sha256`` **NOT NULL** for every full or tombstone binding,
  including an unconsumed prepared nonce; prepared registration computes/binds it before
  first execution;
* ``prepared_operation_id`` required only when
  ``record_kind=full`` and ``key_mode=prepared_execution_nonce`` and the record has not
  yet been compacted;
* ``prepared_input_sha256`` required only when
  ``record_kind=full`` and ``key_mode=prepared_execution_nonce`` and the record has not
  yet been compacted;
* ``prepared_expires_at`` required only when
  ``record_kind=full`` and ``key_mode=prepared_execution_nonce`` and the record has not
  yet been compacted;
* ``prepared_state_binding_sha256`` required only when
  ``record_kind=full`` and ``key_mode=prepared_execution_nonce`` and the record has not
  yet been compacted;
* ``prepared_registered_boot_id_digest`` required only when
  ``record_kind=full`` and ``key_mode=prepared_execution_nonce`` and the record has not
  yet been compacted;
* ``prepared_monotonic_deadline_ns`` required for a full prepared nonce created in the
  current boot; it is meaningful only when boot IDs match;
* ``target_identity_sha256`` nullable;
* ``maximum_effect_sha256`` nullable;
* ``operation_id`` FK nullable only for a valid tombstone or an unconsumed
  ``prepared_execution_nonce`` full binding;
* ``terminal_class`` nullable for an active full record; for an unconsumed prepared nonce
  whose expiry has been durably proven it is the existing reviewed
  ``prepared_operation_expired`` class, and it is required for every tombstone;
* ``created_at`` / ``last_access_at``;
* ``terminal_at`` nullable for active full records; for a proven-expired unconsumed
  prepared nonce it records the protected expiry/terminal fact used for retention;
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
exact prepared input digest, the canonical effect-bearing request fingerprint required by
``spec/operation/idempotency.yaml``, expiry timestamp, expected current-state binding
digest, owner/device/Tool/contract scope, nonce digest, registration boot identity, and the
same-boot monotonic deadline needed to prevent wall-clock rollback from extending the
nonce. The fingerprint is computed from the reviewed normalized effect inputs including
prepared operation/input and target/maximum-effect facts; mutable current observations and
policy results remain excluded exactly as the contract requires. This is persistence
infrastructure only: Phase 4 adds no MCP/CLI preparation endpoint and no production
prepare/execute workflow.

Database checks permit a full row with ``operation_id=NULL`` only for that unconsumed
prepared-nonce shape and require all prepared semantic fields plus the request fingerprint
for a full prepared record. Other full rows require an operation ID. Prepared fields are
rejected for non-prepared key modes. A proven-expired unconsumed prepared full record may
retain ``operation_id=NULL`` with ``terminal_class=prepared_operation_expired`` and its
protected ``terminal_at`` fact until the full-record retention window permits explicit
compaction. Every tombstone, including one whose historical ``key_mode`` is
``prepared_execution_nonce``, requires all preparation-only fields to be NULL; tombstone
checks therefore depend on ``record_kind`` rather than key mode alone. Successful first
admission atomically creates the version-1 operation and attaches its ``operation_id`` to
the existing prepared binding without rewriting the registration fingerprint.

When trusted-time checks prove an unconsumed prepared nonce has expired, the same short
binding transaction durably records ``terminal_class=prepared_operation_expired`` and the
protected terminal/expiry fact before returning ``prepared_operation_expired``; no
operation is created. Repeated first-use attempts during full retention return the same
prepared-expired outcome. A retention/compaction pass may also prove expiry for a never-
retried unused nonce; if trusted time cannot prove it, compaction fails closed and retains
the full record rather than guessing.

The full row owns controller ID/epoch; the tombstone contract requires only the
non-reversible owner digest. Full-to-tombstone compaction, when explicitly exercised
after the required retention window, has two contract-safe sources. For an attached
operation it atomically verifies terminal operation state; for an unconsumed prepared
nonce it requires the durable/proven ``prepared_operation_expired`` terminal class and no
operation. Both paths write ``retired_at``, retain the contract-required key digest,
``tool_name``, ``contract_version``, owner digest, request fingerprint and terminal class
plus the table's device/epoch uniqueness scope, clear ``operation_id`` and raw owner
ID/epoch, and clear every preparation-only field. They must not retain prepared operation,
input, expiry, current-state, boot, or monotonic-deadline data in a tombstone. Once
compacted, same-owner replay follows the machine-readable tombstone outcome
``idempotency_key_retired`` rather than exposing the former preparation detail. Phase 4
implements only explicit operator/test compaction, not broad automatic purge.

12.6 ``policy_decisions``
~~~~~~~~~~~~~~~~~~~~~~~~~

Store exactly one durable admission decision for every operation before it leaves
``received``:

* ``policy_decision_id`` PK;
* ``operation_id`` **NOT NULL** FK to ``operations(operation_id)`` with a named
  ``UNIQUE(operation_id)`` constraint;
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

The Phase 4 layout is fixed: ``policy_decisions.operation_id`` is the sole relational
reference between these tables. ``operations`` has **no** ``policy_decision_id`` column
and no reverse policy FK. During normal admission, the one-to-one decision is inserted
after the version-1 operation exists and before ``received -> authorised`` or ``received
-> rejected``; it is retrieved by joining/querying ``policy_decisions`` on
``operation_id``. A just-created ``received`` operation may therefore transiently have no
decision while its policy evaluation is in progress, but no transaction may move it out
of ``received`` without a durable decision. The unique constraint rejects a second
admission decision for the same operation and the FK rejects an orphan decision.

Restart is the fail-closed completion of that invariant, not an exception to it. If
reconciliation finds ``received`` with no admission decision after audit recovery is
writable, one short SQLite transaction inserts a reserved internal recovery decision with
``decision=deny`` and reason ``restart_before_admission`` and commits the legal
``received -> rejected`` transition/version row atomically. The row uses the protected
current Bootstrap recovery-policy identity/digest and retained normalized input facts; it
does not pretend the interrupted original policy evaluation completed and it does not
resume external effect/admission work. If a decision row already exists, reconciliation
must not insert a second one; it rejects the still-``received`` interrupted operation using
that retained admission evidence plus the separate ``restart_before_admission`` recovery
reason. Failure to commit the required decision/transition leaves the operation
``received`` and consequential readiness blocked rather than producing a terminal record
with zero decisions.

Final OP-BOUNDARY policy revalidation is a fresh current-policy check, not a second
admission decision and not an update/replacement of this row. Its current result is
represented by the boundary outcome and schema-valid audit/evidence. If a later reviewed
phase needs policy-decision history or multiple persisted revalidation decisions, that
phase must introduce an explicit migration and semantics; migration ``0001`` does not
leave that choice to the implementer.

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
``controller_owners`` first; ``operations`` next; then ``operation_transitions``,
``idempotency_bindings``, ``policy_decisions``, ``payload_objects``, and
``operation_evidence``. ``policy_decisions`` has the one-way ``NOT NULL`` FK to
``operations`` plus ``UNIQUE(operation_id)``; there is no reverse operations-to-policy
reference and therefore no circular policy FK graph. Migration tests inspect actual
SQLite FK/unique/check metadata and perform negative inserts. Do not assume ORM
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
``prepared_input_sha256``, the canonical ``request_fingerprint_sha256`` for the prepared
effect-bearing request, ``prepared_expires_at``, ``prepared_state_binding_sha256``,
registration boot identity, and same-boot monotonic deadline. Registration itself
requires a trusted-time snapshot; if that cannot be established, no prepared binding is
created. The raw nonce is never persisted.

The registration fingerprint is computed by the same reviewed operation-specific
normalizer that will be used at first execution. It includes the contract fields from
``spec/operation/idempotency.yaml`` and excludes mutable current observations/policy
results. The generic store never reconstructs or guesses it later. This lets an unused
prepared nonce retain the request-fingerprint fact required by a future tombstone even if
no operation is ever created.

The operation-specific future caller is responsible for computing the exact current-state
binding under its reviewed preparation contract. It supplies that digest at first
admission **and** provides a narrow state-verification callback/port that can recompute the
current digest immediately before a consequential boundary. The generic kernel compares
digests; it does not invent filesystem, command, Git, or other current-state semantics.
If the durable prepared binding or final verifier cannot be loaded/executed truthfully,
the prepared operation fails closed without effect.

Preparation expiry, exact prepared operation/input, request fingerprint, current-state
binding, and trusted time ordering are checked before first operation admission. For a
newly admitted prepared operation that is still on its first dispatch path, expiry and
current state are checked again as part of the final OP-BOUNDARY guard immediately before
``EffectBoundary.start``.

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
#. if present and ``record_kind=tombstone`` or ``retired_at`` is set, compare the
   authenticated controller/epoch through the same domain-separated owner digest retained
   by compaction **before** disclosing retirement or loading any operation; a digest
   mismatch increments only bounded conflict/abuse evidence and returns non-disclosing
   ``idempotency_owner_mismatch``; a matching digest returns
   ``idempotency_key_retired`` without loading/disclosing an operation;
#. for a present full record, verify owner before disclosing preparation or operation
   details; another controller returns non-disclosing ``idempotency_owner_mismatch``;
#. if the full record is an unconsumed prepared-nonce binding with ``operation_id=NULL``
   and is already durably marked ``terminal_class=prepared_operation_expired``, return
   ``prepared_operation_expired`` with no operation/effect;
#. if the full record is an active unconsumed prepared-nonce binding with
   ``operation_id=NULL``, obtain a ``TrustedTimeGuard`` decision; inability to prove safe
   time ordering returns ``trusted_time_unavailable`` with no operation created; a proven
   elapsed deadline durably marks the binding ``prepared_operation_expired`` in the same
   short transaction and returns ``prepared_operation_expired`` with no operation;
#. for that active unconsumed prepared binding, compare the supplied prepared operation
   ID, exact input digest, canonical request fingerprint, and current-state binding digest
   against the durable values; any mismatch returns ``prepared_operation_mismatch`` with
   no operation created;
#. after all prepared checks pass, atomically create the version-1 ``received`` operation
   and attach its ``operation_id`` to the existing prepared binding without rewriting its
   request fingerprint, then continue only that newly admitted operation;
#. for a present full record already attached to an operation, verify fingerprint;
#. same owner + same fingerprint -> return the retained operation, including terminal or
   ``uncertain`` state, with no effect;
#. same owner + different fingerprint -> increment conflict count and return
   ``idempotency_conflict``;
#. different controller -> increment conflict count and return non-disclosing
   ``idempotency_owner_mismatch``;
#. commit;
#. only a newly created/attached full operation proceeds to policy/admission.

The tombstone branch still occurs before any retained-operation load because a valid
tombstone may have ``operation_id=NULL``. Within that branch, however, owner-digest
verification occurs before the retirement outcome: cross-controller matching keys return
``idempotency_owner_mismatch`` and only the matching owner receives
``idempotency_key_retired``. No code attempts to load or disclose a retired operation from
a tombstone.

Prepared expiry/input/fingerprint/current-state/trusted-time checks before first admission
use durable fields that survive process restart. They are not bypassed by reconstructing a
fresh application. After an operation is attached, normal retained-operation idempotency
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

The final guard and the actual submission handoff are serialized with cancellation by a
small application-layer ``DispatchHandoffGate`` keyed by ``operation_id``. The coordinator
acquires that gate **before** the final OP-BOUNDARY revalidation and retains it through the
``EffectBoundary.start`` attempt and immediate durable capture/classification of the
returned receipt/reference/effect knowledge. ``OperationService.request_cancel`` and any
other application path allowed to move that same pre-start ``running`` operation away from
the expected version must acquire the same gate before committing its lifecycle change.

This is intentionally not a SQLite or distributed lock. Phase 4 has one authoritative
application writer. No SQLite transaction is held while boundary verifiers or the effect
adapter perform external I/O. The gate only removes the in-process check-then-start race:

* if cancellation acquires the gate first and commits ``running -> cancelling``, the later
  coordinator revalidation observes the changed state/version and suppresses ``start``;
* if the coordinator acquires the gate first, cancellation waits until the bounded start
  handoff has been attempted and its immediate receipt/uncertainty/reference knowledge has
  been durably classified; cancellation then re-reads current state/version and follows
  only the lifecycle edges that remain legal;
* therefore no ``EffectBoundary.start`` invocation may begin **after** a cancellation
  transition for that expected running version has committed;
* process crash drops the in-memory gate but cannot erase the durable running marker,
  intent audit, or effect knowledge already committed; startup therefore follows the
  conservative reconciliation rules rather than redispatching.

``EffectBoundary.start`` is a bounded submission/handoff operation, not the lifetime of a
long-running effect. Independently supervised work continues outside this gate. An adapter
that cannot bound its submission handoff is not composable as a reviewed consequential
boundary until it supplies a safe handoff/reconciliation contract.

The final guard is the last potentially blocking/revalidating work before
``EffectBoundary.start``. After it returns success, the coordinator performs no unrelated
I/O or policy work before the call; the shared dispatch gate remains held across that
check-to-call handoff.

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
#. for retained/conflict/owner-mismatch/retired outcomes, return without effect after any
   required schema-valid bounded idempotency abuse/conflict audit described in section 28;
#. append/fsync a schema-valid audit event with
   ``payload.kind=operation.state_changed``, ``old_state=null``,
   ``new_state=received``, ``state_version=1``, ``effect_knowledge=none``, and a bounded
   reason code such as ``operation_received``;
#. evaluate policy;
#. durably persist the operation's one admission policy decision;
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
   ``known_no_effect`` and ``audit_unavailable``, latch the current audit-failure generation
   and disable consequential admission, then record emergency/recovery evidence where the
   existing audit contract permits; if the DB terminalization/latch itself cannot be
   committed, leave no in-memory claim of a durable terminal/recovery state and let restart
   use the conservative running/fail-restricted path;
#. acquire the per-operation ``DispatchHandoffGate`` shared with cancellation/pre-start
   lifecycle mutation;
#. while holding the gate, run the mandatory final OP-BOUNDARY revalidation from section
   19 for **every** operation mode, including trusted-time and prepared expiry/current-
   state checks where applicable;
#. on final-guard failure, suppress the boundary call, follow the no-effect/concurrent-
   state behavior defined in section 19, and release the gate only after that result is
   durably classified as far as the stores permit;
#. **only after all applicable final boundary checks pass and while still holding the
   gate** call ``EffectBoundary.start`` with an ``EffectRequest`` containing the operation
   ID and running state version as stable dispatch identity;
#. while still holding the gate, durably persist/classify the returned no-crossing/
   crossed/reference/outcome knowledge and the bounded recoverable opaque reference when
   one exists; a lost/exceptional receipt remains dispatch-attempted uncertainty;
#. release the dispatch-handoff gate; a waiting cancellation then re-reads current
   state/version and may use only the lifecycle-declared next edge;
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

``DispatchHandoffGate`` is an application-only keyed async mutual-exclusion primitive,
not an effect/DB port and not durable authority. Both the coordinator's final
revalidate/start/receipt-classification handoff and ``request_cancel`` use the same key.
The implementation must bound gate ownership and clean up idle per-operation entries so a
cancel request cannot deadlock or leak unbounded lock objects. Crash recovery never trusts
the vanished in-memory gate; it trusts only durable state/audit/effect evidence.

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

* ``received`` with no admission decision -> after required recovery audit is writable,
  atomically insert the reserved fail-closed recovery ``deny`` decision with
  ``restart_before_admission`` and commit ``received -> rejected``; if either write cannot
  commit, leave it received and keep consequential readiness blocked;
* ``received`` with its one durable admission decision already present -> do not create a
  second decision; reject the interrupted operation with ``restart_before_admission``
  using the retained decision plus recovery evidence, and never resume admission/effect;
* ``authorised`` -> ``failed`` with ``known_no_effect`` because coordinator invariants
  prohibit calling the effect adapter before the durable transition to ``running``;
* ``running``/``paused``/``cancelling`` with a durable recoverable external reference ->
  ask ``EffectReconciler``;
* a process that failed ``effect.intent_recorded`` and successfully committed
  ``running -> failed`` before exit is already terminal and is not reclassified as
  uncertain, but its independently durable audit-failure latch still blocks consequential
  admission until same-generation recovery evidence clears it;
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
* ``request_cancel`` acquires the same per-operation ``DispatchHandoffGate`` as the final
  revalidation/start handoff before it commits a transition that could invalidate a new
  start;
* if cancellation owns the gate first, its legal state/version transition commits before
  dispatch revalidation and the later start is suppressed;
* if dispatch owns the gate first, cancellation waits until the bounded start attempt and
  immediate receipt/reference/uncertainty classification complete, then re-reads the
  retained state/version rather than committing against the stale pre-start version;
* a cancellation or state-version change observed by final boundary revalidation always
  suppresses a new ``start`` call, and the gate ensures such a transition cannot commit in
  the check-to-call gap;
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
described above. Prepared registration binds the request fingerprint before first use, so
a prepared nonce that expires unused is not an uncompactable special case: once trusted
time proves expiry it is durably marked ``prepared_operation_expired`` without an
operation, retained for the required full-record window, then may compact using that
fingerprint/owner digest/terminal class/retirement fact. Prepared-nonce compaction removes
all preparation-only fields; those facts are not part of the tombstone contract. If
trusted time cannot prove expiry, the full record is retained. Uncertain/security-recovery
evidence is not removed merely because ordinary result data expires.

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
* the exact first-store genesis predecessor vector frozen in section 12.1;
* strictly monotonic sequence;
* segment chain metadata and audit-epoch continuity;
* event byte and safe-fact bounds from ``spec/audit/audit-policy.yaml``.

For the first-ever event only, the allocator emits sequence 1 and
``previous_event_hash=a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632``.
The verifier independently recomputes SHA-256 over the 26-byte genesis preimage in section
12.1 and requires exact equality before accepting that first event. Sequence 1 with any
other predecessor may still be JSON-schema-valid but is not a valid Phase 4 store genesis.
Sequence >1 may never use the genesis predecessor in place of a real predecessor. This is
a writer/verifier protocol invariant, not a mutable setting.

Phase 4 has one application process that owns the audit journal. ``AuditJournal.append``
must therefore use one process-wide async append gate independent from per-operation
``DispatchHandoffGate`` instances. The append gate is acquired **before** reading the
verified current tail and remains held through next-sequence/``previous_event_hash``
allocation, schema validation, redaction/JCS canonicalization, hash calculation, append,
file/segment fsync, any segment rotation metadata required for the new tail, and
publication of the new authoritative in-memory tail. Only then is it released. Thus two
coordinators cannot allocate the same sequence/predecessor or race a segment rotation.
No SQLite transaction is held across the journal write/fsync. Phase 4 adds no second audit
writer process; any future multi-process audit writer requires a separately reviewed
cross-process serialization protocol rather than weakening this invariant.

``payload.kind`` is the **only** authoritative event type. All events validate against
``schemas/audit/audit-event.schema.json`` before append. Phase 4 uses only existing
payload kinds, including as applicable:

* ``operation.state_changed`` for received/running/terminal lifecycle records;
* ``operation.idempotency_conflict`` only when a retained operation exists and its
  authoritative ``old_state``/``new_state``/``state_version``/``effect_knowledge`` can be
  populated truthfully;
* ``policy.decision``, ``operation.rejected``, ``operation.authorised``;
* ``effect.intent_recorded``, ``effect.started``, ``effect.observed``,
  ``effect.failed``, ``effect.uncertain``;
* ``cancellation.requested`` / ``cancellation.phase_changed`` /
  ``cancellation.verified``;
* ``reconciliation.started`` / ``reconciliation.completed`` / ``recovery.required`` /
  ``recovery.completed``;
* existing ``audit.*`` payload kinds for segment/checkpoint/integrity events.

A tombstone or other pre-operation idempotency rejection has no truthful operation
``state_version`` and must not fabricate one merely to use
``operation.idempotency_conflict``. For the cross-controller tombstone replay/enumeration
case required by the idempotency contract, emit the existing schema-supported
``payload.kind=policy.decision`` with ``decision=rejected``,
``reason_code=idempotency_owner_mismatch``, ``operation_id=null``, the protected current
policy identity/version required by the top-level audit record, and only bounded digested
facts allowed by the policy payload/safe-fact schema. This is **audit evidence only**; it
does not insert, update, or count as the one durable admission row in
``policy_decisions``. The same rule applies to any pre-operation idempotency abuse record:
choose an existing schema-supported payload whose required facts are truthful, or fail the
required audit path closed; never invent operation state solely for logging.

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

For every normal journal append, the durable/tail ordering is exact:

#. acquire the process-wide audit append gate;
#. derive the current tail from the already-verified authoritative journal/in-memory tail,
   never from ``kernel_meta.audit_last_*``;
#. allocate the next sequence and ``previous_event_hash`` and build/validate/canonicalize
   the event;
#. append the canonical event bytes, fsync the journal file, and fsync/publish any required
   segment rotation metadata while the same gate is still held;
#. publish the new authoritative in-memory journal tail;
#. only after the journal durability point, update ``kernel_meta.audit_last_sequence`` and
   ``audit_last_hash`` in a separate short SQLite transaction as a derived cache;
#. release the append gate after the cache update attempt and tail publication are fully
   classified.

A crash after journal fsync but before the SQLite cache update leaves a safe **behind**
cache. Startup verifies the journal and refreshes that cache before the next append. A
cache-update failure never rolls back, deletes, or reuses the already-fsynced event or its
sequence; it degrades/fail-restricts consequential readiness until DB health and the cache
are reconciled. Writer ordering never advances the cache before journal fsync. Therefore
startup treats a cache ahead of the verified journal, or a same-sequence different hash,
as integrity failure rather than silently moving the cache backward. The next append is
never allowed until authoritative journal verification and this cache comparison finish.

Pre-effect ordering:

#. DB version-1 ``received`` commits;
#. ``operation.state_changed`` received audit appends/fsyncs;
#. policy decision commits;
#. deny path audits rejection; allow path commits ``authorised``;
#. ``policy.decision``/``operation.authorised`` audit appends/fsyncs;
#. DB ``authorised -> running`` dispatch marker commits;
#. ``effect.intent_recorded`` audit appends/fsyncs;
#. if the intent append/fsync fails and DB is writable, terminalize ``running -> failed``
   with ``known_no_effect``/``audit_unavailable`` and durably latch the current audit
   failure generation before entering fail-restricted recovery;
#. acquire the per-operation dispatch-handoff gate shared with cancellation;
#. perform final OP-BOUNDARY revalidation for every operation mode while holding the gate;
#. only then, still holding the gate, may the effect adapter submission be called and its
   immediate receipt/reference/uncertainty knowledge durably classified.

After a synthetic/future external effect, truthful operation persistence has priority;
audit follows immediately and fsyncs. If audit fails after a known effect, do not roll
back history or repeat the effect: mark audit degraded, retain truthful state, latch the
audit-failure generation where SQLite is writable, and block new consequential admission.

Crash-window rules:

* audit event fsynced but SQLite tail-cache update missing -> verify the authoritative
  journal on restart, refresh the behind cache, and allocate the next event from that
  verified journal tail; never reuse the fsynced sequence/hash;
* SQLite tail cache ahead of the verified journal, or same sequence with a different hash
  -> ``audit_integrity_failed``/fail-restricted; do not silently repair backward or append;
* DB received but missing received audit -> never continue to effect; recovery records
  the audit gap/recovery and rejects the unadmitted operation once audit is trustworthy;
* received audit present but no admission decision -> recovery must atomically persist the
  reserved fail-closed ``restart_before_admission`` deny decision with
  ``received -> rejected``; a failed DB commit leaves the operation received/unavailable;
* an admission decision present while state is still ``received`` -> recovery never
  inserts a second decision and rejects the interrupted operation without resuming effect;
* authorised DB state without authorization audit -> no effect; fail/recover as
  ``known_no_effect`` only after audit recovery;
* authorization audit but still authorised -> no effect was dispatched because running
  transition is the code-level precondition;
* running state with a known in-process effect-intent append/fsync failure -> no boundary
  was called; if DB is writable, commit ``running -> failed`` ``known_no_effect`` and the
  audit-failure latch before leaving the path, then attempt emergency evidence;
* if that DB terminalization/latch commit fails, do not call the boundary and do not
  fabricate a durable no-effect or recovered-audit claim; restart treats the unresolved
  running record conservatively and required audit readiness stays fail-restricted;
* a terminal operation whose post-effect audit append failed does not disappear from the
  recovery problem: its durable audit-failure generation still prevents startup from
  re-enabling admission even when the surviving main journal is otherwise continuous;
* running + effect-intent audit but crash before/during final boundary revalidation ->
  uncertain on restart unless separate durable evidence proves no boundary call;
* running + effect-intent audit + passed final boundary guard with lost start receipt ->
  uncertain unless reconciler proves an allowed terminal outcome.

30. Audit failure gate and emergency journal
-------------------------------------------

``KernelHealth`` tracks DB/audit/payload separately. When required audit cannot append,
fsync, or verify:

* if SQLite is writable and no audit failure is currently latched, one short transaction
  increments ``audit_failure_generation``, sets ``audit_failure_latched=true``, stores a
  bounded ``audit_failure_reason_code``/``audit_failure_detected_at``, and sets
  ``consequential_admission_enabled=false``; if a generation is already latched, preserve
  that generation and keep admission false;
* inability to durably write the latch never permits an effect: the process remains
  fail-restricted in memory and a subsequent startup must independently prove all recovery
  requirements rather than assuming the failed latch write means healthy audit;
* do not cross a new effect boundary;
* if the failure occurs on ``effect.intent_recorded`` after the durable running marker,
  first persist ``running -> failed`` with ``known_no_effect``/``audit_unavailable`` when
  SQLite is still writable because this process knows ``EffectBoundary.start`` was not
  called; the same short failure handling path also leaves the audit generation latched;
* allow bounded trustworthy recovery/status reads;
* attempt one bounded emergency audit record only when the pre-created emergency journal
  remains writable/trustworthy;
* emergency exhaustion remains fail-restricted;
* a successful later verification of the surviving main chain is necessary but **not
  sufficient** to clear the durable latch.

Recovery is explicit and generation-bound. The local-only operator command from section 32
runs only with the service stopped and the same exclusive runtime lock used by other
offline maintenance. For requested generation ``g`` it must:

#. require ``audit_failure_latched=true`` and ``g == audit_failure_generation`` while
   ``audit_recovered_generation < g``; stale/future generations fail closed;
#. verify the surviving main journal/segment/epoch chain from genesis through its current
   tail and reconcile any trustworthy bounded emergency evidence for that outage;
#. append/fsync schema-valid recovery evidence for **that exact generation**, using
   existing ``audit.verification_passed`` and ``recovery.completed`` payloads with bounded
   safe facts/reason ``audit_failure_recovered`` rather than inventing a new payload kind;
#. retain the fsynced ``recovery.completed`` event hash as the recovery-evidence digest;
#. only after those event bytes are durable, commit a short SQLite transaction setting
   ``audit_recovered_generation=g``, ``audit_recovery_evidence_sha256`` to that event hash,
   ``audit_failure_latched=false``, clearing the active reason/time, and leaving
   ``consequential_admission_enabled=false``;
#. release the offline lock without starting or dispatching any operation.

A crash after recovery evidence fsync but before latch-clear remains safe: the latch stays
active. Re-running recovery for the same generation first searches/verifies the already
fsynced exact-generation recovery evidence and may use its hash to complete the idempotent
SQLite clear; it must not treat an arbitrary verification event or an older generation as
recovery. Startup itself never clears the latch and never manufactures this evidence.
Only a later normal startup that verifies all stores **and** observes
``audit_failure_latched=false`` with ``audit_recovered_generation ==
audit_failure_generation`` for a nonzero generation may consider consequential admission
for re-enable.

If SQLite cannot persist a known-no-effect failure, the audit latch, or a recovery clear,
no effect is called and the kernel must not claim the corresponding durable state survived;
recovery remains conservative. No silent ordinary-log fallback exists.

31. Audit verification and checkpoints
--------------------------------------

Verifier checks event schema, JCS hash, sequence, previous-event hash, the exact store-
genesis predecessor vector, segment metadata, epoch continuity, truncation/fork/duplicate
sequence, and canonical byte ceiling.

Local consistency checkpoints may record DB schema revision, highest operation/transition
summary, audit epoch/sequence/final digest, trusted-time high-water/generation, active audit-
failure/recovery generation, and runtime build/config/policy digests. SQLite stores only
checkpoint reference/digest metadata; audit event bytes remain authoritative. This is not
an external signed checkpoint or post-compromise history claim.

32. Minimal local operator CLI and migration safety
--------------------------------------------------

Extend existing CLI with local-only:

::

   binnacle db status
   binnacle db upgrade
   binnacle kernel verify
   binnacle audit verify
   binnacle audit recover --generation <n>

``db status`` reads Alembic revision and pragmas.

``db upgrade`` is explicit, never MCP-callable, acquires the exclusive migration/runtime
lock described above, and refuses if the live application writer is active. The
development-Pi runbook requires stop -> upgrade -> verify -> start. The service unit's
``RuntimeDirectoryPreserve=yes`` keeps the already systemd-created ``/run/binnacle``
parent present across that ordinary stop; the stopped-service command verifies its
protected owner/group/mode and acquires the same lock as the running application would.
If the parent is absent or unsafe, the command fails closed rather than creating it with
privilege or falling back to another lock. The sequence never creates a second writer
beside the running service.

``kernel verify`` checks schema/pragmas, lifecycle/idempotency invariants, trusted-time
ordering state, payload metadata/bytes, audit continuity, and audit-failure latch/recovery
generation without automatic repair.

``audit verify`` checks the append-only chain, including the exact first-store genesis
vector, without dumping event payloads or clearing an audit-failure latch.

``audit recover --generation <n>`` is explicit fail-restricted recovery, never MCP-callable
and never an ordinary startup side effect. It requires the service stopped, verifies and
acquires the same protected exclusive runtime lock, follows section 30 exactly, and leaves
consequential admission disabled for the next normal startup to reassess. It is an offline
maintenance use of the same authoritative persistence/audit adapters, not a concurrent
second application writer. If the runtime directory/lock or surviving audit evidence is
unsafe/unavailable, recovery fails closed.

Human/agent/JSON output follows existing CLI conventions and never exposes raw payload,
audit, credential, idempotency-key, or raw boot/time-trust material.

33. Startup and migration behavior
----------------------------------

Application startup does not silently migrate or silently recover an audit outage.

Sequence:

#. acquire runtime DB lock;
#. inspect Alembic revision;
#. new/uninitialized or behind/ahead DB -> kernel unavailable/migration required;
#. operator stops service; ``RuntimeDirectoryPreserve=yes`` leaves the systemd-created
   protected runtime-lock parent in place, and the non-root ``binnacle db upgrade``
   verifies/acquires the same exclusive migration lock before upgrading;
#. startup reopens and verifies revision/pragmas;
#. under the audit append gate, verify audit event/segment/epoch continuity from the exact
   genesis convention and reconstruct the authoritative journal tail from durable journal
   bytes;
#. compare that verified tail with ``kernel_meta.audit_last_sequence/hash``: refresh a
   merely-behind cache in a short SQLite transaction; treat cache-ahead or same-sequence
   hash divergence as ``audit_integrity_failed`` and keep the kernel fail-restricted;
#. initialize the next-append allocator only from the verified journal tail, never from the
   SQLite cache;
#. read ``audit_failure_generation``, ``audit_failure_latched``, recovered generation, and
   recovery-evidence digest; **never clear or advance them during startup** merely because
   the surviving journal verifies;
#. if the audit latch is active, or a nonzero cleared generation lacks exact matching
   recovered generation/schema-valid recovery evidence, keep consequential admission
   disabled and report explicit audit recovery required; terminal operations are not an
   exception to this check;
#. verify payload roots/metadata;
#. load trusted-time durable high-water/boot evidence and obtain a current trust snapshot;
#. if current time is untrusted or rolled back, mark time-dependent consequential
   predicates unavailable rather than resetting/advancing deadlines;
#. run bounded restart reconciliation without dispatching effects;
#. only after all required checks succeed **and no audit failure generation remains
   latched/unrecovered** set ``consequential_admission_enabled=true`` and mark internal
   kernel available, while time-dependent operations remain fail-closed if trusted time is
   unavailable.

Migration failure never deletes/recreates DB. Migration ``0001`` rejects incompatible
unmanaged tables rather than silently taking ownership.

Migration tests cover fresh upgrade, FK/check/index presence, unknown revision refusal,
exclusive migration coordination, stopped-service runtime-directory preservation/safe
lock acquisition, durable audit-failure latch constraints/generation persistence, and safe
downgrade/round-trip where downgrade exists.

34. Kernel health and readiness
-------------------------------

Internal availability is ``available``, ``degraded``, or ``unavailable``. Consequential
admission requires ``available`` and no latched/unrecovered audit-failure generation; a
time-dependent operation additionally requires a trusted-time state that can prove its
deadline/freshness predicates.

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

The main MCP/application process is the sole live authoritative ``binnacle.db`` writer.
The explicit stopped-service ``db upgrade`` and ``audit recover`` maintenance commands are
serialized by the same exclusive runtime lock and never coexist with that writer. Future
executor/privileged-broker processes:

* never open the application SQLite DB directly;
* retain minimum independent execution/broker evidence;
* reconcile through typed IPC/application ports;
* return stable bounded external reference identity to the application.

Phase 4 defines only effect/reconciliation semantics, not future IPC wire schemas.
Audit/payload/trusted-time adapters run in the application process in Phase 4 except for
the explicitly stopped-service maintenance composition described above.

38. Logging and diagnostics
---------------------------

Structured diagnostic logs may include DB revision/pragmas, operation ID, state/version,
safe idempotency digest prefix, policy decision ID/reason code, boundary-revalidation
result code, trusted-time health/generation (not raw trust material), reconciliation result,
payload byte counts/digest prefix, audit sequence/status/failure generation, and kernel
availability.

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
* prepared nonce registration always persists the contract request fingerprint before
  first use, including for a nonce that is never consumed;
* prepared nonce first admission requires a durable registration;
* unconsumed prepared nonce expiry durably classifies the binding
  ``prepared_operation_expired`` and returns that code with no operation/effect;
* an expired unconsumed prepared full record can compact after retention to an exact
  tombstone without inventing an operation, while unprovable expiry cannot be compacted;
* prepared operation/input/request-fingerprint/current-state binding mismatch returns
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
* if cancellation wins the shared dispatch gate and commits first, no later start occurs;
  if dispatch wins, cancellation cannot commit against that running version until the
  start attempt and immediate effect-knowledge/reference classification complete;
* a concurrent state/version change is never overwritten by a stale failed transition;
* after successful prepared admission, a same-fingerprint retry returns the retained
  operation even when the preparation expiry time has subsequently passed;
* uncertain never auto-retries;
* cancellation cannot become cancelled without verification;
* full-to-tombstone conversion retaining exact duplicate-prevention fields;
* prepared-nonce full-to-tombstone conversion clears every preparation-only field while
  retaining the exact contract tombstone facts and global uniqueness scope;
* same-owner tombstone replay returns ``idempotency_key_retired`` with no operation load;
* different-controller tombstone replay returns non-disclosing
  ``idempotency_owner_mismatch`` with no operation load or retirement disclosure;
* any number of concurrent ``AuditJournal.append`` calls produce one linear strictly
  increasing sequence/hash chain with no duplicate sequence or predecessor fork;
* first-store sequence 1 uses exactly the frozen genesis predecessor digest, while any
  alternate/schema-only placeholder predecessor fails chain verification;
* once an audit-failure generation is latched, arbitrary restart/verified surviving chain/
  terminal-operation state cannot make consequential admission true until the matching
  generation has explicit recovery evidence and is durably cleared;
* a pre-operation/tombstone idempotency rejection selects a schema-valid audit payload
  without fabricating an operation ID/state/version.

Tests consume reviewed YAML/fixtures or parity mappings so contract changes break tests
visibly.

40. Integration and fault tests
-------------------------------

Use temporary SQLite/filesystem roots plus a separate counting effect fixture. Required
fault points include:

* crash before create/find commit;
* crash after received commit/before received audit;
* audit failure before policy;
* crash after received audit/before admission decision -> restart atomically writes one
  fail-closed recovery deny plus ``received -> rejected``; no zero-decision terminal row;
* crash after admission decision/before received transition -> restart creates no second
  policy decision and rejects the interrupted received operation;
* policy deny;
* duplicate admission policy decision for one operation is rejected by the unique
  constraint and an orphan decision is rejected by the FK;
* undeclared ``derived_member_key`` is rejected before any durable binding/operation;
* prepared binding registration persists request fingerprint even when never consumed;
* prepared binding persisted, process restarted, then first use while valid;
* prepared binding persisted, process restarted past expiry -> durable
  ``prepared_operation_expired`` classification and no operation;
* expired unconsumed prepared binding survives full retention then compacts to a tombstone
  retaining fingerprint/owner digest/terminal class and clearing preparation-only fields;
* compaction with untrusted/unprovable expiry retains the full prepared binding;
* prepared binding persisted, process restarted with input/fingerprint/current-state
  mismatch -> ``prepared_operation_mismatch`` and no operation;
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
* deterministic cancellation race where ``request_cancel`` acquires the shared handoff
  gate first -> legal cancellation transition commits and counting boundary=0;
* deterministic inverse race where dispatch owns the gate first -> cancellation blocks
  until ``start`` has been attempted and immediate receipt/reference/uncertainty knowledge
  is classified, then re-reads current state/version; no start begins after a committed
  ``cancelling`` transition;
* generic target/freshness/reservation/recovery verifier fails -> boundary=0;
* crash after authorised commit/before authorization audit;
* crash after authorization audit/before running transition;
* crash after running transition/before effect-intent audit;
* ``effect.intent_recorded`` append/fsync failure with writable DB -> durable
  ``running -> failed`` known-no-effect plus a durable active audit-failure generation,
  admission disabled, counting boundary=0;
* same audit failure plus DB terminalization/latch failure -> boundary=0 and conservative
  restart treatment rather than fabricated terminal/recovery durability;
* crash after a terminal operation's required post-effect audit append fails -> fresh
  process observes the active failure generation and stays fail-restricted even though the
  surviving main chain verifies and the operation itself needs no nonterminal reconciliation;
* explicit recovery with wrong/stale generation -> latch remains active/admission false;
* crash after exact-generation ``recovery.completed`` fsync but before SQLite latch clear ->
  fresh process remains fail-restricted; rerun verifies/reuses that exact evidence and can
  complete the idempotent clear without fabricating another generation;
* exact-generation recovery clear leaves admission false until a later full startup passes
  all checks;
* first-store audit writer emits sequence 1 with the frozen genesis predecessor; replacing
  it with the schema-only all-``f`` fixture placeholder fails chain verification;
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
* matching full-record key from another owner;
* same key/different fingerprint;
* prepared-nonce full record compacts to a tombstone with preparation-only fields NULL;
* a tombstone that retains any preparation-only field is rejected by schema checks;
* same-owner tombstone replay -> ``idempotency_key_retired`` without operation load;
* cross-controller tombstone replay -> ``idempotency_owner_mismatch`` without operation
  load or retirement disclosure and a schema-valid ``policy.decision`` rejection audit
  with ``operation_id=null`` rather than fabricated operation state/version;
* many coordinators forced to append from the same initial audit tail still produce one
  serialized sequence/hash chain with no fork or duplicate predecessor;
* crash/fault after journal event fsync but before ``kernel_meta`` tail-cache update ->
  fresh startup verifies the journal, refreshes the behind cache, and the next append uses
  the fsynced event as predecessor with sequence+1;
* ``kernel_meta`` audit tail ahead of the verified journal or same sequence/different hash
  -> fail-restricted ``audit_integrity_failed`` and no new append/effect;
* SQLite busy/lock timeout and migration lock contention;
* DB read-only/disk-full simulation where feasible;
* audit bit flip/delete/reorder/truncation/fork;
* emergency-journal exhaustion;
* payload temp crash/finalize-before-DB orphan;
* DB-complete/payload-missing/digest mismatch;
* payload quota pressure;
* systemd unit starts with ``/run/binnacle`` absent, recreates it through
  ``RuntimeDirectory=binnacle`` with the expected owner/mode, and can acquire the runtime
  advisory lock without broadening durable write roots;
* an ordinary stop of ``binnacle-dev.service`` preserves that protected runtime directory
  through ``RuntimeDirectoryPreserve=yes``; while the service is stopped, the non-root
  ``binnacle db upgrade``/``binnacle audit recover`` paths verify it and can acquire/release
  the same exclusive maintenance lock without privileged recreation or a fallback path;
* a reboot-like removal of ``/run/binnacle`` is still recovered by the next systemd start,
  after which a migration/recovery-required stop preserves the recreated directory for
  offline maintenance;
* systemd unit permits only declared Phase 4 state/result/audit durable write roots.

The synthetic counter proves at most one effect for one logical idempotency identity.
Tests never mutate real repository/system state.

41. Fresh-process restart tests
------------------------------

Close every runtime object and reconstruct a fresh application. Verify:

* operation identity/state/version remains resolvable;
* idempotency binding reconciles;
* a received operation that crashed before policy persistence gains exactly one explicit
  recovery-deny admission decision atomically with restart rejection; an already-present
  decision is never duplicated;
* exactly one persisted admission policy decision is retrievable by ``operation_id`` for
  every operation that leaves ``received`` and no reverse operation-to-policy pointer is
  required to reconstruct it;
* undeclared ``derived_member_key`` remains rejected after fresh composition and cannot
  acquire a binding merely because in-memory registration state was lost/recreated;
* an unconsumed prepared binding retains its request fingerprint, expiry,
  boot/monotonic-ordering evidence, and exact prepared input/current-state digests across
  restart;
* a prepared binding that expires unused remains durably ``prepared_operation_expired``
  with no operation and can later compact after retention without losing required
  tombstone facts;
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
* a journal event fsynced before a crash but missing from the SQLite tail cache remains
  authoritative; startup refreshes the behind cache and next append continues from that
  verified journal hash/sequence;
* a cache-ahead or same-sequence/hash-divergent audit tail blocks startup readiness instead
  of being silently repaired or used for allocation;
* first-store genesis verification recomputes the frozen domain-separated predecessor and
  rejects a schema-valid-but-wrong predecessor;
* an active audit-failure generation survives reconstruction even if the surviving main
  chain verifies, and keeps admission disabled until matching explicit recovery evidence
  has been fsynced and the durable generation is cleared;
* a terminal operation with a missing required post-effect audit event cannot bypass that
  latch simply because it is absent from nonterminal reconciliation;
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

Add an explicit writer/verifier genesis test vector with exactly:

::

   preimage_hex = 62696e6e61636c652e61756469742e67656e657369732e763100
   sha256       = a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632
   first_event_sequence = 1
   first_event_previous_event_hash = a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632

The writer must produce that predecessor for a brand-new store and the verifier must
independently derive/require it. A fixture/event with sequence 1 and the existing all-``f``
schema placeholder remains useful for schema validation but must fail Phase 4 chain-
genesis verification. Later events cannot reuse the sentinel.

Concurrency tests force multiple appenders to observe the same initial tail and prove the
process-wide append gate serializes tail read/allocation, canonicalization/hash, write,
fsync, segment rotation, and tail publication into one strictly monotonic chain. Crash
window tests fsync an event and stop before the SQLite cache update, then prove fresh
startup reconstructs the journal tail, refreshes the behind cache, and appends exactly the
next sequence/hash; cache-ahead or same-sequence hash divergence instead fails restricted.

Exact mapping tests prove a cross-controller tombstone replay audits with a schema-valid
``policy.decision`` rejection and ``operation_id=null`` without creating a DB admission
policy row or fabricating ``state_version``; ``operation.idempotency_conflict`` is used only
when a retained operation supplies truthful required operation payload fields.

A dedicated test injects ``effect.intent_recorded`` append/fsync failure after the durable
running marker and proves that a writable DB records ``running -> failed`` with
``known_no_effect``/``audit_unavailable`` plus an active audit-failure generation before
the coordinator leaves the path, while the counting effect boundary remains zero. Another
test makes that DB terminalization/latch fail and proves no effect call occurs and no
durable terminal/recovery claim is fabricated.

A recovery test leaves a terminal operation with its required post-effect audit append
missing, restarts with an otherwise continuous surviving chain, and proves startup remains
fail-restricted. It then proves only schema-valid fsynced recovery evidence bound to the
exact active generation permits the durable latch to clear; stale generation, plain chain
verification, or a crash before the clear cannot re-enable admission.

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

Persistence tests prove each operation that leaves ``received`` has exactly one admission
policy row, the row cannot precede/orphan its operation, and it is queried by
``operation_id`` without a reverse ``operations.policy_decision_id`` reference. A crash
between version-1 creation and normal decision persistence is covered explicitly: restart
atomically inserts the reserved fail-closed recovery deny with ``received -> rejected``;
a crash after decision persistence but before the received-state transition creates no
second decision. Final OP-BOUNDARY policy revalidation is a fresh check and cannot update,
replace, or append another admission decision row; its result is captured through
boundary/audit evidence. A ``policy.decision`` payload used solely to audit a pre-operation
idempotency rejection is explicitly not inserted into this table and cannot satisfy or
alter the exactly-one admission-decision invariant.

Boundary tests prove an earlier ``allow`` decision is never treated as perpetual
authority. Every applicable predicate is re-read immediately before the effect boundary;
changed/unavailable trust, policy/profile, target/freshness, reservation, privilege/
credential delegation, interlock, cancellation/supervision, or recovery state suppresses
the call. Deterministic barrier tests additionally prove cancellation and the final
check-to-start handoff use the same per-operation dispatch gate, so no cancellation
transition can commit in the gap and then be followed by a stale new ``start``. The fake
boundary verifier cannot be reached from the production MCP surface.

45. Migration and deployment tests
----------------------------------

On Python 3.11/3.12/3.13 where applicable:

* fresh ``alembic upgrade head``;
* exact tables/indexes/checks/FKs exist;
* ``policy_decisions.operation_id`` is ``NOT NULL``, FK-enforced and unique while
  ``operations`` has no ``policy_decision_id`` column/reverse policy FK;
* duplicate policy rows for one operation and orphan policy rows fail;
* prepared full-record checks require preparation fields and non-null request fingerprint,
  prepared-nonce tombstones permit those fields to be cleared, and tombstones retaining
  preparation-only fields fail;
* a proven-expired unconsumed prepared full record with ``operation_id=NULL`` and
  ``terminal_class=prepared_operation_expired`` is valid during retention and can compact
  to the contract tombstone; an active/unproven arbitrary operation-less full row cannot;
* invalid FK inserts fail with foreign keys enabled;
* WAL and synchronous FULL are read back;
* app refuses behind/ahead/unknown revision;
* concurrent live-writer vs migration/recovery maintenance is rejected;
* downgrade round-trip where safe;
* migration failure leaves original DB recoverable;
* trusted-time durable fields survive upgrade/restart and cannot be reset by ordinary
  startup to bypass rollback detection;
* audit-failure generation/latch/recovered-generation constraints survive upgrade/restart
  and cannot be reset by ordinary startup;
* Phase 3 ``ProtectSystem=strict`` remains active;
* ``RuntimeDirectory=binnacle`` plus ``RuntimeDirectoryMode=0750`` (or exact equivalent)
  recreates ``/run/binnacle`` with the expected service owner/group and mode after an
  absent/reboot-like runtime tree;
* ``RuntimeDirectoryPreserve=yes`` (not ``restart``) keeps that protected directory across
  the ordinary service stop used by the runbook, and stopped-service non-root
  ``binnacle db upgrade``/``audit recover`` can verify/acquire the same exclusive lock;
  missing or unsafe runtime-directory state fails closed rather than being recreated with
  privilege or redirected to another path;
* only ``/var/lib/binnacle/state``, ``results``, and ``audit`` are durable writable
  additions; protected controller config and evaluation evidence permissions are not
  broadened.

46. Security invariants
-----------------------

Phase 4 must preserve:

#. no production consequential effect adapter;
#. no new mutating MCP Tool/Resource/Task/Prompt;
#. durable global idempotency identity before synthetic effect dispatch;
#. undeclared ``derived_member_key`` cannot create a binding/operation/effect; Phase 4
   admits no derived-member mode until a reviewed parent derivation exists;
#. prepared execution nonces retain durable request fingerprint, expiry,
   boot/monotonic-ordering evidence, and exact current-state binding before first
   admission;
#. expired unconsumed prepared nonces cannot be revived: proven expiry is durably
   classified and eventually compacts to a tombstone without inventing an operation;
#. prepared-nonce tombstones clear preparation-only state and retain only the contract
   tombstone facts plus fields required for the global uniqueness scope;
#. wall-clock rollback/reboot/loss of trusted time cannot extend operation deadlines;
#. a newly admitted prepared operation revalidates expiry/current state as part of the
   final OP-BOUNDARY guard; stale/unprovable state cannot reach ``EffectBoundary.start``;
#. every operation mode revalidates all applicable OP-BOUNDARY authority/state predicates
   immediately before effect dispatch;
#. final revalidation/start handoff and cancellation are serialized by the same bounded
   per-operation application gate; no stale ``start`` begins after a cancellation
   transition for that running version commits;
#. a concurrent cancellation/state-version change suppresses dispatch and cannot be
   overwritten by stale transition logic;
#. raw idempotency material never persists/discloses;
#. global duplicate prevention survives controller replacement and tombstoning;
#. operation ownership never transfers from key possession;
#. same key/different input never executes;
#. a tombstone verifies owner digest before retirement disclosure: cross-controller replay
   returns ``idempotency_owner_mismatch`` and same-owner replay returns
   ``idempotency_key_retired`` without operation load;
#. tombstone replay cannot load/revive an old operation;
#. policy persistence has one non-circular one-to-one admission-decision FK layout;
#. every operation leaving ``received`` has exactly one durable admission decision;
   recovery of an interrupted pre-decision received operation atomically writes a
   fail-closed deny with rejection rather than creating a zero-decision terminal row;
#. final policy revalidation cannot rewrite the historical admission decision;
#. durable ``running`` dispatch marker exists before effect adapter invocation;
#. required intent-audit failure with writable DB terminalizes the running operation as a
   known-no-effect failure before the audit failure gate; no effect call occurs;
#. missing start receipt cannot be treated as proof of no effect;
#. ``uncertain`` never auto-retries;
#. lifecycle/state-version rules are contract-exact;
#. main app process solely owns live authoritative SQLite writes; explicit stopped-service
   migration/audit-recovery maintenance uses the same exclusive lock and never overlaps it;
#. SQLite durability pragmas are verified;
#. migration/recovery maintenance cannot race the live writer;
#. the same systemd-managed ``/run/binnacle`` lock parent is preserved across the explicit
   stopped-service maintenance window with ``RuntimeDirectoryPreserve=yes`` and remains
   reboot-ephemeral/recreated on the next service start;
#. audit uses existing schema, JCS+SHA-256, and ``payload.kind`` discriminator;
#. the first-store audit predecessor is exactly the frozen domain-separated genesis digest;
   restart/rotation/later epochs do not invent or reuse another sentinel;
#. audit appends are process-wide serialized through tail allocation, write/fsync, segment
   rotation, and tail publication; concurrent coordinators cannot fork the chain;
#. verified journal bytes/tail are allocation authority; SQLite ``audit_last_*`` is only a
   post-fsync cache whose behind state is repairable and whose ahead/divergent state fails
   restricted;
#. required audit failure has a durable monotonically identified latch that survives
   restart and cannot be cleared by successful chain verification alone; exact-generation
   schema-valid fsynced recovery evidence is required before a durable clear;
#. pre-operation/tombstone idempotency abuse audit never fabricates operation state/version
   to fit a schema payload; schema-valid rejection evidence remains separate from DB
   admission-policy persistence;
#. audit redaction precedes persistence/hash;
#. required audit failure blocks new effects;
#. payload cannot claim complete before durable bytes/digest;
#. result/audit state contains no reusable credential;
#. DB/audit/payload roots are not ordinary env/CLI-overridable;
#. systemd grants only narrow declared durable write paths and a systemd-managed
   ``/run/binnacle`` ephemeral runtime directory;
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
upgrade`` -> ``kernel verify`` -> start sequence; explicit audit recovery, when required,
is a separate stopped-service command and is never implied by ``verify`` or startup.

49. Implementation order
------------------------

Implement Phase 4 in this order:

#. add persistence/JCS dependencies, Alembic skeleton, systemd durable write-path changes,
   and systemd-managed ``RuntimeDirectory=binnacle`` / ``RuntimeDirectoryPreserve=yes``
   for the runtime/migration lock;
#. define domain types and lifecycle/idempotency/audit contract-parity tests, including
   fail-closed undeclared-derived-member handling and the exact genesis vector;
#. implement migration ``0001`` and SQLite runtime/pragmas/migration locking, including
   trusted-time durable high-water/boot-ordering fields, durable audit-failure/recovery
   generation latch fields, exact prepared tombstone checks, operation-less proven-expired
   prepared retention/compaction, and the one-way unique policy-decision FK;
#. implement ``TrustedTimeSource``/guard and rollback/reboot/loss-of-trust tests;
#. implement atomic create/find with full/tombstone exact semantics, including
   owner-digest-before-retirement disclosure, registration-time request fingerprints,
   contract-exact prepared-nonce compaction, and durable prepared-nonce pre-admission
   registration/expiry/current-state validation;
#. implement state-version transition store;
#. implement fail-closed Bootstrap policy + exactly one durable admission decision for
   every operation leaving ``received``, including atomic recovery-deny+rejection after a
   crash before normal decision persistence;
#. implement the process-wide serialized JCS audit writer/verifier, frozen genesis
   predecessor, exact schema mapping, verified-journal-tail allocator, post-fsync SQLite
   tail cache/restart reconciliation, durable audit-failure generation latch, explicit
   same-generation recovery evidence/clear path, and no-effect terminalization on pre-
   dispatch intent-audit failure;
#. implement retained payload filesystem adapter + metadata consistency;
#. implement mandatory generic/operation-specific OP-BOUNDARY revalidation plus the
   bounded per-operation dispatch-handoff gate shared with cancellation;
#. implement ``OperationCoordinator`` through durable running dispatch marker, intent
   audit, gated final boundary revalidation/start/receipt classification, and unavailable
   production effect boundary;
#. implement synthetic counting effect/reconciler/prepared-state/boundary verifiers only
   in tests;
#. implement restart reconciliation and cancellation semantics using the same handoff gate;
#. add local DB/kernel/audit operator commands, including explicit stopped-service
   generation-bound audit recovery;
#. add property, crash-window, trusted-time, boundary, restart, audit, payload, migration,
   stopped-service runtime-directory preservation, and systemd tests;
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
* one live authoritative SQLite writer and no executor/broker DB access; stopped-service
  maintenance is serialized by the same exclusive runtime lock;
* version-1 received creation and lifecycle edges match contracts;
* idempotency unique scope is non-null and contract-exact;
* undeclared ``derived_member_key`` fails closed before binding/operation creation;
* prepared nonce registration durably binds prepared operation/input, canonical request
  fingerprint, expiry, exact current-state digest, boot identity, and monotonic deadline
  ordering;
* an expired unconsumed prepared nonce is durably classified without creating an
  operation, remains replay-blocking during full retention, and later compacts to a
  contract-exact tombstone retaining fingerprint/owner digest/terminal class;
* prepared-nonce compaction clears every preparation-only field and leaves a
  contract-exact tombstone that still enforces the global unique scope;
* same-boot rollback and cross-boot untrusted/rolled-back wall time cannot extend the
  prepared lifetime;
* prepared expiry/mismatch behavior survives fresh-process restart and uses the reviewed
  ``prepared_operation_expired`` / ``prepared_operation_mismatch`` codes when those facts
  are provable;
* loss of trusted time fails closed rather than pretending a nonce remains valid;
* final OP-BOUNDARY revalidation applies to **all** operation modes, not only prepared
  nonces, and rechecks every applicable authority/state/cancellation/recovery predicate;
* final boundary revalidation/start handoff shares a bounded per-operation gate with
  cancellation, so a cancellation transition cannot commit in the check-to-start gap;
* a concurrent state/version change is not overwritten by stale dispatch failure logic;
* tombstones contain exactly the required duplicate-prevention facts, verify owner digest
  before retirement disclosure, return owner mismatch cross-controller, and return retired
  only to the matching owner without loading an operation;
* raw keys never persist;
* ``policy_decisions.operation_id`` is the sole ``NOT NULL UNIQUE`` policy FK,
  ``operations`` has no reverse policy pointer, and every operation leaving ``received``
  has exactly one admission decision;
* restart after received creation but before policy persistence atomically records an
  explicit fail-closed recovery deny with ``received -> rejected``; restart never leaves a
  terminal zero-decision operation or creates a second decision;
* final policy revalidation is fresh authority checking and does not overwrite the durable
  admission decision;
* audit authorization and durable running dispatch marker precede effect invocation;
* ``effect.intent_recorded`` audit failure before dispatch terminalizes running work as
  known-no-effect when DB durability remains available and never calls the boundary;
* a lost start receipt becomes uncertain, not known-no-effect;
* same-key conflict/cross-controller cases cannot create effect;
* persisted effect reference permits restart reconciliation;
* audit schema ``payload.kind`` and required fields are exact;
* first-store sequence 1 uses the exact domain-separated genesis predecessor vector and
  the verifier rejects schema-valid placeholder/alternate genesis digests;
* ``AuditJournal.append`` serializes verified-tail read/allocation through fsync/segment
  rotation/tail publication under one process-wide gate;
* journal bytes own the audit tail; ``kernel_meta.audit_last_*`` is updated only post-fsync,
  a verified behind cache is refreshed on startup, and ahead/divergent cache is an
  integrity failure rather than allocation authority;
* an audit-failure generation latch survives restart, including when the affected operation
  is already terminal; successful surviving-chain verification alone never clears it;
* only explicit same-generation schema-valid fsynced recovery evidence can clear the
  audit-failure latch, and that clear itself leaves admission disabled until full startup;
* tombstone/pre-operation idempotency abuse uses schema-valid audit evidence with no
  fabricated operation state/version and does not create a DB admission policy row;
* DB/audit are not falsely one transaction;
* audit failure blocks new effects;
* payload completion is durable/digest truthful;
* Bootstrap policy is minimal/fail-closed;
* migrations are explicit and cannot race live service;
* systemd write authority is narrow under ``ProtectSystem=strict``; the unit recreates
  ``/run/binnacle`` with ``RuntimeDirectory=binnacle`` after reboot and preserves it with
  ``RuntimeDirectoryPreserve=yes`` across the ordinary stop required by offline
  migration/recovery, allowing the same non-root maintenance lock path without fallback;
* current five read-only MCP Tools remain unchanged;
* exact-head quality/CI passes.

51. Deterministic acceptance checklist
--------------------------------------

Phase 4 implementation is accepted only when every item is true:

#. persistence/JCS dependencies are locked and support Python 3.11--3.13;
#. Alembic ``0001`` creates exactly the Phase 4 authoritative schema;
#. runtime never silently creates/migrates tables;
#. DB path is local/protected/separate from source/config/evaluation evidence;
#. systemd setup creates and grants only state/results/audit durable write roots, while
   ``RuntimeDirectory=binnacle`` recreates the narrow service-owned ``/run/binnacle``
   ephemeral lock directory when absent after reboot and
   ``RuntimeDirectoryPreserve=yes`` keeps it present across the ordinary stopped-service
   offline-maintenance window;
#. every DB connection verifies foreign keys, WAL, FULL synchronous, and busy timeout;
#. migration mismatch/unavailable audit keeps consequential kernel unavailable;
#. live writer and stopped-service ``db upgrade``/``audit recover`` cannot run concurrently,
   and after the required service stop the non-root command can verify and acquire the same
   protected ``/run/binnacle`` lock without privileged recreation or an alternate path;
#. ``kernel_meta`` binds stable device epoch, schema-compatible audit epoch continuity,
   durable trusted-time high-water/boot-ordering evidence, and the durable audit-failure/
   recovery generation latch;
#. ``kernel_meta.audit_last_sequence/hash`` is cache-only: journal fsync precedes cache
   advancement, startup reconstructs the authoritative journal tail, repairs only a
   verified behind cache, and fails restricted on ahead/hash-divergent cache state;
#. first-store audit sequence 1 sets
   ``previous_event_hash=a3be2bea4d6491d8c23e9de679e5b99da91b43cf7bc76728069cc5514d921632``
   derived from the exact section-12.1 preimage, and the verifier independently requires
   that value rather than accepting a private/schema-only sentinel;
#. controller ownership rows contain no reusable credential;
#. lifecycle state vocabulary/edges exactly match ``spec/operation/lifecycle.yaml``;
#. version 1 is ``NULL -> received`` and every later transition increments once;
#. invalid/stale transitions are rejected;
#. global idempotency index exactly matches contract scope with non-null key columns;
#. ``derived_member_key`` is rejected as ``idempotency_invalid`` before durable binding/
   operation creation until a reviewed parent contract/derivation exists;
#. raw caller key/prepared nonce never persists/logs/audits;
#. an unconsumed prepared nonce is durably registered with owner/device/Tool/contract,
   prepared operation/input, canonical request fingerprint, expiry, exact current-state
   binding, boot identity, and same-boot monotonic deadline before first use;
#. first use of an expired prepared nonce durably classifies the operation-less binding as
   ``prepared_operation_expired``, returns that error, and creates no operation/effect;
#. after the required full-record retention window, an expired unconsumed prepared binding
   can compact to a tombstone retaining key/tool/contract/owner digest/request fingerprint/
   ``prepared_operation_expired`` terminal class/retired time and device/epoch uniqueness
   scope while clearing all preparation-only fields;
#. untrusted/unprovable time cannot be used to expire/compact an unused prepared binding;
#. prepared operation/input/request-fingerprint/current-state mismatch returns
   ``prepared_operation_mismatch`` and creates no operation/effect;
#. same-boot wall-clock rollback cannot extend a prepared lifetime;
#. reboot/loss of trusted wall time or a wall time behind durable high-water fails closed
   without creating/crossing an effect;
#. fresh-process restart preserves and re-enforces prepared expiry/mismatch/time-ordering
   checks;
#. valid prepared first admission atomically attaches exactly one version-1 operation;
#. consumed prepared-nonce full records compact to tombstones with preparation-only fields
   NULL while retaining key/tool/contract/owner digest/fingerprint/terminal class/retired
   time and the table's device/epoch uniqueness scope;
#. schema checks reject tombstones that retain prepared operation/input/expiry/state/boot/
   monotonic-deadline fields;
#. before that newly admitted prepared operation crosses an effect boundary, expiry and
   exact current-state digest are recomputed/revalidated again;
#. every non-prepared operation also performs the complete applicable OP-BOUNDARY
   revalidation immediately before ``EffectBoundary.start``;
#. changed controller/device trust, policy/profile, state version/cancellation,
   target/freshness/reservation/privilege/interlock/recovery state suppresses the effect
   call when applicable;
#. cancellation and final revalidation/start are serialized by the same bounded
   per-operation dispatch gate: cancellation-first gives boundary=0, while dispatch-first
   prevents cancellation from committing against the stale running version until the
   start attempt and immediate effect knowledge are classified;
#. a concurrent lifecycle change cannot be overwritten by a stale no-effect failure;
#. a later retry of an already admitted/dispatched prepared nonce returns retained work
   rather than creating or redispatching a fresh operation when preparation has expired;
#. concurrent same-key admission creates one binding/operation;
#. same owner + same key + same fingerprint returns retained operation;
#. same key + different fingerprint returns conflict/no second operation;
#. different controller + matching full-record key reveals no old operation and creates no
   effect;
#. tombstone retains key/tool/contract/owner digest/fingerprint/terminal class/retired time;
#. same-owner tombstone replay returns ``idempotency_key_retired`` without loading an
   operation;
#. different-controller tombstone replay returns non-disclosing
   ``idempotency_owner_mismatch`` without loading an operation or revealing retirement;
#. that cross-controller tombstone replay produces schema-valid bounded rejection audit
   evidence with ``operation_id=null`` and no fabricated operation state/version;
#. production policy denies unknown/unreviewed consequential contracts;
#. ``policy_decisions.operation_id`` is a ``NOT NULL UNIQUE`` FK to ``operations`` and
   ``operations`` contains no reverse policy-decision column/FK;
#. orphan policy decisions and a second admission decision for one operation are rejected;
#. every operation leaving ``received`` has exactly one durable admission decision;
   a restart before normal decision persistence atomically records the reserved fail-closed
   recovery deny with ``received -> rejected``, and a restart after decision persistence
   creates no second decision;
#. the admission decision is retrievable by operation ID after restart and is not rewritten
   by final policy revalidation;
#. received/authorization/effect-intent audit records are schema-valid and durable at the
   defined gates;
#. every normal ``AuditJournal.append`` is process-wide serialized from verified-tail
   selection through sequence/hash allocation, append/fsync, segment rotation, and
   authoritative tail publication;
#. concurrent audit appends cannot reuse one sequence/predecessor or fork the chain;
#. a crash after journal fsync but before SQLite tail-cache update is recovered by journal
   verification/cache refresh and the next append uses the fsynced event as predecessor;
#. durable ``running`` transition occurs before every effect-boundary call;
#. pre-dispatch ``effect.intent_recorded`` audit failure with writable DB commits a
   ``running -> failed`` known-no-effect outcome, durably latches the audit-failure
   generation, and calls no effect boundary;
#. inability to commit that failure/latch still calls no boundary and is reconciled
   conservatively after restart;
#. after any durably latched required audit failure, restart leaves admission false even
   when surviving chain verification succeeds and the affected operation is already
   terminal;
#. only explicit recovery for the exact active generation, with schema-valid fsynced
   ``audit.verification_passed``/``recovery.completed`` evidence, may clear the latch; a
   stale generation, verification-only run, or crash before the durable clear cannot;
#. clearing the latch does not itself set admission true; a later complete startup must
   verify all stores and matching recovery generation before enabling it;
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
#. audit failure disables new consequential admission durably across restart;
#. emergency journal is bounded/fail-restricted;
#. payload bytes are atomically finalized/fsynced/digest-verified before complete metadata;
#. payload orphan/corruption/quota pressure is detected without silent completeness;
#. operation evidence is bounded and not authoritative audit storage;
#. fresh-process restart reconstructs DB/idempotency/audit/payload/trusted-time truth;
#. local DB/kernel/audit commands expose no secrets/raw payloads and migration/recovery is
   safe under the stopped-service exclusive lock;
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
audit with frozen genesis and durable generation-bound recovery, retained payload/evidence
storage, durable pre-dispatch state, reconciliation, local diagnostics, deployment
permissions, migrations, and fault/property tests without deciding later operation-specific
authority or host behavior.

Stop here. Do not add the disposable write-probe workflow or any later operational
capability in this document.