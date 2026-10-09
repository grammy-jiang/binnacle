# Binnacle Stage 1 — OS-Independent Core / Linux Platform Separation

**Document ID:** BINNACLE-OS-STAGE1-20261009
**Status:** Proposed implementation plan; implementation not yet started
**Baseline:** Binnacle v1.0.1, commit 02f4bab9bc7562668ffc41d622c4274449933768
**Framework baseline:** FastMCP 4.1.0; MCP SDK 2.3.0; mcp-types 2.3.0
**Primary target:** Separate OS-independent Binnacle logic from existing Linux-specific mechanisms without losing Linux behavior
**Next stage:** Native macOS/Darwin implementation after Stage 1 acceptance
**Explicitly excluded:** macOS adapter implementation, Fedora/RHEL-specific compatibility, unrelated feature development and dependency upgrades

> This document is the implementation proposal for discussion and approval. A committed plan is not permission to modify production, deploy, restart the stable job manager, weaken tests or bypass established review/CI gates.

## 1. Goals and design invariants

### 1.1 Definition of the problem

The current release has extracted several Linux mechanisms into the platform package but the isolation is incomplete. Examples observed in source and read-only probes:

- The job and deployment factories choose Linux directly.
- The generic job engine exposes PID/PGID/starttime/cgroup semantics.
- The generic deployment and doctor paths still contain systemd, procfs, journald and loginctl assumptions.
- The general log analysis module loads its Linux acquisition facade at import time.
- Root/path checks compare resolved candidate paths against roots that may not be normalized the same way. A synthetic allowed-root symlink was incorrectly rejected with path_outside_root.
- The production bootstrap eagerly constructs platform-dependent services during module import.
- Existing import-linter policies correctly preserve the G3–G6 architecture but do not yet prove complete OS-independent core execution.

The architectural objective is **one FastMCP application, one product/domain core, narrow OS contracts, and a Linux adapter selected at one composition boundary**. Future Darwin support must implement OS contracts, not a second MCP server.

### 1.2 Three responsibility owners

| Owner | Owns | Does not own |
| --- | --- | --- |
| FastMCP | MCP server, child-server mounting, Providers, Transforms, Middleware, authentication, request-scoped injection, lifespan, MCP Tasks and HTTP routes | POSIX process identity, jobs, cgroups, systemd, service logs, OS-specific paths |
| Binnacle Core | Files, Search, Commands, job orchestration, durable storage, diagnostics policy, telemetry parsing, deployment decisions and public MCP tool semantics | Direct systemctl, procfs/cgroup mechanics, OS platform selection |
| OS Platform | Process execution/inspection/signaling, job containment, resource measurement, managed services, service log acquisition, runtime path conventions and host-specific diagnostics | MCP registration, component visibility, Binnacle policy or storage ownership |

Use FastMCP's native mechanisms; do **not** create ServerBuilder, FeatureRegistry, OS Provider, generic Middleware dispatcher, new MCP transport, custom ServerExtension for platform selection, or a second lifecycle framework.

FastMCP Depends (FastMCP 4.1.0 import: fastmcp.dependencies) belongs to request-scoped MCP dependencies when appropriate. Long-lived OS/process dependencies are ordinary explicitly constructed Python application services. FastMCP Lifespan must not terminate independently managed durable jobs.

### 1.3 Non-negotiable Linux parity

Preserve:

- Eight public MCP tools in the existing order: read_file, list_files, search_text, edit_file, write_file, run_command, job_status, stop_job.
- Existing four client-visibility profiles (8 / 6 / 6 / 8), descriptions, input/output schemas, annotations, visibility and denied-call behavior.
- Original auth, middleware ordering, logging/correlation and native FastMCP mount arrangement.
- Bash command semantics, bounded wait and handoff, job IDs, output spool/cursors, 1st-party job-manager RPC, repeated stop behavior and manager/embedded ownership.
- Existing persisted job records and historical cgroup/resource metadata; no silent schema migration or deletion.
- Linux systemd units, setup/dry-run/adopt/backup, dev/prod mode, doctor, stats, token rotation, quiet restart, CI, smoke and rollback guarantees.
- Root path security and denial of escaping allowed directories.

A necessary defect fix (e.g. alias root normalization) must be isolated and tested; it must not become a pretext for arbitrary public contract change.

## 2. Baseline and evidence

The candidate must be derived from the exact v1.0.1 SHA. Maintain an independent Git worktree. Do not alter the primary checkout or its preexisting untracked documents.

Stage OS0 shall freeze immutable evidence with source SHA and toolchain versions:

1. All tracked production, script and relevant test paths with SHA-256 hashes; cross-platform ownership inventory.
2. Full raw MCP surface for default, modern ChatGPT, legacy ChatGPT and unrelated clients (not just normalized hashes), including root-local/raw provider multiplicity.
3. Existing CLI help, relevant JSON/text output, units rendered from recorded parameters, managed-service setup previews and doctor behavior.
4. Representative durable-job metadata, RPC protocol v1 records, full cursor semantics, stdout/stderr/exit/signal, wait/handoff, recovery, cgroup/resource history and stop behavior.
5. Quality gates, import graph, focused tests and known defects, all attributed to the baseline SHA.
6. Independent failure probes (symlink root alias and Linux import blocking) preserved without overwriting prior evidence.

Already observed during investigation, for orientation only (re-run/record formally in OS0):

- 143 production Python modules, 47 scripts, 195 test files.
- Import Linter: 20 contracts kept; 0 broken. Source architecture check: 143 modules, 0 forbidden reverse dependencies.
- Focused platform/path tests: 167 passed. Focused job/resource tests: 42 passed. FastMCP composition/tool tests: 40 passed.
- Allowed-root symlink synthetic probe: path_outside_root (a reproducible defect).
- Blocking Linux imports prevented import of logstats, jobs and the current server bootstrap, revealing missing separation.

Artifact placement: evidence lives outside production checkout and is immutable once labeled. Each work package records its input SHA and the evidence it consumes.

## 3. Target architecture

~~~text
FastMCP (native)
  root FastMCP
    ├── Files child FastMCP
    ├── Search child FastMCP
    └── Commands child FastMCP
              │
              ▼
         Binnacle Domain
              │
              ▼
      narrow Platform Contracts
              ▲
              │
        Linux implementations

Host/bootstrap composition (the only OS selection entrypoint)
  └── Linux services (Stage 1)
      └── Darwin services (Stage 2, NOT Stage 1)
~~~

Keep existing package domains. Evolve the smallest necessary files; do not move code for cosmetic symmetry. A possible target is:

~~~text
binnacle/
  mcp/                         # native FastMCP glue and pure factory
  features/{files,search,commands}/
  deployment/                  # generic plan/review/apply policy
  diagnostics/                 # generic checks/results/rendering
  observability/               # event parsing/aggregation
  platform/
    contracts/                 # small domain-oriented Protocols
    composition.py             # automatic host selection, Linux only now
    linux/                     # process, cgroup, systemd, journal, paths
  companions/{watchdog,tunnel}/ # independent auxiliary apps
  server.py                    # compatible production bootstrap/exports
  cli.py                       # public CLI, calls domain + platform service
~~~

Contracts must remain small and semantic. Platform selection is not a universal service locator or dynamic MCP Provider registry. Use explicit dependency passing in factories.

For testability the pure FastMCP factory may need to move into a Linux-free composition module. Preserve existing binnacle.server:mcp, binnacle.server:app and create_server() consumer contracts via a thin compatibility/bootstrap module. The **pure factory** must work with fake platform dependencies without importing Linux; the default Linux production bootstrap is allowed to select Linux deliberately.

### 3.1 Dependency rules

Allowed:

- MCP tools -> domain use cases / small command backend contract.
- Domain -> platform Protocol, explicit callbacks/data structures.
- Linux implementation -> platform Protocol/common utility.
- App/bootstrap -> concrete Linux implementation and child-server factories.
- Companions -> deliberately approved stable public core contracts.

Forbidden:

- Pure core -> platform.linux / observability.linux.
- Platform Protocol -> FastMCP, MCP request/session types, CLI, job storage.
- Linux platform implementation -> FastMCP, domain policy and job store.
- Core server -> companion implementation.
- Generic deployment/diagnostics -> systemctl, loginctl, journalctl, /proc, /sys/fs/cgroup.
- Tool adapters -> platform-specific process signals, unit definitions or host detection.
- Provider/Transform/Middleware -> selecting OS adapters.

Static rules must cover imports, aliases, common dynamic imports and actual method/path use, with meaningful negative tests. Limit explicit compatibility exceptions to named modules/edges; no blanket suppression.

## 4. Complete ownership and split-point inventory

Each source module must receive one of KEEP / SPLIT / LINUX / BOUNDARY with evidence and a target owner. The following are the known high-priority split points; OS0 must complete the exhaustive per-file inventory before implementation.

| Area | Files or families | Decision / expected outcome |
| --- | --- | --- |
| Root composition | server.py | SPLIT: pure FastMCP factory vs production Linux bootstrap; preserve existing exports/instructions |
| Core CLI | cli.py | SPLIT: command dispatch from Linux unit/provisioning and system-specific remedies |
| Configuration | config.py | SPLIT: generic settings vs OS runtime defaults; avoid eager Linux selection |
| Factories | platform/job_platform.py, platform/deployment_platform.py | SPLIT: central platform selection with Linux default |
| Contracts | platform/contracts/process_contracts.py, resource_contracts.py | BOUNDARY: remove Linux-visible names/ownership where material; keep compatibility |
| Contracts | runtime_path_contracts.py, service_lifecycle_contracts.py, service_log_contracts.py | KEEP/BOUNDARY: assess semantics and optional unavailable states |
| Linux process | platform/linux/job_process.py | LINUX: procfs, PGID, process inspection, signal group, boot identity |
| Linux resources | platform/linux/job_cgroup.py | LINUX: cgroup v2 creation, attachment, counters, wait-empty, cleanup |
| Jobs | features/commands/jobs.py | SPLIT: domain lifecycle, storage, wait/reap vs Linux identity/containment |
| Job manager | features/commands/job_manager.py | SPLIT: owner protocol/dispatch vs systemd READY notification, local endpoint binding where necessary |
| Job routing | features/commands/job_owner.py | BOUNDARY: use validated job identity and scoped process API |
| Command status | features/commands/command_status.py, command_contracts.py, command_backend.py | BOUNDARY: replace PGID as core querying identity without changing public result |
| Resource history | features/commands/job_resource_history.py | SPLIT: generic retention/history vs cgroup finalization mechanics |
| Job RPC/store | job_client.py, job_store.py, job_output.py | KEEP: current local Unix JSON RPC and disk/cursor behavior; test Darwin suitability later |
| Command execution | command_execution.py, commands_server.py, tools/* | KEEP/BOUNDARY: FastMCP adapter and use-case architecture remain unchanged |
| Deployment | deployment/units.py | SPLIT: marker/diff/adopt/backup vs systemctl/procfs/unit-specific checks |
| Linux service templates | deployment/server_unit.py, job_manager_unit.py | LINUX: systemd-only units (may relocate under platform/linux while retaining compatibility imports) |
| Linux services | platform/linux/service_systemd.py, service_provisioning_linux.py | LINUX: systemd status/restart/install/linger |
| Linux log/path | platform/linux/service_journal.py, runtime_paths_linux.py | LINUX: journald and XDG runtime paths |
| Diagnostics | diagnostics/doctor.py, doctor_common.py, doctor_jobs.py, job_manager_doctor.py | SPLIT/BOUNDARY: generic checks vs Linux systemctl/procfs/linger and messages |
| Endpoint doctor | diagnostics/doctor_connectivity.py | BOUNDARY: HTTP check generic; systemd restart advice platform-specific |
| Diagnostics helpers | doctor_io.py, doctor_provenance.py, doctor_render.py, doctor_contracts.py | KEEP |
| Log acquisition | observability/logstats_io.py | SPLIT: keep Linux facade only where needed; generic parser may not import Linux |
| Log analysis | observability/logstats.py, logstats_* | KEEP/BOUNDARY: pure parsing/aggregation; remove eager Linux acquisition |
| Resource history | observability/system_resource_history.py, observability/linux/webminstats.py | BOUNDARY/LINUX: optional provider and Linux-only Webmin storage |
| Privacy/log path | observability/log_safety.py | BOUNDARY: root path normalization must not hardcode home/Projects |
| Files paths | features/files/paths.py | SPLIT: consistent canonicalization, symlink safety, authorized root policy |
| File tool set | features/files/tools/*, textio.py, files_server.py | KEEP: native MCP adapter and generic file/text operations |
| Search | features/search/search_text_rg.py, search_text_stream.py, other search modules | KEEP: ripgrep is an external cross-platform tool, not inherently Linux |
| MCP plumbing | mcp/identity.py, visibility.py, logging_middleware.py, callctx.py, tool_order.py | KEEP: FastMCP-native behavior and protocol-era client support |
| Tunnel companion | companions/tunnel/* | LINUX companion where service unit logic exists; no core dependency |
| Watchdog companion | companions/watchdog/ including ops/ | LINUX/Raspberry Pi companion; no broad porting in this stage |
| Deployment scripts | scripts/deploy_flow.py, deploy_smoke.py, smoke_checks.py | BOUNDARY: generic orchestration vs Linux production composition |
| Host scripts | scripts/resource_monitor.py, weekly_host.py, weekly_scope.py | LINUX-only maintenance tools; out of core runtime |
| Build/test scripts | scripts/dev*, check_architecture.py, test/CI policy | BOUNDARY: enforce architecture, preserve local developer workflows |
| Packaging | pyproject.toml, uv.lock, workflows, README | BOUNDARY: keep current Linux support claims, preserve tested dependency versions |

Every KEEP decision requires a short justification, especially where subprocess is used. Generic subprocess to launch ripgrep is not by itself a reason to write an OS adapter.

## 5. Implementation work packages

### OS0 — Baseline, evidence and exhaustive inventory

Inputs: exact tag v1.0.1, existing docs/tests, current Linux reference behavior.

Tasks:

1. Inspect repo/worktrees/branch state and establish single implementation owner with an independent worktree.
2. Reproduce the focused static and behavioral baselines and collect immutable outputs.
3. Generate comprehensive module/import/symbol/OS-mechanism inventory; classify 143 modules and relevant scripts.
4. Identify hidden import-time effects, settings globals, process/socket/service ownership and affected downstream callers.
5. Map each split point to minimal interface change, behavior invariant, tests, owner and work package.
6. Identify historical compatibility facades and pre-existing user-owned untracked documents; do not take ownership of them.
7. Produce a risk register and dependency graph for OS1–OS7.

Exit: each module is classified; every P0/P1 seam has an owner, observable invariant and test; source baseline and public wire are immutable.

### OS1 — Contract design and architecture gates

1. Review all five existing platform Protocols against Linux behaviors.
2. Specify a semantic job/process identity interface that avoids leaking PGID into generic commands.
3. Clarify containment vs accounting. Split interface only as required to express different capabilities; avoid an unnecessary class hierarchy.
4. Define lifecycle, runtime path, service log and diagnostic unavailable/error semantics.
5. Specify typed factory entrypoints, compatibility fields and exact ordering of construction.
6. Add Import Linter contracts and AST scanner rules with positive/negative tests for direct, alias and literal dynamic imports, subprocess utilities and Linux path literals.
7. Have an independent design review before broad module migration.

Exit: frozen narrow contracts, enforceable dependency direction and a reviewed migration compatibility strategy.

### OS2 — OS selection, pure application composition and configuration

1. Implement a single OS-family resolver for bootstrap, selecting Linux only in Stage 1.
2. Allow explicit injection of fake platform services into pure application/core factories.
3. Eliminate unnecessary import-time Linux backend construction in core.
4. Separate runtime socket, state, config and token path defaults from generic configuration validation.
5. Preserve existing server public entrypoints and default Linux initialization, including authentication and FastMCP mounts.
6. Ensure unknown OS fails transparently without selecting Linux.
7. Ensure a fake-platform core factory builds a FastMCP app with the current tool inventory, without importing platform.linux.

Exit: default Linux behavior unchanged; pure factory + generic configuration can be tested without Linux implementation imports.

### OS3 — Commands / durable jobs platform boundary (high risk)

1. Preserve the existing durable engine, owner routing, data store and RPC; characterize leader-exit and descendants.
2. Introduce an internally opaque job/process identity for process inspection/stop, keeping Linux persisted pid/pgid/starttime and public fields intact.
3. Move OS-specific process launch/inspection/signal details behind ProcessBackend; keep existing Linux procfs and group behavior.
4. Audit the read-state -> enumerate descendants -> send SIGTERM -> wait -> SIGKILL race. Reject unverified targets and test PID/PGID reuse; do not assert an atomic guarantee that Linux implementation does not have.
5. Clarify containment responsibility separate from resource counter collection; retain cgroup v2 integration and correct finalization.
6. Move systemd NOTIFY_SOCKET readiness into Linux integration; keep generic manager RPC request/response lifecycle.
7. Keep current bash -c, input spool file, merged stdout/stderr, wait handoff, output cursors and error shapes.
8. Run bidirectional existing/new manager-RPC compatibility checks, schema-1/schema-2/legacy persisted record checks, restart/recovery and concurrency tests.
9. Test no accounting, failed cgroup attachment, disconnected client, dead owner, orphaned child and resource-finalizer behavior using isolated temporary roots and processes.

Exit: core commands execute with fake process backend; Linux job lifecycle, persistence, stop and resource accounting match the v1.0.1 contract. No production manager restart.

### OS4 — Deployment, managed services and Linux-specific CLI (high risk)

1. Extract generic marker/plan/diff/adopt/backup from deployment/units.py without altering decisions.
2. Keep systemd unit rendering, process property inspection, readiness, linger, systemctl and journalctl in Linux implementation.
3. Make setup/mode/doctor/token-rotation call semantic platform/deployment services rather than Linux classes.
4. Maintain explicit safe restart/quiet-window and rollback behavior; no service-manager-specific mechanics in generic orchestration.
5. Preserve systemd unit template content and rendered markers, path and enable/reload order under current Linux contract.
6. Move or isolate Linux-only compatibility facades with controlled import rules; keep existing public CLI names and options.
7. Use fakes/synthetic unit trees in tests; no host service mutation from ordinary tests.

Exit: CLI/deploy generic workflow has no direct systemd/procfs calls; Linux service behavior and unit bytes/semantics are preserved.

### OS5 — Files, paths, diagnostics and observability

1. Fix allowed-root canonicalization so symlink roots and targets are compared consistently; preserve symlink escape protection.
2. Verify absolute/relative/~ paths, missing targets, .. escapes, alias roots, permission failures, path swapping, glob behavior and case-sensitive matching assumptions.
3. Preserve ripgrep search, stream timeout, context/ordering/budgeting and tool schemas; do not create a needless search OS adapter.
4. Remove the import edge from generic observability/logstats.py into the Linux log reader; retain a Linux compatibility accessor where needed.
5. Split generic diagnostics result aggregation from systemd/linger/procfs checks, text hints and deployment-specific status.
6. Make the resource history provider optional and explicit; Webmin remains a Linux host feature.
7. Align telemetry path hashing with configured root conventions without revealing private paths or modifying retained telemetry semantics without tests.
8. Re-run Linux module import blocking and fake-platform tests after each split.

Exit: core Files/Search/diagnostics/statistics execute against mocks without importing platform.linux; Linux public outputs retain compatibility except explicitly characterized defect fixes.

### OS6 — Completeness sweep, companions and infrastructure alignment

1. Re-scan every src/binnacle Python module, script entrypoint, lazy import and module-level constructor.
2. Verify companion boundaries: core -> Watchdog/Tunnel forbidden; companions may remain Linux-only and consume approved public contracts.
3. Classify Linux-only resource monitor, weekly host/scope and hardware tools; do not port them in this stage.
4. Upgrade old tests pinned to the literal Linux factory AST structure to enforce semantic selection and contract compliance instead.
5. Update pyproject Import Linter policies, quality-policy.json architecture rules and documentation without reducing test/coverage thresholds.
6. Check wheel/sdist/imports and Linux metadata; do not advertise macOS support yet.
7. Eliminate stale compatibility facades only when no supported consumers remain, with negative tests for forbidden return paths.
8. Verify no duplicate FastMCP child servers, Providers or tools were introduced.

Exit: complete inventory reconciled; no unexplained platform leak or obsolete module remains.

### OS7 — Integrated acceptance and Linux deployment qualification

1. Integrate only reviewed SHA-bound work packages into a single candidate.
2. Execute the complete OS Independence Acceptance Suite and FastMCP Native Architecture Gates.
3. Verify exact client-visible MCP surface in all four profiles and raw local/provider ownership; no golden rebasing to hide drift.
4. Execute cross-version durable RPC/metadata, restart, stop, cgroup and Linux service tests.
5. Run pre-commit, pre-push, coverage-policy, supported Python 3.10–3.14 tox matrix, wheel-from-sdist and clean-install tests.
6. Complete independent architecture and implementation review, with no framework overlap, undocumented contract change or weakened gate.
7. Only after exact-candidate CI is green, use the existing guarded production deployment process. Never replace it with a direct push or unmanaged service restart.
8. If job-manager code is affected, treat manager restart/upgrade as a separately gated operation after confirming no active work; verify rollback and old records.
9. Confirm Raspberry Pi live smoke and production doctors. Preserve rollback evidence and a clean accepted candidate.
10. Publish a stage-completion evidence report and a bounded list of Darwin adapter work remaining.

Exit: accepted Linux production parity **and** verifiably Linux-independent core, with reviewed artifacts and no uncontrolled host changes.

## 6. Test contracts and mandatory gates

### 6.1 OS Independence Acceptance Suite

| ID | Test | Acceptance condition |
| --- | --- | --- |
| OI-01 | Static dependency graph | Generic core cannot import Linux implementation modules |
| OI-02 | Dynamic import / alias negatives | Intentional violations trigger the gate |
| OI-03 | Adapter import isolation | Blocking platform.linux imports does not prevent loading pure factories and domain modules |
| OI-04 | Fake-platform execution | Files, Search, Commands, generic diagnostics and log parsing work against fake services |
| OI-05 | Config/bootstrap independence | Generic Settings and explicit pure factories do not eagerly construct Linux adapters |
| OI-06 | Process identity and stop | No signal sent to a target not proven to belong to the requested job; race tests explicitly cover uncertain cases |
| OI-07 | Durable lifecycle | start/wait/background/restart/stop/recovery/cursor/retention remain correct |
| OI-08 | Path and symlink safety | Legitimate aliases work, escaping symlinks stay forbidden, error codes stay intentional |
| OI-09 | Service abstraction | Generic service policy runs with fake lifecycle/provisioning; Linux backend manages systemd |
| OI-10 | Log source isolation | Parsing/analytics does not require journald import |
| OI-11 | Companion isolation | Server/core works with companions absent; only approved companion exports used |
| OI-12 | Linux parity | Real Linux implementation satisfies frozen behavior and deployment semantics |

Negative test cases should cover direct imports, aliases, `__import__`, importlib imports, forbidden path literals, dynamic selection and contract bypass attempts. Do not claim to detect arbitrary dynamic code with a static analyzer; complement static checks with runtime isolation.

### 6.2 FastMCP Native Architecture Gates

| ID | Required property |
| --- | --- |
| FM-01 | Original root and three native FastMCP children; mount structure and native Providers retained |
| FM-02 | No PlatformBackend implemented as MCP Provider or shadow Provider registry |
| FM-03 | Transforms own visibility/presentation; Middleware owns request/interception; ordering preserved |
| FM-04 | FastMCP Depends used only for appropriate MCP dependencies; long-lived OS services injected by ordinary constructors |
| FM-05 | FastMCP Lifespan cannot terminate independent durable jobs; no redundant MCP lifecycle manager |
| FM-06 | Auth, client identity, visibility, denied-call behavior and privacy-safe logging unchanged |
| FM-07 | No Platform Contract or concrete adapter depends on FastMCP |
| FM-08 | Exact eight-tool public surface, schemas, description, annotation, local/raw multiplicity and four visibility profiles |

Do not equate on_duplicate="error" with checking cross-provider duplication; retain explicit raw-component ownership tests. Use FastMCP in-process Client as well as wire/golden tests.

### 6.3 Test frequency

- For each small change: targeted unit/contract/static tests only.
- On failure: inspect captured traceback/output; fix cause; rerun only relevant scope; do not repeat identical calls without new evidence.
- End of each work package: focused package tests + affected OI/FM gates.
- OS3/OS4 integration: isolated real Linux process/service-adapter regression tests.
- OS7 only: full managed two-lane test suite, coverage-policy, tox matrix, packaging, exact-candidate CI and guarded production smoke.
- Never bypass the test runner's no_xdist lane. Ordinary tests must not mutate host services, network, system configuration or production jobs.

## 7. Coordination, autonomy and safe failure handling

### 7.1 Worktrees and ownership

Use a separate implementation worktree/branch for substantial work. OS3 and OS4 may proceed independently after OS1 contracts freeze; OS5 path work may start in parallel, but OS5 diagnostics depends on OS4 service contracts. One integrator owns the final candidate.

Do not clean/stash/reset another session's worktree. Preserve dirty and untracked files. Check SHA, worktree status, lock, branch ownership and staged diff immediately before commit/integration/cleanup.

### 7.2 Independent execution protocol

For routine code/test failures, proceed without stopping for minor questions:

1. Inspect exact failure and relevant evidence.
2. Localize cause and distinguish actual implementation failure from a stale layout-only test.
3. Fix cause while preserving behavior.
4. Run minimal related tests.
5. Expand verification to dependent contracts.
6. Record the fix and resume downstream work.

Failures in import graph, fixture setup, mock implementations, lint/type checks, code moves, and safe build tooling fall under normal autonomous repair.

Do **not** silently weaken tests or architecture restrictions, modify frozen goldens to manufacture parity, bypass hooks/CI/deployment, restart an active stable job manager, overwrite another agent's edits or change published job-data semantics. If such boundaries are reached, continue independent safe work and retain an explicit evidence-backed blocker.

### 7.3 Review structure

- OS0: inventory and baseline review.
- OS1: independent interface/architecture review before migration.
- OS3, OS4: targeted review for process safety and service-deployment compatibility.
- OS6: full source-boundary audit.
- OS7: independent end-to-end architecture/security/behavior review before production.

## 8. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| FastMCP architecture duplication | FM gates; prohibit custom MCP registries/providers for OS behavior |
| Eager Linux import from core | Separate pure factory and production bootstrap; import-blocking tests |
| PID reuse / process stop race | Identity-aware backend API, explicit fail-closed uncertainty, controlled race tests |
| Manager/version incompatibility | Cross-version RPC and old metadata fixtures, no implicit manager restart |
| Lost descendant containment or resource history | Preserve Linux cgroup behavior; test leader-exit and finalizer scenarios |
| Symlink alias fix weakens security | Canonical root/candidate tests plus symlink escape/property cases |
| systemd deployment drift | Golden original unit templates, plan/adopt/backup/quiet/rollback tests |
| Log parsing tied to journald | Separate log acquisition from parsing; generic fake-source test |
| Companion leakage | Maintain one-way dependency graph and approved public exception list |
| Excessive test cost | Focused reruns; one full suite at final convergence |
| Collisions with other worktrees | Separate branches, SHA-bound reviews, single integration owner |
| Public protocol drift | Exact wire and visibility gate; no unapproved golden update |

## 9. Definition of Done / deliverables

The stage is complete only when **all** hold:

- [ ] Complete owned per-file inventory for all production modules and relevant scripts, including justified KEEP decisions.
- [ ] FastMCP and Binnacle domain responsibilities remain distinct and native.
- [ ] Core imports and business tests run with Linux adapters blocked and mock platform services injected.
- [ ] Linux platform selection is centralized; unknown OS is handled explicitly.
- [ ] Process identity, containment and accounting are correctly separated by responsibility.
- [ ] Existing Linux persistent job metadata, RPC, output/cursor and stop semantics remain compatible.
- [ ] File aliases work without opening traversal or symlink escape paths.
- [ ] Generic deployment, diagnostic and log-processing code no longer directly performs Linux mechanisms.
- [ ] Companions remain independent; no extra platform runtime is required for the core.
- [ ] OI-01..OI-12 and FM-01..FM-08 pass.
- [ ] Existing Linux focused/full, CI, packaging, doctor and live smoke acceptance pass.
- [ ] Final candidate and source/decision evidence are independently reviewed and auditable.
- [ ] No macOS adapter or Fedora/RHEL-specific development was introduced prematurely.

Expected final artifacts:

1. Accepted OS-independent core with Linux concrete implementations.
2. Exhaustive module/boundary map and updated architecture policy.
3. Narrow tested platform contracts and composition entrypoint.
4. Mock-platform acceptance tests plus Linux parity evidence.
5. Cross-version job/manager compatibility evidence.
6. FastMCP-native architecture review evidence.
7. Updated developer/architecture documentation.
8. Guarded production Linux qualification evidence and rollback reference.
9. A precise, non-implemented Darwin adapter backlog for the following stage.

**Final acceptance rule:** Pure core + fake platform works; current Linux works unchanged; FastMCP remains the only MCP component/lifecycle framework. These are conjunctive, not interchangeable, criteria.
