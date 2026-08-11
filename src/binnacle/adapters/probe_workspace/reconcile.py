"""Receipt-bound Phase 5 effect dispatch and restart-safe ledger closure."""

from __future__ import annotations

import hashlib
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from binnacle.domain.audit import AuditEventDraft, AuditTail
from binnacle.domain.idempotency import owner_digest
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationError,
    OperationSnapshot,
    OperationState,
    TransitionRequest,
)
from binnacle.domain.probe_workspace import (
    ProbeArtifact,
    ProbeArtifactState,
    ProbeOperationKind,
    ProbeTargetState,
    ProbeWorkspaceError,
)
from binnacle.ports.audit import AuditJournal, AuditObligationStore
from binnacle.ports.effect import (
    BoundaryCrossing,
    EffectBoundary,
    EffectRequest,
    EffectStartReceipt,
)
from binnacle.ports.operation_store import OperationStore
from binnacle.ports.probe_workspace import (
    ProbeWorkspaceFilesystem,
    ProbeWorkspaceRepository,
)

from .linux import ProbeEffectNotStarted


class ProbeEffectReferenceError(ProbeWorkspaceError):
    """A retained effect reference does not bind the exact probe generation."""


class ProbeClosureHealth(Protocol):
    async def __call__(self) -> bool: ...


class ProbeReconciliationStore(OperationStore, Protocol):
    async def update_audit_tail_cache(self, tail: AuditTail) -> None: ...

    async def latch_audit_failure(self, reason_code: str) -> int: ...


@dataclass(frozen=True, slots=True)
class ProbeEffectReference:
    operation: ProbeOperationKind
    artifact_id: str
    path_generation: int
    file_identity_digest: str


def parse_probe_effect_reference(value: str) -> ProbeEffectReference:
    """Parse only the stable opaque references emitted by the Linux adapter."""

    parts = value.split(":")
    if len(parts) != 5 or parts[1] != "v1":
        raise ProbeEffectReferenceError("probe effect reference has an invalid shape")
    operation_by_prefix = {
        "probe-write": ProbeOperationKind.WRITE,
        "probe-cleanup": ProbeOperationKind.CLEANUP,
    }
    try:
        operation = operation_by_prefix[parts[0]]
        generation = int(parts[3])
    except (KeyError, ValueError) as exc:
        raise ProbeEffectReferenceError("probe effect reference is invalid") from exc
    if generation < 1:
        raise ProbeEffectReferenceError("probe effect generation is invalid")
    artifact_id = parts[2]
    identity = parts[4]
    if (
        not artifact_id
        or len(artifact_id) > 160
        or len(identity) != 64
        or any(character not in "0123456789abcdef" for character in identity)
    ):
        raise ProbeEffectReferenceError("probe effect reference is not canonical")
    return ProbeEffectReference(operation, artifact_id, generation, identity)


def effect_reference_digest(value: str) -> str:
    return hashlib.sha256(b"binnacle.effect-reference.v1\0" + value.encode()).hexdigest()


class ProbeWorkspaceEffectBoundary(EffectBoundary):
    """Dispatch the only two finite descriptor-relative Phase 5 effects."""

    def __init__(
        self,
        *,
        repository: ProbeWorkspaceRepository,
        filesystem: ProbeWorkspaceFilesystem,
    ) -> None:
        self._repository = repository
        self._filesystem = filesystem

    async def start(self, request: EffectRequest) -> EffectStartReceipt:
        probe = await self._repository.get_probe_operation(request.operation_id)
        if probe is None or request.effect_type != f"probe_workspace_{probe.probe_operation.value}":
            return self._known_no_effect("probe_effect_request_mismatch")
        snapshot = await self._repository.get_path_snapshot(probe.relative_path)
        artifact = snapshot.active_artifact
        if artifact is None or artifact.artifact_id != probe.artifact_id:
            return self._known_no_effect("probe_active_artifact_mismatch")
        try:
            if probe.probe_operation is ProbeOperationKind.WRITE:
                content = request.protected_arguments.get("content")
                if (
                    not isinstance(content, bytes)
                    or probe.expected_byte_count != len(content)
                    or hashlib.sha256(content).hexdigest() != probe.expected_content_sha256
                ):
                    return self._known_no_effect("probe_write_content_mismatch")
                reference = await self._filesystem.create(
                    operation_id=request.operation_id,
                    artifact_id=artifact.artifact_id,
                    path_generation=artifact.path_generation,
                    relative_path=probe.relative_path,
                    content=content,
                    expected_content_sha256=probe.expected_content_sha256,
                )
            else:
                if request.protected_arguments:
                    return self._known_no_effect("probe_cleanup_arguments_invalid")
                if artifact.file_identity_digest is None:
                    return self._known_no_effect("probe_cleanup_identity_unavailable")
                cleanup_reference = await self._filesystem.remove(
                    operation_id=request.operation_id,
                    artifact_id=artifact.artifact_id,
                    path_generation=artifact.path_generation,
                    relative_path=probe.relative_path,
                    expected_content_sha256=probe.expected_content_sha256,
                    expected_file_identity_digest=artifact.file_identity_digest,
                )
                if cleanup_reference is None:
                    return self._known_no_effect("probe_cleanup_absent_after_start")
                reference = cleanup_reference
        except ProbeEffectNotStarted as exc:
            return self._known_no_effect(str(exc))
        return EffectStartReceipt(
            crossing=BoundaryCrossing.CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_EFFECT,
            reference=reference,
            reason_code=f"probe_{probe.probe_operation.value}_effect_recorded",
        )

    @staticmethod
    def _known_no_effect(reason_code: str) -> EffectStartReceipt:
        return EffectStartReceipt(
            crossing=BoundaryCrossing.DEFINITELY_NOT_CROSSED,
            effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
            terminal_state=OperationState.FAILED,
            reason_code=reason_code,
        )


class ProbeWorkspaceReconciler:
    """Close Phase 5 state only from retained effect truth and exact observations."""

    def __init__(
        self,
        *,
        operations: ProbeReconciliationStore,
        repository: ProbeWorkspaceRepository,
        filesystem: ProbeWorkspaceFilesystem,
        audit: AuditJournal,
        obligations: AuditObligationStore,
        closure_health: ProbeClosureHealth,
    ) -> None:
        self._operations = operations
        self._repository = repository
        self._filesystem = filesystem
        self._audit = audit
        self._obligations = obligations
        self._closure_health = closure_health

    async def close_operation(self, operation: OperationSnapshot) -> OperationSnapshot:
        probe = await self._repository.get_probe_operation(operation.operation_id)
        if probe is None:
            return operation
        if operation.state is OperationState.UNCERTAIN:
            if probe.probe_operation is ProbeOperationKind.WRITE:
                await self._repository.mark_write_uncertain(operation.operation_id)
            return operation
        if operation.state is OperationState.RUNNING:
            if operation.effect_knowledge is EffectKnowledge.KNOWN_EFFECT:
                await self._require_audit_closed(operation)
                reference, _artifact = await self._require_exact_reference(operation)
                observation = await self._filesystem.observe(probe.relative_path)
                if probe.probe_operation is ProbeOperationKind.WRITE:
                    if (
                        observation.state is not ProbeTargetState.EXACT
                        or observation.content_sha256 != probe.expected_content_sha256
                        or observation.byte_count != probe.expected_byte_count
                        or observation.file_identity_digest != reference.file_identity_digest
                    ):
                        raise ProbeWorkspaceError("created probe file verification failed")
                    return await self._repository.close_write_created(
                        operation.operation_id,
                        file_identity_digest=reference.file_identity_digest,
                    )
                if observation.state is not ProbeTargetState.ABSENT:
                    raise ProbeWorkspaceError("cleanup effect did not establish exact absence")
                closed = await self._repository.close_cleanup_removed(
                    operation.operation_id,
                    removed_by_operation=True,
                )
                if closed is None:
                    raise ProbeWorkspaceError("cleanup effect closure did not terminalize")
                return closed
            if operation.effect_knowledge is EffectKnowledge.NONE:
                uncertain = await self._operations.transition(
                    operation.operation_id,
                    TransitionRequest(
                        expected_state_version=operation.state_version,
                        to_state=OperationState.UNCERTAIN,
                        effect_knowledge=EffectKnowledge.UNCERTAIN,
                        reason_code="restart_missing_effect_receipt",
                        error=OperationError(
                            "operation_uncertain",
                            "Probe dispatch outcome is unavailable; reconcile before retry.",
                            "reconcile",
                        ),
                    ),
                )
                if probe.probe_operation is ProbeOperationKind.WRITE:
                    await self._repository.mark_write_uncertain(operation.operation_id)
                return uncertain
        if (
            operation.state is OperationState.FAILED
            and operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
        ):
            if self._is_restart_before_dispatch(operation):
                await self._ensure_restart_no_effect_audit(operation)
            snapshot = await self._repository.get_path_snapshot(probe.relative_path)
            terminal = next(
                (
                    item
                    for item in snapshot.terminal_artifacts
                    if item.artifact_id == probe.artifact_id
                ),
                None,
            )
            closure_time = operation.terminal_at
            if (
                closure_time is not None
                and terminal is not None
                and terminal.removed_at is not None
                and terminal.removed_at >= closure_time
                and (
                    (
                        probe.probe_operation is ProbeOperationKind.WRITE
                        and terminal.state is ProbeArtifactState.ABANDONED
                    )
                    or (
                        probe.probe_operation is ProbeOperationKind.CLEANUP
                        and terminal.state is ProbeArtifactState.REMOVED
                        and terminal.removed_by_cleanup_operation_id is None
                    )
                )
            ):
                return operation
            active_artifact = snapshot.active_artifact
            if (
                closure_time is not None
                and probe.probe_operation is ProbeOperationKind.CLEANUP
                and active_artifact is not None
                and active_artifact.artifact_id == probe.artifact_id
                and active_artifact.state is ProbeArtifactState.CREATED
                and active_artifact.active_cleanup_operation_id is None
                and active_artifact.updated_at >= closure_time
            ):
                return operation
            await self._require_audit_closed(operation)
            observation = await self._filesystem.observe(probe.relative_path)
            if probe.probe_operation is ProbeOperationKind.WRITE:
                if observation.state is not ProbeTargetState.ABSENT:
                    raise ProbeWorkspaceError("no-effect write target is not absent")
                await self._repository.close_write_abandoned(operation.operation_id)
                return operation
            if observation.state is ProbeTargetState.ABSENT:
                await self._repository.close_cleanup_removed(
                    operation.operation_id,
                    removed_by_operation=False,
                )
                return operation
            if not self._observation_matches_artifact(observation, active_artifact):
                raise ProbeWorkspaceError("no-effect cleanup target identity is ambiguous")
            await self._repository.clear_cleanup_claim(operation.operation_id)
        return operation

    async def reconcile(self, operation: OperationSnapshot) -> OperationSnapshot | None:
        """Handle admitted probe operations before the generic restart reconciler."""

        probe = await self._repository.get_probe_operation(operation.operation_id)
        if probe is None:
            return None
        if operation.state is OperationState.AUTHORISED:
            operation = await self._operations.transition(
                operation.operation_id,
                TransitionRequest(
                    expected_state_version=operation.state_version,
                    to_state=OperationState.FAILED,
                    effect_knowledge=EffectKnowledge.KNOWN_NO_EFFECT,
                    reason_code="restart_before_dispatch",
                    error=OperationError(
                        "reconciliation_unavailable",
                        "Probe operation did not reach the durable dispatch marker.",
                    ),
                ),
            )
        return await self.close_operation(operation)

    async def reconcile_terminal_closures(self) -> tuple[OperationSnapshot, ...]:
        """Revisit terminal probe work whose separate artifact closure may have crashed."""

        reconciled: list[OperationSnapshot] = []
        after_created_at: datetime | None = None
        after_operation_id: str | None = None
        while True:
            page = await self._repository.list_probe_operations_for_closure(
                limit=100,
                after_created_at=after_created_at,
                after_operation_id=after_operation_id,
            )
            for probe in page:
                operation = await self._operations.get_operation(probe.operation_id)
                if operation is None:
                    raise ProbeWorkspaceError("probe operation lifecycle is unavailable")
                if (
                    operation.state is OperationState.FAILED
                    and operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
                ):
                    reconciled.append(await self.close_operation(operation))
            if len(page) < 100:
                break
            last = page[-1]
            after_created_at = last.created_at
            after_operation_id = last.operation_id
        return tuple(reconciled)

    async def _require_audit_closed(self, operation: OperationSnapshot) -> None:
        await self._require_audit_runtime_ready(operation)
        evidence = await self._audit.find_operation_state_evidence(
            operation_id=operation.operation_id,
            state_version=operation.state_version,
            state=operation.state.value,
            effect_knowledge=operation.effect_knowledge.value,
        )
        if evidence is None:
            raise ProbeWorkspaceError("probe operation audit evidence is unavailable")

    async def _require_audit_runtime_ready(self, operation: OperationSnapshot) -> None:
        if any(
            item.operation_id == operation.operation_id for item in await self._obligations.scan()
        ):
            raise ProbeWorkspaceError("probe audit obligation remains open")
        if not await self._closure_health():
            raise ProbeWorkspaceError("probe audit recovery health is unavailable")

    async def _ensure_restart_no_effect_audit(self, operation: OperationSnapshot) -> None:
        """Durably and idempotently audit AUTHORISED restart terminalization."""

        await self._require_audit_runtime_ready(operation)
        evidence = await self._audit.find_operation_state_evidence(
            operation_id=operation.operation_id,
            state_version=operation.state_version,
            state=operation.state.value,
            effect_knowledge=operation.effect_knowledge.value,
        )
        if evidence is not None:
            return
        draft = AuditEventDraft(
            event_id=f"event_{secrets.token_hex(16)}",
            recorded_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            severity="notice",
            source="binnacle_system",
            controller_id_digest=owner_digest(operation.owner),
            operation_id=operation.operation_id,
            payload={
                "kind": "operation.state_changed",
                "old_state": OperationState.AUTHORISED.value,
                "new_state": operation.state.value,
                "state_version": operation.state_version,
                "effect_knowledge": operation.effect_knowledge.value,
                "result_digest": None,
                "reason_code": "restart_before_dispatch",
            },
        )
        try:
            result = await self._audit.append(draft)
            await self._operations.update_audit_tail_cache(
                AuditTail(result.sequence, result.event_hash)
            )
        except Exception as exc:
            with suppress(Exception):
                await self._operations.latch_audit_failure("probe_restart_audit_unavailable")
            with suppress(Exception):
                await self._audit.append_emergency(
                    reason_code="probe_restart_audit_unavailable",
                    operation_id=operation.operation_id,
                    source_event_id=draft.event_id,
                )
            raise ProbeWorkspaceError(
                "probe restart audit evidence could not be persisted"
            ) from exc

    @staticmethod
    def _is_restart_before_dispatch(operation: OperationSnapshot) -> bool:
        return (
            operation.started_at is None
            and operation.error is not None
            and operation.error.code == "reconciliation_unavailable"
        )

    async def _require_exact_reference(
        self, operation: OperationSnapshot
    ) -> tuple[ProbeEffectReference, ProbeArtifact]:
        if operation.effect_reference is None or operation.effect_reference_digest is None:
            raise ProbeEffectReferenceError("probe effect reference is unavailable")
        if effect_reference_digest(operation.effect_reference) != operation.effect_reference_digest:
            raise ProbeEffectReferenceError("probe effect reference digest mismatch")
        reference = parse_probe_effect_reference(operation.effect_reference)
        probe = await self._repository.get_probe_operation(operation.operation_id)
        if probe is None or reference.operation is not probe.probe_operation:
            raise ProbeEffectReferenceError("probe effect reference operation mismatch")
        snapshot = await self._repository.get_path_snapshot(probe.relative_path)
        artifact = snapshot.active_artifact
        if (
            artifact is None
            or artifact.artifact_id != probe.artifact_id
            or reference.artifact_id != artifact.artifact_id
            or reference.path_generation != artifact.path_generation
            or (
                probe.probe_operation is ProbeOperationKind.CLEANUP
                and reference.file_identity_digest != artifact.file_identity_digest
            )
        ):
            raise ProbeEffectReferenceError("probe effect reference generation mismatch")
        return reference, artifact

    @staticmethod
    def _observation_matches_artifact(
        observation: object,
        artifact: ProbeArtifact | None,
    ) -> bool:
        from binnacle.domain.probe_workspace import ProbeFileObservation

        return (
            isinstance(observation, ProbeFileObservation)
            and artifact is not None
            and observation.state is ProbeTargetState.EXACT
            and observation.content_sha256 == artifact.content_sha256
            and observation.byte_count == artifact.byte_count
            and observation.file_identity_digest == artifact.file_identity_digest
        )


__all__ = [
    "ProbeClosureHealth",
    "ProbeEffectReference",
    "ProbeEffectReferenceError",
    "ProbeWorkspaceEffectBoundary",
    "ProbeWorkspaceReconciler",
    "effect_reference_digest",
    "parse_probe_effect_reference",
]
