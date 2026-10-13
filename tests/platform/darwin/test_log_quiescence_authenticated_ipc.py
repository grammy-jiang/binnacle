"""Issue #30: real native authenticated IPC with a synthetic Manager only.

The tests neither connect to Binnacle's installed Jobs socket nor call
launchctl; all server/lease credentials are newly created under a private
temporary root owned by this pytest process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from binnacle.platform.darwin.job_manager_client import (
    DarwinJobClient,
    DarwinJobManagerError,
)
from binnacle.platform.darwin.job_manager_maintenance_fence import ManagerStartFence
from tests.platform.darwin.test_ipc_generation import LABEL, serving
from tests.platform.darwin.test_job_manager_maintenance_fence import (
    NONCE,
    _manager,
    _write,
)


@pytest.fixture
def runtime():
    # Same private, short named AF_UNIX root as the established A3 test
    # suite; never resolves or touches the installed Binnacle jobs.sock.
    with tempfile.TemporaryDirectory(
        prefix="bna3-issue30-", dir=Path(tempfile.gettempdir()).resolve()
    ) as value:
        yield Path(value)


NATIVE = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="A3 private getpeereid/LOCAL_PEERPID authenticated Mac fixture only",
)


def _manager_with_fenced_ping(tmp_path: Path):
    manager, owner, pause_root = _manager(tmp_path)
    fence = ManagerStartFence(
        pause_root, owner_instance_id=owner.owner_instance_id, pid=os.getpid()
    )
    manager.maintenance_fence = fence.refusal
    manager.maintenance_probe = lambda reply: fence.synchronized_ping(manager, reply)
    return manager, owner, pause_root


@NATIVE
def test_actual_authenticated_channel_reports_pause_and_refuses_start(
    tmp_path: Path, runtime: Path
) -> None:
    manager, owner, pause_root = _manager_with_fenced_ping(tmp_path)
    with serving(runtime, handler=manager.handle) as (_lease, _calls, errors):
        client = DarwinJobClient(label=LABEL)
        sock = runtime / "jobs.sock"
        before = client.ping(sock)
        assert before["maintenance_admission"] == {"state": "absent", "nonce": None}
        with manager._transaction():
            _write(pause_root, owner.owner_instance_id)
        after = client.ping(sock)
        assert after["ok"] is True
        assert after["maintenance_admission"] == {"state": "paused", "nonce": NONCE}
        assert after["running_jobs"] == after["unknown_jobs"] == 0
        assert after["owner_instance_id"] == owner.owner_instance_id
        assert after["pid"] == os.getpid()
        with pytest.raises(DarwinJobManagerError, match="maintenance"):
            client.start(
                sock,
                command="synthetic-but-must-not-run",
                workdir=tmp_path,
                stdin=None,
                wait_seconds=0,
                call_id="fixture",
            )
        assert owner.spawned == []
    assert errors == []


@NATIVE
def test_separate_python_process_gets_only_authenticated_pause_receipt(
    tmp_path: Path, runtime: Path
) -> None:
    manager, owner, pause_root = _manager_with_fenced_ping(tmp_path)
    with serving(runtime, handler=manager.handle) as (_lease, _calls, errors):
        with manager._transaction():
            _write(pause_root, owner.owner_instance_id)
        code = (
            "import json,sys\n"
            "from pathlib import Path\n"
            "from binnacle.platform.darwin.job_manager_client import DarwinJobClient\n"
            "reply=DarwinJobClient(label=sys.argv[2]).ping(Path(sys.argv[1]))\n"
            "print(json.dumps({k: reply.get(k) for k in ('ok','pid','owner_instance_id',"
            "'maintenance_admission','running_jobs','unknown_jobs')},sort_keys=True))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(runtime / "jobs.sock"), LABEL],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        reply = json.loads(result.stdout)
        assert reply["maintenance_admission"] == {"state": "paused", "nonce": NONCE}
        assert reply["owner_instance_id"] == owner.owner_instance_id
        assert reply["pid"] == os.getpid()
        assert reply["running_jobs"] == reply["unknown_jobs"] == 0
    assert errors == []


@NATIVE
def test_corrupt_request_never_claims_authenticated_pause_receipt(
    tmp_path: Path, runtime: Path
) -> None:
    manager, owner, pause_root = _manager_with_fenced_ping(tmp_path)
    with serving(runtime, handler=manager.handle) as (_lease, _calls, errors):
        marker = pause_root / "request.json"
        marker.write_text('{"bogus":true}')
        marker.chmod(0o600)
        reply = DarwinJobClient(label=LABEL).ping(runtime / "jobs.sock")
        assert reply["maintenance_admission"] == {"state": "unknown", "nonce": None}
        with pytest.raises(DarwinJobManagerError, match="maintenance state unknown"):
            DarwinJobClient(label=LABEL).start(
                runtime / "jobs.sock",
                command="synthetic",
                workdir=tmp_path,
                stdin=None,
                wait_seconds=0,
                call_id="fixture",
            )
        assert owner.spawned == []
    assert errors == []


@NATIVE
def test_unrecognized_management_op_cannot_unpause_manager(
    tmp_path: Path, runtime: Path
) -> None:
    manager, owner, pause_root = _manager_with_fenced_ping(tmp_path)
    with serving(runtime, handler=manager.handle) as (_lease, _calls, errors):
        with manager._transaction():
            _write(pause_root, owner.owner_instance_id)
        client = DarwinJobClient(label=LABEL)
        with pytest.raises(DarwinJobManagerError, match="unknown"):
            client.request(
                runtime / "jobs.sock",
                {"version": 1, "op": "maintenance_unpause", "nonce": NONCE},
            )
        reply = client.ping(runtime / "jobs.sock")
        assert reply["maintenance_admission"] == {"state": "paused", "nonce": NONCE}
        assert (pause_root / "request.json").is_file()
        assert owner.spawned == []
    assert errors == []


def test_no_manually_authorized_native_label_in_this_module() -> None:
    """Static contract prevents tests accidentally using a real label."""
    assert LABEL.startswith("com.binnacle.r3test.")
    assert LABEL not in {
        "system/com.binnacle.mcp",
        "system/com.binnacle.jobs",
        "system/com.binnacle.service-watchdog",
    }
