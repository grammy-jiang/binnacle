# multilspy Pyright adapter — implemented and real-provider tested

Date: 2026-10-21. Implementation branch:
feat/lsp-isolated-p0-review-20261021. This is an optional private
adapter, **not a production enabled MCP tool or completed P3 audit**.

## Community-first selection

Multilspy v0.1.1 (Microsoft, commit
62acb3cf2d7a0746992ca08767d8a4fded402ebb) supports custom
LanguageServer subclasses. A previous community PR #39
(https://github.com/microsoft/multilspy/pull/39) proposed Python
Pyright support in 2024, but its retrieved PR head
43d6a6190ecb17cd5059fad5a4f9d14bc49c8f2b calls
basedpyright-langserver, not pyright-langserver, passes a string
rather than argv list to ProcessLaunchInfo, and retains Jedi-specific
completion assertions. It is not merged in the audited v0.1.1
language factory. Do not import that PR wholesale.

The implemented replacement is an **external** multilspy subclass
created lazily by:
  binnacle.features.development_intelligence.multilspy_pyright.create_pyright_adapter

It imports the upstream package only on explicit invocation, so the
default-off Binnacle MCP service does not require or import multilspy.
No upstream copy or private fork was checked into Binnacle.

## Adapter behavior

- Explicit absolute pyright-langserver executable. No automatic download,
  pip/npm install, or implicit project-local PATH search.
- Launch argv is [absolute_binary, "--stdio"], with a canonical project
  root as cwd and Python language ID. Uses Microsoft's LanguageServer
  and LanguageServerHandler for JSON-RPC, stdio and request dispatch.
- Provides a deterministic Python/Pyright workspace/configuration handler
  for typeCheckingMode (off/basic/standard/strict) and diagnosticMode
  (openFilesOnly/workspace), plus a bounded queue for
  textDocument/publishDiagnostics notifications.
- Initializes with only read-oriented LSP client capabilities, UTF-16
  position encoding and no applyEdit capability. Refuses
  workspace/applyEdit and dynamic client/registerCapability.
- Reuses inherited multilspy hover/documentSymbol facilities.
  The small definition/references overrides accept null, Location
  and LocationLink without the optional originSelectionRange.
  Returned locations are restricted to the allowed workspace.
- Rejects absolute/traversing/symlink-escaping input paths. These are
  in-adapter checks only: full workspace authorization, historic
  snapshot/TOCTOU and provider confinement remain P2.5/P3 gates.
- On context exit performs multilspy shutdown then process cleanup.
  No guarantee is made about malicious escaped descendants.
- Does not log raw JSON-RPC payloads; rejects the upstream
  trace_lsp_communication option for this adapter.

## Reproducible temporary real-provider POC

Upstream library installed in a standalone Python 3.13 virtualenv in /tmp:
multilspy v0.1.1. Pyright installed using npm with explicit
pyright@1.1.413 under a separate /tmp prefix with lifecycle scripts
disabled. System service configuration, PATH, Binnacle uv.lock,
development dependency set and production MCP processes were untouched.

Checks performed on a disposable sample Python project:
- standard LSP initialize, Pyright capability negotiation and clean exit;
- definition query: one correct local result;
- references query: one correct local result;
- hover and documentSymbol responses;
- diagnostic push, after ignoring stale empty notifications:
  reportReturnType generated for a deliberately invalid str return;
- no changes to the test source;
- process handle cleared at context exit.

The existing Pyright CLI independently reported the same
reportReturnType diagnostic with an explicit strict configuration.
This validates the local code path but does not prove large-project
correctness or that all Python configuration precedence combinations
work as expected.

Unit: tests/unit/core/test_multilspy_pyright_adapter.py validates options,
boundaries, Location and spec-valid LocationLink, null, malformed ranges,
URI/path confinement and no-import default behavior.
Integration: tests/integration/test_lsp_multilspy_pyright.py tests actual
Pyright stdio, source unchanged, safe path refusal and adapter construction.
Integration tests explicitly skip in normal Binnacle environments without
a pinned PYRIGHT_LSP_TEST_BIN and the optional multilspy package.

## Remaining (not claimed)

- No automatic public MCP registration or host production install.
- **Linux ARM64 Raspberry Pi native real adapter regression: 46/46
  passed** in a disposable /tmp installation, including 3 real Pyright
  integration tests and 4 extended capability tests. This confirms
  Linux/macOS functional compatibility on tested inputs, not a live
  Binnacle service-context or process-containment guarantee.
- Sextant has the installed Pyright binary and prior independent CLI
  configuration-mode tests, but this exact multilspy adapter suite was
  not executed on Sextant.
- No complete type/diagnostic correctness, latency, RAM and resource audit.
- No robust P2.4 forced-stop/timeout/cancellation process containment,
  concurrent workspace instance manager or P2.5 repository authorization.
- Upstream multilspy currently does not enforce per-request deadlines
  in its request dispatcher. Binnacle should fail closed on interrupted
  sessions; production exposure requires P2.4/P2.6 validation.
- Python source document freshness, URI/returned-link policy and the
  final privileged host trust profile require review before public READ.
- Before releasing any user-facing tool, verify unchanged default six/eight
  MCP tool surfaces and conditional subserver mounting under P2.7.

**Decision:** Pyright adapter feasibility and real-protocol functionality:
PASS on isolated macOS. Production enablement: NOT APPROVED. Prefer
contributing generic LocationLink/null normalization upstream rather than
maintaining duplicate LSP clients or a private multilspy fork.
