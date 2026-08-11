"""Phase 5 fail-closed admission, corruption, and retained cleanup tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import text
from tests.phase5_support import controller_context, phase5_kernel

from binnacle.adapters.probe_workspace.reconcile import ProbeWorkspaceEffectBoundary
from binnacle.adapters.sqlite.probe_workspace import (
    ProbeWorkspaceStoreError,
    SqliteProbeWorkspaceRepository,
)
from binnacle.application.probe_workspace import ProbeWorkspaceService, ProbeWorkspaceUseCases
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeWorkspaceCleanupRequest,
    ProbeWorkspacePrepareRequest,
    ProbeWorkspaceWriteData,
    ProbeWorkspaceWriteRequest,
    SuccessEnvelope,
)
from binnacle.domain.operation import OperationOwner, OperationSnapshot
from binnacle.domain.probe_workspace import (
    ProbeFileObservation,
    ProbeOperationKind,
    ProbeTargetState,
    ProbeWorkspaceError,
)
from binnacle.ports.effect import EffectRequest, EffectStartReceipt
from binnacle.ports.probe_workspace import ProbeAuthorisationRequest

CONTENT = b"phase-five-fault"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()


async def _write_once(
    use_cases: ProbeWorkspaceUseCases,
    *,
    key: str = "a" * 32,
) -> tuple[SuccessEnvelope[ProbeWorkspaceWriteData], ProbeWorkspaceWriteRequest]:
    prepare = await use_cases.prepare(
        ProbeWorkspacePrepareRequest(
            ProbeOperationKind.WRITE,
            "probe.txt",
            CONTENT_SHA256,
            len(CONTENT),
        ),
        controller_context(),
    )
    assert isinstance(prepare, SuccessEnvelope)
    request = ProbeWorkspaceWriteRequest(
        prepare.data.prepared_operation_id,
        prepare.data.execution_nonce,
        key,
        "probe.txt",
        CONTENT,
        False,
    )
    result = await use_cases.write(request, controller_context())
    assert isinstance(result, SuccessEnvelope)
    return result, request


@pytest.mark.anyio
async def test_write_use_cases_require_authentication_and_exact_entitlement(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root, entitled=False) as (kernel, _root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        request = ProbeWorkspacePrepareRequest(
            ProbeOperationKind.WRITE,
            "probe.txt",
            CONTENT_SHA256,
            len(CONTENT),
        )

        unauthenticated = await use_cases.prepare(
            request,
            controller_context(authenticated=False),
        )
        denied = await use_cases.prepare(request, controller_context())

        assert isinstance(unauthenticated, ExecutionErrorEnvelope)
        assert unauthenticated.error.code == "authentication_required"
        assert isinstance(denied, ExecutionErrorEnvelope)
        assert denied.error.code == "probe_workspace_scope_required"


@pytest.mark.anyio
async def test_preparation_rejects_unsafe_shapes_and_existing_target(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        invalid_write = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                CONTENT_SHA256,
                None,
            ),
            controller_context(),
        )
        invalid_cleanup = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.CLEANUP,
                "probe.txt",
                CONTENT_SHA256,
                artifact_id=None,
            ),
            controller_context(),
        )
        (probe_root / "probe.txt").write_bytes(b"foreign")
        (probe_root / "probe.txt").chmod(0o600)
        occupied = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                CONTENT_SHA256,
                len(CONTENT),
            ),
            controller_context(),
        )

        assert isinstance(invalid_write, ExecutionErrorEnvelope)
        assert isinstance(invalid_cleanup, ExecutionErrorEnvelope)
        assert isinstance(occupied, ExecutionErrorEnvelope)
        assert occupied.error.code == "probe_preparation_rejected"


@pytest.mark.anyio
async def test_cleanup_missing_before_start_is_known_no_effect_and_retained(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, trusted_time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        written, _request = await _write_once(use_cases)
        artifact_id = written.data.artifact_id
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.CLEANUP,
                "probe.txt",
                CONTENT_SHA256,
                artifact_id=artifact_id,
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        original = SqliteProbeWorkspaceRepository.authorise

        async def authorise_then_remove(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            with pytest.raises(ProbeWorkspaceStoreError, match="target changed"):
                repository._validate_filesystem_admission(
                    request,
                    ProbeFileObservation(ProbeTargetState.MISMATCH),
                )
            result = await original(repository, request)
            (probe_root / "probe.txt").unlink()
            return result

        monkeypatch.setattr(SqliteProbeWorkspaceRepository, "authorise", authorise_then_remove)
        cleanup_request = ProbeWorkspaceCleanupRequest(
            preparation.data.prepared_operation_id,
            preparation.data.execution_nonce,
            "c" * 32,
            "probe.txt",
            artifact_id,
            CONTENT_SHA256,
        )
        cleaned = await use_cases.cleanup(cleanup_request, controller_context())
        assert isinstance(cleaned, SuccessEnvelope)
        assert cleaned.data.already_missing and not cleaned.data.removed

        trusted_time.advance(1_000)
        retained = await use_cases.cleanup(cleanup_request, controller_context())
        assert isinstance(retained, SuccessEnvelope)
        assert retained.operation == cleaned.operation
        assert retained.data == cleaned.data


@pytest.mark.anyio
async def test_cleanup_prepared_from_observed_absence_is_known_no_effect(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        written, _request = await _write_once(use_cases)
        (probe_root / "probe.txt").unlink()
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.CLEANUP,
                "probe.txt",
                CONTENT_SHA256,
                artifact_id=written.data.artifact_id,
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        original = SqliteProbeWorkspaceRepository.authorise

        async def recheck_absence_then_authorise(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            with pytest.raises(ProbeWorkspaceStoreError, match="absence changed"):
                repository._validate_filesystem_admission(
                    request,
                    ProbeFileObservation(
                        ProbeTargetState.EXACT,
                        file_identity_digest="b" * 64,
                        content_sha256=CONTENT_SHA256,
                        byte_count=len(CONTENT),
                    ),
                )
            return await original(repository, request)

        monkeypatch.setattr(
            SqliteProbeWorkspaceRepository,
            "authorise",
            recheck_absence_then_authorise,
        )

        cleaned = await use_cases.cleanup(
            ProbeWorkspaceCleanupRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "1" * 32,
                "probe.txt",
                written.data.artifact_id,
                CONTENT_SHA256,
            ),
            controller_context(),
        )

        assert isinstance(cleaned, SuccessEnvelope)
        assert cleaned.data.already_missing and not cleaned.data.removed
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)
        snapshot = await repository.get_path_snapshot("probe.txt")
        assert snapshot.active_artifact is None
        assert snapshot.terminal_artifacts[-1].removed_by_cleanup_operation_id is None


@pytest.mark.anyio
async def test_ledger_corruption_after_cleanup_admission_prevents_unlink(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        written, _request = await _write_once(use_cases)
        artifact_id = written.data.artifact_id
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.CLEANUP,
                "probe.txt",
                CONTENT_SHA256,
                artifact_id=artifact_id,
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)

        original = SqliteProbeWorkspaceRepository.authorise

        async def authorise_then_corrupt(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            result = await original(repository, request)
            async with kernel.database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE probe_path_ledger SET terminal_history_sha256=:digest "
                        "WHERE relative_path='probe.txt'"
                    ),
                    {"digest": "f" * 64},
                )
            return result

        monkeypatch.setattr(SqliteProbeWorkspaceRepository, "authorise", authorise_then_corrupt)
        result = await use_cases.cleanup(
            ProbeWorkspaceCleanupRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "d" * 32,
                "probe.txt",
                artifact_id,
                CONTENT_SHA256,
            ),
            controller_context(),
        )

        assert isinstance(result, ExecutionErrorEnvelope)
        assert (probe_root / "probe.txt").read_bytes() == CONTENT


@pytest.mark.parametrize(
    "mutation",
    (
        "prepared_binding_id=caller_binding_id",
        "caller_binding_id=prepared_binding_id",
    ),
)
@pytest.mark.anyio
async def test_binding_corruption_after_admission_prevents_effect_start(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    statements = {
        "prepared_binding_id=caller_binding_id": (
            "UPDATE probe_operations SET prepared_binding_id=caller_binding_id "
            "WHERE operation_id=:operation_id"
        ),
        "caller_binding_id=prepared_binding_id": (
            "UPDATE probe_operations SET caller_binding_id=prepared_binding_id "
            "WHERE operation_id=:operation_id"
        ),
    }
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                CONTENT_SHA256,
                len(CONTENT),
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        original_authorise = SqliteProbeWorkspaceRepository.authorise
        original_start = ProbeWorkspaceEffectBoundary.start
        starts = 0

        async def authorise_then_corrupt_binding(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            result = await original_authorise(repository, request)
            async with kernel.database.engine.begin() as connection:
                await connection.execute(
                    text(statements[mutation]),
                    {"operation_id": result.operation_id},
                )
            return result

        async def count_start(
            boundary: ProbeWorkspaceEffectBoundary,
            request: EffectRequest,
        ) -> EffectStartReceipt:
            nonlocal starts
            starts += 1
            return await original_start(boundary, request)

        monkeypatch.setattr(
            SqliteProbeWorkspaceRepository,
            "authorise",
            authorise_then_corrupt_binding,
        )
        monkeypatch.setattr(ProbeWorkspaceEffectBoundary, "start", count_start)
        result = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "9" * 32,
                "probe.txt",
                CONTENT,
                False,
            ),
            controller_context(),
        )

        assert isinstance(result, ExecutionErrorEnvelope)
        assert starts == 0
        assert not (probe_root / "probe.txt").exists()


@pytest.mark.anyio
async def test_prepared_ledger_change_before_authorisation_reserves_nothing(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                CONTENT_SHA256,
                len(CONTENT),
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        original = SqliteProbeWorkspaceRepository.authorise

        async def change_ledger_then_authorise(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            async with kernel.database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE probe_path_ledger SET ledger_version=ledger_version+1 "
                        "WHERE relative_path='probe.txt'"
                    )
                )
            return await original(repository, request)

        monkeypatch.setattr(
            SqliteProbeWorkspaceRepository,
            "authorise",
            change_ledger_then_authorise,
        )
        result = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "e" * 32,
                "probe.txt",
                CONTENT,
                False,
            ),
            controller_context(),
        )

        assert isinstance(result, ExecutionErrorEnvelope)
        assert not (probe_root / "probe.txt").exists()
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)
        assert await repository.list_probe_operations() == ()
        snapshot = await repository.get_path_snapshot("probe.txt")
        assert snapshot.active_artifact is None
        assert snapshot.ledger.generation_high_water == 0


@pytest.mark.anyio
async def test_prepared_target_change_before_authorisation_reserves_nothing(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                CONTENT_SHA256,
                len(CONTENT),
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        original = SqliteProbeWorkspaceRepository.authorise

        async def occupy_target_then_authorise(
            repository: SqliteProbeWorkspaceRepository,
            request: ProbeAuthorisationRequest,
        ) -> OperationSnapshot:
            (probe_root / "probe.txt").write_bytes(b"foreign")
            (probe_root / "probe.txt").chmod(0o600)
            return await original(repository, request)

        monkeypatch.setattr(
            SqliteProbeWorkspaceRepository,
            "authorise",
            occupy_target_then_authorise,
        )
        result = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "f" * 32,
                "probe.txt",
                CONTENT,
                False,
            ),
            controller_context(),
        )

        assert isinstance(result, ExecutionErrorEnvelope)
        assert (probe_root / "probe.txt").read_bytes() == b"foreign"
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)
        assert await repository.list_probe_operations() == ()
        assert (await repository.get_path_snapshot("probe.txt")).active_artifact is None


@pytest.mark.anyio
async def test_repository_anchor_queries_and_integrity_fail_closed(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, _probe_root, _time):
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)
        first = await repository.ensure_path_anchor("never.txt")
        second = await repository.ensure_path_anchor("never.txt")
        assert first == second
        assert await repository.get_probe_operation("op-missing") is None
        assert await repository.get_prepared_state_binding_sha256("prepared-missing") is None
        assert await repository.list_probe_operations() == ()
        assert await repository.list_probe_operations_for_closure(limit=1) == ()
        with pytest.raises(ValueError, match="limit"):
            await repository.list_probe_operations_for_closure(limit=0)
        with pytest.raises(ValueError, match="cursor"):
            await repository.list_probe_operations_for_closure(
                limit=1,
                after_created_at=None,
                after_operation_id="op-cursor",
            )
        with pytest.raises(ProbeWorkspaceStoreError, match="ledger is missing"):
            await repository.get_path_snapshot("missing.txt")

        async with kernel.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE probe_path_ledger SET terminal_history_sha256=:digest "
                    "WHERE relative_path='never.txt'"
                ),
                {"digest": "f" * 64},
            )
        with pytest.raises(ProbeWorkspaceError, match="digest"):
            await repository.verify_integrity()


@pytest.mark.anyio
async def test_write_projection_is_exact_and_fail_closed_for_bad_execution_shapes(
    tmp_path: Path, repo_root: Path
) -> None:
    class Resolver:
        def __call__(self, context: McpCallContext) -> OperationOwner:
            del context
            return OperationOwner("controller-fixture", 1, "profile-fixture", "1.0.0")

    with pytest.raises(ValueError, match="exact write-probe"):
        ProbeWorkspaceUseCases(
            service=object.__new__(ProbeWorkspaceService),
            contracts=ContractRegistry.load(),
            controller_resolver=Resolver(),
            entitlement=lambda _context: True,
            maximum_file_bytes=65_536,
        )

    async with phase5_kernel(tmp_path, repo_root) as (kernel, _root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        context = controller_context()
        missing_write = ProbeWorkspaceWriteRequest(
            "prepared-missing",
            "n" * 32,
            "k" * 32,
            "probe.txt",
            CONTENT,
            False,
        )
        missing_cleanup = ProbeWorkspaceCleanupRequest(
            "prepared-missing",
            "n" * 32,
            "k" * 32,
            "probe.txt",
            "artifact-missing",
            CONTENT_SHA256,
        )

        assert isinstance(
            await use_cases.write(missing_write, controller_context(authenticated=False)),
            ExecutionErrorEnvelope,
        )
        assert isinstance(
            await use_cases.cleanup(missing_cleanup, controller_context(authenticated=False)),
            ExecutionErrorEnvelope,
        )
        rejected_write = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                "prepared-missing",
                "n" * 32,
                "k" * 32,
                "probe.txt",
                CONTENT,
                True,
            ),
            context,
        )
        rejected_cleanup = await use_cases.cleanup(
            ProbeWorkspaceCleanupRequest(
                "prepared-missing",
                "n" * 32,
                "k" * 32,
                "probe.txt",
                "contains space",
                CONTENT_SHA256,
            ),
            context,
        )
        missing_write_result = await use_cases.write(missing_write, context)
        missing_cleanup_result = await use_cases.cleanup(missing_cleanup, context)

        assert isinstance(rejected_write, ExecutionErrorEnvelope)
        assert rejected_write.error.code == "probe_write_rejected"
        assert isinstance(rejected_cleanup, ExecutionErrorEnvelope)
        assert rejected_cleanup.error.code == "probe_cleanup_rejected"
        assert isinstance(missing_write_result, ExecutionErrorEnvelope)
        assert missing_write_result.error.code == "prepared_operation_mismatch"
        assert isinstance(missing_cleanup_result, ExecutionErrorEnvelope)
        assert missing_cleanup_result.error.code == "prepared_operation_mismatch"


@pytest.mark.anyio
async def test_repository_rejects_wrong_closure_kind_state_and_missing_rows(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, _root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        written, _request = await _write_once(use_cases)
        operation = written.operation
        assert operation is not None
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)

        invalid_calls = (
            repository.mark_write_uncertain(operation.operation_id),
            repository.close_write_created(
                operation.operation_id,
                file_identity_digest="f" * 64,
            ),
            repository.close_write_abandoned(operation.operation_id),
            repository.close_cleanup_removed(
                operation.operation_id,
                removed_by_operation=True,
            ),
            repository.clear_cleanup_claim(operation.operation_id),
            repository.mark_write_uncertain("operation-missing"),
            repository.close_write_created(
                "operation-missing",
                file_identity_digest="f" * 64,
            ),
            repository.close_write_abandoned("operation-missing"),
            repository.close_cleanup_removed(
                "operation-missing",
                removed_by_operation=False,
            ),
            repository.clear_cleanup_claim("operation-missing"),
        )
        for call in invalid_calls:
            with pytest.raises((ProbeWorkspaceStoreError, RuntimeError)):
                await call

        probes = await repository.list_probe_operations()
        assert len(probes) == 1
        assert probes[0].operation_id == operation.operation_id
        assert (
            await repository.list_probe_operations_for_closure(
                limit=1,
                after_created_at=probes[0].created_at,
                after_operation_id=probes[0].operation_id,
            )
            == ()
        )

        # Keep the foreign keys valid while proving semantic provenance is checked.
        async with kernel.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE probe_operations SET caller_binding_id=prepared_binding_id "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation.operation_id},
            )
        with pytest.raises(ProbeWorkspaceStoreError, match="provenance"):
            await repository.verify_integrity()


@pytest.mark.anyio
async def test_repository_rejects_coordinated_live_artifact_fact_corruption(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, _root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        written, _request = await _write_once(use_cases)
        assert written.operation is not None
        repository = SqliteProbeWorkspaceRepository(kernel.database, kernel.store)

        async with kernel.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE probe_artifacts SET content_sha256=:digest "
                    "WHERE create_operation_id=:operation_id"
                ),
                {"digest": "f" * 64, "operation_id": written.operation.operation_id},
            )
            await connection.execute(
                text(
                    "UPDATE probe_operations SET expected_content_sha256=:digest "
                    "WHERE operation_id=:operation_id"
                ),
                {"digest": "f" * 64, "operation_id": written.operation.operation_id},
            )

        with pytest.raises(ProbeWorkspaceStoreError, match="provenance"):
            await repository.verify_integrity()
