"""R6W3-06: a current bootstrap failure with unknown Git SHA must block deploy.

The tests connect actual on-disk failure receipt -> doctor Check. A failing
check makes ``binnacle doctor`` exit non-zero, which stops the deploy gate
(``scripts/smoke_checks.py``). There are no service launches or production
record writes.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from binnacle import startup_imports
from binnacle.diagnostics import doctor_provenance
from binnacle.diagnostics.doctor_provenance import check_startup_imports


def _receipt_to_gate(tmp_path, *, recorded_revision, current_revision):
    failure = startup_imports.StartupImportFailed(
        "binnacle.platform.darwin.job_manager_records",
        "SyntaxError",
        "binnacle/platform/darwin/job_manager_records.py:9",
    )
    root = startup_imports.record_dir(tmp_path)
    assert startup_imports.record_start_failure("job-manager", failure, tmp_path)
    receipt = startup_imports.record_path(tmp_path, "job-manager")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["module"] == failure.module
    data["revision"] = recorded_revision
    receipt.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    checks = check_startup_imports(root, revision=current_revision)
    assert len(checks) == 1
    assert checks[0].group == "startup"
    return failure, data, checks[0]


@pytest.mark.parametrize(
    "unverified",
    [
        None,
        "",
        "unknown",
        "installed",
        "?",
        "not-a-git-sha",
        "a" * 11,
        "b" * 41,
        "ABCDEF123456",
        12345,
    ],
)
def test_unverifiable_recorded_revision_is_a_blocking_current_failure(
    tmp_path, unverified
):
    failure, data, check = _receipt_to_gate(
        tmp_path, recorded_revision=unverified, current_revision="d" * 12
    )
    assert check.status == "fail"
    assert not check.detail.startswith("STALE:")
    assert failure.module in check.detail
    assert data["revision"] == unverified


@pytest.mark.parametrize("current", ["unknown", "installed", "", "?"])
def test_unverifiable_current_checkout_is_never_claimed_stale(tmp_path, current):
    _failure, _data, check = _receipt_to_gate(
        tmp_path, recorded_revision="a" * 12, current_revision=current
    )
    assert check.status == "fail"
    assert not check.detail.startswith("STALE:")


@pytest.mark.parametrize(
    ("recorded", "current", "expect"),
    [
        ("a" * 12, "a" * 12, "fail"),
        ("a" * 12, "b" * 12, "warn"),
        ("a" * 40, "b" * 40, "warn"),
        ("a" * 12 + "+dirty", "b" * 12, "warn"),
    ],
)
def test_only_distinct_verified_git_versions_get_stale_warning(
    tmp_path, recorded, current, expect
):
    _failure, _data, check = _receipt_to_gate(
        tmp_path, recorded_revision=recorded, current_revision=current
    )
    assert check.status == expect
    assert check.detail.startswith("STALE:") == (expect == "warn")


def test_real_provenance_import_failure_writes_unknown_then_gate_refuses(
    tmp_path, monkeypatch
):
    # Same condition as when required provenance itself could not load:
    # do not reimport it while writing the error record.
    monkeypatch.setitem(sys.modules, "binnacle.provenance", None)
    failure = startup_imports.StartupImportFailed(
        "binnacle.provenance", "SyntaxError", "binnacle/provenance.py:1"
    )
    assert startup_imports.record_start_failure("mcp-server", failure, tmp_path)
    record = startup_imports.record_path(tmp_path, "mcp-server")
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["revision"] == "unknown"
    assert data["module"] == "binnacle.provenance"
    (check,) = check_startup_imports(
        startup_imports.record_dir(tmp_path), revision="d" * 12
    )
    assert check.status == "fail"
    assert "binnacle.provenance" in check.detail


def test_missing_revision_argument_uses_actual_runtime_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor_provenance,
        "runtime_provenance",
        lambda: SimpleNamespace(revision="unknown"),
    )
    _failure, _data, check = _receipt_to_gate(
        tmp_path, recorded_revision="a" * 12, current_revision=None
    )
    assert check.status == "fail"
