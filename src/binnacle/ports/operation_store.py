"""Authoritative durable operation storage boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from binnacle.domain.idempotency import IdempotencyKey, IdempotencyOutcome
from binnacle.domain.operation import (
    EffectKnowledge,
    OperationIntent,
    OperationOwner,
    OperationSnapshot,
    TransitionRequest,
)
from binnacle.domain.policy import PolicyDecision
from binnacle.domain.trusted_time import DeadlineStatus, TrustedTimeEvidence


@dataclass(frozen=True, slots=True)
class CreateOrFindRequest:
    key: IdempotencyKey
    owner: OperationOwner
    intent: OperationIntent
    tool_name: str
    contract_version: str
    prepared_operation_id: str | None = None
    prepared_input_sha256: str | None = None
    prepared_state_binding_sha256: str | None = None
    prepared_deadline_status: DeadlineStatus | None = None
    verified_prepared_state_binding_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CreateOrFindResult:
    outcome: IdempotencyOutcome
    operation: OperationSnapshot | None


@dataclass(frozen=True, slots=True)
class PreparedExecutionAdmission:
    """One caller key consuming one separately registered prepared nonce."""

    caller: CreateOrFindRequest
    prepared_key: IdempotencyKey


@dataclass(frozen=True, slots=True)
class PreparedNonceRegistration:
    key: IdempotencyKey
    owner: OperationOwner
    device_id: str
    device_epoch: int
    tool_name: str
    contract_version: str
    request_fingerprint_sha256: str
    prepared_operation_id: str
    prepared_input_sha256: str
    prepared_expires_at: datetime
    prepared_state_binding_sha256: str
    registered_boot_id_digest: str
    monotonic_deadline_ns: int
    target_identity_sha256: str | None = None
    maximum_effect_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedExecutionRecord:
    """Authoritative retained facts needed for application-layer revalidation."""

    prepared_operation_id: str
    prepared_expires_at: datetime
    prepared_state_binding_sha256: str
    registered_boot_id_digest: str
    monotonic_deadline_ns: int


@dataclass(frozen=True, slots=True)
class ReconciliationCursor:
    created_at: datetime
    operation_id: str


class OperationStore(Protocol):
    async def find_existing(self, request: CreateOrFindRequest) -> CreateOrFindResult | None: ...

    async def create_or_find(self, request: CreateOrFindRequest) -> CreateOrFindResult: ...

    async def create_or_find_prepared(
        self, request: PreparedExecutionAdmission
    ) -> CreateOrFindResult: ...

    async def get_operation(self, operation_id: str) -> OperationSnapshot | None: ...

    async def transition(
        self, operation_id: str, request: TransitionRequest
    ) -> OperationSnapshot: ...

    async def record_effect_start(
        self,
        operation_id: str,
        *,
        expected_state_version: int,
        effect_knowledge: EffectKnowledge,
        effect_reference: str | None,
        effect_reference_digest: str | None,
    ) -> OperationSnapshot: ...

    async def store_policy_decision(self, decision: PolicyDecision) -> None: ...

    async def get_policy_decision(self, operation_id: str) -> PolicyDecision | None: ...

    async def register_prepared_execution_nonce(
        self, registration: PreparedNonceRegistration
    ) -> None: ...

    async def get_prepared_execution(
        self, request: CreateOrFindRequest
    ) -> PreparedExecutionRecord | None: ...

    async def get_idempotency_conflict_operation(
        self, request: CreateOrFindRequest
    ) -> OperationSnapshot | None: ...

    async def get_trusted_time_evidence(self) -> TrustedTimeEvidence: ...

    async def store_trusted_time_evidence(self, evidence: TrustedTimeEvidence) -> None: ...

    async def set_consequential_admission_enabled(self, enabled: bool) -> None: ...

    async def consequential_admission_enabled(self) -> bool: ...

    async def audit_recovery_evidence_sha256(self) -> str | None: ...

    async def list_reconcilable(
        self,
        *,
        limit: int = 100,
        after: ReconciliationCursor | None = None,
    ) -> tuple[OperationSnapshot, ...]: ...

    async def reject_received_on_restart(
        self, operation_id: str, decision: PolicyDecision
    ) -> OperationSnapshot: ...
