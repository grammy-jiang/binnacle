"""P3.3 characterize real Pyright behavior; NO OS sandbox or READ certificate.

Only synthetic, disposable Python sources/home and a synthetic environment
marker are used. The CLI returns sanitized aggregate telemetry, never raw
syscall traces, parent environment values, source content or host paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("unsupported", ("relative/path", ""))
@pytest.mark.asyncio
async def test_auditor_does_not_accept_nonabsolute_binary_paths(unsupported):
    from scripts.lsp_p33_side_effect_probe import characterize

    with pytest.raises(ValueError, match="absolute local file"):
        await characterize(Path(unsupported))


def test_auditor_real_pyright_sanitized_aggregate_only():
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("real Pyright must be explicitly enabled for private audit")
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.lsp_p33_side_effect_probe",
            "--binary",
            binary,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=35,
    )
    data = json.loads(result.stdout)
    assert data["provider_spawn_intercepted"]
    assert data["synthetic_marker_forwarded"] is False
    assert data["environment_mode"] == "p33_admitted_node_minimal_env"
    assert data["environment_entry_count"] <= 5
    assert data["clean_parent_exit"]
    assert data["cleanup_unverified"] is False
    assert data["read_eligibility"] == "NOT_PROVEN"
    assert data["scope"] == "synthetic_workspace_plus_synthetic_home_only"
    assert data["synthetic_audit_files_changed"] == []
    assert data["synthetic_audit_files_deleted"] == []
    assert data["synthetic_audit_files_created"] == []
    assert data["network_sampling_complete"] in (True, False)
    assert data["network_samples"] > 0
    # Never serialize environment values, host path metadata or LSP frames.
    assert "synthetic-only" not in result.stdout
    assert "not-a-real-secret" not in result.stdout
    assert binary not in result.stdout
    assert "file:///" not in result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.1.412", "unexpected"])
async def test_auditor_refuses_to_label_an_unverified_provider_version(
    tmp_path, version
):
    from scripts.lsp_p33_side_effect_probe import characterize

    binary = tmp_path / "langserver.index.js"
    binary.write_text("#!/usr/bin/env node\n")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "pyright", "version": version})
    )
    with pytest.raises(ValueError, match="provider identity"):
        await characterize(binary)


def test_audit_cli_failure_does_not_emit_paths_or_tracebacks():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.lsp_p33_side_effect_probe",
            "--binary",
            "synthetic-private-path",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "audit_status": "failed",
        "read_eligibility": "NOT_PROVEN",
    }
    assert result.stderr == ""
