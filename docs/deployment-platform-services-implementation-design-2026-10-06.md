# G4 deployment/platform services — implementation design — 2026-10-06

Status: **ready for implementation; independent ChatGPT design review R8 approved on 2026-10-06**.

Baseline: production/deployed documentation commit
`f21f86055ebea4ae5fc14c4aa6aed6e19c3f3d1e`, whose runtime source is
identical to G3 implementation `01523d406732dddf1421eabd93269ad09c25e5ea`.

This document is the detailed implementation design for Group 4 of
`docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`.

It was prepared from the current repository after G3 production completion.
The design phase is owned by ChatGPT Chat Mode. Local Codex is not the
investigation/design owner for this group.

## 1. Purpose and design posture

G4 removes Linux deployment assumptions from generic Binnacle application and
deployment orchestration while preserving the current Linux behavior exactly.

The three responsibilities are:

1. service-log acquisition;
2. managed-service lifecycle/provisioning;
3. host runtime-path conventions.

The first implementation remains Linux-only and keeps systemd, journald,
procfs, and the current XDG runtime-directory behavior behind narrow Binnacle
platform contracts.

G4 is an extraction, not a product redesign. The safest implementation shape is:

```text
characterize current behavior
        |
        v
introduce a narrow contract and Linux adapter
        |
        v
prove byte/semantic parity through existing tests
        |
        v
switch one caller family
        |
        v
retain a compatibility facade where useful
        |
        v
repeat
```

Do not introduce macOS/launchd behavior in G4. The point is to make such an
adapter possible later without changing current Linux behavior.

## 2. Inputs and current evidence

Architecture/control inputs:

- `docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`;
- `docs/platform-neutral-architecture-design-2026-10-02.md`;
- `docs/fastmcp-native-architecture-investigation-2026-10-02.md`;
- `docs/fastmcp-native-refactor-high-level-plan-2026-10-02.md`;
- `docs/commands-platform-seams-implementation-design-2026-10-03.md`;
- `DEVELOPMENT.md`;
- `AGENTS.md`.

The three architecture input documents from 2026-10-02 are currently
user-owned untracked documents in the production checkout. G4 must not adopt,
delete, rewrite, or otherwise take ownership of them.

The isolated design worktree is:

```text
/home/grammy-jiang/Projects/binnacle-g4-design
branch: design/g4-deployment-platform-services-2026-10-06
base:   f21f86055ebea4ae5fc14c4aa6aed6e19c3f3d1e
```

Before this design was written, the focused current-state baseline passed:

```text
120 focused tests passed
architecture: 111 modules, 0 forbidden reverse dependencies
strict module-size gate: 0 errors
```

The focused baseline covered journal IO, unit mechanics, job-manager unit
rendering, setup/mode integration, CLI glue, doctor coverage, deploy flow, and
live-smoke orchestration.

## 3. Current-state dependency graph

The current core/deployment path is approximately:

```text
binnacle CLI
  |
  +--> server_unit.py --------------------+
  |                                       |
  +--> job_manager_unit.py                v
  |                                    units.py
  |                               (systemd unit files,
  |                                systemctl-backed checks,
  |                                procfs process check)
  |
  +--> doctor.py
  |      |
  |      +--> doctor_common.py
  |      |      +--> systemctl --user
  |      |
  |      +--> logstats.fetch_journal()
  |             |
  |             v
  |        logstats_io.py
  |             |
  |             +--> journalctl --user
  |
  +--> stats
         |
         +--> logstats.fetch_journal()
                |
                +--> journalctl --user

scripts/deploy_smoke.py
  |
  +--> read_journal() --------------------> journalctl --user
  |
  +--> smoke_checks.Env(run, journal, ...)
  |
  +--> deploy_flow.py
          |
          +--> systemctl --user restart binnacle-mcp.service

config.py
  |
  +--> _default_jobs_socket()
          |
          +--> XDG_RUNTIME_DIR
          +--> /run/user/<uid>/binnacle/jobs.sock
```

The companion side also contains direct systemd/journal usage. That is
intentionally not all migrated in G4:

```text
watchdog/tunnel companion code
  +--> direct systemctl/journal behavior
  +--> existing unit rendering helpers
```

Companion dependency cleanup belongs primarily to G5. G4 may provide reusable
contracts/adapters that G5 can adopt, but must not broaden into watchdog/tunnel
redesign.

## 4. Platform-leakage inventory

### 4.1 Service-log acquisition

Current canonical core acquisition:

- `src/binnacle/logstats_io.py::fetch_journal` directly invokes
  `journalctl --user`;
- `binnacle stats` uses it;
- `binnacle doctor` uses it for recent-error scanning;
- restart quiet-window logic uses the same journal source through doctor/job
  checks.

Current canonical deployment acquisition:

- `scripts/deploy_smoke.py::read_journal` independently invokes
  `journalctl --user`;
- `scripts/deploy_flow.py` consumes the injected `Env.journal` to detect
  the quiet window and code-load evidence.

Other direct journal users exist in historical/weekly/migration/companion
tools. They are inventoried but are not automatically in G4 scope. Each one
must be classified before migration rather than swept into a broad rewrite.

### 4.2 Managed-service lifecycle

Direct systemd knowledge is currently spread across:

- `src/binnacle/cli.py`:
  `_systemctl`, `_unit_state`, daemon-reload, enable/start, restart;
- `src/binnacle/doctor_common.py`:
  `systemctl`, `unit_state`, `unit_property`;
- `src/binnacle/units.py`:
  unit-file rendering/planning plus live process/service checks;
- `src/binnacle/doctor.py`:
  systemd properties, loginctl, and direct `/proc/<pid>/environ` reads for the
  managed service `PATH`;
- `src/binnacle/doctor_jobs.py`:
  systemd state/main PID plus direct `/proc/<pid>/environ` reads for the
  `BINNACLE_MANAGED_DEPLOYMENT=1` restart-safety marker;
- `scripts/deploy_flow.py`:
  direct server restart;
- `scripts/smoke_checks.py`:
  direct `systemctl show` for service/cgroup/startup facts.

The current unit renderers are intentionally systemd-specific:

- `server_unit.py`;
- `job_manager_unit.py`;
- `tunnel_unit.py`;
- `watchdog_unit.py`.

They should remain Linux adapter material in G4 rather than being disguised as
portable service-definition objects.

### 4.3 Runtime-path conventions

The canonical server leakage is currently small but important:

`src/binnacle/config.py::_default_jobs_socket` chooses:

```text
$XDG_RUNTIME_DIR/binnacle/jobs.sock
```

or falls back to:

```text
/run/user/<uid>/binnacle/jobs.sock
```

The systemd job-manager unit independently creates the matching
`RuntimeDirectory=binnacle`.

Some weekly/host scripts construct `/run/user/<uid>` for the user bus. They
are not generic application configuration and should be classified separately
rather than forcing G4 to refactor unrelated weekly infrastructure.

## 5. UX evaluation

G4 should be nearly invisible to a Binnacle operator.

### 5.1 Current UX strengths to preserve

The current Linux UX is already strong in the areas G4 touches:

- `binnacle setup --dry-run` explains every planned action without mutation;
- hand-written or foreign unit files are refused unless `--adopt` is explicit;
- rewritten units are backed up;
- `binnacle mode` performs a quiet-window safety check before restart and
  preserves `--force` as the explicit override;
- one stable server unit name survives dev/prod switching;
- `binnacle doctor` distinguishes OK/WARN/FAIL and provides actionable hints;
- the canonical deployment gate waits for CI and a quiet window, performs the
  live smoke, and rolls back on failure;
- the stable jobs manager is deliberately not restarted by ordinary deployment.

These are product contracts, not incidental systemd implementation details.

### 5.2 Current UX weaknesses caused by platform coupling

The visible commands mostly work well. The primary problems are hidden
consistency and future portability risks:

1. Service state/restart behavior is implemented in several places, so timeout,
   failure, and output semantics can drift.
2. Journal acquisition is duplicated between product statistics/doctor and
   deployment smoke.
3. `stats --unit` and several help/hint strings expose Linux/systemd
   vocabulary. This is acceptable for the current Linux product and must not be
   renamed merely for architectural purity.
4. `doctor` hints currently recommend raw `systemctl`, `journalctl`, and
   `loginctl` commands. G4 should preserve those Linux hints; G5 owns
   diagnostics/operations UX restructuring.
5. Runtime socket selection is hidden inside configuration construction rather
   than an explicit host convention.
6. The same service lifecycle semantics are not reusable by a future non-systemd
   adapter because orchestration calls subprocess/systemctl directly.

### 5.3 G4 UX decision

**No new public command, required flag, output schema, or workflow is justified
for G4.**

Compatibility requirements:

- keep `binnacle setup`, `mode`, `doctor`, `stats`, and token commands;
- keep current options, defaults, exit codes, and Linux-visible unit names;
- keep current dry-run/adopt/backup semantics;
- keep quiet-window and rollback behavior;
- keep current Linux-specific help/hints unless a change is necessary to avoid
  lying after extraction;
- do not introduce a new `--platform`, `--service-manager`, or `--log-source`
  option;
- do not rename `--unit` in G4;
- do not expose the new internal contracts through MCP.

The intended UX improvement is operational consistency, not a new interface.

## 6. Goals

G4 is complete when:

1. stats/doctor/deploy obtain service logs through a Binnacle service-log
   contract with a Linux journald implementation;
2. generic deployment/control orchestration no longer invokes systemctl/loginctl
   primitives directly;
3. Linux service rendering/provisioning remains behaviorally identical behind
   the platform boundary;
4. generic configuration no longer constructs `/run/user/<uid>`;
5. the deployed Linux behavior, public MCP surface, durable-job behavior,
   setup/mode/doctor/stats UX, CI/deploy/rollback behavior, and live smoke remain
   compatible;
6. the boundary is explicit enough for a future platform adapter without
   implementing that adapter now.

## 7. Non-goals

G4 must not:

- implement launchd or macOS behavior;
- introduce a generic plugin framework for operating systems;
- change FastMCP composition, visibility, providers, transforms, middleware,
  Tasks, or public MCP surface;
- redesign durable jobs, process identity, resource accounting, cgroups, spool
  format, job RPC, or manager ownership;
- redesign log parsing, telemetry events, statistics calculations, or journal
  message format;
- reorganize diagnostics ownership or remove watchdog reverse dependencies;
  those are G5;
- add the public operational HTTP surface; that is G5;
- move packages into final `platform/linux` ownership; broad movement is G6;
- change tunnel/watchdog behavior except for a narrowly required compatibility
  import;
- replace current service-unit templates with a generic cross-platform service
  DSL;
- add `platformdirs` or another runtime-path dependency;
- rebaseline MCP wire/goldens to hide drift.

## 8. Proposed responsibility boundaries

### 8.1 Service-log contract

Introduce a narrow contract whose only responsibility is acquiring text emitted
by one or more managed services in a bounded time window.

Conceptual platform-neutral interface:

```python
class ServiceLogError(RuntimeError):
    """The platform log source could not satisfy a bounded read."""

class ServiceLogSource(Protocol):
    def read_window(
        self,
        services: Sequence[str],
        since_epoch: float,
        until_epoch: float | None = None,
    ) -> str:
        ...
```

The current public CLI has a separate Linux compatibility boundary.
`binnacle stats` and `binnacle doctor --since` intentionally accept
journalctl-compatible strings such as `-24 hours`, `2 days ago`, and `now`.
G4 preserves that UX exactly, but those strings are **not** declared portable.
The Linux `JournalServiceLogSource` therefore also exposes a Linux-only
`read_spec(services, since: str, until: str | None)` compatibility method, and
`logstats_io.fetch_journal(...)` remains a temporary facade over that method.
A future non-journald platform is required to implement only the semantic
`read_window()` contract; making the legacy CLI time grammar portable is a
separate user-visible design problem.

Caller ownership is explicit. The semantic `ServiceLogSource` is consumed only
through `read_window(epoch)`; it is **not** the interface for the legacy
journalctl-style string grammar.

- `binnacle stats`, doctor, and mode restart-safety continue through the
  Linux-only `logstats_io.fetch_journal(...)` compatibility facade, which
  delegates to `JournalServiceLogSource.read_spec(...)`. They do not require a
  generic `ServiceLogSource` implementation to understand strings such as
  `-24 hours` or `now`.
- canonical deployment uses `ServiceLogSource.read_window()` directly.
  `scripts/deploy_smoke.py` is the Linux composition point and adapts returned
  raw text with `splitlines()` into the existing
  `Env.journal(since, until) -> list[str]` callback. The `Env` test seam stays
  intact; `scripts/deploy_flow.py` and `scripts/smoke_checks.py` remain unaware
  of journalctl syntax.

A future non-journald `ServiceLogSource` therefore needs to implement only
`read_window()` and is never required to expose `read_spec()`.

Rules:

- both paths return raw text; parsing remains in `logstats`/doctor;
- multiple-service ordering/merging preserves journald's current behavior on
  Linux;
- acquisition failure is `ServiceLogError`, not `SystemExit`;
- the Linux CLI compatibility facade may translate `ServiceLogError` to the
  same user-facing command failure it has today;
- doctor turns log-source failure into WARN;
- every restart/quiet gate fails closed when logs are unreadable;
- live smoke reports an ALERT when required log evidence is unreadable;
- the contract does not define telemetry/event parsing.

Linux implementation:

```text
JournalServiceLogSource(command_timeout_s: float | None)
  +--> read_window(epoch seconds)
  +--> read_spec(journalctl-compatible strings; Linux compatibility only)
  \--> journalctl --user ...
```

Literal argv ordering is also frozen per current caller because the final focused
tests claim exact argv parity, even though journalctl accepts equivalent option
orderings:

- core `logstats_io.fetch_journal()` compatibility order remains
  `journalctl --user`, repeated `-u UNIT`, `--since SPEC`, `-o cat`,
  `--no-pager`, then optional `--until SPEC`;
- canonical deploy/smoke epoch order remains `journalctl --user -u UNIT`,
  `--since @N`, optional `--until @M`, then `--no-pager -o cat`.

This removes ambiguity from the phrase "exact argv" without promoting option
ordering to a portable contract.

Execution timeout is a Linux adapter/composition policy, not part of the
semantic `ServiceLogSource` protocol. Preserve the two current behaviors
explicitly:

- core `stats` / doctor / mode compatibility composition uses
  `command_timeout_s=None`, preserving today's unbounded `logstats_io`
  subprocess behavior; G4 does not silently introduce a new core CLI timeout;
- canonical deploy/smoke composition uses `command_timeout_s=60.0`, preserving
  today's `deploy_smoke.read_journal()` per-read 60-second bound.

`read_window()` preserves the canonical deploy's exact epoch conversion:
`since_epoch` is truncated with `int()` and emitted as `--since @N`; when an
`until_epoch` exists it is truncated with `int()`, incremented by one second,
and emitted as `--until @N`. This is the current bounded-window behavior in
`deploy_smoke.read_journal()` and is frozen for G4; changing edge inclusivity is
a separate behavioral review.

`subprocess.TimeoutExpired`, launch/OSError, and non-zero journalctl completion
all become `ServiceLogError` with bounded diagnostic detail. A deploy timeout is
therefore processed by exactly the same fail-closed phase mapping as another log
acquisition error. The deploy's higher-level `quiet_timeout` / reload control
remains meaningful because no single journal acquisition can block longer than
60 seconds. Changing the historical core CLI's unbounded read is deliberately
left for a separate reviewed UX/reliability change.

### 8.2 Managed-service inspection and control contracts

The first draft used one `ManagedServiceLifecycle` protocol. Current-code review
showed that this mixed read-only inspection with mutation and still did not
cover the facts needed by doctor and smoke. G4 therefore splits the capability
in two. One concrete Linux object may implement both protocols.

```python
@dataclass(frozen=True, slots=True)
class ManagedServiceStatus:
    state: str
    main_pid: int | None = None
    restart_count: int | None = None

@dataclass(frozen=True, slots=True)
class ServiceAction:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    launch_error: str | None = None

class ManagedServiceInspector(Protocol):
    def status(self, service: str) -> ManagedServiceStatus: ...

    def started_at_epoch(self, service: str) -> float | None: ...

    def rss_kb(self, service: str) -> float | None: ...

    def main_process_has_environment(
        self, service: str, name: str, value: str
    ) -> bool | None:
        """True/False when inspectable; None when it cannot be established."""
        ...

    def main_process_path(self, service: str) -> str | None:
        """The main process PATH, or None when it cannot be inspected."""
        ...

class ManagedServiceController(Protocol):
    def restart(
        self, service: str, *, timeout: float | None = None
    ) -> ServiceAction: ...
```

This covers the portable meanings the current callers actually use:

- raw service-manager state text, preserving active/inactive/failed/transitional states;
- main PID;
- crash-restart count;
- process start time for smoke measurement through a named capability;
- resident memory for smoke measurement through a named capability;
- one narrow main-process environment-marker query needed by the existing
  restart-safety ownership check;
- the main process `PATH` string needed by the existing service-environment
  doctor check;
- restart as the only generic service mutation.

The environment capabilities are not an arbitrary process-environment property
bag. Generic callers get only the two semantics current code already consumes:
exact marker membership and the service `PATH`. The Linux implementation may
read `/proc/<pid>/environ`; generic code must not. If the environment cannot be
inspected, the methods return `None`; restart safety maps that to the same
conservative non-manager result it uses today, while doctor preserves its
current WARN behavior for an unreadable service environment.

It deliberately does **not** expose
`systemctl show -p <arbitrary-property>`. Linux-specific facts such as
`ExecStart`, `ExecStartPost`, `LoadError`, `After`, unit-file paths,
`RuntimeDirectory`, and `DelegateSubgroup` stay in Linux
provisioning/diagnostic helpers. G5 later decides their final diagnostic
ownership.

Linux implementation:

```text
SystemdUserServices
  -> systemctl --user for status/restart
  -> cgroup/procfs details only to produce semantic status fields
```

The split also protects tests and future orchestration from accidental mutation:
a read-only caller receives only `ManagedServiceInspector`. Expensive smoke-only
measurements are named methods rather than fields populated on every ordinary
status read.

`ManagedServiceStatus.state` preserves the service manager's observable state
text exactly on Linux. The Systemd adapter returns the current `is-active` text
(`active`, `inactive`, `failed`, `activating`, `deactivating`, `reloading`, and
other systemd states) and uses `unknown` only when there is no usable text. G4
does not normalize transitional/failure states into a smaller enum because that
would change `mode status` and doctor behavior.

`ServiceAction` also has fixed failure semantics. A completed service-manager
command preserves its real return code/stdout/stderr. A timeout is represented
with return code 124 and `timed_out=True`; an executable/launch `OSError` is
represented with return code 127 and `launch_error` populated. The adapter does
not throw those operational failures. Existing compatibility wrappers may raise
`CalledProcessError` when their historical `check=True` contract requires it.
This lets deploy/mode/token paths make explicit decisions while preserving the
existing deploy timeout/rollback meanings.

### 8.3 Provisioning boundary

Do not invent a portable service-definition schema in G4.

Existing `UnitSpec`, marker, diff, adopt, backup, and server/job-manager unit
renderers remain the Linux/systemd representation.

The orchestration boundary should be:

```text
CLI setup/mode
      |
      v
deployment/service orchestration
      |
      +--> ManagedServiceInspector / ManagedServiceController
      |
      +--> Linux unit provisioner
               |
               +--> units.py
               +--> server_unit.py
               +--> job_manager_unit.py
```

This is intentionally asymmetric: lifecycle semantics are generic; the only
definition renderer implemented in G4 is explicitly Linux/systemd.

### 8.4 Runtime-path contract

Extract host convention from `config.py`.

Conceptual shape:

```python
@dataclass(frozen=True, slots=True)
class RuntimePaths:
    binnacle_runtime_dir: Path
    jobs_socket: Path
```

G4 does not need a speculative provider object merely because another platform
may exist later. The Linux resolver is a pure function that accepts environment
and UID inputs for deterministic tests, and `deployment_platform.py` is the
single default-platform composition point that returns `RuntimePaths`.
A future platform can return the same value object.

Linux behavior remains exactly:

1. choose host base `XDG_RUNTIME_DIR` when set;
2. otherwise choose host base `/run/user/<uid>`;
3. set `binnacle_runtime_dir = host_base / "binnacle"`;
4. set `jobs_socket = binnacle_runtime_dir / "jobs.sock"`.

The provider does not own the durable job spool. The spool is intentionally
state, not runtime socket state.

No new external dependency is required.

## 9. Proposed implementation modules

Names are deliberately flat until G6 package convergence.

Preferred new modules:

```text
src/binnacle/service_log_contracts.py
src/binnacle/service_journal.py

src/binnacle/service_lifecycle_contracts.py
src/binnacle/service_systemd.py

src/binnacle/runtime_path_contracts.py
src/binnacle/runtime_paths_linux.py

src/binnacle/deployment_platform.py
```

`deployment_platform.py` is the explicit Linux default composition point,
analogous to G3's `job_platform.py`. It may expose factories such as:

```python
create_service_log_source()
create_service_inspector()
create_service_controller()
create_linux_provisioner()
create_runtime_paths()
```

The factory owns the default platform selection. Generic modules should not
instantiate Linux adapters themselves.

Compatibility facades may temporarily remain in:

- `logstats_io.py`;
- `doctor_common.py`;
- `units.py`;
- `cli.py`.

They should delegate rather than continue to execute platform commands once
their callers have migrated.

## 10. Atomic implementation plan

### G4.0 — Freeze and characterize the deployed Linux baseline

Input:

- exact base `f21f86055ebea4ae5fc14c4aa6aed6e19c3f3d1e`;
- runtime source equivalent to `01523d406732...`.

Work:

- preserve focused current-state test evidence;
- archive current setup/mode/doctor/stats help/output fixtures where they
  represent user-visible contracts;
- record exact systemd unit renderings for dev/prod server and jobs manager;
- record log acquisition argv behavior;
- record runtime-path behavior for XDG set/unset;
- record deploy quiet/restart/rollback behavior.

No production source changes.

Exit:

- current Linux behavior is independently reproducible without relying on the
  implementation plan's assumptions.

### G4.1 — Runtime-path extraction

This is the smallest independent lane and may run in parallel with G4.2.

Add:

- `RuntimePaths` value contract;
- pure Linux runtime-path resolver;
- focused tests for XDG set, XDG absent, UID fallback, exact
  `binnacle_runtime_dir`, and exact jobs socket.

Switch:

- `JobsSettings.socket_path` default construction to the platform composition
  function.

Preserve:

- exact default socket path;
- environment override behavior;
- config serialization/validation;
- job manager socket compatibility.

Do not touch:

- job spool location;
- job RPC;
- manager unit `RuntimeDirectory=binnacle`.

Rollback:

- revert the default-factory switch; no persisted data migration exists.

### G4.2 — Service-log source extraction

May run in parallel with G4.1 after G4.0.

Add:

- `ServiceLogSource` contract;
- `JournalServiceLogSource`;
- exact argv/error/window tests.

Switch in order:

1. `JournalServiceLogSource` implements semantic `read_window()` and its
   explicitly Linux-only `read_spec()` compatibility method;
2. `logstats_io.fetch_journal` becomes a compatibility facade over
   `read_spec()`. Stats, doctor, and mode keep using this Linux compatibility
   facade/injection path; they do **not** consume the semantic protocol for
   string time specifications;
3. deployment smoke's default environment receives the semantic
   `ServiceLogSource` and implements its existing `Env.journal` callback with
   `read_window()` rather than a second journalctl implementation.

Preserve:

- raw text;
- multiple-unit merge;
- current string `--since`/`--until` UX through the Linux compatibility
  facade only;
- semantic `ServiceLogSource` callers use epoch windows only;
- a future non-journald test double implementing only `read_window()` is valid
  and is never asked for `read_spec()`;
- epoch-bounded deployment windows through the Linux composition helper;
- error handling visible to stats/doctor;
- smoke quiet-window semantics.

Correct two characterized safety defects explicitly:

1. Current `logstats_io.fetch_journal()` raises `SystemExit` on journal failure
   while `doctor_jobs.server_busy_reasons()` catches `OSError`/
   `SubprocessError`. A failed journal read can therefore escape instead of
   becoming a conservative restart blocker.
2. Current `scripts/deploy_smoke.py::read_journal()` maps journalctl failure to
   `[]`, so `deploy_flow._wait_quiet()` can falsely conclude there were zero
   recent calls and mutate production without proving a quiet window.

The new source raises `ServiceLogError`, and every safety caller has an explicit
fail-closed mapping:

- `binnacle mode` quiet checking adds a blocker and does not restart;
- canonical deploy quiet polling records ALERT and stops **before** fast-forward
  or any service mutation;
- canonical deploy post-fast-forward code-load verification (`_await_config`)
  converts unreadable log evidence into a deterministic load failure rather than
  exception escape; the deploy enters its existing rollback path and never
  pushes;
- rollback code-load verification handles the same error independently; if the
  old code's config evidence cannot be read, rollback is reported `NOT CONFIRMED`
  and the final result remains ALERT rather than exception-escaping;
- live smoke records ALERT when its required log evidence is unreadable rather
  than treating it as an empty journal or propagating an exception;
- doctor reports WARN;
- `stats` retains command failure instead of silently returning an empty report.

These are reviewed correctness repairs, not hidden behavior changes.

Do not change parser code in `logstats*.py`.

Rollback:

- facade can be switched back to the old implementation without changing
  callers or data.

### G4.3 — Read-only managed-service inspection

Serial after shared lifecycle contracts settle.

Add:

- `ManagedServiceInspector` contract;
- `SystemdUserServices` read-only inspection implementation.

Migrate read paths first:

- CLI mode status;
- job-manager/server ownership safety checks that need state/main PID and the
  exact `BINNACLE_MANAGED_DEPLOYMENT=1` main-process marker;
- doctor state/restart-count/main-PID and service-PATH facts without
  reorganizing doctor groups;
- smoke startup/RSS measurement through semantic inspection capabilities.

`doctor.check_service_env()` must stop reading `/proc/<pid>/environ` directly
and consume `main_process_path()`, preserving its existing OK/WARN/FAIL text and
PATH resolution checks.

`doctor_jobs.server_uses_manager()` must stop reading `/proc/<pid>/environ`
directly. It consumes `main_process_has_environment()` through the injected
inspector. This is a restart-safety boundary, not G5 diagnostic reorganization.

Do not add an arbitrary-property escape hatch to generic code merely to make
migration easy. In particular, smoke must not learn `ControlGroup`; the Linux
inspector converts that mechanism into `rss_kb`. The smoke must not learn
`ExecMainStartTimestamp`; the inspector converts it into `started_at_epoch`.

Where doctor needs Linux-specific definition facts such as unit-file drift,
ExecStart, ExecStartPost or LoadError, keep those checks explicitly in the
Linux provisioning/diagnostic helper until G5 decides diagnostic ownership.

Exit:

- generic read-side orchestration uses semantic inspection capabilities;
- G4 has not reorganized doctor ownership or output.

### G4.4 — Linux provisioning containment

After G4.3 is green, establish the final owner of Linux definition/provisioning
operations before migrating generic restart control. This avoids a temporary
checkpoint where generic lifecycle code owns actions that the next step moves
back into Linux provisioning.

Keep the current systemd renderers and `UnitSpec` format, but make the explicit
Linux provisioner the only layer that knows:

- `~/.config/systemd/user`;
- systemd marker/definition files;
- unit write/backup;
- daemon-reload;
- enable-now;
- loginctl lingering/persistence enablement and inspection;
- ExecStart/ExecStartPost inspection.

Generic CLI setup/mode orchestration requests the Linux provisioner's
server/jobs definition plan/write operations and receives the same
plan/action/diff information it prints today. Mode's unit rewrite and
daemon-reload occur through this provisioner before G4.5 owns only the restart.

Preserve:

- exact unit text unless a separately reviewed correctness fix is required;
- marker format;
- dry-run text semantics;
- adopt refusal;
- backup behavior;
- current mode persistence;
- current setup restart hints;
- current boot/linger diagnostic wording.

The Linux adapter may reuse existing `units.py`, `server_unit.py`, and
`job_manager_unit.py`; do not duplicate their logic.

Rollback:

- revert the CLI/provisioner composition switch; unit bytes remain unchanged and
  no schema/data migration exists.

### G4.5 — Restart/control migration

After the provisioner has final ownership, migrate the remaining portable
service mutation through `ManagedServiceController.restart()` only:

- server restart in `binnacle mode`;
- active-service restart during token rotation, including the existing tunnel
  service name without changing ownership;
- canonical deploy restart and rollback restart paths.

Preserve exactly:

- quiet-window gating before restart;
- explicit `--force`;
- caller-specific restart timeout policy from the baseline:
  - `binnacle mode` passes `timeout=None`, preserving its current unbounded
    Python subprocess wait;
  - `binnacle token rotate` passes `timeout=None` for both server and tunnel,
    preserving its current unbounded Python subprocess waits;
  - canonical deploy forward restart passes its existing `restart_timeout`
    value (default 90 seconds);
  - rollback restart passes that same existing `restart_timeout` value;
- dev environment sync before dependency-driven restart;
- rollback restart behavior;
- stable manager non-restart rule in normal deploy.

Correct a second characterized lifecycle safety defect explicitly: current
`binnacle token rotate` ignores non-zero restart results and still prints
`restarted <unit>`. A direct fake-host characterization confirmed it returns
success after both restarts report failure. G4.5 must stop claiming success for
a failed restart, preserve the exact action detail, and return a failure status.

Preservation-first sequencing remains fixed: token rotation still examines the
server unit and then tunnel unit, attempts the restart of **every** unit that was
active even if an earlier restart fails, prints `restarted <unit>` only for
successful actions, records each failed action truthfully, and exits non-zero
after all active units have been attempted if any restart failed. It must not
abort after the first failure. This is the only token-rotation behavioral delta.
This correctness repair is reviewed separately from general CLI cleanup.

Every mutation preserves the caller's existing timeout policy and returns an
inspectable result. Canonical deploy/rollback restarts remain bounded by
`restart_timeout`; mode and token rotation intentionally remain `timeout=None`
in G4 because adding a new timeout would be an unreviewed UX/behavior change. No
method may silently convert a failed service-manager operation into success.

Rollback:

- compatibility wrappers can route restart back to the old systemctl path; no
  persisted data or service-definition bytes change in this step.

### G4.6 — Remove direct platform calls from generic paths

After callers have switched, prove the boundary.

Generic paths that should no longer **execute** direct
systemd/journal/runtime mechanisms include at least:

- `cli.py`;
- `config.py`;
- `doctor.py` for lifecycle/log acquisition;
- `doctor_common.py` for lifecycle primitives;
- `doctor_jobs.py` and `job_manager_doctor.py` for service inspection;
- `logstats_io.py` except a compatibility delegation;
- `scripts/deploy_flow.py`;
- `scripts/smoke_checks.py`.

`scripts/deploy_smoke.py` is the Linux default composition entry point for the
canonical deploy and may construct the Linux adapters, but it must not duplicate
raw `journalctl`/`systemctl` subprocess logic.

Allowed Linux implementation/provisioning modules contain the primitives.

The leakage gate must be AST/behavior based, not a raw text grep. User-facing
Linux hints and comments such as `journalctl --user ...` or
`systemctl --user ...` are intentionally preserved in G4 and must not fail the
gate. The gate looks for executable subprocess argv construction, direct
platform helper calls, and runtime-path construction in generic code.

Companion/weekly/migration scripts are classified explicitly. Do not call G4
failed merely because a G5-owned companion or an explicitly Linux maintenance
tool still uses systemctl/journalctl.

### G4.7 — Convergence, review, CI, deploy, live verification

Local convergence:

- all G4 focused tests;
- architecture/import checks;
- strict module-size gate;
- pre-commit;
- pre-push;
- managed full suite;
- coverage policy;
- Python 3.10-3.14 matrix;
- wheel artifact smoke;
- exact public MCP wire parity.

Before remote review/deploy, run an explicit CLI/operator parity gate against the
G4.0 baseline. Compare command help, normal output, exit codes, and representative
failure behavior for `setup`, `mode`, `doctor`, `stats`, and `token`. The two
reviewed safety corrections are the only expected deltas: unreadable service logs
must fail closed at restart/deploy/smoke gates, and token rotation must no longer
claim a failed restart succeeded. Existing uneven setup failure presentation is
otherwise preserved unless separately reviewed.

Then:

1. fresh independent ChatGPT source/design review;
2. exact-SHA CI;
3. canonical deployment;
4. live pytest;
5. full deploy smoke;
6. doctor verification;
7. real ChatGPT read-only MCP call;
8. truthful completion documentation.

G4 is not done when local tests pass.

## 11. Parallelization plan

Safe after G4.0:

```text
                    G4.0 baseline
                         |
             +-----------+-----------+
             |                       |
             v                       v
      G4.1 runtime paths       G4.2 service logs
             |                       |
             +-----------+-----------+
                         |
                         v
             G4.3 lifecycle reads
                         |
                         v
             G4.4 Linux provisioning
                         |
                         v
             G4.5 restart/control
                         |
                         v
             G4.6 boundary cleanup
                         |
                         v
             G4.7 convergence
```

G4.1 and G4.2 may use separate worktrees because they should not need the same
source files except the integration-owned platform factory.

Parallel-unsafe shared files:

- `src/binnacle/cli.py`;
- `src/binnacle/doctor.py`;
- `src/binnacle/doctor_common.py`;
- `src/binnacle/units.py`;
- `src/binnacle/deployment_platform.py`;
- `scripts/deploy_flow.py`;
- `scripts/deploy_smoke.py`;
- architecture/control documents.

One integrator owns those files.

## 12. Compatibility surface

The following are frozen unless an explicit reviewed finding proves a change is
required.

### 12.1 MCP/public server surface

No change to:

- tool names/order;
- schemas;
- annotations;
- visibility;
- instructions;
- errors;
- durable-job fields;
- job spool/RPC format.

### 12.2 CLI/operator surface

No change to:

- command names;
- option names/defaults;
- exit codes except where the reviewed token-rotation safety defect currently
  returns success after failed restarts;
- dry-run/adopt behavior;
- current dev/prod mode semantics;
- token rotation ordering and active-unit selection, except false restart success
  is corrected;
- stats analysis format;
- doctor OK/WARN/FAIL semantics.

### 12.3 Deployment safety

No change to:

- exact-SHA CI requirement;
- clean-master/fast-forward gate;
- 30-second quiet-window semantics;
- dev dependency sync;
- live-load verification;
- live smoke;
- atomic remote update;
- rollback behavior;
- stable jobs manager non-restart policy.

### 12.4 Linux host behavior

No change to:

- unit names;
- current unit bodies;
- user-unit ownership;
- `RuntimeDirectory=binnacle`;
- XDG runtime-dir preference;
- `/run/user/<uid>` fallback;
- token/config/spool locations.

## 13. Testing strategy

### 13.1 New focused contract tests

Service logs:

- one and multiple services;
- relative string window;
- semantic-protocol boundary test: a fake non-journald source implements only
  `read_window()` and canonical deploy/smoke never asks it for `read_spec()`;
- Linux compatibility boundary test: stats/doctor/mode string specifications
  reach `JournalServiceLogSource.read_spec()` only and never widen the semantic
  protocol;
- epoch window through the Linux composition helper;
- exact Linux epoch conversion parity: `since_epoch` becomes
  `--since @<int(since_epoch)>`; a bounded `until_epoch` becomes
  `--until @<int(until_epoch)+1>`; no `--until` is emitted for an unbounded
  window;
- boundary-event regression pins the current truncation and inclusive
  `until + 1 second` behavior so edge events are neither lost nor newly added;
- non-zero journalctl status;
- adapter timeout/launch failure maps to `ServiceLogError`;
- core compatibility composition preserves `command_timeout_s=None`;
- canonical deploy/smoke composition pins `command_timeout_s=60.0`;
- `ServiceLogError` mapping for CLI, doctor and restart safety;
- mode regression proving an unreadable log source conservatively blocks restart
  rather than escaping as `SystemExit`;
- canonical deploy pre-mutation regression: unreadable quiet-window journal =>
  ALERT before fast-forward, restart, push, or any other service mutation;
- canonical deploy forward-load regression: after fast-forward/restart,
  `ServiceLogError` from config-evidence polling becomes reload ALERT, performs
  the existing rollback, never pushes, and never exception-escapes;
- canonical deploy rollback-load regression: if config-evidence polling for the
  restored old code also raises `ServiceLogError`, final output is deterministic
  ALERT with rollback `NOT CONFIRMED`, no push occurs, and the exception does not
  escape;
- repeat the pre-mutation, forward-load, and rollback-load deploy regressions
  with an acquisition **timeout** (not only a non-zero/read error), proving the
  60-second adapter cap maps to deterministic ALERT/no-push/rollback behavior;
- live-smoke regression: unreadable required journal => report ALERT and exit 1
  without exception escape or empty-evidence success; exercise every smoke
  journal-read site so a later read cannot escape after the first ALERT;
- repeat every required live-smoke journal-read failure case with an acquisition
  timeout, proving it reports ALERT rather than hanging or treating timeout as
  empty evidence;
- stderr clipping/error contract;
- exact `-o cat --no-pager` behavior.

Runtime paths:

- XDG set;
- XDG absent;
- UID injection;
- exact `binnacle/jobs.sock` composition;
- no mutation of environment.

Managed-service inspection/control:

- preserve exact non-empty Linux state text, including failed/transitional
  states, with only empty/unusable state becoming `unknown`;
- main PID and restart count;
- smoke-only start epoch and RSS capabilities;
- main-process environment-marker query, including present, absent, unreadable
  environment, inactive service, and invalid/missing main PID parity;
- main-process PATH query, including unreadable environment parity for doctor;
- `doctor_jobs.server_uses_manager()` and `doctor.check_service_env()` no longer
  read `/proc` directly and preserve current safety/diagnostic behavior;
- restart success/failure;
- composition timeout-argument parity: mode uses `None`; token server then
  tunnel each use `None`; forward deploy and rollback deploy each receive the
  existing `restart_timeout` value (including current custom-timeout regression
  such as 77 seconds);
- restart timeout maps to return code 124 plus `timed_out=True` when a caller
  supplied a finite timeout;
- launch/OSError maps to return code 127 plus `launch_error`;
- result stdout/stderr preservation;
- no shell invocation;
- token-rotation regression: preserve server-then-tunnel order, attempt every
  active unit even after an earlier failure, print `restarted <unit>` only for
  successful restarts, report each failed action detail, and exit non-zero if
  any restart failed; exercise server-failure and tunnel-failure cases.

Provisioning:

- daemon reload and enable-now stay Linux provisioner operations;
- persistence inspection/enablement stays Linux/loginctl provisioning;
- all existing `test_units.py` and `test_setup_units.py` behavior;
- exact dev/prod server unit;
- exact jobs-manager unit;
- marker/adopt/backup semantics;
- current process/drift diagnostics.

### 13.2 Existing regression suites

At minimum preserve the current focused baseline families:

- `tests/unit/core/test_logstats_io.py`;
- `tests/unit/core/test_units.py`;
- `tests/unit/core/test_job_manager_unit.py`;
- `tests/integration/test_setup_units.py`;
- `tests/integration/test_cli.py`;
- `tests/system/test_doctor_coverage.py`;
- `tests/scripts/test_deploy_flow.py`;
- `tests/scripts/test_smoke_checks.py`.

The pre-design baseline is 120 passed for this set.

### 13.3 Architecture leakage gate

Add a deterministic AST/static test or extend the architecture checker so that
generic G4-owned paths cannot reintroduce:

- direct `systemctl`;
- direct `journalctl`;
- direct `loginctl`;
- literal `/run/user/`;
- `XDG_RUNTIME_DIR` host selection;
- direct managed-service `/proc/<pid>/environ` reads outside the Linux service
  adapter;
- generic smoke ownership of systemd `ControlGroup` or
  `ExecMainStartTimestamp` properties;
- generic smoke traversal of `/sys/fs/cgroup`;
- generic smoke `/proc/<pid>/status` RSS inspection;
- generic smoke `date -d` conversion of service start timestamps.

The allowlist must name Linux implementation modules explicitly. It must not
globally ban those commands because G5-owned companions and Linux adapters still
legitimately need them.

Add a dedicated smoke-boundary regression that inspects
`scripts/smoke_checks.py` and proves RSS/start-time measurement consumes only
`ManagedServiceInspector.rss_kb()` and `started_at_epoch()` plus the injected log
source. The generic smoke module must contain no executable ownership of
`ControlGroup`, `ExecMainStartTimestamp`, `/sys/fs/cgroup`,
`/proc/<pid>/status`, or `date -d`. Those mechanisms are allowlisted only in the
Linux service adapter.

## 14. Error and failure semantics

Platform extraction must not make failures less visible.

- Log acquisition failure remains distinguishable from an empty log.
- Service restart failure keeps return code and bounded stderr.
- Unknown/inactive service state remains explicit.
- Setup refuses unmanaged definitions exactly as today.
- A failed deployment still rolls back and verifies the old smoke.
- No adapter catches broad exceptions merely to present a portable facade.
- Service-log execution timeouts are Linux composition policy: core compatibility
  preserves no cap, while canonical deploy/smoke preserves the existing 60-second
  cap; timeout maps to `ServiceLogError`. Other timeouts remain owned by the
  caller/use case unless the contract explicitly specifies a cap.
- No lifecycle mutation occurs implicitly during object construction.

## 15. Rollback model

Each implementation checkpoint has a source-only rollback.

No G4 step changes a durable schema.

No G4 step requires migration of:

- job spool;
- job metadata;
- RPC protocol;
- cgroup identities;
- service names;
- token file;
- config file.

Unit files should remain byte-identical through the extraction. If a checkpoint
changes unit bytes unexpectedly, stop and review before deployment.

Because the Linux adapter initially reproduces existing behavior, rollback is
primarily reverting composition/caller switches.

## 16. FastMCP relationship

G4 does not need a new FastMCP mechanism.

Service management, journald, runtime directories, and deployment orchestration
are host/product concerns, not FastMCP Providers, Transforms, Middleware,
Depends, lifespan, ServerExtensions, or Tasks.

The MCP server remains composed exactly as G2/G3 left it.

Any proposal to represent a platform adapter as a FastMCP Provider or plugin is
out of scope and requires design review.

## 17. Interaction with G5 and G6

G4 intentionally leaves two later responsibilities alone.

G5 will decide:

- doctor ownership reorganization;
- watchdog/tunnel reverse-dependency cleanup;
- public operational custom HTTP routes;
- companion adoption of the G4 platform contracts where useful.

G6 will decide:

- final package moves such as `platform/linux`;
- removal of temporary compatibility facades;
- stronger final import/AST architecture rules;
- full package convergence.

G4 should create stable seams that make those later steps mechanical rather than
mixing them into this group.

## 18. Entry criteria

Implementation may begin only after:

1. this detailed design is complete;
2. current-code/platform leakage inventory is reviewed;
3. UX compatibility decision is accepted;
4. a fresh independent ChatGPT review finds no blocking design issue;
5. the design baseline SHA is frozen;
6. ownership/parallel lanes are recorded.

## 19. Exit criteria

G4 is done only when all of the following are true:

- service-log acquisition is behind the contract in core and canonical deploy;
- managed-service inspection/control and Linux provisioning are behind the
  platform boundary for generic CLI/deploy orchestration;
- runtime socket convention is produced by the runtime-path value/composition
  boundary;
- generic G4-owned paths pass the platform leakage gate;
- current Linux UX and deployment safety are preserved;
- current systemd unit behavior is preserved;
- focused, full, coverage, matrix, packaging, architecture and public-wire gates
  are green;
- independent review passes;
- exact-SHA CI passes;
- canonical deployment and live smoke pass;
- real ChatGPT read-only verification passes;
- completion docs truthfully mark G4 done;
- G5/G6 work has not been silently included.

## 20. Current-code, UX and contract review — ChatGPT Chat Mode

First review completed against the deployed G3 code on 2026-10-06.

### 20.1 Findings and resolutions

1. **Service-log failure semantics were inconsistent.** `fetch_journal()` exits
   with `SystemExit`, while the quiet-gate path catches different exception
   classes. A direct characterization confirmed the `SystemExit` escapes.
   **Resolution:** add `ServiceLogError`; map it to CLI failure, doctor WARN,
   and conservative busy/restart refusal respectively.

2. **The first lifecycle protocol mixed mutation and inspection and was still
   incomplete.** Current doctor/smoke need main PID, restart count, start time,
   memory measurement, and boot-persistence state.
   **Resolution:** split `ManagedServiceInspector` from
   `ManagedServiceController`; one `SystemdUserServices` object implements both.

3. **An arbitrary systemd-property API would leak the mechanism through the
   contract.** It would merely rename `systemctl show`.
   **Resolution:** prohibit a generic property bag. Add semantic fields only
   when a current generic caller demonstrably needs them.

4. **Smoke currently exposes `ControlGroup` and `ExecMainStartTimestamp`.**
   Those are systemd/Linux mechanisms, not deploy-domain concepts.
   **Resolution:** the Linux inspector reports `rss_kb` and
   `started_at_epoch`; smoke consumes the semantic values.

5. **The service-log time grammar cannot honestly be made portable without a
   user-visible change.** `stats --since` intentionally accepts journalctl
   time syntax today.
   **Resolution:** preserve string time specs in the compatibility contract.
   Epoch conversion for deploy lives in the Linux composition helper. Do not
   claim that the existing CLI grammar is cross-platform.

6. **`scripts/smoke_checks.py::Env` is already a valuable DI/test boundary.**
   Replacing it with import-time globals would make the refactor worse.
   **Resolution:** inject platform log/service capabilities through the default
   `Env`; keep `deploy_flow.py` and smoke logic testable with fakes.

7. **Core token rotation currently knows the tunnel unit name.** That is an
   ownership smell, but changing ownership is G5.
   **Resolution:** G4 may route the existing restart through the service
   controller, but must not move or redesign the tunnel responsibility.

8. **`units.py` mixes pure unit-file mechanics with live systemd diagnostic
   helpers.** Moving all diagnostics now would overlap G5.
   **Resolution:** retain compatibility helpers and Linux unit representation;
   only redirect execution primitives needed by G4. G5 owns final diagnostic
   placement.

9. **Raw text leakage scanning would produce false positives.** Current help,
   hints, templates and comments intentionally mention systemctl/journalctl.
   **Resolution:** use AST/behavioral leakage checks, not grep-based bans.

10. **Current setup failure presentation is uneven.** Some setup actions use
    `check=True` and can surface `CalledProcessError`, while mode has explicit
    failure text.
    **Resolution:** record as a baseline UX rough edge. Do not silently redesign
    CLI failure presentation in G4 unless the lifecycle switch requires a
    narrowly reviewed mapping.

### 20.2 Explicit scope classification

| Current direct platform user | G4 disposition |
| --- | --- |
| `config.py` runtime socket default | migrate in G4.1 |
| `logstats_io.py` | compatibility facade over G4.2 source |
| `doctor.py` log acquisition / service execution | delegate mechanism; keep diagnostic UX/order |
| `doctor_common.py` service primitives | compatibility facade over inspector/controller |
| `doctor_jobs.py` service inspection + quiet log read | migrate mechanism |
| `job_manager_doctor.py` service inspection | migrate mechanism |
| `cli.py` systemctl/loginctl actions | migrate mechanism; preserve UX |
| `deploy_flow.py` restart | migrate to controller |
| `deploy_smoke.py` journal composition | construct Linux log adapter; no duplicate subprocess |
| `smoke_checks.py` service RSS/start time | migrate to semantic inspection |
| `units.py`, `server_unit.py`, `job_manager_unit.py` | retain as Linux provisioning implementation |
| `watchdog*`, `tunnel*`, `ops/watchdog/*` | G5-owned; compatibility imports only in G4 |
| `watchlog.py` | G5 companion |
| `weekly_host.py`, `weekly_scope.py` | explicitly Linux quality/host tooling; not required for G4 |
| `migrate_resource_history_v2.py` | historical Linux migration tool; not required for G4 |
| `chat_scheduling_runtime.py` | experiment/harness; not canonical deployment path |

### 20.3 Contract feasibility probes

Read-only prototypes were run outside the repository before implementation.
They did not change services or source.

- A frozen 30-second journal window read through the proposed Linux argv shape
  was byte-identical to current `logstats_io.fetch_journal()` (8,068 bytes in
  the sampled window).
- Current and prototype service state agreed: active server, PID 3051321, zero
  crash restarts at the sample time.
- Prototype RSS calculation preserved the current smoke algorithm exactly:
  187,888 kB in both paths for the sampled service state.
- Prototype main-process start epoch matched the current smoke conversion
  exactly: 1791240123.0 in both paths.
- The host reports user-service persistence enabled.
- Runtime-path characterization confirmed `/tmp/g4-xdg/binnacle/jobs.sock`
  when `XDG_RUNTIME_DIR=/tmp/g4-xdg`, and
  `/run/user/4242/binnacle/jobs.sock` for an injected UID 4242 with XDG absent.

These probes support the semantic contract without proving implementation. The
implementation still needs focused tests and normal convergence gates.

### 20.4 UX review conclusion

The operator-facing workflow should not change in G4.

The current UX was exercised directly on the production checkout:

- root command help;
- `setup --help`;
- `mode --help`;
- `doctor --help`;
- `stats --help`;
- `mode status`;
- `setup --dev ... --dry-run`;
- local `doctor --no-probe`.

The current design preserves the strengths that matter: explicit dry-run,
adopt/refuse semantics, backups, stable unit names, quiet restart gating,
doctor severity/hints, CI-gated deploy, live smoke and rollback.

Two current doctor warnings on the host are not G4 design blockers: the stable
job manager reports runtime source `01523d4` while the checkout is the later
doc-only `f21f860`, and the recent MCP journal contains one retained error line.
G3 already verified that the doc-only commit has identical runtime source.

G4 is therefore an **internal platform-boundary refactor with intentionally
unchanged Linux operator UX**, except for two reviewed safety corrections:
unreadable service logs must no longer make restart/deploy safety gates fail
open, and token rotation must no longer claim failed restarts succeeded. A
genuinely portable CLI time grammar and diagnostic ownership redesign are future
work, not hidden G4 scope.

## 21. Independent design review R1 and correction record

A fresh ChatGPT Chat Mode reviewer, using only a self-contained 18-file packet,
returned `changes_required` in conversation
`6ac43db7-b744-83ec-b115-26793cf68079`. Current-code/scope passed; UX, contract
quality and implementation/validation had material findings. No local Codex or
repository tool was available to that reviewer.

The review produced eight material corrections, all incorporated before a
second review:

1. **Provisioning ownership:** generic control now owns restart only. Linux
   provisioning owns daemon-reload, enable-now, unit files and loginctl
   persistence.
2. **Log-time boundary:** the portable contract now uses epoch windows;
   journalctl-style strings are explicitly a Linux compatibility edge for the
   existing CLI.
3. **Service state parity:** Linux state text is preserved, including failure
   and transitional states; `unknown` is only an empty/unusable fallback.
4. **Runtime path invariant:** `binnacle_runtime_dir` is exactly
   `host_base / "binnacle"`; the jobs socket is exactly its `jobs.sock`.
5. **Journal failure safety:** both the mode quiet gate's escaping `SystemExit`
   and canonical deploy's fail-open empty-list behavior are explicit G4.2 safety
   repairs. Mode blocks, deploy ALERTs before mutation, and smoke ALERTs.
6. **Service action failures:** timeout and launch/OSError mappings are explicit
   and preserve action details.
7. **Checkpoint ownership:** Linux provisioning is established in G4.4 before
   G4.5 migrates generic restart control, eliminating the mixed ownership
   checkpoint.
8. **Operator parity:** G4.7 now requires an explicit baseline-vs-final CLI
   parity gate, with only the reviewed safety corrections allowed to differ.

Current-code review also characterized a related restart defect not in the R1
packet: current `binnacle token rotate` ignores non-zero restart returns and
prints success. G4.5 treats this as the second explicit safety correction rather
than preserving false-success behavior.

## 22. Frozen contract decisions for independent re-review

The corrected design freezes these decisions unless the second independent
review finds a concrete blocker:

1. Use separate `ManagedServiceInspector` and `ManagedServiceController`; the
   controller's only generic mutation is `restart`.
2. Use semantic epoch windows for the platform-neutral `ServiceLogSource`; keep
   journalctl-compatible string windows only on the Linux CLI compatibility
   path.
3. Keep unit provisioning as explicit Linux adapter functions/data for G4. Do
   not invent a generic provisioning protocol before a second platform exists.
4. Migrate only current core/canonical deploy paths in G4. Historical migration,
   weekly host tooling, scheduling experiments and G5 companions stay explicitly
   classified rather than being swept into this refactor.
5. Keep `doctor_common.py` compatibility wrappers through G5, but make their
   platform execution delegate to the new Linux inspection/control path where
   G4 owns the mechanism. Keep `Check` and diagnostic rendering stable.
6. Introduce the leakage rule as a focused G4 AST/behavior contract test. G6 may
   merge the proven rule into the global architecture checker during package
   convergence.
7. Use `RuntimePaths` as a value object and a pure Linux resolver; no speculative
   provider protocol and no new path dependency.
8. Preserve existing CLI and deployment UX except for the two explicit safety
   repairs: fail-closed unreadable logs and truthful token-rotation restart
   failure.

A fresh independent ChatGPT re-review must challenge, rather than assume, these
decisions. It should verify that every R1 finding is actually closed and that no
new G5/G6 scope creep or mixed checkpoint was introduced while correcting them.

## 23. Independent design review R2 and correction record

A second fresh ChatGPT Chat Mode reviewer, again restricted to a self-contained
packet and no tools, returned `changes_required` in conversation
`6ac440cd-94d4-83ec-88d2-c1817f5dcc12`. It marked all eight R1 findings closed
and identified two remaining important ambiguities plus one minor parity gap.

Corrections applied before R3:

1. **Managed-service process environment seam:**
   `ManagedServiceInspector.main_process_has_environment()` is the narrow
   capability for the current `BINNACLE_MANAGED_DEPLOYMENT=1` ownership marker,
   and `main_process_path()` covers the only other current generic consumer.
   `doctor_jobs.server_uses_manager()` and `doctor.check_service_env()` must stop
   reading `/proc/<pid>/environ` directly. The G4 leakage gate now covers direct
   managed-service procfs environment reads in generic code.
2. **Named fail-closed regressions:** G4.2 now explicitly requires canonical
   deploy journal failure to ALERT before any mutation and live-smoke journal
   failure to report ALERT/exit 1 without exception escape or empty-evidence
   success, across every required smoke journal read.
3. **Token-rotation sequence:** a failed restart no longer prints success or
   yields exit 0, but the command still attempts every active unit in the
   existing server-then-tunnel order before returning failure.

No new product scope is introduced by these corrections. The process-environment
capability exists only to move an already-required Linux safety mechanism behind
the platform seam; it is not a generic environment property bag.

## 24. Independent design review R3 and correction record

A third fresh ChatGPT Chat Mode reviewer returned `changes_required` in
conversation `6ac442be-6dfc-83ec-8b77-ddc1fa0bb9dd`. It marked current-code
scope, UX compatibility, and contract quality as pass, with only validation
specification completeness remaining. It explicitly confirmed the R2 closures
for the process-environment seam, deploy/smoke journal-failure regressions, and
token-rotation sequence.

Two remaining corrections were applied before R4:

1. **Token rotation regression is now mandatory in the concrete test plan.**
   G4.5/G4.7 must prove server-then-tunnel order, all-active-unit attempts after
   an earlier failure, truthful success/failure output, retained action detail,
   and non-zero exit after any restart failure. Server-failure and tunnel-failure
   cases are explicitly named.
2. **The architecture leakage gate now names managed-service procfs environment
   reads explicitly.** Generic G4 code may not reintroduce direct
   `/proc/<pid>/environ` access; only the Linux service adapter owns that
   mechanism.

No contract or UX redesign was required by R3. The remaining step before design
acceptance is a fresh R4 review of the corrected packet.

## 25. Independent design review R4 and correction record

A fourth fresh ChatGPT Chat Mode reviewer returned `changes_required`. It marked
current-code scope and UX compatibility as pass, closed R1 and R3, and identified
one remaining deploy-flow validation gap: post-mutation config-evidence polling
uses the same injected journal source as the quiet gate.

The correction is now explicit in both behavior and tests:

1. Forward `_await_config` journal failure becomes a deterministic reload ALERT,
   enters the existing rollback path, never pushes, and never exception-escapes.
2. Rollback `_await_config` journal failure is handled independently; rollback is
   reported `NOT CONFIRMED`, the final result remains ALERT, and no exception
   escapes.
3. Focused regressions are mandatory for both forward-load and rollback-load
   journal failure, in addition to the already specified pre-mutation quiet-gate
   and live-smoke journal-failure tests.

This closes the last R4 finding without changing contracts, UX scope, or
checkpoint ownership. A fresh R5 review is required before the design can move
from `designing` to `ready`.

## 26. Independent design review R5 and correction record

A fifth fresh ChatGPT Chat Mode reviewer returned `changes_required`, while
marking R1-R4 closed and the scope/UX/contracts as pass. The only remaining
finding was an architecture-validation completeness gap around the current
smoke implementation.

The design now makes that gate explicit:

1. Generic smoke code may not own systemd `ControlGroup` or
   `ExecMainStartTimestamp` inspection.
2. Generic smoke code may not traverse `/sys/fs/cgroup`, read
   `/proc/<pid>/status` for RSS, or invoke `date -d` to convert service start
   time.
3. A dedicated smoke-boundary regression must prove
   `scripts/smoke_checks.py` consumes only semantic
   `ManagedServiceInspector.rss_kb()` / `started_at_epoch()` capabilities plus
   the injected log source for those measurements.
4. The Linux service adapter is the only G4 allowlisted owner of those host
   mechanisms.

No contract or UX change was needed. A fresh R6 review is required before
marking the design ready.

## 27. Independent design review R6 and correction record

A sixth fresh ChatGPT Chat Mode reviewer marked R1-R5 closed and found one final
contract/validation ambiguity: sharing the journal adapter could accidentally
lose canonical deploy's existing 60-second per-read timeout or impose that cap
on core stats/doctor without review.

The timeout policy is now frozen explicitly:

1. `ServiceLogSource` remains semantic and carries no execution-timeout
   parameter.
2. Linux `JournalServiceLogSource` is constructed with
   `command_timeout_s: float | None`.
3. Core stats/doctor/mode compatibility uses `None`, preserving the current
   unbounded `logstats_io` behavior in G4.
4. Canonical deploy/smoke uses exactly 60 seconds per journal acquisition,
   preserving current `deploy_smoke.read_journal()` behavior.
5. `TimeoutExpired`, launch/OSError, and non-zero completion all map to
   `ServiceLogError`.
6. Mandatory timeout-specific regressions cover pre-mutation deploy quiet,
   forward `_await_config`, rollback `_await_config`, and every required live
   smoke journal read, proving deterministic ALERT/no-push/rollback behavior
   rather than hang or empty evidence.

No public API, CLI grammar, or cross-platform abstraction was added. A fresh R7
review is required before design acceptance.

## 28. Independent design review R7 and correction record

A seventh fresh ChatGPT Chat Mode reviewer marked R2-R6 closed and found three
remaining specification ambiguities. All three are now resolved before R8:

1. **Semantic-vs-compatibility caller boundary:** stats/doctor/mode string-time
   behavior stays on the Linux-only `fetch_journal()` / `read_spec()` facade.
   The semantic `ServiceLogSource` is consumed only through epoch
   `read_window()`. A future non-journald source never needs `read_spec()`.
2. **Restart timeout ownership:** mode and token rotation explicitly pass
   `timeout=None`, preserving their current unbounded Python waits. Forward and
   rollback deploy restarts pass the existing finite `restart_timeout` (default
   90 seconds). The incorrect blanket claim that every mutation is bounded has
   been removed.
3. **Epoch-window parity:** Linux `read_window()` freezes the current conversion
   exactly: `--since @int(since_epoch)` and, when bounded,
   `--until @int(until_epoch)+1`. Exact argv and boundary-event regressions are
   mandatory.

Focused composition tests also pin the timeout argument for mode, token, forward
deploy, and rollback deploy. A fresh R8 review is required before design
acceptance.

## 29. Independent design review R8 — approved

A fresh ChatGPT Chat Mode reviewer independently approved the current G4 design
in conversation `6ac45f7a-3a48-83ec-bf40-32bb6e4d9747` with all four review
cells passing and R1-R7 marked closed.

Verdict: `approve_design`.

The reviewer reported one non-blocking minor ambiguity: the design said exact
journal argv parity while prose examples used an option order different from one
of the current callers. The design now explicitly freezes each baseline caller's
literal journalctl option ordering while keeping that ordering out of the
portable `ServiceLogSource` contract. No behavior, public surface, or scope was
changed by this clarification.

With R8 approval, all G4 design entry criteria are satisfied. Implementation may
proceed from the frozen deployed G3 baseline subject to the atomic G4.0-G4.7
plan and the validation/rollback gates in this document.
