Binnacle Phase 6 Detailed Implementation Plan
=============================================

:Phase: 6 -- Implement the Binnacle development workspace
:Status: merged
:Planning status: provisional -- evidence-independent workspace and development-session
                  semantics are concrete; implementation/promotion remains gated by the
                  real Phase 5 implementation exit, write-confirmation evidence, and a
                  reviewed session-scoped host-authority profile
:Roadmap: ``../bootstrap-implementation-plan.rst``
:Index: ``index.rst``
:Depends on: merged Phase 5 disposable write-capability-probe plan; real Phase 5 exit
             before Phase 6 implementation/promotion; reviewed/current host-authority
             evidence before operational workspace mutation is exposed
:Primary objective: Give the authenticated owner/controller normal bounded software-
                    development file authority over one registered Binnacle source
                    workspace, inside a temporary auditable development session, without
                    granting ambient filesystem, credential, policy, broker, or system
                    authority
:Implementation scope: development-session state, registered-workspace read/search/file
                       services, descriptor-relative Linux containment, typed ``ripgrep``
                       search, durable Phase 4 consequential-operation integration for
                       mutations, bounded MCP contract/schema/manifest promotion, tests,
                       deployment permissions, and evidence gates only

Purpose
-------

Phase 6 crosses from the disposable Phase 5 probe into the first real source-development
capability. It lets ChatGPT inspect and modify the registered Binnacle repository through
semantic workspace operations while keeping the network-facing Binnacle application
unprivileged and preserving the permanent boundaries around credentials, protected
configuration, local policy, privileged broker state, and arbitrary host administration.

The phase deliberately separates three facts:

* an owner-authorised development session grants broad normal developer authority inside
  the registered Binnacle source workspace;
* each consequential file mutation still consumes the Phase 4 durable operation,
  idempotency, audit, policy, final-boundary, effect-knowledge, and reconciliation kernel;
* whether the selected real ChatGPT host can represent the owner-visible bounded session
  semantics without redundant per-file confirmations remains empirical HOST-profile
  evidence and is not guessed by this plan.

This document freezes the evidence-independent local architecture and algorithms only. It
does not claim that the current ChatGPT product exposes the proposed Phase 6 Tools, that
a particular host confirmation UI exists, that the development Pi already satisfies the
required filesystem primitives, or that real Phase 5 write evidence has passed.

``:Status: merged`` denotes the terminal authoritative state of this numbered plan after
its planning review and CI acceptance. Before that acceptance the document is proposed.

1. Governing source order
-------------------------

Implementation follows this precedence:

#. ``docs/design-principles.rst``;
#. ``docs/design.md``;
#. ``docs/bootstrap-v1.rst``;
#. ``docs/bootstrap-implementation-plan.rst``;
#. ``docs/implementation/index.rst``;
#. merged ``docs/implementation/phase-04-durable-operation-kernel.rst``;
#. merged ``docs/implementation/phase-05-write-capability-probe.rst``;
#. this detailed Phase 6 plan;
#. ``docs/operation-idempotency.md`` and ``spec/operation/idempotency.yaml``;
#. ``spec/operation/lifecycle.yaml`` and operation fixtures;
#. ``docs/audit-evidence.md``, ``spec/audit/audit-policy.yaml``, and audit schemas;
#. ``docs/mcp-host-confirmation.md`` and
   ``spec/policy/host-confirmation-classes.yaml``;
#. ``spec/mcp/bootstrap-tool-manifest.yaml`` and MCP schemas;
#. ``docs/security/controller-transport.md`` and the reviewed controller profile;
#. ``docs/mcp-evaluation.md`` and evaluation contracts;
#. ``docs/deferred-decisions.rst``;
#. ``docs/target-architecture.rst``.

``docs/design-principles.rst`` supersedes conflicting older V17 detail. In particular,
its owner-approved development-session decision governs over older text that would require
a separate owner approval for every ordinary source-development step.

2. Three independent gates
---------------------------

2.1 Plan acceptance
~~~~~~~~~~~~~~~~~~~

The Phase 6 plan may merge when review and repository CI show that the evidence-independent
workspace/session specification is coherent, bounded, compatible with merged Phase 4/5
invariants, and does not invent real host/device behaviour.

Plan acceptance grants no runtime source-workspace authority.

2.2 Implementation and promotion gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not expose operational Phase 6 workspace/session handlers until all of the following
are true:

* the Phase 4 durable-operation kernel implementation exit is current on the candidate;
* the real Phase 5 write-capability exit is reviewed/current for the selected Pi and
  ChatGPT HOST profile;
* exact real Phase 5 write-confirmation/retry/reconnect evidence is available;
* a reviewed session-scoped host-authority contract/profile has reconciled the current
  HC0/HC1 per-invocation model with owner-approved development-session semantics;
* the registered workspace profile and root identity are configured outside the source
  workspace and pass local filesystem verification;
* the proposed Phase 6 operation contracts, JSON schemas, Tool-manifest entries,
  descriptions, annotations, information classes, and host-confirmation metadata have
  passed contract/schema/manifest validation;
* runtime composition keeps all Phase 6 Tools invisible/disabled whenever those
  prerequisites are absent, stale, contradictory, or unsupported.

Planning text never substitutes for any of those observations.

2.3 Phase exit gate
~~~~~~~~~~~~~~~~~~~

The roadmap exit remains empirical. Real ChatGPT must be able to inspect the registered
Binnacle repository, make one controlled source edit, inspect the resulting file, and
revert or replace it without affecting unrelated paths.

Reviewed evidence must additionally demonstrate development-session begin/inspect/end or
expiry semantics, no workspace escape, bounded read/search behaviour, exact mutation
idempotency, reconnect behaviour, and truthful failure/uncertainty handling.

3. Exact Phase 6 authority boundary
-----------------------------------

Phase 6 grants normal developer file authority only inside one reviewed registered
Binnacle source workspace. Conceptually the Bootstrap workspace is:

::

   /srv/binnacle-dev/repo

The exact path is owner configuration, not a model-controlled input.

Phase 6 may expose semantic capability for:

* workspace inspect;
* bounded directory listing;
* bounded file read;
* bounded text/regex search;
* regular-file and explicit directory creation;
* exact regular-file replacement;
* exact text patch;
* same-workspace move;
* exact regular-file deletion;
* explicit empty-directory deletion;
* development-session begin, inspect, and end/expiry.

Phase 6 does **not** grant or implement:

* unrestricted absolute-path filesystem authority;
* root filesystem access;
* arbitrary recursive delete or recursive move effects;
* symlink-following mutation;
* direct ``.git`` database/object/reference mutation;
* Git commit/fetch/pull/push credentials or signing;
* command/process execution;
* package or service mutation;
* privileged-broker access;
* Binnacle policy mutation;
* access to protected configuration, audit storage, SQLite state, controller credentials,
  SSH/GPG private keys, credential agents, or broker/control-plane sockets;
* hardware authority;
* implicit parent-directory tree creation;
* a proprietary remote filesystem protocol outside the reviewed MCP Tool surface.

Phase 7 owns development-command execution, Phase 8 owns semantic Git operations and
credential use, and Phase 9 owns privileged self-management.

4. Contract, schema, manifest, and host-profile promotion barrier
-----------------------------------------------------------------

The current Bootstrap Tool manifest contains the eight Phase 0--5 Tools only. Phase 6
runtime handlers must not be registered before a reviewed promotion step creates exact
versioned contracts and schema references for the operational workspace/session surface.

The proposed semantic Tool names are:

::

   workspace_inspect
   workspace_list
   workspace_read
   workspace_search
   workspace_create
   workspace_write
   workspace_patch
   workspace_move
   workspace_delete
   development_session_begin
   development_session_inspect
   development_session_end

Those names are proposals until the Phase 6 contract/schema/manifest promotion itself is
reviewed. The implementation should normally keep the existing schema family where it is
compatible and bump ``manifest_version`` because the reviewed catalogue changes. If all
12 proposed Tools are accepted, the Bootstrap manifest grows from 8 to 20 exact entries.

Before any handler exposure, the implementation promotion sequence is:

#. reconcile ``docs/mcp-host-confirmation.md`` and
   ``spec/policy/host-confirmation-classes.yaml`` with the bounded development-session
   authority semantics in section 5;
#. define/review the 12 operation contracts and exact input/output schema definitions;
#. define information classes, annotations, result limits, errors, and capability/profile
   requirements;
#. update ``spec/mcp/bootstrap-tool-manifest.yaml`` and the manifest documentation;
#. update evaluation fixtures and contract parity tests;
#. validate every JSON Pointer, handler binding, Tool name, contract version, annotation,
   host-confirmation classification, and schema digest;
#. only then compose/register runtime handlers.

An unmanifested or schema-mismatched handler fails startup exactly as the current manifest
contract requires.

5. Session-scoped host-authority reconciliation
------------------------------------------------

5.1 Governing semantic decision
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An explicit owner request to develop or improve Binnacle authorises a bounded Binnacle
development session for the same development objective. Once that session is active,
ChatGPT may perform ordinary source-development work inside the registered source
workspace without asking the owner to repeat the same approval for each read, write,
patch, move, or delete.

The current host-confirmation v1.1 contract does not yet represent that decision cleanly:
HC0 is limited to bounded no-effect observation/evidence, while HC1+ requires exact
per-invocation prepared confirmation and explicitly rejects open-ended future-command
approval.

Phase 6 therefore requires an explicit reviewed **session-scoped host-authority profile**
before operational promotion. The semantics are frozen here; the final machine-readable
identifier is promoted with the host-confirmation contract. A proposed identifier such as
``HCS1`` is acceptable if review retains the following meaning:

* the owner-visible authority boundary is session begin, not each member file operation;
* the session is bounded to one exact device/controller/workspace/profile and a finite
  trusted-time lifetime;
* only the reviewed workspace capability family is included;
* credential, policy, control-plane, privileged, arbitrary-system, and hardware authority
  remain excluded;
* each member call still requires authenticated controller identity, exact current session
  validity, local policy, exact Tool contract, exact input, and current verified state;
* host metadata, a Tool annotation, model prose, or possession of a session identifier
  never creates local authority;
* the selected real ChatGPT HOST profile remains unsupported for Phase 6 if it cannot
  safely express/demonstrate the bounded session model.

The actual ChatGPT interaction may be a one-time owner-visible confirmation, an explicit
session-start interaction derived from the owner request, or another host-native mechanism.
That mechanism is an empirical profile fact and is not invented here.

5.2 Information-class consequence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Workspace metadata can normally be ``normal-result``. Source file contents and search
matches are conservatively ``restricted-result`` unless the reviewed workspace profile
explicitly proves a narrower public-information classification.

The session-scoped host profile must therefore cover both ordinary source-workspace
mutation authority and bounded source-content disclosure without repeated per-file owner
prompts. Reusable credentials and protected state remain ``never-disclosable`` and are
outside the workspace profile rather than relying on content scanning.

6. Development-session domain model
------------------------------------

Phase 6 introduces one durable/auditable development-session model owned by the main
Binnacle application.

Representative domain types:

.. code-block:: python

   class DevelopmentSessionState(StrEnum):
       PENDING = "pending"
       ACTIVE = "active"
       ENDED = "ended"
       EXPIRED = "expired"
       REVOKED = "revoked"

   @dataclass(frozen=True, slots=True)
   class DevelopmentSessionSnapshot:
       session_id: str
       state: DevelopmentSessionState
       state_version: int
       controller_id: str
       controller_epoch: int
       device_id: str
       device_epoch: int
       workspace_id: str
       workspace_profile_sha256: str
       workspace_root_identity_sha256: str
       policy_version: str
       contract_profile_sha256: str
       objective_sha256: str
       started_at: datetime | None
       expires_at: datetime
       effective_for_new_work: bool
       ineffective_reason: str | None

``session_id`` is opaque and contains at least 128 random bits. It is an identifier, not a
bearer credential.

One active session per authenticated owner/controller + registered workspace is sufficient
for Bootstrap. A concurrent distinct begin request while an exact session is active does
not create a second overlapping authority domain; it returns a bounded
``development_session_already_active`` result or the retained same-key operation as
applicable.

The free-form owner objective is not executable policy. The implementation stores a
bounded safe label where useful plus a canonical digest for provenance. Binnacle does not
attempt to decide whether every later source edit is semantically part of the objective;
the session grants the reviewed broad workspace capability and ChatGPT remains the
reasoning agent.

7. Session lifetime, restart, and revocation
--------------------------------------------

7.1 Trusted-time binding
~~~~~~~~~~~~~~~~~~~~~~~~

Session lifetime uses the Phase 4 trusted-time model rather than wall clock alone. The
session record stores enough evidence to enforce expiry safely across ordinary restart:

* ``expires_at``;
* trusted-time generation at activation;
* activation boot identity digest;
* same-boot monotonic deadline when available;
* controller/device/workspace/profile/policy version snapshots.

A reasonable Bootstrap configuration is a one-hour default with a hard maximum of four
hours. Exact schema limits are frozen during contract promotion and cannot be enlarged by
model-controlled input beyond the reviewed hard maximum.

Clock rollback, reboot with untrusted wall time, or lost trusted-time continuity never
extends a session. If expiry cannot be proven safely, ``effective_for_new_work=false`` and
new workspace mutations fail closed.

7.2 Ordinary Binnacle restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An ordinary MCP/application restart does not by itself end a session. On startup,
reconciliation may restore a session as effective only when all exact identity/profile/
policy/trusted-time predicates still verify.

This is necessary for the Bootstrap self-hosting loop: a normal Binnacle restart must not
force the owner to repeat the same development-session approval solely because the MCP
process restarted.

7.3 End, expiry, and revocation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session end/expiry/revocation has two separate meanings:

* it prevents **new** member admission and any not-yet-started consequential member from
  crossing its final effect boundary;
* it does not rewrite, erase, duplicate, or blindly cancel the truth of an effect whose
  ``EffectBoundary.start`` already linearized.

Therefore the final OP-BOUNDARY for every workspace mutation revalidates that the exact
session is still effective immediately before effect start. If the session ended or
expired before start, the mutation closes as proven no-effect and releases its workspace
mutation fence only after the normal Phase 4 audit/recovery closure.

If the effect already started, later session end does not manufacture
``known_no_effect``. The retained operation proceeds through truthful receipt/effect
classification and restart reconciliation. Same-key retry after session end returns the
retained operation/result/uncertainty and never requires a now-expired session to create a
second effect.

8. Session begin/inspect/end application semantics
--------------------------------------------------

8.1 ``development_session_begin``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session begin is a consequential authority-state operation even though it does not write a
source file.

First-use ordering is:

#. authenticate the owner/controller and normalize the exact workspace/objective/duration
   request;
#. resolve an existing caller-key binding before mutable session/current-state checks;
#. create the minimal Phase 4 ``received`` identity and required received audit;
#. evaluate local policy for development-session activation;
#. after allow, create a ``PENDING`` session row bound to exact controller/device/workspace
   profile and trusted-time deadline;
#. emit required allowed/authorised audit and move the operation to ``running``;
#. record the activation intent and perform final controller/device/workspace/profile/
   policy/time revalidation;
#. atomically transition the exact pending session to ``ACTIVE`` with the activation
   operation ID/state version;
#. classify that authoritative SQLite state transition and complete required post-effect
   audit/obligation closure before the session is considered effective for new member
   mutations.

Because the authority effect itself is authoritative SQLite state, restart can reconcile a
crash after the exact ``PENDING -> ACTIVE`` commit from the retained session row and
activation operation identity. It does not infer activation from host UI or model text.

8.2 ``development_session_inspect``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session inspect is bounded/read-only. The authenticated owner may inspect current/terminal
session metadata, effective status, expiry/provisional trusted-time status, workspace ID,
profile digest, and bounded reason codes. It reveals no credential, policy body, protected
path, raw audit bytes, or source content.

8.3 ``development_session_end``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

End is an authority-reducing operation. When the exact active owner session is ended, the
session state transition takes effect before any later new member can be admitted. A
failure to append the required end audit must never cause authority to remain active merely
so the audit can succeed first; instead the session remains reduced/ended while Phase 4
audit failure puts consequential admission into fail-restricted recovery.

A same-key retry returns the retained end operation. A new request against an already
terminal session may return bounded already-ended state with no new effect.

9. Registered workspace profile and protected configuration
-----------------------------------------------------------

Workspace registration is protected configuration/control-plane state. Phase 6 Tools may
consume but never create, change, broaden, or delete a workspace registration.

Representative resolved settings:

.. code-block:: python

   class WorkspaceProfile(BaseModel):
       workspace_id: str
       root: Path
       enabled: bool = False
       max_path_bytes: int = 4096
       max_path_depth: int = 64
       max_file_mutation_bytes: int = 4 * 1024 * 1024
       max_read_chunk_bytes: int = 1024 * 1024
       max_list_entries: int = 4096
       max_search_matches: int = 2000
       max_search_output_bytes: int = 1024 * 1024
       search_timeout_seconds: float = 5.0

The exact production profile lives under protected configuration such as
``/etc/binnacle`` and is loaded into an immutable resolved settings snapshot. Model input
selects a registered ``workspace_id`` only; it cannot supply or redirect the root path.

At session activation Binnacle opens/verifies the configured root and records a protected
root identity digest derived from exact descriptor-visible facts such as filesystem/device
and directory inode identity plus the workspace/profile digest. Every later operation
re-opens the configured root and proves it still corresponds to the session-bound root
identity before returning source content or admitting mutation.

A root path replacement, symlink substitution, bind/profile change, or unverifiable root
identity makes the session ineffective for new work. Binnacle does not silently rebase the
session onto a newly observed directory.

10. Workspace-internal protected boundaries
--------------------------------------------

The Binnacle source checkout includes source files and project-local development state.
Phase 6 must not turn every byte below the path string into identical authority.

At minimum, the reviewed Binnacle workspace profile excludes direct workspace mutation of:

* ``.git/`` -- Phase 8 semantic Git operations own repository metadata and credentials;
* project-local credential/private-key material if any is explicitly registered;
* any path mapped to protected Binnacle config/state/audit/control-plane storage;
* any deployment-specific protected path added by the owner profile.

``.github/``, ``docs/``, source, tests, ``pyproject.toml``, ``uv.lock``, lint/test
configuration, and ordinary repository files are normal source-workspace content.

The implementation does not rely on heuristic secret scanning as the security boundary.
Reusable secrets belong outside the workspace or in explicit protected exclusions. Source
content returned to ChatGPT remains conservatively classified as described in section 5.2.

11. Canonical workspace path model
----------------------------------

One normalizer owns all path-bearing workspace contracts.

Canonical input is a workspace-relative POSIX-style path with these rules:

* UTF-8 and NFC-normalized;
* no leading ``/`` and no platform drive/UNC prefix;
* ``/`` is the only separator; backslash is rejected rather than reinterpreted;
* no empty component, ``.`` or ``..`` component, NUL, CR, or LF;
* each encoded component is within the Linux filename limit;
* full encoded path and component depth are within the reviewed profile limits;
* reserved Binnacle staging names/prefixes are rejected;
* the path identifies the semantic target only after descriptor-relative resolution.

String normalization never proves containment. Security containment is descriptor based.

12. Descriptor-relative Linux containment
-----------------------------------------

The security boundary uses Linux descriptor-relative operations rather than
``Path.resolve()``/string-prefix checks.

Bootstrap may prefer ``openat2`` with exact beneath/no-magiclink/no-symlink resolution when
a small reviewed implementation is available. The required portable Bootstrap baseline is
still race-resistant descriptor traversal using Python/Linux primitives:

* open and pin the registered root directory descriptor;
* compare its exact identity with the session/profile root identity;
* walk directory components relative to already-open descriptors using ``dir_fd`` APIs,
  ``O_DIRECTORY`` and ``O_NOFOLLOW``;
* use ``follow_symlinks=False`` for metadata checks;
* invoke final ``open``, ``link``, ``rename``, ``unlink`` and directory operations through
  pinned parent descriptors rather than reconstructed absolute paths;
* never follow a symlink during read or mutation;
* close all descriptors deterministically.

Read-only inspect/list may report that an entry is a symlink and may return its bounded
link metadata/target text where explicitly reviewed, but ``workspace_read`` and all
Phase 6 mutation operations reject symlink traversal and symlink-as-file mutation.

13. Stable object/version identity
----------------------------------

Read/inspect output returns a bounded opaque ``object_version`` for regular files and
explicit directories. The token is a digest of a canonical server-side structure that
binds at least:

* workspace/profile/root identity;
* normalized relative path;
* object type;
* descriptor-observed filesystem/inode identity;
* relevant mode/size/time facts;
* for mutable regular files, exact full content SHA-256 when within the reviewed mutation
  ceiling.

The token is not authority. Mutation inputs that replace/delete/move existing content must
supply the exact expected token and, where required, the expected content SHA-256. A stale
or changed object fails before effect start.

Files exceeding the reviewed mutation/hash ceiling remain readable in bounded chunks where
permitted but are not directly mutable by Phase 6 until a separately reviewed larger-file
contract exists.

14. Read-only workspace operations
----------------------------------

All read-only operations require authenticated owner/controller identity, the exact
registered workspace, and an effective development session unless the promoted contract
explicitly defines a smaller safe metadata exception.

They create no consequential Phase 4 operation merely for bookkeeping. They still enforce
request bounds, session/workspace authority, information classification, redaction,
rate/resource limits, and audit/diagnostic policy applicable to reads.

14.1 ``workspace_inspect``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns bounded workspace/profile/root identity, optional one-path metadata, object type,
object version, size/mode summary, and capability/degradation facts. It does not expose
absolute protected paths when a stable workspace-relative projection is sufficient.

14.2 ``workspace_list``
~~~~~~~~~~~~~~~~~~~~~~~

Lists one directory or a bounded recursive depth. Traversal is descriptor-relative, does
not follow symlinks, stops at configured entry/depth/output ceilings, and returns a
truthful ``truncated`` indicator.

14.3 ``workspace_read``
~~~~~~~~~~~~~~~~~~~~~~~

Reads one exact regular file with bounded byte range/chunk semantics. It returns the
object version, full content digest when available, exact returned range, encoding/media
facts, and truncation/continuation information. Binary content is never silently decoded
as text.

15. Typed ``ripgrep`` search adapter
------------------------------------

``workspace_search`` uses the mature ``ripgrep`` executable behind a typed adapter rather
than a custom repository index or Python regex walk.

The adapter invokes explicit argv only and never a shell. Use ``rg --json`` or an equally
structured mode so parser behaviour is deterministic.

The reviewed adapter binds:

* exact registered workspace/root descriptor identity before launch;
* optional normalized search subpath;
* bounded pattern length;
* Rust-regex/default engine semantics only for Bootstrap; no arbitrary PCRE2 feature
  expansion unless separately reviewed;
* case/fixed-string options from a closed enum;
* file/match/output/per-file byte ceilings;
* hard wall timeout;
* binary-file skip policy;
* no symlink following;
* hidden-file handling sufficient to search normal source paths such as ``.github`` while
  explicitly excluding protected ``.git`` metadata;
* reviewed ignore-file behaviour;
* bounded subprocess stdout/stderr capture;
* truthful ``truncated`` and ``timed_out`` results.

Search is read-only. A timeout or output ceiling never becomes a partial-success claim
without explicit ``truncated``/``timed_out`` metadata.

16. Consequential workspace mutation fence
------------------------------------------

Phase 6 deliberately chooses a conservative Bootstrap concurrency model: at most one
consequential Binnacle-managed workspace file mutation may own the registered workspace
fence at a time. Read-only operations remain concurrent.

This avoids recreating the Phase 5 path-history cascade for overlapping parent/source/
target paths while still supporting the one-controller self-development loop.

Migration ``0003`` introduces a durable row conceptually equivalent to:

::

   workspace_mutation_fences(
       workspace_id PRIMARY KEY,
       fence_version INTEGER NOT NULL,
       active_operation_id NULLABLE UNIQUE,
       active_contract NULLABLE,
       acquired_at NULLABLE
   )

The row is authoritative protected state, not a cache reconstructed from surviving
filesystem observations. A missing/corrupt row for a configured/previously initialized
workspace fails consequential readiness.

Post-policy admission may acquire only the exact transition:

::

   free fence version N
       -> exact current operation owns fence version N+1

The operation-specific current-state binding represents that expected self transition
semantically rather than hashing a raw ``NULL`` that would necessarily mismatch after
admission. Final OP-BOUNDARY canonicalization accepts only the exact self-owned fence plus
the consumed operation binding. Foreign ownership, missing ownership, changed workspace
profile, or unexpected fence version fails closed.

The fence is released only after the operation has a truthful terminal/no-effect/effect
classification plus the required post-effect audit/obligation/recovery closure. An
``uncertain`` operation retains the fence and blocks new mutations until explicit
reconciliation. Filesystem appearance/absence never reconstructs or steals fence
ownership.

17. Mutation first-use ordering and retained retry
-------------------------------------------------

Every consequential workspace mutation follows the same high-level sequence.

For an existing caller-key/global duplicate-prevention binding, **retained lookup wins
first**: same owner + same key + same request fingerprint returns/reconciles the retained
operation without requiring the current session to still be active, without rechecking the
now-changed filesystem as fresh authority, and with zero new fence/effect. Same-key +
different fingerprint conflicts; another owner receives the Phase 4 non-disclosing owner
mismatch; a current tombstone returns the retired-key outcome.

Only when no caller binding/operation exists may first admission continue:

#. authenticate and normalize exact session/workspace/path/content/expected-version input;
#. compute the effect-bearing fingerprint including the exact session ID and mutation
   contract inputs but excluding mutable observations/policy results;
#. atomically create/find the global caller-key record and minimal version-1 ``received``
   operation;
#. fsync the required schema-valid ``operation.state_changed(NULL -> received)`` audit
   before policy;
#. load/revalidate the exact active session, workspace/profile/root identity, expected
   source/target state and local policy inputs;
#. evaluate policy;
#. on deny, durably store the one decision and ``received -> rejected`` with no workspace
   fence/effect;
#. on allow, in one short post-policy transaction re-prove the exact operation/session
   predicates, acquire the free workspace mutation fence for this exact operation, store
   the operation-specific workspace binding, store the one allow decision, and commit
   ``received -> authorised``;
#. fsync required allowed ``policy.decision`` + ``operation.authorised`` evidence;
#. commit ``authorised -> running``;
#. fsync ``effect.intent_recorded``;
#. enter the Phase 4 per-operation dispatch handoff and process-wide consequential gate;
#. perform final all-mode OP-BOUNDARY revalidation including exact current session,
   controller/device/profile/policy/root/fence/source/target/cancellation/audit/recovery
   facts;
#. publish/fsync the durable audit-obligation marker;
#. linearize and start the exact workspace effect;
#. immediately persist the bounded effect reference/receipt/effect knowledge;
#. complete required post-effect audit, operation/domain closure, obligation cleanup, and
   fence release where truthfully safe.

No SQLite transaction spans filesystem effect I/O.

18. Phase-stable mutation current-state binding
-----------------------------------------------

The operation-specific workspace binding is a canonical digest over immutable/request
facts plus exact current state and only the narrowly expected self-owned admission
transition.

For all mutation kinds it binds at least:

* session ID and session state/version expected at admission;
* controller/device identity+epoch;
* workspace ID/profile/root identity;
* Tool/contract version;
* normalized source/target path(s);
* expected source object version/content digest/type as applicable;
* expected target absence/object version as applicable;
* proposed new content digest/byte count as applicable;
* the semantic fence component
  ``workspace_fence_transition=free_N_then_exact_self_N_plus_1``;
* policy/profile digest facts required by the operation contract.

At final OP-BOUNDARY, the callback may reproduce the same semantic fence component only
after proving the raw fence owner equals the exact running operation, version equals
``N+1``, and the immutable operation/binding relationship matches. No other changed state
is normalized away.

This is the Phase 5 lesson generalized explicitly rather than discovered serially in
review.

19. ``workspace_create``
------------------------

The create contract has an explicit kind:

* ``file`` -- create one new regular file with bounded content;
* ``directory`` -- create one exact empty directory.

There is no implicit ``parents=true``. Parent directories must already exist and pass
exact descriptor-relative verification.

For a file:

* final target must be absent at admission and final OP-BOUNDARY;
* content is bounded by the workspace profile;
* mode is a reviewed closed choice such as ordinary ``0644`` or executable ``0755``;
* stage complete bytes in the verified target filesystem under a reserved operation-owned
  staging name;
* fsync staged file;
* publish with an atomic no-replace primitive; a same-filesystem descriptor-relative hard
  link from the complete staged inode is an acceptable baseline when it provides exact
  no-overwrite semantics;
* fsync the parent directory after publication;
* remove/fsync the staging name only after truthful publication handling.

If the target appears before the no-replace publication, return a proven no-effect
conflict. If the process loses the publication/fsync receipt, final pathname presence
alone cannot establish ``known_effect`` and the operation becomes/remains ``uncertain``.

Directory create uses exact descriptor-relative ``mkdir`` with no parent broadening and
parent-directory fsync. Receipt ambiguity is treated conservatively.

20. ``workspace_write``
-----------------------

Write is full replacement of one existing regular file. It is not create-if-missing and
not overwrite-without-version.

Required first-use input includes:

* exact normalized path;
* expected ``object_version``;
* expected current content SHA-256;
* one bounded text/base64 content representation;
* caller idempotency key and exact development-session identity.

Admission and final OP-BOUNDARY require the same exact regular file identity/content.

Replacement algorithm:

#. create a restrictive operation-owned temporary regular file in the same verified target
   directory/filesystem;
#. write all bounded bytes and verify byte count/digest;
#. fsync the temporary file;
#. re-stat/re-read/hash the exact target through the pinned parent descriptor immediately
   before replacement and require the expected object version/content;
#. atomically rename/replace the temporary inode onto the exact target path;
#. fsync the parent directory;
#. retain a bounded effect reference containing the operation/workspace/target and verified
   new content/object identity facts.

The implementation preserves the reviewed ordinary executable/non-executable POSIX mode
where safe. It rejects special files, setuid/setgid/capability-bearing files, unsupported
ACL/xattr semantics that would otherwise be silently destroyed, or ownership outside the
registered source-workspace profile.

Linux pathname replacement does not provide perfect compare-and-swap against an unrelated
external writer between the final revalidation and rename. Bootstrap records this residual
local race explicitly. The workspace mutation fence serializes all **Binnacle-managed**
mutations; immediate final descriptor-relative revalidation narrows the external race; a
post-syscall mismatch/lost receipt is never overclaimed and may remain ``uncertain``.

21. ``workspace_patch``
-----------------------

Patch is deterministic text transformation against one exact UTF-8 base file.

Required input includes exact base object version/content SHA-256 and a bounded ordered set
of exact-match replacements. Each edit provides an exact ``match_text`` and
``replacement_text``. Against the original base, each match must occur exactly once and
all matched spans must be non-overlapping. Zero, duplicate, overlapping, invalid UTF-8, or
stale-base matches reject with no effect.

The application computes the complete new bytes in memory/bounded retained storage,
validates final byte count/digest, then uses the exact ``workspace_write`` replacement
adapter path. Patch never executes a shell ``patch`` program and never applies fuzzy
context.

22. ``workspace_move``
----------------------

Bootstrap move supports:

* one exact regular file; or
* one exact empty directory.

Non-empty directory tree move is deferred until a separately reviewed bounded subtree
contract exists.

First-use input binds exact source object version/content where applicable and exact target
absence. Source and target must be inside the same registered workspace and verified
filesystem. Cross-device semantics are rejected truthfully rather than silently becoming a
copy+delete compound effect.

Immediately before rename, final OP-BOUNDARY and adapter revalidation require the exact
source and absent target. After rename, parent directories for source and target are
fsynced when distinct. Lost rename/fsync receipt or unprovable result becomes
``uncertain``; target appearance/source absence alone is not sufficient recovery proof.

23. ``workspace_delete``
------------------------

Delete supports exactly:

* one existing regular file with expected object version/content digest; or
* one exact empty directory with expected object version.

There is no recursive flag, glob, wildcard, implicit cleanup, or delete-through-symlink.

Final descriptor-relative identity verification occurs immediately before ``unlink`` or
``rmdir``. Parent-directory fsync is part of successful effect completion. A lost receipt
with observed absence remains ``uncertain`` unless independent durable effect evidence
proves the deletion; absence alone is not a removal receipt.

24. Effect knowledge and domain closure
---------------------------------------

Each mutation adapter returns a bounded typed effect receipt only after its required
filesystem durability point is reached.

Representative internal effect reference fields include:

* workspace ID/profile digest;
* operation ID;
* mutation kind;
* source/target digest(s);
* staged object identifier where applicable;
* verified post-effect object identity/content digest where applicable;
* exact durability step completed;
* receipt digest/version.

The generic Phase 4 operation owns authoritative lifecycle/effect knowledge. Phase 6
operation-specific rows may record bounded source/target/result facts but cannot invent a
parallel effect-knowledge enum.

Rules are:

* complete adapter receipt after the exact durability point -> eligible for
  ``known_effect``;
* explicit pre-start/no-syscall or exact no-effect receipt -> eligible for
  ``known_no_effect``;
* lost syscall/fsync receipt, incomplete effect reference, identity mismatch, or
  unprovable external race -> ``uncertain``;
* final filesystem state alone never upgrades uncertainty;
* terminal operation/domain/fence closure occurs only after the required audit obligation
  and reconciliation predicates are complete.

25. Restart and reconciliation
------------------------------

Startup reconciliation loads Phase 4 operations plus Phase 6 session/workspace state.

Required behaviour:

* ``received`` without completed admission follows Phase 4 fail-closed recovery deny;
* ``authorised`` that never entered dispatch does not start automatically after restart;
* ``running`` with no durable exact effect receipt is not classified
  ``known_no_effect`` merely from the filesystem;
* an operation retaining the workspace mutation fence is reconciled before any new
  mutation may acquire it;
* exact durable receipt/reference plus independently verifiable identity may converge an
  operation according to its adapter contract;
* ambiguous/lost receipt remains ``uncertain`` and retains the fence;
* session end/expiry does not prevent same-key retrieval/reconciliation of already retained
  work;
* a still-active session is restored as effective only after exact profile/root/policy/time
  verification;
* no session or workspace integrity record is rebuilt from mutable source-tree state after
  corruption.

26. Persistence and migration
-----------------------------

Phase 6 implementation is expected to add Alembic migration
``0003_development_workspace.py`` after the Phase 5 probe migration.

Representative authoritative tables are:

``development_sessions``
   Durable session identity, owner/device/workspace/profile/policy/objective digests,
   trusted-time deadline evidence, state/version, activation operation, and terminal
   timestamps/reasons.

``workspace_operations``
   One-to-one operation-specific metadata keyed by the Phase 4 ``operation_id``: session,
   workspace, mutation kind, normalized source/target digests, expected object/content
   bindings, proposed content digest, and canonical current-state binding digest.

``workspace_mutation_fences``
   One authoritative row per registered workspace with monotonic fence version and nullable
   active operation owner.

Foreign keys point toward the Phase 4 authoritative operation/session ownership records.
Database checks reject impossible state combinations. Runtime code never creates schema
opportunistically.

27. Expected implementation file set
------------------------------------

Representative implementation paths are:

::

   src/binnacle/domain/development_session.py
   src/binnacle/domain/workspace.py
   src/binnacle/ports/workspace.py
   src/binnacle/application/development_session.py
   src/binnacle/application/workspace.py
   src/binnacle/adapters/workspace/__init__.py
   src/binnacle/adapters/workspace/linux.py
   src/binnacle/adapters/workspace/ripgrep.py
   src/binnacle/adapters/workspace/reconcile.py
   migrations/versions/0003_development_workspace.py
   tests/unit/domain/test_development_session.py
   tests/unit/domain/test_workspace.py
   tests/unit/application/test_workspace.py
   tests/integration/test_workspace_linux.py
   tests/integration/test_workspace_reconciliation.py
   tests/property/test_workspace_lifecycle.py

Existing Phase 4 application/persistence/audit/policy composition and MCP registry files are
extended rather than replaced.

Contract-promotion implementation is also expected to update:

::

   docs/mcp-host-confirmation.md
   spec/policy/host-confirmation-classes.yaml
   spec/mcp/bootstrap-tool-manifest.yaml
   schemas/mcp/bootstrap-inputs.schema.json
   schemas/mcp/bootstrap-outputs.schema.json
   docs/mcp-tool-manifest.md
   docs/mcp-schemas.md
   docs/mcp-evaluation.md
   spec/mcp/evaluation-cases.yaml

The exact set remains implementation-driven, but no alternate parallel contract files are
introduced merely for Phase 6 convenience.

28. Ports and adapter responsibilities
--------------------------------------

Representative boundaries:

.. code-block:: python

   class WorkspaceReader(Protocol):
       async def inspect(self, request: InspectRequest) -> WorkspaceEntry: ...
       async def list(self, request: ListRequest) -> WorkspaceListing: ...
       async def read(self, request: ReadRequest) -> WorkspaceReadResult: ...

   class WorkspaceSearch(Protocol):
       async def search(self, request: SearchRequest) -> WorkspaceSearchResult: ...

   class WorkspaceMutator(Protocol):
       async def create(self, intent: CreateIntent) -> WorkspaceEffectReceipt: ...
       async def write(self, intent: WriteIntent) -> WorkspaceEffectReceipt: ...
       async def move(self, intent: MoveIntent) -> WorkspaceEffectReceipt: ...
       async def delete(self, intent: DeleteIntent) -> WorkspaceEffectReceipt: ...

``workspace_patch`` belongs in the application layer: it computes deterministic new bytes
from exact base content and delegates the final replacement to ``WorkspaceMutator.write``.

The Linux adapter never performs policy, controller authentication, host confirmation, or
operation lifecycle decisions. The application service never implements raw pathname
containment or shell search execution.

29. Error projection
--------------------

Use closed machine-readable reason/error codes with bounded safe summaries. Representative
Phase 6 errors include:

* ``development_session_required``;
* ``development_session_expired``;
* ``development_session_not_effective``;
* ``development_session_already_active``;
* ``workspace_not_registered``;
* ``workspace_profile_mismatch``;
* ``workspace_root_identity_mismatch``;
* ``workspace_path_invalid``;
* ``workspace_path_protected``;
* ``workspace_symlink_forbidden``;
* ``workspace_object_type_unsupported``;
* ``workspace_object_stale``;
* ``workspace_target_exists``;
* ``workspace_target_missing``;
* ``workspace_patch_mismatch``;
* ``workspace_cross_device_move_unsupported``;
* ``workspace_directory_not_empty``;
* ``workspace_busy``;
* ``workspace_effect_uncertain``;
* ``workspace_output_truncated``;
* ``workspace_search_timeout``.

Errors do not reveal a protected absolute path, another controller's session/operation, raw
idempotency key, credential, or never-disclosable state.

30. Logging, metrics, and diagnostics
------------------------------------

Structured diagnostics may include workspace ID, operation/session IDs, mutation kind,
normalized-path digest, result byte counts, truncation, search duration, fence state,
reason codes, and effect-reference digest.

Do not log:

* raw idempotency keys/nonces;
* source file contents/search matches by default;
* reusable credentials;
* protected absolute paths where workspace-relative identity suffices;
* raw controller authentication material.

Useful metrics include bounded counters/histograms for workspace reads/searches/mutations,
search timeout/truncation, stale-version rejections, fence contention, uncertain mutation
outcomes, and session starts/ends/expiry. Path names and operation keys are never unbounded
metric labels.

31. Security invariants
-----------------------

The implementation and review must prove at least:

#. The network-facing MCP/application process remains unprivileged.
#. Workspace root is owner configuration and never model-selected absolute path input.
#. A development session never grants credential, policy, broker, control-plane, arbitrary
   system, or hardware authority.
#. Session identifiers are not bearer authority; exact authenticated owner identity and
   local policy remain required.
#. Session expiry/end/revocation denies new/not-yet-started mutations but does not rewrite
   already-started effect truth.
#. Same-key retained retry resolves before mutable session/filesystem checks and can never
   create a second effect.
#. Every new mutation has Phase 4 durable caller identity before policy/effect.
#. Workspace mutation fence is acquired only after policy allow and is exact-self bound at
   final OP-BOUNDARY.
#. ``uncertain`` retains the workspace mutation fence and is never blindly retried.
#. Final OP-BOUNDARY revalidates session, controller/device, profile/root, policy, audit,
   operation state, fence, and exact source/target facts immediately before start.
#. Required received and authorised audit ordering remains exactly Phase 4 compatible.
#. No symlink traversal or string-prefix containment decides filesystem authority.
#. Create cannot overwrite; write/patch cannot silently create; delete cannot recursively
   broaden; move cannot silently become copy+delete.
#. External-writer pathname races are acknowledged and never converted into false
   compare-and-swap guarantees.
#. Post-syscall observation alone never proves effect after a lost receipt.
#. ``.git`` metadata and protected paths are outside direct workspace mutation authority.
#. Search uses typed argv and bounded structured parsing, never a shell command assembled
   from model text.
#. Source-content disclosure is bounded and classified; reusable secrets remain excluded.
#. Workspace/session integrity state is never silently reconstructed from a changed source
   tree after corruption.

32. Test strategy
-----------------

32.1 Unit tests
~~~~~~~~~~~~~~~

Cover:

* path normalization and every invalid component class;
* session state/version/expiry/effective predicates;
* same-key retained retry before current session/state validation;
* object-version canonicalization;
* exact-match patch transformation and duplicate/overlap rejection;
* mutation fence free/self/foreign/version transitions;
* policy deny before fence acquisition;
* final verifier exact-self fence canonicalization;
* create/write/patch/move/delete input and error mapping;
* bounded read/list/search result projection.

32.2 Property tests
~~~~~~~~~~~~~~~~~~~

Use Hypothesis for:

* normalized paths never escaping the registered root model;
* arbitrary symlink/component trees never becoming valid mutation traversal;
* same key/same fingerprint producing one operation/effect counter;
* same key/different fingerprint producing zero additional effects;
* no legal transition releasing a fence from ``uncertain`` without reconciliation;
* session end/expiry before start producing zero effect;
* session end after start never converting durable/uncertain effect truth to no-effect;
* patch edits either deterministically produce one exact byte string or reject with no
  effect;
* fence version monotonicity across acquire/release/restart.

32.3 Linux integration tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux temp workspaces test:

* descriptor-relative nested traversal;
* symlink-to-inside and symlink-to-outside rejection;
* root replacement/mismatch;
* create no-overwrite;
* regular-file replacement durability path;
* parent rename/symlink races where reproducible;
* empty-directory create/delete;
* non-empty-directory delete/move rejection;
* same-workspace move and cross-device rejection where fixtures permit;
* file mode/unsupported metadata rejection;
* ``rg --json`` parsing, hidden ``.github`` search, ``.git`` exclusion, binary skip,
  timeout, output truncation, and process failure.

32.4 Fault and restart tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inject crashes/failures at least at:

* after minimal received operation before policy;
* after policy allow before fence acquisition;
* after fence acquisition before authorised audit;
* after running/effect intent before final OP-BOUNDARY;
* after audit-obligation publication before filesystem syscall;
* after create publication before directory-fsync receipt;
* after write rename before directory-fsync/receipt;
* after move rename before receipt;
* after delete unlink before receipt;
* after durable adapter receipt before generic effect classification;
* after generic known-effect before post-effect audit/fence release;
* DB failure during terminal/fence release;
* process restart with an active session;
* process restart with expired/untrusted-time session;
* process restart with retained ``uncertain`` mutation.

Expected results prefer conservative retained truth. In particular, pathname presence or
absence after a lost receipt never manufactures ``known_effect``/``known_no_effect``.

32.5 Concurrency tests
~~~~~~~~~~~~~~~~~~~~~~

Prove:

* two distinct first mutations cannot both own the workspace fence;
* same-key concurrent first calls converge to one operation;
* session end racing final OP-BOUNDARY either wins before start (zero effect) or loses to
  the Phase 4 start linearization (effect already started and truthfully classified);
* required audit failure racing dispatch obeys the process-wide Phase 4 gate;
* read/search operations remain bounded while a mutation owns the fence.

32.6 Contract/schema tests
~~~~~~~~~~~~~~~~~~~~~~~~~

Before runtime exposure prove:

* proposed Tool names are unique/non-confusable;
* every input/output JSON Pointer resolves;
* manifest/handler/contract versions agree;
* information/host-confirmation classes match reviewed session semantics;
* no Phase 6 Tool appears when promotion prerequisites are absent;
* current eight-tool profiles remain unchanged until explicit promotion;
* exact catalogue digest changes only through the reviewed manifest bump.

33. Real-Pi and real-ChatGPT evidence procedure
-----------------------------------------------

Evidence is required for implementation promotion/exit, not for plan acceptance.

Real Pi evidence should verify:

* source checkout root identity and ownership;
* descriptor-relative filesystem behaviour on the actual filesystem/kernel;
* no-replace create primitive used by the implementation;
* rename/fsync semantics needed by write/move/delete;
* ``ripgrep`` availability/version and bounded execution;
* systemd/service permissions permit exactly the registered source workspace and do not
  accidentally grant protected state.

Real ChatGPT evidence should verify:

* exact catalogue discovery of promoted Phase 6 Tools;
* actual session-start host interaction/authority behaviour;
* no redundant per-member confirmation if the reviewed HOST profile claims session
  semantics;
* bounded source read/search presentation;
* create/write/patch/move/delete entitlement as actually promoted;
* same-key retry and lost-response behaviour;
* session reconnect/restart continuity;
* session end/expiry handling;
* no capability escape to protected/unregistered paths.

If the host cannot safely express the reviewed bounded session authority, operational
Phase 6 remains unsupported for that HOST profile. Do not weaken local policy or silently
fall back to ambient HC0 mutation authority.

34. Holistic invariant pass before review
-----------------------------------------

Before opening the Phase 6 planning PR for external AI review, inspect the design as one
continuous consequential-operation pipeline rather than waiting for serial comments:

::

   normalize exact request/session/workspace state
     -> caller-key retained lookup or minimal pre-policy durable identity
     -> required received audit
     -> policy
     -> post-policy exact-self workspace fence + operation binding
     -> authorised audit
     -> running/effect intent
     -> phase-stable binding across the expected self fence transition
     -> final OP-BOUNDARY session/profile/root/source/target revalidation
     -> durable audit obligation
     -> EffectBoundary.start
     -> immediate durable receipt/effect knowledge
     -> operation-specific domain closure
     -> post-effect audit/obligation closure
     -> fence release or conservative retention
     -> crash/restart reconciliation
     -> caller-binding-first retained retry

The review must additionally walk each mutation kind through:

* normal success;
* stale source/target before start;
* session end/expiry before start;
* audit failure before start;
* crash after filesystem syscall but before receipt;
* durable known effect then DB/audit closure failure;
* same-key response-loss retry after state changed/session expired;
* ``uncertain`` restart with new unrelated mutation attempted.

If a review finding exposes a shared abstraction defect, correct the shared Phase 6
foundation rather than patching each Tool independently.

35. Plan acceptance checklist
-----------------------------

The Phase 6 detailed plan is acceptable when review/CI confirms:

* scope is exactly the registered Binnacle source workspace + development session;
* no ambient absolute-path/system/credential/policy/broker authority is introduced;
* session authority semantics follow the owner-approved design and the current HC0/HC1
  conflict is explicitly named as a promotion prerequisite rather than silently ignored;
* all proposed operational Tools are absent until reviewed contracts/schemas/manifest and
  host-profile reconciliation pass;
* read/search operations are bounded and symlink-safe;
* mutations use exact current identity/version semantics and descriptor-relative
  containment;
* the conservative one-workspace mutation fence closes Binnacle-managed concurrency and
  uncertainty safely;
* Phase 4 audit/idempotency/final-boundary ordering is preserved exactly;
* retained same-key retry is evaluated before mutable session/filesystem freshness checks;
* session loss before start produces no effect while post-start loss never rewrites truth;
* create/write/patch/move/delete effect/no-effect/uncertain outcomes are representable and
  restart-reconcilable;
* external local filesystem races are acknowledged rather than hidden by false atomic-CAS
  claims;
* no Raspberry Pi or ChatGPT support fact is fabricated.

36. Implementation/promotion checklist
--------------------------------------

Implementation/promotion remains blocked until:

* real Phase 5 implementation/exit and write-confirmation evidence are current;
* the session-scoped host-authority contract/profile is reviewed and the selected real
  ChatGPT profile passes it;
* the exact Phase 6 operation contracts/schemas/manifest are promoted and validated;
* migration ``0003`` and all persistence constraints pass fresh/upgrade tests;
* session/fence/idempotency/audit/final-boundary fault tests pass;
* Linux containment/search/mutation tests pass on the candidate Pi profile;
* production composition exposes no Phase 6 Tool when any prerequisite fails.

37. Real Phase 6 exit criteria
------------------------------

Do not mark Phase 6 implementation complete until real evidence proves at least:

#. the owner-authorised development session is started and visible to real ChatGPT under
   the reviewed HOST profile;
#. ChatGPT inspects/lists/reads/searches the exact registered Binnacle workspace;
#. ChatGPT performs one controlled source edit with the promoted mutation contract;
#. the new file/object version and content digest are inspected truthfully;
#. ChatGPT reverts/replaces the edit with exactly one admitted effect;
#. same-key retry does not create a duplicate effect;
#. no operation can escape the registered workspace or protected internal paths;
#. session end/expiry blocks new mutations;
#. reconnect/restart preserves or truthfully rejects the session according to the frozen
   identity/time rules;
#. all evidence is captured from the real Pi/ChatGPT rather than inferred from tests.

38. Implementation order
------------------------

When the evidence gate permits implementation, use this order:

#. reconcile and promote the session-scoped host-authority contract/profile;
#. define/review all Phase 6 operation contracts and input/output schemas;
#. update manifest/docs/evaluation fixtures and pass contract/schema/manifest validation;
#. add migration ``0003`` for sessions/workspace operation metadata/mutation fence;
#. implement domain types and persistence repositories;
#. implement registered workspace profile/root identity verification;
#. implement descriptor-relative read/list/read primitives;
#. implement typed ``ripgrep`` search;
#. implement development-session begin/inspect/end orchestration;
#. implement the conservative workspace mutation fence and final-binding callback;
#. implement create and its fault/reconciliation tests;
#. implement write + shared replacement adapter and fault/reconciliation tests;
#. implement deterministic patch on top of replacement;
#. implement move and delete;
#. integrate exact Phase 4 audit/idempotency/OP-BOUNDARY/effect-knowledge semantics;
#. wire MCP handlers only after registry/contract parity passes;
#. run unit/property/Linux/fault/restart/security test suites;
#. deploy to the candidate Pi only after local/CI gates pass;
#. collect real ChatGPT evidence without converting missing observations into support.

39. Explicit provisional items
------------------------------

The following remain provisional/evidence-gated after this plan merges:

* exact real ChatGPT UI/interaction used to establish the bounded development session;
* whether the selected HOST profile can support the reviewed session-scoped authority
  semantics at all;
* exact selected confirmation-profile identifier if promotion review rejects the proposed
  ``HCS1`` name while retaining the same semantics;
* actual Pi filesystem/kernel behaviour for the selected no-replace and durability
  primitives;
* actual ``ripgrep`` version/performance ceilings on the development Pi;
* exact real-host result-size/catalogue-refresh behaviour where it affects promoted
  schemas/limits.

Those items may change host/profile-specific implementation choices or limits. They must
not change the frozen local authority boundary, durable-operation ordering, truthful
uncertainty rule, or prohibition on workspace escape without a separately reviewed design
revision.

40. Deferred work
-----------------

Phase 6 intentionally defers:

* arbitrary workspace registration/mutation by ChatGPT;
* multiple simultaneous mutating operations per workspace;
* recursive delete and non-empty directory tree move;
* symlink-following development operations;
* generic chmod/chown/xattr/ACL manipulation;
* very-large-file streaming mutation;
* repository indexing/vector search;
* shell command execution;
* semantic Git operations/credentials/signing;
* privileged host changes;
* advanced namespaces/seccomp/MAC/container sandboxing;
* post-Bootstrap multi-user/project workspace policy.

Add those only when they block the self-hosting loop or later evidence justifies a
separately reviewed capability.
