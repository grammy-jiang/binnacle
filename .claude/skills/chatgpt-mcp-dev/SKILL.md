---
name: chatgpt-mcp-dev
description: Develop and test an MCP server that is exposed to ChatGPT as a connector. Use when editing MCP tools and verifying them in ChatGPT, when a new or changed tool does not appear in ChatGPT, to refresh a connector's cached tool list from the terminal, and to clean up throwaway test chats created during testing. Covers the edit/reload/local-test/refresh/browser-test loop. Do not use for MCP servers consumed by Claude Code or other clients, and not for general ChatGPT usage. Local agent sessions on this Raspberry Pi only; it needs the desktop session D-Bus, an unlocked GNOME keyring, and a browser logged in to chatgpt.com. Never use from a remote or cloud agent.
---

# ChatGPT MCP development

Drive the full loop for an MCP server that ChatGPT reaches through a connector:
change a tool, verify it locally, sync ChatGPT's cached tool list, verify in a
chat, then remove the test chat.

Reference implementation: `~/Projects/binnacle` (FastMCP over an OpenAI tunnel).
Its `CLAUDE.md` holds the project-specific parts (auth, ports, unit names).

## Compatibility

Use this skill only with local agents on this Raspberry Pi. Everything that
talks to ChatGPT reuses the ChatGPT web session that the local Chrome profile
already holds, so it needs the desktop session D-Bus, an unlocked GNOME
keyring, and a browser logged in to chatgpt.com. Never use it from a remote or
cloud agent.

Since 2026-09-29 the ChatGPT side is the `chatgpt-web-operations` skill's
(`~/.claude/skills/chatgpt-web-operations`): the one ChatGPT client on this
host, with its own `.venv`, setup and recovery guide (`references/setup.md`)
and daily health check. This repository keeps no copy of it. What this skill
used for each job:

| Job | Command |
| --- | --- |
| Refresh a connector's tool list | `chatgpt-refresh NAME` (the skill's `refresh_connector.py`, same command line) |
| Read or set a Project's instructions | `project_settings.py --name NAME --show` / `--instructions FILE --apply` |
| List Projects | `list_projects.py` |
| Track, review and delete test chats | `clean_chats.py --track URL`, `--tracked --delete`, `... --backup DIR --apply` |
| Find a chat's id | `list_chats.py`, `search_chats.py` |
| Send a message (full pass) | `chatgpt-send` here, which runs the skill's `send_prompt.py` |

Below, `W=~/.claude/skills/chatgpt-web-operations/scripts`. The tools on `PATH`, restored with:

```bash
S=~/Projects/binnacle/.claude/skills/chatgpt-mcp-dev/scripts
ln -sf ~/.claude/skills/chatgpt-web-operations/scripts/refresh_connector.py ~/.local/bin/chatgpt-refresh
ln -sf $S/mcp-probe ~/.local/bin/mcp-probe
ln -sf $S/mcp-conformance ~/.local/bin/mcp-conformance
ln -sf $S/mcp-conformance-server ~/.local/bin/mcp-conformance-server
ln -sf $S/mcp-era-check ~/.local/bin/mcp-era-check
ln -sf $S/chatgpt-send ~/.local/bin/chatgpt-send
```

`chatgpt-send` runs in the skill's `.venv` and draws its window on an Xvfb
virtual display, never on the desktop (`--visible` shows it). `mcp-probe`
just reads a systemd journal, and `mcp-conformance` / `mcp-conformance-server`
drive local CLI clients — all three work for any host.

## Status: incubating in this project

This skill lives in `~/Projects/binnacle/.claude/` on purpose. It is being used
here until it proves stable, then it moves to `~/.claude/skills/` so every
project sees it. The commands already work from any directory, because they are
symlinked onto `PATH`; only the skill's own discovery is project-scoped for now.

To promote it later, move the directory and repoint its symlinks
(`chatgpt-refresh` points into the chatgpt-web-operations skill and stays):

```bash
mv ~/Projects/binnacle/.claude/skills/chatgpt-mcp-dev ~/.claude/skills/
S=~/.claude/skills/chatgpt-mcp-dev/scripts
for f in mcp-probe mcp-conformance mcp-conformance-server mcp-era-check chatgpt-send; do
  ln -sf $S/$f ~/.local/bin/$f
done
```

Then update the paths in the Compatibility section above, and drop this section.

## Pick the loop by what changed

Run the server under `uvicorn ... --reload`. Saving the source reloads it in
about 1 to 2 seconds. Reloading is not a manual step.

**Fast loop** — the body of a tool changed, but its name, parameters,
description, and annotations did not:

1. Edit and save.
2. Run the project's local MCP client (binnacle: `.venv/bin/python test_client.py`).

Stop there. ChatGPT's cached schema is still correct, and every `tools/call`
already runs the live server code. Do not refresh. Do not open a browser.

**Full loop** — the tool surface changed (a tool was added, removed, or renamed,
or its parameters, description, or annotations changed):

1. Edit and save.
2. Run the local client. Do this **before** the refresh. It proves the server
   reloaded, and a syntax error shows up here as a connection failure, so a
   broken build never reaches ChatGPT.
3. `chatgpt-refresh "<connector name>"` — sync ChatGPT's cached schema.
4. Verify in ChatGPT in a new chat, and delete that chat when the test ends
   (owner rule, 2026-09-27). `chatgpt-send` does this from the terminal (see
   "Full pass test").

## Refresh the connector tool list

ChatGPT caches each connector's tool schema. A changed tool surface is invisible
to a running chat until the cache syncs.

```bash
chatgpt-refresh --list                 # your connectors, live
chatgpt-refresh "Raspberry Pi MCP"     # exact name, or a unique substring
```

The name match is case-insensitive: exact first, then unique substring, so
`chatgpt-refresh raspberry` works. The command prints the tool list it synced;
report that list. It discovers connectors itself — there is nothing to register.
Since 2026-09-29 `chatgpt-refresh` is the chatgpt-web-operations skill's
`refresh_connector.py` under its old name; `--dry-run` resolves the name
without refreshing.

A brand new chat re-syncs on its own. The refresh is still needed for the chats
that already exist, such as the owner's own. Tests use a new chat and delete it
when they end, so test chats never pile up (owner rule, 2026-09-27).

If a chat still shows a stale tool list, that is a ChatGPT snapshot glitch, not
a server fault. Resend the message, or refresh again.

In the seconds after the tunnel client restarts, ChatGPT answers the refresh
with HTTP 424 ("Connection timed out" / "Connection failed") while its tunnel
service re-registers the poller. `chatgpt-refresh` retries that up to five
times, ten seconds apart, and says so on stderr; `--no-retry` fails at once.

## Project instructions from the terminal

A ChatGPT Project's instructions are the prompt layer above the tool
descriptions; both together are what the model reads about how to work.
The chatgpt-web-operations skill manages them without the browser (backend:
a Project is a "snorlax" gizmo; update is `PATCH /backend-api/projects/<id>`
with name, emoji, theme and instructions):

```bash
python3 $W/list_projects.py
python3 $W/project_settings.py --name "Raspberry Pi 5" --show
python3 $W/project_settings.py --name "Raspberry Pi 5" \
  --instructions references/project-instructions.txt --apply   # canonical rules text
```

Without `--apply` it shows the change and sends nothing; with it, it reads the
text back and fails on a mismatch. Keep the canonical text in
`references/project-instructions.txt` and change it there, so the rules are
versioned next to the evidence that produced them.

## Full pass test: a real tool call from a chat

Listing tools proves connection and auth, not that a call round-trips. The
full pass is: send a message in a chat, see the call and its arguments in
the server journal, and read the reply in the chat. `chatgpt-send` does the
browser half without hands, and with no window on screen: it drives a
headed system Chrome through Playwright on an Xvfb virtual display (headless
Chrome is Cloudflare-challenged, so a real headed browser on a virtual
screen is what works), logged in by injecting the browser's own chatgpt.com
cookies, types the message, approves a connector confirmation card if one
appears, waits for the reply to settle, and prints it. Pass `--visible` to
watch it on your real screen; it self-heals a missing DISPLAY either way. A
pure backend-API send like chatgpt-refresh is not possible: posting a
message requires a Cloudflare Turnstile token, which only a browser can
produce (`/backend-api/sentinel/chat-requirements` returns
`turnstile.required: true`).

```bash
NONCE="e2e-$(date +%H%M%S)-$RANDOM"; T0=$(date +%T)
chatgpt-send --browser chrome --chat <conversation id or URL> --json \
  "Use the Raspberry Pi MCP connector. Run this exact command in \
   ~/Projects/binnacle with run_command and reply with its exact output, \
   nothing else: uname -n && echo $NONCE"
journalctl --user -u binnacle-mcp --since "$T0" --no-pager -o cat \
  | grep -E "tools/call|arguments|$NONCE|event=job_|event=tool_result"
```

A pass is the nonce in three places: the journal's `arguments`, the
`event=job_start` command, and the printed reply. Use a nonce every time;
without one a cached or earlier reply is indistinguishable from a new one.
Prefer an existing test chat (`--chat`); `--new` starts one and prints its
URL, which you must then track with `python3 $W/clean_chats.py --track URL`.
To test a Project's instructions, the chat must live inside that Project:
`--project g-p-<id>` (id from `python3 $W/list_projects.py`) types on the
project page, which starts a new chat there; track it the same way. The result's
`buttons_seen` lists every button the page offered while waiting, which is
how to tell a silent client-side block from an unclicked confirmation card. The Chrome
window is drawn on an Xvfb virtual display for the duration, headed but never
on the desktop (headless Chrome gets a Cloudflare challenge). Verified
2026-09-03: two nonce runs, both replies exact, both calls in the journal.

One tool is not the full test. Cover every tool the client is served (for
ChatGPT: read_file, list_files, search_text, run_command, job_status,
stop_job) with one message each, or grouped where the tools chain. A recipe
that passed on 2026-09-03 with exact replies for all six:

- Fixture: `mkdir -p /tmp/binnacle-$N/sub`, a `marker.txt` with the nonce
  on line 2, a `b.py`, and `sub/c.md` containing `needle-$N`.
- list_files: "list_files on /tmp/binnacle-$N recursively; reply with only
  the relative paths, one per line."
- read_file: "read_file on /tmp/binnacle-$N/marker.txt line 2 to 2; reply
  with only that line."
- search_text: "search_text pattern needle-$N in /tmp/binnacle-$N; reply with
  only file:line."
- run_command + job_status + stop_job, one message: "run_command with
  background=true, command `sleep 300; echo done-$N`; job_status on it;
  stop_job on it; job_status again. Reply with four lines: job_id, then the
  state after each call." Expect `running`, then `exited 15` twice, and
  `signal: 15` in that job's `meta.json` with a runtime of a few seconds.

Then remove the fixture. Each `chatgpt-send` run takes 30 to 60 s.

To find an existing test chat's id without the browser:
`python3 $W/list_chats.py --match TEXT` (titles) or
`python3 $W/search_chats.py TEXT` (contents).

## Test chats: track the id, then delete by id

Only open a new chat when the test needs one. When you do, record its id as soon
as the chat exists. A browser tab on a chat is `https://chatgpt.com/c/<id>`, so
the id is free — take it from the tab URL.

```bash
B=~/.local/share/chatgpt-chats/backups
python3 $W/clean_chats.py --track "https://chatgpt.com/c/<id>" --note "what this test was"
python3 $W/clean_chats.py --tracked --delete                       # review; changes nothing
python3 $W/clean_chats.py --tracked --delete --backup $B --apply   # back up each, delete, clear the ledger
```

`--track` accepts a bare id or a full URL. The ledger is
`~/.local/share/chatgpt-chats/test-chats.json`, the same file `chatgpt-chats`
kept until 2026-09-29. `--backup` writes a full JSON copy of each conversation
first, and a chat whose copy fails is not deleted.

Clean up test chats at the end of the work, and report which ones went.

## Deletion rules

Deleting a chat is not reversible, and nothing in a conversation's metadata
marks it as a test. The user's chat list is mostly real personal conversations.

- Delete by tracked id (`--tracked`) or exact id (`--id`). That is exact and
  cannot hit a real conversation.
- Never delete by guessing at titles. `clean_chats.py --match TEXT --delete`
  exists only for chats that were never tracked. It is a dry run until
  `--apply`, refuses patterns under 3 characters, and with `--max 5` refuses
  an apply to more than five chats. Show the dry run to the user and let them
  confirm before deleting on a pattern.
- Delete only chats created for testing. Anything else needs the user to ask.
- `--untrack` drops an id from the ledger and deletes nothing.

## Build the surface out of tools

MCP has three primitives, and they differ by **who controls them** — that is what
decides whether ChatGPT ever touches them:

| Primitive | Controlled by | Core MCP purpose                                                     |
| --------- | ------------- | -------------------------------------------------------------------- |
| Tools     | the model     | functions the model calls                                            |
| Resources | the host app  | passive read-only data for context (file contents, DB schemas, docs) |
| Prompts   | the user      | templates the user explicitly invokes                                |

Only tools are model-controlled, so only tools work by the model deciding to use
them. Resources and prompts need the host to offer UI — a resource picker, a
slash-command menu — and ChatGPT offers neither. That is the whole reason a data
resource is invisible there: not that resources are unsupported in principle,
but that nothing in ChatGPT lets the application or the user pull one in.

**Tools** — fully supported, and the whole surface in practice. OpenAI's plugin
docs say plainly that "Plugins primarily use tools".

**Resources** — never fetched as data. ChatGPT fetches a resource in exactly one
flow, the MCP Apps extension: a tool declares `_meta.ui.resourceUri` pointing at
a `ui://` resource that holds an HTML page; the host fetches it and renders it in
a sandboxed iframe beside the conversation, talking over a `ui/*` JSON-RPC bridge
on `postMessage`. That is a UI delivery channel that reuses the resource
mechanism — it is not resources doing their core job.

**Prompts** — no support. Verified 2026-08-30: a prompt was added to binnacle
and the connector refreshed. The connector registry lists only the five tools;
`audit_data_dir` is absent and the word "prompt" appears zero times in it. In a
chat, ChatGPT never sent `prompts/list` or `prompts/get` (those appear in the
server log only from a local Python client) and said plainly that the connector
surface "did not expose the audit_data_dir MCP prompt", then fell back to the
tools. OpenAI's docs list prompts only when reciting MCP's generic definitions.

Other hosts do implement resources and prompts as intended (Claude Desktop
exposes resources through its attachment UI, and prompts as slash commands), so
resources are still worth adding if another client will consume the same server.

Reference files carry this work, so none of it has to be redone:

- `references/primitive-support.md` — the ChatGPT investigation: what was
  tested, the evidence, outside corroboration, and the open questions the user
  wants to revisit. Read it before re-testing any of this.
- `references/client-conformance.md` — a repeatable 14-test battery for
  establishing what *any* MCP host implements, with results for ChatGPT, Claude
  Code, Codex and Copilot CLI.
- `references/protocol-eras.md` — legacy vs modern (2026-07-28): what our server
  speaks, what each client picks, and the verified upgrade path.
- `references/mcp-apps-portability.md` — does a `ui://` component run outside
  ChatGPT? (Desktop hosts yes, terminal hosts no.) Includes the
  `_meta.ui.visibility` trap that hides a tool from the model in Codex CLI.
- `references/prompt-support.md` — who implements MCP prompts (of four hosts
  measured, only Claude Code), what each vendor documents, and the `/prompts`
  name collisions that look like support and are not.
- `references/resource-context-flow.md` — once a resource is read, does its
  content reach the model and stay in history? (Yes to both; an `@` mention is a
  lazy reference and the content lands as a tool result.) Also: tools vs
  resources is about **discoverability**, not access — in Claude Code the model
  can list and read resources unaided; what it lacks is any prompt telling it to.

## Protocol eras

Two questions, two tools — keep them apart:

```bash
mcp-era-check --url http://127.0.0.1:8000/mcp   # does OUR SERVER speak both eras?
mcp-conformance run claude codex copilot        # which era does each CLIENT pick?
```

Legacy (2024-11-05 … 2025-11-25) negotiates with `initialize`; modern
(2026-07-28) has no handshake — `server/discover`, stateless requests,
`mcp-protocol-version` / `mcp-method` headers and a `params._meta` envelope.
Asking for 2026-07-28 inside an `initialize` is not a modern request and will
be answered with the latest handshake version instead.

binnacle on FastMCP 3.4.7 is **legacy only**; FastMCP 4.0.0b5 makes it
**dual-era with no code change**. Claude Code and Copilot CLI already prefer the
modern era when a server offers it. Details, measurements and the verified
upgrade path: `references/protocol-eras.md`.

## Surveying what a client supports

For any client with a CLI, the whole battery is scripted — nothing to read, no
agent output parsed:

```bash
mcp-conformance-server --reset &            # throwaway probe server on :8899
mcp-conformance run claude codex copilot    # ~90s
mcp-conformance report [--json]
```

It exposes one of every primitive, records each JSON-RPC method the client
sends, and prints the verdict from that log. Add a client by extending
`CLIENTS` in `scripts/mcp-conformance`.

## Measuring what a client really did

`mcp-probe` reads the server log and reports which MCP methods each client
actually called, so a host's own account of itself is never the evidence:

```bash
mcp-probe --since "-30 min" --primitives    # defaults to unit binnacle-mcp
```

It tells clients apart by `clientInfo.name` (ChatGPT is `openai-mcp`, a local
FastMCP client is `mcp`), and separates `ui://` reads from data reads, so
`resources=UI-ONLY` is distinguishable from real resource support. Always run
`test_client.py` alongside as a control: if the control reaches a feature and
the host does not, the gap is the host's, not the server's.

Verified on 2026-08-30 against binnacle: a static resource plus a resource
template were added, the connector refreshed, and a chat asked to read the
resource. The server log for that chat shows only `initialize` and `tools/call`.
ChatGPT sent no `resources/list`, `resources/templates/list`, or
`resources/read` — those appear only from a local Python MCP client. Asked to
"read the station card resource", ChatGPT guessed at the `read` tool with
`filename="station_card"` and reported the not-found error. The refresh response
and the connector metadata endpoints contain only `actions`.

So: to give ChatGPT data, give it a tool that returns that data. Add resources
only to serve a UI component, or for a different MCP client (such as Claude
Code) that consumes the same server.

Sources: `modelcontextprotocol.io/docs/learn/server-concepts` (the control table
above; resources are "passive data sources that provide read-only access to
information for context"), `developers.openai.com/plugins/concepts/mcp-server`
("Plugins primarily use tools"), `developers.openai.com/plugins/build/chatgpt-ui`
("ChatGPT implements the open MCP Apps standard for UI returned by an MCP server
... Declare the UI resource with `_meta.ui.resourceUri`"), and the MCP Apps
extension spec at `modelcontextprotocol.io/docs/extensions/apps` ("the host
fetches the UI resource from the server. This resource contains an HTML page").
OpenAI's own docs are reachable as an MCP server at
`https://developers.openai.com/mcp` — useful for checking claims like these
against primary text.

## MCP Apps: a UI component beside the conversation

A tool can render an interactive HTML panel in the chat. FastMCP supports this
natively (`fastmcp.apps.AppConfig`). Two pieces:

```python
@mcp.resource("ui://<name>", app=AppConfig(prefers_border=True))
def my_ui() -> str:
    return HTML  # a ui:// resource gets text/html;profile=mcp-app free


@mcp.tool(app=AppConfig(resource_uri="ui://<name>"))
def my_tool() -> dict:
    return {...}  # also return plain data: clients without UI need it
```

Inside the component, `window.openai` is the bridge: `toolOutput` holds the tool
result, `callTool(name, args)` calls back into the server, `setWidgetState` /
`widgetState` persist state across re-mounts. Listen for `openai:set_globals` to
re-render when the host pushes new data — and keep your own view state across
that event, or a re-render will wipe what the user opened.

### The component bundle is cached hard — plan for it

ChatGPT caches the fetched component per `resourceUri`, and neither
`chatgpt-refresh` nor a brand-new chat reliably clears it. Editing the HTML and
refreshing will keep showing the OLD component, silently. This wasted a long
debugging session; the symptom is that edits appear to do nothing.

What actually works: **make the fetch fail once, then restore it.** Rename the
resource (e.g. `ui://x` to `ui://x/v2`) and refresh — the chat then asks for the
old URI, which no longer exists, and shows "Error loading app / Failed to fetch
template". Rename it back and refresh again, then hit Retry (or ask for the panel
again): that failed fetch invalidates the cache, and the next fetch serves the
new component.

While iterating, put a visible version marker in the component (a title suffix
or a small diagnostic line) so you can always tell which build is on screen.
Without one, a cached build is indistinguishable from a broken edit.

## Tool annotations

Declare annotations on every tool so ChatGPT can tell reads from writes:
`readOnlyHint: True` for read-only tools, `destructiveHint: True` for tools that
overwrite or delete. They drive the READ versus write labels in the connector UI
and the per-action permission prompts. Without them ChatGPT treats every tool as
destructive.

## Troubleshooting

- **HTTP 403, "could not authenticate", a Cloudflare challenge**: these are
  the chatgpt-web-operations skill's; follow its `references/setup.md`
  ("Fix a failed check") and run its `preflight.py` before retrying.
- **"key not found in the GNOME keyring"**: the keyring is locked, or the agent
  is not running in the desktop user's session. On an autologin machine the
  keyring is locked at every boot because no login password is entered. Fix it
  once by giving the "Default keyring" an empty password, so it auto-unlocks:
  run `scripts/set-empty-keyring-password` in a terminal (it prompts for the
  current password, calls the same private gnome-keyring D-Bus method Seahorse
  uses, and verifies). It must run in your own TTY, because it reads the
  password with getpass and never stores it.
- **A tool call reaches ChatGPT but not the server**: check the server log
  (binnacle: `journalctl --user -u binnacle-mcp -f`). The middleware logs each
  method and its payload, which distinguishes a stale ChatGPT schema from a
  server fault.
