"""Strict protected controller-profile parsing tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from binnacle.domain.controller import ControllerProfileKind
from binnacle.security.profile import (
    ControllerBoundaryProfile,
    ControllerProfileProtectionError,
    load_controller_boundary_profile,
)


def _profile_values() -> dict[str, object]:
    return {
        "profile_id": "chatgpt-bootstrap-readonly-v1",
        "profile_version": "1.0.0",
        "kind": "oauth-resource-server",
        "canonical_resource_uri": "https://pi.example.test/mcp",
        "required_scopes": ["binnacle:connect", "binnacle:observe"],
        "allowed_hosts": ["pi.example.test"],
        "allowed_origins": ["https://chatgpt.com"],
        "allow_missing_origin": True,
        "clock_skew_seconds": 60,
    }


def test_profile_normalizes_finite_sets_and_builds_safe_summary() -> None:
    values = _profile_values()
    values["allowed_hosts"] = ["PI.EXAMPLE.TEST"]
    profile = ControllerBoundaryProfile.model_validate(values)

    assert profile.allowed_hosts == ("pi.example.test",)
    assert profile.required_scopes == frozenset({"binnacle:connect", "binnacle:observe"})
    assert profile.summary().kind is ControllerProfileKind.OAUTH_RESOURCE_SERVER
    assert profile.summary().canonical_resource_uri == "https://pi.example.test/mcp"


def test_protected_profile_load_does_not_consult_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = tmp_path / "controller-profile.toml"
    profile_path.write_text(
        """
profile_id = "fixture-profile"
profile_version = "1.0.0"
kind = "trusted-gateway-assertion"
canonical_resource_uri = "https://pi.example.test/mcp"
required_scopes = ["mcp:read"]
allowed_hosts = ["pi.example.test"]
allowed_origins = []
allow_missing_origin = true
clock_skew_seconds = 30
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("BINNACLE_PROFILE_ID", "untrusted-environment-value")

    profile = load_controller_boundary_profile(profile_path, require_protected=False)

    assert profile.profile_id == "fixture-profile"
    assert profile.kind is ControllerProfileKind.TRUSTED_GATEWAY_ASSERTION

    with pytest.raises(ControllerProfileProtectionError):
        load_controller_boundary_profile(profile_path)

    linked_profile = tmp_path / "linked-profile.toml"
    linked_profile.symlink_to(profile_path)
    with pytest.raises(ControllerProfileProtectionError):
        load_controller_boundary_profile(linked_profile, require_protected=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonical_resource_uri", "http://pi.example.test/mcp"),
        ("canonical_resource_uri", "https://pi.example.test/other"),
        ("canonical_resource_uri", "https://other.example.test/mcp"),
        ("canonical_resource_uri", "https://PI.EXAMPLE.TEST/mcp"),
        ("required_scopes", ["binnacle:*"]),
        ("allowed_hosts", ["*.example.test"]),
        ("allowed_hosts", ["pi..example.test"]),
        ("allowed_hosts", ["pi.example.test:70000"]),
        ("allowed_hosts", ["pi.example.test\\redirect"]),
        ("allowed_origins", ["null"]),
        ("clock_skew_seconds", 301),
    ],
)
def test_profile_rejects_non_canonical_security_values(field: str, value: object) -> None:
    values = _profile_values()
    values[field] = value

    with pytest.raises(ValidationError):
        ControllerBoundaryProfile.model_validate(values)


def test_profile_forbids_unknown_profile_specific_assumptions() -> None:
    values = _profile_values()
    values["issuer"] = "https://unobserved.example.test"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ControllerBoundaryProfile.model_validate(values)
