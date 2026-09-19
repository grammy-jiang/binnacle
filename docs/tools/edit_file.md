# `edit_file` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented in `tools/edit_file.py`; unit gate (16 tests) and the write-pair ChatGPT checkpoint passed 2026-08-30 — see §5 |
| **Parent** | `docs/agent-toolset-design.md` §7.7 |
| **Method** | Survey of Gemini `replace` (source, incl. its 4-tier matcher + LLM fixer), OpenHands/Anthropic `str_replace` (source/docs), Copilot `edit` (fixtures/changelog/bugs), Claude Code `Edit` (self) → decisions → spec |

## 1. Survey highlights

| Aspect | Gemini `replace` [source] | OpenHands `str_replace` [source] | Anthropic docs [official] | Copilot `edit` [official+community] | Claude Code `Edit` [self] |
| --- | --- | --- | --- | --- | --- |
| Params | file_path, **instruction** (powers an LLM repair call), old_string, new_string, allow_multiple | path, old_str, new_str (optional = delete) | old_str, new_str | path, old_str, new_str (optional = delete) | file_path, old_string, new_string, replace_all |
| Occurrence rule | exactly one unless allow_multiple | exactly one; multi-match error lists **line numbers** | "match exactly one location" | "must match exactly one occurrence" | unique unless replace_all |
| Match relaxation | 4 tiers: exact → line-trimmed flexible (re-indents) → tokenized regex → Levenshtein fuzzy; then an **LLM edit-fixer** (2nd model call, 40 s, SHA-cached) | exact → one `strip()` retry | — | changelog: "recovering from fuzzy or misaligned edit blocks" | exact only (harness enforces read-first) |
| Create via empty old | yes (only if file absent) | separate `create`, refuses existing | separate `create` | separate `create` | no |
| Post-edit feedback | 5-line diff-context snippet — "avoid the need to spend a turn doing a verification read" | 4-line `cat -n` window + "Review the changes…" | — | "File {path} updated with changes." | terse confirm |
| Real-world failure class | — | — | — | open bugs: CJK curly quotes normalized → "No match found" (#3254); BOM added (#3389); CRLF conversion (#1148); encoding corruption (#308) | line-number-prefix copying (documented footgun) |

## 2. Decisions

| Decision | From | Rejected alternative |
| --- | --- | --- |
| Params exactly `path`, `old_string`, `new_string`, `replace_all` — `new_string` required but may be `""` (delete) | CC/Gemini priors (Rev. 5); Copilot's optional-new_str folded as empty-string | Gemini's `instruction` — it exists to power a second-model repair we don't have; a separate delete mode |
| Two-tier matching: **exact**, then one **whitespace-normalized** tier (line-wise `strip()` compare, unique-match only, replacement re-indented by the matched block's leading indentation delta); the result reports `match: exact\|whitespace_normalized` | every survey subject quietly forgives whitespace (Gemini tier 2, OpenHands strip-retry, Copilot changelog); transparency via the `match` field is our addition | exact-only (CC — but CC's harness enforces read-first, ChatGPT's doesn't); Levenshtein fuzzy and LLM repair (wrong-target risk, no local second model, latency) |
| Multi-match error lists the **line numbers** of every occurrence | OpenHands (genuinely actionable) | bare count (our Rev. 1 draft) |
| No create-via-empty-old_string | one job per tool; `write_file` exists | Gemini's convention |
| **Zero text normalization**; BOM preserved through the edit (strip for matching, re-attach on write); lossy-decode files refused | read_file byte-fidelity contract; Copilot's quote-normalization (#3254), BOM (#3389), CRLF (#1148) bugs — all four community bugs are normalization bugs | any smart-quote/EOL normalization |
| Post-edit snippet: new content ± 4 lines around the first change, prefix-free, with `snippet_first_line` | Gemini's rationale + OpenHands' window; prefix-free per the copy-safety rule | no feedback (forces a verification read — measured waste) |
| 0-match error tells the model to re-read and warns about whitespace and line-number prefixes | Gemini's re-read wording + CC's documented footgun | bare "not found" |

## 3. Specification

Annotations: `destructiveHint: true`, `idempotentHint: false`, `openWorldHint: false`.

**Description (ship verbatim):**
> Replace an exact string in a text file. old_string must match the file
> byte-for-byte (copy it from read_file content; never include
> line-number prefixes) and must be unique unless replace_all=true. A
> whitespace-normalized fallback match is attempted and reported. Returns
> a snippet of the changed region. Use write_file to create files.

**Input**: `path` (required); `old_string` (required — "Exact text to replace, copied verbatim from the file."); `new_string` (required, may be empty = delete — "Replacement text; empty string deletes old_string."); `replace_all` (bool, default false — "Replace every occurrence instead of requiring uniqueness.").

**Result**: `{path, replacements, match: "exact"|"whitespace_normalized",
first_change_line, snippet, snippet_first_line, bytes}` — snippet is the
new content ± 4 lines around the first change, no line-number prefixes.
Summary: `Replaced 1 occurrence in /x (exact match, line 42).` /
`Replaced 3 occurrences in /x.` / whitespace tier adds
`(whitespace-normalized match)`.

**Behavior**: shared guard → must exist and be a file (missing → nearby
hint + "use write_file to create") → read bytes, split off any BOM,
decode (BOM codec or UTF-8); lossy → error ("undecodable bytes; edit
with run_command sed") → binary → error. `old_string == new_string` →
error. Tier 1: literal `str.count`/`replace`. Tier 2 (only when tier 1
finds 0): line-wise trimmed window compare; requires a unique match
(unless replace_all); re-indents `new_string` by the indentation delta of
the matched block's first line. Occurrence rules per tier: exactly one
unless `replace_all`. Re-encode with the original codec, re-attach the
original BOM bytes, write.

**Errors**: 0 matches (re-read + whitespace + prefix warning); N matches
with line numbers; identical old/new; missing file; directory; binary;
lossy; outside roots.

## 4. Test checklist (tests/unit/tools/test_edit_file.py)

Exact single replace (payload + file content + snippet window); delete
via empty new_string; replace_all count; read→edit round-trip on a CRLF
file using a slice of read_file's own `content` (the cross-tool
byte-fidelity guarantee); UTF-8-BOM file keeps its BOM after edit; curly
quotes match exactly (anti-normalization — Copilot #3254 inverse);
whitespace-normalized tier: mis-indented old_string edits the unique
block, replacement re-indented, `match` field reports the tier;
ambiguous whitespace-tier match errors; 0-match error mentions read_file
and line-number prefixes; multi-match error lists line numbers;
identical strings error; missing file (write_file pointer); directory;
binary refused; lossy refused; outside roots.

## 5. Results — 2026-08-30

Unit gate: 16 tests, all pass first run (suite total 72) — including the
cross-tool byte-fidelity round-trip (a slice of `read_file`'s content
used verbatim as `old_string` on a CRLF file), BOM preservation, curly
quotes, and both whitespace-tier behaviors.

Write-pair browser checkpoint (one tracked-then-deleted chat; disk +
journal as ground truth): "create a haiku file, then edit its last line"
executed as the minimal chain `write_file → edit_file → read_file`, and
the file on disk matched ChatGPT's displayed content exactly, compass
line and all.

Observations:

- **No write-confirmation dialogs appeared** for `write_file` or
  `edit_file` in this session, although the documented developer-mode
  default gates every non-readOnly call. Most likely this connector's
  tools were set to always-allow earlier, but it contradicts the
  per-conversation "remember approval" doc — folded into open
  measurement #3 (approval UX) in the parent doc.
- ChatGPT performed its own verification read after editing without
  being asked — consistent with the read-before/after-edit habits its
  models are trained on.
