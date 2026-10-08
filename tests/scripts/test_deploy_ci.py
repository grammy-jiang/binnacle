"""Required CI results, rather than arbitrary workflows, gate deployment."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.deploy_flow import ci_state
from tests.deploy_ci_fakes import (
    API_ROOT,
    CONTEXTS,
    RUNS_PATH,
    SHA,
    GitHub,
    pages,
    workflow,
)


def test_optional_review_failure_does_not_veto_complete_required_ci(
    tmp_path: Path,
) -> None:
    host = GitHub()
    host.legacy_runs.append(
        {"name": "Optional review", "status": "completed", "conclusion": "failure"}
    )
    assert ci_state(host.env(tmp_path), SHA)[0] == "success"


def test_unrelated_workflow_success_cannot_replace_required_ci(tmp_path: Path) -> None:
    host = GitHub()
    host.runs = []
    host.legacy_runs = [
        {"name": "Optional review", "status": "completed", "conclusion": "success"}
    ]
    assert ci_state(host.env(tmp_path), SHA)[0] != "success"


@pytest.mark.parametrize("name", CONTEXTS)
def test_every_required_job_must_exist(tmp_path: Path, name: str) -> None:
    host = GitHub()
    host.jobs[101] = [job for job in host.jobs[101] if job["name"] != name]
    assert ci_state(host.env(tmp_path), SHA)[0] != "success"


@pytest.mark.parametrize("name", CONTEXTS)
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "neutral"])
def test_every_required_job_must_succeed(
    tmp_path: Path, name: str, conclusion: str
) -> None:
    host = GitHub()
    job = next(job for job in host.jobs[101] if job["name"] == name)
    job["conclusion"] = conclusion
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_new_attempt_blocks_before_replacement_jobs_exist(
    tmp_path: Path, status: str
) -> None:
    host = GitHub()
    host.runs[0].update(run_attempt=2, status=status, conclusion=None)
    assert ci_state(host.env(tmp_path), SHA)[0] == "pending"


def test_failed_rerun_cannot_reuse_old_success(tmp_path: Path) -> None:
    host = GitHub()
    host.runs[0].update(run_attempt=2, conclusion="failure")
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


def test_partial_rerun_selects_explicit_attempt_per_job(tmp_path: Path) -> None:
    host = GitHub()
    host.jobs[101][0]["conclusion"] = "failure"
    host.checks[101000]["conclusion"] = "failure"
    host.runs[0]["run_attempt"] = 2
    host.add_jobs(host.runs[0], ("Code quality",))
    assert ci_state(host.env(tmp_path), SHA)[0] == "success"


def test_ambiguous_duplicate_within_selected_attempt_fails(tmp_path: Path) -> None:
    host = GitHub()
    host.add_jobs(host.runs[0], ("Code quality",))
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize(
    "status,conclusion,want",
    [
        ("completed", "failure", "failed"),
        ("in_progress", None, "pending"),
    ],
)
def test_all_ci_suites_are_binding(
    tmp_path: Path, status: str, conclusion: str | None, want: str
) -> None:
    host = GitHub()
    second = workflow(102)
    second.update(status=status, conclusion=conclusion)
    host.runs.append(second)
    host.add_jobs(second)
    assert ci_state(host.env(tmp_path), SHA)[0] == want


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "a" * 40),
        ("run_id", 102),
        ("run_attempt", 0),
        ("run_attempt", 2),
        ("run_attempt", True),
        ("check_run_url", "https://api.github.com/repos/other/repo/check-runs/101000"),
    ],
)
def test_foreign_or_invalid_job_cannot_grant_eligibility(
    tmp_path: Path, field: str, value: Any
) -> None:
    host = GitHub()
    host.jobs[101][0][field] = value
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "a" * 40),
        ("id", 2),
        ("name", "Other"),
        ("app", {"id": 999}),
        ("check_suite", {"id": 999}),
        ("status", "in_progress"),
        ("conclusion", "failure"),
    ],
)
def test_selected_check_must_authenticate_the_job(
    tmp_path: Path, field: str, value: Any
) -> None:
    host = GitHub()
    host.checks[101000][field] = value
    assert ci_state(host.env(tmp_path), SHA)[0] != "success"


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "a" * 40),
        ("run_attempt", 0),
        ("run_attempt", True),
        ("path", ".github/workflows/optional.yml"),
        ("check_suite_id", None),
    ],
)
def test_foreign_or_malformed_workflow_fails(
    tmp_path: Path, field: str, value: Any
) -> None:
    host = GitHub()
    host.runs[0][field] = value
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize("ref", ["main", "refs/heads/fix/ci", "b" * 40])
def test_canonical_workflow_accepts_valid_ref_suffix(tmp_path: Path, ref: str) -> None:
    host = GitHub()
    host.runs[0]["path"] = f".github/workflows/ci.yml@{ref}"
    assert ci_state(host.env(tmp_path), SHA)[0] == "success"


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/other.yml@main",
        ".github/workflows/ci.yml-extra@main",
        ".github/workflows/ci.yml@",
        ".github/workflows/ci.yml@bad ref",
        ".github/workflows/ci.yml@ref..name",
        ".github/workflows/ci.yml@refs//main",
        ".github/workflows/ci.yml@--help",
        ".github/workflows/ci.yml@main.lock",
    ],
)
def test_ref_suffix_never_weakens_workflow_identity(tmp_path: Path, path: str) -> None:
    host = GitHub()
    host.runs[0]["path"] = path
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "tag"),
        ("enforcement", "disabled"),
        ("name", "other policy"),
        ("conditions", {"ref_name": {"include": ["refs/heads/other"], "exclude": []}}),
        ("rules", []),
    ],
)
def test_only_active_master_policy_can_grant_eligibility(
    tmp_path: Path, field: str, value: Any
) -> None:
    host = GitHub()
    host.policy[field] = value
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [{"context": "", "integration_id": 15368}],
        [{"context": "Code quality", "integration_id": 999}],
        [{"context": "Code quality", "integration_id": 15368}] * 2,
    ],
)
def test_invalid_required_check_policy_fails(tmp_path: Path, checks: Any) -> None:
    host = GitHub()
    host.policy["rules"][2]["parameters"]["required_status_checks"] = checks
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


def test_missing_policy_fails_without_querying_ci(tmp_path: Path) -> None:
    host = GitHub()

    def missing(path: Path) -> str:
        raise FileNotFoundError(path)

    assert ci_state(replace(host.env(tmp_path), read=missing), SHA)[0] == "failed"


def test_multiple_job_pages_are_complete_before_success(tmp_path: Path) -> None:
    host = GitHub()
    host.add_jobs(host.runs[0], tuple(f"Optional {i}" for i in range(101)))
    assert ci_state(host.env(tmp_path), SHA)[0] == "success"


@pytest.mark.parametrize("count", [100, 200])
def test_complete_page_boundaries_are_accepted(tmp_path: Path, count: int) -> None:
    host = GitHub()
    host.add_jobs(host.runs[0], tuple(f"Extra {i}" for i in range(count - 7)))
    assert ci_state(host.env(tmp_path), SHA)[0] == "success"


@pytest.mark.parametrize("count", [1000, 1001])
def test_workflow_search_limit_cannot_prove_complete_inventory(
    tmp_path: Path, count: int
) -> None:
    host = GitHub()
    host.runs = [workflow(i) for i in range(1, count + 1)]
    host.jobs.clear()
    host.checks.clear()
    for run in host.runs:
        host.add_jobs(run)
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        [{"total_count": 1, "workflow_runs": []}],
        [{"total_count": True, "workflow_runs": [workflow()]}],
        [{"total_count": 2, "workflow_runs": [workflow(), workflow()]}],
        [{"total_count": 1001, "workflow_runs": [workflow()]}],
        [
            {"total_count": 2, "workflow_runs": [workflow()]},
            {"total_count": 1, "workflow_runs": [workflow(102)]},
        ],
    ],
)
def test_incomplete_or_malformed_workflow_pages_fail(
    tmp_path: Path, payload: Any
) -> None:
    host = GitHub()
    host.overrides[RUNS_PATH] = (0, payload)
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


def test_partial_job_inventory_never_accepts_seven_successes(tmp_path: Path) -> None:
    host = GitHub()
    payload = pages("jobs", host.jobs[101])
    payload[0]["total_count"] = 107
    host.overrides[f"{API_ROOT}/actions/runs/101/jobs?filter=all&per_page=100"] = (
        0,
        payload,
    )
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


@pytest.mark.parametrize("response", [(1, "API unavailable"), (0, "not JSON")])
def test_api_errors_fail_closed(tmp_path: Path, response: tuple[int, str]) -> None:
    host = GitHub()
    host.overrides[RUNS_PATH] = response
    assert ci_state(host.env(tmp_path), SHA)[0] == "failed"


def test_rerun_during_observation_requires_new_snapshot(tmp_path: Path) -> None:
    host = GitHub()
    changed = deepcopy(host.runs[0])
    changed.update(run_attempt=2, status="queued", conclusion=None)
    host.overrides[f"{API_ROOT}/actions/runs/101"] = (0, changed)
    assert ci_state(host.env(tmp_path), SHA)[0] == "pending"


def test_new_ci_run_during_observation_requires_new_snapshot(tmp_path: Path) -> None:
    host = GitHub()
    original = host.run
    reads = 0

    def changed(argv: Any, timeout: float) -> tuple[int, str]:
        nonlocal reads
        if argv[-1] == RUNS_PATH:
            reads += 1
            if reads == 2:
                host.runs.append(workflow(102))
        return original(argv, timeout)

    assert ci_state(replace(host.env(tmp_path), run=changed), SHA)[0] == "pending"
