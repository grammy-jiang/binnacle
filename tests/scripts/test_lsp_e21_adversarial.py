"""E2.1 adversarial evidence joins: no false matches or unjustified certainty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import lsp_e02_samples as e02
from scripts import lsp_e21_recovery as e21
from tests.scripts.test_lsp_e01_trace import _calls, _observer, _write
from tests.scripts.test_lsp_e21_recovery import BATCH, SECRET, UNTIL


def _ready(tmp_path: Path, rows: list, identifiers: list[str]):
    cap = _write(tmp_path / "capture", rows).parent
    db = tmp_path / "observer.sqlite3"
    _observer(db, [("g", id_, "hash-" + id_, "base") for id_ in identifiers])
    private = tmp_path / "private"
    e02.run(cap, db, until=UNTIL, private_dir=private, batch=BATCH)
    return cap, db, private


def test_reused_request_identity_is_not_two_verified_tool_calls(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git diff"}, None, 0, "wfr_a/1"),
        ("a2", "run_command", {"command": "git diff"}, None, 1, "wfr_a/2"),
    ]
    rows = _calls(actions)
    rows[4]["correlation"]["session"] = rows[1]["correlation"]["session"]
    rows[4]["correlation"]["request_id"] = rows[1]["correlation"]["request_id"]
    rows = [
        r
        for r in rows
        if not (r["event"] == "mcp_request" and r["correlation"]["call"] == "a2")
    ]
    cap, db, priv = _ready(tmp_path, rows, ["a1", "a2"])
    with pytest.raises(ValueError, match="cardinality ambiguous"):
        e21.recover(cap, db, priv, BATCH)


def test_request_timestamp_after_tool_call_never_verifies_chronology(tmp_path):
    actions = [
        ("a1", "search_text", {"pattern": "class Symbol"}, None, 2, "wfr_a/1"),
        ("a2", "read_file", {"path": SECRET}, None, 4, "wfr_a/2"),
    ]
    rows = _calls(actions)
    rows[0]["timestamp"] = "2026-10-21T01:30:00Z"
    cap, db, priv = _ready(tmp_path, rows, ["a1", "a2"])
    out = e21.recover(cap, db, priv, BATCH, write_local_review=True)
    assert out["exact_cases_recovered"] == 1
    assert out["sequence_order_uncertain"] == 1
    assert out["request_chronology_anomalies"] == 1
    review = json.loads((priv / (BATCH + "-e21-v2-review.json")).read_text())
    assert not review["cases"][0]["chronology_unambiguous"]
    assert (
        review["cases"][0]["tool_call_sequence"][0]["request_time_precedes_call"]
        is False
    )
    assert (
        review["cases"][0]["tool_call_sequence"][0]["request_tool_pair_verified"]
        is False
    )
    assert (
        review["cases"][0]["tool_call_sequence"][0]["request_arguments_matched"] is True
    )
    assert SECRET not in json.dumps(out)


def test_missing_timestamp_excluded_by_cutoff_invalidates_local_sequence(tmp_path):
    actions = [
        ("a1", "search_text", {"pattern": "class Symbol"}, None, 0, "wfr_a/1"),
        ("a2", "read_file", {"path": "x.py"}, None, 3, "wfr_a/2"),
        ("a3", "job_status", {"job_id": "synthetic"}, None, 1, "wfr_a/3"),
    ]
    rows = _calls(actions)
    rows[7].pop("timestamp")  # a3 tool_call, excluded under fixed cutoff
    cap, db, priv = _ready(tmp_path, rows, ["a1", "a2", "a3"])
    out = e21.recover(cap, db, priv, BATCH, write_local_review=True)
    assert out["exact_cases_recovered"] == 1
    assert out["sequence_order_uncertain"] == 1
    packet = json.loads((priv / (BATCH + "-e21-v2-review.json")).read_text())
    case = packet["cases"][0]
    assert case["excluded_undated_group_event"] is True
    assert case["chronology_unambiguous"] is False
    assert case["observed_calls"] == 2  # a3 was excluded, not hidden as a third event


def test_shell_newline_is_not_a_single_git_revision_query(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git\nrev-parse HEAD"}, None, 0, "wfr_a/1"),
    ]
    rows = _calls(actions)
    rows[2]["result"]["structured_content"] = {
        "output": "b" * 40 + "\n",
        "exit_code": 0,
        "truncated": False,
    }
    cap, db, priv = _ready(tmp_path, rows, ["a1"])
    out = e21.recover(cap, db, priv, BATCH)
    assert out["explicit_git_revision_query_results"] == 0
    assert out["source_snapshots_verified"] == 0


def test_output_body_mutation_after_checkpoint_is_detected(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git rev-parse HEAD"}, None, 0, "wfr_a/1"),
    ]
    rows = _calls(actions)
    rows[2]["result"]["structured_content"] = {
        "output": "a" * 40 + "\n",
        "exit_code": 0,
        "truncated": False,
    }
    cap, db, priv = _ready(tmp_path, rows, ["a1"])
    e21.recover(cap, db, priv, BATCH, write_local_review=True)
    rows[2]["result"]["structured_content"]["output"] = "b" * 40 + "\n"
    _write(cap, rows)
    report = e21.recover(cap, db, priv, BATCH)
    assert report["original_E2_source_content_integrity_unproven"] is True
    assert report["explicit_git_revision_query_results"] == 1
    with pytest.raises(FileExistsError):
        e21.recover(cap, db, priv, BATCH, write_local_review=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", True),
        ("group_call_count", True),
        ("group_call_count", "1"),
        ("schema", "wrong-schema"),
    ],
)
def test_manifest_case_schema_and_type_falsification_refused(tmp_path, field, value):
    actions = [("a1", "read_file", {"path": "p.py"}, None, 0, "wfr_a/1")]
    cap, db, priv = _ready(tmp_path, _calls(actions), ["a1"])
    file = priv / (BATCH + ".json")
    manifest = json.loads(file.read_text())
    if field == "seed":
        manifest[field] = value
    else:
        manifest["cases"][0][field] = value
    file.write_text(json.dumps(manifest) + "\n")
    with pytest.raises((ValueError, TypeError)):
        e21.recover(cap, db, priv, BATCH)


def test_changed_provisional_hint_is_not_silently_reclassified(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git diff --stat"}, None, 0, "wfr_a/1"),
    ]
    cap, db, priv = _ready(tmp_path, _calls(actions), ["a1"])
    manifest = priv / (BATCH + ".json")
    data = json.loads(manifest.read_text())
    original = data["cases"][0]["partial_subgoal_hint"]
    assert type(original) is bool
    data["cases"][0]["partial_subgoal_hint"] = not original
    manifest.write_text(json.dumps(data) + "\n")
    with pytest.raises(ValueError, match="metadata changed"):
        e21.recover(cap, db, priv, BATCH)


@pytest.mark.parametrize(
    ("exit_code", "truncated"),
    [
        (False, False),
        (True, False),
        (0, 1),
        (0, 0),
        (0, None),
        ("0", False),
    ],
)
def test_git_head_proof_requires_strict_result_types(tmp_path, exit_code, truncated):
    actions = [
        ("a1", "run_command", {"command": "git rev-parse HEAD"}, None, 0, "wfr_a/1"),
    ]
    rows = _calls(actions)
    rows[2]["result"]["structured_content"] = {
        "output": "a" * 40 + "\n",
        "exit_code": exit_code,
        "truncated": truncated,
    }
    cap, db, priv = _ready(tmp_path, rows, ["a1"])
    report = e21.recover(cap, db, priv, BATCH)
    assert report["explicit_git_revision_query_results"] == 0
    assert report["source_snapshots_verified"] == 0


def test_git_head_proof_accepts_only_integer_zero_and_explicit_false(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git rev-parse HEAD"}, None, 0, "wfr_a/1"),
    ]
    rows = _calls(actions)
    rows[2]["result"]["structured_content"] = {
        "output": "c" * 40 + "\n",
        "exit_code": 0,
        "truncated": False,
    }
    cap, db, priv = _ready(tmp_path, rows, ["a1"])
    report = e21.recover(cap, db, priv, BATCH)
    assert report["explicit_git_revision_query_results"] == 1
    assert report["source_snapshots_verified"] == 0
