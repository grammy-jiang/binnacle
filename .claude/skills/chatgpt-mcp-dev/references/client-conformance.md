# MCP client conformance suite

A repeatable way to establish what an MCP *host* actually implements, rather
than what its documentation claims. Written after ChatGPT turned out to
implement only one of MCP's three primitives; the same battery applies to Claude
Desktop, Claude Code, Codex, GitHub Copilot, or any other client.

## Two separate questions

Keep these apart; they need different tools and answer different risks.

**Does *our server* speak both protocol eras?** — `mcp-era-check --url …`. It
probes each era the way that era is meant to be spoken and prints `dual-era` /
`legacy only` / `modern only`.

**Which era and which primitives does *a client* use?** — `mcp-conformance`.
Note the probe server must itself be dual-era, or a modern-capable client has
nothing to negotiate up to and will be scored as legacy. Run it from a venv with
`fastmcp>=4`:

```bash
uv venv ~/.local/share/mcp-conformance/venv --python 3.13
uv pip install --python ~/.local/share/mcp-conformance/venv/bin/python "fastmcp==4.0.0b5"
~/.local/share/mcp-conformance/venv/bin/python <skill>/scripts/mcp-conformance-server --reset &
```

### The two eras are not two dialects of one handshake

* **legacy** — 2024-11-05 … 2025-11-25. `initialize` negotiates the version;
  the session carries an `Mcp-Session-Id`.
* **modern** — 2026-07-28. No handshake. Discovery is `server/discover`, every
  request is stateless and self-describing: `mcp-protocol-version` and
  `mcp-method` headers (plus `mcp-name` for a tool call) and a `params._meta`
  envelope with `io.modelcontextprotocol/protocolVersion` and
  `…/clientCapabilities`.

Two consequences worth internalising. Asking for `2026-07-28` inside an
`initialize` is **not** a modern request — a correct server answers with its
latest *handshake* version, which looks like a downgrade but is right. And a
modern request puts `clientInfo` inside `_meta` under a namespaced key rather
than at the top level, so attributing calls by a top-level `clientInfo` silently
stops working; `mcp-conformance` therefore brackets each client's phases with
markers in the log and attributes by time window.

## Run it

For any client with a CLI, this is scripted — no agent output is parsed and no
one has to read prose:

```bash
mcp-conformance-server --reset &          # throwaway probe on :8899
mcp-conformance run claude codex copilot  # ~90s for all three
mcp-conformance report                    # or --report --json to feed a matrix
```

The probe server exposes one of every primitive and records each JSON-RPC method
a client sends. `mcp-conformance` configures the client, runs two sessions with
fixed prompts, removes the configuration, and prints the verdict from the log
alone. Add a client by extending `CLIENTS` in the script: a way to register an
HTTP MCP server, a way to start a session, a way to clean up.

Three phases, because clients differ in when and how they reach a primitive.
**Eager** clients list everything on connect — Claude Code sends
`resources/list` and `prompts/list` before the model does anything. **Lazy**
clients look only when asked — Codex lists resources only when its
`list_mcp_resources` tool runs, so an eager-only probe scores it as having no
resources, which is wrong. And a **user-controlled** primitive is unreachable
from the model at all, so prompts need the host's own command form. Phase A
opens a session with a trivial prompt; phase B sends one fixed prompt naming
each operation; phase C, for hosts that have one, invokes the prompt through its
command syntax (`invoke_prompt` in the client spec). No reply is ever read.

It also checks that calls are **correct**, not merely present. The probe exposes
`probe_types(text, count, flag, items)`, a resource template `probe://item/{name}`
and a prompt taking `topic`; the fixed phase-B prompt asks for exact values, and
the server records each argument with its JSON type. The report's second table
shows whether the target and every argument arrived intact — catching a client
that sends `"42"` for an int, drops an optional, or fails to substitute a
template parameter. All three clients passed argument fidelity where they
attempted the call at all.

What it cannot reach: a purely graphical surface, such as a desktop resource
picker or a slash-command menu that only populates in a TUI. A `no` from the
script means "not reachable from a scripted session"; a GUI client still needs
one manual check before recording it as unsupported. ChatGPT has no CLI at all,
so it is browser-tested and measured with `mcp-probe` against the live server.

Latest run, 2026-08-30:

```
client                       tools    resources  templates   prompts   mcp apps
claude-code      2.1.251       yes          yes         no       yes         no
codex-mcp-client 0.151.0       yes          yes        yes        no         no
copilot-cli      (cli 1.0.82)  yes           no         no        no         no

did it call them correctly?
client              tool arguments   template substitution   prompt arguments
claude-code                     ok                      ok                 ok
codex-mcp-client                ok                      ok      not attempted
copilot-cli                     ok           not attempted      not attempted
```

Read "not attempted" as "the client never made that call", which for prompts is
the same finding as the first table. Where a call happened, every client got it
right: `probe_types text='alpha':str, count=42:int, flag=True:bool,
items=['a','b']:list` arrived intact from all three, and both Claude Code and
Codex substituted the template parameter (`probe://item/beta`). Claude Code also
passed a prompt argument correctly through its slash command
(`prompts/get probe_prompt topic='gamma':str`).

Note Claude Code shows `resource templates = no` while passing the template
substitution check: it never calls `resources/templates/list`, but it does read
a templated URI when told one. Discovery and use are separate capabilities.

### Protocol era per client, 2026-08-30

Measured against a **dual-era** probe, so each client could choose:

| Client | Era chosen | Evidence |
|--------|-----------|----------|
| ChatGPT `openai-mcp(ChatGPT)` 1.0.0 | **modern (2026-07-28)** | `server/discover` with `_meta` envelope |
| Claude Code 2.1.251 | **modern (2026-07-28)** | `server/discover`, no `initialize` |
| GitHub Copilot CLI 1.0.82 | **modern (2026-07-28)** | `server/discover`, no `initialize` |
| Codex 0.151.0 (default) | legacy (2025-06-18) | `initialize` |
| Codex 0.151.0 (`mcp_2026_07_28` on) | **modern (2026-07-28)** | `server/discover` |

A probe measures *configured* behaviour, not *possible* behaviour: Codex ships
the modern lane but keeps it behind an under-development feature flag, so a
"legacy" verdict means "legacy as configured". Check a host's feature flags
before concluding it cannot do better.

**All four hosts can speak 2026-07-28**; three do so by default. They are also
dual-era, so a legacy-only server still works: against the pre-upgrade binnacle
(FastMCP 3.4.7) every one of them fell back to `initialize` without complaint.
binnacle now runs FastMCP 4.0.0b5 and is dual-era — see
`references/protocol-eras.md`.

A modern request also carries **no top-level `clientInfo`**: identity lives at
`_meta["io.modelcontextprotocol/clientInfo"]`. Reading only the top level makes
every modern client look anonymous.

## Method

Three rules make the result deterministic:

1. **Measure at the server, not in the client's words.** A host's answer is
   hearsay; the server log is the record. Run `mcp-probe` (in this skill's
   `scripts/`) to see which methods each client actually called:

   ```bash
   mcp-probe --since "-30 min" --primitives      # defaults to unit binnacle-mcp
   ```

   It reads FastMCP's `LoggingMiddleware(include_payloads=True)` output,
   attributes every method to the `clientInfo.name` of the nearest preceding
   `initialize`, and separates `ui://` reads from data reads.

2. **Always run a local control.** A FastMCP Python client
   (`test_client.py`) hitting the same server proves the server really serves
   the feature. It reports as `mcp` in the probe, the host under test reports as
   its own name (ChatGPT is `openai-mcp`), so the two never blur. If the control
   shows `YES` and the host shows `no`, the gap is the host's.

3. **Use a fresh canary for anything the model could otherwise guess.** Put a
   newly generated hex code inside the resource or prompt under test and ask the
   host for that code. A host that cannot reach the primitive cannot produce the
   code, and — importantly — will usually say so rather than invent it. Generate
   with `python3 -c "import secrets; print(secrets.token_hex(4))"`.

4. **Deny the agent a shell, or verify the clientInfo name.** A coding agent
   with shell access can bypass its own MCP client and hand-write JSON-RPC with
   `curl` — Codex did exactly that and reported every canary despite its client
   never calling `prompts/*`. The probe separates them because the handcrafted
   request carries a different `clientInfo.name`. Tell the agent not to use curl
   or shell commands, and confirm the row you are reading is the real client.

Delete every probe tool, resource, and prompt when finished, and clean up test
chats (`chatgpt-chats --tracked --delete`, or the host's equivalent) and any MCP
server entries added to the hosts under test.

## The battery

### Two surfaces, tested separately

The single biggest mistake this suite can make is to test only what the **model**
can reach. Core MCP hands each primitive to a different actor, so a host that
implements a primitive correctly may still, correctly, keep it away from the
model:

- tools -> the **model** decides; probe by asking the model to do something.
- resources -> the **application** decides; probe both the model path (a
  built-in "read MCP resource" tool, if the host has one) and the user path (an
  attachment picker, an `@` mention, a resource browser).
- prompts -> the **user** decides; probe the user path (a slash command, a
  command palette). Asking the model to "use the prompt" tests nothing, and a
  well-behaved host will correctly answer that it has no such tool.

Claude Code demonstrated this: in `claude -p` the model said it had no tool for
MCP prompts (true), yet the host had already called `prompts/list` on connect
and the slash command `/mcp__<server>__<prompt>` produced a real `prompts/get`.
Judging on the model answer alone would have scored a supporting host as
failing. **Record a primitive as unsupported only after both surfaces fail.**

Likewise, "resources" splits into two unrelated uses that must never share a
verdict: a **data resource** (core MCP — content the client reads) and an
**MCP Apps UI resource** (the extension — a `ui://` HTML component). ChatGPT
does the second and not the first. `mcp-probe` reports the URI scheme for this
reason; treat `resources=UI-ONLY` as a fail on T4 and a pass on T10.

### The battery

| # | Test | Surface | Add to the server | Exercise | Pass = |
|---|------|---------|-------------------|----------|--------|
| T1 | Tool discovery | model | any tool | "what tools do you have" | `tools/list` in probe |
| T2 | Tool call | model | `ping` | "ping the server" | `tools/call` in probe |
| T3 | Semantic discovery | model | a tool whose name is never mentioned | describe the *intent* only | correct `tools/call`, no name given |
| T4a | Data resource, model path | model | resource holding a canary | "read the resource `x://y`" | `resources/read` of a **non-`ui://`** URI; canary returned |
| T4b | Data resource, user path | user | same | attach/mention it through the host's own UI | same, via the user action |
| T5 | Resource template | either | `x://{param}` resource | read `x://foo` | `resources/templates/list` + `resources/read` |
| T6a | Prompt, model path | model | prompt whose text holds a canary | "use the `<name>` prompt" | `prompts/get`. Expected to fail even on supporting hosts — record, do not conclude |
| T6b | Prompt, user path | user | same | invoke the host's command form, e.g. `/mcp__<server>__<prompt>` | `prompts/get` in probe; canary in the reply |
| T7 | Annotations | model | `readOnlyHint` read tool, `destructiveHint` write tool | inspect the tool UI; call each | read runs without a confirm; UI labels differ |
| T8 | Structured output | model | tool returning a dict | call it | host uses the fields, not just prose |
| T9 | Tool errors | model | tool raising `ToolError` | trigger it | host surfaces the message, does not crash |
| T10 | MCP Apps UI resource | host | `ui://` resource + tool with `_meta.ui.resourceUri` | call that tool | component renders; probe shows `resources/read` of a `ui://` URI |
| T11 | UI -> tool bridge | user | component calling `callTool` | click inside the component | that tool appears in probe |
| T12 | UI state | user | component using `setWidgetState` | interact, then let the host re-push | state survives |
| T13 | Tool-list caching | — | add a tool without refreshing | use it in an existing session | visible without a refresh |
| T14 | UI caching | — | edit the component HTML | re-render | the edit appears |

T1–T3 cover tools. T4–T6 establish which primitives exist, each on both
surfaces. T7–T9 cover tool semantics. T10–T12 cover MCP Apps, which is a
separate question from T4. T13–T14 are operational and decide how painful
iteration is.

A capability verdict is not the whole story: "the client called `resources/read`"
does not say whether the content reached the model or stayed in the
conversation. That is measured on the client's own transcript — see
`resource-context-flow.md`.

## Results

### ChatGPT — tested 2026-08-30

Apps SDK connector, developer mode, Pro account. Probe over the whole session:

```
openai-mcp  (ChatGPT)
    -> primitives exercised: tools=YES  resources=UI-ONLY  prompts=no
       resource URI schemes: ui:// x11
mcp  (local control)
    -> primitives exercised: tools=YES  resources=YES  prompts=YES
       resource URI schemes: binnacle:// x3, ui:// x8
```

| # | Result |
|---|--------|
| T1, T2 | **Pass.** |
| T3 | **Pass.** "show me what's inside notes.txt" → `read`; "repeat the phrase…" → `echo`. One-shot, correct arguments, tool names never mentioned. |
| T4 | **Fail.** No `resources/*` from `openai-mcp` at all. Asked to read the resource, it guessed at the `read` tool instead and reported the not-found error. Canary never produced. |
| T5 | **Fail.** Same — templates never listed. |
| T6 | **Fail.** Prompt absent from the connector registry (`"prompt"` appears zero times); no `prompts/*` calls; the host said the surface "did not expose the audit_data_dir MCP prompt". |
| T7 | **Pass.** After adding annotations the connector UI changed each tool's badge to READ; before them every tool showed PUBLIC WRITE / DESTRUCTIVE. (Community reports say `readOnlyHint` is sometimes ignored — recheck.) |
| T8 | **Pass.** `show_files` returns a dict; the host both rendered the panel and tabulated the same data in prose. |
| T9 | **Pass.** `ToolError` text reached the user verbatim, including the "existing files: …" hint, which the model then acted on. |
| T10 | **Pass.** `ui://` component rendered in a bordered iframe beside the conversation. |
| T11 | **Pass.** A click inside the component produced a `read` call in the probe and the content rendered back into the panel. |
| T12 | **Pass**, and necessary: the host re-pushes globals after a UI-initiated call, so a component that does not keep its own view state will wipe what the user opened. |
| T13 | **Fail (by design).** A changed tool surface stays invisible until `chatgpt-refresh`. A brand-new chat re-syncs on its own. |
| T14 | **Fail, badly.** The component is cached per `resourceUri` and neither a refresh nor a new chat clears it. See SKILL.md for the rename-then-restore workaround. |

Conclusion: build the whole model-facing surface out of tools. Use resources
only for MCP Apps UI. See `primitive-support.md` for the T4–T6 evidence in full
and the open questions.

### Claude Code 2.1.251 — tested 2026-08-30

`claude mcp add --transport http … --header "Authorization: Bearer …"`, then
`claude -p` in print mode. Probe: `tools=YES resources=YES prompts=YES`, scheme
`binnacle:// x1`.

| # | Result |
|---|--------|
| T1, T2 | **Pass.** |
| T4a | **Pass.** Read `binnacle://station` through `ReadMcpResourceTool` and quoted the canary. A real data resource, not a UI template. |
| T6a | **Fail, as expected.** The model said it had "no tool for MCP prompts" — the correct answer for a user-controlled primitive, and on its own it proves nothing. |
| T6b | **Pass.** `prompts/list` on connect, and the slash command `/mcp__<server>__<prompt>` produced a real `prompts/get` and executed the template. |

The first client seen to implement all three primitives, and a clean
demonstration of the control model.

Its docs (`code.claude.com/docs/en/mcp`) describe both as **user** surfaces:
resources are referenced with `@server:protocol://resource/path` in the `@`
autocomplete ("Resources appear alongside files in the autocomplete menu"), and
prompts appear in the `/` menu as `/servername:promptname (MCP)`, also callable
as `/mcp__servername__promptname` with space-separated arguments. The docs state
outright that there is no documented way for the *model* to invoke prompts or
reference resources — they are purely user-facing. Neither is documented as
available in `-p` print mode, yet both worked there: the model reached the
resource through a built-in `ReadMcpResourceTool`, and the slash command ran.

### Codex 0.151.0 — tested 2026-08-30

`codex mcp add binnacle --url … --bearer-token-env-var BINNACLE_TOKEN`, then
`codex exec`. Probe, client `codex-mcp-client`:
`tools=YES resources=YES prompts=no`, scheme `binnacle:// x1`.

| # | Result |
|---|--------|
| T1, T2 | **Pass.** |
| T4a | **Pass.** It has a built-in `list_mcp_resources` tool and read the data resource; canary returned. Discovery is **lazy** — nothing on connect, only when that tool runs. |
| T5 | **Pass.** `resources/templates/list` called. |
| T6a | **Fail.** No `prompts/*` from its client. |
| T6b | **Fail.** Asked for `/audit_data_dir` and for its MCP-sourced commands, it answered "MCP-sourced slash commands available: **none**; MCP prompts visible in my command menu: **no**". Both surfaces fail, so prompts are genuinely unsupported. |

Consistent with the docs: `learn.chatgpt.com/docs/extend/mcp` has a "Supported
MCP features" section listing only STDIO servers, streamable HTTP servers, and
server `instructions` — **resources and prompts are not listed**, and the whole
config reference is about `enabled_tools` / `disabled_tools` / per-tool approval.
Resource support is therefore *better* than documented; prompts match the docs.

**Methodology warning, learned here.** Codex reported all three canaries
anyway — it fell back to `curl` against the MCP endpoint and hand-wrote the
JSON-RPC for `prompts/get`. The probe caught it because the handcrafted request
announced itself as `codex` while the real client is `codex-mcp-client`, so the
two appear as separate rows. **An agent with shell access can fake conformance.**
Always read the probe rather than the agent's answer, check the clientInfo name,
and tell the agent not to use curl or shell.

### GitHub Copilot CLI 1.0.82 — tested 2026-08-30

`~/.copilot/mcp-config.json` with an `Authorization` header, then `copilot -p`.
Probe, client `github-copilot-developer`: `tools=YES resources=no prompts=no`.

| # | Result |
|---|--------|
| T1, T2 | **Pass.** |
| T4a | **Fail.** No `resources/*` calls. "I do not have a built-in slash command or documented capability to read MCP resources by URI … To access an MCP resource, I would need to call an MCP *tool*." |
| T4b | **Fail.** No resource picker or `@`-mention path found. |
| T6a | **Fail.** No `prompts/*` calls. |
| T6b | **Fail.** `/mcp` exists but only *configures* servers; no MCP-sourced slash commands. `/audit_data_dir` not available. |

Both surfaces fail for both primitives. **Corroborated by GitHub's own issue
tracker**, where all of this is open work, not a misconfiguration on our side:

- [copilot-cli#1518](https://github.com/github/copilot-cli/issues/1518) "Support
  MCP resources and prompts" (open): "MCP servers provide three distinct
  features: tools, prompts, and resources. Currently, Copilot only supports
  tools."
- [#1803](https://github.com/github/copilot-cli/issues/1803) resources/read, and
  [#505](https://github.com/github/copilot-cli/issues/505) server prompts — both
  open, no assignee or linked PR.

A binary inspection of the cached 1.0.80 package agrees: `listPrompts` appears
zero times, and there is no `session.mcp.prompts.*` wire method at all. There is
an undocumented experimental `mcp-apps` capability (feature flag
`copilot_cli_mcp_apps`) exposing `session.mcp.resources.read` — but only so an
MCP App tool can fetch its `ui://` HTML, not to give the model server data. So
Copilot CLI may eventually match ChatGPT's shape: UI resources, no data
resources.

GitHub Docs never mention resources or prompts for the CLI, and the config
schema has no key for either — there is no hidden flag we missed.

**VS Code Copilot is a different client and does support all three.** Its own
docs list "Tools … Prompts: add reusable prompts as slash commands in chat …
Resources: provide data and content that users can add as chat context", with
`Add Context > MCP Resources` and `/mcp.servername.promptname`. Not tested here;
worth testing, since it would also be a second MCP Apps host.

### Not tested yet

- **Claude Desktop** — expect the same result as Claude Code.
- **VS Code Copilot** — its docs claim all three, and it is an MCP Apps host, so
  it would also test whether a `ui://` component written for ChatGPT is portable.
- **OpenAI Responses API** — a third OpenAI client, distinct from both ChatGPT
  and Codex. It re-lists tools every request, so its client may be more complete.

### Summary so far

| Host | Tools | Resources (data) | Resources (MCP Apps UI) | Prompts |
|------|-------|------------------|-------------------------|---------|
| Claude Code 2.1.251 | yes | yes (`@` mention, and a model-side read tool) | not tested | yes (`/mcp__server__prompt`) |
| Codex 0.151.0 | yes | yes (`list_mcp_resources`) | not tested | no (neither surface) |
| ChatGPT (Apps SDK) | yes | **no** | yes (`ui://` in an iframe) | no (neither surface) |
| GitHub Copilot CLI 1.0.82 | yes | no | not tested (experimental flag only) | no (neither surface) |
| VS Code Copilot (docs only) | yes | yes | unknown | yes (`/mcp.server.prompt`) |
| local FastMCP client (control) | yes | yes | n/a | yes |

The two resource columns are deliberately separate: they are different features
that happen to share a protocol method. ChatGPT is the case that proves they
must not be merged — it scores no on one and yes on the other.

Every host implements tools. Support thins out from there, and the hosts that
skip prompts are the ones whose product has no command surface to put them on —
consistent with the control model rather than with any protocol limit.

### Docs vs reality

Checking each vendor's own documentation after testing, the claims are more
modest than "full MCP support", and the gaps run in both directions:

| Host | Docs claim | Measured |
|------|-----------|----------|
| Claude Code | resources via `@`, prompts via `/mcp__…`; explicitly *user* surfaces, neither documented for print mode | both work, and both also worked in print mode |
| Codex | "Supported MCP features" lists only STDIO, streamable HTTP, and server `instructions` | tools + resources (better than documented), no prompts (matches) |
| ChatGPT | "Plugins primarily use tools"; Apps SDK documents only tools + `ui://` UI resources | tools + UI resources only (matches) |
| Copilot CLI | see that section | tools only |

So no vendor claims all three for the clients tested here. If a host looks like
it should support a primitive, check whether the claim is about *that* client:
VS Code Copilot and Copilot CLI are different clients (VS Code does support all
three; the CLI supports none of the two), as are ChatGPT and Codex.

**Cite the right client matrix — there are two, and one is a decoy.**
`github.com/modelcontextprotocol/docs` is an **archived** repo, last pushed
2025-04-08 and 16 months stale; its `clients.mdx` wrongly shows VS Code Copilot
without prompts, and it omits ChatGPT and Copilot CLI. The real one lived at
`modelcontextprotocol.io/clients` until it was deleted on 2026-05-27 (commit
`2075a21d03`); the last live version is still quotable from the
`modelcontextprotocol/modelcontextprotocol` repo at commit `0dfb7b6` or via the
Wayback Machine, and it lists 114 clients with 43 marked `Prompts`. A third
page, `modelcontextprotocol.io/extensions/client-matrix`, is live but tracks
*extensions* (MCP Apps, OAuth) and **does not cover prompts** at all.

Even the good one was community-maintained ("This list is maintained by the
community"), so it corroborates rather than proves. Vendor docs beat it, and a
probe run beats those.

## Running the battery against a new host

1. Point the host at this same server (its own connector/config path).
2. Re-add the probe fixtures: one canary data resource, one resource template,
   one canary prompt. Keep them in a scratch file so they are easy to delete.
3. Work through T1–T14 in the host's UI, then read `mcp-probe --primitives` for
   the window and fill in a results section above.
4. Remove the fixtures and clean up any test conversations.
