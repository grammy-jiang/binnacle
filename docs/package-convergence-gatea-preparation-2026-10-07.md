# G6 package convergence + Gate A preparation — 2026-10-07

Status: **preparation only; no package relocation is authorized yet**.

Baseline: G4 source baseline `fd05b279e324235d0cf6eeddea86935de60ec1c1`.
Later G4 candidates through `c954701ed6691f4749274ea8d7ffc0ce3ec9eb08`
change validation tests only, so this ownership inventory remains source-current pending
the mandatory post-deploy drift check.
This branch exists to shorten future calendar time by preparing ownership maps, static
gate targets and a Gate A report harness. It must not move production modules until G5
has proven the final ownership boundaries.

## 1. Current baseline

Current G4-candidate evidence used by this preparation:

- 121 production modules;
- architecture checker: 0 forbidden reverse dependencies;
- Import Linter: 15 contracts kept;
- composition/server focused baseline: 40 passed;
- public product domains remain Files, Search and Commands;
- G3/G4 platform contracts already exist at top level.

This preparation does not claim Gate A. Companion isolation is still incomplete.

## 2. Target ownership manifest

This is a relocation **manifest**, not a move order.

### 2.1 Root composition

Stay root-owned:

- `server.py`.

### 2.2 MCP-facing shared framework glue

Target `mcp/`:

- `identity.py`;
- `logging_middleware.py`;
- `visibility.py`;
- `callctx.py`;
- `tool_order.py`.

No generic Binnacle MCP framework may be introduced during relocation.

### 2.3 Files feature

Target `features/files/`:

- `files_server.py`;
- `tools/read_file.py`;
- `tools/list_files.py`;
- `tools/edit_file.py`;
- `tools/write_file.py`;
- `paths.py`;
- `textio.py`.

### 2.4 Search feature

Target `features/search/`:

- `search_server.py`;
- `tools/search_text.py`;
- all `search_text_*.py`.

### 2.5 Commands feature

Target `features/commands/`:

- `commands_server.py`;
- `tools/run_command.py`;
- `tools/job_status.py`;
- `tools/stop_job.py`;
- `command_contracts.py`;
- `command_execution.py`;
- `command_status.py`;
- `command_backend.py`;
- durable-job modules `jobs.py`, `job_*.py`;
- `run_command_telemetry.py`;
- `run_command_evidence.py`.

The exact home of Linux process/cgroup adapters is excluded from this feature and
belongs under platform.

### 2.6 Platform contracts

Target `platform/contracts/`:

- `process_contracts.py`;
- `resource_contracts.py`;
- `service_log_contracts.py`;
- `service_lifecycle_contracts.py`;
- `runtime_path_contracts.py`.

### 2.7 Linux platform adapters

Target `platform/linux/`:

- `job_process.py`;
- `job_cgroup.py`;
- `service_journal.py`;
- `service_systemd.py`;
- `service_provisioning_linux.py`;
- `service_unit_linux.py`;
- `runtime_paths_linux.py`.

Composition modules such as `deployment_platform.py` are classified separately until
G5 confirms their final ownership.

### 2.8 Diagnostics / observability / deployment

Candidate target ownership:

- diagnostics:
  `doctor.py`, `doctor_common.py`, `doctor_contracts.py`,
  `doctor_connectivity.py`, `doctor_jobs.py`, `doctor_provenance.py`,
  `job_manager_doctor.py`;
- observability:
  `logstats.py`, all `logstats_*.py`, `token_telemetry.py`, plus the
  G5 system-resource-history contract/composition seam;
- Linux observability adapter:
  current `webminstats.py`, if G5's preserved-`--system-resources` decision is
  approved, moves behind the neutral observability contract rather than under watchdog
  policy;
- deployment:
  `deployment_platform.py`, `units.py`, `server_unit.py`,
  `job_manager_unit.py`.

G5 may still refine the exact diagnostics helper split. Do not move these before the
deployed-G4 drift check and approved G5 design settle the boundaries.

### 2.9 Tunnel companion

Target `companions/tunnel/`:

- `tunnel_cli.py`;
- `tunnel_doctor.py`;
- `tunnel_unit.py`.

### 2.10 Watchdog companion

Target `companions/watchdog/`:

- `watchdog.py`;
- `watchdog_cli.py`;
- `watchdog_doctor.py`;
- `watchdog_config.py`;
- `watchdog_unit.py`;
- `watchlog.py`;
- `ops/watchdog/*`;
- `uplink.py`.

The current G5 design direction no longer treats `webminstats.py` as watchdog policy;
it is tracked as a Linux observability adapter pending independent G5 approval.

### 2.11 Application shell / cross-cutting modules

Stay top-level until the final import graph proves a better home:

- `__init__.py`;
- `cli.py`;
- `config.py`;
- `errors.py`;
- `provenance.py`.

These are not an excuse for reverse dependencies. G6 may split narrow public contracts
out of them, but must not create an umbrella `common` package.

### 2.12 Manifest coverage rule

Before the first relocation, every `src/binnacle/**/*.py` file must be in exactly one
of three states:

1. assigned to one target ownership group above;
2. explicitly retained as a temporary compatibility facade in section 3; or
3. explicitly deferred because G5 still owns the classification decision.

The preparation harness should report unclassified and multiply-classified modules.
A move is blocked while either set is non-empty. Package `__init__.py` files are
classified with their package and are never counted as independent architecture layers.

## 3. Known compatibility facades to revisit in G6

`doctor_common.py` is also a current G4-backed compatibility facade. After G5,
refresh this list for any retained `doctor.py` or tunnel-helper aliases.

Do not delete these during preparation:

- `jobs.py` storage/lifecycle compatibility helpers;
- `watchdog.py` compatibility facade over `ops/watchdog`;
- `logstats.py` compatibility re-exports;
- `logstats_io.py` Linux compatibility IO;
- `service_journal.py::read_spec` compatibility path;
- `service_unit_linux.py` compatibility diagnostics;
- `units.py` compatibility diagnostics;
- `tools/search_text.py` subprocess compatibility seam.

G6 should remove only facades proven obsolete after all internal callers are migrated.
Public CLI/MCP compatibility must not be casually broken by directory cleanup.

The preparation harness pins this exact facade inventory and requires every listed
facade to exist and belong to exactly one ownership group before relocation starts.
This is a preparation PASS only; it does not mean any facade is removable. Actual
removal still requires caller migration plus focused compatibility evidence in G6.

## 4. Proposed relocation order after G5

Relocation should be serialized by dependency direction:

1. platform contracts;
2. Linux platform adapters;
3. Files feature;
4. Search feature;
5. Commands feature;
6. MCP middleware/identity glue;
7. diagnostics / observability / deployment;
8. tunnel companion;
9. watchdog companion;
10. compatibility-facade removal;
11. final import normalization and architecture rule tightening.

Each move must preserve an import-compatible transitional path until its callers are
updated and focused tests are green. Do not combine several ownership moves into one
unreviewable commit.

## 5. Static architecture targets

Final G6 gates should mechanically enforce:

- application/domain services do not import FastMCP;
- platform adapters do not import FastMCP;
- features depend on platform contracts, not Linux adapters;
- server/features/platform/diagnostics-core do not import companions;
- watchdog/tunnel may consume explicit public server contracts;
- Files/Search/Commands remain independent except deliberate shared contracts;
- root server is not a dependency of package internals;
- Linux-only commands/paths stay in platform/Linux or companion implementation.

Current Import Linter rules are a baseline, not the final rule set.

## 6. Gate A preparation harness

`scripts/gate_a_report.py` is introduced on this preparation branch as a report-only
harness. It is intentionally not wired into CI yet.

It distinguishes:

- mechanically checkable repository facts;
- known current failures that G5/G6 must close;
- external/runtime gates that cannot be inferred from source.

Default mode prints JSON and exits successfully so it can be used during preparation.
`--strict` exits non-zero while any Gate A item is FAIL or PENDING.

The final Gate A must run against the exact final G6 SHA and must bind runtime/deploy
evidence to that SHA. This script alone is never sufficient proof.

## 7. Work that may proceed before G5 completion

Safe now:

- keep this ownership manifest current;
- build generic static-report logic;
- identify compatibility facades;
- prepare final Import Linter/AST target rules;
- prepare result/evidence schema for Gate A;
- keep public MCP wire baselines easy to replay.

Unsafe now:

- moving production modules;
- changing import paths in production;
- deleting compatibility facades;
- claiming final package ownership for G5-sensitive diagnostics/Webmin/uplink;
- marking runtime/deployment Gate A cells green from static evidence.

## 8. Gate A final evidence model

Every Gate A cell should ultimately record:

- exact candidate SHA;
- check id;
- status: PASS / FAIL / PENDING;
- evidence type: static / test / CI / deploy / live / external client;
- exact command or evidence artifact;
- timestamp;
- optional review reference.

The preparation harness verifies a clean index/worktree, including untracked files,
and the same HEAD before and after collection. Otherwise its source-binding cell
fails and the candidate field is null; `--strict` cannot pass. A clean collection
binds every emitted cell to the same exact Git SHA and
UTC observation timestamp, in addition to the report-level binding. This prevents a
future collector from accidentally combining static results from one source snapshot
with runtime evidence from another. Command/artifact identifiers and review references
remain deliberately absent until the corresponding execution/review collectors exist;
preparation must not fabricate them.

The final acceptance report is generated only after G6 convergence and the production
deployment/live/client gates all bind to the same reviewed SHA.

## 9. Test execution cadence

G6/Gate A must preserve all final quality gates while avoiding repeated broad
runs during package movement.

For each relocation or facade-removal step, run only focused import/module tests
and the smallest relevant architecture checks. If a test fails, rerun the exact
failure and nearest affected subsystem after repair.

The machine farm, full managed suite, coverage policy, complete Python matrix,
packaging smoke and all-files convergence are reserved for the final exact G6
candidate. Run them once. If independent review or CI changes production code,
repair with focused tests and then perform one fresh final convergence for the new
SHA before Gate A.

An unchanged SHA does not justify repeating an already-green broad gate.
