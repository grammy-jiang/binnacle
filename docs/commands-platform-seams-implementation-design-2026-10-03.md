# Commands and platform seams — G3 implementation design — 2026-10-03

Status: **implementing; G3.2b run extraction passed, status extraction next**.

This is the execution design for Group 3 only. The control document is
`docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`.
G0, G1, and G2 are done. This design does not authorize implementation,
integration, deployment, or a job-manager restart. The coordinator reviews the
design commit before starting a separate implementation worktree.

## 1. Baseline, evidence, and objective

The deployed and design baseline is
`68e690d3fd53cc8f83463a2505fe6d3829e62ea2`. The design branch is
`design/g3-commands-platform-seams-2026-10-03`, in
`/home/grammy-jiang/Projects/binnacle-g3-commands-design`.
This task makes no changes in production or any existing evidence worktree.

G3 makes three internal ownership boundaries explicit:

1. Commands adapters translate MCP requests/results around small command use
   cases, rather than reaching into job storage and owner mechanics.
2. A process contract isolates Linux launch, identity, inspection, and signaling.
3. A separate optional accounting contract isolates cgroup mechanics. Durable
   resource-history policy stays with Binnacle's job domain.

Keep the existing durable-job engine and its compatibility functions while
moving one responsibility at a time. Do not replace it with a new engine or a
single `CommandService` that owns settings, storage, processes, and transport.

### 1.1 Governing inputs

Read `AGENTS.md`, `DEVELOPMENT.md`, `docs/testing.md`, and
`docs/quality-gates.md` before implementation. Also read:

- the implementation master, especially G3 scope and the per-group template;
- `docs/platform-neutral-architecture-design-2026-10-02.md`, especially
  Commands, process/resource contracts, and Binnacle ownership;
- `docs/fastmcp-native-architecture-investigation-2026-10-02.md`, especially
  dependency/lifespan boundaries and Tasks;
- `docs/fastmcp-native-refactor-high-level-plan-2026-10-02.md`, especially
  command-domain, process, and resource steps;
- the final G1/G2 designs and deployed G2 construction tests;
- `docs/tools/run_command.md` and the current job-spool compatibility fixtures.

The three architecture inputs still have user-owned, untracked production
copies. Read them there without modifying, moving, staging, or deleting them.
Their byte copies and hashes are included in the external review evidence.

### 1.2 Measured design evidence

Evidence directory, outside all Git worktrees:

```text
/home/grammy-jiang/.local/state/binnacle/g3-design-20261003T013558Z-a2ai0zhz
```

| Check | Observed result |
| --- | --- |
| Initial design tree / doctor | Clean `68e690d`; 9/9 doctor checks |
| Remote refs, read with `git ls-remote` | `master` and `proof-of-concept` both `68e690d` |
| Offline lock / runtime | Lock exit 0; FastMCP and slim 4.0.10; MCP and MCP-types 2.1.1 |
| Commands/jobs focused baseline | 314 passed, seed 12345; exact invocation in `baseline-focused.json` |
| Architecture / imports / strict size | 104 modules, no forbidden imports; 7 contracts kept; 0 size errors |
| Fresh native clients, four profiles | 8/6/6/8 tools; unchanged three-tool schema hashes |
| Isolated embedded and manager jobs | Fast exit, handoff, cursor, identity, stop, and repeated stop passed |
| Separate manager process / MCP worker exit | Job remained running and readable after the launching MCP worker exited |
| Missing accounting / failed cgroup attach | Command still launched and completed successfully |
| Accounting argv-decoration probe | Old/new stdout, stderr, exit and PID semantics match; arbitrary argv and no-op passthrough passed |
| Admission barrier probe | Real temporary HTTP MCP stopped cleanly; late-admitted job blocked manager restart; subsequent admissions refused |

`code-inventory.json` records imports, functions, calls, sizes, and source hashes
for the 15 principal modules. `initial-worktrees.json` records every starting
worktree/ref/status and every untracked file's checksum. `gates.py` gives the
repeatable focused selection. `probe_jobs.py`, `lifecycle-probe.json`, retained
temporary-spool records, and `accounting-attach-failure.json` preserve the probes.
The probe launched only its own subprocesses with temporary spool/socket paths;
it did not restart services or write production cgroups.

Review follow-up evidence is `accounting-decoration-probe.json` and
`admission-barrier-probe.json`, with their scratch scripts and logs. The latter
owns all RPC writers; it does not claim a fence against uncontrolled local
clients. Its first scratch assertion incorrectly expected exit 0 after graceful
SIGTERM. Pinned Uvicorn re-raises the signal after complete shutdown, giving -15.
The retained correction requires the shutdown-complete and finished-server log
markers plus closed HTTP admission; the corrected probe passed. No repository
test or production code changed. `baseline-package.json` inventories the external
source archive for future mixed-version verification.

The raw four-profile archive is `baseline-wire-py313.json`, 141833 bytes, SHA256
`acbc4e794ee45c1bd9dbd3a51dafa9634f101e06ed18a0b0cea36d2f32fcb61f`.
It contains complete tool JSON and instructions, not only normalized hashes.
The three existing normalized hashes are:

| Tool | SHA256 |
| --- | --- |
| `run_command` | `86bad9e89fba8852069598a9d415f0d556aa5ff0cef5c5f2497dfdc737c7abed` |
| `job_status` | `943496173b29f5c8cf9746fb355fd5ccf4d7351089b6841202e0d8279aa7f1a3` |
| `stop_job` | `ef13121e05987b54c837ce1963f8b967cb67064e91e06604f7e6a63535d02a2d` |

These observations are a design baseline, not G3 implementation gate results.
Recreate the archive and baseline before implementing. Never overwrite this
evidence, replace goldens, or treat variable job IDs/timestamps as wire metadata.

## 2. Fixed scope and invariants

### 2.1 Public and construction contracts

Keep all eight tool names in this order:

```text
read_file, list_files, search_text, edit_file, write_file,
run_command, job_status, stop_job
```

Preserve descriptions, literal defaults, annotations, input/output schemas,
instructions, validation, exact errors, structured results, and text summaries.
Keep default/modern ChatGPT/legacy ChatGPT/unrelated profiles at 8/6/6/8.
No public hash or golden rebaseline is permitted. Dynamic lifecycle results
use existing normalization; their field presence and semantics must match.

G1's three focused children, native mounts, `PublicToolOrder`, local
`on_duplicate="error"`, and test-only raw ownership counters stay unchanged.
G2's visibility Transform, identity memory, request state, exact denied-call
bridge, middleware ordering, auth, module exports, CLI, and bootstrap stay
unchanged. Do not add FastMCP middleware, Providers, Depends, or lifespan.

Keep G2's deep-copied roots/run settings and status scalars. Fully supplied
Commands construction must not read global adapter settings. Backend ownership,
spool/socket, output ceiling, and warmup remain process-owned. Two child factories
may use different adapter settings or fake backends without promising two
independent production job managers.

### 2.2 Durable semantics

- Waiting never kills a command. Timeout hands a durable `job_id` back to the
  client; only an explicit stop follows the existing stop policy.
- The stable manager owns production `Popen` handles and reapers. MCP client
  disconnect, new turns, or server reload do not own or cancel those jobs.
- Disk metadata and spool remain authoritative across MCP processes. Preserve
  file names, schema versions, optional keys, atomic replace, output byte offsets,
  UTF-8 handling, tail behavior, limits, and retention.
- Preserve manager/embedded selection, metadata-directed stop routing, terminal
  idempotency, stop markers, SIGTERM/SIGKILL timing, and durable exit recording.
- Preserve PID plus starttime checks, group membership and stray-descendant
  signaling, old-record existence fallback, and current race limitations.
- Positive waits and concurrent stop paths must bridge process-death/reaper
  windows. Do not introduce false unknown or unknown-job errors there.
- Preserve resource snapshot/finalization behavior, including leader exit before
  descendants, deferred cleanup, and resource-only metadata merging.
- Preserve telemetry logger names, event/field names, call/origin IDs, command
  hashes, dispatch reasons, and the measured phases of timing fields.

### 2.3 Explicit exclusions

No FastMCP Tasks substitution; generic RuntimeContext, service locator, Feature,
ServerBuilder, Provider router, or new lifecycle framework; package relocation;
macOS implementation; systemd/journal/service-log/runtime-path extraction (G4);
watchdog/tunnel/operational-route work (G5); dependency/lock changes; settings-wide
refactor; durable schema/cursor redesign; manager RPC redesign; or broader
resource containment/security policy. G6 owns package convergence.

A concrete need to change public behavior, persisted schema, RPC, or lifecycle
ownership is a stop condition for separate review. Do not hide it in this group.

## 3. Current ownership and call graph

### 3.1 Observed modules

| Module | Current responsibility and pressure point |
| --- | --- |
| `commands_server.py` (55 lines) | Copies adapter configuration; registers three tools on one native child |
| `tools/run_command.py` (290) | MCP metadata plus dispatch policy, owner call, output shaping, telemetry |
| `tools/job_status.py` (500) | MCP metadata plus list/wait/cursor/tail/process orchestration and telemetry |
| `tools/stop_job.py` (76) | Owner routing call plus MCP result/error conversion |
| `job_owner.py` (135) | Manager/embedded routing and restart recovery; uses private `jobs` store helpers |
| `jobs.py` (497) | Process-owned settings, lock/prune/store orchestration, launch/wait/reap/stop, accounting |
| `job_store.py` (94) | Explicit-root durable metadata/log operations; no lifecycle |
| `job_process.py` (115) | Linux `/proc` identity, process tree/group summaries, group signaling |
| `job_cgroup.py` (295) | Linux cgroup-v2 setup, launch wrapper, counters, wait-empty, cleanup |
| `job_resource_history.py` (243) | History schema/privacy/retention and asynchronous accounting finalization |
| `job_manager.py` (268) | Stable owner, private Unix socket, RPC, recovery, process wait/reap |
| `job_client.py` (88) | Protocol 1 newline-JSON `ping`, `start`, `stop` client |
| `job_output.py` (127) | Pure clipping, tail selection, and incremental UTF-8 functions |
| `run_command_telemetry.py` / `run_command_evidence.py` | Dispatch policy, structured timing, and auto-rule evidence |

Line counts describe `68e690d`, not target budgets. Extract responsibility before
growing either 497/500-line module; do not split arbitrary chunks to satisfy size.

```text
Commands FastMCP child
  run_command -> DispatchPlan + job_owner.start_and_wait
              -> jobs.job_state/read_log -> job_output
  job_status  -> jobs.list_jobs/job_state/await_exit/read_log[_range]
              -> jobs.job_processes + job_output
  stop_job    -> job_owner.stop_job

job_owner.start -> manager RPC OR embedded jobs.start_job/wait/reap
job_owner.stop  -> state/metadata -> manager RPC OR embedded stop
manager        -> jobs.start_job/record_exit/reap/stop + owner recovery
jobs           -> job_store + Popen/process helpers + cgroup + resource history
resource history -> cgroup wait/snapshot/cleanup + durable history + merge callback
```

### 3.2 Lifecycle details that must survive extraction

`jobs.start_job` holds the same reentrant store lock through pruning, reservation,
launch, and metadata publication. Stdin is a file, not a pipe that can block on
the pipe buffer. Output and stderr share the disk spool. Launch uses a new
session. Environment overrides and command/job correlation remain domain policy.
Manager metadata adds schema version 2, owner instance, and boot ID; embedded
records intentionally differ. Do not flatten that difference for parity tests.

Fast completion records exit inline. Only jobs that outlive the initial wait get
a reaper thread. `record_exit` uses the actual process return code, snapshots
resources, attempts cleanup, and persists the terminal state under the lock.
A pending resource finalizer runs after the lock, then merges only its resource
fields into the current metadata. Pruning may remove the record first.

`await_exit` waits for persisted terminal metadata, not merely a dead PID. It
uses the existing adaptive delay and deadline. At timeout it can honestly return
the latest running/unknown state; a zero-wait inspection can observe unknown.
Do not promise that every observation hides every transient window. Stop with
an existing stop marker uses the existing extra wait to bridge that window.

Stop captures group members and reachable descendants before signaling. It sends
SIGTERM to the group and strays, waits 5 seconds for the durable exit, then sends
SIGKILL and waits 2 seconds. Preserve the current ProcessLookupError handling.
Starttime guards stale records, but this is not a new pidfd-based atomic signal
identity guarantee. An already double-forked/reparented daemon can escape tree
inspection. G3 neither broadens nor silently repairs these documented limits.

Manager recovery finalizes unfinished v2 records from an earlier owner. A stop
marker wins; otherwise boot mismatch means `host_reboot`, and same boot means
`owner_restart`. Legacy records and current-owner records are skipped. Recovery
does not reattach a `Popen`, resume the process, or manufacture an exit code.

## 4. Command-domain decision

### 4.1 Two use-case modules, one narrow backend port

Use plain functions in `command_execution.py` for run and stop, and in
`command_status.py` for list/status/wait/output. They share a `CommandBackend`
Protocol in `command_contracts.py`. A stateless `DurableCommandBackend` in
`command_backend.py` delegates to the existing `jobs` and `job_owner` functions.

There is no lifecycle-owning facade class. Splitting execution and status keeps
the large read/cursor path out of the dispatch/stop path. Separate execution and
status backend objects would add coordination without independent production
ownership; both must see the same durable spool. One backend interface therefore
serves both modules and supports a simple fake in adapter tests.

The port is the operations adapters already consume:

| Member | Existing delegate / exact role |
| --- | --- |
| `start_and_wait(command, workdir: Path, stdin, wait_seconds) -> str` | `job_owner.start_and_wait`; resolved workdir, durable job ID |
| `stop_job(job_id) -> dict \| None` | `job_owner.stop_job`; preserve routing/idempotency |
| `job_state(job_id) -> dict \| None` | `jobs.job_state` |
| `list_jobs() -> list[dict]` | `jobs.list_jobs`; preserve existing sort |
| `await_exit(job_id, timeout) -> dict \| None` | `jobs.await_exit`; persisted terminal state |
| `read_log(job_id) -> bytes` | `jobs.read_log`; missing output still returns empty bytes |
| `read_log_range(job_id, start, max_bytes) -> tuple[bytes, int]` | `jobs.read_log_range`; preserves `job_store.JobGone` |
| `job_processes(pgid, max_cmd_chars=200) -> list[dict]` | `jobs.job_processes`; process summary only |
| Read-only `owner_mode`, `warmup_s`, `max_output_chars` properties | Existing process-owned `OWNER_MODE`, `WARMUP_S`, `RUN_MAX_OUTPUT_CHARS` |

These properties read the existing owner configuration; they are not a second
settings model. The backend object starts no process/thread and stores no
manager client/session, mutable job cache, or resource handle. Its constructor
does not read settings. Default methods may lazily import existing delegates.

Default selection must still initialize the existing process-owned engine before
the server accepts requests. Use `create_command_backend()` in
`command_backend.py`: import the existing `jobs`/owner modules there, then return
the stateless backend. This preserves their one-time process-owned configuration
capture; it must not silently move owner/spool/warmup selection to the first tool
call. Do not copy those settings into a new backend model. A supplied fake bypasses
this default-selection function entirely, so fake-backed construction does not
import Linux or read engine settings. Test both startup paths in subprocesses.

Use a frozen `CommandReply` with `summary: str` and `payload: dict` only to remove
the `ToolResult` dependency. Use `CommandFailure(Exception)` for the current
human-readable tool errors. Adapters convert it to `ToolError` with the same
text and cause behavior. Path validation and `CodedToolError` remain in the run
adapter. Preserve exception catch boundaries; do not convert unexpected
exceptions, cancellation, or `BaseException` into ordinary command failures.

Keep state, metadata, processes, counters, and RPC responses as their existing
dicts. No new enums or model validators that drop legacy keys or turn missing
values into zeros. `command_status` may import only the existing `JobGone`
exception from `job_store`; it performs no store I/O. This explicit exception
compatibility edge avoids moving or duplicating that public exception identity.

### 4.2 Output, telemetry, and adapter responsibilities

| Responsibility | Target owner |
| --- | --- |
| MCP defaults/descriptions/annotations/schemas and result/error conversion | Existing three `tools/*` adapters |
| Workdir resolution/roots policy and coded path errors | Run adapter, unchanged G2 inputs |
| DispatchPlan, auto-match evidence, run/stop use-case summaries and payloads | `command_execution` |
| List selection, wait orchestration, cursor errors, status payload and summary | `command_status` |
| Tail/clipping/UTF-8 algorithms | Existing pure `job_output`, called by domain functions |
| Atomic byte reads and size-at-open | Existing `job_store` through backend |
| Lifecycle routing/process/storage ownership | Existing job modules through backend |

Move output orchestration without rewriting algorithms. Run output's source
character budget and markers are not identical to status output's hard returned
character limit; preserve both. `end`, `start`, and `v1:job_id:offset`, cursor
ownership/errors, deferred UTF-8 suffix, final flush, `has_more`, and JobGone
translation are exact compatibility contracts. The internal cursor remains as
documented; this is not a public schema expansion.

Keep the same logger names even when a function moves. Move timing scopes with
the corresponding work. Preserve `current_call`, client/turn/argument names,
and call-start ContextVars. Do not create a new context container. Fake clocks
and monkeypatches in tests move to the real function owner; assertions do not
become looser. In particular, preserve wait-error telemetry for exceptions.

### 4.3 Construction and compatibility bridges

Add only an optional internal keyword `backend: CommandBackend | None = None`
to the Commands factory and registration/implementation seams. It is captured
by registration closures and never appears in an MCP tool signature. A supplied
backend is used directly, not deep-copied. Omission uses the explicit default
selection above. Ordinary function arguments are enough; no FastMCP dependency
or lifespan is involved.

The public root remains no-argument `create_server()`. Root and child import
paths remain. `run_command_impl`, `job_status_impl`, and `stop_job_impl` remain
thin compatibility wrappers with existing arguments plus the internal optional
keyword. Keep lazy direct-call configuration fallbacks. Registration closures
must still resolve the module's `*_impl` at call time: do not regress G2's late
binding tests by capturing the implementation in a `partial`.

Domain functions require explicit backend and settings/scalars. They never
choose a backend or read `get_settings()`. Adapter wrappers retain fallback
selection; factory paths supply everything. A fake backend must support native
Commands-client tests without importing Linux adapters or touching a real spool.

## 5. Process contract and Linux implementation

### 5.1 Exact boundary

Define `ProcessHandle` and `ProcessBackend` structural Protocols in
`process_contracts.py`. Implement `LinuxProcessBackend` in the existing
`job_process.py`. Keep that module's current helper functions as compatibility
delegates while tests/callers migrate. Do not relocate it into a package.

`ProcessHandle` exposes `pid`, `returncode`, and
`wait(timeout: float | None = None) -> int`. The Linux implementation returns the
actual `Popen`; a fake implements the same three operations. Preserve native
`subprocess.TimeoutExpired` and negative return codes. A wrapper, new timeout
exception, async process runtime, or process registry is unnecessary.

| `ProcessBackend` member | Meaning / Linux implementation |
| --- | --- |
| `launch(argv, *, workdir: Path, env, stdin, output) -> ProcessHandle` | Current `Popen` options; binary open handles, stderr merged, new session |
| `starttime(pid) -> int \| None` | Opaque identity token persisted in the existing `starttime` key |
| `alive(pid, starttime=None) -> bool` | Same PID/token check; legacy None means existence fallback |
| `processes(pgid, max_cmd_chars=200) -> list[dict]` | Existing sorted `pid/state/etime_s/cpu_s/cmd` summaries |
| `descendants(pid) -> set[int]` | Current reachable parent-chain descendants, including setsid children |
| `signal_job(pgid, strays, intent) -> None` | Intent is `Literal["terminate", "kill"]`; group then stray PIDs |
| `boot_id() -> str` | Current manager boot-ID read and `"unknown"` fallback |

Jobs owns the signal sequence, grace periods, state checks, captured stray set,
and reaper/terminal waits. The backend maps intent to native signals and moves
the existing group/stray mechanics verbatim. A group ProcessLookupError remains
visible to the existing caller; individual stray disappearance stays ignored.
Do not silently reorder or expand the signal target set.

Launch owns only process mechanics. Jobs still opens/closes spool and stdin
files, chooses the base `['bash', '-c', command]` argv and environment overrides,
reserves IDs, writes metadata, and holds the lock. Accounting only decorates
that already-formed argv. Process code does not
read roots/settings, choose a spool/socket, create a cgroup, or record history.

The token is deliberately opaque outside the backend; no `/proc` path or clock
tick calculation escapes it. The persisted integer/token compatibility is more
important than an ambitious cross-platform identity DTO. No macOS backend is
part of this design.

### 5.2 Composition, fakes, and error behavior

Use a small `job_platform.py` with explicit `create_process_backend()` and
`create_resource_accounting()` functions that lazily construct the two current
Linux adapters. It has no discovery, registry, settings model, lifecycle, or
automatic platform selection framework. Unsupported platforms are not claimed
to work. Only job-engine/manager composition imports it.

`jobs` binds the process backend once at its existing process-owned boundary.
Tests replace that binding with a fake; there is no production mutation/setter
API. Manager boot lookup uses the same explicit default construction seam.
Owner/manager wait code depends on `ProcessHandle` and the standard timeout
exception, not a Linux concrete class. Standard `subprocess` exception imports
are allowed there; spawning itself is confined to the Linux implementation.

Preserve each helper's existing failure behavior. Disappearing stat entries,
malformed start tokens, command names with spaces/parentheses, empty cmdlines,
and uptime fallback get deterministic tests. Do not add broad catches around
errors that currently propagate. Moving `os.sysconf` into the Linux adapter
module is sufficient; G3 does not make all of Binnacle importable on macOS.

Python documents that `Popen.wait(timeout)` raises without terminating the
child. Binnacle's owner remains responsible for a later wait and durable exit
record. This is the relevant boundary, not `subprocess.run`'s different timeout
policy. See [Python 3.13 subprocess](https://docs.python.org/3.13/library/subprocess.html#subprocess.Popen.wait).

## 6. Optional resource accounting contract

### 6.1 Counter mechanics, not execution ownership

Define `ResourceAccounting` in `resource_contracts.py`. Implement
`CgroupResourceAccounting` in the existing `job_cgroup.py` around its functions.
Keep process execution and accounting independent: neither concrete adapter
imports the other. The job engine composes them.

| Member | Required semantics |
| --- | --- |
| `prepare(*, log_ready=False) -> str \| None` | Existing optional delegated-root preparation and diagnostics |
| `create(job_id) -> str \| None` | Best-effort per-job identity; None permits normal launch |
| `wrap_argv(argv: list[str], identity) -> list[str]` | Decorate an already-formed argv before exec; unchanged argv when no identity |
| `snapshot(identity) -> dict` | Best-effort counters; absent metrics stay absent |
| `wait_empty(identity: str) -> bool` | Existing kernel-backed wait; False if it cannot establish emptiness |
| `cleanup(identity: str \| None) -> bool` | True only for no identity, absent scope, or completed removal |

An identity is an opaque string to the domain. Keep the existing `cgroup`
metadata key and `BINNACLE_JOB_CGROUP` diagnostic environment value for Linux;
do not parse that string or convert it into a filesystem path in domain code.
`move_pid` and filesystem discovery remain private Linux helpers, not new
port operations with no current consumer.

Jobs chooses the base command argv. The accounting port neither chooses its
interpreter nor receives a command string to reinterpret. With no identity it
returns the supplied argv unchanged. With an identity the Linux adapter wraps
it in the existing attach-before-exec mechanism: write the wrapper shell's PID
to `cgroup.procs`, then `shift; exec "$@"` for the supplied base argv. The wrapper
uses bash only to perform its Linux attach mechanics; it does not choose the
command being executed. It must not mutate the caller's argv.

A failed write must still execute the command, as today. Preserve the same PID
across exec and attach before descendants can launch. Test quoting, stdin,
environment, exit/signal, and an arbitrary supplied argv against the old wrapper.
Retain `job_cgroup.launch_argv(command, cgroup)` as a compatibility helper if
callers remain; production orchestration uses `wrap_argv` after activation.
Do not replace this with post-`Popen` attach or let accounting launch/kill/wait
a process. The only semantic change in wrapper structure is forwarding argv
without owning base shell-command policy; no tool metadata/default changes occur.

Add a `NoResourceAccounting` implementation beside the contract for explicit
test/embedding use: prepare/create return None, snapshot is empty, `wrap_argv`
returns its argument unchanged, and wait-empty returns False. Cleanup(None) returns
True; cleanup of an unknown non-None legacy identity returns False, because
this implementation cannot prove cleanup. Production still selects the Linux
best-effort adapter; no new setting or capability detection framework is added.

Expected cgroup availability and filesystem failures remain contained by the
Linux adapter's existing narrow error handling. They cannot make launch, wait,
stop, or durable exit correctness conditional on counters. Do not swallow
arbitrary programming exceptions merely because accounting is optional.

### 6.2 Resource history stays domain-side

Keep schema version 2, privacy-minimal history records, local-date JSONL,
retention/prune cadence, field units/names, cumulative-counter whitelist, and
gauge/final-gauge distinction in `job_resource_history.py`. These are persisted
Binnacle policy; the kernel adapter should not own them.

Pass `accounting: ResourceAccounting` explicitly to `finalize_async` and capture
that same instance in its thread. Remove its concrete `job_cgroup` import only
when all callers/tests pass the port. Leave append/serialization/retention
functions in place. The platform adapter returns existing counter dicts, not a
new schema or history object.

Leader exit remains terminal even if descendants keep the accounting scope
populated. Cleanup then sets the existing `cgroup_cleanup_pending` key; the finalizer
waits for empty, takes the last snapshot, tries cleanup, appends history, and
calls the existing merge callback. Preserve the four-field resource-only merge,
record-pruned behavior, `resource_finalized_at`, and pending flag on cleanup failure.
Wait unavailability logs and returns without inventing final counters.

Pin the exact four merge keys: `resource_usage`, `resource_history_path`,
`resource_finalized_at`, and `cgroup_cleanup_pending`. Characterization and
mixed-revision fixtures must reject replacement names or extra durable keys.

The current finalizer is an in-memory daemon thread. Restart does not promise
to resume it or deduplicate history across crashes. The current history prune
guard is process-owned. G3 preserves those limitations; it does not introduce
durable task scheduling or exactly-once history semantics.

Kernel population and controller availability are separate facts. Preserve
`cgroup.events` wait semantics and missing-controller behavior. See
[cgroup-v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)
for kernel context; the pinned Binnacle implementation/tests define compatibility.

## 7. Stable owner, manager, and durable store

### 7.1 Routing is an application concern

Keep `job_owner` as the routing/recovery application boundary under
`DurableCommandBackend`. It is neither a platform port nor FastMCP composition.
Global `auto`/manager/embedded start selection remains unchanged. Stop still
uses record ownership: a live v2 manager-owned record routes to RPC even when
the caller's configured default differs. A terminal record is locally idempotent.

Keep protocol 1, socket permissions, request/response shapes, call ID forwarding,
start timeout `max(5, wait + 5)`, stop timeout 10, and error translation. Do not
add status/list RPCs; status continues to use the durable spool. `job_client.py`
does not need production edits. The manager still validates its own wait cap.

Keep manager `prepare` ordering: optional accounting preparation, private
directory/socket checks, recovery, bind/listen, readiness notification. Keep
`KillMode=control-group` and unit generation unchanged. Boot identity moves
behind the process port; systemd readiness, socket path, and service machinery
remain for G4. Neither FastMCP lifespan nor client disconnect stops the manager.

### 7.2 Store separation without a repository rewrite

`job_store` is already an explicit-root repository boundary. Keep its functions,
schema, random IDs, required-key checks, malformed-record handling, atomic temp
write/replace, and single-open range read. No repository class, ORM, new database,
metadata migrations, or log format is needed.

Remove `job_owner`'s private `jobs._read_meta/_write_meta/_STORE_LOCK` dependency
in one late checkpoint. Move the one process-local `RLock` definition to
`job_store.STORE_LOCK`; retain `jobs._STORE_LOCK` as an alias to the same object.
Owner operations use public `job_store.read_meta/write_meta` with the existing
`jobs.JOBS_DIR`, and that same lock where currently required. Recovery retains
its existing pre-bind sequencing; do not claim new interprocess transactional
locking. Tests must assert lock identity and exercise prune/start/stop races.

Keep `jobs._job_dir/_read_meta/_write_meta/_remove_job_dir` compatibility facades
for existing internal callers while migration proceeds. Public `jobs` functions
and `JobGone` alias remain. No broad caller cleanup across diagnostics or G4/G5.
Jobs owns prune policy and live-job protection; the store owns bytes and atomic
I/O. Do not reduce the lock span from prune/reserve through launch/publication.

### 7.3 Truthful reload and restart boundaries

The design probe proved survival of MCP-worker exit with a separate stable
manager. It did not prove embedded survival after its owner process exits.
Embedded mode is a rollback/test path; loss of its waitable parent can leave
legacy records unknown. Preserve that behavior rather than claiming parity
where the owners intentionally differ.

Manager restart/host boot recovers durable records as interruptions. It does
not transparently resume unfinished commands. Mixed old/new manager and MCP
code must interoperate through unchanged protocol/spool during deployment and
rollback. Test both version directions with isolated processes before deployment.

FastMCP Tasks have their own execution/lifespan model. They are not a substitute
for this stable owner and spool. No Tasks dependency, decorator, notification,
or lifecycle is introduced. See [FastMCP Tasks](https://gofastmcp.com/servers/tasks)
for the native concept; G3 deliberately retains Binnacle durable jobs.

## 8. Test groups and acceptance evidence

Run selected files with `uv run pytest -q ... --randomly-seed=12345`.
Selectors below are explicit groups, not a new runner/framework. New files
listed here are implementation deliverables, not tests added by this design.
Keep the existing tests; migrate private patch targets only when ownership moves.

### 8.1 Existing focused groups

| Group | Exact existing files / commands |
| --- | --- |
| B — wire/contracts | `tests/contracts/test_dependency_pin.py`, `test_protocol.py`, `test_tool_surface.py`, `test_job_schemas.py`, `test_input_validation.py`, `test_golden_outputs.py`, `test_job_status_cursor_internal.py`, `test_job_spool_compat.py` in that directory |
| C — composition/construction | `tests/contracts/test_server_composition.py`; `tests/unit/core/test_domain_construction.py`; `tests/integration/test_commands_settings.py`, `test_server_factory.py`, `test_composition_pipeline.py`, `test_composition_workflows.py` |
| V — visibility/auth/entrypoints | `tests/contracts/test_visibility.py`, `test_visibility_policy.py`; `tests/unit/core/test_visibility_native.py`; `tests/integration/test_visibility_http.py`, `test_auth_asgi.py`, `test_http_workflows.py`, `test_logging.py`, `test_config_warning_logging.py` |
| L — lifecycle/races | `tests/integration/test_jobs.py`, `test_jobs_lifecycle.py`, `test_jobs_state_machine.py`, `test_jobs_stop_paths.py`; `tests/unit/tools/test_stop_job_edges.py` |
| M — manager/owner | `tests/integration/test_job_manager.py`, `test_job_manager_telemetry.py`; `tests/unit/core/test_job_owner_selection.py`, `test_job_client.py`, `test_job_manager_unit.py`, `test_job_manager_edges.py`; `tests/system/test_job_manager_doctor.py`, `test_doctor_jobs.py` |
| D — store/output | `tests/integration/test_jobs_store.py`, `test_run_command_output_shaping.py`; `tests/unit/core/test_job_store_range.py`, `test_job_output.py`; B's spool and cursor contracts |
| P — process | `tests/unit/core/test_job_process_edges.py`; L stop/lifecycle and M recovery tests |
| R — accounting/history | `tests/unit/core/test_job_cgroup.py`, `test_jobs_cgroup_integration.py`, `test_job_resource_history.py` |
| T — telemetry/policy | `tests/integration/test_run_command_policy_telemetry.py`, `test_run_command_error_telemetry.py`, `test_job_telemetry.py`, `test_job_manager_telemetry.py`; `tests/unit/core/test_run_command_telemetry.py`, `test_run_command_evidence.py`, `test_logstats_run_command.py`, `test_logstats_jobs.py` |
| A — architecture | `uv run python scripts/check_architecture.py`; `uv run lint-imports --no-logo`; `uv run python scripts/check_module_size.py --strict`; construction/static tests in C and new negative tests below |

The recorded 314-test design baseline is the selection in `gates.py`, not every
file in this larger implementation matrix. B+C+A is the checkpoint minimum;
additional groups are assigned below. At convergence run the complete matrix
through the repository-managed suite and required policies, not a direct full
`pytest -n` invocation.

### 8.2 Characterization and new tests

Add deterministic cases to existing modules where they belong. New cohesive
test modules may be `tests/unit/core/test_command_backend.py`,
`test_command_execution.py`, `test_command_status.py`,
`test_process_contract.py`, `test_resource_accounting_contract.py`, and
`test_commands_architecture.py`; plus
`tests/integration/test_command_domain.py` and `test_job_manager_reload.py`.
Keep helpers small and private to tests. Do not build another mutable golden
system or production registry to make tests convenient.

| Risk | Required positive and negative evidence |
| --- | --- |
| Domain extraction | Fake backend exact call arguments/order; native child real registration; direct impl wrappers; same payload/text/errors; supplied settings/backend never fall back to globals |
| Two factories | Different settings and fake backends remain isolated; defaults still use one process-owned durable engine; mutation of caller settings does not leak; late-bound impl replacement still works |
| Wait/handoff | Fast success/failure, explicit background, timeout handoff without kill, auto-background, stdin larger than pipe buffer; no unnecessary reaper on fast exit |
| Stop | First and repeated stop, terminal offline-manager result, manager-owned record with embedded caller default, unknown ID, existing stop marker, group disappearance, SIGKILL escalation, concurrent stops, post-death-before-record barrier |
| Process identity | Correct and mismatched starttime, PID reuse simulation, missing token legacy behavior, malformed/disappearing proc entries, group versus setsid strays, sorted/truncated summaries, boot-ID unavailable |
| Store/retention | Atomic partial-reader protection, unique temp files, missing/malformed metadata, active-job protection, concurrent starts/prune/stop, identical RLock object, range size-at-open, deletion before/open/after read |
| Output | UTF-8 chunk split, invalid byte replacement, final flush, cursor from another job/beyond EOF/no ID, empty/end cursor, tail/clip differences, bounded list history with all running jobs, quiet threshold |
| Manager lifecycle | Isolated real manager + separate MCP worker exits; reconnect/fresh root status/stop; protocol and socket permissions; previous-owner restart versus boot mismatch; stop reason priority; legacy/current-owner skip |
| Mixed revisions | Baseline manager with candidate MCP, candidate manager with baseline MCP; start/status/cursor/stop/repeated stop; same on-disk fixtures/RPC; no production socket or service |
| Optional accounting | None/create failure/controller absence, failed shell attach but successful command, argv passthrough/decorating without choosing base policy, quoting/stdin/exit and same-PID exec, wrapper-before-descendants order, empty snapshots, cleanup absent/populated/failure, no-op legacy-identity refusal |
| History/finalizer | Leader exited with descendants alive, deferred final counters, wait unavailable, append failure behavior, cleanup failure pending flag, metadata pruned before callback, terminal fields preserved during resource-only merge |
| Telemetry | Same logger/event/fields and origin/call IDs across manager RPC and moved code; errors and wait exception timing; output shaping reasons; no added output/control notifications |
| Manager admission barrier | Isolated HTTP MCP stop closes admission while manager remains alive; a start crossing the first quiet check is caught by the second inventory and defers restart; no accepted request after the barrier; only restart after all admitted work/drain conditions are established |

Use barriers/events/fake clocks for race contracts, not longer sleeps or weakened
assertions. Real lifecycle tests wait on explicit spool/socket/readiness signals
with bounded deadlines. Own and reap every test process; terminate only process
groups the test created. Never point tests at production spool/socket/cgroups.
Current cgroup-present tests use a fake filesystem; optional host tests must not
require a delegated controller for the ordinary suite to pass.

The design's observed manager/embedded parity covers shared public behavior,
not identical metadata or owner-process survival. New restart tests should
simulate the stable unit's interruption semantics in isolated child processes;
they must not run `systemctl` against the host manager. A bare manager process
exit without unit-level child cleanup is not equivalent to the production unit.

Mixed-revision source comes from a checksummed `git archive 68e690d src/binnacle`
captured outside the worktree during G3.0. The mandatory local convergence probe
uses that baseline package and the candidate in separate subprocesses with the
same locked interpreter and explicit source paths, private spools, and private
sockets. Assert the imported module paths so the two lanes cannot accidentally
load the same revision. No production checkout or service is used.

Keep the repository's manager-reload tests self-contained against current code
and the existing protocol/spool fixtures. Do not make ordinary CI depend on
historic Git objects in a shallow checkout, network fetches, or a vendored copy
of the old engine. The two-direction archived-source probe is an additional
required local convergence artifact; repeat it after relevant fixes and retain
the archive hash and exact invocation with review/deployment evidence.

### 8.3 Negative architecture contracts

Extend Import Linter and narrow AST/import tests with these end-state rules:

1. Commands adapters do not import `jobs`, `job_owner`, `job_client`,
   `job_store`, `job_output`, `job_process`, or `job_cgroup`. They import domain
   use cases/contracts/default backend and existing MCP/config/path facilities.
2. `command_execution`, `command_status`, and `command_contracts` do not import
   FastMCP/MCP, concrete backend, owner/client/jobs, platform selection, Linux
   adapters, `os.kill*`, or launch APIs. Status may import `JobGone` only from
   `job_store`, with no store method calls. Pure `job_output`, existing telemetry,
   evidence, config types, and callctx are allowed.
3. `command_backend` is the only new domain-to-existing-engine bridge. It does
   not import FastMCP or concrete Linux adapters, own state, or create resources.
4. Process/resource contracts have no FastMCP, jobs, owner, store, or Linux
   imports. The two Linux implementations do not import each other or job
   orchestration/MCP. `job_platform` is only explicit default construction.
5. Jobs/owner/manager do not contain `/proc` inspection, cgroup path manipulation,
   direct Popen launch, or signal syscalls after activation. Standard timeout
   exception use and manager's existing service/socket code are allowed. Only
   composition imports the concrete default-selection module.
6. Resource history imports the accounting contract, not `job_cgroup`.
   Store imports no process/resource/MCP code. No new import-time settings
   captures enter domain use cases or migrated adapters.

Test the static rules themselves with synthetic forbidden imports/calls and
dynamic-import spellings in the narrow migrated set. A subprocess import blocker
must still allow pure contracts/use cases and a fake-backed native Commands
child while refusing `job_process` and `job_cgroup`. This proves separation,
not a whole-repository macOS support claim. Keep legitimate process-owned
`jobs`/manager settings and G4/G5 Linux code explicitly outside these checks.

Do not use line-count exceptions, `noqa`, generic plugin discovery, or private
FastMCP introspection to enforce the design. Existing seven Import Linter
contracts remain green; new narrow contracts supplement them.

## 9. Atomic implementation sequence

Every checkpoint has one primary responsibility. Before each commit, re-read
status/refs/worktree inventory, inspect the full diff, run its focused gates,
and commit only a green, functional state with the required co-author footer.
Do not batch all adapter/platform activations into one rewrite.

For every step, files not named in its change set are out of scope except the
master/design checkpoint evidence and directly relevant tests/import rules.
All exclusions in section 2.3 apply. Test-only contracts may precede production
switches. FastMCP APIs throughout are the existing child factory, `@tool`
registration, native mount, and `Client`; there is no new FastMCP extension.

### G3.0 — Freeze implementation baseline

- **Purpose/current state:** verify the reviewed design atop deployed G2; no G3
  code exists yet.
- **Input:** this approved design commit, deployed `68e690d`, current refs and
  untracked-document inventory.
- **Output/downstream:** external gate ledger, four-profile raw wire archive,
  three-tool hashes, archived baseline package, copied spool fixtures, and call graph for every
  later comparison. Mark G3 implementing only after a clean baseline.
- **Files:** control evidence only. Use the approved worktree helper for one new
  implementation branch; do not reuse this design or production worktree.
- **Tests before/after:** doctor/worktrees, offline lock/runtime, B+C+L+M+D+P+R+T+A,
  and the isolated lifecycle/accounting probes. Resolve any pre-existing failure
  separately; do not redefine the baseline.
- **Rollback/parallel/done:** no production switch to roll back; serialized
  integrator step; done when evidence is retained and all gates pass.

### G3.1 — Pin characterization before moving production code

- **Purpose/current state:** current functions work but module coupling can hide
  ownership mistakes in mocks.
- **Input:** G3.0 behavior and section 8 risk matrix.
- **Output/downstream:** deterministic current-backend lifecycle/race fixtures,
  exact adapter error/result/telemetry expectations, isolated manager-reload tests
  and an external archived-source mixed-revision harness. These become extraction
  acceptance tests; the latter does not require old Git objects in CI.
- **Files:** only relevant existing/new tests and small test helpers. No source
  changes, new schemas, or alternate goldens.
- **Tests before/after:** B+C+V+L+M+D+P+R+T+A; add missing cases, retain property tests.
- **Rollback/parallel/done:** independent test-only revert; test authoring can
  parallelize by file with a single integrator; done when current behavior passes
  and negative fixtures demonstrate the contracts catch an intentional fault.

### G3.2a — Add unused command port and durable backend

- **Purpose/current state:** adapters still call the existing job modules.
- **Input:** exact consumed operations in section 4 and G3.1 characterization.
- **Output/downstream:** `command_contracts.py` and `command_backend.py`, ready
  for one adapter at a time. Default backend remains unused by exported tools.
- **Files:** these two modules and focused backend/contract tests. No `jobs`,
  owner, platform, or public registration changes.
- **Native API/invariants:** Protocols/ordinary functions only; no FastMCP
  resource creation. Backend methods delegate without caching or shape changes.
- **Tests before/after:** B+C+A plus fake delegate/property/exception tests.
- **Rollback/parallel/done:** revert unused addition; integrator owns shared
  interface; done when each delegate is proved and wire remains identical.

### G3.2b — Move run execution use case

- **Purpose/current state:** run adapter contains dispatch/output orchestration.
- **Input:** G3.2a backend and existing DispatchPlan/output helpers.
- **Output/downstream:** `command_execution.py` run function; run adapter wrapper
  converts `CommandReply`/`CommandFailure`; Commands factory captures backend
  for run only. Status/stop still use their current implementation.
- **Files:** execution module, run adapter, Commands factory, focused run/domain
  tests. Keep path validation, schemas/defaults, output algorithms, jobs unchanged.
- **Native API/invariants:** existing registration closure only; exact captured
  G2 settings, call-time impl lookup, wait/handoff/error/telemetry behavior.
- **Tests before/after:** B+C+L+D+T+A and fake-backed run tests, full wire archive.
- **Rollback/parallel/done:** revert activation while unused backend can remain;
  serialized; done when real and fake backend results/errors match baseline.

### G3.2c — Move status/list/output use case

- **Purpose/current state:** 500-line status adapter mixes schemas and use cases.
- **Input:** stable backend/run activation; exact cursor/list/timing expectations.
- **Output/downstream:** `command_status.py` owns status/list/wait orchestration;
  thin status adapter retains schema/registration and direct-call wrapper.
- **Files:** status module/adapter, Commands factory wiring, focused status tests.
  Leave `job_output`, store I/O, run implementation, and backend semantics intact.
- **Native API/invariants:** same closure registration; late-bound impl lookup;
  no new public cursor/schema; same source timing scopes and exception telemetry.
- **Tests before/after:** B+C+L+D+T+A, cursor contracts, fake-clock/error tests, raw
  wire parity. Fake backend proves no accidental real-store access.
- **Rollback/parallel/done:** revert this activation independently of run;
  serialized; done when list/positive wait/tail/cursor paths all retain parity.

### G3.2d — Move stop use case; seal adapter boundary

- **Purpose/current state:** stop still directly calls owner; run/status now use port.
- **Input:** backend stop method and existing exact terminal/error contract.
- **Output/downstream:** execution module stop function plus thin stop wrapper;
  all three tools share the factory's backend. This is the stable domain seam
  required before parallel platform preparation.
- **Files:** execution module, stop adapter, Commands factory, adapter architecture
  contracts/tests. No owner routing or signal policy change.
- **Tests before/after:** B+C+L+M+T+A, two-factory isolation and late-binding tests.
- **Rollback/parallel/done:** revert stop activation only; serialized; done when
  adapters have no direct storage/owner/process dependencies and wire is exact.

### G3.3 — Prepare process contract and Linux adapter, unused

- **Purpose/current state:** jobs still uses existing Linux helpers/Popen directly.
- **Input:** stable domain seam and current process characterization.
- **Output/downstream:** `process_contracts.py`, `LinuxProcessBackend`, and the
  process constructor in `job_platform.py`. Existing helper paths keep working.
- **Files:** contract, `job_process.py`, composition module, process/fake tests.
  Do not switch jobs/manager or touch accounting in this prepare step.
- **Native API/invariants:** no FastMCP API; actual Popen satisfies handle port;
  identical Linux parsing, signal target/error behavior, and launch options.
- **Tests before/after:** B+C+P+L+M+A; launch/spool-handle/timeout adapter tests.
- **Rollback/parallel/done:** revert unused addition; implementation may parallelize
  with G3.5a after G3.2d, but only integrator edits `job_platform.py`; done when
  fake and Linux contract tests pass without changing exported behavior.

### G3.4a — Route identity and inspection through process port

- **Purpose/current state:** identity/summary/descendant reads use concrete helpers.
- **Input:** tested G3.3 adapter, unchanged durable records.
- **Output/downstream:** jobs' process-owned backend binding and delegated reads;
  existing `jobs.job_processes` compatibility callable stays available.
- **Files:** jobs and related tests. No launch, signal, accounting, owner, store,
  or recovery policy changes; avoid growing jobs past its strict size budget.
- **Tests before/after:** B+C+P+L+M+D+A, explicit mismatched-token and transient-window
  cases, native status parity. Fakes replace the port, not several Linux globals.
- **Rollback/parallel/done:** revert read activation; serialized shared jobs file;
  done when inspection has no Linux mechanics and current state results match.

### G3.4b — Route launch, signals, and boot identity

- **Purpose/current state:** jobs still constructs Popen/signals; manager reads boot ID.
- **Input:** G3.4a binding and characterized mechanics.
- **Output/downstream:** jobs uses handle/launch/signal contract; owner/manager
  retain wait/reap and recovery semantics; manager boot wrapper delegates.
- **Files:** jobs, manager's boot helper, type annotations in owner if needed,
  process/lifecycle/manager tests. No service/RPC/environment policy rewrite.
- **Tests before/after:** B+C+P+L+M+D+T+A, large stdin, wait timeout, escalation,
  separate-manager MCP exit, restart/boot tests, wire parity.
- **Rollback/parallel/done:** revert this activation before process preparation;
  serialized; done when no launch/signal/proc mechanics remain in orchestration.

### G3.5a — Prepare accounting contract and implementations, unused

- **Purpose/current state:** cgroup calls remain concrete; execution already works
  when accounting is missing.
- **Input:** G3.2d stable domain and section 6 counter/identity semantics.
- **Output/downstream:** `resource_contracts.py`, no-op implementation,
  `CgroupResourceAccounting`, explicit accounting constructor. Not activated yet.
- **Files:** contract, `job_cgroup.py`, composition module, focused resource tests.
  No jobs/history/manager activation or process backend changes.
- **Tests before/after:** B+C+R+A, failed-attach actual command probe, no-op legacy
  identity test and controller-absence/failure cases.
- **Rollback/parallel/done:** revert unused addition; may run alongside G3.3 on
  separate files after domain stabilization; integrator owns composition edits;
  done when the optional accounting contract preserves all outcomes.

### G3.5b — Activate accounting and history port together

- **Purpose/current state:** prepared port is unused; history directly imports cgroup.
- **Input:** green G3.4b and G3.5a, including unchanged process launch contract.
- **Output/downstream:** jobs composes process/accounting, manager prepares the
  selected accounting backend, history finalizer receives the same captured
  instance. One atomic activation prevents mixed concrete/port finalization.
- **Files:** jobs, resource history, manager preparation call, directly related
  tests. No counter schema/history retention/RPC/stop-policy changes.
- **Tests before/after:** B+C+L+M+R+T+A; descendant-still-running, unavailable wait,
  cleanup failure and merge/prune races; real launch with missing accounting.
- **Rollback/parallel/done:** revert activation together, keep unused providers;
  serialized shared files; done when accounting remains optional and persisted
  resources/history are compatible in present and absent cases.

### G3.6 — Use public store operations in owner routing/recovery

- **Purpose/current state:** owner still reaches private jobs storage helpers.
- **Input:** stable platform activations and existing explicit-root store API.
- **Output/downstream:** public store lock/operations in owner; jobs compatibility
  aliases remain. Domain, process, accounting, and store boundaries are complete.
- **Files:** job_store, jobs lock definition, job_owner, store/owner/race tests.
  No directory/schema/retention algorithm or RPC change.
- **Tests before/after:** B+C+L+M+D+R+T+A; assert alias identity, prune/reserve lock
  span, terminal idempotency, stop-marker priority, recovery before readiness.
- **Rollback/parallel/done:** revert lock alias/owner change together; serialized;
  done when private owner-to-jobs storage calls are gone and races stay green.

### G3.7 — Tighten static boundaries and remove only obsolete glue

- **Purpose/current state:** compatibility facades work; extraction must not regress.
- **Input:** all prior checkpoints and final import/call inventory.
- **Output/downstream:** section 8.3 enforced, documented process-owned globals,
  small modules, no unused migrated imports; retained facade inventory for G6.
- **Files:** narrow Import Linter configuration, architecture/construction tests,
  obsolete imports in touched modules, control/design evidence. No package moves.
- **Tests before/after:** B+C+V+L+M+D+P+R+T+A, negative static fixtures, blocked-Linux
  fake-backed import test, raw wire comparison, exact scope/dependency audit.
- **Rollback/parallel/done:** revert cleanup without reverting functional seams;
  integrator only; done when each boundary has a failing negative fixture and
  no dead duplicate implementation remains behind compatibility wrappers.

### G3.8 — Converge, review, integrate, and verify actual owner revision

- **Purpose/current state:** local implementation is functional; deployment is
  still a separate completion boundary.
- **Input:** all green checkpoints, full diff, baseline archives, per-step ledger.
- **Output/downstream:** local validated candidate, fresh independent review,
  then exact-SHA CI/deploy/live evidence under separate authorization. G4 does
  not start merely because local tests pass.
- **Files:** only in-scope fixes and truthful control/evidence updates. Never
  change goldens/requirements to hide a failure.
- **Tests:** every gate in section 12, mixed-revision isolated harness, four-profile
  byte comparison, and section 13 manager/deployment completion conditions.
- **Rollback/parallel/done:** reviewed revert or reverse activations with gates;
  single integrator; local status validating until all integration/live gates
  and actual stable-manager revision verification are complete.

## 10. File map and retained bridges

| File set | Planned change |
| --- | --- |
| New `command_contracts.py`, `command_backend.py` | Port/reply/error types and stateless legacy delegation |
| New `command_execution.py`, `command_status.py` | Existing command use-case orchestration moved without redesign |
| `commands_server.py`, three Commands adapters | Ordinary backend argument; thin MCP/compatibility wrappers |
| New `process_contracts.py`, `resource_contracts.py`, `job_platform.py` | Small independent contracts and explicit Linux defaults |
| `job_process.py`, `job_cgroup.py` | Existing mechanics behind adapters; existing helper paths retained |
| `jobs.py` | Orchestration remains; platform delegation, existing facades/globals retained |
| `job_resource_history.py` | Explicit accounting dependency; history policy/format unchanged |
| `job_owner.py`, `job_store.py` | Public store operations and one shared process-local lock |
| `job_manager.py` | Only boot/accounting composition and handle typing, not service/RPC redesign |
| `pyproject.toml` | Narrow Import Linter rules only; dependency tables unchanged |
| Tests and these design/control docs | Characterization, boundary/negative tests, checkpoint/evidence status |

Keep `job_client.py`, `job_output.py`, dispatch/evidence algorithms, config model
definitions, Files/Search code, server root, identity/visibility/logging/callctx,
paths/glob fixes, systemd units, deploy/watchdog/tunnel/diagnostics unchanged.
Test patch targets can move with extracted functions; public module paths do not.
An unexpected required change to this protected set needs characterization and
coordinator review before expansion.

Compatibility bridges are deliberate: direct tool `*_impl` wrappers, stateless
backend delegation, public jobs functions, jobs storage/lock aliases, Linux
helper functions, existing dict shapes/JobGone, and unchanged manager protocol.
Do not delete a bridge until caller search and tests prove it unused; retaining
a short delegate is preferable to a G6 package/caller rewrite. No stage flags,
dual execution, double registration, or runtime backend switching is needed.

## 11. Parallel work and rollback discipline

One integrator owns `jobs.py`, manager/owner/store activation, Commands factory,
`job_platform.py`, wire evidence, and control status. Separate read-only reviews
and nonoverlapping characterization test files can proceed concurrently.
Do not use shared mutation of process bindings or settings across test cases.

After G3.2d, process preparation G3.3 and resource preparation G3.5a can run in
separate worktrees against the same frozen domain seam. Each returns one green
prepare commit with contract tests, exact input SHA, changed-file list, and gate
evidence. Integrator adds their tiny composition entries and validates together.
Activation G3.4a/4b, G3.5b, and G3.6 is sequential. No parallel edits to shared
jobs or independent deployments of mutually dependent activation commits.

A prepare commit is reversible while unused. An activation is reversible by
restoring its old delegate path with its tests. Revert dependents before removing
a contract they consume; arbitrary out-of-order reverts are not promised. Retain
green checkpoint SHAs and external before/after wire artifacts. Never rewrite
user/evidence history, reset a production checkout, or delete another worktree.

## 12. Local convergence and design/implementation review

### 12.1 Required implementation gates

Run focused groups first, then all canonical gates from the locked environment:

```bash
uv lock --check --offline
uv run python scripts/run_test_suite.py --seed 12345
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
uv run tox run
uv run pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
uv run python scripts/check_module_size.py --strict
```

The ordinary-process lane is mandatory. The matrix is Python 3.10-3.14, with
3.13 coverage. New production modules participate in coverage/size policy, not
exclusions. Retain exact failures and classify any pre-existing race before
changing code; never weaken a telemetry assertion or property test to pass.

Recreate and byte-compare complete four-profile wire JSON and instructions using
the same interpreter/environment as G3.0. Also run authenticated no-cache HTTP
visibility/auth parity and native representative command calls. Compare final
diff against both implementation design base and deployed `68e690d`. Verify
dependency tables/lock, protected files, goldens, persisted fixtures, RPC shapes,
and production units unchanged. Check strict size before every growing module.

### 12.2 Review protocol

For this design, run changed-doc pre-commit and prepare an external self-contained
bundle: design/control, three architecture inputs, principal source modules,
relevant test sources, call inventory, exact gate logs, probes/results, and raw
wire archive. Include path/byte-size/SHA256 inventory for every bundled file.
Use a fresh NEW ChatGPT read-only session with `chatgpt-web-operations`; no
traditional Codex subagents. Retain prompt, bundle, review response, and chat ID.

Ask for explicit approval or findings on domain coherence, process/accounting
separation, store/owner/manager ownership, races/recovery, FastMCP use, G4-G6
exclusions, checkpoint/rollback/parallel safety, and test completeness. Correct
all in-scope design findings, rerun affected probes/docs gates, and re-review.
Only then mark this design ready and commit the two docs locally. Stop for the
coordinator's independent review; do not implement in this design turn.

Implementation needs a separate fresh review of final source diff, this design,
wire archives, full gate evidence, mixed-revision tests, and checkpoint history.
An approved design is not an implementation review. Local completion status is
validating/awaiting integration, never done based only on tests.

## 13. Integration, stable-manager activation, and exit criteria

This section specifies future implementation completion. Nothing here is run
during design. Read current DEVELOPMENT/governance policy again at integration.

1. Publish the reviewed candidate branch only after authorization. Require all
   seven exact-SHA CI checks: Code quality; Tests / Python 3.10, 3.11, 3.12,
   3.14; Coverage policy / Python 3.13; Packaging / Python 3.13. No direct
   master/proof-of-concept push substitutes for the gate.
2. Inventory production tracked/untracked state and candidate collisions. Preserve
   unrelated documents; any collision needs a separately reviewed no-loss backup
   procedure before mutation. Never clean them as part of deploy.
3. Use only the canonical production command
   `.venv/bin/python scripts/deploy_smoke.py deploy TARGET`. It verifies CI and
   fast-forward/quiet/smoke conditions and updates deployment refs. Normal
   rollback restores the earlier checkout/environment. Keep evidence of refs,
   environment, smoke, and rollback if it occurs.
4. The canonical deploy deliberately does **not** restart the stable jobs service.
   G3 changes manager-loaded code, so successful MCP smoke alone does not prove
   the new process/accounting backend is active in that service. Require the
   isolated mixed-revision tests before this interval; do not change the deploy
   script or attach manager lifetime to FastMCP to avoid it.
5. Under separate explicit authorization, establish the admission barrier in
   section 13.1 before `systemctl --user restart binnacle-jobs.service`. A quiet
   observation alone has a check-to-restart race and is not permission to restart.
   An exited leader with live descendants is not safe merely because job state
   is terminal. If the barrier/drain conditions cannot be established, defer
   restart and leave G3 validating. Do not kill user jobs to complete the refactor.
6. Record manager PID/start time and checkout/code revision at restart, verify
   a new instance, correct service executable/working directory, protocol ping,
   and manager doctor. Existing protocol ping already reports `revision`, PID,
   and owner instance: verify those fields rather than adding an API. Resume the
   held MCP service, then prove a new job carries the new owner instance and its
   completion/resource behavior matches. Do not add RPC version fields or
   mutate systemd units solely to obtain this evidence.
7. Run `BINNACLE_LIVE=1` live read-only tests, the repository full smoke and
   relevant tunnel/watchdog/jobs doctors, runtime versions, and final local/
   remote refs. Use controlled temporary job probes only when authorized by the
   implementation/deployment task. Require a real ChatGPT → deployed Binnacle
   read-only call and final wire parity. Record evidence without secrets.

There is currently no dedicated safe manager-restart command in the repository;
do not invent one in G3. The extra quiet verification above is an integration
precondition, not a new production service/lifecycle mechanism. In particular,
pending finalizers require a conservative check, since the normal running-job
doctor alone does not account for them. A stale pending record with unknown
accounting state is a blocker to restart, not permission to remove it.

### 13.1 Existing-mechanism admission barrier for manager activation

This is a future, explicitly authorized maintenance procedure, not a new runtime
validator or a change to the deploy script. It temporarily stops MCP admission
while leaving the stable manager running until the final safe restart:

1. Establish an exclusive maintenance window with other local operators/agents.
   Quiesce any direct manager RPC clients and concurrent deploy/start commands.
   Protocol 1 has no admission lock or in-flight query; if another direct writer
   cannot be excluded, do not restart. Do not assume MCP is the only writer
   merely because it is the normal product path.
2. Run the existing quiet checks with running jobs included. Require readable
   journals and completion/drain evidence for admitted tool/RPC calls, not just
   elapsed time. A missing completion or an unknown/incomplete durable record
   blocks this operation. Leave the manager running for work to finish.
3. Gracefully stop only `binnacle-mcp.service` with `systemctl --user stop`.
   Verify it is inactive, MainPID is 0, and its configured HTTP listener refuses
   connections. Require clean shutdown; forced shutdown or an unaccounted RPC
   means restore MCP and defer the manager restart. No new calls may enter
   through MCP from this point until the procedure explicitly starts it again.
4. Repeat the job/RPC/accounting inventory after MCP is stopped. This catches a
   job admitted between the first quiet check and stopping MCP. Require every
   admitted call settled, no running/unfinished/unknown job, no incomplete spool
   reservation, no `cgroup_cleanup_pending`, and no populated per-job accounting
   scope. Inspect accounting identities read-only, including orphan scopes, with
   existing Linux helpers. Unavailable evidence is not equivalent to empty.
   Keep checking that MCP stays stopped; do not restart the manager if another
   actor reopens admission. A pending item means restore MCP, keep the current
   manager alive, and defer; never kill that item to satisfy the checklist.
5. Only while those conditions hold, restart/verify the manager and then start
   `binnacle-mcp.service`. If activation is abandoned before manager restart,
   start MCP again and verify it reconnects to the unchanged manager. If manager
   activation fails, keep the evidence and follow the quiet rollback sequence;
   do not expose a half-verified owner to new MCP work.

An explicit stop does not trigger `Restart=` automatic recovery; see the
[systemd service specification](https://github.com/systemd/systemd/blob/v252/man/systemd.service.xml).
The current watchdog service policy also leaves deliberately stopped MCP units
alone (`ops/watchdog/services.py`). No watchdog, tunnel, unit, masking, or settings
change is required. Reconfirm these facts from current unit/policy state at the
future maintenance boundary. Exclusive operator control remains a precondition;
the existing system has no global admission lock against arbitrary local writers.

The isolated admission probe is mandatory before deployment: real HTTP MCP and
private manager processes, a controlled start between first check and barrier,
second-check refusal while that job lives, refused post-barrier HTTP calls, and
successful temporary-manager restart only after known work is complete. The
probe never operates production units. This proves the product admission path
and conservative deferral; it does not claim to fence uncontrolled local actors.

If rollback occurs before manager restart, the old manager remains active and
the unchanged protocol/spool supports the old MCP. If rollback is needed after
restart, apply the same quiet conditions before any second manager restart.
Use the repository-reviewed revert/CI/canonical deploy flow for remote history;
do not force-reset deployment refs. No data/schema rollback or spool deletion is
required. Keep completed job records and external evidence.

G3 is done only after implementation review, exact-SHA CI, canonical deploy,
actual stable-manager revision verification, live/doctors/smoke, and real
ChatGPT read-only verification. A doc-only completion update follows the normal
CI/deploy flow. G4/G5/G6 remain separate groups with their own detailed designs.

## 14. Design completion record

Design baseline and probes are recorded in section 1.2. The first fresh review
verified all 120 payload inventory hashes and requested three changes: accounting
must decorate supplied argv, the exact pending key is `cgroup_cleanup_pending`,
and manager activation needs an admission barrier. Sections 5/6/13 now resolve
those findings, supported by the added isolated probes. Default-backend startup
timing and archived-source mixed-version provisioning were also clarified.
The [fresh ChatGPT review](https://chatgpt.com/c/6ac065bc-7ce8-83ec-9d06-83720da0f36b)
approved the revised design with all four cells PASS and no remaining findings.
It verified all 139 payload hashes in `g3-review-r2-final.zip`, SHA256
`d3a0f83ea7efbfd5ff97defbd7c66b5e9e1373b58f7cb52ef763dcbc35bced2d`.
The retained `review-r2-reply.txt` explicitly distinguishes design evidence from
future implementation and production-activation proof.

Changed-doc pre-commit passed after revisions (`design-doc-gate-4.log`). The
final status/evidence-only update is checked again before commit. The 314-test
baseline, original lifecycle probe, new accounting-decoration and admission
probes, and architecture/import/strict-size checks passed. No source, test,
dependency, or lockfile changed. No production service or deployment ref changed.

During review and final checks, another task added and updated untracked files
under production's existing `docs/chatgpt-mcp-development/` area. Those files were
left untouched by this task. All 16 other worktree HEADs and production tracked
state stayed unchanged. The external before/after preservation records distinguish
these concurrent document changes from this task's two-file diff; they do not
claim that another writer's untracked files stayed byte-identical throughout.

Only this document and the implementation master are committed. G3 is ready
for coordinator review of this design commit, not implementing or done.
Stop here; a separate task starts G3 implementation after that review.

## 15. Serial implementation evidence

The user authorized the dedicated implementation worker at design commit
`78954f08b0024f151082bbdb59677c8ea0513fa2`, on
`refactor/g3-commands-platform-seams` in `binnacle-g3-commands-impl`.
This worker owns only G3.0 through G3.2d. It must stop at a clean committed
G3.2d freeze for separate Process and Resource preparation lanes. It must not
push, deploy, activate platform ports, or begin G4-G6.

External evidence and the durable checkpoint ledger are at
`/home/grammy-jiang/.local/state/binnacle/g3-implementation-20261003T030542Z-m481gfu3`.

G3.0 passed: clean assigned HEAD, doctor 9/9, current offline lock, arm64 runtime,
FastMCP/FastMCP-slim 4.0.10 and MCP/MCP-types 2.1.1. Production HEAD and remote
deployment refs remain `68e690d`. The older local `proof-of-concept` ref was
observed and left unchanged. Other worktrees and production documents were
not changed. The usage guard returned its critical exit; no unattended manager
was started.

The B+C+L+M+D+P+R+T baseline passed 386 tests with seed 12345. Architecture,
all seven import contracts, and strict size passed. The four-profile raw wire
archive preserves all three Commands hashes. The archived baseline package,
spool fixtures, isolated manager/embedded lifecycle and accounting probes are
retained externally. The probes confirmed manager survival of MCP-worker exit,
fresh-root cursor/stop behavior, PID token checks, and optional accounting.
No production service operation occurred.

G3.1 added exact run/stop replies, exception causes and catch boundaries,
wait-error timing, scripted post-death/reaper waits, owner routing, resource-only
merge keys, prune-safe finalizer callbacks, distinct atomic temporary files,
process-summary parsing, and separate MCP-worker reload characterization.
The broad B+C+V+L+M+D+P+R+T selection passed 486 tests; the final eight-case
lifecycle characterization selection also passed after two additional wait cases.
Architecture, seven import contracts, and strict size passed. An intentional
resource-merge fault failed the exact-field test, without changing source files.
Both archived-baseline/candidate revision directions passed start/cursor/stop/
repeated-stop probes. The isolated HTTP admission probe passed, including a
late-arrival job and the exact `cgroup_cleanup_pending` barrier. Production
source, persisted fixtures, schemas, dependencies, and services are unchanged.

G3.2a adds only the frozen reply/failure/backend contracts and the stateless
`DurableCommandBackend`, with delegate and subprocess construction tests.
Exported tools do not use it yet. Construction imports no engine/settings;
explicit default selection captures the existing engine settings before requests.
All values, unknown dictionary keys, and exception identities pass through.
The focused selection passed 423 tests; architecture, seven import contracts,
strict size, and mypy passed. The complete wire archive is byte-identical to G3.0.
A capture-script filename collision was corrected in external evidence only.

G3.2b moves run dispatch/output/telemetry to `command_execution` over the explicit
backend. The adapter retains path validation, copied settings, MCP conversion,
and call-time implementation lookup. Factory injection preserves backend identity,
including false-valued fakes. Exact error causes and unexpected exceptions remain
unchanged. Fake-backed native run calls prove isolation and argument ordering.
The focused selection passed 428 tests; architecture, seven import contracts,
strict size, and mypy passed. The full wire archive remains byte-identical.
