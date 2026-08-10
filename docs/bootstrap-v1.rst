Binnacle Bootstrap V1
=====================

:Status: Owner-approved bootstrap implementation baseline
:Depends on: ``design-principles.rst``
:Primary milestone: Cross the ChatGPT self-hosting threshold on one development Raspberry Pi
:Release status: Pre-1.0 development; not a production distribution target

Purpose
-------

Bootstrap V1 is intentionally small. It exists to make one development-only Raspberry
Pi useful enough that ChatGPT can continue developing Binnacle through Binnacle itself.

Bootstrap V1 is complete when ChatGPT can perform this loop without routine manual
intervention:

::

   connect
     -> inspect the Pi and the running Binnacle revision
     -> inspect and modify the Binnacle source workspace
     -> run and monitor development/tests
     -> inspect diagnostics and retained evidence
     -> perform the required Git workflow
     -> preflight and restart Binnacle
     -> reconnect to the same endpoint
     -> verify the expected revision and behaviour
     -> continue developing Binnacle

Anything not required for this loop is excluded unless an observed dependency proves it
is a blocker.

1. Reference platform
---------------------

Bootstrap V1 targets one real development platform first:

* one 64-bit Raspberry Pi;
* Raspberry Pi OS or another selected Debian-family system used by the development Pi;
* systemd;
* local storage for Binnacle state;
* a supported distribution-provided Python interpreter, minimum Python 3.11;
* one owner and one intended ChatGPT controller;
* source-checkout development installation;
* Streamable HTTP MCP endpoint reached through the selected private connectivity path.

Broader Pi models, distributions, architectures, and production device profiles are not
Bootstrap blockers.

2. Bootstrap installation
-------------------------

The bootstrap installation is source-based rather than package-based.

A fixed development checkout contains the source and isolated project environment,
conceptually:

::

   /srv/binnacle-dev/repo/
       .git/
       src/
       tests/
       docs/
       pyproject.toml
       uv.lock
       .venv/

Exact paths remain configuration, but the source checkout must be distinguishable from
Binnacle control-plane state.

Bootstrap flow:

#. Install only the OS prerequisites required to run/develop Binnacle.
#. Clone the Binnacle repository.
#. Use ``uv`` to create/synchronise the isolated development environment.
#. Run local validation before exposing the server remotely.
#. Perform an explicit privileged setup step for users, directories, systemd units,
   sockets, and protected state.
#. Start Binnacle under systemd directly from the checkout's project environment.
#. Validate the local MCP endpoint.
#. Configure the working private ChatGPT connectivity/authentication profile.
#. Connect real ChatGPT and begin empirical host validation.

The setup path should be idempotent and eventually support a dry-run view. It must not
install unrelated hardware, container, indexing, or production-release dependencies.

3. Runtime state layout
-----------------------

Source code and control-plane state are separate.

Conceptual ownership:

::

   development checkout
       -> source, tests, project-local environment, project build/cache state

   /etc/binnacle/
       -> protected configuration and local policy

   /var/lib/binnacle/
       -> SQLite state, retained operations/results, audit, checkpoints

   /run/binnacle/
       -> runtime sockets and ephemeral control-plane state

A Git clean/reset/switch operation in the source checkout must not destroy Binnacle
authentication, durable operations, audit, or protected configuration.

4. Core process topology
------------------------

Bootstrap V1 already establishes the three long-term process boundaries, even though
their first capability sets are small.

Main MCP/application process
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runs unprivileged as a dedicated control identity and owns:

* MCP/HTTP handling;
* controller-authentication integration;
* local bootstrap policy decisions;
* authoritative SQLite application state;
* durable Binnacle operation lifecycle;
* workspace/filesystem application services;
* Git application services;
* diagnostics;
* contract registry and capability projection.

It does not run arbitrary development programs in its own process and does not run as
root.

Execution supervisor
~~~~~~~~~~~~~~~~~~~~

Runs independently from the MCP process and is responsible for ChatGPT-started
processes. It provides:

* start/status/output/cancel lifecycle;
* operation-bound execution identities;
* process-tree supervision;
* durable/reconcilable execution references;
* bounded output capture;
* timeouts and basic resource control;
* survival across ordinary MCP/application restart where the execution contract allows
  it.

The bootstrap implementation may use systemd transient units or another systemd-backed
execution mechanism behind the executor boundary. Advanced sandboxing is not a
Bootstrap prerequisite.

Privileged broker
~~~~~~~~~~~~~~~~~

A small root broker exposes only the minimum structured privileged operations required
for self-development. It does not expose a generic root shell.

Initial privileged vocabulary is intentionally narrow, for example:

* inspect/install required OS packages;
* inspect/restart the Binnacle systemd service;
* perform the controlled Binnacle restart path;
* host reboot only if the bootstrap platform proves it is needed.

Broader Linux administration is deferred.

5. Internal IPC
---------------

Independent Binnacle processes communicate through restricted Unix-domain sockets.

Bootstrap internal protocols are:

* explicitly versioned;
* schema-defined;
* language-neutral;
* framed;
* JSON-based initially;
* authenticated partly through OS socket permissions and peer credentials;
* independently validated by the receiving component.

Python ``pickle`` or arbitrary Python-object deserialisation is prohibited across trust
or process boundaries.

The privileged broker and executor use separate narrow protocol surfaces even if they
share framing and protocol infrastructure.

6. Python and dependency baseline
---------------------------------

Primary implementation language
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Python is the primary/default language. Native C/C++ extensions from dependencies are
acceptable when justified and supportable on the reference platform.

Python compatibility target remains 3.11, 3.12, and 3.13. Bootstrap only has to run on
the actual reference Pi interpreter. Python 3.14 may be tested experimentally later but
is not part of the public support claim yet.

Project tooling
~~~~~~~~~~~~~~~

* ``uv`` is the standard Binnacle development/dependency/environment tool.
* ``setuptools`` / ``setuptools.build_meta`` is the Python build backend.
* Bootstrap development runs from the source checkout rather than an installed release
  artifact.
* Development/test/build dependencies stay in the project environment and are never
  bundled into a future runtime package merely because they are used during bootstrap.

7. MCP server baseline
----------------------

Framework
~~~~~~~~~

Bootstrap uses FastMCP 4.x as the high-level framework on the official MCP Python SDK
2.x line. Exact dependency versions are pinned through the development lock.

The target modern server revision remains MCP ``2026-07-28`` with the repository's
explicit compatibility revisions. Actual ChatGPT revision/feature behaviour is an
empirical profile and must not be guessed from SDK capability alone.

Transport
~~~~~~~~~

* Streamable HTTP is the first-priority transport.
* FastMCP's native ASGI application is served by Uvicorn.
* One Uvicorn worker is the compatibility default for Bootstrap.
* ``uvloop`` is preferred when available; standard asyncio remains a tested fallback.
* ``httptools`` is the preferred initial HTTP parser when available; parser performance
  is not a Bootstrap acceptance criterion.
* No parallel general-purpose REST API is implemented.
* Minimal ``/healthz`` and ``/readyz`` endpoints may exist without exposing sensitive
  diagnostics.

STDIO is deferred until after the first ChatGPT self-hosting loop.

8. Authentication and controller identity
-----------------------------------------

Bootstrap does not invent a proprietary login system.

Priority order:

#. use the standard authentication/authorisation mechanism defined by the negotiated MCP
   profile and actually supported by ChatGPT;
#. use host-supported connectivity/authentication mechanisms only where they are part of
   the validated ChatGPT profile;
#. expose safe diagnostics so ChatGPT can inspect the real handshake and help refine the
   implementation.

Authentication results are normalised into an internal ``ControllerIdentity``. Bootstrap
needs only one intended owner/controller profile.

Connectivity, authentication, and local authorisation are separate concerns. A secure
tunnel is not itself proof of controller identity.

9. Minimum MCP capability surface
---------------------------------

Tools and structured results are required to cross the self-hosting threshold. Resources,
Prompts, MCP Tasks, subscriptions, MRTR, and other modern features are probes/early
self-development targets rather than prerequisites.

The initial semantic capabilities are limited to the following groups.

Inspection and diagnostics
~~~~~~~~~~~~~~~~~~~~~~~~~~

Enough capability to obtain:

* device/OS/kernel/architecture/runtime facts;
* exact running Binnacle version/Git revision/branch/dirty state in development;
* service/startup/readiness state;
* sanitised MCP compatibility/authentication observations;
* bounded Binnacle and relevant journald diagnostics;
* capability availability and degradation information.

Workspace/filesystem
~~~~~~~~~~~~~~~~~~~~

Enough capability to:

* inspect the registered Binnacle source workspace;
* list/read/search files;
* create/write/patch/move/delete files;
* perform full normal software-development mutation inside an authorised Binnacle
  development session.

The MCP surface exposes semantic workspace/file operations rather than unrestricted
absolute-path authority.

Command/operation lifecycle
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enough capability to:

* start a development command using explicit executable/argv semantics by default;
* query durable operation state;
* retrieve bounded/incremental stdout and stderr;
* cancel an operation;
* list outstanding Binnacle-managed operations relevant to the controller.

The authoritative identity is the Binnacle ``operation_id``. MCP Tasks may later map to
it when supported by the real host.

Minimal Git
~~~~~~~~~~~

Enough semantic capability for:

* status and diff;
* branch/switch operations needed by the normal workflow;
* commit;
* fetch/pull;
* push.

The implementation uses the official Git CLI behind a typed adapter. Uncommon Git
operations may temporarily use the general development execution path until they justify
first-class semantic capabilities.

Self-management
~~~~~~~~~~~~~~~

Enough capability for:

* development-session state;
* restart preflight;
* Binnacle service restart through the controlled path;
* post-restart startup/revision verification.

10. Workspace and filesystem security
-------------------------------------

The Binnacle source workspace is deliberately permissive for authorised self-development,
but workspace authority is not whole-host authority.

Application-level path handling may use ``pathlib`` and normal Python path types. The
workspace security boundary is designed around descriptor-relative/race-resistant Linux
filesystem operations where practical, with conservative containment fallbacks until
stronger kernel-level hardening is implemented.

System/protected paths use explicit system or self-management operations rather than
being reached through a workspace escape.

11. Development process authority
---------------------------------

Bootstrap development processes run under a separate unprivileged execution identity.

They may have normal Internet and LAN access because ordinary development requires Git,
package downloads, APIs, and local network services.

They do not inherit:

* Binnacle inbound authentication material;
* SSH/GPG private-key material;
* credential-agent authority unless a dedicated outcome-oriented operation supplies it;
* privileged-broker access;
* Binnacle protected control-plane state.

Development servers should bind to loopback by default unless external/LAN exposure is
explicitly requested.

Advanced namespaces/seccomp/MAC/network sandboxing is a target-security workstream, not
a Bootstrap acceptance requirement.

12. Git credentials and signing
-------------------------------

Git repository access and commit signing are distinct capabilities.

Bootstrap may use:

* one device-specific SSH identity for the Binnacle repository, preferably repository-
  scoped where practical;
* one separate device-specific GPG/OpenPGP signing identity or signing subkey registered
  to the owner's GitHub account;
* controlled SSH/GPG agent use or another non-exportable mechanism.

General development commands do not receive raw keys. Dedicated Git operations use the
credential authority needed for the exact Git action.

Signed commits should be the normal Binnacle self-development commit path.

13. Git development workflow
----------------------------

Normal self-development follows a branch/PR workflow rather than direct development on
protected ``master``:

::

   master
     -> create feature/fix branch
     -> edit and test locally
     -> signed commit
     -> push branch
     -> GitHub Actions
     -> PR/review
     -> merge
     -> update development checkout
     -> restart/reconnect/real-host verification

GitHub-host operations such as PR creation/review/merge can initially use ChatGPT's
GitHub integration rather than being implemented inside Binnacle.

14. Development session
-----------------------

Development mode is a temporary auditable session, not a permanent boolean.

An explicit user request to develop or improve Binnacle constitutes authorisation to
begin the corresponding development session. ChatGPT may then perform the actual mode
transition and continue normal source/test/restart work without redundant confirmation
for the same authorised development objective.

The development session enables broader diagnostics and source-development capability,
but does not remove permanent credential, policy, control-plane, or privileged-operation
boundaries.

15. Long-running operations
---------------------------

ChatGPT and Binnacle share lifecycle responsibility.

ChatGPT should remember and actively inspect the long-running work it starts. Binnacle
independently retains authoritative state and acts as an assurance layer.

Once an ``operation_id`` is acknowledged:

* it must remain resolvable across normal Binnacle restart;
* the actual process must not be lifecycle-owned solely by the MCP server process;
* output/evidence is retained independently of one MCP response;
* Binnacle reconciles process state after restart;
* unknown or unverifiable outcomes are reported explicitly.

16. Restart guard
-----------------

Before restarting Binnacle, another development service, or the host, Binnacle performs
a preflight against active operations.

The preflight reports:

* active operation identities;
* purpose/command/workspace where safe;
* recent progress/output summary;
* predicted restart impact;
* recommended graceful completion/stop/teardown actions.

A surviving independently supervised operation does not automatically block restart.
The purpose of the guard is to ensure ChatGPT understands outstanding work before a
disruptive action.

17. Durable application state
-----------------------------

SQLite is the embedded authoritative database.

Application access uses:

* SQLAlchemy 2.x ORM;
* async ``AsyncEngine``/``AsyncSession`` patterns;
* ``aiosqlite`` for the initial SQLite async dialect;
* Alembic as the authoritative schema migration mechanism.

The main Binnacle application is the sole owner of the authoritative SQLite schema.
Executor and privileged-broker processes do not open the application database directly.
They retain only the minimum lifecycle evidence required for their responsibilities and
reconcile through IPC.

SQLite runtime profile
~~~~~~~~~~~~~~~~~~~~~~

Bootstrap uses:

* WAL journal mode;
* ``synchronous=FULL``;
* explicit foreign-key enforcement;
* bounded busy timeout;
* local filesystem storage.

Correctness/durability takes priority over premature commit-throughput optimisation.

18. Operation admission, idempotency, and reconciliation
--------------------------------------------------------

Durable intent precedes consequential effects.

Conceptual sequence:

#. normalise and validate the exact request;
#. establish controller/policy/contract context;
#. durably create/admit the Binnacle operation and idempotency binding;
#. commit authoritative state;
#. issue an operation-bound execution/broker request;
#. retain independent execution identity/evidence;
#. update/reconcile running and terminal state.

SQLite and Linux effects are not treated as one transaction.

Consequential operations define idempotency/retry behaviour. Repeating the exact same
logical request with the same identity reconciles to the existing operation instead of
creating a duplicate effect. Changed arguments cannot reuse the identity.

Where the actual outcome cannot be safely established, state becomes ``uncertain`` and
blind automatic repetition is prohibited.

19. Retained output and audit
-----------------------------

SQLite stores structured authoritative metadata. Large or streamable payloads live in
Binnacle-owned filesystem storage under the state directory.

Operation storage supports:

* incremental stdout/stderr writes;
* bounded retrieval;
* byte counts;
* content digests;
* truncation flags;
* retention metadata;
* storage quotas.

Audit is logically separate from ordinary logs and disposable output. Bootstrap uses a
structured append-only local audit journal with ordered records and SHA-256 integrity
chaining. SQLite may index audit facts but is not the sole authoritative audit
representation.

Reusable credentials and secret material are never written into logs, operation output
metadata, or audit records.

20. Logging and diagnostics
---------------------------

Structured application logging uses ``structlog`` integrated with Python logging.
System-managed deployments write structured output to stdout/stderr for journald.

Logging must not block the main asyncio event loop. A bounded queue/background output
path may drop low-priority diagnostic logs under pressure while incrementing a dropped-
log metric. Audit and authoritative operation state are not allowed to disappear because
the diagnostic queue is full.

Development diagnostic exposure is intentionally broad and may include Binnacle logs,
relevant journald units, startup state, tracebacks, operation lifecycle, MCP
compatibility/authentication facts, and lightweight metrics. Secret redaction and query
bounds remain mandatory.

21. Configuration and typed settings
------------------------------------

Use Pydantic v2 and ``pydantic-settings`` with TOML configuration.

Ordinary configuration precedence may follow the established CLI/environment/user/system
hierarchy, but security-critical policy/control-plane settings are protected and cannot
be overridden merely by a higher-precedence environment variable or CLI flag.

Resolved settings are treated as immutable snapshots. Bootstrap prefers controlled
restart over sophisticated hot reload for structural or security-sensitive changes.

22. Operation/capability contracts
----------------------------------

Use the hybrid model:

* YAML as the human/ChatGPT-editable declarative source;
* JSON Schema for language-neutral structural validation;
* Pydantic v2 for typed loading/semantic validation;
* typed Python implementations for behaviour;
* no embedded executable policy/programming language in YAML.

Validated contract sources are compiled into a versioned/content-addressed persistent
cache and then loaded into an immutable in-memory registry. Normal Tool invocation does
not repeatedly parse YAML.

Contract source remains authoritative; the cache is reproducible and disposable.

23. Bootstrap policy
--------------------

Bootstrap policy is intentionally minimal.

It must be sufficient to distinguish at least:

* one authenticated ChatGPT owner/controller;
* the Binnacle source workspace;
* ordinary development execution;
* protected Binnacle control-plane/credential/policy/audit areas;
* the minimal privileged operations needed for self-development;
* temporary development-session authority.

Do not build the long-term general policy engine before the self-hosting threshold.
Maintain a stable ``PolicyEngine`` boundary so a stronger policy technology can replace
the bootstrap evaluator later.

24. Application architecture
----------------------------

Use a lightweight ports-and-adapters architecture.

Dependency direction:

::

   MCP / CLI interfaces
          -> application/use cases
          -> domain/core semantics

   infrastructure/adapters
          -> implement typed ports required by application/domain

MCP and CLI remain thin adapters. Policy and domain types do not depend on FastMCP/HTTP.
Git, SQLite, filesystem, systemd, package-manager, executor, privileged-broker, and
future hardware implementations live behind typed boundaries.

Use ordinary constructor composition and Python ``Protocol``/ABC-style interfaces rather
than a dependency-injection framework. Enforce high-value import rules with Import
Linter.

25. CLI baseline
----------------

Use Typer + Rich.

The CLI is a thin local-operator adapter over the same application services. The design
supports three output intentions:

* human-oriented Rich output;
* compact deterministic ``agent`` output;
* stable machine-readable JSON output.

Bootstrap needs only the commands required for local setup, diagnostics, development,
and recovery. A large administration CLI is not required.

26. Testing and quality baseline
--------------------------------

Core testing stack:

* pytest;
* AnyIO pytest support for async tests;
* Hypothesis for lifecycle/idempotency/policy/state invariants;
* coverage.py with branch coverage;
* tox 4 + tox-uv for local Python matrix orchestration;
* GitHub Actions as the authoritative remote gate once the CI workflow lands on the
  target branch.

Quality/security stack is intentionally strong but remains development-only. The agreed
set includes Ruff, strict MyPy, Bandit, pip-audit, CodeQL, deptry, Import Linter,
Vulture (conservative confidence), check-jsonschema, yamllint, actionlint, codespell,
markdownlint, Mermaid validation, and Radon analysis as applicable.

Real evidence layers are distinct:

* ordinary CI;
* real Raspberry Pi system tests;
* real ChatGPT MCP-host tests.

Bootstrap requires only one development Pi, not a hardware test farm.

27. Startup and readiness
-------------------------

Expose distinct health/readiness/degraded concepts.

``healthy`` means the process is alive.

``ready`` means the Bootstrap self-hosting kernel is usable, including the required
configuration/contracts/policy/database/executor and the relevant restart reconciliation
state.

``degraded`` means the server is usable but one or more optional capabilities are
unavailable.

Startup diagnostics expose the exact running revision and subsystem validation results.
Optional future hardware/integration failures do not make the self-hosting kernel
unready.

28. Database migration and checkpointing
----------------------------------------

Alembic migrations are explicit. Migration failure prevents readiness rather than
silently recreating the database.

Before risky self-management changes such as database migration, policy/configuration
change, or service-layout change, Bootstrap may create a lightweight local control-plane
checkpoint:

* consistent SQLite backup/snapshot;
* relevant configuration/policy snapshot;
* runtime/build identity;
* service-definition metadata where required.

Git remains the source-code recovery mechanism. Raw reusable credential material is not
copied into ordinary checkpoints.

29. Self-development runtime identity
-------------------------------------

Every running development Binnacle reports enough provenance for ChatGPT to prove which
code is active:

* runtime profile: development;
* Binnacle/version metadata;
* exact Git commit;
* branch;
* dirty state;
* project environment/Python version;
* process start time;
* contract/policy registry digests where relevant.

After restart, ChatGPT compares expected and actual runtime identity before assuming the
new change loaded.

30. Bootstrap acceptance gate
-----------------------------

Bootstrap V1 is ready for the next phase only when real ChatGPT can demonstrate the
following on the real development Pi:

#. connect to Binnacle;
#. inspect host and Binnacle runtime identity;
#. read/search the Binnacle repository;
#. modify the repository;
#. install a missing development OS package if the current task genuinely requires it;
#. use the project-local development environment;
#. run quality/tests through the durable executor;
#. inspect running-operation status and output;
#. inspect Git diff;
#. create a signed commit;
#. push the branch;
#. request restart and receive active-operation preflight;
#. restart through the controlled path;
#. reconnect to the same server identity/endpoint;
#. verify the expected source revision is running;
#. inspect startup diagnostics;
#. verify the changed MCP behaviour against real ChatGPT.

At that point, stop expanding Bootstrap manually. Use Binnacle + ChatGPT to build the
remaining target architecture.

Known reconciliation items
--------------------------

The technology-stack grilling intentionally changed or narrowed several assumptions in
existing draft design documents. These should be reconciled during implementation rather
than hidden.

At minimum:

* the current strict ``command_run`` design describes no network authority and a fully
  proven kernel sandbox before support; Bootstrap now permits normal development
  Internet/LAN access and defers advanced sandbox hardening while preserving credential,
  broker, and control-plane separation;
* the current MCP interface correctly keeps Tools first for bootstrap, but Resources,
  Prompts, Tasks, and subscriptions are now explicit target capabilities rather than
  being conceptually excluded from the long-term interface;
* Bootstrap policy is intentionally small; the richer long-term policy-engine selection
  is deferred;
* production packaging/release requirements remain target architecture and are not part
  of the source-based self-hosting acceptance gate.

These differences require explicit follow-up changes to normative design/security
contracts before a stable release claim is made.
