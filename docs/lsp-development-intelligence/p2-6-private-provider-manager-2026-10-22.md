# P2.6 — Private resident Provider Manager (2026-10-22)

**Decision: GO for private provider-manager functionality, not public rollout.**
All code remains isolated in the Binnacle LSP development branch. It neither
mounts new FastMCP tools nor starts a provider during ordinary Binnacle import,
configuration, startup or default installation. The live service is unchanged.

## Exact ownership and dependency

- Parent baseline is private P2.5 source commit `10a90e86a8aca8bf821913c6253d78657a0f8325`.
- The provider is *only* upstream multilspy `PyrightServer` from optional,
  PEP-508 Git-pinned fork commit `9203732e4e5f65cc1374b109110f7b6354d3d43b`
  (Microsoft [PR #168](https://github.com/microsoft/multilspy/pull/168)).
  The version string `multilspy==0.1.1` is **not** the dependency authority.
- Binnacle owns application admission, canonical Workspace + device/inode
  identity, host-operator profile fingerprint, resident registry, request
  concurrency, cooldown/eviction, and bounded shutdown. P2.5 continues to own
  disk snapshots and ordered `didOpen/didChange/didClose` through multilspy.
  P2.4 still uniquely owns native process creation, process tree observations,
  termination and `cleanup_unverified` evidence.
- Modules `lsp_provider_manager.py`, `lsp_manager_types.py`,
  `lsp_manager_cooldown.py`, `lsp_manager_eviction.py` and
  `lsp_manager_shutdown.py` define private runtime behavior, bounded failure
  bookkeeping, idle supervision, state snapshots,
  and cancellation-shielded cleanup respectively. `lsp_process_owner.py`
  publishes one read-only provider liveness witness; no client supplies a PID.
  No new Pyright subclass, transport, editor, SDK endpoint or MCP tool exists.

## Verified private runtime behavior

**Identity and startup.** One lazily started process serves the same canonical
Git worktree, root device/inode, exact trusted profile fingerprint, and one
manager/service generation. Twenty simultaneous fake-provider requests and ten
real Pyright navigation requests create only one process. Different worktrees
can coexist up to the configured `max_resident_servers` limit (1–8). Invalid
source bytes/positions are rejected before initiating a provider. Operator
RootsSettings and provider declarations are snapshotted on manager creation;
mutating the original objects cannot silently broaden this generation.

**Bounded concurrency.** A caller must pass the bounded pending-admission
limit before joining a startup. Waiting for cold initialization, global
concurrency slots, per-provider slots, and the LSP response have separate
finite deadlines. Individual startup cancellation does not abort an instance
being used by other callers. If the sole cold-start caller disappears, the
P2.4 owner is closed so an orphaned new provider cannot survive. Binnacle P2.5
intentionally serializes *actual document sync/query operations per
workspace* to maintain monotonically ordered versions; concurrent admission
must **not** be confused with concurrent LSP requests on the same document.

**Recycling and memory.** Idle providers are evicted asynchronously after an
explicit configurable timeout. At residency capacity, an unused LRU provider
must completely exit before the next provider is started; an active provider
cannot be evicted to satisfy another Workspace. Multiple 90-cycle fake
spawn/use/evict rounds leave zero tracked callers or retained provider tasks.
The event history is bounded to 64 records, and per-Workspace cooldown state
to 128 entries. Idle process death is proactively noticed by the sweeper.

**Failures and shutdown.** Startup failure, request interruption, actual
provider crash, and mid-query cancellation never silently turn into successful
results. **Only actual upstream failure/timeout** triggers exponential cooldown;
a verified client-initiated cancellation recycles the provider without adding
upstream failure history. A successful call resets prior failure history. Unverified
process cleanup is fatal to the *entire* manager generation: all other owned
providers are requested to stop and new launches are denied. Closing a manager
stops new admission, drains admitted calls for a bounded period, cancels
laggards, and closes each P2.4 owner. Concurrent close callers share one close
task. Cancelling the *waiter* for aclose does not cancel cleanup itself.
Shutdown returns honest counts and `cleanup_unverified` instead of assuming an
unobserved child is gone.

**Resource defaults:** 32 maximum pending calls, four global concurrent
slots, two per provider (document calls serialized independently by P2.5), finite
startup/queue/request/close deadlines, configurable idle timeout. Host feature
settings constrain resident process count; P2.5 bounds source bytes, open
files, and definition counts. These are *private defaults*, not benchmarked
production-size recommendations or a hard RSS/CPU quota. CPU/RSS sampling,
per-profile adaptive sizing and enforceable OS-level confinement remain
separate from this claim.

## Native evidence and reproducible tests

All native runs use the **same manager implementation**, isolated temporary
Git worktrees, Pyright **1.1.413**, and installed SHA-pinned multilspy. No
production Binnacle service was restarted or changed.

| Host | CPython | Private P2.4 + P2.5 + P2.6 cases |
| --- | --- | --- |
| MacBook Pro (macOS ARM64) | 3.13 | **133 passed** full P2.4–P2.6 native matrix |
| MacBook Pro (macOS ARM64) | 3.10 / 3.14 | **43 passed each** focused P2.6 suite on the final review fixes; earlier full P2.4–P2.6 baseline was 126 each |
| Raspberry Pi (Linux ARM64) | 3.13 | **133 passed** full native matrix |
| Sextant (Linux ARM64) | 3.13 | **133 passed** full native matrix |

P2.6 itself adds 34 deterministic fake-provider cases and nine real Pyright
cases. The real fixture demonstrates ten concurrent same-worktree calls,
actual process PID reuse, separate root identities, LRU eviction, idle
restart, disk-accurate `didChange`, stale rejection without spurious restart,
shutdown cancellation, and an actual owned Pyright process exit/cooldown and
recovery. The fake tests provide deterministic capacity, startup/queue
cancellation, timeout, crash, idle liveness, cleanup-uncertainty fail-close,
shutdown waiter cancellation, cross-event-loop refusal and memory/history
bounds. These counts do not claim native fuzz/OS sandbox testing.

Run on a trusted host with an isolated worktree and explicit private opt-in:

```bash
UV_PROJECT_ENVIRONMENT=.qa-p26 uv sync --locked \
  --extra development-intelligence-pyright --group test --python 3.13
export BINNACLE_PATCHED_MULTILSPY_QA=1
export PYRIGHT_LSP_TEST_BIN=/absolute/host-trusted/pyright-langserver
.qa-p26/bin/python -m pytest -q \
  tests/unit/core/test_lsp_provider_manager_p26.py \
  tests/unit/core/test_lsp_provider_manager_failure_p26.py \
  tests/integration/test_lsp_p26_real_provider_manager.py \
  tests/unit/core/test_lsp_authorized_session_p25.py \
  tests/unit/core/test_lsp_workspace_access_basic_p25.py \
  tests/unit/core/test_lsp_document_sync_p25.py \
  tests/unit/core/test_lsp_document_faults_p25.py \
  tests/integration/test_lsp_p25_live_document_sync.py \
  tests/integration/test_lsp_private_process_owner.py \
  tests/integration/test_lsp_owner_startup_close.py \
  tests/integration/test_lsp_owner_native_descendants.py \
  tests/integration/test_lsp_provider_tree_native.py \
  tests/integration/test_lsp_provider_tree_pyright.py \
  tests/unit/core/test_lsp_workspace_policy.py \
  tests/unit/core/test_r6w3_e1g_server_set.py
```

Targeted Ruff lint/format, mypy, Bandit, source compilation, generated startup
manifest, strict 500-line source/module gate, pinned wheel provenance and
ordinary MCP tool-surface tests are independent quality gates. A default
install does **not** pull in multilspy, psutil or activate the manager.

## Independent review and remediation

A read-only Claude Fable source review reported five actionable P2.6 issues.
All five were addressed before the final cross-host matrix above:

1. A redundant Manager-level timeout also counted time waiting for P2.5's
   per-document lock and could falsely mark a healthy Pyright process failed.
   That timer was removed; P2.5 still bounds the actual LSP request.
2. The cold-start abort is now shielded and bounded through P2.4 `aclose`;
   inability to certify the stop is converted into sanitized
   `provider_cleanup_unverified`, not an arbitrary upstream exception.
3. Client-aborted calls still recycle the instance after cleanup but do not
   count as upstream failures for exponential cooldown. Startup failures,
   genuine LSP timeouts and crashes retain their cooldown and fail-closed
   behavior.
4. Per-provider slots are acquired before the global slots to prevent one
   busy workspace's own queue consuming concurrency slots needed by others.
5. Unexpected idle-sweeper failure poisons the entire manager generation and
   stops resident providers rather than silently disabling idle recovery.

Additional regression coverage checks disabled-profile refusal *before any
source-file read*, queue limit before potentially expensive snapshot reads,
and escalating cooldown across consecutive startup failures. Ruff, mypy,
Bandit and strict module-size verification passed for the reviewed changes.
No claimed unit tests are proofs of OS sandbox confinement.

## Open security / deployment gates

1. **P2.5 native adversarial path-race/TOCTOU suite remains unverified.** An
   earlier attempted dedicated adversarial fixture was blocked by the
   execution environment's safety control, and was not replayed using an
   alternate host or command. Descriptor-relative reads and known synthetic
   fixture checks are not proof of a complete boundary.
2. **No provider OS sandbox or untrusted READ guarantee.** The Pyright process
   can directly create type stubs without `workspace/applyEdit`; trusted
   absolute executable and path checks do not confine its filesystem/network
   actions. Keep `explicit_trust_only`; perform P3 audit before public READ.
3. **P2.7 is not implemented.** No conditional FastMCP child mount, no
   application lifespan injection, no public `inspect_symbol`, and no agent
   permissions have changed. The manager is private and must be created per
   service generation with bounded `aclose` on shutdown/reload.
4. **P2.8 repository-wide CI is not green.** Previous P2.4/P2.5 Binnacle
   GitHub Actions runs showed Python matrix, coverage, Ruff/typing and
   historical P1 fixture policy failures. The new P2.6 branch must be tested
   separately and cannot be declared shippable until the full repository
   gates are reconciled. Do not fabricate a CI GO from private native tests.
5. A bounded resident count and eviction timeout do not prove a hard RSS,
   CPU, disk-write, or escaped-child limit. Those require separate policy and
   OS evidence. P2.6 cannot authorize untrusted provider execution.

**Next:** P2.7 default-off conditional child and lifespan ownership, followed
by P2.8 platform/coverage/contract gates and P3 provider trust audit. Keep the
current production eight-tool contract unchanged until explicit release GO.
