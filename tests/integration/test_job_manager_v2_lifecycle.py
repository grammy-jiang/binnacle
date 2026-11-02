"""D1-B owner-first opt-in v2/v1 startup and crash/restart test.

Runs an *independent disposable Python Manager subprocess*. Neither its
sockets nor job store share any path with `binnacle-jobs.service`; no systemd
unit or production cgroup is modified. Active-job systemd restart is NOT proven.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from binnacle.features.commands import job_client
from tests.integration.test_job_manager_v2 import _pinned_fd, _request, _send

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Manager v2")

_WORKER = r"""
import signal,sys,threading
from pathlib import Path
from binnacle.features.commands import jobs
from binnacle.features.commands.job_manager import JobManager

root, run, store = map(Path, sys.argv[1:])
jobs.JOBS_DIR=store
runtime=JobManager(run/'legacy.sock',owner_instance_id='v2-restart-owner',
    boot_id=jobs._PROCESS_BACKEND.boot_id(),
    v2_socket_path=run/'start-v2.sock',v2_allowed_roots=(root,))
def terminate(_sig,_frame):
    threading.Thread(target=runtime.shutdown,daemon=True).start()
signal.signal(signal.SIGTERM,terminate)
runtime.serve_forever()
"""


def _launch(source: Path, root: Path, run: Path, store: Path):
    env = os.environ.copy()
    env.update(PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen(
        [sys.executable, "-c", _WORKER, str(root), str(run), str(store)],
        env=env,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(200):
        assert proc.poll() is None, "isolated Manager failed to start"
        try:
            if (
                job_client.ping(run / "legacy.sock")["version"] == 1
                and (run / "start-v2.sock").exists()
            ):
                return proc
        except (job_client.JobManagerError, FileNotFoundError, OSError):
            pass
        time.sleep(0.025)
    proc.kill()
    _, err = proc.communicate(timeout=3)
    pytest.fail(f"isolated v1/v2 sockets never became ready: {err[-500:]}")


def test_v1_and_v2_survive_manager_process_crash_with_one_durable_job(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "marker").write_text("ONE-OWNER-START\n")
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    store = tmp_path / "store"
    source = Path(__file__).resolve().parents[2] / "src"
    request = _request(root, call_id="persist-across-manager-process-crash")
    first = _launch(source, root, run, store)
    try:
        fd = _pinned_fd(root)
        try:
            response = _send(run / "start-v2.sock", request, (fd,))
        finally:
            os.close(fd)
        assert response["ok"] is True and response["state"] == "exited"
        job_id = response["job_id"]
        assert (store / job_id / "out.log").read_text() == "ONE-OWNER-START\n"
        # Simulates an abrupt crash. Both socket pathnames become stale.
        first.kill()
        assert first.wait(timeout=4) != 0
        assert (run / "legacy.sock").exists()
        assert (run / "start-v2.sock").exists()
        second = _launch(source, root, run, store)
        try:
            assert job_client.ping(run / "legacy.sock")["version"] == 1
            fd = _pinned_fd(root)
            try:
                replay = _send(run / "start-v2.sock", request, (fd,))
            finally:
                os.close(fd)
            assert replay["ok"] is True and replay["replayed"] is True
            assert replay["job_id"] == job_id
            assert {p.name for p in store.iterdir()} == {job_id}
        finally:
            second.terminate()
            _, err = second.communicate(timeout=5)
            assert second.returncode == 0, err[-500:]
            assert not (run / "start-v2.sock").exists()
            assert not (run / "legacy.sock").exists()
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=3)


def test_default_manager_exposes_only_legacy_v1_socket(tmp_path):
    from binnacle.features.commands.job_manager import JobManager

    runtime = JobManager(tmp_path / "legacy.sock")
    assert runtime.v2_socket_path is None and runtime.v2_allowed_roots is None
    assert runtime._v2_server is None
    with pytest.raises(ValueError, match="configured together"):
        JobManager(tmp_path / "legacy.sock", v2_socket_path=tmp_path / "v2.sock")
    with pytest.raises(ValueError, match="separate"):
        JobManager(
            tmp_path / "legacy.sock",
            v2_socket_path=tmp_path / "legacy.sock",
            v2_allowed_roots=(tmp_path,),
        )


def test_explicit_v2_settings_only_enable_opted_in_manager_path(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle.config import JobsSettings
    from binnacle.features.commands import job_manager

    assert JobsSettings().v2_socket_path is None
    root = tmp_path / "allowed"
    root.mkdir()
    v1 = tmp_path / "legacy.sock"
    v2 = tmp_path / "v2.sock"
    assert JobsSettings(v2_socket_path=v2).v2_socket_path == v2
    accepted = []

    class FakeManager:
        def __init__(self, socket_path, **kwargs):
            accepted.append((socket_path, kwargs))

        def serve_forever(self):
            accepted.append("served")

    monkeypatch.setattr(job_manager, "JobManager", FakeManager)
    monkeypatch.setattr(job_manager, "import_manager_modules", lambda **_kwargs: None)
    monkeypatch.setattr(
        job_manager,
        "get_settings",
        lambda: SimpleNamespace(
            jobs=SimpleNamespace(socket_path=v1, v2_socket_path=v2),
            roots=SimpleNamespace(canonical_allowed=(root,)),
        ),
    )
    job_manager.main()
    assert accepted == [
        (v1, {"v2_socket_path": v2, "v2_allowed_roots": (root,)}),
        "served",
    ]
