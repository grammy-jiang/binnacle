"""Darwin manager emits Linux-comparable, single terminal telemetry events."""

from __future__ import annotations

import json
import logging
import time

from binnacle.platform.contracts.process_contracts import OwnedJobExit
from binnacle.platform.darwin.job_manager_service import DarwinJobManager


class Owner:
    owner_instance_id = "0123456789abcdef0123456789abcdef"

    def __init__(self):
        self.releases = []

    def release(self, job_id):
        self.releases.append(job_id)


def test_durable_exit_event_is_complete_and_not_duplicated(tmp_path, caplog):
    owner = Owner()
    manager = DarwinJobManager(
        owner=owner, jobs_dir=tmp_path, boot_id="boot", wait_max_s=30, keep_newest=10
    )
    job = tmp_path / "aaaabbbbcccc"
    job.mkdir()
    (job / "out.log").write_bytes(b"ok\n")
    (job / "meta.json").write_text(
        json.dumps(
            {
                "command": "echo ok",
                "workdir": "/tmp",
                "pid": 123,
                "started_at": time.time() - 2,
                "call_id": "call1",
                "owner": "manager",
                "owner_instance_id": owner.owner_instance_id,
                "boot_id": "boot",
                "command_hash": "b" * 12,
            }
        )
    )
    exit = OwnedJobExit(job.name, 0, None, "normal_exit")
    with caplog.at_level(logging.INFO, logger="binnacle.job_manager"):
        assert manager.record_exit(exit) is True
        assert manager.record_exit(exit) is True
    events = [
        r.getMessage()
        for r in caplog.records
        if "event=job_exit job_id=" in r.getMessage()
    ]
    assert len(events) == 1
    for field in (
        "exit_code=0",
        "signal=None",
        "reason=normal_exit",
        "runtime_s=",
        "log_bytes=3",
        "call=call1",
        "owner=manager",
        "owner_instance=0123456789ab",
        "command_hash=bbbbbbbbbbbb",
    ):
        assert field in events[0]
    assert json.loads((job / "meta.json").read_text())["exit_code"] == 0
