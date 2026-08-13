Binnacle development Pi
=======================

Purpose and current gate
------------------------

This runbook prepares the read-only compatibility server, the disabled Phase 5 write
probe, the default-disabled Phase 7 execution-supervisor foundation, the isolated
default-disabled Phase 8 Git credential-broker foundation, and the default-disabled Phase 9
root-broker boundary on one 64-bit Raspberry Pi.  It
provides repository-side deployment, integrity, and evidence checks; it does not claim that
a ChatGPT controller is authenticated, that a write catalogue has been promoted, that the
host can safely execute command trees, that Git/signing credentials are installed, or that
any package, systemd, selector, restart, rollback, or reboot effect is promoted.

Do not expose ``/mcp`` through a tunnel until the live feasibility gate has selected and
tested exactly one controller profile.  The repository intentionally contains neither a
speculative OAuth verifier nor a speculative trusted-gateway verifier, and it contains no
invented tunnel service command.  ``verify_dev_pi.py`` reports those live checks as
``blocked`` until the selected adapter and actual connectivity product are present.

Current OpenAI documentation should be re-read immediately before the live run:

* ``https://developers.openai.com/plugins/deploy/connect-chatgpt``
* ``https://developers.openai.com/plugins/build/auth``
* ``https://developers.openai.com/api/docs/guides/developer-mode``

The actual account/workspace UI, private-connectivity mechanism, and identity provider
must be observed.  Product documentation or tunnel reachability is not controller
authentication evidence.

Fixed layout and identities
---------------------------

The development profile uses these fixed paths and identities:

.. code-block:: text

   /srv/binnacle-dev/repo
   /etc/binnacle/dev.toml
   /etc/binnacle/controller-profile.toml
   /var/lib/binnacle/evaluation
   /var/lib/binnacle/state
   /var/lib/binnacle/results
   /var/lib/binnacle/audit
   /var/lib/binnacle/probe-workspace
   /var/lib/binnacle/probe-workspace/.staging
   /run/binnacle
   /etc/binnacle-executor/executor.toml
   /var/lib/binnacle-executor/state
   /var/lib/binnacle-executor/output
   /run/binnacle-executor
   /run/binnacle-executor/private
   /etc/binnacle-git-credential
   /var/lib/binnacle-git-credential
   /var/lib/binnacle-git-credential/state
   /run/binnacle-git-credential
   /run/binnacle-git-credential/private
   /etc/binnacle-privileged/broker.toml
   /var/lib/binnacle-privileged/evidence.db
   /run/binnacle-privileged
   /opt/binnacle-privileged
   /srv/binnacle-runtime
   /srv/binnacle-runtime/slots
   /srv/binnacle-runtime/.staging
   /srv/binnacle-runtime/current

   application user and primary group: binnacle
   source-read supplementary group: binnacle-dev
   executor user and primary group: binnacle-executor
   executor socket client group: binnacle-executor-client
   credential broker user and primary group: binnacle-git-credential
   credential broker client group: binnacle-git-credential-client
   privileged broker socket client group: binnacle-privileged-client

Both service identities are supplementary members of ``binnacle-executor-client`` so they
can traverse the root-owned runtime parent; only ``binnacle`` uses that membership as the
socket client.  The executor-private child remains ``binnacle-executor:binnacle-executor``
``0700``.  The Git checkout, application configuration, and executor configuration/state are
separate.  Controller, tunnel, signing, or transport credentials must never be stored in
the checkout or executor evidence database.  Membership in ``binnacle-dev`` does not grant
access to ``/etc/binnacle``.  The application may connect to the executor socket through
``binnacle-executor-client`` but cannot traverse the executor-private runtime or state
directories; the command identity is not created or granted either authority in this
default-disabled foundation.  Only ``binnacle-executor`` and
``binnacle-git-credential`` belong to ``binnacle-git-credential-client``.  The application
and any future general command identity must not belong to it.  The broker state/private
children remain ``binnacle-git-credential:binnacle-git-credential`` ``0700``; neither the
application nor the general command boundary may traverse them.

Only ``binnacle`` belongs to ``binnacle-privileged-client``.  That supplementary group
permits traversal and connection to the systemd-owned root-broker socket; broker-side
``SO_PEERCRED`` still compares the exact numeric application UID and **primary** GID.  The
broker config, database, and separately installed runtime are ``root:root`` and cannot be
read or replaced by the application, executor, command, or credential identities.  The
socket parent is directly under root-owned ``/run``, never under application-owned
``/run/binnacle``.

The runtime root and ``slots`` child are ``root:binnacle`` ``0750``; the private
``.staging`` child is ``root:root`` ``0700``.  Complete slots are published
``root:binnacle`` ``0550`` with only ``0440`` data and ``0550`` traversable/executable
members.  ``current`` is a root-owned relative selector.  The service identity can read a
selected complete slot but cannot create, replace, rename, or remove any slot or selector.

Prepare the reviewed checkout
-----------------------------

As the development checkout owner, install the repository at the exact path and validate
the exact clean candidate:

.. code-block:: console

   cd /srv/binnacle-dev/repo
   git status --short
   git rev-parse --verify HEAD
   uv sync --frozen --python 3.13
   uv run python scripts/compile_mcp_registry.py --check
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests scripts/mcp_evaluation.py \
     scripts/build_privileged_artifact_manifest.py scripts/setup_dev_pi.py \
     scripts/verify_dev_pi.py scripts/verify_operation_kernel.py \
     scripts/verify_execution_supervisor.py scripts/verify_git_credential_broker.py \
     scripts/verify_privileged_broker.py
   uv run lint-imports
   uv run pip-audit
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py

Record the Git commit, clean/dirty state, Python and ``uv`` versions, and resolved MCP,
FastMCP, and Uvicorn versions.  A dirty candidate is a different evaluation profile.

Privileged setup
----------------

Inspect the deterministic plan before applying it:

.. code-block:: console

   sudo python scripts/setup_dev_pi.py check --repo /srv/binnacle-dev/repo
   sudo python scripts/setup_dev_pi.py apply --repo /srv/binnacle-dev/repo

Add ``--enable`` to ``apply`` only when the protected application configuration is ready.
The script creates distinct application, executor, credential-broker, executor-client,
credential-client, privileged-client, and source-read groups; three non-root service
identities; protected
configuration and evaluation directories;
application-owned state/result/audit subtrees; the dedicated ``0700`` probe root and
staging directory; separate executor and credential config/state/runtime roots; root-owned
privileged config/state/runtime/installation roots; and the reviewed
application/executor/credential/privileged systemd, socket, and tmpfiles assets.  It rejects
an upgrade whose application or general command identity is already a credential client.
It leaves ``binnacle-executor.socket``, ``binnacle-git-credential.socket``, and
``binnacle-privileged.socket`` disabled and starts none of those services.  It does not
install the immutable root-broker artifact, install packages, pull/reset Git, create secrets,
configure a firewall or tunnel, or start a ChatGPT evaluation.  The application unit adds only
``ReadWritePaths=/var/lib/binnacle/probe-workspace`` to the Phase 4 write boundary; it
does not grant source, configuration, evaluation, or credential write access.

The systemd unit, not the setup script, creates ``/run/binnacle`` on service start with
``RuntimeDirectory=binnacle``.  ``RuntimeDirectoryPreserve=yes`` keeps that protected
ephemeral lock directory across an ordinary service stop so the same unprivileged
``binnacle`` identity can perform stopped-service migration or audit recovery.  A reboot
still removes ``/run``; the next service start recreates it.

After setup creates ``binnacle-dev``, grant that group read/traverse access to the exact
checkout and execute access only where an executable bit already exists.  Remove group
write rather than making the service a development user:

.. code-block:: console

   sudo chgrp --recursive binnacle-dev /srv/binnacle-dev/repo
   sudo chmod --recursive g+rX,g-w /srv/binnacle-dev/repo

Repeat these two commands after a checkout update or ``uv sync`` creates new paths.  The
checkout owner retains normal owner permissions; the ``binnacle`` service receives only
the read/traverse/execute access needed to import the source and start the locked virtual
environment.  Never grant ``binnacle`` or ``binnacle-dev`` source write access.

Protected application configuration
-----------------------------------

Create ``/etc/binnacle/dev.toml`` as ``root:binnacle`` with mode ``0640``.  Keep the
Phase 2 bounded defaults explicit:

.. code-block:: toml

   runtime_profile = "development"

   [server]
   host = "127.0.0.1"
   port = 8000
   workers = 1
   max_request_bytes = 1048576
   session_idle_timeout_seconds = 300
   graceful_shutdown_seconds = 10
   filesystem_stat_timeout_seconds = 2

   [logging]
   level = "INFO"
   format = "json"

   [database]
   path = "/var/lib/binnacle/state/binnacle.db"
   busy_timeout_ms = 5000
   wal_autocheckpoint_pages = 1000

   [audit]
   directory = "/var/lib/binnacle/audit"
   segment_bytes_max = 16777216
   emergency_bytes_max = 1048576

   [payload]
   directory = "/var/lib/binnacle/results"
   object_bytes_max = 33554432
   controller_bytes_max = 268435456
   append_chunk_bytes_max = 262144

   [probe_workspace]
   enabled = false
   root = "/var/lib/binnacle/probe-workspace"
   max_file_bytes = 65536
   preparation_ttl_seconds = 300

The probe root and maximum are structural settings.  Do not redirect the root or increase
the maximum.  ``enabled = true`` is not sufficient to expose the write Tools: production
composition also requires the reviewed controller profile, one exact external-scope to
``probe_workspace_mutate`` entitlement mapping, a healthy Phase 4/5 kernel, and the exact
compiled eight-Tool projection.  Until those evidence-selected inputs exist, the server
continues to expose only the five read-only Tools.

After the feasibility gate, create ``/etc/binnacle/controller-profile.toml`` as
``root:binnacle`` with mode ``0640``.  Freeze the selected profile ID/version, exact
external HTTPS ``/mcp`` resource URI, exact Host/Origin policy, and only these read-only
deployment scopes:

.. code-block:: text

   binnacle:connect
   binnacle:observe

Profile-specific issuer, audience, gateway, algorithm, freshness, key, and revocation
fields come only from the selected live profile.  Environment variables and convenience
CLI flags do not override this protected file.

Offline application, executor, and credential migration and verification
-------------------------------------------------------------------------

Neither database is created or upgraded opportunistically by a runtime service.  The
reviewed application head is ``0006_privileged_operations`` and the independent executor head is
``0002_git_members``.  The isolated credential-broker head is
``0001_credential_evidence``.  All Phase 8 Git and credential capabilities remain disabled.
For a new installation or an upgrade, first let systemd create the protected application
runtime directory, then stop the application, executor, and credential-broker units.  The
ordinary application stop preserves its runtime directory for the non-root maintenance lock:

.. code-block:: console

   sudo systemctl start binnacle-dev.service
   sudo systemctl stop binnacle-dev.service
   sudo systemctl stop binnacle-executor.service binnacle-executor.socket
   sudo systemctl stop binnacle-git-credential.service binnacle-git-credential.socket
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle db upgrade \
     --config /etc/binnacle/dev.toml
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle db status \
     --config /etc/binnacle/dev.toml --output agent
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle kernel verify \
     --config /etc/binnacle/dev.toml --output agent
   sudo -u binnacle-executor -- \
     touch /var/lib/binnacle-executor/state/executor-state.sqlite3
   sudo -u binnacle-executor -- \
     chmod 0600 /var/lib/binnacle-executor/state/executor-state.sqlite3
   sudo -u binnacle-executor --chdir=/srv/binnacle-dev/repo -- \
     env BINNACLE_EXECUTOR_MIGRATION_DATABASE_URL=\
sqlite:////var/lib/binnacle-executor/state/executor-state.sqlite3 \
     .venv/bin/alembic -c alembic-executor.ini upgrade head
   sudo -u binnacle-executor -- \
     /srv/binnacle-dev/repo/.venv/bin/python \
     /srv/binnacle-dev/repo/scripts/verify_execution_supervisor.py \
     --database /var/lib/binnacle-executor/state/executor-state.sqlite3 \
     --runtime-directory /run/binnacle-executor/private --output json

The credential-broker schema verifier currently runs only in the isolated CI lane:

.. code-block:: console

   uv run python scripts/verify_git_credential_broker.py --temporary --output json

Do not create a Pi credential database, install a key, enable either credential unit, or
grant the broker checkout access from this repository-only result.  The tracked service is
an explicit ``/usr/bin/false`` fail-closed placeholder and applies exact
``InaccessiblePaths`` barriers to the mutable checkout plus application/executor protected
roots.  Setup and verification also require the broker UID to be unique and its effective
groups to contain only the private broker group and credential-client group.  A later
reviewed broker
implementation must supply a protected, immutable migration/verifier runtime and the real
key, peer, socket, and candidate-Pi evidence before the offline broker migration sequence
becomes operational.  ``verify_dev_pi.py`` still verifies the credential identities,
root-owned parent paths, exact installed tmpfiles policy, effective service/socket
properties, absence of drop-ins, and disabled unit state without traversing the broker's
``0700`` private children.  The broker verifier's ``--foundation-only`` mode verifies those
private children and absence of config/database/socket authority, but it must be run only
from that future immutable broker runtime as ``binnacle-git-credential``—never by granting
the credential identity access to the mutable checkout.

The maintenance command acquires the same exclusive ``/run/binnacle`` writer lock as the
live kernel.  It refuses to run concurrently with a live writer, refuses an absent or
unsafe runtime directory, and never falls back to a source or world-writable lock path.
After a reboot, start then stop the service again before offline maintenance so systemd
recreates and preserves the runtime directory.

The application verifier checks the exact Alembic revision, SQLite foreign keys/WAL/FULL synchronous
pragmas, audit chain/cache continuity, durable audit-failure generation, obligation
markers, payload roots, consequential-boundary gate state, the complete Phase 5 probe
ledger/history/provenance invariants, and the Phase 6 session/registered-workspace/
mutation-fence plus Phase 7 command-operation and Phase 8 retained Git cross-row invariants.
The executor verifier
opens only the executor-owned database read-only and checks its exact schema, integrity,
identity generation, one-home acceptance invariant, and private directory ownership.  The
credential verifier checks only its isolated default-disabled schema and refuses any
promoted or retained credential authority.  The verifiers perform no migration, directory
creation, workspace registration, fence
reconstruction, cleanup, acceptance sealing, or automatic recovery.
The explicit ``touch`` is non-truncating for an existing database; it makes a new database
path executor-owned before Alembic opens it.  The verifier rejects a database broader than
``0600`` or owned by a different identity.

Phase 9 privileged-broker foundation
------------------------------------

The tracked Phase 9 broker service is an independently installed root boundary, not a
subcommand that systemd runs from ``/srv/binnacle-dev/repo``.  Its unit executes only the
root-owned ``/opt/binnacle-privileged/bin/binnacle-privileged-broker`` entrypoint.  The
installed read-only verifier is
``/opt/binnacle-privileged/bin/binnacle-privileged-verify``.  Both must be non-symlink
regular files from the same reviewed immutable installation.  Never run the mutable
checkout, its ``.venv``, or ``scripts/verify_privileged_broker.py`` as root against
authoritative host state.

The repository currently implements durable accept-or-seal evidence, authenticated
framing, retained lookup/sealing, the read-only installed verifier, and uncomposed
root-side primitives for exact no-overwrite slot publication and selector compare-and-swap.
Those filesystem primitives do not authorize themselves: the production broker still has
no start handler and no caller can invoke them without the future retained restart intent,
Phase 6 mutation fence, selected systemd adapter, and promotion gates.  Configuration must
contain this exact default-disabled profile:

.. code-block:: toml

   [broker]
   database_path = "/var/lib/binnacle-privileged/evidence.db"
   runtime_directory = "/run/binnacle-privileged"
   runtime_group_gid = <numeric-binnacle-privileged-client-gid>
   expected_application_uid = <numeric-binnacle-uid>
   expected_application_gid = <numeric-binnacle-primary-gid>
   build_sha256 = "<64-lowercase-hex-installed-build-digest>"
   profile_sha256 = "<64-lowercase-hex-disabled-profile-digest>"
   acceptance_enabled = false
   busy_timeout_ms = 5000

``acceptance_enabled = true`` is rejected by this build; it is not an activation switch.
``build_sha256`` is the canonical digest of the root-owned
``/opt/binnacle-privileged/artifact-manifest.json``.  Broker startup and the installed
verifier reject a noncanonical manifest, unexpected/missing directory or file, symlink,
mode/owner drift, file-size change, or content-digest change before opening authority.
An unprivileged packaging job may create that manifest only in an already-complete staging
tree outside protected host roots:

.. code-block:: console

   uv run python scripts/build_privileged_artifact_manifest.py \
     --root /path/to/unprivileged/staging/binnacle-privileged --output json

The generator creates a new manifest with exclusive-create semantics and refuses installed
``/opt``, ``/etc``, ``/run``, ``/var`` and runtime-selector trees.  It is not an installer:
an owner-reviewed root procedure must still bind the verified export, retain the broker
intent, and invoke the uncomposed publication primitive before promotion.
No package-manager, systemd, runtime-selector, restart, rollback, or reboot effect handler
is composed.  The socket and service therefore remain disabled while the immutable artifact
installation/publication procedure, selected adapters, candidate-Pi evidence, and human
promotion review are incomplete.  Do not wait for that hardware evidence while developing
or reviewing these evidence-independent repository foundations.

The repository-only CI verifier remains safe and temporary:

.. code-block:: console

   uv run python scripts/verify_privileged_broker.py --temporary \
     --require-default-disabled --output json

That command creates and verifies only a temporary database.  It does not authorize a Pi
installation.  Once a separately reviewed immutable artifact installer exists, the owner
procedure must stop both privileged units, migrate the root-owned database from the installed
artifact (never from the checkout), verify it with
``/opt/binnacle-privileged/bin/binnacle-privileged-verify --require-default-disabled``, and
leave both units disabled.  ``verify_dev_pi.py`` checks exact client membership, protected
path ownership/modes, installed executable modes, effective unit/socket properties,
drop-in absence, tmpfiles content, and the default-disabled state.

If audit recovery is required, keep the service stopped.  A human must reconcile every
surviving obligation and prepare a protected closure JSON containing the exact active
generation plus one ``obligation_id``, truthful ``effect_outcome``, and evidence SHA-256
for every marker.  Then run:

.. code-block:: console

   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle audit recover \
     --generation <active-audit-failure-generation> \
     --config /etc/binnacle/dev.toml \
     --closure-file /etc/binnacle/audit-recovery.json

Recovery appends and fsyncs schema-valid closure evidence before removing each marker,
then clears only that exact failure generation.  It leaves admission closed until a
later full ``kernel verify`` or startup passes.  Chain verification alone never clears a
surviving marker or failure generation.

Local service validation
------------------------

Before any private endpoint is connected:

.. code-block:: console

   sudo systemctl start binnacle-dev.service
   systemctl status binnacle-dev.service
   curl --fail --silent http://127.0.0.1:8000/healthz
   curl --fail --silent http://127.0.0.1:8000/readyz

The service remains loopback-only.  Health and readiness are local diagnostics and must
not be included in the public tunnel route.

Run the read-only verifier after the selected authentication adapter is deployed:

.. code-block:: console

   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/python \
     /srv/binnacle-dev/repo/scripts/verify_dev_pi.py \
     --config /etc/binnacle/dev.toml \
     --controller-profile /etc/binnacle/controller-profile.toml \
     --expected-commit <full-reviewed-commit-sha>

Running under ``binnacle`` lets the verifier read ``root:binnacle`` configuration while
proving the service's real checkout access.  It does not execute the mutable checkout as
root.  Supply the complete reviewed SHA printed by ``git rev-parse --verify HEAD``; an
abbreviated SHA is rejected.

A non-zero result is expected while the live profile, authenticated catalogue, filesystem
primitive evidence, write entitlement, or tunnel identity remains blocked.  Do not
relabel a blocked check as passed.

Phase 5 write-probe validation
------------------------------

Do not enable the write catalogue merely because repository tests pass.  On the exact
candidate Pi, first keep the service stopped and verify that the probe root and
``.staging`` are real directories owned by ``binnacle:binnacle`` with mode ``0700``, are
on the reviewed block-backed ``ext4`` profile, and are not bind/subpath aliases of the
checkout, configuration, database, results, audit, or evaluation trees.  The deployment
verifier rejects every other filesystem type and any non-root ``findmnt`` source mapping.
Then record bounded tests of no-replace publication,
file and directory ``fsync``, crash windows, symlink containment, and unknown-entry
preservation.  These observations belong in sanitized evidence outside Git.

The current default-disabled build intentionally keeps production ``binnacle serve`` on
the exact five-Tool core even when ``enabled = true``.  Its dependency-injected write
composition is implementation-test evidence only: no concrete production authentication
adapter, middleware composition, or evidence-selected external mutation scope has been
chosen.  Do not set ``enabled = true`` to try to bypass that gate.

After live Phase 3 evidence selects the concrete authentication adapter and exact external
mutation scope, a separately reviewed repository change must bind one immutable protected
activation record into the authentication middleware, catalogue selection, kernel policy,
and runtime identity.  Only that exact production path may make ``enabled = true`` select
the eight-Tool projection.  If the adapter, protected profile/mapping, activation digest,
kernel health, or filesystem evidence is absent or stale, the visible catalogue remains the
five-Tool core.  Once that change and the real-host prerequisites pass, refresh or reconnect
through the observed host procedure and exercise only the synthetic one-component path and
bounded content from the frozen evaluation case:

#. prepare the write and retain its state binding and expiry;
#. record required confirmation decline attempts and prove zero operation/effect;
#. approve once, deliberately lose the response, and retry the same caller key after both
   filesystem state change and nonce expiry;
#. prove one retained operation, one path generation, and one filesystem publication;
#. reconnect and repeat the same-key retry with zero additional effect;
#. prepare and execute exact cleanup, deliberately repeat the response-loss retry, and
   prove the exact artifact alone is absent;
#. run stopped-service ``kernel verify`` and prove ledger high-water, terminal history,
   provenance, audit obligations, and operation state agree.

Never recursively clean the probe root.  A reserved/uncertain artifact, unknown staging
entry, identity mismatch, corrupt ledger/history, or lost receipt is an operator-visible
recovery condition, not permission to infer success from pathname presence or absence.
Successful identity-bound cleanup intentionally retains one recognizable verified full-content
``.staging/.binnacle-cleanup-tomb-v1-*`` entry.  Do not remove these tombs while the service
is running and do not treat a similarly named identity-unbound entry as safe.
Tomb retention or removal requires a separately reviewed stopped-service accounting
procedure; this Bootstrap implementation never pathname-unlinks them automatically.
Keep the write catalogue disabled and record the case as blocked until every prerequisite
above is observed on the real Pi.  CI and temporary-directory tests are implementation
evidence only; they are not real-Pi or real-ChatGPT support evidence.

Phase 6 development-workspace foundation
----------------------------------------

Migration ``0003_development_workspace`` adds durable registered-workspace identity,
development-session authority state, workspace-operation provenance, and the one shared
monotonic mutation fence.  Repository code, the descriptor-relative Linux adapter, and
the process-local ``CONTENT_READ``/``CHANGE`` coordination seam are implemented for local
and CI verification.  Search, move, and delete remain explicitly unavailable.

The protected profile format is deliberately separate from ``dev.toml`` and from every
environment/CLI override.  An eventual owner-reviewed file is fixed at
``/etc/binnacle/workspace-profile.toml``, owned ``root:binnacle`` with exact mode ``0640``.
The safe pre-promotion posture is:

.. code-block:: toml

   workspace_id = "binnacle-development"
   profile_version = "phase6-disabled-v1"
   enabled = false
   root = "/srv/binnacle-dev/repo"
   protected_prefixes = [".git"]
   allow_out_of_band_writers = false
   allow_submounts = false
   require_mount_id_verification = true
   move_enabled = false
   delete_enabled = false

Do not set ``enabled = true`` on the deployed service yet.  Production ``binnacle serve``
does not load this profile or register Phase 6 MCP handlers; it continues to expose the
exact five-Tool core.  The base unit also intentionally retains a read-only source
checkout.  A boolean, file presence, database row, or session ID is never sufficient to
grant source authority.

Promotion requires a later reviewed change that supplies the exact session-scoped host
confirmation contract, concrete authenticated controller/profile binding, closed
catalogue/schema projection, stopped-service workspace registration, accepted writer and
mount model, and the systemd/DAC source-write boundary.  That change must pass the same
immutable activation identity to authentication, catalogue selection, session authority,
kernel policy, and runtime evidence.  Failure or mismatch at any gate keeps Phase 6
invisible and keeps the checkout read-only.

The service unit now freezes ``KillMode=control-group``, ``SendSIGKILL=yes``, and
``Delegate=no`` so any future bounded matcher/helper tree remains owned by and terminable
with the service.  This does not itself enable a matcher or grant source write.  Real Pi
mount/process-tree observations and real ChatGPT session behavior remain promotion/exit
evidence; their absence does not block repository implementation or CI review.

Phase 7 and Phase 8 default-disabled foundations
------------------------------------------------

Application migrations through ``0006_privileged_operations`` retain the Phase 7
command-operation correlation, add default-disabled Git parent/member/commit/remote
evidence, and add default-disabled privileged preparation/ticket/reservation evidence.
monotonic cancellation delivery, exact supervisor evidence, and mutation-fence ownership.
The separate executor migration ``0002_git_members`` retains bounded executor acceptance,
pending-cancel, no-accept, stream, and evidence records and reserves empty discriminated Git
read/member evidence.  The application never opens the executor database and the executor
never opens the application database.  The separate credential-broker migration owns only
one-use credential evidence; the tracked broker unit deliberately runs ``/usr/bin/false``
and both broker units remain disabled until a reviewed implementation and real evidence pass.

Create ``/etc/binnacle-executor/executor.toml`` as ``root:binnacle-executor`` with exact
mode ``0640`` only after recording the reviewed numeric application peer identity and
runtime digests.  The format is closed and uses only these fields:

.. code-block:: toml

   [executor]
   database_path = "/var/lib/binnacle-executor/state/executor-state.sqlite3"
   runtime_directory = "/run/binnacle-executor/private"
   output_directory = "/var/lib/binnacle-executor/output"
   expected_application_uid = <numeric-binnacle-uid>
   expected_application_gid = <numeric-binnacle-primary-gid>
   build_sha256 = "<64-lowercase-hex-reviewed-build-digest>"
   profile_sha256 = "<64-lowercase-hex-reviewed-disabled-profile-digest>"
   busy_timeout_ms = 5000

Do not enable or start ``binnacle-executor.socket`` merely because migration, temporary
verification, or CI passes.  The installed service accepts only a systemd-owned Unix socket,
checks peer credentials and exact framed protocol fields, and keeps durable cancellation/
acceptance evidence, but its production execution backend intentionally reports
``backend_unavailable``.  It has no direct subprocess fallback, no root broker, no device or
credential access, and no MCP Tool/Resource/Task/Prompt exposure.  A disabled socket also
prevents the application from accidentally treating repository foundations as host support.

Promotion requires one separately reviewed candidate-Pi profile to prove the exact
execution-domain/cgroup mechanism, descendant-wide termination and accounting, command UID
separation, protected-path exclusion, output spooling, network/listener enforcement,
restart reconciliation, and resource ceilings.  Only after those results, Phase 4/6
authority wiring, closed command schemas/manifest, and authenticated controller binding are
current may a later change enable the socket and compose command handlers.  Missing Pi or
real ChatGPT evidence keeps command capability unavailable; it is not a reason to delay or
misstate this evidence-independent repository implementation.

Live authentication feasibility
-------------------------------

Use pre-authentication tests that cannot dispatch a Tool.  Evaluate the two permitted
patterns in order:

#. Select ``trusted-gateway-assertion`` only if the actual gateway supplies a
   cryptographically protected, Binnacle-verifiable assertion and the local hop cannot be
   bypassed.
#. Otherwise select ``oauth-resource-server`` only if an established OAuth/OIDC provider
   can issue Binnacle-audience credentials that the application can validate as a
   resource server.
#. If neither profile meets ``docs/security/controller-transport.md``, record the blocked
   result and stop.  Never fall back to tunnel membership, source address, forwarded
   display-name headers, MCP ``clientInfo``, cookies, or anonymous access.

Only after one profile is proven should the implementation add its single concrete
adapter and direct maintained dependency.  A customer-hosted tunnel systemd unit is added
only when the current supported product exposes a stable documented local CLI.

Evaluation workspace
--------------------

Prepare a sanitized JSON profile snapshot containing every required field from
``schemas/mcp/evaluation-manifest.schema.json`` and a sanitized capability-scope JSON
record.  Initialize the workspace:

.. code-block:: console

   uv run python scripts/mcp_evaluation.py init \
     --output artifacts/mcp-evaluation/<evaluation-id> \
     --profile-json /var/lib/binnacle/evaluation/profile-snapshot.json \
     --capability-scope-json /var/lib/binnacle/evaluation/phase3-capability-scope.json

The default remains the reviewed Phase 3 read-only release.  For an eligible Phase 5
write-probe run, select its reviewed release explicitly and provide a capability-scope
record whose ``catalogue_phase`` is exactly ``compatibility-write-probe``:

.. code-block:: console

   uv run python scripts/mcp_evaluation.py init \
     --output artifacts/mcp-evaluation/<evaluation-id> \
     --profile-json /var/lib/binnacle/evaluation/profile-snapshot.json \
     --capability-scope-json /var/lib/binnacle/evaluation/phase5-capability-scope.json \
     --probe-release phase5-write-probe-evaluation-v1

Use ``record`` once per retained attempt or evidence-backed status classification, then
run ``verify``.  The command refuses unknown case IDs and statuses, secret-bearing or
oversized evidence, missing evidence references, inconsistent attempt totals, and frozen
profile/case digest mismatches.

Non-text evidence is retained only after a person has sanitized it and the recorder is
given ``--binary-human-reviewed``.  This pre-retention attestation does not replace the
separate final workspace review.

Human review is mandatory and precedes final hashing:

.. code-block:: console

   uv run python scripts/mcp_evaluation.py verify --output <workspace>
   uv run python scripts/mcp_evaluation.py review --output <workspace> \
     --reviewer <reviewer-id> --reject-promotion --owner-private-data-reviewed
   uv run python scripts/mcp_evaluation.py finalize --output <workspace>

Use ``--approve-promotion`` only when all mandatory live cases for the selected reviewed
release/catalogue meet their frozen attempt and pass-rate thresholds.  A rejected or
blocked run may still be finalized truthfully.  Finalization writes a reviewed manifest,
deterministic archive, and detached receipt.  The archive contains the manifest and
sanitized evidence, never the detached receipt, and the manifest does not inventory/hash
itself.

Retain evidence outside Git
---------------------------

Local workspaces under ``artifacts/mcp-evaluation/`` are ignored.  Pi-side sanitized
evidence may be staged under ``/var/lib/binnacle/evaluation/<evaluation-id>/``.  Do not
commit raw credentials, authorization headers, cookies, private endpoint secrets,
machine IDs, unrelated conversation material, or unreviewed screenshots/transcripts.
