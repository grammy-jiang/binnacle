"""PX1B-F3: legacy Linux edit/write refusals carry stable telemetry codes.

Tests use temporary allowed roots and inject I/O errors without touching
production files. Error text must remain byte-for-byte unchanged.
"""

import errno
import os

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files.tools import edit_file, write_file


@pytest.fixture
def roots(tmp_path):
    return RootsSettings(default_root=tmp_path, extra_roots=())


def assert_refusal(call, code, expected):
    with pytest.raises(ToolError) as exc:
        call()
    assert getattr(exc.value, "telemetry_code", None) == code
    assert str(exc.value) == expected


def test_missing_edit_target_has_file_not_found_code(roots, tmp_path):
    missing = tmp_path / "missing.txt"
    assert_refusal(
        lambda: edit_file.edit_file_impl(
            str(missing), "old", "new", False, roots=roots
        ),
        "file_not_found",
        (
            f"File not found: {missing}."
            f" Directory {tmp_path} is empty. To create a new file, use write_file."
        ),
    )


@pytest.mark.parametrize("host", ["linux", "darwin"])
def test_write_io_error_retains_text_and_gains_code(roots, tmp_path, monkeypatch, host):
    target = tmp_path / "new.txt"
    monkeypatch.setattr(write_file.sys, "platform", host)

    def broken(*args, **kwargs):
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    if host == "linux":
        monkeypatch.setattr(write_file.fd_write, "write_bytes", broken)
    else:
        monkeypatch.setattr(type(target), "write_bytes", broken)
    assert_refusal(
        lambda: write_file.write_file_impl(str(target), "data", roots=roots),
        "write_failed",
        f"Could not write {target}: {os.strerror(errno.EIO)}.",
    )
    assert not target.exists()


def test_edit_read_io_error_has_code_without_writing(roots, tmp_path, monkeypatch):
    target = tmp_path / "source.txt"
    target.write_text("old")
    monkeypatch.setattr(edit_file.sys, "platform", "linux")

    def broken(*args, **kwargs):
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(edit_file.fd_write, "read_for_edit", broken)
    assert_refusal(
        lambda: edit_file.edit_file_impl(str(target), "old", "new", False, roots=roots),
        "file_io_failed",
        f"Could not read {target}: {os.strerror(errno.EIO)}.",
    )
    assert target.read_text() == "old"


def test_edit_write_io_error_has_code_without_overwrite(roots, tmp_path, monkeypatch):
    target = tmp_path / "source.txt"
    target.write_text("old")
    monkeypatch.setattr(edit_file.sys, "platform", "linux")

    def broken(*args, **kwargs):
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    # The error-under-test is the write stage, so isolate the earlier read
    # from the host's Linux-only FD traversal while still using a real file.
    info = target.stat()
    monkeypatch.setattr(
        edit_file.fd_write,
        "read_for_edit",
        lambda *_args, **_kwargs: (b"old", (info.st_dev, info.st_ino)),
    )
    monkeypatch.setattr(edit_file.fd_write, "write_bytes", broken)
    assert_refusal(
        lambda: edit_file.edit_file_impl(str(target), "old", "new", False, roots=roots),
        "write_failed",
        f"Could not write {target}: {os.strerror(errno.EIO)}.",
    )
    assert target.read_text() == "old"
