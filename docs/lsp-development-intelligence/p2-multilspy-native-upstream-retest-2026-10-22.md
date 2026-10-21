# P2/P3 retest — use patched upstream multilspy directly in Binnacle (2026-10-22)

## Decision

**GO for functional private integration testing. NO-GO for production/persistent
provider release.** This is a new Binnacle-level test against the **exact
upstream Pyright adapter that was submitted**; it is *not* another test of the
custom `PyrightAdapter` subclass already found in Binnacle.

Pinned provider inputs:

- Microsoft multilspy PR [#168](https://github.com/microsoft/multilspy/pull/168),
  contributor commit **`b5325f19c7b77317bd4ab7c1ff3c6bb8fa5b8f1b`**.
  Installed into a separate QA virtual environment from its exact source
  checkout. Distribution metadata still reports `multilspy==0.1.1`, which is
  **not sufficient** to identify the patched source. The test insists on the
  source Git SHA **and** on the imported `PyrightServer` file being under the
  specified checkout.
- Real `pyright-langserver --stdio`, Pyright **1.1.413**, preinstalled on each
  host; no run installs or updates the provider.
- Binnacle development baseline: `282b619` with a QA-only test branch
  `qa/lsp-patched-multilspy-20261022` derived from it. Its tests are
  non-production code and are not mounted into a live MCP server.

## What changed from the previous acceptance method

The old `tests/integration/test_lsp_multilspy_pyright*.py` suite constructs
`binnacle.features.development_intelligence.multilspy_pyright.PyrightAdapter`.
That class copies LSP capabilities, callbacks, JSON-RPC initialization,
diagnostics and lifecycle, so it does not prove upstream `PyrightServer` works.
Without the optional multilspy dependency, the old tests can appear as skipped.

The new private tests instead use **unchanged**
`LanguageServer.create(MultilspyConfig(code_language=Language.PYTHON,
python_server="pyright", server_binary=<pinned absolute executable>), ...)`.
They assert the resulting *exact class* is upstream `PyrightServer`. There is
no Binnacle subclass or replacement transport in the successful real-provider
paths. A separate explicit FastMCP in-memory test tool uses this native server
and Binnacle's existing path-admission and result validation helpers. It is
**not** Binnacle's eventual production `inspect_symbol` tool.

## Acceptance evidence

All feature suites are from the same Binnacle QA source and multilspy patch.

| Native host | CPython | Tests (Binnacle old adapter oracle + new patched upstream + policies) |
| --- | --- | --- |
| MacBook Pro, macOS ARM64 | 3.10.22 | **93 passed**, one disabled production release gate |
| MacBook Pro, macOS ARM64 | 3.11.17 | **93 passed**, one disabled production release gate |
| MacBook Pro, macOS ARM64 | 3.12.15 | **93 passed**, one disabled production release gate |
| MacBook Pro, macOS ARM64 | 3.13.16 | **93 passed**, one disabled production release gate |
| MacBook Pro, macOS ARM64 | 3.14.8 | **93 passed**, one disabled production release gate |
| Raspberry Pi, Linux ARM64 | 3.13.16 | **93 passed**, one disabled production release gate |
| Sextant, Linux ARM64 | 3.13.16 | **93 passed**, one disabled production release gate |

The ten new normal acceptance tests establish real definition/reference,
hover, high-level completion (including the previously broken incomplete
retry), document symbols, UTF-16 non-BMP navigation, actual push type
diagnostics, read-only rename proposal, empty/null results, repeated start
and stop, cancellation/exception cleanup, and no source changes. They also
exercise the private FastMCP call path, an explicitly denied path, a
validated same-root result, the default-off configuration, the unmounted
production root's original eight tools, and the Jedi default selection.

The original seven Binnacle real-provider functional cases **also passed**
when explicitly enabled with pinned Pyright, and the broader selected LSP
unit/policy suite passed without failures. This allows a comparison with the
legacy implementation without using it in the new native tests.

## Reproducible commands

In an **isolated QA worktree**, create a test venv and install Binnacle plus
**the exact patched multilspy source** in editable test mode (never into the
installed Binnacle production service):

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python \
  -e . -e /absolute/path/to/multilspy-at-b5325f1 \
  'pytest>=9.1' 'pytest-asyncio>=1' 'pytest-timeout>=2.4'

export BINNACLE_PATCHED_MULTILSPY_QA=1
export BINNACLE_MULTILSPY_SOURCE_DIR=/absolute/path/to/multilspy-at-b5325f1
export PYRIGHT_LSP_TEST_BIN=/absolute/path/to/pyright-langserver
export PYRIGHT_CLI_TEST_BIN=/absolute/path/to/pyright

.venv/bin/python -m pytest -q \
  tests/integration/test_lsp_multilspy_patched_upstream.py \
  tests/integration/test_lsp_multilspy_patched_upstream_mcp.py \
  tests/integration/test_lsp_multilspy_patched_upstream_release_gate.py \
  tests/integration/test_lsp_multilspy_pyright.py \
  tests/integration/test_lsp_multilspy_pyright_feature_matrix.py \
  tests/unit/core/test_multilspy_pyright_adapter.py \
  tests/unit/core/test_lsp_session_policy.py -rs
```

Without `BINNACLE_PATCHED_MULTILSPY_QA=1`, normal optional real-provider tests
skip. **With it**, a missing binary, wrong Git revision, or a stale PyPI
package is an assertion failure, **not** a false green run.

## Hard release gate: confirmed RED on all three hosts

The separately enabled production gate is deliberately strict:

```bash
BINNACLE_LSP_RELEASE_GATE=1 .venv/bin/python -m pytest -q \
  tests/integration/test_lsp_multilspy_patched_upstream_release_gate.py
```

Its negative scenario suppresses one outbound response, times out and cancels
its request, then closes the real `PyrightServer`. On **macOS ARM64, Raspberry
Pi and Sextant Linux ARM64** it reproducibly fails:

- Pending response handlers at entry: **0**.
- Pending response handlers after canceled timeout: **1**.
- Pending response handlers *after the provider stopped*: **1**.

Root cause in the shared upstream
`multilspy/lsp_protocol_handler/server.py`: `LanguageServerHandler.send_request`
registers a `Request` in `_response_handlers` and does not remove it in a
`finally` on cancellation. `stop()` does not empty/wake abandoned handlers.
This can accumulate stale request state over long-lived or repeatedly restarted
sessions. Late answers also need explicit behavior if the request was removed.
Do **not** ignore, xfail, or turn the gate green by swallowing this condition.

**Required P2.4 remediation:** preserve one authoritative process owner;
introduce guaranteed pending request cleanup and deterministic handling for
late/duplicate responses, timeouts, cancellation, provider crash and shutdown.
Prefer a small upstream fix to duplicating JSON-RPC semantics inside Binnacle;
revalidate on both native OSes, then rerun this hard gate. The P2.4 process
tree/sandbox and leak audits remain independent.

## Other production gates that remain open

1. **P2.5 workspace authorization:** Current policy helpers are still located
   in the legacy Binnacle adapter module and manually invoked in the *test
   harness*. The upstream library itself does not enforce allowed-root,
   symlink/TOCTOU or returned URI authority. Extract/reuse the policy in a
   thin host authorization layer, with disk snapshot/version freshness, before
   wiring requests from the real MCP service. Never expose raw `server.send`
   or arbitrary user-supplied paths to an untrusted agent.
2. **P3 provider trust:** `pyright.createtypestub` can write `.pyi` files
   directly on the server side without a `workspace/applyEdit` callback. The
   new upstream opt-in editor callback is not an OS sandbox. This provider
   stays **explicit-trust-only**, never automatically classified READ, until
   its actual host confinement and side effects are audited.
3. **P2.6–P2.8 production architecture:** Instance registry, concurrency,
   timeouts, resident limits, lifespan injection, default-off conditional
   child mount and regressions are still not implemented or released in
   Binnacle. An in-memory FastMCP test app is not a deployed Binnacle MCP
   tool. The current root tool list remains unchanged at eight tools.

## Final scope boundary

No production service restart, live MCP API change, provider install, source
edit in a real user project, or release decision was made. The upstream fork
at `b5325f1` is used **unchanged**, precisely to distinguish upstream library
behavior from required Binnacle policy and orchestration. Functional native
integration passes; production NO-GO is a deliberate, evidenced outcome.
