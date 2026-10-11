"""r6 W2 M1-a2 (R-M1 review N1): the ping reports only a jobs dir it HOLDS.

N1: the ping ``jobs_dir`` is the realpath only when that dir's ``.manager.lock``
is the inode whose writer flock this manager holds (st_dev, st_ino). A symlinked
jobs dir retargeted between the lock and the realpath is refused, fail closed,
with ``event=job_manager_jobs_dir_mismatch``, before recovery and binding.
"""

from __future__ import annotations

import logging
import os
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
    wait_published,
    write_record,
)
from tests.platform.darwin.test_r6w2_m1_ping_jobs_dir import lock_is_held

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")


@contextmanager
def base_dir() -> Iterator[Path]:
    """A private ``/tmp/r6w2-m1a2-*`` base (resolved: no /tmp symlink)."""
    with tempfile.TemporaryDirectory(prefix="r6w2-m1a2-", dir="/tmp") as value:
        yield Path(value).resolve()


def retargeting_writer(link: Path, target: Path | None):
    """Injected hook: the real writer lock, then (optionally) retarget ``link``.

    The swap happens after the flock is taken and before the manager resolves
    the realpath: the exact window R-M1-N1 names, without a sleep race.
    """
    real = entry.jobs_dir_writer

    @contextmanager
    def writer(jobs_dir: Path) -> Iterator[int]:
        with real(jobs_dir) as lock_fd:
            if target is not None:
                staged = link.with_name(link.name + ".swap")
                staged.symlink_to(target)
                os.replace(staged, link)  # atomic retarget of the symlink
            yield lock_fd

    return writer


def linked_jobs(base: Path) -> tuple[Path, Path, Path]:
    held, decoy, link = base / "jobs-held", base / "jobs-decoy", base / "jobs"
    held.mkdir()
    decoy.mkdir()
    link.symlink_to(held)
    return held, decoy, link


# --- N1 -------------------------------------------------------------------


@NATIVE
@pytest.mark.parametrize("decoy_lock", [False, True])
def test_a_jobs_dir_retargeted_after_the_lock_is_refused(
    monkeypatch, caplog, decoy_lock
):
    with base_dir() as base:
        held, decoy, link = linked_jobs(base)
        if decoy_lock:  # a lock FILE in the decoy is still not the held inode
            (decoy / ".manager.lock").write_text("")
        v2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": "boot"}
        write_record(held, "a" * 12, **v2)  # recovery would mark it UNKNOWN
        (base / "rt").mkdir(mode=0o700)
        sock = base / "rt" / "jobs.sock"
        manager = manager_for(ReferenceOwner(), link)
        monkeypatch.setattr(entry, "jobs_dir_writer", retargeting_writer(link, decoy))
        caplog.set_level(logging.ERROR, logger="binnacle.job_manager")
        stop = threading.Event()
        stop.set()  # a manager that wrongly serves returns at once (no hang)
        with pytest.raises(RuntimeError, match="^job_manager_jobs_dir_mismatch$"):
            entry.serve_job_manager(
                manager, socket_path=sock, lease=new_lease(base / "rt"), stop=stop
            )
        assert "event=job_manager_jobs_dir_mismatch" in caplog.text
        assert f"realpath={decoy}" in caplog.text
        assert manager.held_jobs_dir is None  # never reported as held
        assert not sock.exists()  # refused before binding
        assert "authority" not in meta_of(held, "a" * 12)  # before recovery
        assert not lock_is_held(held)  # the lock is released on refusal
        manager.close()


@NATIVE
def test_an_unchanged_symlinked_jobs_dir_still_serves_its_realpath(monkeypatch):
    with base_dir() as base:
        held, _, link = linked_jobs(base)
        (base / "rt").mkdir(mode=0o700)
        sock = base / "rt" / "jobs.sock"
        manager = manager_for(ReferenceOwner(), link)
        monkeypatch.setattr(entry, "jobs_dir_writer", retargeting_writer(link, None))
        stop, errors = threading.Event(), []

        def serve() -> None:
            try:
                lease = new_lease(base / "rt")
                entry.serve_job_manager(
                    manager, socket_path=sock, lease=lease, stop=stop
                )
            except Exception as exc:  # noqa: BLE001 - surfaced by the test
                errors.append(exc)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            pong = wait_published(sock)
            assert pong["jobs_dir"] == str(held) == manager.held_jobs_dir
            assert lock_is_held(held)
        finally:
            stop.set()
            thread.join(15)
        assert not thread.is_alive() and not errors


def test_hold_jobs_dir_compares_the_lock_inode_not_the_name(tmp_path, caplog):
    """Runs everywhere: a symlinked lock file names another inode (lstat)."""
    held, other = tmp_path / "held", tmp_path / "other"
    held.mkdir()
    other.mkdir()
    manager = manager_for(ReferenceOwner(), held)
    fd = os.open(other / ".manager.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        (held / ".manager.lock").symlink_to(other / ".manager.lock")
        with pytest.raises(RuntimeError, match="job_manager_jobs_dir_mismatch"):
            manager.hold_jobs_dir(fd)
        (held / ".manager.lock").unlink()
        os.link(other / ".manager.lock", held / ".manager.lock")  # same inode
        assert manager.hold_jobs_dir(fd) == os.path.realpath(held)
        assert manager.held_jobs_dir == os.path.realpath(held)
    finally:
        os.close(fd)
        manager.close()
    assert caplog.text.count("event=job_manager_jobs_dir_mismatch") == 1
