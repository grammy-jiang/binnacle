"""P2.6 native resident Provider Manager -> pinned upstream PyrightServer.

Unmodified Binnacle production tools never mount or invoke this manager.
Requires explicit real-provider opt-in; missing required opt-in binary FAILS.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_provider_manager import (
    PrivateProviderManager,
    ProviderManagerError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    WorkspaceStaleError,
)


@pytest.fixture
def native(tmp_path):
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("private real Pyright tests require explicit opt-in")
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    allowed = (tmp_path / "operator-allowed").resolve()
    projects = []
    for number in range(3):
        root = allowed / f"project-{number}"
        root.mkdir(parents=True)
        (root / ".git").write_text("gitdir: /test/private-worktree\n")
        (root / "lib.py").write_text(
            "def greet(name: str) -> str:\n    return name.upper()\n"
        )
        main = root / "app.py"
        main.write_text("from lib import greet\nanswer = greet('Ada')\n")
        projects.append(main)
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        max_resident_servers=2,
        request_timeout_s=10,
        idle_timeout_s=120,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=binary,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )
    roots = RootsSettings(default_root=allowed, extra_roots=())
    return projects, settings, roots


async def request(manager, source):
    return await manager.definition(source, line=2, column=10, expected_symbol="greet")


async def wait_until(check, deadline=8.0):
    async def observe():
        while not check():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observe(), deadline)


@pytest.mark.asyncio
async def test_actual_single_flight_ten_concurrent_calls_and_resident_process(native):
    projects, settings, roots = native
    manager = PrivateProviderManager(settings, roots, max_pending_requests=12)
    async with manager:
        answers = await asyncio.wait_for(
            asyncio.gather(*(request(manager, projects[0]) for _ in range(10))), 25
        )
        assert all(answer[0]["relativePath"] == "lib.py" for answer in answers)
        assert manager.resident_count == 1
        assert manager.pending_count == 0
        (entry,) = manager._entries.values()
        assert entry.owner.active
        assert entry.documents is not None
        assert entry.owner._server.__class__.__name__ == "PyrightServer"
        real = entry.owner._server.server.process
        assert real is not None and real.returncode is None
        pid = real.pid
        await request(manager, projects[0])
        assert entry.owner._server.server.process.pid == pid
    assert manager.resident_count == 0
    assert real.returncode is not None
    receipt = await manager.aclose()
    assert receipt.instances_stopped == 1
    assert not receipt.cleanup_unverified


@pytest.mark.asyncio
async def test_real_two_workspaces_create_two_distinct_residents(native):
    projects, settings, roots = native
    async with PrivateProviderManager(settings, roots) as manager:
        await asyncio.gather(
            request(manager, projects[0]), request(manager, projects[1])
        )
        assert manager.resident_count == 2
        observed = list(manager._entries.values())
        assert len({entry.owner._server.server.process.pid for entry in observed}) == 2
        assert all(entry.owner.active for entry in observed)
    assert manager.resident_count == 0
    assert all(entry.owner.last_exit.parent_exited for entry in observed)
    assert all(not entry.owner.last_exit.cleanup_unverified for entry in observed)


@pytest.mark.asyncio
async def test_real_capacity_idle_lru_retires_previous_process(native):
    projects, settings, roots = native
    settings.max_resident_servers = 1
    async with PrivateProviderManager(settings, roots) as manager:
        await request(manager, projects[0])
        (first,) = manager._entries.values()
        process = first.owner._server.server.process
        await request(manager, projects[1])
        assert manager.resident_count == 1
        assert process.returncode is not None
        assert first.owner.last_exit and not first.owner.last_exit.cleanup_unverified
        (second,) = manager._entries.values()
        assert second.owner._server.server.process.pid != process.pid
    assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_real_idle_eviction_and_same_workspace_lazy_restart(native):
    projects, settings, roots = native
    settings.idle_timeout_s = 0.18
    async with PrivateProviderManager(settings, roots) as manager:
        await request(manager, projects[0])
        (original,) = manager._entries.values()
        first_process = original.owner._server.server.process
        await wait_until(lambda: manager.resident_count == 0)
        assert first_process.returncode is not None
        await request(manager, projects[0])
        assert manager.resident_count == 1
        (replacement,) = manager._entries.values()
        assert replacement is not original
    assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_real_disk_change_full_sync_inside_one_resident(native):
    projects, settings, roots = native
    async with PrivateProviderManager(settings, roots) as manager:
        first = await request(manager, projects[0])
        (entry,) = manager._entries.values()
        old_process = entry.owner._server.server.process
        assert entry.documents._documents["app.py"].version == 1
        projects[0].write_text("from lib import greet\nanswer = greet('Lin')\n")
        second = await request(manager, projects[0])
        assert first == second
        assert entry.documents._documents["app.py"].version == 2
        assert entry.owner._server.server.process is old_process
    assert old_process.returncode is not None


@pytest.mark.asyncio
async def test_real_stale_answer_rejected_without_restarting_provider(native):
    projects, settings, roots = native
    async with PrivateProviderManager(settings, roots) as manager:
        await request(manager, projects[0])
        (entry,) = manager._entries.values()
        process = entry.owner._server.server.process
        native_definition = entry.owner._server.server.send.definition

        async def mutate_after_request(payload):
            projects[0].write_text("from lib import greet\nanswer = greet('changed')\n")
            return await native_definition(payload)

        entry.owner._server.server.send.definition = mutate_after_request
        try:
            with pytest.raises(WorkspaceStaleError):
                await request(manager, projects[0])
        finally:
            entry.owner._server.server.send.definition = native_definition
        assert (await request(manager, projects[0]))[0]["relativePath"] == "lib.py"
        assert entry.owner._server.server.process is process
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_real_close_cancels_stalled_query_and_reaps_provider(native):
    projects, settings, roots = native
    manager = PrivateProviderManager(settings, roots, shutdown_timeout_s=0.5)
    await request(manager, projects[0])
    (entry,) = manager._entries.values()
    process = entry.owner._server.server.process
    begin = asyncio.Event()
    hold = asyncio.Event()
    upstream = entry.owner._server
    native_definition = upstream.server.send.definition

    async def simulated_unresponsive_peer(_payload):
        begin.set()
        await hold.wait()

    upstream.server.send.definition = simulated_unresponsive_peer
    query = asyncio.create_task(request(manager, projects[0]))
    await asyncio.wait_for(begin.wait(), 2)
    receipt = await asyncio.wait_for(manager.aclose(), 6)
    upstream.server.send.definition = native_definition
    assert receipt.requests_cancelled == 1
    assert receipt.instances_stopped == 1
    assert not receipt.cleanup_unverified
    with pytest.raises(asyncio.CancelledError):
        await query
    assert process.returncode is not None
    assert manager.resident_count == 0
    assert entry.owner.last_exit and not entry.owner.last_exit.cleanup_unverified


@pytest.mark.asyncio
async def test_no_start_for_invalid_source_cursor_or_disabled_profile(native):
    projects, settings, roots = native
    async with PrivateProviderManager(settings, roots) as manager:
        with pytest.raises(ValueError, match="anchor_mismatch"):
            await manager.definition(
                projects[0], line=2, column=10, expected_symbol="nonexistent"
            )
        assert manager.resident_count == 0
    settings.enabled = False
    manager = PrivateProviderManager(settings, roots)
    with pytest.raises(RuntimeError, match="disabled"):
        await request(manager, projects[0])
    assert manager.resident_count == 0
    await manager.aclose()


@pytest.mark.asyncio
async def test_actual_idle_provider_exit_recycles_after_cooldown(native):
    projects, settings, roots = native
    settings.idle_timeout_s = 0.35
    async with PrivateProviderManager(
        settings, roots, cooldown_base_s=0.4, cooldown_max_s=0.4
    ) as manager:
        await request(manager, projects[0])
        (entry,) = manager._entries.values()
        real = entry.owner._server.server.process
        assert real.returncode is None
        # Only the exact subprocess freshly spawned by this private fixture.
        real.terminate()
        await asyncio.wait_for(real.wait(), 3)
        await wait_until(lambda: manager.resident_count == 0)
        with pytest.raises(ProviderManagerError, match="cooldown"):
            await request(manager, projects[0])
        await asyncio.sleep(0.45)
        refreshed = await request(manager, projects[0])
        assert refreshed[0]["relativePath"] == "lib.py"
        assert manager.resident_count == 1
    assert manager.resident_count == 0
    assert not (await manager.aclose()).cleanup_unverified
