# P2.4 — Private multilspy provider process ownership (2026-10-22)

**Decision: GO for the private P2.4 process lifecycle foundation only.** This
is **not** permission to mount any new public MCP tool, to treat untrusted
project code as READ-safe, or to deploy an enabled Pyright provider. P2.5,
P2.6, P2.7, P2.8 and the independent P3 security audit remain separate.

## Source and single-owner architecture

- Binnacle isolated branch `feat/lsp-p24-process-tree-20261022`, deriving
  from isolated LSP cleanup commit `7a59d69`. Live Binnacle is untouched.
- Optional runtime source: **exact** `grammy-jiang/multilspy` Git commit
  `9203732e4e5f65cc1374b109110f7b6354d3d43b` (PR
  [microsoft/multilspy#168](https://github.com/microsoft/multilspy/pull/168)).
  This is pinned through PEP 508 `project.optional-dependencies` and `uv.lock`,
  **not** by indistinguishable package version `0.1.1`. The wheel's published
  metadata records the exact commit. A standalone binary of Pyright **1.1.413**
  is supplied by the host, never installed or discovered by this runtime.
- Binnacle never reintroduces a Python `PyrightAdapter`, JSON-RPC engine or
  provider-specific file editor. Upstream multilspy's native
  `LanguageServer.create(... python_server="pyright" ...)` is responsible for
  wire protocol, requests, diagnostics, capabilities and low-level process IO.
- `lsp_process_owner.py` provides a **private one-session** Binnacle lifecycle
  context and strict host opt-in (`explicit_trust_only` + authorized absolute
  executable outside the project). It is not the planned P2.6 shared manager.
- `lsp_process_tree.py` provides POSIX-only process observations and a cleanup
  backstop. Its `psutil` dependency is imported lazily and installed only by
  the opt-in extra. All signals are constrained by **previously observed**
  PID + creation-time identities; no client-provided or trace-provided PID
  is ever signaled.
- Files were integrated in a distinct worktree to avoid overwriting another
  concurrently developing P2.4 branch. The prior private owner prototype was
  copied read-only and combined with the independently tested native tree
  observer and extra lifecycle regression tests. No live server files changed.

## Functional and failure behavior

- **Default-off:** ordinary Binnacle installation contains neither multilspy
  nor psutil, startup imports are inert, and the existing eight-tool inventory
  and published schemas are unchanged. The optional extra is an explicit
  host-operator decision.
- **Positive:** real Pyright 1.1.413 starts via multilspy, responds to
  navigation requests, shuts down and returns no retained JSON-RPC requests
  or live reader tasks. Two sequential sessions clean up independently.
- **Concurrency and close:** concurrent session attempts are refused pending
  P2.6's manager; body cancellation, body exception, active close, close
  *before* spawn and close *after* spawn while initialize is blocked are
  all tested. Failed initialization cannot silently become a READY session.
- **Process identities:** same-group children are observed and cleaned even
  if their parent exits first. Children starting in a new session, or
  calling `setsid()` after initial observation, are detected, cleaned where
  observed, and reported as `cleanup_unverified`; the owner refuses reuse.
  PID reuse is tested by a substituted creation timestamp.
- **Scope:** the executable must be an explicit absolute host-trusted path,
  outside the requested workspace after symlink resolution. Arbitrary argv/
  environment overrides are denied, as is wire-content logging.
- **Honest evidence:** `observed_clean` means observed process identities no
  longer run, NOT a proof of exhaustive descendant discovery. Provider exit
  evidence separately contains pending RPCs, parent status, task count,
  observed/remaining/escaped descendants and `containment_verified=False`.
  Unobserved escapes, owner-process crashes, transient writes and process
  namespace/cgroup enforcement require independent OS confinement research.

## Exact acceptance evidence

Identical provider-owner/process-tree source and focused native test corpus
were transferred by checksum, tested with real `pyright-langserver` 1.1.413,
and never launched from the production MCP service.

| Platform | Interpreter | Private P2.4 cases |
| --- | --- | --- |
| MacBook Pro, macOS ARM64 | CPython 3.10.22 | **24 passed** |
| MacBook Pro, macOS ARM64 | CPython 3.13.16 | **24 passed** |
| MacBook Pro, macOS ARM64 | CPython 3.14.8 | **24 passed** |
| Raspberry Pi, Linux ARM64 | CPython 3.13.16 | **24 passed** |
| Sextant, Linux ARM64 | CPython 3.13.16 | **24 passed** |

The native corpus includes real OS spawn, actual parent/child disappearance,
slow or blocked initialize, mid-flight close, late session escape, and real
upstream Pyright navigation. No mock PID is treated as proof of native cleanup.
The multilspy upstream fork separately completed **7/7 GitHub Actions jobs**
(including four native Windows Python 3.10/3.12/3.13/3.14 jobs), see
[run 39690294398](https://github.com/grammy-jiang/multilspy/actions/runs/39690294398).
That upstream CI proves **library portability**, not Binnacle's native
process-tree tests on Windows (Binnacle's process owner is POSIX-only).

Against a **fresh PEP 508 installed** multilspy extra, the combined private
P2.4 and previously failing upstream request-cleanup release-gate suite also
passes. Ruff lint and formatting, Python compilation, generated server startup
manifest, wheel build + exact provenance check and baseline MCP-tool
composition are separately enforced before acceptance.

Reproduce on an explicit trusted development host in an isolated worktree:

```bash
UV_PROJECT_ENVIRONMENT=.qa-lsp uv sync --locked \
  --extra development-intelligence-pyright --group test --python 3.13
export BINNACLE_PATCHED_MULTILSPY_QA=1
export PYRIGHT_LSP_TEST_BIN=/absolute/trusted/path/to/pyright-langserver
.qa-lsp/bin/python -m pytest -q \
  tests/integration/test_lsp_private_process_owner.py \
  tests/integration/test_lsp_owner_startup_close.py \
  tests/integration/test_lsp_owner_native_descendants.py \
  tests/integration/test_lsp_provider_tree_native.py \
  tests/integration/test_lsp_provider_tree_pyright.py
```

Do not set this opt-in on a normal production service. No command above
performs Binnacle tool registration or restarts its hosted server.

## Responsibility boundaries and next work

1. **P2.4 private lifecycle GO:** upstream library owns transport/process IO;
   Binnacle owns explicit host authorization, one private session, observed
   process-tree cleanup and fail-closed evidence. Unexpected escapes poison
   the owner. Unknown descendants are not assumed absent.
2. **P2.5 open:** workspace discovery, symlink/TOCTOU hardening, on-disk
   snapshots and ordered `didOpen/didChange/didClose` are incomplete.
   Existing `lsp_workspace_policy.py` is a narrow provisional pure guard.
3. **P2.6 open:** single-flight registry, shared resident processes, bounded
   parallel requests, active-request draining, cooldown/restart and idle
   eviction are not implemented by the one-session owner.
4. **P2.7–P2.8 open:** actual conditional FastMCP child mounting, service
   generation lifecycle/reload, 6/8-tool contract invariance and full
   coverage/architecture release gates remain to be implemented.
5. **P3 security open:** Pyright `pyright.createtypestub` can create files
   directly without `workspace/applyEdit`; opt-in `explicit_trust_only`
   is not READ security. Escaped or unobserved descendants require enforceable
   OS isolation before accepting arbitrary untrusted project trees.

Do not merge this branch into the running service or mark P5/P6/P7 released
based on private P2.4 tests alone.
