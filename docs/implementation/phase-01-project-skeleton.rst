Binnacle Phase 1 Detailed Implementation Plan
=============================================

:Phase: 1 -- Create the executable project skeleton
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Primary objective: Turn the design repository into a runnable, typed, testable Python project without implementing operational capability
:Implementation scope: Project/package skeleton, composition root, configuration/logging/CLI foundations, quality tooling, and CI only

Purpose
-------

Phase 1 converts the repository from a contract/design repository into an executable
Python project while preserving the Bootstrap rule that architecture should only be
implemented where there is a real seam.

The phase establishes:

* the Python package and build metadata;
* the ``uv`` environment and lock workflow;
* the minimal application/composition structure;
* typed immutable configuration loading;
* structured logging bootstrap;
* a thin Typer/Rich local CLI;
* runtime identity/version reporting for local diagnostics;
* unit/smoke test layout;
* Python quality/type/import-boundary configuration;
* normal CI for the Python project while retaining the existing contract-validation
  workflow.

Phase 1 does **not** implement the Phase 2 FastMCP server, operational Tools, durable
operations, workspace mutation, command execution, Git mutation, privileged operations,
or systemd deployment.

The technology choices for FastMCP 4.x, the official MCP Python SDK 2.x, Uvicorn,
Streamable HTTP, SQLite/SQLAlchemy/Alembic, Git CLI, systemd, and Unix-socket IPC remain
fixed by the Bootstrap baseline. Their packages are added only by the first implementing
phase that actually imports/uses them, unless this phase genuinely needs them for the
executable skeleton.

1. Preconditions and governing sources
---------------------------------------

Phase 1 begins only after the Phase 0 detailed plan is merged and the Phase 0 contract
reconciliation work is authoritative for subsequent implementation.

Implementation follows this order:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. this document;
#. detailed contracts and schemas relevant to project/quality validation.

The following owner-approved architectural rules are binding:

* Python is the primary implementation language;
* supported target versions are Python 3.11, 3.12, and 3.13;
* ``uv`` is the dependency/environment tool;
* ``setuptools.build_meta`` is the build backend;
* architecture is lightweight ports-and-adapters;
* ordinary constructor composition is used instead of a DI framework;
* ``Protocol``/ABC boundaries are introduced only when there is a real consumer;
* MCP/CLI adapters remain thin and do not own domain semantics;
* infrastructure implementations must sit behind typed boundaries when introduced;
* dependencies are added only when first genuinely used;
* exact dependency resolution belongs in ``uv.lock``;
* repository quality gates include strict MyPy, Ruff, pytest/AnyIO/Hypothesis,
  coverage, tox/tox-uv, Import Linter, and the agreed development-only quality/security
  checks as applicable.

2. Roadmap exit gate
--------------------

Phase 1 implementation is complete only when a clean checkout can successfully run:

::

   uv sync
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src tests
   uv run lint-imports

and can import and execute the Binnacle application skeleton through both:

::

   uv run binnacle version
   uv run python -m binnacle version

The skeleton must also provide a local diagnostic command that constructs the same
application context used by later adapters without starting an MCP server.

GitHub Actions for the exact implementation head must run the Python test/quality gates
and the existing contract-validation workflow successfully.

3. Explicit non-goals
---------------------

Phase 1 does **not** implement:

* FastMCP application creation;
* MCP Tool registration;
* Streamable HTTP ``/mcp``;
* Uvicorn startup;
* ``/healthz`` or ``/readyz`` HTTP routes;
* MCP authentication/controller negotiation;
* contract registry compilation/loading;
* SQLite state or SQLAlchemy;
* Alembic migrations;
* operation lifecycle/idempotency;
* filesystem/workspace services;
* ``ripgrep`` adapter;
* command execution/executor IPC;
* Git services;
* credential brokering;
* privileged broker IPC;
* systemd units;
* Raspberry Pi deployment;
* package-manager operations;
* service restart/recovery;
* hardware adapters;
* Docker/Podman;
* dependency-injection framework;
* plugin framework;
* semantic/code index;
* production packaging/release publication.

If implementation requires one of these capabilities merely to make Phase 1 pass, the
phase boundary has been crossed and the design should be re-evaluated.

4. Repository changes
---------------------

The Phase 1 implementation PR is expected to create or modify the following paths.

4.1 New project files
~~~~~~~~~~~~~~~~~~~~~

::

   pyproject.toml
   uv.lock
   .python-version
   tox.ini
   .importlinter

``pyproject.toml``
   PEP 621 metadata, setuptools build configuration, project/runtime dependencies,
   dependency groups, console entry point, and tool configuration for pytest, coverage,
   Ruff, MyPy, Bandit, deptry, Vulture, Radon, and related Python-local checks.

``uv.lock``
   Exact resolved development lock generated by ``uv``. The lock is committed.

``.python-version``
   Reference local development interpreter, ``3.11``. This does not narrow the supported
   compatibility target of 3.11/3.12/3.13.

``tox.ini``
   Local compatibility matrix orchestration for Python 3.11, 3.12, and 3.13 using
   tox 4 + tox-uv.

``.importlinter``
   High-value dependency-direction rules for the package skeleton.

4.2 New Python package
~~~~~~~~~~~~~~~~~~~~~~

Create only modules that Phase 1 genuinely uses:

::

   src/
     binnacle/
       __init__.py
       __main__.py
       version.py
       runtime.py
       composition.py
       config/
         __init__.py
         models.py
         loader.py
       logging/
         __init__.py
         configure.py
       cli/
         __init__.py
         app.py
         output.py

Do **not** create empty future packages such as ``domain/``, ``ports/``, ``adapters/mcp/``,
``adapters/sqlite/``, ``git/``, ``executor/``, or ``privileged/`` merely to resemble the
target architecture. The detailed plan reserves their eventual ownership but the first
phase that has a real implementation/consumer creates them.

4.3 New tests
~~~~~~~~~~~~~

::

   tests/
     conftest.py
     smoke/
       test_import.py
     unit/
       test_version.py
       test_runtime.py
       test_composition.py
       config/
         test_models.py
         test_loader.py
       logging/
         test_configure.py
       cli/
         test_cli.py
         test_output.py

Phase 1 tests must not require network access, systemd, root privileges, Git credentials,
SQLite, or a Raspberry Pi.

4.4 GitHub Actions
~~~~~~~~~~~~~~~~~~

Keep the existing ``.github/workflows/contracts.yml`` contract-validation workflow.

Add:

::

   .github/workflows/python-quality.yml

The new workflow owns Python project checks only. Do not copy contract-validation logic
into it when the existing workflow already provides the authoritative contract gate.

4.5 Existing repository files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Review and update only if necessary:

* ``.gitignore`` for ``.venv/``, ``.tox/``, ``.coverage``, ``htmlcov/``,
  ``.mypy_cache/``, ``.ruff_cache/``, and build metadata;
* ``.pre-commit-config.yaml`` to call project-local tools consistently after
  ``pyproject.toml`` exists;
* documentation references that explicitly assume the repository is design-only, but
  only if they would become factually incorrect after Phase 1.

Do not rewrite unrelated design documents.

5. Python package metadata
--------------------------

5.1 Build system
~~~~~~~~~~~~~~~~

``pyproject.toml`` must use setuptools through PEP 517:

.. code-block:: toml

   [build-system]
   requires = ["setuptools>=80,<82"]
   build-backend = "setuptools.build_meta"

Do not add Hatchling, Poetry, PDM, Flit, setuptools-scm, or a custom build backend in
Phase 1.

5.2 Project metadata
~~~~~~~~~~~~~~~~~~~~

Preferred PEP 621 shape:

.. code-block:: toml

   [project]
   name = "binnacle"
   version = "0.1.0.dev0"
   description = "Deterministic Raspberry Pi execution boundary for ChatGPT"
   requires-python = ">=3.11,<3.14"
   readme = "README.md"
   license = {text = "MIT"}  # only if this matches the repository's existing license
   dependencies = [
     "pydantic>=2,<3",
     "pydantic-settings>=2,<3",
     "structlog>=25,<26",
     "typer>=0.16,<1",
     "rich>=14,<15",
   ]

The implementation must not invent a license. If the repository's actual license differs
or no license exists, use the repository truth instead of the illustrative line above.

``0.1.0.dev0`` is the initial development distribution version unless the existing
repository already declares another canonical package version. Do not add dynamic VCS
versioning in Phase 1.

5.3 Package discovery
~~~~~~~~~~~~~~~~~~~~~

Use the ``src`` layout:

.. code-block:: toml

   [tool.setuptools]
   package-dir = {"" = "src"}

   [tool.setuptools.packages.find]
   where = ["src"]

Editable development comes from ``uv sync`` rather than ad-hoc ``PYTHONPATH`` mutation.

5.4 CLI entry point
~~~~~~~~~~~~~~~~~~~

Declare one console script:

.. code-block:: toml

   [project.scripts]
   binnacle = "binnacle.cli.app:main"

``python -m binnacle`` must dispatch to the same Typer application rather than maintain a
second command surface.

6. Dependency policy for Phase 1
--------------------------------

6.1 Runtime dependencies introduced now
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add only packages used by the Phase 1 skeleton:

``pydantic``
   Typed immutable settings/runtime models.

``pydantic-settings``
   Environment-aware settings construction.

``structlog``
   Structured logging bootstrap.

``typer``
   Local CLI adapter.

``rich``
   Human-oriented CLI rendering.

6.2 Technology choices fixed but packages deferred
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following choices are authoritative but their Python dependencies are first added by
the phase that imports/uses them:

* FastMCP 4.x -> Phase 2;
* official MCP Python SDK 2.x -> Phase 2;
* Uvicorn -> Phase 2;
* ``uvloop`` -> Phase 2 when supported by the reference Pi;
* ``httptools`` -> Phase 2 when supported;
* SQLAlchemy 2.x -> Phase 4;
* ``aiosqlite`` -> Phase 4;
* Alembic -> Phase 4.

This is not a technology-stack re-decision. It applies the implementation-index rule that
packages enter ``pyproject.toml`` when the first implementing phase genuinely requires
them.

System-native future dependencies such as Git, ``ripgrep``, systemd, OpenSSH/GPG, and
package managers are not represented as Python dependencies.

6.3 Development/test dependency groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use PEP 735 dependency groups supported by ``uv``. Preferred groups:

.. code-block:: toml

   [dependency-groups]
   test = [
     "pytest>=8,<9",
     "anyio>=4,<5",
     "hypothesis>=6,<7",
     "coverage[toml]>=7,<8",
   ]
   quality = [
     "ruff>=0.12,<1",
     "mypy>=1.17,<2",
     "import-linter>=2,<3",
     "bandit>=1.8,<2",
     "pip-audit>=2,<3",
     "deptry>=0.23,<1",
     "vulture>=2.14,<3",
     "codespell>=2.4,<3",
     "radon>=6,<7",
   ]
   matrix = [
     "tox>=4,<5",
     "tox-uv>=1,<2",
   ]
   dev = [
     {include-group = "test"},
     {include-group = "quality"},
     {include-group = "matrix"},
   ]

If a currently available tool version has moved beyond the illustrative compatibility
range, the implementation may adjust the range while keeping the agreed tool family and
recording the reason in the PR. Exact resolution remains in ``uv.lock``.

Do not add ``pytest-cov`` merely to wrap ``coverage.py``; use ``coverage run -m pytest``
unless a later implementation demonstrates a concrete need.

7. ``uv`` workflow
------------------

7.1 Clean checkout
~~~~~~~~~~~~~~~~~~

The canonical development setup is:

::

   uv sync --group dev

This creates/updates ``.venv`` and installs the project editable in the project
environment.

The minimal runtime-only install for the skeleton is:

::

   uv sync --no-dev

7.2 Lock discipline
~~~~~~~~~~~~~~~~~~~

The implementation PR must generate and commit ``uv.lock``.

CI uses ``--frozen`` after the lock is committed:

::

   uv sync --frozen --group dev

Dependency updates use an explicit lock refresh rather than silently resolving on every
CI run.

7.3 Python support
~~~~~~~~~~~~~~~~~~

``requires-python`` is ``>=3.11,<3.14``.

The reference development interpreter is 3.11 through ``.python-version``. The tox/CI
matrix verifies 3.11, 3.12, and 3.13.

Python 3.14 may be explored later but must not be included in the supported matrix or
used to force dependency choices during Bootstrap.

8. Canonical package ownership
------------------------------

8.1 ``binnacle.version``
~~~~~~~~~~~~~~~~~~~~~~~~

Owns distribution-version access only.

Public interface:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass(frozen=True, slots=True)
   class VersionInfo:
       distribution: str
       version: str

   def get_version_info() -> VersionInfo:
       ...

Implementation uses ``importlib.metadata.version("binnacle")``. It must not run Git
commands to discover a version in Phase 1.

``binnacle.__init__`` may expose ``__version__`` as a convenience derived from
``get_version_info()`` but must not perform expensive startup work.

8.2 ``binnacle.runtime``
~~~~~~~~~~~~~~~~~~~~~~~~

Owns process-local immutable runtime identity facts that are available without Git,
SQLite, systemd, or MCP.

Types:

.. code-block:: python

   from dataclasses import dataclass
   from datetime import datetime
   from pathlib import Path

   @dataclass(frozen=True, slots=True)
   class RuntimeIdentity:
       version: str
       python_version: str
       python_executable: Path
       platform: str
       process_id: int
       started_at: datetime

   def build_runtime_identity(*, started_at: datetime | None = None) -> RuntimeIdentity:
       ...

``started_at`` is captured once during composition. The object does not claim Git
revision, branch, dirty state, contract digests, service identity, or database readiness;
those facts enter in later phases when their providers exist.

8.3 ``binnacle.config.models``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns Phase 1 settings types.

Recommended types:

.. code-block:: python

   from enum import StrEnum
   from pydantic import BaseModel, ConfigDict, Field
   from pydantic_settings import BaseSettings, SettingsConfigDict

   class RuntimeProfile(StrEnum):
       DEVELOPMENT = "development"

   class LogFormat(StrEnum):
       CONSOLE = "console"
       JSON = "json"

   class OutputMode(StrEnum):
       HUMAN = "human"
       AGENT = "agent"
       JSON = "json"

   class LoggingSettings(BaseModel):
       model_config = ConfigDict(frozen=True, extra="forbid")

       level: str = "INFO"
       format: LogFormat = LogFormat.CONSOLE

   class AppSettings(BaseSettings):
       model_config = SettingsConfigDict(
           env_prefix="BINNACLE_",
           frozen=True,
           extra="forbid",
       )

       profile: RuntimeProfile = RuntimeProfile.DEVELOPMENT
       logging: LoggingSettings = LoggingSettings()

No credential, authentication, broker, executor, database, workspace, or policy settings
are added merely as placeholders.

8.4 ``binnacle.config.loader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns settings-source merging and TOML loading.

Public interface:

.. code-block:: python

   from collections.abc import Mapping
   from pathlib import Path
   from typing import Any

   def load_settings(
       *,
       config_path: Path | None = None,
       environ: Mapping[str, str] | None = None,
       overrides: Mapping[str, Any] | None = None,
   ) -> AppSettings:
       ...

Phase 1 precedence is deliberately small and deterministic:

#. explicit ``overrides`` from the local CLI/application composition;
#. environment variables using the ``BINNACLE_`` prefix;
#. explicit TOML file when ``config_path`` is supplied;
#. model defaults.

Phase 1 does not auto-discover system/user configuration paths. Phase 3 owns deployment
paths such as ``/etc/binnacle/``.

Malformed TOML, unknown keys, invalid enum values, and invalid types fail closed with a
typed configuration error before application composition completes.

Define one exception:

.. code-block:: python

   class ConfigurationError(ValueError):
       pass

The loader should normalise third-party parsing/validation exceptions into
``ConfigurationError`` while retaining the original exception as ``__cause__``.

8.5 ``binnacle.logging.configure``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns stdlib logging + structlog configuration.

Public interface:

.. code-block:: python

   def configure_logging(settings: LoggingSettings) -> None:
       ...

   def reset_logging_for_tests() -> None:
       ...

Requirements:

* structured events use ``structlog``;
* no file sink is configured;
* output goes to stdout/stderr for future journald capture;
* console format is readable for local development;
* JSON format emits one structured event per line;
* timestamp and level are present;
* library loggers propagate through the same stdlib configuration;
* repeated calls are deterministic/idempotent for tests;
* no background queue is required in Phase 1 because no long-running server exists yet;
* no secret-redaction framework is invented before secret-bearing fields exist.

8.6 ``binnacle.composition``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns the Phase 1 composition root.

Types and functions:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass(frozen=True, slots=True)
   class ApplicationContext:
       settings: AppSettings
       runtime: RuntimeIdentity

   def build_application(
       *,
       settings: AppSettings,
   ) -> ApplicationContext:
       ...

``build_application``:

* performs constructor composition only;
* does not read environment/TOML itself;
* does not configure global logging implicitly;
* does not start threads/tasks/processes;
* does not open network sockets;
* does not create database connections;
* does not invoke Git/systemd/subprocesses.

Later phases may extend ``ApplicationContext`` or introduce more specific application
service containers. They should not bypass this composition-root responsibility by
constructing infrastructure ad hoc inside MCP handlers.

8.7 ``binnacle.cli.output``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Owns deterministic output rendering for local CLI commands.

Public functions:

.. code-block:: python

   from collections.abc import Mapping
   from typing import Any

   def emit(
       payload: Mapping[str, Any],
       *,
       mode: OutputMode,
   ) -> None:
       ...

Requirements:

* ``human`` uses Rich formatting;
* ``agent`` is compact deterministic text with stable key ordering;
* ``json`` uses stable JSON object output without Rich markup;
* output functions do not perform application work;
* JSON output goes to stdout; error diagnostics use stderr;
* stable machine-readable output must not contain incidental ANSI escape codes.

8.8 ``binnacle.cli.app``
~~~~~~~~~~~~~~~~~~~~~~~~

Owns the Typer adapter and nothing else.

Create one Typer application:

.. code-block:: python

   app = typer.Typer(no_args_is_help=True)

   def main() -> None:
       app()

Required Phase 1 commands:

``binnacle version``
   Emits distribution/Python version information. Does not load deployment state.

``binnacle doctor``
   Loads settings, configures logging, builds ``ApplicationContext``, and reports the
   Phase 1-local checks below.

``binnacle config show``
   Emits the resolved **non-secret Phase 1** settings snapshot. Because Phase 1 has no
   credentials/security-critical secrets, no redaction framework is needed yet.

Every command supports ``--output human|agent|json``. ``doctor`` and ``config show``
accept ``--config PATH``.

Do not add ``serve``, ``setup``, ``db``, ``workspace``, ``exec``, ``git``, ``service``, or
``restart`` commands in this phase.

8.9 ``binnacle.__main__``
~~~~~~~~~~~~~~~~~~~~~~~~~

Contains only:

.. code-block:: python

   from binnacle.cli.app import main

   if __name__ == "__main__":
       main()

No second CLI parser is permitted.

9. Phase 1 diagnostic model
---------------------------

``binnacle doctor`` is a project-skeleton smoke diagnostic, not the future operational
health/readiness endpoint.

It reports:

* package distribution version;
* Python version and interpreter path;
* runtime platform string;
* runtime profile;
* configuration source path if explicitly supplied;
* whether settings validation succeeded;
* whether application composition succeeded.

It must not claim:

* MCP readiness;
* authentication readiness;
* database readiness;
* executor readiness;
* broker readiness;
* Git state;
* systemd service state;
* contract registry readiness;
* Raspberry Pi hardware readiness.

Recommended result type:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class DoctorResult:
       ok: bool
       runtime: RuntimeIdentity
       profile: RuntimeProfile
       config_path: Path | None
       checks: tuple[DoctorCheck, ...]

   @dataclass(frozen=True, slots=True)
   class DoctorCheck:
       name: str
       ok: bool
       detail: str

These types may live in ``binnacle.cli.app`` only if they remain CLI-specific. If Phase 1
unit tests demonstrate they are application semantics shared by multiple adapters, move
them to ``runtime.py`` rather than creating an empty application-service layer.

10. Reserved future package ownership
-------------------------------------

Phase 1 documents, but does not create, these future ownership boundaries:

``binnacle.domain``
   Domain/core semantics such as controller and operation identity when first needed.

``binnacle.application``
   Use-case orchestration when Phase 2/4 creates actual application services.

``binnacle.ports``
   Typed ``Protocol``/ABC boundaries once an application use case has a real external
   dependency.

``binnacle.adapters.mcp``
   Phase 2 FastMCP/HTTP adapter.

``binnacle.adapters.sqlite``
   Phase 4 SQLAlchemy/SQLite adapter.

``binnacle.adapters.filesystem``
   Phase 5/6 workspace/filesystem adapter.

``binnacle.adapters.executor``
   Phase 7 executor client/IPC adapter.

``binnacle.adapters.git``
   Phase 8 Git CLI adapter.

``binnacle.adapters.privileged``
   Phase 9 privileged-broker client/IPC adapter.

These names establish ownership for planning consistency but must not result in empty
packages or placeholder classes in the Phase 1 implementation.

11. Protocol/ABC policy
-----------------------

Phase 1 introduces **no future infrastructure Protocol merely for anticipation**.

A ``Protocol`` is added only when Phase 1 itself has at least one consumer and a real
replaceable boundary.

The default Phase 1 functions use concrete immutable types:

* ``AppSettings``;
* ``RuntimeIdentity``;
* ``ApplicationContext``;
* ``LoggingSettings``;
* CLI output enums/results.

Future phase examples such as ``OperationStore``, ``GitPort``, ``WorkspacePort``,
``ExecutorPort``, ``PrivilegedPort``, ``PolicyEngine``, and ``Clock`` remain documented
ownership only until their first consumer exists.

This prevents an empty interface framework while keeping the architectural direction
clear.

12. Import/dependency direction
-------------------------------

12.1 Allowed Phase 1 direction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Conceptually:

::

   binnacle.cli
       -> binnacle.composition
       -> binnacle.config
       -> binnacle.runtime
       -> binnacle.version

   binnacle.logging
       -> binnacle.config.models

``binnacle.config``, ``binnacle.runtime``, and ``binnacle.version`` must not import Typer,
Rich, or CLI modules.

``binnacle.composition`` must not import CLI modules.

12.2 Import Linter contracts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure at least these rules:

#. core skeleton modules must not import ``binnacle.cli``;
#. ``binnacle.config`` must not import ``binnacle.logging`` or ``binnacle.cli``;
#. ``binnacle.runtime`` must not import ``binnacle.cli`` or third-party interface
   frameworks;
#. ``binnacle.version`` must remain stdlib-only;
#. ``binnacle.cli`` may depend inward on composition/config/runtime/version.

A preferred `.importlinter` form is a small set of ``forbidden`` contracts rather than a
large speculative layer graph.

13. Configuration semantics
----------------------------

13.1 TOML input
~~~~~~~~~~~~~~~

Phase 1 accepts a caller-supplied TOML file such as:

.. code-block:: toml

   profile = "development"

   [logging]
   level = "INFO"
   format = "console"

Unknown keys fail validation.

13.2 Environment mapping
~~~~~~~~~~~~~~~~~~~~~~~~

Environment variable names use the ``BINNACLE_`` prefix and nested delimiter ``__`` if
needed, for example:

::

   BINNACLE_PROFILE=development
   BINNACLE_LOGGING__LEVEL=DEBUG
   BINNACLE_LOGGING__FORMAT=json

The exact pydantic-settings configuration must be unit-tested rather than assumed.

13.3 CLI overrides
~~~~~~~~~~~~~~~~~~

CLI flags may override only Phase 1 non-security settings such as log level/output mode.

Later security-critical settings must not automatically inherit this permissive override
model. The configuration loader API therefore keeps ``overrides`` explicit so later
phases can separate ordinary overrides from protected configuration sources.

13.4 Settings immutability
~~~~~~~~~~~~~~~~~~~~~~~~~~

Resolved settings are frozen Pydantic models. Code must not mutate a global settings
singleton.

Application components receive the resolved settings or the specific settings subtree
they require through constructor/function arguments.

14. Logging semantics
---------------------

14.1 Event shape
~~~~~~~~~~~~~~~~

Each structured event should have, where available:

* timestamp;
* level;
* event/message;
* package version;
* runtime profile.

Phase 1 does not invent operation/controller/request correlation IDs before those
concepts exist.

14.2 Output destination
~~~~~~~~~~~~~~~~~~~~~~~

Use stdout/stderr only. Future systemd deployment will capture output into journald.

No rotating files, external log service, OpenTelemetry collector, metrics backend, or
external observability agent is introduced.

14.3 Testability
~~~~~~~~~~~~~~~~

Tests must be able to configure/reset logging repeatedly without duplicate handlers or
processor chains.

The test suite must assert that JSON output is valid JSON and that console output does
not leak Rich/ANSI sequences into JSON mode.

15. CLI error model
-------------------

Phase 1 defines a small local CLI error boundary.

``ConfigurationError``
   Invalid/missing TOML, invalid environment values, unknown settings, or incompatible
   configuration.

``ApplicationBuildError``
   Composition failure that is not already represented by ``ConfigurationError``.

Preferred definition:

.. code-block:: python

   class ApplicationBuildError(RuntimeError):
       pass

CLI behaviour:

* human mode: concise Rich error on stderr;
* agent mode: deterministic one-line error with stable error code;
* JSON mode: object containing ``ok=false``, stable ``error_code``, and safe message;
* non-zero exit code for failures;
* traceback only when an explicit local debug flag is supplied.

Do not build the future MCP error taxonomy in Phase 1.

16. Quality configuration
-------------------------

16.1 Ruff
~~~~~~~~~

Preferred configuration:

.. code-block:: toml

   [tool.ruff]
   target-version = "py311"
   line-length = 100

   [tool.ruff.lint]
   select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

   [tool.ruff.format]
   quote-style = "double"

Avoid enabling large stylistic rule sets that create churn without correctness value.

16.2 MyPy
~~~~~~~~~

Use strict typing for ``src`` and tests:

.. code-block:: toml

   [tool.mypy]
   python_version = "3.11"
   strict = true
   warn_unreachable = true
   show_error_codes = true
   pretty = true

Do not globally silence missing-import or Any errors merely to make CI green. Add narrow
per-module exceptions only for a documented third-party typing defect.

16.3 Pytest
~~~~~~~~~~~

Preferred configuration:

.. code-block:: toml

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   addopts = "-ra --strict-config --strict-markers"

No implicit network/systemd/root fixtures are allowed in the Phase 1 default test suite.

16.4 Coverage
~~~~~~~~~~~~~

Enable branch coverage:

.. code-block:: toml

   [tool.coverage.run]
   branch = true
   source = ["binnacle"]

   [tool.coverage.report]
   show_missing = true
   skip_covered = true
   fail_under = 90

If the initial implementation cannot meet 90% without meaningless tests, the PR must
justify a narrowly lower temporary threshold rather than adding assertions solely to
inflate coverage.

16.5 Bandit
~~~~~~~~~~~

Configure Bandit for ``src/binnacle``. Tests may be excluded from normal Bandit scanning
unless test code starts managing credentials/subprocesses later.

16.6 deptry
~~~~~~~~~~~

Use deptry to prevent undeclared, obsolete, and misplaced dependencies. Development-only
tools must remain in dependency groups rather than project runtime dependencies.

16.7 Vulture and Radon
~~~~~~~~~~~~~~~~~~~~~~

Use conservative Vulture confidence and Radon complexity reporting.

For Phase 1 these are advisory/reporting checks unless the implementation establishes a
small, stable threshold that cannot produce false-positive churn. Ruff/MyPy/tests/import
boundaries remain the primary hard Python code gates.

16.8 Codespell and repository document checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retain existing documentation/schema checks. Codespell may include source/docs with an
allowlist for legitimate domain terms.

Do not replace existing markdown/Mermaid/YAML/schema validation scripts with a new Python
wrapper.

17. tox matrix
--------------

Use tox 4 with tox-uv.

Required environments:

::

   py311
   py312
   py313

Each environment runs the unit/smoke suite against the locked project dependency
constraints.

A separate local ``quality`` tox environment may invoke the hard quality gates, but CI
may call ``uv run`` directly to keep logs simple.

The tox matrix must not include Python 3.14 in Bootstrap support claims.

18. GitHub Actions design
-------------------------

18.1 Workflow name
~~~~~~~~~~~~~~~~~~

Create ``.github/workflows/python-quality.yml`` with display name:

::

   Python quality

18.2 Trigger
~~~~~~~~~~~~

Run on pull requests affecting Python/project/quality files and on pushes to ``master``.
Path filtering must not be so narrow that changes to ``pyproject.toml`` or ``uv.lock``
can bypass the workflow.

18.3 Quality job
~~~~~~~~~~~~~~~~

Use Python 3.11 as the authoritative quality interpreter.

Steps:

#. checkout;
#. install Python 3.11;
#. install pinned/current supported ``uv`` action/tool;
#. ``uv sync --frozen --group dev``;
#. ``uv run ruff check .``;
#. ``uv run ruff format --check .``;
#. ``uv run mypy src tests``;
#. ``uv run lint-imports``;
#. ``uv run bandit -r src/binnacle``;
#. ``uv run deptry .``;
#. ``uv run coverage run -m pytest``;
#. ``uv run coverage report``.

Use official/mature GitHub Actions rather than custom bootstrap scripts.

18.4 Compatibility test matrix
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Separate test job matrix:

::

   3.11
   3.12
   3.13

Each job performs frozen sync for the test group and runs pytest.

If a dependency does not publish wheels for one supported interpreter on the reference
platform, investigate before relaxing the declared Python support range.

18.5 Existing contract workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not delete or weaken ``.github/workflows/contracts.yml``. Phase 1 acceptance requires
both ``Contract validation`` and ``Python quality`` to pass for the implementation PR.

18.6 CodeQL
~~~~~~~~~~~

If the repository does not already run GitHub CodeQL for Python, Phase 1 implementation
may add the standard GitHub CodeQL workflow because Python code now exists. Prefer the
official GitHub action/configuration; do not implement a custom SAST wrapper.

19. Pre-commit integration
--------------------------

The existing pre-commit configuration remains the local fast feedback layer.

Add/adjust only hooks that now have a project-local authoritative configuration, for
example:

* Ruff check;
* Ruff format check/fix according to existing repository policy;
* MyPy if runtime remains acceptable for local commits;
* existing Markdown/YAML/Mermaid/schema checks unchanged.

Avoid duplicating every CI-only scanner as a pre-commit hook. ``pip-audit``/CodeQL/tox
matrix can remain CI/manual because they are not useful on every commit.

20. Local validation command set
--------------------------------

The Phase 1 implementation PR must make the following commands authoritative and
document them in the PR description:

::

   uv sync --group dev
   uv lock --check
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src tests
   uv run lint-imports
   uv run bandit -r src/binnacle
   uv run deptry .
   uv run coverage run -m pytest
   uv run coverage report
   uv run tox -e py311,py312,py313
   python scripts/validate_contracts.py
   python scripts/validate_schema_instances.py
   uv run binnacle version --output json
   uv run binnacle doctor --output json
   uv run python -m binnacle version --output json

If ``uv lock --check`` syntax differs in the selected uv release, use the current
supported equivalent and record it in the implementation PR.

21. Test plan
-------------

21.1 Import/install smoke tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``tests/smoke/test_import.py`` verifies:

* ``import binnacle`` succeeds after ``uv sync``;
* distribution metadata resolves;
* no import starts a server/thread/process;
* no import reads deployment config or opens files outside package metadata.

21.2 Version tests
~~~~~~~~~~~~~~~~~~

Verify:

* package version matches distribution metadata;
* ``version`` command returns stable human/agent/JSON shapes;
* module and console-script paths report the same version.

21.3 Configuration model tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verify:

* defaults are valid and frozen;
* unknown keys fail;
* invalid runtime/log-format values fail;
* nested environment variables resolve as intended;
* settings cannot be mutated after creation.

21.4 Configuration loader tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verify precedence:

#. explicit override;
#. environment;
#. TOML;
#. defaults.

Also verify:

* malformed TOML -> ``ConfigurationError``;
* wrong types -> ``ConfigurationError``;
* missing explicitly requested file -> ``ConfigurationError``;
* no config path -> defaults/environment only;
* caller-supplied environment mapping prevents tests from depending on global process
  environment.

21.5 Logging tests
~~~~~~~~~~~~~~~~~~

Verify:

* console configuration installs no duplicate handlers;
* JSON mode emits parseable JSON;
* repeated configure/reset cycles remain deterministic;
* log event includes level/timestamp/event;
* JSON mode contains no ANSI sequences.

21.6 Composition tests
~~~~~~~~~~~~~~~~~~~~~~

Verify:

* ``build_application`` returns frozen context;
* supplied settings object is the one represented by the context;
* runtime identity is constructed once;
* composition performs no network, filesystem deployment, subprocess, Git, systemd, or
  database effects.

21.7 CLI tests
~~~~~~~~~~~~~~

Use Typer's test runner.

Verify:

* no-args shows help;
* ``version`` succeeds;
* ``doctor`` succeeds with defaults;
* ``doctor --config`` uses the supplied TOML;
* malformed config produces non-zero exit;
* ``config show`` supports all three output modes;
* JSON output is stable/parseable;
* ``python -m binnacle`` and console script dispatch the same commands;
* no Phase 2/later command appears in help.

21.8 Import-boundary tests
~~~~~~~~~~~~~~~~~~~~~~~~~~

``lint-imports`` must fail if core skeleton modules import CLI/interface modules in the
forbidden direction.

22. Error and exit-code policy
-----------------------------

Use a small stable CLI exit policy:

``0``
   success;

``2``
   CLI usage/argument validation error (Typer/Click convention);

``10``
   configuration error;

``20``
   application composition/diagnostic failure.

Do not pre-allocate future MCP/operation/executor error-code ranges in Phase 1.

JSON/agent output should include symbolic error codes such as
``configuration_invalid`` rather than relying only on numeric process exits.

23. Security invariants for Phase 1
----------------------------------

Import safety
~~~~~~~~~~~~~

Importing ``binnacle`` performs no consequential effect.

Configuration safety
~~~~~~~~~~~~~~~~~~~~

Unknown settings fail closed. Resolved settings are immutable. No credential or
security-critical configuration model is added before its governing phase.

Logging safety
~~~~~~~~~~~~~~

Phase 1 logs no environment dump and does not serialize the entire process environment.

CLI safety
~~~~~~~~~~

The CLI exposes diagnostics/configuration only. It cannot execute arbitrary commands,
write arbitrary files, perform Git mutation, install packages, restart services, or
start a remote server.

Dependency safety
~~~~~~~~~~~~~~~~~

Development-only tools do not become project runtime dependencies. Dependency versions
are locked and CI uses frozen resolution.

Architecture safety
~~~~~~~~~~~~~~~~~~~

Interface/UI dependencies do not leak into core configuration/runtime/version modules.
No empty privileged/executor/Git/database abstractions create misleading authority.

24. Implementation ordering within Phase 1
------------------------------------------

Implement in this order:

#. create ``pyproject.toml`` build/project metadata and ``src`` package discovery;
#. create minimal ``version.py`` and import smoke path;
#. create ``config.models`` and ``config.loader``;
#. create ``logging.configure``;
#. create ``runtime.py`` and ``composition.py``;
#. create CLI output adapter and commands;
#. add unit/smoke tests alongside each module;
#. add Ruff/MyPy/pytest/coverage configuration;
#. add Import Linter rules;
#. add remaining quality dependency groups/configuration;
#. generate ``uv.lock``;
#. add tox matrix;
#. add ``python-quality.yml``;
#. update pre-commit/gitignore only where needed;
#. run complete local validation;
#. push and require both Python and contract CI gates.

Do not create all files first and postpone testing until the end.

25. Review checklist
--------------------

A reviewer should verify:

* project uses ``src`` layout and setuptools build backend;
* Python support is exactly 3.11/3.12/3.13 for Bootstrap;
* ``uv.lock`` is committed and CI uses frozen resolution;
* only Phase 1 runtime dependencies are in ``project.dependencies``;
* FastMCP/Uvicorn/SQLAlchemy/Alembic are not pulled early merely because they are future
  choices;
* no empty future package/interface framework was created;
* CLI is thin and non-operational;
* settings are immutable and fail closed on unknown keys;
* logging uses structlog/stdlib and stdout/stderr only;
* composition is explicit constructor/function composition, not a DI container;
* imports obey inward dependency direction;
* tests do not require network/root/systemd/Raspberry Pi;
* strict MyPy and Ruff pass;
* Import Linter passes;
* test coverage meets the agreed threshold or a documented narrow exception;
* 3.11/3.12/3.13 compatibility tests pass;
* existing contract/schema validation remains active;
* no Phase 2 MCP server capability is implemented.

26. Deterministic acceptance checklist
--------------------------------------

Phase 1 implementation is accepted only when all items below are true:

#. ``pyproject.toml`` uses ``setuptools.build_meta`` and ``src`` layout;
#. ``requires-python`` covers 3.11 through 3.13 and excludes unsupported 3.14;
#. ``uv.lock`` exists and frozen sync succeeds;
#. ``uv sync`` installs/imports Binnacle from a clean checkout;
#. ``binnacle version`` works through console script and ``python -m binnacle``;
#. ``binnacle doctor`` constructs ``ApplicationContext`` without external effects;
#. settings load from defaults/TOML/environment/explicit overrides with documented
   precedence;
#. invalid/unknown configuration fails deterministically;
#. logging supports console and JSON modes without duplicate handlers;
#. CLI human/agent/JSON output paths are deterministic;
#. Ruff check/format pass;
#. strict MyPy passes;
#. Import Linter passes;
#. Bandit and deptry hard checks pass;
#. pytest/coverage passes;
#. tox tests Python 3.11, 3.12, and 3.13;
#. GitHub Actions ``Python quality`` passes for the exact head;
#. GitHub Actions ``Contract validation`` passes for the exact head;
#. no Phase 2 or later operational capability exists in the implementation diff.

27. Handoff to Phase 2
----------------------

After the Phase 1 implementation and this detailed plan are authoritative, Phase 2 may
introduce the first real MCP-facing adapter and the dependencies it actually uses:
FastMCP 4.x, the official MCP Python SDK 2.x, Uvicorn, and the selected optional event
loop/parser dependencies.

Phase 2 must build on the existing composition/config/logging/runtime foundations rather
than creating a parallel server-specific settings system or dependency-injection path.

The Phase 1 package skeleton is intentionally small. Its success criterion is not the
number of modules created; it is that the next phase can implement the read-only MCP
compatibility server without first re-deciding package layout, dependency tooling,
configuration ownership, logging ownership, CLI conventions, or quality gates.
