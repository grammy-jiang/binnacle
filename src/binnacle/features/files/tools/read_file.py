"""read_file — read a text file with 1-based line ranges.

Full specification, survey, decision records, and test checklist:
docs/tools/read_file.md. Limits are captured construction settings,
interpolated into messages so text can never drift from code.
"""

import mimetypes
import os
import stat
import sys
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import ReadFileSettings, RootsSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.paths import FileToolAccess, nearby_hint, resolve_path
from binnacle.features.files.textio import decode_text, human_size
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
)

LINE_CLIP_MARK = "… [line truncated]"
# A FIFO, socket or device: Darwin's file_traversal.regular_fd refuses these.
SPECIAL_FILE_TYPES = (stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK)
# fd_walk's refusals for such an object: the type check after the open (a
# FIFO or device), ENXIO (a socket) and EACCES (a disk device) at the open.
SPECIAL_FILE_REFUSALS = ("not_a_regular_file", "file_io_failed", "permission_denied")


def _description(settings: ReadFileSettings) -> str:
    """Keep the advertised read window tied to its captured limits."""
    return (
        "Read a text file, optionally a line range (1-based, inclusive). One call "
        f"returns at most {settings.max_chars // 1000}k chars (about "
        f"{settings.max_chars // 4000}k tokens, ~{settings.max_chars // 50} lines of prose); "
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


def _too_large(size: int, settings: ReadFileSettings) -> CodedToolError:
    return CodedToolError(
        "file_too_large",
        f"File is {human_size(size)}; the limit is "
        f"{settings.max_file_bytes // (1024 * 1024)} MB. "
        f"Use run_command (tail, sed -n, grep) to sample it.",
    )


def special_file_unsupported() -> CodedToolError:
    """The refusal for a FIFO, socket or device on both OSes (r6 W3 RF1).

    Code and text come from platform/contracts/special_file_contracts.py,
    the one source for both OSes. Darwin raises the same code in
    platform/darwin/file_traversal.py, which FileToolAccess.operation words
    as f"{code}."; until that call site uses the shared text (r6 W3 wave B),
    read_file_impl rewords the Darwin refusal with this helper, so read_file
    says the same thing on both OSes.
    """
    return CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)


def _is_special(resolved: Path, expected: tuple[int, int]) -> bool:
    """The checked object is still there and is a FIFO, socket or device."""
    try:
        info = os.lstat(resolved)
    except OSError:
        return False
    return (info.st_dev, info.st_ino) == expected and (
        stat.S_IFMT(info.st_mode) in SPECIAL_FILE_TYPES
    )


def _read_at_most(fd: int, limit: int) -> bytes:
    """Read at most limit bytes from fd.

    Each read(2) asks only for the bytes still allowed, so at most limit
    bytes are read; a file under the limit also gets a final request that
    sees end of file (RX3b3-F1). No buffered file object, so no read-ahead
    past the bound (RX3b2-F1).
    """
    chunks: list[bytes] = []
    left = limit
    while left > 0:
        chunk = os.read(fd, left)
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _read_bounded(fd: int, settings: ReadFileSettings) -> bytes:
    """Read at most max_file_bytes from fd; a file that grew is file_too_large."""
    data = _read_at_most(fd, settings.max_file_bytes + 1)
    if len(data) > settings.max_file_bytes:
        grown = os.fstat(fd).st_size
        raise _too_large(max(grown, len(data)), settings)
    return data


def _read_legacy(
    resolved: Path, expected: tuple[int, int], settings: ReadFileSettings
) -> bytes:
    """The non-Linux read without a file_access adapter (SRC-W2-10).

    Production Darwin reads through DarwinFileAccess; this path serves tests
    and direct read_file_impl calls. It opens with fd_walk.READ_FLAGS
    (O_NONBLOCK: a FIFO swapped in after the stat never blocks the open;
    O_NOFOLLOW: a final symlink is not followed), checks that the opened
    object is the checked regular file, and reads at most max_file_bytes + 1
    bytes, as on Linux.
    """
    fd = os.open(resolved, fd_walk.READ_FLAGS)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != expected:
            # The same words as fd_walk's path_changed on Linux.
            raise CodedToolError(
                "path_changed",
                f"File changed while it was opened: {resolved}. Read it again.",
            )
        if not stat.S_ISREG(opened.st_mode):
            raise special_file_unsupported()
        return _read_bounded(fd, settings)
    finally:
        os.close(fd)


def _read_checked(
    resolved: Path,
    expected: tuple[int, int],
    roots: RootsSettings | None,
    settings: ReadFileSettings,
) -> bytes:
    """Read the object the containment check saw, or refuse (SD-76, X3b).

    Linux opens it through the descriptor walk, verifies the opened object
    (fd_walk.open_verified) and reads only from that descriptor; the path
    is never opened again. The read stops after max_file_bytes + 1 bytes, so
    a file that grew after the stat is file_too_large, never read unbounded
    (RX3b-F6); the raw descriptor is read with os.read, each request asking
    only for the bytes still allowed, so at most max_file_bytes + 1 bytes are
    read from the descriptor (RX3b2-F1, RX3b3-F1). Darwin keeps its own READ_FLAGS walk (RX3a2-N4) and never
    calls open_verified. read_file_impl refuses a FIFO, socket or device by
    its pre-open stat (SRC-W2-01), so one reaches this point only after a
    race; a special file that fd_walk refuses is still worded
    special_file_unsupported when an lstat shows the checked object
    (X3b-a3); path_outside_root and path_changed are never reworded, and
    nothing is opened again. Other OSes read through _read_legacy.
    """
    if sys.platform == "linux":
        allowed = (get_settings().roots if roots is None else roots).canonical_allowed
        try:
            fd = fd_walk.open_walked(resolved, allowed, expected)
        except CodedToolError as exc:
            if exc.telemetry_code in SPECIAL_FILE_REFUSALS and _is_special(
                resolved, expected
            ):
                raise special_file_unsupported() from exc
            raise
        try:
            return _read_bounded(fd, settings)
        finally:
            os.close(fd)
    else:
        return _read_legacy(resolved, expected, settings)


def read_file_impl(
    path: str,
    start_line: int,
    end_line: int | None,
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
    settings: ReadFileSettings | None = None,
) -> ToolResult:
    settings = get_settings().read_file if settings is None else settings
    if file_access is not None:
        file_access.require("read_file")
        try:
            resolved, size, data = file_access.read(path, settings.max_file_bytes)
        except CodedToolError as exc:
            # Darwin words this code as f"{code}." until wave B (r6 W3 RF1).
            if exc.telemetry_code == SPECIAL_FILE_CODE:
                raise special_file_unsupported() from exc
            raise
    else:
        resolved = resolve_path(path, roots=roots)
        if not resolved.exists():
            raise CodedToolError(
                "file_not_found",
                f"File not found: {resolved}.{nearby_hint(resolved.parent, roots=roots)}",
            )
        if resolved.is_dir():
            raise CodedToolError(
                "path_is_directory",
                f"Path is a directory, not a file: {resolved}. Use list_files to browse it.",
            )
        checked = resolved.stat()
        if not stat.S_ISREG(checked.st_mode):
            # SRC-W2-01: a FIFO, socket or device is refused by this stat,
            # before any open; the verify after the open still covers a race.
            raise special_file_unsupported()
        if checked.st_size > settings.max_file_bytes:
            raise _too_large(checked.st_size, settings)
    if end_line is not None and start_line > end_line:
        raise CodedToolError(
            "range_invalid",
            f"start_line ({start_line}) is greater than end_line ({end_line}).",
        )

    if file_access is None:
        data = _read_checked(
            resolved, (checked.st_dev, checked.st_ino), roots, settings
        )
        # SRC-W2-11: report the bytes read from the verified descriptor, as
        # Darwin's FileToolAccess.read does, not the pre-open stat size.
        size = len(data)
    decoded = decode_text(data, resolved)
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
        raise CodedToolError(
            "range_past_end",
            f"start_line {start_line} exceeds total_lines {total_lines} of {resolved}.",
        )

    notes: list[str] = []
    if end_line is not None and end_line > total_lines:
        notes.append(f"end_line clamped to {total_lines} (end of file).")
    requested_end = min(end_line, total_lines) if end_line is not None else total_lines
    hard_end = min(requested_end, start_line + settings.max_lines - 1)

    served: list[str] = []
    chars = 0
    lines_clipped = 0
    served_end = start_line - 1
    for idx in range(start_line - 1, hard_end):
        line = lines[idx]
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if len(body) > settings.max_line_chars:
            line = body[: settings.max_line_chars] + LINE_CLIP_MARK + ending
            lines_clipped += 1
        if served and chars + len(line) > settings.max_chars:
            break
        served.append(line)
        chars += len(line)
        served_end = idx + 1
        if chars >= settings.max_chars:
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
            f"{lines_clipped} line(s) exceeded {settings.max_line_chars} chars and were "
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
        and total_lines <= settings.max_lines
        and len(text) <= settings.max_chars
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


def register(
    mcp: FastMCP,
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
    settings: ReadFileSettings | None = None,
) -> None:
    if roots is None or settings is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        settings = defaults.read_file if settings is None else settings
    roots, settings = roots.model_copy(deep=True), settings.model_copy(deep=True)

    @mcp.tool(
        description=_description(settings),
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
        """Read using the settings captured with the advertised description."""
        return read_file_impl(
            path,
            start_line,
            end_line,
            roots=roots,
            file_access=file_access,
            settings=settings,
        )
