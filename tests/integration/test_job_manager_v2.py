"""D1-A: isolated real Python Manager v2 SCM_RIGHTS launch behavior.

All sockets, job stores and shell commands use tmp_path. The live manager
service/socket is never contacted. The separate v1 listener must remain intact.
"""

from __future__ import annotations

import array
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from binnacle.features.commands import job_client, jobs
from binnacle.features.commands.job_manager import JobManager
from binnacle.features.commands.job_manager_v2 import V2FDServer

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux SCM_RIGHTS")


@pytest.fixture()
def running_owner(tmp_path: Path, monkeypatch):
    roots = tmp_path / "allowed"
    roots.mkdir()
    (roots / "marker").write_text("AUTHORIZED_ONLY\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker").write_text("OUTSIDE_SENTINEL\n")
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    store = tmp_path / "store"
    monkeypatch.setattr(jobs, "JOBS_DIR", store)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    manager = JobManager(
        run / "legacy-v1.sock",
        owner_instance_id="isolated-v2-owner",
        boot_id=jobs._PROCESS_BACKEND.boot_id(),
    )
    v1_thread = threading.Thread(target=manager.serve_forever, daemon=True)
    v1_thread.start()
    for _ in range(200):
        try:
            assert job_client.ping(run / "legacy-v1.sock")["version"] == 1
        except (OSError, AssertionError, job_client.JobManagerError):
            time.sleep(0.005)
        else:
            break
    else:
        pytest.fail("isolated v1 manager failed to initialize")
    server = V2FDServer(run / "start-v2.sock", manager, (roots,))
    v2_thread = threading.Thread(target=server.serve_forever, daemon=True)
    v2_thread.start()
    try:
        yield manager, roots, outside, run, store
    finally:
        for record in jobs.list_jobs():
            if record["state"] == "running":
                try:
                    job_client.stop(run / "legacy-v1.sock", record["job_id"])
                except job_client.JobManagerError:
                    pass
        server.shutdown()
        server.server_close()
        v2_thread.join(timeout=4)
        assert not v2_thread.is_alive()
        assert not (run / "start-v2.sock").exists()
        manager.shutdown()
        v1_thread.join(timeout=4)
        assert not v1_thread.is_alive()


def _request(workdir: Path, **changes):
    request = {
        "version": 2,
        "op": "start",
        "workdir": str(workdir),
        "workdir_fd": True,
        "command": "cat marker",
        "stdin": None,
        "wait_seconds": 2.0,
        "call_id": "bounded-isolated-test",
    }
    request.update(changes)
    return request


def _send(path: Path, request: dict | bytes, fds: tuple[int, ...]):
    wire = (
        request if isinstance(request, bytes) else json.dumps(request).encode() + b"\n"
    )
    ancillary = (
        []
        if not fds
        else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))]
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(6)
        conn.connect(str(path))
        conn.sendmsg([wire], ancillary)
        data = bytearray()
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        assert data.endswith(b"\n"), data
        return json.loads(data)


def _pinned_fd(path: Path):
    return os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _record_ids(store: Path) -> set[str]:
    return {p.name for p in store.iterdir()} if store.exists() else set()


def test_v2_pinned_fd_starts_real_job_without_changing_v1(running_owner):
    _, root, _, run, store = running_owner
    descriptor = _pinned_fd(root)
    try:
        response = _send(run / "start-v2.sock", _request(root), (descriptor,))
    finally:
        os.close(descriptor)
    assert response["version"] == 2
    assert response["ok"] is True
    assert response["workdir_fd_accepted"] is True
    assert response["state"] == "exited"
    job = response["job_id"]
    assert len(job) == 12
    assert (store / job / "out.log").read_text() == "AUTHORIZED_ONLY\n"
    metadata = json.loads((store / job / "meta.json").read_text())
    assert metadata["workdir"] == str(root)
    assert "/proc/self/fd" not in metadata["workdir"]
    assert metadata["owner_instance_id"] == "isolated-v2-owner"
    assert metadata["call_id"] == "bounded-isolated-test"
    assert job_client.ping(run / "legacy-v1.sock")["version"] == 1
    v1 = job_client.start(
        run / "legacy-v1.sock",
        command="cat marker",
        workdir=root,
        stdin=None,
        wait_seconds=2,
        call_id="legacy-kept-working",
    )
    assert v1["ok"] and v1["job_id"] != job
    assert (store / v1["job_id"] / "out.log").read_text() == "AUTHORIZED_ONLY\n"


@pytest.mark.parametrize(
    "reason",
    [
        "missing_fd",
        "double_fd",
        "regular_fd",
        "outside_fd",
        "mismatched_fd",
        "version_one",
        "missing_key",
        "duplicate_json",
        "trailing_data",
    ],
)
def test_v2_invalid_descriptor_and_framing_never_launch(
    running_owner,
    reason: str,
):
    _, root, outside, run, store = running_owner
    start = _record_ids(store)
    file_fd = os.open(root / "marker", os.O_RDONLY)
    good = _pinned_fd(root)
    other = _pinned_fd(outside)
    try:
        request: dict | bytes = _request(root)
        fds = (good,)
        if reason == "missing_fd":
            fds = ()
        elif reason == "double_fd":
            fds = (good, good)
        elif reason == "regular_fd":
            fds = (file_fd,)
        elif reason == "outside_fd":
            fds = (other,)
        elif reason == "mismatched_fd":
            directory = root / "different"
            directory.mkdir()
            fds = (_pinned_fd(directory),)
        elif reason == "version_one":
            request = _request(root, version=1)
        elif reason == "missing_key":
            request = _request(root)
            del request["call_id"]
        elif reason == "duplicate_json":
            wire = json.dumps(_request(root))
            request = wire[:-1].encode() + b',"version":2}\n'
        elif reason == "trailing_data":
            request = json.dumps(_request(root)).encode() + b"\n{}\n"
        response = _send(run / "start-v2.sock", request, fds)
        assert response["version"] == 2 and response["ok"] is False
        assert "workdir_fd_accepted" not in response
        assert _record_ids(store) == start
        assert (outside / "marker").read_text() == "OUTSIDE_SENTINEL\n"
    finally:
        os.close(good)
        os.close(other)
        os.close(file_fd)
        if reason == "mismatched_fd":
            os.close(fds[0])


def test_v2_retarged_directory_cannot_run_outside_command(running_owner):
    _, root, outside, run, store = running_owner
    original = root / "sub"
    original.mkdir()
    (original / "marker").write_text("PINNED_SUB\n")
    fd = _pinned_fd(original)
    try:
        original.rename(root / "moved")
        original.symlink_to(outside, target_is_directory=True)
        response = _send(run / "start-v2.sock", _request(original), (fd,))
        assert response["ok"] is False
        assert not _record_ids(store)
        assert (outside / "marker").read_text() == "OUTSIDE_SENTINEL\n"
    finally:
        os.close(fd)


def test_v2_peer_credential_is_required_before_request_dispatch(
    running_owner,
):
    manager, root, _, run, store = running_owner
    path = run / "unauthorized-v2.sock"
    server = V2FDServer(path, manager, (root,), peer_uid=os.geteuid() + 1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fd = _pinned_fd(root)
        try:
            response = _send(path, _request(root), (fd,))
        finally:
            os.close(fd)
        assert response["ok"] is False
        assert not _record_ids(store)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_v2_requires_private_socket_parent_and_roots(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    runtime = JobManager(tmp_path / "ignored-v1.sock")
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)  # Fixture umask may otherwise silently make it 0700.
    with pytest.raises(ValueError, match="private"):
        V2FDServer(shared / "v2.sock", runtime, (root,))
    run = tmp_path / "private"
    run.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="authorized roots"):
        V2FDServer(run / "v2.sock", runtime, ())
