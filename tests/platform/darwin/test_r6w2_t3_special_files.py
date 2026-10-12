"""Darwin read_file special files through DarwinFileAccess (r6 W2 T3 item 3).

tests/unit/tools/test_r6w2_x3b3_special_files.py runs the Linux read path
beside the Darwin one on Linux. This module is its native Darwin half: a
FIFO, a unix socket, a character device and a block device are refused by
the production Darwin path (FileToolAccess over DarwinFileAccess) with the
code special_file_unsupported and the shared text Linux uses (SPECIAL_FILE_TEXT).
A mode-000 regular file differs by design: Darwin says
permission_denied_tcc_possible, Linux permission_denied.
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

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import paths
from binnacle.features.files.tools import read_file as rf
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.contracts.special_file_contracts import SPECIAL_FILE_TEXT
from binnacle.platform.darwin.file_access import DarwinFileAccess

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin file access")
CODE = "special_file_unsupported"
LINUX_TEXT = SPECIAL_FILE_TEXT  # r6 W3 RF1: the shared text on both OSes.


@pytest.fixture
def root() -> Iterator[Path]:
    # A short /tmp path: an AF_UNIX socket path is limited to 104 bytes on Darwin.
    base = Path(tempfile.mkdtemp(prefix="r6w2-t3-", dir="/tmp")).resolve()
    try:
        yield base
    finally:
        for entry in base.iterdir():
            if not entry.is_symlink() and stat.S_IMODE(entry.lstat().st_mode) == 0:
                entry.chmod(0o600)
        shutil.rmtree(base)


def in_root(root: Path) -> RootsSettings:
    return RootsSettings(default_root=root, extra_roots=())


def access(roots: RootsSettings) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots,
        files=DarwinFileAccess(),
        search=None,
        generation="t3",
        capability=Capability(CapabilityState.LIMITED, "test_only", "t3"),
    )


def refusal(roots: RootsSettings, path: Path) -> tuple[str, str]:
    """(code, text) of the Darwin read_file refusal."""
    files = access(roots)
    try:
        with pytest.raises(ToolError) as exc:
            rf.read_file_impl(str(path), 1, None, roots=roots, file_access=files)
    finally:
        files.close()
    assert isinstance(exc.value, CodedToolError)
    return exc.value.telemetry_code, str(exc.value)


@NATIVE
@pytest.mark.timeout(10)
def test_a_fifo_is_special_file_unsupported(root):
    os.mkfifo(root / "fifo")
    assert refusal(in_root(root), root / "fifo") == (CODE, LINUX_TEXT)


@NATIVE
@pytest.mark.timeout(10)
def test_an_unreadable_fifo_is_special_file_unsupported(root):
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    os.mkfifo(root / "fifo", 0o000)
    assert refusal(in_root(root), root / "fifo") == (CODE, LINUX_TEXT)


@NATIVE
def test_a_unix_socket_is_special_file_unsupported(root):
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(root / "sock"))
        assert refusal(in_root(root), root / "sock") == (CODE, LINUX_TEXT)


@NATIVE
def test_a_character_device_is_special_file_unsupported():
    # /dev is the root, as on Linux: a device node cannot be created without
    # privilege, so the test reads the host's own /dev/null in place.
    assert stat.S_ISCHR(os.lstat("/dev/null").st_mode)
    roots = RootsSettings(default_root=Path("/dev"), extra_roots=())
    assert refusal(roots, Path("/dev/null")) == (CODE, LINUX_TEXT)


@NATIVE
def test_a_block_device_is_special_file_unsupported():
    # /dev/disk0 is root:operator 0640; nothing is opened for read either way.
    disk = Path("/dev/disk0")
    if not (disk.exists() and stat.S_ISBLK(os.lstat(disk).st_mode)):
        pytest.skip("/dev/disk0 is missing or not a block device (lstat)")
    roots = RootsSettings(default_root=Path("/dev"), extra_roots=())
    assert refusal(roots, disk) == (CODE, LINUX_TEXT)


@NATIVE
def test_a_mode_000_regular_file_is_permission_denied_tcc_possible(root):
    # By design: Linux says permission_denied; Darwin adds the TCC hint.
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    secret = root / "secret.txt"
    secret.write_text("hidden")
    secret.chmod(0o000)
    code, text = refusal(in_root(root), secret)
    assert code == "permission_denied_tcc_possible"
    assert "hidden" not in text


@NATIVE
def test_a_regular_file_still_reads(root):
    (root / "f.txt").write_text("plain")
    roots = in_root(root)
    files = access(roots)
    try:
        payload = rf.read_file_impl(
            str(root / "f.txt"), 1, None, roots=roots, file_access=files
        ).structured_content
    finally:
        files.close()
    assert payload is not None and payload["content"] == "plain"
