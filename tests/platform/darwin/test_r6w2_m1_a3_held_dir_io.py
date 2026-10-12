"""r6 W2 M1-a3 F1 (R-M1a2-F1): after the proof, I/O goes through the held dir.

``hold_jobs_dir`` proves that the realpath of the configured jobs dir holds the
locked ``.manager.lock``. A symlinked jobs dir retargeted AFTER that proof must
not move the manager: recovery reads the held dir, new records land in it, the
``.lock`` transactions use it, and the ping still reports it. The decoy that
the link now names is never read or written.
"""

from __future__ import annotations

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
    client,
    manager_for,
    meta_of,
    new_lease,
    run,
    wait_published,
    write_record,
)
from tests.platform.darwin.test_r6w2_m1_a2_followups import linked_jobs
from tests.platform.darwin.test_r6w2_m1_ping_jobs_dir import lock_is_held

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")
V2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": "boot"}


@contextmanager
def base_dir() -> Iterator[Path]:
    """A private ``/tmp/r6w2-m1a3-*`` base (resolved: no /tmp symlink)."""
    with tempfile.TemporaryDirectory(prefix="r6w2-m1a3-", dir="/tmp") as value:
        yield Path(value).resolve()


def retarget(link: Path, target: Path) -> None:
    staged = link.with_name(link.name + ".swap")
    staged.symlink_to(target)
    staged.replace(link)  # atomic retarget of the symlink


@NATIVE
def test_a_retarget_after_the_proof_keeps_all_io_in_the_held_dir(monkeypatch):
    with base_dir() as base:
        held, decoy, link = linked_jobs(base)
        write_record(held, "a" * 12, **V2)  # recovery must mark this one
        write_record(decoy, "b" * 12, **V2)  # and never this one
        (base / "rt").mkdir(mode=0o700)
        sock = base / "rt" / "jobs.sock"
        manager = manager_for(ReferenceOwner(), link)
        proven = manager.hold_jobs_dir

        def hold_then_retarget(lock_fd: int) -> str:
            value = proven(lock_fd)
            retarget(link, decoy)  # after the proof, before recover()
            return value

        monkeypatch.setattr(manager, "hold_jobs_dir", hold_then_retarget)
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
            assert link.resolve() == decoy  # the link really names the decoy now
            assert pong["jobs_dir"] == str(held) == manager.held_jobs_dir
            assert meta_of(held, "a" * 12)["authority"] == "UNKNOWN"
            assert "authority" not in meta_of(decoy, "b" * 12)
            job = run(sock, "true", base, wait=5)
            assert job["state"] == "exited"
            assert meta_of(held, job["job_id"])["exit_code"] == 0
            assert not (decoy / job["job_id"]).exists()
            assert client().ping(sock)["jobs_dir"] == str(held)
            assert lock_is_held(held)
            assert (held / ".lock").exists() and not (decoy / ".lock").exists()
            assert sorted(p.name for p in decoy.iterdir()) == ["b" * 12]
            assert manager.jobs_dir == held
        finally:
            stop.set()
            thread.join(15)
        assert not thread.is_alive() and not errors
