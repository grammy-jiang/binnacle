"""r6 W2 M1-a3 T1 (R-M1a2-T1): the jobs-dir proof runs BEFORE ``recover()``.

A symlinked jobs dir retargeted after the writer lock is refused. The refusal
must come before recovery: neither the held dir nor the decoy (the dir that
``recover()`` would read through the retargeted link) has a record marked
UNKNOWN, and ``recover()`` is never called. Mutant R1 (``hold_jobs_dir``
moved after ``recover()``) marks the decoy's record and fails this test.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.platform.darwin import job_manager_entry as entry
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    new_lease,
    write_record,
)
from tests.platform.darwin.test_r6w2_m1_a2_followups import (
    linked_jobs,
    retargeting_writer,
)
from tests.platform.darwin.test_r6w2_m1_ping_jobs_dir import lock_is_held

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")
V2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": "boot"}


@contextmanager
def base_dir() -> Iterator[Path]:
    """A private ``/tmp/r6w2-m1a3-*`` base (resolved: no /tmp symlink)."""
    with tempfile.TemporaryDirectory(prefix="r6w2-m1a3-", dir="/tmp") as value:
        yield Path(value).resolve()


@NATIVE
@pytest.mark.parametrize("decoy_lock", [False, True])
def test_the_jobs_dir_proof_refuses_before_recovery(monkeypatch, caplog, decoy_lock):
    with base_dir() as base:
        held, decoy, link = linked_jobs(base)
        if decoy_lock:  # a lock FILE in the decoy is still not the held inode
            (decoy / ".manager.lock").write_text("")
        write_record(held, "a" * 12, **V2)
        write_record(decoy, "b" * 12, **V2)  # what recover() reads after the swap
        (base / "rt").mkdir(mode=0o700)
        sock = base / "rt" / "jobs.sock"
        manager = manager_for(ReferenceOwner(), link)
        recovered: list[int] = []
        real_recover = manager.recover

        def recover() -> int:
            recovered.append(real_recover())
            return recovered[-1]

        monkeypatch.setattr(manager, "recover", recover)
        monkeypatch.setattr(entry, "jobs_dir_writer", retargeting_writer(link, decoy))
        caplog.set_level(logging.ERROR, logger="binnacle.job_manager")
        stop = threading.Event()
        stop.set()  # a manager that wrongly serves returns at once (no hang)
        with pytest.raises(RuntimeError, match="^job_manager_jobs_dir_mismatch$"):
            entry.serve_job_manager(
                manager, socket_path=sock, lease=new_lease(base / "rt"), stop=stop
            )
        assert "event=job_manager_jobs_dir_mismatch" in caplog.text
        assert recovered == []  # the proof ran first; recovery never started
        assert "authority" not in meta_of(decoy, "b" * 12)
        assert "authority" not in meta_of(held, "a" * 12)
        assert manager.held_jobs_dir is None
        assert not sock.exists()
        assert not lock_is_held(held)
        manager.close()
