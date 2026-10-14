"""Default-disabled, authenticated A3 sidecar for native MCP request admission.

No launchctl, Jobs, Watchdog, bootout, bootstrap or raw-log operations.
The MCP server never exposes these RPC commands as FastMCP tools. A trusted,
independent controller must own higher-level authorization, J7 locking,
guardian, write-FD and restart proof; a drained MCP count alone is never
permission to stop the service or delete logs.

The A3 native peer+HMAC/sequence/generation proof prevents mere pathname
spoofing. As for A3 generally, a hostile same-UID account is NOT excluded;
the real production privileged controller and peer-UID separation remain an
explicit blocker until reviewed and natively tested.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from binnacle.platform.contracts.maintenance_contracts import (
    DrainSnapshot,
    MCPAdmissionGate,
)
from binnacle.platform.contracts.native_service_contracts import ServiceLease

_SOCKET = "mcp-admission.sock"
_DIR = "mcp-maintenance-admission"
_LABEL = "com.binnacle.mcp-maintenance-admission"
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_KEYS = frozenset({"version", "op", "generation"})
_NONCE_KEYS = _KEYS | {"nonce"}
_WAIT_KEYS = _NONCE_KEYS | {"timeout_s"}
_REPLY_KEYS = frozenset(
    {
        "version",
        "ok",
        "generation",
        "pause_nonce",
        "in_flight",
        "drained",
        "shutdown_authorized",
        "production_authorized",
    }
)


class MCPAdmissionRPCRefused(RuntimeError):
    """Unauthorized, malformed or unavailable admission proof."""


def _endpoint(socket_path: Path, lease: ServiceLease) -> None:
    if (
        not socket_path.is_absolute()
        or socket_path.name != _SOCKET
        or socket_path.parent.name != _DIR
        or lease.label != _LABEL
        or lease.uid != os.getuid()
        or os.getuid() == 0
        or os.geteuid() != os.getuid()
    ):
        raise MCPAdmissionRPCRefused("MCP maintenance A3 endpoint not allowlisted")


def _response(state: DrainSnapshot) -> dict[str, object]:
    if state.shutdown_authorized:
        raise MCPAdmissionRPCRefused("MCP drain never authorizes shutdown")
    return {
        "version": 1,
        "ok": True,
        "generation": state.generation,
        "pause_nonce": state.pause_nonce,
        "in_flight": state.in_flight,
        "drained": state.drained,
        "shutdown_authorized": False,
        "production_authorized": False,
    }


@dataclass(frozen=True)
class MCPAdmissionHandler:
    """Only status, fence and drain; it cannot ever lift a fence."""

    gate: MCPAdmissionGate

    def __call__(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if (
            not isinstance(payload, dict)
            or type(payload.get("version")) is not int
            or payload["version"] != 1
            or not isinstance(payload.get("generation"), str)
            or payload["generation"] != self.gate.generation
        ):
            raise MCPAdmissionRPCRefused("MCP admission generation not authenticated")
        op = payload.get("op")
        if op == "status" and set(payload) == _KEYS:
            return _response(self.gate.snapshot())
        if op == "fence" and set(payload) == _NONCE_KEYS:
            nonce = payload["nonce"]
            if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
                raise MCPAdmissionRPCRefused("invalid MCP maintenance nonce")
            try:
                return _response(
                    self.gate.fence(nonce=nonce, generation=self.gate.generation)
                )
            except RuntimeError as exc:
                raise MCPAdmissionRPCRefused("unknown MCP fence owner") from exc
        if op == "wait_drained" and set(payload) == _WAIT_KEYS:
            nonce, timeout = payload["nonce"], payload["timeout_s"]
            if (
                not isinstance(nonce, str)
                or _NONCE.fullmatch(nonce) is None
                or type(timeout) not in (float, int)
                or not math.isfinite(timeout)
                or not 0 <= timeout <= 60
            ):
                raise MCPAdmissionRPCRefused("invalid MCP wait parameters")
            try:
                return _response(
                    self.gate.wait_drained(nonce=nonce, timeout=float(timeout))
                )
            except RuntimeError as exc:
                raise MCPAdmissionRPCRefused("MCP drain owner unknown") from exc
        raise MCPAdmissionRPCRefused("MCP admission operation not allowlisted")


def _check_reply(reply: Mapping[str, object], *, generation: str) -> DrainSnapshot:
    if (
        not isinstance(reply, dict)
        or set(reply) != _REPLY_KEYS
        or type(reply["version"]) is not int
        or reply["version"] != 1
        or reply["ok"] is not True
        or reply["generation"] != generation
        or reply["shutdown_authorized"] is not False
        or reply["production_authorized"] is not False
        or type(reply["in_flight"]) is not int
        or reply["in_flight"] < 0
        or type(reply["drained"]) is not bool
    ):
        raise MCPAdmissionRPCRefused("untrusted MCP admission response")
    nonce = reply["pause_nonce"]
    if nonce is not None and (
        not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None
    ):
        raise MCPAdmissionRPCRefused("invalid MCP admission reply nonce")
    if reply["drained"] != (nonce is not None and reply["in_flight"] == 0):
        raise MCPAdmissionRPCRefused("contradictory MCP admission evidence")
    return DrainSnapshot(
        generation,
        nonce,
        reply["in_flight"],
        reply["drained"],
    )


def read_mcp_admission_a3(
    socket_path: Path,
    *,
    lease: ServiceLease,
    generation: str,
    op: str = "status",
    nonce: str | None = None,
    timeout_s: float = 4.0,
) -> DrainSnapshot:
    """One A3-authenticated RPC and one strict reply parse; no retry on UNKNOWN."""
    _endpoint(socket_path, lease)
    if (
        not isinstance(generation, str)
        or _NONCE.fullmatch(generation) is None
        or op not in {"status", "fence", "wait_drained"}
        or type(timeout_s) not in (int, float)
        or not math.isfinite(timeout_s)
        or not 0 < timeout_s <= 10
    ):
        raise MCPAdmissionRPCRefused("invalid MCP admission RPC arguments")
    request: dict[str, object] = {
        "version": 1,
        "op": op,
        "generation": generation,
    }
    if op != "status":
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            raise MCPAdmissionRPCRefused("MCP admission nonce required")
        request["nonce"] = nonce
    elif nonce is not None:
        raise MCPAdmissionRPCRefused("status takes no nonce")
    if op == "wait_drained":
        request["timeout_s"] = timeout_s
    from binnacle.platform.darwin.ipc_transport import connect_authenticated

    channel = connect_authenticated(socket_path, lease=lease, timeout_s=timeout_s)
    try:
        answer = channel.request(request, timeout_s=timeout_s)
        snapshot = _check_reply(answer, generation=generation)
        if op != "status" and snapshot.pause_nonce != nonce:
            raise MCPAdmissionRPCRefused("MCP admission nonce acknowledgement mismatch")
        return snapshot
    finally:
        channel.close()


def serve_mcp_admission_a3(
    socket_path: Path,
    *,
    lease: ServiceLease,
    gate: MCPAdmissionGate,
    stop: Event,
) -> None:
    """An explicit-only MCP-owned A3 sidecar; no independent startup yet."""
    _endpoint(socket_path, lease)
    from binnacle.platform.darwin.ipc_transport import serve_authenticated

    serve_authenticated(
        socket_path,
        lease=lease,
        handler=MCPAdmissionHandler(gate),
        stop=stop,
    )
