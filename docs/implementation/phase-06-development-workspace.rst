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
                       services, descriptor-relative Linux containment, descriptor-pinned
                       and configuration-disabled ``ripgrep`` search, protected-object
                       alias rejection, shared content/change coordination, durable Phase 4
                       consequential-operation integration for mutations, session/start and
                       content-admission linearization, bounded MCP contract/schema/manifest
                       promotion, tests, deployment permissions, and evidence gates only

Purpose
-------

Phase 6 crosses from the disposable Phase 5 probe into the first real source-development
capability. It lets ChatGPT inspect and modify the registered Binnacle repository through
semantic workspace operations while keeping the network-facing Binnacle application
unprivileged and preserving permanent boundaries around credentials, protected
configuration, policy, privileged state, and arbitrary host administration.

The phase separates three facts:

* an owner-authorised development session grants broad normal developer authority inside
  the registered Binnacle source workspace;
* every consequential file mutation still consumes the Phase 4 durable operation,
  idempotency, audit, policy, final-boundary, effect-knowledge, and reconciliation kernel;
* whether the selected real ChatGPT host can represent the owner-visible bounded session
  semantics without redundant per-file confirmations remains empirical HOST-profile
  evidence and is not guessed here.

This document freezes evidence-independent local architecture and algorithms only. It does
not claim that the current ChatGPT product exposes the proposed Phase 6 Tools, that a
particular host confirmation UI exists, that the development Pi already satisfies the
required filesystem/process primitives, that ``ripgrep`` supports a particular option on
the candidate Pi, or that real Phase 5 write evidence has passed.

``:Status: merged`` denotes the terminal authoritative state of this numbered plan after
planning review and CI acceptance. Before that acceptance the document is proposed.

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

``docs/design-principles.rst`` supersedes conflicting older V17 detail. Its owner-approved
development-session decision governs over older text that would require a separate owner
approval for every ordinary source-development step.

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
* the registered workspace profile/root identity are configured outside the source
  workspace and pass local filesystem verification;
* the selected Pi/runtime proves every required descriptor-relative, no-overwrite,
  hard-link/link-count, process-lifecycle, and search primitive used by an exposed
  operation;
* content-returning read/search is promoted only under the reviewed coordinated-writer
  model plus the shared access gate, or a stronger reviewed protected-object confinement
  mechanism; link-count semantics must be reliable enough to enforce the conservative
  no-hard-link content rule in sections 10, 14, and 15;
* the candidate ``ripgrep`` binary proves the exact configuration/preprocessor/archive
  disabling options used by the typed adapter, and the child receives only the reviewed
  sanitized environment; otherwise ``workspace_search`` remains disabled;
* the candidate systemd deployment proves the search-child lifecycle/readiness barrier in
  sections 15, 16, and 25: an ``rg`` child or helper cannot survive an application service
  restart into a newly opened workspace access gate;
* mutations whose required primitive or writer assumption is unavailable stay disabled
  rather than silently degrading;
* the proposed Phase 6 operation contracts, JSON schemas, Tool-manifest entries,
  descriptions, annotations, information classes, and host-confirmation metadata have
  passed contract/schema/manifest validation;
* runtime composition keeps all Phase 6 Tools invisible/disabled whenever those
  prerequisites are absent, stale, contradictory, or unsupported.

Planning text never substitutes for those observations.

2.3 Phase exit gate
~~~~~~~~~~~~~~~~~~~

The roadmap exit remains empirical. Real ChatGPT must inspect the registered Binnacle
repository, make one controlled source edit, inspect the resulting file, and revert or
replace it without affecting unrelated paths.

Reviewed evidence must additionally demonstrate development-session begin/inspect/end or
expiry semantics, no workspace escape, bounded read/search behaviour, exact mutation
idempotency, reconnect behaviour, and truthful failure/uncertainty handling.

3. Exact Phase 6 authority boundary
-----------------------------------

Phase 6 grants normal developer file authority only inside one reviewed registered
Binnacle source workspace. Conceptually the Bootstrap workspace is:

::

   /srv/binnacle-dev/repo

The exact path is owner configuration, not model-controlled input.

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
* symlink-following content access or mutation;
* hard-link creation or content access through multiply-linked regular files;
* direct ``.git`` database/object/reference content access or mutation through workspace
  Tools;
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
credential use, and Phase 9 owns privileged self-management. Any Phase 7 or Phase 8 effect
that can mutate this workspace must coordinate with the authoritative access/change seam in
section 16 and must preserve the protected-content/non-alias information boundary before
content readiness can reopen. Later phases may extend the contract but must not create an
independent writer lane.

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
reviewed. The implementation should normally keep the existing schema family where
compatible and bump ``manifest_version`` because the reviewed catalogue changes. If all
12 proposed Tools are accepted, the Bootstrap manifest grows from 8 to 20 exact entries.

Before any handler exposure, implementation promotion is:

#. reconcile ``docs/mcp-host-confirmation.md`` and
   ``spec/policy/host-confirmation-classes.yaml`` with the bounded development-session
   authority semantics in section 5;
#. define/review the 12 operation contracts and exact input/output schema definitions;
#. define information classes, annotations, result limits, errors, and capability/profile
   requirements;
#. update ``spec/mcp/bootstrap-tool-manifest.yaml`` and manifest documentation;
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
development session for the same development objective. Once that session is active and
**effective**, ChatGPT may perform ordinary source-development work inside the registered
source workspace without asking the owner to repeat the same approval for each read,
write, patch, move, or delete.

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
* host metadata, Tool annotation, model prose, or possession of a session identifier never
  creates local authority;
* the selected real ChatGPT HOST profile remains unsupported for Phase 6 if it cannot
  safely express/demonstrate the bounded session model.

The actual ChatGPT interaction may be a one-time owner-visible confirmation, an explicit
session-start interaction derived from the owner request, or another host-native mechanism.
That mechanism is empirical and is not invented here.

5.2 Information-class consequence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Workspace metadata can normally be ``normal-result``. Source file contents and search
matches are conservatively ``restricted-result`` unless the reviewed workspace profile
explicitly proves a narrower public-information classification.

The session-scoped host profile must therefore cover ordinary source-workspace mutation
authority and bounded source-content disclosure without repeated per-file owner prompts.
Reusable credentials and protected state remain ``never-disclosable`` and are outside the
workspace profile rather than relying on content scanning.

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

   class ActivationClosure(StrEnum):
       PENDING = "pending"
       COMPLETE = "complete"

   @dataclass(frozen=True, slots=True)
   class DevelopmentSessionSnapshot:
       session_id: str
       state: DevelopmentSessionState
       state_version: int
       activation_closure: ActivationClosure
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

``effective_for_new_work`` is derived, not merely ``state == ACTIVE``. It is true only when
the exact session is ``ACTIVE``, ``activation_closure == COMPLETE``, trusted time is valid
and before deadline, controller/device/workspace/profile/policy facts remain exact, no
explicit end/revocation won the session gate, and global consequential readiness is healthy.

One **live session slot** per exact device epoch + registered workspace is sufficient for
Bootstrap. ``PENDING`` and ``ACTIVE`` both occupy that slot, regardless of activation-
closure state. Migration ``0003`` enforces this independently in SQLite with a partial
unique index equivalent to::

   CREATE UNIQUE INDEX uq_development_sessions_live_workspace
       ON development_sessions(device_id, device_epoch, workspace_id)
       WHERE state IN ('pending', 'active');

The constraint is the durable overlap-prevention invariant, not an application pre-check.
A concurrent distinct begin request cannot create a second ``PENDING`` row while the first
activation is in flight. Same-key retry resolves the retained begin operation before
slot/current-state checks; a distinct key that loses the slot race receives a bounded
non-disclosing ``development_session_slot_busy``/already-pending-or-active outcome and
creates no second authority-state effect. A different controller also cannot create an
overlapping live session for the same device/workspace merely because ownership changed.

The slot is released only by a truthful terminal session transition to ``ENDED``,
``EXPIRED``, or ``REVOKED``. Ambiguous/incomplete activation keeps the ``PENDING``/``ACTIVE``
row live and the slot reserved fail-closed. Startup treats multiple live rows for one slot
as integrity failure; it never picks one or rebuilds slot ownership from mutable source
state.

The free-form owner objective is not executable policy. The implementation stores a
bounded safe label where useful plus a canonical digest for provenance. Binnacle does not
try to decide whether every later source edit is semantically part of the objective; the
session grants the reviewed broad workspace capability and ChatGPT remains the reasoning
agent.

7. Session authority gate, lifetime, restart, and revocation
------------------------------------------------------------

7.1 ``DevelopmentSessionAuthorityGate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 6 adds one application-level authority gate per current development session. It is a
correctness primitive, not a cache and not a substitute for durable session state.

The gate serializes:

* a content-returning read/search about to establish its one process-local content permit;
* a member mutation about to cross ``EffectBoundary.start``;
* explicit session end/revocation;
* trusted-time expiry becoming effective for new work;
* startup/recovery reduction caused by controller/device/workspace/profile/policy/time
  discontinuity.

The global application lock order is fixed as:

::

   WorkspaceAccessGate
     -> Phase 4 per-operation dispatch handoff, when consequential
     -> DevelopmentSessionAuthorityGate
     -> Phase 4 process-wide ConsequentialBoundaryGate, when consequential

Content read/search uses only ``WorkspaceAccessGate CONTENT_READ ->
DevelopmentSessionAuthorityGate`` from that chain. A mutation already owns exclusive
``CHANGE`` before it later enters Phase 4 handoff/session/process gates. Session
end/revocation acquires the session gate directly and **never** reaches back to acquire
``WorkspaceAccessGate``. Recovery/access-gate transitions likewise never acquire a session
gate while holding a later gate in reverse order. Tests fail on any inversion.

For content read/search, initial session checks before waiting for ``CONTENT_READ`` are
advisory freshness checks only. After the shared content guard is acquired, the application
acquires the exact session gate and re-samples trusted time plus controller/device/session
state+version/activation closure/workspace/profile/root/protected-content policy. Only an
exact still-effective session may create a bounded process-local ``ContentReadPermit``
bound to exact session state/version, profile/root identity, request digest, and current
content-guard epoch. No source bytes are opened/returned and no ``rg`` child is spawned
before that permit exists.

Permit creation while content guard + session gate are held is the content-admission
linearization point. The session gate may then be released while the shared content guard
remains held for the full file read or search traversal. If end/revocation/expiry/recovery
reduction wins first, the reader releases its content guard and returns no source content.
If content admission wins first, later reduction blocks new admission but does not
retroactively interrupt/reclassify the already-admitted bounded no-effect request. The
permit is non-durable, non-transferable, non-reusable, and dies with its exact guard/runtime.

For a member mutation, the session gate is held from final trusted-time/session predicates
through final Phase 4 revalidation, durable audit-obligation publication, and process-wide
gate-owned ``call_start``. It is released only after bounded start handoff either definitely
did not occur or linearized and immediate effect-receipt/knowledge classification completed.

Thus:

* authority reduction wins session gate before start -> no ``EffectBoundary.start``;
* member ``call_start`` wins while gate still proves exact effectiveness -> effect is
  already started/committed-to-start before later reduction, which cannot rewrite effect
  truth.

Expiry is not a timer callback. Every session-gate entry samples Phase 4 trusted time under
the same critical section. Reached or unverifiable deadline makes
``effective_for_new_work=false`` before a new mutation/content admission may linearize.
Persistence of ``EXPIRED`` may follow; persistence delay cannot extend authority.

7.2 Trusted-time binding
~~~~~~~~~~~~~~~~~~~~~~~~

Session lifetime uses the Phase 4 trusted-time model. Store enough evidence to enforce
expiry across ordinary restart:

* ``expires_at``;
* trusted-time generation at activation;
* activation boot identity digest;
* same-boot monotonic deadline where available;
* controller/device/workspace/profile/policy snapshots.

A reasonable Bootstrap configuration is a one-hour default with a hard maximum of four
hours. Exact schema limits are frozen during contract promotion and cannot be enlarged by
model-controlled input beyond the reviewed maximum.

Clock rollback, reboot with untrusted wall time, or lost trusted-time continuity never
extends a session. If expiry cannot be proved safely, the session is ineffective for new
mutations and new content-returning admissions.

7.3 Ordinary Binnacle restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An ordinary MCP/application restart does not by itself end a session. Startup may restore
a session effective only when all exact identity/profile/policy/time predicates verify and
activation closure is durably complete.

This supports the Bootstrap self-hosting loop without forcing the owner to repeat the same
session approval solely because the MCP process restarted.

The in-memory session gate is reconstructed from authoritative session rows plus current
trusted predicates. It never converts an ``ACTIVE`` row with incomplete activation closure
into authority.

7.4 End, expiry, and revocation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

End/expiry/revocation:

* prevents new member admission, including content read/search, and any not-yet-started
  consequential member from crossing its final effect boundary;
* never rewrites, erases, duplicates, or blindly cancels an already-linearized mutation or
  already-admitted bounded no-effect content request.

If reduction wins before mutation start, the mutation closes proven-no-effect and releases
its workspace fence only after normal Phase 4 audit/recovery closure. If start wins, later
end never manufactures ``known_no_effect``. Same-key retry after session end returns the
retained operation/result/uncertainty before mutable session checks and never creates a
second effect.

8. Session begin/inspect/end application semantics
--------------------------------------------------

8.1 ``development_session_begin``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session begin is consequential authority-state mutation even though it writes no source
file.

First-use ordering is:

#. authenticate owner/controller and normalize workspace/objective/duration;
#. resolve existing caller-key binding before mutable session/current-state checks;
#. create minimal Phase 4 ``received`` identity and required received audit;
#. evaluate policy against exact observed no-live-slot/current-state facts;
#. after allow, in one short post-policy transaction re-prove operation/controller/device/
   workspace/profile/time and live-slot freedom;
#. atomically insert exact self-owned ``PENDING`` session row with ``begin_operation_id`` +
   trusted deadline, persist one current allow decision, and commit
   ``received -> authorised``; the partial unique index is final race arbiter;
#. bind expected self transition as
   ``session_slot_transition=free_then_exact_self_pending``;
#. fsync required allowed/authorised audit and move operation to ``running``;
#. record activation intent and final-revalidate controller/device/workspace/profile/
   policy/time/slot;
#. publish Phase 4 audit obligation and perform exact ``PENDING -> ACTIVE`` with
   ``activation_closure=PENDING``;
#. retain effect knowledge/reference and fsync required post-effect activation audit;
#. only after audit success, obligation closure, and exact identity revalidation may a
   short CAS set ``activation_closure=COMPLETE``;
#. only ``ACTIVE`` + ``COMPLETE`` makes session gate effective for member work.

A distinct begin losing the slot race creates no second ``PENDING`` or authority effect;
it follows a bounded non-disclosing no-effect busy/rejection path. It never waits and
attaches to another session.

The session gate remains closed to member starts/content admission throughout activation
until the closure CAS succeeds. Post-effect audit/obligation/CAS failure leaves session
ineffective. Restart may complete activation only from exact retained operation/effect/audit
and obligation evidence, never from host UI/model text or ``ACTIVE`` row presence alone.

A pre-effect activation failure frees the slot only after durable ``known_no_effect`` plus
required audit/recovery truthfully terminalizes the exact ``PENDING`` row. Once authority
state may have started or is known to have occurred, incomplete/uncertain closure keeps the
slot fail-closed until exact reconciliation or explicit authority reduction.

8.2 ``development_session_inspect``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inspect is bounded/read-only. Owner may inspect current/terminal session metadata,
effective/closure/expiry/trusted-time status, workspace ID/profile digest, and bounded
reason codes. It reveals no credential, policy body, protected path, raw audit bytes, or
source content.

8.3 ``development_session_end``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

End is authority reducing. It acquires exact session gate before changing durable authority
state. Once terminal reduction wins, no later member mutation start or content permit can
begin.

Reduction is fail-safe: inability to append the required end audit must not leave authority
active merely to make audit ordering convenient. Durable ``ACTIVE -> ENDED``/``REVOKED``
reduction takes effect under the gate; subsequent audit failure places global
consequential admission into Phase 4 fail-restricted recovery while the session remains
reduced. Activation and revocation are intentionally asymmetric: activation withholds
authority until audit closure; revocation removes authority first.

A member whose mutation ``call_start`` or content permit already won before end remains
in-flight/admitted and is not reclassified. Same-key end retry returns retained end work.
A new request against an already terminal session may return bounded already-ended state
with no new effect.

9. Registered workspace profile and protected configuration
-----------------------------------------------------------

Workspace registration is protected configuration/control-plane state. Phase 6 Tools may
consume but never create/change/broaden/delete a workspace registration.

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
       allow_out_of_band_writers: bool = False
       move_enabled: bool = False
       delete_enabled: bool = False

Exact production profile lives under protected configuration such as ``/etc/binnacle``
and loads into an immutable resolved settings snapshot. Model input selects a registered
``workspace_id`` only; it cannot redirect root or weaken safety settings.

``allow_out_of_band_writers`` records a reviewed deployment assumption; it never turns
pathname operations into inode CAS. When true, content read/search stays disabled unless a
stronger reviewed mechanism preserves protected-object exclusion throughout traversal.
When false, ``WorkspaceAccessGate`` coordinates Binnacle-managed changers and the reviewed
deployment must establish that other writers do not bypass the model.

Content promotion also requires reliable regular-file link-count semantics. Binnacle
conservatively rejects content-bearing access/mutation for a regular file whose descriptor
reports ``st_nlink != 1``. If the candidate filesystem cannot supply trustworthy link-count
facts, content-returning read/search and affected mutations stay disabled rather than
assuming hard-link aliases cannot exist.

At session activation Binnacle opens/verifies root and records a protected root-identity
digest from exact descriptor-visible filesystem/directory identity plus workspace/profile
digest. Every later operation reopens configured root and proves the same identity before
content return or mutation. Root path replacement, symlink substitution, bind/profile
change, or unverifiable root identity makes session ineffective; Binnacle never silently
rebases the session onto a newly observed tree.

10. Workspace-internal protected boundaries and alias invariant
---------------------------------------------------------------

The source checkout includes normal source plus internal/protected objects. Phase 6 must
not turn every byte below the root string into identical authority.

At minimum, the reviewed profile excludes **content-returning access and mutation** for:

* ``.git/`` -- Phase 8 semantic Git owns repository metadata/credential use;
* explicitly registered project-local credential/private-key material;
* paths mapped to protected Binnacle config/state/audit/control-plane storage;
* deployment-specific protected paths added by owner profile.

``workspace_read``/``workspace_search`` reject those paths; path-prefix filtering is not
sufficient by itself. A regular file can be a hard-link alias of another pathname. Phase 6
therefore adopts the conservative rule:

* no content-bearing Phase 6 operation reads, searches, replaces, moves, or deletes a
  regular file whose descriptor-visible ``st_nlink`` is not exactly 1;
* direct read checks the opened target descriptor after the content permit and before any
  bytes are returned;
* recursive search performs a descriptor-relative bounded alias preflight of the exact
  admitted search scope while ``CONTENT_READ`` is held and rejects the whole search if any
  search-eligible regular file is multiply linked or link-count state is unverifiable;
* the preflight is bounded by a reviewed entry/time ceiling; exceeding the ceiling is a
  fail-closed search-degraded result, not permission to skip the alias check;
* Phase 6 exposes no hard-link creation operation;
* every Phase 6 mutation revalidates single-link status for an existing regular-file
  source immediately before its effect boundary;
* future Phase 7/8 workspace changers consuming the shared ``CHANGE`` seam must preserve
  the same information boundary. A future contract that can access protected content may
  not declassify it into the content-visible namespace or create an alias bypass and then
  reopen content readiness without its own reviewed information-boundary proof.

The no-uncoordinated-writer profile plus shared access gate makes a successful alias
preflight stable for that admitted read/search: Binnacle-managed changes cannot introduce a
hard link while ``CONTENT_READ`` is held. A profile permitting uncoordinated writers cannot
promote content access merely by checking ``st_nlink`` once; it requires a stronger
reviewed confinement mechanism.

Protection must remain stable for the **entire** content traversal. A Binnacle-managed
changer cannot rename/exchange protected directories beneath allowed names because content
operations hold shared ``WorkspaceAccessGate`` and every changer holds exclusive
``CHANGE``. ``ripgrep`` ignore/path filters are defense in depth, not the security boundary.

``workspace_inspect``/``workspace_list`` may expose bounded non-sensitive metadata for a
protected entry only when the promoted contract explicitly permits it; they never expose
protected bytes, sensitive link targets, or reusable authority material.

``.github/``, ``docs/``, source, tests, ``pyproject.toml``, ``uv.lock``, lint/test config,
and ordinary repository files are normal source content subject to the alias rule.

The implementation never relies on heuristic secret scanning as the security boundary.
Reusable secrets belong outside workspace or explicit protected exclusions. Source content
returned to ChatGPT remains conservatively classified as section 5.2 specifies.

11. Canonical workspace path model
----------------------------------

One normalizer owns all path-bearing workspace contracts. Canonical input is a
workspace-relative POSIX-style path with:

* UTF-8 and NFC normalization;
* no leading ``/`` or drive/UNC prefix;
* ``/`` only; backslash rejected rather than reinterpreted;
* no empty/``.``/``..`` component, NUL, CR, LF;
* Linux component limit, reviewed full-path and depth limits;
* reserved Binnacle staging names/prefixes rejected;
* protected-prefix policy checked before content return or mutation;
* semantic target established only after descriptor-relative resolution.

String normalization never proves containment.

12. Descriptor-relative Linux containment
-----------------------------------------

Security uses Linux descriptor-relative operations rather than ``Path.resolve()`` or
string-prefix checks.

Bootstrap may prefer ``openat2`` with exact ``RESOLVE_BENEATH`` /
``RESOLVE_NO_MAGICLINKS`` / ``RESOLVE_NO_SYMLINKS`` semantics when a small reviewed
implementation is available. Required baseline remains race-resistant descriptor walking:

* open/pin registered root descriptor and compare exact session/profile identity;
* walk directory components relative to open descriptors using ``dir_fd``,
  ``O_DIRECTORY`` and ``O_NOFOLLOW``;
* metadata checks use ``follow_symlinks=False``;
* final open/link/rename/unlink/mkdir/rmdir through pinned parent descriptors;
* content-bearing regular-file opens additionally require exact ordinary-file type and
  ``st_nlink == 1`` under the reviewed filesystem profile;
* never follow a workspace symlink during content read or mutation;
* close descriptors deterministically.

A narrowly reviewed internal ``/proc/self/fd/<n>`` reference may be used **only** to bind a
trusted subprocess such as ``ripgrep`` to an already-pinned descriptor. It is not a model
path and does not relax workspace magic-link rejection.

Inspect/list may report symlink metadata where explicitly reviewed, but read/search
traversal and all Phase 6 mutations reject symlink-as-content/effect targets.

13. Stable object/version identity
----------------------------------

Read/inspect output returns bounded opaque ``object_version`` for regular files and
explicit directories. Token binds at least:

* workspace/profile/root identity;
* normalized path;
* object type;
* descriptor-observed filesystem/inode identity;
* relevant mode/size/time/link-count facts;
* for mutable regular files, exact full content SHA-256 within mutation ceiling.

Token is not authority. Replacement/delete/move inputs supply exact expected token and
where required content SHA-256. Stale/changed/multiply-linked existing regular file fails
before effect start.

Files exceeding mutation/hash ceiling may remain readable in bounded chunks but are not
directly mutable until separately reviewed larger-file contract exists.

Object identity is exact evidence at observation, not inode-conditional syscall CAS.
Section 23 scopes residual out-of-band-writer race.

14. Read-only workspace operations
----------------------------------

All read-only operations require authenticated owner/controller, exact registered
workspace, and effective development session unless promoted contract explicitly defines a
smaller safe metadata exception.

They create no consequential Phase 4 operation merely for bookkeeping but enforce bounds,
session/workspace authority, information class, protected paths/aliases, redaction, rate/
resource limits, and read-audit/diagnostic policy.

Metadata-only inspect/list that depends on session performs a final session/profile/time
freshness check immediately before protected result projection. It returns no source bytes
and need not acquire content guard solely for metadata.

Content-returning operations are stricter:

#. an early session check may reject obvious stale calls but is advisory only;
#. acquire shared ``WorkspaceAccessGate.CONTENT_READ`` only after durable mutation fence is
   free and startup recovery is complete;
#. while guard is held acquire ``DevelopmentSessionAuthorityGate`` and re-prove exact
   effective session, trusted time, controller/device, workspace/profile/root identity,
   request binding, protected-content policy;
#. mint one process-local request/guard-bound ``ContentReadPermit``;
#. only after the permit exists open candidate source content;
#. for each directly opened regular file require descriptor-visible ``st_nlink == 1``;
#. retain content guard until direct read finishes or search preflight/child traversal/
   output drain/termination fully completes.

If session reduction wins before permit, release guard and return no source content/no
search child. Permit winning first authorizes only that already-admitted bounded no-effect
request; later end blocks later admission but does not retroactively reclassify it.

``workspace_read`` opens one exact non-protected regular file after permit, checks exact
single-link ordinary-file identity, and returns bounded range/chunk plus object version,
content digest where available, encoding/media and continuation/truncation facts. Binary
content is never silently decoded as text.

``workspace_list`` traversal is descriptor-relative/no-follow, bounded by depth/entries/
output, and truthfully marks truncation. Protected metadata is exposed only if contract
allows it.

15. Descriptor-pinned, configuration-disabled typed ``ripgrep`` adapter
-----------------------------------------------------------------------

``workspace_search`` uses mature ``ripgrep`` behind a typed adapter rather than a custom
repository index or Python regex walk.

Explicit argv alone is not enough: ripgrep can load configuration from
``RIPGREP_CONFIG_PATH`` and some optional modes can invoke preprocessors/decompression
helpers. Phase 6 therefore treats **process purity** as part of the search security
boundary.

The exact executable is an owner-profile-resolved absolute path. Child environment is
constructed from a minimal closed allowlist needed for deterministic execution/locale; it
never inherits the service environment wholesale and specifically excludes
``RIPGREP_CONFIG_PATH``, ``HOME``, credential/helper variables, Python/runtime injection
variables, proxy/agent variables not required by this no-network search, and every
Binnacle control-plane value. The adapter explicitly supplies and the candidate binary must
prove support for options equivalent to:

* ``--no-config`` -- do not load ripgrep configuration;
* ``--no-pre`` -- no per-file preprocessor command;
* ``--no-search-zip`` -- no decompression helper subprocess;
* ``--no-follow`` -- never follow symlinks;
* ``--json`` -- structured output.

No caller option may negate those mandatory flags. If the selected ripgrep version cannot
prove those disabling semantics, ``workspace_search`` is not promoted for that profile.
The adapter never invokes a shell and never enables PCRE2, preprocessor, archive-search,
external pager, or another helper-spawning mode in Bootstrap.

Before spawn, search also proves the protected-object alias invariant. While the shared
``CONTENT_READ`` guard and exact ``ContentReadPermit`` are held, Binnacle performs a
bounded descriptor-relative preflight over the exact admitted search directory. Every
search-eligible regular file must be an ordinary non-symlink file with reliable
``st_nlink == 1``. A multiply-linked file, alias-scan ceiling, unsupported link-count
semantics, or ambiguous entry fails the search **before** ``rg`` starts. Under the reviewed
coordinated/no-out-of-band-writer model the shared guard keeps that preflight stable for the
full traversal. A profile that permits uncoordinated writers needs a stronger reviewed
confinement mechanism and cannot rely on this preflight.

The launch sequence is:

#. normalize optional search subpath and reject protected/symlink-bearing scope;
#. verify writer/confinement + hard-link/link-count profile;
#. require current service invocation to pass ``SearchChildRecoveryBarrier``;
#. acquire shared ``CONTENT_READ`` and atomically require durable mutation fence free;
#. under that guard acquire session gate, revalidate exact trusted/session/controller/
   device/profile/root/protected policy and mint ``ContentReadPermit``;
#. descriptor-walk the admitted search scope and complete the bounded single-link alias
   preflight;
#. open/pin exact registered root and exact search-directory descriptor and verify
   permit-bound identities;
#. duplicate pinned search FD to an operation-owned inherited FD;
#. spawn absolute ``rg`` executable with ``close_fds=True`` and only that FD explicitly
   inherited, using only the closed sanitized environment and mandatory disabling flags;
#. keep child in exact Binnacle application systemd service cgroup; no ``systemd-run``,
   delegated scope, double-fork/daemon escape, preprocessor/helper, or archive-helper path;
#. establish child cwd from pinned descriptor via reviewed internal procfd/helper and pass
   ``.`` as the only search root; never pass configured root/reconstructed subpath;
#. retain process handle binding PID + non-reused identity such as start-time/pidfd +
   current application service invocation identity;
#. keep inherited descriptor through exec/cwd establishment then close parent copies;
#. hold content guard through traversal, timeout/termination and bounded stdout/stderr
   drain, releasing only after pidfd/wait-style proof that ``rg`` is reaped **and** no
   operation-attributable descendant/helper remains able to traverse the workspace.

The service unit retains search children in its cgroup and uses
``KillMode=control-group`` + ``SendSIGKILL=yes`` or reviewed stronger lifecycle. ``Delegate``
is not granted for this purpose. A bounded stop timeout is part of deployment profile.
Parent-death signalling may be defense in depth but is never sole restart invariant.

Every fresh application invocation starts ``SearchChildRecoveryBarrier`` before
``WorkspaceAccessGate`` may leave ``RECOVERY_CLOSED``. Barrier verifies exact unit/cgroup
identity and proves no process from prior invocation remains able to traverse a pinned
workspace descriptor. Service-manager state may be combined with cgroup membership,
process start-time/pidfd, and current systemd invocation identity. Stale/foreign/
unverifiable state keeps both ``CONTENT_READ`` and ``CHANGE`` closed. Barrier never clears
a durable mutation fence.

Configured root/search-directory replacement cannot redirect child because traversal is
against pinned object. Binnacle-managed Phase 6/7/8 changer cannot relabel protected dir
while search runs because exclusive CHANGE cannot overlap CONTENT_READ. Uncoordinated
writers remain fail-closed without stronger confinement.

Additional typed search bounds include closed pattern/case/fixed-string options, Rust
regex/default engine only, file/match/output/per-file byte ceilings, hard timeout, binary
skip, hidden handling sufficient for normal ``.github`` while protected ``.git`` excluded,
reviewed ignore behaviour, bounded stdout/stderr, and truthful truncation/timeout.

Mandatory adversarial tests include service-level ``RIPGREP_CONFIG_PATH`` containing
``--pre=<sentinel command>`` and config options that attempt archive/helper execution. The
sentinel must never execute, mandatory no-config/no-pre/no-search-zip flags must remain
present, the child environment must omit the config variable, and no unexpected descendant
may survive search completion/restart.

16. Shared workspace access/change coordination seam
----------------------------------------------------

Phase 6 deliberately chooses conservative concurrency. At most one consequential
Binnacle-managed workspace-changing effect owns registered workspace fence at a time.
Metadata-only inspect/list may remain concurrent; content read/search may share with other
content readers but not a Binnacle-managed changer.

One per-workspace ``WorkspaceAccessGate`` supplies linearization:

* ``CONTENT_READ`` is shared, available only while durable mutation fence is free and
  startup search-child recovery complete. Acquisition is not authority: while guard held,
  caller next acquires session gate, revalidates exact effective session, mints request-
  bound ``ContentReadPermit``, and then performs direct single-link check or search alias
  preflight before source bytes/search child;
* ``CHANGE`` is exclusive. New mutation acquires it **after policy allow but before**
  durable workspace fence and retains until fence truthfully released. ``uncertain`` keeps
  durable fence owned and access gate/recovery change-closed;
* lock order is ``WorkspaceAccessGate -> per-operation dispatch handoff (if
  consequential) -> DevelopmentSessionAuthorityGate -> ConsequentialBoundaryGate (if
  consequential)``. Session reduction never acquires workspace access after session gate;
* one coordinator orders acquire/release so no reader sees fence free while changer enters
  ownership and no changer acquires durable fence while content guard active;
* every application invocation initializes ``RECOVERY_CLOSED`` and opens only after exact
  search-child recovery + durable-fence reconciliation. Retained fence owner keeps change
  closed. Unknown prior search child keeps both modes closed.

Gate is not authority and cannot make out-of-band writers cooperate. ``ContentReadPermit``
is only ephemeral proof of exact request/session admission while exact guard is held.
Content operations therefore require coordinated writer profile or stronger confinement.

The word **changing** includes later Phase 7 commands and Phase 8 Git operations whenever
their contract may change workspace. Those phases must consume this seam and additionally
preserve the protected-content/non-alias information boundary. A future changer with access
to protected content cannot copy/link/declassify it into normal content and simply release
CHANGE; its own contract must prove the required information-boundary closure or leave
content readiness closed.

Migration ``0003`` introduces authoritative row conceptually:

::

   workspace_mutation_fences(
       workspace_id PRIMARY KEY,
       fence_version INTEGER NOT NULL,
       active_operation_id NULLABLE UNIQUE,
       active_contract NULLABLE,
       acquired_at NULLABLE
   )

Missing/corrupt row for configured/initialized workspace fails consequential readiness.
Access-gate restart posture derives from row + search-child barrier, but never reconstructs
or clears durable ownership.

Post-policy admission, while exact operation owns exclusive CHANGE, may acquire only:

::

   free fence version N
       -> exact current operation owns fence version N+1

Operation-specific binding represents expected self transition semantically. Final
OP-BOUNDARY accepts only exact self-owned fence + consumed operation binding. Foreign/
missing owner, changed profile, unexpected version fails closed.

Fence release requires truthful terminal/no-effect/effect classification plus required
post-effect audit/obligation/recovery closure. Exclusive access guard releases only after
durable fence release commits. ``uncertain`` retains fence, blocking changing operations
and content until explicit reconciliation. Filesystem appearance/absence never rebuilds or
steals ownership.

17. Mutation first-use ordering and retained retry
-------------------------------------------------

Existing caller-key/global duplicate binding wins first: same owner/key/fingerprint
returns/reconciles retained operation without requiring current session active and with
zero new fence/effect. Different fingerprint conflicts; other owner gets non-disclosing
mismatch; current tombstone gets retired-key outcome.

Only unbound caller first-use continues:

#. authenticate/normalize exact session/workspace/path/content/expected-version;
#. compute effect-bearing fingerprint including session ID and contract inputs, excluding
   mutable observations/policy;
#. atomically create/find global caller record + minimal version-1 ``received`` operation;
#. fsync required ``operation.state_changed(NULL -> received)`` audit before policy;
#. revalidate exact effective session, profile/root, expected source/target and policy
   inputs;
#. policy evaluate;
#. deny -> one decision + ``received -> rejected`` with no fence/effect;
#. allow -> acquire exclusive CHANGE, then short post-policy transaction re-proves exact
   predicates, acquires free durable workspace fence for current op, stores workspace
   binding + one allow decision + ``received -> authorised``; fence failure releases CHANGE
   with zero filesystem effect;
#. fsync required allowed policy + authorised audit;
#. commit ``authorised -> running``;
#. fsync ``effect.intent_recorded``;
#. acquire Phase 4 per-operation handoff;
#. acquire exact session gate;
#. acquire Phase 4 process-wide consequential gate;
#. under gates re-sample time and final all-mode OP-BOUNDARY including exact session/
   closure/controller/device/profile/policy/root/fence/source/target/cancel/audit/recovery;
#. publish/fsync durable audit obligation while session gate held;
#. recheck session/time and process-gate ``call_start`` exact workspace effect;
#. immediately persist bounded receipt/reference/effect knowledge before session gate
   releases;
#. complete post-effect audit/domain closure/obligation cleanup/durable fence release, then
   access-guard release where truthfully safe.

No SQLite transaction spans filesystem effect I/O. Session reduction cannot commit between
final session predicate and later stale start because it shares session gate.

18. Phase-stable mutation current-state binding
-----------------------------------------------

Binding digest includes immutable/request facts + exact current state + only narrow
expected self admission transition:

* session ID/state/version/activation closure expected at admission;
* controller/device identity+epoch;
* workspace/profile/root;
* Tool/contract;
* normalized source/target;
* expected source object/content/type/link-count as applicable;
* expected target absence/object as applicable;
* proposed content digest/bytes as applicable;
* semantic ``workspace_fence_transition=free_N_then_exact_self_N_plus_1``;
* policy/profile facts required by contract.

Final callback reproduces fence component only after raw owner equals exact running op,
version ``N+1``, immutable op/binding matches. Existing regular-file source must remain
single-linked where contract bears content. Session gate proves expected session still
effective at start. No unrelated state normalized away.

19. ``workspace_create``
------------------------

Create kind is explicit ``file`` or ``directory``. No implicit parents; parent exists and
passes descriptor verification.

File:

* final target absent at admission/final boundary;
* bounded content;
* reviewed closed mode such as ordinary ``0644``/``0755``;
* stage complete bytes under exact operation-owned reserved name in target filesystem;
* fsync staged file;
* publish atomic target-no-replace; same-filesystem descriptor-relative hard-link from the
  **staging inode to a previously absent final pathname** may be an implementation
  primitive only when verified, but Phase 6 never exposes user-requested hard-link
  semantics and post-publication the final file must be normalized to the single-link
  contract before content readiness. An implementation may instead use another reviewed
  no-replace primitive that directly preserves single-link state;
* never substitute overwriting rename;
* fsync parent after publication;
* remove/fsync exact operation-owned staging entry only after truthful handling;
* before declaring normal content-ready success, verify final ordinary-file identity and
  ``st_nlink == 1`` after staging link removal. If link cleanup/verification is ambiguous,
  operation remains conservative/uncertain and workspace content readiness stays closed as
  required rather than exposing a multiply-linked artifact.

Staging recovery never broad-globs/prefix-guesses/recursively deletes. Operation retains
exact staging identity/reference. Unknown staging content preserved/reported.

Target appears before no-replace -> proven no-effect conflict. Required primitive absent ->
create-file disabled. Publication/fsync receipt lost -> path presence alone cannot establish
known effect; remains ``uncertain``.

Directory create uses exact descriptor-relative ``mkdir`` + parent fsync; no parent
broadening. Receipt ambiguity conservative.

20. ``workspace_write``
-----------------------

Write is full replacement of one existing **single-linked** regular file, not create-if-
missing or overwrite-without-version.

First input includes exact path, object version, current content SHA-256, bounded text/base64
new content, caller key and session ID. Admission/final boundary require same regular file
identity/content and ``st_nlink == 1``.

Algorithm:

#. create restrictive operation-owned temp regular file same target directory/filesystem;
#. write bounded bytes, verify count/digest, fsync temp;
#. re-stat/read/hash exact target through pinned parent immediately before replacement and
   require expected object/content/single-link status;
#. atomically rename/replace temp inode onto exact target path;
#. fsync parent;
#. retain bounded effect reference with verified new object/content facts.

Preserve reviewed ordinary executable/non-executable mode where safe. Reject special,
setuid/setgid/capability-bearing, unsupported ACL/xattr, wrong ownership, or multiply-linked
targets.

Linux pathname replacement is not inode CAS against uncooperative external writer between
check and rename. Exact serialization guarantee is for Binnacle-coordinated writers via
shared fence. Immediate revalidation narrows race; post-syscall mismatch/lost receipt is
``uncertain``. Profile must accept writer model or replacement remains disabled.

21. ``workspace_patch``
-----------------------

Patch is deterministic UTF-8 transformation against exact single-linked base. Input binds
base object/content + bounded ordered exact-match replacements. Each match occurs exactly
once against original base and spans do not overlap. Zero/duplicate/overlap/invalid UTF-8/
stale/multiply-linked base rejects no-effect.

Application computes complete new bytes then uses exact ``workspace_write`` adapter path,
inheriting writer/race semantics. Never shells out to ``patch`` and never fuzzy-applies.

22. ``workspace_move``
----------------------

Bootstrap move supports one exact single-linked regular file or one exact empty directory.
Non-empty tree move deferred.

Input binds source object/content/link-count where applicable + exact target absence. Both
inside same registered workspace/filesystem. Cross-device rejects, never copy+delete.

Immediately before syscall final boundary/adapter require exact source and absent target.
Target no-overwrite is atomic via reviewed descriptor-relative primitive such as
``renameat2(..., RENAME_NOREPLACE)``. Normal overwriting rename is never fallback. Required
primitive absent -> move disabled.

Linux cannot atomically require source pathname still names inode X against uncooperative
writer. Fence serializes Binnacle writers; immediate descriptor revalidation narrows race.
Profile accepts cooperative writer model or move disabled. Detected/unprovable mismatch/
lost receipt -> ``uncertain``; target appearance/source absence alone never proves intended
object moved. Fsync distinct source/target parents after proven rename.

23. ``workspace_delete`` and external-writer safety
---------------------------------------------------

Delete supports one existing single-linked regular file with expected object/content or one
exact empty directory with expected object. No recursive/glob/wildcard/implicit cleanup/
delete-through-symlink.

Final descriptor identity and regular-file ``st_nlink == 1`` revalidation immediately
precedes ``unlink``/``rmdir``. Parent fsync is successful completion. Lost receipt + absence
remains ``uncertain`` unless independent durable effect evidence proves deletion.

``unlinkat``/``rmdir`` are pathname operations, not inode CAS. Uncooperative writer can
race final verification. Shared fence prevents Binnacle-managed overlap only. Thus delete
exposes only under reviewed cooperative/exclusive writer model or stronger primitive; else
disabled.

Security claim is no symlink follow, no broadening, all Binnacle writers serialized,
identity checked immediately, multiply-linked regular sources rejected, move target never
overwritten, detected/unprovable race never overclaimed. It is not a claim Linux pathname
syscalls prevent hostile same-UID writer race.

24. Effect knowledge and domain closure
---------------------------------------

Each mutation adapter returns bounded typed receipt only after required filesystem
durability point.

Internal effect reference includes workspace/profile, operation ID, kind, source/target
digests, staging ID if any, verified post-effect object/content/link-count where applicable,
exact durability step, primitive/profile version, receipt digest/version.

Phase 4 operation owns authoritative lifecycle/effect knowledge; Phase 6 rows cannot invent
parallel enum.

* complete exact durability receipt -> eligible ``known_effect``;
* explicit pre-start/no-syscall exact receipt -> eligible ``known_no_effect``;
* lost syscall/fsync receipt, incomplete reference, identity/link-count mismatch, detected
  out-of-band race, or otherwise unprovable -> ``uncertain``;
* final filesystem state alone never upgrades uncertainty;
* terminal domain/fence closure only after required audit obligation/reconciliation;
* session end after ``call_start`` never downgrades effect truth.

25. Restart and reconciliation
------------------------------

Startup loads Phase 4 operations + Phase 6 session/workspace state.

Required behaviour:

* before access coordinator admits CONTENT_READ/CHANGE, new runtime is ``RECOVERY_CLOSED``
  and ``SearchChildRecoveryBarrier`` proves systemd cleanup of every prior-invocation rg or
  operation-attributable helper/descendant that could hold workspace descriptor; stale/
  foreign/unverifiable member keeps readiness closed;
* old in-process read cannot survive app death; old search child/descendant is never
  assumed gone because parent PID exited;
* service cgroup/lifecycle profile verified before search promotion; startup never opens by
  pathname/cgroup-emptiness guess alone;
* access-gate recovery never equals session authority: each new content admission still
  takes rebuilt session gate after CONTENT_READ;
* received without completed admission follows Phase 4 recovery deny;
* authorised never auto-starts after restart;
* running without exact receipt is not known-no-effect from filesystem;
* retained mutation fence reconciles before new changer/content; startup reconstructs
  change-closed from owner;
* exact receipt/reference + independently verifiable identity may converge per adapter;
* ambiguous receipt remains uncertain and retains fence;
* session end/expiry does not block same-key retained reconciliation;
* live-session-slot invariant verified; multiple PENDING/ACTIVE rows integrity failure;
* active session restored effective only after activation closure + exact profile/root/
  policy/time;
* incomplete activation remains ineffective;
* session gate rebuilt closed until predicates proven;
* no integrity record rebuilt from mutable source tree;
* unknown staging never heuristically removed.

26. Persistence and migration
-----------------------------

Expected Alembic ``0003_development_workspace.py`` after Phase 5 migration.

``development_sessions``
   Durable session identity, begin operation, owner/device/workspace/profile/policy/
   objective/time deadline, state/version, activation operation, closure state/version,
   terminal times/reasons. Partial unique index over device+epoch+workspace for PENDING or
   ACTIVE reserves one live slot.

``workspace_operations``
   One-to-one Phase 4 operation metadata: session/workspace/kind/source-target digests,
   expected object/content/link-count bindings, proposed content, canonical state binding,
   exact staging reference, primitive/profile version.

``workspace_mutation_fences``
   One row per workspace, monotonic version + nullable active operation owner; authoritative
   restart signal for WorkspaceAccessGate. Phase 7/8 consume through same coordination
   service, never independent fence.

Foreign keys point toward Phase 4 authoritative ownership records. Database checks reject
impossible combinations. Runtime never creates schema opportunistically.

27. Expected implementation file set
------------------------------------

Representative paths:

::

   src/binnacle/domain/development_session.py
   src/binnacle/domain/workspace.py
   src/binnacle/ports/workspace.py
   src/binnacle/application/development_session.py
   src/binnacle/application/workspace.py
   src/binnacle/application/workspace_coordination.py
   src/binnacle/adapters/workspace/__init__.py
   src/binnacle/adapters/workspace/linux.py
   src/binnacle/adapters/workspace/ripgrep.py
   src/binnacle/adapters/workspace/search_process.py
   src/binnacle/adapters/workspace/reconcile.py
   migrations/versions/0003_development_workspace.py
   tests/unit/domain/test_development_session.py
   tests/unit/domain/test_workspace.py
   tests/unit/application/test_workspace.py
   tests/integration/test_workspace_linux.py
   tests/integration/test_workspace_reconciliation.py
   tests/property/test_workspace_lifecycle.py

Contract promotion also expected to update:

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

No alternate parallel contracts for convenience.

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

   class WorkspaceSearchProcessSupervisor(Protocol):
       async def verify_previous_runtime_quiesced(self, workspace_id: str) -> None: ...
       async def spawn(self, request: SearchSpawnRequest) -> SearchProcessHandle: ...
       async def wait_tree_terminated(self, handle: SearchProcessHandle) -> None: ...

   class WorkspaceAliasVerifier(Protocol):
       async def verify_single_link_file(self, fd: int) -> None: ...
       async def preflight_search_scope(
           self, root_fd: int, relative_scope: str
       ) -> AliasPreflightResult: ...

   class WorkspaceMutator(Protocol):
       async def create(self, intent: CreateIntent) -> WorkspaceEffectReceipt: ...
       async def write(self, intent: WriteIntent) -> WorkspaceEffectReceipt: ...
       async def move(self, intent: MoveIntent) -> WorkspaceEffectReceipt: ...
       async def delete(self, intent: DeleteIntent) -> WorkspaceEffectReceipt: ...

   class WorkspaceAccessCoordinator(Protocol):
       async def content_read(self, workspace_id: str) -> ContentReadGuard: ...
       async def acquire_change(
           self, operation_id: str, workspace_id: str
       ) -> FenceLease: ...
       async def reconcile_change(self, operation_id: str) -> FenceLease: ...
       async def release_change(self, operation_id: str) -> None: ...

   class DevelopmentSessionAuthorityGate(Protocol):
       async def admit_content_read(
           self,
           session_id: str,
           workspace_id: str,
           request_digest: str,
           content_guard_epoch: int,
       ) -> ContentReadPermit: ...
       async def member_start(self, session_id: str, operation_id: str) -> StartPermit: ...
       async def reduce_authority(self, session_id: str, reason: str) -> None: ...

``admit_content_read`` is called only while exact ContentReadGuard is held. It revalidates
authoritative session/time/profile and returns permit bound to guard/request. Permit itself
neither acquires workspace access nor persists authority.

``workspace_patch`` computes deterministic bytes in application layer and delegates final
replacement to ``WorkspaceMutator.write``.

Linux adapter never performs policy/auth/host confirmation/lifecycle/session/fence
decisions. Application never implements raw pathname containment or shell search.

29. Error projection
--------------------

Use closed machine-readable codes/bounded safe summaries. Representative errors:

* ``development_session_required``;
* ``development_session_expired``;
* ``development_session_not_effective``;
* ``development_session_activation_incomplete``;
* ``development_session_already_active``;
* ``development_session_slot_busy``;
* ``workspace_not_registered``;
* ``workspace_profile_mismatch``;
* ``workspace_root_identity_mismatch``;
* ``workspace_path_invalid``;
* ``workspace_path_protected``;
* ``workspace_symlink_forbidden``;
* ``workspace_hardlink_forbidden``;
* ``workspace_alias_preflight_limit``;
* ``workspace_object_type_unsupported``;
* ``workspace_object_stale``;
* ``workspace_target_exists``;
* ``workspace_target_missing``;
* ``workspace_patch_mismatch``;
* ``workspace_no_replace_unsupported``;
* ``workspace_external_writer_model_unsupported``;
* ``workspace_cross_device_move_unsupported``;
* ``workspace_directory_not_empty``;
* ``workspace_busy``;
* ``workspace_effect_uncertain``;
* ``workspace_output_truncated``;
* ``workspace_search_timeout``;
* ``workspace_search_root_unavailable``;
* ``workspace_search_recovery_pending``;
* ``workspace_search_configuration_unsafe``;
* ``workspace_content_access_writer_model_unsupported``.

Errors do not reveal protected absolute path, another controller's session/operation, raw
key/nonce, credential, or never-disclosable state.

30. Logging, metrics, and diagnostics
------------------------------------

Structured diagnostics may include workspace ID, operation/session IDs, kind, normalized-
path digest, result bytes/truncation/search duration/fence state/reason codes/primitive
profile/session-gate outcome/content-admission/alias-preflight/search-child recovery/effect
reference digest.

Never log raw keys/nonces, source/search matches by default, credentials, protected
absolute paths where relative identity suffices, controller auth material, inherited
procfd numbers as stable IDs, or inherited environment/config content.

Metrics may cover bounded reads/searches/mutations, search timeout/truncation, alias
rejections/preflight limits, stale versions, fence contention, session-race rejection,
uncertain effects, session starts/ends, stale-search-child recovery, unsafe search config,
and disabled primitives. Path names/keys are not unbounded labels.

31. Security invariants
-----------------------

Implementation/review proves at least:

#. MCP/application process remains unprivileged.
#. Workspace root is owner config, never model absolute-path input.
#. Development session never grants credential/policy/broker/control-plane/arbitrary-system/
   hardware authority.
#. Session ID is not bearer authority.
#. Activation ineffective until exact post-effect audit/obligation closure.
#. Exactly one live PENDING/ACTIVE session row per device-epoch/workspace.
#. Session reduction and mutation start share authority-gate linearization.
#. Content admission shares session linearization **after** CONTENT_READ; stale pre-wait
   proof cannot disclose.
#. Lock order is WorkspaceAccessGate -> Phase4 handoff when applicable -> session gate ->
   process gate when applicable; no reverse session-reduction acquisition.
#. Same-key retained retry precedes mutable session/filesystem checks.
#. Every new mutation has Phase4 durable identity + required received audit before policy.
#. Change fence is post-policy exact-self and ``uncertain`` retains it.
#. Phase7/8 changers consume same coordination seam and preserve protected-content boundary.
#. Final OP-BOUNDARY revalidates session/closure/controller/device/profile/root/policy/audit/
   op/fence/source/target immediately before start.
#. No symlink or string-prefix containment decides authority.
#. Protected content cannot be exposed through path prefix, rename/exchange, **or hard-link
   alias**; content-bearing regular files require reliable ``st_nlink == 1`` and search
   preflights exact admitted scope under shared guard.
#. A profile with uncoordinated writers cannot promote content access from one-time alias/
   pathname checks; stronger confinement required.
#. No source bytes/no rg child before exact ContentReadPermit.
#. Every runtime starts RECOVERY_CLOSED until prior search children/helpers are proven gone
   and durable fence reconciled.
#. Ripgrep stays in exact service cgroup; guard release proves process tree quiescence.
#. Ripgrep starts from descriptor-pinned directory, never revalidated pathname.
#. Ripgrep child environment is closed/sanitized, configuration is explicitly disabled,
   preprocessors/archive helpers are explicitly disabled, no mandatory disabling flag is
   caller-negatable, and unexpected descendants are a failure.
#. Create cannot overwrite and staging cleanup exact/non-recursive; final content-ready
   regular file is single-linked.
#. Move target no-replace never degrades; delete no recursion; move no copy+delete.
#. Linux external-writer races are explicit limitations, not fake inode CAS.
#. Required unavailable primitive/writer/link-count/search purity keeps capability disabled.
#. Post-syscall path state alone never proves effect.
#. Source content bounded/classified; reusable secrets excluded.
#. Integrity state never rebuilt from mutable source after corruption.

32. Test strategy
-----------------

32.1 Unit/property tests
~~~~~~~~~~~~~~~~~~~~~~~~

Cover:

* path/protected-prefix normalizer;
* session state/expiry/effective/activation closure;
* live-session-slot uniqueness and same-key convergence;
* session gate lock order/start-vs-reduction;
* CONTENT_READ then session gate, exact permit, no content before permit;
* WorkspaceAccessGate shared/exclusive + RECOVERY_CLOSED startup;
* search process identity/no-release-before-tree-quiescence;
* direct regular-file ``st_nlink==1`` enforcement and bounded alias-preflight outcomes;
* same-key retry before mutable state;
* object-version including link-count facts;
* exact patch transformation;
* fence free/self/foreign/version;
* policy deny before fence;
* final exact-self fence canonicalization;
* create/write/patch/move/delete primitive/link-count/error mapping;
* bounded read/list/search projection.

Property tests prove normalized paths never escape; symlink trees never become valid;
protected hard-link aliases/multiply-linked files never become content-bearing targets;
same key creates at most one effect; different fingerprint adds zero effects; uncertain
never releases fence; session reduction before mutation start yields zero effect; reduction
after CONTENT_READ but before permit yields zero source/child; permit-first admits at most
one exact request while later admission fails; incomplete activation never admits; distinct
begins yield one live slot; content and change guards never overlap; RECOVERY_CLOSED never
opens without child quiescence; patch deterministic or no-effect; fence version monotonic.

32.2 Linux integration/adversarial tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux temp workspaces test:

* descriptor nested traversal and symlink inside/outside rejection;
* root replacement/mismatch;
* hard-link `.git/config` or another protected regular file into an allowed filename:
  direct read rejects before bytes and recursive search rejects before rg spawn;
* multiply link an ordinary file: Phase 6 content-bearing operations reject
  conservatively; remove alias and verify exact single-link recovery;
* link-count-unreliable/unsupported profile keeps affected capability disabled;
* descriptor-pinned rg while configured root/subdir renamed/replaced;
* rg JSON, hidden `.github`, protected `.git`, binary skip, timeout/truncation/failure;
* set service ``RIPGREP_CONFIG_PATH`` to a config that requests ``--pre`` sentinel or
  helper/archive behavior: sanitized environment + ``--no-config``/``--no-pre``/
  ``--no-search-zip`` prevent sentinel execution and no unexpected descendant appears;
* attempt caller options that negate mandatory process-purity flags and verify schema/
  adapter rejection;
* rg stays owning service cgroup and normal completion proves process tree quiescence
  before CONTENT_READ release;
* changer holds CHANGE, content caller early-validates session, end/expiry wins before guard
  available: queued content revalidates after guard and returns zero bytes/zero rg;
* Binnacle rename/exchange protected dir under allowed name while rg active cannot acquire
  exclusive guard until search ends;
* uncoordinated-writer profile without stronger confinement disables content access;
* create no-overwrite + unavailable primitive, exact staging recovery, final single-link
  publication;
* replacement durability, empty dir create/delete, non-empty dir move/delete rejection;
* RENAME_NOREPLACE/new target, cross-device rejection, external source replacement for
  write/move/delete, unsupported metadata rejection.

Adversarial move/delete tests do not assert impossible inode CAS. They assert limitations,
no-overwrite, detected/unprovable -> uncertain, and capability disabled when safety profile
not accepted.

32.3 Fault/restart/concurrency tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inject failures/crashes:

* after received before policy;
* after policy allow before live-session slot;
* after PENDING slot before activation intent/audit;
* failure terminalizing no-effect PENDING keeps slot until exact recovery;
* after allow before fence; after fence before authorised audit;
* after running/effect intent before final boundary;
* session gate held before obligation; after obligation before syscall;
* after create/write/move/delete syscall before durable receipt;
* after adapter receipt before effect classification;
* after known-effect before post-effect audit/fence release;
* DB failure during closure/fence release;
* after PENDING->ACTIVE before activation audit; after audit before closure CAS;
* after CONTENT_READ before permit while session end wins;
* app SIGKILL while rg holds descriptor: systemd removes rg and any operation-attributable
  descendant before replacement passes SearchChildRecoveryBarrier; both access modes remain
  blocked meanwhile;
* app restart active/effective, active/incomplete, expired/untrusted, uncertain mutation.

Concurrency proves two mutations cannot own fence; two begins cannot create two live slots;
same-key first mutation converges; session end vs call_start binary; content queued behind
changer cannot disclose after end; permit-first request may finish while later rejects;
trusted-time expiry blocks both start/content admission; audit-failure dispatch follows
Phase4 global gate; content cannot start while durable fence owner exists; changer cannot
acquire during content; replacement runtime cannot change while old search traversal may
survive; protected rename/exchange cannot race active search.

32.4 Contract/schema tests
~~~~~~~~~~~~~~~~~~~~~~~~~

Before exposure prove proposed Tool uniqueness, JSON Pointers, versions, information/host
classes, protected path+alias rules, content gate-owned session revalidation, coordinated-
writer/strong-confinement requirement, search process-purity flags/environment,
service-cgroup recovery barrier, live session slot non-disclosure, primitive degradation,
no Phase6 Tool when prereq absent, existing eight-tool profiles unchanged until promotion,
and catalogue digest changes only through reviewed manifest bump.

33. Real-Pi and real-ChatGPT evidence procedure
-----------------------------------------------

Evidence is for implementation promotion/exit, not plan acceptance.

Real Pi evidence verifies root ownership/identity; descriptor filesystem behavior;
reliable ``st_nlink`` semantics and protected-hard-link rejection; no-replace create;
RENAME_NOREPLACE if move enabled; accepted writer profile; rename/fsync; descriptor-pinned
rg; exact rg configuration/preprocessor/archive disabling options; sanitized environment;
service KillMode/control-group lifecycle, non-delegated search-child membership, crash/
restart child cleanup, SearchChildRecoveryBarrier, WorkspaceAccessGate protected-rename and
retained-fence behavior, queued-content/session-end linearization, writer/confinement model,
rg version/performance limits, and systemd permissions limited to registered source
workspace without protected state.

Real ChatGPT evidence verifies exact promoted catalogue; actual session-start host
interaction; no redundant member confirmation if HOST profile claims it; bounded source
read/search; new content request after session end rejected; promoted mutation entitlement;
same-key/lost-response; reconnect/restart continuity; end/expiry; no protected/unregistered
escape. If host cannot express bounded session authority, operational Phase6 remains
unsupported; never weaken local policy or silently use ambient HC0 mutation.

34. Holistic invariant pass before review
-----------------------------------------

Every new head is reviewed as continuous pipelines.

Content read/search:

::

   normalize/authenticate
     -> advisory early session/profile check
     -> CONTENT_READ acquisition
     -> session-authority gate
     -> exact time/session/controller/device/profile/root/protected-policy recheck
     -> request/guard-bound ContentReadPermit
     -> direct opened-file single-link check OR bounded recursive alias preflight
     -> descriptor read OR pinned/config-disabled/process-pure rg traversal
     -> proven read completion / process-tree termination+output drain
     -> content-guard release

Reduction before permit -> zero content/child. Permit-first authorizes only that bounded
request. Multiply-linked/unverifiable file -> zero content/child. Search configuration/
helper ambiguity -> zero child.

Mutation:

::

   normalize exact request/session/workspace state
     -> caller-key retained lookup or minimal pre-policy identity
     -> required received audit
     -> policy
     -> exclusive CHANGE
     -> post-policy exact-self durable fence + operation binding
     -> authorised audit
     -> running/effect intent
     -> phase-stable expected self transition
     -> per-operation handoff
     -> session gate
     -> process gate
     -> final session/profile/root/source/target/link-count revalidation
     -> durable audit obligation while session gate held
     -> gate-owned EffectBoundary.start
     -> immediate durable receipt/effect knowledge
     -> operation-specific domain closure
     -> post-effect audit/obligation closure
     -> fence release or conservative retention
     -> crash/restart
     -> caller-binding-first retained retry

Review walks normal success; stale source/target; session reduction while content waits and
before/during mutation start; activation incomplete/audit failure/concurrent begin; audit
failure; root/search replacement; protected rename/exchange; hard-link alias; hostile rg
config/preprocessor attempt; app crash with search child; lost filesystem receipt;
out-of-band source replacement; durable known effect then DB/audit closure failure;
same-key retry after session expiry; uncertain restart + unrelated mutation attempt.

Shared abstraction defect is fixed at foundation rather than patching each Tool.

35. Plan acceptance checklist
-----------------------------

Accept when review/CI confirms:

* scope exactly registered source workspace + development session;
* no ambient absolute/system/credential/policy/broker authority;
* session semantics owner-approved and HC0/HC1 mismatch named promotion prerequisite;
* activation cannot authorize before audit closure; one live PENDING/ACTIVE slot;
* session reduction vs mutation start one linearization;
* content waits for CONTENT_READ then revalidates under session gate before bytes/rg;
* fixed cross-gate order/no reverse reduction;
* Tools absent until reviewed contracts/schemas/manifest/host reconciliation;
* read/search bounded, protected-path/alias aware, symlink safe, descriptor-pinned, stable
  against coordinated rename/exchange;
* content-bearing regular files reject multiply-linked aliases and recursive search has a
  bounded exact-scope alias preflight under the shared guard;
* rg uses sanitized environment + mandatory no-config/no-pre/no-search-zip/no-follow
  process-purity settings and no unreviewed helper subprocess;
* search child lifecycle bound to service cgroup, process-tree quiescence proven, startup
  recovery closed until prior traversal absent;
* content fails closed if writer/link-count/confinement model insufficient;
* mutations exact version/descriptor containment + durable shared change fence reusable by
  Phase7/8;
* create/move no-overwrite no silent degrade; external-writer limitations truthful;
* staging exact/non-recursive and final created regular file single-linked;
* Phase4 audit/idempotency/final-boundary ordering exact;
* retained retry before mutable checks;
* pre-linearization session loss -> no effect/disclosure; post-linearization loss never
  rewrites started/admitted truth;
* all mutation outcomes representable/restart-reconcilable;
* no Pi/ChatGPT support fact fabricated.

36. Implementation/promotion checklist
--------------------------------------

Blocked until real Phase5 exit/write-confirmation; session host profile reviewed/passed;
Phase6 contracts/schemas/manifest promoted; migration + one-live-slot pass; session/access/
alias/fence/idempotency/audit/boundary tests pass; descriptor-pinned and config-disabled
search + protected rename + hardlink alias + session-end-while-waiting + application-crash/
child cleanup barrier pass; candidate service proves no prior rg/helper survives readiness;
content writer/confinement and link-count model accepted; no-overwrite primitives verified;
local writer profile permits each mutation; Linux tests pass; production exposes nothing
when prerequisite fails.

37. Real Phase 6 exit criteria
------------------------------

Do not mark implementation complete until real evidence proves:

#. owner-authorised session visible to real ChatGPT under reviewed HOST profile;
#. activation closure complete before member effect/content admission;
#. ChatGPT inspect/list/read/search exact registered workspace without protected path or
   hard-link-alias disclosure under reviewed writer/confinement model;
#. new content request after session end/expiry rejected even if it waited behind changer;
#. one controlled source edit;
#. new object version/content digest inspected truthfully;
#. revert/replace with exactly one admitted effect;
#. same-key retry no duplicate;
#. no workspace/protected escape;
#. session end/expiry blocks new/not-yet-started mutation;
#. restart preserves or truthfully rejects session, and active search cannot admit changer
   until prior rg/helper traversal proven terminated;
#. evidence captured from real Pi/ChatGPT, not inferred.

Move/delete/content access may remain truthfully disabled when their independent promotion
gates are not met.

38. Implementation order
------------------------

When evidence permits implementation:

#. reconcile/promote session-scoped host profile;
#. define/review Phase6 operation contracts/schemas;
#. update manifest/docs/evaluation, validate;
#. migration ``0003`` sessions/closure/live-slot/workspace metadata/shared fence;
#. domain/persistence + live-slot integrity tests;
#. DevelopmentSessionAuthorityGate + global lock-order tests;
#. workspace profile/root/protected-path + link-count/alias verifier;
#. WorkspaceAccessGate + durable fence with startup RECOVERY_CLOSED;
#. CONTENT_READ -> session gate -> ContentReadPermit;
#. application service child lifecycle + SearchChildRecoveryBarrier;
#. descriptor inspect/list/read with permit + single-link checks;
#. descriptor-pinned ``ripgrep`` with sanitized env, mandatory no-config/no-pre/
   no-search-zip, bounded alias preflight, full guard, process-tree quiescence, all race/
   config-injection/restart tests;
#. session begin/inspect/end with atomic PENDING slot, closure, fail-safe revocation;
#. mutation final-binding callback/shared change seam;
#. create exact staging/no-replace/final single-link closure;
#. write replacement + alias/external-race tests;
#. deterministic patch;
#. move only verified no-replace + accepted writer profile;
#. delete only explicit writer profile;
#. Phase4 audit/idempotency/boundary/effect integration;
#. expose coordination seam for Phase7/8 without their authority;
#. wire MCP only after registry parity;
#. unit/property/Linux/fault/restart/security tests;
#. deploy candidate Pi only after local/CI gates;
#. collect real ChatGPT evidence without converting missing observation into support.

39. Explicit provisional items
------------------------------

Remain evidence-gated after plan merges:

* exact ChatGPT session-start UI/interaction and whether HOST supports session semantics;
* exact host-profile identifier if ``HCS1`` name changes while semantics remain;
* Pi filesystem/kernel no-replace/durability/link-count behavior;
* descriptor-pinned rg spawn feasibility;
* exact candidate rg version and support/semantics for mandatory configuration,
  preprocessor, archive-helper disabling options;
* systemd proof that service cgroup + startup barrier prevents prior rg/helper survival;
* whether deployment enforces coordinated/no-out-of-band writer model or stronger
  protected-object confinement;
* whether move/delete cooperative writer assumption can be accepted;
* rg performance ceilings;
* real-host result size/catalogue refresh where promoted schemas depend on it.

These may change profile-specific choices/limits but not local authority, durable ordering,
truthful uncertainty, session start/content-admission linearization, protected-content
path+alias boundary, or no workspace escape without reviewed revision.

40. Deferred work
-----------------

Phase 6 defers arbitrary workspace registration by ChatGPT; multiple simultaneous changers;
recursive delete/non-empty tree move; symlink-following; user-visible hard-link operations;
generic chmod/chown/xattr/ACL; very-large-file streaming mutation; repository index/vector
search; shell command execution; Git credentials/signing; privileged host changes; advanced
namespace/seccomp/MAC/container hardening; hostile same-UID writer prevention beyond
explicit model; post-Bootstrap multi-user/project policy.

Add them only when they block self-hosting or later evidence justifies separately reviewed
capability.
