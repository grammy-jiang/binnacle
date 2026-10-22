"""Deterministic P2.6 private registry contract using P1-style fake workers."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

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


class SimulatedProvider:
    def __init__(self, witness, root):
        self.witness = witness
        self.root = root
        self.closed = False
        self.last_exit = None

    @asynccontextmanager
    async def session(self):
        self.witness.launches += 1
        self.witness.started.set()
        if self.witness.start_blocked:
            await self.witness.start_gate.wait()
        if self.closed:
            raise RuntimeError("owner was closed before process launch")
        if self.witness.fail_starts:
            self.witness.fail_starts -= 1
            raise RuntimeError("simulated startup error")
        self.witness.live += 1
        self.witness.peak_live = max(self.witness.live, self.witness.peak_live)
        try:
            yield SimpleNamespace(
                repository_root_path=str(self.root), server_started=True
            )
        finally:
            self.witness.live -= 1
            self.last_exit = SimpleNamespace(cleanup_unverified=self.witness.unclean)

    @property
    def process_running(self):
        if self.witness.liveness_fault:
            raise RuntimeError("simulated liveness observation failure")
        return self.witness.live > 0 and not self.witness.process_crashed

    def observe_owned_processes(self):
        self.witness.observations += 1
        if self.witness.process_crashed:
            raise RuntimeError("simulated crashed child")

    async def aclose(self):
        self.closed = True
        self.witness.start_gate.set()
        if self.witness.aclose_fault:
            raise RuntimeError("simulated unsafe cleanup")
        if self.witness.fail_close:
            raise RuntimeError("simulated owner cleanup failure")


class SimulatedDocuments:
    def __init__(self, server, workspace, *, request_timeout_s):
        self.witness = WITNESS
        self.poisoned = False
        self.request_timeout_s = request_timeout_s

    async def __aenter__(self):
        self.witness.document_starts += 1
        return self

    async def __aexit__(self, _kind, _value, _traceback):
        self.witness.document_exits += 1

    async def definition(self, relative_file, *, line, column, expected_symbol):
        self.witness.request_count += 1
        self.witness.parallel += 1
        self.witness.peak_parallel = max(
            self.witness.parallel, self.witness.peak_parallel
        )
        self.witness.query_started.set()
        try:
            if self.witness.query_blocked:
                await asyncio.wait_for(
                    self.witness.query_gate.wait(), self.request_timeout_s
                )
            if self.witness.fail_request:
                raise RuntimeError("simulated wire failure")
            await asyncio.sleep(0)
            return [{"relativePath": relative_file, "line": line, "column": column}]
        finally:
            self.witness.parallel -= 1


class Witness:
    def __init__(self):
        self.launches = 0
        self.live = 0
        self.peak_live = 0
        self.observations = 0
        self.document_starts = 0
        self.document_exits = 0
        self.request_count = 0
        self.parallel = 0
        self.peak_parallel = 0
        self.start_blocked = False
        self.start_gate = asyncio.Event()
        self.started = asyncio.Event()
        self.query_blocked = False
        self.query_gate = asyncio.Event()
        self.query_started = asyncio.Event()
        self.fail_starts = 0
        self.fail_close = False
        self.fail_request = False
        self.process_crashed = False
        self.unclean = False
        self.liveness_fault = False
        self.aclose_fault = False


WITNESS = None


@pytest.fixture
def fx(tmp_path):
    global WITNESS
    WITNESS = Witness()
    allowed = (tmp_path / "allowed").resolve()
    roots = RootsSettings(default_root=allowed, extra_roots=())
    files = []
    for index in range(3):
        root = allowed / f"project-{index}"
        root.mkdir(parents=True)
        (root / ".git").write_text("gitdir: /managed\n")
        file = root / "main.py"
        file.write_text("target = 1\n", encoding="utf-8")
        files.append(file)
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        max_resident_servers=2,
        request_timeout_s=0.15,
        idle_timeout_s=120,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )

    def factory(**overrides):
        configured = settings.model_copy(
            update={
                k: overrides.pop(k)
                for k in tuple(overrides)
                if k in {"max_resident_servers", "idle_timeout_s", "request_timeout_s"}
            }
        )
        return PrivateProviderManager(
            configured,
            roots,
            _owner_factory=lambda _settings, root, *, operator_allowed_roots: (
                SimulatedProvider(WITNESS, root)
            ),
            _document_factory=SimulatedDocuments,
            **overrides,
        )

    return files, factory, WITNESS, settings


async def query(manager, file):
    return await manager.definition(file, line=1, column=1, expected_symbol="target")


async def until(condition, seconds=2):
    async def _wait():
        while not condition():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(_wait(), seconds)


@pytest.mark.asyncio
async def test_default_inert_lifetime_does_not_launch(fx):
    _files, factory, witness, _ = fx
    async with factory() as manager:
        assert manager.resident_count == 0
        assert manager.pending_count == 0
        assert not manager.observations()
        assert witness.launches == 0
    assert manager.closed
    assert witness.live == 0


@pytest.mark.asyncio
async def test_single_flight_same_canonical_workspace_many_concurrent_callers(fx):
    files, factory, witness, _ = fx
    async with factory(max_parallel_requests=3, max_per_provider_requests=2) as manager:
        results = await asyncio.gather(*(query(manager, files[0]) for _ in range(20)))
        assert len(results) == 20
        assert results[0][0]["relativePath"] == "main.py"
        assert witness.launches == 1
        assert manager.resident_count == 1
        assert manager.pending_count == 0
        assert 0 < witness.peak_parallel <= 2
    assert witness.document_starts == witness.document_exits == 1
    assert witness.live == 0
    assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_two_separate_roots_have_different_resident_processes(fx):
    files, factory, witness, _ = fx
    async with factory() as manager:
        await query(manager, files[0])
        await query(manager, files[1])
        await query(manager, files[0])
        assert witness.launches == 2
        assert witness.peak_live == 2
        assert manager.resident_count == 2
    assert witness.live == 0
    assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_lru_evicts_idle_instance_before_launching_next(fx):
    files, factory, witness, _ = fx
    async with factory(max_resident_servers=1) as manager:
        await query(manager, files[0])
        await query(manager, files[1])
        assert witness.launches == 2
        assert witness.peak_live == 1
        assert manager.resident_count == 1
        await query(manager, files[1])
        assert witness.launches == 2
    assert witness.live == 0


@pytest.mark.asyncio
async def test_capacity_rejects_second_project_when_first_is_busy(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    async with factory(max_resident_servers=1) as manager:
        task = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.query_started.wait(), 1)
        with pytest.raises(ProviderManagerError, match="capacity_reached"):
            await query(manager, files[1])
        witness.query_gate.set()
        assert (await task)[0]["relativePath"] == "main.py"
        assert witness.launches == 1
    assert witness.live == 0


@pytest.mark.asyncio
async def test_idle_sweeper_evicts_finished_instance(fx):
    files, factory, witness, _ = fx
    async with factory(idle_timeout_s=0.07) as manager:
        await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        assert witness.launches == 1
        assert witness.live == 0
        await query(manager, files[0])
        assert witness.launches == 2
    assert witness.live == 0


@pytest.mark.asyncio
async def test_idle_timeout_zero_closes_at_request_boundary(fx):
    files, factory, witness, _ = fx
    async with factory(idle_timeout_s=0) as manager:
        await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        await query(manager, files[0])
        assert witness.launches == 2
    assert witness.live == 0


@pytest.mark.asyncio
async def test_bounded_pending_admission_is_rejected_without_spawning(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    async with factory(max_pending_requests=1) as manager:
        task = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.query_started.wait(), 1)
        with pytest.raises(ProviderManagerError, match="queue_full"):
            await query(manager, files[0])
        witness.query_gate.set()
        await task
        assert witness.launches == 1


@pytest.mark.asyncio
async def test_invalid_symbol_anchor_never_launches_provider(fx):
    files, factory, witness, _ = fx
    async with factory() as manager:
        with pytest.raises(ValueError, match="anchor_mismatch"):
            await manager.definition(
                files[0], line=1, column=1, expected_symbol="wrong"
            )
        assert witness.launches == 0
        assert manager.resident_count == 0


@pytest.mark.asyncio
async def test_startup_single_flight_even_when_a_caller_cancels(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    async with factory() as manager:
        first = asyncio.create_task(query(manager, files[0]))
        await asyncio.wait_for(witness.started.wait(), 1)
        second = asyncio.create_task(query(manager, files[0]))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        witness.start_gate.set()
        assert (await asyncio.wait_for(second, 1))[0]["relativePath"] == "main.py"
        assert witness.launches == 1
    assert witness.live == 0


@pytest.mark.asyncio
async def test_provider_crash_forces_cooldown_not_reuse(fx):
    files, factory, witness, _ = fx
    async with factory(cooldown_base_s=0.18, cooldown_max_s=0.18) as manager:
        witness.process_crashed = True
        with pytest.raises(RuntimeError, match="crashed"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        assert witness.launches == 1
        witness.process_crashed = False
        with pytest.raises(ProviderManagerError, match="cooldown"):
            await query(manager, files[0])
        await asyncio.sleep(0.2)
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
        assert witness.launches == 2
    assert witness.live == 0


@pytest.mark.asyncio
async def test_provider_start_failure_cools_down_and_recovers(fx):
    files, factory, witness, _ = fx
    witness.fail_starts = 1
    async with factory(cooldown_base_s=0.1, cooldown_max_s=0.1) as manager:
        with pytest.raises(ProviderManagerError, match="not_ready"):
            await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        with pytest.raises(ProviderManagerError, match="cooldown"):
            await query(manager, files[0])
        await asyncio.sleep(0.13)
        assert (await query(manager, files[0]))[0]["relativePath"] == "main.py"
        assert witness.launches == 2


@pytest.mark.asyncio
async def test_unverified_process_cleanup_never_allows_same_key_restart(fx):
    files, factory, witness, _ = fx
    witness.unclean = True
    async with factory(idle_timeout_s=0) as manager:
        await query(manager, files[0])
        await until(lambda: manager.resident_count == 0)
        with pytest.raises(ProviderManagerError, match="cleanup_unverified"):
            await query(manager, files[0])
        assert witness.launches == 1
    assert (await manager.aclose()).cleanup_unverified


@pytest.mark.asyncio
async def test_shutdown_drains_then_cancels_stuck_request(fx):
    files, factory, witness, _ = fx
    witness.query_blocked = True
    manager = factory(shutdown_timeout_s=0.2)
    task = asyncio.create_task(query(manager, files[0]))
    await asyncio.wait_for(witness.query_started.wait(), 1)
    result = await asyncio.wait_for(manager.aclose(), 2)
    assert result.requests_cancelled == 1
    assert result.instances_stopped == 1
    assert not result.cleanup_unverified
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.closed and manager.resident_count == 0
    assert witness.live == 0


@pytest.mark.asyncio
async def test_manager_close_during_startup_is_bounded_and_does_not_late_launch(fx):
    files, factory, witness, _ = fx
    witness.start_blocked = True
    manager = factory(shutdown_timeout_s=0.15, startup_timeout_s=1)
    task = asyncio.create_task(query(manager, files[0]))
    await asyncio.wait_for(witness.started.wait(), 1)
    outcome = await asyncio.wait_for(manager.aclose(), 2)
    with pytest.raises((asyncio.CancelledError, ProviderManagerError)):
        await task
    assert outcome.instances_requested == 1
    assert manager.closed and manager.resident_count == 0
    assert witness.live == 0


@pytest.mark.asyncio
async def test_original_host_settings_mutation_does_not_change_generation(fx):
    files, factory, witness, settings = fx
    async with factory() as manager:
        settings.max_resident_servers = 1
        settings.enabled = False
        await query(manager, files[0])
        await query(manager, files[1])
        assert witness.launches == 2
        assert manager.resident_count == 2


@pytest.mark.asyncio
async def test_two_manager_generations_do_not_share_their_providers(fx):
    files, factory, witness, _ = fx
    async with factory() as first:
        await query(first, files[0])
    async with factory() as second:
        await query(second, files[0])
    assert witness.launches == 2
    assert witness.live == 0
