"""r6 W2 M1-a2 (R-M1 review N1, N2, N5): held jobs dir, path reasons, default root.

N1: the ping ``jobs_dir`` is the realpath only when that dir's ``.manager.lock``
is the inode whose writer flock this manager holds (st_dev, st_ino). A symlinked
jobs dir retargeted between the lock and the realpath is refused, fail closed,
with ``event=job_manager_jobs_dir_mismatch``, before recovery and binding.
N2: an unusable socket path names its actual reason (not absolute vs too long).
N5: removing the DEFAULT Application Support root of a test HOME while a job
runs keeps the job, the manager rebinds, and a later default-root request works.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import generation_runtime as runtime
from binnacle.platform.darwin import job_manager_entry as entry
from tests.platform.darwin.test_job_manager_entry import ping_when_ready
from tests.platform.darwin.test_job_manager_resilience import wait_for
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    new_lease,
    wait_published,
    write_record,
)
from tests.platform.darwin.test_r6_d1_runtime_rebind import (
    alive,
    finish,
    generation,
    reap_exact,
)
from tests.platform.darwin.test_r6_d2_stop_marker_start import start_entry
from tests.platform.darwin.test_r6w2_m1_ping_jobs_dir import lock_is_held

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")
DEFAULT_ROOT = Path("Library/Application Support/Binnacle/r3")


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


# --- N2 -------------------------------------------------------------------


def cause(path: Path) -> str:
    with pytest.raises(NativeCapabilityError) as refused:
        runtime.check_socket_path(path)
    assert refused.value.code == "runtime_socket_path_invalid"
    return str(refused.value.__cause__)


def test_a_short_relative_socket_path_is_reported_not_absolute():
    relative = Path("relative") / "jobs.sock"
    assert cause(relative) == f"darwin_socket_path_not_absolute: {relative}"
    assert "bytes" not in cause(relative) and "too_long" not in cause(relative)
    with pytest.raises(NativeCapabilityError) as refused:
        entry.require_socket_path(relative)  # the manager entry's own check
    assert str(refused.value.__cause__).startswith("darwin_socket_path_not_absolute")


def test_an_overlong_socket_path_is_reported_too_long():
    long = Path("/tmp") / ("x" * 100) / "jobs.sock"
    size = len(os.fsencode(long))
    assert size >= 104
    assert cause(long) == f"darwin_socket_path_too_long: {size} bytes > 103: {long}"
    relative = Path("x" * 100) / "jobs.sock"  # both: the size is reported first
    assert cause(relative).startswith("darwin_socket_path_too_long: ")
    runtime.check_socket_path(Path("/tmp/fits/jobs.sock"))  # no error


def test_a_relative_runtime_dir_names_the_reason(monkeypatch):
    monkeypatch.setenv("BINNACLE_RUNTIME_DIR", "relative-runtime")
    with pytest.raises(NativeCapabilityError) as refused:
        runtime.resolve_runtime_paths()
    assert str(refused.value.__cause__) == (
        "darwin_socket_path_not_absolute: relative-runtime/jobs.sock"
    )
    assert not Path("relative-runtime").exists()


# --- N5 -------------------------------------------------------------------


@NATIVE
def test_removing_the_default_root_keeps_the_job_and_rebinds(monkeypatch):
    """Test HOME only: the real ~/Library/Application Support is never used."""
    with base_dir() as base:
        (base / "bin").mkdir()
        jobs = base / "jobs"
        (base / "config.toml").write_text(f'[jobs]\ndir = "{jobs}"\n')  # no socket
        sock = base / DEFAULT_ROOT / "jobs.sock"
        assert " " in str(sock) and len(os.fsencode(sock)) < entry.SUN_PATH_MAX
        child = start_entry(base)  # HOME=base: the default root is under base
        try:
            client, pong = ping_when_ready(sock, child)
            me, before = pong["owner_instance_id"], generation(sock)
            kw = {"workdir": base, "stdin": None, "call_id": "n5"}
            started = client.start(sock, command="sleep 60", wait_seconds=0, **kw)
            job_id = started["job_id"]
            leader = meta_of(jobs, job_id)["pid"]
            shutil.rmtree(base / "Library" / "Application Support")  # the space
            assert wait_for(lambda: generation(sock) not in (None, before), 20)
            client, pong = ping_when_ready(sock, child)
            assert (pong["pid"], pong["owner_instance_id"]) == (child.pid, me)
            assert (pong["running_jobs"], pong["unknown_jobs"]) == (1, 0)
            assert alive(leader) and "exit_code" not in meta_of(jobs, job_id)
            # A later request through the client's DEFAULT root resolution.
            monkeypatch.delenv("BINNACLE_RUNTIME_DIR", raising=False)
            monkeypatch.setenv("HOME", str(base))
            default = runtime.resolve_runtime_paths().jobs_socket
            assert default == sock
            done = client.start(default, command="exit 0", wait_seconds=10, **kw)
            assert done["state"] == "exited"
            assert client.stop(default, job_id)["state"] == "exited"
            assert meta_of(jobs, job_id)["termination_reason"] == "stop_requested"
            err = finish(child, sock, me)
            assert "event=job_manager_endpoint_lost" in err
        finally:
            reap_exact(child)
