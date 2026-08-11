"""Framework-independent authenticated controller values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ControllerProfileKind(StrEnum):
    """Controller authentication patterns permitted by the security contract."""

    OAUTH_RESOURCE_SERVER = "oauth-resource-server"
    TRUSTED_GATEWAY_ASSERTION = "trusted-gateway-assertion"


@dataclass(frozen=True, slots=True)
class ControllerIdentity:
    """Opaque local identity derived from a validated controller tuple."""

    controller_id: str
    profile_id: str


@dataclass(frozen=True, slots=True)
class ControllerSecurityContext:
    """Non-secret authentication facts available to MCP dispatch."""

    identity: ControllerIdentity
    profile_version: str
    issuer: str
    subject: str
    canonical_audience: str
    authorized_client: str | None
    owner_boundary: str | None
    credential_binding_id: str | None
    scopes: frozenset[str]
    authentication_time: datetime
    expires_at: datetime
    revocation_checked_at: datetime | None
    revocation_fresh_until: datetime | None
    connection_binding_digest: str | None
    evidence_id_digest: str | None


@dataclass(frozen=True, slots=True)
class ControllerProfileSummary:
    """Safe, immutable projection of the selected protected profile."""

    profile_id: str
    profile_version: str
    kind: ControllerProfileKind
    required_scopes: frozenset[str]
    canonical_resource_uri: str


__all__ = [
    "ControllerIdentity",
    "ControllerProfileKind",
    "ControllerProfileSummary",
    "ControllerSecurityContext",
]
