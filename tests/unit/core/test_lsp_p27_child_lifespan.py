"""P2.7 native FastMCP child lifespan injection and rollback (no Pyright)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_manager_types import (
    ShutdownObservation,
)
from binnacle.features.development_intelligence.lsp_preview_server import (
    PREVIEW_NAME,
    create_private_lsp_preview_server,
)


class FakeResidentManager:
    def __init__(self, ledger, _settings, _roots):
        self.ledger = ledger
        self.closed = False
        self.calls = 0
        self.close_calls = 0
        self.ledger.append(self)
        self.fail_shutdown = False
        self.delay_shutdown = False
        self.shutdown_started = asyncio.Event()
        self.shutdown_gate = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, _kind, _value, _traceback):
        await self.aclose()

    async def definition(self, _source, *, line, column, expected_symbol):
        self.calls += 1
        if expected_symbol == "reject":
            raise ValueError("/PRIVATE/root/secret.py contains private data")
        if expected_symbol == "timeout":
            raise TimeoutError("/PRIVATE/root/secret.py timeout")
        if expected_symbol == "permission":
            raise PermissionError("/PRIVATE/root/secret.py forbidden")
        if expected_symbol == "malformed":
            return [{"uri": "file:///PRIVATE/root/secret.py"}]
        return [
            {
                "relativePath": "lib.py",
                "uri": "file:///PRIVATE/never-return-this",
                "range": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 8},
                },
            }
        ]

    async def aclose(self):
        self.close_calls += 1
        self.shutdown_started.set()
        if self.delay_shutdown:
            await self.shutdown_gate.wait()
        self.closed = True
        return ShutdownObservation(
            instances_requested=1,
            instances_stopped=1,
            requests_cancelled=0,
            cleanup_unverified=self.fail_shutdown,
        )


@pytest.fixture
def enabled_child(tmp_path):
    allowed = (tmp_path / "approved").resolve()
    allowed.mkdir()
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable="/usr/bin/false",
                mode="explicit_trust_only",
            )
        },
    )
    roots = RootsSettings(default_root=allowed, extra_roots=())
    created = []

    def factory(s, r):
        return FakeResidentManager(created, s, r)

    child = create_private_lsp_preview_server(
        feature_settings=settings,
        roots=roots,
        manager_factory=factory,
    )
    return child, created


@pytest.mark.asyncio
async def test_construct_and_list_tools_without_manager_or_pyright_start(enabled_child):
    child, created = enabled_child
    assert created == []
    metadata = child._private_preview_lifespan
    assert metadata.active is None
    async with Client(child) as client:
        assert len(created) == 1
        assert created[0].calls == 0
        assert [tool.name for tool in await client.list_tools()] == [PREVIEW_NAME]
        assert metadata.active is created[0]
    assert created[0].closed
    assert metadata.active is None
    assert metadata.starts == metadata.closed == 1
    assert metadata.last_close.cleanup_unverified is False


@pytest.mark.asyncio
async def test_two_sessions_create_distinct_manager_generations(enabled_child):
    child, created = enabled_child
    metadata = child._private_preview_lifespan
    for _ in range(2):
        async with Client(child) as client:
            response = await client.call_tool(
                PREVIEW_NAME,
                {
                    "source_file": "/no/file-reading-in-fake-manager.py",
                    "line": 1,
                    "column": 2,
                    "expected_symbol": "hello",
                },
            )
            assert not response.is_error
            assert response.structured_content == {
                "status": "ok",
                "locations": [
                    {
                        "relative_path": "lib.py",
                        "range": {
                            "start": {"line": 0, "character": 4},
                            "end": {"line": 0, "character": 8},
                        },
                    }
                ],
            }
    assert len(created) == 2
    assert created[0] is not created[1]
    assert all(entry.calls == 1 and entry.closed for entry in created)
    assert metadata.starts == metadata.closed == 2
    assert metadata.active is None


@pytest.mark.asyncio
async def test_fake_transport_exception_never_leaks_host_source_paths(enabled_child):
    child, created = enabled_child
    async with Client(child) as client:
        error = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": "/some/path.py",
                "line": 1,
                "column": 1,
                "expected_symbol": "reject",
            },
            raise_on_error=False,
        )
        assert error.is_error
        assert "/PRIVATE/" not in str(error)
        assert "private data" not in str(error)
    assert created[0].calls == 1


@pytest.mark.asyncio
async def test_unverified_cleanup_poison_entire_child_generation(enabled_child):
    child, created = enabled_child
    metadata = child._private_preview_lifespan
    with pytest.raises(RuntimeError, match="cleanup_unverified"):
        async with Client(child):
            created[0].fail_shutdown = True
    assert created[0].closed
    assert metadata.active is created[0]  # retain poison, never accept reuse
    assert metadata.last_close.cleanup_unverified is True
    with pytest.raises(RuntimeError, match="lifespan_overlap"):
        async with Client(child):
            pytest.fail("poisoned root reopened")
    assert len(created) == 1


@pytest.mark.asyncio
async def test_child_manager_factory_failure_has_no_resident_state(tmp_path):
    allowed = tmp_path / "approved"
    allowed.mkdir()
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable="/bin/false",
                mode="explicit_trust_only",
            )
        },
    )

    def broken_manager(_settings, _roots):
        raise RuntimeError("fixture constructor failed")

    child = create_private_lsp_preview_server(
        feature_settings=settings,
        roots=RootsSettings(default_root=allowed, extra_roots=()),
        manager_factory=broken_manager,
    )
    with pytest.raises(RuntimeError, match="fixture constructor failed"):
        async with Client(child):
            pytest.fail("failed to create manager")
    assert child._private_preview_lifespan.active is None
    assert child._private_preview_lifespan.starts == 0


@pytest.mark.asyncio
async def test_partial_start_manager_enter_failure_is_closed(enabled_child):
    child, _created = enabled_child

    class BadManager(FakeResidentManager):
        async def __aenter__(self):
            raise RuntimeError("fixture start failed")

    from binnacle.features.development_intelligence import lsp_preview_server

    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable="/bin/false",
                mode="explicit_trust_only",
            )
        },
    )
    tmp = Path("/tmp")
    children = []
    child = lsp_preview_server.create_private_lsp_preview_server(
        feature_settings=settings,
        roots=RootsSettings(default_root=tmp, extra_roots=()),
        manager_factory=lambda s, r: BadManager(children, s, r),
    )
    with pytest.raises(RuntimeError, match="fixture start failed"):
        async with Client(child):
            pytest.fail("partial init accepted")
    assert len(children) == 1
    assert children[0].closed
    assert child._private_preview_lifespan.active is None
    assert child._private_preview_lifespan.closed == 1


@pytest.mark.asyncio
async def test_cancel_waiter_does_not_cancel_manager_cleanup(enabled_child):
    child, created = enabled_child
    metadata = child._private_preview_lifespan
    inside = asyncio.Event()
    release_client = asyncio.Event()

    async def use_client():
        async with Client(child):
            created[0].delay_shutdown = True
            inside.set()
            await release_client.wait()

    task = asyncio.create_task(use_client())
    await asyncio.wait_for(inside.wait(), 1)
    release_client.set()
    await asyncio.wait_for(created[0].shutdown_started.wait(), 1)
    task.cancel()
    # Once cancelled, our child lifespan keeps cleanup alive until it ends.
    created[0].shutdown_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    # FastMCP transports may finish propagating cancellation before the
    # shielded child lifespan has finished its cleanup. Wait for evidence.
    async def verified_exit():
        while metadata.active is not None:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(verified_exit(), 1)
    assert created[0].closed
    assert metadata.active is None
    assert metadata.closed == 1


@pytest.mark.asyncio
async def test_parent_fastmcp_sidecar_rolls_back_on_partial_child_start(tmp_path):
    from binnacle.application import create_application
    from binnacle.config import Settings
    from binnacle.features.development_intelligence.lsp_preview_server import (
        create_private_lsp_preview_server,
    )
    from tests.command_support import MemoryCommands

    allowed = tmp_path / "operator-root"
    allowed.mkdir()
    settings = Settings(roots=RootsSettings(default_root=allowed, extra_roots=()))
    settings.jobs.owner = "embedded"
    settings.jobs.socket_path = tmp_path / "unused-manager.sock"
    settings.development_intelligence = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable="/usr/bin/false",
                mode="explicit_trust_only",
            )
        },
    )
    events = []

    class Sidecar:
        def start(self):
            events.append("sidecar-start")

        def stop(self):
            events.append("sidecar-stop")

    def child_factory(**kwargs):
        def manager_factory(_settings, _roots):
            events.append("child-manager-fail")
            raise RuntimeError("private P2.7 partial child startup failed")

        return create_private_lsp_preview_server(
            **kwargs,
            manager_factory=manager_factory,
        )

    app = create_application(
        settings=settings,
        token="qa-internal",
        backend=MemoryCommands("qa"),
        maintenance_runtime=Sidecar(),
        _private_lsp_preview_gate=True,
        _private_lsp_preview_factory=child_factory,
    )
    with pytest.raises(Exception, match="partial child startup failed"):
        async with Client(app):
            pytest.fail("FastMCP child started despite failed Manager")
    assert events == ["sidecar-start", "child-manager-fail", "sidecar-stop"]


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["timeout", "permission", "malformed"])
async def test_all_backend_exceptions_are_redacted_even_when_root_masks_only_partially(
    enabled_child, symbol
):
    child, created = enabled_child
    async with Client(child) as client:
        response = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": "/caller/private/path.py",
                "line": 1,
                "column": 2,
                "expected_symbol": symbol,
            },
            raise_on_error=False,
        )
        assert response.is_error
        assert "/PRIVATE" not in str(response)
        assert "secret.py" not in str(response)
    assert created[0].closed


@pytest.mark.asyncio
async def test_cleanup_timeout_fails_closed_and_consumes_late_task_result(
    monkeypatch,
):
    from binnacle.features.development_intelligence import lsp_preview_server

    monkeypatch.setattr(lsp_preview_server, "_CLEANUP_CEILING_SECONDS", 0.05)
    config = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable="/bin/false",
                mode="explicit_trust_only",
            )
        },
    )
    created = []

    class SlowClose(FakeResidentManager):
        async def __aexit__(self, _kind, _value, _traceback):
            # Force the child, not the fake manager, to own the closing budget.
            return None

    child = create_private_lsp_preview_server(
        feature_settings=config,
        roots=RootsSettings(default_root=Path("/tmp"), extra_roots=()),
        manager_factory=lambda s, r: SlowClose(created, s, r),
    )
    life = child._private_preview_lifespan
    with pytest.raises(RuntimeError, match="cleanup_unverified"):
        async with Client(child):
            created[0].delay_shutdown = True
    assert life.poisoned
    assert life.active is created[0]
    assert created[0].shutdown_started.is_set()
    created[0].shutdown_gate.set()
    await asyncio.sleep(0.04)
    assert created[0].closed
    assert life.poisoned and life.active is created[0]
    with pytest.raises(RuntimeError, match="lifespan_overlap"):
        async with Client(child):
            pytest.fail("timed-out lifespan unexpectedly reused")
