Binnacle Bootstrap V1 Implementation Plan
=========================================

:Status: Draft implementation plan
:Primary objective: Reach the first reliable ChatGPT self-hosting loop on one development Raspberry Pi
:Depends on: ``design-principles.rst``, ``design.md``, ``bootstrap-v1.rst``
:Scope: Bootstrap V1 only

Purpose
-------

This document defines the implementation order for the first working version of
Binnacle.

Bootstrap V1 is not intended to implement the complete Binnacle design. Its purpose is
to create the smallest coherent system that allows real ChatGPT to connect to one
development Raspberry Pi and then continue developing Binnacle through Binnacle itself.

Bootstrap ends when ChatGPT can reliably:

::

   connect
     -> inspect the Pi and Binnacle
     -> inspect and modify the Binnacle repository
     -> run and monitor development work
     -> inspect diagnostics
     -> perform the required Git workflow
     -> restart Binnacle safely
     -> reconnect
     -> verify the expected revision and behaviour
     -> continue developing Binnacle

Capabilities that do not block this loop should normally be deferred.

1. Source-of-truth order
------------------------

Implementation decisions use the following precedence:

#. ``design-principles.rst``
#. ``design.md``
#. ``bootstrap-v1.rst``
#. Bootstrap-relevant detailed MCP, operation, security, and evidence contracts
#. ``deferred-decisions.rst``
#. ``target-architecture.rst``

``design-principles.rst`` governs when an older V17 contract conflicts with a later
owner-approved Bootstrap decision.

``design.md`` remains the root feature specification and vocabulary source, but it is
not a checklist requiring every described capability to exist in Bootstrap V1.

``target-architecture.rst`` supplies future architectural direction. Bootstrap should
create small stable seams where necessary without implementing the complete target
architecture.

2. Implementation rules
-----------------------

Every proposed Bootstrap feature should first answer:

**Does this feature block ChatGPT from developing Binnacle through Binnacle?**

If no, defer it unless the implementation requires a small stable seam now.

Additional rules are:

* use existing standards, Linux mechanisms, and mature open-source software before
  building custom infrastructure;
* keep ChatGPT as the sole reasoning and planning agent;
* keep the network-facing MCP application unprivileged;
* separate ordinary workspace development, development execution, credentials, and
  privileged host operations;
* introduce durable operation state before consequential effects, not before the first
  read-only compatibility server;
* test real ChatGPT behaviour early rather than designing the whole server around
  assumed host support;
* prefer a working, observable implementation over premature completeness;
* stop expanding Bootstrap once the self-hosting acceptance gate passes.

Bootstrap V1 technology baseline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The detailed phase plans in ``docs/implementation/`` use the following owner-approved
Bootstrap technology baseline unless real Raspberry Pi or ChatGPT evidence requires an
explicit revision:

* **language/runtime:** Python, with the reference Pi requiring Python 3.11 or newer;
  the compatibility target remains Python 3.11, 3.12, and 3.13;
* **dependency/environment tooling:** ``uv`` with exact resolved versions pinned in
  ``uv.lock``;
* **build backend:** ``setuptools`` / ``setuptools.build_meta``;
* **MCP framework:** FastMCP 4.x over the official MCP Python SDK 2.x line;
* **remote transport/server:** Streamable HTTP served by Uvicorn with one worker for
  Bootstrap compatibility;
* **async runtime:** asyncio/AnyIO; ``uvloop`` is preferred when available and the
  standard asyncio loop remains the fallback;
* **HTTP parser:** ``httptools`` is preferred when available, without making parser
  performance a Bootstrap gate;
* **typed models/configuration:** Pydantic v2 + ``pydantic-settings`` with TOML
  configuration and immutable resolved settings snapshots;
* **persistence:** SQLite owned by the main application process, SQLAlchemy 2 async,
  ``aiosqlite``, and Alembic migrations;
* **CLI:** Typer + Rich as a thin local adapter over the same application services;
* **logging:** ``structlog`` integrated with Python logging and journald under systemd;
* **service management:** systemd;
* **internal IPC:** restricted Unix-domain sockets using an explicitly versioned,
  schema-defined, language-neutral framed JSON protocol;
* **Git:** the official Git CLI behind a typed adapter;
* **repository search:** ``ripgrep`` or an equivalent mature native search mechanism
  behind a small adapter;
* **application architecture:** lightweight ports and adapters, explicit constructor
  composition, and typed ``Protocol``/ABC-style boundaries without a dependency-
  injection framework;
* **tests:** pytest, AnyIO pytest support, Hypothesis for state/lifecycle invariants,
  coverage.py, tox 4 + tox-uv, and GitHub Actions as the remote gate;
* **quality/security tooling:** Ruff, strict MyPy, Import Linter, and the agreed
  development-only security/schema/documentation checks from ``bootstrap-v1.rst``.

Dependencies are introduced by the first phase that genuinely implements their use.
Bootstrap does not add every future dependency to ``pyproject.toml`` on day one. Native
mechanisms such as Git, systemd/journald, distro package managers, OpenSSH/GPG, SQLite,
and ``ripgrep`` remain preferred over custom Python replacements unless a concrete
Binnacle-specific requirement justifies otherwise.

The roadmap remains the phase-order document. ``docs/implementation/index.rst`` indexes
the detailed phase engineering plans that specify concrete repository paths, modules,
classes, functions, interfaces, schemas, dependencies, scripts, configuration, tests,
and evidence requirements.

3. Phase 0 -- Reconcile Bootstrap-blocking contracts
----------------------------------------------------

Objective
~~~~~~~~~

Remove known contradictions between the current V17 contracts and the newer Bootstrap
principles before implementing the affected capabilities.

Required work
~~~~~~~~~~~~~

Reconcile at least:

* ``security/command-execution.md``;
* ``security/capability-composition.md``;
* ``spec/policy/command-profiles.yaml``;
* any related security fixtures.

The authorised development-command profile must permit ordinary Internet and LAN
application networking while continuing to deny:

* reusable Binnacle credentials;
* credential-agent authority unless provided by a dedicated operation;
* privileged-broker access;
* protected Binnacle control-plane IPC;
* inherited Binnacle sockets;
* raw/packet network administration;
* unrelated device authority.

Advanced namespace/seccomp/MAC sandbox requirements must not block Bootstrap
``command_run``. They remain later hardening work.

Also reconcile older text that defers all repository push and package operations.
Bootstrap requires:

* signed Git commit and branch push;
* the minimum package operation required to unblock development;
* service inspection/restart;
* controlled Binnacle restart.

Exit gate
~~~~~~~~~

The machine-readable contracts and prose used by Bootstrap no longer contradict the
owner-approved principles, and repository contract validation passes.

4. Phase 1 -- Create the executable project skeleton
----------------------------------------------------

Objective
~~~~~~~~~

Turn the repository from a design repository into a runnable Python project without
building operational capability yet.

Required work
~~~~~~~~~~~~~

Create:

::

   pyproject.toml
   uv.lock
   src/binnacle/
   tests/

Establish:

* Python 3.11+ project metadata;
* ``uv`` development environment;
* FastMCP 4.x over the official MCP Python SDK 2.x line;
* Uvicorn;
* Pydantic v2 / pydantic-settings;
* Typer + Rich for the local CLI;
* structlog;
* pytest + AnyIO;
* Ruff;
* strict MyPy;
* existing contract/schema validation in normal CI.

Establish the architectural seams for:

* MCP/application process;
* execution supervisor;
* privileged broker;
* persistence;
* policy;
* Git;
* filesystem/workspaces;
* credentials.

Only the MCP/application process needs to be runnable at this phase. Do not implement
empty frameworks for future capability merely to match the target architecture.

Exit gate
~~~~~~~~~

A clean checkout can run:

::

   uv sync
   uv run pytest
   uv run ruff check .
   uv run mypy ...

and import/start the Binnacle application skeleton.

5. Phase 2 -- Build the read-only MCP compatibility server
----------------------------------------------------------

Objective
~~~~~~~~~

Reach a locally working MCP server as quickly as possible.

Required work
~~~~~~~~~~~~~

Implement:

* FastMCP application;
* Streamable HTTP ``/mcp`` endpoint;
* Uvicorn with one worker;
* ``/healthz``;
* minimal ``/readyz``;
* build/runtime identity;
* device identity;
* configuration loading;
* contract/schema registry sufficient for the compatibility catalogue;
* canonical structured success and error envelopes.

Implement the ``compatibility-core`` Tools:

* ``binnacle_probe``;
* ``system_inspect``;
* ``probe_result_formats``;
* ``probe_error``;
* ``compatibility_report``.

Use the existing reviewed Tool manifest and schemas rather than inventing parallel
contracts.

Implement enough of the repository-declared MCP revision contract to accept the actual
ChatGPT connection. Prefer framework/SDK support over custom protocol machinery where
possible.

Do not implement yet:

* operational workspace mutation;
* command execution;
* Git mutation;
* privileged broker;
* MCP Tasks;
* Resources;
* Prompts;
* MRTR;
* hardware support.

Exit gate
~~~~~~~~~

A local MCP client can discover and call the compatibility-core Tools, results validate
against the declared schemas, and no consequential device effect is possible.

6. Phase 3 -- Deploy the compatibility server to the real Raspberry Pi
----------------------------------------------------------------------

Objective
~~~~~~~~~

Move from theoretical MCP compatibility to real ChatGPT evidence before implementing
the expensive parts of Binnacle.

Required work
~~~~~~~~~~~~~

Create the development installation on the selected 64-bit Raspberry Pi.

Use a source checkout such as:

::

   /srv/binnacle-dev/repo/

Keep protected state outside the repository:

::

   /etc/binnacle/
   /var/lib/binnacle/
   /run/binnacle/

Install the development environment with ``uv`` and run the MCP application under
systemd.

Configure the selected private connectivity path manually where necessary. Full tunnel
setup automation is not required.

Configure the minimum authenticated controller profile needed for the real ChatGPT
connection. Do not design the final production OAuth architecture yet.

Then connect real ChatGPT.

Run the first compatibility cases covering:

#. remote connection;
#. authentication;
#. actual MCP revision;
#. Tool discovery;
#. Tool invocation;
#. structured and text results;
#. execution-error presentation;
#. catalogue refresh behaviour relevant to later promotion.

Record what ChatGPT actually demonstrates in the compatibility profile.

Exit gate
~~~~~~~~~

Real ChatGPT can reliably call ``binnacle_probe`` and ``system_inspect`` on the
development Pi, and the actual negotiated/requested MCP behaviour is recorded.

This is the first major Bootstrap milestone.

7. Phase 4 -- Add the durable consequential-operation kernel
------------------------------------------------------------

Objective
~~~~~~~~~

Create the minimum reliable foundation required before allowing ChatGPT to mutate local
state.

Required work
~~~~~~~~~~~~~

Implement SQLite authoritative state using:

* SQLAlchemy 2.x async APIs;
* aiosqlite;
* Alembic;
* WAL;
* ``synchronous=FULL``;
* foreign-key enforcement.

Implement the minimum durable domain model for:

* controller identity;
* operation identity and state;
* state version;
* idempotency binding;
* request fingerprint;
* effect knowledge;
* timestamps and runtime provenance.

Implement the required operation states:

::

   received
   rejected
   authorised
   running
   paused
   cancelling
   cancelled
   succeeded
   failed
   uncertain

Implement durable idempotency before consequential effects.

Implement a minimal append-only integrity-linked audit journal. Do not implement external
audit anchoring.

Implement the small Bootstrap ``PolicyEngine`` boundary. Do not select or build the
long-term general-purpose policy engine.

Exit gate
~~~~~~~~~

Unit/property/integration tests prove that:

* a mutating logical request cannot accidentally create two effects;
* same-key/different-input reuse is rejected;
* uncertain effects cannot be blindly retried;
* state survives normal application restart;
* required audit failure prevents new consequential work.

8. Phase 5 -- Validate real ChatGPT write capability
----------------------------------------------------

Objective
~~~~~~~~~

Test mutation entitlement and host behaviour on a disposable target before granting
authority over the real Binnacle source workspace.

Required work
~~~~~~~~~~~~~

Implement:

* ``probe_workspace_prepare``;
* ``probe_workspace_write``;
* ``probe_workspace_cleanup``.

Use the dedicated disposable probe workspace only.

Validate with real ChatGPT:

* preparation;
* exact-input binding;
* host confirmation behaviour where applicable;
* write entitlement;
* idempotent retry;
* cleanup;
* reconnect behaviour.

Do not promote operational repository mutation until this evidence passes.

Exit gate
~~~~~~~~~

Real ChatGPT can create and remove one exact disposable probe artifact with exactly one
effect and no escape from the probe workspace.

9. Phase 6 -- Implement the Binnacle development workspace
----------------------------------------------------------

Objective
~~~~~~~~~

Allow ChatGPT to perform normal software-development file work on the Binnacle repository.

Required work
~~~~~~~~~~~~~

Before exposing the operational workspace or development-session Tools, define and
review their versioned operation contracts and input/output schemas, add them to the
reviewed Bootstrap Tool manifest, and pass schema/manifest validation. Runtime handlers
must not be exposed before this promotion step succeeds.

Implement registered-workspace operations for:

* inspect;
* list;
* read;
* bounded text/regex search;
* create;
* write;
* patch;
* move;
* delete.

Use a mature existing search mechanism such as ``ripgrep`` behind a small adapter rather
than building a repository index.

Implement path containment and symlink/race protections appropriate to Bootstrap.

Implement the temporary Binnacle development session:

* begin;
* inspect;
* expire/end.

Development-session authority grants broad normal developer access to the registered
Binnacle source workspace but does not grant:

* root filesystem access;
* Binnacle credential access;
* policy mutation;
* privileged-broker access;
* arbitrary system administration.

Exit gate
~~~~~~~~~

Real ChatGPT can inspect the Binnacle repository, make a controlled source edit, inspect
the resulting file, and revert or replace it without affecting unrelated paths.

10. Phase 7 -- Implement durable development-command execution
--------------------------------------------------------------

Objective
~~~~~~~~~

Let ChatGPT run Binnacle development and testing work without making the MCP process a
shell or process supervisor.

Required work
~~~~~~~~~~~~~

Before exposing command-start, operation-status/output/cancel, or outstanding-operation
Tools, define and review their contracts and schemas, add the exact entries to the
Bootstrap Tool manifest, and pass schema/manifest validation.

Implement the independent unprivileged execution supervisor.

Use a versioned Unix-domain-socket protocol between the application and executor.

Implement:

* explicit executable + argv execution;
* explicit working directory;
* allowlisted environment construction;
* stdin where needed;
* operation-bound execution identity;
* process-tree supervision;
* time limits;
* reasonable CPU/memory/process/output limits;
* stdout/stderr retention;
* status;
* bounded output retrieval;
* cancellation;
* outstanding-operation listing;
* restart reconciliation.

Development commands may use normal Internet/LAN application networking.

They must not receive:

* raw Git/GPG credentials;
* Binnacle authentication material;
* broker/control-plane sockets;
* protected configuration/audit/state;
* arbitrary privileged capabilities.

Do not implement:

* PTY;
* interactive terminal reattachment;
* advanced container sandboxing;
* full seccomp/MAC framework;
* Docker/Podman orchestration.

Exit gate
~~~~~~~~~

Real ChatGPT can run Binnacle tests and quality tools, inspect incremental output, cancel
a running command, and still inspect an acknowledged operation after an MCP application
restart.

11. Phase 8 -- Implement the minimal Git development workflow
-------------------------------------------------------------

Objective
~~~~~~~~~

Allow ChatGPT to complete the repository-side portion of normal Binnacle development.

Required work
~~~~~~~~~~~~~

Before exposing Git Tools, define and review the minimum Git operation contracts and
schemas, add their entries to the Bootstrap Tool manifest, and pass schema/manifest
validation.

Use the official Git CLI behind a typed adapter.

Implement semantic operations sufficient for:

* status;
* diff;
* branch creation;
* switch;
* commit;
* fetch;
* pull;
* push.

Configure:

* a dedicated device Git SSH identity;
* a separate commit-signing identity;
* non-exportable credential use.

General ``command_run`` must not receive the raw private keys.

GitHub-native workflow operations such as:

* PR creation;
* review;
* GitHub Actions inspection;
* merge;

remain outside Binnacle and may use ChatGPT's GitHub integration.

Exit gate
~~~~~~~~~

Through Binnacle, real ChatGPT can create a feature branch, modify/test Binnacle, create
a signed commit, and push the branch without receiving reusable credential material.

12. Phase 9 -- Implement the minimal privileged broker and self-management
---------------------------------------------------------------------------

Objective
~~~~~~~~~

Give ChatGPT only the privileged capabilities required to keep Binnacle self-development
moving.

Required work
~~~~~~~~~~~~~

Before exposing package, service, restart-preflight, or self-management Tools, define and
review their minimum operation contracts and schemas, add the exact entries to the
Bootstrap Tool manifest, and pass schema/manifest validation.

Implement a separate root broker using a restricted Unix-domain socket and a narrow,
versioned structured protocol.

The broker must not expose a generic root shell.

Bootstrap privileged vocabulary should be limited to:

* inspect required OS package state;
* install a specifically requested development OS package;
* inspect Binnacle service state;
* restart the Binnacle service;
* perform the controlled Binnacle restart path;
* reboot only if real Bootstrap evidence proves it necessary.

Implement restart preflight against active durable operations.

Implement lightweight control-plane checkpoints around risky changes where necessary.
Before a self-restart, retain outside the replaceable MCP/application process the exact
candidate revision, the last-known-good revision, relevant configuration/service
metadata, and enough evidence to drive deterministic recovery.

Implement a minimum failed-restart recovery path. If the candidate revision does not
reach the declared readiness state within the restart timeout, the controlled
self-management path should restore the last-known-good revision/checkpoint and restart
Binnacle. If rollback cannot be completed or verified, leave the service in a known
restricted/stopped state and preserve exact local recovery instructions and evidence;
never report the failed candidate as successful.

Implement runtime identity reporting including:

* exact Git revision;
* branch;
* dirty state;
* Python/environment identity;
* process start time;
* contract/policy digests where relevant.

Implement post-restart verification.

Exit gate
~~~~~~~~~

Real ChatGPT can:

#. inspect outstanding work;
#. request a Binnacle restart;
#. receive restart-impact information;
#. restart through the dedicated privileged path;
#. reconnect to the same endpoint;
#. verify the expected Git revision is running;
#. inspect startup diagnostics.

A failed-restart test also proves that a deliberately broken candidate either rolls
back to the last-known-good revision and becomes reachable again, or reaches a verified
restricted/local-recovery state with evidence retained outside the failed process.

13. Phase 10 -- Execute the first complete self-hosting loop
------------------------------------------------------------

Objective
~~~~~~~~~

Prove that Bootstrap has achieved its purpose.

Use a real, small Binnacle development change.

The complete workflow should be:

::

   ChatGPT connects to Binnacle
       -> inspects host and Binnacle revision
       -> creates a feature branch
       -> reads/searches source
       -> edits Binnacle
       -> runs tests/quality checks
       -> inspects operation output
       -> inspects Git diff
       -> creates a signed commit
       -> pushes the branch
       -> uses ChatGPT GitHub integration for PR/review/merge
       -> updates the development checkout
       -> requests restart preflight
       -> restarts Binnacle
       -> reconnects
       -> verifies the merged revision
       -> verifies the changed MCP behaviour

The test should also demonstrate at least one recoverable failure or cancellation so
durable operation state is exercised.

Exit gate
~~~~~~~~~

The complete loop succeeds on the real development Raspberry Pi using real ChatGPT
without routine manual intervention.

At this point Bootstrap V1 implementation stops.

14. Explicitly deferred until after self-hosting
------------------------------------------------

The following must not delay the first self-hosting loop unless real evidence proves one
is necessary:

* broad GPIO/I2C/SPI/UART/PWM/hardware support;
* official peripheral support;
* third-party hardware;
* production DEB/RPM/PyPI packaging;
* automated release publication;
* full MCP Resources/Prompts/Tasks/subscriptions/MRTR support;
* multi-controller authorisation;
* fleet management;
* plugin framework;
* full general-purpose policy engine;
* advanced seccomp/namespaces/Landlock/AppArmor/SELinux sandboxing;
* PTY and persistent interactive terminals;
* Docker/Podman development environments;
* semantic/code-intelligence indexing;
* GitHub API implementation inside Binnacle;
* alternative Git backend;
* alternative database;
* external observability stack;
* TPM-backed credential storage;
* strong external audit anchoring;
* autonomous release/update workflows;
* GUI or dashboard;
* general remote REST administration API.

These capabilities should be developed later through ChatGPT + Binnacle when a real need
or observed limitation justifies them.

15. Delivery discipline
-----------------------

Normal implementation work should follow:

::

   master
     -> feature branch
     -> implementation
     -> local validation
     -> commit
     -> push
     -> GitHub Actions
     -> PR/review
     -> merge

Do not attempt to implement all phases in one pull request.

Prefer small vertical milestones whose behaviour can be demonstrated before starting the
next phase.

The implementation plan itself may change before 1.0 when real ChatGPT or Raspberry Pi
evidence invalidates an assumption. Such changes should be explicit and should continue
to follow ``design-principles.rst``.

16. Definition of Bootstrap complete
------------------------------------

Bootstrap is complete when the acceptance loop in Phase 10 passes.

Passing that gate is more important than implementing every capability described in
``design.md``.

After the gate passes, future ChatGPT should preferentially use Binnacle itself to build
the remaining target architecture.
