"""E2 reproducibility, negatives, privacy and evidence-quality gates."""

from __future__ import annotations

import json
import stat
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import lsp_e01_trace as trace
from scripts import lsp_e02_samples as workflow
from scripts.lsp_e02_selection import STRATA, Episode, sample, summary
from tests.scripts.test_lsp_e01_trace import _calls, _observer, _write

PRIVATE = "PRIVATE_TASK_IDENTIFIER_AND_COMMAND_SHOULD_NEVER_ESCAPE_42"
FREEZE = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)


def _fake_episode(i: int, stratum: str) -> Episode:
    call = trace.Call(
        ("generation", f"{PRIVATE}-{i}"),
        "run_command",
        float(i),
        ("observer", f"secret-group-{i}"),
        "observer",
        ("session", ("str", "2")),
        PRIVATE,
        "sha",
        frozenset({"test"}),
        "present",
        "result",
    )
    assert call.group is not None  # synthetic fixture always has verified attribution
    return Episode(
        group=call.group,
        calls=(call,),
        stratum=stratum,
        window_counts=(),
        source_quality="complete_tool_inputs",
        outcome_quality="delivered_only",
        partial_goal_hint=True,
    )


def _capture(tmp_path: Path, actions) -> tuple[Path, Path]:
    root = _write(tmp_path / "capture", _calls(actions)).parent
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [
            (
                "g",
                ident,
                f"req-{ident}",
                "group-change"
                if ident.startswith("a")
                else "group-negative"
                if ident.startswith("n")
                else "group-search",
            )
            for ident, *_ in actions
        ],
    )
    return root, db


def test_real_trace_ingestion_stratifies_candidates_and_negative_controls(tmp_path):
    actions = [
        ("a1", "run_command", {"command": "git diff --stat"}, None, 0, "wfr_a/1"),
        ("a2", "read_file", {"path": f"/private/{PRIVATE}"}, None, 2, "wfr_a/2"),
        ("s1", "search_text", {"pattern": "class Context"}, None, 4, "wfr_s/1"),
        ("s2", "read_file", {"path": f"/private/{PRIVATE}"}, None, 5, "wfr_s/2"),
        ("n1", "job_status", {"job_id": "test-1"}, None, 8, "wfr_n/1"),
    ]
    root, db = _capture(tmp_path, actions)
    report = workflow.run(root, db, until=FREEZE, limit=10)
    assert report["capture_tool_calls"] == 5
    assert report["population_request_groups"] == 3
    assert report["sample_request_groups"] == 3
    assert report["sample_strata"] == {
        "change_navigation_chain": 1,
        "negative_polling": 1,
        "search_read_chain": 1,
    }
    assert report["selected_negative_controls"] == 1
    assert report["r2_r3_replay_ready"] == 0
    assert report["independent_task_goals_verified"] == 0
    assert report["source_snapshots_verified"] == 0
    assert PRIVATE not in json.dumps(report)
    assert "group-change" not in json.dumps(report)


def test_sample_stratifies_and_maintains_negative_controls():
    cases = [
        _fake_episode(i, label)
        for i in range(100)
        for label in (STRATA[i % len(STRATA)],)
    ]
    chosen = sample(cases, limit=22, minimum_negatives=5, seed=1234)
    assert len(chosen) == 22
    assert len({e.group for e in chosen}) == 22
    assert len([e for e in chosen if e.stratum.startswith("negative_")]) >= 5
    assert {e.group for e in chosen} == {
        e.group for e in sample(cases[::-1], limit=22, minimum_negatives=5, seed=1234)
    }
    assert {e.stratum for e in chosen} == set(STRATA)
    assert len(sample(cases, limit=1, minimum_negatives=1)) == 1


def test_no_relabeling_positive_as_negative_when_absent():
    candidates = [_fake_episode(i, "testing") for i in range(11)]
    selected = sample(candidates, limit=7, minimum_negatives=5)
    assert len(selected) == 7
    assert summary(candidates, selected, {})["selected_negative_controls"] == 0
    assert summary(candidates, selected, {})["total_negative_controls"] == 0


@pytest.mark.parametrize(
    ("limit", "min_negatives"), [(0, 0), (101, 1), (10, -1), (2, 3)]
)
def test_invalid_sampling_constraints_fail_closed(limit, min_negatives):
    with pytest.raises(ValueError):
        sample([], limit=limit, minimum_negatives=min_negatives)


def test_duplicate_request_groups_are_rejected():
    a = _fake_episode(1, "testing")
    with pytest.raises(ValueError, match="duplicate"):
        sample([a, replace(a, stratum="navigation")])


def test_missing_request_and_unattributed_calls_excluded(tmp_path):
    rows = _calls(
        [
            ("a", "run_command", {"command": "git diff"}, None, 0, "bad-format/1"),
            ("b", "read_file", {"path": "private-file"}, None, 2, "bad-format/2"),
        ]
    )
    rows = [
        row
        for row in rows
        if not (row["event"] == "mcp_request" and row["correlation"]["call"] == "a")
    ]
    root = _write(tmp_path / "capture", rows).parent
    report = workflow.run(root, None, until=FREEZE)
    assert report["capture_tool_calls"] == 2
    assert report["population_request_groups"] == 0
    assert report["missingness"]["unattributed_calls"] == 2
    assert report["sample_request_groups"] == 0
    assert PRIVATE not in json.dumps(report)


def test_partial_source_and_truncated_output_are_not_verified_goal(tmp_path):
    root, db = _capture(
        tmp_path,
        [
            (
                "s1",
                "search_text",
                {"pattern": "[truncated]"},
                {"truncated": True},
                0,
                "wfr_s/1",
            ),
            ("s2", "read_file", {"path": "test.py"}, None, 2, "wfr_s/2"),
        ],
    )
    report = workflow.run(root, db, until=FREEZE)
    assert report["sample_request_groups"] == 1
    assert report["sample_input_quality"] == {"incomplete_tool_inputs": 1}
    assert report["sample_result_quality"] == {"incomplete": 1}
    assert report["r2_r3_replay_ready"] == 0
    assert report["provisional_subgoal_hints"] == 0


def test_manifest_opaque_private_and_key_reproducible(tmp_path):
    cases = [_fake_episode(i, STRATA[i % len(STRATA)]) for i in range(5)]
    folder = tmp_path / "private-e2"
    workflow.write_private_manifest(
        folder, cases, cohort_end=FREEZE, seed=123, name="first"
    )
    manifest = folder / "first.json"
    key = folder / "e02-local-key.bin"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert len(key.read_bytes()) == 32
    payload = manifest.read_text()
    assert PRIVATE not in payload
    assert "secret-group" not in payload
    data = json.loads(payload)
    assert all(
        x["replayability"] == "R0_unverified"
        and x["annotation_status"] == "pending_independent_review"
        and x["actual_user_task_verified"] is False
        and x["original_source_snapshot_verified"] is False
        for x in data["cases"]
    )
    workflow.write_private_manifest(
        folder, cases, cohort_end=FREEZE, seed=123, name="second"
    )
    followup = json.loads((folder / "second.json").read_text())
    assert [x["host_local_lookup"] for x in followup["cases"]] == [
        x["host_local_lookup"] for x in data["cases"]
    ]
    original = manifest.read_bytes()
    # An exact retry is deliberately idempotent after atomic publication.
    workflow.write_private_manifest(
        folder, cases, cohort_end=FREEZE, seed=123, name="first"
    )
    assert manifest.read_bytes() == original
    with pytest.raises(FileExistsError):
        workflow.write_private_manifest(
            folder, cases[:-1], cohort_end=FREEZE, seed=123, name="first"
        )


def test_manifest_refuses_symlink_and_insecure_root(tmp_path):
    cases = [_fake_episode(2, "testing")]
    other = tmp_path / "target"
    other.mkdir(mode=0o700)
    link = tmp_path / "shortcut"
    link.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        workflow.write_private_manifest(
            link, cases, cohort_end=FREEZE, seed=1, name="one"
        )
    insecure = tmp_path / "public"
    insecure.mkdir(mode=0o755)
    insecure.chmod(0o755)
    with pytest.raises(PermissionError):
        workflow.write_private_manifest(
            insecure, cases, cohort_end=FREEZE, seed=1, name="one"
        )
    with pytest.raises(ValueError, match="batch"):
        workflow.write_private_manifest(
            other, cases, cohort_end=FREEZE, seed=1, name="../outside"
        )


def test_private_dir_cannot_be_relative(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        workflow.write_private_manifest(
            Path("relative-data"), [], cohort_end=FREEZE, seed=1, name="x"
        )


def test_legacy_scrubbed_era_is_unusable_as_original_command(tmp_path):
    root, db = _capture(
        tmp_path, [("s1", "search_text", {"pattern": "[redacted]"}, None, 0, "wfr_s/1")]
    )
    report = workflow.run(root, db, until=FREEZE)
    assert report["sample_input_quality"] == {"incomplete_tool_inputs": 1}
    assert report["r2_r3_replay_ready"] == 0


def test_missing_datetime_is_not_valid_replay_snapshot(tmp_path):
    root, db = _capture(
        tmp_path,
        [("s1", "search_text", {"pattern": "class Context"}, None, 0, "wfr_s/1")],
    )
    with pytest.raises(ValueError):
        workflow.run(root, db, until=datetime.fromisoformat("2026-10-21T00:00:00"))


def test_report_has_no_private_names_paths_or_hashes(tmp_path):
    root, db = _capture(
        tmp_path,
        [("a1", "run_command", {"command": "git diff " + PRIVATE}, None, 0, "wfr_a/1")],
    )
    report = workflow.run(root, db, until=FREEZE)
    wire = json.dumps(report)
    assert PRIVATE not in wire
    assert str(root) not in wire
    assert "group-change" not in wire
    assert "req-a1" not in wire
    assert "host_local_lookup" not in wire


def test_private_fd_anchor_survives_intermediate_symlink_swap(tmp_path):
    import os

    from scripts import lsp_e02_private as private

    root = tmp_path / "private-root"
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    with private._owned_directory(root) as fd:
        moved = tmp_path / "moved-root"
        root.rename(moved)
        root.symlink_to(target, target_is_directory=True)
        private._atomic_publish(
            fd, "anchored.json", b"safe-local-evidence", allow_existing=False
        )
        assert (moved / "anchored.json").read_bytes() == b"safe-local-evidence"
        assert not (target / "anchored.json").exists()
        assert os.stat("anchored.json", dir_fd=fd).st_mode & 0o077 == 0


def test_atomic_publish_interruption_leaves_no_final_or_partial(tmp_path, monkeypatch):
    from scripts import lsp_e02_private as private

    root = tmp_path / "atomic"
    original_link = private.os.link

    def failed_link(*args, **kwargs):
        raise OSError("synthetic crash before final hardlink")

    with private._owned_directory(root) as fd:
        monkeypatch.setattr(private.os, "link", failed_link)
        with pytest.raises(OSError):
            private._atomic_publish(
                fd, "test-batch.json", b"complete-value", allow_existing=False
            )
        assert not (root / "test-batch.json").exists()
        assert not list(root.glob(".e02-part-*"))
        monkeypatch.setattr(private.os, "link", original_link)
        private._atomic_publish(
            fd, "test-batch.json", b"complete-value", allow_existing=False
        )
    assert (root / "test-batch.json").read_bytes() == b"complete-value"


def test_concurrent_private_key_creation_is_consistent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from scripts import lsp_e02_private as private

    root = tmp_path / "private"

    def worker(number):
        entry = {
            "_host_private_lookup_material": [
                ["observer", "private-group"],
                ["gen", "call"],
            ]
        }
        private.write_document(root, f"batch{number}", {"cases": [entry]})
        return json.loads((root / f"batch{number}.json").read_text())["cases"][0][
            "host_local_lookup"
        ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        case_ids = list(pool.map(worker, range(16)))
    assert len(set(case_ids)) == 1
    assert len((root / "e02-local-key.bin").read_bytes()) == 32
    assert all(stat.S_IMODE(file.stat().st_mode) == 0o600 for file in root.iterdir())


@pytest.mark.parametrize(
    "arguments",
    [
        ["--limit", PRIVATE],
        ["--seed", PRIVATE],
        ["--minimum-negatives", PRIVATE],
        ["--unknown-flag", PRIVATE],
    ],
)
def test_cli_never_echoes_invalid_argument_values(
    tmp_path, monkeypatch, capsys, arguments
):
    root = tmp_path / "capture"
    root.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "e02",
            "--capture-dir",
            str(root),
            "--until-utc",
            "2026-10-21T01:00:00Z",
            *arguments,
        ],
    )
    with pytest.raises(SystemExit) as error:
        workflow.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE not in captured.err
    assert captured.err == "E02_ARGUMENT_ERROR\n"


def test_sqlite_cli_failure_does_not_expose_error_text(tmp_path, monkeypatch, capsys):
    import sqlite3

    root = tmp_path / "capture"
    root.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["e02", "--capture-dir", str(root), "--until-utc", "2026-10-21T01:00:00Z"],
    )

    def fail_db(_):
        raise sqlite3.OperationalError(PRIVATE)

    monkeypatch.setattr(workflow, "_observer", fail_db)
    assert workflow.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "E02_SAMPLING_FAILED:OperationalError"
    assert PRIVATE not in captured.err


def test_quality_reports_include_missingness_from_cutoff(tmp_path):
    root = tmp_path / "capture"
    rows = _calls([("a", "run_command", {"command": "git diff"}, None, 0, "wfr_a/1")])
    rows[2]["timestamp"] = "2026-10-21T02:01:00Z"
    _write(root, rows, bad=True, torn=True)
    outcome = workflow.run(root, None, until=FREEZE)
    assert outcome["capture_quality"]["invalid_json"] == 1
    assert outcome["capture_quality"]["incomplete_lines"] == 1
    assert outcome["capture_quality"]["rows"] == 5
    assert outcome["capture_quality"]["unknown_timestamp_excluded"] == 0
    assert outcome["capture_quality"]["after_cutoff_excluded"] == 1
    assert outcome["population_request_groups"] == 1
    assert outcome["sample_result_quality"] == {"incomplete": 1}


def test_capture_directory_permission_failure_is_sanitized(
    tmp_path, monkeypatch, capsys
):
    from pathlib import Path

    root = tmp_path / "private-directory-marker"
    root.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        ["e02", "--capture-dir", str(root), "--until-utc", "2026-10-21T01:00:00Z"],
    )
    original = Path.is_dir

    def block(self):
        if self == root:
            raise PermissionError(13, "PRIVATE_PATH_DO_NOT_DISCLOSE", str(root))
        return original(self)

    monkeypatch.setattr(Path, "is_dir", block)
    assert workflow.main() == 2
    report = capsys.readouterr()
    assert report.out == ""
    assert report.err.strip() == "E02_SAMPLING_FAILED:PermissionError"
    assert str(root) not in report.err
    assert "PRIVATE_PATH_DO_NOT_DISCLOSE" not in report.err


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX FIFO")
def test_fifo_private_key_is_refused_without_blocking(tmp_path):
    import os

    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    os.mkfifo(folder / "e02-local-key.bin", mode=0o600)
    with pytest.raises(PermissionError, match="ownership/mode"):
        workflow.write_private_manifest(
            folder, [], cohort_end=FREEZE, seed=1, name="fifo"
        )
    assert not (folder / "fifo.json").exists()


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX FIFO")
def test_fifo_existing_batch_is_refused_without_blocking(tmp_path):
    import os

    folder = tmp_path / "private"
    workflow.write_private_manifest(folder, [], cohort_end=FREEZE, seed=1, name="first")
    os.mkfifo(folder / "second.json", mode=0o600)
    with pytest.raises(PermissionError, match="ownership/mode"):
        workflow.write_private_manifest(
            folder, [], cohort_end=FREEZE, seed=1, name="second"
        )


def test_resumed_manifest_is_not_accidentally_overwritten(tmp_path):
    folder = tmp_path / "private"
    selected = [_fake_episode(8, "testing")]
    workflow.write_private_manifest(
        folder, selected, cohort_end=FREEZE, seed=12, name="batch"
    )
    existing = (folder / "batch.json").read_bytes()
    with pytest.raises(FileExistsError):
        workflow.write_private_manifest(
            folder, selected, cohort_end=FREEZE, seed=13, name="batch"
        )
    assert (folder / "batch.json").read_bytes() == existing
