from __future__ import annotations

import json
from pathlib import Path

from binnacle import jobs


def test_manager_start_records_cgroup_and_job_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    seen: list[tuple[str, str | None]] = []
    monkeypatch.setattr(jobs.job_cgroup, "create", lambda job_id: f"/demo/job-{job_id}")

    def argv(command: str, cgroup: str | None):
        seen.append((command, cgroup))
        return ["bash", "-c", command]

    monkeypatch.setattr(jobs.job_cgroup, "launch_argv", argv)
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
    assert seen == [(meta["command"], f"/demo/job-{job_id}")]
    assert meta["cgroup"] == f"/demo/job-{job_id}"
    assert out == f"{job_id}:/demo/job-{job_id}"


def test_record_exit_persists_cgroup_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs.job_cgroup, "create", lambda job_id: f"/demo/job-{job_id}")
    monkeypatch.setattr(
        jobs.job_cgroup, "launch_argv", lambda command, cgroup: ["bash", "-c", command]
    )
    monkeypatch.setattr(
        jobs.job_cgroup,
        "snapshot",
        lambda cgroup: {"cpu": {"usage_usec": 1234}, "processes": 0},
    )
    cleaned: list[str | None] = []
    monkeypatch.setattr(
        jobs.job_cgroup,
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
