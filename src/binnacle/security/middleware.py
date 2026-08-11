"""Fail-closed ASGI controller authentication before MCP dispatch."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeAlias

from binnacle.domain.controller import ControllerSecurityContext
from binnacle.ports.controller_auth import (
    AuthenticationRejected,
    ControllerAuthenticator,
    TransportAuthenticationInput,
)
from binnacle.security.controller import controller_context
from binnacle.security.profile import ControllerBoundaryProfile

ASGIMessage: TypeAlias = MutableMapping[str, Any]
ASGIReceive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
ASGISend: TypeAlias = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp: TypeAlias = Callable[
    [MutableMapping[str, Any], ASGIReceive, ASGISend],
    Awaitable[None],
]

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_CONTROLLER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_AUTHORIZATION_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]{0,31}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9a-z-]+$")
_FORWARDED_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-user",
        "x-real-ip",
        "x-user",
    }
)


@dataclass(frozen=True, slots=True)
class CredentialExtraction:
    """Selected credential location; validation remains the authenticator's job."""

    authorization_scheme: str | None = None
    assertion_header: str | None = None

    def __post_init__(self) -> None:
        configured = int(self.authorization_scheme is not None) + int(
            self.assertion_header is not None
        )
        if configured != 1:
            raise ValueError("exactly one controller credential source must be configured")
        if self.authorization_scheme is not None and (
            _AUTHORIZATION_SCHEME.fullmatch(self.authorization_scheme) is None
        ):
            raise ValueError("authorization_scheme is invalid")
        if self.assertion_header is not None:
            normalized = self.assertion_header.casefold()
            if (
                normalized != self.assertion_header
                or not normalized.startswith("x-")
                or len(normalized) > 64
                or any(
                    character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                    for character in normalized
                )
            ):
                raise ValueError("assertion_header is invalid")


class ControllerAuthenticationMiddleware:
    """Authenticate every request to the exact MCP route before calling FastMCP."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        profile: ControllerBoundaryProfile,
        authenticator: ControllerAuthenticator,
        extraction: CredentialExtraction,
        authentication_challenge: str,
        insufficient_scope_challenge: str | None = None,
        trusted_forwarded_headers: frozenset[str] = frozenset(),
        max_header_count: int = 64,
        max_header_bytes: int = 32_768,
        max_credential_bytes: int = 8_192,
    ) -> None:
        if not _safe_response_header(authentication_challenge, maximum=512):
            raise ValueError("authentication_challenge is invalid")
        if insufficient_scope_challenge is not None and (
            not _safe_response_header(insufficient_scope_challenge, maximum=1024)
        ):
            raise ValueError("insufficient_scope_challenge is invalid")
        if not 1 <= max_header_count <= 256:
            raise ValueError("max_header_count is outside the reviewed range")
        if not 1_024 <= max_header_bytes <= 131_072:
            raise ValueError("max_header_bytes is outside the reviewed range")
        if not 256 <= max_credential_bytes <= 32_768:
            raise ValueError("max_credential_bytes is outside the reviewed range")
        if not trusted_forwarded_headers <= _FORWARDED_HEADERS:
            raise ValueError("trusted_forwarded_headers contains an unknown header")
        self.app = app
        self.profile = profile
        self.authenticator = authenticator
        self.extraction = extraction
        self.authentication_challenge = authentication_challenge
        self.insufficient_scope_challenge = insufficient_scope_challenge
        self.trusted_forwarded_headers = trusted_forwarded_headers
        self.max_header_count = max_header_count
        self.max_header_bytes = max_header_bytes
        self.max_credential_bytes = max_credential_bytes

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if not (scope.get("type") == "http" and scope.get("path") == "/mcp"):
            await self.app(scope, receive, send)
            return

        headers = self._bounded_headers(scope)
        if headers is None:
            await _send_error(send, status=431, code="request_headers_rejected")
            return
        authority = self._single_text_header(headers, "host")
        if authority is None or authority.casefold() not in self.profile.allowed_hosts:
            await _send_error(send, status=403, code="authority_rejected")
            return
        origin = self._single_text_header(headers, "origin", required=False)
        if not self._origin_allowed(origin, headers):
            await _send_error(send, status=403, code="origin_rejected")
            return
        if self._has_untrusted_forwarded_header(headers):
            await _send_error(send, status=403, code="forwarded_header_rejected")
            return

        try:
            credential_scheme, credential, assertion = self._extract_credential(headers)
        except AuthenticationRejected as exc:
            await self._send_authentication_error(send, exc.code)
            return

        peer_kind, peer_id = _peer_identity(scope)
        request = TransportAuthenticationInput(
            method=str(scope.get("method", "")),
            path="/mcp",
            authority=authority,
            origin=origin,
            peer_kind=peer_kind,
            peer_id=peer_id,
            credential_scheme=credential_scheme,
            credential_bytes=credential,
            forwarded_assertion_bytes=assertion,
        )
        try:
            context = await self.authenticator.authenticate(request)
        except AuthenticationRejected as exc:
            await self._send_authentication_error(send, exc.code)
            return
        finally:
            del credential, assertion
        del request

        rejection = self._context_rejection(context)
        if rejection is not None:
            await self._send_authentication_error(send, rejection)
            return
        if not self.profile.required_scopes <= context.scopes:
            headers_out: list[tuple[bytes, bytes]] = []
            if self.insufficient_scope_challenge is not None:
                headers_out.append(
                    (b"www-authenticate", self.insufficient_scope_challenge.encode("ascii"))
                )
            await _send_error(
                send,
                status=403,
                code="insufficient_scope",
                headers=headers_out,
            )
            return

        sanitized_scope = dict(scope)
        sensitive_names = {"authorization", "cookie"}
        if self.extraction.assertion_header is not None:
            sensitive_names.add(self.extraction.assertion_header)
        sanitized_scope["headers"] = [
            (name, value)
            for name, value in scope.get("headers", ())
            if isinstance(name, bytes) and name.decode("latin-1").casefold() not in sensitive_names
        ]
        del headers, scope
        with controller_context(context):
            await self.app(sanitized_scope, receive, send)

    def _bounded_headers(
        self,
        scope: MutableMapping[str, Any],
    ) -> list[tuple[str, bytes]] | None:
        raw_headers = scope.get("headers", ())
        if not isinstance(raw_headers, Sequence) or len(raw_headers) > self.max_header_count:
            return None
        parsed: list[tuple[str, bytes]] = []
        total = 0
        for item in raw_headers:
            if not isinstance(item, Sequence) or len(item) != 2:
                return None
            name, value = item
            if not isinstance(name, bytes) or not isinstance(value, bytes):
                return None
            total += len(name) + len(value) + 4
            if total > self.max_header_bytes:
                return None
            try:
                normalized_name = name.decode("ascii").casefold()
            except UnicodeDecodeError:
                return None
            if (
                _HEADER_NAME.fullmatch(normalized_name) is None
                or b"\x00" in value
                or b"\r" in value
                or b"\n" in value
            ):
                return None
            parsed.append((normalized_name, value))
        return parsed

    @staticmethod
    def _single_text_header(
        headers: list[tuple[str, bytes]],
        name: str,
        *,
        required: bool = True,
    ) -> str | None:
        values = [value for header_name, value in headers if header_name == name]
        if len(values) != 1:
            if not values and not required:
                return None
            return None
        try:
            decoded = values[0].decode("ascii")
        except UnicodeDecodeError:
            return None
        return decoded if decoded and len(decoded) <= 2048 else None

    def _origin_allowed(self, origin: str | None, headers: list[tuple[str, bytes]]) -> bool:
        origin_count = sum(name == "origin" for name, _value in headers)
        if origin_count > 1:
            return False
        if any(name == "cookie" for name, _value in headers):
            return False
        if origin is None:
            return origin_count == 0 and self.profile.allow_missing_origin
        return origin.casefold() in self.profile.allowed_origins

    def _has_untrusted_forwarded_header(self, headers: list[tuple[str, bytes]]) -> bool:
        assertion_header = self.extraction.assertion_header
        return any(
            name in _FORWARDED_HEADERS
            and name not in self.trusted_forwarded_headers
            and name != assertion_header
            for name, _value in headers
        )

    def _extract_credential(
        self,
        headers: list[tuple[str, bytes]],
    ) -> tuple[str | None, bytes | None, bytes | None]:
        if self.extraction.authorization_scheme is not None:
            values = [value for name, value in headers if name == "authorization"]
            if len(values) != 1 or len(values[0]) > self.max_credential_bytes:
                raise AuthenticationRejected("authentication_required")
            scheme_bytes, separator, credential = values[0].partition(b" ")
            try:
                scheme = scheme_bytes.decode("ascii")
            except UnicodeDecodeError as exc:
                raise AuthenticationRejected() from exc
            if (
                not separator
                or scheme.casefold() != self.extraction.authorization_scheme.casefold()
                or not credential
            ):
                raise AuthenticationRejected()
            return scheme, credential, None

        assertion_header = self.extraction.assertion_header
        if assertion_header is None:
            raise AuthenticationRejected()
        values = [value for name, value in headers if name == assertion_header]
        if len(values) != 1 or not values[0] or len(values[0]) > self.max_credential_bytes:
            raise AuthenticationRejected("authentication_required")
        return None, None, values[0]

    def _context_rejection(self, context: ControllerSecurityContext) -> str | None:
        now = datetime.now(UTC)
        skew = timedelta(seconds=self.profile.clock_skew_seconds)
        if (
            context.identity.profile_id != self.profile.profile_id
            or context.profile_version != self.profile.profile_version
            or context.canonical_audience != self.profile.canonical_resource_uri
            or _SAFE_CONTROLLER_ID.fullmatch(context.identity.controller_id) is None
            or not context.issuer
            or not context.subject
            or len(context.issuer) > 2048
            or len(context.subject) > 512
            or any(_SAFE_SCOPE.fullmatch(scope) is None for scope in context.scopes)
        ):
            return "controller_profile_mismatch"
        if (
            context.authentication_time.tzinfo is None
            or context.expires_at.tzinfo is None
            or context.authentication_time > now + skew
            or context.expires_at <= context.authentication_time
            or context.expires_at < now - skew
        ):
            return "credential_freshness_rejected"
        if context.revocation_fresh_until is not None and (
            context.revocation_fresh_until.tzinfo is None
            or context.revocation_checked_at is None
            or context.revocation_checked_at.tzinfo is None
            or context.revocation_fresh_until < context.revocation_checked_at
            or context.revocation_fresh_until < now - skew
        ):
            return "revocation_freshness_rejected"
        if (
            context.revocation_checked_at is not None
            and context.revocation_checked_at.tzinfo is None
        ):
            return "revocation_freshness_rejected"
        return None

    async def _send_authentication_error(self, send: ASGISend, code: str) -> None:
        safe_code = code if _SAFE_ERROR_CODE.fullmatch(code) is not None else "invalid_credentials"
        await _send_error(
            send,
            status=401,
            code=safe_code,
            headers=[(b"www-authenticate", self.authentication_challenge.encode("ascii"))],
        )


def _peer_identity(scope: MutableMapping[str, Any]) -> tuple[str, str | None]:
    client = scope.get("client")
    if (
        isinstance(client, Sequence)
        and not isinstance(client, (str, bytes, bytearray))
        and len(client) == 2
        and isinstance(client[0], str)
        and len(client[0]) <= 255
    ):
        return "tcp", client[0]
    return "unknown", None


def _safe_response_header(value: str, *, maximum: int) -> bool:
    return (
        value.isascii()
        and 1 <= len(value) <= maximum
        and all(0x20 <= ord(character) < 0x7F for character in value)
    )


async def _send_error(
    send: ASGISend,
    *,
    status: int,
    code: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = (f'{{"error":"{code}"}}').encode("ascii")
    response_headers = list(headers or ())
    response_headers.extend(
        [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
    )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": response_headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["ControllerAuthenticationMiddleware", "CredentialExtraction"]
