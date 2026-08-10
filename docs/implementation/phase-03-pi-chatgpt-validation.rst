Binnacle Phase 3 Detailed Implementation Plan
=============================================

:Phase: 3 -- Deploy to the development Raspberry Pi and validate real ChatGPT
:Status: merged
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 2 read-only MCP compatibility-server plan
:Primary objective: Replace assumptions about remote ChatGPT compatibility with authenticated real-device evidence before consequential capability is designed or implemented
:Implementation scope: development-Pi source deployment, systemd service operation, private connectivity, one evidence-selected authenticated controller profile, read-only real-ChatGPT evaluation, evidence bundling, and compatibility-profile promotion only

Purpose
-------

Phase 3 moves Binnacle from local MCP compatibility to one real authenticated ChatGPT
connection against one real 64-bit development Raspberry Pi.

The phase exists because MCP specification support, SDK/framework support, server
implementation, ChatGPT product support, account/workspace entitlement, private
connectivity, and authentication are different facts. None may be substituted for
observed evidence from the actual Bootstrap profile.

Phase 3 consumes the Phase 2 ``compatibility-core`` server unchanged in authority: the
remote catalogue remains exactly the five read-only Tools and no consequential device
effect becomes possible. The implementation work is deployment, controller-security
integration, evidence capture, and profile promotion.

The first major Bootstrap milestone is reached when real ChatGPT can reliably connect to
the selected development Pi, authenticate as the intended controller, discover the
read-only catalogue, call ``binnacle_probe`` and ``system_inspect``, and leave a complete
sanitised evidence record of the actual requested/negotiated MCP behaviour.

The ``:Status: merged`` value is the terminal status defined by
``docs/implementation/index.rst`` for the authoritative document after this plan PR
lands. While the PR is open, this document is proposed rather than authoritative.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-02-readonly-mcp-server.rst``;
#. ``docs/security/controller-transport.md``;
#. ``docs/mcp-interface.md``;
#. ``docs/mcp-revision-support.md``;
#. ``docs/mcp-evaluation.md``;
#. ``docs/mcp-profile.md``;
#. ``spec/mcp/evaluation-profile.yaml``;
#. ``spec/mcp/evaluation-cases.yaml``;
#. ``schemas/mcp/evaluation-manifest.schema.json`` and relevant controller/MCP security
   fixtures;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

Real Raspberry Pi and real ChatGPT observations outrank planning-time assumptions when a
detail depends on the host, plan, workspace, tunnel, authentication path, client
capabilities, or negotiated MCP revision.

2. Planning-time product hypothesis and revalidation rule
---------------------------------------------------------

At the time this Phase 3 plan is written, current OpenAI product documentation describes
ChatGPT custom MCP connectivity as remote rather than direct-local connectivity, with a
Secure MCP Tunnel path for private/on-premises/developer-machine servers and an
application authentication configuration flow. Product availability and write/modify
entitlement are plan/workspace dependent.

Those facts are **planning-time hypotheses only**. The Phase 3 implementation run must
re-read the current official OpenAI product documentation and inspect the actual ChatGPT
UI/account/workspace immediately before the live test. Evidence records what is observed
then. A changed product UI or entitlement changes the evaluation profile rather than
being silently normalized to this document.

In particular:

* do not assume that a private tunnel authenticates a Binnacle controller;
* do not assume that the selected account can use write/modify MCP actions;
* do not require write entitlement for the Phase 3 exit gate;
* do not treat local MCP SDK success as ChatGPT support;
* do not promote ``2026-07-28`` merely because it is Binnacle's target revision;
* do not infer tenant/workspace/client/binding claims that the actual authentication path
  does not provide.

3. Prerequisite and phase exit gate
----------------------------------

Prerequisite
~~~~~~~~~~~~

The Phase 2 implementation described by the merged Phase 2 plan must exist and pass its
local exit gate before remote deployment begins. The exact candidate build deployed to
the Pi must therefore already have:

* the Phase 1 project/quality foundation;
* the five reviewed ``compatibility-core`` Tools;
* exact schema/result validation;
* build-bound runtime manifest/catalogue identity;
* finite MCP revision support;
* local loopback-only serving;
* local MCP discovery/invocation tests;
* health/readiness;
* no consequential operation surface.

Exit gate
~~~~~~~~~

Phase 3 implementation is complete only when all of the following are true for one exact
evaluation profile:

* the selected 64-bit Raspberry Pi runs the exact reviewed Binnacle source revision from
  the source checkout under systemd;
* Binnacle's MCP application process runs as a dedicated non-root service identity;
* the application itself remains on loopback or an equally reviewed protected local hop;
* the selected private connectivity path reaches only the intended MCP route;
* every remotely accepted ``/mcp`` request is authenticated before MCP Tool dispatch;
* one stable ``ControllerIdentity`` is derived from the selected live authentication
  profile;
* unauthenticated/direct-bypass requests cannot reach Tool dispatch;
* real ChatGPT connects through the selected app/connector profile;
* ``endpoint-connect`` passes or is classified honestly as host-policy-blocked without
  weakening authentication;
* real ChatGPT can discover the five read-only Tools;
* real ChatGPT can invoke ``binnacle_probe`` and ``system_inspect`` reliably;
* the actual requested and, where applicable, negotiated MCP revision is recorded;
* structured/text result handling and execution-error rendering are exercised through
  the real host;
* the applicable frozen evaluation cases meet their exact minimum-attempt/oracle rules;
* non-applicable/later-capability cases are classified without implementing them;
* the evidence manifest validates against the existing evaluation schema;
* the evidence bundle is sanitised and receives a detached receipt without
  self-reference;
* ``docs/mcp-profile.md`` is updated from that reviewed evidence rather than from
  expectation;
* no raw token, cookie, full authorization header, private key, reusable gateway
  assertion, or owner-private payload is present in the retained evidence;
* the exact deployed implementation head passes its normal CI gates.

If no authentication profile satisfies the mandatory controller-transport contract, the
Phase 3 exit gate is **blocked**. Do not fall back to anonymous tunnel trust, source IP,
client display name, conversation identity, or a manually configured wildcard owner.

4. Explicit non-goals
---------------------

Phase 3 does **not** implement:

* any write/modify Tool;
* the ``compatibility-write-probe`` catalogue;
* workspace registration, file read/search, or workspace mutation;
* durable operations, SQLite, SQLAlchemy, Alembic, idempotency persistence, retained
  operation output, or the audit journal;
* command execution or an execution supervisor;
* Git operations or Git credentials/signing;
* package/service/restart Tools or the privileged broker;
* controller replacement/transfer or multi-controller policy;
* production OAuth architecture for every future deployment;
* an OAuth authorization server merely to avoid selecting a mature external/provider
  mechanism;
* a general identity platform;
* full tunnel-provider automation or multi-provider management;
* public Internet exposure of the Binnacle application listener;
* general REST endpoints;
* STDIO MCP transport;
* Resources, Prompts, MCP Tasks, MRTR/elicitation, subscriptions, owner-only result
  surfaces, or cross-server capabilities;
* a local GUI/dashboard;
* production PyPI/DEB/RPM packaging;
* production rollout/update/recovery automation;
* hardware capability implementation;
* later numbered phase design.

The larger frozen evaluation manifest intentionally contains cases for later write,
idempotency, cancellation, reconnect, concurrency, and optional MCP capabilities. Phase
3 records those as ``server-not-implemented``, ``not-applicable``, ``not-tested``, or
another exact evidence-derived status. It does not implement them to make the manifest
look complete.

5. Before/after semantics
-------------------------

Before Phase 3
~~~~~~~~~~~~~~

Binnacle has a locally proven loopback-only read-only MCP server. The compatibility
profile still contains unknown/not-tested host facts. No remote controller is trusted.

After Phase 3
~~~~~~~~~~~~~

One exact deployment has:

* a stable source-checkout/service identity on one Pi;
* a private ChatGPT connectivity path;
* one validated controller authentication profile;
* an in-memory authenticated controller security context on every accepted MCP request;
* a reviewed evidence bundle for the applicable frozen cases;
* an observed compatibility profile with actual product/plan/workspace/revision facts;
* explicit residual limitations and rerun triggers.

No consequential-operation authority is added.

6. Exact implementation file set
--------------------------------

The Phase 3 **implementation** work is expected to create or modify the following paths.
This detailed-plan PR itself adds only this document.

6.1 Existing Python files to modify
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   pyproject.toml
   uv.lock
   src/binnacle/application.py
   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/adapters/mcp.py
   src/binnacle/adapters/compatibility.py
   src/binnacle/domain/mcp.py
   src/binnacle/cli.py
   .github/workflows/python.yml
   .gitignore

Phase 3 extends the Phase 2 server; it does not create another FastMCP/Uvicorn
application.

6.2 New controller-security modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/domain/controller.py
   src/binnacle/ports/controller_auth.py
   src/binnacle/security/
     __init__.py
     controller.py
     middleware.py
     profile.py

Create **one** selected concrete authentication adapter after the live feasibility gate:

::

   src/binnacle/adapters/auth_gateway.py

or:

::

   src/binnacle/adapters/auth_oauth.py

Do not implement both complete profiles speculatively. The common domain/port/middleware
seam is implemented first; the selected live profile supplies exactly one concrete
adapter.

6.3 Development-Pi deployment assets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   deploy/systemd/binnacle-dev.service
   scripts/setup_dev_pi.py
   scripts/verify_dev_pi.py
   docs/operations/development-pi.rst

Create this file **only if** the selected supported Secure MCP Tunnel/client actually
runs as a customer-hosted persistent process with a documented stable CLI at
implementation time:

::

   deploy/systemd/binnacle-tunnel.service

Do not commit an invented tunnel command line. If current OpenAI tooling owns tunnel
lifecycle differently, record and use its actual supported mechanism instead.

6.4 Evaluation tooling
~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/evaluation/
     __init__.py
     profile.py
     evidence.py
     redaction.py
     cases.py
     bundle.py
   scripts/mcp_evaluation.py

The evaluator consumes the existing evaluation profile, case manifest, and evaluation
manifest schema. It does not invent a new evaluation status vocabulary or a second case
manifest.

6.5 Tests
~~~~~~~~~

Add at least:

::

   tests/unit/
     test_controller_domain.py
     test_controller_profile.py
     test_controller_middleware.py
     test_auth_selected_profile.py
     test_evaluation_profile.py
     test_evaluation_evidence.py
     test_evaluation_redaction.py
     test_evaluation_bundle.py
   tests/integration/
     test_authenticated_mcp.py
     test_controller_transport_security.py
     test_tunnel_bypass.py
     test_phase3_systemd_assets.py
     test_evaluation_manifest.py

Reuse ``tests/fixtures/mcp/controller-transport-security.yaml`` and the existing
machine-readable evaluation cases instead of creating a parallel security/evaluation
fixture language.

7. Development-Pi filesystem layout
-----------------------------------

Use the Bootstrap source-checkout model:

::

   /srv/binnacle-dev/
     repo/
       .git/
       src/
       tests/
       docs/
       pyproject.toml
       uv.lock
       .venv/

   /etc/binnacle/
     dev.toml
     controller-profile.toml

   /var/lib/binnacle/
     evaluation/

   /run/binnacle/

The Phase 3 application still has no SQLite state. ``/var/lib/binnacle/evaluation`` is an
operator/evaluation evidence location, not the future authoritative operation store.

The repository checkout and protected controller configuration are separate. Git reset,
checkout, or future workspace mutation must not delete authentication configuration or
retained evidence.

8. Development identities and permissions
------------------------------------------

Create during privileged setup:

``binnacle``
   Dedicated unprivileged main MCP/application service user.

``binnacle-dev``
   Development group used to grant the source checkout the minimum shared read/traverse
   access required by the service now and a stable ownership seam for later development
   execution. Do not grant this group root or protected-controller-state authority.

If the selected tunnel uses a local customer-hosted daemon, create a separate unprivileged
``binnacle-tunnel`` identity rather than giving the main Binnacle process tunnel
credentials/network authority it does not need.

Minimum layout expectations:

* ``/srv/binnacle-dev/repo`` is not owned by root-only state and remains a real Git
  development checkout;
* the ``binnacle`` service can read/execute the project environment and source needed to
  run the server;
* ``/etc/binnacle`` is root-controlled and not writable by ``binnacle``;
* controller-profile material is readable only by the service identity/group that
  validates it;
* tunnel credentials, when present, are not readable by the Binnacle application user;
* evaluation evidence is not world-readable;
* no reusable authentication secret exists inside the Git repository or Tool result.

Do not preconfigure later executor/broker users or sockets unless systemd/service setup
requires only the stable identity names; their authority is deferred.

9. ``scripts/setup_dev_pi.py``
------------------------------

Purpose
~~~~~~~

Perform the idempotent local privileged setup needed to run the read-only development
server as a service. It is an operator setup utility, not the future privileged broker.

Interface
~~~~~~~~~

Use subcommands equivalent to:

.. code-block:: console

   sudo python scripts/setup_dev_pi.py check --repo /srv/binnacle-dev/repo
   sudo python scripts/setup_dev_pi.py apply --repo /srv/binnacle-dev/repo

``check`` is read-only and prints a deterministic plan/result. ``apply`` performs only
the declared Phase 3 setup.

Required preflight
~~~~~~~~~~~~~~~~~~

Before mutation verify:

* Linux + systemd;
* 64-bit architecture;
* selected Debian-family development profile or explicitly recorded equivalent;
* compatible distribution-provided Python, minimum 3.11 and below 3.14 for the reviewed
  Bootstrap matrix;
* exact repository path exists, is a Git checkout, and is not under ``/etc``, ``/var`` or
  another protected system directory;
* ``uv.lock`` and ``pyproject.toml`` exist;
* the service unit source file exists;
* required user/group names are not conflicting with an incompatible local identity;
* no generated output path escapes the declared system directories.

``apply`` may:

* create the ``binnacle`` user and ``binnacle-dev`` group;
* create/protect ``/etc/binnacle``, ``/var/lib/binnacle/evaluation``, and
  ``/run/binnacle`` ownership/modes;
* install/update the reviewed ``binnacle-dev.service`` unit atomically;
* run ``systemctl daemon-reload``;
* enable the service only when an explicit ``--enable`` flag is supplied;
* report the exact manual next steps for project sync, protected config, tunnel, and live
  evaluation.

It must not:

* install arbitrary OS packages;
* clone/pull/reset the repository;
* generate OAuth/tunnel secrets;
* edit firewall/router configuration;
* open an Internet/LAN listener;
* install the future executor/broker;
* start real ChatGPT evaluation automatically.

All writes are atomic where practical. Re-running ``apply`` with the same inputs is
idempotent.

10. Source-checkout environment workflow
---------------------------------------

The operator performs as the development checkout owner:

.. code-block:: console

   cd /srv/binnacle-dev/repo
   git status --short
   uv sync --frozen --python <pi-python>
   uv run python scripts/compile_mcp_registry.py --check
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests
   uv run lint-imports
   uv run pip-audit
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py

Do not run a service from a checkout that has not passed the applicable exact-build
validation.

Record before deployment:

* Git commit SHA;
* branch;
* dirty/clean state;
* Phase 2 build digest/runtime-manifest digest;
* Python version;
* ``uv`` version;
* resolved FastMCP/MCP SDK/Uvicorn versions.

The first Phase 3 supported evidence run should use a clean reviewed commit. A deliberately
dirty source checkout is a different profile and cannot reuse the clean-build evidence.

11. ``binnacle-dev.service``
----------------------------

The systemd unit runs Binnacle directly from the source checkout environment.

Required shape is equivalent to:

.. code-block:: ini

   [Unit]
   Description=Binnacle development MCP server
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=binnacle
   Group=binnacle-dev
   WorkingDirectory=/srv/binnacle-dev/repo
   ExecStart=/srv/binnacle-dev/repo/.venv/bin/binnacle serve --config /etc/binnacle/dev.toml
   Restart=on-failure
   RestartSec=2s
   UMask=0077
   NoNewPrivileges=yes
   PrivateTmp=yes
   ProtectSystem=strict
   ProtectHome=yes
   ProtectKernelTunables=yes
   ProtectKernelModules=yes
   ProtectControlGroups=yes
   RestrictSUIDSGID=yes
   CapabilityBoundingSet=
   AmbientCapabilities=

   [Install]
   WantedBy=multi-user.target

The implementation may add narrowly justified systemd hardening that does not break the
read-only procfs/os-release inspection contract or the protected local connectivity path.
Do not enable ``PrivateNetwork`` because a separate local tunnel process must be able to
reach the Binnacle loopback listener.

Do not add writable system paths beyond what Phase 3 actually requires. The main server
has no operational state database in this phase.

12. Protected Binnacle configuration
-----------------------------------

``/etc/binnacle/dev.toml`` contains non-secret server/runtime settings:

.. code-block:: toml

   runtime_profile = "development"

   [server]
   host = "127.0.0.1"
   port = 8000
   workers = 1

   [logging]
   level = "INFO"
   format = "json"

The exact Phase 2 request/shutdown/inspection limits remain present with their reviewed
bounded defaults.

Phase 3 does not permit an ordinary environment variable or CLI flag to turn the
application into an unauthenticated non-loopback server.

``/etc/binnacle/controller-profile.toml`` is a separate protected security-critical
configuration file for the **selected** live authentication profile. It contains no raw
private key/token unless the selected standard profile absolutely requires a local key
reference; reusable secret bytes should be supplied through systemd credentials or a
separate root-controlled file/reference.

13. Controller security domain
------------------------------

``src/binnacle/domain/controller.py`` owns framework-independent immutable values.

Define:

.. code-block:: python

   class ControllerProfileKind(StrEnum):
       OAUTH_RESOURCE_SERVER = "oauth-resource-server"
       TRUSTED_GATEWAY_ASSERTION = "trusted-gateway-assertion"

   @dataclass(frozen=True, slots=True)
   class ControllerIdentity:
       controller_id: str
       profile_id: str

   @dataclass(frozen=True, slots=True)
   class ControllerSecurityContext:
       identity: ControllerIdentity
       issuer: str
       subject: str
       canonical_audience: str
       authorized_client: str | None
       owner_boundary: str | None
       credential_binding_id: str | None
       scopes: frozenset[str]
       authentication_time: datetime
       expires_at: datetime
       evidence_id_digest: str | None

   @dataclass(frozen=True, slots=True)
   class ControllerProfileSummary:
       profile_id: str
       profile_version: str
       kind: ControllerProfileKind
       required_scopes: frozenset[str]
       canonical_resource_uri: str

No raw access token, refresh token, authorization code, cookie, gateway assertion,
private key, or password is stored in these domain objects.

``controller_id`` is a non-reversible digest/opaque ID derived from the exact validated
identity tuple required by ``controller-transport.md``. Missing profile fields remain
explicitly absent; they do not become wildcard strings.

14. Authentication port
-----------------------

``src/binnacle/ports/controller_auth.py`` owns the first stable controller-authentication
port:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class TransportAuthenticationInput:
       method: str
       path: str
       authority: str
       origin: str | None
       peer_kind: str
       peer_id: str | None
       credential_scheme: str | None
       credential_bytes: bytes | None
       forwarded_assertion_bytes: bytes | None

   class ControllerAuthenticator(Protocol):
       async def authenticate(
           self,
           request: TransportAuthenticationInput,
       ) -> ControllerSecurityContext: ...

The concrete HTTP middleware owns extraction of credential/assertion bytes and must
release references after validation. The bytes are sensitive runtime data and are never
logged, persisted, copied into Tool arguments, or attached to the returned security
context.

The implementation may replace raw ``bytes`` fields with a dedicated non-repr sensitive
container if that makes accidental logging harder. It must not weaken the no-retention
rule.

15. Phase 3 read-only transport authorisation
---------------------------------------------

The selected remote profile requires at minimum:

::

   binnacle:connect
   binnacle:observe

Phase 3 defines no ``binnacle:modify``, ``binnacle:execute``, or
``binnacle:self-manage`` entitlement because no such Tool exists.

Before MCP dispatch:

* missing/invalid/expired/revoked/untrusted credentials -> HTTP 401 where the selected
  profile requires it;
* valid controller lacking ``connect``/``observe`` -> HTTP 403;
* Host/Origin/proxy/profile mismatch -> pre-dispatch transport/security rejection;
* unsupported MCP revision -> protocol rejection;
* valid authenticated read-only call -> MCP Tool dispatch.

A tunnel connection, source IP, loopback peer, session ID, clientInfo name, or ChatGPT
conversation ID never satisfies these checks alone.

16. Authenticated request context
--------------------------------

Extend the Phase 2 ``McpCallContext`` so every remotely dispatched Tool call carries a
validated controller identity separately from model-supplied arguments:

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class McpCallContext:
       revision: str
       era: ProtocolEra
       request_id: str
       controller: ControllerSecurityContext

Local unit/integration tests may inject a deterministic authenticated test context. There
is no anonymous production/Phase-3 remote context.

The five read-only Tool use cases do not use ``controller_id`` as application authority
beyond the pre-dispatch read-only profile check, but logs/evidence may record the opaque
controller ID for correlation.

17. Authentication-profile feasibility gate
--------------------------------------------

The controller-transport contract defines two acceptable Bootstrap candidate patterns.
Phase 3 selects exactly one from live evidence.

17.1 Decision sequence
~~~~~~~~~~~~~~~~~~~~~~

Before implementing the concrete authentication adapter:

#. revalidate current official ChatGPT custom-app/MCP and Secure MCP Tunnel guidance;
#. inspect the selected tunnel/gateway's current documented local-hop/authentication
   behavior and CLI/configuration model;
#. create the ChatGPT custom app/draft against the private endpoint only as far as needed
   to establish the actual supported authentication setup;
#. record which stable authenticated claims/credentials can reach Binnacle;
#. compare them field-for-field with ``controller-transport.md``;
#. choose exactly one profile using the decision rules below;
#. freeze ``controller-profile.toml`` schema/values and concrete adapter only after the
   evidence is sufficient.

Do not run an unauthenticated five-Tool remote server simply to observe traffic.
Pre-authentication feasibility testing must reject before MCP Tool dispatch.

17.2 Prefer trusted gateway assertion only when provable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Select ``trusted-gateway-assertion`` only if the current tunnel/gateway provides a
cryptographically protected assertion/channel whose Binnacle-verifiable data includes
the mandatory selected-profile identity/audience/freshness fields and whose protected
local hop cannot be bypassed.

Plain ``X-User``/forwarded identity headers, tunnel membership, source IP, or an
undocumented opaque connection marker do not qualify.

If selected, the profile fixes:

* assertion format and version;
* trusted gateway identity/key/certificate;
* exact external issuer/auth source where supplied;
* subject;
* canonical Binnacle audience;
* authorized client when available/required;
* owner/workspace boundary when available/required;
* exact read-only scopes;
* issued-at/expiry maximum lifetime;
* assertion identifier/replay rule;
* request/local-channel binding;
* algorithm/key allowlist;
* local peer/socket/loopback trust boundary.

17.3 OAuth resource-server fallback
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If no qualifying gateway assertion exists, select the OAuth resource-server profile only
if current ChatGPT/app configuration and a mature OAuth/OIDC provider can issue Binnacle-
audience credentials that Binnacle can validate according to the controller-transport
contract.

The Phase 3 implementation acts as a **resource server**, not a custom authorization
server.

The profile fixes:

* canonical issuer;
* canonical Binnacle resource/audience URI;
* signature/introspection authority;
* algorithm allowlist;
* subject requirement;
* authorized client/``azp`` requirement when the real profile supplies it;
* tenant/workspace requirement only when actually supplied and selected;
* token expiration/not-before/issued-at policy;
* required ``connect``/``observe`` scopes;
* revocation/freshness method;
* credential binding when the actual profile supports it;
* bounded clock skew;
* residual bearer-token risk if proof-of-possession is not available.

Opaque tokens are accepted only with authoritative introspection or equivalent verified
validation. No token is trusted based on shape.

17.4 Neither profile is feasible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If neither profile satisfies mandatory controller identity and remote authentication:

* keep Phase 2 local server behavior;
* record ``authentication`` as ``test-failed`` or ``host-policy-blocked`` according to
  the layer actually reached;
* retain the evidence;
* fail the Phase 3 exit gate;
* do **not** weaken the controller contract to source-IP/tunnel trust/anonymous access.

18. Selected authentication adapter
-----------------------------------

Only the selected adapter becomes a runtime dependency/implementation.

18.1 Gateway adapter shape
~~~~~~~~~~~~~~~~~~~~~~~~~~

If selected:

.. code-block:: python

   class GatewayAssertionAuthenticator(ControllerAuthenticator):
       def __init__(
           self,
           *,
           profile: GatewayControllerProfile,
           verifier: GatewayAssertionVerifier,
           clock: Clock,
           replay_guard: InMemoryReplayGuard,
       ) -> None: ...

       async def authenticate(...) -> ControllerSecurityContext: ...

The replay guard may be in-memory because Phase 3 has no consequential effects and one
server worker. A restart losing replay-cache history is recorded as a residual read-only
limitation; no durable security claim for mutating operations is inferred.

18.2 OAuth adapter shape
~~~~~~~~~~~~~~~~~~~~~~~~

If selected:

.. code-block:: python

   class OAuthResourceAuthenticator(ControllerAuthenticator):
       def __init__(
           self,
           *,
           profile: OAuthControllerProfile,
           validator: AccessTokenValidator,
           clock: Clock,
       ) -> None: ...

       async def authenticate(...) -> ControllerSecurityContext: ...

Use a mature maintained JOSE/OAuth library or authoritative introspection client. Do not
implement signature algorithms/JWK parsing manually.

18.3 Conditional dependency rule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add only the selected adapter's direct dependency to ``pyproject.toml`` and ``uv.lock``.
The plan does not freeze a package name before the live assertion/token format is known.
The implementation PR must document:

* selected library/version compatibility line;
* why it is needed;
* Python 3.11--3.13 support;
* cryptographic maintenance posture;
* ``pip-audit`` result;
* why an already locked dependency cannot satisfy the same verified profile.

19. Controller-profile protected configuration
----------------------------------------------

The exact file is security-critical and uses ``extra=forbid`` typed parsing separate
from ordinary environment-overridable settings.

Common fields:

.. code-block:: toml

   profile_id = "chatgpt-bootstrap-readonly-v1"
   profile_version = "1.0.0"
   kind = "<selected-kind>"
   canonical_resource_uri = "<exact external MCP resource URI>"
   required_scopes = ["binnacle:connect", "binnacle:observe"]
   allowed_hosts = ["<exact reviewed host>"]
   allowed_origins = []
   clock_skew_seconds = 60

Profile-specific issuer/audience/gateway/key/revocation fields are added only for the
selected kind.

Security-critical profile values are loaded only from the protected file/systemd
credential references. They are not overridden by ``BINNACLE_*`` environment variables
or ``binnacle serve`` convenience flags.

The canonical external resource URI is not replaced by internal loopback/tunnel target
addresses when validating audience.

20. Authentication middleware
-----------------------------

``src/binnacle/security/middleware.py`` owns the smallest ASGI middleware necessary to
authenticate the public ``/mcp`` route before FastMCP dispatch.

Responsibilities:

#. match only the reviewed MCP route;
#. enforce request/header/body size limits before expensive authentication where
   practical;
#. validate exact ``Host``/``:authority`` allowlist;
#. validate ``Origin`` when present according to selected profile;
#. trust forwarded headers only on the selected validated local gateway boundary;
#. extract the selected credential/assertion without logging it;
#. call ``ControllerAuthenticator``;
#. enforce ``connect``/``observe`` scopes;
#. attach ``ControllerSecurityContext`` to request-local context inaccessible to model
   arguments;
#. call FastMCP only on success;
#. emit correct bounded 401/403 responses/challenges for the selected profile;
#. clear sensitive temporary references after completion.

``/healthz`` and ``/readyz`` remain local diagnostics and are **not** exposed through the
public tunnel/app route. Local unauthenticated access to these two minimal routes is
acceptable because the listener remains loopback/private and they reveal only bounded
status.

There is no authentication bypass flag.

21. Host, proxy, Origin, and local-hop rules
--------------------------------------------

21.1 Binnacle bind
~~~~~~~~~~~~~~~~~~

Keep the Binnacle application on ``127.0.0.1``/``::1`` or a reviewed restricted Unix
socket/private local hop. Do not bind ``0.0.0.0`` or a LAN address merely because Secure
MCP Tunnel exists.

21.2 Trusted proxy/gateway
~~~~~~~~~~~~~~~~~~~~~~~~~~

Forwarded scheme/host/client/identity data is accepted only from the exact configured
gateway identity or protected local socket boundary.

An untrusted local process that can reach the loopback socket cannot create a controller
identity by sending forwarded headers. It must still satisfy the selected cryptographic
authentication profile.

21.3 Host
~~~~~~~~~

The selected external ``Host``/``:authority`` allowlist is exact. Unexpected hosts and
ambiguous absolute-form targets are rejected before MCP dispatch.

21.4 Origin/CORS/cookies
~~~~~~~~~~~~~~~~~~~~~~~

No ambient cookie authorization exists. Do not enable wildcard credentialed CORS.
A missing ``Origin`` from the validated non-browser ChatGPT path is handled according to
observed profile evidence; it is not automatic trust.

22. Tunnel/private connectivity setup
------------------------------------

22.1 Preferred path
~~~~~~~~~~~~~~~~~~~

Use the current OpenAI-supported private MCP connectivity mechanism for a private/local
development server when it is available to the tested profile. At the time of planning,
Secure MCP Tunnel is the preferred candidate; implementation revalidates current support
immediately before setup.

22.2 Manual setup is acceptable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 3 may require operator/UI actions to:

* enable ChatGPT developer mode;
* create the custom app/connector draft;
* establish the Secure MCP Tunnel/private endpoint;
* select/configure the supported authentication mechanism;
* authenticate the intended owner;
* scan/refresh the Tool catalogue;
* select the app in a real ChatGPT conversation.

Do not automate ChatGPT UI or tunnel provisioning merely to make Phase 3 unattended.
The purpose is empirical host evidence.

22.3 Separate tunnel service when applicable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the current tunnel product provides a local persistent agent binary, run it under
``binnacle-tunnel`` with its own systemd unit/credential budget.

The concrete ``ExecStart`` is taken from the current official tunnel client/version and
recorded in the evaluation profile. The plan deliberately does not invent CLI flags.

The tunnel target is the local MCP route only, not ``/healthz``/``/readyz`` or a whole
local HTTP origin when the tunnel can restrict the path.

Tunnel service hardening must prevent its reusable credential from entering the main
Binnacle service environment.

23. ``scripts/verify_dev_pi.py``
-------------------------------

Provide a read-only deployment verification utility:

.. code-block:: console

   uv run python scripts/verify_dev_pi.py \
     --config /etc/binnacle/dev.toml \
     --controller-profile /etc/binnacle/controller-profile.toml

It emits human/JSON output and checks:

* architecture/Python/systemd profile;
* exact source checkout/build/runtime-manifest identity;
* clean/dirty Git state as observation only;
* systemd unit enabled/active status using a fixed unit name;
* service UID is non-root;
* application listener is loopback/private only;
* local ``/healthz`` and ``/readyz``;
* direct unauthenticated local ``/mcp`` is rejected once Phase 3 auth is enabled;
* expected protected config file ownership/modes;
* tunnel-agent unit/process identity when applicable;
* no tunnel credential appears in Binnacle service environment;
* five-Tool catalogue still matches Phase 2 registry through an authenticated local test
  credential/adapter fixture where practical.

The script never prints raw credentials/assertions/tokens.

24. Evidence workspace and Git safety
------------------------------------

Raw/sanitised evaluation files must not be accidentally committed with source changes.

Add to ``.gitignore``:

::

   /artifacts/mcp-evaluation/

Default evaluator output for a workstation/operator run is:

::

   artifacts/mcp-evaluation/<evaluation_id>/

On the Pi, server-side sanitised evidence may be staged under:

::

   /var/lib/binnacle/evaluation/<evaluation_id>/

The final bundle may combine sanitised Pi and ChatGPT-UI observations in the operator
workspace. The evaluator records source/file digests after sanitisation.

Do not commit screenshots, transcripts, wire frames, authentication diagnostics, or
bundle archives by default. The authoritative repository may later contain a small
reviewed compatibility-profile summary/digest, not the raw private evidence corpus.

25. Evaluation tool interface
-----------------------------

``scripts/mcp_evaluation.py`` exposes:

.. code-block:: console

   uv run python scripts/mcp_evaluation.py init --output <dir>
   uv run python scripts/mcp_evaluation.py record --output <dir> --case-id <id> ...
   uv run python scripts/mcp_evaluation.py verify --output <dir>
   uv run python scripts/mcp_evaluation.py finalize --output <dir>

The script uses ``src/binnacle/evaluation`` application code and the existing JSON
Schema/case/profile sources.

``init``
   Snapshot exact profile dimensions/digests known before the run and create a bounded
   working manifest state.

``record``
   Add one sanitised attempt/evidence reference for an existing frozen ``case_id``.
   It cannot invent a new case/risk class/status.

``verify``
   Validate case IDs, attempt counts, evidence references, profile/case digests,
   redaction metadata, conclusions, and evaluation-manifest schema without finalizing.

``finalize``
   Freeze the evidence inventory, write ``evaluation-manifest.json``, create a
   deterministic evidence archive, hash it, and write a detached
   ``evaluation-receipt.json`` alongside the archive. The manifest never contains the
   archive digest it is part of.

There is no ``--force-pass`` or status-vocabulary override.

26. Evaluation domain types
---------------------------

``src/binnacle/evaluation/profile.py`` owns immutable typed wrappers around the existing
evaluation schema/profile, including:

.. code-block:: python

   class CompatibilityStatus(StrEnum):
       OBSERVED_SUPPORTED = "observed-supported"
       OBSERVED_LIMITED = "observed-limited"
       DECLARED_UNEXERCISED = "declared-unexercised"
       NOT_DECLARED = "not-declared"
       TEST_FAILED = "test-failed"
       HOST_POLICY_BLOCKED = "host-policy-blocked"
       SERVER_NOT_IMPLEMENTED = "server-not-implemented"
       NOT_TESTED = "not-tested"
       UNSUPPORTED_BY_DESIGN = "unsupported-by-design"
       UNSTABLE = "unstable"
       EXPIRED = "expired"
       NOT_APPLICABLE = "not-applicable"

   @dataclass(frozen=True, slots=True)
   class EvaluationProfileIdentity:
       profile_id: str
       chatgpt_product: str
       chatgpt_surface: str
       account_plan: str
       workspace_type: str
       connection_method: str
       authentication_profile: str
       binnacle_build_sha256: str
       binnacle_config_sha256: str
       mcp_sdk_name: str
       mcp_sdk_version: str
       tunnel_or_gateway_identity: str | None
       device_model: str
       device_os: str
       device_kernel: str
       device_architecture: str
       device_profile: str
       intended_revision_set: tuple[str, ...]
       requested_revision: str | None
       negotiated_revision: str | None

Do not duplicate every JSON-schema field as a competing validation system. Typed objects
support construction; final serialized objects are always validated against the existing
``evaluation-manifest.schema.json``.

27. Profile-dimension collection
--------------------------------

The evaluator records every dimension required by
``spec/mcp/evaluation-profile.yaml``/the evaluation manifest.

27.1 ChatGPT/user-interface dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Human-observed and recorded explicitly:

* ChatGPT product;
* surface;
* actual account plan;
* workspace type;
* workspace-policy digest where a stable policy export/config can be reviewed, otherwise
  schema-valid ``null`` only where permitted;
* developer-mode/app availability;
* app permission/read entitlement observations.

Do not silently populate these from the repository's initial ``Pro`` hypothesis.

27.2 Connectivity/authentication dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Record:

* connection method/product name;
* selected controller profile ID/version/kind;
* canonical public MCP resource URI in sanitised/profile-safe form;
* tunnel/gateway agent identity/version and artifact digest where applicable;
* authentication-profile configuration digest excluding secret bytes;
* opaque ``controller_id`` and safe identity tuple field presence/absence in server
  evidence, not raw credentials.

27.3 Binnacle/server dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Record:

* build digest/version;
* config digest;
* runtime Tool-manifest digest;
* schema-registry digest;
* policy-bundle digest or the exact existing no-policy/Phase-3 bootstrap projection
  required by the evaluation schema;
* MCP SDK name/version/artifact digest;
* evaluation profile/case digests;
* dispatcher version;
* intended revision set.

27.4 Pi dimensions
~~~~~~~~~~~~~~~~~~

Record bounded facts:

* Pi model from an implementation-owned fixed source such as device-tree model file;
* OS;
* kernel;
* architecture;
* selected device-profile name.

Raw machine ID is not evidence.

27.5 Observed MCP dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Record separately:

* revision requested by the real client when observable;
* legacy revision negotiated/session revision where applicable;
* protocol dispatch path actually used;
* observed client capabilities as a sanitised canonical object plus digest.

Never infer one from another.

28. Configuration digest
------------------------

``binnacle_config_sha256`` is the SHA-256 of a canonical **sanitised resolved
configuration projection**, not the raw TOML bytes if they can contain local paths/key
references.

Include behavior-relevant non-secret fields:

* runtime profile;
* server bind/port/limits;
* logging mode where it affects evidence;
* selected authentication profile ID/version/kind;
* canonical resource/audience URI;
* required scopes;
* allowed host/origin policy;
* algorithm/freshness/revocation mode names;
* secret/key **reference identities/digests**, never secret bytes.

Canonical JSON normalization follows the repository's deterministic digest conventions.

A material config change triggers a new evaluation profile/evidence run.

29. Evidence file model and redaction
-------------------------------------

Every retained evidence file receives:

* stable ``evidence_id``;
* relative path;
* SHA-256;
* media type;
* ``normal-result`` or ``restricted-result`` information class;
* ``redacted=true`` before final bundle promotion.

``src/binnacle/evaluation/redaction.py`` enforces at minimum:

* no ``Authorization`` header value;
* no bearer/refresh token;
* no cookie value;
* no authorization code;
* no raw gateway assertion;
* no private key;
* no systemd credential content;
* no raw machine ID;
* no unrelated owner-private prompt/transcript material;
* no unbounded HTTP body/log dump.

Use allowlist-first structured evidence generation wherever possible. Regex secret
scanning is an additional check, not the sole redaction strategy.

Human UI screenshots/transcripts require explicit reviewer redaction before they enter the
final inventory.

30. Server-side evaluation observations
---------------------------------------

Phase 3 adds bounded structured **evaluation diagnostics**, not a durable audit journal.

For an explicitly active evaluation run, record sanitised events containing only:

* evaluation ID;
* timestamp;
* local request correlation ID;
* opaque controller ID;
* authentication profile ID/version;
* authentication result category;
* safe issuer/audience/client/owner-boundary presence/digest values where permitted;
* MCP requested/negotiated revision;
* Tool name/version;
* result classification;
* latency;
* catalogue/build/config digests;
* bounded failure code.

Never record raw authorization data.

The implementation may emit these events to journald and let the evaluator collect a
bounded cursor/time window, or write a dedicated restricted evaluation file if that is
simpler and safer. It must not introduce SQLite solely for Phase 3 evidence.

31. Applicable frozen cases in Phase 3
--------------------------------------

Use the existing ``spec/mcp/evaluation-cases.yaml`` exactly.

31.1 Required Phase 3 live cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run and evaluate:

``endpoint-connect``
   Minimum 1 deterministic attempt. Must prove authenticated request observed and no
   unauthenticated Tool dispatch.

``protocol-revision-observed``
   Minimum 1. Invoke ``binnacle_probe`` and record actual requested/negotiated revision
   and dispatch path.

``tool-discovery-manifest``
   Minimum 1. Compare real-host Tool discovery with the reviewed runtime catalogue.

``model-tool-selection-binnacle-probe``
   Minimum 10 attempts using the frozen prompt/oracle. The expected Tool is
   ``binnacle_probe`` and prohibited alternatives remain prohibited.

``model-tool-selection-system-inspect``
   Minimum 10 attempts using the frozen prompt/oracle.

``structured-result-rendering``
   Minimum 10 attempts because its risk class is
   ``tool_selection_and_result_rendering``. Preserve null/array/nested/warning semantics.

``execution-error-rendering``
   Minimum 10 attempts. Must remain a Tool error result, not HTTP authentication error.

``read-entitlement``
   Minimum 5 attempts. Distinguish server success from host-policy block.

``latency-context-cost``
   Minimum 20 attempts. Record p50/p95/p99, metadata/result byte size, and context/token
   estimate where observable.

31.2 Later mutating/durable cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do **not** run/implement the required server capability for:

* ``write-entitlement-and-confirmation``;
* ``confirmation-decline``;
* ``idempotency-lost-response``;
* ``uncertain-no-auto-retry``;
* ``operation-cancellation``;
* ``reconnect-status-reconciliation``;
* ``concurrent-idempotency-race``.

For Phase 3, the evaluator classifies the relevant axes according to the existing rules,
primarily ``server-not-implemented`` because the required probe/capability does not
exist. Do not interpret absence of a write Tool as evidence that ChatGPT lacks write
entitlement.

31.3 Optional modern MCP probes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``resources-probe``, ``mrtr-elicitation-probe``, and ``tasks-probe`` remain
``not-applicable``/``server-not-implemented``/host-policy classification according to the
frozen case rules because Phase 3 does not implement those server probes.

Observed client capability declarations may still be recorded if they appear in the
normal connection handshake. A declaration without behavioral exercise is
``declared-unexercised``, not observed support.

31.4 Owner-only and cross-server cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not implement an owner-only payload surface or a second Binnacle/control server just
to run these cases. Record the exact not-applicable/server-not-implemented status under
the frozen oracle unless the already-selected host surface independently exposes the
necessary safe observation without expanding Binnacle scope.

32. Real ChatGPT execution procedure
-----------------------------------

Execute the first live run in this order.

32.1 Freeze candidate
~~~~~~~~~~~~~~~~~~~~~

Record exact Git/build/config/SDK/tunnel/controller-profile/evaluation-case identities and
confirm the Pi service is healthy/ready locally.

32.2 Verify bypass failure
~~~~~~~~~~~~~~~~~~~~~~~~~~

Before connecting ChatGPT, prove:

* direct unauthenticated local/public MCP request cannot dispatch a Tool;
* invalid/expired/wrong-audience/wrong-scope profile fixture is rejected at the correct
  security layer;
* public tunnel route cannot expose ``/healthz``/``/readyz`` when path restriction is
  supported;
* the main listener is not public/LAN-bound.

32.3 Connect custom app
~~~~~~~~~~~~~~~~~~~~~~~

Create/select the real ChatGPT custom MCP app using the selected private endpoint and
authentication profile. Record the actual product/plan/workspace configuration shown by
the UI.

32.4 Authenticate
~~~~~~~~~~~~~~~~~

Complete the normal user authentication flow. Do not copy credentials into prompts,
Tool arguments, screenshots, or evaluation notes.

32.5 Discovery/protocol
~~~~~~~~~~~~~~~~~~~~~~~

Run connection/revision/discovery cases before free-form prompts. Capture sanitised
server/wire evidence and the exact catalogue presented by ChatGPT.

32.6 Read-only Tool selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the frozen model-selection prompts the required number of independent attempts.
Record Tool selection, result, and grader outcome for each attempt.

32.7 Result/error rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run structured-result and execution-error cases to the frozen repetition threshold.
Capture model-visible/UI behavior and server-side schema observations.

32.8 Read entitlement
~~~~~~~~~~~~~~~~~~~~~

Run the frozen ``system_inspect`` entitlement case. A ChatGPT/workspace policy block is
recorded as host-policy evidence, not a Binnacle protocol defect.

32.9 Latency/context
~~~~~~~~~~~~~~~~~~~~

Run the 20-attempt read-only performance/context case without introducing performance
optimization during the measurement.

32.10 Finalize/review
~~~~~~~~~~~~~~~~~~~~~

Redact, verify, finalize bundle/receipt, derive conclusions, update
``docs/mcp-profile.md``, and perform an explicit human review before any axis is promoted.

33. Tool-discovery refresh observation
-------------------------------------

Later Bootstrap phases will add new Tools. Phase 3 must observe how the current ChatGPT
custom app handles catalogue refresh **without adding a new Tool now**.

Use supported UI/app management operations only:

* record whether the UI exposes Scan/Refresh actions;
* record whether re-scanning the unchanged server preserves the same catalogue;
* record the displayed change/review behavior, if any, for the unchanged manifest;
* do not mutate the manifest solely to force a refresh experiment;
* classify dynamic/list-change support only from what is actually observed.

This evidence informs later Tool promotion but creates no runtime capability.

34. Compatibility report after evidence promotion
-------------------------------------------------

Phase 2's ``compatibility_report`` reads a no-live-evidence baseline. Phase 3 replaces
that adapter with a reader that can consume **only a reviewed promoted summary**, not raw
UI evidence.

Use a protected generated summary such as:

::

   /var/lib/binnacle/evaluation/current-profile.json

The evaluator writes/promotes this file only after:

* manifest schema validation passes;
* bundle/receipt digests verify;
* reviewer fields are complete;
* profile/case manifest match is verified;
* evidence is marked complete/redacted;
* ``approved_for_promotion=true``.

The runtime reader validates the summary/profile digest before use. If no promoted
summary exists, keep the Phase 2 ``not-tested`` baseline.

``compatibility_report`` never reads screenshots/transcripts/raw wire logs or credentials.

35. Updating ``docs/mcp-profile.md``
-----------------------------------

The Phase 3 **implementation/evidence** work updates the human profile only from the
final reviewed evidence manifest.

Replace the initial unknown table with an observed-profile section containing:

* product/surface;
* actual plan/workspace type/policy digest where available;
* connection method;
* selected authentication profile ID/version;
* Binnacle build/config/SDK/tunnel identities;
* Pi profile;
* intended/requested/negotiated revisions;
* observed client capabilities digest;
* per-axis canonical status;
* evidence bundle/manifest receipt digest references;
* validity dates and rerun triggers;
* explicit limitations.

Do not copy raw credentials, private endpoint secrets, full private transcripts, or
restricted evidence into the human profile.

Do not change a status to ``observed-supported`` unless the frozen case attempts/oracles
satisfy the existing promotion contract.

36. Evidence bundle finalization
--------------------------------

``src/binnacle/evaluation/bundle.py`` implements deterministic bundling.

Final directory contains at least:

::

   evaluation-manifest.json
   evidence/
     <sanitised evidence files>

The detached receipt is stored beside, not inside, the archive:

::

   <evaluation_id>.tar.gz
   <evaluation_id>.receipt.json

To avoid compression metadata nondeterminism, the finalizer fixes archive entry order,
normalized path names, owner/group metadata, and timestamp policy before computing the
bundle SHA.

Receipt conforms to ``#/$defs/bundleReceipt`` and contains:

* schema version;
* bundle SHA-256;
* manifest SHA-256;
* profile ID;
* creation time.

The manifest inventories every included evidence file but does not contain the final
bundle digest.

37. Evaluation review gate
--------------------------

No automated script may self-approve the evaluation.

Before ``approved_for_promotion=true``:

* reviewer identity/time present;
* exact profile dimensions confirmed;
* frozen case-manifest digest confirmed;
* every applicable required case present;
* attempt counts meet the risk-class threshold;
* passes/failures/blocked totals are internally consistent;
* evidence references resolve and digests match;
* redaction declaration is true and independently spot-checked;
* no contradictory valid run is unresolved;
* conclusions use exact status vocabulary;
* validity end is no more than the profile's configured maximum days;
* all rerun triggers are copied from the frozen profile;
* evidence is complete enough to support every promoted axis.

The reviewer may reject promotion and retain the bundle as failed/blocked evidence.

38. Controller-transport security tests
---------------------------------------

Reuse and execute the mandatory controller transport fixture set against the selected
adapter.

At minimum prove:

* missing credential -> no Tool dispatch;
* malformed credential -> no Tool dispatch;
* expired credential/assertion -> no Tool dispatch;
* wrong issuer -> rejected when selected profile uses issuer;
* wrong audience/resource -> rejected;
* wrong subject/authorized client/owner boundary -> rejected when those are required by
  the selected profile;
* missing read scope -> 403;
* replay/freshness rule enforced to the extent of the read-only selected profile;
* session/controller mismatch rejected;
* tunnel/gateway direct bypass rejected;
* untrusted forwarded identity headers rejected;
* Host/authority mismatch rejected;
* unexpected Origin rejected where the observed profile sends Origin/policy requires it;
* oversized auth/header/body rejected before Tool dispatch;
* raw credential never appears in logs/results/evidence;
* inbound MCP credential is never forwarded downstream;
* authentication failure remains 401/403 and is not converted to a Tool execution error.

The test suite uses generated/fake credentials, not production user credentials.

39. Selected-profile integration test
-------------------------------------

``tests/integration/test_authenticated_mcp.py`` starts the actual Phase 3 ASGI application
on loopback with deterministic test profile/keys or a fake standards-compliant verifier.

Positive path:

#. establish valid selected-profile authentication;
#. list five Tools;
#. call ``binnacle_probe``;
#. call ``system_inspect``;
#. assert opaque controller identity exists in request context;
#. assert only ``connect``/``observe`` scope is required;
#. assert response contracts remain Phase 2-compatible.

Negative path proves unauthenticated/insufficient-scope/identity mismatch never invokes a
Tool binding.

The test must not require the real OpenAI tunnel or real ChatGPT in normal CI.

40. Systemd/deployment tests
----------------------------

Static/system tests verify:

* service unit ``User`` is non-root;
* one worker/source-checkout ExecStart path;
* no shell wrapper in ExecStart;
* no secret environment assignment;
* ``NoNewPrivileges=yes``;
* no ambient/bounding capabilities;
* no public bind encoded in unit/config fixture;
* protected config path outside repo;
* setup script check/apply idempotency under a temporary root filesystem fixture where
  possible;
* setup script refuses unsafe repository/system paths;
* verification script redacts sensitive data.

A real-Pi system test additionally runs ``systemd-analyze verify`` on installed unit(s).

41. Real-Pi deployment acceptance evidence
------------------------------------------

Capture sanitised command results for:

.. code-block:: console

   uname -m
   python3 --version
   systemctl show binnacle-dev.service --property=User,Group,MainPID,ActiveState,SubState
   ss -ltnp
   curl --fail http://127.0.0.1:8000/healthz
   curl --fail http://127.0.0.1:8000/readyz

For listener/process evidence, sanitize unrelated host services/addresses rather than
storing a complete unbounded host dump.

Also capture:

* exact repo commit/dirty state;
* `binnacle version`;
* build/runtime-manifest/catalogue digests;
* dependency/runtime versions;
* service journal excerpt around startup with bounded/redacted fields;
* selected tunnel/gateway identity/version without credential bytes.

42. Exact ChatGPT evidence outputs
---------------------------------

For each live attempt, retain enough evidence to reconstruct:

* case ID;
* timestamp;
* prompt/action used by the frozen case;
* whether ChatGPT selected/called the expected Tool;
* sanitized Tool arguments;
* server request correlation ID;
* requested/negotiated revision;
* server-side authentication outcome/controller ID;
* schema-validation outcome;
* model-visible result/error behavior;
* latency;
* pass/fail/blocked oracle result;
* bounded UI observation/screenshot reference when required.

Do not retain unrelated conversation history.

43. Failure classification
--------------------------

Use the existing fault taxonomy.

Examples:

``account cannot create/connect custom MCP app``
   ``host-policy`` / ``host-policy-blocked`` when the product/account/workspace actually
   blocks the setup independently of Binnacle protocol behavior.

``tunnel cannot reach local endpoint``
   connectivity/server/tunnel failure; do not call it MCP protocol failure without wire
   evidence.

``authentication cannot establish mandatory identity``
   authentication failure; Phase 3 blocked; do not bypass.

``wrong/unsupported MCP revision reaches server``
   protocol failure.

``Tool visible with wrong metadata``
   schema/server discovery failure.

``ChatGPT repeatedly selects wrong Tool``
   selection failure when the deterministic expected-tool case reaches the intended
   layer.

``result schema valid server-side but UI drops structure``
   host/result-handling evidence; classify per frozen oracle rather than rewriting the
   server contract without analysis.

``write case not runnable because no write probe exists``
   ``server-not-implemented`` rather than host-policy-blocked.

``optional Resource/Task/MRTR probe absent by design``
   ``not-applicable``/``server-not-implemented`` according to the frozen case/profile
   rule.

44. Rerun/expiry semantics
--------------------------

The first promoted evidence is valid for at most the existing profile's 30-day window and
expires sooner on any configured rerun trigger.

Material triggers include:

* ChatGPT product/plan/workspace-policy change;
* custom-app/developer-mode policy change;
* connection/tunnel/authentication change;
* requested/negotiated revision change;
* observed client-capability change;
* Binnacle build/config change;
* MCP SDK/FastMCP/tunnel agent change;
* Tool manifest/schema/policy/evaluation profile/case change;
* Pi OS/kernel/device-profile change;
* material regression.

A changed trigger creates a new evaluation ID/bundle. Do not overwrite history or extend
the old ``valid_until``.

45. Dependency and package impact
--------------------------------

Phase 3 direct dependency changes should be minimal:

* the selected authentication verifier/client library, only after live profile selection;
* any existing locked HTTP/crypto dependency should be reused when it safely satisfies
  the selected standard;
* no database, Git, systemd-Python, tunnel-management framework, browser automation,
  hardware, or policy-engine library is introduced merely for Phase 3.

Prefer native ``systemctl``/systemd configuration for setup/verification scripts over a
large service-management library.

Keep ``pip-audit`` mandatory after auth/crypto dependency resolution.

46. Machine-readable contract impact
------------------------------------

Phase 3 does **not** change the five Tool contracts or output schemas merely because the
server becomes remote/authenticated.

The selected controller profile is deployment/security configuration, not a new MCP Tool
manifest.

Existing files consumed as normative inputs remain:

::

   spec/mcp/evaluation-profile.yaml
   spec/mcp/evaluation-cases.yaml
   schemas/mcp/evaluation-manifest.schema.json
   tests/fixtures/mcp/controller-transport-security.yaml

If live evidence exposes a true contradiction in one of those sources, reconcile it in a
separate contract change rather than teaching the evaluator a hidden exception.

47. Import Linter updates
-------------------------

Extend the Phase 2 dependency rules:

* ``binnacle.domain.controller`` remains stdlib-only;
* ``binnacle.ports.controller_auth`` imports domain values only;
* ``binnacle.security.controller`` may implement profile/security logic using domain and
  selected crypto/standards abstractions but not FastMCP Tool semantics;
* ``binnacle.security.middleware`` is an outer ASGI/security adapter and may import the
  authentication port plus bounded ASGI types;
* concrete ``auth_*`` adapter may depend on selected maintained security libraries;
* application/use-case modules receive ``ControllerSecurityContext`` but never raw
  credentials;
* ``binnacle.evaluation`` may depend on JSON/schema/archive/hash utilities and reviewed
  evaluation sources but not ChatGPT UI automation;
* ``composition`` wires the selected authenticator once;
* no inward module imports CLI/composition/systemd/tunnel implementation.

48. Logging changes
-------------------

Phase 3 adds security-safe fields:

* controller ID;
* controller-profile ID/version;
* auth success/failure **category**;
* required/provided scope names where safe;
* credential/assertion ID digest where selected profile safely provides it;
* audience/issuer identity or digest where not sensitive;
* request correlation;
* MCP revision;
* Tool name;
* evaluation ID when an explicit evaluation run is active.

Never log:

* access/refresh token;
* authorization code;
* full ``Authorization`` header;
* cookie;
* raw gateway assertion;
* private key;
* systemd credential content;
* raw machine ID;
* arbitrary forwarded header values;
* full owner-private conversation.

49. CI changes
--------------

Normal GitHub CI remains self-contained and does not require OpenAI credentials or a
real Pi.

Extend the exact-interpreter Phase 1/2 matrix to run:

* controller domain/profile/middleware tests;
* selected-auth adapter fixture tests;
* authenticated MCP integration tests;
* evaluation manifest/redaction/bundle tests;
* systemd/setup asset static tests;
* existing Phase 2 local MCP/revision tests;
* Ruff/format;
* strict MyPy;
* Import Linter;
* ``pip-audit``;
* compiler ``--check``;
* contract/schema validation.

Real-Pi/real-ChatGPT acceptance evidence is a separate manual/empirical gate and must not
be represented by CI mocks.

50. Canonical local validation commands
--------------------------------------

The Phase 3 implementation must retain/pass:

.. code-block:: console

   uv sync --frozen
   uv run python scripts/compile_mcp_registry.py --check
   uv run pytest
   uv run pytest tests/integration/test_authenticated_mcp.py
   uv run pytest tests/integration/test_controller_transport_security.py
   uv run pytest tests/integration/test_evaluation_manifest.py
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests
   uv run lint-imports
   uv run pip-audit
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py
   uv run tox -e py311,py312,py313,quality

CI matrix lanes retain explicit ``uv --python`` selection from Phase 1.

51. Real-Pi operational commands
--------------------------------

A typical implementation run uses reviewed commands equivalent to:

.. code-block:: console

   sudo python scripts/setup_dev_pi.py check --repo /srv/binnacle-dev/repo
   sudo python scripts/setup_dev_pi.py apply --repo /srv/binnacle-dev/repo
   sudo install -o root -g binnacle-dev -m 0640 <reviewed-dev-config> /etc/binnacle/dev.toml
   sudo install -o root -g binnacle-dev -m 0640 <reviewed-controller-profile> /etc/binnacle/controller-profile.toml
   sudo systemctl daemon-reload
   sudo systemctl start binnacle-dev.service
   uv run python scripts/verify_dev_pi.py --config /etc/binnacle/dev.toml --controller-profile /etc/binnacle/controller-profile.toml

Tunnel/app configuration follows the actual current supported product workflow and is
recorded as evidence rather than hard-coded as speculative CLI syntax in this plan.

52. Security invariants
-----------------------

Phase 3 must preserve all of these:

#. main Binnacle MCP/application process is non-root;
#. Binnacle listener remains loopback/private rather than public/LAN wildcard;
#. remote connectivity is not controller authentication;
#. anonymous remote MCP access is unsupported;
#. every accepted remote request has one validated controller profile and stable opaque
   controller ID before Tool dispatch;
#. one active ChatGPT controller profile only;
#. only ``connect``/``observe`` transport scopes are relevant in this read-only phase;
#. session/clientInfo/conversation/source address never grants authority;
#. raw credentials/assertions/cookies/private keys never reach Tools/results/logs/evidence;
#. inbound MCP credential is never forwarded downstream;
#. controller security-critical config cannot be weakened by ordinary environment/CLI
   overrides;
#. Host/Origin/proxy rules fail closed according to the selected profile;
#. health/readiness are not publicly exposed through the MCP tunnel route;
#. Tool catalogue remains exactly the five read-only compatibility-core Tools;
#. no device mutation is possible;
#. evidence uses exact frozen cases/status vocabulary;
#. UI/account/workspace facts come from real observation;
#. local SDK tests cannot promote host support;
#. missing write probe is not evidence of host write denial;
#. evidence contains no reusable authority material;
#. bundle receipt is detached and non-self-referential;
#. unreviewed evidence cannot become runtime ``compatibility_report`` promotion;
#. failure to obtain a secure authentication profile blocks Phase 3 instead of weakening
   the security boundary.

53. Implementation order
------------------------

The future Phase 3 implementation should proceed in this order:

#. add common controller domain/port/profile/middleware seams with fixture-only test
   authenticator;
#. add evaluator/profile/redaction/bundle tooling using existing schemas/cases;
#. add systemd/setup/verify development-Pi assets;
#. deploy the unchanged Phase 2 read-only server locally on the Pi and validate it;
#. revalidate current official ChatGPT private-connectivity/custom-app documentation and
   actual account/workspace UI;
#. configure the selected private tunnel/connectivity path in pre-authenticated/fail-
   closed mode;
#. perform authentication feasibility against the two allowed controller profile kinds;
#. select/freeze exactly one authentication profile;
#. add only that concrete auth adapter/dependency and protected config model;
#. run complete local/CI auth/security fixture tests;
#. deploy the selected authenticated build to the Pi;
#. prove tunnel/direct/invalid-credential bypass failures before live Tool evaluation;
#. initialize a new evaluation workspace/profile snapshot;
#. connect real ChatGPT;
#. run connection/protocol/discovery deterministic cases;
#. run model Tool-selection/read/result/error cases to exact attempt thresholds;
#. run read entitlement and latency/context cases;
#. classify later/optional cases without adding capabilities;
#. redact/verify/finalize evidence bundle and detached receipt;
#. conduct human promotion review;
#. update ``docs/mcp-profile.md`` from the approved evidence;
#. publish/install only the sanitised promoted compatibility summary for
   ``compatibility_report``;
#. rerun exact deployment verification and normal CI for the final implementation head;
#. stop without adding consequential capability.

54. Deterministic acceptance checklist
--------------------------------------

Phase 3 implementation is accepted only when every applicable item is true:

#. Exact candidate Git/build/runtime-manifest/config identities are frozen before live
   evaluation.
#. Development Pi is 64-bit and uses a supported Python 3.11--3.13 interpreter.
#. Source checkout lives outside protected Binnacle state.
#. ``binnacle-dev.service`` runs as non-root from the project ``.venv``.
#. Main service has no ambient/bounding Linux capabilities.
#. Application listener is loopback/private only.
#. ``/healthz`` and ``/readyz`` work locally and are not exposed through the public MCP
   route.
#. Private connectivity path is the current supported ChatGPT mechanism for the tested
   profile or an explicitly reviewed equivalent.
#. Tunnel credentials, when present, are separated from the Binnacle application user.
#. One of the two controller-transport authentication profiles is selected from live
   evidence and versioned.
#. No anonymous/tunnel/source-IP fallback exists.
#. Controller ID derives from validated identity tuple rather than client metadata.
#. Required read-only scopes are enforced before Tool dispatch.
#. Missing/invalid/expired/wrong-audience/wrong-scope fixtures fail at the correct layer.
#. Direct tunnel/local bypass fixture cannot dispatch a Tool.
#. No authentication secret appears in logs/results/evidence.
#. Normal local/CI authenticated MCP tests pass without real production credentials.
#. Evaluation run uses the existing profile/case manifest digests.
#. Every evaluation-manifest profile dimension required by the schema is populated or
   legitimately null where the schema permits null.
#. Actual ChatGPT product/surface/plan/workspace values come from current observation.
#. Actual connection/authentication profile is recorded.
#. Actual Pi model/OS/kernel/architecture/device profile is recorded.
#. Actual SDK/tunnel/build/config/manifest/schema/evaluation digests are recorded.
#. ``endpoint-connect`` reaches authenticated MCP without unauthenticated dispatch.
#. ``protocol-revision-observed`` records real requested/negotiated revision and dispatch
   path.
#. ``tool-discovery-manifest`` proves the real ChatGPT-visible catalogue matches the five
   reviewed Tools.
#. ``model-tool-selection-binnacle-probe`` completes at least 10 attempts and meets its
   frozen oracle/threshold for promotion.
#. ``model-tool-selection-system-inspect`` completes at least 10 attempts and meets its
   frozen oracle/threshold for promotion.
#. ``structured-result-rendering`` completes at least 10 attempts with schema-valid,
   consistent text/structured semantics.
#. ``execution-error-rendering`` completes at least 10 attempts and uses Tool error-result
   semantics rather than 401/403.
#. ``read-entitlement`` completes at least 5 attempts or is honestly classified as host-
   policy-blocked.
#. ``latency-context-cost`` completes at least 20 attempts with p50/p95/p99 and size/context
   observations.
#. No write/idempotency/cancellation/reconnect/concurrency capability is implemented to
   satisfy later frozen cases.
#. Optional Resources/MRTR/Tasks facts are not promoted without behavioral evidence.
#. Catalogue refresh behavior relevant to later promotion is observed without changing
   the Tool set.
#. Evidence files are sanitised and individually hashed.
#. Evaluation manifest validates against the existing schema.
#. Bundle contains the manifest/evidence inventory and no detached receipt.
#. Detached receipt hashes the final bundle/manifest without self-reference.
#. Human review fields are complete before any promotion.
#. ``docs/mcp-profile.md`` reflects the approved evidence and exact limitations.
#. Promoted runtime compatibility summary contains no raw evidence/credentials.
#. Evidence validity/rerun triggers match the frozen evaluation profile.
#. Ruff/format/MyPy/Import Linter/pytest/``pip-audit``/compiler/contract/schema gates pass.
#. Python 3.11/3.12/3.13 CI passes with explicit interpreters.
#. GitHub Actions is green for the exact implementation head.
#. Phase 3 exits with exactly the five read-only Tools and no consequential capability.

55. Planning stop rule
----------------------

This plan is complete when an implementation/evaluation agent can deploy the Phase 2
server to one real development Pi, establish one standards-based authenticated ChatGPT
controller path without weakening the security contract, run the applicable frozen
read-only evaluation cases, produce a reviewable non-self-referential evidence bundle,
and promote an honest compatibility profile without making another architectural
decision about deployment layout, controller identity seams, auth-profile selection
criteria, evidence structure, or Phase-3 acceptance.

Stop here. Do not extend this document into durable consequential operations, write
entitlement probing, workspace mutation, command execution, Git, privileged self-
management, credentials for downstream effects, hardware, or any later Bootstrap phase.
