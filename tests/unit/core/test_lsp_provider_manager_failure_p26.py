"""P2.6 failure, cooldown, cancellation and long-lived registry bounds."""

from __future__ import annotations

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_provider_manager import (
    ProviderManagerError,
)
from tests.unit.core.test_lsp_provider_manager_p26 import query, until

pytest_plugins = ("tests.unit.core.test_lsp_provider_manager_p26",)


@pytest.mark.asyncio
async def test_cancelled_aclose_waiter_does_not_cancel_owned_cleanup(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    manager = factory(shutdown_timeout_s=0.24)
    query_task = asyncio.create_task(query(manager, files[0]))
    await asyncio.wait_for(witness.query_started.wait(), 1)
    close_waiter = asyncio.create_task(manager.aclose())
    await asyncio.sleep(0)
    close_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_waiter
    result = await asyncio.wait_for(manager.aclose(), 2)
    assert result.instances_requested == result.instances_stopped == 1
    assert result.requests_cancelled == 1
    assert not result.cleanup_unverified
    with pytest.raises(asyncio.CancelledError):
        await query_task
    assert manager.resident_count == 0
    assert witness.live == 0


@pytest.mark.asyncio
async def test_many_concurrent_close_callers_share_single_cleanup(fx):
    files, factory, witness, _ = fx
    manager = factory()
    await query(manager, files[0])
    outcomes = await asyncio.gather(*(manager.aclose() for _ in range(12)))
    assert len(outcomes) == 12
    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert outcomes[0].instances_requested == 1
    assert outcomes[0].instances_stopped == 1
    assert witness.document_exits == 1
    assert witness.live == 0
    with pytest.raises(ProviderManagerError, match="closing"):
        await query(manager, files[0])


@pytest.mark.asyncio
async def test_client_cancelled_during_provider_query_forces_recycle(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    async with factory(cooldown_base_s=0.2, cooldown_max_s=0.2) as manager:
        task = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.query_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await until(lambda: manager.resident_count == 0)
        witness.query_blocked = False
        # A client-initiated cancel still reaps this instance, but must not
        # impose exponential failure cooldown on a healthy provider.
        assert manager._cooldowns == {}
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
        assert witness.launches == 2
    assert witness.live == 0


@pytest.mark.asyncio
async def test_bounded_queue_wait_does_not_poison_busy_provider(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    manager = factory(
        queue_timeout_s=0.04,
        max_parallel_requests=1,
        request_timeout_s=1,
    )
    async with manager:
        first = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.query_started.wait(), 1)
        with pytest.raises(ProviderManagerError, match="queued_timeout"):
            await query(manager, files[0])
        assert witness.launches == 1
        assert manager.resident_count == 1
        witness.query_gate.set()
        assert (await first)[0]["relativePath"] == "main.py"
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
    assert witness.live == 0


@pytest.mark.asyncio
async def test_startup_timeout_aborts_and_refuses_immediate_reuse(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    async with factory(
        startup_timeout_s=0.05, cooldown_base_s=0.2, cooldown_max_s=0.2
    ) as manager:
        with pytest.raises(ProviderManagerError, match="start_timeout"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        assert witness.live == 0
        with pytest.raises(ProviderManagerError, match="cooldown"):
            await query(manager, files[0])
        assert witness.launches == 1


def test_event_loop_affinity_rejects_reuse_after_previous_loop(fx):
    files, factory, witness, _ = fx
    manager = factory()

    async def first_generation():
        await query(manager, files[0])
        await manager.aclose()

    asyncio.run(first_generation())
    assert witness.live == 0
    with pytest.raises(ProviderManagerError, match="event_loop_mismatch"):
        asyncio.run(manager.aclose())


@pytest.mark.asyncio
async def test_unverified_cleanup_blocks_every_workspace_in_same_generation(fx):
    files, factory, witness, _ = fx
    witness.unclean = True
    async with factory(idle_timeout_s=0) as manager:
        await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        with pytest.raises(ProviderManagerError, match="cleanup_unverified"):
            await query(manager, files[1])
        assert witness.launches == 1
        assert manager.pending_count == 0
    assert (await manager.aclose()).cleanup_unverified


@pytest.mark.asyncio
async def test_idle_process_exit_is_detected_and_requires_cooldown(fx):
    files, factory, witness, _ = fx
    async with factory(
        idle_timeout_s=0.15,
        cooldown_base_s=0.18,
        cooldown_max_s=0.18,
    ) as manager:
        await query(manager, files[0])
        assert manager.resident_count == 1
        witness.process_crashed = True
        await until(lambda: manager.resident_count == 0)
        assert witness.live == 0
        witness.process_crashed = False
        with pytest.raises(ProviderManagerError, match="cooldown"):
            await query(manager, files[0])
        await asyncio.sleep(0.21)
        await query(manager, files[0])
        assert witness.launches == 2


@pytest.mark.asyncio
async def test_prolonged_many_complete_requests_leave_no_unbounded_task_history(fx):
    files, factory, witness, _ = fx
    async with factory(idle_timeout_s=0) as manager:
        for _ in range(90):
            await query(manager, files[0])
            await until(lambda: manager.resident_count == 0)
        assert witness.launches == 90
        assert manager.pending_count == 0
        assert manager._callers == set()
        assert len(manager.observations()) <= 64
        assert len(manager._cooldowns) == 0
    assert witness.live == 0


def test_configured_limits_reject_invalid_values(fx):
    _files, factory, _witness, _settings = fx
    cases = (
        {"max_pending_requests": 0},
        {"max_pending_requests": True},
        {"max_pending_requests": 257},
        {"max_parallel_requests": 0},
        {"max_per_provider_requests": -1},
        {"cooldown_base_s": 0},
        {"cooldown_max_s": 0.5, "cooldown_base_s": 1.0},
        {"shutdown_timeout_s": True},
    )
    for options in cases:
        with pytest.raises(ValueError):
            factory(**options)


@pytest.mark.asyncio
async def test_solo_cold_start_cancellation_prevents_orphaned_provider(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    async with factory(startup_timeout_s=1.0) as manager:
        task = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.started.wait(), 1)
        assert manager.resident_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await until(lambda: manager.resident_count == 0)
        assert witness.live == 0
        assert witness.document_starts == 0
        assert manager.pending_count == 0


@pytest.mark.asyncio
async def test_disabled_manager_refuses_before_any_workspace_disk_access(fx):
    _files, factory, witness, _settings = fx
    async with factory() as manager:
        manager._settings.enabled = False  # simulate a disabled host generation
        # The requested path is intentionally invalid. A disabled profile must
        # return disabled without touching/resolving an untrusted path.
        with pytest.raises(
            ProviderManagerError, match="development_intelligence_disabled"
        ):
            await manager.definition(
                "not-an-absolute-path", line=1, column=1, expected_symbol="target"
            )
        assert witness.launches == 0
        assert manager.pending_count == 0
        assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_consecutive_failures_increase_cooldown_then_success_resets(fx):
    files, factory, witness, _settings = fx
    witness.fail_starts = 2
    async with factory(cooldown_base_s=0.045, cooldown_max_s=0.3) as manager:
        with pytest.raises(ProviderManagerError, match="not_ready"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        assert next(iter(manager._cooldowns.values())).failures == 1
        await asyncio.sleep(0.06)
        with pytest.raises(ProviderManagerError, match="not_ready"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        cooldown = next(iter(manager._cooldowns.values()))
        assert cooldown.failures == 2
        assert cooldown.until - asyncio.get_running_loop().time() >= 0.055
        await asyncio.sleep(0.11)
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
        assert manager._cooldowns == {}
        assert witness.launches == 3


@pytest.mark.asyncio
async def test_cleanup_failure_cannot_leak_pending_request_accounting(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    witness.fail_close = True
    manager = factory(startup_timeout_s=1)
    task = asyncio.create_task(query(manager, files[0]))
    await asyncio.wait_for(witness.started.wait(), 1)
    task.cancel()
    with pytest.raises(ProviderManagerError, match="cleanup_unverified"):
        await task
    await until(lambda: manager.resident_count == 0)
    assert manager.pending_count == 0
    assert manager._callers == set()
    assert (await manager.aclose()).cleanup_unverified


@pytest.mark.asyncio
async def test_exponential_backoff_across_two_failed_generations_then_reset(fx):
    files, factory, witness, _ = fx
    witness.fail_starts = 2
    async with factory(cooldown_base_s=0.06, cooldown_max_s=0.18) as manager:
        with pytest.raises(ProviderManagerError, match="not_ready"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        (key,) = manager._cooldowns
        first = manager._cooldowns[key]
        assert first.failures == 1
        await asyncio.sleep(0.08)
        with pytest.raises(ProviderManagerError, match="not_ready"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        next_failure = manager._cooldowns[key]
        assert next_failure.failures == 2
        assert next_failure.until > first.until
        await asyncio.sleep(0.14)
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
        assert key not in manager._cooldowns
        assert witness.launches == 3


@pytest.mark.asyncio
async def test_failed_liveness_monitor_refuses_new_provider_without_silent_loss(fx):
    files, factory, witness, _ = fx
    async with factory(idle_timeout_s=0.09) as manager:
        await query(manager, files[0])
        witness.liveness_fault = True
        await until(lambda: manager.resident_count == 0)
        assert manager._unsafe_cleanup
        with pytest.raises(ProviderManagerError, match="cleanup_unverified"):
            await query(manager, files[1])
    assert witness.live == 0
    assert (await manager.aclose()).cleanup_unverified


@pytest.mark.asyncio
async def test_startup_cleanup_exception_is_sanitized_and_generation_poisoned(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    witness.aclose_fault = True
    manager = factory(startup_timeout_s=0.05, shutdown_timeout_s=0.2)
    with pytest.raises(ProviderManagerError, match="cleanup_unverified"):
        await query(manager, files[0])
    await until(lambda: manager.resident_count == 0)
    assert manager._unsafe_cleanup
    assert manager.pending_count == 0
    assert witness.live == 0
    assert (await manager.aclose()).cleanup_unverified
