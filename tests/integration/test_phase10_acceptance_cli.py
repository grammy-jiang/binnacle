"""Phase 10 evaluator and checkout-attestation command integration tests."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from scripts.ci_checkout_attestation import _git as attested_git
from scripts.ci_checkout_attestation import main as attestation_main
from scripts.phase10_acceptance import main as acceptance_main


def _git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_initialize_creates_non_promoted_manifest_and_evaluates_incomplete(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "run.json"

    assert (
        acceptance_main(
            [
                "--repo-root",
                str(repo_root),
                "initialize",
                "--manifest",
                str(manifest),
                "--run-id",
                "acceptance-cli-test",
            ]
        )
        == 0
    )
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert _load_json(manifest)["readiness"]["real_development_pi"] == "unavailable"
    assert (
        acceptance_main(
            [
                "--repo-root",
                str(repo_root),
                "evaluate",
                "--manifest",
                str(manifest),
                "--output",
                "json",
                "--require-pass",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out.splitlines()
    assert json.loads(output[-1])["verdict"] == "INCOMPLETE"


def test_pass_fixture_satisfies_require_pass(repo_root: Path) -> None:
    fixture = repo_root / "tests/fixtures/acceptance/phase10-pass.json"

    assert (
        acceptance_main(
            [
                "--repo-root",
                str(repo_root),
                "evaluate",
                "--manifest",
                str(fixture),
                "--output",
                "json",
                "--require-pass",
            ]
        )
        == 0
    )


def test_duplicate_manifest_key_is_rejected(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "duplicate.json"
    manifest.write_text('{"schema_version":"1.0","schema_version":"1.0"}\n')

    result = acceptance_main(
        [
            "--repo-root",
            str(repo_root),
            "evaluate",
            "--manifest",
            str(manifest),
        ]
    )

    assert result == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_push_checkout_command_emits_schema_valid_bound_attestation(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = _git(repo_root, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "grammy-jiang/binnacle"},
                "after": head,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "attestation.json"
    monkeypatch.setenv("GITHUB_REPOSITORY", "grammy-jiang/binnacle")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Python CI")
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    result = attestation_main(
        [
            "--repo",
            str(repo_root),
            "--event-path",
            str(event_path),
            "--output",
            str(output),
            "--job-name",
            "Code, contract, dependency, and document quality",
            "--created-at",
            "2026-08-13T00:00:00Z",
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    value = _load_json(output)
    schema = _load_json(repo_root / "schemas/acceptance/ci-checkout-attestation.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    assert value["checkout_kind"] == "push_commit"
    assert value["checkout_oid"] == head


def test_checkout_command_refuses_overwrite(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = _git(repo_root, "rev-parse", "HEAD")
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": "grammy-jiang/binnacle"},
                "after": head,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "attestation.json"
    output.write_text("existing\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "grammy-jiang/binnacle")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Python CI")
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    result = attestation_main(
        [
            "--repo",
            str(repo_root),
            "--event-path",
            str(event_path),
            "--output",
            str(output),
            "--job-name",
            "validate-contracts",
        ]
    )

    assert result == 2
    assert output.read_text(encoding="utf-8") == "existing\n"


def test_attestation_git_ignores_ambient_path(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _git(repo_root, "rev-parse", "--verify", "HEAD")
    attacker = tmp_path / "git"
    attacker.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    attacker.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert attested_git(repo_root, "rev-parse", "--verify", "HEAD") == expected
