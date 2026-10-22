"""Offline evaluator CLI reads JSON only; no provider workload is executed."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.lsp_p36_evaluate import main
from tests.fixtures.lsp.decision_evidence import inputs


@pytest.mark.parametrize(
    "mode,code", [("accepted", 0), ("absent", 1), ("invalid", 2), ("unreadable", 2)]
)
def test_json_report_exit_status_and_private_data_redaction(
    tmp_path, capsys, mode, code
):
    request, bundle = inputs()
    request_path = tmp_path / "request.json"
    evidence_path = tmp_path / "evidence.json"
    request_path.write_text(request.model_dump_json())
    raw = bundle.model_dump(mode="json")
    if mode == "absent":
        raw["measurement"] = None
    if mode == "invalid":
        raw["private-token-never-echo"] = True
    if mode != "unreadable":
        evidence_path.write_text(json.dumps(raw))
    assert main([str(request_path), str(evidence_path)]) == code
    output = capsys.readouterr().out
    report = json.loads(output)
    assert "private-token-never-echo" not in output
    assert report["selection"] == {0: "GO", 1: "REWORK", 2: "NO-GO"}[code]


def test_module_entrypoint_with_committed_pending_bundle(tmp_path, monkeypatch, capsys):
    request, _ = inputs()
    path = tmp_path / "operator.json"
    path.write_text(request.model_dump_json())
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lsp_p36_evaluate.py",
            str(path),
            str(root / "docs/lsp-development-intelligence/p3-6-pending-evidence.json"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(root / "scripts/lsp_p36_evaluate.py"), run_name="__main__")
    assert exc.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["selection"] == "REWORK"
    assert result["observed"] is None
    assert result["tested_envelope"] is None
    assert result["reasons"] == ["P3.3:missing", "P3.4:missing", "P3.5:missing"]
