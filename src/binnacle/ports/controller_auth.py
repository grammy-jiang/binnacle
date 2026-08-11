"""Port for validating one request's remote controller credential."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from binnacle.domain.controller import ControllerSecurityContext


@dataclass(frozen=True, slots=True)
class TransportAuthenticationInput:
    """Bounded transport facts plus short-lived sensitive credential references."""

    method: str
    path: str
    authority: str
    origin: str | None
    peer_kind: str
    peer_id: str | None
    credential_scheme: str | None
    credential_bytes: bytes | None = field(repr=False)
    forwarded_assertion_bytes: bytes | None = field(repr=False)


class AuthenticationRejected(Exception):
    """Expected credential rejection safe to map to a generic HTTP response."""

    def __init__(self, code: str = "invalid_credentials") -> None:
        self.code = code
        super().__init__(code)


class ControllerAuthenticator(Protocol):
    """Validate a selected profile without exposing credential material."""

    async def authenticate(
        self,
        request: TransportAuthenticationInput,
    ) -> ControllerSecurityContext: ...


__all__ = [
    "AuthenticationRejected",
    "ControllerAuthenticator",
    "TransportAuthenticationInput",
]
