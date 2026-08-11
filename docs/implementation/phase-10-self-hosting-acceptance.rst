Binnacle Phase 10 Detailed Implementation Plan
===============================================

:Phase: 10 -- Prove the Bootstrap self-hosting acceptance loop
:Status: provisional
:Planning status: evidence-independent acceptance design; real execution remains gated
                  by predecessor implementation/promotion exits and real development-Pi /
                  real-ChatGPT evidence
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 4 durable-operation kernel plan; merged Phase 6 development
             workspace plan; merged Phase 7 execution-supervisor plan; merged Phase 8 Git
             development plan; merged Phase 9 privileged self-management plan; real
             implementation/promotion exits for every capability exercised by acceptance
:Primary objective: Prove, with one correlated retained evidence chain, that real ChatGPT
                    can use Binnacle to make, test, review, merge, deploy, restart and
                    verify one real Binnacle change without routine manual intervention

1. Purpose and phase boundary
-----------------------------

Phase 10 is the Bootstrap acceptance phase. It is not a new broad runtime-capability
phase. Its job is to compose the already-reviewed local development, execution, Git,
privileged restart and hosted GitHub seams into one real self-hosting development loop and
to decide truthfully whether Bootstrap is complete.

The acceptance loop is:

::

   real ChatGPT connects to the real development Pi
       -> inspect exact host/runtime/repository state
       -> start one bounded development session
       -> create one feature branch
       -> inspect/search/read the Binnacle source
       -> make one small real Binnacle change
       -> run required tests/quality checks
       -> exercise one safe recoverable failure or cancellation
       -> inspect Git status/diff
       -> create and independently verify one signed commit
       -> push the exact branch/ref with protected repository credentials
       -> use ChatGPT GitHub integration for PR/review/Actions/merge
       -> if review changes the head, repeat the complete local Phase 6/7/8 candidate chain
       -> independently bind the exact hosted merge result
       -> update the development checkout through Phase 8 semantics
       -> run Phase 9 restart preflight
       -> perform one controlled Binnacle restart
       -> reconnect after expected connection loss
       -> reconcile the retained restart operation
       -> verify exact merged runtime identity
       -> verify the selected changed MCP behaviour
       -> close the evidence bundle and declare PASS or FAIL/INCOMPLETE

Phase 10 does **not** introduce:

* a new generic shell, file, Git, GitHub, root or credential interface;
* a Binnacle-native GitHub PR/review/merge client for Bootstrap;
* an alternative self-update service;
* automatic selection of arbitrary production changes;
* a database-migration mechanism beyond what Phase 9 has actually promoted;
* new hidden host-confirmation assumptions;
* fabricated branch names, object IDs, PR IDs, Action run IDs, restart evidence, Pi
  capabilities or ChatGPT behaviour;
* a reason to continue adding Bootstrap features after the acceptance gate passes.

Plan acceptance and real Phase 10 exit are separate facts. This document may be reviewed
and merged before the real Pi can execute the acceptance loop. That merge proves only that
the acceptance method is coherent.

2. Governing acceptance principles
-----------------------------------

2.1 Evidence, not narrative, decides Bootstrap completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A successful conversation transcript is insufficient. Every consequential stage is bound
to retained machine evidence from its authoritative source. The final PASS decision is a
comparison over exact identities and terminal states, not an inference that the overall
workflow "looked successful".

2.2 Phase 10 does not waive predecessor gates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A Phase 10 plan cannot promote an unimplemented Phase 6/7/8/9 capability. Before a real
acceptance run begins, the implementation/promotion/real-evidence gates for every exercised
operation must be current. An unavailable capability blocks the run rather than being
replaced by a manual shell shortcut.

2.3 No hidden manual development step
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The acceptance run is intended to prove Binnacle self-development. Human setup explicitly
outside Bootstrap runtime scope may occur before the run -- for example initial Pi
installation, registered controller/credential/profile provisioning or enabling the
already-reviewed connectivity path -- but the correlated acceptance sequence itself may
not silently substitute a human editor, local shell, manual ``git`` command, ``sudo`` or
service restart for a missing Binnacle operation.

2.4 Uncertainty blocks PASS
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Any required operation in ``uncertain`` or otherwise unreconciled effect state blocks the
acceptance result. The workflow may continue only after the exact retained operation is
reconciled to a supported truthful state. It never creates a fresh idempotency key merely
to get a cleaner-looking second attempt.

2.5 Connection loss is expected during self-restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MCP connection disappearing during the Phase 9 controlled restart is not itself a
failure. The next ChatGPT connection must reconcile the retained restart operation and
checkpoint rather than requesting a second restart.

2.6 The tested change is selected at execution time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The planning document defines what kind of change is acceptable and what evidence is
required. It does not pre-invent the actual future branch name, changed lines, commit OID,
PR number, CI run IDs, merge OID or runtime result.

2.7 PASS ends Bootstrap feature expansion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once the real evidence bundle passes and is accepted by the owner/reviewer, Bootstrap is a
closed milestone. Subsequent capability expansion belongs to post-Bootstrap development
and should be performed through the working Binnacle loop rather than extending the
Bootstrap acceptance target indefinitely.

2.8 Final PR head has closed local provenance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The final hosted PR head is not allowed to be merely "reviewed code". It must be the exact
signed commit produced by the complete Binnacle-local acceptance chain for the current
candidate generation.

Every change to the candidate commit after local signing -- whether made by ChatGPT's
GitHub integration, a reviewer, an owner, an automation, or another contributor --
invalidates the prior candidate generation's Phase 6 mutation evidence, Phase 7 local
checks, Phase 8 status/diff evidence, signed-commit verification and push evidence for
PASS purposes.

A moved PR head can continue in the same acceptance run only by creating a new monotonic
``candidate_generation`` and repeating the complete local candidate chain:

#. obtain/reconcile the exact remediation content through the supported repository flow;
#. ensure the final source content is present in the registered local workspace;
#. apply or reproduce the accepted remediation through Phase 6 workspace semantics when
   local mutation is required;
#. rerun the complete required Phase 7 local test/quality chain against that exact content;
#. rerun Phase 8 status/diff and repository-safety inspection;
#. create and independently verify a **new signed Phase 8 commit** containing the final
   remediation content;
#. push/reconcile that exact signed commit through the protected Phase 8 push operation;
#. prove the hosted PR head equals that exact newly signed/pushed OID;
#. only then collect exact-head review and CI evidence for the new generation.

A remotely authored, unsigned, locally untested, or otherwise non-Binnacle-proven commit
can never be the final PASS candidate. If it cannot be superseded by a complete locally
proven signed candidate, the run is ``INCOMPLETE``. Review/CI on a moved head never inherits
local evidence from the previous head merely because the diff is small.

3. Source-of-truth composition
------------------------------

Phase 10 consumes the authoritative seams established earlier:

* Phase 3 owns the real development-Pi/real-ChatGPT connection and negotiated compatibility
  evidence;
* Phase 4 owns operation identity, lifecycle, caller-bound idempotency, effect knowledge,
  audit obligations and authoritative application persistence;
* Phase 6 owns the registered development workspace, development-session authority and
  shared workspace access/change fence;
* Phase 7 owns independently supervised development-command process/output/cancellation
  truth across application restart;
* Phase 8 owns exact repository state, signed-commit identity, protected repository
  credentials and semantic fetch/pull/push/ref/worktree transitions;
* Phase 9 owns privileged broker acceptance/effect evidence, restart preflight, complete
  LKG/runtime-control recovery state, controlled restart and post-restart identity truth;
* ChatGPT's GitHub integration owns the hosted PR/review/Actions/merge interaction used by
  Bootstrap.

Phase 10 adds no competing lifecycle database. It defines one acceptance-level correlation
record whose fields are references/digests/identities from those authoritative sources.

4. Plan acceptance, run readiness and Bootstrap exit
----------------------------------------------------

Three different gates must not be conflated.

4.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

This Phase 10 planning PR may merge when:

* it changes exactly the Phase 10 detailed-plan document;
* the holistic acceptance design is reviewed;
* exact-head CI is green;
* mandatory exact-head Codex substantive review is clean;
* actionable review threads are resolved;
* Copilot is attempted at most once per exact head and remains best-effort;
* no future Pi/ChatGPT/credential/GitHub evidence is claimed as already existing.

4.2 Acceptance-run readiness
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A real run may begin only when the selected development Pi has current evidence that all
required predecessor capabilities are implemented and promoted. At minimum:

* Phase 3 real connection/authentication/compatibility evidence is current;
* Phase 4 durable kernel, idempotency, audit and final-boundary implementation exits pass;
* Phase 5 real write entitlement evidence is current;
* Phase 6 registered source workspace and development-session operations are promoted;
* Phase 7 start/status/output/cancel/outstanding/restart reconciliation is promoted;
* Phase 8 status/diff/branch/switch/commit/fetch/pull/push plus signing/repository
  credential profiles are promoted;
* Phase 9 service/runtime inspection, restart preflight and controlled restart are
  promoted for the exact selected candidate class;
* the current manifest/contracts/schemas/host classifications match the real runtime;
* no predecessor evidence is stale relative to the runtime/config/policy/device epoch used
  for this run.

4.3 Bootstrap exit
~~~~~~~~~~~~~~~~~~

Bootstrap exits only after one real acceptance run reaches PASS under section 34 and the
owner/reviewer accepts its exact evidence bundle. Merging the Phase 10 plan alone is not
Bootstrap implementation completion.

5. ``AcceptanceRun`` correlation record
----------------------------------------

The acceptance evidence bundle uses one run identity created before the first development
effect. The exact storage representation is an implementation detail, but the normalized
record conceptually contains:

* ``acceptance_run_id`` -- random opaque identifier;
* acceptance-plan version and evidence-schema version;
* authenticated controller ID/epoch digest;
* device ID/epoch;
* development-session ID/profile/version;
* start trusted time/runtime instance;
* exact initial Binnacle runtime identity;
* exact initial repository/workspace identity;
* selected change objective and scope digest;
* monotonic ``candidate_generation``;
* for every generation, exact locally proven source-content/change-scope digest, local
  checks evidence set, status/diff evidence, signed commit OID+signer and push effect;
* explicit invalidation reason/reference for every superseded generation;
* every Phase 4 operation ID/idempotency key reference used by the run;
* Phase 6 workspace-session/fence references;
* Phase 7 execution IDs/output evidence used for tests/failure exercise;
* Phase 8 branch/ref/index/worktree/commit/push evidence;
* hosted GitHub repository/PR/review/CI/merge identifiers bound to the final generation;
* Phase 9 restart preflight/checkpoint/broker/runtime-slot/recovery evidence;
* post-reconnect exact runtime identity and changed-behaviour evidence;
* security/non-disclosure checks;
* terminal ``PASS | FAIL | INCOMPLETE`` plus exact failed invariant/evidence references.

The run record is correlation evidence, not an authority token. Possessing
``acceptance_run_id`` grants no workspace, credential or root capability.

A candidate generation is immutable once its signed commit is recorded. A later head
movement creates a new generation rather than overwriting the old commit/evidence fields.
This prevents stale local evidence from being rebound to a new hosted head.

6. Evidence collection model
-----------------------------

Phase 10 should prefer a small evidence assembler over a new orchestration engine. It may
be implemented as a test/helper/report component that:

* queries existing bounded operation/status/runtime/Git/broker evidence;
* records external GitHub identifiers supplied/read through ChatGPT's connected GitHub
  workflow;
* canonicalizes exact references/digests;
* evaluates candidate-generation validity and the pass/fail matrix;
* emits a bounded machine-readable acceptance report and a human-readable summary.

It must not:

* execute shell commands itself;
* mutate files, Git refs or services itself;
* hold SSH/GPG/root credentials;
* create a second operation lifecycle;
* infer success from transcript text when an authoritative source exists;
* relabel review/CI evidence from one candidate generation as evidence for another.

If no new evidence-assembler code is required, the run may be evaluated from existing
operation snapshots plus a reviewed acceptance fixture/report procedure. Phase 10 should
not add a Tool solely to make the checklist cosmetically convenient.

7. Selecting the real acceptance change
----------------------------------------

The actual change is selected immediately before the real run from current repository
needs. It must satisfy all of:

* small enough to review and reason about in one acceptance run;
* genuinely changes observable Binnacle behaviour, not whitespace-only evidence theatre;
* does not require a new broad capability outside already-promoted Phase 3-9 surfaces;
* does not require database migration unless the exact Phase 9 database-compatibility
  profile for such a candidate has already been separately proven;
* does not require package/environment/config/service-definition change unless the exact
  Phase 9 candidate/LKG recovery profile for that change class is already proven;
* has a safe post-restart semantic probe that can distinguish old and new behaviour;
* can be covered by bounded tests/quality commands;
* can be reverted/changed before commit without destructive repository operations;
* does not intentionally weaken security merely to make the acceptance loop easier.

Preferred first-run changes are a small bounded Tool result/diagnostic/validation behaviour
change within the current runtime environment. A dependency upgrade, DB migration, root
policy change or service-definition change is a poor first acceptance case unless those
specific Phase 9 recovery paths already have independent real evidence.

8. Acceptance state machine
---------------------------

The evidence-level run state is monotonic and may use names equivalent to:

::

   planned
   readiness_verifying
   baseline_ready
   branch_ready
   change_in_progress
   local_checks_in_progress
   local_checks_ready
   candidate_signed
   candidate_pushed
   hosted_review_in_progress
   candidate_superseded
   hosted_merge_ready
   hosted_merged
   local_update_ready
   restart_preflight_ready
   restart_in_progress
   reconnecting
   runtime_verified
   behaviour_verified
   evidence_closing
   passed
   failed
   incomplete

``candidate_superseded`` creates a new ``candidate_generation`` and routes back through
``change_in_progress`` / ``local_checks_in_progress``. It never jumps directly from a
remotely moved PR head to ``hosted_review_in_progress`` with inherited local evidence.

This state machine does not replace Phase 4 operations. Each transition references the
underlying authoritative operation/evidence. A run may be ``incomplete`` while an
underlying operation remains uncertain/reconciling.

9. Run-readiness snapshot
-------------------------

Before branch creation, collect an exact baseline:

* real ChatGPT connection/controller/device/session identity;
* current compatibility profile and relevant MCP catalogue generation;
* Binnacle runtime revision/branch/dirty state/runtime-slot/config/policy/manifest/service
  composition;
* application database compatibility identity if Phase 9 exposes it;
* registered development workspace root/mount/profile identity;
* current Git repository profile safety digest and protected remote profile;
* exact HEAD/branch/index/worktree state;
* no unresolved Phase 4 consequential operation that conflicts with the run;
* no uncertain workspace mutation/fence;
* no surviving Phase 7 command that conflicts with branch/edit/restart;
* no unresolved Phase 8 credential/Git effect;
* no unresolved Phase 9 package/restart/recovery effect;
* current verified LKG/runtime-control evidence required for the selected restart class;
* exact CI/review policy expected for the hosted PR.

The baseline must be internally coherent. Repository HEAD used to create the feature
branch must equal the baseline commit bound into the run. Runtime revision may differ only
if the documented development topology permits it and the exact relationship is captured.

10. Development-session admission
---------------------------------

Begin or reuse one exact Phase 6 development session according to the promoted session
contract. Bind its controller/device/workspace/profile/policy/trusted-time predicates into
the acceptance run.

The acceptance run never treats the session as permission to cross permanent boundaries:
credentials remain Phase 8 dedicated capabilities and privileged self-management remains
Phase 9 broker authority.

If the session expires before a not-yet-started consequential operation, that operation
must not start. Already-started operation truth and same-key retained retry follow the
merged Phase 6-9 rules rather than being rewritten for Phase 10.

11. Feature-branch creation
---------------------------

Create a new non-protected feature branch through the exact Phase 8 semantic operation.
The branch operation binds:

* baseline source OID;
* current exact HEAD/ref state;
* protected-branch policy;
* target feature-branch name;
* target absence/no-overwrite fact;
* repository/workspace profile and safety digest;
* Phase 4 operation/idempotency identity.

A branch name is chosen at execution time and recorded in ``AcceptanceRun``. The plan does
not reserve a future literal branch name.

Acceptance requires independent post-operation proof that the new ref points to the exact
baseline OID and that protected ``master`` was not directly mutated.

12. Source inspection and change-scope binding
----------------------------------------------

Use Phase 6 inspect/list/read/search operations to understand the selected change. Record:

* files inspected;
* bounded search/query evidence relevant to the change;
* exact source object versions/content bindings used to prepare the patch;
* protected-content exclusions encountered, if any;
* final approved change-scope digest for the current candidate generation.

The change scope should be narrow. If investigation proves the change requires a deferred
capability, environment migration, DB migration or broad privileged change outside the
selected real evidence profile, classify this run ``INCOMPLETE`` and choose another case
later rather than silently broadening authority.

13. Source mutation
-------------------

Make the real change through Phase 6 create/write/patch/move/delete semantics as needed.
Every mutation remains under Phase 4 idempotency/audit and the shared workspace-change
coordination model.

After mutation, inspect exact resulting files/object versions and record the changed-path
set and exact source-content digest for this candidate generation. The acceptance run
rejects:

* unexpected files outside selected scope;
* protected ``.git``/credential/control-plane content mutation through workspace Tools;
* mount/symlink/hard-link escape;
* uncertain workspace effect;
* a mutation requiring manual repair outside Binnacle.

When review remediation changes source later, section 22 requires a new candidate
generation and this Phase 6 content-binding step is repeated for the final content.

14. Development-command checks
------------------------------

Run the exact test/quality commands required by the repository using Phase 7 semantic
execution. Command profiles must be current and source-changing command effects remain
coordinated through the Phase 6 workspace fence as required by Phase 7.

For each command record:

* Phase 4 operation ID;
* candidate generation and exact source-content digest tested;
* Phase 7 execution ID/ticket profile;
* executable/argv/cwd/profile digests;
* start/terminal process evidence;
* bounded stdout/stderr digest and truncation facts;
* exit status;
* descendant cleanup result;
* workspace-fence closure.

At minimum run the repository's current focused tests plus the normal quality gate
appropriate to the selected change. The actual repository at execution time determines
commands through its reviewed development profile.

Every new candidate generation created after review remediation repeats the **complete**
required local Phase 7 chain. A previous generation's green local checks are not inherited.

15. Required recoverable failure or cancellation
------------------------------------------------

The acceptance run must include at least one safe, intentional non-happy-path event and
prove truthful recovery. This is evidence that durable semantics work in the real loop,
not an invitation to create an unsafe outage.

Preferred choices, in order:

#. **test failure then correction** -- make or retain a deliberately failing assertion for
   the selected change, run the exact test, observe truthful non-zero failure, correct it
   through Phase 6, and rerun to success;
#. **Phase 7 cancellation** -- run a bounded long test/check command whose cancellation is
   safe, cancel before launch or while running, prove exact accepted/cancel generation,
   descendant termination and workspace-fence closure, then run the real check normally;
#. **controlled broken-candidate restart** -- use only if real Phase 9 LKG rollback has
   already been independently proven for this exact candidate class; do not make the first
   Phase 10 run depend on an unproven destructive recovery path.

The chosen event gets its own evidence reference in ``AcceptanceRun`` and must be
reconciled before continuing. An ``uncertain`` cancellation does not satisfy the
requirement. The exercise need not be repeated merely because review creates a new
candidate generation unless its evidence depends on the changed candidate content; the
final generation's ordinary local test/quality chain is always repeated regardless.

16. Local checks gate
---------------------

Before **each** candidate generation can be signed:

* every selected test/quality command required by current repository policy is terminal and
  acceptable for that exact generation/source digest;
* the required deliberate failure/cancel is truthfully reconciled;
* no Phase 7 descendant or ambiguous process remains;
* workspace mutation fences are released or have the exact expected current owner;
* Phase 6 inspection confirms the intended source state;
* no unresolved audit obligation blocks new consequential work.

If any local check is red/uncertain, no signed commit/push is attempted merely to let hosted
CI diagnose it.

17. Git status and diff evidence
-------------------------------

Use Phase 8 ``git_status``/``git_diff`` semantics under the supported repository profile.
For every candidate generation record exact:

* branch/HEAD OID before commit;
* changed paths and modes;
* index/worktree state;
* bounded diff digest/result;
* repository config/attributes/helper-surface safety digest;
* proof that protected/unexpected paths are absent from the candidate commit.

Repository-controlled helpers/hooks/filters/textconv/external-diff/LFS/submodule behaviour
must remain within the promoted Phase 8 profile. Phase 10 never relaxes that profile to
make the acceptance commit succeed.

18. Signed commit creation
--------------------------

Create one signed commit for the candidate generation through Phase 8 controlled
semantics. The acceptance evidence binds independently:

* candidate generation;
* exact parent OID;
* exact committed tree OID and changed-path set;
* exact commit OID;
* commit message digest/text under the reviewed result policy;
* protected author/committer identity;
* exact signing identity/fingerprint/profile;
* signature verification result;
* branch ref CAS old -> new evidence;
* repository safety/profile digest used by the operation;
* exact Phase 6 source-content + Phase 7 local-check evidence set from which this commit
  was produced.

Do not accept "git commit exited zero" as sufficient proof. Verify the resulting commit
object/tree/parent/signature/ref identity through Phase 8 post-effect evidence.

A branch-ref CAS conflict is a truthful failure and requires reconciliation/replanning,
not force-updating a ref to preserve the acceptance script.

The **final** Phase 10 candidate must be a commit created and signed by this step. A commit
created only on GitHub or by a reviewer cannot become the final PR head for PASS.

19. Push preparation and exact remote binding
---------------------------------------------

Before each candidate-generation push, bind:

* protected repository remote profile;
* exact normalized host/repository identity;
* feature branch local ref and signed commit OID;
* exact destination remote ref;
* expected remote old OID/nonexistence condition according to the promoted push contract;
* dedicated repository SSH identity profile;
* closed SSH/known-hosts/helper configuration;
* operation/idempotency identity.

The local repository's mutable URL/config does not choose credential audience or push
destination. Generic Phase 7 commands receive no repository SSH/GPG credential authority.

20. Push and ambiguous-network reconciliation
---------------------------------------------

Perform Phase 8 semantic push. Record executor/Git evidence and the exact protected
remote/ref target. The pushed target OID must equal the signed OID for the same candidate
generation.

If the network response is lost:

* do not issue a fresh blind push under a new idempotency key;
* reconcile the retained push operation;
* independently inspect the protected remote ref through the reviewed Phase 8 mechanism;
* remote ref == exact target commit may prove desired current effect under Phase 8;
* a different current remote ref does not automatically prove the original push had no
  effect because another change may have occurred after success;
* remain uncertain until exact effect can be reconciled.

Phase 10 cannot PASS with an ambiguous push effect.

21. Hosted GitHub PR creation
-----------------------------

After exact push success, ChatGPT uses its connected GitHub integration to create the
hosted pull request. Binnacle does not acquire a new GitHub API credential or PR Tool for
Bootstrap.

Record:

* GitHub repository identity;
* PR number/URL identity;
* candidate generation;
* exact head branch/ref and commit OID observed by GitHub;
* exact base protected branch and base OID at PR creation;
* PR creation time/evidence source;
* run correlation note/reference if repository process permits one.

The hosted PR head must equal the exact signed/pushed commit of the current candidate
generation. If it differs, stop and reconcile before review.

22. Hosted review policy and head movement
-----------------------------------------

Use the repository's current review process, including the bounded AI-review policy that
applies to development workflow at execution time. Phase 10 acceptance requires that the
hosted change is substantively reviewed; it does not require review spam or a particular
bot signal when an equivalent exact-head clean assessment is accepted by repository
policy.

Record:

* candidate generation;
* exact reviewed head commit;
* required reviewer identities/types;
* actionable findings;
* remediation decisions;
* proof each actionable thread is resolved or explicitly accepted under owner policy;
* final exact-head clean review evidence.

**Any remediation that changes PR content/head invalidates the current candidate
generation for PASS.** The workflow must not use a GitHub-side edit or reviewer-authored
commit as the new final candidate while retaining old local evidence.

For a changed head, create the next candidate generation and repeat sections 12 through 20
as one closed chain. In particular:

#. bind/produce the final remediation content in the real registered workspace through the
   supported Phase 6 path;
#. rerun the complete required Phase 7 local tests/quality against that exact content;
#. rerun Phase 8 status/diff/repository-safety checks;
#. create a new independently verified signed Phase 8 commit;
#. push/reconcile exactly that commit;
#. prove GitHub PR head equals that signed/pushed OID;
#. then rerun exact-head substantive review and Actions for the new head.

If a hosted reviewer/automation has already authored a commit, it is historical input, not
final acceptance provenance. Its desired changes must be represented in a new locally
proven signed candidate before PASS. If repository policy cannot preserve this closed
local provenance, the acceptance run is ``INCOMPLETE`` rather than weakening the gate.

No local check, diff, signature, push, review or CI evidence from a superseded generation
can satisfy the final generation's corresponding requirement.

23. GitHub Actions gate
-----------------------

Record the exact required workflow runs/checks for the **final locally proven candidate
generation and exact PR head**:

* workflow name/ID and run ID;
* exact commit SHA;
* candidate generation;
* trigger/source;
* terminal conclusion;
* required job/check conclusions;
* retry/attempt identity when a transient infrastructure failure is rerun.

A rerun is acceptable when repository policy permits it and evidence shows the original
failure was infrastructure/transient rather than a hidden code change. Final PASS requires
that the exact GitHub Actions head equals the generation's locally signed/pushed OID.
Green CI on any prior generation is stale and cannot be reused.

24. Hosted merge binding
------------------------

Merge through ChatGPT GitHub integration only after exact-head review and CI are clean.
Immediately before merge, re-read and bind:

* PR number;
* current candidate generation;
* exact expected PR head;
* exact locally signed commit OID for that generation;
* exact pushed remote-ref OID;
* final review head;
* final CI head;
* merge method;
* protected base branch/current expected base state as required by repository policy.

The four candidate identities -- locally signed OID, pushed ref OID, current PR head, and
review/CI head -- must be exactly equal before merge. A last-second head movement returns
to section 22; it never proceeds with mixed-generation evidence.

Record the exact resulting merged commit OID and hosted merge timestamp/evidence. Read the
hosted result independently after merge. The merge OID becomes the only allowed local
update/restart candidate for the remainder of the run.

25. Local checkout update after hosted merge
--------------------------------------------

Updating the real development checkout is an explicit Phase 8 semantic operation. Do not
substitute a manual ``git pull``.

Before update, prove:

* final-generation signed commit was pushed/merged as expected;
* local index/worktree state matches the exact allowed transition;
* no uncommitted acceptance artifacts or unrelated edits exist;
* no conflicting Phase 6/7/8 workspace changer is active;
* protected remote/base identities are current.

Use promoted fetch/pull/switch/ref-update semantics to reach the exact hosted merged
commit. Preferred integration is protected fetch plus explicit verified fast-forward /
exact branch update as defined by Phase 8, not arbitrary merge/rebase/stash.

After update record:

* local protected branch/ref;
* local HEAD OID;
* index/worktree cleanliness/expected state;
* exact equality to hosted merged commit;
* repository safety-profile digest;
* Phase 8 operation/effect evidence.

If local HEAD != hosted merged OID, restart is prohibited.

26. Runtime-candidate binding
-----------------------------

Construct the Phase 9 candidate identity only after local update is exact. Bind:

* final candidate-generation signed/pushed/PR-head evidence;
* hosted merged OID == local HEAD;
* exact branch/dirty expectation;
* source/workspace/root/mount identity;
* environment/lock/package identity;
* config/policy/manifest/service-definition identity;
* application-database compatibility/effect class where promoted;
* exact Phase 9 ``VerifiedRuntimeSlot``/LKG compatibility requirements;
* expected post-restart behaviour probe.

If the acceptance change unexpectedly changes an unsupported environment/config/DB/service
class, classify the run ``INCOMPLETE`` before service stop rather than weakening Phase 9
recovery rules.

27. Restart preflight
---------------------

Call Phase 9 ``restart_preflight`` and record:

* active/uncertain Phase 4 operations;
* Phase 6 workspace fences;
* Phase 7 supervised work;
* Phase 8 Git/credential effects;
* prior Phase 9 privileged/recovery state;
* current exact runtime identity;
* exact candidate/LKG compatibility;
* predicted restart impact/blockers;
* manager-reload/database compatibility facts when applicable.

Preflight is advisory. Actual ``binnacle_restart`` must acquire Phase 6 exclusive workspace
coordination and revalidate exact current state under the Phase 9 final boundary before
privileged dispatch.

28. Controlled restart dispatch
-------------------------------

Request exactly one Phase 9 controlled restart with a stable idempotency key bound into
``AcceptanceRun``. Record:

* Phase 4 operation ID;
* privileged ticket ID/digest/profile;
* restart-owned Phase 6 workspace fence ID/generation;
* Phase 9 broker acceptance evidence;
* exact restart checkpoint ID/digest;
* exact hosted merged candidate OID;
* final candidate-generation provenance reference;
* retained LKG ``VerifiedRuntimeSlot`` identity;
* restart deadline/profile;
* any manager-reload/database-compatibility plan required by candidate class.

Once broker acceptance occurs, application/session disappearance does not cancel accepted
recovery. Do not issue a second restart merely because ChatGPT loses the MCP connection.

29. Expected connection loss and reconnect
------------------------------------------

When the application stops, record connection loss only as an observed transport event.
The acceptance run enters ``reconnecting`` while the broker continues its retained state
machine.

Reconnect attempts use the same registered endpoint/controller profile. On reconnect:

* authenticate current controller/device again;
* inspect current runtime identity/readiness;
* retrieve/reconcile the exact retained Phase 4 restart operation;
* inspect Phase 9 broker checkpoint/recovery evidence;
* prove restart-owned workspace fence and audit obligations reached truthful supported
  closure before new overlapping work;
* never create a fresh restart operation to replace an accepted one.

30. Candidate success versus rollback outcome
---------------------------------------------

For the normal Phase 10 acceptance case, expected success is the exact hosted merged
candidate. Acceptance recognizes Phase 9 truth if a failure occurs:

* ``candidate_ready`` at exact merged revision and expected runtime identity can proceed to
  behaviour verification;
* candidate failure with proven LKG rollback is a truthful recovered Phase 9 result but
  **fails this Phase 10 run**, because the merged change is not running;
* restricted recovery is ``FAIL/INCOMPLETE`` and requires operator/recovery work outside
  this run;
* ambiguous broker/systemd/database effect is ``INCOMPLETE`` until reconciled.

Phase 10 never calls a successful rollback equivalent to successful candidate self-hosting
deployment.

31. Post-reconnect runtime identity verification
------------------------------------------------

Before probing changed behaviour, prove at minimum:

* exact runtime Git revision == hosted merged OID;
* hosted merged OID descends from/includes the final candidate-generation signed commit as
  expected for the repository merge method;
* exact protected branch/detached expectation;
* clean/expected source state;
* exact source/workspace/root/mount identity;
* exact Python/environment/lock/package identity expected for selected candidate;
* config/policy/manifest/service-profile identities;
* loaded service composition where Phase 9 exposes it;
* application DB compatibility generation where applicable;
* device ID/epoch;
* readiness generation/runtime instance distinct from pre-restart instance;
* no fail-restricted startup state;
* exact retained restart operation shows candidate success, not hidden rollback.

Systemd ``active`` or local source HEAD alone is insufficient.

32. Changed-behaviour verification
----------------------------------

The selected acceptance change must have an explicit safe semantic probe. After exact
runtime identity is established, real ChatGPT invokes that probe through the actual MCP
surface and records:

* exact Tool/operation/contract version;
* bounded request/input fingerprint;
* expected old-vs-new behavioural distinction;
* actual structured result/evidence;
* runtime/catalogue generation used;
* proof result comes from post-restart candidate runtime;
* final candidate-generation/merged-OID evidence reference;
* no consequential side effect unless selected probe contract explicitly requires one.

The probe must distinguish the merged change from old runtime. Merely seeing commit OID is
not changed-behaviour evidence. A result cached or observed from a pre-restart runtime or
catalogue generation cannot satisfy this step.

33. Security/non-disclosure acceptance checks
---------------------------------------------

The final bundle must demonstrate that the self-hosting loop did not obtain authority by
leaking or bypassing permanent boundaries. At minimum verify:

* no reusable controller/auth credential appears in Tool results, command output, Git
  output, audit summaries, PR text or acceptance report;
* no raw SSH private key, reusable SSH agent authority or GPG private key is exposed to
  ChatGPT/general Phase 7 execution;
* repository credential/signing authority appears only in the dedicated Phase 8 operation
  domain and is closed after use;
* no generic root token/socket/shell/path authority is exposed to Phase 7/8 or ChatGPT;
* no manual root command substitutes for Phase 9;
* no workspace mount/symlink/hard-link/protected-content escape occurred;
* no unreviewed repository-controlled credential helper/hook/filter/textconv/external diff
  ran with credential authority;
* privileged broker/recovery logs/evidence remain bounded/redacted;
* all workspace/credential/restart reservations/fences are terminally closed or have a
  truthful retained reason for remaining closed.

A credential leak is an acceptance failure even if the code change otherwise deployed.

34. Final pass/fail matrix
--------------------------

The acceptance evaluator returns exactly ``PASS``, ``FAIL`` or ``INCOMPLETE``.

34.1 PASS
~~~~~~~~~

PASS requires **all** of:

#. real ChatGPT connected to the real selected development Pi under expected controller and
   compatibility profile;
#. exact baseline/runtime/repository/run correlation recorded;
#. one real feature branch created from expected base without protected-master direct
   mutation;
#. one real bounded source behaviour change made through Phase 6;
#. the **final candidate generation** has complete Phase 6 source/content binding, complete
   required Phase 7 local test/quality evidence, Phase 8 status/diff evidence, independently
   verified signed commit and exact protected push evidence;
#. one safe recoverable failure/cancellation is truthfully reconciled;
#. no superseded candidate generation contributes local/review/CI evidence to the final
   generation's required fields;
#. final locally signed commit OID == exact pushed feature-branch OID == exact final hosted
   PR head == exact substantive-review head == exact GitHub Actions head;
#. required substantive review is clean for that exact final head;
#. required GitHub Actions checks are green on that exact final head;
#. PR is merged and exact merged OID independently recorded;
#. local development checkout reaches exactly that merged OID through Phase 8 semantics;
#. Phase 9 restart preflight and controlled restart use exactly that merged candidate;
#. reconnect reconciles the same retained restart rather than a second attempt;
#. post-reconnect runtime identity equals exact merged OID and expected runtime/control
   composition;
#. selected changed behaviour is observed through real MCP on that runtime;
#. no unresolved ``uncertain`` operation, audit obligation, workspace fence, credential
   effect or broker recovery remains;
#. security/non-disclosure checks pass;
#. evidence bundle is internally consistent and owner/reviewer accepts it.

34.2 FAIL
~~~~~~~~~

FAIL is a terminal evidence-backed negative result, for example:

* hosted review/CI rejects final candidate and run is deliberately ended;
* protected repository/security policy violation occurs;
* wrong signer/remote/branch/merge/runtime identity is proven;
* final PR head cannot be traced to a complete locally tested/signed/pushed candidate
  generation;
* candidate restart truthfully rolls back instead of running merged candidate;
* changed behaviour is definitively absent on exact candidate runtime;
* credential or privilege boundary is breached.

A later acceptance run may start only after underlying issue is corrected and normal
predecessor gates are restored.

34.3 INCOMPLETE
~~~~~~~~~~~~~~~

INCOMPLETE means acceptance truth cannot yet be decided safely, for example:

* required predecessor capability/evidence is unavailable;
* an effect remains ``uncertain``;
* GitHub/executor/broker evidence needed for correlation is unavailable;
* PR head moved and the complete local Phase 6/7/8 candidate chain has not yet been
  repeated for the new head;
* selected change unexpectedly requires unpromoted environment/DB/root capability;
* restricted recovery requires local operator work;
* external service outage prevents completion without proving candidate failure.

INCOMPLETE never silently becomes PASS from elapsed time or a later unrelated observation.

35. Retained retry rules
------------------------

For every Phase 4/6/7/8/9 operation:

* same logical retry uses same idempotency binding/fingerprint according to contract;
* retained work is resolved before mutable admission predicates;
* response loss does not authorize fresh logical effect;
* ``uncertain`` blocks blind repeat;
* session expiry cannot rewrite already-started effect truth;
* restart connection loss cannot allocate second restart;
* hosted GitHub operations are re-read from GitHub rather than guessed from local state.

For acceptance candidate generations:

* head movement never mutates old generation's OID/evidence in place;
* a new generation must rebuild the complete local source/check/sign/push provenance;
* only evidence explicitly bound to final generation can satisfy PASS fields.

The acceptance-run record may gain new evidence, but it cannot rewrite authoritative effect
results to make the matrix pass.

36. Fault and interruption scenarios
------------------------------------

Before real exit, walk or exercise as appropriate:

* ChatGPT disconnects during read-only inspection;
* application restarts between source edit and test;
* Phase 7 command response lost after acceptance;
* safe cancellation before command launch;
* safe cancellation while command process tree is running;
* test fails, source is corrected and exact same acceptance objective continues;
* application dies while retained Phase 7 operation survives;
* Git branch/ref CAS loses to unexpected concurrent change;
* push response lost;
* remote ref changes after a push may have succeeded;
* PR review remediation moves head after original local checks/signing;
* reviewer/GitHub automation creates an unsigned or locally untested commit;
* old-generation local checks are accidentally offered with new-generation review/CI;
* transient GitHub Actions infrastructure failure is rerun under repository policy;
* hosted merge response lost but GitHub later proves exact merged OID;
* local update response lost after ref/worktree effect;
* restart preflight clean but competing Phase 7/8 changer races final admission -- shared
  Phase 6 fence gives one winner;
* application connection disappears after Phase 9 broker acceptance;
* broker accepted restart and app retry arrives after reconnect;
* candidate readiness delayed until near deadline;
* candidate fails and exact LKG rollback succeeds;
* candidate/recovery ends restricted;
* post-reconnect runtime revision differs from hosted merge;
* runtime revision matches but changed behaviour is absent;
* audit/credential/fence closure fails after otherwise successful deployment.

Each case has a defined PASS-blocking or reconciliation outcome. No case is resolved by
manual narrative alone.

37. Acceptance-run evidence schema
----------------------------------

A future machine-readable evidence artifact should be closed/versioned and bounded. A
representative shape is:

.. code-block:: text

   acceptance_run:
     id
     plan_version
     controller_ref
     device_ref
     session_ref
     baseline_runtime_ref
     baseline_repo_ref
     change_objective_digest
     candidate_generations[]:
       generation
       source_content_ref
       local_check_refs[]
       status_diff_ref
       signed_commit_oid
       signer_ref
       push_effect_ref
       hosted_head_ref
       review_refs[]
       ci_refs[]
       superseded_reason_ref
     final_candidate_generation
     operation_refs[]
     command_execution_refs[]
     failure_exercise_ref
     github_pr_ref
     github_merge_oid
     local_update_ref
     restart_operation_ref
     restart_checkpoint_ref
     post_restart_runtime_ref
     behaviour_probe_ref
     security_check_refs[]
     unresolved_refs[]
     verdict
     verdict_reason

The artifact contains references/digests and bounded non-sensitive facts, not raw
credentials, complete command logs, protected configuration or arbitrary source content.

38. Reviewability and human evidence bundle
-------------------------------------------

The final evidence package should allow an owner/reviewer to answer quickly:

* What exact real Pi/runtime did ChatGPT start from?
* What exact change was selected and why was it safe for this acceptance profile?
* Which candidate generations were superseded and why?
* Does the final PR head equal the final locally tested/signed/pushed commit?
* What files changed in that final generation?
* What local tests ran against that exact content and what failure/cancel was exercised?
* What exact signer and protected remote were used?
* What PR/review/CI/merge evidence corresponds to exact final head?
* What exact merged OID was installed locally?
* What Phase 9 checkpoint/LKG/broker operation performed restart?
* Did candidate run or rollback occur?
* What exact post-restart runtime identity was observed?
* What semantic MCP probe proves changed behaviour is live?
* Were all audit/fence/credential/broker states closed?
* Was any reusable credential or privileged authority exposed?

If these questions require reconstructing facts from an unbounded chat transcript, the
evidence design is insufficient.

39. Tests for the acceptance evaluator
--------------------------------------

Any implementation of evidence assembler/evaluator should have deterministic tests for:

* missing required evidence -> INCOMPLETE;
* wrong branch/base/head relationship -> FAIL;
* wrong signer -> FAIL;
* review on old head -> INCOMPLETE/FAIL according to repository policy, never PASS;
* CI green on old head only -> INCOMPLETE;
* final PR head differs from final locally signed/pushed OID -> FAIL/INCOMPLETE, never PASS;
* new PR head reuses old generation's Phase 6/7/8 local evidence -> INCOMPLETE;
* remotely authored remediation commit lacks new local test/sign/push generation ->
  INCOMPLETE;
* merged OID != local update target -> FAIL;
* local update target != post-restart runtime revision -> FAIL;
* candidate rollback despite hosted merge -> FAIL for Phase 10 candidate success;
* runtime revision correct but behaviour probe absent -> INCOMPLETE;
* runtime revision correct but behaviour definitively old/wrong -> FAIL;
* unresolved Phase 4/7/8/9 uncertain state -> INCOMPLETE;
* deliberate cancellation not truthfully reconciled -> INCOMPLETE;
* leaked credential/security invariant -> FAIL;
* every final-generation identity/evidence exact and closed -> PASS.

Use property tests for evidence-reference permutation/omission so evaluator cannot pass
because a similarly named but different operation/commit/run/generation was supplied.

40. Real-Pi/ChatGPT evidence campaign
-------------------------------------

The real acceptance campaign records, rather than assumes:

* actual ChatGPT connection/reconnection behaviour;
* actual catalogue refresh behaviour after restart if relevant to selected change;
* actual host confirmation/authority prompts for promoted operations;
* real Phase 7 process/cancel survival behaviour;
* real Phase 8 SSH/signing/push evidence without raw-secret disclosure;
* real GitHub connected integration PR/review/Actions/merge behaviour;
* real Phase 9 broker/systemd/checkpoint/recovery behaviour;
* exact restart downtime/reconnect timing;
* exact post-restart runtime identity/readiness evidence;
* actual changed Tool behaviour.

Unknown facts stay unknown until this campaign runs. The plan does not claim ChatGPT will
automatically rediscover a changed catalogue, that Pi can materialize an LKG slot, or that
a particular Git/GPG/systemd mechanism works merely because design names it.

41. No manual fallback inside the acceptance chain
--------------------------------------------------

If a required step cannot be completed through promoted Binnacle/ChatGPT GitHub
interfaces, record missing capability and stop run INCOMPLETE. Do not patch over it with:

* SSH shell commands;
* manual file edits;
* manual ``git``/``gh`` commands;
* manual ``systemctl``/``sudo``;
* direct credential copying;
* local database edits;
* hidden repository force updates.

This also applies to review remediation: a GitHub-side edit may be useful collaboration
input, but it cannot become final PASS head unless its content is superseded by a complete
Binnacle-local Phase 6/7/8 tested/signed/pushed candidate generation.

A separately documented operator recovery required by Phase 9 ``restricted_recovery`` is
truthful recovery, but once used it means this Phase 10 run did not prove required routine
no-manual-intervention self-hosting loop.

42. Hosted GitHub boundary
--------------------------

Keeping hosted PR/review/CI/merge in ChatGPT's GitHub integration is deliberate Bootstrap
scope. Phase 10 verifies composition:

* Binnacle can prepare/push a correct signed branch without exposing reusable credentials;
* ChatGPT can use its separate connected GitHub authority for hosted collaboration;
* hosted collaboration may suggest changes but cannot replace the required local final-head
  provenance;
* exact hosted result can be brought back into Binnacle local/restart evidence.

This is not considered a local Binnacle authority leak and does not justify exposing
GitHub credentials to the Pi.

43. Acceptance of changed MCP behaviour
---------------------------------------

When selected change affects a Tool schema/catalogue entry, run must respect actual
promoted contract/catalogue-refresh rules observed in Phase 3 and later evidence. It may
require reconnect or catalogue refresh according to real host behaviour. Do not assume
immediate host uptake.

When selected change affects only handler behaviour under unchanged schema, probe still
verifies actual post-restart result and binds it to post-restart runtime
instance/catalogue generation.

A Tool result from pre-restart connection/cache cannot satisfy changed-behaviour proof.

44. Database/environment/service-definition guard
--------------------------------------------------

Phase 10 intentionally chooses a candidate class supported by current Phase 9 evidence.
Before every candidate-generation signing/push and again before restart:

* classify whether change alters dependencies/environment;
* classify whether it alters configuration/policy/manifest;
* classify whether it alters systemd service-unit/drop-in/runtime-selector material;
* classify whether it can perform application DB schema/data migration;
* compare classes to promoted candidate/LKG recovery profile.

If real Phase 9 profile supports only database-neutral/no-environment-change candidates,
Phase 10 uses that class. Acceptance never expands Phase 9 by selecting a more aggressive
candidate and hoping rollback works.

45. Cleanup after PASS or terminal FAIL
---------------------------------------

After terminal evidence closure:

* development session is ended/allowed to expire under normal authority semantics;
* no Phase 7 command descendant remains;
* repository worktree/index state is exact expected protected branch state;
* no acceptance-only feature branch cleanup destroys useful hosted evidence; cleanup
  follows normal repository policy;
* credential capability sockets/leases are closed;
* Phase 6 workspace fences are free;
* Phase 9 restart/recovery reservations/broker state are terminally retained/cleaned under
  retention policy;
* acceptance evidence bundle is durably retained at reviewed location without secrets.

Cleanup cannot retroactively rewrite a failed/uncertain effect.

46. Implementation order
------------------------

Phase 10 implementation/execution should proceed in this order:

#. Freeze/review Phase 10 evidence schema, candidate-generation rules and pass/fail matrix.
#. Implement only the small evidence assembler/evaluator if existing retained snapshots are
   insufficient for reliable review; do not add a new authority surface.
#. Add evaluator fixtures/property tests including moved-head/stale-generation cases.
#. Add an acceptance-run operator/reviewer procedure referencing existing semantic Tools.
#. Verify Phase 3-9 implementation/promotion exits on real selected Pi.
#. Choose one real safe acceptance change at execution time.
#. Capture exact baseline and create ``AcceptanceRun`` generation 1.
#. Execute branch/read/edit/test/failure-exercise/diff/commit/push through Binnacle.
#. Complete hosted PR/review; for every head-changing remediation, create next generation
   and repeat the complete local Phase 6/7/8 candidate chain before further review/CI.
#. Complete exact-head hosted CI/merge through ChatGPT GitHub integration.
#. Bind exact merged OID and update development checkout through Phase 8.
#. Execute Phase 9 restart preflight + controlled restart.
#. Reconnect and reconcile same restart.
#. Verify exact runtime identity and changed behaviour.
#. Close security/audit/fence/credential/broker evidence.
#. Evaluate PASS/FAIL/INCOMPLETE and submit evidence bundle for owner/reviewer acceptance.
#. On accepted PASS, mark Bootstrap milestone complete and stop Bootstrap feature expansion.

47. Holistic pre-review checklist
---------------------------------

Before asking bot reviewers to accept this plan, walk the complete chain:

``real ChatGPT/controller/device -> run readiness -> baseline runtime/repository -> one
Phase 6 development session -> Phase 8 feature branch -> Phase 6 inspect/search/read ->
Phase 6 mutation -> Phase 7 tests/quality -> one recoverable failure/cancel -> exact local
checks -> Phase 8 status/diff -> locally created signed commit -> exact push/reconciliation
-> ChatGPT GitHub PR -> if head changes: NEW GENERATION + repeat Phase 6/7/8 local
content/check/diff/sign/push chain -> final PR head == final signed/pushed OID -> exact-head
substantive review -> exact-head Actions -> hosted merge -> exact merged OID -> Phase 8 local
checkout update -> Phase 9 candidate binding -> restart preflight -> shared Phase 6 CHANGE
fence -> broker accept/checkpoint -> service stop/candidate start / optional manager
reload/recovery -> expected connection loss -> reconnect -> same retained restart
reconciliation -> exact merged runtime identity -> changed MCP behaviour probe ->
security/audit/fence/credential closure -> PASS/FAIL/INCOMPLETE``.

Scrutinize especially:

* stale evidence from an old candidate generation/commit/head/run being reused;
* review/CI on pre-remediation head;
* hosted-authored remediation becoming final head without complete local retest/sign/push;
* push or merge response loss;
* local checkout update not equal to hosted merge OID;
* manual ``git pull`` or shell restart sneaking into loop;
* second restart issued after connection loss;
* candidate rollback mislabeled candidate success;
* runtime HEAD matching while wrong environment/config/service/DB state runs;
* behaviour probe coming from stale connection/catalogue/runtime;
* deliberate failure/cancel not truthfully reconciled;
* unresolved uncertainty hidden by later success;
* credential/helper/root authority leakage;
* Phase 9 recovery profile exceeded by selected candidate;
* evidence bundle claiming Bootstrap complete merely because Phase 10 plan merged.

48. Plan acceptance checklist
-----------------------------

This planning PR may merge when:

* branch starts from exact merged Phase 9 ``master``;
* it adds exactly ``docs/implementation/phase-10-self-hosting-acceptance.rst``;
* it changes no runtime implementation, contracts, manifest or prior numbered plan;
* holistic pre-review has checked full evidence chain and candidate-generation provenance;
* exact-head Contract Validation and Python CI are green;
* mandatory exact-head Codex substantive review is clean;
* actionable threads are resolved;
* Copilot is attempted no more than once on each exact head and remains best-effort;
* every real-Pi/ChatGPT/GitHub execution fact remains explicitly future/evidence-gated.

Plan acceptance completes the **authorized detailed planning workflow through Phase 10**.
It does not complete Bootstrap implementation.

49. Real Phase 10 exit
----------------------

Real Phase 10 exit requires one owner/reviewer-accepted ``PASS`` evidence bundle meeting
section 34 on the real development Pi with real ChatGPT.

The decisive identity/provenance chain is:

::

   exact baseline
      -> feature branch
      -> final candidate generation
      -> exact locally content-bound/tested/diffed source
      -> locally created signed commit OID
      -> pushed remote ref at same OID
      -> exact hosted PR final head at same OID
      -> exact review/CI head at same OID
      -> exact hosted merged OID
      -> exact local update target
      -> exact Phase 9 restart candidate
      -> exact post-restart runtime revision
      -> exact changed behaviour

Every equality/transition is independently evidenced. Any head-changing remediation
creates a new locally proven candidate generation; there is no shortcut from hosted edit to
accepted final head. Any gap is not a partial pass.

The run must additionally prove one safe recoverable failure/cancellation and no reusable
credential/root/workspace-boundary disclosure.

Only after that evidence is accepted is Bootstrap V1 complete.

50. Post-Bootstrap handoff
--------------------------

After accepted PASS:

* stop expanding Bootstrap V1;
* preserve acceptance evidence and exact milestone revision;
* record deferred hardening/architecture gaps without retroactively adding them to
  Bootstrap exit gate;
* use now-working Binnacle self-development loop for subsequent architecture, hardening and
  feature work;
* require future migrations/privilege/credential changes to follow normal reviewed
  contracts rather than inheriting special authority from Bootstrap acceptance run.

The target outcome is not a permanently privileged bootstrap mode. It is a normal,
reviewable Binnacle development workflow that has been proven once end-to-end.
