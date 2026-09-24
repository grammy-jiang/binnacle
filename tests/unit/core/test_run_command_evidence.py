import json
import stat
from datetime import datetime, timezone

from binnacle.run_command_evidence import load_evidence, record_auto_match


def _record(root, *, retention_days=14, day=25, now=None):
    return record_auto_match(
        retention_days=retention_days,
        call_id=f"call-{day}",
        client="openai-mcp",
        command=f"echo secret-{day}",
        command_hash=f"hash-{day}",
        policy_hash="policy",
        behavior_hash="behavior",
        semantics_version=1,
        auto_warmup_s=1.0,
        rule_hash="rule",
        match_start=5,
        match_end=11,
        root=root,
        now=now or datetime(2026, 9, day, 12, 0, tzinfo=timezone.utc),
    )


def test_evidence_disabled_writes_nothing(tmp_path):
    root = tmp_path / "evidence"
    assert _record(root, retention_days=0) is None
    assert not root.exists()


def test_evidence_normalizes_naive_timestamp_to_utc(tmp_path):
    root = tmp_path / "evidence"
    naive = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    path = _record(root, now=naive)

    assert path is not None
    assert load_evidence(root)[0]["timestamp"] == "2026-09-25T12:00:00+00:00"


def test_evidence_is_private_and_preserves_full_command(tmp_path):
    root = tmp_path / "evidence"
    path = _record(root)

    assert path is not None and path.exists()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    rows = load_evidence(root)
    assert len(rows) == 1
    assert rows[0]["command"] == "echo secret-25"
    assert rows[0]["behavior_hash"] == "behavior"
    assert rows[0]["rule_hash"] == "rule"
    assert (rows[0]["match_start"], rows[0]["match_end"]) == (5, 11)


def test_evidence_prunes_old_day_files_only_on_auto_match(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "2026-09-01.jsonl").write_text(json.dumps({"old": True}) + "\n")
    (root / "2026-09-23.jsonl").write_text(json.dumps({"keep": True}) + "\n")

    _record(root, retention_days=3)

    assert not (root / "2026-09-01.jsonl").exists()
    assert (root / "2026-09-23.jsonl").exists()
    assert (root / "2026-09-25.jsonl").exists()


def test_load_evidence_skips_invalid_rows(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "2026-09-25.jsonl").write_text('{bad}\n{"ok":1}\n')
    assert load_evidence(root) == [{"ok": 1}]


def test_evidence_io_failure_is_best_effort(tmp_path, monkeypatch, caplog):
    root = tmp_path / "evidence"

    def fail_open(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("binnacle.run_command_evidence.os.open", fail_open)
    with caplog.at_level("WARNING", logger="binnacle.run_command_evidence"):
        path = _record(root)

    assert path is None
    line = next(
        record.getMessage()
        for record in caplog.records
        if "event=run_command_evidence_error" in record.getMessage()
    )
    assert "error_class=OSError" in line
    assert "secret-25" not in line
