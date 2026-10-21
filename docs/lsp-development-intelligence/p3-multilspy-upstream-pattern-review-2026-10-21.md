# Microsoft multilspy PR #168: upstream adapter and test-pattern review

Date: 2026-10-21. Reviewed repository: microsoft/multilspy main baseline
62acb3cf2d7a0746992ca08767d8a4fded402ebb (v0.1.1).
Contributed fork branch: feat/pyright-language-server-20261021.
Reviewed and pushed revision: f6f7e6a3c2021b56fc99c4ac7d4530e8d9a94c44.
Pull request: https://github.com/microsoft/multilspy/pull/168 .

## Review method

Compared upstream language adapters for Jedi, Rust Analyzer, clangd,
TypeScript, Go, and the remaining native language providers. Compared test
patterns from test_multilspy_python, test_adapter_notifications,
test_completion_responses, test_python_completions, test_sync_startup and
test_runtime_permissions. Also performed one independent read-only source
review of the initial revisions. No user source/logs used in that review.

## Implementation alignment

- LanguageServer.create selects Jedi by default; Pyright only when
  explicitly configured with python_server=pyright.
- Added MultilspyConfig field at END, leaving preexisting positional
  constructor semantics and Jedi behavior intact.
- Uses a dedicated PyrightServer(LanguageServer) alongside other adapter
  classes, with ProcessLaunchInfo argv and canonical project root.
- Loads a packaged initialize_params.json via _get_initialize_params,
  matching other provider adapters rather than embedding the full
  initialization template inline in start_server.
- Explicitly registers workspace/configuration, denied workspace/applyEdit,
  denied dynamic registration, bounded publishDiagnostics,
  window/logMessage and progress handlers before initialize.
- Validates required capabilities using LSP-legal booleans OR options
  objects (including empty dicts), confirms UTF-16 position encoding,
  signals initialized/completion readiness, then guarantees process stop
  even on failed start, timeout, cancellation or failed shutdown.
- High-level inherited multilspy APIs handle ordinary Python navigation;
  generic normalized LocationLink now accepts omitted optional
  originSelectionRange and references can be null.
- Generic completion parser now supports label-only CompletionItem payloads
  and requests incomplete completions with triggerKind=3 on retries.
  Real Pyright previously timed out/asserted; after fix, high-level
  completion returned class method candidates.

## Test conventions and coverage

Mirrors existing upstream tests, NOT Binnacle-specific MCP tests:
pytest.mark.asyncio, fixtures, parametrization, AsyncMock/Mock for
notification and failure cases, and a local temporary project for real
optional Provider tests. No new remote repository downloads in tests.

Selected focused regression coverage consists of:
- 10 Python/Pyright backend selection and real navigation/completion/hover/
  symbols/diagnostics/synchronous facade tests
- 14 adapter notification/initialize/capability/config/cleanup mock tests
- 2 real nonresponsive subprocess timeout/cancellation cleanup tests
- 16 cross-adapter LSP Location/LocationLink/null response tests
- 11 shared completion variant and incomplete-trigger tests
- 7 existing notification regression tests
- 2 existing Jedi high-level completion tests
- 4 existing sync startup/cleanup tests

Native execution: Mac ARM64 CPython 3.10, 3.13 and 3.14 each **66 passed**;
Raspberry Pi Linux ARM64 CPython 3.13 **66 passed**. Real Pyright version
1.1.413, except fake-stdio resource cases where Pyright was intentionally
not launched. The source and tests on Pi were checked out directly from
f6f7e6a, not assumed equivalent from a separate copy.

The built wheel was verified to contain both PyrightServer and its
initialize_params.json. Targeted Ruff check/format, YAML structural
validation, Python compilation and Git diff whitespace checks passed.

## Publication status and scope

The revised PR #168 was successfully pushed. GitHub currently reports
OPEN, MERGEABLE, REVIEW_REQUIRED and license/cla PASS. This is not an
upstream merge or released multilspy package.

The current GitHub CLI OAuth authorization lacks workflow scope, so a
proposed edit to the upstream workflow could not be pushed; it was removed
from unpublished local history rather than bypassing authorization.
Existing CI will run synthetic tests, while real-provider tests only
execute when the maintainer/environment explicitly supplies the
MULTILSPY_PYRIGHT_TEST_BINARY absolute path. Reviewers were told how to
run them with pinned Pyright 1.1.413.

Binnacle production dependencies continue using the unmodified official
multilspy v0.1.1 unless separately pinned to an audited upstream revision.
The generic high-level completion fixes in this PR must NOT be assumed
available in the published v0.1.1 package. No production tool surface,
running MCP service, process-owner integration, or per-host provider
safety release gate was modified. Continue P2.4/P2.5 only on their own
release evidence.
