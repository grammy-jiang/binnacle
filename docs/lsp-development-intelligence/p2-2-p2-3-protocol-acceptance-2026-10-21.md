# P2.2–P2.3 — Private LSP protocol and capability session (2026-10-21)

**State:** Implementation validated on MacBook Pro with P1 synthetic
fixtures and real stdio; no real language-server provider was started.
No production Binnacle service, MCP tool surface or workspace content changed.

## Implementation

| Work | Source | Accepted behavior |
| --- | --- | --- |
| P2.2 | lsp_wire.py | Incremental and coalesced bounded Content-Length frames, UTF-8/JSON strictness, invalid headers/fields/numbers refused |
| P2.2 | lsp_client.py | Concurrent monotonic request IDs, out-of-order responses, notifications, bounded queues, timeouts, cancellation, late IDs, sanitized RPC errors, unexpected/duplicate response refusal |
| P2.3 | lsp_policy.py | Safe reverse RPC: edit, executeCommand, dynamic registration rejected; only fixed host-configurable sections; bounded progress/workspace replies |
| P2.3 | lsp_session.py | Single initialize attempt, explicit UTF-16 position encoding, strict capability gate, initialized/shutdown/exit messages, Unicode codepoint conversion |

## Independent fixture evidence

Real stdio tests launch only the preexisting fake fixture as a test-owned
subprocess. They test handshake, definition/hover results, disabled
capabilities, safe rejection of editor modifications and command execution,
split/coalesced framing, malformed server replies and graceful exit.

Out-of-order/duplicate request IDs, timeouts, cancellation, late replies,
bounded notifications, non-finite JSON and UTF-16 surrogate splitting are
covered by deterministic synthetic tests. A targeted independent review
identified an unbounded send-stage wait and a transport-error Future whose
exception was never retrieved. Both were corrected: request deadlines now
cover send/write lock/drain as well as response wait, reverse replies and
notifications also have bounded writes, and terminal Futures are consumed.
Tests explicitly exercise blocked writer, cancellation and broken drain. A Python 3.10 timeout exception
difference was found by native matrix tests and fixed.

No raw JSON-RPC messages, file content, returned sources or child stderr
are logged. Errors use fixed reason categories. The production client only
accepts injected streams and cannot itself create a process.

## Verification result

- MacBook Pro: **88 new P2.2/P2.3 tests passed** under CPython 3.10.22
  and 3.14.8, including 19 real stdio P1 fake-provider integration tests.
- Existing P1 tests: 373 passed; combined P1/P2.2/P2.3: **461 passed**.
- MCP tool surface contracts: 42 passed, 13 skipped, 2 xfailed.
- P2.0 config tests: 38 passed.
- Ruff/format, import contracts and startup manifest: passed; architecture
  checked 267 modules with zero reverse-dependency violations.
- Native Linux P2.2/P2.3 and real Provider integration are separate
  P2.8/P3 gates, not claimed by these macOS fixture tests.

## Deferred gates

- P2.4: Linux/macOS process ownership, subprocess cleanup and lost-worker policy.
- P2.5: authorized workspaces, URI resolution and didOpen/didChange/didClose.
- P2.6: manager registry, single-flight, resource limits and eviction.
- P2.7/P2.8: optional FastMCP mounting, native two-OS process integration,
  complete public tool/token contracts and release gates.
- P3/P4: real audited providers and agent-facing semantic results.

No real Pyright/clangd initialization, production containment, Agent token
savings or public Development Intelligence availability is asserted here.
