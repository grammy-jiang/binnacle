"""Portable transaction-journal tests; no real launchd, RPC or archive I/O."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from binnacle.platform.darwin import log_maintenance_transaction as journal

NONCE = "a" * 32
CTRL = "b" * 32
PRODUCER = "c" * 32
TARGET = "system/com.binnacle.mcp"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / ("txn-" + NONCE)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def begin(txn: journal.MaintenanceTransactionJournal, **changes):
    args = {
        "nonce": NONCE,
        "controller_generation": CTRL,
        "target": TARGET,
        "producer_pid": 230,
        "producer_generation": PRODUCER,
        "source_dev": 89,
        "source_ino": 901,
    }
    args.update(changes)
    return txn.begin(**cast(Any, args))


def receipt(phase: str) -> str:
    return hashlib.sha256(("test-fake-proof:" + phase).encode()).hexdigest()


def advance_to(txn: journal.MaintenanceTransactionJournal, phase: str):
    result = txn.inspect()
    assert result is not None
    stages = journal._PHASES
    for step in stages[result.revision + 1 : stages.index(phase) + 1]:
        result = txn.advance(
            nonce=NONCE,
            expected_revision=result.revision,
            phase=step,
            receipt_digest=receipt(step),
        )
    return result


def test_absent_record_inspects_as_unknown_not_permission(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        assert lease.inspect() is None
        assert not (root / "transaction.json").exists()
        assert (root / "transaction.lock").stat().st_mode & 0o777 == 0o600


def test_begin_creates_atomic_private_journal_never_authorizes_io(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        state = begin(lease)
        assert state.nonce == NONCE and state.owner_pid == os.getpid()
        assert state.phase == "intent" and state.revision == 0
        assert not state.production_authorized
        assert not state.needs_external_recovery
        assert not state.producer_may_be_stopped
        assert lease.inspect() == state
        meta = (root / "transaction.json").stat()
        assert meta.st_mode & 0o777 == 0o600 and meta.st_nlink == 1
        assert meta.st_uid == os.getuid()
        assert not list(root.glob(".*.tmp"))


def test_all_steps_strictly_linear_until_completed(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        for step in journal._PHASES[1:]:
            new = advance_to(lease, step)
            assert new.phase == step
            assert new.revision == journal._PHASES.index(step)
            assert len(new.receipts) == new.revision
            assert not new.production_authorized
            if step == "producer_stopped":
                assert new.producer_may_be_stopped
            if step == "complete":
                assert not new.needs_external_recovery
                assert not new.producer_may_be_stopped
        with pytest.raises(journal.MaintenanceJournalRefused, match="immutable"):
            lease.advance(
                nonce=NONCE,
                expected_revision=len(journal._PHASES) - 1,
                phase="complete",
                receipt_digest=receipt("complete"),
            )


def test_after_writer_stop_an_unfinished_transaction_demands_external_recovery(
    root: Path,
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        paused = advance_to(lease, "producer_stopped")
        assert paused.needs_external_recovery
        assert paused.producer_may_be_stopped
    # A new controller has no original ephemeral signing key. Even with a
    # reused PID and all JSON available, it cannot adopt the retired writer.
    with journal.MaintenanceTransactionJournal(root) as reader:
        snapshot = reader.inspect()
        assert snapshot is not None and snapshot.producer_may_be_stopped
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            reader.advance(
                nonce=NONCE,
                expected_revision=snapshot.revision,
                phase="writer_fds_closed",
                receipt_digest=receipt("writer_fds_closed"),
            )


def test_idempotent_replay_only_same_digest_and_revision(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        step = lease.advance(
            nonce=NONCE,
            expected_revision=0,
            phase="j7_locked",
            receipt_digest=receipt("j7_locked"),
        )
        assert (
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )
            == step
        )
        for wrong in (
            (0, "j7_locked", "f" * 64),
            (0, "watchdog_acked", receipt("watchdog_acked")),
            (1, "guardian_armed", receipt("guardian_armed")),
            (11, "watchdog_acked", receipt("watchdog_acked")),
        ):
            with pytest.raises(journal.MaintenanceJournalRefused, match="not next"):
                lease.advance(
                    nonce=NONCE,
                    expected_revision=wrong[0],
                    phase=wrong[1],
                    receipt_digest=wrong[2],
                )
        assert lease.inspect() == step


def test_existing_transaction_root_rejects_another_begin(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        with pytest.raises(journal.MaintenanceJournalRefused, match="already exists"):
            begin(lease)
    with (
        journal.MaintenanceTransactionJournal(root) as successor,
        pytest.raises(journal.MaintenanceJournalRefused, match="already exists"),
    ):
        begin(successor)


@pytest.mark.parametrize(
    ("changed", "error"),
    [
        ({"nonce": "d" * 32}, "initial"),
        ({"controller_generation": "bogus"}, "initial"),
        ({"controller_generation": "A" * 32}, "initial"),
        ({"target": "system/com.binnacle.session-observability"}, "initial"),
        ({"target": "/tmp/arbitrary-bootout"}, "initial"),
        ({"target": "system/com.binnacle.mcp\n"}, "initial"),
        ({"producer_pid": 0}, "initial"),
        ({"producer_pid": False}, "initial"),
        ({"producer_generation": "C" * 32}, "initial"),
        ({"source_ino": -1}, "initial"),
        ({"source_dev": True}, "initial"),
    ],
)
def test_begin_with_invalid_identity_never_creates_journal(
    root: Path, changed: dict, error: str
) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        with pytest.raises(journal.MaintenanceJournalRefused, match=error):
            begin(lease, **changed)
        assert lease.inspect() is None


@pytest.mark.parametrize("phase", ["intent", "not-real", "", 123])
def test_owner_cannot_jump_back_or_invent_phase(root: Path, phase: object) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase=cast(str, phase),
                receipt_digest="e" * 64,
            )


@pytest.mark.parametrize(
    "bad",
    [None, True, "0", -1, 1.0],
    ids=["none", "bool", "text", "negative", "float"],
)
def test_malformed_expected_revision_fails_closed(root: Path, bad: object) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        with pytest.raises(journal.MaintenanceJournalRefused):
            lease.advance(
                nonce=NONCE,
                expected_revision=cast(int, bad),
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )


@pytest.mark.parametrize("bad", [None, 1, "short", "F" * 64, "g" * 64])
def test_invalid_receipt_hash_never_advances(root: Path, bad: object) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        begin(lease)
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=cast(str, bad),
            )


def test_wrong_nonce_does_not_mutate_journal(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root) as lease:
        original = begin(lease)
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            lease.advance(
                nonce="e" * 32,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )
        assert lease.inspect() == original


def test_close_purges_ephemeral_key_and_cannot_reuse_lease(root: Path) -> None:
    lease = journal.MaintenanceTransactionJournal(root)
    with lease:
        begin(lease)
        assert lease._key is not None
    assert lease._key is None
    with pytest.raises(journal.MaintenanceJournalRefused, match="owner process"):
        lease.inspect()
    with lease:
        assert lease.inspect() is not None
        with pytest.raises(journal.MaintenanceJournalRefused, match="owner/evidence"):
            lease.advance(
                nonce=NONCE,
                expected_revision=0,
                phase="j7_locked",
                receipt_digest=receipt("j7_locked"),
            )


def test_cross_process_flock_excludes_other_controller(root: Path) -> None:
    with journal.MaintenanceTransactionJournal(root):
        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "from pathlib import Path\n"
                    "from binnacle.platform.darwin.log_maintenance_transaction import "
                    "MaintenanceTransactionJournal, MaintenanceJournalRefused\n"
                    "try:\n with MaintenanceTransactionJournal(Path(sys.argv[1])): "
                    "sys.exit(25)\n"
                    "except MaintenanceJournalRefused: sys.exit(17)\n"
                ),
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        assert contender.returncode == 17, contender.stderr
        assert not (root / "transaction.json").exists()


def test_killed_controller_does_not_authorize_replay_or_continue(root: Path) -> None:
    # Only SIGKILL the synthetic test controller spawned by this fixture.
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os,sys,signal\n"
                "from pathlib import Path\n"
                "from binnacle.platform.darwin.log_maintenance_transaction import "
                "MaintenanceTransactionJournal\n"
                "p=Path(sys.argv[1])\n"
                "with MaintenanceTransactionJournal(p) as j:\n"
                " j.begin(nonce='a'*32,controller_generation='b'*32,"
                "target='system/com.binnacle.mcp',producer_pid=230,"
                "producer_generation='c'*32,source_dev=89,source_ino=901)\n"
                " j.advance(nonce='a'*32,expected_revision=0,phase='j7_locked',"
                "receipt_digest='e'*64)\n"
                " os.kill(os.getpid(),signal.SIGKILL)\n"
            ),
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL
    with journal.MaintenanceTransactionJournal(root) as observer:
        report = observer.inspect()
        assert report is not None
        assert report.phase == "j7_locked"
        assert report.needs_external_recovery
        assert not report.production_authorized
        with pytest.raises(journal.MaintenanceJournalRefused):
            observer.advance(
                nonce=NONCE,
                expected_revision=1,
                phase="watchdog_acked",
                receipt_digest="e" * 64,
            )


def test_manually_constructed_snapshot_cannot_grant_authority(root: Path) -> None:
    with pytest.raises(ValueError, match="never authorizes"):
        journal.JournalSnapshot(
            NONCE,
            TARGET,
            1,
            CTRL,
            2,
            PRODUCER,
            1,
            2,
            "intent",
            0,
            (),
            production_authorized=True,
        )
