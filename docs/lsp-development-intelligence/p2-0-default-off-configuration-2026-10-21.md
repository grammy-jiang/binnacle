# P2.0 — Strict optional Development Intelligence configuration

**State:** Implemented in an isolated feature worktree on 2026-10-21.
**Scope:** Configuration only. No MCP child mounted, provider discovered,
process spawned, production service restarted, or new user-visible tool.

## Operator contract

- The development_intelligence.enabled setting defaults to false. It must be
  intentionally enabled per host; a nondeveloper sees no additional tools.
- The separate discovery_enabled option is also false by default; it cannot
  be enabled while the overall feature is disabled.
- max_resident_servers (1–8, default 2), request_timeout_s (positive to
  120 seconds, default 30) and idle_timeout_s (0–3600, default 120) are
  validated but do not start any runtime workers in P2.0.
- Provider definitions are strictly typed under development_intelligence.profiles:
  enabled, source, executable, argv, env, languages, mode. Unknown provider
  identifiers or fields fail validation, including while the feature is off.
- service_path executable is a bare name only. trusted_absolute requires an
  absolute path and explicit_trust_only mode; neither choice authorizes
  execution or certifies provider READ safety. No project-local executable
  auto-discovery or PATH lookup occurs at configuration load time.
- Feature table/env near misses fail startup. Existing unrelated legacy
  top-level settings retain their backwards-compatible behavior.
- Environment override prefix: BINNACLE_DEVELOPMENT_INTELLIGENCE__.

A deliberately enabled configuration is **inert in P2.0**. Public MCP
mounting and provider ownership are separate P2.7/P3 release gates.

## Deliverables

- src/binnacle/config_development_intelligence.py — strict feature/provider model
- src/binnacle/config.py — default-off settings and typo rejection
- src/binnacle/startup_server_modules.py — updated import inventory
- tests/unit/core/test_development_intelligence_config.py — deterministic unit
  and in-memory MCP tool-surface parity tests

## Acceptance

Run focused P2.0 and legacy configuration tests, in-memory six/eight MCP
tool-surface equality with enabled on/off, native Python 3.10/3.14,
startup module inventory, Ruff, architecture/import contracts.

**Next implementation:** P2.1 JSON-RPC client dependency decision, P2.2
dispatcher and P2.4 native cross-platform provider process owner.
Do not revive E2/E3 historical analysis or represent its output as a
precondition for development.
