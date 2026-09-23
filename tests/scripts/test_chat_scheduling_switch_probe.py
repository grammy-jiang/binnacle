import json

from scripts import chat_scheduling_switch_probe as probe


class FakeProject:
    def __init__(self, text: str):
        self.text = text
        self.sets: list[str] = []

    def instructions(self) -> str:
        return self.text

    def set_instructions(self, text: str) -> None:
        self.sets.append(text)
        self.text = text


class FakeProduction:
    captures = 0

    @classmethod
    def capture(cls):
        cls.captures += 1
        return cls()

    def assert_unchanged(self, after) -> None:
        assert isinstance(after, FakeProduction)


def _state_factory(base):
    def create(identity):
        path = base / identity.run_id
        path.mkdir(parents=True)
        return path

    return create


def _conversation(cid: str, reply: str):
    return {
        "conversation_id": cid,
        "conversation_template_id": probe.PROJECT_ID,
        "current_node": "a",
        "mapping": {
            "a": {
                "message": {
                    "author": {"role": "assistant"},
                    "status": "finished_successfully",
                    "content": {"parts": [reply]},
                    "metadata": {
                        "is_complete": True,
                        "model_slug": "gpt-5-6-thinking",
                        "resolved_model_slug": "gpt-5-6-thinking",
                        "thinking_effort": "max",
                    },
                }
            }
        },
    }


def test_switch_probe_success_is_exact_a_b_a(monkeypatch, tmp_path):
    project = FakeProject("ARM-A")
    FakeProduction.captures = 0

    monkeypatch.setattr(probe, "ProjectClient", lambda *args: project)
    monkeypatch.setattr(probe, "ProductionSnapshot", FakeProduction)
    monkeypatch.setattr(probe, "new_state_dir", _state_factory(tmp_path))
    monkeypatch.setattr(probe, "arm_instructions", lambda arm: f"ARM-{arm}")

    code, state = probe.run_switch_probe()

    assert code == 0
    assert project.text == "ARM-A"
    assert project.sets == ["ARM-B", "ARM-A"]
    assert FakeProduction.captures == 2
    record = json.loads((state / "switch-probe.json").read_text())
    assert record["status"] == "passed"
    assert record["checks"] == {
        "a_exact_after_b": True,
        "b_exact_readback": True,
        "initial_a_exact": True,
        "production_unchanged": True,
    }


def test_chat_isolation_uses_two_distinct_project_conversations(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_conversation("A-ID", "DONE")))
    b.write_text(json.dumps(_conversation("B-ID", "SWITCH-B-N")))

    result = probe.validate_chat_isolation(
        a,
        b,
        expected_a="DONE",
        expected_b="SWITCH-B-N",
    )

    assert result["chat_ids_distinct"] is True
    assert result["same_project"] is True
    assert result["A"]["model_slug"] == "gpt-5-6-thinking"
    assert result["B"]["thinking_effort"] == "max"


def test_switch_probe_records_chat_isolation_when_evidence_is_supplied(
    monkeypatch, tmp_path
):
    project = FakeProject("ARM-A")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_conversation("A-ID", "DONE")))
    b.write_text(json.dumps(_conversation("B-ID", "SWITCH-B-N")))

    monkeypatch.setattr(probe, "ProjectClient", lambda *args: project)
    monkeypatch.setattr(probe, "ProductionSnapshot", FakeProduction)
    monkeypatch.setattr(probe, "new_state_dir", _state_factory(tmp_path / "state"))
    monkeypatch.setattr(probe, "arm_instructions", lambda arm: f"ARM-{arm}")

    code, state = probe.run_switch_probe(
        a_conversation=a,
        b_conversation=b,
        expected_a="DONE",
        expected_b="SWITCH-B-N",
    )

    assert code == 0
    record = json.loads((state / "switch-probe.json").read_text())
    assert record["checks"]["chat_ids_distinct"] is True
    assert record["checks"]["chat_project_isolation"] is True


def test_switch_probe_rejects_non_a_initial_state(monkeypatch, tmp_path):
    project = FakeProject("UNEXPECTED")

    monkeypatch.setattr(probe, "ProjectClient", lambda *args: project)
    monkeypatch.setattr(probe, "ProductionSnapshot", FakeProduction)
    monkeypatch.setattr(probe, "new_state_dir", _state_factory(tmp_path))
    monkeypatch.setattr(probe, "arm_instructions", lambda arm: f"ARM-{arm}")

    code, state = probe.run_switch_probe()

    assert code == 1
    record = json.loads((state / "switch-probe.json").read_text())
    assert "must start from exact Arm A" in record["error"]["message"]


def test_failure_restore_evidence_is_validated(tmp_path):
    path = tmp_path / "trial.json"
    path.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": {
                    "type": "HarnessError",
                    "message": "injected failure after instructions",
                },
                "instructions": {
                    "changed": True,
                    "restored": True,
                },
                "production_unchanged": True,
            }
        )
    )

    result = probe.validate_failure_restore_evidence(path)

    assert result["instructions_changed"] is True
    assert result["instructions_restored"] is True
    assert result["production_unchanged"] is True


def test_switch_probe_records_failure_restore_evidence(monkeypatch, tmp_path):
    project = FakeProject("ARM-A")
    evidence = tmp_path / "failure.json"
    evidence.write_text(
        json.dumps(
            {
                "status": "failed",
                "error": {"type": "HarnessError", "message": "injected"},
                "instructions": {"changed": True, "restored": True},
                "production_unchanged": True,
            }
        )
    )

    monkeypatch.setattr(probe, "ProjectClient", lambda *args: project)
    monkeypatch.setattr(probe, "ProductionSnapshot", FakeProduction)
    monkeypatch.setattr(probe, "new_state_dir", _state_factory(tmp_path / "state2"))
    monkeypatch.setattr(probe, "arm_instructions", lambda arm: f"ARM-{arm}")

    code, state = probe.run_switch_probe(failure_restore_evidence=evidence)

    assert code == 0
    record = json.loads((state / "switch-probe.json").read_text())
    assert record["checks"]["failure_restore_exact"] is True
    assert record["failure_restore_evidence"]["instructions_restored"] is True
