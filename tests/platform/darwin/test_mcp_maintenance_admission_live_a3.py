"""Real A3 HMAC Unix socket (test-only Linux syscall substitution) and MCP gate."""

from __future__ import annotations

import asyncio
import os
import socket
import struct
import tempfile
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from binnacle.mcp.maintenance_request_admission import FullRequestAdmissionMiddleware
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.contracts.capability_contracts import AuthorityUnknown
from binnacle.platform.darwin import (
    generation_runtime,
    ipc_transport,
    mcp_maintenance_admission_rpc,
    mcp_maintenance_admission_runtime,
)


@pytest.fixture
def linux_a3(monkeypatch: pytest.MonkeyPatch):
    if not hasattr(socket, "SO_PEERCRED"):
        pytest.skip("Linux SO_PEERCRED isolated A3 cross-platform test only")

    def linux_peer(conn: socket.socket) -> tuple[int, int]:
        data = conn.getsockopt(
            socket.SOL_SOCKET, vars(socket)["SO_PEERCRED"], struct.calcsize("3i")
        )
        pid, uid, _gid = struct.unpack("3i", data)
        return uid, pid

    def linux_publish(dirfd: int, source: str, target: str) -> None:
        try:
            os.stat(target, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("fixture cannot overwrite A3 endpoint")
        os.rename(source, target, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)

    with monkeypatch.context() as m:
        m.setattr(ipc_transport, "_native", lambda: None)
        m.setattr(ipc_transport, "_peer", linux_peer)
        m.setattr(ipc_transport, "_publish_entry", linux_publish)
        yield


@pytest.fixture
def fixture(linux_a3):
    with tempfile.TemporaryDirectory(prefix="bi30-mcp-", dir="/tmp") as folder:
        root = Path(folder) / "mcp-maintenance-admission"
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        gate = ToolAdmissionDrain()
        runtime = mcp_maintenance_admission_runtime.MCPMaintenanceAdmissionRuntime(
            root, gate
        )
        yield root, gate, runtime


def test_real_a3_generation_and_hmac_fences_actual_mcp_tool_dispatch(
    fixture,
) -> None:
    root, gate, runtime = fixture
    runtime.start(timeout_s=4)
    hits: list[str] = []
    api = FastMCP("real-a3-maintenance")
    api.add_middleware(FullRequestAdmissionMiddleware(gate))

    @api.tool
    async def change_fixture() -> str:
        hits.append("changed")
        return "ok"

    async def run() -> None:
        async with Client(api) as client:
            assert not (await client.call_tool("change_fixture")).is_error
            assert hits == ["changed"]

    asyncio.run(run())
    lease = generation_runtime.discover_service_lease(
        root=root,
        label=mcp_maintenance_admission_rpc._LABEL,
        name=mcp_maintenance_admission_rpc._SOCKET,
    )
    assert lease.generation == gate.generation
    path = root / mcp_maintenance_admission_rpc._SOCKET
    try:
        status = mcp_maintenance_admission_rpc.read_mcp_admission_a3(
            path,
            lease=lease,
            generation=gate.generation,
        )
        assert status.pause_nonce is None and not status.drained
        paused = mcp_maintenance_admission_rpc.read_mcp_admission_a3(
            path,
            lease=lease,
            generation=gate.generation,
            op="fence",
            nonce="a" * 32,
        )
        assert paused.drained and paused.pause_nonce == "a" * 32
        drained = mcp_maintenance_admission_rpc.read_mcp_admission_a3(
            path,
            lease=lease,
            generation=gate.generation,
            op="wait_drained",
            nonce="a" * 32,
        )
        assert drained.drained and drained.in_flight == 0
        assert not drained.shutdown_authorized
        with pytest.raises(
            Exception, match="maintenance|unavailable|closed|initialize handshake"
        ):
            asyncio.run(run())
        assert hits == ["changed"]
    finally:
        runtime.stop()
    assert not path.exists()
    assert not path.with_name("mcp-admission.sock.auth").exists()


def test_real_a3_wrong_generation_nonce_never_fences_gate(fixture) -> None:
    root, gate, runtime = fixture
    runtime.start(timeout_s=4)
    lease = generation_runtime.discover_service_lease(
        root=root,
        label=mcp_maintenance_admission_rpc._LABEL,
        name=mcp_maintenance_admission_rpc._SOCKET,
    )
    path = root / mcp_maintenance_admission_rpc._SOCKET
    try:
        with pytest.raises(AuthorityUnknown, match="outcome_unknown"):
            mcp_maintenance_admission_rpc.read_mcp_admission_a3(
                path,
                lease=lease,
                generation="e" * 32,
                op="fence",
                nonce="a" * 32,
            )
        assert gate.snapshot().pause_nonce is None
    finally:
        runtime.stop()
