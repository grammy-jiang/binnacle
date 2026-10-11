"""list_files — browse a directory, or find files recursively by glob.

Spec: docs/tools/list_files.md. Two modes: no glob = one-level listing
(dirs first); glob = recursive `rg --files` match, newest first,
gitignore respected. Uses the system ripgrep on purpose: bundled
jemalloc builds abort on this Pi's 16 KB kernel pages (Copilot lesson).
"""

import errno
import os
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePath
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import ListFilesSettings, RootsSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.paths import (
    FileToolAccess,
    full_match,
    nearby_hint,
    resolve_path,
)
from binnacle.features.search.rg_env import NO_CONFIG, rg_env
from binnacle.platform.contracts.file_access_contracts import ListRequest

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
    # Follows links; LIST mode types entries with _list_entry instead (SD-60).
    try:
        if p.is_dir():
            return {"path": str(p), "type": "dir"}
        return {"path": str(p), "type": "file", "bytes": p.stat().st_size}
    except OSError:
        return None


# The r5/r6 names stay importable here; fd_walk holds the shared walk.
MAX_LINK_HOPS = fd_walk.MAX_LINK_HOPS
_absolute_in_root = fd_walk.absolute_in_root


@contextmanager
def _opened(
    top: Path, parts: tuple[str, ...], shown: Path
) -> Iterator[tuple[list[int], int]]:
    """The descriptor chain from the root being listed, and the listed fd.

    Every component is opened no-follow, one at a time (SD-74): a component
    swapped for a symlink or a file after resolve_path fails here instead of
    being followed out of the root. The chain only traverses (O_PATH on
    Linux); the listed directory alone is opened O_RDONLY to be read.
    """
    with ExitStack() as opened:
        try:
            # Only the listed directory itself is opened readable.
            readable = fd_walk.DIRECTORY_FLAGS
            root_fd = opened.enter_context(
                fd_walk.open_root(top) if parts else fd_walk.open_root(top, readable)
            )
            chain = opened.enter_context(
                fd_walk.directory_chain(root_fd, parts, readable)
            )
        except FileNotFoundError as exc:
            raise CodedToolError(
                "directory_not_found", f"Directory not found: {shown}."
            ) from exc
        except NotADirectoryError as exc:
            raise CodedToolError(
                "path_changed",
                f"Directory changed during the listing: {shown}. "
                f"A path component is no longer a directory; list it again.",
            ) from exc
        except PermissionError as exc:
            raise fd_walk.permission_denied(shown) from exc
        # Links resolve through the open chain; the listed fd ends it (F3).
        yield chain, chain[-1]


def _entry_info(
    fd: int, name: str, follow: Callable[[str], os.stat_result | None]
) -> os.stat_result | None:
    """ONE no-follow read of name, or of its contained target if it is a link.

    The entry never re-follows the link: any lstat failure (Darwin
    file_traversal.py walk: EACCES/ENOENT entries are omitted) or a link
    whose target does not resolve inside the root being listed omits the
    entry before it is counted (SD-60).
    """
    try:
        info = os.lstat(name, dir_fd=fd)
    except OSError:
        return None
    return follow(name) if stat.S_ISLNK(info.st_mode) else info


def _list_mode(
    root: Path, max_results: int, include_hidden: bool, allowed: tuple[Path, ...]
) -> ToolResult:
    # Links resolve inside the innermost root holding root, as Darwin's grant
    # descriptor walk does: '..' into an outer root is omitted (SD-74).
    top = max(
        (r for r in allowed if root.is_relative_to(r)), key=lambda r: len(r.parts)
    )
    parts = root.relative_to(top).parts
    listed = []
    with _opened(top, parts, root) as (chain, fd):

        def follow(name: str) -> os.stat_result | None:
            return fd_walk.link_target_info(
                chain[0], parts, name, str(top), chain=chain
            )

        for name in os.listdir(fd):
            if name == ".git" or (not include_hidden and name.startswith(".")):
                continue
            info = _entry_info(fd, name, follow)
            if info is None:
                continue
            entry: dict = {"path": str(root / name), "type": "dir"}
            if not stat.S_ISDIR(info.st_mode):
                entry.update(type="file", bytes=info.st_size)
            listed.append((name, entry))
    listed.sort(key=lambda ne: (0 if ne[1]["type"] == "dir" else 1, ne[0].lower()))
    truncated = len(listed) > max_results
    entries = [e for _, e in listed[:max_results]]
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
            f"Showing first {max_results} of {len(listed)} entries; "
            f"raise max_results or use a glob."
        )
        payload["note"] = note
        summary = f"Listed first {len(entries)} of {len(listed)} entries in {root}."
    return ToolResult(content=summary, structured_content=payload)


def _glob_entries(root: Path, lines: list[str]) -> list[dict]:
    """Size each listed file by ONE no-follow lstat (r6 W2 X3c, SD-76).

    rg lists by path string and never lists a symlink, so every component
    from '/' to the file's directory is opened no-follow (O_PATH on Linux),
    and the file is lstat-ed relative to that descriptor. A path whose
    directory is no longer a directory (swapped for a symlink or a file) or
    whose final component is now a symlink is omitted: no outside object is
    typed or sized. Any other failure keeps the entry without bytes, as r6
    did when p.stat() failed.
    """
    entries: list[dict] = []
    with ExitStack() as stack:
        fds: dict[tuple[str, ...], int] = {}

        def directory(parts: tuple[str, ...]) -> int:
            if parts not in fds:
                if parts:
                    parent = directory(parts[:-1])
                    fd = os.open(parts[-1], fd_walk.TRAVERSE_FLAGS, dir_fd=parent)
                else:
                    fd = os.open("/", fd_walk.TRAVERSE_FLAGS)
                stack.callback(os.close, fd)
                fds[parts] = fd
            return fds[parts]

        for line in lines:
            p = root / line
            entry: dict = {"path": str(p), "type": "file"}
            try:
                info = os.lstat(p.name, dir_fd=directory(p.parent.parts[1:]))
            except OSError as exc:
                if exc.errno in (errno.ENOTDIR, errno.ELOOP):
                    continue
                entries.append(entry)
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            entry["bytes"] = info.st_size
            entries.append(entry)
    return entries


def _glob_mode(
    root: Path,
    glob: str,
    max_results: int,
    include_hidden: bool,
    *,
    rg_bin: str | None = None,
    timeout_s: int | None = None,
) -> ToolResult:
    if rg_bin is None or timeout_s is None:
        defaults = get_settings()
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
        timeout_s = defaults.list_files.rg_timeout_s if timeout_s is None else timeout_s
    # rg only walks (gitignore/hidden respected); the glob filter runs in
    # Python: rg's --glob "always overrides any other ignore logic", so a
    # positive --glob would whitelist gitignored files (found by the gate).
    pattern = glob if "/" in glob else f"**/{glob}"
    cmd = [rg_bin, NO_CONFIG, "--files", "--sortr", "modified"]
    if include_hidden:
        cmd += ["--hidden", "--glob", "!**/.git/**"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=rg_env(),
        )
    except FileNotFoundError as exc:
        raise CodedToolError(
            "rg_missing",
            "ripgrep (rg) is not available on this system; "
            "use run_command (find, ls) instead.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CodedToolError(
            "rg_timeout",
            f"Glob search timed out after {timeout_s} s in {root}. "
            f"Narrow the glob or point path at a subdirectory.",
        ) from exc
    if proc.returncode not in (0, 1):
        stderr = proc.stderr.strip()[-300:]
        raise CodedToolError(
            "rg_failed",
            f"ripgrep failed in {root}: {stderr or 'unknown error'}. "
            f"Use run_command (find, ls) as a fallback.",
        )

    try:
        lines = [
            line
            for line in proc.stdout.splitlines()
            if line and full_match(line, pattern)
        ]
    except ValueError as e:
        raise CodedToolError(
            "invalid_glob", f"Invalid glob pattern {glob!r}: {e}"
        ) from e
    truncated = len(lines) > max_results
    entries = _glob_entries(root, lines[:max_results])
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
    path: str,
    glob: str | None,
    max_results: int,
    include_hidden: bool,
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
    settings: ListFilesSettings | None = None,
    rg_bin: str | None = None,
) -> ToolResult:
    if settings is None or rg_bin is None:
        defaults = get_settings()
        settings = defaults.list_files if settings is None else settings
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
    if file_access is not None:
        file_access.require("list_files")
        with file_access.operation(path, "list_files") as (grant, relative, display):
            cap = settings.max_results_cap
            wanted = max(1, min(max_results, cap))
            # Ask for the full cap so the total behind a "showing first N of M"
            # note is known, as it is on Linux.
            listing = file_access.provider.list_entries(
                grant,
                ListRequest(
                    relative,
                    glob,
                    include_hidden,
                    cap,
                    10000,
                    settings.rg_timeout_s,
                ),
            )
            entries = []
            root_label = display
            for _ in PurePath(relative).parts:
                root_label = root_label.parent
            for entry in listing.entries:
                # A symlink is typed by its in-root target; any other entry the
                # provider could not type (unresolved link, fifo, socket) is omitted.
                kind = entry.target_kind or entry.kind
                if kind not in ("file", "directory"):
                    continue
                item: dict = {
                    "path": str(root_label / entry.relative_path),
                    "type": "dir" if kind == "directory" else "file",
                }
                if entry.size_bytes is not None:
                    item["bytes"] = entry.size_bytes
                entries.append(item)
            total = len(entries)
            shown = entries[:wanted]
            # Beyond the provider cap the true total is unknown: keep the
            # provider's own truncation flag and no total-bearing sentence.
            truncated = total > wanted or listing.truncated
            exact_total = not listing.truncated
            payload: dict = {
                "path": str(display),
                "mode": "glob" if glob else "list",
                "entries": shown,
                "count": len(shown),
                "truncated": truncated,
            }
            summary = f"Listed {len(shown)} entries in {display}."
            if glob:
                if not shown:
                    payload["note"] = (
                        f"No files match {glob!r} under {display} "
                        f"(gitignored and hidden files are skipped by default)."
                    )
                    summary = f"No files match {glob!r} under {display}."
                elif truncated and exact_total:
                    payload["note"] = (
                        f"Showing first {wanted} of {total} matches; "
                        f"narrow the glob or raise max_results."
                    )
                    summary = (
                        f"Found {total} files matching {glob!r} under {display}; "
                        f"showing newest {wanted}."
                    )
                elif not truncated:
                    summary = (
                        f"Found {len(shown)} files matching {glob!r} "
                        f"under {display} (newest first)."
                    )
            elif truncated and exact_total:
                payload["note"] = (
                    f"Showing first {wanted} of {total} entries; "
                    f"raise max_results or use a glob."
                )
                summary = f"Listed first {len(shown)} of {total} entries in {display}."
            return ToolResult(content=summary, structured_content=payload)
    resolved = resolve_path(path, roots=roots)
    if not resolved.exists():
        raise CodedToolError(
            "directory_not_found",
            f"Directory not found: {resolved}.{nearby_hint(resolved.parent, roots=roots)}",
        )
    if not resolved.is_dir():
        raise CodedToolError(
            "path_is_file",
            f"Path is a file, not a directory: {resolved}. Use read_file to read it.",
        )
    max_results = max(1, min(max_results, settings.max_results_cap))
    if glob:
        return _glob_mode(
            resolved,
            glob,
            max_results,
            include_hidden,
            rg_bin=rg_bin,
            timeout_s=settings.rg_timeout_s,
        )
    allowed = (get_settings().roots if roots is None else roots).canonical_allowed
    return _list_mode(resolved, max_results, include_hidden, allowed)


def register(
    mcp: FastMCP,
    *,
    roots: RootsSettings | None = None,
    file_access: FileToolAccess | None = None,
    settings: ListFilesSettings | None = None,
    rg_bin: str | None = None,
) -> None:
    if roots is None or settings is None or rg_bin is None:
        defaults = get_settings()
        roots = defaults.roots if roots is None else roots
        settings = defaults.list_files if settings is None else settings
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
    roots, settings = roots.model_copy(deep=True), settings.model_copy(deep=True)

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
                ge=1,
                le=settings.max_results_cap,
                description="Cap on returned entries.",
            ),
        ] = settings.max_results_default,
        include_hidden: Annotated[
            bool, Field(description="Include dotfiles (.git always excluded).")
        ] = False,
    ) -> ToolResult:
        """List a directory (no glob: one level, dirs first) or find files
        recursively by glob (e.g. **/*.py), newest first, gitignore
        respected. Names only; for contents use search_text or read_file.
        """
        return list_files_impl(
            path,
            glob,
            max_results,
            include_hidden,
            roots=roots,
            file_access=file_access,
            settings=settings,
            rg_bin=rg_bin,
        )
