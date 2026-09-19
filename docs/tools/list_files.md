# `list_files` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented in `tools/list_files.py`; unit gate passed (`tests/unit/tools/test_list_files.py`); live browser check at the read-trio checkpoint — see §5 |
| **Parent** | `docs/agent-toolset-design.md` §7.2 |
| **Method** | Survey of Gemini `glob`+`list_directory` (source), Copilot `glob`+`view`-on-dir (fixtures/changelog + local logs), Claude Code `Glob` (docs + self) → decisions → spec |

## 1. Survey highlights (full detail in the research record)

| Aspect | Gemini `glob` / `list_directory` [source] | Copilot `glob` [official+local] | Claude Code `Glob` [official/self] |
| --- | --- | --- | --- |
| Params | `pattern`, `dir_path`, `case_sensitive`, `respect_git_ignore`, `respect_gemini_ignore` / `dir_path`, `ignore[]` | `pattern` (+ `paths` since 1.0.35) | `pattern`, `path` |
| Engine | npm `glob` / `fs.readdir` | bundled ripgrep | `rg --files --glob … --sort=modified` — even Glob is ripgrep |
| Caps | **none** (quirk) | timeout-guarded | **100 files + truncation flag** |
| Sorting | "newest first" header, but only a 24 h recency window, then alphabetical (header overstates — bug) | — | mtime newest-first |
| gitignore | param-controlled | respects | Glob does **not** respect gitignore by default (Grep does) — deliberate asymmetry |
| Dir listing | separate `list_directory`: dirs first, `[DIR]` prefix, sizes, no cap | `view` on a directory works (local logs) | separate tool (`ls` behavior inside Bash) |

Bugs to design against: Gemini's cap-less glob and misleading sort header;
Copilot's bundled jemalloc ripgrep aborting on this Pi's 16 KB kernel pages
(`Unsupported system page size`, observed locally) — use the system
`/usr/bin/rg` (Debian-built, verified working), never a bundled binary.

## 2. Decisions

| Decision | From | Rejected alternative |
| --- | --- | --- |
| One tool, two modes: no `glob` → **non-recursive listing** of `path` (browse); with `glob` → **recursive match** via `rg --files` (find) | Gemini's two tools folded; Copilot `view`-on-dir; design doc §7.2 | Separate `list_directory` tool — schema budget; recursion-without-pattern — explosion risk |
| Engine: system `rg --files` for the ignore-respecting walk, glob filtering in Python (`PurePath.full_match`, no-slash patterns get a `**/` prefix); pure Python for listing mode | Claude Code (Glob is ripgrep); the Copilot page-size crash argues for the system binary; **corrected by the gate** — rg's positive `--glob` "always overrides any other ignore logic", so it silently whitelists gitignored files | `rg --files --glob {pattern}` (the spec's original engine — killed by the gitignore test); bundled binary; npm-glob-style library |
| Cap `max_results` default 200 (≤ 2 000), `truncated` flag + narrow-the-pattern hint | Claude Code's 100-file cap + flag; Gemini's caplessness as the cautionary tale | Uncapped |
| Glob mode sorts newest-first (`--sortr=modified`) | Claude Code; recency-first recurs across agents | Gemini's 24 h-window quirk |
| Listing mode sorts dirs-first, then alphabetical; files carry `bytes` | Gemini `list_directory` | mtime sort for browsing — alphabetical scans better |
| gitignore: glob mode respects it (rg default); listing mode shows everything except hidden | budget (glob into `.venv` is thousands of paths; a listed `.venv/` is one line) | Symmetric semantics — the asymmetry is deliberate, as in Claude Code |
| `include_hidden` default false; when true, `.git` stays excluded | rg defaults; Claude Code VCS exclusions | dotfile noise by default |
| Absolute paths in results | design doc §6.5 (stable identifiers) | Claude Code's relative-paths-for-tokens — our stateless multi-root design outweighs |
| Empty glob result → normal result with note, not an error | Gemini | error noise |
| 20 s subprocess timeout → `ToolError` with "narrow the pattern" | Claude Code ~20 s; Gemini's timeout message pattern | hanging |

## 3. Specification

Annotations: `readOnlyHint: true`, `openWorldHint: false`.

**Description (ship verbatim):**
> List a directory (no glob: one level, dirs first) or find files
> recursively by glob (e.g. **/*.py), newest first, gitignore
> respected. Names only; for contents use search_text or read_file.

(Consolidated 2026-09-07: one "use this when / not" clause kept per
OpenAI's tool-design guidance, design doc §5.2.)

**Input schema** (portable subset):

| Param | Type | Required | Default | Description (ship) |
| --- | --- | --- | --- | --- |
| `path` | string | no | `~/Projects` | "Directory to list or search under. Absolute (~ allowed); relative resolves against ~/Projects." |
| `glob` | string | no | — | "Glob pattern like **/*.py. Present = recursive find; absent = one-level listing." |
| `max_results` | integer 1–2000 | no | 200 | "Cap on returned entries." |
| `include_hidden` | boolean | no | false | "Include dotfiles (.git always excluded)." |

**Result** (`structuredContent`, `outputSchema` declared):
`{path, mode: "list"|"glob", entries: [{path, type: "file"|"dir", bytes?}], count, truncated, note?}` — `bytes` on files only; `truncated: true` when `max_results` was hit. Text summary: `Listed 23 entries in /x.` / `Found 57 files matching **/*.py under /x (newest first).` / truncated variant adds `; narrow the glob or raise max_results`.

**Behavior**: resolve `path` via the shared guard (sanitize NUL/`@`, `~`, relative→default root, roots check). Listing mode: `iterdir`, skip hidden unless `include_hidden`, dirs first then alphabetical, `bytes` from `stat` (stat failures skip the entry). Glob mode: `rg --files --sortr=modified --glob {pattern}` in `path` (+`--hidden --glob !**/.git/**` when `include_hidden`), 20 s timeout, exit code 1 = no matches (empty result + note), exit code 2 or a dead binary = `ToolError` carrying stderr and a `run_command ls/find` fallback hint; take `max_results` lines, absolutize.

**Errors** (all instructions): directory not found → nearby-siblings hint (shared helper); path is a file → "Use read_file to read it."; outside roots → shared guard message; rg failure/timeout → actionable message.

## 4. Test checklist (tests/unit/tools/test_list_files.py)

Listing: dirs-first + alphabetical + sizes; hidden excluded by default,
included with flag (`.git` still absent); cap + `truncated`. Glob:
nested match; gitignore respected (repo fixture with `.git/` +
`.gitignore`); newest-first ordering (`os.utime` fixtures); empty match →
`count 0` + note, no error; absolute paths returned; cap + `truncated`.
Errors: missing dir (nearby hint), path-is-file, outside roots. Live
(deferred to the read-trio browser checkpoint): semantic discovery
("what's in my binnacle project?"), browse→read chain.

## 5. Results — 2026-08-30

| | |
| --- | --- |
| Unit gate | 11 tests, all pass (`tests/unit/tools/test_list_files.py`; suite total 32) |
| Wire | `scripts/mcp_client.py` list + both modes verified against the live server |
| Connector | refreshed; tools now `ping, read_file, list_files` |
| Browser | deferred to the read-trio checkpoint (after `search_text`) |

Spec corrections from implementation:

1. **rg's `--glob` overrides ignore logic.** The spec's engine
   (`rg --files --glob {pattern}`) silently whitelists gitignored files —
   rg documents that a positive glob "always overrides any other ignore
   logic", and the gitignore gate test caught it. Engine changed: rg does
   the ignore-respecting walk only; the glob filter runs in Python via
   `PurePath.full_match` (3.13), with gitignore-style convenience — a
   pattern without `/` gets a `**/` prefix so `*.py` finds nested files.
2. **Python 3.14 compatibility (2026-09-19)**: the fallback glob matcher
   delegates character classes to `fnmatch.translate()`. Python 3.14 changed
   that helper's regex end anchor from `\Z` to `\z`; the old wrapper extractor
   recognized only `\Z`, causing thousands of differential mismatches in bracket
   classes. `_unwrap_fnmatch_translation()` now accepts both stdlib wrappers; a
   34,592-case Python 3.14 probe went from 7,096 mismatches to zero, and tool
   tests cover the `[^]` class through both list_files and search_text.

3. **Dogfood catch**: the first live listing of the repo root exposed
   seven stray files that research subagents had downloaded into the
   working directory — the tool found real mess on its first run
   (cleaned; agents' downloads belong in scratchpads).

Live verification completed 2026-09-19: `glob="[^]"` selected only a file named `^` through both list_files and search_text.
