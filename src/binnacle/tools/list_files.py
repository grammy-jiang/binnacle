"""list_files — browse a directory, or find files recursively by glob.

Spec: docs/tools/list_files.md. Two modes: no glob = one-level listing
(dirs first); glob = recursive `rg --files` match, newest first,
gitignore respected. Uses the system ripgrep on purpose: bundled
jemalloc builds abort on this Pi's 16 KB kernel pages (Copilot lesson).
"""

import subprocess
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import get_settings
from binnacle.paths import full_match, nearby_hint, resolve_path

LIST_MAX_RESULTS_DEFAULT = get_settings().list_files.max_results_default
LIST_MAX_RESULTS_CAP = get_settings().list_files.max_results_cap
RG_TIMEOUT_S = get_settings().list_files.rg_timeout_s
RG_BIN = get_settings().rg_bin


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "mode": {"type": "string", "enum": ["list", "glob"]},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "type": {"type": "string", "enum": ["file", "dir"]},
                    "bytes": {"type": "integer"},
                },
                "required": ["path", "type"],
            },
        },
        "count": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["path", "mode", "count", "truncated"],
}


def _file_entry(p: Path) -> dict | None:
    try:
        if p.is_dir():
            return {"path": str(p), "type": "dir"}
        return {"path": str(p), "type": "file", "bytes": p.stat().st_size}
    except OSError:
        return None


def _list_mode(root: Path, max_results: int, include_hidden: bool) -> ToolResult:
    children = [
        p
        for p in root.iterdir()
        if p.name != ".git" and (include_hidden or not p.name.startswith("."))
    ]
    children.sort(key=lambda p: (0 if p.is_dir() else 1, p.name.lower()))
    truncated = len(children) > max_results
    entries = [e for p in children[:max_results] if (e := _file_entry(p)) is not None]
    payload = {
        "path": str(root),
        "mode": "list",
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
    }
    summary = f"Listed {len(entries)} entries in {root}."
    if truncated:
        note = (
            f"Showing first {max_results} of {len(children)} entries; "
            f"raise max_results or use a glob."
        )
        payload["note"] = note
        summary = f"Listed first {len(entries)} of {len(children)} entries in {root}."
    return ToolResult(content=summary, structured_content=payload)


def _glob_mode(
    root: Path, glob: str, max_results: int, include_hidden: bool
) -> ToolResult:
    # rg only walks (gitignore/hidden respected); the glob filter runs in
    # Python: rg's --glob "always overrides any other ignore logic", so a
    # positive --glob would whitelist gitignored files (found by the gate).
    pattern = glob if "/" in glob else f"**/{glob}"
    cmd = [RG_BIN, "--files", "--sortr", "modified"]
    if include_hidden:
        cmd += ["--hidden", "--glob", "!**/.git/**"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=RG_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        raise ToolError(
            "ripgrep (rg) is not available on this system; "
            "use run_command (find, ls) instead."
        )
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Glob search timed out after {RG_TIMEOUT_S} s in {root}. "
            f"Narrow the glob or point path at a subdirectory."
        )
    if proc.returncode not in (0, 1):
        stderr = proc.stderr.strip()[-300:]
        raise ToolError(
            f"ripgrep failed in {root}: {stderr or 'unknown error'}. "
            f"Use run_command (find, ls) as a fallback."
        )

    try:
        lines = [
            line
            for line in proc.stdout.splitlines()
            if line and full_match(line, pattern)
        ]
    except ValueError as e:
        raise ToolError(f"Invalid glob pattern {glob!r}: {e}")
    truncated = len(lines) > max_results
    entries = []
    for line in lines[:max_results]:
        p = root / line
        try:
            entries.append({"path": str(p), "type": "file", "bytes": p.stat().st_size})
        except OSError:
            entries.append({"path": str(p), "type": "file"})
    payload = {
        "path": str(root),
        "mode": "glob",
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
    }
    if not entries:
        payload["note"] = (
            f"No files match {glob!r} under {root} "
            f"(gitignored and hidden files are skipped by default)."
        )
        summary = f"No files match {glob!r} under {root}."
    elif truncated:
        payload["note"] = (
            f"Showing first {max_results} of {len(lines)} matches; "
            f"narrow the glob or raise max_results."
        )
        summary = (
            f"Found {len(lines)} files matching {glob!r} under {root}; "
            f"showing newest {max_results}."
        )
    else:
        summary = (
            f"Found {len(entries)} files matching {glob!r} under {root} (newest first)."
        )
    return ToolResult(content=summary, structured_content=payload)


def list_files_impl(
    path: str, glob: str | None, max_results: int, include_hidden: bool
) -> ToolResult:
    resolved = resolve_path(path)
    if not resolved.exists():
        raise ToolError(
            f"Directory not found: {resolved}.{nearby_hint(resolved.parent)}"
        )
    if not resolved.is_dir():
        raise ToolError(
            f"Path is a file, not a directory: {resolved}. Use read_file to read it."
        )
    max_results = max(1, min(max_results, LIST_MAX_RESULTS_CAP))
    if glob:
        return _glob_mode(resolved, glob, max_results, include_hidden)
    return _list_mode(resolved, max_results, include_hidden)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False},
        output_schema=OUTPUT_SCHEMA,
    )
    def list_files(
        path: Annotated[
            str,
            Field(
                description="Directory to list or search under. Absolute (~ allowed); relative resolves against ~/Projects."
            ),
        ] = "~/Projects",
        glob: Annotated[
            str | None,
            Field(
                description="Glob pattern like **/*.py. Present = recursive find; absent = one-level listing."
            ),
        ] = None,
        max_results: Annotated[
            int,
            Field(
                ge=1, le=LIST_MAX_RESULTS_CAP, description="Cap on returned entries."
            ),
        ] = LIST_MAX_RESULTS_DEFAULT,
        include_hidden: Annotated[
            bool, Field(description="Include dotfiles (.git always excluded).")
        ] = False,
    ) -> ToolResult:
        """List a directory (no glob: one level, dirs first) or find files
        recursively by glob (e.g. **/*.py), newest first, gitignore
        respected. Names only; for contents use search_text or read_file.
        """
        return list_files_impl(path, glob, max_results, include_hidden)
