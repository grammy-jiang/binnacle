"""Authenticated, default-disabled privileged broker protocol service."""

from __future__ import annotations

import asyncio
import os
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from binnacle.domain.privileged import (
    PRIVILEGED_PROTOCOL_ID,
    PRIVILEGED_PROTOCOL_VERSION,
    BrokerAcceptanceReceipt,
    BrokerNoAcceptReason,
    PrivilegedAction,
    PrivilegedError,
    PrivilegedTicket,
)
from binnacle.domain.privileged_restart import PrivilegedRestartCheckpointIntent
from binnacle.ports.privileged import PrivilegedEvidenceStore
from binnacle.privileged_broker.protocol import (
    PrivilegedProtocolError,
    acceptance_receipt_to_wire,
    binding_snapshot_to_wire,
    error_response,
    read_frame,
    require_peer,
    restart_checkpoint_intent_from_wire,
    routing_identity_from_wire,
    success_response,
    validate_request,
    write_frame,
)
from binnacle.privileged_broker.state import PrivilegedStoreConflict, PrivilegedStoreError
from binnacle.privileged_broker.tickets import PrivilegedTicketRejected

_READ_TIMEOUT_SECONDS: Final = 10.0
_WRITE_TIMEOUT_SECONDS: Final = 10.0
_IDENTIFIER: Final = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
ProtocolResult = Mapping[str, object] | None
StartHandler = Callable[
    [PrivilegedTicket, PrivilegedRestartCheckpointIntent | None],
    Awaitable[BrokerAcceptanceReceipt],
]


class PrivilegedServerError(RuntimeError):
    """The broker listener or server identity is unsafe."""


@dataclass(frozen=True, slots=True)
class PrivilegedServerIdentity:
    build_sha256: str
    profile_sha256: str
    broker_instance_id: str
    broker_generation: int
    expected_client_uid: int
    expected_client_gid: int
    readiness: str

    def __post_init__(self) -> None:
        for value in (self.build_sha256, self.profile_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise PrivilegedServerError("privileged server digest is invalid")
        if (
            _IDENTIFIER.fullmatch(self.broker_instance_id) is None
            or self.broker_generation < 1
            or min(self.expected_client_uid, self.expected_client_gid) < 0
        ):
            raise PrivilegedServerError("privileged server identity is invalid")
        if self.readiness not in {
            "disabled",
            "ready",
            "restricted_recovery",
            "integrity_failed",
        }:
            raise PrivilegedServerError("privileged server readiness is invalid")


class PrivilegedBrokerService:
    """Expose evidence recovery while keeping new root effects disabled by default."""

    def __init__(
        self,
        *,
        store: PrivilegedEvidenceStore,
        identity: PrivilegedServerIdentity,
        start_handler: StartHandler | None = None,
    ) -> None:
        self._store = store
        self._identity = identity
        self._start_handler = start_handler

    async def dispatch(self, request: dict[str, object]) -> ProtocolResult:
        message_type = _text(request, "type")
        if message_type == "hello":
            return {
                "protocol_id": PRIVILEGED_PROTOCOL_ID,
                "protocol_version": PRIVILEGED_PROTOCOL_VERSION,
                "build_sha256": self._identity.build_sha256,
                "profile_sha256": self._identity.profile_sha256,
                "broker_instance_id": self._identity.broker_instance_id,
                "broker_generation": self._identity.broker_generation,
                "backend_ready": self._start_handler is not None,
                "readiness": self._identity.readiness,
            }
        if message_type == "start_privileged":
            if self._start_handler is None:
                raise PrivilegedTicketRejected("privileged effect backend is not promoted")
            ticket_value = request["ticket"]
            if not isinstance(ticket_value, dict):
                raise PrivilegedProtocolError("privileged ticket must be one object")
            ticket = PrivilegedTicket.from_wire(ticket_value)
            restart_value = request["restart_intent"]
            restart_intent = (
                None
                if restart_value is None
                else restart_checkpoint_intent_from_wire(restart_value)
            )
            if (ticket.action is PrivilegedAction.CONTROLLED_RESTART) != (
                restart_intent is not None
            ):
                raise PrivilegedProtocolError(
                    "privileged restart intent shape differs from the ticket action"
                )
            return acceptance_receipt_to_wire(await self._start_handler(ticket, restart_intent))
        if message_type == "get_binding":
            operation_id = _operation_id(request)
            snapshot = await self._store.get(operation_id)
            return None if snapshot is None else binding_snapshot_to_wire(snapshot)
        if message_type == "seal_no_accept":
            try:
                reason = BrokerNoAcceptReason(_text(request, "reason"))
            except ValueError as exc:
                raise PrivilegedProtocolError("privileged seal reason is invalid") from exc
            receipt = await self._store.seal_no_accept(
                identity=routing_identity_from_wire(request["identity"]),
                reason=reason,
                trusted_time_at=_timestamp(request, "trusted_time_at"),
                retain_until=_timestamp(request, "retain_until"),
            )
            return acceptance_receipt_to_wire(receipt)
        raise PrivilegedProtocolError("privileged request type is unsupported")

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_id = "invalid"
        message_type = "invalid"
        try:
            peer_socket = writer.get_extra_info("socket")
            if peer_socket is None:
                raise PrivilegedProtocolError("privileged connection has no peer socket")
            require_peer(
                peer_socket,
                expected_uid=self._identity.expected_client_uid,
                expected_gid=self._identity.expected_client_gid,
            )
            request = await asyncio.wait_for(read_frame(reader), _READ_TIMEOUT_SECONDS)
            request_id_value = request.get("request_id")
            type_value = request.get("type")
            if isinstance(request_id_value, str):
                request_id = request_id_value
            if isinstance(type_value, str):
                message_type = type_value
            validate_request(request)
            response = success_response(request, await self.dispatch(request))
        except PrivilegedTicketRejected:
            response = error_response(
                request_id,
                message_type,
                code="privileged_ticket_rejected",
            )
        except PrivilegedStoreConflict:
            response = error_response(
                request_id,
                message_type,
                code="privileged_identity_conflict",
            )
        except (PrivilegedProtocolError, PrivilegedError, PrivilegedStoreError, ValueError):
            response = error_response(
                request_id,
                message_type,
                code="privileged_request_invalid",
            )
        except asyncio.CancelledError:
            writer.close()
            await writer.wait_closed()
            raise
        except Exception:  # noqa: BLE001 - never disclose unexpected broker exceptions.
            response = error_response(
                request_id,
                message_type,
                code="privileged_request_failed",
            )
        try:
            await asyncio.wait_for(write_frame(writer, response), _WRITE_TIMEOUT_SECONDS)
        except (OSError, TimeoutError, PrivilegedProtocolError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()


async def start_privileged_server(
    listener: socket.socket,
    service: PrivilegedBrokerService,
) -> asyncio.AbstractServer:
    if listener.family != socket.AF_UNIX or listener.type & socket.SOCK_STREAM == 0:
        raise PrivilegedServerError("privileged listener is not a Unix stream socket")
    listener.setblocking(False)
    return await asyncio.start_unix_server(service.handle_connection, sock=listener)


def inherited_listener() -> socket.socket:
    try:
        listen_pid = int(os.environ["LISTEN_PID"])
        listen_fds = int(os.environ["LISTEN_FDS"])
    except (KeyError, ValueError) as exc:
        raise PrivilegedServerError("privileged broker requires one inherited listener") from exc
    if listen_pid != os.getpid() or listen_fds != 1:
        raise PrivilegedServerError("privileged inherited-listener identity is invalid")
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX or listener.type & socket.SOCK_STREAM == 0:
        listener.detach()
        raise PrivilegedServerError("privileged inherited listener has the wrong type")
    return listener


def _operation_id(request: Mapping[str, object]) -> str:
    operation_id = _text(request, "operation_id")
    if _IDENTIFIER.fullmatch(operation_id) is None:
        raise PrivilegedProtocolError("privileged operation identity is invalid")
    return operation_id


def _text(value: Mapping[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise PrivilegedProtocolError(f"privileged {name} must be text")
    return result


def _timestamp(value: Mapping[str, object], name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, name))
    except ValueError as exc:
        raise PrivilegedProtocolError(f"privileged {name} must be a timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PrivilegedProtocolError(f"privileged {name} must include a timezone")
    return result


__all__ = [
    "PrivilegedBrokerService",
    "PrivilegedServerError",
    "PrivilegedServerIdentity",
    "inherited_listener",
    "start_privileged_server",
]
