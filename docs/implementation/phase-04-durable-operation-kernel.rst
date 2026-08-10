Binnacle Phase 4 Detailed Implementation Plan
=============================================

:Phase: 4 -- Add the durable consequential-operation kernel
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Planning status: provisional -- internal kernel design is concrete; host-facing projection remains evidence-gated
:Depends on: merged Phase 3 Raspberry Pi/ChatGPT validation plan; actual Phase 3 evidence before any host-facing operation projection
:Primary objective: Establish durable operation, idempotency, audit, policy, payload, and reconciliation foundations before any Binnacle capability is permitted to mutate local state
:Implementation scope: internal operation kernel, SQLite/SQLAlchemy/Alembic persistence, append-only integrity-linked audit, minimal PolicyEngine boundary, retained payload/evidence storage, local operator diagnostics, tests, and CI only

Purpose
-------

Phase 4 creates the reliability/security kernel that every later consequential Binnacle
capability must use. The phase does **not** add a write Tool or execute a real device
mutation. It proves that durable intent exists before an effect boundary, duplicate
logical requests reconcile to one retained operation, uncertain outcomes cannot be
blindly repeated, lifecycle state survives application restart, and required audit
failure prevents new consequential work.

The durable kernel is intentionally usable without knowing which later workspace,
executor, Git, package, service, or hardware operation will consume it. It owns generic
operation semantics, not operation-specific effect logic.

``docs/implementation/index.rst`` marks Phase 4 ``provisional`` because host-facing
projection depends on Phase 3 real ChatGPT evidence. This plan therefore freezes the
owner-approved **internal** boundaries now while refusing to invent or promote MCP
operation/status/cancel/result Tools, host retry assumptions, confirmation behavior, or
host-specific result limits without the required evidence.

The ``:Status: merged`` value is the terminal document status after this plan PR passes
review/CI and lands. While the PR is open, this document is proposed rather than
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
#. this detailed Phase 4 plan;
#. ``docs/operation-idempotency.md``;
#. ``spec/operation/idempotency.yaml``;
#. ``spec/operation/lifecycle.yaml``;
#. ``docs/audit-evidence.md``;
#. ``spec/audit/audit-policy.yaml`` and ``schemas/audit/audit-event.schema.json``;
#. ``docs/mcp-schemas.md`` and ``schemas/mcp/binnacle-common.schema.json`` for the
   canonical operation snapshot vocabulary;
#. ``docs/mcp-large-results.md`` and ``spec/mcp/result-limits.yaml`` where retained
   payload semantics constrain internal storage;
#. ``docs/security/controller-transport.md`` for controller ownership/binding semantics;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

Machine-readable lifecycle/idempotency/audit contracts constrain the implementation but
do not expand Phase 4 into later operational capabilities.

2. Provisional/evidence gate
----------------------------

2.1 Concrete now
~~~~~~~~~~~~~~~

The following are owner-approved internal architecture and are fully specifiable now:

* the main Binnacle application is the sole authoritative SQLite owner;
* SQLAlchemy 2.x async APIs + ``aiosqlite`` + Alembic;
* WAL, ``synchronous=FULL``, foreign keys, and bounded busy timeout;
* durable operation and idempotency records before consequential effects;
* exact lifecycle states/transitions from ``spec/operation/lifecycle.yaml``;
* two-level idempotency ownership/duplicate-prevention semantics;
* filesystem-backed retained payloads with SQLite authoritative metadata;
* append-only RFC-8785-JCS + SHA-256 audit hash chaining;
* audit failure blocks new consequential work;
* a small replaceable ``PolicyEngine`` boundary with fail-closed Bootstrap policy;
* ports-and-adapters ownership and future executor/broker separation;
* no automatic retry of ``uncertain`` work.

2.2 Evidence-gated and not implemented here
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Until actual Phase 3 evidence exists and the relevant Tool contracts are separately
reviewed, Phase 4 does not freeze or expose:

* MCP ``operation_get``, ``operation_cancel``, result-retrieval, or status Tool names;
* MCP Task adaptation;
* Resources adaptation;
* host retry/confirmation semantics;
* model-visible retained-result page/chunk sizes lower than repository defaults;
* write/modify entitlement;
* controller scopes for future mutation classes;
* operation annotations/manifest entries;
* workspace/executor/Git/privileged/hardware operation contracts.

Internal application interfaces may use ``get_operation``, ``request_cancel``, and
``get_result`` semantics because those are Binnacle-owned lifecycle concepts. An MCP
adapter for them is a later evidence/contract promotion and is absent from this phase.

3. Roadmap exit gate
--------------------

Phase 4 implementation is complete only when unit/property/integration/system tests prove
all of the following:

* the configured SQLite database is migrated explicitly to the expected Alembic head;
* all required SQLite durability pragmas are verified on live connections;
* operation/idempotency state survives normal application restart;
* a logical mutating request has a durable global idempotency identity before any test
  effect boundary can run;
* concurrent first-use of the same key creates exactly one binding/operation;
* same owner + same key + same fingerprint returns the existing operation;
* same key + different fingerprint is rejected without another operation/effect;
* matching key under another controller cannot disclose/advance the old operation and
  cannot create a duplicate effect;
* raw idempotency keys are never persisted/logged/audited;
* lifecycle transitions reject edges not declared in ``spec/operation/lifecycle.yaml``;
* ``state_version`` starts at 1 and strictly increments on every transition;
* optimistic concurrent state updates cannot silently overwrite one another;
* ``uncertain`` is never automatically retried;
* restart reconciliation distinguishes known-no-effect work from effect-uncertain work;
* required append-only audit records are canonicalized, chained, fsynced, and verified;
* audit corruption/truncation/fork/storage failure makes the consequential kernel
  unavailable for new effects;
* bounded read-only recovery/status/verification remains possible where trustworthy;
* retained payload metadata and filesystem bytes cannot disagree silently;
* payload writes are atomic/finalized or explicitly incomplete; there is no silent
  truncation marked complete;
* minimal Bootstrap policy is fail-closed and its decision is durably correlated with
  the operation;
* no production adapter in this phase performs a real consequential device effect;
* no new host-facing MCP Tool/Resource/Task is added;
* exact-head GitHub Actions passes all normal gates.

4. Explicit non-goals
---------------------

Phase 4 does **not** implement:

* any workspace write/read Tool;
* ``probe_workspace_prepare``, ``probe_workspace_write``, or cleanup;
* real write-entitlement or host-confirmation testing;
* command execution or the execution supervisor;
* executor IPC/protocol;
* Git operations;
* package-manager operations;
* service restart/self-management;
* privileged broker or root operation vocabulary;
* hardware operations;
* production controller replacement/recovery UI;
* MCP Tasks/Resources/Prompts/MRTR;
* a general long-term policy language/engine;
* external audit checkpoint publication/anchoring;
* database replication/high availability;
* PostgreSQL or network database support;
* distributed locks;
* multiple authoritative application writers;
* production backup orchestration;
* automatic destructive retention/purge under pressure;
* Phase 5 design.

Test doubles may cross a synthetic effect boundary to prove idempotency/reconciliation.
Those doubles must be clearly test-only and cannot be reachable from the production MCP
catalogue or CLI.

5. Before/after semantics
-------------------------

Before Phase 4
~~~~~~~~~~~~~~

Binnacle can authenticate/read through the Phase 3 architecture but has no authoritative
operation database, durable idempotency record, general lifecycle store, or append-only
audit journal. No consequential capability should rely on process memory for correctness.

After Phase 4
~~~~~~~~~~~~~

Binnacle has an internal durable kernel that later operation-specific use cases can call:

::

   authenticated/validated request
      -> canonical request fingerprint + idempotency key digest
      -> atomically create/find durable binding and operation
      -> evaluate/durably record Bootstrap policy decision
      -> durably authorize operation
      -> append/fsync required audit evidence
      -> effect boundary port (test-only in Phase 4; real adapters later)
      -> persist effect knowledge/result metadata
      -> reconcile/recover truthfully after restart

The kernel is ready to support future effects but does not itself grant one.

6. Exact repository changes
---------------------------

The Phase 4 **implementation** is expected to create/modify the following paths. This
planning PR itself adds only this document.

6.1 Existing project/application files to modify
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   pyproject.toml
   uv.lock
   .gitignore
   .github/workflows/python.yml
   src/binnacle/application.py
   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/cli.py

Do not alter the five Phase 3 MCP Tool contracts/manifest solely to expose the kernel.

6.2 Domain/application/port modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/domain/operation.py
   src/binnacle/domain/idempotency.py
   src/binnacle/domain/policy.py
   src/binnacle/domain/audit.py
   src/binnacle/domain/payload.py
   src/binnacle/ports/operation_store.py
   src/binnacle/ports/policy.py
   src/binnacle/ports/audit.py
   src/binnacle/ports/payload.py
   src/binnacle/ports/effect.py
   src/binnacle/application/operations.py
   src/binnacle/application/reconciliation.py
   src/binnacle/application/kernel_health.py

If ``src/binnacle/application.py`` from earlier phases remains a module rather than a
package, implementation may create ``src/binnacle/operations.py`` and
``src/binnacle/reconciliation.py`` instead of converting package shape. Do not create two
parallel canonical ownership paths; choose one repository-consistent shape in the first
implementation PR and update imports atomically.

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

Alembic owns schema evolution. Runtime code never creates missing tables opportunistically
with ``metadata.create_all()`` outside tests.

6.4 Audit and payload adapters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

6.5 Local operator scripts/tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create/update at least:

::

   scripts/verify_operation_kernel.py
   tests/unit/test_operation_domain.py
   tests/unit/test_idempotency_domain.py
   tests/unit/test_policy_domain.py
   tests/unit/test_audit_domain.py
   tests/unit/test_payload_domain.py
   tests/unit/test_bootstrap_policy.py
   tests/unit/test_audit_journal.py
   tests/unit/test_payload_store.py
   tests/integration/test_sqlite_operation_store.py
   tests/integration/test_idempotency_concurrency.py
   tests/integration/test_operation_restart_reconciliation.py
   tests/integration/test_audit_failure_gate.py
   tests/integration/test_payload_integrity.py
   tests/integration/test_alembic_migrations.py
   tests/property/test_operation_lifecycle_properties.py
   tests/property/test_idempotency_properties.py

Use existing operation/audit fixtures and contracts rather than creating a second
lifecycle/status vocabulary.

7. Direct dependency changes
----------------------------

7.1 Runtime dependencies
~~~~~~~~~~~~~~~~~~~~~~~~

Add the owner-approved persistence stack:

* ``SQLAlchemy`` on the 2.x line;
* ``aiosqlite``;
* ``Alembic``;
* one maintained RFC 8785 JSON Canonicalization Scheme implementation for authoritative
  audit canonical bytes.

The implementation PR must verify the selected JCS package against the audit contract and
Python 3.11/3.12/3.13 matrix before locking it. Do not write a partial home-grown JCS
encoder or substitute ordinary ``json.dumps(sort_keys=True)``.

No database server/client, Redis, distributed-lock library, ORM framework other than
SQLAlchemy, or general policy engine is added.

7.2 Development/test dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reuse pytest/AnyIO/Hypothesis/coverage/tox and existing quality tools. Add no separate
SQLite testing framework. Hypothesis is specifically required for lifecycle,
idempotency, and state-version invariants.

7.3 Lock discipline
~~~~~~~~~~~~~~~~~~~

Exact direct/transitive versions remain in ``uv.lock``. CI uses frozen sync and explicit
Python interpreter selection as established by prior phases.

8. Runtime state layout
-----------------------

Under the development/system profile use:

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

``/etc/binnacle`` remains protected configuration/policy. ``/run/binnacle`` remains
runtime/ephemeral IPC/control state.

The database, audit journal, retained payloads, controller security configuration, and
source repository must not share one deletion/reset boundary.

Directory ownership is the dedicated Binnacle application identity with restrictive
modes. Reusable credentials are not stored anywhere under ordinary operation/result/audit
state.

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

Paths are structural/control-plane settings. Production/system profile paths cannot be
redirected into the source checkout, world-writable directories, network filesystems, or
arbitrary paths by ordinary environment variables/CLI flags. Tests may inject temporary
paths through explicit composition constructors.

No hot reload of database/audit/storage roots exists. Changes require controlled restart
and, where relevant, checkpoint/migration procedure.

10. SQLite engine contract
--------------------------

``binnacle.adapters.sqlite.engine`` owns engine/session construction only.

Expose equivalent APIs:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class DatabaseRuntime:
       engine: AsyncEngine
       session_factory: async_sessionmaker[AsyncSession]

   async def create_database_runtime(settings: DatabaseSettings) -> DatabaseRuntime: ...
   async def verify_database_runtime(runtime: DatabaseRuntime) -> DatabaseHealth: ...
   async def close_database_runtime(runtime: DatabaseRuntime) -> None: ...

Every SQLite connection verifies/applies:

::

   PRAGMA foreign_keys=ON;
   PRAGMA journal_mode=WAL;
   PRAGMA synchronous=FULL;
   PRAGMA busy_timeout=<bounded milliseconds>;
   PRAGMA wal_autocheckpoint=<configured pages>;

Read back effective values. Startup fails the consequential-kernel readiness gate if
required durability values cannot be established.

Use local filesystem storage only. Detect and refuse obviously unsupported/non-local
runtime locations where correctness cannot be established.

11. Database transaction rules
------------------------------

SQLite/SQLAlchemy and Linux effects are never described as one ACID transaction.

Rules:

* one ``AsyncSession`` per application use-case transaction;
* no long-running external I/O while holding a SQLite write transaction;
* admission/idempotency create-or-find uses an explicit short write transaction;
* use SQLite uniqueness + conflict handling as the correctness mechanism, not a Python
  process lock;
* use ``BEGIN IMMEDIATE`` or an equivalently verified SQLAlchemy/SQLite write-admission
  strategy for the narrow create/find critical section where needed;
* commit durable intent before crossing an effect boundary;
* state updates use expected ``state_version`` optimistic concurrency checks;
* retry ``database is locked`` only within a small bounded internal transaction retry
  policy and never reinterpret it as permission to repeat an external effect;
* commit/rollback exceptions after a possible effect are reconciled truthfully; they do
  not trigger automatic effect repetition.

A database outage or inability to fsync durable intent rejects new consequential
admission.

12. Initial database schema
---------------------------

Migration ``0001_durable_operation_kernel`` creates the minimum authoritative schema.
Names below are normative unless SQLAlchemy naming conventions require a narrow syntactic
adjustment.

12.1 ``kernel_meta``
~~~~~~~~~~~~~~~~~~~~

Singleton/epoch facts:

* ``id`` integer primary key constrained to one active row;
* ``schema_generation``;
* ``device_id``;
* ``device_epoch`` integer >= 1;
* ``created_at``;
* ``updated_at``;
* ``audit_stream_id``;
* ``audit_epoch`` integer >= 1;
* ``audit_last_sequence`` integer >= 0;
* ``audit_last_hash`` nullable SHA-256;
* ``consequential_admission_enabled`` boolean.

On first initialization ``device_epoch=1``. If the configured/observed device identity no
longer matches the durable record, startup does not silently adopt a new device epoch.
That requires explicit future recovery/owner action; Phase 4 fails consequential
readiness.

12.2 ``controller_owners``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Persist only durable ownership facts, never credentials:

* ``controller_id``;
* ``controller_epoch`` integer >= 1;
* ``controller_profile_id``;
* ``controller_profile_version``;
* ``first_seen_at``;
* ``last_seen_at``;
* ``active``.

Primary key: ``(controller_id, controller_epoch)``.

The active-controller rule remains owned by the controller/security layer. This table is
the durable operation-ownership reference, not an authentication database.

12.3 ``operations``
~~~~~~~~~~~~~~~~~~~

Columns:

* ``operation_id`` primary key;
* ``controller_id`` + ``controller_epoch`` foreign key;
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
* ``effect_reference_digest`` nullable;
* ``policy_decision_id`` nullable initially;
* ``error_code`` / ``error_summary`` / ``retry_action`` nullable as lifecycle permits;
* ``runtime_build_sha256``;
* ``runtime_config_sha256``;
* ``controller_profile_version_snapshot``;
* ``created_at`` / ``updated_at``;
* ``authorised_at`` nullable;
* ``started_at`` nullable;
* ``terminal_at`` nullable;
* ``last_reconciled_at`` nullable.

Checks enforce the canonical lifecycle vocabulary, effect-knowledge vocabulary, terminal
class, non-negative versions, and no ``automatic_retry_allowed=true``.

Indexes:

* owner + creation time;
* state + updated time;
* terminal time;
* request fingerprint for diagnostics only (not duplicate-prevention authority).

12.4 ``operation_transitions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Append-only lifecycle history:

* ``operation_id`` foreign key;
* ``state_version``;
* ``from_state`` nullable for version 1;
* ``to_state``;
* ``effect_knowledge``;
* ``terminality``;
* ``reason_code``;
* ``error_code`` nullable;
* ``recorded_at``;
* ``runtime_build_sha256``.

Primary key ``(operation_id, state_version)``. No transition row is updated after commit.
The ``operations`` row is the current snapshot; transition rows are authoritative state
history inside the application database, distinct from security audit events.

12.5 ``idempotency_bindings``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Columns follow ``spec/operation/idempotency.yaml``:

* ``binding_id`` primary key;
* ``device_id``;
* ``device_epoch``;
* ``key_mode``;
* ``key_digest_sha256``;
* ``tool_name`` / ``contract_version`` or internal operation-contract equivalents;
* ``owner_controller_id``;
* ``owner_controller_epoch``;
* ``request_fingerprint_sha256``;
* ``prepared_operation_id`` nullable;
* ``prepared_input_sha256`` nullable;
* ``target_identity_sha256`` nullable;
* ``maximum_effect_sha256`` nullable;
* ``operation_id`` foreign key nullable only after future record compaction;
* ``created_at``;
* ``last_access_at``;
* ``terminal_at`` nullable;
* ``retired_at`` nullable;
* ``record_kind`` enum ``full``/``tombstone``;
* ``duplicate_count``;
* ``conflict_count``.

The global duplicate-prevention unique index is exactly the contract scope:

::

   (device_id, device_epoch, tool_name, contract_version, key_digest_sha256)

For internal pre-Tool tests, ``tool_name`` is a reserved stable internal contract name,
not an invented visible MCP Tool.

The same durable row becomes the security tombstone; Phase 4 does not move it to another
table and thereby lose atomic global uniqueness.

12.6 ``policy_decisions``
~~~~~~~~~~~~~~~~~~~~~~~~~

Store bounded structured decision facts:

* ``policy_decision_id`` primary key;
* ``operation_id`` foreign key;
* ``policy_id`` / ``policy_version``;
* ``decision`` enum ``allow``/``deny``;
* ``controller_id`` / ``controller_epoch``;
* ``operation_contract`` / version;
* ``required_scope_digest`` nullable;
* ``normalized_target_digest`` nullable;
* ``input_facts_sha256``;
* ``reason_codes_json`` bounded canonical JSON;
* ``decided_at``;
* ``runtime_policy_sha256``.

No raw credential or unbounded user content is stored.

12.7 ``payload_objects``
~~~~~~~~~~~~~~~~~~~~~~~~

SQLite metadata for filesystem payloads:

* ``payload_id`` primary key;
* ``operation_id`` nullable foreign key;
* ``controller_id`` / ``controller_epoch``;
* ``kind`` enum such as ``result``/``stdout``/``stderr``/``evidence``/``internal``;
* ``lifecycle`` enum ``building``/``complete``/``failed``/``expired``/``deleted``;
* ``relative_path``;
* ``media_type``;
* ``encoding``;
* ``decoded_byte_count``;
* ``sha256`` nullable until complete;
* ``truncated`` boolean;
* ``information_class``;
* ``retention_class``;
* ``created_at`` / ``completed_at`` nullable / ``expires_at`` nullable;
* ``last_access_at`` nullable.

Unique constraint on ``relative_path``. Metadata never claims ``complete`` until payload
bytes are durably finalized and digest-verified.

12.8 ``operation_evidence``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bounded correlation metadata:

* ``evidence_id`` primary key;
* ``operation_id`` foreign key;
* ``source``;
* ``provenance``;
* ``information_class``;
* ``fresh_until`` nullable;
* ``result_sha256`` nullable;
* ``payload_id`` nullable foreign key;
* ``audit_ref`` nullable;
* ``facts_json`` bounded canonical JSON;
* ``recorded_at``.

This table does not replace the append-only audit journal and does not store credentials.

13. Domain lifecycle model
--------------------------

``binnacle.domain.operation`` owns exact values mirroring
``spec/operation/lifecycle.yaml``:

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

Use one table-driven transition validator generated/loaded from the reviewed lifecycle
contract at startup or represented by a hand-maintained exact mapping protected by a
contract-parity test. Do not maintain multiple divergent transition maps.

Invalid edge/effect-knowledge/error/terminality combinations fail before persistence.

14. Operation identity and request fingerprint
----------------------------------------------

``operation_id`` is server-generated from at least 128 random bits and rendered as a
schema-compatible opaque identifier such as:

::

   op_<32 lowercase hex>

Request fingerprinting uses a closed normalized structure containing exactly the
idempotency contract's effect-bearing fields. Canonical bytes use the same verified JCS
implementation where values are within I-JSON constraints; SHA-256 produces
``request_fingerprint_sha256``.

Fingerprint excludes current policy decisions, observation freshness, and mutable
resource availability so a retry finds/reconciles the original binding rather than
creating a new effect.

Normalization belongs to the operation-specific caller/use case. The kernel accepts a
typed ``OperationIntent`` containing normalized effect inputs and their canonical
digests; it does not guess filesystem/Git/command semantics.

15. Idempotency key handling
----------------------------

``binnacle.domain.idempotency`` defines:

.. code-block:: python

   class IdempotencyKeyMode(StrEnum):
       CALLER_KEY = "caller_key"
       PREPARED_EXECUTION_NONCE = "prepared_execution_nonce"
       DERIVED_MEMBER_KEY = "derived_member_key"

   @dataclass(frozen=True, slots=True)
   class IdempotencyIdentity:
       mode: IdempotencyKeyMode
       digest_sha256: str

``caller_key`` validation accepts only the encodings/randomness rules in
``spec/operation/idempotency.yaml``. Raw keys exist only long enough to validate/decode
and compute a domain-separated SHA-256 digest; they are not stored in domain snapshots,
SQLite, logs, audit, metrics labels, or errors.

UUIDv4 alone is rejected as a compliant caller key according to the existing contract.

16. Atomic create-or-find semantics
----------------------------------

``OperationStore.create_or_find`` owns the critical first transaction.

Port shape:

.. code-block:: python

   class OperationStore(Protocol):
       async def create_or_find(
           self,
           *,
           intent: OperationIntent,
           idempotency: IdempotencyIdentity,
           owner: OperationOwner,
           runtime: RuntimeProvenance,
       ) -> CreateOrFindResult: ...

       async def get(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot: ...
       async def transition(self, request: TransitionRequest) -> OperationSnapshot: ...
       async def attach_policy_decision(...): ...
       async def attach_effect_reference(...): ...

Transaction algorithm:

#. begin short write transaction;
#. attempt/select the global idempotency binding by exact unique scope;
#. if absent, create binding + ``received`` operation + version-1 transition atomically;
#. if present, compare owner and request fingerprint without disclosing another owner's
   operation;
#. same owner/same fingerprint -> return retained operation;
#. same owner/different fingerprint -> increment conflict counter and return
   ``idempotency_conflict``;
#. different controller -> increment conflict counter and return non-disclosing
   ``idempotency_owner_mismatch``;
#. commit;
#. only a newly created operation proceeds to policy/admission.

Concurrent uniqueness races catch the database uniqueness conflict, roll back, re-read,
and reconcile. They do not create a second operation.

17. Minimal Bootstrap ``PolicyEngine``
--------------------------------------

``binnacle.ports.policy`` defines:

.. code-block:: python

   class PolicyEngine(Protocol):
       async def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...

``PolicyRequest`` contains only normalized/bounded facts:

* authenticated controller ID/profile/epoch;
* operation contract/version;
* transport scope names already validated where available;
* normalized target/effect digests;
* maximum-effect classification;
* runtime/development-session flags when later supplied;
* current protected policy identity/digest.

Phase 4 ``BootstrapPolicyEngine`` is deliberately fail-closed:

* unknown operation contract -> deny;
* no authenticated owner/controller -> deny;
* protected/control-plane targets -> deny unless a later reviewed contract explicitly
  supplies authority;
* no generic wildcard allow;
* no embedded scripting/policy language;
* no environment/CLI override that broadens security-critical policy.

Because Phase 4 exposes no real consequential operation contract, production policy does
not need to allow one. Kernel integration tests inject a fixture/test policy and synthetic
operation contract to exercise the full admission/effect path. Later phases extend
reviewed operation contracts without replacing the ``PolicyEngine`` port.

18. Consequential admission sequence
------------------------------------

``OperationCoordinator`` in the application layer owns the required ordering:

#. receive already-authenticated owner + normalized ``OperationIntent`` + raw
   idempotency input from a future caller;
#. validate key syntax and derive safe key digest;
#. atomically ``create_or_find`` global binding/operation;
#. if retained/conflict/owner-mismatch, return reconciliation result without effect;
#. append/fsync ``operation_received`` audit event for a newly created operation;
#. evaluate policy;
#. durably persist policy decision;
#. on deny, transition ``received -> rejected`` and append required rejection audit;
#. on allow, transition ``received -> authorised`` and commit;
#. append/fsync authorization audit;
#. **only now** call the ``EffectBoundary`` port;
#. persist boundary acknowledgement/effect knowledge/result metadata;
#. append/fsync corresponding effect/lifecycle audit;
#. return retained operation snapshot/result metadata.

If required audit fails before step 10, no effect boundary is crossed and new
consequential work becomes fail-restricted.

There is deliberately no production effect adapter in Phase 4.

19. Effect boundary/reconciliation seam
---------------------------------------

``binnacle.ports.effect`` defines the minimum later-process seam without defining executor
or broker IPC:

.. code-block:: python

   class EffectBoundary(Protocol):
       async def start(self, request: EffectRequest) -> EffectStartReceipt: ...

   class EffectReconciler(Protocol):
       async def reconcile(self, reference: EffectReference) -> EffectObservation: ...

``EffectStartReceipt`` can express only:

* effect boundary definitely not crossed;
* effect boundary crossed with stable opaque external reference;
* outcome already known;
* outcome uncertain.

No subprocess/Git/systemd/root vocabulary exists here.

Phase 4 production composition uses ``UnavailableEffectBoundary`` which rejects start,
proving that merely adding the kernel creates no device effect. Integration tests inject
``CountingTestEffectBoundary`` backed by a separate test store/counter to prove one-effect
semantics under response loss/concurrency/restart.

Later executor/broker phases implement their own adapters/IPC behind this port and must
not open the application SQLite database directly.

20. State transition persistence
--------------------------------

Every transition:

#. loads current state/version;
#. validates exact lifecycle edge and cross-field invariants;
#. issues conditional update ``WHERE operation_id=? AND state_version=?``;
#. increments version exactly once;
#. inserts the matching append-only transition row in the same SQLite transaction;
#. requires exactly one updated row;
#. returns ``state_conflict`` on a stale expected version rather than overwriting.

Duplicate observation may return the same existing version when it is semantically the
same observation; it does not create a fake transition/version.

Transition-specific requirements include:

* ``received`` can only become ``rejected`` or ``authorised``;
* ``authorised`` may become ``running``, ``cancelling``, ``cancelled``, or ``failed``;
* ``uncertain`` is ``effect_terminal_reconcilable`` and only reconciliation may move it
  to ``succeeded``/``failed``/``cancelled``;
* ``cancelled`` requires verified cancellation/remaining-effect truth;
* ``succeeded`` requires verified effect knowledge and no error;
* rejected/failed/uncertain require the contract-defined error presence.

21. Restart reconciliation
--------------------------

``OperationReconciler`` runs after DB/audit/payload verification and before the
consequential kernel is considered available.

Scan nonterminal/effect-reconcilable operations in bounded pages.

Rules:

* ``received`` with no authorization/effect crossing -> transition to ``rejected`` with
  ``restart_before_admission`` after required audit is available;
* ``authorised`` with no effect-boundary reference/crossing -> ``failed`` with
  ``known_no_effect``; never redispatch automatically;
* ``running``/``paused``/``cancelling`` with a stable external reference -> ask the
  configured ``EffectReconciler``;
* if no reconciler exists or outcome cannot be proven -> ``uncertain``;
* existing ``uncertain`` remains uncertain until an explicit reconciliation observation
  proves a permitted terminal transition;
* no startup path creates a fresh idempotency key or replays an effect automatically.

Phase 4 production has no external effect references; property/integration tests exercise
all branches with fakes.

22. Cancellation/status/result application interfaces
-----------------------------------------------------

These are internal/use-case APIs only in Phase 4.

Expose equivalent methods:

.. code-block:: python

   class OperationService:
       async def get_operation(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot: ...
       async def request_cancel(self, operation_id: str, owner: OperationOwner) -> OperationSnapshot: ...
       async def get_payload_metadata(self, payload_id: str, owner: OperationOwner) -> PayloadMetadata: ...
       async def read_payload_range(...): ...

``get_operation`` of a failed/uncertain operation is a successful query of represented
state; application exceptions are reserved for malformed/not-owned/not-found requests.

``request_cancel``:

* never treats transport disconnect as cancellation;
* validates owner/current state/state version;
* transitions to ``cancelling`` only where lifecycle permits;
* calls a cancellation-capable future effect adapter only when one exists;
* never marks ``cancelled`` until cancellation is verified;
* may become ``succeeded``/``failed``/``uncertain`` depending on truthful reconciliation.

No MCP registration/projection is added in this phase.

23. Payload storage contract
----------------------------

``PayloadStore`` owns bytes; SQLite owns authoritative metadata/ownership/lifecycle.

Port shape:

.. code-block:: python

   class PayloadStore(Protocol):
       async def create_stream(self, spec: PayloadSpec) -> PayloadHandle: ...
       async def append(self, handle: PayloadHandle, data: bytes) -> PayloadAppendResult: ...
       async def finalize(self, handle: PayloadHandle) -> FinalizedPayload: ...
       async def abort(self, handle: PayloadHandle, reason: str) -> None: ...
       async def read_range(self, payload_id: str, offset: int, length: int) -> bytes: ...
       async def verify(self, payload_id: str) -> PayloadVerification: ...

Filesystem adapter behavior:

* create with exclusive names under implementation-owned root;
* never accept caller-supplied absolute paths;
* append using bounded chunks;
* track byte count incrementally;
* enforce per-object/per-controller quotas before growth;
* fsync data before finalization;
* compute SHA-256 of decoded/full bytes;
* atomically rename ``tmp``/``.part`` file to finalized path;
* fsync containing directory;
* only then commit SQLite lifecycle ``complete``/digest metadata;
* if crash occurs between filesystem finalize and DB commit, startup verification treats
  the orphan as unreferenced/recoverable and never exposes it as complete;
* if DB says complete but bytes/digest are absent/wrong, mark integrity failure and block
  affected result use.

No silent truncation is marked complete. ``truncated=true`` is explicit metadata and a
later Tool contract must decide whether truncated data is a valid complete result or an
error/reference.

24. Retained payload/result semantics
-------------------------------------

Phase 4 establishes internal storage but not host-facing pagination Tools.

Use repository default maximums from ``mcp-large-results.md`` as storage ceilings unless
the implementation profile is more restrictive. Actual host-visible effective limits
remain Phase-3-evidence-gated.

Retention classes are stored exactly as policy identifiers. Phase 4 implements safe
expiry/tombstone metadata and explicit operator/test cleanup only; it does not introduce
a broad automatic deletion policy that could remove uncertainty/recovery evidence.

Quota pressure rejects new payload production when protected data cannot be evicted
safely.

25. Operation evidence metadata
-------------------------------

``OperationEvidence`` mirrors only bounded canonical evidence facts needed internally:

* source/provenance;
* information class;
* freshness;
* optional result digest;
* operation/payload/audit reference;
* bounded diagnostic facts.

It is a projection/index, not security audit authority. Raw command output, repository
content, credentials, tokens, private keys, or unbounded prompt content never enter
``facts_json``.

Later MCP evidence projection must revalidate information class/recipient and host
profile before model visibility.

26. Append-only audit journal
-----------------------------

``AuditJournal`` is independent from ordinary structlog/journald and independent from
SQLite as the authoritative event bytes.

The adapter implements the existing audit contract exactly:

* UTF-8;
* RFC 8785 JCS canonicalization;
* I-JSON-compatible values;
* SHA-256 with ``event_hash`` omitted from preimage;
* ``previous_event_hash`` chain;
* strict sequence monotonicity;
* segment metadata with first/last sequence, count, bytes, previous segment digest and
  final digest;
* audit epoch continuity.

Redaction happens before canonicalization/persistence. Raw idempotency keys and authority
material are prohibited.

Phase 4 does not claim external-compromise-resistant history because external checkpoint
publication is deferred.

27. Audit persistence ordering
------------------------------

Required events are fsynced before their gated action continues.

Admission ordering:

* DB ``received`` intent commits;
* ``operation_received`` audit appends/fsyncs;
* policy decision commits;
* decision/rejection or authorization audit appends/fsyncs;
* only a successfully audited authorization may cross the effect boundary.

After an external/test effect, truthful state persistence takes priority; audit follows
immediately and is fsynced. If audit fails after a known effect, do not roll back history
or repeat the effect. Mark audit subsystem degraded, retain truthful operation state, and
block new consequential admission until repaired.

SQLite and audit are therefore deliberately two durable systems with explicit recovery,
not falsely described as one transaction.

28. Audit failure gate and emergency journal
-------------------------------------------

``KernelHealth`` includes independent database/audit/payload status.

When required audit cannot append/fsync/verify:

* set in-memory + durable control state disabling new consequential admission where DB is
  available;
* do not cross a new effect boundary;
* allow bounded status/verification/recovery reads when their stores remain trustworthy;
* attempt one bounded emergency audit record only if the pre-created emergency journal
  remains writable/trustworthy;
* emergency-journal exhaustion remains fail-restricted;
* operator recovery must verify surviving chain continuity before re-enabling admission.

No silent fallback to ordinary logs exists.

29. Audit verification
----------------------

``AuditVerifier`` checks on startup and via local operator command:

* event schema validity;
* JCS hash recomputation;
* sequence monotonicity;
* previous-event hash chain;
* segment digest/count/byte metadata;
* epoch continuity;
* unexpected truncation/fork/duplicate sequence;
* canonical event byte size <= policy maximum.

Verification result reports safe sequence/hash prefixes and error codes, not sensitive
payloads.

30. Database/audit consistency checkpoints
------------------------------------------

Phase 4 needs a local consistency marker without pretending SQLite/audit are one
transaction.

After clean startup and at explicit verification points record a bounded checkpoint event
containing:

* database schema revision;
* highest operation/transition sequence summary;
* audit epoch/sequence/final digest;
* runtime build/config/policy digests.

SQLite stores only the checkpoint reference/digest metadata needed for diagnostics. The
audit event remains authoritative audit bytes.

This is a **local** consistency/checkpoint mechanism, not the optional external signed
checkpoint defined for post-compromise history claims.

31. Minimal local operator CLI
-----------------------------

Extend the existing CLI with local-operator commands only:

::

   binnacle db status
   binnacle db upgrade
   binnacle kernel verify
   binnacle audit verify

``db status``
   Read current Alembic revision/required pragmas without mutation.

``db upgrade``
   Explicitly run reviewed Alembic migrations to head. It is never callable through MCP
   in Phase 4.

``kernel verify``
   Verify DB schema/pragmas, operation invariants, payload metadata integrity, and audit
   continuity. It does not repair automatically.

``audit verify``
   Verify the append-only audit chain.

Human/agent/JSON output follows existing CLI conventions and never dumps raw payload/audit
content.

32. Migration/startup behavior
------------------------------

Application startup does **not** silently upgrade schema.

Sequence:

#. open database enough to inspect Alembic revision;
#. if DB is new/uninitialized, readiness reports migration required;
#. if DB revision != expected head, consequential kernel remains unavailable;
#. operator runs explicit ``binnacle db upgrade``;
#. startup reopens/verifies SQLite pragmas/schema;
#. verify audit journal continuity;
#. verify payload roots/metadata invariants;
#. run bounded operation restart reconciliation;
#. mark internal kernel available/degraded/unavailable.

Migration failure never deletes/recreates the database.

33. Alembic migration rules
---------------------------

Migration ``0001`` must:

* create all Phase 4 tables/indexes/check constraints in one reviewed migration;
* be deterministic on an empty local SQLite DB;
* reject incompatible pre-existing unmanaged tables instead of taking ownership
  silently;
* record schema revision normally through Alembic;
* not import the running application/composition graph;
* not access network/auth credentials;
* have upgrade tests from empty and downgrade/round-trip tests where downgrade is safe.

Future destructive migrations require checkpointing/recovery design; Phase 4 has no
production destructive migration yet.

34. Kernel health/readiness semantics
-------------------------------------

Define internal:

.. code-block:: python

   class KernelAvailability(StrEnum):
       AVAILABLE = "available"
       DEGRADED = "degraded"
       UNAVAILABLE = "unavailable"

Consequential admission requires ``AVAILABLE``.

Phase 4 does not change public/MCP ``/readyz`` response shape solely to expose kernel
status because no current read-only Tool depends on the kernel. Existing compatibility
server may remain ready while internal kernel is degraded, but logs/local ``kernel
verify`` must report it. A later phase that promotes mutating Tools makes kernel
availability part of readiness for those capabilities.

This avoids host-facing contract drift before Phase 3 evidence/Tool promotion.

35. Errors
----------

Define stable internal/application error codes including:

::

   database_unavailable
   database_revision_mismatch
   database_state_conflict
   idempotency_invalid
   idempotency_conflict
   idempotency_owner_mismatch
   idempotency_key_retired
   idempotency_storage_unavailable
   policy_rejected
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

These are not automatically MCP execution-error codes until a later reviewed Tool
contract explicitly maps them.

Cross-controller not-found/owner-mismatch results are non-disclosing at host-facing
boundaries later; internal logs/audit use safe digests only.

36. Controller ownership binding
--------------------------------

Phase 4 does not authenticate requests itself; it consumes the validated controller
identity produced by the selected Phase 3 controller profile when that implementation
exists.

Durable operation ownership stores only:

* opaque ``controller_id``;
* controller profile/version;
* controller epoch;
* no reusable credential.

A successor/replacement controller cannot automatically read/advance old operations and
cannot reuse an old key to create a duplicate. Explicit owner transfer/recovery remains a
separate future contract.

If Phase 3 evidence changes the exact selected auth-profile fields, only the adapter that
constructs ``OperationOwner`` changes; the durable kernel schema does not invent missing
tenant/client/binding values.

37. Process-boundary ownership
------------------------------

The main MCP/application process is the sole owner that opens authoritative
``binnacle.db`` for normal application writes.

Future executor and privileged-broker processes:

* do not open this SQLite database directly;
* retain only minimum independent execution/broker evidence;
* reconcile through typed IPC/application ports;
* return stable external execution/reference identities to the application process.

Phase 4 defines ``EffectBoundary``/``EffectReconciler`` semantics only. It does not define
or implement Unix-socket message schemas for a process that does not yet exist.

Audit/payload filesystem adapters execute in the application process in Phase 4.

38. Logging and diagnostics
---------------------------

Add structured safe events for:

* database open/close/pragmas/migration revision;
* operation create/find/transition by operation ID;
* idempotency outcome using digest prefix only, never raw key;
* policy decision ID/result/reason code;
* reconciliation decision;
* payload lifecycle/byte counts/digest prefix;
* audit append/segment/verification status;
* kernel availability transitions.

Do not log:

* raw idempotency key/nonces;
* credentials/controller security tokens;
* full request fingerprint inputs;
* complete operation payloads/stdout/stderr;
* raw policy protected values;
* full audit event bodies by default.

Audit and diagnostic logs remain separate systems.

39. Property tests
------------------

Hypothesis state machines/property tests must cover:

* every allowed lifecycle edge and every forbidden edge;
* state-version monotonicity;
* valid state/effect-knowledge/terminality/error combinations;
* duplicate observation not creating an artificial version;
* same key/same normalized input reconciliation;
* same key/different input conflict;
* cross-controller key replay non-disclosure/no effect;
* concurrent first request exactly-one binding;
* ``uncertain`` never auto-retries;
* cancellation cannot become cancelled without verification;
* retention/tombstone record retains duplicate-prevention authority.

Tests consume the reviewed YAML contracts or parity fixtures so contract changes fail
property assumptions visibly.

40. Integration/fault tests
---------------------------

Use temporary local SQLite/filesystem roots and a separate counting effect fixture.

Required fault points include:

* crash before idempotency transaction commit;
* crash after ``received`` commit/before audit;
* audit failure before policy;
* policy deny;
* crash after ``authorised`` commit/before audit;
* crash after authorization audit/before effect boundary;
* lost response after test effect;
* DB write failure after known test effect;
* audit failure after known test effect;
* restart with running/cancelling/uncertain state;
* concurrent duplicate requests from one owner;
* matching key from another owner;
* same key/different fingerprint;
* SQLite busy/lock timeout;
* database read-only/disk-full simulation where feasible;
* audit event bit flip/delete/reorder/truncation/fork;
* emergency-journal exhaustion;
* payload temp-file crash/finalize-before-DB-commit orphan;
* DB-complete/payload-missing/digest-mismatch;
* payload quota pressure.

The synthetic counter proves at most one effect for one logical idempotency identity.
Tests never mutate the real repository/system.

41. Restart tests
-----------------

Integration tests compose application, admit synthetic operations, close all runtime
objects, reconstruct a fresh application/runtime, and verify:

* retained operation identity/state/version remains resolvable;
* idempotency binding still reconciles;
* terminal results remain stable;
* uncertain remains uncertain;
* known-no-effect pre-boundary work is not redispatched;
* audit sequence continues without reset/fork;
* payload finalized objects remain digest-valid;
* incomplete/orphan payloads are detected safely.

Do not simulate restart by reusing in-memory repositories/singletons.

42. Audit contract tests
------------------------

Required tests include existing audit-contract cases:

* RFC 8785 edge cases and exact canonical bytes;
* hash changes on bit modification;
* insertion/deletion/reorder/truncation detection;
* duplicate sequence/fork detection;
* segment rotation and epoch continuity;
* payload ``kind``/schema mismatch;
* bounded safe facts/event bytes;
* secret/authority-material redaction before hash;
* primary audit storage failure;
* emergency journal behavior;
* fail-restricted new consequential work.

External checkpoint/non-equivocation service integration is deferred, but local verifier
must not claim protection from full-host compromise.

43. Payload tests
-----------------

Cover:

* zero-length object;
* boundary/max object size;
* append chunks and byte counts;
* duplicate/finalize calls idempotently returning same finalized metadata;
* append after finalize rejected;
* quota overflow before write;
* atomic temp/final rename;
* fsync/rename failure;
* orphan recovery;
* complete metadata with missing/corrupt bytes;
* UTF-8/binary bytes remain byte-exact;
* restricted information class is never downgraded by storage/retrieval;
* range overflow/negative lengths rejected.

Host-facing page/cursor semantics remain later projection work.

44. Policy tests
----------------

Test production Bootstrap policy:

* unknown operation denied;
* missing controller denied;
* protected target denied;
* broad/unrecognized scope cannot create allow;
* environment/CLI cannot enable wildcard authority;
* decision output is bounded/deterministic/versioned.

Test fixture policy separately for synthetic kernel effect tests. Never ship a hidden
``allow_all`` production switch.

45. Migration tests
-------------------

For Python 3.11/3.12/3.13 and SQLite available on CI:

* fresh ``alembic upgrade head``;
* expected tables/indexes/checks/FKs exist;
* foreign key enforcement actually fails invalid inserts;
* WAL and synchronous FULL verified;
* application refuses behind/ahead unknown revision;
* migration is not rerun concurrently by application workers;
* downgrade round-trip where implemented;
* migration failure leaves original DB intact/recoverable.

46. Security invariants
-----------------------

Phase 4 preserves all of these:

#. no production consequential effect adapter exists;
#. no new mutating MCP Tool/Resource/Task exists;
#. durable idempotency record exists before any synthetic/test effect boundary;
#. raw idempotency keys are never persisted/disclosed;
#. global duplicate-prevention survives controller replacement;
#. operation ownership does not transfer from key possession;
#. same key/different fingerprint never executes;
#. ``uncertain`` never triggers automatic retry;
#. lifecycle transitions are contract-exact and state-versioned;
#. main application process solely owns authoritative SQLite writes;
#. SQLite durability pragmas are verified, not assumed;
#. migration mismatch prevents consequential-kernel availability;
#. audit is authoritative append-only security evidence, not ordinary logs;
#. audit redaction precedes persistence/hash;
#. required audit failure blocks new consequential work;
#. payload metadata cannot claim complete before durable bytes/digest exist;
#. payload/result storage never contains reusable credentials;
#. security-critical database/audit/payload roots are not ordinary env/CLI-overridable;
#. policy is fail-closed and has no general script/wildcard authority;
#. later executor/broker does not gain DB access through this phase;
#. host-facing operation projection remains evidence/contract gated.

47. Quality/CI changes
----------------------

Extend the existing Python workflow; do not create a competing Phase 4 workflow.

Keep all previous gates and add:

.. code-block:: console

   uv run alembic upgrade head
   uv run python scripts/verify_operation_kernel.py --temporary
   uv run pytest tests/property
   uv run pytest tests/integration/test_sqlite_operation_store.py
   uv run pytest tests/integration/test_idempotency_concurrency.py
   uv run pytest tests/integration/test_audit_failure_gate.py
   uv run pytest tests/integration/test_payload_integrity.py

Run migrations/tests in isolated temporary directories/DBs. Never write CI state into
repository paths.

Keep ``pip-audit`` after new persistence/JCS dependencies, strict MyPy, Ruff/format,
Import Linter, coverage, contract/schema validation, compiler checks, and explicit
3.11/3.12/3.13 interpreter lanes.

48. Canonical local validation commands
---------------------------------------

The implementation PR documents/passes at least:

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

The operator/system profile separately runs ``binnacle db status``, reviewed explicit
``binnacle db upgrade``, and ``binnacle kernel verify`` against the development-Pi state.

49. Implementation order
------------------------

Implement Phase 4 in this order:

#. add persistence/JCS dependencies and Alembic skeleton;
#. define operation/idempotency/policy/audit/payload domain types and contract parity
   tests;
#. implement migration ``0001`` and SQLite engine/pragmas/health checks;
#. implement atomic operation/idempotency store and state-version transition store;
#. implement fail-closed Bootstrap ``PolicyEngine`` + durable decision recording;
#. implement JCS audit writer/verifier + storage-failure gate;
#. implement retained payload filesystem adapter + metadata consistency checks;
#. implement ``OperationCoordinator`` ordering up to the unavailable production effect
   boundary;
#. implement synthetic counting effect/reconciler only under tests;
#. implement startup reconciliation;
#. add local operator DB/kernel/audit commands;
#. add property/fault/restart/audit/payload/migration tests;
#. integrate internal kernel health into composition/logging without changing MCP Tool
   surface;
#. update CI/lock/import rules;
#. run full exact-interpreter validation;
#. stop before any host-facing write/status/cancel/result Tool promotion.

50. Review checklist
--------------------

A reviewer should verify:

* plan/implementation remains Phase 4 only;
* host-facing operation projection is explicitly provisional/evidence-gated;
* no Phase 5 write probe appears;
* SQLAlchemy 2.x/aiosqlite/Alembic match Bootstrap baseline;
* SQLite main-application ownership is preserved;
* no executor/broker directly accesses DB;
* lifecycle state vocabulary/edges match machine-readable contract exactly;
* idempotency global unique scope matches machine-readable contract;
* two-level duplicate prevention vs operation ownership is preserved;
* raw keys never persist;
* durable intent/audit authorization precede test effect boundary;
* same-key/different-input and cross-controller cases create no effect;
* ``uncertain`` never auto-retries;
* database and audit are not falsely treated as one transaction;
* audit uses RFC 8785 JCS + SHA-256 and chain verification;
* audit failure blocks new consequential work;
* payload completion is durability/digest truthful;
* Bootstrap policy remains minimal/fail-closed;
* migrations are explicit/no runtime ``create_all``;
* current five read-only MCP Tools are unchanged;
* all exact-head quality/CI gates pass.

51. Deterministic acceptance checklist
--------------------------------------

Phase 4 implementation is accepted only when every item below is true:

#. Direct persistence dependencies are locked and support Python 3.11--3.13.
#. Alembic ``0001`` creates exactly the Phase 4 authoritative schema.
#. Runtime never silently creates/migrates tables.
#. Database path is local/protected and separated from source/config/evaluation evidence.
#. Every connection verifies foreign keys/WAL/``synchronous=FULL``/busy timeout.
#. Migration mismatch makes consequential kernel unavailable.
#. ``kernel_meta`` binds stable device ID/epoch and audit continuity metadata.
#. Controller ownership records contain no reusable credential.
#. Operation lifecycle states exactly match ``spec/operation/lifecycle.yaml``.
#. Every state transition increments version once and records append-only history.
#. Invalid/stale transition is rejected.
#. Idempotency global unique index exactly matches contract scope.
#. Raw caller key/prepared nonce never persists/logs/audits.
#. Concurrent same-key admission produces one binding/operation.
#. Same owner + same key + same fingerprint returns retained operation.
#. Same key + different fingerprint returns conflict/no second operation.
#. Different controller + matching key reveals no old operation and creates no effect.
#. Tombstone form retains duplicate-prevention authority.
#. Production ``PolicyEngine`` denies unknown/unreviewed consequential contracts.
#. Policy decision is durable/correlated before authorization/effect.
#. Required authorization audit is durable before effect boundary.
#. Production composition has no real effect adapter.
#. Synthetic test effect proves at most one effect under concurrency/lost response.
#. Restart reconciliation never redispatches an effect automatically.
#. ``uncertain`` persists/reconciles only through explicit observation.
#. Cancellation cannot claim ``cancelled`` without verification.
#. Audit event canonicalization is RFC-8785-JCS + SHA-256 contract exact.
#. Audit chain detects modification/deletion/reordering/truncation/fork.
#. Required audit failure disables new consequential admission.
#. Emergency journal is bounded and failure remains fail-restricted.
#. Payload bytes are atomically finalized/fsynced/digest-verified before complete metadata.
#. Payload orphan/corruption/quota pressure are detected without silent completeness.
#. Operation evidence metadata is bounded and not authoritative audit storage.
#. Application restart reconstructs DB/idempotency/audit/payload truth from fresh runtime.
#. ``binnacle db status``/``db upgrade``/``kernel verify``/``audit verify`` are local-only
   operator paths and emit no secrets/raw payloads.
#. Existing Phase 3 authenticated read-only MCP behavior remains regression-tested.
#. No MCP Tool/Resource/Task/manifest change exposes Phase 4 operation APIs.
#. No workspace/command/Git/package/service/privileged/hardware effect capability exists.
#. Ruff/format/strict MyPy/Import Linter/coverage/``pip-audit`` pass.
#. Property/fault/migration/integration tests pass on explicit 3.11/3.12/3.13 lanes.
#. Contract/schema/compiler validation passes.
#. GitHub Actions is green for the exact implementation head.

52. Provisional freeze points after Phase 3 evidence
----------------------------------------------------

Before a later phase exposes this kernel through ChatGPT, re-check the reviewed Phase 3
evidence and freeze only the host-dependent projection items it supports:

* which status/result lifecycle interactions ChatGPT can use reliably;
* actual supported result-size/effective page limits;
* authenticated scope/profile mapping for the promoted operation class;
* whether host confirmation is required/observed for that risk class;
* whether MCP Tasks/Resources remain unavailable or can be optional adapters;
* catalogue refresh behavior for new operation Tools;
* retry/reconnect behavior that must be handled as host behavior rather than assumed.

If Phase 3 evidence is absent/expired/contradictory, internal Phase 4 implementation may
still pass its kernel tests, but no host-facing consequential projection is promoted.

53. Planning stop rule
----------------------

This plan is complete when a coding agent can build and test the durable operation kernel
without deciding any later operation-specific authority or host behavior: authoritative
SQLite state, exact lifecycle/idempotency semantics, minimal policy, append-only audit,
retained payload/evidence storage, reconciliation seams, local diagnostics, migrations,
and fault/property tests are all specified.

Stop here. Do not add the disposable write-probe workflow or any later operational
capability in this document.
