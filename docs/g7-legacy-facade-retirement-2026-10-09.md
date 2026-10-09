# Binnacle G7 — Legacy Facade Retirement (2026-10-09)

## Authorization and scope

G7 removes the 90 retained Python compatibility facades from G0–G6, plus two empty namespace initializers and two obsolete tunnel typing stubs (94 retired files / 92 module names). The user accepts intentionally breaking historical Python imports, including the old binnacle.doctor.Deployment pickle module path. Canonical Python objects and pickle round trips remain supported. Do not deserialize arbitrary old pickles to provide migration support.

Preserve public MCP tool ordering/names/descriptions/schemas/errors/client visibility, HTTP health/authentication behavior, the four installed CLI commands, systemd names, durable jobs JSON on-disk schema, IDs, and lifecycle. No feature refactor, new abstraction, or macOS implementation belongs in G7.

## Wave implementation

- W1 (7): 7415e0e — MCP, Files and Search.
- W2 (16): d3722d4 — Observability and Telemetry.
- W3 (13): 3b75ed1 — Diagnostics and Deployment.
- W4 (24): 2123627 — retired Watchdog ops namespace.
- W5 (12): ad3e171 — Watchdog/Tunnel root facades and typing stubs.
- W6 (17): 23cb267 — Commands and Jobs root facades; empty tools namespace.
- W7 (1): f894303 — final doctor.py alias.

The Watchdog→Tunnel dependency retains only canonical, specifically permitted imports of TUNNEL_UNIT and scan_tunnel_log. Effective canonical Import Linter boundaries stay enforced; two obsolete contracts exclusively targeting the removed legacy tools package were retired. New G7 static gate preserves the frozen 94-path history and disallows restoring old source files or runtime import spellings.

## Verification and guarded release

During waves, use relevant focused tests and the normal hooks, not repeated full pytest. On a clean final SHA, complete seeded managed suite including no_xdist lane, Python 3.10–3.14, coverage, packaging, architecture, remote CI and exact wire comparison, independent source review, canonical guarded deploy, post-deploy smoke and real read-only ChatGPT MCP client proof. Do not weaken safety gates.

The primary Raspberry Pi master checkout has unrelated user-owned uncommitted material that must remain unchanged. G7 development is isolated under /home/grammy-jiang/Projects/binnacle-g7-facade-cleanup; sextant provides independent test capacity only, not the deployment target.

This plan is not a claim that all release gates have passed.
