"""Phase 10 evaluator and checkout-attestation command integration tests."""

from __future__ import annotations

import copy
import json
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from scripts import phase10_acceptance as acceptance_script
from scripts.ci_checkout_attestation import _git as attested_git
from scripts.ci_checkout_attestation import main as attestation_main
from scripts.phase10_acceptance import main as acceptance_main

from binnacle.evaluation.phase10_acceptance import (
    ArtifactApiLookupUnavailable,
    phase10_reviewed_evidence_sha256,
)
from binnacle.evaluation.phase10_policy import load_phase10_policy


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


def _install_authenticated_artifact_api(
    *,
    fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = {
        (evidence["repository"], evidence["github_artifact_id"]): copy.deepcopy(
            evidence["github_artifact_api_observation"]
        )
        for integration in fixture["integration_generations"]
        for evidence in integration["ci_evidence"]
    }

    def fetch(
        *,
        token: str,
        repository: str,
        artifact_id: int,
        response_bytes_max: int,
        timeout_seconds: int,
    ) -> dict[str, Any] | None:
        assert token == "github-api-test-token"
        assert response_bytes_max == 65_536
        assert timeout_seconds == 15
        observation = observations.get((repository, artifact_id))
        return copy.deepcopy(observation) if observation is not None else None

    monkeypatch.setattr(acceptance_script, "_fetch_authenticated_artifact_api_observation", fetch)


def _private_token_file(tmp_path: Path) -> Path:
    path = tmp_path / "github-token"
    path.write_text("github-api-test-token\n", encoding="ascii")
    path.chmod(0o600)
    return path


class _FakeGitHubResponse:
    def __init__(self, *, status: int, value: object) -> None:
        self.status = status
        self.payload = json.dumps(value).encode("utf-8")

    def getheader(self, name: str, default: str = "") -> str:
        return "application/json; charset=utf-8" if name == "Content-Type" else default

    def read(self, amount: int | None = None) -> bytes:
        return self.payload if amount is None else self.payload[:amount]


class _FakeGitHubConnection:
    def __init__(self, response: _FakeGitHubResponse) -> None:
        self.response = response
        self.request_values: tuple[str, str, dict[str, str]] | None = None
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.request_values = method, path, headers

    def getresponse(self) -> _FakeGitHubResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_authenticated_artifact_reader_uses_fixed_bounded_github_endpoint(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_json(repo_root / "tests/fixtures/acceptance/phase10-pass.json")
    embedded = fixture["integration_generations"][0]["ci_evidence"][0][
        "github_artifact_api_observation"
    ]
    raw_response = copy.deepcopy(embedded)
    del raw_response["repository"]
    raw_response["created_at"] = "ignored authenticated API field"
    connection = _FakeGitHubConnection(_FakeGitHubResponse(status=200, value=raw_response))
    connection_arguments: dict[str, object] = {}

    def connection_factory(host: str, **kwargs: object) -> _FakeGitHubConnection:
        connection_arguments.update(host=host, **kwargs)
        return connection

    monkeypatch.setattr(acceptance_script, "HTTPSConnection", connection_factory)

    actual = acceptance_script._fetch_authenticated_artifact_api_observation(
        token="private-test-token",
        repository="grammy-jiang/binnacle",
        artifact_id=embedded["id"],
        response_bytes_max=65_536,
        timeout_seconds=15,
    )

    assert actual == embedded
    assert connection_arguments["host"] == "api.github.com"
    assert connection_arguments["timeout"] == 15
    assert connection.request_values is not None
    method, path, headers = connection.request_values
    assert method == "GET"
    assert path == f"/repos/grammy-jiang/binnacle/actions/artifacts/{embedded['id']}"
    assert headers == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer private-test-token",
        "User-Agent": "binnacle-phase10-acceptance",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    assert connection.closed


@pytest.mark.parametrize(("status", "expected"), ((404, None), (503, "unavailable")))
def test_authenticated_artifact_reader_fails_closed_on_non_success(
    status: int,
    expected: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeGitHubConnection(_FakeGitHubResponse(status=status, value={}))
    monkeypatch.setattr(
        acceptance_script,
        "HTTPSConnection",
        lambda *args, **kwargs: connection,
    )

    if expected is None:
        assert (
            acceptance_script._fetch_authenticated_artifact_api_observation(
                token="private-test-token",
                repository="grammy-jiang/binnacle",
                artifact_id=9999,
                response_bytes_max=65_536,
                timeout_seconds=15,
            )
            is None
        )
    else:
        with pytest.raises(ArtifactApiLookupUnavailable, match="lookup failed"):
            acceptance_script._fetch_authenticated_artifact_api_observation(
                token="private-test-token",
                repository="grammy-jiang/binnacle",
                artifact_id=9999,
                response_bytes_max=65_536,
                timeout_seconds=15,
            )


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


def test_pass_fixture_satisfies_require_pass(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = repo_root / "tests/fixtures/acceptance/phase10-pass.json"
    _install_authenticated_artifact_api(fixture=_load_json(fixture), monkeypatch=monkeypatch)
    token_file = _private_token_file(tmp_path)

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
                "--github-token-file",
                str(token_file),
            ]
        )
        == 0
    )


def test_github_api_token_file_must_be_private(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = repo_root / "tests/fixtures/acceptance/phase10-pass.json"
    token_file = tmp_path / "github-token"
    token_file.write_text("github-api-test-token\n", encoding="ascii")
    token_file.chmod(0o644)

    result = acceptance_main(
        [
            "--repo-root",
            str(repo_root),
            "evaluate",
            "--manifest",
            str(fixture),
            "--github-token-file",
            str(token_file),
            "--require-pass",
        ]
    )

    assert result == 2
    assert "bounded private file" in capsys.readouterr().err


def test_review_digest_command_emits_exact_owner_review_binding(
    tmp_path: Path,
    repo_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = repo_root / "tests/fixtures/acceptance/phase10-pass.json"
    manifest = _load_json(fixture)
    _install_authenticated_artifact_api(fixture=manifest, monkeypatch=monkeypatch)
    token_file = _private_token_file(tmp_path)

    assert (
        acceptance_main(
            [
                "--repo-root",
                str(repo_root),
                "review-digest",
                "--manifest",
                str(fixture),
                "--github-token-file",
                str(token_file),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out.strip()
    assert output == phase10_reviewed_evidence_sha256(manifest)
    assert output == manifest["owner_review"]["reviewed_evidence_sha256"]


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


def test_checkout_command_runs_from_reviewed_bundle_in_isolated_stdlib_mode(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    head = _git(repo_root, "rev-parse", "HEAD")
    policy = load_phase10_policy(repo_root)
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
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "scripts/ci_checkout_attestation.py",
            "--repo",
            str(repo_root),
            "--event-path",
            str(event_path),
            "--output",
            str(output),
            "--job-name",
            "dependency-free-attestation",
            "--collector-commit",
            policy.ci_attestation_collector_commit_oid,
            "--expected-collector-commit",
            policy.ci_attestation_collector_commit_oid,
            "--expected-collector-sha256",
            policy.ci_attestation_collector_sha256,
            "--created-at",
            "2026-08-13T00:00:00Z",
        ],
        cwd=repo_root,
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_REPOSITORY": "grammy-jiang/binnacle",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_WORKFLOW": "Python CI",
            "GITHUB_SHA": head,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    value = _load_json(output)
    assert value["checkout_kind"] == "push_commit"
    assert value["collector_commit_oid"] == policy.ci_attestation_collector_commit_oid
    assert value["collector_sha256"] == policy.ci_attestation_collector_sha256


def test_checkout_command_rejects_unreviewed_collector_bundle(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    head = _git(repo_root, "rev-parse", "HEAD")
    policy = load_phase10_policy(repo_root)
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
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "scripts/ci_checkout_attestation.py",
            "--repo",
            str(repo_root),
            "--event-path",
            str(event_path),
            "--output",
            str(output),
            "--job-name",
            "dependency-free-attestation",
            "--collector-commit",
            policy.ci_attestation_collector_commit_oid,
            "--expected-collector-sha256",
            "8" * 64,
        ],
        cwd=repo_root,
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_REPOSITORY": "grammy-jiang/binnacle",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_WORKFLOW": "Python CI",
            "GITHUB_SHA": head,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 2
    assert "collector bundle differs from the reviewed identity" in result.stderr
    assert not output.exists()
