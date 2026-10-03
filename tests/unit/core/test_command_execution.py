"""Run use cases consume only the supplied backend and policy."""

from pathlib import Path

import pytest

from binnacle import command_execution, job_owner, jobs
from binnacle.command_contracts import CommandFailure
from binnacle.config import RunCommandSettings
from tests.command_support import MemoryCommands


def test_run_backend_arguments_order_and_handoff_without_engine(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real engine reached")

    monkeypatch.setattr(job_owner, "start_and_wait", forbidden)
    monkeypatch.setattr(jobs, "job_state", forbidden)
    monkeypatch.setattr(jobs, "read_log", forbidden)
    backend = MemoryCommands()
    result = command_execution.run_command(
        "probe",
        Path("/tmp"),
        99,
        True,
        "input",
        backend=backend,
        settings=RunCommandSettings(wait_max_s=2),
    )
    assert backend.calls == [
        ("start", ("probe", Path("/tmp"), "input", 0.125)),
        ("state", "fixed"),
        ("log", "fixed"),
    ]
    assert result.payload == {
        "job_id": "fixed",
        "state": "running",
        "output": "ready\n",
        "truncated": False,
        "output_bytes": 6,
        "runtime_s": 3.0,
        "log_path": "/fake/out.log",
        "workdir": "/tmp",
        "background_job": True,
    }
    assert result.summary.startswith("Command started in background; job_id=fixed.")


def test_missing_state_retains_running_fallback():
    backend = MemoryCommands()
    backend.state = None
    reply = command_execution.run_command(
        "probe",
        Path("/tmp"),
        99,
        False,
        None,
        backend=backend,
        settings=RunCommandSettings(wait_max_s=2),
    )
    assert reply.payload["state"] == "running"
    assert reply.payload["output_bytes"] == reply.payload["runtime_s"] == 0
    assert reply.payload["log_path"] == ""
    assert reply.summary.startswith("Command still running after 2 s;")


def test_expected_launch_failure_is_domain_only(monkeypatch):
    backend = MemoryCommands()
    failure = OSError("disk")

    def fail(*args):
        raise failure

    monkeypatch.setattr(backend, "start_and_wait", fail)
    with pytest.raises(CommandFailure) as caught:
        command_execution.run_command(
            "probe",
            Path("/tmp"),
            1,
            False,
            None,
            backend=backend,
            settings=RunCommandSettings(),
        )
    assert str(caught.value) == "Could not start the job: disk. Run `binnacle doctor`."
    assert caught.value.__cause__ is failure
