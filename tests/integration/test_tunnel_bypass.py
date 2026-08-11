"""Remote reachability and source address never substitute for controller identity."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]

from binnacle.domain.controller import ControllerSecurityContext
from binnacle.ports.controller_auth import AuthenticationRejected, TransportAuthenticationInput
from binnacle.security.middleware import (
    ASGIMessage,
    ASGIReceive,
    ASGISend,
    ControllerAuthenticationMiddleware,
    CredentialExtraction,
)
from binnacle.security.profile import ControllerBoundaryProfile


class CredentialRequiredAuthenticator:
    """Fixture verifier that deliberately grants no source-address authority."""

    async def authenticate(
        self,
        request: TransportAuthenticationInput,
    ) -> ControllerSecurityContext:
        del request
        raise AuthenticationRejected("authentication_required")


@pytest.mark.anyio
async def test_connected_tunnel_and_allowlisted_source_ip_cannot_dispatch(
    repo_root: Path,
) -> None:
    fixture = cast(
        dict[str, Any],
        yaml.safe_load(
            (repo_root / "tests/fixtures/mcp/controller-transport-security.yaml").read_bytes()
        ),
    )
    case = next(
        item for item in fixture["cases"] if item["id"] == "tunnel-source-ip-is-not-identity"
    )
    dispatched = False

    async def downstream(
        scope: MutableMapping[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        del scope, receive, send
        nonlocal dispatched
        dispatched = True

    profile = ControllerBoundaryProfile.model_validate(
        {
            "profile_id": "fixture-profile",
            "profile_version": "1.0.0",
            "kind": "oauth-resource-server",
            "canonical_resource_uri": "https://pi.example.test/mcp",
            "required_scopes": ["mcp:read"],
            "allowed_hosts": ["pi.example.test"],
            "allow_missing_origin": True,
        }
    )
    middleware = ControllerAuthenticationMiddleware(
        downstream,
        profile=profile,
        authenticator=CredentialRequiredAuthenticator(),
        extraction=CredentialExtraction(authorization_scheme="Bearer"),
        authentication_challenge='Bearer realm="binnacle"',
    )
    messages: list[ASGIMessage] = []

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: ASGIMessage) -> None:
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"host", b"pi.example.test")],
            "client": ("127.0.0.1", 51234),
        },
        receive,
        send,
    )

    assert messages[0]["status"] == case["expect"]["http_status"] == 401
    assert dispatched is case["expect"]["dispatch_allowed"] is False
