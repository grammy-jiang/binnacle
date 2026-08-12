Binnacle Phase 8 Detailed Implementation Plan
=============================================

:Phase: 8 -- Implement the minimal Git development workflow
:Status: merged
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
* every push profile proves an exact remote-old/nonexistence CAS at the hosted destination,
  including ordinary fast-forward and new-branch creation rather than relying on a
  non-atomic preflight;
* any stale, contradictory, unsupported, or unverifiable prerequisite keeps the affected
  Git Tool invisible/disabled rather than falling back to generic shell Git with ambient
  credentials.

3.3 Phase exit
~~~~~~~~~~~~~~

Phase exit additionally requires the empirical real-Pi/real-ChatGPT procedure in section
39. Automated tests and a locally signed synthetic commit do not establish the complete
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
* a general-purpose staging/index editor. Bootstrap ``git_commit`` owns one exact bounded
  commit selection and requires a clean main staging index before it starts;
* raw private-key, token, password, agent-cookie, or reusable credential disclosure;
* GitHub PR/review/Actions/merge implementation inside Binnacle;
* package/service/root administration;
* libgit2/pygit2;
* treating Git stdout/stderr as authoritative effect truth;
* blind retry of an uncertain fetch/push/ref/worktree/index effect;
* deriving protected remote destination or signing identity from untrusted repository
  files.

5. Process and authority topology
---------------------------------

The Phase 8 path composes the existing application/executor boundaries with a protected
credential boundary selected during implementation. A selected software broker is a
separate unprivileged service identity; a hardware-backed equivalent must prove the same
peer/action/audience isolation:

.. code-block:: text

   MCP / CLI adapter
      -> GitApplicationService
      -> Phase 4 operation/policy/audit kernel
      -> Phase 6 workspace access/change coordinator
      -> protected Git-metadata authority + repository validator
      -> GitOperationTicketBuilder
      -> Phase 7 execution supervisor
      -> dedicated internal semantic Git process profile
      -> official Git CLI
      -> optional exact operation-owned ssh/gpg child
      -> protected credential broker or equivalent non-exportable boundary

The application owns semantic admission, authoritative operation state, repository/profile
policy, exact target/effect binding, and effect reconciliation. The Phase 7 supervisor owns
process acceptance/lifecycle/output evidence. The Git/credential adapter maps only reviewed
semantic operations into fixed executable/argv/environment/file-descriptor/network plans.

A credential broker/agent may perform one exact SSH/signing action without exporting the
secret. It is **not** a generic shell endpoint, does not open application or executor
SQLite, and is not reachable by ordinary ``command_run``.

5.1 Protected Git-metadata authority is not Phase 6 content authority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 6 deliberately prevents model-visible workspace read/search/mutation from treating
``.git`` and other protected control/credential paths as ordinary source content. Phase 8
does not weaken that boundary.

Instead, the Phase 8 application and dedicated Git execution profile receive a separate,
internal semantic authority for the exact registered Git directory/common directory needed
to perform reviewed Git operations. That authority:

* is derived only from the protected ``RegisteredGitRepositoryProfile``;
* is never produced by a model-supplied path;
* is bound to the exact registered workspace/root/mount/Git-dir identity;
* permits only the metadata access required by the selected semantic Git operation;
* does not make raw ``.git`` file contents model-visible;
* does not make protected credential/config files ordinary repository content;
* is unavailable to generic ``command_run`` unless a separately reviewed command contract
  explicitly grants a safe non-credential Git operation;
* remains coordinated by the same Phase 6 ``WorkspaceAccessGate``/CHANGE seam.

``WorkspaceAccessGate`` coordinates Binnacle-managed readers/changers; it does not itself
grant Git-metadata or credential authority.

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
root/mount/no-submount boundary and the protected Git-metadata authority from section 5.1.

Bootstrap supports the normal single registered Binnacle development worktree first. A
repository shape is unsupported when exact identity or containment cannot be established,
including ambiguous external ``GIT_DIR`` indirection, unexpected linked-worktree/common-dir
layout, unsafe symlink/mount escape, or repository format/extensions not covered by the
reviewed profile.

A bounded ``GitRepositorySnapshot`` records enough current facts for admission and final
revalidation, including as applicable:

* HEAD symbolic/detached state;
* current branch ref and OID;
* exact selected index identity/digest/metadata and index-tree OID;
* unmerged-entry count;
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

7.1 Git object identity and repository-state binding
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Git object IDs are algorithm-tagged values, not Binnacle state digests:

.. code-block:: text

   GitObjectId {
       algorithm: sha1 | sha256
       hex: exact lowercase algorithm-sized hexadecimal value
   }

Bootstrap accepts only full object IDs in the registered repository's object format. It
does not hard-code forty hexadecimal characters, accept abbreviations, or accept revision
expressions where an object ID is required. Binnacle request, evidence, profile, and state
digests remain JCS + SHA-256 and use names ending in ``_sha256``; Git object IDs do not.

The inspector canonicalizes the snapshot into
``repository_state_binding_sha256``. That stale-state token covers the registered
repository/workspace/root/mount/common-directory identity; symbolic HEAD/detached state;
HEAD and relevant ref ``GitObjectId`` values; logical index/tree state; bounded worktree,
untracked, conflict, lock, and in-progress-operation facts; object format; remote/profile/
config/helper-surface digests; and capture provenance. It is request state, never authority,
and every consequential stage re-reads the exact facts it depends on before crossing.

Bootstrap binds one normal primary worktree/common-directory identity one-to-one with one
registered Phase 6 workspace. Linked worktrees, an external common directory, or reuse of
one common directory by another registered workspace are rejected. Therefore the existing
per-workspace gate and durable fence also serialize the supported common directory; Phase 8
does not invent a parallel durable Git lock. A future multiple-worktree profile must add a
reviewed common-directory coordinator before promotion.

8. Repository-local configuration is untrusted data
----------------------------------------------------

Skipping system/global Git config does **not** make repository-local configuration
trustworthy. Phase 8 therefore treats ``.git/config`` and worktree config as untrusted
repository inputs.

Before a Git capability is enabled for a repository snapshot,
``GitRepositoryProfileValidator`` performs a bounded, side-effect-free validation under the
appropriate Phase 6 access guard and protected internal Git-metadata authority. The
validation does not follow arbitrary config includes or execute any Git helper.

The supported Bootstrap repository profile rejects or explicitly neutralizes at least:

* ``include`` / ``includeIf``;
* ``credential.helper`` and related ambient credential selection;
* repository-selected remote destination for credential-bearing operations;
* ``url.*.insteadOf`` / ``pushInsteadOf``;
* ``core.sshCommand``;
* repository-selected ``gpg.program``, signing key, SSH variant, upload-pack, or
  receive-pack command;
* protocol/proxy/helper settings that can execute commands or redirect the protected
  destination;
* aliases, ``core.gitProxy``, ``core.alternateRefsCommand``, ``core.fsmonitor`` or an
  fsmonitor hook, and any ``submodule.*.update=!command`` form;
* ``diff.external`` and diff-driver textconv helpers;
* pager/editor/sequence-editor settings;
* repository-selected hooks path or executable hooks;
* clean/smudge/process filters;
* custom merge drivers;
* submodule recursion/config requiring helper execution;
* Git LFS/custom external extensions;
* unsupported alternates/object-store indirection that escapes the reviewed repository
  storage profile;
* replacement refs, grafts, shallow/partial-clone/promisor/sparse state, or lazy object
  fetching outside an explicitly reviewed repository profile;
* unexpected ``core.worktree``/Git-dir/common-dir indirection, repository-owned proxy/TLS/
  HTTP configuration, or protocol allowlist changes;
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
* exact registered worktree/Git-dir context through the protected internal authority;
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
* ``GIT_CONFIG_NOSYSTEM=1`` and no caller/repository-provided ``GIT_CONFIG_COUNT`` or
  ``GIT_CONFIG_KEY_*``/``GIT_CONFIG_VALUE_*``;
* closed ``HOME``/``XDG_CONFIG_HOME`` appropriate to the Git operation profile;
* ``LC_ALL=C`` and fixed protected ``GIT_EXEC_PATH``/helper search path;
* ``GIT_TERMINAL_PROMPT=0``;
* closed/disabled ``GIT_ASKPASS`` / ``SSH_ASKPASS`` unless a specific protected brokered
  mechanism requires an operation-owned helper;
* ``GIT_PAGER=cat`` / no interactive pager;
* no model-provided ``GIT_SSH_COMMAND``;
* ``GIT_NO_REPLACE_OBJECTS=1``, fixed discovery/ceiling boundaries, and
  ``GIT_PROTOCOL_FROM_USER=0`` where the reviewed Git version supports the required
  semantics;
* literal pathspec handling with no model-provided pathspec magic/revision expression;
* explicit protocol allowlist;
* command-scope configuration used only to neutralize/force reviewed behavior and itself
  included in the ticket digest;
* one exact command-scope ``safe.directory=<registered workspace root>`` exception for
  the dedicated Git execution identity, never ``safe.directory=*`` or a caller-selected
  path;
* a protected read-only empty hooks directory; ``--no-verify`` or a magic path alone is not
  a sufficient hook boundary.

Repository-local config is still validated separately because ordinary repository Git
commands may consume it despite system/global isolation.

No Git operation uses a shell command string. User/model data is passed as structured argv
or bounded stdin and cannot become config, executable path, helper command, or environment
name.

10. Phase 6 workspace coordination
----------------------------------

Phase 8 consumes the same ``WorkspaceAccessGate`` and durable workspace mutation fence as
Phases 6 and 7. Git does not create a bypass writer path.

Coordination paths are:

``CONTENT_READ`` plus ``GitReadPermit``
   Read-only Git inspection uses the **existing** Phase 6 shared ``CONTENT_READ`` mode; it
   does not add a ``GIT_READ`` enum/state or a second access coordinator. After acquiring
   that guard, Phase 8 acquires the exact development-session authority gate, revalidates
   repository/root/mount/profile/safety facts, and mints a request-bound
   ``GitReadPermit``. This permit is distinct from Phase 6 ``ContentReadPermit`` because it
   grants the typed Git adapter narrow protected Git-metadata inspection under the same
   shared guard.

``CHANGE``
   Any Git operation that may modify refs, index, worktree, Git metadata relevant to later
   security decisions, fetched object/ref state, or local checkout state. It acquires the
   exclusive Phase 6 CHANGE side and one durable mutation fence before consequential
   effect.

Bootstrap defaults conservatively:

* ``git_status`` and bounded ``git_diff`` use ``CONTENT_READ`` + ``GitReadPermit``;
* branch creation, switch, commit, fetch, pull, and push use ``CHANGE`` unless a later
  reviewed contract proves a narrower coordination mode without creating races.

The exact read ordering is:

.. code-block:: text

   authenticate/normalize
   -> WorkspaceAccessGate.CONTENT_READ
   -> DevelopmentSessionAuthorityGate
   -> repository/root/mount/profile/safety revalidation
   -> request-bound GitReadPermit
   -> discriminated read-only Phase7 GitReadExecutionTicket
   -> complete immutable result materialization
   -> process-tree quiescence
   -> release

The fixed consequential lock order is ``WorkspaceAccessGate -> Phase 4 per-operation
handoff -> DevelopmentSessionAuthorityGate -> ConsequentialBoundaryGate -> Phase 7
supervisor acceptance``. The applicable guard/fence remains held until process descendants,
Git lock files/temporary files, index/ref/worktree effect knowledge, credential-child
lifecycle, output/evidence, and audit obligations are truthfully closed. ``uncertain``
retains the fence. If the selected Git/profile cannot prove status/diff are helper-,
network-, credential-, and repository-write-free under an OS-read-only worktree/``.git``
view, those Tools use the full CHANGE/fence path or remain disabled.

The read ticket is an explicit Phase 8 extension to Phase 7, not a malformed command
ticket. It binds a server request/member identity, session/version, repository/root/mount/
profile, content-guard epoch and ``GitReadPermit`` digest; its schema requires
``operation_id=null`` and mutation-fence fields null. It is accepted only by the internal
read-only Git profile and cannot enter ``command_run`` or an effect adapter. The existing
consequential command ticket continues to require a non-null Phase 4 operation and Phase 6
fence; the two shapes are a closed discriminated union.

Read start is linearized under an executor ``GitReadAcceptanceGate`` after the guard/session/
permit sequence above. The supervisor durably records request/member/ticket identity and
accepted/no-accept/launch/terminal/process-tree evidence before returning, but this no-effect
record is not a fabricated Phase 4 operation. Every read connection/ticket also binds the
application runtime generation negotiated with the executor.

Application death closes the read member's input/control channel and the supervisor
terminates its exact domain, but channel closure alone is not no-accept proof for a queued
handler. On every application startup, ``GitReadRecoveryBarrier`` requests one executor-
wide ``close_and_drain_read_generation`` transition. Under the **same**
``GitReadAcceptanceGate`` used by registration/acceptance, the executor:

#. durably seals every earlier application generation against new acceptance;
#. makes every handler, including one received/queued but not yet registered, atomically
   observe that seal before it can insert/accept, and persist a matching no-accept tombstone;
#. waits for every handler reference in the closed generation to drain and every accepted
   domain/process/output resource to become terminal/quiescent;
#. persists and returns a generation/high-water/boot/evidence-bound quiescence receipt.

If acceptance wins before the seal, the barrier sees that accepted member and waits for
cleanup; if sealing wins, the delayed handler cannot launch. A newer application opens
CONTENT_READ/CHANGE only after validating that durable receipt. Missing/contradictory
generation evidence, executor restart ambiguity, an undrained queued handler, or unknown
cleanup keeps both modes ``RECOVERY_CLOSED``. This is the Git equivalent of Phase 6's
bounded search-child recovery lane, not a relaxation of consequential ticket validation.

The promoted repository profile also requires the accepted cooperative/local-writer model
needed by Phase 6. An uncoordinated external writer that can mutate the main index,
worktree, refs, config, attributes, hooks, or mount topology keeps affected Git mutations
unsupported unless a stronger reviewed confinement/CAS mechanism covers the exact surface.

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

11.1 Prepared credential/signing composition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Commit signing and every credential-bearing fetch/pull/push are high-risk compositions
under ``docs/security/capability-composition.md``. They require a short-lived no-effect
preparation before execution, even inside an already-authorised development session. The
contract review may promote one closed ``git_prepare`` Tool with an action discriminator or
separate per-action preparation names; an execute Tool is never promoted without one exact
preparation path.

Preparation binds controller/device/session, repository/workspace/root/mount/profile,
semantic action, exact change set or tree/parent/message and source/destination refs/OIDs,
protected normalized remote scheme/host/port/path and permitted effective-IP class,
known-host policy, credential/signing reference and broker action, information/resource
ceilings, policy/profile versions, expiry, and one execution nonce. It returns only the
prepared operation identity, nonce, expiry, and normalized digest. Preparation performs no
Git, signing, credential, DNS, network, ref, index, worktree, or object-store effect.

Execution must match every prepared field, consume the nonce at most once, and revalidate
current repository, remote, DNS/effective target, credential, policy, and session facts at
the final boundary. Caller-key and prepared-nonce identities converge on one retained Phase
4 operation; fresh keys cannot reuse consumed preparation or bypass uncertainty.

12. Common operation request identity
-------------------------------------

Every consequential Git operation request fingerprint includes at least:

* Tool/operation contract version;
* exact repository/workspace profile identity/version;
* controller/device identity/epoch;
* development-session identity/version where required;
* semantic action;
* exact protected branch/ref/remote target as applicable;
* exact ``repository_state_binding_sha256`` plus algorithm-tagged expected current OIDs or
  absence predicates;
* relevant index/worktree/config/attributes safety digests;
* exact commit path-selection/message/content/tree/parent digest as applicable;
* exact remote profile/refspec/expected-old/outbound-closure bindings for network effects;
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

The preferred adapter uses porcelain v2 with NUL-delimited paths and a closed argv, no
color/control-sequence interpretation, no pager, no hooks/helpers, and
``GIT_OPTIONAL_LOCKS=0``. Both the worktree and protected Git-metadata view are OS-read-only;
the environment disables external diff/textconv, filters, fsmonitor, maintenance,
credential/remote helpers, networking, and every credential endpoint.

The result is a normalized bounded projection, not raw unbounded porcelain text. It may
include:

* current branch/HEAD state;
* staged/unstaged/untracked/conflict state within configured item/byte ceilings;
* ignored, assume-unchanged, skip-worktree, sparse/index-extension, lock, and sequencer state
  needed to distinguish a complete snapshot from unsupported/hidden state;
* ahead/behind only when the exact local refs required for that computation are already
  available and no network effect is triggered;
* explicit truncation/incomplete flags that can never mean clean;
* repository/profile identity and snapshot digest.

Status never auto-fetches, refreshes credentials, writes an index, runs maintenance, or
executes repository helpers. If the selected Git version/repository shape cannot prove that
profile, the Tool uses ``CHANGE`` with the normal fence or remains disabled. A complete
collection is materialized while the guard is held and returned inline or through stable
retained item pages; later paging never re-reads the live repository.

14. ``git_diff``
----------------

``git_diff`` returns a bounded repository diff under ``CONTENT_READ`` plus a
``GitReadPermit``.

The contract requires an explicit diff mode, for example:

* worktree vs index;
* index vs exact HEAD;
* exact commit/tree A vs exact commit/tree B.

No arbitrary revision expression or pathspec magic is accepted when a closed full
``GitObjectId``/ref and literal bounded path set can be used. Output has file-count, hunk,
line, byte, binary-metadata, and timeout ceilings.

The adapter uses exact helper-suppression switches/configuration such as ``--no-ext-diff``
and disabled textconv where supported by the reviewed Git version. It does not invoke
pagers or repository helpers. Attributes/config that would require a custom driver/filter
cause the repository profile or requested diff mode to be rejected rather than executing
the helper. Rename/copy heuristics, color, and control-sequence interpretation are disabled
by default.

The complete semantic diff is materialized into an immutable retained result while the read
guard is held, then the process tree is proven quiescent before release. It follows the
common large-result byte-chunk/cursor contract. A prefix is explicitly incomplete and never
marked as a complete diff; ``operation_output`` contains only bounded sanitized process
diagnostics and is not the semantic diff result.

Diff content is untrusted/model-visible only under the normal repository-content information
policy; it is never authority for a later credential/system action.

15. ``git_branch_create``
------------------------

Branch creation is a consequential local-ref effect under ``CHANGE``.

Input binds:

* exact bounded ASCII-normalized new branch name within the allowed feature/fix namespace;
* exact full source commit ``GitObjectId``;
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
* expected main-index identity/tree/digest;
* expected worktree status digest;
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
ordinary checkout semantics without helper/hook execution. Before a tree-changing switch
it materializes and validates a bounded affected-path manifest and rejects symlink/gitlink/
submodule entries, protected names, path collisions, unsupported modes, unregistered
mounts, and out-of-profile paths. Publication is journaled and parent-directory durability
is verified; multi-file checkout is never described as atomic. Bootstrap may initially
promote only create-then-switch where target/current trees are equal. The exact broader Git
version/profile and materialization behavior must be proven on the candidate Pi.

A lost response after worktree/index mutation is not classified solely from current HEAD.
Index/worktree effect evidence and Git process receipt must be reconciled; ambiguous partial
checkout remains ``uncertain`` and retains the workspace fence.

17. ``git_commit`` selection and preconditions
----------------------------------------------

Commit is a high-value local Git mutation because it combines repository content, protected
identity, signing authority, object creation, main-index reconciliation, and branch-ref
update.

Bootstrap does not expose a separate staging Tool. The first ``git_commit`` contract
therefore uses an exact **commit selection** rather than inheriting arbitrary preexisting
staging state.

Before admission and again at final boundary:

* HEAD must be an allowed non-protected feature/fix branch with exact expected parent OID;
* the normal main index must contain no unmerged entries;
* the main index tree must equal the exact current HEAD tree -- preexisting staged changes
  cause ``git_index_not_clean`` rather than being silently committed or overwritten;
* the caller supplies an exact bounded set of repository-relative paths to commit, and each
  path is bound to the Phase 6 object/version/content/mode state or exact deletion predicate;
* every selected path must appear in the exact supported worktree delta and every selected
  untracked path must be explicit; no implicit ``git add -A`` or hidden discovery broadens
  the commit;
* unselected worktree changes may remain only when the supported repository/profile can
  prove they do not overlap the selected commit paths or main-index publication semantics;
* repository safety/config/attributes/profile/session/fence state is bound and current.

The exact normalized path selection and per-path action/content/mode digest are effect-
bearing request inputs.

17.1 Controlled commit construction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bootstrap prefers a controlled plumbing path rather than unrestricted ``git commit``
porcelain:

#. acquire ``CHANGE`` + durable workspace mutation fence;
#. persist the expected main-index identity/tree/digest, selected-path digest, exact parent,
   worktree snapshot, repository safety digest, protected author/committer profile, commit
   message digest, and signing profile;
#. create an operation-owned temporary index and, where supported, an operation-private
   quarantine object store initialized from the exact expected HEAD tree;
#. update that temporary index only for the exact selected path actions using reviewed Git
   plumbing that does not invoke repository clean/smudge/process filters, LFS, submodules,
   or hooks;
#. run ``write-tree`` and record the exact tree OID;
#. create the commit object with official ``commit-tree`` using the exact parent OID,
   bounded message input, protected author/committer environment, and exact signing
   capability;
#. independently verify the created commit object: tree, parent set, author/committer
   identity, message digest, signature presence/status, signer fingerprint, and object OID;
#. durably import the exact verified object closure from quarantine when applicable, then
   update the exact current feature branch using ``update-ref`` CAS from old parent OID to
   the verified new commit OID;
#. publish/reconcile the normal main index through the explicit state machine in section
   17.5; selected worktree files are not rewritten merely to make status look clean;
#. verify the exact intended post-state, including selected paths clean against new HEAD and
   allowed unselected worktree changes preserved;
#. close audit/credential/process/fence obligations only after truthful repository/index
   state is established.

No commit is created on protected ``master`` under the normal development profile.

17.2 Operation-local index
~~~~~~~~~~~~~~~~~~~~~~~~~~

The operation-owned temporary index path is protected and not model-controlled. It starts
from the exact expected parent tree rather than copying an arbitrary staged main index.

The tree builder consumes only the selected Phase 6-bound path state and modes. It must not
invoke repository-defined filters, LFS, submodule recursion, or helpers. If repository
semantics cannot be faithfully represented within this supported profile, ``git_commit`` is
disabled rather than invoking repository-selected executable behavior.

Temporary-index identity, tree OID, lifecycle, and cleanup obligation are retained as
operation evidence. Temporary-index/quarantine cleanup failure does not erase commit/ref
effects. Automatic GC/prune/reflog expiry is disabled while retained recovery objects may
be needed; unknown locks, pack temporaries, and objects are never heuristically removed.

17.3 Commit message and protected identity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Commit message is untrusted model input with explicit byte/encoding limits. It is passed as
bounded data, never as shell/config syntax.

Author and committer name/email come from the protected owner/device Git profile. The model
may not substitute an arbitrary identity in Bootstrap. Author/committer timestamps follow
the reviewed time policy and are recorded as effect-bearing facts when required for exact
reconciliation.

Exact author/committer timestamps are allocated once and durably bound before commit
creation. A same-key retry reuses them and never creates a second commit because wall time
advanced.

17.4 Signing
~~~~~~~~~~~~

The commit-signing identity is separate from repository transport SSH authority.

The signing request binds:

* exact operation/commit-preimage/tree/parent/message identity;
* exact signing key fingerprint/reference;
* signing algorithm/profile;
* controller/device/repository/session context;
* expiry/one-action authority;
* output/evidence limits.

After the exact tree OID and one-time timestamps are durable, the application derives and
persists the exact unsigned commit-preimage digest and issues one signing sub-capability for
that digest. Changed tree, parent, message, identity, timestamp, algorithm, or payload is
rejected rather than signed.

Raw private key material is never put in argv, environment, stdin, output, audit, SQLite,
or model-visible data. A protected operation-owned signing agent/socket/helper may be mapped
only into the exact Git signing process tree and removed when the operation ends.

After ``commit-tree -S`` or the exact reviewed official equivalent, Binnacle independently
verifies that the resulting commit has the expected signature and signer fingerprint before
allowing branch-ref CAS. Signing failure or wrong signer produces no branch-ref update.
There is no unsigned fallback. A retained signing response is reused for the same frozen
preimage; retry never requests a fresh nondeterministic signature that would create a
different commit object.

17.5 Branch CAS and main-index publication state machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The branch transition is ``expected_old_oid -> new_signed_commit_oid`` and uses an exact
expected-old ``update-ref`` CAS. CAS failure leaves the branch unchanged; the created commit
may remain unreachable and is recorded as a real object effect.

Main-index reconciliation is a separate **post-ref effect**, not an informal cleanup step.
Before branch CAS, the operation durably retains:

* ``expected_main_index_identity``;
* ``expected_main_index_tree_oid`` equal to the exact parent tree;
* ``expected_main_index_digest``/metadata needed to detect replacement;
* ``target_main_index_tree_oid`` equal to the verified new commit tree;
* exact selected-path/unselected-worktree snapshot digest;
* ``main_index_publication_state=PENDING``.

After branch CAS succeeds, publication uses a reviewed lockfile/atomic-replacement Git index
primitive. It must first re-prove that the main index still has the exact expected identity/
tree/digest and that the selected/unselected worktree snapshot remains compatible. It then
builds/fsyncs the exact target index representation and atomically publishes it, retaining an
exact publication receipt/digest before marking ``COMPLETE``.

The authoritative states are:

``NOT_REQUIRED``
   Branch CAS did not occur; main index remains governed by the original expectation.

``PENDING``
   Signed commit and branch CAS may have succeeded but main-index publication is not yet
   proven complete. The Phase 6 CHANGE/fence remains held.

``COMPLETE``
   Exact target index identity/tree/digest and compatible worktree post-state are proven.

``UNCERTAIN``
   Publication may have occurred but receipt/post-state cannot be proven, or external state
   changed so safe completion cannot be established. The fence remains held and no blind
   index overwrite is attempted.

Application restart replays the state machine, not a generic ``git reset``. If branch CAS
is proven and publication is still ``PENDING``, recovery may finish publication only after
re-proving the exact pre-publication main-index/worktree identity. If current index already
matches the exact target representation, retained publication evidence/current-state rules
may close it. If neither exact old nor exact target state is provable, remain ``UNCERTAIN``.
No recovery step overwrites an intervening index/worktree state merely because HEAD points
to the new commit.

Mandatory fault tests crash before target-index build, after build/fsync, immediately after
atomic publication, and before the ``COMPLETE`` receipt. They prove no intervening main
index/worktree state is overwritten and that the workspace fence cannot release while
publication is unresolved.

18. Repository SSH authority
----------------------------

Repository transport uses one protected device-specific SSH identity/reference for the
registered Binnacle repository, preferably repository-scoped where the hosting service
supports it.

The protected remote profile owns:

* exact transport scheme;
* host and port;
* strictly normalized repository path/identity and remote service user;
* permitted effective-IP class/ranges with loopback, link-local, private/control-plane,
  device-management, and rebinding pivots denied unless separately approved;
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
part of Bootstrap. The fixed wrapper uses an exact reviewed SSH executable/argv, protected
known-host file, no proxy or environment forwarding, and only the normalized upload-pack/
receive-pack repository command implied by the semantic action. Redirected schemes,
userinfo, fragments, arbitrary remote shell text, and repository-selected transport
commands are rejected.

19. Credential-broker composition
---------------------------------

Credential-bearing Git actions are explicit high-risk compositions:

.. code-block:: text

   untrusted repository state
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

The selected software implementation is a separate unprivileged credential identity/
process, distinct from application, supervisor, command, and Phase 9 broker identities. It
alone reads/uses the protected SSH/signing keys. Its control/state boundary is outside every
workspace and general command view; both peers validate exact local identity, protocol/
build, operation/member/ticket digest, action, audience, expiry, and generation.

An operation-owned wrapper/connected FD is visible only to the exact supervised Git member.
The broker binds a request to the prepared upload-pack/receive-pack action or commit
preimage and rejects arbitrary signing, remote shell, extra authentication sessions,
stale/replayed tickets, and another operation/domain. A generic long-lived agent socket
available to any same-UID process is unsupported. Signing and transport authorities are
never simultaneously visible: status/diff/branch/switch receive neither, commit gets only
signing with network denied, and fetch/pull/push get only repository transport authority.

Credential-use acceptance, completion, retained response, revocation/cleanup, and
uncertainty are durable. A broker/application/supervisor crash never causes automatic
reissue; ambiguity retains the audit obligation and workspace fence until exact
reconciliation or explicit recovery.

20. ``git_fetch``
-----------------

Fetch is a credential/network effect and also changes local object/ref metadata. Bootstrap
therefore uses ``CHANGE`` and the Phase 4 consequential path.

The request binds:

* protected remote profile;
* exact remote source ref(s), normally one branch;
* one operation-owned private destination ref required absent, plus any exact shared local
  destination ref/OID precondition to publish after verification;
* expected repository/config safety digest;
* credential capability;
* exact fetch-side-effect profile;
* object/pack/ref/output/time ceilings.

The adapter uses explicit repository URL/refspec from protected configuration. It never
uses default ``origin`` selection from mutable repo config.

The preferred narrow profile fetches one exact protected remote ref into an absent
operation-owned namespace such as ``refs/binnacle/fetch/<operation-id>``. It suppresses
``FETCH_HEAD``, implicit tags, maintenance, commit-graph, and other default effects when the
candidate Git version proves the required switches. Fetched object type/connectivity,
object-store containment, and pack/object ceilings are verified before any shared ref is
published. Shared publication is a separate ``update-ref`` expected-old/absence CAS; fetch
output or the earlier snapshot never substitutes for that CAS. The private ref is removed
only after its effect/evidence is durably classified, while downloaded objects remain
truthful local effects.

Fetch never writes the checked-out branch or force-updates a shared ref. If transfer cannot
be isolated in a private ref with the named ambient effects suppressed, the Tool remains
unsupported. Exact atomic multi-ref mode may be used only for a reviewed set; no stronger
reader atomicity is claimed beyond Git's documented guarantees.

No ``--all``, implicit tag sweep, pruning, submodule recursion, or arbitrary force fetch is
allowed in Bootstrap.

Downloaded objects/packfiles are a real local effect even when the intended ref update later
fails. Effect knowledge and retry semantics therefore distinguish object transfer from ref
publication. Response loss or process failure after network transfer may be ``known_effect``
or ``uncertain`` depending on retained Git/executor evidence; it is never blindly repeated
just because the target ref did not move.

21. ``git_pull``
-----------------

Bootstrap pull is **not** arbitrary ``git pull`` merge/rebase porcelain. It is a semantic
composition:

#. exact protected ``git_fetch`` under the reviewed narrow fetch profile;
#. verify the exact fetched target OID and expected local current branch OID;
#. prove fast-forward ancestry using a reviewed local Git query;
#. if fast-forward is not possible, return ``git_diverged`` with no automatic merge/rebase;
#. perform an explicit fast-forward-only local integration under the same continuously held
   CHANGE guard/durable fence and exact expected-old ref/worktree/index preconditions;
#. verify resulting ref/index/worktree state and close the operation truthfully.

The operation binds enough phase-stable evidence to distinguish expected self-owned
fetch/ref transitions from unrelated concurrent mutation.

No conflict resolution, auto-stash, merge commit, rebase, or reset occurs implicitly.

Before local integration, Phase 8 validates the complete bounded target-tree publication
manifest using the same protected-name, type/mode, symlink/gitlink, collision, root/mount,
and path rules as switch. It journals exact affected paths and publication progress. A
partial checkout remains recovery-closed and is never repaired with automatic
``reset --hard`` or ``clean``.

Because fetch and local integration are separate consequential boundaries, the operation
model records intermediate effect knowledge. A successful fetch followed by a stale local
integration is not ``known_no_effect``; downloaded objects/ref updates remain real effects.

Fast-forward local integration uses the same explicit index/worktree publication discipline
as switch/commit where applicable. A branch-ref move with unresolved index/worktree
publication remains partial/uncertain with the CHANGE/fence retained.

22. ``git_push``
-----------------

Push is the highest-value Phase 8 remote effect because it composes untrusted repository
state, protected SSH authority, network egress, and a hosted ref mutation.

Bootstrap push input binds:

* exact protected remote profile/destination;
* exact local source branch ref and commit OID;
* exact remote destination branch ref;
* exact expected remote old OID or exact nonexistence predicate;
* exact bounded outgoing reachable-object closure digest/count/bytes and information class;
* protected-branch policy;
* repository safety digest;
* credential capability/audience;
* maximum effect and response/evidence bounds.

Only an allowed feature/fix branch destination is accepted. Direct normal push to protected
``master`` is rejected.

22.1 Exact hosted-ref CAS is mandatory for every push
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The bound expected remote state is enforced atomically at the hosted ref update for
**every** Phase 8 push, not merely non-fast-forward replacement.

For the reviewed Git profile, the preferred mechanism is an explicit exact lease such as
``--force-with-lease=<destination-ref>:<expected-old-oid>``. For new branch creation the
explicit empty expected value is used only when the reviewed Git version proves that it
requires destination nonexistence. A bare lease, a lease without explicit expected value,
or an expectation derived from mutable local remote-tracking refs is forbidden.

Use of the exact lease is a CAS mechanism, not permission to rewrite history. Binnacle
separately proves branch policy before launch:

* for an existing ordinary feature branch, the expected remote old commit must be the exact
  bound value and the target local commit must satisfy the operation's reviewed
  fast-forward/ancestry policy unless an explicitly different future contract exists;
* for a new feature branch, expected remote state is exact nonexistence;
* protected branches remain rejected;
* no wildcard, tag side effect, delete, mirror, arbitrary push option, or generic force is
  accepted.

A non-atomic remote preflight is current-state evidence only. It never substitutes for the
exact lease/CAS at mutation time. If the selected Git/remote profile cannot provide the
required exact CAS semantics, ``git_push`` remains disabled.

The adapter supplies the protected explicit remote URL/refspec and closed SSH environment.
It also disables repository hook execution for push, using exact reviewed no-hook semantics
such as protected ``core.hooksPath`` plus ``--no-verify`` when the selected Git version
proves them. Repository config cannot select the destination, credential helper, SSH
command, proxy, protocol helper, or pre-push hook.

Push preparation enumerates and bounds every missing reachable object that may be sent,
not merely the tip diff. The prepared data boundary covers that full outbound closure and
rejects an unbounded, unavailable, or changed closure before credential use. Transport
resource ceilings and hosting policy must make the bound enforceable; otherwise push stays
unsupported.

22.2 Remote preflight
~~~~~~~~~~~~~~~~~~~~~

No-effect preparation binds the exact expected destination OID/absence and protected remote
constraints without DNS, authentication, or a remote query. After durable execution
admission, an initial bounded credentialed remote-observation member obtains the exact
current destination state and persists its network/credential-use evidence. A mismatch
blocks the push member. That observation remains non-atomic current-state evidence; the
exact lease/CAS decides any later race.

DNS/host/known-host/credential audience and exact destination are revalidated at final
boundary. A changed expected remote ref blocks the push at the hosted CAS even if it changes
after local preflight.

22.3 Push response loss and reconciliation
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
handoffs.

.. code-block:: text

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
     -> operation-specific Git ref/object/index/worktree/remote reconciliation
     -> post-effect audit / credential cleanup / process-tree cleanup / fence closure
     -> restart reconciliation
     -> retained same-key retry

Post-policy exact-self changes such as the operation-owned workspace fence, temporary index,
expected ref CAS inputs, exact-hosted-ref lease, or fetched exact self-owned refs are
represented phase-stably in the final verifier. The final boundary does not reject the
operation merely because it sees an expected self-owned transition, and it does not
reconstruct integrity solely from mutable surviving Git state.

24. Phase 7 supervisor integration
----------------------------------

Phase 8 does not bypass or weaken Phase 7. It extends the supervisor protocol/evidence store
with two closed internal ticket shapes:

``GitReadExecutionTicket``
   The no-effect read shape from section 10, bound to ``GitReadPermit`` and no Phase 4
   operation/fence.

``GitOperationMemberTicket``
   One fixed consequential stage under an already-durable Phase 8 parent operation and
   existing Phase 6 fence.

Common ticket fields bind:

* exact read request/member identity or parent operation/member identity;
* repository/controller/device/session identity;
* semantic Git action;
* Git executable identity/version profile;
* exact argv/stdin/environment/FD digests;
* workspace/root/mount/Git-dir identity and protected Git-metadata authority;
* repository safety digest;
* ref/index/worktree/remote expectation digests;
* network profile;
* process isolation/resource/output limits;
* optional exact credential/signing capability references;
* expiry/single-use nonce.

The supervisor independently validates the ticket/profile mapping it is responsible for and
retains Phase 7 start/cancel/output/restart evidence. Both profiles are
``command_run_visible=false``. Phase 8 never invokes public/general ``command_run`` because
that would create a second Phase 4 operation and reacquire CHANGE/fence while the parent
owns them. One ticket cannot launch twice.

A consequential parent may have a bounded ordered stage graph. Each member identity is
derived from ``parent operation_id + Phase 8 contract/stage + monotonic stage generation``
and persisted before dispatch with its exact argv/environment/credential capability,
crossing/receipt/effect fields. The preferred derivation is a Phase 7 member identity, not a
new Phase 4 ``create_or_find`` call. Any use of Phase 4 ``derived_member_key`` requires an
explicit registered parent derivation and still cannot create a second operation/fence.
Wrong-parent/stage/generation and caller-supplied member identities fail closed.

The parent owns exactly one Phase 4 operation and one Phase 6 fence, permits at most one
active member, and binds every member to one supervisor acceptance home. It retains the
CHANGE/fence across the graph. Before each consequential member it re-enters the parent's
Phase 4 dispatch handoff, session gate, and process-wide boundary in fixed order and
revalidates exact repository/root/mount/fence/profile/credential/destination facts. Session
or policy loss blocks later stages without erasing earlier effects. Lost/uncertain member
evidence blocks dependent stages and is never rerun merely because the parent is unfinished.

Phase 7 protocol/schema/store APIs therefore gain exact member addressing:

* ``start_member(ticket)`` returns the discriminated accepted/no-accept receipt for one
  member;
* ``get_member(parent_or_read_request_id, member_id)`` addresses one execution;
* ``read_member_output(member_id, stream, offset, evidence_generation)`` returns only that
  member's retained bytes and stable cursor;
* ``cancel_member(parent_operation_id, member_id, cancellation_generation)`` targets the
  one active member while cancellation remains authoritative on the parent.

Application ``operation_get`` aggregates durable Phase 8 stages plus exact member evidence.
``operation_output`` uses an opaque cursor containing parent, member generation, stream,
offset, and executor evidence generation; it never ambiguously queries by parent operation
alone. Member outputs remain stable in stage order. Read-only status/diff return their
immutable semantic result directly and do not use parent-operation output APIs.

Parent aggregate effect is ``known_no_effect`` only when every declared member is proven
not crossed; proven effects aggregate to ``known_effect``/``partial`` according to the
operation contract; any unresolved crossing/outcome makes the parent ``uncertain`` and
retains the fence.

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
   Commit-object creation, branch CAS, and main-index publication are separate effect facts.
   A verified signed commit object with failed branch CAS is a known object effect with no
   branch-ref effect. Branch CAS success with ``main_index_publication_state=PENDING`` is a
   real branch effect with incomplete local publication and the fence retained. Ambiguous
   index publication or branch CAS remains uncertain according to the exact receipt.

``git_fetch``
   Pack/object transfer and local ref publication are separate effect facts. Failed ref
   update does not erase downloaded-object effect.

``git_pull``
   Fetch effect, local ref move, and index/worktree publication are separate facts. Failure
   or staleness in a later stage does not rewrite an earlier real effect to no-effect.

``git_push``
   Remote ref mutation is an independent external effect. Exact lease rejection proves that
   requested hosted ref CAS did not occur; ambiguous network/response outcome remains
   uncertain until reconciled by trustworthy remote evidence.

26. Idempotency and retained retry
----------------------------------

A Phase 8 retry with the same idempotency identity never blindly repeats Git.

Retained reconciliation first examines:

* authoritative Phase 4 operation state/effect knowledge;
* Phase 7 executor ticket/acceptance/process evidence;
* exact Git operation evidence;
* ref/index/worktree/object evidence and main-index publication state;
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
#. run the gate-serialized ``close_and_drain_read_generation`` barrier and keep both
   workspace modes closed until queued handlers are sealed/drained and every accepted prior
   read member/process/output resource is proven quiescent by a durable receipt;
#. reconcile Phase 7 supervisor accepted/running/terminal Git execution evidence;
#. restore exact Phase 8 Git operation facts, temporary-index/main-index-publication/
   credential obligations, and repository-profile binding;
#. query current repository state only as an observation, never as sole effect truth;
#. reconcile ref/index/worktree/object/remote evidence according to the operation type;
#. finish a ``PENDING`` main-index publication only after exact old/target index and worktree
   preconditions prove the repair cannot overwrite intervening state;
#. retain CHANGE/fence when any Git process, credential child, lock/temp, partial worktree,
   index publication, remote effect, or audit obligation remains ambiguous;
#. expose retained operation status/output/result only after the resulting state is
   schema-valid and ownership-scoped.

An application restart must not cause a new Git process or credential use for an already
accepted retained logical operation unless the exact reconciliation contract explicitly
allows a no-effect reissue and Phase 4 idempotency proves it safe.

27.1 Recovery, cleanup, and rollback truth
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Startup keeps Git mutation admission ``RECOVERY_CLOSED`` until root/Git-directory/mount/
profile identity, the existing Phase 6 fence, all retained members/helpers/credential
endpoints, exact refs/objects/index/worktree, operation-owned temp/quarantine state, remote
evidence, and audit obligations reconcile. Current Git state corroborates durable history;
it does not replace an absent crossing/receipt.

Cleanup removes only exact operation-owned temporary state whose identity/preimage and dead
owner are proven. It never guesses that ``index.lock``, ref locks, pack temporaries,
sequencer state, or dangling objects are stale. Automatic ``reset --hard``, ``clean``,
force checkout, GC/prune, reflog expiry, or remote push reversal is forbidden. A local ref
rollback, if ever supported, is a predefined expected-current CAS or a new explicit
operation. Tree-path restoration is allowed only for exact recorded partial publication
whose current value still matches the operation's own write; otherwise preserve and provide
bounded owner guidance.

Changing the checkout does not change the running service build. Runtime/status evidence
records ``running_build_sha`` separately from ``checkout_head``; Phase 8 neither restarts
the service nor claims the running process adopted the new tree. Mixed-revision risk for an
editable/lazy-import runtime is a deployment test and controlled restart is deferred to the
Phase 9 administration path.

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

.. code-block:: text

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

Session end before a Git effect starts blocks a new start through the Phase 6/7 authority
linearization. Session end after a remote/local Git effect has started never rewrites effect
truth; it blocks new starts and the retained operation must reconcile/clean up under its
already-admitted authority without manufacturing a second effect.

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
#. define no-effect preparation plus the closed read-ticket/consequential-member ticket,
   member output/cancel cursor, and broker-use schemas;
#. define Git metadata, main-index publication, and remote-CAS result/evidence variants;
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
* ``git_index_not_clean``;
* ``git_index_stale``;
* ``git_index_publication_uncertain``;
* ``git_conflict_state``;
* ``git_helper_surface_unsupported``;
* ``git_signing_unavailable``;
* ``git_signing_failed``;
* ``git_signer_mismatch``;
* ``git_credential_profile_unavailable``;
* ``git_remote_destination_mismatch``;
* ``git_remote_ref_stale``;
* ``git_remote_cas_rejected``;
* ``git_diverged``;
* ``git_fetch_partial``;
* ``git_push_uncertain``;
* ``git_process_uncertain``;
* ``git_output_truncated``;
* normal Phase 4/6/7 authentication/policy/session/audit/fence/ticket/recovery errors.

Diagnostics may expose safe public Git/version/profile/ref/OID/fingerprint facts and bounded
reason codes. They never expose private key material, credential-agent protocol secrets,
unredacted protected config, raw ``.git`` file content, or arbitrary helper command content.

32.1 Result projection and cancellation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 8 reuses Phase 7 ``operation_get``, ``operation_output``, ``operation_cancel``, and
``operation_list`` for consequential parent operations; section 24's member-addressed
extension removes parent/execution ambiguity. It adds no Git-specific status/cancel/list
Tools. Every consequential Git Tool returns the parent ``operation_id`` and canonical
retained snapshot. ``operation_get`` projects semantic stage and safe evidence;
``operation_output`` projects only sanitized bounded member diagnostics. Semantic diff data
uses the immutable retained result contract instead.

Cancellation acts on the parent and is safe only at declared stage boundaries:

* branch/switch/ref CAS cannot be interrupted inside an atomic ref update and completes
  post-crossing reconciliation;
* commit may stop between closed members, never by regenerating/discarding a retained
  signature/object/ref effect;
* fetch/push cancellation terminates the exact active member while possible network/object/
  remote effects remain classified independently;
* pull cancellation after fetch preserves that partial effect and blocks integration;
* natural completion may win, and cancellation acknowledgement alone never means
  ``cancelled``.

Cancellation never creates another Git operation/member generation. Fence release waits
for member/process/credential/output/Git/audit/aggregate-effect closure.

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
       async def publish_main_index(self, plan: MainIndexPublicationPlan) -> MainIndexPublicationResult: ...
       async def fetch(self, plan: GitFetchPlan) -> GitFetchResult: ...
       async def fast_forward(self, plan: GitFastForwardPlan) -> GitEffectResult: ...
       async def push(self, plan: GitPushPlan) -> GitPushResult: ...

   class GitCredentialCapabilityBroker(Protocol):
       async def prepare_repository_ssh(self, request: GitSshCapabilityRequest) -> OpaqueCapability: ...
       async def prepare_commit_signing(self, request: GitSigningCapabilityRequest) -> OpaqueCapability: ...

   class GitExecutionMemberDispatcher(Protocol):
       async def dispatch(self, member: GitExecutionMember) -> ExecutionStartReceipt: ...

   class GitReadRecoveryBarrier(Protocol):
       async def close_and_drain(
           self, previous_generation: int, new_generation: int
       ) -> GitReadRecoveryResult: ...

   class GitCredentialEvidenceStore(Protocol):
       async def accept_once(self, request: CredentialUseRequest) -> CredentialUseReceipt: ...
       async def reconcile(self, ticket_digest: str) -> CredentialUseReceipt: ...

   class GitEffectReconciler(Protocol):
       async def reconcile(self, operation: OperationSnapshot) -> GitReconciliationResult: ...

The implementation keeps Git command construction, protected metadata access, repository
safety validation, credential capability mapping, process execution, remote evidence
reading, index publication, and operation orchestration behind separate typed seams.

34. Repository layout and implementation seams
----------------------------------------------

A likely implementation file set is:

.. code-block:: text

   src/binnacle/domain/git.py
   src/binnacle/ports/git.py
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
       index.py
       fetch.py
       push.py
   src/binnacle/adapters/credentials/
       protocol.py
       git_ssh.py
       git_signing.py
   src/binnacle/adapters/sqlite/git.py
   src/binnacle/credential_broker/
       service.py
       protocol.py
       state.py
       sqlite.py
   migrations/versions/0005_git_operations.py
   migrations_executor/versions/0002_git_members.py
   migrations_git_credential/env.py
   migrations_git_credential/versions/0001_credential_evidence.py
   spec/operation/git-operations.yaml
   spec/policy/git-profiles.yaml
   spec/mcp/bootstrap-tool-manifest.yaml
   schemas/mcp/bootstrap-inputs.schema.json
   schemas/mcp/bootstrap-outputs.schema.json
   spec/mcp/evaluation-cases.yaml
   src/binnacle/_generated/compatibility_core_registry.json
   src/binnacle/_generated/compatibility_core_registry.digest.json
   deploy/systemd/binnacle-dev.service
   deploy/systemd/binnacle-executor.service
   deploy/systemd/binnacle-git-credential.service
   deploy/systemd/binnacle-git-credential.socket
   deploy/tmpfiles.d/binnacle-git-credential.conf
   scripts/setup_dev_pi.py
   scripts/verify_dev_pi.py
   scripts/verify_git_profile.py
   docs/security/git-development.md
   docs/operations/development-pi.rst
   .github/workflows/python.yml
   pyproject.toml
   uv.lock
   tests/unit/git/
   tests/integration/git/
   tests/security/git/

The exact credential service assets apply to the selected software broker; a hardware-backed
alternative names and tests equivalent concrete assets. ``pyproject.toml``/``uv.lock``
change only for a genuine selected dependency. Do not create empty layers merely to match
this sketch. Reuse Phase 4/6/7 ports where they already provide the required seam, and
extend the canonical manifest/schema/evaluation sources above rather than inventing a
parallel ``spec/mcp/manifest.yaml`` or per-Tool schema tree.

35. Protected configuration and persistence
-------------------------------------------

Protected repository/credential profiles live outside the source workspace in the normal
Binnacle protected configuration/state areas. They are versioned, digest-bound, owner-
governed, and not mutable through Git/workspace operations.

35.1 Application and executor persistence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Application migration ``0005_git_operations.py`` follows Phase 7
``0004_execution_operations.py``. Runtime requires the exact expected head and never
creates/upgrades schema opportunistically. It adds authoritative tables equivalent to:

``git_operations``
   One-to-one with the Phase 4 operation. It binds operation kind, repository/workspace/
   session/profile/safety digests, expected ``repository_state_binding_sha256``, source/
   destination refs and typed OIDs, commit/remote request digests, current semantic stage,
   aggregate effect knowledge, credential reference digests, and existing Phase 6 fence.

``git_operation_stages``
   Parent operation plus monotonic stage generation, deterministic member/ticket identity,
   stage/input/pre-state digest, a frozen consequential-versus-verification effect role,
   supervisor acceptance/execution, crossing/effect knowledge, before/after typed OIDs,
   cancellation generation, cleanup, and reconciliation. Only consequential stages
   contribute to the parent aggregate. Checks allow at most one active member and reject a
   dependent stage before predecessor closure.

``git_commit_evidence``
   Typed commit/tree/parent OIDs, author/committer/message/preimage digests, one-time
   timestamps, signer/profile and signature verification, object import, branch CAS, exact
   main-index publication, and worktree evidence.

``git_remote_evidence``
   Remote-profile/destination/outbound-closure digests, refs, expected/observed typed OIDs,
   transport acceptance/send/reconciliation and exact retained response evidence, plus safe
   credential-use evidence. A conclusive hosted-CAS rejection records the truthfully observed
   changed or absent remote state rather than requiring it to equal the stale expectation.

Constraints reject contradictory receipt/effect shapes, commit success without verified
signature/object/ref/index closure, push success without exact remote evidence, or terminal
parent with unresolved member/audit/fence. Retained diff/status data uses existing bounded
payload/result facilities. Raw keys, agent paths, full diffs/messages, config, and stderr do
not enter application SQLite.

Executor migration ``0002_git_members.py`` is required, not conditional. It adds the closed
read-vs-consequential ticket discriminator, parent/read-request plus member identity,
application runtime generation/seal/high-water/quiescence receipt, read no-accept
tombstones, member-specific acceptance/launch/cancel/output/terminal evidence, and
uniqueness needed by sections 10/24. The executor never opens application SQLite, and the
application never infers a member by querying only ``operation_id``.

35.2 Broker persistence and runtime ownership
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Software-broker migration
``migrations_git_credential/versions/0001_credential_evidence.py`` targets only the broker
DB. It records protocol/schema/generation metadata plus one row/tombstone per
credential-use ticket: exact operation/member/action/audience/credential generation,
preimage or destination digest, expiry, consume generation, ``REGISTERED|ACCEPTED|COMPLETED|
UNCERTAIN|REVOKED`` state, retained response/evidence digest, cleanup, and timestamps. One
serialized ``accept_once`` transaction consumes a matching ticket or returns its retained
response; conflicting/replayed input fails closed. Signing retains the exact private
response needed to return the same signature after response loss. Ambiguous SSH use is not
reissued and remains ``UNCERTAIN`` for Git/remote reconciliation. Neither broker nor
executor opens the other's or application DB.

Use a dedicated non-root ``binnacle-git-credential`` identity/private group, distinct from
application, supervisor, and command identities. Avoid the app-owned ``/run/binnacle``
parent. Root tmpfiles creates ``/run/binnacle-git-credential`` as broker-owned, client-group
traversable but non-writable (for example 0710) under root-owned ``/run``; its socket is
broker-owned and connectable only by the exact executor client group. The application and
generic command identity are not clients. The supervisor obtains an approved connected FD
and maps it only into the exact Git member. Private broker state lives under a separate
``/var/lib/binnacle-git-credential`` tree and key/config material under a separate protected
``/etc/binnacle-git-credential`` tree; existing app runtime/maintenance-lock ownership is
unchanged.

Both sides verify Linux peer credentials plus protocol/build/ticket/action/audience. The
broker service uses no new privileges/capabilities, strict filesystem/device isolation, no
workspace/app/executor state, and action-exact network policy; signing is network-denied.
Setup and the read-only verifier check fresh/upgrade ownership, exact socket parent/mode,
effective unit/drop-ins, keys/known-host public fingerprints, broker DB head/integrity, and
generic-command denial without printing secrets.

Offline upgrade order is fixed: stop app/new admission, drain or conservatively retain Git
operations, stop executor and credential socket/service, acquire each service's runtime
migration lock, migrate application as ``binnacle``, executor as its identity, and broker as
``binnacle-git-credential``, verify all heads/ownership/integrity, then start broker socket/
service, executor, and application. Failure leaves dependent services stopped and retained
uncertainty intact. Credential rotation/revocation advances generation and never silently
reissues an accepted ticket.

36. Security invariants
-----------------------

The implementation must preserve at least:

#. Repository content/config/output is untrusted data, never credential or policy authority.
#. Git executes only through the Phase 7 supervisor; no MCP-process direct-subprocess
   fallback exists.
#. Phase 8's internal Git-metadata authority does not make raw protected ``.git`` content a
   model-visible Phase 6 capability.
#. General ``command_run`` receives no raw Git SSH/signing secret or ambient dedicated agent.
#. A consequential Phase 8 parent owns one Phase 4 operation and one Phase 6 fence; internal
   members never re-enter ``command_run`` or create/reacquire either one.
#. Repository SSH and commit-signing authority are separate exact capabilities.
#. At most one exact credential authority is visible to a stage; signing and transport are
   never simultaneously mapped.
#. Protected remote destination/ref policy is not chosen by mutable repository config.
#. Credential-bearing operations revalidate repository safety digest, destination, audience,
   action, controller/device/session/profile, and credential identity immediately before
   effect.
#. Repository-local includes/helpers/hooks/filters/textconv/external diff/submodule/LFS or
   other unsupported executable surfaces cause fail-closed behavior.
#. Status/diff cannot execute helpers or trigger network/credential/repository-write
   effects, and a complete result never rereads live state after guard release.
#. The discriminated Git-read supervisor lane is bound to ``GitReadPermit`` and startup
   gate-serializes prior-generation close/drain against queued acceptance and proves every
   handler/reader quiescent before either workspace mode opens.
#. Git object IDs are full algorithm-tagged values and are never conflated with Binnacle
   JCS/SHA-256 state digests.
#. Branch creation cannot overwrite an existing ref.
#. Switch never implicitly discards/stashes/resets user work.
#. Bootstrap commit never consumes or overwrites preexisting staged main-index changes.
#. A branch ref is updated to a new commit only after exact signed-commit verification.
#. Branch CAS and main-index publication are separate durable effect facts; unresolved index
   publication retains the workspace fence and never triggers a blind reset/overwrite.
#. Protected ``master`` is not a normal direct development/push target.
#. Fetch default side effects are narrowed to the reviewed effect contract.
#. Pull is fetch + verified fast-forward-only integration, never automatic merge/rebase.
#. Every push enforces the bound expected remote old OID/nonexistence atomically at the
   hosted ref update and binds the full bounded outgoing object closure; non-atomic preflight
   is never accepted as the CAS.
#. Exact remote lease use does not waive fast-forward/protected-branch policy.
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
* algorithm-tagged SHA-1/SHA-256 full OID validation and strict OID/state-digest separation;
* repository snapshot/current-state canonicalization;
* repository-safety digest determinism;
* protected Git-metadata authority never becoming content authority;
* config/helper-surface rejection matrix;
* operation request fingerprints/idempotency conflicts;
* read-vs-consequential ticket discriminator and permit/fence cross-field rejection;
* deterministic parent/stage/generation member derivation and wrong-parent rejection;
* branch-create absence/old-OID CAS mapping;
* switch stale/dirty/conflict rejection;
* commit exact path selection and preexisting staged-index rejection;
* commit tree/parent/message/identity/signature/ref-CAS state machine;
* main-index publication PENDING/COMPLETE/UNCERTAIN invariants and recovery preconditions;
* fetch object/ref intermediate effects;
* pull fast-forward/divergence/publication state machine;
* push exact remote-old/nonexistence CAS mapping for ordinary existing/new branches;
* push expected-remote-state/effect reconciliation;
* output/truncation/error parser bounds;
* credential capability audience/action binding;
* exact Phase 4 effect-knowledge cross-field validity;
* same-key retry never emits a second effect from uncertainty.

37.2 Integration tests with real Git CLI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use temporary local repositories and exact Git versions in CI where available. Cover:

* clean/dirty/conflicted/untracked status;
* status/index byte-for-byte non-mutation under OS-read-only worktree/``.git``;
* bounded retained diff with binary/large content and no live re-read across cursor pages;
* SHA-1 and, where installed Git supports it, SHA-256 repositories;
* branch create CAS and concurrent creator;
* switch with stale index/worktree and no implicit data loss;
* commit rejects preexisting staged changes;
* operation-local index initialized from exact HEAD and exact selected-path tree creation;
* signed commit using a test-only signing identity, verification, wrong-signer and signing
  failure;
* ref CAS race after commit object creation;
* branch CAS followed by main-index publication and selected/unselected worktree status;
* crash at every main-index publication boundary and exact safe recovery/no-overwrite;
* fetch explicit refspec with default ``FETCH_HEAD``/maintenance/commit-graph side effects
  suppressed according to the selected profile;
* pull fast-forward and divergence rejection;
* push to a local controlled SSH/bare-repository fixture with explicit expected-old lease;
* concurrent remote advancement between preflight and push is rejected by hosted CAS;
* concurrent new-branch creation after absence preflight is rejected by hosted CAS;
* lost/ambiguous push response and independent remote-ref reconciliation;
* application restart with Phase 7 executor evidence;
* supervisor crash around Git/SSH/GPG process start/exit;
* application restart with an accepted Git reader and ``GitReadRecoveryBarrier`` closure;
* Phase 6 CHANGE/fence concurrency with workspace edits/commands.

37.3 Adversarial repository tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Construct repositories containing hostile:

* local/worktree ``include``/``includeIf``;
* ``credential.helper`` including shell snippets;
* URL rewrite and unexpected remote config;
* ``core.sshCommand``;
* proxy/protocol helper settings;
* hooks/hook-path overrides including ``pre-push`` and checkout-related hooks;
* ``.gitattributes`` filter/textconv/external-diff surfaces;
* LFS/submodule configuration;
* fake pager/editor/merge driver;
* fsmonitor, shallow/partial/promisor/sparse/replace/graft state, linked worktree, and
  alternate-object-store indirection;
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
* immediately after branch CAS before main-index publication;
* during target main-index build/fsync;
* immediately after atomic main-index publication before durable completion receipt;
* during fetch after pack transfer but before ref update;
* after fetch ref update before result receipt;
* between fetch and pull fast-forward;
* during worktree/index fast-forward integration;
* after push request is sent but before response;
* after hosted ref update but before local receipt;
* after application crash while Phase 7 supervisor owns Git process;
* after supervisor crash with ambiguous Git/SSH/GPG child effect;
* after audit failure/obligation publication around a Git effect.

Every fault has a truthful retained outcome and no blind automatic repeat.

37.6 Race, migration, deployment, and evaluation tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cover status/diff against every Phase 6/7/8 mutation; two operations for one ref/parent;
session end, audit trip, root/mount/Git-directory replacement, remote advance, and cancel at
every member boundary; parent/member persistence before dispatch; exactly one active member;
member-specific output/cancel addressing; app/supervisor/broker restart; object/pack/output/
quota/ENOSPC/unknown-lock behavior; and no automatic reset/clean/gc/prune.

The mandatory read-generation race delays an old application's handler after frame receipt
but before registration/acceptance while new startup closes/drains that generation. Both
linearizations are tested: accept-first makes the barrier wait for terminal cleanup;
seal-first creates durable no-accept and the delayed handler can never launch. An empty
pre-barrier member scan is never sufficient evidence.

Migration tests cover application ``0005``, mandatory executor ``0002``, and broker
``0001`` from empty/current/prior head with FK/check/unique/index/integrity and strict DB
ownership isolation. Deployment tests cover fresh/upgrade tmpfiles and unit ownership,
separate runtime parents, peer/DAC denial, effective drop-ins, protected keys/config, broker
restart/retained signing response, offline migration order, and generic-command denial.

CI retains Python 3.11/3.12/3.13, frozen sync, Ruff/format, strict MyPy, Import Linter,
coverage, pip-audit, RST, canonical contracts/schemas/registry, manifest parity, all three
migration environments, and pre-commit. It records Git version and uses temporary repos,
local bare remotes, and ephemeral signing material; it does not claim Pi/systemd/UID/quota/
GitHub/ChatGPT evidence.

Add frozen cases to ``spec/mcp/evaluation-cases.yaml`` with exact risk classes:

* status/diff selection/rendering/paging use ``tool_selection_and_result_rendering`` with
  minimum 10 attempts;
* confirmation/entitlement-only cases use ``confirmation_and_entitlement`` with minimum 5;
* **every** branch/switch/commit/fetch/pull/push write, cancellation, retry, and cache/
  confirmation case uses ``write_cancellation_retry_cache_confirmation`` with minimum 20;
* remote races, reconnect, response loss, and instability use
  ``concurrency_race_reconnect_instability`` with minimum 20.

Cases cover branch response loss; dirty/collision switch refusal; exact tree/parent/signer;
signing failure and ref/index crash windows; exact private-ref fetch; fast-forward/divergent
pull; exact feature push and protected/force/delete/tag denial; outbound closure; remote
race/response loss/reconciliation; credential non-disclosure; reconnect; cancellation; and
uncertainty. Evidence binds exact repository snapshots/profile/build/Git digests, Phase 4
operation/audit, Phase 6 fence, Phase 7 member receipts, broker evidence, signature, remote
ref, and detached evaluation receipt. Missing Pi/ChatGPT attempts remain blocked without
stopping repository-only implementation work.

38. Review-correction invariants
--------------------------------

The first exact-head review established two foundation requirements that are part of the
plan, not local exceptions:

#. **Main-index publication is durable effect state.** Branch CAS cannot be treated as
   complete commit cleanup while the normal index is stale. Exact old/target index identity,
   publication state, receipt, restart repair predicates, and fault tests are mandatory.
#. **Every hosted push is an exact remote CAS.** The expected remote old OID/nonexistence
   predicate is enforced atomically at the hosted update even for normal fast-forward/new-
   branch pushes. Preflight is evidence, never the mutation precondition.
#. **Git readers have a lawful supervisor lane.** ``CONTENT_READ`` mints a
   ``GitReadPermit`` and a discriminated no-effect read ticket; it never fabricates the
   operation/fence fields required by consequential Phase 7 tickets. Startup seals/drains
   every prior application generation under the acceptance gate so even queued pre-accept
   handlers cannot launch after recovery reports quiescence.
#. **Compound Git work is one parent with addressed members.** Internal stages cannot call
   ``command_run`` or create another Phase 4 operation/fence; output/cancel/restart evidence
   always names the exact member.
#. **Credential use is durable and separately owned.** Broker acceptance/retained response/
   uncertainty survives restart in its own store/runtime tree, and transport/signing
   capabilities are never simultaneously visible.
#. **Object and result identity is exact.** Algorithm-tagged Git OIDs remain distinct from
   Binnacle SHA-256 state digests; complete status/diff results are immutable; fetch uses a
   private ref; push preparation binds the full outbound reachable-object closure.

These requirements must be preserved by later implementation edits and by Phase 10
acceptance evidence.

39. Candidate-Pi and real-host evidence
--------------------------------------

Before operational promotion, run an explicit candidate-Pi evidence suite recording exact
Git/OpenSSH/GPG/system versions and selected profile behavior.

Verify at least:

* official Git executable identity/version and required machine-readable/plumbing switches;
* ``update-ref`` exact expected-old/nonexistence behavior and any transaction semantics used;
* ``commit-tree`` signing behavior and independent signature verification;
* operation-local index behavior and exact main-index publication/recovery primitive;
* status/diff helper suppression;
* config-source isolation plus repository-local safety validation;
* physically unavailable hooks plus disabled filters/textconv/fsmonitor/maintenance and
  byte-for-byte read-only index/status behavior;
* fetch side-effect suppression used by the contract;
* explicit exact ``--force-with-lease=<ref>:<expect>`` behavior for existing and absent
  destination refs, without relying on remote-tracking refs;
* exact SSH host-key/known-host/identity behavior;
* non-exportable SSH credential use;
* non-exportable signing capability use and signer fingerprint verification;
* Phase 7 distinct-UID/process-introspection/resource/FD isolation with Git/SSH/GPG children;
* Phase 6 root/mount/workspace coordination while Git modifies refs/index/worktree;
* read-ticket acceptance/application-crash recovery and complete prior-reader quiescence;
* tree-publication path/type/mount validation and crash recovery for switch/pull;
* enforceable object/pack/ref/index/worktree/temp/output byte/inode quotas and disk-full
  behavior rather than cgroup-only claims;
* real remote fetch/push exact-ref behavior against the registered Binnacle repository;
* outgoing reachable-object closure binding and protected/force/delete/tag denial;
* response-loss/reconciliation procedure without deliberately corrupting the hosted repo;
* broker persistence/restart, same-signature replay, runtime parent/DAC/peer isolation, and
  offline three-database migration order;
* separate running-build versus checkout-HEAD reporting;
* no raw credential disclosure.

Then run real ChatGPT through the Phase 8 exit sequence. Record only actual observed host
behavior. Unsupported Tool projection, confirmation/session semantics, credential mechanism,
or candidate Git behavior remains explicitly unsupported/blocked.

40. Holistic invariant pass before review/promotion
---------------------------------------------------

Before requesting review for this plan and again before implementation promotion, walk the
full chain for every operation:

.. code-block:: text

   request / session / repository snapshot
     -> caller-binding-first retained lookup/minimal received identity
     -> received audit
     -> policy + protected repository profile + repository-safety validation
     -> Phase6 CONTENT_READ/GitReadPermit or CHANGE/fence
     -> post-policy exact current-state/expected-self binding
     -> authorised audit
     -> Phase7 exact read/member ticket + optional one exact credential capability
     -> running/effect intent
     -> final controller/device/session/root/mount/repository/config/ref/index/worktree/
        remote/credential/network/audit OP-BOUNDARY
     -> audit obligation
     -> Phase7 single-use read/member acceptance with exact member addressing
     -> exact Git/SSH/GPG effect
     -> immediate process/effect evidence
     -> Git-specific ref/object/index-publication/worktree/remote reconciliation
     -> post-effect audit/credential/process cleanup/fence release
     -> application/supervisor restart
     -> retained same-key reconciliation

Walk at least:

* clean status/diff and output truncation;
* malicious repository config/helper/filter surfaces;
* protected internal Git metadata versus model-visible content authority;
* concurrent branch creation;
* switch stale/dirty/conflict cases;
* commit preexisting staged-index rejection and exact selected-path semantics;
* commit signing failure/wrong signer/ref CAS race;
* branch CAS followed by every main-index publication crash window;
* fetched objects with failed local ref publication;
* pull divergence after successful fetch;
* push expected-remote mismatch and a race after preflight;
* new-branch push racing a concurrent remote creator;
* push response loss followed by remote equality and remote difference;
* repository/config/profile change after policy but before effect;
* development-session end before start and after remote effect start;
* application restart/supervisor crash;
* credential cleanup ambiguity;
* same-key retry after session end;
* no raw secret or authority escalation anywhere in results/output/audit.

If multiple review findings share a common repository-profile, credential, current-state,
publication, or effect-reconciliation abstraction defect, fix the shared foundation rather
than serially patching individual Tools.

41. Plan acceptance and promotion checklist
-------------------------------------------

Plan acceptance requires:

* exactly this Phase 8 numbered document in the planning PR;
* governing source order/current merged Phase 4/6/7 references correct;
* official-Git/typed-adapter boundary explicit;
* protected Git-metadata authority separated from Phase 6 model-visible content authority;
* no direct-subprocess or generic credential-bearing command fallback;
* repository-local config/helper surface treated as untrusted and fail-closed;
* exact Phase 6 workspace coordination and Phase 7 process semantics consumed;
* Git OIDs separated from Binnacle state digests;
* lawful read-ticket/recovery lane plus one Phase 4 parent/Phase 6 fence and deterministic,
  member-addressed consequential executions without ``command_run`` re-entry;
* local branch/ref CAS and switch safety concrete;
* commit path selection, clean main-index precondition, signed commit, branch CAS, and
  durable main-index publication/recovery semantics concrete;
* fetch/pull effects separated and truthful;
* every push uses exact hosted expected-old/nonexistence CAS plus independent branch policy;
* separate SSH/signing authority and non-exportable credential contract explicit;
* exact application/executor/broker migrations, runtime ownership, result/cancellation, CI,
  and frozen evaluation seams named;
* effect knowledge/idempotency/restart/reconciliation walk complete;
* adversarial/fault/candidate-Pi/real-host evidence procedures concrete;
* no Raspberry Pi/ChatGPT/Git/credential support fact fabricated;
* exact-head CI and review green.

Implementation promotion additionally requires the empirical gates in section 3.2.

42. Implementation order
------------------------

Implement Phase 8 in this order after prerequisite exits are real:

#. define/review versioned Phase 8 operation contracts and schemas without exposing handlers;
#. define protected registered Git repository/remote/identity/signing profiles and internal
   Git-metadata authority;
#. implement repository identity/snapshot and supported-shape validator;
#. implement repository config/attributes/helper-surface validator and safety digest;
#. implement application ``0005``, executor ``0002``, broker ``0001``, and their isolated
   stores/migration/runtime ownership;
#. implement the discriminated read ticket/recovery barrier and deterministic member-
   addressed Phase 7 tickets under one consequential parent/fence;
#. implement typed closed Git execution-plan builder over that dispatcher;
#. implement read-only status/diff with strict bounds and helper suppression;
#. implement ref normalization/policy and branch-create expected-old/absence CAS;
#. implement switch stale/dirty/no-loss semantics and integration tests;
#. implement exact commit-selection validation and clean-main-index requirement;
#. implement operation-local index/tree builder and signed commit creation/verification;
#. implement exact branch-ref CAS plus durable main-index publication/restart state machine;
#. provision/integrate separately isolated signing and SSH broker capabilities, retained
   one-use evidence, and prove generic commands cannot reach either or observe both;
#. implement narrow fetch and fetched-effect reconciliation;
#. implement fast-forward-only pull composition with explicit local publication states;
#. implement exact protected-destination push with mandatory expected-remote hosted CAS and
   remote reconciliation;
#. wire Phase 4 operation/audit/idempotency, Phase 6 guard/fence, Phase 7 member-addressed
   output/restart, immutable results, cancellation, and broker obligations end-to-end;
#. promote reviewed manifest entries only after contract/schema/handler parity passes;
#. run unit/property/integration/security/fault tests;
#. run candidate-Pi Git/SSH/GPG evidence suite;
#. run real ChatGPT Phase 8 exit workflow;
#. only then mark Phase 8 implementation exited and unblock operational Phase 9/10 use.

43. Provisional and deferred items
----------------------------------

The following remain evidence-gated or deferred rather than guessed:

* exact candidate-Pi Git/OpenSSH/GPG versions and optional switches;
* exact non-exportable SSH/signing mechanism/agent implementation;
* exact ChatGPT host-confirmation/session projection for Git credential effects;
* broader repository config/features beyond the conservative supported profile;
* LFS/submodules/custom filters/hooks/merge drivers/external diff/textconv;
* a general staging/index API;
* multiple repositories/remotes;
* tag/release workflows;
* history rewriting/rebase/merge/conflict automation;
* generic force push;
* libgit2/pygit2;
* GitHub PR/review/merge APIs inside Binnacle;
* hardware-backed signing keys;
* broad developer credential broker;
* performance tuning for large repositories/object transfers.

Missing evidence in these areas does not stop this evidence-independent plan from merging.
It blocks only the corresponding implementation/promotion claim.

44. Completion state
--------------------

When this numbered plan is accepted, set ``:Status: merged``. That means the Phase 8
**planning artifact** is authoritative. It does not mean the Git Tools, credentials, signed
commit path, remote effects, or real ChatGPT self-hosting workflow have been implemented or
validated.

Phase 8 implementation exits only when the real evidence procedure in section 39 passes.
