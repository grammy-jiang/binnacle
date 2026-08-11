"""Production graph composition with explicit temporary filesystem seams."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.conftest import FakeDeviceIdentityProvider
from tests.phase4_support import intent, migrate_database, owner

from binnacle.adapters.sqlite.engine import (
    DatabaseRuntimeSettings,
    acquire_runtime_lock,
    close_database_runtime,
    create_database_runtime,
)
from binnacle.adapters.sqlite.operation_store import SqliteOperationStore
from binnacle.composition import KernelCompositionPaths, compose_operation_kernel
from binnacle.config import BinnacleSettings
from binnacle.domain.audit import AuditTail
from binnacle.domain.idempotency import IdempotencyKeyMode, validate_and_digest_key
from binnacle.domain.operation import OperationState
from binnacle.domain.runtime import BuildIdentity
from binnacle.domain.trusted_time import TrustedTimeSnapshot
from binnacle.ports.audit import AuditObligation
from binnacle.ports.effect import UnavailableEffectBoundary
from binnacle.ports.operation_store import CreateOrFindRequest


class FakeTrustedTimeSource:
    async def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(
            wall_time=datetime(2026, 8, 11, tzinfo=UTC),
            monotonic_ns=123,
            boot_id_digest="a" * 64,
            wall_time_trusted=True,
        )


class UntrustedTimeSource:
    async def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(
            wall_time=datetime(2026, 8, 11, tzinfo=UTC),
            monotonic_ns=123,
            boot_id_digest="a" * 64,
            wall_time_trusted=False,
        )


def _paths(tmp_path: Path) -> KernelCompositionPaths:
    return KernelCompositionPaths(
        database=tmp_path / "state/binnacle.db",
        audit=tmp_path / "audit",
        payload=tmp_path / "results",
        runtime=tmp_path / "run",
        verify_runtime_directory=False,
    )


def _stub_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "binnacle.composition.LinuxDeviceIdentityProvider", FakeDeviceIdentityProvider
    )
    monkeypatch.setattr("binnacle.composition.LinuxTrustedTimeSource", FakeTrustedTimeSource)
    monkeypatch.setattr(
        "binnacle.composition.compute_build_identity",
        lambda *, version: BuildIdentity(version=version, build_sha256="b" * 64),
    )


@pytest.mark.anyio
async def test_kernel_composes_available_then_surviving_obligation_closes_gate(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.database.parent.mkdir(parents=True)
    migrate_database(paths.database, repo_root)
    _stub_identity(monkeypatch)

    first = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    assert first.health.consequential_admission_allowed
    assert first.gate.state.value == "open"
    assert await first.store.consequential_admission_enabled()
    await first.obligations.publish(AuditObligation("1", "obl-fixture", "op-fixture", 3))
    await first.close()
    await first.close()

    stopped_runtime = await create_database_runtime(
        DatabaseRuntimeSettings(
            paths.database,
            paths.runtime,
            verify_runtime_directory=False,
        )
    )
    try:
        assert not await SqliteOperationStore(stopped_runtime).consequential_admission_enabled()
    finally:
        await close_database_runtime(stopped_runtime)

    restarted = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    try:
        assert restarted.health.availability.value == "unavailable"
        assert restarted.health.reason_codes == ("audit_recovery_required",)
        assert restarted.health.obligation_count == 1
        assert restarted.health.audit_failure_latched
        assert restarted.gate.state.value == "closed"
        assert not await restarted.store.consequential_admission_enabled()
    finally:
        await restarted.close()


@pytest.mark.anyio
async def test_untrusted_startup_time_keeps_global_admission_closed(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.database.parent.mkdir(parents=True)
    migrate_database(paths.database, repo_root)
    _stub_identity(monkeypatch)
    monkeypatch.setattr("binnacle.composition.LinuxTrustedTimeSource", UntrustedTimeSource)

    kernel = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    try:
        assert kernel.health.availability.value == "unavailable"
        assert kernel.health.reason_codes == ("trusted_time_unavailable",)
        assert not kernel.health.consequential_admission_allowed
        assert kernel.gate.state.value == "closed"
        assert not await kernel.store.consequential_admission_enabled()
    finally:
        await kernel.close()


@pytest.mark.anyio
async def test_kernel_rejects_audit_cache_ahead_and_releases_database_lock(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.database.parent.mkdir(parents=True)
    migrate_database(paths.database, repo_root)
    _stub_identity(monkeypatch)
    first = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    await first.store.update_audit_tail_cache(AuditTail(1, "c" * 64))
    await first.close()

    with pytest.raises(RuntimeError, match="ahead of or divergent"):
        await compose_operation_kernel(
            settings=BinnacleSettings(), project_root=repo_root, paths=paths
        )

    # The failed composition must close its writer lock.
    lock = acquire_runtime_lock(
        paths.runtime, lock_name="database-writer.lock", verify_directory=False
    )
    lock.close()


@pytest.mark.anyio
async def test_kernel_composition_reconciles_before_opening_and_exposes_only_unavailable_effect(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.database.parent.mkdir(parents=True)
    migrate_database(paths.database, repo_root)
    _stub_identity(monkeypatch)
    first = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    key = validate_and_digest_key("ab" * 32, IdempotencyKeyMode.CALLER_KEY)
    created = await first.store.create_or_find(
        CreateOrFindRequest(
            key=key,
            owner=owner(),
            intent=intent(),
            tool_name="internal.synthetic",
            contract_version="1.0.0",
        )
    )
    assert created.operation is not None
    operation_id = created.operation.operation_id
    assert created.operation.state is OperationState.RECEIVED
    await first.close()

    restarted = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    try:
        reconciled = await restarted.store.get_operation(operation_id)
        assert reconciled is not None
        assert reconciled.state is OperationState.REJECTED
        assert isinstance(restarted.effect_boundary, UnavailableEffectBoundary)
        assert restarted.health.consequential_admission_allowed
        assert restarted.gate.state.value == "open"
    finally:
        await restarted.close()


@pytest.mark.anyio
async def test_kernel_rejects_cleared_generation_without_exact_journal_evidence(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.database.parent.mkdir(parents=True)
    migrate_database(paths.database, repo_root)
    _stub_identity(monkeypatch)
    first = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    generation = await first.store.latch_audit_failure("injected_outage")
    await first.store.clear_audit_failure(generation, "f" * 64)
    await first.close()

    restarted = await compose_operation_kernel(
        settings=BinnacleSettings(), project_root=repo_root, paths=paths
    )
    try:
        assert restarted.health.availability.value == "unavailable"
        assert restarted.health.reason_codes == ("audit_recovery_evidence_invalid",)
        assert restarted.gate.state.value == "closed"
        assert not await restarted.store.consequential_admission_enabled()
    finally:
        await restarted.close()
