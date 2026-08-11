"""Phase 5 preparation, dual-key admission, and final-boundary orchestration."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from binnacle.application.operations import (
    CoordinatedOperationRequest,
    OperationCoordinator,
)
from binnacle.application.trusted_time import TrustedTimeGuard
from binnacle.contracts import ContractRegistry
from binnacle.domain.audit import AuditEventDraft
from binnacle.domain.idempotency import (
    IdempotencyKeyMode,
    IdempotencyOutcome,
    owner_digest,
    validate_and_digest_key,
)
from binnacle.domain.mcp import (
    BinnacleError,
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeWorkspaceCleanupData,
    ProbeWorkspacePreparationData,
    ProbeWorkspaceWriteData,
    SuccessEnvelope,
    ToolIdentity,
    operation_view,
)
from binnacle.domain.mcp import (
    ProbeWorkspaceCleanupRequest as McpProbeWorkspaceCleanupRequest,
)
from binnacle.domain.mcp import (
    ProbeWorkspacePrepareRequest as McpProbeWorkspacePrepareRequest,
)
from binnacle.domain.mcp import (
    ProbeWorkspaceWriteRequest as McpProbeWorkspaceWriteRequest,
)
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationIntent,
    OperationOwner,
    OperationSnapshot,
    OperationState,
)
from binnacle.domain.probe_workspace import (
    ProbeArtifactState,
    ProbeOperationKind,
    ProbeOperationRecord,
    ProbePathSnapshot,
    ProbePreparedState,
    ProbeRootIdentity,
    ProbeTargetState,
    ProbeWorkspaceError,
    maximum_effect_sha256,
    normalize_probe_path,
    operation_fingerprint_sha256,
    prepared_input_sha256,
    prepared_state_sha256,
    target_identity_sha256,
    validate_path_snapshot,
    validate_probe_identifier,
    validate_sha256,
)
from binnacle.ports.boundary import (
    BoundaryDecision,
    BoundaryDisposition,
    OperationBoundaryCheck,
    PreparedStateCheck,
)
from binnacle.ports.operation_store import (
    CreateOrFindRequest,
    OperationStore,
    PreparedExecutionAdmission,
    PreparedNonceRegistration,
)
from binnacle.ports.probe_workspace import (
    ProbeAuthorisationRequest,
    ProbeWorkspaceFilesystem,
    ProbeWorkspaceRepository,
)

ProbeSuccessT = TypeVar("ProbeSuccessT")


@dataclass(frozen=True, slots=True)
class ProbePrepareRequest:
    operation: ProbeOperationKind
    relative_path: str
    content_sha256: str
    byte_count: int | None = None
    artifact_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProbePreparation:
    prepared_operation_id: str
    execution_nonce: str
    expires_at: datetime
    operation: ProbeOperationKind
    relative_path: str
    normalized_input_sha256: str
    maximum_effect_sha256: str


@dataclass(frozen=True, slots=True)
class ProbeWriteRequest:
    prepared_operation_id: str
    execution_nonce: str
    idempotency_key: str
    relative_path: str
    content: bytes
    overwrite: bool


@dataclass(frozen=True, slots=True)
class ProbeCleanupRequest:
    prepared_operation_id: str
    execution_nonce: str
    idempotency_key: str
    relative_path: str
    artifact_id: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ProbeExecution:
    outcome: IdempotencyOutcome
    operation: OperationSnapshot | None
    probe_operation: ProbeOperationRecord | None
    path: ProbePathSnapshot | None


class ProbeOperationClosure(Protocol):
    async def close_operation(self, operation: OperationSnapshot) -> OperationSnapshot: ...


class ProbeOperationAuthoriser:
    def __init__(
        self,
        repository: ProbeWorkspaceRepository,
        state_verifier: ProbePreparedStateVerifier,
    ) -> None:
        self._repository = repository
        self._state_verifier = state_verifier

    async def authorise(
        self,
        *,
        operation: OperationSnapshot,
        decision: object,
        request: CoordinatedOperationRequest,
    ) -> OperationSnapshot:
        from binnacle.domain.policy import PolicyDecision

        if not isinstance(decision, PolicyDecision):
            raise TypeError("probe authorisation requires a policy decision")
        if request.prepared_state_facts is None:
            raise ProbeWorkspaceError("prepared state facts are unavailable at authorisation")
        facts = _parse_facts(request.prepared_state_facts)
        prepared_state_binding_sha256 = await self._repository.get_prepared_state_binding_sha256(
            request.admission.prepared_operation_id or ""
        )
        if prepared_state_binding_sha256 is None:
            raise ProbeWorkspaceError("prepared binding is unavailable at authorisation")
        prepared_state = await self._state_verifier.current_state(
            PreparedStateCheck(
                operation_id=operation.operation_id,
                prepared_operation_id=request.admission.prepared_operation_id or "",
                protected_facts=request.prepared_state_facts,
            )
        )
        return await self._repository.authorise(
            ProbeAuthorisationRequest(
                operation=operation,
                decision=decision,
                probe_operation=facts.operation,
                relative_path=facts.relative_path,
                expected_content_sha256=facts.content_sha256,
                expected_byte_count=facts.byte_count,
                artifact_id=facts.artifact_id,
                prepared_state_binding_sha256=prepared_state_binding_sha256,
                prepared_state=prepared_state,
            )
        )


class ProbePreparedStateVerifier:
    """Recompute and phase-stably canonicalize exact probe preparation state."""

    def __init__(
        self,
        *,
        repository: ProbeWorkspaceRepository,
        filesystem: ProbeWorkspaceFilesystem,
    ) -> None:
        self._repository = repository
        self._filesystem = filesystem

    async def current_state_digest(self, request: PreparedStateCheck) -> str:
        return prepared_state_sha256(await self.current_state(request))

    async def current_state(self, request: PreparedStateCheck) -> ProbePreparedState:
        """Return the one exact prepared state that still matches durable authority."""

        facts = _parse_facts(request.protected_facts)
        expected = await self._repository.get_prepared_state_binding_sha256(
            request.prepared_operation_id
        )
        if expected is None:
            raise ProbeWorkspaceError("prepared binding is unavailable")
        candidates = await self._current_states(
            facts,
            operation_id=request.operation_id,
        )
        matching = [state for state in candidates if prepared_state_sha256(state) == expected]
        if len(matching) != 1:
            raise ProbeWorkspaceError("current probe state does not match preparation")
        return matching[0]

    async def boundary_decision(
        self,
        *,
        operation_id: str,
        prepared_operation_id: str,
        protected_facts: Mapping[str, str],
    ) -> BoundaryDecision:
        facts = _parse_facts(protected_facts)
        boundary = await self._repository.get_boundary_snapshot(
            operation_id=operation_id,
            prepared_operation_id=prepared_operation_id,
            relative_path=facts.relative_path,
        )
        root = await self._filesystem.root_identity()
        candidates = await self._states_for_snapshot(
            facts,
            root=root,
            snapshot=boundary.path,
            operation_id=operation_id,
            probe_operation=boundary.probe_operation,
        )
        matching = [
            state
            for state in candidates
            if prepared_state_sha256(state) == boundary.prepared_state_binding_sha256
        ]
        if len(matching) != 1:
            raise ProbeWorkspaceError("current probe state does not match preparation")
        observation = await self._filesystem.observe(facts.relative_path)
        if facts.operation is ProbeOperationKind.WRITE:
            if observation.state is ProbeTargetState.ABSENT:
                return BoundaryDecision(BoundaryDisposition.PROCEED, "probe_write_exact")
            return BoundaryDecision(BoundaryDisposition.DENY, "probe_target_not_absent")
        if observation.state is ProbeTargetState.ABSENT:
            return BoundaryDecision(
                BoundaryDisposition.KNOWN_NO_EFFECT,
                "cleanup_already_missing_before_start",
            )
        if observation.state is ProbeTargetState.EXACT:
            return BoundaryDecision(BoundaryDisposition.PROCEED, "probe_cleanup_exact")
        return BoundaryDecision(BoundaryDisposition.DENY, "probe_cleanup_identity_mismatch")

    async def preparation_state(
        self, request: ProbePrepareRequest, owner: OperationOwner
    ) -> tuple[ProbePreparedState, ProbeRootIdentity]:
        facts = _facts_from_prepare(request, owner)
        root = await self._filesystem.root_identity()
        snapshot = await self._repository.ensure_path_anchor(facts.relative_path)
        candidates = await self._states_for_snapshot(
            facts,
            root=root,
            snapshot=snapshot,
            operation_id=None,
        )
        if len(candidates) != 1:
            raise ProbeWorkspaceError("preparation state is ambiguous")
        return candidates[0], root

    async def _current_states(
        self,
        facts: _ProbeFacts,
        *,
        operation_id: str | None,
    ) -> tuple[ProbePreparedState, ...]:
        root = await self._filesystem.root_identity()
        snapshot = await self._repository.get_path_snapshot(facts.relative_path)
        probe_operation = (
            None
            if operation_id is None
            else await self._repository.get_probe_operation(operation_id)
        )
        states = await self._states_for_snapshot(
            facts,
            root=root,
            snapshot=snapshot,
            operation_id=operation_id,
            probe_operation=probe_operation,
        )
        return states

    async def _states_for_snapshot(
        self,
        facts: _ProbeFacts,
        *,
        root: ProbeRootIdentity,
        snapshot: ProbePathSnapshot,
        operation_id: str | None,
        probe_operation: ProbeOperationRecord | None = None,
    ) -> tuple[ProbePreparedState, ...]:
        validate_path_snapshot(snapshot)
        ledger = snapshot.ledger
        observation = await self._filesystem.observe(facts.relative_path)
        if facts.operation is ProbeOperationKind.WRITE:
            if facts.artifact_id is not None or facts.byte_count is None:
                raise ProbeWorkspaceError("write preparation facts are invalid")
            active = snapshot.active_artifact
            if active is None:
                if operation_id is not None and probe_operation is not None:
                    raise ProbeWorkspaceError("admitted write lost its reservation")
                canonical_version = ledger.ledger_version
                canonical_high_water = ledger.generation_high_water
            else:
                if (
                    operation_id is None
                    or active.create_operation_id != operation_id
                    or active.state
                    not in {ProbeArtifactState.RESERVED, ProbeArtifactState.UNCERTAIN}
                    or active.content_sha256 != facts.content_sha256
                    or active.byte_count != facts.byte_count
                    or active.owner_controller_id != facts.owner_controller_id
                    or active.owner_controller_epoch != facts.owner_controller_epoch
                ):
                    raise ProbeWorkspaceError("write reservation is not exact self")
                canonical_version = ledger.ledger_version - 1
                canonical_high_water = ledger.generation_high_water - 1
            if observation.state is not ProbeTargetState.ABSENT:
                raise ProbeWorkspaceError("write target is not securely absent")
            return (
                ProbePreparedState(
                    operation=facts.operation,
                    relative_path=facts.relative_path,
                    content_sha256=facts.content_sha256,
                    byte_count=facts.byte_count,
                    artifact_id=None,
                    owner_controller_id=facts.owner_controller_id,
                    owner_controller_epoch=facts.owner_controller_epoch,
                    root_identity_sha256=root.digest_sha256,
                    ledger_version=canonical_version,
                    generation_high_water=canonical_high_water,
                    terminal_history_count=ledger.terminal_history_count,
                    terminal_history_sha256=ledger.terminal_history_sha256,
                    active_artifact_id=None,
                    active_generation=None,
                    active_create_operation_id=None,
                    write_reservation_transition=(
                        "absent_generation_N_then_exact_self_reserved_generation_N_plus_1"
                    ),
                    cleanup_target_transition=None,
                    cleanup_claim_transition=None,
                    expected_file_identity_digest=None,
                ),
            )

        active = snapshot.active_artifact
        if (
            facts.artifact_id is None
            or facts.byte_count is not None
            or active is None
            or active.artifact_id != facts.artifact_id
            or active.state is not ProbeArtifactState.CREATED
            or active.content_sha256 != facts.content_sha256
            or active.owner_controller_id != facts.owner_controller_id
            or active.owner_controller_epoch != facts.owner_controller_epoch
            or active.file_identity_digest is None
        ):
            raise ProbeWorkspaceError("cleanup target is not exact active created state")
        if active.active_cleanup_operation_id not in {None, operation_id}:
            raise ProbeWorkspaceError("cleanup artifact is claimed by another operation")
        if (
            operation_id is not None
            and probe_operation is not None
            and (
                probe_operation.probe_operation is not ProbeOperationKind.CLEANUP
                or probe_operation.artifact_id != active.artifact_id
            )
        ):
            raise ProbeWorkspaceError("cleanup operation provenance is inconsistent")

        def cleanup_state(target_transition: str) -> ProbePreparedState:
            return ProbePreparedState(
                operation=facts.operation,
                relative_path=facts.relative_path,
                content_sha256=facts.content_sha256,
                byte_count=None,
                artifact_id=facts.artifact_id,
                owner_controller_id=facts.owner_controller_id,
                owner_controller_epoch=facts.owner_controller_epoch,
                root_identity_sha256=root.digest_sha256,
                ledger_version=ledger.ledger_version,
                generation_high_water=ledger.generation_high_water,
                terminal_history_count=ledger.terminal_history_count,
                terminal_history_sha256=ledger.terminal_history_sha256,
                active_artifact_id=ledger.active_artifact_id,
                active_generation=ledger.active_generation,
                active_create_operation_id=ledger.active_create_operation_id,
                write_reservation_transition=None,
                cleanup_target_transition=target_transition,
                cleanup_claim_transition="unclaimed_then_exact_self",
                expected_file_identity_digest=active.file_identity_digest,
            )

        if observation.state is ProbeTargetState.EXACT:
            if (
                observation.content_sha256 != active.content_sha256
                or observation.byte_count != active.byte_count
                or observation.file_identity_digest != active.file_identity_digest
            ):
                raise ProbeWorkspaceError("cleanup file identity/content changed")
            return (cleanup_state("exact_prepared_identity_or_absent_no_start"),)
        if observation.state is ProbeTargetState.ABSENT:
            candidates = [cleanup_state("created_target_observed_absent")]
            if active.active_cleanup_operation_id == operation_id and operation_id is not None:
                candidates.append(cleanup_state("exact_prepared_identity_or_absent_no_start"))
            return tuple(candidates)
        raise ProbeWorkspaceError("cleanup target is not a safe exact file or absence")


class ProbeOperationBoundaryVerifier:
    def __init__(self, verifier: ProbePreparedStateVerifier) -> None:
        self._verifier = verifier

    async def verify(self, request: OperationBoundaryCheck) -> BoundaryDecision:
        predicates = request.predicates
        prepared_operation_id = predicates.get("prepared_operation_id")
        if not isinstance(prepared_operation_id, str):
            return BoundaryDecision(BoundaryDisposition.DENY, "probe_boundary_facts_missing")
        facts = {
            key: value
            for key, value in predicates.items()
            if key in _FACT_KEYS and isinstance(value, str)
        }
        return await self._verifier.boundary_decision(
            operation_id=request.operation_id,
            prepared_operation_id=prepared_operation_id,
            protected_facts=facts,
        )


class ProbeWorkspaceService:
    def __init__(
        self,
        *,
        operation_store: OperationStore,
        repository: ProbeWorkspaceRepository,
        coordinator: OperationCoordinator,
        closure: ProbeOperationClosure,
        state_verifier: ProbePreparedStateVerifier,
        trusted_time: TrustedTimeGuard,
        device_id: str,
        device_epoch: int,
        runtime_build_sha256: str,
        runtime_config_sha256: str,
        root_identity: ProbeRootIdentity,
        preparation_ttl_seconds: int,
        maximum_file_bytes: int,
    ) -> None:
        self._operation_store = operation_store
        self._repository = repository
        self._coordinator = coordinator
        self._closure = closure
        self._state_verifier = state_verifier
        self._trusted_time = trusted_time
        self._device_id = device_id
        self._device_epoch = device_epoch
        self._runtime_build_sha256 = runtime_build_sha256
        self._runtime_config_sha256 = runtime_config_sha256
        self._root_identity = root_identity
        self._preparation_ttl_seconds = preparation_ttl_seconds
        self._maximum_file_bytes = maximum_file_bytes

    async def prepare(
        self,
        request: ProbePrepareRequest,
        *,
        owner: OperationOwner,
    ) -> ProbePreparation:
        normalized = _validated_prepare_request(request)
        if (
            normalized.operation is ProbeOperationKind.WRITE
            and normalized.byte_count is not None
            and normalized.byte_count > self._maximum_file_bytes
        ):
            raise ProbeWorkspaceError("write preparation byte count exceeds configured maximum")
        state, root = await self._state_verifier.preparation_state(normalized, owner)
        if root.digest_sha256 != self._root_identity.digest_sha256:
            raise ProbeWorkspaceError("probe root changed since capability composition")
        prepared_operation_id = f"prepared_{secrets.token_hex(16)}"
        execution_nonce = secrets.token_urlsafe(32).rstrip("=")
        input_digest = prepared_input_sha256(
            operation=normalized.operation,
            relative_path=normalized.relative_path,
            expected_content_sha256=normalized.content_sha256,
            byte_count=normalized.byte_count,
            artifact_id=normalized.artifact_id,
        )
        target_digest = target_identity_sha256(root.digest_sha256, normalized.relative_path)
        maximum_digest = maximum_effect_sha256(
            operation=normalized.operation,
            maximum_bytes=self._maximum_file_bytes,
        )
        fingerprint = operation_fingerprint_sha256(
            operation=normalized.operation,
            prepared_operation_id=prepared_operation_id,
            prepared_input_sha256=input_digest,
            relative_path=normalized.relative_path,
            expected_content_sha256=normalized.content_sha256,
            byte_count=normalized.byte_count,
            artifact_id=normalized.artifact_id,
            target_identity_digest=target_digest,
            maximum_effect_digest=maximum_digest,
        )
        state_digest = prepared_state_sha256(state)
        deadline = await self._trusted_time.issue_deadline(self._preparation_ttl_seconds)
        execute_tool = f"probe_workspace_{normalized.operation.value}"
        await self._operation_store.register_prepared_execution_nonce(
            PreparedNonceRegistration(
                key=validate_and_digest_key(
                    execution_nonce,
                    IdempotencyKeyMode.PREPARED_EXECUTION_NONCE,
                ),
                owner=owner,
                device_id=self._device_id,
                device_epoch=self._device_epoch,
                tool_name=execute_tool,
                contract_version="1.1",
                request_fingerprint_sha256=fingerprint,
                prepared_operation_id=prepared_operation_id,
                prepared_input_sha256=input_digest,
                prepared_expires_at=deadline.expires_at,
                prepared_state_binding_sha256=state_digest,
                registered_boot_id_digest=deadline.registered_boot_id_digest,
                monotonic_deadline_ns=deadline.monotonic_deadline_ns,
                target_identity_sha256=target_digest,
                maximum_effect_sha256=maximum_digest,
            )
        )
        await self._coordinator.record_required_audit(
            AuditEventDraft(
                event_id=f"event_{secrets.token_hex(16)}",
                recorded_at=datetime.now(UTC),
                monotonic_ns=time.monotonic_ns(),
                severity="info",
                source="binnacle_system",
                controller_id_digest=owner_digest(owner),
                prepared_operation_id=prepared_operation_id,
                payload={
                    "kind": "operation.reserved",
                    "decision": "reserved",
                    "rule_id": "phase5-prepared-execution",
                    "reason_code": "probe_preparation_recorded",
                    "normalized_target_digest": target_digest,
                    "resource_digests": [input_digest, state_digest, maximum_digest],
                },
            )
        )
        return ProbePreparation(
            prepared_operation_id=prepared_operation_id,
            execution_nonce=execution_nonce,
            expires_at=deadline.expires_at,
            operation=normalized.operation,
            relative_path=normalized.relative_path,
            normalized_input_sha256=input_digest,
            maximum_effect_sha256=maximum_digest,
        )

    async def write(
        self,
        request: ProbeWriteRequest,
        *,
        owner: OperationOwner,
    ) -> ProbeExecution:
        if request.overwrite:
            raise ProbeWorkspaceError("probe write overwrite must be false")
        relative_path = normalize_probe_path(request.relative_path)
        content_digest = hashlib.sha256(request.content).hexdigest()
        facts = _ProbeFacts(
            operation=ProbeOperationKind.WRITE,
            relative_path=relative_path,
            content_sha256=content_digest,
            byte_count=len(request.content),
            artifact_id=None,
            owner_controller_id=owner.controller_id,
            owner_controller_epoch=owner.controller_epoch,
        )
        return await self._execute(
            prepared_operation_id=request.prepared_operation_id,
            execution_nonce=request.execution_nonce,
            idempotency_key=request.idempotency_key,
            facts=facts,
            owner=owner,
            protected_effect_arguments={"content": request.content},
        )

    async def cleanup(
        self,
        request: ProbeCleanupRequest,
        *,
        owner: OperationOwner,
    ) -> ProbeExecution:
        facts = _ProbeFacts(
            operation=ProbeOperationKind.CLEANUP,
            relative_path=normalize_probe_path(request.relative_path),
            content_sha256=validate_sha256(request.content_sha256, name="content_sha256"),
            byte_count=None,
            artifact_id=validate_probe_identifier(request.artifact_id, name="artifact_id"),
            owner_controller_id=owner.controller_id,
            owner_controller_epoch=owner.controller_epoch,
        )
        return await self._execute(
            prepared_operation_id=request.prepared_operation_id,
            execution_nonce=request.execution_nonce,
            idempotency_key=request.idempotency_key,
            facts=facts,
            owner=owner,
            protected_effect_arguments={},
        )

    async def _execute(
        self,
        *,
        prepared_operation_id: str,
        execution_nonce: str,
        idempotency_key: str,
        facts: _ProbeFacts,
        owner: OperationOwner,
        protected_effect_arguments: Mapping[str, object],
    ) -> ProbeExecution:
        validate_probe_identifier(prepared_operation_id, name="prepared_operation_id")
        if facts.byte_count is not None and not 0 <= facts.byte_count <= self._maximum_file_bytes:
            raise ProbeWorkspaceError("probe write content exceeds configured maximum")
        input_digest = prepared_input_sha256(
            operation=facts.operation,
            relative_path=facts.relative_path,
            expected_content_sha256=facts.content_sha256,
            byte_count=facts.byte_count,
            artifact_id=facts.artifact_id,
        )
        target_digest = target_identity_sha256(
            self._root_identity.digest_sha256, facts.relative_path
        )
        maximum_digest = maximum_effect_sha256(
            operation=facts.operation,
            maximum_bytes=self._maximum_file_bytes,
        )
        fingerprint = operation_fingerprint_sha256(
            operation=facts.operation,
            prepared_operation_id=prepared_operation_id,
            prepared_input_sha256=input_digest,
            relative_path=facts.relative_path,
            expected_content_sha256=facts.content_sha256,
            byte_count=facts.byte_count,
            artifact_id=facts.artifact_id,
            target_identity_digest=target_digest,
            maximum_effect_digest=maximum_digest,
        )
        tool_name = f"probe_workspace_{facts.operation.value}"
        admission = CreateOrFindRequest(
            key=validate_and_digest_key(idempotency_key, IdempotencyKeyMode.CALLER_KEY),
            owner=owner,
            intent=OperationIntent(
                operation_contract=tool_name,
                operation_contract_version="1.1",
                request_fingerprint_sha256=fingerprint,
                device_id=self._device_id,
                device_epoch=self._device_epoch,
                runtime_build_sha256=self._runtime_build_sha256,
                runtime_config_sha256=self._runtime_config_sha256,
                tool_name=tool_name,
                tool_contract_version="1.1",
                target_identity_sha256=target_digest,
                maximum_effect_sha256=maximum_digest,
            ),
            tool_name=tool_name,
            contract_version="1.1",
            prepared_operation_id=prepared_operation_id,
            prepared_input_sha256=input_digest,
            prepared_state_binding_sha256=None,
        )
        protected_facts = _facts_mapping(facts)
        coordinated = CoordinatedOperationRequest(
            admission=admission,
            prepared_execution=PreparedExecutionAdmission(
                caller=admission,
                prepared_key=validate_and_digest_key(
                    execution_nonce,
                    IdempotencyKeyMode.PREPARED_EXECUTION_NONCE,
                ),
            ),
            required_scope_digest=None,
            normalized_target_digest=target_digest,
            boundary_predicates={
                **protected_facts,
                "prepared_operation_id": prepared_operation_id,
            },
            effect_type=tool_name,
            protected_effect_arguments=protected_effect_arguments,
            prepared_state_facts=protected_facts,
        )
        result = await self._coordinator.execute(coordinated)
        operation = result.operation
        if operation is not None:
            operation = await self._closure.close_operation(operation)
        probe = (
            None
            if operation is None
            else await self._repository.get_probe_operation(operation.operation_id)
        )
        path = (
            None if probe is None else await self._repository.get_path_snapshot(probe.relative_path)
        )
        return ProbeExecution(result.outcome, operation, probe, path)


class ProbeWorkspaceControllerResolver(Protocol):
    def __call__(self, context: McpCallContext) -> OperationOwner: ...


class ProbeWorkspaceEntitlement(Protocol):
    def __call__(self, context: McpCallContext) -> bool: ...


class ProbeWorkspaceUseCases:
    """Authenticated MCP projection over the bounded Phase 5 service."""

    def __init__(
        self,
        *,
        service: ProbeWorkspaceService,
        contracts: ContractRegistry,
        controller_resolver: ProbeWorkspaceControllerResolver,
        entitlement: ProbeWorkspaceEntitlement,
        maximum_file_bytes: int,
    ) -> None:
        if contracts.catalogue_phase != "compatibility-write-probe":
            raise ValueError("write use cases require the exact write-probe registry")
        self._service = service
        self._contracts = contracts
        self._controller_resolver = controller_resolver
        self._entitlement = entitlement
        self._maximum_file_bytes = maximum_file_bytes

    async def prepare(
        self,
        request: McpProbeWorkspacePrepareRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeWorkspacePreparationData] | ExecutionErrorEnvelope:
        owner = self._authorised_owner(context, "probe_workspace_prepare")
        if isinstance(owner, ExecutionErrorEnvelope):
            return owner
        try:
            preparation = await self._service.prepare(
                ProbePrepareRequest(
                    operation=request.operation,
                    relative_path=request.relative_path,
                    content_sha256=request.content_sha256,
                    byte_count=request.byte_count,
                    artifact_id=request.artifact_id,
                ),
                owner=owner,
            )
        except (ProbeWorkspaceError, ValueError) as exc:
            return self._error(
                "probe_workspace_prepare",
                context,
                code="probe_preparation_rejected",
                message=str(exc),
            )
        maximum_effect = (
            f"Create one new file of at most {self._maximum_file_bytes} bytes without overwrite."
            if request.operation is ProbeOperationKind.WRITE
            else "Remove only the exact prepared live probe artifact."
        )
        return self._success(
            "probe_workspace_prepare",
            context,
            ProbeWorkspacePreparationData(
                prepared_operation_id=preparation.prepared_operation_id,
                execution_nonce=preparation.execution_nonce,
                expires_at=preparation.expires_at.isoformat().replace("+00:00", "Z"),
                operation=preparation.operation.value,
                relative_path=preparation.relative_path,
                normalized_input_sha256=preparation.normalized_input_sha256,
                maximum_effect=maximum_effect,
            ),
        )

    async def write(
        self,
        request: McpProbeWorkspaceWriteRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeWorkspaceWriteData] | ExecutionErrorEnvelope:
        owner = self._authorised_owner(context, "probe_workspace_write")
        if isinstance(owner, ExecutionErrorEnvelope):
            return owner
        try:
            result = await self._service.write(
                ProbeWriteRequest(
                    prepared_operation_id=request.prepared_operation_id,
                    execution_nonce=request.execution_nonce,
                    idempotency_key=request.idempotency_key,
                    relative_path=request.relative_path,
                    content=request.content,
                    overwrite=request.overwrite,
                ),
                owner=owner,
            )
        except (ProbeWorkspaceError, ValueError) as exc:
            return self._error(
                "probe_workspace_write",
                context,
                code="probe_write_rejected",
                message=str(exc),
            )
        operation = result.operation
        artifact = None if result.path is None else result.path.active_artifact
        if (
            operation is not None
            and operation.state is OperationState.SUCCEEDED
            and artifact is not None
            and artifact.state is ProbeArtifactState.CREATED
        ):
            return self._success(
                "probe_workspace_write",
                context,
                ProbeWorkspaceWriteData(
                    relative_path=artifact.relative_path,
                    byte_count=artifact.byte_count,
                    content_sha256=artifact.content_sha256,
                    artifact_id=artifact.artifact_id,
                    created=True,
                ),
                operation=operation,
            )
        return self._execution_result_error("probe_workspace_write", context, result)

    async def cleanup(
        self,
        request: McpProbeWorkspaceCleanupRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeWorkspaceCleanupData] | ExecutionErrorEnvelope:
        owner = self._authorised_owner(context, "probe_workspace_cleanup")
        if isinstance(owner, ExecutionErrorEnvelope):
            return owner
        try:
            result = await self._service.cleanup(
                ProbeCleanupRequest(
                    prepared_operation_id=request.prepared_operation_id,
                    execution_nonce=request.execution_nonce,
                    idempotency_key=request.idempotency_key,
                    relative_path=request.relative_path,
                    artifact_id=request.artifact_id,
                    content_sha256=request.content_sha256,
                ),
                owner=owner,
            )
        except (ProbeWorkspaceError, ValueError) as exc:
            return self._error(
                "probe_workspace_cleanup",
                context,
                code="probe_cleanup_rejected",
                message=str(exc),
            )
        operation = result.operation
        artifact = None
        if result.path is not None:
            artifact = next(
                (
                    item
                    for item in result.path.terminal_artifacts
                    if item.artifact_id == request.artifact_id
                ),
                None,
            )
        removed = operation is not None and operation.state is OperationState.SUCCEEDED
        already_missing = (
            operation is not None
            and operation.state is OperationState.FAILED
            and operation.effect_knowledge is EffectKnowledge.KNOWN_NO_EFFECT
            and artifact is not None
            and artifact.state is ProbeArtifactState.REMOVED
            and artifact.removed_by_cleanup_operation_id is None
        )
        if artifact is not None and (removed or already_missing):
            return self._success(
                "probe_workspace_cleanup",
                context,
                ProbeWorkspaceCleanupData(
                    relative_path=artifact.relative_path,
                    artifact_id=artifact.artifact_id,
                    content_sha256=artifact.content_sha256,
                    removed=removed,
                    already_missing=already_missing,
                ),
                operation=operation,
            )
        return self._execution_result_error("probe_workspace_cleanup", context, result)

    def _authorised_owner(
        self, context: McpCallContext, tool_name: str
    ) -> OperationOwner | ExecutionErrorEnvelope:
        if context.controller is None:
            return self._error(
                tool_name,
                context,
                code="authentication_required",
                message="An authenticated reviewed controller profile is required.",
            )
        if not self._entitlement(context):
            return self._error(
                tool_name,
                context,
                code="probe_workspace_scope_required",
                message="The selected controller lacks probe-workspace authority.",
            )
        return self._controller_resolver(context)

    def _execution_result_error(
        self,
        tool_name: str,
        context: McpCallContext,
        result: ProbeExecution,
    ) -> ExecutionErrorEnvelope:
        operation = result.operation
        if operation is not None and operation.error is not None:
            return self._error(
                tool_name,
                context,
                code=operation.error.code,
                message=operation.error.summary,
                retry_action=operation.error.retry_action,
                operation=operation,
            )
        return self._error(
            tool_name,
            context,
            code=result.outcome.value,
            message="The retained probe operation cannot safely produce a success result.",
            retry_action=("reconcile" if operation is not None else "none"),
            operation=operation,
        )

    def _success(
        self,
        tool_name: str,
        context: McpCallContext,
        data: ProbeSuccessT,
        *,
        operation: OperationSnapshot | None = None,
    ) -> SuccessEnvelope[ProbeSuccessT]:
        contract = self._contracts.tools[tool_name]
        return SuccessEnvelope(
            schema_version="1.1",
            call_status="succeeded",
            tool=ToolIdentity(tool_name, contract.contract_version),
            request_id=context.request_id,
            data=data,
            operation=None if operation is None else operation_view(operation),
        )

    def _error(
        self,
        tool_name: str,
        context: McpCallContext,
        *,
        code: str,
        message: str,
        retry_action: str = "none",
        operation: OperationSnapshot | None = None,
    ) -> ExecutionErrorEnvelope:
        contract = self._contracts.tools[tool_name]
        return ExecutionErrorEnvelope(
            schema_version="1.1",
            call_status="execution_error",
            tool=ToolIdentity(tool_name, contract.contract_version),
            request_id=context.request_id,
            error=BinnacleError(
                code=code,
                message=message,
                retryable=False,
                retry_action=retry_action,
                operation_id=None if operation is None else operation.operation_id,
            ),
            operation=None if operation is None else operation_view(operation),
        )


@dataclass(frozen=True, slots=True)
class _ProbeFacts:
    operation: ProbeOperationKind
    relative_path: str
    content_sha256: str
    byte_count: int | None
    artifact_id: str | None
    owner_controller_id: str
    owner_controller_epoch: int


_FACT_KEYS = frozenset(
    {
        "operation",
        "relative_path",
        "content_sha256",
        "byte_count",
        "artifact_id",
        "owner_controller_id",
        "owner_controller_epoch",
    }
)


def _facts_from_prepare(request: ProbePrepareRequest, owner: OperationOwner) -> _ProbeFacts:
    return _ProbeFacts(
        operation=request.operation,
        relative_path=request.relative_path,
        content_sha256=request.content_sha256,
        byte_count=request.byte_count,
        artifact_id=request.artifact_id,
        owner_controller_id=owner.controller_id,
        owner_controller_epoch=owner.controller_epoch,
    )


def _facts_mapping(facts: _ProbeFacts) -> dict[str, str]:
    return {
        "operation": facts.operation.value,
        "relative_path": facts.relative_path,
        "content_sha256": facts.content_sha256,
        "byte_count": "" if facts.byte_count is None else str(facts.byte_count),
        "artifact_id": facts.artifact_id or "",
        "owner_controller_id": facts.owner_controller_id,
        "owner_controller_epoch": str(facts.owner_controller_epoch),
    }


def _parse_facts(value: Mapping[str, str] | None) -> _ProbeFacts:
    if value is None or set(value) != _FACT_KEYS:
        raise ProbeWorkspaceError("probe prepared-state facts are incomplete")
    operation = ProbeOperationKind(value["operation"])
    byte_count = None if value["byte_count"] == "" else int(value["byte_count"])
    artifact_id = value["artifact_id"] or None
    return _ProbeFacts(
        operation=operation,
        relative_path=normalize_probe_path(value["relative_path"]),
        content_sha256=validate_sha256(value["content_sha256"], name="content_sha256"),
        byte_count=byte_count,
        artifact_id=(
            None
            if artifact_id is None
            else validate_probe_identifier(artifact_id, name="artifact_id")
        ),
        owner_controller_id=validate_probe_identifier(
            value["owner_controller_id"], name="owner_controller_id"
        ),
        owner_controller_epoch=int(value["owner_controller_epoch"]),
    )


def _validated_prepare_request(request: ProbePrepareRequest) -> ProbePrepareRequest:
    relative_path = normalize_probe_path(request.relative_path)
    digest = validate_sha256(request.content_sha256, name="content_sha256")
    if request.operation is ProbeOperationKind.WRITE:
        if request.byte_count is None or request.artifact_id is not None:
            raise ProbeWorkspaceError("write preparation requires byte count only")
        if not 0 <= request.byte_count <= 65_536:
            raise ProbeWorkspaceError("write preparation byte count is out of range")
    elif request.artifact_id is None or request.byte_count is not None:
        raise ProbeWorkspaceError("cleanup preparation requires artifact identity only")
    return ProbePrepareRequest(
        operation=request.operation,
        relative_path=relative_path,
        content_sha256=digest,
        byte_count=request.byte_count,
        artifact_id=(
            None
            if request.artifact_id is None
            else validate_probe_identifier(request.artifact_id, name="artifact_id")
        ),
    )


__all__ = [
    "ProbeCleanupRequest",
    "ProbeExecution",
    "ProbeOperationAuthoriser",
    "ProbeOperationBoundaryVerifier",
    "ProbePreparation",
    "ProbePrepareRequest",
    "ProbePreparedStateVerifier",
    "ProbeWorkspaceService",
    "ProbeWriteRequest",
]
