from __future__ import annotations

import json

from binnacle import job_resource_history


def test_history_is_daily_privacy_minimal_jsonl(tmp_path):
    meta = {
        "command": "secret payload",
        "workdir": "/tmp/demo",
        "command_hash": "abc123",
        "started_at": 100.0,
        "ended_at": 101.0,
        "exit_code": 0,
        "termination_reason": "normal_exit",
    }
    path = job_resource_history.append(
        tmp_path, "012345abcdef", meta, {"memory_peak": 4096}, retention_days=365
    )
    row = json.loads(path.read_text())
    assert row["schema_version"] == 1
    assert row["job_id"] == "012345abcdef"
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
