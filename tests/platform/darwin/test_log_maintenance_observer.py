"""Read-only recovery witness: no auto-owned lock, no record creation or mutation."""

from __future__ import annotations

import fcntl
import hashlib
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.platform.darwin import log_maintenance_transaction as journal
from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from tests.platform.darwin.test_log_maintenance_transaction import (
    NONCE,
    advance_to,
    begin,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_existing_completed_transaction_is_observable_but_not_authority(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
        expected = advance_to(controller, "complete")
    observed = inspect_unowned_transaction(root)
    assert observed == expected
    assert observed.phase == "complete"
    assert not observed.needs_external_recovery
    assert not observed.producer_may_be_stopped
    assert not observed.production_authorized


def test_unfinished_guardian_armed_is_readable_without_owning_append(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
        expected = advance_to(controller, "guardian_armed")
    snapshot = inspect_unowned_transaction(root)
    assert snapshot == expected
    assert snapshot.needs_external_recovery
    assert snapshot.producer_may_be_stopped
    assert snapshot.production_authorized is False
    with journal.MaintenanceTransactionJournal(root) as new_owner:
        assert new_owner._key is None
        assert new_owner.inspect() == snapshot
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            new_owner.advance(
                nonce=NONCE,
                expected_revision=snapshot.revision,
                phase="producer_stopped",
                receipt_digest="a" * 64,
            )


def test_attempt_during_active_controller_refuses_nonblocking(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        expected = begin(controller)
        before = (root / "transaction.json").read_bytes()
        with pytest.raises(journal.MaintenanceJournalRefused, match="still owns"):
            inspect_unowned_transaction(root)
        assert controller.inspect() == expected
        assert (root / "transaction.json").read_bytes() == before
    assert inspect_unowned_transaction(root) == expected


def test_observation_preserves_every_file_identity_and_record_byte(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
        expected = advance_to(controller, "canonical_verified")
    paths = [root / "transaction.lock", root / "transaction.json"]
    originals = [
        (
            p.stat().st_dev,
            p.stat().st_ino,
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).digest(),
        )
        for p in paths
    ]
    count = len(list(root.iterdir()))
    for _ in range(4):
        assert inspect_unowned_transaction(root) == expected
    current = [
        (
            p.stat().st_dev,
            p.stat().st_ino,
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).digest(),
        )
        for p in paths
    ]
    assert current == originals
    assert len(list(root.iterdir())) == count


def test_no_lock_or_record_is_ever_created_during_observation(root: Path) -> None:
    with pytest.raises(journal.MaintenanceJournalRefused, match="unavailable"):
        inspect_unowned_transaction(root)
    assert list(root.iterdir()) == []


def test_missing_journal_record_stays_unknown(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root):
        pass
    lock = root / "transaction.lock"
    assert lock.is_file()
    with pytest.raises(journal.MaintenanceJournalRefused, match="record unavailable"):
        inspect_unowned_transaction(root)
    assert list(root.iterdir()) == [lock]


@pytest.mark.parametrize("bad", ["/tmp", "relative", "txn-nothex", "txn-" + "A" * 32])
def test_foreign_path_never_results_in_lock_creation(tmp_path: Path, bad: str) -> None:
    path = Path(bad)
    if bad.startswith("txn-"):
        path = tmp_path / bad
        path.mkdir(mode=0o700)
    with pytest.raises(journal.MaintenanceJournalRefused, match="noncanonical"):
        inspect_unowned_transaction(path)


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_public_root_refuses_without_touching_lock(root: Path, mode: int) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    root.chmod(mode)
    with pytest.raises(journal.MaintenanceJournalRefused, match="root identity"):
        inspect_unowned_transaction(root)
    assert (root / "transaction.json").is_file()


def test_symlink_root_is_rejected(root: Path) -> None:
    root.rename(root.with_name("real-root"))
    root.symlink_to(root.with_name("real-root"), target_is_directory=True)
    with pytest.raises(journal.MaintenanceJournalRefused, match="noncanonical"):
        inspect_unowned_transaction(root)
    assert not (root / "transaction.lock").exists() or root.is_symlink()


@pytest.mark.parametrize("violation", ["public", "hardlink", "symlink", "directory"])
def test_unsafe_existing_lock_refused_before_reading(
    root: Path, violation: str
) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    lock = root / "transaction.lock"
    if violation == "public":
        lock.chmod(0o644)
    elif violation == "hardlink":
        os.link(lock, root / "shadow-lock")
    elif violation == "symlink":
        lock.rename(root / "original-lock")
        lock.symlink_to(root / "original-lock")
    else:
        lock.unlink()
        lock.mkdir()
    with pytest.raises(journal.MaintenanceJournalRefused):
        inspect_unowned_transaction(root)
    assert (root / "transaction.json").is_file()


def test_corrupt_existing_record_is_not_a_successful_observation(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    record = root / "transaction.json"
    record.write_bytes(b"corrupt ignored if no verifier")
    record.chmod(0o600)
    with pytest.raises(journal.MaintenanceJournalRefused):
        inspect_unowned_transaction(root)
    assert record.read_bytes() == b"corrupt ignored if no verifier"


def test_read_only_observer_after_sigkill_does_not_adopt_old_controller(
    root: Path,
) -> None:
    code = (
        "import os,signal,sys\n"
        "from pathlib import Path\n"
        "from binnacle.platform.darwin.log_maintenance_transaction import "
        "MaintenanceTransactionJournal\n"
        "p=Path(sys.argv[1])\n"
        "with MaintenanceTransactionJournal(p) as j:\n"
        " s=j.begin(nonce='a'*32,controller_generation='b'*32,"
        "target='system/com.binnacle.mcp',producer_pid=230,"
        "producer_generation='c'*32,source_dev=89,source_ino=901)\n"
        " for idx,phase in enumerate(('j7_locked','watchdog_acked',"
        "'mcp_drained','jobs_drained','guardian_armed')):\n"
        "  s=j.advance(nonce='a'*32,expected_revision=s.revision,"
        "phase=phase,receipt_digest='e'*64)\n"
        " os.kill(os.getpid(),signal.SIGKILL)\n"
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr
    observed = inspect_unowned_transaction(root)
    assert observed.phase == "guardian_armed"
    assert observed.needs_external_recovery
    assert observed.producer_may_be_stopped
    assert not observed.production_authorized


def test_independent_flock_owner_also_blocks_read_only_inspection(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    with (root / "transaction.lock").open("r+b") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(journal.MaintenanceJournalRefused, match="still owns"):
            inspect_unowned_transaction(root)
    assert inspect_unowned_transaction(root).phase == "intent"


def test_journal_content_swapped_with_valid_foreign_nonce_refuses(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as controller:
        begin(controller)
    record = root / "transaction.json"
    item = journal.json.loads(record.read_text())
    item["nonce"] = "d" * 32
    body = {key: value for key, value in item.items() if key != "digest"}
    item["digest"] = journal.hashlib.sha256(journal._canonical(body)).hexdigest()
    record.write_bytes(journal._canonical(item))
    record.chmod(0o600)
    with pytest.raises(journal.MaintenanceJournalRefused, match="nonce"):
        inspect_unowned_transaction(root)


@pytest.mark.parametrize("identity", ["root", "setuid"])
def test_observer_rejects_root_and_mixed_uid(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity: str,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as txn:
        begin(txn)
    from binnacle.platform.darwin import log_maintenance_observer as obs

    uid = os.getuid()
    with monkeypatch.context() as m:
        if identity == "root":
            m.setattr(obs.os, "getuid", lambda: 0)
        else:
            m.setattr(obs.os, "geteuid", lambda: uid + 1)
        with pytest.raises(journal.MaintenanceJournalRefused, match="unprivileged"):
            inspect_unowned_transaction(root)


def test_swapped_lock_path_during_kernel_acquisition_refused(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as txn:
        begin(txn)
    from binnacle.platform.darwin import log_maintenance_observer as obs

    original_flock = fcntl.flock
    moves = [0]
    lock = root / "transaction.lock"

    def substitute(fd: int, flags: int) -> None:
        original_flock(fd, flags)
        if moves[0] == 0:
            moves[0] += 1
            lock.rename(root / "old-transaction.lock")
            lock.write_bytes(b"foreigner")
            lock.chmod(0o600)

    with monkeypatch.context() as m:
        m.setattr(obs.fcntl, "flock", substitute)
        with pytest.raises(journal.MaintenanceJournalRefused, match="lock identity"):
            inspect_unowned_transaction(root)
    assert moves == [1]
    assert lock.read_bytes() == b"foreigner"
    assert (root / "old-transaction.lock").is_file()
    assert (root / "transaction.json").is_file()


def test_root_renamed_after_open_is_not_observed_as_same_transaction(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as txn:
        begin(txn)
    from binnacle.platform.darwin import log_maintenance_observer as obs

    real_open = os.open
    moved = root.with_name("renamed-transaction")
    changes = [0]

    def change_root(path, flags, *args, **kw):
        fd = real_open(path, flags, *args, **kw)
        if str(path) == str(root) and changes[0] == 0:
            changes[0] += 1
            root.rename(moved)
            root.mkdir(mode=0o700)
        return fd

    with monkeypatch.context() as m:
        m.setattr(obs.os, "open", change_root)
        with pytest.raises(journal.MaintenanceJournalRefused, match="root identity"):
            inspect_unowned_transaction(root)
    assert changes == [1]
    assert not (root / "transaction.json").exists()
    assert (moved / "transaction.json").is_file()
