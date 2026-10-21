# P2 migration: no Binnacle-local Pyright Adapter — 2026-10-22

Decision: **only the pinned multilspy fork defines and maintains `PyrightServer`**.
Binnacle is the owner of workspace admission, request authorization, result
filtering, provider registry, process policy and MCP-facing tools. The old
subclass factory was a private proof of concept, not a second production
language-server stack.

Cleanup in `feat/lsp-upstream-cleanup-20261022`:

- **Deleted** `src/binnacle/features/development_intelligence/multilspy_pyright.py`,
  including its copied LSP initialization, diagnostics, provider lifetime and
  custom `PyrightAdapter` class. No equivalent class replaced it.
- **Retained** provider-agnostic path and result guards in
  `src/binnacle/features/development_intelligence/lsp_workspace_policy.py`.
  These remain preliminary P2.5 guards, **not** an OS sandbox or TOCTOU proof.
- Migrated the former feature corpus from the custom class to the native
  multilspy `LanguageServer.create(...python_server="pyright"...)`, using
  pinned-source and binary identity checks from the new private QA tests.
  The redundant legacy class smoke and old optional test wrapper were removed.
- Regenerated the frozen startup manifest using the repository's generator;
  test coverage enforces that no Binnacle-local `PyrightServer`/`PyrightAdapter`
  class returns.

The prior fake JSON-RPC client/transport under `lsp_client.py`, `lsp_wire.py`,
and `lsp_session.py` is retained **only as a P1/P2.2-P2.3 test oracle** until
P2.4 migrates process and protocol ownership to the patched library. It must
not become another production JSON-RPC client. This cleanup does not mount a
new MCP tool, change existing public schemas, deploy, restart services, or
claim privileged read-only status for Pyright; command-side type-stub writing
requires separate OS confinement.

The dependency pin must ultimately select the **exact upstream fork commit**,
not distribution metadata `multilspy==0.1.1` alone. Binnacle opt-in remains
default-off, and the dependency must not become a mandatory runtime import.
