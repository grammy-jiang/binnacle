"""Exact GitHub event-to-checkout attestation tests."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from binnacle.evaluation.ci_attestation import (
    CI_ATTESTATION_COLLECTOR_PATHS,
    CiAttestationError,
    GitCheckoutIdentity,
    build_ci_checkout_attestation,
    ci_attestation_collector_sha256,
    ci_attestation_is_bound,
)

BASE = "1" * 40
CANDIDATE = "2" * 40
MERGE = "3" * 40
TREE = "4" * 40
COLLECTOR_COMMIT = "5" * 40
COLLECTOR_SHA256 = "6" * 64


def _build_attestation(
    *,
    event: Mapping[str, Any],
    environment: Mapping[str, str],
    checkout: GitCheckoutIdentity,
    job_name: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    return build_ci_checkout_attestation(
        event=event,
        environment=environment,
        checkout=checkout,
        collector_commit_oid=COLLECTOR_COMMIT,
        collector_sha256=COLLECTOR_SHA256,
        job_name=job_name,
        created_at=created_at,
    )


def _environment(event_name: str, sha: str) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": "grammy-jiang/binnacle",
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_WORKFLOW": "Python CI",
        "GITHUB_SHA": sha,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "2",
    }


def _pr_event() -> dict[str, object]:
    return {
        "repository": {"full_name": "grammy-jiang/binnacle"},
        "pull_request": {
            "head": {"sha": CANDIDATE},
            "base": {"sha": BASE},
        },
    }


def test_pull_request_attestation_binds_exact_merge_parents() -> None:
    value = _build_attestation(
        event=_pr_event(),
        environment=_environment("pull_request", MERGE),
        checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
        job_name="Test Python 3.13",
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert value["checkout_kind"] == "pull_request_integration"
    assert value["event_candidate_oid"] == CANDIDATE
    assert value["event_base_oid"] == BASE
    assert value["checkout_parent_oids"] == [BASE, CANDIDATE]
    assert value["collector_commit_oid"] == COLLECTOR_COMMIT
    assert value["collector_sha256"] == COLLECTOR_SHA256
    assert ci_attestation_is_bound(value)


def test_pull_request_attestation_does_not_infer_wrong_parent_order() -> None:
    value = _build_attestation(
        event=_pr_event(),
        environment=_environment("pull_request", MERGE),
        checkout=GitCheckoutIdentity(MERGE, TREE, (CANDIDATE, BASE)),
        job_name="Test Python 3.13",
    )

    assert value["checkout_kind"] == "unbound"
    assert not ci_attestation_is_bound(value)


def test_push_attestation_binds_exact_after_oid() -> None:
    event = {
        "repository": {"full_name": "grammy-jiang/binnacle"},
        "after": CANDIDATE,
    }
    value = _build_attestation(
        event=event,
        environment=_environment("push", CANDIDATE),
        checkout=GitCheckoutIdentity(CANDIDATE, TREE, (BASE,)),
        job_name="validate-contracts",
    )

    assert value["checkout_kind"] == "push_commit"
    assert value["event_after_oid"] == CANDIDATE
    assert value["event_candidate_oid"] is None


def test_repository_mismatch_is_rejected() -> None:
    event = _pr_event()
    event["repository"] = {"full_name": "attacker/other"}

    with pytest.raises(CiAttestationError, match="repository"):
        _build_attestation(
            event=event,
            environment=_environment("pull_request", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_invalid_checkout_oid_is_rejected() -> None:
    with pytest.raises(CiAttestationError, match="OID"):
        GitCheckoutIdentity("not-an-oid", TREE, (BASE, CANDIDATE))


def test_event_repository_identity_is_required() -> None:
    with pytest.raises(CiAttestationError, match="event field"):
        _build_attestation(
            event={},
            environment=_environment("pull_request", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_unsupported_event_is_rejected() -> None:
    with pytest.raises(CiAttestationError, match="reviewed CI profile"):
        _build_attestation(
            event={"repository": {"full_name": "grammy-jiang/binnacle"}},
            environment=_environment("workflow_dispatch", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_run_attempt_must_fit_attestation_schema() -> None:
    environment = _environment("pull_request", MERGE)
    environment["GITHUB_RUN_ATTEMPT"] = "1001"

    with pytest.raises(CiAttestationError, match="numeric identity"):
        _build_attestation(
            event=_pr_event(),
            environment=environment,
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(CiAttestationError, match="timezone-aware"):
        _build_attestation(
            event=_pr_event(),
            environment=_environment("pull_request", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
            created_at=datetime(2026, 8, 13),
        )


def test_push_identity_mismatch_remains_explicitly_unbound() -> None:
    value = _build_attestation(
        event={
            "repository": {"full_name": "grammy-jiang/binnacle"},
            "after": CANDIDATE,
        },
        environment=_environment("push", MERGE),
        checkout=GitCheckoutIdentity(MERGE, TREE, (BASE,)),
        job_name="validate-contracts",
    )

    assert value["checkout_kind"] == "unbound"
    assert not ci_attestation_is_bound(value)


def test_checkout_parent_count_is_bounded() -> None:
    with pytest.raises(CiAttestationError, match="too many parents"):
        GitCheckoutIdentity(MERGE, TREE, (BASE,) * 65)


def test_collector_bundle_digest_changes_with_any_reviewed_member(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    for relative in CI_ATTESTATION_COLLECTOR_PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_root / relative, target)

    expected = ci_attestation_collector_sha256(repo_root)
    assert ci_attestation_collector_sha256(tmp_path) == expected

    member = tmp_path / CI_ATTESTATION_COLLECTOR_PATHS[-1]
    member.write_bytes(member.read_bytes() + b"\n")
    assert ci_attestation_collector_sha256(tmp_path) != expected
