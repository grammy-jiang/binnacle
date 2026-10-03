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
        job_store,
        "read_meta",
        lambda root, job: {"schema_version": 2, "owner_instance_id": "old"},
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


def test_owner_uses_public_store_and_shared_lock(tmp_path, monkeypatch):
    from binnacle import job_owner, job_store

    assert jobs._STORE_LOCK is job_store.STORE_LOCK
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "public-store"
    (tmp_path / job_id).mkdir()
    record = {
        "command": "true",
        "workdir": "/tmp",
        "pid": 12,
        "started_at": 1,
        "schema_version": 2,
        "owner_instance_id": "old",
        "boot_id": "boot",
    }
    job_store.write_meta(tmp_path, job_id, record)

    def private(*args):
        raise AssertionError("owner reached private jobs storage")

    monkeypatch.setattr(jobs, "_read_meta", private)
    monkeypatch.setattr(jobs, "_write_meta", private)
    job_owner.mark_stop_requested(job_id)
    assert job_store.read_meta(tmp_path, job_id)["stop_requested"] is True
    assert job_owner.recover_previous_owner("new", "different-boot") == 1
    final = job_store.read_meta(tmp_path, job_id)
    assert final["termination_reason"] == "stop_requested"
    assert final["exit_code"] is None and final["signal"] is None
    state = {"state": "exited"}
    monkeypatch.setattr(jobs, "job_state", lambda job: state)
    assert job_owner.stop_job(job_id) is state


def test_shared_store_lock_covers_prune_launch_and_publication(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from binnacle import job_store

    assert jobs._STORE_LOCK is job_store.STORE_LOCK
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    events = []

    def unavailable_to_other_thread():
        acquired = job_store.STORE_LOCK.acquire(blocking=False)
        if acquired:
            job_store.STORE_LOCK.release()
        return not acquired

    with ThreadPoolExecutor(max_workers=1) as pool:

        def check(phase):
            assert pool.submit(unavailable_to_other_thread).result(timeout=2)
            events.append(phase)

        real_prune = jobs._prune
        real_write = job_store.write_meta

        def prune(reserve=0):
            check("prune")
            real_prune(reserve)

        def launch(*args, **kwargs):
            check("launch")
            return SimpleNamespace(pid=71, returncode=0)

        def write(root, job, meta):
            check("publish")
            real_write(root, job, meta)

        monkeypatch.setattr(jobs, "_prune", prune)
        monkeypatch.setattr(
            jobs,
            "_PROCESS_BACKEND",
            SimpleNamespace(launch=launch, starttime=lambda pid: 99),
        )
        monkeypatch.setattr(job_store, "write_meta", write)
        job_id, _ = jobs.start_job("fake", tmp_path, None)
        assert job_store.read_meta(jobs.JOBS_DIR, job_id)["starttime"] == 99
        assert events == ["prune", "launch", "publish"]
        assert not pool.submit(unavailable_to_other_thread).result(timeout=2)
