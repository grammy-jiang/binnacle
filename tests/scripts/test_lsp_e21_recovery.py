"""E2.1 synthetic, read-only recovery of opaque private historical request groups."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import lsp_e02_samples as e02
from scripts import lsp_e21_recovery as e21
from tests.scripts.test_lsp_e01_trace import _calls, _observer, _write

SECRET = "PRIVATE_HISTORICAL_COMMAND_OR_PATH_DO_NOT_PRINT_927"
UNTIL = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
BATCH = "synthetic-20261021"


def _ready(tmp_path: Path, actions: list) -> tuple[Path, Path, Path]:
    root = _write(tmp_path / "capture", _calls(actions)).parent
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [
            ("g", ident, f"request-{ident}", f"group-{ident[:1]}")
            for ident, *_ in actions
        ],
    )
    private_dir = tmp_path / "private-e2"
    e02.run(
        root,
        db,
        until=UNTIL,
        limit=20,
        minimum_negatives=2,
        private_dir=private_dir,
        batch=BATCH,
    )
    return root, db, private_dir


def _actions() -> list:
    return [
        (
            "a1",
            "run_command",
            {"command": f"git diff -- {SECRET}"},
            None,
            0,
            "wfr_change/1",
        ),
        ("a2", "read_file", {"path": f"/private/{SECRET}"}, None, 2, "wfr_change/2"),
        ("s1", "search_text", {"pattern": f"class {SECRET}"}, None, 5, "wfr_search/1"),
        ("s2", "read_file", {"path": f"/private/{SECRET}"}, None, 7, "wfr_search/2"),
        ("n1", "job_status", {"job_id": SECRET}, None, 10, "wfr_negative/1"),
    ]


def test_recover_exact_private_refs_and_aggregate_without_raw_content(tmp_path):
    capture, db, private_dir = _ready(tmp_path, _actions())
    files_before = set(private_dir.iterdir())
    out = e21.recover(capture, db, private_dir, BATCH)
    assert out["manifest_cases"] == out["exact_cases_recovered"] == 3
    assert out["sample_strata"] == {
        "change_navigation_chain": 1,
        "negative_polling": 1,
        "search_read_chain": 1,
    }
    assert out["sequence_order_uncertain"] == 0
    assert out["selected_requests_with_nonempty_task_field"] == 0
    assert out["source_snapshots_verified"] == 0
    assert out["independent_task_goals_verified"] == 0
    assert out["gold_answers_verified"] == 0
    assert out["r2_r3_ready"] == 0
    assert out["local_detailed_review_created"] is False
    assert out["original_E2_source_content_integrity_unproven"] is True
    assert set(private_dir.iterdir()) == files_before
    wire = json.dumps(out)
    for private_value in (SECRET, "request-a1", "group-a", "wfr_change", str(capture)):
        assert private_value not in wire


def test_private_review_sequence_is_detailed_but_not_raw(tmp_path):
    capture, db, private_dir = _ready(tmp_path, _actions())
    out = e21.recover(
        capture,
        db,
        private_dir,
        BATCH,
        write_local_review=True,
    )
    assert out["exact_cases_recovered"] == 3
    report_path = private_dir / (BATCH + "-e21-v2-review.json")
    assert report_path.is_file()
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    private_report = json.loads(report_path.read_text())
    assert private_report["schema"] == e21.REVIEW_SCHEMA
    assert len(private_report["cases"]) == 3
    for case in private_report["cases"]:
        assert case["replayability"] == "R0_unverified"
        assert case["independent_gold_verified"] is False
        assert case["original_task_goal_verified"] is False
        assert case["historical_source_snapshot_verified"] is False
        assert len(case["local_evidence_fingerprint"]) == 32
        assert case["observed_calls"] == case["paired_calls"]
        assert case["chronology_unambiguous"]
        for record in case["tool_call_sequence"]:
            assert record["tool"] in {
                "run_command",
                "read_file",
                "search_text",
                "job_status",
            }
            assert record["outcome"] == "result"
            assert record["request_tool_pair_verified"]
            assert isinstance(record["start_offset_s"], (int, float))
    text = report_path.read_text()
    for marker in (SECRET, "group-a", "request-a1", "/private/"):
        assert marker not in text
    # The identical evidence checkpoint is safely idempotent.
    e21.recover(capture, db, private_dir, BATCH, write_local_review=True)
    assert report_path.read_text() == text


def test_mutated_arguments_can_only_be_checked_after_local_e21_checkpoint(tmp_path):
    actions = _actions()
    capture, db, private_dir = _ready(tmp_path, actions)
    e21.recover(capture, db, private_dir, BATCH, write_local_review=True)
    rows = _calls(actions)
    # Both request and call change coherently, preserving the lexical stratum
    # and opaque group/call reference from E2. The original E2 selection did
    # not store a content fingerprint; do not invent historical certainty.
    rows[0]["payload"]["arguments"] = {"command": "git diff -- modified"}
    rows[1]["arguments"] = {"command": "git diff -- modified"}
    _write(capture, rows)
    report = e21.recover(capture, db, private_dir, BATCH)
    assert report["original_E2_source_content_integrity_unproven"]
    with pytest.raises(FileExistsError):
        e21.recover(capture, db, private_dir, BATCH, write_local_review=True)


def test_git_revision_observation_does_not_certify_historic_worktree(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git rev-parse HEAD"}, None, 0, "wfr_a/1"),
        (
            "a2",
            "run_command",
            {"command": "git status --porcelain"},
            None,
            2,
            "wfr_a/2",
        ),
        ("a3", "read_file", {"path": SECRET}, None, 4, "wfr_a/3"),
    ]
    capture = tmp_path / "capture"
    rows = _calls(actions)
    rows[2]["result"]["structured_content"] = {
        "truncated": False,
        "exit_code": 0,
        "output": "a" * 40 + "\n",
    }
    rows[5]["result"]["structured_content"] = {
        "truncated": False,
        "exit_code": 0,
        "output": "",
    }
    # The Git result arrives before the corresponding call in this fixture.
    rows.insert(0, rows.pop(2))
    _write(capture, rows)
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [("g", ident, f"request-{ident}", "group-a") for ident, *_ in actions],
    )
    private_dir = tmp_path / "private"
    e02.run(capture, db, until=UNTIL, private_dir=private_dir, batch=BATCH)
    out = e21.recover(capture, db, private_dir, BATCH)
    assert out["explicit_git_revision_query_results"] == 1
    assert out["explicit_git_clean_status_results"] == 1
    assert out["source_snapshots_verified"] == 0
    assert out["r2_r3_ready"] == 0
    assert "a" * 40 not in json.dumps(out)


def test_compound_git_string_and_truncated_output_are_not_revision_proof(tmp_path):
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git rev-parse HEAD; echo changed"},
            None,
            0,
            "wfr_a/1",
        ),
        ("a2", "run_command", {"command": "git rev-parse HEAD"}, None, 2, "wfr_a/2"),
    ]
    rows = _calls(actions)
    for i in (2, 5):
        rows[i]["result"]["structured_content"] = {
            "truncated": i == 5,
            "exit_code": 0,
            "output": "f" * 40 + "\n",
        }
    capture = _write(tmp_path / "capture", rows).parent
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [("g", ident, f"request-{ident}", "group-a") for ident, *_ in actions],
    )
    private = tmp_path / "private"
    e02.run(capture, db, until=UNTIL, private_dir=private, batch=BATCH)
    report = e21.recover(capture, db, private, BATCH)
    assert report["explicit_git_revision_query_results"] == 0
    assert report["source_snapshots_verified"] == 0


def test_present_task_payload_does_not_become_verified_user_goal(tmp_path):
    actions = [
        ("a1", "search_text", {"pattern": "class Symbol"}, None, 0, "wfr_a/1"),
    ]
    root, db, private_dir = _ready(tmp_path, actions)
    rows = _calls(actions)
    rows[0]["payload"]["task"] = {"description": SECRET}
    _write(root, rows)
    report = e21.recover(root, db, private_dir, BATCH)
    assert report["selected_requests_with_nonempty_task_field"] == 1
    assert report["independent_task_goals_verified"] == 0
    assert SECRET not in json.dumps(report)


def test_opaque_ref_tampering_is_detected_not_substituted(tmp_path):
    root, db, private_dir = _ready(tmp_path, _actions())
    manifest = private_dir / (BATCH + ".json")
    data = json.loads(manifest.read_text())
    data["cases"][0]["host_local_lookup"] = "0" * 32
    manifest.write_text(json.dumps(data) + "\n")
    with pytest.raises(ValueError, match="cannot be relinked"):
        e21.recover(root, db, private_dir, BATCH)


@pytest.mark.parametrize(
    "field",
    [
        "actual_user_task_verified",
        "independent_gold_verified",
        "original_source_snapshot_verified",
    ],
)
def test_claiming_verified_gold_in_unreviewed_manifest_is_refused(tmp_path, field):
    root, db, private_dir = _ready(tmp_path, _actions())
    manifest = private_dir / (BATCH + ".json")
    data = json.loads(manifest.read_text())
    data["cases"][0][field] = True
    manifest.write_text(json.dumps(data) + "\n")
    with pytest.raises(ValueError, match="must not silently upgrade"):
        e21.recover(root, db, private_dir, BATCH)


def test_read_only_recovery_does_not_create_files(tmp_path, monkeypatch):
    root, db, private_dir = _ready(tmp_path, _actions())
    before = set(private_dir.iterdir())
    from scripts import lsp_e21_recovery

    def refuse_write(*args, **kwargs):
        raise AssertionError("E21 attempted a write")

    monkeypatch.setattr(lsp_e21_recovery.os, "mkdir", refuse_write)
    monkeypatch.setattr(lsp_e21_recovery.os, "fsync", refuse_write)
    result = e21.recover(root, db, private_dir, BATCH)
    assert result["exact_cases_recovered"] == 3
    assert set(private_dir.iterdir()) == before


def test_missing_and_symlinked_manifest_fail_before_any_recovery(tmp_path):
    root, db, private_dir = _ready(tmp_path, _actions())
    manifest = private_dir / (BATCH + ".json")
    manifest.unlink()
    with pytest.raises(FileNotFoundError):
        e21.recover(root, db, private_dir, BATCH)
    # Avoid dangling copies or a path outside the owner-private directory.
    link = private_dir / (BATCH + ".json")
    link.symlink_to(root / "2026-10-21.jsonl")
    with pytest.raises(OSError):
        e21.recover(root, db, private_dir, BATCH)
