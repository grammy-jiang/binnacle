"""Frozen evaluation profile and case-source validation."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from binnacle.evaluation import profile as profile_module
from binnacle.evaluation.cases import load_evaluation_cases
from binnacle.evaluation.profile import EvaluationSourceError, load_evaluation_profile


def test_frozen_profile_and_all_cases_cross_validate(repo_root: Path) -> None:
    profile = load_evaluation_profile(repo_root)
    cases = load_evaluation_cases(repo_root, profile=profile)

    assert profile.schema_version == "1.1"
    assert profile.sha256 == "cf94e6057bf55876d0b6d27613f36ef1b650ac11dcd8619c4d765eb7c2f93e89"
    assert profile.case_manifest.sha256 == (
        "b0fe3fc8204eb18f611c662c9772bc9554fee39e322c3f29f7b043730e5ee7af"
    )
    assert len(profile.canonical_statuses) == 12
    assert len(cases.cases) == 63
    assert cases.require("endpoint-connect").axis == "connectivity"
    assert cases.require("latency-context-cost").risk_class == "latency_and_context_cost"
    assert cases.require("endpoint-connect").allows_status("server-not-implemented") is False
    assert cases.require("write-entitlement-and-confirmation").allows_status(
        "server-not-implemented"
    )
    assert cases.require("resources-probe").allows_status("not-applicable")


def test_unknown_case_and_status_cannot_be_invented(repo_root: Path) -> None:
    profile = load_evaluation_profile(repo_root)
    cases = load_evaluation_cases(repo_root, profile=profile)

    with pytest.raises(EvaluationSourceError, match="unknown evaluation status"):
        profile.requires_status("looks-good")
    with pytest.raises(EvaluationSourceError, match="unknown evaluation case"):
        cases.require("invented-case")


def test_profile_load_fails_when_exact_case_bytes_change(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "repo"
    (destination / "spec/mcp").mkdir(parents=True)
    shutil.copy2(
        repo_root / "spec/mcp/evaluation-profile.yaml",
        destination / "spec/mcp/evaluation-profile.yaml",
    )
    case_path = destination / "spec/mcp/evaluation-cases.yaml"
    case_path.write_bytes(
        (repo_root / "spec/mcp/evaluation-cases.yaml").read_bytes() + b"\n# changed\n"
    )

    with pytest.raises(EvaluationSourceError, match="digest does not match"):
        load_evaluation_profile(destination)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: profile_module._mapping([], "value"), "must be an object"),
        (lambda: profile_module._string({}, "value"), "non-empty string"),
        (lambda: profile_module._digest({"value": "x" * 64}, "value"), "SHA-256"),
        (
            lambda: profile_module._integer({"value": True}, "value", minimum=1, maximum=2),
            "reviewed range",
        ),
        (lambda: profile_module._string_tuple([], "value"), "non-empty array"),
        (lambda: profile_module._string_tuple([""], "value"), "invalid identifier"),
        (lambda: profile_module._safe_repo_path("../escape"), "escapes"),
    ],
)
def test_frozen_profile_primitive_validators_fail_closed(
    call: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(EvaluationSourceError, match=message):
        call()
