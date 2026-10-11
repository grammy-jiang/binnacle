"""SD-43 JCRP-F1 E2E (J1g): a background member survives its leader's exit.

Through the J5 harness (real com.binnacle.jobs child, production composition
with test-only AVAILABLE rows): ``sleep 30 & echo done`` exits at once; the
``sleep`` keeps running like on Linux; job_status says exited with no
processes; stop_job returns the exited state and signals nothing; the
manager's SIGTERM close() then terminates the fenced group. The member is
identified by its exact recorded (pid, birth); teardown signals only that
verified record (RULE-NO-PKILL).
"""

import functools
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from binnacle.features.commands.tools import job_status as js
from binnacle.features.commands.tools import stop_job as sj
from binnacle.platform.darwin.process_authority import _process_records
from tests import signal_safety
from tests.platform.darwin.test_durable_manager_e2e import (
    _available_manager_backend,
    _ping_when_ready,
    _real_manager,
    _stop_manager,
)
from tests.platform.darwin.test_durable_tool_wiring import _run

_DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="real com.binnacle.jobs")


def _live_members(leader):
    return [m for m in _process_records(2, leader) if m.pid != leader and m.state != 5]


def _alive_exact(pid, birth):
    record = signal_safety.observe(pid)
    return record is not None and record.birth == birth and record.state != 5


@_DARWIN
def test_background_member_survives_leader_exit_like_linux(tmp_path):
    member = None
    try:
        with _real_manager() as (child, sock, jobs, log):
            settings, root, backend = _available_manager_backend(tmp_path, sock, jobs)
            _ping_when_ready(backend, child)
            run = functools.partial(_run, settings, root, backend)
            done = run("sleep 30 & echo done", 10).structured_content
            assert done["state"] == "exited" and done["exit_code"] == 0
            assert done["output"] == "done\n"
            record = backend.job_state(done["job_id"])
            assert record["termination_reason"] == "normal_exit"
            deadline = time.monotonic() + 5
            while not (members := _live_members(record["pid"])):
                assert time.monotonic() < deadline, "background member not found"
                time.sleep(0.02)
            (member,) = members
            time.sleep(0.5)
            assert _alive_exact(member.pid, member.birth)  # survived the leader
            status = js.job_status_impl(done["job_id"], 10, backend=backend)
            assert status.structured_content["state"] == "exited"
            assert status.structured_content["processes"] == []  # Linux: running only
            stopped = sj.stop_job_impl(done["job_id"], backend=backend)
            assert stopped.structured_content["state"] == "exited"
            assert _alive_exact(member.pid, member.birth)  # stop signalled nothing
            assert _stop_manager(child, sock) == 0, log.read_text()
            assert not _alive_exact(member.pid, member.birth)  # close() stopped it
            final = backend.job_state(done["job_id"])
            assert (final["exit_code"], final["termination_reason"]) == (
                0,
                "normal_exit",
            )
    finally:
        if member is not None and _alive_exact(member.pid, member.birth):
            signal_safety.kill_verified(member.pid, member.birth)


@_DARWIN
def test_job_status_lists_the_running_group_through_the_manager(tmp_path):
    """JCRP-F6: job_status.processes comes from the manager's verified group."""
    with _real_manager() as (child, sock, jobs, log):
        settings, root, backend = _available_manager_backend(tmp_path, sock, jobs)
        _ping_when_ready(backend, child)
        run = functools.partial(_run, settings, root, backend)
        job = run("sleep 30 & sleep 31; wait", 1).structured_content
        assert job["state"] == "running"
        leader = backend.job_state(job["job_id"])["pid"]
        deadline = time.monotonic() + 5
        while len(processes := backend.job_processes(job["job_id"])) < 3:
            assert time.monotonic() < deadline, processes
            time.sleep(0.05)
        status = js.job_status_impl(job["job_id"], 10, backend=backend)
        listed = status.structured_content["processes"]
        by_pid = {item["pid"]: item for item in listed}
        assert leader in by_pid and by_pid[leader]["state"] in {"R", "S"}
        commands = sorted(item.get("cmd", "") for item in listed)
        assert "sleep 30" in commands and "sleep 31" in commands
        assert all(item["ppid"] in {leader, child.pid} for item in listed)
        short = backend.job_processes(job["job_id"], max_cmd_chars=5)
        assert all(len(item.get("cmd", "")) <= 5 for item in short)
        stopped = sj.stop_job_impl(job["job_id"], backend=backend)
        assert stopped.structured_content["state"] == "exited"
        assert backend.job_processes(job["job_id"]) == []  # Linux: running only
        assert _stop_manager(child, sock) == 0, log.read_text()
    assert backend.job_processes(job["job_id"]) == []  # unreachable manager


def test_backend_job_processes_degrades_to_empty_without_the_manager():
    from binnacle.features.commands.command_backend import (
        DarwinManagerCommandBackend,
    )

    backend = object.__new__(DarwinManagerCommandBackend)
    backend._socket_path = "/nonexistent/jobs.sock"
    backend.client = mock.Mock(**{"processes.side_effect": RuntimeError("down")})
    assert backend.job_processes("abc") == []
    reply = {"ok": True, "processes": [{"pid": 1, "ppid": 0, "state": "S"}]}
    backend.client = mock.Mock(**{"processes.return_value": reply})
    assert backend.job_processes("abc", 7) == reply["processes"]
    backend.client.processes.assert_called_with(
        Path("/nonexistent/jobs.sock"), "abc", max_cmd_chars=7
    )
    backend.client = object()  # a client without the additive op
    assert backend.job_processes("abc") == []
