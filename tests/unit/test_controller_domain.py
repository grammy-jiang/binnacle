"""Controller identity and request-context invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from binnacle.domain.controller import ControllerSecurityContext
from binnacle.security.controller import (
    controller_context,
    derive_controller_identity,
    get_controller_context,
    require_controller_context,
)


def _security_context() -> ControllerSecurityContext:
    now = datetime.now(UTC)
    return ControllerSecurityContext(
        identity=derive_controller_identity(
            profile_id="fixture-profile",
            issuer="https://issuer.example.test",
            subject="owner",
            canonical_audience="https://pi.example.test/mcp",
            authorized_client="chatgpt-client",
            owner_boundary=None,
            credential_binding_id="binding-1",
        ),
        profile_version="1.0.0",
        issuer="https://issuer.example.test",
        subject="owner",
        canonical_audience="https://pi.example.test/mcp",
        authorized_client="chatgpt-client",
        owner_boundary=None,
        credential_binding_id="binding-1",
        scopes=frozenset({"binnacle:connect", "binnacle:observe"}),
        authentication_time=now,
        expires_at=now + timedelta(minutes=5),
        revocation_checked_at=now,
        revocation_fresh_until=now + timedelta(minutes=1),
        connection_binding_digest=None,
        evidence_id_digest=None,
    )


def test_controller_identity_is_deterministic_and_non_secret() -> None:
    first = _security_context().identity
    second = _security_context().identity

    assert first == second
    assert first.controller_id.startswith("ctrl_")
    assert len(first.controller_id) == 69
    assert "owner" not in first.controller_id
    assert "issuer" not in first.controller_id


def test_explicitly_absent_identity_field_changes_the_identity_tuple() -> None:
    absent = derive_controller_identity(
        profile_id="fixture-profile",
        issuer="issuer",
        subject="subject",
        canonical_audience="audience",
        authorized_client=None,
        owner_boundary=None,
        credential_binding_id=None,
    )
    empty = derive_controller_identity(
        profile_id="fixture-profile",
        issuer="issuer",
        subject="subject",
        canonical_audience="audience",
        authorized_client="",
        owner_boundary=None,
        credential_binding_id=None,
    )

    assert absent != empty


def test_controller_context_is_bound_and_reset() -> None:
    context = _security_context()

    assert get_controller_context() is None
    with controller_context(context):
        assert get_controller_context() is context
        assert require_controller_context() is context
    assert get_controller_context() is None


def test_missing_controller_context_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        require_controller_context()
