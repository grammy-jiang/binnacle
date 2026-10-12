"""list_files GLOB mode follows search_text's descriptor-shortage policy.

SRC-W2-04 (glob half, r6 W3 SP1): search_text refuses with
too_many_open_files when the no-follow descriptor walk still meets EMFILE
or ENFILE after DirectoryChain's one retry; glob kept such an entry without
bytes. Glob now refuses the same way, and a shortage that the one retry
clears still sizes the entry.
"""

import errno
import os
import shutil
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import list_files as lf

RG = shutil.which("rg") or "rg"
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path.resolve() / "root"
    (root / "d").mkdir(parents=True)
    (root / "a.txt").write_text("a" * 10)
    (root / "d" / "b.txt").write_text("b" * 20)
    return root


def short_of_descriptors(monkeypatch, name: str, code: int, times: int) -> list:
    """The first `times` no-follow opens of name fail with code."""
    real_open, failures = os.open, [code] * times

    def failing(path, flags, *args, **kwargs):
        if path == name and flags == fd_walk.TRAVERSE_FLAGS and failures:
            failed = failures.pop()
            raise OSError(failed, os.strerror(failed))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", failing)
    return failures


def glob(root: Path) -> dict:
    result = lf._glob_mode(root, "*.txt", 100, False, rg_bin=RG, timeout_s=30)
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.parametrize("code", [errno.EMFILE, errno.ENFILE])
def test_a_persistent_shortage_is_too_many_open_files(root, monkeypatch, code):
    short_of_descriptors(monkeypatch, "d", code, times=2)
    with pytest.raises(ToolError) as exc:
        glob(root)
    assert isinstance(exc.value, CodedToolError)
    assert exc.value.telemetry_code == "too_many_open_files"
    assert str(exc.value) == (
        "list_files could not check the listed files: the server has too many "
        "open files. Retry, or narrow the glob."
    )


def test_a_shortage_the_retry_clears_still_sizes_the_entry(root, monkeypatch):
    failures = short_of_descriptors(monkeypatch, "d", errno.EMFILE, times=1)
    entries = glob(root)["entries"]
    assert failures == []
    assert {Path(e["path"]).name: e["bytes"] for e in entries} == {
        "a.txt": 10,
        "b.txt": 20,
    }


def test_the_refusal_leaks_no_descriptor(root, monkeypatch):
    before = len(os.listdir(FD_DIR))
    for _ in range(5):
        short_of_descriptors(monkeypatch, "d", errno.EMFILE, times=2)
        with pytest.raises(ToolError):
            glob(root)
    monkeypatch.undo()
    assert len(os.listdir(FD_DIR)) <= before
