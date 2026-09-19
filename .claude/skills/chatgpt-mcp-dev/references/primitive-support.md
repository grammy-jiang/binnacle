# ChatGPT vs the three MCP primitives — findings and open questions

Investigated 2026-08-30 against the binnacle connector (Apps SDK, developer
mode, Pro account). Recorded because the result is surprising and the user
wants to revisit it: **ChatGPT implements only one of MCP's three primitives
for the model.**

| Primitive | Controlled by (core MCP) | ChatGPT |
| --------- | ------------------------ | ------- |
| Tools     | the model                | Full support |
| Resources | the host application     | Only as MCP Apps UI templates; never as data |
| Prompts   | the user                 | No support at all |

## What was actually tested

**Resources.** Added a static resource (`binnacle://station`, holding a code
that existed nowhere else) and a resource template (`binnacle://files/{name}`),
refreshed the connector, and asked a chat to read the resource. The server log
for that chat shows only `initialize` and `tools/call`. ChatGPT sent no
`resources/list`, `resources/templates/list`, or `resources/read` — those appear
in the log only from a local Python MCP client. Asked to "read the station card
resource", ChatGPT guessed at the `read` tool with `filename="station_card"` and
reported the resulting not-found error. It never saw the code.

**Resources as MCP Apps UI.** The same mechanism *is* used, but only through the
MCP Apps extension: a tool declares `_meta.ui.resourceUri` pointing at a `ui://`
resource holding HTML, and the host fetches it with `resources/read` and renders
it in a sandboxed iframe. Confirmed working end to end — the panel rendered, and
clicking inside it called `read` back on the server. So ChatGPT *can* fetch a
resource; it just never does so on the model's behalf for data.

**Prompts.** Added `audit_data_dir` (a prompt whose text contained a code that
existed nowhere else) and refreshed. The connector registry lists only the five
tools; `audit_data_dir` is absent and the string "prompt" appears zero times in
it. In a chat, ChatGPT sent no `prompts/list` or `prompts/get`, and said plainly
that the connector surface "did not expose the audit_data_dir MCP prompt", then
fell back to the tools. It never produced the code.

## Why, as far as the specs explain it

Core MCP (`modelcontextprotocol.io/docs/learn/server-concepts`) splits the
primitives by who drives them. Tools are model-controlled. Resources are
application-controlled — the host is expected to offer a picker, a file browser,
an attachment menu. Prompts are user-controlled — the host is expected to offer
slash commands or a command palette. ChatGPT ships neither surface, so neither
primitive has a path into a conversation. This is a product gap, not a protocol
limitation: other hosts do implement them.

## Corroboration from outside our own testing

- OpenAI's own docs say "Plugins primarily use tools", and the Apps SDK
  reference documents only tools for model use. Prompts appear nowhere.
- The MCP client support matrix (`github.com/modelcontextprotocol/docs`,
  `clients.mdx`) tracks Resources / Prompts / Tools / Sampling across 28
  clients. **ChatGPT and OpenAI are not listed at all.** Claude Desktop is
  listed with full support for all three.
- FastMCP's own ChatGPT integration page discusses only tools.
- `SEP-1814` in the MCP repo proposes a caniuse-style compatibility matrix
  precisely because "developers spend hours debugging issues that turn out to be
  unsupported features" — the gap we hit is a known, unsolved ecosystem problem.
- The OpenAI developer forum has many MCP connector threads, all about tools
  (routing failures, caching, annotations being ignored, regressions). Nobody
  reports prompts failing — apparently because nobody expects them to work.

## Open questions to revisit

1. Does ChatGPT ever add a resource picker or slash-command surface? That is
   what would unlock resources-as-data and prompts. Watch the Apps SDK
   changelog and the developer forum.
2. Does the OpenAI **Responses API** (as opposed to the ChatGPT app) consume
   resources or prompts from a remote MCP server? It re-lists tools on every
   request, so its client may be more complete. Not tested.
3. Do prompts work in **Codex** (CLI or app-server), which is a separate MCP
   client from ChatGPT? Not tested.
4. Does ChatGPT ever get added to the official client support matrix, and with
   what marks?

## How to re-test cheaply

Add a prompt and a data resource whose contents include a freshly generated
code that exists nowhere else. Refresh. In a chat, ask for that code. Then check
the server log for `prompts/list`, `prompts/get`, `resources/list`, and
`resources/read` from clientInfo `openai-mcp` — a local Python client's calls
look identical apart from the client name, so always separate by client and
timestamp. Absence of those methods, plus a missing code in the answer, is the
result. Delete the prompt and resource afterwards.
