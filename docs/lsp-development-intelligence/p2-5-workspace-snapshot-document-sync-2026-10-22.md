# P2.5 — Private workspace authority, disk snapshots and LSP document sync

Date: 2026-10-22, Sydney. This is a **private, default-unmounted** development
milestone, not a deployment, OS sandbox certificate or approval to publish
agent-facing semantic tools.

## Locked implementation and responsibilities

- Base: Binnacle private P2.4 process-owner commit
  `9beddf6f3a37e9b2719401c429c6a892b85dd45d`.
- External LSP: optional PEP-508 dependency on forked Microsoft multilspy
  commit `9203732e4e5f65cc1374b109110f7b6354d3d43b` and host-provided
  Pyright 1.1.413. Nothing is copied from upstream into Binnacle.
- `lsp_workspace_access.py` owns the independently-authorized source tree:
  host RootsSettings roots only, deterministic nearest Git root (including
  linked worktree `.git` files), provider marker root, optional explicitly
  enabled parent fallback, source type/size limits, hash snapshots, and
  fail-closed descriptor-relative `O_NOFOLLOW` traversal on macOS/Linux.
- `lsp_document_sync.py` owns disk-versioned client-side *document state*,
  **not** a second LSP protocol implementation. It uses upstream multilspy's
  low-level `notify.did_open_text_document`, `did_change_text_document` (full
  sync with monotonic versions), `did_close_text_document`, and
  `send.definition`. Never call upstream's implicit-disk-reading high-level
  `open_file`/`request_definition` in the authorized code path.
- `lsp_authorized_session.py` is the single private composition boundary:
  pinned operator-configured roots -> `AuthorizedWorkspace` -> upstream
  P2.4 one-shot `PrivatePyrightProcessOwner` -> `AuthorizedDocumentSession`.
  It starts no provider at import, creates no MCP tool, and owns no P2.6
  registry or shared resident session state.

## Correctness and resource gates

- All target/document paths remain within one authorized Workspace, with
  no-follow descriptor walks for each parent and target. Result URIs are
  independently re-admitted and their ranges checked against current target
  disk contents. Unauthorized/non-file/off-root paths are refused; no private
  source content is appended to the returned definition payload.
- Reads are bounded at 2 MiB per source; current Pyright profile admits `.py`
  and `.pyi` only. Non-UTF-8/binary source is refused. The initial open and
  every request begin from an on-disk snapshot with SHA-256, inode, device,
  ctime and mtime. A stable descriptor is independently checked against its
  current relative path before returning data.
- Request source and definition targets are revalidated after the response.
  Disk changes, invalid UTF-16 ranges, or changes during a request yield an
  explicit stale/error, *never a fresh-labeled success*. There is no hidden
  retry. `didChange` sends full contents and increases a per-file version.
- Caller supplies 1-based line/column and an exact expected identifier; the
  code validates that identifier **at** the cursor and converts Python
  codepoint offset to negotiated UTF-16. It never selects an arbitrary first
  occurrence of an identically named symbol elsewhere on the line.
- Serial request/document operations within this one-shot context; default
  max 32 open documents and 64 definition results. Cancellation, timeouts,
  unknown buffer ownership and notification/close failures are bounded or
  poison the context. Cleanup attempts all document closes; provider lifetime
  and process tree remain owned by P2.4.

## Executed acceptance

MacBook Pro (macOS ARM64) ran real Pyright 1.1.413 with the pinned multilspy
fork and the P2.4 native-process regressions. Raspberry Pi and Sextant
(Linux ARM64) independently installed the same pinned fork from the lock and
ran the **same** P2.5 candidate and P2.4 suite in isolated worktrees.

| Native host | CPython | Result |
| --- | --- | --- |
| MacBook Pro | 3.13 | P2.5 + P2.4 + startup manifest **86 passed** |
| Raspberry Pi | 3.13 | Same candidate suite **86 passed** |
| Sextant | 3.13 | Same candidate suite **86 passed** |
| MacBook Pro | 3.10 and 3.14 | P2.5 focused native tests **25 passed per version** |

Tests establish actual `didOpen -> didChange(v2) -> didClose` on a real Git
worktree, unchanged source bytes across navigation, full disk authoritative
refresh, inline Unicode anchor handling, repeated token positions, stale
source and returned target, serialized same-session requests, no implicit
multilspy high-level file-read buffer, timeout/cancellation, failed notify and
close behavior, opt-in authority facade, idempotent one-shot teardown, and
existing P2.4 native process lifecycle/descendant observations. The normal
MCP application composition and tool list remained untouched.

Reproduce on an explicitly trusted host with an isolated worktree:

```bash
UV_PROJECT_ENVIRONMENT=.qa-p25 uv sync --locked \
  --extra development-intelligence-pyright --group test --python 3.13
export BINNACLE_PATCHED_MULTILSPY_QA=1
export PYRIGHT_LSP_TEST_BIN=/absolute/trusted/path/to/pyright-langserver
.qa-p25/bin/python -m pytest -q \
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

Ruff and formatting checks, Python 3.10-3.14 compilation, generated startup
manifest verification, and default-off import behavior are independent checks.

## Explicit limitations and outstanding gates

1. **Full P2.5 adversarial gate is still open.** An attempted dedicated suite
   with symlink/path-swap/TOCTOU adversarial file-system cases was blocked by
   the execution environment's safety controls. We did not re-submit the same
   blocked operation through a different command or host. Earlier standalone
   `lsp_workspace_policy` regressions include symlink and URI denial, but do
   **not** count as native adversarial validation of the new descriptor-based
   reader. The code deliberately rejects symlink traversal and revalidates
   dirfd identities, yet this must not be overstated as a complete proof.
2. **P2.4 repository-wide GitHub CI is RED** for baseline revision `9beddf6`
   ([run 39695678041](https://github.com/grammy-jiang/binnacle/actions/runs/39695678041)),
   despite passing private native tests. Failures include repository-wide
   lint/typing/coverage and Python matrix gates, with numerous historical P1
   fixture errors. That CI must be triaged and passed independently before a
   merged/deployed release. No CI green claim is made for this P2.5 branch.
3. **No provider OS sandbox or READ certification.** Pyright can create type
   stubs through server-side commands without workspace/applyEdit. Even
   descriptor-safe Binnacle source reading does not constrain what the
   Pyright process itself can scan, execute, access, write or download. The
   provider remains `explicit_trust_only` and must not analyze untrusted
   workspaces without additional OS-enforced controls.
4. **P2.6 is not done:** no shared long-lived Manager registry, single-flight
   cold starts, per-workspace resident lifetime, cooldown or idle eviction.
   P2.7 conditional FastMCP mount and P2.8 full regression/ship gate also
   remain separate. Returned definition targets are checked against current
   disk, but the provider's overall workspace indexing freshness is not
   independently proven. No public tool is exposed.

**Decision:** functionality and native portability of the *private* P2.5
workspace/document layer have evidence. Keep the security release gate OPEN
pending permitted TOCTOU adversarial tests, global CI remediation, and P3 OS
confinement. The next functional milestone after these private foundations is
P2.6, not an unreviewed production mount.
