# `write_file` — detailed specification

| | |
| --- | --- |
| **Status** | Implemented in `tools/write_file.py`; unit gate (8 tests) passed 2026-08-30; live check at the write-pair checkpoint |
| **Parent** | `docs/agent-toolset-design.md` §7.8 |
| **Method** | Survey of Gemini `write_file` (source), OpenHands/Anthropic `create` (source/docs), Copilot `create` (fixtures) → decisions → spec |

## 1. Survey highlights

| Aspect | Gemini `write_file` [source] | OpenHands `create` [source] | Anthropic `create` [official] | Copilot `create` [fixtures/leak] |
| --- | --- | --- | --- | --- |
| Overwrite | unconditional (schema says so: "Overwrites existing files") | **refuses** existing files ("Cannot overwrite files using command `create`") | implementer's choice | leaked prompt: "Use view/edit for existing files (not create - avoid data loss)" |
| Parents | created recursively | **not** created (raw OSError) | — | — |
| Content guard | rejects omission placeholders ("rest of methods ...") in schema text AND code | — | — | — |
| Line endings | preserves CRLF for existing CRLF files, `os.EOL` for new | — | — | open bug #1148: converts files to CRLF; #3389: adds BOM on Windows |
| Feedback | "Successfully created and wrote to new file: …" / "Successfully overwrote file: …" + 5-line diff-context snippet | "File created successfully at: {path}" | — | "Created file {path} with 15 characters" |
| Extra machinery | LLM-assisted escaping corrector for older models | 10-deep undo history | — | — |

## 2. Decisions

| Decision | From | Rejected alternative |
| --- | --- | --- |
| Create **or** overwrite, with the result loudly reporting which (`action`, `previous_bytes`) | Gemini semantics + ChatGPT's per-write confirmation dialog as the real gate; design doc §7.8 | OpenHands' refuse-existing — worth it for autonomous CLIs, redundant under ChatGPT's confirm UX; a separate create tool — schema budget |
| Parent directories created | Gemini; design doc | OpenHands' raw error — one avoidable round trip |
| **Content written verbatim, UTF-8, zero newline/BOM transformation** | read_file's byte-faithful principle; Copilot's CRLF (#1148) and BOM (#3389) bugs as cautionary tales | Gemini's EOL adaptation — clever for whole-file rewrites, but "the file contains exactly what you sent" is the simpler contract for a model that just composed the content |
| No-placeholder rule lives in the **description**, not a hard reject | Gemini's guard, adapted | Gemini's hard reject — false-positives on legitimate `...` in prose/docs (this repo's own docs would trip it); ChatGPT shows the full content in the confirm dialog anyway |
| No post-write content snippet | budget; the model authored the content one message ago | Gemini's diff-context snippet — earns its keep for `replace`, not here |
| Errors carry `strerror` + next step | Gemini's specific EACCES/ENOSPC/EISDIR messages, folded | generic "write failed" |
| Annotations `destructiveHint: true, idempotentHint: true` | design doc §7.12 (same content → same state) | — |

## 3. Specification

**Description (ship verbatim):**
> Create a new file or fully overwrite an existing one; parent
> directories are created. Content is written verbatim (UTF-8) — provide
> the COMPLETE file, never placeholders like '... rest unchanged'.
> Prefer edit_file for changing part of an existing file.

**Input**: `path` (string, required — "Absolute path (~ ok); relative resolves against ~/Projects."), `content` (string, required — "Complete file content, written byte-for-byte.").

**Result**: `{path, bytes, action: "created"|"overwritten", previous_bytes?}`.
Summary: `Created /x (245 bytes).` / `Overwrote /x (245 bytes, was 1020).`

**Behavior**: shared path guard → if target is a directory → error
("Path is a directory, not a file: … Use list_files to browse it.") →
`mkdir -p` parents → record `previous_bytes` if the file exists →
`write_bytes(content.encode("utf-8"))`. OSError → `ToolError` with
`strerror` and the path.

**Errors**: directory target; outside roots; OS failures (permission, no
space) with `strerror`.

## 4. Test checklist (tests/unit/tools/test_write_file.py)

Create with nested parents; byte-verbatim content (CRLF stays CRLF — the
Copilot #1148 regression; no BOM added — #3389); overwrite reports
`action` + `previous_bytes`; empty content → empty file; unicode content;
directory target error; outside roots; permission-denied surfaces
`strerror`.

## 5. Results — 2026-08-30

Unit gate: 8 tests, all pass first run (suite total 56) — including the
CRLF/BOM byte-verbatim regressions and permission-denied `strerror`
surfacing. Wire check created a real file with correct structured output.
No spec corrections needed. Live verification: write-pair checkpoint
(after `edit_file`).
