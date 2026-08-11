"""Opaque controller identity derivation and request-local context handling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from binnacle.domain.controller import ControllerIdentity, ControllerSecurityContext

_IDENTITY_FORMAT = "binnacle-controller-identity-v1"
_CURRENT_CONTROLLER: ContextVar[ControllerSecurityContext | None] = ContextVar(
    "binnacle_controller_context",
    default=None,
)


def derive_controller_identity(
    *,
    profile_id: str,
    issuer: str,
    subject: str,
    canonical_audience: str,
    authorized_client: str | None,
    owner_boundary: str | None,
    credential_binding_id: str | None,
) -> ControllerIdentity:
    """Derive a stable non-secret ID while preserving explicitly absent tuple fields."""

    identity_tuple = {
        "authorized_client": authorized_client,
        "canonical_audience": canonical_audience,
        "credential_binding_id": credential_binding_id,
        "format": _IDENTITY_FORMAT,
        "issuer": issuer,
        "owner_boundary": owner_boundary,
        "profile_id": profile_id,
        "subject": subject,
    }
    canonical = json.dumps(
        identity_tuple,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return ControllerIdentity(controller_id=f"ctrl_{digest}", profile_id=profile_id)


@contextmanager
def controller_context(context: ControllerSecurityContext) -> Iterator[None]:
    """Bind a validated controller only for the current asynchronous request context."""

    token = _CURRENT_CONTROLLER.set(context)
    try:
        yield
    finally:
        _CURRENT_CONTROLLER.reset(token)


def get_controller_context() -> ControllerSecurityContext | None:
    """Return the validated request controller, if middleware has bound one."""

    return _CURRENT_CONTROLLER.get()


def require_controller_context() -> ControllerSecurityContext:
    """Return the validated controller or fail closed before application dispatch."""

    context = get_controller_context()
    if context is None:
        raise RuntimeError("authenticated controller context is unavailable")
    return context


__all__ = [
    "controller_context",
    "derive_controller_identity",
    "get_controller_context",
    "require_controller_context",
]
