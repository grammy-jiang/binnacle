"""FDW-8: fail closed on Linux per-entry metadata I/O and FD shortages.

Tests isolate one allowed temporary root and inject the error specifically
into a descriptor-relative no-follow metadata read. No production files.
"""

import errno
import os

import pytest

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import list_files_glob
from binnacle.features.files.tools import list_files as listing

ERRORS = (errno.EIO, errno.EINVAL, errno.EMFILE, errno.ENFILE)
OMIT = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EACCES, errno.EPERM)


@pytest.fixture
def root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "victim.txt").write_text("owned")
    return allowed


def fail_lstat_only_for_held_entry(monkeypatch, name, code):
    original = os.lstat
    observed = []

    def failing(path, *args, **kwargs):
        if path == name and isinstance(kwargs.get("dir_fd"), int):
            observed.append((path, kwargs.get("dir_fd")))
            raise OSError(code, os.strerror(code))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", failing)
    return observed


@pytest.mark.parametrize("code", ERRORS)
def test_list_mode_fails_explicitly_on_unexpected_lstat(root, monkeypatch, code):
    observed = fail_lstat_only_for_held_entry(monkeypatch, "victim.txt", code)
    config = RootsSettings(default_root=root, extra_roots=())
    with pytest.raises(CodedToolError) as exc:
        listing.list_files_impl(str(root), None, 100, False, roots=config)
    expected = (
        "too_many_open_files"
        if code in (errno.EMFILE, errno.ENFILE)
        else "file_io_failed"
    )
    assert exc.value.telemetry_code == expected
    assert observed
    assert all(isinstance(fd, int) for _, fd in observed)


@pytest.mark.parametrize("code", OMIT)
def test_list_mode_omits_only_known_nonfatal_lstat_errors(root, monkeypatch, code):
    observed = fail_lstat_only_for_held_entry(monkeypatch, "victim.txt", code)
    config = RootsSettings(default_root=root, extra_roots=())
    result = listing.list_files_impl(str(root), None, 100, False, roots=config)
    assert result.structured_content["count"] == 0
    assert result.structured_content["entries"] == []
    assert observed


@pytest.mark.parametrize("code", ERRORS)
def test_glob_mode_fails_explicitly_on_unexpected_lstat(root, monkeypatch, code):
    observed = fail_lstat_only_for_held_entry(monkeypatch, "victim.txt", code)
    with pytest.raises(CodedToolError) as exc:
        list_files_glob.glob_entries(root, ["victim.txt"])
    expected = (
        "too_many_open_files"
        if code in (errno.EMFILE, errno.ENFILE)
        else "file_io_failed"
    )
    assert exc.value.telemetry_code == expected
    assert observed


@pytest.mark.parametrize("code", OMIT)
def test_glob_mode_omits_only_known_nonfatal_lstat_errors(root, monkeypatch, code):
    observed = fail_lstat_only_for_held_entry(monkeypatch, "victim.txt", code)
    assert list_files_glob.glob_entries(root, ["victim.txt"]) == []
    assert observed


@pytest.mark.parametrize("mode", ["list", "glob"])
def test_later_io_error_aborts_entire_partial_result_without_fd_leak(
    tmp_path, monkeypatch, mode
):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "good.txt").write_bytes(b"healthy")
    (root / "victim.txt").write_bytes(b"fault")
    config = RootsSettings(default_root=root, extra_roots=())
    fd_dir = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
    before = len(os.listdir(fd_dir))
    real_listdir = os.listdir
    real_lstat = os.lstat
    visited = []

    def deterministic_names(path):
        if isinstance(path, int):
            return ["good.txt", "victim.txt"]
        return real_listdir(path)

    def fault_second(path, *args, **kwargs):
        if path in ("good.txt", "victim.txt") and isinstance(kwargs.get("dir_fd"), int):
            visited.append(path)
            if path == "victim.txt":
                raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_lstat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", fault_second)
        if mode == "list":
            patch.setattr(os, "listdir", deterministic_names)
        with pytest.raises(CodedToolError) as exc:
            if mode == "glob":
                list_files_glob.glob_entries(root, ["good.txt", "victim.txt"])
            else:
                listing.list_files_impl(str(root), None, 100, False, roots=config)
    assert visited == ["good.txt", "victim.txt"]
    assert exc.value.telemetry_code == "file_io_failed"
    assert len(os.listdir(fd_dir)) <= before
