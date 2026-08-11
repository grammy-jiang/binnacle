Binnacle development Pi
=======================

Purpose and current gate
------------------------

This runbook prepares the read-only compatibility server and the disabled Phase 5 write
probe on one 64-bit Raspberry Pi.  It provides repository-side deployment, integrity, and
evidence checks; it does not claim that a ChatGPT controller is authenticated or that the
write catalogue has been promoted.

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

   service user and primary group: binnacle
   source-read supplementary group: binnacle-dev

The Git checkout and protected controller configuration are separate.  Controller or
tunnel credentials must never be stored in the checkout.  Membership in
``binnacle-dev`` does not grant access to ``/etc/binnacle``.

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
   uv run mypy src/binnacle tests scripts/mcp_evaluation.py scripts/setup_dev_pi.py \
     scripts/verify_dev_pi.py scripts/verify_operation_kernel.py
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

Add ``--enable`` to ``apply`` only when the protected configuration is ready.  The script
creates the two Binnacle groups, the non-root service user, protected configuration and
evaluation directories, application-owned state/result/audit subtrees, the dedicated
``0700`` probe root and staging directory, and the reviewed systemd unit.  It does not
install packages, pull/reset Git, create secrets, configure a firewall or tunnel, or start
a ChatGPT evaluation.  The unit adds only
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

Offline kernel and probe migration and verification
----------------------------------------------------

The Phase 4/5 schema is never created or upgraded opportunistically by ``serve``.  The
reviewed Phase 5 head is ``0002_write_probe_state``.  For a new installation or an upgrade
from ``0001_durable_operation_kernel``, first let systemd create the protected runtime
directory, then stop the service.  The ordinary stop preserves that directory for the
non-root maintenance lock:

.. code-block:: console

   sudo systemctl start binnacle-dev.service
   sudo systemctl stop binnacle-dev.service
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle db upgrade \
     --config /etc/binnacle/dev.toml
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle db status \
     --config /etc/binnacle/dev.toml --output agent
   sudo -u binnacle -- \
     /srv/binnacle-dev/repo/.venv/bin/binnacle kernel verify \
     --config /etc/binnacle/dev.toml --output agent

The maintenance command acquires the same exclusive ``/run/binnacle`` writer lock as the
live kernel.  It refuses to run concurrently with a live writer, refuses an absent or
unsafe runtime directory, and never falls back to a source or world-writable lock path.
After a reboot, start then stop the service again before offline maintenance so systemd
recreates and preserves the runtime directory.

The verifier checks the exact Alembic revision, SQLite foreign keys/WAL/FULL synchronous
pragmas, audit chain/cache continuity, durable audit-failure generation, obligation
markers, payload roots, consequential-boundary gate state, and the complete Phase 5 probe
ledger/history/provenance invariants.  It performs no migration, directory creation,
ledger reconstruction, cleanup, or automatic recovery.

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
