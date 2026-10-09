from __future__ import annotations

import json
from pathlib import Path

import pytest

from binnacle.features.commands import jobs
from binnacle.platform.contracts.resource_contracts import NoResourceAccounting


@pytest.fixture(autouse=True)
def fake_accounting(monkeypatch):
    class Accounting(NoResourceAccounting):
        pass

    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", Accounting())


def test_manager_start_records_cgroup_and_job_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    seen: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING, "create", lambda job_id: f"/demo/job-{job_id}"
    )

    def argv(command: list[str], cgroup: str | None):
        seen.append((command, cgroup))
        return command

    monkeypatch.setattr(jobs._RESOURCE_ACCOUNTING, "wrap_argv", argv)
    job_id, proc = jobs.start_job(
        'printf "%s:%s" "$BINNACLE_JOB_ID" "$BINNACLE_JOB_CGROUP"',
        Path("/tmp"),
        None,
        owner_instance_id="owner-a",
        boot_id="boot-a",
    )
    proc.wait(timeout=5)
    jobs.record_exit(job_id, proc)
    meta = json.loads((jobs.JOBS_DIR / job_id / "meta.json").read_text())
    out = (jobs.JOBS_DIR / job_id / "out.log").read_text()
    assert seen == [(["bash", "-c", meta["command"]], f"/demo/job-{job_id}")]
    assert meta["cgroup"] == f"/demo/job-{job_id}"
    assert out == f"{job_id}:/demo/job-{job_id}"


def test_record_exit_persists_cgroup_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING, "create", lambda job_id: f"/demo/job-{job_id}"
    )
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING, "wrap_argv", lambda command, cgroup: command
    )
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING,
        "snapshot",
        lambda cgroup: {"cpu": {"usage_usec": 1234}, "processes": 0},
    )
    cleaned: list[str | None] = []
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING,
        "cleanup",
        lambda cgroup: cleaned.append(cgroup) is None or True,
    )
    job_id, proc = jobs.start_job(
        "true", Path("/tmp"), None, owner_instance_id="owner-a", boot_id="boot-a"
    )
    proc.wait(timeout=5)
    jobs.record_exit(job_id, proc)
    state = jobs.job_state(job_id)
    assert state is not None
    assert state["resource_usage"] == {"cpu": {"usage_usec": 1234}, "processes": 0}
    history = tmp_path / "resource-jobs"
    rows = list(history.glob("*.jsonl"))
    assert len(rows) == 1
    row = json.loads(rows[0].read_text().splitlines()[-1])
    assert row["job_id"] == job_id
    assert row["command_hash"] == state["command_hash"]
    assert "command" not in row
    assert row["resources"]["cpu"]["usage_usec"] == 1234
    assert cleaned == [f"/demo/job-{job_id}"]


def test_record_exit_defers_history_when_descendant_keeps_cgroup_populated(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING, "create", lambda job_id: f"/demo/job-{job_id}"
    )
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING, "wrap_argv", lambda command, cgroup: command
    )
    monkeypatch.setattr(
        jobs._RESOURCE_ACCOUNTING,
        "snapshot",
        lambda cgroup: {"memory_peak": 100, "processes": 1},
    )
    monkeypatch.setattr(jobs._RESOURCE_ACCOUNTING, "cleanup", lambda cgroup: False)
    finalizers: list[tuple[str, str, dict]] = []

    def fake_finalize(job_id, cgroup, meta, *, accounting, history_root, on_finalized):
        assert accounting is jobs._RESOURCE_ACCOUNTING
        assert history_root == tmp_path / "resource-jobs"
        assert callable(on_finalized)
        finalizers.append((job_id, cgroup, meta))

    monkeypatch.setattr(jobs.job_resource_history, "finalize_async", fake_finalize)
    history_calls: list[object] = []
    monkeypatch.setattr(
        jobs.job_resource_history,
        "append_best_effort",
        lambda *args, **kwargs: history_calls.append(args) or "/unexpected",
    )

    job_id, proc = jobs.start_job(
        "true", Path("/tmp"), None, owner_instance_id="owner-a", boot_id="boot-a"
    )
    proc.wait(timeout=5)
    jobs.record_exit(job_id, proc)
    meta = json.loads((jobs.JOBS_DIR / job_id / "meta.json").read_text())
    assert meta["cgroup_cleanup_pending"] is True
    assert "resource_history_path" not in meta
    assert history_calls == []
    assert finalizers and finalizers[0][0] == job_id


def test_save_final_resource_meta_updates_only_resource_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    job_id = "012345abcdef"
    directory = jobs.JOBS_DIR / job_id
    directory.mkdir(parents=True)
    meta = {
        "command": "true",
        "workdir": "/tmp",
        "pid": 1,
        "started_at": 10.0,
        "ended_at": 11.0,
        "command_hash": "abc123",
        "cgroup_cleanup_pending": True,
    }
    (directory / "meta.json").write_text(json.dumps(meta))
    jobs._save_final_resource_meta(
        job_id,
        {
            "resource_usage": {"memory_peak": 4096},
            "resource_history_path": "/history/2026-09-30.jsonl",
            "resource_finalized_at": 12.0,
        },
    )
    got = json.loads((directory / "meta.json").read_text())
    assert got["command"] == "true"
    assert got["resource_usage"] == {"memory_peak": 4096}
    assert got["resource_history_path"] == "/history/2026-09-30.jsonl"
    assert got["resource_finalized_at"] == 12.0
    assert "cgroup_cleanup_pending" not in got
