Binnacle Phase 2 Detailed Implementation Plan
=============================================

:Phase: 2 -- Build the read-only MCP compatibility server
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 1 project-skeleton plan
:Primary objective: Turn the runnable zero-capability MCP skeleton into a locally testable read-only compatibility server
:Implementation scope: compatibility-core MCP Tools, contract/schema runtime registry, bounded host inspection, protocol adaptation, health/readiness, and local MCP integration tests only

Purpose
-------

Phase 2 is the first phase that exposes real Binnacle MCP Tools.  It keeps the authority
surface deliberately read-only and local so protocol, schema, manifest, result, error,
and application-layer behaviour can be proven before remote deployment or consequential
operations exist.

The Phase 1 skeleton already establishes Python packaging, FastMCP 4.x over the official
MCP Python SDK 2.x line, Uvicorn, Pydantic settings, Typer/Rich, structlog, the
composition root, and a runnable MCP/HTTP process with zero Binnacle operational Tools.
Phase 2 consumes those decisions rather than re-deciding them.

A successful Phase 2 implementation provides exactly the reviewed
``compatibility-core`` catalogue:

* ``binnacle_probe``;
* ``system_inspect``;
* ``probe_result_formats``;
* ``probe_error``;
* ``compatibility_report``.

The implementation remains incapable of workspace mutation, command execution, Git
mutation, package/service changes, privileged operations, durable operation admission,
credential use, or hardware control.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-01-project-skeleton.rst``;
#. this detailed Phase 2 plan;
#. ``docs/mcp-interface.md``;
#. ``docs/mcp-revision-support.md``;
#. ``docs/mcp-schemas.md``;
#. ``docs/mcp-tool-manifest.md``;
#. ``docs/mcp-profile.md`` and ``docs/mcp-evaluation.md`` where they define status and
   evidence vocabulary;
#. machine-readable MCP manifest, schemas, evaluation fixtures, and validators;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

The reviewed Tool manifest and JSON Schemas are authoritative for Tool names,
descriptions, annotations, contract versions, input/output shapes, information class,
confirmation class, and catalogue membership.  Runtime code projects those contracts;
it does not invent a parallel Tool contract.

2. Roadmap exit gate
--------------------

Phase 2 implementation is complete only when all of the following are true:

* a clean checkout still passes the complete Phase 1 project/quality gates;
* the application starts a one-worker Streamable HTTP MCP server on loopback;
* ``/mcp`` is the only MCP control route;
* ``/healthz`` reports process liveness without exposing diagnostics;
* ``/readyz`` reports ready only after the compatibility-core registry and all five
  handlers are validated and the application lifecycle is started;
* a local MCP client can list exactly the five compatibility-core Tools;
* every listed Tool's name, description, annotations, input schema, output schema,
  contract version, and binding match the reviewed manifest projection;
* a local MCP client can invoke all five Tools;
* every successful ``structuredContent`` validates against the exact declared output
  schema and includes bounded model-readable content;
* every synthetic Tool execution error uses the canonical execution-error envelope and
  ``isError=true`` rather than masquerading as an HTTP authentication or protocol error;
* supported MCP revision behaviour is exercised locally for the finite repository
  revision set to the extent required by this phase;
* no mutating Tool is discoverable or callable;
* no consequential device effect is possible;
* the exact implementation head passes GitHub Actions.

3. Explicit non-goals
---------------------

Phase 2 does **not** implement:

* remote deployment to a Raspberry Pi;
* real ChatGPT connection, account/workspace entitlement testing, or UI evidence;
* production OAuth/OIDC or trusted-gateway authentication;
* an externally reachable unauthenticated listener;
* the ``compatibility-write-probe`` catalogue;
* ``probe_workspace_prepare``, ``probe_workspace_write``, or
  ``probe_workspace_cleanup`` handlers;
* workspace registration, file list/read/search, or any file mutation;
* command execution or an execution supervisor;
* SQLite, SQLAlchemy, Alembic, durable operations, idempotency persistence, retained
  output, or audit journal;
* Git status/diff/commit/fetch/push;
* SSH/GPG credentials or credential brokering;
* package installation, systemd service mutation, restart, reboot, or privileged broker;
* Resources, Prompts, MCP Tasks, MRTR/elicitation, subscriptions, Sampling, or Roots;
* hardware/GPIO/I2C/SPI/UART/camera support;
* STDIO transport;
* multiple Uvicorn workers;
* production packaging or release publication;
* performance tuning beyond bounded, conservative local defaults.

Local read-only inspection is not permission to add a generic command runner, arbitrary
file reader, process enumerator, network scanner, or package manager wrapper.

4. Before/after semantics
-------------------------

Before Phase 2
~~~~~~~~~~~~~~

The MCP process is executable but advertises no Binnacle operational Tool.  It proves
only that packaging, settings, logging, composition, FastMCP, ASGI, and Uvicorn can be
assembled.

After Phase 2
~~~~~~~~~~~~~

The same process has a frozen read-only compatibility catalogue.  It can prove local MCP
Tool discovery/invocation, canonical result/error rendering, contract projection,
bounded host inspection, build/device identity, and protocol revision handling without
creating a consequential effect.

No authority is inferred from Tool visibility.  The server still has no remote
controller trust profile and therefore Phase 2 is a loopback-only local validation
server.

5. Exact repository changes
---------------------------

The Phase 2 **implementation** PR should create or modify the following paths.  This
planning PR itself adds only this document.

5.1 Existing package files to modify
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   pyproject.toml
   uv.lock
   src/binnacle/application.py
   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/cli.py
   src/binnacle/adapters/mcp.py
   src/binnacle/domain/runtime.py
   .github/workflows/python.yml

Phase 2 extends the Phase 1 ownership model; it does not create a second composition
root, CLI, settings hierarchy, MCP process, or logging configuration path.

5.2 New package files
~~~~~~~~~~~~~~~~~~~~~

::

   src/binnacle/contracts.py
   src/binnacle/domain/mcp.py
   src/binnacle/domain/system.py
   src/binnacle/ports/
     __init__.py
     device.py
     system.py
     compatibility.py
   src/binnacle/adapters/
     linux.py
     compatibility.py
   src/binnacle/bootstrap/
     __init__.py
     binnacle_probe.py
     system_inspect.py
     probe_result_formats.py
     probe_error.py
     compatibility_report.py
   src/binnacle/_generated/
     __init__.py
     compatibility_core_registry.json
     compatibility_core_registry.digest.json

The ``bootstrap`` package exists because the reviewed manifest already binds handlers to
paths such as ``binnacle.bootstrap.binnacle_probe.v1_1``.  Each module therefore exports
an async ``v1_1`` binding with exactly that import path.  These binding modules remain
thin and framework-independent; FastMCP types stay in ``adapters/mcp.py``.

5.3 New compiler and machine-readable revision contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   scripts/compile_mcp_registry.py
   spec/mcp/revision-support.yaml
   schemas/mcp/revision-support.schema.json

``spec/mcp/revision-support.yaml`` is the machine-readable projection of the finite
revision contract already defined by ``docs/mcp-revision-support.md``.  It does not add a
revision.  It must encode exactly:

::

   2026-07-28
   2025-11-25
   2025-06-18
   2025-03-26

with ``2026-07-28`` identified as the target/modern stateless profile and the three
others as supported legacy profiles.

The existing prose remains the human normative explanation.  Contract validation must
fail if the machine-readable set diverges from it or from the frozen evaluation setup.

5.4 Narrow schema correction discovered by Phase 2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current common ``identifier`` definition excludes ``-`` while the reviewed manifest
identity is ``binnacle-bootstrap-tools`` and ``binnacle_probe`` is required to return
that manifest identity through a field referencing ``identifier``.

The Phase 2 implementation must therefore make the narrow compatibility correction in:

::

   schemas/mcp/binnacle-common.schema.json
   scripts/validate_contracts.py
   tests/fixtures/mcp/schema-validation.yaml

Change the identifier pattern so ASCII hyphen is explicitly permitted while retaining
all existing length and first-character restrictions.  A suitable semantic form is:

.. code-block:: text

   ^[A-Za-z0-9][A-Za-z0-9_.:\-]*$

Add a positive fixture for ``binnacle-bootstrap-tools`` and negatives for whitespace,
slashes, control characters, leading punctuation, and Unicode-confusable forms.

Do not work around this contradiction by returning a renamed underscore manifest ID;
that would make runtime identity disagree with the reviewed source manifest.

5.5 New tests
~~~~~~~~~~~~~

Create at least:

::

   tests/unit/
     test_contracts.py
     test_domain_mcp.py
     test_domain_system.py
     test_linux_adapter.py
     test_compatibility_adapter.py
     test_bootstrap_binnacle_probe.py
     test_bootstrap_system_inspect.py
     test_bootstrap_probe_result_formats.py
     test_bootstrap_probe_error.py
     test_bootstrap_compatibility_report.py
   tests/integration/
     test_mcp_catalogue.py
     test_mcp_invocation.py
     test_mcp_revision_dispatch.py
     test_http_health_readiness.py
     test_generated_registry.py

No Phase 2 default test may require root, systemd, Git credentials, external network
access, a real Raspberry Pi, or real ChatGPT.

6. Dependency changes
---------------------

6.1 Existing runtime dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Keep the Phase 1 constraints for:

* ``fastmcp>=4,<5``;
* ``mcp>=2,<3``;
* Uvicorn;
* Pydantic v2 / pydantic-settings;
* Typer;
* Rich;
* structlog.

Do not loosen those compatibility lines merely because Phase 2 starts registering
Tools.  Resolve exact versions in ``uv.lock``.

6.2 New direct runtime dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``jsonschema`` as a direct runtime dependency because Phase 2 validates every
outgoing structured result against the compiled authoritative output schema before
serialization.

Add ``starlette`` as a direct runtime dependency only if the selected FastMCP 4.x public
ASGI API does not provide a clean supported way to compose ``/mcp``, ``/healthz``, and
``/readyz`` without a general-purpose wrapper.  Starlette is acceptable as a narrow ASGI
routing dependency; FastAPI is not introduced.

If FastMCP exposes supported custom-route/mount facilities that satisfy the same tests,
prefer those and do not add Starlette directly.

6.3 Build/development dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``PyYAML`` remains in the existing contract/development group and is used by
``scripts/compile_mcp_registry.py``.  Runtime does not parse source YAML; it loads the
compiled JSON bundle.

Add ``httpx`` to the test group if integration tests import it directly for raw HTTP/
ASGI protocol-negative cases.

No ``psutil`` dependency is required.  The Linux read adapter uses bounded standard
Linux/stdlib interfaces described below.

7. Compiled compatibility-core registry
---------------------------------------

7.1 Why compile
~~~~~~~~~~~~~~~

The checked-in YAML manifest and JSON Schemas remain authoritative editing sources, but
normal Tool invocation must not reparse YAML or resolve JSON Pointers repeatedly.

``scripts/compile_mcp_registry.py`` creates a deterministic package resource containing
only the runtime projection needed for ``compatibility-core`` plus the evidence required
to prove where it came from.

7.2 Compiler inputs
~~~~~~~~~~~~~~~~~~~

The compiler consumes:

::

   spec/mcp/bootstrap-tool-manifest.yaml
   spec/mcp/revision-support.yaml
   schemas/mcp/binnacle-common.schema.json
   schemas/mcp/bootstrap-inputs.schema.json
   schemas/mcp/bootstrap-outputs.schema.json
   spec/mcp/evaluation-profile.yaml
   spec/mcp/evaluation-cases.yaml

It selects the five entries whose ``phases`` include ``compatibility-core``.

7.3 Compiled registry shape
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Define one closed top-level JSON object with at least:

.. code-block:: json

   {
     "registry_format": "binnacle-compatibility-core-v1",
     "source_manifest": {
       "id": "binnacle-bootstrap-tools",
       "version": "1.1.0",
       "sha256": "..."
     },
     "schema_registry_sha256": "...",
     "revision_contract_sha256": "...",
     "evaluation_profile_version": "1.1.0",
     "supported_revisions": [],
     "tools": [],
     "schemas": {},
     "compatibility_baseline": {},
     "catalogue_sha256": "..."
   }

Each selected Tool entry contains the reviewed metadata plus resolved input/output schema
objects and the SHA-256 of each referenced schema definition.

The compiler must not rewrite descriptions, annotations, contract versions, information
class, confirmation class, or binding paths.

7.4 Deterministic canonicalization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Canonical generated bytes use:

* UTF-8;
* LF line endings;
* Unicode NFC strings;
* sorted JSON object keys;
* compact separators for digest input;
* one terminal newline in checked-in pretty JSON;
* SHA-256 over explicit canonical byte sequences.

``catalogue_sha256`` hashes the canonical selected Tool catalogue with the digest field
itself excluded.

7.5 Detached digest record
~~~~~~~~~~~~~~~~~~~~~~~~~~

``compatibility_core_registry.digest.json`` is outside the bytes hashed as the registry
and contains:

* registry SHA-256;
* source manifest SHA-256;
* schema registry SHA-256;
* revision contract SHA-256;
* catalogue SHA-256;
* compiler format/version.

It does not claim to be a production release attestation and does not include a
self-referential archive digest.  It is development/source-checkout integrity evidence
sufficient for Bootstrap Phase 2.

7.6 Compiler commands
~~~~~~~~~~~~~~~~~~~~~

Canonical commands are:

.. code-block:: console

   uv run python scripts/compile_mcp_registry.py
   uv run python scripts/compile_mcp_registry.py --check

``--check`` builds in memory and fails if either checked-in generated file differs byte
for byte.  CI always uses ``--check`` and never rewrites generated files.

8. Runtime contract registry
----------------------------

``binnacle.contracts`` owns immutable runtime registry types.

Expose types equivalent to:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class SchemaBinding:
       source_ref: str
       definition_sha256: str
       schema: Mapping[str, object]

   @dataclass(frozen=True, slots=True)
   class ToolContract:
       name: str
       title: str
       description: str
       contract_version: str
       handler_binding: str
       information_class: str
       confirmation_class: str
       annotations: Mapping[str, bool]
       input_schema: SchemaBinding
       output_schema: SchemaBinding

   @dataclass(frozen=True, slots=True)
   class ContractRegistry:
       manifest_id: str
       manifest_version: str
       manifest_sha256: str
       schema_registry_sha256: str
       catalogue_sha256: str
       supported_revisions: tuple[str, ...]
       tools: Mapping[str, ToolContract]

       @classmethod
       def load(cls) -> "ContractRegistry": ...
       def validate_output(self, tool_name: str, value: Mapping[str, object]) -> None: ...

``load()`` reads package resources through ``importlib.resources`` rather than current
working directory paths.

Startup validation must:

#. recompute the generated registry SHA-256 and compare with its detached record;
#. verify exactly five visible compatibility-core Tool names;
#. verify every selected schema is valid JSON Schema 2020-12;
#. prebuild output validators;
#. import every visible ``handler_binding`` and confirm it resolves to an async callable;
#. verify no write-probe binding is visible;
#. verify the finite revision set exactly matches the machine-readable contract;
#. fail startup/readiness on any mismatch.

9. Framework-independent MCP domain types
----------------------------------------

``binnacle.domain.mcp`` owns no FastMCP/Pydantic/jsonschema types.

Define at least:

.. code-block:: python

   class ProtocolEra(StrEnum):
       MODERN = "modern"
       LEGACY = "legacy"

   class CataloguePhase(StrEnum):
       COMPATIBILITY_CORE = "compatibility-core"

   @dataclass(frozen=True, slots=True)
   class McpCallContext:
       revision: str
       era: ProtocolEra
       request_id: str

   @dataclass(frozen=True, slots=True)
   class ToolIdentity:
       name: str
       contract_version: str

   @dataclass(frozen=True, slots=True)
   class WarningRecord:
       code: str
       message: str

   @dataclass(frozen=True, slots=True)
   class BinnacleError:
       code: str
       message: str
       retryable: bool
       retry_action: str
       operation_id: None
       details: tuple[DiagnosticFact, ...]

Use a generic immutable success envelope and an immutable execution-error envelope.
Every Phase 2 envelope has ``operation=None`` because no durable operation kernel exists.
Evidence is an empty tuple unless a Tool has a bounded server-observed fact that already
matches the reviewed evidence schema; do not invent audit references.

The envelope serializer converts domain dataclasses to ordinary JSON-compatible objects,
then ``ContractRegistry.validate_output`` validates the final structure before the MCP
adapter sees it.

10. Typed Tool request/result models
------------------------------------

10.1 Requests
~~~~~~~~~~~~~

Define immutable dataclasses matching the five reviewed input schemas:

``BinnacleProbeRequest``
   No fields.

``SystemInspectRequest``
   ``sections: tuple[SystemSection, ...] | None``.

``ProbeResultFormatsRequest``
   ``include_warning: bool = False``;
   ``nullable_value: str | None = None``;
   ``array_length: int = 3``.

``ProbeErrorRequest``
   ``case: ProbeErrorCase``;
   ``delay_ms: int | None`` with the same conditional rule as the schema.

``CompatibilityReportRequest``
   No fields.

The MCP adapter first validates model-supplied arguments against the exact compiled input
schema, then converts to these types.  Typed conversion may be explicit functions rather
than Pydantic models so application/domain layers remain independent of Pydantic.

10.2 Tool-specific data
~~~~~~~~~~~~~~~~~~~~~~~

Define immutable result data types for:

* ``BinnacleProbeData``;
* ``SystemInspectData``;
* ``ProbeResultFormatsData``;
* ``ProbeErrorDelayData``;
* ``CompatibilityReportData``.

Their field names and optionality must map one-for-one to the existing output schema.
Do not add convenient fields that the schema cannot serialize.

11. Request correlation identity
--------------------------------

The canonical output schema requires an identifier-shaped ``request_id``.  JSON-RPC IDs
may be numbers or arbitrary strings and therefore are not reused directly.

For each Tool call, the MCP adapter creates a local correlation ID using cryptographic
randomness:

.. code-block:: text

   req_<32 lowercase hex characters>

This value satisfies the common identifier schema and is used as:

* the envelope ``request_id``;
* ``binnacle_probe.data.request_correlation_id``;
* structured log correlation for that Tool call.

The raw bearer credential, future controller identity, or conversation ID never enters
this value.

12. Build identity
------------------

Extend ``binnacle.domain.runtime`` with:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class BuildIdentity:
       version: str
       build_sha256: str

``build_sha256`` in source-checkout development is a deterministic development-build
fingerprint, not a release-artifact attestation.

The Phase 2 adapter computes it once at composition time by hashing the canonical ordered
set of:

* all ``*.py`` files under the installed/editable ``binnacle`` package root;
* the two generated compatibility-core registry resources.

For each file, hash ``relative_posix_path + NUL + sha256(file_bytes)`` and feed the
ordered records into one SHA-256 accumulator.  Ignore ``__pycache__``, bytecode, editor
files, and filesystem metadata.

The package version remains the Phase 1 distribution version.  No Git command is run and
no branch/dirty-state claim is made in Phase 2.

13. Device identity
-------------------

``binnacle.ports.device`` defines the first real device-identification port:

.. code-block:: python

   class DeviceIdentityProvider(Protocol):
       def get_device_identity(self) -> DeviceIdentity: ...

``binnacle.domain.system`` owns:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class DeviceIdentity:
       device_id: str

``LinuxDeviceIdentityProvider`` in ``adapters/linux.py`` uses ``/etc/machine-id`` when
available but never returns or logs the raw machine ID.  It computes:

.. code-block:: text

   sha256("binnacle-device-id-v1\0" || raw_machine_id)

and returns ``device_<first 32 hex chars>``.

If ``/etc/machine-id`` is unavailable, the provider may use another stable local
machine-identity source only after normalising it through the same one-way domain-
separated digest.  If no stable source exists, application readiness fails rather than
fabricating a random identity that changes each process start.

14. Bounded Linux system inspection
-----------------------------------

14.1 Port
~~~~~~~~~

``binnacle.ports.system`` defines:

.. code-block:: python

   class SystemInspector(Protocol):
       def inspect(self, sections: tuple[SystemSection, ...]) -> SystemSnapshot: ...

No method accepts an arbitrary command, path, process ID, interface, package, service
name, or device node.

14.2 Domain types
~~~~~~~~~~~~~~~~~

``binnacle.domain.system`` owns:

* ``SystemSection`` enum with exactly the eight schema values;
* ``CpuInfo``;
* ``MemoryInfo``;
* ``FilesystemInfo``;
* ``BinnacleServiceInfo``;
* ``SystemSnapshot``;
* inspection warnings.

14.3 Default sections
~~~~~~~~~~~~~~~~~~~~~

When ``system_inspect.sections`` is omitted, use exactly:

::

   os
   kernel
   architecture
   uptime
   cpu
   memory

``filesystems`` and ``binnacle_service`` are returned only when explicitly requested.
This keeps the default result small and deterministic.

14.4 Linux implementation
~~~~~~~~~~~~~~~~~~~~~~~~~

``LinuxSystemInspector`` uses bounded read-only sources:

``os``
   Parse selected public fields from ``/etc/os-release`` and return one bounded summary
   string.  Do not return the entire file or environment.

``kernel`` and ``architecture``
   Use ``platform.uname()`` / ``platform.machine()``.

``uptime``
   Read the first numeric field from ``/proc/uptime`` and return integer seconds.

``cpu``
   Use ``os.cpu_count()`` and reject/convert ``None`` to a deterministic execution
   error rather than inventing a count.

``memory``
   Parse only ``MemTotal`` and ``MemAvailable`` from ``/proc/meminfo`` and convert KiB
   to bytes with checked non-negative integer arithmetic.

``filesystems``
   Parse mount points/filesystem type/source from ``/proc/self/mountinfo`` and obtain
   total/available bytes with ``os.statvfs``.  Sort by mount point.  Return at most 128
   entries.  If more eligible entries exist, return 128 and add the envelope warning
   ``filesystem_list_truncated``; truncation is never silent.

``binnacle_service``
   Phase 2 has no systemd deployment contract.  Return ``state="unknown"`` plus warning
   ``service_manager_not_integrated``.  Do not invoke a general subprocess solely to
   make local tests look more complete.

All file reads use explicit maximum byte budgets and fail as bounded execution errors on
unexpected size/format rather than returning partial unlabelled data.

15. Static compatibility-profile reader
---------------------------------------

``binnacle.ports.compatibility`` defines:

.. code-block:: python

   class CompatibilityProfileReader(Protocol):
       def read(self) -> CompatibilityProfileSnapshot: ...

``CompiledCompatibilityProfileReader`` in ``adapters/compatibility.py`` reads only the
baseline embedded in the generated registry.  Phase 2 has no live host evidence bundle
and therefore must not report any ChatGPT feature as observed-supported.

The compiler derives the baseline axis list from the frozen evaluation cases and records
status values using the repository's exact canonical vocabulary.

Rules before real-host evidence exists:

* axes whose server-side compatibility-core probe exists but require host observation ->
  ``not-tested``;
* write/idempotency/cancellation/reconnect axes whose server capability is absent ->
  ``server-not-implemented``;
* optional unpromoted Resources/MRTR/Tasks-style probes -> ``not-applicable``;
* ``observed_protocol_revision`` -> ``null``;
* ``evidence_bundle_sha256`` -> ``null``;
* limitations explicitly state that only local compatibility-core evidence exists.

Local test-client success must never be promoted into ChatGPT evidence.

16. Application/use-case ownership
----------------------------------

Phase 2 extends ``BinnacleApplication`` with a concrete compatibility use-case object.

Expose an application-layer API equivalent to:

.. code-block:: python

   class CompatibilityUseCases:
       async def binnacle_probe(
           self,
           request: BinnacleProbeRequest,
           context: McpCallContext,
       ) -> SuccessEnvelope[BinnacleProbeData]: ...

       async def system_inspect(
           self,
           request: SystemInspectRequest,
           context: McpCallContext,
       ) -> SuccessEnvelope[SystemInspectData]: ...

       async def probe_result_formats(...): ...
       async def probe_error(...) -> SuccessEnvelope[ProbeErrorDelayData] | ExecutionErrorEnvelope: ...
       async def compatibility_report(...): ...

Constructor dependencies are explicit:

* ``BuildIdentity``;
* ``DeviceIdentityProvider``;
* ``SystemInspector``;
* ``CompatibilityProfileReader``;
* ``ContractRegistry``.

The use-case layer does not import FastMCP, Uvicorn, Starlette, Typer, Pydantic, PyYAML,
or Linux-specific adapter modules.

17. Exact Tool behaviour
------------------------

17.1 ``binnacle_probe``
~~~~~~~~~~~~~~~~~~~~~~~

Return the exact schema fields:

* ``build_version`` from ``BuildIdentity.version``;
* ``build_sha256`` from ``BuildIdentity.build_sha256``;
* ``device_id`` from ``DeviceIdentityProvider``;
* ``protocol_revision`` from the current ``McpCallContext``;
* ``protocol_era`` from the selected revision contract;
* ``tool_manifest.id/version/sha256`` from ``ContractRegistry``;
* ``catalogue_phase="compatibility-core"``;
* ``catalogue_sha256`` from the compiled registry;
* ``request_correlation_id`` equal to the envelope ``request_id``.

It performs no broad host inspection.

17.2 ``system_inspect``
~~~~~~~~~~~~~~~~~~~~~~~

Normalise the requested section order to the canonical ``SystemSection`` order so the
same logical request produces stable output ordering.

Return hostname using ``socket.gethostname()`` bounded to the schema limit plus only the
requested/default sections.

A failure to collect one requested mandatory section is a Tool execution error for the
call; do not silently omit it from ``returned_sections``.  The only documented degraded
section in Phase 2 is ``binnacle_service=unknown`` because service-manager integration is
explicitly absent.

17.3 ``probe_result_formats``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Return deterministic values:

* ``string_value="binnacle-result-format-probe"``;
* ``integer_value=42``;
* ``boolean_value=true``;
* ``nullable_value`` copied from validated input;
* ``array_values`` equal to integers ``0..array_length-1``;
* ``nested={"name":"nested","enabled":true}``;
* ``warning_included`` equal to input.

When ``include_warning=true``, add exactly one warning with code
``synthetic_probe_warning``.  No random payload is used so result-rendering tests can use
stable expected values.

17.4 ``probe_error``
~~~~~~~~~~~~~~~~~~~~

``bounded_delay``
   Await ``asyncio.sleep(delay_ms / 1000)`` and return the schema-defined success data.
   The input schema limits delay to 10 seconds.

``invalid_input``
   Return a synthetic execution error with code ``synthetic_invalid_input``.  Actual
   schema-invalid model arguments still fail at the MCP/schema validation layer before
   this handler; this case exists only to test execution-error rendering.

``policy_rejection``
   Return code ``policy_rejected``.

``known_execution_failure``
   Return code ``known_execution_failure``.

``timeout``
   Return code ``synthetic_timeout`` with ``retryable=false`` and
   ``retry_action="none"``.  Do not deliberately stall the server beyond the bounded
   probe contract.

``uncertain_outcome``
   Return code ``synthetic_uncertain_outcome`` with ``retryable=false`` and
   ``retry_action="reconcile"``.  ``operation`` remains ``null`` because Phase 2 has no
   durable operation and this synthetic probe must not fabricate one.

17.5 ``compatibility_report``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Return only the compiled no-live-evidence baseline described above.  It never reads raw
HTTP headers, credentials, cookies, owner-private data, or arbitrary files.

18. Manifest binding modules
----------------------------

Each ``binnacle.bootstrap.<tool>.v1_1`` binding has framework-independent arguments:

.. code-block:: python

   async def v1_1(
       *,
       use_cases: CompatibilityUseCases,
       request: ToolRequest,
       context: McpCallContext,
   ) -> ToolEnvelope:
       ...

The function delegates once to the matching use case and contains no FastMCP decorator,
settings lookup, global singleton, filesystem access, or protocol parsing.

``ContractRegistry.load`` imports these exact paths during readiness validation.  This
makes the reviewed ``handler_binding`` field executable rather than decorative.

19. MCP adapter and Tool registration
-------------------------------------

19.1 Adapter responsibilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``binnacle.adapters.mcp`` owns:

* FastMCP server construction;
* ASGI construction;
* revision/request context extraction;
* Tool registration from ``ContractRegistry``;
* argument schema validation and typed conversion;
* invocation of the imported manifest binding;
* canonical output validation;
* conversion to FastMCP Tool result content/``structuredContent``/``isError``;
* protocol-layer errors before Tool dispatch;
* health/readiness HTTP routes.

It does not own Tool semantics or Linux inspection logic.

19.2 Registration algorithm
~~~~~~~~~~~~~~~~~~~~~~~~~~~

At server construction:

#. load the already-validated ``ContractRegistry``;
#. assert catalogue phase is exactly ``compatibility-core``;
#. iterate the five Tool contracts in manifest order;
#. import the exact handler binding;
#. register reviewed title/description/annotations without rewriting text;
#. register the exact compiled input and output schemas through the supported FastMCP
   public API;
#. attach one wrapper that injects use cases and call context;
#. fail construction if FastMCP cannot represent the reviewed schema/metadata faithfully.

Do not derive the authoritative schema from Python function annotations and then compare
loosely.  The manifest-resolved JSON Schema is the source of truth.

19.3 Input validation
~~~~~~~~~~~~~~~~~~~~~

Even if FastMCP/SDK performs JSON Schema validation, the wrapper validates the received
arguments against the compiled input schema before typed conversion.  This is defense in
depth and protects against framework configuration drift.

Invalid inputs never invoke the application binding.

19.4 Output validation
~~~~~~~~~~~~~~~~~~~~~~

Before returning any Tool result:

#. serialize the domain envelope to a JSON-compatible mapping;
#. validate it against the exact Tool output schema;
#. produce bounded model-readable text from the validated mapping;
#. set structured content to the validated mapping;
#. set ``isError`` from ``call_status``;
#. refuse to send malformed structured success/error data.

An internal output-schema failure becomes a bounded server/internal Tool error and logs
the schema failure location without logging the rejected payload.

20. Model-readable text projection
----------------------------------

Every result includes structured content plus concise deterministic text.

Text rules:

* never exceed 4 KiB in Phase 2;
* never dump the full schema or manifest;
* never include raw machine ID;
* preserve the primary error code/message for execution errors;
* include warnings by code, not by serializing all internal objects;
* remain semantically consistent with structured content.

Tests compare the text projection with the structured result for key facts.

21. MCP revision support
------------------------

21.1 Finite set
~~~~~~~~~~~~~~~

The runtime accepts only the four repository-declared revisions.  One request is handled
under exactly one revision.

``2026-07-28`` maps to ``ProtocolEra.MODERN``.  The three older revisions map to
``ProtocolEra.LEGACY``.

21.2 Framework-first implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use FastMCP 4.x / official MCP SDK 2.x public support for lifecycle, Streamable HTTP,
JSON-RPC, Tool listing, Tool calls, and target/legacy result shapes.

Do not build a second MCP server or fork the protocol parser merely to imitate a revision.
The implementation must select a FastMCP 4.x/SDK 2.x lock combination that genuinely
supports the required repository revision contract.

If a required revision cannot be represented by that reviewed framework line, Phase 2
implementation is blocked and must update the compatibility assumption explicitly rather
than silently accepting a different wire contract.

21.3 Narrow revision guard
~~~~~~~~~~~~~~~~~~~~~~~~~~

A small ASGI pre-dispatch guard may enforce Binnacle-specific finite-set/header integrity
that the framework does not enforce itself.  It may:

* reject missing/malformed/unsupported protocol versions under the documented rules;
* reject target-era ``Mcp-Method``/``Mcp-Name`` mismatches;
* reject legacy/modern session-header misuse;
* populate a request-local ``McpCallContext`` for Tool handlers.

It must not implement Tool dispatch, authentication, JSON-RPC method execution, session
storage, or an alternate protocol lifecycle.

Target-era body inspection, if required for header/body integrity, buffers at most the
configured request-body limit and faithfully replays the bytes to FastMCP after
validation.

22. HTTP/ASGI surface
---------------------

22.1 Paths
~~~~~~~~~~

Expose exactly:

``/mcp``
   FastMCP Streamable HTTP endpoint.

``/healthz``
   Process liveness only.

``/readyz``
   Compatibility-core readiness only.

Do not expose a general REST API, debug endpoint, metrics endpoint, schema browser, admin
route, or generated API documentation.

22.2 ``/healthz``
~~~~~~~~~~~~~~~~~

Return HTTP 200 with a minimal JSON body equivalent to:

.. code-block:: json

   {"status":"healthy"}

It does not inspect the host, contracts, or external services.

22.3 ``/readyz``
~~~~~~~~~~~~~~~~

Return 200 only when:

* ``BinnacleApplication`` is started;
* contract registry digest verification passed;
* exactly five compatibility-core bindings are loaded;
* build identity is available;
* device identity is available;
* MCP adapter construction succeeded.

Otherwise return 503 with a small safe code list such as:

.. code-block:: json

   {"status":"not_ready","reasons":["contract_registry_invalid"]}

Do not return stack traces, filesystem paths, environment values, schemas, raw digests,
or credentials.

22.4 Loopback-only rule
~~~~~~~~~~~~~~~~~~~~~~~

Because remote controller authentication is deliberately absent in Phase 2, ``serve``
must refuse non-loopback bind targets.

Accepted canonical bind addresses are ``127.0.0.1`` and ``::1``.  Do not treat an
arbitrary hostname that happens to resolve to loopback as equivalent, and do not provide
an ``--allow-unauthenticated-nonloopback`` escape hatch.

This intentionally tightens the Phase 1 generic explicit-bind skeleton once real Tools
exist.

23. Configuration additions
----------------------------

Extend ``ServerSettings`` only with fields Phase 2 genuinely uses:

.. code-block:: python

   class ServerSettings(BaseModel):
       host: str = "127.0.0.1"
       port: int = Field(default=8000, ge=1, le=65535)
       workers: Literal[1] = 1
       max_request_bytes: int = Field(default=1_048_576, ge=65_536, le=4_194_304)
       graceful_shutdown_seconds: float = Field(default=10.0, gt=0, le=60)

The supported MCP revision set, Tool catalogue phase, manifest path, schema paths,
handler bindings, and security boundaries are **not** ordinary environment/CLI settings.
They come from the reviewed compiled contracts and cannot be expanded with
``BINNACLE_*`` variables.

24. Application lifecycle
-------------------------

Phase 2 lifecycle order is:

Startup
   #. load/validate settings;
   #. configure logging;
   #. load/verify contract registry;
   #. compute build identity;
   #. initialise device and system read adapters;
   #. construct compatibility profile reader;
   #. construct ``CompatibilityUseCases``;
   #. construct/start ``BinnacleApplication``;
   #. construct FastMCP/ASGI adapter and five Tool bindings;
   #. mark readiness true;
   #. enter Uvicorn serving loop.

Shutdown
   #. mark readiness false;
   #. stop accepting new server work through Uvicorn lifecycle;
   #. await in-flight bounded Tool calls up to the graceful timeout;
   #. stop ``BinnacleApplication``;
   #. close logging runtime;
   #. exit foreground process.

No background operation survives process shutdown in Phase 2 because no durable
operation or executor exists.

25. Composition root changes
----------------------------

Extend ``ComposedApplication`` with explicit Phase 2 dependencies:

.. code-block:: python

   @dataclass(slots=True)
   class ComposedApplication:
       settings: BinnacleSettings
       application: BinnacleApplication
       contracts: ContractRegistry
       compatibility: CompatibilityUseCases
       logging_runtime: LoggingRuntime

``compose_application`` constructs concrete Linux/read-only adapters once and injects
them into ``CompatibilityUseCases``.  Tests may call a narrower constructor that injects
fake ports directly.

Do not use monkeypatching or global registries as the normal dependency-injection
mechanism.

26. Import/dependency direction
-------------------------------

Update Import Linter rules so:

* ``binnacle.domain`` remains stdlib-only;
* ``binnacle.ports`` may import ``binnacle.domain`` only;
* ``binnacle.application`` may import domain, ports, and ``binnacle.contracts`` but not
  adapters/FastMCP/Uvicorn/Typer/Rich;
* ``binnacle.bootstrap`` may import application/domain types but not FastMCP;
* ``binnacle.adapters`` implements ports and may import required vendor/OS libraries;
* ``binnacle.contracts`` may import jsonschema and package-resource facilities but not
  FastMCP or CLI;
* ``binnacle.cli`` remains outer adaptation;
* ``binnacle.composition`` remains the outer composition root and no inward module
  imports it.

27. Error taxonomy for Phase 2
------------------------------

Define framework-independent exceptions/types for:

``ContractRegistryError``
   Generated registry/digest/schema/binding mismatch; startup/readiness failure.

``InputContractError``
   Arguments fail the exact compiled Tool input schema; MCP Tool validation failure before
   use-case invocation.

``OutputContractError``
   Application result fails its exact output schema; internal server failure and no
   malformed success is sent.

``InspectionError``
   A bounded requested host fact cannot be collected truthfully.

``ToolExecutionFailure``
   Application-level execution-error envelope information for synthetic/read failures.

Protocol revision errors remain protocol errors defined by the revision contract and do
not become Tool execution-error envelopes.

28. Logging and diagnostics
---------------------------

Phase 2 logs bounded structured events for:

* application start/stop;
* registry load success/failure with safe digest prefixes only where useful;
* MCP request start/end using local request correlation ID;
* selected Tool name and contract version;
* selected MCP revision/era;
* Tool call success/execution-error/internal-error;
* health/readiness state transitions;
* bounded inspection warning codes.

Do not log:

* raw request headers;
* authorization values;
* cookies;
* complete Tool input/output payloads;
* raw ``/etc/machine-id``;
* environment dumps;
* full schema bodies;
* stack traces in model-visible Tool text.

There is still no authoritative audit journal in Phase 2.

29. CLI ``serve`` integration
-----------------------------

Keep the existing ``binnacle serve`` command and extend its implementation rather than
adding a second server command.

The command:

#. loads settings;
#. rejects non-loopback host;
#. composes Phase 2 application dependencies;
#. constructs the MCP/HTTP app;
#. runs one Uvicorn worker in the foreground;
#. propagates normal SIGINT/SIGTERM shutdown through the lifecycle above.

``binnacle config validate`` must validate the new request-size/shutdown fields.
``binnacle version`` remains side-effect free.

No CLI command directly invokes ``system_inspect`` or the synthetic probes in Phase 2;
the compatibility surface is intentionally tested through MCP.

30. Local MCP client integration tests
--------------------------------------

30.1 Framework client path
~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the official MCP Python SDK test/client primitives to connect to the local ASGI/
loopback server through Streamable HTTP.

The test must perform real MCP discovery and invocation rather than calling binding
functions directly.

30.2 Discovery test
~~~~~~~~~~~~~~~~~~~

``test_local_client_lists_exact_compatibility_core`` asserts exactly five Tool names and
no write-probe Tool.

For each Tool compare:

* title;
* description;
* annotations;
* contract version metadata where projected;
* input schema;
* output schema.

The expected values come from the compiled registry, which is independently checked
against source manifest bytes by compiler tests.

30.3 Invocation tests
~~~~~~~~~~~~~~~~~~~~~

Invoke each Tool through MCP and validate:

* ``content`` exists and is bounded;
* structured content is present;
* ``isError`` is correct;
* output validates against the exact source-derived schema;
* Tool identity/contract version match;
* operation is ``null``;
* no undeclared field appears.

30.4 Error rendering test
~~~~~~~~~~~~~~~~~~~~~~~~~

Invoke ``probe_error(case="policy_rejection")`` and assert transport/MCP request success
with Tool ``isError=true`` and canonical ``execution_error`` structured content.

Separately send schema-invalid input and assert the handler binding was not called.

31. Revision-dispatch integration tests
---------------------------------------

For each supported revision, include a positive local fixture reaching Tool listing and
``binnacle_probe`` under the correct era behavior.

Negative tests include:

* unsupported ``2024-11-05``;
* missing version where not permitted;
* modern request carrying legacy session state;
* legacy post-initialization wrong version header;
* target ``Mcp-Method`` mismatch;
* target ``Mcp-Name`` mismatch for Tool call;
* cross-era result-shape contamination;
* disabled Tasks/unsupported extension request.

A negative passes only when it reaches the intended validation layer.  A malformed JSON
request that fails before revision validation is not evidence that revision validation
works.

32. Health/readiness tests
--------------------------

Required tests:

``test_health_is_200_before_optional_subsystems``
   Liveness is independent from Tool readiness.

``test_ready_is_503_when_registry_digest_mismatches``
   Corrupt generated registry fixture prevents readiness.

``test_ready_is_503_when_handler_binding_missing``
   A visible manifest binding cannot be imported.

``test_ready_is_200_with_exact_five_bindings``
   Fully composed local server is ready.

``test_nonloopback_serve_is_rejected``
   ``0.0.0.0`` and representative LAN addresses fail before Uvicorn starts.

33. Contract/compiler tests
---------------------------

Required tests prove:

* compiler output is deterministic;
* ``--check`` detects drift;
* exactly five source-manifest entries project into compatibility-core;
* source descriptions/annotations are byte/semantic equivalent after projection;
* every JSON Pointer resolves;
* definition digests change when their schema changes;
* generated registry digest excludes its detached record;
* all five handler bindings import;
* write-probe bindings are absent from runtime registration;
* revision machine contract equals the finite prose/evaluation set;
* ``binnacle-bootstrap-tools`` validates under corrected ``identifier`` schema;
* invalid/confusable identifiers remain rejected.

34. Tool unit tests
-------------------

34.1 ``binnacle_probe``
~~~~~~~~~~~~~~~~~~~~~~~

Use fake build/device/context values and assert exact mapping, including equal envelope
request ID and ``request_correlation_id``.

34.2 ``system_inspect``
~~~~~~~~~~~~~~~~~~~~~~~

Test default section set, explicit section subset, canonical ordering, collection
failure, filesystem truncation warning, and service-manager unknown warning.

Use temporary fixture files/parser inputs rather than depending on the CI runner's real
``/proc`` content for parser unit tests.

34.3 ``probe_result_formats``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Property-style parameter cases are not required yet; table-test array lengths 0, 1, 3,
and 16 plus null/string values and warning enabled/disabled.

34.4 ``probe_error``
~~~~~~~~~~~~~~~~~~~~

Cover every enum case and ensure only bounded-delay returns success.

34.5 ``compatibility_report``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assert no status is ``observed-supported`` or ``observed-limited`` in the Phase 2 static
baseline and no evidence digest is fabricated.

35. Security invariants
-----------------------

Phase 2 implementation must preserve all of these invariants:

#. the network listener is loopback-only because controller authentication is absent;
#. Tool visibility never grants authority beyond the five read-only contracts;
#. no write-probe Tool is registered;
#. no general command/subprocess interface is exposed;
#. no arbitrary filesystem path comes from model input;
#. host inspection reads only fixed implementation-owned sources;
#. raw machine identity is one-way transformed before result/log use;
#. manifest/schema metadata comes only from the reviewed compiled registry;
#. runtime filtering can remove but never rewrite Tool semantics;
#. every Tool input is validated before application invocation;
#. every structured output is validated before serialization;
#. protocol/authentication-style failures are not mislabeled as Tool execution errors;
#. no credential, cookie, authorization header, or private key handling is introduced;
#. no persistent operation/audit claim is made;
#. no local test result is presented as real ChatGPT compatibility evidence;
#. health/readiness endpoints expose only minimal safe status;
#. a malformed/oversized target-era body cannot force unbounded middleware buffering;
#. shutdown cannot leave a Phase 2 managed consequential effect because none exists.

36. Quality and CI changes
--------------------------

Extend ``.github/workflows/python.yml`` without creating a parallel Phase 2 workflow.

The authoritative quality job additionally runs:

.. code-block:: console

   uv run python scripts/compile_mcp_registry.py --check
   python scripts/validate_contracts.py
   python scripts/validate_schema_instances.py

The test matrix continues to run 3.11, 3.12, and 3.13 with explicit interpreter
selection from the Phase 1 correction.

The Python workflow must execute the new integration tests on loopback.  It must not need
Internet access after dependencies are installed and must not require privileged ports.

Keep Ruff, strict MyPy, Import Linter, coverage, ``pip-audit``, and existing contract
validation hard gates.

37. Canonical local validation command set
-----------------------------------------

The Phase 2 implementation PR must document and pass:

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
   python scripts/validate_contracts.py
   python scripts/validate_schema_instances.py

Also run the local MCP integration test target explicitly if the implementation separates
it with a marker, for example:

.. code-block:: console

   uv run pytest -m mcp_integration

38. Implementation ordering
---------------------------

Implement Phase 2 in this order:

#. add the machine-readable finite revision contract/schema and narrow identifier fix;
#. implement ``compile_mcp_registry.py`` and deterministic generated bundle;
#. add compiler/contract tests and make ``--check`` green;
#. implement immutable MCP/system domain types;
#. introduce the device/system/compatibility ports;
#. implement Linux device/system read adapters;
#. implement compiled compatibility-profile reader;
#. extend build identity;
#. implement ``CompatibilityUseCases``;
#. implement the five exact manifest binding modules;
#. extend MCP adapter registration/input/output projection;
#. implement revision request context/guard using framework-first behaviour;
#. add ``/healthz`` and ``/readyz``;
#. enforce loopback-only serve;
#. extend composition/lifecycle;
#. add local MCP discovery/invocation tests;
#. add revision/error/health/readiness negative tests;
#. update import/quality/CI configuration;
#. regenerate ``uv.lock`` only for genuine direct dependency changes;
#. run the complete validation set;
#. open the implementation PR with evidence mapped to the acceptance checklist.

Do not postpone output-schema validation or manifest integrity until after Tool handlers
are written; those are foundational Phase 2 boundaries.

39. Review checklist
--------------------

A reviewer should verify:

* Phase 1 framework/dependency decisions are consumed, not duplicated;
* only five compatibility-core Tools are visible;
* all Tool metadata and schemas originate from the reviewed source manifest;
* the hyphen/identifier contradiction is corrected rather than hidden;
* runtime does not parse YAML on each request;
* generated registry is deterministic and CI-checked;
* every visible handler binding resolves to the exact manifest path;
* application/domain code imports no FastMCP/Uvicorn types;
* Linux inspection accepts no arbitrary path/command target from MCP input;
* system inspection is bounded and truncation is explicit;
* build identity is deterministic and does not pretend to be Git identity;
* device ID does not expose raw machine ID;
* compatibility report contains no fabricated host evidence;
* modern/legacy revision context is explicit per request;
* FastMCP/SDK remains the real protocol implementation;
* input and output schemas are enforced at runtime;
* synthetic execution errors are distinguishable from protocol errors;
* health/readiness semantics are separate;
* server cannot bind non-loopback while unauthenticated;
* no write/durable/Git/privileged/credential/hardware capability enters the diff;
* all exact-head CI gates pass.

40. Deterministic acceptance checklist
--------------------------------------

Phase 2 implementation is accepted only when every item below is true:

#. ``spec/mcp/revision-support.yaml`` contains exactly the four reviewed revisions;
#. the common identifier schema accepts the real reviewed manifest ID while retaining
   negative identifier protections;
#. generated compatibility-core registry and detached digest record are checked in;
#. compiler ``--check`` passes from a clean checkout;
#. generated registry contains exactly five Tool entries;
#. every selected source schema reference resolves and has a recorded definition digest;
#. every selected handler binding imports as an async callable;
#. ``ContractRegistry.load`` fails closed on registry/digest/schema/binding drift;
#. deterministic development ``BuildIdentity`` is available without Git commands;
#. device identity is stable for one machine and does not reveal raw machine ID;
#. ``system_inspect`` uses only bounded implementation-owned read sources;
#. ``binnacle_service`` is truthful ``unknown`` until service integration exists;
#. ``binnacle_probe`` validates against its exact output schema;
#. ``system_inspect`` validates against its exact output schema;
#. ``probe_result_formats`` validates against its exact output schema;
#. every ``probe_error`` execution-error case validates against its exact output schema;
#. ``compatibility_report`` validates against its exact output schema;
#. local MCP discovery returns exactly the five compatibility-core names;
#. local MCP invocation succeeds for all five Tools;
#. model-readable text and structured content are both present and consistent;
#. execution-error responses use ``isError=true``;
#. schema-invalid Tool input never invokes the application binding;
#. output-schema failure cannot be sent as a success;
#. all four supported revisions have a positive local dispatch fixture at the intended
   validation layer;
#. unsupported/cross-era/header-mismatch negatives fail at the correct layer;
#. ``/healthz`` returns minimal HTTP 200 liveness;
#. ``/readyz`` is 503 before/after readiness failure and 200 only for valid composition;
#. ``serve`` refuses ``0.0.0.0`` and LAN/non-loopback bind targets;
#. no write-probe Tool is registered or callable;
#. no persistence, command execution, Git mutation, privileged operation, credential
   authority, or hardware capability exists in the implementation diff;
#. local compatibility results are not written into the real ChatGPT evidence profile as
   observed support;
#. Ruff and Ruff format checks pass;
#. strict MyPy passes;
#. Import Linter passes;
#. ``pip-audit`` passes or has a separately reviewed explicit advisory exception;
#. branch-inclusive coverage remains at or above the Phase 1 threshold;
#. Python 3.11, 3.12, and 3.13 test lanes pass with their explicit interpreters;
#. repository contract/schema validation passes;
#. GitHub Actions is green for the exact implementation head.

41. Planning stop rule for Phase 2
---------------------------------

This plan is intentionally complete enough for a coding agent to build and locally test
the read-only compatibility server without making new architectural decisions about Tool
identity, manifest projection, schemas, result envelopes, Linux inspection, protocol
revision context, readiness, or package ownership.

Do not extend this document into remote deployment, real-host evidence collection,
production controller authentication, write entitlement, durable operations, or
self-hosting.  Those require later evidence/implementation gates and are outside the
Phase 2 acceptance boundary.
