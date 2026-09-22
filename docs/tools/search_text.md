# `search_text` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented in `tools/search_text.py`; unit gate (16 tests) and the read-trio ChatGPT checkpoint passed 2026-08-30 — see §5 |
| **Parent** | `docs/agent-toolset-design.md` §7.3 |
| **Method** | Survey of Gemini `grep_search` (source, both engines), Copilot `grep` (fixtures/changelog/local), Claude Code `Grep` (docs + self) → decisions → spec |

## 1. Survey highlights

| Aspect | Gemini `grep_search` [source] | Copilot `grep` [official+local] | Claude Code `Grep` [official/self] |
| --- | --- | --- | --- |
| Engine | bundled rg (`--json`), fallback git grep → grep → JS | bundled rg; tgrep for monorepos; **crashes on this Pi (jemalloc/16 K pages)** | rg |
| Params | pattern, dir_path, include/exclude_pattern, names_only, case_sensitive, fixed_strings, context/after/before, no_ignore, max_matches_per_file, total_max_matches | Claude-clone: output_mode (default files_with_matches), -i, -n, multiline, type, paths | pattern, path, glob, type, output_mode, -A/-B/-C, -i, -n, multiline, head_limit, offset |
| Default cap | 100 total matches | "automatic output limiting" | head_limit 250 (content) |
| Case | insensitive by default | -i flag | -i flag |
| Killer feature | **auto-context**: ≤3 matches → auto 50 (1 match) / 15 (2–3) context lines each side — "~10% fewer turns on SWEBench" | — | out-of-range offset returns a corrective message |
| Timeout | 30 s, message: "narrow your search scope by specifying a 'dir_path' or an 'include_pattern'" | timeout-guarded (1.0.13) | ~20 s |
| Line cap | 2 000 graphemes + `... [truncated]` | large-line OOM fixes (1.0.14) | `--max-columns 500` → `[omitted long line]` |
| Regex errors | `Invalid regular expression pattern provided: …` | — | pre-2.1.208 bug: rg errors misreported as "No files found" — now surfaces rg's diagnostic |

## 2. Decisions

| Decision | From | Rejected alternative |
| --- | --- | --- |
| Engine: system `rg --json` stream; **no positive `--glob` flags** — the include filter runs in Python (`full_match`, `**/` convenience), same as `list_files` | Gemini's `--json`; the `--glob`-overrides-ignore trap caught in R1 (Gemini hits the same trap and re-filters matches after the fact) | `--glob {include}` (whitelists gitignored files); text-output parsing (fragile) |
| **smart-case fixed behavior** (`--smart-case`): insensitive unless the pattern has an uppercase letter | rg ergonomics; splits the difference between Gemini's always-insensitive and CC's opt-in `-i`, with zero schema cost | a `case_sensitive` param (decorative under smart-case) |
| **Auto-context**: ≤ 3 matches, no explicit `context_lines`, not `names_only` → re-run with 50 (1 match) / 15 (2–3) lines each side | Gemini (SWEBench-measured, −10 % turns) — and our own §5.4 sequential-call economy | context only on request |
| `names_only` mode returning `{file, count}` entries | Gemini `names_only` + CC `count` mode folded | a 3-value `output_mode` enum (schema cost) |
| Cap `max_results` default 100 (≤ 1 000), `truncated` + note | Gemini's 100; CC's flag-on-truncation | uncapped |
| **64 KiB structured-result budget**, independent of `max_results`; when hit, keep the largest complete prefix of match entries, set `truncated`, and tell the model to narrow or use `names_only` | Live ChatGPT journal, 2026-09-14..19: 682 sized results; 5.7% exceeded 64 KiB but they accounted for 18.6% of all search payload bytes; max 655,605 B / ~162k estimated tokens. Exact-token replay put a 64 KiB result at ~14.6k–16.7k tokens vs ~21.8k–24.6k at 96 KiB. | Lowering `max_results` globally (entry count is a poor size proxy); 48 KiB (cuts cross-file discovery too aggressively); 96 KiB (still permits ~24k-token calls); context de-dup alone (saved 9–50% of context in replay, not enough to bound the result). |
| Match `text` carries **no line-number prefix**; context ships as a separate string with `context_first_line` | read_file's copy-safety rule (search hits seed `edit_file.old_string`) | `cat -n`-style prefixes (the CC footgun) |
| `line_numbers` (opt-in, 2026-09-03) prefixes **context** lines with `N:` and a space, right-aligned; `text` stays prefix-free | grep -n parity for models that reason about locations (ChatGPT has no edit_file, so copy-safety costs it nothing); off by default so local agents keep verbatim context | always-numbered context (breaks copy-safety); a second `context_numbered` field (doubles output) |
| Per-line clip at 2 000 chars, marked | textio convention (read_file) | rg `--max-columns` (drops the line entirely) |
| Surface rg's own diagnostic on a bad pattern | CC's 2.1.208 lesson (bad regex once misreported as "no matches") | swallowing stderr |
| 20 s timeout with Gemini's narrow-the-scope message | Gemini/CC | hanging |
| gitignore always respected; hidden skipped; no `no_ignore`/`multiline` params in v1 | schema budget; `run_command rg -U --no-ignore` is the escape hatch | Gemini's param pair |
| `path` may be a file or a directory | Gemini | dir-only |

## 3. Specification

Annotations: `readOnlyHint: true`, `openWorldHint: false`.

**Description (ship verbatim; rewritten 2026-09-03, consolidated 2026-09-07):**
> Search file contents with a regex, like grep -rn (ripgrep; smart-case).
> Each match is file, line number and text; context_lines adds N lines
> around every match (grep -C) and line_numbers prefixes them (grep -n);
> few matches get context automatically. Prefer this over grep in
> run_command.

Why the rewrite: in ChatGPT's first week `grep` ran 435 times inside
run_command against 34 search_text calls; 243 of those greps searched
files directly, almost always with `-n` and `-A/-B`
(docs/usage-analysis-2026-09-03.md). The tool already had `context_lines`;
the model never learned that it answered the same need. The description
now names the grep flags it replaces, and `line_numbers` supplies the one
thing grep -n had that the context block lacked.

**Input schema:**

| Param | Type | Required | Default | Description (ship) |
| --- | --- | --- | --- | --- |
| `pattern` | string | yes | — | "Regex (Rust syntax). Use fixed_strings for literal text." |
| `path` | string | no | `~/Projects` | "File or directory to search. Absolute (~ ok); relative resolves against ~/Projects." |
| `glob` | string | no | — | "Only search files matching this glob (e.g. *.py)." |
| `fixed_strings` | boolean | no | false | "Treat pattern as literal text." |
| `context_lines` | integer 0–100 | no | auto | "Context lines around each match. Omit for automatic context on few matches." |
| `names_only` | boolean | no | false | "Return only files and their match counts." |
| `max_results` | integer 1–1000 | no | 100 | "Cap on returned matches." |
| `line_numbers` | boolean | no | false | "Prefix each context line with its line number (grep -n style)." |

**Result**: `{path, pattern, entries, count, truncated, note?}` — content
mode entries `{file, line, text, context_first_line?, context?}` (`text` =
the matched line, clip-marked past 2 000 chars; `context` = plain joined
lines, no number prefixes); `names_only` entries `{file, count}`. `count` =
total matching lines observed. `truncated` is true when either `max_results`
or the structured-result byte budget cut the returned entries. The default
`search_text.result_max_bytes` is **65,536 bytes** and is configuration, not
an MCP parameter. Budget enforcement measures compact-JSON UTF-8 bytes, keeps
entry order, and never returns a partial ordinary entry. If the first entry's
context alone cannot fit, its `{file,line,text}` identity is retained without
context and the note points to `read_file`. Summary: `Found 12 matches for
'foo' under /x.` / `…; showing first 100` / `…; showing 47 within the response
budget.` / `No matches for 'foo' under /x.`

**Behavior**: resolve path (shared guard). Run
`rg --json --smart-case [-F] [-C n]` on the path, 20 s timeout; parse the
event stream (`match`/`context`) with `orjson`; apply the Python-side glob filter; stop
at `max_results`. Auto-context: when the first pass yields 1–3 matches with
no explicit `context_lines` and not `names_only`, re-run with `-C 50`
(1 match) or `-C 15` (2–3). After the ordinary result is assembled, measure
its compact-JSON UTF-8 size. If it exceeds `result_max_bytes`, binary-search
the largest complete prefix that fits after the budget note is included. The
full match `count` is retained so the model knows how much is omitted. A
`search_budget_hit` journal event records final bytes, configured bytes,
returned entries and total matches without adding any MCP response fields.
If the required result metadata plus the budget note cannot fit (only plausible
with an extreme input pattern or an unusually tiny configured budget), return a
`ToolError` rather than clip truthful metadata or exceed the cap. This cap bounds
what the model receives; it is not an internal working-set cap for the rg event/
context assembly. Exit 1 = clean no-match; exit 2 or
spawn failure = `ToolError` carrying rg's stderr tail and a `run_command grep`
fallback hint.

**Errors**: empty pattern; invalid regex (rg diagnostic included); missing
path (nearby-siblings hint); outside roots; timeout (narrow-scope
message).

## 4. Test checklist (tests/unit/tools/test_search_text.py)

Match basics (file/line/text, no number prefix); smart-case both ways;
`fixed_strings` with regex metachars; glob filter (nested convenience);
gitignore respected (repo fixture); `max_results` + `truncated`;
`names_only` counts; explicit `context_lines` (content, no prefixes,
`context_first_line` correct); `line_numbers` prefixes context lines
(`1: def alpha():`), leaves `text` bare, is off by default, and applies to
auto-context too; auto-context fires on a single match and
stays off at ≥ 4; long match line clipped; structured-result budget uses
UTF-8 bytes, preserves complete entries and order, retains the true match
count, coexists with `max_results`, leaves small results unchanged, logs the
budget hit, and preserves a match without context when one context block alone
is too large; invalid regex surfaces rg's diagnostic; empty pattern; missing
path; outside roots; file-as-path works. Live: read-trio browser checkpoint
(search → read chain), plus a broad-search budget checkpoint after 2026-09-19.

## 5. Results — 2026-08-30

Unit gate: 16 tests, all pass first run (suite total 48). Wire check
showed auto-context working (a single-match constant search returned 50
surrounding lines unprompted).

Read-trio browser checkpoint (one tracked-then-deleted chat; journal as
ground truth):

1. "Find where SEARCH_MAX_RESULTS_DEFAULT is defined and its value" →
   **one** `search_text` call, exact answer (`tools/search_text.py:23`,
   value 100) with zero follow-up reads — auto-context earned its keep on
   the very first live use.
2. "What test files exist and how many test functions in each?" → a
   `list_files` + `search_text` (+ one `read_file`) chain producing an
   exactly correct table: 21 + 16 + 11 = 48, matching pytest's own count,
   plus an unprompted, correct note that `scripts/mcp_client.py` is not a pytest
   module. Seven tool calls across the two prompts, all with sensible
   arguments.

No spec corrections were needed this round; the R1 lesson (Python-side
glob filtering) was designed in from the start and the gitignore gate
passed first try.

### Result-budget review — 2026-09-19

Live-journal analysis and historical replay added the 64 KiB structured-result
budget described above. The evidence, threshold comparison and replay table are
in `docs/usage-analysis-2026-09-19-search-text-result-budget.md`. The public MCP
input schema is unchanged; the budget is server configuration. Normal small
results are unchanged byte-for-byte, while the largest replayable historical
result fell from 655,605 bytes to 64,837 bytes.

## 6. Development indexed-context mode (2026-09-19)

The development machine may enable explicit indexed discovery without adding an MCP
parameter or a seventh tool:

```text
pattern="@context <natural-language repository question>"
```

Normal patterns retain the exact regex/literal contract above. `fixed_strings=true`
forces literal mode even when the text begins with `@context` followed by a space. During the pilot the
`path` must be the Git worktree root; indexed mode rejects `glob`, `names_only`, and
non-zero `context_lines` rather than silently changing their meaning.

Indexed mode uses a persistent per-worktree SQLite/FTS5 semantic index and typed
relations, then maps a bounded path/symbol/provenance/excerpt package into the
existing result schema. The package is an orientation aid, not proof: use ordinary
regex/read_file to verify ambiguity, especially known-symbol or same-name questions.

The public description continues to name the existing grep equivalents (`grep -rn`,
`grep -c`, `grep -n`) so indexed discovery does not hide the deterministic search
capabilities from the model.

Repository default is disabled. Configuration, telemetry, review criteria, and
rollback are in `docs/indexed-context-pilot.md`.

## 7. Adaptive broad-result representation (development pilot)

The public input/output schema is unchanged. Repository defaults keep this path
disabled. When `search_text.adaptive_discovery_enabled=true`, an ordinary content
search whose fully assembled structured payload would otherwise exceed
`search_text.result_max_bytes` is represented as ranked file discovery instead of
immediately taking the old match-prefix budget path.

Adaptive `entries` reuse only shapes already allowed by `OUTPUT_SCHEMA`:

- detailed representatives: `{file,line,text,count}`, where `count` is that file's
  total match count;
- ranked tail summaries: `{file,count}`.

The default pilot policy returns representative matches for up to 30 ranked files,
two representatives per file, clips representative `text` to 180 characters, and
keeps compact file/count summaries for up to 200 ranked candidate files.
`max_results` continues to cap detailed match entries; tail summaries are not match
entries. `count` remains the total matching-line count and `truncated=true` records
that matching detail was summarized.

The existing 65,536-byte structured-result budget remains authoritative. If the
adaptive result itself would exceed it, only a ranked entry prefix is kept with an
adaptive-specific truthful note. `search_adaptive_discovery` telemetry records the
pre-adaptive byte size, total matches/files, detailed/candidate files,
representative/tail entry counts, final bytes and whether this final hard-budget
trim occurred.

Small results, `names_only`, explicit `@context`, and ordinary results already under
the byte budget retain their previous behavior. See
`docs/search-text-adaptive-discovery.md` for the pilot contract and rollback.

## 8. Exact-search Phase B telemetry — 2026-09-22

Ordinary exact search now emits one terminal `search_exact` journal summary in addition to
`search_dispatch` and the existing budget/adaptive records. This is internal telemetry and
does not change the MCP input/output schema. It records coarse phase timings plus raw-work
counters so a slow call can be attributed to rg execution, JSON parsing, collect/glob
filtering, context shaping, adaptive construction or budget fitting. It also records the
final strategy and machine-readable budget outcome.

Phase B changed the rg JSON parser from stdlib `json.loads` to `orjson.loads`. Controlled
A/B on the same broad query preserved the final structured payload hash exactly while two
baseline runs took 22.42/22.61 s and two Phase-B runs took 19.91/19.78 s (about 12% lower
wall time). Fast-path instrumentation also passed the performance gate: median p50 changed
from 17.216 to 16.696 ms for a literal no-context workload and 42.762 to 39.536 ms for a
regex+context workload; the only median p95 increase was 19.157 to 19.640 ms (~2.5%).

The original Phase-B materialized backend remains available as
`search_text.exact_execution="materialized"` for rollback and A/B work. The repository
default is now `streaming`: rg stdout stays as bytes, JSONL is parsed incrementally with
`orjson`, glob acceptance is cached once per file, and only already-accepted match events
are retained for the existing adaptive ranker. The MCP schema, rg query semantics, context
policy, adaptive ranking, budgets, and result wording remain unchanged.

Streaming telemetry uses `pipeline=streaming`, `rg_stdout_bytes`, `rg_wall_ms`,
`stream_cpu_ms`, and glob-cache/rejected-event counters; materialized historical records
keep their earlier `rg_stdout_chars`, parse, and collect timings. `binnacle stats` renders
both generations separately when a window spans the migration.

Controlled A/B on this Raspberry Pi 5 showed no fast-path regression. Two medium historical
runs were ~3.6–4.3x faster with ~59% lower peak RSS; two broad historical runs were
~14–17x faster with peak RSS falling from ~1.10 GiB to ~91 MiB. Those ratios are evidence
for this host/workload, not a universal performance promise. Complete structured payload
SHA-256 values matched between backends for the controlled medium and broad cases.
