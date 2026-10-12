"""read_file special files: Linux words them as Darwin does (r6 W2 X3b-a3).

A FIFO, a socket and a character or block device are refused on Linux with
Darwin's code special_file_unsupported and its exact text. Each case runs
the same object through both production paths on this host: the Linux path
(read_file_impl without file_access, over fd_walk.open_walked) and the Darwin
path (FileToolAccess over DarwinFileAccess, which raises
file_traversal.unsafe("special_file_unsupported") and is worded by
FileToolAccess.operation). Code and text must be equal. A mode-000 regular
file differs by design: Darwin's permission_denied_tcc_possible carries a
macOS TCC hint that does not apply on Linux.
"""

import os
import shutil
import socket
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import ReadFileSettings, RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk, paths
from binnacle.features.files.tools import read_file as rf
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.contracts.special_file_contracts import SPECIAL_FILE_TEXT
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores modes")
# Linux-only mechanism: these cases run the Linux read path (fd_walk) beside
# the Darwin one; the native Darwin cases are test_r6w2_t3_special_files.py.
LINUX_READ = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux read path (fd_walk.open_walked)"
)
CODE = "special_file_unsupported"
TEXT = SPECIAL_FILE_TEXT  # r6 W3 RF1: the shared, actionable text.


@pytest.fixture
def root() -> Iterator[Path]:
    # A short /tmp path: an AF_UNIX socket path is limited to 108 bytes.
    base = Path(tempfile.mkdtemp(prefix="r6w2-x3b3-", dir="/tmp")).resolve()
    try:
        yield base
    finally:
        for entry in base.iterdir():
            if not entry.is_symlink() and stat.S_IMODE(entry.lstat().st_mode) == 0:
                entry.chmod(0o600)
        shutil.rmtree(base)


def refusal(roots: RootsSettings, path: Path, *, darwin: bool) -> tuple[str, str]:
    """(code, text) of the refusal on the Linux or the Darwin read path."""
    access = None
    if darwin:
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="x3b3",
            capability=Capability(CapabilityState.LIMITED, "test_only", "x3b3"),
        )
    try:
        with pytest.raises(ToolError) as exc:
            rf.read_file_impl(str(path), 1, None, roots=roots, file_access=access)
    finally:
        if access is not None:
            access.close()
    assert isinstance(exc.value, CodedToolError)
    return exc.value.telemetry_code, str(exc.value)


def both(roots: RootsSettings, path: Path) -> tuple[str, str]:
    linux = refusal(roots, path, darwin=False)
    assert linux == refusal(roots, path, darwin=True)
    return linux


def in_root(root: Path) -> RootsSettings:
    return RootsSettings(default_root=root, extra_roots=())


def test_the_helper_equals_the_darwin_rendering():
    # Darwin raises the same code; read_file words it with the shared text
    # on both OSes (r6 W3 RF1) until the Darwin call site uses it (wave B).
    darwin = file_traversal.unsafe(CODE)
    assert darwin.code == CODE
    rendered = rf.special_file_unsupported()
    assert rendered.telemetry_code == darwin.code
    assert str(rendered) == TEXT


@LINUX_READ
@pytest.mark.timeout(10)
def test_a_fifo_is_refused_as_on_darwin(root):
    os.mkfifo(root / "fifo")
    assert both(in_root(root), root / "fifo") == (CODE, TEXT)


@LINUX_READ
@not_root
@pytest.mark.timeout(10)
def test_an_unreadable_fifo_is_refused_as_on_darwin(root):
    # The open fails with EACCES; the entry is still the checked FIFO.
    os.mkfifo(root / "fifo", 0o000)
    assert both(in_root(root), root / "fifo") == (CODE, TEXT)


@LINUX_READ
def test_a_socket_is_refused_as_on_darwin(root):
    # open(2) of a socket is ENXIO; r6 W2 X3b-a2 said file_io_failed.
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(root / "sock"))
        assert both(in_root(root), root / "sock") == (CODE, TEXT)


@LINUX_READ
def test_a_character_device_is_refused_as_on_darwin():
    # /dev is the root because a device node cannot be created without
    # privilege, so the test reads the host's own /dev/null in place.
    if not (
        os.path.exists("/dev/null") and stat.S_ISCHR(os.lstat("/dev/null").st_mode)
    ):
        pytest.skip(
            "/dev/null is missing or not a character device (lstat); /dev is the"
            " root because a device node cannot be created without privilege"
        )
    roots = RootsSettings(default_root=Path("/dev"), extra_roots=())
    assert both(roots, Path("/dev/null")) == (CODE, TEXT)


@LINUX_READ
def test_a_block_device_is_refused_as_on_darwin():
    # Without the disk group the open is EACCES; nothing is read either way.
    candidates = ("loop0", "mmcblk0", "nvme0n1", "sda", "vda")
    found = [
        Path("/dev", n)
        for n in candidates
        if os.path.exists(f"/dev/{n}") and stat.S_ISBLK(os.lstat(f"/dev/{n}").st_mode)
    ]
    if not found:
        pytest.skip(
            "none of /dev/loop0, /dev/mmcblk0, /dev/nvme0n1, /dev/sda, /dev/vda"
            " exists as a block device (lstat); /dev is the root because a"
            " device node cannot be created without privilege"
        )
    roots = RootsSettings(default_root=Path("/dev"), extra_roots=())
    assert both(roots, found[0]) == (CODE, TEXT)


@LINUX_READ
@not_root
def test_a_mode_000_regular_file_differs_by_design(root):
    # Darwin adds a macOS TCC hint (permission_denied_tcc_possible); Linux
    # keeps permission_denied with its own text.
    secret = root / "secret.txt"
    secret.write_text("hidden")
    secret.chmod(0o000)
    roots = in_root(root)
    code, text = refusal(roots, secret, darwin=False)
    assert code == "permission_denied"
    assert text.startswith(f"Permission denied: {secret}.")
    assert refusal(roots, secret, darwin=True)[0] == "permission_denied_tcc_possible"


def test_a_regular_file_still_reads(root):
    (root / "f.txt").write_text("plain")
    payload = rf.read_file_impl(
        str(root / "f.txt"), 1, None, roots=in_root(root)
    ).structured_content
    assert payload is not None and payload["content"] == "plain"


@LINUX_READ
def test_a_socket_swapped_in_keeps_the_identity_refusal(root, monkeypatch):
    # Identity first: the open fails (ENXIO) on an object that is not the
    # checked file, so the special-file wording does not apply.
    target = root / "f.txt"
    target.write_text("checked")
    real = fd_walk.open_walked
    server = socket.socket(socket.AF_UNIX)

    def swapped(*args, **kwargs) -> int:
        target.rename(root / "kept.txt")  # Keep the inode: no number reuse.
        server.bind(str(target))
        return real(*args, **kwargs)

    monkeypatch.setattr(fd_walk, "open_walked", swapped)
    with server:
        code, _text = refusal(in_root(root), target, darwin=False)
    assert code == "file_io_failed"


@LINUX_READ
@pytest.mark.parametrize("code", ["path_changed", "path_outside_root"])
def test_path_refusals_on_the_checked_fifo_are_never_reworded(root, monkeypatch, code):
    # RX3b3-F2: the lstat shows the unchanged checked FIFO, so only the code
    # decides; path_changed and path_outside_root keep their code and text.
    # read_file_impl refuses a FIFO by its pre-open stat (r6 W3 RF1,
    # SRC-W2-01), so the race step is called directly.
    fifo = root / "fifo"
    os.mkfifo(fifo)
    before = os.lstat(fifo)
    assert stat.S_ISFIFO(before.st_mode)
    original = CodedToolError(code, f"{code} from the stub: {fifo}")
    seen: list[tuple[int, int]] = []

    def refuse(_resolved, _allowed, expected) -> int:
        seen.append(expected)
        raise original

    monkeypatch.setattr(fd_walk, "open_walked", refuse)
    with pytest.raises(CodedToolError) as exc:
        rf._read_checked(
            fifo, (before.st_dev, before.st_ino), in_root(root), ReadFileSettings()
        )
    after = os.lstat(fifo)
    assert seen == [(before.st_dev, before.st_ino)]
    assert (after.st_dev, after.st_ino) == seen[0] and stat.S_ISFIFO(after.st_mode)
    assert exc.value.telemetry_code == code
    assert str(exc.value) == f"{code} from the stub: {fifo}"


# RX3b2-F1: read(2) is asked for at most READ_MAX_FILE_BYTES + 1 bytes.


def recorded_reads(monkeypatch) -> list[tuple[int, int]]:
    """Every (fd, size) that os.read is asked for."""
    asked: list[tuple[int, int]] = []
    real = os.read

    def counted(fd: int, size: int) -> bytes:
        asked.append((fd, size))
        return real(fd, size)

    monkeypatch.setattr(os, "read", counted)
    return asked


@LINUX_READ
def test_a_grown_file_asks_for_at_most_the_limit_plus_one(root, monkeypatch):
    limit = ReadFileSettings().max_file_bytes  # READ_MAX_FILE_BYTES
    target = root / "grows.txt"
    target.write_text("small")
    real = fd_walk.open_walked

    def grow(*args, **kwargs) -> int:
        os.truncate(target, 4 * limit)  # Sparse: grows past the limit cheaply.
        return real(*args, **kwargs)

    monkeypatch.setattr(fd_walk, "open_walked", grow)
    asked = recorded_reads(monkeypatch)
    with pytest.raises(CodedToolError) as exc:
        rf.read_file_impl(
            str(target), 1, None, roots=in_root(root), settings=ReadFileSettings()
        )
    assert exc.value.telemetry_code == "file_too_large"
    assert asked and sum(size for _fd, size in asked) <= limit + 1
    assert asked[0][1] == limit + 1


@LINUX_READ
def test_a_small_file_reads_until_end_of_file(root, monkeypatch):
    (root / "f.txt").write_text("plain")
    asked = recorded_reads(monkeypatch)
    payload = rf.read_file_impl(
        str(root / "f.txt"), 1, None, roots=in_root(root), settings=ReadFileSettings()
    ).structured_content
    assert payload is not None and payload["content"] == "plain"
    limit = ReadFileSettings().max_file_bytes
    # One read returns the 5 bytes, the next sees end of file.
    assert [size for _fd, size in asked] == [limit + 1, limit + 1 - 5]
