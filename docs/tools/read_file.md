# `read_file` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented in `tools/read_file.py` (shared helpers: `paths.py`, `textio.py`); unit gate (pytest, `tests/unit/tools/test_read_file.py`) and ChatGPT live verification passed 2026-08-30 — see §5 Results |
| **Date** | 2026-08-30 |
| **Parent** | `docs/agent-toolset-design.md` §7.1 (overview, annotations, path guard) |
| **Method** | Survey of 7 file-reading implementations → absorb the best parts, record the bugs to avoid → full spec |

## 1. Survey: how 7 implementations read files

Evidence labels: [local] measured on this Pi / self, [source] vendor source
code at the installed/current version, [official] vendor docs, changelog,
or repo test fixtures, [paper] peer-reviewed, [leaked] community-leaked
prompts (unverified).

| Aspect | Claude Code `Read` [local] | Gemini `read_file` [source] | Copilot CLI `view` [official+local] | Codex [source] | SWE-agent viewer [paper] | Cursor `read_file` [leaked] | OpenHands / Anthropic `view` [official+source] |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Range params | `offset`, `limit` (lines) | `start_line`, `end_line` (1-based, `integer`, `minimum: 1`) | `view_range: [start, end]` | none — shell (`sed -n`, `rg`) | 100-line window + `scroll_up/down`, `goto` | gen1: 1-indexed start/end + `should_read_entire_file`; gen2: `offset`/`limit` | `view_range: [start, end]`, `-1` = EOF |
| Default window | 2 000 lines | 2 000 lines | 20 KB output cap | n/a | 100 lines | 250 lines (750 in Max Mode) | 16 000 chars (`MAX_RESPONSE_LEN_CHAR`) |
| Per-line cap | 2 000 chars | 2 000 chars + `... [truncated]` | none (byte-based) | n/a | n/a | n/a | n/a |
| Hard size guard | — | 20 MB stat guard before read | 10 MB; `view_range` bypasses (v0.0.380) | n/a | n/a | n/a | 10 MB |
| Line numbers in output | yes (`cat -n`) | **no** | **no** (raw content; SDK fixture: `line2\nline3\nline4`) | n/a | yes | gen2: `LINE_NUMBER\|LINE_CONTENT` | yes (`cat -n`, 6-wide) |
| Truncation notice | yes | banner + "use start_line: ${end + 1}" | prompt states the 20 KB limit | n/a | header counts omitted lines before/after | summary of omitted lines + re-read checklist | `<response clipped>` + "retry after `grep -n`" |
| Media | images, PDF (`pages`), notebooks | image/audio/PDF as inline base64; SVG as text; other binary → message, **not an error** | images to vision models; **GIF crashed sessions** (#2860, #2468) | n/a | n/a | images (gen2) | Markdown-conversion path for some docs |
| Directory path | error | typed error | **works — used on directories in real sessions here** [local]; web evidence inconclusive | n/a | n/a | separate tool | lists 2 levels deep, hidden excluded, with `ls -la` hint |
| Read-before-edit gate | enforced by harness | none | none (official fixture: blind `old_str` edit succeeds) | n/a | n/a | prompt-level only | none |
| Encoding | — | BOM detect UTF-8/16LE/16BE/32, strip, decode; else UTF-8 | — | n/a | n/a | n/a | — |

## 2. Empirical findings worth absorbing

1. **Bounded windows beat whole files — measured.** SWE-agent's ablation
   (SWE-bench Lite, GPT-4 Turbo): 100-line window 18.0 % resolved, 30-line
   window 14.3 %, **entire file 12.7 % — the worst option**. "Either too
   little content (30 lines) or too much (entire file) lowers performance."
   Every production agent independently converged on a capped window with a
   range escape hatch.
2. **1-based inclusive line ranges are how models think.** Gemini migrated
   0-based `offset`/`limit` → 1-based `start_line`/`end_line` (PR #19526):
   "aligns the API with how Large Language Models naturally reason about
   line ranges". Cursor gen1 named its params `..._one_indexed` outright.
3. **Schema types bite.** Gemini PR #26922: `number` → `integer` +
   `minimum: 1` because the API returned `400 Invalid JSON` on `number`.
4. **Truncation messages must teach the recovery move.** Gemini names the
   exact next call (`start_line: ${end + 1}`); OpenHands says "retry after
   you have searched inside the file with 'grep -n'". Nobody truncates
   silently. This matches binnacle's own T9 measurement: ChatGPT acts on
   instructions embedded in tool output.
5. **Defensive path sanitization is a real need.** Gemini strips NUL bytes
   and a hallucinated leading `@`/`@/` prefix from model-supplied paths —
   artifacts that actually occur in LLM tool calls.
6. **Binary detection by MIME alone misfires.** Gemini special-cases
   `.ts/.mts/.cts` because MIME guesses MPEG transport stream. A known-text
   extension allowlist must run before any MIME/content sniff.
7. **Bugs to design against** (Copilot CLI): the size gate misfired and
   rejected an 8.6 KB file as "too large" (#4633); tool-prompt text claimed
   a 50 KB limit while the real limit was 20 KB (fixed v1.0.62) — keep
   limits in ONE constant that both the code and the description
   interpolate; a 5 MB single-line minified file once produced empty output
   (fixed v1.0.5) — char caps must apply even when no newline is found;
   GIF-to-vision crashed sessions — media needs an explicit gate.
8. **Frugality guidance flipped over 2025→2026.** Cursor gen1: "Reading
   entire files is often wasteful"; Cursor gen2: "speculatively read
   multiple files as a batch"; Copilot v0.0.377 moved to "encourage
   incremental reading … instead of discouraging all reading". For ChatGPT,
   frugality still wins: calls are sequential and slow, and the response
   budget is finite — but the window must not be so small that it forces
   extra round trips (SWE-agent's 30-line result).

## 3. Decisions (what binnacle absorbs, and from whom)

| Decision | From | Rejected alternative and why |
| --- | --- | --- |
| `start_line` / `end_line`, 1-based inclusive, `integer`, `minimum: 1` | Gemini PRs #19526/#26922; Cursor gen1 naming | `offset`/`limit` (0-based) — models mis-reason about it; Gemini abandoned it. |
| Single window: 2 000-line ceiling + 24 000 content chars per call | SWE-agent ablation (bounded windows), Copilot's proven 20 KB, ChatGPT response budget (§5.3 of parent) | The spec's original two-tier window (1 000-line no-range default) — implementation testing killed it: it pointlessly truncated an 8.6 KB / 1 720-line file. The char cap is the budget-bearing bound; the line cap is a secondary guard. Whole-file dumps stay impossible either way. Tune after measurement #1. |
| Per-line clip at 2 000 chars, marked | CC + Gemini (convergent) | Unbounded lines — one minified file eats the budget. |
| Char cap applies even with no newline | Copilot bug v1.0.5 | Line-based-only logic returns nothing for single-line files. |
| 20 MB stat guard, error points at `run_command` | Gemini guard + binnacle T9 error style | Copilot's range-bypass of the guard — its gate misfired (#4633); a line-indexed read of a multi-GB file must scan anyway. Sampling giants is shell work. |
| **No inline line numbers; metadata carries the line info** | Gemini + Copilot precedent | `cat -n` output (CC/OpenHands/SWE-agent) — their edit tools are line-addressed or their models are trained on the format. binnacle's `edit_file` is exact-string: inline numbers are a copy-paste footgun (CC documents it: "strip the line-number prefix before matching") and cost ~7 chars/line of budget. Line-addressed navigation comes from `search_text` results (`{file, line}`) and from `start_line`/`total_lines` fields. |
| **Byte-faithful content**: line endings preserved (`splitlines(keepends=True)`, join `""`), no normalization | binnacle-original (required by exact-string `edit_file`) | Gemini splits `/\r?\n/` and joins `\n` — CRLF files would silently normalize, and every `edit_file.old_string` copied from the read would then miss the on-disk bytes. |
| Truncation result carries `next_start_line` + a text summary naming the exact next call | Gemini banner, OpenHands hint, T9 | Silent truncation. |
| BOM detect (UTF-8/16/32), strip, decode; else UTF-8 `errors="replace"` with `lossy: true` flag | Gemini `readFileWithEncoding` | Bare UTF-8 — Windows-originated files land on the Pi too. |
| Known-text extension allowlist before content sniff (null-byte check) | Gemini's `.ts` MPEG-TS fix | MIME-first detection. |
| Binary/media → structured note, **not** a `ToolError` | Gemini | Error result — it is not a failure; the model should pivot calmly to `run_command` (`file`, `xxd`, `pdftotext`). Images stay out until measurement #5 (ChatGPT image-block support; Copilot's GIF crash is the cautionary tale). |
| Missing file error lists nearby files in the parent dir | binnacle's own `read` (T9-proven: ChatGPT acted on the hint) | Bare "not found". |
| `end_line` past EOF clamps with a note; `start_line` past EOF errors | OpenHands clamp behavior | Gemini errors on both — clamping saves a round trip. |
| Path sanitization: strip NUL and leading `@`/`@/`, expand `~`, relative resolves against the default root, result echoes the resolved absolute path | Gemini defensive parsing; parent doc §6.2 (stable identifiers) | Rejecting relative paths — costs a correction round trip for no safety gain (the roots guard runs either way). |
| Empty file → normal result, `content: ""`, note "File is empty." | Cursor gen2 | Error — an empty file is a fact, not a failure. |
| No server-side read-before-edit gate | Copilot fixture (blind edits succeed); statelessness (§6.2) | CC's harness gate — impossible without sessions; `edit_file`'s description says "read first" and its errors guide recovery. |
| Directory path → typed error naming `list_files` | Gemini error + binnacle tool pointer | Copilot-style directory listing inside the read tool — binnacle already has `list_files`; one job per tool. |

## 4. Specification

### 4.1 Tool definition

- **Name**: `read_file`
- **Annotations**: `readOnlyHint: true`, `openWorldHint: false`
- **Description** (to ship, verbatim; the limit is interpolated from the
  constants in §4.3 — rewritten 2026-09-06, 2026-09-07, consolidated in the
  2026-09-07 review):

  > Read a text file, optionally a line range (1-based, inclusive). One
  > call returns at most 24k chars (about 6k tokens, ~480 lines of prose);
  > a file within that comes back whole, so omit the range. For a larger
  > file do not page through it: search_text to locate, then read only that
  > range. Returns plain content without line numbers, plus total_lines and
  > next_start_line when truncated. Binary or media files return a note;
  > inspect those with run_command (file, xxd, pdftotext).

  The 2026-09-07 review moved "read once, do not re-read slices, verify
  once" to the ChatGPT Project instructions (workflow, single owner) and
  dropped the list_files/edit_file cross-references (edit_file is hidden
  from ChatGPT, the only client). Kept: the limit in chars/tokens and the
  no-paging rule, both measured.

  Why the rewrite: the original said "Reading again with a range is cheap —
  start narrow." Measured 2026-09-04/05 (docs/usage-analysis-2026-09-06.md
  §6): ChatGPT made 492 read_file calls on 21 files, median slice 26 lines,
  one 462-line file read 213 times, with nothing telling it the window was
  2,000 lines. The description now states the window; a partial read of a
  file that would fit whole also gets a one-line note and
  `fits_in_one_call: true` (§4.4). Baseline for the comparison:
  `docs/usage-baselines/2026-09-06.json` (`read_file` block).

### 4.2 Input schema

| Param | Type | Required | Default | Description (to ship) |
| --- | --- | --- | --- | --- |
| `path` | string | yes | — | "Absolute path (`~` allowed). A relative path resolves against ~/Projects." |
| `start_line` | integer, `minimum: 1` | no | 1 | "1-based first line to read." |
| `end_line` | integer, `minimum: 1` | no | to caps | "1-based last line, inclusive. Values past the end of the file are clamped." |

JSON Schema stays in the portable subset (parent §7.12): `object`,
`properties`, `required`, `integer`, `minimum`. No other params — no
`should_read_entire_file`, no `explanation` (decorative; Cursor gen2
dropped them too).

### 4.3 Limits (single source of truth — module constants, interpolated into the description and messages so text can never drift from code, per Copilot's 50 KB/20 KB lesson)

| Constant | Value | Meaning |
| --- | --- | --- |
| `READ_MAX_LINES` | 2 000 | Line ceiling per call, range or not |
| `READ_MAX_CHARS` | 24 000 | Content chars per call, all cases, newline or not |
| `READ_MAX_LINE_CHARS` | 2 000 | Per-line clip, marked `… [line truncated]` |
| `READ_MAX_FILE_BYTES` | 20 MB | Stat guard before reading |

All four are initial values pending response-budget measurement #1
(parent §10); record measured values here when known.

`READ_MAX_CHARS` reviewed 2026-09-07 against every ChatGPT read since
09-01 (750 calls): the 2 000-line cap never binds on prose (24k chars ≈
480 lines), and 24k itself bound only 6 calls. Lowering to 16k would have
cut total context by under 2.5 % while adding 9 paging calls and pushing 8
more files into paging — so 24k stays. What actually shrank context was
removing repeated slice reads (1.57 M chars over 496 calls → 251 k over 65)
and the no-paging rule for large files in the description above.

### 4.4 Result (`structuredContent`; `outputSchema` declared)

| Field | Type | Notes |
| --- | --- | --- |
| `path` | string | Resolved absolute path — the stable identifier for follow-up calls |
| `kind` | `"text" \| "binary" \| "empty"` | |
| `content` | string | Byte-faithful slice (original line endings; absent for `binary`) |
| `start_line`, `end_line` | int | The range actually served (1-based, inclusive) |
| `total_lines` | int | |
| `fits_in_one_call` | bool | Present (true) only on a partial, untruncated read of a file with ≤ 2 000 lines and ≤ 24 000 chars; the `note` and summary then say to omit the range. Added 2026-09-06. |
| `bytes` | int | File size on disk |
| `truncated` | bool | Range served is less than requested/available |
| `next_start_line` | int? | Present iff `truncated` and more lines exist |
| `lines_clipped` | int? | Count of lines cut at `READ_MAX_LINE_CHARS` — those lines are NOT safe as `edit_file.old_string` |
| `lossy` | bool? | Decode used replacement characters |
| `note` | string? | e.g. "File is empty.", clamp notes, binary explanation |

Accompanying one-line text content (the structured-first policy, parent
§7.12): `Read lines 1–1000 of 5230 from /home/…/server.py; continue with
start_line=1001.` / `Read all 247 lines from …` / `Binary file (1.2 MB,
looks like image/png) — content not shown.`

### 4.5 Behavior

1. **Sanitize**: strip NUL bytes and a leading `@`/`@/`; expand `~`;
   resolve relative against the default root; `realpath`; enforce
   `ALLOWED_ROOTS` (parent §7.11). Anything the expansion or resolution
   itself refuses (`~nosuchuser` raises `RuntimeError` in `expanduser`,
   a pathological name can raise `OSError` in `resolve`) is a `ToolError`
   naming the path, never an internal error (property test, 2026-09-13).
2. **Stat**: missing → error E1; directory → E2; > `READ_MAX_FILE_BYTES`
   → E3.
3. **Sniff**: extension in the known-text allowlist → text; else read the
   first 8 KB — NUL byte present → `kind: "binary"` result (message names
   the size and a MIME guess; not an error).
4. **Decode**: BOM check (UTF-8-sig, UTF-16 LE/BE, UTF-32) → strip and
   decode; else UTF-8 with `errors="replace"`, setting `lossy` if any
   replacement occurred.
5. **Slice**: `splitlines(keepends=True)`; apply `start_line`/`end_line`;
   clamp `end_line` to EOF with a note; error E4 if `start_line` >
   `total_lines`; enforce `READ_MAX_LINES`; walk
   lines accumulating chars, stop before exceeding `READ_MAX_CHARS`
   (always serve ≥ 1 line, clipped if needed — the single-line-minified
   case); clip individual lines at `READ_MAX_LINE_CHARS` with the marker
   and count them in `lines_clipped`.
6. **Assemble** result + summary; set `truncated` / `next_start_line`.

### 4.6 Error catalog (`ToolError`; every message is an instruction — T9)

| # | Condition | Message template |
| --- | --- | --- |
| E1 | Not found | `File not found: {path}. Files in {parent}: {up to 10 names}. Use list_files for more.` (listing omitted when the parent is outside roots) |
| E2 | Directory | `Path is a directory, not a file: {path}. Use list_files to browse it.` |
| E3 | Too large | `File is {size_mb} MB; the limit is 20 MB. Use run_command (tail, sed -n, grep) to sample it.` |
| E4 | Range past EOF | `start_line {s} exceeds total_lines {t} of {path}.` |
| E5 | Bad range | `start_line ({s}) is greater than end_line ({e}).` |
| E6 | Outside roots | `Path outside allowed roots ({roots}): {path}.` |

### 4.7 Interplay contracts

- `search_text` results (`{file, line}`) feed `start_line` directly.
- `edit_file`'s description says to read first; `content` is guaranteed
  paste-safe as `old_string` **except** lines counted in `lines_clipped`.
- `list_files` is the answer for E1/E2 recovery.
- `run_command` is the escape hatch for binary, media, and >20 MB files.

## 5. Test checklist (implementation gate)

Unit: empty file; exactly-at-cap file; CRLF file → `content` bytes equal
disk bytes (the edit_file round-trip guarantee); UTF-16-LE BOM file;
UTF-8 with invalid bytes → `lossy`; 5 MB single-line file → clipped
content, not empty (Copilot v1.0.5 case); 8.6 KB file passes untruncated
(Copilot #4633 regression); `.ts` source file reads as text (MIME trap);
PNG and GIF → `kind: "binary"`, no crash; NUL/`@`-prefixed path
sanitized; symlink escaping roots → E6; `end_line` 10× past EOF →
clamped + note; `start_line` past EOF → E4; relative path resolves and
result echoes absolute; partial read of a small file → `fits_in_one_call`
plus note and summary sentence, absent on a whole-file read and on a
range into a file larger than the window; description names the window
and no longer says "start narrow".

Live (ChatGPT, per the `chatgpt-mcp-dev` loop): semantic discovery (T3
style — "show me what's in server.py" with no tool name); truncation
continuation (does it call again with `next_start_line`?); E1 hint
uptake (T9 style).

### Property tests — 2026-09-13

`tests/unit/core/test_properties.py` (hypothesis) guards the invariants behind the
checklist: for any string the guard returns a path under an allowed root
or raises `ToolError` (found and fixed: `~nosuchuser` leaked a
`RuntimeError`); `full_match` agrees with `PurePath.full_match` on 3.13+
(found and fixed: reversed ranges like `[a-.]` raised where the stdlib
matches nothing, `[^a]` treated `^` as negation where fnmatch does not,
and `.`/`a/.`/`./a` were not normalized -- character classes now go
through `fnmatch.translate`; on 2026-09-19 the same differential gate caught
Python 3.14 changing that translation wrapper's end anchor from `\Z` to `\z`,
which is now accepted by the compatibility unwrapping helper; later the same day
a mutmut stats run drew a
fresh example, `/a/a` against `**/a`, where the stdlib matches because its
`**` translation `(?:.+/)?` spans the root of an absolute path -- the
matcher now emits that translation verbatim); `decode_text` never raises and honours every
BOM (a UTF-16-LE BOM followed by U+0000 is byte-identical to the UTF-32-LE
BOM and decodes as such, by design).

### Results — 2026-08-30

Unit gate: **all 24 checks pass** (`test_read_file.py`). Two spec
corrections came out of writing and running them:

1. **The two-tier line window died on contact with the tests.** The
   spec's 1 000-line no-range default truncated the 8.6 KB / 1 720-line
   fixture — a pointless extra round trip for a file that costs ~2 k
   tokens. The char cap is the budget-bearing bound; the line cap is a
   secondary guard. Now a single 2 000-line ceiling (§3/§4.3 updated).
2. **BOM decode bug**: decoding UTF-16 with the endian-specific codec
   keeps the BOM as U+FEFF in the text — the BOM bytes must be stripped
   first (`utf-8-sig` handles its own). The unit test caught it
   immediately.

Live verification (ChatGPT developer mode; one tracked-then-deleted test
chat; server journal as ground truth):

- **Semantic discovery** — "show me what is inside ~/…/scripts/mcp_client.py"
  (no tool name) → one `read_file` call, `~` path accepted, full content
  rendered plus a correct one-sentence summary. No confirmation prompt
  (READ badge honored).
- **Big-file navigation** — asked for a secret hidden at line 2 200 of a
  2 500-line file: ChatGPT read it in four explicit-range calls (1–120,
  121–1000, 1001–1800, 1801–2500, ~5 s apart) and answered correctly.
- **E1 uptake** — a missing file surfaced the error verbatim and the
  model relayed the nearby-files listing as useful information. The T9
  pattern holds for this tool.
- **Behavioral finding: ChatGPT never called without a range.** Every
  live call carried explicit `start_line`/`end_line`; it opened with
  narrow probes (1–400 on a small file, 1–120 on the big one), then
  paginated by its own plan driven by `total_lines` from the first
  result — not by following `next_start_line` literally. Implications:
  `total_lines` is the load-bearing metadata field, the description's
  "start narrow" line visibly steers behavior, and the no-range default
  window barely matters in practice with this client.
- Wire observation: ChatGPT sends `"task": null` inside `tools/call`
  params — consistent with the tasks extension being plumbed client-side
  but undeclared (parent §7.12).

## 6. Open items

- Caps (§4.3) are provisional until response-budget measurement #1.
- Images/PDF inline content gated on measurement #5 (ChatGPT image
  blocks); if it lands, follow Gemini's inline-base64 shape and gate GIFs.
- Revisit line numbers only if live testing shows ChatGPT navigating
  poorly without them; the remedy would be a sidecar field, never inline.

## 7. Sources

Claude Code 2.1.251 [local, self]. Gemini CLI @ main/v0.57.0:
`packages/core/src/tools/read-file.ts`, `utils/fileUtils.ts`
(`processSingleFileContent`), `utils/constants.ts`,
`definitions/model-family-sets/{default-legacy,gemini-3}.ts`; PRs #12517
and #12861 (read_many_files deprecation: "in favor of parallel read_file
calls"), #19526, #26922. Copilot CLI: `github/copilot-sdk` test snapshots
(`should_read_file_with_line_range.yaml` — `view_range: [2, 4]`, raw
un-numbered output; `should_edit_a_file_successfully.yaml` — blind edit),
`copilot-cli` changelog (v0.0.377, v0.0.380 10 MB + range bypass, v1.0.5
single-line fix, v1.0.26/1.0.74 images, v1.0.62 20 KB prompt fix), and
issues #4633, #2860, #2468; local session logs (directory `view` calls).
SWE-agent: arXiv 2405.15793 (Table 3 ablations), swe-agent.com ACI docs.
Cursor: leaked prompts (jujumilk3/leaked-system-prompts,
x1xhlol/system-prompts-and-models-of-ai-tools) [leaked]; forum/community
for 750-line Max Mode. OpenHands/Anthropic:
`All-Hands-AI/openhands-aci` `editor/editor.py`, `config.py`,
`prompts.py`; platform.claude.com text-editor tool docs.
