"""Fail-closed offline P3.6 import preflight: only reproducibility, never approval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import lsp_p36_import as importer

ROOT = Path(__file__).resolve().parents[2]


def _p34() -> dict:
    return {
        "schema": 1,
        "script_sha256": {
            name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
            for name in importer.P34_SCRIPTS
        },
        "providers": [
            {
                "provider": "typescript",
                "status": "pass",
                "initialize": "pass",
                "shutdown": "pass",
                "exit": "pass",
                "document_symbol": "fixture_pass",
                "fixture_files_unchanged": True,
                "extra_workspace_entries": 0,
                "cleanup": "group_signaled_leader_reaped",
            }
        ],
    }


def _p35() -> dict:
    return {
        "schema": "binnacle.p35/1",
        "status": "completed",
        "valid": True,
        "cleanup_verified": True,
        "snapshot_unchanged": True,
        "resident_reuse_verified": True,
        "authoritative_timings": False,
        "release_decision": "NOT_EVALUATED_READ_NO_GO",
        "provider": {
            "provider": "pyright",
            "multilspy_commit": importer.UPSTREAM_SHA,
            "read_release": "NO_GO",
        },
        "environment": {
            "harness_sha256": importer._harness_sha(ROOT),
            "uv_lock_sha256": hashlib.sha256(
                (ROOT / "uv.lock").read_bytes()
            ).hexdigest(),
        },
        "corpus": {"kind": "trusted_real_snapshot"},
        "options": {"instances": 1},
        "resources": {
            "status": "observed",
            "sampling_errors": 0,
            "tree_rss_peak_bytes": 22334455,
        },
        "operations": [
            {
                "operation": "manager_definition",
                "supported_instances": 1,
                "warm": {
                    "samples": 30,
                    "correct": 30,
                    "incorrect": 0,
                    "error": 0,
                    "timeout": 0,
                },
            }
        ],
    }


def _files(tmp_path: Path, p34: dict | None = None, p35: dict | None = None):
    a, b = tmp_path / "native34.json", tmp_path / "native35.json"
    a.write_text(json.dumps(_p34() if p34 is None else p34))
    b.write_text(json.dumps(_p35() if p35 is None else p35))
    return {
        "p34": a,
        "p35": b,
        "p34_sha256": hashlib.sha256(a.read_bytes()).hexdigest(),
        "p35_sha256": hashlib.sha256(b.read_bytes()).hexdigest(),
    }


def test_exact_local_inputs_stay_non_authorizing(tmp_path):
    result = importer.inspect(**_files(tmp_path))
    assert result["selection"] == result["resource"] == "REWORK"
    assert result["read"] == result["public_release"] == "NO-GO"
    assert result["attestations_verified"] is False
    assert result["p3_6_bundle"] == {
        "schema_version": 1,
        "safety": None,
        "capability": None,
        "measurement": None,
    }
    assert result["inputs"]["p34"]["script_digests_match_local_source"]
    assert result["inputs"]["p34"]["pyright_in_native_probe"] is False
    assert result["inputs"]["p35"]["reported_gold_calls"] == 30
    assert result["inputs"]["p35"]["authoritative_timings"] is False
    assert len(result["blockers"]) >= 5


def test_never_invokes_provider_or_external_verifier(tmp_path, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("offline importer attempted external execution or networking")

    inputs = _files(tmp_path)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert importer.inspect(**inputs)["selection"] == "REWORK"


@pytest.mark.parametrize("stage", ["p34", "p35"])
def test_artifact_byte_mismatch_is_rejected(tmp_path, stage):
    args = _files(tmp_path)
    args[stage].write_text(args[stage].read_text() + " ")
    with pytest.raises(importer.EvidenceRefused, match="evidence_sha256_mismatch"):
        importer.inspect(**args)


@pytest.mark.parametrize(
    "bad", ["duplicate", "nan", "oversize", "symlink", "directory"]
)
def test_malformed_or_nonregular_artifact_rejected(tmp_path, bad):
    args = _files(tmp_path)
    file = args["p34"]
    if bad == "duplicate":
        file.write_text('{"schema":1,"schema":1}')
    elif bad == "nan":
        file.write_text('{"schema": NaN}')
    elif bad == "oversize":
        file.write_bytes(b"x" * (importer.MAX_BYTES + 1))
    elif bad == "symlink":
        actual = file.with_name("actual.json")
        file.rename(actual)
        file.symlink_to(actual)
    else:
        file.unlink()
        file.mkdir()
    args["p34_sha256"] = (
        hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else "0" * 64
    )
    with pytest.raises(importer.EvidenceRefused):
        importer.inspect(**args)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(fixture_files_unchanged=False),
        lambda row: row.update(extra_workspace_entries=1),
        lambda row: row.update(document_symbol="unprobed"),
        lambda row: row.update(initialize="unprobed"),
        lambda row: row.update(cleanup="cleanup_unverified"),
        lambda row: row.pop("cleanup"),
    ],
    ids=["mutation", "extra", "gold", "initialize", "cleanup", "missing_cleanup"],
)
def test_p34_cannot_promote_bad_fixture_to_pass(tmp_path, mutation):
    report = _p34()
    mutation(report["providers"][0])
    with pytest.raises(
        importer.EvidenceRefused, match="p34_positive_without_gold_or_integrity"
    ):
        importer.inspect(**_files(tmp_path, p34=report))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["provider"].update(multilspy_commit="0" * 40),
        lambda r: r["environment"].update(harness_sha256="0" * 64),
        lambda r: r["operations"][0]["warm"].update(correct=29),
        lambda r: r["operations"][0].update(supported_instances=0),
        lambda r: r["resources"].update(sampling_errors=1),
        lambda r: r.update(cleanup_verified=False),
        lambda r: r.update(authoritative_timings=True),
        lambda r: r["provider"].update(read_release="GO"),
    ],
    ids=[
        "revision",
        "harness",
        "incorrect",
        "instances",
        "resources",
        "cleanup",
        "authoritative",
        "read_release",
    ],
)
def test_p35_claims_do_not_override_missing_evidence(tmp_path, mutation):
    report = _p35()
    mutation(report)
    with pytest.raises(importer.EvidenceRefused):
        importer.inspect(**_files(tmp_path, p35=report))


def test_cli_emits_only_redacted_non_authorizing_decision(tmp_path, capsys):
    args = _files(tmp_path)
    flags = [
        "--p34",
        str(args["p34"]),
        "--p34-sha256",
        args["p34_sha256"],
        "--p35",
        str(args["p35"]),
        "--p35-sha256",
        args["p35_sha256"],
    ]
    assert importer.main(flags) == 1
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["selection"] == "REWORK"
    assert str(tmp_path) not in output
    args["p34"].write_text('{"private-secret": "never-echo"}')
    assert importer.main(flags) == 2
    output = capsys.readouterr().out
    assert '"selection": "NO-GO"' in output
    assert "private-secret" not in output
    assert "never-echo" not in output


def test_caller_pins_are_not_independent_attestations(tmp_path):
    p34 = _p34()
    p34["providers"].append({"provider": "pyright", "status": "not_installed"})
    result = importer.inspect(**_files(tmp_path, p34=p34))
    assert result["inputs"]["p34"]["pyright_in_native_probe"] is True
    assert result["attestations_verified"] is False
    assert result["p3_6_bundle"]["capability"] is None
    assert result["selection"] == "REWORK"


def test_partial_report_bad_p34_script_hash_rejected(tmp_path):
    p34 = _p34()
    p34["script_sha256"][importer.P34_SCRIPTS[0]] = "0" * 64
    with pytest.raises(importer.EvidenceRefused, match="p34_script_identity_mismatch"):
        importer.inspect(**_files(tmp_path, p34=p34))
