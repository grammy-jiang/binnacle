Binnacle Target Architecture
============================

:Status: Owner-approved target direction; not all items are Bootstrap requirements
:Depends on: ``design-principles.rst`` and ``bootstrap-v1.rst``
:Purpose: Preserve the intended long-term architecture while allowing Bootstrap V1 to remain minimal

Purpose
-------

This document records architectural and technology directions that have been agreed but
do not all need to exist before the first ChatGPT self-hosting milestone.

The Bootstrap implementation should establish the seams that make these directions
possible without attempting to build the complete target system in advance.

1. Product boundary
-------------------

Binnacle remains one deterministic MCP server per Raspberry Pi/Linux device.

ChatGPT remains the sole reasoning/planning agent. Binnacle owns deterministic local
execution, observation, policy, durable operation lifecycle, evidence, and recovery
behaviour for its own device.

Long-term capability domains are:

* software engineering;
* Linux host administration;
* Raspberry Pi board hardware;
* official Raspberry Pi peripherals/accessories;
* selected third-party devices/integrations;
* Binnacle self-development and self-management.

Binnacle does not become a local AI agent or fleet reasoning service.

2. Supported platform direction
-------------------------------

Long-term Linux-family targets include:

* Raspberry Pi OS;
* Debian/Ubuntu;
* Fedora;
* RHEL/CentOS/Rocky-compatible profiles where a supported Python is available.

Platform support is profile- and evidence-based rather than a generic claim that all
Linux distributions are supported.

Python support target remains 3.11, 3.12, and 3.13. Python 3.14 can be carried as an
experimental/non-blocking compatibility lane until upstream dependency support and real
tests justify promotion.

3. Python packaging and distribution
-------------------------------------

After an explicitly accepted stable/feature-complete milestone, Binnacle may begin
normal release distribution.

Python distribution
~~~~~~~~~~~~~~~~~~~

* standard PyPI package;
* ``pipx install binnacle`` recommended for ordinary Python-package users;
* ``pip install binnacle`` and ``uv tool install binnacle`` remain valid where
  appropriate;
* installation has no hidden system-level side effects;
* runtime does not require ``pipx`` or ``uv`` specifically once installed.

Native system distribution
~~~~~~~~~~~~~~~~~~~~~~~~~~

* DEB packages for Debian/Raspberry Pi OS/Ubuntu profiles;
* RPM packages for Fedora/RHEL/Rocky/CentOS profiles;
* initially published through Binnacle GitHub Releases rather than distro repositories;
* behave like normal system packages;
* own systemd service integration, system users/groups, ``/etc/binnacle``,
  ``/var/lib/binnacle``, and related system paths;
* depend on the distribution-provided compatible Python interpreter rather than bundling
  CPython;
* do not modify the distribution's global Python environment with ``sudo pip``.

Native packages may privately ship Binnacle-specific Python runtime dependencies under
an application-owned path while relying on the OS for the interpreter and fundamental
system libraries. Build/release resolves exact runtime dependencies from the reviewed
lock and includes only runtime components, never development/test/build tools.

Target-specific native packages are acceptable when Python minor, architecture, ABI, or
native wheels differ. One universal DEB/RPM is not a requirement.

4. Release model
----------------

When releases begin:

* strict Semantic Versioning applies;
* Git tag ``vMAJOR.MINOR.PATCH`` is the release version source of truth;
* ``setuptools-scm`` derives Python package version metadata;
* tagged GitHub Actions is the sole publisher;
* PyPI receives wheel/sdist;
* GitHub Releases receive wheel/sdist plus native packages, checksums, SBOM/provenance,
  and other release evidence;
* PyPI Trusted Publishing/OIDC is preferred over long-lived publishing tokens;
* one built artifact is published consistently rather than rebuilding different bits for
  different destinations.

Pre-1.0 development remains free to break experimental interfaces with explicit
migration/testing.

5. Runtime service architecture
-------------------------------

The three-process-role model remains foundational:

* unprivileged MCP/application control process;
* independently supervised unprivileged execution service;
* narrow privileged root broker.

systemd remains the managed-service supervisor on native system installations.
Binnacle processes remain foreground processes and do not implement their own daemon,
PID-file, restart, or log-rotation framework.

Long-running execution may use systemd transient units/cgroups so operation processes
remain independently observable/supervised across MCP server restart.

Future process isolation can be strengthened without changing the MCP/application
contract.

6. Privileged host administration
----------------------------------

Long term, Binnacle can provide broad Linux administration capability while keeping root
authority concentrated in the privileged boundary.

Outcome-oriented privileged capabilities may expand to cover:

* package installation/removal/upgrade;
* service lifecycle/configuration;
* managed protected-file changes;
* users/groups/permissions;
* networking;
* kernel modules/drivers;
* storage/mounts;
* firmware/boot configuration;
* reboot/shutdown;
* hardware setup;
* Binnacle self-management.

The broker does not become a generic ``run arbitrary command as root`` service.

``sudo`` remains primarily a bootstrap/local-administration mechanism. polkit may be
used later where a local interactive authorisation model provides value, but is not the
central remote privilege model.

7. General process isolation
----------------------------

The long-term command-execution security target is stronger than Bootstrap.

After empirical self-hosting work, evaluate Linux mechanisms such as:

* namespaces;
* cgroup v2;
* seccomp;
* Landlock/AppArmor/SELinux where appropriate;
* Bubblewrap/NsJail or another mature sandbox implementation;
* descriptor/environment/device confinement;
* process-tree cleanup and escape testing.

Do not select these mechanisms merely because they are fashionable. The chosen sandbox
must satisfy Binnacle's security properties on the real supported platform and must not
make ordinary software/hardware development unusable.

Normal development network access remains an explicit product decision. Credential,
privileged IPC, and protected-control-plane isolation remain independent of network
availability.

8. MCP target surface
---------------------

MCP remains Binnacle's only general-purpose remote control interface.

The final interface should fully use current MCP primitives according to their intended
roles and the actual host profile:

Tools
~~~~~

Focused semantic operations/observations selected by the model. Avoid giant generic
``action`` dispatchers and avoid direct wrappers around implementation CLIs.

Resources
~~~~~~~~~

Addressable state/context such as:

* device/profile state;
* capability state;
* workspaces;
* durable operation snapshots/output;
* retained results;
* hardware state/catalogue;
* diagnostics/metrics/log projections;
* audit projections.

Resources remain subject to the same authentication, policy, information, and result
boundaries as equivalent Tool access.

Prompts
~~~~~~~

Explicit user-selected workflow templates such as development/debug/setup workflows.
Selecting a Prompt does not grant authority.

Tasks and subscriptions
~~~~~~~~~~~~~~~~~~~~~~~

Use the MCP Tasks extension when the actual connected client advertises/supports it.
MCP task IDs map onto authoritative Binnacle operations rather than replacing them.

Use current notification/subscription mechanisms for meaningful state changes where
supported. Durable state remains authoritative if notifications are missed.

MRTR and other interaction mechanisms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

May be used for missing input/interactive continuation after real-host validation.
They do not automatically replace Binnacle's host-confirmation/preparation contract for
security-sensitive operations.

Deprecated MCP facilities
~~~~~~~~~~~~~~~~~~~~~~~~~

Do not build new Binnacle functionality around protocol facilities deprecated by the
current MCP direction when newer mechanisms exist. In particular, Binnacle does not
need MCP Sampling for reasoning because ChatGPT is the reasoning layer, and Binnacle's
workspace/diagnostic designs do not require deprecated Roots/Logging as foundational
interfaces.

9. MCP revision compatibility
-----------------------------

The target modern revision remains ``2026-07-28`` while retaining the explicit older
revision compatibility set defined by the repository's MCP revision-support contract.

FastMCP/SDK capability is a superset; Binnacle's own allowed revisions and behaviours
remain explicit.

Actual ChatGPT support is always an empirical host profile. Binnacle must be able to
probe and report differences between standard capability, SDK capability, server
implementation, and host behaviour.

10. HTTP runtime evolution
--------------------------

FastMCP native ASGI + Uvicorn remains the HTTP stack unless a measured requirement
justifies change. Do not add FastAPI simply to wrap the MCP application.

Bootstrap uses one worker for compatibility. A later stateless modern profile may use
multiple workers only after state/session compatibility, operation coordination, audit,
metrics aggregation, and real-host behaviour are proven.

``uvloop``, ``httptools``, standard asyncio, h11, and newer parser choices are benchmark
subjects rather than architecture identities. Real MCP workloads on the Pi decide
performance tuning.

11. Local STDIO support
-----------------------

STDIO is a later first-class transport for local AI clients such as Claude Code, Codex,
or other MCP hosts.

Use standard MCP STDIO behaviour: the client may launch a server process. Do not invent
a local bridge merely to avoid that normal model.

Because multiple local clients can launch multiple processes, later STDIO support must
prove cross-process operation/idempotency/resource-reservation/audit correctness against
shared Binnacle state.

HTTP daemon and STDIO processes may eventually coexist under a consistent device-local
policy model.

12. Controller identity and policy
----------------------------------

Authentication results from each supported transport/host are normalised into internal
``ControllerIdentity`` values.

Long-term policy may distinguish ChatGPT, local Claude Code, Codex, GitHub Copilot, CLI,
or future controllers without treating conversation IDs as authority.

The Bootstrap evaluator stays simple. Long term, adopt a proper policy-engine approach
behind the stable ``PolicyEngine`` boundary when real multi-resource/multi-controller
requirements justify it. Candidate technologies such as OPA/Rego, Cedar, or another
mature policy engine should be selected then, not now.

Regardless of implementation:

* operation contracts define maximum authority;
* policy may restrict, never expand, that authority;
* permanent safety/credential invariants cannot be overridden by user/environment/session
  convenience settings;
* policy decisions are explainable and auditable.

13. Capability and contract model
---------------------------------

Maintain one authoritative capability/operation model and project it onto MCP/CLI/policy
rather than independently hard-coding each surface.

Declarative contract source remains data-oriented YAML with formal schema/typed
validation and compiled immutable runtime representation.

Potential contract metadata includes:

* semantic identity/version;
* input/output schemas;
* scope;
* risk/confirmation class;
* privilege/network/credential/hardware authority;
* information class;
* idempotency/retry;
* timeout/cancellation;
* resource reservation;
* audit/evidence;
* device-profile applicability;
* MCP projection/annotations.

Implementation logic remains typed Python.

14. Persistence evolution
-------------------------

SQLite remains the default embedded transactional store unless measured concurrency or
operational requirements prove otherwise.

SQLAlchemy 2.x models/queries should remain portable where practical, while SQLite-
specific behaviour is isolated behind adapters. Future PostgreSQL support is possible,
but data migration would be an explicit export/import/migration process rather than
pretending Alembic alone converts one database engine into another.

Large payloads remain outside the primary DB. External object stores are not required
for a single Pi unless future retention scale justifies one.

15. Durable operation architecture
----------------------------------

The three-layer model remains:

::

   MCP Task/host request representation
       -> Binnacle operation_id
       -> execution/broker/system identity

The Binnacle operation is the authoritative durable lifecycle. It survives MCP request,
conversation, and process boundaries.

Long-term operation framework includes:

* idempotency;
* reservations/conflict control;
* output/evidence retention;
* cancellation;
* restart reconciliation;
* uncertain-outcome handling;
* managed-workload distinction;
* event/subscription projection;
* per-operation resource accounting.

16. Event and monitoring architecture
-------------------------------------

Prefer native event mechanisms where Linux already provides them:

* process/systemd lifecycle;
* udev device events;
* filesystem watches;
* GPIO edge events;
* netlink for network changes;
* journald-follow mechanisms;
* hardware-specific event APIs.

Internal events are typed, bounded, and non-authoritative. Durable state remains the
source of truth. Raw high-frequency events are aggregated before being surfaced to
ChatGPT.

No external message broker is required for the single-device architecture.

17. Git architecture
--------------------

Official Git CLI remains the canonical general Git backend because it provides the most
complete/native behaviour and fast adoption of new Git features.

Use machine-readable porcelain/plumbing formats rather than parse human presentation
where possible.

Keep the Git backend boundary open for future pygit2/libgit2 acceleration of workloads
such as:

* Git object database inspection;
* massive commit/tree traversal;
* history analytics where subprocess overhead becomes measurable.

GitHub-host operations remain separate from Git itself and can continue using ChatGPT's
external GitHub integration unless Binnacle-specific need emerges.

18. Credential architecture
----------------------------

Use a ``CredentialRef``/broker model rather than passing raw secrets through Tools,
Resources, logs, operation payloads, or general commands.

System-managed deployments may use systemd credentials, encrypted credentials,
dedicated SSH/GPG agents, and later hardware-backed mechanisms.

GitHub direction:

* repository-specific deploy SSH identities are appropriate for simple/small repository
  sets;
* GitHub App should be evaluated when many repositories/fine-grained short-lived
  permissions become a real need;
* GPG/OpenPGP signing remains a separate identity from Git transport authentication.

19. Hardware architecture
-------------------------

Hardware support tiers
~~~~~~~~~~~~~~~~~~~~~~

Tier 1: Raspberry Pi board/platform hardware.

Tier 2: official Raspberry Pi accessories/peripherals.

Tier 3: popular third-party devices, with weaker/curated guarantees.

Tier 1 and Tier 2 support are first-class Binnacle knowledge: detection, dependency
requirements, setup, verification, and operation. This knowledge ships with Binnacle,
but optional driver/system/Python dependencies are not installed by default.

Dependencies are installed only when the corresponding hardware capability is explicitly
enabled.

Unknown Tier-3 hardware may fall back to generic Linux device inspection plus ChatGPT
research/development.

Linux-kernel-first integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prefer standard Linux hardware subsystems and current Raspberry Pi stacks rather than
direct register manipulation where a maintained kernel/userspace interface exists.

Examples include current GPIO character-device/libgpiod direction, Linux I2C/SPI/UART
interfaces, and the current Raspberry Pi libcamera/rpicam/Picamera2 camera stack.

Exact libraries remain capability-specific decisions at implementation time.

20. Optional hardware runtime packaging
---------------------------------------

Knowledge/support code for Tier 1/2 remains integrated with Binnacle, but optional
runtime dependencies are installed only when a hardware capability is enabled.

For a future system-package installation, prefer optional native capability packages or
another package-manager-owned mechanism over running uncontrolled ``pip`` into the
system/global interpreter.

For a pipx installation, optional Binnacle runtime dependencies may be injected into the
Binnacle environment through the managed pipx mechanism.

Dependencies for software ChatGPT is developing belong to that project's own environment,
not the Binnacle runtime.

21. Third-party extension architecture
--------------------------------------

Do not require a full plugin ecosystem for Bootstrap.

Long term, keep stable extension/capability/adaptor contracts so owners or third parties
can add hardware/integrations without rewriting Binnacle internals.

Trusted Binnacle-maintained integrations may live in-process. A future general
third-party extension system should prefer out-of-process workers with narrow IPC and
capability authority rather than arbitrary plugin imports into the privileged/main MCP
process.

Standard Python package metadata/entry points may be used for discovery/distribution
without implying in-process trust.

22. Filesystem architecture
---------------------------

Continue the hybrid model:

* Python ``pathlib`` and ordinary abstractions for application-level path handling;
* descriptor-relative/race-resistant Linux primitives for security-sensitive workspace
  containment and mutation;
* atomic replacement patterns where promised;
* explicit protected/system filesystem operations outside normal workspaces.

Structural source-code editing/search should use mature existing solutions when a real
need emerges rather than being reimplemented inside Binnacle.

23. Development environment architecture
----------------------------------------

Every software project gets its own local isolated development environment where the
ecosystem supports it.

Binnacle orchestrates native ecosystem tools rather than inventing a universal package
manager:

* Python -> project environment/pyproject/lock tooling;
* Node -> project package-manager conventions;
* Rust -> Cargo;
* Go -> modules;
* C/C++ -> project build/toolchain conventions.

Existing project choices/lockfiles take precedence over Binnacle preferences.

Containers are optional future project tooling, not the default development boundary.

24. Observability architecture
------------------------------

Keep zero mandatory external observability services for the core single-Pi product.

Use:

* structured logging;
* journald retention for system-managed services;
* in-memory lightweight counters/gauges/timings;
* bounded MCP/CLI diagnostics;
* separate authoritative audit.

Prometheus/OpenTelemetry/Loki/Grafana/exporters may be added as optional integrations if
real deployment requirements justify them.

25. Audit evolution
-------------------

Bootstrap local hash-linked audit establishes the core contract but does not claim
resistance to a fully compromised root host that can rewrite all local history.

Stronger future evidence may include:

* independently signed checkpoints;
* TPM/hardware-backed signing;
* off-device receipts/anchors;
* remote immutable retention.

Only claim the integrity level actually demonstrated.

26. Documentation architecture
------------------------------

Use Sphinx as the long-term documentation system.

New long-form documentation uses reStructuredText. Python docstrings follow PEP 257 with
Sphinx-native reStructuredText roles/fields where needed; type hints remain authoritative
for types.

Target Sphinx extensions include the first-party autodoc/autosummary/doctest/intersphinx/
viewcode family as appropriate.

Mermaid remains the standard source format for architecture/state/sequence diagrams and
must be validated in development/CI.

Documentation hosting is separate from documentation source/tooling and can be chosen
when public release requires it.

27. Production development model
--------------------------------

Long term, use a dedicated Raspberry Pi for Binnacle development and separate Raspberry
Pi devices for stable/production usage.

Development Pi:

* source checkout;
* broad development diagnostics;
* experimental changes;
* real-device tests;
* real ChatGPT host validation.

Production Pi:

* released package;
* standard diagnostics;
* controlled upgrade/rollback;
* incremental rollout after development validation.

A stable release should be promoted gradually rather than assuming every device upgrades
immediately after a Git merge.

28. Connectivity providers
--------------------------

OpenAI Secure MCP Tunnel is the first preferred private-connectivity path for ChatGPT
because it is directly relevant to the target host.

Keep provider boundaries open for alternatives such as Cloudflare Tunnel and Tailscale
Funnel where they prove useful.

The tunnel remains transport/connectivity, not a replacement for controller
authentication or local policy.

29. Technology-quality direction
--------------------------------

Core implementation remains strongly typed and highly validated.

Agreed quality directions include:

* Ruff format/lint with a reviewed explicit rule set;
* strict MyPy and the Pydantic plugin where appropriate;
* SQLAlchemy 2.x native typing, not deprecated SQLAlchemy mypy stubs/plugins;
* Bandit and CodeQL security analysis;
* pip-audit dependency vulnerability scanning;
* deptry dependency hygiene;
* Import Linter architecture constraints;
* Vulture conservative dead-code analysis;
* schema/YAML/Actions/docs/Mermaid validation;
* Radon complexity/maintainability reporting with conservative blocking only where
  meaningful;
* wheel/twine checks when release packaging begins.

Tools are development dependencies only unless required at runtime for a real capability.

30. Decision rule for future implementation
-------------------------------------------

When adding a target capability after Bootstrap:

#. start from ``design-principles.rst``;
#. inspect real current Raspberry Pi/ChatGPT evidence;
#. prefer standards/native/mature open source;
#. preserve explicit authority/lifecycle boundaries;
#. implement the smallest capability that solves the observed need;
#. test in ordinary CI, real-device context, and real-host context as applicable;
#. update target/deferred status based on evidence rather than speculation.

This document defines direction. It does not make every section a precondition for the
first working Binnacle.
