"""R4 J4: the Darwin command tools end to end through the real com.binnacle.jobs.

Split from test_durable_tool_wiring.py (module size ratchet, R4 J4 STEER-10).
The manager runs as this module's own child process in a private /tmp/r4-*
runtime; only that exact child is ever signalled (RULE-NO-PKILL).
"""

import functools
import json
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.features.commands.tools import job_status as js
from binnacle.features.commands.tools import stop_job as sj
from binnacle.platform.contracts.process_contracts import JOB_MANAGER_UNAVAILABLE
from tests.platform.darwin.test_durable_tool_wiring import _app, _run, _settings, _tools

_DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="real com.binnacle.jobs")

# J2r frozen ping fields (jobs/J2r-a2/INTERFACE-FROZEN.md, D3).
PING_FIELDS = {"ok", "version", "owner_instance_id", "boot_id", "pid"}
PING_FIELDS |= {"package_version", "revision", "running_jobs", "unknown_jobs"}


@contextmanager
def _real_manager():
    """The real com.binnacle.jobs entry point; only its own child is signalled."""
    with tempfile.TemporaryDirectory(prefix="r4-j4e-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        toml = f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        (base / "config.toml").write_text(toml)
        env = {"BINNACLE_CONFIG_FILE": str(base / "config.toml"), "HOME": str(base)}
        env["PATH"] = "/usr/bin:/bin"
        argv = [sys.executable, "-m", "binnacle.platform.darwin.job_manager_service"]
        with open(base / "manager.log", "wb") as log:
            child = subprocess.Popen(argv, env=env, cwd=base, stdout=log, stderr=log)
        try:
            yield child, sock, jobs, base / "manager.log"
        finally:
            _stop_manager(child, sock)


def _stop_manager(child, sock):
    """RJ4-F3: marker and SIGTERM first, so close() reaps every owned group."""
    from binnacle.platform.composition import create_job_client

    if child.poll() is None:
        with suppress(RuntimeError, OSError):  # the marker needs a live ping
            owner = create_job_client().ping(sock)["owner_instance_id"]
            marker = sock.with_name("jobs.sock.stop")
            marker.write_text(json.dumps({"owner_instance_id": owner}))
            marker.chmod(0o600)
        child.send_signal(signal.SIGTERM)  # the fixture's own unreaped child
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=30)
    if child.poll() is None:
        child.kill()  # the exact child pid, only after close() had its chance
    return child.wait(timeout=30)


def _available_manager_backend(tmp_path, sock, jobs):
    """Production composition with test-only AVAILABLE rows (SD-16 item 3)."""
    from dataclasses import replace

    from binnacle.application import compose_native_tools
    from binnacle.platform.contracts import capability_contracts as cc
    from binnacle.platform.contracts import darwin_release_scope as drs

    scope = dict(drs.release_scope_for_owner("manager"))
    for tool in drs.COMMAND_TOOLS:
        available = cc.Capability(cc.CapabilityState.AVAILABLE, "test", tool)
        scope[tool] = replace(scope[tool], capability=available)
    settings, root = _settings(tmp_path)
    settings.jobs.dir, settings.jobs.socket_path = jobs, sock
    _, backend = compose_native_tools(
        settings=settings, release_scope=scope, owner="manager"
    )
    return settings, root, backend


def _ping_when_ready(backend, child):
    deadline = time.monotonic() + 30
    while True:
        try:
            return backend.client.ping(backend.socket_path)
        except RuntimeError:
            if child.poll() is not None or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


@_DARWIN
def test_tools_run_end_to_end_through_the_real_job_manager(tmp_path):
    """STEER-07 item 5: J4 tools -> DarwinJobClient -> com.binnacle.jobs -> J1."""
    with _real_manager() as (child, sock, jobs, log):
        settings, root, backend = _available_manager_backend(tmp_path, sock, jobs)
        assert type(backend.client).__name__ == "DarwinJobClient"
        assert backend.client.label == "com.binnacle.jobs"  # production label
        pong = _ping_when_ready(backend, child)
        assert PING_FIELDS <= set(pong) and pong["pid"] == child.pid
        assert (pong["version"], pong["running_jobs"], pong["unknown_jobs"]) == (
            1,
            0,
            0,
        )
        owner_id = pong["owner_instance_id"]

        run = functools.partial(_run, settings, root, backend)
        done = run("echo hi; exit 3", 10)
        payload = done.structured_content
        assert payload["state"] == "exited" and payload["exit_code"] == 3
        assert payload["output"] == "hi\n" and payload["background_job"] is False
        assert str(done.content).count("descendants_unverified=true") == 1
        status = js.job_status_impl(payload["job_id"], 10, backend=backend)
        assert status.structured_content["state"] == "exited"
        record = backend.job_state(payload["job_id"])  # the J2 spool record
        assert record["owner_instance_id"] == owner_id and record["owner"] == "manager"
        assert record["termination_reason"] == "normal_exit"
        tail = run("seq 1 20000", 30).structured_content  # PARITY-INVENTORY gap
        assert tail["state"] == "exited" and tail["truncated"] is True
        assert tail["output"].rstrip().endswith("\n20000")
        assert "elided" in tail["output"] and tail["background_job"] is False
        job = run("sleep 60", 1).structured_content
        assert job["state"] == "running" and job["background_job"] is True
        assert backend.client.ping(sock)["running_jobs"] == 1
        # An MCP restart is only a new client: a fresh composition reads the job.
        _, _, again = _available_manager_backend(tmp_path, sock, jobs)
        assert len(_tools(_app(settings, again))) == 8
        assert again.job_state(job["job_id"])["state"] == "running"
        stopped = sj.stop_job_impl(job["job_id"], backend=again).structured_content
        assert stopped["state"] == "exited" and stopped["signal"] == 15
        assert again.job_state(job["job_id"])["termination_reason"] == "stop_requested"
        assert again.job_processes(job["job_id"]) == []  # no pid adoption
        pong = backend.client.ping(sock)
        assert (pong["running_jobs"], pong["unknown_jobs"]) == (0, 0)
        with pytest.raises(ToolError, match="No job with id"):
            sj.stop_job_impl("0" * 12, backend=backend)
        # Provisioner quiet-window stop (ENTRY-CONTRACT): marker, then SIGTERM.
        assert _stop_manager(child, sock) == 0, log.read_text()
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        run("echo after", 5)  # no embedded fallback once the manager is gone
