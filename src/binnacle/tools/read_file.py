"""read_file — read a text file with 1-based line ranges.

Full specification, survey, decision records, and test checklist:
docs/tools/read_file.md. Limits are single-source constants below,
interpolated into messages so text can never drift from code.
"""

import mimetypes
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import get_settings
from binnacle.paths import nearby_hint, resolve_path
from binnacle.textio import decode_text, human_size

READ_MAX_LINES = get_settings().read_file.max_lines  # line ceiling per call
READ_MAX_CHARS = get_settings().read_file.max_chars  # content chars per call
READ_MAX_LINE_CHARS = get_settings().read_file.max_line_chars  # per-line clip
READ_MAX_FILE_BYTES = get_settings().read_file.max_file_bytes  # stat guard
LINE_CLIP_MARK = "… [line truncated]"

# Shipped description; the limits are interpolated so the text cannot drift
# from the constants. Rewritten 2026-09-06: the earlier "start narrow"
# wording matched a measured habit of 26-line slices re-read hundreds of
# times (docs/usage-analysis-2026-09-06.md §6).
DESCRIPTION = (
    "Read a text file, optionally a line range (1-based, inclusive). One call "
    f"returns at most {READ_MAX_CHARS // 1000}k chars (about "
    f"{READ_MAX_CHARS // 4000}k tokens, ~{READ_MAX_CHARS // 50} lines of prose); "
    "a file within that comes back whole, so omit the range. For a larger file "
    "do not page through it: search_text to locate, then read only that range. "
    "Returns plain content without line numbers, plus total_lines and "
    "next_start_line when truncated. Binary or media files return a note; "
    "inspect those with run_command (file, xxd, pdftotext)."
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "kind": {"type": "string", "enum": ["text", "binary", "empty"]},
        "content": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
        "total_lines": {"type": "integer"},
        "bytes": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "next_start_line": {"type": "integer"},
        "lines_clipped": {"type": "integer"},
        "lossy": {"type": "boolean"},
        "mime_guess": {"type": "string"},
        "note": {"type": "string"},
        "fits_in_one_call": {"type": "boolean"},
    },
    "required": ["path", "kind", "bytes"],
}


def read_file_impl(path: str, start_line: int, end_line: int | None) -> ToolResult:
    resolved = resolve_path(path)
    if not resolved.exists():
        raise ToolError(f"File not found: {resolved}.{nearby_hint(resolved.parent)}")
    if resolved.is_dir():
        raise ToolError(
            f"Path is a directory, not a file: {resolved}. Use list_files to browse it."
        )
    size = resolved.stat().st_size
    if size > READ_MAX_FILE_BYTES:
        raise ToolError(
            f"File is {human_size(size)}; the limit is "
            f"{READ_MAX_FILE_BYTES // (1024 * 1024)} MB. "
            f"Use run_command (tail, sed -n, grep) to sample it."
        )
    if end_line is not None and start_line > end_line:
        raise ToolError(
            f"start_line ({start_line}) is greater than end_line ({end_line})."
        )

    decoded = decode_text(resolved.read_bytes(), resolved)
    if decoded is None:
        mime = mimetypes.guess_type(resolved.name)[0] or "unknown type"
        summary = (
            f"Binary file ({human_size(size)}, looks like {mime}) — content not shown."
        )
        return ToolResult(
            content=summary,
            structured_content={
                "path": str(resolved),
                "kind": "binary",
                "bytes": size,
                "mime_guess": mime,
                "note": "Content not shown. Use run_command (file, xxd, strings, pdftotext) to inspect it.",
            },
        )
    text, lossy = decoded

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines == 0:
        return ToolResult(
            content=f"Read {resolved}: file is empty.",
            structured_content={
                "path": str(resolved),
                "kind": "empty",
                "content": "",
                "start_line": 0,
                "end_line": 0,
                "total_lines": 0,
                "bytes": size,
                "truncated": False,
                "note": "File is empty.",
            },
        )
    if start_line > total_lines:
        raise ToolError(
            f"start_line {start_line} exceeds total_lines {total_lines} of {resolved}."
        )

    notes: list[str] = []
    if end_line is not None and end_line > total_lines:
        notes.append(f"end_line clamped to {total_lines} (end of file).")
    requested_end = min(end_line, total_lines) if end_line is not None else total_lines
    hard_end = min(requested_end, start_line + READ_MAX_LINES - 1)

    served: list[str] = []
    chars = 0
    lines_clipped = 0
    served_end = start_line - 1
    for idx in range(start_line - 1, hard_end):
        line = lines[idx]
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if len(body) > READ_MAX_LINE_CHARS:
            line = body[:READ_MAX_LINE_CHARS] + LINE_CLIP_MARK + ending
            lines_clipped += 1
        if served and chars + len(line) > READ_MAX_CHARS:
            break
        served.append(line)
        chars += len(line)
        served_end = idx + 1
        if chars >= READ_MAX_CHARS:
            break

    truncated = served_end < requested_end
    payload: dict = {
        "path": str(resolved),
        "kind": "text",
        "content": "".join(served),
        "start_line": start_line,
        "end_line": served_end,
        "total_lines": total_lines,
        "bytes": size,
        "truncated": truncated,
    }
    if truncated:
        payload["next_start_line"] = served_end + 1
    if lines_clipped:
        payload["lines_clipped"] = lines_clipped
        notes.append(
            f"{lines_clipped} line(s) exceeded {READ_MAX_LINE_CHARS} chars and were "
            f"clipped ('{LINE_CLIP_MARK}'); clipped lines are not safe to use as "
            f"edit_file.old_string."
        )
        if total_lines == 1:
            notes.append(
                "Single-line file; use run_command (fold, cut, jq) to see more."
            )
    if lossy:
        payload["lossy"] = True
        notes.append("Some bytes could not be decoded and were replaced with U+FFFD.")
    # A partial read of a file that would fit in one call: say so, once.
    partial = start_line > 1 or served_end < total_lines
    fits_whole = (
        not truncated
        and partial
        and total_lines <= READ_MAX_LINES
        and len(text) <= READ_MAX_CHARS
    )
    if fits_whole:
        payload["fits_in_one_call"] = True
        notes.append(
            f"The whole file ({total_lines} lines) fits in one call; omit "
            f"start_line and end_line to read it all."
        )
    if notes:
        payload["note"] = " ".join(notes)

    if truncated:
        summary = (
            f"Read lines {start_line}-{served_end} of {total_lines} from {resolved}; "
            f"continue with start_line={served_end + 1}."
        )
    elif start_line == 1 and served_end == total_lines:
        summary = f"Read all {total_lines} lines from {resolved}."
    else:
        summary = (
            f"Read lines {start_line}-{served_end} of {total_lines} from {resolved}."
        )
        if fits_whole:
            summary += " The whole file fits in one call."
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        description=DESCRIPTION,
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=OUTPUT_SCHEMA,
    )
    def read_file(
        path: Annotated[
            str,
            Field(
                description="Absolute path (~ allowed). A relative path resolves against ~/Projects."
            ),
        ],
        start_line: Annotated[
            int, Field(ge=1, description="1-based first line to read.")
        ] = 1,
        end_line: Annotated[
            int | None,
            Field(
                ge=1,
                description="1-based last line, inclusive. Values past the end of the file are clamped.",
            ),
        ] = None,
    ) -> ToolResult:
        """See DESCRIPTION (shipped text; interpolates the limits)."""
        return read_file_impl(path, start_line, end_line)
