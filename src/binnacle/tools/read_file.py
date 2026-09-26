"""read_file — read a text file with 1-based line ranges.

Full specification, survey, decision records, and test checklist:
docs/tools/read_file.md. Limits are single-source constants below,
interpolated into messages so text can never drift from code.

The multi-file read candidates under evaluation (2026-09-27, off by
default; read_file.multi_mode) reuse the same per-file steps: `_load`
(checks and decoding), `_window` (line and char windowing) and `_serve`
(payload and summary); tools/read_files.py reads a list of files under
one shared char budget (spec docs/tools/read_files.md).
"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.paths import nearby_hint, resolve_path
from binnacle.textio import decode_text, human_size

READ_MAX_LINES = get_settings().read_file.max_lines  # line ceiling per call
READ_MAX_CHARS = get_settings().read_file.max_chars  # content chars per call
READ_MAX_LINE_CHARS = get_settings().read_file.max_line_chars  # per-line clip
READ_MAX_FILE_BYTES = get_settings().read_file.max_file_bytes  # stat guard
LINE_CLIP_MARK = "… [line truncated]"
MULTI_MODE = get_settings().read_file.multi_mode  # off | param | tool

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
# multi_mode "tool": read_file points to the separate read_files tool.
TOOL_POINTER = " To read several known files in one call, use read_files."

PATH_DESCRIPTION = (
    "Absolute path (~ allowed). A relative path resolves against ~/Projects."
)
START_LINE_DESCRIPTION = "1-based first line to read."
END_LINE_DESCRIPTION = (
    "1-based last line, inclusive. Values past the end of the file are clamped."
)

OUTPUT_SCHEMA: dict[str, Any] = {
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

# -- one file ---------------------------------------------------------------


@dataclass
class _TextFile:
    """A decoded, non-empty text file and the range asked of it."""

    resolved: Path
    size: int
    text: str
    lossy: bool
    lines: list[str]
    start_line: int
    end_line: int | None

    @property
    def requested_end(self) -> int:
        total = len(self.lines)
        return min(self.end_line, total) if self.end_line is not None else total


def _binary(resolved: Path, size: int) -> tuple[str, dict]:
    mime = mimetypes.guess_type(resolved.name)[0] or "unknown type"
    summary = (
        f"Binary file ({human_size(size)}, looks like {mime}) — content not shown."
    )
    return summary, {
        "path": str(resolved),
        "kind": "binary",
        "bytes": size,
        "mime_guess": mime,
        "note": "Content not shown. Use run_command (file, xxd, strings, pdftotext) to inspect it.",
    }


def _empty(resolved: Path, size: int) -> tuple[str, dict]:
    return f"Read {resolved}: file is empty.", {
        "path": str(resolved),
        "kind": "empty",
        "content": "",
        "start_line": 0,
        "end_line": 0,
        "total_lines": 0,
        "bytes": size,
        "truncated": False,
        "note": "File is empty.",
    }


def _load(
    path: str, start_line: int, end_line: int | None
) -> tuple[str, dict] | _TextFile:
    """The checks and decoding of one read, in read_file's order: a final
    (summary, payload) for a binary or empty file, else the decoded text.
    Raises CodedToolError for every per-file problem."""
    resolved = resolve_path(path)
    if not resolved.exists():
        raise CodedToolError(
            "file_not_found",
            f"File not found: {resolved}.{nearby_hint(resolved.parent)}",
        )
    if resolved.is_dir():
        raise CodedToolError(
            "path_is_directory",
            f"Path is a directory, not a file: {resolved}. Use list_files to browse it.",
        )
    size = resolved.stat().st_size
    if size > READ_MAX_FILE_BYTES:
        raise CodedToolError(
            "file_too_large",
            f"File is {human_size(size)}; the limit is "
            f"{READ_MAX_FILE_BYTES // (1024 * 1024)} MB. "
            f"Use run_command (tail, sed -n, grep) to sample it.",
        )
    if end_line is not None and start_line > end_line:
        raise CodedToolError(
            "range_invalid",
            f"start_line ({start_line}) is greater than end_line ({end_line}).",
        )

    decoded = decode_text(resolved.read_bytes(), resolved)
    if decoded is None:
        return _binary(resolved, size)
    text, lossy = decoded

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines == 0:
        return _empty(resolved, size)
    if start_line > total_lines:
        raise CodedToolError(
            "range_past_end",
            f"start_line {start_line} exceeds total_lines {total_lines} of {resolved}.",
        )
    return _TextFile(resolved, size, text, lossy, lines, start_line, end_line)


def _window(f: _TextFile, char_cap: int) -> tuple[list[str], int, int, int]:
    """(served lines, served_end, chars, lines_clipped): at most
    READ_MAX_LINES lines and char_cap chars, always at least one line."""
    hard_end = min(f.requested_end, f.start_line + READ_MAX_LINES - 1)
    served: list[str] = []
    chars = 0
    lines_clipped = 0
    served_end = f.start_line - 1
    for idx in range(f.start_line - 1, hard_end):
        line = f.lines[idx]
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if len(body) > READ_MAX_LINE_CHARS:
            line = body[:READ_MAX_LINE_CHARS] + LINE_CLIP_MARK + ending
            lines_clipped += 1
        if served and chars + len(line) > char_cap:
            break
        served.append(line)
        chars += len(line)
        served_end = idx + 1
        if chars >= char_cap:
            break
    return served, served_end, chars, lines_clipped


def _serve(f: _TextFile, char_cap: int) -> tuple[str, dict]:
    """read_file's payload and summary for one decoded file under char_cap."""
    start_line, end_line, total_lines = f.start_line, f.end_line, len(f.lines)
    notes: list[str] = []
    if end_line is not None and end_line > total_lines:
        notes.append(f"end_line clamped to {total_lines} (end of file).")
    requested_end = f.requested_end
    served, served_end, _chars, lines_clipped = _window(f, char_cap)

    truncated = served_end < requested_end
    payload: dict = {
        "path": str(f.resolved),
        "kind": "text",
        "content": "".join(served),
        "start_line": start_line,
        "end_line": served_end,
        "total_lines": total_lines,
        "bytes": f.size,
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
    if f.lossy:
        payload["lossy"] = True
        notes.append("Some bytes could not be decoded and were replaced with U+FFFD.")
    # A partial read of a file that would fit in one call: say so, once.
    partial = start_line > 1 or served_end < total_lines
    fits_whole = (
        not truncated
        and partial
        and total_lines <= READ_MAX_LINES
        and len(f.text) <= READ_MAX_CHARS
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
            f"Read lines {start_line}-{served_end} of {total_lines} from {f.resolved}; "
            f"continue with start_line={served_end + 1}."
        )
    elif start_line == 1 and served_end == total_lines:
        summary = f"Read all {total_lines} lines from {f.resolved}."
    else:
        summary = (
            f"Read lines {start_line}-{served_end} of {total_lines} from {f.resolved}."
        )
        if fits_whole:
            summary += " The whole file fits in one call."
    return summary, payload


def read_file_impl(path: str, start_line: int, end_line: int | None) -> ToolResult:
    loaded = _load(path, start_line, end_line)
    summary, payload = (
        loaded if isinstance(loaded, tuple) else _serve(loaded, READ_MAX_CHARS)
    )
    return ToolResult(content=summary, structured_content=payload)


# -- registration -------------------------------------------------------------


def register(mcp: FastMCP, multi_mode: str | None = None) -> None:
    mode = multi_mode or MULTI_MODE
    if mode == "param":
        from binnacle.tools.read_files import register_param

        register_param(mcp)
        return

    @mcp.tool(
        description=DESCRIPTION + (TOOL_POINTER if mode == "tool" else ""),
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=OUTPUT_SCHEMA,
    )
    def read_file(
        path: Annotated[
            str,
            Field(description=PATH_DESCRIPTION),
        ],
        start_line: Annotated[int, Field(ge=1, description=START_LINE_DESCRIPTION)] = 1,
        end_line: Annotated[
            int | None,
            Field(ge=1, description=END_LINE_DESCRIPTION),
        ] = None,
    ) -> ToolResult:
        """See DESCRIPTION (shipped text; interpolates the limits)."""
        return read_file_impl(path, start_line, end_line)
