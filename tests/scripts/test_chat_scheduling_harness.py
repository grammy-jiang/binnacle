import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import chat_scheduling_chat as chat
from scripts import chat_scheduling_harness as harness
from scripts import chat_scheduling_runtime as runtime
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario


class FakeProject:
    def __init__(self, text: str = "original", fail_on_restore: bool = False):
        self.text = text
        self.original = text
        self.fail_on_restore = fail_on_restore
        self.sets: list[str] = []

    def instructions(self) -> str:
        return self.text

    def set_instructions(self, text: str) -> None:
        if self.fail_on_restore and text == self.original:
            raise RuntimeError("restore unavailable")
        self.sets.append(text)
        self.text = text


class FakeMCP:
    def __init__(self):
        self.started: list[tuple[str, Path]] = []
        self.stopped_roots: list[Path] = []

    def start_job(self, command: str, workdir: Path) -> str:
        self.started.append((command, workdir))
        return f"job-{len(self.started)}"

    def stop_root_jobs(self, root: Path) -> list[str]:
        self.stopped_roots.append(root)
        return []


class FakeProduction:
    def __init__(self, marker: str = "same"):
        self.marker = marker

    @classmethod
    def capture(cls):
        return cls()

    @property
    def __dict__(self):
        return {"marker": self.marker}

    def assert_unchanged(self, after) -> None:
        if self.marker != after.marker:
            raise runtime.HarnessError("production changed")


def _state_dir_factory(base: Path):
    def create(identity):
        path = base / identity.run_id
        path.mkdir(parents=True)
        return path

    return create


def test_trial_identity_is_unique_and_nonce_is_unpredictable_length():
    first = runtime.TrialIdentity.create("M1")
    second = runtime.TrialIdentity.create("M1")

    assert first.run_id != second.run_id
    assert first.nonce != second.nonce
    assert len(first.nonce) == len(second.nonce) == 32


def test_render_text_substitutes_only_runtime_vocabulary(tmp_path):
    identity = runtime.TrialIdentity("M1", "run-1", "abc123")

    rendered = runtime.render_text(
        "{id}|{run_id}|{nonce}|{root}|{job:x}|{result:later.job_id}",
        identity,
        tmp_path,
        {"x": "job-9"},
    )

    assert rendered == (f"M1|run-1|abc123|{tmp_path}|job-9|{{result:later.job_id}}")


def test_instruction_lease_restores_after_success():
    project = FakeProject("A")

    with chat.InstructionLease(project, "B", sleep=lambda _: None):
        assert project.text == "B"

    assert project.text == "A"
    assert project.sets == ["B", "A"]


def test_instruction_lease_restores_after_trial_failure():
    project = FakeProject("A")

    with (
        pytest.raises(ValueError, match="trial"),
        chat.InstructionLease(project, "B", sleep=lambda _: None),
    ):
        raise ValueError("trial")

    assert project.text == "A"


def test_instruction_lease_preserves_original_error_when_restore_fails():
    project = FakeProject("A", fail_on_restore=True)

    with (
        pytest.raises(runtime.RestoreError) as captured,
        chat.InstructionLease(project, "B", sleep=lambda _: None),
    ):
        raise ValueError("original")

    assert isinstance(captured.value.original, ValueError)
    assert isinstance(captured.value.restore, RuntimeError)


def test_fixture_lease_creates_git_fixture_and_removes_it(monkeypatch, tmp_path):
    scenario = load_scenario(SCENARIO_ROOT / "R8.json").model_copy(deep=True)
    monkeypatch.setattr(runtime, "FIXTURE_BASE", tmp_path)
    scenario.fixture.root_template = str(tmp_path / "{id}" / "{run_id}")
    identity = runtime.TrialIdentity("R8", "r8-test", "nonce-x")
    fake_mcp = FakeMCP()
    fixture = runtime.FixtureLease(scenario, identity, fake_mcp)

    fixture.__enter__()
    try:
        assert (fixture.root / ".git").is_dir()
        assert "nonce-x" in (fixture.root / "README.md").read_text()
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=fixture.root, text=True
        ).strip()
        assert len(head) == 40
    finally:
        result = fixture.cleanup()

    assert result["errors"] == []
    assert result["root_removed"] is True
    assert not fixture.root.exists()


def test_fixture_lease_prelaunches_manifest_jobs(monkeypatch, tmp_path):
    scenario = load_scenario(SCENARIO_ROOT / "M3.json").model_copy(deep=True)
    monkeypatch.setattr(runtime, "FIXTURE_BASE", tmp_path)
    scenario.fixture.root_template = str(tmp_path / "{id}" / "{run_id}")
    fixture = runtime.FixtureLease(
        scenario,
        runtime.TrialIdentity("M3", "m3-test", "n"),
        FakeMCP(),
    )

    fixture.__enter__()
    try:
        assert fixture.jobs == {"slow": "job-1"}
        assert "job-1" in fixture.rendered_prompt()
    finally:
        fixture.cleanup()


def test_production_snapshot_reports_changed_invariant():
    before = runtime.ProductionSnapshot("a", "", "cfg", "unit", "active", "running")
    after = runtime.ProductionSnapshot("b", "", "cfg", "unit", "active", "running")

    with pytest.raises(runtime.HarnessError, match="head"):
        before.assert_unchanged(after)


def test_chat_artifact_cleanup_is_exact_and_copies_backup(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(chat, "CHAT_BACKUP_DIR", backup_dir)
    calls: list[list[str]] = []
    cid = "12345678-1234-1234-1234-123456789abc"

    def fake_run(args, **kwargs):
        calls.append(args)
        if "--delete" in args:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"20260923T000000Z_{cid}.json").write_text(
                '{"conversation":"saved"}'
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    artifact = chat.ChatArtifact("project", tmp_path)
    artifact.chat_id = cid
    artifact.tracked = True

    result = artifact.cleanup()

    assert result["deleted"] is True
    assert json.loads((tmp_path / "conversation.json").read_text()) == {
        "conversation": "saved"
    }
    delete_call = next(args for args in calls if "--delete" in args)
    assert delete_call[delete_call.index("--id") + 1] == cid
    assert any("--untrack" in args for args in calls)


def test_url_file_discovers_exact_chat_id(tmp_path):
    cid = "12345678-1234-1234-1234-123456789abc"
    url_file = tmp_path / "url"
    url_file.write_text(f"https://chatgpt.com/c/{cid}\n")
    artifact = chat.ChatArtifact("project", tmp_path)

    artifact.discover(url_file)

    assert artifact.chat_id == cid


def test_restore_probe_injects_failure_but_returns_success_after_restore(
    monkeypatch, tmp_path
):
    project = FakeProject("baseline")
    monkeypatch.setattr(harness, "ProjectClient", lambda *args, **kwargs: project)
    monkeypatch.setattr(harness, "new_state_dir", _state_dir_factory(tmp_path))

    code, state = harness.run_restore_probe()

    assert code == 0
    assert project.text == "baseline"
    record = json.loads((state / "trial.json").read_text())
    assert record["status"] == "completed"
    assert record["instructions"]["restored"] is True


@pytest.mark.parametrize(
    ("arm", "budget", "endpoint", "normalized"),
    [
        ("A", None, "A", None),
        ("B", None, "B", None),
        ("C", 300, "C300", 300),
        ("H", None, "H", 10),
    ],
)
def test_phase4_arm_budget_endpoint_contract(arm, budget, endpoint, normalized):
    assert runtime.validate_arm_endpoint(arm, budget, endpoint) == normalized


@pytest.mark.parametrize(
    ("arm", "budget", "endpoint"),
    [
        ("A", 10, "A"),
        ("B", None, "A"),
        ("C", None, "C300"),
        ("C", 120, "C300"),
        ("H", 11, "H"),
    ],
)
def test_phase4_arm_budget_endpoint_mismatch_is_hard_error(arm, budget, endpoint):
    with pytest.raises(runtime.HarnessError, match="arm/budget/endpoint"):
        runtime.validate_arm_endpoint(arm, budget, endpoint)


def test_r12_runtime_placeholder_uses_selected_budget(tmp_path):
    identity = runtime.TrialIdentity("R12", "r12", "nonce")
    assert (
        runtime.render_text(
            "{budget_plus_margin_s}", identity, tmp_path, budget_s=300, margin_s=30
        )
        == "330"
    )


def test_trial_failure_does_not_mutate_lane_project_and_records_identity(
    monkeypatch, tmp_path
):
    project = FakeProject("variant-B")
    selected = {
        "logical_arm": "B",
        "budget_s": None,
        "endpoint_id": "B",
        "connector_logical_name": "Raspberry Pi MCP Scheduling B",
        "project_id": "g-p-B",
        "project_name": "rp-sched-B",
        "model_thinking": {"thinking_effort": "max"},
        "phase4_source_head": "0" * 40,
        "instruction_sha256": hashlib.sha256(b"variant-B").hexdigest(),
        "base_topology_sha256": "a" * 64,
        "lane_manifest_path": "B.json",
        "lane_manifest_sha256": "b" * 64,
        "runtime_registry_sha256": "c" * 64,
        "admission_envelope_revision": "r01",
        "host": "127.0.0.1",
        "port": 8111,
        "token_path": "token",
    }
    monkeypatch.setattr(harness, "resolve_phase4_endpoint", lambda *a, **k: selected)
    monkeypatch.setattr(harness, "_begin_endpoint_capture", lambda *a, **k: {})
    monkeypatch.setattr(
        harness,
        "_finalize_endpoint_capture",
        lambda *a, **k: {"evidence_integrity_error": False},
    )
    monkeypatch.setattr(harness, "ProjectClient", lambda *args, **kwargs: project)
    monkeypatch.setattr(harness, "new_state_dir", _state_dir_factory(tmp_path / "runs"))
    monkeypatch.setattr(harness, "ProductionSnapshot", FakeProduction)
    monkeypatch.setattr(harness, "LocalMCP", lambda *args, **kwargs: FakeMCP())

    code, state = harness.run_trial(
        "M1", "B", budget_s=None, endpoint_id="B", fail_after_instructions=True
    )

    record = json.loads((state / "trial.json").read_text())
    assert code == 1 and project.sets == []
    assert record["instructions"]["mutated"] is False
    assert record["submission_status"] == "pre_submit_failure"
    assert record["provenance_classification"] == "pre_mcp_submission_failure"
    assert (record["arm"], record["budget_s"], record["endpoint_id"]) == (
        "B",
        None,
        "B",
    )
    assert record["connector_logical_name"] == "Raspberry Pi MCP Scheduling B"
    assert record["model_thinking_snapshot"]["thinking_effort"] == "max"
    assert record["source_head"] == "0" * 40 and record["manifest_sha256"]


def test_fixture_snapshot_preserves_final_files_and_git_diff(monkeypatch, tmp_path):
    scenario = load_scenario(SCENARIO_ROOT / "R8.json").model_copy(deep=True)
    fixture_base = tmp_path / "fixtures"
    monkeypatch.setattr(runtime, "FIXTURE_BASE", fixture_base)
    scenario.fixture.root_template = str(fixture_base / "{id}" / "{run_id}")
    fixture = runtime.FixtureLease(
        scenario,
        runtime.TrialIdentity("R8", "snapshot-test", "N-SNAP"),
        FakeMCP(),
    )
    fixture.__enter__()
    try:
        app = fixture.root / "app.py"
        app.write_text(app.read_text().replace("BEFORE-N-SNAP", "AFTER-N-SNAP"))
        target = tmp_path / "fixture-final.json"
        payload = fixture.snapshot(target)

        assert "AFTER-N-SNAP" in payload["final_files"]["app.py"]
        assert "app.py" in payload["git_status_porcelain"]
        assert "AFTER-N-SNAP" in payload["git_diff"]
        assert json.loads(target.read_text())["file_sha256"]["app.py"]
    finally:
        fixture.cleanup()


def test_chat_artifact_cleanup_retries_transient_delete_failures(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(chat, "CHAT_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(chat.time, "sleep", lambda _: None)
    cid = "12345678-1234-1234-1234-123456789abc"
    delete_attempts = 0
    delete_args = []

    def fake_run(args, **kwargs):
        nonlocal delete_attempts
        if "--delete" in args:
            delete_args.append(args)
            delete_attempts += 1
            if delete_attempts < 3:
                raise subprocess.CalledProcessError(1, args)
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"20260923T000000Z_{cid}.json").write_text(
                '{"conversation":"saved"}'
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    artifact = chat.ChatArtifact("project", tmp_path)
    artifact.chat_id = cid
    artifact.tracked = True

    result = artifact.cleanup()

    assert delete_attempts == 3
    assert delete_args[-1][0] == "/usr/bin/python3"
    assert delete_args[-1][1].endswith("/chatgpt-chats")
    assert result["deleted"] is True
    assert artifact.tracked is False


def test_project_client_retries_transient_helper_failures(monkeypatch):
    attempts = 0
    monkeypatch.setattr(chat.time, "sleep", lambda _: None)

    def fake_run(args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, "baseline\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)

    client = chat.ProjectClient("project")
    assert client.instructions() == "baseline"
    assert attempts == 3


def test_project_client_uses_system_python_for_dbus_helper(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "baseline\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    client = chat.ProjectClient("project")
    assert client.instructions() == "baseline"
    assert calls[0][0] == "/usr/bin/python3"
    assert calls[0][1].endswith("/chatgpt-project")


def test_send_project_chat_retries_only_before_submission(monkeypatch, tmp_path):
    attempts = 0
    monkeypatch.setattr(chat.time, "sleep", lambda _: None)

    def fake_run(args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps({"url": "https://chatgpt.com/c/123", "reply": "DONE"}),
            "",
        )

    monkeypatch.setattr(chat, "_run", fake_run)
    result = chat.send_project_chat(
        "g-p-project",
        "prompt",
        10,
        tmp_path / "url.txt",
        timing_file=tmp_path / "timing.json",
    )

    assert attempts == 3
    assert result["submit_attempts"] == 3


def test_send_project_chat_does_not_retry_after_enter_evidence(monkeypatch, tmp_path):
    attempts = 0
    timing = tmp_path / "timing.json"

    def fake_run(args, **kwargs):
        nonlocal attempts
        attempts += 1
        timing.write_text('{"status":"running"}')
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(chat, "_run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        chat.send_project_chat(
            "g-p-project",
            "prompt",
            10,
            tmp_path / "url.txt",
            timing_file=timing,
        )

    assert attempts == 1


def test_endpoint_capture_freezes_new_bytes_and_marks_truncation(tmp_path):
    logs = {name: tmp_path / f"{name}.log" for name in ("server", "manager", "tunnel")}
    for path in logs.values():
        path.write_text("old\n")
    selected = {
        "endpoint_id": "C300",
        "logical_arm": "C",
        "admission_envelope_revision": "r01",
        **{f"{name}_log_path": str(path) for name, path in logs.items()},
    }
    identity = runtime.TrialIdentity("R5", "run", "nonce")
    state = tmp_path / "state"
    state.mkdir()
    capture = harness._begin_endpoint_capture(selected, state, identity, "R5")
    for path in logs.values():
        with path.open("a") as handle:
            handle.write("new\n")
    evidence = harness._finalize_endpoint_capture(capture, state)
    assert not evidence["evidence_integrity_error"]
    assert (state / "endpoint-server.log").read_text() == "new\n"
    bad = tmp_path / "bad"
    bad.mkdir()
    capture = harness._begin_endpoint_capture(selected, bad, identity, "R5")
    logs["server"].write_text("")
    evidence = harness._finalize_endpoint_capture(capture, bad)
    assert evidence["evidence_integrity_error"]
    assert not (bad / "endpoint-server.log").exists()
