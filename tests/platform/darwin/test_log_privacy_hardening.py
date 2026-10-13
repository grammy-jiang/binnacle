"""User-only log privacy: refuse symlinks, foreign owners and unsafe inodes."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from binnacle.companions.darwin_log_privacy import harden_private_logs


def private_root(tmp_path):
    root = tmp_path / "logs"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def test_hardens_only_user_owned_regular_logs_without_removing_bytes(tmp_path):
    root = private_root(tmp_path)
    a = root / "mcp.stderr.log"
    b = root / "jobs.stderr.log"
    c = root / "notes.txt"
    a.write_bytes(b"first\n")
    b.write_bytes(b"second\n")
    c.write_bytes(b"not a log")
    a.chmod(0o644)
    b.chmod(0o600)
    c.chmod(0o644)
    before = a.stat()
    assert harden_private_logs(root) == ("mcp.stderr.log",)
    after = a.stat()
    assert before.st_ino == after.st_ino
    assert a.read_bytes() == b"first\n"
    assert stat.S_IMODE(after.st_mode) == 0o600
    assert stat.S_IMODE(b.stat().st_mode) == 0o600
    assert stat.S_IMODE(c.stat().st_mode) == 0o644
    assert harden_private_logs(root) == ()


def test_symlink_in_log_dir_aborts_before_any_chmod(tmp_path):
    root = private_root(tmp_path)
    a = root / "aa.log"
    a.write_bytes(b"a")
    a.chmod(0o644)
    (root / "bad.log").symlink_to(a)
    with pytest.raises(RuntimeError):
        harden_private_logs(root)
    assert stat.S_IMODE(a.stat().st_mode) == 0o644


def test_hardlink_refused_before_any_chmod(tmp_path):
    root = private_root(tmp_path)
    a = root / "aa.log"
    a.write_bytes(b"a")
    a.chmod(0o644)
    os.link(a, root / "bb.log")
    with pytest.raises(RuntimeError, match="unsafe"):
        harden_private_logs(root)
    assert stat.S_IMODE(a.stat().st_mode) == 0o644


def test_symlinked_root_refused(tmp_path):
    root = private_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    with pytest.raises(RuntimeError):
        harden_private_logs(alias)


def test_root_must_be_private(tmp_path):
    root = private_root(tmp_path)
    root.chmod(0o755)
    with pytest.raises(RuntimeError, match="unsafe"):
        harden_private_logs(root)


def test_nonexistent_root_refused(tmp_path):
    with pytest.raises(RuntimeError, match="unavailable"):
        harden_private_logs(tmp_path / "missing")


def test_wrong_user_root_and_file_refused(tmp_path, monkeypatch):
    root = private_root(tmp_path)
    (root / "foo.log").write_bytes(b"data")
    monkeypatch.setattr(os, "getuid", lambda: -12345)
    with pytest.raises(RuntimeError, match="unsafe"):
        harden_private_logs(root)


def test_wrong_owner_file_refused(tmp_path, monkeypatch):
    root = private_root(tmp_path)
    (root / "foo.log").write_bytes(b"data")
    original_fstat = os.fstat
    calls = []

    def wrong_file(fd):
        st = original_fstat(fd)
        calls.append(st)
        if len(calls) >= 2:
            return os.stat_result(tuple(st[:4]) + (st.st_uid + 99,) + tuple(st[5:]))
        return st

    # Emulate a foreign inode using a real root-owned descriptor stat shape.
    monkeypatch.setattr(os, "fstat", wrong_file)
    with pytest.raises((RuntimeError, TypeError)):
        harden_private_logs(root)


def test_too_many_matches_aborts_without_changes(tmp_path):
    root = private_root(tmp_path)
    for i in range(2):
        path = root / f"log{i}.log"
        path.write_text("content")
        path.chmod(0o644)
    with pytest.raises(RuntimeError, match="too many"):
        harden_private_logs(root, max_files=1)
    with pytest.raises(RuntimeError, match="too many"):
        harden_private_logs(root, max_files=0)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o644 for p in root.iterdir())


def test_open_file_descriptor_remains_usable_and_log_writes_continue(tmp_path):
    root = private_root(tmp_path)
    log = root / "stdout.log"
    log.write_bytes(b"head\n")
    log.chmod(0o644)
    fd = os.open(log, os.O_WRONLY | os.O_APPEND)
    try:
        assert harden_private_logs(root) == ("stdout.log",)
        os.write(fd, b"tail\n")
    finally:
        os.close(fd)
    assert log.read_bytes() == b"head\ntail\n"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_log_growth_read_only_and_guarded(tmp_path):
    from binnacle.companions.darwin_log_privacy import logs_nearing_rotation

    root = private_root(tmp_path)
    (root / "large.log").write_bytes(b"x" * 10)
    (root / "small.log").write_bytes(b"y" * 2)
    assert logs_nearing_rotation(root, warn_bytes=5) == (("large.log", 10),)
    assert logs_nearing_rotation(root, warn_bytes=99) == ()
    with pytest.raises(ValueError):
        logs_nearing_rotation(root, warn_bytes=0)
    (root / "bad.log").symlink_to(root / "small.log")
    with pytest.raises(RuntimeError):
        logs_nearing_rotation(root)


def test_log_growth_nonexistent_or_foreign_root_refused(tmp_path, monkeypatch):
    from binnacle.companions.darwin_log_privacy import logs_nearing_rotation

    with pytest.raises(RuntimeError, match="unavailable"):
        logs_nearing_rotation(tmp_path / "nonexistent")
    root = private_root(tmp_path)
    monkeypatch.setattr(os, "getuid", lambda: -10000)
    with pytest.raises(RuntimeError, match="unsafe"):
        logs_nearing_rotation(root)


def test_retention_policy_matches_long_lived_mac_ssd():
    from binnacle.companions.darwin_log_privacy import (
        ARCHIVE_COUNT,
        MIN_DISK_FREE_BYTES,
        ROTATION_SIZE_KIB,
        ROTATION_WARNING_BYTES,
        render_newsyslog_rule,
    )

    root = Path("/Users/auser")
    text = render_newsyslog_rule(root, user="auser")
    assert text == (
        "/Users/auser/Library/Logs/binnacle/*.log auser:staff 600 7 10485760 * GNJ"
    )
    assert ARCHIVE_COUNT == 7
    assert ROTATION_SIZE_KIB * 1024 == 10 * 1024**3
    assert ROTATION_WARNING_BYTES == 8 * 1024**3
    assert ROTATION_WARNING_BYTES < ROTATION_SIZE_KIB * 1024
    assert MIN_DISK_FREE_BYTES == 100 * 1024**3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"home": Path("relative"), "user": "auser"},
        {"home": Path("/Users/space in name"), "user": "auser"},
        {"home": Path("/Users/auser"), "user": "bad:name"},
        {"home": Path("/Users/auser"), "user": ""},
        {"home": Path("/Users/auser"), "user": "auser", "group": "staff;rm"},
        {"home": Path("/Users/auser"), "user": "auser", "archives": 0},
        {"home": Path("/Users/auser"), "user": "auser", "size_kib": 0},
        {"home": Path("/Users/auser"), "user": "auser", "size_kib": 100 * 1024**2 + 1},
    ],
)
def test_retention_renderer_rejects_unsafe_inputs(kwargs):
    from binnacle.companions.darwin_log_privacy import render_newsyslog_rule

    with pytest.raises(ValueError, match="unsafe"):
        render_newsyslog_rule(**kwargs)


def test_default_warning_matches_new_policy_without_allocating_gigabytes(tmp_path):
    from binnacle.companions import darwin_log_privacy as privacy

    root = private_root(tmp_path)
    log = root / "mcp.stderr.log"
    log.write_text("x")
    assert privacy.logs_nearing_rotation(root) == ()
    with pytest.MonkeyPatch.context() as mp:
        # Stub filesystem size only; opening & reading remain real and safe.
        actual_stat = privacy.os.stat

        def near_limit(path, **kwargs):
            observed = actual_stat(path, **kwargs)
            if path == "mcp.stderr.log":
                return os.stat_result(
                    (
                        observed.st_mode,
                        observed.st_ino,
                        observed.st_dev,
                        observed.st_nlink,
                        observed.st_uid,
                        observed.st_gid,
                        privacy.ROTATION_WARNING_BYTES + 1,
                        observed.st_atime,
                        observed.st_mtime,
                        observed.st_ctime,
                    )
                )
            return observed

        mp.setattr(privacy.os, "stat", near_limit)
        assert privacy.logs_nearing_rotation(root) == (
            ("mcp.stderr.log", privacy.ROTATION_WARNING_BYTES + 1),
        )
