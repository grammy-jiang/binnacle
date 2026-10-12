"""list_files — browse a directory, or find files recursively by glob.

Spec: docs/tools/list_files.md. Two modes: no glob = one-level listing
(dirs first); glob = recursive `rg --files` match, newest first,
gitignore respected. Glob mode lives in features/files/list_files_glob.py
(split behavior-neutrally, r6 W3 SP1); it uses the system ripgrep on purpose.
"""

import errno
import os
import stat
import subprocess  # noqa: F401 - tests patch lf.subprocess.run (glob mode moved)
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePath
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle.config import ListFilesSettings, RootsSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk, list_files_glob
from binnacle.features.files.error_text import followed
from binnacle.features.files.paths import (
    FileToolAccess,
    nearby_hint,
    resolve_path,
)
from binnacle.features.search.rg_env import noting_unreadable, record_unreadable
from binnacle.platform.contracts.file_access_contracts import ListRequest, RootGrant
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    TOO_MANY_OPEN_FILES_CODE,
)

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
# Glob mode moved to list_files_glob (r6 W3 SP1); the r6 names stay here.
_glob_entries = list_files_glob.glob_entries
_glob_mode = list_files_glob.glob_mode


def _changed(shown: Path) -> CodedToolError:
    # The shared text; Darwin's link refusal after the followed hop uses it too.
    return fd_walk.path_changed(shown, "list_files")


def _refusal(exc: OSError, shown: Path) -> CodedToolError:
    """The coded refusal for any other walk or read failure (SRC-W2-06)."""
    if exc.errno == errno.ELOOP:
        # O_NOFOLLOW met a symlink: the listed directory was swapped.
        return _changed(shown)
    if list_files_glob.is_shortage(exc):
        return list_files_glob.descriptor_shortage(f"open {shown}", "Retry.")
    return CodedToolError("file_io_failed", f"Cannot list {shown}: {exc.strerror}.")


@contextmanager
def _opened(
    top: Path,
    parts: tuple[str, ...],
    shown: Path,
    roots: RootsSettings | None = None,
) -> Iterator[tuple[list[int], int]]:
    """The descriptor chain from the root being listed, and the listed fd.

    Every component is opened no-follow, one at a time (SD-74): a component
    swapped for a symlink or a file after resolve_path fails here instead of
    being followed out of the root. The chain only traverses (O_PATH on
    Linux); the listed directory alone is opened O_RDONLY to be read.
    Every failure is a coded refusal; a race directory_not_found carries
    the nearby hint, as the path check before the walk does (SRC-W2-06).
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
            hint = nearby_hint(shown.parent, roots=roots)
            raise CodedToolError(
                "directory_not_found", f"Directory not found: {shown}.{hint}"
            ) from exc
        except NotADirectoryError as exc:
            raise _changed(shown) from exc
        except PermissionError as exc:
            raise fd_walk.permission_denied(shown) from exc
        except OSError as exc:
            raise _refusal(exc, shown) from exc
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


def _names(alias: Path, held: os.stat_result) -> bool:
    # Absolute, no '..' (never normalized away), as Darwin's grant (LP-a2).
    if not alias.is_absolute() or ".." in alias.parts:
        return False
    try:
        return os.path.samestat(os.stat(alias), held)
    except OSError:
        return False


def _list_mode(
    root: Path,
    max_results: int,
    include_hidden: bool,
    allowed: tuple[Path, ...],
    configured: tuple[tuple[Path, Path], ...] = (),
    *,
    roots: RootsSettings | None = None,
) -> ToolResult:
    # Links resolve inside the innermost root holding root, as Darwin's grant
    # descriptor walk does: '..' into an outer root is omitted (SD-74).
    top = max(
        (r for r in allowed if root.is_relative_to(r)), key=lambda r: len(r.parts)
    )
    try:
        listed = _listed(top, root, include_hidden, configured, roots)
    except CodedToolError as exc:
        # One retry on a descriptor shortage, after every descriptor of the
        # first walk is closed, as DarwinFileAccess.list_entries does: this
        # call's own descriptors never cause the refusal. A second shortage
        # is too_many_open_files (FDW-B1-a2 R2).
        if exc.telemetry_code != TOO_MANY_OPEN_FILES_CODE:
            raise
        listed = _listed(top, root, include_hidden, configured, roots)
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


def _listed(
    top: Path,
    root: Path,
    include_hidden: bool,
    configured: tuple[tuple[Path, Path], ...],
    roots: RootsSettings | None,
) -> list[tuple[str, dict]]:
    """One walk of root below top: (name, entry) for each listed entry.

    Every descriptor it opens is closed when it returns or raises.
    """
    parts = root.relative_to(top).parts
    listed = []
    with _opened(top, parts, root, roots) as (chain, fd):
        held = os.fstat(chain[0])  # Configured aliases, re-checked per call (LP).
        live = [str(a) for a, c in configured if c == top != a and _names(a, held)]

        def follow(name: str) -> os.stat_result | None:
            try:
                return fd_walk.link_target_info(
                    chain[0], parts, name, str(top), chain=chain, aliases=live
                )
            except OSError as exc:  # Only a descriptor shortage (FDW-B1 #9).
                raise _refusal(exc, root) from exc

        try:
            names = os.listdir(fd)  # dup(2): EMFILE is possible here too.
        except OSError as exc:
            raise _refusal(exc, root) from exc
        for name in names:
            if name == ".git" or (not include_hidden and name.startswith(".")):
                continue
            info = _entry_info(fd, name, follow)
            if info is None or not (
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            ):
                continue  # A FIFO, socket or device is omitted, as on Darwin.
            entry: dict = {"path": str(root / name), "type": "dir"}
            if not stat.S_ISDIR(info.st_mode):
                entry.update(type="file", bytes=info.st_size)
            listed.append((name, entry))
    return listed


@noting_unreadable  # Partial result plus one note (R-OS1-F1).
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

        def listed(grant: RootGrant, relative: str, display: Path) -> ToolResult:
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
            # Directories the walk could not open (FileListing.unreadable,
            # Darwin only): the same note as Linux rg's (R-OS1-F1).
            unreadable = getattr(listing, "unreadable", ())
            record_unreadable(str(root_label / path) for path in unreadable)
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

        # An in-root link is listed as its target, as on Linux (PF-PX1-1).
        return followed(
            file_access.operation,
            path,
            "list_files",
            lambda: dict(file_access.grants),
            listed,
        )
    resolved = resolve_path(path, roots=roots)
    if not resolved.exists():
        raise CodedToolError(
            "directory_not_found",
            f"Directory not found: {resolved}.{nearby_hint(resolved.parent, roots=roots)}",
        )
    if not resolved.is_dir() and not resolved.is_file():
        raise CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)
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
    roots = get_settings().roots if roots is None else roots
    allowed = roots.canonical_allowed
    pairs = tuple(zip([r.expanduser() for r in roots.allowed], allowed, strict=True))
    return _list_mode(
        resolved, max_results, include_hidden, allowed, pairs, roots=roots
    )


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
