"""Exact GitHub event-to-checkout attestation tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from binnacle.evaluation.ci_attestation import (
    CiAttestationError,
    GitCheckoutIdentity,
    build_ci_checkout_attestation,
    ci_attestation_is_bound,
)

BASE = "1" * 40
CANDIDATE = "2" * 40
MERGE = "3" * 40
TREE = "4" * 40


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
    value = build_ci_checkout_attestation(
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
    assert ci_attestation_is_bound(value)


def test_pull_request_attestation_does_not_infer_wrong_parent_order() -> None:
    value = build_ci_checkout_attestation(
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
    value = build_ci_checkout_attestation(
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
        build_ci_checkout_attestation(
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
        build_ci_checkout_attestation(
            event={},
            environment=_environment("pull_request", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_unsupported_event_is_rejected() -> None:
    with pytest.raises(CiAttestationError, match="reviewed CI profile"):
        build_ci_checkout_attestation(
            event={"repository": {"full_name": "grammy-jiang/binnacle"}},
            environment=_environment("workflow_dispatch", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_run_attempt_must_fit_attestation_schema() -> None:
    environment = _environment("pull_request", MERGE)
    environment["GITHUB_RUN_ATTEMPT"] = "1001"

    with pytest.raises(CiAttestationError, match="numeric identity"):
        build_ci_checkout_attestation(
            event=_pr_event(),
            environment=environment,
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
        )


def test_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(CiAttestationError, match="timezone-aware"):
        build_ci_checkout_attestation(
            event=_pr_event(),
            environment=_environment("pull_request", MERGE),
            checkout=GitCheckoutIdentity(MERGE, TREE, (BASE, CANDIDATE)),
            job_name="Test Python 3.13",
            created_at=datetime(2026, 8, 13),
        )


def test_push_identity_mismatch_remains_explicitly_unbound() -> None:
    value = build_ci_checkout_attestation(
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
