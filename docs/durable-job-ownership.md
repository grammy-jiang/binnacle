# Durable local job ownership

Status: design baseline for `feature/durable-job-ownership`.

This change is developed entirely in an isolated worktree. The production Binnacle MCP
checkout remains unchanged until the full implementation, compatibility suite, restart
matrix, performance gate, and rollback checks pass.

## 1. Problem statement

`run_command` currently launches `bash -c` directly from the FastMCP/uvicorn process.
The child uses `start_new_session=True`, so it has its own process group and survives an
ordinary uvicorn worker reload. It does **not** have ownership independent of the
`binnacle-mcp.service` cgroup. The deployed user unit has `KillMode=control-group`, so a
full service restart or stop may terminate commands that are still running.

The final exit status is also owned by process memory: either the original request thread
waits on the `Popen`, or an in-process daemon reaper thread does. If that owner disappears
before the child exits, the durable `meta.json` has no final exit code and the job later
becomes `unknown`.

The target invariant is narrower and explicit:

> Restarting, crashing, hot-reloading, or switching the MCP server must not terminate an
> already-started `run_command` job or lose its eventual exit result.

A restart of the job owner itself or a host reboot may interrupt arbitrary shell commands;
such interruptions must become durable, classified terminal states rather than `unknown`.

## 2. Current implementation inventory

### 2.1 `run_command`

`src/binnacle/tools/run_command.py` currently:

1. validates `workdir` through the shared path guard;
2. resolves synchronous/background wait policy;
3. calls `jobs.start_job()`;
4. waits on the returned `Popen` for the foreground window;
5. records a synchronous exit inline, or starts a daemon reaper when the wait expires;
6. reads the durable state and output spool;
7. returns the existing MCP schema.

The MCP contract must remain unchanged in this migration.

### 2.2 `jobs.py`

`src/binnacle/jobs.py` currently combines four responsibilities:

- durable job-directory storage and retention;
- process launch and environment construction;
- exit ownership/reaping and stop escalation;
- state/list/output helpers used by the MCP tools.

The current store is one directory per job under
`~/.local/state/binnacle/jobs/<job_id>/`, with atomic replacement of `meta.json`, a spooled
`stdin`, and merged `out.log`.

### 2.3 `job_status`

`src/binnacle/tools/job_status.py` intentionally reads durable state rather than relying on
an MCP session. It also derives quiet time and scans `/proc` for processes in a running
job's process group. Listing behavior, wait semantics, timing telemetry, and output schema
are existing public contracts.

### 2.4 `stop_job`

The current stop path sends SIGTERM to the process group, finds descendants that escaped
that group via `setsid()`, waits for the exit recorder, then escalates to SIGKILL. This
behavior has extensive integration coverage and should not be redesigned in the first
ownership migration.

### 2.5 Deployment coupling

`binnacle setup` currently provisions the bearer token and one managed systemd user unit,
`binnacle-mcp.service`, then performs `daemon-reload`, `enable --now`, and enables linger.
Production mode runs the installed `binnacle serve`; development mode runs the checkout
with uvicorn auto-reload.

`binnacle mode` currently refuses to restart the MCP service while background jobs are
running because those jobs live in the MCP unit cgroup. That restriction should disappear
once ownership is separated; only in-flight MCP calls remain a reason to defer an MCP
restart.

`binnacle doctor` currently checks the MCP service, its environment, the job spool, and
`unknown` jobs. `binnacle stats` currently reads the MCP unit journal only, including
`job_start`/`job_exit` events that are written by the MCP process today.

## 3. Options investigated

### 3.1 One systemd service per command

Systemd transient services and a temporary template unit were tested on the live host.
They correctly handled normal/non-zero exit, SIGTERM, TERM-to-KILL escalation, `setsid()`
children through cgroups, unit collection, and `daemon-reload` while active.

This is not the selected implementation because launch overhead is material for Binnacle's
workload:

- transient service launch observed roughly 60–90 ms;
- template starts across ten runs observed 28–101 ms, median about 59 ms;
- the last seven days contain 7,307 synchronous `run_command` results with a median around
  117 ms; 3,621 were below 100 ms and 5,012 below 500 ms.

Adding tens of milliseconds to every short shell command is an unacceptable default
regression.

### 3.2 SQLite-only persistence

Replacing `meta.json` with SQLite does not solve ownership. If the process that owns the
`Popen.wait()` disappears, SQLite cannot reconstruct the lost Unix child wait status.
Storage and ownership are separate problems.

SQLite therefore remains deferred until a future workload needs parent/child distributed
jobs, leases, retries, worker assignment, or queries that justify a relational state store.

### 3.3 Selected: one stable job-manager service

Run one sibling systemd user service for execution ownership:

```text
systemd --user
├── binnacle-mcp.service       MCP/control plane; may reload/restart
└── binnacle-jobs.service      stable command owner; no auto-reload
    ├── job A
    ├── job B
    └── job C
```

The MCP service communicates with the manager over a local Unix socket. The manager owns
`Popen` objects and their reapers. Both services run as the same Unix user on the same
host, so commands keep the same filesystem, network, device, credential, and process
namespace expected by the existing toolset.

A minimal AF_UNIX proof of concept measured `/bin/true` at about 0.328 ms median via direct
`Popen` and 0.382 ms through a persistent Unix-socket manager plus `Popen`, an added median
cost of about 0.055 ms. A production protocol will be more expensive than that synthetic
minimum, but this establishes the correct order of magnitude and justifies a performance
gate rather than per-job systemd overhead.

## 4. Product and API invariants

The following must remain unchanged to MCP clients:

- tool names: `run_command`, `job_status`, `stop_job`;
- current input schemas and annotations;
- synchronous fast-command behavior;
- `background_job` semantics;
- nullable `exit_code` / `signal` output fields;
- output clipping and `tail_lines` behavior;
- `wait_seconds` wait-not-kill behavior;
- `stdin`, `workdir`, environment hygiene, and path guard behavior;
- recent-job listing behavior and command previews;
- stop idempotence;
- full output retained on disk.

ChatGPT must not need to know that a job-manager service exists.

## 5. Responsibilities after the split

### 5.1 `job_store.py`

Owns durable state only:

- job ID allocation;
- job directory creation;
- atomic metadata read/update;
- stdin/output paths;
- retention and listing;
- schema-version compatibility;
- terminal-state immutability checks;
- boot/owner recovery metadata.

It does not call `Popen`, signal processes, or run an IPC server.

### 5.2 `job_manager.py`

Runs as `binnacle-jobs.service` and owns:

- AF_UNIX request server;
- process launch;
- in-memory `job_id -> Popen` ownership for jobs started by this instance;
- exit wait/reaping;
- current stop behavior, initially moved without semantic redesign;
- startup recovery/classification;
- manager-side `job_start`, `job_exit`, recovery, and lifecycle logs.

It is deliberately **not** auto-reloaded in development mode.

### 5.3 `job_client.py`

Runs inside the MCP process and owns:

- connect/request/response protocol;
- manager availability errors;
- `start`, `stop`, and `ping` operations;
- bounded IPC timeout/error translation.

The MCP does not receive or retain a `Popen` object.

### 5.4 `job_process.py`

Keep the current `/proc`, process-group, descendant, and signal helpers for the first
migration. This deliberately avoids coupling durable ownership to a second redesign of
stop semantics. Per-job cgroups can be evaluated later as an independent change.

### 5.5 MCP tools

`run_command` becomes orchestration only:

1. validate arguments;
2. ask the manager to start the job;
3. wait/read durable state for the requested foreground window;
4. return the same current result.

`job_status` should continue reading durable state directly wherever possible. Running
process inspection can remain `/proc` based. `stop_job` sends a stop request to the manager,
then reads the durable result.

## 6. IPC protocol

Use an AF_UNIX stream socket under the user's runtime directory, for example:

```text
$XDG_RUNTIME_DIR/binnacle/jobs.sock
```

The runtime directory/socket must be private to the current user. The protocol is internal
and versioned from the first implementation.

Minimum request operations:

```json
{"version":1,"op":"ping"}
{"version":1,"op":"start","job_id":"...","call_id":"..."}
{"version":1,"op":"stop","job_id":"..."}
```

The raw shell command does not need to traverse the socket if the MCP has already committed
it to the job record; `start` may refer only to the durable job ID. This reduces IPC payload
size and keeps the durable request as the source of truth.

Responses must be bounded and machine-readable. Manager protocol errors are internal and
must be translated into stable MCP `ToolError` messages rather than leaking implementation
tracebacks.

## 7. Durable state schema

Keep the per-job filesystem store for this migration. Add an explicit schema version and
owner/recovery fields while preserving a legacy-reader path for existing records.

A version-2 record needs, at minimum:

```text
schema_version
job_id
command
workdir
created_at
started_at
owner_instance_id
boot_id
pid
pgid
starttime
exit_code
signal
ended_at
termination_reason
stop_requested
```

`termination_reason` should distinguish at least:

- `normal_exit`;
- `signal`;
- `stop_requested`;
- `owner_restart`;
- `host_reboot`;
- `launch_failure`;
- `ownership_lost` only for evidence that cannot be classified more precisely.

The public MCP `state` remains compatible during this migration; richer internal reasons do
not require an immediate tool-schema expansion.

Terminal results are immutable except for explicitly versioned repair/migration tooling.

## 8. Owner and boot identity

Each `binnacle-jobs.service` start generates a fresh random `owner_instance_id`. The
manager also reads the Linux boot ID. New jobs record both.

At manager startup, any non-terminal record from a previous owner is reconciled:

- different boot ID -> `host_reboot`;
- same boot, different owner -> `owner_restart` unless evidence establishes a different
  terminal result;
- malformed/incomplete record -> preserve current defensive behavior and surface a clear
  diagnostic rather than inventing success.

The first implementation intentionally allows manager restart to terminate jobs because
`binnacle-jobs.service` uses `KillMode=control-group`. The invariant being introduced is
MCP-lifecycle independence, not owner-lifecycle independence.

## 9. Systemd deployment

Add a managed sibling unit, conceptually:

```ini
[Unit]
Description=Binnacle command job manager

[Service]
Type=simple
ExecStart=<absolute installed binnacle runtime entry> ...
Restart=always
RestartSec=1
KillMode=control-group
UMask=0077

[Install]
WantedBy=default.target
```

The exact internal entry point should be packaged with the wheel but need not become a
user-facing workflow. Production and development MCP modes both point at a stable manager
entry point chosen by `binnacle setup`.

The manager unit does **not** use uvicorn/watchfiles reload semantics.

## 10. Setup, mode, upgrade, and rollback

### `binnacle setup`

Remain the single user-facing provisioning command. It should eventually:

1. preflight systemd user-manager availability;
2. keep/create the token;
3. plan/write the managed MCP unit;
4. plan/write the managed jobs unit;
5. create/verify state and runtime directories;
6. `systemctl --user daemon-reload` once;
7. enable/start the jobs service;
8. enable/start the MCP service;
9. enable linger;
10. verify both services.

Setup stays idempotent and refuses to overwrite foreign unit files without the existing
`--adopt` contract.

### `binnacle mode`

After ownership migration, running background jobs are no longer a reason to reject an MCP
service restart. Recent/in-flight MCP calls remain a quiet-moment concern.

Restarting the jobs service is a separate operation and must have its own quiet gate.

### Upgrade

Changing MCP code/unit may restart MCP without disturbing jobs. Changing manager code/unit
must not silently restart the manager while jobs are running. Initial policy should defer
that restart and report drift/required action rather than kill active work.

### Rollback

During migration, keep the embedded owner implementation behind a deployment-only switch.
The public tool schema remains identical, so rollback does not require MCP client refresh.
Legacy v1 job records remain readable for at least one release/migration window.

## 11. Environment equivalence

The manager and MCP services must inherit the same relevant systemd user-manager
environment. The current command behavior inherits the MCP process environment and then
applies:

```text
PAGER=cat
GIT_PAGER=cat
GIT_TERMINAL_PROMPT=0
PYTHONUNBUFFERED=1
CI=1
BINNACLE=1
DEBIAN_FRONTEND=noninteractive
```

The new manager must preserve that effective command environment. `binnacle doctor` must
validate the manager's PATH and critical executable resolution as well as the MCP service's.

## 12. Logging and statistics

Today `job_start`, `job_exit`, and `jobs_pruned` are in the MCP service journal, and
`binnacle stats` reads one unit. After migration:

- MCP journal owns request/tool records;
- jobs journal owns job-lifecycle records;
- the MCP call ID is sent to the manager with `start`, preserving `tool_call -> job_start`
  correlation;
- `binnacle stats` must merge both journals for the requested time window before parsing,
  or otherwise preserve equivalent job-exit statistics.

Do not silently lose historical metrics as a side effect of ownership separation.

## 13. Doctor changes

Extend `binnacle doctor` to verify:

- managed jobs unit is installed and matches setup output;
- jobs service is active and not crash-looping;
- Unix socket exists and responds to `ping`;
- state directory is writable;
- MCP and manager command environments resolve required tools consistently;
- recovery/interruption states are classified;
- journal error checks cover both MCP and jobs units.

The old warning text that calls every missing exit an orphan caused by a server stop must be
retired once the new owner is authoritative.

## 14. Compatibility test inventory

Existing behavior must be preserved for at least these cases:

### Run

- exit zero and output;
- merged stderr/stdout;
- non-zero exit code;
- one-shot stdin;
- working directory and root guard;
- environment hygiene;
- foreground completion;
- wait boundary -> background job;
- explicit background warm-up;
- configured auto-background policy;
- output head/tail budget;
- `tail_lines`;
- invalid UTF-8 replacement;
- large unread stdin must not block launch.

### Status

- unknown job error;
- newest-first listing;
- all running + bounded history;
- command preview and workdir;
- quiet detection;
- wait-until-exit and wait timeout;
- wait cap;
- process list while running;
- missing output log robustness;
- malformed legacy metadata robustness.

### Stop/lifecycle

- SIGTERM normal stop;
- SIGKILL escalation;
- process-group cleanup;
- `setsid()` child cleanup under current semantics;
- self SIGTERM / SIGKILL;
- exit code 128+N is not a signal;
- already-exited stop is idempotent;
- double concurrent stop agrees;
- external signal is recorded;
- PID reuse never signals a stranger;
- terminal state never returns to running.

### New durability gates

- uvicorn worker reload while a job runs;
- full `binnacle-mcp.service` restart while a job runs;
- MCP process crash while a job runs;
- dev -> prod and prod -> dev switch while a job runs;
- token/tunnel restart while a job runs;
- manager crash with running jobs -> classified `owner_restart`, never ambiguous `unknown`;
- simulated previous boot -> classified `host_reboot`;
- manager socket unavailable -> clean tool error, no half-launched job;
- manager restarts and accepts new jobs after recovery;
- manager and MCP journal correlation remains intact.

## 15. Performance acceptance gate

Compare the manager path with the current embedded path using representative short commands
and the real production distribution.

Primary gate:

- no material degradation of synchronous `run_command` latency;
- target added p50 overhead <5 ms, preferably <2 ms;
- no new output-size or token regression;
- background throughput/concurrency remains at least equivalent.

The synthetic Unix-socket proof of concept suggests this is feasible, but the real manager
protocol, persistence, logging, and locking must be measured.

## 16. Implementation stages

1. **Design freeze** — this document and the executable test matrix.
2. **Storage seam** — extract durable storage from `jobs.py`; behavior remains embedded and
   all existing job tests pass unchanged.
3. **Versioned IPC seam** — add manager client/protocol with fake/in-process tests, no live
   deployment.
4. **Manager runtime** — implement launch/reap/stop/recovery in an isolated test runtime.
5. **Owner feature flag** — embedded remains default; manager path can be exercised in the
   worktree only.
6. **Durability matrix** — prove MCP reload/restart/crash/mode-switch survival and manager
   failure classification.
7. **Performance gate** — compare real short/medium/long command workloads.
8. **Deployment integration** — setup/unit/doctor/mode/stats changes only after runtime is
   proven.
9. **Shadow deployment** — install manager on the development host without switching
   production ownership; verify health and observability.
10. **Local owner switch** — switch this host to manager ownership with an immediate
    configuration rollback path.
11. **Observation window** — use real work, including background tests/builds, before
    deleting the embedded owner.
12. **Default flip and cleanup** — manager becomes product default only after the evidence
    above is satisfactory; then remove obsolete reaper/orphan code in a later cleanup.

## 17. Explicit non-goals for this change

Do not combine this migration with:

- SQLite adoption;
- multi-host/distributed execution;
- Docker execution backends;
- per-job systemd units/cgroups;
- pytest sharding;
- a new MCP tool;
- a generic command-duration predictor;
- unrelated search/readability work.

The sole goal is durable local ownership across MCP lifecycle changes with minimal latency
and no client-visible regression.
