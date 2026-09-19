# MCP prompts: who actually supports them

The three primitives are presented as co-equal in the MCP spec, which makes
"every major agent supports all three" a natural assumption. It is not true.
Prompts are the least implemented of the three, and the gap is documented by the
vendors themselves once you read the right page.

## Measured, 2026-08-30

Server-side JSON-RPC log against binnacle, which for the duration of the test
exposed a real prompt (`audit_data_dir`, taking a `focus` argument, whose text
carried an audit code that existed nowhere else). The prompt was removed
afterwards — only Claude Code could reach it, so it was dead weight; add one
back the same way to re-test. `prompts/get` reaching the server is the proof;
`prompts/list` alone is not, because a client can enumerate prompts and still
offer no way to run one.

| Client | `prompts/get` observed | How |
|--------|------------------------|-----|
| **Claude Code** 2.1.251 | **yes** | `/binnacle:audit_data_dir`, or `/mcp__binnacle__audit_data_dir <focus>`; arguments arrived intact (`{"focus":"file sizes"}`) and the default applied when omitted |
| Codex CLI 0.151.0 | no | neither surface. Its whole session was `initialize` / `server/discover`, `tools/list`, `tools/call` — it never even listed prompts |
| GitHub Copilot CLI 1.0.82 | no | no `prompts/*`, including under `--experimental`. Asked to use the prompt it fell back to the `read` tool and fetched the files itself |
| ChatGPT | no | the prompt is absent from the connector registry (`"prompt"` appears zero times), and asked to use it the server received **no request at all** — ChatGPT answered `NO_PROMPT_ACCESS` from its cached schema: *"the Raspberry Pi MCP connector exposes only ping, echo, write, read, and show_files; it does not expose the audit_data_dir prompt to me"* |

All four were exercised against a server that really does serve the prompt — the
local FastMCP control fetches it with arguments — so a `no` is the host's gap,
not the server's.

Codex was checked for a hidden switch, since its modern protocol turned out to
be flag-gated. Of its eight feature flags, **none relates to prompts** — this is
absence of implementation, not a default-off capability.

## What the vendors say

- **Claude** (claude.ai, Desktop, Code) —
  `claude.com/docs/connectors/building`, "Protocol features → Supported":
  *"Tools, prompts, and resources"*.
- **GitHub, for VS Code** —
  *"you can use MCP prompts and resources in VS Code … access these prompts in
  chat with slash commands, using the format `/mcp.servername.promptname`"*.
- **GitHub, for its other surfaces** —
  *"Copilot cloud agent and Copilot code review **only support MCP tools. They do
  not currently support resources or prompts** provided by the MCP server."*
  For the **CLI** GitHub says nothing at all; the open issue
  [copilot-cli#505](https://github.com/github/copilot-cli/issues/505) asks for
  prompt support and `listPrompts` is absent from the 1.0.80 binary.
- **Codex** — the "Supported MCP features" list covers transports and server
  `instructions` only. Prompts are never mentioned.
- **ChatGPT** — prompts appear only where OpenAI recites MCP's generic
  definitions; the Apps SDK documents tools, and `ui://` resources for UI.

So one product family, GitHub's, documents prompts for VS Code, explicitly
denies them for cloud agent and code review, and is silent for the CLI. Product
boundaries matter more than brand names.

## The retired client matrix agrees

`modelcontextprotocol.io/clients` was deleted on 2026-05-27 (commit
`2075a21d03`), but the last live version is recoverable and dated. It listed 114
clients, 43 marked `Prompts`:

| Client | `supports=` verbatim | Prompts |
|---|---|---|
| ChatGPT | Tools, Apps, DCR, CIMD, Instructions | no |
| Codex | Resources, Tools, Elicitation, Instructions | no |
| GitHub Copilot CLI | Tools, Discovery, Instructions, Sampling, Elicitation, DCR, OAuth CC, Tasks | no |
| GitHub Copilot coding agent | Tools, DCR | no |
| Claude Code | Resources, Prompts, Tools, Roots, Elicitation, Instructions, Discovery, DCR | yes |
| VS Code GitHub Copilot | Resources, Prompts, Tools, Discovery, Sampling, Roots, Elicitation, Instructions, Apps, CIMD, DCR, Tasks | yes |

Note Codex's row lists **Resources** but not Prompts — matching what we measured
on both counts. It was community-maintained, so it corroborates rather than
proves.

Other clients whose own docs claim prompt support: Goose (`/prompts`,
`/prompt <name> key=value`), Amazon Q Developer CLI (`/prompts`, `@prompt-name
args`), Cursor (listed as supported, no invocation surface documented), Windsurf
/ Cascade. Listed as prompt-capable in the old matrix but **not** claimed in
their own docs, so do not cite: Continue, opencode, Amp.

## Name collisions that look like prompt support

Several clients ship a `/prompts` command that has nothing to do with
`prompts/get`. Check the wire before believing any of them:

- **Codex** — `/prompts:` reads local Markdown from `~/.codex/prompts`.
- **Warp** — `/prompts` searches saved prompts in Warp Drive.
- **JetBrains AI Assistant** — its "invoke manually with a `/` command" refers
  to **tools**.

## Design consequence

Prompts cannot carry a feature today: of the four hosts measured here, one
supports them. If a capability should be user-triggered, ship it as a **tool**
with a description that states when to use it, and treat a prompt as an
ergonomic extra for the hosts that have one. This is the same conclusion
resources reach — tools are the only primitive that works everywhere.
