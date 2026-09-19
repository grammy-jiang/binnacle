# MCP protocol eras: what our server speaks, and what clients want

Two different questions, two different tools. Do not conflate them.

| Question | Tool | Subject |
|----------|------|---------|
| Does *our server* speak both eras? | `mcp-era-check --url …` | the server |
| Which era does *a client* choose? | `mcp-conformance run …` | the client |

## The split

MCP divides into eras that are not two dialects of one handshake:

* **legacy** — `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`.
  `initialize` negotiates a version; the session carries `Mcp-Session-Id`.
* **modern** — `2026-07-28`. No handshake. Discovery is `server/discover`, and
  every request is stateless and self-describing: `mcp-protocol-version` and
  `mcp-method` headers (plus `mcp-name` on a tool call) and a `params._meta`
  envelope carrying `io.modelcontextprotocol/protocolVersion` and
  `io.modelcontextprotocol/clientCapabilities`.

The Python SDK encodes exactly this (`mcp_types.version`):

```
HANDSHAKE_PROTOCOL_VERSIONS = ('2024-11-05','2025-03-26','2025-06-18','2025-11-25')
MODERN_PROTOCOL_VERSIONS    = ('2026-07-28',)
LATEST_HANDSHAKE_VERSION    = 2025-11-25
```

**Asking for `2026-07-28` inside an `initialize` is not a modern request.** A
correct server answers with its latest *handshake* version, which looks like a
downgrade and is not one. Testing the modern era through `initialize` will
always produce a false negative — that mistake cost an hour here.

## Where our server stands

**binnacle runs FastMCP 4.0.0b5 and is dual-era** (upgraded 2026-08-30).

| Stack | Legacy | Modern | Verdict |
|-------|--------|--------|---------|
| FastMCP 3.4.7 + mcp 1.29 (previous) | all four versions | ✗ `Bad Request: Missing session ID` | legacy only |
| FastMCP 4.0.0b5 + mcp 2.0.0 (**now**) | all four versions | ✓ stateless `tools/list` and `tools/call` | **dual-era** |

`server.py` needed **no changes** — era support comes entirely from the SDK.
The only code change anywhere was in `test_client.py`, where SDK v2 renamed
`Tool.inputSchema` to `input_schema` (handled with a `getattr` fallback so the
file still works on either SDK).

FastMCP 4 is a beta; 3.4.7 is the latest stable and is pinned to `mcp<2.0`,
which is what caps it at 2025-11-25. To roll back:
`uv pip install --python .venv/bin/python 'fastmcp==3.4.7'` then restart
`binnacle-mcp`. Previous pins: fastmcp 3.4.7, fastmcp-slim 3.4.7, mcp 1.29.0,
mcp_types 2.0.0.

One transient to expect: right after restarting `binnacle-tunnel`, the first
`chatgpt-refresh` can fail with `HTTP 424 Connection timed out` while the tunnel
settles. The tunnel log says `mcp session initialized` and the server logs the
`initialize` — retry after ~15s. Not an SDK incompatibility.

## Where the clients stand, 2026-08-30

Measured against a **dual-era** server, so each client could pick freely. This
distinction matters: against the old legacy-only binnacle every one of these
looked like a legacy client, because none of them had anything to negotiate up
to. Re-measure after any server-side era change.

| Client | Era chosen | Version requested | Evidence |
|--------|-----------|-------------------|----------|
| **ChatGPT** — `openai-mcp(ChatGPT)` v1.0.0 | **modern** | 2026-07-28 | `server/discover` with the `_meta` envelope |
| **Claude Code** 2.1.251 | **modern** | 2026-07-28 | `server/discover` |
| **GitHub Copilot CLI** 1.0.82 | **modern** | 2026-07-28 | `server/discover` |
| Codex CLI 0.151.0, default | legacy | 2025-06-18 | `initialize` |
| Codex CLI 0.151.0, **flag on** | **modern** | 2026-07-28 | `server/discover` |
| OpenAI `tunnel-client` 0.0.12 | legacy | 2025-06-18 | `initialize` |

All four hosts can speak the modern era. **Codex ships it but keeps it off**,
behind an under-development feature flag:

```toml
# ~/.codex/config.toml
[features]
mcp_2026_07_28 = true
```

or `codex features enable mcp_2026_07_28` (which warns that under-development
features "may behave unpredictably"). Verified here: with the flag off Codex
sends `initialize` asking for 2025-06-18; flip it on and the same binary sends
`server/discover` with 2026-07-28. The flag was restored to its default
afterwards.

For a **stdio** server the flag alone is not enough — that server's `env` must
also carry `CODEX_MCP_PROTOCOL_VERSION = "2026-07-28"`, and without it Codex
silently downgrades to legacy with no warning. Streamable HTTP needs only the
flag; it probes `server/discover` and falls back only if the endpoint proves
legacy-only.

The OpenAI `tunnel-client` asks for the same 2025-06-18 as default-Codex, which
suggests both sit on the same Rust MCP client stack — while ChatGPT's backend, a
different implementation, is modern out of the box.

**Methodology note.** A capability can exist and be flag-gated off. A probe
measures *configured* behaviour, not *possible* behaviour, so "legacy" from
`mcp-conformance` means "legacy as configured" — check the host's feature flags
before concluding it cannot do better.

They are all dual-era in practice, so a legacy-only server still works today:
pointed at the pre-upgrade binnacle, ChatGPT and Claude Code fell back to
`initialize` without complaint. The exposure was never today's breakage — it was
that a legacy-only server holds modern clients down and has nothing to offer
when one eventually drops the fallback.

ChatGPT's modern request, from binnacle's own log:

```json
{"method":"server/discover","params":{"_meta":{
  "io.modelcontextprotocol/protocolVersion":"2026-07-28",
  "io.modelcontextprotocol/clientInfo":{"name":"openai-mcp(ChatGPT)","version":"1.0.0"},
  "io.modelcontextprotocol/clientCapabilities":{...}}}}
```

Note where `clientInfo` lives: **inside `_meta`, under a namespaced key**, not at
the top level as in `initialize`. Anything that identifies clients by a
top-level `clientInfo` sees every modern client as anonymous — that bug was in
`mcp-conformance-server` until it was fixed here.

## Upgrade path, verified

Everything below was run, not assumed:

1. `uv pip install "fastmcp==4.0.0b5"` into a scratch venv.
2. `import server` under it — clean, no code change.
3. `mcp-era-check` against it — `dual-era`.
4. Legacy clients still negotiate all four handshake versions.

To adopt: install FastMCP 4 in the project venv and restart `binnacle-mcp`, then
re-run `test_client.py`, `mcp-era-check`, and one ChatGPT round trip. To roll
back, reinstall `fastmcp==3.4.7`. The decision is a beta-in-production
judgement, not a technical obstacle.

## Codex's modern lane, from its own repo

Not documented on `learn.chatgpt.com` — none of the MCP page, the config
reference's `[features]` table, or the changelog mentions `2026-07-28`,
`server/discover`, or the flag. The evidence is in `openai/codex`:

- Shipped in **0.147.0** (2026-08-07): "Support the opt-in MCP 2026-07-28
  protocol, including paginated discovery, multi-round requests, and
  non-blocking server startup" ([PR #35724](https://github.com/openai/codex/pull/35724),
  [#35725](https://github.com/openai/codex/pull/35725)).
- `codex-rs/rmcp-client/src/protocol_mode.rs` defines `McpProtocolMode::Legacy`
  (the `#[default]`) and `V20260728`; the modern mode prefers 2026-07-28 with
  2025-06-18 as the legacy fallback.
- `codex-rs/features/src/lib.rs` marks the flag `Stage::UnderDevelopment`,
  `default_enabled: false` — still so at 0.151.0 and 0.152.0-alpha.1.
- `scripts/mcp_conformance/` runs the official MCP conformance suite against the
  real binary across 2025-06-18, 2025-11-25 and 2026-07-28, with 312 passing
  official-http checks on the modern lane and 12 known failures. The lane is
  real and heavily tested, just gated.

Known rough edges before relying on it: multi-round `input_required` fails on
the modern lane ([#40657](https://github.com/openai/codex/issues/40657)), and
there is no way to confirm the negotiated version from the CLI
([#33952](https://github.com/openai/codex/issues/33952), open). Also worth
knowing: `subscriptions/listen` appears only in Codex's *test* server, not in
its client — so Codex does not consume the modern change-notification API.

Correction to a claim circulating in blog posts: there is **no**
`protocol_version = "2026-07-28"` config key. It does not exist in the source or
in `config.schema.json`. The flag is the only switch.

## Notes from the user's ChatGPT research threads (2026-08, second-hand)

Useful leads, not verified here, and their version numbers already trail this
machine (they cite Copilot CLI 1.0.80, Codex 0.148, Claude Code 2.1.238):

- Recommended server profile: Streamable HTTP + tools + legacy handshake +
  modern stateless wire — i.e. dual-era, which matches what we measured.
- Do not serve both eras through one wire format; branch on the era.
- Both eras require an `inputSchema` root of `object`; 2026 allows full JSON
  Schema 2020-12. Keep to the common subset (`object`, `properties`, `required`,
  `additionalProperties`, `enum`, `minimum`/`maximum`, `pattern`) for portability.
- Both eras support `outputSchema` + `structuredContent`; keep text content
  alongside structured content rather than going structured-only.
- Copilot CLI `1.0.81-*` prereleases were reported to have a dual-era
  negotiation regression — avoid that line.
- Codex waits ~1s for an optional MCP server before capturing the tool catalogue,
  so a fast cold start is a portability nicety (a SHOULD, not a MUST).
- A client that sends `initialize` after a modern connection is locked is
  misbehaving; the server should reject the cross-era transition rather than
  accommodate it.
