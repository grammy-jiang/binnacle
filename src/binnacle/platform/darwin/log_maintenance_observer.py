"""Read-only, non-adopting inspection of an existing Issue #30 transaction.

Unlike the controller's ordinary journal context this function NEVER creates
a lock or record, NEVER recovers a service, and NEVER grants any maintenance
authority. It acquires an existing lock nonblocking only to prove no current
cooperative owner holds it; an owner that just died or voluntarily exited
cannot have its in-memory journal key reconstructed or reused.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from binnacle.platform.darwin.log_maintenance_transaction import (
    JournalSnapshot,
    MaintenanceJournalRefused,
    MaintenanceTransactionJournal,
    _check_record,
    _hex32,
)


def inspect_unowned_transaction(root: Path) -> JournalSnapshot:
    """Inspect a pre-existing private transaction only if its OS lock is free.

    If a controller is still running and owns the existing exclusive lock,
    refuse immediately; never wait, signal or force a lease break. A missing
    journal/lock/root, changed inode or corrupt receipt is not 'no work':
    it requires separate operator investigation, not a guessed restoration.

    Returning a JournalSnapshot NEVER authorizes bootout, writer FD close,
    restart, archive publication or raw-source deletion.
    """
    if (
        not root.is_absolute()
        or not root.name.startswith("txn-")
        or not _hex32(root.name[4:])
        or root.resolve() != root
    ):
        raise MaintenanceJournalRefused("noncanonical recovery observation root")
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        raise MaintenanceJournalRefused("journal observer must be unprivileged")
    lease = MaintenanceTransactionJournal(root)
    try:
        # No O_CREAT anywhere: this path must not invent a recovery lease.
        lease._dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        lease._identity()
        lease._lockfd = os.open(
            "transaction.lock",
            # O_RDWR (without O_CREAT) is compatible with exclusive flock
            # semantics on both BSD/Darwin and Linux. No write syscall is made.
            os.O_RDWR | os.O_NOFOLLOW,
            dir_fd=lease._dirfd,
        )
        lease._lock_identity()
        try:
            fcntl.flock(lease._lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MaintenanceJournalRefused(
                "existing controller still owns the journal lease"
            ) from exc
        # Verify a lock replacement that occurred during the nonblocking
        # kernel acquisition, before checking any untrusted journal bytes.
        lease._pid = os.getpid()
        lease._verify()
        record = lease._read()
        if record is None:
            raise MaintenanceJournalRefused("existing journal record unavailable")
        snapshot = _check_record(record)
        lease._verify()
        return snapshot
    except OSError as exc:
        raise MaintenanceJournalRefused(
            "existing controller journal observation unavailable"
        ) from exc
    finally:
        # Closing FDs releases this *observation*, not the previous owner's
        # crashed control lease. No flock(LOCK_UN), unlink, or record write.
        lease._close()
