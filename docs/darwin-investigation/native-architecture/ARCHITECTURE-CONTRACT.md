# Darwin native architecture contract

Revision: `binnacle-darwin-r3-interface-1.0.0`.
Source base: `c2234f16bdfb1a17500b99101d3184b797ebb673`.
Status: **proposed; R0 review and Supervisor CR0 freeze pending**.

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

The original manifest does not assign shared contract files or the Darwin
package initializer. B0 is their **exclusive proposed owner**. This document
does not grant a live source lease or expand an already running task card.
The Task Manager must issue a CR0-approved **B0-contract prerequisite card**
for shared declarations and inert package initializers, then allow adapter
cards to consume its accepted commit. B0's later integration card still follows
A2–A6/T0. The two B0 phases cannot run concurrently. This resolves the otherwise
circular dependency on shared declarations without creating a second writer.

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

## Typed availability and errors

`CapabilityState` has exactly four values:

| State | Meaning | Authority |
| --- | --- | --- |
| `AVAILABLE` | Implemented and observed within the stated scope | Only that scope, subject to current identity checks |
| `LIMITED` | Supported subset with explicit scope and exclusions | Never implies full-job or full-OS guarantees |
| `UNKNOWN` | Current evidence is insufficient, missing or contradictory | No destructive action or inference of absence |
| `UNAVAILABLE` | Unsupported mechanism or deliberately disabled operation | Explicit refusal before side effects |

`Capability(state, reason_code, scope, evidence_id)` is immutable. Runtime state
is distinct from the target state `full/limited/unavailable` in the decision
file. A planned limited capability starts unavailable until its implementation
and required evidence exist. A missing observation stays unknown; it cannot be
converted to a measured zero, dead process, empty scope, or successful stop.

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
bounded support and disabled Commands. Preserve argument and output schemas;
do not claim identical Linux composite digests when Darwin prose differs.

| Tool | macOS target | Required behavior |
| --- | --- | --- |
| `read_file` | limited | Read only authorized opened regular-file bytes, retaining existing limits and decoding policy |
| `list_files` | limited | Enumerate from captured directory grants; bounded traversal, explicit denial |
| `write_file` | limited | Descriptor-relative replacement with verified parent, no symlink following |
| `edit_file` | limited | Existing exact-string policy on authorized bytes, conflict detection and descriptor-relative replacement |
| `search_text` | limited | Search only authorized opened file bytes with bounded ripgrep execution |
| `run_command` | unavailable | Fail with `darwin_commands_unavailable` before launching any job |
| `job_status` | limited | Read authorized Darwin history/output; unresolved active state remains unknown |
| `stop_job` | unavailable | Fail with `darwin_commands_unavailable`; no numeric PID/PGID signal fallback |

This deliberately declines full native Commands for this revision. A2 may
implement and test finite owned-child/witness mechanisms, but those tests do
not enable the public shell or stop tools. A scope increase needs new native
membership, signal API, durable stop and loss evidence plus independent review
and an explicit revised CR0/CR1 decision. E0 must assert unavailable errors as
well as the real supported calls; eight listed tools are not eight functional
tools. Darwin messages must not recommend disabled Commands as a workaround.

## Process authority, stop durability and recovery

A2 owns `process_backend`, `process_authority`, and `witness_protocol` under
`binnacle.platform.darwin`. They consume B0's portable declarations and A3's
abstract authenticated channel. `DarwinProcessBackend` implements the unchanged
`ProcessBackend` plus `authority(job_id) -> AuthorityObservation`.

`OwnerGeneration(manager_epoch, witness_epoch, job_id)` identifies an epoch; it
is neither a bearer credential nor a process capability. An
`AuthorityObservation` contains capability, generation, membership closure, and
`can_signal`. This revision always exposes `can_signal=False` in shipped Darwin
code. A live trusted channel and positive enrollment are prerequisites for any
future authority. A pid, pgid, birth time, boot identifier, launchd label or
persisted record alone is never sufficient.

Manager loss with a retained witness permits only authenticated observation and
explicit generation reconciliation. Loss of both manager and witness yields
`UNKNOWN`, `membership_closed=False`, and disabled stop. `identity_from_record`
returns no usable identity without live proof. No historic PID/PGID adoption,
`killpg` fallback, private `proc_signal_with_audittoken` support, or cross-version
libproc stability claim is permitted. The supplied SDK evidence labels those
process interfaces private; symbol presence and finite tests are not public
API guarantees.

Legacy boolean/list interfaces cannot encode uncertainty. Darwin must raise
`AuthorityUnknown` rather than report `alive=False`, empty descendants or
completed exit from failed observation. B0 prevents such uncertainty from
reaching existing Linux-style negative-to-exit inference. History remains
readable, but unknown jobs never become stopped merely because the leader is
absent. Restricted public Commands avoid bootstrapping the existing Linux job
engine through a default backend.

A1 owns `features/commands/job_stop.py` and its exact assigned tests. Its stop
policy must establish durable admission **before the first signal**, use one
validated lease through TERM/KILL, and synchronize stop/reaper state by job
and owner generation. Failed admission means no signal. After partial delivery,
failed persistence, owner loss or uncertain target closure, report failure or
unknown; leader exit alone cannot produce whole-job success. Reaper and stop
must not overwrite each other's durable outcome or reap the same child twice.
B0 alone owns shared owner/store/reaper wiring. A1 supplies the focused policy
and shared-file integration requirements; no concurrent A1 edits to B0 paths.
The additive `StopIntent`/`StopReceipt` and `stop_with_intent` declarations in the
machine contract define the seam. Existing `stop_embedded` is retained for
compatibility; B0 must route real new stop admission through the reviewed seam.

## Descriptor-rooted Files and Search

A4 implements `FileAccess` and `SearchAccess`. B0 connects these to the existing
Files/Search tool implementations; A4 never edits their shared registration or
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
| A1 | Linux stop admission/closure policy in assigned stop module and focused tests |
| A2 | Darwin process observation, witness loss, safe disabled public Commands |
| A3 | Runtime generations, authenticated IPC and test-owned launchd lifecycle |
| A4 | Opened-root Files/Search native mechanics and negative races |
| A5 | Private log epochs, redaction, scoped metrics and unavailable totals |
| A6 | Darwin plist/provisioning transaction, package and test install CLI |
| T0 | Explicit native test collection inventory and retained Linux assertions |
| B0 | Shared declarations/initializers first; later single-writer Core/composition integration |
| E0 | Real authenticated native MCP calls, denial cases and positive teardown |

The manifest names native test files without the default `test_` prefix. They
must be passed as explicit pytest file selectors until B0 installs a narrowly
scoped collection hook from T0's design. Collection receipts must show exact
node IDs, not only a green exit code. Never blanket-skip Darwin adapters or
weaken the original Linux assertions. B0 owns common test initializers and
configuration; T0 cannot edit those shared files concurrently.

A0 validates JSON structure, cross-file references, parseable declarations,
existing signature/hash pins, exact ownership expansion and canonical aliases.
It runs static import analysis and read-only Linux source/wire-pin comparison.
Negative fixtures reject a second shared-file owner and an attempted private
libproc/cross-version signal claim. These checks prove document consistency;
they do not prove native safety, current macOS behavior, R0 approval or CR0 freeze.
No Linux execution is needed for this documentation-only commit.

Authors subsequently run their task-card native and Linux focused tests at their
own exact source SHAs. Native signal authority, IPC, filesystem races, launchd
cleanup and provisioning require independent source-bound review. B0 integration
must regenerate/check the actual OS6 ownership inventory through its repository
workflow and obtain an exact-path amendment for generated outputs. Full suites,
coverage, final package/CI and release belong to the later frozen QA/release
lanes. No A0 result authorizes deployment or a stable Job Manager restart.
