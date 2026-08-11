"""Actual FastMCP dispatch behind the profile-neutral authentication boundary."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx2
import pytest

from binnacle.adapters.mcp import RequestBodyLimitMiddleware, create_http_app
from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.domain.controller import ControllerSecurityContext
from binnacle.domain.mcp import (
    BinnacleProbeData,
    BinnacleProbeRequest,
    McpCallContext,
    SuccessEnvelope,
)
from binnacle.ports.controller_auth import (
    AuthenticationRejected,
    TransportAuthenticationInput,
)
from binnacle.security.controller import derive_controller_identity
from binnacle.security.middleware import (
    ControllerAuthenticationMiddleware,
    CredentialExtraction,
)
from binnacle.security.profile import ControllerBoundaryProfile

_PROTOCOL_META = "io.modelcontextprotocol/protocolVersion"
_CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo"
_CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"


class ExactFixtureAuthenticator:
    def __init__(self, *, scopes: frozenset[str]) -> None:
        now = datetime.now(UTC)
        audience = "https://pi.example.test/mcp"
        self.context = ControllerSecurityContext(
            identity=derive_controller_identity(
                profile_id="fixture-profile",
                issuer="https://issuer.example.test",
                subject="controller-owner",
                canonical_audience=audience,
                authorized_client="chatgpt-client",
                owner_boundary="personal-workspace",
                credential_binding_id="fixture-binding",
            ),
            profile_version="1.0.0",
            issuer="https://issuer.example.test",
            subject="controller-owner",
            canonical_audience=audience,
            authorized_client="chatgpt-client",
            owner_boundary="personal-workspace",
            credential_binding_id="fixture-binding",
            scopes=scopes,
            authentication_time=now,
            expires_at=now + timedelta(minutes=5),
            revocation_checked_at=now,
            revocation_fresh_until=now + timedelta(minutes=1),
            connection_binding_digest=None,
            evidence_id_digest=None,
        )

    async def authenticate(
        self,
        request: TransportAuthenticationInput,
    ) -> ControllerSecurityContext:
        if request.credential_bytes == b"fixture-token":
            return self.context
        if request.credential_bytes == b"replacement-token":
            replacement_identity = derive_controller_identity(
                profile_id="fixture-profile",
                issuer="https://issuer.example.test",
                subject="replacement-controller",
                canonical_audience="https://pi.example.test/mcp",
                authorized_client="chatgpt-client",
                owner_boundary="personal-workspace",
                credential_binding_id="fixture-binding",
            )
            return replace(
                self.context,
                identity=replacement_identity,
                subject="replacement-controller",
            )
        else:
            raise AuthenticationRejected()


def _profile() -> ControllerBoundaryProfile:
    return ControllerBoundaryProfile.model_validate(
        {
            "profile_id": "fixture-profile",
            "profile_version": "1.0.0",
            "kind": "oauth-resource-server",
            "canonical_resource_uri": "https://pi.example.test/mcp",
            "required_scopes": ["binnacle:connect", "binnacle:observe"],
            "allowed_hosts": ["pi.example.test"],
            "allowed_origins": [],
            "allow_missing_origin": True,
            "clock_skew_seconds": 0,
        }
    )


@asynccontextmanager
async def _authenticated_client(
    application: BinnacleApplication,
    *,
    scopes: frozenset[str],
) -> AsyncIterator[httpx2.AsyncClient]:
    bounded = create_http_app(application)
    assert isinstance(bounded, RequestBodyLimitMiddleware)
    secured = ControllerAuthenticationMiddleware(
        bounded,
        profile=_profile(),
        authenticator=ExactFixtureAuthenticator(scopes=scopes),
        extraction=CredentialExtraction(authorization_scheme="Bearer"),
        authentication_challenge='Bearer realm="binnacle"',
        insufficient_scope_challenge=(
            'Bearer error="insufficient_scope", scope="binnacle:connect binnacle:observe"'
        ),
    )
    inner_app = cast(Any, bounded.app)
    async with (
        inner_app.router.lifespan_context(inner_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=secured),
            base_url="https://pi.example.test",
        ) as client,
    ):
        yield client


def _modern_request(method: str, params: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "_meta": {
                _PROTOCOL_META: "2026-07-28",
                _CLIENT_INFO_META: {"name": "fixture", "version": "1"},
                _CLIENT_CAPABILITIES_META: {},
            },
        },
    }


def _headers(method: str, *, credential: bool = True) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if method == "tools/call":
        headers["Mcp-Name"] = "binnacle_probe"
    if credential:
        headers["Authorization"] = "Bearer fixture-token"
    return headers


def _jsonrpc(response: httpx2.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        line = next(line for line in response.text.splitlines() if line.startswith("data: "))
        value = json.loads(line.removeprefix("data: "))
    else:
        value = response.json()
    assert isinstance(value, dict)
    return value


@pytest.mark.anyio
async def test_authenticated_controller_lists_and_calls_read_only_catalogue(
    phase2_application: BinnacleApplication,
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_contexts: list[McpCallContext] = []
    original = compatibility_use_cases.binnacle_probe

    async def recording_probe(
        request: BinnacleProbeRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[BinnacleProbeData]:
        observed_contexts.append(context)
        return await original(request, context)

    monkeypatch.setattr(compatibility_use_cases, "binnacle_probe", recording_probe)
    scopes = frozenset({"binnacle:connect", "binnacle:observe"})
    async with _authenticated_client(phase2_application, scopes=scopes) as client:
        listed = await client.post(
            "/mcp",
            json=_modern_request("tools/list", {}),
            headers=_headers("tools/list"),
        )
        called = await client.post(
            "/mcp",
            json=_modern_request(
                "tools/call",
                {"name": "binnacle_probe", "arguments": {}},
            ),
            headers=_headers("tools/call"),
        )

    assert listed.status_code == 200
    assert len(_jsonrpc(listed)["result"]["tools"]) == 5
    assert called.status_code == 200
    assert _jsonrpc(called)["result"]["structuredContent"]["call_status"] == "succeeded"
    assert len(observed_contexts) == 1
    assert observed_contexts[0].controller is not None
    assert observed_contexts[0].controller.identity.profile_id == "fixture-profile"
    assert observed_contexts[0].controller.scopes == scopes


@pytest.mark.anyio
async def test_authentication_and_scope_failures_never_reach_tool_binding(
    phase2_application: BinnacleApplication,
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    async def should_not_run(
        request: BinnacleProbeRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[BinnacleProbeData]:
        del request, context
        nonlocal invoked
        invoked = True
        raise AssertionError("unauthorized request reached application binding")

    monkeypatch.setattr(compatibility_use_cases, "binnacle_probe", should_not_run)
    async with _authenticated_client(
        phase2_application,
        scopes=frozenset({"binnacle:connect"}),
    ) as client:
        unauthenticated = await client.post(
            "/mcp",
            json=_modern_request(
                "tools/call",
                {"name": "binnacle_probe", "arguments": {}},
            ),
            headers=_headers("tools/call", credential=False),
        )
        insufficient = await client.post(
            "/mcp",
            json=_modern_request(
                "tools/call",
                {"name": "binnacle_probe", "arguments": {}},
            ),
            headers=_headers("tools/call"),
        )

    assert unauthenticated.status_code == 401
    assert insufficient.status_code == 403
    assert invoked is False


@pytest.mark.anyio
async def test_legacy_session_cannot_move_to_another_valid_controller(
    phase2_application: BinnacleApplication,
) -> None:
    revision = "2025-11-25"
    base_headers = {
        "accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": revision,
        "Authorization": "Bearer fixture-token",
    }
    async with _authenticated_client(
        phase2_application,
        scopes=frozenset({"binnacle:connect", "binnacle:observe"}),
    ) as client:
        initialized = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": revision,
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            },
            headers=base_headers,
        )
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]
        notification = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**base_headers, "Mcp-Session-Id": session_id},
        )
        moved = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={
                **base_headers,
                "Authorization": "Bearer replacement-token",
                "Mcp-Session-Id": session_id,
            },
        )

    assert notification.status_code == 202
    assert moved.status_code == 403
    assert moved.json() == {"error": "controller_session_mismatch"}
