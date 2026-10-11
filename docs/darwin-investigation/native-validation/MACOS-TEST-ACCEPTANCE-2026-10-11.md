# Mac/Linux native compatibility test acceptance plan

Date: 2026-10-11 (Australia/Sydney). Status: **PLAN; native product acceptance NO-GO**.
Branch: `plan/macos-native-tests-20261011`.
Base: `1ba2bf33e1791cd18f96984f4808b4863b89239c`.
The sole tracked output is this document.

## Authority, baseline and evidence

This pairs with the independently authored
[implementation execution plan](MACOS-IMPLEMENTATION-EXECUTION-2026-10-11.md).
That expected file belongs to another writer/worktree; this author does not
create or edit it. M0-M6 here are acceptance lanes. Reconcile their interfaces
with the parallel plan before implementation without weakening predicates.

The current user instruction authorizes eventual Mac-first implementation after
infrastructure and docs, autonomous parallel workers, source-bound independent
review, minimal affected tests per iteration, full suites after convergence,
and guarded merge/cleanup and Mac deployment **only when proven safe**. This
supersedes the older handoff's lack of future implementation authorization;
it does not convert unresolved research into approval. This documentation task
permits no source/tests/CI edits, subagents, global Mac changes, push, merge,
cleanup or deployment. All product commands below are for the later authorized
stage. Preserve unrelated sessions and production services.

Canonical contracts: [development](../../../DEVELOPMENT.md),
[testing](../../testing.md), [quality gates](../../quality-gates.md),
[Mac-first workflow](../../mac-first-development-workflow.md),
[CI](../../../.github/workflows/ci.yml) and
[hooks](../../../.pre-commit-config.yaml). Native FastMCP retains lifecycle,
Provider, Transform and Middleware responsibility. No replacement registry/router
or FastMCP Tasks substitution for durable jobs.

Pinned input directory:
`/Users/grammy-jiang/Projects/binnacle-macos-dev-method-poc-20261011/mac-native-plan-inputs/`.
Read `HANDOFF.md`, `CAPABILITY.md`, `RESEARCH-SUMMARY.md`; preserve their SHA-256
in the execution ledger. Read input digests:

| Input | SHA-256 |
| --- | --- |
| HANDOFF.md | `7c3859c183f6e2f8a3ab430a5ae4ca32776f5e7c1fc5c7f405f5324ae9303f19` |
| CAPABILITY.md | `ce0bc9ad44f2912580997f46f9dc6b94f520dfc5f648ab9f663c10b19204c51b` |
| RESEARCH-SUMMARY.md | `dec5d37cb7dfd7f3c2ce55c531e60914cae7f6bde616ab3f1e324e9d00227ef1` |

Immutable anchors:

| Evidence | SHA |
| --- | --- |
| Targeted report | `855749098c2960b13507c092c822bd695917a5a2` |
| Independent review | `2a4a03a1dac9e2f5caf81b37e6a2061b81029512` |
| Capability index | `3bad179314fdd88520cd0d44ad66fa20ffac53db` |
| Investigation plan | `6249d42417afb0901c6558cc6a293ba94f6d0b0f` |

Historical research source and isolated StopIntent WIP are not accepted fixes
or automatically the implementation baseline. Reconcile then-current reviewed
Linux source before adopting any candidate.

**Current full Mac pytest is NOT GREEN:** `UnsupportedHostOS` at collection
from the missing Darwin adapter. Linux-only tests also require explicit reviewed
markers and equivalent native coverage. This supplied baseline agrees with
`src/binnacle/platform/composition.py`; this author has not rerun full pytest.
Do not skip all tests, broadly ignore collection failures or claim the macOS
backend works from fake adapters or dual mypy.

| Boundary | Acceptance consequence |
| --- | --- |
| N1 | Native ARM64 Python/FastMCP primitives feasible; fake adapters prove no shipping native backend. |
| N2 | Full job ownership after unrecoverable witness loss is **INCONCLUSIVE**; full Commands acceptance blocked. |
| N3/N4 | User-domain launchd, private IPC and descriptor roots feasible with explicit same-UID/session constraints; product lifecycle unproved. |
| N5 | Only observed 70.051 seconds, 8/8 SSH foreground heartbeats, AC and lid closed at both endpoints. No actual system sleep, logout, preunlock or continuous intermediate lid observation. |
| N6 | Finite own-service logging feasible; whole-job cgroup metrics unavailable. Process/direct-child samples cannot substitute for totals. |

## Selection, skips, parallelism and ownership

Existing paths/nodes below were verified at the base via `rg --files tests` and
`rg -n '^def test_|^async def test_'`. They are regression anchors, not claims
of current pass results or native coverage. Table scenarios are requirements,
**not invented existing pytest names**. Before each iteration use `rg` to select
actual affected nodes at the candidate SHA; add the smallest missing test.

Every reviewed Linux-only skip must record exact node/parameter, dependency
(`/proc`, pidfd, cgroup, systemd or hardware), reason, reviewer/SHA, native
replacement and capability impact. Register explicit platform markers before
use; unknown markers are errors. Do not mark an entire portable directory
Linux-only, skip Darwin failures or count xfail as support. Synthetic Linux
boundary tests safe on Mac still run. Full Mac collection must finish without
missing-adapter exceptions or unreviewed skips. Equivalent native coverage must
exercise real Mac-owned resources, not solely fake adapters.

Retain the managed Linux full suite's parallel-safe and ordinary-process lanes.
`no_xdist` means ordinary process, not exclusion. Allow xdist only for fixtures
with independent roots, ports, process authority and no shared singleton state.
Native launchd/witness/IPC lifecycle tests run sequentially under locks; start
Mac full runs with `--workers 1`. More workers require reviewed independence,
with native service nodes kept in the ordinary lane. Preserve autouse host
mutation guards; launchctl requires a separately reviewed owned native harness,
not disabling global safety for all pytest.

Each real-resource case leases a random label, private mode-0700 root, socket,
spool and authenticated generation. Record UID/domain/boot/session, manager and
witness birth identities, child enrollment and exact paths before use. Cleanup
rechecks ownership, stops only enrolled owned processes, boots out only the
exact test label/domain, closes descriptors and removes only its leased root.
Assert helper/label/socket/root absence and unrelated sentinel/job survival.
Numeric PID, PID file, process name or pathname alone is not cleanup authority.
Lost authority means UNKNOWN/quarantine, never guessed PGID signals, broad
`pkill`, sweeping bootout or removal of a possibly active worktree.

Pi supervisor takes global shared `mac-session` then exclusive resource lock
(`mac-heavy`, `mac-launchd`, IPC or job lease), held through child termination
and positive cleanup. Mac-local authors must join the same scheduling contract
through the supervisor; Pi `flock` cannot fence an independent Mac worker. The
later harness must provide reviewed Mac-native locking; do not assume Linux
`flock` is installed on Darwin. Foreign Git fixtures must clear all variables
reported by `git rev-parse --local-env-vars` before child Git commands.

## M0-M6 acceptance matrix

Start with focused anchors, not full pytest/tox on each edit. Each lane needs
Mac native evidence and independent Pi regression at the same candidate SHA.

| Lane | Minimal existing regression anchors | Mac positive/failure acceptance | Linux preservation and exit |
| --- | --- | --- | --- |
| M0 platform/config/infrastructure | `tests/unit/core/test_platform_activation.py`; `tests/unit/core/test_config_loading.py`; `tests/scripts/test_os_stage1_native_boundaries.py` | Lazy explicit Darwin selection, unsupported OS refusal, no accidental Linux imports, captured config/root generation; retarget requires new generation. Native uv/Python/FastMCP startup and collection. | Linux selection unchanged; both mypy targets, Ruff, lint/import boundaries pass. Fake composition remains distinguished from native backend. |
| M1 Darwin Files/Search security | `tests/unit/core/test_os_independence_paths.py`; affected nodes in `tests/unit/tools/test_read_file.py`, `test_write_file.py`, `test_edit_file.py`, `test_list_files.py`, `test_search_text.py` | Real descriptor-rooted operations; symlink escape, ancestor/root replacement between authorization and open, moved opened object, missing target, filesystem case/Unicode and permission semantics. Ripgrep cannot reopen a replaceable pathname and escape authorized objects. TCC denial is explicit, never empty success. | Linux golden payloads, budgets and aliases preserved. Independent review binds opened-object/moved-object policy and TCC/entitlement limits to source. |
| M2 launchd/AF_UNIX | `tests/integration/test_job_manager.py::test_ping_reports_protocol_and_owner`, `::test_socket_permissions_are_private`, `::test_unavailable_socket_is_a_manager_error`; `tests/unit/core/test_job_client.py` | Own user-domain stable manager and separate frontend; authenticated IPC precedes readiness. Two starters, stale socket/lock inode, wrong peer/generation/nonce, replay, abrupt exit, reconnect, partial/oversized request. Frontend restart preserves manager/job identity. | Existing systemd units, owner semantics and v1.0.1 RPC unchanged. Private modes plus peer/generation auth required; document cooperative same-UID model, not hostile same-UID isolation. |
| M3 retained witness/Commands N2 | `tests/unit/core/test_os_job_identity.py`; `tests/integration/test_jobs_stop_paths.py`; `tests/integration/test_jobs_lifecycle.py::test_setsid_child_is_stopped_with_the_job`, `::test_pid_reuse_is_not_reported_as_running`, `::test_concurrent_stops_agree`; `tests/integration/test_os_job_rpc_cross_version.py` | Authenticated birth enrollment before execution; leader exit, escaped/reparented/TERM-ignoring descendants, manager crash with retained witness, witness loss, both lost, stale PID and forged metadata. Stop target-set closure; unrelated sentinel survives. Durable StopIntent precedes signal; crash/write/reaper races cannot create false success. | Independent Linux StopIntent safety approval, exact bidirectional RPC/spool and mixed-version retention. Full Commands blocked unless retained trusted witness enrollment and stop closure pass; otherwise disable unsupported commands or typed UNKNOWN, fail closed. |
| M4 logs/metrics | `tests/integration/test_job_manager_telemetry.py`; `tests/integration/test_log_privacy.py`; `tests/unit/core/test_resource_accounting_contract.py`; `tests/unit/core/test_job_resource_history.py` | Own launchd stdout/stderr; bounded bytes, open inode/rotation, restart epochs, gaps, truncation, disk/write failure, crash durability and redaction. Native own-process/direct-child counters include scope/units/time; whole-job CPU/RSS/peak/IO/OOM/empty-scope typed UNAVAILABLE, never zero. | Accurate Linux cgroups retained. Missing records mean incomplete logs; wire-shape changes require explicit version/capability review. |
| M5 ARM64 packaging | `tests/integration/test_wheel_artifact.py::test_distributions_are_publishable_installable_and_smokeable`; `tests/integration/test_cli.py` | Isolated arm64 locked install, sdist then wheel, hash-verified backend/runtime, entry points, native adapter imports and architecture/provenance. No Rosetta result labeled native. | Same locked artifact passes independent Pi installation. Build validation is not publication or production service install. |
| M6 native MCP/Chat | `tests/integration/test_auth_asgi.py`; `tests/integration/test_os_pure_application.py`; `tests/contracts/test_server_composition.py`; `tests/contracts/test_tool_surface.py`; `tests/contracts/test_os_stage1_wire_parity.py`; `tests/integration/test_http_workflows.py` | Real disposable native frontend: initialize, token rejection, session validation, discovery/call, Files/Search and supported/disabled Commands, frontend restart. Authorized actual Chat discovery and call to owned fixture correlate client/request/result/server epoch. | Three children, local inventory, raw aggregate multiplicity and profile surfaces 8/6/6/8 for accepted full support. ASGI/fake tests alone cannot pass native Chat. Restricted Commands requires explicit reviewed discovery/schema contract, never false full-support count. |

### Mandatory counterexamples

| Scenario | Required observation and recovery |
| --- | --- |
| Descriptor race / M1 | Barrier-controlled symlink/root rename during read/write/search never accesses outside-root content. Close authority; retry only with newly authorized generation. |
| Enrollment gap / M3 | Double-fork, setsid, late children and reparenting cannot outrun enrollment; otherwise reject topology or capability. Snapshot polling cannot prove historical membership. |
| Witness loss / M3 | Drop witness/journal: UNKNOWN, no blind signals. New manager cannot recreate authority from metadata; preserve orphan evidence and restrict operations. |
| StopIntent / M3 | Marker failures before/after signal, stop/reaper/manager races, each store/crash barrier, leader-exited TERM-ignoring descendants. Never claim stopped/finished without target clearance; replay durable intent under authenticated generation. |
| PID/epoch reuse / M2-M3 | Deterministic synthetic reuse plus real owned process turnover reject stale PID/PGID/boot/session/generation. Sentinel survives; no host-wide PID stress. |
| Frontend/manager split / M2/M6 | Kill only own frontend: manager/witness/child continue. Retained-witness manager reconnect authenticates. Both lost is UNKNOWN, not successful recovery. |
| Log/metric loss / M4 | Rotation, inode replacement, full/unwritable spool, truncated records and epoch gaps produce bounded incomplete logs/UNAVAILABLE totals; restore fixture storage only, never merge incomparable epochs. |

**N2 veto:** retained W→M→C evidence is not full cold recovery. A private
`proc_signal_with_audittoken` header/symbol or positive own-child signal is not a
stable public cross-build API guarantee. Review must inspect actual signal
authority, enrollment invariant, witness retention and loss. Any unproved complete
ownership leaves full `run_command/job_status/stop_job` NO-GO. Narrow mode is
acceptable only with reviewed refusal/UNKNOWN behavior; do not rewrite Linux
goldens to disguise unsupported native semantics.

## Host commands for later authorized execution

Use independently owned implementation/integration checkouts, never this plan
branch as a runtime target. Set `CANDIDATE_SHA` to an immutable full SHA and
verify `git rev-parse HEAD` equality on Mac and Pi. These are execution recipes,
not product test results from this author.

On **Mac**, bootstrap its own environment:

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv sync --locked --group dev
export PATH="$PWD/.venv/bin:$PATH"
./.venv/bin/uv run scripts/dev.py doctor
./.venv/bin/uv run scripts/dev.py worktrees
uname -sm
./.venv/bin/python -VV
./.venv/bin/uv --version
./.venv/bin/python -c 'import importlib.metadata as m; print({n: m.version(n) for n in ("fastmcp", "mcp", "uv")})'
./.venv/bin/uv run --no-sync python -m pytest -q tests/unit/core/test_config_loading.py --randomly-seed=12345
./.venv/bin/uv run --no-sync python -m pytest -q tests/integration/test_os_pure_application.py --randomly-seed=12345
```

Require native Darwin arm64, pinned local Python 3.13 and uv 0.12.24 at this base.
Handoff baseline: FastMCP 4.1.0 / MCP SDK 2.3.0; compare installed metadata to
candidate lock and record reviewed drift. Imports are prerequisites, not backend
acceptance. SSH zsh may reset PATH: use explicit checkout-local uv each time.
Use a private owned cache if necessary; never copy `.venv`, change global shell
profiles or loosen sandbox/TCC. A stale global uv is not the tool baseline.

During Python implementation run both targets and lint in the locked project:

```bash
./.venv/bin/uv run --no-sync mypy --platform linux --cache-dir .mypy_cache/linux src/binnacle tests scripts
./.venv/bin/uv run --no-sync mypy --platform darwin --cache-dir .mypy_cache/darwin src/binnacle tests scripts
./.venv/bin/uv run --no-sync ruff check src/binnacle tests scripts
./.venv/bin/uv run --no-sync ruff format --check src/binnacle tests scripts
./.venv/bin/uv run --no-sync lint-imports --no-logo
./.venv/bin/uv run --no-sync python scripts/check_architecture.py
```

Run changed-file pre-commit using actual affected paths. Python triggers still
run both mypy targets across `src/binnacle tests scripts`. Source-boundary changes
also regenerate/check OS6 inventory in the source author's checkout:

```bash
./.venv/bin/uv run --no-sync python -m scripts.os_stage1_inventory
./.venv/bin/uv run --no-sync python -m scripts.os_stage1_inventory --check
```

After convergence, **Mac** must pass full collection/runtime with the reviewed
skip register, final static/pre-push gates, packaging and sequential native harness:

```bash
./.venv/bin/uv run --no-sync python scripts/run_test_suite.py --workers 1 --seed 12345
./.venv/bin/uv run --no-sync pre-commit run --all-files
./.venv/bin/uv run --no-sync pre-commit run --hook-stage pre-push --all-files
./.venv/bin/uv run --no-sync pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
```

The native launchd/IPC/witness harness does not exist at this plan base. Record
its reviewed actual entry point/node list, lock and cleanup command before
execution. No fictional runnable script is specified here. Portable pytest
commands alone cannot satisfy native service or eight-hour acceptance.

**Pi→Mac** uses existing trusted `mbp`, bounded SSH and canonical supervisor lock:

```bash
state="$HOME/.local/state/binnacle/darwin-study-parallel"
mkdir -p -m 700 "$state/locks"
flock -w 12 -s "$state/locks/mac-session.lock" \
  ssh -n -T -o BatchMode=yes -o ConnectTimeout=8 \
  -o StrictHostKeyChecking=yes mbp 'uname -sm'
```

For mutation also hold exclusive resource lock through remote job and cleanup.
Transfer immutable commit/bundle or digest-verified patch, never mutable files
into another writer's checkout. Never copy keys into prompts/evidence.

On **independent Pi**, in its own same-SHA checkout, run focused changed
contracts first. At convergence keep all Linux gates:

```bash
export PATH="$PWD/.venv/bin:$PATH"
uv run scripts/dev.py doctor
uv run scripts/dev.py worktrees
git rev-parse HEAD
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
env BINNACLE_TEST_WORKERS=4 uv run tox run
uv run pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
```

Reduce workers for competing Pi sessions and record allocation. Tox environments
remain sequential; supported full matrix py310/311/312/313/314. Do not replace
the runner with direct full `pytest -n`. Only intentionally authorized read-only
production checks use `BINNACLE_LIVE=1 uv run pytest tests/live -q`; those verify
the deployed SHA, not an undeployed candidate. Never restart the stable jobs
service while durable jobs are active.

## Incremental, final and deployment gates

An iteration passes when the relevant failure/new case establishes its cause,
the smallest affected tests pass on the owning host, diff stays scoped and owned
resources are positively cleaned. Record failed attempts separately. Run
adjacent dependent contracts after interface changes. Broad suites follow
convergence, not every edit; affected type/lint gates still apply.

Final acceptance binds all requirements to one immutable candidate:

1. M0-M6 pass within declared capability limits; real Mac resources pass,
   collection completes, every Linux-only skip has independent review and native
   equivalent or explicitly unavailable capability.
2. Independent source-bound APPROVE for descriptor security, identity/signal/
   enrollment, StopIntent, launchd/IPC, log privacy/crash behavior, packaging
   and deployment. Self-tests do not grant review. Source changes invalidate
   affected approval; INCONCLUSIVE cannot be promoted by repeating weak probes.
3. Independent Pi two-lane full tests, fixed-seed coverage policy, pre-commit,
   pre-push, full supported Python matrix and packaging pass. Preserve Linux
   v1.0.1 MCP/RPC records, unit templates and active-job restart gate; OS6 checks.
4. Keep all **seven required GitHub CI jobs**: `Code quality`,
   `Tests / Python 3.10`, `Tests / Python 3.11`, `Tests / Python 3.12`,
   `Tests / Python 3.14`, `Coverage policy / Python 3.13`,
   `Packaging / Python 3.13`. Every job succeeds at the exact candidate SHA;
   cancelled, skipped or nearby-SHA runs do not qualify. Mac gates supplement CI.
5. Eight-hour checklist, positive cleanup and truthful discovery/docs pass;
   no false Commands or whole-job metric support claim remains.

For exact-SHA verification use
`gh api repos/OWNER/REPO/commits/BRANCH` to reconcile branch head,
`gh run list --commit "$CANDIDATE_SHA" --workflow ci.yml` to locate runs and
`gh run view RUN_ID --json headSha,status,conclusion,jobs` to inspect all seven
jobs. Substitute actual observed repo/ref/run, record URL/id/attempt and verify
`headSha == CANDIDATE_SHA`. Query target refs again before integration; Pi local
master may differ from GitHub. New merge/rebase SHA requires bound review/tests/CI.

The user authorizes eventual guarded merge, safe cleanup and Mac deployment.
Re-read status, refs and worktrees before each operation. Preserve dirty,
locked, unmerged or unknown work; `worktree-cleanup` dry-run must report safe
before `--apply`. Never remove another writer's work. Development completion is
not deployment. Only `.venv/bin/python scripts/deploy_smoke.py deploy TARGET`
may perform the canonical deployment with reviewed CI, fast-forward target,
clean tracked tree, quiet window, live smoke and rollback; no direct protected
branch push. The current deployment contract is Linux/systemd: **Mac production
release stays blocked until a reviewed native gate supplies equivalent launchd
reload, provenance, live smoke and rollback**. Do not run a Linux gate on Mac
and infer safety. Stable manager restart is separate from frontend reload;
locked dependency sync/restart and rollback must preserve durable jobs.

## Failure and recovery matrix

| Failure | Evidence/diagnosis | Recovery and re-entry |
| --- | --- | --- |
| Darwin mypy attr-defined | Capture target/cache/trace; pidfd and SO_BINDTODEVICE are not Darwin guarantees. | Typed capability lookup with fail-closed absence tests, both targets pass; no ignores or weakened hooks. |
| gh branch drift/stale CI | Compare remote API SHA, local refs and run headSha/attempt. | Reconcile in owned worktree, freeze new SHA and rerun affected review/tests/final CI. |
| PATH/stale uv/cache denial | Capture resolution/version/cwd/interpreter/doctor. | Own locked environment, explicit local uv/private cache; no global updates or venv copying. Doctor passes before native work. |
| SSH failure/disconnect | Connect rc, timeout, session/job ID, heartbeat age. | Trusted supervisor reconnect inspects lease/generation before retry; disconnect does not prove child exit. |
| Agent timeout/partial output | Retain log, commit/status and live-job identity. | Resume exact session or bounded inspection; one writer per scope. Never duplicate author before proving old process exited. |
| TCC denial | Safe path class, operation, errno; no private contents. | Explicit permission/unavailable result, readable own fixture; no automatic TCC/privacy changes. |
| launchd bootstrap/readiness | Inner launchctl rc/stderr, domain/label/plist identity; outer wrapper rc is not inner rc. | Repair only owned fixture; bootout exact own label, retry after absence verification. |
| IPC auth/stale endpoint | Peer/generation/inode and bounded request trace. | Reject, recover under owned lock/new generation; no unlinking foreign live endpoint or pathname-only trust. |
| PID reuse/enrollment gap | Identity epochs, target closure and sentinel outcome. | UNKNOWN/fail closed, restrict Commands; no numeric PID/PGID fallback. |
| Logs/disk/rotation | Offsets, durable sequence, epochs, redacted write errors. | Bounded incomplete response, repair fixture storage, verified replay; no fabricated complete history. |
| UnsupportedHostOS collection | Import chain/selection at candidate. | Reviewed Darwin binding or explicit disabled capability, focused collection then full suite; no broad skips. |
| Linux regression/review inconclusive | Preserve assertions/counterexamples. | Source repair or narrower native contract; quarantine WIP and block unsafe integration/deployment. |

## Eight-hour unattended checklist

This is a planned run, not a result or authorization to change power/login.
Begin after focused convergence and independent approval of the native harness.
Host outage or safety veto produces a partial/failed receipt, never a fabricated
pass. Time windows include cleanup; expensive final suites/CI may finish separately.

- [ ] 0:00-0:30 preflight: freeze candidate/input hashes, host authentication,
  jobs/worktrees, doctor, locks/budget, leases, exact commands/timeouts and
  rollback/cleanup authority.
- [ ] 0:30-1:00 baseline: native arm64 versions, collection/skip audit, supported
  profile discovery, own service readiness/auth, heartbeat/log epochs.
- [ ] 1:00-2:30 lifecycle: sequential two-starter, frontend replacement,
  retained-witness reconnect/loss, UNKNOWN on authority loss and sentinel
  survival. Positive cleanup between cases.
- [ ] 2:30-4:00 Files/logs: descriptor races, scoped TCC denial, rotation/crash
  barriers/redaction and accurate metric availability. No global settings.
- [ ] 4:00-7:00 sustained installed **test-owned** user-domain manager with no
  foreground SSH parent dependency: bounded jobs, independent authenticated
  heartbeats/status, resource/log budgets and generation continuity. Record
  actual duration and observed AC/lid/session state, never infer sleep/logout.
- [ ] 7:00-8:00 closeout: stop enrolled own jobs, bootout exact labels, verify
  helpers/sockets/roots absent and unrelated jobs intact, hash evidence and
  obtain independent receipt/gate summary. Cleanup failure blocks deployment.

Supervisor checks at least every five minutes for heartbeat freshness, lease
expiry, resource bounds and progress. Bound each remote command/case. Stop
admission on unexpected ownership, disk pressure, auth mismatch or unreviewed
host state. Timeout cleanup uses trusted authority only; absent authority means
quarantine. Retain failed attempts even when retry passes. Eight hours does not
prove indefinite availability, actual system sleep, logout or FileVault preunlock.

## Evidence ledger and document closeout

One append-only row per experiment/attempt links private immutable artifacts
and sanitized public summaries. Required schema:

| Group | Fields |
| --- | --- |
| Identity | experiment ID, M lane/scenario, PASS/FAIL/INCONCLUSIVE/NOT_RUN, UTC start/end, monotonic duration |
| Source | host checkout/branch, full candidate/base SHA, dirty diff digest, exact source/test nodes, input SHA-256/research anchors |
| Environment | host pseudonym, OS/build/arch, UID/domain/boot/session, Python/uv/FastMCP/MCP/ripgrep, lock digest, native vs fake adapters |
| Execution | literal redacted command/args/cwd, seed/workers, lock/lease IDs, timeout, rc, collection/pass/fail/skip counts |
| Authority | descriptor/root generation, socket peer/generation, manager/witness birth identity, enrollment/stop closure, sentinel |
| Capability | supported/restricted/UNAVAILABLE/UNKNOWN reasons, skip entry/reviewer, actual N5 observations |
| Artifacts | stdout/stderr/JUnit/trace path and SHA-256, privacy/redaction receipt, retention owner |
| Review/CI | independent reviewer/verdict, reviewed SHA/digests, CI headSha/URL/id/attempt/seven-job conclusions |
| Cleanup | before/after manifests, exact label/helper/socket/root absence, unrelated-job survival, rc, quarantine/rollback |
| Decision | predicate, limits, next safe action, integration/deployment vetoes; worker requested/observed model/effort and job/session ID |

Counts alone are not acceptance; link causal observations and authority.
Missing results are NOT_RUN; interrupted/unproved ownership is INCONCLUSIVE.
Never publish tokens, keys, sensitive contents or raw unredacted IPC.

This document task runs only changed-file markdownlint/pre-commit and diff
checks, then re-reads status/refs/worktree inventory and commits this path only.
No full product suite, pre-push tests, coverage or deployment runs. Initial
doctor found global uv 0.12.22 versus required 0.12.24 and missing local `.venv`.
An owned environment bootstrap using installed pinned uv failed at PyPI DNS;
these are environment findings, not native test results. Documentation tooling
can use installed hook executables with a private writable cache. Report final
lint and commit in the handoff; this plan claims no product test passes.

Document validation: changed-file pre-commit passed, including markdownlint,
secret scanning and spelling. Python/type/test hooks correctly had no matching
files. No product test suite was executed.
