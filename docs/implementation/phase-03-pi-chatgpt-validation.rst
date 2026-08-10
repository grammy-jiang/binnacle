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

Phase 3 consumes the Phase 2 ``compatibility-core`` server without expanding its
authority. The remote catalogue remains exactly the five read-only Tools and no
consequential device effect becomes possible. The implementation work is deployment,
controller-security integration, evidence capture, and profile promotion.

The first empirical Bootstrap milestone is reached when real ChatGPT can reliably connect
to the selected development Pi, authenticate as the intended controller, discover the
read-only catalogue, call ``binnacle_probe`` and ``system_inspect``, and leave a complete
sanitized evidence record of the actual requested/negotiated MCP behavior.

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

At planning time, current OpenAI product documentation describes ChatGPT custom MCP
connectivity as remote rather than direct-local connectivity, with a Secure MCP Tunnel
path for private/on-premises/developer-machine servers and an application authentication
configuration flow. Product availability and write/modify entitlement are plan/workspace
dependent.

Those facts are planning-time hypotheses only. The Phase 3 implementation run must
re-read current official OpenAI product documentation and inspect the actual ChatGPT
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

3. Prerequisite and exit gate
-----------------------------

Prerequisite
~~~~~~~~~~~~

The Phase 2 implementation described by the merged Phase 2 plan must exist and pass its
local exit gate before remote deployment begins. The candidate build deployed to the Pi
must already have:

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
* Binnacle's MCP/application process runs as a dedicated non-root service identity;
* the application itself remains on loopback or an equally reviewed protected local hop;
* the selected private connectivity path reaches only the intended MCP route;
* every remotely accepted ``/mcp`` request is authenticated before MCP Tool dispatch;
* one stable ``ControllerIdentity`` is derived from the selected live authentication
  profile;
* unauthenticated/direct-bypass requests cannot reach Tool dispatch;
* real ChatGPT connects through the selected app/connector profile;
* ``endpoint-connect`` passes or is classified honestly without weakening
  authentication;
* real ChatGPT can discover the five read-only Tools;
* real ChatGPT can invoke ``binnacle_probe`` and ``system_inspect`` reliably;
* the actual requested and, where applicable, negotiated MCP revision is recorded;
* structured/text result handling and execution-error rendering are exercised through
  the real host;
* applicable frozen evaluation cases meet their exact attempt/oracle rules;
* later/unexercised cases remain present in the evaluation manifest with statuses allowed
  by their own frozen oracle instead of being generalized by phase scope;
* the evidence manifest validates against the existing evaluation schema;
* reviewer decision is embedded in the final manifest before its final digest/archive is
  frozen;
* the evidence bundle receives a detached receipt without self-reference;
* ``docs/mcp-profile.md`` is updated from reviewed evidence rather than expectation;
* no raw token, cookie, full authorization header, private key, reusable gateway
  assertion, or owner-private payload is present in retained evidence;
* the exact deployed implementation head passes its normal CI gates.

If no authentication profile satisfies the mandatory controller-transport contract, the
Phase 3 exit gate is blocked. Do not fall back to anonymous tunnel trust, source IP,
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
idempotency, cancellation, reconnect, concurrency, optional MCP capabilities,
owner-only information handling, and cross-server behavior. Phase 3 does not implement
those capabilities merely to make the manifest look complete. Each unexercised case is
classified only according to that case's own frozen oracle/status rules.

No Phase 4 design appears in this document.

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
* explicit entries for every frozen case, including honest unexercised statuses;
* an observed compatibility profile with actual product/plan/workspace/revision facts;
* explicit residual limitations and rerun triggers.

No consequential-operation authority is added.

6. Exact implementation file set
--------------------------------

The Phase 3 **implementation** work is expected to create or modify the following paths.
This detailed-plan PR itself adds only this document.

6.1 Existing files to modify
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   pyproject.toml
   uv.lock
   .gitignore
   .github/workflows/python.yml
   src/binnacle/application.py
   src/binnacle/composition.py
   src/binnacle/config.py
   src/binnacle/cli.py
   src/binnacle/domain/mcp.py
   src/binnacle/adapters/mcp.py
   src/binnacle/adapters/compatibility.py
   docs/mcp-profile.md

``docs/mcp-profile.md`` is changed only after the real evidence bundle has been reviewed.
Do not replace its unknowns from planning assumptions.

6.2 Controller-security modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   src/binnacle/domain/controller.py
   src/binnacle/ports/controller_auth.py
   src/binnacle/security/
     __init__.py
     controller.py
     middleware.py
     profile.py

Create exactly one selected concrete adapter after the live feasibility gate:

::

   src/binnacle/adapters/auth_gateway.py

or:

::

   src/binnacle/adapters/auth_oauth.py

Do not implement both complete profiles speculatively. The common domain/port/middleware
seam is implemented first; the selected live profile supplies exactly one concrete
adapter.

6.3 Development-Pi assets
~~~~~~~~~~~~~~~~~~~~~~~~~

Create:

::

   deploy/systemd/binnacle-dev.service
   scripts/setup_dev_pi.py
   scripts/verify_dev_pi.py
   docs/operations/development-pi.rst

Create this file only if the selected supported Secure MCP Tunnel/client actually runs as
a customer-hosted persistent process with a documented stable CLI at implementation
time:

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
     digests.py
     bundle.py
   scripts/mcp_evaluation.py

The evaluator consumes the existing evaluation profile, case manifest, and evaluation
manifest schema. It does not invent a new status vocabulary or a second case manifest.

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
     test_evaluation_digests.py
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

The current controller fixture contains example profile/scope values such as
``mcp:read``. Execute those cases against a fixture-specific profile that preserves their
literal semantics. Separately test the selected deployment profile's exact scope
vocabulary. Do not silently alias fixture scope strings to production scope strings or
rewrite the fixture simply to make the selected profile pass.

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
   Dedicated non-root MCP/application service user with primary group ``binnacle``.

``binnacle-dev``
   Development group used only to grant the source checkout the minimum shared
   read/traverse access needed by the service now and to preserve a future development
   workspace ownership seam.

If the selected tunnel uses a local customer-hosted daemon, create a separate non-root
``binnacle-tunnel`` identity rather than giving the main Binnacle process tunnel
credentials/network authority it does not need.

Minimum layout expectations:

* ``/srv/binnacle-dev/repo`` remains a real Git development checkout and is accessible
  through ``binnacle-dev``;
* the ``binnacle`` service has ``binnacle-dev`` as a supplementary group, not as its
  primary protected-control-plane group;
* ``/etc/binnacle`` is owned by ``root:binnacle`` with directory mode no broader than
  ``0750``;
* ``dev.toml`` and ``controller-profile.toml`` are owned ``root:binnacle`` with mode no
  broader than ``0640``;
* future development/executor users that join ``binnacle-dev`` do **not** thereby gain
  access to controller-profile files;
* tunnel credentials, when present, are not readable by the Binnacle application user;
* evaluation evidence is not world-readable;
* no reusable authentication secret exists inside the Git repository or Tool result.

Do not preconfigure later executor/broker users or sockets unless systemd setup needs only
a stable unprivileged identity name; their authority is deferred.

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

The script is stdlib-only so root does not need the project virtual environment.

``check`` is read-only and prints a deterministic plan/result. ``apply`` performs only
the declared Phase 3 setup.

Required preflight
~~~~~~~~~~~~~~~~~~

Before mutation verify:

* Linux + systemd;
* 64-bit architecture;
* selected Debian-family development profile or explicitly recorded equivalent;
* compatible distribution-provided Python, minimum 3.11 and below 3.14;
* exact repository path exists, is a Git checkout, and is not under ``/etc``, ``/var`` or
  another protected system directory;
* ``uv.lock`` and ``pyproject.toml`` exist;
* the service unit source file exists;
* required user/group names are not conflicting with incompatible identities;
* no generated output path escapes declared system directories.

``apply`` may:

* create the ``binnacle`` user/primary group and ``binnacle-dev`` group;
* add ``binnacle`` to ``binnacle-dev`` as a supplementary group;
* create/protect ``/etc/binnacle``, ``/var/lib/binnacle/evaluation``, and
  ``/run/binnacle``;
* install/update the reviewed ``binnacle-dev.service`` unit atomically;
* run ``systemctl daemon-reload``;
* enable the service only when explicit ``--enable`` is supplied;
* report exact manual next steps for project sync, protected config, tunnel, and live
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

Do not run a service from a checkout that has not passed applicable exact-build
validation.

Record before deployment:

* Git commit SHA;
* branch;
* dirty/clean state;
* Phase 2 build digest/runtime-manifest digest;
* Python version;
* ``uv`` version;
* resolved FastMCP/MCP SDK/Uvicorn versions.

The first supported evidence run uses a clean reviewed commit. A deliberately dirty
source checkout is a different profile and cannot reuse clean-build evidence.

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
   Group=binnacle
   SupplementaryGroups=binnacle-dev
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
configuration file for the selected live authentication profile. It contains no raw
private key/token unless the selected standard profile absolutely requires a protected
local reference; reusable secret bytes should be supplied through systemd credentials or
a separate root-controlled credential file/reference.

Both config files are ``root:binnacle`` and no broader than ``0640``. Membership in
``binnacle-dev`` alone grants no protected configuration access.

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
       revocation_checked_at: datetime | None
       revocation_fresh_until: datetime | None
       connection_binding_digest: str | None
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

The concrete HTTP middleware owns extraction of credential/assertion bytes and releases
references after validation. The bytes are sensitive runtime data and are never logged,
persisted, copied into Tool arguments, or attached to the returned security context.

A dedicated non-``repr`` sensitive container may replace raw ``bytes`` if it makes
accidental logging harder. It must not weaken the no-retention rule.

15. Phase 3 read-only transport authorization
---------------------------------------------

The deployment profile uses a minimal read-only vocabulary:

::

   binnacle:connect
   binnacle:observe

Phase 3 defines no ``binnacle:modify``, ``binnacle:execute``, or
``binnacle:self-manage`` entitlement because no such Tool exists.

Before MCP dispatch:

* missing/invalid/expired/revoked/untrusted credentials -> HTTP 401 where the selected
  profile requires it;
* valid controller lacking required ``connect``/``observe`` -> HTTP 403;
* Host/Origin/proxy/profile mismatch -> pre-dispatch transport/security rejection;
* unsupported MCP revision -> protocol rejection;
* valid authenticated read-only call -> MCP Tool dispatch.

A tunnel connection, source IP, loopback peer, session ID, ``clientInfo`` name, or ChatGPT
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

Local unit/integration tests inject deterministic authenticated test contexts. There is
no anonymous Phase 3 remote context.

The five read-only use cases do not use ``controller_id`` as application authority
beyond the pre-dispatch profile/scope check, but safe logs/evidence may record the opaque
ID for correlation.

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
#. create the ChatGPT custom app/draft only as far as needed to establish the actually
   supported authentication setup;
#. record which stable authenticated claims/credentials can reach Binnacle;
#. compare them field-for-field with ``controller-transport.md``;
#. choose exactly one profile using the rules below;
#. freeze the protected profile schema/values and concrete adapter only after evidence is
   sufficient.

Do not run an unauthenticated five-Tool remote server merely to observe traffic.
Pre-authentication feasibility testing rejects before MCP Tool dispatch.

17.2 Trusted gateway assertion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Select ``trusted-gateway-assertion`` only if the current tunnel/gateway provides a
cryptographically protected assertion/channel whose Binnacle-verifiable data includes
the mandatory selected-profile identity/audience/freshness fields and whose protected
local hop cannot be bypassed.

Plain forwarded identity headers, tunnel membership, source IP, or an undocumented opaque
connection marker do not qualify.

If selected, freeze:

* assertion format/version;
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
* revocation/freshness evidence where supplied;
* local peer/socket/loopback trust boundary.

17.3 OAuth resource-server fallback
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If no qualifying gateway assertion exists, select the OAuth resource-server profile only
if current ChatGPT/app configuration and a mature OAuth/OIDC provider can issue
Binnacle-audience credentials that Binnacle can validate according to the
controller-transport contract.

The Phase 3 implementation acts as a resource server, not a custom authorization server.

Freeze:

* canonical issuer;
* canonical Binnacle resource/audience URI;
* signature/introspection authority;
* algorithm allowlist;
* subject requirement;
* authorized client/``azp`` requirement when the real profile supplies it;
* tenant/workspace requirement only when actually supplied and selected;
* token expiration/not-before/issued-at policy;
* required read-only scopes;
* revocation/freshness method;
* credential binding when the actual profile supports it;
* bounded clock skew;
* residual bearer-token risk if proof-of-possession is unavailable.

Opaque tokens are accepted only with authoritative introspection or equivalent verified
validation. No token is trusted based on shape.

If the selected MCP/OAuth profile requires protected-resource metadata, expose only the
standards-defined protected-resource metadata route through the framework/standards
adapter. It is protocol metadata, not a general REST control API. Its resource URI,
authorization-server reference, scope information, and 401 challenge are exact for the
selected profile.

17.4 Neither profile is feasible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If neither profile satisfies mandatory controller identity and remote authentication:

* keep Phase 2 local server behavior;
* record the authentication failure at the exact reached fault layer;
* retain sanitized evidence;
* fail the Phase 3 exit gate;
* do not weaken the controller contract to source-IP/tunnel/anonymous trust.

18. Selected authentication adapter
-----------------------------------

Only the selected adapter becomes a runtime dependency/implementation.

Gateway shape, if selected:

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
worker. Restart losing replay-cache history is recorded as a residual read-only
limitation; no mutating security claim is inferred.

OAuth shape, if selected:

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

Add only the selected adapter's direct dependency to ``pyproject.toml``/``uv.lock``. The
implementation PR documents the selected library/version line, Python 3.11--3.13 support,
maintenance/security posture, ``pip-audit`` result, and why the already locked stack
cannot satisfy the same profile without it.

19. Controller-profile protected configuration
----------------------------------------------

The exact file is security-critical and uses ``extra=forbid`` typed parsing separate
from ordinary environment-overridable settings.

Common fields are equivalent to:

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

Security-critical values are loaded only from the protected file/systemd credential
references. They are not overridden by ``BINNACLE_*`` variables or convenience CLI
flags.

The canonical external resource URI is not replaced by internal loopback/tunnel target
addresses when validating audience.

20. Authentication middleware
-----------------------------

``src/binnacle/security/middleware.py`` owns the smallest ASGI middleware necessary to
authenticate the public ``/mcp`` route before FastMCP dispatch.

Responsibilities:

#. match only the reviewed MCP route;
#. enforce request/header/body limits before expensive authentication where practical;
#. validate exact ``Host``/``:authority`` allowlist;
#. validate ``Origin`` when present according to the selected profile;
#. trust forwarded headers only on the selected validated local gateway boundary;
#. extract the selected credential/assertion without logging it;
#. call ``ControllerAuthenticator``;
#. enforce read-only scopes;
#. attach ``ControllerSecurityContext`` to request-local context inaccessible to model
   arguments;
#. call FastMCP only on success;
#. emit correct bounded 401/403/challenge metadata for the selected profile;
#. clear sensitive temporary references after completion.

``/healthz`` and ``/readyz`` remain local diagnostics and are not exposed through the
public tunnel/app route. Local unauthenticated access to those two minimal routes is
acceptable because the listener remains loopback/private and they reveal only bounded
status.

There is no authentication bypass flag.

21. Host, proxy, Origin, and local-hop rules
--------------------------------------------

Binnacle bind
~~~~~~~~~~~~~

Keep the application on ``127.0.0.1``/``::1`` or a reviewed restricted Unix/private
local hop. Do not bind ``0.0.0.0`` or a LAN address merely because a tunnel exists.

Trusted proxy/gateway
~~~~~~~~~~~~~~~~~~~~~

Forwarded scheme/host/client/identity data is accepted only from the exact configured
gateway identity or protected local socket boundary.

An untrusted local process that reaches loopback cannot create a controller identity by
sending forwarded headers. It must satisfy the selected cryptographic profile.

Host
~~~~

External ``Host``/``:authority`` allowlist is exact. Unexpected hosts and ambiguous
absolute-form targets are rejected before MCP dispatch.

Origin/CORS/cookies
~~~~~~~~~~~~~~~~~~~

No ambient cookie authorization exists. Do not enable wildcard credentialed CORS. A
missing ``Origin`` from a validated non-browser ChatGPT path is handled according to
observed profile evidence; it is not automatic trust.

22. Tunnel/private connectivity setup
------------------------------------

Preferred path
~~~~~~~~~~~~~~

Use the current OpenAI-supported private MCP connectivity mechanism for a private/local
development server when available to the tested profile. At planning time Secure MCP
Tunnel is the preferred candidate; implementation revalidates current support immediately
before setup.

Manual setup is acceptable
~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 3 may require operator/UI actions to enable developer mode, create the custom app,
establish the private endpoint, configure authentication, authenticate the intended
owner, scan/refresh Tools, and select the app in a real ChatGPT conversation.

Do not automate ChatGPT UI or tunnel provisioning merely to make Phase 3 unattended.

Separate tunnel service when applicable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the current tunnel product provides a local persistent agent binary, run it under
``binnacle-tunnel`` with its own systemd unit/credential budget.

The concrete ``ExecStart`` comes from the current official tunnel client/version and is
recorded in the evaluation profile/evidence. This plan deliberately does not invent CLI
flags.

The tunnel target is the local MCP route only, not health/readiness or an entire local
HTTP origin when path restriction is supported.

Tunnel reusable credentials never enter the main Binnacle service environment.

23. ``scripts/verify_dev_pi.py``
-------------------------------

Provide a read-only deployment verifier:

.. code-block:: console

   uv run python scripts/verify_dev_pi.py \
     --config /etc/binnacle/dev.toml \
     --controller-profile /etc/binnacle/controller-profile.toml

It emits human/JSON output and checks:

* architecture/Python/systemd profile;
* exact source checkout/build/runtime-manifest identity;
* clean/dirty Git state as observation only;
* systemd unit enabled/active status using fixed unit names;
* service UID is non-root;
* service primary group is ``binnacle`` and supplementary development access is
  ``binnacle-dev``;
* application listener is loopback/private only;
* local health/readiness;
* direct unauthenticated local ``/mcp`` is rejected once Phase 3 auth is enabled;
* protected config ownership/modes;
* tunnel-agent identity when applicable;
* no tunnel credential appears in Binnacle service environment;
* five-Tool catalogue remains Phase 2-compatible through an authenticated test path.

The script never prints raw credentials/assertions/tokens.

24. Evidence workspace and Git safety
------------------------------------

Add to ``.gitignore``:

::

   /artifacts/mcp-evaluation/

Default operator output:

::

   artifacts/mcp-evaluation/<evaluation_id>/

Pi-side sanitized evidence may be staged under:

::

   /var/lib/binnacle/evaluation/<evaluation_id>/

Raw/sanitized evaluation files are not committed by default. The authoritative
repository may later contain a small reviewed compatibility-profile summary/digest, not
the private evidence corpus.

25. Evaluation command interface
--------------------------------

``scripts/mcp_evaluation.py`` exposes:

.. code-block:: console

   uv run python scripts/mcp_evaluation.py init --output <dir>
   uv run python scripts/mcp_evaluation.py record --output <dir> --case-id <id> ...
   uv run python scripts/mcp_evaluation.py verify --output <dir>
   uv run python scripts/mcp_evaluation.py review --output <dir> ...
   uv run python scripts/mcp_evaluation.py finalize --output <dir>

``init``
   Snapshot exact profile dimensions/digests known before the run and create a bounded
   working manifest.

``record``
   Add one sanitized attempt/evidence reference for an existing frozen ``case_id``. It
   cannot invent a new case/risk class/status.

``verify``
   Validate case IDs, attempt counts, evidence references, profile/case digests,
   redaction metadata, conclusions, and schema consistency. Before final review it may
   validate a draft form whose review fields are explicitly pending in working state; the
   final schema-valid manifest is produced only after ``review``.

``review``
   Require a human reviewer decision and write the final review object **into the working
   manifest before any final manifest/archive digest is frozen**. It records reviewer,
   ``reviewed_at``, and ``approved_for_promotion``. A rejection is still a valid reviewed
   evidence outcome.

``finalize``
   Refuse an unreviewed working manifest. Serialize the reviewed final
   ``evaluation-manifest.json``, validate it against the existing schema, freeze evidence
   inventory, build the deterministic archive, compute final manifest/archive digests,
   and write a detached receipt. No reviewed field changes after this point without a new
   finalization/run identity.

There is no ``--force-pass`` or status-vocabulary override.

26. Evaluation identifiers and versions
--------------------------------------

Use stable values so required schema fields never become ad-hoc strings.

``evaluation_id``
   ``eval_<UTC-compact>_<12-lowercase-hex>``.

``profile_id``
   Use the frozen profile ID from ``spec/mcp/evaluation-profile.yaml`` unless an actual
   product/workspace change requires a separately reviewed profile version.

``probe_release``
   ``phase3-readonly-evaluation-v1`` for this evaluator/probe set.

``dispatcher_version``
   ``mcp-revision-dispatch-v1`` plus the Phase 2 revision-contract digest in evidence.

``oracle_version``
   ``evaluation-cases/<case-manifest-version>`` from the exact frozen case source.

``runner_version``
   ``binnacle-mcp-evaluation/1.0.0`` plus the runner source/build digest in evidence.

``completed_at``
   The time the reviewed final manifest is serialized immediately before archive
   construction.

These strings identify behavior families; exact code/file digests remain separate
profile/evidence fields.

27. Profile-dimension collection
--------------------------------

The evaluator fills every required ``#/$defs/profile`` field from the existing evaluation
schema.

ChatGPT/UI dimensions
~~~~~~~~~~~~~~~~~~~~~

Record actual:

* product;
* surface;
* account plan;
* workspace type;
* workspace-policy digest when a stable export/config exists, otherwise ``null`` only
  because the schema permits it;
* developer-mode/app availability and observed permission behavior.

Do not silently populate these from the repository's initial ``Pro`` hypothesis.

Connectivity/authentication dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Record:

* connection method/product identity;
* selected controller profile ID/version/kind;
* canonical public MCP resource URI in sanitized/profile-safe form;
* tunnel/gateway identity/version;
* tunnel/gateway artifact digest when a local artifact exists;
* authentication-profile configuration digest excluding secret bytes;
* opaque controller ID and safe identity-field presence/absence, never raw credential.

Binnacle/server dimensions
~~~~~~~~~~~~~~~~~~~~~~~~~~

Record:

* build digest/version;
* sanitized config digest;
* runtime Tool-manifest digest;
* schema-registry digest;
* policy-bundle digest defined below;
* MCP SDK name/version/installed-distribution digest;
* evaluation profile/case digests;
* probe/dispatcher/oracle/runner versions;
* intended revision set.

Pi dimensions
~~~~~~~~~~~~~

Record bounded:

* Pi model from a fixed implementation-owned device-tree source;
* OS;
* kernel;
* architecture;
* selected device-profile name.

Raw machine ID is not evidence.

Observed MCP dimensions
~~~~~~~~~~~~~~~~~~~~~~~

Record separately:

* revision requested by the real client when observable;
* negotiated/session revision where applicable;
* dispatch path actually used;
* observed client capabilities as sanitized canonical JSON plus digest.

Never infer one from another.

28. Required digest algorithms
------------------------------

28.1 Binnacle configuration digest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``binnacle_config_sha256`` hashes canonical JSON of a sanitized resolved configuration
projection containing behavior-relevant non-secret fields:

* runtime profile;
* server bind/port/limits;
* logging mode where evidence behavior depends on it;
* authentication profile ID/version/kind;
* canonical resource/audience URI;
* required scopes;
* allowed Host/Origin policy;
* algorithm/freshness/revocation mode names;
* secret/key reference identities or public-key digests, never secret bytes.

A material change creates a new evaluation profile/run.

28.2 Policy-bundle digest
~~~~~~~~~~~~~~~~~~~~~~~~~

The evaluation schema requires non-null ``policy_bundle_sha256`` even though Phase 3 does
not yet implement a general PolicyEngine.

Define a conservative evaluation policy identity:

.. code-block:: json

   {
     "format": "phase3-policy-bundle-v1",
     "spec_policy_files": [
       {"path": "<sorted repo-relative path>", "sha256": "..."}
     ],
     "controller_profile_sha256": "...",
     "runtime_manifest_sha256": "...",
     "revision_contract_sha256": "..."
   }

``spec_policy_files`` contains every regular reviewed ``*.yaml``/``*.json`` file under
``spec/policy`` in lexicographic relative-path order. Hash exact file bytes. Hash the
canonical JSON object above for ``policy_bundle_sha256``.

This is an evaluation identity of enforced/reviewed policy inputs, not a new runtime
policy language. Including the full policy directory is deliberately conservative: an
unrelated policy edit may trigger extra reevaluation, but a relevant policy edit cannot
be missed.

28.3 Evaluation-profile/case digests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``evaluation_profile_sha256`` is SHA-256 of exact bytes of
``spec/mcp/evaluation-profile.yaml``.

``evaluation_cases_sha256`` is SHA-256 of exact bytes of
``spec/mcp/evaluation-cases.yaml`` and must equal the case-manifest digest frozen in the
evaluation profile. ``init`` fails if they diverge.

28.4 MCP SDK artifact digest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``mcp_sdk_artifact_sha256`` identifies the **installed SDK distribution bytes actually
executing on the Pi**, not merely the version string.

Compute ``python-distribution-content-v1`` by enumerating regular files belonging to the
installed ``mcp`` distribution through ``importlib.metadata``, excluding mutable cache
files, hashing ``relative-path NUL file-sha256 LF`` records in sorted order, then hashing
the canonical inventory.

Record the algorithm and installed version in a sanitized evidence file referenced by the
manifest. This avoids guessing which lock-file wheel was selected while still binding the
actual runtime SDK code.

28.5 Tunnel/gateway artifact digest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If a local tunnel/gateway executable/package exists, hash the exact local executable or
installed distribution using a documented content-digest method and populate
``tunnel_or_gateway_artifact_sha256``.

If the connectivity product is entirely managed and exposes no local artifact, the field
remains ``null`` because the evaluation schema permits null; retain the observable
product/connection identity/version/policy evidence instead.

28.6 Tool/schema/build identities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use Phase 2 runtime/build/catalogue/schema digests directly. Do not recompute a competing
Tool-manifest canonicalization in the evaluator.

29. Evidence file model and redaction
-------------------------------------

Every retained evidence payload receives:

* stable ``evidence_id``;
* relative path;
* SHA-256;
* media type;
* information class;
* ``redacted=true`` before finalization.

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
scanning is an additional check, not the sole strategy.

Human UI screenshots/transcripts require explicit reviewer redaction before final
inventory.

30. Evidence manifest, archive, and non-self-reference
-----------------------------------------------------

The final bundle layout is:

::

   evaluation-manifest.json
   evidence/
     <sanitized evidence payload files>

``evaluation-manifest.json`` inventories files under ``evidence/`` in
``evidence_files``. It does **not** list itself as an ``evidence_files`` entry because
that would require a self-digest. The evaluation profile's
``evidence_files_include_manifest: true`` is satisfied by including the manifest as a
top-level bundle member, not by making the manifest inventory/hash itself.

If a future normative schema/contract explicitly requires self-inventory instead of
bundle inclusion, stop and reconcile that contradiction before implementation; do not
invent a recursive digest.

Finalize order is exact:

#. all case attempts/evidence collected;
#. all evidence payloads sanitized and hashed;
#. draft conclusions computed;
#. human review performed;
#. reviewer fields and approval/rejection written to working manifest;
#. reviewed final manifest serialized and schema-validated;
#. manifest SHA-256 computed;
#. deterministic archive built containing reviewed final manifest + evidence payloads;
#. bundle SHA-256 computed;
#. detached receipt written **outside** the bundle.

No manifest field changes after step 6 without creating a new finalization/run identity.

Deterministic archive construction fixes entry order, normalized paths, owner/group
metadata, permissions, and timestamp policy before hashing.

Receipt conforms to ``#/$defs/bundleReceipt`` and contains schema version, bundle digest,
manifest digest, profile ID, and creation time. The receipt is not inside the archive.

31. Every case result requires evidence
---------------------------------------

The evaluation schema requires at least one ``evidence_ref`` for every case result.
Therefore even an unexercised/status-only case must reference concrete evidence supporting
that classification.

Create one sanitized capability-scope evidence file during ``init``/deployment
verification, for example:

::

   evidence/phase3-capability-scope.json

It records exact build/catalogue digests and proves which capabilities are absent from the
Phase 3 server (write probes, durable operations, Resources, Tasks, MRTR, owner-only
surface, second Binnacle server, and so on).

A case classified ``server-not-implemented`` or ``not-applicable`` may reference this
file only when its own frozen oracle permits that status for the observed condition.

A ``not-tested`` case references a sanitized test-plan/scope evidence record explaining
why it was not exercised and must not be promoted.

``record`` refuses to create a case-result entry without at least one valid evidence ID.

32. Server-side evaluation diagnostics
--------------------------------------

For an explicitly active evaluation run, record sanitized structured events containing
only:

* evaluation ID;
* timestamp;
* request correlation ID;
* opaque controller ID;
* authentication profile ID/version;
* authentication result category;
* safe issuer/audience/client/owner-boundary presence/digest values where permitted;
* revocation/freshness/binding outcome categories;
* MCP requested/negotiated revision;
* Tool name/version;
* result classification;
* latency;
* catalogue/build/config digests;
* bounded failure code.

Never record raw authorization data.

Use journald + bounded collection or a dedicated restricted evaluation file; do not add
SQLite solely for Phase 3 evidence.

33. Frozen-case execution rules
-------------------------------

Use ``spec/mcp/evaluation-cases.yaml`` exactly. Do not apply generic phase-level status
rules that contradict a specific case oracle.

33.1 Required live read-only cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``endpoint-connect``
   Minimum 1 deterministic attempt. Prove authenticated request observed and no
   unauthenticated Tool dispatch.

``protocol-revision-observed``
   Minimum 1. Invoke ``binnacle_probe`` and record actual requested/negotiated revision
   and dispatch path.

``tool-discovery-manifest``
   Minimum 1. Compare real-host discovery with reviewed runtime catalogue.

``model-tool-selection-binnacle-probe``
   Minimum 10 independent attempts using the frozen prompt/oracle.

``model-tool-selection-system-inspect``
   Minimum 10 independent attempts using the frozen prompt/oracle.

``structured-result-rendering``
   Minimum 10 attempts because its risk class is
   ``tool_selection_and_result_rendering``.

``execution-error-rendering``
   Minimum 10 attempts; canonical Tool error result must not become HTTP auth error.

``read-entitlement``
   Minimum **5 attempts regardless of whether the expected conclusion is supported or
   host-policy-blocked**. A single transient UI/policy block is not enough to promote a
   blocked read-entitlement conclusion. If fewer than five attempts are available, keep
   the axis unpromoted/``not-tested`` with evidence of incomplete sampling.

``latency-context-cost``
   Minimum 20 attempts. Record p50/p95/p99, metadata/result bytes, and context/token
   estimate where observable.

33.2 Later mutating/durable cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not implement the required server capability for:

* ``write-entitlement-and-confirmation``;
* ``confirmation-decline``;
* ``idempotency-lost-response``;
* ``uncertain-no-auto-retry``;
* ``operation-cancellation``;
* ``reconnect-status-reconciliation``;
* ``concurrent-idempotency-race``.

Classify each only according to its exact frozen oracle/profile rules. Where the profile's
probe-missing rule permits ``server-not-implemented``, use that with capability-scope
evidence. Do not infer host write denial from missing Binnacle write Tools.

33.3 Optional modern MCP probes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``resources-probe`` and ``tasks-probe`` have explicit
``server_probe_not_promoted`` not-applicable conditions and may use ``not-applicable``
when Phase 3 has not promoted those probes.

``mrtr-elicitation-probe`` has a different oracle: legacy negotiation may make it
``not-applicable``; target-era absence may instead be blocked by host/client capability.
Follow the exact case rule rather than treating every optional feature the same.

A client capability declaration without behavioral exercise is
``declared-unexercised``, not observed support.

33.4 Owner-only result probe
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``owner-only-result-probe`` may be ``not-applicable`` only when the frozen condition
``owner_only_surface_not_available`` is actually observed/supported by evidence. Do not
create a synthetic owner-only payload path in Binnacle merely to exercise it.

33.5 Cross-server case
~~~~~~~~~~~~~~~~~~~~~~

``cross-server-normal-result`` has **no** ``not_applicable_when`` or
``server_probe_not_promoted`` oracle. Phase 3 must therefore not label it
``not-applicable`` or ``server-not-implemented`` merely because a second server is
outside Binnacle scope.

Unless the actual test profile already has two MCP servers connected and the frozen case
is run as specified, record the case as ``not-tested`` with scope/test-plan evidence and
do not promote ``cross_server_behavior``.

If two servers are already available without expanding Binnacle, the case may be run
exactly as frozen. Do not connect/build a second Binnacle server solely for this phase.

34. Real ChatGPT execution procedure
-----------------------------------

Freeze candidate
~~~~~~~~~~~~~~~~

Record exact Git/build/config/policy/SDK/tunnel/controller-profile/evaluation identities
and confirm local service health/readiness.

Verify bypass failure
~~~~~~~~~~~~~~~~~~~~~

Before ChatGPT connection prove:

* direct unauthenticated local/public MCP request cannot dispatch a Tool;
* invalid/expired/wrong-audience/wrong-scope fixture is rejected at the correct layer;
* public tunnel route does not expose health/readiness when path restriction exists;
* main listener is not public/LAN-bound.

Connect custom app
~~~~~~~~~~~~~~~~~~

Create/select the real ChatGPT custom MCP app using the selected private endpoint and
authentication profile. Record actual product/plan/workspace configuration shown by UI.

Authenticate
~~~~~~~~~~~~

Complete normal user authentication. Do not copy credentials into prompts, Tool
arguments, screenshots, or notes.

Discovery/protocol
~~~~~~~~~~~~~~~~~~

Run connection/revision/discovery cases before free-form prompts. Capture sanitized
server/wire evidence and the exact catalogue presented by ChatGPT.

Tool selection/result/error
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the frozen selection, structured-result, execution-error, and read-entitlement cases
to their exact thresholds.

Latency/context
~~~~~~~~~~~~~~~

Run the 20-attempt read-only performance/context case without adding performance
optimization during measurement.

Classify remaining cases
~~~~~~~~~~~~~~~~~~~~~~~~

Create an evidence-backed result entry for every remaining frozen case using only that
case's allowed status/oracle semantics. In particular, cross-server remains ``not-tested``
unless actually run.

Review/finalize
~~~~~~~~~~~~~~~

Sanitize -> verify draft -> human review -> write review fields -> serialize/validate
final manifest -> archive -> detached receipt. Never review/approve after the final
manifest/archive digest is frozen.

35. Catalogue refresh observation
---------------------------------

Observe later-promotion-relevant refresh behavior without adding a Tool:

* record whether UI exposes Scan/Refresh;
* record whether re-scanning unchanged server preserves same catalogue;
* record displayed change/review behavior for unchanged manifest;
* do not mutate manifest solely to force a refresh experiment;
* classify dynamic/list-change support only from actual observation.

36. Compatibility report after evidence promotion
-------------------------------------------------

Phase 2 ``compatibility_report`` reads a no-live-evidence baseline. Phase 3 may replace
that adapter with a reader of **only a reviewed promoted summary**, not raw UI evidence.

Use:

::

   /var/lib/binnacle/evaluation/current-profile.json

Promotion requires:

* final schema-valid reviewed manifest;
* bundle/receipt digests verify;
* reviewer fields complete;
* profile/case match verified;
* evidence complete and sanitized;
* ``approved_for_promotion=true``.

Runtime reader validates summary/profile digest before use. If no promoted summary exists,
keep Phase 2 ``not-tested`` baseline.

``compatibility_report`` never reads screenshots/transcripts/raw wire logs or credentials.

37. Updating ``docs/mcp-profile.md``
-----------------------------------

Update only from the reviewed final evidence manifest.

Observed-profile section contains:

* product/surface;
* actual plan/workspace type/policy digest where available;
* connection method;
* selected authentication profile ID/version;
* Binnacle build/config/policy/SDK/tunnel identities;
* Pi profile;
* intended/requested/negotiated revisions;
* observed client capabilities digest;
* per-axis canonical status;
* bundle/manifest/receipt digest references;
* validity dates/rerun triggers;
* limitations.

Do not copy raw credentials, private endpoint secrets, private transcripts, or restricted
evidence into the human profile.

No status becomes ``observed-supported`` without the frozen case/oracle/attempt
requirements.

38. Evaluation review gate
--------------------------

Automation cannot self-approve the evaluation.

Before ``review`` can write ``approved_for_promotion=true``:

* reviewer identity is known;
* exact profile dimensions confirmed;
* frozen case-manifest digest confirmed;
* every frozen case ID has a case-result entry and at least one evidence reference;
* every axis proposed for promotion meets its risk-class attempt threshold;
* blocked conclusions meet the same minimum attempt threshold when promotion relies on a
  repeated block (for example five read-entitlement attempts);
* pass/fail/blocked totals are internally consistent;
* evidence references resolve/digests match;
* redaction declaration true and independently spot-checked;
* no contradictory valid run unresolved;
* conclusions use exact status vocabulary and case-specific oracles;
* validity end is no more than configured maximum days;
* rerun triggers match frozen profile;
* evidence supports every promoted axis.

A reviewer may set ``approved_for_promotion=false`` and still finalize a valid failed or
blocked evidence bundle.

39. Controller-transport security tests
---------------------------------------

Reuse mandatory fixture semantics and execute selected-profile tests.

At minimum prove:

* missing credential -> no Tool dispatch;
* malformed credential -> no Tool dispatch;
* expired credential/assertion -> no Tool dispatch;
* wrong issuer -> rejected when selected profile uses issuer;
* wrong audience/resource -> rejected;
* wrong subject/authorized client/owner boundary -> rejected when required;
* missing read scope -> 403;
* replay/freshness rule enforced to selected read-only profile extent;
* session/controller mismatch rejected;
* tunnel/gateway direct bypass rejected;
* untrusted forwarded identity headers rejected;
* Host/authority mismatch rejected;
* unexpected Origin rejected where selected profile requires it;
* oversized auth/header/body rejected before Tool dispatch;
* raw credential never appears in logs/results/evidence;
* inbound MCP credential never forwarded downstream;
* authentication failure stays 401/403 rather than Tool execution error.

Fixture literals remain literal. A fixture-specific test profile may require ``mcp:read``
while the selected deployment profile requires ``binnacle:connect`` and
``binnacle:observe``; both must pass their own exact expectations without hidden aliasing.

40. Selected-profile MCP integration test
-----------------------------------------

``tests/integration/test_authenticated_mcp.py`` starts the actual Phase 3 ASGI application
on loopback with deterministic test profile/keys or a standards-compliant fake verifier.

Positive path:

#. establish valid selected-profile authentication;
#. list five Tools;
#. call ``binnacle_probe``;
#. call ``system_inspect``;
#. assert opaque controller identity exists in request context;
#. assert only selected read-only scopes are required;
#. assert response contracts remain Phase 2-compatible.

Negative path proves unauthenticated/insufficient-scope/identity mismatch never invokes a
Tool binding.

Normal CI does not require real OpenAI credentials/tunnel/ChatGPT.

41. Systemd/deployment tests
----------------------------

Static/system tests verify:

* service unit ``User=binnacle`` and ``Group=binnacle``;
* ``SupplementaryGroups=binnacle-dev`` only for source access;
* one-worker/source-checkout ExecStart;
* no shell wrapper in ExecStart;
* no secret environment assignment;
* ``NoNewPrivileges=yes``;
* no ambient/bounding capabilities;
* no public bind encoded in unit/config fixture;
* protected config owned by ``root:binnacle``, not ``binnacle-dev``;
* setup script idempotency under temporary-root fixture where practical;
* setup refuses unsafe paths;
* verification script redacts sensitive data.

A real-Pi test additionally runs ``systemd-analyze verify`` on installed unit(s).

42. Real-Pi deployment evidence
------------------------------

Capture sanitized results for:

.. code-block:: console

   uname -m
   python3 --version
   systemctl show binnacle-dev.service --property=User,Group,MainPID,ActiveState,SubState
   ss -ltnp
   curl --fail http://127.0.0.1:8000/healthz
   curl --fail http://127.0.0.1:8000/readyz

Sanitize unrelated host services/addresses rather than retaining a complete unbounded
host dump.

Also capture:

* exact repo commit/dirty state;
* ``binnacle version``;
* build/runtime-manifest/catalogue digests;
* config/policy digest evidence;
* dependency/runtime versions;
* MCP SDK installed-distribution digest;
* bounded service journal startup excerpt;
* tunnel/gateway identity/version/artifact digest where applicable.

43. Exact ChatGPT attempt evidence
---------------------------------

For each live attempt retain enough to reconstruct:

* case ID;
* timestamp;
* frozen prompt/action;
* Tool selection/call outcome;
* sanitized Tool arguments;
* server request correlation ID;
* requested/negotiated revision;
* authentication outcome/opaque controller ID;
* schema-validation outcome;
* model-visible result/error behavior;
* latency;
* pass/fail/blocked oracle result;
* bounded UI observation/screenshot reference where required.

Do not retain unrelated conversation history.

44. Failure classification
--------------------------

Examples:

``account cannot create/connect custom MCP app``
   Host-policy fault when the actual product/account/workspace blocks setup independently
   of Binnacle protocol behavior.

``tunnel cannot reach local endpoint``
   Connectivity/server/tunnel fault; do not label protocol failure without protocol
   evidence.

``authentication cannot establish mandatory identity``
   Authentication failure; Phase 3 blocked; do not bypass.

``wrong/unsupported revision reaches server``
   Protocol failure.

``Tool visible with wrong metadata``
   Server/discovery/schema failure.

``ChatGPT repeatedly selects wrong Tool``
   Tool-selection failure when the intended frozen layer was reached.

``result schema valid server-side but UI drops structure``
   Host/result-handling evidence; classify per frozen oracle.

``write case lacks required write probe``
   Use only the status allowed by that case/profile's probe-missing rule; do not infer
   host write denial.

``cross-server case not executed because no second server``
   ``not-tested`` with scope/test-plan evidence; do not use ``not-applicable`` or
   ``server-not-implemented`` because the frozen case has no such oracle.

45. Rerun/expiry semantics
--------------------------

Promoted evidence is valid for at most the existing profile's 30-day window and expires
sooner on a rerun trigger.

Material triggers include:

* ChatGPT product/plan/workspace-policy change;
* custom-app/developer-mode policy change;
* connection/tunnel/authentication change;
* requested/negotiated revision change;
* observed client-capability change;
* Binnacle build/config/policy change;
* MCP SDK/FastMCP/tunnel agent change;
* Tool manifest/schema/evaluation profile/case change;
* Pi OS/kernel/device-profile change;
* material regression.

A trigger creates a new evaluation ID/bundle. Do not overwrite history or extend old
``valid_until``.

46. Dependency impact
---------------------

Phase 3 dependency changes remain minimal:

* add the selected authentication verifier/client library only after live profile
  selection;
* reuse locked HTTP/crypto dependencies when they safely satisfy the selected standard;
* do not add database, Git, systemd-Python, tunnel-management framework, browser
  automation, hardware, or policy-engine libraries merely for Phase 3.

Prefer native systemd/``systemctl`` for setup/verification scripts over a service
framework.

Keep ``pip-audit`` mandatory after auth/crypto dependency resolution.

47. Machine-readable contract impact
------------------------------------

Phase 3 does not change the five Tool contracts/output schemas merely because the server
becomes remote/authenticated.

The selected controller profile is deployment/security configuration, not a new Tool
manifest.

Existing normative inputs remain:

::

   spec/mcp/evaluation-profile.yaml
   spec/mcp/evaluation-cases.yaml
   schemas/mcp/evaluation-manifest.schema.json
   tests/fixtures/mcp/controller-transport-security.yaml

If live evidence exposes a true contradiction, reconcile it in a separate contract
change rather than teaching evaluator/runtime code a hidden exception.

48. Import Linter updates
-------------------------

Extend Phase 2 rules:

* ``binnacle.domain.controller`` remains stdlib-only;
* ``binnacle.ports.controller_auth`` imports domain values only;
* ``binnacle.security.controller`` may implement profile/security logic using domain and
  selected standards abstractions but not FastMCP Tool semantics;
* ``binnacle.security.middleware`` is an outer ASGI/security adapter;
* concrete ``auth_*`` adapter may depend on selected maintained security libraries;
* application/use-case modules receive ``ControllerSecurityContext`` but never raw
  credentials;
* ``binnacle.evaluation`` may depend on JSON/schema/archive/hash utilities and reviewed
  evaluation sources but not ChatGPT UI automation;
* ``composition`` wires selected authenticator once;
* no inward module imports CLI/composition/systemd/tunnel implementation.

49. Logging changes
-------------------

Add safe fields:

* controller ID;
* controller-profile ID/version;
* auth success/failure category;
* required/provided scope names where safe;
* credential/assertion ID digest where safe;
* audience/issuer identity or digest where not sensitive;
* revocation/freshness/binding outcome category;
* request correlation;
* MCP revision;
* Tool name;
* evaluation ID when active.

Never log access/refresh token, authorization code, full ``Authorization`` header, cookie,
raw gateway assertion, private key, systemd credential content, raw machine ID, arbitrary
forwarded header values, or full owner-private conversation.

50. CI changes
--------------

Normal GitHub CI remains self-contained and does not require OpenAI credentials or a real
Pi.

Extend exact-interpreter Phase 1/2 matrix to run:

* controller domain/profile/middleware tests;
* selected-auth adapter fixture tests;
* authenticated MCP integration tests;
* evaluation digest/manifest/redaction/bundle tests;
* systemd/setup asset static tests;
* existing Phase 2 local MCP/revision tests;
* Ruff/format;
* strict MyPy;
* Import Linter;
* ``pip-audit``;
* compiler ``--check``;
* contract/schema validation.

Real-Pi/real-ChatGPT evidence is a separate manual/empirical gate and is never represented
by CI mocks.

51. Canonical local validation commands
--------------------------------------

The Phase 3 implementation retains/passes:

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

52. Real-Pi operational commands
--------------------------------

Typical implementation run uses reviewed commands equivalent to:

.. code-block:: console

   sudo python scripts/setup_dev_pi.py check --repo /srv/binnacle-dev/repo
   sudo python scripts/setup_dev_pi.py apply --repo /srv/binnacle-dev/repo
   sudo install -o root -g binnacle -m 0640 <reviewed-dev-config> /etc/binnacle/dev.toml
   sudo install -o root -g binnacle -m 0640 <reviewed-controller-profile> /etc/binnacle/controller-profile.toml
   sudo systemctl daemon-reload
   sudo systemctl start binnacle-dev.service
   uv run python scripts/verify_dev_pi.py --config /etc/binnacle/dev.toml --controller-profile /etc/binnacle/controller-profile.toml

Tunnel/app configuration follows the actual supported product workflow and is recorded as
evidence rather than hard-coded as speculative CLI syntax.

53. Security invariants
-----------------------

Phase 3 must preserve:

#. main MCP/application process is non-root;
#. protected controller config uses ``root:binnacle`` and is not exposed through
   ``binnacle-dev`` membership;
#. listener remains loopback/private;
#. remote connectivity is not controller authentication;
#. anonymous remote MCP unsupported;
#. every accepted remote request has one validated controller profile/opaque controller
   ID before Tool dispatch;
#. one active ChatGPT controller profile only;
#. only selected read-only transport scopes apply;
#. session/clientInfo/conversation/source address never grants authority;
#. raw credentials/assertions/cookies/private keys never reach Tools/results/logs/evidence;
#. inbound MCP credential never forwarded downstream;
#. security-critical config cannot be weakened by ordinary environment/CLI overrides;
#. Host/Origin/proxy rules fail closed;
#. health/readiness not publicly exposed through tunnel route;
#. Tool catalogue remains exactly five read-only compatibility-core Tools;
#. no device mutation possible;
#. evidence uses exact frozen cases/status vocabulary/oracles;
#. blocked conclusions satisfy required attempt thresholds;
#. cross-server case remains ``not-tested`` unless actually run as frozen;
#. every case result has at least one evidence reference;
#. required evaluation profile digests/version fields have deterministic sources;
#. policy-bundle digest is non-null and reproducible;
#. UI/account/workspace facts come from real observation;
#. local SDK tests cannot promote host support;
#. missing write probe is not host write denial;
#. evidence contains no reusable authority material;
#. human review is embedded before final manifest/archive hashing;
#. bundle receipt is detached/non-self-referential;
#. unreviewed evidence cannot become runtime compatibility promotion;
#. failure to obtain secure auth blocks Phase 3 rather than weakening security.

54. Implementation order
------------------------

Implement in this order:

#. add common controller domain/port/profile/middleware seams with fixture-only test
   authenticator;
#. add evaluator/profile/digest/redaction/bundle tooling using existing schemas/cases;
#. add systemd/setup/verify development-Pi assets with protected group separation;
#. deploy unchanged Phase 2 read-only server locally on Pi and validate it;
#. revalidate current official ChatGPT private-connectivity/custom-app documentation and
   actual account/workspace UI;
#. configure selected private connectivity in pre-authenticated/fail-closed mode;
#. perform auth feasibility against the two allowed controller profile kinds;
#. select/freeze exactly one authentication profile;
#. add only selected concrete auth adapter/dependency and protected config model;
#. run complete local/CI auth/security fixture tests;
#. deploy selected authenticated build to Pi;
#. prove tunnel/direct/invalid-credential bypass failures before live Tool evaluation;
#. initialize evaluation workspace/profile/digest snapshot;
#. connect real ChatGPT;
#. run connection/protocol/discovery deterministic cases;
#. run Tool-selection/read/result/error cases to exact thresholds;
#. run five read-entitlement attempts even when blocked;
#. run latency/context case;
#. classify every remaining frozen case according to its own oracle, with cross-server
   kept ``not-tested`` unless actually run;
#. sanitize/verify evidence;
#. conduct human review and write review fields;
#. serialize/validate final manifest;
#. build/hash archive and write detached receipt;
#. update ``docs/mcp-profile.md`` from reviewed evidence;
#. publish/install only sanitized promoted compatibility summary;
#. rerun exact deployment verification and normal CI for final implementation head;
#. stop without adding consequential capability.

55. Deterministic acceptance checklist
--------------------------------------

Phase 3 implementation is accepted only when every applicable item is true:

#. Candidate Git/build/runtime-manifest/config/policy identities frozen before live run.
#. Development Pi is 64-bit and uses Python 3.11--3.13.
#. Source checkout lives outside protected controller state.
#. ``binnacle-dev.service`` runs as ``User=binnacle``, ``Group=binnacle``, with
   ``SupplementaryGroups=binnacle-dev``.
#. Protected config is ``root:binnacle`` and not readable merely through development
   group membership.
#. Main service has no ambient/bounding Linux capabilities.
#. Application listener is loopback/private only.
#. Health/readiness local-only and not public-tunnel routes.
#. Private connectivity path is current supported ChatGPT mechanism or reviewed
   equivalent.
#. Tunnel credentials, when present, separated from application user.
#. One of two controller-transport auth profiles selected from live evidence/versioned.
#. No anonymous/tunnel/source-IP fallback.
#. Controller ID derives from validated identity tuple.
#. Required read-only scopes enforced before Tool dispatch.
#. Missing/invalid/expired/wrong-audience/wrong-scope fixtures fail at correct layer.
#. Direct tunnel/local bypass cannot dispatch Tool.
#. No auth secret appears in logs/results/evidence.
#. Local/CI authenticated MCP tests pass without production credentials.
#. Evaluation uses exact frozen profile/case digests.
#. ``policy_bundle_sha256`` is non-null and reproducibly derived from policy inventory,
   controller profile, runtime manifest, and revision contract.
#. ``mcp_sdk_artifact_sha256`` binds installed SDK distribution bytes.
#. Tunnel/gateway artifact digest is recorded when a local artifact exists or legitimately
   null when schema/product has no local artifact.
#. Probe/dispatcher/oracle/runner versions have deterministic declared sources.
#. Every schema-required profile dimension populated or legitimately null.
#. Actual ChatGPT product/surface/plan/workspace values come from observation.
#. Actual connection/auth profile recorded.
#. Pi model/OS/kernel/architecture/device profile recorded.
#. ``endpoint-connect`` proves authenticated MCP with no unauthenticated dispatch.
#. ``protocol-revision-observed`` records real requested/negotiated revision/path.
#. ``tool-discovery-manifest`` proves five reviewed ChatGPT-visible Tools.
#. ``model-tool-selection-binnacle-probe`` >=10 attempts and frozen oracle met for
   promotion.
#. ``model-tool-selection-system-inspect`` >=10 attempts and frozen oracle met.
#. ``structured-result-rendering`` >=10 attempts with schema/text consistency.
#. ``execution-error-rendering`` >=10 attempts and Tool-error semantics.
#. ``read-entitlement`` has >=5 attempts before either supported or host-policy-blocked
   conclusion is promoted.
#. ``latency-context-cost`` >=20 attempts with p50/p95/p99/size/context observations.
#. No write/durable capability implemented to satisfy later cases.
#. Optional Resources/MRTR/Tasks statuses follow their individual frozen oracles.
#. Owner-only status follows its explicit frozen not-applicable condition only when true.
#. ``cross-server-normal-result`` is ``not-tested`` unless its two-server setup/action was
   actually exercised; it is never phase-generically relabeled.
#. Every frozen case has a case-result entry with >=1 valid evidence reference.
#. Catalogue refresh behavior observed without changing Tool set.
#. Evidence payloads sanitized/individually hashed.
#. Human reviewer decision written before final manifest digest/archive creation.
#. Final manifest validates against existing schema.
#. ``evidence_files`` does not self-inventory the manifest; bundle still includes final
   manifest as top-level member.
#. Bundle contains reviewed final manifest + evidence and no receipt.
#. Detached receipt hashes final bundle/manifest without self-reference.
#. ``docs/mcp-profile.md`` reflects approved evidence/limitations.
#. Promoted runtime compatibility summary contains no raw evidence/credentials.
#. Validity/rerun triggers match frozen profile.
#. Ruff/format/MyPy/Import Linter/pytest/``pip-audit``/compiler/contract/schema gates pass.
#. Python 3.11/3.12/3.13 CI passes with explicit interpreters.
#. GitHub Actions green for exact implementation head.
#. Phase 3 exits with exactly five read-only Tools and no consequential capability.

56. Planning stop rule
----------------------

This plan is complete when an implementation/evaluation agent can deploy the Phase 2
server to one real development Pi, establish one standards-based authenticated ChatGPT
controller path without weakening the security contract, run the applicable frozen
read-only evaluation cases, create evidence-backed entries for all remaining frozen
cases, perform human review before final hashing, produce a non-self-referential evidence
bundle/receipt, and promote an honest compatibility profile without making another
architectural decision about deployment layout, controller identity seams, auth-profile
selection criteria, evaluation digests, evidence structure, or Phase-3 acceptance.

Stop here. Do not extend this document into durable consequential operations, write
entitlement probing, workspace mutation, command execution, Git, privileged self-
management, downstream-effect credentials, hardware, or any later Bootstrap phase.
