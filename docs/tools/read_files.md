# `read_files` — detailed specification (candidate under evaluation)

| | |
| --- | --- |
| **Status** | Candidate, off by default. Implemented in `tools/read_files.py` on the reading core `read_files_impl`, which reuses read_file's per-file steps. Served only when `read_file.multi_mode = "tool"`. |
| **Date** | 2026-09-27 |
| **Sibling** | The "param" candidate gives `read_file` a `files` argument instead: `docs/tools/read_file.md` §4.8. Both return the same result. |
| **Evaluation** | Owner, 2026-09-27: "we must make sure the model can handle this correctly." Nothing ships until a live evaluation with ChatGPT passes. |

## 1. Why (usage evidence)

2026-09-27, `mcp-usage-review` round on the journal since 2026-09-14
(attributed by the tunnel's turn id): ChatGPT made 2,801 `read_file` calls
right after a read of a different file, 10.6 % of its 26,342 tool calls.
They form 1,058 runs of consecutive reads: median 3 distinct files, p90 6,
max 18. 54 % of adjacent pairs are in the same directory. One model step
costs about 11 s (median gap between calls in a turn), so a batch read can
save model round trips when the model already knows which files it needs.

What it cannot fix: a read that depends on the previous file's content,
and reads the client already issues in parallel.

## 2. Tool definition

- **Name**: `read_files`
- **Annotations**: `readOnlyHint: true`, `openWorldHint: false`
- **Visibility**: in "tool" mode it follows `read_file` into every
  `client_tools` allowlist that serves `read_file`
  (`read_files.effective_client_tools`), so ChatGPT gets it without a
  second setting.
- **Description** (limits interpolated from the settings):

  > Read several known text files in one call: up to 8 entries of path,
  > start_line, end_line (1-based, inclusive), read in order under one
  > 48k-char budget: small files come back whole, larger ones are cut and
  > give next_start_line. Each entry succeeds or fails on its own (kind,
  > error); entries the budget cannot reach come back not_read, and
  > next_call holds the arguments to continue. Content matches read_file:
  > plain text without line numbers; binary files return a note.

- `read_file`'s description gains one sentence in this mode only: "To read
  several known files in one call, use read_files."

## 3. Input schema

| Param | Type | Required | Description (to ship) |
| --- | --- | --- | --- |
| `files` | array, `minItems: 1`, `maxItems: 8` | yes | "1-8 files, read in this order." |
| `files[].path` | string | yes | Same as read_file's `path`. |
| `files[].start_line` | integer, `minimum: 1`, default 1 | no | Same as read_file's `start_line`. |
| `files[].end_line` | integer, `minimum: 1` | no | Same as read_file's `end_line`. |

Entries allow no other keys (`additionalProperties: false`), so a
misspelled key is an error, not a silent default. More than 8 entries is a
schema validation error that names the limit ("at most 8 items").

## 4. Limits

| Setting (`[read_file]`) | Default | Meaning |
| --- | --- | --- |
| `multi_mode` | `off` | `off`, `param` or `tool` |
| `multi_max_files` | 8 (2-20) | entries per call |
| `multi_max_chars` | unset: 2 × `max_chars` = 48,000 (4,000-200,000) | content chars shared by all entries |
| `MULTI_MIN_SHARE_CHARS` (code) | 4,000 | a file that is read gets at least this, or all it needs |

Per file, the single-read limits still apply: `max_lines` 2,000,
`max_chars` 24,000, `max_line_chars` 2,000, `max_file_bytes` 20 MB.

## 5. Result (`structuredContent`)

Top level: `kind: "files"`, `files` (one entry per request, in order),
`files_requested`, `files_read`, `files_failed`, `files_not_read`,
`files_duplicate`, `truncated` (any entry cut or not read), `chars`,
`budget_chars`, `next_call` (only when something is left: `{files: [...]}`,
the exact arguments of the follow-up call) and `note`.

Each entry: `index`, `path`, `kind` (`text`, `binary`, `empty`, `error`,
`not_read`, `duplicate`). A read entry carries read_file's own fields
(`content`, `start_line`, `end_line`, `total_lines`, `bytes`, `truncated`,
`next_start_line`, `lines_clipped`, `lossy`, `note`, `fits_in_one_call`)
plus `budget_cut` when the shared budget, not the single-read window, cut
it. An error entry has `error: {code, message}` with read_file's codes and
messages. A `not_read` entry has `not_read: true` and `request` (its
original arguments). A `duplicate` entry has `duplicate_of`.

The text part is a one-line summary per file ("Read 2 of 3 files (1132
chars): a.py: all 11 lines; b.md: error file_not_found").

## 6. Behavior

1. Every entry goes through read_file's checks in read_file's order (path
   guard, existence, directory, size, range, decoding, empty, start past
   the end). A problem becomes that entry's error; the call still succeeds.
   An unreadable file (permission) is `read_error`.
2. The same file and range twice: the second entry is a `duplicate` and is
   not read again. The same file with another range is read.
3. The budget is shared by water-filling: the smallest needs are met first,
   and the rest is split evenly. "Need" is what a single read_file call
   would return for that entry.
4. If the budget cannot give every file at least 4,000 chars (or its whole
   need), the last entries in request order come back `not_read`.
5. A file cut by the budget has `budget_cut: true` and appears in
   `next_call` with `start_line` = its `next_start_line` and its original
   `end_line`. A file cut by the single-read window is truncated exactly as
   read_file would do it and is not put in `next_call`; the read_file rule
   "do not page through a large file" still applies.
6. The journal's `tool_call` line carries `files_requested`; the
   `tool_result` line carries `kind=files`, `files_requested`, `files_read`,
   `files_failed`, `files_not_read`, `files_duplicate` and `truncated`.
   Paths and content are not copied.

## 7. Test checklist

Unit (`tests/unit/tools/test_read_files.py`): request order and `index`; a
one-entry call equals a single read; per-entry ranges; the summary names
every outcome; water-filling (a small file whole, two large files cut
evenly, `next_call` in order); `next_call` continues exactly, keeping the
requested `end_line`; a single-read window cut is not a budget cut; a small
budget leaves the last files `not_read` and every read file gets at least
the minimum share; per-entry errors (missing, directory, outside the roots,
range invalid, range past the end, too large, unreadable); binary and
empty entries; duplicates; more than the limit and an empty list; the
visibility follow rule; the descriptions state the limits.

Protocol (`tests/contracts/test_read_files_protocol.py`, strict in-memory
client, results validated with `jsonschema` against the advertised output
schema): the schema limits; mixed results; the pointer sentence; ChatGPT is
served `read_files` in "tool" mode only; the journal counts.

Off mode (`tests/contracts/test_tool_surface_off.py`): the instructions and
every tool's name, description, schemas and annotations are byte-identical
to the pre-candidate snapshot (origin/master 3ee3399).

Live (evaluation, not yet run): see §8.

## 8. Open questions for the evaluation

- Are the 2,801 consecutive reads serial model steps, or parallel calls in
  one step? Only serial steps are saved by a batch read.
- Does the model use the batch only for files it already knows, and does it
  follow `next_call` and `not_read` correctly?
- Param or tool: which one does the model discover and use correctly more
  often, and does the extra tool change its other tool choices?
- Does a larger result per call change later behavior (re-reads, context
  pressure)?

## 9. Sources

The usage round of 2026-09-27 (see §1). Gemini CLI PRs #12517 and #12861
deprecated `read_many_files` "in favor of parallel read_file calls"
(`docs/tools/read_file.md` §7): the reason to measure parallelism first.
