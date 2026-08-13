"""Bounded one-request-per-connection client for the root broker UDS."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from binnacle.adapters.privileged_ipc.protocol import (
    PrivilegedProtocolError,
    acceptance_receipt_from_wire,
    binding_snapshot_from_wire,
    read_frame,
    request_envelope,
    require_peer,
    restart_checkpoint_intent_to_wire,
    routing_identity_to_wire,
    validate_response,
    write_frame,
)
from binnacle.domain.privileged import (
    BrokerAcceptanceReceipt,
    BrokerBindingSnapshot,
    BrokerNoAcceptReason,
    PrivilegedBrokerHello,
    PrivilegedTicket,
    PrivilegedTicketRoutingIdentity,
    canonical_timestamp,
)
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointIntent
from binnacle.ports.privileged import PrivilegedBrokerUnavailable

_Decoded = TypeVar("_Decoded")


class PrivilegedClientError(PrivilegedBrokerUnavailable):
    """The broker is unavailable, incompatible, or returned invalid evidence."""


@dataclass(frozen=True, slots=True)
class PrivilegedClientSettings:
    socket_path: Path = Path("/run/binnacle-privileged/broker.sock")
    expected_peer_uid: int = 0
    expected_peer_gid: int = 0
    connect_timeout_seconds: float = 2.0
    request_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if min(self.expected_peer_uid, self.expected_peer_gid) < 0:
            raise PrivilegedClientError("privileged broker peer identity is not configured")
        if not 0.1 <= self.connect_timeout_seconds <= 10:
            raise PrivilegedClientError("privileged connect timeout is outside the safe range")
        if not 0.1 <= self.request_timeout_seconds <= 60:
            raise PrivilegedClientError("privileged request timeout is outside the safe range")
        if not self.socket_path.is_absolute():
            raise PrivilegedClientError("privileged socket path must be absolute")


class PrivilegedClient:
    def __init__(self, settings: PrivilegedClientSettings) -> None:
        self._settings = settings

    async def hello(self) -> PrivilegedBrokerHello:
        value = await self._exchange("hello")
        raw = _exact_result(
            value,
            {
                "protocol_id",
                "protocol_version",
                "build_sha256",
                "profile_sha256",
                "broker_instance_id",
                "broker_generation",
                "backend_ready",
                "readiness",
            },
        )
        return _decode_result(
            lambda: PrivilegedBrokerHello(
                protocol_id=_text(raw, "protocol_id"),
                protocol_version=_text(raw, "protocol_version"),
                build_sha256=_text(raw, "build_sha256"),
                profile_sha256=_text(raw, "profile_sha256"),
                broker_instance_id=_text(raw, "broker_instance_id"),
                broker_generation=_integer(raw, "broker_generation"),
                backend_ready=_boolean(raw, "backend_ready"),
                readiness=_text(raw, "readiness"),
            )
        )

    async def start(
        self,
        ticket: PrivilegedTicket,
        restart_intent: PrivilegedRestartCheckpointIntent | None = None,
    ) -> BrokerAcceptanceReceipt:
        value = await self._exchange(
            "start_privileged",
            ticket=ticket.to_wire(),
            restart_intent=(
                None
                if restart_intent is None
                else restart_checkpoint_intent_to_wire(restart_intent)
            ),
        )
        return _decode_result(lambda: acceptance_receipt_from_wire(value))

    async def get(self, operation_id: str) -> BrokerBindingSnapshot | None:
        value = await self._exchange("get_binding", operation_id=operation_id)
        return None if value is None else _decode_result(lambda: binding_snapshot_from_wire(value))

    async def seal_no_accept(
        self,
        *,
        identity: PrivilegedTicketRoutingIdentity,
        reason: BrokerNoAcceptReason,
        trusted_time_at: datetime,
        retain_until: datetime,
    ) -> BrokerAcceptanceReceipt:
        value = await self._exchange(
            "seal_no_accept",
            identity=routing_identity_to_wire(identity),
            reason=reason.value,
            trusted_time_at=canonical_timestamp(trusted_time_at),
            retain_until=canonical_timestamp(retain_until),
        )
        return _decode_result(lambda: acceptance_receipt_from_wire(value))

    async def _exchange(self, message_type: str, **fields: object) -> object:
        request_id = f"req_{secrets.token_hex(16)}"
        request = request_envelope(request_id, message_type, **fields)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._settings.socket_path),
                timeout=self._settings.connect_timeout_seconds,
            )
            try:
                peer_socket = writer.get_extra_info("socket")
                if peer_socket is None:
                    raise PrivilegedClientError("privileged connection has no peer socket")
                require_peer(
                    peer_socket,
                    expected_uid=self._settings.expected_peer_uid,
                    expected_gid=self._settings.expected_peer_gid,
                )
                await asyncio.wait_for(
                    write_frame(writer, request),
                    timeout=self._settings.request_timeout_seconds,
                )
                response = await asyncio.wait_for(
                    read_frame(reader),
                    timeout=self._settings.request_timeout_seconds,
                )
                validate_response(response, request_id=request_id)
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, TimeoutError, PrivilegedProtocolError) as exc:
            raise PrivilegedClientError("privileged request failed closed") from exc
        if response["type"] != f"{message_type}_result":
            raise PrivilegedClientError("privileged response type is invalid")
        if not response["ok"]:
            error = response["error"]
            if not isinstance(error, dict) or set(error) != {"code"}:
                raise PrivilegedClientError("privileged error response is invalid")
            code = error.get("code")
            if not isinstance(code, str):
                raise PrivilegedClientError("privileged error code is invalid")
            raise PrivilegedClientError(f"privileged broker rejected request: {code}")
        return response["result"]


def _exact_result(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivilegedClientError("privileged result fields are invalid")
    return value


def _decode_result(factory: Callable[[], _Decoded]) -> _Decoded:
    try:
        return factory()
    except (PrivilegedProtocolError, ValueError) as exc:
        raise PrivilegedClientError("privileged broker returned invalid evidence") from exc


def _text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise PrivilegedClientError(f"privileged {name} is invalid")
    return result


def _integer(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise PrivilegedClientError(f"privileged {name} is invalid")
    return result


def _boolean(value: Mapping[str, object], name: str) -> bool:
    result = value.get(name)
    if not isinstance(result, bool):
        raise PrivilegedClientError(f"privileged {name} is invalid")
    return result


__all__ = ["PrivilegedClient", "PrivilegedClientError", "PrivilegedClientSettings"]
