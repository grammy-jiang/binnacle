Phase 10 self-hosting acceptance
================================

Purpose and gate boundary
-------------------------

This procedure closes the repository-owned part of Phase 10 and defines the later live
campaign.  It deliberately separates two gates.

Evidence-independent repository implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The repository gate is complete when the reviewed policy and schemas, authority-free
evaluator, adversarial fixtures, checkout-attestation support, ordinary CI integration,
and this procedure pass the normal repository checks.  Raspberry Pi or ChatGPT evidence
is not required to implement, review, or merge those assets.

Real-device acceptance promotion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bootstrap promotion still requires a separate, owner-accepted ``PASS`` manifest from one
real ChatGPT-controlled run on the selected development Pi.  Until that campaign occurs,
the truthful live status is ``INCOMPLETE``.  Repository implementation must not invent,
simulate, or pre-approve that evidence.

The evaluator executes no device, GitHub, credential, package, service, or restart effect.
It only checks a bounded manifest against repository-owned relationships.  The manifest
and referenced evidence are evidence, not authority.

Repository-owned acceptance assets
-----------------------------------

The frozen implementation consists of:

* ``spec/acceptance/phase10-policy.json`` -- exact repository/protected branch, merge
  method, required workflow/job names, security checks, and reviewed bounds;
* ``schemas/acceptance/phase10-run.schema.json`` -- closed acceptance-run record;
* ``schemas/acceptance/ci-checkout-attestation.schema.json`` -- exact GitHub event and
  checkout identity record;
* ``scripts/phase10_acceptance.py`` -- policy inspection, non-promoted skeleton creation,
  and deterministic evaluation;
* ``scripts/ci_checkout_attestation.py`` -- shell-free reading of the actual checkout
  commit, tree, and parents in GitHub Actions;
* normal ``Contract validation`` and ``Python CI`` artifacts named
  ``phase10-checkout-*``; and
* the checked-in positive, negative, and property-test fixtures under
  ``tests/fixtures/acceptance`` and ``tests``.

The policy includes the canonical digests of both schemas, and its own SHA-256 is part of
every run and integration generation.  A policy or schema change makes earlier evidence
stale; do not edit a retained manifest merely to replace its policy hash.

Repository validation
---------------------

Before publishing a repository change, run the same complete gate used by CI:

.. code-block:: console

   uv sync --frozen --python 3.13
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/binnacle tests \
     scripts/mcp_evaluation.py scripts/build_privileged_artifact_manifest.py \
     scripts/setup_dev_pi.py scripts/verify_dev_pi.py \
     scripts/verify_operation_kernel.py scripts/verify_execution_supervisor.py \
     scripts/verify_git_credential_broker.py scripts/verify_privileged_broker.py \
     scripts/ci_checkout_attestation.py scripts/phase10_acceptance.py
   uv run lint-imports
   uv run pip-audit
   uv run rstcheck --recursive docs
   uv run python scripts/compile_mcp_registry.py --check
   uv run python scripts/validate_contracts.py
   uv run python scripts/validate_schema_instances.py
   uv run pre-commit run --all-files

Inspect the frozen policy identity separately:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py policy --output json

GitHub checkout attestation
---------------------------

Every required GitHub job runs ``scripts/ci_checkout_attestation.py`` after its normal
work, including after a preceding failure.  The script independently reads ``HEAD``,
``HEAD^{tree}``, and the commit parents.  It then binds those facts to the bounded GitHub
event payload and environment.

For a pull request, ``checkout_kind`` is ``pull_request_integration`` only when all of the
following are exact:

* ``GITHUB_SHA`` equals the actual checkout commit;
* the event repository equals the frozen policy repository;
* the event supplies the candidate and protected-base OIDs; and
* the actual checkout parents, in order, are protected base then candidate.

For a push, ``checkout_kind`` is ``push_commit`` only when the event ``after`` OID,
``GITHUB_SHA``, and actual checkout commit are identical.  Any other relationship is
``unbound`` and the CI step refuses success.  The JSON file is still uploaded after an
unbound result so reviewers can diagnose the mismatch.

An attestation proves checkout identity; it does not prove the job conclusion.  The
acceptance manifest must bind both the downloaded attestation digest and the independently
observed GitHub workflow/job conclusion to the same run ID and attempt.

Live campaign prerequisites
---------------------------

Do not begin the real campaign until all of these are current:

* the selected real ChatGPT connection is authenticated under the reviewed controller
  profile;
* the selected real development Pi and exact runtime instance are known;
* every Phase 3 through Phase 9 implementation and promotion gate needed by the chosen
  change is satisfied;
* the repository baseline is clean and the protected base OID is observed independently;
* the accepted signer, controller, device, workspace, and runtime-profile identities have
  bounded evidence references; and
* no retained operation, audit closure, workspace fence, credential lease, restart, or
  recovery state is unresolved.

Missing prerequisites do not block repository implementation.  They do block the live run
from reaching ``PASS`` and must be recorded as unavailable or stale rather than bypassed
with a shell, manual Git command, or manual restart.

Create the run record
---------------------

Create the evidence workspace outside Git with owner-only permissions.  Initialize a
schema-valid record that claims no live evidence:

.. code-block:: console

   install -d -m 0700 /var/lib/binnacle/evaluation/phase10/<run-id>
   uv run python scripts/phase10_acceptance.py initialize \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --run-id <run-id>

The command creates a new file with mode ``0600`` and refuses overwrite.  Populate a new
working copy under the controlled evidence procedure; retain the prior record rather than
editing history in place.  Evidence references contain only a bounded opaque ID and
SHA-256.  Keep raw logs, transcripts, screenshots, credentials, headers, cookies, endpoint
secrets, and private machine identifiers out of the manifest and Git.

Candidate generations
---------------------

Candidate generations start at 1 and remain consecutive.  One candidate generation binds:

* exact source-content and intended-scope digests;
* every local check to that same source-content digest;
* terminal check conclusions, closed descendants, and a closed workspace fence;
* exact status/diff, parent, branch, and repository-safety evidence;
* a locally created commit, tree, parent, approved signer, and verified signature;
* exact push target/ref/result plus remote observation; and
* the hosted PR head at the same signed commit OID.

If source changes, the PR head moves, a correction is committed, a result belongs to an
older source digest, or push truth cannot be reconciled, supersede that generation and
create the next one.  Never copy a prior evidence reference into a new generation.  The
final generation must be the latest and must not have a supersession reason.

Integration generations
-----------------------

After the final candidate is hosted, freeze an integration generation for exactly one
candidate OID, protected-base OID, expected integration tree, and policy SHA-256.  Obtain:

* substantive review explicitly bound to that candidate and protected base;
* zero unresolved actionable findings; and
* every exact required workflow/job result plus its checkout-attestation artifact.

If the candidate moves, return to the complete candidate process and then create a new
integration generation.  If only the protected base moves, create a new integration
generation and repeat base-aware review and CI.  Old review, CI, checkout, or expected-tree
evidence cannot satisfy the new generation.

Hosted merge and local update
-----------------------------

Merge only while the final candidate and integration generation are current.  Record the
actual merge method, candidate, accepted base, result commit/tree/parents, expected tested
tree, and provenance evidence.  The frozen policy currently permits only squash merge, so
the result must have the accepted base as its sole parent and its tree must equal the tested
integration tree.

Update the Pi checkout through the promoted Phase 8 semantics, not a manual shell shortcut.
Record the exact resulting OID/tree, clean state, and repeat the complete required local
checks on that exact merged tree.

Restart, runtime, and behaviour
-------------------------------

Run Phase 9 restart preflight and the controlled restart for the exact merged OID/tree.
After connection loss, reconnect and reconcile the same retained operation.  Never issue a
second restart to obtain a cleaner result.

Record whether the candidate became ready, rolled back, entered restricted recovery,
failed, or remains uncertain.  A rollback or failed candidate is a Phase 10 ``FAIL``;
restricted recovery or uncertainty is ``INCOMPLETE``.  Then independently verify:

* the post-restart runtime OID and tree equal the hosted merged result;
* the source state is clean;
* the runtime instance differs from the baseline instance; and
* the chosen safe semantic probe observes the changed behaviour on that new instance.

Close the required security checks, unresolved-reference list, and owner review only after
all evidence has been sanitized and correlated.

Evaluate and retain the result
------------------------------

Evaluate without a promotion assertion while the campaign is in progress:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py evaluate \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --report /var/lib/binnacle/evaluation/phase10/<run-id>/report.json \
     --output json

For the final owner-reviewed candidate, require ``PASS`` explicitly:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py evaluate \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --report /var/lib/binnacle/evaluation/phase10/<run-id>/final-report.json \
     --output json --require-pass

Output files are new-only and mode ``0600``.  A non-PASS result returns a nonzero status
with ``--require-pass``.  The report contains only finding codes and JSON paths; it does not
echo referenced evidence content.

Reviewer closure
----------------

The substantive reviewer verifies all of the following against independent sources:

* manifest and policy digests;
* consecutive candidate and integration generations with no stale reference reuse;
* signer, pushed head, PR head, protected base, review, and CI identities;
* actual checkout commit/tree/parents from each required attestation artifact;
* GitHub job conclusions for the recorded run IDs and attempts;
* merge tree/parent/provenance and exact local update;
* same-operation restart reconciliation, no duplicate restart, and runtime replacement;
* changed behaviour on the post-restart instance;
* closed audit/fence/credential/root-authority checks and an empty unresolved list; and
* evidence sanitation and retention outside Git.

``FAIL`` means a decisive invariant was violated.  ``INCOMPLETE`` means truth or required
evidence is not closed.  Neither may be relabelled as ``PASS`` by narrative review.  Only
an exact owner-accepted ``PASS`` closes the real Phase 10 exit and the Bootstrap milestone.
