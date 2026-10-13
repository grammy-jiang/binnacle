"""Crash and malformed write probes for the dormant test-only guardian."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_maintenance_guardian as guardian
from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused
from tests.platform.darwin.test_log_guardian_guards import _record, _root


def test_old_pid_named_temp_does_not_block_new_journal_publication(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    stale = root / f".guardian-{os.getpid()}.tmp"
    stale.write_bytes(b"partial recording from old incarnation")
    stale.chmod(0o600)
    journal = root / "journal.json"
    current = _record(root)
    guardian._write_record(journal, current)
    assert guardian._read_verified(journal) == current
    assert stale.read_bytes() == b"partial recording from old incarnation"
    assert list(root.glob(".guardian-*.tmp")) == [stale]


@pytest.mark.parametrize("failure", ["write_error", "zero_write", "fsync", "publish"])
def test_journal_write_failure_never_damages_previous_or_leaks_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = _root(tmp_path)
    journal = root / "journal.json"
    prior = _record(root)
    guardian._write_record(journal, prior)
    previous = journal.read_bytes()
    before_tmp = sorted(root.glob(".guardian-*.tmp"))
    newer = {**prior, "state": "recovered", "restored_pid": 456}

    if failure in ("write_error", "zero_write"):
        monkeypatch.setattr(
            guardian.os,
            "write",
            lambda fd, data: (
                (_ for _ in ()).throw(OSError("simulated disk failure"))
                if failure == "write_error"
                else 0
            ),
        )
    elif failure == "fsync":
        monkeypatch.setattr(
            guardian.os,
            "fsync",
            lambda fd: (_ for _ in ()).throw(OSError("simulated sync failure")),
        )
    else:
        monkeypatch.setattr(
            guardian.os,
            "replace",
            lambda old, new: (_ for _ in ()).throw(PermissionError("publish refused")),
        )
    with pytest.raises((OSError, ArchiveFinalizeRefused)):
        guardian._write_record(journal, newer)
    assert journal.read_bytes() == previous
    assert sorted(root.glob(".guardian-*.tmp")) == before_tmp


def test_existing_foreign_temp_on_uuid_collision_must_not_be_unlinked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    token = "a" * 32
    monkeypatch.setattr(guardian.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    occupied = root / f".guardian-{token}.tmp"
    occupied.write_bytes(b"not-ours")
    occupied.chmod(0o600)
    with pytest.raises(FileExistsError):
        guardian._write_record(root / "journal.json", _record(root))
    assert occupied.read_bytes() == b"not-ours"
    assert not (root / "journal.json").exists()


def test_foreign_symlink_is_not_followed_or_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    token = "b" * 32
    monkeypatch.setattr(guardian.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    target = root / "protected"
    target.write_bytes(b"protected")
    symlink = root / f".guardian-{token}.tmp"
    symlink.symlink_to(target)
    with pytest.raises(FileExistsError):
        guardian._write_record(root / "journal.json", _record(root))
    assert symlink.is_symlink()
    assert target.read_bytes() == b"protected"


def test_short_os_writes_are_retried_until_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    actual = os.write
    count = [0]

    def short_write(fd: int, data: bytes) -> int:
        count[0] += 1
        return actual(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(guardian.os, "write", short_write)
    record = _record(root)
    guardian._write_record(root / "journal.json", record)
    assert guardian._read_verified(root / "journal.json") == record
    assert count[0] > 1


def test_ready_publication_error_keeps_old_verified_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    nonce = "c" * 32
    guardian._ready(root, nonce)
    receipt = root / f"ready-{nonce}"
    before = receipt.read_bytes()
    before_tmp = sorted(root.glob(".ready-*.tmp"))
    monkeypatch.setattr(
        guardian.os,
        "replace",
        lambda old, new: (_ for _ in ()).throw(OSError("synthetic rename error")),
    )
    with pytest.raises(OSError):
        guardian._ready(root, nonce)
    assert receipt.read_bytes() == before
    assert sorted(root.glob(".ready-*.tmp")) == before_tmp
