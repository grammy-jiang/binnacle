Binnacle development Pi
=======================

Purpose and current gate
------------------------

This runbook prepares the Phase 2 read-only compatibility server on one 64-bit Raspberry
Pi and provides the repository-side Phase 3 verification and evidence tools.  It does not
claim that a ChatGPT controller is authenticated.

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
   uv run mypy src/binnacle tests scripts/mcp_evaluation.py scripts/setup_dev_pi.py scripts/verify_dev_pi.py
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

Add ``--enable`` to ``apply`` only when the protected configuration is ready.  The
script creates the two Binnacle groups, the non-root service user, protected directories,
and the reviewed systemd unit.  It does not install packages, pull/reset Git, create
secrets, configure a firewall or tunnel, or start a ChatGPT evaluation.

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

A non-zero result is expected while the live profile, authenticated five-Tool probe, or
tunnel identity remains blocked.  Do not relabel a blocked check as passed.

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

Use ``--approve-promotion`` only when all mandatory live read-only cases meet their
frozen attempt and pass-rate thresholds.  A rejected or blocked run may still be
finalized truthfully.  Finalization writes a reviewed manifest, deterministic archive,
and detached receipt.  The archive contains the manifest and sanitized evidence, never
the detached receipt, and the manifest does not inventory/hash itself.

Retain evidence outside Git
---------------------------

Local workspaces under ``artifacts/mcp-evaluation/`` are ignored.  Pi-side sanitized
evidence may be staged under ``/var/lib/binnacle/evaluation/<evaluation-id>/``.  Do not
commit raw credentials, authorization headers, cookies, private endpoint secrets,
machine IDs, unrelated conversation material, or unreviewed screenshots/transcripts.
