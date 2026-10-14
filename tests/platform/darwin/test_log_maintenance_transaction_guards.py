"""Crash, corruption, inode and unsafe-publication refusals for private journals."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from binnacle.platform.darwin import log_maintenance_transaction as journal
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    begin,
    receipt,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def mutate(root: Path, **changes: object) -> None:
    """Controlled rewrite of a synthetic record with a recomputed checksum."""
    path = root / "transaction.json"
    data = json.loads(path.read_bytes())
    data.update(changes)
    body = {key: value for key, value in data.items() if key != "digest"}
    data["digest"] = hashlib.sha256(journal._canonical(body)).hexdigest()
    path.write_bytes(journal._canonical(data))
    path.chmod(0o600)


def test_valid_foreign_transaction_nonce_cannot_be_adopted(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        # Use a *valid* 32-character nonce and recompute the record digest.
        # The journal must remain bound to its original txn-<nonce> directory.
        mutate(root, nonce="b" * 32)
        with pytest.raises(journal.MaintenanceJournalRefused, match="root nonce"):
            lease.inspect()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"version": 2}, "version"),
        ({"version": True}, "version"),
        ({"nonce": "x" * 32}, "identity"),
        ({"controller_generation": "G" * 32}, "identity"),
        ({"owner_key_digest": 5}, "identity"),
        ({"owner_key_digest": "0" * 31}, "identity"),
        ({"producer_generation": None}, "identity"),
        ({"target": [1]}, "identity"),
        ({"target": "system/com.binnacle.session-observability"}, "identity"),
        ({"owner_pid": 0}, "identity"),
        ({"owner_pid": True}, "identity"),
        ({"producer_pid": "99"}, "identity"),
        ({"source_dev": 0}, "identity"),
        ({"source_ino": -9}, "identity"),
        ({"phase": "unreviewed_stop"}, "phase"),
        ({"phase": None}, "phase"),
        ({"revision": True}, "sequence"),
        ({"revision": 8}, "sequence"),
        ({"receipts": {"j7_locked": "f" * 64}}, "chain"),
        ({"receipts": []}, "chain"),
    ],
)
def test_signed_but_untrusted_record_is_refused(
    root: Path, changes: dict[str, object], reason: str
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        mutate(root, **changes)
        with pytest.raises(journal.MaintenanceJournalRefused, match=reason):
            lease.inspect()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda obj: obj.pop("target"),
        lambda obj: obj.update(extra="hello"),
        lambda obj: obj.update(digest="not-hex"),
        lambda obj: obj.update(digest=5),
        lambda obj: obj.update(digest="0" * 64),
    ],
    ids=["missing", "extra", "bad-hash", "nonstring-hash", "mismatched-hash"],
)
def test_broken_record_schema_or_digest_is_refused(root: Path, mutator) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        p = root / "transaction.json"
        obj = json.loads(p.read_bytes())
        mutator(obj)
        p.write_text(json.dumps(obj))
        p.chmod(0o600)
        with pytest.raises(journal.MaintenanceJournalRefused):
            lease.inspect()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"[",
        b"[]",
        b'{"version":1,"version":2}',
        b"x" * 4100,
    ],
    ids=["empty", "invalid-json", "array", "duplicate-key", "oversized"],
)
def test_torn_malformed_oversized_record_refused(root: Path, data: bytes) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        p = root / "transaction.json"
        p.write_bytes(data)
        p.chmod(0o600)
        with pytest.raises(journal.MaintenanceJournalRefused):
            lease.inspect()


@pytest.mark.parametrize("violation", ["public", "hardlink", "symlink", "directory"])
def test_foreign_record_identity_fails_closed(root: Path, violation: str) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        record = root / "transaction.json"
        if violation == "public":
            record.chmod(0o644)
        elif violation == "hardlink":
            os.link(record, root / "other-link")
        elif violation == "symlink":
            moved = root / "legitimate"
            record.rename(moved)
            record.symlink_to(moved)
        else:
            record.unlink()
            record.mkdir()
        with pytest.raises(journal.MaintenanceJournalRefused):
            lease.inspect()


def test_record_replaced_after_fd_open_is_unverifiable(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        original_read = journal.os.read
        changed = [False]
        p = root / "transaction.json"

        def switch(fd, n):
            data = original_read(fd, n)
            if not changed[0]:
                changed[0] = True
                p.rename(root / "old-journal")
                p.write_bytes(data)
                p.chmod(0o600)
            return data

        with monkeypatch.context() as m:
            m.setattr(journal.os, "read", switch)
            with pytest.raises(journal.MaintenanceJournalRefused, match="changed"):
                lease.inspect()
        assert changed == [True]


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_untrusted_state_root_does_not_create_lock(root: Path, mode: int) -> None:
    root.chmod(mode)
    with (
        pytest.raises(journal.MaintenanceJournalRefused, match="root identity"),
        journal.MaintenanceTransactionJournal(root),
    ):
        pytest.fail("not a private journal state")
    assert not (root / "transaction.lock").exists()


def test_symlinked_root_never_accepted(root: Path) -> None:
    real = root.with_name("saved-txn")
    root.rename(real)
    root.symlink_to(real, target_is_directory=True)
    with (
        pytest.raises(journal.MaintenanceJournalRefused),
        journal.MaintenanceTransactionJournal(root),
    ):
        pytest.fail("symlinked root must be refused")


@pytest.mark.parametrize("name", ["anything", "txn-bad", "txn-" + "Z" * 32])
def test_invalid_root_basename_refuses_without_side_effect(
    tmp_path: Path, name: str
) -> None:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    with (
        pytest.raises(journal.MaintenanceJournalRefused, match="root not canonical"),
        journal.MaintenanceTransactionJournal(root),
    ):
        pytest.fail("untrusted path")
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("violation", ["public", "hardlink", "symlink", "directory"])
def test_untrusted_lock_not_adopted(root: Path, violation: str) -> None:
    lock = root / "transaction.lock"
    if violation == "directory":
        lock.mkdir()
    else:
        original = root / "foreign"
        original.write_bytes(b"previous-owner-lock")
        original.chmod(0o600)
        if violation == "symlink":
            lock.symlink_to(original)
        elif violation == "hardlink":
            os.link(original, lock)
        else:
            lock.write_bytes(b"previous-owner-lock")
            lock.chmod(0o644)
    with (
        pytest.raises(journal.MaintenanceJournalRefused),
        journal.MaintenanceTransactionJournal(root),
    ):
        pytest.fail("foreign lock cannot be held")
    assert lock.exists()


def test_nested_lease_and_path_swap_fail_closed(root: Path) -> None:
    lease = journal.MaintenanceTransactionJournal(root)
    with lease:
        with pytest.raises(journal.MaintenanceJournalRefused, match="already in use"):
            lease.__enter__()
        lock = root / "transaction.lock"
        lock.rename(root / "old-lock")
        lock.write_bytes(b"new lock")
        lock.chmod(0o600)
        with pytest.raises(journal.MaintenanceJournalRefused, match="lock identity"):
            lease.inspect()


def test_root_changed_after_lease_rejects_every_observation(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        root.rename(root.with_name("old-directory"))
        root.mkdir(mode=0o700)
        with pytest.raises(journal.MaintenanceJournalRefused, match="root identity"):
            lease.inspect()


def test_missing_journal_root_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / ("txn-" + NONCE)
    with (
        pytest.raises(journal.MaintenanceJournalRefused, match="unavailable"),
        journal.MaintenanceTransactionJournal(path),
    ):
        pytest.fail("missing state root cannot be auto-created")


def test_file_lock_released_when_transaction_context_exits(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root):
        fd = os.open(root / "transaction.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    with journal.MaintenanceTransactionJournal(root) as new_owner:
        assert new_owner.inspect() is None


def test_controlled_record_advance_rejects_absent_begin(root: Path) -> None:
    with (
        journal.MaintenanceTransactionJournal(root) as lease,
        pytest.raises(journal.MaintenanceJournalRefused, match="no begun"),
    ):
        lease.advance(
            nonce=NONCE,
            expected_revision=0,
            phase="j7_locked",
            receipt_digest=receipt("j7_locked"),
        )


@pytest.mark.parametrize("privilege", ["root", "euid"])
def test_root_or_setuid_controller_cannot_own_a_user_journal(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    privilege: str,
) -> None:
    current = os.getuid()
    with monkeypatch.context() as m:
        if privilege == "root":
            m.setattr(journal.os, "getuid", lambda: 0)
        else:
            m.setattr(journal.os, "geteuid", lambda: current + 1)
        with (
            pytest.raises(journal.MaintenanceJournalRefused, match="unprivileged"),
            journal.MaintenanceTransactionJournal(root),
        ):
            pytest.fail("privileged controller not eligible")
    assert not (root / "transaction.lock").exists()
