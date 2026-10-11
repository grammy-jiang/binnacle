# Mac-first native compatibility: implementation execution plan

Date: 2026-10-11, Australia/Sydney. Status: **AUTHORIZED AFTER INFRASTRUCTURE AND DESIGN GATES; IMPLEMENTATION NOT STARTED BY THIS DOCUMENT.**

## 1. Authorization, deliverable and truth boundary

The user's 2026-10-11 instruction supersedes the older research handoff's
“implementation not authorized” status. It authorizes autonomous Mac source
implementation, scoped native tests and branch commits after the gates below,
then conditional guarded integration and cleanup after all applicable Mac and
Linux features, tests and independent reviews pass. No routine clarification
is needed during the next eight hours. This is not permission to weaken gates,
signal uncertain processes, change credentials or deploy through ordinary Git.

**This authoring task changes and commits only this document**, in:

```text
/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011/mac-native-implementation-plan-worktree
branch: plan/macos-native-autonomous-20261011
base:   1ba2bf33e1791cd18f96984f4808b4863b89239c
```

No production `src/` or `tests/` edits, service operations, other worktree
mutations, GitHub push, master merge or background implementation launch are
part of this authoring task. Future dispatch uses separate owned author
worktrees on Mac. The plan worktree remains a reviewable checkpoint.

Canonical workflow: [DEVELOPMENT.md](../../../DEVELOPMENT.md),
[AGENTS.md](../../../AGENTS.md),
[Mac-first workflow](../../mac-first-development-workflow.md),
[testing](../../testing.md), [quality gates](../../quality-gates.md),
[architecture](../../os-independent-stage1-architecture.md), and
[GitHub governance](../../github-governance.md). Repository development rules
remain binding. New support claims require new evidence; authorization does
not turn research into acceptance.

### 1.1 Immutable external research inputs

Read directly outside the worktree, under:

```text
/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011/mac-native-plan-inputs
```

| Input | Observed SHA-256 |
| --- | --- |
| `HANDOFF.md` | `7c3859c183f6e2f8a3ab430a5ae4ca32776f5e7c1fc5c7f405f5324ae9303f19` |
| `CAPABILITY.md` | `ce0bc9ad44f2912580997f46f9dc6b94f520dfc5f648ab9f663c10b19204c51b` |
| `RESEARCH-SUMMARY.md` | `dec5d37cb7dfd7f3c2ce55c531e60914cae7f6bde616ab3f1e324e9d00227ef1` |

Research commits recorded by these inputs: plan
`6249d42417afb0901c6558cc6a293ba94f6d0b0f`, evidence
`855749098c2960b13507c092c822bd695917a5a2`, independent review
`2a4a03a1dac9e2f5caf81b37e6a2061b81029512`, capability index
`3bad179314fdd88520cd0d44ad66fa20ffac53db`. Historical source
`dbff274eb3ba925a1b6619cd072e112cdc6febf8` and targeted comparison source
`526dd5ef5829a342dbf8ff99d867869bbdc81742` are not implementation bases.
The old StopIntent plan `9e98a40b76bea7ebe66f529913fc5c9f2be566e6`
and abbreviated WIP `27a6888` are quarantined historical inputs, not accepted
fixes. Resolve its full SHA before any read-only comparison; never guess it.

The prior research directory and its original capability index were absent from this
checkout at the pinned base. Do not manufacture local evidence files or change
the supplied artifacts. Future I0 may retrieve exact research commits read-only
and verify hashes. This document alone corrects the obsolete authorization.

### 1.2 Observed source and operational pins

Observation window: 2026-10-10 16:30 UTC / 2026-10-11 AEDT. Ref names are
mutable; these observations are not guaranteed current at future dispatch.

| Surface | Observed value | Interpretation |
| --- | --- | --- |
| Requested worktree HEAD | `1ba2bf33e1791cd18f96984f4808b4863b89239c` | Clean authoring base, includes four commits beyond observed master |
| Local shared `master` and cached `origin/master` | `d61761356ee0fce8ea6d73b0c3043b4881c5645e` | Read-only refs; never move them from a worker |
| GitHub `master`, read through GitHub connector | `d61761356ee0fce8ea6d73b0c3043b4881c5645e` | Remote observation, independently of cached ref |
| GitHub `proof-of-concept`, same connector | `02f4bab9bc7562668ffc41d622c4274449933768` | Remote branch only; not proof of running deployment |
| Actual Pi checkout, MCP loaded revision and stable manager generation | **NOT OBSERVED** | Required runtime inputs from Pi coordinator before implementation dispatch |
| Mac capacity | User-specified 18 cores / 128 GiB | `sysctl` denied in authoring sandbox; remeasure in I0 |
| Developer doctor | 7 OK, 2 FAIL | Global uv 0.12.22 versus locked 0.12.24; no worktree `.venv` |
| Worktree inventory | 16 registered at observation | Several dirty; all other owners' work preserved |

The four source-base additions are `300d4bae0974431b0ae1b14a061d6422c760215a`
(search regression), `1e141ba5b537bb8d5f0924cc96da69d697af456b`
(Mac workflow), `b41b6c199adc22c925b01b591ca94eec04b7db88`
(dual-target mypy/API guards), and the requested base. Presence does not prove
independent approval or CI for these commits. I0 must reconcile their evidence
with upstream before relying on them.

Shell `git ls-remote` failed DNS in the authoring sandbox; the connector was
usable read-only. Default uv cache access was denied; using a private
`UV_CACHE_DIR` allowed doctor and worktree inspection. No claim of a clean
infrastructure gate follows from these partial checks.

## 2. Bounded product contract and non-negotiable limits

Mac is the primary development and native test host. Raspberry Pi supplies
trusted SSH coordination, independent Linux clones, review and release gates;
it is not a parallel product source author. Git commits or hashed patches are
the exchange boundary, never mutable-directory rsync.

FastMCP retains MCP lifecycle, native Providers, Transforms, Middleware and
three child-server composition. Portable Core remains ordinary Python policy
behind explicit contracts; do not add a FeatureRegistry/router or substitute
FastMCP Tasks for durable jobs. Existing Core is not a `src/binnacle/core/`
directory: use the actual `features/`, `application.py` and contracts layout.

| Milestone | Initial supported objective | Hard acceptance limit |
| --- | --- | --- |
| M0 | Darwin path/config selection, lazy platform construction, portable application/Core imports | Linux defaults and records unchanged; unsupported hosts fail explicitly |
| M1 | Native Files/Search using retained opened-root descriptor authority | No resolve-then-open authorization; TCC denial is explicit, not bypassed |
| M2 | Separate user-domain launchd manager/frontend; authenticated generation-bound AF_UNIX | Pathname, lockfile or same UID alone cannot establish service authority |
| M3 | Evaluate retained trusted witness for Commands; default narrow disabled mode | No full Commands claim until public supported authority, enrollment and closure are independently proven |
| M4 | Scoped process/direct-child metrics and private epoch-aware logs | Whole-job cgroup equivalents remain typed `UNAVAILABLE` when unproven |
| M5 | Native ARM64 wheel/CLI and user-domain installation into owned fixtures | No production label, credentials, global PATH changes or PyPI publication |
| M6 | Meaningful dual-host fake, contract and native acceptance | Fake adapters/type-checks are never native runtime evidence |
| P0 | Separate Linux Stage1 StopIntent safety repair | Blocks combined integration/release until independently accepted |

**N2 remains INCONCLUSIVE.** A retained witness is an implementation candidate,
not established complete authority. Enumerating a PID tree, testing a start
stamp and later killing a numeric PID/PGID is forbidden. No private `libproc`
signaling API, including `proc_signal_with_audittoken`, may be the shipping
cross-version safety foundation. A direct-child handle experiment proves only
that scope. It cannot establish arbitrary shell descendant enrollment or safe
cold adoption after both manager and witness die.

M3 must produce a capability decision: either independently proven retained
native authority for the stated bounded scope, or **Commands disabled before
launch**. In the latter mode Files/Search may qualify independently; calls to
`run_command` refuse explicitly, status of uncertain prior work is `UNKNOWN`,
and `stop_job` refuses unsafe delivery and never reports “all stopped”. Do not
silently emulate completion, omit unknown jobs or advertise complete native
`run_command/job_status/stop_job`. Capability messaging and disabled-mode tests
must be part of the product, CLI and acceptance matrix. Preserve existing Linux
wire and historical spool behavior. Any Darwin-visible surface variation gets
its own reviewed expectation, not a rewritten Linux golden.

N5 proves only a 70.051-second foreground SSH experiment, eight heartbeats and
AC/closed-lid observations at the two endpoints. It proves neither continuous
lid state nor actual sleep, logout, FileVault preunlock or installed daemon
survival. Initial acceptance is awake, unlocked, tested user-domain access.
Do not alter Mac power settings, credentials, TCC grants/global prompts, login
state or permanent production launchd labels as prerequisites. An inaccessible
headless domain becomes a recorded blocked native gate; other work continues.

N6 process or direct-child counters are labeled with scope, sample epoch and
availability. No invented zero, sum of known descendants presented as a whole
job, or Linux cgroup empty-scope/OOM/IO guarantee. Log crash durability,
redaction, retention and multi-epoch completeness are new acceptance work.

## 3. Gates and automatic dispatch DAG

A gate is a signed-off ledger record containing exact inputs, source SHA,
reviewer identity, command/results, artifact hashes and cleanup outcome.
“Started”, agent prose, research feasibility and a successful SSH exit are not
PASS. Independent review verdicts are `APPROVE`, `REVISE` or `INCONCLUSIVE`.

| Gate | Required evidence | Releases |
| --- | --- | --- |
| G0 infrastructure | Current ref/product pins; clean owned worktree environment; trusted transport; executable supervisor and timeout/restart rehearsal; model/auth capability; locks and single-writer registry | Parallel design, harness and source dispatch after G1 |
| G1 design | R-ARCH approves contracts, path ownership manifest, disabled Commands behavior, test selection and scope/permission boundaries | M0 foundation and independently scoped lane implementation |
| G2 foundation | M0 contracts/path defaults, Linux focused regression, import isolation, reviewed interfaces | M1–M5 adapter wiring, M6 cross-component tests |
| G3 lane acceptance | Each lane's focused fake/unit, Mac native own-resource evidence, Pi Linux focused regression, independent review and cleanup | Automatic dependent work; approved commits enter integration queue |
| G-N2 | R-SEC exact-source authority review; either supported bounded Commands proof or approved disabled-mode implementation | Enabled Commands only on proof; disabled-mode product otherwise |
| G-P0 | Linux StopIntent counterexamples, wire/record compatibility and independent high-risk approval | Combined integration/release eligibility; not unrelated Mac development |
| G4 convergence | All selected initial-scope lanes accepted, G-N2 decision, G-P0, OS6 inventory, no unresolved source overlap or high-risk findings | One final Mac/Linux qualification campaign |
| G5 qualification | Mac native matrix and managed suite; Pi managed suite/coverage/matrix/hooks; independent final candidate review | Feature-branch publication only |
| G6 exact-SHA CI | Seven required GitHub checks, complete stable evidence on exact pushed SHA; fresh upstream sync | Conditional guarded integration; deployment remains separately gated |
| G7 release, if separately satisfied | Pi clean tree, current source/review/CI, fast-forward and quiet window, live smoke/rollback gate | Canonical deployment only; otherwise READY, NOT DEPLOYED |

```text
I0 supervisor/pins ── G0 ── design + R-ARCH/R-SEC ── G1
                                      │
                  ┌───────────────────┼────────────────────────┐
                  M0 foundation       P0 Linux safety          M6 harness/spec
                  │ G2                │ G-P0                   │
            ┌─────┼─────┬─────┬──────┤                        │
            M1    M2    M3    M4     M5 scaffolding             │
                  │     │             │                        │
                  └── M3 native proof │                        │
                        │ G-N2        │                        │
       M1 + M2 + M4 + M5 + (M3 proof OR disabled implementation)│
                        └─────────────┴──────── M6 acceptance ─┘
                                      │ + G-P0 + reviews
                                     G4 → G5 → G6 → conditional G7
```

M1 file access, M4 parser/metric availability, M5 packaging and M6 contracts
continue when N2 fails. M2 runtime plumbing does not wait for enabled Commands.
M3's native witness test depends on M2 authenticated IPC; its threat model and
unit model start at G1. P0 begins at G1 independently of M0. M5 renders package
and CLI fixtures at G1, integrating working adapters after G2/G3. M6 designs
acceptance and fakes at G1, then consumes lane commits. No failure permits a
combined release before G-P0. A narrower candidate is accepted explicitly as
Commands-disabled, never relabeled “full native compatibility”.

## 4. One-writer work packages and model allocation

Use one Mac branch/worktree per author: `native/20261011/<lane>-<run-id>` and
`/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011/native-workers/<run-id>/<lane>`.
These paths are **future targets**, not existing or installed workers. The
supervisor records the exact full path and branch before creation; if either
already exists, reconcile its owner rather than reuse it blindly.

All paths below are repository-relative. In a table cell only, abbreviated
production siblings inherit `src/binnacle/`: for example `application.py`
means `src/binnacle/application.py`, `features/commands/job_stop.py` means
`src/binnacle/features/commands/job_stop.py`, and `platform/contracts/` means
`src/binnacle/platform/contracts/`. Test and script paths are already complete.
G1 must expand these abbreviations before enforcing ownership. `new` means
proposed files, not observed implementation. Directory ownership includes its `__init__.py`
and future children except explicit exclusions. G1 expands every pattern into
an exact manifest. No source path may match two writers. Unlisted changes
require a ledger ownership assignment and reviewer impact check first. Requests
for another owner's file are patch proposals; only its owner applies them.

| Lane / priority | Sole writable source/config scope | Inputs → outputs | Model / effort | Prerequisites / independent reviewer |
| --- | --- | --- | --- | --- |
| I0 / P0 infra | New `scripts/mac_native_supervisor.py`, `scripts/mac_native_worker.py`, `tests/scripts/test_mac_native_supervisor.py`; private state and dispatch prompts | Pins, workflow, resource inventory → durable dispatcher, locks, event/result schemas, executable recovery | `gpt-6-astra` / high | Initial read-only reconciliation; G0 required before product dispatch; R-OPS |
| M0 / P0 foundation | `src/binnacle/config.py`, `application.py`, `server.py`, `platform/composition.py`, `platform/job_platform.py`, `platform/deployment_platform.py`, `platform/contracts/`; new `platform/darwin/__init__.py`, `platform/darwin/runtime_paths.py`; `diagnostics/` | Linux contracts, N1/N3 → explicit capabilities, lazy Darwin config and adapter selection, portable diagnostics | `gpt-6-astra` / high | G1; R-ARCH |
| M1 / P1 Files/Search | `src/binnacle/features/files/`, `features/search/`; new `platform/darwin/file_access.py` | Opened-root contract, N4 → descriptor traversal/open/write/search implementation, TCC errors | `gpt-6-astra` / high; security escalation xhigh | G1 design, G2 wiring; R-SEC |
| M2 / P0 IPC/service | New `src/binnacle/platform/darwin/service.py`, `ipc.py`, `generation.py`; `features/commands/job_client.py` | Runtime paths, N3/N4 and RPC v1 → authenticated RPC transport, manager/frontend lifecycle adapter | `gpt-6-astra` / high | G1 design, G2 wiring; R-SEC plus R-OPS |
| M3 / P0 N2 | New `src/binnacle/platform/darwin/process.py`, `witness.py`; `features/commands/command_backend.py`, `command_execution.py`, `command_status.py`, `commands_server.py`, `tools/` | N2 counterexamples, M0 contracts, M2 IPC → disabled mode first, optional retained-authority backend and honest UNKNOWN | `gpt-6-astra` / xhigh; high for bounded corrections | G1 model, G2 disabled mode, M2 for native authority; R-SEC xhigh |
| M4 / P1 telemetry | New `src/binnacle/platform/darwin/metrics.py`, `service_logs.py`; `src/binnacle/observability/`; `features/commands/job_output.py`, `job_resource_history.py` | N6 evidence, resource/log contracts → scope/availability semantics, private logs, epochs/cursors | `gpt-6-astra` / high for log/crash safety; `gpt-6.1-sol` / medium for simple metric cases | G1 fake model, G2 adapters; R-SEC logs, R-QA counters |
| M5 / P1 package/CLI | `src/binnacle/cli.py`, `src/binnacle/deployment/`; new `platform/darwin/provisioning.py`; `pyproject.toml`, `uv.lock`, `MANIFEST.in` if needed, `.github/workflows/` | Linux CLI/unit pins, M0/M2 → ARM64 artifacts, user-domain install/doctor/help, marker/architecture config edits requested by owners | `gpt-6.1-sol` / medium; lifecycle questions to Astra high | G1 scaffolding; G2/M2 integration; R-PKG plus R-OPS |
| M6 / P1 test/acceptance | Existing `tests/` except I0's new test and lane-owned new tests below; `scripts/run_test_suite.py`, `scripts/os_stage1_inventory.py`, `scripts/check_architecture.py`, `scripts/gate_a_manifest.py`; generated OS inventory and new acceptance document | Existing suite/OS0 pins, lane receipts → collection portability, contracts, native harness/matrix, dual-host results | `gpt-6.1-sol` / medium for simple tests; `gpt-6-astra` / high for matrix/security test design | G1 harness; G3 adapters for acceptance; R-QA |
| P0 / P0 Linux | `src/binnacle/features/commands/job_stop.py`, `job_manager.py`, `job_owner.py`, `job_store.py`, `jobs.py`; `src/binnacle/platform/linux/job_identity.py`, `job_process.py` | Current Linux source plus read-only historical WIP comparison → reviewed StopIntent repair and manager adapter hooks requested by M2 | `gpt-6-astra` / xhigh | G1, independent Pi tests; R-LINUX xhigh, distinct from author |
| S / P1 integration | New execution evidence docs only; integration branch merges accepted commits, no competing source edits | Lane receipts and reviews → candidate, CI ledger, next-chat checkpoint | `gpt-6-astra` / high | Continuous intake; G4–G7 enforced; R-FINAL |

M0–M5 and P0 each exclusively own new
`tests/unit/core/test_native_<lane>_contract.py` and
`tests/integration/test_native_<lane>_adapter.py`, with lowercase lane names
(`m0`…`m5`, `p0`). M6 excludes those files; it owns separate adversarial tests
and all modifications to existing tests. Author-written tests are necessary
but not independent review. Any shared test helper or conftest edit belongs to
M6. The new `platform/darwin` directory's initializer belongs only to M0.
M0 contract changes are requested by M1–M4; M5 alone writes project markers,
dependencies and import-linter configuration. P0 alone wires shared job-manager
source for M2/M3; queue these patches behind its safety design. A lane may
split files within its namespace without transferring ownership implicitly.

Reviewers have separate read-only checkouts and evidence directories; no
reviewer may approve source it authored or repaired. R-ARCH/R-SEC/R-LINUX use
`gpt-6-astra` high/xhigh (N2 and StopIntent xhigh). R-QA/R-PKG use
`gpt-6.1-sol` medium for routine artifact/tests, escalating security findings to
Astra high. R-OPS and R-FINAL use Astra high. Record requested and observed
model/effort, CLI version and session ID. If the configured model cannot be
used, mark that job blocked, keep independent work moving, and do not silently
substitute a weaker model. Claude is not an assumed fallback: prior OAuth
refresh expired; absent a successful already-authenticated probe, use Codex.

### 4.1 Dynamic host scheduling

At least seven product lanes are independent at design/fixture level. This is
not an instruction to run seven heavy suites simultaneously. Begin with four
Mac CLI authors, at most two xhigh, plus one light evidence/review job. Every
60 seconds sample CPU/load, memory pressure, swap growth, disk and other users'
work; increase by one up to eight author/reviewer CLI jobs only while memory
pressure stays normal and sustained load remains below roughly 12 on the
user-specified 18-core machine. Reserve at least four cores and 32 GiB for the
OS and unrelated work. Reduce admission before throttling any existing owner.
These are initial scheduler thresholds to validate in I0, not measured limits.

Use a separate budget for local test subprocesses: at most eight test workers
total across this project, one heavy full suite, and one mutable launchd test
at a time. Each focused iteration normally uses one process. Pi starts with
one focused Linux test job, one reviewer CLI and no full suite overlapping
unrelated heavy workloads; at most two test workers until its coordinator
records spare capacity. Never terminate another workload to meet a deadline.

Acquire Pi cooperative locks in the documented order: shared
`mac-session.lock`, then exclusive `mac-heavy`, `mac-launchd`, or lane resource
lock. Mac supervisor retains corresponding locks across SSH disconnection;
Pi's transport lock alone cannot protect a detached Mac child. Use Mac
`fcntl.flock` in the Python supervisor, not an assumed Homebrew `flock` command.
Record owner nonce, host/boot epoch, process birth identity and lease; a numeric
PID/expired timestamp alone never authorizes lock stealing or process killing.

## 5. Lane test cards and bounded cleanup

Every card starts with: re-read status/refs/worktrees, validate exact parent
and ownership, `uv run scripts/dev.py doctor`, locked dependencies, native
host/build/UID/domain/capabilities, active locks and free resources. Capture
`--collect-only` for selected nodes, then run only their minimal affected set.
Each failure produces a reproducible test, diagnosis, scoped fix and rerun of
that case plus affected neighbors. No full-suite loop during authoring.

All native tests use private random roots, non-production label names such as
`com.binnacle.native-test.<run-id>.<nonce>`, private sockets and explicit lifetime
bounds (normally 120 seconds, 30 seconds cleanup). A parent holds trusted child
handles until reaped. Test manifests list exact roots, labels, descriptors,
process/witness capabilities, nonce and source hash before side effects.
Cleanup uses those capabilities and exact labels only. If authority is lost,
quarantine the resource and report `CLEANUP_BLOCKED`; never recover by `pkill`,
PGID enumeration or deleting a possibly foreign endpoint. This is a gate
failure, not positive cleanup. Prefer helpers with their own bounded lifetime
and retained test-parent witness so the negative test is itself safely owned.

Mutable launchd validation is a separate explicit opt-in native harness,
outside the ordinary host-safe pytest population; I0/M6 review its allowlist
and manifest. Ordinary tests retain command fakes and the global safety net.
Do not globally disable `tests/conftest.py` to make native tests work.

### M0: platform/config and portable application

Preflight: inspect `platform/composition.py` (currently Linux-only), runtime
path contracts, config precedence and Linux factory exports. Freeze Linux
socket defaults, unit templates, RPC v1 and OS0 wire hashes before changes.

Fake/unit: blocked Linux imports, Darwin/unknown-host selection, explicit
settings without side effects, temporary HOME/XDG/config precedence, private
runtime-directory permissions, overlong AF_UNIX paths, missing capabilities,
Unicode paths and generation changes. Importing Core must not select Linux.

Mac native for G2: construct the real runtime-path adapter in an owned root,
verify directory permissions and Darwin selection without importing Linux.
Application/import contract tests use explicit fakes at this foundation gate.
Real Files/Search and service-adapter MCP calls with Commands disabled belong
to G3/G4 after M1/M2 deliver, not to G2. Cleanup closes root handles and removes
only the manifest root. Pi clone: existing pure-application, configuration,
server factory and OS independence focused tests. Output: versioned contracts
and G2 receipt, reviewed by R-ARCH; later native calls remain pending.

### M1: descriptor-rooted Files/Search

Preflight: choose an allowed temporary root outside protected Desktop,
Documents and other TCC areas; record filesystem case behavior and rg version.
The retained directory descriptor and configuration generation are authority,
not a later canonical pathname. Define allowed symlinks and moved/deleted-root
semantics before coding; use component-relative opens and checked descriptors.

Fake/unit: symlink/ancestor swap between check/open, root-alias retarget,
rename after open, missing leaf/parent, `..`, permissions, descriptor close,
case/Unicode collisions, atomic replace, concurrent edit and traversal budgets.
Model attacker replacement at every relevant boundary. `resolve()` alone
cannot pass the race tests. TCC-style denial produces stable permission errors.

Mac native: read/write/edit/list/search inside own root while swapping owned
symlinks and ancestor names; denied escaped object is never read or modified.
Search must consume authorized opened objects or an independently justified
descriptor traversal; passing a re-resolved path to rg reopens the race and
fails acceptance. Test rename/inode identity and fd leak count. No attempt to
trigger global TCC prompts; real protected-path denial can remain untested and
explicitly unsupported. Pi clone: existing Files/Search/alias/streaming tests,
Linux error and output equivalence. Output: N4 security review and cleanup.

### M2: launchd and authenticated AF_UNIX

Preflight: verify available `user/<uid>` or already-active `gui/<uid>` domain
without login/power changes; freeze owned label/root/endpoint identity. Render
absolute interpreter/program paths and bounded startup time. Capture inner
`launchctl` return code and stderr, not merely wrapper status.

Fake/unit: two-starter serialization; stale socket and lock replacement;
wrong peer UID, generation mismatch, replayed handshake, partial frame,
oversized frame, timeout, abrupt exit and protocol-version mismatch. State
precisely the cooperative same-UID trust model: same UID is not protection
against a malicious peer with all user access. Bind peer credentials plus
private authentication and generation to an already trusted endpoint.

Mac native: two owned starters, authenticated client RPC, stale endpoint
substitution, frontend restart while manager remains live, manager restart
invalidating old clients, cleanup after failed bootstrap. Verify readiness
through authenticated challenge, not socket existence or launchctl listing.
Close socket handles and boot out only the exact test label; verify no owned
helper/label/root remains. Pi clone: RPC v1, client errors, mixed-version tests
and unchanged Linux unit rendering; systemd commands remain faked. M2 requests
manager edits from P0 and composition edits from M0. Output: R-SEC/R-OPS receipt.

### M3: native Commands and retained witness

Preflight: write the authority proof obligation and public API support matrix
before any signal experiment. No native enabled mode until R-SEC approves
safe own-resource harness and ownership acquisition. Default is disabled.

Fake/unit: job/witness/manager generations; authenticated birth enrollment;
manager-only death with witness retained; witness-only death; both lost;
unenrolled late fork; escaped/reparented descendants; PID reuse; authority loss
between TERM/KILL; incomplete target-set closure; failed delivery and lost
acknowledgment. UNKNOWN must persist across restart and no test may translate
“cannot inspect” into “exited”. Disable admission before launching anything
when complete authority is unavailable.

Mac native: bounded owned direct-child/witness tests with retained outer test
parent, successful refusal after authority loss and no signals to unrelated
sentinel. Test manager restart with surviving witness separately from cold
restart with none. Require independently checked enrollment and target closure
before any full-job success. If no public safe mechanism proves those, finish
disabled-mode acceptance automatically and record enabled Commands NO-GO.
Pi clone: command policy, status/stop errors, old spool/RPC compatibility and
native pidfd refusal paths. Output: explicit G-N2 verdict, never extrapolated
from finite witness success. R-SEC is a separate xhigh reviewer.

### M4: logs and scoped metrics

Preflight: map each contract field to available native source, scope and error;
keep signal authority separate from metrics. Record per-process/direct-child
versus whole-job scope, units, final/sample distinction and access limits.

Fake/unit: absent metric versus zero, counter resets, partial samples, process
exit races, timestamps/units, epoch changes, dropped sequence, partial writes,
rotation, inode replacement, byte budgets, redaction, retention, crash replay
and stale cursors. No private API signaling or fabricated aggregation.

Mac native: owned child emits bounded stdout/stderr across frontend/manager
restart and rotation; verify inode, sequence/epoch, missing-record behavior,
redaction and positive close/removal. Compare measured own-process or child
counters against their declared scope. Unavailable complete job totals remain
`UNAVAILABLE`. Pi clone: journal/parser/privacy/resource-history tests and
Linux cgroup semantics. Output: field-level availability table and R-SEC log
review; N6 whole-job equivalence remains unproven unless new evidence exists.

### M5: ARM64 packaging, CLI and installation

Preflight: confirm `uname -m`, locked Python/uv, FastMCP/MCP pins from current
lock (research named FastMCP 4.1.0/MCP SDK 2.3.0; verify, do not overwrite newer
reviewed pins), build tools and writable fixture. No release credentials.

Fake/unit: CLI help, platform routing, Linux unit-byte preservation,
launchd/plist rendering, absolute executable path/quoting, config permissions,
read-only doctor, dry-run/adopt/refuse/backup rules, failed install rollback,
uninstall refusing foreign labels and disabled Commands messaging.

Mac native: build sdist then wheel, install wheel into fresh native ARM64
virtualenv outside source imports, run CLI/import/Files/Search smoke, install
and remove only random user-domain fixture labels. Prove actual service
readiness, intended signal/liveness handling and stdout/stderr behavior; an
import success is not a service smoke. No sudo/system daemon, permanent
Binnacle label, release tag or PyPI upload. Pi clone: packaging artifact/CLI
and Linux install rendering regressions. Output: hashed artifacts, clean
install receipt and R-PKG/R-OPS review. PyPI publishing remains a separate
release operation; do not modify publish credentials/workflow policy to pass.

### M6: contracts, collection and acceptance harness

Preflight: inventory existing tests and dependencies. Current full pytest on
Mac cannot pass honestly before runtime support exists. Capture collection
failures by cause; fix eager native selection at its owning source boundary.
M6 may not replace every backend with a fake or mark all integration tests off.

Fake/unit: contract/middleware/auth/visibility tests against explicit fake
backends, import denial, deterministic platform capability selection; safety
harness refuses unowned resources. Test ledger/replay metadata only where it
belongs to M6; I0 owns supervisor implementation tests.

Mac native: real Files/Search/CLI and supported service/Commands mode matrix,
with separately labeled fake and native outcomes. Require existing Linux
four-profile 8/6/6/8 raw wire/ownership contract via
`tests/contracts/test_os_stage1_wire_parity.py`; a Darwin disabled surface gets
explicit additional cases. No Linux golden regeneration to conceal a defect.
Use precise `linux_native`, `darwin_native` and opt-in resource markers only
after M5 registers them; unknown markers fail. Linux-only skips require an
actual platform dependency and reason. Pure mocked system tests should run on
both hosts. Unexpected skip/xfail/empty selection is a gate failure.

Pi clone: run exact Mac-authored commit in independent environment, existing
contract and affected regression modules. At convergence validate both runner
lanes, including ordinary-process `no_xdist`, and audit collected/run/skipped
node lists against baseline. Output: acceptance matrix and G4/G5 evidence.

### P0: Linux Stage1 StopIntent, separate safety gate

Preflight: inspect then-current Linux source and quarantined WIP read-only;
start fresh from reconciled base. Never blindly cherry-pick `27a6888`.

Fake/unit: admission-before-signal, durable StopIntent before delivery,
marker write failure both before/after signal, partial delivery, crash/store
barriers, manager generation, racing stop/reaper, retained pidfd loss,
TERM-ignoring descendants after leader exit, unknown closure, retention,
legacy records/RPC and mixed-version writers. No stale numeric-PID fallback.
Conservative behavior changes require explicit compatibility review; changing
expected results merely to bless failure is not a repair.

Mac: portable state-machine fakes and unavailable-Linux-capability refusal,
never a claim of native pidfd coverage. Pi independent clone: real bounded
owned Linux child/pidfd cases and focused stop/reaper/manager regression;
cgroups only in positively owned scopes, never production services. Preserve
Linux v1.0.1 MCP/RPC records, unit templates and stable manager restart gate.
R-LINUX independently attempts counterexamples at exact SHA. Output: G-P0
APPROVE or blocking INCONCLUSIVE; unrelated Mac lanes continue.

## 6. Upstream synchronization and exact-commit integration

I0 captures `source_base`, `github_master`, local master, Pi checkout HEAD,
loaded MCP source, manager generation, lockfile hash, tool versions and
research hashes separately. Pi must supply its actual paths and read-only
runtime doctor/provenance evidence; no Pi production path is invented here.
Unknown production state blocks G0 product dispatch, not read-only planning.

Run the sync gate before **every stage dispatch**, after upstream changes,
after worker commits, before combining patches, before integration, before
feature push and before any guarded release/cleanup. A webhook/poll (60-second
interval with backoff) only detects drift; the synchronous gate decides safety.

```bash
# From the owned coordinator checkout; inspect before changing any ref.
git status --porcelain=v1
uv run scripts/dev.py worktrees --json
git remote -v
git config --get-all remote.origin.fetch
git ls-remote --heads origin master proof-of-concept
# Explicit refspec avoids a stale tracking ref under narrow fetch config.
git fetch --no-tags origin refs/heads/master:refs/remotes/origin/master
git rev-parse HEAD refs/remotes/origin/master
git merge-base --is-ancestor refs/remotes/origin/master HEAD
```

No leading `+`, force fetch, `--prune` cleanup or force push. A rejected
non-fast-forward tracking update is a drift incident to inspect. Missing or
pruned feature refs do not mean source disappeared: preserve local SHA, bundle
and ownership ledger, inspect remote heads and restore only a uniquely owned
new branch if needed. Avoid relying on `@{upstream}` when unset/gone.

Remote calls can fail independently of local Git. Retry read-only checks with
bounded backoff; cached refs cannot satisfy a freshness gate. Continue tests
against pinned inputs while marking integration blocked. Connector ref reads
are useful corroboration but fetching/verifying commit objects is required
before implementation synchronization.

On master drift: stop admitting source writes, let active operations reach a
checkpoint, record dirty state and worker heads, invalidate affected downstream
receipts and resume unrelated already-pinned tests. The sole owner merges
new upstream into its clean branch, preserving commits, or authors a new
branch from the reconciled base and reapplies reviewed exact patches. Never
rebase someone else's/shared/published history, reset/stash their checkout or
silently overwrite conflicts. Freeze updated contract versions before dispatch
resumes. Re-run affected tests/reviews after the merge. Every new candidate SHA
invalidates final exact-SHA qualification and CI; tree-equivalent evidence may
be referenced for diagnosis but cannot substitute for final required checks.

### 6.1 Commit transport and candidate creation

Mac authors make ordinary commits with full hooks. Immediately before commit
refresh status/refs/worktrees and inspect staged paths against their manifest.
No `--no-verify`, `SKIP`, blanket `git add .`, copied `.venv` or hook downgrades.
If sandbox permissions prevent shared Git metadata writes, the trusted
coordinator may perform the exact scoped commit in that same owned worktree
after revalidation; it must not repair permissions globally or write into
another owner. In this authoring task, report any such boundary honestly.

Transport exact commits via a Git bundle plus SHA-256 over trusted SSH, or a
binary patch with both parent SHA and full patch hash. Pi creates independent
clones under its recorded private run root; clear all variables returned by
`git rev-parse --local-env-vars` before Git subprocesses in foreign repos.
Verify imported commit SHA, tree hash and patch hash. Pi never becomes a second
source writer. Failure diagnostics return to the Mac owner.

S creates a fresh integration branch from the freshly reconciled base and
merges accepted author commits in topological order. Merge conflicts are
assigned to the owning source author and reviewed; S does not improvise source
repairs. Preserve all original author SHAs in the ledger. Both the final merge
commit and its resulting tree receive independent source review. Do not
cherry-pick unrelated or unaccepted upstream work to obtain passing tests.

### 6.2 Converged qualification and publication

Run the minimal affected tests during iteration. After G4, run one complete
qualification campaign on the frozen candidate; repeated full campaigns are
justified only by new changes, failures or invalidated evidence:

```bash
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run python -m scripts.os_stage1_inventory --check
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
uv run python scripts/run_test_suite.py --seed 12345
uv run tox -e coverage-policy -- --seed 12345
uv run tox
```

Before G4 freezes the candidate, M6 runs
`uv run python -m scripts.os_stage1_inventory`, reviews the generated diff and
commits it with any required ownership-manifest updates; final verification uses `--check` and must leave a clean tree.
The managed suite runs on Mac and Pi Linux. The canonical coverage/full Python
matrix and unchanged gate policy run on Pi; Mac runs the supported native
interpreter matrix and native artifact cases declared in the acceptance
matrix. Missing required interpreters are a gate failure, not a skip-all pass.
`BINNACLE_TEST_WORKERS` reflects scheduler capacity; do not replace the runner
with direct full-suite `pytest -n`. Both mypy targets remain mandatory:

```bash
uv run --no-sync mypy --platform linux --cache-dir .mypy_cache/linux src/binnacle tests scripts
uv run --no-sync mypy --platform darwin --cache-dir .mypy_cache/darwin src/binnacle tests scripts
```

After G5 and fresh sync, push only the uniquely owned converged feature branch
using ordinary `git push origin "$candidate_branch"`; normal pre-push checks
still run. This future feature publication is distinct from this document's
explicit **no push yet** instruction. Watch exact candidate SHA, all attempts
and canonical `ci.yml` runs; require all seven named GitHub checks:

1. Code quality.
2. Tests / Python 3.10.
3. Tests / Python 3.11.
4. Tests / Python 3.12.
5. Tests / Python 3.14.
6. Coverage policy / Python 3.13.
7. Packaging / Python 3.13.

Use the repository CI evaluator's complete paginated, stable reread evidence,
issuer and workflow-suite matching. Optional CodeQL is not an eighth required
gate. CI failure routes the failing scope back to its owner; rerun that scope
first and then required qualification on the new converged SHA. A green older
SHA or unrelated workflow cannot authorize the candidate.

### 6.3 Master, production and cleanup

A linked worktree's local branch refs are shared with its repository; there is
no independent per-worktree `master` ref. A developer may fast-forward a local
master only in a clean explicitly owned coordinator repository when no other
worktree checks it out and the accepted target/ownership is verified. Never
move this shared repository's master from a feature worker. Such a developer
ref update is not Pi deployment, remote master acceptance or loaded code.

Guarded integration is authorized after G0–G6 and independent review, not as a
blanket unsafe operation. Protected GitHub master and `proof-of-concept` are
advanced only by the canonical Pi deployment flow, if its separate release
conditions and authority are satisfied:

```bash
# Only in the verified Pi production checkout, never a Mac author worktree.
.venv/bin/python scripts/deploy_smoke.py deploy "$candidate_sha"
```

Do not run this merely because development finished. Verify clean tracked
production tree (untracked only under `docs/`), current production/source
provenance, exact CI, fast-forward eligibility and quiet window. The gate owns
live smoke, rollback and atomic protected-ref updates. Dependency changes use
its locked sync/MCP restart behavior. Stable `binnacle-jobs.service` is never
restarted by this flow; active durable jobs block a separate manager restart.
If no separate production operation is satisfied, record READY/NOT DEPLOYED
and retain the accepted feature candidate. No PyPI publication is implied.

Cleanup applies only to this run's owned worktrees/branches with positive
owner identity, no running jobs/locks, clean state and HEAD already merged into
accepted master. Refresh inventory and refs immediately before cleanup. From
another owned checkout run `uv run scripts/dev.py worktree-cleanup PATH
--delete-branch` dry-run, then the identical command with `--apply` only if safe.
Use normal `git branch -d`; never `-D`, force reset, blanket prune or remote
branch deletion. A squash/cherry-pick equivalent whose original HEAD is not an
ancestor is preserved. Unknown, dirty, locked, unmerged or foreign work stays.

## 7. Eight-hour durable execution handoff

**No supervisor, background worker or service is installed by this plan.**
The coordinator records the current authorization window as `run_started` and
`deadline` in its pre-G0 receipt. Infrastructure time counts within those eight
hours; supervisor launch, a new chat, retries and resume never reset the clock.
Use the original request timestamp when available, otherwise the earliest
recorded coordinator intake and disclose that timing approximation. I0 must
implement and rehearse the following small supervisor before source dispatch;
script names below are proposed interfaces, not existing repository commands.
The task cannot honestly promise work after ChatGPT exits until that gate passes.

### 7.1 Required I0 executable interface and ledger

I0 creates the two scripts listed in its ownership row and a private run root:

```text
/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011/native-run-state/<run-id>/
  run.json             # plan hash, authorization, deadline, host/source pins
  owners.json          # exact file → one author, branch/worktree, lease
  events.jsonl         # append-only events, sequence, timestamp, prior digest
  ledger.json          # atomic snapshot derived from events
  jobs/<job-id>/       # prompt, CLI JSONL/stderr, session, receipts, artifacts
  evidence/            # hashes, reviews, native manifests, test/CI receipts
  locks/               # supervisor and resource locks
  NEXT-CHAT.md         # current DAG, active jobs, blockers, exact resume command
```

Use mode 0700 directories/0600 private files, fsync of event append and atomic
snapshot replacement, with one supervisor writer. Sanitize logs and never
copy credentials into evidence. A worker sends events to the supervisor rather
than editing its snapshot. Event/job fields include ID/attempt, owner, branch,
worktree, base/head/tree, upstream observation, dependencies, requested/observed
model+effort, session ID, start/deadline/heartbeat, subprocess handle, commands,
exit code, tests collected/passed/failed/skipped, artifact SHA-256, review,
cleanup, next action and failure reason. Terminal result is mandatory.

Job states: `QUEUED → RUNNING → CHECKPOINTED → TESTING → REVIEW → ACCEPTED`;
failures become `RETRYABLE`, `BLOCKED`, `REVISE` or `FAILED`. `TIMED_OUT` and
`LOST_CONTACT` are not success or automatic retry permission. A RUNNING lease
requires reconciliation against a retained handle/session before redispatch.
Supervisor restart rebuilds state from events and validates all live children;
uncertain identity fences that owner and preserves resources.

The script CLI must implement `init`, `preflight`, `run`, `status`, `resume`
and `checkpoint`, all accepting `--state`; `init` also takes `--plan`,
`--source-base`, `--hours`, `--started-at`; the latter is the original pre-G0
UTC start, never a newly generated resume time. `run` takes `--deadline-from-ledger`;
`resume` takes `--reconcile`; `checkpoint` takes `--reason`.
`preflight` is read-only except private evidence and fails closed. `run`
launches no source job until G0/G1 PASS. Prompts carry exact ownership, no
questions for routine choices, test card, inputs/outputs and hard stop rules.

Heartbeats every 15 seconds; stale after 90 seconds triggers inspection and a
visible ledger event, not killing by PID. Each CLI attempt gets 25 minutes,
a checkpoint request at minute 20, and one supervised continuation if there
is progress. Native probes have shorter card deadlines. Bounded retries (two
for transient tool/transport errors with 15/60-second backoff); repeated code
failure routes to author/reviewer with reproducer. Never endlessly relaunch an
unchanged failed prompt. Optional questions are resolved by documented narrow
choices; missing authority/model/auth is BLOCKED for that lane without waiting
for the user, while independent work continues.

I0 tests crash between event/snapshot writes, duplicate dispatch refusal,
worker timeout, completed-but-uncollected results, lost SSH, supervisor restart,
stale lease, deadline expiry and an intentionally failed lane with downstream
suppression. A harmless worker must keep heartbeating after the launching SSH
session disconnects, then be reattached and positively cleaned. This is new
infrastructure proof, not inferred from N5's old foreground experiment.

### 7.2 Concrete bootstrap, start and resume commands

These are commands for the authorized later coordinator. Run them only after
it has the necessary filesystem/transport access; this authoring sandbox does
not grant write access to sibling worktrees or shared Git metadata. Existing
trusted Pi executor uses SSH alias `mbp`, BatchMode, StrictHostKeyChecking and
ConnectTimeout=8. Never disable host-key checks or copy private keys.

Set a unique run ID and literal owned paths. I0's first read-only action must
refresh pins. A pre-G0 coordinator preflight records source/ref/production
observations, ownership and filesystem authority before any supervisor exists.
It selects the reconciled full base SHA, then creates I0's worktree through the
canonical helper. This bootstrap preflight does not claim full G0: G0 remains
closed until the implemented supervisor and recovery rehearsal pass. I0-only
infrastructure edits are authorized during this bootstrap; product dispatch is
still prohibited until G0/G1. The bootstrap helper itself must run under pinned
uv; a fresh SSH PATH can first obtain project uv through locked sync as the
Mac-first workflow describes. Do not change global uv/shell profiles.

```bash
run_id=native-20261011-01
project=/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011
plan_worktree="$project/mac-native-implementation-plan-worktree"
plan="$plan_worktree/docs/darwin-investigation/native-validation/MACOS-IMPLEMENTATION-EXECUTION-2026-10-11.md"
state="$project/native-run-state/$run_id"
infra="$project/native-workers/$run_id/i0"
umask 077
mkdir -p "$state/jobs/i0" "$state/cache/uv"
export UV_CACHE_DIR="$state/cache/uv"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# Bootstrap only this owned checkout, not another session's environment.
cd "$plan_worktree"
uv sync --locked --group dev
export PATH="$PWD/.venv/bin:$PATH"
./.venv/bin/uv run scripts/dev.py doctor
# Set reconciled_base from the pre-G0 read-only pin record; do not assume master.
: "${reconciled_base:?Full reconciled source SHA required}"
uv run scripts/dev.py worktree-create "$infra" \
  --branch "native/20261011/i0-$run_id" --base "$reconciled_base"
cd "$infra"
export PATH="$PWD/.venv/bin:$PATH"
export UV_CACHE_DIR="$PWD/.cache/uv"
mkdir -p "$UV_CACHE_DIR"
./.venv/bin/uv run scripts/dev.py doctor
codex exec -m gpt-6-astra \
  -c 'model_reasoning_effort="high"' \
  -c 'approval_policy="never"' -s workspace-write -C "$infra" \
  --add-dir "$state/jobs/i0" \
  --json -o "$state/jobs/i0/result.md" \
  "Read $plan. Implement ONLY lane I0 within its owned scope; preserve other work. Build and test the specified supervisor/worker interfaces, write the durable I0 checkpoint under the explicitly writable $state/jobs/i0, and do not dispatch product authors before G0/G1 evidence. Record actual model and session. The coordinator owns publishing shared run state." \
  > "$state/jobs/i0/events.jsonl" 2> "$state/jobs/i0/stderr.log"
```

This initial I0 call must itself run inside a verified durable terminal session
(e.g. existing `tmux`) launched by the trusted executor. If `tmux` is available,
create an owned session with `tmux new-session -s "binnacle-$run_id"`, run the
bootstrap inside it, and detach with its normal detach command. Verify from a
second SSH session using `tmux has-session -t "binnacle-$run_id"` and a fresh
heartbeat. Do not assume tmux is installed; if unavailable I0 may implement a
reviewed detached parent with redirected stdio and session separation, prove
SSH-disconnect survival, then use it. Merely appending `&` or receiving a job
ID is not sufficient. If neither is available, record infrastructure BLOCKED
and leave a runnable checkpoint, not a fictional background promise.

After I0 is committed, independently reviewed and G0 evidence is complete,
its scripts are executable in the owned infrastructure worktree. Restore
`authorized_started_at` from the pre-G0 receipt; do not replace it with current
time. `init` refuses an existing run or an elapsed deadline. Run inside the
proven durable session:

```bash
cd "$infra"
./.venv/bin/python scripts/mac_native_supervisor.py init \
  --state "$state" --plan "$plan" --source-base "$reconciled_base" \
  --hours 8 --started-at "$authorized_started_at"
./.venv/bin/python scripts/mac_native_supervisor.py preflight --state "$state"
./.venv/bin/python scripts/mac_native_supervisor.py run \
  --state "$state" --deadline-from-ledger
```

From a later chat or SSH connection, reconstruct the literal paths from
`NEXT-CHAT.md`, inspect status first, and resume only if reconciliation says no
supervisor already owns the run:

```bash
cd "$infra"
./.venv/bin/python scripts/mac_native_supervisor.py status --state "$state"
./.venv/bin/python scripts/mac_native_supervisor.py resume \
  --state "$state" --reconcile
```

A timed-out CLI can resume its exact recorded session (never global `--last`):

```bash
cd "$lane_worktree"
codex exec -c 'approval_policy="never"' \
  -c 'sandbox_mode="workspace-write"' resume \
  -m gpt-6-astra -c 'model_reasoning_effort="high"' --json \
  "$session_id" 'Reconcile the recorded checkpoint and ownership; continue only your authorized lane.'
```

Local `codex exec --help` and `codex exec resume --help` were inspected during
plan preparation. I0 must revalidate installed CLI syntax and actual model
access; N2 uses xhigh in the same form, packaging/simple tests use
`gpt-6.1-sol` medium. Resume cannot create a duplicate owner. The wrapper keeps
stderr and final result even when the CLI exits without a result file, and
produces a synthetic **failure** receipt rather than treating missing output
as completion. Supervisor owns cross-worktree Git operations; source agents
retain workspace-write/never approvals. No sandbox bypass flags.

### 7.3 Eight-hour schedule, triggers and next-chat checkpoint

| Window | Intended work | Automatic trigger / time-budget response |
| --- | --- | --- |
| 0–45 min | I0 pin/bootstrap/supervisor/auth/transport rehearsal; R-ARCH/R-SEC design intake | G0/G1 PASS dispatches lane owners; failures remain visible and independent read-only design continues |
| 45–120 min | M0 interfaces; parallel P0, M1–M5 designs/fakes and M6 harness | G2 PASS releases adapter wiring without waiting for manual chat |
| 2–4 h | Parallel focused implementation/native probes; Pi independent small regressions | Each commit triggers sync, reviewer and dependent ready jobs; N2 failure selects disabled path |
| 4–5.5 h | Repair review findings, integrate accepted commits, scoped reruns | No-progress lane gets one correction cycle then BLOCKED; unrelated ready lanes continue |
| 5.5–7 h | Freeze converged candidate, OS6, final Mac/Linux qualification and review | G4/G5 PASS allows feature push; do not publish incomplete candidate just to meet clock |
| 7–8 h | Exact-SHA GitHub CI, final evidence, conditional guarded integration if all gates satisfy | Otherwise preserve feature/worker heads and explicit blockers; never waive tests |

These are scheduling budgets, not promises that a safety proof or full matrix
will finish within eight hours. At 7 h 30 min stop admitting work that cannot
checkpoint safely. At deadline stop new jobs, let bounded owned probes clean
up, checkpoint writers and preserve unfinished branches. A task still running
is explicitly recorded with its heartbeat, deadline and monitor; the supervisor
continues monitoring that bounded task until result/timeout instead of silently
abandoning it. No unattended production action begins near expiry.

Every accepted commit, failure, upstream drift, session loss and gate change
updates `NEXT-CHAT.md`. It includes plan commit/hash, exact author/integration
SHAs, immutable input hashes, upstream/prod observations, running sessions and
resource owners, last heartbeat, test/review/CI receipts, blocked DAG edges,
next ready jobs, remaining budget, cleanup status and literal status/resume
commands. Pi periodically pulls sanitized snapshots over trusted SSH into its
private evidence root; it does not overwrite the Mac's authoritative ledger.
On reconnection reconcile sequence/hash and run ID before any dispatch.

## 8. Forecast failures, owner and concrete fallback

| Failure | Owner | Autonomous response and boundary |
| --- | --- | --- |
| Mac headless SSH disconnect, stale session or missing GUI domain | I0/M2 | Mac durable supervisor continues; Pi reconnects with trusted host key, reads ledger. If domain absent use already-accessible user domain or mark native service gate blocked; no forced login/power changes |
| SSH PATH reset, global uv mismatch or unwritable cache | I0 | Command-local PATH and project `.venv/bin/uv`; fresh locked sync per worktree; private cache. No copied virtualenv or global profile change |
| Locale/time/Unicode portability | M0/M1/M4/M6 | Monotonic deadlines, timezone-aware UTC evidence, explicit encoding and available locale; test DST/wall-clock jumps/case normalization with fixtures. Do not assume GNU `date`, `timeout` or `/proc` on Mac |
| Mypy Linux/Darwin target divergence | M0/M6, path owner | Run both targets with separate caches; typed capability lookup and fail-closed behavior. No weakening hook/types or blanket ignores |
| GitHub master drift, narrow refspec or pruned branch | I0/S | Explicit master fetch, fresh ancestry/evidence, preserve exact SHAs/bundles; owner-only reconciliation and affected re-review; network loss blocks publication only |
| Codex approval/write boundary or model unavailable | I0 | Use workspace-owned paths/cache, trusted coordinator for authorized shared Git writes, record exact denial. No bypass/escalation flags, duplicate writer or silent model substitution; other lanes continue |
| Claude OAuth expiry | I0 | Do not schedule Claude; use validated Codex session. No credential modification or unattended OAuth flow |
| TCC path denied or headless prompt would be required | M1 | Use approved owned scratch root, report permission limitation, test denial through fakes; no global prompt/grant or copying private user files |
| AF_UNIX peer mismatch, stale launchd endpoint/label or two starters | M2 | Refuse auth/generation mismatch, preserve questionable path, retire only proven-owned generation; retry bounded fresh fixture. Capture inner launchctl diagnostics |
| Lost manager/witness or retained Linux pidfd | M3/P0 | Fail closed UNKNOWN/refusal; durable stop intent/error; no PID/PGID re-adoption or signal guessing. Select disabled Commands if authority proof fails |
| Root path TOCTOU or descriptor exhaustion | M1 | Retain/open relative to authority descriptors; reject inconsistent objects, close deterministically and bound traversal. Stop release on demonstrated escape |
| Optional metrics absent | M4 | Typed `UNAVAILABLE` with reason/scope; keep Files/Search/other metrics functioning; no fabricated totals |
| Mac release service signal/liveness mismatch | M2/M5 | Reproduce with owned labels/children, diagnose authenticated readiness and actual exit; keep release blocked, never restart production labels |
| Wheel works in source tree but fails clean install/PyPI policy | M5 | Build sdist→wheel, inspect contents/architecture and isolated CLI; fix packaging owner scope. No upload, tag, credentials or policy bypass |
| Test or native cleanup failure | Lane owner/M6 | Preserve failure artifacts, reproduce smallest case, fix and rerun affected neighbors; quarantine unowned cleanup, invalidate dependent gates |
| CLI timeout, missing output or stalled worker | I0 | Inspect session/handle/branch and heartbeat, checkpoint/resume exact session with one writer; synthetic failure receipt, bounded retries, visible blocked state |
| Supervisor/Pi outage or lost receipt | I0/S | Mac event log remains authoritative; recover atomic snapshot/event tail and reconcile children; no automatic duplicate dispatch or assumption of completion |
| Eight hours exhausted or GitHub still pending | S | Durable checkpoint and explicit pending gates; no forced merge, false pass or silently unmonitored task |

## 9. Future acceptance matrix and completion definition

M6 will create a **separate future document**, not part of this one-file plan
commit, at
`docs/darwin-investigation/native-validation/MACOS-NATIVE-ACCEPTANCE-2026-10-11.md`,
with a machine-readable evidence index beside it. It must link to this plan
commit, external research hashes and actual immutable receipts. Do not create
empty “PASS” placeholders during planning.

| Acceptance IDs | Required matrix evidence | Gate |
| --- | --- | --- |
| A-INFRA-01…06 | Source/prod pins, transport, model/auth, single-writer, durable timeout/resume, unrelated-work preservation | G0 |
| A-CORE-01…04 | Import isolation, config/path permissions, Linux defaults, real Darwin bootstrap | G2 |
| A-FS-01…08 | Opened-root positive/negative/race/symlink/move/TCC/search/cleanup | M1 G3 |
| A-IPC-01…08 | Peer/generation/replay/two-starter/stale-endpoint/readiness/frontend restart/cleanup | M2 G3 |
| A-CMD-01…10 | Enrollment/authority/closure, manager/witness losses, escape/PID reuse, partial stop, UNKNOWN, disabled mode | G-N2 |
| A-OBS-01…07 | Scope/availability, counters, rotation/inode, epoch/sequence, redaction, crash replay, cleanup | M4 G3 |
| A-PKG-01…06 | ARM64 artifact, fresh wheel install, CLI, user fixture install/uninstall, service liveness, Linux unit parity | M5 G3 |
| A-LINUX-P0-01…10 | StopIntent ordering/persistence/races/crash/partial signal/descendants/pidfd/retention/legacy/mixed version | G-P0 |
| A-PARITY-01…05 | Linux 8/6/6/8 raw wire, schema/golden/spool/RPC, meaningful Mac disabled/enabled profile, collection/markers, OS6 ownership | G4 |
| A-FINAL-01…06 | Mac/Linux suite, coverage/matrix/hooks, native cleanup, independent review, exact-SHA seven CI gates, guarded integration disposition | G5/G6 |

Each row records requirement, owner/reviewer, exact source and host build,
fake versus native method, command/node IDs, artifact hash, result,
limitations, cleanup and invalidation rule. Results distinguish `PASS`,
`FAIL`, `INCONCLUSIVE`, `BLOCKED`, `NOT_RUN`, and justified `UNAVAILABLE`.
No overall pass percentage substitutes for a missing P0 requirement.

Implementation completion means all requirements of the explicitly selected
initial product mode pass on both hosts with independent source-bound review,
source ownership inventory and exact-SHA CI. Enabled full Commands and broader
power/session support remain NO-GO unless separately proved. Development
completion, protected integration, deployment and PyPI publication are distinct
ledger outcomes. This plan is ready to dispatch once infrastructure/design
gates are satisfied; it does not assert that those gates or implementation
have already completed.
