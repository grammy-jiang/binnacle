"""edit_file — exact-string replacement with a whitespace-normalized fallback.

Spec: docs/tools/edit_file.md. Two match tiers (exact, then line-trimmed
with re-indentation — the deterministic core of Gemini's cascade, without
its fuzzy/LLM tiers). Zero text normalization: BOM is preserved through
the edit, CRLF and typographic quotes are matched byte-for-byte
(Copilot's normalization bugs are the cautionary tales).
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import get_settings
from binnacle.paths import nearby_hint, resolve_path

SNIPPET_CONTEXT_LINES = get_settings().edit_file.snippet_context_lines

_BOM_CODECS = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "replacements": {"type": "integer"},
        "match": {"type": "string", "enum": ["exact", "whitespace_normalized"]},
        "first_change_line": {"type": "integer"},
        "snippet": {"type": "string"},
        "snippet_first_line": {"type": "integer"},
        "bytes": {"type": "integer"},
    },
    "required": ["path", "replacements", "match"],
}


def _decode_for_edit(data: bytes, path) -> tuple[str, bytes, str]:
    """Returns (text, bom_bytes, codec). Raises ToolError on binary/lossy."""
    bom, codec = b"", "utf-8"
    for candidate_bom, candidate_codec in _BOM_CODECS:
        if data.startswith(candidate_bom):
            bom, codec = candidate_bom, candidate_codec
            data = data[len(bom) :]
            break
    else:
        if b"\0" in data[:8192]:
            raise ToolError(
                f"Binary file: {path}. edit_file only edits text; "
                f"use run_command for binary files."
            )
    try:
        return data.decode(codec), bom, codec
    except UnicodeDecodeError:
        raise ToolError(
            f"File {path} has bytes that do not decode as {codec}; editing "
            f"it here would corrupt them. Use run_command (sed) instead."
        )


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snippet_around(text: str, first_change_line: int) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    start = max(0, first_change_line - 1 - SNIPPET_CONTEXT_LINES)
    end = min(len(lines), first_change_line + SNIPPET_CONTEXT_LINES)
    return "".join(lines[start:end]), start + 1


def _reindent(new_string: str, old_first_line: str, matched_first_line: str) -> str:
    """Shift new_string by the indentation delta of the matched block."""
    old_indent = old_first_line[: len(old_first_line) - len(old_first_line.lstrip())]
    matched_indent = matched_first_line[
        : len(matched_first_line) - len(matched_first_line.lstrip())
    ]
    if old_indent == matched_indent:
        return new_string
    out = []
    for line in new_string.splitlines(keepends=True):
        stripped = line.lstrip()
        if not stripped:
            out.append(line)
        elif line.startswith(old_indent):
            out.append(matched_indent + line[len(old_indent) :])
        else:
            out.append(matched_indent + stripped)
    return "".join(out)


def _flexible_matches(text: str, old_string: str) -> list[tuple[int, int]]:
    """Line-trimmed window compare. Returns (start_line_idx, end_line_idx) spans."""
    text_lines = text.splitlines(keepends=True)
    old_trimmed = [line.strip() for line in old_string.splitlines()]
    if not old_trimmed:
        return []
    spans = []
    window = len(old_trimmed)
    for i in range(len(text_lines) - window + 1):
        if all(text_lines[i + j].strip() == old_trimmed[j] for j in range(window)):
            spans.append((i, i + window))
    return spans


def edit_file_impl(
    path: str, old_string: str, new_string: str, replace_all: bool
) -> ToolResult:
    resolved = resolve_path(path)
    if not resolved.exists():
        raise ToolError(
            f"File not found: {resolved}.{nearby_hint(resolved.parent)} "
            f"To create a new file, use write_file."
        )
    if resolved.is_dir():
        raise ToolError(f"Path is a directory, not a file: {resolved}.")
    if not old_string:
        raise ToolError(
            "old_string must be non-empty. To create or fully rewrite a "
            "file, use write_file."
        )
    if old_string == new_string:
        raise ToolError("old_string and new_string are identical; nothing to change.")

    text, bom, codec = _decode_for_edit(resolved.read_bytes(), resolved)

    match_tier = "exact"
    count = text.count(old_string)
    if count > 0:
        if count > 1 and not replace_all:
            line_numbers = []
            start = 0
            while (idx := text.find(old_string, start)) != -1:
                line_numbers.append(_line_of_offset(text, idx))
                start = idx + 1
            raise ToolError(
                f"Found {count} occurrences of old_string in {resolved} "
                f"(lines {', '.join(map(str, line_numbers))}). Add surrounding "
                f"context to make it unique, or set replace_all=true."
            )
        first_idx = text.find(old_string)
        first_change_line = _line_of_offset(text, first_idx)
        new_text = text.replace(old_string, new_string)
        replacements = count
    else:
        spans = _flexible_matches(text, old_string)
        if not spans:
            raise ToolError(
                f"old_string not found in {resolved}. The file may have "
                f"changed since you read it — call read_file on the target "
                f"range and copy the exact text (whitespace and quote "
                f"characters matter; never include line-number prefixes)."
            )
        if len(spans) > 1 and not replace_all:
            lines_list = ", ".join(str(s[0] + 1) for s in spans)
            raise ToolError(
                f"Found {len(spans)} whitespace-normalized matches in "
                f"{resolved} (lines {lines_list}). Add surrounding context "
                f"to make it unique, or set replace_all=true."
            )
        match_tier = "whitespace_normalized"
        text_lines = text.splitlines(keepends=True)
        old_first_line = old_string.splitlines()[0]
        for start_idx, end_idx in reversed(spans):
            replacement = _reindent(new_string, old_first_line, text_lines[start_idx])
            # keep the original trailing newline of the replaced block
            block = "".join(text_lines[start_idx:end_idx])
            body = block.rstrip("\r\n")
            ending = block[len(body) :]
            if replacement and not replacement.endswith(("\n", "\r")):
                replacement += ending
            text_lines[start_idx:end_idx] = [replacement] if replacement else []
        new_text = "".join(text_lines)
        first_change_line = spans[0][0] + 1
        replacements = len(spans)

    data = bom + new_text.encode(codec)
    try:
        resolved.write_bytes(data)
    except OSError as e:
        raise ToolError(f"Could not write {resolved}: {e.strerror or e}.")

    snippet, snippet_first_line = _snippet_around(new_text, first_change_line)
    payload = {
        "path": str(resolved),
        "replacements": replacements,
        "match": match_tier,
        "first_change_line": first_change_line,
        "snippet": snippet,
        "snippet_first_line": snippet_first_line,
        "bytes": len(data),
    }
    tier_note = "" if match_tier == "exact" else " (whitespace-normalized match)"
    plural = "occurrence" if replacements == 1 else "occurrences"
    summary = (
        f"Replaced {replacements} {plural} in {resolved}"
        f"{tier_note} (first change at line {first_change_line})."
    )
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        output_schema=OUTPUT_SCHEMA,
    )
    def edit_file(
        path: Annotated[
            str,
            Field(
                description="Absolute path (~ ok); relative resolves against ~/Projects."
            ),
        ],
        old_string: Annotated[
            str,
            Field(description="Exact text to replace, copied verbatim from the file."),
        ],
        new_string: Annotated[
            str,
            Field(description="Replacement text; empty string deletes old_string."),
        ],
        replace_all: Annotated[
            bool,
            Field(
                description="Replace every occurrence instead of requiring uniqueness."
            ),
        ] = False,
    ) -> ToolResult:
        """Replace an exact string in a text file. old_string must match
        the file byte-for-byte (copy it from read_file content; never
        include line-number prefixes) and must be unique unless
        replace_all=true. A whitespace-normalized fallback match is
        attempted and reported. Returns a snippet of the changed region.
        Use write_file to create files.
        """
        return edit_file_impl(path, old_string, new_string, replace_all)
