"""Explicit-only A3 sidecar lifetime: readiness, fail-closed config and cleanup."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.darwin import generation_runtime
from binnacle.platform.darwin import mcp_maintenance_admission_runtime as runtime
from binnacle.platform.darwin.mcp_maintenance_admission_rpc import (
    MCPAdmissionRPCRefused,
)


@pytest.fixture
def config():
    # Darwin sockaddr_un supports at most 103 pathname bytes; pytest tmp_path
    # test-name subdirectories can exceed it even on Linux.
    with tempfile.TemporaryDirectory(prefix="bi30-mcp-", dir="/tmp") as private:
        root = Path(private) / "mcp-maintenance-admission"
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        gate = ToolAdmissionDrain()
        yield root, gate


def test_single_explicit_sidecar_binds_one_generation_and_joins(
    config: tuple[Path, ToolAdmissionDrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, gate = config
    seen: list[tuple] = []
    worker_ready = threading.Event()

    def fake_serve(path, *, lease, gate, stop):
        seen.append((path, lease.label, lease.generation, gate.generation))
        worker_ready.set()
        stop.wait(timeout=3)

    def fake_ping(path, *, lease, generation, timeout_s):
        assert worker_ready.wait(timeout=1)
        assert generation == lease.generation == gate.generation
        return gate.snapshot()

    monkeypatch.setattr(runtime, "serve_mcp_admission_a3", fake_serve)
    monkeypatch.setattr(runtime, "read_mcp_admission_a3", fake_ping)

    sidecar = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    assert sidecar.lease is None
    sidecar.start()
    assert sidecar.lease is not None
    assert seen == [
        (
            root / "mcp-admission.sock",
            "com.binnacle.mcp-maintenance-admission",
            gate.generation,
            gate.generation,
        )
    ]
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="already started"):
        sidecar.start()
    sidecar.stop()
    assert sidecar.lease is None
    assert sidecar._worker is None
    sidecar.stop()  # idempotent
    assert gate.snapshot().pause_nonce is None


def test_sidecar_does_not_start_with_held_gate(
    config: tuple[Path, ToolAdmissionDrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, gate = config
    gate.fence(nonce="a" * 32, generation=gate.generation)

    def fake_serve(path, *, lease, gate, stop):
        stop.wait(2)

    monkeypatch.setattr(runtime, "serve_mcp_admission_a3", fake_serve)
    monkeypatch.setattr(
        runtime, "read_mcp_admission_a3", lambda *a, **kw: gate.snapshot()
    )
    service = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="not authenticated"):
        service.start(timeout_s=0.11)
    assert service._worker is None


def test_server_thread_error_prevents_admission_ready(
    config: tuple[Path, ToolAdmissionDrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, gate = config

    def bad_serve(path, *, lease, gate, stop):
        raise OSError("synthetic socket bind unavailable")

    monkeypatch.setattr(runtime, "serve_mcp_admission_a3", bad_serve)
    monkeypatch.setattr(
        runtime,
        "read_mcp_admission_a3",
        lambda *a, **kw: pytest.fail("must not claim readiness after worker death"),
    )
    service = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused):
        service.start(timeout_s=0.25)
    assert service.lease is None and service._worker is None


def test_readiness_timeout_stops_worker_without_claiming_ready(
    config: tuple[Path, ToolAdmissionDrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, gate = config
    calls = [0]

    def fake_serve(path, *, lease, gate, stop):
        stop.wait(1.5)

    def failed_ping(*args, **kwargs):
        calls[0] += 1
        raise MCPAdmissionRPCRefused("socket not yet published")

    monkeypatch.setattr(runtime, "serve_mcp_admission_a3", fake_serve)
    monkeypatch.setattr(runtime, "read_mcp_admission_a3", failed_ping)
    service = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="not authenticated"):
        service.start(timeout_s=0.12)
    assert calls[0] >= 1
    assert service._worker is None


@pytest.mark.parametrize("bad", [0, -1, 11])
def test_invalid_start_budget_rejected_without_starting(
    config: tuple[Path, ToolAdmissionDrain],
    bad: float,
) -> None:
    root, gate = config
    sidecar = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="deadline"):
        sidecar.start(timeout_s=bad)
    assert sidecar.lease is None


@pytest.mark.parametrize("mode", ["missing", "public", "symlink", "foreign"])
def test_runtime_root_must_be_existing_private_and_correct_name(
    tmp_path: Path,
    mode: str,
) -> None:
    root = tmp_path / "mcp-maintenance-admission"
    if mode == "public":
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    elif mode == "symlink":
        other = tmp_path / "other"
        other.mkdir(mode=0o700)
        root.symlink_to(other, target_is_directory=True)
    elif mode == "foreign":
        root = tmp_path / "not-mcp"
        root.mkdir(mode=0o700)
    gate = ToolAdmissionDrain()
    service = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused):
        service.start(timeout_s=0.15)
    assert service._worker is None
    assert not (root / "mcp-admission.sock").exists()


@pytest.mark.parametrize("state", ["root", "mixed-uid"])
def test_privileged_or_mixed_uid_runtime_forbidden(
    config: tuple[Path, ToolAdmissionDrain],
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    root, gate = config
    service = runtime.MCPMaintenanceAdmissionRuntime(root, gate)
    current = os.getuid()
    with monkeypatch.context() as patch:
        if state == "root":
            patch.setattr(runtime.os, "getuid", lambda: 0)
        else:
            patch.setattr(runtime.os, "geteuid", lambda: current + 1)
        with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="not trusted"):
            service.start(timeout_s=0.1)
    assert service._worker is None


def test_real_open_service_lease_does_not_create_a_missing_root(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcp-maintenance-admission"
    assert not path.exists()
    gate = ToolAdmissionDrain()
    service = runtime.MCPMaintenanceAdmissionRuntime(path, gate)
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused):
        service.start(timeout_s=0.1)
    assert not path.exists()


def test_explicit_runtime_cannot_be_started_from_a_non_absolute_root() -> None:
    sidecar = runtime.MCPMaintenanceAdmissionRuntime(
        Path("mcp-maintenance-admission"),
        ToolAdmissionDrain(),
    )
    with pytest.raises(runtime.MCPMaintenanceRuntimeRefused, match="not trusted"):
        sidecar.start(timeout_s=0.1)


def test_native_lease_mints_same_incarnation_for_A3_generation(
    config: tuple[Path, ToolAdmissionDrain],
) -> None:
    root, gate = config
    lease = generation_runtime.open_service_lease(
        root=root,
        label="com.binnacle.mcp-maintenance-admission",
        generation=gate.generation,
    )
    assert lease.uid == os.getuid()
    assert lease.generation == gate.generation
    assert lease.label == "com.binnacle.mcp-maintenance-admission"
