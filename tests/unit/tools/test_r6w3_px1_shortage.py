"""Descriptor shortage and vanished glob entries on both OSes (r6 W3 PX1 4/5).

PF-SP1-1: Darwin mapped EMFILE/ENFILE to file_io_failed; it now raises
too_many_open_files and FileToolAccess words it with the shared template,
the same sentence as Linux list mode. PF-SP1-2: Linux glob kept a listed
file that vanished before its lstat (ENOENT) without bytes; the Darwin walk
omits it; both now omit it. Each case runs the Linux path (file_access=None)
and the Darwin path (FileToolAccess over DarwinFileAccess) on both OSes;
none is skipped.
"""

import errno
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    NativeCapabilityError,
)
from binnacle.platform.contracts.special_file_contracts import (
    SHORTAGE_CODES,
    TOO_MANY_OPEN_FILES_CODE,
    too_many_open_files_text,
)
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

RG = shutil.which("rg") or "rg"
PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)


@pytest.fixture
def root() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1-short-", dir="/tmp")).resolve()
    (base / "d").mkdir()
    for name in ("keep.txt", "gone.txt"):
        (base / "d" / name).write_text("x\n")
    try:
        yield base
    finally:
        shutil.rmtree(base)


def listed(root: Path, darwin: bool, glob: str | None, path: Path):
    roots = RootsSettings(default_root=root, extra_roots=())
    access = None
    if darwin:
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="r6w3-px1",
            capability=Capability(CapabilityState.LIMITED, "test_only", "px1"),
        )
    try:
        return lf.list_files_impl(
            str(path), glob, 100, False, roots=roots, file_access=access, rg_bin=RG
        )
    finally:
        if access is not None:
            access.close()


@pytest.mark.parametrize("number", [errno.EMFILE, errno.ENFILE])
def test_the_darwin_adapter_names_a_shortage(number):
    assert SHORTAGE_CODES[number] == TOO_MANY_OPEN_FILES_CODE
    with pytest.raises(NativeCapabilityError) as exc, file_traversal.native_errors():
        raise OSError(number, os.strerror(number))
    assert exc.value.code == TOO_MANY_OPEN_FILES_CODE


def test_other_errors_stay_file_io_failed():
    with pytest.raises(NativeCapabilityError) as exc, file_traversal.native_errors():
        raise OSError(errno.EIO, os.strerror(errno.EIO))
    assert exc.value.code == "file_io_failed"


@PATHS
def test_a_list_shortage_says_one_sentence(root, darwin, monkeypatch):
    def exhausted(*_args, **_kwargs):
        raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))

    # Linux lists with os.listdir(fd), Darwin with os.scandir(fd); undone
    # before the fixture's rmtree, which needs them.
    with monkeypatch.context() as patch, pytest.raises(ToolError) as exc:
        patch.setattr(os, "listdir", exhausted)
        patch.setattr(os, "scandir", exhausted)
        listed(root, darwin, None, root / "d")
    assert (exc.value.telemetry_code, str(exc.value)) == (
        TOO_MANY_OPEN_FILES_CODE,
        too_many_open_files_text("list_files", f"open {root / 'd'}"),
    )


@PATHS
def test_a_glob_entry_that_vanished_is_omitted(root, darwin, monkeypatch):
    # The file is gone between the listing and its no-follow stat: Linux
    # lstat-s it relative to its directory descriptor, Darwin fstatat-s it.
    real_lstat, real_stat = os.lstat, os.stat

    def gone(stat_call):
        def call(path, *args, **kwargs):
            if os.fspath(path) == "gone.txt" and kwargs.get("dir_fd") is not None:
                raise FileNotFoundError(errno.ENOENT, "vanished", path)
            return stat_call(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "lstat", gone(real_lstat))
    monkeypatch.setattr(os, "stat", gone(real_stat))
    result = listed(root, darwin, "*.txt", root)
    assert [e["path"] for e in result.structured_content["entries"]] == [
        str(root / "d" / "keep.txt")
    ]
