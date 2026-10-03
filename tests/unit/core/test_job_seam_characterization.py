"""Deterministic lifecycle boundaries needed before command extraction."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import job_owner, job_resource_history, job_store, jobs


def test_positive_wait_bridges_process_death_until_recorded_exit(monkeypatch):
    terminal = {"state": "exited", "exit_code": 7, "signal": None}
    states = iter([{"state": "running"}, {"state": "unknown"}, terminal])
    delays = []
    monkeypatch.setattr(jobs, "job_state", lambda job: next(states))
    monkeypatch.setattr(
        jobs,
        "time",
        SimpleNamespace(monotonic=lambda: sum(delays), sleep=delays.append),
    )
    assert jobs.await_exit("fixed", 1) is terminal
    assert delays == [0.02, 0.03]


def test_zero_wait_may_honestly_report_unknown(monkeypatch):
    transient = {"state": "unknown"}
    monkeypatch.setattr(jobs, "job_state", lambda job: transient)
    assert jobs.await_exit("fixed", 0) is transient


@pytest.mark.parametrize("timeout", [False, True])
def test_embedded_wait_only_hands_off_after_timeout(monkeypatch, timeout):
    calls = []

    class Process:
        def wait(self, timeout):
            calls.append(("wait", timeout))
            if timeout and should_timeout:
                raise subprocess.TimeoutExpired("probe", timeout)
            return 0

    should_timeout = timeout
    proc = Process()
    monkeypatch.setattr(jobs, "OWNER_MODE", "embedded")
    monkeypatch.setattr(jobs, "start_job", lambda *args: ("fixed", proc))
    monkeypatch.setattr(
        jobs, "record_exit", lambda *args: calls.append(("record", args))
    )
    monkeypatch.setattr(
        jobs, "reap_in_background", lambda *args: calls.append(("reap", args))
    )
    assert job_owner.start_and_wait("probe", Path("/tmp"), None, 0.25) == "fixed"
    assert calls == [("wait", 0.25), ("reap" if timeout else "record", ("fixed", proc))]


def test_manager_record_routes_stop_with_embedded_default(monkeypatch):
    from binnacle import job_client

    terminal = {"state": "exited", "exit_code": None, "signal": 15}
    states = iter([{"state": "running"}, terminal, terminal])
    calls = []
    monkeypatch.setattr(jobs, "OWNER_MODE", "embedded")
    monkeypatch.setattr(jobs, "job_state", lambda job: next(states))
    monkeypatch.setattr(
        jobs,
        "_read_meta",
        lambda job: {"schema_version": 2, "owner_instance_id": "old"},
    )
    monkeypatch.setattr(
        job_client, "stop", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    assert job_owner.stop_job("fixed") is terminal
    assert job_owner.stop_job("fixed") is terminal
    assert len(calls) == 1


def test_resource_merge_accepts_exact_four_fields_only():
    current = {"state": "exited", "exit_code": 7, "cgroup_cleanup_pending": True}
    final = {
        "state": "running",
        "exit_code": 0,
        "cleanup_pending": True,
        "resource_usage": {"processes": 0},
        "resource_history_path": "/history",
        "resource_finalized_at": 12,
        "cgroup_cleanup_pending": True,
    }
    merged = job_resource_history.merge_final_meta(current, final)
    assert merged == {
        "state": "exited",
        "exit_code": 7,
        "cgroup_cleanup_pending": True,
        "resource_usage": {"processes": 0},
        "resource_history_path": "/history",
        "resource_finalized_at": 12,
    }


def test_finalizer_callback_does_not_recreate_pruned_record(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._save_final_resource_meta("pruned", {"cgroup_cleanup_pending": True})
    assert list(tmp_path.iterdir()) == []


def test_each_atomic_write_uses_distinct_complete_temporary_file(tmp_path, monkeypatch):
    (tmp_path / "fixed").mkdir()
    observed = []
    replace = job_store.os.replace

    def record(src, dst):
        observed.append((Path(src).name, Path(src).read_text()))
        replace(src, dst)

    monkeypatch.setattr(job_store.os, "replace", record)
    for value in (1, 2):
        job_store.write_meta(tmp_path, "fixed", {"value": value})
    assert observed[0][0] != observed[1][0]
    assert [text for _, text in observed] == ['{"value": 1}', '{"value": 2}']
    assert [path.name for path in (tmp_path / "fixed").iterdir()] == ["meta.json"]
