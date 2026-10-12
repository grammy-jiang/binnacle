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

**Symlinks in listing mode (r5, SD-60; r6, SD-67; r6 W2, SD-74; Linux and macOS follow the same rules)**: both systems walk descriptors: the root being listed (the innermost configured root that holds the listed directory), the listed directory and every directory a link walk passes are opened no-follow, one component at a time, and every metadata or link read is relative to an opened directory, so a component swapped for a symlink after the path check is never followed (a listed directory swapped this way fails with `path_changed`). An in-root symlink is listed, typed by its target, only when its link text stays inside the root being listed at every component and its target resolves inside that root; the entry is built from one no-follow metadata read of that resolved target. When roots nest, a link in the inner root whose text leads into the outer root (also with `..`) is omitted, as on macOS. Absolute link text (r6) is accepted only when, compared as text with no filesystem lookup, it has no `..` component and lies under the canonical path of the root that holds the link (the innermost one when roots nest; for example `.venv -> /home/me/Projects/other/.venv` in the root `~/Projects`), or under a configured alias of that root (r6 W2, SD-74; for example `/tmp` for `/private/tmp` on macOS); the checks above then still apply. An alias is only a root string as configured, normalized as a path (`//` and `/./` and a trailing `/` collapse; after `~` expansion; never inferred, no built-in alias table); an alias with `..` never matches. The first of the canonical path and the aliases that accepts the text is chosen, once, and the link is walked once from the root. An alias is accepted when it resolves to that root when the root is opened, and re-checked on every call by one identity check against the opened root: a retargeted alias stops matching for that call (its text is omitted, canonical text is still listed). Compared as text, an alias is case-sensitive. These links are omitted, with no detail about the target: absolute link text that contains `..` or names a path outside that root (or outside every configured alias of it that still names it), links to another root, out-and-back link text (for example `../outside/../root/f`), links that pass through a symlink whose own text is absolute or leads out of the root being listed, targets outside the root being listed, dangling links, loops and chains longer than 40 hops, and entries whose metadata cannot be read. macOS also omits links to in-root FIFOs and sockets. Omitted entries do not count toward `count` or `truncated`. Glob mode does not use these listing-mode symlink rules; its path checks (rejected absolute or `..` lines, the no-follow per-component walk, `rg --no-config` without `RIPGREP_CONFIG_PATH`) are described below under **Glob mode and swapped paths**. `read_file` is unchanged: it can still open a path through such a link when the path resolves inside the roots.

**Execute-only directories on Darwin (r6 W3 OS1)**: directories that the walk only passes through (the ancestors of the listed directory) are opened with `O_SEARCH|O_DIRECTORY|O_NOFOLLOW`, as on Linux, so search permission alone is enough to pass them. An execute-only root is granted, and files and directories below an execute-only directory are reachable. Listing an execute-only directory (the root or any other) is refused with `permission_denied_tcc_possible`, because only the listed directory is opened for reading.

**Errors** (all instructions): directory not found → nearby-siblings hint (shared helper); path is a file → "Use read_file to read it."; outside roots → shared guard message; a directory the server cannot open → `permission_denied`; a path component that stops being a directory during the listing (on Linux also a listed directory swapped for a symlink) → `path_changed`; a listed directory removed after the path check → `directory_not_found` with the same nearby-siblings hint (r6 W3 SP1, SRC-W2-06); the server out of file descriptors → `too_many_open_files` (`list_files could not open PATH: the server has too many open files. Retry.`, the code search_text uses); any other failure to open or read the listed directory (for example a name that is too long) → `file_io_failed` (`Cannot list PATH: REASON.`), never a raw OS error; rg failure/timeout → actionable message.

**Glob mode and swapped paths (Linux path, r6 W2 X3c, SD-76; X3c-a3, SD-78)**: `rg --files` lists by path string and never lists a symlink. A listed line that is absolute or has a `..` component is rejected (rg below the glob base prints neither). Each listed file is sized by one no-follow metadata read relative to its directory, and that directory is opened from `/` one component at a time, no-follow (O_PATH on Linux). Only the directory chain of the current path is open, so the descriptors held are bounded by the path depth, not by the number of listed directories. An entry whose directory is no longer a directory (swapped for a symlink or a file after rg listed it) or whose final component is now a symlink is omitted, so no outside object is typed or sized. A final component that is now a directory, a FIFO, a socket or a device is omitted too (r6 W3 SP1, SRC-W2-12): an entry typed `file` is a regular file, the rule search_text applies to the files it reports. Omitted entries do not count toward `count`. Any other metadata failure (for example a file removed after rg listed it) keeps the entry without `bytes`, as before; no benign entry is dropped. A descriptor shortage in the server that persists after one retry fails the call with `too_many_open_files` (`list_files could not check the listed files: the server has too many open files. Retry, or narrow the glob.`), the policy search_text follows (r6 W3 SP1, SRC-W2-04): no entry is omitted or kept unchecked because of it. Benign results are unchanged, including a glob under a path reached through a cross-root link. rg runs with `--no-config` and without `RIPGREP_CONFIG_PATH`.

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
