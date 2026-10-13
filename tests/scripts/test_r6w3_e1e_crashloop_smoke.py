"""E1-a4: a crash-looping server or manager is a FAILED Pi deploy smoke.

A process that aborts start-up on a required import leaves a durable record;
``binnacle doctor`` turns it into a FAIL (exit 1) on every restart of the
loop, and the deploy smoke treats a failing doctor as an ALERT, which makes
``deploy`` roll back. The doctor output here is the real rendering of the real
check over a real record.
"""

from __future__ import annotations

import json
from pathlib import Path

from binnacle.diagnostics.doctor_provenance import check_startup_imports
from binnacle.diagnostics.doctor_render import render
from scripts.smoke_checks import smoke
from tests.scripts.test_smoke_checks import FakeClient, make_env


def _record(directory: Path, process: str) -> None:
    directory.mkdir(parents=True)
    record = {
        "process": process,
        "pid": 4242,
        "module": "binnacle.features.commands.job_store",
        "error_class": "ImportError",
        "where": "binnacle/features/commands/job_store.py:12",
        "time": "2026-10-12T07:00:00Z",
        "exit_code": 70,
    }
    (directory / f"{process}.json").write_text(json.dumps(record), encoding="utf-8")


def test_a_crash_looping_manager_fails_the_doctor_and_the_smoke(tmp_path: Path):
    directory = tmp_path / "startup-import"
    _record(directory, "job-manager")
    output, code = render(check_startup_imports(directory))
    assert code == 1 and "job_store" in output and "ImportError" in output
    env = make_env(tmp_path, FakeClient(), rc={"binnacle": code}, doctor_output=output)
    report = smoke(env)
    doctor = next(check for check in report.checks if check.name == "doctor")
    assert doctor.level == "alert", doctor
    assert "job-manager failed to import" in doctor.detail


def test_a_clean_start_leaves_the_doctor_check_ok(tmp_path: Path):
    output, code = render(check_startup_imports(tmp_path / "absent"))
    assert code == 0 and "no start-up import failure" in output
