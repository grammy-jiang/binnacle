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

The evaluator executes no device, GitHub mutation, package, service, or restart effect.
When a private token file is supplied, it performs only bounded, fixed-host GitHub REST
reads needed to authenticate retained artifact, job, workflow-run, and workflow-source
facts.  The manifest and referenced evidence are evidence, not authority.

Repository-owned acceptance assets
-----------------------------------

The frozen implementation consists of:

* ``spec/acceptance/phase10-policy.json`` -- exact repository/protected branch, merge
  method, required workflow/job names, local check profiles, security checks, and reviewed
  bounds;
* ``schemas/acceptance/phase10-run.schema.json`` -- closed acceptance-run record;
* ``schemas/acceptance/ci-checkout-attestation.schema.json`` -- exact GitHub event and
  checkout identity record;
* ``scripts/phase10_acceptance.py`` -- policy inspection, non-promoted skeleton creation,
  owner-review projection hashing, and deterministic evaluation;
* ``scripts/ci_checkout_attestation.py`` -- shell-free reading of the actual checkout
  commit, tree, and parents in GitHub Actions;
* ``.github/actions/phase10-checkout-attestation/action.yml`` -- immutable composite-action
  entry point used before candidate-controlled setup, dependencies, or tests;
* normal ``Contract validation`` and ``Python CI`` artifacts named
  ``phase10-checkout-*``; and
* the checked-in positive, negative, and property-test fixtures under
  ``tests/fixtures/acceptance`` and ``tests``.

The policy includes the canonical digests of both schemas, the exact collector commit and
collector-bundle digest, and the immutable GitHub workflow ID/path/source-SHA-256 profile
for every required workflow.  Its own SHA-256 is part of every run and integration
generation.  A policy, schema, collector, or reviewed workflow-source change makes earlier
evidence stale; do not edit a retained manifest merely to replace its policy hash.

Repository validation
---------------------

Before publishing a repository change, run the canonical entry point from the repository
root:

.. code-block:: console

   make verify

That target runs the exact complete local profile frozen in the policy.  The underlying
profile intentionally names the ``tox`` environments rather than accepting a free-form
claim that some equivalent test ran:

.. code-block:: console

   uv run tox run -e py311
   uv run tox run -e py312
   uv run tox run -e py313
   uv run tox run -e quality
   uv run pre-commit run --all-files

``tox-quality`` includes lint, format, type, import-boundary, dependency/security,
documentation, contract/schema, generated-registry, verifier/migration, and operational
CLI validation.  Every candidate and post-merge run records the exact
``pre-commit-all-files``, ``tox-py311``, ``tox-py312``, ``tox-py313``, and ``tox-quality``
check IDs plus the canonical policy digest of each command-and-coverage profile.  A
missing, duplicate, renamed, or differently hashed check cannot satisfy the gate.

Inspect the frozen policy identity separately:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py policy --output json

GitHub checkout attestation
---------------------------

Every required GitHub job invokes the collector through the exact commit-pinned
``phase10-checkout-attestation`` action immediately after ``actions/checkout``.  The
attestation is written under ``runner.temp`` and uploaded before Python setup,
dependency installation, environment synchronization, tests, or any other
candidate-controlled repository work.  The action invokes fixed
``/usr/bin/python3 -I -S`` from its immutable action checkout, verifies the frozen
collector-bundle digest, and independently reads ``HEAD``, ``HEAD^{tree}``, and the commit
parents from the candidate checkout.  It then binds those facts, its collector commit, and
its collector digest to the bounded GitHub event payload and environment.
Each checkout fetches depth 2 so the integration commit's parents are present without
fetching unbounded history; a depth-1 shallow checkout cannot provide parent evidence and
must remain unbound.  The reader invokes the fixed ``/usr/bin/git`` binary with a fixed
executable path, no system/global Git configuration, and replacement objects disabled so
earlier workflow environment changes cannot substitute the identity reader or its object
view.

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

An attestation proves checkout and collector identity; it does not prove the later job
conclusion.  For each required job, use the authenticated GitHub Actions API to retain a
sanitized artifact-metadata observation: repository, numeric artifact ID, exact expected
name, byte size, canonical API/download URLs, expiry state, GitHub-reported ``sha256:``
digest, and workflow-run ID/head SHA.  Embed that closed observation and record its
canonical SHA-256 in ``github_artifact_api_ref``.  Download that exact artifact, recompute
the SHA-256 of the original ZIP bytes, require equality with the API digest and byte size,
and preserve those exact bytes in ``github_artifact_archive_base64``.  The archive must
contain only the bounded canonical
``phase10-ci-checkout.json`` member.  The evaluator opens the ZIP again and requires its
object to equal the separately embedded attestation byte-for-byte after canonical parsing.

The embedded observation and its hash are not themselves authentication.  Final
evaluation must receive a bounded mode-``0600`` GitHub bearer-token file and query the
numeric artifact ID live through fixed ``api.github.com`` TLS with REST version
``2022-11-28``.  The evaluator sanitizes that non-manifest response to the same closed
fields and requires exact equality.

The same rule applies to the later job outcome and workflow definition.  Each CI record
retains a numeric ``github_job_id`` and a closed ``github_ci_api_observation`` whose
canonical digest is ``github_ci_api_ref``.  Final evaluation independently reads:

* that exact Actions job by numeric ID;
* its exact workflow run by run ID; and
* the policy-selected workflow path through the Contents API at the actual synthetic
  ``checkout_oid``, not at a mutable branch name or PR head.

The authenticated job must match the recorded repository, run and per-job execution
attempt, workflow/job names, candidate head and canonical URLs and must be terminal
``success``.  Its conclusion is the
authority for the manifest ``conclusion``; an early uploaded attestation cannot make a
later failed job green.  The authenticated run must match the frozen numeric workflow ID,
name/path, pull-request event, candidate head, run ID, and independently retained latest
workflow-run attempt and must also be terminal ``success``.  A successful job and artifact
from an earlier attempt remain valid when ``re-run failed jobs`` advances only other jobs;
the workflow-run attempt may not precede the retained job attempt.  The evaluator also
reads the run's complete bounded ``filter=latest`` job view and requires the retained
numeric job ID to remain a member.  A full workflow rerun therefore supersedes every older
job, while a job genuinely preserved by ``re-run failed jobs`` remains admissible.  The
exact-revision workflow source must match the frozen path and raw
SHA-256; its Git blob OID and bounded byte size are retained for diagnosis.

A live 404 or authenticated mismatch is a failure.  A nonterminal job/run or unavailable
authentication/transport is ``INCOMPLETE``.  Never place the token in the manifest,
evidence reference, report, command output, or repository.

Every workflow/job/run/attempt, repository/event, collector, candidate/base, GitHub SHA,
checkout OID/tree/parents, and checkout-kind field in the surrounding CI record must equal
that archived attestation.  Artifact and CI API references, numeric artifact/job IDs,
archive digests, and attestation digests must be distinct per required job; copying one
observation or uploaded artifact under another label or into a later integration
generation is a failure.

Live campaign prerequisites
---------------------------

Do not begin the real campaign until all of these are current:

* the selected real ChatGPT connection is authenticated under the reviewed controller
  profile;
* the selected real development Pi and exact runtime instance are known;
* every Phase 3 through Phase 9 implementation and promotion gate needed by the chosen
  change is satisfied;
* the repository baseline is clean, the protected base OID is observed independently, and
  the local repository HEAD exactly equals that protected base before branch creation;
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

The baseline's clean local ``repository_head_oid`` must equal its independently observed
``protected_base_oid`` before the feature branch is created.  Branch origin and the first
signed candidate parent must equal that coherent OID.  A stale local protected-branch
checkout cannot be repaired by recording a newer base only in the later integration
generation.

The push evidence's ``remote_profile_sha256`` must exactly equal the protected remote
profile captured in the baseline.  A successful push through a different remote profile
is a failure, even when the destination ref happens to contain the expected OID.

If source changes, the PR head moves, a correction is committed, a result belongs to an
older source digest, or push truth cannot be reconciled, supersede that generation and
create the next one.  Never copy a prior evidence reference into a new generation.  Both
the opaque reference ID and immutable evidence SHA-256 are generation identities; changing
only the ID does not refresh old evidence.  The final generation must be the latest and
must not have a supersession reason.

Integration generations
-----------------------

After the final candidate is hosted, freeze an integration generation for exactly one
candidate OID, protected-base OID, expected integration tree, and policy SHA-256.  Obtain:

* substantive review explicitly bound to that candidate and protected base;
* zero unresolved actionable findings; and
* every exact required workflow/job result, authenticated terminal conclusion, reviewed
  exact-revision workflow source, and checkout-attestation artifact.

Follow the final signed candidate's parent through every immediately preceding candidate
generation to its lineage base.  Each generation must fully pass its own local-check,
status-parent, signature/signer, push, and hosted-head validation; a skipped generation,
missing/forward/cyclic/duplicate OID, contradictory record, or otherwise disconnected link fails.  When the
lineage base is the integration protected base, the final signed tree must equal the
expected synthetic integration tree even when the immediate parent is an earlier
candidate.  A moved protected base instead requires a new integration generation and its
separately computed merge tree; the old candidate chain must still terminate at the
coherent original baseline, or a fresh candidate must be rebuilt from the new base.

If the candidate moves, return to the complete candidate process and then create a new
integration generation.  If only the protected base moves, create a new integration
generation and repeat base-aware review and CI.  Old review, CI, checkout, or expected-tree
evidence cannot satisfy the new generation.  The evaluator compares evidence-reference IDs
and digests, verifies each embedded checkout-attestation artifact, and rejects duplicate
attestation digests, so relabelling one artifact as another job or as a new generation
cannot satisfy the gate.

Hosted merge and local update
-----------------------------

Merge only while the final candidate and integration generation are current.  Record the
actual merge method, candidate, accepted base, result commit/tree/parents, expected tested
tree, and provenance evidence.  The frozen policy currently permits only squash merge, so
the result must have the accepted base as its sole parent and its tree must equal the tested
integration tree.

Update the Pi checkout through the promoted Phase 8 semantics, not a manual shell shortcut.
Record the exact resulting OID/tree, clean state, and repeat the complete required local
five-check policy profile on that exact merged tree.

Restart, runtime, and behaviour
-------------------------------

Run Phase 9 restart preflight and the controlled restart for the exact merged OID/tree.
After connection loss, reconnect and reconcile the same retained operation.  Never issue a
second restart to obtain a cleaner result.

The restart record includes the retained operation reference, checkpoint reference, and
monotonic readiness generation observed by that operation.  Post-restart runtime evidence
must repeat all three exactly.  Runtime readiness from another restart, checkpoint, or
generation cannot promote this candidate even if its OID happens to match.

Record whether the candidate became ready, rolled back, entered restricted recovery,
failed, or remains uncertain.  A rollback or failed candidate is a Phase 10 ``FAIL``;
restricted recovery or uncertainty is ``INCOMPLETE``.  Then independently verify:

* the post-restart runtime OID and tree equal the hosted merged result;
* the source state is clean;
* the post-restart runtime profile equals the frozen baseline runtime profile;
* the reauthenticated controller, device, and workspace identities equal the selected
  baseline identities;
* the runtime instance differs from the baseline instance; and
* the chosen safe semantic probe observes the changed behaviour on that new instance.

Close the required security checks and unresolved-reference list only after all evidence
has been sanitized and correlated.  Each security record's canonical binding digest must
cover its raw evidence reference, acceptance run and policy, exact merged OID/tree,
restart operation/checkpoint/readiness generation, runtime instance/profile, and
controller/device/workspace identities.  Evidence copied from another campaign cannot be
refreshed by relabelling the record or recomputing only the owner-review projection.  Leave
``owner_review`` null while the evidence is
still changing.  When the evidence projection is final, compute the exact review target:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py review-digest \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --github-token-file /run/credentials/binnacle/github-artifact-read.token

The owner approval record must repeat the manifest ``acceptance_run_id``, current frozen
``policy_sha256``, and emitted ``reviewed_evidence_sha256``.  The digest covers the complete
manifest with ``owner_review`` projected to null, so any later evidence change invalidates
the approval without making the approval self-referential.

Evaluate and retain the result
------------------------------

Evaluate without a promotion assertion while the campaign is in progress:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py evaluate \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --report /var/lib/binnacle/evaluation/phase10/<run-id>/report.json \
     --output json \
     --github-token-file /run/credentials/binnacle/github-artifact-read.token

For the final owner-reviewed candidate, require ``PASS`` explicitly:

.. code-block:: console

   uv run python scripts/phase10_acceptance.py evaluate \
     --manifest /var/lib/binnacle/evaluation/phase10/<run-id>/run.json \
     --report /var/lib/binnacle/evaluation/phase10/<run-id>/final-report.json \
     --output json --require-pass \
     --github-token-file /run/credentials/binnacle/github-artifact-read.token

Output files are new-only and mode ``0600``.  A non-PASS result returns a nonzero status
with ``--require-pass``.  The report contains only finding codes and JSON paths; it does not
echo referenced evidence content.

Reviewer closure
----------------

The substantive reviewer verifies all of the following against independent sources:

* manifest and policy digests;
* clean baseline repository HEAD equality with the independently observed protected base;
* consecutive candidate and integration generations with no stale reference reuse, every
  candidate fully validated, and an immediate-predecessor signed parent lineage terminating
  at the coherent candidate base;
* signer, pushed head, PR head, protected base, review, and CI identities;
* actual checkout commit/tree/parents from each required attestation artifact;
* each attestation's collector commit and bundle digest against the frozen policy;
* each embedded artifact API observation exactly equals a fresh bearer-authenticated live
  GitHub REST response and has matching canonical evidence digest plus exact
  repository/ID/name/size/URL/expiry/archive/run/head bindings; each
  original ZIP digest and archived attestation is unique per required job, and the
  downloaded bytes reproduce the API digest, size, and embedded object;
* each embedded CI API observation equals fresh bearer-authenticated job, workflow-run, and
  exact-checkout workflow-source responses; job/run conclusions are terminal success, and
  workflow ID/path/source SHA-256 equal the frozen policy profile;
* lineage-aware same-base signed-tree equality, merge tree/parent/provenance, exact local
  update, and the complete frozen local check profile at both candidate and merged
  identities, with separate canonical ``evidence_binding_sha256`` values, immutable raw
  execution-evidence references, and no candidate/post-merge evidence overlap;
* same-operation/checkpoint/readiness-generation restart reconciliation, no duplicate
  restart, baseline runtime-profile continuity, and runtime-instance replacement;
* changed behaviour on the post-restart instance;
* closed audit/fence/credential/root-authority checks and an empty unresolved list; and
* evidence sanitation and retention outside Git.

The final approval is valid only for its exact acceptance run, policy, and reviewed
evidence digest.  Recompute and repeat owner review after any evidence change; never copy
an approval record from an earlier manifest projection.

``FAIL`` means a decisive invariant was violated.  ``INCOMPLETE`` means truth or required
evidence is not closed.  Neither may be relabelled as ``PASS`` by narrative review.  Only
an exact owner-accepted ``PASS`` closes the real Phase 10 exit and the Bootstrap milestone.
