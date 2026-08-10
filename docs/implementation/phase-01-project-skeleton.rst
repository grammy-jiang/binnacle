Binnacle Phase 1 Detailed Implementation Plan
=============================================

:Phase: 1 -- Create the executable project skeleton
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 0 contract-reconciliation plan
:Primary objective: Turn the design repository into a runnable, typed Python project without adding operational capability
:Implementation scope: Packaging, dependency/environment setup, application composition skeleton, configuration/logging bootstrap, CLI/MCP server startup skeleton, tests, and Python quality CI

Purpose
-------

Phase 1 creates the smallest executable Binnacle project foundation that later Bootstrap
capabilities can extend without re-deciding packaging, dependency direction, composition,
configuration, logging, or developer workflow.

The phase deliberately stops before operational capability. A Phase 1 checkout can be
synchronised with ``uv``, imported, tested, linted, type-checked, invoked through the
local CLI, and used to start an MCP/HTTP application skeleton. It does not expose
Binnacle filesystem, diagnostic, execution, Git, package, service, credential, hardware,
or self-management operations.

The ``:Status: merged`` value is the terminal status defined by
``docs/implementation/index.rst`` for the authoritative document after this plan PR
lands. While the PR is open, the document is proposed rather than authoritative.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. this detailed Phase 1 plan;
#. Bootstrap-relevant detailed contracts, schemas, manifests, policy, and fixtures;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

The governing constraints that matter most in this phase are:

* the reference implementation is Python and supports Python 3.11, 3.12, and 3.13;
* ``uv`` owns development dependency/environment synchronisation and ``uv.lock`` is the
  exact resolved dependency record;
* ``setuptools`` / ``setuptools.build_meta`` is the build backend;
* FastMCP 4.x over the official MCP Python SDK 2.x line is established now because the
  roadmap requires the MCP/application process itself to be runnable in Phase 1;
* Streamable HTTP through FastMCP's native ASGI application and Uvicorn is the first
  remote runtime path;
* Pydantic v2 / ``pydantic-settings``, Typer + Rich, and ``structlog`` are the selected
  configuration, CLI, and logging foundations;
* application structure uses lightweight ports-and-adapters, constructor composition,
  and explicit dependency direction rather than a dependency-injection framework;
* dependencies are introduced only when this phase actually imports or executes them;
* source-checkout development is the Bootstrap installation model; production
  distribution, PyPI/native packages, ``setuptools-scm``, and release publishing remain
  outside this phase.

2. Prerequisite and roadmap exit gate
-------------------------------------

Prerequisite
~~~~~~~~~~~~

Phase 0 must be merged so the Bootstrap contracts no longer encode the superseded
network/sandbox/self-hosting assumptions. Phase 1 starts from the exact updated
``master`` after that merge.

Roadmap exit gate
~~~~~~~~~~~~~~~~~

A clean checkout must be able to run, without hand-created Python files or undocumented
environment state:

.. code-block:: console

   uv sync
   uv run pytest
   uv run ruff check .
   uv run mypy src/binnacle tests

and must be able to import and start the Binnacle MCP/application skeleton.

The implementation additionally must pass the repository's existing contract/schema
validation and the new Python CI workflow on Python 3.11, 3.12, and 3.13.

3. Explicit non-goals
---------------------

Phase 1 does **not** implement:

* any Binnacle MCP Tool;
* Resources, Prompts, MCP Tasks, subscriptions, MRTR, or host capability probing;
* controller authentication or authorisation;
* device/OS/runtime inspection capabilities beyond local package/process skeleton facts;
* workspace registration, file listing, reading, searching, or mutation;
* command execution, process supervision, cgroups, execution IPC, or durable operations;
* SQLite, SQLAlchemy, Alembic, persistence schemas, migrations, or retained output;
* privileged-broker IPC or root operations;
* policy evaluation or machine-readable runtime policy loading;
* Git status/diff/commit/fetch/push or credential handling;
* SSH/GPG agents or credential brokers;
* systemd unit installation or service lifecycle management;
* package-manager operations;
* hardware support;
* production packaging, PyPI publishing, DEB/RPM generation, release automation, or
  ``setuptools-scm``;
* general REST control endpoints;
* STDIO MCP transport;
* multi-worker Uvicorn operation;
* advanced sandboxing, containers, or performance tuning.

If a proposed Phase 1 change needs an operational contract, persistent application state,
credential authority, privileged authority, workspace authority, or a first-class MCP
operation, it has crossed the phase boundary.

4. Before/after repository semantics
------------------------------------

Before Phase 1
~~~~~~~~~~~~~~

The repository is a reviewed design/contract repository. Python is used by validation
scripts, but there is no installable ``binnacle`` package, project lock, application
composition root, typed settings object, application CLI, or runnable MCP server
skeleton.

The existing ``.github/workflows/contracts.yml`` directly installs only the small
validation dependency set and executes the contract validators. Existing pre-commit
hooks primarily protect documentation, YAML/JSON, Mermaid, repository hygiene, and
secret scanning.

After Phase 1
~~~~~~~~~~~~~

The repository is also an executable Python project:

* ``uv sync`` creates/synchronises the project-local environment from ``pyproject.toml``
  and ``uv.lock``;
* ``import binnacle`` succeeds in the synced environment;
* ``python -m binnacle`` and the ``binnacle`` console script invoke the same Typer CLI;
* ``binnacle version`` reports the package-development version without requiring any
  operational subsystem;
* ``binnacle config validate`` performs pure local settings validation;
* ``binnacle serve`` composes the application skeleton and starts the FastMCP/Uvicorn
  HTTP process with no Binnacle operational Tools registered;
* configuration is parsed into an immutable typed snapshot;
* structured logging is configured before application construction;
* package-layer import rules are machine-checked;
* Python 3.11/3.12/3.13 tests and the quality gate run in GitHub Actions;
* the existing contract/schema validators remain part of normal CI.

No new authority is created merely because the server process can start.

5. Exact implementation file set
--------------------------------

The Phase 1 **implementation** PR is expected to create or modify the following paths.
This detailed-plan PR itself adds only this document.

5.1 Root project files
~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   pyproject.toml
   uv.lock

Do not create a ``setup.py``, ``setup.cfg``, ``requirements.txt``, ``Pipfile``, Poetry
configuration, or another competing dependency source.

Do not create a repository-wide ``.python-version`` in Phase 1. The supported range is
3.11--3.13 and the actual reference Pi may use any compatible distribution-provided
interpreter. CI selects each matrix interpreter explicitly.

5.2 Application package
~~~~~~~~~~~~~~~~~~~~~~~

Create exactly this initial package tree unless a framework API requires one narrowly
justified helper module:

::

   src/
     binnacle/
       __init__.py
       __main__.py
       application.py
       cli.py
       composition.py
       config.py
       logging.py
       adapters/
         __init__.py
         mcp.py
       domain/
         __init__.py
         runtime.py

Do **not** create empty ``executor/``, ``broker/``, ``persistence/``, ``git/``,
``workspace/``, ``credentials/``, ``hardware/``, or generic ``services/`` packages merely
to resemble the target architecture. Their canonical ownership boundaries are reserved
in this plan, but concrete modules/interfaces appear only when a real caller exists.

5.3 Tests
~~~~~~~~~

Create:

::

   tests/
     conftest.py
     unit/
       test_application.py
       test_cli.py
       test_config.py
       test_logging.py
       test_runtime.py
     integration/
       test_mcp_skeleton.py

Keep tests that require a real Raspberry Pi, real ChatGPT, systemd, Git credentials,
root, or external network access out of Phase 1.

5.4 CI
~~~~~~

Create:

::

   .github/workflows/python.yml

Retain ``.github/workflows/contracts.yml`` as the focused low-cost contract gate. The
new Python workflow also invokes the existing contract/schema validators so a normal
Python-project CI run cannot accidentally ignore them.

5.5 Existing files intentionally unchanged
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normally leave these unchanged in Phase 1:

* ``.gitignore`` -- it already excludes ``.venv``, Python caches, coverage output, tox,
  MyPy, Ruff, build output, and common editor state;
* ``.pre-commit-config.yaml`` -- the existing repository-hygiene/documentation hooks
  remain valid; Python correctness is initially enforced by canonical ``uv`` commands
  and CI rather than duplicating the whole Python toolchain inside pre-commit;
* Phase 0 policy/specification files -- Phase 1 adds no machine-readable authority;
* Bootstrap design documents -- change them only if implementation discovers a genuine
  contradiction, not for wording uniformity.

6. ``pyproject.toml`` design
----------------------------

6.1 Build system
~~~~~~~~~~~~~~~~

Use PEP 517 with setuptools:

.. code-block:: toml

   [build-system]
   requires = ["setuptools"]
   build-backend = "setuptools.build_meta"

Setuptools package discovery is ``src``-layout only:

.. code-block:: toml

   [tool.setuptools]
   package-dir = {"" = "src"}

   [tool.setuptools.packages.find]
   where = ["src"]

Do not enable namespace-package discovery for speculative future extensions in Phase 1.

6.2 Project metadata
~~~~~~~~~~~~~~~~~~~~

The Phase 1 implementation should use the following semantic metadata:

.. code-block:: toml

   [project]
   name = "binnacle"
   version = "0.1.0.dev0"
   description = "Deterministic MCP execution and observation boundary for a Raspberry Pi/Linux device"
   requires-python = ">=3.11,<3.14"

``0.1.0.dev0`` is deliberately a pre-release/bootstrap version, not the beginning of the
future release-version mechanism. Do not add ``setuptools-scm`` or tag-derived versioning
in this phase.

Do not invent licence metadata, public project URLs, classifiers, release maturity, or
PyPI claims that are not already owner-approved.

6.3 Console entry point
~~~~~~~~~~~~~~~~~~~~~~~

Define one application console script:

.. code-block:: toml

   [project.scripts]
   binnacle = "binnacle.cli:main"

``python -m binnacle`` delegates to the same ``main()`` function through
``src/binnacle/__main__.py``. There must not be separate CLI and module-entry behaviour.

7. Runtime dependencies and dependency groups
---------------------------------------------

7.1 Runtime dependencies introduced now
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The runtime dependency set is limited to packages imported by the Phase 1 skeleton or
required to hold the owner-approved framework line:

* ``fastmcp>=4,<5``;
* ``mcp>=2,<3`` to keep the official SDK on the reviewed compatibility line even when
  FastMCP could resolve a broader transitive range;
* ``uvicorn``;
* ``pydantic>=2,<3``;
* ``pydantic-settings>=2,<3``;
* ``typer``;
* ``rich``;
* ``structlog``.

For dependencies whose governing documents freeze only the technology rather than a
specific major/minor line, the implementation must resolve the current stable release
that supports Python 3.11--3.13, record a sensible upper compatibility boundary in
``pyproject.toml``, and pin the exact transitive graph in ``uv.lock``. Do not put every
exact transitive pin into ``pyproject.toml``.

``uvloop`` and ``httptools`` are not hard runtime dependencies in Phase 1. If the
reference platform can install them cleanly they may be represented as a named optional
``performance`` extra, but the roadmap exit gate must pass on the standard asyncio/Uvicorn
fallback without that extra. Performance extras are not a Phase 1 acceptance condition.

7.2 Dependency groups
~~~~~~~~~~~~~~~~~~~~~

Use PEP 735/``uv`` dependency groups with these responsibilities:

``test``
   ``pytest``, ``anyio`` for the pytest AnyIO plugin, and ``coverage``. Hypothesis is not
   added until a phase contains actual state/lifecycle invariants worth generating.

``quality``
   ``ruff``, ``mypy``, and ``import-linter``.

``matrix``
   ``tox`` and ``tox-uv`` for developer-run Python compatibility orchestration.

``contracts``
   ``PyYAML`` and ``jsonschema`` because the existing contract validators import them.

``dev``
   Includes the ``test``, ``quality``, ``matrix``, and ``contracts`` groups using the
   supported ``uv`` group-inclusion syntax instead of duplicating package names.

The default developer sync should include ``dev`` so the documented exit-gate commands
work after plain ``uv sync``.

Do not add SQLAlchemy, ``aiosqlite``, Alembic, Git libraries, systemd/D-Bus libraries,
hardware packages, policy engines, security sandbox packages, or release/publishing
packages in Phase 1.

7.3 Lock policy
~~~~~~~~~~~~~~~

``uv.lock`` is committed and authoritative for exact development resolution.

The implementation sequence is:

#. author ``pyproject.toml``;
#. run ``uv lock`` on a supported developer machine;
#. run ``uv sync --frozen`` from the generated lock;
#. verify Python 3.11, 3.12, and 3.13 through CI/tox using the same lock policy;
#. commit ``pyproject.toml`` and ``uv.lock`` together.

CI uses ``--frozen`` so it fails rather than silently rewriting the lock.

8. Module ownership and dependency direction
--------------------------------------------

8.1 ``binnacle.domain``
~~~~~~~~~~~~~~~~~~~~~~~

Owns framework-independent core values introduced in this phase.

``domain/runtime.py`` owns:

.. code-block:: python

   from dataclasses import dataclass
   from enum import StrEnum

   class RuntimeProfile(StrEnum):
       DEVELOPMENT = "development"

   @dataclass(frozen=True, slots=True)
   class PackageIdentity:
       distribution_name: str
       version: str

No FastMCP, Uvicorn, Typer, Rich, Pydantic, or structlog types may appear in this module.

8.2 ``binnacle.application``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns the minimal framework-independent application lifecycle object:

.. code-block:: python

   class BinnacleApplication:
       def __init__(self, *, identity: PackageIdentity) -> None: ...

       @property
       def identity(self) -> PackageIdentity: ...

       async def start(self) -> None: ...
       async def stop(self) -> None: ...

Phase 1 ``start()`` and ``stop()`` perform only lifecycle bookkeeping needed to prove
composition. They do not initialise a database, policy registry, executor, broker,
workspace, Git backend, or credential service.

Lifecycle methods must be idempotent within one process instance: repeated ``start()``
or ``stop()`` must not create duplicate framework state or raise merely because the
requested lifecycle state is already true.

8.3 ``binnacle.config``
~~~~~~~~~~~~~~~~~~~~~~~

Owns settings models and the pure settings-loading boundary. Pydantic types stay here and
must not leak into ``binnacle.domain``.

8.4 ``binnacle.logging``
~~~~~~~~~~~~~~~~~~~~~~~~

Owns structlog/Python-logging bootstrap and shutdown of any logging background resource.
Application/domain code emits through normal logger acquisition but does not configure
handlers itself.

8.5 ``binnacle.adapters.mcp``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns FastMCP/Uvicorn adaptation. Vendor-specific types do not leak into application or
domain modules.

8.6 ``binnacle.cli``
~~~~~~~~~~~~~~~~~~~~

Owns Typer/Rich command-line adaptation and output formatting. CLI commands call the same
composition/application functions used by the MCP process; they do not duplicate domain
logic.

8.7 ``binnacle.composition``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Is the composition root. It is the only ordinary package module allowed to know about
settings construction, logging setup, the application object, and the MCP adapter at the
same time.

No domain/application module imports ``binnacle.composition``.

9. Protocol/ABC seam policy
---------------------------

The roadmap requires architectural seams for the future execution supervisor, privileged
broker, persistence, policy, Git, workspace/filesystem, and credentials domains. Phase 1
establishes those seams by **canonical ownership and dependency direction**, not by
creating speculative empty Protocols.

Introduce now
~~~~~~~~~~~~~

No method-bearing Protocol is needed for a future operational subsystem in Phase 1
because there is no Phase 1 caller. The framework-independent
``BinnacleApplication`` lifecycle and the MCP adapter boundary are concrete, used seams.

The following ownership paths are reserved conceptually and must be used when a real
caller first appears:

* executor client/port -> ``binnacle.ports.executor``;
* privileged-broker client/port -> ``binnacle.ports.privileged``;
* persistence port -> ``binnacle.ports.persistence``;
* ``PolicyEngine`` -> ``binnacle.ports.policy``;
* Git backend -> ``binnacle.ports.git``;
* workspace/filesystem port -> ``binnacle.ports.workspace``;
* credential reference/broker port -> ``binnacle.ports.credentials``.

Deferred intentionally
~~~~~~~~~~~~~~~~~~~~~~

Do not create those modules in Phase 1 and do not guess methods such as ``execute()``,
``evaluate()``, ``commit()``, or ``read_file()`` before the first use-case contract needs
them. The phase that first consumes a port introduces its exact Protocol and owned domain
types, and later phases extend rather than redefine it.

This satisfies the owner principle "build the seam now; defer the implementation" while
also obeying the implementation-index rule against empty architecture for its own sake.
The seam is the frozen dependency/ownership boundary; the callable interface is frozen
only when evidence from a real use case exists.

10. Application identity and package version
--------------------------------------------

``src/binnacle/__init__.py`` exposes only stable package-level metadata:

.. code-block:: python

   from importlib.metadata import PackageNotFoundError, version

   def distribution_version() -> str:
       ...

The normal synced/editable environment should resolve ``version("binnacle")``. A
``PackageNotFoundError`` fallback may return ``"0.1.0.dev0"`` solely so direct
source-tree imports fail gracefully outside an installed/synced environment; it must not
fabricate a Git revision.

Exact Git commit/branch/dirty-state runtime identity is not implemented in Phase 1.

11. Typed configuration bootstrap
---------------------------------

11.1 Models
~~~~~~~~~~~

Define immutable Pydantic settings with a narrow Phase 1 surface:

.. code-block:: python

   from pathlib import Path
   from typing import Literal, Mapping

   from pydantic import BaseModel, ConfigDict, Field
   from pydantic_settings import BaseSettings, SettingsConfigDict

   class ServerSettings(BaseModel):
       model_config = ConfigDict(frozen=True, extra="forbid")
       host: str = "127.0.0.1"
       port: int = Field(default=8000, ge=1, le=65535)
       workers: Literal[1] = 1

   class LoggingSettings(BaseModel):
       model_config = ConfigDict(frozen=True, extra="forbid")
       level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
       format: Literal["console", "json"] = "console"

   class BinnacleSettings(BaseSettings):
       model_config = SettingsConfigDict(
           frozen=True,
           extra="forbid",
           env_prefix="BINNACLE_",
           env_nested_delimiter="__",
       )
       runtime_profile: Literal["development"] = "development"
       server: ServerSettings = ServerSettings()
       logging: LoggingSettings = LoggingSettings()

Phase 1 deliberately contains no credential, protected-state, policy, broker, executor,
or database settings.

11.2 TOML loading and precedence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Expose:

.. code-block:: python

   def load_settings(
       *,
       config_path: Path | None = None,
       cli_overrides: Mapping[str, object] | None = None,
   ) -> BinnacleSettings:
       ...

Use the standard-library ``tomllib`` for file parsing. Pydantic/
``pydantic-settings`` performs typed validation and environment integration.

Phase 1 precedence for its **ordinary, non-security-critical** fields is:

::

   defaults < TOML file < BINNACLE_* environment < explicit CLI override

Unknown TOML keys are errors. Invalid environment values are errors. The resolved object
is frozen.

Do not generalise this precedence into a future security-policy rule. Security-critical
settings are not introduced in Phase 1 and later protected settings may deliberately
have stricter non-overridable sources.

11.3 Configuration path
~~~~~~~~~~~~~~~~~~~~~~~

``binnacle serve`` and ``binnacle config validate`` accept an explicit ``--config PATH``.
No Phase 1 command silently creates or mutates ``/etc/binnacle``.

When ``--config`` is absent, Phase 1 may start from defaults/environment only. The future
system installation path can supply an explicit protected file when that capability is
implemented.

12. Structured logging bootstrap
--------------------------------

Expose:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass(slots=True)
   class LoggingRuntime:
       def close(self) -> None: ...

   def configure_logging(settings: LoggingSettings) -> LoggingRuntime:
       ...

Requirements:

* configure Python logging and structlog once per process;
* write application diagnostics to stdout/stderr, suitable for future journald capture;
* support human-readable development console output and deterministic JSON output;
* include timestamp, level, logger, event, and exception information;
* avoid global secret-bearing context fields;
* make repeated configuration in tests deterministic and cleanly replace/close the prior
  Phase 1 logging runtime;
* ensure ``LoggingRuntime.close()`` is idempotent.

A bounded ``QueueHandler``/``QueueListener`` path from the standard logging library is
preferred so logging output work is not performed directly in the application event
loop. If the implementation uses it, queue/listener ownership belongs entirely to
``binnacle.logging`` and tests must stop the listener.

Audit logging is explicitly absent in Phase 1; ordinary logs must never be described as
authoritative audit evidence.

13. Composition root
--------------------

Expose the following construction API from ``binnacle.composition``:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass(slots=True)
   class ComposedApplication:
       settings: BinnacleSettings
       application: BinnacleApplication
       logging_runtime: LoggingRuntime

       async def close(self) -> None: ...

   def compose_application(*, settings: BinnacleSettings) -> ComposedApplication:
       ...

Composition order is deterministic:

#. receive an already validated immutable ``BinnacleSettings`` snapshot;
#. configure logging;
#. resolve ``PackageIdentity``;
#. construct ``BinnacleApplication``;
#. return the composed container;
#. build the MCP adapter only when a caller requests the HTTP/MCP surface.

``ComposedApplication.close()`` stops the application if needed and closes logging
resources. It is idempotent.

Do not use a service locator, global dependency registry, framework DI container, or
runtime reflection-based injection.

14. MCP/HTTP skeleton
---------------------

14.1 Adapter API
~~~~~~~~~~~~~~~~

``binnacle.adapters.mcp`` owns vendor integration and exposes a narrow API equivalent to:

.. code-block:: python

   from collections.abc import Awaitable, Callable
   from typing import Any, TypeAlias

   from fastmcp import FastMCP

   ASGIReceive: TypeAlias = Callable[[], Awaitable[dict[str, Any]]]
   ASGISend: TypeAlias = Callable[[dict[str, Any]], Awaitable[None]]
   ASGIApp: TypeAlias = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]

   def create_mcp_server(application: BinnacleApplication) -> FastMCP:
       ...

   def create_http_app(application: BinnacleApplication) -> ASGIApp:
       ...

   def run_http_server(
       *,
       application: BinnacleApplication,
       settings: ServerSettings,
   ) -> None:
       ...

The adapter may refine the local ASGI aliases to the selected framework's public typed
ASGI protocol if that avoids ``Any`` without adding a dependency solely for type aliases.
Vendor-specific types remain inside the adapter.

14.2 Server identity
~~~~~~~~~~~~~~~~~~~~

The FastMCP server name is ``"Binnacle"``. Description/version metadata may include the
Phase 1 package identity where supported without exposing Git/workspace state.

14.3 Zero operational capability
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Phase 1 FastMCP instance registers **zero Binnacle operational Tools**. It also does
not register Binnacle Resources, Prompts, Tasks, or experimental operational handlers.

Framework-required protocol metadata/handshake behavior is permitted because it is part
of running a valid MCP server, not a Binnacle operation.

Do not add placeholder Tools that return ``not implemented``. Placeholder Tools would
create an advertised contract without an implementation and would incorrectly consume
later capability scope.

14.4 Uvicorn behavior
~~~~~~~~~~~~~~~~~~~~~

``run_http_server`` uses:

* one worker exactly;
* the configured host/port;
* FastMCP's native ASGI application;
* ordinary asyncio-compatible startup/shutdown;
* no FastAPI wrapper;
* no reload mode in the canonical application command;
* no daemonisation or PID file.

Default bind is ``127.0.0.1``. Any non-loopback bind must be an explicit configuration or
CLI choice; it is never inferred from development mode.

15. CLI design
--------------

15.1 Entry functions
~~~~~~~~~~~~~~~~~~~~

``binnacle.cli`` owns:

.. code-block:: python

   import typer

   app = typer.Typer(...)

   def main() -> None:
       app()

The module may use small internal renderer helpers, but application behavior remains in
application/composition/config modules.

15.2 Commands
~~~~~~~~~~~~~

Phase 1 exposes only:

``binnacle version``
   Report ``PackageIdentity``. Must not inspect Git, the host, systemd, credentials, or
   the network.

``binnacle config validate [--config PATH]``
   Load settings and report success or deterministic validation errors. It performs no
   file mutation.

``binnacle serve [--config PATH] [--host HOST] [--port PORT]``
   Load settings, apply explicit ordinary CLI overrides, configure logging, compose the
   application, and start the MCP/HTTP skeleton. ``--host`` is explicit bind intent;
   default behavior remains loopback.

No generic ``run``, ``exec``, ``admin``, ``git``, ``file``, ``package``, ``service``, or
``shell`` command exists in Phase 1.

15.3 Output intentions
~~~~~~~~~~~~~~~~~~~~~~

Provide one output-mode enum owned by the CLI adapter:

.. code-block:: python

   class OutputMode(StrEnum):
       HUMAN = "human"
       AGENT = "agent"
       JSON = "json"

``version`` and ``config validate`` support all three modes:

* ``human`` uses Rich presentation;
* ``agent`` is compact deterministic plain text with no terminal decoration;
* ``json`` emits one stable JSON object to stdout.

Errors go to stderr and use non-zero exit status. JSON mode must not mix Rich markup or
logging records into stdout.

16. Import and dependency rules
-------------------------------

Phase 1 configures Import Linter with high-value architectural contracts equivalent to:

#. ``binnacle.domain`` is independent and may import only the Python standard library;
#. ``binnacle.application`` may import ``binnacle.domain`` but not ``binnacle.adapters``,
   ``binnacle.cli``, FastMCP, Uvicorn, Typer, Rich, Pydantic, or structlog;
#. ``binnacle.adapters`` may import application/domain and its required vendor libraries;
#. ``binnacle.cli`` may import composition/config/domain plus CLI libraries, but it must
   not become a dependency of application/domain/adapters;
#. ``binnacle.composition`` may depend inward and on adapters/config/logging, but no
   inward layer imports ``binnacle.composition``;
#. ``binnacle.config`` and ``binnacle.logging`` remain cross-cutting outer modules and are
   not imported by ``binnacle.domain``.

Do not create exceptions for tests by weakening production import contracts. Tests may
import any public/internal module needed to verify behavior.

17. Ruff configuration
----------------------

Configure Ruff in ``pyproject.toml`` with:

* target version ``py311`` so syntax remains compatible with the oldest supported
  interpreter;
* line length 100;
* source roots ``src`` and ``tests``;
* lint families at minimum ``E``, ``F``, ``I``, ``UP``, ``B``, ``SIM``, and ``RUF``;
* formatter enabled with the same line length;
* no blanket ``noqa`` policy.

Per-file ignores are allowed only for a documented test-specific reason. Do not globally
suppress unused imports or typing failures to make the skeleton green.

Canonical commands:

.. code-block:: console

   uv run ruff check .
   uv run ruff format --check .

18. Strict MyPy configuration
-----------------------------

Configure MyPy in ``pyproject.toml`` with Python 3.11 syntax target and strict checking.
At minimum enable the semantics represented by ``strict = true`` and require typed
function definitions throughout ``src/binnacle``.

Canonical command:

.. code-block:: console

   uv run mypy src/binnacle tests

Do not solve missing third-party typing by scattering ``# type: ignore``. Prefer public
typed framework APIs; if a targeted ignore is unavoidable it must include an error code
and a short reason.

19. Pytest, coverage, and tox
-----------------------------

19.1 Pytest
~~~~~~~~~~~

Configure pytest in ``pyproject.toml``:

* test root ``tests``;
* strict marker/config handling;
* AnyIO plugin available;
* warnings treated as errors except narrowly documented third-party warnings;
* no network, root, systemd, or external service requirement.

19.2 Coverage
~~~~~~~~~~~~~

Measure branch coverage for ``src/binnacle``. Phase 1 should achieve full meaningful
coverage of its small package, but do not add assertion-free tests merely to chase a
number.

The CI gate should fail below 90% branch-inclusive coverage in Phase 1. Later phases may
change the threshold only through an explicit reviewed decision if generated/adaptor
code makes the number misleading.

19.3 Tox
~~~~~~~~

Configure tox 4 + tox-uv for environments:

::

   py311
   py312
   py313
   quality

The Python environments run pytest. ``quality`` runs Ruff, MyPy, Import Linter, and the
contract/schema validators.

Tox orchestrates an already-defined project environment; it does not replace ``uv`` as
the dependency/lock source.

20. Required test cases
-----------------------

20.1 Package/runtime tests
~~~~~~~~~~~~~~~~~~~~~~~~~~

``test_distribution_version_is_available``
   Synced package metadata resolves a non-empty version string.

``test_package_identity_is_frozen``
   ``PackageIdentity`` cannot be mutated after creation.

``test_application_start_is_idempotent``
   Two starts leave one started application state and no duplicate side effect.

``test_application_stop_is_idempotent``
   Repeated stop is safe.

20.2 Configuration tests
~~~~~~~~~~~~~~~~~~~~~~~~

``test_default_settings_are_development_loopback``
   Defaults are development profile, host ``127.0.0.1``, one worker.

``test_toml_overrides_defaults``
   A temporary TOML file changes ordinary server/logging settings.

``test_environment_overrides_toml``
   A ``BINNACLE_*`` value wins over the TOML value for Phase 1 ordinary settings.

``test_nested_environment_mapping``
   ``BINNACLE_LOGGING__LEVEL`` and ``BINNACLE_LOGGING__FORMAT`` populate the nested
   ``LoggingSettings`` model through ``env_nested_delimiter="__"``.

``test_cli_override_wins_for_ordinary_server_field``
   Explicit host/port CLI input wins over environment/TOML.

``test_unknown_toml_key_is_rejected``
   Extra keys fail closed.

``test_invalid_port_is_rejected``
   Values outside 1--65535 fail validation.

``test_settings_snapshot_is_immutable``
   Resolved settings cannot be mutated.

20.3 Logging tests
~~~~~~~~~~~~~~~~~~

``test_json_logging_emits_parseable_record``
   JSON mode emits one parseable structured record containing required fields.

``test_reconfigure_logging_closes_previous_runtime``
   Repeated test configuration does not leak queue-listener threads/handlers.

``test_logging_runtime_close_is_idempotent``
   Cleanup may be called repeatedly.

20.4 CLI tests
~~~~~~~~~~~~~~

``test_version_human``
   Human output succeeds.

``test_version_agent_is_plain_deterministic_text``
   Agent mode contains no ANSI/Rich decoration.

``test_version_json_is_single_json_document``
   JSON mode writes only machine-readable JSON to stdout.

``test_config_validate_invalid_file_exits_nonzero``
   Validation errors are deterministic and non-zero.

``test_serve_defaults_to_loopback_one_worker``
   Monkeypatch the Uvicorn runner and verify the resolved bind/worker settings without
   opening a real listening socket.

20.5 MCP skeleton integration tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``test_create_mcp_server_returns_framework_server``
   Construction succeeds from a composed application.

``test_http_app_can_be_constructed``
   FastMCP's native ASGI application is constructible without database/executor/broker
   dependencies.

``test_phase1_registers_no_binnacle_operational_tools``
   Inspect the supported FastMCP registration surface and prove that Phase 1 itself has
   registered no Binnacle operational Tool.

The integration test must avoid depending on undocumented FastMCP internals. If the
framework lacks a stable registration-inspection API, test the Binnacle registration
function directly and assert it performs no registration rather than introspecting
private attributes.

21. Python CI workflow
----------------------

Create ``.github/workflows/python.yml`` with least-privilege ``contents: read`` and
pinned action SHAs, matching the repository's existing supply-chain style.

Required jobs:

``test``
   Matrix Python 3.11, 3.12, and 3.13 on Ubuntu. Install ``uv`` through the reviewed
   pinned setup action. For each job, explicitly select the matrix interpreter rather
   than relying on project/environment discovery:

   .. code-block:: console

      uv sync --frozen --python "${{ matrix.python-version }}"
      uv run --python "${{ matrix.python-version }}" pytest

   The explicit interpreter selection is mandatory so a local/default interpreter can
   never make the 3.12/3.13 jobs false positives.

``quality``
   Python 3.13 lane. Run ``uv sync --frozen --python 3.13``, Ruff check/format check,
   strict MyPy, Import Linter, ``uv run python scripts/validate_contracts.py``, and
   ``uv run python scripts/validate_schema_instances.py``.

The focused existing ``Contract validation`` workflow remains enabled. The new workflow
is additive rather than replacing the contract gate during Phase 1.

CI must not mutate ``uv.lock``. A lock mismatch is a failure.

22. Existing validator integration
----------------------------------

No contract validator semantics change in Phase 1 unless project packaging exposes an
actual path/import problem.

The existing scripts remain canonical:

.. code-block:: console

   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py

The ``contracts`` dependency group supplies their imports. Do not move validation logic
into pytest merely to make one command own everything; contract validation remains a
separate explicit gate as well as part of normal CI.

23. Scripts and developer commands
----------------------------------

Do not add a ``Makefile``, shell wrapper, task runner, or custom Python orchestration
script in Phase 1. ``uv`` and the selected tools already provide the required commands.

Canonical local workflow:

.. code-block:: console

   uv sync
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests
   uv run lint-imports
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py
   uv run tox

A future wrapper may be justified only if repeated real use demonstrates value. Avoid
creating a second source of truth for command arguments in this phase.

24. Dependency and compatibility impact
---------------------------------------

Python
~~~~~~

The repository becomes a Python package project and CI support is explicitly 3.11,
3.12, and 3.13. Python 3.14 is not a required or advertised lane.

System dependencies
~~~~~~~~~~~~~~~~~~~

Phase 1 requires no root-installed service, database server, systemd configuration,
Git credential helper, hardware library, container runtime, or external observability
service.

Network
~~~~~~~

Dependency resolution during ``uv sync`` naturally needs package-index/network access.
Tests themselves must not depend on Internet access. The MCP server smoke path may bind
locally only when explicitly invoked; unit/integration tests monkeypatch or use in-process
ASGI construction rather than public network exposure.

Lock portability
~~~~~~~~~~~~~~~~

The committed lock must resolve on the supported Python range and the 64-bit Linux
reference direction. If a dependency chosen only for optional performance cannot resolve
on one supported lane, keep it optional rather than reducing the supported Python range.

25. Machine-readable policy/spec impact
---------------------------------------

Phase 1 changes no operation manifests, capability policy, security policy, schemas, or
security fixtures. It creates no new authority and therefore must not edit the
machine-readable Phase 0 policy merely to make the Python package aware of it.

Runtime contract loading is not implemented in this phase.

26. Error and shutdown semantics
--------------------------------

Configuration failure
~~~~~~~~~~~~~~~~~~~~~

CLI validation errors exit non-zero and identify the invalid setting without dumping
arbitrary environment contents.

Composition failure
~~~~~~~~~~~~~~~~~~~

If logging config or application construction fails, close any already-created logging
runtime before propagating a deterministic startup error.

Serve failure
~~~~~~~~~~~~~

A Uvicorn/FastMCP construction or bind failure exits non-zero. Phase 1 does not implement
restart loops or daemon supervision inside Python.

Shutdown
~~~~~~~~

Keyboard interrupt/process shutdown causes the composed application to stop and logging
resources to close. No durable recovery claim exists because Phase 1 owns no durable
operation.

27. Security invariants
-----------------------

The Phase 1 skeleton must preserve these invariants even though it has almost no
operational authority:

* the MCP/application process is designed to run unprivileged;
* default HTTP bind is loopback and one worker;
* no generic REST control API is added;
* no raw credential, SSH/GPG-agent, broker socket, protected control-plane, or device
  authority is introduced;
* no placeholder MCP Tool advertises unimplemented authority;
* no application/domain import depends on FastMCP/HTTP/CLI framework types;
* unknown configuration keys fail closed;
* settings are immutable after resolution;
* ordinary logs are not represented as audit;
* tests never require root or weaken host permissions;
* dependency installation remains project-local through ``uv``.

28. Implementation order
------------------------

The coding PR should implement Phase 1 in this order:

#. add ``pyproject.toml`` with build/project/dependency/tool configuration;
#. generate and commit ``uv.lock``;
#. create domain runtime identity and package version helper;
#. create typed settings/load path;
#. create structured logging bootstrap;
#. create the minimal ``BinnacleApplication`` lifecycle;
#. create the composition root;
#. create the FastMCP/Uvicorn adapter with zero operational Tools;
#. create Typer/Rich CLI and ``__main__`` entry;
#. add unit/integration tests;
#. add Import Linter contracts and tox configuration;
#. add ``.github/workflows/python.yml``;
#. run the full local command set;
#. verify the PR diff contains no operational capability implementation.

Do not reorder this by implementing future subsystem adapters first.

29. Acceptance checklist
------------------------

Phase 1 is ready to merge only when all of the following are true:

#. ``pyproject.toml`` uses setuptools, ``src`` layout, project name ``binnacle``, static
   bootstrap version ``0.1.0.dev0``, and Python ``>=3.11,<3.14``.
#. ``uv.lock`` is committed and ``uv sync --frozen`` succeeds from a clean checkout.
#. Runtime dependencies are limited to the Phase 1 stack; no persistence/executor/broker/
   Git/hardware/release dependency has been pulled forward.
#. ``import binnacle`` succeeds.
#. ``python -m binnacle --help`` and ``binnacle --help`` reach the same Typer CLI.
#. ``binnacle version`` works in human, agent, and JSON modes.
#. ``binnacle config validate`` validates immutable TOML/environment/CLI settings and
   rejects unknown keys.
#. ``binnacle serve`` can construct/start the FastMCP/Uvicorn skeleton with loopback and
   one-worker defaults.
#. Phase 1 registers no Binnacle operational MCP Tools or other operational MCP surface.
#. Domain/application modules contain no FastMCP/Uvicorn/Typer/Rich/Pydantic/structlog
   dependencies contrary to the defined layering.
#. Import Linter passes.
#. ``uv run pytest`` passes with the Phase 1 coverage gate.
#. ``uv run ruff check .`` passes.
#. ``uv run ruff format --check .`` passes.
#. ``uv run mypy src/binnacle tests`` passes in strict mode.
#. ``uv run python scripts/validate_contracts.py`` passes.
#. ``uv run python scripts/validate_schema_instances.py`` passes.
#. Tox can orchestrate Python 3.11, 3.12, and 3.13 where those interpreters are installed.
#. GitHub ``Python CI`` is green for the exact PR head on Python 3.11/3.12/3.13.
#. Existing ``Contract validation`` is green for the exact PR head.
#. No root/systemd/database/Git credential/network service setup is required by tests.
#. The implementation PR has not introduced later Bootstrap capability behavior merely
   to make the skeleton appear complete.

30. Planning stop rule
----------------------

This plan is complete when a coding agent can create the executable project foundation,
run it, test it, and preserve the intended architectural dependency direction without
making another packaging/composition/tooling decision.

Do not extend this document with the design of inspection Tools, host-specific MCP
behavior, workspace operations, durable persistence, executor IPC, Git operations, or
privileged self-management. Those concerns require their own reviewed phase plans and
must remain separate from Phase 1.
