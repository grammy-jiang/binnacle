# Darwin native architecture contract

Revision: `binnacle-darwin-r4-interface-1.2.0` (proposed; see the 1.2.0 section).
Previous revision: `binnacle-darwin-r3-interface-1.1.0`.
Source base: `c2234f16bdfb1a17500b99101d3184b797ebb673`.
Revision base: `372c5036595bcb7deaa38dce9d3b123725f21ee1`.
Implementation-lane base: `068114f87e9d0159471d0bd001683457ad4c4368`.
Status: **revised proposal; exact signed-commit CR0 approval pending**.
Overall decision: **FULL_PARITY_NO_GO**, independent of limited-component approval.

The 1.1.0 changes resolve A0-R0-01 through A0-R0-03, R0 categories C2/C4/C9,
and CR0-01 through CR0-07. Each revised rule cites these IDs below. Their exact
review and source path/SHA-256 references are in `revision_evidence` in each
JSON document and the finding map in [REVISION-NOTES.md](REVISION-NOTES.md).
The original source base above remains the immutable Linux evidence base;
SD-10's implementation base changes only the branch-sync workflow, not these
product sources. This revision does not certify native execution.

This is an implementation contract, not a claim that the native adapters exist,
passed tests, or are approved for release. `api-contract.json` is the normative
machine interface; `PATH-OWNERS.json` is the finite source ownership map;
`CAPABILITY-DECISION.json` records target scope and historical evidence hashes.
These four documents form one revision. A disagreement requires correction and
CR0 review, not an author's local interpretation.

## Freeze and dispatch

CR0 alone freezes this revision after source-bound R0 review. The Task Manager
must publish `FROZEN-API-CONTRACT.json` with the revision, documentation commit,
SHA-256 of all four documents, and the CR0 receipt. Authors consume that exact
packet. An interface, capability, or ownership change requires a new revision
and explicit task-card amendment before another writer starts.

**CR0-05/CR0-07:** B0 remains the sole shared-contract declaration owner.
The exact `contract_precursor_card.write_paths` in `PATH-OWNERS.json` define
**B0a**: shared declarations and inert initializers only. It starts after CR0
APPROVE. A1 may author the Linux repair concurrently from this frozen seam, but
consumes the accepted B0a commit before compile/integration checks; it cannot
copy shared declarations into its own files. A2–A6/T0 wait for accepted B0a.
B0a and later B0 integration are sequential phases of one writer. No concrete
adapter, fixture behavior, tool wiring or Linux job engine edit belongs to B0a.
The Task Manager must issue the exact amended cards before dispatch.

**CR0-03:** The frozen packet and every CR0–CR3/handoff/release packet carry
`full_parity=FULL_PARITY_NO_GO` and the tool-by-tool limited/unavailable scope,
along with the documentation commit, all four hashes and decision receipts.
A limited-component acceptance cannot change that overall decision.

The exact-path map narrows original globs to existing base-tree matches and
explicit new files. Other files are read-only. Additional modules, tests,
fixtures, inventory outputs or `uv.lock` edits require an amended path list and
fresh overlap check. Neither a glob prefix nor this design authorizes arbitrary
future files. Source-owner cards remain subordinate to CR0 and Task Manager
leases. A0 changes documentation only.

## Composition and Linux invariants

FastMCP owns the root, the three child servers, Providers, Transforms,
Middleware, authentication, request dependencies and lifecycle. Binnacle owns
ordinary domain policy and durable jobs. Platform adapters implement native
mechanisms. There is no FeatureRegistry, custom Provider router, replacement
MCP lifecycle, or substitution of FastMCP Tasks for durable jobs.

`binnacle.platform.composition` remains the only host selector. Its factories
lazily import the selected adapter; unknown operating systems raise
`UnsupportedHostOS`. Linux factories and `create_linux_provisioner` retain
existing behavior. Darwin imports must not eagerly construct Linux jobs,
procfs, cgroups, systemd or journald dependencies. Package initializers are inert.
`application.create_application` remains ordinary dependency injection and
retains native child-server mounts and middleware/transform order.

The machine contract pins every existing portable declaration and file hash.
`ProcessBackend`, `ResourceAccounting`, `RuntimePaths`, service interfaces,
`CommandBackend` and Linux `UnitProvisioner` retain their existing methods,
defaults and exceptions. New typed interfaces are additive; Linux dictionary
shapes do not acquire capability fields. Linux MCP descriptions, input/output
schemas, annotations, ordering, instructions and profile visibility remain
pinned to G0's eight/default and six/ChatGPT composite surface hashes. Existing
four-profile expectations remain `8/6/6/8`.

Linux RPC version 1, spool records including historical pid/pgid/starttime,
combined output bytes, cursors, unit templates and stable-manager restart gate
remain unchanged. Existing Linux safety defects require A1's independently
reviewed repair; source equality is not evidence that those defects are safe.
No Linux production host or service is touched by A0.

## Revision 1.2.0: durable-job owner and release scope

Source base `9f958798bf9cbe289ad4cc8daa0714bbb8d0a305` (R4 lane J0). This
section adds to 1.1.0 and replaces only the unconditional stop_job rule.

- **Owner kinds.** `JobOwnerKind` is `manager` or `embedded`. On Darwin,
  `auto` and `manager` compose the manager. `embedded` exists only by explicit
  configuration, for tests and rollback (JCR-2).
- **Rows follow the composed owner.** `release_scope_for_owner` returns the
  embedded table (today's reviewed LIMITED rows) or the manager table. The
  choice never depends on whether the manager answers. An unreachable manager
  gives the Linux per-call error `job manager unavailable`. There is no
  fallback to embedded execution or LIMITED rows.
- **Full with disclosure.** No new capability state. A manager command row is
  `AVAILABLE` with `decision_target="full_with_disclosure"` and disclosures
  D-1, D-2 and `descendants_unverified=true`. Until J-CR these rows are
  committed `UNAVAILABLE`.
- **Owner-conditioned invariant.** Embedded: stop_job stays `UNAVAILABLE` on
  every host. Manager: each command row is only `UNAVAILABLE` or `AVAILABLE`;
  job_status and stop_job need run_command `AVAILABLE`; no embedded
  `ForegroundExecution` is composed.
- **DarwinJobOwner.** One instance per manager process. `spawn` uses
  `posix_spawn(setsid=True)` and arms kqueue `NOTE_EXIT` before it returns.
  `reap_exits` is the only `waitpid` caller (SIGCHLD stays `SIG_DFL`). `wait`
  waits on the reaper. `signal_owned_group` signals an owned pgid only while
  membership is proven. `authority` is `OWNED` or `UNKNOWN`; a pid read from
  disk is never adopted. `close` is the normal stop: owned groups are
  terminated, then killed, reaped and recorded as `owner_restart` (no orphans).

## Typed availability and errors

`CapabilityState` has exactly four values:

| State | Meaning | Authority |
| --- | --- | --- |
| `AVAILABLE` | Implemented and observed within the stated scope | Only that scope, subject to current identity checks |
| `LIMITED` | Supported subset with explicit scope and exclusions | Never implies full-job or full-OS guarantees |
| `UNKNOWN` | Current evidence is insufficient, missing or contradictory | No destructive action or inference of absence |
| `UNAVAILABLE` | Unsupported mechanism or deliberately disabled operation | Explicit refusal before side effects |

**A0-R0-01 / CR0-01:** `Capability(state, reason_code, scope, evidence_id)` is
immutable. Target policy (`full/limited/unavailable`) never grants runtime
authority. Every proposed Darwin capability and all eight tools have runtime
`UNAVAILABLE` and `runtime_enabled=false` in this packet. No adapter is accepted
here. To materialize even `LIMITED`, require implemented adapter and wiring,
exact-source native positive/negative receipts, independent R1/R2 review,
applicable CR1/CR2 approval, the CR0 frozen revision, and current generation and
operation authority. These requirements are conjunctive. After implementation,
missing or contradictory current evidence yields `UNKNOWN` and disables the
operation; it cannot become measured zero, dead process, empty scope or success.
`stop_job` remains policy-disabled. CR0-04 permits only the specified foreground
`run_command` target after A2 implementation and R1 **and** CR1 approval.

`NativeCapabilityError` carries a stable code and typed capability. Its concrete
subclasses are `CapabilityUnavailable`, `AuthorityUnknown`,
`GenerationMismatch`, `PermissionDenied`, `UnsafePath`, `CursorExpired` and
`BudgetExceeded`. Existing `UnverifiedJobProcess`, `JobSignalDeliveryError` and
`ServiceLogError` remain valid at their original boundaries. B0 translates
native errors at the existing `CodedToolError`/`CommandFailure` MCP boundary.
Errors use sanitized reasons and never include credentials or raw secret-bearing
native stderr. Unavailable calls are MCP errors, not success-shaped placeholders.

## Eight-tool contract for this revision

All eight names remain registered in the default native surface. Existing
client visibility policy still applies; registration does not mean operational
parity. Darwin descriptions and server instructions must explicitly describe
bounded support, foreground limits and disabled `stop_job`. Preserve argument
schemas; CR0-04 adds only the Darwin `run_command` output flag described below;
do not claim identical Linux composite digests when Darwin prose differs.

| Tool | macOS target | Required behavior |
| --- | --- | --- |
| `read_file` | limited | Read only authorized opened regular-file bytes, retaining existing limits and decoding policy |
| `list_files` | limited | Enumerate from captured directory grants; bounded traversal, explicit denial |
| `write_file` | limited | Descriptor-relative replacement with verified parent, no symlink following |
| `edit_file` | limited | Existing exact-string policy on authorized bytes, conflict detection and descriptor-relative replacement |
| `search_text` | limited | Search only authorized opened file bytes with bounded ripgrep execution |
| `run_command` | limited target; runtime unavailable | After A2/R1/CR1 acceptance: bounded foreground owned-child execution; always disclose `descendants_unverified=true` |
| `job_status` | limited | Read authorized Darwin history/output; unresolved active state remains unknown |
| `stop_job` | unavailable | Fail with `darwin_commands_unavailable`; no numeric PID/PGID signal fallback |

**A0-R0-03 / CR0-03:** This is **FULL_PARITY_NO_GO**. The table lists targets,
not enabled operations. All runtime defaults are unavailable until the exact
scope is accepted. Files/Search and history are bounded targets; public durable
background jobs and `stop_job` are unavailable. E0 must test real accepted calls
and denial cases; eight registered names do not imply eight enabled tools.
Descriptions and errors must never recommend an unavailable operation.

**CR0-04 — foreground owned-child execution:** A2 implements the separate
`ForegroundExecution.run_foreground(ForegroundRequest, cancel)` entrypoint in
`DarwinProcessBackend`. Its ordinary durable `ProcessBackend.launch` and signal
methods remain disabled. B0 injects the accepted foreground adapter and routes
Darwin `tools/run_command.py::run_command_impl` through
`command_execution.run_foreground_command` before the Linux `DispatchPlan`,
auto-background policy or `CommandBackend.start_and_wait`. This retains Linux
behavior and prevents an accidental durable-engine fallback.

The live spawning process uses public `posix_spawn` with a new process group
(`setpgroup=0`) for `bash -c`. Only that process may signal that group, and only
while its leader remains an unreaped direct child. A2 serializes every signal
with its sole reap operation: no second waiter, implicit `Popen.poll`, or
SIGCHLD handler may consume the child. After reap, invalidate authority before
unlocking and never signal again. Timeout/cancel cleanup uses bounded TERM/KILL
while the leader remains unreaped, then one reap. Failures report an error and
uncertainty; they never imply complete descendant cleanup.

Explicit `background=true` or a requested wait above the captured foreground
limit returns `darwin_background_jobs_unavailable` before spawn. If a group
already exists when such a condition is detected, clean up that owned group
first under the same unreaped-leader rule. Actual execution reaching
`min(wait_seconds, foreground_limit_s)` also cleans up and returns that error,
without auto-backgrounding. The limit is positive and at most the captured
`settings.wait_max_s` (base maximum 50 seconds). Cancellation uses the same
bounded cleanup before teardown. Output drain is bounded even when an escaped
descendant keeps a pipe open; close it and report truncation on exhaustion.

Descendants that leave the group, including `setsid` or double fork, are
unverified. Every successful Darwin result has `descendants_unverified=true`
in its typed result, structured payload and Darwin-only output schema, and its
text describes leader completion only. This is the explicit CR0-04 exception
to equal Darwin output schemas; Linux schemas and hashes are unchanged. Error
text after spawn carries the same scope warning. Never return a Darwin
`running`/`background_job=true` success. Owner death may leave a command
unsupervised; later status is `UNKNOWN` absent already committed leader-only
history, and a restarted owner never adopts or signals it. `job_status` exposes
history/output only. `stop_job` stays unavailable even after foreground approval.

The default stays `UNAVAILABLE` unless A2 implements and R1 plus CR1 approve this
exact scope with B0 wiring. CR0 architecture approval alone does not enable it.
If CR1 declines, the unavailable behavior remains the fallback. Native tests
must cover reap/cancel races, post-reap rejection, group escapes, owner death,
output drain, foreground expiry and zero-spawn refusal cases.

## Process authority, stop durability and recovery

A2 owns `process_backend`, `process_authority`, and `witness_protocol` under
`binnacle.platform.darwin`. They consume B0's portable declarations and A3's
abstract authenticated channel. `DarwinProcessBackend` implements the unchanged
`ProcessBackend` plus `authority(job_id) -> AuthorityObservation`.

`OwnerGeneration(manager_epoch, witness_epoch, job_id)` identifies an epoch; it
is neither a bearer credential nor a process capability. An
`AuthorityObservation` contains capability, generation, membership closure, and
`can_signal`. For durable/history/witness observations this revision exposes
`can_signal=False`. CR0-04 foreground authority is a separate ephemeral live-parent
capability and never a transferable observation or public `stop_job` right.
A live trusted channel and positive enrollment are prerequisites for future
durable/witness authority. A pid, pgid, birth time, boot identifier, launchd label
or persisted record alone is never sufficient.

Manager loss with a retained witness permits only authenticated observation and
explicit generation reconciliation. Loss of both manager and witness yields
`UNKNOWN`, `membership_closed=False`, and disabled stop. `identity_from_record`
returns no usable identity without live proof. No historic PID/PGID adoption,
recovery-time numeric `killpg` fallback, private `proc_signal_with_audittoken`
support, or cross-version libproc stability claim is permitted. The supplied SDK evidence labels those
process interfaces private; symbol presence and finite tests are not public
API guarantees.

Legacy boolean/list interfaces cannot encode uncertainty. Darwin must raise
`AuthorityUnknown` rather than report `alive=False`, empty descendants or
completed exit from failed observation. B0 prevents such uncertainty from
reaching existing Linux-style negative-to-exit inference. History remains
readable, but unknown jobs never become stopped merely because the leader is
absent. The separate foreground entrypoint and restricted history backend avoid
bootstrapping the existing Linux job engine through a default backend.

**A0-R0-02 / CR0-02 / R0-C2 / CR0-05:** A1 exclusively owns Linux
`job_stop`, `stop_coordinator`, `job_store`, `job_owner`, `jobs`, `job_manager`,
`job_client`, and `job_resource_history`, plus the exact tests in PATH-OWNERS.
B0 never edits those paths. They are the Linux durable engine; Darwin uses its
separate foreground/history backend. B0a owns only portable seam declarations.
B0's shared tool consumers preserve the controlled errors from A1's guarded
APIs. The normative `stop_protocol` in `api-contract.json` governs all paths.

`admit` returns a `StopAdmission`: exactly one caller receives a nontransferable
`StopExecutor`; all concurrent callers for the same job incarnation join the
same unresolved `StopIntent`, regardless of call ID. A joiner cannot open a
lease or signal. The intent includes job incarnation, owner epoch and operation
ID, but those strings are not authority. Every lease signal checks the live
executor fence. No successor may run while an earlier executor might signal.

Admission durably records immutable unresolved prepare state before any signal:
write, file sync, atomic replacement and directory sync (including any newly
created ancestor). Failed post-replace directory sync is a failed admission,
with zero signals. All readers/writers/reapers use one stable interprocess
transaction boundary; an `RLock` alone is insufficient. Release metadata locks
before signals or waits so the reaper can progress. One validated signal lease
spans TERM/KILL; one owning reaper consumes child exit. Reaper exit evidence and
resource-history merges preserve unresolved prepare/partial flags and never
resolve stop on leader exit alone.

Resolution requires the **same admitted operation**, full authorized target
closure with birth admission closed, terminal leader evidence, and positive
executor quiescence. Close leases and wait for every in-flight signal before
resolution. Persist and sync resolution file plus directory before returning
`outcome_persisted=true`. Visible closed bytes after failed directory sync are
uncommitted; leave prepare unresolved and invalidate cached success. Recovery
must check matching prepare/resolution, closure evidence and old-executor
quiescence and re-sync file/directory successfully before accepting those bytes.
A new epoch, timeout, missing PID or broken socket is not quiescence proof.

Every terminal path (`stop` retries, job state/list, `await_exit`, RPC before
`ok=true`, local fallback, status, recovery) invokes `terminal_guard` in the same
transaction/version as its metadata read. Missing/corrupt records, unresolved
legacy `stop_requested`/`stop_signal_partial`, uncommitted resolution, or unknown
ownership produce controlled existing errors; no new Linux wire state is
needed. Retention keeps unresolved jobs and their required evidence and checks
eligibility again under the transaction before deletion. Unknown jobs still
block stable-manager restart/rollback. An unchanged old owner cannot be credited
with these repaired guarantees; reverse ABI checks prove compatibility only.
A1 must pass STOP-ADMISSION, STOP-REAPER, STOP-RESOLUTION, STOP-PIDFD and both RPC
compatibility directions before R1/CR1 Linux stop acceptance.

## Descriptor-rooted Files and Search

**R0-C4 / CR0-06:** A4 implements `FileAccess` and `SearchAccess`. B0 connects
these to the existing Files/Search tool implementations; A4 never edits their shared registration or
Core modules. Tool schemas, text decoding, exact edit matching and budgets stay
Core responsibilities. A4 owns filesystem opening, traversal and safe native
ripgrep input. Linux's current path implementation remains its default.

Each application generation captures canonical configured roots and opens a
`RootGrant`. Relative component traversal uses directory descriptors and
no-follow checks. Reject escaping components, unsupported symlinks, special
files and ambiguous authority. An authorization check followed by reopening a
pathname is forbidden. TCC or permission refusal becomes explicit denial; when
errno does not distinguish TCC from permissions, report permission denial with
TCC as a possible cause, not a fabricated confirmed diagnosis. No permission
escalation or automatic Full Disk Access request is allowed.

The supported model is **opened-object authority**: a retained root descriptor
continues to identify that root object after rename; a replacement at its old
pathname is not granted. This is not continuous pathname containment or a
hostile same-UID sandbox. The task card must preserve this documented semantic
choice in moved-root tests. Grants and open files close deterministically at
request/application teardown. No pathname-derived error hint may open an
unauthorized ancestor.

The `file_tool_wiring` map pins exact B0 application, child-server, registration
and implementation methods. B0 injects grants and adapters before any legacy
pathname check. Request-to-grant selection is lexical and performs no filesystem
I/O. On Darwin every content/stat/traversal/mkdir/hint operation stays inside
the adapter; a missing adapter refuses the call.

| Tool | Descriptor-owning entrypoints (A4; wired by B0) |
| --- | --- |
| `read_file` | `open_read` → `metadata`/bounded `read` → `close`; safe `nearby_hint` on failure |
| `list_files` | `list_entries(grant, ListRequest)` covers one-level and recursive glob listing |
| `write_file` | `write_bytes(create_parents=True)` covers mkdir, replace and `WriteReceipt` |
| `edit_file` | `open_read`/bounded `read`, Core matching, `write_bytes(expected_sha256=...)` with no parent creation |
| `search_text` | `SearchAccess.search` owns traversal, file opens, rg stdin and cleanup |

`OpenedFile.metadata` uses that file's descriptor. Listing has visit/time/result
budgets and explicit truncation; it never delegates to recursive pathname
`rg --files`. Parent creation uses descriptor-relative `mkdir`, followed by
no-follow open/validation for every component, with a finite parent count.
A failed write can leave newly created parents; no transaction-wide rollback is
claimed. `nearby_hint` uses only an authorized existing parent and bounded
entries; a denied hint preserves the original error without ancestor probing.
`WriteReceipt` obtains prior size and created/overwritten status at the adapter
write step. Core treats display paths as text, never `Path` authority.

Writes use a verified parent descriptor, bounded temporary regular file,
flush/fsync as required, descriptor-relative atomic replacement and precise
cleanup. A symlink destination is refused. Existing hardlinked content is not
mutated in place. `expected_sha256` detects observed edit conflicts; it is not
an atomic compare-and-swap against a malicious concurrent writer. Do not claim
power-loss durability or adversarial writer serialization from rename alone.

Search enumerates authorized files through the grant, opens each file safely,
and feeds its bytes to bounded `rg --json` stdin execution. Remap stdin labels
to authorized relative display paths. Passing a previously checked root path to
recursive ripgrep, or relying on a directory `/dev/fd` path as confinement, is
not allowed. A4 must prove glob, ignore, hidden-file, case, binary, context,
no-match, error and truncation behavior. Unsupported policy cases return explicit
errors; denial is never silently reported as no match. Cancel/timeout closes
pipes and reaps the one owned ripgrep child. No general process-tree stop claim
is inferred from this bounded helper lifetime.

## Services, IPC and provisioning

A3 owns `generation_runtime`, `ipc_transport`, and `service_launchd`. Runtime
paths and persistent state are separate. Validate UID, private directory modes,
opened inode identity, symlink ancestors and AF_UNIX path length. Fail explicitly
if a configured private root is unusable. Do not adopt a foreign endpoint or
blindly unlink an unresponsive socket. Two starters must produce one owner and
an explicit refusal, never two managers.

A `ServiceLease` binds UID, label, generation, and root device/inode. Both ends
of a private AF_UNIX channel validate peer identity and a fresh generation-bound
challenge before any RPC. Secrets never enter argv/logs. Same-UID permissions,
markers and locks protect a cooperative account; they are not security against
a malicious same-UID process that can copy secrets or replace writable paths.
Darwin's versioned authentication envelope carries unchanged RPC v1 application
payloads. Linux endpoints and their framing remain unchanged.

Readiness requires an authenticated generation-specific ping. A launchd status
or socket pathname alone does not prove ready. The stable Job Manager and MCP
frontend have distinct test-owned labels. Frontend restart must not restart the
manager. Manager restart or rollback refuses active **or unknown** durable-job
state; the existing quiet gate is never bypassed.

A6 owns pure plist rendering and `DarwinProvisioner`, consuming A3's lifecycle
implementation. `plan` returns immutable bytes/path/previous-digest intent;
`apply` and `rollback` revalidate the exact lease and current file before changing
it. No second launchctl implementation in A6. Rollback positively verifies the
owned label, child processes and socket are gone and restores only the exact
owned prior bytes. Foreign state is preserved. `ServiceReceipt.absent=False`
never counts as successful teardown.

The new `NativeProvisioner` is separate from the existing systemd-oriented
`UnitProvisioner`; Linux CLI options and templates remain unchanged. The test
CLI lives under `deployment.darwin.setup` with explicit root/label and
plan/apply/rollback commands. No global install, login item, privileged helper,
account mutation or claim of logout/FileVault persistence belongs to this lane.
A6's wheel/sdist smoke is unprivileged and test-owned.

The initial session envelope is awake, unlocked and a verified user domain.
The N5 records contain corrections and bounded endpoint observations; neither
closed-lid SSH nor FileVault enabled proves progress through real sleep, logout,
preunlock, or unmeasured transitions. Those guarantees remain unavailable.

## Metrics and private logs

A5 implements `DarwinResourceAccounting`, `ScopedMetrics`,
`PrivateServiceLogSource` and cursor validation. The existing `ResourceAccounting`
compatibility facade does not invent cgroups: legacy snapshot is empty, creation
returns no identity, `wait_empty` is false, and unknown non-null identities cannot
be cleaned. The new scoped metric map explicitly supplies typed unavailable
values. B0 must not render the empty compatibility map as measured zero totals.

`MetricValue` includes state, nullable numeric value, units, scope, sample time
and final/sample distinction. Whole-job CPU, current/peak memory, swap, PID
counts, I/O totals, OOM, final history completeness and empty-scope proof are
unavailable. The decision file enumerates the historical N6 fields separately.
Available direct-child `wait4` observations come from one owning reaper; no
second collector consumes child exit. Private libproc sampling is disabled.
Missing/restarted samples are unknown and null, not zero. Actual measured zero
is permitted only for an available value in its named scope.

Private service logs have generation, stream epoch, device/inode and byte offset.
Writer restart, truncation, rotation and missing coverage invalidate or explicitly
mark a gap; size alone cannot detect truncate-and-regrow. Read budgets cover bytes
and lines. Redact before persistence and preserve private directory/file modes.
`read_window` raises `ServiceLogError` when requested completeness cannot be
established. Missing records do not prove event absence. Log cursors do not
change durable job output byte cursors or Linux journal acquisition.

## Responsibilities and verification

| Lane | Exclusive responsibility |
| --- | --- |
| A1 | Entire Linux stop/store/owner/reaper/RPC/retention repair and assigned tests |
| A2 | Darwin foreground owned-child execution, process observation and witness loss; runtime gated |
| A3 | Runtime generations, authenticated IPC and test-owned launchd lifecycle |
| A4 | Opened-root Files/Search native mechanics and negative races |
| A5 | Private log epochs, redaction, scoped metrics and unavailable totals |
| A6 | Darwin plist/provisioning transaction, package and test install CLI |
| T0 | Explicit native test collection inventory and retained Linux assertions |
| B0 | B0a declarations first, then shared tool/composition wiring; never A1 Linux engine paths |
| E0 | Real authenticated native MCP calls, denial cases and positive teardown |

**R0-C9 / CR0-07:** All new native test modules now have `test_` prefixes.
No custom collection hook is permitted. PATH-OWNERS lists exact replacements;
the Task Manager must amend lane cards (including T0) before dispatch. T0 proves
ordinary discovery with exact collected node IDs once the tests exist. A0's
filename validation is not a collection receipt for unimplemented tests. Never
blanket-skip Darwin adapters or weaken original Linux assertions. B0 owns common
initializers/configuration; T0 cannot edit those shared files concurrently.

A0 validates JSON structure, cross-file references, parseable declarations,
existing signature/hash pins, exact ownership expansion and canonical aliases.
It runs static import analysis and read-only Linux source/wire-pin comparison.
Negative fixtures reject a second shared-file owner, B0 edits to A1 Linux paths,
an attempted private libproc/cross-version signal claim, premature runtime
enablement, a stop_job promotion and non-discoverable test filenames. These
checks prove document consistency; they do not prove native safety, current macOS behavior, R0 approval or CR0 freeze.
No Linux execution is needed for this documentation-only commit.

Authors subsequently run their task-card native and Linux focused tests at their
own exact source SHAs. Native signal authority, IPC, filesystem races, launchd
cleanup and provisioning require independent source-bound review. B0 integration
must regenerate/check the actual OS6 ownership inventory through its repository
workflow and obtain an exact-path amendment for generated outputs. Full suites,
coverage, final package/CI and release belong to the later frozen QA/release
lanes. No A0 result authorizes deployment or a stable Job Manager restart.
