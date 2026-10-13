"""read_file polish (r6 W3 RF1): SRC-W2-01, SRC-W2-10, SRC-W2-11 and the shared text.

- SRC-W2-01: a FIFO or socket is refused by the pre-open stat; nothing opens it.
  The verify after the open still refuses a special file that a race brings in.
- SRC-W2-10: the non-Linux path without a file_access adapter reads at most
  max_file_bytes + 1 bytes and never blocks on a FIFO.
- SRC-W2-11: 'bytes' is the count read from the verified descriptor.
- FILES-FOLLOWUP-special-file-text: one actionable text from
  platform/contracts/special_file_contracts.py; read_file says it on the
  Linux path and on the Darwin path (FileToolAccess over DarwinFileAccess).

Every case runs on both OSes; none is skipped.
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
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
)
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

SMALL = ReadFileSettings(max_file_bytes=64)


@pytest.fixture
def root() -> Iterator[Path]:
    # A short /tmp path: an AF_UNIX socket path is limited to 104 bytes on Darwin.
    base = Path(tempfile.mkdtemp(prefix="r6w3-rf1-", dir="/tmp")).resolve()
    try:
        yield base
    finally:
        shutil.rmtree(base)


def in_root(root: Path) -> RootsSettings:
    return RootsSettings(default_root=root, extra_roots=())


def refusal(roots: RootsSettings, path: Path, *, darwin: bool) -> tuple[str, str]:
    """(code, text) of read_file's refusal on the Linux or the Darwin path."""
    access = None
    if darwin:
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="rf1",
            capability=Capability(CapabilityState.LIMITED, "test_only", "rf1"),
        )
    try:
        with pytest.raises(ToolError) as exc:
            rf.read_file_impl(str(path), 1, None, roots=roots, file_access=access)
    finally:
        if access is not None:
            access.close()
    assert isinstance(exc.value, CodedToolError)
    return exc.value.telemetry_code, str(exc.value)


def recorded_opens(monkeypatch) -> list[str]:
    """Every path that os.open or fd_walk.open_walked is asked to open."""
    opened: list[str] = []
    real_open, real_walked = os.open, fd_walk.open_walked

    def counted_open(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, *args, **kwargs)

    def counted_walked(resolved, *args, **kwargs):
        opened.append(os.fspath(resolved))
        return real_walked(resolved, *args, **kwargs)

    monkeypatch.setattr(os, "open", counted_open)
    monkeypatch.setattr(fd_walk, "open_walked", counted_walked)
    return opened


# The shared, actionable text.


def test_the_shared_text_is_actionable():
    assert SPECIAL_FILE_CODE == "special_file_unsupported"
    # The code stays the first word: a matcher of the old text still finds it.
    assert SPECIAL_FILE_TEXT.startswith(f"{SPECIAL_FILE_CODE}: ")
    for words in ("FIFO, socket or device", "not a regular file", "run_command"):
        assert words in SPECIAL_FILE_TEXT
    rendered = rf.special_file_unsupported()
    assert (rendered.telemetry_code, str(rendered)) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


def test_darwin_raises_the_shared_code():
    # The Darwin call site keeps its code; its text moves to the shared
    # constant in wave B, and read_file rewords it until then.
    assert file_traversal.unsafe(SPECIAL_FILE_CODE).code == SPECIAL_FILE_CODE


@pytest.mark.timeout(10)
@pytest.mark.parametrize("darwin", [False, True], ids=["linux_path", "darwin_path"])
def test_a_fifo_says_the_shared_text_on_both_paths(root, darwin):
    os.mkfifo(root / "fifo")
    assert refusal(in_root(root), root / "fifo", darwin=darwin) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


@pytest.mark.parametrize("darwin", [False, True], ids=["linux_path", "darwin_path"])
def test_a_socket_says_the_shared_text_on_both_paths(root, darwin):
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(root / "sock"))
        assert refusal(in_root(root), root / "sock", darwin=darwin) == (
            SPECIAL_FILE_CODE,
            SPECIAL_FILE_TEXT,
        )


# SRC-W2-01: refused by the pre-open stat.


@pytest.mark.timeout(10)
def test_a_fifo_is_refused_before_any_open(root, monkeypatch):
    os.mkfifo(root / "fifo")
    opened = recorded_opens(monkeypatch)
    assert refusal(in_root(root), root / "fifo", darwin=False)[0] == SPECIAL_FILE_CODE
    assert opened == []


def test_a_socket_is_refused_before_any_open(root, monkeypatch):
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(root / "sock"))
        opened = recorded_opens(monkeypatch)
        code, _text = refusal(in_root(root), root / "sock", darwin=False)
    assert code == SPECIAL_FILE_CODE
    assert opened == []


@pytest.mark.timeout(10)
def test_the_verify_after_the_open_still_refuses_a_fifo(root):
    # A race: the read step sees a FIFO with the checked identity. Linux
    # refuses it in fd_walk.open_verified, other OSes in _read_legacy.
    fifo = root / "fifo"
    os.mkfifo(fifo)
    info = os.lstat(fifo)
    with pytest.raises(CodedToolError) as exc:
        rf._read_checked(fifo, (info.st_dev, info.st_ino), in_root(root), SMALL)
    assert (exc.value.telemetry_code, str(exc.value)) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


# SRC-W2-10: the non-Linux path without an adapter.


@pytest.mark.timeout(10)
def test_the_legacy_path_never_blocks_on_a_fifo(root):
    # No writer: a blocking open would wait for one forever.
    fifo = root / "fifo"
    os.mkfifo(fifo)
    info = os.lstat(fifo)
    with pytest.raises(CodedToolError) as exc:
        rf._read_legacy(fifo, (info.st_dev, info.st_ino), SMALL)
    assert exc.value.telemetry_code == SPECIAL_FILE_CODE


def test_the_legacy_path_refuses_another_object(root):
    target = root / "f.txt"
    target.write_text("checked")
    other = os.lstat(root)
    with pytest.raises(CodedToolError) as exc:
        rf._read_legacy(target, (other.st_dev, other.st_ino), SMALL)
    assert exc.value.telemetry_code == "path_changed"
    assert str(exc.value) == (
        f"File changed while it was opened: {target}. Read it again."
    )


def test_the_legacy_path_reads_at_most_the_limit_plus_one(root, monkeypatch):
    target = root / "big.txt"
    target.write_bytes(b"x" * (4 * SMALL.max_file_bytes))
    info = os.lstat(target)
    asked: list[int] = []
    real = os.read

    def counted(fd: int, size: int) -> bytes:
        asked.append(size)
        return real(fd, size)

    monkeypatch.setattr(os, "read", counted)
    with pytest.raises(CodedToolError) as exc:
        rf._read_legacy(target, (info.st_dev, info.st_ino), SMALL)
    assert exc.value.telemetry_code == "file_too_large"
    assert asked and sum(asked) <= SMALL.max_file_bytes + 1


def test_read_file_impl_uses_the_legacy_path_off_linux(root, monkeypatch):
    (root / "f.txt").write_text("plain")
    called: list[Path] = []
    real = rf._read_legacy

    def legacy(resolved, expected, settings):
        called.append(resolved)
        return real(resolved, expected, settings)

    monkeypatch.setattr(rf, "_read_legacy", legacy)
    monkeypatch.setattr(sys, "platform", "darwin")
    payload = rf.read_file_impl(
        str(root / "f.txt"), 1, None, roots=in_root(root)
    ).structured_content
    assert payload is not None and payload["content"] == "plain"
    assert payload["bytes"] == 5
    assert called == [root / "f.txt"]


# SRC-W2-11: 'bytes' comes from the verified descriptor.


def grow_after_the_stat(monkeypatch, target: Path, extra: bytes) -> None:
    """Append extra to target after the stat, before the descriptor is read."""
    real = rf._read_bounded

    def grown(fd: int, settings: ReadFileSettings) -> bytes:
        with target.open("ab") as handle:
            handle.write(extra)
        return real(fd, settings)

    monkeypatch.setattr(rf, "_read_bounded", grown)


def test_text_bytes_are_the_bytes_read(root, monkeypatch):
    target = root / "f.txt"
    target.write_text("one\n")
    grow_after_the_stat(monkeypatch, target, b"two\n")
    payload = rf.read_file_impl(
        str(target), 1, None, roots=in_root(root)
    ).structured_content
    assert payload is not None
    assert payload["content"] == "one\ntwo\n"
    assert payload["bytes"] == 8  # The stat said 4.


def test_binary_bytes_are_the_bytes_read(root, monkeypatch):
    target = root / "blob.bin"
    target.write_bytes(b"\0\1\2")
    grow_after_the_stat(monkeypatch, target, b"\3\4")
    result = rf.read_file_impl(str(target), 1, None, roots=in_root(root))
    payload = result.structured_content
    assert payload is not None and payload["kind"] == "binary"
    assert payload["bytes"] == 5  # The stat said 3.
    assert "Binary file (5 bytes," in str(result.content)


def test_a_regular_file_mode_is_unchanged(root):
    target = root / "f.txt"
    target.write_text("plain")
    assert stat.S_ISREG(os.lstat(target).st_mode)
    payload = rf.read_file_impl(
        str(target), 1, None, roots=in_root(root)
    ).structured_content
    assert payload is not None and payload["bytes"] == 5
