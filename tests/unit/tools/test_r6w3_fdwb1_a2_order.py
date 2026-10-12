"""One open-check order and one shortage retry on both OSes (r6 W3 FDW-B1-a2, SD-91).

R1: a file the tools read is opened no-follow and non-blocking, then the
fstat TYPE of the opened object decides (a FIFO, socket or device is
special_file_unsupported, a directory path_is_directory; never read), then
its IDENTITY against the pre-open stat (another regular file is
path_changed). Linux fd_walk.open_verified checked identity first; Darwin
file_traversal.checked_open has the identity step, and its entry_changed is
now worded as Linux's path_changed. Each swap is injected by a hook at the
final open, between the stat and the open, on both paths.

R2: Linux list mode retries ONE descriptor shortage (EMFILE/ENFILE) after
closing every descriptor of its first walk, as DarwinFileAccess.list_entries
does; a second shortage is too_many_open_files on both paths.

Every case runs on both OSes. DarwinFileAccess is constructed directly (never
through platform.composition), so the Darwin path runs on the Pi. The Linux
read path needs /proc for its root check: off Linux, the /proc read is
replaced by fcntl(F_GETPATH), the kernel path of the same descriptor, and the
Linux-only guard is lifted for the call; on Linux nothing is replaced.
"""

import errno
import os
import shutil
import stat
import sys
import tempfile
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ListFilesSettings, ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import error_text, fd_walk, paths
from binnacle.features.files.tools import list_files as lf
from binnacle.features.files.tools import read_file as rf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import RootGrant
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    too_many_open_files_text,
)
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)
SHORTAGE = pytest.mark.parametrize("code", [errno.EMFILE, errno.ENFILE])


@pytest.fixture
def base() -> Iterator[Path]:
    # A NON-secret fixture tree; no credential or socket lives here.
    made = Path(tempfile.mkdtemp(prefix="r6w3-fdwb1a2-", dir="/tmp")).resolve()
    try:
        yield made
    finally:
        shutil.rmtree(made)


@pytest.fixture
def patch(base: Path) -> Iterator[pytest.MonkeyPatch]:
    # Undone before base's teardown, which needs the real os functions.
    with pytest.MonkeyPatch.context() as patcher:
        yield patcher


@pytest.fixture
def root(base: Path) -> Path:
    top = base / "root"
    (top / "sub").mkdir(parents=True)
    (top / "sub" / "f.txt").write_text("in sub\n")
    (top / "a.txt").write_text("checked\n")
    (top / "lnk").symlink_to("sub/f.txt")
    return top


def roots_for(top: Path) -> RootsSettings:
    return RootsSettings(default_root=top, extra_roots=())


def access_for(top: Path) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots_for(top),
        files=DarwinFileAccess(),
        search=None,
        generation="r6w3-fdwb1a2",
        capability=Capability(CapabilityState.LIMITED, "test_only", "fdwb1a2"),
    )


def _kernel_path(fd: int) -> str:
    import fcntl  # Darwin: the path the kernel holds for fd, as /proc on Linux.

    raw = fcntl.fcntl(fd, getattr(fcntl, "F_GETPATH"), bytes(1024))  # noqa: B009
    return raw.split(b"\0", 1)[0].decode()


def linux_read_path(patch: pytest.MonkeyPatch) -> None:
    """read_file_impl takes its Linux branch (fd_walk.open_walked) on this host."""
    patch.setattr(rf, "sys", types.SimpleNamespace(platform="linux"))
    if sys.platform != "linux":
        patch.setattr(fd_walk, "_require_linux", lambda: None)
        patch.setattr(fd_walk, "_opened_path", _kernel_path)


def outcome(top: Path, darwin: bool, call: Callable) -> tuple:
    """(code or "ok", text) of one tool call on the Linux or the Darwin path."""
    access = access_for(top) if darwin else None
    code: str | None
    try:
        result = call(roots_for(top), access)
        text, code = result.content[0].text, "ok"
    except ToolError as exc:
        text, code = str(exc), getattr(exc, "telemetry_code", None)
    finally:
        if access is not None:
            access.close()
    return code, text


def reading(path: Path) -> Callable:
    return lambda roots, access: rf.read_file_impl(
        str(path),
        1,
        None,
        roots=None if access else roots,
        file_access=access,
        settings=ReadFileSettings(),
    )


def listing(path: Path) -> Callable:
    return lambda roots, access: lf.list_files_impl(
        str(path),
        None,
        200,
        False,
        roots=roots,
        file_access=access,
        settings=ListFilesSettings(),
        rg_bin="rg",
    )


# R1: open -> TYPE -> IDENTITY, a swap injected at the final open.


def regular(path: Path) -> None:
    # os.replace of a DIFFERENT file that exists first: a new inode on every
    # filesystem (unlink-then-create can reuse the number on ext4, STEER-01).
    incoming = path.with_name("incoming.txt")
    incoming.write_text("swapped in\n")
    os.replace(incoming, path)


def rewrite_in_place(path: Path) -> None:
    with path.open("r+b") as same:  # The same inode, new bytes.
        same.truncate(0)
        same.write(b"rewritten\n")


def fifo_swap(path: Path) -> None:
    path.unlink()
    os.mkfifo(path)


def directory_swap(path: Path) -> None:
    path.unlink()
    path.mkdir()


SWAPS: dict[str, Callable[[Path], None]] = {
    "regular": regular,
    "fifo": fifo_swap,
    "directory": directory_swap,
}


def expected(kind: str, target: Path) -> tuple[str, str]:
    if kind == "regular":
        return (
            "path_changed",
            f"File changed while it was opened: {target}. Read it again.",
        )
    if kind == "fifo":
        return SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT
    return (
        "path_is_directory",
        f"Path is a directory, not a file: {target}. Use list_files to browse it.",
    )


def swap_at_open(patch, target: Path, make: Callable[[Path], None]) -> list[str]:
    """The final no-follow open of target first swaps it (after every stat)."""
    real_open, fired = os.open, list[str]()

    def swapping(path, flags, *args, **kwargs):
        if path == target.name and kwargs.get("dir_fd") is not None and not fired:
            fired.append(path)
            make(target)
        return real_open(path, flags, *args, **kwargs)

    patch.setattr(os, "open", swapping)
    return fired


def no_reads(patch) -> list[int]:
    reads: list[int] = []
    real_read = os.read

    def reading(fd: int, n: int) -> bytes:
        reads.append(fd)
        return real_read(fd, n)

    patch.setattr(os, "read", reading)
    return reads


@PATHS
@pytest.mark.timeout(10)  # A blocking open of the FIFO would wait for a writer.
@pytest.mark.parametrize("kind", list(SWAPS))
def test_a_swap_between_the_stat_and_the_open_is_refused_alike(
    root, patch, darwin, kind
):
    target = root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    fired = swap_at_open(patch, target, SWAPS[kind])
    reads = no_reads(patch)
    assert outcome(root, darwin, reading(target)) == expected(kind, target)
    assert fired == ["a.txt"]
    assert reads == []  # Never read: not the swapped-in object, not the old one.


@PATHS
def test_an_in_place_rewrite_of_the_same_inode_is_read(root, patch, darwin):
    # Identity is (st_dev, st_ino): a rewrite keeps it, so the open is the
    # checked file and its current bytes are read, on both OSes.
    target = root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    fired = swap_at_open(patch, target, rewrite_in_place)
    assert outcome(root, darwin, reading(target)) == (
        "ok",
        f"Read all 1 lines from {target}.",
    )
    assert fired == ["a.txt"]
    assert target.read_text() == "rewritten\n"


def test_darwin_checked_open_allows_an_in_place_rewrite(root):
    checked = os.lstat(root / "a.txt")
    rewrite_in_place(root / "a.txt")
    parent = os.open(root, file_traversal.TRAVERSE_FLAGS)
    try:
        fd = file_traversal.checked_open(
            parent, "a.txt", file_traversal.READ_FLAGS, checked
        )
        os.close(fd)
    finally:
        os.close(parent)


@PATHS
def test_without_a_swap_the_file_reads(root, patch, darwin):
    target = root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    assert outcome(root, darwin, reading(target)) == (
        "ok",
        f"Read all 1 lines from {target}.",
    )


@pytest.fixture
def fifo(root: Path) -> tuple[Path, tuple[int, int]]:
    """A FIFO and the identity of ANOTHER object: both checks would refuse."""
    path = root / "fifo"
    os.mkfifo(path)
    other = os.lstat(root / "a.txt")
    return path, (other.st_dev, other.st_ino)


@pytest.mark.timeout(10)
def test_linux_open_verified_checks_the_type_before_the_identity(root, patch, fifo):
    path, other = fifo
    linux_read_path(patch)
    with pytest.raises(CodedToolError) as caught:
        fd_walk.open_walked(path, (root,), other)
    assert (caught.value.telemetry_code, str(caught.value)) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


@pytest.mark.timeout(10)
def test_darwin_checked_open_checks_the_type_before_the_identity(root, fifo):
    path, _ = fifo
    regular_info = os.lstat(root / "a.txt")  # The policy saw a regular file.
    parent = os.open(root, file_traversal.TRAVERSE_FLAGS)
    try:
        with pytest.raises(UnsafePath) as caught:
            file_traversal.checked_open(
                parent, path.name, file_traversal.READ_FLAGS, regular_info
            )
    finally:
        os.close(parent)
    assert caught.value.code == SPECIAL_FILE_CODE


def test_darwin_checked_open_has_the_identity_step(root):
    checked = os.lstat(root / "a.txt")
    parent = os.open(root, file_traversal.TRAVERSE_FLAGS)
    try:
        regular(root / "a.txt")  # Another regular file: only identity differs.
        with pytest.raises(UnsafePath) as caught:
            file_traversal.checked_open(
                parent, "a.txt", file_traversal.READ_FLAGS, checked
            )
    finally:
        os.close(parent)
    assert caught.value.code == "entry_changed"


@pytest.mark.timeout(10)
def test_the_legacy_path_checks_the_type_before_the_identity(fifo):
    path, other = fifo
    with pytest.raises(CodedToolError) as caught:
        rf._read_legacy(path, other, ReadFileSettings())
    assert caught.value.telemetry_code == SPECIAL_FILE_CODE


@pytest.mark.parametrize(
    ("tool", "text"),
    [
        ("read_file", "File changed while it was opened: {}. Read it again."),
        ("edit_file", "File changed while it was opened: {}. Read it again."),
        ("write_file", "File changed while it was opened: {}. Write it again."),
    ],
)
def test_darwin_entry_changed_is_worded_as_path_changed(tool, text):
    display = Path("/r/a.txt")
    mapped = error_text.linux_error(
        file_traversal.unsafe("entry_changed"),
        tool,
        files=None,
        grants=(),
        allowed=(),
        grant=cast("RootGrant", None),
        rel="a.txt",
        display=display,
    )
    assert mapped is not None
    assert (mapped.telemetry_code, str(mapped)) == (
        "path_changed",
        text.format(display),
    )


# R2: list mode retries one shortage after closing its own descriptors.


def fail_open(patch, name: str, code: int, times: int | None = None) -> list[int]:
    """os.open of name (relative to a dir_fd) fails with code; others pass.

    Returns the number of descriptors this process holds at each failed
    open, so a retry that leaked the first walk's descriptors shows up.
    """
    real_open, held = os.open, list[int]()

    def failing(path, flags, *args, **kwargs):
        wanted = path == name and kwargs.get("dir_fd") is not None
        if wanted and (times is None or len(held) < times):
            held.append(_open_descriptors())
            raise OSError(code, os.strerror(code))
        return real_open(path, flags, *args, **kwargs)

    patch.setattr(os, "open", failing)
    return held


def _open_descriptors() -> int:
    table = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
    return len(os.listdir(table))


@PATHS
@SHORTAGE
@pytest.mark.parametrize("where", ["listed_directory", "link_walk"])
def test_one_shortage_in_the_listing_is_retried(root, patch, darwin, code, where):
    # 'sub' is the listed directory itself, or the directory the link walk
    # of lnk -> sub/f.txt opens; list mode never opens it otherwise.
    listed = root / "sub" if where == "listed_directory" else root
    held = fail_open(patch, "sub", code, times=1)
    count = 1 if where == "listed_directory" else 3
    assert outcome(root, darwin, listing(listed)) == (
        "ok",
        f"Listed {count} entries in {listed}.",
    )
    assert len(held) == 1


@PATHS
@SHORTAGE
@pytest.mark.parametrize("where", ["listed_directory", "link_walk"])
def test_a_second_shortage_is_refused(root, patch, darwin, code, where):
    listed = root / "sub" if where == "listed_directory" else root
    held = fail_open(patch, "sub", code)
    assert outcome(root, darwin, listing(listed)) == (
        "too_many_open_files",
        too_many_open_files_text("list_files", f"open {listed}"),
    )
    assert len(held) == 2  # Exactly one retry, never more.


@PATHS
@SHORTAGE
def test_the_retry_starts_after_the_first_walk_closed_its_descriptors(
    root, patch, darwin, code
):
    # The link walk fails deep in the first walk; the retry fails at the same
    # point holding no more descriptors than the first attempt did.
    held = fail_open(patch, "sub", code)
    outcome(root, darwin, listing(root))
    assert len(held) == 2 and held[1] == held[0]


@PATHS
def test_another_listing_failure_is_not_retried(root, patch, darwin):
    held = fail_open(patch, "sub", errno.EIO)
    code, _ = outcome(root, darwin, listing(root / "sub"))
    assert code == "file_io_failed"
    assert len(held) == 1


def test_the_type_constants_are_one_set():
    assert rf.SPECIAL_FILE_TYPES is fd_walk.SPECIAL_FILE_TYPES
    assert {stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK} == set(
        fd_walk.SPECIAL_FILE_TYPES
    )
