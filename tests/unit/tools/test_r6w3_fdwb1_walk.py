"""W3 fd-walk parity bugs on both paths (r6 W3 FDW-B1, SD-86; FDW-PREP items).

(9) EMFILE/ENFILE during a link walk is the too_many_open_files refusal on
both paths, never a silently omitted entry. PREP gap 4: Linux open_walked
maps EMFILE/ENFILE to the same shared template. (10) Darwin list mode types
an entry by fstatat alone (Linux lstat-s it): no listed file is opened, and
the peak descriptor count is bounded by the depth, not the entry count; a
descriptor shortage retries the Darwin listing once, as Linux's
DirectoryChain does. (12) Darwin decides the type by fstat AFTER the open:
a regular file swapped for a FIFO after the stat is special_file_unsupported
and never read. (5) The Darwin root grant opens '/' only to pass through it
(O_SEARCH; O_PATH on Linux), and a search-only ancestor still works.

Every case runs on both OSes: DarwinFileAccess is constructed directly
(never through platform.composition), so the Darwin path runs on the Pi.
"""

import errno
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ListFilesSettings, ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk, paths
from binnacle.features.files.tools import list_files as lf
from binnacle.features.files.tools import read_file as rf
from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    Capability,
    CapabilityState,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import ListRequest
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
    made = Path(tempfile.mkdtemp(prefix="r6w3-fdwb1-", dir="/tmp")).resolve()
    try:
        yield made
    finally:
        pending = [made]
        while pending:  # Readable again before it is listed (search-only dirs).
            directory = pending.pop()
            directory.chmod(0o755)
            pending += [
                p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
            ]
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
    (top / "a.txt").write_text("alpha\n")
    (top / "lnk").symlink_to("sub/f.txt")
    return top


def roots_for(top: Path) -> RootsSettings:
    return RootsSettings(default_root=top, extra_roots=())


def access_for(top: Path) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots_for(top),
        files=DarwinFileAccess(),
        search=None,
        generation="r6w3-fdwb1",
        capability=Capability(CapabilityState.LIMITED, "test_only", "fdwb1"),
    )


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


def fail_open(patch, name: str, code: int, times: int | None = None) -> list[str]:
    """os.open of name (relative to a dir_fd) fails with code; others pass."""
    real_open, failed = os.open, list[str]()

    def failing(path, flags, *args, **kwargs):
        wanted = path == name and kwargs.get("dir_fd") is not None
        if wanted and (times is None or len(failed) < times):
            failed.append(path)
            raise OSError(code, os.strerror(code))
        return real_open(path, flags, *args, **kwargs)

    patch.setattr(os, "open", failing)
    return failed


# (9) EMFILE/ENFILE during the link walk.


@PATHS
@SHORTAGE
def test_a_shortage_in_the_link_walk_is_too_many_open_files(root, patch, darwin, code):
    # lnk -> sub/f.txt: the walk opens 'sub'; list mode itself never does.
    fail_open(patch, "sub", code)
    assert outcome(root, darwin, listing(root)) == (
        "too_many_open_files",
        too_many_open_files_text("list_files", f"open {root}"),
    )


@PATHS
def test_without_a_shortage_the_link_is_listed_as_its_target(root, darwin):
    code, text = outcome(root, darwin, listing(root))
    assert (code, text) == ("ok", f"Listed 3 entries in {root}.")


def test_another_link_walk_failure_still_omits_the_entry(root, patch):
    # Only a shortage is raised; any other failure keeps the oracle-free None.
    fail_open(patch, "sub", errno.EACCES)
    with fd_walk.open_root(root) as root_fd:
        assert fd_walk.link_target_info(root_fd, (), "lnk", str(root)) is None


# PREP gap 4: Linux open_walked EMFILE/ENFILE.


@SHORTAGE
def test_open_walked_shortage_is_too_many_open_files(root, patch, code):
    # open_walked is Linux-only (/proc); its refusal mapping is not, so the
    # /proc guard is lifted and the final open fails before any /proc read.
    patch.setattr(fd_walk, "_require_linux", lambda: None)
    fail_open(patch, "a.txt", code)
    target = root / "a.txt"
    info = target.stat()
    with pytest.raises(CodedToolError) as caught:
        fd_walk.open_walked(target, (root,), (info.st_dev, info.st_ino))
    assert caught.value.telemetry_code == "too_many_open_files"
    assert str(caught.value) == too_many_open_files_text("read_file", f"open {target}")


@SHORTAGE
def test_read_file_shortage_text_is_equal_on_both_paths(root, patch, code):
    # The Darwin read of the same file words the same refusal (error_text).
    fail_open(patch, "a.txt", code)
    target = root / "a.txt"
    darwin = outcome(
        root,
        True,
        lambda roots, access: rf.read_file_impl(
            str(target), 1, None, file_access=access, settings=ReadFileSettings()
        ),
    )
    linux = fd_walk._open_refusal(OSError(code, os.strerror(code)), str(target), ())
    assert darwin == (linux.telemetry_code, str(linux))


# (10) Darwin list mode: fstatat only; peak descriptors bounded by depth.


class Descriptors:
    """Counts the descriptors os.open/os.dup hand out and os.close returns."""

    def __init__(self, patch) -> None:
        self.live: set[int] = set()
        self.peak = 0
        self.names: list[str] = []
        real_open, real_dup, real_close = os.open, os.dup, os.close

        def opened(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            self.names.append(os.fspath(path))
            self._add(fd)
            return fd

        def dup(fd):
            new = real_dup(fd)
            self._add(new)
            return new

        def close(fd):
            self.live.discard(fd)
            real_close(fd)

        patch.setattr(os, "open", opened)
        patch.setattr(os, "dup", dup)
        patch.setattr(os, "close", close)

    def _add(self, fd: int) -> None:
        self.live.add(fd)
        self.peak = max(self.peak, len(self.live))


def deep_tree(base: Path, depth: int, files: int) -> tuple[Path, Path]:
    top = base / f"root-{depth}-{files}"
    listed = top.joinpath(*[f"d{level}" for level in range(depth)])
    (listed / "child").mkdir(parents=True)
    for index in range(files):
        (listed / f"f{index:03}.txt").write_text("x")
    return top, listed


def peak_of(base: Path, patch, darwin: bool, depth: int, files: int) -> tuple:
    top, listed = deep_tree(base, depth, files)
    with patch.context() as patched:
        counted = Descriptors(patched)
        code, _ = outcome(top, darwin, listing(listed))
    assert code == "ok"
    return counted.peak, counted.names


@PATHS
def test_list_mode_opens_no_listed_entry(base, patch, darwin):
    _, names = peak_of(base, patch, darwin, 2, 40)
    assert not [name for name in names if name.startswith("f") or name == "child"]


@PATHS
def test_peak_descriptors_are_bounded_by_depth_not_entries(base, patch, darwin):
    few, _ = peak_of(base, patch, darwin, 3, 2)
    many, _ = peak_of(base, patch, darwin, 3, 120)
    deep, _ = peak_of(base, patch, darwin, 9, 2)
    assert few == many
    # Each extra level costs at most one held descriptor (Linux keeps the
    # chain; Darwin holds two transiently), never one per entry.
    assert deep - few <= 6
    assert many <= len(base.parts) + 3 + 6


def darwin_grant(top: Path) -> tuple[DarwinFileAccess, object]:
    files = DarwinFileAccess()
    return files, files.grant(top, generation="r6w3-fdwb1")


@SHORTAGE
def test_darwin_listing_retries_one_shortage(root, patch, code):
    failed = fail_open(patch, "sub", code, times=1)
    files, grant = darwin_grant(root)
    try:
        result = files.list_entries(grant, ListRequest("", None, False, 50, 100, 5.0))
    finally:
        files.close()
    assert failed == ["sub"]
    assert sorted(entry.relative_path for entry in result.entries) == [
        "a.txt",
        "lnk",
        "sub",
    ]


@SHORTAGE
def test_darwin_listing_refuses_a_second_shortage(root, patch, code):
    failed = fail_open(patch, "sub", code)
    files, grant = darwin_grant(root)
    try:
        with pytest.raises(AuthorityUnknown) as caught:
            files.list_entries(grant, ListRequest("", None, False, 50, 100, 5.0))
    finally:
        files.close()
    assert caught.value.code == "too_many_open_files"
    assert failed == ["sub", "sub"]


# (12) Darwin: the type of the opened object decides.


def swap_after_stat(patch, target: Path, make: Callable[[Path], None]) -> None:
    """The pre-open stat of target sees the regular file; then it is swapped."""
    real_stat = os.stat

    def swapping(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None:
            target.unlink()
            make(target)
        return info

    patch.setattr(os, "stat", swapping)


def test_a_file_swapped_for_a_fifo_is_refused_and_never_read(root, patch):
    target = root / "a.txt"
    reads: list[int] = []
    real_read = os.read
    patch.setattr(os, "read", lambda fd, n: reads.append(fd) or real_read(fd, n))
    swap_after_stat(patch, target, os.mkfifo)
    files, grant = darwin_grant(root)
    try:
        with pytest.raises(UnsafePath) as caught:
            files.open_read(grant, "a.txt")
    finally:
        files.close()
    assert caught.value.code == SPECIAL_FILE_CODE
    assert reads == []
    assert stat.S_ISFIFO(os.lstat(target).st_mode)


def test_the_fifo_swap_is_worded_with_the_shared_text(root, patch):
    target = root / "a.txt"
    swap_after_stat(patch, target, os.mkfifo)
    call = lambda roots, access: rf.read_file_impl(
        str(target), 1, None, file_access=access, settings=ReadFileSettings()
    )
    assert outcome(root, True, call) == (SPECIAL_FILE_CODE, SPECIAL_FILE_TEXT)


def test_a_file_swapped_for_a_directory_is_path_is_directory(root, patch):
    swap_after_stat(patch, root / "a.txt", lambda path: path.mkdir())
    files, grant = darwin_grant(root)
    try:
        with pytest.raises(UnsafePath) as caught:
            files.open_read(grant, "a.txt")
    finally:
        files.close()
    assert caught.value.code == "path_is_directory"


def test_a_same_type_swap_is_still_entry_changed(root, patch):
    swap_after_stat(patch, root / "a.txt", lambda path: path.write_text("new"))
    files, grant = darwin_grant(root)
    try:
        with pytest.raises(UnsafePath) as caught:
            files.open_read(grant, "a.txt")
    finally:
        files.close()
    assert caught.value.code == "entry_changed"


# (5) The Darwin root grant passes through '/'.


def test_the_grant_opens_the_slash_only_to_pass_through(root, patch):
    real_open, seen = os.open, []

    def recording(path, flags, *args, **kwargs):
        if path == "/":
            seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    patch.setattr(os, "open", recording)
    files, _ = darwin_grant(root)
    files.close()
    assert seen == [file_traversal.TRAVERSE_FLAGS]
    assert seen[0] != file_traversal.DIRECTORY_FLAGS


def test_search_only_ancestors_still_work(base):
    top = base / "above" / "inner" / "root"
    top.mkdir(parents=True)
    (top / "f.txt").write_text("found\n")
    for ancestor in (base / "above", base / "above" / "inner"):
        ancestor.chmod(0o111)  # Search (execute) only: no read permission.
    files, grant = darwin_grant(top)
    try:
        listed = files.list_entries(grant, ListRequest("", None, False, 10, 100, 5.0))
        opened = files.open_read(grant, "f.txt")
        data = opened.read(100)
    finally:
        files.close()
    assert [entry.relative_path for entry in listed.entries] == ["f.txt"]
    assert data == b"found\n"
