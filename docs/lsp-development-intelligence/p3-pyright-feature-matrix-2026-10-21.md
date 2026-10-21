# Real Pyright LSP feature matrix — 2026-10-21

Status: TESTED in disposable development workspaces, not production ready.
Selection: Pyright is the sole preferred Python LSP provider; do not
restart Jedi/Zuban comparisons. This is functional acceptance only,
not a provider security/containment or performance audit.

## Locked actual runtime

- Pyright / pyright-langserver: 1.1.413 (pinned npm installation under /tmp).
- Microsoft multilspy: v0.1.1, upstream commit
  62acb3cf2d7a0746992ca08767d8a4fded402ebb, optional library.
- Binnacle PyrightAdapter in
  src/binnacle/features/development_intelligence/multilspy_pyright.py.
- macOS arm64: actual multilspy/stdio real-provider integration.
- Linux aarch64: Raspberry Pi and Sextant checked the four type-checking
  modes through installed Pyright 1.1.413 CLI, not the multilspy adapter.
- Tests only use temporary synthesized Python projects. Production Binnacle
  host services, real user repositories, external file edits, and MCP tool
  inventory are not touched.

## Verified against real LSP responses

| Capability | Real result | multilspy/Binnacle access |
| --- | --- | --- |
| LSP initialize, UTF-16 negotiation | PASS | Adapter-managed |
| Definition navigation across files; method definitions | PASS; correct lib.py lines | Adapter high-level |
| Cross-file references | PASS across app.py and signature.py | Adapter high-level |
| Hover type/documentation | PASS | Inherited high-level |
| Completion for class members and import names | PASS; add and Calculator candidates | Upstream low-level LspRequest |
| Function signature/argument help | PASS; parameter 1 and parameter labels | Upstream low-level LspRequest |
| Document and workspace symbols | PASS; workspace needs index readiness | Inherited high-level |
| Declaration and type definition | PASS | Upstream low-level LspRequest |
| Document highlights | PASS; multiple references | Upstream low-level LspRequest |
| Rename preparation and cross-file edit proposal | PASS; four source files and eight proposed edits in one POC | Upstream low-level LspRequest; never applied |
| Call hierarchy | PASS; incoming callers; outgoing may be null when no callees | Upstream low-level LspRequest |
| Non-BMP Unicode source position | PASS; emoji uses UTF-16 offset 23 vs Python 22 | Explicit Binnacle position conversion |
| Push diagnostics: static return/assignment type | PASS; reportReturnType and reportAssignmentType | Bounded adapter diagnostic queue |
| Push diagnostics: syntax errors | PASS; severity=error; rule code may be absent | Bounded adapter diagnostic queue |
| Push diagnostics: undefined variable/import | PASS; reportUndefinedVariable and reportMissingImports | Push + CLI |
| Whole workspace analysis | PASS, including unopened files and exclusion paths | Pyright CLI (not same as LSP) |

Type-checking CLI mode acceptance on Mac:
- Off: syntax and undefined symbols still diagnosed; type mismatches suppressed.
- Basic / Standard: both report return/assignment type inconsistencies.
- Strict: additional missing or unknown parameter annotations diagnosed.
- Clean and excluded source paths do not raise unrelated errors.
- Linux native Pi/Sextant: Pyright 1.1.413, 4/4 modes each; on a
  separate minimal fixture error counts off 8, basic 11, standard 11,
  strict 17. These counts are not directly comparable with the Mac
  corpus because their test inputs differ.

## Important negative and integration findings

1. An initial multilspy raw-request probe used macOS file URIs under
   /var while the Binnacle adapter canonicalized the workspace to
   /private/var. The incorrect URI caused misleading null responses
   and diagnostics misses. The test fixture now resolves its root and
   constructs all file URIs from the same canonical root.
2. Upstream multilspy high-level request_completions repeatedly sends
   up to 30 completion requests with triggerKind=Invoked even if Pyright
   reports isIncomplete=true, then may return an empty list or take too
   long. A real high-level attempt exceeded a five-second bound.
   **Do not call this high-level convenience method production-ready.**
   The upstream low-level textDocument/completion request returns valid
   candidate items promptly and passed our feature suite. A bounded
   upstream contribution or thin adapter fix is needed before exposing
   high-level completion to Agent tools.
3. Pyright 1.1.413 does not advertise implementationProvider, and
   textDocument/implementation returns JSON-RPC method-not-found -32601.
   This is NOT a verified supported feature. Use definition/references.
4. Pull diagnosticProvider is not advertised in this tested initialization;
   validated diagnostics use publishDiagnostics pushes and standalone
   Pyright CLI. Do not claim textDocument/diagnostic support.
5. Organize Imports uses a command/edit path. No executeCommand or
   workspace edit was applied, by design. Stub generation and code-action
   execution were not exercised; absence of test evidence is not a failure
   of Pyright's advertised general capability.
6. Binnacle does not yet expose signature help, rename or call hierarchy
   as agent-facing public methods. They are **provider/low-level client
   capabilities**, not shipping MCP tools. Returned edit proposals,
   URI scope and non-idempotent command execution require later admission.
7. Performance, memory, disk/cache writes, network behavior, fault-tolerant
   subprocess shutdown and escaped descendants are NOT established by
   these short-lived functional checks. P2.4/P2.5/P3 safety gates remain.

## Repeatable tests

New file: tests/integration/test_lsp_multilspy_pyright_feature_matrix.py.
It requires pinned PYRIGHT_LSP_TEST_BIN and PYRIGHT_CLI_TEST_BIN for actual
execution, and the separately installed optional multilspy library.
Normal/default Binnacle installation skips all four added integration
tests and does not download or install any Provider.

- Mac real provider matrix: 4/4 tests pass, repeated at seeds
  19, 101 and 8215 alongside three existing integration tests: 7/7
  per run.
- Mac CPython 3.10 and 3.14: with pinned optional multilspy v0.1.1
  installed only in disposable temporary virtualenvs, 7/7 actual
  existing+new integration tests pass in each version.
- Linux aarch64 on Raspberry Pi and Sextant: four CLI type
  configuration modes passed on each device; multilspy integration
  on those hosts was **not** executed by this task.

Decision: Pyright's listed core LSP language features work correctly
with canonical paths and valid request locations. Some features require
the low-level multilspy API and high-level completion still needs an
upstream fix. Keep Pyright as selected provider; continue P2.4 process
ownership and P2.5 workspace/URI gates before public MCP exposure.
