# G6 package convergence + Gate A preparation — 2026-10-07

Status: **G5 drift-check complete; G6 package-ownership re-review pending before relocation**.

Baseline: deployed G5 completion `8218567f3af8c2157530ac5aa4af3bd4e99cc61b`.
Its production-source bytes are identical to reviewed/runtime candidate
`dd10ef0c77e87f1c8807c652e2d07188d9add6d3`; the completion commit changes only
the G5 design/master documentation. This branch was rebased onto that exact deployed
completion before the G6 drift check. The ownership manifest now includes every G5
addition exactly once. Production relocation remains blocked only until the required
fresh package-ownership review confirms this post-G5 manifest.

## 1. Current baseline

Current deployed-G5 evidence used by this preparation:

- 127 production modules, all singly classified by the G6 manifest;
- the G5 exact candidate already passed its final architecture/import convergence;
- all eight previously exposed G5 companion/ownership gaps now report PASS;
- public product domains remain Files, Search and Commands;
- G3/G4 platform contracts remain the platform boundary baseline;
- G5 runtime/deploy/client evidence remains external evidence, not a static inference.

This preparation does not claim Gate A. Package convergence and the final external
acceptance cells remain pending G6 implementation.

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

`paths.py` is the deliberate shared path-guard contract used by Files, Search, and
Commands. During the ordered relocation its implementation moves with Files while a
thin top-level `binnacle.paths` compatibility facade remains until the Search and
Commands waves migrate their callers. The final facade-removal step may delete that
alias only after those callers and architecture rules point at the owned contract.

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
- durable-job modules `jobs.py`, `job_client.py`, `job_manager.py`, `job_output.py`,
  `job_owner.py`, `job_resource_history.py`, and `job_store.py`;
- `run_command_telemetry.py`;
- `run_command_evidence.py`.

Linux process/cgroup adapters and the explicit default-platform composition point are
excluded from this feature and belong under platform.

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
- `service_unit_linux.py` (move together with the deployment/unit caller migration);
- `runtime_paths_linux.py`.

`service_unit_linux.py` is intentionally the one transitional exception during the
earlier Linux-adapter checkpoint: moving it before `units.py` creates a real
`units -> platform -> service_provisioning_linux -> units` package cycle. Keep its
top-level compatibility implementation until the deployment/unit ownership checkpoint,
then move it atomically with that caller. The Linux adapter package contains mechanics,
not default-selection policy.

### 2.7.1 Platform default composition

Target `platform/` (outside `platform/linux/`):

- `job_platform.py`;
- `deployment_platform.py`.

These are the two narrow explicit Linux-default composition points established by G3/G4.
They may construct Linux adapters lazily but are not Commands or deployment feature
implementation. Domain modules may consume these explicit factories while remaining
decoupled from concrete Linux adapter modules.

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
  current `webminstats.py` moves behind the deployed neutral observability contract
  rather than under watchdog policy;
- deployment:
  `units.py`, `server_unit.py`, `job_manager_unit.py`.

G5 has settled the diagnostics helper split. The G6 package-ownership re-review is the
remaining pre-relocation boundary for these modules.

### 2.8.1 G5 deployed additions

The deployed G5 runtime candidate `dd10ef0c77e87f1c8807c652e2d07188d9add6d3`
adds six production modules relative to G4 `b074068`. The post-deploy G6 drift check
classifies these modules **exactly once** before any package relocation:

| G5 addition | Intended G6 owner | Constraint |
| --- | --- | --- |
| `doctor_io.py` | diagnostics | Neutral bounded file-tail reader; no companion imports |
| `doctor_render.py` | diagnostics | Shared `Check` rendering, not a core aggregate import |
| `system_resource_contracts.py` | observability | `SystemResourceHistory` protocol; no Linux adapter import |
| `system_resource_history.py` | observability | Lazy optional adapter composition, preserving CLI UX |
| `tunnel_log.py` | tunnel | Narrow public tunnel-log facts used by watchdog |
| `watchdog_connectivity.py` | watchdog | Uplink reliability diagnostics owned by watchdog |

The deployed source snapshot contains **127** production modules. The harness does not
hard-code 127 as an acceptance target: it enumerates actual files and fails on every
unclassified, duplicate or stale manifest entry. The exact deployed G5 SHA is now the
branch base, the six additions are classified, the compatibility-facade inventory is
intact, and the focused manifest/source tests are the re-review evidence. The optional
resource-history seam is an observability boundary, not permission to move Webmin
beneath watchdog.

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
- `paths.py` temporary shared path-guard alias during Files/Search/Commands relocation;
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
3. platform default-composition points;
4. Files feature;
5. Search feature;
6. Commands feature;
7. MCP middleware/identity glue;
8. diagnostics / observability / deployment;
9. tunnel companion;
10. watchdog companion;
11. compatibility-facade removal;
12. final import normalization and architecture rule tightening.

Each move must preserve an import-compatible transitional path until its callers are
updated and focused tests are green. Do not combine several ownership moves into one
unreviewable commit.

## 5. Static architecture targets

Final G6 gates should mechanically enforce:

- application/domain services do not import FastMCP;
- platform adapters do not import FastMCP;
- features depend on platform contracts or the two explicit default-composition points,
  never concrete Linux adapters;
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

### 2026-10-08 service-unit compatibility decision (G6 checkpoint)

Independent review APPROVE_OPTION_A, reviewed evidence under
`~/.local/state/binnacle/g6-service-unit-review-n9cibbcd/` (reply and inventory).
`deployment.units.unit_property` retains the deployed default Linux systemctl query
locally rather than importing `platform.linux.service_unit_linux`. This avoids the
`deployment` ↔ `platform.linux.service_provisioning_linux` package cycle.
The Linux adapter remains at the approved owner and the legacy
`binnacle.service_unit_linux` module identity alias remains intact.
A newly staged cross-package monkeypatch-propagation assertion was not part of
the deployed contract; focused behavioral and injected-runner regression tests
replace that assertion. No Import Linter exemption or lifecycle change is made.
Integration, Gate A convergence, independent final review and deployment remain pending.

Implementation checkpoint: `07d423a6e93b03b90b794a01cd9bda91abd732d9`.
Focused Gate A boundary, service-unit, provisioning and doctor tests passed;
22 Import Linter contracts kept, 0 broken. Changed-file commit hooks passed.
Original staged service-unit wave remains unmodified and unmerged; its earlier
mypy failure was tied to the older `f5a7044` baseline and does not recur on
integration after the already-committed Webmin fix. No full convergence,
final-review, CI, live MCP or deployment evidence is claimed at this checkpoint.

### 2026-10-08 diagnostics/provenance checkpoint

Integration commit `e0c27c9` relocates `doctor_provenance` to diagnostics with a module-identity compatibility alias. Originating diagnostics-wave evidence was read, not modified. Focused provenance/system-doctor/Gate A tests: 58 passed. Changed-source Ruff/mypy and commit hooks passed; Import Linter 22 kept, 0 broken. No full convergence, CI, deployment or final Gate A evidence claimed.

### 2026-10-08 diagnostics/connectivity checkpoint

Integration 1638d51: endpoint doctor relocation with identity-compatible alias. The diagnostics wave remains untouched. Focused tests 83 passed; Ruff, mypy, Import Linter 22/22 and commit hooks passed. Final Gate A and deployment remain pending.

### 2026-10-08 doctor_common ownership conflict

On clean parent db4c9e3, a proposed diagnostics/doctor_common relocation passed 91 focused tests but broke top-level acyclicity (Import Linter 21/22). Exact loop: diagnostics.doctor_common to platform.deployment_platform to platform.linux.service_provisioning_linux to deployment.units to diagnostics.doctor_contracts. All trial changes were restored; the integration tree and 22/22 architecture contracts are clean again. The preexisting diagnostics-wave file was not modified. Smallest reviewable choices: defer doctor_common to the existing application shell with an explicit ownership exception, or approve a separate one-way Check/UnitSpec dependency boundary refactor. Neither is currently approved. G6 cannot claim final package convergence or Gate A while this target discrepancy remains.

### G6 diagnostics shared-contract boundary amendment — 2026-10-08

Independent reviewer APPROVE_SHARED_CONTRACT, evidence
`~/.local/state/binnacle/g6-diagnostics-boundary-review-oayxj4ii/`.
The deployed G5 pure `Check`/`Status`/`ok`/`warn`/`fail` contract remains
canonical at `binnacle.doctor_contracts`, classified once in the existing
`application_shell` manifest group as a **neutral root shared contract**, not
an application orchestrator. `diagnostics.doctor_contracts` becomes a compatible
same-module alias and is classified as a diagnostics facade. Deployment,
platform consumers and internal diagnostics import the neutral canonical
contract to avoid the actual `deployment -> diagnostics -> platform -> deployment`
cycle when the four remaining diagnostic modules converge. This amendment
neither creates a new package/framework nor weakens existing import contracts.
C0 must pass independently before D1–D4; all final Gate A external cells remain pending.

### G6 diagnostics C0–D4 implementation checkpoints (2026-10-08)

Independent review approved the shared-contract boundary in
`~/.local/state/binnacle/g6-diagnostics-boundary-review-oayxj4ii/`.
Committed in dependency order on the sole integration branch:

- C0 `dca93c7`: G5-stable neutral `binnacle.doctor_contracts` canonical owner,
  diagnostics compatibility alias, direct importer canonicalization and manifest.
  Focused contract/doctor/Gate A tests passed; Import Linter 22/22; mypy and
  changed-file hooks passed.
- D1 `829738c`: `diagnostics.doctor_common`; legacy module identity and
  definition-time `systemctl` binding retained. Focused tests 34 passed,
  Import Linter 22/22, mypy and changed-file hooks passed.
- D2 `d1f151e`: `diagnostics.doctor_jobs`; legacy identity, default state reader
  and restart-safety semantics retained. Focused tests 40 passed, Import Linter
  22/22, mypy and changed-file hooks passed.
- D3 `7b9b152`: `diagnostics.job_manager_doctor`; legacy identity and default
  `job_client.ping` binding retained. Focused tests 54 passed, Import Linter
  22/22, mypy and changed-file hooks passed.
- D4 `6e56997`: `diagnostics.doctor` aggregate relocated last; public module
  identity, `Deployment` pickle round-trip, CLI behavior and existing `__all__`
  preserved. Focused tests 94 passed, Import Linter 22/22, mypy and
  changed-file hooks passed. TYPE_CHECKING compatibility exports retain mypy
  access to the public symbols without changing runtime module alias.

These are focused checkpoint proofs, not the final exact-SHA full suite, coverage,
Python matrix, independent final implementation review, CI, canonical deployment,
live test/smoke/doctors, ChatGPT MCP call or final Gate A PASS. Production refs
and other wave evidence worktrees were not changed.

### G6 candidate freeze preparation — package/import ownership audit

Following C0–D4, the coordinator committed the additional narrow source and
verification checkpoints:

- `179dd2a`: register all newly retained Diagnostics aliases in the compatibility
  manifest; focused report/boundary tests and changed-file hooks passed.
- `bfe5031`: CLI/Watchdog CLI consumers select canonical diagnostic implementations
  rather than old compatibility aliases; 41 focused tests and all 22 Import Linter
  contracts passed.
- `93e9c5d`: verify old `binnacle.doctor.Deployment` pickle path resolution and
  neutral-contract AST import boundary; focused tests and hooks passed.
- `d5597d8`: correct the obsolete Gate A report wording while deliberately leaving
  final architecture/review/deployment cells **PENDING**.
- `fc6138d`: Diagnostics job-state/manager imports use the Commands-owned canonical
  implementations; 13 focused tests, 22 Import Linter contracts and hooks passed.

The latest source audit found **235** production Python modules each assigned exactly
once, **88** retained compatibility facades with no missing/multiply-owned entries,
and only two remaining direct legacy-facade imports among nested package modules:
`companions/watchdog/ops/services.py` uses the public tunnel-log fact interface,
and `companions/watchdog/watchdog_cli.py` consumes the approved tunnel unit name
constant. Both are deliberately retained as narrow companion-facing compatibility
boundaries rather than promoting new cross-companion implementation coupling.
They are not authorization to remove the public aliases. No other legacy facade
removal was proved safe under the public compatibility requirement.

All relocation groups in the approved manifest have their target canonical package
implementations. This is a **candidate freeze proposal**, not an independent final
implementation review or final Gate A pass. Final source and acceptance SHA must be
bound after committing this record. The exact-final-SHA full-suite, coverage, Python
matrix, distribution, architecture, CI, canonical deploy and real client gates still
require their respective independently recorded evidence.

### Exact-candidate first convergence finding — 2026-10-08

The first frozen source candidate `d433d9c` passed full `pre-commit --all-files`
(34 applicable/registered checks; job `37bff4003c5b`). Its pre-push fast suite
failed **5 of 1108 parallel-safe tests** (1103 passed) because two frozen G3
architecture test modules still matched the pre-G6 root alias
`binnacle.callctx`, while canonical G6 imports use `binnacle.mcp.callctx`.
The ordinary-process lane passed 1 selected test. Evidence: durable job
`9bf6d70c046d`. This was an actual FAIL, not a Gate A PASS.

The narrowly repaired tests now identify **only** the approved pure MCP
call-context module as owner `callctx`, rejecting other MCP glue imports.
`afe8f93` passed all focused platform and Commands architecture nodes,
changed-file mypy/Ruff/hooks, with no product-source change or linter exemption.
The corrected candidate needs new exact-SHA convergence; do not reuse the
failed pre-push result or mark any external Gate A cell green.

### Exact-candidate full-suite finding — 2026-10-08

Candidate `2b90465` passed the fixed-seed pre-push fast unit/contract gate
(job `ac0620b84929`) and entered managed full-suite validation.
Full suite job `ff7fc293b18e` produced **2241 passed, 3 skipped and 1 failed**
in its parallel-safe lane, with its ordinary-process lane **2 passed**.
The lone failure was the packaging smoke's pre-G6 expectation that the
removed private `binnacle/tools/read_file.py` path remained in the wheel.
The approved Files implementation is canonical at
`binnacle/features/files/tools/read_file.py`; reintroducing an obsolete
Files-tool importer would conflict with the existing protected import
architecture. No public MCP tool-wire behavior changed.

The test was tightened in `e0995e3` to assert **all four** canonical Files-tool
modules, their focused server, and the canonical Commands tool inside the built
wheel while retaining the existing Commands compatibility-entry assertions.
It also rejects the obsolete private Files adapter path. The exact failing
wheel-from-sdist, clean-install and CLI smoke test passed in isolation (job
`37a881822dec`); changed-file hooks passed. This repairs packaging
expectations, not product runtime, dependency or protected import rules.
A new final exact SHA must still pass the full convergence gates and independent
final implementation review before deployment or Gate A acceptance.

### G6 coverage policy boundary correction — 2026-10-08

Exact candidate `1581de3` completed all four coverage test execution lanes
(986+1 unit tests and 1256+1 non-unit tests passed, 3 skipped), but the
per-module coverage **policy checker failed with 23 findings** (durable job
`20d5b8bb5e58`). The failures concern old compatibility module files
with unexecuted import/CLI branches plus two stale core-source filenames;
canonical G6 feature/companion implementations already have measured high
coverage. No percentage threshold or temporary floor was changed.

The small repair updates the **existing 95% core policy paths** from removed or
facade files `src/binnacle/paths.py` and `src/binnacle/textio.py` to their
canonical `src/binnacle/features/files/{paths,textio}.py` implementations,
with unchanged core/other thresholds. A targeted unit module exercises the
legacy identity aliases and filesystem facade. The two `__main__` dispatch
branches are tested with pre-injected **stub-only canonical modules**; tests
never start or restart the actual job-manager or watchdog services.
Focused coverage showed 100% for the sampled legacy facades, including
`job_manager.py`, `watchdog_cli.py`, Diagnostics contract alias, Logstats,
Watchdog ops and `paths.py`; all 24 focused tests passed. This is targeted
regression evidence and **not** a claim that full coverage now passes.
The full policy gate must be rerun against the next committed exact candidate.

### Coverage convergence follow-up — 2026-10-08

Candidate `1cfbc527b5559c156b2f5f4a6e1b2110a798c85d` ran the full
coverage-policy gate (durable job `ef30e0be5891`). All test execution lanes
passed (1010 parallel-safe unit tests, 1 ordinary-process unit test, 1256
parallel-safe non-unit tests, 1 ordinary-process non-unit test, 3 skipped).
The checker reduced the prior **23 errors to one**:
`src/binnacle/watchdog_cli.py`: **66.67% full branch coverage**, below the
unchanged 90% minimum. The 211 other covered source modules satisfied their
policy; no temporary floors were introduced. This single legacy facade has a
`TYPE_CHECKING` branch and a `__main__` CLI dispatch branch, while the real
implementation lives at `companions/watchdog/watchdog_cli.py` and exceeds the
full-module coverage target. The latter result does not excuse the former.

A safe focused test exercises module identity and stub-only dispatch without
starting production watchdog or jobs. Its standalone coverage differs from
the aggregated xdist result; an attempted additional direct module-execution
probe did not produce stable attribution in coverage instrumentation and was
not committed. Preserve the failing Gate A coverage cell until the precise
wrapper/coverage attribution issue is resolved with a reviewable, non-weakened
check. Neither source candidate nor deployed refs were altered in this
follow-up; source integration was clean before this ledger update.

### G6 focused coverage attribution fix (2026-10-08)

The isolated four-worker test previously passed 24 tests but attributed 0%
coverage to the watchdog CLI compatibility alias. The stubbed runpy dispatch
test assumed a different test had already imported the real module in its
worker. The test now imports the canonical CLI and checks the legacy alias
before substituting a stub for main. The focused four-worker run passed all
24 tests, with 100% coverage for both CLI compatibility wrappers. No runtime
code, exclusions or coverage thresholds changed. The full exact-candidate
coverage policy and final Gate A cells remain pending.
