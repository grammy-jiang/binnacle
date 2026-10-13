"""Only the actual opened private temporary inode may be removed."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_archive_finalize as finalize
from tests.platform.darwin.test_log_archive_finalize import (
    EVENTS,
    NAME,
    fixture,
)


def _temp(root: Path, token: str) -> Path:
    return root / ("." + NAME + "." + token + ".bz2.tmp")


def test_colliding_exclusive_temp_open_preserves_foreign_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, raw, hold = fixture(tmp_path)
    token = "a" * 32
    foreign = _temp(root, token)
    foreign.write_bytes(b"EXISTING FOREIGN CONTENT - DO NOT DELETE")
    foreign.chmod(0o600)
    before = foreign.stat()
    monkeypatch.setattr(
        finalize.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=token),
    )
    with pytest.raises(finalize.ArchiveFinalizeRefused, match="raw retained"):
        finalize.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert foreign.read_bytes() == b"EXISTING FOREIGN CONTENT - DO NOT DELETE"
    assert foreign.stat().st_ino == before.st_ino
    assert raw.read_bytes() == EVENTS
    assert not hold.held


def test_written_temp_is_removed_if_compressor_throws_midstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, raw, hold = fixture(tmp_path)
    before = raw.read_bytes()

    def fail_writer(fd, packed):
        assert packed
        raise OSError("synthetic disk full while compressing")

    monkeypatch.setattr(finalize.stage, "_write_all", fail_writer)
    with pytest.raises(finalize.ArchiveFinalizeRefused, match="raw retained"):
        finalize.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert raw.read_bytes() == before
    assert not list(root.glob(".*.bz2.tmp"))
    assert not hold.held


def test_temporary_name_substitution_is_not_cleaned_or_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, raw, hold = fixture(tmp_path)
    token = "b" * 32
    target = _temp(root, token)
    stranded = root / "stranded-original-temp"
    monkeypatch.setattr(finalize.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    original = finalize.stage._write_all
    swapped = [0]

    def substitute(fd, data):
        original(fd, data)
        if swapped[0] == 0:
            swapped[0] += 1
            target.rename(stranded)
            target.write_bytes(b"NOT THIS TRANSACTION")
            target.chmod(0o600)
            raise OSError("synthetic lost compressor generation")

    monkeypatch.setattr(finalize.stage, "_write_all", substitute)
    with pytest.raises(finalize.ArchiveFinalizeRefused, match="temporary archive"):
        finalize.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert swapped == [1]
    assert target.read_bytes() == b"NOT THIS TRANSACTION"
    assert stranded.is_file()
    assert raw.read_bytes() == EVENTS
    assert not hold.held


def test_temporary_symlink_substitution_does_not_unlink_foreign_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, raw, hold = fixture(tmp_path)
    token = "c" * 32
    target = _temp(root, token)
    foreign = root / "foreign-protected"
    foreign.write_bytes(b"PERMANENT")
    monkeypatch.setattr(finalize.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    original_write = finalize.stage._write_all

    def replace_with_link(fd, data):
        original_write(fd, data)
        target.rename(root / "stranded-temp")
        target.symlink_to(foreign)
        raise OSError("synthetic compressor failure")

    monkeypatch.setattr(finalize.stage, "_write_all", replace_with_link)
    with pytest.raises(finalize.ArchiveFinalizeRefused, match="temporary archive"):
        finalize.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert target.is_symlink()
    assert foreign.read_bytes() == b"PERMANENT"
    assert raw.read_bytes() == EVENTS


def test_normal_fresh_archive_still_removes_own_temporary(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    finished = finalize.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert not raw.exists()
    assert (root / finished.canonical).is_file()
    assert not list(root.glob(".*.bz2.tmp"))


def test_direct_temp_compression_exception_prunes_only_opened_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, raw, _hold = fixture(tmp_path)
    dfd = finalize.stage._safe_directory(root)
    rawfd = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
    try:
        initial = os.fstat(rawfd)

        def refuse_fsync(fd):
            raise OSError("temporary file fsync denied")

        with monkeypatch.context() as m:
            m.setattr(finalize.os, "fsync", refuse_fsync)
            with pytest.raises(OSError, match="fsync denied"):
                finalize._make_temp(dfd, rawfd, ".direct-temp.bz2.tmp", initial)
        assert not (root / ".direct-temp.bz2.tmp").exists()
        assert raw.read_bytes() == EVENTS
    finally:
        os.close(rawfd)
        os.close(dfd)
