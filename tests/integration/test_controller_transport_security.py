"""Keep mandatory controller-transport fixture semantics literal and complete."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from binnacle.security.profile import ControllerBoundaryProfile


def _fixture(repo_root: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        (repo_root / "tests/fixtures/mcp/controller-transport-security.yaml").read_bytes()
    )
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_mandatory_controller_fixture_keeps_security_negative_cases(repo_root: Path) -> None:
    fixture = _fixture(repo_root)
    case_ids = {case["id"] for case in fixture["cases"]}

    assert fixture["contract"] == "CONTROLLER-TRANSPORT-SECURITY"
    assert {
        "wrong-audience",
        "insufficient-scope",
        "gateway-replay",
        "tunnel-source-ip-is-not-identity",
        "inbound-token-passthrough-forbidden",
        "cross-origin-cookie-request",
        "other-controller-retry-denied-without-duplicate",
    } <= case_ids


def test_fixture_scope_is_not_aliased_to_deployment_scope(repo_root: Path) -> None:
    fixture = _fixture(repo_root)
    oauth_case = next(case for case in fixture["cases"] if case["id"] == "oauth-valid-controller")
    fixture_scopes = frozenset(oauth_case["authentication"]["token_claims"]["scope"].split())
    fixture_profile = ControllerBoundaryProfile.model_validate(
        {
            "profile_id": "fixture-profile",
            "profile_version": "1.0.0",
            "kind": "oauth-resource-server",
            "canonical_resource_uri": "https://pi.example.test/mcp",
            "required_scopes": list(fixture_scopes),
            "allowed_hosts": ["pi.example.test"],
            "allow_missing_origin": True,
        }
    )
    deployment_scopes = frozenset({"binnacle:connect", "binnacle:observe"})

    assert fixture_profile.required_scopes == frozenset({"mcp:read"})
    assert fixture_profile.required_scopes.isdisjoint(deployment_scopes)
