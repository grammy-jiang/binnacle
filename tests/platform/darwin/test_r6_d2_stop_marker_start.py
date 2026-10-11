"""r6 D2 (J7-FOLLOWUP-stop-marker-start-refusal): no start into a pending stop.

While the provisioner's quiet-window stop marker names the serving incarnation,
``start`` is refused with a typed, retryable reply whose text is the existing
manager-unavailable class, and no job record is created. A marker naming
another incarnation, or none at all, leaves ``start`` working.
"""

from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.features.commands import job_client
from binnacle.platform.composition import create_job_client
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_entry as entry
from tests.platform.darwin.test_durable_tool_wiring import _manager, _run
from tests.platform.darwin.test_job_manager_entry import MODULE, ping_when_ready
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    req,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")


def write_marker(marker: Path, owner_instance_id: str, mode: int = 0o600) -> None:
    marker.write_text(json.dumps({"owner_instance_id": owner_instance_id}))
    marker.chmod(mode)


def start_entry(base: Path) -> subprocess.Popen[str]:
    env = {"BINNACLE_CONFIG_FILE": str(base / "config.toml"), "HOME": str(base)}
    env["PATH"] = f"{base / 'bin'}:/usr/bin:/bin"
    argv = [sys.executable, "-m", MODULE]
    pipe = subprocess.PIPE
    return subprocess.Popen(
        argv, env=env, cwd=base, stdout=pipe, stderr=pipe, text=True
    )


def job_dirs(jobs: Path) -> list[str]:
    return sorted(p.name for p in jobs.iterdir() if p.is_dir()) if jobs.exists() else []


@pytest.fixture
def reaped(tmp_path):
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    yield owner, manager
    halt.set()
    reaper.join()
    manager.close()


def test_pending_stop_refuses_start_typed_and_writes_no_record(reaped):
    owner, manager = reaped
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        base = Path(value).resolve()  # private 0700 runtime root
        sock, jobs = base / "jobs.sock", manager.jobs_dir
        manager.stop_pending = lambda: entry.stop_pending_refusal(
            sock, owner.owner_instance_id
        )
        write_marker(sock.with_name("jobs.sock.stop"), owner.owner_instance_id)
        reply = manager.handle(req(base, "echo never"))
        assert reply == {
            "ok": False,
            "error": f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: manager_stopping",
            "code": entry.STOP_PENDING_CODE,
            "retryable": True,
        }
        assert job_dirs(jobs) == [] and owner.live == owner.exits == {}
        sock.with_name("jobs.sock.stop").unlink()
        assert manager.handle(req(base, "true", wait=5))["ok"] is True
        assert len(job_dirs(jobs)) == 1


@NATIVE
def test_entry_refuses_start_only_while_its_own_marker_exists(tmp_path):
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        (base / "bin").mkdir()
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        (base / "config.toml").write_text(
            f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        )
        marker = sock.with_name("jobs.sock.stop")
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            me = pong["owner_instance_id"]
            kw = {"workdir": base, "stdin": None, "call_id": "d2"}
            # Marker absent: start works.
            done = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert done["state"] == "exited"
            before = job_dirs(jobs)
            # Another incarnation's or a non-private marker: not ours, ignored.
            for owner_id, mode in (("previous-incarnation", 0o600), (me, 0o644)):
                write_marker(marker, owner_id, mode)
                extra = client.start(sock, command="exit 0", wait_seconds=10, **kw)
                assert extra["state"] == "exited"
                before = job_dirs(jobs)
                marker.unlink()
            # Our own marker: typed retryable refusal, no record, still serving.
            write_marker(marker, me)
            with pytest.raises(job_client.JobManagerError) as refused:
                client.start(sock, command="echo never", wait_seconds=0, **kw)
            assert str(refused.value) == (
                f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: {entry.STOP_PENDING_CODE}"
            )
            assert job_dirs(jobs) == before
            assert client.ping(sock)["running_jobs"] == 0
            assert marker.exists()  # the peek never consumes the provisioner's marker
            # MCP side: run_command shows the existing manager-unavailable text.
            settings, root, backend = _manager(tmp_path, client=create_job_client())
            backend._socket_path = sock
            unavailable = rf"{pc.JOB_MANAGER_UNAVAILABLE} at {re.escape(str(sock))}: "
            with pytest.raises(ToolError, match=unavailable + "manager_stopping"):
                _run(settings, root, backend, "echo never", 5)
            assert job_dirs(jobs) == before
            # Marker withdrawn: start works again in the same incarnation.
            marker.unlink()
            again = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert again["state"] == "exited" and again["job_id"] not in before
            # The quiet-window stop itself is unchanged: marker + TERM exits 0.
            write_marker(marker, me)
            child.send_signal(signal.SIGTERM)
            _, err = child.communicate(timeout=30)
            assert child.returncode == 0, err
            assert "reason=provisioner_quiet_window" in err
            assert "event=job_start_refused reason=stop_marker" in err
        finally:
            if child.poll() is None:  # our exact child only (RULE-NO-PKILL)
                child.kill()
                child.communicate(timeout=10)


def test_marker_peek_matches_the_consuming_reader():
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        sock = Path(value).resolve() / "jobs.sock"
        marker = sock.with_name("jobs.sock.stop")
        assert not entry.stop_marker_names(sock, "me")
        assert entry.stop_pending_refusal(sock, "me") is None
        write_marker(marker, "other")
        assert not entry.stop_marker_names(sock, "me") and marker.exists()
        write_marker(marker, "me")
        assert entry.stop_marker_names(sock, "me") and marker.exists()
        assert entry.provisioner_stop(sock, "me") and not marker.exists()
