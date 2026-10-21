"""P2.4 startup/close race checks with upstream multilspy's real process owner.

No MCP tools or production sessions are used by these disposable tests.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)


@pytest.mark.asyncio
async def test_aclose_during_pre_spawn_initialize_cancels_inflight_start(tmp_path):
    """No provider may spawn after its Binnacle owner has finished closing."""
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    root = tmp_path / "private-workspace"
    root.mkdir()
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
            )
        },
    )
    owner = PrivatePyrightProcessOwner(settings, root, cleanup_timeout_s=4)
    server = LanguageServer.create(
        MultilspyConfig(
            code_language=Language.PYTHON,
            python_server="pyright",
            server_binary=sys.executable,
        ),
        MultilspyLogger(),
        str(root),
    )
    attempted = asyncio.Event()
    allow_spawn = asyncio.Event()
    native_start = server.server.start
    spawned = []

    async def delayed_start():
        attempted.set()
        await allow_spawn.wait()
        await native_start()
        spawned.append(server.server.process)

    server.server.start = delayed_start
    owner._make_upstream_server = lambda: server
    entered = []

    async def session_runner():
        async with owner.session():
            entered.append(True)

    task = asyncio.create_task(session_runner())
    await asyncio.wait_for(attempted.wait(), 3)
    assert owner.active and server.server.process is None
    await asyncio.wait_for(owner.aclose(), 4)
    allow_spawn.set()
    assert task.done()
    assert not entered and not spawned
    assert owner.closed and not owner.active
    assert owner.last_exit is not None and owner.last_exit.cleanup_unverified
    assert server.server.process is None
    with pytest.raises(ProviderLifecycleError, match="closed"):
        async with owner.session():
            pytest.fail("closed owner started provider after shutdown")


@pytest.mark.asyncio
async def test_aclose_during_blocked_initialize_after_spawn_reaps_process(tmp_path):
    """Closing owner while real stdio peer hangs after spawn cannot leak it."""
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    root = tmp_path / "private-project"
    root.mkdir()
    script = tmp_path / "blocked_stdio.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    profile = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
            )
        },
    )
    owner = PrivatePyrightProcessOwner(profile, root, cleanup_timeout_s=10)
    server = LanguageServer.create(
        MultilspyConfig(
            code_language=Language.PYTHON,
            python_server="pyright",
            server_binary=sys.executable,
        ),
        MultilspyLogger(),
        str(root),
    )
    server.server.process_launch_info.cmd = [sys.executable, "-u", str(script)]
    spawned = asyncio.Event()
    children = []
    native_start = server.server.start

    async def tracked_start():
        await native_start()
        children.append(server.server.process)
        spawned.set()

    server.server.start = tracked_start
    server._initialize_timeout_seconds = 15
    owner._make_upstream_server = lambda: server
    entered = []

    async def run_session():
        async with owner.session():
            entered.append(True)

    worker = asyncio.create_task(run_session())
    await asyncio.wait_for(spawned.wait(), 5)
    assert children[0] is not None and children[0].returncode is None
    await asyncio.wait_for(owner.aclose(), 10)
    assert worker.done()
    assert not entered
    assert len(children) == 1 and children[0].returncode is not None
    assert server.server.process is None
    assert not server.server.tasks
    assert not server.server._response_handlers
    assert owner.closed and not owner.active
    assert owner.last_exit is not None and owner.last_exit.cleanup_unverified
    with pytest.raises(ProviderLifecycleError, match="closed_or_unverified"):
        async with owner.session():
            pytest.fail("closed or uncertain owner must not start another provider")
