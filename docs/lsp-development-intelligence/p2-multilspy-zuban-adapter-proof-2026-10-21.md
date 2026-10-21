# P2 Zuban external adapter proof — 2026-10-21

Scope: source inspection and a disposable multilspy+Zuban experiment.
This is NOT production implementation, deployment, Linux-native validation,
provider sandbox certification or an invitation to restart historical E2/E3.

## Pinned sources

- Microsoft multilspy v0.1.1, tag commit
  62acb3cf2d7a0746992ca08767d8a4fded402ebb, MIT.
  https://github.com/microsoft/multilspy
- Zuban 0.10.0, via PyPI, Rust-implemented Python LSP; isolated macOS arm64
  virtualenv; source https://github.com/zubanls/zuban and
  https://docs.zubanls.com/en/latest/installation.html .
- Official process command: zuban server. Zuban LSP initializationOptions:
  typeCheckingMode=default/off/mypy/auto; diagnosticMode=open-files-only/workspace;
  disableLanguageServices and optionally pythonExecutable.
- Zuban distribution is listed AGPL-3.0-only by PyPI; upstream advertises a
  commercial license. Before redistributing with Binnacle, review licensing.

## Actual multilspy extension points

1. multilspy.language_server.LanguageServer.create has a fixed Language.PYTHON
   to JediServer factory branch; setting server_binary=zuban on the Jedi
   adapter is NOT sufficient. Jedi startup asserts exact Jedi-specific
   completion and synchronization capabilities.
2. LanguageServer.__init__ accepts ProcessLaunchInfo and language_id. It
   explicitly allows a subclass. Construct a custom ZubanAdapter
   directly, without changing multilspy source or language enum.
3. ProcessLaunchInfo(cmd=[authorized zuban absolute path, "server"],
   cwd=authorized workspace), language_id="python".
4. In the adapter async start_server context: register read-only reverse
   request handlers, enter super().start_server, await server.start,
   await server.send.initialize(approved parameters), send initialized,
   and in finally await server.shutdown and server.stop.
5. Reuse the existing high-level async reference, hover and document symbol
   query methods. Request textDocument/diagnostic through the existing
   low-level server.send.text_document_diagnostic; add a small public
   wrapper if needed for Binnacle check_code.
6. For a formal upstream integration, add Language.ZUBAN, a LanguageServer
   factory branch and first-party language-specific module with tests.
   The upstream maintainers document this pattern in microsoft/multilspy
   issue #5. Prefer upstream acceptance to a permanent private fork.

## Executed disposable tests (MacBook Pro only)

Everything below executed in /tmp, with no Binnacle or multilspy Git edits.

- External ZubanAdapter with Binnacle P1 fake LSP subprocess:
  initialize PASS, definition 1, references 2, hover present, clean exit.
- Zuban 0.10.0 actual server process, configured with multilspy handler:
  initialize PASS, references 1, hover present, clean exit.
- Inherited multilspy request_definition raised AssertionError.
  The raw Zuban response was a valid LocationLink list of length 1 with
  targetUri, targetRange and targetSelectionRange, and NO
  originSelectionRange. multilspy incorrectly requires this optional field.
  See LSP specification LocationLink.originSelectionRange optional marker.
- A temporary ZubanCompatAdapter override normalized the LocationLink
  and rejected non-file or off-root URIs. It produced: definition 1,
  references 1, documentSymbol tuple and pull document diagnostic
  report kind=full with 1 diagnostic for an intentionally mismatched
  annotated function return. Source remained unchanged and process exited.
- No real performance/latency comparison, resource isolation guarantee,
  Linux ARM64 proof or broad symbol accuracy claim was generated.

Disposable POC scripts:
  /tmp/binnacle-multilspy-zuban-poc-20261021/probe_adapter.py
  /tmp/binnacle-multilspy-zuban-poc-20261021/probe_real_zuban.py
  /tmp/binnacle-multilspy-zuban-poc-20261021/probe_definition_shape.py
  /tmp/binnacle-multilspy-zuban-poc-20261021/probe_compat.py

## Remaining acceptance conditions

- Prefer proposing the optional-LocationLink normalization fix upstream
  (also robust null result normalization) instead of permanent override.
- Preserve Binnacle P2.0 disabled-by-default settings and strict audited
  absolute executable selection; prevent upstream automatic download/setup.
- Preserve authorized root/URI validation, file snapshot freshness and
  return-path filtering. Multilspy itself is not the policy authority.
- Reconcile multilspy's process-owned stdio with Binnacle's P2.4 process
  cleanup and loss handling. A passing short-lived test does NOT certify
  containment of escaped children or cancellation during crashes.
- Make logging source-private and avoid automatically answering write/
  execute requests. Test UTF-16 Unicode, queue/request timeout and concurrency.
- Repeat real Zuban test on both Linux ARM64 devices in a disposable
  environment and verify host service PATH before any rollout.
- Independently validate Python code-navigation quality and diagnostic
  scope before replacing Jedi/Pyright; current sample is deliberately tiny.

Decision: external subclass viability CONFIRMED with real Zuban 0.10.0 on
macOS. Production migration remains unapproved. Keep preexisting Binnacle
protocol code as test oracle until replacement passes scoped gates.
