"""Descriptor walk for the Linux Files tools (r6 W2 X3a, SD-74; X3a-a2, SD-76).

Linux twin of platform/darwin/file_traversal.py ``directory_at`` and
platform/darwin/file_access.py ``absolute_in_root``/``link_target_info``.
A root is opened from '/' one component at a time; every directory below it
is opened with O_NOFOLLOW|O_DIRECTORY relative to its parent descriptor, and
every metadata or link read is relative to an opened directory. A same-uid
swap of an in-root component for a symlink between a check and its use
therefore cannot redirect the walk outside the root. This is not continuous
containment: a directory renamed after it was opened keeps its identity.

On Linux the walk opens directories with O_PATH (RX3a-F1): like a path
lookup, it needs only search (execute) permission, so execute-only
directories in the root chain or inside a root work as they did in r6. Only
a directory that is enumerated is opened O_RDONLY (DIRECTORY_FLAGS).
"""

import errno
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path

from binnacle.errors import CodedToolError

MAX_LINK_HOPS = 40  # Darwin platform/darwin/file_access.py MAX_LINK_HOPS.
# A directory that is read (listed): read permission is required.
DIRECTORY_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY
)
# A directory that is only passed through or stat-ed.
if sys.platform == "linux":
    TRAVERSE_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
else:  # Darwin keeps its own walk (DARWIN-FOLLOWUP-exec-only-dirs).
    TRAVERSE_FLAGS = DIRECTORY_FLAGS
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY


def absolute_in_root(text: str, root: str) -> list[str] | None:
    """Lexical gate for absolute link text (r6 X2; Darwin file_access.py twin).

    The components of text below root, or None: any '..' component, or text
    outside root. Only '' and '.' components are dropped; the filesystem is
    never consulted, so text that steps out and back is no existence oracle.
    A trailing '/' or '/.' keeps one '' marker, so the walk requires a
    directory there, as it does for relative text (RX2-F2).
    """
    raw = text.split("/")
    parts = [part for part in raw if part not in ("", ".")]
    base = [part for part in root.split("/") if part]
    if ".." in parts or parts[: len(base)] != base:
        return None
    below = parts[len(base) :]
    return [*below, ""] if raw[-1] in ("", ".") else below


@contextmanager
def directory_at(
    base_fd: int, parts: Sequence[str], flags: int = TRAVERSE_FLAGS
) -> Iterator[int]:
    """Open each component no-follow before releasing its parent descriptor.

    The last component (base_fd again when parts is empty) gets flags.
    """
    fd = os.open(".", flags if not parts else TRAVERSE_FLAGS, dir_fd=base_fd)
    try:
        for index, part in enumerate(parts, 1):
            last = index == len(parts)
            child = os.open(part, flags if last else TRAVERSE_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def directory_chain(
    base_fd: int, parts: Sequence[str], flags: int = TRAVERSE_FLAGS
) -> Iterator[list[int]]:
    """base_fd and a descriptor for each prefix of parts, opened no-follow.

    The last one gets flags. The caller owns base_fd; the others close on
    exit. A link walk keeps the chain, so '..' returns to an opened parent
    without a new walk from the root (RX3a-F3).
    """
    with ExitStack() as owned:
        chain = [base_fd]
        for index, part in enumerate(parts, 1):
            last = index == len(parts)
            child = os.open(part, flags if last else TRAVERSE_FLAGS, dir_fd=chain[-1])
            owned.callback(os.close, child)
            chain.append(child)
        yield chain


@contextmanager
def open_root(root: Path, flags: int = TRAVERSE_FLAGS) -> Iterator[int]:
    """Open a canonical root from '/'; a symlink component fails (ENOTDIR).

    The root itself gets flags (DIRECTORY_FLAGS when it is listed).
    """
    top = os.open("/", TRAVERSE_FLAGS)
    try:
        with directory_at(top, root.parts[1:], flags) as fd:
            yield fd
    finally:
        os.close(top)


def link_target_info(
    root_fd: int,
    directory: Sequence[str],
    name: str,
    root_path: str,
    *,
    chain: Sequence[int] | None = None,
    aliases: Sequence[str] = (),
) -> os.stat_result | None:
    """ONE no-follow read of a link's target, only if it resolves in the root.

    ``directory`` holds the link's components below root_fd, the root being
    listed. ``chain`` holds root_fd and an open descriptor for each prefix
    of ``directory`` (the last one is the link's directory); without it the
    chain is opened once here. Each further component is opened once,
    relative to its opened parent (RX3a-F3). Absolute text is walked from
    root_fd only when absolute_in_root accepts it for root_path or, failing
    that, for one of ``aliases`` (configured alias strings of that root whose
    identity was re-checked for this call; LP, SD-74). The prefix is chosen
    lexically, once, as on Darwin; the link is walked once. '..' above
    the root (also into an outer root when roots nest), an absolute
    intermediate link, more than MAX_LINK_HOPS links, a non-directory
    intermediate, a dangling link, a loop and any read failure yield None.
    The result is the lstat of the last component, or the fstat of the
    directory a trailing '', '.' or '..' ends on; it is never a symlink, and
    no path string below '/' is followed.
    """
    try:
        with ExitStack() as owned:
            if chain is None:
                chain = owned.enter_context(directory_chain(root_fd, directory))
            return _walk_link(list(chain), name, root_path, aliases)
    except OSError:
        return None


def _walk_link(
    fds: list[int], name: str, root_path: str, aliases: Sequence[str] = ()
) -> os.stat_result | None:
    # fds[0] is the root; descriptors opened here are closed on every exit.
    opened: list[int] = []
    try:
        text = os.readlink(name, dir_fd=fds[-1])
        pending = text.split("/")
        if pending[0] == "":
            below = None
            for prefix in (root_path, *aliases):
                below = absolute_in_root(text, prefix)
                if below is not None:
                    break
            if below is None:
                return None  # '..', another root or an unknown alias: omitted.
            del fds[1:]
            pending = below
        hops = 1
        info: os.stat_result | None = None
        while pending:
            part = pending.pop(0)
            if part in ("", "."):
                info = None
                continue
            if part == "..":
                if len(fds) == 1:
                    return None
                fd = fds.pop()
                if fd in opened:
                    opened.remove(fd)
                    os.close(fd)
                info = None
                continue
            info = os.lstat(part, dir_fd=fds[-1])
            if stat.S_ISLNK(info.st_mode):
                hops += 1
                target = os.readlink(part, dir_fd=fds[-1])
                if hops > MAX_LINK_HOPS or target.startswith("/"):
                    return None
                pending[:0] = target.split("/")
                info = None
                continue
            if pending:
                if not stat.S_ISDIR(info.st_mode):
                    return None
                child = os.open(part, TRAVERSE_FLAGS, dir_fd=fds[-1])
                opened.append(child)
                fds.append(child)
        return os.fstat(fds[-1]) if info is None else info
    finally:
        for fd in opened:
            os.close(fd)


def _opened_path(fd: int) -> str:
    """The path the kernel holds for an open descriptor (Linux /proc)."""
    return os.readlink(f"/proc/self/fd/{fd}")


def _require_linux() -> None:
    # /proc/self/fd is Linux-only; Darwin keeps its own READ_FLAGS walk
    # (RX3a2-N4), so a call there is a programming error, never a refusal.
    if sys.platform != "linux":
        raise RuntimeError("open_verified is Linux-only (RX3a2-N4).")


def open_verified(
    path: str | os.PathLike[str],
    root_paths: Sequence[Path],
    expected: tuple[int, int],
    *,
    parent_fd: int | None = None,
) -> int:
    """Open an already-resolved regular file and verify the opened object.

    For read_file (r6 W2 X3b, SD-76); this is no confinement resolver. The
    final component is opened no-follow and non-blocking: relative to
    ``parent_fd`` when given (open_walked), else by path, which follows
    intermediate symlinks and so can open an outside object before the
    refusal. The descriptor is returned only when its kernel path is inside
    SOME configured root (any one, not only the innermost), its (st_dev,
    st_ino) equals ``expected`` from the caller's containment check, it is
    a regular file and it still has a link (st_nlink > 0: a file deleted
    after the open is path_changed). The checks run in that order
    (RX3a2-N2), so an outside object is always path_outside_root. Otherwise
    the descriptor is closed and a coded refusal is raised.
    """
    _require_linux()
    shown = os.fspath(path)
    try:
        if parent_fd is None:
            fd = os.open(shown, READ_FLAGS)
        else:
            fd = os.open(os.path.basename(shown), READ_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise _open_refusal(exc, shown, root_paths) from exc
    try:
        real = Path(_opened_path(fd))
        if not any(real.is_relative_to(root) for root in root_paths):
            raise _outside(shown, root_paths)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != expected:
            raise _changed(shown)
        if not stat.S_ISREG(info.st_mode):
            raise _not_regular(shown)
        if info.st_nlink == 0:
            raise _changed(shown)
    except BaseException as exc:
        os.close(fd)
        if isinstance(exc, OSError):
            raise _open_refusal(exc, shown, root_paths) from exc
        raise
    return fd


def open_walked(
    path: Path, root_paths: Sequence[Path], expected: tuple[int, int]
) -> int:
    """open_verified relative to a descriptor-walked parent (X3b, RX3a2-N2).

    ``path`` is canonical. The innermost root holding it is opened from '/'
    and every directory below it is traversed no-follow (O_PATH), so a
    component swapped for a symlink fails the walk and nothing outside a
    root is opened. The /proc root check and the identity check stay as
    defence in depth (a directory renamed out after it was opened).
    """
    _require_linux()
    shown = str(path)
    holders = [root for root in root_paths if path.is_relative_to(root)]
    if not holders:
        raise _outside(shown, root_paths)
    top = max(holders, key=lambda root: len(root.parts))
    parts = path.relative_to(top).parts
    if not parts:  # A root itself is a directory.
        raise _not_regular(shown)
    try:
        with open_root(top) as root_fd, directory_at(root_fd, parts[:-1]) as parent:
            return open_verified(path, root_paths, expected, parent_fd=parent)
    except OSError as exc:
        raise _open_refusal(exc, shown, root_paths) from exc


def _open_refusal(
    exc: OSError, shown: str, root_paths: Sequence[Path]
) -> CodedToolError:
    if isinstance(exc, PermissionError):
        return permission_denied(shown)
    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        # A symlink the no-follow open refused. Name an outside target as
        # such (RX3a2-N2); only lstat/readlink are used, nothing is opened.
        real = Path(os.path.realpath(shown))
        if not any(real.is_relative_to(root) for root in root_paths):
            return _outside(shown, root_paths)
        return _changed(shown)
    if exc.errno == errno.ENOENT:
        return _changed(shown)
    return CodedToolError("file_io_failed", f"Cannot open {shown}: {exc.strerror}.")


def _outside(shown: str, root_paths: Sequence[Path]) -> CodedToolError:
    roots = ", ".join(str(root) for root in root_paths)
    return CodedToolError(
        "path_outside_root", f"Path outside allowed roots ({roots}): {shown}"
    )


def _not_regular(shown: str) -> CodedToolError:
    return CodedToolError(
        "not_a_regular_file",
        f"Not a regular file: {shown}. read_file reads regular files only.",
    )


def _changed(shown: str) -> CodedToolError:
    return CodedToolError(
        "path_changed", f"File changed while it was opened: {shown}. Read it again."
    )


def permission_denied(shown: object) -> CodedToolError:
    """The coded refusal for EACCES/EPERM from a walk or an open (RX3a-F2)."""
    return CodedToolError(
        "permission_denied",
        f"Permission denied: {shown}. The server cannot open this path; "
        f"check its permissions or choose another path.",
    )
