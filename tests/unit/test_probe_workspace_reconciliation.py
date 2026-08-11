"""Receipt, no-effect, and restart closure tests for the Phase 5 probe."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from tests.phase4_support import NOW, audit_identity, audit_schema, intent, owner

from binnacle.adapters.audit.journal import FileAuditJournal
from binnacle.adapters.probe_workspace import ProbeEffectNotStarted
from binnacle.adapters.probe_workspace.reconcile import (
    ProbeEffectReferenceError,
    ProbeReconciliationStore,
    ProbeWorkspaceEffectBoundary,
    ProbeWorkspaceReconciler,
    effect_reference_digest,
    parse_probe_effect_reference,
)
from binnacle.application.boundary import ConsequentialBoundaryGate, GateState
from binnacle.application.probe_workspace import ProbePreparedStateVerifier
from binnacle.application.reconciliation import (
    OperationReconciler,
    ReconciliationStore,
    SpecializedOperationReconciler,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    terminality_for,
)
from binnacle.domain.probe_workspace import (
    EMPTY_TERMINAL_HISTORY_SHA256,
    ProbeArtifact,
    ProbeArtifactState,
    ProbeFileObservation,
    ProbeOperationKind,
    ProbeOperationRecord,
    ProbePathLedger,
    ProbePathSnapshot,
    ProbePreparedState,
    ProbeRootIdentity,
    ProbeTargetState,
    ProbeWorkspaceError,
    prepared_state_sha256,
)
from binnacle.ports.audit import AuditJournal, AuditObligation, AuditObligationStore
from binnacle.ports.boundary import BoundaryDisposition
from binnacle.ports.effect import BoundaryCrossing, EffectRequest
from binnacle.ports.probe_workspace import (
    ProbeBoundarySnapshot,
    ProbeWorkspaceFilesystem,
    ProbeWorkspaceRepository,
)

CONTENT = b"phase-five"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
IDENTITY = "d" * 64
WRITE_REFERENCE = f"probe-write:v1:artifact-fixture:1:{IDENTITY}"
CLEANUP_REFERENCE = f"probe-cleanup:v1:artifact-fixture:1:{IDENTITY}"


def _operation(
    *,
    state: OperationState,
    knowledge: EffectKnowledge,
    reference: str | None = None,
) -> OperationSnapshot:
    error = None
    if state in {OperationState.FAILED, OperationState.UNCERTAIN}:
        error = OperationError("fixture_error", "Fixture error.", "reconcile")
    return OperationSnapshot(
        operation_id="op-fixture",
        owner=owner(),
        intent=intent(),
        state=state,
        state_version=4,
        effect_knowledge=knowledge,
        terminality=terminality_for(state),
        automatic_retry_allowed=False,
        created_at=NOW,
        updated_at=NOW,
        authorised_at=NOW,
        started_at=NOW if state is not OperationState.AUTHORISED else None,
        terminal_at=NOW if state is OperationState.FAILED else None,
        effect_reference=reference,
        effect_reference_digest=(None if reference is None else effect_reference_digest(reference)),
        error=error,
    )


def _probe(kind: ProbeOperationKind) -> ProbeOperationRecord:
    return ProbeOperationRecord(
        operation_id="op-fixture",
        probe_operation=kind,
        prepared_binding_id="prepared-fixture",
        caller_binding_id="caller-fixture",
        artifact_id="artifact-fixture",
        relative_path="probe.txt",
        expected_content_sha256=CONTENT_SHA256,
        expected_byte_count=len(CONTENT) if kind is ProbeOperationKind.WRITE else None,
        prepared_state_binding_sha256="a" * 64,
        created_at=NOW,
    )


def _artifact(*, state: ProbeArtifactState, identity: str | None = IDENTITY) -> ProbeArtifact:
    return ProbeArtifact(
        artifact_id="artifact-fixture",
        relative_path="probe.txt",
        path_generation=1,
        owner_controller_id="controller-fixture",
        owner_controller_epoch=1,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
        state=state,
        create_operation_id="op-write",
        active_cleanup_operation_id=("op-fixture" if state is ProbeArtifactState.CREATED else None),
        removed_by_cleanup_operation_id=None,
        created_at=NOW,
        updated_at=NOW,
        file_identity_digest=identity,
    )


def _path(artifact: ProbeArtifact | None) -> ProbePathSnapshot:
    return ProbePathSnapshot(
        ledger=ProbePathLedger(
            relative_path="probe.txt",
            generation_high_water=0 if artifact is None else 1,
            terminal_history_count=0,
            terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
            active_artifact_id=None if artifact is None else artifact.artifact_id,
            active_generation=None if artifact is None else artifact.path_generation,
            active_create_operation_id=(None if artifact is None else artifact.create_operation_id),
            ledger_version=1,
            updated_at=NOW,
        ),
        terminal_artifacts=(),
        active_artifact=artifact,
    )


def _protected_facts(
    operation: ProbeOperationKind,
    *,
    artifact_id: str | None = None,
) -> dict[str, str]:
    return {
        "operation": operation.value,
        "relative_path": "probe.txt",
        "content_sha256": CONTENT_SHA256,
        "byte_count": str(len(CONTENT)) if operation is ProbeOperationKind.WRITE else "",
        "artifact_id": artifact_id or "",
        "owner_controller_id": "controller-fixture",
        "owner_controller_epoch": "1",
    }


def _prepared_state(
    *,
    operation: ProbeOperationKind,
    root: ProbeRootIdentity,
    path: ProbePathSnapshot,
) -> ProbePreparedState:
    artifact = path.active_artifact
    if operation is ProbeOperationKind.WRITE:
        return ProbePreparedState(
            operation=operation,
            relative_path="probe.txt",
            content_sha256=CONTENT_SHA256,
            byte_count=len(CONTENT),
            artifact_id=None,
            owner_controller_id="controller-fixture",
            owner_controller_epoch=1,
            root_identity_sha256=root.digest_sha256,
            ledger_version=path.ledger.ledger_version - 1,
            generation_high_water=path.ledger.generation_high_water - 1,
            terminal_history_count=0,
            terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
            active_artifact_id=None,
            active_generation=None,
            active_create_operation_id=None,
            write_reservation_transition=(
                "absent_generation_N_then_exact_self_reserved_generation_N_plus_1"
            ),
            cleanup_target_transition=None,
            cleanup_claim_transition=None,
            expected_file_identity_digest=None,
        )
    assert artifact is not None
    return ProbePreparedState(
        operation=operation,
        relative_path="probe.txt",
        content_sha256=CONTENT_SHA256,
        byte_count=None,
        artifact_id=artifact.artifact_id,
        owner_controller_id="controller-fixture",
        owner_controller_epoch=1,
        root_identity_sha256=root.digest_sha256,
        ledger_version=path.ledger.ledger_version,
        generation_high_water=path.ledger.generation_high_water,
        terminal_history_count=0,
        terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
        active_artifact_id=artifact.artifact_id,
        active_generation=artifact.path_generation,
        active_create_operation_id=artifact.create_operation_id,
        write_reservation_transition=None,
        cleanup_target_transition="exact_prepared_identity_or_absent_no_start",
        cleanup_claim_transition="unclaimed_then_exact_self",
        expected_file_identity_digest=artifact.file_identity_digest,
    )


def _dependencies(
    *,
    kind: ProbeOperationKind,
    artifact: ProbeArtifact | None,
    observation: ProbeFileObservation,
    probe: ProbeOperationRecord | object | None = ...,  # sentinel for the default record
) -> tuple[
    ProbeWorkspaceRepository,
    ProbeWorkspaceFilesystem,
    ProbeReconciliationStore,
    AuditJournal,
    AuditObligationStore,
    dict[str, AsyncMock],
]:
    selected_probe = _probe(kind) if probe is ... else probe
    calls = {
        "get_probe": AsyncMock(return_value=selected_probe),
        "get_path": AsyncMock(return_value=_path(artifact)),
        "list_closure": AsyncMock(return_value=()),
        "mark_uncertain": AsyncMock(),
        "close_created": AsyncMock(
            return_value=_operation(
                state=OperationState.SUCCEEDED,
                knowledge=EffectKnowledge.KNOWN_EFFECT,
                reference=WRITE_REFERENCE,
            )
        ),
        "close_abandoned": AsyncMock(),
        "close_removed": AsyncMock(
            return_value=_operation(
                state=OperationState.SUCCEEDED,
                knowledge=EffectKnowledge.KNOWN_EFFECT,
                reference=CLEANUP_REFERENCE,
            )
        ),
        "clear_claim": AsyncMock(),
        "observe": AsyncMock(return_value=observation),
        "create": AsyncMock(return_value=WRITE_REFERENCE),
        "remove": AsyncMock(return_value=CLEANUP_REFERENCE),
        "transition": AsyncMock(),
        "get_operation": AsyncMock(),
        "scan": AsyncMock(return_value=()),
        "state_evidence": AsyncMock(return_value="e" * 64),
        "closure_health": AsyncMock(return_value=True),
        "update_tail": AsyncMock(),
        "latch_audit": AsyncMock(return_value=1),
    }
    repository = cast(
        ProbeWorkspaceRepository,
        SimpleNamespace(
            get_probe_operation=calls["get_probe"],
            get_path_snapshot=calls["get_path"],
            list_probe_operations_for_closure=calls["list_closure"],
            mark_write_uncertain=calls["mark_uncertain"],
            close_write_created=calls["close_created"],
            close_write_abandoned=calls["close_abandoned"],
            close_cleanup_removed=calls["close_removed"],
            clear_cleanup_claim=calls["clear_claim"],
        ),
    )
    filesystem = cast(
        ProbeWorkspaceFilesystem,
        SimpleNamespace(
            observe=calls["observe"],
            create=calls["create"],
            remove=calls["remove"],
        ),
    )
    operations = cast(
        ProbeReconciliationStore,
        SimpleNamespace(
            transition=calls["transition"],
            get_operation=calls["get_operation"],
            update_audit_tail_cache=calls["update_tail"],
            latch_audit_failure=calls["latch_audit"],
        ),
    )
    audit = cast(
        AuditJournal,
        SimpleNamespace(find_operation_state_evidence=calls["state_evidence"]),
    )
    obligations = cast(AuditObligationStore, SimpleNamespace(scan=calls["scan"]))
    return repository, filesystem, operations, audit, obligations, calls


@pytest.mark.anyio
async def test_final_boundary_rejects_digest_and_last_moment_target_drift() -> None:
    root = ProbeRootIdentity("b" * 64, 1, 2, 1000, 1000, 0o700)
    write_artifact = replace(
        _artifact(state=ProbeArtifactState.RESERVED, identity=None),
        create_operation_id="op-fixture",
    )
    write_path = _path(write_artifact)
    write_path = replace(
        write_path,
        ledger=replace(write_path.ledger, ledger_version=2),
    )
    write_state = _prepared_state(
        operation=ProbeOperationKind.WRITE,
        root=root,
        path=write_path,
    )
    write_boundary = ProbeBoundarySnapshot(
        probe_operation=_probe(ProbeOperationKind.WRITE),
        path=write_path,
        prepared_state_binding_sha256=prepared_state_sha256(write_state),
    )

    def verifier(
        boundary: ProbeBoundarySnapshot,
        *observations: ProbeFileObservation,
    ) -> ProbePreparedStateVerifier:
        repository = cast(
            ProbeWorkspaceRepository,
            SimpleNamespace(get_boundary_snapshot=AsyncMock(return_value=boundary)),
        )
        filesystem = cast(
            ProbeWorkspaceFilesystem,
            SimpleNamespace(
                root_identity=AsyncMock(return_value=root),
                observe=AsyncMock(side_effect=observations),
            ),
        )
        return ProbePreparedStateVerifier(repository=repository, filesystem=filesystem)

    mismatched_binding = replace(
        write_boundary,
        prepared_state_binding_sha256="f" * 64,
    )
    with pytest.raises(ProbeWorkspaceError, match="does not match preparation"):
        await verifier(
            mismatched_binding,
            ProbeFileObservation(ProbeTargetState.ABSENT),
        ).boundary_decision(
            operation_id="op-fixture",
            prepared_operation_id="prepared-fixture",
            protected_facts=_protected_facts(ProbeOperationKind.WRITE),
        )

    write_decision = await verifier(
        write_boundary,
        ProbeFileObservation(ProbeTargetState.ABSENT),
        ProbeFileObservation(ProbeTargetState.MISMATCH),
    ).boundary_decision(
        operation_id="op-fixture",
        prepared_operation_id="prepared-fixture",
        protected_facts=_protected_facts(ProbeOperationKind.WRITE),
    )
    assert write_decision.disposition is BoundaryDisposition.DENY
    assert write_decision.reason_code == "probe_target_not_absent"

    cleanup_artifact = _artifact(state=ProbeArtifactState.CREATED)
    cleanup_path = _path(cleanup_artifact)
    cleanup_state = _prepared_state(
        operation=ProbeOperationKind.CLEANUP,
        root=root,
        path=cleanup_path,
    )
    cleanup_boundary = ProbeBoundarySnapshot(
        probe_operation=_probe(ProbeOperationKind.CLEANUP),
        path=cleanup_path,
        prepared_state_binding_sha256=prepared_state_sha256(cleanup_state),
    )
    exact = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    cleanup_decision = await verifier(
        cleanup_boundary,
        exact,
        ProbeFileObservation(ProbeTargetState.MISMATCH),
    ).boundary_decision(
        operation_id="op-fixture",
        prepared_operation_id="prepared-fixture",
        protected_facts=_protected_facts(
            ProbeOperationKind.CLEANUP,
            artifact_id="artifact-fixture",
        ),
    )
    assert cleanup_decision.disposition is BoundaryDisposition.DENY
    assert cleanup_decision.reason_code == "probe_cleanup_identity_mismatch"


@pytest.mark.anyio
async def test_effect_boundary_classifies_only_exact_bound_dispatch() -> None:
    exact = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    repository, filesystem, _operations, _audit, _obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=exact,
    )
    boundary = ProbeWorkspaceEffectBoundary(repository=repository, filesystem=filesystem)
    request = EffectRequest(
        "op-fixture",
        4,
        "probe_workspace_write",
        {"content": CONTENT},
    )

    receipt = await boundary.start(request)
    assert receipt.crossing is BoundaryCrossing.CROSSED
    assert receipt.reference == WRITE_REFERENCE

    calls["get_probe"].return_value = None
    assert (await boundary.start(request)).reason_code == "probe_effect_request_mismatch"
    calls["get_probe"].return_value = _probe(ProbeOperationKind.WRITE)
    calls["get_path"].return_value = _path(None)
    assert (await boundary.start(request)).reason_code == "probe_active_artifact_mismatch"
    calls["get_path"].return_value = _path(
        _artifact(state=ProbeArtifactState.RESERVED, identity=None)
    )
    assert (
        await boundary.start(
            EffectRequest("op-fixture", 4, "probe_workspace_write", {"content": b"wrong"})
        )
    ).reason_code == "probe_write_content_mismatch"
    calls["create"].side_effect = ProbeEffectNotStarted("probe_target_not_absent")
    assert (await boundary.start(request)).reason_code == "probe_target_not_absent"


@pytest.mark.anyio
async def test_cleanup_boundary_rejects_arguments_identity_and_absence() -> None:
    exact = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    artifact = _artifact(state=ProbeArtifactState.CREATED)
    repository, filesystem, _operations, _audit, _obligations, calls = _dependencies(
        kind=ProbeOperationKind.CLEANUP,
        artifact=artifact,
        observation=exact,
    )
    boundary = ProbeWorkspaceEffectBoundary(repository=repository, filesystem=filesystem)
    request = EffectRequest("op-fixture", 4, "probe_workspace_cleanup", {})

    assert (await boundary.start(request)).reference == CLEANUP_REFERENCE
    assert (
        await boundary.start(
            EffectRequest("op-fixture", 4, "probe_workspace_cleanup", {"path": "untrusted"})
        )
    ).reason_code == "probe_cleanup_arguments_invalid"
    calls["get_path"].return_value = _path(
        _artifact(state=ProbeArtifactState.CREATED, identity=None)
    )
    assert (await boundary.start(request)).reason_code == "probe_cleanup_identity_unavailable"
    calls["get_path"].return_value = _path(artifact)
    calls["remove"].return_value = None
    assert (await boundary.start(request)).reason_code == "probe_cleanup_absent_after_start"


@pytest.mark.anyio
async def test_reconciler_closes_known_write_and_cleanup_effects() -> None:
    exact = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    repository, filesystem, operations, audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=exact,
    )
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=audit,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )
    written = await reconciler.close_operation(
        _operation(
            state=OperationState.RUNNING,
            knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference=WRITE_REFERENCE,
        )
    )
    assert written.state is OperationState.SUCCEEDED
    calls["close_created"].assert_awaited_once_with("op-fixture", file_identity_digest=IDENTITY)

    calls["get_probe"].return_value = _probe(ProbeOperationKind.CLEANUP)
    calls["get_path"].return_value = _path(_artifact(state=ProbeArtifactState.CREATED))
    calls["observe"].return_value = ProbeFileObservation(ProbeTargetState.ABSENT)
    cleaned = await reconciler.close_operation(
        _operation(
            state=OperationState.RUNNING,
            knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference=CLEANUP_REFERENCE,
        )
    )
    assert cleaned.state is OperationState.SUCCEEDED
    calls["close_removed"].assert_awaited_with("op-fixture", removed_by_operation=True)


@pytest.mark.anyio
async def test_reconciler_preserves_uncertainty_and_no_effect_truth() -> None:
    absent = ProbeFileObservation(ProbeTargetState.ABSENT)
    repository, filesystem, operations, audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=absent,
    )
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=audit,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )
    uncertain = _operation(
        state=OperationState.UNCERTAIN,
        knowledge=EffectKnowledge.UNCERTAIN,
    )
    assert await reconciler.close_operation(uncertain) is uncertain
    calls["mark_uncertain"].assert_awaited_once()

    failed = _operation(
        state=OperationState.FAILED,
        knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
    )
    assert await reconciler.close_operation(failed) is failed
    calls["close_abandoned"].assert_awaited_once_with("op-fixture")

    calls["get_probe"].return_value = _probe(ProbeOperationKind.CLEANUP)
    calls["get_path"].return_value = _path(_artifact(state=ProbeArtifactState.CREATED))
    assert await reconciler.close_operation(failed) is failed
    calls["close_removed"].assert_awaited_with("op-fixture", removed_by_operation=False)

    calls["observe"].return_value = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    assert await reconciler.close_operation(failed) is failed
    calls["clear_claim"].assert_awaited_once_with("op-fixture")


@pytest.mark.anyio
async def test_restart_reconciliation_classifies_pre_dispatch_and_missing_receipt() -> None:
    absent = ProbeFileObservation(ProbeTargetState.ABSENT)
    repository, filesystem, operations, audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=absent,
    )
    failed = _operation(
        state=OperationState.FAILED,
        knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
    )
    calls["transition"].return_value = failed
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=audit,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )
    assert (
        await reconciler.reconcile(
            _operation(state=OperationState.AUTHORISED, knowledge=EffectKnowledge.NONE)
        )
    ) is failed
    calls["close_abandoned"].assert_awaited_once()

    uncertain = _operation(
        state=OperationState.UNCERTAIN,
        knowledge=EffectKnowledge.UNCERTAIN,
    )
    calls["transition"].return_value = uncertain
    result = await reconciler.close_operation(
        _operation(state=OperationState.RUNNING, knowledge=EffectKnowledge.NONE)
    )
    assert result is uncertain
    calls["mark_uncertain"].assert_awaited()

    calls["get_probe"].return_value = None
    ordinary = _operation(state=OperationState.RUNNING, knowledge=EffectKnowledge.NONE)
    assert await reconciler.reconcile(ordinary) is None
    assert await reconciler.close_operation(ordinary) is ordinary


@pytest.mark.anyio
async def test_restart_no_effect_audit_survives_both_closure_crash_windows(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    repository, filesystem, operations, _audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=ProbeFileObservation(ProbeTargetState.ABSENT),
    )
    failed = replace(
        _operation(
            state=OperationState.FAILED,
            knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
        ),
        state_version=5,
        started_at=None,
        error=OperationError(
            "reconciliation_unavailable",
            "Probe operation did not reach the durable dispatch marker.",
        ),
    )
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    await journal.open()
    calls["close_abandoned"].side_effect = RuntimeError("crash after audit append")
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=journal,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )

    # This starts from the durable post-transition state: the prior process may have
    # crashed after AUTHORISED -> FAILED and before writing its recovery audit fact.
    with pytest.raises(RuntimeError, match="crash after audit append"):
        await reconciler.close_operation(failed)
    assert journal.tail.sequence == 1
    assert (
        await journal.find_operation_state_evidence(
            operation_id=failed.operation_id,
            state_version=failed.state_version,
            state=failed.state.value,
            effect_knowledge=failed.effect_knowledge.value,
        )
        is not None
    )

    # A fresh journal instance models restart after the audit fsync but before the
    # separate Phase 5 reservation closure. It must reuse, not duplicate, evidence.
    reopened = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    assert (await reopened.open()).sequence == 1
    calls["close_abandoned"].side_effect = None
    restarted = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=reopened,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )
    assert await restarted.close_operation(failed) is failed
    assert reopened.tail.sequence == 1
    calls["update_tail"].assert_awaited_once()
    assert calls["close_abandoned"].await_count == 2


@pytest.mark.anyio
async def test_restart_no_effect_audit_failure_latches_and_preserves_reservation(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, filesystem, operations, _audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=ProbeFileObservation(ProbeTargetState.ABSENT),
    )
    failed = replace(
        _operation(
            state=OperationState.FAILED,
            knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
        ),
        state_version=5,
        started_at=None,
        error=OperationError("reconciliation_unavailable", "Restart fixture."),
    )
    journal = FileAuditJournal(
        directory=tmp_path / "audit",
        identity=audit_identity(),
        schema=audit_schema(repo_root),
    )
    await journal.open()
    monkeypatch.setattr(journal, "append", AsyncMock(side_effect=OSError("audit unavailable")))
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=journal,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )

    with pytest.raises(ProbeWorkspaceError, match="could not be persisted"):
        await reconciler.close_operation(failed)

    calls["latch_audit"].assert_awaited_once_with("probe_restart_audit_unavailable")
    calls["close_abandoned"].assert_not_awaited()


@pytest.mark.anyio
async def test_restart_reconciliation_scans_interrupted_terminal_probe_closure() -> None:
    absent = ProbeFileObservation(ProbeTargetState.ABSENT)
    repository, filesystem, operations, audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=absent,
    )
    failed = _operation(
        state=OperationState.FAILED,
        knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
    )
    calls["list_closure"].return_value = (_probe(ProbeOperationKind.WRITE),)
    calls["get_operation"].return_value = failed
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=audit,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )

    assert await reconciler.reconcile_terminal_closures() == (failed,)
    calls["list_closure"].assert_awaited_once_with(
        limit=100,
        after_created_at=None,
        after_operation_id=None,
    )
    calls["close_abandoned"].assert_awaited_once_with("op-fixture")


@pytest.mark.anyio
async def test_terminal_probe_closure_scan_precedes_global_gate_open() -> None:
    failed = _operation(
        state=OperationState.FAILED,
        knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
    )
    gate = ConsequentialBoundaryGate()

    async def terminal_closures() -> tuple[OperationSnapshot, ...]:
        assert gate.state is GateState.CLOSED
        return (failed,)

    specialized = cast(
        SpecializedOperationReconciler,
        SimpleNamespace(
            reconcile=AsyncMock(),
            reconcile_terminal_closures=AsyncMock(side_effect=terminal_closures),
        ),
    )
    store = cast(
        ReconciliationStore,
        SimpleNamespace(
            list_reconcilable=AsyncMock(return_value=()),
            audit_failure_state=AsyncMock(return_value=(False, 0, 0)),
        ),
    )
    obligations = cast(
        AuditObligationStore,
        SimpleNamespace(scan=AsyncMock(return_value=())),
    )

    result = await OperationReconciler(
        store=store,
        obligations=obligations,
        gate=gate,
        specialized_reconciler=specialized,
    ).reconcile_startup()

    assert result == (failed,)
    assert gate.state is GateState.OPEN


@pytest.mark.anyio
async def test_reconciler_rejects_open_audit_bad_reference_and_ambiguous_target() -> None:
    exact = ProbeFileObservation(
        ProbeTargetState.EXACT,
        file_identity_digest=IDENTITY,
        content_sha256=CONTENT_SHA256,
        byte_count=len(CONTENT),
    )
    repository, filesystem, operations, audit, obligations, calls = _dependencies(
        kind=ProbeOperationKind.WRITE,
        artifact=_artifact(state=ProbeArtifactState.RESERVED, identity=None),
        observation=exact,
    )
    reconciler = ProbeWorkspaceReconciler(
        operations=operations,
        repository=repository,
        filesystem=filesystem,
        audit=audit,
        obligations=obligations,
        closure_health=calls["closure_health"],
    )
    running = _operation(
        state=OperationState.RUNNING,
        knowledge=EffectKnowledge.KNOWN_EFFECT,
        reference=WRITE_REFERENCE,
    )
    calls["scan"].return_value = (AuditObligation("1.1", "obl-fixture", "op-fixture", 4),)
    with pytest.raises(ProbeWorkspaceError, match="obligation"):
        await reconciler.close_operation(running)

    calls["scan"].return_value = ()
    calls["closure_health"].return_value = False
    with pytest.raises(ProbeWorkspaceError, match="audit recovery health"):
        await reconciler.close_operation(running)

    calls["closure_health"].return_value = True
    calls["state_evidence"].return_value = None
    with pytest.raises(ProbeWorkspaceError, match="operation audit evidence"):
        await reconciler.close_operation(running)

    calls["state_evidence"].return_value = "e" * 64
    bad = _operation(
        state=OperationState.RUNNING,
        knowledge=EffectKnowledge.KNOWN_EFFECT,
        reference="probe-write:v1:artifact-other:1:" + IDENTITY,
    )
    with pytest.raises(ProbeEffectReferenceError, match="generation"):
        await reconciler.close_operation(bad)

    failed_cleanup = _operation(
        state=OperationState.FAILED,
        knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
    )
    calls["get_probe"].return_value = _probe(ProbeOperationKind.CLEANUP)
    calls["get_path"].return_value = _path(_artifact(state=ProbeArtifactState.CREATED))
    calls["observe"].return_value = ProbeFileObservation(ProbeTargetState.MISMATCH)
    with pytest.raises(ProbeWorkspaceError, match="ambiguous"):
        await reconciler.close_operation(failed_cleanup)


def test_effect_reference_parser_rejects_noncanonical_identity_and_digest_drift() -> None:
    assert parse_probe_effect_reference(CLEANUP_REFERENCE).operation is ProbeOperationKind.CLEANUP
    with pytest.raises(ProbeEffectReferenceError, match="shape"):
        parse_probe_effect_reference("probe-write:v1:too-short")
    with pytest.raises(ProbeEffectReferenceError, match="canonical"):
        parse_probe_effect_reference("probe-write:v1:artifact:1:" + "G" * 64)
