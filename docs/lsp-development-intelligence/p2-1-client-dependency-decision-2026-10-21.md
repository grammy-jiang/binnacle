# P2.1 — Minimal in-house LSP JSON-RPC client (2026-10-21)

**Decision: GO for a small standard-library async JSON-RPC client.**
Source baseline: isolated feature branch at P2.0 commit 50a3393.
Production/root MCP tool registration is unchanged.

## Options

| Option | Strength | Cost / risk | Decision |
| --- | --- | --- | --- |
| Reuse P1 fake LspPeer unchanged | Tests framing and failures | Test-only synchronous subprocess wrapper; cannot route concurrent and reverse requests, mixes process ownership and protocol | Reject as production client; keep as test oracle |
| Add an external LSP client library | Possible protocol API shortcuts | New dependency/versioning and async/process lifecycle mismatch, uncertain correctness/safety contract | Defer until needed |
| Small stdlib asyncio + json client with injected reader/writer | No new dependency; explicit bounds/ID handling and P1 fault tests | We own protocol correctness and regression tests | Select |

## Boundaries

- lsp_wire.py: incremental bounded Content-Length framing and strict JSON.
- lsp_client.py: async request/response routing, IDs, cancellation,
  notifications and server-initiated requests; injected stdio only.
- lsp_policy.py: deterministic non-executing reverse request responses.
- lsp_session.py: LSP capability/encoding negotiation and lifecycle.
- **P2.4:** platform-specific process owner, pipe shutdown and child cleanup.
- **P2.5:** allowed workspace paths, URI checks and document synchronization.
- Production client does not spawn, discover, supervise or import any provider,
  and no new public tool is exposed. Configured enabled=true remains inert
  until the separately gated P2.7 mount.

## Acceptance

Native Python 3.10–3.14 tests, malformed/oversized/coalesced/split wire,
request timeout and cancellation, out-of-order/duplicate responses,
reverse requests, UTF-16 and real stdio interaction with the P1 fake LSP.
No raw source or server error body may be emitted on failure.

Reconsider a library only for a concrete unsupported capability after
measuring its maintenance/security cost against this narrow implementation.
