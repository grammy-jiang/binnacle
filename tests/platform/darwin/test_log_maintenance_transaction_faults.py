"""I/O failure and interrupted publication of a test-owned controller journal."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.platform.darwin import log_maintenance_transaction as journal
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    begin,
    receipt,
)
from tests.platform.darwin.test_log_maintenance_transaction_guards import mutate


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_invalid_receipt_contents_cannot_pass_even_with_matching_checksum(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        lease.advance(
            nonce=NONCE,
            expected_revision=0,
            phase="j7_locked",
            receipt_digest=receipt("j7_locked"),
        )
        mutate(root, receipts={"j7_locked": "G" * 64})
        with pytest.raises(journal.MaintenanceJournalRefused, match="digest invalid"):
            lease.inspect()


def test_missing_record_read_permission_is_indeterminate(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        real_open = journal.os.open

        def deny(path, flags, *args, **kw):
            if path == "transaction.json":
                raise PermissionError("synthetic file access denied")
            return real_open(path, flags, *args, **kw)

        with monkeypatch.context() as m:
            m.setattr(journal.os, "open", deny)
            with pytest.raises(journal.MaintenanceJournalRefused, match="inaccessible"):
                lease.inspect()


def test_short_read_is_not_a_valid_snapshot(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        real = journal.os.read
        read_once = [False]

        def short(fd, n):
            data = real(fd, n)
            if not read_once[0]:
                read_once[0] = True
                return data[:-1]
            return data

        with monkeypatch.context() as m:
            m.setattr(journal.os, "read", short)
            with pytest.raises(journal.MaintenanceJournalRefused, match="changed"):
                lease.inspect()
        assert read_once == [True]


def test_unexpected_os_error_during_read_is_typed_refusal(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)

        def interrupted(fd, limit):
            raise OSError("synthetic journal read error")

        with monkeypatch.context() as m:
            m.setattr(journal.os, "read", interrupted)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="read incomplete"
            ):
                lease.inspect()


def test_oversized_private_record_refused_before_creating_temp(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        with pytest.raises(journal.MaintenanceJournalRefused, match="too large"):
            lease._publish({"huge": "z" * 5000}, new=True)
        assert not (root / "transaction.json").exists()
        assert not list(root.glob(".*.tmp"))


def test_exclusive_temp_collision_preserves_preexisting_file(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = root / ("." + "d" * 32 + ".tmp")
    foreign.write_bytes(b"PRIVATE FOREIGN DATA")
    foreign.chmod(0o600)
    inode = foreign.stat().st_ino
    monkeypatch.setattr(journal.uuid, "uuid4", lambda: SimpleNamespace(hex="d" * 32))
    with journal.MaintenanceTransactionJournal(root) as lease:
        with pytest.raises(
            journal.MaintenanceJournalRefused, match="publication incomplete"
        ):
            begin(lease)
        assert not (root / "transaction.json").exists()
        assert foreign.read_bytes() == b"PRIVATE FOREIGN DATA"
        assert foreign.stat().st_ino == inode


def test_short_write_after_exclusive_open_cleans_only_owned_scratch(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = [0]

    def zero_write(fd, buf):
        written[0] += 1
        return 0

    with journal.MaintenanceTransactionJournal(root) as lease:
        with monkeypatch.context() as m:
            m.setattr(journal.os, "write", zero_write)
            with pytest.raises(journal.MaintenanceJournalRefused, match="short write"):
                begin(lease)
        assert written[0] == 1
        assert lease.inspect() is None
        assert not list(root.glob(".*.tmp"))


def test_partial_write_retries_then_fsyncs_and_publishes(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = journal.os.write
    calls = [0]

    def partial(fd, buf):
        calls[0] += 1
        return actual(fd, buf[: max(1, len(buf) // 3)])

    with journal.MaintenanceTransactionJournal(root) as lease:
        with monkeypatch.context() as m:
            m.setattr(journal.os, "write", partial)
            state = begin(lease)
        assert state.phase == "intent"
        assert calls[0] >= 2
        assert lease.inspect() == state


def test_foreign_replaced_scratch_inode_is_never_unlinked(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = "e" * 32
    scratch = root / ("." + fixed + ".tmp")
    old = root / "opened-journal-scratch"
    monkeypatch.setattr(journal.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed))
    real = journal.os.fsync
    swaps = [0]

    def swap_during_fsync(fd):
        if swaps[0] == 0:
            swaps[0] += 1
            scratch.rename(old)
            scratch.write_bytes(b"FOREIGN REPLACEMENT")
            scratch.chmod(0o600)
        return real(fd)

    with journal.MaintenanceTransactionJournal(root) as lease:
        with monkeypatch.context() as m:
            m.setattr(journal.os, "fsync", swap_during_fsync)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="foreign journal"
            ):
                begin(lease)
        assert swaps == [1]
        assert old.exists()
        assert scratch.read_bytes() == b"FOREIGN REPLACEMENT"
        assert lease.inspect() is None


def test_create_only_publish_refuses_conflicting_destination_inode(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    def collision(*args, **kwargs):
        raise FileExistsError("synthetic concurrent creation")

    with journal.MaintenanceTransactionJournal(root) as lease:
        with monkeypatch.context() as m:
            m.setattr(journal.os, "link", collision)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="publication incomplete"
            ):
                begin(lease)
        assert lease.inspect() is None
        assert not list(root.glob(".*.tmp"))


def test_failed_atomic_update_retains_previous_phase(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        before = begin(lease)

        def refuse_replace(*args, **kwargs):
            raise PermissionError("synthetic directory refused rename")

        with monkeypatch.context() as m:
            m.setattr(journal.os, "replace", refuse_replace)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="publication incomplete"
            ):
                lease.advance(
                    nonce=NONCE,
                    expected_revision=0,
                    phase="j7_locked",
                    receipt_digest=receipt("j7_locked"),
                )
        assert lease.inspect() == before
        assert not list(root.glob(".*.tmp"))


def test_directory_fsync_failure_after_publish_can_idempotently_replay(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        original = journal.os.fsync
        seen = [0]

        def refuse_dir_sync(fd):
            seen[0] += 1
            if seen[0] == 2:
                raise OSError("synthetic directory durability uncertain")
            original(fd)

        with monkeypatch.context() as m:
            m.setattr(journal.os, "fsync", refuse_dir_sync)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="publication incomplete"
            ):
                lease.advance(
                    nonce=NONCE,
                    expected_revision=0,
                    phase="j7_locked",
                    receipt_digest=receipt("j7_locked"),
                )
        assert seen == [2]
        after = lease.inspect()
        assert after is not None and after.phase == "j7_locked"
        # Never redo or skip a stage after a lost publish acknowledgement.
        assert (
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )
            == after
        )


def test_failed_first_publish_can_only_be_inspected_not_adopted(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        original = journal.os.fsync
        call = [0]

        def refuse_dir(fd):
            call[0] += 1
            if call[0] == 2:
                raise OSError("uncertain first commit")
            original(fd)

        with monkeypatch.context() as m:
            m.setattr(journal.os, "fsync", refuse_dir)
            with pytest.raises(
                journal.MaintenanceJournalRefused, match="publication incomplete"
            ):
                begin(lease)
        assert call == [2]
        snapshot = lease.inspect()
        assert snapshot is not None and snapshot.phase == "intent"
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )
