"""Exact pre-extraction replies, catch boundaries, and wait error telemetry."""

import pytest
from fastmcp.exceptions import ToolError

from binnacle import job_owner, jobs
from binnacle.callctx import current_call
from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.tools import job_status, run_command, stop_job


@pytest.mark.parametrize("code,signal", [(0, None), (7, None), (None, 15)])
def test_exact_finished_run_reply(tmp_path, monkeypatch, code, signal):
    calls = []
    monkeypatch.setattr(
        job_owner, "start_and_wait", lambda *args: calls.append(args) or "fixed"
    )
    monkeypatch.setattr(
        jobs,
        "job_state",
        lambda job: {
            "state": "exited",
            "exit_code": code,
            "signal": signal,
            "log_bytes": 3,
            "runtime_s": 0.125,
            "log_path": "/spool/out.log",
        },
    )
    monkeypatch.setattr(jobs, "read_log", lambda job: b"ok\n")
    result = run_command.run_command_impl(
        "probe",
        ".",
        99,
        False,
        "input",
        roots=RootsSettings(default_root=tmp_path),
        settings=RunCommandSettings(wait_max_s=2, auto_background_patterns={}),
    )
    assert calls == [("probe", tmp_path, "input", 2)]
    expected = {
        "job_id": "fixed",
        "state": "exited",
        "exit_code": code,
        "output": "ok\n",
        "truncated": False,
        "output_bytes": 3,
        "duration_s": 0.125,
        "log_path": "/spool/out.log",
        "workdir": str(tmp_path),
        "background_job": False,
    }
    if signal is not None:
        expected["signal"] = signal
    assert result.structured_content == expected
    prefix = (
        "Command killed by signal 15 after 0.125 s."
        if signal
        else f"Command exited {code} in 0.125 s."
    )
    assert result.content[0].text == prefix + (
        " It finished synchronously; no background job was created, so no "
        "job_status or stop_job is needed."
    )


@pytest.mark.parametrize("failure", [OSError("disk"), RuntimeError("owner")])
def test_run_error_preserves_original_cause(tmp_path, monkeypatch, failure):
    def fail(*args):
        raise failure

    monkeypatch.setattr(job_owner, "start_and_wait", fail)
    with pytest.raises(ToolError) as caught:
        run_command.run_command_impl(
            "probe",
            str(tmp_path),
            1,
            False,
            None,
            settings=RunCommandSettings(),
        )
    assert (
        str(caught.value)
        == f"Could not start the job: {failure}. Run `binnacle doctor`."
    )
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("failure", [ValueError("bug"), KeyboardInterrupt()])
def test_unexpected_run_failure_is_not_translated(tmp_path, monkeypatch, failure):
    def fail(*args):
        raise failure

    monkeypatch.setattr(job_owner, "start_and_wait", fail)
    with pytest.raises(type(failure)) as caught:
        run_command.run_command_impl("probe", str(tmp_path), 1, False, None)
    assert caught.value is failure


@pytest.mark.parametrize(
    "record,summary",
    [
        ({"state": "exited", "exit_code": 0, "signal": None}, "already exited 0"),
        ({"state": "exited", "exit_code": None, "signal": 15}, "stopped (signal 15)"),
        (
            {
                "state": "exited",
                "exit_code": None,
                "signal": None,
                "termination_reason": "owner_restart",
            },
            "was interrupted (owner_restart)",
        ),
        (
            {"state": "exited", "exit_code": None, "signal": None},
            "ended without a recorded exit status",
        ),
        (
            {"state": "unknown", "exit_code": None, "signal": None},
            "is in state unknown",
        ),
    ],
)
def test_exact_stop_reply(monkeypatch, record, summary):
    monkeypatch.setattr(job_owner, "stop_job", lambda job: record)
    result = stop_job.stop_job_impl("fixed")
    assert result.structured_content == {
        "job_id": "fixed",
        **{key: record[key] for key in ("state", "exit_code", "signal")},
    }
    assert result.content[0].text == f"Job fixed {summary}."


def test_stop_catch_boundary_and_unknown_cause(monkeypatch):
    failure = RuntimeError("owner")

    def fail(job):
        raise failure

    monkeypatch.setattr(job_owner, "stop_job", fail)
    with pytest.raises(ToolError) as caught:
        stop_job.stop_job_impl("fixed")
    assert str(caught.value) == "Could not stop the job: owner. Run `binnacle doctor`."
    assert caught.value.__cause__ is failure
    failure = OSError("unwrapped")
    with pytest.raises(OSError) as caught:
        stop_job.stop_job_impl("fixed")
    assert caught.value is failure
    monkeypatch.setattr(job_owner, "stop_job", lambda job: None)
    with pytest.raises(ToolError) as caught:
        stop_job.stop_job_impl("fixed")
    assert str(caught.value) == (
        "No job with id 'fixed'. Call job_status without a job_id to list recent jobs."
    )
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("failure", [RuntimeError("wait"), KeyboardInterrupt()])
def test_wait_exception_keeps_exact_timing_and_identity(monkeypatch, caplog, failure):
    ticks = iter(range(10, 18))
    monkeypatch.setattr(job_status, "_PERF_COUNTER", lambda: next(ticks))
    monkeypatch.setattr(jobs, "job_state", lambda job: {"log_bytes": 7})

    def fail(job, timeout):
        assert (job, timeout) == ("fixed", 2)
        raise failure

    monkeypatch.setattr(jobs, "await_exit", fail)
    token = current_call.set("characterize")
    try:
        with (
            caplog.at_level("INFO", logger="binnacle.job_status"),
            pytest.raises(type(failure)) as caught,
        ):
            job_status.job_status_impl(
                "fixed",
                10,
                9,
                quiet_after_s=10,
                history_limit=2,
                preview_chars=20,
                wait_max=2,
            )
    finally:
        current_call.reset(token)
    assert caught.value is failure
    assert [r.getMessage() for r in caplog.records] == [
        (
            "event=job_status_timing call=characterize job_id=fixed wait_requested_s=9 "
            "wait_bounded_s=2 wait_effective_s=2 waited_s=2 turn=- client=- "
            "dispatch_ms=na state_ms=4000.00 read_log_ms=na process_scan_ms=na "
            "impl_ms=6000.00 state=error processes=na log_bytes=7"
        )
    ]
