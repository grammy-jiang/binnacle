"""Managed unit rendering for the stable command owner."""

from pathlib import Path

import pytest

from binnacle import job_manager_unit, units


def executable(tmp_path: Path, name: str) -> Path:
    exe = tmp_path / "bin" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_job_manager_unit_is_stable_sibling_service(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    params = job_manager_unit.job_manager_params("dev", repo)
    spec = job_manager_unit.job_manager_unit_spec(params)
    assert spec.name == "binnacle-jobs.service" and spec.owner == "binnacle"
    assert f"ExecStart={repo.resolve()}/.venv/bin/binnacle-jobs\n" in spec.body
    assert "Type=notify" in spec.body and "NotifyAccess=main" in spec.body
    assert "TimeoutStartSec=30" in spec.body
    assert "Restart=always" in spec.body
    assert "KillMode=control-group" in spec.body
    assert "RuntimeDirectory=binnacle" in spec.body
    assert "ExecStartPost" not in spec.body
    assert spec.body.startswith("[Unit]\n")
    assert not spec.body.startswith("\\\n")
    text = job_manager_unit.render_job_manager_unit(params)
    marker = units.read_marker(text)
    assert marker is not None and marker.params == params
    assert job_manager_unit.render_job_manager_unit(marker.params) == text

    exe = executable(tmp_path, "binnacle-jobs")
    monkeypatch.setattr(units, "resolve_executable", lambda name, **kw: exe)
    prod = job_manager_unit.job_manager_params("prod", None)
    assert prod == {"mode": "prod", "jobs": str(exe)}


def test_job_manager_unit_rejects_bad_mode_and_missing_binary():
    with pytest.raises(units.UnitError, match="unknown jobs mode"):
        job_manager_unit.job_manager_params("staging", None)
    with pytest.raises(units.UnitError, match="needs the `jobs` executable"):
        job_manager_unit.job_manager_unit_spec({"mode": "prod"})
