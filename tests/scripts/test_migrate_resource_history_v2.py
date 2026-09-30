from __future__ import annotations

import json

from scripts import migrate_resource_history_v2 as migration


def test_migrate_upgrades_rows_and_backs_up(tmp_path, monkeypatch):
    root = tmp_path / "resource-jobs"
    jobs = tmp_path / "jobs"
    root.mkdir()
    jobs.mkdir()
    path = root / "2026-09-30.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "012345abcdef",
                "started_at": 100.0,
                "resources": {
                    "memory_current": 5,
                    "memory_peak": 10,
                    "memory_stat": {"anon": 0, "pgfault": 3},
                },
            }
        )
        + "\n"
    )
    monkeypatch.setattr(
        migration, "_journal_calls", lambda unit, since: {"012345abcdef": "call-a"}
    )
    monkeypatch.setattr(migration, "_spool_calls", lambda jobs_dir: {})
    monkeypatch.setattr(migration.time, "strftime", lambda fmt: "STAMP")

    result = migration.migrate(root, jobs, "binnacle-jobs.service", dry_run=False)
    assert result == {"files": 1, "rows": 1, "changed": 1, "unresolved_call_ids": 0}
    row = json.loads(path.read_text())
    assert row["schema_version"] == 2
    assert row["call_id"] == "call-a"
    assert row["resources"]["memory_current_final"] == 5
    assert row["resources"]["memory_stat_final"] == {"anon": 0}
    assert row["resources"]["memory_counters"] == {"pgfault": 3}
    assert (root / "2026-09-30.jsonl.v1-backup-STAMP").exists()


def test_migrate_dry_run_does_not_rewrite(tmp_path, monkeypatch):
    root = tmp_path / "resource-jobs"
    jobs = tmp_path / "jobs"
    root.mkdir()
    jobs.mkdir()
    path = root / "2026-09-30.jsonl"
    original = (
        json.dumps({"schema_version": 1, "job_id": "fedcba654321", "resources": {}})
        + "\n"
    )
    path.write_text(original)
    monkeypatch.setattr(migration, "_journal_calls", lambda unit, since: {})
    monkeypatch.setattr(migration, "_spool_calls", lambda jobs_dir: {})

    result = migration.migrate(root, jobs, "binnacle-jobs.service", dry_run=True)
    assert result["changed"] == 1
    assert result["unresolved_call_ids"] == 1
    assert path.read_text() == original
    assert not list(root.glob("*.v1-backup-*"))
