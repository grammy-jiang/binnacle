# Group 0 implementation design — Stable FastMCP 4 baseline — 2026-10-02

Status: **dependency change implemented locally; local gates passed; awaiting
independent review, CI, and production deployment**.

Parent control document:

- `docs/fastmcp-native-refactor-implementation-master-2026-10-02.md`

Architecture evidence:

- `docs/fastmcp-native-architecture-investigation-2026-10-02.md`
- `docs/platform-neutral-architecture-design-2026-10-02.md`

## 1. Purpose

Establish one reviewed stable FastMCP 4 baseline before Binnacle begins composition and
platform refactoring.

Pre-change direct runtime pin (the design/rehearsal baseline):

```text
fastmcp==4.0.0b5
```

Reviewed target for this design:

```text
fastmcp==4.0.10
```

FastMCP 4.0.10 is the latest stable FastMCP release as of 2026-10-02 and was published
on 2026-09-25.

Official sources:

- [FastMCP changelog](https://gofastmcp.com/changelog)
- [FastMCP 4.0.10 on PyPI](https://pypi.org/project/fastmcp/4.0.10/)

If implementation is delayed until after a newer FastMCP release exists, do **not**
silently replace 4.0.10 with the newer version.

Either:

1. implement the already-reviewed 4.0.10 baseline; or
2. perform a bounded changelog/dependency delta review and amend this design first.

## 2. Why Group 0 is separate

The architecture refactor intentionally relies on stable FastMCP 4 concepts:

- focused server composition;
- Providers;
- Transforms;
- visibility;
- Middleware;
- dependency injection;
- lifespan;
- ServerExtensions;
- Tasks;
- custom HTTP routes.

Binnacle currently runs a pre-GA beta.

Combining framework upgrade with composition/module/platform refactoring would make any
failure ambiguous.

The required order is:

```text
FastMCP stable upgrade
        |
        v
known-green Binnacle baseline
        |
        v
composition refactor later
```

## 3. Non-goals

Group 0 does **not**:

- introduce `create_server()`;
- mount focused child servers;
- add Providers or Transforms;
- replace `ClientToolVisibility`;
- introduce FastMCP Tasks;
- change middleware ordering;
- change auth behavior;
- move modules;
- introduce platform contracts;
- change durable-job semantics;
- change systemd/deployment architecture;
- change watchdog/tunnel architecture;
- add macOS support.

If a proposed change is not necessary to run the existing Binnacle behavior correctly on
the selected stable FastMCP, it does not belong in Group 0.

## 4. Upstream delta relevant to Binnacle

FastMCP 4.0.0 became GA after Binnacle's beta-5 pin and made the new MCP
`2026-07-28` protocol, extensions, dependency injection and related v4 surfaces stable.

Patch releases after GA include changes in areas Binnacle directly cares about.

Examples from the official changelog:

- 4.0.5 restored field-level strict validation behavior;
- 4.0.6-4.0.8 changed and then corrected visibility/completion/middleware interactions;
- 4.0.10 fixed task-enabled tool behavior behind transforms/CodeMode.

Binnacle does not currently use every one of these features, but the changes justify
re-validating:

- schema/input validation;
- visibility;
- middleware;
- client/protocol behavior;
- tool results;
- auth/HTTP boundaries.

This is why Group 0 is more than changing a version string even though preflight
evidence indicates no production source compatibility patch is currently required.

## 5. Pre-change Binnacle FastMCP dependency surface

### 5.1 Direct dependency pin

`pyproject.toml` declares:

```text
fastmcp==4.0.0b5
```

with a comment explicitly saying the beta pin should be revisited once 4.0 is stable.

### 5.2 Dependency contract

`tests/contracts/test_dependency_pin.py` pins the complete runtime dependency list and
the reason for each runtime dependency.

The FastMCP entry must change in the same implementation change as `pyproject.toml`.

### 5.3 Lock

The pre-change `uv.lock` contains:

- `fastmcp==4.0.0b5`;
- `fastmcp-slim==4.0.0b5`;
- `mcp==2.1.1`;
- `mcp-types==2.1.1`.

The implementation must preserve unrelated locked dependencies unless the stable FastMCP
requirement genuinely forces a change.

### 5.4 Code/tests coupled to FastMCP behavior

Important FastMCP-sensitive areas include:

- root server construction;
- static auth;
- request/tool logging middleware;
- client identity;
- client-specific visibility;
- all tool registration and ToolResult handling;
- in-memory Client contract tests;
- HTTP/ASGI integration;
- protocol/schema validation;
- deployment smoke client.

Group 0 validates these existing responsibilities but does not reorganize them.

## 6. Dependency-resolution rule

### 6.1 Do not perform an unconstrained fresh lock

Investigation evidence on 2026-10-02:

A temporary project with the same `pyproject.toml`, FastMCP changed to 4.0.10, and a
fresh lock resolution changed **43 package versions**, including unrelated packages such
as:

- cyclopts;
- pytest-randomly;
- mypy;
- tox;
- uvicorn;
- uvloop.

That would turn Group 0 into a broad dependency refresh and violates the one-axis rule.

### 6.2 Use the existing lock as the base

The reviewed resolution operation is conceptually:

```bash
uv lock --upgrade-package fastmcp
```

after changing the direct pin to 4.0.10.

Preflight evidence using a copy of the current lock:

```text
fastmcp       4.0.0b5 -> 4.0.10
fastmcp-slim  4.0.0b5 -> 4.0.10
```

Only those two package versions changed.

`mcp==2.1.1` and the rest of the lock remained unchanged.

### 6.3 Hard stop condition

During real implementation, inspect the lock diff before continuing.

Expected package-version changes:

- `fastmcp`;
- `fastmcp-slim`.

If unrelated packages change:

1. stop;
2. determine whether FastMCP truly requires the change;
3. do not accept unrelated opportunistic upgrades;
4. amend this design if the necessary dependency surface is larger than preflight
   evidence showed.

## 7. Preflight compatibility evidence

A read-only/temporary implementation rehearsal was performed on 2026-10-02.

Method:

1. create a clean `git archive HEAD` snapshot under `/tmp`;
2. change only the FastMCP direct pin to 4.0.10;
3. use the targeted lock resolved from the current lock;
4. update only the temporary dependency-pin expectation;
5. run FastMCP-sensitive tests;
6. run the repository managed full suite;
7. run the wheel-artifact clean-install smoke.

No production working-tree file was changed by this rehearsal.

### 7.1 Focused FastMCP-sensitive tests

Before updating the temporary dependency-pin expectation:

```text
89 passed
1 failed
```

The only failure was the intentional assertion that still expected
`fastmcp==4.0.0b5`.

No FastMCP API/schema/runtime compatibility failure appeared.

### 7.2 Managed full suite

After updating only the temporary dependency-pin expectation:

```text
parallel-safe lane: 1473 passed, 4 skipped
ordinary-process lane: 2 passed
total: 1475 passed, 4 skipped
```

This rehearsal used Python 3.13.

### 7.3 Distribution smoke

`tests/integration/test_wheel_artifact.py`:

```text
1 passed
```

### 7.4 Meaning of the rehearsal

The evidence strongly supports a dependency-only Group 0 implementation.

It does **not** replace:

- supported-Python matrix CI;
- coverage gate;
- real deployment smoke;
- current ChatGPT/tunnel path verification.

Those remain implementation acceptance gates.

## 8. Expected files to change

### Required dependency files

1. `pyproject.toml`
   - direct FastMCP pin;
   - update the obsolete "beta pin" comment to describe the deliberate stable pin.

2. `uv.lock`
   - targeted FastMCP resolution;
   - expected package-version movement limited to `fastmcp` and `fastmcp-slim`.

3. `tests/contracts/test_dependency_pin.py`
   - expected FastMCP direct requirement;
   - reason updated from "beta pin" to the stable-framework rationale.

### Current/normative documentation to review

1. `docs/agent-toolset-design.md`
   - it currently attributes active SDK-level MCP obligations to
     `FastMCP 4.0.0b5`;
   - update only after the same obligations are revalidated on the stable baseline.

2. implementation control documents
   - mark Group 0 status after successful integration/deployment.

### Production source expectation

No `src/binnacle/*.py` source file is expected to change.

If a production source compatibility patch is required:

- do not casually add it to the dependency update;
- characterize the failure first;
- split a narrowly scoped G0 compatibility step or amend the design.

The successful preflight makes a production-source change unexpected.

## 9. Historical documentation that must not be rewritten

Do not mechanically replace every occurrence of `4.0.0b5` in the repository.

Historical documents must retain the version actually observed at the time.

Examples:

- dated usage analyses;
- dated long-running/ChatGPT experiment reports;
- historical production measurements.

For example, a September report saying FastMCP 4.0.0b5 was installed is evidence, not
stale configuration.

Only living/current documents that claim the active baseline should change.

## 10. Atomic implementation sequence

### G0.1 — Record the pre-change baseline

Before editing:

- confirm branch/HEAD;
- inspect working-tree state;
- run `uv lock --check --offline`;
- record installed FastMCP/FastMCP-slim/MCP versions;
- confirm existing architecture/import gates are green.

No file changes.

Purpose:

- establish an unambiguous rollback/reference point.

### G0.2 — Change the direct dependency contract

Change together:

- `pyproject.toml` FastMCP pin -> 4.0.10;
- `tests/contracts/test_dependency_pin.py` expected entry/reason.

Do not touch production source.

At this point the old lock is intentionally stale.

### G0.3 — Perform targeted lock update

Update the existing lock using FastMCP-targeted resolution.

Immediately inspect the lock diff.

Expected version changes:

```text
fastmcp       4.0.0b5 -> 4.0.10
fastmcp-slim  4.0.0b5 -> 4.0.10
```

Hard gate:

- no unrelated package-version churn unless separately investigated and justified.

### G0.4 — Sync the development environment

Use the repository-supported locked sync.

Verify the imported versions at runtime.

Expected:

```text
fastmcp 4.0.10
fastmcp-slim 4.0.10
```

Do not introduce Tasks extras or other new FastMCP extras in this group.

### G0.5 — Run focused framework-compatibility tests

Run the FastMCP-sensitive contract/integration population first.

Minimum areas:

- dependency pin;
- protocol surface;
- complete tool-surface hashes;
- input validation;
- job output schemas;
- client visibility;
- ASGI auth;
- HTTP workflows;
- request/tool logging.

Failure policy:

- public surface/hash change is investigated, not automatically rebaselined;
- visibility behavior change is investigated, not worked around by broad new custom code;
- validation change is compared with the intended Binnacle contract.

### G0.6 — Run managed full suite

Run the repository-supported full test runner with the fixed seed.

Do not replace it with direct xdist because the no-xdist lane is part of the contract.

Expected based on rehearsal:

- no new failures attributable to FastMCP 4.0.10.

### G0.7 — Run distribution, quality and compatibility gates

Required before integration:

- pre-commit all files;
- pre-push hooks;
- coverage policy;
- supported Python tox matrix;
- wheel-artifact packaging smoke.

The supported matrix currently covers Python:

- 3.10;
- 3.11;
- 3.12;
- 3.13 through coverage-policy;
- 3.14.

The temporary rehearsal only proved Python 3.13, so the matrix remains a real gate.

### G0.8 — Revalidate current FastMCP-dependent design statements

After tests establish compatibility:

- update current/normative docs that incorrectly describe beta 5 as the active SDK
  baseline;
- do not alter historical reports.

The document update should state that the stable baseline was revalidated, not imply the
original historical check occurred on 4.0.10.

### G0.9 — Integrate through normal CI/deployment path

Use normal reviewed repository flow.

Because `pyproject.toml` and `uv.lock` change, the documented deployment flow will:

- sync the production checkout environment;
- restart the MCP service so the new locked environment is loaded;
- leave the stable jobs service running;
- run live smoke;
- roll back the checkout/environment on failed smoke.

Do not manually bypass the deploy flow.

### G0.10 — Post-deploy verification

Require:

- live server unit healthy;
- authenticated MCP tools/list works;
- representative real tool calls work;
- deployment smoke sees no traceback;
- tool_call/tool_result journal linkage remains healthy;
- performance/startup remains within the existing smoke policy;
- tunnel remains healthy.

Additionally, perform one read-only MCP call through the actual ChatGPT/Binnacle connector
path after deployment to confirm the product path that motivated the server.

A suitable check is a harmless `list_files` or `read_file` call.

## 11. Focused test command set

The exact implementation may use equivalent repository-supported wrappers, but the
minimum focused population should cover:

```text
tests/contracts/test_dependency_pin.py
tests/contracts/test_protocol.py
tests/contracts/test_tool_surface.py
tests/contracts/test_visibility.py
tests/contracts/test_input_validation.py
tests/contracts/test_job_schemas.py
tests/integration/test_auth_asgi.py
tests/integration/test_http_workflows.py
tests/integration/test_logging.py
```

These collectively exercise the FastMCP behavior most likely to drift during the upgrade.

## 12. Full convergence commands

Use the repository's canonical commands.

### Lock

```bash
uv lock --check --offline
```

### Managed full suite

```bash
uv run python scripts/run_test_suite.py --seed 12345
```

### Static/pre-commit

```bash
uv run pre-commit run --all-files
```

### Pre-push

```bash
uv run pre-commit run --hook-stage pre-push --all-files
```

### Coverage policy

```bash
uv run tox -e coverage-policy -- --seed 12345
```

### Supported Python matrix

```bash
uv run tox run
```

### Packaging

```bash
uv run pytest -q tests/integration/test_wheel_artifact.py --randomly-seed=12345
```

### Live read-only suite, after deployment

```bash
BINNACLE_LIVE=1 uv run pytest tests/live -q
```

Deployment itself follows `DEVELOPMENT.md` and `scripts/deploy_smoke.py deploy TARGET`.

## 13. Compatibility invariants

### 13.1 MCP surface

Must remain unchanged unless an upstream normalization is proven semantically identical
and explicitly reviewed:

- eight default tools;
- six ChatGPT-visible tools;
- tool order;
- descriptions;
- schemas;
- annotations;
- output schemas;
- instructions hash.

Do not update surface hashes merely to make a test green.

### 13.2 Visibility

Must preserve:

- default client sees all tools;
- modern ChatGPT identity sees its configured allowlist;
- legacy ChatGPT identity sees the same profile;
- hidden tool direct call is refused;
- unrelated clients remain unrestricted under current policy.

FastMCP's later visibility implementation is relevant to future Group 2, not a reason to
refactor visibility in Group 0.

### 13.3 Input validation

Must preserve:

- unknown argument rejection;
- required-field errors;
- numeric bounds;
- scalar type validation;
- current tool-error semantics.

FastMCP 4.0.5's strict-validation fix makes this an explicit upgrade risk area.

### 13.4 HTTP/auth

Must preserve:

- unauthenticated rejection;
- wrong-token rejection;
- authenticated initialization/calls;
- HTTP session behavior used by current integration tests.

### 13.5 Middleware/telemetry

Must preserve:

- request logging;
- tool_call/tool_result records;
- call/session/client correlation;
- current result-size/domain fields;
- no payload-content leak in size-only telemetry.

### 13.6 Durable jobs

Framework upgrade must not change:

- synchronous completion behavior;
- background handoff;
- job_status;
- stop_job;
- stable owner lifecycle.

Group 0 does not redesign jobs.

## 14. Change review checklist

Before committing, inspect the diff and answer all of these.

### Dependency diff

- [x] direct pin is exactly the reviewed stable version;
- [x] dependency reason no longer says "beta";
- [x] lock changed only expected FastMCP packages or every additional change has a
      reviewed necessity;
- [x] no new FastMCP extra was added.

### Source diff

- [x] no production source changed, or any compatibility patch was separately
      characterized and approved;
- [x] no architecture refactor slipped into Group 0.

### Contract diff

- [x] tool-surface hashes did not change unexpectedly;
- [x] output/input schemas did not drift unexpectedly;
- [x] visibility behavior remains pinned.

### Documentation diff

- [x] living docs reflect the stable baseline where appropriate;
- [x] historical evidence still records the original historical version.

## 15. Rollback design

### Before deployment

Rollback is simply the Group 0 commit/revision reversal:

- restore `pyproject.toml`;
- restore `uv.lock`;
- restore dependency contract/doc changes;
- `uv sync --locked --group dev`.

Because no data/schema migration is involved, there is no persistent application-state
rollback.

### During deployment

Use the repository deploy flow.

Its existing dependency-change behavior synchronizes the environment for the target
commit and, on failed live smoke, synchronizes the old commit's environment again.

The stable jobs service is intentionally not restarted by this deploy flow.

That is desirable here because Group 0 is an MCP framework dependency change; the job
manager does not need a FastMCP-driven lifecycle migration.

## 16. Stop-and-redesign conditions

Stop Group 0 rather than broadening it if any of these occur:

- targeted lock resolution changes unrelated dependency versions unexpectedly;
- stable FastMCP requires a production architectural change;
- tool-surface hashes change for reasons not understood;
- current client visibility cannot be preserved without redesign;
- HTTP/auth semantics materially change;
- supported Python matrix fails due to an upstream compatibility floor;
- clean wheel install requires unrelated dependency changes;
- live ChatGPT/tunnel behavior regresses.

For each condition:

1. characterize the smallest incompatibility;
2. determine whether it belongs to a separate compatibility sub-step;
3. update this design/master status before changing the implementation scope.

## 17. Parallelism

Group 0 is intentionally not parallelized.

Reasons:

- it changes the shared runtime framework and lock;
- every later group depends on the resulting baseline;
- parallel architecture branches created against beta 5 would immediately need
  revalidation/rebase.

Other unrelated repository work may continue, but no FastMCP-native architecture branch
should begin implementation until Group 0 is integrated.

## 18. Expected implementation size

Given current evidence, the core implementation should be very small.

Expected semantic edits:

- one direct dependency pin/comment;
- one dependency-contract entry/reason;
- targeted lock entries;
- small current-document status/baseline updates.

Expected production Python source edits:

```text
none
```

This small size is intentional.

The value of Group 0 is not code volume; it is creating a stable, validated framework
baseline for every later refactor.

## 19. Exit criteria

Group 0 is done when all are true:

- [x] Binnacle direct pin uses reviewed stable FastMCP 4;
- [x] targeted lock has no unexplained unrelated churn;
- [x] runtime imports the expected stable FastMCP version;
- [x] focused FastMCP-sensitive tests pass;
- [x] managed full suite passes;
- [x] pre-commit/pre-push gates pass;
- [x] coverage policy passes;
- [x] supported Python matrix passes;
- [x] packaging clean-install smoke passes;
- [ ] CI required checks pass;
- [ ] normal deploy flow succeeds;
- [ ] live read-only deployment tests pass;
- [ ] actual ChatGPT/Binnacle connector read-only call succeeds;
- [x] living docs/status are updated;
- [x] no architecture refactor was mixed into this group.

After these are satisfied:

1. mark G0 `done` in the master plan;
2. treat the stable FastMCP version as the architecture baseline;
3. re-read current root server code;
4. begin Group 1 implementation design.

## 20. Initial local implementation evidence — 2026-10-02

The local attempt uses branch `chore/fastmcp-stable-baseline`, based on
`77a04c045b74670172ae024fd108ed395979db7f`. It is uncommitted and has not been
pushed, merged, or deployed. Production services have not been restarted.

### Dependency and compatibility evidence

- Pre-change doctor: zero failures. Architecture check: 100 modules, zero
  forbidden reverse dependencies. Import Linter: all six contracts kept.
- Pre-change offline lock check passed. Installed FastMCP and FastMCP-slim
  were `4.0.0b5`; MCP and MCP-types were `2.1.1`.
- `uv lock --upgrade-package fastmcp` changed only FastMCP and FastMCP-slim
  package versions to `4.0.10`. No packages were added or removed. All other
  lock entries remain unchanged except Binnacle's direct requirement metadata.
- `uv sync --locked --group dev` completed. Runtime imports confirm both
  FastMCP packages are `4.0.10`, with MCP and MCP-types still `2.1.1`.
- All nine focused modules in section 11 passed: **90 passed**.
- No production Python source, tool-surface hashes, schema pins, visibility
  code, or validation code changed. No FastMCP extras were added.
- An isolated in-process Client probe confirmed list/call `resultType`,
  list `ttlMs=0` and `cacheScope=private`, and identical repeated listings
  across reconnects for modern default, modern ChatGPT, and legacy ChatGPT
  profiles. This was a local SDK probe, not a real ChatGPT connector call.

### Local gates

| Gate | Result |
| --- | --- |
| Offline lock check | Passed |
| Focused FastMCP compatibility | 90 passed |
| Managed full suite, seed 12345 | Parallel: 1 failed, 1472 passed, 4 skipped; ordinary: 2 passed |
| Pre-commit, all files | Passed |
| Pre-push, all files | Parallel: 1 failed, 502 passed; ordinary: 1 passed |
| Coverage policy, seed 12345 | Stopped at unit parallel lane: 1 failed, 409 passed; policy not evaluated |
| Supported Python matrix | Python 3.10, 3.11, 3.12 passed; Python 3.13 and 3.14 failed on the same glob assertion |
| Packaging clean-install smoke | 1 passed |

### Confirmed pre-existing blocker

The failing node is
`tests/unit/core/test_properties.py::test_full_match_agrees_with_the_stdlib`.
Hypothesis found path `.` with pattern `***`: Binnacle returns `False`, while
Python 3.13.5 returns `True`. The same assertion reproduces under FastMCP
`4.0.0b5`. Both `src/binnacle/paths.py` and the property-test module are
byte-identical to the base commit.

The empty-path special case accepts only exact `**` segments. The Python
reference also accepts a final segment of three or more stars. This is
unrelated to the FastMCP upgrade. Do not weaken the property test, clear its
failure evidence, or add the glob fix to the dependency change. Resolve the
prerequisite separately before claiming local convergence or committing G0.

Two new ChatGPT review sessions accepted the narrow implementation approach
and the dependency diff. The final review identified the same failing local
gates as a blocker to committing. These were static reviews of supplied
evidence; the reviewers did not execute tests or verify deployment.

### Documentation and remaining gates

The living toolset design records the stable SDK revalidation and preserves
its original check date. Historical reports retain their beta observations.
These two implementation-control documents were supplied as untracked files;
only their copies in the isolated worktree were updated. The original design
files and unrelated user-owned work were not modified by this session.

GitHub CI, the normal deployment flow, live read-only tests, and a real
ChatGPT to Binnacle read-only call remain pending. G0 is not done. G1 has not
started.

## 21. Continuation evidence — 2026-10-02

Prerequisite commit `50916ef261d6fe02297e9e61de79db63fa4e27c4` fixes the
pre-existing empty-path glob mismatch separately. Its focused/full suites,
Python 3.10-3.14 matrix, coverage, packaging, hooks, and fresh ChatGPT
read-only review passed. Section 20 preserves the original failed attempt.

The continuation branch is `chore/fastmcp-stable-baseline-resume`, based
directly on `50916ef`, in
`/home/grammy-jiang/Projects/binnacle-fastmcp-stable-baseline-resume`.
Primary production `master` stays at `77a04c0`. Both earlier worktrees remain
unchanged. Updating the primary checkout would trigger the running MCP
server's source watcher, so prerequisite integration is deferred to the
normal deployment flow.

### Transplant and baseline evidence

- The six approved G0 files were copied from the original evidence worktree.
  Before these control updates, all six copies were byte-identical and the
  four tracked-file diffs matched exactly.
- The continuation's clean baseline passed the offline lock check, the
  architecture check (100 modules, zero forbidden reverse dependencies), and
  all six Import Linter contracts. Both FastMCP packages were `4.0.0b5`;
  MCP and MCP-types were `2.1.1`. The prerequisite glob regression passed.
- The previously reviewed targeted lock was transplanted without a fresh
  resolution. Only FastMCP and FastMCP-slim versions change to `4.0.10`.
  MCP and MCP-types remain `2.1.1`; dependency edges, extras, and unrelated
  package entries are unchanged.
- `uv sync --locked --group dev` completed and runtime imports confirmed
  both FastMCP packages at `4.0.10`. No production Python source changes
  belong to G0; the glob fix remains an earlier prerequisite commit.

### Continuation local gates

| Gate | Result |
| --- | --- |
| Offline lock check | Passed |
| Focused FastMCP compatibility | 90 passed |
| Managed full suite, seed 12345 | Parallel: 1573 passed, 4 skipped; ordinary: 2 passed |
| Pre-commit, all files | Passed, including the two control documents |
| Pre-push, all files | Passed |
| Coverage policy, seed 12345 | 96 production modules; zero below target, zero errors; full measured coverage 96.30% |
| First supported Python matrix | Python 3.10, 3.11, 3.12, 3.14 passed; Python 3.13 hit the telemetry startup race below |
| Complete unchanged matrix repeat | Python 3.10, 3.11, 3.12, 3.13, 3.14 passed, with both managed lanes |
| Packaging clean-install smoke | 1 passed |
| Local SDK probe | Result metadata and profile-specific listing order stable across calls and reconnects |

Each matrix environment imported FastMCP and FastMCP-slim `4.0.10`, with
MCP and MCP-types still `2.1.1`. The four original tracked-file G0 changes
remain byte-identical to the reviewed old G0 worktree. Tool-surface hashes,
schemas, visibility, validation, middleware, and production source are
unchanged relative to the prerequisite baseline.

### Telemetry startup race observed during the first matrix

The first Python 3.13 matrix run failed only at
`tests/integration/test_job_telemetry.py::test_stop_escalation_is_visible_in_telemetry`:
the child exited on SIGTERM (`15`) instead of the expected SIGKILL (`9`).
That test uses a 50 ms warm-up and calls stop without confirming that the
child installed its SIGTERM-ignore handler. The related lifecycle test
already documents the same startup race and waits for handler readiness.
The telemetry test, fixture, helpers, and job implementation are
byte-identical to `77a04c0`.

The unchanged telemetry test passed in isolation. One complete unchanged
`uv run tox run` repeat then passed all five environments. No source, tests,
worker configuration, or skip rules changed. The first failed matrix log
and successful repeat are both retained. This separate test-flakiness risk
has not been fixed by G0 and must be disclosed during review.

### Evidence and remaining gates

Continuation logs, dependency/parity checks, protected-worktree snapshots,
and the first-failure investigation are retained outside the worktrees at
`/home/grammy-jiang/.local/state/binnacle/group0-resume-20261002`.

The fresh [read-only ChatGPT review](https://chatgpt.com/c/6abf780b-5cc4-83ec-8748-3aaaebc4d594)
approved the supplied G0 diff, design, and evidence. It reported one minor,
non-blocking finding: the existing telemetry startup race remains a CI
reproducibility risk. The reviewer did not execute tests or verify the
deployment. G0 does not claim to fix that race.

Independent review, GitHub CI, normal deployment, live read-only smoke,
and an actual ChatGPT to Binnacle read-only call remain pending. Primary
production `master` remains at `77a04c0`; no production service was restarted.
G0 is not done; G1 remains queued.
