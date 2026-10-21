"""E2.2: independent document leads must never become verified human goals."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import lsp_e02_samples as sampler
from scripts import lsp_e21_recovery as e21
from scripts import lsp_e22_goals as e22
from tests.scripts.test_lsp_e01_trace import _calls, _observer, _write

FREEZE = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
BATCH = "synthetic-e22"
SECRET = "DO_NOT_EXPORT_PRIVATE_TASK_TEXT_4921"


def _repo(home: Path, name="repo") -> Path:
    result = home / "Projects" / name
    (result / ".git").mkdir(parents=True)
    return result


def _prior_document(repo: Path, text: str, *, later=False) -> Path:
    docs = repo / "docs"
    docs.mkdir(exist_ok=True)
    path = docs / "TASKS.md"
    path.write_text(text)
    epoch = datetime.fromisoformat(
        "2026-10-21T01:05:00+00:00" if later else "2026-10-21T00:59:00+00:00"
    ).timestamp()
    os.utime(path, (epoch, epoch))
    return path


def _setup(
    tmp_path: Path,
    actions: list[tuple],
    *,
    home: Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    home = home or tmp_path / "home"
    (home / "Projects").mkdir(parents=True, exist_ok=True)
    root = _write(tmp_path / "capture", _calls(actions)).parent
    db = tmp_path / "observer.sqlite3"
    _observer(
        db,
        [
            ("g", identity, f"request-{identity}", "one-request-group")
            for identity, *_ in actions
        ],
    )
    private = tmp_path / "private-e2"
    sampler.run(
        root,
        db,
        until=FREEZE,
        private_dir=private,
        batch=BATCH,
        minimum_negatives=0,
    )
    e21.recover(root, db, private, BATCH, write_local_review=True)
    return root, db, private, home


def test_correlated_dated_doc_is_only_provisional_source_lead(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    _prior_document(project, f"# P1.9 acceptance task\n{SECRET}")
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff -- P1.9", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    output = e22.inspect_goals(
        cap,
        db,
        private,
        BATCH,
        home=home,
        write_local_review=True,
    )
    assert output["selected_case_groups"] == 1
    assert output["e21_checkpoint_revalidated"]
    leads = output["local_source_leads"]
    assert leads["cases_with_single_project_repository_anchor"] == 1
    assert leads["cases_with_mtime_window_document_leads"] == 1
    assert leads["cases_with_same_literal_task_id_in_mtime_window_document"] == 1
    assert output["independent_human_task_goals_verified"] == 0
    assert output["gold_answers_verified"] == 0
    assert output["r2_r3_ready"] == 0
    assert SECRET not in json.dumps(output)
    assert str(project) not in json.dumps(output)
    packet = private / (BATCH + "-e22-v2-goal-sources.json")
    assert stat.S_IMODE(packet.stat().st_mode) == 0o600
    content = json.loads(packet.read_text())
    assert len(content["cases"]) == 1
    assert content["cases"][0]["literal_task_id_in_document"] is True
    assert content["cases"][0]["replayability"] == "R0_unverified"
    assert content["cases"][0]["independent_human_task_goal_verified"] is False
    assert SECRET not in packet.read_text()
    assert str(project) not in packet.read_text()
    # The checkpoint is identical on the second pass; no new task proof.
    repeated = e22.inspect_goals(
        cap, db, private, BATCH, home=home, write_local_review=True
    )
    assert repeated == output


def test_newer_document_cannot_be_inferred_as_historical_task(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    _prior_document(project, "P2.7 task planning", later=True)
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff P2.7", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    result = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert (
        result["local_source_leads"]["cases_with_single_project_repository_anchor"] == 1
    )
    assert (
        result["local_source_leads"].get("cases_with_mtime_window_document_leads", 0)
        == 0
    )
    assert (
        result["local_source_leads"].get(
            "cases_with_same_literal_task_id_in_mtime_window_document", 0
        )
        == 0
    )


def test_multiple_repositories_never_selected_as_unique_task_scope(tmp_path):
    home = tmp_path / "home"
    left = _repo(home, "first")
    right = _repo(home, "second")
    _prior_document(left, "P1.9")
    _prior_document(right, "P1.9")
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff P1.9", "workdir": str(left)},
            None,
            0,
            "wfr_a/1",
        ),
        (
            "a2",
            "run_command",
            {"command": "git status P1.9", "workdir": str(right)},
            None,
            1,
            "wfr_a/2",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert report["local_source_leads"]["cases_with_multiple_project_repositories"] == 1
    assert (
        report["local_source_leads"].get(
            "cases_with_single_project_repository_anchor", 0
        )
        == 0
    )
    assert (
        report["local_source_leads"].get(
            "cases_with_same_literal_task_id_in_mtime_window_document", 0
        )
        == 0
    )


def test_document_without_matching_identifier_does_not_create_goal(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    _prior_document(project, "P5.4 independent task")
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff -- P1.9", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert report["local_source_leads"]["cases_with_mtime_window_document_leads"] == 1
    assert (
        report["local_source_leads"].get(
            "cases_with_same_literal_task_id_in_mtime_window_document", 0
        )
        == 0
    )
    assert report["independent_human_task_goals_verified"] == 0


def test_absent_repository_anchor_is_not_silently_guessed(tmp_path):
    actions = [
        (
            "a1",
            "run_command",
            {"command": f"echo {SECRET}", "workdir": "/outside/projects"},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions)
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert report["selected_case_groups"] == 1
    assert (
        report["task_goal_evidence_reasons"]["no_single_explicit_repository_anchor"]
        == 1
    )
    assert (
        report["local_source_leads"].get("cases_with_mtime_window_document_leads", 0)
        == 0
    )


def test_missing_prior_e21_checkpoint_is_a_hard_gate(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    (private / (BATCH + "-e21-v2-review.json")).unlink()
    with pytest.raises(FileNotFoundError):
        e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert not (private / (BATCH + "-e22-v2-goal-sources.json")).exists()


def test_revised_e21_content_rejects_task_source_result(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff P1.9", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    rows = _calls(actions)
    rows[2]["result"]["structured_content"]["output"] = SECRET
    _write(cap, rows)
    with pytest.raises(ValueError, match="checkpoint differs"):
        e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert not (private / (BATCH + "-e22-v2-goal-sources.json")).exists()


@pytest.mark.parametrize(
    "text",
    [
        SECRET + " git diff P1.9",
        "P1.9 " + SECRET,
    ],
)
def test_no_raw_project_or_original_task_text_in_report(tmp_path, text):
    home = tmp_path / "home"
    project = _repo(home)
    _prior_document(project, text)
    actions = [
        (
            "a1",
            "search_text",
            {"pattern": "P1.9", "path": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    report = e22.inspect_goals(
        cap, db, private, BATCH, home=home, write_local_review=True
    )
    packet = (private / (BATCH + "-e22-v2-goal-sources.json")).read_text()
    assert SECRET not in json.dumps(report) and SECRET not in packet
    assert str(project) not in json.dumps(report) and str(project) not in packet
    assert report["independent_human_task_goals_verified"] == 0


def test_conflicting_workdir_and_file_path_do_not_attribute_one_repo(tmp_path):
    home = tmp_path / "home"
    a = _repo(home, "A")
    b = _repo(home, "B")
    _prior_document(a, "P1.9 task definition")
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git diff P1.9", "workdir": str(a), "path": str(b)},
            None,
            0,
            "wfr_a/1",
        ),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    leads = report["local_source_leads"]
    assert leads["cases_with_multiple_project_repositories"] == 1
    assert leads.get("cases_with_single_project_repository_anchor", 0) == 0
    assert leads.get("cases_with_same_literal_task_id_in_mtime_window_document", 0) == 0


def test_unanchored_call_task_id_cannot_borrow_sibling_repo_document(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    _prior_document(project, "P1.9 task acceptance")
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git status", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        ),
        ("a2", "run_command", {"command": "echo P1.9"}, None, 2, "wfr_a/2"),
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    leads = report["local_source_leads"]
    assert leads["cases_with_single_project_repository_anchor"] == 1
    assert leads["cases_with_mtime_window_document_leads"] == 1
    assert leads.get("cases_with_same_literal_task_id_in_mtime_window_document", 0) == 0


def test_task_identifier_requires_exact_case_and_whole_token(tmp_path):
    from scripts.lsp_e22_sources import task_refs

    assert task_refs("P1.9") == {"P1.9"}
    assert task_refs("p1.9") == set()
    assert "P1.2.3.4" not in task_refs("P1.2.3.4.5")
    assert task_refs("P1.9-extra") == set()
    assert task_refs("TASK-12345") == {"TASK-12345"}


def test_malformed_other_tool_event_identity_is_counted_not_fatal(tmp_path):
    home = tmp_path / "home"
    project = _repo(home)
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git status", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        )
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    path = cap / "2026-10-21.jsonl"
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "tool_call",
                    "timestamp": "2026-10-21T01:00:01Z",
                    "correlation": {"server_gen": [], "call": "invalid"},
                    "tool_name": "run_command",
                    "arguments": {"command": SECRET},
                }
            )
            + "\n"
        )
    # E2.1 rejects the unrelated malformed call identity; no new
    # semantic evidence may be attached to the valid chosen case.
    report = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert report["selected_case_groups"] == 1
    assert report["captured_input_quality"]["invalid_call_identity"] == 1
    assert report["independent_human_task_goals_verified"] == 0


def test_default_e22_checkpoint_validation_has_no_write_side_effects(
    tmp_path, monkeypatch
):
    from scripts import lsp_e21_recovery as checkpoint

    home = tmp_path / "home"
    project = _repo(home)
    actions = [
        (
            "a1",
            "run_command",
            {"command": "git status", "workdir": str(project)},
            None,
            0,
            "wfr_a/1",
        )
    ]
    cap, db, private, home = _setup(tmp_path, actions, home=home)
    before = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in private.iterdir()
    }

    def write_refused(*args, **kwargs):
        raise AssertionError("Unexpected private packet write")

    monkeypatch.setattr(checkpoint, "_atomic_publish", write_refused)
    monkeypatch.setattr(checkpoint, "_owned_directory", write_refused)
    monkeypatch.setattr(e22, "_atomic_publish", write_refused)
    monkeypatch.setattr(e22, "_owned_directory", write_refused)
    result = e22.inspect_goals(cap, db, private, BATCH, home=home)
    assert result["e21_checkpoint_revalidated"] is True
    assert result["local_private_source_packet_created"] is False
    after = {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in private.iterdir()
    }
    assert after == before
