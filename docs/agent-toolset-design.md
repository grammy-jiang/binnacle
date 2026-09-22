# Agent toolset for binnacle — research and design

| | |
| --- | --- |
| **Status** | Design proposal, not yet implemented |
| **Date** | 2026-08-30 |
| **Scope** | Which MCP tools binnacle must expose so ChatGPT can work on this Raspberry Pi 5 as a development agent, at parity with local CLI agents (Claude Code, Codex, Copilot CLI) |
| **Decides** | The v1 tool list (§7), the design rules behind it (§6), and what is deliberately left out (§8) |

---

## 1. Goal

ChatGPT (web) connects to binnacle as a custom MCP connector. Today binnacle
exposes five demo tools scoped to a private `data/` directory. The goal is a
tool surface that lets ChatGPT do real development on this Pi: read and edit
code, run builds and tests, manage long-running processes, and inspect the
hardware — the same job Claude Code, Codex, and Copilot CLI do locally.

The design question is not "what can we expose" but "what do working agents
actually need". This document answers it from evidence: a survey of what four
production agents ship as built-in tools, plus the measured constraints of
ChatGPT as an MCP client.

## 2. Method and evidence quality

Every claim below is tagged by its source class:

- **[local]** — measured on this Pi: the installed binaries, Copilot's own
  session logs (`~/.copilot/session-state/*/events.jsonl`, the exact tool
  roster sent to the model), Claude Code's live tool surface (this survey was
  written by Claude Code 2.1.251 itself), and the MCP client-conformance suite
  in `.claude/skills/chatgpt-mcp-dev/references/client-conformance.md`.
- **[source]** — read from the vendor's repository at the exact installed
  version (Codex at tag `rust-v0.151.0`, cross-checked against the installed
  binary; Gemini CLI tool registry at `main`, 0.57.0).
- **[official]** — vendor documentation or a vendor employee's statement.
- **[community]** — third-party reports; used only where nothing better
  exists, and marked as needing local measurement.

Local measurement outranks community reports where they conflict. One conflict
matters and is resolved in §5.

## 3. Survey: built-in tools of four coding agents

### 3.1 Claude Code 2.1.251 [local]

| Tool | Purpose |
| --- | --- |
| `Bash` | Run a shell command. `run_in_background` detaches it; `TaskOutput` / `TaskStop` read and stop it. Output truncated at ~30,000 characters. |
| `Read` | Read a file with line numbers; supports offset/limit ranges, images, PDFs, notebooks. |
| `Write` | Create or overwrite a file. |
| `Edit` | Exact-string replacement (`old_string` → `new_string`, optional `replace_all`). Requires a prior `Read` of the file. |
| `NotebookEdit` | Edit Jupyter cells. |
| `Glob` | File-name pattern search. |
| `Grep` | Content search (ripgrep engine). |
| `WebFetch` / `WebSearch` | Fetch a URL / search the web. |
| `Agent` | Spawn subagents. |
| `TodoWrite` | Maintain a visible task list. |
| `EnterPlanMode` / `ExitPlanMode` | Plan-then-approve mode. |
| `AskUserQuestion` | Ask the user a structured question. |
| `Skill` | Invoke packaged instructions. |
| LSP, MCP client tools | Diagnostics; `ListMcpResources` / `ReadMcpResource`. |

### 3.2 OpenAI Codex CLI 0.151.0 [source, verified against installed binary]

The well-known 2025 list (`shell`, `apply_patch`, `update_plan`, `view_image`,
`web_search`) is obsolete. At 0.151.0:

| Tool | Purpose |
| --- | --- |
| `exec_command` | The shell. Runs a command in a fresh PTY. Key parameters: `cmd`, `workdir`, `tty`, `yield_time_ms` (default 10 000 ms, clamp 250–30 000), `max_output_tokens` (default 10 000), `sandbox_permissions` + `justification` (escalation). If the process outlives `yield_time_ms`, the call returns partial output plus a `session_id`. |
| `write_stdin` | Continue a live `exec_command` session: send input, or poll with empty input. Up to 64 concurrent sessions. |
| `apply_patch` | The single editing primitive. Freeform text constrained by a grammar: `*** Begin Patch` / `*** Add File:` / `*** Update File:` (+ `*** Move to:`) / `*** Delete File:` with `@@` context markers. Not JSON. |
| `update_plan` | Visible step list (`pending` / `in_progress` / `completed`, one `in_progress`). |
| `view_image` | Load a local image into context. |
| `web_search` | Hosted OpenAI tool. Default mode is `cached` (OpenAI-maintained index, no live web); `live` is opt-in. |
| `tool_search` | BM25 search over *deferred* tool metadata. MCP tools and multi-agent tools are hidden behind it by default so the upfront schema stays small. |
| `request_user_input` | Structured questions (collaboration modes only). |
| `spawn_agent` family | Sub-agents; deferred behind `tool_search`. |
| `list_mcp_resources` / `read_mcp_resource` | Only when MCP servers are configured. |

Notable properties:

- **No `read_file`, `list_dir`, or `grep` tools.** Reading and searching go
  through the shell; the system prompt tells the model to use `rg` and
  `rg --files`, and to script bulk edits rather than `apply_patch` them.
- **Truncation is token-budgeted and middle-elided**: default 10 000 tokens
  per call, 1 MiB head+tail buffer per stream, output marked
  `Warning: truncated output (original token count: N)` with
  `…N tokens truncated…` in the middle.
- **Sandbox**: `read-only` / `workspace-write` (default in a git repo; writes
  outside the workspace and network access need approval) /
  `danger-full-access`. Approval policy is orthogonal (`untrusted`,
  `on-request` default, `granular`, `never`).
- **Direction of travel**: the newest catalog models run `code_mode_only` —
  the function-tool surface collapses into one `exec` tool that runs
  JavaScript in a V8 isolate and composes nested tools
  (`await tools.exec_command(...)`).

### 3.3 GitHub Copilot CLI 1.0.82 [local session logs; docs/changelog]

GitHub publishes no complete tool list; this roster is what the CLI actually
sent to the model in 18 sessions on this Pi (all models):

| Tool | Purpose |
| --- | --- |
| `bash` | Run a shell command; supports detached/background mode. |
| `read_bash` / `stop_bash` / `list_bash` | Read output of, stop, and list background shells. (Windows: a parallel `powershell` family.) |
| `view` | Read a file or directory. Output truncated at 20 KB. |
| `create` | Create/write a file. |
| `edit` | Exact-string replacement (`old_str` / `new_str`). |
| `grep` / `glob` | Content search / file-name search, with internal timeouts. |
| `web_fetch` / `web_search` | Gated by `url(...)` permissions. |
| `task` | Spawn subagents (explore, code-review, general-purpose, research). |
| `skill`, `sql`, `session_store_sql`, `read_agent` / `write_agent` / `list_agents`, `fetch_copilot_cli_documentation` | Periphery. |
| Conditional | `ask_user` (interactive only), `store_memory` / `vote_memory`, canvas tools, `manage_schedule`, `tool_search_tool`, IDE diagnostics, a default subset of the built-in GitHub MCP server. |

Notable properties:

- **No plan/todo tool** — plan is a session *mode* (`--plan`), not a tool.
- The pre-GA `str_replace_editor` was split into `view` / `create` / `edit`.
- Approval model: prompt-per-tool with persistable patterns —
  `shell(git:*)` (per first-level subcommand), `write(path?)`,
  `url(domain)`, `<mcp-server>(tool)`; deny always beats allow. Path sandbox
  defaults to cwd + temp dir.

### 3.4 Google Gemini CLI 0.57.0 [source]

Registered by default:

| Tool | Purpose |
| --- | --- |
| `run_shell_command` | `bash -c` with `dir_path`, `description`, and `is_background`; optional PTY; 300 s inactivity timeout; approval narrows by command prefix; chained commands validated per segment. |
| `list_background_processes` / `read_background_output` | Manage `is_background` jobs. |
| `read_file` | Text, images, audio, PDF; paginated. |
| `write_file` | Create/overwrite (approval required). |
| `replace` | Exact-string edit: `old_string` / `new_string` / `allow_multiple` (approval required). |
| `grep_search` | Renamed from `search_file_content`; ripgrep-backed; rich parameters (context lines, per-file and total match caps, `fixed_strings`). |
| `glob` | File-name search, gitignore-aware, newest first. |
| `list_directory` | Plain listing. |
| `web_fetch` / `google_web_search` | Up to 20 URLs per call / grounded search. |
| `write_todos`, `enter_plan_mode` / `exit_plan_mode`, `ask_user`, `activate_skill`, `update_topic`, `invoke_agent`, MCP resource tools | Orchestration and periphery. |

Notable properties: global output truncation at 40 000 characters (default,
configurable); `save_memory` was removed as a tool; `read_many_files` was
deregistered; an opt-in task-tracker suite exists but is off by default.

### 3.5 Capability matrix

| Capability | Claude Code | Codex | Copilot CLI | Gemini CLI |
| --- | --- | --- | --- | --- |
| Shell execution | `Bash` | `exec_command`+`write_stdin` | `bash` | `run_shell_command` |
| Background / long jobs | background + `TaskOutput`/`TaskStop` | session id + poll | `read/stop/list_bash` | `is_background` + list/read |
| Read file | `Read` | — (shell) | `view` | `read_file` |
| Write file | `Write` | `apply_patch` | `create` | `write_file` |
| Surgical edit | `Edit` (str-replace) | `apply_patch` (grammar) | `edit` (str-replace) | `replace` (str-replace) |
| File-name search | `Glob` | — (`rg --files`) | `glob` | `glob` |
| Content search | `Grep` | — (`rg`) | `grep` | `grep_search` |
| Web | fetch + search | hosted search | fetch + search | fetch + search |
| Plan / todo | tool + mode | `update_plan` | mode only | tool + mode |
| Subagents | yes | yes (deferred) | yes | yes |
| Ask user | yes | yes (limited) | yes | yes |
| Output truncation | ~30 k chars | 10 k tokens, middle-elided | 20 KB (`view`) | 40 k chars |

## 4. What the convergence means

1. **There is one core, and every agent ships it**: shell execution, file
   read, file write, surgical edit, file-name search, content search, and
   background-job management. This is the floor for "a normal development
   agent". binnacle v1 implements exactly this core — nothing else.

2. **Codex proves the shell is sufficient — and why binnacle still should not
   copy that.** Codex reads and searches through `rg` in the shell. Three of
   four agents keep dedicated file tools anyway, and for ChatGPT the
   dedicated-tool arguments are decisive:
   - *Permission UX.* ChatGPT skips the confirmation prompt only for tools
     annotated `readOnlyHint: true` (§5). If reading a file means running
     `cat` through a shell tool, every read costs the user a write-approval
     click. Dedicated read-only tools make reads frictionless and keep the
     confirmations for actual writes. This argument alone settles it.
   - *Token efficiency.* `read_file` with a line range beats `cat` of a whole
     file under ChatGPT's response budget.
   - *Structured results.* Exit codes, match lists, and file lists as
     `structuredContent` are machine-usable; conformance test T8 showed
     ChatGPT consumes structured fields well.

3. **The editing primitive is exact-string replacement, 3:1.** Claude Code,
   Copilot, and Gemini all use `old_string` → `new_string`. Three reasons not
   to adopt Codex's `apply_patch`, even though ChatGPT also runs OpenAI
   models (a similarity that was considered and decided 2026-08-30):
   - *The mechanism does not exist over MCP.* Codex registers `apply_patch`
     as a freeform, grammar-constrained custom tool of the Responses API
     (OpenAI's GPT-5 prompting guide ships it the same way). MCP tools take
     JSON-Schema input only, so over a connector the model would have to
     escape an entire patch — newlines, `@@` context markers — inside one
     JSON string. Two flat string fields are strictly easier to emit.
   - *Same-model counter-evidence, measured here* [local]: Copilot CLI
     drives the same OpenAI GPT-5.x model family with str-replace `edit`
     plus dedicated `view` / `grep` / `glob`, across 18 logged sessions on
     this Pi. The model family does not need Codex's tool shapes.
   - *ChatGPT web runs the general chat models*, not the `gpt-5.x-codex`
     fine-tunes whose harness training centers on `apply_patch`.
   Choose str-replace. If editing reliability measures poorly in practice,
   an `apply_patch`-shaped variant is the fallback lever (§9).

4. **Background-job management is standard equipment, not an extra.** All
   four agents have it. ChatGPT's 60-second call timeout (§5) upgrades it
   from standard to mandatory.

5. **Everyone truncates output server-side.** Codex's shape is the one to
   copy: keep head and tail, elide the middle, and say how much was elided.

## 5. ChatGPT as the MCP client: measured constraints

### 5.1 Verified locally on this rig [local]

From `client-conformance.md` (2026-08-30, developer mode, Pro account):

- **Tools are the only model-facing primitive.** Resources reach the model
  never (UI-only for MCP Apps); prompts are unsupported. Build everything as
  tools.
- **Annotations drive the permission UI** (T7): with no annotations every
  tool shows PUBLIC WRITE / DESTRUCTIVE; `readOnlyHint: true` flips the badge
  to READ and removes per-call confirmation.
- **Semantic discovery works** (T3): ChatGPT picked the right tool from
  intent alone, one-shot, on correct descriptions. Descriptions are the API.
- **Structured output is consumed** (T8) — return data, not prose.
- **`ToolError` text reaches the model verbatim and it acts on hints** (T9).
  Error messages are part of the tool contract; write them as instructions
  ("Existing files: …", "still running — poll job_status with this job_id").
- **The tool list is cached** (T13): after any change to names, parameters,
  descriptions, or annotations, run `chatgpt-refresh "Raspberry Pi MCP"`.
- **Protocol**: ChatGPT spoke modern MCP 2026-07-28 (`server/discover`,
  stateless) against dual-era binnacle. Community posts claiming it is stuck
  on 2025-06-18 are outdated — trust the local measurement.

### 5.2 Official [official]

- Developer mode = "full MCP client support for all tools, both read and
  write" (Pro/Plus/Business/Enterprise/Edu, web).
- "We respect the `readOnlyHint` tool annotation. Tools without this hint are
  treated as write actions." Write actions require confirmation; the user can
  expand the JSON input before approving; approval can be remembered **per
  conversation** only.
- **Hard timeout: one minute per tool call** (OpenAI staff, developer forum).
  Not configurable. Progress notifications do not extend it (confirmed for
  the Agent Builder platform; assume the same on web).
- Tool-design guidance: action-oriented names; descriptions with "Use this
  when…" plus disallowed cases; parameter descriptions and enums; return
  stable identifiers for follow-up calls; separate read tools from write
  tools. Server `instructions` should carry cross-tool guidance (sequences,
  relationships); keep the first 512 characters self-contained.
- The `search` / `fetch` special tool contract applies only to deep research
  and company knowledge, not to developer-mode connectors.
- Transport: Streamable HTTP or SSE, remote HTTPS only. Auth: OAuth or
  no-auth — there is **no custom-header field** in the connector UI, which is
  exactly why binnacle's tunnel injects the `Authorization` header.

### 5.3 Community-reported (needs local measurement) [community]

- **Response budget**: results are truncated "at a line boundary to fit the
  tool response budget"; no official number. Returning `structuredContent`
  only — without a duplicate serialized-JSON text block — roughly halves the
  cost and stopped truncation in one documented case.
- **Schema budget**: "All tools (including name, description, and input
  schema) must be less than 5000 tokens" — OpenAI support called it a hard
  limit; ambiguous whether per tool or total. Separately, ~30–40 tools is the
  reported reliability ceiling; ~70+ degrades.
- **Sequential calls only**, each with connection-setup cost; fresh MCP
  session per call. With the modern stateless protocol this is by design.
  Consequence either way: the server must keep zero session state.
- Tool calls consume the plan's message allowance; agent mode reportedly
  cannot use custom connectors (unverified).

### 5.4 Constraint → design rule

| Constraint | Design rule for binnacle |
| --- | --- |
| 60 s hard timeout | Every tool returns in < 50 s by construction. `run_command` returns at `wait_seconds ≤ 50` and **never kills the process when the wait expires**: the call returns partial output plus a `job_id`, and `job_status` continues from there — Codex's `exec_command` → `session_id` contract, adapted to a stateless server. |
| Response budget | Structured-first results: `structuredContent` conforming to a declared `outputSchema`, plus a one-line text summary — never duplicated JSON (§7.12). Server-side head+tail truncation with an explicit elision marker and original size. Conservative caps, tuned after measurement (§10). |
| 5000-token schema, 30–40 tool ceiling | v1 = 8 tools. Terse descriptions. No decorative parameters. |
| Stateless, session-per-call | No server session state. `workdir` is explicit. Job state lives on disk and managed installs use a stable sibling job-owner service, so MCP reload/restart does not own command lifetime. |
| `readOnlyHint` is the confirmation gate | Every read tool carries `readOnlyHint: true`. Never mislabel: a tool that can mutate must not carry it — the annotation is an honor contract, and mislabeling would bypass the user's only approval gate. |
| Sequential + slow round trips | Slightly coarser tools than a local CLI: `search_text` returns context lines in one call; `job_status` returns state *and* log tail; errors carry the data needed for the next call. |
| Errors reach the model (T9) | Every `ToolError` states what went wrong *and* what to call instead. |

## 6. Design principles

1. **Parity with the CLI-agent core** (§4.1), nothing speculative.
2. **Stateless calls.** Absolute paths in, absolute paths out. No implicit
   working directory, no "current file", no session memory.
3. **Reads are free, writes are gated.** Annotations tell the truth.
4. **Bounded everything.** Time (≤ 50 s), output size (head+tail elision),
   result counts (`max_results` with `truncated` flags).
5. **Structured output only**, with stable identifiers (absolute paths, job
   ids, line numbers).
6. **Errors are instructions**, not apologies.
7. **Path allowlist as a guardrail, not a sandbox.** File tools and
   `workdir` resolve inside configured roots (default: `~/Projects`,
   `/tmp`). This
   prevents accidents and prompt-injection drive-bys, not a determined
   command — `run_command` is unrestricted by design inside the user
   account.
   The real security boundary remains: Unix user + bearer token + tunnel +
   ChatGPT's per-write confirmations.
8. **English identifiers and messages**, one term per concept. Names are
   for the model first (Rev. 5 criteria): verb-first action names,
   self-describing without the description, discriminative within the set,
   prior-rich where possible, plain English over unix jargon, snake_case.

## 7. Tool specifications — v1

The full toolset is exactly the convergent core of §4.1, nothing else.
Reads first, then execution, then writes. No liveness tool (`ping` removed:
the connector's own `tools/list` proves the server is up, and
`scripts/mcp_client.py` covers the ops side) and no status tool (`pi_status`
demoted to §9: no CLI agent ships one, and `run_command` + `vcgencmd`
covers the need until real usage argues otherwise). How many of these tools
a given client is served varies per AI agent: per-client visibility
(`client_tools` in the configuration, enforced by middleware) narrows the
surface for clients measured not to use parts of it — usage analysis
(2026-09-02) showed ChatGPT performs edits through `run_command` scripts
and never calls the structured edit tools, so it is served the read/run
subset.

v1 is a synthesis, not an imitation of any one agent: each element comes
from whichever agent solved that problem best, filtered through ChatGPT's
limits (§5). Same-vendor model familiarity is not a design argument (same
model family ≠ same behavior — Rev. 3). The provenance of every choice:

| v1 element | Origin | Why it won |
| --- | --- | --- |
| `run_command` wait-not-kill + poll | Codex unified exec | The only execution shape that fits a hard 60 s client cap without ever losing work. |
| Disk-backed jobs with list / tail / stop | Copilot's `read_bash` / `stop_bash` / `list_bash`; Gemini's background tools | Poll-friendly; stable owner survives MCP reload/restart. |
| `job_status.last_output_age_s` + `quiet` flag | Gemini's shell inactivity timeout, repurposed | Tells ChatGPT when polling is pointless. |
| `read_file` line ranges | Claude Code `Read` | Token-efficient under the response budget. |
| `edit_file` str-replace, uniqueness errors, `replace_all` | Claude Code `Edit` / Copilot `edit` / Gemini `replace` — the 3:1 majority | Portable JSON input; errors double as instructions. |
| `list_files` gitignore awareness | Gemini `glob`; Codex's `rg --files` habit | `.venv` / `__pycache__` noise never spends the budget. |
| `search_text` context lines, `fixed_strings`, caps | Gemini `grep_search` (the richest grep) + Claude Code `Grep` | One call returns enough context — sequential calls are expensive on this client. |
| Head+tail truncation with elision counts | Codex output truncation | The model knows exactly what is missing. |
| Read/write split; annotations as truth | ChatGPT's `readOnlyHint` gate; the spirit of Copilot's `write()` permission class | Zero-friction reads; every real write individually gated. |
| 8 tools, terse schemas | ChatGPT's 5000-token budget; Codex minimalism | Below the reliability ceiling. |
| Errors as instructions | Local T9 measurement; Claude Code's error style | ChatGPT demonstrably acts on hints. |
| Structured-first results (one-line text summary, no JSON duplication) | Community measurement (§5.3) + the spec's back-compat SHOULD (§7.12) | Near-halves response-budget cost while keeping a text block for older clients. |

### 7.1 `read_file`

**Fully specified in `docs/tools/read_file.md`** (survey of 7
implementations, decision records, exact schema/messages, test
checklist). Summary:

> Read a text file, optionally a line range (1-based, inclusive). Returns
> plain content without line numbers, plus total_lines and a
> next_start_line hint when truncated.

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `path` | str | — | Absolute (`~` ok); relative resolves against `~/Projects` |
| `start_line` | int ≥ 1 | 1 | 1-based |
| `end_line` | int ≥ 1 | to caps | Inclusive; past EOF clamps with a note |

Implemented in `server.py` and live-verified against ChatGPT 2026-08-30
(see the spec's Results section). Caps (single-source constants;
provisional until measurement #1): 2 000 lines and 24 000 content chars
per call, 2 000 chars per line (clipped lines flagged), 20 MB stat
guard. Content is **byte-faithful** — original line
endings, no inline line numbers — so it pastes safely into
`edit_file.old_string` (line-addressed navigation comes from
`search_text` and the metadata fields instead). Binary/media → a
structured note, not an error, pointing at `run_command`. Missing file →
error listing nearby files (T9 pattern). Encoding: BOM-aware, lossy
decode flagged. Annotations: `readOnlyHint: true, openWorldHint: false`.

### 7.2 `list_files`

**Fully specified in `docs/tools/list_files.md`; implemented 2026-08-30.**

> List a directory (no glob: one level, dirs first) or find files
> recursively by glob pattern (e.g. **/*.py), newest first, gitignore
> respected.

| Param | Type | Default |
| --- | --- | --- |
| `path` | str | `~/Projects` |
| `glob` | str | none — present = recursive find, absent = one-level listing |
| `max_results` | int 1–2000 | 200 |
| `include_hidden` | bool | false (`.git` always excluded) |

Returns `{path, mode, entries: [{path, type, bytes}], count, truncated,
note?}`. Engine: system `rg --files` walk (gitignore respected — bundled
rg binaries crash on this Pi's 16 KB pages) + Python-side glob filter,
because rg's positive `--glob` overrides ignore logic (gate-caught).
`readOnlyHint: true`.

### 7.3 `search_text`

**Fully specified in `docs/tools/search_text.md`; implemented and
checkpoint-verified 2026-08-30.**

> Search file contents with a regex (ripgrep, smart-case). Matches come
> back as file + line + text; few matches gain automatic context
> (Gemini's SWEBench-measured design: 50 lines for 1 match, 15 for 2–3).

| Param | Type | Default |
| --- | --- | --- |
| `pattern` | str | — |
| `path` | str | `~/Projects` (file or dir) |
| `glob` | str | none (Python-side filter — rg's `--glob` overrides ignore logic) |
| `fixed_strings` | bool | false |
| `context_lines` | int 0–100 | auto |
| `names_only` | bool | false (`{file, count}` entries) |
| `max_results` | int 1–1000 | 100 |

Returns `{path, pattern, entries, count, truncated, note?}`; match `text`
carries no line-number prefix (edit_file copy-safety), context ships
separately with `context_first_line`. Backed by `rg --json --smart-case`.
`readOnlyHint: true`.

§7.4–7.6 are **fully specified together in `docs/tools/run_command.md`**
(they share one disk-backed job model) and **implemented + checkpoint-
verified 2026-08-30**. Summaries below.

### 7.4 `run_command`

> Run a shell command. Waits up to wait_seconds (max 50). A command still
> running when the wait expires is NOT killed: the call returns partial
> output plus a job_id — poll job_status, cancel with stop_job. Set
> background=true to return immediately.

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `command` | str | — | Passed to `bash -c` |
| `workdir` | str | `~/Projects` | Validated against roots |
| `wait_seconds` | int | 30 | Clamped to 1–50 |
| `background` | bool | false | true → return at once with `job_id` |
| `stdin` | str | none | Piped to the process |

Finished within `wait_seconds` → `{exit_code, stdout, stderr, duration_s,
truncated, original_bytes}`. Still running → `{job_id, state: running,
partial_output, runtime_s, log_path}` plus the hint "poll job_status".
Truncation: keep the first 8 000 and last 8 000 characters per stream, elide
the middle as `[... N characters elided ...]` (initial values; tune after
measuring the response budget, §10).
Annotations: `destructiveHint: true, openWorldHint: true` (commands can
reach the network).

The wait-not-kill contract mirrors Codex's `exec_command` (§3.2) on merit
alone: it is the only execution shape that fits a hard 60 s client cap
without ever losing work — a mis-estimated wait degrades into a background
job instead of a killed build. The names are plain English rather than
Codex's (`run` over `exec`, `wait_seconds` over `yield_time_ms`), per the
Rev. 5 naming criteria (§6.8).

Implementation contract (this is what makes wait-not-kill possible on a
server that restarts on every save): **every** command launches detached
(`setsid`, or a `systemd-run --user` transient unit), stdout+stderr
redirected to `~/.local/state/binnacle/jobs/<job_id>/out.log`, with atomic
metadata written at launch and completion. On managed systemd installs the
stable sibling `binnacle-jobs.service` owns the command and its waiter while
FastMCP remains a restartable control plane. `run_command` waits only through
its configured foreground window; a returned `job_id` continues to name the
same disk-backed job across MCP reloads and full MCP service restarts. This is
Codex's `exec_command` → `session_id` design with durable state plus a local
execution owner instead of in-process PTYs;
v1 jobs are therefore non-interactive — no `write_stdin` equivalent until
Phase 2 (§9).

### 7.5 `job_status`

> Check a background job, or return a compact recent-jobs listing when job_id is omitted.

| Param | Type | Default |
| --- | --- | --- |
| `job_id` | str | none → compact recent listing |
| `tail_lines` | int | 100 |

Single job: `{job_id, state: running|exited, exit_code?, runtime_s,
last_output_age_s, quiet, log_tail, log_bytes, log_path}`. A running job
whose `last_output_age_s` is large is flagged `quiet: true`, so the model
can stop polling and investigate differently (borrowed from Gemini's shell
inactivity timeout). Listing (revised 2026-09-19 from live payload measurements): all running
jobs plus the newest 20 non-running jobs, newest-first, with rows
`{job_id,state,exit_code,runtime_s,started_at,workdir,command}`. `command` is
a bounded head+tail preview in the listing; the single-job form keeps the full
command. Liveness from `/proc/<pid>` + `meta.json`. `readOnlyHint: true`. The
read-only analog of Codex's empty `write_stdin` poll.

### 7.6 `stop_job`

> Stop a background job (SIGTERM, then SIGKILL after 5 s).

`job_id` (required). Returns final `{job_id, state, exit_code?}`.
`destructiveHint: true`.

### 7.7 `edit_file`

**Fully specified in `docs/tools/edit_file.md`; implemented and
checkpoint-verified 2026-08-30.**

> Replace an exact string in a text file, byte-for-byte, unique unless
> replace_all. A whitespace-normalized fallback tier matches mis-indented
> old_strings and is reported in the result.

| Param | Type | Default |
| --- | --- | --- |
| `path` | str | — |
| `old_string` | str | — (verbatim; never with line-number prefixes) |
| `new_string` | str | — (empty = delete) |
| `replace_all` | bool | false |

Returns `{path, replacements, match: exact\|whitespace_normalized,
first_change_line, snippet, snippet_first_line, bytes}` — the ±4-line
snippet replaces a verification read (Gemini's measured rationale). BOM
preserved through edits; zero normalization (Copilot's quote/CRLF/BOM bug
class designed out); multi-match errors list the line numbers (OpenHands).
`destructiveHint: true`.

### 7.8 `write_file`

**Fully specified in `docs/tools/write_file.md`; implemented and
checkpoint-verified 2026-08-30.**

> Create a new file or fully overwrite an existing one; parents created;
> content written verbatim UTF-8 (no EOL/BOM transformation — Copilot's
> bug class). Prefer edit_file for changing existing files.

`path`, `content`. Returns `{path, bytes, action: created|overwritten,
previous_bytes?}` — the overwrite case reports loudly instead of being
refused (ChatGPT's write confirmation is the gate). `destructiveHint:
true, idempotentHint: true`.

### 7.9 Server `instructions` (draft)

> binnacle turns this Raspberry Pi 5 into a development workstation for
> ChatGPT. Read code with read_file / list_files / search_text (no
> confirmation needed). Run shell commands with run_command: it waits up
> to wait_seconds (max 50); a command still running is not killed — the
> call returns a job_id; poll job_status, cancel with stop_job, or set
> background=true to return at once. Edit existing files with edit_file
> (exact-string replace; read first); create files with write_file. Paths
> stay inside allowed roots (~/Projects, /tmp). For Pi hardware and health,
> use run_command (vcgencmd, pinctrl, i2cdetect, libcamera-still).

(First 512 characters self-contained, per OpenAI guidance.)

Shipped form after the 2026-09-07 prompt review: a tool map only (~95
tokens). Cross-tool workflow guidance moved to the ChatGPT Project
instructions, because the connector is used from one Project and it is
unverified whether ChatGPT surfaces server `instructions` to the model at
all; tool contracts live in the tool descriptions. Three layers, each
statement with one owner, 1,282 → ~690 tokens.

### 7.10 Disposition of the existing tools

**Done 2026-08-30.** The demo surface (`ping`, `echo`, `read`, `write`,
`show_files`) has been removed entirely; the connector now serves exactly
the v1 tools. `ping` went last, with `run_command` (liveness is
proven by the connector's own `tools/list`; `scripts/mcp_client.py` covers the
ops side). The `data/`-scoped
`read` / `write` must not
coexist with `read_file` / `write_file` even briefly — two "read" tools
blur ChatGPT's description-driven tool selection (T3). The MCP Apps fixture
(`show_files` + `ui://binnacle/files`) goes too; when MCP Apps experiments
resume, recreate a throwaway fixture per the skill's own guidance (mind the
T14 UI-cache workaround).

When this lands: update `instructions`, `scripts/mcp_client.py`, `CLAUDE.md`'s
annotations section, and run the full loop (`scripts/mcp_client.py` →
`chatgpt-refresh` → browser test in the same chat).

### 7.11 Path guard

One `_resolve(path)` helper, same pattern as today's `_data_path`: resolve
symlinks, then require the result inside one of `ALLOWED_ROOTS` (default
`[~/Projects, /tmp]`; the job spool `~/.local/state/binnacle` is readable via
`job_status` only). Reject with a `ToolError` that lists the allowed roots.
`run_command` validates `workdir` the same way. See §6.7 for what this does
and does not defend.

### 7.12 MCP 2026-07-28 conformance

Checked 2026-08-30 against the current revision (2026-07-28 — the draft
changelog is empty, and all 41 SEPs on the index are Final, so nothing newer
is pending). Sources in §11.

**Definitions.** All eight names conform to SEP-986 (1–128 chars, only
`[A-Za-z0-9_.-]`, unique, case-sensitive). `inputSchema` root MUST be an
object; JSON Schema 2020-12 is the 2026 default, but every schema here stays
within the common subset (`object`, `properties`, `required`, `enum`,
bounds, `pattern`) so the same definitions serve legacy-era clients (Codex's
default lane). Every tool declares an `outputSchema`; the spec is normative:
"Servers **MUST** provide structured results that conform to this schema."

**Annotations** — the released set is unchanged (`title`, `readOnlyHint`
default false, `destructiveHint` default true, `idempotentHint` default
false, `openWorldHint` default true), and the spec's trust language backs
§5.4's honor-contract rule: "clients **MUST** consider tool annotations to
be untrusted unless they come from trusted servers." Per tool, stated
explicitly rather than left to defaults:

| Tool | readOnly | destructive | idempotent | openWorld |
| --- | --- | --- | --- | --- |
| `read_file`, `list_files`, `search_text`, `job_status` | true | — | — | false |
| `run_command` | false | true | false | true |
| `stop_job` | false | true | true | false |
| `edit_file` | false | true | false | false |
| `write_file` | false | true | true | false |

**Results.** SDK-level obligations of this revision (required `resultType`,
`ttlMs` + `cacheScope` on `ListToolsResult`, deterministic ordering, a
`tools/list` that never varies per connection) ride on FastMCP 4.0.0b5 —
verify with `mcp-era-check` + `scripts/mcp_client.py` at implementation; binnacle's
list is static, so the stateless-listing MUST is satisfied by construction.
Content policy: `structuredContent` conforming to the declared
`outputSchema`, plus a **one-line** `TextContent` summary ("exit 0 in
2.1 s", "3 matches in 2 files"). The spec says a structured result "SHOULD
also return the serialized JSON in a TextContent block" for backward
compatibility; full duplication is exactly what the ChatGPT response budget
punishes (§5.3), so this is a deliberate, documented soft deviation — a text
block is present, it just summarizes instead of duplicating.

**Errors.** SEP-1303 (since 2025-11-25): input-validation and execution
failures belong in `isError: true` tool results — `ToolError` — not
protocol errors, and "Clients **SHOULD** provide tool execution errors to
language models to enable self-correction." That is the spec-level basis
for §6.6, and ChatGPT measurably complies (T9).

**Long-running work.** The spec-native job mechanism now exists: the tasks
extension (`io.modelcontextprotocol/tasks`, SEP-2663, Final, Extensions
Track) — `tools/call` may return a task handle the client polls with
`tasks/get`. It is capability-gated per request, and **ChatGPT does not
declare it** (still an open feature request on OpenAI's forum as of
2026-07/08). Meanwhile the tools page's non-normative **"Stateful Tools"**
section describes exactly the `run_command` → `job_id` design and blesses
it: "a handle is an ordinary string in a tool result and an ordinary
argument to subsequent tool calls" — with guidance v1 follows (validate the
handle per call, expired handle = execution error, note state retention in
the description). Phase 2 option: because the capability arrives per
request, `run_command` could additionally answer task-declaring clients
with a real `CreateTaskResult` without breaking anyone else.

**Two spec facts that independently reinforce the wait-not-kill design.** SSE
resumability was removed in this revision: a broken response stream loses
the in-flight call and the client "MUST re-issue it as a new request" — so
a long-blocking call is structurally fragile, not just timeout-prone. And
on Streamable HTTP a client disconnect IS cancellation of that request —
but binnacle's jobs are detached, so a dropped or timed-out `run_command`
leaves the job running and discoverable via the `job_status` listing.

**Not used, with the spec reason.** Elicitation/MRTR (`input_required`
results) is gated on the client declaring the `elicitation` capability per
request — and the chat itself is the ask-user channel (§8). Progress
notifications remain legal (request-scoped `progressToken`) but do not
extend ChatGPT's timeout (§5.2), so binnacle does not emit them.
`notifications/tools/list_changed` now flows only over an opt-in
`subscriptions/listen` stream; ChatGPT instead refreshes on demand
(`chatgpt-refresh`, T13).

## 8. Deliberately not built

| Omitted | Why |
| --- | --- |
| `web_fetch` / `web_search` | ChatGPT has browsing built in. A connector copy would waste schema budget and add an unneeded network path on the Pi. One real exception exists — the Pi's own localhost/LAN, which ChatGPT's browsing cannot reach — and it is a §9 candidate, not a v1 tool. |
| Plan / todo tools (`update_plan`, `write_todos`) | CLI agents need a UI channel for progress; ChatGPT renders its own reasoning and plans in the chat. Dead weight. |
| `ask_user` | The whole surface *is* a conversation; ChatGPT asks the user directly. |
| Subagents / `task` | The agent loop lives on ChatGPT's side; binnacle is the hands, not the brain. |
| Skills / prompts | ChatGPT does not implement MCP prompts at all (measured); server `instructions` carries the standing guidance instead. |
| `apply_patch`-style editing | Not portable to MCP: in Codex it is a grammar-constrained freeform tool of the Responses API, while MCP tools take JSON-Schema input only; and Copilot CLI proves the same GPT-5.x model family works well with str-replace (§4.3, full decision record). |
| A generic "read-only shell" tool | It would grant the READ badge to arbitrary commands and hollow out the only approval gate. If read-only shell friction becomes real, promote *curated* commands into dedicated read-only tools instead (§9). |

## 9. Phase 2 candidates (build only on demonstrated need)

- **Curated read-only wrappers** where write-confirmations cause real
  friction: `git_info` (status/diff/log), `service_logs`
  (`journalctl --user`), `list_processes`, and `pi_status` (a structured
  `vcgencmd` / memory / disk / services summary — demoted from v1 on
  2026-08-30: no CLI agent ships such a tool, and `run_command` covers the
  need). Driven by observed usage, not speculation.
- **`take_photo`** (`libcamera-still` → MCP image content block) — first
  verify ChatGPT renders image content from a connector tool.
- **GPIO/I²C helpers** (`gpio_read`, `gpio_write`, `i2c_scan` via `pinctrl`
  / `i2cdetect`) if hardware work becomes frequent; structured pin state
  beats parsing `pinctrl` text.
- **Interactive sessions** (Codex-style `write_stdin` on a PTY) if REPL /
  `raspi-config`-style needs appear. `run_command` already carries Codex's
  wait/poll semantics; Phase 2 would add only the stdin channel (which
  needs job processes that accept input after the server restarts — a pipe
  or PTY held by the detached wrapper, not by uvicorn).
- **Tool deferral** (Codex `tool_search` pattern) only if the schema budget
  becomes a measured problem.
- **`local_http_get`** — read-only GET/HEAD against the Pi's localhost/LAN
  (a dev server under test, a LAN device UI). The one "web" capability that
  is not redundant with ChatGPT's own browsing, and as a read tool it needs
  no confirmation. Until then, `run_command` + `curl` covers it.
- **Batch read (`read_files`)** — one call returning several files, if
  sequential round-trip cost proves painful in practice. Demand is
  unproven: Gemini shipped `read_many_files` and then deregistered it, and
  no other agent has one. Measure before building.

## 10. Open questions — measure on this rig

User-approved first batch (2026-08-30): **#1 response budget**, **#3
`destructiveHint` UX**, **#4 chain length**.

1. **Response budget threshold**: binary-search with a large-output tool
   (bytes and lines); test `structuredContent`-only vs dual content.
2. **Schema budget semantics**: is 5 000 tokens per tool or per connector?
   (Grow a dummy schema until connector creation fails.)
3. **`destructiveHint` UX**: any effect beyond the badge, given the docs
   gate only on `readOnlyHint`? (Compare `write_file` with/without.)
4. **Chain length**: how many sequential tool calls will one turn sustain?
5. **Image content blocks**: does a connector tool result render an image?
   (Gates `take_photo`.)
6. **Timeout margin**: measured wall-clock at which ChatGPT abandons a call
   through this tunnel (validates the 50 s cap).

Method for all six: drive the browser per the `chatgpt-mcp-dev` skill, track
test chats with `chatgpt-chats --track`, read truth from `mcp-probe` /
server logs, keep `scripts/mcp_client.py` as the local control.

## 11. Sources

### Local evidence

- `.claude/skills/chatgpt-mcp-dev/references/client-conformance.md` — T1–T14
  results for ChatGPT/Claude Code/Codex/Copilot, protocol-era table (2026-08-30).
- `~/.copilot/session-state/*/events.jsonl` — Copilot CLI 1.0.82 tool roster.
- Installed binaries: `codex-cli 0.151.0`, `copilot 1.0.82`,
  `claude 2.1.251` (this document's author).

**Codex** (all at tag `rust-v0.151.0` in github.com/openai/codex)

- `codex-rs/core/src/tools/spec_plan.rs` (registry);
  `handlers/shell_spec.rs` (`exec_command`/`write_stdin`);
  `handlers/apply_patch.lark` (patch grammar);
  `codex-rs/features/src/lib.rs` (feature gates);
  `codex-rs/models-manager/models.json` (`code_mode_only` models);
  `codex-rs/core/src/unified_exec/mod.rs` + `utils/output-truncation`
  (sessions, truncation); `codex-rs/protocol/src/protocol.rs`
  (sandbox/approvals); `core/gpt-5.2-codex_prompt.md` (use `rg`, script bulk
  edits).

### Copilot CLI

- docs.github.com Copilot CLI docs (permissions, plugin reference, session
  data); github.com/github/copilot-cli `changelog.md` (1.0.62 20 KB `view`
  cap; GA 2026-02-25); issues #738/#1482 (no official tool list),
  #3254 (`edit` params); github/copilot-sdk#1641 (community roster dump —
  matches local logs).

**Gemini CLI** (github.com/google-gemini/gemini-cli @ 0.57.0)

- `packages/core/src/tools/definitions/base-declarations.ts`,
  `tool-names.ts`, `config/config.ts` (registry; 40 000-char truncation
  default); `docs/tools/*`.

### ChatGPT connector

- developers.openai.com — developer-mode guide (readOnlyHint quote, write
  confirmation, remember-per-conversation, refresh, transport/auth,
  instructions guidance); Apps SDK: plan/tools, optimize-metadata,
  troubleshooting; MCP doc (search/fetch scope).
- community.openai.com — staff statement "the hard limit on any tool call is
  1 minute" (t/1379834); response-budget truncation (t/1383071); 5000-token
  schema limit with support confirmation (t/1371022); session-per-call
  (t/1364975); tool-count degradation (t/1357233).
- modelcontextprotocol.io SEP-2567 (sessionless 2026-07-28 protocol).

### MCP specification (for §7.12)

- modelcontextprotocol.io/specification/2026-07-28 — server/tools (tool
  definitions, annotations + trust language, structuredContent/outputSchema
  normative rules, the "Stateful Tools" section), changelog (resultType,
  ttlMs/cacheScope, x-mcp-header, SEP-2106 schema freedom, SSE resumability
  removal), basic/utilities/progress and /cancellation, client/elicitation
  (MRTR); schema/2026-07-28/schema.ts in the spec repo (field-level ground
  truth); SEP-986 (tool naming), SEP-1303 (validation errors as tool
  results), SEP-2663 + tasks.extensions.modelcontextprotocol.io (tasks
  extension); community.openai.com t/1389851 and t/1391486 (ChatGPT tasks
  support: open feature requests).

---

*Written 2026-08-30 by Claude Code from the research session that produced
memory `chatgpt-connector-design-limits`. Update §7 in place as
implementation lands; keep §10 answers appended to §5.*

*Rev. 2, same day: on the user's direction to align with Codex (same model
vendor), merged `start_job` into `exec_command` and adopted Codex's
yield-never-kill/poll mechanics and vocabulary (`workdir`, `yield_s`) —
v1 is now 10 tools. `apply_patch` and read-via-shell stay rejected, with
the evidence recorded in §4.3.*

*Rev. 3, same day: direction changed again — not "align with Codex" but
"combine the best of all four agents under ChatGPT's limits"; same-vendor
model familiarity is dropped as a design argument (same family ≠ same
behavior). Re-deriving v1 from that lens converged on the same 10 tools —
Rev. 2 was already a synthesis; only the justification was Codex-flavored,
and the yield/poll execution model survives on merit (60 s cap). Net
changes: provenance table added to §7; `job_status` gains
`last_output_age_s` / `quiet` (Gemini-inspired); disposition simplified —
the whole demo surface is replaced (user-confirmed test scaffolding); §9
gains `local_http_get` and batch-read candidates.*

*Rev. 4, same day: on user review, removed `ping` and `pi_status` — no CLI
agent ships such tools, and `exec_command` covers status queries — so v1 is
the pure 8-tool convergent core (`pi_status` demoted to a §9 curated
read-only wrapper candidate). Added §7.12: every tool spec checked against
the released MCP 2026-07-28 revision — names (SEP-986), schemas (2020-12,
portable subset), explicit annotations with spec defaults and trust
language, `outputSchema` + structured-first results with a one-line text
summary (a documented soft deviation from the duplicate-JSON SHOULD),
SEP-1303 error semantics, and the tasks extension (SEP-2663): spec-native
jobs exist but ChatGPT does not declare the capability, while the spec's
own "Stateful Tools" section blesses the `job_id` handle pattern v1 uses;
SSE-resumability removal independently reinforces yield-over-blocking.*

*Rev. 5, same day: naming pass for LLM ergonomics, criteria now in §6.8
(verb-first, self-describing alone, discriminative within the set,
prior-rich, plain English over unix jargon, snake_case). Renames:
`exec_command` → `run_command` (everyday verb over abbreviation),
`search_files` → `search_text` (kills the set's only confusable pair — it
searches contents, not file names, so it no longer collides with
`list_files`), parameter `yield_s` → `wait_seconds` (no Codex-internal
jargon, explicit unit, does not imply kill). Every other name and all
str-replace parameters (`old_string`, `new_string`, `replace_all`) kept
for their training priors.*

*Rev. 6, same day: per-tool deep specifications begin, one file per tool
under `docs/tools/`. `read_file` is first — a 7-implementation survey
(Claude Code, Gemini source, Copilot official fixtures + local logs,
Codex, SWE-agent's ablation paper, Cursor leaks, OpenHands/Anthropic)
distilled into decision records and an exact spec. §7.1 updated to match:
1 000-line default window (SWE-agent: whole-file dumps measurably hurt),
byte-faithful un-numbered content (protects `edit_file` exact matching),
binary as note-not-error (Gemini), clamping and defensive path
sanitization, single-source limit constants (Copilot's 50 KB/20 KB
prompt-drift lesson).*

*Rev. 7, same day: `read_file` implemented and live-verified against
ChatGPT end to end (semantic discovery; a secret at line 2 200 of a
2 500-line file found via self-paginated range reads; error-hint uptake;
test chat tracked and deleted). Demo tools `echo`/`read`/`write`/
`show_files` and the MCP Apps fixture removed; `ping` remains until the
rest of v1 lands. Spec corrections from implementation: a single
2 000-line ceiling replaces the two-tier window (the unit gate showed
the 1 000-line no-range default truncating an 8.6 KB file pointlessly —
the char cap is the budget-bearing bound), and BOM bytes must be
stripped before endian-specific decode. Live behavioral finding: ChatGPT
always sends explicit ranges and paginates from `total_lines`, opening
narrow — the description's "start narrow" line visibly steers it.*

*Rev. 9, same day: **v1 complete.** All eight tools implemented, unit-
gated (89 pytest tests), and ChatGPT-verified end to end; the demo
surface is gone; the connector serves read_file, list_files, search_text,
edit_file, write_file, run_command, job_status, stop_job. Code layout:
`server.py` (assembly) + `tools/<name>.py` + shared `paths.py`,
`textio.py`, `jobs.py`; specs in `docs/tools/<name>.md`; tests in
`tests/unit/tools/test_<name>.py`. Rounds ran read_file → (list_files + search_text)
→ write_file → edit_file → (run_command + job_status + stop_job), each
with a browser checkpoint. Highlight: the shell/jobs checkpoint ran a
72-second task — well past ChatGPT's 60 s cap — as run_command yield →
detached job → three job_status polls across separate MCP sessions,
proving the wait-not-kill architecture. Per-tool spec corrections and
live findings are in each `docs/tools/*.md` Results section. Open item
across write tools: no confirmation dialogs appeared (measurement #3).*

*Rev. 8, same day: code layout split ahead of the remaining tools —
`server.py` is assembly only (auth, middleware, `register_all`, `app`);
each tool lives in `tools/<name>.py` with a `register(mcp)` function,
mirroring its spec at `docs/tools/<name>.md`; shared helpers are
`paths.py` (root guard) and `textio.py` (BOM decode, binary sniff,
sizes). `uvicorn server:app --reload` and the systemd units are
unchanged; watchfiles picks up `tools/` edits. Tool surface identical —
verified by the unit gate and `scripts/mcp_client.py` (fast loop, no refresh).*
