"""P2.8 additional P2.6 manager queue/profile authorization branches."""

from __future__ import annotations

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_provider_manager import (
    ProviderManagerError,
)
from tests.unit.core.test_lsp_provider_manager_p26 import query

pytest_plugins = ("tests.unit.core.test_lsp_provider_manager_p26",)


@pytest.mark.asyncio
async def test_absent_pyright_profile_is_never_a_provider_launch(fx):
    files, factory, witness, settings = fx
    settings.profiles.clear()
    async with factory() as manager:
        assert manager._profile_hash == "disabled"
        with pytest.raises(ProviderManagerError, match="pyright_provider_disabled"):
            await query(manager, files[0])
        assert witness.launches == 0
        assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_closed_manager_never_accepts_new_lifespan(fx):
    _files, factory, _witness, _settings = fx
    manager = factory()
    await manager.aclose()
    with pytest.raises(ProviderManagerError, match="provider_manager_already_closed"):
        async with manager:
            pytest.fail("closed resident provider reentered")


@pytest.mark.asyncio
async def test_provider_queue_timeout_does_not_count_as_remote_error(fx):
    files, factory, witness, _settings = fx
    witness.query_blocked = True
    async with factory(
        max_per_provider_requests=1,
        max_parallel_requests=2,
        queue_timeout_s=0.035,
        request_timeout_s=1,
    ) as manager:
        first = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.query_started.wait(), 1)
        with pytest.raises(
            ProviderManagerError, match="provider_provider_queue_timeout"
        ):
            await query(manager, files[0])
        assert manager.resident_count == 1
        assert manager._cooldowns == {}
        witness.query_gate.set()
        assert (await asyncio.wait_for(first, 1))[0]["relativePath"] == "main.py"
    assert witness.live == 0
