"""The bridge delegates unchanged values and never owns engine lifecycle."""

import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from binnacle import job_owner, jobs
from binnacle.command_backend import DurableCommandBackend
from binnacle.command_contracts import CommandReply
from binnacle.job_store import JobGone


@pytest.mark.parametrize(
    "module,name,args,value",
    [
        (job_owner, "start_and_wait", ("probe", Path("/tmp"), "in", 0.5), "fixed"),
        (job_owner, "stop_job", ("fixed",), {"old-key": None}),
        (jobs, "job_state", ("fixed",), {"unknown-key": 7}),
        (jobs, "list_jobs", (), [{"unknown-key": 7}]),
        (jobs, "await_exit", ("fixed", 0.5), None),
        (jobs, "read_log", ("fixed",), b"\xff"),
        (jobs, "read_log_range", ("fixed", 2, 8), (b"abc", 20)),
        (jobs, "job_processes", (42, 5), [{"pid": 42}]),
    ],
)
def test_delegate_keeps_arguments_identity_and_exceptions(
    monkeypatch, module, name, args, value
):
    calls = []

    def delegate(*received):
        calls.append(received)
        return value

    monkeypatch.setattr(module, name, delegate)
    backend = DurableCommandBackend()
    assert getattr(backend, name)(*args) is value
    assert calls == [args]
    failure = JobGone("fixed")

    def fail(*received):
        raise failure

    monkeypatch.setattr(module, name, fail)
    with pytest.raises(JobGone) as caught:
        getattr(backend, name)(*args)
    assert caught.value is failure


def test_properties_read_process_owned_values_without_caching(monkeypatch):
    backend = DurableCommandBackend()
    for owner, warmup, budget in [("embedded", 0.1, 10), ("manager", 0.2, 20)]:
        monkeypatch.setattr(jobs, "OWNER_MODE", owner)
        monkeypatch.setattr(jobs, "WARMUP_S", warmup)
        monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", budget)
        assert (backend.owner_mode, backend.warmup_s, backend.max_output_chars) == (
            owner,
            warmup,
            budget,
        )
    assert not hasattr(backend, "__dict__")


def test_reply_is_frozen_without_copying_or_normalizing_payload():
    payload = {"legacy": None}
    reply = CommandReply("summary", payload)
    assert reply.payload is payload
    with pytest.raises(FrozenInstanceError):
        reply.summary = "changed"


def test_constructing_backend_imports_no_engine_or_settings():
    code = """
import sys
from binnacle.command_backend import DurableCommandBackend
from binnacle.command_contracts import CommandReply
DurableCommandBackend()
assert not {"binnacle.config", "binnacle.jobs", "binnacle.job_owner",
            "binnacle.job_process", "binnacle.job_cgroup", "fastmcp", "mcp"} & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)


def test_default_selection_captures_engine_settings_before_first_operation():
    code = """
from binnacle import config
from binnacle.command_backend import create_command_backend
settings = config.get_settings().model_copy(deep=True)
settings.jobs.owner = "embedded"
settings.jobs.warmup_s = 0.125
config.get_settings = lambda: settings
backend = create_command_backend()
settings.jobs.owner = "manager"
settings.jobs.warmup_s = 0.5
assert backend.owner_mode == "embedded"
assert backend.warmup_s == 0.125
import sys
assert "binnacle.job_owner" in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)
