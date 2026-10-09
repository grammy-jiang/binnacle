# G7 post-refactor quality audit — 2026-10-09

## Reviewed baseline and boundaries

The independent source review used local production master
`90ffb1a2ca33f26773f73f771c5c97db548ce8b0`. Edits are isolated under
`fix/g7-post-refactor-quality-20261009`; original master retains the user's
pre-existing modified `pyproject.toml` and untracked documents. No runtime
service or external MCP tool is modified by source-review actions.

## Confirmed issues resolved in the candidate

1. The G6 `compatibility_facades() -> set()` path made the Gate A compatibility
   inventory unconditionally green. Remove that dead scanner and its tautological
   tests. The report now evaluates the G7 frozen 94-path, 92-module-name
   retirement gate and reports actual violations. The previous
   `architecture.g6_compatibility_facade_inventory` identifier is replaced by
   `architecture.g7_legacy_retirement` (a static report cell, not a public
   MCP/runtime field).
2. Recognize literal relative `importlib.import_module` calls when a literal
   package is supplied, including aliases, positional/keyword forms. Recognize
   module-registry alias augmented assignment, deletion and dict mutation
   methods in the static G7 guard. The scanner explicitly cannot prove
   dynamically computed Python import names.
3. Gate A source analysis now delegates import discovery to the canonical
   architecture analyzer and resolves the innermost `binnacle` source-package
   root instead of the identically named Git checkout. Regression tests cover
   the duplicated checkout/package path and dynamic imports.
4. The residual `platform/linux/service_unit_linux.py` was proven unreferenced
   by first-party runtime sources: no source importers, no script entrypoint,
   and its only direct executable references were its own unit tests. Other
   working `unit_property` variants live in `deployment.units` and
   `platform.linux.service_provisioning_linux`, with behavior tests. The
   orphan and its self-referential test module were deleted; manifest and
   negative boundary fixtures were adjusted. This intentionally drops an
   unadvertised Python module import (not a public MCP or CLI contract).
5. Removed retired-namespace-only ownership globs and updated live docs for
   Watchdog operations and the canonical stats module. Historical architecture
   journals and deployed logger identities remain unchanged.

## Reachability cross-check

- Before cleanup: 143 current Python source modules. Four configured
  `[project.scripts]` entrypoints plus `binnacle.server` and package root
  reached 142 modules through the AST source-import graph; the sole unvisited
  implementation module was `binnacle.platform.linux.service_unit_linux`.
- After cleanup: 142 source modules, all 142 reachable through this graph.
- The graph includes literal dynamic imports recognized by the canonical
  analyzer. Static reachability is a corroborating signal, not a guarantee of
  runtime use; it was combined with direct source references, entrypoints and
  duplicate implementation checks. No other modules were removed.

## Retained compatibility and measured debt

- `binnacle doctor --probe` remains deliberately inert for CLI callers.
  `binnacle-watchdog doctor --probe` is functional and distinct; do not mix.
- Historical logger identifiers (including `binnacle.jobs`,
  `binnacle.watchdog`) are intentionally stable for journal consumers.
- Small helper re-exports in `observability.logstats` and the search adapter's
  subprocess test seam are tested extension/compatibility affordances and
  remain; do not mistake them for G7's removed root modules.
- `features.commands.jobs` (497 lines) and
  `features.search.tools.search_text` (496 lines) are near the 500-line
  module-size ratchet; a future separate readability refactor requires its own
  tests and approval.
- The original checkout's `src/binnacle/__pycache__` previously contained
  440 Python bytecode files, 409 without a corresponding root Python source
  filename (97 historical stems). These ignored artifacts are not tracked
  production source. Remove **only** such entries after safe release/quiet
  window; do not remove user data or caches of still-existing modules.
- Older G6 Gate A `PENDING` source-state cells remain clearly labeled
  historical preparation evidence, not live deployment acceptance criteria.

## Verification ledger

Focused G7/Gate A/Ruff tests: 86 passed, 2 fixture-writing errors found and
fixed; both rerun individually passed. After orphan removal, an affected
focused run gave 84 passed and one test requiring `no_xdist` mistakenly invoked
under xdist; that test rerun correctly in the ordinary lane passed. The
repository's managed two-lane test runner must be used for final acceptance.

Static lint at source candidate: Ruff passed; G7 static check showed
94 retired paths, 92 module names and 0 violations; architecture check
142 modules and 0 forbidden dependencies; Import Linter 20 contracts kept,
0 broken. All are local evidence, not claims of full CI or deployment.

Final local evidence on the same source/test candidate (seed 12345):

- Full managed suite: parallel-safe lane 2,381 passed / 3 skipped; ordinary
  `no_xdist` lane 2 passed; both exit 0.
- Coverage pipeline: unit 978 passed + ordinary 1 passed; non-unit 1,403 passed
  / 3 skipped + ordinary 1 passed; `tox -e coverage-policy` reports 122
  production modules, 0 below target, 0 policy errors.
- Wheel artifact/packaging smoke: 1 passed.
- `pre-commit run --all-files`: every configured pre-commit quality gate passed,
  including MyPy, Ruff, Bandit, Deptry, module sizing, G7/architecture and
  Import Linter.
- Raw MCP tool-surface parity: an in-memory FastMCP client ran independently in
  the exact base and candidate environments. For `openai-mcp` legacy, modern
  `openai-mcp(ChatGPT)`, unrestricted legacy and unrestricted modern, the
  JSON serialization of tool names/descriptions, unnormalized input/output
  schemas, annotations and server instructions was byte-for-byte identical
  by SHA-256 for all four profiles (two served 6 tools; two served 8).

Cross-Python 3.10–3.14 required GitHub CI and a normal guarded release remain
pending. Live service acceptance and the original checkout's ignored cache
cleanup remain pending until a safe release; none are implied by local tests.
