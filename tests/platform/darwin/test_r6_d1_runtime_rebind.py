"""r6 D1 (DARWIN-FOLLOWUP-runtime-dir-purgeable): the endpoint survives purges.

A removed socket file or a removed runtime root never ends a manager that owns
jobs: it recreates the private 0700 root, publishes a fresh generation and
keeps the same incarnation, pid and jobs. Foreign endpoint debris is never
adopted or removed, and a second manager never becomes a writer. Paths contain
a space (``Application Support``) and ``sun_path`` overflow fails closed.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.features.commands import job_client
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin.generation_runtime import denied
from tests.platform.darwin.test_job_manager_entry import ping_when_ready
from tests.platform.darwin.test_job_manager_resilience import wait_for
from tests.platform.darwin.test_job_manager_service import meta_of
from tests.platform.darwin.test_r6_d2_stop_marker_start import (
    start_entry,
    write_marker,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")
RUNTIME = Path("Application Support/Binnacle/r3")  # a space, like the D1 root


@contextmanager
def manager_home(socket: Path | None = None) -> Iterator[tuple[Path, Path, Path]]:
    """A private base holding config, jobs and ``<base>/Application Support/...``."""
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        base = Path(value).resolve()
        root = base
        for part in RUNTIME.parts:
            root = root / part
            root.mkdir(mode=0o700)
        (base / "bin").mkdir()
        sock, jobs = socket or root / "jobs.sock", base / "jobs"
        (base / "config.toml").write_text(
            f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        )
        yield base, sock, jobs


def generation(sock: Path) -> str | None:
    try:
        return json.loads(sock.with_name("jobs.sock.auth").read_text())["generation"]
    except (OSError, ValueError, KeyError):
        return None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # existence probe of our own job's leader; no signal
    except ProcessLookupError:
        return False
    return True


def finish(child, sock: Path, owner_id: str) -> str:
    """The quiet-window stop still works in the (recreated) root: exit 0."""
    write_marker(sock.with_name("jobs.sock.stop"), owner_id)
    child.send_signal(signal.SIGTERM)
    _, err = child.communicate(timeout=30)
    assert child.returncode == 0, err
    return err


def reap_exact(*children) -> None:
    for child in children:  # our exact children only (RULE-NO-PKILL)
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


@NATIVE
@pytest.mark.parametrize("loss", ["socket_file", "runtime_dir"])
def test_endpoint_loss_rebinds_and_keeps_the_running_job(loss):
    with manager_home() as (base, sock, jobs):
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            me, before = pong["owner_instance_id"], generation(sock)
            kw = {"workdir": base, "stdin": None, "call_id": "d1"}
            job_id = client.start(sock, command="sleep 60", wait_seconds=0, **kw)[
                "job_id"
            ]
            leader = meta_of(jobs, job_id)["pid"]
            if loss == "socket_file":
                sock.unlink()
            else:
                shutil.rmtree(sock.parent)
            assert wait_for(lambda: generation(sock) not in (None, before), 20)
            client, pong = ping_when_ready(sock, child)
            assert (pong["pid"], pong["owner_instance_id"]) == (child.pid, me)
            assert (pong["running_jobs"], pong["unknown_jobs"]) == (1, 0)
            assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700
            assert stat.S_ISSOCK(sock.stat().st_mode)
            meta = meta_of(jobs, job_id)
            assert meta["pid"] == leader and alive(leader)
            assert "exit_code" not in meta and "authority" not in meta
            # Still owned: this incarnation stops it and records the exit.
            assert client.stop(sock, job_id)["state"] == "exited"
            assert meta_of(jobs, job_id)["termination_reason"] == "stop_requested"
            err = finish(child, sock, me)
            assert "event=job_manager_endpoint_lost" in err
        finally:
            reap_exact(child)


@NATIVE
def test_foreign_debris_stays_unowned_and_no_second_writer_appears():
    with manager_home() as (base, sock, jobs):
        child = second = None
        try:
            child = start_entry(base)
            client, pong = ping_when_ready(sock, child)
            me = pong["owner_instance_id"]
            kw = {"workdir": base, "stdin": None, "call_id": "d1"}
            job_id = client.start(sock, command="sleep 60", wait_seconds=0, **kw)[
                "job_id"
            ]
            leader = meta_of(jobs, job_id)["pid"]
            foreign = sock.with_name("foreign")
            foreign.write_text("not this manager's endpoint")
            foreign.chmod(0o600)
            identity = (foreign.stat().st_dev, foreign.stat().st_ino)
            os.replace(foreign, sock)  # atomic: a stale, unrecorded entry
            assert wait_for(lambda: generation(sock) is None, 10)
            time.sleep(1.5)  # several rebind attempts against the debris
            assert child.poll() is None and alive(leader)
            assert (sock.stat().st_dev, sock.stat().st_ino) == identity
            assert sock.read_text() == "not this manager's endpoint"
            with pytest.raises(job_client.JobManagerError):
                client.ping(sock)
            # A second manager for the same jobs dir never becomes a writer.
            second = start_entry(base)
            _, err = second.communicate(timeout=30)
            assert second.returncode == entry.EX_TEMPFAIL, err
            assert "busy=True" in err
            assert child.poll() is None and alive(leader)
            assert "exit_code" not in meta_of(jobs, job_id)
            sock.unlink()  # the operator removes the debris: rebind proceeds
            client, pong = ping_when_ready(sock, child)
            assert (pong["pid"], pong["owner_instance_id"]) == (child.pid, me)
            assert pong["running_jobs"] == 1
            assert client.stop(sock, job_id)["state"] == "exited"
            err = finish(child, sock, me)
            assert "code=ipc_stale_endpoint_refused" in err
        finally:
            reap_exact(child, second)


@NATIVE
def test_overlong_socket_path_fails_closed_before_any_lease():
    long_root = Path("/tmp").resolve() / ("r6-r6-d21-a1-" + "x" * 80)
    with manager_home(socket=long_root / "jobs.sock") as (base, sock, jobs):
        child = start_entry(base)
        try:
            _, err = child.communicate(timeout=30)
            assert child.returncode == entry.EX_CONFIG, err
            size = len(os.fsencode(sock))
            assert f"darwin_socket_path_too_long: {size} bytes > 103" in err
            assert not long_root.exists() and not jobs.exists()
        finally:
            reap_exact(child)


def test_sun_path_boundary_and_a_space_in_the_path():
    base = Path("/tmp/Application Support/Binnacle")
    room = entry.SUN_PATH_MAX - 1 - len(os.fsencode(base / "r3")) - 1
    fits = base / "r3" / ("j" * room)
    assert len(os.fsencode(fits)) == 103
    entry.require_socket_path(fits)  # 103 bytes + NUL fills sun_path exactly
    entry.require_socket_path(base / "r3" / "jobs.sock")
    with pytest.raises(
        ValueError, match=r"darwin_socket_path_too_long: 104 bytes > 103"
    ):
        entry.require_socket_path(fits.with_name(fits.name + "j"))
    with pytest.raises(NativeCapabilityError):
        entry.require_socket_path(Path("relative") / "jobs.sock")


class FakeManager:
    def __init__(self, running: int) -> None:
        self.running = running

    def job_counts(self) -> tuple[int, int]:
        return self.running, 0

    def handle(self, payload):
        return {"ok": True}


def scripted_serving(monkeypatch, failures: int):
    """serve_authenticated fails ``failures`` times, then serves until stopped."""
    import binnacle.platform.darwin.ipc_transport as transport

    leases: list[object] = []

    def serve(socket_path, *, lease, handler, stop):
        leases.append(lease)
        if len(leases) <= failures:
            raise denied("runtime_root_unsafe")  # e.g. the root was removed
        stop.set()

    monkeypatch.setattr(transport, "serve_authenticated", serve)
    monkeypatch.setattr(entry, "REBIND_DELAY_S", (0.0, 0.0))
    fresh = iter(range(1, 100))
    monkeypatch.setattr(entry, "fresh_lease", lambda *_: f"fresh-{next(fresh)}")
    return leases


class Lease:
    label = "com.binnacle.r3test.d1.manager"


def test_owned_jobs_turn_every_endpoint_loss_into_a_rebind(monkeypatch, tmp_path):
    leases = scripted_serving(monkeypatch, failures=3)
    first, stop = Lease(), threading.Event()
    entry.serve_endpoint(
        FakeManager(running=1),
        socket_path=tmp_path / "jobs.sock",
        lease=first,
        stop=stop,
    )
    assert leases == [first, "fresh-1", "fresh-2", "fresh-3"] and stop.is_set()


def test_first_binding_failure_without_jobs_keeps_the_startup_contract(
    monkeypatch, tmp_path
):
    """No owned job: the startup error propagates (non-zero; launchd restarts)."""
    leases = scripted_serving(monkeypatch, failures=1)
    with pytest.raises(NativeCapabilityError, match="runtime_root_unsafe"):
        entry.serve_endpoint(
            FakeManager(running=0),
            socket_path=tmp_path / "jobs.sock",
            lease=Lease(),
            stop=threading.Event(),
        )
    assert len(leases) == 1


def test_a_set_stop_is_never_turned_into_a_rebind(monkeypatch, tmp_path):
    leases = scripted_serving(monkeypatch, failures=1)
    stop = threading.Event()
    stop.set()
    with pytest.raises(NativeCapabilityError):
        entry.serve_endpoint(
            FakeManager(running=1),
            socket_path=tmp_path / "jobs.sock",
            lease=Lease(),
            stop=stop,
        )
    assert len(leases) == 1
