# P2.7 — Private conditional FastMCP child and owned lifespan

Date: 2026-10-22 (Australia/Sydney). **Private composition GO; public/P5 release
NO-GO.** This implementation is NOT deployed to any production Binnacle MCP
service and does not add the official `inspect_symbol` contract.

## Architecture and gate ownership

- Binnacle baseline is P2.6 commit `e8ab69f7a91572f44b205aee1c435e58d071a546`.
  Pyright is **only** the native multilspy adapter from SHA
  `9203732e4e5f65cc1374b109110f7b6354d3d43b` (Microsoft PR #168).
  No new in-binary Pyright subclass or JSON-RPC client was introduced.
- `create_application()` has a **code-injected, default-False**, private test
  argument `_private_lsp_preview_gate`. **Production `server.create_server()`
  does not pass this argument.** It is not a TOML setting, CLI flag, HTTP
  endpoint, environment variable, or available client tool.
- Only a code-approved review instance with all of: enabled feature,
  discovery enabled, approved `pyright` profile, `trusted_absolute` executable,
  `explicit_trust_only` and no unreviewed argv/env may mount the child.
  Otherwise the child does not register. An invalid opted-in executable profile
  is rejected instead of silently falling back to an unsafe provider.
- `lsp_preview_mount.py` isolates conditional mounting from the public app
  factory. When the private gate is False, `create_application` does not even
  import this helper. The new guarded startup-manifest entries remain safe
  to import with **no multilspy installed**; imports never start a process.
- `lsp_preview_server.py` implements one *review-only* tool,
  `lsp_definition_preview_private`, not a production API. The child FastMCP
  lifespan creates a new **P2.6** manager per service generation, but no
  provider subprocess before the first authorized request. Definition calls
  route exclusively through P2.6 -> P2.5 -> patched native multilspy.
  Results discard host absolute target URIs/paths, returning only bounded
  workspace-relative paths and LSP ranges. All errors are sanitized.

## Real MCP visibility and compatibility

- **Default/off:** no child at all in `tools/list` or direct tool lookup;
  existing eight-tool tool-map names/order/schema are byte-identical even when
  the operator config enables Development Intelligence but the code-driven
  release gate is absent. Identical byte payloads imply identical schema
  tokenization cost for the same tokenizer. Default installation imports no
  multilspy and starts no Pyright instance.
- **ChatGPT HTTP client:** a real JSON-RPC initialization with
  `clientInfo.name = openai-mcp(ChatGPT)` retains its existing **six-tool**
  allowlist and refuses direct private-preview calls, even inside the QA root.
  An unmatched review client can see the extra private tool only in the
  deliberately test-gated app. In-memory `Client(name=...)` is *not* used as
  a substitute for the HTTP session/client identity test.
- **Authorized review client:** FastMCP's real memory client and authenticated
  HTTP ASGI client (Bearer, `initialize`, MCP session ID, `tools/list`,
  `tools/call`) both invoked the preview. Repeated and six concurrent HTTP requests reused one
  real Pyright PID; ASGI lifespan exit ended the process, with no leaked
  P2.4/P2.6 requests. A new lifespan receives a new manager generation.
- **Failed/partial lifetime:** disabled profile, child-manager construction
  error, parent sidecar rollback, reentrant lifespans, cancelled client,
  timed-out cleanup, and unverified cleanup are exercised. Cleanup uses an
  AnyIO cancellation shield around the manager-owned close task and a done
  callback to consume late errors. A timeout or `cleanup_unverified` poisons
  the child instance and prohibits creating a second provider generation.
  P2.6 `aclose` is idempotent and still owns actual process teardown.
- **No premature READ designation:** despite a definition-only preview, the
  tool carries no `readOnlyHint`: native Pyright commands can perform writes
  independently of `workspace/applyEdit`. P3 OS side-effects audit remains
  a mandatory gate before release to untrusted workspaces.

## Native regression evidence

All tests ran in isolated review worktrees, not live service installations.
Pyright version was **1.1.413** on all hosts; each test host installed the
same Git-pinned multilspy SHA above.

| Host | CPython | Executed selection | Result |
| --- | --- | --- | --- |
| MacBook Pro macOS ARM64 | 3.13 | P2.4–P2.7 combined, including real HTTP and Pyright | **163 passed** |
| Raspberry Pi Linux ARM64 | 3.13 | Identical reviewed candidate, native platform selection | **163 passed** |
| Sextant Linux ARM64 | 3.13 | Identical reviewed candidate, native platform selection | **163 passed** |
| MacBook Pro macOS ARM64 | 3.10, 3.14 | P2.7 focused HTTP/lifespan/real Pyright | **30 passed each** |

The full Mac selection included P2.4 process owner, P2.5 workspace/document,
P2.6 34 fake and nine real manager tests, and P2.7 30 selected tests. Both Linux hosts were rerun against the exact reviewed final P2.7 source
and test files (SHA-256 matched with the MacBook); all three native hosts
passed the same **163** selected cases. `pytest --collect-only` confirms
**30 P2.7 tests** on Mac, with Python 3.10/3.14 each passing those 30. Normal existing MCP application-composition regression was also
run on macOS: **15 passed, one platform-expected skip**.

Run P2.7 specifically, with explicit opt-in to fail on a missing binary:

```bash
UV_PROJECT_ENVIRONMENT=.qa-p27 uv sync --locked \
  --extra development-intelligence-pyright --group test --python 3.13
export BINNACLE_PATCHED_MULTILSPY_QA=1
export PYRIGHT_LSP_TEST_BIN=/absolute/host-provided/pyright-langserver
.qa-p27/bin/python -m pytest -q \
  tests/unit/core/test_lsp_p27_child_lifespan.py \
  tests/integration/test_lsp_p27_fastmcp_mount.py \
  tests/integration/test_lsp_p27_http_protocol.py
```

Additional checks: Ruff configured rules and formatting, focused mypy, Bandit,
`uv lock --check`, complete guarded startup manifest, strict under-500-line
module gate, wheel contents and pinned PEP 508 optional dependency, separate
no-extra installation (no multilspy imported), and unchanged six/eight tool
surfaces. Tests used real FastMCP v4.1 and the root `create_application`.

## Independent review outcomes

A **read-only** Claude Fable source review found three actionable concerns:

1. FastMCP is driven by AnyIO cancellation scopes; a second plain asyncio
   wait may itself be cancelled. We introduced `anyio.CancelScope(shield=True)`
   and a dedicated cleanup-task done callback. Unverified/late cleanup cannot
   silently authorize a second manager instance; added fault-injection tests.
2. Mounted child exceptions could be surfaced by the parent if they were not
   mapped in the child. We now catch all ordinary downstream exceptions and
   return fixed error codes, also guarding location serialization. HTTP and
   fake tests verify source paths and exception details never reach clients.
3. The production factory was checked for the absence of any private gate
   forwarding. `_private_lsp_preview_gate` must remain a **code-only** review
   dependency until the P5 public product approval and associated permissions.

Default/off mounting and lazy multilspy imports were independently reviewed
without new findings, and verified by native tests. The review does not
certify OS security or make the preview suitable for deployment.

## Still-open production gates

1. **P2.8 full repository CI, quality/coverage, packaging and rollback:**
   P2.4–P2.6 Binnacle feature-branch GitHub CI runs were RED despite their
   native-focused passes. This P2.7 commit will trigger its own CI; neither
   private passing cases nor wheel build is a full-release GO.
2. **P2.5 adversarial filesystem acceptance:** symlink / TOCTOU mutation
   fixtures were blocked by the execution environment and were not retried
   through a different host. Native descriptor-based reader functionality is
   validated, but complete adversarial authority proof is still open.
3. **P3 Pyright process side-effect and OS confinement audit:** no sandbox,
   untrusted READ, hard CPU/RSS or descendant-escape enforcement claimed.
4. **P4/P5 semantic contract and official tool-release decision:** the QA-only
   preview is not `inspect_symbol`, not versioned as public API, and the real
   service factory cannot mount it. No production tool, client permission,
   plugin schema or server process was modified in this work.

**Disposition:** private P2.7 conditional child and manager-lifespan mechanism
functionally verified, with fail-closed status under cancellation and error;
remain default-unmounted in production until P2.8/P3/P4/P5 approvals.
