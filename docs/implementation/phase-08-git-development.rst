Binnacle Phase 8 Detailed Implementation Plan
=============================================

:Phase: 8 -- Implement the minimal Git development workflow
:Status: proposed
:Planning status: provisional -- evidence-independent Git operation, repository-profile,
                  ref/update, credential-use, signing, network, reconciliation, and
                  workspace-coordination semantics are concrete; implementation/promotion
                  remains gated by Phase 4/6/7 implementation exits, reviewed credential
                  provisioning, exact Git-version/platform evidence, and real host evidence
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 4 durable-operation-kernel plan; merged Phase 6 development-
             workspace plan; merged Phase 7 execution-supervisor plan; Phase 4/6/7
             implementation exits before operational Git promotion; real development-
             session/host evidence; protected repository/credential/signing profiles
:Primary objective: Let ChatGPT inspect repository state, create/switch development
                    branches, create a correctly signed commit, fetch/pull narrowly, and
                    push an exact feature branch without exposing reusable SSH/signing
                    credential material, letting repository-controlled configuration gain
                    authority, or bypassing the durable operation/workspace/executor
                    boundaries established in Phases 4/6/7
:Implementation scope: Git operation contracts/schema/manifest promotion barrier; official
                       Git CLI behind typed semantic adapters; registered repository profile;
                       repository-config/attributes/helper-surface validation; dedicated Git
                       execution profile over the Phase 7 supervisor; status/diff/branch/
                       switch/commit/fetch/pull/push semantics; non-exportable repository SSH
                       and commit-signing authority; exact ref/worktree/index coordination;
                       network effect reconciliation; tests, deployment seams, and evidence
                       gates only

Purpose
-------

Phase 8 supplies the repository-side capability required for Binnacle to cross the
self-hosting threshold. It is intentionally narrower than a general Git shell. ChatGPT must
be able to complete the ordinary Binnacle branch workflow while Binnacle preserves exact
operation identity, workspace coordination, credential separation, signed-commit evidence,
and truthful remote-effect reconciliation.

Three rules govern this phase:

* Git is executed through the official Git CLI behind typed semantic adapters and the
  independent Phase 7 supervisor. The MCP/application process never grows a direct
  subprocess escape hatch;
* repository content and repository-local Git configuration are **untrusted data**. They
  may describe repository state, but they never choose credential authority, remote
  destination, helper execution, protected identity, or privileged/control-plane access;
* repository access and commit signing are separate non-exportable capabilities. A Git
  operation receives only the exact authority required for its reviewed semantic action.

This document freezes evidence-independent semantics. It does not claim that the selected
Raspberry Pi already has a Git version supporting every preferred switch, that an SSH or
OpenPGP agent has already been provisioned, that GitHub accepts the selected signing key,
that real ChatGPT exposes any proposed Git Tool, or that any remote push/fetch profile has
passed empirical validation.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-04-durable-operation-kernel.rst``;
#. merged ``docs/implementation/phase-06-development-workspace.rst``;
#. merged ``docs/implementation/phase-07-execution-supervisor.rst``;
#. this Phase 8 plan;
#. ``docs/security/capability-composition.md`` and capability-zone policy;
#. ``docs/security/command-execution.md`` and command profiles;
#. operation idempotency/lifecycle/audit/controller/evaluation contracts;
#. MCP manifest/schema/HOST-confirmation contracts;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

The owner-approved Bootstrap baseline chooses the official Git CLI. ``libgit2``,
``pygit2``, a custom Git implementation, and GitHub-host PR/review/merge APIs inside
Binnacle remain deferred unless an observed blocker requires an explicit later design
change.

2. Roadmap objective and exact exit gate
----------------------------------------

The roadmap requires semantic Git capability sufficient for:

* status;
* diff;
* branch creation;
* switch;
* commit;
* fetch;
* pull;
* push.

It additionally requires one device-specific repository SSH identity, a separate commit-
signing identity, non-exportable credential use, and a normal branch/PR workflow rather
than direct development on protected ``master``.

Real Phase 8 exit is not achieved by this planning PR. It requires real ChatGPT on the
real development Pi to:

#. inspect the registered Binnacle repository status and bounded diff through the reviewed
   semantic Git surface;
#. create one feature/fix branch from an exact reviewed base and switch to it without
   implicit stash/reset/discard;
#. perform the Phase 6 edit and Phase 7 validation work for a small real development
   change;
#. create a signed commit whose exact tree, parent, protected author/committer identity,
   signer fingerprint/signature status, and resulting commit OID are independently
   verified;
#. push exactly the authorised feature branch to the protected registered repository
   destination without exposing reusable SSH/signing credential material;
#. reconcile a lost/retried Git response without creating a duplicate or falsely claiming
   a remote effect;
#. demonstrate that repository-controlled config/hooks/filters/helpers cannot redirect
   credential use, spawn an unreviewed credential-bearing helper, or change the protected
   remote destination;
#. preserve Phase 4 idempotency/audit truth, Phase 6 workspace coordination, and Phase 7
   process/restart evidence throughout the workflow.

GitHub PR creation, hosted review, Actions inspection, and merge remain ChatGPT GitHub-
integration responsibilities in Bootstrap. They are not Phase 8 Binnacle Tools.

3. Three independent gates
---------------------------

3.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

This numbered plan may merge when review and exact-head CI establish that the evidence-
independent Git architecture, operation contracts, credential composition, effect/retry
semantics, tests, and evidence procedure are coherent.

Plan acceptance grants no Git or credential authority.

3.2 Implementation and promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not expose an operational Git Tool until all applicable prerequisites are current:

* Phase 4 durable consequential-operation implementation exit;
* Phase 6 registered workspace/development-session implementation exit, including exact
  ``WorkspaceAccessGate``/durable mutation-fence semantics;
* Phase 7 independent supervisor implementation exit, including exact ticket acceptance,
  output/restart/cancellation/process-isolation semantics;
* real development-session HOST-profile evidence for the selected ChatGPT environment;
* exact Phase 8 operation contracts, schemas, information classes, confirmation/session
  authority class, manifest entries, annotations, and limits reviewed and validated;
* a registered Git repository profile bound to the exact Phase 6 workspace/root/mount
  identity, protected branch policy, remote destination, Git executable/version profile,
  author/committer identity, repository SSH identity reference, signing identity reference,
  known-host policy, and supported repository-feature profile;
* candidate-Pi evidence for the exact Git executable/version and every CLI behavior relied
  on by the promoted profile;
* repository-local/worktree configuration, attributes, hook/helper/filter/submodule/LFS
  surfaces pass the supported-repository validator and are bound by a current digest;
* credential-bearing Git execution proves that repository content cannot choose or invoke
  an unreviewed credential helper, SSH command, proxy/helper, hook, filter, textconv,
  external diff, pager/editor, merge driver, submodule helper, LFS helper, or protocol;
* general Phase 7 ``command_run`` remains unable to access raw keys or the dedicated
  credential/signing authority;
* the selected SSH and signing mechanisms are non-exportable to the model and ordinary
  command processes, and exact credential fingerprint/audience/action bindings are
  revalidated immediately before use;
* status/diff bounds, local ref CAS, switch/commit worktree/index safety, fetch side-effect
  suppression, fast-forward-only pull semantics, and push remote-state reconciliation pass
  unit/integration/fault tests;
* any stale, contradictory, unsupported, or unverifiable prerequisite keeps the affected
  Git Tool invisible/disabled rather than falling back to generic shell Git with ambient
  credentials.

3.3 Phase exit
~~~~~~~~~~~~~~

Phase exit additionally requires the empirical real-Pi/real-ChatGPT procedure in section
38. Automated tests and a locally signed synthetic commit do not establish the complete
host/repository/credential profile.

4. Explicit non-goals
---------------------

Phase 8 does not implement or promote:

* arbitrary Git subcommands through a model-provided command string;
* direct protected-``master`` development or normal direct push to protected ``master``;
* force-push as a generic capability;
* wildcard refspecs, arbitrary tag creation/deletion, arbitrary remote deletion, mirror
  push/fetch, or ``--all`` operations;
* arbitrary remotes chosen from repository-local config;
* user-supplied SSH ``ProxyCommand``/``core.sshCommand`` or arbitrary Git protocol helpers;
* Git credential helpers selected by repository content;
* Git LFS, submodule recursion, custom clean/smudge/process filters, custom merge drivers,
  repository hooks, external diff/textconv, or custom pager/editor execution;
* automatic stash, reset, checkout-force, conflict resolution, merge commits, rebases, or
  history rewriting;
* raw private-key, token, password, agent-cookie, or reusable credential disclosure;
* GitHub PR/review/Actions/merge implementation inside Binnacle;
* package/service/root administration;
* libgit2/pygit2;
* treating Git stdout/stderr as authoritative effect truth;
* blind retry of an uncertain fetch/push/ref/worktree effect;
* deriving protected remote destination or signing identity from untrusted repository
  files.

5. Process and authority topology
---------------------------------

The Phase 8 path composes existing process boundaries rather than adding another long-lived
service:

::

   MCP / CLI adapter
      -> GitApplicationService
      -> Phase 4 operation/policy/audit kernel
      -> Phase 6 workspace access/change coordinator
      -> GitRepositoryProfileValidator
      -> GitOperationTicketBuilder
      -> Phase 7 execution supervisor
      -> dedicated semantic Git process profile
      -> official Git CLI
      -> optional exact operation-owned ssh/gpg child through protected brokered authority

The application owns semantic admission, authoritative operation state, repository/profile
policy, exact target/effect binding, and effect reconciliation. The Phase 7 supervisor owns
process acceptance/lifecycle/output evidence. The Git/credential adapter maps only reviewed
semantic operations into fixed executable/argv/environment/file-descriptor/network plans.

A credential broker/agent may perform one exact SSH/signing action without exporting the
secret. It is **not** a generic shell endpoint and is not reachable by ordinary
``command_run``.

6. Registered Git repository profile
-------------------------------------

Phase 8 introduces a protected ``RegisteredGitRepositoryProfile`` bound to the Phase 6
workspace profile. It is protected configuration/control-plane state, not repository
content and not writable through Phase 6 workspace Tools or Phase 8 Git Tools.

The profile contains at least:

* ``repository_profile_id`` / version;
* exact Phase 6 ``workspace_id`` and workspace-profile version;
* registered root identity and root-mount identity;
* exact Git directory/common-directory identity accepted for this checkout;
* required repository format/worktree mode;
* allowed branch namespace, normally ``refs/heads/<owner-approved-prefix>/...``;
* protected branch set including ``refs/heads/master``;
* exact protected remote transport profile: scheme, host, port, repository path, expected
  server host-key policy, and allowed remote branch namespace;
* Git executable absolute path, reviewed version profile, and executable identity/digest
  where available;
* protected author name/email and committer name/email profile;
* repository SSH credential reference/fingerprint/audience;
* signing credential reference/fingerprint/algorithm/profile;
* supported Git feature flags;
* repository-config/attributes/helper-surface policy version;
* output/object/ref/pack/timeout/resource ceilings;
* policy/profile digest and activation state.

The repository profile never stores raw private key bytes in model-visible or ordinary
operation state.

7. Repository identity and supported-shape verification
-------------------------------------------------------

Every semantic operation first verifies the exact registered checkout under the Phase 6
root/mount/no-submount boundary.

Bootstrap supports the normal single registered Binnacle development worktree first. A
repository shape is unsupported when exact identity or containment cannot be established,
including ambiguous external ``GIT_DIR`` indirection, unexpected linked-worktree/common-dir
layout, unsafe symlink/mount escape, or repository format/extensions not covered by the
reviewed profile.

A bounded ``GitRepositorySnapshot`` records enough current facts for admission and final
revalidation, including as applicable:

* HEAD symbolic/detached state;
* current branch ref and OID;
* exact selected index identity/digest/metadata;
* worktree status digest/projection;
* repository config/worktree-config identities and safety digest;
* attributes/helper-surface digest;
* relevant ref OIDs;
* registered remote-profile identity, never mutable repo URL authority;
* Git object-format identity;
* workspace/root/mount/profile versions;
* capture time/runtime provenance.

Mutable current observations are not idempotency authority by themselves. Operation-
specific request fingerprints bind the exact effect-bearing expected state required by the
operation contract.

8. Repository-local configuration is untrusted data
----------------------------------------------------

Skipping system/global Git config does **not** make repository-local configuration
trustworthy. Phase 8 therefore treats ``.git/config`` and worktree config as untrusted
repository inputs.

Before a Git capability is enabled for a repository snapshot, ``GitRepositoryProfileValidator``
performs a bounded, side-effect-free validation under the appropriate Phase 6 access guard.
The validation does not follow arbitrary config includes or execute any Git helper.

The supported Bootstrap repository profile rejects or explicitly neutralizes at least:

* ``include`` / ``includeIf``;
* ``credential.helper`` and related ambient credential selection;
* repository-selected remote destination for credential-bearing operations;
* ``url.*.insteadOf`` / ``pushInsteadOf``;
* ``core.sshCommand``;
* protocol/proxy/helper settings that can execute commands or redirect the protected
  destination;
* ``diff.external`` and diff-driver textconv helpers;
* pager/editor/sequence-editor settings;
* repository-selected hooks path or executable hooks;
* clean/smudge/process filters;
* custom merge drivers;
* submodule recursion/config requiring helper execution;
* Git LFS/custom external extensions;
* unsupported alternates/object-store indirection that escapes the reviewed repository
  storage profile;
* unsafe ownership/safe-directory ambiguity;
* any config form whose security effect cannot be classified under the reviewed profile.

The validator produces a bounded canonical ``repository_safety_digest`` over the exact
validated config/attributes/helper surface. Credential-bearing and mutating operations bind
that digest into admission and revalidate it at the final consequential boundary.

A future broader profile may support additional repository features only through an
explicit reviewed contract revision. Bootstrap does not silently inherit the user's normal
interactive Git configuration.

9. Git process purity and closed environment
--------------------------------------------

Every Phase 8 Git process is built from a closed typed ``GitExecutionPlan``. It contains:

* absolute reviewed Git executable;
* fixed semantic argv template plus validated operation-specific values;
* exact registered worktree/Git-dir context;
* fixed noninteractive stdin plan;
* allowlisted environment;
* exact FD map;
* network policy;
* credential/signing capability references where applicable;
* resource/output/time ceilings;
* expected result parser and effect reconciler.

The environment does not inherit arbitrary service/user environment. Bootstrap sets or
binds values such as:

* ``GIT_CONFIG_SYSTEM=/dev/null`` and ``GIT_CONFIG_GLOBAL=/dev/null`` or reviewed exact
  protected files;
* closed ``HOME``/``XDG_CONFIG_HOME`` appropriate to the Git operation profile;
* ``GIT_TERMINAL_PROMPT=0``;
* closed/disabled ``GIT_ASKPASS`` / ``SSH_ASKPASS`` unless a specific protected brokered
  mechanism requires an operation-owned helper;
* ``GIT_PAGER=cat`` / no interactive pager;
* no model-provided ``GIT_SSH_COMMAND``;
* explicit protocol allowlist;
* command-scope configuration used only to neutralize/force reviewed behavior and itself
  included in the ticket digest.

Repository-local config is still validated separately because ordinary repository Git
commands may consume it despite system/global isolation.

No Git operation uses a shell command string. User/model data is passed as structured argv
or bounded stdin and cannot become config, executable path, helper command, or environment
name.

10. Phase 6 workspace coordination
----------------------------------

Phase 8 consumes the same ``WorkspaceAccessGate`` and durable workspace mutation fence as
Phases 6 and 7. Git does not create a bypass writer path.

Coordination modes are:

``GIT_READ``
   Read-only Git inspection. It maps to the Phase 6 shared content/read coordination seam
   or an exact reviewed Git-read projection that excludes concurrent Binnacle-managed
   changers for the full traversal/process lifetime.

``CHANGE``
   Any Git operation that may modify refs, index, worktree, Git metadata relevant to later
   security decisions, fetched object/ref state, or local checkout state. It acquires the
   exclusive Phase 6 CHANGE side and one durable mutation fence before consequential
   effect.

Bootstrap defaults conservatively:

* ``git_status`` and bounded ``git_diff`` are ``GIT_READ``;
* branch creation, switch, commit, fetch, pull, and push use ``CHANGE`` unless a later
  reviewed contract proves a narrower coordination mode without creating races.

The guard/fence remains held until process descendants, Git lock files/temporary files,
index/ref/worktree effect knowledge, credential-child lifecycle, output/evidence, and audit
obligations are truthfully closed. ``uncertain`` retains the fence.

11. Proposed MCP semantic surface and promotion barrier
-------------------------------------------------------

The following names are **proposals only** until their exact operation contracts, schemas,
manifest entries, information classes, annotations, confirmation/session authority, and
limits are reviewed:

* ``git_status``;
* ``git_diff``;
* ``git_branch_create``;
* ``git_switch``;
* ``git_commit``;
* ``git_fetch``;
* ``git_pull``;
* ``git_push``.

Runtime handlers must not exist in the visible catalogue before promotion. The current
Bootstrap manifest remains authoritative until an explicit reviewed change adds Phase 8.

Read-only result Tools are bounded and normally restricted/untrusted repository content as
required by the information policy. Mutating/network Git operations consume Phase 4 durable
operation semantics and the exact development-session/host authority profile selected by
the promoted contract.

12. Common operation request identity
-------------------------------------

Every consequential Git operation request fingerprint includes at least:

* Tool/operation contract version;
* exact repository/workspace profile identity/version;
* controller/device identity/epoch;
* development-session identity/version where required;
* semantic action;
* exact protected branch/ref/remote target as applicable;
* exact expected current OIDs or absence predicates;
* relevant index/worktree/config/attributes safety digests;
* exact message/content/tree/parent digest for commit;
* credential/signing capability profile identities where applicable;
* maximum effect;
* policy/profile versions;
* caller idempotency identity/prepared binding as the operation contract requires.

The fingerprint excludes mutable policy results and observations that are explicitly
revalidated rather than effect-bearing input.

Same-key/different-input reuse is rejected. Same-key/same-input reconciliation resolves the
retained Phase 4 operation and never creates a fresh Git effect merely because the current
repository happens to look similar.

13. ``git_status``
------------------

``git_status`` is bounded and read-only.

The preferred adapter uses a machine-readable status form with a closed argv, no pager,
no hooks/helpers, and ``GIT_OPTIONAL_LOCKS=0`` so the read path does not intentionally take
optional repository locks or refresh mutable metadata.

The result is a normalized bounded projection, not raw unbounded porcelain text. It may
include:

* current branch/HEAD state;
* staged/unstaged/untracked/conflict state within configured item/byte ceilings;
* ahead/behind only when the exact local refs required for that computation are already
  available and no network effect is triggered;
* truncation/incomplete flags;
* repository/profile identity and snapshot digest.

Status never auto-fetches, refreshes credentials, writes an index, runs maintenance, or
executes repository helpers. If the selected Git version/repository shape cannot prove that
profile, the Tool remains disabled.

14. ``git_diff``
----------------

``git_diff`` returns a bounded repository diff under ``GIT_READ``.

The contract requires an explicit diff mode, for example:

* worktree vs index;
* index vs exact HEAD;
* exact commit/tree A vs exact commit/tree B.

No arbitrary revision expression is accepted when a closed OID/ref input can be used.
Output has file-count, hunk, line, byte, and timeout ceilings and truthful truncation.

The adapter disables external diff/textconv execution and does not invoke pagers or
repository helpers. Attributes/config that would require a custom driver/filter cause the
repository profile or requested diff mode to be rejected rather than executing the helper.

Diff content is untrusted/model-visible only under the normal repository-content information
policy; it is never authority for a later credential/system action.

15. ``git_branch_create``
------------------------

Branch creation is a consequential local-ref effect under ``CHANGE``.

Input binds:

* exact normalized new branch name within the allowed feature/fix namespace;
* exact source commit OID;
* required target-ref absence;
* repository/profile/session state;
* exact current branch/HEAD constraints if the contract cares about them.

The preferred effect primitive is official ``git update-ref`` expected-old/absence CAS.
Creating a branch requires target absence, represented by Git's exact nonexistence
precondition. The operation never falls back to an overwrite-capable ref update.

The final OP-BOUNDARY revalidates source object type/OID, target absence, repository safety
digest, workspace/repository profile, session/policy/audit/fence state, and branch policy.

Success is proven by the exact Git effect receipt plus independently read ref value under the
retained operation evidence. Response loss is reconciled against the durable operation and
exact target ref. A current target OID match alone may support reconciliation only when the
operation contract can prove no conflicting actor could have produced the same transition;
otherwise retained Git/process/audit evidence remains necessary.

16. ``git_switch``
------------------

Switch changes HEAD/index/worktree and therefore always uses ``CHANGE``.

The contract accepts an exact already-existing local branch/ref and binds:

* expected current HEAD ref/OID;
* target branch ref/OID;
* expected index/worktree status digest;
* clean-state requirements;
* repository safety/profile digest;
* exact maximum effect.

Bootstrap switch refuses:

* implicit stash;
* implicit reset/discard;
* force checkout;
* unresolved conflicts;
* detached-HEAD surprises not explicitly requested by a future contract;
* submodule recursion;
* helper/filter behavior outside the supported repository profile.

If the current worktree/index differs from the bound expected snapshot at final boundary,
return stale-state with no switch effect.

The implementation may use a reviewed official porcelain/plumbing sequence that preserves
ordinary checkout semantics without helper execution. The exact Git version/profile must
be proven on the candidate Pi. The plan does not freeze a fragile hand-written worktree
algorithm before that evidence; it freezes the no-loss/no-stash/no-force semantics and the
Phase 4/6/7 ordering.

A lost response after worktree/index mutation is not classified solely from current HEAD.
Index/worktree effect evidence and Git process receipt must be reconciled; ambiguous partial
checkout remains ``uncertain`` and retains the workspace fence.

17. Commit semantics
--------------------

Commit is a high-value local Git mutation because it combines repository content, protected
identity, signing authority, object creation, and branch-ref update.

Bootstrap prefers a controlled plumbing path rather than unrestricted ``git commit``
porcelain:

#. acquire ``CHANGE`` + durable workspace mutation fence;
#. bind exact current branch ref/OID, expected worktree/index state, repository safety
   digest, protected author/committer profile, commit message digest, and signing profile;
#. construct an operation-local index/tree using reviewed Git plumbing from the exact
   intended workspace content/modes without invoking repository clean/smudge filters or
   hooks;
#. run ``write-tree`` and record the exact tree OID;
#. create the commit object with official ``commit-tree`` using the exact parent OID,
   bounded message input, protected author/committer environment, and exact signing
   capability;
#. verify the created commit object: tree, parent set, author/committer identity, message
   digest, signature presence/status, signer fingerprint, and object OID;
#. update the exact current feature branch using ``update-ref`` CAS from old parent OID to
   the new commit OID;
#. reconcile the normal worktree/index representation explicitly and verify expected
   post-state;
#. close audit/credential/process/fence obligations only after truthful repository state is
   established.

No commit is created on protected ``master`` under the normal development profile.

17.1 Operation-local index
~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not let an unreviewed main-index mutation become an implicit staging API. The preferred
Bootstrap commit path uses an operation-owned temporary index (for example through a
protected operation-local ``GIT_INDEX_FILE``) whose path and lifecycle are not model-
controlled.

The tree-builder consumes the exact intended repository/workspace snapshot and modes. It
must not invoke repository-defined clean/smudge/process filters. If the repository semantics
cannot be faithfully represented without an unsupported filter/LFS/submodule behavior, the
commit capability is disabled for that repository profile.

The temporary index is private, bounded, operation-owned, fsync/cleanup-aware as required by
the platform profile, and never treated as reusable credential/protected content.

17.2 Commit message and identity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Commit message is untrusted model input with explicit byte/encoding limits. It is passed as
bounded stdin/file data, not shell/config syntax.

Author and committer name/email come from protected owner/device Git profile. The model may
not substitute an arbitrary identity in Bootstrap. Author/committer timestamps follow the
reviewed time policy and are recorded as effect-bearing facts when exact reproducibility or
reconciliation requires them.

17.3 Signing
~~~~~~~~~~~~

The commit-signing identity is separate from repository transport SSH authority.

The signing request binds:

* exact operation/commit-preimage/tree/parent/message identity;
* exact signing key fingerprint/reference;
* signing algorithm/profile;
* controller/device/repository/session context;
* expiry/one-action authority;
* output/evidence limits.

Raw private key material is never put in argv, environment, stdin, output, audit, SQLite,
or model-visible data. A protected operation-owned signing agent/socket/helper may be mapped
only into the exact Git signing process tree and removed when the operation ends.

After ``commit-tree -S`` (or the exact reviewed official equivalent), Binnacle independently
verifies that the resulting commit has the expected signature and signer fingerprint before
allowing branch-ref CAS. Signing failure or wrong signer produces no branch-ref update.

17.4 Ref CAS and unreachable objects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The branch transition is ``expected_old_oid -> new_signed_commit_oid``. It is performed by
an exact expected-old ref update. If CAS fails because the branch changed concurrently, the
branch remains unchanged. The newly created commit/object may be unreachable; this is a
benign retained object, not evidence that the branch changed.

No retry creates another commit object/ref effect under a fresh operation merely to work
around a stale branch. The caller must reconcile/re-admit against the new state.

18. Repository SSH authority
----------------------------

Repository transport uses one protected device-specific SSH identity/reference for the
registered Binnacle repository, preferably repository-scoped where the hosting service
supports it.

The protected remote profile owns:

* exact transport scheme;
* host and port;
* repository path/identity;
* SSH credential reference and public fingerprint;
* expected server host-key/known-host policy;
* allowed action (fetch/pull/push as applicable);
* allowed source/destination refs;
* listener/network/resource profile;
* credential-broker profile/version.

Repository-local ``remote.*.url`` is informational at most. Credential-bearing operations
use the protected remote profile, not mutable repository config, to choose the effective
destination.

SSH config is closed/protected. ``ProxyCommand``, arbitrary identity files, arbitrary
known-host bypass, agent forwarding, port forwarding, and user-provided ssh options are not
part of Bootstrap.

19. Credential-broker composition
---------------------------------

Credential-bearing Git actions are explicit high-risk compositions:

``untrusted repository state``
   -> validated repository safety digest
   -> exact semantic Git operation
   -> exact protected remote/signing target
   -> one operation-scoped credential capability
   -> supervised Git/SSH/GPG process tree

The broker/agent validates exact audience and action at the consequential boundary. It does
not expose a general socket that the ordinary Phase 7 command profile can discover.

Credential authority is represented by opaque protected references/digests. Operation
results may report public key fingerprint, signing verification status, and credential-
profile identity where safe, but never raw secret material.

20. ``git_fetch``
-----------------

Fetch is a credential/network effect and also changes local object/ref metadata. Bootstrap
therefore uses ``CHANGE`` and the Phase 4 consequential path.

The request binds:

* protected remote profile;
* exact remote source ref(s), normally one branch;
* exact local destination ref namespace/OID preconditions;
* expected repository/config safety digest;
* credential capability;
* exact fetch-side-effect profile;
* object/pack/ref/output/time ceilings.

The adapter uses explicit repository URL/refspec from protected configuration. It never
uses default ``origin`` selection from mutable repo config.

The preferred narrow profile suppresses default side effects that are not part of the
contract, including ``FETCH_HEAD`` writing, automatic maintenance, and commit-graph writing,
when the candidate Git version proves the required switches. Atomic ref update mode is used
where the operation updates multiple exact local refs and the reviewed Git version supports
the desired semantics. The plan does not claim concurrent readers observe multi-ref updates
as an indivisible snapshot beyond Git's documented guarantees.

No ``--all``, implicit tag sweep, pruning, submodule recursion, or arbitrary force fetch is
allowed in Bootstrap.

Downloaded objects/packfiles are a real local effect even when the intended ref update later
fails. Effect knowledge and retry semantics must therefore distinguish object transfer from
ref publication. Response loss or process failure after network transfer may be
``known_effect`` or ``uncertain`` depending on retained Git/executor evidence; it is never
blindly repeated just because the target ref did not move.

21. ``git_pull``
----------------

Bootstrap pull is **not** arbitrary ``git pull`` merge/rebase porcelain. It is a semantic
composition:

#. exact protected ``git_fetch`` under the reviewed narrow fetch profile;
#. verify the exact fetched target OID and expected local current branch OID;
#. prove fast-forward ancestry using a reviewed local Git query;
#. if fast-forward is not possible, return ``git_diverged`` with no automatic merge/rebase;
#. perform an explicit fast-forward-only local integration under the same/reconciled CHANGE
   coordination and exact expected-old ref/worktree/index preconditions;
#. verify resulting ref/index/worktree state and close the operation truthfully.

The operation binds enough phase-stable evidence to distinguish expected self-owned
fetch/ref transitions from unrelated concurrent mutation.

No conflict resolution, auto-stash, merge commit, rebase, or reset occurs implicitly.

Because fetch and local integration are separate consequential boundaries, the operation
model records intermediate effect knowledge. A successful fetch followed by a stale local
integration is not ``known_no_effect``; downloaded objects/ref updates remain real effects.

22. ``git_push``
-----------------

Push is the highest-value Phase 8 remote effect because it composes untrusted repository
state, protected SSH authority, network egress, and a hosted ref mutation.

Bootstrap push input binds:

* exact protected remote profile/destination;
* exact local source branch ref and commit OID;
* exact remote destination branch ref;
* exact expected remote old OID or exact nonexistence predicate;
* protected-branch policy;
* repository safety digest;
* credential capability/audience;
* maximum effect and response/evidence bounds.

Only an allowed feature/fix branch destination is accepted. Direct normal push to protected
``master`` is rejected.

No wildcard refspec, tag side effect, delete, mirror, arbitrary push option, or generic
force is allowed. If a contract ever requires a non-fast-forward exact replacement, it must
use an explicit exact expected-remote-OID lease/CAS profile; bare ``--force`` or a lease that
derives expectations from mutable remote-tracking refs is not sufficient.

The adapter supplies the protected explicit remote URL/refspec and closed SSH environment.
Repository config cannot select the destination, credential helper, SSH command, proxy, or
protocol helper.

22.1 Remote preflight
~~~~~~~~~~~~~~~~~~~~~

Where the remote protocol/profile can safely obtain the exact current destination OID,
Binnacle records that as current-state evidence before final admission/effect. The expected
remote OID is effect-bearing request input when the contract requires it.

DNS/host/known-host/credential audience and exact destination are revalidated at final
boundary. A changed expected remote ref blocks the push before effect when it can be proven
without causing an unintended mutation.

22.2 Push response loss and reconciliation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A successful process exit/line of stdout is useful evidence but not sufficient by itself
when response transport is lost or remote outcome is ambiguous.

Reconciliation rules are conservative:

* independent current remote ref equal to the exact intended target OID may prove the
  **current desired effect** for the exact bound destination when the remote read itself is
  trustworthy and the operation contract accepts that proof;
* a current remote ref different from the intended target does **not** prove the push never
  happened -- another actor may have changed it after a successful push;
* a local remote-tracking ref is never treated as authoritative proof of the hosted ref;
* ambiguous remote effect remains ``uncertain`` and is not retried blindly with a new
  operation/key;
* same-key retry reconciles the retained operation/evidence first.

The audit record stores safe remote destination/ref/OID/evidence digests, never private key
material.

23. Phase 4 consequential-operation ordering
--------------------------------------------

Every consequential Phase 8 operation follows the merged Phase 4 kernel and Phase 6/7
handoffs. Conceptually:

::

   authenticate / normalize semantic Git request
     -> caller-binding-first durable idempotency lookup / minimal received identity
     -> required received audit
     -> local policy / repository profile / development-session checks
     -> acquire Phase6 CHANGE where required
     -> create exact durable workspace mutation fence / Git current-state binding
     -> persist authorised decision + authorised audit
     -> build exact Git operation ticket / credential plan
     -> running + effect.intent_recorded
     -> Phase4 per-operation handoff
     -> DevelopmentSessionAuthorityGate
     -> Phase4 ConsequentialBoundaryGate
     -> final controller/device/session/repository/root/mount/config/attributes/ref/index/
        worktree/remote/credential/network/audit/fence OP-BOUNDARY
     -> durable audit-obligation marker
     -> Phase7 supervisor single-use acceptance
     -> exact Git/SSH/GPG process effect
     -> immediate durable supervisor/process/effect receipt
     -> operation-specific Git reconciliation
     -> post-effect audit / credential cleanup / process-tree cleanup / fence closure
     -> restart reconciliation
     -> retained same-key retry

Post-policy exact-self changes such as the operation-owned workspace fence, temporary index,
expected ref lock/CAS inputs, or fetched exact self-owned refs are represented phase-stably
in the final verifier. The final boundary does not reject the operation merely because it
sees an expected self-owned transition, and it does not reconstruct integrity solely from
mutable surviving Git state.

24. Phase 7 supervisor integration
----------------------------------

Phase 8 does not bypass or weaken Phase 7.

Every Git process uses an exact ``GitExecutionTicket`` mapped to the Phase 7 ticket model and
bound to:

* operation/repository/controller/device/session identity;
* semantic Git action;
* Git executable identity/version profile;
* exact argv/stdin/environment/FD digests;
* workspace/root/mount/Git-dir identity;
* repository safety digest;
* ref/index/worktree/remote expectation digests;
* network profile;
* process isolation/resource/output limits;
* optional exact credential/signing capability references;
* expiry/single-use nonce.

The supervisor independently validates the ticket/profile mapping it is responsible for and
retains normal Phase 7 start/cancel/output/restart evidence. One ticket cannot launch twice.

Git children use the preferred distinct unprivileged execution identity/process domain and
inherit Phase 7 ptrace/process-introspection isolation. Credential-bearing exact child
helpers remain inside the same attributable supervised descendant tree.

25. Effect knowledge by operation
---------------------------------

The generic Phase 4 effect-knowledge enum remains authoritative; Phase 8 defines operation-
specific interpretation.

``git_branch_create``
   Ref CAS not attempted/accepted -> known no branch effect. CAS success -> known effect.
   Lost receipt after possible CAS -> reconcile exact ref plus retained process evidence;
   ambiguity -> ``uncertain``.

``git_switch``
   Worktree/index update may be partial before process failure. Any possible started switch
   without complete verified post-state may be ``partial``/``uncertain`` according to the
   Phase 4 contract; never infer success from HEAD alone.

``git_commit``
   Commit-object creation is an effect even if signing/ref CAS later fails. A signed commit
   object plus failed branch CAS is known object effect with no branch-ref effect. The
   operation result reports the exact distinction. Ambiguous branch CAS remains uncertain.

``git_fetch``
   Pack/object transfer and local ref publication are separate effect facts. Failed ref
   update does not erase downloaded-object effect.

``git_pull``
   Fetch effect and local fast-forward integration are separate facts. Failure/staleness in
   the second stage does not rewrite the first stage to no-effect.

``git_push``
   Remote ref mutation is independent external effect. Ambiguous network/response outcome is
   uncertain until reconciled by trustworthy remote evidence.

26. Idempotency and retained retry
----------------------------------

A Phase 8 retry with the same idempotency identity never blindly repeats Git.

Retained reconciliation first examines:

* authoritative Phase 4 operation state/effect knowledge;
* Phase 7 executor ticket/acceptance/process evidence;
* exact Git operation evidence;
* ref/index/worktree/object evidence;
* remote evidence for network effects;
* audit-obligation closure;
* credential-use evidence;
* workspace fence ownership.

If outcome is ``uncertain``, the same-key response reports uncertainty/reconciliation status
and does not launch a fresh Git/SSH/GPG process. A new idempotency key is not a legitimate
way to bypass unresolved uncertainty for the same intended effect.

27. Application restart reconciliation
--------------------------------------

After MCP/application restart:

#. restore Phase 4 audit/operation readiness;
#. restore Phase 6 workspace access coordinator and durable fence ownership;
#. reconcile Phase 7 supervisor accepted/running/terminal Git execution evidence;
#. restore exact Phase 8 Git operation facts, temporary-index/credential obligations, and
   repository-profile binding;
#. query current repository state only as an observation, never as sole effect truth;
#. reconcile ref/index/worktree/object/remote evidence according to the operation type;
#. retain CHANGE/fence when any Git process, credential child, lock/temp, partial worktree,
   remote effect, or audit obligation remains ambiguous;
#. expose retained operation status/output/result only after the resulting state is
   schema-valid and ownership-scoped.

An application restart must not cause a new Git process or credential use for an already
accepted retained logical operation unless the exact reconciliation contract explicitly
allows a no-effect reissue and Phase 4 idempotency proves it safe.

28. Supervisor crash/restart reconciliation
-------------------------------------------

Phase 7 semantics remain authoritative for process acceptance/launch ambiguity. Phase 8
adds Git-specific evidence interpretation.

If the supervisor cannot prove whether a credential-bearing Git/SSH/GPG process crossed its
external effect boundary, the application does not infer no-effect from PID absence. It
reconciles through retained Git/remote evidence and otherwise remains uncertain.

The workspace fence and protected credential-use obligation remain closed until exact
process-tree and credential-child cleanup are proven.

29. Protected branch and workflow policy
----------------------------------------

Normal Binnacle self-development policy is:

::

   protected master
      -> exact feature/fix branch creation
      -> switch
      -> Phase6 edit
      -> Phase7 test/quality
      -> signed Phase8 commit
      -> Phase8 push exact feature/fix branch
      -> ChatGPT GitHub integration PR/review/Actions/merge
      -> later local update/restart through reviewed phases

Phase 8 does not implement the hosted PR/review/merge actions and does not use the Git SSH
credential as a substitute for repository-host governance.

The protected branch set is local protected configuration. Repository content cannot remove
``master`` protection.

30. HOST confirmation and development-session authority
-------------------------------------------------------

The owner-approved bounded development session is the normal authority boundary for routine
same-objective development workflow, but Phase 8 must still reconcile exact host-confirmation
semantics before promotion.

Read-only Git inspection may use the reviewed no-effect class appropriate to bounded
repository content. Local branch/switch/commit and network credential effects require the
reviewed session-scoped/mutation authority model. Credential use remains a permanent local
capability boundary even inside the development session.

No model statement, Tool annotation, repository file, Git commit message, branch name, or
remote response grants credential authority. Local authority derives from authenticated
controller + local policy + exact live development session + protected repository/credential
profiles + durable operation/ticket bindings.

31. Contract/schema/manifest promotion
--------------------------------------

Before runtime handler exposure:

#. define versioned operation contracts for each promoted Git semantic operation;
#. define exact input/output JSON Schemas;
#. define operation/effect/retry/current-state-binding semantics;
#. define information class and result bounds;
#. define host-confirmation/session-authority class;
#. define idempotency requirement for every consequential operation;
#. define credential capability composition where applicable;
#. add exact manifest entries and handler bindings;
#. pass schema/manifest/confusable-name/handler parity validation;
#. record the promoted manifest/config digests used by runtime readiness.

Proposed names and fields in this plan are not themselves the promoted contract.

32. Bounded errors and diagnostics
----------------------------------

Phase 8 needs typed bounded error vocabulary, including as appropriate:

* ``git_repository_profile_unavailable``;
* ``git_repository_identity_mismatch``;
* ``git_repository_shape_unsupported``;
* ``git_repository_config_unsupported``;
* ``git_repository_safety_changed``;
* ``git_protected_branch``;
* ``git_invalid_ref``;
* ``git_ref_exists``;
* ``git_ref_stale``;
* ``git_worktree_dirty``;
* ``git_index_stale``;
* ``git_conflict_state``;
* ``git_helper_surface_unsupported``;
* ``git_signing_unavailable``;
* ``git_signing_failed``;
* ``git_signer_mismatch``;
* ``git_credential_profile_unavailable``;
* ``git_remote_destination_mismatch``;
* ``git_remote_ref_stale``;
* ``git_diverged``;
* ``git_fetch_partial``;
* ``git_push_uncertain``;
* ``git_process_uncertain``;
* ``git_output_truncated``;
* normal Phase 4/6/7 authentication/policy/session/audit/fence/ticket/recovery errors.

Diagnostics may expose safe public Git/version/profile/ref/OID/fingerprint facts and bounded
reason codes. They never expose private key material, credential-agent protocol secrets,
unredacted protected config, or arbitrary helper command content.

33. Ports and adapters
----------------------

Representative application/domain interfaces are conceptual and may be renamed during
implementation while preserving contracts:

.. code-block:: python

   class GitRepositoryInspector(Protocol):
       async def snapshot(self, profile: RegisteredGitRepositoryProfile) -> GitRepositorySnapshot: ...

   class GitRepositoryProfileValidator(Protocol):
       async def validate(self, snapshot: GitRepositorySnapshot) -> RepositorySafetyAssessment: ...

   class GitAdapter(Protocol):
       async def status(self, plan: GitStatusPlan) -> GitStatusResult: ...
       async def diff(self, plan: GitDiffPlan) -> GitDiffResult: ...
       async def branch_create(self, plan: GitBranchCreatePlan) -> GitEffectResult: ...
       async def switch(self, plan: GitSwitchPlan) -> GitEffectResult: ...
       async def create_signed_commit(self, plan: GitCommitPlan) -> GitCommitResult: ...
       async def fetch(self, plan: GitFetchPlan) -> GitFetchResult: ...
       async def fast_forward(self, plan: GitFastForwardPlan) -> GitEffectResult: ...
       async def push(self, plan: GitPushPlan) -> GitPushResult: ...

   class GitCredentialCapabilityBroker(Protocol):
       async def prepare_repository_ssh(self, request: GitSshCapabilityRequest) -> OpaqueCapability: ...
       async def prepare_commit_signing(self, request: GitSigningCapabilityRequest) -> OpaqueCapability: ...

   class GitEffectReconciler(Protocol):
       async def reconcile(self, operation: OperationSnapshot) -> GitReconciliationResult: ...

The implementation should keep Git command construction, repository safety validation,
credential capability mapping, process execution, remote evidence reading, and operation
orchestration behind separate typed seams.

34. Repository layout and implementation seams
----------------------------------------------

A likely implementation layout is:

::

   src/binnacle/domain/git.py
   src/binnacle/application/git/
       service.py
       repository_profile.py
       operation_plans.py
       reconciliation.py
   src/binnacle/adapters/git/
       cli.py
       config_validator.py
       status.py
       diff.py
       refs.py
       commit.py
       fetch.py
       push.py
   src/binnacle/adapters/credentials/
       git_ssh.py
       git_signing.py
   src/binnacle/infrastructure/git/
       profile_store.py
   tests/unit/git/
   tests/integration/git/
   tests/security/git/

Do not create empty layers merely to match this sketch. Reuse Phase 4/6/7 ports where they
already provide the required seam.

35. Protected configuration and persistence
-------------------------------------------

Protected repository/credential profiles live outside the source workspace in the normal
Binnacle protected configuration/state areas. They are versioned, digest-bound, owner-
governed, and not mutable through Git/workspace operations.

Application SQLite may persist authoritative Phase 8 operation metadata such as:

* operation-specific Git semantic type;
* repository-profile/version/digest snapshot;
* expected/current/result ref/tree/commit OIDs;
* repository safety digest;
* temporary index/effect-reference identities;
* public signer/SSH fingerprints;
* credential capability reference digests, never secrets;
* remote destination/ref/evidence digests;
* phase-specific effect knowledge/reconciliation status;
* Phase 7 execution references;
* workspace fence linkage;
* audit references.

The Phase 7 executor does not open application SQLite. Its normal minimal execution evidence
store remains separate.

36. Security invariants
-----------------------

The implementation must preserve at least:

#. Repository content/config/output is untrusted data, never credential or policy authority.
#. Git executes only through the Phase 7 supervisor; no MCP-process direct-subprocess
   fallback exists.
#. General ``command_run`` receives no raw Git SSH/signing secret or ambient dedicated agent.
#. Repository SSH and commit-signing authority are separate exact capabilities.
#. Protected remote destination/ref policy is not chosen by mutable repository config.
#. Credential-bearing operations revalidate repository safety digest, destination, audience,
   action, controller/device/session/profile, and credential identity immediately before
   effect.
#. Repository-local includes/helpers/hooks/filters/textconv/external diff/submodule/LFS or
   other unsupported executable surfaces cause fail-closed behavior.
#. Status/diff cannot execute helpers or trigger network/credential effects.
#. Branch creation cannot overwrite an existing ref.
#. Switch never implicitly discards/stashes/resets user work.
#. A branch ref is updated to a new commit only after exact signed-commit verification.
#. Protected ``master`` is not a normal direct development/push target.
#. Fetch default side effects are narrowed to the reviewed effect contract.
#. Pull is fetch + verified fast-forward-only integration, never automatic merge/rebase.
#. Push binds exact local OID + destination ref + expected remote old OID/nonexistence as
   required by the contract; no generic force/wildcard behavior.
#. Remote state differing after an ambiguous push does not prove the push never occurred.
#. Phase 6 workspace guard/fence covers all Binnacle-managed Git changers for their truthful
   effect/cleanup lifetime.
#. Phase 4 operation/idempotency/audit truth and Phase 7 process/restart evidence are never
   replaced by surviving Git pathname/ref observations.
#. Raw/reusable credentials never enter model-visible results, ordinary logs, audit payloads,
   application SQLite, general command output, argv, or unprotected files.
#. Missing candidate-Pi/Git/credential/host evidence disables the affected capability rather
   than weakening the boundary.

37. Test strategy
-----------------

37.1 Unit and property tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cover at least:

* ref-name normalization/namespace/protected-branch policy;
* repository snapshot/current-state canonicalization;
* repository-safety digest determinism;
* config/helper-surface rejection matrix;
* operation request fingerprints/idempotency conflicts;
* branch-create absence/old-OID CAS mapping;
* switch stale/dirty/conflict rejection;
* commit tree/parent/message/identity/signature/ref-CAS state machine;
* fetch object/ref intermediate effects;
* pull fast-forward/divergence state machine;
* push expected-remote-state/effect reconciliation;
* output/truncation/error parser bounds;
* credential capability audience/action binding;
* exact Phase 4 effect-knowledge cross-field validity;
* same-key retry never emits a second effect from uncertainty.

37.2 Integration tests with real Git CLI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use temporary local repositories and exact Git versions in CI where available. Cover:

* clean/dirty/conflicted/untracked status;
* bounded diff with binary/large content;
* branch create CAS and concurrent creator;
* switch with stale index/worktree and no implicit data loss;
* operation-local index/tree creation;
* signed commit using a test-only signing identity, verification, wrong-signer and signing
  failure;
* ref CAS race after commit object creation;
* fetch explicit refspec with default ``FETCH_HEAD``/maintenance/commit-graph side effects
  suppressed according to the selected profile;
* pull fast-forward and divergence rejection;
* push to a local controlled SSH/bare-repository fixture with exact expected remote OID;
* lost/ambiguous push response and independent remote-ref reconciliation;
* application restart with Phase 7 executor evidence;
* supervisor crash around Git/SSH/GPG process start/exit;
* Phase 6 CHANGE/fence concurrency with workspace edits/commands.

37.3 Adversarial repository tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Construct repositories containing hostile:

* local/worktree ``include``/``includeIf``;
* ``credential.helper`` including shell snippets;
* URL rewrite and unexpected remote config;
* ``core.sshCommand``;
* proxy/protocol helper settings;
* hooks/hook-path overrides;
* ``.gitattributes`` filter/textconv/external-diff surfaces;
* LFS/submodule configuration;
* fake pager/editor/merge driver;
* alternate-object-store indirection;
* branch/ref names intended to escape the allowed namespace;
* repository config changed between admission and final boundary.

Credential-bearing operation must execute zero hostile helper processes, use only the
protected destination/capability, or remain disabled.

37.4 Credential and process-boundary tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prove:

* general Phase 7 command environment/FDs have no SSH/signing agent capability;
* exact Git process receives only the operation-owned capability needed for that action;
* SSH child cannot use arbitrary ProxyCommand/identity/known-host bypass;
* signing child cannot sign an unbound arbitrary payload/action;
* credential socket/handle disappears after process-tree cleanup;
* no secret appears in argv/env/stdin/output/log/audit/SQLite;
* Git/SSH/GPG child remains inside Phase 7 process/resource/ptrace accounting;
* credential cleanup ambiguity retains operation/fence fail-closed.

37.5 Fault tests
~~~~~~~~~~~~~~~~

Inject crashes/lost receipts:

* after branch ref CAS before app receipt;
* after switch changes HEAD but before worktree/index completion;
* after commit object creation before signature verification;
* after signed commit creation before branch CAS;
* after branch CAS before app receipt;
* during fetch after pack transfer but before ref update;
* after fetch ref update before result receipt;
* between fetch and pull fast-forward;
* during worktree fast-forward integration;
* after push request is sent but before response;
* after hosted ref update but before local receipt;
* after application crash while Phase 7 supervisor owns Git process;
* after supervisor crash with ambiguous Git/SSH/GPG child effect;
* after audit failure/obligation publication around a Git effect.

Every fault has a truthful retained outcome and no blind automatic repeat.

38. Candidate-Pi and real-host evidence
--------------------------------------

Before operational promotion, run an explicit candidate-Pi evidence suite recording exact
Git/OpenSSH/GPG/system versions and selected profile behavior.

Verify at least:

* official Git executable identity/version and required machine-readable/plumbing switches;
* ``update-ref`` exact expected-old/nonexistence behavior and any transaction semantics used;
* ``commit-tree`` signing behavior and independent signature verification;
* operation-local index behavior;
* status/diff helper suppression;
* config-source isolation plus repository-local safety validation;
* fetch side-effect suppression used by the contract;
* exact SSH host-key/known-host/identity behavior;
* non-exportable SSH credential use;
* non-exportable signing capability use and signer fingerprint verification;
* Phase 7 distinct-UID/process-introspection/resource/FD isolation with Git/SSH/GPG children;
* Phase 6 root/mount/workspace coordination while Git modifies refs/index/worktree;
* real remote fetch/push exact-ref behavior against the registered Binnacle repository;
* response-loss/reconciliation procedure without deliberately corrupting the hosted repo;
* no raw credential disclosure.

Then run real ChatGPT through the Phase 8 exit sequence. Record only actual observed host
behavior. Unsupported Tool projection, confirmation/session semantics, credential mechanism,
or candidate Git behavior remains explicitly unsupported/blocked.

39. Holistic invariant pass before review/promotion
--------------------------------------------------

Before requesting review for this plan and again before implementation promotion, walk the
full chain for every operation:

``request / session / repository snapshot``
   -> caller-binding-first retained lookup/minimal received identity
   -> received audit
   -> policy + protected repository profile + repository-safety validation
   -> Phase6 GIT_READ or CHANGE/fence
   -> post-policy exact current-state/expected-self binding
   -> authorised audit
   -> Phase7 exact Git ticket + optional exact credential capability
   -> running/effect intent
   -> final controller/device/session/root/mount/repository/config/ref/index/worktree/remote/
      credential/network/audit OP-BOUNDARY
   -> audit obligation
   -> Phase7 single-use acceptance
   -> exact Git/SSH/GPG effect
   -> immediate process/effect evidence
   -> Git-specific ref/index/worktree/object/remote reconciliation
   -> post-effect audit/credential/process cleanup/fence release
   -> application/supervisor restart
   -> retained same-key reconciliation.

Walk at least:

* clean status/diff and output truncation;
* malicious repository config/helper/filter surfaces;
* concurrent branch creation;
* switch stale/dirty/conflict cases;
* commit signing failure/wrong signer/ref CAS race;
* fetched objects with failed local ref publication;
* pull divergence after successful fetch;
* push expected-remote mismatch;
* push response loss followed by remote equality and remote difference;
* repository/config/profile change after policy but before effect;
* development-session end before start and after remote effect start;
* application restart/supervisor crash;
* credential cleanup ambiguity;
* same-key retry after session end;
* no raw secret or authority escalation anywhere in results/output/audit.

If multiple review findings share a common repository-profile, credential, current-state,
or effect-reconciliation abstraction defect, fix the shared foundation rather than serially
patching individual Tools.

40. Plan acceptance and promotion checklist
-------------------------------------------

Plan acceptance requires:

* exactly this Phase 8 numbered document in the planning PR;
* governing source order/current merged Phase 4/6/7 references correct;
* official-Git/typed-adapter boundary explicit;
* no direct-subprocess or generic credential-bearing command fallback;
* repository-local config/helper surface treated as untrusted and fail-closed;
* exact Phase 6 workspace coordination and Phase 7 process semantics consumed;
* local branch/ref CAS, switch safety, signed commit, fetch/pull/push semantics concrete;
* separate SSH/signing authority and non-exportable credential contract explicit;
* effect knowledge/idempotency/restart/reconciliation walk complete;
* adversarial/fault/candidate-Pi/real-host evidence procedures concrete;
* no Raspberry Pi/ChatGPT/Git/credential support fact fabricated;
* exact-head CI and review green.

Implementation promotion additionally requires the empirical gates in section 3.2.

41. Implementation order
------------------------

Implement Phase 8 in this order after prerequisite exits are real:

#. define/review versioned Phase 8 operation contracts and schemas without exposing handlers;
#. define protected registered Git repository/remote/identity/signing profiles;
#. implement repository identity/snapshot and supported-shape validator;
#. implement repository config/attributes/helper-surface validator and safety digest;
#. implement typed closed Git execution-plan builder over Phase 7 supervisor;
#. implement read-only status/diff with strict bounds and helper suppression;
#. implement ref normalization/policy and branch-create expected-old/absence CAS;
#. implement switch stale/dirty/no-loss semantics and integration tests;
#. implement operation-local index/tree builder and signed commit creation/verification;
#. implement exact branch-ref CAS and commit reconciliation;
#. provision/integrate non-exportable repository SSH capability in protected deployment
   configuration and prove generic commands cannot reach it;
#. implement narrow fetch and fetched-effect reconciliation;
#. implement fast-forward-only pull composition;
#. implement exact protected-destination push + remote reconciliation;
#. wire Phase 4 operation/audit/idempotency, Phase 6 guard/fence, Phase 7 ticket/output/restart,
   and credential obligations end-to-end;
#. promote reviewed manifest entries only after contract/schema/handler parity passes;
#. run unit/property/integration/security/fault tests;
#. run candidate-Pi Git/SSH/GPG evidence suite;
#. run real ChatGPT Phase 8 exit workflow;
#. only then mark Phase 8 implementation exited and unblock operational Phase 9/10 use.

42. Provisional and deferred items
----------------------------------

The following remain evidence-gated or deferred rather than guessed:

* exact candidate-Pi Git/OpenSSH/GPG versions and optional switches;
* exact non-exportable SSH/signing mechanism/agent implementation;
* exact ChatGPT host-confirmation/session projection for Git credential effects;
* broader repository config/features beyond the conservative supported profile;
* LFS/submodules/custom filters/hooks/merge drivers/external diff/textconv;
* multiple repositories/remotes;
* tag/release workflows;
* history rewriting/rebase/merge/conflict automation;
* force push;
* libgit2/pygit2;
* GitHub PR/review/merge APIs inside Binnacle;
* hardware-backed signing keys;
* broad developer credential broker;
* performance tuning for large repositories/object transfers.

Missing evidence in these areas does not stop this evidence-independent plan from merging.
It blocks only the corresponding implementation/promotion claim.

43. Completion state
--------------------

When this numbered plan is accepted, set ``:Status: merged``. That means the Phase 8
**planning artifact** is authoritative. It does not mean the Git Tools, credentials, signed
commit path, remote effects, or real ChatGPT self-hosting workflow have been implemented or
validated.

Phase 8 implementation exits only when the real evidence procedure in section 38 passes.
