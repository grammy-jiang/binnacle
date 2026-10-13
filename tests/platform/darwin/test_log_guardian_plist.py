"""Reject test guardian bootstrap plans that could elevate producer authority.

Pure policy tests run on Linux and Darwin; none invokes launchctl or sudo.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_maintenance_guardian as guardian
from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused
from tests.platform.darwin.test_log_guardian_guards import (
    PLIST,
    _root,
    _trusted_plist,
)


@pytest.mark.parametrize(
    ("field", "new_value"),
    [
        ("ProgramArguments", ["/bin/sh", "-c", "id"]),
        ("UserName", "root"),
        ("GroupName", "wheel"),
        ("StandardErrorPath", "/tmp/foreign.err.log"),
        ("StandardOutPath", "/tmp/foreign.out.log"),
        ("KeepAlive", False),
        ("RunAtLoad", False),
        ("Umask", 0),
        ("ThrottleInterval", 10),
        ("EnvironmentVariables", {"PATH": "/tmp"}),
        ("MachServices", {"org.example": True}),
        ("Program", "/bin/sh"),
        ("WorkingDirectory", "/"),
    ],
)
def test_guardian_rejects_extra_or_retargeted_launchd_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    new_value: object,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root, **{field: new_value})
        with pytest.raises(ArchiveFinalizeRefused, match="plan"):
            guardian._policy(record, root)


def test_guardian_rejects_foreign_log_root_even_when_plist_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        # Use an existing, private but non-fixture directory on both OSes:
        # a Linux host need not have the real macOS Library/Logs tree.
        foreign = tmp_path / "binnacle"
        foreign.mkdir(mode=0o700)
        with pytest.raises(ArchiveFinalizeRefused, match="unsafe"):
            guardian._policy({**record, "log_root": str(foreign)}, root)
        # The exact production path is likewise always refused, whether the
        # directory exists on the host or not.
        with pytest.raises(ArchiveFinalizeRefused):
            guardian._policy(
                {**record, "log_root": str(Path.home() / "Library/Logs/binnacle")},
                root,
            )


@pytest.mark.parametrize("log_root_value", ["", "../private-logs", 42, None])
def test_guardian_rejects_unpinned_log_root_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    log_root_value: object,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        with pytest.raises(ArchiveFinalizeRefused, match="not authenticated"):
            guardian._policy({**record, "log_root": log_root_value}, root)


@pytest.mark.parametrize("violation", ["world_mode", "symlink", "wrong_basename"])
def test_guardian_rejects_log_directory_identity_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        logs = Path(record["log_root"])
        if violation == "world_mode":
            logs.chmod(0o755)
        elif violation == "symlink":
            saved = tmp_path / "original-logs"
            logs.rename(saved)
            logs.symlink_to(saved, target_is_directory=True)
        else:
            logs = tmp_path / "foreign-log-dir"
            logs.mkdir(mode=0o700)
            record = {**record, "log_root": str(logs)}
        try:
            with pytest.raises(ArchiveFinalizeRefused, match="unsafe"):
                guardian._policy(record, root)
        finally:
            if violation == "world_mode":
                logs.chmod(0o700)


def test_guardian_requires_fixture_writer_to_have_user_privileges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        target, _plist = guardian._policy(record, root)
        assert target.startswith("system/com.binnacle.archivefixture.")
        assert os.getuid() != 0  # Native Mac fixtures never run as root.


def test_guardian_policy_refuses_bad_plist_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        good_lstat = Path.lstat

        def bad_owner(p):
            if p == PLIST:
                return SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o644,
                    st_uid=99,
                    st_gid=0,
                    st_nlink=1,
                )
            return good_lstat(p)

        m.setattr(Path, "lstat", bad_owner)
        with pytest.raises(ArchiveFinalizeRefused, match="ownership"):
            guardian._policy(record, root)


@pytest.mark.parametrize("identity", ["root", "uid_mismatch"])
def test_guardian_refuses_privileged_or_setuid_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        actual = os.getuid()
        if identity == "root":
            m.setattr(guardian.os, "getuid", lambda: 0)
        else:
            m.setattr(guardian.os, "geteuid", lambda: actual + 1)
        with pytest.raises(ArchiveFinalizeRefused, match="unprivileged"):
            guardian._policy(record, root)
