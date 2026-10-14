"""Explicit macOS profile for request admission A3, default disabled."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from binnacle import application, server
from binnacle.config import MCPMaintenanceSettings, Settings
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform import composition
from binnacle.platform.darwin.mcp_maintenance_admission_runtime import (
    MCPMaintenanceAdmissionRuntime,
)


def test_mcp_maintenance_profile_disabled_by_default() -> None:
    settings = Settings()
    assert settings.mcp_maintenance.enabled is False
    assert settings.mcp_maintenance.control_root is None


@pytest.mark.parametrize(
    "profile",
    [
        {"enabled": True},
        {"enabled": False, "control_root": "/tmp/private"},
        {"enabled": True, "control_root": None},
    ],
)
def test_partial_or_inconsistent_maintenance_profile_refused(
    profile: dict,
) -> None:
    with pytest.raises(ValueError, match="enabled and control_root together"):
        MCPMaintenanceSettings(**profile)


def test_explicit_disabled_profile_does_not_start_control_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("default-off request admission must not start sidecar")

    monkeypatch.setattr(MCPMaintenanceAdmissionRuntime, "__init__", unexpected)
    monkeypatch.setattr(server, "get_settings", lambda: Settings())
    monkeypatch.setattr(server, "_load_token", lambda: "test-only")
    server.create_server()
    # No sidecar can have been created, regardless of local platform.


def test_explicit_profile_refused_on_linux_before_any_service_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = Settings(
        mcp_maintenance={
            "enabled": True,
            "control_root": tmp_path / "mcp-maintenance-admission",
        }
    )
    monkeypatch.setattr(server, "get_settings", lambda: options)
    monkeypatch.setattr(composition, "host_os_family", lambda: "linux")
    monkeypatch.setattr(server, "_load_token", lambda: "test-only")
    with pytest.raises(RuntimeError, match="native Darwin"):
        server.create_server()
    assert not (tmp_path / "mcp-maintenance-admission").exists()


def test_opt_in_profile_passes_same_gate_to_native_app_and_a3_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "mcp-maintenance-admission"
    options = Settings(
        mcp_maintenance={
            "enabled": True,
            "control_root": private,
        }
    )
    calls: list[dict] = []

    def fake_native(*, settings):
        assert settings is options
        return None, object()

    def fake_create_application(**kw):
        calls.append(kw)
        return object()

    monkeypatch.setattr(server, "get_settings", lambda: options)
    monkeypatch.setattr(server, "_load_token", lambda: "test-only")
    monkeypatch.setattr(composition, "host_os_family", lambda: "darwin")
    monkeypatch.setattr(application, "compose_native_tools", fake_native)
    monkeypatch.setattr(application, "create_application", fake_create_application)
    result = server.create_server()
    assert result is not None
    assert len(calls) == 1
    supplied = calls[0]
    assert isinstance(supplied["admission_gate"], ToolAdmissionDrain)
    assert isinstance(supplied["maintenance_runtime"], MCPMaintenanceAdmissionRuntime)
    assert supplied["admission_gate"] is supplied["maintenance_runtime"].gate
    assert supplied["maintenance_runtime"].root == private
    assert supplied["settings"] is options
    # No directory or socket is created by composition.
    assert not private.exists()


def test_app_lifespan_starts_sidecar_before_enter_and_stops_after_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Use exactly the same FastMCP lifespan composition as installed app,
    # with an isolated fake implementation. No A3 socket or privileged work.
    events: list[str] = []

    class FakeSidecar:
        def start(self):
            events.append("ready")

        def stop(self):
            events.append("stopped")

    from binnacle.features.commands.command_backend import RestrictedCommandBackend
    from tests.unit.core.test_r4_cov_application import settings_with

    settings = settings_with(tmp_path)
    gate = ToolAdmissionDrain()
    fake_backend = RestrictedCommandBackend()
    root = application.create_application(
        settings=settings,
        token="synthetic-token",
        backend=fake_backend,
        admission_gate=gate,
        maintenance_runtime=FakeSidecar(),
    )
    app = root.http_app()

    async def lifecycle() -> None:
        async with app.router.lifespan_context(app):
            assert events == ["ready"]
            assert gate.snapshot().pause_nonce is None

    asyncio.run(lifecycle())
    assert events == ["ready", "stopped"]


def test_failure_to_start_sidecar_prevents_lifespan_and_file_grant_leak(
    tmp_path: Path,
) -> None:
    from binnacle.features.commands.command_backend import RestrictedCommandBackend
    from tests.unit.core.test_r4_cov_application import settings_with

    class BrokenSidecar:
        def start(self):
            raise RuntimeError("separate control socket not authenticated")

        def stop(self):
            pytest.fail("no started service to stop")

    gate = ToolAdmissionDrain()
    root = application.create_application(
        settings=settings_with(tmp_path),
        token="synthetic-token",
        backend=RestrictedCommandBackend(),
        admission_gate=gate,
        maintenance_runtime=BrokenSidecar(),
    )
    app = root.http_app()

    async def lifecycle() -> None:
        with pytest.raises(RuntimeError, match="not authenticated"):
            async with app.router.lifespan_context(app):
                pytest.fail("MCP may not serve before authenticated readiness")

    asyncio.run(lifecycle())
