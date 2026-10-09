# G7 post-refactor quality convergence — 2026-10-09

Base: `90ffb1a2ca33f26773f73f771c5c97db548ce8b0`.
Branch: `fix/g7-post-refactor-quality-20261009`.
Owner: one isolated writer worktree; production `master` has user-owned dirty files.

## Objective and boundaries

Restore truthful, mutation-resistant quality checks after G7 retired 94 historical
source paths. Preserve the public MCP eight-tool surface, order, wire contracts,
CLI names/options, service units, journal identifiers, durable-job storage,
FastMCP version and live behavior. Do not rewrite implementation architecture.

## Execution

1. Freeze the base and dirty-file inventory. Do not edit, stash or reset the
   original checkout, or alter any unrelated worktree.
2. Make the G6 empty compatibility inventory truthful: replace the vacuous
   report cell with the frozen G7 retirement gate, remove the now-dead
   manifest entry points, and update report tests/labels.
3. Close narrowly reproducible static-analysis gaps: literal relative
   `importlib.import_module` with a literal package, module-registry mutation
   via augmented aliases/delete/mutator calls, and Gate A's package-root
   resolution. Share the canonical AST import scanner rather than introduce
   another independent implementation. Add positive and negative fixtures.
4. Inventory surviving source modules with source imports and external
   entrypoints, classify dynamic imports and plugin hooks manually. Do not
   delete a module solely because static imports do not reach it.
5. Remove genuinely outdated live commentary and no-longer-used quality-test
   scaffolding. Keep documented historical logs, identifiers and compatible
   CLI options. Defer the 450–500-line module split as independent debt.
6. Verify changed tests first, then local static hooks/import-linter, followed
   by *one* complete seeded two-lane suite plus coverage/packaging. Match
   required Python 3.10–3.14 CI gates and fixed-wire comparisons before any
   production merge or deployment.
7. Only after successful acceptance, purge ignored legacy `__pycache__`
   entries if safely scoped and in a quiet window, preserve all live service
   and user-owned paths. Deployment requires exact-SHA CI and normal guarded
   flow; on any policy/safety refusal, stop that operation without bypass.

## Acceptance evidence

- All 94 retired source paths remain absent; the gate fails if reintroduced.
- Static negative fixtures fail and benign imports/introspection pass.
- Gate A no longer shows a PASS for an empty former-facade manifest.
- Full suite and platform gates green, no wire behavioral change.
- A written module reachability inventory and cache cleanup receipt.
- Final exact SHA/branch, repository dirtiness and deployment status explicit.
