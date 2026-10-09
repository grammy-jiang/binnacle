# Binnacle G7 — Post-refactor Quality Hardening

Date: 2026-10-09. Base: 4e8e1013b89aec2158eb423d93eb426aa6e13f60.

## Goal and strict scope

Fix two reproducible source-quality gate blind spots found in the read-only G0–G7 review. Make no FastMCP, MCP wire, durable-job protocol, package ownership, dependency, systemd, or platform redesign. Preserve existing historical journal logger identifiers. Runtime semantics and tool order must remain identical.

## Implementation steps

1. Fix the package-level relative-import resolver in scripts/check_architecture.py. Distinguish a package's __init__.py from a leaf module. Add negative regression tests that detect forbidden package-relative imports and positive tests for permitted relative imports.
2. Extend static literal import analysis to handle importlib aliases, imported import_module functions, getattr importlib calls and builtins.__import__ aliases. Keep using one canonical analyzer for the G7 legacy guard; do not duplicate a parser.
3. Reject new module-identity compatibility forwarders even under new filenames. Detect sys.modules mutations (including explicit alias and registry variable cases), module-level __getattr__, and wildcard re-exports. The checker is static and does not claim to prove arbitrary dynamically computed Python code.
4. Correct current docstrings referring to deleted paths, preserving historical logging identifiers and frozen historical evidence. Treat module-size warnings as deferred maintainability debt, not scope for another refactor.
5. After a guarded release, remove only ignored bytecode/cache directories from the two retired legacy namespace paths if safe, leaving production source and the user's dirty files untouched.

## Verification cadence

- During implementation: targeted pytest, Ruff, MyPy as part of normal commit hooks, Import Linter and static gate checks. Fix and rerun only affected tests.
- Candidate freeze: Git status clean, no source/runtime protocol changes beyond docstrings, full managed test suite (seed 12345, including ordinary no_xdist lane), module coverage policy and package smoke, Python 3.10–3.14 via required GitHub CI. Check exact four-client raw-wire parity against the frozen production baseline.
- Release: verified exact-SHA GitHub required checks, canonical guarded deploy, quiet window and rollback. Preserve original user-edited pyproject.toml and untracked docs using a checksum-bound temporary backup. Confirm live MCP, Jobs, Tunnel and Watchdog; real MCP read-only acceptance and namespace cache cleanup.
- Finish: remove only the clean, merged temporary development worktree and branch. Never force-delete unrelated worktrees or rewrite historical commits.

## Known compatibility decisions

The former 94 file paths remain prohibited. Logging names such as binnacle.jobs and binnacle.watchdog are intentionally retained because existing observability consumers may depend on them. The removed historical Python import and pickle paths remain unsupported; G7 already documented these breakages.

This document sets release requirements; it is not itself evidence that CI or deployment passed.
