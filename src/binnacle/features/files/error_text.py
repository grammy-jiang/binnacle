"""Linux wording for file-tool failures raised by the Darwin adapters.

The adapters report terse codes (``path_not_found``); the Linux tools say what
happened and what to do next. This module maps one to the other so both hosts
give the same sentence for the same condition. It never decides whether a
request is allowed; it only words a refusal that was already made.
"""

import errno
import os
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from contextvars import ContextVar
from pathlib import Path, PurePath
from typing import TypeVar

from binnacle.errors import CodedToolError
from binnacle.features.files.fd_walk import path_changed, permission_denied
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.file_access_contracts import (
    FileAccess,
    ListRequest,
    RootGrant,
)
from binnacle.platform.contracts.special_file_contracts import (
    PATH_IS_DIRECTORY_CODE,
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    TOO_MANY_OPEN_FILES_CODE,
    path_is_directory_text,
    too_many_open_files_text,
)

# Tool named by the last access.require() in this call context.
TOOL: ContextVar[str] = ContextVar("binnacle_file_tool", default="read_file")
TERSE_OUTSIDE = ("Path outside opened roots.", "Unsafe relative path.")

# Linux texts for a missing target, per tool.
MISSING_ERRORS = {
    "list_files": ("directory_not_found", "Directory not found"),
    "search_text": ("path_not_found", "Path not found"),
}
DEFAULT_MISSING = ("file_not_found", "File not found")
# Tools whose Darwin open of one file can see it swapped (checked_open).
ENTRY_CHANGED_TOOLS = ("read_file", "edit_file", "write_file")
# Symlink hops caller_form follows before it gives up (the kernel's MAXSYMLINKS).
_MAX_LINKS = 32
T = TypeVar("T")
Operation = Callable[[str, str], AbstractContextManager[tuple[RootGrant, str, Path]]]


def outside_error(allowed: Iterable[Path], display: Path) -> CodedToolError:
    roots = ", ".join(str(r) for r in allowed)
    return CodedToolError(
        "path_outside_root", f"Path outside allowed roots ({roots}): {display}"
    )


def _resolve(path: Path) -> Path:
    """Path.resolve() as Python 3.13+ does it, on every supported version.

    Before 3.13, Path.resolve() raises RuntimeError for a symlink loop; 3.13+
    is os.path.realpath(strict=False), which leaves the looping tail in place.
    The display and link-target logic below needs the 3.13 answer (r6 W3 PX1c).
    """
    return Path(os.path.realpath(path))


def caller_form(requested: Path, resolved: Path, roots: Iterable[Path]) -> Path:
    """`resolved` spelled the way the caller and the configuration spelled it.

    Display only; every decision has already been made on `resolved`. The
    caller's text and configured root prefixes are kept as written, so /tmp
    stays /tmp on macOS. Only symlinks inside an allowed (canonical) root are
    followed, through their own link text: they are what moved the request
    elsewhere. The result names the same location as `resolved`, otherwise
    `resolved` itself is returned.
    """
    if not requested.is_absolute():
        return resolved
    canonical = tuple(roots)
    shown = Path(requested.anchor)
    pending = list(requested.parts[1:])
    links = 0
    try:
        while pending:
            part = pending.pop(0)
            if part == "..":
                shown = shown.parent
                continue
            step = shown / part
            here = _resolve(shown)
            if any(here.is_relative_to(r) for r in canonical) and step.is_symlink():
                links += 1
                if links > _MAX_LINKS:
                    return resolved
                target = PurePath(os.readlink(step))
                if target.is_absolute():
                    shown = Path(target.anchor)
                pending[:0] = target.parts[1:] if target.is_absolute() else target.parts
                continue
            shown = step
        same = _resolve(shown) == resolved
    except (RuntimeError, OSError, ValueError):
        return resolved
    return shown if same else resolved


def outside_display(requested: Path, resolved: Path, roots: Iterable[Path]) -> Path:
    """Refusal wording only: the caller's spelling on macOS, the real path on Linux.

    Linux keeps its long-standing wording byte for byte; macOS spells system
    aliases (/tmp, /etc, /var) as the caller did instead of /private/... .
    """
    from binnacle.platform.composition import host_os_family

    if host_os_family() == "linux":
        return resolved
    return caller_form(requested, resolved, roots)


def format_nearby(parent: Path, names: Sequence[str]) -> str:
    if not names:
        return f" Directory {parent} is empty."
    more = " …" if len(names) > 10 else ""
    return (
        f" Files in {parent}: {', '.join(names[:10])}{more}. Use list_files for more."
    )


def _nearby(
    files: FileAccess | None, grant: RootGrant, parts: tuple[str, ...], display: Path
) -> str:
    """Linux nearby_hint wording, listed through the grant, not the pathname."""
    if not parts or files is None:
        return ""
    request = ListRequest("/".join(parts[:-1]), None, True, 1000, 10000, 5.0)
    try:
        entries = files.list_entries(grant, request).entries
    except (NativeCapabilityError, OSError):
        return ""
    parent = display.parent
    names = []
    for e in entries:
        n = PurePath(e.relative_path).name
        # An out-of-root symlink has no typed target here; Linux follows it.
        is_dir = (e.target_kind or e.kind) == "directory" or (
            e.kind == "other" and (parent / n).is_dir()
        )
        names.append(n + "/" if is_dir else n)
    return format_nearby(parent, sorted(names))


def _missing(
    tool: str, files: FileAccess | None, grant: RootGrant, rel: str, display: Path
) -> CodedToolError:
    code, text = MISSING_ERRORS.get(tool, DEFAULT_MISSING)
    tail = " To create a new file, use write_file." if tool == "edit_file" else ""
    hint = _nearby(files, grant, PurePath(rel).parts, display)
    return CodedToolError(code, f"{text}: {display}.{hint}{tail}")


def linux_error(
    exc: NativeCapabilityError,
    tool: str,
    *,
    files: FileAccess | None,
    grants: Iterable[Path],
    allowed: Iterable[Path],
    grant: RootGrant,
    rel: str,
    display: Path,
) -> CodedToolError | None:
    """The sentence Linux gives for the condition behind a terse adapter code."""
    code = exc.code
    if code in ("file_not_found", "path_not_found"):
        return _missing(tool, files, grant, rel, display)
    if code == SPECIAL_FILE_CODE:
        # The shared text for every tool on both OSes (r6 W3 PX1).
        return CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)
    if code == TOO_MANY_OPEN_FILES_CODE:
        # Darwin EMFILE/ENFILE: Linux list mode's sentence (PF-SP1-1).
        return CodedToolError(code, too_many_open_files_text(tool, f"open {display}"))
    if code == "permission_denied_tcc_possible":
        # Darwin keeps its code (SD-77) and says Linux's sentence (R-OS1-F4).
        return CodedToolError(code, str(permission_denied(display)))
    if code == "entry_changed" and tool in ENTRY_CHANGED_TOOLS:
        # The opened file is another regular file than the one stat-ed: the
        # identity step after the type step, Linux's path_changed (FDW-B1-a2).
        return path_changed(display, tool)
    if code == PATH_IS_DIRECTORY_CODE:
        return CodedToolError(code, path_is_directory_text(display, tool))
    if code != "symlink_or_wrong_path_type":
        return None
    try:
        resolved = _resolve(display)
        canonical = [_resolve(r) for r in grants]
        if not any(resolved.is_relative_to(r) for r in canonical):
            return outside_error(allowed, caller_form(display, resolved, canonical))
    except (RuntimeError, OSError):
        return None
    if resolved.exists() and not resolved.is_dir() and not resolved.is_file():
        # A FIFO, socket or device opened as a directory (list, glob).
        return CodedToolError(SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)
    if tool == "list_files" and resolved.is_file():
        return CodedToolError(
            "path_is_file",
            f"Path is a file, not a directory: {display}. Use read_file to read it.",
        )
    if tool == "write_file" and any(
        p.is_file() or (p.is_symlink() and not p.exists()) for p in display.parents
    ):
        # A file or a link loop where a parent directory should be (Linux mkdir).
        return CodedToolError(
            "write_failed", f"Could not write {display}: File exists."
        )
    if resolved.is_symlink() and not resolved.exists():
        # A link loop: Linux resolves the request to itself and finds nothing.
        if tool == "write_file":
            loop = os.strerror(errno.ELOOP)
            return CodedToolError("write_failed", f"Could not write {display}: {loop}.")
        return _missing(tool, files, grant, rel, display)
    if tool != "write_file" and not resolved.exists():
        # Below a file or a loop ("a.txt/x", "loop/x"): Linux finds nothing.
        return _missing(tool, files, grant, rel, display)
    return None


def link_target(
    exc: NativeCapabilityError, display: Path, roots: Iterable[Path]
) -> Path | None:
    """The in-root path a request names through a symlink, else None (R-OS1-F3).

    Linux resolves the request (resolve_path) and opens what it names. Darwin
    refuses any link on its no-follow walk (symlink_or_wrong_path_type); this
    resolves the request the way Linux does, only to choose which in-root path
    to open next. The open is again a no-follow descriptor walk from a grant,
    so a link retargeted in between is refused, never followed. A target
    outside every root keeps the refusal, which linux_error words as
    path_outside_root.
    """
    if exc.code != "symlink_or_wrong_path_type":
        return None
    try:
        target = _resolve(display)
    except (RuntimeError, OSError):
        return None
    if target == Path(os.path.normpath(display)):
        return None
    return target if any(target.is_relative_to(r) for r in roots) else None


def followed(
    operation: Operation,
    raw: str,
    tool: str,
    roots: Iterable[Path] | Callable[[], Iterable[Path]],
    step: Callable[[RootGrant, str, Path], T],
) -> T:
    """Follow only a link that was present during the *first* resolution.

    The previous retry-on-ELOOP path could follow a link appearing after the
    initial stat, and read a swapped-in in-root file on Darwin while Linux
    refused the same race. Resolve only to choose an original in-root target;
    the target itself is still opened via a new descriptor-verified grant.
    A newly appearing link is never followed (FDW-B1-a3 F3).
    """
    target: Path | None = None
    request_display: Path | None = None
    initially_linked = False
    try:
        with operation(raw, tool) as (grant, relative, display):
            request_display = display
            resolved = _resolve(display)
            initially_linked = resolved != Path(os.path.normpath(display))
            if initially_linked:
                allowed = roots() if callable(roots) else roots
                if any(resolved.is_relative_to(r) for r in allowed):
                    target = resolved
            if target is None:
                return step(grant, relative, display)
    except CodedToolError as exc:
        if (
            not initially_linked
            and request_display is not None
            and exc.telemetry_code == "path_outside_root"
        ):
            # The newly swapped-in outside link is named by the *request*,
            # as Linux's _open_refusal does; static outside-link texts stay
            # byte-identical to their existing XOS contract.
            allowed = roots() if callable(roots) else roots
            raise outside_error(allowed, request_display) from exc
        raise
    if target is None:
        raise path_changed(
            request_display if request_display is not None else raw, tool
        )
    with operation(str(target), tool) as (grant, relative, display):
        return step(grant, relative, display)
