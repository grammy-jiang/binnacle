from __future__ import annotations

import json

import pytest

from binnacle.features.commands import job_resource_history
from binnacle.platform.contracts.resource_contracts import NoResourceAccounting


@pytest.fixture
def accounting():
    class Accounting(NoResourceAccounting):
        pass

    return Accounting()


def test_history_is_daily_privacy_minimal_jsonl(tmp_path):
    meta = {
        "command": "secret payload",
        "workdir": "/tmp/demo",
        "command_hash": "abc123",
        "call_id": "call-123",
        "started_at": 100.0,
        "ended_at": 101.0,
        "exit_code": 0,
        "termination_reason": "normal_exit",
    }
    path = job_resource_history.append(
        tmp_path, "012345abcdef", meta, {"memory_peak": 4096}, retention_days=365
    )
    row = json.loads(path.read_text())
    assert row["schema_version"] == 2
    assert row["job_id"] == "012345abcdef"
    assert row["call_id"] == "call-123"
    assert row["workdir"] == "/tmp/demo"
    assert row["resources"] == {"memory_peak": 4096}
    assert "command" not in row


def test_prune_runs_once_per_day_and_removes_expired_files(tmp_path, monkeypatch):
    old = tmp_path / "2020-01-01.jsonl"
    recent = tmp_path / "2026-09-30.jsonl"
    old.write_text("old\n")
    recent.write_text("new\n")
    monkeypatch.setattr(job_resource_history, "_last_prune_day", None)
    monkeypatch.setattr(job_resource_history.time, "time", lambda: 2_000_000_000.0)
    # Make one file older than the retention cutoff and one newer.
    import os

    os.utime(old, (1_000_000_000.0, 1_000_000_000.0))
    os.utime(recent, (2_000_000_000.0, 2_000_000_000.0))
    job_resource_history._prune(tmp_path, "2099-01-01", retention_days=1)
    assert not old.exists()
    assert recent.exists()

    # A second call for the same day is deliberately a no-op.
    recent.unlink()
    job_resource_history._prune(tmp_path, "2099-01-01", retention_days=1)
    assert not recent.exists()


def test_prune_tolerates_per_file_stat_failure(tmp_path, monkeypatch):
    path = tmp_path / "2020-01-01.jsonl"
    path.write_text("x\n")
    monkeypatch.setattr(job_resource_history, "_last_prune_day", None)
    original = type(path).stat

    def fail_one(self, *args, **kwargs):
        if self == path:
            raise OSError("synthetic")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "stat", fail_one)
    job_resource_history._prune(tmp_path, "2099-01-02", retention_days=1)
    assert path.read_text() == "x\n"


def test_append_best_effort_success_and_failure(tmp_path, monkeypatch, caplog):
    meta = {"ended_at": 100.0}
    got = job_resource_history.append_best_effort(
        tmp_path, "012345abcdef", meta, {"memory_peak": 1}
    )
    assert got is not None and got.endswith(".jsonl")

    monkeypatch.setattr(
        job_resource_history,
        "append",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk")),
    )
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        assert (
            job_resource_history.append_best_effort(
                tmp_path, "fedcba654321", meta, {"memory_peak": 2}
            )
            is None
        )
    assert "event=job_resource_history_error" in caplog.text


def test_merge_final_meta_removes_stale_pending_and_preserves_other_fields():
    current = {
        "command": "true",
        "cgroup_cleanup_pending": True,
        "resource_usage": {"memory_peak": 1},
    }
    got = job_resource_history.merge_final_meta(
        current,
        {
            "resource_usage": {"memory_peak": 2},
            "resource_finalized_at": 12.0,
        },
    )
    assert got["command"] == "true"
    assert got["resource_usage"] == {"memory_peak": 2}
    assert got["resource_finalized_at"] == 12.0
    assert "cgroup_cleanup_pending" not in got
    assert "resource_history_path" not in got


def test_finalize_async_waits_then_records_and_calls_back(
    tmp_path, monkeypatch, accounting
):
    job_id = "012345abcdef"
    cgroup = "/demo/job-012345abcdef"
    resources = {"memory_peak": 4096, "processes": 0}
    monkeypatch.setattr(accounting, "wait_empty", lambda cg: True)
    monkeypatch.setattr(accounting, "snapshot", lambda cg: resources)
    monkeypatch.setattr(accounting, "cleanup", lambda cg: True)
    monkeypatch.setattr(
        job_resource_history,
        "append_best_effort",
        lambda root, jid, meta, values: str(root / "2026-09-30.jsonl"),
    )
    callbacks: list[dict] = []

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            assert name == f"job-cgroup-{job_id}"
            assert daemon is True

        def start(self):
            self.target()

    monkeypatch.setattr(job_resource_history.threading, "Thread", ImmediateThread)
    job_resource_history.finalize_async(
        job_id,
        cgroup,
        {"cgroup_cleanup_pending": True, "ended_at": 11.0},
        accounting=accounting,
        history_root=tmp_path,
        on_finalized=callbacks.append,
    )
    assert len(callbacks) == 1
    final = callbacks[0]
    assert final["resource_usage"] == resources
    assert final["resource_history_path"].endswith("2026-09-30.jsonl")
    assert "resource_finalized_at" in final
    assert "cgroup_cleanup_pending" not in final


def test_finalize_async_preserves_pending_when_cleanup_fails(
    tmp_path, monkeypatch, accounting
):
    monkeypatch.setattr(accounting, "wait_empty", lambda cg: True)
    monkeypatch.setattr(accounting, "snapshot", lambda cg: {})
    monkeypatch.setattr(accounting, "cleanup", lambda cg: False)
    callbacks: list[dict] = []

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(job_resource_history.threading, "Thread", ImmediateThread)
    job_resource_history.finalize_async(
        "012345abcdef",
        "/demo/job-012345abcdef",
        {"cgroup_cleanup_pending": True},
        accounting=accounting,
        history_root=tmp_path,
        on_finalized=callbacks.append,
    )
    assert callbacks[0]["cgroup_cleanup_pending"] is True
    assert "resource_usage" not in callbacks[0]


def test_finalize_async_logs_when_event_wait_is_unavailable(
    tmp_path, monkeypatch, caplog, accounting
):
    monkeypatch.setattr(accounting, "wait_empty", lambda cg: False)
    callbacks: list[dict] = []

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(job_resource_history.threading, "Thread", ImmediateThread)
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        job_resource_history.finalize_async(
            "012345abcdef",
            "/demo/job-012345abcdef",
            {},
            accounting=accounting,
            history_root=tmp_path,
            on_finalized=callbacks.append,
        )
    assert callbacks == []
    assert "event=job_cgroup_finalizer_unavailable" in caplog.text


def test_history_resources_separates_final_gauges_from_cumulative_counters():
    raw = {
        "cpu": {"usage_usec": 123},
        "memory_current": 10,
        "memory_peak": 20,
        "memory_swap_current": 3,
        "memory_swap_peak": 5,
        "pids_current": 2,
        "pids_peak": 7,
        "processes": 2,
        "memory_events": {"oom_kill": 0},
        "memory_stat": {
            "anon": 100,
            "file": 200,
            "kernel": 30,
            "pagetables": 4,
            "pgfault": 50,
            "pgmajfault": 6,
            "pswpin": 7,
            "workingset_refault_file": 8,
        },
    }
    got = job_resource_history.history_resources(raw)
    assert got["memory_current_final"] == 10
    assert got["memory_swap_current_final"] == 3
    assert got["pids_current_final"] == 2
    assert got["processes_final"] == 2
    assert got["memory_peak"] == 20
    assert got["memory_swap_peak"] == 5
    assert got["pids_peak"] == 7
    assert got["memory_stat_final"] == {
        "anon": 100,
        "file": 200,
        "kernel": 30,
        "pagetables": 4,
    }
    assert got["memory_counters"] == {
        "pgfault": 50,
        "pgmajfault": 6,
        "pswpin": 7,
        "workingset_refault_file": 8,
    }
    assert "memory_stat" not in got
    assert "memory_current" not in got
    assert raw["memory_stat"]["anon"] == 100  # input is not mutated


def test_history_resources_is_idempotent_for_v2_shape():
    resources = {
        "memory_peak": 20,
        "memory_current_final": 10,
        "memory_stat_final": {"anon": 3},
        "memory_counters": {"pgfault": 4},
    }
    assert job_resource_history.history_resources(resources) == resources


def test_upgrade_v1_row_adds_call_id_and_v2_resource_semantics():
    old = {
        "schema_version": 1,
        "job_id": "012345abcdef",
        "workdir": "/tmp",
        "resources": {
            "memory_current": 10,
            "memory_peak": 20,
            "processes": 0,
            "memory_stat": {"anon": 0, "pgfault": 12},
        },
    }
    got = job_resource_history.upgrade_row(old, call_id="call-xyz")
    assert got["schema_version"] == 2
    assert got["call_id"] == "call-xyz"
    assert got["resources"] == {
        "memory_peak": 20,
        "memory_current_final": 10,
        "processes_final": 0,
        "memory_stat_final": {"anon": 0},
        "memory_counters": {"pgfault": 12},
    }
    assert old["schema_version"] == 1


def test_upgrade_v2_row_preserves_existing_call_id():
    row = {
        "schema_version": 2,
        "call_id": "original",
        "resources": {"memory_peak": 5, "memory_current_final": 0},
    }
    assert job_resource_history.upgrade_row(row, call_id="replacement") == row


def test_missing_call_id_is_serialized_as_null(tmp_path):
    path = job_resource_history.append(
        tmp_path,
        "012345abcdef",
        {"ended_at": 100.0, "call_id": "-"},
        {"memory_peak": 1},
    )
    assert json.loads(path.read_text())["call_id"] is None
