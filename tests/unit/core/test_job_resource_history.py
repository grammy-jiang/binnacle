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
