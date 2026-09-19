# Are MCP Apps components portable? Codex, investigated

MCP Apps is an open extension, so a `ui://` component written for ChatGPT ought
to run in other hosts. Codex exposes an `enable_mcp_apps` feature flag, which
looks like the answer. It is not — at least not for the CLI.

## The flag does nothing in Codex CLI

`enable_mcp_apps` appears in only three places in `openai/codex`: the `Feature`
enum, its `FeatureSpec` (`Stage::UnderDevelopment`, `default_enabled: false`),
and a list of features a review sub-agent disables. **There is no
`if features.enabled(Feature::EnableMcpApps)` branch anywhere.** The PR that
added it ([#19884](https://github.com/openai/codex/pull/19884), merged
2026-04-27, first stable in 0.128.0) touched two files and only registered the
key.

It is a registry entry the closed-source Codex Desktop / ChatGPT desktop app
reads over the app-server's `experimentalFeature/list`. Flipping it in the CLI
changes nothing, which matches the reports on
[#21019](https://github.com/openai/codex/issues/21019) — users enabled it and
still got no rendering; the actual fix arrived in a **Desktop** release.

## What Codex CLI does do, ungated

The MCP Apps *parsing* runs regardless of the flag:

- `_meta.ui.resourceUri` is read in three accepted forms — the spec's nested
  `ui.resourceUri`, a flat `"ui/resourceUri"`, and ChatGPT's
  `"openai/outputTemplate"` (`codex-rs/core/src/mcp_tool_call.rs`).
- `_meta.ui.visibility` **filtering is enforced** and also ungated
  (`codex-rs/codex-mcp/src/connection_manager/tool_catalog.rs`).

But nothing renders: `ui://` appears only in test fixtures, the binary contains
no `ui/initialize` or other bridge method names, and there is no server-side
hydration — the resource is never fetched after a tool call. The TUI's MCP
renderer handles text and images only; the resource URI rides along in the event
and is discarded. `/mcp` prints the `ui://` resource as a dim line of text.

## The trap worth knowing

A tool that declares `"ui": {"visibility": ["app"]}` — common in ChatGPT Apps,
meaning "the widget may call this, the model may not see it" — is **hidden from
the model entirely in Codex CLI**. Only tools with no visibility metadata, or
with `"model"` in the array, are exposed.

binnacle is unaffected: `show_files` declares
`{"ui": {"resourceUri": "ui://binnacle/files"}}` with no `visibility` key, and
Codex both lists and calls it (verified 2026-08-30 — `tools/call show_files`
reached the server and Codex reported the file count). The lesson is to leave
`visibility` unset unless a tool genuinely must be UI-only.

Also open and relevant: [#41280](https://github.com/openai/codex/issues/41280) —
a tool result containing a `resource_link` content block fails the whole call
with `Unexpected response type`. Codex has no `resource_link` handling outside
tests. Returning plain content plus `structuredContent`, as binnacle does, stays
clear of it.

## Verdict on portability

| Target | Fetches the `ui://` resource? | Renders it? |
|--------|-------------------------------|-------------|
| ChatGPT | yes | **yes** — verified working |
| Codex **Desktop** / ChatGPT desktop app | yes | yes, since Desktop `26.616.51431`, with known defects (#41280, #33717, #30560) |
| **GitHub Copilot CLI** 1.0.82 | **yes** — observed | unknown; a TUI has nowhere to put an iframe |
| Codex **CLI** (TUI) | no | **no** — no rendering path exists, and none is being built |
| VS Code Copilot | untested | untested; it is listed as an MCP Apps host |

**Treat the Copilot CLI row as provisional — do not build on it.** The
capability behind it is undocumented and experimental (an `@experimental` SDK
surface behind the `copilot_cli_mcp_apps` flag). An unannounced feature can be
withdrawn or changed without notice, so this is a note to revisit, not a
supported behaviour to design against. Re-check when GitHub documents it:
docs.github.com's Copilot CLI MCP page currently says nothing about MCP Apps,
`ui://`, or resources.

Copilot CLI surprised us here. Measured 2026-08-30 against binnacle: it called
`tools/call show_files` and then `resources/read ui://binnacle/files` — the MCP
Apps sequence. That matches the undocumented experimental `mcp-apps` capability
found in its bundle (`session.mcp.resources.read`, feature flag
`copilot_cli_mcp_apps`), whose stated purpose is fetching a tool's `ui://` HTML
rather than giving the model server data. So Copilot CLI has the same shape as
ChatGPT on resources: **no data resources, but it does fetch UI ones**. Whether
it does anything with the HTML in a terminal is a separate question.

So a component is portable to *desktop* hosts, not to terminal ones — which is
unsurprising once stated, since a TUI has nowhere to put a sandboxed iframe.
Design accordingly: **keep the tool useful without its UI**, which the MCP Apps
spec itself requires ("Keep tools useful without UI so the model can complete the
workflow in clients that do not render components"). binnacle's `show_files`
returns the file list as structured data for exactly this reason, and that is why
it works in Codex CLI at all.

None of this is documented: `learn.chatgpt.com`'s config reference lists a
`features.apps` key but not `enable_mcp_apps`, and the Codex MCP page never
mentions MCP Apps, `ui://`, or components.
