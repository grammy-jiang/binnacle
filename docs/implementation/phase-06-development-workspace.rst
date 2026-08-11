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
                       ``ripgrep`` search, shared content/change coordination, durable
                       Phase 4 consequential-operation integration for mutations,
                       session/start linearization, bounded MCP
                       contract/schema/manifest promotion, tests, deployment permissions,
                       and evidence gates only

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
required filesystem primitives, that ``ripgrep`` is installed at a particular version, or
that real Phase 5 write evidence has passed.

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
* the selected Pi/runtime proves every required descriptor-relative/no-overwrite/search
  primitive used by an exposed operation;
* the local workspace-writer safety assumptions described in sections 15, 16, and 23
  are explicitly accepted by the reviewed workspace profile; content-returning read/search
  requires either the reviewed no-uncoordinated-writer model plus the shared access gate or
  a stronger reviewed protected-object confinement mechanism, and mutations whose required
  primitive or writer assumption is unavailable stay disabled rather than silently
  degrading;
* the candidate systemd deployment proves the search-child lifecycle/readiness barrier in
  sections 15, 16, and 25: an ``rg`` child cannot survive an application service restart
  into a newly opened workspace access gate;
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
* symlink-following content access or mutation;
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
that can mutate this same registered workspace must coordinate with the authoritative
workspace access/change seam defined in section 16; those phases may extend the contract
but must not bypass it with an independent writer path.

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

``effective_for_new_work`` is a derived predicate, not merely ``state == ACTIVE``. It is
true only when the exact session is ``ACTIVE``, ``activation_closure == COMPLETE``, trusted
time is valid and before the deadline, controller/device/workspace/profile/policy facts
remain exact, no explicit end/revocation won the session gate, and global consequential
readiness is healthy.

One **live session slot** per exact device epoch + registered workspace is sufficient for
Bootstrap. ``PENDING`` and ``ACTIVE`` both occupy that slot, regardless of activation-
closure state. Migration ``0003`` enforces this independently in SQLite with a partial
unique index equivalent to::

   CREATE UNIQUE INDEX uq_development_sessions_live_workspace
       ON development_sessions(device_id, device_epoch, workspace_id)
       WHERE state IN ('pending', 'active');

The constraint is the durable overlap-prevention invariant, not an application pre-check.
A concurrent distinct begin request cannot create a second ``PENDING`` row while the first
activation is in flight. Same-key retry still resolves the retained begin operation before
slot/current-state checks; a distinct key that loses the slot race receives a bounded
non-disclosing ``development_session_slot_busy``/already-pending-or-active outcome and
creates no second authority-state effect. A different controller also cannot create an
overlapping live session for the same device/workspace merely because ownership changed.

A slot is released only by a truthful terminal session transition to ``ENDED``, ``EXPIRED``,
or ``REVOKED``. Ambiguous activation, incomplete activation audit/obligation closure, or
restart uncertainty leaves the ``PENDING``/``ACTIVE`` row live and therefore keeps the slot
reserved fail-closed. Startup treats multiple live rows for one slot as integrity failure;
it never picks one or rebuilds slot ownership from mutable source state.

The free-form owner objective is not executable policy. The implementation stores a
bounded safe label where useful plus a canonical digest for provenance. Binnacle does not
attempt to decide whether every later source edit is semantically part of the objective;
the session grants the reviewed broad workspace capability and ChatGPT remains the
reasoning agent.

7. Session authority gate, lifetime, restart, and revocation
------------------------------------------------------------

7.1 ``DevelopmentSessionAuthorityGate``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Phase 6 adds one application-level authority gate per current development session. It is
a correctness primitive, not a cache and not a substitute for durable session state.

The gate serializes exactly these competing events:

* a member mutation that is about to cross ``EffectBoundary.start``;
* explicit session end/revocation;
* trusted-time expiry becoming effective for new work;
* startup/recovery transition that marks the session ineffective because controller,
  device, workspace/profile, policy, or trusted-time continuity changed.

The fixed acquisition order for a member mutation is:

::

   Phase 4 per-operation dispatch handoff
     -> DevelopmentSessionAuthorityGate
     -> Phase 4 process-wide ConsequentialBoundaryGate

No code path acquires those gates in reverse order. Session end/revocation uses the same
session gate before any session authority-state transition and, when it needs the generic
Phase 4 consequential gate for its own durable effect, acquires it only after the session
gate. Tests fail on lock-order inversion.

For a member mutation, the session gate is held from the final trusted-time/session
predicate through final Phase 4 revalidation, durable audit-obligation publication, and
the process-wide gate-owned ``call_start`` linearization. It is released only after the
bounded start handoff has either definitely not occurred or has linearized and immediate
effect-receipt/knowledge classification has completed.

This closes the former race in which end/expiry could commit while audit-obligation bytes
were being fsynced and a stale member could still start afterward.

The outcome is binary at the start boundary:

* end/revocation/expiry wins the session-gate linearization -> the member cannot call
  ``EffectBoundary.start`` and closes with proven no effect after required recovery/audit;
* member ``call_start`` wins while the session gate still proves exact effectiveness ->
  the effect is already started/committed-to-start before later authority reduction, and
  later end/revocation cannot rewrite its effect truth.

Expiry is not a best-effort timer callback. Every gate entry samples the Phase 4 trusted-
time source under the same critical section; a deadline already reached or unverifiable
causes ``effective_for_new_work=false`` before a new member may start. A reconciler may
persist ``EXPIRED`` afterward, but persistence delay cannot extend authority.

7.2 Trusted-time binding
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

7.3 Ordinary Binnacle restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An ordinary MCP/application restart does not by itself end a session. On startup,
reconciliation may restore a session as effective only when all exact identity/profile/
policy/trusted-time predicates still verify **and** activation closure is durably complete.

This is necessary for the Bootstrap self-hosting loop: a normal Binnacle restart must not
force the owner to repeat the same development-session approval solely because the MCP
process restarted.

The in-memory ``DevelopmentSessionAuthorityGate`` is reconstructed from authoritative
session rows plus trusted current predicates. It never converts a merely ``ACTIVE`` row
with incomplete activation closure into effective authority.

7.4 End, expiry, and revocation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session end/expiry/revocation has two separate meanings:

* it prevents **new** member admission and any not-yet-started consequential member from
  crossing its final effect boundary;
* it does not rewrite, erase, duplicate, or blindly cancel the truth of an effect whose
  ``call_start`` already linearized.

Every member mutation therefore uses the exact session-gate sequence in section 7.1. If
session authority reduction wins before start, the mutation closes as proven no-effect and
releases its workspace mutation fence only after the normal Phase 4 audit/recovery closure.
If effect start wins, later session end does not manufacture ``known_no_effect``. The
retained operation proceeds through truthful receipt/effect classification and restart
reconciliation.

Same-key retry after session end returns the retained operation/result/uncertainty before
mutable session checks and never requires a now-expired session to create a second effect.

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
#. evaluate local policy for development-session activation against the exact observed
   no-live-slot/current-state facts;
#. after allow, enter one short post-policy admission transaction that re-proves the exact
   operation/controller/device/workspace/profile/time facts **and** the live slot is still
   free; a stale allow is not persisted as authority when that predicate changed;
#. in that same transaction, atomically insert the exact self-owned ``PENDING`` session row
   with ``begin_operation_id`` plus the trusted-time deadline, persist the one current
   allow/admission decision, and commit ``received -> authorised``; the SQLite partial
   unique index is the final race arbiter, so a distinct losing begin creates no second
   ``PENDING`` row or authority effect;
#. represent that post-policy reservation phase-stably as
   ``session_slot_transition=free_then_exact_self_pending`` bound to the exact begin
   operation; a foreign/missing/different pending row is never normalized into the final
   verifier;
#. emit required allowed/authorised audit and move the operation to ``running``;
#. record activation intent and perform final controller/device/workspace/profile/
   policy/time/slot revalidation;
#. publish the Phase 4 audit obligation and perform the exact ``PENDING -> ACTIVE``
   authority-state effect with ``activation_closure=PENDING``;
#. immediately retain effect knowledge/reference and append/fsync the required post-effect
   activation audit;
#. only after the required audit reports durable success, the obligation is safely closed,
   and exact operation/session identity is revalidated may one short CAS set
   ``activation_closure=COMPLETE``;
#. only ``ACTIVE`` + ``activation_closure=COMPLETE`` can make the session authority gate
   effective for new member work.

If the live slot becomes occupied between policy evaluation and the post-policy admission
transaction, the transaction does not persist the stale allow or an ``authorised`` state.
The request re-evaluates the now-current admission fact and follows a bounded Phase 4
proven-no-effect rejection path with ``development_session_slot_busy`` (or the exact
promoted equivalent), while the database unique index remains the final concurrency
arbiter. It never waits for the competing activation and then silently attaches to that
other session.

The session authority gate remains closed to member starts for the entire activation
operation until the final closure CAS succeeds. This eliminates any window where a newly
``ACTIVE`` row could authorize a member before required activation audit/obligation
closure.

If post-effect audit, obligation cleanup, or the final closure CAS fails, the session is
not effective for new work. Restart reconciliation may complete activation only from the
exact retained activation operation/effect reference plus schema-valid durable audit and
obligation evidence. It never infers activation from a host UI, model text, or the mere
presence of an ``ACTIVE`` row.

The live session slot remains occupied throughout this process. A pre-effect activation
failure may free it only after durable ``known_no_effect`` plus required audit/recovery
closure truthfully terminalizes the exact ``PENDING`` row. Once the authority-state effect
may have started or is durably known to have occurred, any incomplete/uncertain closure
keeps the ``PENDING``/``ACTIVE`` slot fail-closed until exact reconciliation or explicit
authority reduction terminalizes that same session. Slot release is never inferred from an
expired caller response, missing host UI, process restart, or a second begin request.

8.2 ``development_session_inspect``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Session inspect is bounded/read-only. The authenticated owner may inspect current/terminal
session metadata, effective status, activation-closure status, expiry/provisional
trusted-time status, workspace ID, profile digest, and bounded reason codes. It reveals no
credential, policy body, protected path, raw audit bytes, or source content.

8.3 ``development_session_end``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

End is an authority-reducing operation. It acquires the exact session authority gate before
changing the durable session authority state. Once the terminal transition wins that gate,
no later member ``call_start`` can begin.

The authority reduction is fail-safe: a failure to append the required end audit must never
cause authority to remain active merely so the audit can succeed first. The durable
``ACTIVE -> ENDED``/``REVOKED`` transition takes effect under the gate; subsequent audit
failure places global consequential admission into Phase 4 fail-restricted recovery while
the session remains reduced. This asymmetry is intentional: activation fails closed by
withholding effectiveness until audit closure, while revocation fails safe by removing
authority first.

If a member already won ``call_start`` before end acquired the session gate, end records
that the member is retained/in-flight but does not alter its effect knowledge. A same-key
end retry returns the retained end operation. A new request against an already terminal
session may return bounded already-ended state with no new effect.

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
       allow_out_of_band_writers: bool = False
       move_enabled: bool = False
       delete_enabled: bool = False

The exact production profile lives under protected configuration such as
``/etc/binnacle`` and is loaded into an immutable resolved settings snapshot. Model input
selects a registered ``workspace_id`` only; it cannot supply or redirect the root path or
weaken writer-safety settings.

``allow_out_of_band_writers`` does **not** make pathname CAS magically safe and it also
weakens pathname-based protected-content classification: an uncoordinated writer could
rename/exchange a protected directory beneath an allowed name while a recursive reader is
running. The flag therefore records a reviewed deployment assumption, not permission to
ignore the race.

When it is true, ``workspace_read``/``workspace_search`` content access remains disabled
unless a stronger reviewed mechanism preserves protected-object exclusion for the whole
read/traversal. When it is false, the shared ``WorkspaceAccessGate`` in section 16
coordinates all Binnacle-managed changers with content readers; the reviewed deployment
must also establish that other writers do not bypass that model. Mutations whose Linux
syscall cannot be made identity-conditional must either remain disabled or expose the
residual race classification required by their promoted contract.
``move_enabled``/``delete_enabled`` may become true only after the implementation/profile
promotion review accepts the exact primitive and writer model described in section 23.

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

At minimum, the reviewed Binnacle workspace profile excludes **content-returning access and
mutation** for:

* ``.git/`` -- Phase 8 semantic Git operations own repository metadata and credentials;
* project-local credential/private-key material if any is explicitly registered;
* any path mapped to protected Binnacle config/state/audit/control-plane storage;
* any deployment-specific protected path added by the owner profile.

``workspace_read`` and ``workspace_search`` therefore reject those protected content paths
rather than relying only on ``restricted-result`` classification. Protection must remain
stable for the **entire** content read/search, not only at initial pathname normalization.
A Binnacle-managed changer cannot rename/exchange ``.git`` or another excluded directory
beneath an allowed name while a content operation is traversing because content operations
hold the shared side of the ``WorkspaceAccessGate`` and every Binnacle-managed changer
holds its exclusive side. ``ripgrep`` ignore/path filters remain defense in depth; they are
not the sole security boundary for protected-object exclusion.

An accepted uncoordinated out-of-band writer would bypass that gate. Such a profile cannot
promote content-returning read/search unless a stronger reviewed descriptor/sandbox/view
mechanism preserves protected-object exclusion across concurrent rename/exchange. The
default Bootstrap path is therefore coordinated/exclusive writers for source-content
access, with fail-closed capability degradation otherwise.

``workspace_inspect`` or ``workspace_list`` may expose only bounded non-sensitive metadata
for a protected entry when the promoted contract explicitly permits it; they never expose
protected file bytes, link targets that reveal secret locations, or reusable authority
material.

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
* protected-prefix policy is checked before content return or mutation;
* the path identifies the semantic target only after descriptor-relative resolution.

String normalization never proves containment. Security containment is descriptor based.

12. Descriptor-relative Linux containment
-----------------------------------------

The security boundary uses Linux descriptor-relative operations rather than
``Path.resolve()``/string-prefix checks.

Bootstrap may prefer ``openat2`` with exact ``RESOLVE_BENEATH`` /
``RESOLVE_NO_MAGICLINKS`` / ``RESOLVE_NO_SYMLINKS`` semantics when a small reviewed
implementation is available. The required baseline is still race-resistant descriptor
traversal using Python/Linux primitives:

* open and pin the registered root directory descriptor;
* compare its exact identity with the session/profile root identity;
* walk directory components relative to already-open descriptors using ``dir_fd`` APIs,
  ``O_DIRECTORY`` and ``O_NOFOLLOW``;
* use ``follow_symlinks=False`` for metadata checks;
* invoke final ``open``, ``link``, ``renameat2``, ``unlink`` and directory operations
  through pinned parent descriptors rather than reconstructed absolute paths;
* never follow a workspace symlink during read or mutation;
* close all descriptors deterministically.

A narrowly reviewed internal ``/proc/self/fd/<n>`` reference may be used **only** to bind a
trusted subprocess such as ``ripgrep`` to an already-pinned descriptor. That procfd usage
is not a workspace path accepted from the model, does not relax normal magic-link
rejection, and is covered by explicit inherited-FD lifetime tests.

Read-only inspect/list may report that an entry is a symlink and may return bounded safe
metadata where explicitly reviewed, but ``workspace_read``, ``workspace_search`` traversal,
and all Phase 6 mutation operations reject symlink traversal and symlink-as-file mutation.

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

Object/version identity is exact evidence at the moment observed; it is not an
inode-conditional Linux mutation primitive. Section 23 scopes the residual race against an
uncooperative out-of-band writer.

14. Read-only workspace operations
----------------------------------

All read-only operations require authenticated owner/controller identity, the exact
registered workspace, and an effective development session unless the promoted contract
explicitly defines a smaller safe metadata exception.

They create no consequential Phase 4 operation merely for bookkeeping. They still enforce
request bounds, session/workspace authority, information classification, protected-path
exclusion, redaction, rate/resource limits, and audit/diagnostic policy applicable to
reads.

Content-returning operations additionally use the shared workspace access coordinator.
``workspace_read`` and ``workspace_search`` acquire a shared ``CONTENT_READ`` guard only
after proving the durable mutation fence is free and the exact workspace/session/profile
is valid; they hold it until the exact file read completes or the ``ripgrep`` child is
proven terminated/reaped and its bounded output is drained. A Binnacle-managed changer
must acquire the exclusive ``CHANGE`` side before it can acquire the durable mutation
fence, so protected objects cannot be relabelled by a coordinated rename while content is
being returned.

The guard is an application/process coordination primitive, not durable authority and not
a substitute for the mutation fence. In-process ``workspace_read`` dies with the owning
application runtime. ``workspace_search`` additionally uses the service-cgroup child
lifecycle and startup barrier in sections 15 and 16 so an ``rg`` child from a failed prior
runtime cannot retain a pinned descriptor while a replacement process opens the gate.
Every new application runtime initializes workspace access in ``RECOVERY_CLOSED`` and does
not admit either ``CONTENT_READ`` or ``CHANGE`` until that barrier and durable-fence
reconciliation are complete.

14.1 ``workspace_inspect``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns bounded workspace/profile/root identity, optional one-path metadata, object type,
object version, size/mode summary, and capability/degradation facts. It does not expose
absolute protected paths when a stable workspace-relative projection is sufficient.

14.2 ``workspace_list``
~~~~~~~~~~~~~~~~~~~~~~~

Lists one directory or a bounded recursive depth. Traversal is descriptor-relative, does
not follow symlinks, stops at configured entry/depth/output ceilings, and returns a
truthful ``truncated`` indicator. Protected entries may be represented as bounded metadata
only if the promoted information contract permits it.

14.3 ``workspace_read``
~~~~~~~~~~~~~~~~~~~~~~~

Reads one exact non-protected regular file with bounded byte range/chunk semantics. It
returns the object version, full content digest when available, exact returned range,
encoding/media facts, and truncation/continuation information. Binary content is never
silently decoded as text.

15. Descriptor-pinned typed ``ripgrep`` search adapter
------------------------------------------------------

``workspace_search`` uses the mature ``ripgrep`` executable behind a typed adapter rather
than a custom repository index or Python regex walk.

The adapter invokes explicit argv only and never a shell. Use ``rg --json`` or an equally
structured mode so parser behaviour is deterministic.

A configured root pathname is **never** passed to ``rg`` after merely checking it.
Path-based ``--glob``/ignore exclusions alone are also insufficient because a concurrent
rename could relabel a protected directory. The launch sequence is:

#. normalize the optional search subpath and reject any protected/symlink-bearing scope;
#. verify the promoted profile either excludes uncoordinated writers for content traversal
   or supplies a separately reviewed stronger protected-object confinement mechanism;
#. require the current application service invocation to have passed the
   ``SearchChildRecoveryBarrier`` described below;
#. acquire the shared ``WorkspaceAccessGate`` ``CONTENT_READ`` guard and, atomically with
   that admission, require the durable workspace mutation fence to be free;
#. open/pin the exact registered workspace root descriptor and verify the session-bound
   root identity;
#. descriptor-walk and pin the exact search-directory descriptor; Bootstrap search scopes
   are directories, while exact-file content search may be implemented separately only if
   its descriptor binding is reviewed;
#. duplicate the pinned search descriptor to an operation-owned FD with deterministic
   lifetime;
#. spawn ``rg`` with ``close_fds=True`` and only that exact FD explicitly inherited;
#. keep the child in the exact Binnacle application systemd service cgroup: do not launch
   it through ``systemd-run``, a delegated scope, double-fork/daemon path, or any mechanism
   that can move it outside the service manager's lifecycle domain;
#. establish child cwd from the pinned descriptor, for example through a reviewed internal
   ``/proc/self/fd/<fd>`` cwd or an equivalent tiny descriptor-bound spawn helper;
#. pass ``.`` as the only search root; do not pass the configured workspace pathname or a
   reconstructed subpath;
#. retain a process handle that binds child PID plus a non-reused process identity such as
   Linux start-time/pidfd evidence and the current application service invocation/runtime
   identity; PID alone is never sufficient recovery evidence;
#. keep the inherited descriptor valid until exec/cwd establishment has completed, then
   close parent copies deterministically;
#. retain the shared content guard for the full recursive traversal, including timeout/
   termination and bounded stdout/stderr drain, and release it only after pidfd/wait-style
   evidence proves the child is terminated/reaped and can no longer traverse the workspace.

The application service unit must explicitly retain search children in its cgroup and use
``KillMode=control-group`` plus ``SendSIGKILL=yes`` (or a reviewed strictly stronger
systemd lifecycle). ``Delegate`` is not granted to the application service for this
purpose. On service stop/restart, remaining search children therefore belong to the unit
cleanup rather than becoming an unmanaged process tree. A bounded stop timeout is part of
the deployment profile. Optional parent-death signalling from a tiny reviewed launcher may
be defense in depth, but it is never the sole restart invariant.

Every fresh application invocation starts a ``SearchChildRecoveryBarrier`` before the
``WorkspaceAccessGate`` may leave ``RECOVERY_CLOSED``. The barrier verifies the exact
systemd unit/cgroup identity and proves that no process from the prior application
invocation remains able to traverse a pinned workspace descriptor. The implementation may
combine service-manager state with cgroup membership, process start-time/pidfd evidence,
and the current systemd invocation identity; any stale/foreign member or unverifiable
state keeps both ``CONTENT_READ`` and ``CHANGE`` closed. The barrier never clears a durable
workspace mutation fence. If the required cgroup cleanup/readiness proof cannot be
implemented and verified on the candidate Pi, content search and workspace-changing
capability remain unready rather than assuming old children disappeared.

Replacing or renaming the configured root/search directory after verification therefore
cannot redirect the child into a replacement tree. The search continues against the
pinned directory object or fails; it never silently rebases onto the new pathname.
Likewise, a Binnacle-managed Phase 6/7/8 changer cannot rename/exchange a protected
directory beneath an allowed path while ``rg`` is running because it cannot acquire the
exclusive change guard. Profiles that permit uncoordinated writers remain fail-closed for
content search unless the stronger reviewed mechanism above is present.

The reviewed adapter additionally binds:

* bounded pattern length;
* Rust-regex/default engine semantics only for Bootstrap; no arbitrary PCRE2 feature
  expansion unless separately reviewed;
* case/fixed-string options from a closed enum;
* file/match/output/per-file byte ceilings;
* hard wall timeout;
* binary-file skip policy;
* ``--no-follow`` or equivalent no-symlink traversal;
* hidden-file handling sufficient to search normal source paths such as ``.github`` while
  explicitly excluding protected ``.git`` and other profile exclusions;
* reviewed ignore-file behaviour;
* bounded subprocess stdout/stderr capture;
* truthful ``truncated`` and ``timed_out`` results.

Search is read-only. A timeout or output ceiling never becomes a partial-success claim
without explicit ``truncated``/``timed_out`` metadata. Root/subdirectory replacement
races at launch, protected-directory rename/exchange while traversal is active, application
crash/restart while ``rg`` holds a pinned descriptor, and content-search admission while a
durable changer fence exists are mandatory Linux/concurrency integration tests.

16. Shared workspace access/change coordination seam
------------------------------------------------------

Phase 6 deliberately chooses a conservative Bootstrap concurrency model. At most one
consequential Binnacle-managed workspace-changing effect may own the registered workspace
fence at a time. Metadata-only inspect/list can remain concurrent; content-returning
``workspace_read``/``workspace_search`` may run concurrently with other content readers but
not with a Binnacle-managed workspace changer.

One per-workspace ``WorkspaceAccessGate`` supplies that read/write linearization:

* ``CONTENT_READ`` is shared and may be acquired only while the durable mutation fence is
  free and startup search-child recovery is complete; ``workspace_read`` holds it for the
  exact descriptor read and ``workspace_search`` for the entire child traversal/output-
  drain/termination lifetime;
* ``CHANGE`` is exclusive. A new mutation acquires it **after policy allow but before**
  acquiring the durable workspace mutation fence and retains it until the durable fence is
  truthfully released. If effect truth is ``uncertain``, the durable fence remains owned
  and the access gate remains/recovers change-closed;
* acquisition/release is ordered by one application coordinator so a content reader cannot
  observe ``fence free`` while a changer concurrently crosses into ownership, and a
  changer cannot acquire its durable fence while a content guard is active;
* every new application invocation initializes the coordinator in ``RECOVERY_CLOSED``.
  It may transition to its normal free/change-closed posture only after the exact
  ``SearchChildRecoveryBarrier`` proves no search child from a previous invocation can
  still traverse the workspace **and** durable mutation-fence state has been loaded and
  reconciled. A retained durable fence owner keeps the change side closed even after child
  recovery. A stale/unknown prior search child keeps both content and change admission
  closed.

The access gate is not a second authority source and does not make out-of-band writers
cooperate. Content-returning operations therefore require the reviewed no-uncoordinated-
writer profile or a stronger protected-object confinement mechanism as described in
sections 9, 10, and 15.

The word **changing** is deliberate. The same authoritative seam must later be consumed by
Phase 7 development commands and Phase 8 Git operations whenever their reviewed contract
may change files in this workspace. Later phases may add richer coordination or typed
submodes, but they must not create an independent mutation lane that can race past this
gate/fence pair.

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
workspace fails consequential readiness. ``WorkspaceAccessGate`` derives its restart
closed/open posture from this row **and** the verified search-child recovery barrier, but
never reconstructs or clears durable fence ownership.

Post-policy admission, while the exact operation already owns the exclusive
``WorkspaceAccessGate`` ``CHANGE`` guard, may acquire only the exact transition:

::

   free fence version N
       -> exact current operation owns fence version N+1

The operation-specific current-state binding represents that expected self transition
semantically rather than hashing a raw ``NULL`` that would necessarily mismatch after
admission. Final OP-BOUNDARY canonicalization accepts only the exact self-owned fence plus
the consumed operation binding. Foreign ownership, missing ownership, changed workspace
profile, or unexpected fence version fails closed.

The fence is released only after the operation has a truthful terminal/no-effect/effect
classification plus the required post-effect audit/obligation/recovery closure. The
exclusive access guard is released only after that durable fence release commits. An
``uncertain`` operation retains the fence, which keeps/reconstructs the workspace
change-closed and blocks both new changing operations and new content-returning read/search
until explicit reconciliation. Filesystem appearance/absence never reconstructs or steals
fence ownership.

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
#. load/revalidate the exact active/effective session, workspace/profile/root identity,
   expected source/target state and local policy inputs;
#. evaluate policy;
#. on deny, durably store the one decision and ``received -> rejected`` with no workspace
   fence/effect;
#. on allow, acquire the exclusive ``WorkspaceAccessGate`` ``CHANGE`` guard, then in one
   short post-policy transaction re-prove the exact operation/session predicates, acquire
   the free durable workspace change fence for this exact operation, store the operation-
   specific workspace binding, store the one allow decision, and commit
   ``received -> authorised``; if the transaction cannot acquire the fence, release the
   access guard with zero filesystem effect;
#. fsync required allowed ``policy.decision`` + ``operation.authorised`` evidence;
#. commit ``authorised -> running``;
#. fsync ``effect.intent_recorded``;
#. acquire the Phase 4 per-operation dispatch handoff;
#. acquire the exact ``DevelopmentSessionAuthorityGate``;
#. acquire the Phase 4 process-wide consequential gate;
#. under those gates, re-sample trusted time and perform final all-mode OP-BOUNDARY
   revalidation including exact current session activation closure, controller/device,
   profile/policy/root/fence/source/target/cancellation/audit/recovery facts;
#. publish/fsync the durable audit-obligation marker while the session gate remains held;
#. re-check the gate-owned session/trusted-time predicate and use the process-wide
   ``call_start`` linearization to start the exact workspace effect;
#. immediately persist the bounded effect reference/receipt/effect knowledge before the
   session gate is released;
#. complete required post-effect audit, operation/domain closure, obligation cleanup,
   durable fence release, and only then exclusive access-guard release where truthfully
   safe.

No SQLite transaction spans filesystem effect I/O. Session end/revocation/expiry cannot
commit between the final session predicate and a later stale member start because they
share the same session gate.

18. Phase-stable mutation current-state binding
-----------------------------------------------

The operation-specific workspace binding is a canonical digest over immutable/request
facts plus exact current state and only the narrowly expected self-owned admission
transition.

For all mutation kinds it binds at least:

* session ID, session state/version, and activation-closure version expected at admission;
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
``N+1``, and the immutable operation/binding relationship matches. The session gate then
proves that the exact expected session is still effective at start. No unrelated changed
state is normalized away.

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
* stage complete bytes in the verified target filesystem under an exact
  operation-owned reserved staging name;
* fsync staged file;
* publish with an atomic target-no-replace primitive; a same-filesystem
  descriptor-relative hard link from the complete staged inode is an acceptable baseline
  when verified on the candidate profile;
* never silently substitute a normal overwriting rename for no-replace publication;
* fsync the parent directory after publication;
* remove/fsync the exact operation-owned staging name only after truthful publication
  handling.

Staging recovery never scans by broad glob, prefix guess, recursive delete, or pathname
appearance alone. The operation retains the exact staging identity/reference needed to
remove only its own verified staging entry. Unknown staging content is preserved and
reported for recovery.

If the target appears before no-replace publication, return a proven no-effect conflict.
If the required no-replace primitive is unavailable, create-file promotion is disabled for
that profile rather than weakened. If the process loses publication/fsync receipt, final
pathname presence alone cannot establish ``known_effect`` and the operation
becomes/remains ``uncertain``.

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

Linux pathname replacement does not provide perfect inode-conditional compare-and-swap
against an uncooperative out-of-band writer between the final revalidation and rename.
Bootstrap scopes its exact serialization guarantee to Binnacle-coordinated workspace
writers through the shared fence. Immediate final descriptor-relative revalidation narrows
an out-of-band race; post-syscall mismatch/lost receipt is ``uncertain`` and is never
reported as perfect CAS. The promoted workspace profile must disclose/accept this local
writer model or keep replacement mutation disabled.

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
adapter path and therefore inherits the same out-of-band writer limitation. Patch never
executes a shell ``patch`` program and never applies fuzzy context.

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

Immediately before the syscall, final OP-BOUNDARY and adapter revalidation require the
exact source and absent target. Target no-overwrite is enforced atomically with a reviewed
descriptor-relative primitive such as ``renameat2(..., RENAME_NOREPLACE)``. A normal
``rename`` that can overwrite a newly appeared target is **not** a fallback. If
``RENAME_NOREPLACE`` or an equivalent reviewed primitive is unavailable, move remains
unsupported/disabled for that workspace profile.

Linux does not provide an inode-conditional ``rename`` that atomically says “move this
pathname only if it still names inode X” against an uncooperative external writer. The
Binnacle fence serializes Binnacle-coordinated writers and immediate descriptor-relative
source revalidation narrows the race, but a same-permission out-of-band writer can replace
the source name between verification and ``renameat2``. Phase 6 therefore makes this an
explicit local concurrency limitation rather than a false CAS guarantee.

The promoted contract/profile must either establish the accepted cooperative-writer model
for move or leave move disabled. Tests deliberately replace the source during the final
handoff and require any detected post-syscall identity mismatch/lost receipt to become
``uncertain``. Binnacle never claims that target appearance/source absence alone proves the
intended object moved. After a proven rename receipt, parent directories for source and
target are fsynced when distinct.

23. ``workspace_delete`` and the external-writer safety boundary
----------------------------------------------------------------

Delete supports exactly:

* one existing regular file with expected object version/content digest; or
* one exact empty directory with expected object version.

There is no recursive flag, glob, wildcard, implicit cleanup, or delete-through-symlink.

Final descriptor-relative identity verification occurs immediately before ``unlink`` or
``rmdir``. Parent-directory fsync is part of successful effect completion. A lost receipt
with observed absence remains ``uncertain`` unless independent durable effect evidence
proves the deletion; absence alone is not a removal receipt.

Linux ``unlinkat``/``rmdir`` are pathname operations and are not inode-conditional CAS.
An uncooperative out-of-band writer with permission to replace the source name can race the
final verification and cause a different entry to be removed. The Binnacle shared fence
prevents Binnacle-managed overlap but cannot force arbitrary same-permission processes to
honour it.

Therefore Phase 6 does not claim perfect exact-object deletion in the presence of
uncoordinated external writers. ``workspace_delete`` is exposed only when the reviewed
workspace profile accepts a cooperative/exclusive Binnacle writer model for destructive
pathname operations or a stronger reviewed identity-safe primitive is introduced. If that
assumption cannot be established on the candidate environment, delete remains disabled.

The same limitation is recorded for replacement/move in their contracts. The security
claim is: Binnacle never follows symlinks, never broadens the target, serializes all
Binnacle-managed writers, checks exact identity immediately before the syscall, never
silently overwrites a move target, and never overclaims a detected or unprovable race. It
is **not** a claim that Linux pathname syscalls can prevent a hostile same-UID writer from
changing the name between check and syscall.

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
* primitive/profile version used;
* receipt digest/version.

The generic Phase 4 operation owns authoritative lifecycle/effect knowledge. Phase 6
operation-specific rows may record bounded source/target/result facts but cannot invent a
parallel effect-knowledge enum.

Rules are:

* complete adapter receipt after the exact durability point -> eligible for
  ``known_effect``;
* explicit pre-start/no-syscall or exact no-effect receipt -> eligible for
  ``known_no_effect``;
* lost syscall/fsync receipt, incomplete effect reference, identity mismatch, detected
  out-of-band source race, or otherwise unprovable result -> ``uncertain``;
* final filesystem state alone never upgrades uncertainty;
* terminal operation/domain/fence closure occurs only after the required audit obligation
  and reconciliation predicates are complete;
* session end after ``call_start`` never downgrades known/uncertain effect truth.

25. Restart and reconciliation
------------------------------

Startup reconciliation loads Phase 4 operations plus Phase 6 session/workspace state.

Required behaviour:

* before the workspace access coordinator can admit either ``CONTENT_READ`` or ``CHANGE``,
  the new runtime starts it ``RECOVERY_CLOSED`` and the ``SearchChildRecoveryBarrier``
  proves that systemd completed cleanup of every prior-invocation search child that could
  still hold a pinned workspace descriptor; a stale/foreign/unverifiable service-cgroup
  member keeps workspace content/change readiness closed;
* ``workspace_read`` from the old application cannot survive process death; an old
  ``workspace_search`` child is never assumed gone merely because its parent PID exited;
* the application service cgroup/lifecycle profile is verified before search promotion and
  startup never opens the gate by pathname/cgroup emptiness guess alone;
* ``received`` without completed admission follows Phase 4 fail-closed recovery deny;
* ``authorised`` that never entered dispatch does not start automatically after restart;
* ``running`` with no durable exact effect receipt is not classified
  ``known_no_effect`` merely from the filesystem;
* an operation retaining the workspace mutation fence is reconciled before any new
  changing operation may acquire it; startup also reconstructs ``WorkspaceAccessGate`` as
  change-closed from that durable owner, so content read/search is blocked until exact
  reconciliation;
* exact durable receipt/reference plus independently verifiable identity may converge an
  operation according to its adapter contract;
* ambiguous/lost receipt remains ``uncertain`` and retains the fence;
* session end/expiry does not prevent same-key retrieval/reconciliation of already retained
  work;
* the durable live-session-slot invariant is verified before session readiness; more
  than one ``PENDING``/``ACTIVE`` row for the same device epoch/workspace is integrity
  failure, and an uncertain/incomplete activation continues to occupy its slot;
* a still-``ACTIVE`` session is restored as effective only after activation closure and
  exact profile/root/policy/time verification;
* an ``ACTIVE`` session with incomplete activation audit/obligation closure remains
  ineffective and is reconciled from exact retained evidence only;
* the session authority gate is rebuilt closed until those predicates are proven;
* no session or workspace integrity record is rebuilt from mutable source-tree state after
  corruption;
* unknown operation-owned staging entries are never recursively or heuristically removed.

26. Persistence and migration
-----------------------------

Phase 6 implementation is expected to add Alembic migration
``0003_development_workspace.py`` after the Phase 5 probe migration.

Representative authoritative tables are:

``development_sessions``
   Durable session identity, ``begin_operation_id``, owner/device/workspace/profile/policy/
   objective digests, trusted-time deadline evidence, state/version, activation operation,
   ``activation_closure`` state/version, and terminal timestamps/reasons. Migration
   ``0003`` creates a SQLite partial unique index over
   ``(device_id, device_epoch, workspace_id)`` for rows whose state is ``PENDING`` or
   ``ACTIVE``. The database therefore reserves the one live session slot from the first
   post-policy ``PENDING`` insert through activation/incomplete activation until a truthful
   terminal transition releases it.

``workspace_operations``
   One-to-one operation-specific metadata keyed by the Phase 4 ``operation_id``: session,
   workspace, mutation kind, normalized source/target digests, expected object/content
   bindings, proposed content digest, canonical current-state binding digest, exact
   operation-owned staging identity/reference where applicable, and primitive/profile
   version used for the effect.

``workspace_mutation_fences``
   One authoritative row per registered workspace with monotonic fence version and nullable
   active operation owner. It is also the durable restart signal that causes the
   per-workspace ``WorkspaceAccessGate`` to initialize change-closed while an owner remains.
   Phase 7/8 workspace-changing contracts consume this row through the same application
   coordination service rather than writing an independent fence.

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

   class WorkspaceSearchProcessSupervisor(Protocol):
       async def verify_previous_runtime_quiesced(self, workspace_id: str) -> None: ...
       async def spawn(self, request: SearchSpawnRequest) -> SearchProcessHandle: ...
       async def wait_terminated(self, handle: SearchProcessHandle) -> None: ...

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
       async def member_start(self, session_id: str, operation_id: str) -> StartPermit: ...
       async def reduce_authority(self, session_id: str, reason: str) -> None: ...

``workspace_patch`` belongs in the application layer: it computes deterministic new bytes
from exact base content and delegates the final replacement to ``WorkspaceMutator.write``.

The Linux adapter never performs policy, controller authentication, host confirmation,
operation lifecycle, session-authority, or fence ownership decisions. The application
service never implements raw pathname containment or shell search execution.

29. Error projection
--------------------

Use closed machine-readable reason/error codes with bounded safe summaries. Representative
Phase 6 errors include:

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
* ``workspace_content_access_writer_model_unsupported``.

Errors do not reveal a protected absolute path, another controller's session/operation, raw
idempotency key, credential, or never-disclosable state.

30. Logging, metrics, and diagnostics
------------------------------------

Structured diagnostics may include workspace ID, operation/session IDs, mutation kind,
normalized-path digest, result byte counts, truncation, search duration, fence state,
reason codes, primitive/profile version, session-gate outcome, search-child recovery state,
and effect-reference digest.

Do not log:

* raw idempotency keys/nonces;
* source file contents/search matches by default;
* reusable credentials;
* protected absolute paths where workspace-relative identity suffices;
* raw controller authentication material;
* inherited procfd numbers as stable identifiers.

Useful metrics include bounded counters/histograms for workspace reads/searches/mutations,
search timeout/truncation, stale-version rejections, fence contention, uncertain mutation
outcomes, session starts/ends/expiry, session-start race outcomes, stale-search-child
recovery blocking, and disabled primitive profiles. Path names and operation keys are never
unbounded metric labels.

31. Security invariants
-----------------------

The implementation and review must prove at least:

#. The network-facing MCP/application process remains unprivileged.
#. Workspace root is owner configuration and never model-selected absolute path input.
#. A development session never grants credential, policy, broker, control-plane, arbitrary
   system, or hardware authority.
#. Session identifiers are not bearer authority; exact authenticated owner identity and
   local policy remain required.
#. Session activation is ineffective until exact required post-effect audit/obligation
   closure is durably complete/reconcilable.
#. Exactly one live ``PENDING``/``ACTIVE`` session row may occupy a device-epoch/workspace
   slot; distinct concurrent begin operations cannot both reserve or activate it, and
   uncertain/incomplete activation retains the slot fail-closed.
#. Session end/revocation/expiry and member effect start share one authority-gate
   linearization; no member starts after an authority reduction that won before start.
#. Session end after ``call_start`` never rewrites already-started effect truth.
#. Same-key retained retry resolves before mutable session/filesystem checks and can never
   create a second effect.
#. Every new mutation has Phase 4 durable caller identity before policy/effect.
#. Workspace change fence is acquired only after policy allow and is exact-self bound at
   final OP-BOUNDARY.
#. ``uncertain`` retains the workspace fence and is never blindly retried.
#. Phase 7/8 workspace-changing effects must consume the same authoritative coordination
   seam rather than bypassing it.
#. Final OP-BOUNDARY revalidates session, activation closure, controller/device,
   profile/root, policy, audit, operation state, fence, and exact source/target facts
   immediately before start.
#. Required received and authorised audit ordering remains exactly Phase 4 compatible.
#. No symlink traversal or string-prefix containment decides filesystem authority.
#. Content-returning read/search cannot expose ``.git`` or other protected credential/
   control-plane exclusions.
#. Content-returning read/search holds the shared side of ``WorkspaceAccessGate`` for the
   entire descriptor read/recursive traversal; all Binnacle-managed changers hold the
   exclusive side, and a profile permitting uncoordinated writers cannot promote content
   access without stronger protected-object confinement.
#. Every application runtime starts the workspace access coordinator ``RECOVERY_CLOSED``;
   neither content access nor a workspace-changing effect is admitted until the verified
   service-cgroup search-child barrier proves no prior runtime can still traverse a pinned
   workspace descriptor.
#. ``ripgrep`` stays in the exact Binnacle application service cgroup and normal guard
   release requires proven child termination/reaping; parent PID exit alone is never
   treated as proof that recursive traversal ended.
#. ``ripgrep`` starts from a descriptor-pinned search directory and never from a merely
   revalidated configured pathname; pathname ignore rules are defense in depth rather than
   the sole protected-content boundary.
#. Create cannot overwrite and never degrades to an overwriting primitive; staging cleanup
   is exact/non-recursive.
#. Move target publication uses atomic no-replace or remains disabled.
#. Delete cannot recursively broaden; move cannot silently become copy+delete.
#. Linux source/delete pathname races against uncooperative out-of-band writers are stated
   as a limitation and never misrepresented as inode-conditional CAS.
#. Operations whose required primitive or accepted writer model is unavailable stay
   disabled for that profile.
#. Post-syscall observation alone never proves effect after a lost receipt.
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

* path normalization and every invalid component/protected-prefix class;
* session state/version/expiry/effective/activation-closure predicates;
* live-session-slot partial uniqueness, same-key retention, distinct-key concurrent begin,
  and fail-closed slot retention during incomplete/uncertain activation;
* session-authority gate lock order and start-vs-reduction outcomes;
* ``WorkspaceAccessGate`` shared-content/exclusive-change acquisition, unconditional
  startup ``RECOVERY_CLOSED`` state, and transition only after search-child recovery plus
  durable-fence reconciliation;
* search-process identity, current-runtime binding, and no-release-before-reap semantics;
* same-key retained retry before current session/state validation;
* object-version canonicalization;
* exact-match patch transformation and duplicate/overlap rejection;
* mutation fence free/self/foreign/version transitions;
* policy deny before fence acquisition;
* final verifier exact-self fence canonicalization;
* create/write/patch/move/delete input, primitive-gating, and error mapping;
* bounded read/list/search result projection.

32.2 Property tests
~~~~~~~~~~~~~~~~~~~

Use Hypothesis for:

* normalized paths never escaping the registered root model;
* arbitrary symlink/component trees never becoming valid mutation traversal;
* same key/same fingerprint producing one operation/effect counter;
* same key/different fingerprint producing zero additional effects;
* no legal transition releasing a fence from ``uncertain`` without reconciliation;
* session end/expiry winning the authority gate before start producing zero effect;
* member start winning before end never converting durable/uncertain effect truth to
  no-effect;
* incomplete activation closure never permitting a member start;
* arbitrary concurrent distinct begin operations yielding at most one live
  ``PENDING``/``ACTIVE`` session slot;
* incomplete/uncertain activation never freeing the live slot for a second begin;
* content-read guards and Binnacle-managed change guards never overlapping;
* no transition from workspace ``RECOVERY_CLOSED`` to normal admission while prior-runtime
  search-child quiescence is unproven;
* patch edits either deterministically produce one exact byte string or reject with no
  effect;
* fence version monotonicity across acquire/release/restart.

32.3 Linux integration tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux temp workspaces test:

* descriptor-relative nested traversal;
* symlink-to-inside and symlink-to-outside rejection;
* root replacement/mismatch;
* descriptor-pinned ``rg`` launch while the configured root is renamed/replaced;
* descriptor-pinned search-subdirectory replacement during spawn;
* ``rg --json`` parsing, hidden ``.github`` search, protected ``.git`` exclusion, binary
  skip, timeout, output truncation, and process failure;
* ``rg`` remains in the owning application service cgroup/no delegated scope and normal
  completion proves termination/reaping before ``CONTENT_READ`` release;
* Binnacle-managed rename/exchange of ``.git`` or another protected directory beneath an
  allowed name while ``rg`` is active: the changer cannot acquire the exclusive access
  guard until search ends and no protected bytes are returned;
* content read/search fail-closed when the profile permits uncoordinated writers and no
  stronger protected-object confinement mechanism is promoted;
* create no-overwrite and required-primitive-unavailable fail-closed behaviour;
* exact operation-owned staging recovery with unrelated staging content preserved;
* regular-file replacement durability path;
* empty-directory create/delete;
* non-empty-directory delete/move rejection;
* move with ``RENAME_NOREPLACE`` or selected exact equivalent and newly appeared target;
* cross-device move rejection where fixtures permit;
* adversarial out-of-band source replacement between final check and move/delete syscall;
* file mode/unsupported metadata rejection.

The adversarial move/delete tests do not assert an impossible inode-conditional syscall.
They assert that Binnacle's contract discloses the limitation, required target no-overwrite
never degrades, detected/unprovable results become ``uncertain``, and the operation stays
disabled when its writer-safety profile is not accepted.

32.4 Fault and restart tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inject crashes/failures at least at:

* after minimal received operation before policy;
* after policy allow before live-session-slot reservation;
* after ``PENDING`` live-slot reservation before activation intent/audit;
* DB/operation failure while attempting to terminalize a no-effect ``PENDING`` activation,
  requiring the live slot to remain reserved until exact recovery;
* after policy allow before fence acquisition;
* after fence acquisition before authorised audit;
* after running/effect intent before final OP-BOUNDARY;
* while session gate is held after final session check but before audit-obligation fsync;
* after audit-obligation publication before filesystem syscall;
* after create publication before directory-fsync receipt;
* after write rename before directory-fsync/receipt;
* after move rename before receipt;
* after delete unlink before receipt;
* after durable adapter receipt before generic effect classification;
* after generic known-effect before post-effect audit/fence release;
* DB failure during terminal/fence release;
* after ``PENDING -> ACTIVE`` before activation post-effect audit;
* after activation audit before activation-closure CAS;
* application main-process ``SIGKILL`` while ``rg`` holds the pinned search descriptor:
  systemd must remove all prior-invocation search descendants before the replacement
  runtime can pass ``SearchChildRecoveryBarrier``; until then ``CHANGE`` and
  ``CONTENT_READ`` both remain blocked;
* process restart with an active/effective session;
* process restart with active-but-activation-incomplete session;
* process restart with expired/untrusted-time session;
* process restart with retained ``uncertain`` mutation.

Expected results prefer conservative retained truth. In particular, pathname presence or
absence after a lost receipt never manufactures ``known_effect``/``known_no_effect``, and
parent process death never proves a search child is gone.

32.5 Concurrency tests
~~~~~~~~~~~~~~~~~~~~~~

Prove:

* two distinct first mutations cannot both own the workspace change fence;
* two distinct first session-begin operations cannot both create live ``PENDING`` rows or
  later become effective; same-key concurrent begin converges to one retained operation;
* same-key concurrent first mutation calls converge to one operation;
* session end/revocation racing a member start either wins the shared authority gate before
  ``call_start`` (zero effect) or loses to the already-linearized start;
* trusted-time expiry discovered while the member holds/requests the session gate blocks
  start even if an earlier pre-gate check was valid;
* audit-obligation fsync cannot create a stale-start window because the session gate
  remains held through ``call_start``;
* required audit failure racing dispatch obeys the process-wide Phase 4 gate;
* content read/search cannot begin while a durable mutation fence owner exists and a new
  changer cannot acquire its fence while a content guard is active;
* after application crash, a replacement runtime cannot admit a changer while any
  prior-invocation search descendant may still hold a pinned workspace descriptor;
* protected-directory rename/exchange by a Binnacle-managed changer cannot race through an
  active recursive search; metadata-only inspect/list remains bounded under the reviewed
  concurrency rules.

32.6 Contract/schema tests
~~~~~~~~~~~~~~~~~~~~~~~~~

Before runtime exposure prove:

* proposed Tool names are unique/non-confusable;
* every input/output JSON Pointer resolves;
* manifest/handler/contract versions agree;
* information/host-confirmation classes match reviewed session semantics;
* protected content exclusions are represented consistently across read/search/mutation;
* a content-read/search profile that permits uncoordinated writers cannot expose those
  Tools unless the promoted contract names a stronger protected-object confinement
  mechanism;
* search/content/change readiness cannot be advertised before the exact service-cgroup
  child-recovery barrier and durable mutation-fence reconciliation succeed;
* live-session-slot uniqueness/current-state errors are represented without disclosing a
  foreign controller's retained session;
* primitive/writer-profile degradation cannot expose a Tool that lacks required safety
  semantics;
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
* ``renameat2(RENAME_NOREPLACE)`` or exact reviewed equivalent for move if move is enabled;
* the accepted local writer-safety profile for replacement/move/delete;
* rename/fsync semantics needed by write/move/delete;
* descriptor-pinned ``ripgrep`` cwd/inherited-FD launch and root-replacement race test;
* application service ``KillMode=control-group``/``SendSIGKILL=yes`` (or reviewed stronger
  equivalent), non-delegated search-child cgroup membership, and a crash/restart run that
  proves a prior ``rg`` cannot survive into workspace access/change readiness;
* ``SearchChildRecoveryBarrier`` cgroup/process-identity verification and fail-closed
  behaviour when stale-member absence cannot be proven;
* ``WorkspaceAccessGate`` protected-directory rename/exchange coordination and restart
  blocking from a retained durable mutation fence;
* the accepted writer model for content-returning read/search, or the exact stronger
  protected-object confinement mechanism if uncoordinated writers are allowed;
* ``ripgrep`` availability/version and bounded execution;
* systemd/service permissions permit exactly the registered source workspace and do not
  accidentally grant protected state.

Real ChatGPT evidence should verify:

* exact catalogue discovery of promoted Phase 6 Tools;
* actual session-start host interaction/authority behaviour;
* no redundant per-member confirmation if the reviewed HOST profile claims session
  semantics;
* bounded source read/search presentation;
* create/write/patch/move/delete entitlement only for operations actually promoted;
* same-key retry and lost-response behaviour;
* session reconnect/restart continuity;
* session end/expiry handling;
* no capability escape to protected/unregistered paths.

If the host cannot safely express the reviewed bounded session authority, operational
Phase 6 remains unsupported for that HOST profile. Do not weaken local policy or silently
fall back to ambient HC0 mutation authority.

34. Holistic invariant pass before review
-----------------------------------------

Before every external review of a new Phase 6 head, inspect the design as one continuous
consequential-operation pipeline rather than waiting for serial comments:

::

   normalize exact request/session/workspace state
     -> caller-key retained lookup or minimal pre-policy durable identity
     -> required received audit
     -> policy
     -> exclusive workspace access/change guard
     -> post-policy exact-self workspace change fence + operation binding
     -> authorised audit
     -> running/effect intent
     -> phase-stable binding across the expected self fence transition
     -> per-operation handoff
     -> session-authority gate
     -> process-wide consequential gate
     -> final session/profile/root/source/target revalidation
     -> durable audit obligation while session gate remains held
     -> gate-owned EffectBoundary.start linearization
     -> immediate durable receipt/effect knowledge
     -> operation-specific domain closure
     -> post-effect audit/obligation closure
     -> fence release or conservative retention
     -> crash/restart reconciliation
     -> caller-binding-first retained retry

The review must additionally walk each mutation kind through:

* normal success;
* stale source/target before start;
* session end/revocation/expiry before and during the final start handoff;
* activation incomplete/audit failure and concurrent distinct session begin while the
  first live slot is ``PENDING``;
* audit failure before start;
* configured root/search-root replacement during ``ripgrep`` launch;
* protected-directory rename/exchange while content read/search traversal is active;
* application crash while ``ripgrep`` holds a pinned descriptor, systemd descendant
  cleanup, startup ``RECOVERY_CLOSED``, and no changer admission before the recovery
  barrier proves prior traversal is gone;
* crash after filesystem syscall but before receipt;
* out-of-band source replacement for write/move/delete;
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
* session activation cannot authorize member work before audit/obligation closure;
* the live-session-slot uniqueness constraint covers both ``PENDING`` and ``ACTIVE`` so
  concurrent distinct begin operations cannot create overlapping authority domains;
* session end/revocation/expiry and member start have one implementable linearization;
* all proposed operational Tools are absent until reviewed contracts/schemas/manifest and
  host-profile reconciliation pass;
* read/search operations are bounded, protected-path aware, symlink-safe, descriptor-
  pinned when a subprocess traverses the workspace, and protected against coordinated
  rename/exchange for their full content-traversal lifetime;
* search-child lifecycle is bound to the application service cgroup, normal guard release
  requires proven termination/reaping, and startup keeps both content and change admission
  recovery-closed until prior-invocation traversal is proven absent;
* content-returning access fails closed when the reviewed writer model cannot keep
  protected-object exclusion stable;
* mutations use exact current identity/version semantics and descriptor-relative
  containment;
* the conservative workspace change fence closes all Binnacle-managed concurrency and is
  explicitly reusable by later Phase 7/8 workspace-changing effects;
* create/move no-overwrite never silently degrades when a primitive is missing;
* write/move/delete local out-of-band-writer limitations are stated truthfully and can
  disable an operation when the reviewed profile does not accept them;
* operation-owned staging cleanup is exact/non-recursive;
* Phase 4 audit/idempotency/final-boundary ordering is preserved exactly;
* retained same-key retry is evaluated before mutable session/filesystem freshness checks;
* session loss before start produces no effect while post-start loss never rewrites truth;
* create/write/patch/move/delete effect/no-effect/uncertain outcomes are representable and
  restart-reconcilable;
* no Raspberry Pi or ChatGPT support fact is fabricated.

36. Implementation/promotion checklist
--------------------------------------

Implementation/promotion remains blocked until:

* real Phase 5 implementation/exit and write-confirmation evidence are current;
* the session-scoped host-authority contract/profile is reviewed and the selected real
  ChatGPT profile passes it;
* the exact Phase 6 operation contracts/schemas/manifest are promoted and validated;
* migration ``0003`` and all persistence constraints pass fresh/upgrade tests, including
  the one-live-session partial unique index across ``PENDING``/``ACTIVE``;
* session authority-gate/access-gate/fence/idempotency/audit/final-boundary fault tests
  pass;
* descriptor-pinned search launch, protected-directory rename/exchange coordination, and
  application-crash/search-child cgroup cleanup/readiness-barrier tests pass;
* candidate-Pi systemd service lifecycle proves no prior search child can survive into a
  reopened workspace access/change gate;
* the content-read/search writer model is accepted, or a stronger reviewed protected-
  object confinement mechanism is verified;
* required no-overwrite primitives are verified on the candidate Pi;
* the reviewed local writer-safety profile explicitly permits each exposed replacement,
  move, and delete contract; otherwise those operations remain disabled;
* Linux containment/search/mutation tests pass on the candidate Pi profile;
* production composition exposes no Phase 6 Tool when any prerequisite fails.

37. Real Phase 6 exit criteria
------------------------------

Do not mark Phase 6 implementation complete until real evidence proves at least:

#. the owner-authorised development session is started and visible to real ChatGPT under
   the reviewed HOST profile;
#. activation closure is complete before any member workspace effect is allowed;
#. ChatGPT inspects/lists/reads/searches the exact registered Binnacle workspace without
   protected-content disclosure, with content access enabled only under the reviewed
   stable protected-object writer/confinement model;
#. ChatGPT performs one controlled source edit with the promoted mutation contract;
#. the new file/object version and content digest are inspected truthfully;
#. ChatGPT reverts/replaces the edit with exactly one admitted effect;
#. same-key retry does not create a duplicate effect;
#. no operation can escape the registered workspace or protected internal paths;
#. session end/expiry blocks new/not-yet-started mutations through the authority gate;
#. reconnect/restart preserves or truthfully rejects the session according to the frozen
   identity/time/activation-closure rules, and a restart during an active search cannot
   admit a changer until the prior search traversal is proven terminated;
#. all evidence is captured from the real Pi/ChatGPT rather than inferred from tests.

Move/delete need not be falsely claimed supported when their independently reviewed
primitive/writer-profile promotion gate is not satisfied; their disabled/degraded status
must be visible and truthful.

38. Implementation order
------------------------

When the evidence gate permits implementation, use this order:

#. reconcile and promote the session-scoped host-authority contract/profile;
#. define/review all Phase 6 operation contracts and input/output schemas;
#. update manifest/docs/evaluation fixtures and pass contract/schema/manifest validation;
#. add migration ``0003`` for sessions/activation closure, the one-live-session
   ``PENDING``/``ACTIVE`` partial unique index, workspace operation metadata, and the
   shared workspace mutation fence;
#. implement domain types and persistence repositories plus live-slot conflict/restart
   integrity tests;
#. implement ``DevelopmentSessionAuthorityGate`` and lock-order tests before member
   mutation adapters;
#. implement registered workspace profile/root identity/protected-content verification;
#. implement the shared ``WorkspaceAccessGate`` + durable change-fence coordinator with
   unconditional startup ``RECOVERY_CLOSED`` posture;
#. implement and verify the application-service search-child cgroup lifecycle plus
   ``SearchChildRecoveryBarrier`` before allowing the access gate to open after restart;
#. implement descriptor-relative inspect/list/read primitives, with content-read guard
   coverage;
#. implement descriptor-pinned typed ``ripgrep`` search, full-lifetime content guard,
   child termination/reaping proof, and launch/protected-directory-rename/restart race
   tests;
#. implement development-session begin/inspect/end orchestration including atomic
   ``PENDING`` slot reservation, activation closure, and fail-safe revocation;
#. implement the mutation final-binding callback on the shared access/change seam;
#. implement create with exact staging ownership/no-replace/fault reconciliation tests;
#. implement write + shared replacement adapter and out-of-band-race tests;
#. implement deterministic patch on top of replacement;
#. implement move only with verified atomic target no-replace and accepted writer profile;
#. implement delete only under its explicit writer-safety promotion rule;
#. integrate exact Phase 4 audit/idempotency/OP-BOUNDARY/effect-knowledge semantics;
#. expose the workspace change-coordination seam for Phase 7/8 extension without granting
   their authority early;
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
* actual feasibility of the selected descriptor-pinned ``ripgrep`` spawn mechanism on the
  candidate Python/kernel/systemd profile;
* candidate-systemd proof that ``KillMode=control-group``/``SendSIGKILL=yes`` (or a
  reviewed stronger equivalent) plus the startup barrier prevents a prior ``rg`` child
  from surviving into workspace content/change readiness;
* whether the candidate deployment can enforce the coordinated/no-uncoordinated-writer
  model required for stable protected-content read/search exclusion, or instead supplies a
  stronger reviewed protected-object confinement mechanism;
* whether the candidate deployment can accept the cooperative/exclusive local writer
  assumption required to expose move/delete without a stronger identity-safe primitive;
* actual ``ripgrep`` version/performance ceilings on the development Pi;
* exact real-host result-size/catalogue-refresh behaviour where it affects promoted
  schemas/limits.

Those items may change host/profile-specific implementation choices or limits. They must
not change the frozen local authority boundary, durable-operation ordering, truthful
uncertainty rule, session/start linearization, protected-content boundary, or prohibition
on workspace escape without a separately reviewed design revision.

40. Deferred work
-----------------

Phase 6 intentionally defers:

* arbitrary workspace registration/mutation by ChatGPT;
* multiple simultaneous Binnacle-managed changing operations per workspace;
* recursive delete and non-empty directory tree move;
* symlink-following development operations;
* generic chmod/chown/xattr/ACL manipulation;
* very-large-file streaming mutation;
* repository indexing/vector search;
* shell command execution;
* semantic Git operations/credentials/signing;
* privileged host changes;
* advanced namespaces/seccomp/MAC/container sandboxing;
* hostile/uncooperative same-UID writer prevention beyond the explicit local-writer model;
* post-Bootstrap multi-user/project workspace policy.

Add those only when they block the self-hosting loop or later evidence justifies a
separately reviewed capability.
