"""Fail-closed tests for the common controller authentication middleware."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from binnacle.domain.controller import ControllerSecurityContext
from binnacle.ports.controller_auth import (
    AuthenticationRejected,
    TransportAuthenticationInput,
)
from binnacle.security.controller import derive_controller_identity, get_controller_context
from binnacle.security.middleware import (
    ASGIMessage,
    ASGIReceive,
    ASGISend,
    ControllerAuthenticationMiddleware,
    CredentialExtraction,
)
from binnacle.security.profile import ControllerBoundaryProfile


class FixtureAuthenticator:
    def __init__(self, context: ControllerSecurityContext, *, reject: bool = False) -> None:
        self.context = context
        self.reject = reject
        self.requests: list[TransportAuthenticationInput] = []

    async def authenticate(
        self,
        request: TransportAuthenticationInput,
    ) -> ControllerSecurityContext:
        self.requests.append(request)
        if self.reject:
            raise AuthenticationRejected("fixture_rejected")
        return self.context


class RecordingApp:
    def __init__(self) -> None:
        self.calls = 0
        self.controller: ControllerSecurityContext | None = None
        self.headers: list[tuple[bytes, bytes]] = []

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        del receive
        self.calls += 1
        self.controller = get_controller_context()
        self.headers = list(scope.get("headers", ()))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def _profile(*, allow_missing_origin: bool = True) -> ControllerBoundaryProfile:
    return ControllerBoundaryProfile.model_validate(
        {
            "profile_id": "fixture-profile",
            "profile_version": "1.0.0",
            "kind": "oauth-resource-server",
            "canonical_resource_uri": "https://pi.example.test/mcp",
            "required_scopes": ["mcp:read"],
            "allowed_hosts": ["pi.example.test"],
            "allowed_origins": ["https://chatgpt.com"],
            "allow_missing_origin": allow_missing_origin,
            "clock_skew_seconds": 0,
        }
    )


def _context(
    *,
    scopes: frozenset[str] = frozenset({"mcp:read"}),
    profile_id: str = "fixture-profile",
    expires_delta: timedelta = timedelta(minutes=5),
) -> ControllerSecurityContext:
    now = datetime.now(UTC)
    audience = "https://pi.example.test/mcp"
    return ControllerSecurityContext(
        identity=derive_controller_identity(
            profile_id=profile_id,
            issuer="https://issuer.example.test",
            subject="controller-owner",
            canonical_audience=audience,
            authorized_client="chatgpt-client",
            owner_boundary="personal-workspace",
            credential_binding_id="binding",
        ),
        profile_version="1.0.0",
        issuer="https://issuer.example.test",
        subject="controller-owner",
        canonical_audience=audience,
        authorized_client="chatgpt-client",
        owner_boundary="personal-workspace",
        credential_binding_id="binding",
        scopes=scopes,
        authentication_time=now - timedelta(seconds=1),
        expires_at=now + expires_delta,
        revocation_checked_at=now,
        revocation_fresh_until=now + timedelta(minutes=1),
        connection_binding_digest=None,
        evidence_id_digest=None,
    )


async def _exercise(
    *,
    headers: list[tuple[bytes, bytes]],
    context: ControllerSecurityContext | None = None,
    path: str = "/mcp",
    reject: bool = False,
    profile: ControllerBoundaryProfile | None = None,
    extraction: CredentialExtraction | None = None,
) -> tuple[RecordingApp, FixtureAuthenticator, list[ASGIMessage]]:
    downstream = RecordingApp()
    authenticator = FixtureAuthenticator(context or _context(), reject=reject)
    middleware = ControllerAuthenticationMiddleware(
        downstream,
        profile=profile or _profile(),
        authenticator=authenticator,
        extraction=extraction or CredentialExtraction(authorization_scheme="Bearer"),
        authentication_challenge='Bearer realm="binnacle"',
        insufficient_scope_challenge=('Bearer error="insufficient_scope", scope="mcp:read"'),
    )
    sent: list[ASGIMessage] = []

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b""}

    async def send(message: ASGIMessage) -> None:
        sent.append(message)

    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "client": ("127.0.0.1", 12345),
        },
        receive,
        send,
    )
    return downstream, authenticator, sent


def _valid_headers() -> list[tuple[bytes, bytes]]:
    return [(b"host", b"pi.example.test"), (b"authorization", b"Bearer secret-value")]


@pytest.mark.anyio
async def test_valid_controller_is_request_local_and_credential_is_stripped() -> None:
    downstream, authenticator, sent = await _exercise(headers=_valid_headers())

    assert sent[0]["status"] == 204
    assert downstream.calls == 1
    assert downstream.controller is authenticator.context
    assert authenticator.requests[0].credential_bytes == b"secret-value"
    assert authenticator.requests[0].peer_kind == "tcp"
    assert all(name != b"authorization" for name, _value in downstream.headers)
    assert get_controller_context() is None


@pytest.mark.anyio
async def test_non_mcp_route_bypasses_controller_authentication() -> None:
    downstream, authenticator, sent = await _exercise(headers=[], path="/readyz")

    assert sent[0]["status"] == 204
    assert downstream.calls == 1
    assert downstream.controller is None
    assert authenticator.requests == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ([(b"host", b"pi.example.test")], 401, b"authentication_required"),
        (
            [(b"host", b"other.example.test"), (b"authorization", b"Bearer value")],
            403,
            b"authority_rejected",
        ),
        (
            [
                (b"host", b"pi.example.test"),
                (b"origin", b"https://attacker.example"),
                (b"authorization", b"Bearer value"),
            ],
            403,
            b"origin_rejected",
        ),
        (
            [
                (b"host", b"pi.example.test"),
                (b"cookie", b"ambient=value"),
                (b"authorization", b"Bearer value"),
            ],
            403,
            b"origin_rejected",
        ),
        (
            [
                (b"host", b"pi.example.test"),
                (b"x-forwarded-user", b"controller-owner"),
                (b"authorization", b"Bearer value"),
            ],
            403,
            b"forwarded_header_rejected",
        ),
    ],
)
async def test_transport_rejections_never_reach_dispatch(
    headers: list[tuple[bytes, bytes]],
    status: int,
    code: bytes,
) -> None:
    downstream, _authenticator, sent = await _exercise(headers=headers)

    assert sent[0]["status"] == status
    assert code in sent[-1]["body"]
    assert downstream.calls == 0


@pytest.mark.anyio
async def test_authenticator_rejection_is_bounded_and_challenged() -> None:
    downstream, _authenticator, sent = await _exercise(
        headers=_valid_headers(),
        reject=True,
    )

    assert sent[0]["status"] == 401
    assert (b"www-authenticate", b'Bearer realm="binnacle"') in sent[0]["headers"]
    assert b"fixture_rejected" in sent[-1]["body"]
    assert b"secret-value" not in sent[-1]["body"]
    assert downstream.calls == 0


@pytest.mark.anyio
async def test_insufficient_literal_fixture_scope_is_a_predispatch_403() -> None:
    downstream, _authenticator, sent = await _exercise(
        headers=_valid_headers(),
        context=_context(scopes=frozenset({"binnacle:observe"})),
    )

    assert sent[0]["status"] == 403
    assert b"insufficient_scope" in sent[-1]["body"]
    assert downstream.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "context",
    [
        _context(profile_id="other-profile"),
        _context(expires_delta=timedelta(minutes=-1)),
    ],
)
async def test_untrusted_returned_context_fails_closed(
    context: ControllerSecurityContext,
) -> None:
    downstream, _authenticator, sent = await _exercise(
        headers=_valid_headers(),
        context=context,
    )

    assert sent[0]["status"] == 401
    assert downstream.calls == 0


@pytest.mark.anyio
async def test_selected_assertion_header_is_consumed_without_forwarding() -> None:
    headers = [(b"host", b"pi.example.test"), (b"x-binnacle-assertion", b"assertion")]
    downstream, authenticator, sent = await _exercise(
        headers=headers,
        extraction=CredentialExtraction(assertion_header="x-binnacle-assertion"),
    )

    assert sent[0]["status"] == 204
    assert authenticator.requests[0].credential_bytes is None
    assert authenticator.requests[0].forwarded_assertion_bytes == b"assertion"
    assert all(name != b"x-binnacle-assertion" for name, _value in downstream.headers)


def test_sensitive_transport_input_repr_does_not_include_credentials() -> None:
    value = TransportAuthenticationInput(
        method="POST",
        path="/mcp",
        authority="pi.example.test",
        origin=None,
        peer_kind="tcp",
        peer_id="127.0.0.1",
        credential_scheme="Bearer",
        credential_bytes=b"highly-sensitive",
        forwarded_assertion_bytes=None,
    )

    assert "highly-sensitive" not in repr(value)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"authorization_scheme": "Bearer", "assertion_header": "x-assertion"},
        {"authorization_scheme": "bad scheme"},
        {"authorization_scheme": "Bear\x00er"},
        {"assertion_header": "X-Assertion"},
    ],
)
def test_credential_source_configuration_is_exactly_one_and_canonical(
    arguments: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        CredentialExtraction(**arguments)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"authentication_challenge": ""}, "authentication_challenge"),
        ({"authentication_challenge": "Bearer\r\nx-injected: value"}, "authentication_challenge"),
        ({"insufficient_scope_challenge": "é"}, "insufficient_scope_challenge"),
        ({"max_header_count": 0}, "max_header_count"),
        ({"max_header_bytes": 100}, "max_header_bytes"),
        ({"max_credential_bytes": 100}, "max_credential_bytes"),
        ({"trusted_forwarded_headers": frozenset({"x-invented"})}, "unknown header"),
    ],
)
def test_middleware_configuration_limits_are_bounded(
    change: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "profile": _profile(),
        "authenticator": FixtureAuthenticator(_context()),
        "extraction": CredentialExtraction(authorization_scheme="Bearer"),
        "authentication_challenge": "Bearer",
    }
    arguments.update(change)

    with pytest.raises(ValueError, match=message):
        ControllerAuthenticationMiddleware(RecordingApp(), **arguments)  # type: ignore[arg-type]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        [(b"host", b"pi.example.test"), (b"bad name", b"value")],
        [(b"host", b"pi.example.test\nother")],
        [(b"host", b"pi.example.test")] * 65,
    ],
)
async def test_malformed_or_oversized_headers_are_rejected_before_authentication(
    headers: list[tuple[bytes, bytes]],
) -> None:
    downstream, authenticator, sent = await _exercise(headers=headers)

    assert sent[0]["status"] == 431
    assert downstream.calls == 0
    assert authenticator.requests == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "authorization",
    [b"Basic value", b"Bearer", b"\xff value"],
)
async def test_malformed_authorization_value_is_a_bounded_401(
    authorization: bytes,
) -> None:
    downstream, _authenticator, sent = await _exercise(
        headers=[(b"host", b"pi.example.test"), (b"authorization", authorization)]
    )

    assert sent[0]["status"] == 401
    assert downstream.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "context",
    [
        replace(_context(), subject=""),
        replace(_context(), scopes=frozenset({"bad scope"})),
        replace(_context(), revocation_checked_at=datetime.now(UTC).replace(tzinfo=None)),
        replace(_context(), revocation_checked_at=None),
        replace(
            _context(),
            revocation_checked_at=datetime.now(UTC).replace(tzinfo=None),
            revocation_fresh_until=None,
        ),
    ],
)
async def test_malformed_authenticator_context_is_never_dispatched(
    context: ControllerSecurityContext,
) -> None:
    downstream, _authenticator, sent = await _exercise(
        headers=_valid_headers(),
        context=context,
    )

    assert sent[0]["status"] == 401
    assert downstream.calls == 0
