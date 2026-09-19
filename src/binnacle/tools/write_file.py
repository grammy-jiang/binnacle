"""write_file — create or fully overwrite a file, verbatim UTF-8.

Spec: docs/tools/write_file.md. No newline or BOM transformation ever
(Copilot's CRLF/BOM bugs are the cautionary tales); the overwrite case is
reported loudly (action + previous_bytes) and gated by ChatGPT's own
per-write confirmation.
"""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.paths import resolve_path

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "bytes": {"type": "integer"},
        "action": {"type": "string", "enum": ["created", "overwritten"]},
        "previous_bytes": {"type": "integer"},
    },
    "required": ["path", "bytes", "action"],
}


def write_file_impl(path: str, content: str) -> ToolResult:
    resolved = resolve_path(path)
    if resolved.is_dir():
        raise ToolError(
            f"Path is a directory, not a file: {resolved}. Use list_files to browse it."
        )
    previous_bytes = resolved.stat().st_size if resolved.exists() else None
    data = content.encode("utf-8")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
    except OSError as e:
        raise ToolError(f"Could not write {resolved}: {e.strerror or e}.")

    if previous_bytes is None:
        payload = {"path": str(resolved), "bytes": len(data), "action": "created"}
        summary = f"Created {resolved} ({len(data)} bytes)."
    else:
        payload = {
            "path": str(resolved),
            "bytes": len(data),
            "action": "overwritten",
            "previous_bytes": previous_bytes,
        }
        summary = f"Overwrote {resolved} ({len(data)} bytes, was {previous_bytes})."
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        output_schema=OUTPUT_SCHEMA,
    )
    def write_file(
        path: Annotated[
            str,
            Field(
                description="Absolute path (~ ok); relative resolves against ~/Projects."
            ),
        ],
        content: Annotated[
            str, Field(description="Complete file content, written byte-for-byte.")
        ],
    ) -> ToolResult:
        """Create a new file or fully overwrite an existing one; parent
        directories are created. Content is written verbatim (UTF-8) —
        provide the COMPLETE file, never placeholders like '... rest
        unchanged'. Prefer edit_file for changing part of an existing file.
        """
        return write_file_impl(path, content)
